"""Synthetic HTTP evidence only; no tokenizer/model/native process is loaded."""
import copy
import hashlib
import json
import time

import httpx
import pytest

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_gguf import GGUFGenerator
from doctrail.meeting_thinking_transport import (
    GGUF_SHA256,
    MODEL_ID,
    MODEL_REVISION,
    PREAMBLE,
    RUNTIME_COMMIT,
    SETTINGS,
    ThinkingGenerator,
    request_body,
    validate_response,
)
from scripts.probe_meeting_thinking_resources import NORMAL_SCHEMA, messages

PROMPT = "synthetic input\n" + PREAMBLE


def response(*, stress=False, n=100):
    content = '{"padding":"z z' if stress else '{"marker":"teal"}'
    output = 928 if stress else 20
    return {"object": "chat.completion", "model": GGUF_SHA256,
        "system_fingerprint": "b11429-d81235049", "choices": [{"index": 0,
            "finish_reason": "length" if stress else "stop", "message": {
                "role": "assistant", "reasoning_content": "A brief check.", "content": content}}],
        "usage": {"prompt_tokens": n, "completion_tokens": output, "total_tokens": n + output,
                  "prompt_tokens_details": {"cached_tokens": 0}},
        "__verbose": {"model": GGUF_SHA256, "prompt": PROMPT, "content":
            'A brief check.\n</think>\n\n' + content, "tokens": list(range(output)),
            "tokens_predicted": output, "tokens_evaluated": n, "stop": True,
            "truncated": False, "stop_type": "limit" if stress else "eos",
            "generation_settings": {**copy.deepcopy(SETTINGS), "stop": [], "grammar": "root"},
            "timings": {"prompt_n": n, "predicted_n": output, "cache_n": 0}}}


def generator(handler):
    gen = ThinkingGenerator("http://127.0.0.1:8123", "x" * 40, "unused",
                            transport=httpx.MockTransport(handler))
    gen._alias = GGUF_SHA256
    return gen


def test_chat_only_split_and_final_retokenization():
    seen, observations = [], {}
    def handler(request):
        payload = json.loads(request.content)
        seen.append((request.url.path, payload))
        if request.url.path == "/apply-template":
            assert payload["chat_template_kwargs"] == {"enable_thinking": True}
            return httpx.Response(200, json={"prompt": PROMPT})
        if request.url.path == "/tokenize":
            assert payload["add_special"] is False
            n = 100 if payload["parse_special"] else 8
            return httpx.Response(200, json={"tokens": list(range(n))})
        assert request.url.path == "/v1/chat/completions"
        assert payload == request_body(messages("normal"), NORMAL_SCHEMA)
        return httpx.Response(200, json=response())
    gen = generator(handler)
    result = gen.generate_neutral(messages("normal"), NORMAL_SCHEMA,
                                   observe=lambda k, v: observations.update({k: v}))
    assert result.final_retokenized_tokens == 8
    assert result.output_tokens == 20
    assert result.content == '{"marker":"teal"}'
    assert result.telemetry["reasoning_budget_effective_serialized"] is False
    assert len(observations["final_token_ids"]) == 8
    assert [p for p, _ in seen].count("/v1/chat/completions") == 1
    assert gen._deadline is None
    gen.close()


@pytest.mark.parametrize("location,key,value", [
    ("settings", "temperature", True), ("settings", "seed", 7),
    ("settings", "reasoning_format", "none"), ("settings", "grammar_lazy", True),
    ("settings", "generation_prompt", PREAMBLE + "</think>\n"),
    ("settings", "n_predict", 929), ("settings", "stop", ["stop now"]),
    ("verbose", "truncated", True), ("verbose", "tokens", [1]),
    ("verbose", "stop_type", "word"), ("verbose", "prompt", "different"),
    ("message", "reasoning_content", ""), ("message", "content", '{"marker":"red"}'),
    ("timing", "cache_n", 1), ("timing", "predicted_n", 19),
    ("top", "model", "wrong"), ("top", "system_fingerprint", "b11429-unknown"),
])
def test_fail_closed_native_mismatches(location, key, value):
    raw = response()
    targets = {"settings": raw["__verbose"]["generation_settings"],
        "verbose": raw["__verbose"], "message": raw["choices"][0]["message"],
        "timing": raw["__verbose"]["timings"], "top": raw}
    targets[location][key] = value
    with pytest.raises(GenerationError):
        validate_response(raw, prompt=PROMPT, input_tokens=100)


def test_native_framing_is_verified_without_cleaning_content():
    raw = response()
    raw["__verbose"]["content"] = 'A brief check.\n</think>\n```json\n{"marker":"teal"}\n```'
    result = validate_response(raw, prompt=PROMPT, input_tokens=100)
    assert result["content"] == raw["choices"][0]["message"]["content"]
    assert result["telemetry"]["native_json_framing"] == "fenced"
    raw["__verbose"]["content"] += "unexplained trailer"
    with pytest.raises(GenerationError):
        validate_response(raw, prompt=PROMPT, input_tokens=100)


