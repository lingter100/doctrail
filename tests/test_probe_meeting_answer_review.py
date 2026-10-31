"""Model-free synthetic C1 runner enforcement; no experiment/validation content read."""
import dataclasses
import json
import time
from contextlib import contextmanager

import pytest

from scripts import probe_meeting_answer_review as probe


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def payload():
    text = "The synthetic lamp is blue."
    return {"schema_version": 1, "query": "What color is the lamp?", "contexts": [{
        "document_id": "doc", "revision": 1, "chunk_id": "chunk", "title": "Synthetic",
        "meeting_date": None, "page": None, "start_offset": 0, "end_offset": len(text), "text": text}]}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    monkeypatch.setattr(probe, "REQUIRED_FILES", {"implementation.py"})
    (tmp_path / "implementation.py").write_text("# synthetic source\n")
    plan = {"schema_version": 1, "candidate": probe.CANDIDATE, "limits": probe.LIMITS.copy(),
            "retries": 0, "analysis_calls": 0, "warmup_calls": 0,
            "bound_files": {"implementation.py": probe.sha(tmp_path / "implementation.py")},
            "phases": {}, "calibration_gate": {"report": "out-calibration/report.json",
                                              "review": "review.json"}}
    for phase, count in probe.COUNTS.items():
        file = tmp_path / (phase + ".json")
        ids = [f"synthetic-{phase}-{n}" for n in range(count)]
        write(file, {"cases": [{"id": identity, "operation": "answer", "payload": payload(),
                                "expected_status": "answered"} for identity in ids]})
        plan["phases"][phase] = {"input_file": file.name, "input_sha256": probe.sha(file),
                                 "case_ids": ids, "output_dir": "out-" + phase,
                                 "max_native_calls": count * 4, "oracle_sha256": "a" * 64}
    path = tmp_path / "plan.json"
    write(path, plan)
    return tmp_path, path, plan


@dataclasses.dataclass
class Result:
    text: str = '{"status":"answered","claims":[]}'
    finish_reason: str = "eos"
    input_tokens: int = 15
    output_tokens: int = 20
    elapsed_seconds: float = .01


class Base:
    def __init__(self, effect=None):
        self.calls = 0
        self.effect = effect
        self.closed = False
        self.last_effective_config = {"temperature": 0}

    def _request(self, method, path, payload=None, deadline=None):
        if path == "/completion":
            self.calls += 1
            if self.effect:
                self.effect(self.calls)
        return {"content": "synthetic response", "tokens_predicted": 20}

    def _complete(self, messages, deadline, token_limit, grammar=""):
        self._request("POST", "/completion", {}, deadline)
        return Result()


class Generator:
    def __init__(self, effect=None):
        self.base = Base(effect)

    def public_metadata(self):
        return {"repo_id": "synthetic"}

    def close(self):
        self.base.closed = True


class Runtime:
    stage_count = 2
    error = None
    status = "answered"

    def __init__(self, generator):
        self.generator = generator
        self.last_telemetry = [{"checks": "synthetic"}]

    def answer(self, request):
        for index in range(self.stage_count):
            self.generator.base._complete([{"role": "user", "content": request.query}],
                                          time.monotonic() + 120,
                                          768 if index % 2 == 0 else 512, "synthetic grammar")
        if self.error:
            raise ValueError(self.error)
        return {"status": self.status, "claims": []}

    def close(self):
        self.generator.close()


@contextmanager
def service(log_dir, remaining):
    assert remaining > 0
    yield object()


def run_phase(setup, phase="neutral", generator=None, runtime=Runtime, service_factory=service):
    root, path, _ = setup
    prepared = probe.prepare(path, phase, root / ("out-" + phase))
    generator = generator or Generator()
    report = probe.run(prepared, service_factory, lambda _: generator, runtime)
    return report, generator


