"""Launch Java and experimental local generation; optional retrieval stays on CPU."""
from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from scripts.serve_models import ROOT, stop_process, unused_port, wait_ready
from scripts.verify_java_service import java_executable


@dataclass
class Services:
    java: subprocess.Popen
    worker: subprocess.Popen
    java_url: str
    worker_url: str
    health: dict
    startup_ms: float
    retrieval: subprocess.Popen | None = None


@contextmanager
def start_services(*, jar, database, model_root, device="cuda", token=None, log_dir,
                   java_port=0, worker_port=0, retrieval=False, retrieval_model_root=None,
                   retrieval_port=0):
    """Only the exact children created here are stopped; never build or download."""
    token = token or secrets.token_urlsafe(48)
    if device != "cuda" or len(token) < 32 or any(not 33 <= ord(c) <= 126 for c in token):
        raise ValueError("invalid_generation_configuration")
    if not Path(jar).is_file():
        raise ValueError("build_java_jar_first")
    java_port, worker_port = java_port or unused_port(), worker_port or unused_port()
    retrieval_port = retrieval_port or unused_port()
    ports = [java_port, worker_port] + ([retrieval_port] if retrieval else [])
    if len(set(ports)) != len(ports) or any(not 1 <= p <= 65535 for p in ports):
        raise ValueError("invalid_ports")
    java_url, worker_url = f"http://127.0.0.1:{java_port}", f"http://127.0.0.1:{worker_port}"
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    Path(database).resolve().parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, DOCTRAIL_DB=str(Path(database).resolve()),
        DOCTRAIL_SECURE_COOKIE="0", DOCTRAIL_GENERATION_TOKEN=token,
        DOCTRAIL_GENERATION_URL=worker_url, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
        TOKENIZERS_PARALLELISM="false", PYTHONUTF8="1")
    # A stale inherited inference URL could point at a GPU worker. Default BM25 is explicit.
    environment.pop("DOCTRAIL_INFERENCE_URL", None)
    environment.pop("DOCTRAIL_INFERENCE_TOKEN", None)
    environment["DOCTRAIL_EMBEDDING_PROFILE"] = "base"
    started = time.perf_counter()
    with ExitStack() as stack:
        worker_log = stack.enter_context((log_dir / "generation.log").open("ab"))
        java_log = stack.enter_context((log_dir / "java.log").open("ab"))
        worker = subprocess.Popen(
            [sys.executable, "-m", "doctrail.meeting_worker", "--port", str(worker_port),
             "--model-root", str(Path(model_root).resolve())], cwd=ROOT, env=environment,
            stdout=worker_log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        stack.callback(stop_process, worker)
        health = wait_ready(worker, worker_url + "/health",
                            headers={"Authorization": "Bearer " + token}, timeout=180)
        retrieval_process = None
        if retrieval:
            retrieval_token = secrets.token_urlsafe(48)
            retrieval_url = f"http://127.0.0.1:{retrieval_port}"
            environment.update(DOCTRAIL_INFERENCE_TOKEN=retrieval_token,
                               DOCTRAIL_INFERENCE_URL=retrieval_url)
            retrieval_log = stack.enter_context((log_dir / "retrieval.log").open("ab"))
            retrieval_process = subprocess.Popen(
                [sys.executable, "-m", "doctrail.inference", "--device", "cpu", "--port",
                 str(retrieval_port), "--model-root", str(Path(retrieval_model_root or
                                                           ROOT / "models").resolve())],
                cwd=ROOT, env=environment, stdout=retrieval_log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            stack.callback(stop_process, retrieval_process)
            wait_ready(retrieval_process, retrieval_url + "/health",
                       headers={"Authorization": "Bearer " + retrieval_token}, timeout=240)
        java = subprocess.Popen(
            [str(java_executable()), "-jar", str(Path(jar).resolve()),
             f"--server.port={java_port}"], cwd=ROOT, env=environment,
            stdout=java_log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        stack.callback(stop_process, java)
        wait_ready(java, java_url + "/api/health", timeout=60)
        yield Services(java, worker, java_url, worker_url, health,
                       round((time.perf_counter() - started) * 1000, 3), retrieval_process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, default=ROOT / "server/target/doctrail-server-0.1.0.jar")
    parser.add_argument("--database", type=Path, default=ROOT / "var/doctrail-java.sqlite3")
    parser.add_argument("--model-root", type=Path,
                        default=ROOT / "models/generation-m5-qwen3-1.7b")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--worker-port", type=int, default=8092)
    parser.add_argument("--retrieval", action="store_true", help="load E5/BGE on CPU only")
    parser.add_argument("--no-retrieval", action="store_false", dest="retrieval")
    parser.set_defaults(retrieval=False)
    parser.add_argument("--log-dir", type=Path, default=ROOT / "var/meeting-service-logs")
    args = parser.parse_args()
    try:
        with start_services(jar=args.jar, database=args.database, model_root=args.model_root,
            token=secrets.token_urlsafe(48), log_dir=args.log_dir,
            java_port=args.port, worker_port=args.worker_port, retrieval=args.retrieval) as services:
            print(f"DocTrail experimental meetings ready: {services.java_url}", flush=True)
            children = [services.java, services.worker] + (
                [services.retrieval] if services.retrieval else [])
            while all(child.poll() is None for child in children):
                time.sleep(0.5)
            raise RuntimeError("service_exited")
    except KeyboardInterrupt:
        pass
    except Exception:  # noqa: BLE001 - do not reveal child environment or raw errors
        parser.exit(1, "meeting_service_failed_check_local_logs\n")


if __name__ == "__main__":
    main()
