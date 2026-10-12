"""Synthetic CPU numerical-boundary checks; no actual CUDA/model execution."""

import copy
import json
import sys
from types import SimpleNamespace

import pytest
from test_embedding_training import passing_probe, synthetic_runtime

from doctrail.training import UpdateProgress
from scripts import prepare_training as pilot
from scripts import train_embedding_v2 as runner


def fixed_scale_runtime(**kwargs):
    values = synthetic_runtime(**kwargs)
    fake = values[2]
    original = fake.amp.GradScaler
    received = []

    def scaler(device, *, init_scale):
        received.append((device, init_scale))
        result = original(device)
        result.get_scale = lambda: init_scale
        return result

    fake.amp.GradScaler = scaler
    return values, received


def test_fixed_scale_1024_used_for_successful_updates_without_recipe_changes():
    values, calls = fixed_scale_runtime()
    recipe = copy.deepcopy(values[-1])
    state = runner.run_updates(*values, probe=False)
    assert calls == [("cuda", 1024.0)]
    assert values[-1] == recipe and "grad_scaler_init_scale" not in recipe
    assert state["optimizer_steps_verified"] == 2
    assert state["numerical_override"] == {"grad_scaler_init_scale": 1024.0}
    assert state["grad_scaler_actual_initial_scale"] == state["grad_scaler_current_scale"] == 1024.0
    assert all(s["grad_scaler_scale_before_unscale"] == s["grad_scaler_scale_before_clip"] == 1024.0
               for s in state["steps"])


def test_nonfinite_gradient_norm_stop_before_optimizer_with_precise_stage_and_scale():
    torch = pytest.importorskip("torch")
    values, calls = fixed_scale_runtime()
    values[0].weight.register_hook(lambda gradient: torch.full_like(gradient, float("inf")))
    state = {}
    with pytest.raises(FloatingPointError, match="^nonfinite_gradient_norm$"):
        runner.run_updates(*values, probe=False, progress=UpdateProgress(state))
    assert calls == [("cuda", 1024.0)]
    assert state["failure_stage"] == "gradient_clipping"
    assert state["grad_scaler_actual_initial_scale"] == state["grad_scaler_current_scale"] == 1024.0
    assert state["steps"][0]["grad_scaler_scale_before_unscale"] == 1024.0
    assert state["steps"][0]["grad_scaler_scale_before_clip"] == 1024.0
    assert state["optimizer_step_calls"] == state["optimizer_steps_attempted"] == 0
    assert state["optimizer_steps_verified"] == state["weight_updates_observed"] == 0


def test_scaler_actual_initial_value_must_match_fixed_configuration():
    values, _ = fixed_scale_runtime()
    factory = values[2].amp.GradScaler

    def wrong(*args, **kwargs):
        result = factory(*args, **kwargs)
        result.get_scale = lambda: 65536.0
        return result

    values[2].amp.GradScaler = wrong
    state = {}
    with pytest.raises(ValueError, match="grad_scaler_initial_scale_mismatch"):
        runner.run_updates(*values, probe=False, progress=UpdateProgress(state))
    assert state["grad_scaler_actual_initial_scale"] == 65536.0
    assert state["optimizer_step_calls"] == 0


def test_skipped_update_still_fails_with_no_verified_weight_update():
    values, _ = fixed_scale_runtime(skip_update=True)
    state = {}
    with pytest.raises(FloatingPointError, match="optimizer_update_not_verified"):
        runner.run_updates(*values, probe=False, progress=UpdateProgress(state))
    assert state["failure_stage"] == "optimizer_step"
    assert state["optimizer_step_calls"] == state["optimizer_steps_verified"] == 0


def test_late_resource_failure_preserves_actual_completed_update():
    values, _ = fixed_scale_runtime(memory_mib=6000)
    state = {}
    with pytest.raises(MemoryError, match="resource_allocated_limit_exceeded"):
        runner.run_updates(*values, probe=False, progress=UpdateProgress(state))
    assert state["failure_stage"] == "resource_check"
    assert state["optimizer_steps_verified"] == state["weight_updates_observed"] == 1


def test_unknown_clipping_error_is_not_mislabeled_as_nonfinite(monkeypatch):
    values, _ = fixed_scale_runtime()

    def unknown(*args, **kwargs):
        assert kwargs["error_if_nonfinite"] is True
        raise RuntimeError("synthetic unrelated runtime failure")

    monkeypatch.setattr(values[2].nn.utils, "clip_grad_norm_", unknown)
    state = {}
    with pytest.raises(RuntimeError, match="synthetic unrelated"):
        runner.run_updates(*values, probe=False, progress=UpdateProgress(state))
    assert state["failure_stage"] == "gradient_clipping"
    assert state["last_completed_phase"] == "gradient_unscale"
    assert state["optimizer_step_calls"] == 0


@pytest.mark.parametrize("mismatch", ["selection", "shape"])
def test_matched_probe_selection_and_shapes_fail_before_forward(monkeypatch, mismatch):
    values, _ = fixed_scale_runtime()
    model, _, _, records, context, _ = values
    selection = [{"question_id": records[0]["question_id"], "raw_input_token_lengths": [1] * 4}]
    group = {"epoch": 0, "optimizer_step": 1, "question_count": 1,
             "microbatches": [[records[0]]], "probe_selection": selection}
    monkeypatch.setattr(runner, "probe_group", lambda *_: group)
    context["resource_followup_probe_selection"] = [] if mismatch == "selection" else selection
    context["resource_followup_probe_tensor_shapes"] = [[8, 512]]
    with pytest.raises(ValueError, match=f"resource_followup_probe_{mismatch}_changed"):
        runner.run_updates(*values, probe=True)
    assert model.calls == 0


