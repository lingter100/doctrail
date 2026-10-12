"""Frozen base/terminal E5 comparison on original-train calibration only.

checkpoint: bind the terminal checkpoint of one successful bounded training run.
run: one CUDA FP32 comparison, never dev/test evaluation or service adoption.
replay: recompute saved-ranking metrics and verify provenance, without inference.
"""

from __future__ import annotations

import argparse
import contextlib
import gc
import importlib
import json
import math
import os
import random
from functools import partial
from importlib.metadata import version
from pathlib import Path

from doctrail import model_retrieval as models
from doctrail.training import optimizer_batches
from scripts import prepare_training as pilot
from scripts import prepare_training_ready as ready
from scripts import train_embedding as training
from scripts.evaluate_dataset import score_question
from scripts.evaluate_retrieval import CONFIG as M3_CONFIG
from scripts.evaluate_retrieval import (
    Journal,
    candidate_coverage,
    stage,
    timed,
    timing_summary,
)
from scripts.validate_training_reviews import question_hash

ROOT = pilot.ROOT
CONFIG = {
    "question_partition": "calibration_inside_original_train", "questions": 16,
    "documents": 180, "chunks": 2196, "candidate_count": 50,
    "comparison": ["base", "terminal"], "checkpoint_selection": "terminal_only",
    "device": "cuda", "dtype": "float32", "passage_batch_size": 8, "query_batch_size": 1,
    "query_prefix": "query: ", "passage_prefix": "passage: ", "max_length": 512,
    "pooling": "attention_masked_mean_then_l2", "tokenizer": "same_frozen_base_tokenizer",
    "seed": M3_CONFIG["seed"], "warmup_repetitions": M3_CONFIG["warmup_repetitions"],
    "warmup_query": M3_CONFIG["warmup_query"], "warmup_passage": M3_CONFIG["warmup_passage"],
    "measured_passes": 1, "main_dev": "not_opened", "test": "locked",
    "promotion": "primary_question_count_gain_at_least_1_and_no_evidence_at5_count_decline",
}
REQUIRED_SOURCES = {
    "scripts/evaluate_training.py", "scripts/train_embedding.py", "src/doctrail/training.py",
    "src/doctrail/model_retrieval.py", "scripts/evaluate_dataset.py", "scripts/evaluate_retrieval.py",
    "scripts/prepare_training.py", "scripts/prepare_corpus.py",
    "src/doctrail/ingest.py", "src/doctrail/retrieval.py",
}
INPUT_KEYS = {"execution_plan", "ready_manifest", "train_report", "probe_report", "checkpoint_manifest"}
METRICS = ("evidence_all_at_50_chunks", "evidence_all_at_5_chunks", "evidence_mrr_at_10_chunks",
           "document_hit_at_5_within_10_chunks", "document_reciprocal_rank_within_10_chunks")
CHECKPOINT_FILES = {"config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json",
                    "special_tokens_map.json"}
EXECUTION_RUNNERS = {"m4-e5-execution-v1": "scripts.train_embedding",
                     "m4-e5-execution-v2": "scripts.train_embedding_v2"}


def execution_runner(execution: dict):
    """Explicit lazy allowlist; importing this evaluator never imports a future runner."""
    module = EXECUTION_RUNNERS.get(execution.get("execution_id"))
    if module is None:
        raise ValueError("unsupported_evaluation_execution_runner")
    return importlib.import_module(module)


def runner_source(execution: dict) -> str:
    module = EXECUTION_RUNNERS.get(execution.get("execution_id"))
    if module is None:
        raise ValueError("unsupported_evaluation_execution_runner")
    return module.replace(".", "/") + ".py"


def bound_json(path: Path, expected: str | None = None) -> tuple[dict, str]:
    ready.relative(path)
    raw = path.read_bytes()
    digest = pilot.sha256(raw)
    if expected is not None and digest != expected:
        raise ValueError("evaluation_input_checksum_mismatch")
    return json.loads(raw), digest


