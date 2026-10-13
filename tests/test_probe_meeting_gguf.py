import json

import pytest

from scripts import probe_meeting_gguf as probe


def bound(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    fixture = tmp_path / "fixture.txt"
    fixture.write_text("source", encoding="utf-8")
    source = tmp_path / "worker.py"
    source.write_text("protocol", encoding="utf-8")
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps({"cases": [{"id": str(i)} for i in range(5)],
                                 "fixture_hashes": {"fixture.txt": probe.sha(fixture)}}),
                      encoding="utf-8")
    return {"inputs": "inputs.json", "bound_files": {
        "inputs.json": probe.sha(inputs), "worker.py": probe.sha(source)}}


def test_changed_source_rejected_before_candidate_execution(tmp_path, monkeypatch):
    plan = bound(tmp_path, monkeypatch)
    assert len(probe.verify_plan(plan)["cases"]) == 5
    (tmp_path / "worker.py").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="source_binding"):
        probe.verify_plan(plan)


def test_changed_fixture_rejected(tmp_path, monkeypatch):
    plan = bound(tmp_path, monkeypatch)
    (tmp_path / "fixture.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="fixture_binding"):
        probe.verify_plan(plan)


def test_existing_output_never_overwritten(tmp_path):
    output = tmp_path / "report"
    output.mkdir()
    with pytest.raises(ValueError, match="output_exists"):
        probe.run(None, tmp_path / "nonexistent-plan", output)
