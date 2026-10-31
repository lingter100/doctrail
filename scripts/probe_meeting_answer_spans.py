"""Once-only C0 phases; sealed inputs stay unopened until the known gate passes."""
from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from doctrail.meeting_contract import AnswerRequest

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = "meeting-answer-spans-c0"
COUNTS = {"neutral": 2, "known": 4, "validation": 12}
REQUIRED_FILES = {
    "scripts/probe_meeting_answer_spans.py", "src/doctrail/meeting_answer_spans.py",
    "src/doctrail/meeting_answer_v2.py", "src/doctrail/meeting_answer_grammar.py",
    "src/doctrail/meeting_qwen35.py", "src/doctrail/meeting_gguf.py",
    "src/doctrail/meeting_contract.py", "src/doctrail/meeting_worker.py",
    "src/doctrail/meeting_runtime.py", "src/doctrail/inference.py",
    "src/doctrail/generation_runtime.py", "src/doctrail/generation_runtime_v2.py",
    "scripts/serve_meeting_qwen35.py", "scripts/prepare_meeting_gguf.py",
    "scripts/serve_meetings_gguf.py", "scripts/serve_models.py",
    "data/models/meetings-generation-qwen35-v1.json",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def local_path(value):
    if not isinstance(value, str) or not value:
        raise ValueError("invalid_plan_path")
    path = Path(value)
    resolved = (ROOT / path).resolve()
    if path.is_absolute() or ".." in path.parts or not resolved.is_relative_to(ROOT.resolve()):
        raise ValueError("invalid_plan_path")
    return resolved


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
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique)


def verify_known_gate(plan, plan_sha):
    source_plan, source_sha = plan, plan_sha
    if "source_plan" in plan:
        reference = plan["source_plan"]
        source_path = local_path(reference.get("path"))
        if sha(source_path) != reference.get("sha256"):
            raise ValueError("source_plan_hash_mismatch")
        source_plan, source_sha = read_json(source_path), reference["sha256"]
        if (source_plan.get("candidate") != CANDIDATE
                or source_plan.get("bound_files") != plan["bound_files"]
                or "known" not in source_plan.get("phases", {})):
            raise ValueError("source_plan_link_mismatch")
    gate = plan.get("known_gate", {})
    report_path, review_path = local_path(gate.get("report")), local_path(gate.get("review"))
    if "known" not in source_plan["phases"]:
        raise ValueError("known_source_phase_required")
    expected_report = local_path(source_plan["phases"]["known"]["output_dir"]) / "report.json"
    if report_path != expected_report or review_path == report_path:
        raise ValueError("known_gate_path_mismatch")
    report, review = read_json(report_path), read_json(review_path)
    ids = source_plan["phases"]["known"]["case_ids"]
    if (report.get("candidate") != CANDIDATE or report.get("phase") != "known"
            or len(ids) != COUNTS["known"] or len(set(ids)) != COUNTS["known"]
            or report.get("plan_sha256") != source_sha
            or report.get("bound_files") != source_plan["bound_files"]
            or report.get("phase_inputs") != source_plan["phases"]
            or report.get("status") != "completed_not_semantically_verified"
            or report.get("sources_unchanged") is not True
            or report.get("analysis_calls") != 0
            or [x.get("id") for x in report.get("results", [])] != ids
            or any(x.get("structural_status") != "passed" for x in report["results"])
            or [x.get("case_id") for x in report.get("calls", [])] != ids
            or any("output" not in x or "error" in x for x in report["calls"])
            or review.get("gate_passed") is not True
            or review.get("report_sha256") != sha(report_path)
            or review.get("plan_sha256") != source_sha
            or review.get("independent_of_implementation") is not True):
        raise ValueError("known_gate_not_passed")
    return {"report_sha256": sha(report_path), "review_sha256": sha(review_path),
            "source_plan_sha256": source_sha}


