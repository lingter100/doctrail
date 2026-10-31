"""Synthetic observer/service orchestration checks, never real model quality."""
import json
import sys
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_contract import AnswerRequest, Context
from scripts import run_meeting_qa_service_development as m


class FakeGenerator:
    def __init__(self):
        self.tokens = 100
        self.text = '{"status":"abstained","claims":[]}'
        self.count_error = self.generate_error = self.end_error = None
        self.calls = []
        self.last_effective_config = {"n_predict": 768}

    def public_metadata(self):
        return {"repo_id": "synthetic", "revision": "fake"}

    def begin_request(self, deadline):
        self.calls.append(("begin", deadline))

    def end_request(self):
        self.calls.append(("end",))
        if self.end_error:
            raise self.end_error

    def count_tokens(self, messages):
        self.calls.append(("count", messages))
        if self.count_error:
            raise self.count_error
        return self.tokens

    def generate_bounded(self, messages, deadline):
        self.calls.append(("generate", messages, deadline))
        if self.generate_error:
            raise self.generate_error
        self.result = SimpleNamespace(text=self.text, input_tokens=self.tokens,
            output_tokens=12, finish_reason="eos", elapsed_seconds=0.25)
        return self.result

    def close(self):
        self.calls.append(("close",))


def request(empty=False):
    return AnswerRequest(schema_version=1, query="fixed public question", contexts=[] if empty else [
        Context(document_id="doc", revision=1, chunk_id="chunk", title="public", page=None,
                meeting_date=None, start_offset=0, end_offset=6, text="source")])


@pytest.mark.parametrize("mode", ["count", "generate", "parser", "citation", "input"])
def test_second_failure_never_inherits_first_success(mode):
    base = FakeGenerator()
    observer = m.ObservedGenerator(base, ["one", "two"])
    runtime = m.ObservedRuntime(observer)
    observer.reset("one")
    runtime.answer(request())
    previous = runtime.runtime.last_telemetry
    observer.reset("two")
    if mode == "count":
        base.count_error = GenerationError("generation_tokenization_failed")
    elif mode == "generate":
        base.generate_error = GenerationError("generation_backend_unavailable")
    elif mode == "parser":
        base.text = "public malformed output"
    elif mode == "citation":
        base.text = '{"status":"answered","claims":[{"text":"claim","evidence":[999]}]}'
    else:
        base.tokens = 4097
    with pytest.raises(WorkerError):
        runtime.answer(request())
    row = observer.current
    assert runtime.runtime.last_telemetry is previous  # The production stale value exists.
    assert row["first_failure"] is not None
    assert row["worker_result"] is None
    assert row["count_calls"] == 1
    if mode in {"parser", "citation"}:
        assert row["raw_output"] == base.text
        assert row["metrics"]["output_tokens"] == 12
        assert row["generation_returned"] is True
    else:
        assert row["metrics"] is row["raw_output"] is None
        assert row["generation_returned"] is False
    if mode in {"count", "input"}:
        assert row["generation_attempts"] == 0 and observer.attempts == 1
    if mode == "count":
        assert row["counted_input_tokens"] is None
    if mode == "input":
        assert row["counted_input_tokens"] == 4097


def test_exact_forwarding_results_and_lifecycle():
    base = FakeGenerator()
    observer = m.ObservedGenerator(base, ["one", "two"])
    observer.reset("one")
    messages, deadline = [{"role": "user", "content": "public"}], 123.0
    observer.begin_request(deadline)
    assert observer.count_tokens(messages) == 100
    result = observer.generate_bounded(messages, deadline)
    assert result is base.result
    observer.end_request()
    observer.close()
    assert [c[0] for c in base.calls] == ["begin", "count", "generate", "end", "close"]
    assert base.calls[1][1] is messages and base.calls[2][1] is messages
    assert base.calls[2][2] == deadline
    assert observer.public_metadata() == base.public_metadata()
    assert observer.last_effective_config is base.last_effective_config


