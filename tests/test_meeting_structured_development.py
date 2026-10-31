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


def reasoning_options():
    return {"profile": m.REASONING_PROFILE, "qa_only": True, "qa_contract": "requested_facts_v1",
            "externally_supervised": True, "startup_run_id": "a" * 32}


@pytest.mark.parametrize("change", [
    {"qa_only": False}, {"analysis_only": True}, {"qa_contract": "legacy"},
    {"qa_contract": "evidence_plan_v1"}, {"externally_supervised": False},
    {"startup_run_id": None}, {"startup_run_id": "secret/path"},
])
def test_reasoning_rejects_conflicts_before_any_service_or_output(tmp_path, change):
    with pytest.raises(m.DevelopmentError, match="reasoning_requires"):
        m.execute(tmp_path / "missing.jar", "unused", tmp_path / "absent", **(reasoning_options() | change))
    assert not (tmp_path / "absent").exists()


def test_reasoning_envelope_startup_handoff_and_actual_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "ROOT", tmp_path)
    docs, cases = packet()
    for doc in docs:
        doc["raw_sha256"] = hashlib.sha256(doc["content"]).hexdigest()
    monkeypatch.setattr(m, "load_bundle", lambda _: (docs, cases))
    ports = iter([11001, 11002, 11003])
    monkeypatch.setattr(m, "unused_port", lambda: next(ports))
    jar = tmp_path / "fixture.jar"
    jar.write_bytes(b"fixture")
    output, clock = tmp_path / ".local" / "fresh", Clock()
    seen = []

    @contextmanager
    def launch(**kwargs):
        assert kwargs["startup_run_id"] == "a" * 32
        assert kwargs["externally_supervised"] is True
        assert kwargs["startup_marker"] == output / "startup-state.json"
        initial = json.loads((output / "result.json").read_text(encoding="utf-8"))
        assert initial["limits"]["owned_rss_bytes"] == 8 * 1024**3
        assert initial["startup_supervision"]["owner"] == "external"
        kwargs["report"].update(profile=m.REASONING_PROFILE, qa_contract={"name": "requested_facts_v1"})
        clock.now = 119
        yield {"java_url": "http://test", "runtime": SimpleNamespace(set_development_capture=lambda callback: None),
               "generator": SimpleNamespace(profile=m.REASONING_PROFILE,
               _client=SimpleNamespace(event_hooks={"response": []}))}

    def run(*args, **kwargs):
        seen.append((args[5], kwargs["reasoning_qa"], kwargs["qa_only"]))

    monkeypatch.setattr(m, "run_operations", run)
    result = m.execute(jar, hashlib.sha256(b"fixture").hexdigest(), output,
                       **reasoning_options(), launcher=launch, clock=clock)
    assert result["status"] == "completed" and seen == [(449, True, True)]
    assert result["profile"] == m.REASONING_PROFILE and result["mode"] == "qa_only"
    assert result["limits"]["whole_seconds"] == 455 and result["limits"]["external_whole_seconds"] == 490
    assert result["limits"]["requested_output_token_ceiling"] == 2624
    assert result["limits"]["native_completion_ceiling"] == 2 and result["limits"]["auto_analyses"] == 0
    assert result["reasoning_policy"]["reasoning_segment_hard_cap_verified"] is False
    assert (m.LIMITS["whole_seconds"], m.QA_ONLY_LIMITS["whole_seconds"], m.ANALYSIS_ONLY_LIMITS["whole_seconds"]) == (715, 395, 475)


def test_reasoning_two_fixed_qa_windows_share_deadline_and_keep_source_order():
    scenario = QaOnlyScenario()
    original = scenario.handler
    answer_timeouts, questions = [], []

    def handler(request):
        if request.url.path.endswith("/answer"):
            answer_timeouts.append(request.extensions["timeout"]["read"])
            questions.append(json.loads(request.content)["query"])
            scenario.clock.now += 149
        return original(request)

    with (httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test") as client,
          pytest.raises(m.DevelopmentError, match="deadline")):
        m.run_operations(client, scenario.services, *packet(), scenario.report, 280, lambda: None,
                         qa_only=True, reasoning_qa=True, clock=scenario.clock, sleep=scenario.clock.sleep)
    assert scenario.uploads == ["d3", "d1", "d2"] and scenario.answers == 2 and scenario.meetings == 0
    assert answer_timeouts == [150, 131] and questions == [case["question"] for case in packet()[1]]
    assert scenario.report["operations"][1]["state"] == "failed_or_unknown"


def test_reasoning_observation_fresh_idle_terminal_and_safe_split_metrics():
    runtime = SimpleNamespace(last_telemetry={}, lock=threading.Lock())
    generator = SimpleNamespace(profile=m.REASONING_PROFILE, last_call=None)
    services = {"runtime": runtime, "generator": generator}
    before = m.snapshot(services)
    generator.last_call = {"stage": "completed", "output_tokens": 900, "final_retokenized_tokens": 300,
                           "accepted": True, "returned": True, "dispatch_intent": True, "reasoning_content": "SECRET"}
    runtime.last_telemetry = {"service_accepted": True, "cleanup_failed": False, "request_stage": "completed",
        "native_call": generator.last_call, "calls": [{"reasoning_budget_tokens_requested": 512,
        "reasoning_budget_effective_serialized": False, "final_token_measurement": "retokenized_content_not_generated_segment"}]}
    observed = m.observe(services, before)
    assert observed["runtime"]["status"] == "complete"
    assert observed["runtime"]["native_call"]["final_retokenized_tokens"] == 300
    assert "SECRET" not in json.dumps(observed)
    assert m.observe(services, m.snapshot(services))["runtime_state"] == "unknown_or_inflight"
    with runtime.lock:
        assert m.observe(services, before)["runtime_state"] == "unknown_or_inflight"
    runtime.last_telemetry = {**runtime.last_telemetry, "service_accepted": False,
                              "request_stage": "final_validation", "failure_code": "generation_final_content_limit"}
    assert m.observe(services, before)["runtime"]["failure_code"] == "generation_final_content_limit"
    assert m.observe(services, before)["runtime"]["status"] == "failed"


