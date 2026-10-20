"""C6 once-only single-call quality execution; no extra resource or repair calls."""
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
from doctrail.meeting_answer_thinking import grounded_answer_thinking, prepare_answer
from doctrail.meeting_c6_review import COUNTS, validate_attestation
from doctrail.meeting_thinking_quality import QualityThinkingGenerator, validate_quality_response
from doctrail.meeting_thinking_transport import PREAMBLE, request_body
from scripts import prepare_meeting_c6_inputs as prep
from scripts.prepare_meeting_budget_inputs import PreparationError
from scripts.probe_meeting_blocks_resources import owned_watchdog
from scripts.probe_meeting_gpu_placement import bounded_rss as rss_samples
from scripts.probe_meeting_thinking_compat_resources import drain_pass
from scripts.serve_meeting_gpu_placement import normalized_argv
from scripts.serve_meeting_gpu_placement import start_llama as placement_service
from scripts.serve_meeting_thinking_compat import cleanup_owned

CANDIDATE_ID = prep.CANDIDATE_ID
REUSED_POLICY_ID = prep.REUSED_POLICY_ID
ROOT = prep.ROOT
PLAN = "data/evaluation/meetings-c6-execution-plan-v1.json"
LEDGER = ".local/meetings-c6-quality-ledger-v1.json"
EXCLUDED = {"/root", "/root/c2_comparison_runner", "/root/bounded_thinking_transport",
    "/root/free_qa_candidate_review", "/root/host_proof_profile", "/root/meeting_navigation_audit",
    "/root/c5_persistence_recovery", "/root/c5_persistence_review",
    "/root/requirements_candidate", "/root/knowledge_recovery_review"}
MATERIAL = {"draft", "oracle", "source_freeze", "item_freeze"}


REVIEW_REGISTRATION = "data/evaluation/meetings-c6-review-registration-v1.json"


def start_llama(*, service=placement_service, **kwargs):
    """Fixed C6 setting. No GPU option or policy ID substitution."""
    return service(gpu_layers=28, **kwargs)


class C6Generator(QualityThinkingGenerator):
    outer_deadline = None

    def _remaining(self, deadline=None):
        deadlines = [d for d in (deadline, self._deadline, self.outer_deadline) if d is not None]
        return super()._remaining(min(deadlines) if deadlines else None)


def numeric(value, limit):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= limit


def failure(error):
    code = getattr(error, "code", None) if isinstance(error, (GenerationError, WorkerError)) else None
    if type(error) is ValueError and re.fullmatch(r"c6_[a-z0-9_]{1,90}", str(error)):
        code = str(error)
    if isinstance(error, PreparationError) and str(error) in {
            "preparation_file_limit", "preparation_snapshot_changed", "preparation_stream_contract"}:
        code = str(error)
    if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9_]{1,100}", code):
        code = "quality_failed_closed"
    return {"code": code, "type": type(error).__name__}


