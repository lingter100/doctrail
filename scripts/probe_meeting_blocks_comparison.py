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
from scripts.probe_meeting_answer_review import native_service, safe_error
from scripts.probe_meeting_blocks_resources import FILES as RESOURCE_FILES
from scripts.probe_meeting_blocks_resources import rss_samples

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = "meeting-answer-blocks-c2-comparison-v1"
RESOURCE_REPORT_SHA256 = "eb138abc5e6af97df68026b3e68c771c7e9d6c4dc974aa58865e894956b4a4d6"
RESOURCE_REPORT_FILE = "experiments/results/meetings-c2-resources-v1.json"
COUNTS = {"calibration": 8, "validation": 12}
LIMITS = {"input_tokens": 4096, "output_tokens": 384, "request_seconds": 90,
          "cleanup_seconds": 5, "request_and_cleanup_seconds": 120,
          "calibration_native_calls": 16, "validation_native_calls": 12,
          "new_native_calls": 28, "warmup_calls": 0, "retries": 0}
FILES = RESOURCE_FILES | {
    "src/doctrail/meeting_answer_lines_bounded.py", "tests/test_meeting_answer_lines_bounded.py",
    "scripts/probe_meeting_blocks_comparison.py", "tests/test_probe_meeting_blocks_comparison.py",
    "scripts/prepare_meeting_comparison_audit.py", "tests/test_prepare_meeting_comparison_audit.py",
    "src/doctrail/meeting_comparison_review.py", "tests/test_meeting_comparison_review.py",
    "scripts/prepare_meeting_blocks_inputs.py", "tests/test_prepare_meeting_blocks_inputs.py",
    "docs/MEETINGS-C2-REVIEW-CONTRACT.md",
    "docs/MEETINGS-C2-COMPARISON-PLAN.md", "data/evaluation/meetings-c2-family-registry-v1.json",
}


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


def local_path(name):
    if not isinstance(name, str) or not name:
        raise ValueError("comparison_invalid_path")
    path = Path(name)
    result = (ROOT / path).resolve()
    if path.is_absolute() or ".." in path.parts or not result.is_relative_to(ROOT.resolve()):
        raise ValueError("comparison_invalid_path")
    return result


def schedule(phase, ids):
    return [(identity, arm) for index, identity in enumerate(ids)
            for arm in (("C2",) if phase == "validation" else
                        (("L0", "C2") if index % 2 == 0 else ("C2", "L0")))]


def verify_gate(prepared):
    if prepared["phase"] != "validation":
        return None
    # Import only the NEW audit entrypoint. No legacy evaluation pool is opened.
    from scripts.prepare_meeting_comparison_audit import verify_validation_gate
    return verify_validation_gate(prepared["plan"], ROOT, prepared["gate_path"],
                                  plan_sha256=prepared["sha256"])


def verify(prepared, *, include_input=True):
    if snapshot(prepared["path"])[1] != prepared["sha256"]:
        raise ValueError("comparison_plan_changed")
    # This always precedes any validation input read, including repeated hashes.
    if verify_gate(prepared) != prepared["gate"]:
        raise ValueError("comparison_gate_changed")
    for name, expected in prepared["plan"]["bound_files"].items():
        if snapshot(local_path(name))[1] != expected:
            raise ValueError("comparison_source_changed")
    resource = prepared["plan"]["resource_report"]
    if snapshot(local_path(resource["file"]))[1] != RESOURCE_REPORT_SHA256:
        raise ValueError("comparison_resource_report_changed")
    if include_input and snapshot(prepared["input"])[1] != prepared["spec"]["input_sha256"]:
        raise ValueError("comparison_input_changed")


