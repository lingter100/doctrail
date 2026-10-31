"""C2-P0 synthetic protocol checks; no model calls or semantic quality claims."""
import hashlib
import json
import random
import threading
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import doctrail.meeting_answer_blocks as module
from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_answer_blocks import (
    ANSWER_POLICY,
    BLOCK_PROMPT_SUFFIX,
    BlockAnswerGenerator,
    BlockAnswerMeetingRuntime,
    answer_messages_blocks,
    block_units,
    build_block_catalog,
    citation_metrics,
    grounded_answer_blocks,
    validate_block_catalog,
)
from doctrail.meeting_answer_spans import ANSWER_PROMPT, span_answer_grammar
from doctrail.meeting_contract import AnswerRequest, Context
from doctrail.meeting_worker import MeetingRuntime, create_app


def context(text="The prism shines\nonly while the lid is open.\n", index=0, start=17, document=None):
    return Context(document_id=document or f"synthetic-{index}", revision=2,
        chunk_id=f"chunk-{index}", title=f"Synthetic source {index}", meeting_date=None,
        page=None, text=text, start_offset=start, end_offset=start + len(text))


def request(contexts=None, query="Under which condition does the prism shine?"):
    return AnswerRequest(schema_version=1, query=query,
        contexts=[context()] if contexts is None else contexts)


def raw(ids=None, text="The prism shines only while the lid is open."):
    return json.dumps({"status": "answered", "claims": [
        {"evidence_ids": [0] if ids is None else ids, "text": text}]}, ensure_ascii=False)


def parse(output, sources=None, language="en", catalog=None):
    sources = sources or [context()]
    return grounded_answer_blocks(output, catalog or build_block_catalog(sources), sources, language)


@pytest.mark.parametrize("text,expected", [
    ("A sentence wraps\nwithout ending here\nand ends here.",
     ("A sentence wraps\nwithout ending here\nand ends here.",)),
    ("Only after approval\nmay the violet lamp be lit.\nThe lid must also be closed.\n",
     ("Only after approval\nmay the violet lamp be lit.\nThe lid must also be closed.\n",)),
    ("First.\n\nSecond.\n \nThird.", ("First.\n", "\n", "Second.\n", " \n", "Third.")),
    ("# Header\nBody wraps\nonto another line.\n## Next\nText",
     ("# Header\n", "Body wraps\nonto another line.\n", "## Next\n", "Text")),
    ("Heading\n=======\nBody.\n", ("Heading\n=======\n", "Body.\n")),
    ("First heading\n---\nSecond paragraph", ("First heading\n---\n", "Second paragraph")),
    ("  ### Title\n\nText.", ("  ### Title\n", "\n", "Text.")),
    ("###No heading\nSame paragraph", ("###No heading\nSame paragraph",)),
    ("A sentence wraps\n    with indentation\nand ends here.",
     ("A sentence wraps\n    with indentation\nand ends here.",)),
])
def test_paragraph_and_heading_boundaries_do_not_split_physical_sentences(text, expected):
    assert block_units(text) == expected


@pytest.mark.parametrize("text", [
    "- One item\n  continues with a condition.\n- Second item\n  with another line.\n",
    "1. The first item\n   continues.\n2. Another item\n   - Nested item\n     continuation\n",
    "* First.\n\n* Second.\n\n  Continued second item.\n",
    "- Text that\ncontinues lazily without indentation.\n- Last.\n",
    "- Item\n  ```python\n  x = 1\n\n  # Literal heading\n  ```\n- Next.\n",
    "- ```\n  literal\n\n  still literal\n  ```\n- Next.\n",
    "- Item\n\n  More detail\n\n  and another continuation.\n",
])
def test_lists_and_their_continuations_are_single_units(text):
    assert block_units(text) == (text,)


