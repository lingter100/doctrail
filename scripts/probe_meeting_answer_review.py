"""Once-only C1 experiment. Never opens validation before independent calibration gate."""
from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import math
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from doctrail.meeting_contract import AnswerRequest

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = "meeting-answer-review-c1"
COUNTS = {"neutral": 2, "calibration": 8, "validation": 8}
LIMITS = {"request_seconds": 120, "experiment_seconds": 2700, "input_tokens": 4096,
          "answer_tokens": 768, "review_tokens": 512, "request_output_tokens": 2560,
          "experiment_native_calls": 72}
REQUIRED_FILES = {
    "scripts/probe_meeting_answer_review.py", "src/doctrail/meeting_answer_review.py",
    "src/doctrail/meeting_answer_spans.py", "src/doctrail/meeting_answer_v2.py",
    "src/doctrail/meeting_answer_grammar.py", "src/doctrail/meeting_qwen35.py",
    "src/doctrail/meeting_gguf.py", "src/doctrail/meeting_contract.py",
    "src/doctrail/meeting_worker.py", "src/doctrail/meeting_runtime.py",
    "src/doctrail/inference.py", "src/doctrail/generation_runtime.py",
    "src/doctrail/generation_runtime_v2.py", "scripts/prepare_meeting_gguf.py",
    "scripts/serve_meetings_gguf.py", "scripts/serve_meetings.py",
    "scripts/serve_models.py", "scripts/verify_java_service.py",
    "data/models/meetings-generation-qwen35-v1.json",
}
QUALITY = ("citation_exact", "claim_support", "completeness", "language", "temporal",
           "subject", "conditions", "correct_abstention_or_answer")
STAGES = ("D0", "V0", "D1", "V1")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def local_path(value):
    if not isinstance(value, str) or not value:
        raise ValueError("invalid_plan_path")
    path = Path(value)
    result = (ROOT / path).resolve()
    if path.is_absolute() or ".." in path.parts or not result.is_relative_to(ROOT.resolve()):
        raise ValueError("invalid_plan_path")
    return result


def read_json(path):
    if Path(path).stat().st_size > 16 * 1024 * 1024:
        raise ValueError("json_file_limit")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid_json")))


def safe_error(error):
    code = getattr(error, "code", None)
    if code is None and type(error) is ValueError:
        code = str(error)
    return code if isinstance(code, str) and re.fullmatch(r"[a-z_]{1,100}", code) else type(error).__name__


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def source_plan(plan, plan_sha):
    reference = plan.get("source_plan")
    if reference is None:
        return plan, plan_sha
    path = local_path(reference.get("path"))
    if sha(path) != reference.get("sha256"):
        raise ValueError("source_plan_hash_mismatch")
    source = read_json(path)
    if (source.get("candidate") != CANDIDATE or "source_plan" in source
            or source.get("bound_files") != plan["bound_files"]
            or source.get("limits") != LIMITS
            or any(source.get("phases", {}).get(p) != plan["phases"].get(p)
                   for p in ("neutral", "calibration"))):
        raise ValueError("source_plan_link_mismatch")
    return source, reference["sha256"]


def validate_report(plan, plan_sha, phase):
    spec = plan["phases"][phase]
    path = local_path(spec["output_dir"]) / "report.json"
    report = read_json(path)
    rows = report.get("results", [])
    if (report.get("candidate") != CANDIDATE or report.get("phase") != phase
            or report.get("plan_sha256") != plan_sha
            or report.get("bound_files") != plan["bound_files"]
            or report.get("phase_inputs") != plan["phases"]
            or report.get("status") != "completed_not_semantically_verified"
            or report.get("sources_unchanged") is not True
            or report.get("resources_passed") is not True
            or report.get("security_passed") is not True
            or report.get("work_finalized") is not True
            or not number(report.get("native_work_seconds"))
            or report["native_work_seconds"] > LIMITS["experiment_seconds"]
            or [r.get("id") for r in rows] != spec["case_ids"]
            or any(r.get("structural_status") != "passed" for r in rows)
            or not resource_checks(report, spec)):
        raise ValueError("prerequisite_report_not_passed")
    return report, sha(path)


