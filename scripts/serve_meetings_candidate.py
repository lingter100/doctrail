"""Explicit experimental candidate launcher; no adoption, fallback, builds or downloads."""
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

from doctrail.inference import _validate_token
from doctrail.meeting_answer_grammar import DECODER_POLICY, GRAMMAR_SHA256
from doctrail.meeting_answer_v2 import ANSWER_POLICY
from scripts.prepare_meeting_gguf import DEFAULT_ROOT, MANIFEST
from scripts.serve_meetings_gguf import start_llama
from scripts.serve_models import ROOT, stop_process, unused_port, wait_ready
from scripts.verify_java_service import java_executable


@dataclass
class CandidateServices:
    java: subprocess.Popen
    worker: subprocess.Popen
    llama: subprocess.Popen
    java_url: str
    worker_url: str
    health: dict
    startup_ms: float
    retrieval: subprocess.Popen | None = None


@contextmanager
def start_services(*, jar, database, log_dir, model_dir=DEFAULT_ROOT, manifest=MANIFEST,
                   java_port=0, worker_port=0, llama_port=0, retrieval=False,
                   retrieval_model_root=None, retrieval_port=0, token=None):
    """Launch only the opt-in candidate; unwind owned children before native GPU lease."""
    token = token or secrets.token_urlsafe(48)
    _validate_token(token)
    if not Path(jar).is_file():
        raise ValueError("build_java_jar_first")
    requested = [java_port, worker_port, llama_port] + ([retrieval_port] if retrieval else [])
    if any(type(port) is not int or not 0 <= port <= 65535 for port in requested):
        raise ValueError("invalid_ports")
    ports = [port or unused_port() for port in requested]
    if len(set(ports)) != len(ports):
        raise ValueError("ports_must_differ")
    java_port, worker_port, llama_port = ports[:3]
    java_url, worker_url = f"http://127.0.0.1:{java_port}", f"http://127.0.0.1:{worker_port}"
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    Path(database).resolve().parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    for key in ("DOCTRAIL_INFERENCE_URL", "DOCTRAIL_INFERENCE_TOKEN", "DOCTRAIL_LLAMA_TOKEN",
                "LLAMA_API_KEY", "DOCTRAIL_GENERATION_URL", "DOCTRAIL_GENERATION_TOKEN"):
        environment.pop(key, None)
    environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                       TOKENIZERS_PARALLELISM="false", PYTHONUTF8="1",
                       DOCTRAIL_EMBEDDING_PROFILE="base")
    started = time.perf_counter()
    with ExitStack() as stack:
        llama = stack.enter_context(start_llama(log_dir=log_dir, model_dir=model_dir,
                                                manifest=manifest, port=llama_port))
        worker_log = stack.enter_context((log_dir / "generation.log").open("ab"))
        worker_env = dict(environment, DOCTRAIL_GENERATION_TOKEN=token,
                          DOCTRAIL_LLAMA_TOKEN=llama.token)
        worker = subprocess.Popen([sys.executable, "-m", "doctrail.meeting_worker_grammar",
            "--port", str(worker_port), "--llama-url", llama.url,
            "--llama-manifest", str(Path(llama.manifest).resolve())], cwd=ROOT, env=worker_env,
            stdout=worker_log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        stack.callback(stop_process, worker)
        health = wait_ready(worker, worker_url + "/health",
                            headers={"Authorization": "Bearer " + token}, timeout=180)
        decoder = health.get("runtime", {}).get("answer_decoder", {})
        if (health.get("experimental") is not True or health.get("answer_policy") != ANSWER_POLICY
                or decoder.get("policy") != DECODER_POLICY
                or decoder.get("grammar_sha256") != GRAMMAR_SHA256):
            raise RuntimeError("experimental_worker_identity_mismatch")
        java_env = dict(environment, DOCTRAIL_DB=str(Path(database).resolve()),
            DOCTRAIL_SECURE_COOKIE="0", DOCTRAIL_GENERATION_URL=worker_url,
            DOCTRAIL_GENERATION_TOKEN=token)
        retrieval_process = None
        if retrieval:
            retrieval_port = ports[3]
            retrieval_token = secrets.token_urlsafe(48)
            retrieval_url = f"http://127.0.0.1:{retrieval_port}"
            retrieval_env = dict(environment, DOCTRAIL_INFERENCE_TOKEN=retrieval_token,
                                 CUDA_VISIBLE_DEVICES="")
            retrieval_log = stack.enter_context((log_dir / "retrieval.log").open("ab"))
            retrieval_process = subprocess.Popen([sys.executable, "-m", "doctrail.inference",
                "--device", "cpu", "--port", str(retrieval_port), "--model-root",
                str(Path(retrieval_model_root or ROOT / "models").resolve())], cwd=ROOT,
                env=retrieval_env, stdout=retrieval_log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            stack.callback(stop_process, retrieval_process)
            wait_ready(retrieval_process, retrieval_url + "/health",
                       headers={"Authorization": "Bearer " + retrieval_token}, timeout=240)
            java_env.update(DOCTRAIL_INFERENCE_URL=retrieval_url,
                            DOCTRAIL_INFERENCE_TOKEN=retrieval_token)
        java_log = stack.enter_context((log_dir / "java.log").open("ab"))
        java = subprocess.Popen([str(java_executable()), "-jar", str(Path(jar).resolve()),
            f"--server.port={java_port}", "--server.address=127.0.0.1"], cwd=ROOT, env=java_env,
            stdout=java_log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        stack.callback(stop_process, java)
        wait_ready(java, java_url + "/api/health", timeout=60)
        yield CandidateServices(java, worker, llama.process, java_url, worker_url, health,
                                round((time.perf_counter() - started) * 1000, 3), retrieval_process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, default=ROOT / "server/target/doctrail-server-0.1.0.jar")
    parser.add_argument("--database", type=Path, default=ROOT / "var/meetings-experimental.sqlite3")
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--worker-port", type=int, default=8092)
    parser.add_argument("--llama-port", type=int, default=8093)
    parser.add_argument("--retrieval", action="store_true", help="enable base retrieval on CPU only")
    parser.add_argument("--no-retrieval", action="store_false", dest="retrieval")
    parser.set_defaults(retrieval=False)
    parser.add_argument("--log-dir", type=Path, default=ROOT / "var/meeting-candidate-logs")
    args = parser.parse_args()
    try:
        with start_services(jar=args.jar, database=args.database, log_dir=args.log_dir,
            model_dir=args.model_dir, manifest=args.manifest, java_port=args.port,
            worker_port=args.worker_port, llama_port=args.llama_port,
            retrieval=args.retrieval) as services:
            print(f"DocTrail EXPERIMENTAL meeting candidate ready: {services.java_url}; "
                  "natural-language answer quality is not approved.", flush=True)
            children = [services.java, services.worker, services.llama] + (
                [services.retrieval] if services.retrieval else [])
            while all(child.poll() is None for child in children):
                time.sleep(0.5)
            raise RuntimeError("service_exited")
    except KeyboardInterrupt:
        pass
    except Exception:  # noqa: BLE001 - do not expose child environment/native model output
        parser.exit(1, "experimental_meeting_service_failed_check_local_logs\n")


if __name__ == "__main__":
    main()
