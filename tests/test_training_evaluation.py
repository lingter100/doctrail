"""Synthetic calibration/receipt tests; no model inference or real quality claims."""

import copy
import json

import pytest

from scripts import evaluate_training as evaluation
from scripts import prepare_training as pilot


@pytest.fixture
def context():
    documents, candidates = {}, []
    for index in range(6):
        identifier = f"document-{index}"
        text = f"Synthetic fact number {index}."
        documents[identifier] = {"id": identifier, "content": text,
                                  "language": "en" if index % 2 == 0 else "ko", "split": "train"}
        candidates.append({"document_id": identifier, "chunk_id": identifier + ":0",
                           "family_id": f"family-{index}", "text": text,
                           "text_sha256": pilot.sha256(text.encode()),
                           "start_offset": 0, "end_offset": len(text), "page": None})
    questions = [{"id": f"m4-cal-{i + 1:03d}", "partition": "calibration",
                  "question": f"Synthetic question {i}?", "question_family_id": f"intent-{i}",
                  "language": "ko", "query_type": "semantic", "human_review": "pending",
                  "evidence": [{"document_id": f"document-{i}", "start_offset": 0,
                                "end_offset": len(documents[f"document-{i}"]["content"]),
                                "quote": documents[f"document-{i}"]["content"]}]}
                 for i in range(2)]
    return {"documents": documents, "candidates": candidates, "questions": questions,
            "bindings": {"data/training/synthetic.json": "a" * 64},
            "evaluation_sha256": "b" * 64,
            "evaluation_plan": {"source_sha256_lf": {"scripts/synthetic.py": "c" * 64}}}


def ranked(context, order=None):
    candidates = context["candidates"]
    order = order or list(range(len(candidates)))
    return [{**candidates[index], "score": 1 - rank * .1} for rank, index in enumerate(order)]


def report(context):
    outcomes = [evaluation.outcome(q, ranked(context), context["documents"])
                for q in context["questions"]]
    method = evaluation.method_report(outcomes)
    measurements = {}
    for name in ("base", "terminal"):
        token = {"tokens_before_truncation": 10, "truncated": False}
        measurements[name] = {
            "dtype": "torch.float32", "warmup_tokens": [dict(token) for _ in range(4)],
            "passage_tokens": [{"chunk_id": c["chunk_id"], **token} for c in context["candidates"]],
            "query_tokens": [{"question_id": q["id"], **token} for q in context["questions"]],
            "truncation": {"tokenized_inputs": 12, "truncated_inputs": 0,
                           "tokens_before_truncation": 120, "max_tokens_before_truncation": 10},
            "query_encode_plus_dense_rank": evaluation.timing_summary([1.0, 2.0]),
            "resources": {name + suffix: {"wall_ms": 1, "process_rss_sampled_peak_bytes": 10,
                                          "cuda_allocator_peak_allocated_bytes": 10,
                                          "cuda_allocator_peak_reserved_bytes": 10}
                          for suffix in ("_load", "_warmup", "_passage_prefill", "_queries")}}
    result = {"status": "passed", "configuration": evaluation.CONFIG,
              "inputs_sha256": context["bindings"],
              "source_sha256_lf": context["evaluation_plan"]["source_sha256_lf"],
              "evaluation_plan_sha256": context["evaluation_sha256"],
              "methods": {"base": method, "terminal": copy.deepcopy(method)},
              "comparison": evaluation.comparison(outcomes, outcomes), "measurements": measurements,
              "main_dev_accessed": False, "test_accessed": False, "original_base_unchanged": True}
    reseal(result)
    return result


def reseal(value):
    value["payload_sha256"] = pilot.fingerprint({k: v for k, v in value.items() if k != "payload_sha256"})


def test_reuses_full_source_evidence_and_named_document_metrics(context):
    question = context["questions"][0]
    hits = ranked(context, [1, 2, 3, 4, 5, 0])
    result = evaluation.outcome(question, hits, context["documents"])
    assert result["metrics"]["evidence_all_at_50_chunks"] is True
    assert result["metrics"]["evidence_all_at_5_chunks"] is False
    assert result["metrics"]["evidence_mrr_at_10_chunks"] == pytest.approx(1 / 6)
    assert result["metrics"]["document_hit_at_5_within_10_chunks"] is False
    assert "query" not in result and "question" not in result
    assert result["cross_language"] == "cross_language_only"
    evaluation.ready.public_safe(result)


