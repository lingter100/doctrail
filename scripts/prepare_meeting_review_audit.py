"""Package frozen C1 outputs for independent judgment, without model calls.

The local mapping reveals D0/C1; give reviewers review-input.json only. Reviewers
may infer an error's role, so this masks labels, not guaranteed model blinding.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from doctrail.meeting_answer_spans import build_span_catalog, grounded_answer_spans
from doctrail.meeting_answer_v2 import response_language
from doctrail.meeting_contract import AnswerRequest, strict_json
from scripts.probe_meeting_answer_review import CANDIDATE, safe_error, sha


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def read_snapshot(path):
    """Parse and fingerprint one bounded read, never independently reopened data."""
    limit = 16 * 1024 * 1024
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("json_file_limit")
    return strict_json(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def prepare(report_path, cases_path, oracle_path, seed_path, output, expected_seed_sha):
    """Freeze an anonymous pair per case. No scoring or claim repair is performed."""
    seed = Path(seed_path).read_bytes()
    if hashlib.sha256(seed).hexdigest() != expected_seed_sha or len(seed) < 32:
        raise ValueError("audit_seed_mismatch")
    report, report_sha = read_snapshot(report_path)
    phase = report.get("phase")
    if (report.get("candidate") != CANDIDATE or phase not in {"calibration", "validation"}
            or report.get("status") != "completed_not_semantically_verified"
            or report.get("sources_unchanged") is not True
            or report.get("work_finalized") is not True):
        raise ValueError("audit_report_not_complete")
    spec = report["phase_inputs"][phase]
    case_data, cases_sha = read_snapshot(cases_path)
    oracle_data, oracle_sha = read_snapshot(oracle_path)
    if cases_sha != spec["input_sha256"] or oracle_sha != spec["oracle_sha256"]:
        raise ValueError("audit_input_hash_mismatch")
    cases = case_data["cases"]
    oracles = oracle_data["cases"]
    ids = spec["case_ids"]
    if (len(ids) != 8 or len(set(ids)) != 8 or [c["id"] for c in cases] != ids
            or [c["id"] for c in oracles] != ids
            or [r["id"] for r in report["results"]] != ids):
        raise ValueError("audit_case_set_mismatch")
    output = Path(output)
    if output.exists():
        raise ValueError("audit_output_exists")
    prepared = []
    for case, oracle, row in zip(cases, oracles, report["results"], strict=True):
        request = AnswerRequest.model_validate(case["payload"])
        stages = [s for s in report["stages"] if s["case_id"] == case["id"] and s["stage"] == "D0"]
        if len(stages) != 1 or "output" not in stages[0]:
            raise ValueError("audit_draft_missing_or_duplicate")
        catalog = build_span_catalog(request.contexts)
        baseline = grounded_answer_spans(stages[0]["output"]["text"], catalog,
                                        request.contexts, response_language(request.query))
        if row.get("structural_status") == "passed":
            final = {key: row["result"][key] for key in ("status", "reason", "claims")}
        elif row.get("error") == "generation_semantic_rejected":
            final = {"status": "error", "error": "candidate_did_not_return_an_answer"}
        else:
            raise ValueError("audit_operational_failure")
        for role, answer in (("D0", baseline), ("C1", final)):
            prepared.append({"case_id": case["id"], "role": role, "answer": answer,
                             "question": request.query, "contexts": case["payload"]["contexts"],
                             "oracle": oracle})
    random.Random(int.from_bytes(hashlib.sha256(seed).digest(), "big")).shuffle(prepared)
    samples, mapping = [], []
    for index, item in enumerate(prepared, start=1):
        sample_id = f"sample-{index:02}"
        mapping.append({"sample_id": sample_id, "case_id": item["case_id"], "role": item["role"]})
        samples.append({"sample_id": sample_id, "question": item["question"],
                        "contexts": item["contexts"], "oracle": item["oracle"], "answer": item["answer"]})
    pack = {"schema_version": 1, "purpose": "independent_case_judgment_before_candidate_comparison",
            "label_masking_limits": "Error shape or equal outputs may reveal a role; same underlying model and AI review are not independent human evidence.",
            "instructions": "Judge each sample only against its sources and fixed oracle; lock every judgment before opening the local role mapping or computing candidate scores.",
            "human_review_count": 0, "samples": samples}
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "review-input.json", pack)
    write_json(output / "mapping.json", {"schema_version": 1, "mappings": mapping})
    receipt = {"schema_version": 1, "candidate": CANDIDATE, "phase": phase,
               "report_sha256": report_sha, "plan_sha256": report["plan_sha256"],
               "input_sha256": cases_sha, "oracle_sha256": oracle_sha,
               "seed_sha256": expected_seed_sha, "samples": len(samples),
               "review_input_sha256": sha(output / "review-input.json"),
               "mapping_sha256": sha(output / "mapping.json"), "model_calls": 0,
               "judgments": 0, "human_review_count": 0}
    write_json(output / "receipt.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "cases", "oracle", "seed", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected-seed-sha", required=True)
    args = parser.parse_args()
    try:
        receipt = prepare(args.report, args.cases, args.oracle, args.seed, args.output,
                          args.expected_seed_sha)
    except Exception as error:  # noqa: BLE001 - source contents stay out of console output
        parser.exit(1, safe_error(error) + "\n")
    print(json.dumps({"samples": receipt["samples"], "model_calls": 0,
                      "review_input_sha256": receipt["review_input_sha256"]}))


if __name__ == "__main__":
    main()
