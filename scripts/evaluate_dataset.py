"""Offline, development-only BM25 measurements against immutable corpus inputs.

Uses the service extractor, chunker and scorer unchanged. This is not an API,
permission, load, answer-generation, or held-out quality evaluation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from doctrail.ingest import extract
from doctrail.retrieval import chunk_content, rank_chunks

ROOT = Path(__file__).resolve().parents[1]
METRIC_KEYS = (
    "document_hit_at_5_within_10_chunks",
    "document_recall_at_5_within_10_chunks",
    "document_reciprocal_rank_within_10_chunks",
    "evidence_any_at_5_chunks",
    "evidence_all_at_5_chunks",
    "evidence_group_recall_at_5_chunks",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_dev(split: str) -> None:
    if split != "dev":
        raise ValueError("Only dev evaluation is permitted; held-out test evaluation is locked.")


def cross_language(question: dict, documents: dict[str, dict]) -> str:
    """Describe annotated language possibilities; do not infer from retrieved results."""
    groups: dict[str, set[str]] = {}
    for span in question["evidence"]:
        if span["grade"] == 2:
            groups.setdefault(span["evidence_group_id"], set()).add(
                documents[span["document_id"]]["language"]
            )
    if not groups:
        return "not_applicable"
    language = question["language"]
    if all(languages == {language} for languages in groups.values()):
        return "same_language_only"
    if all(language not in languages for languages in groups.values()):
        return "cross_language_only"
    if all(language in languages for languages in groups.values()):
        return "same_language_sufficient_with_cross_language_alternatives"
    return "mixed_language_required_or_alternative"


def score_question(question: dict, hits: list[dict], documents: dict[str, dict]) -> dict:
    """Full containment covers a span; alternate spans OR, required fact groups AND."""
    hits = hits[:10]
    ranked_ids = [hit["document_id"] for hit in hits]
    unique_ids = list(dict.fromkeys(ranked_ids))
    relevant = set(question["relevant_document_ids"])
    first_rank = next((rank for rank, doc in enumerate(unique_ids, 1) if doc in relevant), None)
    spans = []
    expected_groups = set()
    covered_groups = set()
    for span in question["evidence"]:
        positions = [
            rank
            for rank, hit in enumerate(hits, 1)
            if hit["document_id"] == span["document_id"]
            and hit["start_offset"] <= span["start_offset"]
            and hit["end_offset"] >= span["end_offset"]
        ]
        if span["grade"] == 2:
            expected_groups.add(span["evidence_group_id"])
            if any(rank <= 5 for rank in positions):
                covered_groups.add(span["evidence_group_id"])
        spans.append(
            {
                "document_id": span["document_id"],
                "evidence_group_id": span["evidence_group_id"],
                "grade": span["grade"],
                "start_offset": span["start_offset"],
                "end_offset": span["end_offset"],
                "quote_sha256": sha256(span["quote"].encode("utf-8")),
                "covering_chunk_ranks_within_10": positions,
                "covered_at_5_chunks": any(rank <= 5 for rank in positions),
            }
        )
    exact_offsets = all(
        documents[hit["document_id"]]["content"][hit["start_offset"] : hit["end_offset"]]
        == hit["text"]
        for hit in hits
    )
    if not exact_offsets:
        raise ValueError("Retrieved chunk offsets do not match ingested source content")
    metrics = {
        "document_hit_at_5_within_10_chunks": bool(relevant.intersection(unique_ids[:5])),
        "document_recall_at_5_within_10_chunks": (
            len(relevant.intersection(unique_ids[:5])) / len(relevant) if relevant else None
        ),
        "document_reciprocal_rank_within_10_chunks": 1 / first_rank if first_rank else 0.0,
        "evidence_any_at_5_chunks": bool(covered_groups),
        "evidence_all_at_5_chunks": bool(expected_groups) and covered_groups == expected_groups,
        "evidence_group_recall_at_5_chunks": (
            len(covered_groups) / len(expected_groups) if expected_groups else None
        ),
    }
    if not relevant:
        metrics = dict.fromkeys(METRIC_KEYS)
    return {
        "id": question["id"],
        "question_family_id": question["question_family_id"],
        "query": question["query"],
        "category": question["category"],
        "answerability": question["answerability"],
        "language": question["language"],
        "cross_language": cross_language(question, documents),
        "human_review": question["human_review"],
        "expected_document_ids": sorted(relevant),
        "ranked_chunk_document_ids": ranked_ids,
        "ranked_unique_document_ids_within_10_chunks": unique_ids,
        "first_relevant_unique_document_rank_within_10_chunks": first_rank,
        "ranked_chunks": [
            {
                "rank": rank,
                **{
                    key: hit[key]
                    for key in (
                        "document_id",
                        "chunk_id",
                        "score",
                        "start_offset",
                        "end_offset",
                        "page",
                    )
                },
            }
            for rank, hit in enumerate(hits, 1)
        ],
        "evidence_spans": spans,
        "expected_evidence_groups": sorted(expected_groups),
        "covered_evidence_groups_at_5_chunks": sorted(covered_groups),
        "metrics": metrics,
        "source_offsets_match": exact_offsets,
        "empty_result": not hits,
    }


def summarize(outcomes: list[dict]) -> dict:
    positive = [row for row in outcomes if row["expected_document_ids"]]
    absent = [row for row in outcomes if row["category"] == "no_evidence"]
    result = {
        "questions": len(outcomes),
        "annotated_positive_questions": len(positive),
        "no_evidence_questions": len(absent),
        "no_evidence_empty_result_rate_diagnostic_only": (
            sum(row["empty_result"] for row in absent) / len(absent) if absent else None
        ),
        "source_offsets_match": all(row["source_offsets_match"] for row in outcomes),
    }
    result.update(
        {
            key: sum(row["metrics"][key] for row in positive) / len(positive) if positive else None
            for key in METRIC_KEYS
        }
    )
    return result


def breakdown(outcomes: list[dict], field: str) -> dict:
    return {
        value: summarize([row for row in outcomes if row[field] == value])
        for value in sorted({row[field] for row in outcomes})
    }


def source_hashes(root: Path, manifest: Path, questions: Path) -> dict:
    paths = sorted((root / "src").rglob("*.py")) + sorted((root / "scripts").glob("*.py"))
    paths += [root / "uv.lock", root / "pyproject.toml"]
    values = {path.relative_to(root).as_posix(): sha256(path.read_bytes()) for path in paths}
    values["input_manifest"] = sha256(manifest.read_bytes())
    values["input_questions"] = sha256(questions.read_bytes())
    return values


def evaluate(manifest_path: Path, questions_path: Path, split: str = "dev", *, root=ROOT) -> dict:
    require_dev(split)
    # Deferred imports permit metric regression tests without preparing a corpus.
    from scripts.prepare_corpus import load_verified_corpus
    from scripts.question_dataset import validate_questions

    created_at = datetime.now(UTC).isoformat()
    frozen_hashes = source_hashes(root, manifest_path, questions_path)
    git = lambda *args: subprocess.check_output(["git", *args], cwd=root, text=True).strip()
    git_commit, git_dirty = git("rev-parse", "HEAD"), bool(git("status", "--porcelain"))
    load_started = time.perf_counter()
    corpus = load_verified_corpus(manifest_path, root=root)
    verification_ms = (time.perf_counter() - load_started) * 1000
    questions = [
        json.loads(line)
        for line in questions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not questions:
        raise ValueError("Question set is empty")
    validation = validate_questions(
        questions, corpus, allowed_split=split, manifest_sha256=frozen_hashes["input_manifest"]
    )
    documents, candidates, hashes = {}, [], {}
    ingestion_started = time.perf_counter()
    for row in sorted(corpus, key=lambda item: item["id"]):
        source = row["content"].encode("utf-8")
        actual_normalized = sha256(source)
        if actual_normalized != row["normalized_sha256"]:
            raise ValueError("Normalized corpus checksum drift")
        content, pages = extract(source, "md")
        documents[row["id"]] = {**row, "content": content}
        chunks = chunk_content(content, pages)
        hashes[row["id"]] = {
            "raw_sha256": row["sha256"],
            "actual_normalized_sha256": actual_normalized,
            "actual_ingested_sha256": sha256(content.encode("utf-8")),
            "chunks": len(chunks),
            "characters": len(content),
        }
        for chunk in chunks:
            candidates.append(
                {
                    "document_id": row["id"],
                    "chunk_id": f"{row['id']}:{chunk.ordinal}",
                    "title": row["title"],
                    "filename": f"{row['id']}.md",
                    "text": chunk.text,
                    "page": chunk.page,
                    "start_offset": chunk.start_offset,
                    "end_offset": chunk.end_offset,
                }
            )
    ingestion_ms = (time.perf_counter() - ingestion_started) * 1000
    # Offset validation is repeated after service extraction because it normalizes text.
    for question in questions:
        for span in question["evidence"]:
            content = documents[span["document_id"]]["content"]
            if content[span["start_offset"] : span["end_offset"]] != span["quote"]:
                raise ValueError("Evidence offsets mismatch after service extraction")
    outcomes, timings = [], []
    for question in questions:
        started = time.perf_counter()
        hits = rank_chunks(question["query"], candidates, limit=10)
        elapsed = (time.perf_counter() - started) * 1000
        timings.append(elapsed)
        outcome = score_question(question, hits, documents)
        outcome["offline_rank_ms"] = round(elapsed, 3)
        outcomes.append(outcome)
    if source_hashes(root, manifest_path, questions_path) != frozen_hashes:
        raise ValueError("Evaluation source or input checksum drift during run")
    # Recheck raw and processed files too, not merely their in-memory input snapshot.
    verified_again = load_verified_corpus(manifest_path, root=root)
    if {row["id"]: sha256(row["content"].encode("utf-8")) for row in verified_again} != {
        doc_id: value["actual_normalized_sha256"] for doc_id, value in hashes.items()
    }:
        raise ValueError("Corpus checksum drift during run")
    percentile = lambda proportion: sorted(timings)[math.ceil(len(timings) * proportion) - 1]
    return {
        "schema_version": 2,
        "status": "measured_development_only_unreviewed_annotations",
        "created_at": created_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "python": platform.python_version(),
        "platform": platform.system(),
        "source_sha256": frozen_hashes,
        "evaluated_corpus_sha256": hashes,
        "dataset": {
            "documents": len(documents),
            "chunks": len(candidates),
            "questions": len(questions),
            "indexed_document_splits": dict(
                sorted(Counter(row["split"] for row in corpus).items())
            ),
            "question_split": split,
            "human_review_status_counts": dict(Counter(row["human_review"] for row in questions)),
            "validation": validation,
            "labels_coverage": "incomplete_annotations_not_exhaustive_relevance_judgments",
            "index_scope": "all_verified_manifest_documents_including_other_splits; no_training",
        },
        "config": {
            "method": "bm25",
            "k1": 1.5,
            "b": 0.75,
            "chunk_characters": 1000,
            "overlap_characters": 150,
            "tokenizer": "ascii-word-korean-bigram-v1",
            "retrieved_chunks": 10,
            "document_metrics": "first_5_deduplicated_documents_within_returned_10_chunks",
            "reciprocal_rank": "first_relevant_deduplicated_document_within_returned_10_chunks",
            "evidence_metrics": "grade2_groups; alternative_spans_OR; required_groups_AND; full_span_in_one_top5_chunk",
            "tie_breaking": "service_sort_with_stable_source_id_filenames_and_chunk_ids",
        },
        "metrics": summarize(outcomes),
        "breakdowns": {
            field: breakdown(outcomes, field)
            for field in ("category", "language", "cross_language")
        },
        "timing": {
            "corpus_verification_and_load_ms": round(verification_ms, 3),
            "service_extraction_and_chunking_ms": round(ingestion_ms, 3),
            "offline_rank_total_ms": round(sum(timings), 3),
            "offline_rank_p50_ms": round(percentile(0.5), 3),
            "offline_rank_p95_ms": round(percentile(0.95), 3),
            "definition": "serial_single_pass_service_rank_chunks_including_tokenization; excludes_ingestion_network_HTTP_SQL_ACL",
        },
        "cost": {
            "external_api_requests": 0,
            "external_api_cost_usd": 0,
            "local_electricity_and_hardware_cost": "not_measured",
        },
        "limitations": [
            "AI-authored development annotations are not human-reviewed or held-out quality evidence.",
            "Incomplete judgments measure annotated positives only; unannotated hits may be relevant.",
            "Document recall includes alternative supporting documents; evidence groups express sufficient alternatives.",
            "All required evidence groups, not any one span, must be retrieved for full multi-fact coverage.",
            "Exact span containment in one chunk is required; partial or distributed spans do not count.",
            "No-evidence empty results are diagnostic, not validated abstention, answerability or QA accuracy.",
            "Offline public corpus ranking does not exercise API sessions, database persistence or ACL checks.",
            "Serial local ranking timings exclude ingestion and network; no production load claim.",
            "No model training, embeddings, generated answers, paid inference or deployment measured.",
            "Test evaluation is locked for this milestone regardless of candidate review status.",
        ],
        "questions": outcomes,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--split", default="dev", choices=("dev", "test"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        require_dev(args.split)
        if args.output.exists():
            raise ValueError("Refusing to overwrite a past run. Choose a new report name.")
        report = evaluate(args.manifest, args.questions, args.split)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"report": args.output.as_posix(), "metrics": report["metrics"]}))


if __name__ == "__main__":
    main()
