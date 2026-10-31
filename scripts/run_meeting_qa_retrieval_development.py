"""Six fixed OPEN development searches through existing Java and CPU retrieval.

Actual execution requires the external fresh serial/resource gate. No generation,
analysis, retries, warmup requests or changes to the production ranking path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import secrets
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from doctrail.model_retrieval import load_model_manifest
from scripts.java_runtime import java_executable
from scripts.run_meeting_qa_service_development import (
    BUNDLE,
    FailureRecord,
    cleanup_owned,
    load_bundle,
    record_error,
    remaining,
)
from scripts.serve_meeting_rag_service import check_retrieval
from scripts.serve_models import unused_port, wait_ready

MANIFEST = ROOT / "data/models/m3-models.json"
METHODS = ("bm25", "dense", "hybrid")
LIMITS = {"startup_seconds": 240, "operations_seconds": 360, "cleanup_seconds": 5,
    "whole_seconds": 605, "external_seconds": 650, "search_requests": 6,
    "generation_requests": 0, "cpu_threads": 2, "rss_gib": 6,
    "start_available_gib": 8, "host_available_gib": 2, "retrieval_limit": 10}
# This sets the existing worker's thread settings before its normal eager load.
WORKER_BOOTSTRAP = (
    "import runpy,torch;torch.set_num_threads(2);torch.set_num_interop_threads(2);"
    "runpy.run_module('doctrail.inference',run_name='__main__')"
)
STARTUP_STREAM_BYTES = 1024 * 1024


class StartupDiagnostics:
    """Private bounded startup bytes; keep draining, but never capture ready traffic."""

    def __init__(self, output, report):
        self.output, self.report = output, report
        self.streams = []
        self.deadline = None
        self.close_error = None
        report["startup_diagnostics"] = []

    def attach(self, role, process):
        row = {"role": role, "phase": "waiting_ready", "pid": process.pid,
               "exit_before_cleanup": None, "code": "not_ready", "streams": []}
        self.report["startup_diagnostics"].append(row)
        for name in ("stdout", "stderr"):
            state = {"pipe": getattr(process, name), "data": bytearray(), "capture": True,
                     "truncated": False, "error": None, "lock": threading.Lock()}
            state["thread"] = threading.Thread(target=self._drain, args=(state,), daemon=True)
            self.streams.append((row, name, state))
            state["thread"].start()
        return row

    @staticmethod
    def _drain(state):
        try:
            with state["pipe"] as pipe:
                while chunk := pipe.read1(8192):
                    with state["lock"]:
                        if state["capture"]:
                            room = STARTUP_STREAM_BYTES - len(state["data"])
                            state["data"].extend(chunk[:room])
                            state["truncated"] |= len(chunk) > room
        except Exception as error:  # noqa: BLE001 - only safe error metadata reaches report
            state["error"] = error

    def ready(self, row):
        for owner, _, state in self.streams:
            if owner is row:
                with state["lock"]:
                    state["capture"] = False
        row.update(phase="ready", code="ready")

    def close(self):
        # Called inside cleanup_owned's existing five-second allowance.
        for row, name, state in self.streams:
            state["thread"].join(timeout=max(0, self.deadline - time.monotonic()))
            complete = not state["thread"].is_alive()
            with state["lock"]:
                state["capture"] = False
                data = bytes(state["data"])
            if not complete:
                self.close_error = self.close_error or TimeoutError()
            if state["error"] is not None:
                record_error(self.report, state["error"])
            path = self.output / f"startup-{row['role']}-{name}.log"
            with path.open("xb") as stream:
                stream.write(data)
            row["streams"].append({"stream": name, "path": path.name,
                "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "truncated": state["truncated"], "drain_complete": complete,
                "read_error": None if state["error"] is None else type(state["error"]).__name__,
                "capture_scope": "startup_before_ready_only", "private": True})


def environment(database, worker_url, token):
    env = {key: value for key, value in os.environ.items()
        if not key.startswith(("DOCTRAIL_", "LLAMA_ARG_")) and key != "LLAMA_API_KEY"}
    env.update(DOCTRAIL_DB=str(database), DOCTRAIL_SECURE_COOKIE="0",
        DOCTRAIL_INFERENCE_URL=worker_url, DOCTRAIL_INFERENCE_TOKEN=token,
        DOCTRAIL_GENERATION_URL="", DOCTRAIL_GENERATION_TOKEN="",
        DOCTRAIL_EMBEDDING_PROFILE="base", DOCTRAIL_RAG_ANSWER_ENABLED="false",
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
        CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="2", MKL_NUM_THREADS="2",
        OPENBLAS_NUM_THREADS="2", NUMEXPR_NUM_THREADS="2", PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1")
    return env


@contextmanager
def start_services(jar, output, report, startup):
    """Only owned worker/Java children, one shared startup and cleanup budget."""
    processes = []
    diagnostics = StartupDiagnostics(output, report)
    current = current_row = None
    try:
        worker_port, java_port = unused_port(), unused_port()
        if worker_port == java_port:
            raise ValueError("ports_must_differ")
        worker_url, java_url = f"http://127.0.0.1:{worker_port}", f"http://127.0.0.1:{java_port}"
        token = secrets.token_urlsafe(48)
        env = environment(output / "retrieval.sqlite3", worker_url, token)
        specs = load_model_manifest(MANIFEST)["models"]
        report["startup_phase"] = "java_validation"
        java = java_executable()
        remaining(startup)
        report["startup_phase"] = "worker_launch"
        worker_env = {**env, "DOCTRAIL_STARTUP_DIAGNOSTICS": "1"}
        worker = subprocess.Popen([sys.executable, "-B", "-c", WORKER_BOOTSTRAP,
            "--device", "cpu", "--model-root", str(ROOT / "models"), "--port", str(worker_port)],
            cwd=ROOT, env=worker_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        processes.append(worker)
        report["owned_pids"] = [worker.pid]
        current, current_row = worker, diagnostics.attach("worker", worker)
        report["startup_phase"] = "worker_ready_check"
        health = wait_ready(worker, worker_url + "/health",
            headers={"Authorization": "Bearer " + token}, timeout=remaining(startup))
        remaining(startup)
        current_row["phase"] = "health_validation"
        check_retrieval(health, specs)
        diagnostics.ready(current_row)
        report["retrieval_health"] = health
        current = current_row = None
        report["startup_phase"] = "java_launch"
        backend = subprocess.Popen([str(java), "-jar", str(jar.resolve()),
            "--server.address=127.0.0.1", f"--server.port={java_port}",
            "--doctrail.embedding-profile=base", "--doctrail.rag-answer-enabled=false",
            "--doctrail.generation-url=", "--doctrail.generation-token="],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        processes.append(backend)
        report["owned_pids"].append(backend.pid)
        current, current_row = backend, diagnostics.attach("java", backend)
        report["startup_phase"] = "java_ready_check"
        java_health = wait_ready(backend, java_url + "/api/health", timeout=remaining(startup))
        remaining(startup)
        current_row["phase"] = "health_validation"
        if java_health.get("status") != "ok" or java_health.get("version") != "0.1.0":
            raise ValueError("java_health_identity")
        report["java_health"] = java_health
        diagnostics.ready(current_row)
        current = current_row = None
        report["startup_phase"] = "ready"
        yield java_url
    except BaseException as error:
        record_error(report, error)
        if current_row is not None:
            try:
                code = current.poll()
                current_row["exit_before_cleanup"] = code
                current_row["code"] = "exited_before_ready" if code is not None else "startup_failed"
            except Exception as observation:  # noqa: BLE001 - preserve original error
                current_row["code"] = "exit_unreadable"
                record_error(report, observation)
        raise
    finally:
        diagnostics.deadline = time.monotonic() + 5
        cleanup_owned(processes, None, None, report, observer=diagnostics)


def plan(cases):
    return [FailureRecord({"case_id": case["id"], "method": method, "status": "unattempted",
        "first_failure": None, "secondary_failures": []})
        for case in cases for method in METHODS]


def current_chunks(documents, uploaded):
    """Bind every returned chunk to the fresh ordinary document's current source."""
    if len(documents) != len(uploaded):
        raise ValueError("document_count")
    chunks, document_ids = {}, set()
    for source, row in zip(documents, uploaded, strict=True):
        doc = row["java"]
        content = source["content"].decode("utf-8")
        if (doc.get("status") != "ready" or doc.get("revision") != 1
                or doc.get("title") != source["title"] or doc.get("content") != content
                or not isinstance(doc.get("id"), str) or doc["id"] in document_ids
                or not isinstance(doc.get("chunks"), list) or not doc["chunks"]):
            raise ValueError("document_source_mismatch")
        document_ids.add(doc["id"])
        for chunk in doc["chunks"]:
            start, end = chunk.get("start_offset"), chunk.get("end_offset")
            chunk_id = chunk.get("id")
            if (not isinstance(chunk_id, str) or chunk_id in chunks
                    or type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(content)
                    or content[start:end] != chunk.get("text")
                    or type(chunk.get("ordinal")) is not int):
                raise ValueError("chunk_source_mismatch")
            chunks[chunk_id] = {"document_id": doc["id"], "revision": doc["revision"],
                "title": doc["title"], "chunk_id": chunk_id, "page": chunk.get("page"),
                "start_offset": start, "end_offset": end, "text": chunk["text"],
                "source_id": source["document_id"], "source_sha256": source["raw_sha256"],
                "source_url": source["immutable_url"], "ordinal": chunk["ordinal"]}
    return chunks


