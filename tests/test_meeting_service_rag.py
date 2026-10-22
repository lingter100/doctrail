"""Service contracts with synthetic native HTTP only; no model/tokenizer execution."""
import copy
import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_contract import AnalyzeRequest, AnswerRequest
from doctrail.meeting_gguf import GREEDY
from doctrail.meeting_qwen35 import NONTHINKING_PREAMBLE, Qwen35Generator
from doctrail.meeting_runtime import DEADLINE_SECONDS as EXTRACTION_SECONDS
from doctrail.meeting_service_rag import (
    BUDGET_HEADER,
    ObservedBatchedAnalysisGenerator,
    ObservedScopedBatchedAnalysisGenerator,
    ServiceAnswerGenerator,
    ServiceRuntime,
    create_app,
)
from doctrail.meeting_thinking_transport import GGUF_SHA256, PREAMBLE, SETTINGS

TOKEN = "s" * 40
TEXT = "The beacon is amber."
CONTENT = '{"status":"answered","claims":[{"text":"The beacon is amber.","evidence_ids":[0]}]}'
PROMPT = "synthetic service request\n" + PREAMBLE
PAYLOAD = {"schema_version": 1, "query": "What color is the beacon?", "contexts": [{
    "document_id": "service-synthetic", "revision": 1, "chunk_id": "synthetic-0",
    "title": "Synthetic beacon", "meeting_date": None, "page": None,
    "start_offset": 0, "end_offset": len(TEXT), "text": TEXT}]}
ANALYZE = {"schema_version": 1, "document_id": "service-synthetic", "revision": 1,
           "title": "Synthetic beacon", "content": TEXT}
METADATA = {"repo_id": "Qwen/Qwen3.5-9B", "revision": "gguf-sha256:" + GGUF_SHA256}


def native_answer(content=CONTENT):
    return {"object": "chat.completion", "model": GGUF_SHA256,
        "system_fingerprint": "b11429-d81235049",
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant",
            "content": content, "reasoning_content": "Private synthetic reasoning."}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18,
                  "prompt_tokens_details": {"cached_tokens": 0}},
        "__verbose": {"model": GGUF_SHA256, "prompt": PROMPT,
            "content": "Private synthetic reasoning.</think>" + content,
            "tokens": list(range(8)), "tokens_predicted": 8, "tokens_evaluated": 10,
            "stop": True, "truncated": False, "stop_type": "eos",
            "generation_settings": {**copy.deepcopy(SETTINGS), "stop": [], "grammar": "root"},
            "timings": {"prompt_n": 10, "predicted_n": 8, "cache_n": 0}}}


def runtime(seen, *, override=None, cleanup=None):
    def handler(request):
        body = json.loads(request.content)
        seen.append((request.url.path, body, request.extensions.get("timeout")))
        if override:
            replacement = override(request, body)
            if replacement is not None:
                return replacement
        if request.url.path == "/apply-template":
            thinking = body["chat_template_kwargs"]["enable_thinking"]
            return httpx.Response(200, json={"prompt": PROMPT if thinking else
                "synthetic extraction\n" + NONTHINKING_PREAMBLE})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": list(range(10))})
        if request.url.path == "/completion":
            return httpx.Response(200, json={
                "generation_settings": {k: body[k] for k in (*GREEDY, "n_predict", "grammar")},
                "model": GGUF_SHA256, "truncated": False, "stop": True, "stop_type": "eos",
                "timings": {"cache_n": 0, "prompt_n": 10},
                "tokens_evaluated": 10, "tokens_predicted": 2, "content": "5"})
        return httpx.Response(200, json=native_answer())
    generators = []
    for cls in (ServiceAnswerGenerator, Qwen35Generator):
        generator = cls("http://127.0.0.1:8123", TOKEN, "synthetic-unused",
                        transport=httpx.MockTransport(handler))
        generator._alias = GGUF_SHA256
        generator._metadata = copy.deepcopy(METADATA)  # explicit synthetic readiness
        generators.append(generator)
    return ServiceRuntime(*generators, cleanup=cleanup or (lambda: True))


