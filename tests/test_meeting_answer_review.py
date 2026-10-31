"""Synthetic scripted C1 protocol tests; no model inference or quality measurement."""
import copy
import hashlib
import json
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import doctrail.meeting_answer_review as module
from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_answer_review import (
    ReviewAnswerGenerator,
    ReviewAnswerMeetingRuntime,
    parse_review,
    review_grammar,
)
from doctrail.meeting_answer_spans import (
    answer_messages_spans,
    build_span_catalog,
    span_answer_grammar,
)
from doctrail.meeting_contract import AnswerRequest, Context
from doctrail.meeting_worker import MeetingRuntime, create_app


def request(empty=False, query="Which shape is displayed?"):
    text = "😀 The displayed shape is a circle.\n\nThe square is hidden."
    return AnswerRequest(schema_version=1, query=query, contexts=[] if empty else [Context(
        document_id="synthetic-shape", revision=4, chunk_id="shape-1", title="Synthetic shapes",
        meeting_date=None, page=None, start_offset=11, end_offset=11 + len(text), text=text)])


def draft(abstained=False, text="The displayed shape is a circle."):
    return {"status": "abstained" if abstained else "answered", "claims": [] if abstained else [
        {"evidence_ids": [0], "text": text}]}


def review(verdict="entailed", covered="covered", sufficient="sufficient", language=True,
           count=1):
    return {"claim_checks": [{"claim_index": i, "verdict": verdict} for i in range(count)],
        "question_parts": [{"description": "Identify displayed shape", "claim_indices": list(range(count)),
                            "status": covered}],
        "source_sufficiency": sufficient, "language_ok": language}


class Script:
    def __init__(self, outputs, *, tokens=None, hook=None):
        self.outputs = list(outputs)
        self.tokens = iter(tokens or [100] * 10)
        self.calls, self.counted, self.begun, self.ended = [], [], [], 0
        self.hook = hook
        self.last_effective_config = None
        self.closed = False

    def public_metadata(self):
        return {"repo_id": "synthetic/model", "revision": "synthetic-revision"}

    def begin_request(self, deadline):
        self.begun.append(deadline)
        self.last_effective_config = None

    def end_request(self):
        self.ended += 1

    def count_tokens(self, prompt):
        self.counted.append(copy.deepcopy(prompt))
        return next(self.tokens)

    def _complete(self, messages, deadline, cap, grammar):
        self.calls.append((copy.deepcopy(messages), deadline, cap, grammar))
        if self.hook:
            self.hook(len(self.calls))
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        if not isinstance(output, str):
            output = json.dumps(output)
        self.last_effective_config = {"n_predict": cap, "grammar": grammar}
        return SimpleNamespace(text=output, finish_reason="eos", input_tokens=100,
            output_tokens=20, elapsed_seconds=0.01, telemetry={"native_timings": {"prompt_n": 100},
                "raw_text": "DO_NOT_LOG", "question": "DO_NOT_LOG"})

    def classify_bounded(self, prompts, deadline):
        return "unchanged"

    def close(self):
        self.closed = True


def runtime(outputs, **kwargs):
    base = Script(outputs, **kwargs)
    generator = ReviewAnswerGenerator(base)
    return ReviewAnswerMeetingRuntime(generator), base


def assert_clean(rt, base):
    assert not rt.lock.locked()
    assert rt.generator._catalog is None
    assert rt.generator.current_stage is None
    assert rt.generator._claim_count is None
    assert len(base.begun) == base.ended


def test_two_call_acceptance_preserves_c0_prompt_decoder_exact_citations_and_deadline():
    rt, base = runtime([draft(), review()])
    result = rt.answer(request())
    catalog = build_span_catalog(request().contexts)
    assert base.calls[0][0] == answer_messages_spans(request().query, catalog)
    assert base.calls[0][3] == span_answer_grammar(catalog)
    assert base.calls[1][3] == review_grammar(1)
    assert [c[2] for c in base.calls] == [768, 512]
    assert {c[1] for c in base.calls} == set(base.begun)
    assert result["claims"][0]["citations"] == [{"chunk_id": "shape-1",
        "quote": catalog.spans[0].quote, "start_offset": 11,
        "end_offset": 11 + len(catalog.spans[0].quote)}]
    assert result["status"] == "answered" and result["reason"] is None
    assert len(result["telemetry"]["calls"]) == result["telemetry"]["completion_attempts"] == 2
    assert result["telemetry"]["semantic_support_verified"] is False
    assert result["telemetry"]["question_completeness_verified"] is False
    assert "DO_NOT_LOG" not in json.dumps(result["telemetry"])
    metadata = rt.generator.public_metadata()
    assert metadata["answer_decoder"]["grammar_sha256"] == hashlib.sha256(
        base.calls[0][3].encode()).hexdigest()
    assert metadata["answer_review"]["grammar_sha256"] == hashlib.sha256(
        base.calls[1][3].encode()).hexdigest()
    assert_clean(rt, base)


