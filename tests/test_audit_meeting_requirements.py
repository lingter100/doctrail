"""Synthetic answer locks, raw replay and gate-before-heldout checks only."""
import copy
import json

import pytest

from scripts import audit_meeting_requirements as audit
from scripts import probe_meeting_requirements as probe
from tests.test_probe_meeting_requirements import factory as factory_fixture
from tests.test_probe_meeting_requirements import run_phase, write
from tests.test_probe_meeting_requirements import world as world_fixture

factory, world = factory_fixture, world_fixture


def judgments(pack, reviewer):
    rows = []
    for sample in pack["samples"]:
        answered = sample["answer"]["status"] == "answered"
        correct = answered == (sample["oracle"]["expected_status"] == "answered")
        claims = []
        for index, claim in enumerate(sample["answer"]["claims"]):
            claims.append({"claim_index": index, "facts": [{"text": claim["text"], "supported": True,
                "support": [{"citation_index": 0, "start_offset": claim["citations"][0]["start_offset"],
                    "end_offset": claim["citations"][0]["end_offset"]}]}],
                "citations": [{"citation_index": i, "relevant": True, "reason": "Synthetic relevance."}
                    for i, _ in enumerate(claim["citations"])]})
        quality = {k: True for k in ("language", "temporal", "subject", "conditions", "citation_exact", "claim_support", "completeness", "correct_abstention_or_answer")}
        quality["correct_abstention_or_answer"] = correct
        quality["completeness"] = answered or correct
        rows.append({"sample_id": sample["sample_id"], "quality": quality, "claims": claims,
            "required_facts": [{"fact_id": f["id"], "present": answered, "reason": "Synthetic coverage vote."} for f in sample["oracle"]["required_facts"]],
            "full_correct": all(quality.values()), "reason": "Synthetic test only.",
            "masking_guess": {"unit_style": "unknown", "confidence": "none", "reason": "Unknown."}})
    return {"schema_version": 1, "reviewer_id": reviewer, "human_review_count": 0, "mapping_not_seen": True, "independent_of_authors_and_designers": True, "judgments": rows}


def diagnostics(plan_pack, reveal, reviewer):
    rows = []
    for sample in plan_pack["samples"]:
        req = sample["plan"]["requirements"][0]
        answered = sample["answer"]["status"] == "answered"
        rows.append({"sample_id": sample["sample_id"], "plan_sha256": sample["plan_sha256"],
            "requirements": [{"requirement_id": 1, "oracle_fact_ids": [], "need_relevant": True,
                "support_assessment": "not_assessable", "status_justified": False,
                "reason": "Deliberately adverse plan diagnostic; cannot change locked answers.", "support_offsets": []}],
            "oracle_coverage": [{"fact_id": f["id"], "requirement_ids": [], "need_covered": False, "reason": "Synthetic omitted need."}
                for f in sample["oracle"]["required_facts"]],
            "realization_checks": [{"requirement_id": 1, "fully_realized": False, "added_inference": True,
                "reason": "Synthetic adverse diagnostic."}] if answered else [],
            "abstention_branch": None if answered else "stage2" if req["status"] == "supported" else "stage1",
            "abstention_appropriate": None if answered else True, "abstention_reason": None if answered else "Synthetic missing requirement.",
            "failure_categories": [{"category": "requirement_omission", "evidence": "Synthetic diagnostic only."}]})
    return {"schema_version": 1, "purpose": "post_lock_plan_diagnostic", "reviewer_id": reviewer,
        "answer_lock_sha256": reveal["answer_lock_sha256"], "plan_pack_sha256": reveal["plan_pack_sha256"],
        "human_review_count": 0, "items": rows}


def completed(world, phase="calibration", gate=None):
    world.transport.status_for_case = lambda case: "missing" if case["id"].rsplit("-", 1)[-1] in {"2", "3"} else "supported"
    report = run_phase(world, phase, gate)
    assert report["status"] == "completed", report
    receipt = audit.prepare(world.plan_name, phase, gate, root=world.root)
    files = audit.paths(receipt["output_dir"], world.root)
    pack = json.loads((world.root / files["pack"]).read_bytes())
    votes = judgments(pack, receipt["reviewer_id"])
    write(world.root / files["judgments"], votes)
    return receipt, files, pack, votes


