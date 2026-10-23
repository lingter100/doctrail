"""Decoder-only candidate for the unchanged evidence-first answer policy.

The grammar contains JSON structure, counts and the allowed integer ID range only.
It cannot guarantee exact quotes, correct IDs, entailment, language or completeness;
the unchanged v2 parser and independent semantic review remain necessary.
"""
from __future__ import annotations

import hashlib

from doctrail.meeting_answer_v2 import ANSWER_POLICY
from doctrail.meeting_gguf import GGUFGenerator
from doctrail.meeting_runtime import MAX_NEW_TOKENS

DECODER_POLICY = "meeting-answer-json-grammar-v1"
# JSON character escapes follow the pinned llama.cpp grammars/json.gbnf. Compact
# serialization intentionally has no optional whitespace outside string values.
ANSWER_GRAMMAR = r'''root ::= answered | abstained
answered ::= "{\"status\":\"answered\",\"claims\":[" claim ("," claim){0,5} "]}"
abstained ::= "{\"status\":\"abstained\",\"claims\":[]}"
claim ::= "{\"evidence\":[" evidence ("," evidence){0,3} "],\"text\":" string "}"
evidence ::= "{\"id\":" [0-9] ",\"quote\":" string "}"
string ::= "\"" char+ "\""
char ::= [^"\\\x7F\x00-\x1F] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F]{4})
'''
GRAMMAR_SHA256 = hashlib.sha256(ANSWER_GRAMMAR.encode("utf-8")).hexdigest()


class GrammarAnswerGenerator(GGUFGenerator):
    """Same model, prompt and greedy settings; only answer decoding is constrained."""

    def public_metadata(self):
        return {**super().public_metadata(), "answer_decoder": {
            "policy": DECODER_POLICY, "answer_policy": ANSWER_POLICY,
            "grammar_sha256": GRAMMAR_SHA256, "guarantee_scope": "json_structure_only"}}

    def generate_bounded(self, messages, deadline):
        # _complete validates that the native response echoes this exact grammar,
        # along with the existing greedy configuration and token-budget checks.
        return self._complete(messages, deadline, MAX_NEW_TOKENS, ANSWER_GRAMMAR)
