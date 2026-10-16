"""Fresh synthetic runtime/HTTP doubles only; no local inference or tokenizers."""
import copy
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from doctrail import meeting_requirements_runtime as c3
from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_answer_blocks import build_block_catalog
from doctrail.meeting_answer_requirements import parse_requirement_plan
from doctrail.meeting_contract import AnswerRequest
from doctrail.meeting_gguf import GGUFResult
from doctrail.meeting_qwen35 import GGUF_SHA256, NONTHINKING_PREAMBLE, PREAMBLE_SHA256


def request():
    text = "Synthetic silver hexagon.\r\nThe code is Q.\n\nA separate unused sentence."
    return AnswerRequest.model_validate({"schema_version": 1, "query": "Describe the hexagon.",
        "contexts": [{"document_id": "fresh", "revision": 2, "chunk_id": "fresh-2-0",
            "title": "Synthetic", "meeting_date": None, "page": None, "text": text,
            "start_offset": 13, "end_offset": 13 + len(text)}]})


def plan(status="supported"):
    return json.dumps({"requirements": [
        {"requirement_id": 1, "need": "Describe the hexagon", "status": "supported",
         "evidence_ids": [0]},
        {"requirement_id": 2, "need": "Give the code", "status": status,
         "evidence_ids": [0] if status == "supported" else []}]})


ANSWER = json.dumps({"status": "answered", "claims": [
    {"requirement_id": 1, "text": "The synthetic hexagon is silver."},
    {"requirement_id": 2, "text": "The code is Q."}]})


class Backend:
    def __init__(self, outputs=None):
        self.outputs = [plan(), ANSWER] if outputs is None else outputs
        self.counts = [100, 200]
        self.counted, self.calls = [], []
        self.begun, self.ended = [], 0
        self.on_count = self.on_complete = self.on_cleanup = None
        self.output_fields = {}

    def public_metadata(self):
        return {"repo_id": "synthetic", "revision": "a" * 40, "runtime": {}}

    def begin_request(self, deadline):
        self.begun.append(deadline)

    def end_request(self):
        self.ended += 1
        if self.on_cleanup:
            self.on_cleanup()

    def count_tokens(self, messages):
        self.counted.append(copy.deepcopy(messages))
        if self.on_count:
            self.on_count(len(self.counted))
        return self.counts[len(self.counted) - 1]

    def _complete(self, messages, deadline, limit, grammar):
        self.calls.append((copy.deepcopy(messages), deadline, limit, grammar))
        if self.on_complete:
            self.on_complete(len(self.calls))
        output = self.outputs[len(self.calls) - 1]
        if isinstance(output, Exception):
            raise output
        fields = {"text": output, "finish_reason": "eos",
            "input_tokens": self.counts[len(self.calls) - 1], "output_tokens": 30,
            "elapsed_seconds": 0.0, "telemetry": {"native_timings": {"cache_n": 0,
                "prompt_n": self.counts[len(self.calls) - 1], "PRIVATE": "SECRET"}}}
        fields.update(self.output_fields)
        return GGUFResult(**fields)


def service(base=None):
    return c3.RequirementsRuntime(c3.RequirementsGenerator(base or Backend()))


def test_two_stages_share_one_deadline_and_keep_exact_sources_without_raw_telemetry():
    base = Backend()
    runtime = service(base)
    req = request()
    result = runtime.answer(req)
    assert result["status"] == "answered"
    assert len(base.calls) == 2 and len(base.begun) == base.ended == 1
    assert base.calls[0][1] == base.calls[1][1] == base.begun[0]
    assert [x[2] for x in base.calls] == [384, 384]
    selected = json.loads(base.calls[1][0][1]["content"])["evidence"]
    assert len(selected) == 1 and "unused" not in selected[0]["text"]
    for claim in result["claims"]:
        assert claim["citations"] == [{"chunk_id": "fresh-2-0", "quote": selected[0]["text"],
            "start_offset": 13, "end_offset": 13 + len(selected[0]["text"])}]
    telemetry = result["telemetry"]
    assert telemetry["completed_stages"] == telemetry["completion_attempts"] == 2
    assert not telemetry["semantic_support_verified"] and not telemetry["question_completeness_verified"]
    assert [x["stage"] for x in telemetry["calls"]] == [1, 2]
    assert all(x["finish_reason"] == "eos" for x in telemetry["calls"])
    for private in (req.query, req.contexts[0].text, "Give the code", "SECRET", "PRIVATE"):
        assert private not in json.dumps(telemetry)
    assert not runtime.lock.locked() and runtime.generator._request_deadline is None
    assert runtime.health()["answer_limits"]["output_tokens_total"] == 768
    assert runtime.health()["experimental"]


