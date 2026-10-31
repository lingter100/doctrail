"""A separately registered C4 compatibility resource gate; original C4 stays closed."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

from doctrail.meeting_gguf import _integer, _json
from doctrail.meeting_thinking_transport import (
    PROTOCOL,
    ThinkingGenerator,
    request_body,
    validate_response,
)
from scripts.check_meeting_review_token_budget import load_tokenizer
from scripts.prepare_meeting_gguf import linked
from scripts.probe_meeting_blocks_resources import owned_watchdog, rss_samples
from scripts.probe_meeting_thinking_resources import count, encoded, safe_error
from scripts.probe_meeting_thinking_resources import source_files as original_source_files
from scripts.serve_meeting_thinking_compat import cleanup_owned, start_llama

ROOT = Path(__file__).resolve().parents[1]
FOLLOWUP = "meeting-thinking-c4-compat-resource-v1"
PROTOCOL_FILE = "data/evaluation/meetings-c4-compat-resource-protocol-v1.json"
PROTOCOL_SHA = "4f3f6239ff241d3555d54ddb1f753324e5f51000e9ef6bf01a646d0ab3e0802c"
ORIGINAL_FREEZE = "data/evaluation/meetings-c4-resource-source-freeze-v1.json"
ORIGINAL_FREEZE_SHA = "2ba79c7fba2ad52090392f9256396dc8a1813b6bfae31d6b06a7ba2dd9f2d701"
ORIGINAL_REPORT = "experiments/results/meetings-c4-resources-v1.json"
ORIGINAL_REPORT_SHA = "2b66105860e47180dc29ff78213d43ade81ac29ef2f17ba19ba632440e017729"
ORIGINAL_PLAN = "data/evaluation/meetings-c4-neutral-plan-v1.json"
ORIGINAL_PLAN_SHA = "ba0b3f40134f79a63eee61329ea50dbebc121d7e357a9bbbec0ff8511b4e1e6d"
NEW_FILES = {"scripts/serve_meeting_thinking_compat.py",
    "scripts/probe_meeting_thinking_compat_resources.py",
    "tests/test_meeting_thinking_compat_launcher.py",
    "tests/test_meeting_thinking_compat_resources.py"}
LITERAL = " ".join(["z"] * 2048)
COMPLETE_JSON = json.dumps({"padding": LITERAL}, separators=(",", ":"))
NORMAL_SCHEMA = {"type": "object", "properties": {"marker": {"const": "teal"}},
                 "required": ["marker"], "additionalProperties": False}
STRESS_SCHEMA = {"type": "object", "properties": {"padding": {"const": LITERAL}},
                 "required": ["padding"], "additionalProperties": False}


def path(value, *, local=False):
    root, target = ROOT.resolve(), Path(value)
    target = target if target.is_absolute() else root / target
    if ".." in target.parts or not target.is_relative_to(root):
        raise ValueError("compat_path_invalid")
    current = root
    for part in target.relative_to(root).parts:
        current /= part
        if ":" in part or linked(current):
            raise ValueError("compat_path_invalid")
    if local and (not target.is_relative_to(root / ".local") or target == root / ".local"):
        raise ValueError("compat_output_invalid")
    return target


def snapshot(value):
    with path(value).open("rb") as stream:
        raw = stream.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("compat_file_limit")
    return raw, hashlib.sha256(raw).hexdigest()


def read(value):
    raw, digest = snapshot(value)
    return _json(raw), digest


def write_new(value, content):
    target = path(value)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(encoded(content))


def replace(value, content):
    target = path(value)
    temporary = path(target.with_suffix(target.suffix + ".tmp"))
    with temporary.open("xb") as stream:
        stream.write(encoded(content))
    temporary.replace(target)


def source_files():
    # All new local imports point to these four modules or the frozen original
    # closure; no helper/global mutation is used to retarget the original runner.
    return original_source_files() | NEW_FILES | {PROTOCOL_FILE,
        "docs/MEETINGS-C4-COMPAT-PLAN.md", ORIGINAL_FREEZE, ORIGINAL_REPORT, ORIGINAL_PLAN}


def bindings(freeze_path):
    for name, digest in ((PROTOCOL_FILE, PROTOCOL_SHA), (ORIGINAL_FREEZE, ORIGINAL_FREEZE_SHA),
                         (ORIGINAL_REPORT, ORIGINAL_REPORT_SHA), (ORIGINAL_PLAN, ORIGINAL_PLAN_SHA)):
        if snapshot(name)[1] != digest:
            raise ValueError("compat_original_or_protocol_changed")
    original, _ = read(ORIGINAL_FREEZE)
    if len(original["bound_files"]) != 43:
        raise ValueError("compat_original_freeze_mismatch")
    freeze, digest = read(freeze_path)
    bound = freeze.get("bound_files", {})
    if (freeze.get("followup_id") != FOLLOWUP or set(bound) != source_files()
            or any(bound.get(p) != h for p, h in original["bound_files"].items())):
        raise ValueError("compat_source_freeze_mismatch")
    for name, expected in bound.items():
        if snapshot(name)[1] != expected:
            raise ValueError("compat_source_changed")
    return bound, digest


def committed(names):
    for name in sorted(names):
        result = subprocess.run(["git", "show", f"HEAD:{name}"], cwd=ROOT,
                                capture_output=True, check=False, timeout=15)
        if result.returncode or result.stdout != snapshot(name)[0]:
            raise ValueError("compat_uncommitted_contract")


def messages(kind, padding=0):
    if kind == "normal":
        if padding != 0:
            raise ValueError("compat_normal_padding")
        return [{"role": "system", "content": "Synthetic compatibility formatting check. "
            "Briefly consider whether 31 plus 47 is even, then return the final JSON "
            'object {"marker":"teal"}.'}, {"role": "user", "content":
            "Carry out this new neutral transport check; no factual question is involved."}]
    if kind != "stress" or type(padding) is not int or not 1 <= padding <= 6000:
        raise ValueError("compat_neutral_input_invalid")
    return [{"role": "system", "content": "Synthetic compatibility capacity check. Briefly "
        "consider whether 29 plus 35 is even, then produce a JSON object with a padding string "
        "of exactly 2048 copies of z separated by single spaces, as required by the schema."},
        {"role": "user", "content": "Meaningless input markers: " + "bx " * padding
         + "\nProduce the fixed padding object now."}]


def validate_tokenizer(metadata):
    baseline, _ = read(ORIGINAL_PLAN)
    if metadata != baseline["tokenizer"]:
        raise ValueError("compat_tokenizer_identity")


def register(plan_path, output, source_freeze, *, loader=load_tokenizer):
    target, output = path(plan_path), path(output, local=True)
    receipt_path = target.with_suffix(".preparation.json")
    if target.exists() or output.exists() or target.is_relative_to(output):
        raise ValueError("compat_output_exists")
    bound, freeze_sha = bindings(source_freeze)
    freeze_name = path(source_freeze).relative_to(ROOT).as_posix()
    committed(set(bound) | {freeze_name})
    receipt = {"followup_id": FOLLOWUP, "status": "started", "native_calls": 0,
        "source_freeze_sha256": freeze_sha, "tokenizer_loads": 0, "literal_measured": False}
    write_new(receipt_path, receipt)  # Exclusive reservation precedes even an offline load.
    try:
        receipt["tokenizer_loads"] = 1
        replace(receipt_path, receipt)
        tokenizer, metadata = loader(False)
        validate_tokenizer(metadata)
        tokens = tokenizer.encode(COMPLETE_JSON, add_special_tokens=False)
        if not isinstance(tokens, list) or not all(_integer(t) for t in tokens):
            raise ValueError("compat_literal_tokens_invalid")
        receipt.update(literal_measured=True, complete_json_retokenized_tokens=len(tokens))
        replace(receipt_path, receipt)
        if len(tokens) <= 928:
            raise ValueError("compat_literal_too_short")
        normal_n, normal_sha = count(tokenizer, messages("normal"))
        if not 0 < normal_n <= 1024:
            raise ValueError("compat_normal_input_target")
        low, high, selected = 1, 6000, None
        while low <= high:
            size = (low + high) // 2
            n, prompt_sha = count(tokenizer, messages("stress", size))
            if 4992 <= n <= 5120:
                selected = size, n, prompt_sha
                break
            if n < 4992:
                low = size + 1
            else:
                high = size - 1
        if selected is None:
            raise ValueError("compat_stress_input_unreachable")
        size, n, prompt_sha = selected
        if bindings(source_freeze) != (bound, freeze_sha):
            raise ValueError("compat_source_changed")
        receipt.update(status="passed", tokenizer=metadata, complete_json_sha256=
                       hashlib.sha256(COMPLETE_JSON.encode()).hexdigest())
        replace(receipt_path, receipt)
        plan = {"schema_version": 1, "followup_id": FOLLOWUP, "generation_protocol": PROTOCOL,
            "source_freeze": {"path": freeze_name, "sha256": freeze_sha}, "bound_files": bound,
            "preparation": {"path": receipt_path.relative_to(ROOT).as_posix(),
                            "sha256": snapshot(receipt_path)[1]},
            "output_dir": output.relative_to(ROOT).as_posix(), "tokenizer": metadata,
            "complete_json_retokenized_tokens": len(tokens), "new_native_calls": 0,
            "original_failure_sha256": ORIGINAL_REPORT_SHA, "cases": [
                {"id": "normal", "padding": 0, "input_tokens": normal_n,
                 "prompt_sha256": normal_sha, "messages": messages("normal"), "schema": NORMAL_SCHEMA},
                {"id": "stress", "padding": size, "input_tokens": n,
                 "prompt_sha256": prompt_sha, "messages": messages("stress", size), "schema": STRESS_SCHEMA}]}
        write_new(target, plan)
        return plan
    except Exception as error:
        receipt.update(status="failed_closed", error=safe_error(error))
        replace(receipt_path, receipt)
        raise


def check(plan_path, *, allow_output=False):
    plan, digest = read(plan_path)
    bound, freeze_sha = bindings(plan["source_freeze"]["path"])
    receipt, receipt_sha = read(plan["preparation"]["path"])
    validate_tokenizer(plan["tokenizer"])
    if (plan.get("followup_id") != FOLLOWUP or plan.get("generation_protocol") != PROTOCOL
            or plan.get("bound_files") != bound or plan["source_freeze"]["sha256"] != freeze_sha
            or plan.get("original_failure_sha256") != ORIGINAL_REPORT_SHA
            or plan["preparation"]["sha256"] != receipt_sha or receipt.get("status") != "passed"
            or receipt.get("followup_id") != FOLLOWUP or receipt.get("tokenizer_loads") != 1
            or receipt.get("literal_measured") is not True
            or receipt.get("source_freeze_sha256") != freeze_sha
            or receipt.get("tokenizer") != plan["tokenizer"]
            or not _integer(plan.get("complete_json_retokenized_tokens"), 929)
            or receipt.get("complete_json_retokenized_tokens") != plan["complete_json_retokenized_tokens"]
            or receipt.get("complete_json_sha256") != hashlib.sha256(COMPLETE_JSON.encode()).hexdigest()
            or [r.get("id") for r in plan.get("cases", [])] != ["normal", "stress"]):
        raise ValueError("compat_plan_mismatch")
    for row in plan["cases"]:
        kind, n = row["id"], row["input_tokens"]
        if (row["messages"] != messages(kind, row["padding"])
                or row["schema"] != (NORMAL_SCHEMA if kind == "normal" else STRESS_SCHEMA)
                or type(n) is not int or not (1 <= n <= 1024 if kind == "normal" else 4992 <= n <= 5120)
                or not isinstance(row.get("prompt_sha256"), str)
                or re.fullmatch("[a-f0-9]{64}", row["prompt_sha256"]) is None):
            raise ValueError("compat_input_contract_mismatch")
    output = path(plan["output_dir"], local=True)
    if output.exists() and not allow_output:
        raise ValueError("compat_output_exists")
    return {"plan": plan, "path": path(plan_path), "sha256": digest, "output": output}


def verify(prepared):
    current = check(prepared["path"], allow_output=True)
    if current["sha256"] != prepared["sha256"]:
        raise ValueError("compat_plan_changed")


def drain_pass(cleanup):
    drain = cleanup.get("drain", {})
    return (cleanup.get("process_started") is True and cleanup.get("cleanup_attempted") is True
        and cleanup.get("stopped") is True and cleanup.get("within_budget") is True
        and cleanup.get("cleanup_errors") == 0 and 0 <= cleanup.get("seconds", 6) <= 5
        and type(drain.get("emitted_bytes")) is int and drain["emitted_bytes"] == 0
        and drain.get("started") is True and drain.get("eof") is True and drain.get("joined") is True
        and drain.get("read_errors") == 0 and drain.get("join_errors") == 0
        and drain.get("raw_content_retained") is False and drain.get("chunk_bytes") == 8192)


def ready(report):
    return ("error" not in report and report.get("sources_unchanged") is True
        and report.get("metadata_recovery") is True and report.get("restarts") == 1
        and report.get("quality_calls") == 0 and report.get("elapsed_seconds", 1201) <= 1200
        and report.get("last_request_through_cleanup_seconds", 121) <= 120
        and len(report.get("cleanup", [])) == 2 and all(drain_pass(c) for c in report["cleanup"])
        and all(report.get(name, {}).get("watchdog_fired") is False
            and report.get(name, {}).get("watchdog_joined") is True
            for name in ("phase_watchdog", "recovery_watchdog"))
        and [r.get("id") for r in report.get("calls", [])] == ["normal", "stress"]
        and all(r.get("passed") is True and r.get("dispatch_started") is True and "error" not in r
            and r.get("request_seconds", 91) <= 90 and r.get("watchdog", {}).get("watchdog_fired") is False
            and r.get("watchdog", {}).get("watchdog_joined") is True for r in report["calls"]))


def run(prepared, *, factory=start_llama, generator_factory=ThinkingGenerator):
    verify(prepared)
    plan = prepared["plan"]
    committed(set(plan["bound_files"]) | {plan["source_freeze"]["path"], plan["preparation"]["path"],
              prepared["path"].relative_to(ROOT).as_posix()})
    prepared["output"].mkdir(parents=True, exist_ok=False)
    started, last_request = time.monotonic(), None
    report = {"followup_id": FOLLOWUP, "generation_protocol": PROTOCOL,
        "plan_sha256": prepared["sha256"], "original_failure_sha256": ORIGINAL_REPORT_SHA,
        "status": "running", "calls": [], "cleanup": [], "quality_calls": 0, "restarts": 0,
        "sources_unchanged": False, "metadata_recovery": False}
    def save():
        replace(prepared["output"] / "report.json", report)
    save()
    try:
        initial_cleanup = {}
        report["cleanup"].append(initial_cleanup)
        with factory(log_dir=prepared["output"] / "initial", phase_deadline=started + 1200,
                     telemetry=initial_cleanup) as svc:
            gen = generator_factory(svc.url, svc.token, svc.manifest)
            try:
                with owned_watchdog(svc.process, report.setdefault("phase_watchdog", {}),
                                    max(0.01, started + 1200 - time.monotonic())):
                    gen.load()
                    report["identity"] = gen.public_metadata()
                    for case in plan["cases"]:
                        verify(prepared)
                        if svc.drain.emitted_bytes or svc.drain.read_errors:
                            raise ValueError("compat_native_diagnostics")
                        row = {"id": case["id"], "dispatch_started": False, "passed": False}
                        report["calls"].append(row)
                        last_request = time.monotonic()
                        def before(prompt, tokens, payload, case=case, row=row):
                            verify(prepared)
                            if (len(tokens) != case["input_tokens"] or hashlib.sha256(
                                    prompt.encode()).hexdigest() != case["prompt_sha256"]):
                                raise ValueError("compat_native_input_drift")
                            row.update(prompt=prompt, input_token_ids=tokens, request=payload,
                                       dispatch_started=True)
                            save()
                        def observe(key, value, row=row):
                            row[key] = value
                            save()
                        try:
                            with owned_watchdog(svc.process, row.setdefault("watchdog", {}), 90), \
                                    rss_samples(svc.process, row.setdefault("memory", {})):
                                result = gen.generate_neutral(case["messages"], case["schema"],
                                    stress=case["id"] == "stress", before_dispatch=before, observe=observe)
                            row.update(result=dataclasses.asdict(result),
                                       request_seconds=time.monotonic() - last_request)
                            if row["watchdog"]["watchdog_fired"] or row["request_seconds"] > 90:
                                raise ValueError("compat_request_timeout")
                            row["passed"] = True
                            save()
                        except Exception as error:
                            row["error"] = safe_error(error)
                            raise
            finally:
                gen.close()
                cleanup_owned(svc.process, svc.drain, svc.cleanup)
                if last_request is not None:
                    report["last_request_through_cleanup_seconds"] = time.monotonic() - last_request
        if not drain_pass(report["cleanup"][0]):
            raise ValueError("compat_diagnostic_or_cleanup_failure")
        verify(prepared)
        report["restarts"] = 1
        recovery_cleanup = {}
        report["cleanup"].append(recovery_cleanup)
        with factory(log_dir=prepared["output"] / "recovery", phase_deadline=started + 1200,
                     telemetry=recovery_cleanup) as svc:
            gen = generator_factory(svc.url, svc.token, svc.manifest)
            try:
                with owned_watchdog(svc.process, report.setdefault("recovery_watchdog", {}),
                                    max(0.01, started + 1200 - time.monotonic())):
                    gen.load()
                    report["metadata_recovery"] = gen.public_metadata() == report["identity"]
            finally:
                gen.close()
                cleanup_owned(svc.process, svc.drain, svc.cleanup)
        verify(prepared)
        report["sources_unchanged"] = True
    except Exception as error:  # noqa: BLE001 - retain failures without model retries
        report["error"] = safe_error(error)
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        report["status"] = "passed_resources_only" if ready(report) else "failed_closed"
        save()
    return report


def replay(plan_path, report_path):
    prepared = check(plan_path, allow_output=True)
    report, _ = read(report_path)
    if (report.get("followup_id") != FOLLOWUP or report.get("generation_protocol") != PROTOCOL
            or report.get("plan_sha256") != prepared["sha256"]
            or report.get("original_failure_sha256") != ORIGINAL_REPORT_SHA
            or len(report.get("calls", [])) > 2):
        raise ValueError("compat_report_binding")
    for row, case in zip(report.get("calls", []), prepared["plan"]["cases"], strict=False):
        if not row.get("passed"):
            continue
        if (row["id"] != case["id"] or row["request"] != request_body(case["messages"], case["schema"])
                or hashlib.sha256(row["prompt"].encode()).hexdigest() != case["prompt_sha256"]
                or len(row["input_token_ids"]) != case["input_tokens"]):
            raise ValueError("compat_replay_input_mismatch")
        expected = validate_response(row["response"], prompt=row["prompt"],
            input_tokens=case["input_tokens"], stress=case["id"] == "stress")
        if any(row["result"].get(k) != v for k, v in expected.items()):
            raise ValueError("compat_replay_result_mismatch")
        tokens = row["final_token_ids"]
        if (not isinstance(tokens, list) or not all(_integer(t) for t in tokens)
                or row["result"]["final_retokenized_tokens"] != len(tokens)
                or (case["id"] == "normal" and not 0 < len(tokens) <= 384)):
            raise ValueError("compat_replay_token_mismatch")
    status = "passed_resources_only" if ready(report) else "failed_closed"
    if report.get("status") != status:
        raise ValueError("compat_replay_status_mismatch")
    return {"followup_id": FOLLOWUP, "status": status, "replayed": True, "quality_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["register", "check", "run", "replay"])
    parser.add_argument("--plan", required=True)
    parser.add_argument("--source-freeze")
    parser.add_argument("--output")
    parser.add_argument("--report")
    args = parser.parse_args()
    try:
        if args.mode == "register":
            register(args.plan, args.output, args.source_freeze)
            result = {"status": "registered", "new_native_calls": 0}
        elif args.mode == "check":
            check(args.plan)
            result = {"status": "checked", "new_native_calls": 0}
        elif args.mode == "run":
            result = {"status": run(check(args.plan))["status"]}
        else:
            result = replay(args.plan, args.report)
        print(json.dumps(result))
        if result["status"] == "failed_closed":
            raise SystemExit(1)
    except Exception as error:  # noqa: BLE001 - no diagnostic contents in console
        parser.exit(1, safe_error(error) + "\n")


if __name__ == "__main__":
    main()
