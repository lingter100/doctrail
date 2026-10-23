"""One evidence-first answer comparison; preserve passing v1 analysis without rerunning."""
from __future__ import annotations

import argparse
import dataclasses
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from doctrail.meeting_contract import AnswerRequest
from scripts.probe_meeting_gguf import sha, verify_plan, write


def run(generator, plan_path, output):
    from doctrail.meeting_answer_v2 import EvidenceFirstMeetingRuntime

    output = Path(output)
    if output.exists():
        raise ValueError("candidate_output_exists")
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    data = verify_plan(plan)
    cases = [case for case in data["cases"] if case["operation"] == "answer"]
    if [case["id"] for case in cases] != plan["answer_cases"] or len(cases) != 4:
        raise ValueError("candidate_case_set_mismatch")
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "kind": "known_failure_evidence_first_answer_comparison",
              "started_at": datetime.now(UTC).isoformat(), "plan_sha256": sha(plan_path),
              "bound_files": plan["bound_files"], "model_runtime": generator.public_metadata(),
              "human_review_count": 0, "semantic_review": "pending", "paid_service_calls": 0,
              "results": [], "calls": [], "status": "running", "analysis_calls": 0}
    runtime = EvidenceFirstMeetingRuntime(generator)
    original_generate = generator.generate_bounded

    def save():
        write(output / "report.json", report)

    def generated(messages, deadline):
        if len(report["calls"]) >= 4:
            raise ValueError("candidate_call_budget")
        call = {"kind": "answer", "messages": messages}
        report["calls"].append(call)
        save()
        try:
            result = original_generate(messages, deadline)
            call["output"] = dataclasses.asdict(result)
            call["effective_config"] = generator.last_effective_config
            return result
        except Exception as error:
            call["error"] = getattr(error, "code", type(error).__name__)
            raise
        finally:
            save()

    def forbidden_classification(*args, **kwargs):
        raise ValueError("classification_not_in_this_plan")

    generator.generate_bounded, generator.classify_bounded = generated, forbidden_classification
    try:
        for case in cases:
            started = time.perf_counter()
            row = {"id": case["id"]}
            try:
                row["result"] = runtime.answer(AnswerRequest.model_validate(case["payload"]))
                row["structural_status"] = "passed"
            except Exception as error:  # noqa: BLE001 - safe failure retained, no retry
                row["structural_status"] = "failed"
                row["error"] = getattr(error, "code", type(error).__name__)
            row["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
            report["results"].append(row)
            save()
            print(case["id"], row["structural_status"], flush=True)
        verify_plan(plan)
        report["sources_unchanged"] = True
        report["status"] = "completed_not_semantically_verified"
    finally:
        runtime.close()
        report["completed_at"] = datetime.now(UTC).isoformat()
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from doctrail.meeting_gguf import GGUFGenerator
    from scripts.serve_meetings_gguf import start_llama

    with start_llama(log_dir=args.output.parent / (args.output.name + "-server")) as service:
        generator = GGUFGenerator(service.url, service.token, service.manifest).load()
        run(generator, args.plan, args.output)


if __name__ == "__main__":
    main()