def paths(plan, root=ROOT):
    if (plan.get("candidate") != CANDIDATE_ID or type(plan.get("schema_version")) is not int or plan["schema_version"] != 1
            or set(plan.get("phases", {})) != set(COUNTS) or set(plan.get("audit", {})) != set(COUNTS)
            or not isinstance(plan.get("excluded_roles"), list) or any(not isinstance(r, str) or not r for r in plan["excluded_roles"])
            or len(set(plan["excluded_roles"])) != len(plan["excluded_roles"]) or not EXCLUDED <= set(plan["excluded_roles"])):
        raise ValueError("c6_plan_contract")
    if plan.get("reused_policy_id") != REUSED_POLICY_ID or plan.get("gpu_layers_requested") != 28:
        raise ValueError("c6_policy_or_placement")
    protected, judges = [LEDGER, PLAN, prep.CI_RECEIPT, prep.TOOLCHAIN_FREEZE], []
    for key, name in (("role_registration", prep.ROLE_REGISTRATION), ("review_registration", REVIEW_REGISTRATION)):
        prep.ref(plan[key], root)
        if plan[key]["file"] != name:
            raise ValueError("c6_actual_registration_path")
        protected.append(name)
    for phase in COUNTS:
        spec, audit = plan["phases"][phase], plan["audit"][phase]
        if set(spec) != MATERIAL | {"input", "preparation_receipt", "output_dir", "case_ids"} or set(audit) != {"reviewer_id", "seed", "attestation", "output_dir"}:
            raise ValueError("c6_phase_registration")
        if spec["case_ids"] != [f"C6-{'CAL' if phase == 'calibration' else 'VAL'}-{n:02d}" for n in range(1, COUNTS[phase] + 1)]:
            raise ValueError("c6_registered_cases")
        for role in MATERIAL | {"input", "preparation_receipt"}:
            prep.ref(spec[role], root)
            prep.phase_path(spec[role]["file"], phase, root)
            protected.append(spec[role]["file"])
        for role, filename in (("input", "input.json"), ("preparation_receipt", "receipt.json")):
            if spec[role]["file"] not in {f".local/meetings-c6-{phase}-prepared-v1/{filename}",
                                         f"data/evaluation/meetings-c6-{phase}-inputs-v1/{filename}"}:
                raise ValueError("c6_prepared_path")
        for role, filename in (("seed", "seed.bin"), ("attestation", "attestation.json")):
            prep.ref(audit[role], root)
            if audit[role]["file"] != f"data/evaluation/meetings-c6-review-metadata-v1/{phase}/{filename}":
                raise ValueError("c6_review_metadata_path")
            protected.append(audit[role]["file"])
        if (spec["output_dir"] != f".local/meetings-c6-quality-{phase}-v1"
                or audit["output_dir"] != f".local/meetings-c6-audit-{phase}-v1"
                or not isinstance(audit["reviewer_id"], str) or not audit["reviewer_id"] or audit["reviewer_id"] in plan["excluded_roles"]):
            raise ValueError("c6_role_or_output")
        protected += [spec["output_dir"], audit["output_dir"]]
        judges.append(audit["reviewer_id"])
    if len(set(judges)) != 2:
        raise ValueError("c6_judges_not_distinct")
    prep.separate(protected, root)


def metadata(plan, snapshots, *, git=prep.committed, contract=prep.code_contract):
    paths(plan, snapshots.root)
    code, ci = contract(snapshots, git=git)
    if (plan.get("bound_files") != code or plan.get("code_freeze") != {"file": prep.TOOLCHAIN_FREEZE, "sha256": snapshots.hashes[prep.TOOLCHAIN_FREEZE]}
            or plan.get("protocol_sha256") != prep.PINNED[prep.PROTOCOL]):
        raise ValueError("c6_plan_source_binding")
    cutoff = prep.now()
    git([PLAN, prep.ROLE_REGISTRATION, REVIEW_REGISTRATION], root=snapshots.root)
    registration = snapshots.read(plan["review_registration"])
    snapshots.read(plan["role_registration"])
    judges = registration.get("judges", [])
    if (registration.get("candidate_id") != CANDIDATE_ID or registration.get("schema_version") != 1
            or len(judges) != 2 or {r.get("phase") for r in judges} != set(COUNTS)):
        raise ValueError("c6_judge_registration")
    for phase in COUNTS:
        audit, spec = plan["audit"][phase], plan["phases"][phase]
        roles = prep.role_contract(snapshots, phase, git=git)
        if not set(roles.values()) <= set(plan["excluded_roles"]):
            raise ValueError("c6_actual_role_exclusion")
        judge = next(r for r in judges if r["phase"] == phase)
        if (judge.get("reviewer_id") != audit["reviewer_id"] or judge.get("accepted") is not True
                or judge.get("actual_model") != "gpt-6-astra" or judge.get("actual_effort") != "xhigh"
                or judge.get("attestation") != audit["attestation"] or judge.get("seed") != audit["seed"]):
            raise ValueError("c6_actual_judge_acceptance")
        seed = snapshots.get(audit["seed"]["file"], audit["seed"]["sha256"])
        if len(seed) != 64:
            raise ValueError("c6_seed_length")
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
            raise ValueError("c6_preparation_binding")
        prep._tokenizer_metadata(receipt["tokenizer"])
        for reference in [plan["code_freeze"], *(spec[k] for k in MATERIAL)]:
            if receipt.get("snapshots", {}).get(reference["file"]) != reference["sha256"]:
                raise ValueError("c6_preparation_snapshot_binding")
    git(snapshots.hashes, root=snapshots.root)
    return code, ci


def gate(plan, phase, root=ROOT, *, git=prep.committed, contract=prep.code_contract, reader=prep.snapshot):
    if phase == "validation":
        from scripts.audit_meeting_c6_quality import verify_calibration_gate
        return verify_calibration_gate(plan, root=root, git=git, contract=contract, reader=reader)
    return None


