"""C4-P0 register/check/run/replay. Two neutral calls, no quality-data access."""
from __future__ import annotations

import argparse
import ast
import dataclasses
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

from doctrail.meeting_gguf import _integer, _json
from doctrail.meeting_thinking_transport import (
    MODEL_ID,
    MODEL_REVISION,
    PREAMBLE,
    PROTOCOL,
    ThinkingGenerator,
    request_body,
    validate_response,
)
from scripts.check_meeting_review_token_budget import load_tokenizer
from scripts.prepare_meeting_gguf import linked
from scripts.probe_meeting_blocks_resources import owned_watchdog, rss_samples
from scripts.serve_meeting_thinking import start_llama, stop_owned

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_FILE = "data/evaluation/meetings-c4-resource-protocol-v1.json"
PROTOCOL_SHA = "498297947a61e653f23fb8d5b04431d85b3cffff3915a1da71fd1d9419fe4314"
ENTRY_FILES = {"src/doctrail/meeting_thinking_transport.py", "scripts/serve_meeting_thinking.py",
    "scripts/probe_meeting_thinking_resources.py", "tests/test_meeting_thinking_transport.py",
    "tests/test_meeting_thinking_resources.py"}
METADATA_FILES = {PROTOCOL_FILE, "docs/MEETINGS-C4-RESOURCE-DESIGN.md", "pyproject.toml",
                  "uv.lock", "data/models/meetings-generation-qwen35-v1.json"}
NORMAL_SCHEMA = {"type": "object", "properties": {"marker": {"const": "teal"}},
                 "required": ["marker"], "additionalProperties": False}
STRESS_SCHEMA = {"type": "object", "properties": {"padding": {
    "type": "string", "minLength": 10000}}, "required": ["padding"],
    "additionalProperties": False}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            + "\n").encode("utf-8")


def path(value, *, local=False):
    root = ROOT.resolve()
    item = Path(value)
    if not item.is_absolute():
        item = root / item
    if ".." in item.parts or not item.is_relative_to(root):
        raise ValueError("thinking_path_invalid")
    current = root
    for component in item.relative_to(root).parts:
        if ":" in component:
            raise ValueError("thinking_path_invalid")
        current /= component
        if linked(current):
            raise ValueError("thinking_linked_path")
    if local and (not item.is_relative_to(root / ".local") or item == root / ".local"):
        raise ValueError("thinking_output_invalid")
    return item


def snapshot(value):
    with path(value).open("rb") as stream:
        raw = stream.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("thinking_file_limit")
    return raw, hashlib.sha256(raw).hexdigest()


def read(value):
    raw, digest = snapshot(value)
    return _json(raw), digest


def write_new(value, content):
    target = path(value)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(encoded(content))


def source_files():
    """Bind transitive repository imports, including lazy imports, without executing them."""
    pending, found = list(ENTRY_FILES), set()
    while pending:
        name = pending.pop()
        if name in found:
            continue
        found.add(name)
        tree = ast.parse(snapshot(name)[0])
        module_parts = Path(name).with_suffix("").parts
        if module_parts[0] == "src":
            module_parts = module_parts[1:]
        package = module_parts[:-1]
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    if node.level > len(package):
                        raise ValueError("thinking_relative_import_invalid")
                    base = package[:len(package) - node.level + 1]
                    module = ".".join((*base, *node.module.split("."))) if node.module else ".".join(base)
                else:
                    module = node.module or ""
                modules = [module, *(f"{module}.{a.name}" for a in node.names)]
            for module in modules:
                if not module:
                    continue
                relative = module.replace(".", "/")
                for candidate in (f"src/{relative}.py", f"{relative}.py",
                                  f"src/{relative}/__init__.py", f"{relative}/__init__.py"):
                    if path(candidate).is_file() and candidate not in found:
                        pending.append(candidate)
                # Python executes parent package initializers as part of an import.
                for length in range(1, len(module.split("."))):
                    parent = "/".join(module.split(".")[:length])
                    for candidate in (f"src/{parent}/__init__.py", f"{parent}/__init__.py"):
                        if path(candidate).is_file() and candidate not in found:
                            pending.append(candidate)
    return found | METADATA_FILES


