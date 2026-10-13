"""Model-free checks of the v2 adapter, spawn target, and effective-config replay."""

import copy
import json
import pickle
from dataclasses import make_dataclass
from types import SimpleNamespace

import pytest

from scripts import evaluate_generation_smoke as base
from scripts import evaluate_generation_smoke_v2 as smoke


def metadata():
    return {
        "generation_protocol": "m5-greedy-v2", "use_model_defaults": False,
        "effective_config_verified": True,
        "effective_generation_config": copy.deepcopy(smoke.EXPECTED_EFFECTIVE),
    }


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    for relative in smoke.REQUIRED_SOURCES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((smoke.ROOT / relative).read_bytes())
    bindings = {}
    for key, relative in {
        "dataset": "data/evaluation/m5-synthetic-smoke-v1.json",
        "model_manifest": "data/models/m5-generation-v1.json",
    }.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((smoke.ROOT / relative).read_bytes())
        bindings[key] = {"path": relative, "sha256": base.sha256(path)}
    plan = {
        "schema_version": 1, "run_id": "m5-generation-v2", "protocol_id": smoke.PROTOCOL_ID,
        "test_locked": True, "human_review_count": 0, "fixed_no_retry": True,
        "watchdog": {"load_seconds": 300, "generation_seconds": 195},
        "source_sha256": {p: base.sha256(root / p, normalized=True)
                          for p in smoke.REQUIRED_SOURCES}, **bindings,
    }
    path = root / "data/evaluation/m5-generation-plan-v2.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(base, "git_identity", lambda root: {"head": "a" * 40, "clean": True})
    return SimpleNamespace(root=root, plan=path, snapshot=root / "models/fake",
                           output=root / ".local/v2-result")


@pytest.fixture
def fake_worker(monkeypatch):
    state = SimpleNamespace(alive=False, calls=0, target=None)

    class Connection:
        def __init__(self):
            self.pending = [{"event": "loaded", "metadata": metadata(),
                             "load_metrics": {}, "verified_files": {}}]

        def send(self, value):
            if value["event"] == "close":
                state.alive = False
                return
            state.calls += 1
            result = {
                "text": '{"status":"abstained","reason":"insufficient_evidence","claims":[]}',
                "finish_reason": "eos", "input_tokens": 100, "output_tokens": 20,
                "elapsed_seconds": 1, "peak_allocated_mib": 80, "peak_reserved_mib": 100,
                "effective_generation_config": copy.deepcopy(smoke.EXPECTED_EFFECTIVE),
            }
            self.pending.append({"event": "generated", "case_id": value["case_id"],
                                 "result": result})

        def poll(self, timeout):
            return bool(self.pending)

        def recv(self):
            return self.pending.pop(0)

        def close(self):
            pass

    class Process:
        pid = 999999

        def __init__(self, *, target, **kwargs):
            state.target = target

        def start(self):
            state.alive = True

        def is_alive(self):
            return state.alive

        def join(self, timeout):
            pass

        def terminate(self):
            state.alive = False

        kill = terminate

        def close(self):
            pass

    monkeypatch.setattr(base.multiprocessing, "get_context", lambda kind: SimpleNamespace(
        Pipe=lambda: (Connection(), Connection()), Process=Process,
    ))
    return state


def test_v2_plan_requires_new_sources_run_id_and_protocol(setup):
    assert smoke.verify_plan(setup.plan, setup.root)[0]["protocol_id"] == smoke.PROTOCOL_ID
    plan = json.loads(setup.plan.read_text())
    for change in ({"run_id": "m5-generation-v1"}, {"protocol_id": "wrong"},
                   {"source_sha256": {key: value for key, value in plan["source_sha256"].items()
                                      if not key.endswith("generation_runtime_v2.py")}}):
        setup.plan.write_text(json.dumps({**plan, **change}))
        with pytest.raises(base.SmokeError, match="invalid_generation_v2_plan"):
            smoke.verify_plan(setup.plan, setup.root)


