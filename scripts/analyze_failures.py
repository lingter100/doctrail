"""Diagnose saved development results without changing labels or querying test data."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from doctrail.ingest import extract
from doctrail.retrieval import chunk_content
from scripts.prepare_corpus import load_verified_corpus
from scripts.question_dataset import digest_file, read_questions


def analyze(report: dict, questions: list[dict], corpus: list[dict]) -> dict:
    if any(q["split"] != "dev" for q in questions):
        raise ValueError("Failure analysis is development-only")
    by_id = {row["id"]: row for row in questions}
    chunks = {}
    for doc in corpus:
        content, pages = extract(doc["content"].encode(), "md")
        chunks[doc["id"]] = chunk_content(content, pages)
    diagnoses = []
    for outcome in report["questions"]:
        question = by_id[outcome["id"]]
        if question["answerability"] != "answerable":
            diagnoses.append(
                {
                    "id": question["id"],
                    "category": question["category"],
                    "diagnosis": "non_answerable_result_is_not_abstention",
                    "empty_result": outcome["empty_result"],
                }
            )
            continue
        groups: dict[str, list[dict]] = {}
        for span in question["evidence"]:
            if span["grade"] == 2:
                groups.setdefault(span["evidence_group_id"], []).append(span)
        unrecoverable = [
            group
            for group, alternatives in groups.items()
            if not any(
                chunk.start_offset <= span["start_offset"]
                and chunk.end_offset >= span["end_offset"]
                for span in alternatives
                for chunk in chunks[span["document_id"]]
            )
        ]
        retrieved_docs = set(outcome["ranked_chunk_document_ids"])
        absent_groups = [
            group
            for group, spans in groups.items()
            if not any(span["document_id"] in retrieved_docs for span in spans)
        ]
        if outcome["metrics"]["evidence_all_at_5_chunks"]:
            diagnosis = "all_annotated_required_groups_found"
        elif unrecoverable:
            diagnosis = "required_span_unrepresentable_in_current_chunks"
        elif absent_groups:
            diagnosis = "required_group_document_absent_from_top10_chunks"
        else:
            diagnosis = "required_span_missing_from_top5_despite_document_candidates"
        diagnoses.append(
            {
                "id": question["id"],
                "category": question["category"],
                "cross_language": outcome["cross_language"],
                "diagnosis": diagnosis,
                "unrepresentable_groups": unrecoverable,
                "groups_without_annotated_document_in_top10": absent_groups,
            }
        )
    return {
        "status": "derived_development_diagnostics_not_semantic_ground_truth",
        "questions": len(diagnoses),
        "counts": dict(Counter(row["diagnosis"] for row in diagnoses)),
        "cross_language_only_counts": dict(
            Counter(
                row["diagnosis"]
                for row in diagnoses
                if row.get("cross_language") == "cross_language_only"
            )
        ),
        "details": diagnoses,
        "limitations": [
            "Diagnoses use incomplete AI annotations; unannotated results may be sufficient.",
            "Priority buckets identify observable missing coverage, not experimentally proven causal explanations.",
            "Unrepresentable span means no existing chunk contains a whole alternative span for a required fact group.",
            "No retrieval is rerun and no test result is inspected. Source labels remain unchanged.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Refusing to overwrite a previous failure analysis")
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if report["source_sha256"]["input_manifest"] != digest_file(args.manifest) or report[
        "source_sha256"
    ]["input_questions"] != digest_file(args.questions):
        raise ValueError("Failure analysis inputs differ from measured evaluation")
    result = analyze(report, read_questions(args.questions), load_verified_corpus(args.manifest))
    result["input_sha256"] = {
        "manifest": digest_file(args.manifest),
        "questions": digest_file(args.questions),
        "report": digest_file(args.report),
        "analysis_script": digest_file(Path(__file__)),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["counts"]))


if __name__ == "__main__":
    main()
