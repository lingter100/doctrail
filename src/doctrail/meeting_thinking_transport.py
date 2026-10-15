"""C4-P0 resource-only chat transport. No quality policy or service integration.

The pinned native build does not serialize reasoning_budget_tokens in its
generation settings. It is recorded as requested, never as an observed hard cap.
Final-content token counts are retokenizations, not generated segment counts.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_gguf import GGUFGenerator, _fail, _integer, _json, _same_setting

MODEL_ID = "Qwen/Qwen3.5-9B"
MODEL_REVISION = "c202236235762e1c871ad0ccb60c8ee5ba337b9a"
GGUF_SHA256 = "dc2a39aef291f91a9116ad214058da0d86eb648743a124bd8c333787c4b9c91c"
MANIFEST_SHA256 = "c03d394c9a2e6c94654dc49047c8c851f46b5498871afbbd6d0e5b0b4f042c99"
RUNTIME_COMMIT = "d81235049384534c167caea52b85a694f6103d14"
PROTOCOL = "meeting-single-call-thinking-c4-p0-v1"
PREAMBLE = "<|im_start|>assistant\n<think>\n"
LIMITS = {"context_tokens": 6144, "input_tokens": 5120, "output_tokens": 928,
          "final_retokenized_tokens": 384, "request_seconds": 90}
SETTINGS = {"temperature": 0.0, "samplers": ["temperature"], "seed": 0,
            "dynatemp_range": 0.0, "mirostat": 0, "ignore_eos": False,
            "stream": False, "logit_bias": [], "grammar_lazy": False,
            "grammar_triggers": [], "lora": [], "n_predict": 928,
            "max_tokens": 928, "reasoning_format": "deepseek",
            "reasoning_in_content": False, "generation_prompt": PREAMBLE}


def request_body(messages, schema, alias=GGUF_SHA256):
    return {**{k: v for k, v in SETTINGS.items()
               if k not in {"generation_prompt", "reasoning_in_content"}},
            "model": alias, "messages": messages, "cache_prompt": False,
            "return_tokens": True, "verbose": True, "stop": [],
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget_tokens": 512, "reasoning_control": False,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "neutral_resource", "strict": True, "schema": schema}}}


@dataclass(frozen=True)
class ThinkingResult:
    content: str
    reasoning: str
    input_tokens: int
    output_tokens: int
    final_retokenized_tokens: int
    finish_reason: str
    elapsed_seconds: float
    telemetry: dict


def validate_response(response, *, prompt, input_tokens, stress=False):
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
        stop = "limit" if stress else "eos"
        if (verbose.get("stop_type") != stop
                or choice.get("finish_reason") != ("length" if stress else "stop")
                or (stress and output_n != 928)):
            _fail("generation_stop_mismatch")
        raw = verbose["content"]
        if not isinstance(raw, str) or raw.count("</think>") != 1 or "<think>" in raw:
            _fail("generation_reasoning_split_mismatch")
        before, _, after = raw.partition("</think>")
        framing = after.strip()
        fenced = framing.startswith("```json") and framing.endswith("```")
        partial_fence = stress and framing.startswith("```json") and not fenced
        if fenced:
            framing = framing[7:-3].strip()
        elif partial_fence:
            framing = framing[7:].strip()
        # Comparisons tolerate parser framing whitespace only; returned text is untouched.
        if (before.strip() != message["reasoning_content"].strip()
                or framing != message["content"].strip()
                or "</think>" in message["content"] or "<think>" in message["content"]):
            _fail("generation_reasoning_split_mismatch")
        if not stress:
            parsed = _json(message["content"])
            if parsed != {"marker": "teal"}:
                _fail("generation_neutral_json_mismatch")
        return {"content": message["content"], "reasoning": message["reasoning_content"],
                "output_tokens": output_n, "finish_reason": "length" if stress else "eos",
                "telemetry": {"native_timings": {k: timing[k] for k in
                    ("cache_n", "prompt_n", "predicted_n")},
                    "grammar_sha256": hashlib.sha256(settings["grammar"].encode()).hexdigest(),
                    "reasoning_budget_tokens_requested": 512,
                    "reasoning_budget_effective_serialized": False,
                    "reasoning_split_verified": True, "native_token_ids_count": len(tokens),
                    "native_json_framing": ("partial_fence" if partial_fence else
                                            "fenced" if fenced else "bare"),
                    "final_token_measurement": "retokenized_content_not_generated_segment"}}
    except (KeyError, TypeError, ValueError, AttributeError):
        _fail()


class ThinkingGenerator(GGUFGenerator):
    """Reuse only HTTP, identity hashing and lifecycle primitives from GGUFGenerator."""

    def load(self):
        if hashlib.sha256(self.manifest_path.read_bytes()).hexdigest() != MANIFEST_SHA256:
            self.close()
            _fail("generation_identity_mismatch")
        super().load()
        metadata = self._metadata
        if (metadata["repo_id"] != MODEL_ID or metadata["original_revision"] != MODEL_REVISION
                or metadata["artifact"]["sha256"] != GGUF_SHA256
                or metadata["runtime"]["tag"] != "b11429"
                or metadata["runtime"]["commit"] != RUNTIME_COMMIT
                or metadata["runtime"]["context_tokens"] != 6144):
            self.close()
            _fail("generation_identity_mismatch")
        metadata["generation_protocol"] = PROTOCOL
        metadata["runtime"].update(max_input_tokens=5120, max_new_tokens=928,
                                   deadline_seconds=90)
        metadata["thinking"] = {"enable_thinking_requested": True,
            "reasoning_format": "deepseek", "reasoning_budget_tokens_requested": 512,
            "reasoning_budget_effective_serialized": False}
        return self

    def _prepare(self, messages, deadline=None):
        body = {"messages": messages, "chat_template_kwargs": {"enable_thinking": True}}
        prompt = self._request("POST", "/apply-template", body, deadline).get("prompt")
        if not isinstance(prompt, str) or not prompt.endswith(PREAMBLE):
            _fail("generation_thinking_template_mismatch")
        tokens = self._tokenize(prompt, True, deadline)
        if not 0 < len(tokens) <= 5120:
            _fail("generation_input_limit")
        return prompt, tokens

    def _tokenize(self, content, parse_special, deadline):
        response = self._request("POST", "/tokenize", {"content": content,
            "add_special": False, "parse_special": parse_special, "with_pieces": False}, deadline)
        tokens = response.get("tokens")
        if not isinstance(tokens, list) or not all(_integer(t) for t in tokens):
            _fail()
        return tokens

    def count_tokens(self, messages):
        return len(self._prepare(messages)[1])

    def generate_neutral(self, messages, schema, *, stress=False, before_dispatch=None,
                         observe=None):
        started = time.monotonic()
        deadline = started + 90
        self.begin_request(deadline)
        try:
            prompt, tokens = self._prepare(messages, deadline)
            if stress and len(tokens) < 4992:
                _fail("generation_stress_input_target")
            payload = request_body(messages, schema, self._alias)
            if before_dispatch is not None:
                before_dispatch(prompt, tokens, payload)
            self._remaining(deadline)
            response = self._request("POST", "/v1/chat/completions", payload, deadline)
            if observe is not None:
                observe("response", response)
            result = validate_response(response, prompt=prompt, input_tokens=len(tokens), stress=stress)
            final_tokens = self._tokenize(result["content"], False, deadline)
            if observe is not None:
                observe("final_token_ids", final_tokens)
            if not stress and not 0 < len(final_tokens) <= 384:
                _fail("generation_final_content_limit")
            self._remaining(deadline)
            self.last_effective_config = {**SETTINGS, "cache_prompt_requested": False,
                "observed_cache_tokens": 0, "reasoning_budget_tokens_requested": 512,
                "reasoning_budget_effective_serialized": False}
            return ThinkingResult(**result, input_tokens=len(tokens),
                final_retokenized_tokens=len(final_tokens), elapsed_seconds=time.monotonic() - started)
        finally:
            self.end_request()

    def generate_bounded(self, messages, deadline):
        raise GenerationError("resource_only_transport")

    def classify_bounded(self, prompts, deadline):
        raise GenerationError("resource_only_transport")