def test_v2_fake_run_restores_v1_globals_and_persists_protocol(setup, fake_worker):
    originals = (base.verify_plan, base._worker, base._write_json)
    result = smoke.run(setup.plan, setup.snapshot, setup.output, setup.root)
    assert result["status"] == "completed" and fake_worker.calls == 11
    assert fake_worker.target is smoke._worker
    assert pickle.loads(pickle.dumps(fake_worker.target)) is smoke._worker
    assert (base.verify_plan, base._worker, base._write_json) == originals
    for path in setup.output.glob("report*.json"):
        assert json.loads(path.read_text(encoding="utf-8"))["protocol_id"] == smoke.PROTOCOL_ID
    replayed = smoke.replay(setup.output / "report.json", setup.root)
    assert replayed["replay"] == "passed" and replayed["effective_config_verified"] is True
    assert (base.verify_plan, base._worker, base._write_json) == originals


def test_v2_once_only_reservation_survives_new_output(setup, fake_worker):
    smoke.run(setup.plan, setup.snapshot, setup.output, setup.root)
    result = smoke.run(setup.plan, setup.snapshot, setup.root / ".local/again", setup.root)
    assert result["error_code"] == "generation_run_already_reserved"
    assert fake_worker.calls == 11


def test_adapter_restores_after_preflight_failure(setup, fake_worker):
    original = base.verify_plan
    (setup.root / "src/doctrail/generation_runtime_v2.py").write_text("changed")
    result = smoke.run(setup.plan, setup.snapshot, setup.output, setup.root)
    assert result["error_code"] == "source_binding_mismatch" and fake_worker.calls == 0
    assert base.verify_plan is original


def test_nested_adapter_fails_without_changing_active_adapter():
    original = base._worker
    with smoke._adapter():
        with pytest.raises(base.SmokeError, match="generation_v2_adapter_busy"), smoke._adapter():
            pytest.fail("nested adapter entered")
        assert base._worker is smoke._worker
    assert base._worker is original


@pytest.mark.parametrize("target", ["protocol", "load", "case"])
def test_replay_refuses_protocol_or_effective_config_tampering(setup, fake_worker, target):
    report = smoke.run(setup.plan, setup.snapshot, setup.output, setup.root)
    if target == "protocol":
        report["protocol_id"] = "v1"
    elif target == "load":
        report["model_runtime"]["metadata"]["effective_generation_config"]["do_sample"] = True
    else:
        report["cases"][0]["generation"]["effective_generation_config"]["do_sample"] = True
    path = setup.output / "tampered.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(base.SmokeError):
        smoke.replay(path, setup.root)


def test_spawn_target_constructs_v2_generator_and_checks_actual_result(monkeypatch):
    from doctrail import generation_runtime_v2

    state = SimpleNamespace(constructed=0, closed=False, sent=[])
    result_type = make_dataclass("Result", [("text", str), ("effective_generation_config", dict)])

    class Generator:
        def __init__(self, *args):
            state.constructed += 1
            self.load_metrics = {}
            self.verified_files = {}

        def load(self):
            return self

        def public_metadata(self):
            return metadata()

        def generate(self, messages):
            return result_type("{}", {**smoke.EXPECTED_EFFECTIVE, "do_sample": True})

        def close(self):
            state.closed = True

    monkeypatch.setattr(generation_runtime_v2, "LocalGenerator", Generator)
    connection = SimpleNamespace(
        send=state.sent.append,
        recv=lambda: {"event": "generate", "case_id": "one", "messages": []}, close=lambda: None,
    )
    smoke._worker(connection, "fake", "fake")
    assert state.constructed == 1 and state.closed
    assert state.sent[0]["event"] == "loaded"
    assert state.sent[1]["error_code"] == "generation_v2_effective_config_mismatch"
