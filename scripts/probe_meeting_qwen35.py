"""One known-failure comparison for the separately frozen Qwen3.5 candidate."""
from __future__ import annotations

import argparse
from pathlib import Path

from doctrail.meeting_qwen35 import Qwen35Generator
from scripts.probe_meeting_answer_grammar import check_plan
from scripts.probe_meeting_answer_v2 import run
from scripts.serve_meeting_qwen35 import start_llama


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('candidate_output_exists')
    check_plan(args.plan)
    with start_llama(log_dir=args.output.parent / (args.output.name + '-server')) as service:
        generator = Qwen35Generator(service.url, service.token, service.manifest).load()
        run(generator, args.plan, args.output)


if __name__ == '__main__':
    main()
