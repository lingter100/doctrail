"""Owned GPU24/28 launcher; one inference argv value changes, no downloads."""
from __future__ import annotations

import hashlib
import os
import secrets
import subprocess
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

from doctrail.meeting_thinking_transport import MANIFEST_SHA256
from doctrail.meeting_worker import worker_lease
from scripts.prepare_meeting_gguf import ROOT, prepare
from scripts.serve_meeting_thinking import DEFAULT_ROOT, MANIFEST
from scripts.serve_meeting_thinking import command as baseline_command
from scripts.serve_meeting_thinking_compat import CompatService, DiscardDrain, cleanup_owned
from scripts.serve_models import unused_port, wait_ready


def command(server, model, port, gpu_layers):
    if type(gpu_layers) is not int or gpu_layers not in (24, 28):
        raise ValueError("placement_gpu_layers")
    original = baseline_command(server, model, port)
    if original.count("--n-gpu-layers") != 1:
        raise ValueError("placement_baseline_argv")
    index = original.index("--n-gpu-layers") + 1
    if original[index] != "24":
        raise ValueError("placement_baseline_argv")
    candidate = list(original)
    candidate[index] = str(gpu_layers)
    if [i for i, pair in enumerate(zip(original, candidate, strict=True)) if pair[0] != pair[1]] != ([] if gpu_layers == 24 else [index]):
        raise ValueError("placement_argv_difference")
    return candidate


def normalized_argv(gpu_layers):
    return command("<verified-server>", "<verified-model>", "<loopback-port>", gpu_layers)


@contextmanager
def start_llama(*, gpu_layers, log_dir, model_dir=DEFAULT_ROOT, manifest=MANIFEST,
                phase_deadline=None, telemetry=None, port=0, token=None):
    metrics = telemetry if telemetry is not None else {}
    metrics.update(process_started=False, process_creation_attempted=False,
        process_absence_confirmed=True, cleanup_attempted=False,
        gpu_layers_requested=gpu_layers, gpu_layers_effective=None,
        flash_attention_requested="auto_default_unchanged", flash_attention_effective=None,
        metadata_gpu_fields={"manifest_local_execution_gpu_layers": 24,
                             "scope": "frozen_artifact_declaration_not_effective_placement"},
        normalized_argv=normalized_argv(gpu_layers))
    phase_deadline = phase_deadline or time.monotonic() + 1200
    model_dir, manifest, log_dir = Path(model_dir), Path(manifest), Path(log_dir)
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != MANIFEST_SHA256:
        raise ValueError("placement_manifest_identity")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("placement_port")
    token = token or secrets.token_urlsafe(48)
    if not isinstance(token, str) or not 32 <= len(token) <= 256 or any(not 33 <= ord(c) <= 126 for c in token):
        raise ValueError("placement_token")
    with ExitStack() as stack:
        stack.enter_context(worker_lease(ROOT / ".local/meeting-generation.gpu.lock"))
        with worker_lease(ROOT / ".local/meeting-generation.worker.lock"):
            pass
        stack.enter_context(worker_lease(ROOT / ".local/meeting-llama.lease"))
        try:
            receipt = prepare(manifest, model_dir, allow_download=False)
        except (OSError, ValueError) as error:
            raise ValueError("placement_asset_identity") from error
        if time.monotonic() >= phase_deadline:
            raise ValueError("placement_readiness_timeout")
        server = (model_dir / receipt["server_path"]).resolve()
        model = (model_dir / receipt["model"]["path"]).resolve()
        log_dir.mkdir(parents=True, exist_ok=False)
        environment = {k: v for k, v in os.environ.items() if not k.startswith("LLAMA_ARG_")}
        environment.update(LLAMA_API_KEY=token, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        port = port or unused_port()
        argv = command(server, model, port, gpu_layers)
        metrics["process_creation_attempted"] = True
        metrics["process_absence_confirmed"] = False
        try:
            process = subprocess.Popen(argv, cwd=server.parent, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            metrics["process_absence_confirmed"] = True
            raise
        drain = DiscardDrain(process.stdout)
        metrics.update(process_started=True, owned_pid=process.pid)
        stack.callback(cleanup_owned, process, drain, metrics)
        drain.start()
        url = f"http://127.0.0.1:{port}"
        wait_ready(process, url + "/health", headers={"Authorization": "Bearer " + token},
                   timeout=min(240, max(0.01, phase_deadline - time.monotonic())))
        yield CompatService(process, url, token, manifest, receipt, metrics, drain)
