"""C2-P0 paragraph/structural evidence units, not semantic completeness proof.

Deterministic, conservative Markdown subset (not a Markdown renderer):
* Python splitlines(keepends=True) retains every code point and original newline.
  Blank lines delimit ordinary paragraphs; physical nonblank lines stay together.
* Outside a structure, precedence is fenced code, ATX heading, pipe table, list,
  indented code, ordinary paragraph. ATX headings allow 0-3 leading spaces.
  A paragraph ending with a Setext underline is kept together as a heading.
* Backtick/tilde fences require >=3 identical markers and 0-3 leading spaces.
  Closing fences use the same marker, >= opening length, and whitespace only
  afterwards. Blank lines and apparent structures inside a fence remain literal.
  An unclosed fence consumes the rest of its context, never another context.
* Tables require a pipe-bearing header followed by dash/colon delimiter cells;
  contiguous pipe-bearing rows remain together. Escaped pipes are not interpreted.
* Consecutive bullet/numbered list items, nested items, indented continuations,
  and nonblank lazy prose continuations remain one block. Blank gaps stay inside
  only when followed by another item or a more-indented continuation. Fences
  inside list items preserve their blank lines. A top-level structural opener
  ends a list. This may group multiple list styles conservatively.
* Indented code (>=4 spaces or a tab, unless recognized as a list) starts at a
  block boundary or immediately after a colon introduction. Other indentation
  never interrupts a paragraph. Code retains blank gaps only when followed by
  another indented code line.
* A paragraph ending in a literal ':' or fullwidth colon joins the immediately
  following list/table/code block, including intervening whitespace. Headings
  are never introductions. No noncontiguous quote concatenation is performed.
* Remaining whitespace runs are units too. Every unit, including whitespace,
  must fit 1024 code points. Oversize is refused, never split or summarized.

Chunk edges cannot establish sentence/paragraph completeness. Boundary flags
only identify contact with a supplied context edge, not semantic completeness.
No neighboring context is fetched or merged. Existing ACL/revision checks stay
in Java; this experimental adapter does not change the service default.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from contextlib import contextmanager

from pydantic import ValidationError

from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_answer_spans import (
    ANSWER_PROMPT,
    HANGUL,
    ExactSpan,
    SourceSnapshot,
    SpanAnswerGenerator,
    SpanCatalog,
    SpanResponse,
    answer_messages_spans,
    response_language,
    span_answer_grammar,
)
from doctrail.meeting_contract import AnswerRequest, Context, strict_json
from doctrail.meeting_worker import MeetingRuntime, safe_payload

ANSWER_POLICY = "meeting-paragraph-block-answer-c2-p0-v1"
DECODER_POLICY = "meeting-block-id-grammar-c2-p0-v1"
MAX_BLOCK_CODEPOINTS = 1024
MAX_SPANS = 160
MAX_CHUNKS = 10
MAX_INPUT_TOKENS = 4096
MAX_NEW_TOKENS = 384
DEADLINE_SECONDS = 90
BLOCK_PROMPT_SUFFIX = """Evidence IDs here identify preserved paragraphs or structural blocks.
touches_context_start/end marks contact with a supplied context boundary; text may be
incomplete there. Neither an internal block boundary nor a larger block proves semantic
completeness. Do not invent text outside the supplied context."""

_HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+|$)")
_LIST = re.compile(r"^([ \t]*)(?:[-+*]|[0-9]{1,9}[.)])(?:[ \t]+|$)")
_SETEXT = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def _body(line):
    return line.rstrip("\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029")


def _indent(line):
    return len(line[:len(line) - len(line.lstrip(" \t"))].expandtabs(4))


def _fence(line):
    match = _FENCE.match(_body(line))
    if match and not (match[1][0] == "`" and "`" in match[2]):
        return match[1][0], len(match[1])
    return None


def _closes(line, fence, nested=False):
    body = _body(line)
    if nested:
        body = body.lstrip(" \t")
    marker, count = fence
    return re.fullmatch(r" {0,3}" + re.escape(marker) + "{" + str(count) + r",}[ \t]*", body)


def _table(lines, index):
    if index + 1 >= len(lines) or "|" not in lines[index] or _indent(lines[index]) > 3:
        return False
    separator = _body(lines[index + 1]).strip()
    if "|" not in separator:
        return False
    cells = separator.strip("|").split("|")
    return bool(cells) and all(re.fullmatch(r"[ \t]*:?-{3,}:?[ \t]*", cell) for cell in cells)


def _kind(lines, index):
    line = lines[index]
    if not line.strip():
        return "whitespace"
    if _fence(line):
        return "code"
    if _HEADING.match(_body(line)):
        return "heading"
    if _table(lines, index):
        return "table"
    if _LIST.match(_body(line)):
        return "list"
    if _indent(line) >= 4:
        return "indented_code"
    return "paragraph"


def _list_end(lines, start):
    base_indent, index, fence = _indent(lines[start]), start, None
    while index < len(lines):
        line = lines[index]
        if fence:
            if _closes(line, fence, nested=True):
                fence = None
            index += 1
            continue
        if not line.strip():
            next_index = index
            while next_index < len(lines) and not lines[next_index].strip():
                next_index += 1
            if next_index == len(lines) or not (
                    _LIST.match(_body(lines[next_index])) or _indent(lines[next_index]) > base_indent):
                break
            index = next_index
            continue
        item = _LIST.match(_body(line))
        if item:
            fence = _fence(line[item.end():])
        elif _indent(line) > base_indent:
            fence = _fence(line.lstrip(" \t"))
        elif index != start and _kind(lines, index) in {"heading", "table", "code"}:
            break
        index += 1
    return index


def block_units(text):
    """Lossless lexical units; boundaries use only source syntax, never a query."""
    lines = text.splitlines(keepends=True)
    blocks, index = [], 0
    while index < len(lines):
        start, kind = index, _kind(lines, index)
        index += 1
        if kind == "whitespace":
            while index < len(lines) and not lines[index].strip():
                index += 1
        elif kind == "code":
            fence = _fence(lines[start])
            while index < len(lines):
                closes = _closes(lines[index], fence)
                index += 1
                if closes:
                    break
        elif kind == "table":
            index += 1  # the delimiter row belongs to this table
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                index += 1
        elif kind == "list":
            index = _list_end(lines, start)
        elif kind == "indented_code":
            while index < len(lines):
                if lines[index].strip():
                    if _indent(lines[index]) < 4:
                        break
                    index += 1
                else:
                    next_index = index
                    while next_index < len(lines) and not lines[next_index].strip():
                        next_index += 1
                    if next_index == len(lines) or _indent(lines[next_index]) < 4:
                        break
                    index = next_index
            kind = "code"
        elif kind == "paragraph":
            while index < len(lines) and _kind(lines, index) in {"paragraph", "indented_code"}:
                if (_kind(lines, index) == "indented_code"
                        and "".join(lines[start:index]).rstrip().endswith((":", "："))):
                    break
                if _SETEXT.fullmatch(_body(lines[index])):
                    kind = "heading"
                    index += 1
                    break
                index += 1
        blocks.append((kind, "".join(lines[start:index])))

    merged, index = [], 0
    while index < len(blocks):
        kind, quote = blocks[index]
        following = index + 1
        if kind == "paragraph" and quote.rstrip().endswith((":", "：")):
            if following < len(blocks) and blocks[following][0] == "whitespace":
                following += 1
            if following < len(blocks) and blocks[following][0] in {"list", "table", "code"}:
                quote = "".join(row[1] for row in blocks[index:following + 1])
                index = following
        if len(quote) > MAX_BLOCK_CODEPOINTS:
            raise WorkerError("generation_block_limit", 422)
        merged.append(quote)
        index += 1
    return tuple(merged)


def build_block_catalog(contexts):
    if not 1 <= len(contexts) <= MAX_CHUNKS:
        raise WorkerError("generation_invalid_evidence", 502)
    sources, spans, seen = [], [], set()
    try:
        for context in contexts:
            source = Context.model_validate(context.model_dump())
            if source.chunk_id in seen:
                raise ValueError("duplicate_chunk")
            seen.add(source.chunk_id)
            sources.append(SourceSnapshot(**source.model_dump()))
            offset = source.start_offset
            for quote in block_units(source.text):
                spans.append(ExactSpan(len(spans), source.document_id, source.revision,
                    source.chunk_id, quote, offset, offset + len(quote)))
                offset += len(quote)
                if len(spans) > MAX_SPANS:
                    raise WorkerError("generation_span_limit", 422)
            if offset != source.end_offset:
                raise ValueError("invalid_offsets")
    except (ValidationError, ValueError, TypeError, AttributeError):
        raise WorkerError("generation_invalid_evidence", 502) from None
    return SpanCatalog(tuple(sources), tuple(spans))


def validate_block_catalog(catalog, contexts):
    if (type(catalog) is not SpanCatalog or type(catalog.sources) is not tuple
            or type(catalog.spans) is not tuple
            or any(type(source) is not SourceSnapshot or any(type(getattr(source, field)) is not int
                for field in ("revision", "start_offset", "end_offset"))
                or (source.page is not None and type(source.page) is not int)
                for source in catalog.sources)
            or any(type(span) is not ExactSpan or any(type(getattr(span, field)) is not int
                for field in ("span_id", "revision", "start_offset", "end_offset"))
                for span in catalog.spans)
            or catalog != build_block_catalog(contexts)):
        raise WorkerError("generation_invalid_evidence", 502)


def answer_messages_blocks(query, catalog):
    messages = answer_messages_spans(query, catalog)
    messages[0]["content"] = ANSWER_PROMPT + "\n\n" + BLOCK_PROMPT_SUFFIX
    payload = json.loads(messages[1]["content"])
    for source, row in zip(catalog.sources, payload["sources"], strict=True):
        for block in row["spans"]:
            span = catalog.spans[block["id"]]
            block["touches_context_start"] = span.start_offset == source.start_offset
            block["touches_context_end"] = span.end_offset == source.end_offset
    messages[1]["content"] = safe_payload(payload)
    return messages


def grounded_answer_blocks(raw, catalog, contexts, language):
    """C0 response contract with block-catalog validation and exact copying only."""
    validate_block_catalog(catalog, contexts)
    if language not in {"ko", "en"}:
        raise WorkerError("generation_invalid_schema", 502)
    try:
        response = SpanResponse.model_validate(strict_json(raw))
    except ValidationError:
        raise WorkerError("generation_invalid_schema", 502) from None
    if response.status == "abstained":
        if response.claims:
            raise WorkerError("generation_invalid_schema", 502)
        return {"status": "abstained", "reason": "insufficient_evidence", "claims": []}
    if not response.claims:
        raise WorkerError("generation_invalid_schema", 502)
    mapping, claims = {span.span_id: span for span in catalog.spans}, []
    for claim in response.claims:
        if not (HANGUL.search(claim.text) if language == "ko" else re.search(r"[A-Za-z]", claim.text)):
            raise WorkerError("generation_language_mismatch", 502)
        if len(set(claim.evidence_ids)) != len(claim.evidence_ids):
            raise WorkerError("generation_invalid_evidence", 502)
        citations = []
        for identity in claim.evidence_ids:
            span = mapping.get(identity)
            if span is None or not span.quote.strip():
                raise WorkerError("generation_invalid_evidence", 502)
            citations.append({"chunk_id": span.chunk_id, "quote": span.quote,
                              "start_offset": span.start_offset, "end_offset": span.end_offset})
        claims.append({"text": claim.text, "citations": citations})
    return {"status": "answered", "reason": None, "claims": claims}


def _unique_codepoints(intervals):
    by_document, total = {}, 0
    for document, revision, start, end in intervals:
        by_document.setdefault((document, revision), []).append((start, end))
    for ranges in by_document.values():
        right = -1
        for start, end in sorted(ranges):
            total += max(0, end - max(start, right))
            right = max(right, end)
    return total


def citation_metrics(result, catalog):
    """Counts only; unique lengths union document/revision coordinate intervals.

    Source occurrence length includes received overlapping chunks; source unique
    length does not. Citation occurrence length includes repetitions across claims.
    Neither length nor exact reconstruction certifies relevance or entailment.
    """
    sources = {source.chunk_id: source for source in catalog.sources}
    intervals, claim_lengths = [], []
    for claim in result["claims"]:
        length = 0
        for citation in claim["citations"]:
            source = sources[citation["chunk_id"]]
            start, end = citation["start_offset"], citation["end_offset"]
            intervals.append((source.document_id, source.revision, start, end))
            length += end - start
        claim_lengths.append(length)
    total, unique = sum(claim_lengths), _unique_codepoints(intervals)
    return {"source_codepoints": sum(len(s.text) for s in catalog.sources),
        "source_unique_codepoints": _unique_codepoints((s.document_id, s.revision,
            s.start_offset, s.end_offset) for s in catalog.sources),
        "unit_codepoints": [len(span.quote) for span in catalog.spans],
        "claim_citation_codepoints": claim_lengths, "citation_codepoints": total,
        "citation_unique_codepoints": unique, "citation_duplicate_codepoints": total - unique,
        "unique_length_basis": "document_revision_coordinate_union"}


class BlockAnswerGenerator(SpanAnswerGenerator):
    def __init__(self, base):
        super().__init__(base)
        self._called = False

    @contextmanager
    def answer_catalog(self, catalog):
        if self._catalog is not None:
            raise WorkerError("model_busy", 503)
        if type(catalog) is not SpanCatalog:
            raise WorkerError("generation_invalid_evidence", 502)
        try:
            contexts = [Context(**vars(source)) for source in catalog.sources]
        except (ValidationError, TypeError):
            raise WorkerError("generation_invalid_evidence", 502) from None
        validate_block_catalog(catalog, contexts)
        self._catalog = catalog
        try:
            yield
        finally:
            self._catalog = None

    def begin_request(self, deadline):
        self._called = False
        super().begin_request(deadline)

    def end_request(self):
        self._called = False
        super().end_request()

    def public_metadata(self):
        metadata = self.base.public_metadata()
        return {**metadata, "runtime": {**metadata.get("runtime", {}),
            "max_input_tokens": MAX_INPUT_TOKENS, "max_new_tokens": MAX_NEW_TOKENS,
            "deadline_seconds": DEADLINE_SECONDS}, "answer_decoder": {
            "policy": DECODER_POLICY, "answer_policy": ANSWER_POLICY,
            "grammar_sha256": self._last_grammar_sha256,
            "grammar_scope": "last_request_valid_block_ids",
            "guarantee_scope": "structure_and_catalog_membership_only"}}

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


class BlockAnswerMeetingRuntime(MeetingRuntime):
    """One answer call with a 90s deadline shared by preparation and native work.

    The native adapter must honor its passed deadline. The final post-cleanup
    check rejects overruns; it cannot forcibly cancel a noncooperative backend.
    Extraction remains inherited and retains its existing separate contract.
    """

    def __init__(self, generator):
        if not isinstance(generator, BlockAnswerGenerator):
            raise TypeError("block_answer_generator_required")
        super().__init__(generator)

    def health(self):
        return {**super().health(), "answer_policy": ANSWER_POLICY,
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
        telemetry = {"answer_policy": ANSWER_POLICY, "completion_attempts": 0, "calls": [],
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