def ranked_evidence(body, payload, chunks):
    if (body.get("query") != payload["query"] or body.get("method") != payload["method"]
            or not isinstance(body.get("results"), list) or len(body["results"]) > 10):
        raise ValueError("search_response_mismatch")
    if payload["method"] != "bm25" and body.get("embedding_profile", {}).get("id") != "base":
        raise ValueError("embedding_profile_mismatch")
    result, seen = [], set()
    for rank, hit in enumerate(body["results"], 1):
        chunk_id = hit.get("chunk_id")
        if chunk_id not in chunks or chunk_id in seen:
            raise ValueError("stale_or_duplicate_chunk")
        source = chunks[chunk_id]
        fields = ("document_id", "revision", "title", "chunk_id", "page", "start_offset", "end_offset", "text")
        if (any(hit.get(key) != source[key] for key in fields)
                or hit.get("document_kind") != "document" or hit.get("meeting_date") is not None
                or type(hit.get("score")) not in (int, float) or not math.isfinite(hit["score"])):
            raise ValueError("retrieved_evidence_mismatch")
        seen.add(chunk_id)
        result.append({**source, "rank": rank, "score": hit["score"]})
    return result


def operations(client, documents, cases, report, deadline):
    """Registration/uploads precede six serial searches within one operations budget."""
    def request(method, url, **kwargs):
        started = time.monotonic()
        response = client.request(method, url, timeout=remaining(deadline), **kwargs)
        remaining(deadline)
        return response, time.monotonic() - started

    report["stage"] = "registration"
    response, _ = request("POST", "/api/auth/register", json={
        "email": "open-retrieval@example.invalid", "password": secrets.token_urlsafe(32),
        "name": "Open retrieval development", "workspace_name": "OpenSearch retrieval"})
    response.raise_for_status()
    workspace = response.json()["workspaces"][0]["id"]
    report["stage"] = "document_uploads"
    for source in documents:
        response, elapsed = request("POST", f"/api/workspaces/{workspace}/documents",
            files={"file": (Path(source["path"]).name, source["content"], "text/markdown")},
            data={"title": source["title"]})
        response.raise_for_status()
        report["documents"].append({"source_id": source["document_id"], "java": response.json(),
                                    "http_elapsed_seconds": elapsed})
    chunks = current_chunks(documents, report["documents"])
    report["uploaded_chunks"] = len(chunks)
    questions = {case["id"]: case["question"] for case in cases}
    for row in report["searches"]:
        try:
            report["stage"] = "search"
            payload = {"query": questions[row["case_id"]], "workspace_id": workspace,
                "method": row["method"], "limit": 10, "expected_embedding_profile": "base"}
            remaining(deadline)  # Do not label a never-issued request as attempted.
            row.update(status="attempted", request=payload)
            report["search_attempts"] += 1
            response, elapsed = request("POST", "/api/knowledge/search", json=payload)
            row.update(http_status=response.status_code, http_elapsed_seconds=elapsed)
            row["response"] = response.json()
            response.raise_for_status()
            row["ranked_evidence"] = ranked_evidence(row["response"], payload, chunks)
            row["status"] = "completed"
        except Exception as error:
            if row["status"] == "attempted":
                row["status"] = "failed"
            record_error(row, error)
            raise  # HTTP failure does not prove the synchronous learned worker has stopped.
    report["stage"] = "searches_completed"