def test_partial_source_span_not_counted_as_complete_evidence(context):
    question = context["questions"][0]
    hits = ranked(context)
    hits[0] = {**hits[0], "end_offset": 8, "text": hits[0]["text"][:8]}
    result = evaluation.outcome(question, hits, context["documents"])
    assert result["metrics"]["evidence_all_at_50_chunks"] is False
    assert result["metrics"]["document_hit_at_5_within_10_chunks"] is True
    assert result["metrics"]["evidence_mrr_at_10_chunks"] == 0


def test_only_calibration_single_fact_questions(context):
    for invalid in ({**context["questions"][0], "partition": "fit"},
                    {**context["questions"][0], "evidence": []}):
        with pytest.raises(ValueError, match="calibration"):
            evaluation.metric_question(invalid)


@pytest.mark.parametrize("primary,evidence,passed", [(0, 0, False), (-1, 0, False),
                                                    (1, -1, False), (1, 0, True)])
def test_preregistered_net_gain_and_no_evidence_regression_gate(context, primary, evidence, passed):
    base = [evaluation.outcome(q, ranked(context), context["documents"]) for q in context["questions"]]
    base[0]["metrics"]["evidence_all_at_50_chunks"] = 1
    base[0]["metrics"]["evidence_all_at_5_chunks"] = 1
    changed = copy.deepcopy(base)
    changed[0]["metrics"]["evidence_all_at_50_chunks"] += primary
    changed[0]["metrics"]["evidence_all_at_5_chunks"] += evidence
    result = evaluation.comparison(base, changed)
    assert result["calibration_gate_passed"] is passed
    assert result["service_adoption"] is False
    if not passed:
        assert result["decision"] == "retain_base"


def test_paired_ids_cannot_change_denominator(context):
    rows = [evaluation.outcome(q, ranked(context), context["documents"]) for q in context["questions"]]
    with pytest.raises(ValueError, match="paired_calibration"):
        evaluation.comparison(rows, rows[::-1])


def test_saved_ranking_replay_is_explicitly_not_fresh_inference(context):
    result = evaluation.replay_report(report(context), context)
    assert result["fresh_inference"] is False
    assert result["latency_and_memory"] == "saved_observations_not_remeasured"
    assert result["comparison"]["decision"] == "retain_base"


@pytest.mark.parametrize("mutation", ["hash", "duplicate", "rank", "nonfinite", "metric", "dropped"])
def test_saved_rankings_and_metrics_reject_tampering(context, mutation):
    saved = report(context)
    row = saved["methods"]["base"]["questions"][0]
    if mutation == "hash":
        row["ranked_chunks"][0]["text_sha256"] = "tampered"
    elif mutation == "duplicate":
        row["ranked_chunks"][1] = copy.deepcopy(row["ranked_chunks"][0])
    elif mutation == "rank":
        row["ranked_chunks"][0]["rank"] = 2
    elif mutation == "nonfinite":
        row["ranked_chunks"][0]["score"] = float("nan")
    elif mutation == "metric":
        row["metrics"]["evidence_mrr_at_10_chunks"] = 0
    else:
        row["ranked_chunks"].pop()
    reseal(saved)
    with pytest.raises(ValueError):
        evaluation.replay_report(saved, context)


@pytest.mark.parametrize("mutation", ["dtype", "token_coverage", "truncation", "timing", "resources"])
def test_saved_measurement_provenance_checked_without_remeasurement(context, mutation):
    saved = report(context)
    measured = saved["measurements"]["terminal"]
    if mutation == "dtype":
        measured["dtype"] = "torch.float16"
    elif mutation == "token_coverage":
        measured["query_tokens"].pop()
    elif mutation == "truncation":
        measured["truncation"]["truncated_inputs"] = 1
    elif mutation == "timing":
        measured["query_encode_plus_dense_rank"]["samples_ms"][0] = -1
    else:
        measured["resources"] = {}
    reseal(saved)
    with pytest.raises(ValueError):
        evaluation.replay_report(saved, context)