def verify_prerequisites(plan, plan_sha, phase):
    if phase == "neutral":
        return {"reports": {}, "prior_work_seconds": 0, "prior_native_calls": 0}
    source, source_sha = source_plan(plan, plan_sha)
    neutral, neutral_sha = validate_report(source, source_sha, "neutral")
    reports = {"neutral": neutral_sha}
    seconds, calls = neutral["native_work_seconds"], len(neutral["calls"])
    if phase == "validation":
        calibration, calibration_sha = validate_report(source, source_sha, "calibration")
        if calibration.get("prerequisites", {}).get("reports") != reports:
            raise ValueError("prerequisite_chain_mismatch")
        gate = plan.get("calibration_gate", {})
        report_path = local_path(source["phases"]["calibration"]["output_dir"]) / "report.json"
        if local_path(gate.get("report")) != report_path:
            raise ValueError("calibration_gate_path_mismatch")
        review_path = local_path(gate.get("review"))
        if review_path == report_path:
            raise ValueError("calibration_gate_path_mismatch")
        review = read_json(review_path)
        rows = review.get("cases", [])
        ids = source["phases"]["calibration"]["case_ids"]
        if (review.get("candidate") != CANDIDATE or review.get("phase") != "calibration"
                or review.get("report_sha256") != calibration_sha
                or review.get("plan_sha256") != source_sha
                or review.get("oracle_sha256") != source["phases"]["calibration"]["oracle_sha256"]
                or review.get("independent_of_implementation") is not True
                or review.get("judgments_locked_before_comparison") is not True
                or review.get("review_kind") != "independent_semantic_review"
                or review.get("gate_passed") is not True
                or [r.get("id") for r in rows] != ids
                or any(type(r.get("d0_correct")) is not bool or r.get("c1_correct") is not True
                       or any(r.get(k) is not True for k in QUALITY) for r in rows)
                or sum(r.get("answerable") is True for r in rows) != 6
                or sum(r.get("answerable") is False for r in rows) != 2
                or sum(not r["d0_correct"] and r["c1_correct"] for r in rows) < 1
                or any(r["d0_correct"] and not r["c1_correct"] for r in rows)):
            raise ValueError("calibration_semantic_gate_not_passed")
        reports.update(calibration=calibration_sha, semantic_review=sha(review_path))
        seconds += calibration["native_work_seconds"]
        calls += len(calibration["calls"])
    if seconds >= LIMITS["experiment_seconds"] or calls >= LIMITS["experiment_native_calls"]:
        raise ValueError("experiment_budget_exhausted")
    return {"reports": reports, "prior_work_seconds": seconds, "prior_native_calls": calls}