def prepare(plan_path, phase, gate_path=None, *, loader=None, counter=None):
    """Verify sealed plan, then selected inputs; tokenizer use is strictly local."""
    raw, sha = snapshot(plan_path)
    plan = strict_json(raw.decode("utf-8"))
    if (type(plan.get("schema_version")) is not int or plan["schema_version"] != 1
            or plan.get("candidate") != CANDIDATE or phase not in COUNTS
            or fingerprint(plan.get("limits")) != fingerprint(LIMITS)
            or set(plan.get("phases", {})) != set(COUNTS)
            or set(plan.get("bound_files", {})) != FILES
            or any(not digest(h) for h in plan["bound_files"].values())
            or not digest(plan.get("runtime_receipt_sha256"))
            or plan.get("resource_report", {}).get("sha256") != RESOURCE_REPORT_SHA256
            or plan.get("resource_report", {}).get("file") != RESOURCE_REPORT_FILE
            or not isinstance(plan.get("tokenizer"), dict)):
        raise ValueError("comparison_plan_mismatch")
    from scripts.prepare_meeting_comparison_audit import (
        validate_audit_paths,
        validate_audit_registration,
    )
    validate_audit_registration(plan)
    validate_audit_paths(plan, ROOT)
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
        if not request.contexts or set(case.get("official_input_tokens", {})) != {"L0", "C2"}:
            raise ValueError("comparison_input_contract")
        arms = {}
        for arm, catalog_fn, message_fn in (
                ("L0", build_span_catalog, answer_messages_spans),
                ("C2", build_block_catalog, answer_messages_blocks)):
            catalog = catalog_fn(request.contexts)
            prompt = message_fn(request.query, catalog)
            n = (counter or count_prompt)(tokenizer, prompt)
            expected = case["official_input_tokens"][arm]
            if (type(n) is not int or not 0 < n <= 4096 or type(expected) is not int
                    or n != expected):
                raise ValueError("comparison_token_budget")
            arms[arm] = {"prompt_sha256": fingerprint(prompt), "official_input_tokens": n,
                         "grammar": span_answer_grammar(catalog), "unit_count": len(catalog.spans)}
        prepared["cases"][case["id"]] = {"request": request,
            "payload_sha256": fingerprint(request.model_dump()), "arms": arms}
    prepared["schedule"] = schedule(phase, spec["case_ids"])
    verify(prepared)
    return prepared


def save(prepared, report):
    target = prepared["output"] / "report.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8")
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
            or not isinstance(payload["prompt"], list) or not 0 < len(payload["prompt"]) <= 4096
            or any(type(token) is not int for token in payload["prompt"])):
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
            or not 0 < metrics[0]["input_tokens"] <= 4096
            or type(metrics[0].get("output_tokens")) is not int
            or not 0 < metrics[0]["output_tokens"] <= 384
            or row.get("watchdog_fired") is not False or row.get("watchdog_joined") is not True
            or row.get("watchdog_kill_failed") or row["elapsed_ms"] >= 90000):
        raise ValueError("comparison_row_integrity")
    completion_seconds = metrics[0].get("elapsed_seconds")
    if (type(completion_seconds) not in (int, float) or not math.isfinite(completion_seconds)
            or not 0 <= completion_seconds < 90 or completion_seconds * 1000 > worker_elapsed + 1):
        raise ValueError("comparison_row_timing")