@pytest.mark.parametrize("structure", [
    "- Upper\n  continuation\n- Lower\n",
    "| Side | Code |\n| --- | :---: |\n| upper | U |\n| lower | L |\n",
    "```text\none\n\ntwo\n```\n",
    "    first code line\n\n    second code line\n",
])
@pytest.mark.parametrize("gap", ["", "\n", " \n\t\n"])
@pytest.mark.parametrize("colon", [":", "："])
def test_intro_colon_attaches_full_contiguous_list_table_or_code(structure, gap, colon):
    intro = "The following\nitems apply" + colon + "\n"
    joined = intro + gap + structure
    assert block_units(joined + "\nAfterward.") == (joined, "\n", "Afterward.")


def test_nonintro_paragraph_and_heading_colon_are_separate_from_structure():
    assert block_units("A label.\n\n- Item\n") == ("A label.\n", "\n", "- Item\n")
    assert block_units("# Label:\n\n- Item\n") == ("# Label:\n", "\n", "- Item\n")


@pytest.mark.parametrize("text", [
    "```\n# Literal\n\n- Also literal\n| a | b |\n```\n",
    "~~~~custom\none\n~~~\n\n~~~notclosing\n~~~~\n",
    "````lang\n```\n\n````\n",
    "   ```lang\n\nabc\n   ```\n",
    "```unclosed\n\n# text\n- item\n",
    "~~~\n\n```\nanything\n~~~\n",
])
def test_fences_preserve_blanks_marker_lengths_and_unclosed_tail(text):
    assert block_units(text) == (text,)


def test_list_stops_at_unindented_structure_but_not_fenced_blank_lines():
    assert block_units("- Item\n# New section\nBody") == ("- Item\n", "# New section\n", "Body")
    assert block_units("- Item\n\nNew paragraph") == ("- Item\n", "\n", "New paragraph")
    assert block_units("- Item\n```\ncode\n```\n") == ("- Item\n", "```\ncode\n```\n")


def test_pipe_table_requires_delimiter_and_retains_all_rows():
    table = "Left | Right\n:--- | ---:\nup | down\none | two\n"
    assert block_units(table + "After.") == (table, "After.")
    assert block_units("left | right\nThis is prose.") == ("left | right\nThis is prose.",)


@pytest.mark.parametrize("text", [
    "😀 e\u0301 “curly” **bold**\r\ncontinued 한글\r\n\r\nend",
    "first\u2028second\u2028\u2028third\u2029fourth",
    "one\rsecond\r\rthird\n",
    "\n \nfirst\n\t\nlast\n\n",
    "\tcode line\n\n\tmore code\n",
])
def test_unicode_and_mixed_line_endings_reconstruct_exact_codepoint_coordinates(text):
    source = context(text)
    catalog = build_block_catalog([source])
    assert "".join(span.quote for span in catalog.spans) == text
    cursor = source.start_offset
    for span in catalog.spans:
        assert span.start_offset == cursor
        cursor += len(span.quote)
        assert span.end_offset == cursor
    assert cursor == source.end_offset
    assert catalog == build_block_catalog([source])


def test_seeded_random_source_reconstruction_without_missing_or_duplicated_characters():
    rng = random.Random(82418)
    fragments = ["words", "# header", "- list", "  indent", "", "```", "~~~", ":", "😀", "가", "|x|",
                 "|---|", "2. item", "\tcode", "   ", "e\u0301"]
    endings = ["\n", "\r\n", "\r", "\u2028"]
    for _ in range(100):
        text = "".join(rng.choice(fragments) + rng.choice(endings) for _ in range(20))
        catalog = build_block_catalog([context(text)])
        assert "".join(span.quote for span in catalog.spans) == text
        assert sum(len(span.quote) for span in catalog.spans) == len(text)
        assert [span.span_id for span in catalog.spans] == list(range(len(catalog.spans)))


def test_whitespace_is_counted_preserved_and_never_eligible():
    source = context("First.\n\n \nLast.")
    catalog = build_block_catalog([source])
    assert catalog.eligible_ids == (0, 2)
    assert catalog.spans[1].quote == "\n \n"
    assert span_answer_grammar(catalog).endswith('span-id ::= "0" | "2"\n')
    with pytest.raises(WorkerError, match="generation_invalid_evidence"):
        parse(raw([1]), [source])