@pytest.mark.parametrize("status", ["missing", "uncertain"])
def test_unsupported_requirement_skips_second_call(status):
    base = Backend([plan(status)])
    result = service(base).answer(request())
    assert result["status"] == "abstained" and result["claims"] == []
    assert len(base.calls) == len(base.counted) == 1
    assert result["telemetry"]["requirements"][1]["status"] == status


def test_stage_two_can_only_wholly_abstain():
    base = Backend([plan(), '{"status":"abstained","claims":[]}'])
    assert service(base).answer(request())["claims"] == []
    assert len(base.calls) == 2


def test_empty_context_has_zero_native_attempts():
    base = Backend()
    req = request()
    req.contexts.clear()
    result = service(base).answer(req)
    assert result["status"] == "abstained"
    assert result["telemetry"]["completion_attempts"] == 0 and not base.calls


@pytest.mark.parametrize("stage", [1, 2])
@pytest.mark.parametrize("count", [5121, 0, False, "100", 1.0])
def test_each_actual_stage_input_limit_closes_without_trimming(stage, count):
    base = Backend()
    base.counts[stage - 1] = count
    runtime = service(base)
    req = request()
    before = req.model_dump()
    with pytest.raises(WorkerError, match="generation_input_limit"):
        runtime.answer(req)
    assert len(base.calls) == stage - 1 and req.model_dump() == before
    assert len(base.counted) == stage and base.ended == 1 and not runtime.lock.locked()
    assert runtime.last_telemetry["completion_attempts"] == stage - 1


@pytest.mark.parametrize("fields,code", [
    ({"finish_reason": "length"}, "generation_output_truncated"),
    ({"output_tokens": 385}, "generation_token_limit"),
    ({"output_tokens": True}, "generation_token_limit"),
    ({"output_tokens": 0}, "generation_token_limit"),
    ({"input_tokens": 99}, "generation_token_limit"),
    ({"input_tokens": 5121}, "generation_token_limit"),
    ({"input_tokens": False}, "generation_token_limit"),
])
def test_output_guards_stop_before_stage_two(fields, code):
    base = Backend()
    base.output_fields = fields
    with pytest.raises(WorkerError, match=code):
        service(base).answer(request())
    assert len(base.calls) == 1 and base.ended == 1


@pytest.mark.parametrize("outputs,code,calls", [
    (["bad"], "generation_invalid_json", 1),
    ([plan().replace('"requirement_id": 2', '"requirement_id": 1')],
     "generation_invalid_schema", 1),
    ([plan().replace('"evidence_ids": [0]', '"evidence_ids": [9]')],
     "generation_invalid_evidence", 1),
    ([plan(), ANSWER.replace('"requirement_id": 2', '"requirement_id": 1')],
     "generation_invalid_schema", 2),
    ([plan(), ANSWER.replace("The code is Q.", "한국어만 반환했습니다.")],
     "generation_language_mismatch", 2),
    ([GenerationError("generation_effective_config_mismatch")],
     "generation_effective_config_mismatch", 1),
    ([plan(), RuntimeError("SECRET native detail")], "generation_failed", 2),
])
def test_failures_are_atomic_sanitized_and_not_retried(outputs, code, calls):
    base = Backend(outputs)
    runtime = service(base)
    with pytest.raises(WorkerError, match=code) as error:
        runtime.answer(request())
    assert len(base.calls) == calls and base.ended == 1
    assert runtime.last_telemetry["error_code"] == code
    assert "SECRET" not in str(error.value) + json.dumps(runtime.last_telemetry)
    assert not runtime.lock.locked() and runtime.generator._stage == 0


@pytest.mark.parametrize("phase,advance,expected_calls", [
    ("count1", 90, 0), ("complete1", 90, 1), ("count2", 90, 1),
    ("complete2", 90, 2), ("cleanup", 90, 2),
])
def test_single_deadline_includes_preparation_both_calls_and_cleanup(monkeypatch, phase,
                                                                   advance, expected_calls):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(c3.time, "monotonic", lambda: clock.now)
    base = Backend()
    def tick(at):
        if at == phase:
            clock.now += advance
    base.on_count = lambda n: tick(f"count{n}")
    base.on_complete = lambda n: tick(f"complete{n}")
    base.on_cleanup = lambda: tick("cleanup")
    runtime = service(base)
    with pytest.raises(WorkerError, match="generation_deadline_exceeded"):
        runtime.answer(request())
    assert len(base.calls) == expected_calls and base.ended == 1
    assert not runtime.lock.locked()


