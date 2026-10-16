"""C4 once-only single-call quality execution; no extra resource or repair calls."""
from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import math
import re
import time
from pathlib import Path

from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_answer_thinking import CANDIDATE_ID, grounded_answer_thinking, prepare_answer
from doctrail.meeting_thinking_quality import QualityThinkingGenerator, validate_quality_response
from doctrail.meeting_thinking_review import COUNTS, validate_attestation
from doctrail.meeting_thinking_transport import PREAMBLE, request_body
from scripts import prepare_meeting_thinking_inputs as prep
from scripts.probe_meeting_blocks_resources import owned_watchdog, rss_samples
from scripts.probe_meeting_thinking_compat_resources import drain_pass
from scripts.serve_meeting_thinking_compat import cleanup_owned, start_llama

ROOT = prep.ROOT
PLAN = "data/evaluation/meetings-c4-quality-execution-plan-v1.json"
LEDGER = ".local/meetings-c4-quality-ledger-v1.json"
EXCLUDED = {"/root", "/root/c2_comparison_runner", "/root/bounded_thinking_transport",
    "/root/free_qa_candidate_review", "/root/requirements_candidate", "/root/knowledge_recovery_review"}
MATERIAL = {"draft", "oracle", "source_freeze", "item_freeze"}


def numeric(value, limit):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= limit


def failure(error):
    code = getattr(error, "code", None) if isinstance(error, (GenerationError, WorkerError)) else None
    if type(error) is ValueError and re.fullmatch(r"c4_[a-z0-9_]{1,90}", str(error)):
        code = str(error)
    if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9_]{1,100}", code):
        code = "quality_failed_closed"
    return {"code": code, "type": type(error).__name__}


def paths(plan, root=ROOT):
    if (plan.get("candidate") != CANDIDATE_ID or type(plan.get("schema_version")) is not int or plan["schema_version"] != 1
            or set(plan.get("phases", {})) != set(COUNTS) or set(plan.get("audit", {})) != set(COUNTS)
            or not isinstance(plan.get("excluded_roles"), list) or any(not isinstance(r, str) or not r for r in plan["excluded_roles"])
            or len(set(plan["excluded_roles"])) != len(plan["excluded_roles"]) or not EXCLUDED <= set(plan["excluded_roles"])):
        raise ValueError("c4_plan_contract")
    protected, judges = [LEDGER, PLAN, prep.CI_RECEIPT, prep.TOOLCHAIN_FREEZE], []
    for phase in COUNTS:
        spec, audit = plan["phases"][phase], plan["audit"][phase]
        if set(spec) != MATERIAL | {"input", "preparation_receipt", "output_dir", "case_ids"} or set(audit) != {"reviewer_id", "seed", "attestation", "output_dir"}:
            raise ValueError("c4_phase_registration")
        if spec["case_ids"] != [f"C4-{'CAL' if phase == 'calibration' else 'VAL'}-{n:02d}" for n in range(1, COUNTS[phase] + 1)]:
            raise ValueError("c4_registered_cases")
        for role in MATERIAL | {"input", "preparation_receipt"}:
            prep.ref(spec[role], root)
            prep.phase_path(spec[role]["file"], phase, root)
            protected.append(spec[role]["file"])
        for role, filename in (("input", "input.json"), ("preparation_receipt", "receipt.json")):
            if spec[role]["file"] not in {f".local/meetings-c4-{phase}-prepared-v1/{filename}",
                                         f"data/evaluation/meetings-c4-{phase}-inputs-v1/{filename}"}:
                raise ValueError("c4_prepared_path")
        for role, filename in (("seed", "seed.bin"), ("attestation", "attestation.json")):
            prep.ref(audit[role], root)
            if audit[role]["file"] != f"data/evaluation/meetings-c4-review-metadata-v1/{phase}/{filename}":
                raise ValueError("c4_review_metadata_path")
            protected.append(audit[role]["file"])
        if (spec["output_dir"] != f".local/meetings-c4-quality-{phase}-v1"
                or audit["output_dir"] != f".local/meetings-c4-audit-{phase}-v1"
                or not isinstance(audit["reviewer_id"], str) or not audit["reviewer_id"] or audit["reviewer_id"] in plan["excluded_roles"]):
            raise ValueError("c4_role_or_output")
        protected += [spec["output_dir"], audit["output_dir"]]
        judges.append(audit["reviewer_id"])
    if len(set(judges)) != 2:
        raise ValueError("c4_judges_not_distinct")
    prep.separate(protected, root)