def test_1024_exact_bound_and_oversize_refusal_without_splitting():
    assert block_units("字" * 1024) == ("字" * 1024,)
    for text in ("字" * 1025, "x" * 600 + "\n" + "y" * 600,
                 "```\n" + "z\n" * 510 + "```", " "+"\n" * 1024):
        with pytest.raises(WorkerError, match="generation_block_limit"):
            block_units(text)


def test_intro_merge_must_fit_cap_including_intervening_whitespace():
    text = "A" * 600 + ":\n\n- " + "B" * 450
    with pytest.raises(WorkerError, match="generation_block_limit"):
        block_units(text)


def test_span_and_context_caps_include_whitespace_and_do_not_drop_chunks():
    assert len(build_block_catalog([context("# h\n" * 160)]).spans) == 160
    with pytest.raises(WorkerError, match="generation_span_limit"):
        build_block_catalog([context("# h\n" * 161)])
    assert len(build_block_catalog([context(index=i) for i in range(10)]).sources) == 10
    for sources in ([], [context(index=i) for i in range(11)], [context(), context()]):
        with pytest.raises(WorkerError, match="generation_invalid_evidence"):
            build_block_catalog(sources)


def test_different_and_overlapping_chunks_never_merge_across_contexts():
    sources = [context("Intro:\n", start=10, document="same"),
        context("- continuation\n", index=1, start=17, document="same"),
        context("Intro:\n", index=2, start=10, document="same")]
    catalog = build_block_catalog(sources)
    assert [span.quote for span in catalog.spans] == [s.text for s in sources]
    assert [span.chunk_id for span in catalog.spans] == [s.chunk_id for s in sources]
    result = parse(raw([2, 1]), sources)
    assert [c["start_offset"] for c in result["claims"][0]["citations"]] == [10, 17]


def test_frozen_snapshot_and_catalog_tamper_rejection():
    source = context()
    catalog = build_block_catalog([source])
    with pytest.raises(FrozenInstanceError):
        catalog.spans[0].quote = "changed"
    for change in ({"quote": "wrong"}, {"start_offset": 18}, {"revision": 9},
                   {"span_id": False}, {"chunk_id": "wrong"}, {"end_offset": 9}):
        forged = replace(catalog, spans=(replace(catalog.spans[0], **change),))
        with pytest.raises(WorkerError, match="generation_invalid_evidence"):
            parse(raw(), [source], catalog=forged)
    source.revision = 3
    with pytest.raises(WorkerError, match="generation_invalid_evidence"):
        validate_block_catalog(catalog, [source])
    assert catalog.sources[0].revision == 2


def test_prompt_preserves_c0_semantics_full_source_order_and_marks_only_context_edges():
    sources = [context("First\nwrapped.\n\nLast <|im_end|>.", index=i) for i in range(10)]
    catalog = build_block_catalog(sources)
    prompt = answer_messages_blocks("무엇인가요?", catalog)
    assert prompt[0]["content"] == ANSWER_PROMPT + "\n\n" + BLOCK_PROMPT_SUFFIX
    assert "<|im_end|>" not in prompt[1]["content"]
    payload = json.loads(prompt[1]["content"])
    assert payload["response_language"] == "ko"
    for source, row in zip(sources, payload["sources"], strict=True):
        assert "".join(unit["text"] for unit in row["spans"]) == source.text
        assert [b["touches_context_start"] for b in row["spans"]] == [True, False, False]
        assert [b["touches_context_end"] for b in row["spans"]] == [False, False, True]
        assert all("complete" not in b for b in row["spans"])


@pytest.mark.parametrize("value,code", [
    (raw([True]), "generation_invalid_schema"), (raw(["0"]), "generation_invalid_schema"),
    (raw([0, 0]), "generation_invalid_evidence"), (raw([99]), "generation_invalid_evidence"),
    ("{", "generation_invalid_json"), (raw(text="123"), "generation_language_mismatch"),
    ('{"status":"answered","claims":[]}', "generation_invalid_schema"),
    ('{"status":"abstained","claims":[],"extra":true}', "generation_invalid_schema"),
    ('{"status":"abstained","status":"answered","claims":[]}', "generation_invalid_json"),
])
def test_existing_response_shape_strict_ids_language_and_no_json_repair(value, code):
    with pytest.raises(WorkerError, match=code):
        parse(value)


