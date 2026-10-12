"""Read-only, frozen M3 dev candidate and optional tokenizer-offset diagnostics.

No ranking, inference, download, label editing, or held-out question access.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from doctrail.model_retrieval import file_sha256, load_model_manifest, rrf_fuse
from scripts.evaluate_dataset import require_dev
from scripts.evaluate_retrieval import FROZEN_INPUTS, digest_json, prepare_inputs

ROOT = Path(__file__).resolve().parents[1]
FROZEN_REPORT_SHA256 = "76aa4bbc0f827fc4022dbab289eb730072ded56122b8ed8107f72f67ee32a63f"
CATEGORIES = (
    "covered", "no_representable_full_span_chunk",
    "evidence_document_absent", "correct_document_other_chunks",
)
SOURCES = (
    "docs/M3-CANDIDATE-DESIGN.md",
    "scripts/analyze_candidates.py", "tests/test_candidate_analysis.py",
    "scripts/evaluate_retrieval.py", "scripts/evaluate_dataset.py",
    "scripts/question_dataset.py", "scripts/prepare_corpus.py", "scripts/validate_splits.py",
    "src/doctrail/__init__.py",
    "src/doctrail/ingest.py", "src/doctrail/retrieval.py",
    "src/doctrail/model_retrieval.py", "uv.lock", "pyproject.toml",
)


def contains(hit, span):
    return (hit["document_id"] == span["document_id"]
            and hit["start_offset"] <= span["start_offset"]
            and hit["end_offset"] >= span["end_offset"])


def required_groups(question):
    groups = defaultdict(list)
    for index, span in enumerate(question["evidence"]):
        if span["grade"] == 2:
            groups[span["evidence_group_id"]].append((index, span))
    return groups


def classify_groups(question, hits, corpus_chunks):
    """One disjoint reason per required group; alternatives are existential OR."""
    groups = []
    for key, alternatives in sorted(required_groups(question).items()):
        spans = [span for _, span in alternatives]
        representable = [index for index, span in alternatives
                         if any(contains(chunk, span) for chunk in corpus_chunks)]
        covering = sorted({hit["chunk_id"] for hit in hits
                           if any(contains(hit, span) for span in spans)})
        present = sorted({hit["document_id"] for hit in hits
                          if any(hit["document_id"] == span["document_id"] for span in spans)})
        representable_docs = {span["document_id"] for index, span in alternatives
                              if index in representable}
        present_representable = sorted(representable_docs.intersection(present))
        if covering:
            category = "covered"
        elif not representable:
            category = "no_representable_full_span_chunk"
        elif not present_representable:
            category = "evidence_document_absent"
        else:
            category = "correct_document_other_chunks"
        groups.append({"group_id": key, "category": category,
                       "representable_alternative_indices": representable,
                       "covering_chunk_ids": covering, "present_evidence_document_ids": present,
                       "present_representable_alternative_document_ids": present_representable})
    return {
        "groups": groups, "required_group_count": len(groups),
        "all_groups_covered": all(g["category"] == "covered" for g in groups) if groups else None,
        "question_overlapping_flags": {
            category: any(g["category"] == category for g in groups)
            for category in CATEGORIES[1:]
        },
    }


def occupancy(hits, documents):
    by_doc, by_family = Counter(), defaultdict(list)
    for hit in hits:
        by_doc[hit["document_id"]] += 1
        by_family[documents[hit["document_id"]]["family_id"]].append(hit)
    overlapping = []
    for index, left in enumerate(hits):
        for right in hits[index + 1:]:
            overlap = min(left["end_offset"], right["end_offset"]) - max(
                left["start_offset"], right["start_offset"])
            if left["document_id"] == right["document_id"] and overlap > 0:
                overlapping.append({"chunk_ids": [left["chunk_id"], right["chunk_id"]],
                                    "intersection_codepoints": overlap})
    families = [{"family_id": key, "chunks": len(rows),
                 "document_ids": sorted({r["document_id"] for r in rows}),
                 "languages": sorted({documents[r["document_id"]]["language"] for r in rows})}
                for key, rows in sorted(by_family.items())]
    return {"chunks": len(hits), "unique_documents": len(by_doc),
            "chunks_beyond_first_per_document": len(hits) - len(by_doc),
            "document_chunk_counts": dict(sorted(by_doc.items())),
            "same_document_positive_overlap_pairs": overlapping,
            "translation_family_occupancy": families,
            "multilanguage_family_count": sum(len(row["languages"]) > 1 for row in families)}


def verified_hits(rows, chunks):
    ids = [r["chunk_id"] for r in rows]
    if len(ids) != len(set(ids)) or any(key not in chunks for key in ids):
        raise ValueError("invalid_frozen_candidate_ids")
    for row in rows:
        if any(row[key] != chunks[row["chunk_id"]][key]
               for key in ("document_id", "start_offset", "end_offset", "page")):
            raise ValueError("frozen_candidate_offset_drift")
    return [chunks[key] for key in ids]


def candidate_pools(report, questions, candidates):
    chunks = {r["chunk_id"]: r for r in candidates}
    methods = report["methods"]
    expected = [q["id"] for q in questions]
    for name in ("bm25", "dense_e5", "hybrid", "hybrid_reranked"):
        if [q["id"] for q in methods[name]["questions"]] != expected:
            raise ValueError("frozen_question_order_mismatch")
    result = {}
    for index, question in enumerate(questions):
        pools = {label: verified_hits(methods[name]["questions"][index]["candidate_chunks"], chunks)
                 for label, name in (("B50", "bm25"), ("D50", "dense_e5"), ("H50", "hybrid"))}
        if any(len(rows) > 50 for rows in pools.values()):
            raise ValueError("candidate_budget_exceeded")
        pools["union100"] = list({r["chunk_id"]: r for r in pools["B50"] + pools["D50"]}.values())
        fused = rrf_fuse([pools["B50"], pools["D50"]], candidates, limit=50, k=60)
        if [r["chunk_id"] for r in fused] != [r["chunk_id"] for r in pools["H50"]]:
            raise ValueError("frozen_rrf_candidate_mismatch")
        hr = verified_hits(methods["hybrid_reranked"]["questions"][index]["candidate_chunks"], chunks)
        if [r["chunk_id"] for r in hr] != [r["chunk_id"] for r in pools["H50"]]:
            raise ValueError("frozen_reranker_pool_mismatch")
        result[question["id"]] = pools
    return result


def merged_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return merged


def uncovered_intervals(start, end, intervals):
    cursor, gaps = start, []
    for left, right in merged_intervals(intervals):
        left, right = max(start, left), min(end, right)
        if right <= left:
            continue
        if left > cursor:
            gaps.append([cursor, left])
        cursor = max(cursor, right)
    if cursor < end:
        gaps.append([cursor, end])
    return gaps


def source_tokens(encoded, sequence_id, prefix_length, source_length):
    """Do not decode or infer a prefix envelope; retain exact source offset intervals."""
    result = []
    for token, offsets, sequence in zip(encoded["input_ids"], encoded["offset_mapping"],
                                        encoded.sequence_ids(), strict=True):
        if sequence != sequence_id:
            continue
        start, end = offsets
        if start < 0 or end < start or end > source_length + prefix_length:
            raise ValueError("invalid_tokenizer_offset")
        start, end = max(0, start - prefix_length), end - prefix_length
        if end > start:
            result.append((int(token), start, end))
    return result


def tokenize_input(tokenizer, chunk, query=None):
    kwargs = {"return_offsets_mapping": True, "padding": False}
    if query is None:
        inputs, sequence, prefix = ("passage: " + chunk["text"],), 0, 9
        truncation = True
    else:
        query_ids = tokenizer(query, add_special_tokens=False)["input_ids"]
        if len(query_ids) + tokenizer.num_special_tokens_to_add(pair=True) >= 512:
            raise ValueError("reranker_query_too_long")
        inputs, sequence, prefix = (query, chunk["text"]), 1, 0
        truncation = "only_second"
    before = tokenizer(*inputs, truncation=False, **kwargs)
    after = tokenizer(*inputs, truncation=truncation, max_length=512, **kwargs)
    original = source_tokens(before, sequence, prefix, len(chunk["text"]))
    retained = source_tokens(after, sequence, prefix, len(chunk["text"]))
    if retained != original[:len(retained)]:
        raise ValueError("passage_token_offsets_not_right_prefix")
    return {"tokens_before": len(before["input_ids"]), "tokens_after": len(after["input_ids"]),
            "truncated": len(before["input_ids"]) > 512, "before": original, "after": retained}


def span_visibility(chunk, span, tokens):
    start, end = span["start_offset"] - chunk["start_offset"], span["end_offset"] - chunk["start_offset"]
    full_source = contains(chunk, span)
    before = [t for t in tokens["before"] if t[1] < end and t[2] > start]
    after = [t for t in tokens["after"] if t[1] < end and t[2] > start]
    before_gaps = uncovered_intervals(start, end, [(t[1], t[2]) for t in before])
    after_gaps = uncovered_intervals(start, end, [(t[1], t[2]) for t in after])
    return {"full_source_span_in_chunk": full_source,
            "offset_union_covers_entire_span_before": full_source and not before_gaps,
            "offset_union_covers_entire_span_after": full_source and not after_gaps,
            "literal_interval_coverage_status": "proven" if full_source and not after_gaps else "not_proven",
            "all_evidence_overlapping_tokens_retained": full_source and bool(before) and before == after,
            "evidence_tokens_lost_to_truncation": len(before) - len(after),
            "overlapping_tokens_before": len(before), "overlapping_tokens_after": len(after),
            "uncovered_source_intervals_before": [[a + chunk["start_offset"], b + chunk["start_offset"]]
                                                   for a, b in before_gaps],
            "uncovered_source_intervals_after": [[a + chunk["start_offset"], b + chunk["start_offset"]]
                                                  for a, b in after_gaps]}


def verify_tokenizer_files(snapshot, spec):
    """Only tokenizer/config files are read; weights are neither read nor loaded."""
    allowed = set(spec["files"]) | {"verification.json"}
    root = snapshot.resolve()
    if any(p.name not in allowed for p in root.iterdir()):
        raise ValueError("unexpected_tokenizer_snapshot_file")
    hashes = {}
    for name, expected in spec["files"].items():
        if name.endswith(".safetensors"):
            continue
        path = (root / name).resolve()
        if path.parent != root or not path.is_file():
            raise ValueError("tokenizer_file_missing_or_unsafe")
        if path.stat().st_size != expected["size_bytes"] or file_sha256(path) != expected["sha256"]:
            raise ValueError("tokenizer_file_hash_mismatch")
        hashes[name] = expected["sha256"]
    return hashes


def open_tokenizer(snapshot, spec):
    hashes = verify_tokenizer_files(snapshot, spec)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True,
                                              trust_remote_code=False, use_fast=True)
    if not tokenizer.is_fast or tokenizer.truncation_side != "right":
        raise ValueError("fast_right_truncating_tokenizer_required")
    return tokenizer, {"verified_files_sha256": hashes, "class": type(tokenizer).__name__,
                       "is_fast": True, "truncation_side": "right",
                       "backend_sha256": digest_json(json.loads(tokenizer.backend_tokenizer.to_str()))}


def visibility_analysis(report, questions, candidates, pools, specifications, snapshots):
    tokenizers, provenance = {}, {}
    for key in ("e5", "reranker"):
        tokenizers[key], provenance[key] = open_tokenizer(snapshots[key], specifications[key])
    frozen = report["tokenization_per_input"]
    e5_expected = {r["chunk_id"]: r for r in frozen["e5_offline_passage_prefill"]}
    bge_expected = {(q["question_id"], p["chunk_id"]): p
                    for q in frozen["reranker_measured_queries"] for p in q["pairs"]}
    spans_by_doc = defaultdict(list)
    for question in questions:
        for index, span in enumerate(question["evidence"]):
            if span["grade"] == 2:
                spans_by_doc[span["document_id"]].append((question["id"], index, span))
    inputs, span_rows = {"e5": [], "reranker": []}, {"e5": [], "reranker": []}

    def record(key, chunk, question=None):
        tokens = tokenize_input(tokenizers[key], chunk, question["query"] if question else None)
        identity = {"chunk_id": chunk["chunk_id"]}
        expected = e5_expected[chunk["chunk_id"]] if question is None else bge_expected[
            (question["id"], chunk["chunk_id"])]
        if tokens["tokens_before"] != expected["tokens_before_truncation"] or tokens["truncated"] != expected["truncated"]:
            raise ValueError("frozen_tokenization_telemetry_mismatch")
        if question:
            identity["question_id"] = question["id"]
        inputs[key].append({**identity, "tokens_before": tokens["tokens_before"],
                            "tokens_after": tokens["tokens_after"], "truncated": tokens["truncated"],
                            "source_token_offsets_sha256": digest_json({k: tokens[k] for k in ("before", "after")})})
        for qid, index, span in spans_by_doc[chunk["document_id"]]:
            if question and qid != question["id"]:
                continue
            if span["start_offset"] >= chunk["end_offset"] or span["end_offset"] <= chunk["start_offset"]:
                continue
            span_rows[key].append({"question_id": qid, "span_index": index,
                                   "group_id": span["evidence_group_id"], "chunk_id": chunk["chunk_id"],
                                   **span_visibility(chunk, span, tokens)})
    for chunk in candidates:
        record("e5", chunk)
    for question in questions:
        for chunk in pools[question["id"]]["H50"]:
            record("reranker", chunk, question)
    if (len(inputs["e5"]), len(inputs["reranker"])) != (3588, 3950):
        raise ValueError("tokenizer_diagnostic_denominator_mismatch")
    for key in tokenizers:
        if verify_tokenizer_files(snapshots[key], specifications[key]) != provenance[key]["verified_files_sha256"]:
            raise ValueError("tokenizer_snapshot_drift")
    scope_rows = []
    lookups = {key: defaultdict(list) for key in span_rows}
    for key, observations in span_rows.items():
        for row in observations:
            lookups[key][row["question_id"]].append(row)
    for index, question in enumerate(questions):
        scopes = {f"e5_{name}": ("e5", {r["chunk_id"] for r in hits})
                  for name, hits in pools[question["id"]].items()}
        scopes["e5_all_corpus"] = ("e5", {r["chunk_id"] for r in candidates})
        scopes["e5_D5"] = ("e5", {r["chunk_id"] for r in pools[question["id"]]["D50"][:5]})
        scopes["reranker_H50"] = ("reranker", {r["chunk_id"] for r in pools[question["id"]]["H50"]})
        scopes["reranker_HR5"] = ("reranker", {
            r["chunk_id"] for r in report["methods"]["hybrid_reranked"]["questions"][index]["ranked_chunks"][:5]})
        required = set(required_groups(question))
        for name, (key, chunk_ids) in scopes.items():
            observations = [r for r in lookups[key][question["id"]] if r["chunk_id"] in chunk_ids]
            coverage = {}
            for field in ("full_source_span_in_chunk", "offset_union_covers_entire_span_before",
                          "offset_union_covers_entire_span_after", "all_evidence_overlapping_tokens_retained"):
                covered = sorted({r["group_id"] for r in observations if r[field]})
                coverage[field] = {"covered_group_ids": covered,
                                   "all_required_groups": set(covered) == required if required else None}
            scope_rows.append({"question_id": question["id"], "scope": name,
                               "required_group_ids": sorted(required), "coverage": coverage})
    scope_summary = {}
    for scope in sorted({r["scope"] for r in scope_rows}):
        positives = [r for r in scope_rows if r["scope"] == scope and r["required_group_ids"]]
        scope_summary[scope] = {"positive_question_denominator": len(positives),
                                "required_group_denominator": sum(len(r["required_group_ids"]) for r in positives),
                                "all_groups_question_counts": {
                                    field: sum(r["coverage"][field]["all_required_groups"] for r in positives)
                                    for field in positives[0]["coverage"]} if positives else {}}
    return {"provenance": provenance,
            "runtime": {name: version(name) for name in ("transformers", "tokenizers", "huggingface-hub")},
            "input_counts": {key: len(rows) for key, rows in inputs.items()},
            "truncated_input_counts": {key: sum(r["truncated"] for r in rows) for key, rows in inputs.items()},
            "inputs": inputs, "evidence_span_chunk_observations": span_rows,
            "scope_summary": scope_summary, "scope_question_coverage": scope_rows,
            "definition": "Strict union of source-codepoint token offsets covers the entire annotated interval in one source chunk. Whitespace/normalization gaps are not filled. Separate retention of all overlapping pre-truncation tokens does not assert literal source coverage or semantic understanding. Special/query/prefix tokens excluded; no decode or max-offset envelope."}


def analyze(*, report_path, manifest_path, questions_path, model_manifest_path,
            tokenizer_visibility=False, e5_snapshot=None, reranker_snapshot=None, root=ROOT):
    if questions_path.resolve() != (root / "data/evaluation/m2-dev-v1.1.jsonl").resolve():
        raise ValueError("only_frozen_dev_question_path_permitted")
    paths = {"frozen_report": report_path, "input_manifest": manifest_path,
             "input_questions": questions_path, "model_manifest": model_manifest_path,
             **{name: root / name for name in SOURCES}}
    hashes = {key: file_sha256(path) for key, path in paths.items()}
    if hashes["frozen_report"] != FROZEN_REPORT_SHA256:
        raise ValueError("frozen_report_checksum_mismatch")
    if any(hashes[key] != value for key, value in FROZEN_INPUTS.items()):
        raise ValueError("frozen_dev_inputs_required")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    require_dev(report["dataset"]["question_split"])
    specifications = load_model_manifest(model_manifest_path)["models"]
    if hashes["model_manifest"] != report["model_manifest_sha256"] or specifications != report["model_specifications"]:
        raise ValueError("frozen_model_specification_drift")
    for name in SOURCES:
        if name in report["source_sha256"] and hashes[name] != report["source_sha256"][name]:
            raise ValueError("frozen_dependency_source_drift")
    _, questions, validation, documents, candidates, corpus_hashes = prepare_inputs(
        manifest_path, questions_path, hashes, root)
    if digest_json(candidates) != report["candidate_sha256"] or corpus_hashes != report["evaluated_corpus_sha256"]:
        raise ValueError("frozen_corpus_or_chunk_drift")
    pools = candidate_pools(report, questions, candidates)
    rows = []
    for index, question in enumerate(questions):
        pool = pools[question["id"]]
        b, d = {r["chunk_id"] for r in pool["B50"]}, {r["chunk_id"] for r in pool["D50"]}
        analyses = {name: {**classify_groups(question, hits, candidates),
                           "occupancy": occupancy(hits, documents)} for name, hits in pool.items()}
        covered = {name: {g["group_id"] for g in value["groups"] if g["category"] == "covered"}
                   for name, value in analyses.items()}
        final = classify_groups(question, report["methods"]["hybrid_reranked"]["questions"][index]["ranked_chunks"][:5], candidates)
        rows.append({"id": question["id"], "category": question["category"],
                     "language": question["language"], "branch_chunk_intersection_count": len(b & d),
                     "branch_document_intersection_count": len(
                         {r["document_id"] for r in pool["B50"]} & {r["document_id"] for r in pool["D50"]}),
                     "pools": analyses,
                     "stage_transitions": {
                         "selection_cutoff_loss_group_ids": sorted(covered["union100"] - covered["H50"]),
                         "h50_complete_hr5_incomplete": analyses["H50"]["all_groups_covered"] is True and final["all_groups_covered"] is False,
                         "hr5_missing_group_ids": [g["group_id"] for g in final["groups"] if g["category"] != "covered"]}})
    summary = {}
    for name in ("B50", "D50", "union100", "H50"):
        values = [r["pools"][name] for r in rows]
        summary[name] = {"questions": len(values),
                         "questions_with_required_groups": sum(v["required_group_count"] > 0 for v in values),
                         "all_groups_covered_questions": sum(v["all_groups_covered"] is True for v in values),
                         "disjoint_group_categories": dict(Counter(g["category"] for v in values for g in v["groups"])),
                         "overlapping_question_flags": {key: sum(v["question_overlapping_flags"][key] for v in values)
                                                        for key in CATEGORIES[1:]}}
    visibility = visibility_analysis(report, questions, candidates, pools, specifications,
                                     {"e5": e5_snapshot, "reranker": reranker_snapshot}) if tokenizer_visibility else None
    # Re-read and verify every corpus file, and all source/input bytes after computation.
    _, _, _, _, candidates_after, corpus_after = prepare_inputs(manifest_path, questions_path, hashes, root)
    if digest_json(candidates_after) != report["candidate_sha256"] or corpus_after != corpus_hashes:
        raise ValueError("corpus_drift_during_diagnostic")
    if {key: file_sha256(path) for key, path in paths.items()} != hashes:
        raise ValueError("source_drift_during_diagnostic")
    return {"schema_version": 1, "status": "automated_ai_authored_dev_diagnostic_not_human_review",
            "created_at": datetime.now(UTC).isoformat(),
            "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
            "git_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()),
            "python": platform.python_version(), "source_input_sha256": hashes,
            "frozen_run_git_commit": report["git_commit"], "frozen_run_git_dirty": report["git_dirty"],
            "candidate_sha256": report["candidate_sha256"], "evaluated_corpus_sha256": corpus_hashes,
            "model_specifications": specifications, "dataset_validation": validation,
            "protocol": {"question_split": "dev", "test_questions_accessed": 0,
                         "model_forward_passes": 0, "external_requests": 0,
                         "group_precedence": list(CATEGORIES),
                         "design_category_mapping": {"chunk_boundary_uncoverable": "no_representable_full_span_chunk",
                                                     "same_document_wrong_chunk": "correct_document_other_chunks"},
                         "document_presence": "Only documents of globally full-span-representable alternatives determine absent versus other-chunks categories; all alternative document presence also reported.",
                         "alternatives": "grade2 spans OR within group; groups AND; whole span in one chunk",
                         "occupancy": "Exact same-document offset intersections and manifest family membership only; not semantic duplicates or redundant facts."},
            "summary": summary, "questions": rows, "tokenizer_visibility": visibility,
            "limitations": ["AI labels unreviewed and non-exhaustive; no human review or answer-quality evidence.",
                            "Diagnostics associate candidate/offset properties with failures; they do not establish causes.",
                            "No new retrieval ranking, model quality, Java service performance, or ACL measurement.",
                            "Group reasons are disjoint; question flags overlap and must not be summed as question counts."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "experiments/results/m3-retrieval-dev-v1.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/manifests/kubernetes-v1.json")
    parser.add_argument("--questions", type=Path, default=ROOT / "data/evaluation/m2-dev-v1.1.jsonl")
    parser.add_argument("--model-manifest", type=Path, default=ROOT / "data/models/m3-models.json")
    parser.add_argument("--split", default="dev")
    parser.add_argument("--tokenizer-visibility", action="store_true")
    parser.add_argument("--e5-snapshot", type=Path, default=ROOT / "models/e5")
    parser.add_argument("--reranker-snapshot", type=Path, default=ROOT / "models/reranker")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--journal", type=Path, help="New append-only event file; default OUTPUT.journal.jsonl")
    args = parser.parse_args(argv)
    journal = None

    def event(name, **metadata):
        if journal is not None:
            journal.write(json.dumps({"event": name, "at": datetime.now(UTC).isoformat(),
                                      **metadata}) + "\n")
            journal.flush()

    try:
        require_dev(args.split)
        if args.output.exists():
            raise ValueError("refusing_output_overwrite")
        journal_path = args.journal or args.output.with_suffix(".journal.jsonl")
        if journal_path.resolve() == args.output.resolve():
            raise ValueError("journal_output_path_collision")
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal = journal_path.open("x", encoding="utf-8", newline="\n")
        event("started", split="dev", tokenizer_visibility=args.tokenizer_visibility,
              source_sha256=file_sha256(Path(__file__)), frozen_report_sha256=file_sha256(args.report))
        result = analyze(report_path=args.report, manifest_path=args.manifest,
                         questions_path=args.questions, model_manifest_path=args.model_manifest,
                         tokenizer_visibility=args.tokenizer_visibility,
                         e5_snapshot=args.e5_snapshot, reranker_snapshot=args.reranker_snapshot)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        event("completed", output_sha256=file_sha256(args.output),
              source_input_sha256=result["source_input_sha256"])
    except Exception as exc:  # noqa: BLE001 -- redact library paths/source in CLI failure output.
        # Library exceptions may include source text or private cache paths.
        event("failed", error_code="candidate_diagnostic_failed", exception_type=type(exc).__name__)
        print(json.dumps({"status": "failed", "error_code": "candidate_diagnostic_failed",
                          "exception_type": type(exc).__name__}))
        raise SystemExit(1) from None
    finally:
        if journal is not None:
            journal.close()
    print(json.dumps({"status": result["status"], "summary": result["summary"]}))


if __name__ == "__main__":
    main()
