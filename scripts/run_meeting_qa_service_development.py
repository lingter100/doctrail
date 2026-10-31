"""OPEN development only: two fixed questions through real Java BM25 and generic QA.

Actual dispatch requires the external fresh serial/resource gate. Local deadlines
are acceptance checks and HTTP limits, not a claim of hard process preemption.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_gguf import GGUFGenerator
from doctrail.meeting_worker import MeetingRuntime, create_app, worker_lease
from scripts.java_runtime import java_executable
from scripts.prepare_meeting_gguf import prepare
from scripts.serve_meeting_rag_service import make_server
from scripts.serve_models import unused_port, wait_ready

BUNDLE = ROOT / "data/meeting-qa-development/opensearch-v1"
MANIFEST = ROOT / "data/models/meetings-generation-ministral3-v1.json"
MODEL = ROOT / "models/meetings-ministral3-v1"
LIMITS = {"startup_seconds": 120, "operations_seconds": 240, "cleanup_seconds": 5,
          "whole_seconds": 365, "input_tokens": 4096, "output_tokens": 768,
          "request_seconds": 120, "generation_attempts": 2, "requested_tokens": 1536}


def failure(error):
    # Never serialize exception messages, URLs, headers or environment secrets.
    code = getattr(error, "code", None)
    return {"type": type(error).__name__, "code": code if isinstance(code, str)
            and code.startswith("generation_") and code.replace("_", "").isalnum()
            else "development_failed"}


class FailureRecord(dict):
    """Exception identities are retained in memory, outside serialized public data."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.errors = []
        self.error_lock = threading.Lock()


def record_error(target, error):
    with target.error_lock:
        if any(error is previous for previous in target.errors):
            return
        target.errors.append(error)
        row = failure(error)
        if target["first_failure"] is None:
            target["first_failure"] = row
        else:
            target["secondary_failures"].append(row)


class ObservedGenerator:
    """Delegation only; one count and one generation per fixed case, no extra calls."""

    def __init__(self, generator, case_ids):
        self.base, self.case_ids = generator, tuple(case_ids)
        self.rows, self.current = [], None
        self.attempts = self.requested_tokens = 0
        self.closed = False
        self.close_error = None
        self.state_lock = threading.Lock()
        self.invocation = threading.local()
        self.active = self.halted = False

    def __getattr__(self, name):
        return getattr(self.base, name)

    def reset(self, case_id):
        with self.state_lock:
            if self.active or self.halted:
                raise GenerationError("generation_development_worker_inflight")
            if case_id not in self.case_ids or any(r["id"] == case_id for r in self.rows):
                raise GenerationError("generation_development_case_replay")
            self.current = FailureRecord({"id": case_id, "count_calls": 0, "counted_input_tokens": None,
                "generation_attempts": 0, "generation_returned": False, "raw_output": None,
                "metrics": None, "effective_generation_config": None, "messages": None,
                "worker_request": None, "worker_result": None, "first_failure": None,
                "secondary_failures": []})
            self.rows.append(self.current)

    @property
    def row(self):
        return getattr(self.invocation, "row", self.current)

    @contextmanager
    def bind(self, request):
        with self.state_lock:
            row = self.current
            if self.active or row is None or row["worker_request"] is not None:
                raise GenerationError("generation_development_answer_replay")
            self.active = True
            self.invocation.row = row
        try:
            row["worker_request"] = request.model_dump()
            yield row
        finally:
            with self.state_lock:
                del self.invocation.row
                self.active = False

    def halt(self):
        with self.state_lock:
            self.halted = True

    def begin_request(self, deadline):
        if self.row is None:
            raise GenerationError("generation_development_unbound")
        try:
            return self.base.begin_request(deadline)
        except Exception as error:
            record_error(self.row, error)
            raise

    def end_request(self):
        # MeetingRuntime's finally executes while its first exception is active.
        # Capture parser/limit failure before a secondary end_request can mask it.
        active = sys.exception()
        if active is not None:
            record_error(self.row, active)
        try:
            return self.base.end_request()
        except Exception as error:
            record_error(self.row, error)
            raise

    def count_tokens(self, messages):
        row = self.row
        try:
            if row is None or row["count_calls"]:
                raise GenerationError("generation_development_count_limit")
            row["count_calls"] += 1
            row["messages"] = copy.deepcopy(messages)
            result = self.base.count_tokens(messages)
            row["counted_input_tokens"] = result
            return result
        except Exception as error:
            if row is not None:
                record_error(row, error)
            raise

    def generate_bounded(self, messages, deadline):
        row = self.row
        try:
            if (row is None or row["generation_attempts"] or self.attempts >= 2
                    or self.requested_tokens + 768 > 1536):
                raise GenerationError("generation_development_completion_limit")
            row["generation_attempts"] += 1
            self.attempts += 1
            self.requested_tokens += 768  # Failed calls consume budget too.
            result = self.base.generate_bounded(messages, deadline)
            row.update(generation_returned=True, raw_output=result.text,
                metrics={key: getattr(result, key) for key in
                    ("input_tokens", "output_tokens", "elapsed_seconds", "finish_reason")},
                effective_generation_config=copy.deepcopy(self.base.last_effective_config))
            return result
        except Exception as error:
            if row is not None:
                record_error(row, error)
            raise

    def classify_bounded(self, *args, **kwargs):
        raise GenerationError("generation_development_analysis_forbidden")

    def close(self):
        if not self.closed and self.base is not None:
            self.closed = True
            try:
                return self.base.close()
            except Exception as error:
                self.close_error = error
                if self.row is not None:
                    record_error(self.row, error)
                raise