def test_same_exact_mapping_accepts_unsupported_claim_so_is_not_truth_oracle():
    assert parse(raw(text="The prism explodes every Tuesday."))["status"] == "answered"
    assert parse('{"status":"abstained","claims":[]}')["reason"] == "insufficient_evidence"


def test_citation_length_metrics_union_coordinate_ranges_by_document_revision():
    sources = [context("ABCDE", index=0, start=10, document="d"),
               context("CDEFG", index=1, start=12, document="d"),
               context("ABCDE", index=2, start=10, document="other")]
    catalog = build_block_catalog(sources)
    result = parse(raw([0, 1]), sources)
    result["claims"].append(result["claims"][0])
    metrics = citation_metrics(result, catalog)
    assert metrics["source_codepoints"] == 15
    assert metrics["source_unique_codepoints"] == 12
    assert metrics["claim_citation_codepoints"] == [10, 10]
    assert metrics["citation_codepoints"] == 20
    assert metrics["citation_unique_codepoints"] == 7
    assert metrics["citation_duplicate_codepoints"] == 13
    assert metrics["unit_codepoints"] == [5, 5, 5]


class Base:
    def __init__(self, output=None, tokens=100, finish="eos", output_tokens=30):
        self.output = output if output is not None else raw()
        self.tokens, self.finish, self.output_tokens = tokens, finish, output_tokens
        self.calls, self.begun, self.ended = [], [], 0
        self.last_effective_config, self.cache, self.closed = None, [], False

    def public_metadata(self):
        return {"repo_id": "synthetic/model", "revision": "synthetic-revision",
                "runtime": {"max_new_tokens": 768, "deadline_seconds": 120}}

    def begin_request(self, deadline):
        self.begun.append(deadline)
        self.last_effective_config = None

    def end_request(self):
        self.ended += 1
        self.cache.clear()

    def count_tokens(self, prompt):
        self.cache.append(prompt)
        return self.tokens

    def _complete(self, prompt, deadline, cap, grammar):
        self.calls.append((prompt, deadline, cap, grammar))
        if isinstance(self.output, BaseException):
            raise self.output
        self.last_effective_config = {"n_predict": cap, "grammar": grammar}
        return SimpleNamespace(text=self.output, finish_reason=self.finish, input_tokens=self.tokens,
            output_tokens=self.output_tokens, elapsed_seconds=0.01,
            telemetry={"native_timings": {"prompt_n": self.tokens, "prompt_ms": 3,
                "private": "DO_NOT_LOG"}, "raw_text": "DO_NOT_LOG"})

    def classify_bounded(self, prompts, deadline):
        return "unchanged"

    def close(self):
        self.closed = True


def runtime(**kwargs):
    base = Base(**kwargs)
    return BlockAnswerMeetingRuntime(BlockAnswerGenerator(base)), base


def assert_clean(rt, base):
    assert not rt.lock.locked() and rt.generator._catalog is None
    assert rt.generator._called is False
    assert not base.cache
    assert base.ended == len(base.begun)