def bindings(freeze_path):
    freeze, digest = read(freeze_path)
    bound = freeze.get("bound_files")
    if (freeze.get("candidate") != PROTOCOL or not isinstance(bound, dict)
            or set(bound) != source_files() or bound.get(PROTOCOL_FILE) != PROTOCOL_SHA):
        raise ValueError("thinking_source_freeze_mismatch")
    for name, expected in bound.items():
        if snapshot(name)[1] != expected:
            raise ValueError("thinking_source_changed")
    return bound, digest


def committed(names):
    for name in sorted(names):
        expected = snapshot(name)[0]
        result = subprocess.run(["git", "show", f"HEAD:{name}"], cwd=ROOT,
            capture_output=True, check=False, timeout=15)
        if result.returncode or result.stdout != expected:
            raise ValueError("thinking_uncommitted_contract")


def messages(kind, padding=0):
    if kind == "normal":
        return [{"role": "system", "content": "This is a synthetic transport check, not Q&A. "
            "Think briefly about whether 17 plus 25 is even. Then return only the JSON "
            'object {"marker":"teal"} as final content.'},
            {"role": "user", "content": "Perform the neutral formatting check."}]
    if kind != "stress" or type(padding) is not int or not 1 <= padding <= 6000:
        raise ValueError("thinking_neutral_input_invalid")
    return [{"role": "system", "content": "Synthetic resource stress only. Think briefly about "
        "whether 19 plus 23 is even, then emit a JSON object whose padding string contains "
        "at least 10000 repetitions of the letter z separated by spaces. Do not summarize."},
        {"role": "user", "content": "Mechanical input padding, without facts: " + "ax " * padding
         + "\nNow produce the requested long padding string."}]


def count(tokenizer, payload):
    rendered = tokenizer.apply_chat_template(payload, tokenize=False,
        add_generation_prompt=True, enable_thinking=True)
    if not isinstance(rendered, str) or not rendered.endswith(PREAMBLE):
        raise ValueError("thinking_offline_template_mismatch")
    tokens = tokenizer.encode(rendered, add_special_tokens=False)
    if not isinstance(tokens, list) or not tokens or not all(_integer(t) for t in tokens):
        raise ValueError("thinking_offline_tokens_invalid")
    return len(tokens), hashlib.sha256(rendered.encode()).hexdigest()


def register(plan_path, output, source_freeze, *, loader=load_tokenizer):
    target, output = path(plan_path), path(output, local=True)
    if target.exists() or output.exists() or target.is_relative_to(output):
        raise ValueError("thinking_output_exists")
    bound, freeze_sha = bindings(source_freeze)
    freeze_name = path(source_freeze).relative_to(ROOT).as_posix()
    committed(set(bound) | {freeze_name})
    tokenizer, metadata = loader(False)
    if (metadata.get("repo_id") != MODEL_ID or metadata.get("revision") != MODEL_REVISION
            or metadata.get("download_authorized") is not False
            or metadata.get("trust_remote_code") is not False):
        raise ValueError("thinking_tokenizer_identity")
    normal_n, normal_sha = count(tokenizer, messages("normal"))
    if not 0 < normal_n <= 1024:
        raise ValueError("thinking_normal_input_target")
    # Mechanical neutral length search only; no generation or quality texts.
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
        raise ValueError("thinking_stress_input_unreachable")
    size, n, prompt_sha = selected
    plan = {"schema_version": 1, "candidate": PROTOCOL,
        "source_freeze": {"path": freeze_name, "sha256": freeze_sha}, "bound_files": bound,
        "output_dir": output.relative_to(ROOT).as_posix(), "tokenizer": metadata,
        "native_calls": 0, "quality_calls": 0, "cases": [
            {"id": "normal", "padding": 0, "messages": messages("normal"),
             "schema": NORMAL_SCHEMA, "input_tokens": normal_n, "prompt_sha256": normal_sha},
            {"id": "stress", "padding": size, "messages": messages("stress", size),
             "schema": STRESS_SCHEMA, "input_tokens": n, "prompt_sha256": prompt_sha}]}
    if bindings(source_freeze) != (bound, freeze_sha):
        raise ValueError("thinking_source_changed")
    write_new(target, plan)
    return plan