def headers(budget="90000"):
    return {"Authorization": "Bearer " + TOKEN, BUDGET_HEADER: budget}


def test_real_answer_mapper_and_existing_extraction_routed_without_raw_output():
    seen = []
    service = runtime(seen)
    with TestClient(create_app(TOKEN, lambda: service)) as client:
        reply = client.post("/answer", json=PAYLOAD, headers=headers("1500"))
        assert reply.status_code == 200, reply.text
        assert reply.json()["claims"][0]["citations"][0]["quote"] == TEXT
        assert not any(secret in reply.text for secret in ("reasoning", "tokens", PROMPT))
        assert [path for path, _, _ in seen].count("/v1/chat/completions") == 1
        assert all(max(timeout.values()) <= 1.5 for _, _, timeout in seen)
        reply = client.post("/analyze", json=ANALYZE, headers={"Authorization": "Bearer " + TOKEN})
        assert reply.status_code == 200, reply.text
        assert reply.json()["analysis"]["items"][0]["type"] == "topic"
        assert any(path == "/completion" and body["n_predict"] == 4 for path, body, _ in seen)
        health = client.get("/health", headers=headers()).json()
        assert health["answer"]["candidate_id"]
        assert health["extraction"]["runtime"]["nonthinking"]


@pytest.mark.parametrize("budget", ["", "0", "-1", "90001", "1.0", "01", " 1", "NaN"])
def test_budget_header_rejects_invalid_values_without_native_call(budget):
    seen = []
    with TestClient(create_app(TOKEN, lambda: runtime(seen))) as client:
        assert client.post("/answer", json=PAYLOAD, headers=headers(budget)).status_code == 422
    assert seen == []


def test_auth_missing_duplicate_budget_and_body_limit_are_checked():
    seen = []
    with TestClient(create_app(TOKEN, lambda: runtime(seen))) as client:
        assert client.post("/answer", json=PAYLOAD).status_code == 401
        assert client.post("/answer", json=PAYLOAD, headers={
            "Authorization": "Bearer " + TOKEN}).status_code == 422
        duplicate = [("Authorization", "Bearer " + TOKEN),
                     (BUDGET_HEADER, "1"), (BUDGET_HEADER, "90000")]
        assert client.post("/answer", json=PAYLOAD, headers=duplicate).status_code == 422
        assert client.post("/answer", content=b"x" * (1024 * 1024),
                           headers=headers()).status_code == 413
    assert seen == []


@pytest.mark.parametrize("failure,status,code", [
    ("input", 422, "context_budget_exceeded"),
    ("identity", 503, "generation_failed"),
    ("timeout", 504, "generation_deadline_exceeded"),
])
def test_failures_are_safe_single_attempt_and_never_abstentions(failure, status, code):
    seen, cleaned = [], []
    def override(request, body):
        if failure == "input" and request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": list(range(5121))})
        if request.url.path == "/v1/chat/completions":
            if failure == "timeout":
                raise httpx.ReadTimeout("private source")
            if failure == "identity":
                response = native_answer()
                response["model"] = "wrong"
                return httpx.Response(200, json=response)
    service = runtime(seen, override=override, cleanup=lambda: cleaned.append(True) or True)
    with TestClient(create_app(TOKEN, lambda: service)) as client:
        response = client.post("/answer", json=PAYLOAD, headers=headers())
        assert response.status_code == status
        assert response.json()["error"] == code
        assert "private" not in response.text and "abstained" not in response.text
        if failure == "timeout":
            assert cleaned == [True]
            assert client.get("/health", headers=headers()).status_code == 503
        assert sum(path == "/v1/chat/completions" for path, _, _ in seen) <= 1


def test_block_limit_rejected_before_any_native_request():
    seen = []
    payload = copy.deepcopy(PAYLOAD)
    payload["contexts"][0].update(text="x" * 1025, end_offset=1025)
    with TestClient(create_app(TOKEN, lambda: runtime(seen))) as client:
        result = client.post("/answer", json=payload, headers=headers())
        assert result.status_code == 422
        assert result.json()["error"] == "context_budget_exceeded"
    assert seen == []


