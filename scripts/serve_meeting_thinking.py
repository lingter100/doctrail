"""Owned C4 resource process only; offline verification and no warmup generation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from doctrail.meeting_thinking_transport import GGUF_SHA256, MANIFEST_SHA256
from doctrail.meeting_worker import worker_lease
from scripts.prepare_meeting_gguf import ROOT, prepare
from scripts.serve_models import unused_port, wait_ready

DEFAULT_ROOT = ROOT / "models/meetings-qwen35-v1"
MANIFEST = ROOT / "data/models/meetings-generation-qwen35-v1.json"


@dataclass
class ThinkingService:
    process: subprocess.Popen
    url: str
    token: str = field(repr=False)
    manifest: Path
    receipt: dict
    cleanup: dict


def stop_owned(process, metrics):
    if metrics and process.poll() is not None:
        return  # Keep the first cleanup measurement when ExitStack calls us again.
    previous_failed = bool(metrics) and not metrics.get("within_budget", False)
    previous_seconds = metrics.get("seconds", 0)
    started = time.monotonic()
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=max(0.01, 5 - (time.monotonic() - started)))
    finally:
        metrics.update(seconds=previous_seconds + time.monotonic() - started,
                       stopped=process.poll() is not None)
        metrics["within_budget"] = (not previous_failed and metrics["stopped"]
                                    and metrics["seconds"] <= 5)


def command(server, model, port):
    return [str(server), "--model", str(model), "--host", "127.0.0.1", "--port", str(port),
        "--alias", GGUF_SHA256, "--ctx-size", "6144", "--parallel", "1", "--n-gpu-layers", "24",
        "--batch-size", "512", "--ubatch-size", "128", "--fit", "off", "--jinja",
        "--reasoning", "on", "--reasoning-format", "deepseek", "--reasoning-budget", "512",
        "--no-warmup", "--cache-ram", "0", "--no-context-shift", "--no-webui", "--log-disable"]


@contextmanager
def start_llama(*, log_dir, model_dir=DEFAULT_ROOT, manifest=MANIFEST,
                phase_deadline=None, port=0, token=None):
    """The caller holds the request/phase watchdog; this context always owns cleanup."""
    phase_deadline = phase_deadline or time.monotonic() + 1200
    model_dir, manifest, log_dir = Path(model_dir), Path(manifest), Path(log_dir)
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != MANIFEST_SHA256:
        raise ValueError("thinking_manifest_mismatch")
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
            raise TimeoutError("thinking_phase_timeout")
        server = (model_dir / receipt["server_path"]).resolve()
        model = (model_dir / receipt["model"]["path"]).resolve()
        log_dir.mkdir(parents=True, exist_ok=False)
        log = stack.enter_context((log_dir / "native.log").open("xb"))
        environment = {k: v for k, v in os.environ.items() if not k.startswith("LLAMA_ARG_")}
        environment.update(LLAMA_API_KEY=token, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        port = port or unused_port()
        process = subprocess.Popen(command(server, model, port), cwd=server.parent,
            env=environment, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        metrics = {}
        stack.callback(stop_owned, process, metrics)
        url = f"http://127.0.0.1:{port}"
        wait_ready(process, url + "/health", headers={"Authorization": "Bearer " + token},
                   timeout=min(240, max(0.01, phase_deadline - time.monotonic())))
        yield ThinkingService(process, url, token, manifest, receipt, metrics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--log-dir", type=Path, required=True)
    args = parser.parse_args()
    # Standalone launcher provides metadata-only inspection, never generation.
    from doctrail.meeting_thinking_transport import ThinkingGenerator
    try:
        with start_llama(log_dir=args.log_dir, model_dir=args.model_dir) as service:
            generator = ThinkingGenerator(service.url, service.token, service.manifest)
            try:
                generator.load()
                print(json.dumps(generator.public_metadata(), ensure_ascii=False))
            finally:
                generator.close()
    except Exception:  # noqa: BLE001 - do not expose source, local paths or credentials
        parser.exit(1, "thinking_identity_probe_failed\n")


if __name__ == "__main__":
    main()
