"""Frozen M3 local CUDA comparison; dev only, no API/ACL or answer-quality claims."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import subprocess
import threading
import time
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import partial
from importlib.metadata import version
from pathlib import Path

from doctrail.ingest import extract
from doctrail.retrieval import chunk_content, rank_chunks
from scripts.evaluate_dataset import (
    METRIC_KEYS,
    breakdown,
    require_dev,
    score_question,
    sha256,
    source_hashes,
    summarize,
)

ROOT = Path(__file__).resolve().parents[1]
FROZEN_INPUTS = {
    "input_manifest": "e4d33997b5589bd8d9cc5c56691da5940eba3a7b6554c671b8c39b78910fe69a",
    "input_questions": "9cce5a304f3f430c626aae2c1c0f267e0f3abc2dba16ccd7f9ec2f3989d28cb2",
}
METHODS = ("bm25", "dense_e5", "hybrid", "hybrid_reranked", "hybrid_budget50")
CONFIG = {
    "question_split": "dev",
    "test_evaluation": "always_locked",
    "expected_documents": 313,
    "expected_chunks": 3588,
    "expected_questions": 79,
    "chunk_characters": 1000,
    "overlap_characters": 150,
    "bm25": {"k1": 1.5, "b": 0.75, "candidates": 50},
    "dense_e5": {"candidates": 50, "passage_batch_size": 8, "queries_per_call": 1},
    "hybrid": {"bm25_candidates": 50, "dense_candidates": 50, "rrf_k": 60, "keep": 50},
    "hybrid_reranked": {"input": "same_hybrid_50", "batch_size": 1, "keep": 10},
    "hybrid_budget50": {
        "bm25_candidates": 25, "dense_candidates": 25, "rrf_k": 60, "keep": 50,
        "role": "equal_branch_candidate_budget_diagnostic",
    },
    "device": "cuda",
    "dtype": {"e5": "float32", "reranker": "float16"},
    "seed": 42,
    "warmup_query": "What is a Kubernetes Pod?",
    "warmup_passage": "A Pod is the smallest deployable unit of computing in Kubernetes.",
    "warmup_repetitions": 2,
    "measured_concurrency": 1,
    "final_chunks": 10,
    "evidence_chunks": 5,
    "metrics": "unchanged_M2_score_question_full_span_grade2_OR_within_group_AND_across_groups",
}


def now() -> str:
    return datetime.now(UTC).isoformat()


def digest_json(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8"))


class Journal:
    """Append-only checkpoints survive failure; never log raw queries or exception text."""

    def __init__(self, path: Path):
        self.path = path
        self.stage = "initialization"
        self.stream = path.open("x", encoding="utf-8", newline="\n")

    def write(self, event: str, **metadata) -> None:
        payload = {"at": now(), "event": event, "stage": self.stage, **metadata}
        self.stream.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def close(self) -> None:
        self.stream.close()


class ResourceScope:
    """Sample process RSS; CUDA allocator peaks are distinct, not whole-device usage."""

    def __init__(self, torch, psutil, device="cuda"):
        self.torch, self.device = torch, device
        self.process = psutil.Process()
        self.stop = threading.Event()
        self.peak = self.process.memory_info().rss
        self.samples = 0
        self.result = {}

    def sample(self):
        self.peak = max(self.peak, self.process.memory_info().rss)
        self.samples += 1

    def poll(self):
        while not self.stop.wait(0.05):
            self.sample()

    def __enter__(self):
        self.torch.cuda.synchronize(self.device)
        self.torch.cuda.reset_peak_memory_stats(self.device)
        self.sample()
        self.start_rss = self.process.memory_info().rss
        self.started = time.perf_counter()
        self.thread = threading.Thread(target=self.poll, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        try:
            self.torch.cuda.synchronize(self.device)
        finally:
            elapsed = (time.perf_counter() - self.started) * 1000
            self.stop.set()
            self.thread.join()
            self.sample()
        self.result = {
            "wall_ms": round(elapsed, 3),
            "process_rss_start_bytes": self.start_rss,
            "process_rss_sampled_peak_bytes": self.peak,
            "rss_samples": self.samples,
            "rss_sampling_interval_ms": 50,
            "cuda_allocator_peak_allocated_bytes": self.torch.cuda.max_memory_allocated(self.device),
            "cuda_allocator_peak_reserved_bytes": self.torch.cuda.max_memory_reserved(self.device),
            "scope": "current_process_RSS_including_CPU_models; current_process_CUDA_allocator_only",
        }


@contextmanager
def stage(name, journal, resources, torch, psutil):
    journal.stage = name
    journal.write("stage_started")
    measurement = ResourceScope(torch, psutil)
    try:
        with measurement:
            yield
    finally:
        resources[name] = measurement.result
        journal.write("stage_resource_checkpoint", resources=measurement.result)
    journal.write("stage_completed")


def timed(call, synchronize=lambda: None):
    synchronize()
    started = time.perf_counter()
    value = call()
    synchronize()
    return value, (time.perf_counter() - started) * 1000


def timing_summary(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {
        "requests": len(samples),
        "total_ms": round(sum(samples), 3),
        "p50_ms": round(ordered[math.ceil(len(ordered) * 0.5) - 1], 3) if ordered else None,
        "p95_ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3) if ordered else None,
        "samples_ms": [round(value, 3) for value in samples],
    }


def telemetry_delta(before: dict, after: dict) -> dict:
    return {
        (key + "_since_model_load" if key.startswith("max_") else key):
        value if key.startswith("max_") else value - before.get(key, 0)
        for key, value in after.items()
    }


def verify_baseline_parity(rows: list[dict], baseline: dict) -> dict:
    """Reject ranking/metric drift before crediting model gains over the M2 baseline."""
    old_rows = baseline["questions"]
    if [row["id"] for row in rows] != [row["id"] for row in old_rows]:
        raise ValueError("M2 baseline question order drift")
    for old, new in zip(old_rows, rows, strict=True):
        if old["metrics"] != new["metrics"] or old["ranked_chunks"] != new["ranked_chunks"]:
            raise ValueError("M2 baseline ranking or metric drift")
    if summarize(rows) != baseline["metrics"]:
        raise ValueError("M2 baseline aggregate metric drift")
    return {"passed": True, "questions": len(rows), "scope": "exact_top10_chunks_scores_and_metrics"}


def candidate_coverage(question: dict, hits: list[dict], limit: int = 50) -> dict:
    """Candidate ceiling uses one fully containing chunk per required fact group."""
    hits = hits[:limit]
    required = {s["evidence_group_id"] for s in question["evidence"] if s["grade"] == 2}
    covered = {
        s["evidence_group_id"]
        for s in question["evidence"] if s["grade"] == 2
        for hit in hits
        if hit["document_id"] == s["document_id"]
        and hit["start_offset"] <= s["start_offset"]
        and hit["end_offset"] >= s["end_offset"]
    }
    return {
        "candidate_count": len(hits),
        "unique_candidate_count": len({hit["chunk_id"] for hit in hits}),
        "unique_document_count": len({hit["document_id"] for hit in hits}),
        "required_evidence_groups": sorted(required),
        "covered_evidence_groups": sorted(covered),
        f"all_required_evidence_recall_at_{limit}": covered == required if required else None,
        f"evidence_group_recall_at_{limit}": len(covered) / len(required) if required else None,
    }


def fusion_diagnostic(question, bm25, dense, fused):
    left, right = {r["chunk_id"] for r in bm25}, {r["chunk_id"] for r in dense}
    union = list({row["chunk_id"]: row for row in bm25 + dense}.values())
    coverage = candidate_coverage(question, union, limit=100)
    return {
        "bm25_count": len(bm25), "dense_count": len(dense),
        "intersection_unique_count": len(left & right), "union_unique_count": len(left | right),
        "retained_unique_count": len({row["chunk_id"] for row in fused}),
        "dropped_unique_count": len((left | right) - {row["chunk_id"] for row in fused}),
        "all_required_evidence_recall_in_union": coverage["all_required_evidence_recall_at_100"],
        "evidence_group_recall_in_union": coverage["evidence_group_recall_at_100"],
        "covered_evidence_groups_in_union": coverage["covered_evidence_groups"],
    }


def input_records(records: list[dict], identifiers: list[str], field: str) -> list[dict]:
    if len(records) != len(identifiers):
        raise ValueError("Per-input tokenization telemetry does not match input identities")
    return [{field: identifier, **record}
            for identifier, record in zip(identifiers, records, strict=True)]


def coverage_summary(rows: list[dict]) -> dict:
    positives = [row["candidates"] for row in rows if row["expected_document_ids"]]
    return {
        "annotated_positive_questions": len(positives),
        "all_required_evidence_recall_at_50": (
            sum(row["all_required_evidence_recall_at_50"] for row in positives) / len(positives)
            if positives else None
        ),
        "evidence_group_recall_at_50": (
            sum(row["evidence_group_recall_at_50"] for row in positives) / len(positives)
            if positives else None
        ),
        "candidate_unique_count_min": min((r["candidates"]["unique_candidate_count"] for r in rows), default=None),
        "candidate_unique_count_max": max((r["candidates"]["unique_candidate_count"] for r in rows), default=None),
        "candidate_unique_count_mean": (
            sum(r["candidates"]["unique_candidate_count"] for r in rows) / len(rows) if rows else None
        ),
    }


def paired_changes(baseline: list[dict], challenger: list[dict]) -> dict:
    if [r["id"] for r in baseline] != [r["id"] for r in challenger]:
        raise ValueError("Paired question IDs must be identical and ordered")
    result = {}
    for metric in METRIC_KEYS:
        gains, regressions, ties = [], [], []
        deltas = []
        for old, new in zip(baseline, challenger, strict=True):
            left, right = old["metrics"][metric], new["metrics"][metric]
            if left is None or right is None:
                continue
            delta = float(right) - float(left)
            deltas.append({"id": old["id"], "before": left, "after": right, "delta": delta})
            (gains if delta > 0 else regressions if delta < 0 else ties).append(old["id"])
        result[metric] = {
            "paired_positive_questions": len(deltas), "gain_ids": gains,
            "regression_ids": regressions, "tie_ids": ties, "per_question": deltas,
            "mean_delta": sum(row["delta"] for row in deltas) / len(deltas) if deltas else None,
        }
    return result


def prepare_inputs(manifest_path, questions_path, frozen_hashes, root):
    from scripts.prepare_corpus import load_verified_corpus
    from scripts.question_dataset import read_questions, validate_questions

    if any(frozen_hashes.get(key) != value for key, value in FROZEN_INPUTS.items()):
        raise ValueError("M3 requires unchanged frozen M2 corpus manifest and dev v1.1 questions")
    corpus = load_verified_corpus(manifest_path, root=root)
    questions = read_questions(questions_path)
    validation = validate_questions(
        questions, corpus, allowed_split="dev", manifest_sha256=frozen_hashes["input_manifest"]
    )
    documents, candidates, hashes = {}, [], {}
    for row in sorted(corpus, key=lambda item: item["id"]):
        source = row["content"].encode("utf-8")
        actual = sha256(source)
        if actual != row["normalized_sha256"]:
            raise ValueError("Normalized corpus checksum drift")
        content, pages = extract(source, "md")
        documents[row["id"]] = {**row, "content": content}
        chunks = chunk_content(content, pages)
        hashes[row["id"]] = {
            "raw_sha256": row["sha256"], "actual_normalized_sha256": actual,
            "actual_ingested_sha256": sha256(content.encode("utf-8")), "chunks": len(chunks),
        }
        for chunk in chunks:
            candidates.append({
                "document_id": row["id"], "chunk_id": f"{row['id']}:{chunk.ordinal}",
                "title": row["title"], "filename": f"{row['id']}.md", "text": chunk.text,
                "page": chunk.page, "start_offset": chunk.start_offset, "end_offset": chunk.end_offset,
            })
    if (len(documents), len(candidates), len(questions)) != (313, 3588, 79):
        raise ValueError("Frozen M3 document/chunk/question counts differ from 313/3588/79")
    for question in questions:
        for span in question["evidence"]:
            content = documents[span["document_id"]]["content"]
            if content[span["start_offset"]:span["end_offset"]] != span["quote"]:
                raise ValueError("Evidence offsets mismatch after service extraction")
    return corpus, questions, validation, documents, candidates, hashes


def compact_hits(hits):
    return [{key: hit[key] for key in (
        "document_id", "chunk_id", "score", "start_offset", "end_offset", "page"
    )} for hit in hits]


def build_outcome(question, final_hits, candidates, documents):
    outcome = score_question(question, final_hits, documents)
    outcome["candidates"] = candidate_coverage(question, candidates)
    outcome["candidate_chunks"] = compact_hits(candidates)
    if not outcome["expected_document_ids"]:
        diagnosis = "no_positive_annotation_diagnostic_only"
    elif outcome["metrics"]["evidence_all_at_5_chunks"]:
        diagnosis = "all_required_evidence_at_5"
    elif outcome["candidates"]["all_required_evidence_recall_at_50"]:
        diagnosis = "candidate_ceiling_sufficient_final_top5_missed"
    else:
        diagnosis = "candidate_50_missing_required_evidence"
    outcome["candidate_vs_final_diagnostic"] = diagnosis
    return outcome


def evaluate(manifest_path: Path, questions_path: Path, model_manifest_path: Path,
             e5_snapshot: Path, reranker_snapshot: Path, journal: Journal,
             split: str = "dev", *, root=ROOT) -> dict:
    require_dev(split)
    import psutil
    import torch

    from doctrail.model_retrieval import (
        LocalBGEReranker,
        LocalE5Encoder,
        load_model_manifest,
        rank_dense,
        rrf_fuse,
        verify_snapshot,
    )

    if not torch.cuda.is_available():
        raise ValueError("M3 prescribed CUDA runtime is unavailable; no CPU fallback")
    import random

    import numpy as np

    random.seed(CONFIG["seed"])
    np.random.seed(CONFIG["seed"])
    torch.manual_seed(CONFIG["seed"])
    torch.cuda.manual_seed_all(CONFIG["seed"])
    created_at = now()
    frozen = source_hashes(root, manifest_path, questions_path)
    model_manifest_digest = sha256(model_manifest_path.read_bytes())
    baseline_path = root / "experiments/results/m2-bm25-dev-v1.1.json"
    baseline_digest = sha256(baseline_path.read_bytes())
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if any(baseline["source_sha256"].get(key) != value for key, value in FROZEN_INPUTS.items()):
        raise ValueError("M2 comparison baseline has different frozen inputs")
    models = load_model_manifest(model_manifest_path)
    specifications = models["models"]
    snapshots = {"e5": e5_snapshot, "reranker": reranker_snapshot}
    journal.stage = "input_verification"
    journal.write("stage_started", source_sha256=frozen,
                  model_manifest_sha256=model_manifest_digest, config_sha256=digest_json(CONFIG))
    model_files = {key: verify_snapshot(path, specifications[key]) for key, path in snapshots.items()}
    corpus, questions, validation, documents, candidates, corpus_hashes = prepare_inputs(
        manifest_path, questions_path, frozen, root
    )
    candidate_digest = digest_json(candidates)
    journal.write("stage_completed", documents=len(documents), chunks=len(candidates),
                  questions=len(questions), candidate_sha256=candidate_digest,
                  model_files_sha256=model_files)
    git = lambda *args: subprocess.check_output(["git", *args], cwd=root, text=True).strip()
    git_commit, git_dirty = git("rev-parse", "HEAD"), bool(git("status", "--porcelain"))
    runtime = {
        "python": platform.python_version(), "os": platform.system(),
        "machine": platform.machine(), "logical_cpu_count": os.cpu_count(),
        "system_ram_total_bytes": psutil.virtual_memory().total,
        "gpu_name": torch.cuda.get_device_name(0),
        "gpu_total_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
        "cuda_runtime": torch.version.cuda, "cudnn": torch.backends.cudnn.version(),
        "torch_cuda_matmul_allow_tf32": torch.backends.cuda.matmul.allow_tf32,
        "torch_cudnn_allow_tf32": torch.backends.cudnn.allow_tf32,
        "torch_deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "torch_cudnn_deterministic": torch.backends.cudnn.deterministic,
        "torch_cudnn_benchmark": torch.backends.cudnn.benchmark,
        "seed": CONFIG["seed"], "bitwise_gpu_determinism": "not_guaranteed",
        "model_dtypes": {},
        "packages": {name: version(name) for name in (
            "torch", "transformers", "numpy", "huggingface-hub", "safetensors", "psutil"
        )},
    }
    journal.write("runtime_checkpoint", runtime=runtime, model_specifications=specifications)
    resources, telemetry, per_input_telemetry = {}, {}, {}
    fusion_diagnostics = {"hybrid": [], "hybrid_budget50": []}
    rankings = {method: [] for method in METHODS}
    timings = {key: [] for key in ("bm25", "e5_query_encode", "dense_score", "hybrid_fusion",
                                  "hybrid_budget50_fusion", "rerank")}
    with stage("bm25_warmup", journal, resources, torch, psutil):
        for _ in range(CONFIG["warmup_repetitions"]):
            rank_chunks(CONFIG["warmup_query"], candidates, limit=50)
    with stage("bm25_measured_queries", journal, resources, torch, psutil):
        for question in questions:
            hits, elapsed = timed(partial(rank_chunks, question["query"], candidates, limit=50))
            rankings["bm25"].append(hits)
            timings["bm25"].append(elapsed)
            journal.write("query_completed", question_id=question["id"], elapsed_ms=elapsed,
                          candidates=compact_hits(hits))
    baseline_parity = verify_baseline_parity([
        score_question(question, rankings["bm25"][index], documents)
        for index, question in enumerate(questions)
    ], baseline)
    baseline_parity["report_sha256"] = baseline_digest
    journal.write("m2_baseline_parity", **baseline_parity)
    encoder = None
    try:
        with stage("e5_load", journal, resources, torch, psutil):
            encoder = LocalE5Encoder(e5_snapshot, device="cuda", batch_size=8)
            if encoder.spec != specifications["e5"]:
                raise ValueError("Loaded E5 specification differs from supplied manifest")
            runtime["model_dtypes"]["e5"] = str(encoder.dtype)
            journal.write("model_loaded", model="e5", dtype=str(encoder.dtype), batch_size=8)
        with stage("e5_warmup", journal, resources, torch, psutil):
            before = dict(encoder.telemetry)
            for _ in range(CONFIG["warmup_repetitions"]):
                encoder.encode_passages([CONFIG["warmup_passage"]])
                encoder.encode_queries([CONFIG["warmup_query"]])
            telemetry["e5_warmup"] = telemetry_delta(before, encoder.telemetry)
            per_input_telemetry["e5_warmup"] = input_records(
                encoder.telemetry_inputs,
                ["synthetic_passage_1", "synthetic_query_1", "synthetic_passage_2", "synthetic_query_2"],
                "warmup_input_id",
            )
        with stage("e5_offline_passage_prefill", journal, resources, torch, psutil):
            before = dict(encoder.telemetry)
            input_start = len(encoder.telemetry_inputs)
            passage_embeddings = encoder.encode_passages([row["text"] for row in candidates])
            telemetry["e5_offline_passage_prefill"] = telemetry_delta(before, encoder.telemetry)
            per_input_telemetry["e5_offline_passage_prefill"] = input_records(
                encoder.telemetry_inputs[input_start:], [row["chunk_id"] for row in candidates], "chunk_id"
            )
            journal.write("prefill_completed", embeddings_shape=list(passage_embeddings.shape),
                          telemetry=telemetry["e5_offline_passage_prefill"],
                          per_input_telemetry=per_input_telemetry["e5_offline_passage_prefill"])
        with stage("e5_measured_queries_and_fusion", journal, resources, torch, psutil):
            before = dict(encoder.telemetry)
            input_start = len(encoder.telemetry_inputs)
            for index, question in enumerate(questions):
                query_tokens_before = dict(encoder.telemetry)
                encoded, encode_ms = timed(
                    partial(encoder.encode_queries, [question["query"]]), encoder.synchronize
                )
                dense, score_ms = timed(
                    partial(rank_dense, encoded[0], passage_embeddings, candidates, limit=50),
                    encoder.synchronize,
                )
                bm25 = rankings["bm25"][index]
                hybrid, fusion_ms = timed(partial(rrf_fuse, [bm25, dense], candidates, limit=50, k=60))
                budget, budget_ms = timed(
                    partial(rrf_fuse, [bm25[:25], dense[:25]], candidates, limit=50, k=60)
                )
                fusion_diagnostics["hybrid"].append(fusion_diagnostic(question, bm25, dense, hybrid))
                fusion_diagnostics["hybrid_budget50"].append(
                    fusion_diagnostic(question, bm25[:25], dense[:25], budget)
                )
                for name, value in (("dense_e5", dense), ("hybrid", hybrid),
                                    ("hybrid_budget50", budget)):
                    rankings[name].append(value)
                for name, value in (("e5_query_encode", encode_ms), ("dense_score", score_ms),
                                    ("hybrid_fusion", fusion_ms), ("hybrid_budget50_fusion", budget_ms)):
                    timings[name].append(value)
                journal.write("query_completed", question_id=question["id"],
                              encode_ms=encode_ms, dense_score_ms=score_ms,
                              telemetry=telemetry_delta(query_tokens_before, encoder.telemetry),
                              dense=compact_hits(dense), hybrid=compact_hits(hybrid),
                              hybrid_budget50=compact_hits(budget))
            telemetry["e5_measured_queries"] = telemetry_delta(before, encoder.telemetry)
            per_input_telemetry["e5_measured_queries"] = input_records(
                encoder.telemetry_inputs[input_start:], [row["id"] for row in questions], "question_id"
            )
    finally:
        if encoder is not None:
            journal.write("model_telemetry_checkpoint", model="e5", telemetry=encoder.telemetry,
                          inputs_in_processing_order=encoder.telemetry_inputs)
            encoder.close()
            journal.write("model_released", model="e5")
    # Passage vectors remain on CPU; the E5 model is released before BGE loads.
    reranker = None
    try:
        with stage("reranker_load", journal, resources, torch, psutil):
            reranker = LocalBGEReranker(reranker_snapshot, device="cuda", batch_size=1)
            if reranker.spec != specifications["reranker"]:
                raise ValueError("Loaded reranker specification differs from supplied manifest")
            runtime["model_dtypes"]["reranker"] = str(reranker.dtype)
            journal.write("model_loaded", model="reranker", dtype=str(reranker.dtype), batch_size=1)
        with stage("reranker_warmup", journal, resources, torch, psutil):
            before = dict(reranker.telemetry)
            for _ in range(CONFIG["warmup_repetitions"]):
                reranker.rerank(CONFIG["warmup_query"], [
                    {**candidates[0], "text": CONFIG["warmup_passage"]}
                ], limit=1)
            telemetry["reranker_warmup"] = telemetry_delta(before, reranker.telemetry)
            per_input_telemetry["reranker_warmup"] = input_records(
                reranker.telemetry_inputs, ["synthetic_pair_1", "synthetic_pair_2"], "warmup_input_id"
            )
        with stage("reranker_measured_queries", journal, resources, torch, psutil):
            before = dict(reranker.telemetry)
            per_input_telemetry["reranker_measured_queries"] = []
            for index, question in enumerate(questions):
                query_tokens_before = dict(reranker.telemetry)
                input_start = len(reranker.telemetry_inputs)
                hits, elapsed = timed(
                    partial(reranker.rerank, question["query"], rankings["hybrid"][index], limit=10),
                    reranker.synchronize,
                )
                expected_ids = {row["chunk_id"] for row in rankings["hybrid"][index]}
                actual_ids = [row["chunk_id"] for row in hits]
                if len(actual_ids) != len(set(actual_ids)) or not set(actual_ids) <= expected_ids:
                    raise ValueError("Reranker changed the fixed hybrid candidate pool")
                if len(hits) != min(10, len(expected_ids)):
                    raise ValueError("Reranker returned an incomplete final result")
                rankings["hybrid_reranked"].append(hits)
                timings["rerank"].append(elapsed)
                pair_tokens = input_records(
                    reranker.telemetry_inputs[input_start:],
                    [row["chunk_id"] for row in rankings["hybrid"][index]], "chunk_id"
                )
                per_input_telemetry["reranker_measured_queries"].append({
                    "question_id": question["id"], "pairs": pair_tokens,
                })
                journal.write("query_completed", question_id=question["id"], elapsed_ms=elapsed,
                              telemetry=telemetry_delta(query_tokens_before, reranker.telemetry),
                              per_input_telemetry=pair_tokens,
                              final_chunks=compact_hits(hits))
            telemetry["reranker_measured_queries"] = telemetry_delta(before, reranker.telemetry)
    finally:
        if reranker is not None:
            journal.write("model_telemetry_checkpoint", model="reranker", telemetry=reranker.telemetry,
                          inputs_in_processing_order=reranker.telemetry_inputs)
            reranker.close()
            journal.write("model_released", model="reranker")
    journal.stage = "metrics_and_drift_verification"
    journal.write("stage_started")
    outcomes = {
        method: [build_outcome(
            question, rankings[method][index],
            rankings["hybrid" if method == "hybrid_reranked" else method][index], documents
        ) for index, question in enumerate(questions)]
        for method in METHODS
    }
    for method in ("hybrid", "hybrid_budget50", "hybrid_reranked"):
        diagnostics = fusion_diagnostics["hybrid" if method == "hybrid_reranked" else method]
        for row, diagnostic in zip(outcomes[method], diagnostics, strict=True):
            row["fusion_candidate_diagnostic"] = diagnostic
    if source_hashes(root, manifest_path, questions_path) != frozen:
        raise ValueError("Evaluation source or input checksum drift during run")
    if sha256(model_manifest_path.read_bytes()) != model_manifest_digest:
        raise ValueError("Model manifest checksum drift during run")
    if sha256(baseline_path.read_bytes()) != baseline_digest:
        raise ValueError("M2 baseline report checksum drift during run")
    for key, path in snapshots.items():
        if verify_snapshot(path, specifications[key]) != model_files[key]:
            raise ValueError("Local model snapshot checksum drift during run")
    from scripts.prepare_corpus import load_verified_corpus
    verified_again = load_verified_corpus(manifest_path, root=root)
    if {row["id"]: sha256(row["content"].encode("utf-8")) for row in verified_again} != {
        key: row["actual_normalized_sha256"] for key, row in corpus_hashes.items()
    }:
        raise ValueError("Corpus checksum drift during run")
    # Sum measured serial components, explicitly not an end-to-end live request.
    method_timings = {}
    components = {
        "bm25": ["bm25"], "dense_e5": ["e5_query_encode", "dense_score"],
        "hybrid": ["bm25", "e5_query_encode", "dense_score", "hybrid_fusion"],
        "hybrid_reranked": ["bm25", "e5_query_encode", "dense_score", "hybrid_fusion", "rerank"],
        "hybrid_budget50": ["bm25", "e5_query_encode", "dense_score", "hybrid_budget50_fusion"],
    }
    for method, names in components.items():
        method_timings[method] = {
            **timing_summary([sum(timings[name][i] for name in names) for i in range(len(questions))]),
            "components": names,
        }
    comparisons = {f"{name}_vs_bm25": paired_changes(outcomes["bm25"], outcomes[name])
                   for name in METHODS if name != "bm25"}
    comparisons["hybrid_reranked_vs_hybrid"] = paired_changes(
        outcomes["hybrid"], outcomes["hybrid_reranked"]
    )
    method_reports = {}
    for method, rows in outcomes.items():
        method_reports[method] = {
            "metrics": summarize(rows), "candidate_recall": coverage_summary(rows),
            "breakdowns": {field: breakdown(rows, field)
                           for field in ("category", "language", "cross_language")},
            "candidate_breakdowns": {
                field: {value: coverage_summary([row for row in rows if row[field] == value])
                        for value in sorted({row[field] for row in rows})}
                for field in ("category", "language", "cross_language")
            },
            "failure_diagnostics": dict(Counter(r["candidate_vs_final_diagnostic"] for r in rows)),
            "questions": rows,
        }
    journal.write("stage_completed", source_and_inputs_unchanged=True, model_files_unchanged=True)
    return {
        "schema_version": 1, "status": "measured_local_cuda_development_unreviewed_annotations",
        "created_at": created_at, "completed_at": now(), "git_commit": git_commit,
        "git_dirty": git_dirty, "source_sha256": frozen, "config": CONFIG,
        "config_sha256": digest_json(CONFIG), "runtime": runtime,
        "model_manifest_sha256": model_manifest_digest, "model_specifications": specifications,
        "local_model_files_sha256": model_files, "evaluated_corpus_sha256": corpus_hashes,
        "candidate_sha256": candidate_digest,
        "m2_baseline_parity": baseline_parity,
        "before_after_drift_checks": {"source_inputs": True, "corpus": True, "models": True},
        "dataset": {
            "documents": len(documents), "chunks": len(candidates), "questions": len(questions),
            "question_split": "dev", "validation": validation,
            "indexed_document_splits": dict(Counter(row["split"] for row in corpus)),
            "human_review_status_counts": dict(Counter(row["human_review"] for row in questions)),
            "question_provenance_counts": dict(Counter(row["created_by"] for row in questions)),
            "index_scope": "all_frozen_manifest_documents_including_other_splits; no_training",
        },
        "methods": method_reports, "paired_comparisons": comparisons,
        "timing": {
            "stage_components": {key: timing_summary(values) for key, values in timings.items()},
            "method_serial_component_sums": method_timings,
            "definition": "CUDA_synchronized_local_serial_inference_and_ranking; prefill_and_load_excluded",
            "query_order": [row["id"] for row in questions],
            "warmup": {"repetitions": 2, "input_selection": "fixed_synthetic_CONFIG_text",
                       "resources_and_tokens": "separate_warmup_stages"},
        },
        "resources_by_stage": resources, "tokenization_by_stage": telemetry,
        "tokenization_per_input": per_input_telemetry,
        "cost": {"external_api_requests": 0, "external_api_cost_usd": 0,
                 "local_electricity_and_hardware_cost": "not_measured"},
        "limitations": [
            "AI-authored development labels are incomplete and human review is pending; no test evaluation.",
            "Evidence uses exact full-span containment in one chunk; chunk-boundary misses remain unchanged.",
            "Source-span recall scores full returned chunks; model-visible evidence after 512-token truncation is not measured.",
            "Candidate recall is an upper bound under known labels, not reranker or semantic correctness.",
            "No-evidence empty returns are diagnostic only, not calibrated abstention.",
            "Hybrid unions up to 100 branch candidates then keeps 50; budget50 unions at most 50.",
            "Budget50 timing reuses top50 branch measurements; it is not optimized top25 execution.",
            "Method times sum separately measured components; they are not observed live end-to-end requests.",
            "Offline document embedding prefill, model loading and warmups are reported separately.",
            "RSS sampling can miss short peaks; CUDA peaks cover PyTorch allocator, not entire GPU or driver.",
            "OS caches, power state and background load are uncontrolled; one local serial pass, no load test.",
            "No service API, ACL integration, generated answer, training or production deployment measured.",
        ],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--model-manifest", type=Path, default=ROOT / "data/models/m3-models.json")
    parser.add_argument("--e5-snapshot", type=Path, default=ROOT / "models/e5")
    parser.add_argument("--reranker-snapshot", type=Path, default=ROOT / "models/reranker")
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        require_dev(args.split)
        stage_path = args.output.with_suffix(args.output.suffix + ".stages.jsonl")
        if args.output.exists() or stage_path.exists():
            raise ValueError("Refusing to overwrite a past report or stage journal; use a new run name")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        journal = Journal(stage_path)
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    try:
        journal.write("run_started", config=CONFIG)
        report = evaluate(args.manifest, args.questions, args.model_manifest,
                          args.e5_snapshot, args.reranker_snapshot, journal, args.split)
        # Paths are repository-relative in shareable provenance; never expose host home paths.
        report["invocation"] = {
            "module": "scripts.evaluate_retrieval",
            "arguments": {key: (value.resolve().relative_to(ROOT).as_posix()
                                if value.resolve().is_relative_to(ROOT) else value.name)
                          if isinstance(value, Path) else value for key, value in vars(args).items()},
            "path_policy": "repository_relative; external_paths_reduced_to_basename",
        }
        serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        with args.output.open("x", encoding="utf-8", newline="\n") as output:
            output.write(serialized)
            output.flush()
            os.fsync(output.fileno())
        journal.stage = "completion"
        journal.write("run_completed", report_sha256=sha256(serialized.encode("utf-8")))
    except BaseException as exc:  # noqa: BLE001 - persist interrupts and failures without raw text
        journal.write("run_failed", safe_error_code="M3_EVALUATION_FAILED",
                      exception_type=type(exc).__name__)
        raise SystemExit(f"M3_EVALUATION_FAILED ({type(exc).__name__}); inspect stage journal") from None
    finally:
        journal.close()
    print(json.dumps({"status": "completed", "report": args.output.name,
                      "methods": {key: value["metrics"] for key, value in report["methods"].items()}}))


if __name__ == "__main__":
    main()