@pytest.mark.parametrize("validated", [True, False])
def test_reasoning_capture_keeps_final_only_never_thinking(tmp_path, validated):
    body = {"choices": [{"message": {"content": '{"status":"abstained"}', "reasoning_content": "SECRET_THINKING"}}],
            "__verbose": {"content": 'SECRET_THINKING</think>{"status":"abstained"}', "tokens_predicted": 900},
            "usage": {"completion_tokens": 900}}
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
            200, stream=httpx.ByteStream(json.dumps(body).encode()))), base_url="http://test") as client:
        report = {"operations": [{"id": "q1", "state": "attempted"}], "limits": m.REASONING_QA_LIMITS}
        call = {"stage": "native_http"}
        generator = SimpleNamespace(_client=client, profile=m.REASONING_PROFILE, last_call=call)
        capture = m.NativeOutputCapture(generator, tmp_path, report)
        assert client.post("/v1/chat/completions").json() == body
        call["stage"] = "final_validation" if validated else "native_validation"
        capture.restore()
        capture.flush()
    row = report["native_output_artifacts"][0]
    if validated:
        assert [output["representation"] for output in row["outputs"]] == ["message"]
        assert (tmp_path / row["path"]).read_text() == '{"status":"abstained"}'
    else:
        assert row["state"] == "unavailable" and not list(tmp_path.rglob("*.txt"))
    assert row["observed"]["completion_tokens"] == 900
    assert "SECRET_THINKING" not in json.dumps(report)
    assert all(b"SECRET_THINKING" not in path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())


def test_reasoning_cli_explicit_profile_and_supervision(monkeypatch):
    seen = []
    monkeypatch.setattr(m, "execute", lambda *args, **kwargs: seen.append(kwargs) or {"status": "completed"})
    monkeypatch.setattr(m.sys, "argv", ["run", "--jar", "fixture.jar", "--jar-sha256", "unused", "--output", "new",
        "--profile", m.REASONING_PROFILE, "--qa-only", "--qa-contract", "requested_facts_v1",
        "--externally-supervised", "--startup-run-id", "a" * 32])
    m.main()
    assert seen[0]["externally_supervised"] and seen[0]["startup_run_id"] == "a" * 32
    assert seen[0]["profile"] == m.REASONING_PROFILE and seen[0]["qa_only"]


def test_reasoning_public_request_capture_drops_native_response_and_keeps_exact_body(tmp_path):
    from doctrail.meeting_reasoning_service import reasoning_body

    body = reasoning_body([{"role": "user", "content": "PUBLIC fixture source and question"}])
    report = {"operations": [{"id": "q1", "state": "attempted"}]}
    generator = SimpleNamespace(profile=m.REASONING_PROFILE, _client=SimpleNamespace(event_hooks={"response": []}))
    capture = m.NativeOutputCapture(generator, tmp_path, report)
    capture.bind_development(SimpleNamespace(set_development_capture=lambda callback: None))
    capture.development_event({"kind": "native_request", "stage": "qa", "body": body})
    capture.development_event({"kind": "native_response", "stage": "qa", "body": {"reasoning_content": "SECRET_THINKING"}})
    capture.restore()
    capture.flush()
    assert len(report["development_artifacts"]) == 1
    saved = tmp_path / report["development_artifacts"][0]["path"]
    assert json.loads(saved.read_text(encoding="utf-8"))["body"] == body
    assert "SECRET_THINKING" not in saved.read_text(encoding="utf-8") + json.dumps(report)


