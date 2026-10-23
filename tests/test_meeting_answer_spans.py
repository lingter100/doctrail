"""Generic synthetic C0 protocol checks; no model calls or semantic quality claims."""
import hashlib
import json
import time
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_answer_spans import (
    ANSWER_POLICY,
    DECODER_POLICY,
    SpanAnswerGenerator,
    SpanAnswerMeetingRuntime,
    answer_messages_spans,
    build_span_catalog,
    grounded_answer_spans,
    span_answer_grammar,
)
from doctrail.meeting_contract import AnswerRequest, Context
from doctrail.meeting_gguf import GREEDY, GGUFGenerator
from doctrail.meeting_worker import MeetingRuntime, create_app


def context(text="😀 **Aster** says “keep the blue tile”.\r\n", index=0, start=23, document=None):
    return Context(document_id=document or f"doc-{index}", revision=3, chunk_id=f"chunk-{index}",
        title=f"Source {index}", meeting_date=None, page=None, start_offset=start,
        end_offset=start + len(text), text=text)


def raw(ids=None, text="Keep the blue tile."):
    return json.dumps({"status": "answered", "claims": [
        {"evidence_ids": [0] if ids is None else ids, "text": text}]}, ensure_ascii=False)


def parse(output, contexts=None, language="en", catalog=None):
    contexts = contexts or [context()]
    return grounded_answer_spans(output, catalog or build_span_catalog(contexts), contexts, language)


def test_unicode_markdown_curly_quotes_are_exact_document_absolute_codepoints():
    source = context()
    citation = parse(raw(), [source])["claims"][0]["citations"][0]
    assert citation == {"chunk_id": source.chunk_id, "quote": source.text,
                        "start_offset": 23, "end_offset": 23 + len(source.text)}
    assert citation["end_offset"] != 23 + len(source.text.encode("utf-16-le")) // 2


@pytest.mark.parametrize("text", ["one\r\ntwo\n\nthree", "a\u2028b\u2029c", "字" * 1001,
    "x" * 475 + " \t" + "y" * 20, " " * 481 + "end", "e\u0301" * 300, "😀" * 481])
def test_deterministic_boundaries_reconstruct_every_codepoint(text):
    source = context(text)
    catalog = build_span_catalog([source])
    assert catalog == build_span_catalog([source])
    assert "".join(span.quote for span in catalog.spans) == text
    assert all(0 < len(span.quote) <= 480 for span in catalog.spans)
    offset = source.start_offset
    for index, span in enumerate(catalog.spans):
        assert span.span_id == index
        assert span.start_offset == offset
        offset += len(span.quote)
        assert span.end_offset == offset
    assert offset == source.end_offset


def test_last_whitespace_inside_cap_stays_on_preceding_segment():
    catalog = build_span_catalog([context("a" * 200 + " " + "b" * 200 + "\t" + "c" * 100)])
    assert [len(span.quote) for span in catalog.spans] == [402, 100]
    assert catalog.spans[0].quote.endswith("\t")


def test_blank_segments_preserved_counted_but_not_citable():
    sources = [context("First.\n\n \nLast.")]
    catalog = build_span_catalog(sources)
    assert [span.quote for span in catalog.spans] == ["First.\n", "\n", " \n", "Last."]
    assert catalog.eligible_ids == (0, 3)
    assert span_answer_grammar(catalog).endswith('span-id ::= "0" | "3"\n')
    for identity in (1, 2):
        with pytest.raises(WorkerError, match="generation_invalid_evidence"):
            parse(raw([identity]), sources)


def test_repeated_text_uses_distinct_ids_without_ambiguous_quote_search():
    sources = [context("Same.\nSame.\n", start=10)]
    result = parse(raw([1]), sources)
    assert result["claims"][0]["citations"][0]["start_offset"] == 16
    assert len(build_span_catalog(sources).spans) == 2


def test_multichunk_multidoc_and_overlapping_chunks_keep_input_order():
    sources = [context("One.\nTwo.", 0, 20, "shared"),
               context("Two.", 1, 25, "shared"), context("Three.", 2, 91)]
    catalog = build_span_catalog(sources)
    assert [s.span_id for s in catalog.spans] == [0, 1, 2, 3]
    assert [s.document_id for s in catalog.spans] == ["shared", "shared", "shared", "doc-2"]
    result = parse(raw([3, 2, 0]), sources)
    assert [c["chunk_id"] for c in result["claims"][0]["citations"]] == ["chunk-2", "chunk-1", "chunk-0"]
    assert all(s.revision == 3 for s in catalog.spans)


