"""Validate M5-B data and optionally count prompts with an offline tokenizer only."""

import argparse
import json
from pathlib import Path

from doctrail.generation_calibration import (
    ROOT,
    PreparationError,
    prepare,
    verify_freeze_manifest,
    write_report,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path,
                        default=ROOT / "data/evaluation/m5b-family-registry-v1.json")
    parser.add_argument("--calibration", type=Path,
                        default=ROOT / "data/evaluation/m5b-calibration-v1.json")
    parser.add_argument("--validation", type=Path,
                        default=ROOT / "data/evaluation/m5b-validation-v1.json")
    parser.add_argument("--examples", type=Path,
                        default=ROOT / "data/evaluation/m5b-policy-examples-v1.json")
    parser.add_argument("--model-manifest", type=Path,
                        default=ROOT / "data/models/m5-generation-v1.json")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--review", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-freeze", type=Path)
    parser.add_argument("--require-reviewed", action="store_true",
                        help="Fail unless structural, duplicate, and independent review gates pass.")
    args = parser.parse_args()
    try:
        if args.verify_freeze:
            print(json.dumps(verify_freeze_manifest(args.verify_freeze)))
            return 0
        if args.output is None:
            raise PreparationError("output_path_required")
        result = prepare(args.registry, args.calibration, args.validation, args.examples,
                         snapshot=args.snapshot, model_manifest=args.model_manifest,
                         review_paths=args.review)
        write_report(args.output, result)
        if args.require_reviewed and not result["model_free_prerequisites_passed"]:
            raise PreparationError("model_free_prerequisites_incomplete")
        if result["prompt_budget"]["status"] == "blocked":
            raise PreparationError("prompt_budget_overflow")
    except PreparationError as error:
        print(json.dumps({"status": "failed", "error_code": error.code}))
        return 1
    except (KeyError, TypeError, ValueError, OSError):
        print(json.dumps({"status": "failed", "error_code": "invalid_preparation_input"}))
        return 1
    print(json.dumps({"status": result["status"], "generation_ready": False,
                      "generation_calls": 0, "prompt_budget_status": result["prompt_budget"]["status"],
                      "independent_ai_review_complete": result["independent_ai_review_complete"],
                      "human_review_count": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
