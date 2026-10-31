"""Explicit experimental worker entrypoint; failed answers never receive a fallback."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from doctrail.inference import _validate_token
from doctrail.meeting_answer_grammar import GrammarAnswerGenerator
from doctrail.meeting_answer_v2 import EvidenceFirstMeetingRuntime
from doctrail.meeting_worker import create_app, worker_admission


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8092)
    parser.add_argument("--llama-url", required=True)
    parser.add_argument("--llama-manifest", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.exit(2, "invalid_port\n")
    try:
        token = os.environ.get("DOCTRAIL_GENERATION_TOKEN", "")
        _validate_token(token)
        root = Path(__file__).resolve().parents[2]
        with worker_admission(root, external_gpu_owner=True):
            generator = GrammarAnswerGenerator(args.llama_url,
                os.environ.get("DOCTRAIL_LLAMA_TOKEN", ""), args.llama_manifest)
            try:
                runtime = EvidenceFirstMeetingRuntime(generator.load())
                app = create_app(token, lambda: runtime)
                import uvicorn
                uvicorn.run(app, host="127.0.0.1", port=args.port,
                            access_log=False, log_level="critical")
            finally:
                generator.close()
    except Exception:  # noqa: BLE001 - never disclose credentials, paths or native responses
        parser.exit(2, "experimental_generation_startup_failed\n")


if __name__ == "__main__":
    main()
