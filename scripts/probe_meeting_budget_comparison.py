"""Once-only C2/L0 comparison; preparation is model-free and validation is gated.

This entrypoint never registers questions, downloads weights, scores semantics,
retries generation, or resumes a partial run. Raw evaluation responses belong in
the claimed local report, never operational logs or console diagnostics.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from doctrail.meeting_contract import AnswerRequest, strict_json
from doctrail.meeting_input_budget import (
    BudgetBlockGenerator,
    BudgetBlockRuntime,
    BudgetGGUFGenerator,
    BudgetLineGenerator,
    BudgetLineRuntime,
)
from scripts.prepare_meeting_budget_inputs import FILES as PREPARATION_FILES
from scripts.prepare_meeting_budget_inputs import (
    LEGACY_FREEZES,
    PHASE_PATHS,
    PROTOCOL_FILE,
    PROTOCOL_SHA256,
)
from scripts.probe_meeting_answer_review import native_service, safe_error
from scripts.probe_meeting_blocks_comparison import FILES as LEGACY_FILES
from scripts.probe_meeting_blocks_resources import rss_samples

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = "meeting-answer-blocks-c2-input-budget-v1"
RESOURCE_CANDIDATE = "meeting-answer-blocks-c2-input-budget-resources-v1"
COUNTS = {"calibration": 8, "validation": 12}
ORACLE_PATHS = {
    "calibration": "data/evaluation/meetings-c2-calibration-v1/oracle-draft.json",
    "validation": "data/evaluation/meetings-c2-validation-v1/oracle-draft-v2.json",
}
LIMITS = {"input_tokens": 5120, "context_tokens": 6144, "output_tokens": 384, "request_seconds": 90,
          "cleanup_seconds": 5, "request_and_cleanup_seconds": 120,
          "calibration_native_calls": 16, "validation_native_calls": 12,
          "neutral_native_calls": 4, "new_native_calls": 32, "closed_prior_neutral_calls": 2,
          "c2_lineage_native_cap": 34, "warmup_calls": 0, "retries": 0}
RESOURCE_LIMITS = {"input_tokens": 5120, "context_tokens": 6144, "output_tokens": 384,
    "request_seconds": 90, "cleanup_seconds": 5, "request_and_cleanup_seconds": 120,
    "native_calls": 4, "overall_seconds": 2400, "warmup_calls": 0, "retries": 0}
RESOURCE_ORDER = [("normal", "L0"), ("normal", "C2"), ("stress", "C2"), ("stress", "L0")]
FILES = LEGACY_FILES | PREPARATION_FILES | {
    "scripts/probe_meeting_budget_comparison.py", "tests/test_probe_meeting_budget_comparison.py",
    "scripts/audit_meeting_budget_comparison.py", "tests/test_audit_meeting_budget_comparison.py",
    "scripts/probe_meeting_budget_resources.py", "tests/test_probe_meeting_budget_resources.py",
    "docs/MEETINGS-C2-INPUT-BUDGET-FOLLOWUP.md", PROTOCOL_FILE, *LEGACY_FREEZES,
}
DEVIATION = "equal_input_cap_4096_to_5120_after_length_metadata"
REQUIRED_EXCLUDED = {"/root", "/root/c2_comparison_runner", "/root/c2_budget_followup",
    "/root/c2_calibration_source", "/root/c2_validation_source_b",
    "/root/c2_validation_source_review", "/root/meeting_span_semantic"}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def snapshot(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("comparison_file_limit")
    return raw, hashlib.sha256(raw).hexdigest()


def read_bound(path, expected):
    raw, actual = snapshot(path)
    if actual != expected:
        raise ValueError("comparison_hash_mismatch")
    return strict_json(raw.decode("utf-8"))


def digest(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def checked_path(name, root, *, absolute=False):
    if not isinstance(name, str) or not name:
        raise ValueError("comparison_invalid_path")
    path = Path(name)
    root = Path(root).resolve()
    lexical = path if path.is_absolute() else root / path
    if ((path.is_absolute() and not absolute) or ".." in path.parts
            or not lexical.is_relative_to(root)):
        raise ValueError("comparison_invalid_path")
    current = root
    for part in lexical.relative_to(root).parts:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if current.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("comparison_linked_path")
    result = lexical.resolve()
    if not result.is_relative_to(root):
        raise ValueError("comparison_invalid_path")
    return result


def local_path(name):
    return checked_path(name, ROOT)


def finite(value, maximum, *, inclusive=True):
    return (type(value) in (int, float) and math.isfinite(value) and 0 <= value
            and (value <= maximum if inclusive else value < maximum))


def bound_ref(ref, root):
    if (not isinstance(ref, dict) or set(ref) != {"file", "sha256"}
            or not digest(ref["sha256"])):
        raise ValueError("comparison_artifact_binding")
    return checked_path(ref["file"], root)


def verify_source_contract(plan, root):
    """Only code/freeze/protocol metadata; never validation inputs or oracles."""
    protocol = read_bound(checked_path(PROTOCOL_FILE, root), PROTOCOL_SHA256)
    exposed = {role for group in protocol.get("exposure_roles", {}).values() for role in group}
    if (type(plan.get("schema_version")) is not int or plan["schema_version"] != 1
            or plan.get("candidate") != CANDIDATE or plan.get("protocol_sha256") != PROTOCOL_SHA256
            or plan.get("protocol_deviation") != DEVIATION
            or plan.get("supersedes_for_execution_only") != protocol["supersedes_for_execution_only"]
            or fingerprint(plan.get("limits")) != fingerprint(LIMITS)
            or not digest(plan.get("runtime_receipt_sha256"))
            or not (REQUIRED_EXCLUDED | exposed) <= set(plan.get("excluded_reviewer_ids", []))):
        raise ValueError("comparison_plan_mismatch")
    for phase, name in ORACLE_PATHS.items():
        spec = plan["phases"][phase]
        if (spec.get("oracle_file") != name
                or spec.get("oracle_sha256") != protocol["bound_files"].get(name)):
            raise ValueError("comparison_original_oracle_binding")
    expected = {}
    for name in LEGACY_FREEZES:
        legacy = read_bound(checked_path(name, root), protocol["bound_files"][name])
        for source, value in legacy["bound_files"].items():
            if source in expected and expected[source] != value:
                raise ValueError("comparison_legacy_binding_conflict")
            expected[source] = value
    bindings = plan.get("bound_files", {})
    if (set(bindings) != FILES | set(expected) or any(not digest(h) for h in bindings.values())
            or any(bindings[n] != h for n, h in expected.items())
            or bindings[PROTOCOL_FILE] != PROTOCOL_SHA256
            or any(bindings[n] != protocol["bound_files"][n] for n in LEGACY_FREEZES)):
        raise ValueError("comparison_source_contract")
    frozen = read_bound(bound_ref(plan["source_freeze"], root), plan["source_freeze"]["sha256"])
    if frozen.get("bound_files") != bindings:
        raise ValueError("comparison_source_freeze_mismatch")
    for name, value in bindings.items():
        if snapshot(checked_path(name, root))[1] != value:
            raise ValueError("comparison_source_changed")
    return bindings


def validate_native_response(call, metadata, grammar, *, input_tokens, output_tokens, finish_reason):
    """Replay native configuration/count evidence without model/tokenizer calls."""
    from doctrail.meeting_gguf import GREEDY, _same_setting
    native = call.get("raw_response", {})
    settings, timings = native.get("generation_settings", {}), native.get("timings", {})
    if (not isinstance(settings, dict) or not isinstance(timings, dict)
            or any(k not in settings or not _same_setting(settings[k], v)
                   for k, v in {**GREEDY, "n_predict": 384, "grammar": grammar}.items())
            or type(input_tokens) is not int or not 0 < input_tokens <= 5120
            or type(output_tokens) is not int or not 0 < output_tokens <= 384
            or finish_reason not in {"eos", "length"}
            or native.get("model") != metadata["artifact"]["sha256"]
            or native.get("stop") is not True or native.get("truncated") is not False
            or native.get("stop_type") != ("eos" if finish_reason == "eos" else "limit")
            or not isinstance(native.get("content"), str)
            or type(timings.get("cache_n")) is not int or timings["cache_n"] != 0
            or type(timings.get("prompt_n")) is not int or timings["prompt_n"] != input_tokens
            or type(native.get("tokens_evaluated")) is not int or native["tokens_evaluated"] != input_tokens
            or type(native.get("tokens_predicted")) is not int or native["tokens_predicted"] != output_tokens
            or not finite(timings.get("prompt_ms"), 90000, inclusive=False)
            or not finite(timings.get("predicted_ms"), 90000, inclusive=False)
            or type(timings.get("predicted_n")) is not int or timings["predicted_n"] < 0):
        raise ValueError("comparison_native_mismatch")


def check_model_metadata(metadata):
    from doctrail.meeting_qwen35 import GGUF_SHA256, MODEL_ID, MODEL_REVISION, PREAMBLE_SHA256
    runtime, thinking = metadata.get("runtime", {}), metadata.get("nonthinking", {})
    if (metadata.get("repo_id") != MODEL_ID or metadata.get("original_revision") != MODEL_REVISION
            or metadata.get("revision") != "gguf-sha256:" + GGUF_SHA256
            or metadata.get("artifact", {}).get("sha256") != GGUF_SHA256
            or metadata.get("generation_protocol") != CANDIDATE
            or runtime.get("backend") != "llama.cpp"
            or any(type(runtime.get(k)) is not int or runtime[k] != v for k, v in
                   {"context_tokens": 6144, "max_input_tokens": 5120, "max_new_tokens": 384,
                    "deadline_seconds": 90}.items())
            or thinking.get("enable_thinking_requested") is not False
            or thinking.get("assistant_preamble_sha256") != PREAMBLE_SHA256
            or thinking.get("policy") != "qwen35-terminal-assistant-preamble-v1"
            or thinking.get("verification_scope") != "terminal_assistant_preamble_per_prompt"
            or type(thinking.get("last_template_verified")) is not bool):
        raise ValueError("comparison_model_metadata")


def validate_resource_evidence(resource, resource_plan, *, expected_bound_files,
                               expected_protocol_sha256):
    """Strict neutral4 replay. Truth flags alone never establish readiness."""
    from doctrail.meeting_answer_blocks import (
        answer_messages_blocks,
        build_block_catalog,
        grounded_answer_blocks,
    )
    from doctrail.meeting_answer_spans import (
        answer_messages_spans,
        build_span_catalog,
        grounded_answer_spans,
        response_language,
        span_answer_grammar,
    )
    from doctrail.meeting_qwen35 import PREAMBLE_SHA256
    cases = resource_plan.get("cases", [])
    if (resource_plan.get("candidate") != RESOURCE_CANDIDATE
            or resource_plan.get("protocol_sha256") != expected_protocol_sha256
            or resource_plan.get("bound_files") != expected_bound_files
            or fingerprint(resource_plan.get("limits")) != fingerprint(RESOURCE_LIMITS)
            or [c.get("id") for c in cases] != ["normal", "stress"]
            or resource_plan.get("stress_grammar") != 'root ::= ("z "){600}\n'
            or not isinstance(resource_plan.get("normal_expected_terms"), list)
            or not resource_plan["normal_expected_terms"]
            or any(not isinstance(t, str) or not t.strip() for t in resource_plan["normal_expected_terms"])
            or resource.get("candidate") != RESOURCE_CANDIDATE
            or resource.get("protocol_sha256") != expected_protocol_sha256
            or resource.get("fixture_sha256") != fingerprint(cases)
            or resource.get("bound_files") != expected_bound_files
            or fingerprint(resource.get("limits")) != fingerprint(RESOURCE_LIMITS)
            or resource.get("status") != "completed_resource_only"
            or any(resource.get(k) is not True for k in ("readiness_passed", "sources_unchanged",
                "processes_stopped", "metadata_recovery", "cleanup_within_service_budget"))
            or any(type(resource.get(k)) is not int or resource[k] != 0 for k in (
                "native_log_bytes", "recovery_generation_calls", "paid_calls", "warmup_calls", "retries",
                "human_review_count"))
            or resource.get("model_quality_evaluated") is not False or resource.get("unexecuted") != []
            or any(k in resource for k in ("failure", "recovery_error", "source_error", "readiness_error"))
            or not finite(resource.get("elapsed_seconds"), 2400)
            or not finite(resource.get("owned_cleanup_ms"), 5000)
            or not finite(resource.get("recovery_cleanup_ms"), 5000)
            or not finite(resource.get("last_request_through_cleanup_ms"), 120000)):
        raise ValueError("comparison_resource_not_ready")
    metadata = resource["model_runtime"]
    check_model_metadata(metadata)
    if fingerprint(resource.get("recovered_identity")) != fingerprint(metadata):
        raise ValueError("comparison_resource_recovery_identity")
    wanted = [f"{case}-{arm}" for case, arm in RESOURCE_ORDER]
    if (len(resource.get("calls", [])) != 4 or len(resource.get("results", [])) != 4
            or [r.get("id") for r in resource["results"]] != wanted
            or [c.get("id") for c in resource["calls"]] != wanted):
        raise ValueError("comparison_resource_call_set")
    requests = {}
    for case in cases:
        request = AnswerRequest.model_validate(case["payload"])
        counts = case.get("official_input_tokens", {})
        if (not request.contexts or set(counts) != {"L0", "C2"}
                or any(type(n) is not int or not 0 < n <= 5120 for n in counts.values())):
            raise ValueError("comparison_resource_input")
        if (case["id"] == "normal" and max(counts.values()) > 1024
                or case["id"] == "stress" and (min(counts.values()) <= 4096
                                               or max(counts.values()) < 4992)):
            raise ValueError("comparison_resource_length_target")
        requests[case["id"]] = request, counts
    for sequence, ((case_id, arm), row, call) in enumerate(zip(
            RESOURCE_ORDER, resource["results"], resource["calls"], strict=True)):
        request, counts = requests[case_id]
        catalog_fn, messages_fn, mapper = ((build_span_catalog, answer_messages_spans, grounded_answer_spans)
            if arm == "L0" else (build_block_catalog, answer_messages_blocks, grounded_answer_blocks))
        catalog = catalog_fn(request.contexts)
        grammar = span_answer_grammar(catalog) if case_id == "normal" else resource_plan["stress_grammar"]
        if (any(r.get("case_id") != case_id or r.get("arm") != arm for r in (row, call))
                or row.get("passed") is not True or "error" in row or "error" in call
                or type(call.get("sequence")) is not int or call["sequence"] != sequence
                or call.get("dispatch_attempted") is not True
                or type(row.get("official_input_tokens")) is not int
                or row["official_input_tokens"] != counts[arm]
                or type(row.get("input_tokens")) is not int or row["input_tokens"] != counts[arm]
                or row.get("prompt_sha256") != fingerprint(messages_fn(request.query, catalog))
                or row.get("grammar_sha256") != hashlib.sha256(grammar.encode()).hexdigest()
                or not finite(row.get("elapsed_seconds"), 90, inclusive=False)
                or row.get("watchdog_fired") is not False or row.get("watchdog_joined") is not True
                or row.get("watchdog_kill_failed")):
            raise ValueError("comparison_resource_row")
        memory = row.get("memory", {})
        if (type(memory.get("sample_count")) is not int or memory["sample_count"] < 1
                or memory.get("sampler_joined") is not True):
            raise ValueError("comparison_resource_memory_sampling")
        check_payload(call.get("payload"), grammar)
        if len(call["payload"]["prompt"]) != counts[arm]:
            raise ValueError("comparison_resource_native_count")
        validate_native_response(call, metadata, grammar, input_tokens=row["input_tokens"],
            output_tokens=row.get("output_tokens"), finish_reason=row.get("finish_reason"))
        config = {"backend": "llama.cpp", **{k: v for k, v in call["payload"].items()
            if k not in {"prompt", "cache_prompt", "return_tokens"}},
            "cache_prompt_requested": False, "observed_cache_tokens": 0,
            "observed_nonthinking_preamble_sha256": PREAMBLE_SHA256, "enable_thinking_requested": False}
        if fingerprint(row.get("effective_config")) != fingerprint(config):
            raise ValueError("comparison_resource_effective_config")
        if case_id == "stress":
            if row["finish_reason"] != "length" or row["output_tokens"] != 384:
                raise ValueError("comparison_resource_stress_end")
        else:
            replayed = mapper(call["raw_response"]["content"], catalog, request.contexts,
                              response_language(request.query))
            if (row["finish_reason"] != "eos" or replayed["status"] != "answered"
                    or {k: row.get("response", {}).get(k) for k in ("status", "reason", "claims")} != replayed
                    or any(term.casefold() not in " ".join(c["text"] for c in replayed["claims"]).casefold()
                           for term in resource_plan["normal_expected_terms"])):
                raise ValueError("comparison_resource_normal_replay")
    return resource


def validate_resource_report(plan, root):
    resource_path = bound_ref(plan["resource_report"], root)
    registration_path = bound_ref(plan["resource_plan"], root)
    resource = read_bound(resource_path, plan["resource_report"]["sha256"])
    registration = read_bound(registration_path, plan["resource_plan"]["sha256"])
    if (resource.get("plan_sha256") != plan["resource_plan"]["sha256"]
            or registration.get("runtime_receipt_sha256") != plan["runtime_receipt_sha256"]
            or fingerprint(registration.get("tokenizer")) != fingerprint(plan.get("tokenizer"))):
        raise ValueError("comparison_resource_binding")
    return validate_resource_evidence(resource, registration,
        expected_bound_files=plan["bound_files"], expected_protocol_sha256=PROTOCOL_SHA256)


def schedule(phase, ids):
    return [(identity, arm) for index, identity in enumerate(ids)
            for arm in (("C2",) if phase == "validation" else
                        (("L0", "C2") if index % 2 == 0 else ("C2", "L0")))]


def verify_gate(prepared):
    if prepared["phase"] != "validation":
        return None
    # Import only the NEW audit entrypoint. No legacy evaluation pool is opened.
    from scripts.audit_meeting_budget_comparison import verify_validation_gate
    return verify_validation_gate(prepared["plan"], ROOT, prepared["gate_path"],
                                  plan_sha256=prepared["sha256"])


def verify(prepared, *, include_input=True):
    if snapshot(prepared["path"])[1] != prepared["sha256"]:
        raise ValueError("comparison_plan_changed")
    # This always precedes any validation input read, including repeated hashes.
    if verify_gate(prepared) != prepared["gate"]:
        raise ValueError("comparison_gate_changed")
    verify_source_contract(prepared["plan"], ROOT)
    validate_resource_report(prepared["plan"], ROOT)
    if include_input:
        receipt = prepared["spec"]["preparation_receipt"]
        if snapshot(bound_ref(receipt, ROOT))[1] != receipt["sha256"]:
            raise ValueError("comparison_preparation_changed")
        if snapshot(prepared["input"])[1] != prepared["spec"]["input_sha256"]:
            raise ValueError("comparison_input_changed")


def prepare(plan_path, phase, gate_path=None, *, loader=None, counter=None):
    """Verify sealed plan, then selected inputs; tokenizer use is strictly local."""
    plan_path = checked_path(str(plan_path), ROOT, absolute=True)
    raw, sha = snapshot(plan_path)
    plan = strict_json(raw.decode("utf-8"))
    if (type(plan.get("schema_version")) is not int or plan["schema_version"] != 1
            or plan.get("candidate") != CANDIDATE or phase not in COUNTS
            or fingerprint(plan.get("limits")) != fingerprint(LIMITS)
            or set(plan.get("phases", {})) != set(COUNTS)
            or any(not digest(h) for h in plan["bound_files"].values())
            or not digest(plan.get("runtime_receipt_sha256"))
            or not isinstance(plan.get("tokenizer"), dict)):
        raise ValueError("comparison_plan_mismatch")
    from scripts.audit_meeting_budget_comparison import (
        validate_audit_paths,
        validate_audit_registration,
    )
    validate_audit_registration(plan)
    validate_audit_paths(plan, ROOT)
    verify_source_contract(plan, ROOT)
    input_paths, outputs = [], []
    for name, spec in plan["phases"].items():
        ids = spec.get("case_ids", [])
        if (len(ids) != COUNTS[name] or len(set(ids)) != len(ids)
                or any(not isinstance(i, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", i)
                       for i in ids)
                or not digest(spec.get("input_sha256")) or not digest(spec.get("oracle_sha256"))):
            raise ValueError("comparison_phase_mismatch")
        input_paths.append(local_path(spec.get("input_file")))
        output = local_path(spec.get("output_dir"))
        if not output.is_relative_to((ROOT / ".local").resolve()) or output == ROOT / ".local":
            raise ValueError("comparison_output_invalid")
        outputs.append(output)
    if (input_paths[0] == input_paths[1] or outputs[0].is_relative_to(outputs[1])
            or outputs[1].is_relative_to(outputs[0])
            or any(i.is_relative_to(o) for i in input_paths + [Path(plan_path).resolve()]
                   for o in outputs)
            or any(local_path(name) in input_paths for name in FILES)):
        raise ValueError("comparison_paths_collide")
    spec = plan["phases"][phase]
    prepared = {"plan": plan, "path": Path(plan_path), "sha256": sha, "phase": phase,
                "spec": spec, "output": local_path(spec["output_dir"]),
                "input": local_path(spec["input_file"]), "gate_path": gate_path}
    if prepared["output"].exists():
        raise ValueError("comparison_output_exists")
    if phase == "validation" and gate_path is None:
        raise ValueError("comparison_gate_required")
    prepared["gate"] = verify_gate(prepared)
    verify(prepared, include_input=False)
    receipt_ref = spec["preparation_receipt"]
    token_receipt = read_bound(bound_ref(receipt_ref, ROOT), receipt_ref["sha256"])
    validate_preparation_receipt(plan, phase, token_receipt)
    data = read_bound(prepared["input"], spec["input_sha256"])
    cases = data.get("cases", [])
    if (type(data.get("schema_version")) is not int or data["schema_version"] != 1
            or data.get("phase") != phase or [c.get("id") for c in cases] != spec["case_ids"]):
        raise ValueError("comparison_case_set_mismatch")
    from doctrail.meeting_answer_blocks import answer_messages_blocks, build_block_catalog
    from doctrail.meeting_answer_spans import (
        answer_messages_spans,
        build_span_catalog,
        span_answer_grammar,
    )
    from scripts.check_meeting_review_token_budget import count_prompt, load_tokenizer
    tokenizer, metadata = (loader or load_tokenizer)(False)
    if fingerprint(metadata) != fingerprint(plan["tokenizer"]):
        raise ValueError("comparison_tokenizer_changed")
    prepared["cases"] = {}
    for case in cases:
        request = AnswerRequest.model_validate(case["payload"])
        if (not request.contexts or set(case) != {"id", "payload", "official_input_tokens"}
                or set(case.get("official_input_tokens", {})) != {"L0", "C2"}
                or fingerprint(request.model_dump(exclude_unset=True)) != fingerprint(case["payload"])):
            raise ValueError("comparison_input_contract")
        arms = {}
        for arm, catalog_fn, message_fn in (
                ("L0", build_span_catalog, answer_messages_spans),
                ("C2", build_block_catalog, answer_messages_blocks)):
            catalog = catalog_fn(request.contexts)
            prompt = message_fn(request.query, catalog)
            n = (counter or count_prompt)(tokenizer, prompt)
            expected = case["official_input_tokens"][arm]
            if (type(n) is not int or not 0 < n <= 5120 or type(expected) is not int
                    or n != expected):
                raise ValueError("comparison_token_budget")
            arms[arm] = {"prompt_sha256": fingerprint(prompt), "official_input_tokens": n,
                         "grammar": span_answer_grammar(catalog), "unit_count": len(catalog.spans)}
        prepared["cases"][case["id"]] = {"request": request,
            "original_payload": copy.deepcopy(case["payload"]),
            "payload_sha256": fingerprint(case["payload"]), "arms": arms}
        registered_case = next(r for r in token_receipt["cases"] if r["id"] == case["id"])
        if (registered_case["payload_sha256"] != fingerprint(case["payload"])
                or any(registered_case["arms"][a]["official_input_tokens"] != arms[a]["official_input_tokens"]
                       or registered_case["arms"][a]["prompt_sha256"] != arms[a]["prompt_sha256"]
                       or registered_case["arms"][a]["grammar_sha256"] != hashlib.sha256(arms[a]["grammar"].encode()).hexdigest()
                       for a in ("L0", "C2"))):
            raise ValueError("comparison_preparation_replay")
    prepared["schedule"] = schedule(phase, spec["case_ids"])
    verify(prepared)
    return prepared


def save(prepared, report):
    target = prepared["output"] / "report.json"
    temporary = target.with_suffix(".tmp")
    contents = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    if len(contents) > 16 * 1024 * 1024:
        raise ValueError("comparison_report_limit")
    temporary.write_bytes(contents)
    for attempt, delay in enumerate((.02, .05, 0)):
        try:
            temporary.replace(target)
            return
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(delay)  # unchanged report replacement only, never inference retry


@contextmanager
def watchdog(process, metrics, seconds=90):
    def kill():
        metrics["watchdog_fired"] = True
        try:
            if process.poll() is None:
                process.kill()
        except OSError:
            metrics["watchdog_kill_failed"] = True
    timer = threading.Timer(seconds, kill)
    timer.daemon = True
    metrics["watchdog_fired"] = False
    try:
        timer.start()
        yield
    finally:
        timer.cancel()
        timer.join(timeout=5)
        metrics["watchdog_joined"] = not timer.is_alive()


def stop_owned(process, report):
    started = time.monotonic()
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)
    report["owned_cleanup_ms"] = (time.monotonic() - started) * 1000
    report["processes_stopped"] = process.poll() is not None
    if report["owned_cleanup_ms"] > 5000 or not report["processes_stopped"]:
        raise ValueError("comparison_cleanup_failed")


def check_payload(payload, grammar):
    from doctrail.meeting_gguf import GREEDY
    expected = {**GREEDY, "n_predict": 384, "grammar": grammar,
                "cache_prompt": False, "return_tokens": True}
    if (not isinstance(payload, dict) or set(payload) != set(expected) | {"prompt"}
            or fingerprint({k: payload[k] for k in expected}) != fingerprint(expected)
            or not isinstance(payload["prompt"], list) or not 0 < len(payload["prompt"]) <= 5120
            or any(type(token) is not int or token < 0 for token in payload["prompt"])
            or len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()) > 524288):
        raise ValueError("comparison_dispatch_config")


def check_row(row, calls):
    from doctrail.meeting_gguf import GREEDY
    from doctrail.meeting_qwen35 import PREAMBLE_SHA256
    config = row.get("effective_config", {})
    expected = {"backend": "llama.cpp", **GREEDY, "n_predict": 384,
        "cache_prompt_requested": False, "observed_cache_tokens": 0,
        "observed_nonthinking_preamble_sha256": PREAMBLE_SHA256, "enable_thinking_requested": False}
    telemetry = row.get("worker_telemetry", {})
    metrics = telemetry.get("calls", [])
    elapsed = row.get("elapsed_ms")
    worker_elapsed = telemetry.get("elapsed_ms")
    if (type(elapsed) not in (int, float) or not math.isfinite(elapsed) or not 0 <= elapsed < 90000
            or type(worker_elapsed) not in (int, float) or not math.isfinite(worker_elapsed)
            or not 0 <= worker_elapsed < 90000 or worker_elapsed > elapsed + 1
            or "error" in row or "error_code" in telemetry):
        raise ValueError("comparison_row_timing")
    if (len(calls) != 1 or "raw_response" not in calls[0] or "error" in calls[0]
            or type(telemetry.get("completion_attempts")) is not int
            or telemetry.get("completion_attempts") != 1 or len(metrics) != 1
            or fingerprint({k: config.get(k) for k in expected}) != fingerprint(expected)
            or hashlib.sha256(config.get("grammar", "").encode()).hexdigest() != row["grammar_sha256"]
            or metrics[0].get("finish_reason") != "eos"
            or type(metrics[0].get("input_tokens")) is not int
            or not 0 < metrics[0]["input_tokens"] <= 5120
            or metrics[0]["input_tokens"] != row.get("official_input_tokens")
            or type(metrics[0].get("output_tokens")) is not int
            or not 0 < metrics[0]["output_tokens"] <= 384
            or row.get("watchdog_fired") is not False or row.get("watchdog_joined") is not True
            or row.get("watchdog_kill_failed") or row["elapsed_ms"] >= 90000):
        raise ValueError("comparison_row_integrity")
    completion_seconds = metrics[0].get("elapsed_seconds")
    if (type(completion_seconds) not in (int, float) or not math.isfinite(completion_seconds)
            or not 0 <= completion_seconds < 90 or completion_seconds * 1000 > worker_elapsed + 1):
        raise ValueError("comparison_row_timing")


def validate_preparation_receipt(plan, phase, receipt, *, root=None):
    root = ROOT if root is None else root
    protocol = read_bound(checked_path(PROTOCOL_FILE, root), PROTOCOL_SHA256)
    for name in PHASE_PATHS[phase]:
        expected = protocol["bound_files"].get(name)
        if (not digest(expected)
                or receipt.get("snapshots", {}).get(name, {}).get("sha256") != expected):
            raise ValueError("comparison_original_preparation_binding")
    if receipt.get("snapshots", {}).get(PROTOCOL_FILE, {}).get("sha256") != PROTOCOL_SHA256:
        raise ValueError("comparison_original_preparation_binding")
    spec = plan["phases"][phase]
    n = COUNTS[phase] * 2
    if (receipt.get("candidate") != CANDIDATE or receipt.get("phase") != phase
            or receipt.get("status") != "passed" or receipt.get("payloads_preserved") is not True
            or receipt.get("input_sha256") != spec["input_sha256"]
            or receipt.get("protocol_deviation") != DEVIATION
            or receipt.get("referenced_body_oracle_bytes_rechecked") is not False
            or receipt.get("errors") != []
            or any(type(receipt.get(k)) is not int or receipt[k] != 0
                   for k in ("model_calls", "native_calls", "downloads"))
            or fingerprint(receipt.get("tokenizer")) != fingerprint(plan["tokenizer"])
            or [c.get("id") for c in receipt.get("cases", [])] != spec["case_ids"]
            or any(type(receipt.get("summary", {}).get(k)) is not int or receipt["summary"][k] != v
                   for k, v in {"total_arms": n, "measured_arms": n, "unknown_arms": 0,
                                "failed_arms": 0, "new_5120_pass": n, "new_5120_fail": 0}.items())
            or any(plan["bound_files"].get(k) != v for k, v in receipt.get("bound_files", {}).items())
            or not PREPARATION_FILES <= receipt.get("bound_files", {}).keys()
            or receipt.get("snapshots", {}).get(plan["source_freeze"]["file"], {}).get("sha256")
            != plan["source_freeze"]["sha256"]):
        raise ValueError("comparison_preparation_receipt")
    for case in receipt["cases"]:
        if case.get("payload_preserved") is not True or not digest(case.get("payload_sha256")):
            raise ValueError("comparison_preparation_receipt")
        for arm in ("L0", "C2"):
            row = case["arms"][arm]
            count = row.get("official_input_tokens")
            if (type(count) is not int or not 0 < count <= 5120 or row.get("error_code") is not None
                    or row.get("new_5120_pass") is not True
                    or row.get("old_4096_pass") is not (count <= 4096)):
                raise ValueError("comparison_preparation_receipt")


class DispatchObserver:
    """Explicit dependency on a NEW subclass; no method/global replacement."""
    def __init__(self, prepared, report):
        self.prepared, self.report = prepared, report
        self.active, self.started = None, None

    def before_complete(self, messages, deadline, token_limit, grammar):
        if self.active is None:
            raise ValueError("comparison_hidden_completion")
        spec = self.prepared["cases"][self.active[0]]["arms"][self.active[1]]
        if (fingerprint(messages) != spec["prompt_sha256"] or type(token_limit) is not int
                or token_limit != 384 or grammar != spec["grammar"]):
            raise ValueError("comparison_prompt_changed")
        return min(deadline, self.started + 90)

    def request(self, send, method, path, payload, deadline):
        if path != "/completion":
            if ((method, path) not in {("GET", "/props"), ("POST", "/apply-template"), ("POST", "/tokenize")}
                    or path != "/props" and self.active is None):
                raise ValueError("comparison_unregistered_native_route")
            return send()
        verify(self.prepared)
        if (self.active is None or method != "POST"
                or len(self.report["calls"]) >= len(self.prepared["schedule"])
                or any((c["id"], c["arm"]) == self.active for c in self.report["calls"])):
            raise ValueError("comparison_native_budget")
        spec = self.prepared["cases"][self.active[0]]["arms"][self.active[1]]
        check_payload(payload, spec["grammar"])
        if len(payload["prompt"]) != spec["official_input_tokens"]:
            raise ValueError("comparison_native_official_count")
        call = {"id": self.active[0], "arm": self.active[1], "dispatch_attempted": True,
            "sequence": len(self.report["calls"]), "at": datetime.now(UTC).isoformat(),
            "payload": copy.deepcopy(payload), "payload_sha256": fingerprint(payload),
            "input_tokens": len(payload["prompt"])}
        self.report["calls"].append(call)
        save(self.prepared, self.report)  # Once-only attempt persisted before the actual POST.
        try:
            response = send()
            call["raw_response"] = copy.deepcopy(response)
            return response
        except Exception as error:
            call["error"] = safe_error(error)
            raise
        finally:
            save(self.prepared, self.report)


class ObservedBudgetGenerator(BudgetGGUFGenerator):
    def __init__(self, *args, observer, **kwargs):
        self.observer = observer
        super().__init__(*args, **kwargs)

    def _request(self, method, path, payload=None, deadline=None):
        return self.observer.request(lambda: super(ObservedBudgetGenerator, self)._request(
            method, path, payload, deadline), method, path, payload, deadline)

    def _complete(self, messages, deadline, token_limit, grammar=""):
        deadline = self.observer.before_complete(messages, deadline, token_limit, grammar)
        return super()._complete(messages, deadline, token_limit, grammar)


def run(prepared, factory=native_service, base_factory=None):
    """One claimed phase; a failure leaves a terminal partial report, never resume."""
    base_factory = base_factory or (lambda service, observer: ObservedBudgetGenerator(
        service.url, service.token, service.manifest, observer=observer).load())
    verify(prepared)
    prepared["output"].mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "candidate": CANDIDATE, "phase": prepared["phase"],
        "protocol_sha256": PROTOCOL_SHA256, "protocol_deviation": DEVIATION,
        "plan_sha256": prepared["sha256"], "input_sha256": prepared["spec"]["input_sha256"],
        "oracle_sha256": prepared["spec"]["oracle_sha256"], "limits": LIMITS,
        "bound_files": prepared["plan"]["bound_files"], "gate": prepared["gate"],
        "resource_report": prepared["plan"]["resource_report"],
        "preparation_receipt": prepared["spec"]["preparation_receipt"],
        "started_at": datetime.now(UTC).isoformat(), "status": "running", "calls": [],
        "results": [], "sources_unchanged": False, "resources_passed": False,
        "processes_stopped": False, "human_review_count": 0, "paid_calls": 0,
        "warmup_calls": 0, "retries": 0, "semantics_verified": False,
        "planned_dispatches": [{"id": i, "arm": a} for i, a in prepared["schedule"]]}
    save(prepared, report)
    observer = DispatchObserver(prepared, report)
    process, last_started = None, None
    try:
        with factory(prepared["output"] / "native-logs", 2400) as service:
            process = service.process
            try:
                if fingerprint(service.receipt) != prepared["plan"]["runtime_receipt_sha256"]:
                    raise ValueError("comparison_runtime_receipt_changed")
                base = base_factory(service, observer)
                try:
                    report["model_runtime"] = base.public_metadata()
                    check_model_metadata(report["model_runtime"])
                    resource = validate_resource_report(prepared["plan"], ROOT)
                    if fingerprint(report["model_runtime"]) != fingerprint(resource["model_runtime"]):
                        raise ValueError("comparison_resource_identity_changed")
                    runtimes = {"L0": BudgetLineRuntime(BudgetLineGenerator(base)),
                                "C2": BudgetBlockRuntime(BudgetBlockGenerator(base))}
                    for active in prepared["schedule"]:
                        verify(prepared)
                        item = prepared["cases"][active[0]]
                        if (fingerprint(item["request"].model_dump(exclude_unset=True)) != item["payload_sha256"]
                                or fingerprint(item["original_payload"]) != item["payload_sha256"]):
                            raise ValueError("comparison_request_changed")
                        arm_spec, runtime = item["arms"][active[1]], runtimes[active[1]]
                        row = {"id": active[0], "arm": active[1], "structural_status": "failed",
                            "payload_sha256": item["payload_sha256"],
                            "prompt_sha256": arm_spec["prompt_sha256"],
                            "official_input_tokens": arm_spec["official_input_tokens"],
                            "unit_count": arm_spec["unit_count"],
                            "grammar_sha256": hashlib.sha256(arm_spec["grammar"].encode()).hexdigest()}
                        report["results"].append(row)
                        started = last_started = time.monotonic()
                        observer.active, observer.started = active, started
                        try:
                            with rss_samples(process, row), watchdog(process, row):
                                row["response"] = runtime.answer(item["request"])
                            row["elapsed_ms"] = (time.monotonic() - started) * 1000
                            row["worker_telemetry"] = copy.deepcopy(runtime.last_telemetry)
                            row["effective_config"] = copy.deepcopy(base.last_effective_config)
                            calls = [c for c in report["calls"] if (c["id"], c["arm"]) == active]
                            check_row(row, calls)
                            metric = row["worker_telemetry"]["calls"][0]
                            validate_native_response(calls[0], report["model_runtime"], arm_spec["grammar"],
                                input_tokens=metric["input_tokens"], output_tokens=metric["output_tokens"],
                                finish_reason=metric["finish_reason"])
                            row["structural_status"] = "passed"
                        except Exception as error:
                            row["error"] = safe_error(error)
                            raise
                        finally:
                            observer.active = None
                            row["elapsed_ms"] = (time.monotonic() - started) * 1000
                            row["worker_telemetry"] = copy.deepcopy(runtime.last_telemetry)
                            row["effective_config"] = copy.deepcopy(base.last_effective_config)
                            save(prepared, report)
                finally:
                    base.close()
            finally:
                stop_owned(process, report)
    except Exception as error:  # noqa: BLE001 - preserve safe partial evidence without resume
        report["failure"] = safe_error(error)
    finally:
        if last_started is not None:
            report["last_request_through_cleanup_ms"] = (time.monotonic() - last_started) * 1000
        try:
            verify(prepared)
            report["sources_unchanged"] = True
        except Exception as error:  # noqa: BLE001
            report["source_error"] = safe_error(error)
        report["native_log_bytes"] = sum(p.stat().st_size for p in prepared["output"].rglob("*.log"))
        report["unexecuted"] = [{"id": i, "arm": a} for i, a in prepared["schedule"]
            if (i, a) not in {(c["id"], c["arm"]) for c in report["calls"]}]
        report["resources_passed"] = ("failure" not in report and "source_error" not in report
            and report["sources_unchanged"] and report["processes_stopped"]
            and len(report["calls"]) == len(report["results"]) == len(prepared["schedule"])
            and all(r["structural_status"] == "passed" for r in report["results"])
            and report["native_log_bytes"] == 0
            and report.get("last_request_through_cleanup_ms", 120001) <= 120000)
        report["status"] = ("completed_not_semantically_verified" if report["resources_passed"] else "failed")
        report["completed_at"] = datetime.now(UTC).isoformat()
        save(prepared, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "run"))
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--phase", required=True, choices=COUNTS)
    parser.add_argument("--gate", type=Path)
    args = parser.parse_args()
    try:
        prepared = prepare(args.plan, args.phase, args.gate)
        if args.operation == "check":
            print(json.dumps({"prepared": True, "phase": args.phase, "model_calls": 0}))
        else:
            report = run(prepared)
            print(json.dumps({"status": report["status"], "native_calls": len(report["calls"])}))
            raise SystemExit(0 if report["resources_passed"] else 1)
    except Exception as error:  # noqa: BLE001 - never print source, question or model text
        parser.exit(1, safe_error(error) + "\n")


if __name__ == "__main__":
    main()