def test_failed_generation_consumes_per_case_and_total_budget():
    base = FakeGenerator()
    base.generate_error = GenerationError("generation_backend_unavailable")
    observer = m.ObservedGenerator(base, ["one", "two", "three"])
    for name in ("one", "two"):
        observer.reset(name)
        with pytest.raises(GenerationError):
            observer.generate_bounded([], 123)
        with pytest.raises(GenerationError, match="completion_limit"):
            observer.generate_bounded([], 123)
    observer.reset("three")
    with pytest.raises(GenerationError, match="completion_limit"):
        observer.generate_bounded([], 123)
    assert observer.attempts == 2 and observer.requested_tokens == 1536
    assert len([c for c in base.calls if c[0] == "generate"]) == 2


def test_first_parser_failure_survives_end_request_failure():
    base = FakeGenerator()
    base.text = "malformed public output"
    base.end_error = RuntimeError("SECRET_TOKEN_NEVER_SERIALIZED")
    observer = m.ObservedGenerator(base, ["one"])
    observer.reset("one")
    with pytest.raises(RuntimeError):
        m.ObservedRuntime(observer).answer(request())
    row = observer.current
    assert row["first_failure"]["type"] == "WorkerError"
    assert row["secondary_failures"] == [{"type": "RuntimeError", "code": "development_failed"}]
    assert "SECRET" not in json.dumps(row)
    assert row["raw_output"] == base.text


def test_no_context_has_no_generation_metrics():
    observer = m.ObservedGenerator(FakeGenerator(), ["one"])
    observer.reset("one")
    assert m.ObservedRuntime(observer).answer(request(True))["status"] == "abstained"
    assert observer.attempts == observer.current["count_calls"] == 0
    assert observer.current["generation_returned"] is False
    assert observer.current["metrics"] is None


def test_4096_input_boundary_forwards_one_generation():
    base = FakeGenerator()
    base.tokens = 4096
    observer = m.ObservedGenerator(base, ["one"])
    observer.reset("one")
    m.ObservedRuntime(observer).answer(request())
    assert observer.current["counted_input_tokens"] == 4096
    assert observer.attempts == 1 and observer.requested_tokens == 768
    assert [c[0] for c in base.calls] == ["begin", "count", "generate", "end"]


def test_real_bundle_is_three_sources_two_fixed_questions():
    documents, cases = m.load_bundle()
    assert len(documents) == 3 and len(cases) == 2
    assert all(isinstance(d["content"], bytes) and d["content"] for d in documents)


def test_operations_only_documents_then_search_and_answer_once_each():
    paths = []
    def handle(req):
        paths.append(req.url.path)
        if req.url.path.endswith("/register"):
            return httpx.Response(201, json={"workspaces": [{"id": "fresh"}]})
        if req.url.path.endswith("/documents"):
            return httpx.Response(201, json={"id": str(len(paths)), "status": "ready",
                                            "revision": 1, "chunks": []})
        if req.url.path.endswith("/search"):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json={"status": "abstained", "reason": "no_evidence",
                                         "results": [], "model_called": False, "elapsed_ms": 1})
    documents, cases = m.load_bundle()
    observer = m.ObservedGenerator(FakeGenerator(), [c["id"] for c in cases])
    report = {"documents": []}
    with httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(handle)) as client:
        m.operations(client, documents, cases, observer, report, time.monotonic() + 30)
    assert paths == ["/api/auth/register"] + ["/api/workspaces/fresh/documents"] * 3 + [
        "/api/knowledge/search", "/api/knowledge/answer"] * 2
    assert all(row["generation_returned"] is False for row in observer.rows)
    assert observer.attempts == 0
    assert all(row["java_request"]["limit"] == 10 for row in observer.rows)