def prepare(plan_path, phase, output):
    plan, plan_sha = read_json(plan_path), sha(plan_path)
    if (type(plan.get("schema_version")) is not int or plan["schema_version"] != 1
            or plan.get("candidate") != CANDIDATE or plan.get("limits") != LIMITS
            or any(type(plan.get(k)) is not int or plan[k] != 0
                   for k in ("retries", "analysis_calls", "warmup_calls"))
            or not plan.get("phases") or not set(plan["phases"]) <= set(COUNTS)
            or phase not in plan["phases"]
            or not REQUIRED_FILES <= set(plan.get("bound_files", {}))):
        raise ValueError("candidate_plan_mismatch")
    paths, inputs = [], []
    for name, spec in plan["phases"].items():
        ids, count = spec.get("case_ids"), COUNTS[name]
        if (not isinstance(ids, list) or len(ids) != count
                or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != count
                or not digest(spec.get("input_sha256"))
                or type(spec.get("max_native_calls")) is not int or spec["max_native_calls"] != count * 4
                or (name != "neutral" and not digest(spec.get("oracle_sha256")))):
            raise ValueError("candidate_phase_mismatch")
        inputs.append(local_path(spec.get("input_file")))  # Paths only; never open sealed inputs.
        paths.append(local_path(spec.get("output_dir")))
    if len(set(paths)) != len(paths) or len(set(inputs)) != len(inputs) or any(
            a.is_relative_to(b) or b.is_relative_to(a) for i, a in enumerate(paths)
            for b in paths[i + 1:]) or any(i.is_relative_to(o) for i in inputs for o in paths):
        raise ValueError("candidate_paths_collide")
    output = Path(output).resolve()
    if output != local_path(plan["phases"][phase]["output_dir"]) or output.exists():
        raise ValueError("candidate_output_exists_or_mismatch")
    # Gate must precede even hashing/reading the selected validation data.
    prerequisites = verify_prerequisites(plan, plan_sha, phase)
    prepared = {"plan": plan, "plan_sha256": plan_sha, "plan_path": Path(plan_path),
                "phase": phase, "output": output, "prerequisites": prerequisites}
    verify_sources(prepared)
    data = read_json(local_path(plan["phases"][phase]["input_file"]))
    cases = data.get("cases", [])
    if ([c.get("id") for c in cases] != plan["phases"][phase]["case_ids"]
            or any(c.get("operation") != "answer" for c in cases)):
        raise ValueError("candidate_case_set_mismatch")
    if phase == "neutral" and any(c.get("expected_status") not in {"answered", "abstained"}
                                  for c in cases):
        raise ValueError("candidate_neutral_controls_required")
    requests = [AnswerRequest.model_validate(c["payload"]) for c in cases]
    if any(not request.contexts for request in requests):
        raise ValueError("candidate_contexts_required")
    prepared["cases"] = list(zip(cases, requests))
    return prepared


def verify_sources(prepared):
    plan, phase = prepared["plan"], prepared["phase"]
    if sha(prepared["plan_path"]) != prepared["plan_sha256"]:
        raise ValueError("candidate_plan_changed")
    if verify_prerequisites(plan, prepared["plan_sha256"], phase) != prepared["prerequisites"]:
        raise ValueError("candidate_prerequisites_changed")
    inputs = {local_path(s["input_file"]) for s in plan["phases"].values()}
    for name, expected in plan["bound_files"].items():
        path = local_path(name)
        if path in inputs:
            raise ValueError("phase_input_in_shared_bindings")
        if not digest(expected) or sha(path) != expected:
            raise ValueError("candidate_source_changed")
    spec = plan["phases"][phase]
    if sha(local_path(spec["input_file"])) != spec["input_sha256"]:
        raise ValueError("candidate_input_changed")


def save(prepared, report):
    path = prepared["output"] / "report.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8")
    # Windows scanners can briefly hold the destination. Retry only this unchanged
    # file replacement, never a stage, HTTP request, native generation, or case.
    for attempt, delay in enumerate((0.02, 0.05, 0)):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(delay)


def claim_output(prepared):
    verify_sources(prepared)
    prepared["output"].mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "candidate": CANDIDATE, "phase": prepared["phase"],
              "started_at": datetime.now(UTC).isoformat(), "plan_sha256": prepared["plan_sha256"],
              "bound_files": prepared["plan"]["bound_files"], "phase_inputs": prepared["plan"]["phases"],
              "prerequisites": prepared["prerequisites"], "status": "starting",
              "sources_unchanged": False, "resources_passed": False, "security_passed": False,
              "native_work_seconds": 0, "work_finalized": False, "human_review_count": 0,
              "paid_service_calls": 0, "analysis_calls": 0, "retries": 0, "warmup_calls": 0,
              "semantic_review": "pending", "calls": [], "stages": [], "results": []}
    save(prepared, report)
    return report


