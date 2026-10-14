"""Diagnose the one closed C2 budget calibration; never select or resume it.

Only prepare/lock/finalize are supported. Reviewers receive review-input.json
alone; mapping is opened by finalization only after a complete judgment lock.
Local hashes verify artifacts, not a reviewer's actual independence or exposure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from datetime import UTC, datetime
from pathlib import Path

from doctrail.inference import WorkerError
from doctrail.meeting_comparison_review import JudgmentFile, score_sample, validate_oracles
from doctrail.meeting_contract import AnswerRequest
from scripts import audit_meeting_budget_comparison as audit
from scripts import probe_meeting_budget_comparison as runner

ROOT = Path(__file__).resolve().parents[1]
PLAN_FILE = "data/evaluation/meetings-c2-input-budget-execution-plan-v1.json"
PLAN_SHA256 = "845554b865d6b3fbf362b6834e98b5323cf5c366cc01ea8cf01f3c870bd251db"
REPORT_FILE = "experiments/results/meetings-c2-input-budget-calibration-v1.json"
REPORT_SHA256 = "c4acac4ce4c3af9c6a77988e86400ed6f31d7b4b0c7dd59e9d251b8041ab3486"
REPORT_BYTES = 788359
DESIGN_FILE = "docs/MEETINGS-C2-BUDGET-PARTIAL-AUDIT.md"
DESIGN_SHA256 = "28e26e70cf5dc5373290f8ff878ff303ec315ac1335572988f9fca85f9cd12a7"
OUTPUT = ".local/c2-budget-partial-audit-v1"
REVIEWER = "/root/c2_calibration_judge"
REVIEW_MODEL = "gpt-6-astra"
REVIEW_EFFORT = "xhigh"
CASE_IDS = [f"C2-CAL-{i:02}" for i in range(1, 9)]
FILES = {"scripts/audit_meeting_budget_partial.py", "tests/test_audit_meeting_budget_partial.py"}
ERROR = "generation_language_mismatch"
FLAGS = {"purpose": "post_hoc_partial_diagnostic", "selected": False,
         "eligible_for_selection": False, "original_full_gate": "failed",
         "validation_eligible": False, "automatic_service_adoption": False}
COUNTS = {"planned": 16, "dispatched": 15, "structurally_passed": 14,
          "language_failures": 1, "unexecuted": 1, "validation": 0}


def snapshot(path):
    return audit.snapshot(path)


def path(name, root):
    return runner.checked_path(name, root)


def capture(name, root, expected=None, size=None):
    raw, sha = snapshot(path(name, root))
    if expected is not None and sha != expected or size is not None and len(raw) != size:
        raise ValueError("partial_binding_changed")
    return raw, {"file": name, "sha256": sha, "bytes": len(raw)}


def source_bindings(root):
    return {name: capture(name, root)[1]["sha256"] for name in sorted(FILES)}


def check_flags(value):
    if runner.fingerprint({k: value.get(k) for k in FLAGS}) != runner.fingerprint(FLAGS):
        raise ValueError("partial_ineligible_flags")


def closed_evidence(root):
    """Read calibration semantics once; validation paths are never opened."""
    plan_raw, plan_ref = capture(PLAN_FILE, root, PLAN_SHA256)
    plan = audit.parse(plan_raw)
    audit.validate_audit_registration(plan)
    audit.validate_audit_paths(plan, root)
    if plan["phases"]["calibration"]["case_ids"] != CASE_IDS:
        raise ValueError("partial_case_registration")
    if plan["audit"]["calibration"]["reviewer_id"] != REVIEWER:
        raise ValueError("partial_reviewer_registration")
    output = path(OUTPUT, root)
    protected = [PLAN_FILE, REPORT_FILE, DESIGN_FILE, *plan["bound_files"], *FILES]
    for phase in plan["phases"]:
        spec, reg = plan["phases"][phase], plan["audit"][phase]
        protected += [spec["input_file"], spec["oracle_file"], spec["output_dir"],
                      spec["preparation_receipt"]["file"], reg["seed_file"], reg["output_dir"]]
        if path(reg["output_dir"], root).exists():
            raise ValueError("partial_original_audit_already_exists")
    for name in protected:
        target = path(name, root)
        if output.is_relative_to(target) or target.is_relative_to(output):
            raise ValueError("partial_output_collision")
    resource = audit.verify_sources(plan, root)
    spec, reg = plan["phases"]["calibration"], plan["audit"]["calibration"]
    bindings = {"plan": plan_ref}
    raw = {}
    refs = {"report": (REPORT_FILE, REPORT_SHA256, REPORT_BYTES),
            "input": (spec["input_file"], spec["input_sha256"], None),
            "oracle": (spec["oracle_file"], spec["oracle_sha256"], None),
            "preparation": (spec["preparation_receipt"]["file"], spec["preparation_receipt"]["sha256"], None),
            "seed": (reg["seed_file"], reg["seed_sha256"], 64),
            "source_freeze": (plan["source_freeze"]["file"], plan["source_freeze"]["sha256"], None),
            "design": (DESIGN_FILE, DESIGN_SHA256, None)}
    for key, (name, sha, size) in refs.items():
        raw[key], bindings[key] = capture(name, root, sha, size)
    report = audit.parse(raw["report"])
    audit.check_model(report, resource)
    inputs, oracle, preparation = [audit.parse(raw[k]) for k in ("input", "oracle", "preparation")]
    runner.validate_preparation_receipt(plan, "calibration", preparation, root=root)
    pack, mapping, failure, replay = assemble(plan, report, inputs, oracle, raw["seed"], preparation)
    receipt = {"schema_version": 1, **FLAGS, "phase": "calibration_partial_diagnostic",
        "plan_sha256": PLAN_SHA256, "bindings": bindings, "source_bindings": source_bindings(root),
        "review_input_sha256": audit.hashed(pack), "mapping_sha256": audit.hashed(mapping),
        "failure_replay_sha256": audit.hashed(failure), "reviewer_id": REVIEWER,
        "excluded_reviewer_ids": plan["excluded_reviewer_ids"], "samples": 14,
        "execution_counts": COUNTS, "included_rule": "all_first_14_structurally_passed_responses_in_execution_order",
        "excluded_rule": "15th_language_failure_and_16th_unexecuted_are_not_semantically_scored",
        "row_replay": replay, "seed_carryforward": "same_registered_unused_64_byte_calibration_seed; no_new_seed_or_shuffle_selection",
        "model_calls": 0, "tokenizer_calls": 0, "judgments": 0, "human_review_count": 0}
    return pack, mapping, failure, receipt


def transport_failure(row, call):
    """Validate transport without changing or treating the failed answer as valid."""
    from doctrail.meeting_gguf import GREEDY
    from doctrail.meeting_qwen35 import PREAMBLE_SHA256
    telemetry = row["worker_telemetry"]
    metrics = telemetry.get("calls", [])
    elapsed, worker = row.get("elapsed_ms"), telemetry.get("elapsed_ms")
    expected = {"backend": "llama.cpp", **GREEDY, "n_predict": 384,
        "cache_prompt_requested": False, "observed_cache_tokens": 0,
        "observed_nonthinking_preamble_sha256": PREAMBLE_SHA256, "enable_thinking_requested": False}
    config = row.get("effective_config", {})
    if (row.get("error") != ERROR or telemetry.get("error_code") != ERROR
            or row.get("structural_status") != "failed" or "response" in row or "error" in call
            or not runner.finite(elapsed, 90000, inclusive=False)
            or not runner.finite(worker, 90000, inclusive=False) or worker > elapsed + 1
            or type(telemetry.get("completion_attempts")) is not int or telemetry["completion_attempts"] != 1
            or len(metrics) != 1 or row.get("watchdog_fired") is not False
            or row.get("watchdog_joined") is not True or row.get("watchdog_kill_failed")
            or runner.fingerprint({k: config.get(k) for k in expected}) != runner.fingerprint(expected)
            or hashlib.sha256(config.get("grammar", "").encode()).hexdigest() != row["grammar_sha256"]):
        raise ValueError("partial_failure_transport")
    metric = metrics[0]
    if (metric.get("finish_reason") != "eos" or metric.get("input_tokens") != row["official_input_tokens"]
            or not runner.finite(metric.get("elapsed_seconds"), 90, inclusive=False)
            or metric["elapsed_seconds"] * 1000 > worker + 1):
        raise ValueError("partial_failure_transport")


def assemble(plan, report, inputs, oracle, seed, preparation):
    """Replay captured bytes. No generator, tokenizer, full-phase audit or gate."""
    spec = plan["phases"]["calibration"]
    expected = runner.schedule("calibration", CASE_IDS)
    pairs = lambda rows: [(r.get("id"), r.get("arm")) for r in rows]
    if (type(report.get("schema_version")) is not int or report["schema_version"] != 1
            or type(inputs.get("schema_version")) is not int or inputs["schema_version"] != 1
            or report.get("candidate") != runner.CANDIDATE or report.get("phase") != "calibration"
            or report.get("protocol_sha256") != runner.PROTOCOL_SHA256
            or report.get("protocol_deviation") != runner.DEVIATION
            or report.get("resource_report") != plan["resource_report"]
            or report.get("preparation_receipt") != spec["preparation_receipt"]
            or report.get("plan_sha256") != PLAN_SHA256 or report.get("input_sha256") != spec["input_sha256"]
            or report.get("oracle_sha256") != spec["oracle_sha256"] or report.get("status") != "failed"
            or report.get("failure") != ERROR or "source_error" in report
            or report.get("sources_unchanged") is not True or report.get("resources_passed") is not False
            or report.get("processes_stopped") is not True or report.get("semantics_verified") is not False
            or report.get("gate") is not None
            or any(type(report.get(k)) is not int or report[k] != 0 for k in
                   ("native_log_bytes", "human_review_count", "paid_calls", "warmup_calls", "retries"))
            or report.get("bound_files") != plan["bound_files"]
            or runner.fingerprint(report.get("limits")) != runner.fingerprint(runner.LIMITS)
            or report.get("unexecuted") != [{"id": expected[-1][0], "arm": expected[-1][1]}]
            or pairs(report.get("results", [])) != expected[:15]
            or pairs(report.get("calls", [])) != expected[:15]
            or report.get("planned_dispatches") != [{"id": i, "arm": a} for i, a in expected]
            or [c["id"] for c in inputs["cases"]] != CASE_IDS
            or len(seed) != 64 or hashlib.sha256(seed).hexdigest() != plan["audit"]["calibration"]["seed_sha256"]):
        raise ValueError("partial_closed_execution_contract")
    for key, limit in (("owned_cleanup_ms", 5000), ("last_request_through_cleanup_ms", 120000)):
        if not runner.finite(report.get(key), limit):
            raise ValueError("partial_cleanup_contract")
    oracles = validate_oracles(inputs, oracle, "calibration")
    by_id = {c["id"]: (c, o.model_dump()) for c, o in zip(inputs["cases"], oracles.cases, strict=True)}
    prepared, replay, failure = [], [], None
    for sequence, (row, call) in enumerate(zip(report["results"], report["calls"], strict=True)):
        case, case_oracle = by_id[row["id"]]
        request = AnswerRequest.model_validate(case["payload"])
        if runner.fingerprint(request.model_dump(exclude_unset=True)) != runner.fingerprint(case["payload"]):
            raise ValueError("partial_payload_changed")
        arm = row["arm"]
        catalog_fn, message_fn, mapper = ((audit.build_span_catalog, audit.answer_messages_spans, audit.grounded_answer_spans)
            if arm == "L0" else (audit.build_block_catalog, audit.answer_messages_blocks, audit.grounded_answer_blocks))
        catalog = catalog_fn(request.contexts)
        grammar = audit.span_answer_grammar(catalog)
        if (row.get("payload_sha256") != runner.fingerprint(case["payload"])
                or row.get("prompt_sha256") != runner.fingerprint(message_fn(request.query, catalog))
                or row.get("grammar_sha256") != hashlib.sha256(grammar.encode()).hexdigest()
                or type(row.get("unit_count")) is not int or row["unit_count"] != len(catalog.spans)
                or type(row.get("official_input_tokens")) is not int
                or type(case["official_input_tokens"][arm]) is not int
                or row["official_input_tokens"] != case["official_input_tokens"][arm]
                or not 0 < row["official_input_tokens"] <= 5120
                or type(call.get("sequence")) is not int or call["sequence"] != sequence
                or call.get("dispatch_attempted") is not True):
            raise ValueError("partial_row_binding")
        prep = next(c for c in preparation["cases"] if c["id"] == row["id"])
        if (prep["payload_sha256"] != row["payload_sha256"]
                or any(prep["arms"][arm][k] != row[k] for k in
                       ("official_input_tokens", "prompt_sha256", "grammar_sha256"))):
            raise ValueError("partial_preparation_binding")
        audit.check_native(row, call, report["model_runtime"], grammar)
        language = audit.response_language(request.query)
        link = {"case_id": row["id"], "arm": arm, "sequence": sequence,
                "row_sha256": runner.fingerprint(row), "call_sha256": runner.fingerprint(call),
                "raw_response_sha256": runner.fingerprint(call["raw_response"])}
        if sequence == 14:
            transport_failure(row, call)
            if language != "en":
                raise ValueError("partial_failure_language")
            try:
                mapper(call["raw_response"]["content"], catalog, request.contexts, language)
            except WorkerError as error:
                if error.code != ERROR:
                    raise ValueError("partial_failure_replay_mismatch") from error
            else:
                raise ValueError("partial_failure_not_reproduced")
            failure = {"schema_version": 1, **FLAGS, **link, "request_language": language,
                "observed_error": ERROR, "replayed_error": ERROR, "same_guard_reproduced": True,
                "semantic_scoring_performed": False, "native_transport_verified": True,
                "payload_sha256": row["payload_sha256"], "prompt_sha256": row["prompt_sha256"],
                "grammar_sha256": row["grammar_sha256"], "native_metrics": row["worker_telemetry"]["calls"][0],
                "elapsed_ms": row["elapsed_ms"], "raw_content_sha256": hashlib.sha256(call["raw_response"]["content"].encode()).hexdigest(),
                "unexecuted": report["unexecuted"], "model_calls": 0, "human_review_count": 0}
            continue
        if (row.get("structural_status") != "passed"
                or row.get("worker_telemetry") != row.get("response", {}).get("telemetry")):
            raise ValueError("partial_success_row")
        runner.check_row(row, [call])
        answer = mapper(call["raw_response"]["content"], catalog, request.contexts, language)
        if answer != {k: row["response"][k] for k in ("status", "reason", "claims")}:
            raise ValueError("partial_mapper_replay")
        replay.append({**link, "native_and_mapper_replayed": True})
        prepared.append({"case_id": row["id"], "arm": arm, "question": request.query,
                         "contexts": case["payload"]["contexts"], "oracle": case_oracle, "answer": answer})
    random.Random(int.from_bytes(hashlib.sha256(seed).digest(), "big")).shuffle(prepared)
    samples, links = [], []
    for index, item in enumerate(prepared, 1):
        identity = f"sample-{index:02}"
        samples.append({"sample_id": identity, "question": item["question"], "contexts": item["contexts"],
                        "oracle": {**item["oracle"], "id": identity}, "answer": item["answer"]})
        links.append({"sample_id": identity, "case_id": item["case_id"], "arm": item["arm"]})
    pack = {"schema_version": 1, "samples": samples,
        "instructions": "Judge every factual assertion only against its selected citations; assess every required fact and citation. Include optional examples and reasons. Record minimum support offsets and a masking guess. Do not open mapping, model identity, other judgments or aggregate scores before locking.",
        "masking_limits": "Repeated questions and evidence-unit widths may reveal roles. AI review is not human verification."}
    return pack, {"schema_version": 1, "mappings": links}, failure, replay


def prepare(*, root=ROOT):
    output = path(OUTPUT, root)
    if output.exists():
        raise FileExistsError("partial_output_exists")
    pack, mapping, failure, receipt = closed_evidence(root)
    output.mkdir(parents=True, exist_ok=False)
    for name, value in (("review-input", pack), ("mapping", mapping), ("failure-replay", failure), ("receipt", receipt)):
        audit.write_new(output / (name + ".json"), value)
    return receipt


def artifact(name, root):
    return capture(f"{OUTPUT}/{name}.json", root)


def reviewed(pack, receipt, judgments):
    check_flags(receipt)
    parsed = JudgmentFile.model_validate(judgments)
    if (receipt.get("reviewer_id") != REVIEWER or parsed.reviewer_id != REVIEWER
            or REVIEWER in receipt["excluded_reviewer_ids"] or receipt.get("samples") != 14
            or len(pack["samples"]) != 14
            or [j.sample_id for j in parsed.judgments] != [s["sample_id"] for s in pack["samples"]]
            or len({s["sample_id"] for s in pack["samples"]}) != 14):
        raise ValueError("partial_review_role_or_coverage")
    scores = []
    for sample, judgment in zip(pack["samples"], parsed.judgments, strict=True):
        if REVIEWER in {sample["oracle"][k] for k in ("question_author", "oracle_author", "independent_prereviewer")}:
            raise ValueError("partial_review_role_conflict")
        scores.append(score_sample(sample, judgment.model_dump()))
    return scores


def lock(*, reviewer_model, reviewer_effort, root=ROOT):
    """Never read mapping, seed, report, original input/oracle or model identity."""
    output = path(f"{OUTPUT}/judgments-lock.json", root)
    if (reviewer_model, reviewer_effort) != (REVIEW_MODEL, REVIEW_EFFORT):
        raise ValueError("partial_reviewer_runtime_registration")
    if output.exists():
        raise FileExistsError("partial_lock_exists")
    review_raw, review_ref = artifact("review-input", root)
    receipt_raw, receipt_ref = artifact("receipt", root)
    judgment_raw, judgment_ref = artifact("judgments", root)
    receipt = audit.parse(receipt_raw)
    if (receipt.get("plan_sha256") != PLAN_SHA256
            or receipt.get("bindings", {}).get("report", {}).get("sha256") != REPORT_SHA256
            or receipt.get("source_bindings") != source_bindings(root)
            or receipt.get("review_input_sha256") != review_ref["sha256"]):
        raise ValueError("partial_lock_binding")
    reviewed(audit.parse(review_raw), receipt, audit.parse(judgment_raw))
    result = {"schema_version": 1, **FLAGS, "plan_sha256": PLAN_SHA256,
        "review_input_sha256": review_ref["sha256"], "receipt_sha256": receipt_ref["sha256"],
        "judgments_sha256": judgment_ref["sha256"], "reviewer_id": REVIEWER,
        "reviewer_model": reviewer_model, "reviewer_effort": reviewer_effort,
        "reviewer_runtime_evidence": "operator_supplied_actual_accepted_role_settings",
        "locked_at": datetime.now(UTC).isoformat(), "mapping_opened_by_lock": False, "human_review_count": 0}
    audit.write_new(output, result)
    return result


def finalize(*, root=ROOT):
    output = path(f"{OUTPUT}/diagnostic-summary.json", root)
    if output.exists():
        raise FileExistsError("partial_summary_exists")
    # An absent/invalid lock is rejected before original evidence or mapping is opened.
    locked_raw, lock_ref = artifact("judgments-lock", root)
    locked = audit.parse(locked_raw)
    check_flags(locked)
    review_raw, review_ref = artifact("review-input", root)
    receipt_raw, receipt_ref = artifact("receipt", root)
    judgment_raw, judgment_ref = artifact("judgments", root)
    if (locked.get("plan_sha256") != PLAN_SHA256 or locked.get("reviewer_id") != REVIEWER
            or (locked.get("reviewer_model"), locked.get("reviewer_effort")) != (REVIEW_MODEL, REVIEW_EFFORT)
            or locked.get("mapping_opened_by_lock") is not False
            or locked.get("review_input_sha256") != review_ref["sha256"]
            or locked.get("receipt_sha256") != receipt_ref["sha256"]
            or locked.get("judgments_sha256") != judgment_ref["sha256"]):
        raise ValueError("partial_judgments_not_locked")
    pack, receipt = audit.parse(review_raw), audit.parse(receipt_raw)
    scores = reviewed(pack, receipt, audit.parse(judgment_raw))
    expected_pack, expected_mapping, failure, expected_receipt = closed_evidence(root)
    mapping_raw, mapping_ref = artifact("mapping", root)
    _failure_raw, failure_ref = artifact("failure-replay", root)
    if (audit.hashed(expected_pack) != review_ref["sha256"] or audit.hashed(expected_receipt) != receipt_ref["sha256"]
            or audit.hashed(expected_mapping) != mapping_ref["sha256"] or audit.hashed(failure) != failure_ref["sha256"]):
        raise ValueError("partial_artifact_replay")
    links = audit.parse(mapping_raw)["mappings"]
    rows, paired = [], {}
    for score, link in zip(scores, links, strict=True):
        if score["sample_id"] != link["sample_id"]:
            raise ValueError("partial_mapping_order")
        pair = paired.setdefault(link["case_id"], {})
        if link["arm"] in pair:
            raise ValueError("partial_duplicate_pair")
        pair[link["arm"]] = score["full_correct"]
        rows.append({**score, **link})
    if set(paired) != set(CASE_IDS[:7]) or any(set(p) != {"L0", "C2"} for p in paired.values()):
        raise ValueError("partial_pair_coverage")
    counts = {arm: sum(p[arm] for p in paired.values()) for arm in ("L0", "C2")}
    result = {"schema_version": 1, **FLAGS, "status": "completed_partial_diagnostic",
        "plan_sha256": PLAN_SHA256, "report_sha256": REPORT_SHA256, "execution_counts": COUNTS,
        "semantic_full_correct": {"numerator": sum(counts.values()), "denominator": 14},
        "arms": {arm: {"numerator": count, "denominator": 7} for arm, count in counts.items()},
        "complete_pairs": 7, "posthoc_improvements": sum(not p["L0"] and p["C2"] for p in paired.values()),
        "posthoc_regressions": sum(p["L0"] and not p["C2"] for p in paired.values()),
        "eighth_case_operations": {"C2": "language_failure_not_semantically_scored", "L0": "unexecuted"},
        "reviewer_id": REVIEWER, "review_type": "independent_AI_not_human", "human_review_count": 0,
        "reviewer_model": locked["reviewer_model"], "reviewer_effort": locked["reviewer_effort"],
        "model_calls": 0, "tokenizer_calls": 0, "rows": rows,
        "artifacts": {"lock": lock_ref, "receipt": receipt_ref, "review_input": review_ref,
                      "judgments": judgment_ref, "mapping": mapping_ref, "failure_replay": failure_ref},
        "limitations": "Post-hoc seven-pair diagnostic only; language failure and unexecuted response have no semantic score. No full-eight-pair gate, validation permission or service adoption."}
    audit.write_new(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "lock", "finalize"))
    parser.add_argument("--reviewer-model")
    parser.add_argument("--reviewer-effort")
    args = parser.parse_args()
    try:
        if args.operation == "lock":
            result = lock(reviewer_model=args.reviewer_model, reviewer_effort=args.reviewer_effort)
        else:
            if args.reviewer_model is not None or args.reviewer_effort is not None:
                raise ValueError("partial_unexpected_reviewer_arguments")
            result = {"prepare": prepare, "finalize": finalize}[args.operation]()
        print(json.dumps({"purpose": result["purpose"], "selected": False, "validation_eligible": False}))
    except Exception:  # noqa: BLE001 - never emit private source, questions or judgments
        parser.exit(1, "partial_audit_failed\n")


if __name__ == "__main__":
    main()
