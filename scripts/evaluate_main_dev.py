"""Once-only, frozen main-dev E5 comparison; public model-free receipt replay."""

from __future__ import annotations

import argparse
import contextlib
import gc
import json
import math
import os
import platform
import random
import re
import subprocess
from collections import Counter
from functools import partial
from importlib.metadata import version
from pathlib import Path

from doctrail import model_retrieval as models
from scripts import evaluate_training as calibration
from scripts import prepare_training as pilot
from scripts import train_embedding as training
from scripts.analyze_candidates import classify_groups, contains, required_groups
from scripts.evaluate_candidates import method_report as original_method_report
from scripts.evaluate_candidates import rehydrate, replay_source
from scripts.evaluate_retrieval import CONFIG as M3_CONFIG
from scripts.evaluate_retrieval import (
    FROZEN_INPUTS,
    Journal,
    build_outcome,
    digest_json,
    now,
    paired_changes,
    prepare_inputs,
    stage,
    timed,
    timing_summary,
)

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = "data/evaluation/m4-main-dev-evaluation-v1.json"
DESIGN_PATH = "docs/M4-MAIN-DEV-DESIGN.md"
INPUT_PATHS = {
    "manifest": "data/manifests/kubernetes-v1.json",
    "questions": "data/evaluation/m2-dev-v1.1.jsonl",
    "historical": "experiments/results/m3-retrieval-dev-v1.json",
    "model_manifest": "data/models/m3-models.json",
    "checkpoint": "data/models/m4-terminal-v1.json",
    "calibration_plan": "data/training/m4-calibration-evaluation-v1.1.json",
    "calibration_report": "experiments/results/m4-calibration-v1.json",
    "execution_plan": "data/training/m4-e5-execution-v2.json",
    "ready_manifest": "data/training/m4-training-manifest-v2.json",
    "train_report": "experiments/results/m4-e5-train-v2.json",
    "probe_report": "experiments/results/m4-e5-probe-v2.json",
    "training_plan": "data/training/m4-plan-v1.json",
    "resource_followup": "data/training/m4-resource-followup-v1.json",
    "calibration_analysis": "docs/M4-CALIBRATION-ANALYSIS.md",
    "lock": "uv.lock", "project": "pyproject.toml",
}
REQUIRED_SOURCES = calibration.REQUIRED_SOURCES | {
    "scripts/evaluate_main_dev.py", "tests/test_main_dev_evaluation.py",
    "scripts/evaluate_candidates.py", "scripts/analyze_candidates.py",
    "scripts/prepare_training_ready.py", "scripts/validate_training_reviews.py",
    "scripts/question_dataset.py", "scripts/validate_splits.py",
    "scripts/train_embedding_v2.py", "src/doctrail/__init__.py",
}
METHODS = ("base_fresh", "terminal_fresh")
CONFIG = {
    "methods": list(METHODS), "questions": 79, "positive_questions": 59,
    "documents": 313, "chunks": 3588, "required_groups": 72,
    "candidate_count": 50, "final_chunks": 10, "evidence_chunks": 5,
    "device": "cuda", "dtype": "float32", "attention_implementation": "eager",
    "passage_batch_size": 8, "query_batch_size": 1, "max_length": 512,
    "query_prefix": "query: ", "passage_prefix": "passage: ",
    "pooling": "attention_masked_mean_then_l2", "truncation_side": "right",
    "tokenizer": "same_frozen_base_tokenizer", "seed": 42,
    "warmup_repetitions": 2, "warmup_query": M3_CONFIG["warmup_query"],
    "warmup_passage": M3_CONFIG["warmup_passage"], "measured_passes": 1,
    "concurrency": 1, "tie_break": "original_corpus_order",
    "torch_cuda_matmul_allow_tf32": False, "torch_cudnn_allow_tf32": True,
    "torch_deterministic_algorithms": False, "torch_cudnn_deterministic": False,
    "torch_cudnn_benchmark": False,
}
QUALITY_GATE = {"denominator": 59, "minimum_at50_count_gain": 1,
                "minimum_at5_count_gain": 0, "pass": "eligible_for_separate_operational_validation",
                "fail": "retain_base"}
FAILURE_POLICY = {"automatic_retry": False, "fallback": False,
                  "partial_quality_decision": False, "after_scoring_attempt_consumed": True}
CHUNK_SHA256 = "88e474c05922354de77eeb6d0c4e3b915c74133cb361aa85cc88b0fbcd11f2af"
MRR = "all_required_evidence_reciprocal_rank_at_10_chunks"


def check(condition, code):
    if not condition:
        raise ValueError(code)


def repository_path(name: str, root: Path = ROOT) -> Path:
    check(isinstance(name, str) and "\\" not in name, "unsafe_repository_path")
    path = root / name
    check(not Path(name).is_absolute() and path.resolve().is_relative_to(root.resolve())
          and path.resolve().relative_to(root.resolve()).as_posix() == name,
          "unsafe_repository_path")
    return path