def allow_validation(setup):
    root, path, plan = setup
    run_phase(setup)
    run_phase(setup, "calibration")
    review = {"candidate": probe.CANDIDATE, "phase": "calibration",
              "report_sha256": probe.sha(root / "out-calibration/report.json"),
              "plan_sha256": probe.sha(path), "oracle_sha256": "a" * 64,
              "independent_of_implementation": True, "judgments_locked_before_comparison": True,
              "review_kind": "independent_semantic_review", "gate_passed": True,
              "cases": [{"id": identity, "d0_correct": i != 0, "c1_correct": True,
                         "answerable": i < 6, **dict.fromkeys(probe.QUALITY, True)}
                        for i, identity in enumerate(plan["phases"]["calibration"]["case_ids"])]}
    write(root / "review.json", review)
    return review


@pytest.mark.parametrize("stages", [2, 4])
def test_exact_stage_capture_and_once_only_output(setup, stages):
    class Selected(Runtime):
        stage_count = stages
    report, generator = run_phase(setup, runtime=Selected)
    assert report["status"] == "completed_not_semantically_verified"
    assert report["resources_passed"] and report["work_finalized"]
    assert report["sources_unchanged"] and generator.base.closed
    assert len(report["calls"]) == generator.base.calls == 2 * stages
    assert all(s["messages"] and s["output"] and s["effective_config"] for s in report["stages"])
    assert all(c["raw_response"] for c in report["calls"])
    assert all(r["adapter_checks"] for r in report["results"])
    root, path, _ = setup
    with pytest.raises(ValueError, match="output_exists"):
        probe.prepare(path, "neutral", root / "out-neutral")
    with pytest.raises(ValueError, match="mismatch"):
        probe.prepare(path, "neutral", root / "different")


def test_calibration_requires_neutral_before_inputs(setup, monkeypatch):
    root, path, _ = setup
    (root / "calibration.json").unlink()
    with pytest.raises(FileNotFoundError) as error:
        probe.prepare(path, "calibration", root / "out-calibration")
    assert "out-neutral" in str(error.value)


def test_validation_gate_before_any_sealed_input_access(setup, monkeypatch):
    root, path, _ = setup
    run_phase(setup)
    run_phase(setup, "calibration")
    write(root / "review.json", {"gate_passed": True})
    original_sha, original_read = probe.sha, probe.read_json
    def guarded_sha(file):
        assert Path(file).name != "validation.json"
        return original_sha(file)
    def guarded_read(file):
        assert Path(file).name != "validation.json"
        return original_read(file)
    from pathlib import Path
    monkeypatch.setattr(probe, "sha", guarded_sha)
    monkeypatch.setattr(probe, "read_json", guarded_read)
    with pytest.raises(ValueError, match="semantic_gate"):
        probe.prepare(path, "validation", root / "out-validation")


@pytest.mark.parametrize("mutation", ["no_improvement", "wrong_answer", "claim_support", "independence", "resource"])
def test_semantic_gate_rejects_false_success(setup, mutation):
    root, path, _ = setup
    review = allow_validation(setup)
    if mutation == "no_improvement":
        for row in review["cases"]:
            row["d0_correct"] = True
    elif mutation == "wrong_answer":
        review["cases"][1]["c1_correct"] = False
    elif mutation == "claim_support":
        review["cases"][0]["claim_support"] = False
    elif mutation == "independence":
        review["independent_of_implementation"] = False
    else:
        file = root / "out-calibration/report.json"
        report = probe.read_json(file)
        report["resources_passed"] = False
        write(file, report)
        review["report_sha256"] = probe.sha(file)
    write(root / "review.json", review)
    with pytest.raises(ValueError, match="not_passed"):
        probe.prepare(path, "validation", root / "out-validation")


def test_successful_independent_gate_allows_single_validation(setup):
    allow_validation(setup)
    report, generator = run_phase(setup, "validation")
    assert report["status"] == "completed_not_semantically_verified"
    assert len(report["results"]) == 8 and generator.base.calls == 16
    assert set(report["prerequisites"]["reports"]) == {"neutral", "calibration", "semantic_review"}