def training_fixture():
    recipe = {"seed": 20261012, "epochs": 2, "microbatch_queries": 2,
              "gradient_accumulation_steps": 4, "max_optimizer_steps": 16,
              "learning_rate": 1e-5, "resource_peak_allocated_limit_mib": 5376}
    triplets = [{"question_id": f"m4-fit-{i:03d}"} for i in range(1, 65)]
    schedule = list(evaluation.optimizer_batches(triplets, seed=recipe["seed"], epochs=2,
                                                microbatch=2, accumulation=4, max_steps=16))
    result = {"command": "train", "status": "passed", "execution_plan_sha256": "a" * 64,
              "ready_manifest_sha256": "b" * 64, "recipe": recipe, "training_executed": True,
              "terminal_checkpoint_saved": True, "quality_evaluation_executed": False,
              **{key: 16 for key in ("optimizer_groups_started", "optimizer_steps_attempted",
                  "optimizer_step_calls", "optimizer_steps_completed", "optimizer_steps_verified",
                  "optimizer_steps", "weight_updates_observed")},
              "steps": [{"epoch": g["epoch"], "optimizer_step": g["optimizer_step"],
                         "question_count": 8, "question_ids": [r["question_id"]
                          for batch in g["microbatches"] for r in batch], "status": "passed",
                         "optimizer_update_verified": True, "weight_change_observed": True,
                         "learning_rate": 1e-5, "loss": 1.0, "peak_allocated_mib": 1000}
                        for g in schedule]}
    return result, recipe, triplets


def test_exact_successful_terminal_training_gate():
    trained, recipe, triplets = training_fixture()
    evaluation.validate_train_report(trained, "a" * 64, "b" * 64, recipe, triplets)
    for field in ("optimizer_steps_completed", "optimizer_steps_verified", "weight_updates_observed"):
        changed = copy.deepcopy(trained)
        changed[field] = 15
        with pytest.raises(ValueError, match="exact_16"):
            evaluation.validate_train_report(changed, "a" * 64, "b" * 64, recipe, triplets)
    trained["steps"][0]["question_ids"][0] = "changed"
    with pytest.raises(ValueError, match="schedule_or_update"):
        evaluation.validate_train_report(trained, "a" * 64, "b" * 64, recipe, triplets)


def test_failure_or_intermediate_training_cannot_evaluate():
    trained, recipe, triplets = training_fixture()
    for field, value in (("status", "failed"), ("terminal_checkpoint_saved", False),
                         ("training_executed", False), ("execution_plan_sha256", "tampered")):
        changed = {**trained, field: value}
        with pytest.raises(ValueError, match="exact_16"):
            evaluation.validate_train_report(changed, "a" * 64, "b" * 64, recipe, triplets)


def checkpoint_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "ROOT", tmp_path)
    monkeypatch.setattr(evaluation.ready, "relative", lambda path: path.resolve().relative_to(tmp_path).as_posix())
    monkeypatch.setattr(evaluation.models, "verify_snapshot", lambda *a: {})
    base = tmp_path / "models/e5"
    terminal = tmp_path / ".local/train/terminal"
    base.mkdir(parents=True)
    terminal.mkdir(parents=True)
    config = {"hidden_size": 4, "model_type": "synthetic", "transformers_version": "original"}
    (base / "config.json").write_bytes(pilot.json_bytes(config))
    for name in evaluation.CHECKPOINT_FILES:
        (terminal / name).write_bytes(pilot.json_bytes(config) if name == "config.json" else b"synthetic")
    trained = {"checkpoint_path": ".local/train/terminal", "checkpoint_sha256": {
        name: pilot.sha256((terminal / name).read_bytes()) for name in evaluation.CHECKPOINT_FILES}}
    spec = {"repo_id": "synthetic", "revision": "frozen", "files": {
        "model.safetensors": {"sha256": "a" * 64}}}
    return trained, base, terminal, spec


def test_terminal_manifest_binds_actual_report_bytes_and_rejects_tamper(tmp_path, monkeypatch):
    trained, base, terminal, spec = checkpoint_fixture(tmp_path, monkeypatch)
    result = evaluation.checkpoint_manifest(trained, {"train_report.json": "b" * 64}, base, spec)
    assert result["checkpoint_kind"] == "sole_terminal_after_16_verified_updates"
    assert result["inputs_sha256"] == {"train_report.json": "b" * 64}
    (terminal / "model.safetensors").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="differs_from_training_report"):
        evaluation.checkpoint_manifest(trained, {}, base, spec)


