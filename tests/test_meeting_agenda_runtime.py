"""Synthetic one-call integration and failure lifecycle; no native/model calls."""
import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from doctrail import meeting_agenda_runtime as m
from doctrail import meeting_structured as base
from doctrail.inference import WorkerError
from doctrail.meeting_contract import AnalyzeRequest, AnswerRequest, Context
from doctrail.meeting_gguf import GGUFResult

SOURCE = ("회의 제목: 도서관 계획\nDate: 2028-05-02\n## Catalogue\n"
          "- Proposal: consider a shared index.\n- Action Items (Mira)\n  - Prepare a prototype.\n")


def request():
    return AnalyzeRequest(schema_version=1, document_id="fixture", revision=3,
                          title="도서관 계획", content=SOURCE)


def response():
    return {"status": "complete", "claims": [
        {"text": "공유 색인은 제안 단계이며 시제품 준비 작업이 있다.", "evidence": [[3, 3], [4, 5]]}],
        "items": [[3, 3, "proposal", None, None, None], [4, 5, "action", "Mira", None, None]],
        "metadata": [[0, "meeting_title"], [1, "meeting_date"], [3, "purpose"]]}


class Generator:
    last_effective_config = last_call = None
    profile = "synthetic-profile"
    def __init__(self):
        self.calls, self.deadlines = [], []
        self.count, self.output_tokens, self.finish = 6144, 768, "eos"
        self.data, self.fail_end = response(), False
        self.after_count = self.after_generation = lambda: None
    def public_metadata(self):
        return {"repo_id": "synthetic-model", "revision": "fixture-revision",
                "structured_output": {"review": "same_model_not_independent"}}
    def begin_request(self, deadline):
        self.deadlines.append(deadline)
        self.calls.append("begin")
    def end_request(self):
        self.calls.append("end")
        if self.fail_end:
            raise RuntimeError("private cleanup text")
    def count_structured_tokens(self, messages, name, schema, cap):
        self.calls.append(("count", copy.deepcopy(messages), name, schema, cap))
        self.after_count()
        return self.count
    def structured(self, messages, deadline, name, schema, cap):
        self.calls.append(("structured", copy.deepcopy(messages), name, schema, cap))
        self.deadlines.append(deadline)
        self.last_call = {"operation": name, "dispatched": True, "returned": True, "accepted": True}
        self.after_generation()
        return GGUFResult(json.dumps(self.data, ensure_ascii=False), self.finish,
                          self.count, self.output_tokens, .25, {})
    def generate_bounded(self, messages, deadline):
        self.calls.append(("legacy_qa", copy.deepcopy(messages)))
        self.deadlines.append(deadline)
        return GGUFResult('{"status":"abstained","claims":[]}', "eos", 100, 10, .1, {})


def test_agenda_one_call_complete_source_exact_spans_metadata_and_no_self_review():
    generator = Generator()
    runtime = m.AgendaMeetingRuntime(generator)
    result = runtime.analyze(request())
    calls = [c for c in generator.calls if isinstance(c, tuple)]
    assert [c[0] for c in calls] == ["structured"]
    assert calls[0][2:] == ("agenda_extraction", m.agenda.SCHEMA, 768)
    body = json.loads(calls[0][1][1]["content"])
    assert "".join(part["text"] for part in body["source_parts"]) == SOURCE
    assert len(set(generator.deadlines)) == 1
    assert result["model"] == "synthetic-model" and result["revision"] == "fixture-revision"
    action = result["analysis"]["items"][1]
    assert action["assignee"] == "Mira" and action["status"] == "needs_confirmation"
    assert action["quote"] == SOURCE[action["start_offset"]:action["end_offset"]]
    assert result["summary_review"] == {"performed": False, "status": "not_performed",
                                        "semantic_quality_accepted": False}
    metrics, diagnostic = result["telemetry"]["calls"]
    assert metrics["completion_calls"] == 1 and metrics["output_tokens"] == metrics["output_cap"] == 768
    assert diagnostic["review_performed"] is False and diagnostic["metadata_warnings"][0]["field"] == "purpose"
    assert "Mira" not in json.dumps(result["telemetry"])
    assert result["analysis_contract"]["native_calls_per_analysis"] == 1
    health = runtime.health()
    assert health["analysis_contract"] == result["analysis_contract"]
    assert health["runtime"]["structured_output"]["review"] == "not_performed_for_agenda_extraction_v1"
    assert generator.public_metadata()["structured_output"]["review"] == "same_model_not_independent"
    assert generator.calls[-1] == "end" and not runtime.lock.locked()


@pytest.mark.parametrize("failure,code,native_calls", [
    ("length", "generation_output_truncated", 1),
    ("output_cap", "generation_output_truncated", 1), ("abstained", "generation_summary_insufficient", 1),
    ("malformed", "generation_invalid_evidence", 1), ("unsupported_owner", "generation_unsupported_field", 1)])
