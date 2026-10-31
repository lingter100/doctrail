"""Synthetic transport/parity tests; no native process or real tokenizer."""
import copy
import json

import httpx
import pytest

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_answer_thinking import CANDIDATE_ID, prepare_answer
from doctrail.meeting_thinking_quality import QualityThinkingGenerator, validate_quality_response
from doctrail.meeting_thinking_transport import (
    GGUF_SHA256,
    PREAMBLE,
    PROTOCOL,
    SETTINGS,
    request_body,
    validate_response,
)

PROMPT = "synthetic policy input\n" + PREAMBLE
CONTENT = '{"status":"answered","claims":[{"evidence_ids":[0],"text":"The lamp is blue."}]}'
REQUEST = {"schema_version": 1, "query": "What color is the lamp?", "contexts": [{
    "document_id": "new-synthetic-doc", "revision": 1, "chunk_id": "new-synthetic-chunk",
    "title": "Synthetic lamp", "meeting_date": None, "page": None, "start_offset": 0,
    "end_offset": 17, "text": "The lamp is blue."}]}


def response(content=CONTENT):
    return {"object": "chat.completion", "model": GGUF_SHA256,
        "system_fingerprint": "b11429-d81235049", "choices": [{"index": 0,
            "finish_reason": "stop", "message": {"role": "assistant",
                "reasoning_content": "Synthetic reasoning.", "content": content}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
                  "prompt_tokens_details": {"cached_tokens": 0}},
        "__verbose": {"model": GGUF_SHA256, "prompt": PROMPT,
            "content": "Synthetic reasoning.\n</think>\n\n" + content,
            "tokens": list(range(20)), "tokens_predicted": 20, "tokens_evaluated": 100,
            "stop": True, "truncated": False, "stop_type": "eos",
            "generation_settings": {**copy.deepcopy(SETTINGS), "stop": [], "grammar": "root"},
            "timings": {"prompt_n": 100, "predicted_n": 20, "cache_n": 0}}}


def generator(handler):
    gen = QualityThinkingGenerator("http://127.0.0.1:8123", "x" * 40, "unused",
        transport=httpx.MockTransport(handler))
    # Synthetic identity only; production requires inherited load().
    gen._alias = GGUF_SHA256
    gen._metadata = {"generation_protocol": PROTOCOL}
    return gen


def handler_for(seen, *, native=None, input_n=100, final_n=30):
    def handler(req):
        payload = json.loads(req.content)
        seen.append((req.url.path, payload))
        if req.url.path == "/apply-template":
            return httpx.Response(200, json={"prompt": PROMPT})
        if req.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": list(range(
                input_n if payload["parse_special"] else final_n))})
        return native if native is not None else httpx.Response(200, json=response())
    return handler


def test_one_call_unchanged_request_trace_and_grounding():
    seen, events, dispatched = [], {}, []
    gen = generator(handler_for(seen))
    prepared = prepare_answer(REQUEST, "en")
    result = gen.answer(REQUEST, "en", observe=lambda k, v: events.update({k: v}),
        before_dispatch=lambda *args: dispatched.append(args))
    assert [p for p, _ in seen] == ["/apply-template", "/tokenize",
                                  "/v1/chat/completions", "/tokenize"]
    assert dispatched[0] == (PROMPT, list(range(100)),
                             request_body(prepared.messages, prepared.schema))
    assert events["native_request"] == request_body(prepared.messages, prepared.schema)
    assert events["native_response"] == events["response"] == response()
    assert events["native_post_started"] is True
    assert events["apply_template_response"] == {"prompt": PROMPT}
    assert events["input_tokenize_request"]["parse_special"] is True
    assert events["final_tokenize_request"] == {"content": CONTENT, "parse_special": False,
                                               "add_special": False, "with_pieces": False}
    assert events["final_tokenize_response"]["tokens"] == events["final_token_ids"]
    assert all(events[k + "_http_status"] == 200 for k in (
        "native", "apply_template", "input_tokenize", "final_tokenize"))
    assert result.completion.content == CONTENT
    assert result.completion.final_retokenized_tokens == 30
    assert result.completion.telemetry["semantic_support_verified"] is False
    assert result.completion.telemetry["reasoning_budget_effective_serialized"] is False
    assert result.answer["claims"][0]["citations"][0]["quote"] == "The lamp is blue."
    assert events["result"]["answer"] == result.answer
    assert gen.public_metadata() == {"generation_protocol": PROTOCOL, "candidate_id": CANDIDATE_ID}
    assert gen._deadline is None and gen._observer is None
    gen.close()