def test_elapsed_first_stage_reduces_second_stage_budget(monkeypatch):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(c3.time, "monotonic", lambda: clock.now)
    base = Backend()
    base.on_complete = lambda n: setattr(clock, "now", clock.now + (60 if n == 1 else 29))
    result = service(base).answer(request())
    assert result["status"] == "answered"
    assert [x[1] for x in base.calls] == [190, 190]
    assert result["telemetry"]["elapsed_ms"] == 89000


def test_cumulative_native_work_cannot_reset_deadline(monkeypatch):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(c3.time, "monotonic", lambda: clock.now)
    base = Backend()
    base.on_complete = lambda n: setattr(clock, "now", clock.now + (60 if n == 1 else 31))
    runtime = service(base)
    with pytest.raises(WorkerError, match="generation_deadline_exceeded"):
        runtime.answer(request())
    assert len(base.calls) == 2 and base.ended == 1
    assert runtime.last_telemetry["validated_stages"] == 1


def test_stage_two_cancellation_cleans_and_propagates_without_partial_answer():
    base = Backend()
    def cancel(n):
        if n == 2:
            raise KeyboardInterrupt()
    base.on_complete = cancel
    runtime = service(base)
    with pytest.raises(KeyboardInterrupt):
        runtime.answer(request())
    assert len(base.calls) == 2 and base.ended == 1
    assert runtime.last_telemetry["validated_stages"] == 1
    assert not runtime.lock.locked() and runtime.generator._request_deadline is None


def test_cleanup_exception_is_sanitized():
    base = Backend()
    def fail():
        raise RuntimeError("PRIVATE cleanup detail")
    base.on_cleanup = fail
    runtime = service(base)
    with pytest.raises(WorkerError, match="generation_cleanup_failed") as error:
        runtime.answer(request())
    assert "PRIVATE" not in str(error.value) + json.dumps(runtime.last_telemetry)
    assert not runtime.lock.locked() and runtime.generator._request_deadline is None


@pytest.mark.parametrize("language", ["ja", "", False, [], {}])
def test_invalid_explicit_language_is_rejected_without_dispatch(language):
    base = Backend()
    with pytest.raises(WorkerError, match="generation_invalid_schema"):
        service(base).answer(request(), language=language)
    assert not base.calls and not base.begun


def test_cleanup_budget_and_error_release_lock(monkeypatch):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(c3.time, "monotonic", lambda: clock.now)
    base = Backend()
    base.on_cleanup = lambda: setattr(clock, "now", clock.now + 6)
    runtime = service(base)
    with pytest.raises(WorkerError, match="generation_cleanup_failed"):
        runtime.answer(request())
    assert not runtime.lock.locked() and runtime.generator._request_deadline is None


def test_request_snapshot_survives_caller_mutation_during_generation():
    req = request()
    base = Backend()
    original = req.contexts[0].text
    def mutate(n):
        if n == 1:
            req.contexts[0].text = "ALTERED"
            req.contexts[0].revision = 9
            req.query = "ALTERED"
    base.on_complete = mutate
    result = service(base).answer(req)
    assert result["claims"][0]["citations"][0]["quote"] in original
    second = json.loads(base.calls[1][0][1]["content"])
    assert second["question"] != "ALTERED" and second["evidence"][0]["revision"] == 2


def test_explicit_language_is_independent_of_question_and_sources():
    ko_plan = plan().replace("Describe the hexagon", "육각형 설명").replace("Give the code", "코드 제시")
    ko_answer = ANSWER.replace("The synthetic hexagon is silver.", "합성 육각형은 은색입니다.").replace(
        "The code is Q.", "코드는 큐입니다.")
    base = Backend([ko_plan, ko_answer])
    result = service(base).answer(request(), language="ko")
    assert result["telemetry"]["language_source"] == "explicit"
    assert all(json.loads(c[0][1]["content"])["response_language"] == "ko" for c in base.calls)


def test_busy_invalid_request_and_wrapper_stage_order():
    base = Backend()
    runtime = service(base)
    runtime.lock.acquire()
    try:
        with pytest.raises(WorkerError, match="model_busy"):
            runtime.answer(request())
    finally:
        runtime.lock.release()
    assert not base.begun
    req = request()
    req.query = ""
    with pytest.raises(WorkerError, match="invalid_request"):
        runtime.answer(req)
    assert not base.begun
    generator = runtime.generator
    req = request()
    catalog = build_block_catalog(req.contexts)
    parsed = parse_requirement_plan(plan(), catalog, "en")
    deadline = time.monotonic() + 90
    generator.begin_request(deadline)
    try:
        with pytest.raises(WorkerError, match="generation_call_limit"):
            generator.generate_stage([], deadline, 2, catalog, "en", parsed)
        with pytest.raises(WorkerError, match="generation_call_limit"):
            generator.generate_stage([], deadline + 1, 1, catalog, "en")
        with pytest.raises(WorkerError, match="generation_stage_required"):
            generator.generate_bounded([], deadline)
    finally:
        generator.end_request()
    assert not base.calls


