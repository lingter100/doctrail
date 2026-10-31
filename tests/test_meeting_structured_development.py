"""Synthetic HTTP/clock fixtures only: no Java, native models or network."""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest

from scripts import run_meeting_structured_development as m


class Clock:
    now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def packet():
    return ([{"document_id": f"d{i}", "role": "meeting" if i < 3 else "general_document",
              "title": f"source {i}", "path": f"d{i}.md", "content": b"source text"} for i in range(1, 4)],
            [{"id": f"q{i}", "question": f"fixed question {i}"} for i in range(1, 3)])


def document(identity):
    return {"id": identity, "content": "source text", "revision": 1, "status": "ready", "chunks": [
        {"id": identity + "c", "text": "source text", "start_offset": 0, "end_offset": 11, "page": None}]}


class Scenario:
    def __init__(self, *, fail=None, queued=False, stale=False):
        self.clock = Clock()
        self.services = {"runtime": SimpleNamespace(last_telemetry={}), "generator": SimpleNamespace(last_call=None)}
        self.report = m.FailureRecord(first_failure=None, secondary_failures=[])
        self.calls, self.saves = [], []
        self.fail, self.queued, self.stale = fail, queued, stale
        self.meetings = self.answers = 0

    def receipt(self):
        if self.stale:
            return
        self.services["runtime"].last_telemetry = {"status": "complete", "stage": "assembled",
            "calls": [{"operation": "summary", "input_tokens": 25, "output_tokens": 8, "finish_reason": "eos"}]}
        self.services["generator"].last_call = {"operation": "meeting_summary", "output_cap": 768,
            "dispatched": True, "accepted": True, "secret": "DO_NOT_LOG"}

    def handler(self, request):
        path = request.url.path
        self.calls.append((request.method, path))
        if path.endswith("/register"):
            return httpx.Response(201, json={"workspaces": [{"id": "w"}], "secret": "DO_NOT_LOG"},
                                  headers={"set-cookie": "session=DO_NOT_LOG"})
        if path.endswith("/documents"):
            return httpx.Response(201, json=document("d3"))
        if path.endswith("/meetings"):
            self.meetings += 1
            if self.fail == "http":
                return httpx.Response(503, json={"secret": "DO_NOT_LOG"})
            if self.fail == "timeout":
                raise httpx.ReadTimeout("DO_NOT_LOG", request=request)
            identity = f"d{self.meetings}"
        elif "/meetings/" in path:
            identity = path.rsplit("/", 1)[1]
        else:
            self.answers += 1
            assert json.loads(request.content)["method"] == "bm25"
            assert json.loads(request.content)["limit"] == 10
            if self.fail == "answer":
                return httpx.Response(502, json={"message": "DO_NOT_LOG"})
            self.receipt()
            return httpx.Response(200, json={"status": "abstained", "claims": [], "model_called": True})
        self.receipt()
        state = "failed" if self.fail == "analysis" else "queued" if self.queued else "ready"
        return httpx.Response(201 if request.method == "POST" else 200,
                              json={"document": document(identity), "meeting": {
                                  "analysis_status": state, "source_revision": 1, "ai_analysis": {"fixture": True}}})

    def run(self, monkeypatch, deadline=590):
        monkeypatch.setattr(m, "validate_summary_analysis", lambda analysis, content: None)
        with httpx.Client(transport=httpx.MockTransport(self.handler), base_url="http://test") as client:
            m.run_operations(client, self.services, *packet(), self.report, deadline,
                             lambda: self.saves.append(copy.deepcopy(dict(self.report))),
                             clock=self.clock, sleep=self.clock.sleep)


def test_exact_sequence_caps_and_no_auth_or_arbitrary_metrics_saved(monkeypatch):
    s = Scenario()
    s.run(monkeypatch)
    assert s.meetings == s.answers == 2
    assert [path.rsplit("/", 1)[1] for _, path in s.calls] == [
        "register", "documents", "meetings", "meetings", "answer", "answer"]
    assert all(row["state"] == "complete" for row in s.report["operations"])
    assert "DO_NOT_LOG" not in json.dumps(s.report)
    assert len(s.saves) == 5
    assert m.LIMITS["native_completion_ceiling"] == 2 * (160 + 2) + 2
    assert m.LIMITS["requested_output_token_ceiling"] == 2 * (160 * 4 + 768 + 128) + 2 * 768