def metadata(plan, snapshots, *, git=prep.committed):
    paths(plan, snapshots.root)
    code, ci = prep.code_contract(snapshots, git=git)
    if (plan.get("bound_files") != code or plan.get("code_freeze") != {"file": prep.TOOLCHAIN_FREEZE, "sha256": snapshots.hashes[prep.TOOLCHAIN_FREEZE]}
            or plan.get("protocol_sha256") != prep.PINNED[prep.PROTOCOL]):
        raise ValueError("c4_plan_source_binding")
    cutoff = prep.now()
    for phase in COUNTS:
        audit, spec = plan["audit"][phase], plan["phases"][phase]
        seed = snapshots.get(audit["seed"]["file"], audit["seed"]["sha256"])
        if not 32 <= len(seed) <= 128:
            raise ValueError("c4_seed_length")
        validate_attestation(snapshots.read(audit["attestation"]), audit["reviewer_id"], plan["excluded_roles"], pack_opened_at=cutoff)
        receipt = snapshots.read(spec["preparation_receipt"])
        if (receipt.get("status") != "passed" or receipt.get("candidate") != CANDIDATE_ID or receipt.get("phase") != phase
                or receipt.get("references") != {k: spec[k] for k in MATERIAL} or receipt.get("input_sha256") != spec["input"]["sha256"]
                or receipt.get("bound_files") != code or receipt.get("payloads_preserved") is not True
                or receipt.get("errors") != [] or type(receipt.get("tokenizer_loads")) is not int or receipt["tokenizer_loads"] != 1
                or any(type(receipt.get(k)) is not int or receipt[k] != 0 for k in ("model_calls", "native_calls", "downloads"))
                or not receipt.get("excluded_authors") or not set(receipt["excluded_authors"]) <= set(plan["excluded_roles"])
                or [r.get("id") for r in receipt.get("cases", [])] != spec["case_ids"]
                or any(type(r.get("input_tokens")) is not int or not 0 < r["input_tokens"] <= 5120 or r.get("error") is not None for r in receipt["cases"])
                or receipt.get("summary") != {"planned": COUNTS[phase], "measured": COUNTS[phase], "failed": 0}):
            raise ValueError("c4_preparation_binding")
        prep._tokenizer_metadata(receipt["tokenizer"])
        for reference in [plan["code_freeze"], *(spec[k] for k in MATERIAL)]:
            if receipt.get("snapshots", {}).get(reference["file"]) != reference["sha256"]:
                raise ValueError("c4_preparation_snapshot_binding")
    git(snapshots.hashes, root=snapshots.root)
    return code, ci


def gate(plan, phase, root=ROOT, *, git=prep.committed):
    if phase == "validation":
        from scripts.audit_meeting_thinking_quality import verify_calibration_gate
        return verify_calibration_gate(plan, root=root, git=git)
    return None


def check(phase, *, root=ROOT, git=prep.committed):
    if git is prep.committed:
        git = prep.GitProof(root)
    if phase not in COUNTS:
        raise ValueError("c4_phase")
    snapshots = prep.Snapshots(root)
    plan = snapshots.json(PLAN)
    paths(plan, root)
    selected = gate(plan, phase, root, git=git)  # Before either held-out body or metadata parse.
    code, ci = metadata(plan, snapshots, git=git)
    spec = plan["phases"][phase]
    draft, oracles, authors = prep.load_material(phase, {k: spec[k] for k in MATERIAL}, snapshots, code, ci, git=git)
    if not set(authors) <= set(plan["excluded_roles"]):
        raise ValueError("c4_original_author_exclusion")
    inputs, receipt = snapshots.read(spec["input"]), snapshots.read(spec["preparation_receipt"])
    if (set(inputs) != {"schema_version", "phase", "cases"}
            or type(inputs["schema_version"]) is not int or inputs["schema_version"] != 1 or inputs["phase"] != phase
            or [c.get("id") for c in inputs["cases"]] != spec["case_ids"]):
        raise ValueError("c4_input_contract")
    for original, case, row in zip(draft["cases"], inputs["cases"], receipt["cases"], strict=True):
        if (set(case) != set(original) | {"official_input_tokens", "prompt_sha256"}
                or prep.canonical({k: case[k] for k in original}) != prep.canonical(original)
                or type(case["official_input_tokens"]) is not int or case["official_input_tokens"] != row["input_tokens"]
                or case["prompt_sha256"] != row["prompt_sha256"] or row["payload_sha256"] != prep.sha(prep.canonical(case["payload"]))):
            raise ValueError("c4_input_payload_changed")
        built = prepare_answer(case["payload"], case["response_language"])
        if row["messages_sha256"] != prep.sha(prep.canonical(built.messages)) or row["schema_sha256"] != prep.sha(prep.canonical(built.schema)):
            raise ValueError("c4_prompt_schema_changed")
    snapshots.unchanged()
    git(snapshots.hashes, root=root)
    return {"root": Path(root), "phase": phase, "plan": plan, "snapshots": snapshots, "cases": inputs["cases"],
            "oracles": oracles, "gate": selected, "output": spec["output_dir"], "git": git}