def resource_checks(report, spec):
    calls, rows = report.get("calls", []), report.get("results", [])
    if len(calls) > spec["max_native_calls"] or len(rows) != len(spec["case_ids"]):
        return False
    for row in rows:
        case_calls = [c for c in calls if c.get("case_id") == row["id"]]
        stages = [s for s in report.get("stages", []) if s.get("case_id") == row["id"]]
        if (len(case_calls) not in (2, 4) or len(stages) != len(case_calls)
                or [s.get("stage") for s in stages] != list(STAGES[:len(stages)])
                or not number(row.get("elapsed_ms")) or row["elapsed_ms"] > 120000
                or any("error" in s or "output" not in s for s in stages)):
            return False
        total = 0
        for stage in stages:
            result = stage["output"]
            limit = 768 if stage["stage"].startswith("D") else 512
            if (type(result.get("input_tokens")) is not int or not 1 <= result["input_tokens"] <= 4096
                    or type(result.get("output_tokens")) is not int
                    or not 1 <= result["output_tokens"] <= limit
                    or result.get("finish_reason") != "eos"):
                return False
            total += result["output_tokens"]
        if total > 2560:
            return False
    return True


def execute(generator, prepared, report, runtime_factory=None, work_started=None):
    if runtime_factory is None:
        from doctrail.meeting_answer_review import ReviewAnswerMeetingRuntime
        runtime_factory = ReviewAnswerMeetingRuntime
    base = generator.base
    complete, request_native = base._complete, base._request
    runtime, active, current_stage, case_deadline = None, None, None, None
    work_started = time.monotonic() if work_started is None else work_started
    work_deadline = work_started + 2700 - prepared["prerequisites"]["prior_work_seconds"]

    def check():
        verify_sources(prepared)
        if time.monotonic() >= work_deadline:
            raise ValueError("experiment_deadline_exceeded")

    def request(method, path, payload=None, deadline=None):
        check()
        if path != "/completion":
            report["metadata_requests"] = report.get("metadata_requests", 0) + 1
            bounds = [d for d in (deadline, work_deadline, case_deadline) if d is not None]
            return request_native(method, path, payload, min(bounds))
        calls = [c for c in report["calls"] if c["case_id"] == active]
        if active is None or current_stage is None or any(c["stage"] == current_stage for c in calls):
            raise ValueError("candidate_unregistered_native_call")
        if (len(calls) >= 4 or len(report["calls"]) >= prepared["plan"]["phases"][prepared["phase"]]["max_native_calls"]
                or len(report["calls"]) + prepared["prerequisites"]["prior_native_calls"] >= 72):
            raise ValueError("candidate_native_call_budget")
        row = {"case_id": active, "stage": current_stage, "dispatch_attempted": True}
        report["calls"].append(row)
        save(prepared, report)
        started = time.monotonic()
        try:
            result = request_native(method, path, payload, min(deadline, work_deadline, case_deadline))
            row["raw_response"] = copy.deepcopy(result)
            return result
        except Exception as error:
            row["error"] = safe_error(error)
            raise
        finally:
            row["elapsed_ms"] = (time.monotonic() - started) * 1000
            save(prepared, report)

    def generated(messages, deadline, token_limit, grammar=""):
        nonlocal current_stage
        check()
        prior = [s for s in report["stages"] if s["case_id"] == active]
        if active is None or len(prior) >= 4:
            raise ValueError("candidate_stage_budget")
        current_stage = STAGES[len(prior)]
        if getattr(generator, "current_stage", current_stage) != current_stage:
            raise ValueError("candidate_stage_order_mismatch")
        if token_limit != (768 if current_stage.startswith("D") else 512):
            raise ValueError("candidate_token_budget_mismatch")
        row = {"case_id": active, "stage": current_stage, "messages": copy.deepcopy(messages),
               "grammar_sha256": hashlib.sha256(grammar.encode()).hexdigest()}
        report["stages"].append(row)
        save(prepared, report)
        started = time.monotonic()
        try:
            result = complete(messages, min(deadline, case_deadline, work_deadline), token_limit, grammar)
            row["output"] = dataclasses.asdict(result)
            row["effective_config"] = copy.deepcopy(base.last_effective_config)
            return result
        except Exception as error:
            row["error"] = safe_error(error)
            raise
        finally:
            row["elapsed_ms"] = (time.monotonic() - started) * 1000
            current_stage = None
            save(prepared, report)

    base._complete, base._request = generated, request
    try:
        check()
        report["model_runtime"] = generator.public_metadata()
        runtime = runtime_factory(generator)
        report["status"] = "running"
        for case, dto in prepared["cases"]:
            check()
            active = case["id"]
            started = time.monotonic()
            case_deadline = min(started + 120, work_deadline)
            row = {"id": active}
            try:
                row["result"] = runtime.answer(dto)
                if prepared["phase"] == "neutral" and row["result"].get("status") != case["expected_status"]:
                    raise ValueError("candidate_neutral_control_failed")
                count = sum(c["case_id"] == active for c in report["calls"])
                if count not in (2, 4):
                    raise ValueError("candidate_call_count_mismatch")
                row["structural_status"] = "passed"
            except Exception as error:
                row["structural_status"], row["error"] = "failed", safe_error(error)
                # Semantic rejection is a scored answer failure. Operational failures abort.
                if row["error"] != "generation_semantic_rejected":
                    raise
            finally:
                row["elapsed_ms"] = (time.monotonic() - started) * 1000
                row["adapter_checks"] = copy.deepcopy(getattr(runtime, "last_telemetry", None))
                report["results"].append(row)
                save(prepared, report)
            check()
            if row["elapsed_ms"] > 120000:
                raise ValueError("candidate_request_deadline_exceeded")
        report["resources_passed"] = resource_checks(report, prepared["plan"]["phases"][prepared["phase"]])
        report["sources_unchanged"], report["security_passed"] = True, True
        report["status"] = "completed_not_semantically_verified"
    except Exception as error:  # noqa: BLE001 - preserve partial results with safe diagnostics
        report["status"], report["failure"] = "failed", safe_error(error)
    finally:
        base._complete, base._request = complete, request_native
        try:
            runtime.close() if runtime is not None else generator.close()
        finally:
            report["native_work_seconds"] = time.monotonic() - work_started
            report["completed_at"] = datetime.now(UTC).isoformat()
            save(prepared, report)
    return report