@pytest.mark.parametrize("rejected", [review(verdict="not_entailed"), review(verdict="uncertain"),
    review(covered="missing"), review(covered="uncertain"), review(sufficient="insufficient"),
    review(sufficient="uncertain"), review(language=False)])
def test_exactly_one_revision_for_each_semantic_rejection_condition(rejected):
    rt, base = runtime([draft(), rejected, draft(text="A circle is displayed."), review()])
    result = rt.answer(request())
    assert len(base.calls) == 4
    assert [c[2] for c in base.calls] == [768, 512, 768, 512]
    assert sum(c[2] for c in base.calls) == 2560
    assert [c["stage"] for c in result["telemetry"]["calls"]] == ["D0", "V0", "D1", "V1"]
    payloads = [json.loads(c[0][-1]["content"]) for c in base.calls]
    assert all(p["sources"] == payloads[0]["sources"] for p in payloads)
    assert all(p["question"] == request().query for p in payloads)
    assert payloads[2]["draft"] == draft() and payloads[2]["review"] == rejected
    assert payloads[3]["draft"] == draft(text="A circle is displayed.")
    assert set(payloads[3]) == {"question", "response_language", "sources", "draft"}
    assert base.calls[1][0][0] == base.calls[3][0][0]
    assert base.calls[0][3] == base.calls[2][3]
    assert len({c[1] for c in base.calls}) == len(base.begun) == 1
    assert_clean(rt, base)


def test_real_abstention_candidate_needs_insufficient_sources_and_missing_requirement():
    abstain_review = review(count=0, covered="missing", sufficient="insufficient")
    rt, base = runtime([draft(True), abstain_review])
    result = rt.answer(request())
    assert result["status"] == "abstained" and result["reason"] == "insufficient_evidence"
    assert len(base.calls) == 2
    assert base.calls[1][3] == review_grammar(0)
    assert_clean(rt, base)


@pytest.mark.parametrize("sufficiency,coverage", [
    ("sufficient", "missing"), ("uncertain", "missing"), ("insufficient", "uncertain")])
def test_wrong_abstention_is_revised_not_counted_as_success(sufficiency, coverage):
    rt, base = runtime([draft(True), review(count=0, covered=coverage, sufficient=sufficiency),
                        draft(), review()])
    assert rt.answer(request())["status"] == "answered"
    assert len(base.calls) == 4
    assert_clean(rt, base)


def test_revision_can_produce_reviewed_abstention():
    rt, base = runtime([draft(), review(verdict="not_entailed", sufficient="insufficient"),
        draft(True), review(count=0, covered="missing", sufficient="insufficient")])
    assert rt.answer(request())["reason"] == "insufficient_evidence"
    assert len(base.calls) == 4
    assert_clean(rt, base)


def test_final_semantic_rejection_is_an_error_not_insufficient_evidence():
    rt, base = runtime([draft(), review(verdict="uncertain"), draft(), review(covered="missing")])
    with pytest.raises(WorkerError, match="generation_semantic_rejected"):
        rt.answer(request())
    assert len(base.calls) == 4 and rt.last_telemetry["error_code"] == "generation_semantic_rejected"
    assert rt.last_telemetry["completion_attempts"] == 4
    assert_clean(rt, base)


def test_model_acceptance_is_not_an_independent_oracle():
    # A scripted judge accepts a deliberately false shape. The policy cannot prove truth.
    rt, _ = runtime([draft(text="A triangle is displayed."), review()])
    result = rt.answer(request())
    assert result["status"] == "answered"
    assert result["telemetry"]["semantic_support_verified"] is False


