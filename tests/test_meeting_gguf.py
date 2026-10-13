"""Mocked native transport contracts; these tests are not model-quality evidence."""
import copy
import hashlib
import json
import time

import httpx
import pytest

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_gguf import (
    GREEDY,
    LABEL_GRAMMAR,
    LABEL_TOKEN_LIMIT,
    MAX_RESPONSE_BYTES,
    GGUFGenerator,
)
from doctrail.meeting_runtime import MAX_INPUT_TOKENS, MAX_NEW_TOKENS

TOKEN = "native-test-token-" + "x" * 32
MESSAGES = [{"role": "user", "content": "한국어 question; keep English source 😀 intact."}]


class Native:
    def __init__(self, tmp_path):
        artifact = tmp_path / "test-Q5_K_M.gguf"
        artifact.write_bytes(b"synthetic mocked artifact, never a real model")
        self.digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        self.manifest = {"schema_version": 1, "model": "synthetic/gguf-model", "revision": "a" * 40,
            "gguf": {"repo_id": "synthetic/quantizer", "revision": "b" * 40,
                "filename": artifact.name, "sha256": self.digest,
                "size_bytes": artifact.stat().st_size},
            "llama": {"tag": "b11429", "commit": "d81235049384534c167caea52b85a694f6103d14"}}
        self.path = tmp_path / "manifest.json"
        self.path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.props = {"model_alias": self.digest, "model_path": str(artifact),
            "build_info": "b11429-d81235049", "total_slots": 1, "is_sleeping": False,
            "default_generation_settings": {"n_ctx": 6144}}
        self.tokens = [10, 11, 12]
        self.content = '{"status":"abstained","reason":"insufficient_evidence","claims":[]}'
        self.requests = []
        self.change = lambda response: response

    def handler(self, request):
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        self.requests.append(request)
        if request.url.path == "/props":
            return httpx.Response(200, json=self.props)
        body = json.loads(request.content)
        if request.url.path == "/apply-template":
            assert body["messages"] == MESSAGES
            assert body["chat_template_kwargs"] == {"enable_thinking": False}
            return httpx.Response(200, json={"prompt": "<chat>" + MESSAGES[0]["content"]})
        if request.url.path == "/tokenize":
            assert body["add_special"] is False and body["parse_special"] is True
            return httpx.Response(200, json={"tokens": self.tokens})
        assert request.url.path == "/completion"
        assert body["prompt"] == self.tokens and body["cache_prompt"] is False
        settings = {key: body[key] for key in (*GREEDY, "n_predict", "grammar")}
        result = {"model": self.digest, "generation_settings": settings,
            "content": self.content, "tokens_evaluated": len(self.tokens), "tokens_predicted": 2,
            "stop": True, "stop_type": "eos", "truncated": False,
            "timings": {"cache_n": 0, "prompt_n": len(self.tokens), "predicted_n": 2,
                        "prompt_ms": 1.5, "predicted_ms": 3.0},
            "prompt": "PRIVATE RAW PROMPT MUST NEVER BE TELEMETRY"}
        return httpx.Response(200, json=self.change(result))

    def generator(self):
        return GGUFGenerator("http://127.0.0.1:8093", TOKEN, self.path,
                             transport=httpx.MockTransport(self.handler)).load()


@pytest.fixture
def native(tmp_path):
    return Native(tmp_path)


def test_verified_dynamic_identity_and_native_only_telemetry(native):
    generator = native.generator()
    metadata = generator.public_metadata()
    assert metadata["repo_id"] == "synthetic/gguf-model"
    assert metadata["revision"] == "gguf-sha256:" + native.digest
    assert metadata["original_revision"] == "a" * 40
    assert metadata["artifact"]["sha256"] == native.digest
    assert metadata["runtime"]["memory_telemetry"] == "not_measured"
    assert "model_path" not in json.dumps(metadata)
    output = generator.generate_bounded(MESSAGES, time.monotonic() + 10)
    assert output.finish_reason == "eos" and output.input_tokens == 3
    assert not hasattr(output, "peak_allocated_mib")
    assert "PRIVATE" not in json.dumps(output.telemetry)
    assert generator.last_effective_config["n_predict"] == MAX_NEW_TOKENS
    assert generator.last_effective_config["observed_cache_tokens"] == 0
    generator.close()


@pytest.mark.parametrize("change", [
    {"model_alias": "other"}, {"build_info": "b11428-d81235049"},
    {"build_info": "b11429-aaaaaaaa"}, {"total_slots": 2}, {"is_sleeping": True},
    {"default_generation_settings": {"n_ctx": 4096}}, {"model_path": "missing.gguf"},
])
def test_identity_mismatch_fails_closed(native, change):
    native.props.update(change)
    with pytest.raises(GenerationError, match="generation_identity_mismatch"):
        native.generator()


def test_same_size_wrong_artifact_bytes_rejected(native):
    from pathlib import Path
    artifact = Path(native.props["model_path"])
    artifact.write_bytes(b"X" * artifact.stat().st_size)
    with pytest.raises(GenerationError, match="generation_identity_mismatch"):
        native.generator()


@pytest.mark.parametrize("url", ["https://127.0.0.1:8093", "http://localhost:8093",
    "http://example.com:8093", "http://127.0.0.1:8093/hidden", "http://127.0.0.1:8093?key=x",
    "http://user:secret@127.0.0.1:8093", "http://127.0.0.1:8093#x", "http://127.0.0.1"])
