"""Opt-in local RAG assembly. Time limits are acceptance checks, not hard preemption."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx

from doctrail.meeting_answer_thinking import CANDIDATE_ID
from doctrail.meeting_service_rag import PROTOCOL
from doctrail.meeting_thinking_transport import (
    GGUF_SHA256,
    MODEL_ID,
    MODEL_REVISION,
    RUNTIME_COMMIT,
)
from doctrail.model_retrieval import load_model_manifest
from scripts.serve_meeting_service_rag import start_service
from scripts.serve_models import ROOT, unused_port
from scripts.verify_java_service import java_executable


class LaunchError(Exception):
    """Only fixed codes, never exception text, credentials or request bodies."""

    CODES = frozenset({
        "health_http_rejected", "health_response_limit", "health_invalid_schema",
        "generation_health_identity", "retrieval_health_identity", "java_health_identity",
        "worker_thread_failed", "worker_thread_exited", "java_exited", "retrieval_exited",
        "startup_timeout", "health_timeout", "service_unhealthy", "jar_pin_required",
        "jar_pin_mismatch", "invalid_ports", "ports_must_differ", "token_factory_failed",
        "owned_cleanup_failed", "service_failed",
    })

    def __init__(self, code):
        super().__init__(code if code in self.CODES else "service_failed")


def http_probe(url, token, timeout):
    headers = {"Authorization": "Bearer " + token} if token else {}
    try:
        with (httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client,
              client.stream("GET", url, headers=headers) as response):
            if response.status_code == 503:
                return None
            if response.status_code != 200:
                raise LaunchError("health_http_rejected")
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 65536:
                    raise LaunchError("health_response_limit")
            result = json.loads(content)
            if not isinstance(result, dict):
                raise LaunchError("health_invalid_schema")
            return result
    except (httpx.TransportError, OSError):
        return None
    except (ValueError, UnicodeError):
        raise LaunchError("health_invalid_schema") from None


def make_server(app, port):
    import uvicorn
    return uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
        access_log=False, log_level="critical", timeout_graceful_shutdown=5))


def check_generation(health):
    try:
        if (health["status"] != "ready" or health["protocol"] != PROTOCOL
                or health["model"] != MODEL_ID
                or health["revision"] != "gguf-sha256:" + GGUF_SHA256
                or health["answer"]["candidate_id"] != CANDIDATE_ID):
            raise ValueError
        for metadata in (health["answer"], health["extraction"]["runtime"]):
            if (metadata["repo_id"] != MODEL_ID
                    or metadata["original_revision"] != MODEL_REVISION
                    or metadata["revision"] != "gguf-sha256:" + GGUF_SHA256
                    or metadata["artifact"]["sha256"] != GGUF_SHA256
                    or metadata["runtime"]["commit"] != RUNTIME_COMMIT
                    or metadata["runtime"]["context_tokens"] != 6144):
                raise ValueError
        if (health["answer"]["runtime"]["max_input_tokens"] != 5120
                or health["answer"]["runtime"]["max_new_tokens"] != 928
                or health["answer"]["runtime"]["deadline_seconds"] != 90
                or health["extraction"]["limits"]["input_tokens"] != 4096
                or health["extraction"]["limits"]["output_tokens"] != 768
                or health["extraction"]["limits"]["deadline_seconds"] != 120):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise LaunchError("generation_health_identity") from None


def check_retrieval(health, specs):
    try:
        if (health["status"] != "ready" or health["runtime"]["device"] != "cpu"
                or health["runtime"]["embedding_dtype"] != "torch.float32"
                or health["runtime"]["reranker_dtype"] != "torch.float32"
                or health["embedding"]["dimension"] != 384):
            raise ValueError
        for key, field in (("e5", "embedding"), ("reranker", "reranker")):
            if (health[field]["model"] != specs[key]["repo_id"]
                    or health[field]["revision"] != specs[key]["revision"]
                    or health[field]["max_length"] != 512):
                raise ValueError
    except (KeyError, TypeError, ValueError):
        raise LaunchError("retrieval_health_identity") from None


class RunningService:
    def __init__(self, *, clock, sleep, probe, metrics):
        self.clock, self.sleep, self.probe, self.metrics = clock, sleep, probe, metrics
        self.java = self.retrieval = self.server = self.thread = self.app = None
        self.native_context = None
        self.native_entered = False
        self.thread_failed = False
        self.closed = False
        self._generation_token = self._retrieval_token = None

    def alive(self):
        if self.thread_failed:
            raise LaunchError("worker_thread_failed")
        if self.thread is not None and not self.thread.is_alive():
            raise LaunchError("worker_thread_exited")
        for name in ("java", "retrieval"):
            process = getattr(self, name)
            if process is not None and process.poll() is not None:
                raise LaunchError(name + "_exited")

    def health(self, deadline, *, startup=False):
        self.alive()
        for kind, url, token in (
            ("generation", self.generation_url + "/health", self._generation_token),
            ("retrieval", self.retrieval_url + "/health", self._retrieval_token),
            ("java", self.java_url + "/api/health", None),
        ):
            if kind == "java" and self.java is None:
                continue
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise LaunchError("startup_timeout" if startup else "health_timeout")
            value = self.probe(url, token, min(2, remaining))
            if self.clock() >= deadline:
                raise LaunchError("startup_timeout" if startup else "health_timeout")
            if value is None:
                return False
            if kind == "generation":
                check_generation(value)
            elif kind == "retrieval":
                check_retrieval(value, self.specs)
            elif value.get("status") != "ok" or value.get("version") != "0.1.0":
                # This proves HTTP/version only; opt-in/base are explicit launch config.
                raise LaunchError("java_health_identity")
        self.alive()
        return True

    def ready(self, deadline):
        while not self.health(deadline, startup=True):
            self.sleep(min(0.1, max(0, deadline - self.clock())))

    def monitor(self):
        """Health only. No warmup, answer, analysis or automatic restart."""
        while True:
            if not self.health(self.clock() + 6):
                raise LaunchError("service_unhealthy")
            self.sleep(0.5)

    def shutdown(self):
        if self.closed:
            return self.metrics["cleanup"]["accepted"]
        self.closed = True
        started = self.clock()
        errors = []
        prior_native = self.metrics.get("native_adapter", {}).get("native", {})
        prior_seconds = 0
        if prior_native.get("cleanup_attempted"):
            # A failed __enter__ can already have unwound the native context.
            # Charge that completed cleanup to this same whole-cleanup budget.
            prior_seconds = prior_native.get("seconds")
            if (not isinstance(prior_seconds, (int, float))
                    or isinstance(prior_seconds, bool)
                    or not math.isfinite(prior_seconds) or prior_seconds < 0):
                prior_seconds = None
                errors.append("native_cleanup_time_unconfirmed")
        deadline = started + (max(0, 5 - prior_seconds) if prior_seconds is not None else 0)
        prior_thread_failure = self.thread_failed
        remaining = lambda: max(0, deadline - self.clock())
        # Do not wait for native-dependent handlers before requesting native stop.
        for name in ("java", "retrieval"):
            process = getattr(self, name)
            if self._process_alive(process, name, errors):
                try:
                    process.terminate()  # Windows forced termination, not graceful JVM proof.
                except Exception:  # noqa: BLE001
                    errors.append(name + "_terminate_failed")
        if self.server is not None:
            self.server.should_exit = True
        runtime = getattr(getattr(self.app, "state", None), "runtime", None)
        if runtime is not None:
            try:
                if runtime._stop() is not True:
                    errors.append("native_cleanup_failed")
            except Exception:  # noqa: BLE001
                errors.append("native_cleanup_failed")
        elif self.native_entered:
            # Startup failed before lifespan installed runtime: no authenticated
            # requests were admitted. Close the owning context before worker join.
            self._exit_native(errors)
        if self.thread is not None:
            try:
                self.thread.join(timeout=remaining())
            except Exception:  # noqa: BLE001
                errors.append("worker_join_failed")
            if self.thread.is_alive():
                errors.append("worker_join_incomplete")
                self.server.force_exit = True
        for name in ("java", "retrieval"):
            process = getattr(self, name)
            if process is None:
                continue
            try:
                if self._process_alive(process, name, errors):
                    process.kill()
                process.wait(timeout=remaining())
            except Exception:  # noqa: BLE001
                errors.append(name + "_wait_failed")
        self._exit_native(errors)  # Continue owned cleanup even after the acceptance deadline.
        native = self.metrics.get("native_adapter", {}).get("native", {})
        native_absent = (not self.metrics.get("native_attempted")
                         or native.get("process_absence_confirmed") is True
                         or native.get("stopped") is True)
        if native.get("process_started"):
            native_absent = (native.get("stopped") is True
                             and native.get("drain", {}).get("joined") is True)
        if not native_absent and self.metrics.get("native_attempted"):
            errors.append("native_exit_unconfirmed")
        if native.get("cleanup_attempted") and "native_cleanup_failed" not in errors and (
                native.get("within_budget") is not True
                or native.get("cleanup_errors") != 0
                or native.get("drain", {}).get("read_errors") != 0
                or native.get("drain", {}).get("join_errors") != 0):
            errors.append("native_cleanup_failed")
        alive = {"worker": self.thread is not None and self.thread.is_alive(),
                 **{name: self._process_alive(getattr(self, name), name, errors)
                    for name in ("java", "retrieval")}}
        if self.thread_failed and not prior_thread_failure:
            errors.append("worker_shutdown_failed")
        outer_elapsed = self.clock() - started
        elapsed = None if prior_seconds is None else prior_seconds + outer_elapsed
        accepted = not errors and not any(alive.values()) and elapsed is not None and elapsed <= 5
        self.metrics["cleanup"] = {"accepted": accepted, "elapsed_seconds": elapsed,
            "prior_native_cleanup_seconds": prior_seconds, "outer_elapsed_seconds": outer_elapsed,
            "errors": errors, "alive": alive, "native_absence_confirmed": native_absent,
            "hard_preemption_proven": False, "windows_child_termination": "forced"}
        return accepted

    @staticmethod
    def _process_alive(process, name, errors):
        if process is None:
            return False
        try:
            return process.poll() is None
        except Exception:  # noqa: BLE001 - still attempt other owned cleanup after observation failure
            errors.append(name + "_poll_failed")
            return True

    def _exit_native(self, errors):
        if self.native_entered:
            self.native_entered = False
            try:
                self.native_context.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                errors.append("native_context_cleanup_failed")


@contextmanager
def start_services(*, jar, jar_sha256, database, log_dir, model_root=ROOT / "models",
                   java_port=0, retrieval_port=0, generation_port=0, metrics=None,
                   native_factory=start_service, process_factory=subprocess.Popen,
                   server_factory=make_server, thread_factory=threading.Thread,
                   probe=http_probe, clock=time.monotonic, sleep=time.sleep,
                   token_factory=lambda: secrets.token_urlsafe(48),
                   java_resolver=java_executable, port_factory=unused_port, environment=None,
                   observer=None):
    """Minimal assembly seam. Injected factories are only for synthetic unit checks."""
    metrics = metrics if metrics is not None else {}
    service = RunningService(clock=clock, sleep=sleep, probe=probe, metrics=metrics)
    started = clock()
    deadline = started + 120
    jar, database, log_dir = Path(jar).resolve(), Path(database).resolve(), Path(log_dir).resolve()
    if not re.fullmatch(r"[a-f0-9]{64}", jar_sha256) or not jar.is_file():
        raise LaunchError("jar_pin_required")
    with jar.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != jar_sha256:
            raise LaunchError("jar_pin_mismatch")
    log_dir.mkdir(parents=True, exist_ok=False)
    database.parent.mkdir(parents=True, exist_ok=True)
    ports = [java_port, retrieval_port, generation_port]
    if any(type(port) is not int or not 0 <= port <= 65535 for port in ports):
        raise LaunchError("invalid_ports")
    ports = [port or port_factory() for port in ports]
    if len(set(ports)) != 3:
        raise LaunchError("ports_must_differ")
    java_port, retrieval_port, generation_port = ports
    service.java_url = f"http://127.0.0.1:{java_port}"
    service.retrieval_url = f"http://127.0.0.1:{retrieval_port}"
    service.generation_url = f"http://127.0.0.1:{generation_port}"
    generation_token, retrieval_token = token_factory(), token_factory()
    if (generation_token == retrieval_token or any(not isinstance(value, str)
            or not re.fullmatch(r"[!-~]{32,256}", value)
            for value in (generation_token, retrieval_token))):
        raise LaunchError("token_factory_failed")
    service._generation_token, service._retrieval_token = generation_token, retrieval_token
    env = dict(os.environ if environment is None else environment)
    for key in list(env):
        if key.startswith(("DOCTRAIL_", "LLAMA_ARG_")) or key == "LLAMA_API_KEY":
            env.pop(key)
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
               PYTHONUTF8="1")
    service.specs = load_model_manifest()["models"]
    metrics.update(schema_version=1, startup_accepted=False, jar_sha256=jar_sha256,
                   java_config={"rag_answer_enabled": True, "embedding_profile": "base",
                                "verification": "pinned_jar_and_explicit_arguments_only"},
                   required_request={"method": "hybrid_rerank", "answer_limit": 5},
                   native_attempted=False)
    try:
        java = java_resolver()
        if clock() >= deadline:
            raise LaunchError("startup_timeout")
        service.retrieval = process_factory(
            [sys.executable, "-m", "doctrail.inference", "--device", "cpu", "--port",
             str(retrieval_port), "--model-root", str(Path(model_root).resolve())],
            cwd=ROOT, env=dict(env, DOCTRAIL_INFERENCE_TOKEN=retrieval_token,
                              CUDA_VISIBLE_DEVICES=""),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        metrics["native_attempted"] = True
        options = {} if observer is None else {"observer": observer}
        service.native_context = native_factory(token=generation_token,
            log_dir=log_dir / "native", telemetry=metrics.setdefault("native_adapter", {}), **options)
        service.app = service.native_context.__enter__()
        service.native_entered = True
        if clock() >= deadline:
            raise LaunchError("startup_timeout")
        service.server = server_factory(service.app, generation_port)
        def run_worker():
            try:
                service.server.run()
            except BaseException:  # noqa: BLE001 - capture thread SystemExit without raw text
                service.thread_failed = True
        service.thread = thread_factory(target=run_worker, name="doctrail-rag-http", daemon=True)
        service.thread.start()
        service.ready(deadline)
        service.java = process_factory(
            [str(java), "-jar", str(jar), "--server.address=127.0.0.1",
             f"--server.port={java_port}", "--doctrail.rag-answer-enabled=true",
             "--doctrail.embedding-profile=base", f"--doctrail.db={database}",
             "--doctrail.secure-cookie=0"],
            cwd=ROOT, env=dict(env, DOCTRAIL_INFERENCE_URL=service.retrieval_url,
                DOCTRAIL_INFERENCE_TOKEN=retrieval_token,
                DOCTRAIL_GENERATION_URL=service.generation_url,
                DOCTRAIL_GENERATION_TOKEN=generation_token),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        service.ready(deadline)
        metrics.update(startup_accepted=True, startup_seconds=clock() - started,
                       java_url=service.java_url, generation_url=service.generation_url,
                       retrieval_url=service.retrieval_url)
        yield service
    except BaseException as error:
        metrics["failure"] = str(error) if isinstance(error, LaunchError) else (
            "interrupted" if isinstance(error, KeyboardInterrupt) else "service_failed")
        if isinstance(error, KeyboardInterrupt):
            raise
        raise LaunchError(metrics["failure"]) from None
    finally:
        metrics.setdefault("startup_seconds", clock() - started)
        accepted = service.shutdown()
        (log_dir / "lifecycle.json").write_text(
            json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        if not accepted:
            raise LaunchError("owned_cleanup_failed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-service-rag", action="store_true", required=True)
    parser.add_argument("--jar", type=Path, default=ROOT / "server/target/doctrail-server-0.1.0.jar")
    parser.add_argument("--jar-sha256", required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--retrieval-port", type=int, default=8091)
    parser.add_argument("--generation-port", type=int, default=8092)
    args = parser.parse_args(argv)
    try:
        with start_services(jar=args.jar, jar_sha256=args.jar_sha256, database=args.database,
                log_dir=args.log_dir, java_port=args.port, retrieval_port=args.retrieval_port,
                generation_port=args.generation_port) as service:
            print(f"DocTrail experimental service ready: {service.java_url}", flush=True)
            service.monitor()
    except KeyboardInterrupt:
        return
    except Exception:  # noqa: BLE001 - no credentials, raw health/model or exception strings
        parser.exit(1, "rag_service_failed_check_lifecycle_record\n")


if __name__ == "__main__":
    main()
