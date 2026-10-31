"""Opt-in Ministral JSON-schema transport and grounded summary assembly.

Schema compliance and same-model review are not semantic acceptance. Existing
generic QA citations, native identity verification and classification are reused.
No prompt truncation, output repair, compiler or alternate model fallback exists.
"""
from __future__ import annotations

import copy
import hashlib
import json
import time

from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_contract import strict_json
from doctrail.meeting_gguf import GREEDY, GGUFGenerator, GGUFResult, _fail, _integer, _same_setting
from doctrail.meeting_grounded_summary import (
    classified_analysis,
    parse_draft,
    parse_review,
    source_payload,
    summary_messages,
    summary_projection,
    validate_summary_analysis,
)
from doctrail.meeting_runtime import DEADLINE_SECONDS, MAX_NEW_TOKENS
from doctrail.meeting_runtime import MAX_INPUT_TOKENS as CLASSIFICATION_INPUT_TOKENS
from doctrail.meeting_worker import MeetingRuntime, classification_messages, partitions

PROFILE = "ministral3-json-schema-grounded-v1"
INPUT_TOKENS = 6144
CONTEXT_TOKENS = 8192
SUMMARY_TOKENS = 768
REVIEW_TOKENS = 128
MODEL_ID = "mistralai/Ministral-3-3B-Instruct-2512"
MODEL_SHA256 = "e23dd88b0e0951d3f5784d6d4092210cda2b006b251f33b226b283a6c9d1f6bb"


def claims_schema(status, text_limit):
    return {"type": "object", "additionalProperties": False, "required": ["status", "claims"],
            "properties": {"status": {"type": "string", "enum": [status, "abstained"]},
                "claims": {"type": "array", "minItems": 0, "maxItems": 6,
                    "items": {"type": "object", "additionalProperties": False,
                        "required": ["evidence", "text"], "properties": {
                            "evidence": {"type": "array", "minItems": 1, "maxItems": 4,
                                         "items": {"type": "integer", "minimum": 0}},
                            "text": {"type": "string", "minLength": 1, "maxLength": text_limit}}}}}}


QA_SCHEMA = claims_schema("answered", 2000)
DRAFT_SCHEMA = claims_schema("draft", 240)
REVIEW_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["claims", "coverage"],
    "properties": {"claims": {"type": "array", "minItems": 1, "maxItems": 6,
        "items": {"type": "array", "minItems": 2, "maxItems": 2, "prefixItems": [
            {"type": "integer", "minimum": 0, "maximum": 5},
            {"type": "string", "enum": ["supported", "unsupported", "uncertain"]}]}},
        "coverage": {"type": "string", "enum": ["sufficient", "insufficient", "uncertain"]}}}