def test_reasoning_unseparated_content_is_never_written_even_with_later_stage(tmp_path):
    body = {"choices": [{"message": {"content": "<think>SECRET_THINKING</think>final"}}]}
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
            200, stream=httpx.ByteStream(json.dumps(body).encode()))), base_url="http://test") as client:
        report = {"operations": [{"id": "q1", "state": "attempted"}]}
        generator = SimpleNamespace(_client=client, profile=m.REASONING_PROFILE, last_call={"stage": "completed"})
        capture = m.NativeOutputCapture(generator, tmp_path, report)
        client.post("/v1/chat/completions")
        capture.restore()
        capture.flush()
    assert not list(tmp_path.rglob("*.txt")) and "SECRET_THINKING" not in json.dumps(report)


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

    def run(self, monkeypatch, deadline=590, *, continue_content_failures=False, qa_only=False, analysis_only=False):
        monkeypatch.setattr(m, "validate_summary_analysis", lambda analysis, content: None)
        with httpx.Client(transport=httpx.MockTransport(self.handler), base_url="http://test") as client:
            m.run_operations(client, self.services, *packet(), self.report, deadline,
                             lambda: self.saves.append(copy.deepcopy(dict(self.report))),
                             continue_content_failures=continue_content_failures, qa_only=qa_only, analysis_only=analysis_only,
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


@pytest.mark.parametrize("profile", m.STRUCTURED_PROFILES)
def test_profile_passed_to_service_and_actual_report_retained(tmp_path, monkeypatch, profile):
    monkeypatch.setattr(m, "ROOT", tmp_path)
    docs, cases = packet()
    for doc in docs:
        doc["raw_sha256"] = hashlib.sha256(doc["content"]).hexdigest()
    monkeypatch.setattr(m, "load_bundle", lambda _: (docs, cases))
    monkeypatch.setattr(m, "run_operations", lambda *args, **kwargs: None)
    ports = iter([11001, 11002, 11003])
    monkeypatch.setattr(m, "unused_port", lambda: next(ports))
    jar = tmp_path / "synthetic.jar"
    jar.write_bytes(b"fixture")
    observed = []

    @contextmanager
    def launcher(**kwargs):
        observed.append(kwargs["profile"])
        kwargs["report"].update(profile=profile, model={"profile": profile, "fixture": True})
        yield {"java_url": "http://test", "generator": SimpleNamespace(_client=SimpleNamespace(event_hooks={"response": []}))}

    report = m.execute(jar, hashlib.sha256(b"fixture").hexdigest(), tmp_path / ".local" / "fresh",
                       profile=profile, launcher=launcher)
    assert observed == [profile]
    assert report["status"] == "completed"
    assert report["requested_profile"] == report["profile"] == report["model"]["profile"] == profile


def test_unknown_profile_rejected_before_input_or_service_side_effects(tmp_path):
    with pytest.raises(m.DevelopmentError, match="unknown_profile"):
        m.execute(tmp_path / "nonexistent.jar", "unused", tmp_path / "output", profile="unsupported")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("selected", [None, m.STRUCTURED_PROFILES[1]])
def test_profile_cli_default_and_explicit_selection(monkeypatch, selected):
    seen = []
    monkeypatch.setattr(m, "execute", lambda *args, **kwargs: seen.append(kwargs["profile"]) or {"status": "completed"})
    argv = ["verifier", "--jar", "fixture.jar", "--jar-sha256", "unused", "--output", ".local/fixture"]
    if selected is not None:
        argv.extend(["--profile", selected])
    monkeypatch.setattr(m.sys, "argv", argv)
    m.main()
    assert seen == [selected or m.PROFILE]


def test_safe_error_observation_preserves_known_nested_codes():
    receipt = {"status": "failed", "failure_code": "generation_conflicting_metadata",
               "last_structured_call": {"error_code": "generation_effective_config_mismatch"},
               "calls": [{"error_code": "generation_invalid_evidence"}]}
    assert m.safe_metrics(receipt) == receipt


def test_safe_error_observation_drops_unknown_and_source_looking_values():
    for value in ("unknown_error", "generation_private_meeting_text", "C:\\private\\source.txt",
                  "token=secret", "회의 원문", {"message": "private"}, None):
        assert m.safe_metrics({"failure_code": value, "error_code": value,
                               "last_structured_call": {"error_code": value}}) == {"last_structured_call": {}}


def test_safe_error_observation_only_attributes_fresh_terminal_failure():
    services = {"runtime": SimpleNamespace(last_telemetry={}), "generator": SimpleNamespace(last_call=None)}
    before = m.snapshot(services)
    services["runtime"].last_telemetry = {"status": "failed", "stage": "metadata",
                                          "failure_code": "generation_conflicting_metadata"}
    assert m.observe(services, before)["runtime"]["failure_code"] == "generation_conflicting_metadata"
    assert m.observe(services, before)["runtime"]["stage"] == "metadata"
    assert m.observe(services, m.snapshot(services))["runtime"] is None


class ContentFailureScenario(Scenario):
    def __init__(self, failure_kind="analysis"):
        super().__init__()
        self.failure_kind = failure_kind
        self.services["runtime"].lock = threading.Lock()

    def receipt(self):
        super().receipt()
        self.services["generator"].last_call.update(returned=True, finish_reason="eos", validation_stage="accepted")

    def handler(self, request):
        failing = (self.failure_kind == "analysis" and request.url.path.endswith("/meetings") and self.meetings == 0
                   or self.failure_kind == "answer" and request.url.path.endswith("/answer") and self.answers == 0)
        self.fail = self.failure_kind if failing else None
        response = super().handler(request)
        if failing:
            self.receipt()
            self.services["runtime"].last_telemetry.update(status="failed", stage="review",
                failure_code="generation_summary_review_rejected")
        return response


def test_content_continuation_default_remains_fail_fast(monkeypatch):
    s = ContentFailureScenario()
    with pytest.raises(m.DevelopmentError, match="analysis_failed"):
        s.run(monkeypatch)
    assert s.meetings == 1 and s.answers == 0
    assert [row["state"] for row in s.report["operations"]][1:] == ["unattempted"] * 3


@pytest.mark.parametrize("kind", ["analysis", "answer"])
def test_content_continuation_optin_preserves_failure_without_retry(monkeypatch, kind):
    s = ContentFailureScenario(kind)
    s.run(monkeypatch, continue_content_failures=True)
    assert s.meetings == s.answers == 2
    assert len(s.report["documents"]) == 3
    failed = [row for row in s.report["operations"] if row["state"] == "failed"]
    assert len(failed) == 1 and failed[0]["kind"] == kind
    assert failed[0]["observation"]["runtime"]["failure_code"] == "generation_summary_review_rejected"
    assert s.report["first_failure"] is not None


@pytest.mark.parametrize("unsafe", ["timeout", "protocol", "settings", "unknown", "busy", "stale", "unaccepted", "no_eos"])
def test_content_continuation_unsafe_failure_halts(monkeypatch, unsafe):
    s = ContentFailureScenario()
    original = s.handler

    def handler(request):
        response = original(request)
        if request.url.path.endswith("/meetings"):
            receipt = s.services["runtime"].last_telemetry
            if unsafe in {"timeout", "protocol", "settings", "unknown"}:
                receipt["failure_code"] = {"timeout": "generation_deadline_exceeded", "protocol": "generation_backend_protocol",
                    "settings": "generation_effective_config_mismatch", "unknown": "generation_arbitrary"}[unsafe]
            elif unsafe == "busy":
                s.services["runtime"].lock.acquire()
            elif unsafe == "stale":
                s.services["runtime"].last_telemetry = s.initial_receipt
            elif unsafe == "unaccepted":
                s.services["generator"].last_call["accepted"] = False
            elif unsafe == "no_eos":
                s.services["generator"].last_call.pop("finish_reason")
        return response

    s.initial_receipt = s.services["runtime"].last_telemetry
    s.handler = handler
    with pytest.raises(m.DevelopmentError):
        s.run(monkeypatch, continue_content_failures=True)
    assert s.meetings == 1 and s.answers == 0
    if s.services["runtime"].lock.locked():
        s.services["runtime"].lock.release()


def test_content_continuation_metadata_requires_completed_classification():
    services = {"runtime": SimpleNamespace(lock=threading.Lock()), "generator": SimpleNamespace(last_call=None)}
    receipt = {"status": "failed", "stage": "metadata", "failure_code": "generation_conflicting_metadata",
               "calls": [{"operation": "grammar_constrained_classification", "completion_calls": 3,
                          "input_tokens": 200, "output_tokens": 3}]}
    observed = {"runtime_state": "terminal", "runtime": receipt, "structured_call": None}
    row = {"kind": "analysis", "analysis_status": "failed"}
    error = m.DevelopmentError("analysis_failed")
    assert m.content_failure_completed(services, observed, row, error)
    receipt["calls"][0]["completion_calls"] = 0
    assert not m.content_failure_completed(services, observed, row, error)
    receipt["calls"][0]["completion_calls"] = 3
    assert not m.content_failure_completed(services, observed, row, httpx.ReadTimeout("private"))


def test_content_continuation_exit_stays_failed_and_cleanup_sees_first_error(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "ROOT", tmp_path)
    docs, cases = packet()
    for doc in docs:
        doc["raw_sha256"] = hashlib.sha256(doc["content"]).hexdigest()
    monkeypatch.setattr(m, "load_bundle", lambda _: (docs, cases))
    ports = iter([11001, 11002, 11003])
    monkeypatch.setattr(m, "unused_port", lambda: next(ports))
    jar = tmp_path / "fixture.jar"
    jar.write_bytes(b"fixture")
    failure = m.DevelopmentError("analysis_failed")
    cleaned = []

    def operations(client, services, documents, cases, report, *args, **kwargs):
        assert kwargs["continue_content_failures"] is True
        report["operations"][0]["state"] = "failed"
        m.record_error(report, failure)

    @contextmanager
    def launcher(**kwargs):
        try:
            yield {"java_url": "http://test", "generator": SimpleNamespace(_client=SimpleNamespace(event_hooks={"response": []}))}
        except m.DevelopmentError as error:
            assert error is failure
            raise
        finally:
            cleaned.append(True)

    monkeypatch.setattr(m, "run_operations", operations)
    report = m.execute(jar, hashlib.sha256(b"fixture").hexdigest(), tmp_path / ".local" / "fresh",
                       continue_content_failures=True, launcher=launcher)
    assert cleaned == [True] and report["status"] == "failed"
    assert report["first_failure"]["code"] == failure.code and report["secondary_failures"] == []


def test_content_continuation_cli_is_explicit(monkeypatch):
    seen = []
    monkeypatch.setattr(m, "execute", lambda *args, **kwargs: seen.append(kwargs["continue_content_failures"]) or {"status": "completed"})
    args = ["verifier", "--jar", "fixture", "--jar-sha256", "unused", "--output", ".local/fixture"]
    monkeypatch.setattr(m.sys, "argv", args)
    m.main()
    monkeypatch.setattr(m.sys, "argv", [*args, "--continue-content-failures"])
    m.main()
    assert seen == [False, True]


def test_metadata_warning_receipts_are_finite_bounded_and_text_free():
    warning = {"field": "meeting_date", "unit_index": 7, "reason": "ambiguous_source_value", "value": "private"}
    receipt = {"metadata_policy": "literal_optional_v1", "metadata_warnings": [warning] * 161}
    safe = m.safe_metrics(receipt)
    assert safe["metadata_policy"] == "literal_optional_v1" and len(safe["metadata_warnings"]) == 160
    assert "private" not in json.dumps(safe)
    for bad in ({**warning, "unit_index": True}, {**warning, "unit_index": 160},
                {**warning, "field": "private"}, {**warning, "reason": "source text"}):
        assert m.safe_metrics({"metadata_warnings": [bad]}) == {"metadata_warnings": []}
    assert m.safe_metrics({"metadata_policy": "unrecognized"}) == {}


class QaOnlyScenario(Scenario):
    def __init__(self, fail=None):
        super().__init__(fail=fail)
        self.uploads = []

    def receipt(self):
        super().receipt()
        self.services["runtime"].last_telemetry["calls"][0]["operation"] = "qa"
        self.services["generator"].last_call.update(operation="meeting_qa", input_tokens=123)

    def handler(self, request):
        if request.url.path.endswith("/documents"):
            identity = ["d3", "d1", "d2"][len(self.uploads)]
            self.uploads.append(identity)
            self.calls.append((request.method, request.url.path))
            assert f'filename="{identity}.md"'.encode() in request.content
            assert f"source {identity[1:]}".encode() in request.content
            assert b"source text" in request.content
            return httpx.Response(201, json=document(identity))
        return super().handler(request)


def test_qa_only_exact_ordinary_upload_order_and_two_unchanged_questions(monkeypatch):
    s = QaOnlyScenario()
    original = s.handler
    questions = []

    def handler(request):
        if request.url.path.endswith("/answer"):
            questions.append(json.loads(request.content)["query"])
        return original(request)

    s.handler = handler
    s.run(monkeypatch, deadline=270, qa_only=True)
    assert s.uploads == ["d3", "d1", "d2"]
    assert s.meetings == 0 and s.answers == 2
    assert questions == [case["question"] for case in packet()[1]]
    assert [path.rsplit("/", 1)[-1] for _, path in s.calls] == [
        "register", "documents", "documents", "documents", "answer", "answer"]
    assert all(row["kind"] == "answer" and row["state"] == "complete" for row in s.report["operations"])
    assert [row["source_id"] for row in s.report["setup"]["document_bindings"]] == s.uploads
    assert all(row["observation"]["structured_call"]["input_tokens"] == 123 for row in s.report["operations"])


def test_qa_only_first_answer_failure_preserves_second_unattempted(monkeypatch):
    s = QaOnlyScenario(fail="answer")
    with pytest.raises(m.DevelopmentError, match="http_failed"):
        s.run(monkeypatch, deadline=270, qa_only=True)
    assert s.meetings == 0 and s.answers == 1 and len(s.uploads) == 3
    assert [row["state"] for row in s.report["operations"]] == ["failed_or_unknown", "unattempted"]


def test_qa_only_all_three_uploads_share_setup_deadline(monkeypatch):
    s = QaOnlyScenario()
    original = s.handler

    def handler(request):
        response = original(request)
        if request.url.path.endswith("/documents"):
            s.clock.now += 15
        return response

    s.handler = handler
    with pytest.raises(m.DevelopmentError, match="deadline"):
        s.run(monkeypatch, deadline=270, qa_only=True)
    assert s.uploads == ["d3", "d1"] and s.answers == 0 and s.meetings == 0
    assert all(row["state"] == "unattempted" for row in s.report["operations"])


@pytest.mark.parametrize("qa_only,active,total,external,native,operations", [
    (False, 590, 715, 750, 326, 4), (True, 270, 395, 430, 2, 2)])
def test_qa_only_execute_envelope_and_actual_contract_report(tmp_path, monkeypatch, qa_only, active, total, external, native, operations):
    monkeypatch.setattr(m, "ROOT", tmp_path)
    docs, cases = packet()
    for doc in docs:
        doc["raw_sha256"] = hashlib.sha256(doc["content"]).hexdigest()
    monkeypatch.setattr(m, "load_bundle", lambda _: (docs, cases))
    ports = iter([11001, 11002, 11003])
    monkeypatch.setattr(m, "unused_port", lambda: next(ports))
    jar = tmp_path / "fixture.jar"
    jar.write_bytes(b"fixture")
    clock = Clock()
    selected = "requested_facts_v1" if qa_only else m.LEGACY_QA_CONTRACT
    observed = []

    @contextmanager
    def launcher(**kwargs):
        assert kwargs["qa_contract"] == selected
        kwargs["report"].update(profile=m.PROFILE, qa_contract={"name": selected, "prompt_sha256": "fixture-hash"})
        clock.now = 119
        yield {"java_url": "http://test", "generator": SimpleNamespace(_client=SimpleNamespace(event_hooks={"response": []}))}

    def run(client, services, documents, cases, report, deadline, save, **kwargs):
        observed.append((deadline, kwargs["qa_only"]))

    monkeypatch.setattr(m, "run_operations", run)
    report = m.execute(jar, hashlib.sha256(b"fixture").hexdigest(), tmp_path / ".local" / "fresh",
                       qa_only=qa_only, qa_contract=selected, launcher=launcher, clock=clock)
    assert report["status"] == "completed" and observed == [(119 + active, qa_only)]
    assert report["limits"]["whole_seconds"] == total
    assert report["limits"]["external_whole_seconds"] == external
    assert report["limits"]["native_completion_ceiling"] == native
    assert len(report["operations"]) == operations
    assert report["qa_contract"] == {"name": selected, "prompt_sha256": "fixture-hash"}
    assert report["requested_qa_contract"] == selected
    if qa_only:
        assert report["limits"]["auto_analyses"] == 0
        assert report["limits"]["requested_output_token_ceiling"] == 1536
        assert report["context_comparison"]["exact_prior_context_binding_proven"] is False


def test_qa_only_unknown_contract_rejected_before_side_effects(tmp_path):
    with pytest.raises(m.DevelopmentError, match="unknown_qa_contract"):
        m.execute(tmp_path / "missing.jar", "unused", tmp_path / "output", qa_only=True, qa_contract="unsupported")
    assert not (tmp_path / "output").exists()


def test_qa_only_cli_contract_selection_is_explicit_and_default_unchanged(monkeypatch):
    seen = []
    monkeypatch.setattr(m, "execute", lambda *args, **kwargs: seen.append(kwargs) or {"status": "completed"})
    args = ["verifier", "--jar", "fixture", "--jar-sha256", "unused", "--output", ".local/fixture"]
    monkeypatch.setattr(m.sys, "argv", args)
    m.main()
    monkeypatch.setattr(m.sys, "argv", [*args, "--qa-only", "--qa-contract", "requested_facts_v1"])
    m.main()
    assert [(row["qa_only"], row["qa_contract"]) for row in seen] == [(False, "legacy"), (True, "requested_facts_v1")]


def test_qa_only_capture_honors_two_completion_ceiling(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=httpx.ByteStream(b'{"content":"public"}'))),
                      base_url="http://test") as client:
        report = {"operations": [], "limits": m.QA_ONLY_LIMITS}
        capture = m.NativeOutputCapture(SimpleNamespace(_client=client), tmp_path, report)
        for _ in range(3):  # synthetic observer boundary only, never an application request plan
            with client.stream("POST", "/completion") as response:
                response.read()
        capture.restore()
        capture.flush()
    assert len(report["native_output_artifacts"]) == 2 and report["native_capture_call_overflow"] is True