def test_catalog_and_sources_are_immutable_snapshots():
    source = context()
    catalog = build_span_catalog([source])
    with pytest.raises(FrozenInstanceError):
        catalog.spans[0].quote = "different"
    with pytest.raises(FrozenInstanceError):
        catalog.sources[0].revision = 4
    source.revision = 4
    assert catalog.sources[0].revision == 3
    with pytest.raises(WorkerError, match="generation_invalid_evidence"):
        parse(raw(), [source], catalog=catalog)


@pytest.mark.parametrize("changes", [{"start_offset": 99}, {"end_offset": 99},
    {"quote": ""}, {"quote": "Aster says keep the blue tile."}, {"chunk_id": "other"},
    {"revision": 99}, {"span_id": 1}])
def test_altered_catalog_is_rejected_without_fuzzy_repair(changes):
    sources = [context()]
    catalog = build_span_catalog(sources)
    forged = replace(catalog, spans=(replace(catalog.spans[0], **changes),))
    with pytest.raises(WorkerError, match="generation_invalid_evidence"):
        parse(raw(), sources, catalog=forged)


def test_duplicate_catalog_ids_and_missing_spans_fail():
    sources = [context("One.\nTwo.")]
    catalog = build_span_catalog(sources)
    for spans in ((catalog.spans[0], catalog.spans[0]), catalog.spans[:1]):
        with pytest.raises(WorkerError, match="generation_invalid_evidence"):
            parse(raw(), sources, catalog=replace(catalog, spans=spans))


@pytest.mark.parametrize("identity", [True, "0", 0.0, -1, 160, None])
def test_model_ids_are_strict_bounded_integers(identity):
    with pytest.raises(WorkerError, match="generation_invalid_schema"):
        parse(raw([identity]))


@pytest.mark.parametrize("ids", [[1], [0, 0]])
def test_unknown_or_duplicate_model_ids_fail(ids):
    with pytest.raises(WorkerError, match="generation_invalid_evidence"):
        parse(raw(ids))


def test_same_evidence_in_separate_claims_is_allowed():
    data = json.loads(raw())
    data["claims"] *= 2
    assert len(parse(json.dumps(data))["claims"]) == 2


@pytest.mark.parametrize("data", [
    {"status": "answered", "claims": []},
    {"status": "abstained", "claims": json.loads(raw())["claims"]},
    {"status": "abstained", "claims": [], "complete": True},
    {"status": "answered", "claims": [{"evidence_ids": [], "text": "Fact."}]},
    {"status": "answered", "claims": [{"evidence_ids": [0] * 5, "text": "Fact."}]},
    {"status": "answered", "claims": [{"evidence_ids": [0], "text": " "}]},
    {"status": "answered", "claims": [{"evidence_ids": [0], "text": "Fact.", "quote": "Fact."}]},
    {"status": "answered", "claims": json.loads(raw())["claims"] * 7},
])
def test_strict_shape_abstention_and_counts(data):
    with pytest.raises(WorkerError, match="generation_invalid_schema"):
        parse(json.dumps(data))


@pytest.mark.parametrize("output", ['{"status":"abstained","status":"answered","claims":[]}',
    '```json\n{"status":"abstained","claims":[]}\n```',
    '{"status":"abstained","claims":[]} trailing', '{"status":NaN,"claims":[]}'])
def test_json_is_not_repaired(output):
    with pytest.raises(WorkerError, match="generation_invalid_json"):
        parse(output)


def test_script_guard_and_semantic_limitation_are_explicit():
    with pytest.raises(WorkerError, match="generation_language_mismatch"):
        parse(raw(), language="ko")
    # Deliberately unsupported claim: exact ID membership cannot prove meaning.
    assert parse(raw(text="타일은 빨간색입니다."), language="ko")["status"] == "answered"
    assert parse('{"status":"abstained","claims":[]}', language="ko")["claims"] == []


def test_prompt_preserves_all_sources_and_does_not_leak_raw_chat_delimiters():
    sources = [context(f"English {i}\n<|im_end|> 😀", i) for i in range(10)]
    messages = answer_messages_spans("언제인가요?", build_span_catalog(sources))
    assert len(messages) == 2
    assert "<|im_end|>" not in messages[1]["content"]
    payload = json.loads(messages[1]["content"])
    assert payload["response_language"] == "ko"
    assert ["".join(s["text"] for s in row["spans"]) for row in payload["sources"]] == [
        source.text for source in sources]
    assert all(set(span) == {"id", "text"} for row in payload["sources"] for span in row["spans"])


