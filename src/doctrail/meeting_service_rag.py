"""Opt-in service composition; frozen answer and extraction policies are imported."""
from __future__ import annotations

import copy
import re
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError

from doctrail.generation_runtime import GenerationError
from doctrail.inference import BoundaryMiddleware, WorkerError, _error, _validate_token
from doctrail.meeting_analysis_batch import (
    POLICIES,
    BatchedAnalysisGenerator,
    classification_metadata,
)
from doctrail.meeting_answer_v2 import response_language
from doctrail.meeting_contract import AnalyzeRequest, AnswerRequest
from doctrail.meeting_qwen35 import Qwen35Generator
from doctrail.meeting_runtime import DEADLINE_SECONDS as EXTRACTION_SECONDS
from doctrail.meeting_thinking_quality import QualityThinkingGenerator
from doctrail.meeting_worker import MeetingRuntime

BUDGET_HEADER = "X-DocTrail-Request-Budget-Ms"
PROTOCOL = "meeting-service-rag-v1"


def _observe(observer, operation, event, value):
    if observer is not None:
        try:
            observer(operation, event, copy.deepcopy(value))
        except Exception:  # noqa: BLE001 - evidence failure must abort before further native work
            raise GenerationError("generation_evidence_failed") from None


class ObservedAnalysisGenerator(Qwen35Generator):
    """Delegate the unchanged extraction policy; archive parsed JSON only."""

    def __init__(self, *args, observer=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.observer = observer
        self.observing = False
        self.service_deadline = None
        self._observed_path = None
        self._observed_status = None
        self._client.event_hooks["request"].append(self._sent)
        self._client.event_hooks["response"].append(self._status)

    def _remaining(self, deadline=None):
        if self.service_deadline is not None:
            deadline = min(deadline or self.service_deadline, self.service_deadline)
        return super()._remaining(deadline)

    def begin_request(self, deadline):
        super().begin_request(min(deadline, self.service_deadline)
                              if self.service_deadline is not None else deadline)

    def _emit(self, event, value, deadline=None):
        if self.observing:
            self._remaining(deadline)
            _observe(self.observer, "analyze", event, value)
            self._remaining(deadline)

    def _sent(self, request):
        if self.observing and request.method == "POST":
            self._emit("transport_started", {"path": request.url.path})
            remaining = self._remaining()
            request.extensions["timeout"] = {
                key: min(value, remaining) if value is not None else remaining
                for key, value in request.extensions.get("timeout", {}).items()}

    def _status(self, response):
        self._observed_status = response.status_code
        self._emit("http_status", {"path": self._observed_path, "status": response.status_code})

    def _request(self, method, path, payload=None, deadline=None):
        self._observed_path, self._observed_status = path, None
        self._emit("transport_request", {"method": method, "path": path, "payload": payload},
                   deadline)
        parsed_available = False
        try:
            result = super()._request(method, path, payload, deadline)
            parsed_available = True
            self._emit("transport_response", {"path": path, "parsed_json": result}, deadline)
            return result
        except GenerationError as error:
            _observe(self.observer if self.observing else None, "analyze", "transport_error",
                     {"code": error.code, "path": path, "status": self._observed_status,
                      "body_available": parsed_available, "parsed_json_available": parsed_available,
                      "archive_failed": error.code == "generation_evidence_failed"})
            raise

    def classify_bounded(self, prompts, deadline):
        self._emit("classification_units", len(prompts), deadline)
        result = super().classify_bounded(prompts, deadline)
        self._remaining(deadline)
        return result


class ObservedBatchedAnalysisGenerator(ObservedAnalysisGenerator, BatchedAnalysisGenerator):
    """Observer hooks wrap the same batch algorithm as the unobserved service."""


class ServiceAnswerGenerator(QualityThinkingGenerator):
    """Clamp every inherited deadline without copying the frozen answer algorithm."""

    service_deadline = None

    def _remaining(self, deadline=None):
        if self.service_deadline is not None:
            deadline = min(deadline or self.service_deadline, self.service_deadline)
        return super()._remaining(deadline)

    def begin_request(self, deadline):
        super().begin_request(min(deadline, self.service_deadline)
                              if self.service_deadline is not None else deadline)


class ServiceRuntime:
    def __init__(self, answer_generator, analysis_generator, *, cleanup, observer=None):
        if not callable(cleanup):
            raise TypeError("owned_cleanup_required")
        self.answer_generator = answer_generator
        self.observer = observer
        self.analysis = MeetingRuntime(analysis_generator)
        self.analysis_policy = "batch-v1" if isinstance(
            analysis_generator, BatchedAnalysisGenerator) else "single"
        answer = answer_generator.public_metadata()
        if (answer.get("repo_id"), answer.get("revision")) != (
                self.analysis.model, self.analysis.revision):
            raise GenerationError("generation_identity_mismatch")
        self.model, self.revision = self.analysis.model, self.analysis.revision
        self.lock = threading.Lock()
        self.cleanup = cleanup
        self._cleanup_lock = threading.Lock()
        self._poisoned = False
        self._cleanup_ok = None
        self._closed = False

    def _stop(self):
        # Repeated shutdown and watchdog callbacks must preserve the first outcome.
        with self._cleanup_lock:
            self._poisoned = True
            if self._cleanup_ok is None:
                try:
                    self._cleanup_ok = self.cleanup() is True
                except Exception:  # noqa: BLE001 - never expose process/input details
                    self._cleanup_ok = False
            return self._cleanup_ok

    def _ready(self):
        if self._poisoned or self._closed:
            raise WorkerError("generation_failed", 503)

    def health(self):
        self._ready()
        return {"schema_version": 1, "status": "ready", "experimental": True,
                "model": self.model, "revision": self.revision, "protocol": PROTOCOL,
                "answer": self.answer_generator.public_metadata(),
                "extraction": {**self.analysis.health(),
                               "classification": classification_metadata(self.analysis_policy)}}

    def analyze(self, request):
        if not self.lock.acquire(blocking=False):
            raise WorkerError("model_busy", 503)
        timer = None
        try:
            self._ready()
            # Outer admission remains held after the unchanged extraction runtime
            # releases its own lock, until watchdog cancellation/join completes.
            timer = threading.Timer(EXTRACTION_SECONDS, self._stop)
            timer.daemon = True
            timer.start()
            started = time.monotonic()
            deadline = started + EXTRACTION_SECONDS
            if self.observer is not None or self.analysis_policy == "batch-v1":
                self.analysis.generator.service_deadline = deadline
            _observe(self.observer, "analyze", "started", request.model_dump(mode="json"))
            self._ready()
            if time.monotonic() >= deadline:
                raise WorkerError("generation_deadline_exceeded", 504)
            if self.observer is not None:
                self.analysis.generator.observing = True
            result = self.analysis.analyze(request)
            self._ready()
            if time.monotonic() >= deadline:
                raise WorkerError("generation_deadline_exceeded", 504)
            _observe(self.observer, "analyze", "result", result)
            if time.monotonic() - started >= EXTRACTION_SECONDS:
                raise WorkerError("generation_deadline_exceeded", 504)
        except WorkerError as error:
            try:
                _observe(self.observer, "analyze", "error", {"code": error.code})
            except GenerationError:
                self._stop()
                raise WorkerError("generation_failed", 503) from None
            if (error.code in {"generation_deadline_exceeded", "generation_failed"}
                    and not self._stop()):
                raise WorkerError("generation_cleanup_failed", 503) from None
            raise
        except Exception:  # noqa: BLE001 - archive failures are not extraction success
            self._stop()
            raise WorkerError("generation_failed", 503) from None
        finally:
            if self.observer is not None:
                self.analysis.generator.observing = False
            if self.observer is not None or self.analysis_policy == "batch-v1":
                self.analysis.generator.service_deadline = None
            if timer is not None:
                timer.cancel()
                timer.join()
            self.lock.release()
        if self._poisoned:
            raise WorkerError("generation_deadline_exceeded" if self._cleanup_ok
                              else "generation_cleanup_failed", 504 if self._cleanup_ok else 503)
        return result

    def answer(self, request, deadline, *, budget_ms=None):
        if not self.lock.acquire(blocking=False):
            raise WorkerError("model_busy", 503)
        timer = None
        try:
            self._ready()
            remaining = min(90, deadline - time.monotonic())
            if remaining <= 0:
                raise WorkerError("generation_deadline_exceeded", 504)
            deadline = min(deadline, time.monotonic() + remaining)
            self.answer_generator.service_deadline = deadline
            timer = threading.Timer(remaining, self._stop)
            timer.daemon = True
            timer.start()
            _observe(self.observer, "answer", "started",
                     {"request": request.model_dump(mode="json"), "budget_ms": budget_ms})
            options = {} if self.observer is None else {
                "observe": lambda event, value: _observe(self.observer, "answer", event, value)}
            result = self.answer_generator.answer(request, response_language(request.query),
                                                  **options)
            if time.monotonic() >= deadline or self._poisoned:
                raise GenerationError("generation_deadline_exceeded")
            response = {"schema_version": 1, "model": self.model, "revision": self.revision,
                        **result.answer}
            _observe(self.observer, "answer", "worker_response", response)
            if time.monotonic() >= deadline:
                raise GenerationError("generation_deadline_exceeded")
        except (GenerationError, WorkerError) as error:
            code = error.code
            try:
                _observe(self.observer, "answer", "error", {"code": code})
            except GenerationError:
                code = "generation_evidence_failed"
            if (isinstance(error, GenerationError)
                    and code not in {"generation_input_limit", "model_busy"}
                    and not self._stop()):
                raise WorkerError("generation_cleanup_failed", 503) from None
            if code == "generation_deadline_exceeded":
                raise WorkerError(code, 504) from None
            if code in {"generation_input_limit", "generation_block_limit",
                        "generation_span_limit"}:
                raise WorkerError("context_budget_exceeded", 422) from None
            if code in {"invalid_request", "model_busy"}:
                raise WorkerError(code, 422 if code == "invalid_request" else 503) from None
            raise WorkerError("generation_failed", 503) from None
        except Exception:  # noqa: BLE001 - raw model/errors are never HTTP content
            if not self._stop():
                raise WorkerError("generation_cleanup_failed", 503) from None
            raise WorkerError("generation_failed", 503) from None
        finally:
            if timer is not None:
                timer.cancel()
                timer.join()  # hold native admission until watchdog cleanup has returned
            self.answer_generator.service_deadline = None
            self.lock.release()
        if self._poisoned:
            raise WorkerError("generation_deadline_exceeded" if self._cleanup_ok
                              else "generation_cleanup_failed", 504 if self._cleanup_ok else 503)
        return response

    def close(self):
        if self._closed:
            if self._cleanup_ok is False:
                raise WorkerError("generation_cleanup_failed", 503)
            return
        self._closed = True
        stopped = self._stop()
        # Uvicorn lifespan shutdown follows outstanding handlers; do not close
        # clients while an owned native request is still being processed.
        with self.lock:
            try:
                self.answer_generator.close()
            finally:
                self.analysis.close()
        if not stopped:
            raise WorkerError("generation_cleanup_failed", 503)


class IngressClock:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope.setdefault("state", {})["rag_started"] = time.monotonic()
        await self.app(scope, receive, send)


def create_app(token, runtime_factory):
    _validate_token(token)

    @asynccontextmanager
    async def lifespan(app):
        app.state.runtime = runtime_factory()
        try:
            yield
        finally:
            app.state.runtime.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(BoundaryMiddleware, token=token)
    app.add_middleware(IngressClock)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return _error("invalid_request", 422, request.state.request_id)

    @app.exception_handler(WorkerError)
    async def failed(request, exc):
        return _error(exc.code, exc.status, request.state.request_id)

    @app.get("/health")
    def health(request: Request):
        return request.app.state.runtime.health()

    @app.post("/analyze")
    def analyze(payload: AnalyzeRequest, request: Request):
        return request.app.state.runtime.analyze(payload)

    @app.post("/answer")
    def answer(payload: AnswerRequest, request: Request):
        values = request.headers.getlist(BUDGET_HEADER)
        if (len(values) != 1 or not re.fullmatch(r"[1-9][0-9]{0,4}", values[0])
                or int(values[0]) > 90000):
            raise WorkerError("invalid_request", 422)
        deadline = request.state.rag_started + int(values[0]) / 1000
        runtime = request.app.state.runtime
        options = {"budget_ms": int(values[0])} if getattr(runtime, "observer", None) else {}
        return runtime.answer(payload, deadline, **options)

    return app


def load_runtime(native, *, cleanup, startup_deadline, observer=None, analysis_policy="single"):
    """Both clients verify the same already launched pinned local artifact."""
    if analysis_policy not in POLICIES:
        raise ValueError("invalid_analysis_policy")
    answer = ServiceAnswerGenerator(native.url, native.token, native.manifest)
    plain, observed = ((Qwen35Generator, ObservedAnalysisGenerator) if analysis_policy == "single"
                       else (BatchedAnalysisGenerator, ObservedBatchedAnalysisGenerator))
    options = {} if observer is None else {"observer": observer}
    analysis = (plain if observer is None else observed)(native.url, native.token, native.manifest,
                                                       **options)
    answer.service_deadline = startup_deadline
    try:
        answer.begin_request(startup_deadline)
        analysis.begin_request(startup_deadline)
        answer.load()
        analysis.load()
        return ServiceRuntime(answer, analysis, cleanup=cleanup, observer=observer)
    except Exception:
        answer.close()
        analysis.close()
        raise
    finally:
        answer.end_request()
        analysis.end_request()
        answer.service_deadline = None
