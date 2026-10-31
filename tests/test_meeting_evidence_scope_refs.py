"""Generic exact-reference fixtures, without model calls or held-out questions."""
import copy
import json
from dataclasses import FrozenInstanceError

import pytest

from doctrail import meeting_evidence_scope_refs as p
from doctrail.inference import WorkerError
from doctrail.meeting_contract import Context, answer_evidence

QUESTION = "Cedar reached A on Monday; Cedar reached B on Friday?"


def plan():
    return {"spans": [{"text": "Cedar", "occurrence": 0},
                      {"text": "Monday", "occurrence": 0},
                      {"text": "Friday", "occurrence": 0}],
            "obligations": [
                {"question_refs": [0, 1], "entity_refs": [0], "time_ref": 1, "fact_kind": "event"},
                {"question_refs": [0, 2], "entity_refs": [0], "time_ref": 2, "fact_kind": "event"}]}


def contexts():
    text = "Cedar reached A on Monday. Cedar did not reach B on Friday. 😀"
    return [Context(document_id="doc", revision=4, chunk_id="chunk", title="Synthetic",
        page=None, meeting_date=None, start_offset=7, end_offset=7 + len(text), text=text)]


def ledger():
    evidence = p.v1.evidence_span_choices(contexts())
    return {"rows": [
        {"id": 0, "status": "supported", "observed_modality": "event",
         "evidence": evidence, "text": "Cedar reached A on Monday."},
        {"id": 1, "status": "supported", "observed_modality": "explicit_negative",
         "evidence": copy.deepcopy(evidence), "text": "Cedar did not reach B on Friday."}]}


def test_scope_refs_preserve_whole_question_exact_sources_and_frozen_plan():
    raw = plan()
    frozen = p.parse_plan(json.dumps(raw), QUESTION)
    assert json.loads(p.plan_messages(QUESTION)[1]["content"]) == {"question": QUESTION}
    assert frozen.obligations[1].time_ref == 2
    assert frozen.spans[1].text == QUESTION[frozen.spans[1].start:frozen.spans[1].end]
    with pytest.raises(FrozenInstanceError):
        frozen.question = "changed"
    raw["spans"][0]["text"] = "changed"
    public = frozen.payload()
    public["spans"][0]["text"] = "changed"
    assert frozen.spans[0].text == "Cedar"
    sources, _ = answer_evidence(contexts())
    payload = json.loads(p.ledger_messages(QUESTION, frozen, sources, contexts())[1]["content"])
    assert payload["question"] == payload["plan"]["question"] == QUESTION
    assert payload["sources"] == sources
    assert payload["passage_provenance"][0]["revision"] == 4
    assert payload["plan"]["obligations"][1] == {
        "id": 1, "question_refs": [0, 2], "entity_refs": [0], "time_ref": 2, "fact_kind": "event"}
    with pytest.raises(WorkerError, match="invalid_evidence"):
        p.ledger_messages(QUESTION.lower(), frozen, sources, contexts())


def test_scope_refs_overlapping_occurrences_use_unicode_codepoints_without_normalization():
    question = "😀aaaa é e\u0301"
    value = {"spans": [{"text": "aa", "occurrence": 2}, {"text": "é", "occurrence": 0},
                       {"text": "e\u0301", "occurrence": 0}],
             "obligations": [{"question_refs": [0, 1, 2], "entity_refs": [], "time_ref": None, "fact_kind": "rule"}]}
    frozen = p.parse_plan(json.dumps(value), question)
    assert [(s.start, s.end) for s in frozen.spans] == [(3, 5), (6, 7), (8, 10)]
    assert frozen.spans[1].text != frozen.spans[2].text


@pytest.mark.parametrize("kind", ["unknown_property", "empty_pool", "pool_over_cap", "empty_literal",
    "oversized_literal", "missing_literal", "negative_occurrence", "bool_occurrence", "missing_occurrence",
    "duplicate_identity", "unused_pool", "bool_ref", "duplicate_ref", "invalid_ref", "empty_question_refs",
    "entity_over_cap", "bool_time", "bad_time", "invalid_kind", "extra_scope", "too_many_obligations"])
