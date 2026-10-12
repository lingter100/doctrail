"""Download the explicitly selected, pinned, free model files for local inference.

No Python source, pickle weights, Hub login, or paid API is used. Each individual
file is atomically promoted only after its size and SHA256 match the manifest.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from doctrail.model_retrieval import (
    DEFAULT_MANIFEST,
    file_sha256,
    load_model_manifest,
    verify_snapshot,
)


def prepare_model(key: str, spec: dict, output_dir: Path) -> dict:
    destination = output_dir / key
    destination.mkdir(parents=True, exist_ok=True)
    for name, expected in spec["files"].items():
        if Path(name).name != name or not name.endswith((".json", ".safetensors")):
            raise ValueError("unsafe_model_manifest_file")
        target = destination / name
        if (
            target.is_file() and target.stat().st_size == expected["size_bytes"]
            and file_sha256(target) == expected["sha256"]
        ):
            continue
        temporary = target.with_name(target.name + ".partial")
        url = f"https://huggingface.co/{spec['repo_id']}/resolve/{spec['revision']}/{name}"
        request = urllib.request.Request(url, headers={"User-Agent": "DocTrail-M3/1.0"})
        print(f"Downloading {key}/{name}", flush=True)
        try:
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as out:
                size = 0
                while block := response.read(1024 * 1024):
                    size += len(block)
                    if size > expected["size_bytes"]:
                        raise ValueError("model_download_size_exceeded")
                    out.write(block)
            if temporary.stat().st_size != expected["size_bytes"]:
                raise ValueError("model_download_size_mismatch")
            if file_sha256(temporary) != expected["sha256"]:
                raise ValueError("model_download_hash_mismatch")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    hashes = verify_snapshot(destination, spec)
    receipt = {
        "repo_id": spec["repo_id"], "revision": spec["revision"], "files": hashes,
        "verified_at": datetime.now(UTC).isoformat(),
        "verification": "size and SHA256 checked against tracked manifest",
    }
    (destination / "verification.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=["e5", "reranker", "all"], required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("models"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    manifest = load_model_manifest(args.manifest)
    keys = ["e5", "reranker"] if args.model == "all" else [args.model]
    for key in keys:
        receipt = prepare_model(key, manifest["models"][key], args.output_dir)
        print(json.dumps({"model": key, "revision": receipt["revision"], "verified": True}))


if __name__ == "__main__":
    main()