def validate_plan(plan: dict, root: Path = ROOT) -> dict:
    """Reject alternate/test question paths before opening any bound input."""
    check(plan.get("schema_version") == 1 and plan.get("evaluation_id") == "m4-main-dev-v1"
          and plan.get("plan_revision") == "1" and plan.get("status") == "preregistered_not_run"
          and plan.get("configuration") == CONFIG and plan.get("quality_gate") == QUALITY_GATE
          and plan.get("failure_policy") == FAILURE_POLICY
          and plan.get("primary_comparator") == "base_fresh"
          and plan.get("historical_bridge") == "m3_dense_saved"
          and plan.get("test") == "locked" and plan.get("service_adoption") is False
          and plan.get("human_review") == "pending", "unsupported_main_dev_plan")
    inputs = plan.get("input_bindings", {})
    check(set(inputs) == set(INPUT_PATHS), "input_binding_keys_changed")
    for role, name in INPUT_PATHS.items():
        binding = inputs[role]
        check(binding.get("path") == name and re.fullmatch("[0-9a-f]{64}", binding.get("sha256", "")),
              "input_path_or_hash_not_allowlisted")
        repository_path(name, root)
    design = plan.get("design_binding", {})
    check(design.get("path") == DESIGN_PATH, "design_path_changed")
    sources = plan.get("source_sha256_lf", {})
    check(REQUIRED_SOURCES <= set(sources), "missing_source_binding")
    for name, expected in sources.items():
        check(name.startswith(("scripts/", "src/", "tests/")) and name.endswith(".py"),
              "source_path_not_python")
        check(pilot.sha256(repository_path(name, root).read_bytes().replace(b"\r\n", b"\n"))
              == expected, "source_binding_changed")
    bindings = {item["path"]: item["sha256"] for item in [*inputs.values(), design]}
    for name, expected in bindings.items():
        check(models.file_sha256(repository_path(name, root)) == expected, "input_binding_changed")
    check(inputs["questions"]["sha256"] == FROZEN_INPUTS["input_questions"]
          and inputs["manifest"]["sha256"] == FROZEN_INPUTS["input_manifest"], "frozen_dev_changed")
    return bindings


def validate_public_receipts(values: dict, bindings: dict) -> dict:
    """Verify immutable public chain; never resolve a training pack or model directory."""
    checkpoint, execution, train = (values[k] for k in ("checkpoint", "execution_plan", "train_report"))
    manifest, probe, calplan, cal = (values[k] for k in
                                    ("ready_manifest", "probe_report", "calibration_plan", "calibration_report"))
    check(execution["execution_id"] == "m4-e5-execution-v2"
          and execution["ready_manifest_sha256"] == bindings[INPUT_PATHS["ready_manifest"]]
          and execution["parent_plan_sha256"] == bindings[INPUT_PATHS["training_plan"]]
          and execution["resource_followup_plan_sha256"] == bindings[INPUT_PATHS["resource_followup"]],
          "training_chain_mismatch")
    for name, expected in checkpoint["inputs_sha256"].items():
        check(bindings.get(name) == expected, "checkpoint_dependency_mismatch")
    for item in calplan["inputs"].values():
        check(bindings.get(item["path"]) == item["sha256"], "calibration_dependency_mismatch")
    recipe = values["training_plan"]["training_proposal"]
    # The immutable successful train report carries the exact executable recipe.
    check(train["recipe"] == recipe, "training_recipe_mismatch")
    args = (bindings[INPUT_PATHS["execution_plan"]], bindings[INPUT_PATHS["ready_manifest"]], recipe)
    training.validate_probe_report(probe, *args)
    calibration.validate_train_report(train, *args, manifest["triplets"])
    for receipt in (probe, train):
        calibration.validate_numerical_receipt(execution, receipt)
    base = values["model_manifest"]["models"]["e5"]
    check(checkpoint["checkpoint_kind"] == "sole_terminal_after_16_verified_updates"
          and checkpoint["checkpoint_path"] == ".local/m4-e5-train-v2/terminal"
          and checkpoint["inference_tokenizer"] == "original_verified_base_snapshot"
          and checkpoint["base_revision"] == base["revision"] == train["base_revision"]
          and checkpoint["base_repo_id"] == base["repo_id"]
          and set(checkpoint["files"]) == calibration.CHECKPOINT_FILES
          and {k: v["sha256"] for k, v in checkpoint["files"].items()} == train["checkpoint_sha256"]
          and train["verified_base_files"] == {k: v["sha256"] for k, v in base["files"].items()}
          and checkpoint["files"]["model.safetensors"]["sha256"] != base["files"]["model.safetensors"]["sha256"],
          "terminal_identity_mismatch")
    check(cal["payload_sha256"] == pilot.fingerprint({k: v for k, v in cal.items() if k != "payload_sha256"})
          and cal["status"] == "passed" and cal["configuration"] == calibration.CONFIG
          and cal["evaluation_plan_sha256"] == bindings[INPUT_PATHS["calibration_plan"]]
          and cal["main_dev_accessed"] is False and cal["test_accessed"] is False,
          "calibration_receipt_mismatch")
    check(cal["comparison"] == calibration.comparison(cal["methods"]["base"]["questions"],
                                                       cal["methods"]["terminal"]["questions"])
          and cal["comparison"]["calibration_gate_passed"] is True, "calibration_gate_mismatch")
    return {"terminal_kind": checkpoint["checkpoint_kind"], "optimizer_updates": 16,
            "fixed_grad_scale": 1024, "calibration_gate_passed": True,
            "public_receipts_verified": True, "local_training_packs_read": False}