def test_qa_only_content_continuation_still_stops_after_two_answers(monkeypatch):
    s = QaOnlyScenario()
    s.services["runtime"].lock = threading.Lock()
    original = s.handler

    def handler(request):
        failing = request.url.path.endswith("/answer") and s.answers == 0
        s.fail = "answer" if failing else None
        response = original(request)
        if failing:
            s.receipt()
            s.services["runtime"].last_telemetry.update(status="failed", stage="qa",
                                                      failure_code="generation_invalid_evidence")
            s.services["generator"].last_call.update(returned=True, finish_reason="eos", validation_stage="accepted")
        return response

    s.handler = handler
    s.run(monkeypatch, deadline=270, qa_only=True, continue_content_failures=True)
    assert s.meetings == 0 and s.answers == 2 and s.uploads == ["d3", "d1", "d2"]
    assert [row["state"] for row in s.report["operations"]] == ["failed", "complete"]
    assert s.report["first_failure"] is not None


class DevelopmentRuntimeFixture:
    def __init__(self):
        self.callback = None
        self.bindings = []

    def set_development_capture(self, callback):
        self.callback = callback
        self.bindings.append(callback)


def development_capture(tmp_path):
    runtime = DevelopmentRuntimeFixture()
    generator = SimpleNamespace(_client=SimpleNamespace(event_hooks={"response": []}))
    report = {"operations": [{"kind": "answer", "id": "q1", "state": "attempted"}],
              "limits": m.EVIDENCE_PLAN_LIMITS}
    capture = m.NativeOutputCapture(generator, tmp_path, report)
    capture.bind_development(runtime)
    return runtime, capture, report


