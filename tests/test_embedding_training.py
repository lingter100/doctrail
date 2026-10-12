import contextlib
import copy
import json
import math
import sys
from types import SimpleNamespace

import pytest

from doctrail.training import (
    UpdateProgress,
    constant_learning_rate,
    optimizer_batches,
    per_query_contrastive_loss,
)
from scripts import prepare_training as pilot
from scripts import train_embedding as runner


def test_frozen_schedule_covers_every_question_per_epoch_once():
    rows = [{"question_id": f"q-{n:03d}"} for n in range(64)]
    kwargs = {"seed": 20261012, "epochs": 2, "microbatch": 2, "accumulation": 4, "max_steps": 16}
    schedule = list(optimizer_batches(rows, **kwargs))
    assert schedule == list(optimizer_batches(list(reversed(rows)), **kwargs))
    assert len(schedule) == 16
    for epoch in (1, 2):
        seen = [row["question_id"] for step in schedule if step["epoch"] == epoch
                for batch in step["microbatches"] for row in batch]
        assert sorted(seen) == sorted(row["question_id"] for row in rows)
    assert schedule[0]["microbatches"] != schedule[8]["microbatches"]


def test_partial_accumulation_and_step_limit_preserve_explicit_denominator():
    rows = [{"question_id": str(n)} for n in range(11)]
    schedule = list(optimizer_batches(rows, seed=7, epochs=3, microbatch=2,
                                      accumulation=4, max_steps=2))
    assert [s["question_count"] for s in schedule] == [8, 3]
    assert [len(batch) for batch in schedule[1]["microbatches"]] == [2, 1]


def test_overlapping_chunks_cannot_oversample_a_question():
    with pytest.raises(ValueError, match="duplicate_training_question"):
        list(optimizer_batches([{"question_id": "same"}] * 2, seed=1, epochs=1,
                               microbatch=2, accumulation=4, max_steps=1))


def test_learning_rate_schedule_is_positive_and_reproducible():
    rates = [constant_learning_rate(s, 16, 1, 1e-5) for s in range(1, 17)]
    assert rates == [1e-5] * 16


def test_explicit_negatives_match_analytic_loss_and_ignore_other_query_passages():
    torch = pytest.importorskip("torch")
    queries = torch.tensor([[1., 0.], [0., 1.]], requires_grad=True)
    passages = torch.tensor([[[1., 0.], [0., 1.], [-1., 0.]],
                             [[0., 1.], [1., 0.], [0., -1.]]], requires_grad=True)
    loss = per_query_contrastive_loss(queries, passages, temperature=1.)
    assert loss.item() == pytest.approx(math.log(math.e + 1 + 1 / math.e) - 1)
    altered = passages.detach().clone()
    altered[1] = torch.tensor([[1., 1.], [1., -1.], [-1., 1.]])
    # Per-query loss must not depend on any passage belonging to a different query.
    first = per_query_contrastive_loss(queries[:1], altered[:1], temperature=1.)
    assert first.item() == pytest.approx(loss.item())
    loss.backward()
    assert torch.isfinite(queries.grad).all() and torch.isfinite(passages.grad).all()
    assert passages.grad.abs().sum() > 0


def test_accumulation_weights_reproduce_full_batch_gradient():
    torch = pytest.importorskip("torch")
    torch.manual_seed(3)
    q = torch.randn(3, 4)
    p = torch.randn(3, 3, 4)
    weight = torch.nn.Parameter(torch.eye(4))
    loss = per_query_contrastive_loss(q @ weight, p @ weight, temperature=0.3)
    loss.backward()
    expected = weight.grad.clone()
    weight.grad = None
    for start, end in ((0, 2), (2, 3)):
        micro = per_query_contrastive_loss(q[start:end] @ weight,
                                          p[start:end] @ weight, temperature=0.3)
        (micro * (end - start) / len(q)).backward()
    assert torch.allclose(weight.grad, expected, atol=1e-6)