def followup_probe():
    report = passing_probe()
    report.update(numerical_override=dict(runner.NUMERICAL_OVERRIDE),
                  grad_scaler_configured_init_scale=1024.0,
                  grad_scaler_actual_initial_scale=1024.0, grad_scaler_current_scale=1024.0)
    report["steps"][0].update(grad_scaler_scale_before_unscale=1024.0,
                               grad_scaler_scale_before_clip=1024.0)
    return report


@pytest.mark.parametrize("field", ["grad_scaler_configured_init_scale", "grad_scaler_actual_initial_scale",
                                  "grad_scaler_current_scale", "numerical_override"])
def test_training_requires_successful_probe_with_same_fixed_scale(field):
    report = followup_probe()
    runner.validate_probe_report(report, "a" * 64, "b" * 64, report["recipe"])
    report[field] = {"grad_scaler_init_scale": 65536.0} if field == "numerical_override" else 65536.0
    with pytest.raises(ValueError, match="probe_did_not_pass"):
        runner.validate_probe_report(report, "a" * 64, "b" * 64, report["recipe"])


def test_original_runner_and_training_primitives_remain_frozen():
    expected = {"scripts/train_embedding.py": "1bc7f71c60012fbfc17e6aaa793302a89826a07acb775bdaae806e5d4a9a0df5",
                "src/doctrail/training.py": "9d0e6913f77b7f28114e7cad737afdc66dc786edc6620f97481f0cdeeaabd3aa"}
    for name, digest in expected.items():
        assert pilot.sha256((runner.ROOT / name).read_bytes().replace(b"\r\n", b"\n")) == digest


def valid_execution():
    execution = json.loads((runner.ROOT / "data/training/m4-e5-execution-v1.1.json").read_bytes())
    execution.update(execution_id="m4-e5-execution-v2", resource_followup_plan_path=runner.FOLLOWUP_PATH,
                     resource_followup_plan_sha256=runner.file_sha256(runner.ROOT / runner.FOLLOWUP_PATH),
                     numerical_override=dict(runner.NUMERICAL_OVERRIDE))
    execution["source_sha256_lf"]["scripts/train_embedding_v2.py"] = pilot.sha256(
        (runner.ROOT / "scripts/train_embedding_v2.py").read_bytes().replace(b"\r\n", b"\n"))
    return execution


def test_followup_preserves_original_recipe_and_rejects_65536_or_plan_drift():
    execution = valid_execution()
    proposal = json.loads((runner.ROOT / "data/training/m4-plan-v1.json").read_bytes())["training_proposal"]
    assert runner.validate_execution(execution) == proposal
    for field, value in (("numerical_override", {"grad_scaler_init_scale": 65536.0}),
                         ("resource_followup_plan_sha256", "0" * 64),
                         ("ready_manifest_sha256", "0" * 64)):
        changed = copy.deepcopy(execution)
        changed[field] = value
        with pytest.raises(ValueError):
            runner.validate_execution(changed)


def test_followup_rejects_failed_report_and_original_source_drift(monkeypatch):
    execution = valid_execution()
    file_hash = runner.file_sha256
    monkeypatch.setattr(runner, "file_sha256", lambda path:
                        "0" * 64 if path == runner.ROOT / runner.FAILED_REPORT_PATH else file_hash(path))
    with pytest.raises(ValueError, match="frozen_input_changed"):
        runner.validate_execution(execution)
    monkeypatch.setattr(runner, "file_sha256", file_hash)
    original = (runner.ROOT / "scripts/train_embedding.py").read_bytes().replace(b"\r\n", b"\n")
    digest = pilot.sha256
    monkeypatch.setattr(pilot, "sha256", lambda raw: "0" * 64 if raw == original else digest(raw))
    with pytest.raises(ValueError, match="frozen_source_changed"):
        runner.validate_execution(execution)


def test_followup_one_attempt_guard_still_rejects_retry(tmp_path):
    with runner.execution_guard(tmp_path, "a" * 64, "probe"):
        pass
    with pytest.raises(FileExistsError), runner.execution_guard(tmp_path, "a" * 64, "probe"):
        pytest.fail("same-plan retry allowed")


def test_setup_failure_records_safe_phase_without_optimizer_execution(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False), OutOfMemoryError=MemoryError))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(AutoModel=None, AutoTokenizer=None))
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b"{}")
    args = SimpleNamespace(command="probe", output_dir=tmp_path / "probe", ready_manifest=manifest)
    execution = pilot.json_bytes({"resource_followup_plan_sha256": runner.FOLLOWUP_SHA256})
    with pytest.raises(RuntimeError, match="cuda_required_no_cpu_fallback"):
        runner.execute_run(args, execution, {"mixed_precision": "synthetic"}, {}, {})
    report = json.loads((args.output_dir / "report.json").read_bytes())
    assert report["failure_code"] == "cuda_required_no_cpu_fallback"
    assert report["failure_stage"] == "runtime_setup"
    assert report["last_completed_phase"] == "execution_started"
    assert report["optimizer_step_calls"] == 0
    assert report["training_executed"] is False and report["probe_optimizer_executed"] is False