def test_scope_refs_reject_malformed_or_unproven_plan(kind):
    value = plan()
    row = value["obligations"][0]
    if kind == "unknown_property":
        value["extra"] = None
    elif kind == "empty_pool":
        value["spans"] = []
    elif kind == "pool_over_cap":
        value["spans"] *= 9
    elif kind in {"empty_literal", "oversized_literal", "missing_literal"}:
        value["spans"][0]["text"] = {"empty_literal": " ", "oversized_literal": "x" * 501,
                                     "missing_literal": "cedar"}[kind]
    elif kind in {"negative_occurrence", "bool_occurrence", "missing_occurrence"}:
        value["spans"][0]["occurrence"] = {"negative_occurrence": -1, "bool_occurrence": True,
                                           "missing_occurrence": 2}[kind]
    elif kind == "duplicate_identity":
        value["spans"].append(copy.deepcopy(value["spans"][0]))
    elif kind == "unused_pool":
        value["spans"].append({"text": "Cedar", "occurrence": 1})
    elif kind in {"bool_ref", "duplicate_ref", "invalid_ref", "empty_question_refs"}:
        row["question_refs"] = {"bool_ref": [False], "duplicate_ref": [0, 0],
                                "invalid_ref": [3], "empty_question_refs": []}[kind]
    elif kind == "entity_over_cap":
        row["entity_refs"] = [0] * 5
    elif kind in {"bool_time", "bad_time"}:
        row["time_ref"] = True if kind == "bool_time" else 99
    elif kind == "invalid_kind":
        row["fact_kind"] = "guess"
    elif kind == "extra_scope":
        row["time"] = "regenerated"
    else:
        value["obligations"] *= 4
    with pytest.raises(WorkerError):
        p.parse_plan(json.dumps(value), QUESTION)


def test_scope_refs_id_compilation_reuses_exact_quotes_text_and_order():
    frozen = p.parse_plan(json.dumps(plan()), QUESTION)
    value = ledger()
    value["rows"].reverse()
    before = copy.deepcopy(value)
    result, checked = p.compile_ledger(json.dumps(value), frozen, contexts())
    assert value == before
    assert result["status"] == "answered"
    assert [c["text"] for c in result["claims"]] == [r["text"] for r in ledger()["rows"]]
    assert [r["id"] for r in checked["rows"]] == [0, 1]
    assert result["claims"][1]["citations"][0] == {"chunk_id": "chunk", "quote": contexts()[0].text,
        "start_offset": 7, "end_offset": 7 + len(contexts()[0].text)}
    assert set(checked["rows"][0]) == {"id", "status", "observed_modality", "evidence", "text"}


@pytest.mark.parametrize("status", ["missing", "ambiguous", "incompatible"])
def test_scope_refs_missing_negative_and_kind_compatibility_remain_full_abstention(status):
    frozen = p.parse_plan(json.dumps(plan()), QUESTION)
    value = ledger()
    if status == "incompatible":
        value["rows"][1]["observed_modality"] = "rule"
    else:
        value["rows"][1].update(status=status, observed_modality="unknown", evidence=[], text="")
    result, _ = p.compile_ledger(json.dumps(value), frozen, contexts())
    assert result == {"status": "abstained", "reason": "insufficient_evidence", "claims": []}
    if status != "incompatible":
        value["rows"][1]["observed_modality"] = "explicit_negative"
        with pytest.raises(WorkerError):
            p.compile_ledger(json.dumps(value), frozen, contexts())


@pytest.mark.parametrize("kind", ["missing", "duplicate", "bool_id", "scope_copy", "narrow_span"])
def test_scope_refs_malformed_ledger_is_technical_failure(kind):
    frozen = p.parse_plan(json.dumps(plan()), QUESTION)
    value = ledger()
    if kind == "missing":
        value["rows"].pop()
    elif kind == "duplicate":
        value["rows"][1]["id"] = 0
    elif kind == "bool_id":
        value["rows"][0]["id"] = False
    elif kind == "scope_copy":
        value["rows"][0]["entity"] = "Cedar"
    else:
        value["rows"][0]["evidence"][0]["end"] -= 1
    with pytest.raises(WorkerError):
        p.compile_ledger(json.dumps(value), frozen, contexts())
