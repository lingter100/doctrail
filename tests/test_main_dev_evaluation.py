"""Synthetic receipt/metric adversarial cases; no fresh model or dev inference."""

import copy
import json
import subprocess
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from scripts import evaluate_main_dev as evaluation


@pytest.fixture
def context():
    documents, candidates = {}, []
    for i in range(60):
        name, text = f"doc-{i}", f"synthetic fact {i}: abcdefghijklmnopqrstuvwxyz"
        documents[name] = {"content": text, "language": "en" if i % 2 else "ko"}
        candidates.append({"document_id": name, "chunk_id": name + ":0", "text": text,
                           "start_offset": 0, "end_offset": len(text), "page": None})

    def span(index, group):
        return {"document_id": f"doc-{index}", "start_offset": 0, "end_offset": 10,
                "quote": documents[f"doc-{index}"]["content"][:10], "grade": 2,
                "evidence_group_id": group}

    questions = [
        {"id": "synthetic-or-and", "evidence": [span(0, "a"), span(2, "a"), span(1, "b")],
         "relevant_document_ids": ["doc-0", "doc-1", "doc-2"], "category": "multi_document"},
        {"id": "synthetic-single", "evidence": [span(55, "c")],
         "relevant_document_ids": ["doc-55"], "category": "semantic"},
        {"id": "synthetic-negative", "evidence": [], "relevant_document_ids": [], "category": "no_evidence"},
        {"id": "synthetic-ambiguous", "evidence": [], "relevant_document_ids": [], "category": "ambiguous"},
    ]
    for q in questions:
        q.update({"question_family_id": q["id"], "query": q["id"] + "?", "language": "ko",
                  "human_review": "pending", "answerability": "positive" if q["evidence"] else q["category"]})
    return {"documents": documents, "candidates": candidates, "questions": questions}


def ranked(context, order=None):
    order = list(range(60)) if order is None else order
    return [{**context["candidates"][index], "score": 1.0 - rank / 100}
            for rank, index in enumerate(order[:50])]


def outcomes(context, order=None):
    return [evaluation.outcome(q, ranked(context, order), context) for q in context["questions"]]


