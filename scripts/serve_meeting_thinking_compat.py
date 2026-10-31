"""C4 compatibility launcher: discard diagnostic contents, count every emitted byte."""
from __future__ import annotations

import hashlib
import os
import secrets
import subprocess
import threading
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from doctrail.meeting_thinking_transport import MANIFEST_SHA256
from doctrail.meeting_worker import worker_lease
from scripts.prepare_meeting_gguf import ROOT, prepare
from scripts.serve_meeting_thinking import DEFAULT_ROOT, MANIFEST, command
from scripts.serve_models import unused_port, wait_ready

CHUNK_BYTES = 8192


class DiscardDrain:
    """Constant-size transient reads; no content, excerpts or exception text retained."""

    def __init__(self, stream):
        self.stream = stream
        self.emitted_bytes = 0
        self.eof = False
        self.read_errors = 0
        self.join_errors = 0
        self.started = False
        self.thread = threading.Thread(target=self._read, daemon=True, name="native-discard-drain")

    def _read(self):
        try:
            while True:
                block = self.stream.read(CHUNK_BYTES)
                if not block:
                    self.eof = True
                    break
                self.emitted_bytes += len(block)
                del block
        except Exception:  # noqa: BLE001 - deliberately discard diagnostic exception text
            self.read_errors += 1

    def start(self):
        self.thread.start()
        self.started = True
        return self

    def join(self, seconds):
        try:
            self.thread.join(timeout=max(0, seconds))
            if self.thread.is_alive():
                self.join_errors += 1
        except Exception:  # noqa: BLE001 - metadata only
            self.join_errors += 1

    def metadata(self):
        return {"emitted_bytes": self.emitted_bytes, "eof": self.eof,
                "read_errors": self.read_errors, "join_errors": self.join_errors,
                "started": self.started, "joined": self.started and not self.thread.is_alive(),
                "chunk_bytes": CHUNK_BYTES,
                "raw_content_retained": False}


def cleanup_owned(process, drain, metrics):
    """One five-second allowance covers process termination and the drain join."""
    if metrics.get("cleanup_attempted") and process.poll() is not None and not drain.thread.is_alive():
        return
    prior_seconds = metrics.get("seconds", 0)
    prior_failed = metrics.get("cleanup_attempted", False) and metrics.get("within_budget") is not True
    started = time.monotonic()
    deadline = started + max(0, 5 - prior_seconds)
    cleanup_errors = metrics.get("cleanup_errors", 0)
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=min(2, max(0, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=max(0, deadline - time.monotonic()))
    except Exception:  # noqa: BLE001 - cleanup failures remain numeric and fail closed
        cleanup_errors += 1
        try:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=max(0, deadline - time.monotonic()))
        except Exception:  # noqa: BLE001
            cleanup_errors += 1
    finally:
        drain.join(max(0, deadline - time.monotonic()))
        if not drain.thread.is_alive():
            try:
                drain.stream.close()
            except Exception:  # noqa: BLE001
                cleanup_errors += 1
        metrics.update(seconds=prior_seconds + time.monotonic() - started,
                       stopped=process.poll() is not None, cleanup_errors=cleanup_errors,
                       cleanup_attempted=True, drain=drain.metadata())
        metrics["within_budget"] = (not prior_failed and metrics["seconds"] <= 5
            and metrics["stopped"] and cleanup_errors == 0 and metrics["drain"]["joined"]
            and metrics["drain"]["read_errors"] == 0 and metrics["drain"]["join_errors"] == 0)


@dataclass
class CompatService:
    process: subprocess.Popen
    url: str
    token: str = field(repr=False)
    manifest: Path
    receipt: dict
    cleanup: dict
    drain: DiscardDrain


@contextmanager
def start_llama(*, log_dir, model_dir=DEFAULT_ROOT, manifest=MANIFEST,
                phase_deadline=None, port=0, token=None, telemetry=None):
    metrics = telemetry if telemetry is not None else {}
    metrics.update(process_started=False, cleanup_attempted=False, drain={"started": False,
        "emitted_bytes": None, "eof": False, "joined": False, "read_errors": None,
        "join_errors": None, "raw_content_retained": False, "chunk_bytes": CHUNK_BYTES})
    phase_deadline = phase_deadline or time.monotonic() + 1200
    model_dir, manifest, log_dir = Path(model_dir), Path(manifest), Path(log_dir)
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != MANIFEST_SHA256:
        raise ValueError("compat_manifest_mismatch")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("invalid_llama_port")
    token = token or secrets.token_urlsafe(48)
    if not isinstance(token, str) or not 32 <= len(token) <= 256 or any(
            not 33 <= ord(c) <= 126 for c in token):
        raise ValueError("invalid_llama_token")
    with ExitStack() as stack:
        stack.enter_context(worker_lease(ROOT / ".local/meeting-generation.gpu.lock"))
        with worker_lease(ROOT / ".local/meeting-generation.worker.lock"):
            pass
        stack.enter_context(worker_lease(ROOT / ".local/meeting-llama.lease"))
        receipt = prepare(manifest, model_dir, allow_download=False)
        if time.monotonic() >= phase_deadline:
            raise TimeoutError("compat_phase_timeout")
        server = (model_dir / receipt["server_path"]).resolve()
        model = (model_dir / receipt["model"]["path"]).resolve()
        log_dir.mkdir(parents=True, exist_ok=False)  # reservation only, never a diagnostic file
        environment = {k: v for k, v in os.environ.items() if not k.startswith("LLAMA_ARG_")}
        environment.update(LLAMA_API_KEY=token, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        port = port or unused_port()
        process = subprocess.Popen(command(server, model, port), cwd=server.parent,
            env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        drain = DiscardDrain(process.stdout)
        metrics["process_started"] = True
        stack.callback(cleanup_owned, process, drain, metrics)
        drain.start()
        url = f"http://127.0.0.1:{port}"
        wait_ready(process, url + "/health", headers={"Authorization": "Bearer " + token},
                   timeout=min(240, max(0.01, phase_deadline - time.monotonic())))
        yield CompatService(process, url, token, manifest, receipt, metrics, drain)