def test_stress_requires_full_budget_and_allows_incomplete_json_only_there():
    raw = response(stress=True, n=5000)
    result = validate_response(raw, prompt=PROMPT, input_tokens=5000, stress=True)
    assert result["finish_reason"] == "length"
    with pytest.raises(GenerationError):
        validate_response(raw, prompt=PROMPT, input_tokens=5000)
    raw["__verbose"]["tokens_predicted"] = 927
    with pytest.raises(GenerationError):
        validate_response(raw, prompt=PROMPT, input_tokens=5000, stress=True)


def test_stress_partial_native_fence_is_only_a_split_comparison():
    raw = response(stress=True, n=5000)
    raw["__verbose"]["content"] = 'A brief check.\n</think>\n```json\n{"padding":"z z'
    result = validate_response(raw, prompt=PROMPT, input_tokens=5000, stress=True)
    assert result["content"] == '{"padding":"z z'
    assert result["telemetry"]["native_json_framing"] == "partial_fence"
    raw = response()
    raw["__verbose"]["content"] = 'A brief check.\n</think>\n```json\n{"marker":"teal"}'
    with pytest.raises(GenerationError):
        validate_response(raw, prompt=PROMPT, input_tokens=100)


@pytest.mark.parametrize("fault", ["template", "input", "timeout", "final_limit", "dispatch_drift"])
def test_errors_preserve_observed_raw_and_never_retry(fault):
    calls, observations = [], {}
    def handler(request):
        calls.append(request.url.path)
        payload = json.loads(request.content)
        if request.url.path == "/apply-template":
            return httpx.Response(200, json={"prompt": "bad" if fault == "template" else PROMPT})
        if request.url.path == "/tokenize":
            n = (5121 if fault == "input" else 100) if payload["parse_special"] else 385
            return httpx.Response(200, json={"tokens": list(range(n))})
        if fault == "timeout":
            raise httpx.ReadTimeout("synthetic private content")
        return httpx.Response(200, json=response())
    def before(*args):
        if fault == "dispatch_drift":
            raise ValueError("source_changed")
    gen = generator(handler)
    with pytest.raises((GenerationError, ValueError)) as exc:
        gen.generate_neutral(messages("normal"), NORMAL_SCHEMA, before_dispatch=before,
                             observe=lambda k, v: observations.update({k: v}))
    assert "synthetic private" not in str(exc.value)
    assert calls.count("/v1/chat/completions") == (1 if fault in {"timeout", "final_limit"} else 0)
    assert ("response" in observations) is (fault == "final_limit")
    assert gen._deadline is None
    gen.close()


def test_deadline_includes_preparation_and_postprocessing(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    def handler(request):
        now[0] = 101.0
        return httpx.Response(200, json={"prompt": PROMPT})
    gen = generator(handler)
    with pytest.raises(GenerationError, match="generation_deadline_exceeded"):
        gen.generate_neutral(messages("normal"), NORMAL_SCHEMA)
    gen.close()


def test_identity_override_is_accurate_and_rejects_context_drift(tmp_path, monkeypatch):
    from doctrail import meeting_thinking_transport as transport
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b"{}")
    monkeypatch.setattr(transport, "MANIFEST_SHA256", hashlib.sha256(b"{}").hexdigest())
    metadata = {"repo_id": MODEL_ID, "original_revision": MODEL_REVISION,
        "artifact": {"sha256": GGUF_SHA256}, "runtime": {"tag": "b11429",
            "commit": RUNTIME_COMMIT, "context_tokens": 6144}}
    def fake_load(self):
        self._metadata = copy.deepcopy(metadata)
        return self
    monkeypatch.setattr(GGUFGenerator, "load", fake_load)
    gen = ThinkingGenerator("http://127.0.0.1:8123", "x" * 40, manifest)
    gen.load()
    assert gen.public_metadata()["runtime"]["max_input_tokens"] == 5120
    assert gen.public_metadata()["runtime"]["max_new_tokens"] == 928
    gen.close()
    metadata["runtime"]["context_tokens"] = 8192
    gen = ThinkingGenerator("http://127.0.0.1:8123", "x" * 40, manifest)
    with pytest.raises(GenerationError, match="generation_identity_mismatch"):
        gen.load()


def test_service_entrypoints_are_not_exposed():
    gen = generator(lambda _: None)
    with pytest.raises(GenerationError, match="resource_only_transport"):
        gen.generate_bounded([], time.monotonic() + 90)
    with pytest.raises(GenerationError, match="resource_only_transport"):
        gen.classify_bounded([], time.monotonic() + 90)
    gen.close()