def prepare(plan_path, phase, output):
    plan = read_json(plan_path)
    plan_sha = sha(plan_path)
    if (type(plan.get("schema_version")) is not int or plan["schema_version"] != 1
            or plan.get("candidate") != CANDIDATE
            or type(plan.get("retries")) is not int or plan["retries"] != 0
            or type(plan.get("analysis_calls")) is not int or plan["analysis_calls"] != 0
            or not plan.get("phases") or not set(plan["phases"]) <= set(COUNTS)
            or phase not in plan["phases"]
            or not REQUIRED_FILES <= set(plan.get("bound_files", {}))):
        raise ValueError("c0_plan_mismatch")
    paths = []
    for name, spec in plan["phases"].items():
        count = COUNTS[name]
        ids = spec.get("case_ids")
        if (not isinstance(ids, list) or len(ids) != count
                or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != count
                or not re.fullmatch(r"[a-f0-9]{64}", spec.get("input_sha256", ""))):
            raise ValueError("c0_phase_mismatch")
        local_path(spec.get("input_file"))  # Resolve only; never read other phase inputs.
        paths.append(local_path(spec.get("output_dir")))
    if len(set(paths)) != len(paths):
        raise ValueError("c0_output_paths_collide")
    output = Path(output).resolve()
    if output != local_path(plan["phases"][phase]["output_dir"]) or output.exists():
        raise ValueError("candidate_output_exists_or_mismatch")
    gate = verify_known_gate(plan, plan_sha) if phase == "validation" else None
    prepared = {"plan": plan, "plan_sha256": plan_sha, "phase": phase,
                "plan_path": Path(plan_path), "output": output, "known_gate": gate}
    verify_sources(prepared)
    data = read_json(local_path(plan["phases"][phase]["input_file"]))
    allowed_operations = {"answer", "analyze"} if phase == "known" else {"answer"}
    if any(x.get("operation") not in allowed_operations for x in data["cases"]):
        raise ValueError("candidate_operation_mismatch")
    cases = [x for x in data["cases"] if x.get("operation") == "answer"]
    if [x.get("id") for x in cases] != plan["phases"][phase]["case_ids"]:
        raise ValueError("candidate_case_set_mismatch")
    # Validate every request before launching a native process or making any model call.
    requests = [AnswerRequest.model_validate(x["payload"]) for x in cases]
    if any(not request.contexts for request in requests):
        raise ValueError("candidate_contexts_required")
    prepared["cases"] = list(zip(cases, requests))
    return prepared


def verify_sources(prepared):
    plan, phase = prepared["plan"], prepared["phase"]
    if sha(prepared["plan_path"]) != prepared["plan_sha256"]:
        raise ValueError("candidate_plan_changed")
    if phase == "validation" and verify_known_gate(plan, prepared["plan_sha256"]) != prepared["known_gate"]:
        raise ValueError("known_gate_changed")
    for name, expected in plan["bound_files"].items():
        # Inputs belong in phase descriptors, so sealed input cannot be opened by this loop.
        if local_path(name) in {local_path(s["input_file"]) for s in plan["phases"].values()}:
            raise ValueError("phase_input_in_shared_bindings")
        if not re.fullmatch(r"[a-f0-9]{64}", expected) or sha(local_path(name)) != expected:
            raise ValueError("candidate_source_changed")
    spec = plan["phases"][phase]
    if sha(local_path(spec["input_file"])) != spec["input_sha256"]:
        raise ValueError("candidate_input_changed")


def safe_error(error):
    code = getattr(error, "code", None)
    if code is None and type(error) is ValueError:
        code = str(error)
    return code if isinstance(code, str) and re.fullmatch(r"[a-z_]{1,100}", code) else type(error).__name__


def save(prepared, report):
    path = prepared["output"] / "report.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def claim_output(prepared):
    verify_sources(prepared)
    prepared["output"].mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "candidate": CANDIDATE, "phase": prepared["phase"],
              "started_at": datetime.now(UTC).isoformat(), "plan_sha256": prepared["plan_sha256"],
              "bound_files": prepared["plan"]["bound_files"],
              "phase_inputs": prepared["plan"]["phases"], "known_gate": prepared["known_gate"],
              "status": "starting", "sources_unchanged": False, "model_runtime": None,
              "human_review_count": 0, "paid_service_calls": 0, "analysis_calls": 0,
              "retries": 0, "semantic_review": "pending", "calls": [], "results": []}
    save(prepared, report)
    return report