def test_nonfinite_or_zero_embeddings_fail_closed():
    torch = pytest.importorskip("torch")
    with pytest.raises(ValueError, match="nonfinite"):
        per_query_contrastive_loss(torch.tensor([[float("nan"), 1.]]), torch.ones(1, 3, 2))
    with pytest.raises(ValueError, match="zero_training_embedding"):
        per_query_contrastive_loss(torch.zeros(1, 2), torch.ones(1, 3, 2))


@pytest.mark.parametrize("peak", [float("nan"), float("inf"), -1, 0])
def test_invalid_learning_rate_rejected(peak):
    with pytest.raises(ValueError, match="learning_rate"):
        constant_learning_rate(1, 16, 1, peak)


def synthetic_runtime(*, memory_mib=10, skip_update=False, fail_post_update=False,
                      fail_model_call=None):
    """Tiny CPU tensors with fake CUDA APIs; never loads or executes a service model."""
    torch = pytest.importorskip("torch")

    class TinyFixture(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.weight = torch.nn.Parameter(torch.eye(4))
            self.calls = 0

        def gradient_checkpointing_enable(self, **kwargs):
            assert kwargs == {"gradient_checkpointing_kwargs": {"use_reentrant": False}}

        def forward(self, input_ids, attention_mask):
            self.calls += 1
            if self.calls == fail_model_call:
                raise RuntimeError("synthetic_forward_failure")
            return SimpleNamespace(last_hidden_state=self.weight[input_ids[:, 0] - 1].unsqueeze(1))

    class Batch(dict):
        def to(self, device):
            assert device == "cuda"
            return self

    def tokenizer(texts, **kwargs):
        assert kwargs["truncation"] is True
        return Batch(input_ids=torch.arange(1, 5).reshape(4, 1).repeat(len(texts) // 4, 1),
                     attention_mask=torch.ones(len(texts), 1, dtype=torch.long))

    class Scaler:
        def scale(self, loss):
            return loss

        def unscale_(self, optimizer):
            return None

        def step(self, optimizer):
            if not skip_update:
                optimizer.step()

        def update(self):
            return None

        def get_scale(self):
            return 1.0

    def optimizer(*args, **kwargs):
        result = torch.optim.AdamW(*args, **kwargs)
        if fail_post_update:
            def fail(*_):
                raise RuntimeError("synthetic_failure_after_weights_changed")
            result.register_step_post_hook(fail)
        return result

    fake = SimpleNamespace(
        optim=SimpleNamespace(AdamW=optimizer), amp=SimpleNamespace(GradScaler=lambda _: Scaler()),
        cuda=SimpleNamespace(synchronize=lambda: None, reset_peak_memory_stats=lambda: None,
                             max_memory_allocated=lambda: memory_mib * 2**20,
                             max_memory_reserved=lambda: memory_mib * 2**20),
        autocast=lambda **_: contextlib.nullcontext(), float32=torch.float32, float16=torch.float16,
        isfinite=torch.isfinite, nn=torch.nn)
    recipe = {"learning_rate": 1e-3, "weight_decay": 0.01, "seed": 1, "epochs": 1,
              "microbatch_queries": 1, "gradient_accumulation_steps": 1,
              "max_optimizer_steps": 2, "warmup_optimizer_steps": 1,
              "temperature": 0.3, "max_grad_norm": 1.0, "resource_peak_allocated_limit_mib": 5376}
    records = [{"question_id": f"synthetic-{i}", "positive": {"chunk_id": "positive"},
                "negatives": [{"chunk_id": "negative1"}, {"chunk_id": "negative2"}]}
               for i in range(2)]
    context = {"questions": [{"id": row["question_id"], "question": "synthetic fixture"}
                              for row in records],
               "chunks": {key: {"text": "synthetic fixture"}
                          for key in ("positive", "negative1", "negative2")},
               "readiness_contract": "m4-readiness-plan-v2",
               "negative_model_input_sha256": {
                   f"negative{i}": pilot.fingerprint({"input_ids": [i + 2], "attention_mask": [1]})
                   for i in (1, 2)}}
    return TinyFixture(), tokenizer, fake, records, context, recipe


def test_actual_update_survives_late_resource_failure_with_durable_journal(tmp_path):
    values = synthetic_runtime(memory_mib=6000)
    model = values[0]
    before = model.weight.detach().clone()
    state = {}
    journal = tmp_path / "progress.jsonl"
    progress = UpdateProgress(state, runner.journal_sink(journal))
    with pytest.raises(MemoryError, match="resource_allocated_limit_exceeded"):
        runner.run_updates(*values, probe=False, progress=progress)
    assert not (model.weight == before).all()
    assert state["optimizer_steps_attempted"] == state["optimizer_steps_completed"] == 1
    assert state["optimizer_steps_verified"] == state["weight_updates_observed"] == 1
    assert state["steps"][0]["status"] == "failed"
    assert progress.execution_flags("train")["training_executed"] is True
    events = [json.loads(line)["event"] for line in journal.read_text().splitlines()]
    assert events.index("optimizer_update_verified") < events.index("optimizer_group_failed")


def test_prior_successful_update_and_losses_survive_next_forward_failure():
    state = {}
    progress = UpdateProgress(state)
    with pytest.raises(RuntimeError, match="synthetic_forward_failure"):
        runner.run_updates(*synthetic_runtime(fail_model_call=2), probe=False, progress=progress)
    assert state["optimizer_groups_started"] == 2
    assert state["optimizer_steps_completed"] == state["optimizer_steps_verified"] == 1
    assert [step["status"] for step in state["steps"]] == ["passed", "failed"]
    assert state["steps"][0]["losses"]


def test_partial_optimizer_exception_preserves_observed_weight_update():
    state = {}
    progress = UpdateProgress(state)
    with pytest.raises(RuntimeError, match="synthetic_failure_after_weights_changed"):
        runner.run_updates(*synthetic_runtime(fail_post_update=True), probe=False, progress=progress)
    assert state["optimizer_steps_attempted"] == state["optimizer_step_calls"] == 1
    assert state["optimizer_steps_completed"] == state["optimizer_steps_verified"] == 0
    assert state["weight_updates_observed"] == 1
    assert progress.execution_flags("train")["training_executed"] is True


def test_grad_scaler_skipped_update_is_not_reported_as_executed():
    state = {}
    progress = UpdateProgress(state)
    with pytest.raises(FloatingPointError, match="optimizer_update_not_verified"):
        runner.run_updates(*synthetic_runtime(skip_update=True), probe=False, progress=progress)
    assert state["optimizer_steps_attempted"] == 1
    assert state["optimizer_step_calls"] == state["optimizer_steps_completed"] == 0
    assert state["weight_updates_observed"] == 0
    assert progress.execution_flags("train")["training_executed"] is False


def test_probe_and_training_flags_distinguish_actual_partial_execution():
    state = {}
    progress = UpdateProgress(state)
    progress.state["optimizer_groups_started"] = 1
    progress.attempt(1)
    progress.entered()
    progress.completed()
    progress.observed({"optimizer_step": 1}, True)
    assert progress.execution_flags("probe") == {
        "training_attempted": False, "training_executed": False,
        "probe_optimizer_executed": True, "probe_weight_update_executed": True}


def test_execution_guard_refuses_parallel_jobs_and_same_plan_retry(tmp_path):
    with (runner.execution_guard(tmp_path, "a" * 64, "probe"),
          pytest.raises(RuntimeError, match="another_model_execution"),
          runner.execution_guard(tmp_path, "b" * 64, "probe")):
        pytest.fail("parallel run allowed")
    with pytest.raises(FileExistsError), runner.execution_guard(tmp_path, "a" * 64, "probe"):
        pytest.fail("retry allowed")
    assert not (tmp_path / ".local/m4-execution/active.lock").exists()
    with runner.execution_guard(tmp_path, "a" * 64, "train"):
        pass


def passing_probe():
    recipe = {"resource_peak_allocated_limit_mib": 5376}
    return {"command": "probe", "status": "passed", "execution_plan_sha256": "a" * 64,
            "ready_manifest_sha256": "b" * 64, "recipe": recipe,
            "optimizer_steps_attempted": 1, "optimizer_step_calls": 1,
            "optimizer_steps_completed": 1, "optimizer_steps_verified": 1, "optimizer_steps": 1,
            "probe_weight_update_executed": True, "training_executed": False,
            "quality_evaluation_executed": False, "peak_allocated_mib": 1024,
            "steps": [{"status": "passed", "optimizer_update_verified": True}]}


@pytest.mark.parametrize("field,value", [("status", "failed"), ("optimizer_steps_completed", 0),
                                         ("optimizer_steps_verified", 0),
                                         ("probe_weight_update_executed", False),
                                         ("peak_allocated_mib", 6000),
                                         ("execution_plan_sha256", "different")])
def test_probe_gate_rejects_failed_unverified_or_different_execution(field, value):
    report = passing_probe()
    runner.validate_probe_report(report, "a" * 64, "b" * 64, report["recipe"])
    report[field] = value
    with pytest.raises(ValueError, match="probe_did_not_pass"):
        runner.validate_probe_report(report, "a" * 64, "b" * 64, report["recipe"])


def test_readiness_calls_frozen_helper_before_any_model_loading(tmp_path, monkeypatch):
    raw = pilot.json_bytes({"synthetic": True})
    path = tmp_path / "data/training/manifest.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    settings = {key: "data/training/synthetic" for key in runner.READINESS_ARGUMENTS}
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.ready, "relative", lambda path: path.relative_to(tmp_path).as_posix())
    called = []

    def blocked(args):
        called.append(args)
        raise ValueError("synthetic_not_ready")

    monkeypatch.setattr(runner.ready, "load_ready_data", blocked)
    execution = {"ready_manifest_sha256": pilot.sha256(raw), "readiness_arguments": settings,
                 "readiness_contract": "m4-readiness-plan-v1"}
    with pytest.raises(ValueError, match="synthetic_not_ready"):
        runner.verified_data(execution, path)
    assert called[0].output == path and called[0].command == "replay"


@pytest.mark.parametrize("field,value,accepted", [
    ("review_pack_dir", ".local", True),
    ("review_pack_dir", "./.local/", True),
    ("review_pack_dir", ".local-sibling", False),
    ("review_pack_dir", "../outside", False),
    ("review_pack_dir", "absolute-outside", False),
    ("review_pack_dir", ".", False),
    ("e5_snapshot", ".local", False),
    ("token_receipt", ".local", False),
])
def test_actual_readiness_paths_allow_local_root_only_for_review_pack_dir(
        tmp_path, monkeypatch, field, value, accepted):
    execution = json.loads((runner.ROOT / "data/training/m4-e5-execution-v1.json").read_bytes())
    raw = pilot.json_bytes({"synthetic": True})
    path = tmp_path / "data/training/manifest.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    execution["ready_manifest_sha256"] = pilot.sha256(raw)
    execution["readiness_arguments"][field] = (
        str(tmp_path.parent / "outside") if value == "absolute-outside" else value)
    relative = runner.ready.relative
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.ready, "relative", lambda p: relative(p, tmp_path))
    calls = []
    expected = {"triplets": [{}] * 64, "calibration": [{}] * 16}

    def verified(args):
        calls.append(args)
        assert args.review_pack_dir.resolve() == tmp_path / ".local"
        return {"manifest": expected}

    monkeypatch.setattr(runner, "readiness_module", lambda _: SimpleNamespace(load_ready_data=verified))
    if accepted:
        manifest, context = runner.verified_data(execution, path)
        assert manifest == expected and context["readiness_contract"] == "m4-readiness-plan-v2"
        assert len(calls) == 1 and calls[0].command == "replay"
    else:
        with pytest.raises(ValueError):
            runner.verified_data(execution, path)
        assert not calls


