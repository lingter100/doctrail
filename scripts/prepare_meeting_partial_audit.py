"""Post-hoc, label-masked failure analysis; never a completed C1 quality gate."""
from __future__ import annotations

import argparse
import hashlib
import random
from pathlib import Path

from doctrail.meeting_answer_spans import build_span_catalog, grounded_answer_spans
from doctrail.meeting_answer_v2 import response_language
from doctrail.meeting_contract import AnswerRequest
from scripts.prepare_meeting_review_audit import read_snapshot, write_json
from scripts.probe_meeting_answer_review import CANDIDATE, local_path, safe_error, sha


def prepare(plan_path, report_path, oracle_path, seed_path, output):
    plan, plan_sha = read_snapshot(plan_path)
    report, report_sha = read_snapshot(report_path)
    spec = plan["phases"]["calibration"]
    if (report.get("candidate") != CANDIDATE or report.get("phase") != "calibration"
            or report.get("plan_sha256") != plan_sha or report.get("status") != "failed"
            or report.get("work_finalized") is not True
            or report.get("bound_files") != plan["bound_files"]
            or report.get("phase_inputs") != plan["phases"]):
        raise ValueError("partial_report_mismatch")
    cases, input_sha = read_snapshot(local_path(spec["input_file"]))
    oracles, oracle_sha = read_snapshot(oracle_path)
    if input_sha != spec["input_sha256"] or oracle_sha != spec["oracle_sha256"]:
        raise ValueError("partial_input_mismatch")
    ids = spec["case_ids"]
    rows = report["results"]
    n = len(rows)
    if (not 0 < n <= len(ids) or [r["id"] for r in rows] != ids[:n]
            or [r["id"] for r in cases["cases"]] != ids
            or [r["id"] for r in oracles["cases"]] != ids
            or any(r.get("structural_status") != "passed" for r in rows[:-1])
            or rows[-1].get("structural_status") != "failed"):
        raise ValueError("partial_prefix_mismatch")
    if not plan["bound_files"] or any(sha(local_path(p)) != h for p, h in plan["bound_files"].items()):
        raise ValueError("partial_source_mismatch")
    seed = Path(seed_path).read_bytes()
    if len(seed) < 32 or hashlib.sha256(seed).hexdigest() != plan["audit"]["seed_sha256"]:
        raise ValueError("partial_seed_mismatch")
    pairs = []
    for case, oracle, row in zip(cases["cases"][:n], oracles["cases"][:n], rows, strict=True):
        request = AnswerRequest.model_validate(case["payload"])
        drafts = [s for s in report["stages"] if s["case_id"] == case["id"] and s["stage"] == "D0"]
        if len(drafts) != 1 or "output" not in drafts[0]:
            raise ValueError("partial_draft_unavailable")
        baseline = grounded_answer_spans(drafts[0]["output"]["text"],
            build_span_catalog(request.contexts), request.contexts, response_language(request.query))
        final = ({k: row["result"][k] for k in ("status", "reason", "claims")}
                 if row["structural_status"] == "passed" else
                 {"status": "error", "error": "candidate_did_not_return_an_answer"})
        for role, answer in (("D0", baseline), ("C1", final)):
            pairs.append({"case_id": case["id"], "role": role, "question": request.query,
                          "contexts": case["payload"]["contexts"], "oracle": oracle, "answer": answer})
    random.Random(int.from_bytes(hashlib.sha256(seed).digest(), "big")).shuffle(pairs)
    samples, mappings = [], []
    for index, pair in enumerate(pairs, 1):
        identity = f"sample-{index:02}"
        mappings.append({"sample_id": identity, "case_id": pair["case_id"], "role": pair["role"]})
        samples.append({"sample_id": identity, **{k: pair[k] for k in
                        ("question", "contexts", "oracle", "answer")}})
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    pack = {"schema_version": 1, "purpose": "post_hoc_partial_failure_analysis_only",
        "planned_cases": len(ids), "attempted_cases": n, "unexecuted_cases": len(ids) - n,
        "selection_gate_passed": False, "human_review_count": 0,
        "limitations": "An incomplete prefix cannot establish calibration quality. Error shape and equal outputs can reveal roles. Lock judgments before opening mapping.",
        "samples": samples}
    write_json(output / "review-input.json", pack)
    write_json(output / "mapping.json", {"mappings": mappings})
    receipt = {"schema_version": 1, "purpose": pack["purpose"], "plan_sha256": plan_sha,
        "report_sha256": report_sha, "input_sha256": input_sha, "oracle_sha256": oracle_sha,
        "seed_sha256": plan["audit"]["seed_sha256"], "samples": len(samples),
        "current_source_hashes_match": True, "selection_gate_passed": False,
        "review_input_sha256": sha(output / "review-input.json"),
        "mapping_sha256": sha(output / "mapping.json"), "model_calls": 0, "human_review_count": 0}
    write_json(output / "receipt.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "report", "oracle", "seed", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.plan, args.report, args.oracle, args.seed, args.output)
    except Exception as error:  # noqa: BLE001 - no raw inputs in console errors
        parser.exit(1, safe_error(error) + "\n")
    print(f'samples={result["samples"]} model_calls=0 selection_gate_passed=false')


if __name__ == "__main__":
    main()
