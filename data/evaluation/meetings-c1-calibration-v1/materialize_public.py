"""One-time registered source materialization, before question authoring.

Download only the four registered raw URLs. Verify all identities and rights
notices before writing source bytes. Never import a model or tokenizer.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
REGISTRY = REPO / "data/evaluation/meetings-c1-calibration-family-registry-v1.json"
FREEZE = REPO / "data/evaluation/meetings-c1-source-freeze-v1.json"
COMMIT = "82b0fff79761c0da86f4d8c5614aa20f9b12e7e5"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode())


def main():
    assert not (ROOT / "cases.json").exists(), "Do not rematerialize after question authoring"
    registry = json.loads(REGISTRY.read_bytes())
    frozen = json.loads(FREEZE.read_bytes())
    assert len(frozen["bound_files"]) == 46
    for path, expected in frozen["bound_files"].items():
        assert sha((REPO / path).read_bytes()) == expected, path
    assert sha(REGISTRY.read_bytes()) == "aacd0a4723160515c09fae355407face498a72d26479a5a5a62cc5375851961a"
    assert sha(FREEZE.read_bytes()) == "5d536cbbdfdb83a7063bbce93e16da067277bcfbc7ae21ed9326f53e4ab38c6f"
    prepared = []
    for src in registry["approved_public_sources"]:
        data = urlopen(src["download_url"], timeout=30).read()
        assert len(data) == src["raw_bytes"]
        assert sha(data) == src["raw_sha256"]
        assert hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest() == src["git_blob_sha1"]
        text = data.decode("utf-8")
        assert "\r" not in text
        normalized = " ".join(text.split())
        assert src["license"]["statement"] in normalized
        assert "Copyright\n" in text
        prepared.append((src, data))
    # All four identities and rights notices have passed before first source write.
    records = []
    for src, data in prepared:
        target = REPO / src["planned_raw_path"]
        assert target.is_relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        text = data.decode("utf-8")
        start = text.index("Copyright\n")
        # Keep the whole copyright section up to the next blank section boundary
        # as well as the complete original raw file. Later source metadata binds it.
        remainder = text[start:]
        lines = remainder.splitlines(keepends=True)
        end = len(remainder)
        for i in range(3, len(lines) - 1):
            if lines[i].strip() and len(set(lines[i + 1].strip())) == 1 and lines[i + 1].strip()[0:1] in {"=", "-"} and len(lines[i + 1].strip()) >= 3:
                end = sum(map(len, lines[:i]))
                break
        notice = remainder[:end]
        notice_path = f"licenses/{src['source_id']}.copyright.rst"
        (ROOT / "licenses").mkdir(exist_ok=True)
        (ROOT / notice_path).write_bytes(notice.encode())
        records.append({"source_id": src["source_id"], "raw_path": target.relative_to(ROOT).as_posix(),
                        "raw_sha256": sha(data), "raw_bytes": len(data),
                        "git_blob_sha1": src["git_blob_sha1"], "license_path": notice_path,
                        "license_sha256": sha(notice.encode()), "license_start_offset": start,
                        "license_end_offset": start + len(notice), "license_verified": True})
    write_json(ROOT / "source-integrity.json", {
        "schema_version": 1, "record_type": "pre_question_source_integrity",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_commit": COMMIT, "source_freeze_sha256": sha(FREEZE.read_bytes()),
        "source_registry_sha256": sha(REGISTRY.read_bytes()), "source_freeze_files_verified": 46,
        "public_sources": records, "questions_authored_at_materialization": 0,
        "oracles_authored_at_materialization": 0, "model_calls": 0, "tokenizer_calls": 0})
    print(json.dumps({"source_freeze_verified": 46, "public_sources_materialized": len(records),
                      "license_notices_verified": len(records), "model_calls": 0}))


if __name__ == "__main__":
    main()