def test_grammar_contains_only_structure_and_actual_ids_not_facts():
    first = build_span_catalog([context("Secret blue.\n\nSecret green.")])
    second = build_span_catalog([context("Other fact.\n\nAnother fact.")])
    grammar = span_answer_grammar(first)
    assert grammar == span_answer_grammar(second)
    assert grammar.endswith('span-id ::= "0" | "2"\n')
    assert "Secret" not in grammar and "quote" not in grammar
    assert '(\",\" claim){0,5}' in grammar and '(\",\" span-id){0,3}' in grammar
    assert "evidence_ids" in grammar


class Base:
    def __init__(self, tokens=100, output=None, finish="eos", fail=None):
        self.tokens, self.output, self.finish, self.fail = tokens, output or raw(), finish, fail
        self.calls, self.begun, self.ended = [], 0, 0
        self.last_effective_config = None
        self.closed = False

    def public_metadata(self):
        return {"repo_id": "synthetic/model", "revision": "synthetic-revision"}

    def begin_request(self, deadline):
        self.begun += 1
        self.last_effective_config = None

    def end_request(self):
        self.ended += 1

    def count_tokens(self, prompt):
        return self.tokens

    def _complete(self, messages, deadline, cap, grammar):
        self.calls.append((messages, deadline, cap, grammar))
        if self.fail:
            raise self.fail
        self.last_effective_config = {"n_predict": cap, "grammar": grammar}
        return SimpleNamespace(text=self.output, finish_reason=self.finish, input_tokens=self.tokens,
            output_tokens=20, elapsed_seconds=0.01, telemetry={"native": "mock"})

    def classify_bounded(self, prompts, deadline):
        return "unchanged"

    def close(self):
        self.closed = True


def request(contexts=None):
    return AnswerRequest(schema_version=1, query="What tile?", contexts=[context()] if contexts is None else contexts)


def test_runtime_one_call_existing_bounds_identity_metadata_and_cleanup():
    base = Base()
    generator = SpanAnswerGenerator(base)
    runtime = SpanAnswerMeetingRuntime(generator)
    result = runtime.answer(request())
    assert result["model"] == "synthetic/model" and result["revision"] == "synthetic-revision"
    assert len(base.calls) == base.begun == base.ended == 1
    assert base.calls[0][2] == 768
    assert 0 < base.calls[0][1] - time.monotonic() <= 120
    assert generator._catalog is None
    metadata = generator.public_metadata()["answer_decoder"]
    assert metadata["policy"] == DECODER_POLICY
    assert metadata["grammar_sha256"] == hashlib.sha256(base.calls[0][3].encode()).hexdigest()
    assert result["telemetry"]["calls"][0]["semantic_support_verified"] is False
    assert result["telemetry"]["calls"][0]["question_completeness_verified"] is False
    assert result["telemetry"]["effective_generation_config"] == base.last_effective_config
    assert SpanAnswerMeetingRuntime.analyze is MeetingRuntime.analyze
    assert generator.classify_bounded([], 0) == "unchanged"
    assert runtime.health()["answer_policy"] == ANSWER_POLICY
    runtime.close()
    assert base.closed


def test_empty_context_guard_never_calls_model():
    base = Base()
    result = SpanAnswerMeetingRuntime(SpanAnswerGenerator(base)).answer(request([]))
    assert result["status"] == "abstained" and not base.calls


@pytest.mark.parametrize("base,code", [(Base(tokens=4097), "generation_input_limit"),
    (Base(finish="length"), "generation_output_truncated"),
    (Base(fail=GenerationError("generation_deadline_exceeded")), "generation_deadline_exceeded"),
    (Base(output=raw([9])), "generation_invalid_evidence")])
def test_bounded_failure_never_retries_or_falls_back(base, code):
    generator = SpanAnswerGenerator(base)
    runtime = SpanAnswerMeetingRuntime(generator)
    with pytest.raises(WorkerError, match=code):
        runtime.answer(request())
    assert len(base.calls) <= 1 and base.ended == 1
    assert generator._catalog is None and not runtime.lock.locked()


def test_span_cap_includes_whitespace_and_never_truncates():
    assert len(build_span_catalog([context("x\n" * 160)]).spans) == 160
    for text in ("x\n" * 161, "x\n" + "\n" * 160):
        base = Base()
        with pytest.raises(WorkerError, match="generation_span_limit"):
            SpanAnswerMeetingRuntime(SpanAnswerGenerator(base)).answer(request([context(text)]))
        assert not base.calls