def test_single_call_fixed_budget_exact_output_and_source_free_telemetry():
    rt, base = runtime()
    result = rt.answer(request())
    assert len(base.calls) == len(base.begun) == base.ended == 1
    assert base.calls[0][1] == base.begun[0]
    assert 0 < base.calls[0][1] - module.time.monotonic() <= 90
    assert base.calls[0][2] == 384
    assert result["claims"][0]["citations"][0]["quote"] == request().contexts[0].text
    assert result["telemetry"]["completion_attempts"] == 1
    assert result["telemetry"]["semantic_support_verified"] is False
    assert result["telemetry"]["question_completeness_verified"] is False
    assert result["telemetry"]["source_codepoints"] == len(request().contexts[0].text)
    serialized = json.dumps(result["telemetry"])
    assert "DO_NOT_LOG" not in serialized and "prism" not in serialized
    assert result["telemetry"]["calls"][0]["native_timings"] == {"prompt_n": 100, "prompt_ms": 3}
    assert all(name in result["telemetry"] for name in ("preprocessing_ms", "cleanup_ms", "elapsed_ms"))
    metadata = rt.generator.public_metadata()
    assert metadata["runtime"]["max_new_tokens"] == 384
    assert metadata["runtime"]["deadline_seconds"] == 90
    assert metadata["answer_decoder"]["grammar_sha256"] == hashlib.sha256(base.calls[0][3].encode()).hexdigest()
    assert rt.health()["answer_policy"] == ANSWER_POLICY
    assert rt.health()["answer_limits"]["completion_calls"] == 1
    assert BlockAnswerMeetingRuntime.analyze is MeetingRuntime.analyze
    assert rt.generator.classify_bounded([], 0) == "unchanged"
    assert_clean(rt, base)


@pytest.mark.parametrize("kwargs,code,calls", [
    ({"tokens": 4097}, "generation_input_limit", 0),
    ({"output_tokens": 385}, "generation_token_limit", 1),
    ({"finish": "length"}, "generation_output_truncated", 1),
    ({"output": "{"}, "generation_invalid_json", 1),
    ({"output": raw([99])}, "generation_invalid_evidence", 1),
    ({"output": GenerationError("generation_deadline_exceeded")}, "generation_deadline_exceeded", 1),
    ({"output": GenerationError("generation_effective_config_mismatch")}, "generation_effective_config_mismatch", 1),
    ({"output": RuntimeError("DO_NOT_LOG")}, "generation_failed", 1),
])
def test_failures_are_terminal_do_not_retry_and_keep_safe_operational_telemetry(kwargs, code, calls):
    rt, base = runtime(**kwargs)
    with pytest.raises(WorkerError, match=code) as caught:
        rt.answer(request())
    assert len(base.calls) == calls
    assert rt.last_telemetry["completion_attempts"] == calls
    assert rt.last_telemetry["error_code"] == code
    assert "DO_NOT_LOG" not in str(caught.value) + json.dumps(rt.last_telemetry)
    if calls:
        assert "completion_wrapper_ms" in rt.last_telemetry["calls"][0]
    assert_clean(rt, base)


def test_oversize_before_model_and_empty_guard_no_native_calls():
    rt, base = runtime()
    with pytest.raises(WorkerError, match="generation_block_limit"):
        rt.answer(request([context("z" * 1025)]))
    assert not base.calls and not rt.last_telemetry["completion_attempts"]
    result = rt.answer(request([]))
    assert result["reason"] == "insufficient_evidence" and not base.calls
    assert "error_code" not in result["telemetry"]
    assert_clean(rt, base)


@pytest.mark.parametrize("phase", ["prepare", "native", "cleanup"])
def test_deadline_includes_preprocessing_native_and_cleanup(monkeypatch, phase):
    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    rt, base = runtime()
    method = {"prepare": "count_tokens", "native": "_complete", "cleanup": "end_request"}[phase]
    original = getattr(base, method)
    def overdue(*args):
        result = original(*args)
        clock[0] = 190.0
        return result
    setattr(base, method, overdue)
    with pytest.raises(WorkerError, match="generation_deadline_exceeded"):
        rt.answer(request())
    assert base.begun == [190.0]
    assert len(base.calls) == (0 if phase == "prepare" else 1)
    assert rt.last_telemetry["elapsed_ms"] == 90000
    assert_clean(rt, base)