@pytest.mark.parametrize("mutation", ["source", "input", "plan"])
def test_mid_case_mutation_aborts_remaining_without_retry(setup, mutation):
    root, path, _ = setup
    def effect(count):
        if count == 1:
            selected = {"source": root / "implementation.py", "input": root / "neutral.json", "plan": path}[mutation]
            selected.write_text(selected.read_text() + " ")
    report, generator = run_phase(setup, generator=Generator(effect))
    assert report["status"] == "failed"
    assert generator.base.calls == 1 and len(report["results"]) == 1
    assert not report["sources_unchanged"]


def test_excess_stage_never_reaches_native(setup):
    class Excess(Runtime):
        stage_count = 5
    report, generator = run_phase(setup, runtime=Excess)
    assert generator.base.calls == 4
    assert report["failure"] == "candidate_stage_budget"


def test_duplicate_native_call_is_blocked(setup):
    generator = Generator()
    def complete(messages, deadline, token_limit, grammar=""):
        generator.base._request("POST", "/completion", {}, deadline)
        generator.base._request("POST", "/completion", {}, deadline)
        return Result()
    generator.base._complete = complete
    report, _ = run_phase(setup, generator=generator)
    assert generator.base.calls == 1 and report["failure"] == "candidate_unregistered_native_call"


def test_semantic_rejection_is_recorded_without_skipping_later_cases(setup):
    run_phase(setup)
    class Reject(Runtime):
        stage_count = 4
        error = "generation_semantic_rejected"
    report, generator = run_phase(setup, "calibration", runtime=Reject)
    assert len(report["results"]) == 8 and generator.base.calls == 32
    assert all(row["error"] == "generation_semantic_rejected" for row in report["results"])
    assert report["resources_passed"] and report["semantic_review"] == "pending"


def test_operational_failure_aborts_and_preserves_native_failure(setup):
    def fail(_):
        raise ValueError("generation_deadline_exceeded")
    report, generator = run_phase(setup, generator=Generator(fail))
    assert generator.base.calls == 1
    assert report["failure"] == "generation_deadline_exceeded"
    assert report["calls"][0]["error"] == "generation_deadline_exceeded"
    assert generator.base.closed


def test_wrong_neutral_control_blocks_readiness(setup):
    class Abstain(Runtime):
        status = "abstained"
    report, _ = run_phase(setup, runtime=Abstain)
    assert report["failure"] == "candidate_neutral_control_failed"


@pytest.mark.parametrize("mutation", ["hash", "order", "bound_input", "budget", "path"])
def test_manifest_mismatch_fails_before_native(setup, mutation):
    root, path, plan = setup
    spec = plan["phases"]["neutral"]
    if mutation == "hash":
        spec["input_sha256"] = "b" * 64
    elif mutation == "order":
        spec["case_ids"].reverse()
    elif mutation == "bound_input":
        plan["bound_files"]["validation.json"] = probe.sha(root / "validation.json")
    elif mutation == "budget":
        spec["max_native_calls"] = 9
    else:
        spec["input_file"] = "../outside.json"
    write(path, plan)
    with pytest.raises(ValueError):
        probe.prepare(path, "neutral", root / "out-neutral")


def test_startup_and_cleanup_in_work_budget(setup):
    events = []
    @contextmanager
    def measured(log_dir, remaining):
        events.append("start")
        yield object()
        events.append("cleanup")
    report, _ = run_phase(setup, service_factory=measured)
    assert events == ["start", "cleanup"] and report["work_finalized"]
    assert report["native_work_seconds"] > 0


def test_transient_persistence_retry_does_not_repeat_native(setup, monkeypatch):
    from pathlib import Path
    original = Path.replace
    failures = []
    def transient(path, destination):
        # First save after the first completed native HTTP request only.
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data["calls"] and "raw_response" in data["calls"][0] and not failures):
            failures.append(True)
            raise PermissionError("synthetic scanner lock")
        return original(path, destination)
    monkeypatch.setattr(Path, "replace", transient)
    report, generator = run_phase(setup)
    assert len(failures) == 1
    assert report["status"] == "completed_not_semantically_verified"
    assert generator.base.calls == len(report["calls"]) == len(report["stages"]) == 4
    assert sum(c["case_id"] == "synthetic-neutral-0" and c["stage"] == "D0"
               for c in report["calls"]) == 1


