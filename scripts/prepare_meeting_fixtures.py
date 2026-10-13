"""Reproduce the small, licensed public meeting fixtures; never fetch during CI."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/manifests/meeting-public-v1.json"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sanitize(value: bytes) -> bytes:
    """Preserve source text except call-access/contact lines and normalize LF."""
    text = value.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line for line in text.splitlines()
             if not any(marker in line.lower() for marker in
                        ("video-conference link", "@googlegroups.com"))]
    return ("\n".join(lines) + "\n").encode("utf-8")


def verify(*, download: bool = False) -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    checked = []
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
        for source in manifest["sources"]:
            target = ROOT / source["fixture"]
            if download:
                response = client.get(source["raw_url"])
                response.raise_for_status()
                raw = response.content
                if len(raw) > 1_000_000 or digest(raw) != source["source_sha256"]:
                    raise ValueError("public_source_changed")
                value = raw if source["kind"] == "license" else sanitize(raw)
                if digest(value) != source["fixture_sha256"]:
                    raise ValueError("fixture_transformation_changed")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(value)
            value = target.read_bytes()
            if digest(value) != source["fixture_sha256"]:
                raise ValueError("fixture_changed")
            checked.append({"id": source["id"], "sha256": digest(value), "bytes": len(value)})
    return {"schema_version": 1, "origin": "real_public_documents",
            "synthetic": False, "human_review_count": 0, "files": checked}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(download=args.download), ensure_ascii=True))


if __name__ == "__main__":
    main()
