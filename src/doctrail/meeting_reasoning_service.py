"""Opt-in single-call 9B reasoning QA; no native process management or activation.

The launcher owns exclusive GPU admission, process/runtime-file identity, resource
sampling and hard wall-clock termination/cleanup. This adapter owns pinned model
identity, HTTP/request limits, native split verification and citation projection.
512 reasoning tokens are REQUESTED, not an observed native segment hard cap.
Only final content is retokenized; neither reasoning nor source text is telemetry.
"""
from __future__ import annotations

import copy
import hashlib
import time

from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_contract import answer_evidence, grounded_answer_refs
from doctrail.meeting_gguf import GGUFGenerator, GGUFResult, _fail, _integer, _json, _same_setting
from doctrail.meeting_structured import QA_SCHEMA, requested_facts_messages
from doctrail.meeting_thinking_transport import (
    GGUF_SHA256,
    MANIFEST_SHA256,
    MODEL_ID,
    MODEL_REVISION,
    PREAMBLE,
    RUNTIME_COMMIT,
    ThinkingGenerator,
    request_body,
)
from doctrail.meeting_thinking_transport import (
    SETTINGS as FROZEN_SETTINGS,
)
from doctrail.meeting_worker import MeetingRuntime

PROFILE = "qwen35-9b-direct-reasoning-service-v1"
LIMITS = {"context_tokens": 8192, "input_tokens": 6144, "output_tokens": 1312,
          "final_retokenized_tokens": 768, "reasoning_tokens_requested": 512,
          "request_seconds": 150, "startup_seconds": 120, "gpu_layers": 28,
          "cpu_threads": 2, "parallel": 1, "owned_rss_bytes": 8 * 1024**3,
          "start_available_ram_bytes": 10 * 1024**3, "active_available_ram_bytes": 2 * 1024**3}
SETTINGS = {**FROZEN_SETTINGS, "n_predict": 1312, "max_tokens": 1312}
FAILURE_CODES = frozenset({
    "generation_backend_protocol", "generation_backend_response_limit",
    "generation_backend_unavailable", "generation_cleanup_failed",
    "generation_deadline_exceeded", "generation_effective_config_mismatch",
    "generation_failed", "generation_final_content_limit", "generation_identity_mismatch",
    "generation_input_limit", "generation_invalid_evidence", "generation_invalid_schema",
    "generation_not_ready", "generation_output_truncated", "generation_reasoning_split_mismatch",
    "generation_request_lifecycle", "generation_thinking_template_mismatch",
})
CALL_STAGES = frozenset({"request_capture", "template", "input_count", "native_http",
                         "response_capture", "native_validation", "final_tokenize",
                         "final_validation", "completed"})


def _safe_failure(error):
    code = getattr(error, "code", None)
    return code if isinstance(code, str) and code in FAILURE_CODES else "generation_failed"


def _safe_call(call):
    """Finite facts only; raw returned observations are distinct from validated counts."""
    if not isinstance(call, dict):
        return None
    result = {"operation": "meeting_qa", "output_cap": 1312}
    for field in ("dispatch_intent", "returned", "accepted"):
        if type(call.get(field)) is bool:
            result[field] = call[field]
    for field in ("input_tokens", "output_tokens", "observed_input_tokens",
                  "observed_output_tokens", "final_retokenized_tokens"):
        if type(call.get(field)) is int and 0 <= call[field] <= 2**31:
            result[field] = call[field]
    if call.get("stage") in CALL_STAGES:
        result["stage"] = call["stage"]
    if call.get("finish_reason") == "eos":
        result["finish_reason"] = "eos"
    return result


def reasoning_body(messages):
    body = request_body(copy.deepcopy(messages), copy.deepcopy(QA_SCHEMA))
    body.update(n_predict=LIMITS["output_tokens"], max_tokens=LIMITS["output_tokens"])
    body["response_format"]["json_schema"]["name"] = "meeting_qa"
    return body


