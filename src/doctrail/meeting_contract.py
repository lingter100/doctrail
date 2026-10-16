"""Strict request/response guards and source-coordinate reconstruction."""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Annotated, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from doctrail.inference import StrictModel, VersionedRequest, WorkerError

Text = Annotated[str, Field(min_length=1, max_length=24000)]
Id = Annotated[str, Field(min_length=1, max_length=128)]


class AnalyzeRequest(VersionedRequest):
    document_id: Id
    revision: Annotated[int, Field(ge=1)]
    title: Annotated[str, Field(min_length=1, max_length=500)]
    content: Text

    @field_validator("content", "title", "document_id")
    @classmethod
    def valid_text(cls, value):
        if not value.strip():
            raise ValueError("invalid_request")
        value.encode("utf-8")
        return value


class Context(StrictModel):
    document_id: Id
    revision: Annotated[int, Field(ge=1)]
    chunk_id: Id
    title: Annotated[str, Field(min_length=1, max_length=500)]
    meeting_date: str | None
    page: Annotated[int, Field(ge=1)] | None
    start_offset: Annotated[int, Field(ge=0)]
    end_offset: Annotated[int, Field(ge=1)]
    text: Text

    @model_validator(mode="after")
    def exact_range(self):
        self.text.encode("utf-8")
        if self.end_offset - self.start_offset != len(self.text) or not self.text.strip():
            raise ValueError("invalid_request")
        return self


class AnswerRequest(VersionedRequest):
    query: Annotated[str, Field(min_length=1, max_length=500)]
    contexts: Annotated[list[Context], Field(max_length=10)]

    @model_validator(mode="after")
    def unique_contexts(self):
        self.query.encode("utf-8")
        if not self.query.strip() or len({c.chunk_id for c in self.contexts}) != len(self.contexts):
            raise ValueError("invalid_request")
        return self


class Selection(StrictModel):
    line: Annotated[int, Field(ge=0)]
    type: Literal["topic", "proposal", "decision", "unresolved", "action"]
    assignee: str | None = None
    due_date: str | None = None
    priority: Literal["low", "medium", "high"] | None = None


class Metadata(StrictModel):
    line: Annotated[int, Field(ge=0)]
    field: Literal["meeting_title", "meeting_date", "participants", "purpose"]
    value: Annotated[str, Field(min_length=1, max_length=500)]


class Extraction(StrictModel):
    summary_lines: Annotated[list[int], Field(max_length=4)]
    items: Annotated[list[list[int | str]], Field(max_length=150)]
    metadata: Annotated[list[list[int | str]], Field(max_length=30)]


def selected_fields(kind, quote):
    """Conservative explicit grammar, after actual model selection/classification."""
    assignee = due_date = priority = None
    if kind == "action":
        # Named subject plus explicit future/assignment grammar, not a speaker label.
        match = re.search(r"(?:^|[:：]\s*)([가-힣]{2,5}?)(?:이|가|은|는)\s+"
                          r"(?:\d{4}-\d{2}-\d{2}까지\s+)?", quote)
        english = re.search(r"(?:^|[:：]\s*)([A-Z][a-z]+(?: [A-Z][a-z]+){0,2}) will\s+", quote)
        if match and match.group(1) not in {"담당자", "작업자", "기한", "마감일", "일정"}:
            assignee = match.group(1)
        elif english:
            assignee = english.group(1)
        dates = re.findall(r"(\d{4}-\d{2}-\d{2})\s*까지", quote)
        dates.extend(re.findall(
            r"(?:\bby\s+|\bdue(?: date)?\s*[:：]?\s*|\bdeadline\s*[:：]?\s*)"
            r"(\d{4}-\d{2}-\d{2})", quote, re.IGNORECASE))
        if len(set(dates)) == 1:
            try:
                date.fromisoformat(dates[0])
                due_date = dates[0]
            except ValueError:
                pass
        priorities = {"low": "low", "medium": "medium", "high": "high",
                      "낮음": "low", "보통": "medium", "높음": "high"}
        found = re.search(r"(?:priority|우선순위)\s*[:：]\s*(low|medium|high|낮음|보통|높음)",
                          quote, re.IGNORECASE)
        if found:
            priority = priorities[found.group(1).lower()]
    return assignee, due_date, priority