def check(phase, *, root=ROOT, git=prep.committed, contract=prep.code_contract,
          reader=prep.snapshot, material=prep.load_material):
    meter = prep.Meter()
    if git is prep.committed:
        git = prep.GitProof(root, meter=meter, reader=reader)
    if phase not in COUNTS:
        raise ValueError("c6_phase")
    snapshots = prep.Snapshots(root, meter=meter, reader=reader)
    plan = snapshots.json(PLAN)
    paths(plan, root)
    selected = gate(plan, phase, root, git=git, contract=contract, reader=reader)  # Before held-out metadata/body.
    code, ci = metadata(plan, snapshots, git=git, contract=contract)
    spec = plan["phases"][phase]
    draft, oracles, authors = material(phase, {k: spec[k] for k in MATERIAL}, snapshots, code, ci, git=git)
    if not set(authors) <= set(plan["excluded_roles"]):
        raise ValueError("c6_original_author_exclusion")
    inputs, receipt = snapshots.read(spec["input"]), snapshots.read(spec["preparation_receipt"])
    if (set(inputs) != {"schema_version", "phase", "cases"}
            or type(inputs["schema_version"]) is not int or inputs["schema_version"] != 1 or inputs["phase"] != phase
            or [c.get("id") for c in inputs["cases"]] != spec["case_ids"]):
        raise ValueError("c6_input_contract")
    for original, case, row in zip(draft["cases"], inputs["cases"], receipt["cases"], strict=True):
        if (set(case) != set(original) | {"official_input_tokens", "prompt_sha256"}
                or prep.canonical({k: case[k] for k in original}) != prep.canonical(original)
                or type(case["official_input_tokens"]) is not int or case["official_input_tokens"] != row["input_tokens"]
                or case["prompt_sha256"] != row["prompt_sha256"] or row["payload_sha256"] != prep.sha(prep.canonical(case["payload"]))):
            raise ValueError("c6_input_payload_changed")
        built = prepare_answer(case["payload"], case["response_language"])
        if row["messages_sha256"] != prep.sha(prep.canonical(built.messages)) or row["schema_sha256"] != prep.sha(prep.canonical(built.schema)):
            raise ValueError("c6_prompt_schema_changed")
    snapshots.unchanged()
    git(snapshots.hashes, root=root)
    return {"root": Path(root), "phase": phase, "plan": plan, "snapshots": snapshots, "cases": inputs["cases"],
            "oracles": oracles, "gate": selected, "output": spec["output_dir"], "git": git,
            "contract": contract, "reader": reader}


def verify(prepared):
    original = prepared["snapshots"]
    # Read only registered metadata and prior calibration gate before source snapshots.
    fresh = prep.Snapshots(prepared["root"], meter=original.meter, reader=prepared["reader"])
    plan = fresh.json(PLAN)
    paths(plan, fresh.root)
    selected = gate(plan, prepared["phase"], fresh.root, git=prepared["git"],
                    contract=prepared["contract"], reader=prepared["reader"])
    metadata(plan, fresh, git=prepared["git"], contract=prepared["contract"])
    if prep.canonical(plan) != prep.canonical(prepared["plan"]) or selected != prepared["gate"]:
        raise ValueError("c6_plan_or_gate_changed")
    spec = plan["phases"][prepared["phase"]]
    if prep.canonical(original.read(spec["input"])["cases"]) != prep.canonical(prepared["cases"]):
        raise ValueError("c6_memory_input_changed")
    original.unchanged()
    prepared["git"](original.hashes, root=fresh.root)