def validate_train_report(report: dict, execution_sha256: str, ready_sha256: str,
                           recipe: dict, triplets: list[dict]) -> None:
    if (report.get("command") != "train" or report.get("status") != "passed"
            or report.get("execution_plan_sha256") != execution_sha256
            or report.get("ready_manifest_sha256") != ready_sha256
            or report.get("recipe") != recipe or report.get("training_executed") is not True
            or report.get("terminal_checkpoint_saved") is not True
            or report.get("quality_evaluation_executed") is not False
            or any(report.get(key) != 16 for key in
                   ("optimizer_groups_started", "optimizer_steps_attempted", "optimizer_step_calls",
                    "optimizer_steps_completed", "optimizer_steps_verified", "optimizer_steps",
                    "weight_updates_observed"))):
        raise ValueError("successful_exact_16_update_training_required")
    expected = list(optimizer_batches(triplets, seed=recipe["seed"], epochs=recipe["epochs"],
                                      microbatch=recipe["microbatch_queries"],
                                      accumulation=recipe["gradient_accumulation_steps"],
                                      max_steps=recipe["max_optimizer_steps"]))
    steps = report.get("steps", [])
    if len(expected) != 16 or len(steps) != 16:
        raise ValueError("training_schedule_denominator_mismatch")
    for actual, group in zip(steps, expected, strict=True):
        ids = [row["question_id"] for batch in group["microbatches"] for row in batch]
        if (actual.get("question_ids") != ids or actual.get("epoch") != group["epoch"]
                or actual.get("optimizer_step") != group["optimizer_step"]
                or actual.get("question_count") != group["question_count"]
                or actual.get("status") != "passed"
                or actual.get("optimizer_update_verified") is not True
                or actual.get("weight_change_observed") is not True
                or actual.get("learning_rate") != recipe["learning_rate"]
                or not isinstance(actual.get("loss"), (float, int))
                or not math.isfinite(actual["loss"])
                or not isinstance(actual.get("peak_allocated_mib"), (float, int))
                or not 0 < actual["peak_allocated_mib"] <= recipe["resource_peak_allocated_limit_mib"]):
            raise ValueError("training_schedule_or_update_proof_mismatch")


def compatible_config(base: dict, terminal: dict) -> None:
    """Ignore only serialization metadata; keep architecture and every semantic field.

    Pinned AutoConfig round-trip changes torch_dtype to dtype and the version/name
    metadata. The frozen BertModel architecture is already the AutoModel class;
    accepting arbitrary default/architecture changes would weaken this boundary.
    """
    metadata = {"_name_or_path", "torch_dtype", "dtype", "transformers_version"}
    if ({key: value for key, value in base.items() if key not in metadata} !=
            {key: value for key, value in terminal.items() if key not in metadata}):
        raise ValueError("terminal_model_architecture_changed")


def validate_numerical_receipt(execution: dict, report: dict) -> None:
    if execution["execution_id"] != "m4-e5-execution-v2":
        return
    expected = {"grad_scaler_init_scale": 1024.0}
    fields = ("grad_scaler_configured_init_scale", "grad_scaler_actual_initial_scale",
              "grad_scaler_current_scale")
    step_fields = ("grad_scaler_actual_initial_scale", "grad_scaler_scale_before_unscale",
                   "grad_scaler_scale_before_clip", "grad_scaler_scale_before_step", "grad_scaler_scale")
    # At most 16 updates < GradScaler's unchanged growth interval (2000). Any
    # skipped/backed-off step already fails the execution gate, so no scale change
    # is valid in either the successful probe or the successful bounded training.
    if (execution.get("numerical_override") != expected or report.get("numerical_override") != expected
            or not execution.get("resource_followup_plan_sha256")
            or report.get("resource_followup_plan_sha256") != execution["resource_followup_plan_sha256"]
            or any(report.get(field) != 1024.0 for field in fields)
            or any(step.get(field) != 1024.0 for step in report.get("steps", []) for field in step_fields)):
        raise ValueError("numerical_followup_actual_scale_or_binding_mismatch")