@pytest.mark.parametrize("failure", ["analysis", "http", "timeout"])
def test_first_analysis_failure_halts_every_later_generation(monkeypatch, failure):
    s = Scenario(fail=failure)
    with pytest.raises((m.DevelopmentError, httpx.ReadTimeout)):
        s.run(monkeypatch)
    assert s.meetings == 1 and s.answers == 0
    assert [row["state"] for row in s.report["operations"]] == [
        "failed_or_unknown", "unattempted", "unattempted", "unattempted"]
    assert "DO_NOT_LOG" not in json.dumps(s.report)


def test_first_answer_http_failure_never_dispatches_second(monkeypatch):
    s = Scenario(fail="answer")
    with pytest.raises(m.DevelopmentError):
        s.run(monkeypatch)
    assert s.answers == 1
    assert s.report["operations"][-1]["state"] == "unattempted"


@pytest.mark.parametrize("deadline,expected", [(590, 160), (1, 1)])
def test_async_polling_uses_stage_and_shared_deadline(monkeypatch, deadline, expected):
    s = Scenario(queued=True)
    with pytest.raises(m.DevelopmentError, match="deadline"):
        s.run(monkeypatch, deadline)
    assert s.clock.now == pytest.approx(expected)
    assert s.meetings == 1 and s.answers == 0
    assert not any(path.endswith("/analyze") for _, path in s.calls)


def test_stale_terminal_receipt_not_attributed_or_followed(monkeypatch):
    s = Scenario(stale=True)
    s.services["runtime"].last_telemetry = {"status": "complete", "calls": [{"input_tokens": 999}]}
    with pytest.raises(m.DevelopmentError, match="receipt_unknown"):
        s.run(monkeypatch)
    assert s.meetings == 1
    observed = s.report["operations"][0]["observation"]
    assert observed["runtime_state"] == "unknown_or_inflight" and observed["runtime"] is None
    assert observed["structured_call"] is None


def test_partial_call_is_observed_without_inventing_terminal_counts():
    services = {"runtime": SimpleNamespace(last_telemetry={}), "generator": SimpleNamespace(last_call=None)}
    before = m.snapshot(services)
    services["generator"].last_call = {"operation": "meeting_summary", "dispatched": True,
                                        "returned": False, "output_cap": 768, "prompt": "DO_NOT_LOG"}
    observed = m.observe(services, before)
    assert observed["runtime"] is None
    assert observed["structured_call"]["dispatched"] is True
    assert "output_tokens" not in observed["structured_call"]
    assert "DO_NOT_LOG" not in json.dumps(observed)


def test_neighbor_citation_uses_all_original_chunks_and_exact_unicode_span():
    doc = document("d1")
    doc["content"] = "😀 source"
    doc["chunks"] = [{"id": "neighbor", "text": "source", "start_offset": 2, "end_offset": 8, "page": None}]
    citation = {"document_id": "d1", "revision": 1, "chunk_id": "neighbor", "page": None,
                "quote": "source", "start_offset": 2, "end_offset": 8}
    answer = {"status": "answered", "results": [], "claims": [{"text": "claim", "citations": [citation]}]}
    m.check_answer(answer, [doc])
    citation["revision"] = 2
    with pytest.raises(m.DevelopmentError, match="citation_binding"):
        m.check_answer(answer, [doc])


def test_document_source_mismatch_rejected():
    sources, _ = packet()
    doc = document("d1")
    doc["content"] = "changed"
    with pytest.raises(m.DevelopmentError, match="document_binding"):
        m.check_document(doc, sources[0])


def test_first_error_survives_snapshot_write_failure(monkeypatch):
    s = Scenario(fail="analysis")
    monkeypatch.setattr(m, "validate_summary_analysis", lambda *_: None)
    writes = 0

    def save():
        nonlocal writes
        writes += 1
        if writes > 1:
            raise OSError("DO_NOT_LOG")

    with (httpx.Client(transport=httpx.MockTransport(s.handler), base_url="http://test") as client,
          pytest.raises(OSError)):
        m.run_operations(client, s.services, *packet(), s.report, 590, save, clock=s.clock)
    assert s.report["first_failure"]["code"].endswith("analysis_failed")