class ObservedRuntime:
    """Capture actual worker inputs/results without consulting last_telemetry."""

    def __init__(self, observer):
        self.observer = observer
        self.runtime = MeetingRuntime(observer)

    def health(self):
        return self.runtime.health()

    def close(self):
        self.runtime.close()

    def analyze(self, request):
        raise GenerationError("generation_development_analysis_forbidden")

    def answer(self, request):
        with self.observer.bind(request) as row:
            try:
                result = self.runtime.answer(request)
                row["worker_result"] = copy.deepcopy(result)
                return result
            except Exception as error:
                record_error(row, error)
                raise


def remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError
    return value


def load_bundle(bundle=BUNDLE):
    from scripts.prepare_meeting_qa_development import reproduce
    reproduce(bundle)  # Existing exact original-source/case validation; no private QA.
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    cases = json.loads((bundle / "cases.json").read_text(encoding="utf-8"))["cases"]
    documents = [{**doc, "content": (bundle / doc["path"]).read_bytes()}
                 for doc in manifest["documents"]]
    if len(documents) != 3 or len(cases) != 2 or len({c["id"] for c in cases}) != 2:
        raise ValueError("fixed_bundle_required")
    return documents, cases


def cleanup_owned(processes, server, thread, report, *, observer=None, clock=time.monotonic):
    """One allowance for only the children/thread this invocation created."""
    started = clock()
    deadline = started + 5
    if server is not None:
        server.should_exit = True
    for process in reversed(processes):
        try:
            if process.poll() is None:
                process.terminate()
        except Exception as error:  # noqa: BLE001 - finish all owned cleanup, fixed metadata only
            record_error(report, error)
    for process in reversed(processes):
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=max(0, deadline - clock()))
        except Exception as error:  # noqa: BLE001 - continue cleanup after an owned child fails
            record_error(report, error)
    if thread is not None:
        try:
            thread.join(timeout=max(0, deadline - clock()))
            if thread.is_alive():
                server.force_exit = True
                raise TimeoutError
        except Exception as error:  # noqa: BLE001 - preserve first error and continue cleanup
            record_error(report, error)
    alive = []
    for process in processes:
        try:
            alive.append(process.poll() is None)
        except Exception as error:  # noqa: BLE001 - observation failure means absence unconfirmed
            record_error(report, error)
            alive.append(True)
    if observer is not None:
        try:
            observer.close()
        except Exception as error:  # noqa: BLE001 - transport cleanup must not mask first failure
            record_error(report, error)
        if observer.close_error is not None:
            record_error(report, observer.close_error)
    report["cleanup"] = {"elapsed_seconds": clock() - started,
        "owned_children_absent": not any(alive),
        "worker_stopped": thread is None or not thread.is_alive()}
    if (any(alive) or report["cleanup"]["elapsed_seconds"] > 5
            or not report["cleanup"]["worker_stopped"]):
        record_error(report, TimeoutError())


