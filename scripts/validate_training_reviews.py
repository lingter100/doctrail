"""Verify immutable independent AI review receipts; never authorize training."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from scripts.prepare_training import json_bytes, sha256, write_or_verify

# Pilot role assignments, made before independent review. Authors cannot self-review.
ROLES = {
    "fit": {"author": "train_author", "reviewer": "train_design"},
    "calibration": {"author": "train_design", "reviewer": "cal_review"},
}


def question_hash(row: dict) -> str:
    return sha256(json.dumps(row, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode())


def validate_reviews(drafts: list[dict], reviews: list[dict], packs: dict[str, dict]) -> dict:
    questions = {row["id"]: row for row in drafts}
    if not drafts or len(questions) != len(drafts):
        raise ValueError("Empty or duplicate draft IDs")
    events = {row["question_id"]: row for row in reviews}
    if len(events) != len(reviews) or set(events) != set(questions):
        raise ValueError("Review IDs must cover each draft exactly once")
    for digest, pack in packs.items():
        if sha256(json_bytes(pack)) != digest:
            raise ValueError("Author pack checksum mismatch")
        for doc in pack["documents"]:
            if sha256(doc["content"].encode()) != doc["normalized_sha256"]:
                raise ValueError("Source document checksum mismatch")
    for identifier, question in questions.items():
        event = events[identifier]
        part = question["partition"]
        if part not in ROLES:
            raise ValueError("Unknown pilot partition")
        digest = question["author_pack_sha256"]
        pack = packs.get(digest)
        if pack is None or pack["partition"] != part:
            raise ValueError("Missing or wrong-partition author pack")
        docs = {doc["id"]: doc for doc in pack["documents"]}
        if len(question["evidence"]) != 1:
            raise ValueError("Pilot review requires one evidence document")
        document = docs.get(question["evidence"][0]["document_id"])
        if document is None or document["id"] not in pack["allowed_document_ids"]:
            raise ValueError("Evidence outside author pack")
        if (event.get("question_sha256") != question_hash(question)
                or event.get("author_pack_sha256") != digest
                or event.get("document_sha256") != document["normalized_sha256"]):
            raise ValueError("Review question, pack or document binding mismatch")
        if (question.get("provenance", {}).get("human_review") != "pending"
                or event.get("human_review") != "pending"):
            raise ValueError("AI receipts must preserve human review pending")
        reviewer = event.get("reviewer", {})
        expected = {"agent": ROLES[part]["reviewer"], "model": "gpt-6-astra",
                    "reasoning": "xhigh", "review_kind": "independent_ai"}
        if reviewer != expected or reviewer["agent"] == ROLES[part]["author"]:
            raise ValueError("Reviewer differs from independently assigned pilot role")
        if event.get("decision") not in {"accept", "revise", "reject"}:
            raise ValueError("Unknown semantic review decision")
        if not isinstance(event.get("reason"), str) or not event["reason"].strip():
            raise ValueError("Semantic review reason is required")
    return {
        "schema_version": 1,
        "scope": "independent_ai_semantic_review_receipt_validation",
        "role_assignments": ROLES,
        "ai_reviewed_questions": len(events),
        "human_reviewed_questions": 0,
        "decisions": dict(sorted(Counter(row["decision"] for row in reviews).items())),
        "partitions": {
            part: dict(sorted(Counter(events[q["id"]]["decision"]
                                      for q in drafts if q["partition"] == part).items()))
            for part in ROLES
        },
        "needs_revision": sorted(row["question_id"] for row in reviews
                                 if row["decision"] != "accept"),
        "all_ai_accepted": all(row["decision"] == "accept" for row in reviews),
        "training_ready": False,
        "limitations": [
            "Receipt validation checks bindings and role assignments, not semantic truth.",
            "AI acceptance is not human review or training readiness.",
            "Original drafts and their pending review fields remain immutable.",
        ],
    }


def read_rows(paths: list[Path]) -> tuple[list[dict], dict[str, str]]:
    if len({path.name for path in paths}) != len(paths):
        raise ValueError("Input filenames must be unique")
    snapshots = {path.name: path.read_bytes() for path in paths}
    return ([json.loads(line) for raw in snapshots.values() for line in
             raw.decode("utf-8").splitlines() if line.strip()],
            {name: sha256(raw) for name, raw in snapshots.items()})


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drafts", type=Path, nargs="+", required=True)
    parser.add_argument("--reviews", type=Path, nargs="+", required=True)
    parser.add_argument("--author-packs", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    drafts, draft_hashes = read_rows(args.drafts)
    reviews, review_hashes = read_rows(args.reviews)
    pack_snapshots = [path.read_bytes() for path in args.author_packs]
    packs = {sha256(raw): json.loads(raw) for raw in pack_snapshots}
    report = validate_reviews(drafts, reviews, packs)
    report.update({"draft_sha256": draft_hashes, "review_sha256": review_hashes,
                   "author_pack_sha256": sorted(packs)})
    write_or_verify(args.output, json_bytes(report), args.verify)
    print(json.dumps({key: report[key] for key in
                      ("decisions", "needs_revision", "training_ready")}))


if __name__ == "__main__":
    main()
