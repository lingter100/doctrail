"""C3 final-answer-first audit. No inference, tokenizer, or automatic adoption.

Only an exclusive answer lock permits plan disclosure. The selection verifier
replays the complete calibration evidence before any held-out body is opened.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
from datetime import UTC, datetime
from pathlib import Path

from doctrail.meeting_contract import strict_json
from doctrail.meeting_requirements_review import (
    COUNTS,
    exposure_label,
    validate_attestation,
    validate_judgments,
    validate_oracles,
    validate_plan_diagnostics,
)
from scripts import probe_meeting_requirements as runner

ROOT = runner.ROOT
ARTIFACTS = {"pack": "answers.json", "mapping": "mapping.json", "receipt": "receipt.json",
    "judgments": "judgments.json", "lock": "answer-lock.json", "plan_pack": "plans.json",
    "reveal": "plan-reveal.json", "diagnostics": "plan-diagnostics.json", "result": "selection.json"}
SAMPLE_KEYS = {"sample_id", "question", "response_language", "contexts", "oracle", "answer"}


def now():
    return datetime.now(UTC).isoformat()


def audit_name(value, root=ROOT):
    name = runner.named(value, root)
    if name not in {f".local/meetings-c3-audit-{phase}-v1" for phase in COUNTS}:
        raise ValueError("c3_audit_directory")
    return name


def paths(directory, root=ROOT):
    name = audit_name(directory, root)
    result = {role: name + "/" + filename for role, filename in ARTIFACTS.items()}
    targets = [runner.path(value, root, local=True) for value in result.values()]
    for index, target in enumerate(targets):
        if target.exists() and any(other.exists() and target.samefile(other) for other in targets[:index]):
            raise ValueError("c3_audit_alias")
    return result


def json_read(snapshots, name, expected=None):
    return strict_json(snapshots.get(name, expected).decode("utf-8"))


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("c3_audit_timestamp")
    return parsed


def replay(plan, plan_sha, phase, snapshots, *, gate_path=None, created_at):
    """All path guards, then cal gate, then source/item/native original replay."""
    if phase not in COUNTS or plan.get("kind") != "quality":
        raise ValueError("c3_audit_phase")
    runner.metadata_paths(plan, snapshots.root)
    directory = plan["audit"][phase]["output_dir"]
    paths(directory, snapshots.root)
    runner.common(plan, snapshots)
    gate = runner.model_free_gate(plan, plan_sha, phase, gate_path, snapshots.root)
    resource = runner.resource_evidence(plan, snapshots)
    inputs, preparation = runner.load_phase(plan, phase, snapshots)
    spec, registration = plan["phases"][phase], plan["audit"][phase]
    oracles = snapshots.read(spec["oracle"])
    validate_oracles({k: v for k, v in inputs.items() if k != "candidate"}, oracles, phase)
    for oracle in oracles["cases"]:
        if not {oracle[k] for k in ("question_author", "oracle_author", "independent_prereviewer")} <= set(plan["excluded_roles"]):
            raise ValueError("c3_oracle_author_exclusion")
    report_name = spec["output_dir"] + "/report.json"
    report = json_read(snapshots, report_name)
    runner.report_integrity(report, plan, plan_sha, phase, spec["case_ids"])
    prefix = resource["ledger_entries"] if phase == "calibration" else gate["ledger_entries"]
    if (report["ledger_entries"][:len(prefix)] != prefix
            or len(report["ledger_entries"]) != len(prefix) + len(report["calls"])
            or runner.fingerprint(report["model_runtime"]) != runner.fingerprint(resource["model_runtime"])
            or report.get("gate") != gate):
        raise ValueError("c3_report_lineage")
    seed = snapshots.get(registration["seed"]["file"], registration["seed"]["sha256"])
    if not 32 <= len(seed) <= 128:
        raise ValueError("c3_seed_length")
    attestation = snapshots.read(registration["attestation"])
    exposure = validate_attestation(attestation, registration["reviewer_id"], plan["excluded_roles"], pack_opened_at=created_at)
    original = []
    cursor = 0
    for case, row, oracle in zip(inputs["cases"], report["results"], oracles["cases"], strict=True):
        calls = [call for call in report["calls"] if call["case_id"] == case["id"]]
        if (report["calls"][cursor:cursor + len(calls)] != calls
                or runner.fingerprint(row.get("preparations")) != runner.fingerprint(calls)):
            raise ValueError("c3_stage_order")
        cursor += len(calls)
        answer, requirement_plan = runner.replay_request(case, row, calls, report["model_runtime"])
        original.append((case, oracle, answer, requirement_plan))
    if cursor != len(report["calls"]):
        raise ValueError("c3_extra_calls")
    original.sort(key=lambda row: hmac.new(seed, row[0]["id"].encode(), hashlib.sha256).digest())
    samples, mappings, diagnostic_samples = [], [], []
    for index, (case, oracle, answer, requirement_plan) in enumerate(original, 1):
        sample_id = f"sample-{index:03d}"
        anonymous_oracle = copy.deepcopy(oracle)
        anonymous_oracle["id"] = sample_id
        sample = {"sample_id": sample_id, "question": case["payload"]["query"],
            "response_language": case["response_language"], "contexts": copy.deepcopy(case["payload"]["contexts"]),
            "oracle": anonymous_oracle, "answer": answer}
        samples.append(sample)
        mappings.append({"sample_id": sample_id, "case_id": case["id"]})
        diagnostic_samples.append({k: sample[k] for k in ("sample_id", "contexts", "oracle", "response_language", "answer")}
            | {"plan": requirement_plan, "plan_sha256": runner.fingerprint(requirement_plan)})
    pack = {"schema_version": 1, "purpose": "final_answer_review", "samples": samples}
    mapping = {"schema_version": 1, "samples": mappings, "custodian_knows_mapping": True}
    plan_pack = {"schema_version": 1, "purpose": "post_lock_plan_diagnostic", "samples": diagnostic_samples}
    receipt = {"schema_version": 1, "candidate": runner.ANSWER_POLICY, "phase": phase,
        "plan_sha256": plan_sha, "created_at": created_at, "reviewer_id": registration["reviewer_id"],
        "excluded_roles": plan["excluded_roles"], "seed": registration["seed"], "attestation": registration["attestation"],
        "output_dir": directory, "pack_sha256": runner.sha(runner.encoded(pack)),
        "mapping_sha256": runner.sha(runner.encoded(mapping)), "report_sha256": snapshots.hashes[report_name],
        "snapshots": dict(snapshots.hashes), "bound_files": plan["bound_files"], "code_freeze": plan["code_freeze"],
        "exposure": exposure_label(exposure), "custodian_knows_mapping": True,
        "model_calls": 0, "tokenizer_calls": 0, "human_review_count": 0}
    return {"pack": pack, "mapping": mapping, "plan_pack": plan_pack, "receipt": receipt,
        "report": report, "attestation": attestation, "preparation": preparation}


def prepare(plan_path, phase, gate_path=None, *, root=ROOT):
    plan, plan_sha, snapshots, _ = runner.read_plan(plan_path, root)
    if phase not in COUNTS:
        raise ValueError("c3_audit_phase")
    files = paths(plan["audit"][phase]["output_dir"], root)
    output = runner.path(plan["audit"][phase]["output_dir"], root, local=True)
    if output.exists():
        raise FileExistsError("c3_audit_consumed")
    evidence = replay(plan, plan_sha, phase, snapshots, gate_path=gate_path, created_at=now())
    snapshots.unchanged()
    output.mkdir(parents=True, exist_ok=False)
    for role in ("pack", "mapping", "receipt"):
        runner.write_new(files[role], evidence[role], root)
    return evidence["receipt"]


def locked(directory, *, root=ROOT, require_lock=True):
    """No current-split requirement plan/mapping/raw is opened.

    Validation first replays the existing calibration gate and its originals;
    that exception never discloses the current validation requirement plans.
    """
    files, snapshots = paths(directory, root), runner.Snapshots(root)
    receipt = json_read(snapshots, files["receipt"])
    phase = receipt.get("phase")
    if (phase not in COUNTS or receipt.get("candidate") != runner.ANSWER_POLICY
            or audit_name(directory, root) != f".local/meetings-c3-audit-{phase}-v1"
            or receipt.get("output_dir") != audit_name(directory, root)
            or not runner.EXCLUDED_ROLES <= set(receipt.get("excluded_roles", []))):
        raise ValueError("c3_audit_receipt")
    if phase == "validation":
        candidates = [name for name, value in receipt.get("snapshots", {}).items()
                      if value == receipt["plan_sha256"] and "-plan-" in Path(name).name]
        if len(candidates) != 1:
            raise ValueError("c3_selection_plan_binding")
        execution, execution_sha, _, _ = runner.read_plan(candidates[0], root)
        if execution_sha != receipt["plan_sha256"]:
            raise ValueError("c3_selection_plan_changed")
        verify_validation_gate(execution, execution_sha,
            paths(execution["audit"]["calibration"]["output_dir"], root)["result"], root=root)
    attestation_ref = receipt["attestation"]
    if attestation_ref.get("file") != f".local/meetings-c3-review-metadata-v1/{phase}/attestation.json":
        raise ValueError("c3_review_metadata_path")
    attestation = snapshots.read(attestation_ref)
    validate_attestation(attestation, receipt["reviewer_id"], receipt["excluded_roles"], pack_opened_at=receipt["created_at"])
    pack = json_read(snapshots, files["pack"], receipt["pack_sha256"])
    if (set(pack) != {"schema_version", "purpose", "samples"} or pack["purpose"] != "final_answer_review"
            or type(pack["schema_version"]) is not int or pack["schema_version"] != 1
            or len(pack["samples"]) != COUNTS[phase] or any(set(s) != SAMPLE_KEYS for s in pack["samples"])):
        raise ValueError("c3_answer_pack")
    judgments = json_read(snapshots, files["judgments"])
    scores = validate_judgments(pack, judgments, receipt["reviewer_id"], receipt["excluded_roles"], attestation)
    expected = {"schema_version": 1, "purpose": "immutable_final_answer_lock", "phase": phase,
        "reviewer_id": receipt["reviewer_id"], "receipt_sha256": snapshots.hashes[files["receipt"]],
        "pack_sha256": snapshots.hashes[files["pack"]], "judgments_sha256": snapshots.hashes[files["judgments"]],
        "attestation_sha256": attestation_ref["sha256"], "plan_sha256": receipt["plan_sha256"],
        "score_sha256": runner.fingerprint(scores), "answer_scores_final": True,
        "plan_disclosed_before_lock": False, "model_calls": 0, "human_review_count": 0}
    lock = json_read(snapshots, files["lock"]) if require_lock else None
    if lock is not None and (set(lock) != set(expected) | {"locked_at"}
            or runner.fingerprint({k: v for k, v in lock.items() if k != "locked_at"}) != runner.fingerprint(expected)
            or timestamp(lock["locked_at"]) < timestamp(receipt["created_at"])):
        raise ValueError("c3_answer_lock_changed")
    return {"files": files, "snapshots": snapshots, "receipt": receipt, "pack": pack,
        "scores": scores, "lock": lock, "expected": expected}


def lock_answers(directory, *, root=ROOT):
    files = paths(directory, root)
    if any(runner.path(files[role], root).exists() for role in ("lock", "plan_pack", "reveal", "diagnostics", "result")):
        raise FileExistsError("c3_answer_lock_consumed")
    state = locked(directory, root=root, require_lock=False)
    state["snapshots"].unchanged()
    lock = state["expected"] | {"locked_at": now()}
    runner.write_new(files["lock"], lock, root)
    return lock


def replay_locked(plan_path, phase, gate_path, root):
    plan, plan_sha, snapshots, _ = runner.read_plan(plan_path, root)
    runner.metadata_paths(plan, root)
    # Lock verification finishes before mapping/raw/plan replay or plan disclosure.
    state = locked(plan["audit"][phase]["output_dir"], root=root)
    evidence = replay(plan, plan_sha, phase, snapshots, gate_path=gate_path,
                      created_at=state["receipt"]["created_at"])
    if runner.fingerprint(evidence["receipt"]) != runner.fingerprint(state["receipt"]):
        raise ValueError("c3_audit_original_changed")
    mapping = json_read(state["snapshots"], state["files"]["mapping"], state["receipt"]["mapping_sha256"])
    if mapping != evidence["mapping"] or state["pack"] != evidence["pack"]:
        raise ValueError("c3_audit_mapping_replay")
    snapshots.unchanged()
    return plan, plan_sha, state, evidence


def reveal_plan(plan_path, phase, gate_path=None, *, root=ROOT):
    _plan, plan_sha, state, evidence = replay_locked(plan_path, phase, gate_path, root)
    files = state["files"]
    if any(runner.path(files[role], root).exists() for role in ("plan_pack", "reveal", "diagnostics", "result")):
        raise FileExistsError("c3_plan_reveal_consumed")
    state["snapshots"].unchanged()
    pack_sha = runner.sha(runner.encoded(evidence["plan_pack"]))
    reveal = {"schema_version": 1, "phase": phase, "plan_sha256": plan_sha, "revealed_at": now(),
        "answer_lock_sha256": state["snapshots"].hashes[files["lock"]], "plan_pack_sha256": pack_sha,
        "answers_unchanged": True, "post_lock_only": True, "model_calls": 0}
    runner.write_new(files["plan_pack"], evidence["plan_pack"], root)
    runner.write_new(files["reveal"], reveal, root)
    return reveal


def aggregate(rows):
    count = len(rows)
    citations = sum(r["citations"] for r in rows)
    exact = sum(r["exact_citations"] for r in rows)
    facts = sum(r["facts"] for r in rows)
    supported = sum(r["supported_facts"] for r in rows)
    relevant = sum(r["relevant_citation_links"] for r in rows)
    source = sum(r["source_unique_codepoints"] for r in rows)
    quote = sum(r["citation_unique_codepoints"] for r in rows)
    support = sum(r["support_unique_codepoints"] for r in rows)
    return {"cases": count, "full_correct": sum(r["full_correct"] for r in rows),
        "quality": {k: sum(r["quality"][k] for r in rows) for k in rows[0]["quality"]},
        "citations": citations, "exact_citations": exact,
        "citation_exact_rate": exact / citations if citations else None,
        "relevant_citation_links": relevant, "citation_precision": relevant / citations if citations else None,
        "facts": facts, "supported_facts": supported, "fact_support_rate": supported / facts if facts else None,
        "citation_codepoints": sum(r["citation_codepoints"] for r in rows),
        "citation_duplicate_codepoints": sum(r["citation_duplicate_codepoints"] for r in rows),
        "source_unique_codepoints": source, "citation_unique_codepoints": quote, "support_unique_codepoints": support,
        "source_quoted_fraction": quote / source if source else None,
        "quote_to_support_width": quote / support if support else None}


def result_from_artifacts(plan_path, phase, gate_path=None, *, root=ROOT):
    plan, plan_sha, state, evidence = replay_locked(plan_path, phase, gate_path, root)
    files, snapshots = state["files"], state["snapshots"]
    reveal = json_read(snapshots, files["reveal"])
    lock_sha = snapshots.hashes[files["lock"]]
    expected = {"schema_version": 1, "phase": phase, "plan_sha256": plan_sha,
        "answer_lock_sha256": lock_sha, "plan_pack_sha256": runner.sha(runner.encoded(evidence["plan_pack"])),
        "answers_unchanged": True, "post_lock_only": True, "model_calls": 0}
    if (set(reveal) != set(expected) | {"revealed_at"}
            or runner.fingerprint({k: v for k, v in reveal.items() if k != "revealed_at"}) != runner.fingerprint(expected)
            or timestamp(reveal["revealed_at"]) < timestamp(state["lock"]["locked_at"])):
        raise ValueError("c3_plan_reveal_binding")
    plan_pack = json_read(snapshots, files["plan_pack"], expected["plan_pack_sha256"])
    if plan_pack != evidence["plan_pack"]:
        raise ValueError("c3_plan_pack_replay")
    diagnostic = json_read(snapshots, files["diagnostics"])
    validate_plan_diagnostics(diagnostic, plan_pack["samples"], reviewer_id=state["receipt"]["reviewer_id"],
        answer_lock_sha256=lock_sha, plan_pack_sha256=expected["plan_pack_sha256"])
    rows = copy.deepcopy(state["scores"]["rows"])
    if len(rows) != COUNTS[phase]:
        raise ValueError("c3_partial_selection")
    summary = aggregate(rows)
    passed = summary["full_correct"] == COUNTS[phase]
    result = {"schema_version": 1, "candidate": runner.ANSWER_POLICY, "phase": phase,
        "plan_sha256": plan_sha, "code_freeze": plan["code_freeze"], "bound_files": plan["bound_files"],
        "complete": True, "selected": phase == "calibration" and passed,
        "validation_eligible": phase == "calibration" and passed,
        "validation_passed": phase == "validation" and passed, "automatic_adoption": False,
        "answer_scores_final": True, "plan_diagnostics_affect_selection": False,
        "summary": summary, "rows": rows, "exposure": state["scores"]["exposure"],
        "reviewer_id": state["receipt"]["reviewer_id"], "artifacts": {
            role: {"file": files[role], "sha256": snapshots.hashes[files[role]]}
            for role in ("receipt", "pack", "mapping", "judgments", "lock", "plan_pack", "reveal", "diagnostics")},
        "ledger_entries": evidence["report"]["ledger_entries"],
        "model_calls": 0, "tokenizer_calls": 0, "human_review_count": 0}
    snapshots.unchanged()
    return result


def finalize(plan_path, phase, gate_path=None, *, root=ROOT):
    result = result_from_artifacts(plan_path, phase, gate_path, root=root)
    plan, _, _, _ = runner.read_plan(plan_path, root)
    files = paths(plan["audit"][phase]["output_dir"], root)
    runner.write_new(files["result"], result, root)
    return result


def verify_validation_gate(plan, plan_sha, gate_path, *, root=ROOT):
    """No validation input, oracle, source, or review bytes are opened."""
    runner.metadata_paths(plan, root)
    expected = paths(plan["audit"]["calibration"]["output_dir"], root)["result"]
    if gate_path is None or runner.named(gate_path, root) != expected:
        raise ValueError("c3_selection_path")
    # A plan filename is not accepted from a gate. Locate it only via the
    # caller's registered immutable bytes, then pass an explicit snapshot below.
    snapshots = runner.Snapshots(root)
    gate = json_read(snapshots, expected)
    if (gate.get("selected") is not True or gate.get("validation_eligible") is not True
            or gate.get("phase") != "calibration" or gate.get("plan_sha256") != plan_sha):
        raise ValueError("c3_selection_failed")
    receipt_name = paths(plan["audit"]["calibration"]["output_dir"], root)["receipt"]
    receipt = json_read(snapshots, receipt_name)
    candidates = [name for name, value in receipt.get("snapshots", {}).items()
                  if value == plan_sha and "-plan-" in Path(name).name]
    if len(candidates) != 1:
        raise ValueError("c3_selection_plan_binding")
    recorded, actual_sha, _, _ = runner.read_plan(candidates[0], root)
    if actual_sha != plan_sha or runner.fingerprint(recorded) != runner.fingerprint(plan):
        raise ValueError("c3_selection_plan_changed")
    replayed = result_from_artifacts(candidates[0], "calibration", root=root)
    if runner.fingerprint(gate) != runner.fingerprint(replayed):
        raise ValueError("c3_selection_replay")
    snapshots.unchanged()
    return gate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "lock-answers", "reveal-plan", "finalize"))
    parser.add_argument("--plan")
    parser.add_argument("--phase", choices=tuple(COUNTS))
    parser.add_argument("--gate")
    parser.add_argument("--audit-dir")
    args = parser.parse_args(argv)
    try:
        if args.operation == "lock-answers":
            if not args.audit_dir:
                raise ValueError("c3_audit_directory_required")
            lock_answers(args.audit_dir)
        else:
            if not args.plan or not args.phase:
                raise ValueError("c3_audit_plan_required")
            {"prepare": prepare, "reveal-plan": reveal_plan, "finalize": finalize}[args.operation](
                args.plan, args.phase, args.gate)
        print("c3_audit_completed")
        return 0
    except Exception:  # noqa: BLE001 - never print private artifact contents
        print("c3_audit_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