def java_environment(database, worker_url, token):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("DOCTRAIL_", "LLAMA_ARG_")) and key != "LLAMA_API_KEY"}
    env.update(DOCTRAIL_DB=str(database), DOCTRAIL_SECURE_COOKIE="0",
        DOCTRAIL_GENERATION_URL=worker_url, DOCTRAIL_GENERATION_TOKEN=token,
        DOCTRAIL_EMBEDDING_PROFILE="base", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    return env


@contextmanager
def start_services(jar, output, observer, report, startup):
    """Same generic native argv and HTTP runtime; separate DB and BM25-only Java."""
    processes, server, thread = [], None, None
    with ExitStack() as stack:
        stack.enter_context(worker_lease(ROOT / ".local/meeting-generation.gpu.lock"))
        stack.enter_context(worker_lease(ROOT / ".local/meeting-generation.worker.lock"))
        stack.enter_context(worker_lease(ROOT / ".local/meeting-llama.lease"))
        try:
            # Resolve the HTTP dependency before model preparation or native start.
            import uvicorn  # noqa: F401
            receipt = prepare(MANIFEST, MODEL, allow_download=False)
            identity = json.loads(MANIFEST.read_text(encoding="utf-8"))
            remaining(startup)
            ports = [unused_port() for _ in range(3)]
            if len(set(ports)) != 3:
                raise ValueError("ports_must_differ")
            native_port, worker_port, java_port = ports
            native_token, token = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
            native_url = f"http://127.0.0.1:{native_port}"
            worker_url = f"http://127.0.0.1:{worker_port}"
            java_url = f"http://127.0.0.1:{java_port}"
            env = java_environment(output / "development.sqlite3", worker_url, token)
            binary = (MODEL / receipt["server_path"]).resolve()
            native = subprocess.Popen([str(binary), "--model", str((MODEL / receipt["model"]["path"]).resolve()),
                "--host", "127.0.0.1", "--port", str(native_port), "--alias", identity["gguf"]["sha256"],
                "--ctx-size", "6144", "--parallel", "1", "--n-gpu-layers", "99",
                "--batch-size", "512", "--ubatch-size", "128", "--fit", "off",
                "--no-context-shift", "--no-webui", "--log-disable", "--no-warmup"], cwd=binary.parent,
                env=dict(env, LLAMA_API_KEY=native_token), stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            processes.append(native)
            wait_ready(native, native_url + "/health", headers={"Authorization": "Bearer " + native_token},
                       timeout=remaining(startup))
            generator = GGUFGenerator(native_url, native_token, MANIFEST)
            observer.base = generator
            generator.begin_request(startup)
            try:
                generator.load()
            finally:
                generator.end_request()
            app = create_app(token, lambda: ObservedRuntime(observer))
            server = make_server(app, worker_port)
            thread = threading.Thread(target=server.run, daemon=True, name="qa-development-http")
            thread.start()
            wait_ready(native, worker_url + "/health", headers={"Authorization": "Bearer " + token},
                       timeout=remaining(startup))
            java = subprocess.Popen([str(java_executable()), "-jar", str(jar.resolve()),
                "--server.address=127.0.0.1", f"--server.port={java_port}",
                "--doctrail.rag-answer-enabled=false", "--doctrail.embedding-profile=base"],
                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            processes.append(java)
            wait_ready(java, java_url + "/api/health", timeout=remaining(startup))
            remaining(startup)
            report["model"] = observer.public_metadata()
            yield java_url
        except BaseException as error:
            record_error(report, error)
            raise
        finally:
            cleanup_owned(processes, server, thread, report, observer=observer)


def operations(client, documents, cases, observer, report, deadline):
    def request(method, url, **kwargs):
        started = time.monotonic()
        response = client.request(method, url, timeout=remaining(deadline), **kwargs)
        remaining(deadline)
        return response, time.monotonic() - started

    response, _ = request("POST", "/api/auth/register", json={
        "email": "open-development@example.invalid", "password": secrets.token_urlsafe(32),
        "name": "Open development", "workspace_name": "OpenSearch development"})
    response.raise_for_status()
    workspace = response.json()["workspaces"][0]["id"]
    for doc in documents:
        response, elapsed = request("POST", f"/api/workspaces/{workspace}/documents",
            files={"file": (Path(doc["path"]).name, doc["content"], "text/markdown")},
            data={"title": doc["title"]})
        response.raise_for_status()
        result = response.json()
        report["documents"].append({"source_id": doc["document_id"], "java": result,
                                    "http_elapsed_seconds": elapsed})
        if result.get("status") != "ready":
            raise ValueError("document_not_ready")
    for index, case in enumerate(cases):
        observer.reset(case["id"])
        row = observer.current
        payload = {"query": case["question"], "workspace_id": workspace, "method": "bm25", "limit": 10}
        row["java_request"] = payload
        response, elapsed = request("POST", "/api/knowledge/search", json=payload)
        row["search"] = {"status_code": response.status_code, "body": response.json(),
                         "http_elapsed_seconds": elapsed}
        response.raise_for_status()
        try:
            response, elapsed = request("POST", "/api/knowledge/answer", json=payload)
            row["answer"] = {"status_code": response.status_code, "body": response.json(),
                             "http_elapsed_seconds": elapsed}
            response.raise_for_status()
            if observer.active:
                raise GenerationError("generation_development_worker_inflight")
        except Exception as error:
            record_error(row, error)
            observer.halt()
            report["unattempted_cases"] = [c["id"] for c in cases[index + 1:]]
            raise  # An HTTP failure does not prove the synchronous worker has stopped.
        # No retries or generation success inferred from a 200/abstention.


def execute(jar, jar_sha256, output, *, bundle=BUNDLE, launcher=start_services):
    documents, cases = load_bundle(bundle)
    if not jar.is_file() or hashlib.sha256(jar.read_bytes()).hexdigest() != jar_sha256:
        raise ValueError("jar_pin_mismatch")
    output.mkdir(parents=True, exist_ok=False)
    observer = ObservedGenerator(None, [case["id"] for case in cases])
    report = FailureRecord({"status": "stopped", "development_only": True, "human_reviews": 0,
        "heldout_evaluation": False, "model_quality_accepted": False, "limits": LIMITS,
        "settings": {"retrieval": "Java BM25", "limit": 10, "context": "full chunks",
            "runtime": "generic MeetingRuntime", "few_shot_examples": 4,
            "rag_answer_enabled": False, "compact_256_contract": False},
        "jar_sha256": jar_sha256, "documents": [], "cases": observer.rows,
        "source_manifest_sha256": hashlib.sha256((bundle / "manifest.json").read_bytes()).hexdigest(),
        "cases_sha256": hashlib.sha256((bundle / "cases.json").read_bytes()).hexdigest(),
        "generation_manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "first_failure": None, "secondary_failures": [], "unattempted_cases": []})
    started = time.monotonic()
    try:
        with launcher(jar, output, observer, report, started + 120) as url:
            deadline = min(started + 360, time.monotonic() + 240)
            with httpx.Client(base_url=url, trust_env=False, follow_redirects=False) as client:
                try:
                    operations(client, documents, cases, observer, report, deadline)
                except BaseException as error:
                    record_error(report, error)
                    raise
    except Exception as error:  # noqa: BLE001 - durable public report without raw exception text
        record_error(report, error)
    finally:
        report.update(generation_attempts=observer.attempts,
                      requested_generation_tokens=observer.requested_tokens,
                      elapsed_seconds=time.monotonic() - started)
        if report["elapsed_seconds"] > 365:
            record_error(report, TimeoutError())
        if report["first_failure"] is None and len(observer.rows) == 2:
            report["status"] = "completed_development_observation"
        try:
            (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2,
                allow_nan=False) + "\n", encoding="utf-8")
        except Exception as error:  # noqa: BLE001 - keep original failure in returned report
            record_error(report, error)
            report["status"] = "report_write_failed"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, required=True)
    parser.add_argument("--jar-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = execute(args.jar, args.jar_sha256, args.output)
    return 0 if result["status"] == "completed_development_observation" else 1


if __name__ == "__main__":
    raise SystemExit(main())
