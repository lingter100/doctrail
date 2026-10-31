"""HTTP-only OPEN development: full analysis/QA or explicit two-question QA-only.

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
from doctrail.meeting_structured import (
    EVIDENCE_PLAN_QA_CONTRACTS,
    LEGACY_QA_CONTRACT,
    PROFILE,
    QA_CONTRACTS,
    STRUCTURED_PROFILES,
)
from scripts.run_meeting_qa_service_development import (
    BUNDLE,
    FailureRecord,
    load_bundle,
    record_error,
)
from scripts.serve_meetings_structured import (
    AGENDA_ANALYSIS_CONTRACT,
    ANALYSIS_CONTRACTS,
    LEGACY_ANALYSIS_CONTRACT,
    start_services,
)
from scripts.serve_models import unused_port

EVIDENCE_PLAN_QA_CONTRACT = EVIDENCE_PLAN_QA_CONTRACTS[0]  # Preserve the existing verifier export.

LIMITS = {"startup_seconds": 120, "active_seconds": 590, "setup_seconds": 30,
          "meeting_seconds": 160, "answer_seconds": 120, "cleanup_seconds": 5,
          "whole_seconds": 715, "external_whole_seconds": 750,
          "auto_analyses": 2, "answer_requests": 2, "classification_units_per_meeting": 160,
          "native_completion_ceiling": 326, "requested_output_token_ceiling": 4608,
          "classification_input_tokens": 4096, "structured_input_tokens": 6144,
          "context_tokens": 8192, "classification_output_tokens": 4,
          "summary_output_tokens": 768, "review_output_tokens": 128, "answer_output_tokens": 768}
QA_ONLY_LIMITS = {**LIMITS, "active_seconds": 270, "whole_seconds": 395, "external_whole_seconds": 430,
                  "auto_analyses": 0, "native_completion_ceiling": 2, "requested_output_token_ceiling": 1536}
EVIDENCE_PLAN_LIMITS = {**QA_ONLY_LIMITS, "native_completion_ceiling": 4,
                       "plan_output_tokens": 192, "ledger_output_tokens": 576}
ANALYSIS_ONLY_LIMITS = {**LIMITS, "active_seconds": 350, "whole_seconds": 475, "external_whole_seconds": 510,
                        "answer_requests": 0, "native_completion_ceiling": 2, "requested_output_token_ceiling": 1536,
                        "classification_units_per_meeting": 0, "classification_output_tokens": 0,
                        "review_output_tokens": 0, "answer_output_tokens": 0, "joint_analysis_output_tokens": 768}
NUMERIC = {"input_tokens", "output_tokens", "output_cap", "input_cap", "completion_calls",
           "label_count", "elapsed_seconds", "elapsed_ms", "http_status", "observed_tokens_predicted",
           "observed_tokens_evaluated", "native_calls_budget"}
BOOLEAN = {"dispatched", "returned", "accepted", "review_performed", "semantic_quality_accepted"}
# Literal codes raised by the structured/GGUF worker and its source-contract helpers.
# Never accept an arbitrary generation_* suffix: it can contain private text.
SAFE_ERROR_CODES = {
    "model_busy", "generation_failed", "generation_backend_protocol", "generation_backend_url",
    "generation_backend_token", "generation_backend_unavailable", "generation_backend_response_limit",
    "generation_deadline_exceeded", "generation_input_limit", "generation_identity_mismatch",
    "generation_not_ready", "generation_effective_config_mismatch", "generation_invalid_label",
    "generation_output_truncated", "generation_invalid_schema", "generation_invalid_json",
    "generation_invalid_evidence", "generation_language_mismatch", "generation_summary_insufficient",
    "generation_summary_review_rejected", "generation_conflicting_metadata", "generation_partition_limit",
    "generation_metadata_limit", "generation_item_limit", "generation_empty_summary",
    "generation_duplicate_item", "generation_unsupported_field", "generation_worker_already_running",
}
CONTENT_FAILURE_CODES = {
    "generation_summary_review_rejected", "generation_summary_insufficient", "generation_language_mismatch",
    "generation_invalid_evidence", "generation_invalid_schema", "generation_conflicting_metadata",
    "generation_empty_summary",
}
METADATA_FIELDS = {"meeting_title", "meeting_date", "participants", "purpose"}
METADATA_REASONS = {"unsupported_source_format", "ambiguous_source_value", "value_out_of_bounds"}
ENUMS = {"operation": {"qa", "summary", "summary_review", "meeting_qa", "meeting_summary",
                       "meeting_summary_review", "grammar_constrained_classification",
                       "qa_obligation_plan", "qa_evidence_ledger", "agenda_extraction"},
         "status": {"failed", "complete"}, "finish_reason": {"eos", "length"},
         "stage": {"request", "partition", "classification", "metadata", "summary", "review", "assembled", "qa",
                   "qa_obligation_plan", "qa_evidence_ledger", "agenda_extraction", "agenda_assembly"},
         "validation_stage": {"input", "http", "native_metadata", "effective_settings",
                              "token_identity_integrity", "eos", "json", "accepted"},
         "observed_stop_type": {"eos", "limit", "word", "other"},
         "failure_code": SAFE_ERROR_CODES, "error_code": SAFE_ERROR_CODES,
         "metadata_policy": {"literal_optional_v1"}, "analysis_mode": {"agenda_extraction_v1"},
         "item_field_policy": {"terminal_task_and_enclosing_action_owner_v1"}}


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
        elif key == "metadata_warnings" and isinstance(item, list):
            out[key] = [{field: row[field] for field in ("field", "unit_index", "reason")}
                        for row in item[:160] if isinstance(row, dict)
                        and isinstance(row.get("field"), str) and row["field"] in METADATA_FIELDS
                        and type(row.get("unit_index")) is int and 0 <= row["unit_index"] <= 159
                        and isinstance(row.get("reason"), str) and row["reason"] in METADATA_REASONS]
        elif key == "item_ranges_including_intervening_units" and isinstance(item, list):
            out[key] = [{field: row[field] for field in ("item_index", "first_unit", "last_unit")}
                        for row in item[:150] if isinstance(row, dict)
                        and all(type(row.get(field)) is int for field in ("item_index", "first_unit", "last_unit"))
                        and 0 <= row["item_index"] < 150 and 0 <= row["first_unit"] <= row["last_unit"] < 160]
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


def content_failure_completed(services, observation, row, error):
    """Positive completion evidence only; never relax any transport or integrity check."""
    if not isinstance(error, DevelopmentError):
        return False
    if row["kind"] == "analysis":
        if error.code != "generation_development_analysis_failed" or row.get("analysis_status") != "failed":
            return False
    elif error.code != "generation_development_http_failed" or row.get("last_http_status") not in {502, 503}:
        return False
    receipt = observation.get("runtime")
    if (observation.get("runtime_state") != "terminal" or not isinstance(receipt, dict)
            or receipt.get("status") != "failed" or receipt.get("failure_code") not in CONTENT_FAILURE_CODES):
        return False
    if receipt.get("stage") in {"qa_obligation_plan", "qa_evidence_ledger"}:
        return False  # Malformed plan/ledger stages are technical failures, never continuable content errors.
    if receipt.get("stage") == "agenda_assembly" and receipt.get("failure_code") not in {
            "generation_summary_insufficient", "generation_language_mismatch"}:
        return False  # Only completed content outcomes, not malformed item/span contracts, may continue.
    try:
        if services["runtime"].lock.locked() is not False:
            return False
    except Exception:  # noqa: BLE001 - unreadable idle state must remain fail-closed
        return False
    call = observation.get("structured_call")
    if (observation.get("structured_call_fresh") is True and isinstance(call, dict)
            and all(call.get(key) is True for key in ("dispatched", "returned", "accepted"))
            and call.get("finish_reason") == "eos" and call.get("validation_stage") == "accepted"):
        return True
    # This aggregate exists only after every bounded classification has returned.
    if receipt.get("stage") != "metadata" or services["generator"].last_call is not None:
        return False
    classification = [item for item in receipt.get("calls", [])
                      if item.get("operation") == "grammar_constrained_classification"]
    return (len(classification) == 1
            and type(classification[0].get("completion_calls")) is int
            and 1 <= classification[0]["completion_calls"] <= LIMITS["classification_units_per_meeting"]
            and all(type(classification[0].get(key)) is int and classification[0][key] > 0
                    for key in ("input_tokens", "output_tokens")))


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


def operation_rows(documents, cases, *, qa_only=False, analysis_only=False):
    return ([{"kind": "analysis", "id": doc["document_id"], "state": "unattempted"}
             for doc in documents if doc["role"] == "meeting" and not qa_only]
            + [{"kind": "answer", "id": case["id"], "state": "unattempted"} for case in cases if not analysis_only])


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
        self.development_runtime = None
        self.development_pending = []
        self.development_bytes = 0
        self.client.event_hooks["response"] = [*self.previous, self.hook]

    def restore(self):
        with self.lock:
            self.closed = True
            self.client.event_hooks["response"] = self.previous
            for row in self.rows:
                if row["state"] == "pending":
                    row["state"] = "unavailable"
        if self.development_runtime is not None:
            self.development_runtime.set_development_capture(None)

    def bind_development(self, runtime):
        self.development_runtime = runtime
        self.report["development_artifacts"] = []
        self.report["development_capture_note"] = "Prepared requests/intermediates are not independent proof of dispatch or semantic acceptance."
        runtime.set_development_capture(self.development_event)

    def development_event(self, event):
        """Explicit development callback: no production logging and no worker I/O."""
        if self.closed:
            return
        try:
            kind = event.get("kind")
            shapes = {"native_request": {"kind", "stage", "body"}, "accepted_plan": {"kind", "plan"},
                      "compiled_ledger": {"kind", "ledger", "result"}}
            if kind not in shapes or set(event) != shapes[kind]:
                raise ValueError("unsupported_development_event")
            stage = event.get("stage", "qa_obligation_plan" if kind == "accepted_plan" else "qa_evidence_ledger")
            if stage not in {"qa_obligation_plan", "qa_evidence_ledger", "agenda_extraction"}:
                raise ValueError("unsupported_development_stage")
            body_hash = None
            if kind == "native_request":
                allowed = {"temperature", "samplers", "seed", "dynatemp_range", "mirostat", "ignore_eos",
                           "stream", "stop", "logit_bias", "grammar_lazy", "lora", "n_predict", "max_tokens",
                           "model", "messages", "cache_prompt", "return_tokens", "verbose", "chat_template_kwargs",
                           "response_format"}
                if not isinstance(event["body"], dict) or set(event["body"]) - allowed:
                    raise ValueError("unsupported_development_body")
                body_hash = hashlib.sha256(json.dumps(event["body"], ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
            raw = json.dumps(event, ensure_ascii=False, allow_nan=False).encode("utf-8")
            with self.lock:
                if self.closed:
                    return
                rows = self.report["development_artifacts"]
                if len(rows) >= 8:
                    self.report["development_capture_overflow"] = True
                    return
                active = [row for row in self.report["operations"] if row["state"] == "attempted"]
                row = {"index": len(rows), "kind": kind, "stage": stage,
                       "operation_id": active[-1]["id"] if len(active) == 1 else None,
                       "state": "unavailable", "bytes": len(raw), "truncated": False}
                rows.append(row)
                if len(raw) > 2 * 1024 * 1024 or self.development_bytes + len(raw) > 8 * 1024 * 1024:
                    row["truncated"] = True
                    return
                self.development_bytes += len(raw)
                row.update(state="buffered", sha256=hashlib.sha256(raw).hexdigest())
                if body_hash is not None:
                    row["request_body_sha256"] = body_hash
                self.development_pending.append((row, raw))
        except Exception:  # noqa: BLE001 - capture cannot replace any generation outcome
            with self.lock:
                if not self.closed:
                    self.report["development_capture_error"] = True

    def flush(self):
        """Called only by the harness main thread, never by HTTP/worker callbacks."""
        with self.lock:
            pending, self.pending = self.pending, []
            development_pending, self.development_pending = self.development_pending, []
        for row, raw in development_pending:
            try:
                (self.output / "development-traces").mkdir(exist_ok=True)
                relative = f"development-traces/{row['index']:03d}-{row['kind']}.json"
                (self.output / relative).write_bytes(raw)
                row.update(state="captured", path=relative)
            except Exception:  # noqa: BLE001 - private trace I/O must not mask model failures
                row.update(state="unavailable", capture_error=True)
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
            if len(self.rows) >= self.report.get("limits", LIMITS)["native_completion_ceiling"]:
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
                   *, qa_only=False, analysis_only=False, continue_content_failures=False, clock=time.monotonic, sleep=time.sleep):
    if qa_only and analysis_only:
        raise DevelopmentError("component_mode_conflict")
    meetings = [doc for doc in documents if doc["role"] == "meeting"]
    general = [doc for doc in documents if doc["role"] == "general_document"]
    if len(meetings) != 2 or len(general) != 1 or len(cases) != 2:
        raise DevelopmentError("bundle_roles")
    rows = report["operations"] = operation_rows(documents, cases, qa_only=qa_only, analysis_only=analysis_only)
    limits = ANALYSIS_ONLY_LIMITS if analysis_only else QA_ONLY_LIMITS if qa_only else LIMITS
    report["documents"] = stored = []
    setup = report["setup"] = {"state": "attempted"}
    setup_end = min(deadline, clock() + limits["setup_seconds"])
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

    setup["document_bindings"] = []
    for source in ([] if analysis_only else [*general, *(meetings if qa_only else [])]):
        doc = upload(source, False, setup_end, setup)
        check_document(doc, source)
        stored.append(doc)
        setup["document_bindings"].append({"source_id": source["document_id"], "document_id": doc["id"],
                                           "registered_as": "ordinary_document"})
    if not analysis_only:
        setup.update(source_id=general[0]["document_id"], document_id=stored[0]["id"])
    setup["state"] = "complete"
    save()
    for source, row in zip(meetings if not qa_only else [], rows[:2] if not qa_only else [], strict=True):
        end = min(deadline, clock() + limits["meeting_seconds"])
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
            observation = observe(services, before)
            if not continue_content_failures or not content_failure_completed(services, observation, row, error):
                raise
            check_document(row["result"]["document"], source)
            stored.append(row["result"]["document"])
            row.update(state="failed", continuation="next_independent_operation_only")
        finally:
            row["observation"] = observe(services, before)
            save()
        if row["state"] == "failed":
            continue
        if row["observation"]["runtime_state"] != "terminal" or row["observation"]["runtime"].get("status") != "complete":
            row["state"] = "failed_or_unknown"
            raise DevelopmentError("analysis_receipt_unknown")
    for case, row in zip([] if analysis_only else cases, rows if qa_only else rows[2:], strict=True):
        end = min(deadline, clock() + limits["answer_seconds"])
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
            if not continue_content_failures or not content_failure_completed(services, observe(services, before), row, error):
                raise
            row.update(state="failed", continuation="next_independent_operation_only")
        finally:
            row["observation"] = observe(services, before)
            save()
        if row["state"] == "failed":
            continue
        if answer.get("model_called") is not False and (row["observation"]["runtime_state"] != "terminal"
                or row["observation"]["runtime"].get("status") != "complete"):
            row["state"] = "failed_or_unknown"
            raise DevelopmentError("answer_receipt_unknown")


def execute(jar, jar_sha256, output, *, profile=PROFILE, qa_contract=LEGACY_QA_CONTRACT, qa_only=False,
            analysis_contract=LEGACY_ANALYSIS_CONTRACT, analysis_only=False,
            continue_content_failures=False, bundle=BUNDLE, launcher=start_services,
            client_factory=httpx.Client, clock=time.monotonic, sleep=time.sleep):
    if profile not in STRUCTURED_PROFILES:
        raise DevelopmentError("unknown_profile")
    if qa_contract not in QA_CONTRACTS:
        raise DevelopmentError("unknown_qa_contract")
    if analysis_contract not in ANALYSIS_CONTRACTS:
        raise DevelopmentError("unknown_analysis_contract")
    if qa_only and analysis_only:
        raise DevelopmentError("component_mode_conflict")
    if analysis_only and (analysis_contract != AGENDA_ANALYSIS_CONTRACT or qa_contract != LEGACY_QA_CONTRACT):
        raise DevelopmentError("analysis_only_contract_conflict")
    if analysis_contract == AGENDA_ANALYSIS_CONTRACT and not analysis_only:
        raise DevelopmentError("agenda_requires_analysis_only")
    if qa_contract in EVIDENCE_PLAN_QA_CONTRACTS and not qa_only:
        raise DevelopmentError("evidence_plan_requires_qa_only")
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
    limits = (ANALYSIS_ONLY_LIMITS if analysis_only else EVIDENCE_PLAN_LIMITS
              if qa_contract in EVIDENCE_PLAN_QA_CONTRACTS else QA_ONLY_LIMITS if qa_only else LIMITS)
    report = FailureRecord(first_failure=None, secondary_failures=[], status="running", limits=limits,
                           semantic_quality_accepted=False, human_reviews=0, heldout_evaluation=False,
                           requested_profile=profile, requested_qa_contract=qa_contract,
                           requested_analysis_contract=analysis_contract,
                           mode="analysis_only" if analysis_only else "qa_only" if qa_only else "full",
                           continue_content_failures=continue_content_failures,
                           jar_sha256=jar_sha256, operations=operation_rows(documents, cases, qa_only=qa_only, analysis_only=analysis_only),
                           external_fresh_gate_required=True)
    if qa_only:
        report["context_comparison"] = {"exact_prior_context_binding_proven": False,
            "limitation": "Fresh ordinary-document uploads preserve source bytes and order, but prior DB/context identity is not reconstructed."}
    selected_sources = [doc for doc in documents if not analysis_only or doc["role"] == "meeting"]
    report["sources"] = [{key: doc[key] for key in ("document_id", "role", "path", "raw_sha256", "title")}
                         for doc in selected_sources]
    for doc in selected_sources:
        (output / (doc["document_id"] + ".txt")).write_bytes(doc["content"])
    report["cases"] = [] if analysis_only else cases
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
                      worker_port=ports[1], native_port=ports[2], enable_structured=True,
                      profile=profile, qa_contract=qa_contract, analysis_contract=analysis_contract, report=report) as services:
            try:
                capture = NativeOutputCapture(services["generator"], output, report)
                if qa_contract in EVIDENCE_PLAN_QA_CONTRACTS or analysis_contract == AGENDA_ANALYSIS_CONTRACT:
                    capture.bind_development(services["runtime"])
                left(started + limits["startup_seconds"], clock)
                active = min(started + limits["whole_seconds"] - limits["cleanup_seconds"],
                             clock() + limits["active_seconds"])
                with client_factory(base_url=services["java_url"], trust_env=False, follow_redirects=False) as client:
                    run_operations(client, services, documents, cases, report, active, save,
                                   qa_only=qa_only, analysis_only=analysis_only,
                                   continue_content_failures=continue_content_failures, clock=clock, sleep=sleep)
                if report.errors:
                    raise report.errors[0]  # Content failures stay failures, also during context cleanup.
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
    parser.add_argument("--profile", choices=STRUCTURED_PROFILES, default=PROFILE)
    parser.add_argument("--qa-contract", choices=QA_CONTRACTS, default=LEGACY_QA_CONTRACT)
    parser.add_argument("--analysis-contract", choices=ANALYSIS_CONTRACTS, default=LEGACY_ANALYSIS_CONTRACT)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--qa-only", action="store_true")
    modes.add_argument("--analysis-only", action="store_true")
    parser.add_argument("--continue-content-failures", action="store_true")
    args = parser.parse_args()
    try:
        report = execute(args.jar, args.jar_sha256, args.output, profile=args.profile,
                         qa_contract=args.qa_contract, qa_only=args.qa_only,
                         analysis_contract=args.analysis_contract, analysis_only=args.analysis_only,
                         continue_content_failures=args.continue_content_failures)
    except Exception:  # noqa: BLE001 - never echo private HTTP or environment details
        parser.exit(1, "structured_development_preflight_failed\n")
    if report["status"] != "completed":
        parser.exit(1, "structured_development_failed\n")


if __name__ == "__main__":
    main()
