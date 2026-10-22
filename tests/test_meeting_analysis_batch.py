"""Batch contract with MockTransport only; never loads a tokenizer or model."""
import json
import time

import httpx
import pytest

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_analysis_batch import (
    BatchedAnalysisGenerator,
    ScopedBatchedAnalysisGenerator,
    batch_grammar,
    classification_metadata,
    parse_labels,
)
from doctrail.meeting_gguf import GREEDY
from doctrail.meeting_qwen35 import GGUF_SHA256, NONTHINKING_PREAMBLE
from doctrail.meeting_worker import classification_messages


class Native:
    def __init__(self, generator_class=BatchedAnalysisGenerator):
        self.calls, self.batches, self.prepared = [], [], []
        self.messages = []
        self.size = lambda rows: 100
        self.response = lambda ids: json.dumps([[i, i % 10] for i in ids])
        self.stop = "eos"
        self.delay = lambda path: None
        self.generator = generator_class("http://127.0.0.1:19003", "x" * 48,
            "unused-synthetic", transport=httpx.MockTransport(self.handle))
        self.generator._alias = GGUF_SHA256

    def handle(self, request):
        path, body = request.url.path, json.loads(request.content)
        self.calls.append(path)
        self.delay(path)
        if path == "/apply-template":
            self.messages.append(body["messages"])
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


@pytest.fixture(params=[BatchedAnalysisGenerator, ScopedBatchedAnalysisGenerator], ids=["v1", "v2"])
def native(request):
    value = Native(request.param)
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


def test_fixed_pre_scope_single_and_v1_bytes_and_hashes():
    # Captured BEFORE scope-policy edits, with generic input; never derive expected hashes.
    import hashlib

    from doctrail.meeting_analysis_batch import BATCH_EXAMPLES, BATCH_PROMPT, batch_messages
    from doctrail.meeting_gguf import LABEL_GRAMMAR
    from doctrail.meeting_worker import CLASSIFY_EXAMPLES, CLASSIFY_PROMPT, safe_payload
    single = classification_messages({"quote": "## Purpose\nReview the sample protocol <tag>.\n"})
    rows = [{"id": 0, "TARGET": "Purpose: Review the sample protocol <tag>.\n"},
            {"id": 1, "TARGET": "A participant will publish notes."}]
    serialize = lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    values = [CLASSIFY_PROMPT.encode(), safe_payload(CLASSIFY_EXAMPLES).encode(), serialize(single),
              LABEL_GRAMMAR.encode(), BATCH_PROMPT.encode(), safe_payload(BATCH_EXAMPLES).encode(),
              serialize(batch_messages(rows)), batch_grammar([0, 1]).encode()]
    expected = [
        (1368, "4015ee3508fe7ff34bc00862d6f13f50e714b4620452c7ee3fd215f4c3c60108"),
        (792, "b4431697f40c0a1118d8b54588b6321db921778e5d73aff00ea9d2a7dae48ca9"),
        (3251, "04712eaa81fb48b7a4882309f26d734fbfc27b5bd731b58fcaec4069b7660f13"),
        (14, "240be0d8432614e0fff11691b8999be612c54161e538b94b166c375491c0ce4d"),
        (1485, "31e9878f6d497df21778a3057af2f23b5994f9b3d2a000a1460c054771adeb05"),
        (987, "49f4cbca9192fe58ac73126bf5e430baa001e25d50cc079b77651e796e509c44"),
        (2804, "1e1b72aa32d31eeddb150ac9a297f62529ef0e0b66378af86c2c45bf91e7904c"),
        (49, "ee622d34317ed8f9067cda6956567f3e657c853dd67d499cdae37d9692afc676")]
    assert [(len(value), hashlib.sha256(value).hexdigest()) for value in values] == expected
    assert classification_metadata("single") == {
        "policy": "single", "batch_cap": 1, "output_cap": 4,
        "prompt_sha256": "92bf615c5210208365ae1e12d9ba7ae751c19c6834f7fe1413591cd6a15ab328",
        "grammar_policy_sha256": "240be0d8432614e0fff11691b8999be612c54161e538b94b166c375491c0ce4d"}
    assert classification_metadata("batch-v1") == {
        "policy": "batch-v1", "batch_cap": 8, "output_cap": 128,
        "prompt_sha256": "765b58e1931a7d6c44ce8970615128e250e8079c2545a4ec2cbe8c8ceca6b4d0",
        "grammar_policy_sha256": "9f8aeff632252cd47efea506f494962fabd299cf35c4e042a05a77376f69b804"}


