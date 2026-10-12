"""Strict, provenance-aware validation for unreviewed M2 question candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from scripts.validate_splits import validate

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = {
    "single_document": "answerable",
    "multi_document": "answerable",
    "no_evidence": "unanswerable",
    "ambiguous": "ambiguous",
}


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def row_digest(row: dict) -> str:
    return hashlib.sha256(
        json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def read_questions(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def validate_questions(
    rows: list[dict],
    corpus_rows: list[dict],
    allowed_split: str | None = None,
    manifest_sha256: str | None = None,
) -> dict:
    """Structural validation is not semantic judgment or a claim of human review.

    Full validation requires each corpus row's verified ``content``. Metadata-only
    checks are useful in CI, but their different scope is explicit in the result.
    M2 candidates remain immutable and human-pending; reviews are separate events.
    """
    if not rows:
        raise ValueError("Question set is empty")
    validate(corpus_rows, rows)
    documents = {row["id"]: row for row in corpus_rows}
    groups: dict[tuple[str, str], str] = {}
    for doc in corpus_rows:
        for field in ("normalized_sha256", "dedup_group_id"):
            if doc.get(field):
                key = (field, doc[field])
                if groups.setdefault(key, doc["split"]) != doc["split"]:
                    raise ValueError(f"{field} crosses splits")
    question_families: dict[str, str] = {}
    seen_texts: set[str] = set()
    full_content = all("content" in doc for doc in corpus_rows)
    for row in rows:
        prefix = row["id"]

        def require(condition: bool, message: str, prefix: str = prefix) -> None:
            if not condition:
                raise ValueError(f"{prefix}: {message}")

        require(row.get("schema_version") == 2, "schema_version must be 2")
        require(row["split"] in {"train", "dev", "test"}, "invalid M2 split")
        require(allowed_split is None or row["split"] == allowed_split, "unexpected split")
        require(row.get("language") in {"ko", "en"}, "unsupported language")
        query = row.get("query", "")
        require(
            isinstance(query, str) and len(query.strip()) >= 3 and len(query) <= 500,
            "invalid query",
        )
        normalized_query = " ".join(query.casefold().split())
        require(normalized_query not in seen_texts, "duplicate question text")
        seen_texts.add(normalized_query)
        family = row.get("question_family_id")
        require(isinstance(family, str) and bool(family), "question family required")
        require(
            question_families.setdefault(family, row["split"]) == row["split"],
            "question family crosses splits",
        )
        category = row.get("category")
        require(category in CATEGORIES, "unknown category")
        require(row.get("answerability") == CATEGORIES[category], "answerability mismatch")
        require(row.get("created_by") == "ai", "M2 candidates must disclose AI authorship")
        require(
            row.get("generator_model") in {"gpt-6-astra", "gpt-6.1-sol"},
            "actual generator model required",
        )
        require(
            row.get("generator_reasoning_effort") in {"high", "xhigh", "max"},
            "actual generator reasoning setting required",
        )
        require(
            bool(re.fullmatch(r"[0-9a-f]{64}", row.get("generation_prompt_sha256", ""))),
            "generation prompt hash required",
        )
        require(
            row.get("human_review") == "pending"
            and row.get("human_reviewer") is None
            and row.get("human_reviewed_at") is None,
            "candidates must stay human-pending; use separate review events",
        )
        require(isinstance(row.get("reference_answer"), str), "AI reference answer field required")
        evidence = row.get("evidence", [])
        require(isinstance(evidence, list), "evidence must be a list")
        direct = set()
        fact_documents: dict[str, set[str]] = {}
        seen_spans = set()
        for item in evidence:
            doc = documents[item["document_id"]]
            require(item.get("grade") in {1, 2}, "evidence grade must be 1 or 2")
            group = item.get("evidence_group_id")
            require(isinstance(group, str) and bool(group), "evidence group required")
            start, end = item.get("start_offset"), item.get("end_offset")
            require(
                type(start) is int and type(end) is int and 0 <= start < end,
                "invalid Unicode codepoint span",
            )
            quote = item.get("quote")
            require(isinstance(quote, str) and len(quote) == end - start, "quote length mismatch")
            require(len(quote.strip()) >= 8, "evidence too short for semantic review")
            if "content" in doc:
                require(doc["content"][start:end] == quote, "evidence quote/offset mismatch")
            elif "characters" in doc:
                require(end <= doc["characters"], "evidence outside document")
            span = (doc["id"], start, end)
            require(span not in seen_spans, "duplicate evidence span")
            seen_spans.add(span)
            if item["grade"] == 2:
                direct.add(doc["id"])
                fact_documents.setdefault(group, set()).add(doc["id"])
        relevant = row["relevant_document_ids"]
        require(len(set(relevant)) == len(relevant), "duplicate relevant document IDs")
        require(set(relevant) == direct, "relevant IDs must equal grade-2 evidence documents")
        if row["answerability"] == "answerable":
            require(bool(fact_documents), "answerable question requires direct evidence")
            require(bool(row["reference_answer"].strip()), "answerable reference answer missing")
            if category == "multi_document":
                require(
                    len(fact_documents) >= 2 and not set.intersection(*fact_documents.values()),
                    "multi-document question must require facts across documents",
                )
            else:
                require(
                    bool(set.intersection(*fact_documents.values())),
                    "single-document question needs a document supporting all facts",
                )
        else:
            require(
                not evidence and not relevant, "non-answerable candidate cannot have gold spans"
            )
            require(
                len(row.get("negative_reason", "").strip()) >= 20,
                "negative or ambiguous candidate needs a reviewable rationale",
            )
            scope = row.get("intended_corpus_scope", {})
            require(scope.get("definition") == "all_manifest_documents", "corpus scope required")
            require(
                bool(re.fullmatch(r"[0-9a-f]{64}", scope.get("manifest_sha256", ""))),
                "negative scope manifest hash missing",
            )
            if manifest_sha256 is not None:
                require(scope["manifest_sha256"] == manifest_sha256, "negative scope drift")
    return {
        "questions": len(rows),
        "documents": len(corpus_rows),
        "checks": "passed",
        "validation_scope": "verified_source_spans" if full_content else "metadata_only",
        "splits": dict(sorted(Counter(row["split"] for row in rows).items())),
        "categories": dict(sorted(Counter(row["category"] for row in rows).items())),
        "languages": dict(sorted(Counter(row["language"] for row in rows).items())),
        "ai_authored": len(rows),
        "human_reviewed": 0,
        "limitations": [
            "Exact offsets do not establish semantic correctness or complete relevance labels.",
            "Negative/ambiguous labels require human assessment of the entire indexed scope.",
            "AI question authoring is not reproducible inference; committed labels and prompt hashes are replayable.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--questions", type=Path, nargs="+", required=True)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--output", type=Path, help="Optional immutable automatic-check report")
    args = parser.parse_args()
    if args.output and args.output.exists():
        raise SystemExit("Refusing to overwrite a past validation report")
    if args.metadata_only:
        corpus = json.loads(args.manifest.read_text(encoding="utf-8"))["documents"]
    else:
        from scripts.prepare_corpus import load_verified_corpus

        corpus = load_verified_corpus(args.manifest)
    questions = [row for path in args.questions for row in read_questions(path)]
    report = validate_questions(questions, corpus, manifest_sha256=digest_file(args.manifest))
    report.update(
        checked_at=datetime.now(UTC).isoformat(),
        manifest_sha256=digest_file(args.manifest),
        question_files={path.name: digest_file(path) for path in args.questions},
        validator_sha256=digest_file(Path(__file__)),
        split_validator_sha256=digest_file(ROOT / "scripts/validate_splits.py"),
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