def test_deadline_clamps_explicit_frozen_deadlines_and_cleanup_failure_is_visible():
    seen = []
    service = runtime(seen, cleanup=lambda: False)
    generator = service.answer_generator
    generator.service_deadline = time.monotonic() - 1
    with pytest.raises(GenerationError, match="generation_deadline_exceeded"):
        generator._remaining(time.monotonic() + 90)
    generator.service_deadline = None
    with pytest.raises(WorkerError, match="generation_cleanup_failed"):
        service.close()
    with pytest.raises(WorkerError, match="generation_cleanup_failed"):
        service.close()


def test_shared_contention_and_watchdog_poison_until_restart():
    seen, entered, release, cleaned = [], threading.Event(), threading.Event(), []
    def override(request, body):
        if request.url.path == "/v1/chat/completions":
            entered.set()
            assert release.wait(2)
    def cleanup():
        cleaned.append(True)
        release.set()
        return True
    service = runtime(seen, override=override, cleanup=cleanup)
    errors = []
    def answer():
        try:
            service.answer(AnswerRequest(**PAYLOAD), time.monotonic() + 0.15)
        except WorkerError as error:
            errors.append(error.code)
    thread = threading.Thread(target=answer)
    thread.start()
    assert entered.wait(1)
    with pytest.raises(WorkerError, match="model_busy"):
        service.analyze(AnalyzeRequest(**ANALYZE))
    thread.join(2)
    assert not thread.is_alive()
    assert errors == ["generation_deadline_exceeded"] and cleaned == [True]
    with pytest.raises(WorkerError, match="generation_failed"):
        service.health()
    service.close()
    assert cleaned == [True]


def test_missing_cleanup_configuration_is_rejected():
    service = runtime([])
    with pytest.raises(TypeError, match="owned_cleanup_required"):
        ServiceRuntime(service.answer_generator, service.analysis.generator, cleanup=None)
    service.close()


def test_analysis_keeps_admission_until_watchdog_join_and_busy_starts_no_timer(monkeypatch):
    service = runtime([])
    joining, release = threading.Event(), threading.Event()
    created = []
    class Timer:
        def __init__(self, seconds, callback):
            created.append(seconds)
        def start(self):
            pass
        def cancel(self):
            pass
        def join(self):
            joining.set()
            assert release.wait(2)
    monkeypatch.setattr("doctrail.meeting_service_rag.threading.Timer", Timer)
    results = []
    thread = threading.Thread(target=lambda: results.append(
        service.analyze(AnalyzeRequest(**ANALYZE))))
    thread.start()
    assert joining.wait(1)
    assert not service.analysis.lock.locked() and service.lock.locked()
    with pytest.raises(WorkerError, match="model_busy"):
        service.answer(AnswerRequest(**PAYLOAD), time.monotonic() + 1)
    with pytest.raises(WorkerError, match="model_busy"):
        service.analyze(AnalyzeRequest(**ANALYZE))
    assert created == [EXTRACTION_SECONDS]
    release.set()
    thread.join(2)
    assert len(results) == 1 and not service.lock.locked()
    service.close()


def test_ingress_body_time_consumes_budget_without_native_dispatch(monkeypatch):
    import asyncio
    seen = []
    service = runtime(seen)
    app = create_app(TOKEN, lambda: service)
    app.state.runtime = service
    clock = [100.0]
    monkeypatch.setattr("doctrail.meeting_service_rag.time.monotonic", lambda: clock[0])
    sent = []
    async def receive():
        clock[0] += 2
        return {"type": "http.request", "body": json.dumps(PAYLOAD).encode(),
                "more_body": False}
    async def send(message):
        sent.append(message)
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "POST", "scheme": "http", "path": "/answer", "raw_path": b"/answer",
             "query_string": b"", "root_path": "", "server": ("localhost", 80),
             "client": ("localhost", 1), "headers": [
                 (b"authorization", ("Bearer " + TOKEN).encode()),
                 (b"content-type", b"application/json"),
                 (BUDGET_HEADER.lower().encode(), b"1000")]}
    asyncio.run(app(scope, receive, send))
    assert sent[0]["status"] == 504 and seen == []
    service.close()