def checkpoint_manifest(report: dict, bindings: dict, base_snapshot: Path,
                         base_spec: dict) -> dict:
    """No caller-selected epoch/path: the successful report selects terminal only."""
    checkpoint = ROOT / report["checkpoint_path"]
    name = ready.relative(checkpoint)
    if not name.startswith(".local/") or checkpoint.name != "terminal":
        raise ValueError("only_local_terminal_checkpoint_allowed")
    files = report.get("checkpoint_sha256", {})
    if set(files) != CHECKPOINT_FILES or {path.name for path in checkpoint.iterdir()} != CHECKPOINT_FILES:
        raise ValueError("unsafe_or_incomplete_terminal_checkpoint_files")
    records = {}
    for filename, expected in files.items():
        path = checkpoint / filename
        if path.resolve().parent != checkpoint.resolve() or not path.is_file():
            raise ValueError("unsafe_terminal_checkpoint_path")
        actual = models.file_sha256(path)
        if actual != expected:
            raise ValueError("terminal_checkpoint_differs_from_training_report")
        records[filename] = {"sha256": actual, "size_bytes": path.stat().st_size}
    models.verify_snapshot(base_snapshot, base_spec)
    compatible_config(json.loads((base_snapshot / "config.json").read_bytes()),
                      json.loads((checkpoint / "config.json").read_bytes()))
    if files["model.safetensors"] == base_spec["files"]["model.safetensors"]["sha256"]:
        raise ValueError("terminal_weights_identical_to_base_after_claimed_updates")
    result = {"schema_version": 1, "checkpoint_kind": "sole_terminal_after_16_verified_updates",
              "checkpoint_path": name, "inputs_sha256": bindings,
              "base_repo_id": base_spec["repo_id"], "base_revision": base_spec["revision"],
              "files": records, "inference_tokenizer": "original_verified_base_snapshot",
              "human_review": "pending", "retrieval_improvement_claimed": False}
    ready.public_safe(result)
    return result


def validated_training(paths: dict[str, Path], hashes: dict[str, str] | None = None) -> dict:
    hashes = hashes or {}
    values, bindings = {}, {}
    for key in ("execution_plan", "ready_manifest", "train_report", "probe_report"):
        values[key], digest = bound_json(paths[key], hashes.get(key))
        bindings[ready.relative(paths[key])] = digest
    runner = execution_runner(values["execution_plan"])
    recipe = runner.validate_execution(values["execution_plan"])
    manifest, context = runner.verified_data(values["execution_plan"], paths["ready_manifest"])
    execution_sha256 = bindings[ready.relative(paths["execution_plan"])]
    ready_sha256 = bindings[ready.relative(paths["ready_manifest"])]
    runner.validate_probe_report(values["probe_report"], execution_sha256, ready_sha256, recipe)
    validate_train_report(values["train_report"], execution_sha256, ready_sha256, recipe,
                          manifest["triplets"])
    base_spec = models.load_model_manifest()["models"]["e5"]
    trained = values["train_report"]
    if (trained.get("base_revision") != base_spec["revision"]
            or trained.get("precision") != recipe["mixed_precision"]
            or trained.get("verified_base_files") !=
            {name: item["sha256"] for name, item in base_spec["files"].items()}):
        raise ValueError("training_base_or_precision_provenance_mismatch")
    validate_numerical_receipt(values["execution_plan"], trained)
    validate_numerical_receipt(values["execution_plan"], values["probe_report"])
    _, documents = pilot.load_inputs(ROOT / "data/training/m4-plan-v1.json")
    candidates = pilot.chunks_for(documents)
    questions = sorted((q for q in context["questions"] if q["partition"] == "calibration"),
                       key=lambda q: q["id"])
    if (len(documents), len(candidates), len(questions)) != (180, 2196, 16):
        raise ValueError("calibration_train_corpus_denominator_mismatch")
    if [q["id"] for q in questions] != [f"m4-cal-{i:03d}" for i in range(1, 17)]:
        raise ValueError("calibration_question_selection_changed")
    return {"bindings": bindings, "recipe": recipe, "manifest": manifest,
            "train_report": values["train_report"], "execution": values["execution_plan"],
            "documents": {d["id"]: d for d in documents}, "candidates": candidates,
            "questions": questions}


