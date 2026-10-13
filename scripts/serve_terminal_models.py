"""Explicit experimental M4 terminal launcher; original launchers stay unchanged."""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

from doctrail.inference import _validate_token
from doctrail.terminal_inference import PROFILE, preflight, validate_health
from scripts.serve_models import ROOT, Services, stop_process, unused_port, wait_ready
from scripts.verify_java_service import java_executable


@contextmanager
def start_terminal_services(*, jar, database, model_root, device, token, log_dir,
                            java_port=0, worker_port=0, checkpoint=None):
    """Fail before launch on invalid artifacts; clean only this context's children."""
    if device not in {"cpu", "cuda"}:
        raise ValueError("invalid_device")
    _validate_token(token)
    if not Path(jar).is_file():
        raise ValueError("build_java_jar_first")
    java_port, worker_port = java_port or unused_port(), worker_port or unused_port()
    if worker_port == java_port:
        raise ValueError("ports_must_differ")
    if not 1 <= java_port <= 65535 or not 1 <= worker_port <= 65535:
        raise ValueError("invalid_port")
    _, location, _ = preflight(model_root, checkpoint)
    java_path = java_executable()
    java_url, worker_url = f"http://127.0.0.1:{java_port}", f"http://127.0.0.1:{worker_port}"
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    Path(database).resolve().parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, DOCTRAIL_DB=str(Path(database).resolve()),
                       DOCTRAIL_SECURE_COOKIE="0", DOCTRAIL_INFERENCE_TOKEN=token,
                       DOCTRAIL_INFERENCE_URL=worker_url, DOCTRAIL_EMBEDDING_PROFILE=PROFILE,
                       HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                       TOKENIZERS_PARALLELISM="false")
    started = time.perf_counter()
    with ExitStack() as stack:
        worker_log = stack.enter_context((log_dir / "terminal-inference.log").open("ab"))
        java_log = stack.enter_context((log_dir / "terminal-java.log").open("ab"))
        worker = subprocess.Popen(
            [sys.executable, "-m", "doctrail.terminal_inference", "--device", device,
             "--port", str(worker_port), "--model-root", str(Path(model_root).resolve()),
             "--checkpoint", str(location.absolute())],
            cwd=ROOT, env=environment, stdout=worker_log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        stack.callback(stop_process, worker)
        health = wait_ready(worker, worker_url + "/health",
                            headers={"Authorization": "Bearer " + token})
        validate_health(health, device)
        java = subprocess.Popen(
            [str(java_path), "-jar", str(Path(jar).resolve()),
             f"--server.port={java_port}", "--server.address=127.0.0.1"],
            cwd=ROOT, env=environment, stdout=java_log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        stack.callback(stop_process, java)
        wait_ready(java, java_url + "/api/health", timeout=60)
        yield Services(java, worker, java_url, worker_url, health,
                       round((time.perf_counter() - started) * 1000, 3))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, default=ROOT / "server/target/doctrail-server-0.1.0.jar")
    parser.add_argument("--database", type=Path,
                        default=ROOT / "var/doctrail-terminal-experimental.sqlite3")
    parser.add_argument("--model-root", type=Path, default=ROOT / "models")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--worker-port", type=int, default=8091)
    parser.add_argument("--log-dir", type=Path, default=ROOT / "var/terminal-model-service-logs")
    args = parser.parse_args()
    try:
        with start_terminal_services(
            jar=args.jar, database=args.database, model_root=args.model_root, device=args.device,
            token=os.environ.get("DOCTRAIL_INFERENCE_TOKEN") or secrets.token_urlsafe(48),
            log_dir=args.log_dir, java_port=args.port, worker_port=args.worker_port,
            checkpoint=args.checkpoint,
        ) as services:
            print(f"DocTrail experimental {PROFILE}: {services.java_url} (stop with Ctrl+C)", flush=True)
            while services.java.poll() is None and services.worker.poll() is None:
                time.sleep(0.5)
            raise RuntimeError("service_exited")
    except KeyboardInterrupt:
        pass
    except Exception:  # noqa: BLE001 - no secrets or raw subprocess errors
        parser.exit(1, "terminal_model_service_failed_check_local_logs\n")


if __name__ == "__main__":
    main()