def test_timeout_cleanup_failure_is_http_error_and_cannot_reenter():
    seen = []
    def override(request, body):
        if request.url.path == "/v1/chat/completions":
            raise httpx.ReadTimeout("private source")
    service = runtime(seen, override=override, cleanup=lambda: False)
    # Shutdown also surfaces the same failed cleanup; do not replace the HTTP error.
    with (pytest.raises(WorkerError, match="generation_cleanup_failed"),
          TestClient(create_app(TOKEN, lambda: service)) as client):
        response = client.post("/answer", json=PAYLOAD, headers=headers())
        assert response.status_code == 503
        assert response.json()["error"] == "generation_cleanup_failed"
        count = len(seen)
        response = client.post("/answer", json=PAYLOAD, headers=headers())
        assert response.status_code == 503 and len(seen) == count


@pytest.fixture(params=["batch-v1", "batch-v2"])
def batch_runtime(request):
    from test_meeting_analysis_batch import Native

    from doctrail.meeting_analysis_batch import (
        BatchedAnalysisGenerator,
        ScopedBatchedAnalysisGenerator,
    )
    rigs = []
    def build(observer=None):
        native = Native()
        native.generator.close()
        def handle(request):
            body = json.loads(request.content)
            if request.url.path == "/apply-template" and "TARGETS" not in json.loads(
                    body["messages"][-1]["content"]):
                return httpx.Response(200, json={"prompt": "partition" + NONTHINKING_PREAMBLE})
            if request.url.path == "/tokenize" and body["content"].startswith("partition"):
                return httpx.Response(200, json={"tokens": [0] * 10})
            return native.handle(request)
        plain, observed = ((BatchedAnalysisGenerator, ObservedBatchedAnalysisGenerator)
                           if request.param == "batch-v1" else
                           (ScopedBatchedAnalysisGenerator, ObservedScopedBatchedAnalysisGenerator))
        cls = plain if observer is None else observed
        options = {} if observer is None else {"observer": observer}
        native.generator = cls("http://127.0.0.1:19003", TOKEN, "unused-synthetic",
            transport=httpx.MockTransport(handle), **options)
        native.generator._alias = GGUF_SHA256
        native.generator._metadata = copy.deepcopy(METADATA)
        answer = SimpleNamespace(public_metadata=lambda: copy.deepcopy(METADATA), close=lambda: None)
        service = ServiceRuntime(answer, native.generator, cleanup=lambda: True, observer=observer)
        rigs.append(service)
        return service, native
    yield build
    for service in rigs:
        service.close()


@pytest.mark.parametrize("observed", [False, True])
def test_batch_actual_meeting_runtime_preserves_all_units_offsets_and_extracts_summary(
        batch_runtime, observed):
    from doctrail.meeting_contract import meeting_units
    from doctrail.meeting_worker import classification_messages
    events = []
    observer = (lambda op, event, value: events.append((event, value))) if observed else None
    service, native = batch_runtime(observer)
    content = "## Purpose\nReview every option.\n" + "\n".join(
        f"Task {i}: prepare the synthetic report." for i in range(10))
    units = meeting_units(content)
    targets = [json.loads(classification_messages(u)[-1]["content"])["TARGET"] for u in units]
    native.response = lambda ids: json.dumps([[i, 4 if targets[i].startswith("Purpose:") else 9]
                                             for i in ids])
    result = service.analyze(AnalyzeRequest(schema_version=1, document_id="synthetic",
        revision=1, title="Synthetic", content=content))
    assert [r["TARGET"] for b in native.batches for r in b] == targets
    assert [r["id"] for b in native.batches for r in b] == list(range(len(units)))
    analysis = result["analysis"]
    for item in [*analysis["items"], *analysis["metadata_evidence"], *analysis["summary_evidence"]]:
        assert content[item["start_offset"]:item["end_offset"]] == item["quote"]
    assert len(analysis["items"]) + len(analysis["metadata_evidence"]) == len(units)
    assert len(analysis["summary_evidence"]) == 4
    assert analysis["summary"] == "\n".join(e["quote"] for e in analysis["summary_evidence"])
    assert analysis["metadata_evidence"][0]["quote"].startswith("## Purpose\n")
    assert service.health()["extraction"]["classification"]["policy"] == native.generator.analysis_policy
    assert all(("Current-meeting scope and statement intent:" in messages[0]["content"])
               == (service.analysis_policy == "batch-v2") for messages in native.messages)
    assert not native.generator._cache and native.generator.service_deadline is None
    if observed:
        assert [value for event, value in events if event == "classification_units"] == [len(units)]
        assert [value["ids"] for event, value in events if event == "classification_batch"] == [
            [r["id"] for r in batch] for batch in native.batches]
        assert sum(event == "transport_started" and value["path"] == "/completion"
                   for event, value in events) == len(native.batches)


