"""Explicit 5120-token C2 follow-up; never a change to a frozen experiment.

Frozen catalogs, prompts, grammars and mappers remain imported. Native identity,
HTTP byte limits and cleanup are inherited; the native completion guard and
request runtimes are explicitly versioned below, with no global/class patches.
"""
from __future__ import annotations

import hashlib
import json
import time

from pydantic import ValidationError

from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_answer_blocks import (
    MAX_BLOCK_CODEPOINTS,
    MAX_CHUNKS,
    MAX_SPANS,
    BlockAnswerGenerator,
    answer_messages_blocks,
    build_block_catalog,
    citation_metrics,
    grounded_answer_blocks,
)
from doctrail.meeting_answer_grammar import ANSWER_GRAMMAR
from doctrail.meeting_answer_lines_bounded import BoundedLineGenerator
from doctrail.meeting_answer_spans import (
    answer_messages_spans,
    build_span_catalog,
    grounded_answer_spans,
    response_language,
    span_answer_grammar,
)
from doctrail.meeting_contract import AnswerRequest
from doctrail.meeting_gguf import (
    GREEDY,
    MAX_REQUEST_BYTES,
    GGUFResult,
    _fail,
    _integer,
    _same_setting,
)
from doctrail.meeting_qwen35 import PREAMBLE_SHA256, Qwen35Generator
from doctrail.meeting_worker import MeetingRuntime

PROTOCOL = "meeting-answer-blocks-c2-input-budget-v1"
LINE_POLICY = "meeting-lines-c2-input-budget-v1"
BLOCK_POLICY = "meeting-blocks-c2-input-budget-v1"
MAX_INPUT_TOKENS = 5120
MAX_NEW_TOKENS = 384
CONTEXT_TOKENS = 6144
DEADLINE_SECONDS = 90


def native_payload(tokens, token_limit, grammar):
    """Guard actual serialized IDs; a tokenizer-only count is not native byte proof."""
    if (not isinstance(tokens, list) or not 0 < len(tokens) <= MAX_INPUT_TOKENS
            or any(not _integer(t) for t in tokens)
            or type(token_limit) is not int or not 0 < token_limit <= MAX_NEW_TOKENS
            or not isinstance(grammar, str)):
        _fail("generation_input_limit")
    expected = {**GREEDY, "n_predict": token_limit, "grammar": grammar}
    payload = {**expected, "prompt": tokens, "cache_prompt": False, "return_tokens": True}
    if len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_REQUEST_BYTES:
        _fail("generation_input_limit")
    return expected, payload


class BudgetGGUFGenerator(Qwen35Generator):
    """Same identity and decoding, an explicit 5120/384/6144 contract."""

    def load(self):
        super().load()
        if self._metadata["runtime"]["context_tokens"] != CONTEXT_TOKENS:
            self.close()
            _fail("generation_identity_mismatch")
        return self

    def public_metadata(self):
        metadata = super().public_metadata()
        return {**metadata, "generation_protocol": PROTOCOL,
            "runtime": {**metadata["runtime"], "max_input_tokens": MAX_INPUT_TOKENS,
                "max_new_tokens": MAX_NEW_TOKENS, "deadline_seconds": DEADLINE_SECONDS}}

    def _remaining(self, deadline=None):
        effective = deadline if deadline is not None else self._deadline
        remaining = effective - time.monotonic() if effective is not None else DEADLINE_SECONDS
        if remaining <= 0:
            _fail("generation_deadline_exceeded")
        return remaining

    def _complete(self, messages, deadline, token_limit, grammar=""):
        started = time.monotonic()
        self.last_effective_config = None
        tokens = self._prepare(messages, deadline)
        expected, payload = native_payload(tokens, token_limit, grammar)
        response = self._request("POST", "/completion", payload, deadline)
        settings = response.get("generation_settings")
        if not isinstance(settings, dict) or any(
                key not in settings or not _same_setting(settings[key], value)
                for key, value in expected.items()):
            _fail("generation_effective_config_mismatch")
        timings = response.get("timings")
        if (response.get("model") != self._alias or response.get("truncated") is not False
                or response.get("stop") is not True or not isinstance(timings, dict)
                or type(timings.get("cache_n")) is not int or timings["cache_n"] != 0
                or not _integer(timings.get("prompt_n"), 1)
                or timings["prompt_n"] != len(tokens)
                or not _integer(response.get("tokens_evaluated"), 1)
                or response["tokens_evaluated"] != len(tokens)
                or not _integer(response.get("tokens_predicted"), 1)
                or response["tokens_predicted"] > token_limit
                or not isinstance(response.get("content"), str)
                or response.get("stop_type") not in ("eos", "limit")):
            _fail()
        # No source-containing prompt, raw native response or local model path in telemetry.
        self.last_effective_config = {"backend": "llama.cpp", **expected,
            "cache_prompt_requested": False, "observed_cache_tokens": timings["cache_n"]}
        telemetry = {key: value for key, value in timings.items()
                     if key in {"cache_n", "prompt_n", "prompt_ms", "predicted_n", "predicted_ms"}
                     and type(value) in (int, float)}
        if not self._template_verified:
            _fail("generation_nonthinking_template_mismatch")
        self.last_effective_config["observed_nonthinking_preamble_sha256"] = PREAMBLE_SHA256
        self.last_effective_config["enable_thinking_requested"] = False
        return GGUFResult(response["content"],
            "eos" if response["stop_type"] == "eos" else "length", len(tokens),
            response["tokens_predicted"], time.monotonic() - started,
            {"backend": "llama.cpp", "native_timings": telemetry})

    def generate_bounded(self, messages, deadline):
        return self._complete(messages, deadline, MAX_NEW_TOKENS, ANSWER_GRAMMAR)