def test_execute_preserves_primary_through_cleanup_and_refuses_reuse(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "ROOT", tmp_path)
    docs, cases = packet()
    for doc in docs:
        doc["raw_sha256"] = hashlib.sha256(doc["content"]).hexdigest()
    monkeypatch.setattr(m, "load_bundle", lambda _: (docs, cases))
    ports = iter([11001, 11002, 11003])
    monkeypatch.setattr(m, "unused_port", lambda: next(ports))
    jar = tmp_path / "synthetic.jar"
    jar.write_bytes(b"fixture")
    sha = hashlib.sha256(b"fixture").hexdigest()
    output = tmp_path / ".local" / "fresh"
    cleaned = []

    @contextmanager
    def launch(**kwargs):
        assert kwargs["enable_structured"] is True
        assert kwargs["database"] == output / "development.sqlite3"
        try:
            yield {"java_url": "http://test", "generator": SimpleNamespace(_client=SimpleNamespace(event_hooks={"response": []}))}
        finally:
            cleaned.append(True)
            raise OSError("DO_NOT_LOG cleanup")

    def operations(*args, **kwargs):
        raise m.DevelopmentError("primary_fixture")

    monkeypatch.setattr(m, "run_operations", operations)
    report = m.execute(jar, sha, output, launcher=launch)
    assert cleaned == [True] and report["status"] == "failed"
    assert report["first_failure"]["code"].endswith("primary_fixture")
    assert report["secondary_failures"][0]["type"] == "OSError"
    assert len(report["operations"]) == 4
    assert all(row["state"] == "unattempted" for row in report["operations"])
    assert "DO_NOT_LOG" not in (output / "result.json").read_text()
    with pytest.raises(m.DevelopmentError, match="fresh_private"):
        m.execute(jar, sha, output, launcher=launch)


def test_wrong_jar_refused_before_launch_or_output(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "ROOT", tmp_path)
    jar = tmp_path / "synthetic.jar"
    jar.write_bytes(b"fixture")
    output = tmp_path / ".local" / "fresh"
    with pytest.raises(m.DevelopmentError, match="jar_hash"):
        m.execute(jar, "0" * 64, output)
    assert not output.exists()


@pytest.mark.parametrize("route", ["/completion", "/v1/chat/completions"])
def test_capture_stream_preserves_public_output_even_before_validator_rejection(tmp_path, route):
    calls = []
    native = {"tokens_predicted": 7, "tokens_evaluated": 12, "stop_type": "eos", "tokens": [99]}
    body = {"content": "rejected public answer", **native} if route == "/completion" else {
        "choices": [{"message": {"content": "rejected public answer"}}], "__verbose": native,
        "usage": {"prompt_tokens": 12, "completion_tokens": 7}}

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(body).encode()), headers={"private": "DO_NOT_LOG"})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test") as client:
        previous = lambda response: None
        client.event_hooks["response"] = [previous]
        report = {"operations": [{"id": "q1", "state": "attempted"}]}
        capture = m.NativeOutputCapture(SimpleNamespace(_client=client), tmp_path, report)
        with client.stream("POST", route) as response:
            assert json.loads(b"".join(response.iter_bytes())) == body
        capture.restore()
        capture.flush()
        assert client.event_hooks["response"] == [previous]
    row = report["native_output_artifacts"][0]
    assert row["operation_id"] == "q1" and row["observed"]["tokens_predicted"] == 7
    assert (tmp_path / row["path"]).read_text() == "rejected public answer"
    assert "DO_NOT_LOG" not in json.dumps(report) and '"tokens"' not in json.dumps(report)
    assert calls == [route]


def test_capture_cap_does_not_change_stream_or_add_requests(tmp_path):
    payload = b'{"content":"public answer exceeding cap"}'
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=httpx.ByteStream(payload))),
                      base_url="http://test") as client:
        report = {"operations": []}
        capture = m.NativeOutputCapture(SimpleNamespace(_client=client), tmp_path, report)
        capture.per_response = 5
        with client.stream("POST", "/completion") as response:
            assert b"".join(response.iter_bytes()) == payload
        capture.restore()
    assert report["native_output_artifacts"][0]["truncated"] is True
    assert report["native_output_artifacts"][0]["state"] == "unavailable"
    assert not (tmp_path / "native-outputs").exists()


