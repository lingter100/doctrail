"""C2 neutral resource-only probe: two native dispatches, no evaluation pools."""
from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from doctrail.meeting_contract import AnswerRequest, strict_json
from scripts.probe_meeting_answer_review import (
    REQUIRED_FILES as NATIVE_FILES,
)
from scripts.probe_meeting_answer_review import native_service, safe_error

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = "meeting-answer-blocks-c2-p0"
STRESS_GRAMMAR = 'root ::= ("x "){500}\n'
LIMITS = {"input_tokens": 4096, "output_tokens": 384, "request_seconds": 90,
          "cleanup_seconds": 5, "request_and_cleanup_seconds": 120,
          "native_calls": 2, "warmup_calls": 0, "retries": 0}
FILES = NATIVE_FILES | {
    "scripts/probe_meeting_blocks_resources.py", "tests/test_meeting_blocks_resources.py",
    "scripts/check_meeting_review_token_budget.py", "src/doctrail/meeting_answer_blocks.py",
    "tests/test_meeting_answer_blocks.py", "docs/MEETINGS-C2-NEUTRAL-PLAN.md",
    "docs/MEETINGS-C1-FAILURE-FOLLOWUP.md", "pyproject.toml", "uv.lock",
}


def snapshot(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("resource_snapshot_limit")
    return raw, hashlib.sha256(raw).hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def dto(texts, query):
    return AnswerRequest(schema_version=1, query=query, contexts=[{
        "document_id": f"synthetic-resource-{i}", "revision": 1,
        "chunk_id": f"synthetic-resource-{i}-0", "title": "Synthetic resource fixture",
        "meeting_date": None, "page": None, "start_offset": 7,
        "end_offset": 7 + len(text), "text": text} for i, text in enumerate(texts)])


def synthetic_requests(tokenizer, counter):
    from doctrail.meeting_answer_blocks import answer_messages_blocks, build_block_catalog
    normal = dto(["The neutral sample has the tone label violet.\n"],
                 "What tone label does the neutral sample have?")
    normal_n = counter(tokenizer, answer_messages_blocks(normal.query,
                                                         build_block_catalog(normal.contexts)))
    for size in range(1, 71):
        paragraphs = [f"Synthetic resource paragraph {i:03d}. This neutral passage is for measuring "
            "input handling and output limits only. It contains no meeting decision, human "
            "feedback, personal record or evaluation answer. Its sample markers are cyan, "
            "magenta, amber and silver; these repeated words are mechanical padding."
            for i in range(size)]
        texts = ["\n\n".join(paragraphs[j:j + 7]) for j in range(0, size, 7)]
        request = dto(texts, "Repeat the literal marker x with spaces for this resource test.")
        count = counter(tokenizer, answer_messages_blocks(request.query,
                                                           build_block_catalog(request.contexts)))
        if 3800 <= count <= 3900:
            return [(normal, normal_n), (request, count)]
        if count > 3900:
            break
    raise ValueError("resource_token_target_unreachable")


def register(path, output, loader=None, counter=None):
    from scripts.check_meeting_review_token_budget import count_prompt, load_tokenizer
    if Path(path).exists() or Path(output).exists():
        raise ValueError("resource_output_exists")
    sources = {p: snapshot(ROOT / p)[1] for p in sorted(FILES)}
    tokenizer, metadata = (loader or load_tokenizer)(False)
    inputs = synthetic_requests(tokenizer, counter or count_prompt)
    plan = {"schema_version": 1, "candidate": CANDIDATE, "limits": LIMITS,
            "bound_files": sources, "output_dir": Path(output).resolve().relative_to(ROOT).as_posix(),
            "tokenizer": metadata, "model_calls": 0, "human_review_count": 0,
            "stress_grammar": STRESS_GRAMMAR,
            "cases": [{"id": name, "payload": item.model_dump(), "official_input_tokens": tokens}
                      for name, (item, tokens) in zip(("normal", "stress"), inputs, strict=True)]}
    if any(snapshot(ROOT / p)[1] != h for p, h in sources.items()):
        raise ValueError("resource_source_changed")
    write_new(path, plan)
    return plan


def prepare(path):
    raw, digest = snapshot(path)
    plan = strict_json(raw.decode("utf-8"))
    if (type(plan.get("schema_version")) is not int or plan["schema_version"] != 1
            or plan.get("candidate") != CANDIDATE
            or json.dumps(plan.get("limits"), sort_keys=True) != json.dumps(LIMITS, sort_keys=True)
            or plan.get("stress_grammar") != STRESS_GRAMMAR
            or set(plan.get("bound_files", {})) != FILES
            or [c.get("id") for c in plan.get("cases", [])] != ["normal", "stress"]):
        raise ValueError("resource_plan_mismatch")
    target = Path(plan["output_dir"])
    output = (ROOT / target).resolve()
    if (target.is_absolute() or ".." in target.parts or not output.is_relative_to(ROOT / ".local")
            or output.exists()):
        raise ValueError("resource_output_exists_or_invalid")
    prepared = {"plan": plan, "path": Path(path), "sha256": digest, "output": output,
                "requests": [AnswerRequest.model_validate(c["payload"]) for c in plan["cases"]]}
    verify(prepared)
    return prepared


def verify(prepared):
    if snapshot(prepared["path"])[1] != prepared["sha256"]:
        raise ValueError("resource_plan_changed")
    for name, expected in prepared["plan"]["bound_files"].items():
        if snapshot(ROOT / name)[1] != expected:
            raise ValueError("resource_source_changed")


def save(prepared, report):
    path = prepared["output"] / "report.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8")
    for attempt, delay in enumerate((0.02, 0.05, 0)):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(delay)


