"""Model-free runner checks using fake process messages and real fixture validation."""
import copy
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from scripts import evaluate_generation_smoke as smoke


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    for relative in smoke.REQUIRED_SOURCES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((smoke.ROOT / relative).read_bytes())
    dataset = root / "data/evaluation/m5-synthetic-smoke-v1.json"
    manifest = root / "data/models/m5-generation-v1.json"
    for target in (dataset, manifest):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((smoke.ROOT / target.relative_to(root)).read_bytes())
    plan = {
        "schema_version": 1, "run_id": "m5-generation-v1", "test_locked": True,
        "human_review_count": 0, "fixed_no_retry": True,
        "watchdog": {"load_seconds": 300, "generation_seconds": 195},
        "source_sha256": {p: smoke.sha256(root / p, normalized=True)
                          for p in smoke.REQUIRED_SOURCES},
        "dataset": {"path": dataset.relative_to(root).as_posix(), "sha256": smoke.sha256(dataset)},
        "model_manifest": {"path": manifest.relative_to(root).as_posix(),
                           "sha256": smoke.sha256(manifest)},
    }
    plan_path = root / "data/evaluation/m5-generation-plan-v1.json"
    plan_path.write_text(json.dumps(plan))
    monkeypatch.setattr(smoke, "git_identity", lambda root: {"head": "a" * 40, "clean": True})
    return SimpleNamespace(root=root, plan=plan_path, dataset=dataset,
                           output=root / ".local/result", snapshot=root / "models/fake")


@pytest.fixture
def fake_worker(setup, monkeypatch):
    state = SimpleNamespace(alive=False, calls=[], closed=False, failure=None, invalid=False)
    fixture = json.loads(setup.dataset.read_text(encoding="utf-8"))
    by_id = {case["id"]: case for case in fixture["cases"]}

    class Connection:
        def __init__(self):
            self.pending = [{"event": "loaded", "metadata": {"experimental": True},
                             "load_metrics": {"elapsed_seconds": 1, "peak_reserved_mib": 100},
                             "verified_files": {}}]

        def send(self, value):
            if value["event"] == "close":
                state.alive = False
                return
            state.calls.append(value["case_id"])
            if state.failure:
                self.pending.append({"event": "failed", "error_code": state.failure,
                                     "telemetry": {"peak_reserved_mib": 5377}})
                return
            case = by_id[value["case_id"]]
            raw = {"status": "abstained", "reason": "insufficient_evidence", "claims": []}
            result = {"text": "bad JSON" if state.invalid else json.dumps(raw),
                      "finish_reason": "eos", "input_tokens": 100, "output_tokens": 20,
                      "elapsed_seconds": 1, "peak_allocated_mib": 80, "peak_reserved_mib": 100}
            self.pending.append({"event": "generated", "case_id": case["id"], "result": result})

        def poll(self, timeout):
            return bool(self.pending)

        def recv(self):
            return self.pending.pop(0)

        def close(self):
            pass

    connection = Connection()

    class Process:
        pid = 999999

        def __init__(self, **kwargs):
            pass

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
            state.closed = True

    context = SimpleNamespace(Pipe=lambda: (connection, Connection()), Process=Process)
    monkeypatch.setattr(smoke.multiprocessing, "get_context", lambda kind: context)

    @contextmanager
    def lock(root):
        with original_lock(root):
            try:
                yield
            finally:
                if state.alive:
                    pytest.fail("worker must stop before shared lock release")

    original_lock = smoke.exclusive_model_check
    monkeypatch.setattr(smoke, "exclusive_model_check", lock)
    return state


def test_fixed_fixture_and_unicode_spans_validate(setup):
    plan, fixture, _, sources = smoke.verify_plan(setup.plan, setup.root)
    assert plan["test_locked"]
    assert len(fixture["cases"]) == 12 and len(sources) == len(smoke.REQUIRED_SOURCES)


def test_source_edit_fails_before_worker(setup):
    (setup.root / "data/prompts/m5-grounded-answer-v1.txt").write_text("modified")
    result = smoke.run(setup.plan, setup.snapshot, setup.output, setup.root)
    assert result["error_code"] == "source_binding_mismatch"
    assert (setup.output / "report.json").exists()


def test_fixture_self_consistent_hash_still_checks_real_source_span(setup):
    data = json.loads(setup.dataset.read_text(encoding="utf-8"))
    data["cases"][0]["evidence"][0]["text"] = "X" * len(data["cases"][0]["evidence"][0]["text"])
    setup.dataset.write_text(json.dumps(data), encoding="utf-8")
    plan = json.loads(setup.plan.read_text())
    plan["dataset"]["sha256"] = smoke.sha256(setup.dataset)
    setup.plan.write_text(json.dumps(plan))
    with pytest.raises(smoke.SmokeError, match="fixture_source_span_mismatch"):
        smoke.verify_plan(setup.plan, setup.root)