def synthetic_report(context):
    rows = outcomes(context)
    context.update({"bindings": {evaluation.PLAN_PATH: "a" * 64},
                    "identity": {"chunk_sha256": "b" * 64},
                    "plan": {"source_sha256_lf": {}}, "historical_source_sha256": {},
                    "public_receipts": {"synthetic": True}, "historical": copy.deepcopy(rows),
                    "values": {"historical": {"runtime": {}},
                               "checkpoint": {"files": {"model.safetensors": {"sha256": "c" * 64}}},
                               "model_manifest": {"models": {"e5": {"files": {"model.safetensors": {"sha256": "d" * 64}}}}}}})
    runtime = {**{k: v for k, v in evaluation.CONFIG.items() if k.startswith("torch_")},
               "seed": 42, "local_files_only": True, "python": "3.11.9", "gpu_total_memory_bytes": 1024,
               "torch_num_threads": 1, "torch_num_interop_threads": 1, "gpu_name": "synthetic",
               "cuda_runtime": "synthetic", "driver_version": "synthetic", "cudnn": 1, "packages": {"synthetic": "1"}}
    measurement = {}
    journal = [{"event": "evaluation_started", "plan_sha256": "a" * 64}]
    for name in evaluation.METHODS:
        token = {"tokens_before_truncation": 8, "truncated": False, "retained_tokens": 8,
                 "input_ids_attention_mask_sha256": "e" * 64}
        tokens = {"warmup": [dict(token) for _ in range(4)],
                  "passages": [{"chunk_id": c["chunk_id"], **token} for c in context["candidates"]],
                  "queries": [{"question_id": q["id"], **token} for q in context["questions"]]}
        samples = [{"question_id": q["id"], "encode_ms": i + .1, "rank_ms": .2,
                    "total_ms": i + .1 + .2} for i, q in enumerate(context["questions"])]
        resources = {name + "_" + stage: {"wall_ms": 1.0, "process_rss_start_bytes": 10,
                     "process_rss_sampled_peak_bytes": 20, "rss_samples": 2,
                     "cuda_allocator_peak_allocated_bytes": 10, "cuda_allocator_peak_reserved_bytes": 20}
                     for stage in ("load", "warmup", "passage_prefill", "queries")}
        measurement[name] = {"dtype": "torch.float32", "device": "cuda", "attention_implementation": "eager",
                             "failure_count": 0, "tokens": tokens, "query_timings": samples, "resources": resources,
                             "timing": {k: evaluation.timing_summary([s[k] for s in samples])
                                        for k in ("encode_ms", "rank_ms", "total_ms")},
                             "truncation": {"tokenized_inputs": 68, "truncated_inputs": 0,
                                            "tokens_before_truncation": 544, "max_tokens_before_truncation": 8}}
        for stage_name, resource in resources.items():
            journal.append({"event": "stage_started", "stage": stage_name})
            if stage_name.endswith("_queries"):
                if name == evaluation.METHODS[0]:
                    journal.append({"event": "fresh_dev_inference_started"})
                journal.extend({"event": "query_completed", "model": name, "question_id": q["id"],
                                "outcome_sha256": evaluation.digest_json(row), "timing": sample,
                                "candidate_chunks": row["candidate_chunks"], "metrics": row["metrics"]}
                               for q, row, sample in zip(context["questions"], rows, samples, strict=True))
            journal.extend([{"event": "stage_resource_checkpoint", "stage": stage_name, "resources": resource},
                            {"event": "stage_completed", "stage": stage_name}])
    decision = evaluation.comparison(rows, rows)
    journal.append({"event": "evaluation_completed", "decision": decision["decision"]})
    raw = evaluation.pilot.jsonl_bytes(journal)
    files = {"base_fresh": {"model.safetensors": "d" * 64}, "terminal_fresh": {"model.safetensors": "c" * 64}}
    report = {"status": "passed", "configuration": evaluation.CONFIG, "bindings": context["bindings"],
              "identity": context["identity"], "source_sha256_lf": {}, "historical_source_sha256": {},
              "public_receipts": context["public_receipts"], "test_question_accessed": False,
              "main_dev_accessed": True, "human_reviewed_questions": 0, "service_adoption": False,
              "fresh_dev_inference_started": True, "failure_count": 0, "freeze_commit": "f" * 40,
              "git_commit": "f" * 40, "model_files_before": files, "model_files_after": copy.deepcopy(files),
              "runtime": runtime, "methods": {name: evaluation.method_report(copy.deepcopy(rows)) for name in evaluation.METHODS},
              "comparison": decision, "historical_bridge": evaluation.historical_bridge(rows, context, runtime),
              "measurements": measurement, "journal_sha256": evaluation.pilot.sha256(raw)}
    reseal(report)
    return report, raw


def reseal(report):
    report["payload_sha256"] = evaluation.pilot.fingerprint({k: v for k, v in report.items() if k != "payload_sha256"})


def test_or_alternatives_and_multidocument_groups_completion_rank(context):
    order = [2, 3, 4, 5, 6, 1] + [i for i in range(60) if i not in {1, 2, 3, 4, 5, 6}]
    row = outcomes(context, order)[0]
    assert row["candidates"]["all_required_evidence_recall_at_50"] is True
    assert row["metrics"]["evidence_all_at_5_chunks"] is False
    assert row[evaluation.MRR] == pytest.approx(1 / 6)
    assert row["metrics"]["document_reciprocal_rank_within_10_chunks"] == 1
    assert row["groups_at5"]["groups"][0]["category"] == "covered"
    assert row["candidate_vs_final_diagnostic"] == "candidate_ceiling_sufficient_final_top5_missed"


