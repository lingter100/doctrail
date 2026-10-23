"""Synthetic resource protocol tests; never read evaluation pools or load weights."""
import json
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace

import pytest

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_gguf import GGUFResult
from scripts import probe_meeting_blocks_resources as probe


class Process:
    def __init__(self):
        self.stopped = False

    def poll(self):
        return 0 if self.stopped else None

    def kill(self):
        self.stopped = True

    def wait(self, timeout):
        assert timeout <= 5
        self.stopped = True


class Base:
    def __init__(self, effect=None):
        self.effect, self.closed = effect, False
        self.last_effective_config = {"temperature": 0, "n_predict": 384}

    def public_metadata(self):
        return {"repo_id": "synthetic-model", "revision": "synthetic-revision"}

    def begin_request(self, deadline):
        pass

    def end_request(self):
        pass

    def count_tokens(self, messages):
        return 3850 if "Repeat the literal" in messages[-1]["content"] else 500

    def _request(self, method, path, payload=None, deadline=None):
        assert path == "/completion"
        return {"synthetic_transport": True}

    def _complete(self, messages, deadline, token_limit, grammar=""):
        assert token_limit == 384
        self._request("POST", "/completion", {}, deadline)
        if self.effect:
            self.effect(grammar)
        stress = grammar == probe.STRESS_GRAMMAR
        text = "x " * 384 if stress else json.dumps({"status": "answered", "claims": [{
            "evidence_ids": [0], "text": "The tone label is violet."}]})
        return GGUFResult(text, "length" if stress else "eos", 3850 if stress else 500,
                          384 if stress else 24, .01, {})

    def close(self):
        self.closed = True


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    monkeypatch.setattr(probe, "FILES", {"source.py"})
    (tmp_path / "source.py").write_text("# neutral synthetic source\n")
    monkeypatch.setattr(probe, "rss_samples", lambda *args: nullcontext())
    plan_path = tmp_path / "plan.json"
    normal = probe.dto(["The neutral sample has the tone label violet.\n"], "What tone label?")
    stress = probe.dto(["Synthetic resource passage."], "Repeat the literal marker x.")
    plan = {"schema_version": 1, "candidate": probe.CANDIDATE, "limits": probe.LIMITS,
        "bound_files": {"source.py": probe.snapshot(tmp_path / "source.py")[1]},
        "output_dir": ".local/resource-test", "stress_grammar": probe.STRESS_GRAMMAR,
        "cases": [{"id": name, "payload": payload.model_dump(), "official_input_tokens": n}
                  for name, payload, n in [("normal", normal, 500), ("stress", stress, 3850)]]}
    probe.write_new(plan_path, plan)
    return plan_path, plan, tmp_path


def launch_set():
    processes = []

    @contextmanager
    def factory(*args):
        p = Process()
        processes.append(p)
        try:
            yield SimpleNamespace(process=p)
        finally:
            p.kill()
    return processes, factory


def test_two_dispatches_and_metadata_only_restart_preserve_raw(source):
    path, _, root = source
    processes, factory = launch_set()
    bases = []

    def base_factory(service):
        base = Base()
        bases.append(base)
        return base
    result = probe.run(probe.prepare(path), factory, base_factory)
    assert result["readiness_passed"] is True
    assert result["status"] == "resource_ready_not_quality_verified"
    assert result["model_quality_evaluated"] is False
    assert len(result["calls"]) == 2
    assert len(processes) == 2 and all(p.stopped for p in processes)
    assert len(bases) == 2 and all(b.closed for b in bases)
    assert result["results"][1]["output"]["finish_reason"] == "length"
    assert (root / ".local/resource-test/report.json").is_file()
    with pytest.raises(ValueError, match="output_exists"):
        probe.prepare(path)


def test_normal_failure_aborts_stress_and_preserves_attempt(source):
    path, _, _ = source
    _, factory = launch_set()

    def fail(grammar):
        raise GenerationError("generation_deadline_exceeded")
    report = probe.run(probe.prepare(path), factory, lambda _: Base(fail))
    assert len(report["calls"]) == len(report["results"]) == 1
    assert report["failure"] == "generation_deadline_exceeded"
    assert report["sources_unchanged"] and report["metadata_recovery"]
    assert not report["readiness_passed"]


