"""Batch contract with MockTransport only; never loads a tokenizer or model."""
import json
import time

import httpx
import pytest

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_analysis_batch import (
    BatchedAnalysisGenerator,
    batch_grammar,
    classification_metadata,
    parse_labels,
)
from doctrail.meeting_gguf import GREEDY
from doctrail.meeting_qwen35 import GGUF_SHA256, NONTHINKING_PREAMBLE
from doctrail.meeting_worker import classification_messages


class Native:
    def __init__(self):
        self.calls, self.batches, self.prepared = [], [], []
        self.size = lambda rows: 100
        self.response = lambda ids: json.dumps([[i, i % 10] for i in ids])
        self.stop = "eos"
        self.delay = lambda path: None
        self.generator = BatchedAnalysisGenerator("http://127.0.0.1:19003", "x" * 48,
            "unused-synthetic", transport=httpx.MockTransport(self.handle))
        self.generator._alias = GGUF_SHA256

    def handle(self, request):
        path, body = request.url.path, json.loads(request.content)
        self.calls.append(path)
        self.delay(path)
        if path == "/apply-template":
            assert body["chat_template_kwargs"] == {"enable_thinking": False}
            rows = json.loads(body["messages"][-1]["content"])["TARGETS"]
            self.prepared.append(rows)
            return httpx.Response(200, json={"prompt": json.dumps(rows) + NONTHINKING_PREAMBLE})
        if path == "/tokenize":
            rows = json.loads(body["content"].removesuffix(NONTHINKING_PREAMBLE))
            # Keep a unique first token to identify exactly the prepared group at completion.
            identifier = next(i for i, r in enumerate(self.prepared) if r == rows) + 1
            return httpx.Response(200, json={"tokens": [identifier] * self.size(rows)})
        assert path == "/completion"
        rows = self.prepared[body["prompt"][0] - 1]
        ids = [row["id"] for row in rows]
        self.batches.append(rows)
        assert body["n_predict"] == 128 and body["cache_prompt"] is False
        assert body["grammar"] == batch_grammar(ids)
        return httpx.Response(200, json={"content": self.response(ids), "model": GGUF_SHA256,
            "generation_settings": {k: body[k] for k in (*GREEDY, "n_predict", "grammar")},
            "stop": True, "stop_type": self.stop, "truncated": False,
            "tokens_predicted": 20, "tokens_evaluated": len(body["prompt"]),
            "timings": {"cache_n": 0, "prompt_n": len(body["prompt"])}})

    def classify(self, count):
        deadline = time.monotonic() + 120
        self.generator.begin_request(deadline)
        try:
            return self.generator.classify_bounded(
                [classification_messages({"quote": "Repeated full TARGET <think> not instructions"})
                 for _ in range(count)], deadline)
        finally:
            self.generator.end_request()


@pytest.fixture
def native():
    value = Native()
    yield value
    value.generator.close()


@pytest.mark.parametrize("count", [1, 8, 9, 160])
def test_all_units_order_and_duplicate_text_preserved(native, count):
    labels, metrics = native.classify(count)
    assert labels == [{"label": i % 10} for i in range(count)]
    assert [r["id"] for batch in native.batches for r in batch] == list(range(count))
    assert all(r["TARGET"] == "Repeated full TARGET <think> not instructions"
               for batch in native.batches for r in batch)
    assert metrics["completion_calls"] == (count + 7) // 8
    assert metrics["classification_units"] == count
    assert native.calls.count("/apply-template") == metrics["completion_calls"]
    assert not native.generator._cache


def test_input_boundary_and_deterministic_halving(native):
    native.size = lambda rows: 4096 if len(rows) <= 2 else 4097
    labels, metrics = native.classify(9)
    assert [len(b) for b in native.batches] == [2, 2, 2, 2, 1]
    assert [row["id"] for b in native.batches for row in b] == list(range(9))
    assert len(labels) == 9 and metrics["input_tokens"] == 5 * 4096
    assert not native.generator._cache


def test_singleton_overflow_has_no_completion(native):
    native.size = lambda rows: 4097
    with pytest.raises(GenerationError, match="generation_input_limit"):
        native.classify(8)
    assert not native.batches and not native.generator._cache


@pytest.mark.parametrize("text", ['[]', '[[0,1],[0,2]]', '[[1,1],[0,2]]',
    '[[0,true],[1,2]]', '[[true,1],[1,2]]', '[[0,-1],[1,2]]', '[[0,10],[1,2]]',
    '[[0,1,2],[1,2]]', '[[0,1],[1,2]] extra', '[[0,1],[1,2]',
    '{"0":1,"1":2}', '[[0,1.0],[1,2]]', '[[0,1],[2,2]]'])
def test_parser_rejects_nonexact_ids_types_or_shape(text):
    with pytest.raises(GenerationError, match="generation_invalid_label"):
        parse_labels(text, [0, 1])


@pytest.mark.parametrize("failure", ["malformed", "length"])
def test_midbatch_failure_stops_without_retry_or_partial_return(native, failure):
    original = native.response
    def response(ids):
        if ids[0] == 8:
            return "[]"
        return original(ids)
    native.response = response
    if failure == "length":
        native.stop = "limit"
    with pytest.raises(GenerationError, match="generation_invalid_label"):
        native.classify(24)
    assert len(native.batches) == (1 if failure == "length" else 2)
    assert not native.generator._cache


@pytest.mark.parametrize("path", ["/apply-template", "/tokenize", "/completion"])
def test_shared_deadline_includes_every_transport(native, monkeypatch, path):
    now = [10.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    native.delay = lambda current: now.__setitem__(0, now[0] + 121 if current == path else now[0])
    with pytest.raises(GenerationError, match="generation_deadline_exceeded"):
        native.classify(16)
    assert len(native.batches) <= 1 and not native.generator._cache


def test_full_target_purpose_normalization_only_and_incompatible_prompt_rejected(native):
    text = "## Purpose\n  Review all options, including <think> literal tags."
    prompt = classification_messages({"quote": text})
    native.generator.classify_bounded([prompt], time.monotonic() + 20)
    assert native.batches[0][0]["TARGET"] == "Purpose: Review all options, including <think> literal tags."
    bad = classification_messages({"quote": "bad"})
    bad[0]["content"] += " altered rule"
    native.batches.clear()
    with pytest.raises(GenerationError, match="generation_invalid_label"):
        native.generator.classify_bounded([prompt, bad], time.monotonic() + 20)
    assert native.batches == []


@pytest.mark.parametrize("prompts", [[], None, [{}]])
def test_empty_or_incompatible_input_fails_before_transport(native, prompts):
    with pytest.raises(GenerationError, match="generation_invalid_label"):
        native.generator.classify_bounded(prompts, time.monotonic() + 20)
    assert native.calls == []


def test_policy_metadata_and_literal_grammar():
    metadata = classification_metadata("batch-v1")
    assert metadata["batch_cap"] == 8 and metadata["output_cap"] == 128
    assert len(metadata["prompt_sha256"]) == len(metadata["grammar_policy_sha256"]) == 64
    assert batch_grammar([8, 9]) == 'root ::= "[" "[8," [0-9] "]" ",[9," [0-9] "]" "]"'