def load_evaluation(plan_path: Path) -> dict:
    plan, digest = bound_json(plan_path)
    if (plan.get("schema_version") != 1 or plan.get("evaluation_id") != "m4-calibration-v1"
            or plan.get("configuration") != CONFIG or set(plan.get("inputs", {})) != INPUT_KEYS
            or not REQUIRED_SOURCES <= set(plan.get("source_sha256_lf", {}))):
        raise ValueError("unsupported_or_incomplete_frozen_evaluation_plan")
    for name, expected in plan["source_sha256_lf"].items():
        if not name.startswith(("scripts/", "src/", "tests/")) or not name.endswith(".py"):
            raise ValueError("evaluation_source_path_not_python_source")
        path = ROOT / name
        ready.relative(path)
        if pilot.sha256(path.read_bytes().replace(b"\r\n", b"\n")) != expected:
            raise ValueError("evaluation_source_checksum_mismatch")
    paths = {key: ROOT / item["path"] for key, item in plan["inputs"].items()}
    hashes = {key: item["sha256"] for key, item in plan["inputs"].items()}
    for path in paths.values():
        name = ready.relative(path)
        if not name.startswith(("data/training/", "data/models/", ".local/")):
            raise ValueError("evaluation_input_outside_train_artifacts")
    execution, _ = bound_json(paths["execution_plan"], hashes["execution_plan"])
    if runner_source(execution) not in plan["source_sha256_lf"]:
        raise ValueError("selected_execution_runner_source_not_frozen")
    context = validated_training(paths, hashes)
    base = ROOT / plan["base_snapshot_path"]
    if ready.relative(base) != "models/e5":
        raise ValueError("frozen_base_snapshot_required")
    spec = models.load_model_manifest()["models"]["e5"]
    checkpoint, checkpoint_hash = bound_json(paths["checkpoint_manifest"], hashes["checkpoint_manifest"])
    expected = checkpoint_manifest(context["train_report"], dict(context["bindings"]), base, spec)
    if checkpoint != expected:
        raise ValueError("checkpoint_manifest_replay_mismatch")
    context["bindings"].update({ready.relative(plan_path): digest,
                               ready.relative(paths["checkpoint_manifest"]): checkpoint_hash})
    context.update({"evaluation_plan": plan, "evaluation_sha256": digest,
                    "base_snapshot": base, "base_spec": spec, "checkpoint": checkpoint,
                    "terminal_snapshot": ROOT / checkpoint["checkpoint_path"]})
    return context


def metric_question(question: dict) -> dict:
    if question["partition"] != "calibration" or len(question["evidence"]) != 1:
        raise ValueError("only_single_fact_calibration_questions_allowed")
    return {**question, "query": question["question"], "category": question["query_type"],
            "answerability": "positive", "relevant_document_ids":
            sorted({e["document_id"] for e in question["evidence"]}),
            "evidence": [{**e, "grade": 2, "evidence_group_id": question["id"] + ":fact"}
                         for e in question["evidence"]]}


def outcome(question: dict, hits: list[dict], documents: dict) -> dict:
    adapted = metric_question(question)
    scored = score_question(adapted, hits, documents)
    coverage = candidate_coverage(adapted, hits, limit=50)
    ranks = [rank for span in scored["evidence_spans"]
             for rank in span["covering_chunk_ranks_within_10"]]
    metrics = {key: scored["metrics"][key] for key in
               ("evidence_all_at_5_chunks", "document_hit_at_5_within_10_chunks",
                "document_reciprocal_rank_within_10_chunks")}
    metrics.update({"evidence_all_at_50_chunks": coverage["all_required_evidence_recall_at_50"],
                    "evidence_mrr_at_10_chunks": 1 / min(ranks) if ranks else 0.0})
    return {"question_id": question["id"], "question_sha256": question_hash(question),
            "language": question["language"], "cross_language": scored["cross_language"],
            "human_review": "pending", "metrics": metrics, "candidate_coverage": coverage,
            "evidence_spans": scored["evidence_spans"],
            "ranked_chunks": [{"rank": rank, **pilot.compact_chunk(hit), "score": hit["score"]}
                              for rank, hit in enumerate(hits, 1)]}