def mock_native(corrupt=None):
    """Exercise inherited native guards through HTTP doubles, not a model/tokenizer."""
    dispatched = []
    def handler(req):
        payload = json.loads(req.content)
        if req.url.path == "/apply-template":
            return httpx.Response(200, json={"prompt": "synthetic" + NONTHINKING_PREAMBLE})
        if req.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": list(range(100))})
        assert req.url.path == "/completion"
        dispatched.append(payload)
        settings = {k: v for k, v in payload.items()
                    if k not in {"prompt", "cache_prompt", "return_tokens"}}
        response = {"model": GGUF_SHA256, "generation_settings": settings, "truncated": False,
            "stop": True, "stop_type": "eos", "tokens_evaluated": 100, "tokens_predicted": 30,
            "timings": {"cache_n": 0, "prompt_n": 100},
            "content": plan() if len(dispatched) == 1 else ANSWER}
        if corrupt:
            corrupt(response)
        return httpx.Response(200, json=response)
    base = c3.RequirementsGGUFGenerator("http://127.0.0.1:12345", "x" * 32,
                                      "unused-synthetic-manifest.json",
                                      transport=httpx.MockTransport(handler))
    # Identity loading involves local GGUF bytes and is independently inherited;
    # this fixture injects metadata solely to test native request/response guards.
    base._alias = GGUF_SHA256
    base._metadata = {"repo_id": "synthetic", "revision": "gguf-sha256:" + GGUF_SHA256,
                      "runtime": {"context_tokens": 6144}}
    return base, dispatched


def test_native_transport_preserves_greedy_cache_nonthinking_and_both_dispatches():
    base, dispatched = mock_native()
    try:
        result = service(base).answer(request())
        assert result["status"] == "answered" and len(dispatched) == 2
        assert all(x["cache_prompt"] is False and x["temperature"] == 0 and x["seed"] == 0
                   and x["n_predict"] == 384 for x in dispatched)
        assert base.last_effective_config["observed_nonthinking_preamble_sha256"] == PREAMBLE_SHA256
        assert not base._cache and base._deadline is None
        assert base.public_metadata()["generation_protocol"] == c3.ANSWER_POLICY
    finally:
        base.close()


def test_reused_runtime_identity_resets_previous_grammar_and_template_observations():
    base, dispatched = mock_native()
    runtime = service(base)
    try:
        first = runtime.answer(request())
        assert len(dispatched) == 2
        assert runtime.generator._last_grammar_sha256 is not None
        assert base.public_metadata()["nonthinking"]["last_template_verified"] is True
        empty = request()
        empty.contexts.clear()
        second = runtime.answer(empty)
        assert second["status"] == "abstained" and len(dispatched) == 2
        telemetry = second["telemetry"]
        assert telemetry["completion_attempts"] == telemetry["completed_stages"] == 0
        identity = telemetry["resource_identity"]
        assert identity["answer_decoder"]["grammar_sha256"] is None
        assert identity["nonthinking"]["last_template_verified"] is False
        for field in ("repo_id", "revision", "runtime"):
            assert identity[field] == first["telemetry"]["resource_identity"][field]
        assert runtime.last_telemetry is telemetry
    finally:
        base.close()


@pytest.mark.parametrize("corrupt,code", [
    (lambda r: r["generation_settings"].update(temperature=0.7), "generation_effective_config_mismatch"),
    (lambda r: r["timings"].update(cache_n=1), "generation_failed"),
    (lambda r: r.update(model="different"), "generation_failed"),
    (lambda r: r.update(tokens_evaluated=99), "generation_failed"),
    (lambda r: r.update(truncated=True), "generation_failed"),
    (lambda r: r.update(stop_type="limit"), "generation_output_truncated"),
])
def test_native_errors_close_without_second_dispatch(corrupt, code):
    base, dispatched = mock_native(corrupt)
    try:
        with pytest.raises(WorkerError, match=code):
            service(base).answer(request())
        assert len(dispatched) == 1 and not base._cache and base._deadline is None
    finally:
        base.close()