def finish(world, phase="calibration", gate=None, lock_reads=None):
    receipt, files, _pack, _votes = completed(world, phase, gate)
    if lock_reads is not None:
        from unittest.mock import patch
        original = probe.Snapshots.get
        def record(self, name, expected=None):
            lock_reads.append(name)
            assert name not in {files["mapping"], files["plan_pack"], world.plan["phases"][phase]["output_dir"] + "/report.json", world.val.names["oracle"], world.val.names["inventory"]}
            return original(self, name, expected)
        with patch.object(probe.Snapshots, "get", record):
            audit.lock_answers(receipt["output_dir"], root=world.root)
    else:
        audit.lock_answers(receipt["output_dir"], root=world.root)
    reveal = audit.reveal_plan(world.plan_name, phase, gate, root=world.root)
    plan_pack = json.loads((world.root / files["plan_pack"]).read_bytes())
    write(world.root / files["diagnostics"], diagnostics(plan_pack, reveal, receipt["reviewer_id"]))
    result = audit.finalize(world.plan_name, phase, gate, root=world.root)
    return result, files


def test_whole_cal_gate_then_validation_and_adverse_diagnostic_cannot_change_score(world):
    cal, files = finish(world)
    assert cal["selected"] and cal["summary"]["full_correct"] == 6
    assert not cal["automatic_adoption"] and not cal["plan_diagnostics_affect_selection"]
    seen = []
    val, _ = finish(world, "validation", files["result"], seen)
    assert world.plan["phases"]["calibration"]["output_dir"] + "/report.json" in seen
    assert val["validation_passed"] and val["summary"]["full_correct"] == 8
    assert len(val["ledger_entries"]) == 26  # neutral4 + cal10 + val12; below max32


def test_final_pack_and_lock_do_not_open_current_plan_mapping_raw(world, monkeypatch):
    receipt, files, pack, _ = completed(world)
    assert all(set(s) == audit.SAMPLE_KEYS for s in pack["samples"])
    assert all(s["oracle"]["id"] == s["sample_id"] for s in pack["samples"])
    original = probe.Snapshots.get
    seen = []
    def record(self, name, expected=None):
        seen.append(name)
        return original(self, name, expected)
    monkeypatch.setattr(probe.Snapshots, "get", record)
    audit.lock_answers(receipt["output_dir"], root=world.root)
    assert files["mapping"] not in seen and files["plan_pack"] not in seen
    assert world.plan_name not in seen
    assert not any("/report.json" in name or "/oracle.json" in name for name in seen)


def test_reveal_before_lock_does_not_open_mapping_or_native_raw(world, monkeypatch):
    _, files, _, _ = completed(world)
    original = probe.Snapshots.get
    seen = []
    def record(self, name, expected=None):
        seen.append(name)
        return original(self, name, expected)
    monkeypatch.setattr(probe.Snapshots, "get", record)
    with pytest.raises(FileNotFoundError):
        audit.reveal_plan(world.plan_name, "calibration", root=world.root)
    assert files["mapping"] not in seen
    assert not any("/report.json" in name for name in seen)


def test_locked_judgment_change_stops_before_plan_replay(world, monkeypatch):
    receipt, files, _, votes = completed(world)
    audit.lock_answers(receipt["output_dir"], root=world.root)
    votes["judgments"][0]["reason"] += " Changed after lock."
    write(world.root / files["judgments"], votes)
    monkeypatch.setattr(audit, "replay", lambda *a, **k: pytest.fail("opened raw after changed judgment"))
    with pytest.raises(ValueError, match="lock_changed"):
        audit.reveal_plan(world.plan_name, "calibration", root=world.root)


