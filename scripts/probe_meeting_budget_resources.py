"""Four new symmetric neutral resource calls; no quality datasets or retries.

Preparation requires both successful frozen-input surveys. Resource-only stress
grammar is never exported into the quality runner. Existing neutral runs stay
closed. Every dispatch is persisted before the HTTP request.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import shutil
import subprocess
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
from scripts.prepare_meeting_budget_inputs import (
    ARMS,
    LEGACY_FREEZES,
    PHASE_PATHS,
    PROTOCOL_FILE,
    PROTOCOL_SHA256,
    _tokenizer_metadata,
    canonical,
    encoded,
)
from scripts.prepare_meeting_budget_inputs import FILES as PREPARATION_FILES
from scripts.probe_meeting_answer_review import native_service, safe_error
from scripts.probe_meeting_blocks_resources import owned_watchdog

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = "meeting-answer-blocks-c2-input-budget-resources-v1"
STRESS_GRAMMAR = 'root ::= ("z "){600}\n'
LIMITS = {"input_tokens": 5120, "context_tokens": 6144, "output_tokens": 384,
    "request_seconds": 90, "cleanup_seconds": 5, "request_and_cleanup_seconds": 120,
    "native_calls": 4, "overall_seconds": 2400, "warmup_calls": 0, "retries": 0}
ORDER = [("normal", "L0"), ("normal", "C2"), ("stress", "C2"), ("stress", "L0")]
NEW_FILES = {
    "src/doctrail/meeting_input_budget.py", "scripts/prepare_meeting_budget_inputs.py",
    "tests/test_meeting_input_budget.py", "tests/test_prepare_meeting_budget_inputs.py",
    "scripts/probe_meeting_budget_comparison.py", "scripts/audit_meeting_budget_comparison.py",
    "tests/test_probe_meeting_budget_comparison.py", "tests/test_audit_meeting_budget_comparison.py",
    "scripts/probe_meeting_budget_resources.py", "tests/test_probe_meeting_budget_resources.py",
}
BYTE_LIMIT = 16 * 1024 * 1024


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def path(value, *, local=False):
    root = ROOT.resolve()
    item = Path(value)
    item = item if item.is_absolute() else root / item
    if ".." in item.parts or not item.is_relative_to(root):
        raise ValueError("resource_path_invalid")
    current = root
    for component in item.relative_to(root).parts:
        if ":" in component:
            raise ValueError("resource_path_invalid")
        current /= component
        if current.is_symlink() or (current.exists() and
                getattr(current.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("resource_linked_path")
    item = item.resolve()
    if local and (not item.is_relative_to(root / ".local") or item == root / ".local"):
        raise ValueError("resource_output_invalid")
    return item


def snapshot(value):
    item = path(value)
    with item.open("rb") as stream:
        raw = stream.read(BYTE_LIMIT + 1)
    if len(raw) > BYTE_LIMIT:
        raise ValueError("resource_snapshot_limit")
    return raw, hashlib.sha256(raw).hexdigest()


def read(value, expected=None):
    raw, digest = snapshot(value)
    if expected is not None and digest != expected:
        raise ValueError("resource_hash_mismatch")
    return strict_json(raw.decode("utf-8")), digest


def write_new(value, content):
    target = path(value)
    raw = encoded(content)
    if len(raw) > BYTE_LIMIT:
        raise ValueError("resource_snapshot_limit")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(raw)


def name(value):
    return path(value).relative_to(ROOT.resolve()).as_posix()


def source_bindings(freeze_path):
    freeze, _ = read(freeze_path)
    bindings = freeze.get("bound_files", {})
    if (not NEW_FILES | {PROTOCOL_FILE, *LEGACY_FREEZES} <= bindings.keys()
            or bindings.get(PROTOCOL_FILE) != PROTOCOL_SHA256):
        raise ValueError("resource_source_freeze_incomplete")
    # A resource source set includes code/metadata only, never question/oracle bodies.
    files = {k: bindings[k] for k in NEW_FILES | {PROTOCOL_FILE, *LEGACY_FREEZES}}
    protocol, _ = read(PROTOCOL_FILE, PROTOCOL_SHA256)
    for legacy_name in LEGACY_FREEZES:
        legacy, _ = read(legacy_name, protocol["bound_files"][legacy_name])
        if bindings[legacy_name] != protocol["bound_files"][legacy_name]:
            raise ValueError("resource_legacy_freeze_mismatch")
        files.update(legacy["bound_files"])
    for k, v in protocol["bound_files"].items():
        if k.startswith("docs/"):
            files[k] = v
    if bindings != files:
        raise ValueError("resource_source_freeze_mismatch")
    for k, v in files.items():
        if snapshot(k)[1] != v:
            raise ValueError("resource_source_changed")
    return dict(sorted(files.items()))


def survey_reference(value, phase, freeze_path):
    if phase not in PHASE_PATHS:
        raise ValueError("resource_survey_phase")
    receipt, digest = read(value)
    count = 16 if phase == "calibration" else 24
    freeze_sha = snapshot(freeze_path)[1]
    code = source_bindings(freeze_path)
    protocol, _ = read(PROTOCOL_FILE, PROTOCOL_SHA256)
    expected_code = {k: code[k] for k in PREPARATION_FILES}
    for freeze_name in LEGACY_FREEZES:
        old, _ = read(freeze_name, protocol["bound_files"][freeze_name])
        expected_code.update(old["bound_files"])
    expected_code.update({k: v for k, v in protocol["bound_files"].items() if k.startswith("docs/")})
    if (receipt.get("candidate") != "meeting-answer-blocks-c2-input-budget-v1"
            or receipt.get("phase") != phase or receipt.get("status") != "passed"
            or receipt.get("payloads_preserved") is not True
            or receipt.get("errors") != []
            or receipt.get("protocol_deviation") != "equal_input_cap_4096_to_5120_after_length_metadata"
            or receipt.get("bound_files") != expected_code
            or receipt.get("snapshots", {}).get(PROTOCOL_FILE, {}).get("sha256") != PROTOCOL_SHA256
            or any(receipt.get("snapshots", {}).get(p, {}).get("sha256") != protocol["bound_files"].get(p)
                   or p not in protocol["bound_files"] for p in PHASE_PATHS[phase])
            or receipt.get("snapshots", {}).get(name(freeze_path), {}).get("sha256") != freeze_sha
            or any(type(receipt.get(k)) is not int or receipt[k] != 0
                   for k in ("model_calls", "native_calls", "downloads"))
            or any(type(receipt.get("summary", {}).get(k)) is not int or
                   receipt["summary"][k] != v for k, v in {
                "total_arms": count, "measured_arms": count, "unknown_arms": 0,
                "failed_arms": 0, "new_5120_pass": count, "new_5120_fail": 0}.items())):
        raise ValueError("resource_survey_not_passed")
    _tokenizer_metadata(receipt.get("tokenizer"))
    rows = receipt.get("cases", [])
    if (not isinstance(rows, list) or len(rows) * 2 != count
            or any(not isinstance(r, dict) or not isinstance(r.get("id"), str) or not r["id"]
                   for r in rows) or len({r["id"] for r in rows}) != len(rows)):
        raise ValueError("resource_survey_rows")
    measured = []
    for row in rows:
        if (row.get("payload_preserved") is not True or set(row.get("arms", {})) != {"L0", "C2"}):
            raise ValueError("resource_survey_rows")
        for arm in ("L0", "C2"):
            result = row["arms"][arm]
            n = result.get("official_input_tokens")
            if (type(n) is not int or not 0 < n <= 5120 or result.get("error_code") is not None
                    or result.get("new_5120_pass") is not True
                    or result.get("old_4096_pass") is not (n <= 4096)):
                raise ValueError("resource_survey_rows")
            measured.append(n)
    if (receipt["summary"].get("old_4096_pass") != sum(n <= 4096 for n in measured)
            or receipt["summary"].get("old_4096_fail") != sum(n > 4096 for n in measured)):
        raise ValueError("resource_survey_rows")
    return {"file": name(value), "sha256": digest}


def dto(texts, query):
    return AnswerRequest(schema_version=1, query=query, contexts=[{
        "document_id": f"budget-neutral-{i}", "revision": 1, "chunk_id": f"budget-neutral-{i}-0",
        "title": "Synthetic budget resource fixture", "page": None, "meeting_date": None,
        "text": text, "start_offset": 0, "end_offset": len(text)}
        for i, text in enumerate(texts)])


def describe(request, tokenizer, counter):
    from doctrail.meeting_answer_spans import span_answer_grammar
    result = {}
    for arm, (catalog_fn, prompt_fn) in ARMS.items():
        catalog = catalog_fn(request.contexts)
        prompt = prompt_fn(request.query, catalog)
        n = counter(tokenizer, prompt)
        if type(n) is not int or n <= 0:
            raise ValueError("resource_official_count_invalid")
        result[arm] = {"input_tokens": n, "prompt_sha256": fingerprint(prompt),
            "grammar_sha256": hashlib.sha256(span_answer_grammar(catalog).encode()).hexdigest()}
    return result


def synthetic_cases(tokenizer, counter):
    normal = dto(["The synthetic badge is copper."], "What color is the synthetic badge?")
    normal_meta = describe(normal, tokenizer, counter)
    if max(v["input_tokens"] for v in normal_meta.values()) > 1024:
        raise ValueError("resource_normal_token_target")
    # Mechanical length search only, before any native generation. Ten whole
    # single-paragraph contexts keep both catalogs at ten evidence units.
    # Distinct meaningless marker strings provide fine token-length increments.
    selected = None
    for count in range(1, 131):
        texts = [f"Neutral capacity segment {i:02d}: " +
                 " ".join(f"m{i:02d}{j:03d}" for j in range(count))
                 for i in range(10)]
        request = dto(texts, "Repeat the literal marker z with spaces for this resource test.")
        meta = describe(request, tokenizer, counter)
        values = [v["input_tokens"] for v in meta.values()]
        if 4992 <= max(values) <= 5120 and min(values) > 4096:
            selected = request, meta
            break
        if max(values) > 5120:
            break
    if selected is None:
        raise ValueError("resource_token_target_unreachable")
    return [{"id": kind, "payload": request.model_dump(),
             "official_input_tokens": {a: x["input_tokens"] for a, x in meta.items()},
             "prompt_sha256": {a: x["prompt_sha256"] for a, x in meta.items()},
             "grammar_sha256": {a: x["grammar_sha256"] for a, x in meta.items()}}
            for kind, request, meta in [("normal", normal, normal_meta),
                                       ("stress", selected[0], selected[1])]]


def register(plan_path, output, *, source_freeze, calibration_receipt, validation_receipt,
             runtime_receipt, loader=None, counter=None):
    from scripts.check_meeting_review_token_budget import count_prompt, load_tokenizer
    target, output = path(plan_path), path(output, local=True)
    if target.exists() or output.exists() or target.is_relative_to(output):
        raise ValueError("resource_output_exists_or_invalid")
    bindings = source_bindings(source_freeze)
    surveys = {p: survey_reference(v, p, source_freeze) for p, v in (
        ("calibration", calibration_receipt), ("validation", validation_receipt))}
    receipt, _ = read(runtime_receipt)
    tokenizer, metadata = (loader or load_tokenizer)(False)
    _tokenizer_metadata(metadata)
    if any(fingerprint(read(ref["file"], ref["sha256"])[0].get("tokenizer")) != fingerprint(metadata)
           for ref in surveys.values()):
        raise ValueError("resource_survey_tokenizer_mismatch")
    cases = synthetic_cases(tokenizer, counter or count_prompt)
    plan = {"schema_version": 1, "candidate": CANDIDATE, "protocol_sha256": PROTOCOL_SHA256,
        "limits": LIMITS, "bound_files": bindings, "output_dir": name(output),
        "source_freeze": {"file": name(source_freeze), "sha256": snapshot(source_freeze)[1]},
        "survey_receipts": surveys, "runtime_receipt_sha256": fingerprint(receipt),
        "tokenizer": metadata, "cases": cases, "fixture_sha256": fingerprint(cases),
        "stress_grammar": STRESS_GRAMMAR, "normal_expected_terms": ["copper"],
        "model_calls": 0, "native_calls": 0, "human_review_count": 0}
    if source_bindings(source_freeze) != bindings:
        raise ValueError("resource_source_changed")
    for p, ref in surveys.items():
        if survey_reference(ref["file"], p, source_freeze) != ref:
            raise ValueError("resource_survey_changed")
    write_new(target, plan)
    return plan


def prepare(plan_path):
    plan, digest = read(plan_path)
    if (type(plan.get("schema_version")) is not int or plan["schema_version"] != 1
            or plan.get("candidate") != CANDIDATE or plan.get("protocol_sha256") != PROTOCOL_SHA256
            or fingerprint(plan.get("limits")) != fingerprint(LIMITS)
            or plan.get("stress_grammar") != STRESS_GRAMMAR
            or plan.get("normal_expected_terms") != ["copper"]
            or [c.get("id") for c in plan.get("cases", [])] != ["normal", "stress"]
            or plan.get("fixture_sha256") != fingerprint(plan["cases"])
            or set(plan.get("survey_receipts", {})) != {"calibration", "validation"}):
        raise ValueError("resource_plan_mismatch")
    output = path(plan["output_dir"], local=True)
    protected = [path(plan_path), path(plan["source_freeze"]["file"]),
                 *(path(r["file"]) for r in plan["survey_receipts"].values()),
                 *(path(p) for p in plan["bound_files"])]
    if output.exists() or any(p.is_relative_to(output) or output.is_relative_to(p)
                              for p in protected):
        raise ValueError("resource_output_exists_or_invalid")
    requests = {}
    for case in plan["cases"]:
        request = AnswerRequest.model_validate(case["payload"])
        if canonical(request.model_dump()) != canonical(case["payload"]):
            raise ValueError("resource_payload_coercion")
        counts = case["official_input_tokens"]
        if (set(counts) != {"L0", "C2"} or
                any(type(n) is not int or not 0 < n <= 5120 for n in counts.values())
                or case["id"] == "normal" and max(counts.values()) > 1024
                or case["id"] == "stress" and
                   not (min(counts.values()) > 4096 and max(counts.values()) >= 4992)):
            raise ValueError("resource_plan_token_target")
        requests[case["id"]] = request
    prepared = {"path": path(plan_path), "sha256": digest, "plan": plan,
                "output": output, "requests": requests}
    verify(prepared)
    return prepared


def verify(prepared):
    plan = prepared["plan"]
    if snapshot(prepared["path"])[1] != prepared["sha256"]:
        raise ValueError("resource_plan_changed")
    freeze = plan["source_freeze"]
    read(freeze["file"], freeze["sha256"])
    if source_bindings(freeze["file"]) != plan["bound_files"]:
        raise ValueError("resource_source_changed")
    for phase, ref in plan["survey_receipts"].items():
        if survey_reference(ref["file"], phase, freeze["file"]) != ref:
            raise ValueError("resource_survey_changed")
        if fingerprint(read(ref["file"], ref["sha256"])[0].get("tokenizer")) != fingerprint(plan["tokenizer"]):
            raise ValueError("resource_survey_tokenizer_mismatch")


def save(prepared, report):
    raw = encoded(report)
    if len(raw) > BYTE_LIMIT:
        raise ValueError("resource_snapshot_limit")
    target = prepared["output"] / "report.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(raw)
    for attempt, delay in enumerate((0.02, 0.05, 0)):
        try:
            temporary.replace(target)
            break
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(delay)


def nvidia_sample():
    binary = shutil.which("nvidia-smi")
    if binary is None:
        return None
    try:
        result = subprocess.run([binary, "--query-gpu=index,memory.used,memory.total",
            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True)
        return [{"index": int(i), "used_mib": int(u), "total_mib": int(t)}
                for i, u, t in (line.split(",") for line in result.stdout.splitlines())]
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


@contextmanager
def memory_samples(process, metrics):
    import psutil
    stop = threading.Event()
    samples = []

    def sample():
        while not stop.is_set():
            try:
                samples.append({"monotonic": time.monotonic(),
                    "rss_bytes": psutil.Process(process.pid).memory_info().rss,
                    "available_ram_bytes": psutil.virtual_memory().available})
            except psutil.Error:
                break
            stop.wait(0.25)
    worker = threading.Thread(target=sample, daemon=True)
    gpu_before = nvidia_sample()
    try:
        worker.start()
        yield
    finally:
        stop.set()
        worker.join(timeout=2)
        metrics["memory"] = {"interval_seconds": .25, "sample_count": len(samples),
            "native_rss_max_sample_bytes": max((s["rss_bytes"] for s in samples), default=None),
            "system_available_ram_min_sample_bytes": min(
                (s["available_ram_bytes"] for s in samples), default=None),
            "sampler_joined": not worker.is_alive(), "gpu_before": gpu_before,
            "gpu_after": nvidia_sample(), "gpu_sampling": "before_after_not_peak",
            "gpu_process_measurement": None, "scope": "sampled_not_peak_no_headroom_claim"}


class ObservedResourceGenerator(BudgetGGUFGenerator):
    """Per-instance observer; no frozen modules/classes are patched."""
    def __init__(self, *args, observer, **kwargs):
        self.observer = observer
        super().__init__(*args, **kwargs)

    def _request(self, method, route, payload=None, deadline=None):
        if route != "/completion":
            if (method, route) not in {("GET", "/props"), ("POST", "/apply-template"),
                                       ("POST", "/tokenize")}:
                raise ValueError("resource_unregistered_route")
            return super()._request(method, route, payload, deadline)
        dispatch = super()._request
        return self.observer(method, route, payload, deadline,
            lambda: dispatch(method, route, payload, deadline))


def stop_owned(process, report):
    started = time.monotonic()
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)
    report["owned_cleanup_ms"] = (time.monotonic() - started) * 1000
    if process.poll() is None or report["owned_cleanup_ms"] > 5000:
        raise ValueError("resource_cleanup_failed")


def run(prepared, factory=native_service, base_factory=None):
    from doctrail.meeting_answer_spans import span_answer_grammar
    from scripts.probe_meeting_budget_comparison import validate_resource_evidence
    verify(prepared)
    prepared["output"].mkdir(parents=True, exist_ok=False)
    plan = prepared["plan"]
    started = time.monotonic()
    report = {"schema_version": 1, "candidate": CANDIDATE, "plan_sha256": prepared["sha256"],
        "protocol_sha256": PROTOCOL_SHA256, "fixture_sha256": plan["fixture_sha256"],
        "limits": LIMITS, "bound_files": plan["bound_files"], "status": "running",
        "started_at": datetime.now(UTC).isoformat(), "calls": [], "results": [],
        "sources_unchanged": False, "processes_stopped": False, "metadata_recovery": False,
        "cleanup_within_service_budget": False, "readiness_passed": False,
        "model_quality_evaluated": False, "human_review_count": 0, "paid_calls": 0,
        "warmup_calls": 0, "retries": 0, "recovery_generation_calls": 0}
    save(prepared, report)
    processes, active, last_started = [], None, None

    def observer(method, route, payload, deadline, dispatch):
        verify(prepared)
        if (active is None or len(report["calls"]) >= 4 or
                any(c["id"] == active["id"] for c in report["calls"])):
            raise ValueError("resource_native_budget")
        if time.monotonic() - started >= 2400:
            raise ValueError("resource_overall_deadline")
        if hashlib.sha256(payload["grammar"].encode()).hexdigest() != active["grammar_sha256"]:
            raise ValueError("resource_dispatch_grammar")
        if len(payload["prompt"]) != active["official_input_tokens"]:
            raise ValueError("resource_native_official_count_mismatch")
        call = {"sequence": len(report["calls"]), "id": active["id"],
            "case_id": active["case_id"], "arm": active["arm"],
            "dispatch_attempted": True, "payload": copy.deepcopy(payload)}
        report["calls"].append(call)
        save(prepared, report)
        try:
            response = dispatch()
            call["raw_response"] = copy.deepcopy(response)
            return response
        except Exception as error:
            call["error"] = safe_error(error)
            raise
        finally:
            save(prepared, report)

    def make(service):
        if fingerprint(service.receipt) != plan["runtime_receipt_sha256"]:
            raise ValueError("resource_runtime_receipt_changed")
        return (base_factory(service, observer) if base_factory else ObservedResourceGenerator(
            service.url, service.token, service.manifest, observer=observer).load())

    try:
        with factory(prepared["output"] / "native-logs", 2100) as service:
            processes.append(service.process)
            base = None
            try:
                base = make(service)
                report["model_runtime"] = base.public_metadata()
                for case_id, arm in ORDER:
                    verify(prepared)
                    case = next(c for c in plan["cases"] if c["id"] == case_id)
                    request = prepared["requests"][case_id]
                    catalog_fn, prompt_fn = ARMS[arm]
                    catalog = catalog_fn(request.contexts)
                    prompt = prompt_fn(request.query, catalog)
                    grammar = STRESS_GRAMMAR if case_id == "stress" else span_answer_grammar(catalog)
                    active = {"id": f"{case_id}-{arm}", "case_id": case_id, "arm": arm,
                        "official_input_tokens": case["official_input_tokens"][arm],
                        "prompt_sha256": fingerprint(prompt),
                        "grammar_sha256": hashlib.sha256(grammar.encode()).hexdigest(), "passed": False}
                    report["results"].append(active)
                    if (active["prompt_sha256"] != case["prompt_sha256"][arm]
                            or case_id == "normal" and
                            active["grammar_sha256"] != case["grammar_sha256"][arm]):
                        raise ValueError("resource_fixture_changed")
                    last_started = time.monotonic()
                    try:
                        with memory_samples(service.process, active), owned_watchdog(
                                service.process, active, 90 - (time.monotonic() - last_started)):
                            if case_id == "normal":
                                runtime = (BudgetLineRuntime(BudgetLineGenerator(base)) if arm == "L0"
                                           else BudgetBlockRuntime(BudgetBlockGenerator(base)))
                                active["response"] = runtime.answer(request)
                                active["worker_telemetry"] = copy.deepcopy(runtime.last_telemetry)
                                metrics = runtime.last_telemetry["calls"][0]
                                active.update({k: metrics[k] for k in
                                    ("input_tokens", "output_tokens", "finish_reason")})
                                claims = " ".join(c["text"] for c in active["response"]["claims"])
                                if (active["response"]["status"] != "answered" or
                                        any(t not in claims for t in plan["normal_expected_terms"])):
                                    raise ValueError("resource_normal_toy_fact_failed")
                            else:
                                deadline = last_started + 90
                                base.begin_request(deadline)
                                try:
                                    n = base.count_tokens(prompt)
                                    if n != active["official_input_tokens"] or not 4096 < n <= 5120:
                                        raise ValueError("resource_native_official_count_mismatch")
                                    result = base._complete(prompt, deadline, 384, STRESS_GRAMMAR)
                                    active["output"] = dataclasses.asdict(result)
                                    active.update({k: getattr(result, k) for k in
                                        ("input_tokens", "output_tokens", "finish_reason")})
                                    if result.output_tokens != 384 or result.finish_reason != "length":
                                        raise ValueError("resource_stress_output_target")
                                finally:
                                    base.end_request()
                            active["effective_config"] = copy.deepcopy(base.last_effective_config)
                            if time.monotonic() - last_started >= 90:
                                raise ValueError("resource_request_deadline")
                        if (active["watchdog_fired"] or not active["watchdog_joined"]
                                or active.get("watchdog_kill_failed")):
                            raise ValueError("resource_watchdog_failed")
                        if (active["memory"]["sample_count"] < 1 or
                                active["memory"]["sampler_joined"] is not True):
                            raise ValueError("resource_memory_sampling_failed")
                        active["passed"] = True
                    except Exception as error:
                        active["error"] = safe_error(error)
                        raise
                    finally:
                        active["elapsed_seconds"] = time.monotonic() - last_started
                        save(prepared, report)
            finally:
                try:
                    if base is not None:
                        base.close()
                finally:
                    stop_owned(service.process, report)
    except Exception as error:  # noqa: BLE001 - preserve failure and never resume its remaining calls
        report["failure"] = safe_error(error)
    finally:
        report["last_request_through_cleanup_ms"] = (
            (time.monotonic() - last_started) * 1000 if last_started is not None else None)
        report["cleanup_within_service_budget"] = (last_started is not None and
            report["last_request_through_cleanup_ms"] <= 120000 and
            report.get("owned_cleanup_ms", 5001) <= 5000 and
            bool(processes) and all(p.poll() is not None for p in processes))
        active = None  # any unexpected generation during metadata restart is rejected
        if "failure" not in report:
            try:
                verify(prepared)
                if not report["cleanup_within_service_budget"]:
                    raise ValueError("resource_cleanup_failed")
                remaining = 2400 - (time.monotonic() - started)
                with factory(prepared["output"] / "recovery-logs", min(300, remaining)) as service:
                    processes.append(service.process)
                    base = None
                    try:
                        base = make(service)
                        report["recovered_identity"] = base.public_metadata()
                        report["metadata_recovery"] = (report["recovered_identity"] == report["model_runtime"])
                    finally:
                        try:
                            if base is not None:
                                base.close()
                        finally:
                            recovery = {}
                            stop_owned(service.process, recovery)
                            report["recovery_cleanup_ms"] = recovery["owned_cleanup_ms"]
            except Exception as error:  # noqa: BLE001
                report["recovery_error"] = safe_error(error)
        report["processes_stopped"] = bool(processes) and all(p.poll() is not None for p in processes)
        try:
            verify(prepared)
            report["sources_unchanged"] = True
        except Exception as error:  # noqa: BLE001
            report["source_error"] = safe_error(error)
        report["native_log_bytes"] = sum(p.stat().st_size for p in prepared["output"].rglob("*.log"))
        report["elapsed_seconds"] = time.monotonic() - started
        report["completed_at"] = datetime.now(UTC).isoformat()
        report["unexecuted"] = [f"{c}-{a}" for c, a in ORDER
                                if not any(x["id"] == f"{c}-{a}" for x in report["calls"])]
        report["readiness_passed"] = True
        report["status"] = "completed_resource_only"
        try:
            validate_resource_evidence(report, plan, expected_bound_files=plan["bound_files"],
                                       expected_protocol_sha256=PROTOCOL_SHA256)
        except Exception as error:  # noqa: BLE001 - no quality inference from partial resource success
            report.update(readiness_passed=False, status="failed", readiness_error=safe_error(error))
        save(prepared, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    prep = sub.add_parser("prepare")
    for flag in ("plan", "output", "source-freeze", "calibration-receipt", "validation-receipt",
                 "runtime-receipt"):
        prep.add_argument("--" + flag, required=True, type=Path)
    execute = sub.add_parser("run")
    execute.add_argument("--plan", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.operation == "prepare":
            result = register(args.plan, args.output, source_freeze=args.source_freeze,
                calibration_receipt=args.calibration_receipt, validation_receipt=args.validation_receipt,
                runtime_receipt=args.runtime_receipt)
            print(json.dumps({"prepared": True, "model_calls": 0,
                              "counts": [c["official_input_tokens"] for c in result["cases"]]}))
        else:
            result = run(prepare(args.plan))
            print(json.dumps({"status": result["status"], "native_calls": len(result["calls"])}))
            raise SystemExit(0 if result["readiness_passed"] else 1)
    except Exception as error:  # noqa: BLE001
        parser.exit(1, safe_error(error) + "\n")


if __name__ == "__main__":
    main()
