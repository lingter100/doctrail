"""Once-only, source-bound synthetic M5 smoke with a separate GPU worker.

Raw synthetic output is saved only in experiment artifacts. Console and journal
contain safe metadata. Structural acceptance is never semantic correctness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import re
import subprocess
import time
from contextlib import ExitStack
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from doctrail.generation_runtime import (
    GenerationError,
    LocalGenerator,
    load_generation_manifest,
    safe_path,
)
from doctrail.grounded_answer import (
    GroundedAnswerError,
    build_messages,
    pre_generation_guard,
    validate_input,
    validate_output,
)
from scripts.verify_terminal_service import exclusive_model_check

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SOURCES = {
    "scripts/evaluate_generation_smoke.py", "src/doctrail/generation_runtime.py",
    "src/doctrail/grounded_answer.py", "data/prompts/m5-grounded-answer-v1.txt",
    "scripts/verify_terminal_service.py", "pyproject.toml", "uv.lock",
    "scripts/prepare_generation_model.py",
}


class SmokeError(RuntimeError):
    def __init__(self, code, telemetry=None):
        self.code = code
        self.telemetry = telemetry or {}
        super().__init__(code)


def sha256(path, *, normalized=False):
    value = safe_path(path).read_bytes()
    if normalized:
        value = value.replace(b"\r\n", b"\n")
    return hashlib.sha256(value).hexdigest()


def _bound_path(root, relative):
    if not isinstance(relative, str) or "\\" in relative:
        raise SmokeError("unsafe_plan_path")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise SmokeError("unsafe_plan_path")
    target = safe_path(root / path)
    if not target.is_relative_to(root.absolute()):
        raise SmokeError("unsafe_plan_path")
    return target


def _json(path):
    return json.loads(safe_path(path).read_text(encoding="utf-8"))


def validate_fixture(dataset):
    if (dataset.get("schema_version") != 1 or dataset.get("split") != "synthetic_smoke"
            or dataset.get("synthetic") is not True or dataset.get("human_review_count") != 0
            or not isinstance(dataset.get("cases"), list) or len(dataset["cases"]) != 12):
        raise SmokeError("invalid_synthetic_fixture")
    ids = set()
    model_count = 0
    for case in dataset["cases"]:
        case_id = case["id"]
        if (not isinstance(case_id, str) or not re.fullmatch(r"[a-z0-9-]{1,64}", case_id)
                or case_id in ids or case["provenance"]["synthetic"] is not True
                or case["provenance"]["question_author"] != "AI"):
            raise SmokeError("invalid_synthetic_case")
        ids.add(case_id)
        validate_input(case["question"], case["evidence"])
        documents = {}
        for document in case["source_documents"]:
            key = (document["document_id"], document["revision"])
            digest = hashlib.sha256(document["text"].encode("utf-8")).hexdigest()
            if key in documents or document["sha256"] != digest:
                raise SmokeError("fixture_source_hash_mismatch")
            documents[key] = document
        used = set()
        for evidence in case["evidence"]:
            key = (evidence["document_id"], evidence["revision"])
            document = documents.get(key)
            if (document is None or evidence["source_sha256"] != document["sha256"]
                    or evidence["end_cp"] > len(document["text"])
                    or document["text"][evidence["start_cp"]:evidence["end_cp"]]
                    != evidence["text"]):
                raise SmokeError("fixture_source_span_mismatch")
            used.add(key)
        if used != set(documents):
            raise SmokeError("fixture_unused_source")
        expected = bool(case["evidence"])
        if case["oracle"]["model_expected"] is not expected:
            raise SmokeError("fixture_model_denominator_mismatch")
        model_count += expected
    if model_count != 11:
        raise SmokeError("fixture_model_denominator_mismatch")
    return dataset


def verify_plan(plan_path, root=ROOT):
    root = safe_path(root)
    plan = _json(plan_path)
    if (plan.get("schema_version") != 1 or plan.get("fixed_no_retry") is not True
            or plan.get("test_locked") is not True or plan.get("human_review_count") != 0
            or not re.fullmatch(r"[a-z0-9-]{1,80}", plan.get("run_id", ""))
            or plan.get("watchdog") != {"load_seconds": 300, "generation_seconds": 195}
            or not REQUIRED_SOURCES.issubset(plan.get("source_sha256", {}))):
        raise SmokeError("invalid_generation_plan")
    sources = {}
    for relative, expected in plan["source_sha256"].items():
        if not (relative.startswith(("scripts/", "src/doctrail/", "data/prompts/"))
                or relative in {"pyproject.toml", "uv.lock", "docs/M5-DESIGN.md",
                                "data/evaluation/reviews/m5-smoke-review-v1.json"}):
            raise SmokeError("unsupported_source_binding")
        actual = sha256(_bound_path(root, relative), normalized=True)
        if actual != expected:
            raise SmokeError("source_binding_mismatch")
        sources[relative] = actual
    for field in ("dataset", "model_manifest"):
        binding = plan[field]
        approved = {"dataset": "data/evaluation/m5-synthetic-smoke-v1.json",
                    "model_manifest": "data/models/m5-generation-v1.json"}
        if binding["path"] != approved[field]:
            raise SmokeError("unsupported_evaluation_binding")
        if sha256(_bound_path(root, binding["path"])) != binding["sha256"]:
            raise SmokeError(f"{field}_binding_mismatch")
    manifest_path = _bound_path(root, plan["model_manifest"]["path"])
    load_generation_manifest(manifest_path)
    dataset = validate_fixture(_json(_bound_path(root, plan["dataset"]["path"])))
    return plan, dataset, manifest_path, sources


def git_identity(root):
    options = {"cwd": root, "capture_output": True, "text": True}
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"],
                            check=True, **options).stdout
    if status.strip():
        raise SmokeError("clean_git_required")
    head = subprocess.run(["git", "rev-parse", "HEAD"], check=True, **options).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise SmokeError("invalid_git_head")
    return {"head": head, "clean": True}


def _write_json(path, payload):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _journal(output, event, **metadata):
    with (output / "journal.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps({"at": datetime.now(UTC).isoformat(), "event": event,
                                 **metadata}, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _worker(connection, snapshot, manifest_path):
    generator = None
    try:
        generator = LocalGenerator(snapshot, manifest_path)
        generator.load()
        connection.send({"event": "loaded", "metadata": generator.public_metadata(),
                         "load_metrics": generator.load_metrics,
                         "verified_files": generator.verified_files})
        while True:
            command = connection.recv()
            if command["event"] == "close":
                break
            result = generator.generate(command["messages"])
            connection.send({"event": "generated", "case_id": command["case_id"],
                             "result": asdict(result)})
    except GenerationError as error:
        connection.send({"event": "failed", "error_code": error.code,
                         "telemetry": error.telemetry})
    except Exception:  # noqa: BLE001 - never send third-party error text across privacy boundary
        connection.send({"event": "failed", "error_code": "generation_worker_failed"})
    finally:
        if generator is not None:
            generator.close()
        connection.close()


def await_event(connection, process, seconds, expected_event):
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SmokeError(f"watchdog_{expected_event}_timeout")
        if connection.poll(min(0.1, remaining)):
            try:
                event = connection.recv()
            except EOFError:
                raise SmokeError("generation_worker_exited") from None
            if event.get("event") == "failed":
                raise SmokeError(event["error_code"], event.get("telemetry"))
            if event.get("event") != expected_event:
                raise SmokeError("generation_worker_protocol")
            return event
        if not process.is_alive():
            raise SmokeError("generation_worker_exited")


def stop_owned_worker(process, connection):
    if process is None:
        return
    if process.pid is None:
        process.close()
        return
    if process.is_alive():
        try:
            connection.send({"event": "close"})
        except (BrokenPipeError, EOFError, OSError):
            pass
        process.join(timeout=5)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)
    if process.is_alive():
        raise SmokeError("owned_worker_cleanup_failed")
    process.close()


def preserve_failed_cleanup_lock(root, witness):
    """Change only our lock payload so the frozen helper leaves a recovery block.