def load_context(plan_path: Path, root: Path = ROOT) -> dict:
    check(plan_path.resolve() == (root / PLAN_PATH).resolve(), "plan_path_not_allowlisted")
    plan = json.loads(plan_path.read_bytes())
    bindings = validate_plan(plan, root)
    bindings[PLAN_PATH] = models.file_sha256(plan_path)
    values = {role: json.loads((root / name).read_bytes()) for role, name in INPUT_PATHS.items()
              if name.endswith(".json")}
    receipts = validate_public_receipts(values, bindings)
    source = values["historical"]
    for name, expected in source["source_sha256"].items():
        if name not in FROZEN_INPUTS:
            raw = repository_path(name, root).read_bytes()
            # Historical source hashes were LF; raw JSON/config bindings stay raw.
            check(pilot.sha256(raw.replace(b"\r\n", b"\n") if name.endswith(".py") else raw)
                  == expected, "historical_protected_source_changed")
    _, questions, validation, documents, candidates, corpus_hashes = prepare_inputs(
        root / INPUT_PATHS["manifest"], root / INPUT_PATHS["questions"], FROZEN_INPUTS, root)
    check(digest_json(candidates) == CHUNK_SHA256 and corpus_hashes == source["evaluated_corpus_sha256"],
          "snapshot_universe_changed")
    check(Counter(q["category"] for q in questions)["no_evidence"] == 12
          and Counter(q["category"] for q in questions)["ambiguous"] == 8
          and sum(bool(q["relevant_document_ids"]) for q in questions) == 59
          and sum(len(required_groups(q)) for q in questions) == 72
          and all(q["human_review"] == "pending" for q in questions), "question_denominator_changed")
    replay_source(source, questions, documents, candidates)
    historical = source["methods"]["dense_e5"]["questions"]
    check(sum(bool(r["candidates"]["all_required_evidence_recall_at_50"]) for r in historical) == 34
          and sum(bool(r["metrics"]["evidence_all_at_5_chunks"]) for r in historical) == 29,
          "historical_dense_count_changed")
    return {"root": root, "plan": plan, "bindings": bindings, "values": values,
            "questions": questions, "documents": documents, "candidates": candidates,
            "historical": historical, "validation": validation, "public_receipts": receipts,
            "identity": {"chunk_sha256": CHUNK_SHA256, "corpus_sha256": digest_json(corpus_hashes),
                         "questions_sha256": digest_json(questions)},
            "historical_source_sha256": source["source_sha256"]}


def outcome(question: dict, hits: list[dict], context: dict) -> dict:
    row = build_outcome(question, hits[:10], hits, context["documents"])
    ranks = [min((rank for rank, hit in enumerate(hits[:10], 1)
                  if any(contains(hit, span) for _, span in alternatives)), default=None)
             for alternatives in required_groups(question).values()]
    row.update({"question_sha256": digest_json(question),
                MRR: (1 / max(ranks) if all(ranks) else 0.0) if ranks else None,
                "groups_at50": classify_groups(question, hits, context["candidates"]),
                "groups_at5": classify_groups(question, hits[:5], context["candidates"])})
    return row


def exact_counts(rows: list[dict]) -> dict:
    positives = [r for r in rows if r["expected_document_ids"]]
    return {"positive_questions": len(positives),
            "all_groups_at50": sum(r["candidates"]["all_required_evidence_recall_at_50"] for r in positives),
            "all_groups_at5": sum(r["metrics"]["evidence_all_at_5_chunks"] for r in positives),
            "required_groups": sum(len(r["expected_evidence_groups"]) for r in positives),
            "covered_groups_at50": sum(len(r["candidates"]["covered_evidence_groups"]) for r in positives),
            "covered_groups_at5": sum(len(r["covered_evidence_groups_at_5_chunks"]) for r in positives)}


def method_report(rows: list[dict]) -> dict:
    result = original_method_report(rows)
    positive = [r for r in rows if r[MRR] is not None]
    result.update({"counts": exact_counts(rows), MRR: sum(r[MRR] for r in positive) / len(positive)
                   if positive else None, "count_breakdowns": {
        field: {value: exact_counts([r for r in rows if r[field] == value])
                for value in sorted({r[field] for r in rows})}
        for field in ("category", "language", "cross_language")}})
    return result


