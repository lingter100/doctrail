"""One source-bound 12-case answer run after a positive known-case semantic gate.

Outputs retain model identity and are not blinded. Mechanical acceptance never
establishes answer quality. This runner neither analyzes meetings nor retries calls.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError

from doctrail.generation_runtime import GenerationError
from doctrail.inference import StrictModel
from doctrail.meeting_answer_grammar import GrammarAnswerGenerator
from doctrail.meeting_answer_v2 import EvidenceFirstMeetingRuntime
from doctrail.meeting_contract import AnswerRequest, strict_json
from doctrail.meeting_qwen35 import Qwen35Generator
from scripts.probe_meeting_gguf import ROOT, sha, write
from scripts.serve_meeting_qwen35 import start_llama as start_qwen35
from scripts.serve_meetings_gguf import start_llama as start_baseline

CASE_LIMIT = 12
RUNNER_PATH = "scripts/evaluate_meeting_answer_candidate.py"


class EvaluationCase(StrictModel):
    id: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")]
    operation: Literal["answer"]
    provenance: Annotated[str, Field(min_length=1)] | dict[str, Any]
    payload: AnswerRequest


def safe_error(error):
    code = getattr(error, "code", "")
    return code if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,80}", code) else type(error).__name__


def bound_path(relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise GenerationError("candidate_invalid_bound_path")
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        raise GenerationError("candidate_invalid_bound_path")
    return path


def verify_bindings(plan):
    """Verify bytes and gate before loading models; no fixed known-case assumptions."""
    try:
        bound = plan["bound_files"]
        if not isinstance(bound, dict) or RUNNER_PATH not in bound:
            raise GenerationError("candidate_source_binding_mismatch")
        actual = {}
        for relative, expected in bound.items():
            if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
                raise GenerationError("candidate_source_binding_mismatch")
            actual[relative] = sha(bound_path(relative))
            if actual[relative] != expected:
                raise GenerationError("candidate_source_binding_mismatch")
        source = plan["candidate_source_plan"]
        gate = plan["gate"]
        required = {plan["inputs"]: bound.get(plan["inputs"]), source["path"]: source["sha256"],
                    gate["report"]: gate["report_sha256"], gate["review"]: gate["review_sha256"]}
        if any(expected is None or bound.get(path) != expected for path, expected in required.items()):
            raise GenerationError("candidate_source_binding_mismatch")
        source_plan = strict_json(bound_path(source["path"]).read_text(encoding="utf-8"))
        if (not isinstance(source_plan, dict) or not isinstance(source_plan.get("bound_files"), dict)
                or not source_plan["bound_files"]):
            raise GenerationError("candidate_source_plan_invalid")
        if any(bound.get(path) != digest for path, digest in source_plan["bound_files"].items()):
            raise GenerationError("candidate_source_plan_mismatch")
        review = strict_json(bound_path(gate["review"]).read_text(encoding="utf-8"))
        if (not isinstance(review, dict) or review.get("gate_passed") is not True
                or review.get("report_sha256") != gate["report_sha256"]):
            raise GenerationError("candidate_semantic_gate_not_passed")
        return actual
    except (KeyError, TypeError, OSError, ValueError):
        raise GenerationError("candidate_plan_invalid") from None


def read_cases(plan):
    """Validate every case before launching; caller never substitutes known questions."""
    try:
        data = strict_json(bound_path(plan["inputs"]).read_text(encoding="utf-8"))
        raw_cases = data["cases"]
        if not isinstance(raw_cases, list) or len(raw_cases) != CASE_LIMIT:
            raise GenerationError("candidate_case_set_mismatch")
        cases = [EvaluationCase.model_validate(value) for value in raw_cases]
        if len({case.id for case in cases}) != CASE_LIMIT or any(not case.payload.contexts for case in cases):
            raise GenerationError("candidate_case_set_mismatch")
        return cases
    except (KeyError, TypeError, OSError, ValidationError):
        raise GenerationError("candidate_case_schema_invalid") from None


def run(candidate, plan_path, output):
    if candidate not in {"baseline", "qwen35"}:
        raise GenerationError("candidate_unknown_model")
    output, plan_path = Path(output), Path(plan_path)
    if output.exists():
        raise GenerationError("candidate_output_exists")
    plan_bytes = plan_path.read_bytes()
    plan, plan_hash = strict_json(plan_bytes), hashlib.sha256(plan_bytes).hexdigest()
    before = verify_bindings(plan)
    cases = read_cases(plan)
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "kind": "meeting_answer_candidate_evaluation",
        "candidate": candidate, "started_at": datetime.now(UTC).isoformat(), "plan_sha256": plan_hash,
        "bound_files": plan["bound_files"], "bound_files_before": before,
        "candidate_source_plan": plan["candidate_source_plan"], "gate": plan["gate"],
        "model_runtime": None, "human_review_count": 0, "semantic_review": "pending",
        "quality_verified": False, "blinded": False, "paid_service_calls": 0,
        "analysis_calls": 0, "call_limit": CASE_LIMIT, "results": [], "calls": [], "status": "running",
        "measurement_scope": "Python adapter/native inference; not Java or worker HTTP"}

    def save():
        write(output / "report.json", report)

    save()
    launch, generator_type = ((start_baseline, GrammarAnswerGenerator) if candidate == "baseline"
                               else (start_qwen35, Qwen35Generator))
    try:
        with launch(log_dir=output / "native") as service:
            generator = generator_type(service.url, service.token, service.manifest)
            try:
                generator.load()
                report["model_runtime"] = generator.public_metadata()
                runtime = EvidenceFirstMeetingRuntime(generator)
                original_generate, original_classify = generator.generate_bounded, generator.classify_bounded
                active_case = None

                def generated(messages, deadline):
                    if len(report["calls"]) >= CASE_LIMIT:
                        raise GenerationError("candidate_call_budget")
                    if any(call["case_id"] == active_case for call in report["calls"]):
                        raise GenerationError("candidate_duplicate_call")
                    call = {"case_id": active_case, "messages": messages, "status": "running"}
                    report["calls"].append(call)
                    save()
                    started = time.monotonic()
                    try:
                        result = original_generate(messages, deadline)
                        call["output"] = (dataclasses.asdict(result) if dataclasses.is_dataclass(result)
                                          else vars(result))
                        call["status"] = "generated_not_semantically_verified"
                        return result
                    except Exception as error:
                        call["status"], call["error"] = "failed", safe_error(error)
                        raise
                    finally:
                        call["effective_config"] = getattr(generator, "last_effective_config", None)
                        call["model_runtime_after_call"] = generator.public_metadata()
                        call["elapsed_python_seconds"] = round(time.monotonic() - started, 3)
                        save()

                def forbidden_classification(*args, **kwargs):
                    raise GenerationError("classification_not_in_this_plan")

                generator.generate_bounded, generator.classify_bounded = generated, forbidden_classification
                try:
                    for case in cases:
                        active_case = case.id
                        row = {"id": case.id, "operation": "answer", "provenance": case.provenance}
                        started = time.monotonic()
                        try:
                            row["result"] = runtime.answer(case.payload)
                            row["structural_status"] = "passed"
                        except Exception as error:  # noqa: BLE001 - preserve failures, never retry
                            row["structural_status"], row["error"] = "failed", safe_error(error)
                        row["elapsed_python_seconds"] = round(time.monotonic() - started, 3)
                        report["results"].append(row)
                        save()
                        print(case.id, row["structural_status"], flush=True)
                finally:
                    generator.generate_bounded, generator.classify_bounded = original_generate, original_classify
                report["status"] = "completed_not_semantically_verified"
            finally:
                generator.close()
    except Exception as error:  # noqa: BLE001 - no raw native errors/credentials in failure fields
        report["status"], report["error"] = "failed", safe_error(error)
    except KeyboardInterrupt:
        report["status"], report["error"] = "interrupted", "KeyboardInterrupt"
    finally:
        try:
            report["plan_sha256_after"] = sha(plan_path)
            report["bound_files_after"] = {path: sha(bound_path(path)) for path in plan["bound_files"]}
            verify_bindings(plan)
            if report["plan_sha256_after"] != plan_hash:
                raise GenerationError("candidate_plan_changed")
            report["sources_unchanged"] = True
        except Exception as error:  # noqa: BLE001 - preserve safe post-run source-check failures
            report["status"], report["source_check_error"] = "failed", safe_error(error)
            report["sources_unchanged"] = False
        report["call_count"] = len(report["calls"])
        report["structural_failures"] = sum(row["structural_status"] != "passed" for row in report["results"])
        report["completed_at"] = datetime.now(UTC).isoformat()
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", choices=["baseline", "qwen35"], required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.candidate, args.plan, args.output)
        if result["status"] != "completed_not_semantically_verified":
            parser.exit(1, "meeting_candidate_evaluation_failed\n")
    except Exception:  # noqa: BLE001 - no paths, prompts or credentials on the console
        parser.exit(1, "meeting_candidate_evaluation_failed\n")


if __name__ == "__main__":
    main()