def run(prepared, service_factory=None, generator_factory=None, runtime_factory=None):
    report = claim_output(prepared)
    started = time.monotonic()
    remaining = 2700 - prepared["prerequisites"]["prior_work_seconds"]
    try:
        if service_factory is None:
            service_factory = native_service
        if generator_factory is None:
            from doctrail.meeting_answer_review import ReviewAnswerGenerator
            from doctrail.meeting_qwen35 import Qwen35Generator
            generator_factory = lambda service: ReviewAnswerGenerator(
                Qwen35Generator(service.url, service.token, service.manifest).load())
        verify_sources(prepared)
        with service_factory(prepared["output"] / "native-logs", remaining) as service:
            execute(generator_factory(service), prepared, report, runtime_factory, started)
    except Exception as error:  # noqa: BLE001 - startup/cleanup failures consume the output claim
        report["status"], report["failure"] = "failed", safe_error(error)
    finally:
        report["native_work_seconds"] = time.monotonic() - started
        report["work_finalized"] = True
        if report["native_work_seconds"] > remaining:
            report["status"], report["failure"] = "failed", "experiment_deadline_exceeded"
            report["resources_passed"] = False
        try:
            verify_sources(prepared)
        except Exception as error:  # noqa: BLE001 - final source checks fail closed
            report["status"], report["failure"] = "failed", safe_error(error)
            report["sources_unchanged"] = False
        report["completed_at"] = datetime.now(UTC).isoformat()
        save(prepared, report)
    return report