def test_evidence_plan_development_capture_preserves_exact_payloads_privately(tmp_path):
    runtime, capture, report = development_capture(tmp_path)
    body = {"messages": [{"role": "system", "content": "Generic planner"},
                         {"role": "user", "content": "Which date is stated? 원문"}],
            "model": "public-model-id", "max_tokens": 192, "n_predict": 192,
            "response_format": {"type": "json_schema", "json_schema": {"name": "qa_obligation_plan", "strict": True,
                                                                        "schema": {"type": "object"}}}}
    events = [{"kind": "native_request", "stage": "qa_obligation_plan", "body": body},
              {"kind": "accepted_plan", "plan": {"obligations": [{"id": 0, "fact_kind": "event"}]}},
              {"kind": "compiled_ledger", "ledger": {"rows": []}, "result": {"status": "abstained", "claims": []}}]
    for event in events:
        runtime.callback(event)
    assert not (tmp_path / "development-traces").exists()
    capture.restore()
    capture.flush()
    assert runtime.callback is None
    assert [json.loads((tmp_path / row["path"]).read_text(encoding="utf-8")) for row in report["development_artifacts"]] == events
    assert all(row["operation_id"] == "q1" for row in report["development_artifacts"])
    assert report["development_artifacts"][0]["request_body_sha256"] == hashlib.sha256(
        json.dumps(body, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    assert "Which date" not in json.dumps(report) and "Generic planner" not in json.dumps(report)


def test_evidence_plan_development_capture_rejects_auth_and_bounds_event_bytes(tmp_path):
    runtime, capture, report = development_capture(tmp_path)
    runtime.callback({"kind": "native_request", "stage": "qa_obligation_plan", "body": {"headers": {"Authorization": "secret"}}})
    assert report["development_capture_error"] is True and report["development_artifacts"] == []
    runtime.callback({"kind": "accepted_plan", "plan": {"oversized": "x" * (2 * 1024 * 1024)}})
    capture.restore()
    capture.flush()
    assert report["development_artifacts"][0]["truncated"] is True
    assert not (tmp_path / "development-traces").exists()
    assert "secret" not in json.dumps(report)


def test_evidence_plan_capture_max_eight_events_and_no_post_restore_writes(tmp_path):
    runtime, capture, report = development_capture(tmp_path)
    callback = runtime.callback
    event = {"kind": "accepted_plan", "plan": {"obligations": []}}
    for _ in range(9):
        callback(event)
    assert len(report["development_artifacts"]) == 8 and report["development_capture_overflow"] is True
    capture.restore()
    callback(event)
    capture.flush()
    assert len(list((tmp_path / "development-traces").iterdir())) == 8


def test_evidence_plan_capture_restore_during_serialization_blocks_late_publication(tmp_path, monkeypatch):
    runtime, capture, report = development_capture(tmp_path)
    entered, resume = threading.Event(), threading.Event()
    original = json.dumps

    def paused(value, *args, **kwargs):
        if threading.current_thread().name == "development-capture-race":
            entered.set()
            assert resume.wait(2)
        return original(value, *args, **kwargs)

    monkeypatch.setattr(m.json, "dumps", paused)
    worker = threading.Thread(target=runtime.callback, args=({"kind": "accepted_plan", "plan": {}},),
                              name="development-capture-race")
    worker.start()
    try:
        assert entered.wait(2)
        capture.restore()
    finally:
        resume.set()
        worker.join(2)
    assert not worker.is_alive()
    capture.flush()
    assert report["development_artifacts"] == [] and not (tmp_path / "development-traces").exists()


def test_evidence_plan_capture_io_failure_is_safe(tmp_path):
    runtime, capture, report = development_capture(tmp_path)
    (tmp_path / "development-traces").write_text("fixture")
    runtime.callback({"kind": "accepted_plan", "plan": {"obligations": []}})
    capture.restore()
    capture.flush()
    assert report["development_artifacts"][0]["capture_error"] is True
    assert report["development_artifacts"][0]["state"] == "unavailable"


@pytest.mark.parametrize("contract", m.EVIDENCE_PLAN_QA_CONTRACTS)
def test_evidence_plan_full_flow_rejected_before_side_effects(tmp_path, contract):
    with pytest.raises(m.DevelopmentError, match="evidence_plan_requires_qa_only"):
        m.execute(tmp_path / "missing.jar", "unused", tmp_path / "output", qa_contract=contract)
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("contract", m.EVIDENCE_PLAN_QA_CONTRACTS)
def test_evidence_plan_mode_budget_hook_and_old_limits_unchanged(tmp_path, monkeypatch, contract):
    monkeypatch.setattr(m, "ROOT", tmp_path)
    docs, cases = packet()
    for doc in docs:
        doc["raw_sha256"] = hashlib.sha256(doc["content"]).hexdigest()
    monkeypatch.setattr(m, "load_bundle", lambda _: (docs, cases))
    ports = iter([11001, 11002, 11003])
    monkeypatch.setattr(m, "unused_port", lambda: next(ports))
    jar = tmp_path / "fixture.jar"
    jar.write_bytes(b"fixture")
    runtime = DevelopmentRuntimeFixture()

    @contextmanager
    def launcher(**kwargs):
        assert kwargs["qa_contract"] == contract
        kwargs["report"]["qa_contract"] = {"name": contract}
        yield {"java_url": "http://test", "runtime": runtime,
               "generator": SimpleNamespace(_client=SimpleNamespace(event_hooks={"response": []}))}

    def run(client, services, documents, cases, report, deadline, save, **kwargs):
        assert kwargs["qa_only"] is True and runtime.callback is not None
        report["operations"][0]["state"] = "attempted"
        runtime.callback({"kind": "accepted_plan", "plan": {"obligations": []}})

    monkeypatch.setattr(m, "run_operations", run)
    report = m.execute(jar, hashlib.sha256(b"fixture").hexdigest(), tmp_path / ".local" / "fresh",
                       qa_only=True, qa_contract=contract, launcher=launcher)
    assert report["status"] == "completed" and runtime.callback is None
    assert report["limits"]["native_completion_ceiling"] == 4
    assert report["limits"]["plan_output_tokens"] + report["limits"]["ledger_output_tokens"] == 768
    assert report["limits"]["requested_output_token_ceiling"] == 1536
    assert report["limits"]["whole_seconds"] == 395 and report["limits"]["external_whole_seconds"] == 430
    assert len(report["operations"]) == 2 and report["limits"]["auto_analyses"] == 0
    assert report["development_artifacts"][0]["state"] == "captured"
    assert m.QA_ONLY_LIMITS["native_completion_ceiling"] == 2 and m.LIMITS["native_completion_ceiling"] == 326


@pytest.mark.parametrize("stage", ["qa_obligation_plan", "qa_evidence_ledger"])
def test_evidence_plan_malformed_stage_never_content_continues(stage):
    services = {"runtime": SimpleNamespace(lock=threading.Lock()), "generator": SimpleNamespace(last_call=None)}
    observed = {"runtime_state": "terminal", "runtime": {"status": "failed", "stage": stage,
                 "failure_code": "generation_invalid_schema"}, "structured_call_fresh": True,
                "structured_call": {"dispatched": True, "returned": True, "accepted": True,
                                    "finish_reason": "eos", "validation_stage": "accepted"}}
    assert not m.content_failure_completed(services, observed, {"kind": "answer", "last_http_status": 503},
                                          m.DevelopmentError("http_failed"))
    safe = m.safe_metrics({"stage": stage, "calls": [{"operation": stage, "output_cap": 192, "finish_reason": "eos"}]})
    assert safe["stage"] == stage and safe["calls"][0]["operation"] == stage


class AgendaScenario(Scenario):
    def receipt(self):
        super().receipt()
        self.services["runtime"].last_telemetry.update(stage="agenda_assembly", calls=[
            {"operation": "agenda_extraction", "input_tokens": 77, "output_tokens": 25, "output_cap": 768,
             "finish_reason": "eos"}, {"review_performed": False, "analysis_mode": "agenda_extraction_v1"}])
        self.services["generator"].last_call.update(operation="agenda_extraction", returned=True,
                                                    finish_reason="eos", validation_stage="accepted")


def test_analysis_only_two_original_meetings_and_no_qa_or_general_upload(monkeypatch):
    s = AgendaScenario()
    s.run(monkeypatch, deadline=350, analysis_only=True)
    assert s.meetings == 2 and s.answers == 0
    assert [path.rsplit("/", 1)[-1] for _, path in s.calls] == ["register", "meetings", "meetings"]
    assert [row["id"] for row in s.report["operations"]] == ["d1", "d2"]
    assert [doc["id"] for doc in s.report["documents"]] == ["d1", "d2"]
    assert s.report["setup"]["document_bindings"] == []
    assert all(row["result"]["meeting"]["ai_analysis"] == {"fixture": True} for row in s.report["operations"])
    assert all(row["observation"]["runtime"]["calls"][0]["input_tokens"] == 77 for row in s.report["operations"])
    assert all(row["observation"]["runtime"]["calls"][1]["review_performed"] is False for row in s.report["operations"])


def test_analysis_only_poll_deadline_and_source_mismatch_halt(monkeypatch):
    queued = AgendaScenario(queued=True)
    with pytest.raises(m.DevelopmentError, match="deadline"):
        queued.run(monkeypatch, deadline=350, analysis_only=True)
    assert queued.clock.now == pytest.approx(160) and queued.meetings == 1 and queued.answers == 0
    assert queued.report["operations"][1]["state"] == "unattempted"
    changed = AgendaScenario()
    original = changed.handler

    def handler(request):
        response = original(request)
        if request.url.path.endswith("/meetings"):
            body = response.json()
            body["document"]["content"] = "changed source"
            return httpx.Response(response.status_code, json=body)
        return response

    changed.handler = handler
    with pytest.raises(m.DevelopmentError, match="document_binding"):
        changed.run(monkeypatch, deadline=350, analysis_only=True)
    assert changed.meetings == 1 and changed.answers == 0


@pytest.mark.parametrize("failure,continues", [("generation_summary_insufficient", True),
                                              ("generation_invalid_evidence", False)])
def test_analysis_only_content_continuation_keeps_technical_errors_fail_stop(monkeypatch, failure, continues):
    s = AgendaScenario()
    s.services["runtime"].lock = threading.Lock()
    original = s.handler

    def handler(request):
        failing = request.url.path.endswith("/meetings") and s.meetings == 0
        s.fail = "analysis" if failing else None
        response = original(request)
        if failing:
            s.services["runtime"].last_telemetry.update(status="failed", failure_code=failure)
        return response

    s.handler = handler
    if continues:
        s.run(monkeypatch, deadline=350, analysis_only=True, continue_content_failures=True)
        assert [row["state"] for row in s.report["operations"]] == ["failed", "complete"]
        assert s.report["first_failure"] is not None
    else:
        with pytest.raises(m.DevelopmentError):
            s.run(monkeypatch, deadline=350, analysis_only=True, continue_content_failures=True)
        assert s.meetings == 1 and s.report["operations"][1]["state"] == "unattempted"
    assert s.answers == 0


@pytest.mark.parametrize("options", [
    {"analysis_only": True, "qa_only": True}, {"analysis_only": True},
    {"analysis_only": True, "analysis_contract": "agenda_extraction_v1", "qa_contract": "requested_facts_v1"},
    {"analysis_contract": "agenda_extraction_v1"}, {"analysis_contract": "unknown"}])
def test_analysis_only_invalid_mode_contracts_reject_before_side_effects(tmp_path, options):
    with pytest.raises(m.DevelopmentError):
        m.execute(tmp_path / "missing.jar", "unused", tmp_path / "output", **options)
    assert not (tmp_path / "output").exists()


def test_analysis_only_execute_tighter_envelope_and_actual_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "ROOT", tmp_path)
    docs, cases = packet()
    for doc in docs:
        doc["raw_sha256"] = hashlib.sha256(doc["content"]).hexdigest()
    monkeypatch.setattr(m, "load_bundle", lambda _: (docs, cases))
    ports = iter([11001, 11002, 11003])
    monkeypatch.setattr(m, "unused_port", lambda: next(ports))
    jar = tmp_path / "fixture.jar"
    jar.write_bytes(b"fixture")
    clock, runtime = Clock(), DevelopmentRuntimeFixture()
    observed = []

    @contextmanager
    def launcher(**kwargs):
        assert kwargs["analysis_contract"] == m.AGENDA_ANALYSIS_CONTRACT
        kwargs["report"]["analysis_contract"] = {"name": m.AGENDA_ANALYSIS_CONTRACT, "review_performed": False}
        clock.now = 119
        yield {"java_url": "http://test", "runtime": runtime,
               "generator": SimpleNamespace(_client=SimpleNamespace(event_hooks={"response": []}))}

    def run(client, services, documents, cases, report, deadline, save, **kwargs):
        observed.append((deadline, kwargs["analysis_only"], kwargs["qa_only"]))
        report["operations"][0]["state"] = "attempted"
        runtime.callback({"kind": "native_request", "stage": "agenda_extraction", "body": {"messages": []}})

    monkeypatch.setattr(m, "run_operations", run)
    output = tmp_path / ".local" / "fresh"
    report = m.execute(jar, hashlib.sha256(b"fixture").hexdigest(), output, analysis_only=True,
                       analysis_contract=m.AGENDA_ANALYSIS_CONTRACT, launcher=launcher, clock=clock)
    assert report["status"] == "completed" and observed == [(469, True, False)]
    assert report["mode"] == "analysis_only" and report["cases"] == []
    assert len(report["operations"]) == 2 and report["limits"]["answer_requests"] == 0
    assert report["limits"]["whole_seconds"] == 120 + 30 + 2 * 160 + 5 == 475
    assert report["limits"]["external_whole_seconds"] == 510
    assert report["limits"]["native_completion_ceiling"] == 2
    assert report["limits"]["requested_output_token_ceiling"] == 1536
    assert [doc["document_id"] for doc in report["sources"]] == ["d1", "d2"]
    assert (output / "d1.txt").read_bytes() == docs[0]["content"] and not (output / "d3.txt").exists()
    assert report["analysis_contract"]["review_performed"] is False and runtime.callback is None
    assert report["development_artifacts"][0]["stage"] == "agenda_extraction"
    assert m.LIMITS["whole_seconds"] == 715 and m.QA_ONLY_LIMITS["whole_seconds"] == 395


def test_analysis_only_cli_is_explicit_and_modes_conflict(monkeypatch):
    seen = []
    monkeypatch.setattr(m, "execute", lambda *args, **kwargs: seen.append(kwargs) or {"status": "completed"})
    args = ["verifier", "--jar", "fixture", "--jar-sha256", "unused", "--output", ".local/fixture"]
    monkeypatch.setattr(m.sys, "argv", args)
    m.main()
    monkeypatch.setattr(m.sys, "argv", [*args, "--analysis-only", "--analysis-contract", "agenda_extraction_v1"])
    m.main()
    assert [(row["analysis_only"], row["analysis_contract"]) for row in seen] == [(False, "legacy"), (True, "agenda_extraction_v1")]
    monkeypatch.setattr(m.sys, "argv", [*args, "--analysis-only", "--qa-only"])
    with pytest.raises(SystemExit) as error:
        m.main()
    assert error.value.code == 2 and len(seen) == 2


def test_analysis_only_safe_diagnostics_keep_only_finite_range_fields():
    value = {"analysis_mode": "agenda_extraction_v1", "review_performed": False,
             "item_field_policy": "terminal_task_and_enclosing_action_owner_v1",
             "item_ranges_including_intervening_units": [{"item_index": 0, "first_unit": 2, "last_unit": 4, "text": "private"},
                                                         {"item_index": True, "first_unit": 1, "last_unit": 3}]}
    safe = m.safe_metrics(value)
    assert safe["item_ranges_including_intervening_units"] == [{"item_index": 0, "first_unit": 2, "last_unit": 4}]
    assert safe["review_performed"] is False and "private" not in json.dumps(safe)