def test_missing_native_dispatch_cannot_pass(source):
    path, _, _ = source
    _, factory = launch_set()
    base = Base()
    old = base._complete

    def no_dispatch(*args):
        request = base._request
        base._request = lambda *args: {}
        try:
            return old(*args)
        finally:
            base._request = request
    base._complete = no_dispatch
    report = probe.run(probe.prepare(path), factory, lambda _: base)
    assert report["failure"] == "resource_native_call_count"
    assert not report["readiness_passed"]


def test_plan_and_source_changes_fail_before_launch(source):
    path, _, root = source
    prepared = probe.prepare(path)
    (root / "source.py").write_text("changed")
    with pytest.raises(ValueError, match="source_changed"):
        probe.verify(prepared)
    path.write_text("{}")
    with pytest.raises(ValueError, match="plan_changed"):
        probe.verify(prepared)


@pytest.mark.parametrize("change", [lambda p: p.update(schema_version=True),
    lambda p: p["limits"].update(retries=False),
    lambda p: p.update(output_dir="../outside"),
    lambda p: p.update(stress_grammar='root ::= "ok"'),
    lambda p: p["cases"].reverse()])
def test_plan_rejects_unregistered_mutations(source, change):
    path, plan, _ = source
    # Avoid mutating the module LIMITS through the synthetic fixture's shared object.
    plan = json.loads(json.dumps(plan))
    change(plan)
    path.write_text(json.dumps(plan))
    with pytest.raises(ValueError):
        probe.prepare(path)


def test_watchdog_kills_only_owned_process_and_records_join():
    process, other, metrics = Process(), Process(), {}
    with probe.owned_watchdog(process, metrics, seconds=0):
        pass
    assert metrics["watchdog_fired"] and metrics["watchdog_joined"]
    assert process.stopped and not other.stopped


def test_fewer_than_384_stress_tokens_fails_resource_readiness(source):
    path, _, _ = source
    _, factory = launch_set()
    base = Base()
    original = base._complete

    def shortened(*args):
        result = original(*args)
        return GGUFResult(result.text, result.finish_reason, result.input_tokens,
                          20, .01, {})
    base._complete = shortened
    report = probe.run(probe.prepare(path), factory, lambda _: base)
    assert report["failure"] == "resource_stress_output_target"
    assert len(report["calls"]) == 2 and not report["readiness_passed"]


def test_tokenizer_only_registration_is_bounded_and_cannot_overwrite(source, monkeypatch):
    _, _, root = source
    counts = iter([500, 1000, 2500, 3850])
    path = root / "registered.json"
    report = probe.register(path, root / ".local/registered", loader=lambda _: (None, {"local": True}),
                            counter=lambda *_: next(counts))
    assert report["model_calls"] == 0
    assert report["cases"][1]["official_input_tokens"] == 3850
    probe.prepare(path)
    with pytest.raises(ValueError, match="output_exists"):
        probe.register(path, root / ".local/registered")


def test_unreachable_token_target_stops_before_registration(source):
    _, _, root = source
    path = root / "unreachable.json"
    with pytest.raises(ValueError, match="token_target_unreachable"):
        probe.register(path, root / ".local/new", loader=lambda _: (None, {}), counter=lambda *_: 4200)
    assert not path.exists()


def test_close_failure_after_successful_outputs_cannot_be_ready(source):
    path, _, _ = source
    _, factory = launch_set()
    bases = []

    def base_factory(service):
        base = Base()
        bases.append(base)
        if len(bases) == 1:
            def fail_close():
                raise ValueError("synthetic_close_failed")
            base.close = fail_close
        return base
    report = probe.run(probe.prepare(path), factory, base_factory)
    assert all(r["passed"] for r in report["results"])
    assert report["failure"] == "synthetic_close_failed"
    assert report["metadata_recovery"] and report["processes_stopped"]
    assert not report["readiness_passed"]


def test_live_previous_child_prevents_recovery_launch(source):
    path, _, _ = source
    starts = []

    @contextmanager
    def leaking(*args):
        p = Process()
        starts.append(p)
        yield SimpleNamespace(process=p)
    report = probe.run(probe.prepare(path), leaking, lambda _: Base())
    assert len(starts) == 1
    assert report["recovery_error"] == "resource_previous_process_not_stopped"
    assert not report["readiness_passed"]
    assert not report["processes_stopped"] and not report["metadata_recovery"]