def test_cleanup_continues_and_keeps_first_error():
    class Child:
        stopped = False
        def poll(self):
            return 0 if self.stopped else None
        def terminate(self):
            raise OSError("SECRET")
        def kill(self):
            self.stopped = True
        def wait(self, timeout):
            return 0
    report = m.FailureRecord({"first_failure": None, "secondary_failures": []})
    m.record_error(report, GenerationError("generation_input_limit"))
    child = Child()
    m.cleanup_owned([child], None, None, report)
    assert child.stopped and report["cleanup"]["owned_children_absent"]
    assert report["first_failure"]["code"] == "generation_input_limit"
    assert report["secondary_failures"] == [{"type": "OSError", "code": "development_failed"}]


def test_environment_removes_inherited_retrieval_and_config(monkeypatch):
    monkeypatch.setenv("DOCTRAIL_INFERENCE_URL", "SECRET")
    monkeypatch.setenv("DOCTRAIL_RAG_ANSWER_ENABLED", "true")
    monkeypatch.setenv("LLAMA_API_KEY", "SECRET")
    env = m.java_environment(Path("fresh.sqlite3"), "http://127.0.0.1:1234", "token")
    assert "DOCTRAIL_INFERENCE_URL" not in env and "LLAMA_API_KEY" not in env
    assert "DOCTRAIL_RAG_ANSWER_ENABLED" not in env
    assert env["DOCTRAIL_GENERATION_URL"] == "http://127.0.0.1:1234"
    assert env["DOCTRAIL_EMBEDDING_PROFILE"] == "base"


def test_launcher_owns_only_two_children_and_preserves_body_failure(monkeypatch):
    children, waits = [], []
    class Child:
        stopped = False
        def __init__(self, argv, **kwargs):
            self.argv, self.kwargs = argv, kwargs
            children.append(self)
        def poll(self):
            return 0 if self.stopped else None
        def terminate(self):
            self.stopped = True
        def kill(self):
            self.stopped = True
        def wait(self, timeout):
            return 0
    class Thread:
        def __init__(self, **kwargs):
            pass
        def start(self):
            pass
        def join(self, timeout):
            pass
        def is_alive(self):
            return False
    base = FakeGenerator()
    base.load = lambda: None
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace())
    monkeypatch.setattr(m, "worker_lease", lambda path: nullcontext())
    monkeypatch.setattr(m, "prepare", lambda *a, **kw: {
        "server_path": "fake/server.exe", "model": {"path": "fake/model.gguf"}})
    monkeypatch.setattr(m, "GGUFGenerator", lambda *a, **kw: base)
    ports = iter([12341, 12342, 12343])
    monkeypatch.setattr(m, "unused_port", lambda: next(ports))
    monkeypatch.setattr(m, "java_executable", lambda: Path("fake-java.exe"))
    monkeypatch.setattr(m.subprocess, "Popen", Child)
    monkeypatch.setattr(m.threading, "Thread", Thread)
    monkeypatch.setattr(m, "make_server", lambda *a: SimpleNamespace(run=lambda: None))
    monkeypatch.setattr(m, "wait_ready", lambda process, url, **kw: waits.append((url, kw)))
    report = m.FailureRecord({"first_failure": None, "secondary_failures": []})
    observer = m.ObservedGenerator(None, ["one", "two"])
    with (pytest.raises(GenerationError, match="input_limit"),
          m.start_services(Path("fake.jar"), Path("fake-output"), observer, report,
                           time.monotonic() + 120)):
        raise GenerationError("generation_input_limit")
    assert len(children) == 2 and all(c.stopped for c in children)
    assert "--no-warmup" in children[0].argv
    assert len(waits) == 3 and all(0 < opts["timeout"] <= 120 for _, opts in waits)
    assert "--doctrail.rag-answer-enabled=false" in children[1].argv
    assert children[1].kwargs["env"]["DOCTRAIL_GENERATION_URL"] == "http://127.0.0.1:12342"
    assert "DOCTRAIL_INFERENCE_URL" not in children[1].kwargs["env"]
    assert report["first_failure"]["code"] == "generation_input_limit"
    assert report["cleanup"]["owned_children_absent"]
    assert [c[0] for c in base.calls].count("close") == 1