def trace_replay(case, row, *, check_cleanup=True):
    built = prepare_answer(case["payload"], case["response_language"])
    prompt, tokens = row["prompt"], row["input_token_ids"]
    if (row.get("id") != case["id"] or row.get("passed") is not True or row.get("dispatch_started") is not True
            or type(row.get("completion_attempts")) is not int or row["completion_attempts"] != 1
            or type(row.get("http_send_attempts")) is not int or row["http_send_attempts"] != 1
            or "error" in row or not numeric(row.get("request_seconds"), 90)
            or not isinstance(prompt, str) or not prompt.endswith(PREAMBLE) or prep.sha(prompt.encode()) != case["prompt_sha256"]
            or not isinstance(tokens, list) or not tokens or any(type(t) is not int or t < 0 for t in tokens)
            or len(tokens) != case["official_input_tokens"] or prep.canonical(row["request"]) != prep.canonical(request_body(built.messages, built.schema))
            or row.get("watchdog", {}).get("watchdog_fired") is not False or check_cleanup and row["watchdog"].get("watchdog_joined") is not True):
        raise ValueError("c6_native_trace")
    if check_cleanup and (not numeric(row.get("request_aux_cleanup_seconds"), 5)
                          or row.get("memory", {}).get("joined") is not True):
        raise ValueError("c6_request_cleanup_trace")
    expected_pairs = {"apply_template": ({"messages": built.messages, "chat_template_kwargs": {"enable_thinking": True}}, {"prompt": prompt}),
        "input_tokenize": ({"content": prompt, "add_special": False, "parse_special": True, "with_pieces": False}, {"tokens": tokens})}
    for key, (request, response) in expected_pairs.items():
        if prep.canonical(row.get(key + "_request")) != prep.canonical(request) or prep.canonical(row.get(key + "_response")) != prep.canonical(response) or type(row.get(key + "_http_status")) is not int or row[key + "_http_status"] != 200:
            raise ValueError("c6_template_tokenizer_trace")
    if row.get("native_request") != row["request"] or row.get("native_http_status") != 200 or row.get("native_response") != row["response"]:
        raise ValueError("c6_native_http_trace")
    expected = validate_quality_response(row["response"], prompt=prompt, input_tokens=len(tokens))
    expected["telemetry"].update(candidate_id=REUSED_POLICY_ID, semantic_support_verified=False,
        question_completeness_verified=False, language_guard="script_presence_only")
    final = row["final_token_ids"]
    if (not isinstance(final, list) or not 0 < len(final) <= 384 or any(type(t) is not int or t < 0 for t in final)
            or row.get("final_tokenize_request") != {"content": expected["content"], "add_special": False, "parse_special": False, "with_pieces": False}
            or row.get("final_tokenize_response") != {"tokens": final} or row.get("final_tokenize_http_status") != 200):
        raise ValueError("c6_final_token_trace")
    completion = row["result"]["completion"]
    if (any(prep.canonical(completion.get(k)) != prep.canonical(v) for k, v in expected.items()) or completion.get("input_tokens") != len(tokens)
            or type(completion.get("final_retokenized_tokens")) is not int or completion["final_retokenized_tokens"] != len(final)
            or not numeric(completion.get("elapsed_seconds"), row["request_seconds"])):
        raise ValueError("c6_result_trace")
    answer = grounded_answer_thinking(expected["content"], built.catalog, built.request.contexts, case["response_language"])
    if prep.canonical(answer) != prep.canonical(row["result"]["answer"]):
        raise ValueError("c6_grounding_replay")
    return answer


EVENT_KEYS = ("prepared", "apply_template_request", "apply_template_http_status", "apply_template_response",
    "input_tokenize_request", "input_tokenize_http_status", "input_tokenize_response", "native_request",
    "native_post_started", "native_http_status", "native_response", "response", "final_tokenize_request",
    "final_tokenize_http_status", "final_tokenize_response", "final_token_ids", "result")


def observation_replay(prepared, report):
    """Reconstruct every successful trace from contiguous immutable event bytes."""
    snapshots = prep.Snapshots(prepared["root"], meter=prepared["snapshots"].meter, reader=prepared["reader"])
    sequence, counters = 0, {"http_send_attempts": 0, "parsed_native_responses": 0,
                             "native_responses_received": 0, "contract_valid_answers": 0}
    for row in report["calls"]:
        references = row.get("observations", [])
        if len(references) != len(EVENT_KEYS):
            raise ValueError("c6_event_coverage")
        for key, reference in zip(EVENT_KEYS, references, strict=True):
            sequence += 1
            if reference.get("file") != f'{prepared["output"]}/trace/{sequence:06d}.json':
                raise ValueError("c6_event_order")
            event = snapshots.read(reference)
            expected = {"sequence": sequence, "id": row["id"], "key": key, "value": row.get(key)}
            if prep.canonical(event) != prep.canonical(expected):
                raise ValueError("c6_event_value")
        if row.get("native_post_started") is not True or "native_post_aborted" in row:
            raise ValueError("c6_event_send")
        counters["http_send_attempts"] += 1
        counters["parsed_native_responses"] += 1
        counters["native_responses_received"] += 1
        counters["contract_valid_answers"] += 1
    directory = prep.path(prepared["output"] + "/trace", prepared["root"])
    if sorted(p.name for p in directory.iterdir()) != [f"{n:06d}.json" for n in range(1, sequence + 1)]:
        raise ValueError("c6_event_extra")
    if any(type(report.get(k)) is not int or report[k] != value for k, value in counters.items()):
        raise ValueError("c6_event_counters")
    snapshots.unchanged()
    return snapshots.hashes