def test_unbound_fixture_fails_closed(setup):
    setup.dataset.write_text("{}")
    with pytest.raises(smoke.SmokeError, match="dataset_binding_mismatch"):
        smoke.verify_plan(setup.plan, setup.root)


def test_locked_test_path_never_read(setup, monkeypatch):
    plan = json.loads(setup.plan.read_text())
    plan["dataset"]["path"] = "data/evaluation/test.json"
    setup.plan.write_text(json.dumps(plan))
    with pytest.raises(smoke.SmokeError, match="unsupported_evaluation_binding"):
        smoke.verify_plan(setup.plan, setup.root)


def test_no_output_overwrite_even_on_preflight_failure(setup):
    setup.output.mkdir(parents=True)
    (setup.output / "report.json").write_text("preserve")
    with pytest.raises(FileExistsError):
        smoke.run(setup.plan, setup.snapshot, setup.output, setup.root)
    assert (setup.output / "report.json").read_text() == "preserve"


def test_fake_full_run_separates_guard_and_replays_without_model(setup, fake_worker, monkeypatch):
    result = smoke.run(setup.plan, setup.snapshot, setup.output, setup.root)
    assert result["status"] == "completed"
    assert len(fake_worker.calls) == 11
    assert "m5-smoke-007" not in fake_worker.calls
    assert result["summary"]["completed_guard_cases"] == 1
    assert result["summary"]["semantic_correctness"] == "not_verified"
    assert len(list(setup.output.glob("report-*.json"))) == 13
    journal = (setup.output / "journal.jsonl").read_text()
    assert "insufficient_evidence" not in journal
    monkeypatch.setattr(smoke, "LocalGenerator", lambda *args: pytest.fail("replay loaded model"))
    assert smoke.replay(setup.output / "report.json", setup.root)["replay"] == "passed"


def test_schema_rejections_are_not_correct_abstentions(setup, fake_worker):
    fake_worker.invalid = True
    result = smoke.run(setup.plan, setup.snapshot, setup.output, setup.root)
    assert result["status"] == "completed"
    assert result["summary"]["rejected_model_cases"] == 11
    assert result["summary"]["accepted_model_abstentions"] == 0
    assert result["summary"]["expected_status_matches"] == 0


def test_resource_failure_aborts_and_preserves_safe_partial_receipt(setup, fake_worker):
    fake_worker.failure = "generation_memory_limit"
    result = smoke.run(setup.plan, setup.snapshot, setup.output, setup.root)
    assert result["status"] == "failed"
    assert result["error_code"] == "generation_memory_limit"
    assert result["active_case_id"] == "m5-smoke-001"
    assert result["failure_telemetry"]["peak_reserved_mib"] == 5377
    assert result["attempted_model_cases"] == 1
    assert result["summary"]["completed_model_cases"] == 0
    assert result["summary"]["unfinished_model_cases"] == 11
    assert len(fake_worker.calls) == 1 and fake_worker.closed


def test_hard_watchdog_is_independent_of_worker_stopping_criteria(monkeypatch):
    clock = iter([0.0, 0.0, 0.1, 0.2, 0.3])
    monkeypatch.setattr(smoke.time, "monotonic", lambda: next(clock))
    connection = SimpleNamespace(poll=lambda delay: False)
    process = SimpleNamespace(is_alive=lambda: True)
    with pytest.raises(smoke.SmokeError, match="watchdog_generated_timeout"):
        smoke.await_event(connection, process, 0.25, "generated")


def test_replay_rejects_modified_validation_result(setup, fake_worker):
    result = smoke.run(setup.plan, setup.snapshot, setup.output, setup.root)
    changed = copy.deepcopy(result)
    changed["cases"][0]["expected_status_match"] = True
    path = setup.output / "tampered.json"
    path.write_text(json.dumps(changed))
    with pytest.raises(smoke.SmokeError, match="replay_validation_mismatch"):
        smoke.replay(path, setup.root)


def test_same_plan_cannot_run_again_in_another_output(setup, fake_worker):
    assert smoke.run(setup.plan, setup.snapshot, setup.output, setup.root)["status"] == "completed"
    calls = len(fake_worker.calls)
    result = smoke.run(setup.plan, setup.snapshot, setup.root / ".local/second", setup.root)
    assert result["error_code"] == "generation_run_already_reserved"
    assert len(fake_worker.calls) == calls


def test_unconfirmed_cleanup_lock_survives_frozen_helper_finalizer(tmp_path):
    from scripts.verify_terminal_service import exclusive_model_check

    with exclusive_model_check(tmp_path):
        lock = tmp_path / ".local/m4-execution/active.lock"
        info = lock.stat()
        smoke.preserve_failed_cleanup_lock(
            tmp_path, ((info.st_dev, info.st_ino), lock.read_bytes()),
        )
    assert json.loads(lock.read_bytes())["recovery_required"]
    with pytest.raises(FileExistsError), exclusive_model_check(tmp_path):
        pytest.fail("unconfirmed cleanup must retain shared exclusion")
