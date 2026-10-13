"""Opt-in native Qwen3.5-9B candidate only; never downloads or starts Java/UI."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

from doctrail.meeting_qwen35 import GGUF_SHA256, MODEL_ID, MODEL_REVISION
from doctrail.meeting_worker import worker_lease
from scripts.prepare_meeting_gguf import ROOT, prepare
from scripts.serve_meetings_gguf import LlamaService
from scripts.serve_models import stop_process, unused_port, wait_ready

DEFAULT_ROOT = ROOT / "models/meetings-qwen35-v1"
MANIFEST = ROOT / "data/models/meetings-generation-qwen35-v1.json"
GPU_LAYERS = 24


@contextmanager
def start_llama(*, log_dir, model_dir=DEFAULT_ROOT, runtime_dir=None, port=0, token=None,
                manifest=MANIFEST):
    """Same shared GPU admission as 4B; fixed partial GPU offload, never auto-fit."""
    model_dir, manifest = Path(model_dir), Path(manifest)
    runtime_dir = Path(runtime_dir) if runtime_dir else model_dir / "runtime"
    if runtime_dir.resolve() != (model_dir / "runtime").resolve():
        raise ValueError("runtime_must_match_setup_receipt")
    token = token or secrets.token_urlsafe(48)
    if len(token) < 32 or any(not 33 <= ord(c) <= 126 for c in token):
        raise ValueError("invalid_llama_token")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("invalid_llama_port")
    port = port or unused_port()
    with ExitStack() as stack:
        stack.enter_context(worker_lease(ROOT / ".local/meeting-generation.gpu.lock"))
        with worker_lease(ROOT / ".local/meeting-generation.worker.lock"):
            pass
        stack.enter_context(worker_lease(ROOT / ".local/meeting-llama.lease"))
        receipt = prepare(manifest, model_dir, allow_download=False)
        identity = json.loads(manifest.read_text(encoding="utf-8"))
        if (identity.get("model") != MODEL_ID or identity.get("revision") != MODEL_REVISION
                or identity.get("gguf", {}).get("sha256") != GGUF_SHA256):
            raise ValueError("qwen35_identity_mismatch")
        server = (model_dir / receipt["server_path"]).resolve()
        model = (model_dir / receipt["model"]["path"]).resolve()
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        log = stack.enter_context((log_dir / "llama-qwen35.log").open("ab"))
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith("LLAMA_ARG_")}
        environment.update(LLAMA_API_KEY=token, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        process = subprocess.Popen([str(server), "--model", str(model), "--host", "127.0.0.1",
            "--port", str(port), "--alias", GGUF_SHA256, "--ctx-size", "6144", "--parallel", "1",
            "--n-gpu-layers", str(GPU_LAYERS), "--batch-size", "512", "--ubatch-size", "128",
            "--fit", "off", "--reasoning", "off", "--no-context-shift", "--no-webui", "--log-disable"],
            cwd=server.parent, env=environment, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        stack.callback(stop_process, process)
        url = f"http://127.0.0.1:{port}"
        wait_ready(process, url + "/health", headers={"Authorization": "Bearer " + token},
                   timeout=240)
        yield LlamaService(process, url, token, manifest, identity, receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--port", type=int, default=8093)
    parser.add_argument("--log-dir", type=Path, default=ROOT / "var/meeting-qwen35-logs")
    args = parser.parse_args()
    try:
        with start_llama(log_dir=args.log_dir, model_dir=args.model_dir,
                         manifest=args.manifest, port=args.port) as service:
            print("EXPERIMENTAL Qwen3.5 native candidate ready; no quality approval.", flush=True)
            while service.process.poll() is None:
                time.sleep(0.5)
            raise RuntimeError("native_service_exited")
    except KeyboardInterrupt:
        pass
    except Exception:  # noqa: BLE001 - never expose tokens, local paths or model output
        parser.exit(1, "experimental_qwen35_service_failed_check_local_logs\n")


if __name__ == "__main__":
    main()
