"""HTTP-only OPEN development: two auto analyses, then two fixed BM25 answers.

Requires an external fresh process/resource gate. Deadlines here bound HTTP and
acceptance; the external supervisor provides hard whole-process preemption.
All source and response artifacts belong in a fresh private .local directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from doctrail.meeting_grounded_summary import validate_summary_analysis
from scripts.run_meeting_qa_service_development import (
    BUNDLE,
    FailureRecord,
    load_bundle,
    record_error,
)
from scripts.serve_meetings_structured import start_services
from scripts.serve_models import unused_port

LIMITS = {"startup_seconds": 120, "active_seconds": 590, "setup_seconds": 30,
          "meeting_seconds": 160, "answer_seconds": 120, "cleanup_seconds": 5,
          "whole_seconds": 715, "external_whole_seconds": 750,
          "auto_analyses": 2, "answer_requests": 2, "classification_units_per_meeting": 160,
          "native_completion_ceiling": 326, "requested_output_token_ceiling": 4608,
          "classification_input_tokens": 4096, "structured_input_tokens": 6144,
          "context_tokens": 8192, "classification_output_tokens": 4,
          "summary_output_tokens": 768, "review_output_tokens": 128, "answer_output_tokens": 768}
NUMERIC = {"input_tokens", "output_tokens", "output_cap", "input_cap", "completion_calls",
           "label_count", "elapsed_seconds", "elapsed_ms", "http_status", "observed_tokens_predicted",
           "observed_tokens_evaluated"}
BOOLEAN = {"dispatched", "returned", "accepted"}
ENUMS = {"operation": {"qa", "summary", "summary_review", "meeting_qa", "meeting_summary",
                       "meeting_summary_review", "grammar_constrained_classification"},
         "status": {"failed", "complete"}, "finish_reason": {"eos", "length"},
         "stage": {"request", "partition", "classification", "summary", "review", "assembled", "qa"},
         "validation_stage": {"input", "http", "native_metadata", "effective_settings",
                              "token_identity_integrity", "eos", "json", "accepted"},
         "observed_stop_type": {"eos", "limit", "word", "other"}}


class DevelopmentError(RuntimeError):
    def __init__(self, code):
        self.code = "generation_development_" + code
        super().__init__(self.code)


def safe_metrics(value):
    """Allow only measured scalars and known labels, never arbitrary diagnostics."""
    if not isinstance(value, dict):
        return {}
    out = {}
    for key, item in value.items():
        if (key in NUMERIC and type(item) in (int, float)
                or key in BOOLEAN and type(item) is bool
                or key in ENUMS and isinstance(item, str) and item in ENUMS[key]):
            out[key] = item
        elif key == "calls" and isinstance(item, list):
            out[key] = [safe_metrics(row) for row in item[:162]]
        elif key == "last_structured_call":
            out[key] = safe_metrics(item)
    return out


def snapshot(services):
    return services["runtime"].last_telemetry, services["generator"].last_call


def observe(services, before):
    receipt, call = snapshot(services)
    terminal = receipt is not before[0] and isinstance(receipt, dict) and receipt.get("status") in {"complete", "failed"}
    return {"runtime_state": "terminal" if terminal else "unknown_or_inflight",
            "runtime": safe_metrics(receipt) if terminal else None,
            "structured_call": safe_metrics(call) if call is not before[1] else None,
            "structured_call_fresh": call is not before[1]}


def left(deadline, clock):
    seconds = deadline - clock()
    if seconds <= 0:
        raise DevelopmentError("deadline")
    return seconds


def request(client, method, path, deadline, row, clock, **kwargs):
    # A single dispatch. HTTP errors/timeouts are never retried.
    timeout = left(deadline, clock)
    row["http_requests"] = row.get("http_requests", 0) + 1
    response = client.request(method, path, timeout=timeout, **kwargs)
    row["last_http_status"] = response.status_code
    left(deadline, clock)
    if response.status_code >= 400:
        raise DevelopmentError("http_failed")
    return response.json()


def check_document(document, source):
    content = source["content"].decode("utf-8")
    if document.get("content") != content or document.get("revision") != 1 or document.get("status") != "ready":
        raise DevelopmentError("document_binding")
    ids = set()
    for chunk in document["chunks"]:
        start, end = chunk["start_offset"], chunk["end_offset"]
        if not 0 <= start < end <= len(content) or content[start:end] != chunk["text"] or chunk["id"] in ids:
            raise DevelopmentError("chunk_binding")
        ids.add(chunk["id"])


def check_answer(answer, documents):
    if answer.get("status") == "abstained" and answer.get("claims") == []:
        return
    if answer.get("status") != "answered" or not answer.get("claims"):
        raise DevelopmentError("answer_contract")
    chunks = {chunk["id"]: (doc, chunk) for doc in documents for chunk in doc["chunks"]}
    for claim in answer["claims"]:
        if not claim.get("citations"):
            raise DevelopmentError("citation_missing")
        for citation in claim["citations"]:
            pair = chunks.get(citation.get("chunk_id"))
            if pair is None:
                raise DevelopmentError("citation_chunk")
            doc, chunk = pair
            start, end = citation["start_offset"], citation["end_offset"]
            if (citation.get("document_id") != doc["id"] or citation.get("revision") != doc["revision"]
                    or citation.get("page") != chunk.get("page")
                    or not chunk["start_offset"] <= start < end <= chunk["end_offset"]
                    or doc["content"][start:end] != citation["quote"]):
                raise DevelopmentError("citation_binding")


def operation_rows(documents, cases):
    return ([{"kind": "analysis", "id": doc["document_id"], "state": "unattempted"}
             for doc in documents if doc["role"] == "meeting"]
            + [{"kind": "answer", "id": case["id"], "state": "unattempted"} for case in cases])


class NativeOutputCapture:
    """Passive stream tap; only public generated content is persisted privately."""

    def __init__(self, generator, output, report):
        self.client, self.output, self.report = generator._client, output, report
        self.previous = list(self.client.event_hooks["response"])
        self.rows = report["native_output_artifacts"] = []
        self.buffered = 0
        self.per_response = 1024 * 1024
        self.total = 8 * 1024 * 1024
        self.closed = False
        self.lock = threading.Lock()
        self.pending = []
        self.client.event_hooks["response"] = [*self.previous, self.hook]

    def restore(self):
        with self.lock:
            self.closed = True
            self.client.event_hooks["response"] = self.previous
            for row in self.rows:
                if row["state"] == "pending":
                    row["state"] = "unavailable"

    def flush(self):
        """Called only by the harness main thread, never by HTTP/worker callbacks."""
        with self.lock:
            pending, self.pending = self.pending, []
        for row, outputs in pending:
            row["outputs"] = []
            for representation, raw in outputs:
                try:
                    (self.output / "native-outputs").mkdir(exist_ok=True)
                    relative = f"native-outputs/{row['index']:03d}-{representation}.txt"
                    (self.output / relative).write_bytes(raw)
                    artifact = {"representation": representation, "path": relative,
                                "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                    row["outputs"].append(artifact)
                    if "path" not in row:
                        row.update({key: artifact[key] for key in ("path", "bytes", "sha256")})
                    row["state"] = "captured"
                except Exception:  # noqa: BLE001 - retain generation outcome on diagnostic I/O failure
                    row["capture_error"] = True

    def hook(self, response):
        path = response.request.url.path
        if self.closed or response.request.method != "POST" or path not in {"/completion", "/v1/chat/completions"}:
            return
        with self.lock:
            if self.closed:
                return
            if len(self.rows) >= LIMITS["native_completion_ceiling"]:
                self.report["native_capture_call_overflow"] = True
                return
            active = [row for row in self.report["operations"] if row["state"] == "attempted"]
            row = {"index": len(self.rows), "operation_id": active[-1]["id"] if active else None,
                   "route": path, "http_status": response.status_code, "state": "pending", "truncated": False}
            self.rows.append(row)
        owner = self
        original = response.stream

        class Tap(httpx.SyncByteStream):
            def __init__(self):
                self.data = bytearray()
                self.done = False
                self.truncated = False

            def finish(self, complete):
                if self.done:
                    return
                self.done = True
                metadata = {"buffered_response_bytes": len(self.data), "stream_complete": complete,
                            "state": "unavailable", "truncated": self.truncated}
                outputs = []
                try:
                    if owner.closed or not complete or self.truncated:
                        return
                    body = json.loads(self.data)
                    native = body if path == "/completion" else body.get("__verbose", {})
                    metadata["observed"] = {}
                    if isinstance(native, dict):
                        for key in ("tokens_predicted", "tokens_evaluated"):
                            if type(native.get(key)) is int and native[key] >= 0:
                                metadata["observed"][key] = native[key]
                        if native.get("stop_type") in {"eos", "limit", "word"}:
                            metadata["observed"]["stop_type"] = native["stop_type"]
                    if path == "/v1/chat/completions":
                        usage = body.get("usage", {})
                        if isinstance(usage, dict):
                            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                                if type(usage.get(key)) is int and usage[key] >= 0:
                                    metadata["observed"][key] = usage[key]
                    if path == "/completion":
                        texts = [("native", body.get("content"))]
                    else:
                        choices = body.get("choices")
                        message = choices[0].get("message", {}) if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
                        texts = [("message", message.get("content") if isinstance(message, dict) else None),
                                 ("native", native.get("content") if isinstance(native, dict) else None)]
                    outputs = [(name, text.encode("utf-8")) for name, text in texts if isinstance(text, str)]
                except Exception:  # noqa: BLE001 - diagnostics must never replace a generation failure
                    metadata["capture_error"] = True
                finally:
                    self.data.clear()
                    with owner.lock:
                        if not owner.closed:
                            row.update(metadata)
                            if outputs:
                                owner.pending.append((row, outputs))
                                row["state"] = "buffered"

            def __iter__(self):
                complete = False
                try:
                    for chunk in original:
                        capacity = min(owner.per_response - len(self.data), owner.total - owner.buffered)
                        kept = chunk[:max(0, capacity)]
                        self.data.extend(kept)
                        owner.buffered += len(kept)
                        self.truncated |= len(kept) != len(chunk)
                        yield chunk  # unchanged bytes, caller retains original deadline/size checks
                    complete = True
                finally:
                    self.finish(complete)

            def close(self):
                try:
                    original.close()
                finally:
                    self.finish(False)

        response.stream = Tap()


def run_operations(client, services, documents, cases, report, deadline, save,
                   *, clock=time.monotonic, sleep=time.sleep):
    meetings = [doc for doc in documents if doc["role"] == "meeting"]
    general = [doc for doc in documents if doc["role"] == "general_document"]
    if len(meetings) != 2 or len(general) != 1 or len(cases) != 2:
        raise DevelopmentError("bundle_roles")
    rows = report["operations"] = operation_rows(documents, cases)
    report["documents"] = stored = []
    setup = report["setup"] = {"state": "attempted"}
    setup_end = min(deadline, clock() + LIMITS["setup_seconds"])
    auth = request(client, "POST", "/api/auth/register", setup_end, setup, clock, json={
        "email": f"open-development-{secrets.token_hex(10)}@example.invalid",
        "password": secrets.token_urlsafe(32), "name": "OPEN development", "workspace_name": "OPEN development"})
    workspace = auth["workspaces"][0]["id"]
    report["workspace_id"] = workspace

    def upload(source, meeting, end, row):
        endpoint = "meetings" if meeting else "documents"
        return request(client, "POST", f"/api/workspaces/{workspace}/{endpoint}", end, row, clock,
                       files={"file": (Path(source["path"]).name, source["content"], "text/markdown")},
                       data={"title": source["title"], "visibility": "workspace"})

    doc = upload(general[0], False, setup_end, setup)
    check_document(doc, general[0])
    stored.append(doc)
    setup.update(source_id=general[0]["document_id"], document_id=doc["id"])
    setup["state"] = "complete"
    save()
    for source, row in zip(meetings, rows[:2], strict=True):
        end = min(deadline, clock() + LIMITS["meeting_seconds"])
        left(end, clock)
        before = snapshot(services)
        row.update(state="attempted", before=safe_metrics(before[0]), before_structured=safe_metrics(before[1]))
        try:
            detail = upload(source, True, end, row)
            while True:
                row["result"] = detail
                state = detail["meeting"]["analysis_status"]
                row["analysis_status"] = state
                if state == "ready":
                    check_document(detail["document"], source)
                    if detail["meeting"]["source_revision"] != detail["document"]["revision"]:
                        raise DevelopmentError("analysis_revision")
                    validate_summary_analysis(detail["meeting"]["ai_analysis"], detail["document"]["content"])
                    stored.append(detail["document"])
                    break
                if state not in {"queued", "running"}:
                    raise DevelopmentError("analysis_failed")
                sleep(min(0.2, left(end, clock)))
                detail = request(client, "GET", f"/api/meetings/{detail['document']['id']}", end, row, clock)
            row["state"] = "complete"
        except BaseException as error:
            row["state"] = "failed_or_unknown"
            record_error(report, error)
            raise
        finally:
            row["observation"] = observe(services, before)
            save()
        if row["observation"]["runtime_state"] != "terminal" or row["observation"]["runtime"].get("status") != "complete":
            row["state"] = "failed_or_unknown"
            raise DevelopmentError("analysis_receipt_unknown")
    for case, row in zip(cases, rows[2:], strict=True):
        end = min(deadline, clock() + LIMITS["answer_seconds"])
        left(end, clock)
        before = snapshot(services)
        row.update(state="attempted", before=safe_metrics(before[0]), before_structured=safe_metrics(before[1]))
        try:
            answer = request(client, "POST", "/api/knowledge/answer", end, row, clock,
                             json={"workspace_id": workspace, "query": case["question"], "method": "bm25", "limit": 10})
            row["result"] = answer
            check_answer(answer, stored)
            row["state"] = "complete"
        except BaseException as error:
            row["state"] = "failed_or_unknown"
            record_error(report, error)
            raise
        finally:
            row["observation"] = observe(services, before)
            save()
        if answer.get("model_called") is not False and (row["observation"]["runtime_state"] != "terminal"
                or row["observation"]["runtime"].get("status") != "complete"):
            row["state"] = "failed_or_unknown"
            raise DevelopmentError("answer_receipt_unknown")


def execute(jar, jar_sha256, output, *, bundle=BUNDLE, launcher=start_services,
            client_factory=httpx.Client, clock=time.monotonic, sleep=time.sleep):
    jar, output = Path(jar), Path(output)
    # No output or model/service side effects until immutable inputs pass.
    if output.exists() or not output.resolve().is_relative_to((ROOT / ".local").resolve()):
        raise DevelopmentError("fresh_private_output_required")
    if hashlib.sha256(jar.read_bytes()).hexdigest() != jar_sha256:
        raise DevelopmentError("jar_hash")
    documents, cases = load_bundle(bundle)
    if ([doc["role"] for doc in documents].count("meeting") != 2
            or [doc["role"] for doc in documents].count("general_document") != 1 or len(cases) != 2):
        raise DevelopmentError("bundle_roles")
    output.mkdir(parents=True)
    report = FailureRecord(first_failure=None, secondary_failures=[], status="running", limits=LIMITS,
                           semantic_quality_accepted=False, human_reviews=0, heldout_evaluation=False,
                           jar_sha256=jar_sha256, operations=operation_rows(documents, cases),
                           external_fresh_gate_required=True)
    report["sources"] = [{key: doc[key] for key in ("document_id", "role", "path", "raw_sha256", "title")}
                         for doc in documents]
    for doc in documents:
        (output / (doc["document_id"] + ".txt")).write_bytes(doc["content"])
    report["cases"] = cases
    started = clock()
    capture = None

    def save():
        if capture is not None:
            capture.flush()
            with capture.lock:
                serialized = json.dumps(report, ensure_ascii=False, indent=2)
        else:
            serialized = json.dumps(report, ensure_ascii=False, indent=2)
        (output / "result.json").write_text(serialized + "\n", encoding="utf-8")

    try:
        ports = [unused_port() for _ in range(3)]
        if len(set(ports)) != 3:
            raise DevelopmentError("ports")
        with launcher(jar=jar, database=output / "development.sqlite3", java_port=ports[0],
                      worker_port=ports[1], native_port=ports[2], enable_structured=True, report=report) as services:
            try:
                capture = NativeOutputCapture(services["generator"], output, report)
                left(started + LIMITS["startup_seconds"], clock)
                active = min(started + LIMITS["whole_seconds"] - LIMITS["cleanup_seconds"],
                             clock() + LIMITS["active_seconds"])
                with client_factory(base_url=services["java_url"], trust_env=False, follow_redirects=False) as client:
                    run_operations(client, services, documents, cases, report, active, save, clock=clock, sleep=sleep)
            except BaseException as error:
                record_error(report, error)  # Preserve first failure before context unwinding.
                raise
        report["status"] = "completed"
    except BaseException as error:  # noqa: BLE001 - persist safe failure after owned cleanup
        record_error(report, error)
        report["status"] = "failed"
    finally:
        if capture is not None:
            try:
                capture.restore()  # after service cleanup; no writes from a detached drain
            except Exception as error:  # noqa: BLE001 - retain original failure on diagnostic cleanup
                record_error(report, error)
                report["status"] = "failed"
        report["elapsed_seconds"] = clock() - started
        report["attempted"] = {kind: sum(row["kind"] == kind and row["state"] != "unattempted"
                                        for row in report["operations"]) for kind in ("analysis", "answer")}
        report["native_counts"] = ("Fresh terminal aggregate and observed per-response counters are recorded separately; "
                                   "interrupted or unobserved completions remain unknown.")
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, required=True)
    parser.add_argument("--jar-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = execute(args.jar, args.jar_sha256, args.output)
    except Exception:  # noqa: BLE001 - never echo private HTTP or environment details
        parser.exit(1, "structured_development_preflight_failed\n")
    if report["status"] != "completed":
        parser.exit(1, "structured_development_failed\n")


if __name__ == "__main__":
    main()