def test_persistence_exhaustion_consumes_claim_without_native(setup, monkeypatch):
    from pathlib import Path
    attempts = []
    def locked(path, destination):
        attempts.append(1)
        raise PermissionError("synthetic persistent scanner lock")
    monkeypatch.setattr(Path, "replace", locked)
    root, path, _ = setup
    prepared = probe.prepare(path, "neutral", root / "out-neutral")
    with pytest.raises(PermissionError):
        probe.claim_output(prepared)
    assert len(attempts) == 3 and (root / "out-neutral").exists()
    assert (root / "out-neutral/report.tmp").exists()
    with pytest.raises(ValueError, match="output_exists"):
        probe.prepare(path, "neutral", root / "out-neutral")


def test_completion_deadline_is_one_request_bound(setup):
    seen = []
    generator = Generator()
    original = generator.base._complete
    def record(messages, deadline, token_limit, grammar=""):
        seen.append(deadline)
        return original(messages, deadline, token_limit, grammar)
    generator.base._complete = record
    report, _ = run_phase(setup, generator=generator)
    assert report["resources_passed"]
    assert seen[0] == seen[1] and seen[2] == seen[3]


def test_cumulative_native_work_budget_blocks_next_phase(setup):
    root, path, _ = setup
    run_phase(setup)
    file = root / "out-neutral/report.json"
    report = probe.read_json(file)
    report["native_work_seconds"] = 2700
    write(file, report)
    with pytest.raises(ValueError, match="budget_exhausted"):
        probe.prepare(path, "calibration", root / "out-calibration")


@pytest.mark.parametrize("failure_point", ["construction", "start"])
def test_native_child_is_owned_before_watchdog_can_fail(tmp_path, monkeypatch, failure_point):
    import subprocess
    import threading

    from doctrail import meeting_qwen35, meeting_worker
    from scripts import prepare_meeting_gguf, serve_models

    events, launched = [], []
    child = object()

    @contextmanager
    def lease(path):
        events.append(("enter", path.name))
        try:
            yield
        finally:
            events.append(("exit", path.name))

    def popen(args, **kwargs):
        launched.append((args, kwargs))
        return child

    class BrokenTimer:
        def __init__(self, *args, **kwargs):
            if failure_point == "construction":
                raise RuntimeError("synthetic watchdog allocation failure")

        def start(self):
            raise RuntimeError("synthetic watchdog start failure")

        def cancel(self):
            events.append(("cancel",))

    monkeypatch.setattr(probe, "ROOT", tmp_path)
    monkeypatch.setattr(meeting_worker, "worker_lease", lease)
    monkeypatch.setattr(prepare_meeting_gguf, "prepare", lambda *a, **k: {
        "server_path": "runtime/server.exe", "model": {"path": "model.gguf"}})
    monkeypatch.setattr(probe, "read_json", lambda path: {
        "model": meeting_qwen35.MODEL_ID, "revision": meeting_qwen35.MODEL_REVISION,
        "gguf": {"sha256": meeting_qwen35.GGUF_SHA256}})
    monkeypatch.setattr(serve_models, "unused_port", lambda: 12345)
    monkeypatch.setattr(serve_models, "stop_process", lambda process: events.append(("stop", process)))
    monkeypatch.setattr(serve_models, "wait_ready", lambda *a, **k: pytest.fail("readiness reached"))
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(threading, "Timer", BrokenTimer)

    with (pytest.raises(RuntimeError, match="synthetic watchdog"),
          probe.native_service(tmp_path / "logs", 100)):
        pytest.fail("native context yielded")
    assert len(launched) == 1 and "--no-warmup" in launched[0][0]
    assert launched[0][1]["stdout"].closed
    assert events.count(("stop", child)) == 1
    assert sorted(value[1] for value in events if value[0] == "enter") == sorted(
        value[1] for value in events if value[0] == "exit")
    if failure_point == "start":
        assert events.index(("cancel",)) < events.index(("stop", child))