def validate_reasoning_response(response, *, prompt, input_tokens):
    """Same pinned chat/native relationship as C4, with this profile's total cap.

    Frozen C4 validates a literal 928 cap; do not mutate it or normalize a response
    to evade that guard. Natural EOS is mandatory and strings are never repaired.
    """
    try:
        native = response["__verbose"]
        settings, timing = native["generation_settings"], native["timings"]
        if (any(not _same_setting(settings.get(k), v) for k, v in SETTINGS.items())
                or not isinstance(settings.get("stop"), list)
                or any(s not in {"<|im_end|>", "<|endoftext|>"} for s in settings["stop"])
                or not isinstance(settings.get("grammar"), str) or not settings["grammar"]):
            _fail("generation_effective_config_mismatch")
        choices, usage = response["choices"], response["usage"]
        if not isinstance(choices, list) or len(choices) != 1:
            _fail()
        choice = choices[0]
        message = choice["message"]
        count, tokens = native["tokens_predicted"], native["tokens"]
        if (response.get("model") != GGUF_SHA256 or native.get("model") != GGUF_SHA256
                or response.get("object") != "chat.completion"
                or response.get("system_fingerprint") != "b11429-d81235049"
                or native.get("prompt") != prompt or native.get("truncated") is not False
                or native.get("stop") is not True or not _integer(count, 1)
                or count > LIMITS["output_tokens"] or not isinstance(tokens, list)
                or len(tokens) != count or not all(_integer(t) for t in tokens)
                or not _same_setting(native.get("tokens_evaluated"), input_tokens)
                or not _same_setting(timing.get("prompt_n"), input_tokens)
                or not _same_setting(timing.get("predicted_n"), count)
                or not _same_setting(timing.get("cache_n"), 0)
                or not _same_setting(usage.get("prompt_tokens"), input_tokens)
                or not _same_setting(usage.get("completion_tokens"), count)
                or not _same_setting(usage.get("total_tokens"), input_tokens + count)
                or not _same_setting(usage.get("prompt_tokens_details", {}).get("cached_tokens"), 0)
                or message.get("role") != "assistant" or message.get("tool_calls")
                or not isinstance(message.get("content"), str)
                or not isinstance(message.get("reasoning_content"), str)
                or not message["reasoning_content"].strip()):
            _fail()
        if native.get("stop_type") != "eos" or choice.get("finish_reason") != "stop":
            _fail("generation_output_truncated")
        raw = native["content"]
        if not isinstance(raw, str) or raw.count("</think>") != 1 or "<think>" in raw:
            _fail("generation_reasoning_split_mismatch")
        before, _, after = raw.partition("</think>")
        framing = after.strip()
        fenced = framing.startswith("```json") and framing.endswith("```")
        if fenced:
            framing = framing[7:-3].strip()
        if (before.strip() != message["reasoning_content"].strip()
                or framing != message["content"].strip()
                or "</think>" in message["content"] or "<think>" in message["content"]):
            _fail("generation_reasoning_split_mismatch")
        _json(message["content"])
        return message["content"], count, {
            "native_timings": {k: timing[k] for k in ("cache_n", "prompt_n", "predicted_n")},
            "grammar_sha256": hashlib.sha256(settings["grammar"].encode()).hexdigest(),
            "reasoning_budget_tokens_requested": 512, "reasoning_budget_effective_serialized": False,
            "reasoning_split_verified": True, "native_token_ids_count": len(tokens),
            "native_json_framing": "fenced" if fenced else "bare",
            "final_token_measurement": "retokenized_content_not_generated_segment",
            "semantic_support_verified": False, "question_completeness_verified": False}
    except (KeyError, TypeError, ValueError, AttributeError):
        _fail()


