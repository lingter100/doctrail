"""Prepare, lock and replay C2 anonymous reviews without generation or downloads.

Give an independent reviewer only review-input.json and the review schema. Lock
their judgment file before opening mapping.json. Role separation is an explicit
workflow assumption; local hashes cannot prove what a reviewer has already seen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from datetime import UTC, datetime
from pathlib import Path

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
from doctrail.meeting_comparison_review import (
    JudgmentFile,
    score_sample,
    summarize,
    validate_oracles,
)
from doctrail.meeting_contract import AnswerRequest, strict_json

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = {"report", "input", "oracle", "seed", "preparation",
             "review_input", "mapping", "receipt", "judgments", "lock"}


def snapshot(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("audit_file_limit")
    return raw, hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def hashed(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def parse(raw):
    return strict_json(raw.decode("utf-8"))


def write_new(path, value):
    with Path(path).open("xb") as stream:
        stream.write(encoded(value))


def relative(path, root):
    from scripts.probe_meeting_budget_comparison import checked_path
    resolved = checked_path(str(path), root, absolute=True)
    return resolved.relative_to(root.resolve()).as_posix()


def resolve(name, root):
    from scripts.probe_meeting_budget_comparison import checked_path
    return checked_path(name, root)


def digest(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def validate_audit_registration(plan):
    from scripts.probe_meeting_budget_comparison import REQUIRED_EXCLUDED
    audit, excluded = plan.get("audit"), plan.get("excluded_reviewer_ids")
    if (not isinstance(audit, dict) or set(audit) != {"calibration", "validation"}
            or not isinstance(excluded, list) or not excluded
            or any(not isinstance(e, str) or not e.strip() for e in excluded)
            or len(set(excluded)) != len(excluded) or not REQUIRED_EXCLUDED <= set(excluded)):
        raise ValueError("audit_registration_invalid")
    reviewers = []
    for spec in audit.values():
        if (not isinstance(spec, dict) or set(spec) != {"seed_sha256", "reviewer_id", "seed_file", "output_dir"}
                or not digest(spec["seed_sha256"]) or not isinstance(spec["reviewer_id"], str)
                or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", spec["reviewer_id"])
                or spec["reviewer_id"] in excluded):
            raise ValueError("audit_registration_invalid")
        reviewers.append(spec["reviewer_id"])
    if len(set(reviewers)) != 2:
        raise ValueError("audit_reviewer_not_separate")
    paths = []
    for phase in ("calibration", "validation"):
        phase_spec = plan["phases"][phase]
        names = [phase_spec.get("input_file"), phase_spec.get("oracle_file"),
                 phase_spec.get("output_dir"), audit[phase]["seed_file"], audit[phase]["output_dir"],
                 phase_spec.get("preparation_receipt", {}).get("file")]
        for name in names:
            if (not isinstance(name, str) or not name or Path(name).is_absolute()
                    or ".." in Path(name).parts or "." == name):
                raise ValueError("audit_registration_path")
            path = Path(name)
            if any(path.is_relative_to(p) or p.is_relative_to(path) for p in paths):
                raise ValueError("audit_registration_collision")
            paths.append(path)
        if (not Path(audit[phase]["output_dir"]).is_relative_to(".local")
                or not Path(audit[phase]["seed_file"]).is_relative_to(".local")
                or not digest(phase_spec.get("preparation_receipt", {}).get("sha256"))):
            raise ValueError("audit_registration_path")


def verify_sources(plan, root):
    from scripts import probe_meeting_budget_comparison as runner
    validate_audit_registration(plan)
    validate_audit_paths(plan, root)
    runner.verify_source_contract(plan, root)
    return runner.validate_resource_report(plan, root)


def validate_audit_paths(plan, root):
    """Check resolved aliases too, before a symlink can alias a held-out path."""
    paths = []
    for phase in ("calibration", "validation"):
        spec, audit = plan["phases"][phase], plan["audit"][phase]
        for name in (spec["input_file"], spec["oracle_file"], spec["output_dir"],
                     audit["seed_file"], audit["output_dir"], spec["preparation_receipt"]["file"]):
            path = resolve(name, root)
            if any(path.is_relative_to(p) or p.is_relative_to(path) for p in paths):
                raise ValueError("audit_resolved_path_collision")
            paths.append(path)
    # These metadata refs are read while replaying calibration selection. They
    # must never alias a held-out input/oracle, even under a forged resource ref.
    for key in ("source_freeze", "resource_report", "resource_plan"):
        ref = plan.get(key, {})
        if set(ref) != {"file", "sha256"} or not digest(ref.get("sha256")):
            raise ValueError("audit_metadata_binding")
        path = resolve(ref["file"], root)
        if any(path.is_relative_to(p) or p.is_relative_to(path) for p in paths):
            raise ValueError("audit_metadata_collision")
        paths.append(path)
    for name in plan.get("bound_files", {}):
        path = resolve(name, root)
        if any(path.is_relative_to(p) or p.is_relative_to(path) for p in paths):
            raise ValueError("audit_code_artifact_collision")


def check_model(report, resource):
    from scripts.probe_meeting_budget_comparison import check_model_metadata
    expected, actual = resource["model_runtime"], report["model_runtime"]
    check_model_metadata(actual)
    for key in ("repo_id", "revision", "original_revision", "artifact"):
        if actual.get(key) != expected.get(key):
            raise ValueError("audit_model_identity")
    for key in ("backend", "tag", "commit", "observed_build", "context_tokens"):
        if actual["runtime"].get(key) != expected["runtime"].get(key):
            raise ValueError("audit_runtime_identity")


def check_native(row, call, model_runtime, grammar):
    from doctrail.meeting_gguf import GREEDY, _same_setting
    from scripts import probe_meeting_budget_comparison as runner
    native, metric = call["raw_response"], row["worker_telemetry"]["calls"][0]
    settings, timings = native.get("generation_settings", {}), native.get("timings", {})
    expected = {**GREEDY, "n_predict": 384, "grammar": grammar}
    runner.check_payload(call.get("payload"), grammar)
    if (runner.fingerprint(call["payload"]) != call.get("payload_sha256")
            or len(call["payload"]["prompt"]) != metric["input_tokens"]):
        raise ValueError("audit_dispatch_payload")
    runner.validate_native_response(call, model_runtime, grammar,
        input_tokens=metric["input_tokens"], output_tokens=metric["output_tokens"], finish_reason="eos")
    if (any(k not in settings or not _same_setting(settings[k], v) for k, v in expected.items())
            or native.get("model") != model_runtime["artifact"]["sha256"]
            or native.get("stop") is not True or native.get("stop_type") != "eos"
            or native.get("truncated") is not False or type(timings.get("cache_n")) is not int
            or timings["cache_n"] != 0 or type(timings.get("prompt_n")) is not int
            or timings["prompt_n"] != metric["input_tokens"]
            or type(native.get("tokens_evaluated")) is not int
            or native["tokens_evaluated"] != metric["input_tokens"]
            or type(native.get("tokens_predicted")) is not int
            or native["tokens_predicted"] != metric["output_tokens"]
            or type(call.get("input_tokens")) is not int
            or call["input_tokens"] != metric["input_tokens"]
            or metric.get("native_timings") != {k: v for k, v in timings.items()
                if k in {"cache_n", "prompt_n", "prompt_ms", "predicted_n", "predicted_ms"}
                and type(v) in (int, float)}):
        raise ValueError("audit_native_mismatch")


def expected_paths(plan, phase):
    spec, audit = plan["phases"][phase], plan["audit"][phase]
    directory = Path(audit["output_dir"])
    return {"input": spec["input_file"], "oracle": spec["oracle_file"],
        "preparation": spec["preparation_receipt"]["file"],
        "report": (Path(spec["output_dir"]) / "report.json").as_posix(), "seed": audit["seed_file"],
        **{k: (directory / filename).as_posix() for k, filename in {
            "review_input": "review-input.json", "mapping": "mapping.json", "receipt": "receipt.json",
            "judgments": "judgments.json", "lock": "judgments-lock.json"}.items()}}


def preflight_refs(plan, phase, refs, root):
    validate_audit_paths(plan, root)
    paths = expected_paths(plan, phase)
    for key, ref in refs.items():
        if (key not in paths or not isinstance(ref, dict) or set(ref) != {"file", "sha256"}
                or not digest(ref["sha256"]) or ref["file"] != paths[key]):
            raise ValueError("audit_artifact_path")
        resolve(ref["file"], root)  # Resolve/check every path before reading any artifact.
    for key, sha in (("input", plan["phases"][phase]["input_sha256"]),
                     ("oracle", plan["phases"][phase]["oracle_sha256"]),
                     ("preparation", plan["phases"][phase]["preparation_receipt"]["sha256"]),
                     ("seed", plan["audit"][phase]["seed_sha256"])):
        if key in refs and refs[key]["sha256"] != sha:
            raise ValueError("audit_artifact_binding")


def assemble(plan, plan_sha, phase, report, inputs, oracle, seed, preparation, *, root=None):
    """Deterministic replay from already captured bytes, never reopen an input."""
    from scripts import probe_meeting_budget_comparison as runner
    validate_audit_registration(plan)
    spec = plan["phases"][phase]
    runner.validate_preparation_receipt(plan, phase, preparation, root=root)
    oracles = validate_oracles(inputs, oracle, phase)
    ids = spec["case_ids"]
    expected = runner.schedule(phase, ids)
    if (len(seed) < 32 or len(seed) > 128
            or hashlib.sha256(seed).hexdigest() != plan["audit"][phase]["seed_sha256"]):
        raise ValueError("audit_seed_mismatch")
    if (type(report.get("schema_version")) is not int or report["schema_version"] != 1
            or type(inputs.get("schema_version")) is not int or inputs["schema_version"] != 1
            or report.get("candidate") != runner.CANDIDATE or report.get("phase") != phase
            or report.get("protocol_sha256") != runner.PROTOCOL_SHA256
            or report.get("protocol_deviation") != runner.DEVIATION
            or report.get("resource_report") != plan["resource_report"]
            or report.get("preparation_receipt") != spec["preparation_receipt"]
            or report.get("plan_sha256") != plan_sha
            or report.get("input_sha256") != spec["input_sha256"]
            or report.get("oracle_sha256") != spec["oracle_sha256"]
            or report.get("status") != "completed_not_semantically_verified"
            or report.get("sources_unchanged") is not True
            or report.get("resources_passed") is not True
            or report.get("processes_stopped") is not True
            or report.get("semantics_verified") is not False
            or any(report.get(k) != 0 or type(report.get(k)) is not int for k in (
                "native_log_bytes", "human_review_count", "paid_calls", "warmup_calls", "retries"))
            or any(k in report for k in ("failure", "source_error"))
            or report.get("unexecuted") != []
            or report.get("bound_files") != plan["bound_files"]
            or report.get("limits") != plan["limits"]
            or [c["id"] for c in inputs["cases"]] != ids
            or [(r.get("id"), r.get("arm")) for r in report.get("results", [])] != expected
            or [(c.get("id"), c.get("arm")) for c in report.get("calls", [])] != expected
            or report.get("planned_dispatches") != [{"id": i, "arm": a} for i, a in expected]):
        raise ValueError("audit_report_incomplete")
    for key, limit in (("owned_cleanup_ms", 5000), ("last_request_through_cleanup_ms", 120000)):
        value = report.get(key)
        if type(value) not in (int, float) or not 0 <= value <= limit:
            raise ValueError("audit_resource_limit")
    by_id = {c["id"]: (c, o.model_dump()) for c, o in zip(inputs["cases"], oracles.cases, strict=True)}
    prepared = []
    for sequence, (row, call) in enumerate(zip(report["results"], report["calls"], strict=True)):
        case, case_oracle = by_id[row["id"]]
        request = AnswerRequest.model_validate(case["payload"])
        if runner.fingerprint(request.model_dump(exclude_unset=True)) != runner.fingerprint(case["payload"]):
            raise ValueError("audit_original_payload_mismatch")
        arm = row["arm"]
        catalog_fn, messages_fn, map_fn = ((build_span_catalog, answer_messages_spans, grounded_answer_spans)
            if arm == "L0" else (build_block_catalog, answer_messages_blocks, grounded_answer_blocks))
        catalog = catalog_fn(request.contexts)
        prompt = messages_fn(request.query, catalog)
        grammar = span_answer_grammar(catalog)
        if (row.get("structural_status") != "passed" or row.get("payload_sha256") != runner.fingerprint(
                case["payload"]) or row.get("prompt_sha256") != runner.fingerprint(prompt)
                or row.get("grammar_sha256") != hashlib.sha256(grammar.encode()).hexdigest()
                or row.get("unit_count") != len(catalog.spans)
                or type(row.get("official_input_tokens")) is not int
                or not 0 < row["official_input_tokens"] <= 5120
                or row["official_input_tokens"] != case["official_input_tokens"][arm]
                or type(call.get("sequence")) is not int or call["sequence"] != sequence
                or call.get("dispatch_attempted") is not True
                or row.get("worker_telemetry") != row.get("response", {}).get("telemetry")):
            raise ValueError("audit_row_binding")
        prep = next(c for c in preparation["cases"] if c["id"] == row["id"])
        if (prep["payload_sha256"] != row["payload_sha256"]
                or prep["arms"][arm]["official_input_tokens"] != row["official_input_tokens"]
                or prep["arms"][arm]["prompt_sha256"] != row["prompt_sha256"]
                or prep["arms"][arm]["grammar_sha256"] != row["grammar_sha256"]):
            raise ValueError("audit_preparation_binding")
        runner.check_row(row, [call])
        check_native(row, call, report["model_runtime"], grammar)
        answer = map_fn(call["raw_response"]["content"], catalog, request.contexts,
                        response_language(request.query))
        actual = {k: row["response"][k] for k in ("status", "reason", "claims")}
        if answer != actual:
            raise ValueError("audit_output_replay_mismatch")
        prepared.append({"case_id": row["id"], "arm": arm, "question": request.query,
                         "contexts": case["payload"]["contexts"], "oracle": case_oracle, "answer": answer})
    random.Random(int.from_bytes(hashlib.sha256(seed).digest(), "big")).shuffle(prepared)
    samples, mapping = [], []
    for index, item in enumerate(prepared, 1):
        identity = f"sample-{index:02}"
        mapping.append({"sample_id": identity, "case_id": item["case_id"], "arm": item["arm"]})
        samples.append({"sample_id": identity, "question": item["question"], "contexts": item["contexts"],
                        "oracle": {**item["oracle"], "id": identity}, "answer": item["answer"]})
    pack = {"schema_version": 1, "phase": phase, "human_review_count": 0,
        "instructions": "Judge every factual assertion, including optional examples and reasons, only against its selected citations. Assess required-fact coverage separately. Record minimal support offsets. Do not open mapping, model identity, earlier judgments or aggregate scores before locking this judgment file.",
        "masking_limits": "Unit shape and repeated outputs may reveal roles. Record any guess. AI review is not human verification.",
        "samples": samples}
    return pack, {"schema_version": 1, "mappings": mapping}


def receipt_for(plan, plan_sha, phase, artifacts, pack, mapping):
    return {"schema_version": 1, "phase": phase, "plan_sha256": plan_sha,
        "candidate": plan["candidate"], "protocol_deviation": plan["protocol_deviation"],
        "bindings": {k: artifacts[k]["sha256"] for k in ("report", "input", "oracle", "seed", "preparation")},
        "review_input_sha256": hashed(pack), "mapping_sha256": hashed(mapping),
        "reviewer_id": plan["audit"][phase]["reviewer_id"], "samples": len(pack["samples"]),
        "model_calls": 0, "judgments": 0, "human_review_count": 0}


def read_artifact(path, root):
    name = relative(path, root)
    raw, sha = snapshot(path)
    return raw, {"file": name, "sha256": sha}


def prepare(plan_path, phase, report_path, oracle_path, seed_path, output, *, root=ROOT):
    plan_raw, plan_sha = snapshot(plan_path)
    plan = parse(plan_raw)
    verify_sources(plan, root)
    if phase == "validation":
        raise ValueError("audit_validation_requires_gate_prepare")
    return prepare_phase(plan, plan_sha, phase, report_path, oracle_path, seed_path, output, root)


def prepare_phase(plan, plan_sha, phase, report_path, oracle_path, seed_path, output, root, gate=None):
    """Called for validation only after verifying selection in prepare_validation."""
    if phase == "validation" and gate is None:
        raise ValueError("audit_validation_requires_gate_prepare")
    spec = plan["phases"][phase]
    paths = expected_paths(plan, phase)
    for name, path in (("report", report_path), ("oracle", oracle_path), ("seed", seed_path)):
        if relative(path, root) != paths[name]:
            raise ValueError("audit_artifact_path")
    if relative(output, root) != plan["audit"][phase]["output_dir"]:
        raise ValueError("audit_output_path")
    resource = verify_sources(plan, root)
    raw, refs = {}, {}
    for name, path in {"report": report_path, "input": resolve(spec["input_file"], root),
                       "preparation": resolve(spec["preparation_receipt"]["file"], root),
                       "oracle": oracle_path, "seed": seed_path}.items():
        raw[name], refs[name] = read_artifact(path, root)
    if refs["input"]["sha256"] != spec["input_sha256"] or refs["oracle"]["sha256"] != spec["oracle_sha256"]:
        raise ValueError("audit_input_binding")
    if refs["preparation"]["sha256"] != spec["preparation_receipt"]["sha256"]:
        raise ValueError("audit_preparation_binding")
    report = parse(raw["report"])
    if phase == "validation" and (gate is None or report.get("gate") != gate):
        raise ValueError("audit_validation_gate_binding")
    check_model(report, resource)
    pack, mapping = assemble(plan, plan_sha, phase, parse(raw["report"]), parse(raw["input"]),
                             parse(raw["oracle"]), raw["seed"], parse(raw["preparation"]), root=root)
    receipt = receipt_for(plan, plan_sha, phase, refs, pack, mapping)
    output = Path(output)
    relative(output, root)
    output.mkdir(parents=True, exist_ok=False)
    for name, value in (("review-input", pack), ("mapping", mapping), ("receipt", receipt)):
        write_new(output / (name + ".json"), value)
    for name, filename in (("review_input", "review-input.json"), ("mapping", "mapping.json"),
                           ("receipt", "receipt.json")):
        refs[name] = {"file": relative(output / filename, root),
                      "sha256": snapshot(output / filename)[1]}
    write_new(output / "bundle.json", {"schema_version": 1, "phase": phase,
                                       "plan_sha256": plan_sha, "artifacts": refs})
    return receipt


def prepare_validation(plan_path, gate_path, report_path, oracle_path, seed_path, output, *, root=ROOT):
    raw, sha = snapshot(plan_path)
    plan = parse(raw)
    gate = verify_validation_gate(plan, root, gate_path, plan_sha256=sha)
    return prepare_phase(plan, sha, "validation", report_path, oracle_path, seed_path, output, root, gate)


def lock(review_path, judgments_path, receipt_path, output):
    """No mapping, seed, model log or previous review is opened here."""
    raw, review_sha = snapshot(review_path)
    pack = parse(raw)
    raw, judgments_sha = snapshot(judgments_path)
    judgments = JudgmentFile.model_validate(parse(raw))
    raw, receipt_sha = snapshot(receipt_path)
    receipt = parse(raw)
    if (review_sha != receipt["review_input_sha256"] or judgments.reviewer_id != receipt["reviewer_id"]
            or [j.sample_id for j in judgments.judgments] != [s["sample_id"] for s in pack["samples"]]):
        raise ValueError("audit_lock_binding")
    for sample, judgment in zip(pack["samples"], judgments.judgments, strict=True):
        score_sample(sample, judgment.model_dump())
    result = {"schema_version": 1, "plan_sha256": receipt["plan_sha256"], "phase": receipt["phase"],
        "review_input_sha256": review_sha, "judgments_sha256": judgments_sha, "receipt_sha256": receipt_sha,
        "reviewer_id": judgments.reviewer_id, "locked_at": datetime.now(UTC).isoformat(),
        "mapping_opened_by_lock": False, "human_review_count": 0}
    write_new(output, result)
    return result


def replay(plan, plan_sha, phase, refs, root, gate=None):
    validate_audit_registration(plan)
    if set(refs) != ARTIFACTS:
        raise ValueError("audit_artifact_set")
    preflight_refs(plan, phase, refs, root)
    resource = verify_sources(plan, root)
    captured = {}
    # One read per artifact; every downstream parser uses these same bytes.
    for name, ref in refs.items():
        raw, sha = snapshot(resolve(ref["file"], root))
        if sha != ref["sha256"]:
            raise ValueError("audit_artifact_changed")
        captured[name] = raw
    spec = plan["phases"][phase]
    if (refs["input"]["file"] != spec["input_file"]
            or refs["input"]["sha256"] != spec["input_sha256"]
            or refs["oracle"]["sha256"] != spec["oracle_sha256"]):
        raise ValueError("audit_input_binding")
    report = parse(captured["report"])
    if phase == "validation" and (gate is None or report.get("gate") != gate):
        raise ValueError("audit_validation_gate_binding")
    check_model(report, resource)
    pack, mapping = assemble(plan, plan_sha, phase, parse(captured["report"]), parse(captured["input"]),
                             parse(captured["oracle"]), captured["seed"], parse(captured["preparation"]), root=root)
    receipt = receipt_for(plan, plan_sha, phase, refs, pack, mapping)
    for name, value in (("review_input", pack), ("mapping", mapping), ("receipt", receipt)):
        if hashed(value) != refs[name]["sha256"]:
            raise ValueError("audit_replay_mismatch")
    locked = parse(captured["lock"])
    if (locked.get("plan_sha256") != plan_sha or locked.get("phase") != phase
            or locked.get("reviewer_id") != plan["audit"][phase]["reviewer_id"]
            or locked.get("review_input_sha256") != refs["review_input"]["sha256"]
            or locked.get("judgments_sha256") != refs["judgments"]["sha256"]
            or locked.get("receipt_sha256") != refs["receipt"]["sha256"]
            or locked.get("mapping_opened_by_lock") is not False):
        raise ValueError("audit_judgments_not_locked")
    summary = summarize(pack, parse(captured["judgments"]), mapping, phase,
                        plan["audit"][phase]["reviewer_id"], plan["excluded_reviewer_ids"])
    return summary


def finalize(plan_path, bundle_path, judgments_path, lock_path, output, *, root=ROOT, gate_path=None):
    raw, plan_sha = snapshot(plan_path)
    plan = parse(raw)
    validate_audit_registration(plan)
    validate_audit_paths(plan, root)
    bundle_name = relative(bundle_path, root)
    phase = next((phase for phase in ("calibration", "validation") if bundle_name ==
                  (Path(plan["audit"][phase]["output_dir"]) / "bundle.json").as_posix()), None)
    if phase is None:
        raise ValueError("audit_bundle_path")
    gate = None
    if phase == "validation":
        gate = verify_validation_gate(plan, root, gate_path, plan_sha256=plan_sha)
    expected_output = Path(plan["audit"][phase]["output_dir"]) / (
        "selection.json" if phase == "calibration" else "validation.json")
    if relative(output, root) != expected_output.as_posix():
        raise ValueError("audit_output_path")
    bundle = parse(snapshot(bundle_path)[0])
    if bundle["phase"] != phase or bundle["plan_sha256"] != plan_sha:
        raise ValueError("audit_bundle_plan")
    refs = bundle["artifacts"]
    paths = expected_paths(plan, phase)
    for name, path in (("judgments", judgments_path), ("lock", lock_path)):
        if relative(path, root) != paths[name]:
            raise ValueError("audit_artifact_path")
        _, refs[name] = read_artifact(path, root)
    summary = replay(plan, plan_sha, phase, refs, root, gate)
    result = {"schema_version": 1, "candidate": plan["candidate"], "phase": phase,
              "plan_sha256": plan_sha, "artifacts": refs, "summary": summary,
              "selected": summary["passed"] if phase == "calibration" else False,
              "validation_passed": summary["passed"] if phase == "validation" else None,
              "automatic_service_adoption": False, "human_review_count": 0}
    write_new(output, result)
    return result


def verify_validation_gate(plan, root, gate_path, *, plan_sha256):
    if gate_path is None:
        raise ValueError("audit_selection_required")
    validate_audit_registration(plan)
    validate_audit_paths(plan, root)
    if relative(gate_path, root) != (
            Path(plan["audit"]["calibration"]["output_dir"]) / "selection.json").as_posix():
        raise ValueError("audit_selection_path")
    # No validation input/oracle bytes are opened by this function.
    raw, gate_sha = snapshot(gate_path)
    gate = parse(raw)
    if (gate.get("phase") != "calibration" or gate.get("candidate") != plan["candidate"]
            or gate.get("plan_sha256") != plan_sha256 or gate.get("selected") is not True):
        raise ValueError("audit_selection_failed")
    summary = replay(plan, plan_sha256, "calibration", gate["artifacts"], root)
    if summary != gate.get("summary") or summary["passed"] is not True:
        raise ValueError("audit_selection_replay_failed")
    return {"gate_sha256": gate_sha, "plan_sha256": plan_sha256,
            "selected": True, "calibration_correct": summary["correct"],
            "improvements": summary["improvements"], "regressions": summary["regressions"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    prepare_parser = sub.add_parser("prepare")
    for name in ("plan", "report", "oracle", "seed", "output"):
        prepare_parser.add_argument("--" + name, type=Path, required=True)
    prepare_parser.add_argument("--phase", choices=("calibration", "validation"), required=True)
    prepare_parser.add_argument("--gate", type=Path)
    lock_parser = sub.add_parser("lock")
    for name in ("review", "judgments", "receipt", "output"):
        lock_parser.add_argument("--" + name, type=Path, required=True)
    final_parser = sub.add_parser("finalize")
    for name in ("plan", "bundle", "judgments", "lock", "output"):
        final_parser.add_argument("--" + name, type=Path, required=True)
    final_parser.add_argument("--gate", type=Path)
    args = parser.parse_args()
    try:
        if args.operation == "prepare":
            if args.phase == "validation":
                result = prepare_validation(args.plan, args.gate, args.report, args.oracle, args.seed, args.output)
            else:
                result = prepare(args.plan, args.phase, args.report, args.oracle, args.seed, args.output)
        elif args.operation == "lock":
            result = lock(args.review, args.judgments, args.receipt, args.output)
        else:
            result = finalize(args.plan, args.bundle, args.judgments, args.lock, args.output, gate_path=args.gate)
        print(json.dumps({k: result[k] for k in ("phase", "samples", "selected", "validation_passed") if k in result}))
    except Exception:  # noqa: BLE001 - no source, question, oracle or judgment text in console errors
        parser.exit(1, "comparison_audit_failed\n")


if __name__ == "__main__":
    main()