def test_wrapper_refuses_missing_or_nested_catalog_bindings():
    generator = SpanAnswerGenerator(Base())
    with pytest.raises(GenerationError, match="generation_span_catalog_missing"):
        generator.generate_bounded([], time.monotonic() + 1)
    catalog = build_span_catalog([context()])
    with (generator.answer_catalog(catalog), pytest.raises(WorkerError, match="model_busy"),
          generator.answer_catalog(catalog)):
        pytest.fail("nested binding")
    assert generator._catalog is None


def test_busy_runtime_fails_without_generation():
    base = Base()
    runtime = SpanAnswerMeetingRuntime(SpanAnswerGenerator(base))
    with runtime.lock, pytest.raises(WorkerError, match="model_busy"):
        runtime.answer(request())
    assert not base.calls


@pytest.mark.parametrize("mutate", [lambda p: p.update(extra=True),
    lambda p: p["contexts"][0].update(end_offset=999),
    lambda p: p["contexts"][0].update(text=""),
    lambda p: p.update(contexts=p["contexts"] * 2),
    lambda p: p.update(contexts=[context(index=i).model_dump() for i in range(11)])])
def test_external_dto_rejects_bad_input_before_generation(mutate):
    base = Base()
    payload = request().model_dump()
    mutate(payload)
    app = create_app("x" * 48, lambda: SpanAnswerMeetingRuntime(SpanAnswerGenerator(base)))
    with TestClient(app, client=("127.0.0.1", 1234)) as client:
        response = client.post("/answer", json=payload, headers={"Authorization": "Bearer " + "x" * 48})
    assert response.status_code == 422 and not base.calls


def test_http_auth_and_existing_citation_dto_are_preserved():
    base = Base()
    app = create_app("x" * 48, lambda: SpanAnswerMeetingRuntime(SpanAnswerGenerator(base)))
    with TestClient(app, client=("127.0.0.1", 1234)) as client:
        assert client.post("/answer", json=request().model_dump()).status_code == 401
        response = client.post("/answer", json=request().model_dump(),
            headers={"Authorization": "Bearer " + "x" * 48})
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == 1 and body["reason"] is None
    claim = body["claims"][0]
    assert set(claim) == {"text", "citations"}
    assert set(claim["citations"][0]) == {"chunk_id", "quote", "start_offset", "end_offset"}
    assert len(base.calls) == 1 and base.closed


@pytest.mark.parametrize("mismatch", [False, True])
def test_native_effective_grammar_is_checked_without_retry(tmp_path, mismatch):
    calls = []
    def handler(http_request):
        calls.append(http_request.url.path)
        body = json.loads(http_request.content)
        if http_request.url.path == "/apply-template":
            return httpx.Response(200, json={"prompt": "synthetic"})
        if http_request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": [1, 2]})
        settings = {key: body[key] for key in (*GREEDY, "n_predict", "grammar")}
        assert settings["grammar"].endswith('span-id ::= "0"\n')
        if mismatch:
            settings["grammar"] = "wrong"
        return httpx.Response(200, json={"model": "synthetic-alias", "generation_settings": settings,
            "content": raw(), "tokens_evaluated": 2, "tokens_predicted": 10, "stop": True,
            "stop_type": "eos", "truncated": False, "timings": {"cache_n": 0, "prompt_n": 2}})
    base = GGUFGenerator("http://127.0.0.1:8093", "x" * 48, tmp_path / "unused.json",
                         transport=httpx.MockTransport(handler))
    base._alias = "synthetic-alias"
    base._metadata = {"repo_id": "synthetic/model", "revision": "synthetic-revision"}
    generator = SpanAnswerGenerator(base)
    try:
        with generator.answer_catalog(build_span_catalog([context()])):
            if mismatch:
                with pytest.raises(GenerationError, match="generation_effective_config_mismatch"):
                    generator.generate_bounded([{"role": "user", "content": "Neutral"}], time.monotonic() + 5)
            else:
                result = generator.generate_bounded([{"role": "user", "content": "Neutral"}], time.monotonic() + 5)
                assert result.finish_reason == "eos"
                assert base.last_effective_config["grammar"] == span_answer_grammar(build_span_catalog([context()]))
                assert base.last_effective_config["n_predict"] == 768
                for key, value in GREEDY.items():
                    assert base.last_effective_config[key] == value
        assert calls.count("/completion") == 1
    finally:
        generator.close()