def test_bad_or_absent_gate_never_opens_validation_semantics(world, monkeypatch):
    original = probe.Snapshots.get
    seen = []
    def record(self, name, expected=None):
        assert not ("meetings-c3-validation-" in name), "heldout opened before gate"
        seen.append(name)
        return original(self, name, expected)
    monkeypatch.setattr(probe.Snapshots, "get", record)
    with pytest.raises(ValueError, match="selection_path"):
        probe.check(world.plan_name, "validation", root=world.root)
    with pytest.raises(ValueError, match="selection_path"):
        audit.prepare(world.plan_name, "validation", root=world.root)
    assert world.val.names["oracle"] not in seen


def test_forged_selected_true_requires_original_replay(world, monkeypatch):
    result, files = finish(world)
    original = probe.Snapshots.get
    def guarded(self, name, expected=None):
        assert not name.startswith("data/evaluation/meetings-c3-validation-synthetic/")
        assert name != world.plan["phases"]["validation"]["input"]["file"]
        return original(self, name, expected)
    monkeypatch.setattr(probe.Snapshots, "get", guarded)
    original_result = copy.deepcopy(result)
    result["summary"]["full_correct"] = 7
    write(world.root / files["result"], result)
    with pytest.raises(ValueError, match="selection_replay"):
        probe.check(world.plan_name, "validation", files["result"], root=world.root)
    write(world.root / files["result"], original_result)
    votes = json.loads((world.root / files["judgments"]).read_bytes())
    votes["judgments"][0]["reason"] += " Changed after selection."
    write(world.root / files["judgments"], votes)
    with pytest.raises(ValueError, match="lock_changed"):
        probe.check(world.plan_name, "validation", files["result"], root=world.root)


def test_partial_operational_report_is_never_audit_eligible(world):
    world.transport.fail_at = 6
    report = run_phase(world)
    assert report["status"] == "failed"
    report["status"] = "completed"
    write(world.root / world.plan["phases"]["calibration"]["output_dir"] / "report.json", report)
    with pytest.raises(ValueError, match="report_incomplete"):
        audit.prepare(world.plan_name, "calibration", root=world.root)


@pytest.fixture
def lock_fixture(tmp_path):
    from tests.test_meeting_requirements_review import attestation, sample_and_judgment
    directory = ".local/meetings-c3-audit-calibration-v1"
    files = audit.paths(directory, tmp_path)
    samples, votes = [], []
    for i in range(6):
        sample, judgment = sample_and_judgment()
        sample_id = f"sample-{i + 1:03d}"
        sample["sample_id"] = sample["oracle"]["id"] = judgment["sample_id"] = sample_id
        sample.setdefault("response_language", "en")
        sample.setdefault("question", "Synthetic question.")
        samples.append(sample); votes.append(judgment)
    pack = {"schema_version": 1, "purpose": "final_answer_review", "samples": samples}
    exposure_name = ".local/meetings-c3-review-metadata-v1/calibration/attestation.json"
    exposure = attestation()
    exposure_sha = write(tmp_path / exposure_name, exposure)
    receipt = {"schema_version": 1, "candidate": probe.ANSWER_POLICY, "phase": "calibration",
        "output_dir": directory, "excluded_roles": sorted(probe.EXCLUDED_ROLES), "reviewer_id": "judge",
        "attestation": {"file": exposure_name, "sha256": exposure_sha}, "created_at": "2026-10-14T00:01:00+00:00",
        "pack_sha256": write(tmp_path / files["pack"], pack), "plan_sha256": "a" * 64}
    votes = {"schema_version": 1, "reviewer_id": "judge", "mapping_not_seen": True,
        "independent_of_authors_and_designers": True, "human_review_count": 0, "judgments": votes}
    write(tmp_path / files["receipt"], receipt)
    write(tmp_path / files["judgments"], votes)
    return directory, files, receipt, pack, votes