def test_distinct_same_code_failures_remain_and_same_exception_propagates_once():
    report = m.FailureRecord({"first_failure": None, "secondary_failures": []})
    body, cleanup = RuntimeError("private body"), RuntimeError("private cleanup")
    m.record_error(report, body)
    m.record_error(report, body)
    m.record_error(report, cleanup)
    m.record_error(report, cleanup)
    assert report["first_failure"] == {"type": "RuntimeError", "code": "development_failed"}
    assert report["secondary_failures"] == [report["first_failure"]]
    assert report.errors == [body, cleanup]
    assert "private" not in json.dumps(report)


def blocking_runtime():
    entered, release = threading.Event(), threading.Event()
    base = FakeGenerator()
    count = base.count_tokens
    def blocked_count(messages):
        entered.set()
        if not release.wait(timeout=5):
            raise TimeoutError
        return count(messages)
    base.count_tokens = blocked_count
    base.end_error = RuntimeError("late end failure")
    observer = m.ObservedGenerator(base, ["one", "two"])
    runtime = m.ObservedRuntime(observer)
    errors = []
    def answer():
        try:
            runtime.answer(request())
        except Exception as error:  # noqa: BLE001 - transfer worker exception to test thread
            errors.append(error)
    thread = threading.Thread(target=answer)
    return base, observer, entered, release, thread, errors


def test_active_invocation_blocks_reset_and_late_generation_end_stay_in_first_case():
    base, observer, entered, release, thread, errors = blocking_runtime()
    observer.reset("one")
    first = observer.current
    thread.start()
    try:
        assert entered.wait(timeout=5)
        with pytest.raises(GenerationError, match="worker_inflight"):
            observer.reset("two")
        assert observer.current is first and len(observer.rows) == 1
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive() and errors == [base.end_error]
    assert first["generation_attempts"] == 1 and first["generation_returned"] is True
    assert first["counted_input_tokens"] == 100
    assert first["first_failure"]["type"] == "RuntimeError"
    assert observer.active is False


def test_http_timeout_halts_later_case_even_when_first_worker_finishes_late():
    base, observer, entered, release, thread, errors = blocking_runtime()
    paths = []
    cases = [{"id": "one", "question": "one"}, {"id": "two", "question": "two"}]
    report = m.FailureRecord({"documents": [], "first_failure": None, "secondary_failures": []})
    def handle(req):
        paths.append(req.url.path)
        if req.url.path.endswith("/register"):
            return httpx.Response(201, json={"workspaces": [{"id": "fresh"}]})
        if req.url.path.endswith("/search"):
            return httpx.Response(200, json={"results": [{"chunk_id": "chunk"}]})
        thread.start()
        assert entered.wait(timeout=5)
        raise httpx.ReadTimeout("private transport detail", request=req)
    try:
        with (httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(handle)) as client,
              pytest.raises(httpx.ReadTimeout)):
            m.operations(client, [], cases, observer, report, time.monotonic() + 30)
        assert observer.halted and report["unattempted_cases"] == ["two"]
        assert paths == ["/api/auth/register", "/api/knowledge/search", "/api/knowledge/answer"]
        with pytest.raises(GenerationError, match="worker_inflight"):
            observer.reset("two")
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive() and errors == [base.end_error]
    first = observer.rows[0]
    assert first["first_failure"]["type"] == "ReadTimeout"
    assert first["secondary_failures"] == [{"type": "RuntimeError", "code": "development_failed"}]
    assert first["generation_returned"] is True and observer.attempts == 1
    assert len(observer.rows) == 1 and "private" not in json.dumps(first)