def test_executable_extra_file_cannot_be_loaded(tmp_path, monkeypatch):
    trained, base, terminal, spec = checkpoint_fixture(tmp_path, monkeypatch)
    (terminal / "modeling.py").write_text("unsafe")
    with pytest.raises(ValueError, match="unsafe_or_incomplete"):
        evaluation.checkpoint_manifest(trained, {}, base, spec)


def test_only_config_metadata_may_change():
    evaluation.compatible_config({"hidden_size": 4, "transformers_version": "old"},
                                  {"hidden_size": 4, "transformers_version": "new"})
    with pytest.raises(ValueError, match="architecture_changed"):
        evaluation.compatible_config({"hidden_size": 4}, {"hidden_size": 8})


def test_pinned_save_serialization_metadata_does_not_change_architecture_gate():
    # Shape of the CPU-only AutoConfig round-trip observed on the pinned snapshot;
    # this is not a saved model, weight load, or inference test.
    base = {"_name_or_path": "tmp/", "architectures": ["BertModel"], "model_type": "bert",
            "hidden_size": 384, "num_hidden_layers": 12, "num_attention_heads": 12,
            "max_position_embeddings": 512, "torch_dtype": "float32",
            "transformers_version": "4.29.0", "use_cache": True}
    terminal = {key: value for key, value in base.items()
                if key not in {"_name_or_path", "torch_dtype", "transformers_version"}}
    terminal.update(dtype="float32", transformers_version="4.57.6")
    evaluation.compatible_config(base, terminal)
    for field, value in (("architectures", ["BertForMaskedLM"]), ("model_type", "roberta"),
                         ("hidden_size", 768), ("num_hidden_layers", 6),
                         ("max_position_embeddings", 1024), ("use_cache", False)):
        with pytest.raises(ValueError, match="architecture_changed"):
            evaluation.compatible_config(base, {**terminal, field: value})
    with pytest.raises(ValueError, match="architecture_changed"):
        evaluation.compatible_config(base, {**terminal, "new_unreviewed_semantic_default": True})


def test_public_artifacts_contain_no_corpus_text(context):
    saved = report(context)
    evaluation.ready.public_safe(saved)
    serialized = json.dumps(saved)
    assert "Synthetic fact" not in serialized and "Synthetic question" not in serialized


def test_evaluation_plan_rejects_policy_drift_before_loading_training_inputs(monkeypatch):
    plan = {"schema_version": 1, "evaluation_id": "m4-calibration-v1",
            "configuration": {**evaluation.CONFIG, "dtype": "float16"},
            "inputs": {key: {} for key in evaluation.INPUT_KEYS},
            "source_sha256_lf": {name: "a" * 64 for name in evaluation.REQUIRED_SOURCES}}
    monkeypatch.setattr(evaluation, "bound_json", lambda *args: (plan, "b" * 64))
    with pytest.raises(ValueError, match="frozen_evaluation_plan"):
        evaluation.load_evaluation(evaluation.ROOT / "synthetic-unused.json")


def test_model_free_replay_rejects_false_promotion_and_source_drift(context):
    saved = report(context)
    saved["comparison"]["calibration_gate_passed"] = True
    reseal(saved)
    with pytest.raises(ValueError, match="promotion_decision"):
        evaluation.replay_report(saved, context)
    saved = report(context)
    saved["source_sha256_lf"] = {}
    reseal(saved)
    with pytest.raises(ValueError, match="provenance_or_payload"):
        evaluation.replay_report(saved, context)


def test_execution_runner_versions_are_lazy_and_explicitly_allowlisted(monkeypatch):
    imported = []
    monkeypatch.setattr(evaluation.importlib, "import_module", lambda name: imported.append(name))
    assert imported == []
    for version in ("v1", "v2"):
        execution = {"execution_id": "m4-e5-execution-" + version}
        evaluation.execution_runner(execution)
        assert evaluation.runner_source(execution) == (
            "scripts/train_embedding.py" if version == "v1" else "scripts/train_embedding_v2.py")
    assert imported == ["scripts.train_embedding", "scripts.train_embedding_v2"]
    with pytest.raises(ValueError, match="unsupported_evaluation_execution_runner"):
        evaluation.execution_runner({"execution_id": "arbitrary.module"})
    assert len(imported) == 2