def verify(prepared):
    original = prepared["snapshots"]
    # Read only registered metadata and prior calibration gate before source snapshots.
    fresh = prep.Snapshots(prepared["root"])
    plan = fresh.json(PLAN)
    paths(plan, fresh.root)
    selected = gate(plan, prepared["phase"], fresh.root, git=prepared["git"])
    metadata(plan, fresh, git=prepared["git"])
    if prep.canonical(plan) != prep.canonical(prepared["plan"]) or selected != prepared["gate"]:
        raise ValueError("c4_plan_or_gate_changed")
    spec = plan["phases"][prepared["phase"]]
    if prep.canonical(original.read(spec["input"])["cases"]) != prep.canonical(prepared["cases"]):
        raise ValueError("c4_memory_input_changed")
    original.unchanged()
    prepared["git"](original.hashes, root=fresh.root)


def trace_replay(case, row):
    built = prepare_answer(case["payload"], case["response_language"])
    prompt, tokens = row["prompt"], row["input_token_ids"]
    if (row.get("id") != case["id"] or row.get("passed") is not True or row.get("dispatch_started") is not True
            or type(row.get("completion_attempts")) is not int or row["completion_attempts"] != 1
            or type(row.get("http_send_attempts")) is not int or row["http_send_attempts"] != 1
            or "error" in row or not numeric(row.get("request_seconds"), 90)
            or not isinstance(prompt, str) or not prompt.endswith(PREAMBLE) or prep.sha(prompt.encode()) != case["prompt_sha256"]
            or not isinstance(tokens, list) or not tokens or any(type(t) is not int or t < 0 for t in tokens)
            or len(tokens) != case["official_input_tokens"] or prep.canonical(row["request"]) != prep.canonical(request_body(built.messages, built.schema))
            or row.get("watchdog", {}).get("watchdog_fired") is not False or row["watchdog"].get("watchdog_joined") is not True):
        raise ValueError("c4_native_trace")
    expected_pairs = {"apply_template": ({"messages": built.messages, "chat_template_kwargs": {"enable_thinking": True}}, {"prompt": prompt}),
        "input_tokenize": ({"content": prompt, "add_special": False, "parse_special": True, "with_pieces": False}, {"tokens": tokens})}
    for key, (request, response) in expected_pairs.items():
        if prep.canonical(row.get(key + "_request")) != prep.canonical(request) or prep.canonical(row.get(key + "_response")) != prep.canonical(response) or type(row.get(key + "_http_status")) is not int or row[key + "_http_status"] != 200:
            raise ValueError("c4_template_tokenizer_trace")
    if row.get("native_request") != row["request"] or row.get("native_http_status") != 200 or row.get("native_response") != row["response"]:
        raise ValueError("c4_native_http_trace")
    expected = validate_quality_response(row["response"], prompt=prompt, input_tokens=len(tokens))
    expected["telemetry"].update(candidate_id=CANDIDATE_ID, semantic_support_verified=False,
        question_completeness_verified=False, language_guard="script_presence_only")
    final = row["final_token_ids"]
    if (not isinstance(final, list) or not 0 < len(final) <= 384 or any(type(t) is not int or t < 0 for t in final)
            or row.get("final_tokenize_request") != {"content": expected["content"], "add_special": False, "parse_special": False, "with_pieces": False}
            or row.get("final_tokenize_response") != {"tokens": final} or row.get("final_tokenize_http_status") != 200):
        raise ValueError("c4_final_token_trace")
    completion = row["result"]["completion"]
    if (any(prep.canonical(completion.get(k)) != prep.canonical(v) for k, v in expected.items()) or completion.get("input_tokens") != len(tokens)
            or type(completion.get("final_retokenized_tokens")) is not int or completion["final_retokenized_tokens"] != len(final)
            or not numeric(completion.get("elapsed_seconds"), row["request_seconds"])):
        raise ValueError("c4_result_trace")
    answer = grounded_answer_thinking(expected["content"], built.catalog, built.request.contexts, case["response_language"])
    if prep.canonical(answer) != prep.canonical(row["result"]["answer"]):
        raise ValueError("c4_grounding_replay")
    return answer


