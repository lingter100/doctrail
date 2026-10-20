"""Opt-in GPU28 RAG worker; reuses pinned launcher, admission and owned cleanup."""
from __future__ import annotations

import argparse
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from doctrail.inference import _validate_token
from doctrail.meeting_service_rag import create_app, load_runtime
from doctrail.meeting_worker import worker_admission
from scripts.prepare_meeting_gguf import ROOT
from scripts.serve_meeting_gpu_placement import start_llama
from scripts.serve_meeting_thinking import DEFAULT_ROOT, MANIFEST
from scripts.serve_meeting_thinking_compat import cleanup_owned


@contextmanager
def start_service(*, token, log_dir, model_dir=DEFAULT_ROOT, manifest=MANIFEST,
                  telemetry=None):
    _validate_token(token)
    metrics = telemetry if telemetry is not None else {}
    started = time.monotonic()
    startup_deadline = started + 120
    native_metrics = metrics.setdefault("native", {})
    with start_llama(gpu_layers=28, log_dir=log_dir, model_dir=model_dir,
                     manifest=manifest, phase_deadline=startup_deadline,
                     telemetry=native_metrics) as native:
        cleanup_lock = threading.Lock()

        def cleanup():
            with cleanup_lock:
                cleanup_owned(native.process, native.drain, native.cleanup)
                return native.cleanup.get("within_budget") is True

        # Native launcher owns the GPU lease. The worker owns admission only.
        with worker_admission(ROOT, external_gpu_owner=True):
            runtime = None
            remaining = startup_deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("generation_startup_timeout")
            timer = threading.Timer(remaining, cleanup)
            timer.daemon = True
            timer.start()
            try:
                runtime = load_runtime(native, cleanup=cleanup, startup_deadline=startup_deadline)
            finally:
                timer.cancel()
                timer.join()
            # Includes native and both identity loaders, not HTTP serving/readiness.
            # Persistent service lifetime is not the old one-shot experiment cap.
            metrics["native_adapter_startup_seconds"] = time.monotonic() - started
            try:
                if metrics["native_adapter_startup_seconds"] >= 120:
                    raise ValueError("generation_startup_timeout")
                yield create_app(token, lambda: runtime)
            finally:
                runtime.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-service-rag", action="store_true", required=True)
    parser.add_argument("--port", type=int, default=8092)
    parser.add_argument("--log-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.exit(2, "invalid_port\n")
    try:
        with start_service(token=os.environ.get("DOCTRAIL_GENERATION_TOKEN", ""),
                           log_dir=args.log_dir) as app:
            import uvicorn
            uvicorn.run(app, host="127.0.0.1", port=args.port,
                        access_log=False, log_level="critical")
    except Exception:  # noqa: BLE001 - no credential/path/native text in server logs
        parser.exit(2, "generation_startup_or_cleanup_failed\n")


if __name__ == "__main__":
    main()
