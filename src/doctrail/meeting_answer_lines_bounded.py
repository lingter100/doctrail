"""Budget-matched physical-line control for a NEW C2 comparison, never C0 replay.

The frozen C0 prompt/catalog/grammar/mapper are reused without edits. Only request
budget and reporting differ: one completion, 384 output tokens and 90 seconds.
This is an offline comparison control; no service default is changed.
"""
from __future__ import annotations

import hashlib
import time

from pydantic import ValidationError

from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_answer_blocks import citation_metrics
from doctrail.meeting_answer_spans import (
    SpanAnswerGenerator,
    answer_messages_spans,
    build_span_catalog,
    grounded_answer_spans,
    response_language,
    span_answer_grammar,
)
from doctrail.meeting_contract import AnswerRequest
from doctrail.meeting_worker import MeetingRuntime

ANSWER_POLICY = "meeting-lines-budget-matched-c2-control-v1"
MAX_NEW_TOKENS = 384
DEADLINE_SECONDS = 90


class BoundedLineGenerator(SpanAnswerGenerator):
    def __init__(self, base):
        super().__init__(base)
        self._called = False

    def begin_request(self, deadline):
        self._called = False
        super().begin_request(deadline)

    def public_metadata(self):
        metadata = super().public_metadata()
        return {**metadata, "runtime": {**metadata.get("runtime", {}),
            "max_new_tokens": MAX_NEW_TOKENS, "deadline_seconds": DEADLINE_SECONDS},
            "comparison_control": {"policy": ANSWER_POLICY, "completion_calls": 1,
                                   "frozen_c0_prompt_and_catalog": True}}

    def generate_bounded(self, messages, deadline):
        if self._catalog is None:
            raise GenerationError("generation_span_catalog_missing")
        if self._called:
            raise WorkerError("generation_call_limit", 502)
        if time.monotonic() >= deadline:
            raise WorkerError("generation_deadline_exceeded", 504)
        grammar = span_answer_grammar(self._catalog)
        self._last_grammar_sha256 = hashlib.sha256(grammar.encode()).hexdigest()
        self._called = True
        output = self.base._complete(messages, deadline, MAX_NEW_TOKENS, grammar)
        if (type(output.output_tokens) is not int or not 0 < output.output_tokens <= MAX_NEW_TOKENS
                or type(output.input_tokens) is not int or not 0 < output.input_tokens <= 4096):
            raise WorkerError("generation_token_limit", 502)
        return output


class BoundedLineRuntime(MeetingRuntime):
    def __init__(self, generator):
        if not isinstance(generator, BoundedLineGenerator):
            raise TypeError("bounded_line_generator_required")
        super().__init__(generator)

    def health(self):
        return {**super().health(), "answer_policy": ANSWER_POLICY,
                "answer_limits": {"output_tokens": MAX_NEW_TOKENS,
                                  "deadline_seconds": DEADLINE_SECONDS, "completion_calls": 1}}

    def answer(self, request):
        if not self.lock.acquire(blocking=False):
            raise WorkerError("model_busy", 503)
        started = time.monotonic()
        deadline = started + DEADLINE_SECONDS
        telemetry = {"answer_policy": ANSWER_POLICY, "calls": [], "completion_attempts": 0,
                     "semantic_support_verified": False, "question_completeness_verified": False}
        failure, result, begun = None, None, False
        self.last_telemetry = {}
        try:
            try:
                request = AnswerRequest.model_validate(request.model_dump())
            except (ValidationError, AttributeError):
                raise WorkerError("invalid_request", 422) from None
            begun = True
            self.generator.begin_request(deadline)
            if not request.contexts:
                result = {"status": "abstained", "reason": "insufficient_evidence", "claims": []}
            else:
                catalog = build_span_catalog(request.contexts)
                prompt = answer_messages_spans(request.query, catalog)
                telemetry.update(citation_metrics({"claims": []}, catalog))
                with self.generator.answer_catalog(catalog):
                    tokens = self.generator.count_tokens(prompt)
                    if type(tokens) is not int or not 0 < tokens <= 4096:
                        raise WorkerError("generation_input_limit", 422)
                    if time.monotonic() >= deadline:
                        raise WorkerError("generation_deadline_exceeded", 504)
                    telemetry["preprocessing_ms"] = (time.monotonic() - started) * 1000
                    telemetry["completion_attempts"] = 1
                    raw = self._generate(prompt, deadline, telemetry["calls"])
                result = grounded_answer_spans(raw, catalog, request.contexts,
                                               response_language(request.query))
                telemetry.update(citation_metrics(result, catalog))
        except WorkerError as error:
            failure = error
        except GenerationError as error:
            safe = {"generation_deadline_exceeded": 504, "generation_input_limit": 422,
                    "generation_effective_config_mismatch": 503,
                    "generation_nonthinking_template_mismatch": 503}
            code = error.code if error.code in safe else "generation_failed"
            failure = WorkerError(code, safe.get(code, 503))
        except Exception:  # noqa: BLE001 - never publish raw source/native exceptions
            failure = WorkerError("generation_failed", 503)
        finally:
            cleanup_started = time.monotonic()
            try:
                if begun:
                    self.generator.end_request()
            except Exception:  # noqa: BLE001 - safe cleanup diagnostics
                failure = failure or WorkerError("generation_cleanup_failed", 503)
            finally:
                try:
                    ended = time.monotonic()
                    if ended >= deadline:
                        failure = WorkerError("generation_deadline_exceeded", 504)
                    telemetry.update(elapsed_ms=(ended - started) * 1000,
                                     cleanup_ms=(ended - cleanup_started) * 1000)
                    if failure:
                        telemetry["error_code"] = failure.code
                    self.last_telemetry = telemetry
                finally:
                    self.lock.release()
        if failure:
            raise failure from None
        return {"schema_version": 1, "model": self.model, "revision": self.revision,
                **result, "telemetry": telemetry}