class StructuredGenerator(GGUFGenerator):
    """The installed model's template and verified identity, never a Qwen preamble."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._prompts = {}
        self.close_error = None
        self._closed = False
        self.last_call = None
        self._client.event_hooks["response"].append(self._response_status)

    def _response_status(self, response):
        if self.last_call is not None and response.request.url.path == "/v1/chat/completions":
            self.last_call["http_status"] = response.status_code

    def load(self):
        super().load()
        if (self._metadata["repo_id"] != MODEL_ID or self._alias != MODEL_SHA256
                or self._metadata["runtime"]["context_tokens"] != CONTEXT_TOKENS):
            self.close()
            _fail("generation_identity_mismatch")
        return self

    def public_metadata(self):
        metadata = super().public_metadata()
        metadata["runtime"]["max_input_tokens"] = INPUT_TOKENS
        metadata["structured_output"] = {"profile": PROFILE, "opt_in": True,
            "endpoint": "/v1/chat/completions", "format": "json_schema", "qa_tokens": MAX_NEW_TOKENS,
            "summary_tokens": SUMMARY_TOKENS, "review_tokens": REVIEW_TOKENS,
            "input_tokens": INPUT_TOKENS, "native_context_tokens": CONTEXT_TOKENS,
            "classification_input_tokens": CLASSIFICATION_INPUT_TOKENS, "shared_request_seconds": DEADLINE_SECONDS,
            "semantic_quality_accepted": False, "review": "same_model_not_independent"}
        return metadata

    def begin_request(self, deadline):
        self._prompts.clear()
        self.last_call = None
        super().begin_request(deadline)

    def end_request(self):
        self._prompts.clear()
        super().end_request()

    def _prepare(self, messages, deadline=None):
        self._remaining(deadline)
        key = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        response = self._request("POST", "/apply-template", {"messages": messages,
            "chat_template_kwargs": {"enable_thinking": False}}, deadline)
        prompt = response.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            _fail()
        tokens = self._request("POST", "/tokenize", {"content": prompt, "add_special": False,
            "parse_special": True, "with_pieces": False}, deadline).get("tokens")
        if not isinstance(tokens, list) or not tokens or not all(_integer(token) for token in tokens):
            _fail()
        self._cache[key], self._prompts[key] = tokens, prompt
        while len(self._cache) > 8:
            old, _ = self._cache.popitem(last=False)
            self._prompts.pop(old, None)
        return tokens

    def structured(self, messages, deadline, name, schema, cap):
        try:
            return self._structured(messages, deadline, name, schema, cap)
        except (GenerationError, WorkerError) as error:
            if self.last_call is not None:
                self.last_call["error_code"] = error.code
            raise

    def _structured(self, messages, deadline, name, schema, cap):
        started = time.monotonic()
        self.last_effective_config = None
        self.last_call = {"operation": name, "output_cap": cap, "input_cap": INPUT_TOKENS,
                          "dispatched": False, "returned": False, "accepted": False, "validation_stage": "input"}
        tokens = self._prepare(messages, deadline)
        self.last_call["input_tokens"] = len(tokens)
        if len(tokens) > INPUT_TOKENS:
            _fail("generation_input_limit")
        prompt = self._prompts[json.dumps(messages, ensure_ascii=False, separators=(",", ":"))]
        expected = {**GREEDY, "n_predict": cap}
        body = {**expected, "max_tokens": cap, "model": self._alias, "messages": copy.deepcopy(messages),
                "cache_prompt": False, "return_tokens": True, "verbose": True,
                "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": name, "strict": True, "schema": copy.deepcopy(schema)}}}
        self.last_call["dispatched"] = True
        self.last_call["validation_stage"] = "http"
        response = self._request("POST", "/v1/chat/completions", body, deadline)
        self.last_call["returned"] = True
        self.last_call["validation_stage"] = "native_metadata"
        try:
            native = response["__verbose"]
            settings, timing = native["generation_settings"], native["timings"]
            for field in ("tokens_predicted", "tokens_evaluated"):
                value = native.get(field)
                if type(value) is int and 0 <= value <= 2**31:
                    self.last_call["observed_" + field] = value
            self.last_call["observed_stop_type"] = native.get("stop_type") if native.get("stop_type") in ("eos", "limit", "word") else "other"
            self.last_call["validation_stage"] = "effective_settings"
            if (any(not _same_setting(settings.get(key), value) for key, value in expected.items())
                    or not isinstance(settings.get("grammar"), str) or not settings["grammar"]):
                _fail("generation_effective_config_mismatch")
            choices, usage = response["choices"], response["usage"]
            if not isinstance(choices, list) or len(choices) != 1:
                _fail()
            message = choices[0]["message"]
            count, generated = native["tokens_predicted"], native["tokens"]
            self.last_call["validation_stage"] = "token_identity_integrity"
            if (response.get("object") != "chat.completion" or response.get("model") != self._alias
                    or response.get("system_fingerprint") != self._metadata["runtime"]["observed_build"]
                    or native.get("model") != self._alias or native.get("prompt") != prompt
                    or native.get("truncated") is not False or native.get("stop") is not True
                    or not _integer(count, 1) or count > cap or not isinstance(generated, list)
                    or len(generated) != count or not all(_integer(token) for token in generated)
                    or not _same_setting(native.get("tokens_evaluated"), len(tokens))
                    or not _same_setting(timing.get("prompt_n"), len(tokens))
                    or not _same_setting(timing.get("predicted_n"), count)
                    or not _same_setting(timing.get("cache_n"), 0)
                    or not _same_setting(usage.get("prompt_tokens"), len(tokens))
                    or not _same_setting(usage.get("completion_tokens"), count)
                    or not _same_setting(usage.get("total_tokens"), len(tokens) + count)
                    or not _same_setting(usage.get("prompt_tokens_details", {}).get("cached_tokens"), 0)
                    or message.get("role") != "assistant" or message.get("tool_calls")
                    or message.get("reasoning_content") not in (None, "")
                    or not isinstance(message.get("content"), str) or message["content"] != native.get("content")):
                _fail()
            self.last_call["validation_stage"] = "eos"
            if native.get("stop_type") != "eos" or choices[0].get("finish_reason") != "stop":
                _fail("generation_output_truncated")
            self.last_call["validation_stage"] = "json"
            if not isinstance(strict_json(message["content"]), dict):
                _fail("generation_invalid_schema")
        except (KeyError, TypeError, AttributeError):
            _fail()
        self._remaining(deadline)
        schema_sha = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
        self.last_effective_config = {"backend": "llama.cpp", "profile": PROFILE, **expected,
            "schema_sha256": schema_sha, "observed_grammar_sha256": hashlib.sha256(settings["grammar"].encode()).hexdigest(),
            "cache_prompt_requested": False, "observed_cache_tokens": 0}
        self.last_call.update(accepted=True, output_tokens=count, finish_reason="eos", validation_stage="accepted")
        return GGUFResult(message["content"], "eos", len(tokens), count, time.monotonic() - started,
                          {"backend": "llama.cpp", "operation": name, "schema_sha256": schema_sha})

    def generate_bounded(self, messages, deadline):
        return self.structured(messages, deadline, "meeting_qa", QA_SCHEMA, MAX_NEW_TOKENS)

    def summary_bounded(self, messages, deadline):
        return self.structured(messages, deadline, "meeting_summary", DRAFT_SCHEMA, SUMMARY_TOKENS)

    def review_bounded(self, messages, deadline):
        return self.structured(messages, deadline, "meeting_summary_review", REVIEW_SCHEMA, REVIEW_TOKENS)

    def close(self):
        if self._closed:
            return
        self._prompts.clear()
        try:
            super().close()
            self._closed = True
        except Exception as error:
            self.close_error = error
            raise


class StructuredMeetingRuntime(MeetingRuntime):
    """One request lock/deadline for classification, natural draft and review."""
    def health(self):
        result = super().health()
        result["limits"]["input_tokens"] = INPUT_TOKENS
        result["limits"]["native_context_tokens"] = CONTEXT_TOKENS
        result["structured_profile"] = PROFILE
        return result

    def _generate(self, prompt, deadline, telemetry):
        self.last_stage = "qa"
        if self.generator.count_tokens(prompt) > INPUT_TOKENS:
            raise WorkerError("generation_input_limit", 422)
        output = self.generator.generate_bounded(prompt, deadline)
        telemetry.append({"operation": "qa", "input_tokens": output.input_tokens,
                          "output_cap": MAX_NEW_TOKENS,
                          "output_tokens": output.output_tokens, "elapsed_seconds": output.elapsed_seconds,
                          "finish_reason": output.finish_reason, **output.telemetry})
        if output.finish_reason != "eos":
            raise WorkerError("generation_output_truncated", 502)
        return output.text

    def answer(self, request):
        if not request.contexts:
            return self._run(lambda deadline, telemetry: {
                "status": "abstained", "reason": "insufficient_evidence", "claims": []})
        return super().answer(request)

    def _run(self, operation):
        if not self.lock.acquire(blocking=False):
            raise WorkerError("model_busy", 503)
        started, telemetry, failure, result = time.monotonic(), [], None, None
        self.last_telemetry = {}
        self.last_stage = "request"
        try:
            self.generator.begin_request(started + DEADLINE_SECONDS)
            result = operation(started + DEADLINE_SECONDS, telemetry)
            if time.monotonic() - started >= DEADLINE_SECONDS:
                raise WorkerError("generation_deadline_exceeded", 504)
        except WorkerError as error:
            failure = error
        except GenerationError as error:
            status = {"generation_deadline_exceeded": 504, "generation_input_limit": 422}.get(error.code, 503)
            failure = WorkerError(error.code if status != 503 else "generation_failed", status)
        except Exception:  # noqa: BLE001 - never expose source/native exception text
            failure = WorkerError("generation_failed", 503)
        finally:
            try:
                self.generator.end_request()
            except Exception:  # noqa: BLE001 - cleanup cannot mask the first request failure
                if failure is None:
                    failure = WorkerError("generation_failed", 503)
            finally:
                receipt = {"calls": telemetry, "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                    "status": "failed" if failure else "complete", "effective_generation_config": self.generator.last_effective_config,
                    "last_structured_call": copy.deepcopy(self.generator.last_call), "stage": self.last_stage,
                    "failure_code": failure.code if failure else None}
                self.last_telemetry = receipt
                self.lock.release()
        if failure:
            raise failure
        return {"schema_version": 1, "model": self.model, "revision": self.revision,
                **result, "telemetry": receipt}

    def analyze(self, request):
        def run(deadline, telemetry):
            def check_time():
                if time.monotonic() >= deadline:
                    raise WorkerError("generation_deadline_exceeded", 504)
            check_time()
            self.last_stage = "partition"
            units = [unit for group in partitions(request.content, self.generator) for unit in group]
            source = source_payload(request.title, request.content, units)
            draft_messages = summary_messages(source)
            if self.generator.count_tokens(draft_messages) > INPUT_TOKENS:
                raise WorkerError("generation_input_limit", 422)
            check_time()
            self.last_stage = "classification"
            labels, metrics = self.generator.classify_bounded([classification_messages(unit) for unit in units], deadline)
            telemetry.append(metrics)
            analysis = classified_analysis(units, labels)
            check_time()
            self.last_stage = "summary"
            draft = self.generator.summary_bounded(draft_messages, deadline)
            telemetry.append({"operation": "summary", "input_tokens": draft.input_tokens,
                              "output_cap": SUMMARY_TOKENS,
                              "output_tokens": draft.output_tokens, "finish_reason": draft.finish_reason})
            if draft.finish_reason != "eos":
                raise WorkerError("generation_output_truncated", 502)
            claims = parse_draft(draft.text, units, request.content)
            check_time()
            self.last_stage = "review"
            review = self.generator.review_bounded(summary_messages(source, claims), deadline)
            telemetry.append({"operation": "summary_review", "input_tokens": review.input_tokens,
                              "output_cap": REVIEW_TOKENS,
                              "output_tokens": review.output_tokens, "finish_reason": review.finish_reason})
            if review.finish_reason != "eos":
                raise WorkerError("generation_output_truncated", 502)
            reviewed = parse_review(review.text, len(claims))
            analysis.update(summary_version=2, summary_claims=claims, **summary_projection(claims, request.content))
            validate_summary_analysis(analysis, request.content)
            self.last_stage = "assembled"
            return {"analysis": analysis, "summary_review": reviewed}
        return self._run(run)