def test_partial_adjacent_chunks_do_not_complete_boundary_span(context):
    question = copy.deepcopy(context["questions"][0])
    question["evidence"] = [{**question["evidence"][0], "start_offset": 4, "end_offset": 14,
                             "quote": context["documents"]["doc-0"]["content"][4:14]}]
    question["relevant_document_ids"] = ["doc-0"]
    original = context["candidates"][0]
    parts = [{**original, "chunk_id": f"doc-0:{i}", "start_offset": start, "end_offset": end,
              "text": original["text"][start:end]} for i, (start, end) in enumerate(((0, 10), (10, len(original["text"]))))]
    context["candidates"] = parts + context["candidates"][1:]
    row = evaluation.outcome(question, [{**c, "score": 1 - i / 100} for i, c in enumerate(context["candidates"][:50])], context)
    assert row["candidates"]["all_required_evidence_recall_at_50"] is False
    assert row[evaluation.MRR] == 0
    assert row["groups_at50"]["groups"][0]["category"] == "no_representable_full_span_chunk"


def test_negative_and_ambiguous_never_inflate_positive_gate(context):
    rows = outcomes(context)
    assert evaluation.exact_counts(rows)["positive_questions"] == 2
    for row in rows[2:]:
        assert all(value is None for value in row["metrics"].values())
        assert row[evaluation.MRR] is None
        assert row["candidates"]["all_required_evidence_recall_at_50"] is None
        assert len(row["candidate_chunks"]) == 50 and not row["empty_result"]
    better = outcomes(context, [55, *range(55), *range(56, 60)])
    assert evaluation.comparison(rows, better)["quality_gate_passed"] is True
    regressed = outcomes(context, [3, 4, 5, 6, 7, 55, 0, 1, 2, *range(8, 55), *range(56, 60)])
    assert evaluation.comparison(rows, regressed)["decision"] == "retain_base"


@pytest.mark.parametrize("damage", ["duplicate", "unknown", "offset", "nan", "tie", "question_hash", "top10", "aggregate", "order"])
def test_replay_rejects_corrupted_rankings_even_after_digest_resealing(context, damage):
    saved = evaluation.method_report(outcomes(context))
    row = saved["questions"][0]
    if damage == "duplicate":
        row["candidate_chunks"][1] = dict(row["candidate_chunks"][0])
    elif damage == "unknown":
        row["candidate_chunks"][0]["chunk_id"] = "deleted-or-private:0"
    elif damage == "offset":
        row["candidate_chunks"][0]["start_offset"] = 1
    elif damage == "nan":
        row["candidate_chunks"][0]["score"] = float("nan")
    elif damage == "tie":
        row["candidate_chunks"][0]["score"] = row["candidate_chunks"][1]["score"]
        row["candidate_chunks"][:2] = reversed(row["candidate_chunks"][:2])
    elif damage == "question_hash":
        row["question_sha256"] = "0" * 64
    elif damage == "top10":
        row["ranked_chunks"][0]["score"] += .001
    elif damage == "aggregate":
        saved["counts"]["positive_questions"] += 1
    else:
        saved["questions"].reverse()
    with pytest.raises(ValueError):
        evaluation.replay_method(saved, context)


def test_full_synthetic_report_replays_without_models(context):
    report, raw = synthetic_report(context)
    receipt = evaluation.replay_report(report, context, raw)
    assert receipt["status"] == "passed" and receipt["live_model_files_reverified"] is False
    assert receipt["comparison"]["decision"] == "retain_base"


@pytest.mark.parametrize("damage", ["gate", "token", "query_truncated", "percentile", "missing_sample", "precision", "resource", "checkpoint", "incomplete_journal"])
def test_resealed_report_still_rejects_false_runtime_or_decision(context, damage):
    report, raw = synthetic_report(context)
    measurement = report["measurements"]["terminal_fresh"]
    if damage == "gate":
        report["comparison"]["quality_gate_passed"] = True
    elif damage == "token":
        measurement["tokens"]["queries"][0]["input_ids_attention_mask_sha256"] = "0" * 64
    elif damage == "query_truncated":
        measurement["tokens"]["queries"][0].update(tokens_before_truncation=513, truncated=True, retained_tokens=512)
    elif damage == "percentile":
        measurement["timing"]["total_ms"]["p95_ms"] += 1
    elif damage == "missing_sample":
        measurement["query_timings"].pop()
    elif damage == "precision":
        measurement["dtype"] = "torch.float16"
    elif damage == "resource":
        measurement["resources"]["terminal_fresh_load"]["process_rss_sampled_peak_bytes"] = -1
    elif damage == "checkpoint":
        report["model_files_after"]["terminal_fresh"]["model.safetensors"] = "0" * 64
    else:
        raw = b"\n".join(raw.splitlines()[:-1]) + b"\n"
        report["journal_sha256"] = evaluation.pilot.sha256(raw)
    reseal(report)
    with pytest.raises(ValueError):
        evaluation.replay_report(report, context, raw)


