"""Pinned Qwen3.5 candidate with verified nonthinking assistant preambles.

Official template provenance:
https://huggingface.co/Qwen/Qwen3.5-9B/blob/c202236235762e1c871ad0ccb60c8ee5ba337b9a/chat_template.jinja
Only the terminal assistant preamble is checked. Literal <think> in source data is
not generated reasoning and must not trigger text removal or blanket rejection.
"""
from __future__ import annotations

import hashlib
import json

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_answer_grammar import GrammarAnswerGenerator
from doctrail.meeting_gguf import _fail, _integer

MODEL_ID = "Qwen/Qwen3.5-9B"
MODEL_REVISION = "c202236235762e1c871ad0ccb60c8ee5ba337b9a"
GGUF_SHA256 = "dc2a39aef291f91a9116ad214058da0d86eb648743a124bd8c333787c4b9c91c"
NONTHINKING_PREAMBLE = "<|im_start|>assistant\n<think>\n\n</think>\n\n"
PREAMBLE_SHA256 = hashlib.sha256(NONTHINKING_PREAMBLE.encode("utf-8")).hexdigest()


class Qwen35Generator(GrammarAnswerGenerator):
    """Same v2 prompt and answer grammar; no decoding fallback or output cleanup."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._template_verified = False

    def load(self):
        super().load()
        try:
            metadata = super().public_metadata()
            if (metadata["repo_id"] != MODEL_ID or metadata["original_revision"] != MODEL_REVISION
                    or metadata["artifact"]["sha256"] != GGUF_SHA256):
                _fail("generation_identity_mismatch")
            return self
        except (GenerationError, KeyError):
            self.close()
            _fail("generation_identity_mismatch")

    def public_metadata(self):
        return {**super().public_metadata(), "nonthinking": {
            "policy": "qwen35-terminal-assistant-preamble-v1", "enable_thinking_requested": False,
            "assistant_preamble_sha256": PREAMBLE_SHA256,
            "last_template_verified": self._template_verified,
            "verification_scope": "terminal_assistant_preamble_per_prompt"}}

    def begin_request(self, deadline):
        super().begin_request(deadline)
        self._template_verified = False

    def _prepare(self, messages, deadline=None):
        self._remaining(deadline)
        key = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
        if key in self._cache:
            self._cache.move_to_end(key)
            self._template_verified = True
            return self._cache[key]
        self._template_verified = False
        response = self._request("POST", "/apply-template", {"messages": messages,
            "chat_template_kwargs": {"enable_thinking": False}}, deadline)
        prompt = response.get("prompt")
        if not isinstance(prompt, str) or not prompt.endswith(NONTHINKING_PREAMBLE):
            _fail("generation_nonthinking_template_mismatch")
        tokenized = self._request("POST", "/tokenize", {"content": prompt,
            "add_special": False, "parse_special": True, "with_pieces": False}, deadline)
        tokens = tokenized.get("tokens")
        if not isinstance(tokens, list) or not tokens or not all(_integer(t) for t in tokens):
            _fail()
        self._template_verified = True
        self._cache[key] = tokens
        while len(self._cache) > 8:
            self._cache.popitem(last=False)
        return tokens

    def _complete(self, messages, deadline, token_limit, grammar=""):
        output = super()._complete(messages, deadline, token_limit, grammar)
        if not self._template_verified:
            _fail("generation_nonthinking_template_mismatch")
        self.last_effective_config["observed_nonthinking_preamble_sha256"] = PREAMBLE_SHA256
        self.last_effective_config["enable_thinking_requested"] = False
        return output
