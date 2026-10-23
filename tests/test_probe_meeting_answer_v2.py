import json
from types import SimpleNamespace

import pytest

from scripts import probe_meeting_answer_v2 as probe


def test_existing_evidence_cannot_be_overwritten(tmp_path):
    with pytest.raises(ValueError, match="output_exists"):
        probe.run(None, tmp_path / "missing", tmp_path)


def test_three_case_plan_rejected_before_model_call(tmp_path, monkeypatch):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"answer_cases": ["a", "b", "c"]}), encoding="utf-8")
    monkeypatch.setattr(probe, "verify_plan", lambda p: {"cases": [
        {"id": name, "operation": "answer"} for name in ["a", "b", "c"]]})
    with pytest.raises(ValueError, match="case_set"):
        probe.run(None, plan, tmp_path / "output")


def test_raw_failure_is_saved_without_retry_or_analysis(tmp_path, monkeypatch):
    from doctrail.generation_runtime import GenerationError
    from doctrail.meeting_answer_v2 import EvidenceFirstMeetingRuntime

    names = ["a", "b", "c", "d"]
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"answer_cases": names, "bound_files": {}}), encoding="utf-8")
    monkeypatch.setattr(probe, "verify_plan", lambda p: {"cases": [
        {"id": name, "operation": "answer", "payload": {"schema_version": 1,
         "query": name, "contexts": []}} for name in names]})
    model_calls, closed = [], []

    def generation(messages, deadline):
        model_calls.append(1)
        raise GenerationError("generation_test_failure")

    generator = SimpleNamespace(public_metadata=lambda: {"repo_id": "test", "revision": "test"},
                                generate_bounded=generation, classify_bounded=None,
                                close=lambda: closed.append(True))
    monkeypatch.setattr(EvidenceFirstMeetingRuntime, "answer", lambda self, request:
                        self.generator.generate_bounded([], 1))
    result = probe.run(generator, plan, tmp_path / "output")
    assert len(model_calls) == 4 and len(result["calls"]) == 4 and closed == [True]
    assert result["analysis_calls"] == 0
    assert all(row["structural_status"] == "failed" for row in result["results"])
    assert all(row["error"] == "generation_test_failure" for row in result["calls"])
    assert json.loads((tmp_path / "output/report.json").read_text(encoding="utf-8")) == result
