"""C4 final-answer-only audit: prepare, immutable judgment lock, original replay.

No reasoning disclosure step exists. Validation always replays original complete
calibration before opening held-out bodies, including at lock and finalize.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
from datetime import datetime

from doctrail.meeting_thinking_review import (
    COUNTS,
    exposure_label,
    validate_attestation,
    validate_judgments,
)
from scripts import prepare_meeting_thinking_inputs as prep
from scripts import probe_meeting_thinking_quality as probe

ROOT = prep.ROOT
FILES = {"pack": "answers.json", "mapping": "mapping.json", "receipt": "receipt.json",
         "judgments": "judgments.json", "lock": "judgment-lock.json", "result": "selection.json"}


def names(phase, root=ROOT):
    if phase not in COUNTS:
        raise ValueError("c4_audit_phase")
    prefix = f".local/meetings-c4-audit-{phase}-v1"
    result = {key: prefix + "/" + filename for key, filename in FILES.items()}
    prep.separate(result.values(), root)
    return prefix, result


def anonymous(case, oracle, answer, sample_id):
    value = copy.deepcopy(oracle.model_dump())
    value["id"] = sample_id
    value.update(question_author="author-A", oracle_author="author-B", independent_prereviewer="prereviewer")
    for index, fact in enumerate(value["required_facts"], 1):
        fact["id"] = f"fact-{index:03d}"
    return {"sample_id": sample_id, "question": case["payload"]["query"], "response_language": case["response_language"],
            "contexts": copy.deepcopy(case["payload"]["contexts"]), "oracle": value, "answer": copy.deepcopy(answer)}


def replay(phase, *, root=ROOT, git=prep.committed, opened_at=None):
    prepared = probe.check(phase, root=root, git=git)
    snapshots, plan = prepared["snapshots"], prepared["plan"]
    created = opened_at or prep.now()
    audit = plan["audit"][phase]
    exposure = snapshots.read(audit["attestation"])
    attested = validate_attestation(exposure, audit["reviewer_id"], plan["excluded_roles"], pack_opened_at=created)
    report_name = prepared["output"] + "/report.json"
    report = snapshots.json(report_name)
    answers = probe.report_replay(prepared, report)
    seed = snapshots.get(audit["seed"]["file"], audit["seed"]["sha256"])
    rows = list(zip(prepared["cases"], prepared["oracles"].cases, answers, strict=True))
    rows.sort(key=lambda row: hmac.new(seed, row[0]["id"].encode(), hashlib.sha256).digest())
    samples, mapping = [], []
    for index, (case, oracle, answer) in enumerate(rows, 1):
        # Original authors were checked by probe.check against sealed source/item evidence.
        if audit["reviewer_id"] in {oracle.question_author, oracle.oracle_author, oracle.independent_prereviewer}:
            raise ValueError("c4_original_reviewer_conflict")
        sample_id = f"sample-{index:03d}"
        samples.append(anonymous(case, oracle, answer, sample_id))
        mapping.append({"sample_id": sample_id, "case_id": case["id"]})
    pack = {"schema_version": 1, "purpose": "final_answer_review", "samples": samples}
    raw = prep.encoded(pack)
    if any(case["id"].encode() in raw for case in prepared["cases"]):
        raise ValueError("c4_original_id_in_anonymous_pack")
    mapping = {"schema_version": 1, "samples": mapping, "custodian_knows_mapping": True}
    receipt = {"schema_version": 1, "candidate": probe.CANDIDATE_ID, "phase": phase, "created_at": created,
        "plan_sha256": snapshots.hashes[probe.PLAN], "report_sha256": snapshots.hashes[report_name],
        "pack_sha256": prep.sha(raw), "mapping_sha256": prep.sha(prep.encoded(mapping)),
        "reviewer_id": audit["reviewer_id"], "attestation": audit["attestation"], "seed": audit["seed"],
        "excluded_roles": plan["excluded_roles"], "exposure": exposure_label(attested),
        "snapshots": snapshots.hashes, "model_calls": 0, "tokenizer_calls": 0, "human_review_count": 0}
    snapshots.unchanged()
    return {"pack": pack, "mapping": mapping, "receipt": receipt, "report": report,
            "attestation": exposure, "prepared": prepared}


def prepare(phase, *, root=ROOT, git=prep.committed):
    output, files = names(phase, root)
    if prep.path(output, root).exists():
        raise FileExistsError("c4_audit_consumed")
    evidence = replay(phase, root=root, git=git)
    prep.path(output, root).mkdir(parents=True, exist_ok=False)
    for key in ("pack", "mapping", "receipt"):
        prep.write_new(files[key], evidence[key], root)
    return evidence["receipt"]


def locked(phase, *, root=ROOT, git=prep.committed, require_lock=True):
    """Current-split raw/mapping/reasoning stay closed. Prior cal gate is replayed."""
    if git is prep.committed:
        git = prep.GitProof(root)
    _, files = names(phase, root)
    snapshots = prep.Snapshots(root)
    plan = snapshots.json(probe.PLAN)
    probe.paths(plan, root)
    probe.gate(plan, phase, root, git=git)
    probe.metadata(plan, snapshots, git=git)
    receipt = snapshots.json(files["receipt"])
    audit = plan["audit"][phase]
    if (receipt.get("candidate") != probe.CANDIDATE_ID or receipt.get("phase") != phase
            or receipt.get("plan_sha256") != snapshots.hashes[probe.PLAN]
            or receipt.get("reviewer_id") != audit["reviewer_id"] or receipt.get("excluded_roles") != plan["excluded_roles"]
            or receipt.get("attestation") != audit["attestation"] or receipt.get("seed") != audit["seed"]):
        raise ValueError("c4_audit_receipt_binding")
    pack = snapshots.read({"file": files["pack"], "sha256": receipt["pack_sha256"]})
    if (set(pack) != {"schema_version", "purpose", "samples"} or type(pack["schema_version"]) is not int
            or pack["schema_version"] != 1 or pack["purpose"] != "final_answer_review" or len(pack["samples"]) != COUNTS[phase]
            or [s["sample_id"] for s in pack["samples"]] != [f"sample-{n:03d}" for n in range(1, COUNTS[phase] + 1)]
            or any(set(s) != {"sample_id", "question", "response_language", "contexts", "oracle", "answer"} for s in pack["samples"])):
        raise ValueError("c4_anonymous_pack_schema")
    attest = snapshots.read(audit["attestation"])
    validate_attestation(attest, audit["reviewer_id"], plan["excluded_roles"], pack_opened_at=receipt["created_at"])
    result = {"snapshots": snapshots, "files": files, "pack": pack, "receipt": receipt, "attestation": attest}
    if require_lock:
        lock_value = snapshots.json(files["lock"])
        judgments = snapshots.read({"file": files["judgments"], "sha256": lock_value["judgments_sha256"]})
        if (set(lock_value) != {"schema_version", "phase", "created_at", "reviewer_id", "actual_model", "actual_effort",
                              "pack_sha256", "receipt_sha256", "judgments_sha256", "attestation_sha256"}
                or lock_value["schema_version"] != 1 or type(lock_value["schema_version"]) is not int
                or lock_value["phase"] != phase or lock_value["reviewer_id"] != audit["reviewer_id"]
                or lock_value["pack_sha256"] != receipt["pack_sha256"] or lock_value["receipt_sha256"] != snapshots.hashes[files["receipt"]]
                or lock_value["attestation_sha256"] != audit["attestation"]["sha256"]
                or lock_value["actual_model"] != attest["actual_model"] or lock_value["actual_effort"] != attest["actual_effort"]
                or not datetime.fromisoformat(receipt["created_at"]) <= datetime.fromisoformat(lock_value["created_at"]) <= datetime.fromisoformat(prep.now())):
            raise ValueError("c4_judgment_lock_binding")
        result["scores"] = validate_judgments(pack, judgments, audit["reviewer_id"], plan["excluded_roles"], attest, opened_at=receipt["created_at"])
        result["lock"] = lock_value
    snapshots.unchanged()
    return result


def lock(phase, submitted_sha256, *, root=ROOT, git=prep.committed):
    evidence = locked(phase, root=root, git=git, require_lock=False)
    files, receipt, snapshots = evidence["files"], evidence["receipt"], evidence["snapshots"]
    if prep.path(files["lock"], root).exists():
        raise FileExistsError("c4_lock_consumed")
    # Judge writes only this predeclared filename; no arbitrary input path is opened.
    submitted = snapshots.read({"file": files["judgments"], "sha256": submitted_sha256})
    validate_judgments(evidence["pack"], submitted, receipt["reviewer_id"], receipt["excluded_roles"],
                       evidence["attestation"], opened_at=receipt["created_at"])
    result = {"schema_version": 1, "phase": phase, "created_at": prep.now(), "reviewer_id": receipt["reviewer_id"],
        "actual_model": evidence["attestation"]["actual_model"], "actual_effort": evidence["attestation"]["actual_effort"],
        "pack_sha256": receipt["pack_sha256"], "receipt_sha256": snapshots.hashes[files["receipt"]],
        "judgments_sha256": submitted_sha256, "attestation_sha256": receipt["attestation"]["sha256"]}
    snapshots.unchanged()
    prep.write_new(files["lock"], result, root)
    return result


def finalize(phase, *, root=ROOT, git=prep.committed, publish=True):
    evidence = locked(phase, root=root, git=git)
    files, snapshots = evidence["files"], evidence["snapshots"]
    # Only after the immutable answer lock is verified may this split's mapping/raw be connected.
    mapping = snapshots.read({"file": files["mapping"], "sha256": evidence["receipt"]["mapping_sha256"]})
    original = replay(phase, root=root, git=git, opened_at=evidence["receipt"]["created_at"])
    if any(prep.canonical(original[k]) != prep.canonical(evidence[k] if k != "mapping" else mapping) for k in ("pack", "receipt", "mapping")):
        raise ValueError("c4_audit_original_replay")
    rows = evidence["scores"]["rows"]
    full = sum(row["full_correct"] for row in rows)
    passed = len(rows) == COUNTS[phase] and full == COUNTS[phase]
    result = {"schema_version": 1, "candidate": probe.CANDIDATE_ID, "phase": phase, "complete_correct": full,
        "denominator": COUNTS[phase], "selected": phase == "calibration" and passed,
        "validation_eligible": phase == "calibration" and passed, "validation_passed": phase == "validation" and passed,
        "automatic_service_adoption": False, "human_review_count": 0, "rows": rows, "exposure": evidence["scores"]["exposure"],
        "plan_sha256": evidence["receipt"]["plan_sha256"], "report_sha256": evidence["receipt"]["report_sha256"],
        "lock_sha256": snapshots.hashes[files["lock"]], "ledger": original["report"]["ledger"]}
    snapshots.unchanged()
    if publish:
        prep.write_new(files["result"], result, root)
    return result


def verify_calibration_gate(plan, *, root=ROOT, git=prep.committed):
    _, files = names("calibration", root)
    # Fixed local path prevents a forged gate reference from opening held-out data.
    stored = prep.Snapshots(root).json(files["result"])
    actual = finalize("calibration", root=root, git=git, publish=False)
    if (prep.canonical(stored) != prep.canonical(actual) or actual["selected"] is not True
            or actual["validation_eligible"] is not True or actual["denominator"] != 6 or actual["complete_correct"] != 6
            or actual["plan_sha256"] != prep.sha(prep.snapshot(prep.path(probe.PLAN, root))[0])):
        raise ValueError("c4_calibration_gate_failed")
    return actual


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "lock", "finalize"))
    parser.add_argument("--phase", required=True, choices=COUNTS)
    parser.add_argument("--judgments-sha256")
    args = parser.parse_args(argv)
    try:
        if args.operation == "prepare":
            prepare(args.phase)
        elif args.operation == "lock":
            lock(args.phase, args.judgments_sha256)
        else:
            finalize(args.phase)
        print('{"status":"completed"}')
        return 0
    except Exception:  # noqa: BLE001 - never print question, final answer or reasoning
        print('{"status":"failed_closed"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
