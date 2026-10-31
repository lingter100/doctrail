"""Opt-in C3 runtime: at most two stages under one preparation/native/cleanup clock.

No service registration, model download, retry, fallback or output repair. The
existing native adapter verifies pinned Qwen identity, nonthinking template, cache,
greedy effective settings and request/response byte limits on every dispatch.
The launcher, not this inference adapter, owns process termination and its receipts.
"""
from __future__ import annotations

import hashlib
import time

from pydantic import ValidationError

from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_answer_blocks import build_block_catalog, citation_metrics
from doctrail.meeting_answer_requirements import (
    ANSWER_POLICY,
    DECODER_POLICY,
    abstained_answer,
    grounded_requirement_answer,
    parse_requirement_plan,
    realization_grammar,
    realization_messages,
    requirement_messages,
    requirement_plan_grammar,
    validate_language,
)
from doctrail.meeting_answer_spans import SpanAnswerGenerator, response_language
from doctrail.meeting_contract import AnswerRequest
from doctrail.meeting_input_budget import (
    CONTEXT_TOKENS,
    DEADLINE_SECONDS,
    MAX_INPUT_TOKENS,
    MAX_NEW_TOKENS,
    BudgetGGUFGenerator,
)
from doctrail.meeting_worker import MeetingRuntime

MAX_CALLS = 2
CLEANUP_SECONDS = 5


class RequirementsGGUFGenerator(BudgetGGUFGenerator):
    """Same 5120/384/6144 pinned native transport, explicitly identified as C3."""

    def public_metadata(self):
        return {**super().public_metadata(), "generation_protocol": ANSWER_POLICY}


class RequirementsGenerator(SpanAnswerGenerator):
    """Bind the two-stage order and deadline; supplied fake bases are for tests only."""

    def __init__(self, base):
        super().__init__(base)
        self._request_deadline = None
        self._stage = 0

    def begin_request(self, deadline):
        if self._request_deadline is not None:
            raise WorkerError("model_busy", 503)
        self._request_deadline, self._stage = deadline, 0
        super().begin_request(deadline)

    def end_request(self):
        try:
            super().end_request()
        finally:
            self._request_deadline, self._stage = None, 0

    def public_metadata(self):
        metadata = self.base.public_metadata()
        return {**metadata, "generation_protocol": ANSWER_POLICY,
            "runtime": {**metadata.get("runtime", {}), "max_input_tokens": MAX_INPUT_TOKENS,
                "max_new_tokens": MAX_NEW_TOKENS, "deadline_seconds": DEADLINE_SECONDS},
            "answer_decoder": {"policy": DECODER_POLICY, "answer_policy": ANSWER_POLICY,
                "grammar_sha256": self._last_grammar_sha256,
                "grammar_scope": "current_stage_catalog_or_requirement_ids",
                "guarantee_scope": "structure_and_catalog_membership_only"}}

    def generate_stage(self, messages, deadline, stage, catalog, language, plan=None):
        if (self._request_deadline is None or deadline != self._request_deadline
                or type(stage) is not int or stage != self._stage + 1 or stage > MAX_CALLS):
            raise WorkerError("generation_call_limit", 502)
        if time.monotonic() >= deadline:
            raise WorkerError("generation_deadline_exceeded", 504)
        if stage == 1:
            if plan is not None:
                raise WorkerError("generation_invalid_schema", 502)
            grammar = requirement_plan_grammar(catalog)
        else:
            grammar = realization_grammar(plan, catalog, language)
        self._last_grammar_sha256 = hashlib.sha256(grammar.encode("utf-8")).hexdigest()
        # Advance before native work; a failed attempt cannot be retried in this request.
        self._stage = stage
        return self.base._complete(messages, deadline, MAX_NEW_TOKENS, grammar)

    def generate_bounded(self, messages, deadline):
        # Prevent accidentally selecting this wrapper through a one-stage answer route.
        raise WorkerError("generation_stage_required", 502)


