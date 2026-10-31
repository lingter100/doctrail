"""Generic fake provenance/control-flow tests; no model or saved QA outputs."""
import copy
import json
from types import SimpleNamespace

import pytest

from doctrail import meeting_evidence_plan as p
from doctrail import meeting_structured as m
from doctrail.inference import WorkerError
from doctrail.meeting_contract import AnswerRequest, Context, answer_evidence
from doctrail.meeting_gguf import GGUFResult

QUESTION = "What rule applies to Cedar and what happened to Elm on Monday?"


def contexts():
    texts = ["Cedar requires two approvals before release.", "Elm did not launch on Monday. 😀"]
    return [Context(document_id="doc" + str(i), revision=3, chunk_id="chunk" + str(i),
        title="Synthetic document", page=None, meeting_date=None, start_offset=10,
        end_offset=10 + len(text), text=text) for i, text in enumerate(texts)]


def plan():
    return {"obligations": [
        {"id": 0, "question_spans": ["What rule applies to Cedar"], "entity": "Cedar", "time": "", "fact_kind": "rule"},
        {"id": 1, "question_spans": ["what happened to Elm on Monday"], "entity": "Elm", "time": "Monday", "fact_kind": "event"}]}


def ledger():
    choices = p.evidence_span_choices(contexts())
    return {"rows": [
        {"id": 0, "status": "supported", "entity": "Cedar", "time": "", "fact_kind": "rule",
         "observed_modality": "rule", "evidence": [choices[0]], "text": "Cedar requires two approvals."},
        {"id": 1, "status": "supported", "entity": "Elm", "time": "Monday", "fact_kind": "event",
         "observed_modality": "explicit_negative", "evidence": [choices[1]], "text": "Elm did not launch on Monday."}]}


def test_question_only_plan_and_complete_unchanged_ledger_sources():
    ctx = contexts()
    sources, _ = answer_evidence(ctx)
    planned = p.parse_plan(json.dumps(plan()), QUESTION)
    question_body = json.loads(p.plan_messages(QUESTION)[1]["content"])
    assert question_body == {"question": QUESTION}
    body = json.loads(p.ledger_messages(QUESTION, planned, sources, ctx)[1]["content"])
    assert body["question"] == QUESTION and body["plan"] == planned and body["sources"] == sources
    assert body["passage_provenance"][1]["revision"] == 3
    assert body["evidence_span_choices"] == p.evidence_span_choices(ctx)
    assert body["sources"][1]["passages"][0]["text"] == ctx[1].text


def test_complete_projection_preserves_text_order_and_exact_unicode_spans():
    rows = ledger()
    rows["rows"].reverse()
    original = copy.deepcopy(rows)
    result, checked = p.compile_ledger(json.dumps(rows), plan(), contexts())
    assert result["status"] == "answered"
    assert [c["text"] for c in result["claims"]] == [r["text"] for r in ledger()["rows"]]
    assert [r["id"] for r in checked["rows"]] == [0, 1] and rows == original
    citation = result["claims"][1]["citations"][0]
    assert citation == {"chunk_id": "chunk1", "quote": contexts()[1].text,
                        "start_offset": 10, "end_offset": 10 + len(contexts()[1].text)}


@pytest.mark.parametrize("kind", ["missing_id", "duplicate_id", "entity", "time", "kind", "unexpected"])
def test_malformed_ledger_blocks_all_partial_publication(kind):
    value = ledger()
    if kind == "missing_id":
        value["rows"].pop()
    elif kind == "duplicate_id":
        value["rows"][1]["id"] = 0
    elif kind == "unexpected":
        value["rows"][0]["extra"] = "no"
    else:
        value["rows"][1][{"kind": "fact_kind"}.get(kind, kind)] = "other"
    with pytest.raises(WorkerError, match="invalid_schema"):
        p.compile_ledger(json.dumps(value), plan(), contexts())


@pytest.mark.parametrize("status", ["missing", "ambiguous"])
def test_missing_or_ambiguous_is_whole_answer_abstention_not_negative(status):
    value = ledger()
    value["rows"][1].update(status=status, observed_modality="unknown", evidence=[], text="")
    result, _ = p.compile_ledger(json.dumps(value), plan(), contexts())
    assert result == {"status": "abstained", "reason": "insufficient_evidence", "claims": []}
    value["rows"][1]["observed_modality"] = "explicit_negative"
    with pytest.raises(WorkerError):
        p.compile_ledger(json.dumps(value), plan(), contexts())


def test_procedure_cannot_fill_established_outcome_slot():
    obligation, value = plan(), ledger()
    obligation["obligations"][1]["fact_kind"] = "established_outcome"
    value["rows"][1].update(fact_kind="established_outcome", observed_modality="rule")
    result, _ = p.compile_ledger(json.dumps(value), obligation, contexts())
    assert result["status"] == "abstained" and result["claims"] == []


@pytest.mark.parametrize("kind", ["subrange", "wrong_passage", "bool_offset", "duplicate", "empty"])
def test_only_exact_offered_evidence_choices_are_accepted(kind):
    value = ledger()
    evidence = value["rows"][0]["evidence"]
    if kind == "subrange":
        evidence[0]["end"] -= 1
    elif kind == "wrong_passage":
        evidence[0]["passage_id"] = 99
    elif kind == "bool_offset":
        evidence[0]["start"] = False
    elif kind == "duplicate":
        evidence.append(dict(evidence[0]))
    else:
        evidence.clear()
    with pytest.raises(WorkerError):
        p.compile_ledger(json.dumps(value), plan(), contexts())