def metadata_values(field, quote):
    """Only literal header/table values from the model-selected source unit."""
    if field == "meeting_date":
        values = list(dict.fromkeys(re.findall(r"\d{4}-\d{2}-\d{2}", quote)))
        if len(values) != 1:
            return []
        try:
            date.fromisoformat(values[0])
        except ValueError:
            return []
        return values
    if field == "participants":
        found = re.match(r"(?:\*\*)?(?:참석자|participants|attendees)(?:\*\*)?\s*[:：]\s*(.+)",
                         quote, re.IGNORECASE)
        if found:
            return [value.strip() for value in re.split(r"[,、]", found.group(1)) if value.strip()]
        if quote.startswith("|"):
            value = quote.split("|")[1].strip()
            if value and value.lower() not in {"name", "attendee"} and set(value) != {"-"}:
                return [value]
        return []
    labels = {"meeting_title": r"(?:회의\s*제목|제목|title)",
              "purpose": r"(?:회의\s*목적|목적|purpose)"}
    found = re.match(r"(?:\*\*)?" + labels[field] + r"(?:\*\*)?\s*[:：]\s*(.+)", quote,
                     re.IGNORECASE)
    if found:
        return [found.group(1).strip()]
    if field == "purpose":
        section = re.match(r"^#{1,6}\s+(?:Purpose|목적|회의\s*목적)\s*\n\s*(.+)",
                           quote, re.IGNORECASE | re.DOTALL)
        if section:
            return [section.group(1).strip()]
    if field == "meeting_title" and re.match(r"^#\s+", quote):
        return [re.sub(r"^#\s+", "", quote)]
    return []


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_key")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
    except (TypeError, ValueError):
        raise WorkerError("generation_invalid_json", 502) from None


def span(source, start, end):
    return {"quote": source[start:end], "start_offset": start, "end_offset": end}


def lines(source):
    """Contiguous nonblank source units; whitespace remains in source coordinates."""
    result = []
    for match in re.finditer(r"[^\n]+", source):
        text = match.group()
        left = len(text) - len(text.lstrip())
        right = len(text.rstrip())
        if right > left:
            result.append(span(source, match.start() + left, match.start() + right))
    return result


def meeting_units(source):
    """Bind an explicit purpose heading to its next paragraph with one exact span."""
    units = lines(source)
    result, index = [], 0
    while index < len(units):
        current = units[index]
        if (re.fullmatch(r"#{1,6}\s+(?:Purpose|목적|회의\s*목적)\s*", current["quote"],
                         re.IGNORECASE)
                and index + 1 < len(units) and not units[index + 1]["quote"].startswith("#")):
            result.append(span(source, current["start_offset"], units[index + 1]["end_offset"]))
            index += 2
        else:
            result.append(current)
            index += 1
    return result


def answer_evidence(contexts):
    """One finite ID per full received chunk; no hidden filtering or text changes."""
    if len(contexts) > 10:
        raise WorkerError("generation_input_limit", 422)
    sources, mapping = [], {}
    by_document = {}
    for identity, context in enumerate(contexts):
        mapping[identity] = {"chunk_id": context.chunk_id, "quote": context.text,
                            "start_offset": context.start_offset, "end_offset": context.end_offset}
        document = (context.document_id, context.revision)
        if document not in by_document:
            by_document[document] = {"title": context.title, "meeting_date": context.meeting_date,
                                    "passages": []}
            sources.append(by_document[document])
        by_document[document]["passages"].append({"id": identity, "text": context.text})
    return sources, mapping


def grounded_answer_refs(raw, mapping):
    """Resolve exact supplied integer references; never repair model quotes or IDs."""
    data = strict_json(raw)
    if not isinstance(data, dict) or set(data) != {"status", "claims"}:
        raise WorkerError("generation_invalid_schema", 502)
    if data["status"] == "abstained" and data["claims"] == []:
        return {"status": "abstained", "reason": "insufficient_evidence", "claims": []}
    if data["status"] != "answered" or not isinstance(data["claims"], list) or not (
        1 <= len(data["claims"]) <= 6
    ):
        raise WorkerError("generation_invalid_schema", 502)
    claims = []
    for claim in data["claims"]:
        if not isinstance(claim, dict) or set(claim) != {"text", "evidence"} or not (
            isinstance(claim["text"], str) and 0 < len(claim["text"].strip()) <= 2000
            and isinstance(claim["evidence"], list) and 1 <= len(claim["evidence"]) <= 4
        ):
            raise WorkerError("generation_invalid_schema", 502)
        references = claim["evidence"]
        if any(type(identity) is not int or identity not in mapping for identity in references):
            raise WorkerError("generation_invalid_evidence", 502)
        if len(set(references)) != len(references):
            raise WorkerError("generation_invalid_evidence", 502)
        claims.append({"text": claim["text"],
                       "citations": [dict(mapping[identity]) for identity in references]})
    return {"status": "answered", "reason": None, "claims": claims}


