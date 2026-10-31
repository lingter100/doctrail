import json

import pytest

from scripts import probe_meeting_answer_grammar as probe


def test_decoder_plan_verified_before_native_load(tmp_path, monkeypatch):
    plan = {"decoder_policy": probe.DECODER_POLICY, "grammar_sha256": probe.GRAMMAR_SHA256,
            "completion_calls": 4, "analysis_calls": 0, "retries": 0}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    verified = []
    monkeypatch.setattr(probe, "verify_plan", lambda value: verified.append(value))
    assert probe.check_plan(path) == plan
    assert verified == [plan]
    plan["grammar_sha256"] = "wrong"
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="decoder_plan_mismatch"):
        probe.check_plan(path)
    assert len(verified) == 1
