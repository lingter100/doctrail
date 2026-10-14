"""Only newly authored synthetic fixtures and fake transport; no model or pool reads."""
import copy
import json
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace

import pytest

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_gguf import GREEDY, GGUFResult
from doctrail.meeting_qwen35 import PREAMBLE_SHA256
from scripts import probe_meeting_blocks_comparison as probe


class Process:
    def __init__(self):
        self.stopped = False

    def poll(self):
        return 0 if self.stopped else None

    def kill(self):
        self.stopped = True

    def wait(self, timeout):
        assert timeout <= 5
        return 0


class Base:
    def __init__(self, effect=None):
        self.effect, self.closed, self.last_effective_config = effect, False, None
        self.calls = 0

    def public_metadata(self):
        return {"repo_id": "synthetic-model", "revision": "synthetic-revision"}

    def begin_request(self, deadline):
        self.last_effective_config = None

    def end_request(self):
        pass

    def count_tokens(self, messages):
        return 200

    def _request(self, method, path, payload=None, deadline=None):
        assert method == "POST" and path == "/completion"
        self.calls += 1
        return {"content": "raw synthetic response", "transport": "fake"}

    def _complete(self, messages, deadline, token_limit, grammar=""):
        payload = {**GREEDY, "n_predict": token_limit, "grammar": grammar,
                   "prompt": [7] * 200, "cache_prompt": False, "return_tokens": True}
        self._request("POST", "/completion", payload, deadline)
        self.last_effective_config = {"backend": "llama.cpp", **GREEDY,
            "n_predict": token_limit, "grammar": grammar, "cache_prompt_requested": False,
            "observed_cache_tokens": 0, "observed_nonthinking_preamble_sha256": PREAMBLE_SHA256,
            "enable_thinking_requested": False}
        if self.effect:
            self.effect(self, payload, deadline)
        return GGUFResult(json.dumps({"status": "answered", "claims": [{"evidence_ids": [0],
            "text": "The synthetic marker is mint."}]}), "eos", 200, 30, 0., {})

    def close(self):
        self.closed = True


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    monkeypatch.setattr(probe, "FILES", {"source.py"})
    monkeypatch.setattr(probe, "rss_samples", lambda *args: nullcontext())
    (tmp_path / "source.py").write_text("# synthetic source\n")
    (tmp_path / "resource.json").write_text('{"synthetic_resource":true}')
    resource_sha = probe.snapshot(tmp_path / "resource.json")[1]
    monkeypatch.setattr(probe, "RESOURCE_REPORT_SHA256", resource_sha)
    monkeypatch.setattr(probe, "RESOURCE_REPORT_FILE", "resource.json")
    payload = {"schema_version": 1, "query": "What is the synthetic marker?", "contexts": [{
        "document_id": "synthetic-doc", "revision": 1, "chunk_id": "synthetic-chunk",
        "title": "Synthetic marker", "meeting_date": None, "page": None,
        "start_offset": 0, "end_offset": 31, "text": "The synthetic marker is mint.\n\n"}]}
    cases = [{"id": f"c-{i}", "payload": copy.deepcopy(payload),
              "official_input_tokens": {"L0": 200, "C2": 200}} for i in range(8)]
    write(tmp_path / "input.json", {"schema_version": 1, "phase": "calibration", "cases": cases})
    plan = {"schema_version": 1, "candidate": probe.CANDIDATE, "limits": copy.deepcopy(probe.LIMITS),
        "bound_files": {"source.py": probe.snapshot(tmp_path / "source.py")[1]},
        "runtime_receipt_sha256": probe.fingerprint({"synthetic_runtime": True}),
        "resource_report": {"file": "resource.json", "sha256": resource_sha},
        "audit": {"calibration": {"seed_sha256": "a" * 64, "reviewer_id": "synthetic-reviewer-cal", "seed_file": ".local/cal.seed", "output_dir": ".local/cal-audit"},
                  "validation": {"seed_sha256": "b" * 64, "reviewer_id": "synthetic-reviewer-val", "seed_file": ".local/val.seed", "output_dir": ".local/val-audit"}},
        "excluded_reviewer_ids": ["synthetic-author"],
        "tokenizer": {"synthetic_tokenizer": True}, "phases": {
            "calibration": {"case_ids": [c["id"] for c in cases], "input_file": "input.json", "oracle_file": "oracle.json",
                "input_sha256": probe.snapshot(tmp_path / "input.json")[1], "oracle_sha256": "1" * 64,
                "output_dir": ".local/calibration"},
            "validation": {"case_ids": [f"v-{i}" for i in range(12)],
                "input_file": "sealed-not-present.json", "oracle_file": "sealed-oracle.json", "input_sha256": "2" * 64,
                "oracle_sha256": "3" * 64, "output_dir": ".local/validation"}}}
    path = tmp_path / "plan.json"
    write(path, plan)
    return SimpleNamespace(root=tmp_path, path=path, plan=plan, cases=cases)