def test_native_interrupt_and_cleanup_exception_release_lock_and_clear_request():
    rt, base = runtime(output=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        rt.answer(request())
    assert_clean(rt, base)
    base.output = raw()
    original = base.end_request
    def broken_cleanup():
        original()
        raise RuntimeError("DO_NOT_LOG")
    base.end_request = broken_cleanup
    with pytest.raises(WorkerError, match="generation_cleanup_failed"):
        rt.answer(request())
    assert_clean(rt, base)


def test_invalid_request_revalidated_no_generation_and_busy_does_not_touch_active_state():
    rt, base = runtime()
    invalid = request()
    invalid.contexts[0].end_offset += 1
    with pytest.raises(WorkerError, match="invalid_request"):
        rt.answer(invalid)
    assert not base.calls and not base.begun and not base.ended
    with rt.lock:
        rt.last_telemetry = {"active": True}
        with pytest.raises(WorkerError, match="model_busy"):
            rt.answer(request())
        assert rt.last_telemetry == {"active": True}
    assert_clean(rt, base)


def test_bound_generator_refuses_nested_catalog_and_second_completion():
    rt, base = runtime()
    gen = rt.generator
    with pytest.raises(GenerationError, match="generation_span_catalog_missing"):
        gen.generate_bounded([], module.time.monotonic() + 90)
    catalog = build_block_catalog([context()])
    with gen.answer_catalog(catalog):
        with pytest.raises(WorkerError, match="model_busy"), gen.answer_catalog(catalog):
            pytest.fail("nested")
        gen.generate_bounded([], module.time.monotonic() + 90)
        with pytest.raises(WorkerError, match="generation_call_limit"):
            gen.generate_bounded([], module.time.monotonic() + 90)
    assert len(base.calls) == 1 and gen._catalog is None


@pytest.mark.parametrize("first_fails", [False, True])
def test_telemetry_is_finalized_under_lock_and_next_request_cannot_contaminate_it(first_fails):
    rt, base = runtime(output="{" if first_fails else raw())
    unlocked, done = threading.Event(), threading.Event()
    results, published = {}, []

    class ReleaseBarrier:
        def __init__(self):
            self.inner = threading.Lock()
            self.count = 0

        def acquire(self, blocking=False):
            return self.inner.acquire(blocking=blocking)

        def locked(self):
            return self.inner.locked()

        def release(self):
            published.append(rt.last_telemetry)
            self.count += 1
            first = self.count == 1
            self.inner.release()
            if first:
                unlocked.set()
                assert done.wait(5)

    rt.lock = ReleaseBarrier()
    def call(name, second=False):
        try:
            if second:
                assert unlocked.wait(5)
            results[name] = rt.answer(request([]) if second else request())
        except Exception as error:  # noqa: BLE001 - assert thread errors on main thread
            results[name] = error
        finally:
            if second:
                done.set()
    first = threading.Thread(target=call, args=("first",))
    second = threading.Thread(target=call, args=("second", True))
    first.start()
    second.start()
    first.join(10)
    second.join(10)
    assert not first.is_alive() and not second.is_alive()
    assert results["second"]["telemetry"] is published[1] is rt.last_telemetry
    assert "error_code" not in results["second"]["telemetry"]
    assert results["second"]["telemetry"]["completion_attempts"] == 0
    if first_fails:
        assert isinstance(results["first"], WorkerError)
        assert published[0]["error_code"] == "generation_invalid_json"
    else:
        assert results["first"]["telemetry"] is published[0]
        assert results["first"]["telemetry"]["completion_attempts"] == 1
    assert_clean(rt, base)


def test_http_auth_exact_answer_contract_safe_error_and_close():
    rt, base = runtime()
    app = create_app("x" * 48, lambda: rt)
    headers = {"Authorization": "Bearer " + "x" * 48}
    with TestClient(app, client=("127.0.0.1", 1234)) as client:
        assert client.post("/answer", json=request().model_dump()).status_code == 401
        response = client.post("/answer", json=request().model_dump(), headers=headers)
        assert response.status_code == 200
        citation = response.json()["claims"][0]["citations"][0]
        assert set(citation) == {"chunk_id", "quote", "start_offset", "end_offset"}
        base.output = RuntimeError("private content")
        failed = client.post("/answer", json=request().model_dump(), headers=headers)
        assert failed.status_code == 503 and failed.json()["error"] == "generation_failed"
        assert "private" not in failed.text
    assert base.closed
