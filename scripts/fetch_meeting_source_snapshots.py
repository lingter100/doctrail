"""Restore pinned public source bytes for an already adopted meeting manifest.

No question authoring, source normalization, tokenization or inference occurs.
Validation manifests belong to the isolated custodian. Existing bytes are never
overwritten. Network access requires --download; --verify-remote also checks
existing snapshots. LICENSE/NOTICE copies remain in the committed split folder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 5 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024


class FetchError(ValueError):
    """Safe code only: never remote text, question text or an exception repr."""


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def contained(name, *, local_only=False):
    path = Path(name)
    root = ROOT.resolve()
    absolute = path if path.is_absolute() else root / path
    if ".." in absolute.parts or not absolute.is_relative_to(root):
        raise FetchError("snapshot_path_outside_repository")
    current = root
    for part in absolute.relative_to(root).parts:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if current.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise FetchError("snapshot_linked_path")
    resolved = absolute.resolve()
    if (not resolved.is_relative_to(root)
            or local_only and (not resolved.is_relative_to(root / ".local")
                               or resolved == root / ".local")):
        raise FetchError("snapshot_invalid_local_path")
    return resolved


def read_bounded(path, limit):
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise FetchError("snapshot_file_limit")
    return raw


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "snapshot_redirect_rejected", headers, fp)


def download_bytes(url, limit):
    request = Request(url, headers={"User-Agent": "DocTrail-pinned-source-replay/1"})
    with build_opener(NoRedirect).open(request, timeout=30) as response:
        if response.status != 200 or response.geturl() != url:
            raise FetchError("snapshot_remote_status")
        length = response.headers.get("Content-Length")
        if length is not None and (not length.isdigit() or int(length) > limit):
            raise FetchError("snapshot_remote_size")
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise FetchError("snapshot_remote_size")
        return raw


def verify(raw, source):
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
    if (len(raw) != source["raw_size_bytes"] or sha(raw) != source["raw_sha256"]
            or blob != source["git_blob_sha1"]):
        raise FetchError("snapshot_bytes_mismatch")


def registered_sources(manifest, phase):
    if (type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1
            or phase not in {"calibration", "validation"} or manifest.get("phase") != phase
            or not isinstance(manifest.get("families"), list)):
        raise FetchError("snapshot_manifest_contract")
    rows, ids, targets = [], set(), set()
    for family in manifest["families"]:
        if family.get("origin") == "synthetic":
            continue
        if (family.get("origin") != "public"
                or family.get("source_suitability", {}).get("verdict") != "ADOPTED"
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*",
                                    family.get("repository", ""))
                or not re.fullmatch(r"[a-f0-9]{40}", family.get("immutable_commit", ""))
                or not isinstance(family.get("sources"), list) or not family["sources"]):
            raise FetchError("snapshot_public_family_contract")
        for source in family["sources"]:
            identity, name = source.get("source_id"), source.get("path")
            target_name = source.get("local_raw_snapshot")
            if (not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", identity)
                    or identity in ids or not isinstance(name, str) or not name
                    or name.startswith("/") or "\\" in name or ":" in name
                    or any(p in {"", ".", ".."} for p in name.split("/"))
                    or not isinstance(target_name, str) or "\\" in target_name or ":" in target_name
                    or any(p in {"", ".", ".."} for p in target_name.split("/"))
                    or PurePosixPath(target_name).is_absolute()
                    or source.get("adoption_verdict") !=
                    f"ADOPTED_FOR_{phase.upper()}_SOURCE_WITH_REGISTERED_CONSTRAINTS"
                    or type(source.get("raw_size_bytes")) is not int
                    or not 0 < source["raw_size_bytes"] <= MAX_BYTES
                    or not re.fullmatch(r"[a-f0-9]{64}", source.get("raw_sha256", ""))
                    or not re.fullmatch(r"[a-f0-9]{40}", source.get("git_blob_sha1", ""))):
                raise FetchError("snapshot_source_contract")
            url = (f"https://raw.githubusercontent.com/{family['repository']}/"
                   f"{family['immutable_commit']}/{quote(name, safe='/-._~')}")
            if source.get("raw_url") != url:
                raise FetchError("snapshot_unpinned_url")
            target = contained(target_name, local_only=True)
            if any(target == p or target.is_relative_to(p) or p.is_relative_to(target) for p in targets):
                raise FetchError("snapshot_duplicate_target")
            ids.add(identity)
            targets.add(target)
            rows.append((source, target, url))
    if not 0 < len(rows) <= 16:
        raise FetchError("snapshot_source_count")
    return rows


def restore(manifest_path, output, phase, *, download=False, verify_remote=False, fetcher=None):
    if verify_remote and not download:
        raise FetchError("snapshot_download_not_authorized")
    manifest_path, output = contained(manifest_path), contained(output, local_only=True)
    if output.exists():
        raise FetchError("snapshot_output_exists")
    raw = read_bounded(manifest_path, MAX_MANIFEST_BYTES)
    # strict_json rejects duplicate keys, non-finite values and extra JSON values.
    from doctrail.meeting_contract import strict_json
    manifest = strict_json(raw.decode("utf-8"))
    rows = registered_sources(manifest, phase)
    protected = [manifest_path, *(target for _, target, _ in rows)]
    if any(p == output or p.is_relative_to(output) or output.is_relative_to(p) for p in protected):
        raise FetchError("snapshot_output_collision")
    # Validate every existing file before a network request or writing any file.
    for source, target, _ in rows:
        if target.exists():
            verify(read_bounded(target, MAX_BYTES), source)
        elif not download:
            raise FetchError("snapshot_missing_download_disabled")
    output.mkdir(parents=True, exist_ok=False)
    result = {"schema_version": 1, "kind": "pinned_public_source_snapshot_replay", "phase": phase,
        "created_at": datetime.now(UTC).isoformat(), "manifest_sha256": sha(raw),
        "script_sha256": sha(Path(__file__).read_bytes()), "download_authorized": download,
        "verify_remote": verify_remote, "network_attempts": 0, "sources": [],
        "model_calls": 0, "source_normalization": False, "status": "failed"}
    error = None
    try:
        for source, target, url in rows:
            target = contained(target, local_only=True)
            existed = target.exists()
            if existed:
                verify(read_bounded(target, MAX_BYTES), source)
            if not existed or verify_remote:
                if not download:
                    raise FetchError("snapshot_download_not_authorized")
                result["network_attempts"] += 1
                fetched = (fetcher or download_bytes)(url, source["raw_size_bytes"])
                verify(fetched, source)
                if read_bounded(manifest_path, MAX_MANIFEST_BYTES) != raw:
                    raise FetchError("snapshot_manifest_changed")
                if not existed:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target = contained(target, local_only=True)
                    with target.open("xb") as stream:
                        stream.write(fetched)
            verify(read_bounded(contained(target), MAX_BYTES), source)
            result["sources"].append({"source_id": source["source_id"], "url": url,
                "target": target.relative_to(ROOT.resolve()).as_posix(),
                "raw_sha256": source["raw_sha256"], "git_blob_sha1": source["git_blob_sha1"],
                "raw_size_bytes": source["raw_size_bytes"], "created": not existed,
                "remote_checked": not existed or verify_remote})
        if read_bounded(manifest_path, MAX_MANIFEST_BYTES) != raw:
            raise FetchError("snapshot_manifest_changed")
        result["status"] = "passed"
    except Exception as exc:  # noqa: BLE001 - deliberately redact remote/error bodies
        error = exc if isinstance(exc, FetchError) else FetchError("snapshot_fetch_or_io_failed")
        result["error_code"] = str(error)
    with (contained(output) / "receipt.json").open("xb") as stream:
        stream.write((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
    if error:
        raise error from None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("calibration", "validation"), required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--verify-remote", action="store_true")
    args = parser.parse_args()
    try:
        result = restore(args.manifest, args.output, args.phase, download=args.download,
                         verify_remote=args.verify_remote)
    except Exception:  # noqa: BLE001
        parser.exit(1, "source_snapshot_replay_failed\n")
    print(json.dumps({"status": result["status"], "sources": len(result["sources"]),
                      "network_attempts": result["network_attempts"], "model_calls": 0}))


if __name__ == "__main__":
    main()