def prepare(source, phase="calibration", gate=None):
    return probe.prepare(source.path, phase, gate,
        loader=lambda download: (None, {"synthetic_tokenizer": True}), counter=lambda *_: 200)


def launch():
    processes = []

    @contextmanager
    def factory(*args):
        process = Process()
        processes.append(process)
        try:
            yield SimpleNamespace(process=process, receipt={"synthetic_runtime": True})
        finally:
            process.kill()
    return factory, processes


def run(source, base=None):
    factory, processes = launch()
    base = base or Base()
    return probe.run(prepare(source), factory, lambda _: base), processes, base


def test_two_arm_alternating_all_sixteen_dispatches_and_raw_evidence(source):
    report, processes, base = run(source)
    assert report["resources_passed"] and report["status"] == "completed_not_semantically_verified"
    assert not report["semantics_verified"] and report["human_review_count"] == 0
    assert len(report["results"]) == len(report["calls"]) == base.calls == 16
    assert len(processes) == 1 and processes[0].stopped and base.closed
    assert [(c["id"], c["arm"]) for c in report["calls"]] == probe.schedule(
        "calibration", source.plan["phases"]["calibration"]["case_ids"])
    assert [r["arm"] for r in report["results"][:4]] == ["L0", "C2", "C2", "L0"]
    assert not report["unexecuted"] and report["sources_unchanged"]
    assert all(c["raw_response"]["content"] == "raw synthetic response" for c in report["calls"])
    for i in range(0, 16, 2):
        assert report["results"][i]["payload_sha256"] == report["results"][i + 1]["payload_sha256"]
    with pytest.raises(ValueError, match="output_exists"):
        prepare(source)


def test_native_failure_persists_dispatch_before_post_and_never_continues(source):
    base = Base()

    def fail(*args):
        report = json.loads((source.root / ".local/calibration/report.json").read_text())
        assert len(report["calls"]) == 1 and report["calls"][0]["dispatch_attempted"]
        raise GenerationError("generation_deadline_exceeded")
    base._request = fail
    report, processes, base = run(source, base)
    assert report["failure"] == "generation_deadline_exceeded"
    assert report["calls"][0]["error"] == "generation_deadline_exceeded"
    assert len(report["calls"]) == len(report["results"]) == 1
    assert len(report["unexecuted"]) == 15 and not report["resources_passed"]
    assert processes[0].stopped and base.closed


def test_duplicate_dispatch_rejected_and_source_changes_stop_before_next_case(source):
    def duplicate(base, payload, deadline):
        base._request("POST", "/completion", payload, deadline)
    report, _, base = run(source, Base(duplicate))
    assert base.calls == 1 and len(report["calls"]) == 1 and not report["resources_passed"]


def test_source_change_during_call_is_preserved_and_stops(source):
    def change(*args):
        (source.root / "source.py").write_text("# changed\n")
    report, _, base = run(source, Base(change))
    assert base.calls == 1 and not report["sources_unchanged"]
    assert report["failure"] == report["source_error"] == "comparison_source_changed"
    assert len(report["unexecuted"]) == 15