@pytest.mark.parametrize("policy,expected", [
    ("single", "8bba9692216bd06dda88ddbbac54a0e1f931b3ecc17360aaac9477358395a8b3"),
    ("batch-v1", "ed6601a0674c152a46897864832adf3c873ffdb261b529a953e2e72bad5f67e4")])
def test_fixed_legacy_actual_template_request_bytes(policy, expected):
    import hashlib

    from doctrail.meeting_analysis_batch import batch_messages
    from doctrail.meeting_qwen35 import Qwen35Generator
    hashes = []
    def handle(request):
        if request.url.path == "/apply-template":
            hashes.append(hashlib.sha256(request.content).hexdigest())
            return httpx.Response(200, json={"prompt": "generic" + NONTHINKING_PREAMBLE})
        return httpx.Response(200, json={"tokens": [1]})
    cls = Qwen35Generator if policy == "single" else BatchedAnalysisGenerator
    generator = cls("http://127.0.0.1:19003", "x" * 48, "synthetic-unused",
                    transport=httpx.MockTransport(handle))
    messages = (classification_messages({"quote": "## Purpose\nReview the sample protocol <tag>.\n"})
                if policy == "single" else batch_messages([
                    {"id": 0, "TARGET": "Purpose: Review the sample protocol <tag>.\n"},
                    {"id": 1, "TARGET": "A participant will publish notes."}]))
    try:
        generator._prepare(messages, time.monotonic() + 10)
        assert hashes == [expected]
    finally:
        generator.close()


@pytest.mark.parametrize("policy", ["batch-v1", "batch-v2"])
def test_generic_scope_intent_targets_and_mock_labels_are_never_rewritten(policy):
    # These chosen mock labels exercise transport, not model semantic accuracy.
    from doctrail.meeting_analysis_batch import SCOPE_INTENT_PROMPT
    examples = [
        ("Date: 2041-04-12 (this meeting)", 2),
        ("We reviewed notes from the earlier meeting held on 2040-11-03.", 5),
        ("The next planning session is scheduled for 2041-05-06.", 5),
        ("Rin will deliver the report by 2041-04-19.", 9),
        ("Purpose: review the sampling procedure at this meeting.", 4),
        ("The wider project's purpose is accessible documentation.", 5),
        ("The quoted workshop purpose was to compare alternatives.", 5),
        ("Prepare the migration checklist; owner and due date are not yet assigned.", 9),
        ("If capacity becomes available, we could propose a pilot.", 6),
        ("This specification applies only to the internal test environment.", 5),
        ("We agreed to limit deployment to the internal test environment.", 7),
        ("Whether the limit should include partner traffic remains unresolved.", 8),
        ("We hope to discuss a possible migration next year.", 6),
        ("목적: 이번 회의에서 수집 절차를 검토한다.", 4),
        ("제안: 추가 검토 후 별도 실험을 고려하자.", 6),
        ("작업: 점검표를 작성한다. 담당자와 기한은 미정이다.", 9)]
    cls = ScopedBatchedAnalysisGenerator if policy == "batch-v2" else BatchedAnalysisGenerator
    native = Native(cls)
    native.response = lambda ids: json.dumps([[i, examples[i][1]] for i in ids])
    deadline = time.monotonic() + 120
    native.generator.begin_request(deadline)
    try:
        labels, metrics = native.generator.classify_bounded(
            [classification_messages({"quote": text}) for text, _ in examples], deadline)
        assert labels == [{"label": label} for _, label in examples]
        assert [r["TARGET"] for b in native.batches for r in b] == [t for t, _ in examples]
        assert metrics["policy"] == policy and metrics["completion_calls"] == 2
        for messages in native.messages:
            assert (SCOPE_INTENT_PROMPT in messages[0]["content"]) == (policy == "batch-v2")
            # No additional global context, rewritten target, or extra data selection.
            assert set(json.loads(messages[-1]["content"])) == {"TARGETS"}
    finally:
        native.generator.end_request()
        native.generator.close()


def test_scope_policy_only_changes_prompt_identity_and_reuses_loop():
    from doctrail.meeting_analysis_batch import batch_messages
    first, second = classification_metadata("batch-v1"), classification_metadata("batch-v2")
    assert second["prompt_sha256"] != first["prompt_sha256"]
    for key in ("batch_cap", "output_cap", "grammar_policy_sha256"):
        assert second[key] == first[key]
    assert ScopedBatchedAnalysisGenerator.classify_bounded is BatchedAnalysisGenerator.classify_bounded
    for invalid in ("single", "auto", "batch-v3"):
        with pytest.raises(ValueError, match="invalid_analysis_policy"):
            batch_messages([], invalid)