class BudgetLineGenerator(BoundedLineGenerator):
    def public_metadata(self):
        metadata = super().public_metadata()
        return {**metadata, "generation_protocol": PROTOCOL,
            "runtime": {**metadata.get("runtime", {}), "max_input_tokens": MAX_INPUT_TOKENS,
                "max_new_tokens": MAX_NEW_TOKENS, "deadline_seconds": DEADLINE_SECONDS},
            "comparison_control": {**metadata["comparison_control"], "policy": LINE_POLICY}}

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
                or type(output.input_tokens) is not int or not 0 < output.input_tokens <= MAX_INPUT_TOKENS):
            raise WorkerError("generation_token_limit", 502)
        return output


class BudgetBlockGenerator(BlockAnswerGenerator):
    def public_metadata(self):
        metadata = super().public_metadata()
        return {**metadata, "generation_protocol": PROTOCOL,
            "runtime": {**metadata.get("runtime", {}), "max_input_tokens": MAX_INPUT_TOKENS,
                "max_new_tokens": MAX_NEW_TOKENS, "deadline_seconds": DEADLINE_SECONDS},
            "answer_decoder": {**metadata["answer_decoder"], "answer_policy": BLOCK_POLICY}}

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
        return self.base._complete(messages, deadline, MAX_NEW_TOKENS, grammar)


