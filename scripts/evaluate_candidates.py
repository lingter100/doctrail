"""One preregistered dev candidate-selection intervention; saved branches, no retrieval rerun."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import subprocess
from collections import Counter
from functools import partial
from importlib.metadata import version
from pathlib import Path

from doctrail.model_retrieval import load_model_manifest, rrf_fuse, verify_snapshot
from scripts.evaluate_dataset import breakdown, require_dev, sha256, source_hashes, summarize
from scripts.evaluate_retrieval import (
    CONFIG as ORIGINAL_CONFIG,
)
from scripts.evaluate_retrieval import (
    METHODS,
    Journal,
    build_outcome,
    compact_hits,
    coverage_summary,
    digest_json,
    fusion_diagnostic,
    input_records,
    now,
    paired_changes,
    prepare_inputs,
    stage,
    telemetry_delta,
    timed,
    timing_summary,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REPORT = "experiments/results/m3-retrieval-dev-v1.json"
SOURCE_SHA256 = "76aa4bbc0f827fc4022dbab289eb730072ded56122b8ed8107f72f67ee32a63f"
POLICY = "balanced_depth_rrf50_v1"
CONFIG = {
    "policy": POLICY,
    "question_split": "dev",
    "test_evaluation": "always_locked",
    "branch_source": "immutable_saved_B50_D50; no_BM25_or_E5_inference",
    "selection": "B1,D1,B2,D2,...,B50,D50; unseen_IDs_until_min(50,union_size)",
    "stopping_edge_tie": "B_before_D",
    "order": "original_full_B50_D50_RRF_k60; original_corpus_order_ties",
    "guarantee": "contains_B25_union_D25",
    "max_candidates": 50,
    "rrf_k": 60,
    "reranker": {"device": "cuda", "dtype": "float16", "batch_size": 1},
    "warmup_query": ORIGINAL_CONFIG["warmup_query"],
    "warmup_passage": ORIGINAL_CONFIG["warmup_passage"],
    "warmup_repetitions": 2,
    "seed": 42,
    "final_chunks": 10,
    "evidence_chunks": 5,
    "metrics": ORIGINAL_CONFIG["metrics"],
    "measured_passes": 1,
}


def select_candidates(bm25: list[dict], dense: list[dict], corpus: list[dict]):
    """Label-blind selection; ranking scores/text/annotations never select membership."""
    if len(bm25) > 50 or len(dense) > 50:
        raise ValueError("branch_budget_exceeded")
    # Original full rankings determine RRF scores, including beyond consumed depths.
    fused = rrf_fuse([bm25, dense], corpus, limit=100, k=60)
    target = min(50, len(fused))
    seen, acquired = set(), []
    consumed = {"bm25": 0, "dense_e5": 0}
    visits = duplicates = 0
    for index in range(max(len(bm25), len(dense))):
        for name, branch in (("bm25", bm25), ("dense_e5", dense)):
            if len(seen) == target:
                break
            if index >= len(branch):
                continue
            consumed[name] = index + 1
            visits += 1
            identifier = branch[index]["chunk_id"]
            if identifier in seen:
                duplicates += 1
            else:
                acquired.append(identifier)
                seen.add(identifier)
        if len(seen) == target:
            break
    chosen = [row for row in fused if row["chunk_id"] in seen]
    left_ids, right_ids = ({row["chunk_id"] for row in branch} for branch in (bm25, dense))
    required = {row["chunk_id"] for row in bm25[:25] + dense[:25]}
    if len(chosen) != target or not required <= seen:
        raise ValueError("candidate_policy_invariant_failed")
    return chosen, {
        "consumed_rank_depth": consumed,
        "visited_branch_entries": visits,
        "duplicate_visits": duplicates,
        "union_unique_count": len(fused),
        "selected_unique_count": len(chosen),
        "acquisition_order": acquired,
        "b25_d25_union_preserved": True,
        "selected_branch_membership": {
            "bm25_only": len(seen & (left_ids - right_ids)),
            "dense_only": len(seen & (right_ids - left_ids)),
            "both": len(seen & left_ids & right_ids),
        },
    }


def method_report(rows):
    return {
        "metrics": summarize(rows),
        "candidate_recall": coverage_summary(rows),
        "breakdowns": {
            field: breakdown(rows, field) for field in ("category", "language", "cross_language")
        },
        "candidate_breakdowns": {
            field: {
                value: coverage_summary([r for r in rows if r[field] == value])
                for value in sorted({r[field] for r in rows})
            }
            for field in ("category", "language", "cross_language")
        },
        "failure_diagnostics": dict(Counter(r["candidate_vs_final_diagnostic"] for r in rows)),
        "questions": rows,
    }


def rehydrate(saved, by_id):
    result, seen = [], set()
    for row in saved:
        identifier = row["chunk_id"]
        if identifier not in by_id or identifier in seen or not math.isfinite(row["score"]):
            raise ValueError("saved_candidate_identity_or_score_drift")
        seen.add(identifier)
        hit = {**by_id[identifier], "score": row["score"]}
        if compact_hits([hit])[0] != {k: v for k, v in row.items() if k != "rank"}:
            raise ValueError("saved_candidate_metadata_drift")
        if "rank" in row and row["rank"] != len(result) + 1:
            raise ValueError("saved_candidate_rank_drift")
        result.append(hit)
    return result


def replay_source(source, questions, documents, candidates):
    """Recompute every saved outcome and aggregate, without any inference."""
    by_id = {r["chunk_id"]: r for r in candidates}
    branches = []
    rebuilt = {method: [] for method in METHODS}
    for method in METHODS:
        if [r["id"] for r in source["methods"][method]["questions"]] != [
            q["id"] for q in questions
        ]:
            raise ValueError("source_question_order_drift")
    for index, question in enumerate(questions):
        pools = {
            method: rehydrate(
                source["methods"][method]["questions"][index]["candidate_chunks"], by_id
            )
            for method in METHODS
        }
        bm25, dense = pools["bm25"], pools["dense_e5"]
        if len(bm25) != 50 or len(dense) != 50:
            raise ValueError("source_branch_count_drift")
        if compact_hits(rrf_fuse([bm25, dense], candidates, limit=50, k=60)) != compact_hits(
            pools["hybrid"]
        ):
            raise ValueError("source_hybrid_rrf_drift")
        if compact_hits(
            rrf_fuse([bm25[:25], dense[:25]], candidates, limit=50, k=60)
        ) != compact_hits(pools["hybrid_budget50"]):
            raise ValueError("source_budget_rrf_drift")
        if pools["hybrid_reranked"] != pools["hybrid"]:
            raise ValueError("source_rerank_pool_drift")
        branches.append((bm25, dense))
        for method in METHODS:
            saved = source["methods"][method]["questions"][index]
            final = rehydrate(saved["ranked_chunks"], by_id)
            if method != "hybrid_reranked" and compact_hits(final) != compact_hits(
                pools[method][:10]
            ):
                raise ValueError("source_final_order_drift")
            if not {r["chunk_id"] for r in final} <= {r["chunk_id"] for r in pools[method]}:
                raise ValueError("source_final_pool_drift")
            outcome = build_outcome(question, final, pools[method], documents)
            if method in ("hybrid", "hybrid_reranked", "hybrid_budget50"):
                left, right = (
                    (bm25[:25], dense[:25]) if method == "hybrid_budget50" else (bm25, dense)
                )
                outcome["fusion_candidate_diagnostic"] = fusion_diagnostic(
                    question, left, right, pools[method]
                )
            if outcome != saved:
                raise ValueError("source_outcome_roundtrip_drift")
            rebuilt[method].append(outcome)
    for method, rows in rebuilt.items():
        if method_report(rows) != source["methods"][method]:
            raise ValueError("source_aggregate_roundtrip_drift")
    comparisons = {
        f"{m}_vs_bm25": paired_changes(rebuilt["bm25"], rebuilt[m]) for m in METHODS if m != "bm25"
    }
    comparisons["hybrid_reranked_vs_hybrid"] = paired_changes(
        rebuilt["hybrid"], rebuilt["hybrid_reranked"]
    )
    if comparisons != source["paired_comparisons"]:
        raise ValueError("source_paired_comparison_drift")
    return branches


def verify_hashes(actual, expected):
    if any(actual.get(key) != value for key, value in expected.items()):
        raise ValueError("frozen_source_or_input_drift")


def verify_runtime(actual, original):
    keys = (
        "python",
        "os",
        "gpu_name",
        "cuda_runtime",
        "cudnn",
        "packages",
        "torch_cuda_matmul_allow_tf32",
        "torch_cudnn_allow_tf32",
        "torch_deterministic_algorithms",
        "torch_cudnn_deterministic",
        "torch_cudnn_benchmark",
        "seed",
    )
    if any(actual.get(key) != original.get(key) for key in keys):
        raise ValueError("source_runtime_drift")
    if actual.get("reranker_dtype") != original["model_dtypes"]["reranker"]:
        raise ValueError("source_reranker_dtype_drift")
    return {"passed": True, "compared_keys": [*keys, "reranker_dtype"]}


def frozen_hashes(root, manifest, questions, model_manifest):
    hashes = source_hashes(root, manifest, questions)
    for relative in (
        SOURCE_REPORT,
        SOURCE_REPORT + ".stages.jsonl",
        "experiments/results/m2-bm25-dev-v1.1.json",
        "docs/M3-CANDIDATE-DESIGN.md",
        "tests/test_candidate_experiment.py",
    ):
        hashes[relative] = sha256((root / relative).read_bytes())
    hashes["model_manifest"] = sha256(model_manifest.read_bytes())
    return hashes


def inclusion_changes(old_rows, new_rows):
    if [r["id"] for r in old_rows] != [r["id"] for r in new_rows]:
        raise ValueError("candidate_comparison_order_drift")
    gains, losses, rows = [], [], []
    key = "all_required_evidence_recall_at_50"
    for old, new in zip(old_rows, new_rows, strict=True):
        left, right = old["candidates"][key], new["candidates"][key]
        old_ids = {r["chunk_id"] for r in old["candidate_chunks"]}
        new_ids = {r["chunk_id"] for r in new["candidate_chunks"]}
        old_groups, new_groups = (
            set(r["candidates"]["covered_evidence_groups"]) for r in (old, new)
        )
        if left is not None:
            if not left and right:
                gains.append(old["id"])
            if left and not right:
                losses.append(old["id"])
        rows.append(
            {
                "id": old["id"],
                "before": left,
                "after": right,
                "added_chunk_ids": sorted(new_ids - old_ids),
                "removed_chunk_ids": sorted(old_ids - new_ids),
                "gained_evidence_groups": sorted(new_groups - old_groups),
                "lost_evidence_groups": sorted(old_groups - new_groups),
            }
        )
    return {"gain_ids": gains, "regression_ids": losses, "per_question": rows}


def evaluate(
    manifest_path,
    questions_path,
    model_manifest_path,
    reranker_snapshot,
    journal,
    split="dev",
    *,
    candidate_only=False,
    root=ROOT,
):
    require_dev(split)
    created_at = now()
    frozen = frozen_hashes(root, manifest_path, questions_path, model_manifest_path)
    if frozen[SOURCE_REPORT] != SOURCE_SHA256:
        raise ValueError("source_report_hash_drift")
    source = json.loads((root / SOURCE_REPORT).read_text(encoding="utf-8"))
    verify_hashes(frozen, source["source_sha256"])
    if frozen["model_manifest"] != source["model_manifest_sha256"]:
        raise ValueError("source_model_manifest_drift")
    specifications = load_model_manifest(model_manifest_path)["models"]
    if specifications != source["model_specifications"]:
        raise ValueError("source_model_specification_drift")
    journal.stage = "frozen_input_and_source_replay"
    journal.write("stage_started", source_sha256=frozen, config_sha256=digest_json(CONFIG))
    _corpus, questions, validation, documents, candidates, corpus_hashes = prepare_inputs(
        manifest_path, questions_path, frozen, root
    )
    if (
        digest_json(candidates) != source["candidate_sha256"]
        or corpus_hashes != source["evaluated_corpus_sha256"]
    ):
        raise ValueError("source_corpus_or_candidate_drift")
    branches = replay_source(source, questions, documents, candidates)
    journal.write("stage_completed", methods_replayed=list(METHODS), questions=len(questions))
    # No policy outcome is computed before the complete original five-method replay passes.
    selected, policy_stats, selection_times, candidate_rows = [], [], [], []
    journal.stage = "candidate_selection"
    for question, (bm25, dense) in zip(questions, branches, strict=True):
        (pool, stats), elapsed = timed(partial(select_candidates, bm25, dense, candidates))
        selected.append(pool)
        policy_stats.append({"question_id": question["id"], **stats})
        selection_times.append(elapsed)
        row = build_outcome(question, pool, pool, documents)
        row["fusion_candidate_diagnostic"] = fusion_diagnostic(question, bm25, dense, pool)
        candidate_rows.append(row)
        journal.write(
            "query_completed",
            question_id=question["id"],
            selection_ms=elapsed,
            selection=stats,
            candidates=compact_hits(pool),
        )
    methods = {POLICY: method_report(candidate_rows)}
    resources, telemetry, per_input = {}, {}, {}
    rerank_times, full_rankings, reranked_rows, score_checks = [], [], [], []
    model_files = runtime_parity = None
    runtime = {"python": platform.python_version(), "os": platform.system()}
    if not candidate_only:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        import random

        import numpy as np
        import psutil
        import torch

        from doctrail.model_retrieval import LocalBGEReranker

        if not torch.cuda.is_available():
            raise ValueError("prescribed_cuda_unavailable")
        random.seed(42)
        np.random.seed(42)
        torch.manual_seed(42)
        torch.cuda.manual_seed_all(42)
        model_files = verify_snapshot(reranker_snapshot, specifications["reranker"])
        if model_files != source["local_model_files_sha256"]["reranker"]:
            raise ValueError("source_reranker_files_drift")
        runtime.update(
            {
                "gpu_name": torch.cuda.get_device_name(0),
                "cuda_runtime": torch.version.cuda,
                "gpu_total_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
                "system_ram_total_bytes": psutil.virtual_memory().total,
                "cudnn": torch.backends.cudnn.version(),
                "torch_cuda_matmul_allow_tf32": torch.backends.cuda.matmul.allow_tf32,
                "torch_cudnn_allow_tf32": torch.backends.cudnn.allow_tf32,
                "torch_deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
                "torch_cudnn_deterministic": torch.backends.cudnn.deterministic,
                "torch_cudnn_benchmark": torch.backends.cudnn.benchmark,
                "seed": 42,
                "bitwise_gpu_determinism": "not_guaranteed",
                "packages": {
                    name: version(name)
                    for name in (
                        "torch",
                        "transformers",
                        "numpy",
                        "huggingface-hub",
                        "safetensors",
                        "psutil",
                    )
                },
            }
        )
        reranker = None
        try:
            with stage("reranker_load", journal, resources, torch, psutil):
                reranker = LocalBGEReranker(reranker_snapshot, device="cuda", batch_size=1)
                if (
                    reranker.spec != specifications["reranker"]
                    or str(reranker.dtype) != "torch.float16"
                ):
                    raise ValueError("reranker_runtime_drift")
                runtime["reranker_dtype"] = str(reranker.dtype)
                runtime_parity = verify_runtime(runtime, source["runtime"])
                journal.write("model_loaded", runtime=runtime)
            with stage("reranker_warmup", journal, resources, torch, psutil):
                before = dict(reranker.telemetry)
                for _ in range(2):
                    reranker.rerank(
                        CONFIG["warmup_query"],
                        [{**candidates[0], "text": CONFIG["warmup_passage"]}],
                        limit=1,
                    )
                telemetry["reranker_warmup"] = telemetry_delta(before, reranker.telemetry)
                per_input["reranker_warmup"] = input_records(
                    reranker.telemetry_inputs,
                    ["synthetic_pair_1", "synthetic_pair_2"],
                    "warmup_input_id",
                )
            with stage("reranker_measured_queries", journal, resources, torch, psutil):
                before = dict(reranker.telemetry)
                per_input["reranker_measured_queries"] = []
                for index, (question, pool) in enumerate(zip(questions, selected, strict=True)):
                    start = len(reranker.telemetry_inputs)
                    hits, elapsed = timed(
                        partial(reranker.rerank, question["query"], pool, limit=len(pool)),
                        reranker.synchronize,
                    )
                    if len(hits) != len(pool) or {r["chunk_id"] for r in hits} != {
                        r["chunk_id"] for r in pool
                    }:
                        raise ValueError("reranker_changed_candidate_pool")
                    pairs = input_records(
                        reranker.telemetry_inputs[start:], [r["chunk_id"] for r in pool], "chunk_id"
                    )
                    score_by_id = {r["chunk_id"]: r["score"] for r in hits}
                    for ordinal, (pair, candidate) in enumerate(zip(pairs, pool, strict=True), 1):
                        pair.update(
                            {
                                "input_ordinal": ordinal,
                                "query_utf8_sha256": sha256(question["query"].encode("utf-8")),
                                "chunk_text_utf8_sha256": sha256(candidate["text"].encode("utf-8")),
                                "full_branch_rrf_score": candidate["score"],
                                "raw_bge_score": score_by_id[candidate["chunk_id"]],
                                "score_provenance": "new_cuda_fp16_batch1_forward",
                            }
                        )
                    all_scores = compact_hits(hits)
                    full_rankings.append(
                        {"question_id": question["id"], "ranked_chunks": all_scores}
                    )
                    per_input["reranker_measured_queries"].append(
                        {"question_id": question["id"], "pairs": pairs}
                    )
                    rerank_times.append(elapsed)
                    row = build_outcome(question, hits, pool, documents)
                    row["fusion_candidate_diagnostic"] = candidate_rows[index][
                        "fusion_candidate_diagnostic"
                    ]
                    reranked_rows.append(row)
                    previous = source["methods"]["hybrid_reranked"]["questions"][index][
                        "ranked_chunks"
                    ]
                    new_scores = {r["chunk_id"]: r["score"] for r in hits}
                    for old in previous:
                        if old["chunk_id"] in new_scores:
                            score_checks.append(
                                {
                                    "question_id": question["id"],
                                    "chunk_id": old["chunk_id"],
                                    "before": old["score"],
                                    "after": new_scores[old["chunk_id"]],
                                    "delta": new_scores[old["chunk_id"]] - old["score"],
                                }
                            )
                    journal.write(
                        "query_completed",
                        question_id=question["id"],
                        rerank_ms=elapsed,
                        all_ranked_chunks=all_scores,
                        pair_tokenization=pairs,
                    )
                telemetry["reranker_measured_queries"] = telemetry_delta(before, reranker.telemetry)
        finally:
            if reranker is not None:
                journal.write(
                    "model_telemetry_checkpoint",
                    telemetry=reranker.telemetry,
                    inputs_in_processing_order=reranker.telemetry_inputs,
                )
                reranker.close()
                journal.write("model_released", model="reranker")
        methods[POLICY + "_reranked"] = method_report(reranked_rows)
    journal.stage = "final_drift_verification"
    if frozen_hashes(root, manifest_path, questions_path, model_manifest_path) != frozen:
        raise ValueError("run_source_or_input_drift")
    from scripts.prepare_corpus import load_verified_corpus

    again = load_verified_corpus(manifest_path, root=root)
    if {r["id"]: sha256(r["content"].encode("utf-8")) for r in again} != {
        key: row["actual_normalized_sha256"] for key, row in corpus_hashes.items()
    }:
        raise ValueError("run_corpus_drift")
    if (
        model_files is not None
        and verify_snapshot(reranker_snapshot, specifications["reranker"]) != model_files
    ):
        raise ValueError("run_model_drift")
    git = lambda *args: subprocess.check_output(["git", *args], cwd=root, text=True).strip()
    comparison_rows = reranked_rows if not candidate_only else candidate_rows
    prefix = POLICY + ("_reranked" if not candidate_only else "")
    journal.write("stage_completed", source_inputs_and_corpus_unchanged=True)
    return {
        "schema_version": 1,
        "status": "candidate_replay_only_no_inference"
        if candidate_only
        else "measured_local_cuda_development_unreviewed_annotations",
        "created_at": created_at,
        "completed_at": now(),
        "git_commit": git("rev-parse", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain")),
        "config": CONFIG,
        "config_sha256": digest_json(CONFIG),
        "source_report_sha256": SOURCE_SHA256,
        "source_sha256": frozen,
        "source_replay": {
            "passed": True,
            "methods": list(METHODS),
            "questions_per_method": len(questions),
            "scope": "all_saved_outcomes_aggregates_and_paired_comparisons_exact; H50_H25_reconstructed",
        },
        "candidate_sha256": digest_json(candidates),
        "evaluated_corpus_sha256": corpus_hashes,
        "model_manifest_sha256": frozen["model_manifest"],
        "model_specifications": specifications,
        "local_reranker_files_sha256": model_files,
        "runtime_identity_comparison": runtime_parity,
        "dataset": {**source["dataset"], "validation": validation},
        "runtime": runtime,
        "methods": methods,
        "selection_per_question": policy_stats,
        "candidate_inclusion_comparisons": {
            f"{POLICY}_vs_{name}": inclusion_changes(
                source["methods"][name]["questions"], candidate_rows
            )
            for name in ("hybrid", "bm25", "hybrid_budget50")
        },
        "paired_comparisons": {
            f"{prefix}_vs_{name}": paired_changes(
                source["methods"][name]["questions"], comparison_rows
            )
            for name in ("hybrid_reranked", "bm25")
        },
        "reranker_all_selected_rankings": full_rankings,
        "overlapping_original_top10_score_diagnostic": {
            "scope": "only_original_saved_top10_still_selected; independently_rescored_not_reused",
            "pairs": len(score_checks),
            "nonidentical_scores": sum(r["delta"] != 0 for r in score_checks),
            "max_absolute_delta": max((abs(r["delta"]) for r in score_checks), default=None),
            "per_pair": score_checks,
        },
        "timing": {
            "definition": "new_policy_and_BGE_only; saved_B_D_generation_excluded; not_service_end_to_end",
            "selection": timing_summary(selection_times),
            "rerank": timing_summary(rerank_times),
            "new_serial_component_sum": timing_summary(
                [a + b for a, b in zip(selection_times, rerank_times, strict=True)]
            )
            if rerank_times
            else None,
            "query_order": [q["id"] for q in questions],
            "warmup": {
                "repetitions": 0 if candidate_only else 2,
                "input_selection": "fixed_synthetic_CONFIG_text",
            },
        },
        "resources_by_stage": resources,
        "tokenization_by_stage": telemetry,
        "tokenization_per_input": per_input,
        "before_after_drift_checks": {
            "source_inputs": True,
            "corpus": True,
            "reranker": model_files is not None,
        },
        "cost": {
            "external_api_requests": 0,
            "external_api_cost_usd": 0,
            "local_electricity_and_hardware_cost": "not_measured",
        },
        "limitations": [
            "AI-authored dev annotations; zero human reviews; no test evaluation or training.",
            "One policy selected after prior dev analysis; exploratory dev result, not held-out confirmation.",
            "Full source-span containment; model-visible evidence after truncation is not measured.",
            "Candidate inclusion is a necessary condition, not an oracle top5 or semantic correctness.",
            "Saved BM25/E5 inputs; fresh timing excludes their generation and is not service latency.",
            "Single local serial pass; uncontrolled caches, power and background load; no production load evidence.",
            "RSS sampling misses short peaks; CUDA allocator excludes other GPU/driver allocations.",
            "No API/session/ACL/update/delete integration, generated answer or public deployment evaluated.",
            "If overlapping raw scores drift, changes cannot be attributed solely to candidate membership.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/manifests/kubernetes-v1.json")
    parser.add_argument(
        "--questions", type=Path, default=ROOT / "data/evaluation/m2-dev-v1.1.jsonl"
    )
    parser.add_argument("--model-manifest", type=Path, default=ROOT / "data/models/m3-models.json")
    parser.add_argument("--reranker-snapshot", type=Path, default=ROOT / "models/reranker")
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--candidate-only", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    journal = None
    try:
        require_dev(args.split)
        stage_path = args.output.with_suffix(args.output.suffix + ".stages.jsonl")
        if args.output.exists() or stage_path.exists():
            raise ValueError("refusing_existing_report_or_journal")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        journal = Journal(stage_path)
        journal.write("run_started", config=CONFIG, candidate_only=args.candidate_only)
        report = evaluate(
            args.manifest,
            args.questions,
            args.model_manifest,
            args.reranker_snapshot,
            journal,
            args.split,
            candidate_only=args.candidate_only,
        )
        report["invocation"] = {
            "module": "scripts.evaluate_candidates",
            "arguments": {
                key: (
                    value.resolve().relative_to(ROOT).as_posix()
                    if value.resolve().is_relative_to(ROOT)
                    else value.name
                )
                if isinstance(value, Path)
                else value
                for key, value in vars(args).items()
            },
            "path_policy": "repository_relative; external_paths_reduced_to_basename",
        }
        serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        journal.stage = "completion"
        journal.write("run_completed", report_sha256=sha256(serialized.encode("utf-8")))
    except BaseException as exc:  # noqa: BLE001 - persist safe failure/interrupt metadata
        if journal is not None:
            journal.write(
                "run_failed",
                safe_error_code="M3_CANDIDATE_EVALUATION_FAILED",
                exception_type=type(exc).__name__,
            )
        raise SystemExit(
            f"M3_CANDIDATE_EVALUATION_FAILED ({type(exc).__name__}); inspect stage journal if created"
        ) from None
    finally:
        if journal is not None:
            journal.close()
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": args.output.name,
                "methods": {k: v["metrics"] for k, v in report["methods"].items()},
            }
        )
    )


if __name__ == "__main__":
    main()
