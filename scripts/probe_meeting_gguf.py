"""One bounded, hash-bound local candidate check on known meeting development failures."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from doctrail.meeting_contract import AnalyzeRequest, AnswerRequest
from doctrail.meeting_worker import MeetingRuntime

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8", newline="\n")


def verify_plan(plan):
    for relative, digest in plan["bound_files"].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or sha(path) != digest:
            raise ValueError("candidate_source_binding_mismatch")
    data = json.loads((ROOT / plan["inputs"]).read_text(encoding="utf-8"))
    if len(data["cases"]) != 5 or len({c["id"] for c in data["cases"]}) != 5:
        raise ValueError("candidate_case_set_mismatch")
    for relative, digest in data["fixture_hashes"].items():
        if sha(ROOT / relative) != digest:
            raise ValueError("candidate_fixture_binding_mismatch")
    return data


def run(generator, plan_path, output):
    """The launcher owns the server; this runner owns only the adapter and its outputs."""
    output = Path(output)
    if output.exists():
        raise ValueError("candidate_output_exists")
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    data = verify_plan(plan)
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "kind": "known_failure_development_candidate",
              "started_at": datetime.now(UTC).isoformat(), "plan_sha256": sha(plan_path),
              "bound_files": plan["bound_files"], "model_runtime": generator.public_metadata(),
              "human_review_count": 0, "semantic_review": "pending", "paid_service_calls": 0,
              "results": [], "calls": [], "status": "running"}
    runtime = MeetingRuntime(generator)
    original_generate, original_classify = generator.generate_bounded, generator.classify_bounded

    def save():
        write(output / "report.json", report)

    def generated(messages, deadline):
        call = {"kind": "answer", "messages": messages}
        report["calls"].append(call)
        save()
        try:
            result = original_generate(messages, deadline)
            call["output"] = dataclasses.asdict(result) if dataclasses.is_dataclass(result) else vars(result)
            call["effective_config"] = generator.last_effective_config
            return result
        except Exception as error:
            call["error"] = getattr(error, "code", type(error).__name__)
            raise
        finally:
            save()

    def classified(prompts, deadline):
        call = {"kind": "classify", "prompts": prompts}
        report["calls"].append(call)
        save()
        try:
            labels, metrics = original_classify(prompts, deadline)
            call.update(labels=labels, metrics=metrics)
            return labels, metrics
        except Exception as error:
            call["error"] = getattr(error, "code", type(error).__name__)
            raise
        finally:
            save()

    generator.generate_bounded, generator.classify_bounded = generated, classified
    try:
        for case in data["cases"]:
            started = time.perf_counter()
            row = {"id": case["id"], "operation": case["operation"]}
            try:
                if case["operation"] == "analyze":
                    row["result"] = runtime.analyze(AnalyzeRequest.model_validate(case["payload"]))
                else:
                    row["result"] = runtime.answer(AnswerRequest.model_validate(case["payload"]))
                row["structural_status"] = "passed"
            except Exception as error:  # noqa: BLE001 - preserve safe failure and remaining cases
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
    # Heavy/runtime setup stays in the explicit local launcher, outside ordinary CI imports.
    from doctrail.meeting_gguf import GGUFGenerator
    from scripts.serve_meetings_gguf import start_llama

    with start_llama(log_dir=args.output.parent / (args.output.name + "-server")) as service:
        generator = GGUFGenerator(service.url, service.token, service.manifest).load()
        run(generator, args.plan, args.output)


if __name__ == "__main__":
    main()
