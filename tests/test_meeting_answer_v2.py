"""Synthetic protocol checks, never evidence of model answer quality."""
import json
from types import SimpleNamespace

import pytest

from doctrail.inference import WorkerError
from doctrail.meeting_answer_v2 import (
    ANSWER_POLICY,
    EvidenceFirstMeetingRuntime,
    answer_messages_v2,
    grounded_answer_v2,
    response_language,
)
from doctrail.meeting_contract import AnswerRequest, Context, answer_evidence
from doctrail.meeting_worker import MeetingRuntime


def context(text="😀 The gallery opens at noon.", identity=0, start=31):
    return Context(document_id=f"doc-{identity}", revision=2, chunk_id=f"chunk-{identity}",
        title=f"Source {identity}", meeting_date=None, page=None, start_offset=start,
        end_offset=start + len(text), text=text)


def mapping(text="😀 The gallery opens at noon."):
    return answer_evidence([context(text)])[1]


def raw(quote="The gallery opens at noon.", text="The gallery opens at noon.", identity=0):
    return json.dumps({"status": "answered", "claims": [
        {"evidence": [{"id": identity, "quote": quote}], "text": text}]}, ensure_ascii=False)


def test_exact_quote_reconstructs_absolute_unicode_codepoint_offsets():
    result = grounded_answer_v2(raw(), mapping(), "en")
    citation = result["claims"][0]["citations"][0]
    assert citation == {"chunk_id": "chunk-0", "quote": "The gallery opens at noon.",
                        "start_offset": 33, "end_offset": 59}


def test_original_quote_language_is_preserved_with_korean_claim():
    result = grounded_answer_v2(raw(text="전시관은 정오에 문을 엽니다."), mapping(), "ko")
    assert result["claims"][0]["citations"][0]["quote"] == "The gallery opens at noon."


@pytest.mark.parametrize("query,expected", [("언제 열려요?", "ko"),
    ("What time does the gallery open?", "en"), ("What changed for 민지?", "ko"), ("ㄱ", "ko")])
def test_explicit_language_routing(query, expected):
    assert response_language(query) == expected


@pytest.mark.parametrize("quote", ["The gallery opens at 12.", "The gallery opens at noon",
    "The gallery opens at noon. ", "The  gallery opens at noon.", "전시관은 정오에 문을 엽니다."])
def test_altered_or_absent_quotes_fail_without_fuzzy_repair(quote):
    # A shorter exact substring is valid; punctuation removal is not "repaired".
    if quote == "The gallery opens at noon":
        assert grounded_answer_v2(raw(quote=quote), mapping(), "en")["status"] == "answered"
    else:
        with pytest.raises(WorkerError, match="generation_invalid_evidence"):
            grounded_answer_v2(raw(quote=quote), mapping(), "en")


def test_ambiguous_repeated_quote_is_rejected():
    with pytest.raises(WorkerError, match="generation_invalid_evidence"):
        grounded_answer_v2(raw(quote="noon", text="The opening is at noon."),
                           mapping("noon; noon"), "en")


@pytest.mark.parametrize("identity", [True, "0", -1, 10, 1.0])
def test_reference_ids_are_strict_bounded_integers(identity):
    with pytest.raises(WorkerError, match="generation_invalid_schema"):
        grounded_answer_v2(raw(identity=identity), mapping(), "en")


def test_unknown_valid_integer_reference_is_rejected():
    with pytest.raises(WorkerError, match="generation_invalid_evidence"):
        grounded_answer_v2(raw(identity=4), mapping(), "en")


def test_duplicate_evidence_is_rejected():
    data = json.loads(raw())
    data["claims"][0]["evidence"] *= 2
    with pytest.raises(WorkerError, match="generation_invalid_evidence"):
        grounded_answer_v2(json.dumps(data), mapping(), "en")