def execute(jar, jar_sha256, output, *, bundle=BUNDLE, launcher=start_services):
    documents, cases = load_bundle(bundle)
    if not jar.is_file() or hashlib.sha256(jar.read_bytes()).hexdigest() != jar_sha256:
        raise ValueError("jar_pin_mismatch")
    report = FailureRecord({"status": "stopped", "stage": "preparation", "limits": LIMITS,
        "development_only": True, "human_reviews": 0, "heldout_evaluation": False,
        "model_quality_accepted": False, "generation_requests": 0, "analysis_requests": 0,
        "search_attempts": 0, "documents": [], "searches": plan(cases),
        "first_failure": None, "secondary_failures": [], "jar_sha256": jar_sha256,
        "source_manifest_sha256": hashlib.sha256((bundle / "manifest.json").read_bytes()).hexdigest(),
        "cases_sha256": hashlib.sha256((bundle / "cases.json").read_bytes()).hexdigest(),
        "retrieval_manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "settings": {"profile": "base", "methods": list(METHODS), "limit": 10,
            "device": "cpu", "worker": "doctrail.inference", "eager_models": ["e5", "reranker"],
            "intraop_threads": 2, "interop_threads": 2, "generation_configuration": "empty"},
        "latency_note": "Fixed serial order shares the existing content-addressed passage LRU. "
            "No warmup or cache reset. HTTP elapsed is not a cold-start method comparison; "
            "Java does not expose worker cache-hit telemetry here.",
        "resource_note": "External fresh serial gate and process resource supervision required. "
            "Phase/HTTP limits are acceptance bounds, not hard preemption."})
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    try:
        report["stage"] = "startup"
        with launcher(jar, output, report, started + 240) as url:
            deadline = min(started + 600, time.monotonic() + 360)
            with httpx.Client(base_url=url, trust_env=False, follow_redirects=False) as client:
                try:
                    operations(client, documents, cases, report, deadline)
                except BaseException as error:
                    record_error(report, error)
                    raise
    except Exception as error:  # noqa: BLE001 - retain safe first failure before cleanup errors
        record_error(report, error)
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        report["unattempted"] = [{"case_id": r["case_id"], "method": r["method"]}
                                 for r in report["searches"] if r["status"] == "unattempted"]
        if report["elapsed_seconds"] > 605:
            record_error(report, TimeoutError())
        if report["first_failure"] is None and all(r["status"] == "completed" for r in report["searches"]):
            report["status"] = "completed_retrieval_observation"
        try:
            (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2,
                allow_nan=False) + "\n", encoding="utf-8")
        except Exception as error:  # noqa: BLE001 - keep first failure in returned report
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
    return 0 if result["status"] == "completed_retrieval_observation" else 1


if __name__ == "__main__":
    raise SystemExit(main())