class BudgetLineRuntime(MeetingRuntime):
    def __init__(self, generator):
        if not isinstance(generator, BudgetLineGenerator):
            raise TypeError("bounded_line_generator_required")
        super().__init__(generator)

    def health(self):
        return {**super().health(), "protocol": PROTOCOL,
            "limits": {"input_tokens": MAX_INPUT_TOKENS, "output_tokens": MAX_NEW_TOKENS,
                       "deadline_seconds": DEADLINE_SECONDS}, "answer_policy": LINE_POLICY,
                "answer_limits": {"input_tokens": MAX_INPUT_TOKENS, "output_tokens": MAX_NEW_TOKENS,
                                  "deadline_seconds": DEADLINE_SECONDS, "completion_calls": 1}}

    def _generate(self, prompt, deadline, telemetry):
        tokens = self.generator.count_tokens(prompt)
        if type(tokens) is not int or not 0 < tokens <= MAX_INPUT_TOKENS:
            raise WorkerError("generation_input_limit", 422)
        output = self.generator.generate_bounded(prompt, deadline)
        metrics = {"input_tokens": output.input_tokens, "output_tokens": output.output_tokens,
                   "elapsed_seconds": output.elapsed_seconds, "finish_reason": output.finish_reason}
        # Native llama.cpp has no Torch allocator measurements. Never invent zero peaks.
        for field in ("peak_allocated_mib", "peak_reserved_mib"):
            if hasattr(output, field):
                metrics[field] = getattr(output, field)
        metrics.update(getattr(output, "telemetry", {}))
        telemetry.append(metrics)
        if output.finish_reason != "eos":
            raise WorkerError("generation_output_truncated", 502)
        return output.text

    def answer(self, request):
        if not self.lock.acquire(blocking=False):
            raise WorkerError("model_busy", 503)
        started = time.monotonic()
        deadline = started + DEADLINE_SECONDS
        telemetry = {"answer_policy": LINE_POLICY, "calls": [], "completion_attempts": 0,
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
                    if type(tokens) is not int or not 0 < tokens <= MAX_INPUT_TOKENS:
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


class BudgetBlockRuntime(MeetingRuntime):
    """One answer call with a 90s deadline shared by preparation and native work.

    The native adapter must honor its passed deadline. The final post-cleanup
    check rejects overruns; it cannot forcibly cancel a noncooperative backend.
    Extraction remains inherited and retains its existing separate contract.
    """

    def __init__(self, generator):
        if not isinstance(generator, BudgetBlockGenerator):
            raise TypeError("block_answer_generator_required")
        super().__init__(generator)

    def health(self):
        return {**super().health(), "protocol": PROTOCOL,
            "limits": {"input_tokens": MAX_INPUT_TOKENS, "output_tokens": MAX_NEW_TOKENS,
                       "deadline_seconds": DEADLINE_SECONDS}, "answer_policy": BLOCK_POLICY,
            "answer_limits": {"chunks": MAX_CHUNKS, "spans": MAX_SPANS,
                "codepoints_per_block": MAX_BLOCK_CODEPOINTS, "input_tokens": MAX_INPUT_TOKENS,
                "output_tokens": MAX_NEW_TOKENS, "deadline_seconds": DEADLINE_SECONDS,
                "completion_calls": 1}}

    def answer(self, request):
        if not self.lock.acquire(blocking=False):
            raise WorkerError("model_busy", 503)
        started = time.monotonic()
        deadline, failure, result = started + DEADLINE_SECONDS, None, None
        begun = False
        telemetry = {"answer_policy": BLOCK_POLICY, "completion_attempts": 0, "calls": [],
            "semantic_support_verified": False, "question_completeness_verified": False}
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
                catalog = build_block_catalog(request.contexts)
                telemetry.update(citation_metrics({"claims": []}, catalog))
                telemetry.update({"received_chunks": len(request.contexts),
                    "supplied_chunks": len(catalog.sources), "supplied_spans": len(catalog.spans),
                    "eligible_spans": len(catalog.eligible_ids),
                    "response_language": response_language(request.query),
                    "language_guard": "script_presence_only"})
                with self.generator.answer_catalog(catalog):
                    if time.monotonic() >= deadline:
                        raise WorkerError("generation_deadline_exceeded", 504)
                    prompt = answer_messages_blocks(request.query, catalog)
                    tokens = self.generator.count_tokens(prompt)
                    if type(tokens) is not int or not 0 < tokens <= MAX_INPUT_TOKENS:
                        raise WorkerError("generation_input_limit", 422)
                    if time.monotonic() >= deadline:
                        raise WorkerError("generation_deadline_exceeded", 504)
                    telemetry["completion_attempts"] = 1  # wrapper; native POST counted by runner
                    completion_started = time.monotonic()
                    telemetry["preprocessing_ms"] = round((completion_started - started) * 1000, 3)
                    metrics = {"input_tokens": tokens, "output_token_limit": MAX_NEW_TOKENS}
                    telemetry["calls"].append(metrics)
                    try:
                        output = self.generator.generate_bounded(prompt, deadline)
                    finally:
                        metrics["completion_wrapper_ms"] = round(
                            (time.monotonic() - completion_started) * 1000, 3)
                    metrics.update({"input_tokens": output.input_tokens,
                        "output_tokens": output.output_tokens, "elapsed_seconds": output.elapsed_seconds,
                        "finish_reason": output.finish_reason})
                    native = getattr(output, "telemetry", {}).get("native_timings", {})
                    metrics["native_timings"] = {key: value for key, value in native.items()
                        if key in {"cache_n", "prompt_n", "prompt_ms", "predicted_n", "predicted_ms"}
                        and type(value) in (int, float)}
                    if time.monotonic() >= deadline:
                        raise WorkerError("generation_deadline_exceeded", 504)
                    if output.finish_reason != "eos":
                        raise WorkerError("generation_output_truncated", 502)
                    if (type(output.output_tokens) is not int or not 0 < output.output_tokens <= MAX_NEW_TOKENS
                            or type(output.input_tokens) is not int
                            or not 0 < output.input_tokens <= MAX_INPUT_TOKENS):
                        raise WorkerError("generation_token_limit", 502)
                    result = grounded_answer_blocks(output.text, catalog, request.contexts,
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
        except Exception:  # noqa: BLE001 - no raw source/native errors cross worker boundary
            failure = WorkerError("generation_failed", 503)
        finally:
            cleanup_started = time.monotonic()
            try:
                if begun:
                    self.generator.end_request()
            except Exception:  # noqa: BLE001 - sanitize cleanup diagnostics too
                failure = failure or WorkerError("generation_cleanup_failed", 503)
            finally:
                try:
                    ended = time.monotonic()
                    if ended >= deadline:
                        failure = WorkerError("generation_deadline_exceeded", 504)
                    telemetry["elapsed_ms"] = round((ended - started) * 1000, 3)
                    telemetry["cleanup_ms"] = round((ended - cleanup_started) * 1000, 3)
                    if failure is not None:
                        telemetry["error_code"] = failure.code
                    self.last_telemetry = telemetry
                finally:
                    self.lock.release()
        if failure is not None:
            raise failure from None
        return {"schema_version": 1, "model": self.model, "revision": self.revision,
                **result, "telemetry": telemetry}