def test_execution_plan_requires_frozen_source_and_evaluation_contract(monkeypatch):
    original = json.loads((runner.ROOT / "data/training/m4-plan-v1.json").read_bytes())
    execution = {"schema_version": 1, "execution_id": "m4-e5-execution-v1",
                 "parent_plan_sha256": pilot.sha256(
                     (runner.ROOT / "data/training/m4-plan-v1.json").read_bytes()),
                 "readiness_contract": "m4-readiness-plan-v1",
                 "evaluation_contract": runner.EVALUATION_CONTRACT,
                 "source_sha256_lf": {name: pilot.sha256((runner.ROOT / name).read_bytes().replace(
                     b"\r\n", b"\n")) for name in runner.REQUIRED_SOURCES |
                     {"scripts/prepare_training_ready.py"}},
                 "implementation": {
                     "scheduler": "linear_warmup_then_constant", "adamw_foreach": False,
                     "probe_query_count": 8, "probe_order": "max_input_tokens_desc_then_question_id",
                     "shuffle": "sorted_question_ids_then_python_random_seed_plus_epoch",
                     "accumulation_weight":
                     "microbatch_query_count_divided_by_optimizer_group_query_count",
                     "stop_on_skipped_update": True, "save_checkpoint": "terminal_only"}}
    assert runner.validate_execution(execution) == original["training_proposal"]
    for field in ("source_sha256_lf", "evaluation_contract"):
        invalid = copy.deepcopy(execution)
        invalid[field] = {}
        with pytest.raises(ValueError, match="missing_frozen_source_or_evaluation_contract"):
            runner.validate_execution(invalid)