def test_capture_io_failure_does_not_replace_original_response(tmp_path):
    (tmp_path / "native-outputs").write_text("blocked directory fixture")
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=httpx.ByteStream(b'{"content":"public"}'))),
                      base_url="http://test") as client:
        report = {"operations": []}
        capture = m.NativeOutputCapture(SimpleNamespace(_client=client), tmp_path, report)
        with client.stream("POST", "/completion") as response:
            assert json.loads(response.read())["content"] == "public"
        capture.restore()
        capture.flush()
    assert report["native_output_artifacts"][0]["capture_error"] is True


def test_interrupted_capture_preserves_original_error_and_stream_close(tmp_path):
    original_error = httpx.ReadError("DO_NOT_LOG")

    class BrokenStream(httpx.SyncByteStream):
        closes = 0

        def __iter__(self):
            yield b'{"content":"incomplete'
            raise original_error

        def close(self):
            self.closes += 1

    stream = BrokenStream()
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)),
                      base_url="http://test") as client:
        report = {"operations": []}
        capture = m.NativeOutputCapture(SimpleNamespace(_client=client), tmp_path, report)
        with pytest.raises(httpx.ReadError) as caught, client.stream("POST", "/completion") as response:
            response.read()
        capture.restore()
    assert caught.value is original_error and stream.closes == 1
    row = report["native_output_artifacts"][0]
    assert row["state"] == "unavailable" and row["stream_complete"] is False
    assert "observed" not in row and "DO_NOT_LOG" not in json.dumps(report)


def test_restored_capture_does_not_write_after_detached_cleanup(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=httpx.ByteStream(b'{"content":"public"}'))),
                      base_url="http://test") as client:
        report = {"operations": []}
        capture = m.NativeOutputCapture(SimpleNamespace(_client=client), tmp_path, report)
        with client.stream("POST", "/completion") as response:
            capture.restore()
            response.read()
    assert report["native_output_artifacts"][0]["state"] == "unavailable"
    assert not (tmp_path / "native-outputs").exists()


def test_capture_keeps_native_and_chat_content_mismatch_separately(tmp_path):
    body = {"choices": [{"message": {"content": "chat representation"}}],
            "__verbose": {"content": "different native representation", "tokens_predicted": 5}}
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=httpx.ByteStream(json.dumps(body).encode()))),
                      base_url="http://test") as client:
        report = {"operations": []}
        capture = m.NativeOutputCapture(SimpleNamespace(_client=client), tmp_path, report)
        with client.stream("POST", "/v1/chat/completions") as response:
            assert json.loads(response.read()) == body
        assert not (tmp_path / "native-outputs").exists()  # callbacks never write files
        capture.restore()
        capture.flush()
    artifacts = report["native_output_artifacts"][0]["outputs"]
    assert {item["representation"]: (tmp_path / item["path"]).read_text() for item in artifacts} == {
        "message": "chat representation", "native": "different native representation"}


def test_capture_restore_during_finish_prevents_late_publication_and_write(tmp_path, monkeypatch):
    parsing, resume = threading.Event(), threading.Event()
    original_loads = json.loads

    def paused_loads(value, *args, **kwargs):
        if threading.current_thread().name == "capture-race-fixture":
            parsing.set()
            assert resume.wait(2)
        return original_loads(value, *args, **kwargs)

    monkeypatch.setattr(m.json, "loads", paused_loads)
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=httpx.ByteStream(b'{"content":"public"}'))),
                      base_url="http://test") as client:
        report = {"operations": []}
        capture = m.NativeOutputCapture(SimpleNamespace(_client=client), tmp_path, report)
        with client.stream("POST", "/completion") as response:
            worker = threading.Thread(target=response.read, name="capture-race-fixture")
            worker.start()
            try:
                assert parsing.wait(2)
                capture.restore()
            finally:
                resume.set()
                worker.join(2)
            assert not worker.is_alive()
        capture.flush()
    assert capture.pending == []
    assert report["native_output_artifacts"][0]["state"] == "unavailable"
    assert not (tmp_path / "native-outputs").exists()