def test_later_singleton_overflow_fails_entire_analysis_without_retry(batch_runtime):
    service, native = batch_runtime()
    native.size = lambda rows: 4097 if any(row["id"] == 8 for row in rows) else 100
    with pytest.raises(WorkerError, match="generation_input_limit"):
        service.analyze(AnalyzeRequest(schema_version=1, document_id="synthetic", revision=1,
            title="Synthetic", content="\n".join(f"Task {i}." for i in range(17))))
    assert [[r["id"] for r in b] for b in native.batches] == [list(range(8))]
    assert not native.generator._cache


@pytest.mark.parametrize("event", ["classification_batch", "transport_response"])
def test_observer_storage_failure_stops_batch_native_without_partial_result(batch_runtime, event):
    records = []
    def observe(op, kind, value):
        records.append(kind)
        if kind == event:
            raise OSError("synthetic archive failure")
    service, native = batch_runtime(observe)
    with pytest.raises(WorkerError, match="generation_failed"):
        service.analyze(AnalyzeRequest.model_validate(ANALYZE))
    assert native.batches == []
    assert not native.generator._cache and native.generator.service_deadline is None
    assert service._poisoned


@pytest.mark.parametrize("observed", [False, True])
def test_batch_preparation_consumes_original_outer_deadline(batch_runtime, monkeypatch, observed):
    from doctrail.meeting_analysis_batch import batch_messages
    now = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    def observer(op, event, value):
        if event == "started":
            now[0] += 50
    service, native = batch_runtime(observer if observed else None)
    original = service.analysis.analyze
    def analyze(request):
        # All preprocessing shares the outer deadline, even when the inner runtime starts later.
        now[0] += 40
        assert native.generator._remaining(340) == (30 if observed else 80)
        native.generator._prepare(batch_messages([{"id": 0, "TARGET": "synthetic"}]), 340)
        now[0] = 221
        return original(request)
    service.analysis.analyze = analyze
    with pytest.raises(WorkerError, match="generation_deadline_exceeded"):
        service.analyze(AnalyzeRequest.model_validate(ANALYZE))
    assert native.batches == [] and not native.generator._cache


@pytest.mark.parametrize("policy,observed", [("single", False), ("single", True),
                                           ("batch-v1", False), ("batch-v1", True),
                                           ("batch-v2", False), ("batch-v2", True)])
def test_load_runtime_selects_same_algorithm_with_or_without_observer(monkeypatch, policy, observed):
    import doctrail.meeting_service_rag as module
    from doctrail.meeting_analysis_batch import BatchedAnalysisGenerator
    def load(self):
        self._metadata = copy.deepcopy(METADATA)
        return self
    monkeypatch.setattr(module.ServiceAnswerGenerator, "load", load)
    monkeypatch.setattr(module.Qwen35Generator, "load", load)
    service = module.load_runtime(SimpleNamespace(url="http://127.0.0.1:19003", token=TOKEN,
        manifest="unused"), cleanup=lambda: True, startup_deadline=time.monotonic() + 30,
        analysis_policy=policy, observer=(lambda *args: None) if observed else None)
    try:
        assert isinstance(service.analysis.generator, BatchedAnalysisGenerator) == (policy != "single")
        assert isinstance(service.analysis.generator, module.ObservedAnalysisGenerator) == observed
        assert service.health()["extraction"]["classification"]["policy"] == policy
    finally:
        service.close()