def input_context():
    return {"readiness_contract": "m4-readiness-plan-v2", "negative_model_input_sha256": {
        "negative": pilot.fingerprint({"input_ids": [4, 5, 6], "attention_mask": [1, 1, 1]})}}


def test_negative_actual_inputs_allow_only_masked_right_padding():
    reference = {"chunk_id": "negative"}
    runner.verify_negative_input(reference, [4, 5, 6], [1, 1, 1], input_context())
    runner.verify_negative_input(reference, [4, 5, 6, 0, 0], [1, 1, 1, 0, 0], input_context())
    for ids, masks in (([0, 4, 5, 6], [0, 1, 1, 1]), ([4, 5, 6], [1, 0, 1])):
        with pytest.raises(ValueError, match="only_right_masked_padding"):
            runner.verify_negative_input(reference, ids, masks, input_context())


@pytest.mark.parametrize("ids,mask", [([4, 5, 7], [1, 1, 1]), ([4, 5], [1, 1]),
                                      ([4, 5, 6], [1, 1, 0])])
def test_negative_input_token_or_mask_tamper_rejected(ids, mask):
    with pytest.raises(ValueError, match="checksum_mismatch"):
        runner.verify_negative_input({"chunk_id": "negative"}, ids, mask, input_context())


def test_batch_guard_blocks_before_any_synthetic_forward():
    values = synthetic_runtime()
    values[4]["negative_model_input_sha256"]["negative1"] = "tampered"
    with pytest.raises(ValueError, match="checksum_mismatch"):
        runner.run_updates(*values, probe=False)
    assert values[0].calls == 0


