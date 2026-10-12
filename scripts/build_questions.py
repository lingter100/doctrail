"""Resolve AI-authored draft quotes against frozen documents; never invent review."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from scripts.question_dataset import CATEGORIES, digest_file, validate_questions

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/manifests/kubernetes-v1.json"
JOBS = ROOT / "data/evaluation/generation/jobs.json"
PROTOCOL = ROOT / "data/evaluation/generation/protocol.md"


def compile_questions(
    draft: dict, job: dict, corpus: list[dict], manifest_hash: str, prompt_hash: str
) -> list[dict]:
    if draft["job_id"] != job["id"]:
        raise ValueError("Draft/job identity mismatch")
    documents = {row["id"]: row for row in corpus}
    allowed = set(job["allowed_document_ids"])
    rows = []
    for source in draft["questions"]:
        if not source["id"].startswith(job["id"] + "-"):
            raise ValueError("Question ID must include its author job namespace")
        evidence = []
        for item in source["evidence"]:
            if item["document_id"] not in allowed:
                raise ValueError("Question source outside assigned family pack")
            doc = documents[item["document_id"]]
            if doc["split"] != job["split"]:
                raise ValueError("Question source crosses split")
            quote = item["quote"]
            content = doc["content"]
            if "start_offset" in item:
                start = item["start_offset"]
                if (
                    type(start) is not int
                    or start < 0
                    or content[start : start + len(quote)] != quote
                ):
                    raise ValueError("Authored explicit offset does not match source")
            else:
                if content.count(quote) != 1:
                    raise ValueError(f"Quote must match uniquely: {source['id']}, {doc['id']}")
                start = content.index(quote)
            evidence.append(
                {
                    **item,
                    "grade": item.get("grade", 2),
                    "start_offset": start,
                    "end_offset": start + len(quote),
                }
            )
        row = {
            **source,
            "schema_version": 2,
            "split": job["split"],
            "answerability": CATEGORIES[source["category"]],
            "created_by": "ai",
            "generator_model": job["model"],
            "generator_reasoning_effort": job["reasoning_effort"],
            "generation_prompt_sha256": prompt_hash,
            "generation_job_id": job["id"],
            "human_review": "pending",
            "human_reviewer": None,
            "human_reviewed_at": None,
            "evidence": evidence,
            "relevant_document_ids": sorted(
                {item["document_id"] for item in evidence if item["grade"] == 2}
            ),
        }
        if row["answerability"] != "answerable":
            row["intended_corpus_scope"] = {
                "manifest_sha256": manifest_hash,
                "definition": "all_manifest_documents",
            }
        rows.append(row)
    validate_questions(rows, corpus, allowed_split=job["split"], manifest_sha256=manifest_hash)
    for field, quota_key in (("category", "category_targets"), ("language", "language_targets")):
        if dict(Counter(row[field] for row in rows)) != job[quota_key]:
            raise ValueError(
                f"Actual {field} counts differ from the job contract; report quality shortfalls before adjusting the contract"
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True)
    args = parser.parse_args()
    registry = json.loads(JOBS.read_text(encoding="utf-8"))
    job = next(row for row in registry["jobs"] if row["id"] == args.job)
    manifest_hash = digest_file(MANIFEST)
    if registry["manifest_sha256"] != manifest_hash or registry["protocol_sha256"] != digest_file(
        PROTOCOL
    ):
        raise SystemExit("Frozen generation inputs changed; do not silently rebuild labels")
    from scripts.prepare_corpus import load_verified_corpus

    corpus = load_verified_corpus(MANIFEST)
    draft = json.loads((ROOT / job["draft_path"]).read_text(encoding="utf-8"))
    rows = compile_questions(draft, job, corpus, manifest_hash, digest_file(PROTOCOL))
    output = ROOT / job["output_path"]
    output.parent.mkdir(parents=True, exist_ok=True)
    rendered = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    if output.exists() and output.read_text(encoding="utf-8") != rendered:
        raise SystemExit("Question set already frozen; write a new explicit dataset version")
    output.write_text(rendered, encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "job": job["id"],
                "questions": len(rows),
                "output_sha256": digest_file(output),
                "human_reviewed": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
