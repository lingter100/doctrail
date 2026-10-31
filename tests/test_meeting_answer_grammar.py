"""Decoder plumbing and strict failures; mocked HTTP is not native grammar validation."""
import hashlib
import json
import re
import time

import httpx
import pytest

from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_answer_grammar import (
    ANSWER_GRAMMAR,
    DECODER_POLICY,
    GRAMMAR_SHA256,
    GrammarAnswerGenerator,
)
from doctrail.meeting_answer_v2 import ANSWER_POLICY, grounded_answer_v2
from doctrail.meeting_gguf import GREEDY, LABEL_GRAMMAR, GGUFGenerator
from doctrail.meeting_runtime import MAX_NEW_TOKENS

MESSAGES = [{"role": "user", "content": "Unchanged synthetic test input."}]


class Native:
    def __init__(self):
        self.requests = []
        self.tokens = [1, 2, 3]
        self.change = lambda response: response

    def handler(self, request):
        self.requests.append(request)
        body = json.loads(request.content)
        if request.url.path == "/apply-template":
            assert body["messages"] == MESSAGES
            return httpx.Response(200, json={"prompt": "unchanged synthetic formatted prompt"})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": self.tokens})
        assert request.url.path == "/completion"
        assert body["prompt"] == self.tokens
        assert body["cache_prompt"] is False
        settings = {key: body[key] for key in (*GREEDY, "n_predict", "grammar")}
        response = {"model": "synthetic-alias", "generation_settings": settings,
            "content": '{"status":"abstained","claims":[]}', "tokens_evaluated": len(self.tokens),
            "tokens_predicted": 10, "stop": True, "stop_type": "eos", "truncated": False,
            "timings": {"cache_n": 0, "prompt_n": len(self.tokens)}}
        return httpx.Response(200, json=self.change(response))

    def generator(self, tmp_path):
        # Identity loading is tested in test_meeting_gguf; this test isolates decoder transport.
        generator = GrammarAnswerGenerator("http://127.0.0.1:8093", "x" * 48,
            tmp_path / "unused-manifest.json", transport=httpx.MockTransport(self.handler))
        generator._alias = "synthetic-alias"
        generator._metadata = {"repo_id": "synthetic/model", "revision": "synthetic-revision"}
        return generator


def test_grammar_is_only_fixed_structure_counts_and_id_range():
    words = set(re.findall(r"[A-Za-z][A-Za-z0-9_-]*", ANSWER_GRAMMAR))
    assert words <= {"root", "answered", "abstained", "status", "claims", "claim",
                     "evidence", "text", "string", "id", "quote", "char", "x7F", "x00-",
                     "x1F", "bfnrt", "u", "a-fA-F"}
    assert '(\",\" claim){0,5}' in ANSWER_GRAMMAR
    assert '(\",\" evidence){0,3}' in ANSWER_GRAMMAR
    assert '[0-9]' in ANSWER_GRAMMAR and 'char+' in ANSWER_GRAMMAR
    assert GRAMMAR_SHA256 == hashlib.sha256(ANSWER_GRAMMAR.encode("utf-8")).hexdigest()


def test_metadata_records_exact_decoder_policy_without_changing_model(tmp_path):
    generator = Native().generator(tmp_path)
    metadata = generator.public_metadata()
    assert metadata["repo_id"] == "synthetic/model"
    assert metadata["revision"] == "synthetic-revision"
    assert metadata["answer_decoder"] == {"policy": DECODER_POLICY, "answer_policy": ANSWER_POLICY,
        "grammar_sha256": GRAMMAR_SHA256, "guarantee_scope": "json_structure_only"}
    assert "answer_decoder" not in generator._metadata
    generator.close()


def test_exact_grammar_and_unchanged_greedy_limits_are_observed(tmp_path):
    native = Native()
    generator = native.generator(tmp_path)
    result = generator.generate_bounded(MESSAGES, time.monotonic() + 10)
    assert result.finish_reason == "eos"
    settings = generator.last_effective_config
    assert settings["grammar"] == ANSWER_GRAMMAR
    assert settings["n_predict"] == MAX_NEW_TOKENS == 768
    for key, value in GREEDY.items():
        assert settings[key] == value
    assert GrammarAnswerGenerator.classify_bounded is GGUFGenerator.classify_bounded
    assert settings["grammar"] != LABEL_GRAMMAR
    generator.close()


def test_native_grammar_mismatch_fails_without_retry(tmp_path):
    native = Native()
    def alter(response):
        response["generation_settings"]["grammar"] = ""
        return response
    native.change = alter
    generator = native.generator(tmp_path)
    with pytest.raises(GenerationError, match="generation_effective_config_mismatch"):
        generator.generate_bounded(MESSAGES, time.monotonic() + 10)
    assert [r.url.path for r in native.requests].count("/completion") == 1
    generator.close()


def test_input_overflow_fails_without_pruning_or_generation(tmp_path):
    native = Native()
    native.tokens = list(range(4097))
    generator = native.generator(tmp_path)
    with pytest.raises(GenerationError, match="generation_input_limit"):
        generator.generate_bounded(MESSAGES, time.monotonic() + 10)
    assert not any(r.url.path == "/completion" for r in native.requests)
    generator.close()


def test_expired_deadline_does_not_send_request(tmp_path):
    native = Native()
    generator = native.generator(tmp_path)
    with pytest.raises(GenerationError, match="generation_deadline_exceeded"):
        generator.generate_bounded(MESSAGES, time.monotonic() - 1)
    assert not native.requests
    generator.close()


def test_truncated_output_is_preserved_for_runtime_rejection(tmp_path):
    native = Native()
    native.change = lambda response: {**response, "stop_type": "limit", "tokens_predicted": 768}
    generator = native.generator(tmp_path)
    assert generator.generate_bounded(MESSAGES, time.monotonic() + 10).finish_reason == "length"
    generator.close()


@pytest.mark.parametrize("reference", [{"id": 1, "quote": "The museum closes at six."},
                                       {"id": 0, "quote": "The museum closes at seven."}])
def test_structurally_valid_answer_still_rejects_wrong_quote_or_id(reference):
    source = {0: {"chunk_id": "synthetic", "quote": "The museum closes at six.",
                  "start_offset": 0, "end_offset": 25}}
    raw = json.dumps({"status": "answered", "claims": [
        {"evidence": [reference], "text": "The museum closes at six."}]})
    with pytest.raises(WorkerError, match="generation_invalid_evidence"):
        grounded_answer_v2(raw, source, "en")
