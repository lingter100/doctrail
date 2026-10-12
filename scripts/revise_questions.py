"""Replay an explicit development-set exclusion before scoring, preserving the original."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.question_dataset import digest_file, read_questions, validate_questions

ROOT = Path(__file__).resolve().parents[1]


def apply_exclusions(rows: list[dict], revision: dict) -> list[dict]:
    if revision.get("schema_version") != 1 or revision.get("decision_actor") != "ai":
        raise ValueError("This revision contract records AI exclusions only, not human review")
    if not rows or any(row["split"] != "dev" for row in rows):
        raise ValueError("M2 revision pipeline is development-only")
    ids = {row["id"] for row in rows}
    excluded = revision.get("excluded_questions", [])
    excluded_ids = [item["id"] for item in excluded]
    if (
        not excluded_ids
        or len(set(excluded_ids)) != len(excluded_ids)
        or not set(excluded_ids) < ids
        or any(len(item.get("reason", "").strip()) < 30 for item in excluded)
    ):
        raise ValueError("Exclusions must be a non-empty, explained, unique proper subset")
    return [row for row in rows if row["id"] not in excluded_ids]


def relative_data_file(value: str) -> Path:
    candidate = (ROOT / value).resolve()
    if not candidate.is_relative_to(ROOT / "data/evaluation"):
        raise ValueError("Revision paths must remain inside data/evaluation")
    return candidate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", type=Path, required=True)
    args = parser.parse_args()
    revision = json.loads(args.revision.read_text(encoding="utf-8"))
    source = relative_data_file(revision["base_question_file"])
    output = relative_data_file(revision["output_question_file"])
    manifest = ROOT / "data/manifests/kubernetes-v1.json"
    if (
        digest_file(source) != revision["base_question_sha256"]
        or digest_file(manifest) != revision["manifest_sha256"]
    ):
        raise ValueError("Revision base question set or corpus changed")
    rows = apply_exclusions(read_questions(source), revision)
    from scripts.prepare_corpus import load_verified_corpus

    validation = validate_questions(
        rows,
        load_verified_corpus(manifest),
        allowed_split="dev",
        manifest_sha256=digest_file(manifest),
    )
    result = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    if output.exists():
        if output.read_text(encoding="utf-8") != result:
            raise ValueError("Refusing to overwrite a different revised question set")
    else:
        with output.open("x", encoding="utf-8", newline="\n") as file:
            file.write(result)
    print(
        json.dumps(
            {
                "questions": validation["questions"],
                "excluded": len(revision["excluded_questions"]),
                "output_sha256": digest_file(output),
                "human_reviewed": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