def aggregate(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("empty_calibration_denominator")
    return {"questions": len(rows), **{metric: {
        "sum": sum(row["metrics"][metric] for row in rows),
        "mean": sum(row["metrics"][metric] for row in rows) / len(rows)} for metric in METRICS}}


def comparison(base: list[dict], terminal: list[dict]) -> dict:
    if [row["question_id"] for row in base] != [row["question_id"] for row in terminal]:
        raise ValueError("paired_calibration_question_order_mismatch")
    old, new = aggregate(base), aggregate(terminal)
    changes = {}
    for metric in METRICS:
        pairs = [{"question_id": a["question_id"], "base": a["metrics"][metric],
                  "terminal": b["metrics"][metric],
                  "delta": float(b["metrics"][metric]) - float(a["metrics"][metric])}
                 for a, b in zip(base, terminal, strict=True)]
        changes[metric] = {"gain_ids": [p["question_id"] for p in pairs if p["delta"] > 0],
                           "regression_ids": [p["question_id"] for p in pairs if p["delta"] < 0],
                           "tie_ids": [p["question_id"] for p in pairs if p["delta"] == 0],
                           "per_question": pairs}
    primary_delta = new["evidence_all_at_50_chunks"]["sum"] - old["evidence_all_at_50_chunks"]["sum"]
    evidence_delta = new["evidence_all_at_5_chunks"]["sum"] - old["evidence_all_at_5_chunks"]["sum"]
    passed = primary_delta >= 1 and evidence_delta >= 0
    return {"base": old, "terminal": new, "paired_changes": changes,
            "primary_question_count_delta": primary_delta, "evidence_at5_question_count_delta": evidence_delta,
            "calibration_gate_passed": passed,
            "decision": "eligible_for_separate_frozen_main_dev_gate" if passed else "retain_base",
            "service_adoption": False}


def method_report(rows: list[dict]) -> dict:
    return {"questions": rows, "metrics": aggregate(rows), "breakdowns": {
        field: {value: aggregate([row for row in rows if row[field] == value])
                for value in sorted({row[field] for row in rows})}
        for field in ("language", "cross_language")}}


def replay_method(saved: dict, context: dict) -> dict:
    by_id = {chunk["chunk_id"]: chunk for chunk in context["candidates"]}
    order = {chunk["chunk_id"]: index for index, chunk in enumerate(context["candidates"])}
    if [row["question_id"] for row in saved["questions"]] != [q["id"] for q in context["questions"]]:
        raise ValueError("saved_calibration_coverage_mismatch")
    rebuilt = []
    for question, row in zip(context["questions"], saved["questions"], strict=True):
        hits, seen = [], set()
        if len(row["ranked_chunks"]) != min(50, len(by_id)):
            raise ValueError("saved_candidate_count_mismatch")
        for rank, reference in enumerate(row["ranked_chunks"], 1):
            chunk = by_id.get(reference["chunk_id"])
            if (chunk is None or chunk["chunk_id"] in seen or reference.get("rank") != rank
                    or any(reference.get(k) != v for k, v in pilot.compact_chunk(chunk).items())
                    or not isinstance(reference.get("score"), (int, float))
                    or not math.isfinite(reference["score"])):
                raise ValueError("saved_candidate_reference_or_score_mismatch")
            seen.add(chunk["chunk_id"])
            hits.append({**chunk, "score": reference["score"]})
        if hits != sorted(hits, key=lambda hit: (-hit["score"], order[hit["chunk_id"]])):
            raise ValueError("saved_dense_rank_order_mismatch")
        expected = outcome(question, hits, context["documents"])
        if row != expected:
            raise ValueError("saved_question_metric_or_provenance_mismatch")
        rebuilt.append(expected)
    expected = method_report(rebuilt)
    if saved != expected:
        raise ValueError("saved_aggregate_or_breakdown_mismatch")
    return expected


def replay_report(report: dict, context: dict) -> dict:
    payload = {key: value for key, value in report.items() if key != "payload_sha256"}
    if (report.get("payload_sha256") != pilot.fingerprint(payload)
            or report.get("status") != "passed" or report.get("configuration") != CONFIG
            or report.get("inputs_sha256") != context["bindings"]
            or report.get("source_sha256_lf") != context["evaluation_plan"]["source_sha256_lf"]
            or report.get("evaluation_plan_sha256") != context["evaluation_sha256"]
            or set(report.get("methods", {})) != {"base", "terminal"}
            or report.get("main_dev_accessed") is not False or report.get("test_accessed") is not False
            or report.get("original_base_unchanged") is not True):
        raise ValueError("evaluation_receipt_provenance_or_payload_mismatch")
    methods = {name: replay_method(report["methods"][name], context) for name in ("base", "terminal")}
    expected = comparison(methods["base"]["questions"], methods["terminal"]["questions"])
    if report.get("comparison") != expected:
        raise ValueError("saved_promotion_decision_mismatch")
    validate_measurements(report.get("measurements", {}), context)
    return {"scope": "saved_ranking_metric_and_provenance_replay", "fresh_inference": False,
            "questions_per_model": len(context["questions"]), "comparison": expected,
            "latency_and_memory": "saved_observations_not_remeasured"}


def validate_measurements(measurements: dict, context: dict) -> None:
    if set(measurements) != {"base", "terminal"}:
        raise ValueError("missing_comparison_measurements")
    for name, saved in measurements.items():
        if saved.get("dtype") != "torch.float32":
            raise ValueError("saved_inference_dtype_mismatch")
        for field, ids, key in (
            ("passage_tokens", [c["chunk_id"] for c in context["candidates"]], "chunk_id"),
            ("query_tokens", [q["id"] for q in context["questions"]], "question_id"),
        ):
            if [row.get(key) for row in saved.get(field, [])] != ids:
                raise ValueError("saved_token_telemetry_coverage_mismatch")
        warmup = saved.get("warmup_tokens", [])
        tokens = warmup + saved["passage_tokens"] + saved["query_tokens"]
        if len(warmup) != 4:
            raise ValueError("saved_warmup_telemetry_mismatch")
        for row in tokens:
            length = row.get("tokens_before_truncation")
            if (type(length) is not int or length < 1 or row.get("truncated") != (length > 512)):
                raise ValueError("invalid_saved_token_telemetry")
        if any(row["truncated"] for row in saved["query_tokens"]):
            raise ValueError("calibration_query_truncated")
        expected = {"tokenized_inputs": len(tokens),
                    "truncated_inputs": sum(t["truncated"] for t in tokens),
                    "tokens_before_truncation": sum(t["tokens_before_truncation"] for t in tokens),
                    "max_tokens_before_truncation": max(t["tokens_before_truncation"] for t in tokens)}
        if saved.get("truncation") != expected:
            raise ValueError("saved_truncation_aggregate_mismatch")
        timing = saved.get("query_encode_plus_dense_rank", {})
        samples = timing.get("samples_ms", [])
        if (len(samples) != len(context["questions"])
                or any(not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0 for t in samples)
                or timing.get("requests") != len(samples)):
            raise ValueError("saved_query_timing_coverage_mismatch")
        # Samples are rounded independently in the frozen timing helper; aggregate
        # rounding may differ by <= 0.001 per request and is not fresh measurement.
        if not isinstance(timing.get("total_ms"), (int, float)) or abs(
                timing["total_ms"] - sum(samples)) > 0.001 * (len(samples) + 1):
            raise ValueError("saved_query_timing_total_mismatch")
        recalculated = timing_summary(samples)
        if any(timing.get(key) != recalculated[key] for key in ("p50_ms", "p95_ms")):
            raise ValueError("saved_query_timing_percentile_mismatch")
        resources = saved.get("resources", {})
        if set(resources) != {name + suffix for suffix in ("_load", "_warmup", "_passage_prefill", "_queries")}:
            raise ValueError("saved_resource_stage_coverage_mismatch")
        for resource in resources.values():
            for field in ("wall_ms", "process_rss_sampled_peak_bytes",
                          "cuda_allocator_peak_allocated_bytes", "cuda_allocator_peak_reserved_bytes"):
                value = resource.get(field)
                if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError("invalid_saved_resource_measurement")


def verify_runtime_bindings(context: dict) -> None:
    for name, digest in context["bindings"].items():
        if models.file_sha256(ROOT / name) != digest:
            raise ValueError("evaluation_input_changed_during_execution")
    for name, digest in context["evaluation_plan"]["source_sha256_lf"].items():
        if pilot.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")) != digest:
            raise ValueError("evaluation_source_changed_during_execution")


class TerminalEncoder(models.LocalE5Encoder):
    """Reuse frozen encoding implementation; change only verified trained weights/config."""

    def __init__(self, checkpoint: Path, specification: dict, base_snapshot: Path):
        self.spec = specification
        self.verified_files = models.verify_snapshot(checkpoint, specification)
        torch, tokenizer_class, encoder_class, _ = models._load_runtime()
        if not torch.cuda.is_available():
            raise RuntimeError("requested_cuda_unavailable")
        self.torch, self.device, self.batch_size = torch, "cuda", 8
        self.telemetry = {"tokenized_inputs": 0, "truncated_inputs": 0,
                          "tokens_before_truncation": 0, "max_tokens_before_truncation": 0}
        self.telemetry_inputs = []
        self.tokenizer = tokenizer_class.from_pretrained(str(base_snapshot), local_files_only=True,
                                                         trust_remote_code=False, use_fast=True)
        if not self.tokenizer.is_fast or self.tokenizer.truncation_side != "right":
            raise ValueError("fast_right_truncating_base_tokenizer_required")
        self.dtype = torch.float32
        self.model = encoder_class.from_pretrained(
            str(checkpoint), local_files_only=True, trust_remote_code=False, use_safetensors=True,
            torch_dtype=torch.float32, attn_implementation="eager").to("cuda").eval()


def run_comparison(context: dict, output: Path) -> dict:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    report = {"schema_version": 1, "status": "started", "configuration": CONFIG,
              "evaluation_plan_sha256": context["evaluation_sha256"],
              "inputs_sha256": context["bindings"],
              "source_sha256_lf": context["evaluation_plan"]["source_sha256_lf"],
              "runtime": {}, "device": None, "methods": {}, "measurements": {},
              "main_dev_accessed": False, "test_accessed": False, "human_review": "pending",
              "quality_claim": "provisional_AI_labels_on_internal_train_calibration_only"}
    output.mkdir(parents=True)
    journal = Journal(output / "progress.jsonl")
    encoder, torch = None, None
    try:
        import numpy as np
        import psutil
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("requested_cuda_unavailable")
        report.update({"runtime": {name: version(name)
                                    for name in ("torch", "transformers", "tokenizers", "numpy")},
                       "device": torch.cuda.get_device_name()})
        for name in ("base", "terminal"):
            random.seed(CONFIG["seed"])
            np.random.seed(CONFIG["seed"])
            torch.manual_seed(CONFIG["seed"])
            torch.cuda.manual_seed_all(CONFIG["seed"])
            resources, timings = {}, []
            report["measurements"][name] = {"resources": resources}
            with stage(name + "_load", journal, resources, torch, psutil):
                encoder = (models.LocalE5Encoder(context["base_snapshot"], device="cuda", batch_size=8)
                           if name == "base" else TerminalEncoder(context["terminal_snapshot"],
                              context["checkpoint"], context["base_snapshot"]))
            with stage(name + "_warmup", journal, resources, torch, psutil):
                for _ in range(CONFIG["warmup_repetitions"]):
                    encoder.encode_passages([CONFIG["warmup_passage"]])
                    encoder.encode_queries([CONFIG["warmup_query"]])
            warmup_tokens = list(encoder.telemetry_inputs)
            passage_start = len(encoder.telemetry_inputs)
            with stage(name + "_passage_prefill", journal, resources, torch, psutil):
                passages = encoder.encode_passages([c["text"] for c in context["candidates"]])
            passage_tokens = [{"chunk_id": c["chunk_id"], **item} for c, item in zip(
                context["candidates"], encoder.telemetry_inputs[passage_start:], strict=True)]
            query_start = len(encoder.telemetry_inputs)
            outcomes = []
            with stage(name + "_queries", journal, resources, torch, psutil):
                for question in context["questions"]:
                    encoded, encode_ms = timed(partial(encoder.encode_queries, [question["question"]]),
                                               encoder.synchronize)
                    hits, rank_ms = timed(partial(models.rank_dense, encoded[0], passages,
                                          context["candidates"], limit=50), encoder.synchronize)
                    row = outcome(question, hits, context["documents"])
                    outcomes.append(row)
                    timings.append(encode_ms + rank_ms)
                    journal.write("calibration_query_completed", model=name, question_id=question["id"],
                                  query_encode_ms=encode_ms, dense_rank_ms=rank_ms,
                                  ranked_chunks=row["ranked_chunks"], metrics=row["metrics"])
            report["methods"][name] = method_report(outcomes)
            report["measurements"][name].update({"query_encode_plus_dense_rank": timing_summary(timings),
                "warmup_tokens": warmup_tokens, "passage_tokens": passage_tokens,
                "query_tokens": [{"question_id": q["id"], **item} for q, item in zip(
                    context["questions"], encoder.telemetry_inputs[query_start:], strict=True)],
                "truncation": dict(encoder.telemetry), "dtype": str(encoder.dtype)})
            encoder.close()
            encoder = None
            del passages
            gc.collect()
            torch.cuda.empty_cache()
        models.verify_snapshot(context["base_snapshot"], context["base_spec"])
        models.verify_snapshot(context["terminal_snapshot"], context["checkpoint"])
        verify_runtime_bindings(context)
        report.update({"original_base_unchanged": True, "status": "passed",
                       "comparison": comparison(report["methods"]["base"]["questions"],
                                                report["methods"]["terminal"]["questions"]),
                       "limitations": ["One internal calibration comparison is not statistical significance.",
                           "AI labels and token survival do not establish semantic correctness.",
                           "Main dev/test and Java service adoption remain separate gates.",
                           "Replay validates saved rankings and metrics, not fresh inference or latency.",
                           "Document reciprocal rank and evidence MRR are separately named metrics."]})
        report["payload_sha256"] = pilot.fingerprint(report)
        replay_report(report, context)
    except BaseException as error:
        report.update({"status": "failed", "failure_type": type(error).__name__,
                       "failure_code": "oom" if torch is not None and isinstance(error, torch.OutOfMemoryError)
                       else "evaluation_failed_no_retry_no_partial_promotion"})
        raise
    finally:
        if encoder is not None:
            with contextlib.suppress(Exception):
                encoder.close()
        journal.close()
        report = training.finite_metadata(report)
        report.pop("payload_sha256", None)
        report["payload_sha256"] = pilot.fingerprint(report)
        ready.public_safe(report)
        pilot.write_or_verify(output / "report.json", pilot.json_bytes(report))
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("checkpoint", "run", "replay"))
    parser.add_argument("--evaluation-plan", type=Path)
    parser.add_argument("--execution-plan", type=Path)
    parser.add_argument("--ready-manifest", type=Path)
    parser.add_argument("--train-report", type=Path)
    parser.add_argument("--probe-report", type=Path)
    parser.add_argument("--base-snapshot", type=Path, default=ROOT / "models/e5")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "checkpoint":
        keys = ("execution_plan", "ready_manifest", "train_report", "probe_report")
        if any(getattr(args, key) is None for key in keys) or args.output is None:
            parser.error("checkpoint requires execution plan, ready manifest, train/probe reports and output")
        context = validated_training({key: getattr(args, key) for key in keys})
        specification = models.load_model_manifest()["models"]["e5"]
        result = checkpoint_manifest(context["train_report"], context["bindings"],
                                     args.base_snapshot, specification)
        ready.relative(args.output)
        pilot.write_or_verify(args.output, pilot.json_bytes(result), args.verify)
        print(json.dumps({"checkpoint_verified": True, "inference_executed": False}))
        return
    if args.evaluation_plan is None:
        parser.error("run/replay require --evaluation-plan")
    context = load_evaluation(args.evaluation_plan)
    if args.command == "replay":
        if args.report is None:
            parser.error("replay requires --report")
        report, _ = bound_json(args.report)
        result = replay_report(report, context)
        print(json.dumps({"structural_replay": True, "fresh_inference": False,
                          "calibration_gate_passed": result["comparison"]["calibration_gate_passed"]}))
        return
    if args.output_dir is None or args.output_dir.exists():
        parser.error("run requires a new --output-dir")
    ready.relative(args.output_dir)
    with training.execution_guard(ROOT, context["evaluation_sha256"], "calibration"):
        result = run_comparison(context, args.output_dir)
    print(json.dumps({"status": result["status"], "comparison": result["comparison"]}))


if __name__ == "__main__":
    main()