def test_agenda_failure_has_no_retry_no_partial_publication_and_preserves_first_error(failure, code, native_calls):
    generator = Generator()
    generator.fail_end = True
    if failure == "length":
        generator.finish = "length"
    elif failure == "output_cap":
        generator.output_tokens = 769
    elif failure == "abstained":
        generator.data = {"status": "abstained", "claims": [], "items": [], "metadata": []}
    elif failure == "malformed":
        generator.data["claims"][0]["evidence"] = [[99, 99]]
    else:
        generator.data["items"][1][3] = "invented"
    runtime = m.AgendaMeetingRuntime(generator)
    with pytest.raises(WorkerError) as error:
        runtime.analyze(request())
    assert error.value.code == code
    assert len([c for c in generator.calls if isinstance(c, tuple) and c[0] == "structured"]) == native_calls
    assert runtime.last_telemetry["failure_code"] == code
    assert len(runtime.last_telemetry["calls"]) == native_calls
    assert not runtime.lock.locked() and generator.calls[-1] == "end"


@pytest.mark.parametrize("phase", ["view", "generation"])
def test_agenda_same_deadline_includes_preflight_generation_and_cleanup(phase, monkeypatch):
    now = [0.0]
    clock = SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(m, "time", clock)
    monkeypatch.setattr(base, "time", clock)
    generator = Generator()
    if phase == "view":
        original = m.agenda.build_view
        def expired_view(*args):
            result = original(*args)
            now[0] = 121.0
            return result
        monkeypatch.setattr(m.agenda, "build_view", expired_view)
    else:
        generator.after_generation = lambda: now.__setitem__(0, 121.0)
    runtime = m.AgendaMeetingRuntime(generator)
    with pytest.raises(WorkerError, match="generation_deadline_exceeded"):
        runtime.analyze(request())
    assert len(set(generator.deadlines)) == 1 and generator.deadlines[0] == 120.0
    assert len(runtime.last_telemetry["calls"]) == (0 if phase == "view" else 1)
    assert not runtime.lock.locked()


def test_agenda_inherits_exact_answer_path_and_shared_busy_lock():
    generator = Generator()
    generator.count = 100
    runtime = m.AgendaMeetingRuntime(generator)
    assert m.AgendaMeetingRuntime.answer is base.StructuredMeetingRuntime.answer
    runtime.lock.acquire()
    with pytest.raises(WorkerError, match="model_busy"):
        runtime.analyze(request())
    assert not generator.calls
    runtime.lock.release()
    text = "Only a proposal is recorded."
    answer = AnswerRequest(schema_version=1, query="Was a decision made?", contexts=[Context(
        document_id="fixture", revision=1, chunk_id="chunk", title="Synthetic", page=None,
        meeting_date=None, start_offset=0, end_offset=len(text), text=text)])
    result = runtime.answer(answer)
    sources, _ = base.answer_evidence(answer.contexts)
    assert result["status"] == "abstained"
    qa_calls = [call for call in generator.calls if isinstance(call, tuple) and call[0] == "legacy_qa"]
    assert qa_calls == [("legacy_qa", base.answer_messages({"question": answer.query, "sources": sources}))]


def test_agenda_delegated_overcap_records_exact_count_body_without_completion_dispatch():
    requests, captured = [], []
    def handle(http_request):
        body = json.loads(http_request.content)
        requests.append((http_request.url.path, body))
        if http_request.url.path == "/apply-template":
            return httpx.Response(200, json={"prompt": "synthetic prepared template"})
        assert http_request.url.path == "/v1/chat/completions/input_tokens"
        return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 6145})
    generator = base.StructuredGenerator("http://127.0.0.1:19003", "x" * 48, "unused-fixture",
                                         transport=httpx.MockTransport(handle))
    generator._alias = "synthetic-alias"
    generator._metadata = {"repo_id": "synthetic-model", "revision": "fixture", "runtime": {}}
    runtime = m.AgendaMeetingRuntime(generator)
    runtime.set_development_capture(captured.append)
    try:
        with pytest.raises(WorkerError, match="generation_input_limit") as error:
            runtime.analyze(request())
        assert error.value.status == 422
        assert [path for path, _ in requests] == ["/apply-template", "/v1/chat/completions/input_tokens"]
        assert len(captured) == 1 and captured[0]["stage"] == "agenda_extraction"
        assert captured[0]["body"] == requests[0][1] == requests[1][1]
        payload = json.loads(captured[0]["body"]["messages"][1]["content"])
        assert "".join(part["text"] for part in payload["source_parts"]) == SOURCE
        metrics = runtime.last_telemetry
        assert metrics["failure_code"] == "generation_input_limit" and metrics["calls"] == []
        observed = metrics["last_structured_call"]
        assert observed["input_tokens"] == 6145 and observed["input_cap"] == 6144
        assert observed["dispatched"] is False and observed["error_code"] == "generation_input_limit"
        assert not runtime.lock.locked() and generator._deadline is None
        assert SOURCE not in json.dumps(metrics, ensure_ascii=False)
    finally:
        runtime.set_development_capture(None)
        generator.close()