@contextmanager
def owned_watchdog(process, metrics, seconds=90):
    """Kill only this launcher's process. Cleanup failure never becomes readiness."""
    def kill():
        if process.poll() is None:
            metrics["watchdog_fired"] = True
            try:
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
        if metrics["watchdog_fired"]:
            process.wait(timeout=5)
        metrics["watchdog_joined"] = not timer.is_alive()


@contextmanager
def rss_samples(process, metrics):
    import psutil
    stopped = threading.Event()
    samples = []

    def sample():
        while not stopped.is_set():
            try:
                samples.append(psutil.Process(process.pid).memory_info().rss)
            except psutil.Error:
                break
            stopped.wait(0.25)
    worker = threading.Thread(target=sample, daemon=True)
    try:
        worker.start()
        yield
    finally:
        stopped.set()
        worker.join(timeout=2)
        metrics["native_rss_sample_count"] = len(samples)
        metrics["native_rss_max_sample_mib"] = max(samples) / 1048576 if samples else None
        metrics["memory_scope"] = "sampled_native_rss_not_peak_not_gpu"


def readiness(report):
    rows, calls = report["results"], report["calls"]
    return (len(rows) == 2 and len(calls) == 2 and report.get("sources_unchanged") is True
            and not {"failure", "recovery_error", "source_error"}.intersection(report)
            and report.get("processes_stopped") is True and report.get("metadata_recovery") is True
            and report.get("cleanup_within_service_budget") is True
            and all(row.get("passed") is True for row in rows)
            and [r["id"] for r in rows] == [c["id"] for c in calls] == ["normal", "stress"]
            and all("raw_response" in c and "error" not in c for c in calls))


