"""Launch the existing Java jar and local inference worker without builds/downloads."""

from __future__ import annotations

import argparse
import os
import secrets
import socket
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx

from scripts.verify_java_service import java_executable

ROOT = Path(__file__).resolve().parents[1]


def unused_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def wait_ready(process, url, *, headers=None, timeout=180):
    deadline = time.monotonic() + timeout
    with httpx.Client(timeout=2, trust_env=False) as client:
        while True:
            if process.poll() is not None:
                raise RuntimeError("service_startup_exited")
            try:
                response = client.get(url, headers=headers)
                if response.status_code == 200:
                    return response.json()
            except httpx.TransportError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError("service_startup_timeout")
            time.sleep(0.2)


@dataclass
class Services:
    java: subprocess.Popen
    worker: subprocess.Popen
    java_url: str
    worker_url: str
    health: dict
    startup_ms: float


@contextmanager
def start_services(*, jar, database, model_root, device, token, log_dir,
                   java_port=0, worker_port=0):
    """Stop precisely these child processes on failure or context exit."""
    if device not in {"cpu", "cuda"}:
        raise ValueError("invalid_device")
    if len(token) < 32 or any(not 33 <= ord(char) <= 126 for char in token):
        raise ValueError("invalid_inference_token")
    if not Path(jar).is_file():
        raise ValueError("build_java_jar_first")
    java_port = java_port or unused_port()
    worker_port = worker_port or unused_port()
    if worker_port == java_port:
        raise ValueError("ports_must_differ")
    if not 1 <= java_port <= 65535 or not 1 <= worker_port <= 65535:
        raise ValueError("invalid_port")
    java_url, worker_url = f"http://127.0.0.1:{java_port}", f"http://127.0.0.1:{worker_port}"
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    Path(database).resolve().parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, DOCTRAIL_DB=str(Path(database).resolve()),
                       DOCTRAIL_SECURE_COOKIE="0", DOCTRAIL_INFERENCE_TOKEN=token,
                       DOCTRAIL_INFERENCE_URL=worker_url,
                       HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                       TOKENIZERS_PARALLELISM="false")
    started = time.perf_counter()
    with ExitStack() as stack:
        worker_log = stack.enter_context((log_dir / "inference.log").open("ab"))
        java_log = stack.enter_context((log_dir / "java.log").open("ab"))
        worker = subprocess.Popen(
            [sys.executable, "-m", "doctrail.inference", "--device", device,
             "--port", str(worker_port), "--model-root", str(Path(model_root).resolve())],
            cwd=ROOT, env=environment, stdout=worker_log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        stack.callback(stop_process, worker)
        health = wait_ready(worker, worker_url + "/health",
                            headers={"Authorization": "Bearer " + token})
        java = subprocess.Popen(
            [str(java_executable()), "-jar", str(Path(jar).resolve()),
             f"--server.port={java_port}"],
            cwd=ROOT, env=environment, stdout=java_log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        stack.callback(stop_process, java)
        wait_ready(java, java_url + "/api/health", timeout=60)
        yield Services(java, worker, java_url, worker_url, health,
                       round((time.perf_counter() - started) * 1000, 3))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, default=ROOT / "server/target/doctrail-server-0.1.0.jar")
    parser.add_argument("--database", type=Path,
                        default=Path(os.environ.get("DOCTRAIL_DB", ROOT / "var/doctrail-java.sqlite3")))
    parser.add_argument("--model-root", type=Path, default=ROOT / "models")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--worker-port", type=int, default=8091)
    parser.add_argument("--log-dir", type=Path, default=ROOT / "var/model-service-logs")
    args = parser.parse_args()
    try:
        with start_services(jar=args.jar, database=args.database, model_root=args.model_root,
                            device=args.device,
                            token=os.environ.get("DOCTRAIL_INFERENCE_TOKEN") or secrets.token_urlsafe(48),
                            log_dir=args.log_dir, java_port=args.port,
                            worker_port=args.worker_port) as services:
            print(f"DocTrail ready: {services.java_url} (stop with Ctrl+C)", flush=True)
            while services.java.poll() is None and services.worker.poll() is None:
                time.sleep(0.5)
            raise RuntimeError("service_exited")
    except KeyboardInterrupt:
        pass
    except Exception:  # noqa: BLE001 - never print environment credentials or raw child errors
        parser.exit(1, "model_service_failed_check_local_logs\n")


if __name__ == "__main__":
    main()
