"""Bounded M5 prompt and structural citation validation, without model inference.

Evidence must already be authorized and current when supplied by the caller. Exact
quotes prove text/span identity only: they do not establish truth or entailment.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

MAX_QUESTION_CP = 500
MAX_EVIDENCE = 5
MAX_EVIDENCE_TEXT_CP = 2000
MAX_CONTEXT_CP = 8000
MAX_OUTPUT_CP = 32768
PROMPT_PATH = Path(__file__).resolve().parents[2] / "data/prompts/m5-grounded-answer-v1.txt"
_EVIDENCE_KEYS = {
    "evidence_id", "document_id", "revision", "source_sha256", "start_cp", "end_cp", "text"
}
_REASONS = {"insufficient_evidence", "conflicting_evidence", "ambiguous_question"}
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class GroundedAnswerError(ValueError):
    """Safe error code only; do not include question, evidence, or model output."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise GroundedAnswerError(code)


def _text(value: Any, maximum: int, code: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        _fail(code)
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail(code)
    return value


def _exact_keys(value: Any, expected: set[str], code: str) -> None:
    if type(value) is not dict or set(value) != expected:
        _fail(code)


def _validate_evidence(evidence: Any) -> list[dict[str, Any]]:
    if type(evidence) is not list or len(evidence) > MAX_EVIDENCE:
        _fail("input_evidence_count")
    normalized = []
    ids: set[str] = set()
    total = 0
    for item in evidence:
        _exact_keys(item, _EVIDENCE_KEYS, "input_evidence_schema")
        for field in ("evidence_id", "document_id"):
            if type(item[field]) is not str or not _IDENTIFIER.fullmatch(item[field]):
                _fail("input_evidence_identifier")
        if item["evidence_id"] in ids:
            _fail("input_evidence_duplicate_id")
        ids.add(item["evidence_id"])
        if type(item["revision"]) is not int or item["revision"] < 1:
            _fail("input_evidence_revision")
        if type(item["source_sha256"]) is not str or not _SHA256.fullmatch(item["source_sha256"]):
            _fail("input_evidence_source_hash")
        chunk = _text(item["text"], MAX_EVIDENCE_TEXT_CP, "input_evidence_text")
        start, end = item["start_cp"], item["end_cp"]
        if type(start) is not int or type(end) is not int or start < 0 or end - start != len(chunk):
            _fail("input_evidence_span")
        total += len(chunk)
        normalized.append(dict(item))
    if total > MAX_CONTEXT_CP:
        _fail("input_context_length")
    return normalized


def validate_input(question: Any, evidence: Any) -> list[dict[str, Any]]:
    """Validate without truncation or Unicode normalization; return evidence copies."""
    _text(question, MAX_QUESTION_CP, "input_question")
    return _validate_evidence(evidence)


def pre_generation_guard(question: Any, evidence: Any) -> dict[str, Any] | None:
    """Return a no-context abstention without pretending a model was called."""
    checked = validate_input(question, evidence)
    if checked:
        return None
    return {
        "status": "abstained",
        "reason": "insufficient_evidence",
        "claims": [],
        "semantic_support": "not_verified",
        "model_called": False,
    }


def build_messages(question: Any, evidence: Any) -> list[dict[str, str]]:
    """Build two fixed-role messages; caller must use the empty-context guard.

    JSON encoding and angle-bracket escaping keep Qwen chat delimiters out of the
    untrusted payload's literal token stream. This is structural containment,
    not a guarantee that a model will resist natural-language prompt injection.
    """
    checked = validate_input(question, evidence)
    if not checked:
        _fail("input_no_evidence")
    payload = json.dumps(
        {"question": question, "evidence": checked},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).replace("<", "\\u003c").replace(">", "\\u003e")
    return [
        {"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
        {"role": "user", "content": payload},
    ]


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("output_duplicate_key")
        result[key] = value
    return result


def _invalid_constant(_: str) -> None:
    _fail("output_json_constant")


def validate_output(
    raw_text: Any, evidence: Any, *, finish_reason: str
) -> dict[str, Any]:
    """Parse once, reject malformed/truncated output, and fill citation metadata.

    Invalid output raises a safe failure and is never converted to semantic
    abstention. No repair, retries, factuality scoring, or inference occurs here.
    """
    checked = _validate_evidence(evidence)
    if not checked:
        _fail("input_no_evidence")
    if finish_reason != "eos":
        _fail("output_not_eos")
    _text(raw_text, MAX_OUTPUT_CP, "output_text")
    try:
        decoded = json.loads(
            raw_text, object_pairs_hook=_unique_keys, parse_constant=_invalid_constant
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, GroundedAnswerError):
            raise
        raise GroundedAnswerError("output_json") from None
    _exact_keys(decoded, {"status", "reason", "claims"}, "output_schema")
    status, reason, claims = decoded["status"], decoded["reason"], decoded["claims"]
    if type(status) is not str or status not in {"answered", "abstained"}:
        _fail("output_status")
    if type(claims) is not list:
        _fail("output_claims")
    if status == "abstained":
        if type(reason) is not str or reason not in _REASONS or claims:
            _fail("output_abstention")
        return {**decoded, "semantic_support": "not_verified", "model_called": True}
    if reason is not None or not 1 <= len(claims) <= 3:
        _fail("output_answer")
    by_id = {item["evidence_id"]: item for item in checked}
    enriched_claims = []
    for claim in claims:
        _exact_keys(claim, {"text", "citations"}, "output_claim_schema")
        _text(claim["text"], 500, "output_claim_text")
        citations = claim["citations"]
        if type(citations) is not list or not 1 <= len(citations) <= 3:
            _fail("output_citations")
        enriched_citations = []
        for citation in citations:
            _exact_keys(citation, {"evidence_id", "quote"}, "output_citation_schema")
            evidence_id = citation["evidence_id"]
            if type(evidence_id) is not str or evidence_id not in by_id:
                _fail("output_citation_unknown_id")
            quote = _text(citation["quote"], 300, "output_citation_quote")
            source = by_id[evidence_id]
            relative_start = source["text"].find(quote)
            if relative_start < 0:
                _fail("output_citation_not_exact")
            if source["text"].find(quote, relative_start + 1) >= 0:
                _fail("output_citation_ambiguous")
            start = source["start_cp"] + relative_start
            enriched_citations.append({
                "evidence_id": evidence_id,
                "quote": quote,
                "document_id": source["document_id"],
                "revision": source["revision"],
                "source_sha256": source["source_sha256"],
                "start_cp": start,
                "end_cp": start + len(quote),
            })
        enriched_claims.append({"text": claim["text"], "citations": enriched_citations})
    return {
        "status": "answered",
        "reason": None,
        "claims": enriched_claims,
        "semantic_support": "not_verified",
        "model_called": True,
    }