def comparison(base: list[dict], terminal: list[dict]) -> dict:
    check([r["id"] for r in base] == [r["id"] for r in terminal], "paired_question_order_changed")
    left, right = exact_counts(base), exact_counts(terminal)
    check(left["positive_questions"] == right["positive_questions"], "paired_denominator_changed")
    changes = {}
    for key, getter in (("at50", lambda r: r["candidates"]["all_required_evidence_recall_at_50"]),
                        ("at5", lambda r: r["metrics"]["evidence_all_at_5_chunks"]),
                        (MRR, lambda r: r[MRR])):
        pairs = [{"id": a["id"], "base": getter(a), "terminal": getter(b),
                  "delta": float(getter(b)) - float(getter(a))}
                 for a, b in zip(base, terminal, strict=True) if getter(a) is not None]
        changes[key] = {"pairs": pairs, **{label: [p["id"] for p in pairs if condition(p["delta"])]
                         for label, condition in (("gain_ids", lambda d: d > 0),
                             ("regression_ids", lambda d: d < 0), ("tie_ids", lambda d: d == 0))}}
    passed = (right["all_groups_at50"] >= left["all_groups_at50"] + 1
              and right["all_groups_at5"] >= left["all_groups_at5"])
    return {"primary_comparator": "base_fresh", "base": left, "terminal": right,
            "paired": changes, "original_metrics": paired_changes(base, terminal),
            "quality_gate_passed": passed, "decision": QUALITY_GATE["pass" if passed else "fail"],
            "service_adoption": False}


def historical_bridge(base: list[dict], context: dict, runtime: dict) -> dict:
    rows = []
    for old, new in zip(context["historical"], base, strict=True):
        a, b = old["candidate_chunks"], new["candidate_chunks"]
        old_scores = {r["chunk_id"]: r["score"] for r in a}
        deltas = [abs(r["score"] - old_scores[r["chunk_id"]]) for r in b if r["chunk_id"] in old_scores]
        old_ids, new_ids = [r["chunk_id"] for r in a], [r["chunk_id"] for r in b]
        rows.append({"id": new["id"], "membership_equal": set(old_ids) == set(new_ids),
                     "order_equal": old_ids == new_ids, "top10_equal": old["ranked_chunks"] == new["ranked_chunks"],
                     "common_pairs": len(deltas), "score_delta_max": max(deltas) if deltas else None,
                     "score_delta_mean": sum(deltas) / len(deltas) if deltas else None,
                     "metrics_equal": old["metrics"] == new["metrics"],
                     "at50_equal": old["candidates"] == new["candidates"]})
    old_runtime = context["values"]["historical"]["runtime"]
    return {"source_replay_passed": True, "historical_counts": exact_counts(context["historical"]),
            "rows": rows, "exact_equivalence": all(r["top10_equal"] and r["order_equal"]
                                                       and r["score_delta_max"] == 0 for r in rows),
            "runtime_differences": {key: {"historical": old_runtime.get(key), "fresh": value}
                                    for key, value in runtime.items() if old_runtime.get(key) != value},
            "role": "historical_bridge_only_never_primary_comparator"}


def replay_method(saved: dict, context: dict) -> dict:
    check([r["id"] for r in saved["questions"]] == [q["id"] for q in context["questions"]],
          "saved_question_order_changed")
    candidates = context["candidates"]
    by_id, order = ({c["chunk_id"]: c for c in candidates},
                    {c["chunk_id"]: i for i, c in enumerate(candidates)})
    check(len(by_id) == len(candidates), "duplicate_snapshot_chunk")
    rebuilt = []
    for question, row in zip(context["questions"], saved["questions"], strict=True):
        check(len(row["candidate_chunks"]) == min(50, len(candidates)), "candidate_count_changed")
        hits = rehydrate(row["candidate_chunks"], by_id)
        check(all(type(r["score"]) in (int, float) for r in hits), "invalid_score_type")
        check(hits == sorted(hits, key=lambda h: (-h["score"], order[h["chunk_id"]])), "dense_rank_order_changed")
        expected = outcome(question, hits, context)
        check(row == expected, "saved_outcome_changed")
        rebuilt.append(expected)
    result = method_report(rebuilt)
    check(saved == result, "saved_aggregate_changed")
    return result


