"""Entirely synthetic partial evidence; no real questions, model or tokenizer."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from test_audit_meeting_budget_comparison import fixture as source_fixture
from test_audit_meeting_budget_comparison import judgments

from scripts import audit_meeting_budget_partial as partial

full_fixture = source_fixture


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(partial.audit.encoded(value))


def read(path):
    return partial.audit.parse(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def evidence(full_fixture, monkeypatch):
    f = full_fixture
    seed_path = f.root / f.plan["audit"]["calibration"]["seed_file"]
    seed_path.write_bytes(b"newly synthetic unused seed bytes".ljust(64, b"!"))
    f.plan["audit"]["calibration"]["seed_sha256"] = sha(seed_path)
    write(f.plan_path, f.plan)
    f.report["plan_sha256"] = sha(f.plan_path)

    # The imported fixture is newly synthetic full calibration, never actual data.
    f.report["results"] = f.report["results"][:15]
    f.report["calls"] = f.report["calls"][:15]
    f.report.update(status="failed", failure=partial.ERROR, resources_passed=False,
                    unexecuted=[f.report["planned_dispatches"][-1]])
    row, call = f.report["results"][-1], f.report["calls"][-1]
    row.pop("response")
    row.update(structural_status="failed", error=partial.ERROR)
    row["worker_telemetry"]["error_code"] = partial.ERROR
    call["raw_response"]["content"] = json.dumps({"status": "answered", "claims": [
        {"text": "합성 표식은 민트색이다.", "evidence_ids": [0]}]}, ensure_ascii=False)
    write(f.report_path, f.report)
    monkeypatch.setattr(partial, "PLAN_FILE", f.plan_path.relative_to(f.root).as_posix())
    monkeypatch.setattr(partial, "PLAN_SHA256", sha(f.plan_path))
    monkeypatch.setattr(partial, "REPORT_FILE", f.report_path.relative_to(f.root).as_posix())
    monkeypatch.setattr(partial, "REPORT_SHA256", sha(f.report_path))
    monkeypatch.setattr(partial, "REPORT_BYTES", f.report_path.stat().st_size)
    monkeypatch.setattr(partial, "CASE_IDS", f.plan["phases"]["calibration"]["case_ids"])
    monkeypatch.setattr(partial, "REVIEWER", "judge-cal")
    monkeypatch.setattr(partial, "DESIGN_FILE", "synthetic-design.md")
    (f.root / "synthetic-design.md").write_bytes(b"Synthetic metadata-only design")
    monkeypatch.setattr(partial, "DESIGN_SHA256", sha(f.root / "synthetic-design.md"))
    for file in partial.FILES:
        p = f.root / file
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"# synthetic diagnostic source")
    f.output = f.root / partial.OUTPUT
    return f


def seal_report(f, monkeypatch):
    """Bind a changed fake report to exercise replay beyond the outer SHA guard."""
    write(f.report_path, f.report)
    monkeypatch.setattr(partial, "REPORT_SHA256", sha(f.report_path))
    monkeypatch.setattr(partial, "REPORT_BYTES", f.report_path.stat().st_size)


def prepare_and_judge(f):
    receipt = partial.prepare(root=f.root)
    review = judgments(read(f.output / "review-input.json"))
    write(f.output / "judgments.json", review)
    return receipt, review


def test_complete_diagnostic_is_ineligible_with_separate_denominators(evidence):
    f = evidence
    receipt, _ = prepare_and_judge(f)
    assert receipt["samples"] == 14 and len(receipt["row_replay"]) == 14
    failure = read(f.output / "failure-replay.json")
    assert failure["same_guard_reproduced"] and not failure["semantic_scoring_performed"]
    assert "content" not in failure and "answer" not in failure
    locked = partial.lock(root=f.root, reviewer_model="gpt-6-astra", reviewer_effort="xhigh")
    assert not locked["mapping_opened_by_lock"]
    result = partial.finalize(root=f.root)
    assert result["semantic_full_correct"] == {"numerator": 13, "denominator": 14}
    assert result["arms"] == {"L0": {"numerator": 6, "denominator": 7}, "C2": {"numerator": 7, "denominator": 7}}
    assert result["posthoc_improvements"] == 1 and result["posthoc_regressions"] == 0
    assert result["execution_counts"] == partial.COUNTS
    for item in (receipt, failure, locked, result):
        partial.check_flags(item)
        assert not item["selected"] and not item["validation_eligible"]
    assert "passed" not in result and not (f.output / "selection.json").exists()
    assert any(r["citation_exact_rate"] is None for r in result["rows"])
    assert all(r["case_id"] != partial.CASE_IDS[-1] for r in result["rows"])
    assert len(list(f.output.iterdir())) == 7


def test_pack_is_anonymous_and_preserves_all_contexts(evidence):
    f = evidence
    partial.prepare(root=f.root)
    pack = read(f.output / "review-input.json")
    assert set(pack) == {"schema_version", "samples", "instructions", "masking_limits"}
    for sample in pack["samples"]:
        assert set(sample) == {"sample_id", "question", "contexts", "oracle", "answer"}
        assert set(sample["answer"]) == {"status", "reason", "claims"}
        assert sample["contexts"] == f.inputs["cases"][0]["payload"]["contexts"]
        assert sample["oracle"]["id"] == sample["sample_id"]
    expected = partial.closed_evidence(f.root)
    assert partial.audit.hashed(expected[0]) == sha(f.output / "review-input.json")
    assert partial.audit.hashed(expected[1]) == sha(f.output / "mapping.json")


def test_even_fourteen_correct_cannot_restore_full_gate(evidence, monkeypatch):
    f = evidence
    row, call = f.report["results"][0], f.report["calls"][0]
    row["response"]["claims"][0]["text"] = "합성 표식은 민트색이다."
    value = json.loads(call["raw_response"]["content"])
    value["claims"][0]["text"] = row["response"]["claims"][0]["text"]
    call["raw_response"]["content"] = json.dumps(value)
    seal_report(f, monkeypatch)
    prepare_and_judge(f)
    partial.lock(root=f.root, reviewer_model="gpt-6-astra", reviewer_effort="xhigh")
    result = partial.finalize(root=f.root)
    assert result["semantic_full_correct"] == {"numerator": 14, "denominator": 14}
    assert result["original_full_gate"] == "failed" and not result["eligible_for_selection"]
    assert not result["validation_eligible"]


@pytest.mark.parametrize("kind", ["missing", "extra", "reordered", "duplicate", "sequence", "success_flag", "unexecuted", "failure", "cleanup", "log", "free", "bool_count"])
def test_partial_execution_contract_rejects_tampering(evidence, monkeypatch, kind):
    f = evidence
    if kind == "missing": f.report["results"].pop(0)
    elif kind == "extra": f.report["calls"].append(copy.deepcopy(f.report["calls"][0]))
    elif kind == "reordered": f.report["results"][0:2] = reversed(f.report["results"][0:2])
    elif kind == "duplicate": f.report["results"][1] = copy.deepcopy(f.report["results"][0])
    elif kind == "sequence": f.report["calls"][0]["sequence"] = 1
    elif kind == "success_flag": f.report["resources_passed"] = True
    elif kind == "unexecuted": f.report["unexecuted"] = []
    elif kind == "failure": f.report["failure"] = "other_error"
    elif kind == "cleanup": f.report["owned_cleanup_ms"] = 5001
    elif kind == "log": f.report["native_log_bytes"] = 1
    elif kind == "free": f.report["paid_calls"] = 1
    else: f.report["paid_calls"] = False
    seal_report(f, monkeypatch)
    with pytest.raises(ValueError): partial.prepare(root=f.root)
    assert not f.output.exists()


@pytest.mark.parametrize("kind", ["native", "mapper", "payload", "prompt", "official", "sampling", "time", "error_not_reproduced", "different_error", "failed_native", "failed_transport"])
def test_native_mapper_and_failure_replay_reject_inconsistency(evidence, monkeypatch, kind):
    f = evidence
    row, call = f.report["results"][0], f.report["calls"][0]
    if kind == "native": call["raw_response"]["tokens_predicted"] = 999
    elif kind == "mapper": row["response"]["claims"][0]["text"] = "Changed answer"
    elif kind == "payload": row["payload_sha256"] = "f" * 64
    elif kind == "prompt": row["prompt_sha256"] = "f" * 64
    elif kind == "official": row["official_input_tokens"] += 1
    elif kind == "sampling": call["raw_response"]["generation_settings"]["temperature"] = 1
    elif kind == "time": row["elapsed_ms"] = 90000
    elif kind == "error_not_reproduced":
        f.report["calls"][-1]["raw_response"]["content"] = json.dumps({"status": "abstained", "claims": []})
    elif kind == "different_error": f.report["calls"][-1]["raw_response"]["content"] = "not-json"
    elif kind == "failed_native": f.report["calls"][-1]["raw_response"]["tokens_evaluated"] = 1
    else: f.report["results"][-1]["worker_telemetry"]["error_code"] = "different_error"
    seal_report(f, monkeypatch)
    with pytest.raises(ValueError): partial.prepare(root=f.root)
    assert not f.output.exists()


@pytest.mark.parametrize("artifact", ["report", "plan", "design"])
def test_closed_artifact_hash_is_required_before_processing(evidence, artifact):
    f = evidence
    target = {"report": f.report_path, "plan": f.plan_path, "design": f.root / partial.DESIGN_FILE}[artifact]
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ValueError, match="binding_changed"):
        partial.prepare(root=f.root)
    assert not f.output.exists()


def test_lock_reads_no_mapping_or_original_semantics(evidence, monkeypatch):
    f = evidence
    prepare_and_judge(f)
    original = partial.snapshot
    seen = []
    def spy(path):
        name = Path(path).name
        assert name in {"review-input.json", "receipt.json", "judgments.json", "audit_meeting_budget_partial.py", "test_audit_meeting_budget_partial.py"}
        seen.append(name)
        return original(path)
    monkeypatch.setattr(partial, "snapshot", spy)
    partial.lock(root=f.root, reviewer_model="gpt-6-astra", reviewer_effort="xhigh")
    assert "judgments.json" in seen


def test_missing_lock_never_opens_mapping_or_original_evidence(evidence, monkeypatch):
    f = evidence
    prepare_and_judge(f)
    original = partial.snapshot
    def spy(path):
        assert Path(path).name == "judgments-lock.json"
        return original(path)
    monkeypatch.setattr(partial, "snapshot", spy)
    with pytest.raises(FileNotFoundError): partial.finalize(root=f.root)


@pytest.mark.parametrize("kind", ["partial", "role", "exposed", "claim_missing", "literal_bool"])
def test_invalid_judgments_cannot_lock(evidence, kind):
    f = evidence
    receipt, review = prepare_and_judge(f)
    if kind == "partial": review["judgments"].pop()
    elif kind == "role": review["reviewer_id"] = "/root"
    elif kind == "exposed":
        receipt["excluded_reviewer_ids"].append("judge-cal")
        write(f.output / "receipt.json", receipt)
    elif kind == "claim_missing":
        next(r for r in review["judgments"] if r["claims"])["claims"].pop()
    else: review["mapping_not_seen"] = 1
    write(f.output / "judgments.json", review)
    with pytest.raises(ValueError): partial.lock(root=f.root, reviewer_model="gpt-6-astra", reviewer_effort="xhigh")
    assert not (f.output / "judgments-lock.json").exists()


@pytest.mark.parametrize("name", ["judgments", "review-input", "receipt", "mapping", "failure-replay"])
def test_changed_artifact_after_lock_prevents_finalization(evidence, name):
    f = evidence
    prepare_and_judge(f)
    partial.lock(root=f.root, reviewer_model="gpt-6-astra", reviewer_effort="xhigh")
    target = f.output / (name + ".json")
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ValueError): partial.finalize(root=f.root)
    assert not (f.output / "diagnostic-summary.json").exists()


@pytest.mark.parametrize("field,value", [("selected", True), ("eligible_for_selection", True),
    ("validation_eligible", True), ("original_full_gate", "passed")])
def test_lock_cannot_claim_selection_or_validation_permission(evidence, field, value):
    f = evidence
    prepare_and_judge(f)
    locked = partial.lock(root=f.root, reviewer_model="gpt-6-astra", reviewer_effort="xhigh")
    locked[field] = value
    write(f.output / "judgments-lock.json", locked)
    with pytest.raises(ValueError, match="ineligible_flags"):
        partial.finalize(root=f.root)


def test_resigned_mapping_and_receipt_still_fail_original_replay(evidence):
    f = evidence
    receipt, _ = prepare_and_judge(f)
    mapping = read(f.output / "mapping.json")
    mapping["mappings"][0]["arm"] = "L0" if mapping["mappings"][0]["arm"] == "C2" else "C2"
    write(f.output / "mapping.json", mapping)
    receipt["mapping_sha256"] = sha(f.output / "mapping.json")
    write(f.output / "receipt.json", receipt)
    partial.lock(root=f.root, reviewer_model="gpt-6-astra", reviewer_effort="xhigh")
    with pytest.raises(ValueError, match="artifact_replay"):
        partial.finalize(root=f.root)


def test_outputs_are_exclusive_and_cannot_reopen_original_gate(evidence):
    f = evidence
    prepare_and_judge(f)
    with pytest.raises(FileExistsError): partial.prepare(root=f.root)
    partial.lock(root=f.root, reviewer_model="gpt-6-astra", reviewer_effort="xhigh")
    with pytest.raises(FileExistsError): partial.lock(root=f.root, reviewer_model="gpt-6-astra", reviewer_effort="xhigh")
    partial.finalize(root=f.root)
    with pytest.raises(FileExistsError): partial.finalize(root=f.root)
    with pytest.raises(ValueError, match="selection_path"):
        partial.audit.verify_validation_gate(f.plan, f.root, f.output / "diagnostic-summary.json", plan_sha256=partial.PLAN_SHA256)


@pytest.mark.parametrize("model,effort", [(None, None), ("gpt-6-astra", "high"), ("other-model", "xhigh")])
def test_judge_runtime_must_be_explicit_registered_settings(evidence, model, effort):
    f = evidence
    prepare_and_judge(f)
    with pytest.raises(ValueError, match="reviewer_runtime_registration"):
        partial.lock(root=f.root, reviewer_model=model, reviewer_effort=effort)
    assert not (f.output / "judgments-lock.json").exists()


def test_existing_original_audit_disallows_unused_seed_claim(evidence):
    f = evidence
    (f.root / f.plan["audit"]["calibration"]["output_dir"]).mkdir()
    with pytest.raises(ValueError, match="original_audit_already_exists"):
        partial.prepare(root=f.root)
    assert not f.output.exists()


def test_helper_changed_after_prepare_prevents_lock(evidence):
    f = evidence
    prepare_and_judge(f)
    (f.root / min(partial.FILES)).write_bytes(b"changed")
    with pytest.raises(ValueError, match="lock_binding"):
        partial.lock(root=f.root, reviewer_model="gpt-6-astra", reviewer_effort="xhigh")


def test_snapshot_is_bounded_before_json_parse(tmp_path):
    oversized = tmp_path / "oversized.json"
    with oversized.open("wb") as stream:
        stream.seek(16 * 1024 * 1024)
        stream.write(b"x")
    with pytest.raises(ValueError, match="file_limit"):
        partial.capture("oversized.json", tmp_path)


def test_no_validation_bytes_are_opened(evidence, monkeypatch):
    f = evidence
    original = partial.snapshot
    def spy(path):
        assert "sealed-" not in str(path) and "val-preparation" not in str(path)
        return original(path)
    monkeypatch.setattr(partial, "snapshot", spy)
    partial.prepare(root=f.root)


def test_path_escape_and_symlink_rejected(tmp_path):
    with pytest.raises(ValueError): partial.path("../escape", tmp_path)
    target = tmp_path / "target"
    target.write_bytes(b"data")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    with pytest.raises(ValueError, match="linked_path"):
        partial.path("alias", tmp_path)