def report_replay(prepared, report):
    # A failed terminal amendment can leave an older completed report on disk.
    if prep.path(prepared["output"] + "/failed-final-save.json", prepared["root"]).exists():
        raise ValueError("c6_report_not_complete")
    phase, cases, plan = prepared["phase"], prepared["cases"], prepared["plan"]
    prefix = [] if phase == "calibration" else prepared["gate"]["ledger"]
    if (type(report.get("schema_version")) is not int or report["schema_version"] != 1
            or report.get("candidate") != CANDIDATE_ID or report.get("phase") != phase or report.get("status") != "completed"
            or report.get("plan_sha256") != prepared["snapshots"].hashes[PLAN]
            or report.get("bound_files") != plan["bound_files"] or report.get("sources_unchanged") is not True
            or report.get("reused_policy_id") != REUSED_POLICY_ID or report.get("restarts") != 0
            or report.get("gpu_layers_requested") != 28 or report.get("normalized_argv") != normalized_argv(28)
            or report.get("unexecuted") != [] or any(k in report for k in ("error", "source_error", "first_failure", "cleanup_or_later_failure", "final_save_failure"))
            or [r.get("id") for r in report.get("calls", [])] != [c["id"] for c in cases]
            or any(type(report.get(k)) is not int or report[k] != 0 for k in ("retries", "warmups", "repair_calls", "resource_calls", "recovery_native_calls"))
            or len(report.get("cleanup", [])) != 1 or not all(drain_pass(c) for c in report["cleanup"])
            or not numeric(report.get("elapsed_seconds"), 1200) or not numeric(report.get("last_request_through_cleanup_seconds"), 120)
            or report.get("identity", {}).get("candidate_id") != REUSED_POLICY_ID
            or not numeric(report.get("whole_cleanup_seconds"), 5)
            or report.get("gate") != prepared["gate"]
            or any(report.get(k, {}).get("watchdog_fired") is not False or report[k].get("watchdog_joined") is not True for k in ("phase_watchdog",))):
        raise ValueError("c6_report_not_complete")
    expected = prefix + [{"phase": phase, "id": row["id"], "request_sha256": prep.sha(prep.canonical(row["request"]))} for row in report["calls"]]
    if (report.get("ledger") != expected or len(expected) > 14
            or any(type(report.get(k)) is not int or report[k] != len(cases)
                   for k in ("http_send_attempts", "native_responses_received", "contract_valid_answers"))):
        raise ValueError("c6_ledger_binding")
    observation_replay(prepared, report)
    return [trace_replay(case, row) for case, row in zip(cases, report["calls"], strict=True)]