@pytest.mark.parametrize("change", [
    {"status": "answered", "claims": []},
    {"status": "abstained", "claims": json.loads(raw())["claims"]},
    {"status": "abstained", "claims": [], "complete": True},
    {"status": "answered", "claims": [{"evidence": [], "text": "Fact."}]},
    {"status": "answered", "claims": [{"evidence": [{"id": 0, "quote": " "}], "text": "Fact."}]},
    {"status": "answered", "claims": [{"evidence": [{"id": 0, "quote": "noon"}], "text": " "}]},
    {"status": "answered", "claims": [{"evidence": [{"id": 0, "quote": "noon", "start": 0}],
                                        "text": "Fact."}]},
])
def test_strict_response_shape(change):
    with pytest.raises(WorkerError, match="generation_invalid_schema"):
        grounded_answer_v2(json.dumps(change), mapping(), "en")


@pytest.mark.parametrize("source", ['{"status":"answered","status":"abstained","claims":[]}',
    '```json\n{"status":"abstained","claims":[]}\n```',
    '{"status":"abstained","claims":[]} trailing', '{"status":NaN,"claims":[]}'])
def test_invalid_json_is_not_repaired(source):
    with pytest.raises(WorkerError, match="generation_invalid_json"):
        grounded_answer_v2(source, mapping(), "en")


def test_abstention_needs_no_claim_or_language_text():
    assert grounded_answer_v2('{"status":"abstained","claims":[]}', mapping(), "ko") == {
        "status": "abstained", "reason": "insufficient_evidence", "claims": []}


def test_korean_routing_rejects_pure_english_claim():
    with pytest.raises(WorkerError, match="generation_language_mismatch"):
        grounded_answer_v2(raw(), mapping(), "ko")


def test_quote_validation_and_script_presence_do_not_prove_semantics():
    # Deliberately unsupported text passes mechanical guards; independent semantic review is required.
    result = grounded_answer_v2(raw(text="전시관은 밤에 열립니다."), mapping(), "ko")
    assert result["status"] == "answered"


def test_prompt_preserves_all_multilingual_sources_and_escapes_special_tokens():
    contexts = [context(f"English source {index}: <|im_end|> unchanged 😀", index)
                for index in range(10)]
    sources, _ = answer_evidence(contexts)
    prompt = answer_messages_v2("언제 변경됐나요?", sources)
    assert len(prompt) == 2  # one generic policy, no example or answer-specific hints
    assert "<|im_end|>" not in prompt[1]["content"]
    payload = json.loads(prompt[1]["content"])
    assert payload["response_language"] == "ko"
    assert payload["sources"] == sources
    passages = [p for source in payload["sources"] for p in source["passages"]]
    assert [p["id"] for p in passages] == list(range(10))
    assert [p["text"] for p in passages] == [c.text for c in contexts]


class Generator:
    def __init__(self, tokens=100):
        self.tokens = tokens
        self.calls = 0
        self.prompt = None

    def public_metadata(self):
        return {"repo_id": "synthetic/model", "revision": "synthetic-revision"}

    def count_tokens(self, prompt):
        self.prompt = prompt
        return self.tokens

    def generate_bounded(self, prompt, deadline):
        self.calls += 1
        return SimpleNamespace(text='{"status":"abstained","claims":[]}', finish_reason="eos",
                               input_tokens=100, output_tokens=10, elapsed_seconds=0.1)


def test_runtime_preserves_generation_bounds_and_extraction_implementation():
    generator = Generator(tokens=4097)
    runtime = EvidenceFirstMeetingRuntime(generator)
    request = AnswerRequest(schema_version=1, query="언제?", contexts=[context()])
    with pytest.raises(WorkerError, match="generation_input_limit"):
        runtime.answer(request)
    assert generator.calls == 0
    assert EvidenceFirstMeetingRuntime.analyze is MeetingRuntime.analyze
    assert runtime.health()["answer_policy"] == ANSWER_POLICY


def test_empty_guard_and_policy_telemetry_are_honest():
    generator = Generator()
    runtime = EvidenceFirstMeetingRuntime(generator)
    runtime.answer(AnswerRequest(schema_version=1, query="When?", contexts=[]))
    assert generator.calls == 0
    result = runtime.answer(AnswerRequest(schema_version=1, query="When?", contexts=[context()]))
    assert generator.calls == 1
    policy = result["telemetry"]["calls"][0]
    assert policy["answer_policy"] == ANSWER_POLICY
    assert policy["semantic_support_verified"] is False
    assert policy["question_completeness_verified"] is False