@pytest.mark.parametrize("mutate", [
    lambda x: x.update(extra="forbidden"),
    lambda x: x.update(language_ok=1),
    lambda x: x.update(source_sufficiency="yes"),
    lambda x: x.update(claim_checks=[]),
    lambda x: x["claim_checks"].append(x["claim_checks"][0]),
    lambda x: x["claim_checks"][0].update(claim_index=1),
    lambda x: x["claim_checks"][0].update(claim_index=True),
    lambda x: x["claim_checks"][0].update(claim_index="0"),
    lambda x: x["claim_checks"][0].update(verdict="supported"),
    lambda x: x.update(question_parts=[]),
    lambda x: x.update(question_parts=x["question_parts"] * 7),
    lambda x: x["question_parts"][0].update(description=" "),
    lambda x: x["question_parts"][0].update(description="x" * 121),
    lambda x: x["question_parts"][0].update(description="\ud800"),
    lambda x: x["question_parts"][0].update(claim_indices=[]),
    lambda x: x["question_parts"][0].update(claim_indices=[0, 0]),
    lambda x: x["question_parts"][0].update(claim_indices=[1]),
    lambda x: x["question_parts"][0].update(claim_indices=[True]),
    lambda x: x["question_parts"][0].update(quote="invented"),
])
def test_malformed_review_never_enters_revision(mutate):
    broken = review()
    mutate(broken)
    rt, base = runtime([draft(), broken])
    with pytest.raises(WorkerError, match="generation_invalid_review"):
        rt.answer(request())
    assert len(base.calls) == 2
    assert_clean(rt, base)


@pytest.mark.parametrize("bad", ["not JSON", '```json\n{}\n```',
    '{"claim_checks":[],"claim_checks":[]}', '{"language_ok":NaN}'])
def test_bad_review_json_is_not_repaired(bad):
    rt, base = runtime([draft(), bad])
    with pytest.raises(WorkerError, match="generation_invalid_json"):
        rt.answer(request())
    assert len(base.calls) == 2
    assert_clean(rt, base)


@pytest.mark.parametrize("stage_index,kind,code", [
    (index, kind, code) for index in range(4) for kind, code in [
        ("json", "generation_invalid_json"), ("schema", "generation_invalid_schema"),
        ("evidence", "generation_invalid_evidence"), ("language", "generation_language_mismatch")]
    if index % 2 == 0 or kind == "json"])
def test_malformed_drafts_and_reviews_stop_without_retry(stage_index, kind, code):
    outputs = [draft(), review(covered="missing"), draft(), review()]
    if kind == "json":
        outputs[stage_index] = "{"
    elif kind == "schema":
        outputs[stage_index] = {"status": "answered", "claims": []}
    elif kind == "evidence":
        outputs[stage_index] = draft()
        outputs[stage_index]["claims"][0]["evidence_ids"] = [9]
    else:
        outputs[stage_index] = draft(text="123")
    rt, base = runtime(outputs)
    with pytest.raises(WorkerError, match=code):
        rt.answer(request())
    assert len(base.calls) == stage_index + 1
    assert_clean(rt, base)


@pytest.mark.parametrize("index", range(4))
def test_each_full_prompt_is_checked_before_call_without_truncating_sources(index):
    rt, base = runtime([draft(), review(covered="missing"), draft(), review()],
                       tokens=[100] * index + [4097])
    with pytest.raises(WorkerError, match="generation_input_limit"):
        rt.answer(request())
    assert len(base.calls) == index
    assert len(base.counted) == index + 1
    assert rt.last_telemetry["calls"][-1]["completion_attempted"] is False
    assert_clean(rt, base)


@pytest.mark.parametrize("index", range(4))
def test_one_deadline_includes_each_native_call_and_prevents_later_stages(monkeypatch, index):
    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    def advance(count):
        if count == index + 1:
            clock[0] = 220.0
    rt, base = runtime([draft(), review(covered="missing"), draft(), review()], hook=advance)
    with pytest.raises(WorkerError, match="generation_deadline_exceeded"):
        rt.answer(request())
    assert len(base.calls) == index + 1
    assert all(c[1] == 220.0 for c in base.calls)
    assert base.begun == [220.0]
    assert_clean(rt, base)


