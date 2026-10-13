"""Explicit pinned GGUF/runtime setup. Default is offline verification, never download."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/models/meetings-generation-gguf-v1.json"
DEFAULT_ROOT = ROOT / "models/meetings-gguf-v1"
MAX_UNPACKED = 4 * 1024**3


def linked(path: Path) -> bool:
    """Python 3.11-compatible Windows junction/reparse-point rejection."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0)
                                            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024))


def digest(path: Path) -> dict:
    """Read current bytes; receipts never substitute for actual file verification."""
    if linked(path) or not path.is_file():
        raise ValueError("missing_or_linked_artifact")
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return {"size_bytes": path.stat().st_size, "sha256": sha.hexdigest()}


def verify_file(path: Path, spec: dict) -> dict:
    actual = digest(path)
    if any(actual[key] != spec[key] for key in ("size_bytes", "sha256")):
        raise ValueError("artifact_digest_mismatch")
    return actual


def safe_member(name: str) -> Path:
    """Reject Windows aliases/ADS/devices as well as ZIP traversal on every OS."""
    parts = PurePosixPath(name).parts
    if not parts or name.startswith("/") or "\\" in name:
        raise ValueError("unsafe_archive_path")
    for part in parts:
        if part in (".", "..") or any(c in part for c in ':<>"|?*'):
            raise ValueError("unsafe_archive_path")
        if part.endswith((" ", ".")) or any(ord(c) < 32 for c in part):
            raise ValueError("unsafe_archive_path")
        if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", part.split(".")[0]):
            raise ValueError("unsafe_archive_path")
    return Path(*parts)


def download(spec: dict, directory: Path, *, allow_download: bool) -> Path:
    filename = safe_member(spec["filename"])
    if len(filename.parts) != 1:
        raise ValueError("invalid_artifact_filename")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    if target.exists() or target.is_symlink():
        verify_file(target, spec)
        return target
    if not allow_download:
        raise ValueError("artifact_missing_run_with_download")
    if not spec["url"].startswith("https://"):
        raise ValueError("https_required")
    fd, temporary_name = tempfile.mkstemp(prefix=".download-", dir=directory)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output:
            request = urllib.request.Request(spec["url"], headers={"User-Agent": "DocTrail-setup/1"})
            with urllib.request.urlopen(request, timeout=60) as response:
                if not response.geturl().startswith("https://"):
                    raise ValueError("https_required")
                received = 0
                while block := response.read(1024 * 1024):
                    received += len(block)
                    if received > spec["size_bytes"]:
                        raise ValueError("artifact_size_exceeded")
                    output.write(block)
            output.flush()
            os.fsync(output.fileno())
        verify_file(temporary, spec)
        # Hard-link publication is atomic and cannot overwrite another setup's result.
        try:
            os.link(temporary, target)
        except FileExistsError:
            verify_file(target, spec)
        return target
    finally:
        temporary.unlink(missing_ok=True)


def inventory(directory: Path) -> dict:
    result = {}
    for path in sorted(directory.rglob("*")):
        if linked(path):
            raise ValueError("linked_runtime_file")
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = digest(path)
    return result


def extract_runtime(archives: list[Path], target: Path) -> dict:
    """Stage and validate both archives together; never overwrite existing binaries."""
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".runtime-", dir=target.parent))
    try:
        total = 0
        names = set()
        for archive in archives:
            with zipfile.ZipFile(archive) as zipped:
                for member in zipped.infolist():
                    relative = safe_member(member.orig_filename)
                    mode = member.external_attr >> 16
                    if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG,
                                                                                  stat.S_IFDIR)):
                        raise ValueError("unsupported_archive_entry")
                    if member.is_dir():
                        (stage / relative).mkdir(parents=True, exist_ok=True)
                        continue
                    key = relative.as_posix().casefold()
                    if key in names:
                        raise ValueError("duplicate_archive_path")
                    names.add(key)
                    total += member.file_size
                    if total > MAX_UNPACKED:
                        raise ValueError("archive_size_exceeded")
                    destination = stage / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with zipped.open(member) as source, destination.open("xb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
        expected = inventory(stage)
        servers = [name for name in expected if Path(name).name == "llama-server.exe"]
        if len(servers) != 1:
            raise ValueError("runtime_server_missing_or_ambiguous")
        if target.exists() or target.is_symlink():
            if linked(target) or inventory(target) != expected:
                raise ValueError("existing_runtime_mismatch")
        else:
            stage.rename(target)
        return expected
    finally:
        if stage.exists():
            if (linked(stage) or stage.resolve().parent != target.parent.resolve()
                    or not stage.name.startswith(".runtime-")):
                raise ValueError("unsafe_stage_cleanup")
            shutil.rmtree(stage)


def prepare(manifest_path: Path = MANIFEST, root: Path = DEFAULT_ROOT,
            *, allow_download: bool = False) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported_manifest")
    # All outputs are under a Git-ignored model directory by default. Do not embed user paths.
    if linked(root):
        raise ValueError("linked_setup_root")
    root.mkdir(parents=True, exist_ok=True)
    for child in ("downloads", "licenses", "runtime"):
        path = root / child
        if linked(path):
            raise ValueError("linked_setup_directory")
    model = download(manifest["gguf"], root, allow_download=allow_download)
    archives = [download(spec, root / "downloads", allow_download=allow_download)
                for spec in manifest["llama"]["assets"]]
    licenses = [download(spec, root / "licenses", allow_download=allow_download)
                for spec in manifest["licenses"]]
    runtime = extract_runtime(archives, root / "runtime")
    receipt = {
        "schema_version": 1,
        "manifest_sha256": digest(manifest_path)["sha256"],
        "model": {"path": model.relative_to(root).as_posix(), **digest(model)},
        "runtime_files": runtime,
        "server_path": "runtime/" + next(n for n in runtime if Path(n).name == "llama-server.exe"),
        "licenses": {p.relative_to(root).as_posix(): digest(p) for p in licenses},
        "quality_verified": False,
    }
    receipt_path = root / "setup-receipt.json"
    if linked(receipt_path):
        raise ValueError("linked_setup_receipt")
    if receipt_path.exists():
        if json.loads(receipt_path.read_text(encoding="utf-8")) != receipt:
            raise ValueError("existing_receipt_mismatch")
    else:
        with receipt_path.open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2)
            stream.write("\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--download", action="store_true", help="explicitly fetch pinned artifacts")
    args = parser.parse_args()
    try:
        receipt = prepare(args.manifest, args.root, allow_download=args.download)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        parser.exit(1, "meeting_gguf_setup_failed_existing_files_preserved\n")
    print(json.dumps({"verified": True, "runtime_files": len(receipt["runtime_files"]),
                      "quality_verified": False}))


if __name__ == "__main__":
    main()