@pytest.mark.parametrize("kind", ["id", "span", "scope", "duplicate_span"])
def test_plan_literal_spans_and_scope_are_not_repaired(kind):
    value = plan()
    if kind == "id":
        value["obligations"][1]["id"] = 0
    elif kind == "span":
        value["obligations"][0]["question_spans"] = ["invented"]
    elif kind == "scope":
        value["obligations"][0]["entity"] = "Oak"
    else:
        value["obligations"][0]["question_spans"] *= 2
    with pytest.raises(WorkerError):
        p.parse_plan(json.dumps(value), QUESTION)


@pytest.mark.parametrize("spans", [["Cedar", "Monday"], ["Cedar on Monday", "Cedar"],
                                  ["Monday", "Cedar on Monday"]])
def test_plan_repeated_or_overlapping_literal_spans_preserve_scope(spans):
    question = "Cedar on Monday; Cedar on Tuesday?"
    value = {"obligations": [{"id": 0, "question_spans": spans,
        "entity": "Cedar", "time": "Monday", "fact_kind": "event"},
        {"id": 1, "question_spans": ["Cedar", "Tuesday"],
         "entity": "Cedar", "time": "Tuesday", "fact_kind": "event"}]}
    assert p.parse_plan(json.dumps(value), question) == value


def test_six_obligations_project_directly_without_merging_or_truncating():
    question = ";".join("item" + str(i) for i in range(6))
    value = {"obligations": [{"id": i, "question_spans": ["item" + str(i)],
        "entity": "item" + str(i), "time": "", "fact_kind": "rule"} for i in range(6)]}
    parsed = p.parse_plan(json.dumps(value), question)
    rows = {"rows": [{"id": i, "entity": "item" + str(i), "time": "", "fact_kind": "rule",
        "status": "supported", "observed_modality": "rule", "text": "fact " + str(i),
        "evidence": [p.evidence_span_choices(contexts())[0]]} for i in range(6)]}
    result, _ = p.compile_ledger(json.dumps(rows), parsed, contexts())
    assert [c["text"] for c in result["claims"]] == ["fact " + str(i) for i in range(6)]


class Generator:
    last_effective_config = last_call = None
    def __init__(self):
        self.calls, self.deadlines = [], []
        self.plan, self.ledger = plan(), ledger()
        self.length = False
    def public_metadata(self):
        return {"repo_id": "synthetic", "revision": "fake"}
    def begin_request(self, deadline):
        self.deadlines.append(deadline)
    def end_request(self):
        self.calls.append("end")
    def structured(self, messages, deadline, name, schema, cap):
        self.calls.append((name, messages, cap))
        self.deadlines.append(deadline)
        value = self.plan if name == "qa_obligation_plan" else self.ledger
        return GGUFResult(json.dumps(value), "length" if self.length else "eos", 100, cap, .1, {})


def request():
    return AnswerRequest(schema_version=1, query=QUESTION, contexts=contexts())


def test_two_stages_share_deadline_aggregate768_and_private_capture():
    g, events = Generator(), []
    runtime = m.StructuredMeetingRuntime(g, qa_contract=m.EVIDENCE_PLAN_QA_CONTRACT)
    runtime.set_development_capture(events.append)
    result = runtime.answer(request())
    assert result["status"] == "answered" and len(set(g.deadlines)) == 1
    assert [row[2] for row in g.calls[:-1]] == [192, 576]
    assert sum(row["output_tokens"] for row in result["telemetry"]["calls"]) == 768
    assert json.loads(g.calls[0][1][1]["content"]) == {"question": QUESTION}
    assert [e["kind"] for e in events] == ["accepted_plan", "compiled_ledger"]
    assert QUESTION not in json.dumps(result["telemetry"])
    runtime.set_development_capture(None)
    assert runtime.development_capture is None and g.development_capture is None


@pytest.mark.parametrize("failure", ["malformed_plan", "length", "expired"])
def test_failed_first_stage_does_not_dispatch_ledger(failure, monkeypatch):
    g = Generator()
    runtime = m.StructuredMeetingRuntime(g, qa_contract=m.EVIDENCE_PLAN_QA_CONTRACT)
    if failure == "malformed_plan":
        g.plan = {"obligations": []}
    elif failure == "length":
        g.length = True
    else:
        now = [0.0]
        monkeypatch.setattr(m, "time", SimpleNamespace(monotonic=lambda: now[0]))
        original = g.structured
        def expired(*args):
            result = original(*args)
            now[0] = 121.0
            return result
        g.structured = expired
    with pytest.raises(WorkerError):
        runtime.answer(request())
    assert not runtime.lock.locked()
    assert len(g.calls) == 2 and runtime.last_telemetry["stage"] == "qa_obligation_plan"


def test_span_choices_cover_long_source_without_changing_it():
    text = "A" * 12000 + "B" * 7
    ctx = contexts()[0].model_copy(update={"text": text, "end_offset": 10 + len(text)})
    choices = p.evidence_span_choices([ctx])
    assert choices == [{"passage_id": 0, "start": 0, "end": 12000},
                       {"passage_id": 0, "start": 12000, "end": 12007}]
    assert "".join(ctx.text[x["start"]:x["end"]] for x in choices) == text