The helper checks both identity and exact payload before unlinking. A replacement
lock owned by another process is never written. Manual inspection is required.
"""
    path = safe_path(root / ".local/m4-execution/active.lock")
    identity, payload = witness
    with path.open("r+b") as stream:
        info = os.fstat(stream.fileno())
        if (info.st_dev, info.st_ino) != identity or stream.read() != payload:
            return
        replacement = json.loads(payload)
        replacement["recovery_required"] = "generation_worker_cleanup_unconfirmed"
        stream.seek(0)
        stream.write(json.dumps(replacement, sort_keys=True).encode("utf-8"))
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())


def validate_case(case, result):
    row = {"case_id": case["id"], "category": case["category"], "model_called": True,
           "semantic_support": "not_verified", "generation": result}
    try:
        row["validated"] = validate_output(result["text"], case["evidence"],
                                           finish_reason=result["finish_reason"])
        row["validation_status"] = "accepted"
        row["expected_status_match"] = row["validated"]["status"] == case["oracle"][
            "expected_status"
        ]
        row["expected_reason_match"] = row["validated"]["reason"] == case["oracle"][
            "expected_reason"
        ]
    except GroundedAnswerError as error:
        row.update(validation_status="rejected", error_code=error.code,
                   expected_status_match=False, expected_reason_match=False)
    return row


def summarize(cases):
    generated = [row for row in cases if row["model_called"]]
    accepted = [row for row in generated if row["validation_status"] == "accepted"]
    return {
        "planned_cases": 12, "planned_model_cases": 11, "planned_guard_cases": 1,
        "completed_cases": len(cases), "completed_model_cases": len(generated),
        "completed_guard_cases": len(cases) - len(generated),
        "unfinished_cases": 12 - len(cases), "unfinished_model_cases": 11 - len(generated),
        "unfinished_guard_cases": 1 - (len(cases) - len(generated)),
        "structurally_accepted_model_cases": len(accepted),
        "rejected_model_cases": len(generated) - len(accepted),
        "accepted_model_abstentions": sum(row["validated"]["status"] == "abstained"
                                         for row in accepted),
        "expected_status_matches": sum(row["expected_status_match"] for row in accepted),
        "semantic_correctness": "not_verified", "human_review_count": 0,
    }


def run(plan_path, snapshot, output, root=ROOT):
    output = safe_path(output)
    output.mkdir(parents=True, exist_ok=False)
    plan_path = safe_path(plan_path)
    report = {"schema_version": 1, "status": "running", "cases": [],
              "attempted_model_cases": 0,
              "measurement_scope": "python_local_generation_synthetic_smoke",
              "test_locked": True, "human_review_count": 0, "fixed_no_retry": True,
              "semantic_correctness": "not_verified"}
    process = connection = None
    lock_witness = None

    def cleanup_worker():
        nonlocal process
        try:
            stop_owned_worker(process, connection)
        except (SmokeError, OSError, ValueError):
            if lock_witness is not None:
                preserve_failed_cleanup_lock(root, lock_witness)
            raise SmokeError("owned_worker_cleanup_failed") from None
        else:
            process = None

    _journal(output, "preflight_start")
    try:
        report["git"] = git_identity(root)
        plan, dataset, manifest_path, sources = verify_plan(plan_path, root)
        report.update(run_id=plan["run_id"], plan_path=plan_path.relative_to(root).as_posix(),
                      plan_sha256=sha256(plan_path), source_sha256=sources,
                      dataset=plan["dataset"], model_manifest=plan["model_manifest"])
        _write_json(output / "report-0000.json", report)
        with exclusive_model_check(root), ExitStack() as cleanup:
            lock_path = safe_path(root / ".local/m4-execution/active.lock")
            info = lock_path.stat()
            lock_witness = ((info.st_dev, info.st_ino), lock_path.read_bytes())
            cleanup.callback(cleanup_worker)
            # Verify bindings again after acquiring the shared lock, before worker creation.
            verify_plan(plan_path, root)
            reservation = safe_path(root / ".local/m5-execution" / f"{plan['run_id']}.json")
            reservation.parent.mkdir(parents=True, exist_ok=True)
            try:
                _write_json(reservation, {"run_id": plan["run_id"],
                                          "plan_sha256": report["plan_sha256"],
                                          "git_head": report["git"]["head"],
                                          "fixed_no_retry": True})
            except FileExistsError:
                raise SmokeError("generation_run_already_reserved") from None
            context = multiprocessing.get_context("spawn")
            connection, worker_connection = context.Pipe()
            process = context.Process(target=_worker, args=(worker_connection, safe_path(snapshot),
                                                            manifest_path), daemon=True)
            _journal(output, "load_start")
            process.start()
            worker_connection.close()
            loaded = await_event(connection, process, plan["watchdog"]["load_seconds"], "loaded")
            report["model_runtime"] = {key: value for key, value in loaded.items() if key != "event"}
            _journal(output, "load_complete", **loaded["load_metrics"])
            for index, case in enumerate(dataset["cases"], 1):
                report["active_case_id"] = case["id"]
                guard = pre_generation_guard(case["question"], case["evidence"])
                _journal(output, "case_start", case_id=case["id"], model_called=guard is None)
                if guard is not None:
                    row = {"case_id": case["id"], "category": case["category"],
                           "model_called": False, "validation_status": "guard",
                           "validated": guard, "semantic_support": "not_verified"}
                else:
                    report["attempted_model_cases"] += 1
                    connection.send({"event": "generate", "case_id": case["id"],
                                     "messages": build_messages(case["question"], case["evidence"])})
                    event = await_event(connection, process,
                                        plan["watchdog"]["generation_seconds"], "generated")
                    if event["case_id"] != case["id"]:
                        raise SmokeError("generation_worker_case_mismatch")
                    row = validate_case(case, event["result"])
                _write_json(output / f"{case['id']}.json", row)
                report["cases"].append(row)
                report["summary"] = summarize(report["cases"])
                _write_json(output / f"report-{index:04d}.json", report)
                _journal(output, "case_complete", case_id=case["id"],
                         model_called=row["model_called"], validation_status=row["validation_status"])
                report["active_case_id"] = None
            verify_plan(plan_path, root)
            if git_identity(root) != report["git"]:
                raise SmokeError("git_changed_during_run")
            report["status"] = "completed"
    except (SmokeError, GenerationError, GroundedAnswerError) as error:
        report.update(status="failed", error_code=error.code,
                      failure_telemetry=getattr(error, "telemetry", {}))
    except Exception:  # noqa: BLE001 - durable failure receipt contains no private exception text
        report.update(status="failed", error_code="smoke_execution_failed")
    finally:
        try:
            cleanup_worker()
        except (SmokeError, OSError, ValueError):
            report.update(status="failed", error_code="owned_worker_cleanup_failed")
        if connection is not None:
            connection.close()
        report["summary"] = summarize(report["cases"])
        _journal(output, "run_complete", status=report["status"],
                 error_code=report.get("error_code"))
        _write_json(output / "report.json", report)
    return report


def replay(report_path, root=ROOT):
    report = _json(report_path)
    plan_path = _bound_path(root, report["plan_path"])
    plan, dataset, _, sources = verify_plan(plan_path, root)
    if (sha256(plan_path) != report["plan_sha256"] or sources != report["source_sha256"]
            or plan["dataset"] != report["dataset"]
            or plan["model_manifest"] != report["model_manifest"]):
        raise SmokeError("replay_binding_mismatch")
    by_id = {case["id"]: case for case in dataset["cases"]}
    if (len(report["cases"]) > 12
            or report["status"] == "completed" and len(report["cases"]) != 12):
        raise SmokeError("replay_case_count_mismatch")
    checked = []
    for index, row in enumerate(report["cases"]):
        if row["case_id"] != dataset["cases"][index]["id"]:
            raise SmokeError("replay_case_order_mismatch")
        case = by_id[row["case_id"]]
        guard = pre_generation_guard(case["question"], case["evidence"])
        if guard is not None:
            expected = {"case_id": case["id"], "category": case["category"],
                        "model_called": False, "validation_status": "guard",
                        "validated": guard, "semantic_support": "not_verified"}
            if row != expected:
                raise SmokeError("replay_guard_mismatch")
            checked.append(row)
        else:
            actual = validate_case(case, row["generation"])
            if actual != row:
                raise SmokeError("replay_validation_mismatch")
            checked.append(actual)
    summary = summarize(checked)
    if summary != report["summary"]:
        raise SmokeError("replay_summary_mismatch")
    return {"replay": "passed", "run_status": report["status"], "summary": summary,
            "limitation": "Rechecks structure and exact citations, not semantic correctness."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    try:
        if args.replay:
            result = replay(args.replay)
        else:
            if not all((args.plan, args.snapshot, args.output)):
                parser.error("--plan, --snapshot and --output are required for execution")
            result = run(args.plan.absolute(), args.snapshot, args.output)
            result = {"status": result["status"], "error_code": result.get("error_code"),
                      "summary": result["summary"]}
    except (SmokeError, GenerationError, GroundedAnswerError) as error:
        result = {"status": "failed", "error_code": error.code}
    except Exception:  # noqa: BLE001 - safe console boundary
        result = {"status": "failed", "error_code": "smoke_command_failed"}
    print(json.dumps(result, sort_keys=True))
    return 1 if result.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
