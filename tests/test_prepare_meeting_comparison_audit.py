"""Entirely synthetic audit evidence; no model, download or real question-pool reads."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from doctrail.meeting_answer_blocks import (
    answer_messages_blocks,
    build_block_catalog,
    grounded_answer_blocks,
)
from doctrail.meeting_answer_spans import (
    answer_messages_spans,
    build_span_catalog,
    grounded_answer_spans,
    span_answer_grammar,
)
from doctrail.meeting_answer_v2 import response_language
from doctrail.meeting_contract import AnswerRequest
from doctrail.meeting_gguf import GREEDY
from doctrail.meeting_qwen35 import PREAMBLE_SHA256
from scripts import prepare_meeting_comparison_audit as audit
from scripts import probe_meeting_blocks_comparison as runner


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audit.encoded(value))


def read(path):
    return audit.parse(path.read_bytes())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    root = tmp_path
    monkeypatch.setattr(runner, "FILES", {"synthetic.py"})
    monkeypatch.setattr(runner, "RESOURCE_REPORT_FILE", "resource.json")
    (root / "synthetic.py").write_text("# synthetic test source\n")
    bound = {"synthetic.py": digest(root / "synthetic.py")}
    metadata = {"repo_id": "synthetic", "revision": "synthetic", "original_revision": "synthetic",
                "artifact": {"sha256": "c" * 64}, "runtime": {"backend": "synthetic", "tag": "synthetic",
                "commit": "synthetic", "observed_build": "synthetic", "context_tokens": 6144}}
    resource = {"readiness_passed": True, "sources_unchanged": True, "processes_stopped": True,
                "metadata_recovery": True, "native_log_bytes": 0, "calls": [{}, {}],
                "bound_files": bound, "model_runtime": metadata}
    write(root / "resource.json", resource)
    monkeypatch.setattr(runner, "RESOURCE_REPORT_SHA256", digest(root / "resource.json"))
    contexts = []
    for n, text in enumerate(("The synthetic marker is mint.\n", "The synthetic code is fourteen.\n")):
        contexts.append({"document_id": f"doc-{n}", "revision": 1, "chunk_id": f"chunk-{n}",
            "title": "Synthetic test", "meeting_date": None, "page": None,
            "start_offset": 10, "end_offset": 10 + len(text), "text": text})
    cases, oracles = [], []
    for i in range(8):
        ko = i % 4 < 2
        question = "합성 표식과 코드는 무엇인가?" if ko else "What are the synthetic marker and code?"
        if i % 4 == 3:
            question += " Also state their deadline."
        identity = f"synthetic-{i}"
        cases.append({"id": identity, "payload": {"schema_version": 1, "query": question,
                    "contexts": copy.deepcopy(contexts)}, "official_input_tokens": {"L0": 200, "C2": 201}})
        facts = [{"id": f"f-{n}", "text": c["text"].strip(), "evidence_alternatives": [[{
            "chunk_id": c["chunk_id"], "quote": c["text"], "start_offset": c["start_offset"],
            "end_offset": c["end_offset"]}]]} for n, c in enumerate(contexts)]
        if i % 4 == 3:
            facts.append({"id": "f-missing", "text": "The required deadline.", "evidence_alternatives": []})
        oracles.append({"id": identity, "family_id": "C2-F01" if i < 4 else "C2-F02",
            "provenance": "public" if i < 4 else "synthetic", "language": "ko" if ko else "en",
            "expected_status": "abstained" if i % 4 == 3 else "answered", "required_facts": facts,
            "unanswerable_reason": "No deadline in source." if i % 4 == 3 else None,
            "forbidden_inferences": ["Do not invent a deadline."], "limitations": ["Synthetic test fixture."],
            "question_author": "test-author", "oracle_author": "test-author",
            "independent_prereviewer": "test-prereviewer", "human_review_count": 0})
    inputs = {"schema_version": 1, "phase": "calibration", "cases": cases}
    oracle = {"schema_version": 1, "phase": "calibration", "cases": oracles}
    write(root / "input.json", inputs)
    write(root / "oracle.json", oracle)
    seed = b"synthetic fixed seed for tests!!!" * 2
    (root / ".local").mkdir()
    (root / ".local/cal.seed").write_bytes(seed)
    plan = {"schema_version": 1, "candidate": runner.CANDIDATE, "limits": copy.deepcopy(runner.LIMITS),
        "bound_files": bound, "runtime_receipt_sha256": "d" * 64,
        "tokenizer": {"test_only": True},
        "resource_report": {"file": "resource.json", "sha256": digest(root / "resource.json")},
        "audit": {"calibration": {"seed_sha256": digest(root / ".local/cal.seed"), "reviewer_id": "judge-cal",
                                  "seed_file": ".local/cal.seed", "output_dir": ".local/audit-cal"},
                  "validation": {"seed_sha256": "e" * 64, "reviewer_id": "judge-val",
                                 "seed_file": ".local/val.seed", "output_dir": ".local/audit-val"}},
        "excluded_reviewer_ids": ["test-author", "test-prereviewer", "designer"],
        "phases": {"calibration": {"input_file": "input.json", "oracle_file": "oracle.json",
            "input_sha256": digest(root / "input.json"), "oracle_sha256": digest(root / "oracle.json"),
            "case_ids": [c["id"] for c in cases], "output_dir": ".local/cal-native"},
            "validation": {"input_file": "sealed-input.json", "oracle_file": "sealed-oracle.json",
            "input_sha256": "a" * 64, "oracle_sha256": "b" * 64,
            "case_ids": [f"sealed-{i}" for i in range(12)], "output_dir": ".local/val-native"}}}
    write(root / "plan.json", plan)
    spec = plan["phases"]["calibration"]
    report = {"schema_version": 1, "candidate": runner.CANDIDATE, "phase": "calibration",
        "plan_sha256": digest(root / "plan.json"), "input_sha256": spec["input_sha256"],
        "oracle_sha256": spec["oracle_sha256"], "limits": plan["limits"], "bound_files": bound,
        "status": "completed_not_semantically_verified", "sources_unchanged": True,
        "resources_passed": True, "processes_stopped": True, "semantics_verified": False,
        "native_log_bytes": 0, "paid_calls": 0, "warmup_calls": 0, "retries": 0, "human_review_count": 0,
        "unexecuted": [], "owned_cleanup_ms": 2, "last_request_through_cleanup_ms": 100,
        "calls": [], "results": [], "model_runtime": metadata,
        "planned_dispatches": [{"id": i, "arm": a} for i, a in runner.schedule("calibration", spec["case_ids"])]}
    for sequence, (identity, arm) in enumerate(runner.schedule("calibration", spec["case_ids"])):
        case = next(c for c in cases if c["id"] == identity)
        index = int(identity.split("-")[-1])
        request = AnswerRequest.model_validate(case["payload"])
        catalog_fn, prompt_fn, mapper = ((build_span_catalog, answer_messages_spans, grounded_answer_spans)
            if arm == "L0" else (build_block_catalog, answer_messages_blocks, grounded_answer_blocks))
        catalog = catalog_fn(request.contexts)
        grammar = span_answer_grammar(catalog)
        ko = response_language(request.query) == "ko"
        first = "합성 표식은 민트색이다." if ko else "The synthetic marker is mint."
        if index == 0 and arm == "L0":
            first = "합성 표식은 보라색이다."  # Deliberately wrong control in a synthetic test only.
        raw = json.dumps({"status": "abstained" if index % 4 == 3 else "answered",
            "claims": [] if index % 4 == 3 else [{"text": first, "evidence_ids": [0]},
                {"text": "합성 코드는 14이다." if ko else "The synthetic code is fourteen.", "evidence_ids": [1]}]})
        timings = {"cache_n": 0, "prompt_n": 200, "predicted_n": 29, "prompt_ms": 10., "predicted_ms": 20.}
        telemetry = {"completion_attempts": 1, "elapsed_ms": 45., "calls": [{"finish_reason": "eos", "input_tokens": 200,
            "output_tokens": 30, "native_timings": timings, "elapsed_seconds": .035}]}
        config = {"backend": "llama.cpp", **GREEDY, "n_predict": 384, "grammar": grammar,
            "cache_prompt_requested": False, "observed_cache_tokens": 0,
            "observed_nonthinking_preamble_sha256": PREAMBLE_SHA256, "enable_thinking_requested": False}
        row = {"id": identity, "arm": arm, "structural_status": "passed",
            "payload_sha256": runner.fingerprint(request.model_dump()),
            "prompt_sha256": runner.fingerprint(prompt_fn(request.query, catalog)),
            "official_input_tokens": case["official_input_tokens"][arm], "unit_count": len(catalog.spans),
            "grammar_sha256": hashlib.sha256(grammar.encode()).hexdigest(), "effective_config": config,
            "elapsed_ms": 50., "watchdog_fired": False, "watchdog_joined": True, "worker_telemetry": telemetry,
            "response": {**mapper(raw, catalog, request.contexts, response_language(request.query)), "telemetry": telemetry}}
        report["results"].append(row)
        report["calls"].append({"id": identity, "arm": arm, "sequence": sequence, "dispatch_attempted": True,
            "input_tokens": 200, "raw_response": {"content": raw, "generation_settings": {**GREEDY, "n_predict": 384, "grammar": grammar},
            "model": metadata["artifact"]["sha256"], "stop": True, "stop_type": "eos", "truncated": False,
            "tokens_evaluated": 200, "tokens_predicted": 30, "timings": timings}})
    write(root / ".local/cal-native/report.json", report)
    return SimpleNamespace(root=root, plan=plan, report=report, inputs=inputs, oracle=oracle, seed=seed,
                           plan_path=root / "plan.json", report_path=root / ".local/cal-native/report.json",
                           output=root / ".local/audit-cal")


def prepared(f):
    return audit.prepare(f.plan_path, "calibration", f.report_path, f.root / "oracle.json",
                         f.root / ".local/cal.seed", f.output, root=f.root)


def judgments(pack):
    rows = []
    for sample in pack["samples"]:
        answer = sample["answer"]
        bad = any("보라" in c["text"] for c in answer["claims"])
        absent = answer["status"] == "abstained"
        claims = []
        for i, claim in enumerate(answer["claims"]):
            supported = not (bad and i == 0)
            citation = claim["citations"][0]
            claims.append({"claim_index": i, "facts": [{"text": claim["text"], "supported": supported,
                "support": [{"citation_index": 0, "start_offset": citation["start_offset"],
                             "end_offset": citation["end_offset"]}] if supported else []}],
                "citations": [{"citation_index": 0, "relevant": True, "reason": "Synthetic test assertion."}]})
        quality = {k: True for k in ("citation_exact", "claim_support", "completeness", "language",
                                    "temporal", "subject", "conditions", "correct_abstention_or_answer")}
        quality.update(claim_support=not bad, completeness=not bad)
        rows.append({"sample_id": sample["sample_id"], "quality": quality, "claims": claims,
            "required_facts": [{"fact_id": fact["id"], "present": not absent and not bad,
                                "reason": "Synthetic test assertion."} for fact in sample["oracle"]["required_facts"]],
            "full_correct": not bad, "reason": "Synthetic test assertion, not an AI semantic review.",
            "masking_guess": {"unit_style": "unknown", "confidence": "none", "reason": "No guess."}})
    return {"schema_version": 1, "reviewer_id": "judge-cal", "mapping_not_seen": True,
            "independent_of_authors_and_designers": True, "human_review_count": 0, "judgments": rows}


def completed(f):
    prepared(f)
    write(f.output / "judgments.json", judgments(read(f.output / "review-input.json")))
    audit.lock(f.output / "review-input.json", f.output / "judgments.json", f.output / "receipt.json",
               f.output / "judgments-lock.json")
    gate = audit.finalize(f.plan_path, f.output / "bundle.json", f.output / "judgments.json",
                         f.output / "judgments-lock.json", f.output / "selection.json", root=f.root)
    return gate


def test_full_replay_selection_and_no_validation_bytes_read(fixture, monkeypatch):
    f = fixture
    gate = completed(f)
    assert gate["selected"] and gate["summary"]["correct"] == {"C2": 8, "L0": 7}
    assert gate["summary"]["improvements"] == 1 and gate["summary"]["regressions"] == 0
    original = audit.snapshot
    seen = []

    def spy(path):
        assert "sealed" not in str(path) and "val-" not in str(path)
        seen.append(path)
        return original(path)
    monkeypatch.setattr(audit, "snapshot", spy)
    result = audit.verify_validation_gate(f.plan, f.root, f.output / "selection.json", plan_sha256=digest(f.plan_path))
    assert result["selected"] and seen
    assert not (f.root / "sealed-input.json").exists()
    pack = read(f.output / "review-input.json")
    assert all(set(s) == {"sample_id", "question", "contexts", "oracle", "answer"} for s in pack["samples"])
    assert all(set(s["answer"]) == {"status", "reason", "claims"} for s in pack["samples"])
    assert any(r["citation_exact_rate"] is None for r in gate["summary"]["rows"])
    with pytest.raises(FileExistsError):
        prepared(f)


@pytest.mark.parametrize("field,value", [("stop_type", "limit"), ("tokens_predicted", 999),
    ("tokens_evaluated", 199), ("model", "wrong"), ("truncated", True), ("stop", False)])
def test_raw_native_tampering_rejected_despite_success_telemetry(fixture, field, value):
    f = fixture
    f.report["calls"][0]["raw_response"][field] = value
    write(f.report_path, f.report)
    with pytest.raises(ValueError, match="native_mismatch"):
        prepared(f)
    assert not f.output.exists()


def test_raw_sampling_and_output_repair_rejected(fixture):
    f = fixture
    f.report["calls"][0]["raw_response"]["generation_settings"]["temperature"] = 1
    write(f.report_path, f.report)
    with pytest.raises(ValueError, match="native_mismatch"):
        prepared(f)
    f.report["calls"][0]["raw_response"]["generation_settings"]["temperature"] = 0
    f.report["results"][0]["response"]["claims"][0]["text"] = "임의로 바꾼 답변이다."
    write(f.report_path, f.report)
    with pytest.raises(ValueError, match="output_replay_mismatch"):
        prepared(f)


@pytest.mark.parametrize("kind", ["partial", "reordered", "duplicate", "resource", "changed-model", "source"])
def test_incomplete_mismatched_execution_is_never_reviewed(fixture, kind):
    f = fixture
    if kind == "partial":
        f.report["results"].pop()
    elif kind == "reordered":
        f.report["calls"].reverse()
    elif kind == "duplicate":
        f.report["results"][1] = copy.deepcopy(f.report["results"][0])
    elif kind == "resource":
        f.report["owned_cleanup_ms"] = 5001
    elif kind == "changed-model":
        f.report["model_runtime"]["artifact"]["sha256"] = "e" * 64
    else:
        (f.root / "synthetic.py").write_text("changed")
    write(f.report_path, f.report)
    with pytest.raises(ValueError):
        prepared(f)
    assert not f.output.exists()


@pytest.mark.parametrize("slot", sorted(audit.ARTIFACTS))
def test_heldout_path_substitution_fails_before_any_artifact_read(fixture, monkeypatch, slot):
    f = fixture
    gate = completed(f)
    gate["artifacts"][slot]["file"] = "sealed-input.json"
    write(f.output / "selection.json", gate)
    original = audit.snapshot
    seen = []

    def spy(path):
        seen.append(Path(path).name)
        assert Path(path).name == "selection.json", "artifact read before metadata validation"
        return original(path)
    monkeypatch.setattr(audit, "snapshot", spy)
    with pytest.raises(ValueError, match="artifact_path"):
        audit.verify_validation_gate(f.plan, f.root, f.output / "selection.json", plan_sha256=digest(f.plan_path))
    assert seen == ["selection.json"]


def test_lock_does_not_open_mapping_and_judgments_cannot_change_after_lock(fixture, monkeypatch):
    f = fixture
    prepared(f)
    write(f.output / "judgments.json", judgments(read(f.output / "review-input.json")))
    original = audit.snapshot

    def spy(path):
        assert Path(path).name in {"review-input.json", "judgments.json", "receipt.json"}
        return original(path)
    with monkeypatch.context() as m:
        m.setattr(audit, "snapshot", spy)
        audit.lock(f.output / "review-input.json", f.output / "judgments.json", f.output / "receipt.json",
                   f.output / "judgments-lock.json")
    data = read(f.output / "judgments.json")
    data["judgments"][0]["reason"] = "A changed judgment after locking."
    write(f.output / "judgments.json", data)
    with pytest.raises(ValueError, match="not_locked"):
        audit.finalize(f.plan_path, f.output / "bundle.json", f.output / "judgments.json",
                       f.output / "judgments-lock.json", f.output / "selection.json", root=f.root)


def test_seed_oracle_and_review_snapshot_mutations_are_rejected(fixture):
    f = fixture
    completed(f)
    path = f.output / "review-input.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="artifact_changed"):
        audit.verify_validation_gate(f.plan, f.root, f.output / "selection.json", plan_sha256=digest(f.plan_path))


def test_forged_pass_aggregate_cannot_open_validation(fixture):
    f = fixture
    gate = completed(f)
    gate["summary"]["correct"]["L0"] = 0
    write(f.output / "selection.json", gate)
    with pytest.raises(ValueError, match="selection_replay_failed"):
        audit.verify_validation_gate(f.plan, f.root, f.output / "selection.json", plan_sha256=digest(f.plan_path))


def test_outside_file_rejected_before_read(fixture, monkeypatch):
    def no_read(*args):
        pytest.fail("must reject path before snapshot")
    monkeypatch.setattr(audit, "snapshot", no_read)
    with pytest.raises(ValueError, match="outside_repository"):
        audit.read_artifact(fixture.root.parent / "outside.json", fixture.root)


def test_validation_preparation_requires_selection_before_input_read(fixture, monkeypatch):
    f = fixture
    original = audit.snapshot

    def spy(path):
        assert Path(path) == f.plan_path
        return original(path)
    monkeypatch.setattr(audit, "snapshot", spy)
    with pytest.raises(ValueError, match="selection_required"):
        audit.prepare_validation(f.plan_path, None, f.root / "sealed-report.json", f.root / "sealed-oracle.json",
                                 f.root / ".local/val.seed", f.root / ".local/audit-val", root=f.root)


def test_single_snapshot_parser_hash_uses_captured_bytes(fixture, monkeypatch):
    f = fixture
    original = audit.snapshot
    target = f.report_path

    def replace_after_read(path):
        result = original(path)
        if Path(path) == target:
            target.write_text("{}")
        return result
    monkeypatch.setattr(audit, "snapshot", replace_after_read)
    receipt = prepared(f)
    assert receipt["bindings"]["report"] != digest(target)
    assert receipt["samples"] == 16
    # The saved receipt binds the captured complete report, never the later {}.


@pytest.mark.parametrize("key,value", [("elapsed_ms", -1), ("elapsed_ms", False),
    ("elapsed_ms", 90000), ("watchdog_joined", "yes"), ("watchdog_fired", None)])
def test_timing_and_watchdog_fields_are_strict(fixture, key, value):
    f = fixture
    f.report["results"][0][key] = value
    write(f.report_path, f.report)
    with pytest.raises(ValueError, match="comparison_row_"):
        prepared(f)


@pytest.mark.parametrize("mode", ["worker", "native", "attempt", "error"])
def test_slow_or_failed_telemetry_cannot_hide_behind_fast_row(fixture, mode):
    f = fixture
    telemetry = f.report["results"][0]["worker_telemetry"]
    if mode == "worker":
        telemetry["elapsed_ms"] = 100000
    elif mode == "native":
        telemetry["calls"][0]["elapsed_seconds"] = 91
    elif mode == "attempt":
        telemetry["completion_attempts"] = True
    else:
        telemetry["error_code"] = "generation_failed"
    write(f.report_path, f.report)
    with pytest.raises(ValueError, match="comparison_row_"):
        prepared(f)


@pytest.mark.parametrize("mode", ["gate", "bundle", "report", "oracle", "seed"])
def test_registered_entry_paths_rejected_before_heldout_read(fixture, monkeypatch, mode):
    f = fixture
    original = audit.snapshot

    def spy(path):
        assert Path(path) != f.root / "sealed-input.json"
        return original(path)
    monkeypatch.setattr(audit, "snapshot", spy)
    target = f.root / "sealed-input.json"
    with pytest.raises(ValueError, match="path"):
        if mode == "gate":
            audit.verify_validation_gate(f.plan, f.root, target, plan_sha256=digest(f.plan_path))
        elif mode == "bundle":
            audit.finalize(f.plan_path, target, f.output / "judgments.json", f.output / "judgments-lock.json",
                           f.output / "selection.json", root=f.root)
        else:
            audit.prepare(f.plan_path, "calibration", target if mode == "report" else f.report_path,
                          target if mode == "oracle" else f.root / "oracle.json",
                          target if mode == "seed" else f.root / ".local/cal.seed", f.output, root=f.root)


def test_symlink_alias_cannot_read_validation_input(fixture, monkeypatch):
    f = fixture
    path = f.root / "alias.json"
    try:
        path.symlink_to(f.root / "sealed-input.json")
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    f.plan["phases"]["calibration"]["input_file"] = "alias.json"

    def no_read(*args):
        pytest.fail("resolved collision must fail before any file read")
    monkeypatch.setattr(audit, "snapshot", no_read)
    with pytest.raises(ValueError, match="resolved_path_collision"):
        audit.verify_sources(f.plan, f.root)


def test_selected_validation_twelve_complete_replay_uses_distinct_reviewer(fixture):
    """Fake native reports only. This proves plumbing, never measured accuracy."""
    f = fixture
    source_indices = [0, 0, 1, 2, 3, 3] * 2
    inputs, oracle = [], []
    for i, index in enumerate(source_indices):
        case, answer = copy.deepcopy(f.inputs["cases"][index]), copy.deepcopy(f.oracle["cases"][index])
        case["id"] = answer["id"] = f"synthetic-val-{i}"
        answer["family_id"] = "C2-F03" if i < 6 else "C2-F04"
        answer["provenance"] = "public" if i < 6 else "synthetic"
        inputs.append(case)
        oracle.append(answer)
    write(f.root / "sealed-input.json", {"schema_version": 1, "phase": "validation", "cases": inputs})
    write(f.root / "sealed-oracle.json", {"schema_version": 1, "phase": "validation", "cases": oracle})
    val_spec = f.plan["phases"]["validation"]
    val_spec.update(input_sha256=digest(f.root / "sealed-input.json"),
                    oracle_sha256=digest(f.root / "sealed-oracle.json"), case_ids=[c["id"] for c in inputs])
    (f.root / ".local/val.seed").write_bytes(b"distinct synthetic validation seed" * 2)
    f.plan["audit"]["validation"]["seed_sha256"] = digest(f.root / ".local/val.seed")
    write(f.plan_path, f.plan)  # Both splits sealed before the synthetic calibration report.
    f.report["plan_sha256"] = digest(f.plan_path)
    write(f.report_path, f.report)
    completed(f)
    selection = f.output / "selection.json"
    gate = audit.verify_validation_gate(f.plan, f.root, selection, plan_sha256=digest(f.plan_path))
    report = copy.deepcopy(f.report)
    report.update(phase="validation", input_sha256=val_spec["input_sha256"],
                  oracle_sha256=val_spec["oracle_sha256"], gate=gate, results=[], calls=[],
                  planned_dispatches=[{"id": c["id"], "arm": "C2"} for c in inputs])
    for i, index in enumerate(source_indices):
        row = next(r for r in f.report["results"] if r["id"] == f"synthetic-{index}" and r["arm"] == "C2")
        call = next(c for c in f.report["calls"] if c["id"] == row["id"] and c["arm"] == "C2")
        report["results"].append({**copy.deepcopy(row), "id": inputs[i]["id"]})
        report["calls"].append({**copy.deepcopy(call), "id": inputs[i]["id"], "sequence": i})
    report_path, output = f.root / ".local/val-native/report.json", f.root / ".local/audit-val"
    write(report_path, report)
    receipt = audit.prepare_validation(f.plan_path, selection, report_path, f.root / "sealed-oracle.json",
                                      f.root / ".local/val.seed", output, root=f.root)
    assert receipt["samples"] == 12 and receipt["reviewer_id"] == "judge-val"
    review = judgments(read(output / "review-input.json"))
    review["reviewer_id"] = "judge-val"
    write(output / "judgments.json", review)
    audit.lock(output / "review-input.json", output / "judgments.json", output / "receipt.json",
               output / "judgments-lock.json")
    result = audit.finalize(f.plan_path, output / "bundle.json", output / "judgments.json",
                           output / "judgments-lock.json", output / "validation.json", root=f.root, gate_path=selection)
    assert result["validation_passed"] and result["summary"]["correct"] == {"C2": 12}
    assert not result["selected"] and not result["automatic_service_adoption"]