def test_nonliteral_or_ambiguous_endpoint_rejected(native, url):
    with pytest.raises(GenerationError, match="generation_backend_url"):
        GGUFGenerator(url, TOKEN, native.path)


@pytest.mark.parametrize("token", ["", "short", "x" * 32 + "\n", "한" * 32])
def test_invalid_native_token_rejected(native, token):
    with pytest.raises(GenerationError, match="generation_backend_token"):
        GGUFGenerator("http://127.0.0.1:8093", token, native.path)


def test_prompt_token_cache_only_inside_one_request(native):
    generator = native.generator()
    generator.begin_request(time.monotonic() + 10)
    assert generator.count_tokens(MESSAGES) == 3
    generator.generate_bounded(MESSAGES, time.monotonic() + 10)
    assert [r.url.path for r in native.requests].count("/tokenize") == 1
    generator.end_request()
    assert not generator._cache
    generator.begin_request(time.monotonic() + 10)
    generator.count_tokens(MESSAGES)
    assert [r.url.path for r in native.requests].count("/tokenize") == 2
    generator.close()


def test_overflow_rejected_without_completion_or_pruning(native):
    native.tokens = list(range(MAX_INPUT_TOKENS + 1))
    generator = native.generator()
    with pytest.raises(GenerationError, match="generation_input_limit"):
        generator.generate_bounded(MESSAGES, time.monotonic() + 10)
    assert not any(r.url.path == "/completion" for r in native.requests)
    generator.close()


@pytest.mark.parametrize("key,value", [("temperature", 0.7), ("samplers", ["top_k", "temperature"]),
    ("seed", 1), ("seed", False), ("n_predict", -1), ("grammar", "root ::= .*"), ("ignore_eos", True),
    ("stop", ["END"]), ("logit_bias", [{"token": 5, "bias": 1}])])
def test_effective_settings_must_match_request(native, key, value):
    def alter(response):
        response["generation_settings"][key] = value
        return response
    native.change = alter
    generator = native.generator()
    with pytest.raises(GenerationError, match="generation_effective_config_mismatch"):
        generator.generate_bounded(MESSAGES, time.monotonic() + 10)
    assert generator.last_effective_config is None
    generator.close()


@pytest.mark.parametrize("change", [{"model": "wrong"}, {"truncated": True}, {"stop": False},
    {"stop_type": "word"}, {"tokens_evaluated": 2}, {"tokens_predicted": 769},
    {"tokens_predicted": True}, {"timings": {"cache_n": 1, "prompt_n": 3}}])
def test_invalid_completion_metadata_rejected(native, change):
    native.change = lambda response: {**response, **copy.deepcopy(change)}
    generator = native.generator()
    with pytest.raises(GenerationError, match="generation_backend_protocol"):
        generator.generate_bounded(MESSAGES, time.monotonic() + 10)
    generator.close()


def test_length_stop_is_preserved_as_failure_not_silently_accepted(native):
    native.change = lambda response: {**response, "stop_type": "limit"}
    generator = native.generator()
    assert generator.generate_bounded(MESSAGES, time.monotonic() + 10).finish_reason == "length"
    generator.close()


def test_actual_digit_completion_classification_without_fake_confidence(native):
    native.content = "9"
    generator = native.generator()
    rows, metrics = generator.classify_bounded([MESSAGES, MESSAGES], time.monotonic() + 10)
    assert rows == [{"label": 9}, {"label": 9}]
    assert metrics["completion_calls"] == 2 and metrics["confidence"] == "not_measured"
    assert generator.last_effective_config["grammar"] == LABEL_GRAMMAR
    assert generator.last_effective_config["n_predict"] == LABEL_TOKEN_LIMIT
    assert "peak_reserved_mib" not in metrics
    generator.close()


@pytest.mark.parametrize("text", ["9 explanation", " 9", "10", "９", ""])
def test_invalid_label_is_not_repaired(native, text):
    native.content = text
    generator = native.generator()
    with pytest.raises(GenerationError, match="generation_invalid_label"):
        generator.classify_bounded([MESSAGES], time.monotonic() + 10)
    generator.close()


@pytest.mark.parametrize("mode", ["redirect", "oversized", "duplicate", "timeout", "error"])
def test_http_failures_safe_and_no_redirects(native, mode):
    requests = []
    def handler(request):
        requests.append(request)
        if mode == "redirect":
            return httpx.Response(302, headers={"location": "http://example.com/private"})
        if mode == "oversized":
            return httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))
        if mode == "duplicate":
            return httpx.Response(200, content=b'{"secret":1,"secret":2}')
        if mode == "timeout":
            raise httpx.ReadTimeout("PRIVATE SOURCE AND CREDENTIAL")
        return httpx.Response(500, content=b"PRIVATE SOURCE AND CREDENTIAL")
    generator = GGUFGenerator("http://127.0.0.1:8093", TOKEN, native.path,
                              transport=httpx.MockTransport(handler))
    with pytest.raises(GenerationError) as raised:
        generator.load()
    assert "PRIVATE" not in str(raised.value) and len(requests) == 1


def test_expired_global_deadline_covers_token_count(native):
    generator = native.generator()
    generator.begin_request(time.monotonic() - 1)
    with pytest.raises(GenerationError, match="generation_deadline_exceeded"):
        generator.count_tokens(MESSAGES)
    assert len(native.requests) == 1
    generator.close()