class RequirementsRuntime(MeetingRuntime):
    def __init__(self, generator):
        if not isinstance(generator, RequirementsGenerator):
            raise TypeError("requirements_generator_required")
        super().__init__(generator)

    def health(self):
        return {**super().health(), "protocol": ANSWER_POLICY, "answer_policy": ANSWER_POLICY,
            "limits": {"input_tokens": MAX_INPUT_TOKENS, "output_tokens": MAX_NEW_TOKENS,
                "deadline_seconds": DEADLINE_SECONDS},
            "answer_limits": {"input_tokens_per_stage": MAX_INPUT_TOKENS,
                "output_tokens_per_stage": MAX_NEW_TOKENS, "output_tokens_total": 768,
                "context_tokens": CONTEXT_TOKENS, "completion_calls": MAX_CALLS,
                "shared_deadline_seconds": DEADLINE_SECONDS, "cleanup_seconds": CLEANUP_SECONDS}}

    def _stage(self, prompt, deadline, stage, catalog, language, telemetry, plan=None):
        if time.monotonic() >= deadline:
            raise WorkerError("generation_deadline_exceeded", 504)
        # Stage 2 is counted only now, from the actual generated plan and selected units.
        tokens = self.generator.count_tokens(prompt)
        if type(tokens) is not int or not 0 < tokens <= MAX_INPUT_TOKENS:
            raise WorkerError("generation_input_limit", 422)
        if time.monotonic() >= deadline:
            raise WorkerError("generation_deadline_exceeded", 504)
        metrics = {"stage": stage, "input_tokens": tokens, "output_token_limit": MAX_NEW_TOKENS}
        telemetry["calls"].append(metrics)
        telemetry["completion_attempts"] += 1
        started = time.monotonic()
        try:
            output = self.generator.generate_stage(prompt, deadline, stage, catalog, language, plan)
        finally:
            metrics["completion_wrapper_ms"] = round((time.monotonic() - started) * 1000, 3)
            metrics["grammar_sha256"] = self.generator._last_grammar_sha256
        metrics.update({"input_tokens": output.input_tokens, "output_tokens": output.output_tokens,
            "elapsed_seconds": output.elapsed_seconds, "finish_reason": output.finish_reason})
        native = getattr(output, "telemetry", {}).get("native_timings", {})
        metrics["native_timings"] = {k: v for k, v in native.items()
            if k in {"cache_n", "prompt_n", "prompt_ms", "predicted_n", "predicted_ms"}
            and type(v) in (int, float)}
        if time.monotonic() >= deadline:
            raise WorkerError("generation_deadline_exceeded", 504)
        if output.finish_reason != "eos":
            raise WorkerError("generation_output_truncated", 502)
        if (type(output.input_tokens) is not int or not 0 < output.input_tokens <= MAX_INPUT_TOKENS
                or output.input_tokens != tokens or type(output.output_tokens) is not int
                or not 0 < output.output_tokens <= MAX_NEW_TOKENS):
            raise WorkerError("generation_token_limit", 502)
        telemetry["completed_stages"] += 1
        return output.text

    def answer(self, request, *, language=None):
        """Existing DTO plus optional explicit ko/en override for the offline experiment.

        Public service routing is intentionally unchanged. Without an override the
        existing query-script heuristic is used, and its limitation is disclosed.
        """
        if not self.lock.acquire(blocking=False):
            raise WorkerError("model_busy", 503)
        started = time.monotonic()
        deadline, result, failure, begun = started + DEADLINE_SECONDS, None, None, False
        telemetry = {"answer_policy": ANSWER_POLICY, "completion_attempts": 0,
            "completed_stages": 0, "validated_stages": 0, "calls": [],
            "semantic_support_verified": False,
            "question_completeness_verified": False,
            "attempt_count_scope": "completion_wrapper_not_native_post",
            "language_guard": "script_presence_only"}
        self.last_telemetry = {}
        try:
            try:
                request = AnswerRequest.model_validate(request.model_dump())
            except (ValidationError, AttributeError, TypeError):
                raise WorkerError("invalid_request", 422) from None
            telemetry["language_source"] = "query_script_heuristic" if language is None else "explicit"
            language = response_language(request.query) if language is None else language
            validate_language(language)
            telemetry["response_language"] = language
            begun = True
            self.generator.begin_request(deadline)
            # Capture after resetting request-scoped grammar/template observations;
            # a reused runtime must not attribute the previous request to this one.
            telemetry["resource_identity"] = self.generator.public_metadata()
            if not request.contexts:
                result = abstained_answer()
            else:
                catalog = build_block_catalog(request.contexts)
                telemetry.update(citation_metrics({"claims": []}, catalog))
                telemetry.update(received_chunks=len(request.contexts),
                                 supplied_spans=len(catalog.spans))
                raw = self._stage(requirement_messages(request.query, catalog, language), deadline,
                                  1, catalog, language, telemetry)
                plan = parse_requirement_plan(raw, catalog, language)
                telemetry["validated_stages"] = 1
                # Safe diagnostics identify slots/statuses, never raw question/need/source text.
                telemetry["requirements"] = [{"requirement_id": r.requirement_id,
                    "status": r.status, "evidence_count": len(r.evidence_ids)}
                    for r in plan.requirements]
                if not plan.supported:
                    result = abstained_answer()
                else:
                    raw = self._stage(realization_messages(request.query, catalog, plan, language),
                                      deadline, 2, catalog, language, telemetry, plan)
                    result = grounded_requirement_answer(raw, catalog, request.contexts,
                                                         plan, language)
                    telemetry["validated_stages"] = 2
                    telemetry.update(citation_metrics(result, catalog))
        except WorkerError as error:
            failure = error
        except GenerationError as error:
            safe = {"generation_deadline_exceeded": 504, "generation_input_limit": 422,
                    "generation_effective_config_mismatch": 503,
                    "generation_nonthinking_template_mismatch": 503,
                    "generation_identity_mismatch": 503}
            code = error.code if error.code in safe else "generation_failed"
            failure = WorkerError(code, safe.get(code, 503))
        except Exception:  # noqa: BLE001 - raw model/source errors never escape
            failure = WorkerError("generation_failed", 503)
        finally:
            cleanup_started = time.monotonic()
            try:
                if begun:
                    self.generator.end_request()
            except Exception:  # noqa: BLE001 - sanitize cleanup errors
                failure = failure or WorkerError("generation_cleanup_failed", 503)
            finally:
                try:
                    ended = time.monotonic()
                    if ended >= deadline:
                        failure = WorkerError("generation_deadline_exceeded", 504)
                    elif ended - cleanup_started > CLEANUP_SECONDS:
                        failure = WorkerError("generation_cleanup_failed", 503)
                    telemetry.update(elapsed_ms=round((ended - started) * 1000, 3),
                                     cleanup_ms=round((ended - cleanup_started) * 1000, 3))
                    if failure:
                        telemetry["error_code"] = failure.code
                    self.last_telemetry = telemetry
                finally:
                    self.lock.release()
        if failure:
            raise failure from None
        return {"schema_version": 1, "model": self.model, "revision": self.revision,
                **result, "telemetry": telemetry}
