"""Download the pinned, openly licensed pilot corpus; no paid services."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/manifests/kubernetes-pilot.json"


def download(url: str) -> bytes:
    for attempt in range(3):
        try:
            with urlopen(
                Request(url, headers={"User-Agent": "DocTrail-research/0.1"}), timeout=30
            ) as response:
                return response.read(5 * 1024 * 1024 + 1)
        except OSError:
            if attempt == 2:
                raise
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError("download failed")


def normalize_markdown(raw: bytes) -> str:
    """v2: preserve tooltip labels; flag unresolved includes separately in provenance."""
    text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

    def tooltip(match: re.Match) -> str:
        attributes = dict(re.findall(r'(\w+)="([^"]*)"', match.group(0)))
        return attributes.get("text", attributes.get("term_id", ""))

    text = re.sub(r"\{\{[<%]\s*glossary_tooltip\b.*?[%>]\}\}", tooltip, text, flags=re.DOTALL)
    text = re.sub(r"\{\{[<%].*?[%>]\}\}", "", text, flags=re.DOTALL)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def verified_processed(row: dict, root: Path = ROOT) -> bytes:
    raw = (root / f"data/raw/kubernetes-pilot/{row['id']}.md").read_bytes()
    if hashlib.sha256(raw).hexdigest() != row["sha256"]:
        raise ValueError(f"raw checksum mismatch: {row['id']}")
    processed = (root / f"data/processed/kubernetes-pilot/{row['id']}.md").read_bytes()
    if processed != normalize_markdown(raw).encode("utf-8"):
        raise ValueError(f"processed corpus drift: {row['id']}; rerun prepare_pilot.py")
    return processed


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    raw_dir = ROOT / "data/raw/kubernetes-pilot"
    processed_dir = ROOT / "data/processed/kubernetes-pilot"
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for row in manifest["documents"]:
        raw_path = raw_dir / f"{row['id']}.md"
        raw = raw_path.read_bytes() if raw_path.exists() else download(row["download_url"])
        if len(raw) > 5 * 1024 * 1024:
            raise ValueError(f"source too large: {row['id']}")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != row["sha256"]:
            raise ValueError(f"checksum mismatch: {row['id']}; do not silently replace snapshot")
        raw_path.write_bytes(raw)
        text = normalize_markdown(raw)
        (processed_dir / f"{row['id']}.md").write_text(text, encoding="utf-8", newline="\n")
        unresolved = re.findall(
            r"\{\{[<%]\s*(glossary_definition|include|code_sample)\b", raw.decode("utf-8-sig")
        )
        records.append(
            {
                **row,
                "processed_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "characters": len(text),
                "normalizer": "hugo-light-v2",
                "unresolved_content_shortcodes": unresolved,
                "human_review": "pending",
            }
        )
    (processed_dir / "provenance.json").write_text(
        json.dumps(
            {"license": manifest["license"], "documents": records}, ensure_ascii=False, indent=2
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "documents": len(records),
                "normalizer": "hugo-light-v2",
                "status": "checksum-verified",
            }
        )
    )


if __name__ == "__main__":
    main()
