"""Mocked Qwen3.5 protocol checks; no native model or quality evaluation."""
import json
import time

import httpx
import pytest

from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_answer_grammar import ANSWER_GRAMMAR, GrammarAnswerGenerator
from doctrail.meeting_answer_v2 import grounded_answer_v2
from doctrail.meeting_gguf import GREEDY, GGUFGenerator
from doctrail.meeting_qwen35 import (
    GGUF_SHA256,
    MODEL_ID,
    MODEL_REVISION,
    NONTHINKING_PREAMBLE,
    PREAMBLE_SHA256,
    Qwen35Generator,
)

MESSAGES = [{"role": "user", "content": "Literal <think> and </think> are document content."}]


class Native:
    def __init__(self, tmp_path):
        self.calls = []
        self.prompt = "<|im_start|>user\n" + MESSAGES[0]["content"] + "<|im_end|>\n" + NONTHINKING_PREAMBLE
        self.text = '{"status":"abstained","claims":[]}'
        self.tokens = [1, 2, 3]
        self.generator = Qwen35Generator("http://127.0.0.1:19003", "x" * 48,
            tmp_path / "unused.json", transport=httpx.MockTransport(self.handle))
        self.generator._alias = GGUF_SHA256
        self.generator._metadata = {"repo_id": MODEL_ID, "original_revision": MODEL_REVISION,
            "revision": "gguf-sha256:" + GGUF_SHA256, "artifact": {"sha256": GGUF_SHA256}}

    def handle(self, request):
        self.calls.append(request.url.path)
        body = json.loads(request.content)
        if request.url.path == "/apply-template":
            assert body == {"messages": MESSAGES, "chat_template_kwargs": {"enable_thinking": False}}
            return httpx.Response(200, json={"prompt": self.prompt})
        if request.url.path == "/tokenize":
            assert body["content"] == self.prompt  # no stripping literal source tags or preamble
            return httpx.Response(200, json={"tokens": self.tokens})
        assert request.url.path == "/completion"
        assert body["prompt"] == self.tokens and body["cache_prompt"] is False
        return httpx.Response(200, json={"content": self.text, "model": GGUF_SHA256,
            "generation_settings": {key: body[key] for key in (*GREEDY, "n_predict", "grammar")},
            "stop": True, "stop_type": "eos", "truncated": False,
            "tokens_predicted": 10, "tokens_evaluated": len(self.tokens),
            "timings": {"cache_n": 0, "prompt_n": len(self.tokens)}})


def test_exact_official_nonthinking_preamble_with_literal_source_tags(tmp_path):
    native = Native(tmp_path)
    generator = native.generator
    output = generator.generate_bounded(MESSAGES, time.monotonic() + 10)
    assert output.text == native.text
    assert generator.last_effective_config["grammar"] == ANSWER_GRAMMAR
    assert generator.last_effective_config["observed_nonthinking_preamble_sha256"] == PREAMBLE_SHA256
    assert generator.last_effective_config["enable_thinking_requested"] is False
    assert generator.public_metadata()["nonthinking"]["last_template_verified"] is True
    assert Qwen35Generator.generate_bounded is GrammarAnswerGenerator.generate_bounded
    generator.close()


@pytest.mark.parametrize("suffix", ["<|im_start|>assistant\n<think>\n",
    "<|im_start|>assistant\n", "<think>\n\n</think>\n\n",
    "<|im_start|>assistant\n<think>reasoning</think>\n\n", NONTHINKING_PREAMBLE + " "])
def test_thinking_or_wrong_preamble_fails_before_tokenization(tmp_path, suffix):
    native = Native(tmp_path)
    native.prompt = "user input with raw <think>\n" + suffix
    with pytest.raises(GenerationError, match="generation_nonthinking_template_mismatch"):
        native.generator.generate_bounded(MESSAGES, time.monotonic() + 10)
    assert native.calls == ["/apply-template"]
    assert native.generator.public_metadata()["nonthinking"]["last_template_verified"] is False
    native.generator.close()


def test_request_cache_contains_only_verified_prompts_and_resets(tmp_path):
    native = Native(tmp_path)
    native.generator.begin_request(time.monotonic() + 10)
    native.generator.count_tokens(MESSAGES)
    native.generator.generate_bounded(MESSAGES, time.monotonic() + 10)
    assert native.calls.count("/apply-template") == 1
    native.generator.end_request()
    native.generator.begin_request(time.monotonic() + 10)
    assert not native.generator._cache
    assert native.generator.public_metadata()["nonthinking"]["last_template_verified"] is False
    native.generator.close()


def test_no_output_cleanup_or_tag_removal(tmp_path):
    native = Native(tmp_path)
    native.text = '<think>unexpected reasoning</think>{"status":"abstained","claims":[]}'
    # Such a native result violates the grammar; the unchanged downstream parser rejects it.
    # The adapter must not silently turn it into an accepted JSON answer.
    result = native.generator.generate_bounded(MESSAGES, time.monotonic() + 10)
    assert result.text == native.text
    with pytest.raises(WorkerError, match="generation_invalid_json"):
        grounded_answer_v2(result.text, {}, "en")
    native.generator.close()


@pytest.mark.parametrize("change", [{"repo_id": "other/model"}, {"original_revision": "a" * 40},
                                    {"artifact": {"sha256": "b" * 64}}])
def test_qwen35_load_rejects_another_candidate_identity(tmp_path, monkeypatch, change):
    native = Native(tmp_path)
    native.generator._metadata.update(change)
    monkeypatch.setattr(GGUFGenerator, "load", lambda self: self)
    with pytest.raises(GenerationError, match="generation_identity_mismatch"):
        native.generator.load()
    assert native.generator._client.is_closed


def test_verified_identity_retains_original_and_quantized_revisions(tmp_path, monkeypatch):
    native = Native(tmp_path)
    monkeypatch.setattr(GGUFGenerator, "load", lambda self: self)
    assert native.generator.load() is native.generator
    assert native.generator.public_metadata()["revision"] == "gguf-sha256:" + GGUF_SHA256
    native.generator.close()


def test_input_budget_unchanged_with_nonthinking_template(tmp_path):
    native = Native(tmp_path)
    native.tokens = list(range(4097))
    with pytest.raises(GenerationError, match="generation_input_limit"):
        native.generator.generate_bounded(MESSAGES, time.monotonic() + 10)
    assert "/completion" not in native.calls
    native.generator.close()
