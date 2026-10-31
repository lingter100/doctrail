"""Synthetic transport and request lifecycle only; no model or saved QA replay."""
import copy
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from doctrail import meeting_structured as m
from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_contract import AnalyzeRequest, AnswerRequest, Context
from doctrail.meeting_gguf import GGUFGenerator, GGUFResult


class Native:
    def __init__(self):
        self.requests, self.prompts, self.inputs = [], {}, 30
        self.text = '{"status":"abstained","claims":[]}'
        self.change = lambda value: value
        self.generator = m.StructuredGenerator("http://127.0.0.1:19003", "x" * 48, "unused-fixture",
                                              transport=httpx.MockTransport(self.handle))
        self.generator._alias = m.MODEL_SHA256
        self.generator._metadata = {"repo_id": m.MODEL_ID, "revision": "gguf-sha256:" + m.MODEL_SHA256,
            "runtime": {"observed_build": "b11429-d81235049", "context_tokens": m.CONTEXT_TOKENS}}

    def handle(self, request):
        body = json.loads(request.content)
        self.requests.append((request.url.path, body))
        if request.url.path == "/apply-template":
            assert body["chat_template_kwargs"] == {"enable_thinking": False}
            prompt = "installed-native-template:" + json.dumps(body["messages"], ensure_ascii=False)
            self.prompts[json.dumps(body["messages"], ensure_ascii=False)] = prompt
            return httpx.Response(200, json={"prompt": prompt})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [10] * self.inputs})
        assert request.url.path == "/v1/chat/completions"
        assert "generation_prompt" not in body and "reasoning_budget_tokens" not in body
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["strict"] is True
        count = 10
        response = {"object": "chat.completion", "model": m.MODEL_SHA256,
            "system_fingerprint": "b11429-d81235049",
            "choices": [{"message": {"role": "assistant", "content": self.text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": self.inputs, "completion_tokens": count, "total_tokens": self.inputs + count,
                      "prompt_tokens_details": {"cached_tokens": 0}},
            "__verbose": {"model": m.MODEL_SHA256, "content": self.text,
                "prompt": self.prompts[json.dumps(body["messages"], ensure_ascii=False)],
                "generation_settings": {**{key: body[key] for key in m.GREEDY}, "n_predict": body["max_tokens"], "grammar": "native-compiled-schema"},
                "timings": {"cache_n": 0, "prompt_n": self.inputs, "predicted_n": count},
                "tokens": list(range(count)), "tokens_predicted": count, "tokens_evaluated": self.inputs,
                "stop": True, "stop_type": "eos", "truncated": False}}
        return httpx.Response(200, json=self.change(response))


@pytest.fixture
def native():
    value = Native()
    yield value
    value.generator.close()


@pytest.mark.parametrize("method,name,cap", [("generate_bounded", "meeting_qa", 768),
                                           ("summary_bounded", "meeting_summary", 768),
                                           ("review_bounded", "meeting_summary_review", 128)])
def test_structured_endpoint_explicit_schema_caps_and_private_telemetry(native, method, name, cap):
    g = native.generator
    g.begin_request(time.monotonic() + 120)
    output = getattr(g, method)([{"role": "user", "content": "private source 😀"}], g._deadline)
    body = native.requests[-1][1]
    assert body["max_tokens"] == body["n_predict"] == cap
    assert body["response_format"]["json_schema"]["name"] == name
    assert output.finish_reason == "eos" and output.input_tokens == 30 and output.output_tokens == 10
    assert "private" not in json.dumps(g.last_effective_config) + json.dumps(output.telemetry)
    assert g.last_call["accepted"] is True
    g.end_request()
    assert not g._cache and not g._prompts and g._deadline is None
    health = g.public_metadata()
    assert health["repo_id"] == m.MODEL_ID and health["runtime"]["max_input_tokens"] == 6144
    assert health["structured_output"]["semantic_quality_accepted"] is False


@pytest.mark.parametrize("kind", ["model", "fingerprint", "usage", "bool_count", "count_over", "token_count", "cache",
                                  "input", "prompt", "truncated", "length", "grammar", "sampling", "reasoning", "content_split", "tool"])
def test_structured_rejects_malformed_native_evidence(native, kind):
    def change(response):
        n = response["__verbose"]
        if kind == "model":
            response["model"] = "wrong"
        elif kind == "fingerprint":
            response["system_fingerprint"] = "wrong"
        elif kind == "usage":
            response["usage"]["total_tokens"] += 1
        elif kind == "bool_count":
            n["tokens_predicted"] = True
        elif kind == "count_over":
            n["tokens_predicted"] = 769
        elif kind == "token_count":
            n["tokens"] = [1]
        elif kind == "cache":
            n["timings"]["cache_n"] = 1
        elif kind == "input":
            n["tokens_evaluated"] -= 1
        elif kind == "prompt":
            n["prompt"] = "another prompt"
        elif kind == "truncated":
            n["truncated"] = True
        elif kind == "length":
            n["stop_type"] = "limit"
            response["choices"][0]["finish_reason"] = "length"
        elif kind == "grammar":
            n["generation_settings"]["grammar"] = ""
        elif kind == "sampling":
            n["generation_settings"]["temperature"] = .7
        elif kind == "reasoning":
            response["choices"][0]["message"]["reasoning_content"] = "hidden reasoning"
        elif kind == "content_split":
            n["content"] = "```json\n" + native.text + "\n```"
        else:
            response["choices"][0]["message"]["tool_calls"] = [{"name": "unexpected"}]
        return response
    native.change = change
    with pytest.raises(GenerationError):
        native.generator.generate_bounded([{"role": "user", "content": "fixture"}], time.monotonic() + 10)
    assert native.generator.last_effective_config is None and native.generator.last_call["accepted"] is False
    assert native.generator.last_call["http_status"] == 200
    assert native.generator.last_call["error_code"].startswith("generation_")
    assert native.generator.last_call["validation_stage"] in ("effective_settings", "token_identity_integrity", "eos")


def test_structured_http_failure_has_safe_fresh_status_without_raw_body(native):
    def failed(request):
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(503, text="private source-containing server explanation")
        return native.handle(request)
    native.generator._client.close()
    native.generator._client = httpx.Client(base_url="http://127.0.0.1:19003", transport=httpx.MockTransport(failed),
                                           event_hooks={"response": [native.generator._response_status]})
    with pytest.raises(GenerationError, match="backend_unavailable"):
        native.generator.generate_bounded([{"role": "user", "content": "private input"}], time.monotonic() + 10)
    record = native.generator.last_call
    assert record["http_status"] == 503 and record["validation_stage"] == "http"
    assert record["dispatched"] and not record["returned"] and not record["accepted"]
    assert "private" not in json.dumps(record)


@pytest.mark.parametrize("text", ['```json\n{"status":"abstained","claims":[]}\n```',
                                  '{"status":"abstained","status":"answered","claims":[]}',
                                  '{"claims":NaN}', '{}{}'])
def test_structured_never_repairs_json(native, text):
    native.text = text
    with pytest.raises(WorkerError):
        native.generator.generate_bounded([{"role": "user", "content": "fixture"}], time.monotonic() + 10)


@pytest.mark.parametrize("count,success", [(4471, True), (6144, True), (6145, False)])
def test_new_input_limit_measured_without_truncation(native, count, success):
    native.inputs = count
    invoke = lambda: native.generator.generate_bounded([{"role": "user", "content": "fixture"}], time.monotonic() + 10)
    if success:
        assert invoke().input_tokens == count
    else:
        with pytest.raises(GenerationError, match="generation_input_limit"):
            invoke()
        assert not any(path == "/v1/chat/completions" for path, _ in native.requests)


def test_deadline_prevents_native_dispatch(native):
    with pytest.raises(GenerationError, match="deadline"):
        native.generator.generate_bounded([], time.monotonic() - 1)
    assert not native.requests


@pytest.mark.parametrize("kind", ["correct", "other_model", "wrong_context"])
def test_identity_load_still_uses_existing_verifier_and_new_context(native, monkeypatch, kind):
    calls = []
    def load(generator):
        calls.append("existing_identity_verifier")
        if kind == "other_model":
            generator._metadata["repo_id"] = "another/model"
        if kind == "wrong_context":
            generator._metadata["runtime"]["context_tokens"] = 6144
        return generator
    monkeypatch.setattr(GGUFGenerator, "load", load)
    if kind == "correct":
        assert native.generator.load() is native.generator
    else:
        with pytest.raises(GenerationError, match="identity"):
            native.generator.load()
    assert calls == ["existing_identity_verifier"]


class FakeGenerator:
    def __init__(self):
        self.deadlines, self.calls = [], []
        self.last_effective_config, self.last_call = None, None
        self.size, self.fail_end = 100, False
        self.draft = {"status": "draft", "claims": [{"text": "현행 정책을 유지하기로 결정했다.", "evidence": [1]}]}
        self.review = {"claims": [[0, "supported"]], "coverage": "sufficient"}
        self.answer = {"status": "abstained", "claims": []}
    def public_metadata(self):
        return {"repo_id": "synthetic", "revision": "fake", "runtime": {}}
    def begin_request(self, deadline):
        self.deadlines.append(deadline)
        self.last_effective_config = self.last_call = None
    def end_request(self):
        self.calls.append("end")
        if self.fail_end:
            raise RuntimeError("private cleanup failure")
    def count_tokens(self, messages):
        return self.size
    def classify_bounded(self, prompts, deadline):
        self.deadlines.append(deadline)
        self.calls.append("classify")
        return [{"label": 1}, {"label": 7}], {"operation": "classification", "completion_calls": 2}
    def result(self, operation, data, deadline):
        self.calls.append(operation)
        self.deadlines.append(deadline)
        return GGUFResult(json.dumps(data, ensure_ascii=False), "eos", self.size, 20, .1, {})
    def summary_bounded(self, messages, deadline):
        return self.result("summary", self.draft, deadline)
    def review_bounded(self, messages, deadline):
        return self.result("review", self.review, deadline)
    def generate_bounded(self, messages, deadline):
        return self.result("qa", self.answer, deadline)


def analysis_request():
    return AnalyzeRequest(schema_version=1, document_id="fake", revision=1, title="정책 회의",
                          content="회의 제목: 정책 검토\n결정: 현행 정책을 유지하기로 확정했다.")


def answer_request():
    text = "제안만 있으며 결정 여부는 알려지지 않았다."
    return AnswerRequest(schema_version=1, query="무엇이 결정되었나?", contexts=[Context(
        document_id="fake", revision=1, chunk_id="chunk", title="공개 가상자료", page=None, meeting_date=None,
        start_offset=0, end_offset=len(text), text=text)])


def test_explicit_natural_summary_keeps_classified_items_and_one_request_deadline():
    generator = FakeGenerator()
    runtime = m.StructuredMeetingRuntime(generator)
    result = runtime.analyze(analysis_request())
    analysis = result["analysis"]
    assert analysis["summary"] == "현행 정책을 유지하기로 결정했다."
    assert analysis["summary"] != analysis["items"][0]["quote"]
    assert analysis["meeting_title"] == "정책 검토" and analysis["items"][0]["type"] == "decision"
    assert analysis["summary_version"] == 2 and analysis["summary_claims"][0]["citations"]
    assert result["summary_review"]["status"] == "accepted"
    assert generator.calls == ["classify", "summary", "review", "end"]
    assert len(set(generator.deadlines)) == 1 and not runtime.lock.locked()
    assert result["telemetry"]["stage"] == "assembled"
    assert [row["output_cap"] for row in result["telemetry"]["calls"] if "output_cap" in row] == [768, 128]
    assert runtime.health()["limits"]["input_tokens"] == 6144


@pytest.mark.parametrize("kind", ["citation", "review", "abstained", "input"])
def test_summary_failure_no_fallback_and_no_stale_success(kind):
    generator = FakeGenerator()
    runtime = m.StructuredMeetingRuntime(generator)
    runtime.analyze(analysis_request())
    previous = copy.deepcopy(runtime.last_telemetry)
    if kind == "citation":
        generator.draft["claims"][0]["evidence"] = [99]
    elif kind == "review":
        generator.review["coverage"] = "insufficient"
    elif kind == "abstained":
        generator.draft = {"status": "abstained", "claims": []}
    else:
        generator.size = 6145
    with pytest.raises(WorkerError):
        runtime.analyze(analysis_request())
    assert runtime.last_telemetry["status"] == "failed" and runtime.last_telemetry != previous
    assert not runtime.lock.locked()


def test_shared_lock_and_primary_failure_survive_end_request_error():
    generator = FakeGenerator()
    runtime = m.StructuredMeetingRuntime(generator)
    runtime.lock.acquire()
    with pytest.raises(WorkerError, match="model_busy"):
        runtime.analyze(analysis_request())
    runtime.lock.release()
    generator.review["coverage"] = "uncertain"
    generator.fail_end = True
    with pytest.raises(WorkerError, match="generation_summary_review_rejected"):
        runtime.analyze(analysis_request())
    assert not runtime.lock.locked()


def test_existing_qa_abstains_and_invalid_citation_fails_without_gold_injection():
    generator = FakeGenerator()
    runtime = m.StructuredMeetingRuntime(generator)
    assert runtime.answer(answer_request())["status"] == "abstained"
    generator.answer = {"status": "answered", "claims": [{"text": "확정됐다.", "evidence": [99]}]}
    with pytest.raises(WorkerError, match="evidence"):
        runtime.answer(answer_request())


def test_expired_summary_request_never_starts_review(monkeypatch):
    generator = FakeGenerator()
    runtime = m.StructuredMeetingRuntime(generator)
    now = [0]
    monkeypatch.setattr(m, "time", SimpleNamespace(monotonic=lambda: now[0]))
    original = generator.summary_bounded
    def summary(messages, deadline):
        result = original(messages, deadline)
        now[0] = 121
        return result
    generator.summary_bounded = summary
    with pytest.raises(WorkerError, match="deadline"):
        runtime.analyze(analysis_request())
    assert generator.calls == ["classify", "summary", "end"]
    assert not runtime.lock.locked()


def test_empty_qa_uses_same_lock_and_fresh_zero_generation_metrics():
    generator = FakeGenerator()
    runtime = m.StructuredMeetingRuntime(generator)
    runtime.analyze(analysis_request())
    result = runtime.answer(AnswerRequest(schema_version=1, query="근거가 있나요?", contexts=[]))
    assert result["status"] == "abstained" and result["telemetry"]["calls"] == []
    assert "qa" not in generator.calls and not runtime.lock.locked()