EVENT_KEYS = ("prepared", "apply_template_request", "apply_template_http_status", "apply_template_response",
    "input_tokenize_request", "input_tokenize_http_status", "input_tokenize_response", "native_request",
    "native_post_started", "native_http_status", "native_response", "response", "final_tokenize_request",
    "final_tokenize_http_status", "final_tokenize_response", "final_token_ids", "result")


def observation_replay(prepared, report):
    """Reconstruct every successful trace from contiguous immutable event bytes."""
    snapshots = prep.Snapshots(prepared["root"])
    sequence, counters = 0, {"http_send_attempts": 0, "native_responses_received": 0, "contract_valid_answers": 0}
    for row in report["calls"]:
        references = row.get("observations", [])
        if len(references) != len(EVENT_KEYS):
            raise ValueError("c4_event_coverage")
        for key, reference in zip(EVENT_KEYS, references, strict=True):
            sequence += 1
            if reference.get("file") != f'{prepared["output"]}/trace/{sequence:06d}.json':
                raise ValueError("c4_event_order")
            event = snapshots.read(reference)
            expected = {"sequence": sequence, "id": row["id"], "key": key, "value": row.get(key)}
            if prep.canonical(event) != prep.canonical(expected):
                raise ValueError("c4_event_value")
        if row.get("native_post_started") is not True or "native_post_aborted" in row:
            raise ValueError("c4_event_send")
        counters["http_send_attempts"] += 1
        counters["native_responses_received"] += 1
        counters["contract_valid_answers"] += 1
    directory = prep.path(prepared["output"] + "/trace", prepared["root"])
    if sorted(p.name for p in directory.iterdir()) != [f"{n:06d}.json" for n in range(1, sequence + 1)]:
        raise ValueError("c4_event_extra")
    if any(type(report.get(k)) is not int or report[k] != value for k, value in counters.items()):
        raise ValueError("c4_event_counters")
    snapshots.unchanged()
    return snapshots.hashes


def report_replay(prepared, report):
    phase, cases, plan = prepared["phase"], prepared["cases"], prepared["plan"]
    prefix = [] if phase == "calibration" else prepared["gate"]["ledger"]
    resource_identity = prepared["snapshots"].json(prep.RESOURCE_REPORT)["identity"] | {"candidate_id": CANDIDATE_ID}
    if (type(report.get("schema_version")) is not int or report["schema_version"] != 1
            or report.get("candidate") != CANDIDATE_ID or report.get("phase") != phase or report.get("status") != "completed"
            or report.get("plan_sha256") != prepared["snapshots"].hashes[PLAN]
            or report.get("bound_files") != plan["bound_files"] or report.get("sources_unchanged") is not True
            or report.get("metadata_recovery") is not True or type(report.get("restarts")) is not int or report["restarts"] != 1
            or report.get("unexecuted") != [] or any(k in report for k in ("error", "source_error", "first_failure", "cleanup_or_later_failure", "final_save_failure"))
            or [r.get("id") for r in report.get("calls", [])] != [c["id"] for c in cases]
            or any(type(report.get(k)) is not int or report[k] != 0 for k in ("retries", "warmups", "repair_calls", "resource_calls", "recovery_native_calls"))
            or len(report.get("cleanup", [])) != 2 or not all(drain_pass(c) for c in report["cleanup"])
            or not numeric(report.get("elapsed_seconds"), 1200) or not numeric(report.get("last_request_through_cleanup_seconds"), 120)
            or report.get("recovered_identity") != report.get("identity")
            or prep.canonical(report.get("identity")) != prep.canonical(resource_identity)
            or report.get("gate") != prepared["gate"]
            or any(report.get(k, {}).get("watchdog_fired") is not False or report[k].get("watchdog_joined") is not True for k in ("phase_watchdog", "recovery_watchdog"))):
        raise ValueError("c4_report_not_complete")
    expected = prefix + [{"phase": phase, "id": row["id"], "request_sha256": prep.sha(prep.canonical(row["request"]))} for row in report["calls"]]
    if (report.get("ledger") != expected or len(expected) > 14
            or any(type(report.get(k)) is not int or report[k] != len(cases)
                   for k in ("http_send_attempts", "native_responses_received", "contract_valid_answers"))):
        raise ValueError("c4_ledger_binding")
    observation_replay(prepared, report)
    return [trace_replay(case, row) for case, row in zip(cases, report["calls"], strict=True)]