def test_completed_batch_archive_failure_blocks_all_later_batches(batch_runtime):
    errors = []
    def observer(op, event, value):
        if event == "transport_response" and value["path"] == "/completion":
            raise OSError("synthetic sink failure after complete parsed body")
        if event == "transport_error":
            errors.append(value)
    service, native = batch_runtime(observer)
    with pytest.raises(WorkerError, match="generation_failed"):
        service.analyze(AnalyzeRequest(schema_version=1, document_id="synthetic", revision=1,
            title="Synthetic", content="\n".join(f"Task {i}." for i in range(20))))
    assert len(native.batches) == 1
    assert errors[-1]["parsed_json_available"] is True and errors[-1]["archive_failed"] is True
    assert not native.generator._cache and service._poisoned


def test_batch_mapping_observer_time_cannot_renew_deadline(batch_runtime, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    def observer(op, event, value):
        if event == "classification_batch":
            now[0] += 121
    service, native = batch_runtime(observer)
    with pytest.raises(WorkerError, match="generation_deadline_exceeded"):
        service.analyze(AnalyzeRequest.model_validate(ANALYZE))
    assert native.batches == [] and not native.generator._cache


@pytest.mark.parametrize("observed", [False, True])
@pytest.mark.parametrize("field,label,first,other", [
    ("meeting_date", 2, "Date: 2041-04-12", "Date: 2041-04-13"),
    ("meeting_title", 1, "Title: Sample review", "Title: Sample planning"),
    ("purpose", 4, "Purpose: Review the protocol.", "Purpose: Approve a rollout.")])
@pytest.mark.parametrize("conflicting", [False, True])
def test_current_metadata_repetition_keeps_evidence_and_conflict_stays_strict(
        batch_runtime, observed, field, label, first, other, conflicting):
    service, native = batch_runtime((lambda *args: None) if observed else None)
    native.response = lambda ids: json.dumps([[i, label if i < 2 else 5] for i in ids])
    content = first + "\n" + (other if conflicting else first) + "\nThe sampler emitted its report."
    request = AnalyzeRequest(schema_version=1, document_id="synthetic", revision=1,
                             title="Synthetic", content=content)
    if conflicting:
        with pytest.raises(WorkerError, match="generation_conflicting_metadata") as error:
            service.analyze(request)
        assert error.value.status == 502
    else:
        analysis = service.analyze(request)["analysis"]
        assert len(analysis["metadata_evidence"]) == 2
        assert all(e["field"] == field for e in analysis["metadata_evidence"])
        for evidence in analysis["metadata_evidence"]:
            assert content[evidence["start_offset"]:evidence["end_offset"]] == evidence["quote"]
    assert len(native.batches) == 1  # no relabel, retry or conflict repair
    assert not native.generator._cache


def test_runtime_rejects_policy_drift_before_health_or_native(batch_runtime):
    service, native = batch_runtime()
    native.generator.analysis_policy = "batch-v2" if service.analysis_policy == "batch-v1" else "batch-v1"
    with pytest.raises(WorkerError, match="generation_failed"):
        service.health()
    with pytest.raises(WorkerError, match="generation_failed"):
        service.analyze(AnalyzeRequest.model_validate(ANALYZE))
    assert native.calls == []


def test_requested_v2_cannot_load_a_v1_generator(monkeypatch):
    import doctrail.meeting_service_rag as module
    def load(self):
        self._metadata = copy.deepcopy(METADATA)
        return self
    monkeypatch.setattr(module.ServiceAnswerGenerator, "load", load)
    monkeypatch.setattr(module.Qwen35Generator, "load", load)
    monkeypatch.setattr(module, "ScopedBatchedAnalysisGenerator", module.BatchedAnalysisGenerator)
    with pytest.raises(GenerationError, match="generation_identity_mismatch"):
        module.load_runtime(SimpleNamespace(url="http://127.0.0.1:19003", token=TOKEN,
            manifest="unused"), cleanup=lambda: True, startup_deadline=time.monotonic() + 30,
            analysis_policy="batch-v2")