@pytest.mark.parametrize("path", ["data/evaluation/m2-test-a.jsonl", "data/evaluation/../evaluation/m2-dev-v1.1.jsonl", "C:/private.json", "../outside.json"])
def test_plan_rejects_question_path_before_any_file_read(tmp_path, monkeypatch, path):
    plan = {"schema_version": 1, "evaluation_id": "m4-main-dev-v1", "plan_revision": "1",
            "status": "preregistered_not_run", "configuration": evaluation.CONFIG,
            "quality_gate": evaluation.QUALITY_GATE, "failure_policy": evaluation.FAILURE_POLICY,
            "primary_comparator": "base_fresh", "historical_bridge": "m3_dense_saved", "test": "locked",
            "service_adoption": False, "human_review": "pending",
            "input_bindings": {key: {"path": name, "sha256": "a" * 64} for key, name in evaluation.INPUT_PATHS.items()}}
    plan["input_bindings"]["questions"]["path"] = path
    monkeypatch.setattr(evaluation.models, "file_sha256", lambda p: pytest.fail("forbidden read"))
    with pytest.raises(ValueError, match="allowlisted"):
        evaluation.validate_plan(plan, tmp_path)


def test_public_receipt_validation_does_not_import_models_or_open_local_packs():
    code = '''
import importlib.abc, json, sys
from pathlib import Path
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'numpy', 'torch', 'transformers'}:
            raise AssertionError('heavy runtime imported')
sys.meta_path.insert(0, Block())
from scripts import evaluate_main_dev as e
original = Path.open
def guarded(self, *args, **kwargs):
    name = self.resolve().relative_to(e.ROOT.resolve()).as_posix()
    if name.startswith(('.local/', 'models/')) or '/m2-test-' in name:
        raise AssertionError('private model/pack/test read')
    return original(self, *args, **kwargs)
Path.open = guarded
b = {n: e.models.file_sha256(e.ROOT / n) for n in e.INPUT_PATHS.values()}
v = {k: json.loads((e.ROOT / n).read_bytes()) for k, n in e.INPUT_PATHS.items() if n.endswith('.json')}
assert e.validate_public_receipts(v, b)['optimizer_updates'] == 16
assert not {'torch', 'numpy', 'transformers'}.intersection(sys.modules)
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=evaluation.ROOT,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_exclusive_execution_claim_rejects_second_attempt(tmp_path):
    with (evaluation.training.execution_guard(tmp_path, "a" * 64, "main-dev"),
          pytest.raises(RuntimeError, match="another_model_execution"),
          evaluation.training.execution_guard(tmp_path, "b" * 64, "main-dev")):
        pytest.fail("concurrent run allowed")
    with (pytest.raises(FileExistsError),
          evaluation.training.execution_guard(tmp_path, "a" * 64, "main-dev")):
        pytest.fail("second attempt allowed")


def test_mid_query_failure_persists_completed_ranks_and_consumes_attempt(context, tmp_path, monkeypatch):
    """Exercise real lifecycle/finally/claim with synthetic runtime, never a model."""
    synthetic_report(context)
    context["root"] = tmp_path
    context["values"]["checkpoint"]["checkpoint_path"] = ".local/terminal"
    for directory in (tmp_path / "models/e5", tmp_path / ".local/terminal"):
        directory.mkdir(parents=True)
        (directory / "config.json").write_text("{}", encoding="utf-8")

    class Array:
        def __init__(self, rows):
            self.shape = (rows, 384)

        def __getitem__(self, _):
            return self

        def __gt__(self, _):
            return True

        def all(self):
            return True

    closed = []

    class Encoder:
        def __init__(self, *args, **kwargs):
            self.tokenizer = SimpleNamespace(is_fast=True, truncation_side="right")
            self.model = SimpleNamespace(config=SimpleNamespace(_attn_implementation="eager"),
                parameters=lambda: [SimpleNamespace(dtype="float32", device=SimpleNamespace(type="cuda"))])
            self.calls = 0

        def encode_passages(self, texts):
            # Main implementation checks the frozen complete-vector dimensions.
            return Array(3588 if len(texts) > 1 else 1)

        def encode_queries(self, texts):
            self.calls += 1
            if self.calls == 4:  # two warmups, one completed query, then failure
                raise RuntimeError("synthetic injected second-query failure")
            return Array(1)

        def synchronize(self):
            pass

        def close(self):
            closed.append(True)

    fake_torch = SimpleNamespace(
        float32="float32", manual_seed=lambda _: None, use_deterministic_algorithms=lambda _: None,
        cuda=SimpleNamespace(is_available=lambda: True, manual_seed_all=lambda _: None),
        backends=SimpleNamespace(cuda=SimpleNamespace(matmul=SimpleNamespace(allow_tf32=True)),
                                 cudnn=SimpleNamespace(allow_tf32=False, deterministic=True, benchmark=True)))
    fake_numpy = SimpleNamespace(random=SimpleNamespace(seed=lambda _: None), isfinite=lambda _: Array(1),
                                  all=lambda value: value, linalg=SimpleNamespace(norm=lambda *a, **k: Array(1)))
    for name, module in (("torch", fake_torch), ("numpy", fake_numpy), ("psutil", SimpleNamespace())):
        monkeypatch.setitem(sys.modules, name, module)

    @contextmanager
    def fake_stage(name, journal, resources, *args):
        journal.stage = name
        journal.write("stage_started")
        yield
        resources[name] = {}
        journal.write("stage_completed")

    monkeypatch.setattr(evaluation, "stage", fake_stage)
    monkeypatch.setattr(evaluation, "verify_freeze", lambda *args: None)
    monkeypatch.setattr(evaluation, "git", lambda root, *args: "f" * 40 if args[0] == "rev-parse" else "")
    monkeypatch.setattr(evaluation, "runtime_receipt", lambda *args: {"synthetic": True})
    monkeypatch.setattr(evaluation.models, "LocalE5Encoder", Encoder)
    monkeypatch.setattr(evaluation.models, "verify_snapshot", lambda path, spec: {k: v["sha256"] for k, v in spec["files"].items()})
    monkeypatch.setattr(evaluation.models, "rank_dense", lambda *args, **kwargs: ranked(context))
    output = tmp_path / "synthetic-run"
    with pytest.raises(RuntimeError, match="synthetic injected"):
        evaluation.run_comparison(context, output, "f" * 40)
    saved = json.loads((output / "report.json").read_bytes())
    assert saved["status"] == "failed" and saved["quality_decision"] is None
    assert saved["fresh_dev_inference_started"] is True and "comparison" not in saved
    assert len(saved["methods"]["base_fresh"]["questions"]) == 1
    assert len(saved["methods"]["base_fresh"]["questions"][0]["candidate_chunks"]) == 50
    assert saved["methods"]["base_fresh"]["questions"][0] == outcomes(context)[0]
    journal = [json.loads(line) for line in (output / "progress.jsonl").read_bytes().splitlines()]
    durable = next(row for row in journal if row["event"] == "query_completed")
    assert durable["candidate_chunks"] == outcomes(context)[0]["candidate_chunks"]
    assert "synthetic injected" not in (output / "progress.jsonl").read_text(encoding="utf-8")
    assert closed == [True]
    with pytest.raises(FileExistsError):
        evaluation.run_comparison(context, tmp_path / "second-output", "f" * 40)
