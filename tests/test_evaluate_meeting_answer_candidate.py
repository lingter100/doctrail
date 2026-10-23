"""Synthetic evaluator-control cases only; never read the custodian validation pool."""
import hashlib
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from doctrail.generation_runtime import GenerationError
from scripts import evaluate_meeting_answer_candidate as evaluator


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluator, "ROOT", tmp_path)
    source = tmp_path / "source.py"
    source.write_text("synthetic frozen source", encoding="utf-8")
    runner = tmp_path / evaluator.RUNNER_PATH
    runner.parent.mkdir(parents=True)
    runner.write_text("synthetic runner binding", encoding="utf-8")
    source_plan = tmp_path / "source-plan.json"
    write_json(source_plan, {"bound_files": {"source.py": digest(source)}})
    cases = [{"id": f"synthetic_{i}", "operation": "answer",
        "provenance": {"kind": "synthetic-control-test", "human_review_count": 0},
        "payload": {"schema_version": 1, "query": f"Synthetic question {i}?", "contexts": [{
            "document_id": "doc", "revision": 1, "chunk_id": "chunk", "title": "Synthetic",
            "meeting_date": None, "page": None, "start_offset": 0, "end_offset": 6,
            "text": "Source"}]}} for i in range(12)]
    inputs = tmp_path / "cases.json"
    write_json(inputs, {"cases": cases})
    gate_report, gate_review = tmp_path / "gate-report.json", tmp_path / "gate-review.json"
    write_json(gate_report, {"status": "synthetic-known-report"})
    write_json(gate_review, {"gate_passed": True, "report_sha256": digest(gate_report)})
    paths = [source, runner, source_plan, inputs, gate_report, gate_review]
    plan = {"inputs": "cases.json", "bound_files": {
        str(path.relative_to(tmp_path)).replace("\\", "/"): digest(path) for path in paths},
        "candidate_source_plan": {"path": "source-plan.json", "sha256": digest(source_plan)},
        "gate": {"report": "gate-report.json", "report_sha256": digest(gate_report),
                 "review": "gate-review.json", "review_sha256": digest(gate_review)}}
    plan_path = tmp_path / "plan.json"
    write_json(plan_path, plan)
    state = SimpleNamespace(root=tmp_path, plan=plan, plan_path=plan_path, cases=cases,
        output=tmp_path / "output", events=[], calls=[], fail_at=None, malformed_at=None,
        load_failure=False, mutate_source=False, classifier_calls=0)

    def rebind():
        for name in plan["bound_files"]:
            plan["bound_files"][name] = digest(tmp_path / name)
        plan["candidate_source_plan"]["sha256"] = digest(source_plan)
        plan["gate"]["review_sha256"] = digest(gate_review)
        write_json(plan_path, plan)
    state.rebind = rebind

    def launcher(name):
        @contextmanager
        def launch(**kwargs):
            state.events.append("start_" + name)
            try:
                yield SimpleNamespace(url="http://127.0.0.1:19003", token="PRIVATE_CREDENTIAL",
                                      manifest=tmp_path / "manifest.json")
            finally:
                state.events.append("stop_" + name)
                if state.mutate_source:
                    source.write_text("changed", encoding="utf-8")
        return launch

    class Generator:
        def __init__(self, *args):
            self.last_effective_config = None
        def load(self):
            state.events.append("load")
            if state.load_failure:
                raise RuntimeError("PRIVATE_CREDENTIAL and C:/private/model")
            return self
        def public_metadata(self):
            return {"repo_id": "synthetic/model", "revision": "synthetic-revision"}
        def count_tokens(self, messages):
            return 100
        def generate_bounded(self, messages, deadline):
            state.calls.append(messages)
            if state.fail_at == len(state.calls):
                raise GenerationError("generation_deadline_exceeded")
            self.last_effective_config = {"temperature": 0, "grammar": "synthetic"}
            text = ("PRIVATE malformed raw output" if state.malformed_at == len(state.calls)
                    else '{"status":"abstained","claims":[]}')
            return SimpleNamespace(text=text, finish_reason="eos", input_tokens=100,
                                   output_tokens=10, elapsed_seconds=0.1)
        def classify_bounded(self, *args):
            state.classifier_calls += 1
            pytest.fail("analysis must never execute")
        def close(self):
            state.events.append("close")

    monkeypatch.setattr(evaluator, "start_baseline", launcher("baseline"))
    monkeypatch.setattr(evaluator, "start_qwen35", launcher("qwen35"))
    monkeypatch.setattr(evaluator, "GrammarAnswerGenerator", Generator)
    monkeypatch.setattr(evaluator, "Qwen35Generator", Generator)
    return state


@pytest.mark.parametrize("candidate", ["baseline", "qwen35"])
def test_twelve_calls_once_with_explicit_identity_and_source_receipts(scenario, candidate, capsys):
    report = evaluator.run(candidate, scenario.plan_path, scenario.output)
    assert len(scenario.calls) == report["call_count"] == 12
    assert len(report["results"]) == 12 and report["structural_failures"] == 0
    assert report["status"] == "completed_not_semantically_verified"
    assert report["quality_verified"] is False and report["human_review_count"] == 0
    assert report["blinded"] is False and report["candidate"] == candidate
    assert report["bound_files_before"] == report["bound_files_after"]
    assert report["plan_sha256"] == report["plan_sha256_after"]
    assert scenario.events == ["start_" + candidate, "load", "close", "stop_" + candidate]
    assert scenario.classifier_calls == report["analysis_calls"] == 0
    console = capsys.readouterr().out
    assert "question" not in console and "PRIVATE" not in console
    assert console.splitlines() == [f"synthetic_{i} passed" for i in range(12)]