def check(plan_path, *, allow_output=False):
    plan, digest = read(plan_path)
    bound, freeze_sha = bindings(plan["source_freeze"]["path"])
    if (plan.get("candidate") != PROTOCOL or plan.get("bound_files") != bound
            or plan["source_freeze"].get("sha256") != freeze_sha
            or [r.get("id") for r in plan.get("cases", [])] != ["normal", "stress"]):
        raise ValueError("thinking_plan_mismatch")
    for row in plan["cases"]:
        kind, n = row["id"], row["input_tokens"]
        if (row["messages"] != messages(kind, row["padding"])
                or row["schema"] != (NORMAL_SCHEMA if kind == "normal" else STRESS_SCHEMA)
                or type(n) is not int or not (1 <= n <= 1024 if kind == "normal"
                                            else 4992 <= n <= 5120)
                or re.fullmatch("[a-f0-9]{64}", row["prompt_sha256"]) is None):
            raise ValueError("thinking_input_contract_mismatch")
    output = path(plan["output_dir"], local=True)
    if output.exists() and not allow_output:
        raise ValueError("thinking_output_exists")
    return {"plan": plan, "path": path(plan_path), "sha256": digest, "output": output}


def verify(prepared):
    current = check(prepared["path"], allow_output=True)
    if current["sha256"] != prepared["sha256"]:
        raise ValueError("thinking_plan_changed")


def safe_error(error):
    code = getattr(error, "code", None)
    if code is None and type(error) is ValueError:
        code = str(error)
    return code if isinstance(code, str) and re.fullmatch("[a-z_]{1,100}", code) else type(error).__name__


def save(prepared, report):
    target = prepared["output"] / "report.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(encoded(report))
    temporary.replace(target)


def run(prepared, *, factory=start_llama, generator_factory=ThinkingGenerator):
    verify(prepared)
    plan = prepared["plan"]
    committed(set(plan["bound_files"]) | {plan["source_freeze"]["path"],
              prepared["path"].relative_to(ROOT).as_posix()})
    prepared["output"].mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = {"candidate": PROTOCOL, "plan_sha256": prepared["sha256"], "status": "running",
        "calls": [], "cleanup": [], "quality_calls": 0, "restarts": 0,
        "sources_unchanged": False, "metadata_recovery": False}
    save(prepared, report)
    last_request = None
    try:
        with factory(log_dir=prepared["output"] / "initial", phase_deadline=started + 1200) as svc:
            report["cleanup"].append(svc.cleanup)
            gen = generator_factory(svc.url, svc.token, svc.manifest)
            try:
                with owned_watchdog(svc.process, report.setdefault("phase_watchdog", {}),
                                    seconds=max(0.01, started + 1200 - time.monotonic())):
                    gen.load()
                    report["identity"] = gen.public_metadata()
                    for case in plan["cases"]:
                        verify(prepared)
                        row = {"id": case["id"], "dispatch_started": False, "passed": False}
                        report["calls"].append(row)
                        request_start = time.monotonic()
                        last_request = request_start
                        def before(prompt, tokens, payload, case=case, row=row):
                            verify(prepared)
                            if (len(tokens) != case["input_tokens"] or hashlib.sha256(
                                    prompt.encode()).hexdigest() != case["prompt_sha256"]):
                                raise ValueError("thinking_native_input_drift")
                            row.update(prompt=prompt, input_token_ids=tokens, request=payload,
                                       dispatch_started=True)
                            save(prepared, report)
                        def observe(key, value, row=row):
                            row[key] = value
                            save(prepared, report)
                        try:
                            with owned_watchdog(svc.process, row.setdefault("watchdog", {}), 90), \
                                    rss_samples(svc.process, row.setdefault("memory", {})):
                                result = gen.generate_neutral(case["messages"], case["schema"],
                                    stress=case["id"] == "stress", before_dispatch=before,
                                    observe=observe)
                            row["result"] = dataclasses.asdict(result)
                            row["request_seconds"] = time.monotonic() - request_start
                            if row["watchdog"]["watchdog_fired"] or row["request_seconds"] > 90:
                                raise ValueError("thinking_request_timeout")
                            row["passed"] = True
                            save(prepared, report)
                        except Exception as error:
                            row["error"] = safe_error(error)
                            raise
            finally:
                gen.close()
                stop_owned(svc.process, svc.cleanup)
                if last_request is not None:
                    report["last_request_through_cleanup_seconds"] = time.monotonic() - last_request
        verify(prepared)
        report["restarts"] = 1
        with factory(log_dir=prepared["output"] / "recovery", phase_deadline=started + 1200) as svc:
            report["cleanup"].append(svc.cleanup)
            gen = generator_factory(svc.url, svc.token, svc.manifest)
            try:
                with owned_watchdog(svc.process, report.setdefault("recovery_watchdog", {}),
                                    seconds=max(0.01, started + 1200 - time.monotonic())):
                    gen.load()
                    report["metadata_recovery"] = gen.public_metadata() == report["identity"]
            finally:
                gen.close()
                stop_owned(svc.process, svc.cleanup)
        verify(prepared)
        report["sources_unchanged"] = True
    except Exception as error:  # noqa: BLE001 - preserve the once-only failure safely
        report["error"] = safe_error(error)
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        report["log_bytes"] = sum(p.stat().st_size for p in prepared["output"].rglob("*.log"))
        report["status"] = "passed_resources_only" if ready(report) else "failed_closed"
        save(prepared, report)
    return report


