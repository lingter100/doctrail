"""C4 quality-only adapter with frozen native budgets and explicit trace hooks.

The common validator mirrors C4-P0 normal guards, without its neutral marker check.
No stress bypass, output repair, retry, service registration or semantic proof.
"""
from __future__ import annotations

import copy
import hashlib
import threading
import time
from dataclasses import asdict, dataclass

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_answer_thinking import (
    CANDIDATE_ID,
    grounded_answer_thinking,
    prepare_answer,
)
from doctrail.meeting_gguf import _fail, _integer, _json, _same_setting
from doctrail.meeting_thinking_transport import (
    GGUF_SHA256,
    SETTINGS,
    ThinkingGenerator,
    ThinkingResult,
    request_body,
)


def validate_quality_response(response, *, prompt, input_tokens):
    """Model-free validation also used by replay; never repair returned strings."""
    try:
        verbose = response["__verbose"]
        settings = verbose["generation_settings"]
        if any(not _same_setting(settings.get(k), v) for k, v in SETTINGS.items()):
            _fail("generation_effective_config_mismatch")
        # Template-generated stops may only be native chat EOG markers, not text stops.
        if (not isinstance(settings.get("stop"), list)
                or any(s not in {"<|im_end|>", "<|endoftext|>"} for s in settings["stop"])
                or not isinstance(settings.get("grammar"), str) or not settings["grammar"]):
            _fail("generation_effective_config_mismatch")
        choices = response["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            _fail()
        choice, usage, timing = choices[0], response["usage"], verbose["timings"]
        message = choice["message"]
        output_n, tokens = verbose["tokens_predicted"], verbose["tokens"]
        if (response.get("model") != GGUF_SHA256 or verbose.get("model") != GGUF_SHA256
                or response.get("object") != "chat.completion"
                or response.get("system_fingerprint") != "b11429-d81235049"
                or verbose.get("prompt") != prompt or verbose.get("truncated") is not False
                or verbose.get("stop") is not True or not _integer(output_n, 1)
                or output_n > 928 or not isinstance(tokens, list) or len(tokens) != output_n
                or not all(_integer(t) for t in tokens)
                or not _same_setting(verbose.get("tokens_evaluated"), input_tokens)
                or not _same_setting(timing.get("prompt_n"), input_tokens)
                or not _same_setting(timing.get("predicted_n"), output_n)
                or not _same_setting(timing.get("cache_n"), 0)
                or not _same_setting(usage.get("prompt_tokens"), input_tokens)
                or not _same_setting(usage.get("completion_tokens"), output_n)
                or not _same_setting(usage.get("total_tokens"), input_tokens + output_n)
                or not _same_setting(usage.get("prompt_tokens_details", {}).get("cached_tokens"), 0)
                or message.get("role") != "assistant" or message.get("tool_calls")
                or not isinstance(message.get("content"), str)
                or not isinstance(message.get("reasoning_content"), str)
                or not message["reasoning_content"].strip()):
            _fail()
        if (verbose.get("stop_type") != "eos"
                or choice.get("finish_reason") != "stop"):
            _fail("generation_stop_mismatch")
        raw = verbose["content"]
        if not isinstance(raw, str) or raw.count("</think>") != 1 or "<think>" in raw:
            _fail("generation_reasoning_split_mismatch")
        before, _, after = raw.partition("</think>")
        framing = after.strip()
        fenced = framing.startswith("```json") and framing.endswith("```")
        if fenced:
            framing = framing[7:-3].strip()
        # Comparisons tolerate parser framing whitespace only; returned text is untouched.
        if (before.strip() != message["reasoning_content"].strip()
                or framing != message["content"].strip()
                or "</think>" in message["content"] or "<think>" in message["content"]):
            _fail("generation_reasoning_split_mismatch")
        _json(message["content"])  # Strict object JSON; answer shape is checked by the mapper.
        return {"content": message["content"], "reasoning": message["reasoning_content"],
                "output_tokens": output_n, "finish_reason": "eos",
                "telemetry": {"native_timings": {k: timing[k] for k in
                    ("cache_n", "prompt_n", "predicted_n")},
                    "grammar_sha256": hashlib.sha256(settings["grammar"].encode()).hexdigest(),
                    "reasoning_budget_tokens_requested": 512,
                    "reasoning_budget_effective_serialized": False,
                    "reasoning_split_verified": True, "native_token_ids_count": len(tokens),
                    "native_json_framing": ("fenced" if fenced else "bare"),
                    "final_token_measurement": "retokenized_content_not_generated_segment"}}
    except (KeyError, TypeError, ValueError, AttributeError):
        _fail()


@dataclass(frozen=True)
class QualityAnswerResult:
    answer: dict
    completion: ThinkingResult


class QualityThinkingGenerator(ThinkingGenerator):
    """One call; preparation, callbacks, native work and mapping share 90 seconds.

    The observer is an explicit raw-data archival hook, never ordinary telemetry.
    Frozen HTTP refuses non-200 bodies before reading them. Such failures record
    status and body_available=False rather than inventing a raw error response.
    """

    def __init__(self, llama_url, token, identity_manifest_path, *, transport=None):
        super().__init__(llama_url, token, identity_manifest_path, transport=transport)
        self._answer_lock = threading.Lock()
        self._observer = None
        self._operation = None
        self._http_status = None
        self._client.event_hooks["request"].append(self._observe_send)
        self._client.event_hooks["response"].append(self._observe_status)

    def public_metadata(self):
        return {**super().public_metadata(), "candidate_id": CANDIDATE_ID}

    def _emit(self, key, value):
        if self._observer is not None:
            self._observer(key, copy.deepcopy(value))

    def _observe_status(self, response):
        if self._operation is not None:
            self._http_status = response.status_code
            self._emit(self._operation + "_http_status", response.status_code)

    def _observe_send(self, request):
        remaining = self._remaining()
        if request.method == "POST" and request.url.path == "/v1/chat/completions":
            # Archival attempt precedes transport. An aborted hook sends no POST.
            try:
                self._emit("native_post_started", True)
                remaining = self._remaining()
            except GenerationError as error:
                self._emit("native_post_aborted", {"code": error.code})
                raise
        # Frozen HTTP calculated this before hooks; archival time consumes it too.
        request.extensions["timeout"] = {key: min(value, remaining)
            if value is not None else remaining
            for key, value in request.extensions.get("timeout", {}).items()}

    def _request(self, method, path, payload=None, deadline=None):
        operation = {"/apply-template": "apply_template",
                     "/v1/chat/completions": "native"}.get(path)
        if path == "/tokenize":
            operation = "input_tokenize" if payload["parse_special"] else "final_tokenize"
        self._operation, self._http_status = operation, None
        try:
            if operation:
                self._emit(operation + "_request", payload)
            response = super()._request(method, path, payload, deadline)
            if operation:
                self._emit(operation + "_response", response)
                if operation == "native":
                    self._emit("response", response)
            return response
        except GenerationError as error:
            if operation:
                self._emit(operation + "_error", {"code": error.code,
                    "http_status": self._http_status, "body_available": False})
            raise
        finally:
            self._operation = None

    def answer(self, request, response_language, *, before_dispatch=None, observe=None):
        if not self._answer_lock.acquire(blocking=False):
            _fail("model_busy")
        started = time.monotonic()
        deadline = started + 90
        self._observer = observe
        try:
            # Readiness remains identity-verified by inherited load().
            self.public_metadata()
            self.begin_request(deadline)
            prepared = prepare_answer(request, response_language)
            self._emit("prepared", {"messages": prepared.messages, "schema": prepared.schema,
                                    "response_language": response_language})
            prompt, tokens = self._prepare(prepared.messages, deadline)
            payload = request_body(prepared.messages, prepared.schema, self._alias)
            if before_dispatch is not None:
                before_dispatch(prompt, copy.deepcopy(tokens), copy.deepcopy(payload))
            self._remaining(deadline)
            raw = self._request("POST", "/v1/chat/completions", payload, deadline)
            validated = validate_quality_response(raw, prompt=prompt, input_tokens=len(tokens))
            final_tokens = self._tokenize(validated["content"], False, deadline)
            self._emit("final_token_ids", final_tokens)
            if not 0 < len(final_tokens) <= 384:
                _fail("generation_final_content_limit")
            answer = grounded_answer_thinking(validated["content"], prepared.catalog,
                prepared.request.contexts, response_language)
            self._remaining(deadline)
            self.last_effective_config = {**SETTINGS, "cache_prompt_requested": False,
                "observed_cache_tokens": 0, "reasoning_budget_tokens_requested": 512,
                "reasoning_budget_effective_serialized": False}
            validated["telemetry"].update(candidate_id=CANDIDATE_ID,
                semantic_support_verified=False, question_completeness_verified=False,
                language_guard="script_presence_only")
            completion = ThinkingResult(**validated, input_tokens=len(tokens),
                final_retokenized_tokens=len(final_tokens), elapsed_seconds=time.monotonic() - started)
            result = QualityAnswerResult(answer, completion)
            self._emit("result", asdict(result))
            self._remaining(deadline)
            return result
        finally:
            try:
                self.end_request()
            finally:
                self._observer = None
                self._answer_lock.release()