@pytest.mark.parametrize("location,key,value", [
    ("settings", "temperature", True), ("settings", "seed", 1),
    ("settings", "reasoning_format", "none"), ("settings", "n_predict", 929),
    ("settings", "max_tokens", 927), ("settings", "generation_prompt", "wrong"),
    ("settings", "stop", ["text"]), ("settings", "grammar", ""),
    ("verbose", "model", "wrong"), ("verbose", "tokens", [1]),
    ("verbose", "tokens_predicted", True), ("verbose", "tokens_evaluated", 101),
    ("verbose", "truncated", True), ("verbose", "stop", False),
    ("verbose", "stop_type", "limit"), ("verbose", "prompt", "wrong"),
    ("timing", "cache_n", 1), ("timing", "prompt_n", 99),
    ("timing", "predicted_n", 21), ("message", "reasoning_content", ""),
    ("message", "tool_calls", [{"name": "tool"}]), ("message", "role", "user"),
    ("top", "model", "wrong"), ("top", "system_fingerprint", "other"),
    ("top", "choices", []), ("usage", "total_tokens", 121),
    ("usage", "prompt_tokens_details", {"cached_tokens": True}),
    ("choice", "finish_reason", "length"),
])
def test_common_guard_parity_with_frozen_normal_validator(location, key, value):
    errors = []
    for validator, content in [(validate_response, '{"marker":"teal"}'),
                               (validate_quality_response, CONTENT)]:
        raw = response(content)
        targets = {"settings": raw["__verbose"]["generation_settings"],
            "verbose": raw["__verbose"], "timing": raw["__verbose"]["timings"],
            "message": raw["choices"][0]["message"], "choice": raw["choices"][0],
            "top": raw, "usage": raw["usage"]}
        targets[location][key] = value
        with pytest.raises(GenerationError) as error:
            validator(raw, prompt=PROMPT, input_tokens=100)
        errors.append(error.value.code)
    assert errors[0] == errors[1]


@pytest.mark.parametrize("frame,accepted", [("{c}", True), ("```json\n{c}\n```", True),
    ("```json\n{c}", False), ("```\n{c}\n```", False), ("prefix{c}", False)])
def test_exact_pinned_framing_without_repair(frame, accepted):
    raw = response()
    raw["__verbose"]["content"] = "Synthetic reasoning.\n</think>\n" + frame.format(c=CONTENT)
    if accepted:
        assert validate_quality_response(raw, prompt=PROMPT, input_tokens=100)["content"] == CONTENT
    else:
        with pytest.raises(GenerationError):
            validate_quality_response(raw, prompt=PROMPT, input_tokens=100)


@pytest.mark.parametrize("content", ['{"a":1,"a":2}', '{"a":NaN}', "[]", CONTENT + "junk"])
def test_strict_json_never_repaired(content):
    with pytest.raises(GenerationError):
        validate_quality_response(response(content), prompt=PROMPT, input_tokens=100)


@pytest.mark.parametrize("input_n,final_n,code,native_count", [
    (5121, 30, "generation_input_limit", 0), (0, 30, "generation_input_limit", 0),
    (100, 385, "generation_final_content_limit", 1),
    (100, 0, "generation_final_content_limit", 1)])
def test_limits_fail_without_truncation_retry_or_abstention(input_n, final_n, code, native_count):
    seen = []
    gen = generator(handler_for(seen, input_n=input_n, final_n=final_n))
    with pytest.raises(GenerationError) as error:
        gen.answer(REQUEST, "en")
    assert error.value.code == code
    assert sum(p == "/v1/chat/completions" for p, _ in seen) == native_count
    assert gen._deadline is None and not gen._answer_lock.locked()
    gen.close()


def test_failed_native_status_is_preserved_without_reading_error_body():
    seen, events = [], {}
    gen = generator(handler_for(seen, native=httpx.Response(500, content=b"private error body")))
    with pytest.raises(GenerationError):
        gen.answer(REQUEST, "en", observe=lambda k, v: events.update({k: v}))
    assert events["native_error"] == {"code": "generation_backend_unavailable",
                                       "http_status": 500, "body_available": False}
    assert "private error body" not in repr(events)
    assert "native_response" not in events
    gen.close()


