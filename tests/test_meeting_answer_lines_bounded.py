"""New synthetic control-budget tests, not a replay of completed C0 questions."""
import json
from dataclasses import replace

import pytest

import doctrail.meeting_answer_lines_bounded as module
from doctrail.inference import WorkerError
from doctrail.meeting_answer_spans import (
    answer_messages_spans,
    build_span_catalog,
    span_answer_grammar,
)
from doctrail.meeting_gguf import GGUFResult
from scripts.probe_meeting_blocks_resources import dto


class Base:
    def __init__(self):
        self.calls, self.clock, self.preparation_cost, self.cleanup_cost = [], 0, 0, 0
        self.output = GGUFResult(json.dumps({"status": "answered", "claims": [{
            "evidence_ids": [0, 1], "text": "The sample square is green when its switch is on."}]}),
            "eos", 100, 40, .01, {})

    def public_metadata(self):
        return {"repo_id": "synthetic-model", "revision": "synthetic-revision"}

    def begin_request(self, deadline):
        self.deadline = deadline

    def end_request(self):
        self.clock += self.cleanup_cost
        self.deadline = None

    def count_tokens(self, messages):
        self.clock += self.preparation_cost
        return 100

    def _complete(self, messages, deadline, token_limit, grammar):
        self.calls.append((messages, deadline, token_limit, grammar))
        assert deadline == self.deadline
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


@pytest.fixture
def source(monkeypatch):
    base = Base()
    monkeypatch.setattr(module.time, "monotonic", lambda: base.clock)
    runtime = module.BoundedLineRuntime(module.BoundedLineGenerator(base))
    request = dto(["The sample square is green\nwhen its switch is on.\n"], "When is the square green?")
    return base, runtime, request


def test_exact_frozen_line_control_prompt_grammar_and_384_90_budget(source):
    base, runtime, request = source
    result = runtime.answer(request)
    catalog = build_span_catalog(request.contexts)
    assert base.calls == [(answer_messages_spans(request.query, catalog), 90, 384,
                           span_answer_grammar(catalog))]
    assert len(result["claims"][0]["citations"]) == 2
    assert result["claims"][0]["citations"][0]["quote"] == "The sample square is green\n"
    assert result["telemetry"]["completion_attempts"] == 1
    assert not result["telemetry"]["semantic_support_verified"]
    assert not runtime.lock.locked() and base.deadline is None


@pytest.mark.parametrize("field", ["preparation_cost", "cleanup_cost"])
def test_both_preparation_and_cleanup_count_toward_90_seconds(source, field):
    base, runtime, request = source
    setattr(base, field, 91)
    with pytest.raises(WorkerError, match="generation_deadline_exceeded"):
        runtime.answer(request)
    assert len(base.calls) == (0 if field == "preparation_cost" else 1)
    assert not runtime.lock.locked() and runtime.generator._catalog is None


@pytest.mark.parametrize("changes", [{"output_tokens": 385}, {"output_tokens": True},
                                    {"input_tokens": 4097}, {"finish_reason": "length"}])
def test_limits_and_truncation_are_failures(source, changes):
    base, runtime, request = source
    base.output = replace(base.output, **changes)
    with pytest.raises(WorkerError):
        runtime.answer(request)
    assert len(base.calls) == 1 and not runtime.lock.locked()


def test_source_exception_is_sanitized_and_later_request_recovers(source):
    base, runtime, request = source
    output, base.output = base.output, RuntimeError("private sample content")
    with pytest.raises(WorkerError, match="generation_failed") as failure:
        runtime.answer(request)
    assert "private" not in str(failure.value)
    base.output = output
    assert runtime.answer(request)["status"] == "answered"
    assert len(base.calls) == 2


def test_busy_and_empty_paths_make_no_native_call(source):
    base, runtime, request = source
    runtime.lock.acquire()
    try:
        with pytest.raises(WorkerError, match="model_busy"):
            runtime.answer(request)
    finally:
        runtime.lock.release()
    request.contexts = []
    assert runtime.answer(request)["status"] == "abstained"
    assert base.calls == []


def test_budget_metadata_distinguishes_control_from_original_c0(source):
    _, runtime, _ = source
    metadata = runtime.generator.public_metadata()
    assert metadata["runtime"]["max_new_tokens"] == 384
    assert metadata["runtime"]["deadline_seconds"] == 90
    assert runtime.health()["answer_policy"] == module.ANSWER_POLICY