def ready(report):
    return ("error" not in report and report.get("sources_unchanged") is True
        and report.get("metadata_recovery") is True and report.get("restarts") == 1
        and report.get("quality_calls") == 0 and report.get("log_bytes") == 0
        and report.get("elapsed_seconds", 1201) <= 1200
        and report.get("last_request_through_cleanup_seconds", 121) <= 120
        and all(report.get(name, {}).get("watchdog_fired") is False
                and report.get(name, {}).get("watchdog_joined") is True
                for name in ("phase_watchdog", "recovery_watchdog"))
        and len(report.get("cleanup", [])) == 2
        and all(c.get("within_budget") is True and c.get("stopped") is True
                and c.get("seconds", 6) <= 5 for c in report["cleanup"])
        and [c.get("id") for c in report.get("calls", [])] == ["normal", "stress"]
        and all(c.get("passed") is True and c.get("dispatch_started") is True
            and c.get("request_seconds", 91) <= 90 and "error" not in c
            and c.get("watchdog", {}).get("watchdog_fired") is False
            and c.get("watchdog", {}).get("watchdog_joined") is True for c in report["calls"]))


def replay(plan_path, report_path):
    prepared = check(plan_path, allow_output=True)
    report, _ = read(report_path)
    if report.get("candidate") != PROTOCOL or report.get("plan_sha256") != prepared["sha256"]:
        raise ValueError("thinking_report_binding")
    for row, case in zip(report.get("calls", []), prepared["plan"]["cases"], strict=False):
        if not row.get("passed"):
            continue
        prompt = row["prompt"]
        if (row["id"] != case["id"] or row["request"] != request_body(case["messages"], case["schema"])
                or hashlib.sha256(prompt.encode()).hexdigest() != case["prompt_sha256"]
                or len(row["input_token_ids"]) != case["input_tokens"]):
            raise ValueError("thinking_replay_input_mismatch")
        result = validate_response(row["response"], prompt=prompt,
                                   input_tokens=case["input_tokens"], stress=case["id"] == "stress")
        if any(row["result"].get(k) != v for k, v in result.items()):
            raise ValueError("thinking_replay_result_mismatch")
        tokens = row["final_token_ids"]
        if (not isinstance(tokens, list) or not all(_integer(t) for t in tokens)
                or row["result"]["final_retokenized_tokens"] != len(tokens)
                or (case["id"] == "normal" and not 0 < len(tokens) <= 384)):
            raise ValueError("thinking_replay_token_mismatch")
    expected = "passed_resources_only" if ready(report) else "failed_closed"
    if report.get("status") != expected:
        raise ValueError("thinking_replay_status_mismatch")
    return {"status": expected, "replayed": True, "quality_calls": 0}


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
            result = {"status": "registered", "native_calls": 0}
        elif args.mode == "check":
            check(args.plan)
            result = {"status": "checked", "native_calls": 0}
        elif args.mode == "run":
            result = {"status": run(check(args.plan))["status"]}
        else:
            result = replay(args.plan, args.report)
        print(json.dumps(result))
        if result["status"] == "failed_closed":
            raise SystemExit(1)
    except Exception as error:  # noqa: BLE001 - metadata-only console, raw stays in report
        parser.exit(1, safe_error(error) + "\n")


if __name__ == "__main__":
    main()