def extraction_analysis(raw, units):
    try:
        extracted = Extraction.model_validate(strict_json(raw))
    except WorkerError:
        raise
    except ValidationError:
        raise WorkerError("generation_invalid_schema", 502) from None

    def unit(index):
        if type(index) is not int or not 0 <= index < len(units):
            raise WorkerError("generation_invalid_evidence", 502)
        return units[index]

    evidence = [unit(index) for index in dict.fromkeys(extracted.summary_lines)]
    result = {"meeting_title": None, "meeting_date": None, "participants": [], "purpose": None,
              "summary": "\n".join(row["quote"] for row in evidence),
              "summary_evidence": evidence, "items": [], "metadata_evidence": []}
    seen_items = set()
    for raw_item in extracted.items:
        if len(raw_item) != 2:
            raise WorkerError("generation_invalid_schema", 502)
        try:
            selected = Selection(line=raw_item[0], type=raw_item[1])
        except ValidationError:
            raise WorkerError("generation_invalid_schema", 502) from None
        source = unit(selected.line)
        quote = source["quote"]
        selected.assignee, selected.due_date, selected.priority = selected_fields(selected.type, quote)
        if (selected.line, selected.type) in seen_items:
            raise WorkerError("generation_duplicate_item", 502)
        seen_items.add((selected.line, selected.type))
        if selected.type != "action" and any(
            value is not None for value in (selected.assignee, selected.due_date, selected.priority)
        ):
            raise WorkerError("generation_unsupported_field", 502)
        if selected.assignee is not None and (not selected.assignee or selected.assignee not in quote):
            raise WorkerError("generation_unsupported_field", 502)
        if selected.due_date is not None:
            try:
                date.fromisoformat(selected.due_date)
            except ValueError:
                raise WorkerError("generation_unsupported_field", 502) from None
            if selected.due_date not in quote:
                raise WorkerError("generation_unsupported_field", 502)
        # Selection/classification is model-authored, not semantic certification.
        result["items"].append({**source, "id": "", "type": selected.type, "text": quote,
            "assignee": selected.assignee, "due_date": selected.due_date,
            "priority": selected.priority, "status": "needs_confirmation"})
    for raw_metadata in extracted.metadata:
        if len(raw_metadata) != 2:
            raise WorkerError("generation_invalid_schema", 502)
        index, field = raw_metadata
        if field not in {"meeting_title", "meeting_date", "participants", "purpose"}:
            raise WorkerError("generation_invalid_schema", 502)
        source = unit(index)
        for value in metadata_values(field, source["quote"]):
            if field == "participants":
                if value not in result["participants"]:
                    result["participants"].append(value)
            elif result[field] not in (None, value):
                raise WorkerError("generation_conflicting_metadata", 502)
            else:
                result[field] = value
            result["metadata_evidence"].append({**source, "field": field})
    return result


def grounded_answer(raw, contexts):
    data = strict_json(raw)
    if not isinstance(data, dict) or set(data) != {"status", "claims"}:
        raise WorkerError("generation_invalid_schema", 502)
    if data["status"] == "abstained" and data["claims"] == []:
        return {"status": "abstained", "reason": "insufficient_evidence", "claims": []}
    if data["status"] != "answered" or not isinstance(data["claims"], list) or not (
        1 <= len(data["claims"]) <= 6
    ):
        raise WorkerError("generation_invalid_schema", 502)
    by_id = {context.chunk_id: context for context in contexts}
    claims = []
    for claim in data["claims"]:
        if not isinstance(claim, dict) or set(claim) != {"text", "citations"} or not (
            isinstance(claim["text"], str) and 0 < len(claim["text"].strip()) <= 2000
            and isinstance(claim["citations"], list) and 1 <= len(claim["citations"]) <= 4
        ):
            raise WorkerError("generation_invalid_schema", 502)
        citations = []
        for citation in claim["citations"]:
            if not isinstance(citation, dict) or set(citation) != {"chunk_id", "quote"}:
                raise WorkerError("generation_invalid_schema", 502)
            chunk_id, quote = citation["chunk_id"], citation["quote"]
            if not isinstance(chunk_id, str) or not isinstance(quote, str) or not quote.strip():
                raise WorkerError("generation_invalid_evidence", 502)
            context = by_id.get(chunk_id)
            if context is None or context.text.count(quote) != 1:
                raise WorkerError("generation_invalid_evidence", 502)
            start = context.start_offset + context.text.index(quote)
            citations.append({"chunk_id": chunk_id, "quote": quote, "start_offset": start,
                              "end_offset": start + len(quote)})
        claims.append({"text": claim["text"], "citations": citations})
    return {"status": "answered", "reason": None, "claims": claims}