@pytest.mark.parametrize("gate", [False, None, 1, "true"])
def test_failed_or_untyped_semantic_gate_prevents_launch(scenario, gate):
    review = scenario.root / "gate-review.json"
    write_json(review, {"gate_passed": gate, "report_sha256": scenario.plan["gate"]["report_sha256"]})
    scenario.rebind()
    with pytest.raises(GenerationError, match="candidate_semantic_gate_not_passed"):
        evaluator.run("qwen35", scenario.plan_path, scenario.output)
    assert not scenario.events and not scenario.calls and not scenario.output.exists()


def test_review_cannot_authorize_a_different_report(scenario):
    write_json(scenario.root / "gate-review.json", {"gate_passed": True, "report_sha256": "a" * 64})
    scenario.rebind()
    with pytest.raises(GenerationError, match="semantic_gate_not_passed"):
        evaluator.run("baseline", scenario.plan_path, scenario.output)
    assert not scenario.events


@pytest.mark.parametrize("mutation", ["eleven", "thirteen", "duplicate", "analyze", "bad_schema", "empty"])
def test_all_case_schemas_checked_before_model_load(scenario, mutation):
    cases = scenario.cases
    if mutation == "eleven":
        cases.pop()
    elif mutation == "thirteen":
        cases.append(cases[-1])
    elif mutation == "duplicate":
        cases[-1]["id"] = cases[0]["id"]
    elif mutation == "analyze":
        cases[-1]["operation"] = "analyze"
    elif mutation == "empty":
        cases[-1]["payload"]["contexts"] = []
    else:
        cases[-1]["payload"]["contexts"][0]["revision"] = True
    write_json(scenario.root / "cases.json", {"cases": cases})
    scenario.rebind()
    with pytest.raises(GenerationError, match="candidate_case"):
        evaluator.run("baseline", scenario.plan_path, scenario.output)
    assert not scenario.events and not scenario.output.exists()


def test_existing_output_is_never_overwritten(scenario):
    scenario.output.mkdir()
    marker = scenario.output / "report.json"
    marker.write_text("previous result", encoding="utf-8")
    with pytest.raises(GenerationError, match="candidate_output_exists"):
        evaluator.run("baseline", scenario.plan_path, scenario.output)
    assert marker.read_text(encoding="utf-8") == "previous result" and not scenario.events


@pytest.mark.parametrize("failure", ["fail_at", "malformed_at"])
def test_failure_preserves_partial_raw_and_continues_without_retry(scenario, failure, capsys):
    setattr(scenario, failure, 3)
    report = evaluator.run("qwen35", scenario.plan_path, scenario.output)
    assert report["call_count"] == 12 and report["structural_failures"] == 1
    assert report["results"][2]["structural_status"] == "failed"
    assert [call["case_id"] for call in report["calls"]] == [f"synthetic_{i}" for i in range(12)]
    if failure == "malformed_at":
        assert report["calls"][2]["output"]["text"] == "PRIVATE malformed raw output"
    else:
        assert report["calls"][2]["error"] == "generation_deadline_exceeded"
    assert "PRIVATE" not in capsys.readouterr().out


def test_load_failure_is_safe_zero_call_report_and_owned_cleanup(scenario):
    scenario.load_failure = True
    report = evaluator.run("baseline", scenario.plan_path, scenario.output)
    assert report["status"] == "failed" and report["call_count"] == 0
    assert report["error"] == "RuntimeError"
    assert scenario.events == ["start_baseline", "load", "close", "stop_baseline"]
    assert "PRIVATE" not in (scenario.output / "report.json").read_text(encoding="utf-8")


def test_source_plan_freeze_must_be_reproduced_in_candidate_plan(scenario):
    source_plan = scenario.root / "source-plan.json"
    write_json(source_plan, {"bound_files": {"source.py": "a" * 64}})
    scenario.rebind()
    with pytest.raises(GenerationError, match="candidate_source_plan_mismatch"):
        evaluator.run("qwen35", scenario.plan_path, scenario.output)
    assert not scenario.events


def test_source_change_after_run_invalidates_completed_calls(scenario):
    scenario.mutate_source = True
    report = evaluator.run("baseline", scenario.plan_path, scenario.output)
    assert report["call_count"] == 12 and report["status"] == "failed"
    assert report["sources_unchanged"] is False
    assert report["bound_files_after"] != report["bound_files_before"]


def test_unbound_or_outside_input_never_launches(scenario):
    scenario.plan["inputs"] = "../outside.json"
    write_json(scenario.plan_path, scenario.plan)
    with pytest.raises(GenerationError):
        evaluator.run("baseline", scenario.plan_path, scenario.output)
    assert not scenario.events


def test_accidental_second_call_for_same_case_is_blocked(scenario, monkeypatch):
    original_runtime = evaluator.EvidenceFirstMeetingRuntime
    class RepeatingRuntime(original_runtime):
        def answer(self, request):
            super().answer(request)
            return super().answer(request)
    monkeypatch.setattr(evaluator, "EvidenceFirstMeetingRuntime", RepeatingRuntime)
    report = evaluator.run("baseline", scenario.plan_path, scenario.output)
    assert len(scenario.calls) == report["call_count"] == 12
    assert len({call["case_id"] for call in report["calls"]}) == 12
    assert report["structural_failures"] == 12