def execute(generator, prepared, report, runtime_factory=None):
    if runtime_factory is None:
        from doctrail.meeting_answer_spans import SpanAnswerMeetingRuntime
        runtime_factory = SpanAnswerMeetingRuntime
    original_generate = generator.generate_bounded
    original_classify = generator.classify_bounded
    runtime = None
    active = None

    def generated(messages, deadline):
        if active is None or any(c["case_id"] == active for c in report["calls"]):
            raise ValueError("candidate_per_case_call_budget")
        if len(report["calls"]) >= COUNTS[prepared["phase"]]:
            raise ValueError("candidate_call_budget")
        verify_sources(prepared)
        call = {"case_id": active, "kind": "answer", "messages": copy.deepcopy(messages)}
        report["calls"].append(call)
        save(prepared, report)
        started = time.perf_counter()
        try:
            value = original_generate(messages, deadline)
            call["output"] = dataclasses.asdict(value)
            call["effective_config"] = copy.deepcopy(generator.last_effective_config)
            call["runtime_identity"] = generator.public_metadata()
            return value
        except Exception as error:
            call["error"] = safe_error(error)
            raise
        finally:
            call["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
            save(prepared, report)

    def forbidden(*args, **kwargs):
        raise ValueError("classification_not_in_this_plan")

    generator.generate_bounded, generator.classify_bounded = generated, forbidden
    try:
        verify_sources(prepared)
        report["model_runtime"] = generator.public_metadata()
        runtime = runtime_factory(generator)
        report["status"] = "running"
        for case, request in prepared["cases"]:
            verify_sources(prepared)
            active = case["id"]
            row = {"id": active}
            started = time.perf_counter()
            try:
                row["result"] = runtime.answer(request)
                if sum(c["case_id"] == active for c in report["calls"]) != 1:
                    raise ValueError("candidate_call_count_mismatch")
                row["structural_status"] = "passed"
            except Exception as error:  # noqa: BLE001 - preserve safe per-case failures, no retry
                row["structural_status"], row["error"] = "failed", safe_error(error)
            row["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
            report["results"].append(row)
            save(prepared, report)
            verify_sources(prepared)
        report["sources_unchanged"] = True
        report["status"] = "completed_not_semantically_verified"
    except Exception as error:  # noqa: BLE001 - partial result survives source changes
        report["status"], report["failure"] = "failed", safe_error(error)
    finally:
        generator.generate_bounded, generator.classify_bounded = original_generate, original_classify
        try:
            runtime.close() if runtime is not None else generator.close()
        finally:
            report["completed_at"] = datetime.now(UTC).isoformat()
            save(prepared, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=COUNTS, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        prepared = prepare(args.plan, args.phase, args.output)
        report = claim_output(prepared)
    except Exception as error:  # noqa: BLE001 - validation errors can contain raw input text
        parser.exit(1, safe_error(error) + "\n")
    from doctrail.meeting_answer_spans import SpanAnswerGenerator
    from doctrail.meeting_qwen35 import Qwen35Generator
    from scripts.serve_meeting_qwen35 import start_llama
    try:
        with start_llama(log_dir=prepared["output"] / "native-logs") as service:
            base = Qwen35Generator(service.url, service.token, service.manifest).load()
            execute(SpanAnswerGenerator(base), prepared, report)
    except Exception as error:  # noqa: BLE001 - no raw source/credentials in console diagnostics
        report["status"], report["failure"] = "failed", safe_error(error)
        report["completed_at"] = datetime.now(UTC).isoformat()
        save(prepared, report)
    print(json.dumps({"phase": args.phase, "status": report["status"],
                      "cases": len(report["results"]), "calls": len(report["calls"])}))
    raise SystemExit(0 if report["status"] == "completed_not_semantically_verified"
                     and all(r["structural_status"] == "passed" for r in report["results"]) else 1)


if __name__ == "__main__":
    main()