@pytest.mark.parametrize("mutation", [
    lambda v: v["judgments"].pop(),
    lambda v: v["judgments"].append(v["judgments"][0]),
    lambda v: v["judgments"][0].update(sample_id="other"),
    lambda v: v["judgments"][0]["claims"][0]["citations"].pop(),
    lambda v: v["judgments"][0]["required_facts"].pop(),
    lambda v: v["judgments"][0].update(full_correct=False),
    lambda v: v.update(mapping_not_seen=1),
    lambda v: v.update(independent_of_authors_and_designers=False),
    lambda v: v.update(human_review_count=False),
])
def test_incomplete_or_inconsistent_votes_never_lock(lock_fixture, tmp_path, mutation):
    directory, files, _, _, votes = lock_fixture
    mutation(votes)
    write(tmp_path / files["judgments"], votes)
    with pytest.raises(ValueError):
        audit.lock_answers(directory, root=tmp_path)
    assert not (tmp_path / files["lock"]).exists()


@pytest.mark.parametrize("field,value", [("answer_scores_final", 1), ("plan_disclosed_before_lock", 0),
    ("human_review_count", False), ("judgments_sha256", "b" * 64)])
def test_lock_tamper_and_boolean_coercion_are_rejected(lock_fixture, tmp_path, field, value):
    directory, files, _, _, _ = lock_fixture
    lock = audit.lock_answers(directory, root=tmp_path)
    lock[field] = value
    write(tmp_path / files["lock"], lock)
    with pytest.raises(ValueError, match="lock_changed"):
        audit.locked(directory, root=tmp_path)


def test_phase_spoof_rejected_before_answer_pack(lock_fixture, tmp_path, monkeypatch):
    _, files, receipt, _, _ = lock_fixture
    directory = ".local/meetings-c3-audit-validation-v1"
    val_files = audit.paths(directory, tmp_path)
    receipt["output_dir"] = directory
    write(tmp_path / val_files["receipt"], receipt)
    original = probe.Snapshots.get
    seen = []
    def record(self, name, expected=None):
        seen.append(name)
        return original(self, name, expected)
    monkeypatch.setattr(probe.Snapshots, "get", record)
    with pytest.raises(ValueError, match="audit_receipt"):
        audit.lock_answers(directory, root=tmp_path)
    assert seen == [val_files["receipt"]] and files["pack"] not in seen


def test_plan_disclosure_file_before_lock_consumes_audit(lock_fixture, tmp_path):
    directory, files, _, _, _ = lock_fixture
    write(tmp_path / files["plan_pack"], {"forbidden_prelock_disclosure": True})
    with pytest.raises(FileExistsError):
        audit.lock_answers(directory, root=tmp_path)


def test_abstention_zero_rate_denominators_stay_null():
    row = {"full_correct": True, "quality": {"completeness": True}, "citations": 0, "exact_citations": 0,
        "facts": 0, "supported_facts": 0, "relevant_citation_links": 0, "source_unique_codepoints": 80,
        "citation_unique_codepoints": 0, "support_unique_codepoints": 0, "citation_codepoints": 0,
        "citation_duplicate_codepoints": 0}
    summary = audit.aggregate([row])
    assert summary["fact_support_rate"] is summary["citation_exact_rate"] is summary["citation_precision"] is None
    assert summary["quote_to_support_width"] is None and summary["source_quoted_fraction"] == 0


@pytest.mark.parametrize("field,value", [("plan_seen", True), ("raw_trace_seen", True),
    ("registered_at", "2099-01-01T00:00:00+00:00")])
def test_actual_exposure_and_late_attestation_block_lock(lock_fixture, tmp_path, field, value):
    directory, files, receipt, _, _ = lock_fixture
    target = tmp_path / receipt["attestation"]["file"]
    exposure = json.loads(target.read_bytes())
    exposure[field] = value
    receipt["attestation"]["sha256"] = write(target, exposure)
    write(tmp_path / files["receipt"], receipt)
    with pytest.raises(ValueError):
        audit.lock_answers(directory, root=tmp_path)
    assert not (tmp_path / files["lock"]).exists()