@pytest.mark.parametrize("field,value", [("n_predict", 385), ("seed", 4),
    ("cache_prompt_requested", True), ("observed_cache_tokens", 1),
    ("enable_thinking_requested", True), ("observed_nonthinking_preamble_sha256", "bad")])
def test_effective_configuration_drift_is_fatal(source, field, value):
    def change(base, *args):
        base.last_effective_config[field] = value
    report, _, base = run(source, Base(change))
    assert base.calls == 1 and not report["resources_passed"]
    assert report["failure"] == "comparison_row_integrity"


@pytest.mark.parametrize("change", [lambda p: p.update(schema_version=True),
    lambda p: p["limits"].update(retries=False),
    lambda p: p["phases"]["calibration"].update(output_dir="../outside"),
    lambda p: p["phases"]["validation"].update(output_dir=".local/calibration/nested"),
    lambda p: p["phases"]["calibration"].update(case_ids=["duplicate"] * 8),
    lambda p: p["bound_files"].update(extra="0" * 64)])
def test_unregistered_plan_mutations_rejected(source, change):
    change(source.plan)
    write(source.path, source.plan)
    with pytest.raises(ValueError):
        prepare(source)


def test_calibration_does_not_touch_validation_input(source, monkeypatch):
    original = probe.snapshot

    def guard(path):
        assert str(path).endswith("sealed-not-present.json") is False
        return original(path)
    monkeypatch.setattr(probe, "snapshot", guard)
    assert len(prepare(source)["schedule"]) == 16


def test_validation_gate_failure_precedes_even_input_hash(source, monkeypatch):
    touched = []
    original = probe.snapshot

    def guard(path):
        touched.append(str(path))
        assert not str(path).endswith("sealed-not-present.json")
        return original(path)

    def failed_gate(prepared):
        raise ValueError("synthetic_independent_gate_failed")
    monkeypatch.setattr(probe, "snapshot", guard)
    monkeypatch.setattr(probe, "verify_gate", failed_gate)
    with pytest.raises(ValueError, match="independent_gate_failed"):
        prepare(source, "validation", "locked-gate.json")
    assert touched == [str(source.path)]


def test_validation_selected_candidate_only_twelve_calls(source, monkeypatch):
    spec = source.plan["phases"]["validation"]
    cases = [dict(copy.deepcopy(source.cases[0]), id=i) for i in spec["case_ids"]]
    path = source.root / spec["input_file"]
    write(path, {"schema_version": 1, "phase": "validation", "cases": cases})
    spec["input_sha256"] = probe.snapshot(path)[1]
    write(source.path, source.plan)
    monkeypatch.setattr(probe, "verify_gate", lambda _: {"synthetic_gate": True})
    factory, _ = launch()
    report = probe.run(prepare(source, "validation", "gate.json"), factory, lambda _: Base())
    assert report["resources_passed"] and len(report["calls"]) == 12
    assert all(r["arm"] == "C2" for r in report["results"])


def test_once_only_output_claim_survives_startup_failure(source):
    prepared = prepare(source)

    def failure(*args):
        raise RuntimeError("private detail that must not escape")
    report = probe.run(prepared, failure)
    assert report["failure"] == "RuntimeError" and not report["calls"]
    assert len(report["unexecuted"]) == 16
    with pytest.raises(FileExistsError):
        probe.run(prepared, failure)


def test_watchdog_terminates_only_owned_child():
    owned, other, metrics = Process(), Process(), {}
    with probe.watchdog(owned, metrics, seconds=0):
        pass
    assert metrics["watchdog_fired"] and metrics["watchdog_joined"]
    assert owned.stopped and not other.stopped