@pytest.mark.parametrize("expired", [False, True])
def test_callback_failure_or_deadline_prevents_post(monkeypatch, expired):
    seen, events = [], {}
    gen = generator(handler_for(seen))
    now = [1.0]
    monkeypatch.setattr("doctrail.meeting_thinking_quality.time.monotonic", lambda: now[0])
    def before(*args):
        if expired:
            now[0] = 92.0
        else:
            raise GenerationError("synthetic_source_drift")
    with pytest.raises(GenerationError):
        gen.answer(REQUEST, "en", before_dispatch=before,
                   observe=lambda k, v: events.update({k: v}))
    assert all(p != "/v1/chat/completions" for p, _ in seen)
    assert "native_post_started" not in events
    assert not gen._answer_lock.locked()
    gen.close()


@pytest.mark.parametrize("raw_content", ["missing separator", "<think>x</think>" + CONTENT,
    "wrong reasoning</think>" + CONTENT, "Synthetic reasoning.</think></think>" + CONTENT])
def test_reasoning_split_mismatch_never_returns_answer(raw_content):
    raw = response()
    raw["__verbose"]["content"] = raw_content
    with pytest.raises(GenerationError, match="generation_reasoning_split_mismatch"):
        validate_quality_response(raw, prompt=PROMPT, input_tokens=100)


def test_validator_failure_preserves_raw_200_response_and_timeout_has_no_status():
    for timeout in (False, True):
        seen, events = [], {}
        raw = response()
        raw["__verbose"]["generation_settings"]["seed"] = 9
        normal_handler = handler_for(seen, native=httpx.Response(200, json=raw))
        def handler(req, normal_handler=normal_handler, timeout=timeout):
            if timeout and req.url.path == "/v1/chat/completions":
                raise httpx.ReadTimeout("synthetic-private-error")
            return normal_handler(req)
        gen = generator(handler)
        with pytest.raises(GenerationError):
            gen.answer(REQUEST, "en", observe=lambda k, v, events=events: events.update({k: v}))
        assert events["native_post_started"] is True
        if timeout:
            assert events["native_error"]["http_status"] is None
            assert "synthetic-private-error" not in repr(events)
        else:
            assert events["response"] == raw
            assert "result" not in events
        gen.close()


def test_observers_cannot_mutate_request_and_late_observer_deadline_is_failure(monkeypatch):
    seen = []
    gen = generator(handler_for(seen))
    now = [1.0]
    monkeypatch.setattr("doctrail.meeting_thinking_quality.time.monotonic", lambda: now[0])
    def observe(key, value):
        if key == "native_request":
            value["max_tokens"] = 1
        if key == "result":
            now[0] = 92.0
    with pytest.raises(GenerationError, match="generation_deadline_exceeded"):
        gen.answer(REQUEST, "en", observe=observe)
    assert seen[2][1]["max_tokens"] == 928
    gen.close()


def test_send_observer_expiry_prevents_actual_native_transport(monkeypatch):
    seen, events = [], {}
    gen = generator(handler_for(seen))
    now = [1.0]
    monkeypatch.setattr("doctrail.meeting_thinking_quality.time.monotonic", lambda: now[0])
    def observe(key, value):
        events[key] = value
        if key == "native_post_started":
            now[0] = 92.0
    with pytest.raises(GenerationError, match="generation_deadline_exceeded"):
        gen.answer(REQUEST, "en", observe=observe)
    assert all(path != "/v1/chat/completions" for path, _ in seen)
    assert events["native_post_started"] is True
    assert events["native_post_aborted"] == {"code": "generation_deadline_exceeded"}
    assert gen._deadline is None and not gen._answer_lock.locked()
    gen.close()


def test_send_observer_time_reduces_actual_transport_timeout(monkeypatch):
    seen, timeouts = [], []
    normal_handler = handler_for(seen)
    def handler(req):
        if req.url.path == "/v1/chat/completions":
            timeouts.append(req.extensions["timeout"])
        return normal_handler(req)
    gen = generator(handler)
    now = [1.0]
    monkeypatch.setattr("doctrail.meeting_thinking_quality.time.monotonic", lambda: now[0])
    def observe(key, value):
        if key == "native_post_started":
            now[0] += 10
    gen.answer(REQUEST, "en", observe=observe)
    assert timeouts == [{"connect": 80.0, "read": 80.0, "write": 80.0, "pool": 80.0}]
    gen.close()


def test_unloaded_and_concurrent_requests_refused_before_http():
    seen = []
    gen = generator(handler_for(seen))
    gen._metadata = None
    with pytest.raises(GenerationError, match="generation_not_ready"):
        gen.answer(REQUEST, "en")
    gen._answer_lock.acquire()
    with pytest.raises(GenerationError, match="model_busy"):
        gen.answer(REQUEST, "en")
    gen._answer_lock.release()
    assert seen == []
    gen.close()