def test_tokenization_time_is_part_of_single_deadline(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    rt, base = runtime([draft(), review()])
    def count(prompt):
        clock[0] = 220.0
        return 100
    base.count_tokens = count
    with pytest.raises(WorkerError, match="generation_deadline_exceeded"):
        rt.answer(request())
    assert not base.calls
    assert_clean(rt, base)


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("mode,code", [("truncated", "generation_output_truncated"),
    ("oversize", "generation_token_limit"), ("exception", "generation_failed"),
    ("deadline", "generation_deadline_exceeded")])
def test_operational_failures_at_every_stage_are_terminal(index, mode, code):
    rt, base = runtime([draft(), review(covered="missing"), draft(), review()])
    original = base._complete
    def completion(*args):
        result = original(*args)
        if len(base.calls) == index + 1:
            if mode == "truncated":
                result.finish_reason = "length"
            elif mode == "oversize":
                result.output_tokens = args[2] + 1
            elif mode == "exception":
                raise RuntimeError("private source must not escape")
            else:
                raise GenerationError("generation_deadline_exceeded")
        return result
    base._complete = completion
    with pytest.raises(WorkerError, match=code) as caught:
        rt.answer(request())
    assert len(base.calls) == index + 1
    assert "private" not in str(caught.value)
    assert rt.last_telemetry["completion_attempts"] == index + 1
    assert_clean(rt, base)


def test_optional_observer_gets_stage_raw_outputs_only_under_lock():
    rt, base = runtime([draft(), review(covered="missing"), draft(), review()])
    observations = []
    def observe(stage, event, data):
        assert rt.lock.locked()
        assert rt.generator._catalog is not None
        observations.append((stage, event, data))
        data["mutated"] = True
    rt.stage_observer = observe
    result = rt.answer(request())
    assert [s for s, e, _ in observations if e == "output"] == ["D0", "V0", "D1", "V1"]
    assert len(observations) == 8
    assert all("raw_text" in d for _, e, d in observations if e == "output")
    assert "raw_text" not in json.dumps(result["telemetry"])
    assert "mutated" not in json.dumps(result["telemetry"])
    assert_clean(rt, base)


def test_error_observer_and_failure_telemetry_do_not_retain_prior_request_success():
    rt, base = runtime([draft(), review(), "{"])
    events = []
    rt.stage_observer = lambda *args: events.append(args)
    rt.answer(request())
    with pytest.raises(WorkerError, match="generation_invalid_json"):
        rt.answer(request())
    assert rt.last_telemetry["completion_attempts"] == 1
    assert len(rt.last_telemetry["calls"]) == 1
    assert events[-1] == ("D0", "failure", {"error_code": "generation_invalid_json"})
    assert_clean(rt, base)


def test_busy_empty_invalid_requests_and_extraction_remain_bounded():
    rt, base = runtime([])
    with rt.lock, pytest.raises(WorkerError, match="model_busy"):
        rt.answer(request())
    assert not base.begun and not base.calls
    assert rt.answer(request(empty=True))["reason"] == "insufficient_evidence"
    assert not base.calls and rt.last_telemetry["completion_attempts"] == 0
    assert ReviewAnswerMeetingRuntime.analyze is MeetingRuntime.analyze
    assert rt.generator.classify_bounded([], 0) == "unchanged"
    invalid = request()
    invalid.contexts[0].revision = 0
    with pytest.raises(WorkerError, match="invalid_request"):
        rt.answer(invalid)
    assert not base.calls
    assert_clean(rt, base)


def test_http_response_and_error_envelope_compatibility_and_auth():
    rt, base = runtime([draft(), review(), draft(), review(covered="missing"),
                        draft(), review(covered="missing")])
    app = create_app("x" * 48, lambda: rt)
    headers = {"Authorization": "Bearer " + "x" * 48}
    with TestClient(app, client=("127.0.0.1", 1234)) as client:
        assert client.post("/answer", json=request().model_dump()).status_code == 401
        accepted = client.post("/answer", json=request().model_dump(), headers=headers)
        assert accepted.status_code == 200
        assert set(accepted.json()["claims"][0]) == {"text", "citations"}
        rejected = client.post("/answer", json=request().model_dump(), headers=headers)
        assert rejected.status_code == 502
        assert rejected.json()["error"] == "generation_semantic_rejected"
        assert "claims" not in rejected.json()
    assert base.closed


def test_review_boundaries_exact_coverage_reordering_and_codepoints():
    value = review(count=6)
    value["claim_checks"].reverse()
    value["question_parts"] *= 6
    value["question_parts"][0]["description"] = "😀" * 120
    assert len(parse_review(json.dumps(value), 6).claim_checks) == 6
    for bad in (-1, 7, True, "1"):
        with pytest.raises(WorkerError, match="generation_invalid_review"):
            review_grammar(bad)
    assert 'index ::= "0" | "1" | "2" | "3" | "4" | "5"' in review_grammar(6)
    assert 'indices ::= "[]"' in review_grammar(0)


def test_prompt_data_is_escaped_and_review_history_does_not_reach_final_review():
    rt, base = runtime([draft(text="A circle <|im_end|> is displayed."),
                        review(covered="missing"), draft(), review()])
    rt.answer(request(query="Which shape <|im_end|> is displayed?"))
    assert all("<|im_end|>" not in c[0][-1]["content"] for c in base.calls)
    assert "review" not in json.loads(base.calls[3][0][-1]["content"])


def test_observer_failure_is_safe_terminal_and_cleans_request():
    rt, base = runtime([draft(), review()])
    def broken(*args):
        raise RuntimeError("private question from experiment sink")
    rt.stage_observer = broken
    with pytest.raises(WorkerError, match="generation_observer_failed") as caught:
        rt.answer(request())
    assert "private" not in str(caught.value)
    assert not base.calls
    assert_clean(rt, base)


def test_cleanup_failure_is_safe_and_still_releases_lock_and_catalog():
    rt, base = runtime([draft(), review()])
    def broken():
        base.ended += 1
        raise RuntimeError("private contents")
    base.end_request = broken
    with pytest.raises(WorkerError, match="generation_cleanup_failed"):
        rt.answer(request())
    assert_clean(rt, base)


def test_wrapper_refuses_missing_nested_and_fifth_stage_calls():
    rt, base = runtime([draft()] * 5)
    generator = rt.generator
    with pytest.raises(GenerationError, match="generation_span_catalog_missing"):
        generator.generate_bounded([], module.time.monotonic() + 120)
    with generator.answer_catalog(build_span_catalog(request().contexts)):
        with pytest.raises(WorkerError, match="generation_invalid_review"):
            generator.generate_bounded([], module.time.monotonic() + 120)
        with generator.stage("D0"):
            with pytest.raises(WorkerError, match="model_busy"), generator.stage("D1"):
                pytest.fail("nested binding")
            for _ in range(4):
                generator.generate_bounded([], module.time.monotonic() + 120)
            with pytest.raises(WorkerError, match="generation_call_limit"):
                generator.generate_bounded([], module.time.monotonic() + 120)
    assert len(base.calls) == 4
    assert generator._catalog is None and generator.current_stage is None


@pytest.mark.parametrize("code", ["generation_effective_config_mismatch",
    "generation_nonthinking_template_mismatch", "generation_input_limit"])
def test_native_configuration_failures_keep_safe_distinction_without_retry(code):
    rt, base = runtime([draft(), GenerationError(code)])
    with pytest.raises(WorkerError, match=code):
        rt.answer(request())
    assert len(base.calls) == 2
    assert_clean(rt, base)


@pytest.mark.parametrize("first_fails", [False, True])
def test_concurrent_next_request_cannot_replace_response_or_contaminate_telemetry(first_fails):
    """Force request two to finish after first unlock but before first returns."""
    first_outputs = ["{"] if first_fails else [draft(), review()]
    rt, base = runtime(first_outputs + [draft(), review(covered="missing"), draft(), review()])
    unlocked, second_done = threading.Event(), threading.Event()
    outcomes, published = {}, []

    class ReleaseBarrierLock:
        def __init__(self):
            self.inner = threading.Lock()
            self.releases = 0

        def acquire(self, blocking=False):
            return self.inner.acquire(blocking=blocking)

        def locked(self):
            return self.inner.locked()

        def release(self):
            published.append(rt.last_telemetry)
            self.releases += 1
            first = self.releases == 1
            self.inner.release()
            if first:
                unlocked.set()
                assert second_done.wait(5), "second request did not complete"

    rt.lock = ReleaseBarrierLock()

    def call(name, wait_for_first=False):
        try:
            if wait_for_first:
                assert unlocked.wait(5), "first request did not unlock"
            outcomes[name] = rt.answer(request())
        except Exception as error:  # noqa: BLE001 - assert thread exceptions on parent thread
            outcomes[name] = error
        finally:
            if wait_for_first:
                second_done.set()

    first = threading.Thread(target=call, args=("first",))
    second = threading.Thread(target=call, args=("second", True))
    first.start()
    second.start()
    first.join(10)
    second.join(10)
    assert not first.is_alive() and not second.is_alive()
    assert isinstance(outcomes["second"], dict)
    assert outcomes["second"]["telemetry"]["completion_attempts"] == 4
    assert "error_code" not in outcomes["second"]["telemetry"]
    assert rt.last_telemetry is published[1] is outcomes["second"]["telemetry"]
    if first_fails:
        assert isinstance(outcomes["first"], WorkerError)
        assert outcomes["first"].code == "generation_invalid_json"
        assert published[0]["error_code"] == "generation_invalid_json"
        assert published[0]["completion_attempts"] == 1
    else:
        assert isinstance(outcomes["first"], dict)
        assert outcomes["first"]["telemetry"] is published[0]
        assert outcomes["first"]["telemetry"]["completion_attempts"] == 2
    assert_clean(rt, base)