def run(prepared, factory=native_service, base_factory=None):
    from doctrail.meeting_answer_blocks import (
        BlockAnswerGenerator,
        BlockAnswerMeetingRuntime,
        answer_messages_blocks,
        build_block_catalog,
    )
    from doctrail.meeting_qwen35 import Qwen35Generator
    base_factory = base_factory or (lambda service: Qwen35Generator(
        service.url, service.token, service.manifest).load())
    verify(prepared)
    prepared["output"].mkdir(parents=True, exist_ok=False)
    report = {"candidate": CANDIDATE, "plan_sha256": prepared["sha256"],
              "bound_files": prepared["plan"]["bound_files"], "limits": LIMITS,
              "started_at": datetime.now(UTC).isoformat(), "status": "running",
              "readiness_passed": False, "calls": [], "results": [],
              "sources_unchanged": False, "processes_stopped": False,
              "metadata_recovery": False, "model_quality_evaluated": False,
              "human_review_count": 0, "paid_calls": 0, "warmup_calls": 0, "retries": 0}
    save(prepared, report)
    processes, last_request_started = [], None
    try:
        # Same native launch for both calls; restart only after its cleanup.
        with factory(prepared["output"] / "native-logs", 600) as service:
            processes.append(service.process)
            base = base_factory(service)
            original = base._request
            active = None

            def request(method, path, payload=None, deadline=None):
                if path != "/completion":
                    return original(method, path, payload, deadline)
                verify(prepared)
                if active not in ("normal", "stress") or len(report["calls"]) >= 2 or any(
                        c["id"] == active for c in report["calls"]):
                    raise ValueError("resource_native_budget")
                call = {"id": active, "dispatch_attempted": True}
                report["calls"].append(call)
                save(prepared, report)
                try:
                    result = original(method, path, payload, deadline)
                    call["raw_response"] = copy.deepcopy(result)
                    return result
                except Exception as error:
                    call["error"] = safe_error(error)
                    raise
                finally:
                    save(prepared, report)

            base._request = request
            try:
                generator = BlockAnswerGenerator(base)
                runtime = BlockAnswerMeetingRuntime(generator)
                report["model_runtime"] = generator.public_metadata()
                for case, dto_ in zip(prepared["plan"]["cases"], prepared["requests"], strict=True):
                    verify(prepared)
                    active = case["id"]
                    row = {"id": active, "passed": False}
                    report["results"].append(row)
                    started = time.monotonic()
                    last_request_started = started
                    try:
                        with rss_samples(service.process, row), owned_watchdog(
                                service.process, row, max(0, 90 - (time.monotonic() - started))):
                            if active == "normal":
                                row["response"] = runtime.answer(dto_)
                                if row["response"]["status"] != "answered":
                                    raise ValueError("resource_normal_contract_failed")
                            else:
                                messages = answer_messages_blocks(dto_.query,
                                                                  build_block_catalog(dto_.contexts))
                                deadline = started + 90
                                base.begin_request(deadline)
                                try:
                                    n = base.count_tokens(messages)
                                    if not 3800 <= n <= 4096:
                                        raise ValueError("resource_native_input_target")
                                    result = base._complete(messages, deadline, 384, STRESS_GRAMMAR)
                                    row["output"] = dataclasses.asdict(result)
                                    if result.finish_reason != "length" or result.output_tokens != 384:
                                        raise ValueError("resource_stress_output_target")
                                finally:
                                    base.end_request()
                            row["effective_config"] = copy.deepcopy(base.last_effective_config)
                            if time.monotonic() - started >= 90 or row["watchdog_fired"]:
                                raise ValueError("resource_request_deadline")
                        if (row["watchdog_fired"] or not row["watchdog_joined"]
                                or row.get("watchdog_kill_failed")):
                            raise ValueError("resource_watchdog_failed")
                        row["passed"] = True
                        if sum(c["id"] == active for c in report["calls"]) != 1:
                            row["passed"] = False
                            raise ValueError("resource_native_call_count")
                    except Exception as error:
                        row["error"] = safe_error(error)
                        raise
                    finally:
                        if active == "normal":
                            row["worker_telemetry"] = copy.deepcopy(runtime.last_telemetry)
                        row["elapsed_with_watchdog_cleanup_ms"] = (time.monotonic() - started) * 1000
                        save(prepared, report)
            finally:
                base._request = original
                base.close()
    except Exception as error:  # noqa: BLE001 - preserve safe failure without private exception text
        report["failure"] = safe_error(error)
    finally:
        report["last_request_through_process_cleanup_ms"] = (
            (time.monotonic() - last_request_started) * 1000 if last_request_started is not None else None)
        report["cleanup_within_service_budget"] = (last_request_started is not None
            and report["last_request_through_process_cleanup_ms"] <= 120000
            and bool(processes) and all(p.poll() is not None for p in processes))
        # Metadata-only restart is not another model generation or answer recovery.
        try:
            if not processes or any(p.poll() is None for p in processes):
                raise ValueError("resource_previous_process_not_stopped")
            verify(prepared)
            with factory(prepared["output"] / "recovery-logs", 300) as service:
                processes.append(service.process)
                base = base_factory(service)
                try:
                    report["recovered_identity"] = base.public_metadata()
                    report["metadata_recovery"] = True
                finally:
                    base.close()
        except Exception as error:  # noqa: BLE001 - a failed restart cannot become readiness
            report["recovery_error"] = safe_error(error)
        report["processes_stopped"] = bool(processes) and all(p.poll() is not None for p in processes)
        try:
            verify(prepared)
            report["sources_unchanged"] = True
        except Exception as error:  # noqa: BLE001 - finalize evidence even if source verification fails
            report["source_error"] = safe_error(error)
        report["native_log_bytes"] = sum(p.stat().st_size for p in prepared["output"].rglob("*.log"))
        report["readiness_passed"] = readiness(report)
        report["status"] = "resource_ready_not_quality_verified" if report["readiness_passed"] else "failed"
        report["completed_at"] = datetime.now(UTC).isoformat()
        save(prepared, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--plan", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    execute = sub.add_parser("run")
    execute.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.operation == "prepare":
            plan = register(args.plan, args.output)
            print(json.dumps({"prepared": True, "input_tokens": [c["official_input_tokens"]
                                                               for c in plan["cases"]], "model_calls": 0}))
        else:
            report = run(prepare(args.plan))
            print(json.dumps({"status": report["status"], "native_calls": len(report["calls"])}))
            raise SystemExit(0 if report["readiness_passed"] else 1)
    except Exception as error:  # noqa: BLE001 - never print model/source exceptions
        parser.exit(1, safe_error(error) + "\n")


if __name__ == "__main__":
    main()