def finite_nonnegative(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def validate_measurements(measurements: dict, context: dict) -> None:
    check(set(measurements) == set(METHODS), "measurement_methods_changed")
    for name, measurement in measurements.items():
        check(measurement.get("dtype") == "torch.float32" and measurement.get("device") == "cuda"
              and measurement.get("attention_implementation") == "eager"
              and measurement.get("failure_count") == 0, "actual_runtime_changed")
        groups = measurement["tokens"]
        check(set(groups) == {"warmup", "passages", "queries"} and len(groups["warmup"]) == 4,
              "token_coverage_changed")
        for group, key, ids in (("passages", "chunk_id", [c["chunk_id"] for c in context["candidates"]]),
                                 ("queries", "question_id", [q["id"] for q in context["questions"]])):
            check([r[key] for r in groups[group]] == ids, "token_identity_changed")
        tokens = [token for group in groups.values() for token in group]
        for token in tokens:
            length = token["tokens_before_truncation"]
            check(type(length) is int and length > 0 and token["truncated"] == (length > 512)
                  and token["retained_tokens"] == min(length, 512)
                  and bool(re.fullmatch("[0-9a-f]{64}", token["input_ids_attention_mask_sha256"])),
                  "token_evidence_invalid")
        check(not any(t["truncated"] for t in groups["queries"]), "query_truncation_forbidden")
        expected = {"tokenized_inputs": len(tokens), "truncated_inputs": sum(t["truncated"] for t in tokens),
                    "tokens_before_truncation": sum(t["tokens_before_truncation"] for t in tokens),
                    "max_tokens_before_truncation": max(t["tokens_before_truncation"] for t in tokens)}
        check(measurement["truncation"] == expected, "token_totals_changed")
        samples = measurement["query_timings"]
        check([r["question_id"] for r in samples] == [q["id"] for q in context["questions"]],
              "timing_coverage_changed")
        for sample in samples:
            check(all(finite_nonnegative(sample[k]) for k in ("encode_ms", "rank_ms", "total_ms"))
                  and sample["total_ms"] == sample["encode_ms"] + sample["rank_ms"], "timing_sum_changed")
        check(measurement["timing"] == {key: timing_summary([r[key] for r in samples])
                                       for key in ("encode_ms", "rank_ms", "total_ms")}, "timing_summary_changed")
        resources = measurement["resources"]
        check(set(resources) == {name + "_" + suffix for suffix in ("load", "warmup", "passage_prefill", "queries")},
              "resource_stage_changed")
        for resource in resources.values():
            check(all(finite_nonnegative(resource.get(key)) for key in (
                "wall_ms", "process_rss_start_bytes", "process_rss_sampled_peak_bytes", "rss_samples",
                "cuda_allocator_peak_allocated_bytes", "cuda_allocator_peak_reserved_bytes"))
                and resource["rss_samples"] > 0
                and resource["process_rss_sampled_peak_bytes"] >= resource["process_rss_start_bytes"]
                and resource["cuda_allocator_peak_reserved_bytes"] >= resource["cuda_allocator_peak_allocated_bytes"],
                "resource_value_invalid")
    check(measurements[METHODS[0]]["tokens"] == measurements[METHODS[1]]["tokens"], "model_token_inputs_differ")


def validate_journal(raw: bytes, report: dict, context: dict):
    check(pilot.sha256(raw) == report["journal_sha256"], "journal_hash_changed")
    rows = [json.loads(line) for line in raw.splitlines()]
    check(rows[0]["event"] == "evaluation_started" and rows[-1]["event"] == "evaluation_completed"
          and rows[0]["plan_sha256"] == context["bindings"][PLAN_PATH]
          and rows[-1]["decision"] == report["comparison"]["decision"], "journal_not_completed")
    allowed = {"evaluation_started", "stage_started", "stage_resource_checkpoint", "stage_completed",
               "fresh_dev_inference_started", "query_completed", "evaluation_completed"}
    check(all(row["event"] in allowed for row in rows)
          and sum(row["event"] == "fresh_dev_inference_started" for row in rows) == 1, "journal_event_invalid")
    stages = [name + "_" + suffix for name in METHODS for suffix in ("load", "warmup", "passage_prefill", "queries")]
    for event in ("stage_started", "stage_resource_checkpoint", "stage_completed"):
        check([r["stage"] for r in rows if r["event"] == event] == stages, "journal_stage_coverage_changed")
    expected = [(name, q["id"]) for name in METHODS for q in context["questions"]]
    actual = [r for r in rows if r["event"] == "query_completed"]
    check([(r["model"], r["question_id"]) for r in actual] == expected, "journal_query_coverage_changed")
    for row in actual:
        index = [q["id"] for q in context["questions"]].index(row["question_id"])
        check(row["outcome_sha256"] == digest_json(report["methods"][row["model"]]["questions"][index])
              and row["timing"] == report["measurements"][row["model"]]["query_timings"][index]
              and row["candidate_chunks"] == report["methods"][row["model"]]["questions"][index]["candidate_chunks"]
              and row["metrics"] == report["methods"][row["model"]]["questions"][index]["metrics"],
              "journal_query_payload_changed")
    for row in rows:
        if row["event"] == "stage_resource_checkpoint":
            name = next(name for name in METHODS if row["stage"].startswith(name + "_"))
            check(row["resources"] == report["measurements"][name]["resources"][row["stage"]],
                  "journal_resource_changed")


def replay_report(report: dict, context: dict, journal_raw: bytes) -> dict:
    check(report.get("payload_sha256") == pilot.fingerprint({k: v for k, v in report.items() if k != "payload_sha256"})
          and report.get("status") == "passed" and report.get("configuration") == CONFIG
          and report.get("bindings") == context["bindings"] and report.get("identity") == context["identity"]
          and report.get("source_sha256_lf") == context["plan"]["source_sha256_lf"]
          and report.get("historical_source_sha256") == context["historical_source_sha256"]
          and report.get("public_receipts") == context["public_receipts"]
          and report.get("test_question_accessed") is False and report.get("main_dev_accessed") is True
          and report.get("human_reviewed_questions") == 0 and report.get("service_adoption") is False
          and report.get("fresh_dev_inference_started") is True and report.get("failure_count") == 0,
          "receipt_provenance_changed")
    check(re.fullmatch("[0-9a-f]{40}", report.get("freeze_commit", ""))
          and report.get("git_commit") == report["freeze_commit"], "freeze_commit_invalid")
    expected_files = {name: {k: v["sha256"] for k, v in context["values"][role]["files"].items()}
                      for name, role in (("terminal_fresh", "checkpoint"),)}
    expected_files["base_fresh"] = {k: v["sha256"] for k, v in
                                   context["values"]["model_manifest"]["models"]["e5"]["files"].items()}
    check(report.get("model_files_before") == expected_files == report.get("model_files_after"),
          "recorded_model_files_changed")
    runtime = report["runtime"]
    check(all(runtime.get(key) == CONFIG[key] for key in CONFIG if key.startswith("torch_"))
          and runtime.get("seed") == 42 and runtime.get("local_files_only") is True
          and runtime.get("python", "").startswith("3.11.")
          and runtime.get("gpu_total_memory_bytes", 0) > 0
          and runtime.get("torch_num_threads", 0) > 0
          and runtime.get("torch_num_interop_threads", 0) > 0
          and all(runtime.get(key) for key in ("gpu_name", "cuda_runtime", "driver_version", "cudnn", "packages")),
          "runtime_receipt_invalid")
    check(set(report["methods"]) == set(METHODS), "report_methods_changed")
    methods = {name: replay_method(report["methods"][name], context) for name in METHODS}
    decision = comparison(*(methods[name]["questions"] for name in METHODS))
    check(report["comparison"] == decision, "quality_decision_changed")
    check(report["historical_bridge"] == historical_bridge(methods["base_fresh"]["questions"], context, runtime),
          "historical_bridge_changed")
    validate_measurements(report["measurements"], context)
    validate_journal(journal_raw, report, context)
    return {"status": "passed", "scope": "saved_ranking_metric_provenance_replay", "fresh_inference": False,
            "live_model_files_reverified": False, "local_training_packs_read": False,
            "latency_memory_tokens": "saved_observations_not_remeasured", "comparison": decision}


class TokenAudit:
    """Observe actual padded forward tensors while retaining frozen encoder semantics."""

    def __init__(self, tokenizer):
        self.tokenizer = tokenizer
        self.records = []

    def __call__(self, *args, **kwargs):
        encoded = self.tokenizer(*args, **kwargs)
        if kwargs.get("return_tensors") == "pt":
            for ids, mask in zip(encoded["input_ids"].tolist(), encoded["attention_mask"].tolist(), strict=True):
                self.records.append({"retained_tokens": sum(mask),
                    "input_ids_attention_mask_sha256": digest_json({"input_ids": ids, "attention_mask": mask})})
        return encoded


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def verify_freeze(context: dict, freeze_commit: str):
    root = context["root"]
    check(re.fullmatch("[0-9a-f]{40}", freeze_commit) and git(root, "rev-parse", "HEAD") == freeze_commit,
          "freeze_commit_must_be_current_head")
    for name, expected in {**context["bindings"], **context["plan"]["source_sha256_lf"]}.items():
        blob = subprocess.check_output(["git", "show", f"{freeze_commit}:{name}"], cwd=root)
        check(pilot.sha256(blob.replace(b"\r\n", b"\n") if name.endswith(".py") else blob) == expected,
              "freeze_commit_binding_mismatch")


def runtime_receipt(torch, psutil):
    driver = subprocess.check_output(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                                     text=True).strip().splitlines()[0]
    return {"python": platform.python_version(), "os": platform.system(), "seed": 42,
            "gpu_name": torch.cuda.get_device_name(0), "gpu_total_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
            "cuda_runtime": torch.version.cuda, "driver_version": driver, "cudnn": torch.backends.cudnn.version(),
            "torch_num_threads": torch.get_num_threads(), "torch_num_interop_threads": torch.get_num_interop_threads(),
            "logical_cpu_count": os.cpu_count(), "system_ram_total_bytes": psutil.virtual_memory().total,
            "local_files_only": True, "bitwise_gpu_determinism": "not_guaranteed",
            "torch_cuda_matmul_allow_tf32": torch.backends.cuda.matmul.allow_tf32,
            "torch_cudnn_allow_tf32": torch.backends.cudnn.allow_tf32,
            "torch_deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
            "torch_cudnn_deterministic": torch.backends.cudnn.deterministic,
            "torch_cudnn_benchmark": torch.backends.cudnn.benchmark,
            "packages": {name: version(name) for name in
                         ("torch", "transformers", "tokenizers", "numpy", "huggingface-hub", "safetensors", "psutil")}}


def run_comparison(context: dict, output: Path, freeze_commit: str) -> dict:
    root = context["root"]
    repository_path(output.resolve().relative_to(root.resolve()).as_posix(), root)
    verify_freeze(context, freeze_commit)
    check(not output.exists(), "existing_output_forbidden")
    with training.execution_guard(root, context["bindings"][PLAN_PATH], "main-dev"):
        output.mkdir(parents=True)
        journal = Journal(output / "progress.jsonl")
        report = {"schema_version": 1, "status": "running", "started_at": now(),
                  "configuration": CONFIG, "bindings": context["bindings"], "identity": context["identity"],
                  "source_sha256_lf": context["plan"]["source_sha256_lf"],
                  "historical_source_sha256": context["historical_source_sha256"],
                  "public_receipts": context["public_receipts"], "freeze_commit": freeze_commit,
                  "git_commit": git(root, "rev-parse", "HEAD"), "git_dirty": bool(git(root, "status", "--porcelain")),
                  "invocation": {"command": "run", "evaluation_plan": PLAN_PATH},
                  "main_dev_accessed": True, "test_question_accessed": False, "service_adoption": False,
                  "human_reviewed_questions": 0, "fresh_dev_inference_started": False,
                  "methods": {}, "measurements": {}, "failure_count": 0}
        encoder = torch = None
        journal.write("evaluation_started", plan_sha256=context["bindings"][PLAN_PATH], freeze_commit=freeze_commit)
        try:
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            import numpy as np
            import psutil
            import torch

            check(torch.cuda.is_available(), "cuda_required_no_fallback")
            torch.backends.cuda.matmul.allow_tf32 = False
            torch.backends.cudnn.allow_tf32 = True
            torch.use_deterministic_algorithms(False)
            torch.backends.cudnn.deterministic = False
            torch.backends.cudnn.benchmark = False
            report["runtime"] = runtime_receipt(torch, psutil)
            base = root / "models/e5"
            checkpoint = context["values"]["checkpoint"]
            snapshots = {"base_fresh": base, "terminal_fresh": root / checkpoint["checkpoint_path"]}
            specs = {"base_fresh": context["values"]["model_manifest"]["models"]["e5"], "terminal_fresh": checkpoint}
            report["model_files_before"] = {name: models.verify_snapshot(snapshots[name], specs[name]) for name in METHODS}
            calibration.compatible_config(json.loads((base / "config.json").read_bytes()),
                                          json.loads((snapshots["terminal_fresh"] / "config.json").read_bytes()))
            for name in METHODS:
                random.seed(42)
                np.random.seed(42)
                torch.manual_seed(42)
                torch.cuda.manual_seed_all(42)
                resources, samples, outcomes = {}, [], []
                report["methods"][name] = {"questions": outcomes, "status": "partial"}
                report["measurements"][name] = measurement = {"resources": resources, "query_timings": samples}
                with stage(name + "_load", journal, resources, torch, psutil):
                    encoder = (models.LocalE5Encoder(base, device="cuda", batch_size=8)
                               if name == "base_fresh" else calibration.TerminalEncoder(snapshots[name], checkpoint, base))
                    check(encoder.tokenizer.is_fast and encoder.tokenizer.truncation_side == "right"
                          and encoder.model.config._attn_implementation == "eager"
                          and all(p.dtype == torch.float32 and p.device.type == "cuda" for p in encoder.model.parameters()),
                          "actual_model_configuration_changed")
                    audit = TokenAudit(encoder.tokenizer)
                    encoder.tokenizer = audit
                with stage(name + "_warmup", journal, resources, torch, psutil):
                    for _ in range(2):
                        encoder.encode_passages([CONFIG["warmup_passage"]])
                        encoder.encode_queries([CONFIG["warmup_query"]])
                with stage(name + "_passage_prefill", journal, resources, torch, psutil):
                    passages = encoder.encode_passages([c["text"] for c in context["candidates"]])
                check(passages.shape == (3588, 384) and np.isfinite(passages).all()
                      and np.all(np.linalg.norm(passages, axis=1) > 0), "passage_vectors_invalid")
                with stage(name + "_queries", journal, resources, torch, psutil):
                    for question in context["questions"]:
                        if not report["fresh_dev_inference_started"]:
                            report["fresh_dev_inference_started"] = True
                            journal.write("fresh_dev_inference_started")
                        encoded, encode_ms = timed(partial(encoder.encode_queries, [question["query"]]), encoder.synchronize)
                        check(encoded.shape == (1, 384), "query_vector_shape_invalid")
                        hits, rank_ms = timed(partial(models.rank_dense, encoded[0], passages,
                                                      context["candidates"], limit=50), encoder.synchronize)
                        row = outcome(question, hits, context)
                        outcomes.append(row)
                        sample = {"question_id": question["id"], "encode_ms": encode_ms,
                                  "rank_ms": rank_ms, "total_ms": encode_ms + rank_ms}
                        samples.append(sample)
                        journal.write("query_completed", model=name, question_id=question["id"],
                                      outcome_sha256=digest_json(row), timing=sample,
                                      candidate_chunks=row["candidate_chunks"], metrics=row["metrics"])
                tokens = [{**length, **token} for length, token in zip(encoder.telemetry_inputs, audit.records, strict=True)]
                measurement.update({"dtype": str(encoder.dtype), "device": encoder.device,
                    "attention_implementation": encoder.model.config._attn_implementation, "failure_count": 0,
                    "tokens": {"warmup": tokens[:4],
                        "passages": [{"chunk_id": c["chunk_id"], **t} for c, t in zip(context["candidates"], tokens[4:3592], strict=True)],
                        "queries": [{"question_id": q["id"], **t} for q, t in zip(context["questions"], tokens[3592:], strict=True)]},
                    "truncation": dict(encoder.telemetry),
                    "timing": {key: timing_summary([s[key] for s in samples]) for key in ("encode_ms", "rank_ms", "total_ms")}})
                report["methods"][name] = method_report(outcomes)
                encoder.close()
                encoder = None
                del passages
                gc.collect()
                torch.cuda.empty_cache()
            report["model_files_after"] = {name: models.verify_snapshot(snapshots[name], specs[name]) for name in METHODS}
            # Reconstruct public corpus again to detect input/universe changes during execution.
            final_context = load_context(root / PLAN_PATH, root)
            check(all(final_context[key] == context[key] for key in
                      ("identity", "bindings", "plan", "historical_source_sha256")),
                  "snapshot_or_bindings_changed_during_run")
            verify_freeze(final_context, freeze_commit)
            report["comparison"] = comparison(*(report["methods"][name]["questions"] for name in METHODS))
            report["historical_bridge"] = historical_bridge(report["methods"]["base_fresh"]["questions"], context, report["runtime"])
            report.update({"status": "passed", "completed_at": now(), "limitations": [
                "AI-authored labels; human review zero; final test locked.",
                "Full-source evidence is not model-token visibility or answer correctness.",
                "Offline Python one-pass base-first timings are not Java/HTTP latency or speed superiority.",
                "Public snapshot integrity is not ACL, revision, deletion or service validation.",
                "Historical bridge cannot replace fresh base; no automatic adoption or tuning.",
                "Replay checks saved evidence, not fresh numeric scores, tokenization or resource use."]})
            journal.write("evaluation_completed", decision=report["comparison"]["decision"])
            report["journal_sha256"] = models.file_sha256(output / "progress.jsonl")
            report["payload_sha256"] = pilot.fingerprint(report)
            replay_report(report, context, (output / "progress.jsonl").read_bytes())
        except BaseException as error:
            report.pop("comparison", None)
            report.update({"status": "failed", "failure_count": 1, "completed_at": now(),
                           "quality_decision": None, "failure_type": type(error).__name__,
                           "failure_code": "main_dev_failed_no_retry_no_fallback"})
            journal.write("evaluation_failed", failure_type=type(error).__name__,
                          fresh_dev_inference_started=report["fresh_dev_inference_started"])
            raise
        finally:
            if encoder is not None:
                with contextlib.suppress(Exception):
                    encoder.close()
            journal.close()
            report["journal_sha256"] = models.file_sha256(output / "progress.jsonl")
            report.pop("payload_sha256", None)
            report = training.finite_metadata(report)
            report["payload_sha256"] = pilot.fingerprint(report)
            pilot.write_or_verify(output / "report.json", pilot.json_bytes(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run", "replay"))
    parser.add_argument("--evaluation-plan", type=Path, default=ROOT / PLAN_PATH)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--freeze-commit")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--journal", type=Path)
    args = parser.parse_args(argv)
    context = load_context(args.evaluation_plan)
    if args.command == "preflight":
        result = {"status": "passed", "fresh_inference": False, "live_model_files_reverified": False,
                  "public_receipts": context["public_receipts"], "identity": context["identity"]}
    elif args.command == "replay":
        if args.report is None or args.journal is None:
            parser.error("replay requires --report and --journal")
        result = replay_report(json.loads(args.report.read_bytes()), context, args.journal.read_bytes())
    else:
        if args.output_dir is None or args.freeze_commit is None:
            parser.error("run requires --output-dir and --freeze-commit")
        report = run_comparison(context, args.output_dir, args.freeze_commit)
        result = {"status": report["status"], "comparison": report["comparison"]}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
