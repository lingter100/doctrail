"""Synthetic audit packaging checks; no experiment data or model is read."""
import json

import pytest

from doctrail.inference import WorkerError
from scripts import prepare_meeting_review_audit as audit
from scripts.probe_meeting_answer_review import read_json


@pytest.fixture
def source(tmp_path):
    text = "The synthetic label is violet.\n"
    cases, oracles, results, stages = [], [], [], []
    for n in range(8):
        identity = f"synthetic-{n}"
        context = {"document_id": identity, "revision": 1, "chunk_id": identity,
                   "title": "Synthetic", "meeting_date": None, "page": None,
                   "start_offset": 0, "end_offset": len(text), "text": text}
        cases.append({"id": identity, "payload": {"schema_version": 1,
                     "query": "What colour is the label?", "contexts": [context]}})
        oracles.append({"id": identity, "answerable": True, "facts": ["violet"]})
        answer = {"status": "answered", "reason": None, "claims": [{"text": "The label is violet.",
                   "citations": [{"chunk_id": identity, "quote": text,
                                  "start_offset": 0, "end_offset": len(text)}]}]}
        results.append({"id": identity, "structural_status": "passed", "result": {
            **answer, "model": "must-not-reach-reviewer", "telemetry": {"stage": "V0"}}})
        stages.append({"case_id": identity, "stage": "D0", "output": {"text": json.dumps({
            "status": "answered", "claims": [{"evidence_ids": [0], "text": "The label is violet."}]})}})
    files = {name: tmp_path / (name + ".json") for name in ("report", "cases", "oracle")}
    audit.write_json(files["cases"], {"cases": cases})
    audit.write_json(files["oracle"], {"cases": oracles})
    report = {"candidate": audit.CANDIDATE, "phase": "calibration",
              "status": "completed_not_semantically_verified", "sources_unchanged": True,
              "work_finalized": True, "plan_sha256": "b" * 64, "results": results,
              "stages": stages, "phase_inputs": {"calibration": {
                  "input_sha256": audit.sha(files["cases"]), "oracle_sha256": audit.sha(files["oracle"]),
                  "case_ids": [c["id"] for c in cases]}}}
    audit.write_json(files["report"], report)
    seed = tmp_path / "seed.txt"
    seed.write_bytes(b"synthetic-only-shuffle-seed-0000000")
    return files, seed, tmp_path / "pack", report


def run(source):
    files, seed, output, _ = source
    return audit.prepare(files["report"], files["cases"], files["oracle"], seed, output, audit.sha(seed))


def test_pairs_preserve_exact_evidence_without_stage_or_runtime_labels(source):
    receipt = run(source)
    _, _, output, _ = source
    pack = read_json(output / "review-input.json")
    mapping = read_json(output / "mapping.json")["mappings"]
    assert receipt["samples"] == 16 and receipt["model_calls"] == 0
    assert {(m["case_id"], m["role"]) for m in mapping} == {
        (f"synthetic-{n}", role) for n in range(8) for role in ("D0", "C1")}
    for sample in pack["samples"]:
        assert "role" not in sample and "telemetry" not in sample["answer"]
        assert "model" not in sample["answer"]
        assert sample["answer"]["claims"][0]["citations"][0]["quote"] == sample["contexts"][0]["text"]
    assert "must-not-reach-reviewer" not in (output / "review-input.json").read_text()
    with pytest.raises(ValueError, match="output_exists"):
        run(source)


def test_rejection_is_an_answer_failure_not_an_abstention(source):
    files, _, output, report = source
    report["results"][0] = {"id": "synthetic-0", "structural_status": "failed",
                            "error": "generation_semantic_rejected"}
    audit.write_json(files["report"], report)
    run(source)
    pack = read_json(output / "review-input.json")
    errors = [s for s in pack["samples"] if s["answer"]["status"] == "error"]
    assert len(errors) == 1 and "reason" not in errors[0]["answer"]


def test_receipt_and_evidence_bind_same_snapshot_during_concurrent_edits(source, monkeypatch):
    files, _, output, _ = source
    initial_hashes = {name: audit.sha(path) for name, path in files.items()}
    original = audit.grounded_answer_spans

    def change_inputs_after_snapshot(*args, **kwargs):
        for path in files.values():
            path.write_bytes(b'{}')
        return original(*args, **kwargs)

    monkeypatch.setattr(audit, "grounded_answer_spans", change_inputs_after_snapshot)
    receipt = run(source)
    assert receipt["report_sha256"] == initial_hashes["report"]
    assert receipt["input_sha256"] == initial_hashes["cases"]
    assert receipt["oracle_sha256"] == initial_hashes["oracle"]
    pack = read_json(output / "review-input.json")
    for sample in pack["samples"]:
        assert sample["contexts"][0]["text"] == "The synthetic label is violet.\n"
        assert sample["oracle"]["facts"] == ["violet"]


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}'])
def test_snapshot_rejects_ambiguous_json(tmp_path, raw):
    path = tmp_path / "ambiguous.json"
    path.write_bytes(raw)
    with pytest.raises(WorkerError):
        audit.read_snapshot(path)


def test_snapshot_enforces_byte_limit(tmp_path):
    path = tmp_path / "oversized.json"
    path.write_bytes(b" " * (16 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="json_file_limit"):
        audit.read_snapshot(path)


@pytest.mark.parametrize("kind", ["source", "oracle", "seed", "duplicate_draft", "partial", "order"])
def test_changed_or_incomplete_inputs_cannot_create_a_pack(source, kind):
    files, seed, output, report = source
    if kind in {"source", "oracle"}:
        files["cases" if kind == "source" else "oracle"].write_bytes(b"{}")
        error_pattern = "hash_mismatch"
    elif kind == "seed":
        with pytest.raises(ValueError, match="seed_mismatch"):
            audit.prepare(files["report"], files["cases"], files["oracle"], seed, output, "a" * 64)
        assert not output.exists()
        return
    else:
        if kind == "duplicate_draft":
            report["stages"].append(report["stages"][0])
            error_pattern = "duplicate"
        elif kind == "partial":
            report["status"] = "failed"
            error_pattern = "not_complete"
        else:
            report["results"].reverse()
            error_pattern = "case_set"
        audit.write_json(files["report"], report)
    with pytest.raises(ValueError, match=error_pattern):
        run(source)
    assert not output.exists()
