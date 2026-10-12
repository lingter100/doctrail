"""Fail closed on document-family/exact-duplicate/query evidence split leakage."""

import argparse
import json
from pathlib import Path


def validate(documents: list[dict], questions: list[dict]) -> dict:
    ids = {}
    families = {}
    hashes = {}
    allowed = {"train", "dev", "test", "smoke"}
    for row in documents:
        if row["id"] in ids:
            raise ValueError("duplicate document id")
        if row["split"] not in allowed:
            raise ValueError("unknown split")
        ids[row["id"]] = row
        for mapping, key in ((families, row["family_id"]), (hashes, row["sha256"])):
            previous = mapping.setdefault(key, row["split"])
            if previous != row["split"]:
                raise ValueError("document family or exact duplicate crosses splits")
    seen_questions = set()
    seen_texts = {}
    for row in questions:
        if row["id"] in seen_questions:
            raise ValueError("duplicate question id")
        seen_questions.add(row["id"])
        normalized = " ".join(row["query"].casefold().split())
        if seen_texts.setdefault(normalized, row["split"]) != row["split"]:
            raise ValueError("duplicate question crosses splits")
        if row["split"] not in allowed:
            raise ValueError("unknown question split")
        for doc_id in row["relevant_document_ids"]:
            if doc_id not in ids or ids[doc_id]["split"] != row["split"]:
                raise ValueError("question evidence missing or crosses splits")
        evidence = row.get("evidence", [])
        for item in evidence:
            doc_id = item["document_id"]
            if (
                doc_id not in ids
                or ids[doc_id]["split"] != row["split"]
                or (doc_id not in row["relevant_document_ids"] and item.get("grade") != 1)
            ):
                raise ValueError("evidence annotation missing, irrelevant or crosses splits")
        if row.get("category") == "no_evidence" and (evidence or row["relevant_document_ids"]):
            raise ValueError("no_evidence question cannot have evidence")
        if row.get("category") in {"single_document", "multi_document"} and (
            not evidence or not row["relevant_document_ids"]
        ):
            raise ValueError("answerable question requires evidence")
        if row.get("human_review") == "approved" and not row.get("human_reviewer"):
            raise ValueError("human approval requires reviewer provenance")
    return {
        "documents": len(ids),
        "questions": len(questions),
        "checks": "passed",
        "limitations": "Near-duplicate/topic/version group assignment must be prepared upstream.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("questions", type=Path)
    args = parser.parse_args()
    docs = json.loads(args.manifest.read_text(encoding="utf-8"))["documents"]
    rows = [
        json.loads(line)
        for line in args.questions.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(json.dumps(validate(docs, rows), ensure_ascii=False))