def run(prepared, factory=native_service, base_factory=None):
    from doctrail.meeting_answer_blocks import BlockAnswerGenerator, BlockAnswerMeetingRuntime
    from doctrail.meeting_answer_lines_bounded import BoundedLineGenerator, BoundedLineRuntime
    from doctrail.meeting_qwen35 import Qwen35Generator
    base_factory = base_factory or (lambda s: Qwen35Generator(s.url, s.token, s.manifest).load())
    verify(prepared)
    prepared["output"].mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "candidate": CANDIDATE, "phase": prepared["phase"],
        "plan_sha256": prepared["sha256"], "input_sha256": prepared["spec"]["input_sha256"],
        "oracle_sha256": prepared["spec"]["oracle_sha256"], "limits": LIMITS,
        "bound_files": prepared["plan"]["bound_files"], "gate": prepared["gate"],
        "started_at": datetime.now(UTC).isoformat(), "status": "running", "calls": [],
        "results": [], "sources_unchanged": False, "resources_passed": False,
        "processes_stopped": False, "human_review_count": 0, "paid_calls": 0,
        "warmup_calls": 0, "retries": 0, "semantics_verified": False,
        "planned_dispatches": [{"id": i, "arm": a} for i, a in prepared["schedule"]]}
    save(prepared, report)
    active, process, last_started = None, None, None
    try:
        with factory(prepared["output"] / "native-logs", 2400) as service:
            process = service.process
            try:
                if fingerprint(service.receipt) != prepared["plan"]["runtime_receipt_sha256"]:
                    raise ValueError("comparison_runtime_receipt_changed")
                base = base_factory(service)
                original, complete = base._request, base._complete

                def request(method, path, payload=None, deadline=None):
                    if path != "/completion":
                        if (method, path) not in {("GET", "/props"), ("POST", "/apply-template"),
                                                  ("POST", "/tokenize")}:
                            raise ValueError("comparison_unregistered_native_route")
                        return original(method, path, payload, deadline)
                    verify(prepared)
                    if (active is None or method != "POST" or len(report["calls"]) >= len(
                            prepared["schedule"]) or any((c["id"], c["arm"]) == active
                                                         for c in report["calls"])):
                        raise ValueError("comparison_native_budget")
                    arm_spec = prepared["cases"][active[0]]["arms"][active[1]]
                    check_payload(payload, arm_spec["grammar"])
                    call = {"id": active[0], "arm": active[1], "dispatch_attempted": True,
                            "sequence": len(report["calls"]), "at": datetime.now(UTC).isoformat(),
                            "payload_sha256": fingerprint(payload),
                            "input_tokens": len(payload["prompt"])}
                    report["calls"].append(call)
                    save(prepared, report)  # persisted before native POST, even if transport fails
                    try:
                        response = original(method, path, payload, deadline)
                        call["raw_response"] = copy.deepcopy(response)
                        return response
                    except Exception as error:
                        call["error"] = safe_error(error)
                        raise
                    finally:
                        save(prepared, report)

                def bounded_complete(messages, deadline, token_limit, grammar=""):
                    if active is None:
                        raise ValueError("comparison_hidden_completion")
                    spec = prepared["cases"][active[0]]["arms"][active[1]]
                    if (fingerprint(messages) != spec["prompt_sha256"]
                            or type(token_limit) is not int or token_limit != 384
                            or grammar != spec["grammar"]):
                        raise ValueError("comparison_prompt_changed")
                    return complete(messages, min(deadline, last_started + 90), token_limit, grammar)

                base._request, base._complete = request, bounded_complete
                try:
                    report["model_runtime"] = base.public_metadata()
                    runtimes = {"L0": BoundedLineRuntime(BoundedLineGenerator(base)),
                                "C2": BlockAnswerMeetingRuntime(BlockAnswerGenerator(base))}
                    for active in prepared["schedule"]:
                        verify(prepared)
                        item = prepared["cases"][active[0]]
                        if fingerprint(item["request"].model_dump()) != item["payload_sha256"]:
                            raise ValueError("comparison_request_changed")
                        arm_spec = item["arms"][active[1]]
                        runtime = runtimes[active[1]]
                        row = {"id": active[0], "arm": active[1], "structural_status": "failed",
                            "payload_sha256": item["payload_sha256"],
                            "prompt_sha256": arm_spec["prompt_sha256"],
                            "official_input_tokens": arm_spec["official_input_tokens"],
                            "unit_count": arm_spec["unit_count"],
                            "grammar_sha256": hashlib.sha256(arm_spec["grammar"].encode()).hexdigest()}
                        report["results"].append(row)
                        started = last_started = time.monotonic()
                        try:
                            with rss_samples(process, row), watchdog(process, row):
                                row["response"] = runtime.answer(item["request"])
                            row["elapsed_ms"] = (time.monotonic() - started) * 1000
                            row["worker_telemetry"] = copy.deepcopy(runtime.last_telemetry)
                            row["effective_config"] = copy.deepcopy(base.last_effective_config)
                            check_row(row, [c for c in report["calls"] if (c["id"], c["arm"]) == active])
                            row["structural_status"] = "passed"
                        except Exception as error:
                            row["error"] = safe_error(error)
                            raise
                        finally:
                            row["elapsed_ms"] = (time.monotonic() - started) * 1000
                            row["worker_telemetry"] = copy.deepcopy(runtime.last_telemetry)
                            row["effective_config"] = copy.deepcopy(base.last_effective_config)
                            save(prepared, report)
                finally:
                    base._request, base._complete = original, complete
                    base.close()
            finally:
                stop_owned(process, report)
    except Exception as error:  # noqa: BLE001 - safe codes only; preserve all partial evidence
        report["failure"] = safe_error(error)
    finally:
        if last_started is not None:
            report["last_request_through_cleanup_ms"] = (time.monotonic() - last_started) * 1000
        try:
            verify(prepared)
            report["sources_unchanged"] = True
        except Exception as error:  # noqa: BLE001 - failed final binding invalidates the whole run
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
        report["status"] = ("completed_not_semantically_verified" if report["resources_passed"]
                            else "failed")
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