def run(prepared, *, factory=start_llama, generator_factory=C6Generator, verify_fn=verify,
        replay_fn=report_replay, clock=time.monotonic, write=prep.write_new, replace=prep.replace,
        cleanup_fn=cleanup_owned, watchdog=owned_watchdog, memory=rss_samples):
    verify_fn(prepared)
    root, output, phase = prepared["root"], prepared["output"], prepared["phase"]
    prefix = [] if phase == "calibration" else prepared["gate"]["ledger"]
    if phase == "validation" and prep.Snapshots(root, meter=prepared["snapshots"].meter, reader=prepared["reader"]).json(LEDGER) != prefix:
        raise ValueError("c6_ledger_drift")
    prep.path(output, root).mkdir(parents=True, exist_ok=False)
    prep.path(output + "/trace", root).mkdir(exist_ok=False)
    event_sequence = 0
    if phase == "calibration":
        write(LEDGER, [], root)
    started, last_request, request_ended = clock(), None, None
    cleanup_start, cleanup_finished = None, False
    report = {"schema_version": 1, "candidate": CANDIDATE_ID, "reused_policy_id": REUSED_POLICY_ID,
        "gpu_layers_requested": 28, "gpu_layers_effective": None, "normalized_argv": normalized_argv(28), "phase": phase,
        "plan_sha256": prepared["snapshots"].hashes[PLAN], "bound_files": prepared["plan"]["bound_files"],
        "status": "running", "calls": [], "cleanup": [], "ledger": list(prefix), "gate": prepared["gate"],
        "unexecuted": [c["id"] for c in prepared["cases"]], "http_send_attempts": 0, "sources_unchanged": False,
        "native_responses_received": 0, "parsed_native_responses": 0, "contract_valid_answers": 0,
        "parsed_response_scope": "parsed_native_responses counts observer entry; native_responses_received counts successful immutable archival",
        "send_count_scope": "http_send_attempts_not_server_receipt_or_generation_completion",
        "metadata_recovery": False, "restarts": 0, "retries": 0, "warmups": 0, "repair_calls": 0, "resource_calls": 0, "recovery_native_calls": 0}
    def save():
        replace(output + "/report.json", report, root)
    save()
    try:
        cleanup = {}
        report["cleanup"].append(cleanup)
        with factory(log_dir=prep.path(output + "/initial", root), phase_deadline=started + 1200, telemetry=cleanup) as service:
            generator = generator_factory(service.url, service.token, service.manifest)
            try:
                with watchdog(service.process, report.setdefault("phase_watchdog", {}), max(.01, started + 1200 - clock())):
                    generator.load()
                    report["identity"] = generator.public_metadata()
                    for case in prepared["cases"]:
                        last_request = clock()
                        request_ended = None
                        generator.outer_deadline = min(last_request + 90, started + 1200)
                        row = {"id": case["id"], "passed": False, "dispatch_started": False,
                               "completion_attempts": 0, "http_send_attempts": 0, "observations": []}
                        report["calls"].append(row)
                        report["unexecuted"].remove(case["id"])
                        try:
                            verify_fn(prepared)  # The first request proof consumes the outer 90 seconds.
                            generator._remaining()
                            if service.drain.emitted_bytes or service.drain.read_errors:
                                raise ValueError("c6_native_diagnostics")
                        except Exception as first:
                            request_ended = clock()
                            row.update(error=failure(first), request_seconds=request_ended - last_request)
                            report.setdefault("first_failure", row["error"])
                            raise
                        finally:
                            row["initial_proof_seconds"] = clock() - last_request
                        def before(prompt, tokens, payload, row=row, case=case):
                            verify_fn(prepared)
                            if (len(tokens) != case["official_input_tokens"] or prep.sha(prompt.encode()) != case["prompt_sha256"]
                                    or len(report["ledger"]) >= 14 or prep.Snapshots(root, meter=prepared["snapshots"].meter, reader=prepared["reader"]).json(LEDGER) != report["ledger"]):
                                raise ValueError("c6_dispatch_binding")
                            row.update(prompt=prompt, input_token_ids=tokens, request=payload, dispatch_started=True, completion_attempts=1)
                            report["ledger"].append({"phase": phase, "id": case["id"], "request_sha256": prep.sha(prep.canonical(payload))})
                            replace(LEDGER, report["ledger"], root)
                            save()  # Durable started receipt exists before the HTTP send.
                            generator._remaining()
                        def observe(key, value, row=row):
                            nonlocal event_sequence
                            event_sequence += 1
                            row[key] = copy.deepcopy(value)  # Raw survives a later archival failure in the failure receipt.
                            if key == "native_post_started":
                                row["http_send_attempts"] += 1
                                report["http_send_attempts"] += 1
                                if row["http_send_attempts"] > 1 or row["completion_attempts"] != 1:
                                    raise ValueError("c6_send_budget")
                            elif key == "native_response":
                                report["parsed_native_responses"] += 1
                            if key.endswith("_error") or key == "native_post_aborted":
                                code = value.get("code") if isinstance(value, dict) else None
                                if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9_]{1,100}", code):
                                    code = "quality_failed_closed"
                                report.setdefault("first_failure", {"code": code, "type": "GenerationError"})
                            event = {"sequence": event_sequence, "id": row["id"], "key": key, "value": copy.deepcopy(value)}
                            name = f"{output}/trace/{event_sequence:06d}.json"
                            raw = prep.encoded(event)
                            try:
                                write(name, raw, root)
                            except Exception as error:
                                row["archival_failure"] = failure(error)
                                report.setdefault("first_failure", row["archival_failure"])
                                raise
                            row["observations"].append({"file": name, "sha256": prep.sha(raw)})
                            row[key] = copy.deepcopy(value)
                            if key == "native_response":
                                report["native_responses_received"] += 1
                        try:
                            with watchdog(service.process, row.setdefault("watchdog", {}), generator._remaining()), memory(service.process, row.setdefault("memory", {}), generator.outer_deadline):
                                try:
                                    result = generator.answer(case["payload"], case["response_language"], before_dispatch=before, observe=observe)
                                    row.update(result=dataclasses.asdict(result), request_seconds=clock() - last_request, passed=True)
                                    # First write and structural replay are inside the same request budget.
                                    save()
                                    generator._remaining()
                                    row["request_seconds"] = clock() - last_request
                                    trace_replay(case, row, check_cleanup=False)
                                    save()
                                    generator._remaining()  # Includes the last required persistence.
                                    row["request_seconds"] = clock() - last_request
                                    report["contract_valid_answers"] += 1
                                except Exception as first:
                                    report.setdefault("first_failure", failure(first))
                                    raise
                                finally:
                                    request_ended = clock()
                            row["request_aux_cleanup_seconds"] = clock() - request_ended
                            if (row["request_aux_cleanup_seconds"] > 5 or not row["memory"].get("joined")
                                    or row["watchdog"].get("watchdog_joined") is not True):
                                raise ValueError("c6_cleanup_or_drain")
                        except Exception as error:
                            row.update(passed=False, error=failure(error), request_seconds=clock() - last_request)
                            report.setdefault("first_failure", row["error"])
                            raise
            except Exception as first:
                report.setdefault("first_failure", failure(first))
                request_ended = request_ended or clock()
                raise
            finally:
                cleanup_start = request_ended or clock()
                generator.close()
                cleanup_fn(service.process, service.drain, service.cleanup)
                report["whole_cleanup_seconds"] = clock() - cleanup_start
                if last_request is not None:
                    report["last_request_through_cleanup_seconds"] = clock() - last_request
        report["whole_cleanup_seconds"] = clock() - cleanup_start
        if last_request is not None:
            report["last_request_through_cleanup_seconds"] = clock() - last_request
        cleanup_finished = True
        if not drain_pass(cleanup):
            raise ValueError("c6_cleanup_or_drain")
        verify_fn(prepared)
        report["sources_unchanged"] = True
        report["status"] = "completed"
        report["elapsed_seconds"] = clock() - started
        replay_fn(prepared, report)
    except Exception as error:  # noqa: BLE001 - retain first failure, never expose body/reasoning in console
        if cleanup_start is not None and not cleanup_finished:
            report["whole_cleanup_seconds"] = clock() - cleanup_start
            if last_request is not None:
                report["last_request_through_cleanup_seconds"] = clock() - last_request
        observed = failure(error)
        report.setdefault("first_failure", observed)
        if report["first_failure"] != observed:
            report["cleanup_or_later_failure"] = observed
        report.update(status="failed_closed", error=report["first_failure"])
    finally:
        report["elapsed_seconds"] = clock() - started
        if report["status"] == "completed" and not numeric(report["elapsed_seconds"], 1200):
            report.setdefault("first_failure", {"code": "c6_phase_deadline", "type": "ValueError"})
            report.update(status="failed_closed", error=report["first_failure"])
        try:
            save()
            if clock() - started > 1200:
                report.setdefault("first_failure", {"code": "c6_phase_deadline", "type": "ValueError"})
                report.update(status="failed_closed", error=report["first_failure"])
                save()
        except Exception as error:  # noqa: BLE001 - preserve reporting failure without masking request cause
            report.setdefault("first_failure", failure(error))
            report.update(status="failed_closed", error=report["first_failure"], final_save_failure=failure(error))
            # A distinct exclusive fallback preserves the first cause without retrying a send or overwrite.
            write(output + "/failed-final-save.json", report, root)
    return report


def main(argv=None, *, checker=check, runner=run):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "run"))
    parser.add_argument("--phase", required=True, choices=COUNTS)
    args = parser.parse_args(argv)
    try:
        prepared = checker(args.phase)
        result = {"status": "checked"} if args.operation == "check" else runner(prepared)
        print(json.dumps({"status": result["status"]}))
        return 0 if result["status"] in {"checked", "completed"} else 1
    except Exception:  # noqa: BLE001
        print('{"status":"failed_closed"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
