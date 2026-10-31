"""Development-only startup diagnostics around the unchanged inference entrypoint."""
from __future__ import annotations

import json
import ntpath
import os
import re
import sys
from collections import deque

from doctrail import inference


def startup_diagnostic(error):
    """Bounded code locations only: never exception text, locals or source lines."""
    def label(value):
        return re.sub(r"[^a-zA-Z0-9_.<>-]", "_", value[:80])

    chain, seen = [], set()
    while error is not None and id(error) not in seen and len(chain) < 4:
        seen.add(id(error))
        frames = deque(maxlen=8)
        trace, visited = error.__traceback__, 0
        while trace is not None and visited < 64:
            code = trace.tb_frame.f_code
            frames.append({"file": label(ntpath.basename(code.co_filename)),
                           "function": label(code.co_name), "line": trace.tb_lineno})
            trace, visited = trace.tb_next, visited + 1
        chain.append({"type": label(type(error).__name__), "frames": list(frames),
                      "frames_truncated": visited > 8 or trace is not None})
        error = error.__cause__ if error.__cause__ is not None else (
            None if error.__suppress_context__ else error.__context__)
    return {"code": "inference_startup_diagnostic", "stage": "worker_entrypoint",
            "exceptions": chain, "chain_truncated": error is not None}


def main():
    try:
        return inference.main()
    except SystemExit as exit_error:
        # Frozen main's parser.exit retains its caught startup error as context.
        # Context alone does not establish which load phase failed.
        error = exit_error.__context__
        if os.environ.get("DOCTRAIL_STARTUP_DIAGNOSTICS") == "1" and isinstance(error, Exception):
            try:
                sys.stderr.write(json.dumps(startup_diagnostic(error), ensure_ascii=True,
                                            separators=(",", ":")) + "\n")
            except Exception:  # noqa: BLE001, S110 - preserve exit without recursive logging
                pass
        raise


if __name__ == "__main__":
    main()
