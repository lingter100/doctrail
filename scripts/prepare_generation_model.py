"""Explicit pinned download, or network-free verification, of the M5 snapshot."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

from doctrail.generation_runtime import (
    DEFAULT_MANIFEST,
    GenerationError,
    file_sha256,
    load_generation_manifest,
    safe_path,
    verify_snapshot,
)

DOWNLOAD_PROGRESS_BYTES = 64 * 1024 * 1024


def prepare_snapshot(snapshot: Path, manifest_path: Path = DEFAULT_MANIFEST,
                     *, download: bool = False,
                     progress: Callable[[dict[str, str | int]], None] | None = None) -> dict:
    """Report transfer bytes, not verification success, through an optional callback.

    Progress contains only an allowlisted filename and byte counts. Existing
    verified files and network-free verification do not emit download progress.
    """
    manifest = load_generation_manifest(manifest_path)
    spec = manifest["model"]
    destination = safe_path(snapshot)
    if download:
        destination.mkdir(parents=True, exist_ok=True)
        safe_path(destination)
        allowed = set(spec["files"])
        if any(entry.name not in allowed for entry in destination.iterdir()):
            raise GenerationError("unexpected_model_snapshot_file")
        for name, expected in spec["files"].items():
            target = safe_path(destination / name)
            if target.exists():
                if (not target.is_file() or target.stat().st_nlink != 1
                        or target.stat().st_size != expected["size_bytes"]
                        or file_sha256(target) != expected["sha256"]):
                    raise GenerationError("existing_model_file_mismatch")
                continue
            # Staging is adjacent, never part of the accepted snapshot. Exclusive
            # create refuses pre-existing partial files and linked staging paths.
            temporary = safe_path(destination.parent / f".{destination.name}.{name}.partial")
            url = f"https://huggingface.co/{spec['repo_id']}/resolve/{spec['revision']}/{name}"
            request = urllib.request.Request(url, headers={"User-Agent": "DocTrail-M5/1.0"})
            created = False
            try:
                with temporary.open("xb") as output:
                    created = True
                    with urllib.request.urlopen(request, timeout=120) as response:
                        if not response.url.startswith("https://"):
                            raise GenerationError("unsafe_model_download_redirect")
                        size = 0
                        next_progress = DOWNLOAD_PROGRESS_BYTES
                        last_reported = -1
                        while block := response.read(1024 * 1024):
                            size += len(block)
                            if size > expected["size_bytes"]:
                                raise GenerationError("model_download_size_exceeded")
                            output.write(block)
                            if progress is not None and size >= next_progress:
                                progress({"filename": name, "downloaded_bytes": size,
                                          "expected_bytes": expected["size_bytes"]})
                                last_reported = size
                                next_progress = (
                                    size // DOWNLOAD_PROGRESS_BYTES + 1
                                ) * DOWNLOAD_PROGRESS_BYTES
                if progress is not None and size != last_reported:
                    progress({"filename": name, "downloaded_bytes": size,
                              "expected_bytes": expected["size_bytes"]})
                if temporary.stat().st_size != expected["size_bytes"]:
                    raise GenerationError("model_download_size_mismatch")
                if file_sha256(temporary) != expected["sha256"]:
                    raise GenerationError("model_download_hash_mismatch")
                safe_path(target)
                if target.exists():
                    raise GenerationError("model_destination_changed")
                temporary.rename(target)
            finally:
                if created:
                    temporary.unlink(missing_ok=True)
    hashes = verify_snapshot(destination, spec)
    return {"repo_id": spec["repo_id"], "revision": spec["revision"], "files": hashes,
            "verified": True, "download_requested": download}


def _print_progress(event: dict[str, str | int]) -> None:
    print(json.dumps(event, sort_keys=True), file=sys.stderr, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--download", action="store_true", help="Explicitly permit HTTPS download")
    args = parser.parse_args()
    try:
        receipt = prepare_snapshot(args.snapshot, args.manifest, download=args.download,
                                   progress=_print_progress)
    except GenerationError as error:
        print(json.dumps({"status": "failed", "error_code": error.code}))
        return 1
    except Exception:  # noqa: BLE001 - CLI emits safe codes instead of URLs/local paths
        print(json.dumps({"status": "failed", "error_code": "generation_prepare_failed"}))
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