class ReasoningServiceGenerator(ThinkingGenerator):
    """Structured-compatible generate_bounded seam, deliberately QA-only.

    load(deadline=...) accepts the launcher's original startup deadline; it must
    not receive a fresh deadline after model startup. Standalone load starts120s.
    Existing GGUF hashing is synchronous, so launcher hard-timeout enforcement
    remains required. close only closes owned HTTP state, never foreign processes.
    """
    profile = PROFILE

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_call = None
        self.development_capture = None

    def load(self, *, deadline=None):
        deadline = min(deadline, time.monotonic() + LIMITS["startup_seconds"]) if deadline is not None else time.monotonic() + LIMITS["startup_seconds"]
        self.begin_request(deadline)
        try:
            self._remaining(deadline)
            if (self.manifest_path.stat().st_size > 65536
                    or hashlib.sha256(self.manifest_path.read_bytes()).hexdigest() != MANIFEST_SHA256):
                _fail("generation_identity_mismatch")
            # Bypass C4's fixed6144 load policy; retain its base identity mechanism.
            GGUFGenerator.load(self)
            self._remaining(deadline)
            metadata = self._metadata
            if (metadata["repo_id"] != MODEL_ID or metadata["original_revision"] != MODEL_REVISION
                    or metadata["artifact"]["sha256"] != GGUF_SHA256
                    or metadata["runtime"]["tag"] != "b11429"
                    or metadata["runtime"]["commit"] != RUNTIME_COMMIT
                    or metadata["runtime"]["observed_build"] != "b11429-d81235049"
                    or not _same_setting(metadata["runtime"]["context_tokens"], 8192)):
                _fail("generation_identity_mismatch")
            metadata["generation_protocol"] = PROFILE
            metadata["runtime"].update(max_input_tokens=6144, max_new_tokens=1312, deadline_seconds=150)
            metadata["reasoning_profile"] = {"name": PROFILE, "opt_in": True, "limits": dict(LIMITS),
                "reasoning_budget_effective_serialized": False, "hardware_fit_measured": False,
                "semantic_quality_accepted": False, "resource_guard_owner": "launcher"}
            return self
        except Exception:
            self.close()
            raise
        finally:
            self.end_request()

    def begin_request(self, deadline):
        self.last_call = None
        super().begin_request(deadline)

    def _capture(self, event):
        if self.development_capture is not None:
            self.development_capture(copy.deepcopy(event))

    def count_tokens(self, messages):
        # The inherited C4 counter has a different limit and omits JSON schema.
        # Admission belongs to generate_bounded's exact complete request body.
        raise GenerationError("reasoning_requires_full_chat_body")

    def generate_neutral(self, *args, **kwargs):
        raise GenerationError("reasoning_qa_only")

    def generate_bounded(self, messages, deadline):
        if self._deadline is None or deadline != self._deadline:
            _fail("generation_request_lifecycle")
        self.public_metadata()
        started = time.monotonic()
        self.last_call = {"operation": "meeting_qa", "output_cap": 1312,
                          "dispatch_intent": False, "returned": False, "accepted": False,
                          "stage": "request_capture"}
        body = reasoning_body(messages)
        self._capture({"kind": "native_request", "stage": "qa", "body": body})
        # Full OAI body includes schema/template formatting; no input truncation.
        self.last_call["stage"] = "template"
        prompt = self._request("POST", "/apply-template", body, deadline).get("prompt")
        if not isinstance(prompt, str) or not prompt.endswith(PREAMBLE):
            _fail("generation_thinking_template_mismatch")
        self.last_call["stage"] = "input_count"
        counted = self._request("POST", "/v1/chat/completions/input_tokens", body, deadline)
        count = counted.get("input_tokens")
        if counted.get("object") != "response.input_tokens" or not _integer(count, 1):
            _fail()
        self.last_call["input_tokens"] = count
        if count > LIMITS["input_tokens"]:
            _fail("generation_input_limit")
        # Intent precedes _request deadline checks; it is not proof of HTTP send.
        self.last_call.update(dispatch_intent=True, stage="native_http")
        response = self._request("POST", "/v1/chat/completions", body, deadline)
        self.last_call.update(returned=True, stage="response_capture")
        native = response.get("__verbose")
        if isinstance(native, dict):
            for field, source in (("observed_input_tokens", "tokens_evaluated"),
                                  ("observed_output_tokens", "tokens_predicted")):
                if type(native.get(source)) is int and 0 <= native[source] <= 2**31:
                    self.last_call[field] = native[source]
        self._capture({"kind": "native_response", "stage": "qa", "body": response})
        self.last_call["stage"] = "native_validation"
        content, output_count, telemetry = validate_reasoning_response(response, prompt=prompt, input_tokens=count)
        self.last_call.update(output_tokens=output_count, finish_reason="eos", stage="final_tokenize")
        final_tokens = self._tokenize(content, False, deadline)
        self.last_call.update(final_retokenized_tokens=len(final_tokens), stage="final_validation")
        if not 0 < len(final_tokens) <= LIMITS["final_retokenized_tokens"]:
            _fail("generation_final_content_limit")
        self._remaining(deadline)
        self.last_effective_config = {**SETTINGS, "profile": PROFILE, "cache_prompt_requested": False,
            "observed_cache_tokens": 0, "reasoning_budget_tokens_requested": 512,
            "reasoning_budget_effective_serialized": False}
        telemetry.update(final_retokenized_tokens=len(final_tokens), profile=PROFILE)
        self.last_call.update(accepted=True, stage="completed")
        return GGUFResult(content, "eos", count, output_count, time.monotonic() - started, telemetry)