def test_missing_actual_input_hash_fails_closed():
    context = input_context()
    context["negative_model_input_sha256"] = {}
    with pytest.raises(ValueError, match="checksum_mismatch"):
        runner.verify_negative_input({"chunk_id": "negative"}, [4, 5, 6], [1, 1, 1], context)


def test_readiness_module_selection_has_explicit_allowlist(monkeypatch):
    seen = []
    monkeypatch.setattr(runner.importlib, "import_module", lambda name: seen.append(name))
    for contract in ("m4-readiness-plan-v1", "m4-readiness-plan-v2"):
        runner.readiness_module({"readiness_contract": contract})
    assert seen == ["scripts.prepare_training_ready", "scripts.prepare_training_ready_v2"]
    with pytest.raises(ValueError, match="unsupported_readiness_contract"):
        runner.readiness_module({"readiness_contract": "arbitrary.module"})


def test_nonfinite_failure_evidence_is_valid_json_and_journal(tmp_path):
    report = {"witness": float("nan"), "steps": [{"norm": float("inf"), "loss": -float("inf")} ]}
    safe = runner.finite_metadata(report)
    assert "NaN" not in json.dumps(safe, allow_nan=False)
    assert safe["witness"] == "nonfinite_nan"
    path = tmp_path / "journal.jsonl"
    runner.journal_sink(path)(report)
    assert json.loads(path.read_bytes())["steps"][0]["norm"] == "nonfinite_positive_infinity"