@pytest.mark.parametrize("field", ["grad_scaler_configured_init_scale", "grad_scaler_actual_initial_scale",
                                   "grad_scaler_current_scale", "grad_scaler_scale_before_unscale",
                                   "grad_scaler_scale_before_clip", "grad_scaler_scale_before_step",
                                   "grad_scaler_scale", "resource_followup_plan_sha256"])
def test_followup_actual_scale_proof_cannot_contradict_declared_override(field):
    execution = {"execution_id": "m4-e5-execution-v2", "resource_followup_plan_sha256": "a" * 64,
                 "numerical_override": {"grad_scaler_init_scale": 1024.0}}
    report = {"resource_followup_plan_sha256": "a" * 64,
              "numerical_override": {"grad_scaler_init_scale": 1024.0},
              "grad_scaler_configured_init_scale": 1024.0, "grad_scaler_actual_initial_scale": 1024.0,
              "grad_scaler_current_scale": 1024.0, "steps": [{
                  "grad_scaler_actual_initial_scale": 1024.0, "grad_scaler_scale_before_unscale": 1024.0,
                  "grad_scaler_scale_before_clip": 1024.0, "grad_scaler_scale_before_step": 1024.0,
                  "grad_scaler_scale": 1024.0} for _ in range(16)]}
    evaluation.validate_numerical_receipt(execution, report)
    if field in report:
        report[field] = "changed" if field.endswith("sha256") else 65536.0
    else:
        report["steps"][-1][field] = 65536.0
    with pytest.raises(ValueError, match="actual_scale_or_binding_mismatch"):
        evaluation.validate_numerical_receipt(execution, report)


def test_public_plan_paths_reach_training_validation_without_model_loading(monkeypatch):
    plan_path = evaluation.ROOT / "data/training/m4-calibration-evaluation-v1.json"
    plan = json.loads(plan_path.read_bytes())
    # An in-memory source amendment exercises the saved plan's actual input paths;
    # the immutable original plan must still fail its old evaluator source hash.
    plan["source_sha256_lf"] = {
        name: pilot.sha256((evaluation.ROOT / name).read_bytes().replace(b"\r\n", b"\n"))
        for name in plan["source_sha256_lf"]}
    bound_json = evaluation.bound_json

    def amended_plan(path, expected=None):
        return (plan, "a" * 64) if path == plan_path else bound_json(path, expected)

    def stop_before_training_validation(paths, hashes):
        for key, name in evaluation.PUBLIC_REPORT_PATHS.items():
            assert evaluation.ready.relative(paths[key]) == name
            assert hashes[key] == plan["inputs"][key]["sha256"]
        raise RuntimeError("reached_training_validation_without_models")

    monkeypatch.setattr(evaluation, "bound_json", amended_plan)
    monkeypatch.setattr(evaluation, "validated_training", stop_before_training_validation)
    with pytest.raises(RuntimeError, match="reached_training_validation_without_models"):
        evaluation.load_evaluation(plan_path)


@pytest.mark.parametrize("key,path", [
    ("train_report", "experiments/results/m4-e5-probe-v2.json"),
    ("probe_report", "experiments/results/m4-e5-train-v2.json"),
    ("checkpoint_manifest", "experiments/results/m4-e5-train-v2.json"),
    ("execution_plan", "experiments/results/m4-e5-train-v2.json"),
    ("ready_manifest", "experiments/results/m4-e5-train-v2.json"),
    ("train_report", "experiments/results/m4-e5-train-v3.json"),
    ("probe_report", "experiments/results/m3-retrieval-dev-v1.json"),
    ("train_report", "data/evaluation/test.json"),
])
def test_public_report_exception_is_exact_and_role_bound(key, path):
    with pytest.raises(ValueError, match="outside_train_artifacts"):
        evaluation.validate_input_paths({key: evaluation.ROOT / path})


def test_public_report_exception_does_not_bypass_content_hashes(tmp_path):
    path = tmp_path / "report.json"
    path.write_bytes(b'{"status":"passed"}')
    # Path containment is separate; test the unchanged byte-binding check directly.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(evaluation.ready, "relative", lambda path: "experiments/results/m4-e5-train-v2.json")
        evaluation.validate_input_paths({"train_report": path})
        with pytest.raises(ValueError, match="input_checksum_mismatch"):
            evaluation.bound_json(path, "0" * 64)