def native_service(log_dir, remaining):
    """Own one native child, explicitly disable warmup; watchdog includes startup/cleanup."""
    import os
    import secrets
    import subprocess
    import threading
    from contextlib import ExitStack, contextmanager

    from doctrail.meeting_qwen35 import GGUF_SHA256, MODEL_ID, MODEL_REVISION
    from doctrail.meeting_worker import worker_lease
    from scripts.prepare_meeting_gguf import prepare as prepare_model
    from scripts.serve_meetings_gguf import LlamaService
    from scripts.serve_models import stop_process, unused_port, wait_ready

    @contextmanager
    def launch():
        started = time.monotonic()
        model_dir = ROOT / "models/meetings-qwen35-v1"
        manifest = ROOT / "data/models/meetings-generation-qwen35-v1.json"
        token, port = secrets.token_urlsafe(48), unused_port()
        with ExitStack() as stack:
            stack.enter_context(worker_lease(ROOT / ".local/meeting-generation.gpu.lock"))
            with worker_lease(ROOT / ".local/meeting-generation.worker.lock"):
                pass
            stack.enter_context(worker_lease(ROOT / ".local/meeting-llama.lease"))
            receipt = prepare_model(manifest, model_dir, allow_download=False)
            identity = read_json(manifest)
            if (identity.get("model") != MODEL_ID or identity.get("revision") != MODEL_REVISION
                    or identity.get("gguf", {}).get("sha256") != GGUF_SHA256):
                raise ValueError("candidate_identity_mismatch")
            server = (model_dir / receipt["server_path"]).resolve()
            model = (model_dir / receipt["model"]["path"]).resolve()
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            log = stack.enter_context((Path(log_dir) / "llama-c1.log").open("ab"))
            environment = {k: v for k, v in os.environ.items() if not k.startswith("LLAMA_ARG_")}
            environment.update(LLAMA_API_KEY=token, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
            available = remaining - (time.monotonic() - started)
            if available <= 25:
                raise ValueError("experiment_budget_exhausted")
            process = subprocess.Popen([str(server), "--model", str(model), "--host", "127.0.0.1",
                "--port", str(port), "--alias", GGUF_SHA256, "--ctx-size", "6144", "--parallel", "1",
                "--n-gpu-layers", "24", "--batch-size", "512", "--ubatch-size", "128", "--fit", "off",
                "--reasoning", "off", "--no-context-shift", "--no-webui", "--log-disable", "--no-warmup"],
                cwd=server.parent, env=environment, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            # Own cleanup before any watchdog allocation/start can fail.
            stack.callback(stop_process, process)
            # Reserve the existing stop helper's maximum 25 seconds for cleanup.
            watchdog = threading.Timer(available - 25, stop_process, args=(process,))
            stack.callback(watchdog.cancel)
            watchdog.daemon = True
            watchdog.start()
            url = f"http://127.0.0.1:{port}"
            wait_ready(process, url + "/health", headers={"Authorization": "Bearer " + token},
                       timeout=min(240, available - 25))
            yield LlamaService(process, url, token, manifest, identity, receipt)
    return launch()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=COUNTS, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        prepared = prepare(args.plan, args.phase, args.output)
        report = run(prepared)
    except Exception as error:  # noqa: BLE001 - never print raw input/native exception contents
        parser.exit(1, safe_error(error) + "\n")
    print(json.dumps({"phase": args.phase, "status": report["status"],
                      "cases": len(report["results"]), "native_calls": len(report["calls"])}))
    raise SystemExit(0 if report["status"] == "completed_not_semantically_verified"
                     and report["resources_passed"]
                     and all(r["structural_status"] == "passed" for r in report["results"]) else 1)


if __name__ == "__main__":
    main()