def test_previous_known_weight_change_not_erased_by_later_unknown_or_unchanged():
    progress = UpdateProgress({})
    progress.observed({"optimizer_step": 1}, True)
    progress.entered()
    assert progress.state["weight_update_status"] == "observed"
    assert progress.state["current_optimizer_weight_update_status"] == "unknown_until_verified"
    progress.observed({"optimizer_step": 2}, False)
    assert progress.state["weight_update_status"] == "observed"
    assert progress.state["weight_updates_observed"] == 1


def test_final_failure_report_preserves_real_progress_after_late_error(tmp_path, monkeypatch):
    # Exercise final reporting with no actual model/device; the tiny CPU update is tested above.
    class UnusedModel:
        def to(self, device):
            return self

    tokenizer = SimpleNamespace(is_fast=True, truncation_side="right")
    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: True, get_device_name=lambda: "synthetic",
                             get_device_properties=lambda _: SimpleNamespace(total_memory=10),
                             mem_get_info=lambda: (10, 10), reset_peak_memory_stats=lambda: None,
                             max_memory_allocated=lambda: 6000 * 2**20,
                             max_memory_reserved=lambda: 6100 * 2**20, empty_cache=lambda: None),
        OutOfMemoryError=type("SyntheticOOM", (RuntimeError,), {}), float32="synthetic")
    fake_transformers = SimpleNamespace(
        AutoModel=SimpleNamespace(from_pretrained=lambda *a, **k: UnusedModel()),
        AutoTokenizer=SimpleNamespace(from_pretrained=lambda *a, **k: tokenizer))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setattr(runner, "verify_snapshot", lambda *a: {"synthetic": "a" * 64})
    monkeypatch.setattr(runner, "seed_runtime", lambda *a: None)
    monkeypatch.setattr(runner, "version", lambda *a: "synthetic")
    monkeypatch.setattr(runner, "verify_all_negative_inputs", lambda *a: None)

    def late_failure(*args, progress, **kwargs):
        progress.state["optimizer_groups_started"] = 1
        progress.attempt(1)
        progress.entered()
        progress.completed()
        step = {"optimizer_step": 1, "status": "failed", "witness_after": float("nan")}
        progress.state["steps"].append(step)
        progress.observed(step, True)
        raise MemoryError("resource_allocated_limit_exceeded")

    monkeypatch.setattr(runner, "run_updates", late_failure)
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    args = SimpleNamespace(output_dir=tmp_path / "output", ready_manifest=manifest,
                           command="train", e5_snapshot=tmp_path / "unused")
    with pytest.raises(MemoryError):
        runner.execute_run(args, b"{}", {"mixed_precision": "synthetic", "seed": 1},
                            {"triplets": []}, {})
    report = json.loads((args.output_dir / "report.json").read_bytes())
    assert report["status"] == "failed" and report["training_executed"] is True
    assert report["optimizer_steps_completed"] == report["weight_updates_observed"] == 1
    assert report["terminal_checkpoint_saved"] is False
    assert report["steps"][0]["witness_after"] == "nonfinite_nan"
    assert (args.output_dir / "progress.jsonl").is_file()
