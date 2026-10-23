"""Run the single registered decoder-only comparison without changing v2 prompts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from doctrail.meeting_answer_grammar import DECODER_POLICY, GRAMMAR_SHA256, GrammarAnswerGenerator
from scripts.probe_meeting_answer_v2 import run
from scripts.probe_meeting_gguf import verify_plan


def check_plan(path):
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if (plan.get("decoder_policy") != DECODER_POLICY
            or plan.get("grammar_sha256") != GRAMMAR_SHA256
            or plan.get("completion_calls") != 4
            or plan.get("analysis_calls") != 0 or plan.get("retries") != 0):
        raise ValueError("decoder_plan_mismatch")
    verify_plan(plan)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("candidate_output_exists")
    check_plan(args.plan)
    from scripts.serve_meetings_gguf import start_llama

    with start_llama(log_dir=args.output.parent / (args.output.name + "-server")) as service:
        generator = GrammarAnswerGenerator(service.url, service.token, service.manifest).load()
        run(generator, args.plan, args.output)


if __name__ == "__main__":
    main()
