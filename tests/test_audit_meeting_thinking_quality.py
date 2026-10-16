"""Anonymous C4 audit over synthetic original sources and mock HTTP only."""
import json

import pytest

from scripts import audit_meeting_thinking_quality as audit
from scripts import prepare_meeting_thinking_inputs as prep
from scripts import probe_meeting_thinking_quality as probe
from tests.test_meeting_thinking_review import judgment
from tests.test_prepare_meeting_thinking_inputs import write
from tests.test_probe_meeting_thinking_quality import material as material_fixture
from tests.test_probe_meeting_thinking_quality import run
from tests.test_probe_meeting_thinking_quality import world as world_fixture

material = material_fixture
world = world_fixture


def submit(world, phase="calibration", *, correct=True):
    _, files = audit.names(phase, world.root)
    pack = json.loads((world.root / files["pack"]).read_bytes())
    votes = {"schema_version": 1, "reviewer_id": "judge-" + phase, "mapping_not_seen": True,
        "independent_of_authors_and_designers": True, "human_review_count": 0,
        "judgments": [judgment(sample, full=correct or i > 0) for i, sample in enumerate(pack["samples"])]}
    return write(world.root / files["judgments"], votes)


def test_answer_only_lock_full_calibration_gate_then_validation_once(world, monkeypatch):
    assert run(world)["status"] == "completed"
    audit.prepare("calibration", root=world.root, git=world.git)
    _, files = audit.names("calibration", world.root)
    pack = json.loads((world.root / files["pack"]).read_bytes())
    encoded = prep.encoded(pack)
    assert all(case["id"].encode() not in encoded for case in world.cal.draft["cases"])
    assert all(set(sample) == {"sample_id", "question", "response_language", "contexts", "oracle", "answer"} for sample in pack["samples"])
    assert all(sample["oracle"]["id"] == sample["sample_id"] and sample["oracle"]["question_author"] == "author-A" for sample in pack["samples"])
    assert b"reasoning_content" not in encoded and b"native_timings" not in encoded
    with pytest.raises(FileNotFoundError):
        audit.finalize("calibration", root=world.root, git=world.git)
    digest = submit(world)
    original = prep.Snapshots.get
    def lock_spy(self, name, expected=None):
        assert name != files["mapping"] and name != world.plan["phases"]["calibration"]["output_dir"] + "/report.json"
        return original(self, name, expected)
    with monkeypatch.context() as patch:
        patch.setattr(prep.Snapshots, "get", lock_spy)
        audit.lock("calibration", digest, root=world.root, git=world.git)
    result = audit.finalize("calibration", root=world.root, git=world.git)
    assert result["selected"] is True and result["complete_correct"] == 6 and not result["automatic_service_adoption"]
    assert audit.verify_calibration_gate(world.plan, root=world.root, git=world.git) == result
    assert run(world, "validation")["status"] == "completed"
    audit.prepare("validation", root=world.root, git=world.git)
    _, val_files = audit.names("validation", world.root)
    digest = submit(world, "validation")
    def val_lock_spy(self, name, expected=None):
        assert name != val_files["mapping"] and name != world.plan["phases"]["validation"]["output_dir"] + "/report.json"
        return original(self, name, expected)
    with monkeypatch.context() as patch:
        patch.setattr(prep.Snapshots, "get", val_lock_spy)
        audit.lock("validation", digest, root=world.root, git=world.git)
    result = audit.finalize("validation", root=world.root, git=world.git)
    assert result["validation_passed"] and result["denominator"] == 8 and result["complete_correct"] == 8
    assert result["selected"] is False and result["validation_eligible"] is False
    assert world.observed.posts == 14


def test_five_of_six_cannot_become_validation_gate_even_with_forged_true(world, monkeypatch):
    assert run(world)["status"] == "completed"
    audit.prepare("calibration", root=world.root, git=world.git)
    audit.lock("calibration", submit(world, correct=False), root=world.root, git=world.git)
    result = audit.finalize("calibration", root=world.root, git=world.git)
    assert result["complete_correct"] == 5 and result["selected"] is False
    _, files = audit.names("calibration", world.root)
    write(world.root / files["result"], result | {"selected": True, "validation_eligible": True})
    original = prep.Snapshots.get
    forbidden = {world.plan["phases"]["validation"][r]["file"] for r in probe.MATERIAL | {"input"}}
    def spy(self, name, expected=None):
        assert name not in forbidden, "validation semantic body opened"
        return original(self, name, expected)
    monkeypatch.setattr(prep.Snapshots, "get", spy)
    for operation in (lambda: probe.check("validation", root=world.root, git=world.git),
                      lambda: audit.prepare("validation", root=world.root, git=world.git),
                      lambda: audit.locked("validation", root=world.root, git=world.git)):
        with pytest.raises(ValueError, match="gate_failed"):
            operation()


def test_changed_judgment_mapping_or_original_raw_never_redefines_locked_score(world):
    assert run(world)["status"] == "completed"
    audit.prepare("calibration", root=world.root, git=world.git)
    audit.lock("calibration", submit(world), root=world.root, git=world.git)
    _, files = audit.names("calibration", world.root)
    raw_report = world.plan["phases"]["calibration"]["output_dir"] + "/report.json"
    for name in (files["judgments"], files["mapping"], raw_report):
        target = world.root / name
        original = target.read_bytes()
        content = json.loads(original)
        if name == files["judgments"]:
            content["judgments"].reverse()
        elif name == files["mapping"]:
            content["samples"].reverse()
        else:
            content["calls"][0]["result"]["answer"]["claims"][0]["text"] = "forged"
        write(target, content)
        with pytest.raises(ValueError):
            audit.finalize("calibration", root=world.root, git=world.git)
        write(target, original)


def test_partial_native_phase_cannot_prepare_scoring_pack(world):
    world.observed.fail_at = 1
    assert run(world)["status"] == "failed_closed"
    with pytest.raises(ValueError, match="report_not_complete"):
        audit.prepare("calibration", root=world.root, git=world.git)
    assert not (world.root / world.plan["audit"]["calibration"]["output_dir"]).exists()


def test_anonymous_fact_and_author_ids_are_fresh_but_source_coordinates_preserved():
    from doctrail.meeting_thinking_review import C4Oracle
    from tests.test_meeting_thinking_review import corpus
    draft, oracles = corpus()
    case, oracle = draft["cases"][0], C4Oracle.model_validate(oracles["cases"][0])
    answer = {"status": "abstained", "reason": "insufficient_evidence", "claims": []}
    sample = audit.anonymous(case, oracle, answer, "sample-001")
    assert sample["oracle"]["required_facts"][0]["id"] == "fact-001"
    assert sample["contexts"] == case["payload"]["contexts"]
    assert case["id"] not in prep.encoded(sample).decode()


def test_audit_names_rejects_arbitrary_paths_before_io(tmp_path):
    with pytest.raises(ValueError, match="audit_phase"):
        audit.names("../../validation/raw", tmp_path)