def test_token_budget_and_tokenizer_identity_fail_before_claim(source):
    with pytest.raises(ValueError, match="token_budget"):
        probe.prepare(source.path, "calibration", loader=lambda _: (None, source.plan["tokenizer"]),
                      counter=lambda *_: 4097)
    with pytest.raises(ValueError, match="tokenizer_changed"):
        probe.prepare(source.path, "calibration", loader=lambda _: (None, {"changed": True}))
    assert not (source.root / ".local/calibration").exists()


def test_truncation_stops_after_single_call(source):
    base = Base()
    original = base._complete

    def truncated(*args):
        output = original(*args)
        return GGUFResult(output.text, "length", 200, 384, output.elapsed_seconds, {})
    base._complete = truncated
    report, _, _ = run(source, base)
    assert len(report["calls"]) == 1 and report["failure"] == "generation_output_truncated"
    assert not report["resources_passed"]


def test_structurally_valid_abstention_remains_unscored_and_does_not_stop(source):
    base = Base()
    original = base._complete

    def abstain(*args):
        output = original(*args)
        # Preserve the fake backend's measured-duration contract. A fixed10ms
        # exceeds the whole request on fast CI and must be rejected by the guard.
        return GGUFResult('{"status":"abstained","claims":[]}', "eos", 200, 10,
                          output.elapsed_seconds, {})
    base._complete = abstain
    report, _, _ = run(source, base)
    assert report["resources_passed"] and len(report["calls"]) == 16
    assert all(r["response"]["status"] == "abstained" for r in report["results"])
    assert report["semantics_verified"] is False


def test_runtime_artifact_receipt_drift_prevents_any_generation(source):
    source.plan["runtime_receipt_sha256"] = "a" * 64
    write(source.path, source.plan)
    report, processes, base = run(source)
    assert not report["calls"] and report["failure"] == "comparison_runtime_receipt_changed"
    assert processes[0].stopped and base.calls == 0


def test_missing_dispatch_never_passes(source):
    base = Base()
    original = base._complete

    def no_dispatch(*args):
        dispatch = base._request
        base._request = lambda *args: {}
        try:
            return original(*args)
        finally:
            base._request = dispatch
    base._complete = no_dispatch
    report, _, _ = run(source, base)
    assert report["failure"] == "comparison_row_integrity" and not report["calls"]
    assert len(report["unexecuted"]) == 16


def test_input_mutation_after_preparation_fails_before_claim(source):
    prepared = prepare(source)
    (source.root / "input.json").write_text("{}")
    with pytest.raises(ValueError, match="input_changed"):
        probe.run(prepared)
    assert not prepared["output"].exists()


def test_closed_resource_report_mutation_fails_before_claim(source):
    (source.root / "resource.json").write_text("{}")
    with pytest.raises(ValueError, match="resource_report_changed"):
        prepare(source)
    assert not (source.root / ".local/calibration").exists()


def test_close_failure_invalidates_even_completed_sixteen_rows(source):
    base = Base()

    def fail_close():
        raise RuntimeError("do not print this")
    base.close = fail_close
    report, processes, _ = run(source, base)
    assert len(report["calls"]) == 16 and not report["resources_passed"]
    assert report["failure"] == "RuntimeError" and processes[0].stopped


def test_request_configuration_rejected_before_native_transport(source):
    base = Base()

    def wrong(*args):
        base._request("POST", "/completion", {"prompt": [1], "n_predict": 500})
    base._complete = wrong
    report, _, _ = run(source, base)
    assert base.calls == 0 and not report["calls"] and not report["resources_passed"]


def test_incorrect_claim_text_is_not_automatically_semantically_scored(source):
    base = Base()
    original = base._complete

    def wrong_fact(*args):
        result = original(*args)
        return GGUFResult(json.dumps({"status": "answered", "claims": [{
            "text": "The synthetic marker is purple.", "evidence_ids": [0]}]}),
            "eos", result.input_tokens, result.output_tokens, result.elapsed_seconds, {})
    base._complete = wrong_fact
    report, _, _ = run(source, base)
    assert len(report["calls"]) == 16 and report["resources_passed"]
    assert report["semantics_verified"] is False