def run(prepared, *, factory=start_llama, generator_factory=QualityThinkingGenerator):
    verify(prepared)
    root, output, phase = prepared["root"], prepared["output"], prepared["phase"]
    prefix = [] if phase == "calibration" else prepared["gate"]["ledger"]
    if phase == "validation" and prep.Snapshots(root).json(LEDGER) != prefix:
        raise ValueError("c4_ledger_drift")
    prep.path(output, root).mkdir(parents=True, exist_ok=False)
    prep.path(output + "/trace", root).mkdir(exist_ok=False)
    event_sequence = 0
    if phase == "calibration":
        prep.write_new(LEDGER, [], root)
    started, last_request = time.monotonic(), None
    report = {"schema_version": 1, "candidate": CANDIDATE_ID, "phase": phase,
        "plan_sha256": prepared["snapshots"].hashes[PLAN], "bound_files": prepared["plan"]["bound_files"],
        "status": "running", "calls": [], "cleanup": [], "ledger": list(prefix), "gate": prepared["gate"],
        "unexecuted": [c["id"] for c in prepared["cases"]], "http_send_attempts": 0, "sources_unchanged": False,
        "native_responses_received": 0, "contract_valid_answers": 0,
        "send_count_scope": "http_send_attempts_not_server_receipt_or_generation_completion",
        "metadata_recovery": False, "restarts": 0, "retries": 0, "warmups": 0, "repair_calls": 0, "resource_calls": 0, "recovery_native_calls": 0}
    def save():
        prep.replace(output + "/report.json", report, root)
    save()
    try:
        cleanup = {}
        report["cleanup"].append(cleanup)
        with factory(log_dir=prep.path(output + "/initial", root), phase_deadline=started + 1200, telemetry=cleanup) as service:
            generator = generator_factory(service.url, service.token, service.manifest)
            try:
                with owned_watchdog(service.process, report.setdefault("phase_watchdog", {}), max(.01, started + 1200 - time.monotonic())):
                    generator.load()
                    report["identity"] = generator.public_metadata()
                    for case in prepared["cases"]:
                        verify(prepared)  # Before semantic DTO/prompt construction for this request.
                        if service.drain.emitted_bytes or service.drain.read_errors:
                            raise ValueError("c4_native_diagnostics")
                        row = {"id": case["id"], "passed": False, "dispatch_started": False,
                               "completion_attempts": 0, "http_send_attempts": 0, "observations": []}
                        report["calls"].append(row)
                        report["unexecuted"].remove(case["id"])
                        last_request = time.monotonic()
                        def before(prompt, tokens, payload, row=row, case=case):
                            verify(prepared)
                            if (len(tokens) != case["official_input_tokens"] or prep.sha(prompt.encode()) != case["prompt_sha256"]
                                    or len(report["ledger"]) >= 14 or prep.Snapshots(root).json(LEDGER) != report["ledger"]):
                                raise ValueError("c4_dispatch_binding")
                            row.update(prompt=prompt, input_token_ids=tokens, request=payload, dispatch_started=True, completion_attempts=1)
                            report["ledger"].append({"phase": phase, "id": case["id"], "request_sha256": prep.sha(prep.canonical(payload))})
                            prep.replace(LEDGER, report["ledger"], root)
                            save()  # Durable started receipt exists before the HTTP send.
                        def observe(key, value, row=row):
                            nonlocal event_sequence
                            event_sequence += 1
                            if key.endswith("_error") or key == "native_post_aborted":
                                code = value.get("code") if isinstance(value, dict) else None
                                if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9_]{1,100}", code):
                                    code = "quality_failed_closed"
                                report.setdefault("first_failure", {"code": code, "type": "GenerationError"})
                            if key == "native_post_aborted":
                                row["http_send_attempts"] -= 1
                                report["http_send_attempts"] -= 1
                            event = {"sequence": event_sequence, "id": row["id"], "key": key, "value": copy.deepcopy(value)}
                            name = f"{output}/trace/{event_sequence:06d}.json"
                            raw = prep.encoded(event)
                            try:
                                prep.write_new(name, raw, root)
                            except Exception as error:
                                row["archival_failure"] = failure(error)
                                report.setdefault("first_failure", row["archival_failure"])
                                raise
                            row["observations"].append({"file": name, "sha256": prep.sha(raw)})
                            row[key] = copy.deepcopy(value)
                            if key == "native_post_started":
                                row["http_send_attempts"] += 1
                                report["http_send_attempts"] += 1
                            elif key == "native_response":
                                report["native_responses_received"] += 1
                        try:
                            with owned_watchdog(service.process, row.setdefault("watchdog", {}), 90), rss_samples(service.process, row.setdefault("memory", {})):
                                result = generator.answer(case["payload"], case["response_language"], before_dispatch=before, observe=observe)
                            row.update(result=dataclasses.asdict(result), request_seconds=time.monotonic() - last_request, passed=True)
                            trace_replay(case, row)
                            report["contract_valid_answers"] += 1
                            save()
                        except Exception as error:
                            row.update(passed=False, error=failure(error), request_seconds=time.monotonic() - last_request)
                            report.setdefault("first_failure", row["error"])
                            raise
            finally:
                generator.close()
                cleanup_owned(service.process, service.drain, service.cleanup)
                if last_request is not None:
                    report["last_request_through_cleanup_seconds"] = time.monotonic() - last_request
        if not drain_pass(cleanup):
            raise ValueError("c4_cleanup_or_drain")
        verify(prepared)
        report["restarts"] = 1
        recovery = {}
        report["cleanup"].append(recovery)
        with factory(log_dir=prep.path(output + "/recovery", root), phase_deadline=started + 1200, telemetry=recovery) as service:
            generator = generator_factory(service.url, service.token, service.manifest)
            try:
                with owned_watchdog(service.process, report.setdefault("recovery_watchdog", {}), max(.01, started + 1200 - time.monotonic())):
                    generator.load()
                    report["recovered_identity"] = generator.public_metadata()
                    report["metadata_recovery"] = report["identity"] == report["recovered_identity"]
            finally:
                generator.close()
                cleanup_owned(service.process, service.drain, service.cleanup)
        verify(prepared)
        report["sources_unchanged"] = True
        report["status"] = "completed"
        report["elapsed_seconds"] = time.monotonic() - started
        report_replay(prepared, report)
    except Exception as error:  # noqa: BLE001 - retain first failure, never expose body/reasoning in console
        observed = failure(error)
        report.setdefault("first_failure", observed)
        if report["first_failure"] != observed:
            report["cleanup_or_later_failure"] = observed
        report.update(status="failed_closed", error=report["first_failure"])
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        if report["status"] == "completed" and not numeric(report["elapsed_seconds"], 1200):
            report.update(status="failed_closed", error={"code": "c4_phase_deadline", "type": "ValueError"})
        try:
            save()
        except Exception as error:  # noqa: BLE001 - preserve reporting failure without masking request cause
            report.setdefault("first_failure", failure(error))
            report.update(status="failed_closed", error=report["first_failure"], final_save_failure=failure(error))
            # A distinct exclusive fallback preserves the first cause without retrying a send or overwrite.
            prep.write_new(output + "/failed-final-save.json", report, root)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "run"))
    parser.add_argument("--phase", required=True, choices=COUNTS)
    args = parser.parse_args(argv)
    try:
        prepared = check(args.phase)
        result = {"status": "checked"} if args.operation == "check" else run(prepared)
        print(json.dumps({"status": result["status"]}))
        return 0 if result["status"] in {"checked", "completed"} else 1
    except Exception:  # noqa: BLE001
        print('{"status":"failed_closed"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