class ReasoningMeetingRuntime(MeetingRuntime):
    """Existing /answer envelope and citation projector, new150s request budget.

    Caller supplies already-authorized, revision-stable contexts; Java continues
    to own ACL/revision checks. No source selection, planner, review, retry or repair.
    """
    def set_development_capture(self, callback):
        if callback is not None and not callable(callback):
            raise TypeError("development_capture_requires_callable")
        self.generator.development_capture = callback

    def health(self):
        result = super().health()
        result.update(protocol=PROFILE, structured_profile=PROFILE)
        result["limits"] = {"input_tokens": 6144, "output_tokens": 1312,
                            "native_context_tokens": 8192, "deadline_seconds": 150,
                            "final_retokenized_tokens": 768}
        return result

    def analyze(self, request):
        raise WorkerError("analysis_not_supported", 422)

    def answer(self, request):
        if not self.lock.acquire(blocking=False):
            raise WorkerError("model_busy", 503)
        started, calls = time.monotonic(), []
        deadline = started + LIMITS["request_seconds"]
        self.last_telemetry = {}
        failure, cleanup_failed, stage = None, False, "request_start"
        try:
            self.generator.begin_request(deadline)
            if not request.contexts:
                answer = {"status": "abstained", "reason": "insufficient_evidence", "claims": []}
            else:
                stage = "evidence_mapping"
                sources, mapping = answer_evidence(request.contexts)
                messages = requested_facts_messages(request.query, sources)
                stage = "generation"
                output = self.generator.generate_bounded(messages, deadline)
                calls.append({"operation": "qa", "input_tokens": output.input_tokens,
                    "output_tokens": output.output_tokens, "output_cap": 1312,
                    "finish_reason": output.finish_reason, "elapsed_seconds": output.elapsed_seconds,
                    **output.telemetry})
                stage = "citation_projection"
                answer = grounded_answer_refs(output.text, mapping)
            stage = "response_validation"
            self.generator._remaining(deadline)
        except Exception as error:  # noqa: BLE001 - capture only finite safe codes
            failure = _safe_failure(error)
        finally:
            try:
                self.generator.end_request()
            except Exception:  # noqa: BLE001 - preserve first failure over cleanup
                cleanup_failed = True
                if failure is None:
                    stage = "cleanup"
                    failure = "generation_cleanup_failed"
            finally:
                # Cleanup consumes the original deadline, with no deadline restart.
                if failure is None and time.monotonic() >= deadline:
                    stage, failure = "cleanup", "generation_deadline_exceeded"
                native_call = _safe_call(self.generator.last_call)
                if stage == "generation" and native_call is not None:
                    stage = native_call.get("stage", "generation")
                self.last_telemetry = {"calls": calls, "native_call": native_call,
                    "request_stage": stage if failure else "completed",
                    "failure_code": failure, "service_accepted": failure is None,
                    "cleanup_failed": cleanup_failed,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                    "effective_generation_config": self.generator.last_effective_config}
                self.lock.release()
        if failure is not None:
            status = {"generation_deadline_exceeded": 504, "generation_input_limit": 422,
                      "generation_invalid_evidence": 502, "generation_invalid_schema": 502}.get(failure, 503)
            raise WorkerError(failure, status) from None
        return {"schema_version": 1, "model": self.model, "revision": self.revision,
                **answer, "telemetry": self.last_telemetry}
