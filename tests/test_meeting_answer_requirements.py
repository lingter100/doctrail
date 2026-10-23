"""Fresh synthetic structure tests; no evaluation examples or model execution."""
import copy
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from doctrail import meeting_answer_requirements as c3
from doctrail.inference import WorkerError
from doctrail.meeting_answer_blocks import build_block_catalog
from doctrail.meeting_contract import AnswerRequest


def request():
    text = "Synthetic copper badge.\r\nKeep 😀 and e\u0301.\r\n\r\n| Key | Value |\n| --- | --- |\n| Z | 4 |\n"
    return AnswerRequest.model_validate({"schema_version": 1, "query": "Describe this fixture.",
        "contexts": [{"document_id": "fixture", "revision": 3, "chunk_id": "fixture-3-0",
            "title": "Synthetic only", "meeting_date": None, "page": 2,
            "start_offset": 17, "end_offset": 17 + len(text), "text": text}]})


def plan_payload():
    return {"requirements": [
        {"requirement_id": 1, "need": "Describe badge and value", "status": "supported",
         "evidence_ids": [2, 0]},
        {"requirement_id": 2, "need": "Describe value", "status": "supported",
         "evidence_ids": [2]}]}


def answer_payload():
    return {"status": "answered", "claims": [
        {"requirement_id": 1, "text": "The synthetic badge is copper."},
        {"requirement_id": 2, "text": "The value is four."}]}


def prepared():
    req = request()
    catalog = build_block_catalog(req.contexts)
    plan = c3.parse_requirement_plan(json.dumps(plan_payload()), catalog, "en")
    return req, catalog, plan


def test_full_context_plan_and_selected_exact_units_realization():
    req, catalog, plan = prepared()
    first = json.loads(c3.requirement_messages(req.query, catalog, "ko")[1]["content"])
    assert first["response_language"] == "ko"
    assert "".join(x["text"] for x in first["sources"][0]["spans"]) == req.contexts[0].text
    assert len(first["sources"][0]["spans"]) == 3  # preserves whitespace too
    messages = c3.realization_messages(req.query, catalog, plan, "en")
    second = json.loads(messages[1]["content"])
    assert second["requirements"] == plan_payload()["requirements"]
    assert [x["id"] for x in second["evidence"]] == [0, 2]
    for unit in second["evidence"]:
        source = req.contexts[0]
        assert unit["text"] == source.text[unit["start_offset"] - source.start_offset:
                                          unit["end_offset"] - source.start_offset]
        assert unit["document_id"] == source.document_id and unit["revision"] == 3
    assert "| Key | Value |" in second["evidence"][1]["text"]
    result = c3.grounded_requirement_answer(json.dumps(answer_payload()), catalog,
                                            req.contexts, plan, "en")
    assert [c["quote"] for c in result["claims"][0]["citations"]] == [
        catalog.spans[2].quote, catalog.spans[0].quote]
    assert result["claims"][1]["citations"][0]["quote"] == catalog.spans[2].quote


@pytest.mark.parametrize("change,code", [
    (lambda p: p.update(extra=1), "schema"),
    (lambda p: p.update(requirements=[]), "schema"),
    (lambda p: p["requirements"].extend(copy.deepcopy(p["requirements"]) * 3), "schema"),
    (lambda p: p["requirements"][0].update(requirement_id=True), "schema"),
    (lambda p: p["requirements"][0].update(requirement_id="1"), "schema"),
    (lambda p: p["requirements"][1].update(requirement_id=1), "schema"),
    (lambda p: p["requirements"][1].update(requirement_id=3), "schema"),
    (lambda p: p["requirements"].reverse(), "schema"),
    (lambda p: p["requirements"][0].update(need=" "), "schema"),
    (lambda p: p["requirements"][0].update(need="x" * 501), "schema"),
    (lambda p: p["requirements"][0].update(status="maybe"), "schema"),
    (lambda p: p["requirements"][0].update(evidence_ids=[]), "evidence"),
    (lambda p: p["requirements"][0].update(evidence_ids=[0, 0]), "evidence"),
    (lambda p: p["requirements"][0].update(evidence_ids=[159]), "evidence"),
    (lambda p: p["requirements"][0].update(evidence_ids=[1]), "evidence"),
    (lambda p: p["requirements"][0].update(evidence_ids=[False]), "schema"),
    (lambda p: p["requirements"][0].update(evidence_ids=[0] * 5), "schema"),
    (lambda p: p["requirements"][0].update(text="extra answer"), "schema"),
])
def test_bad_plans_are_rejected(change, code):
    payload = plan_payload()
    change(payload)
    with pytest.raises(WorkerError, match="generation_invalid_" + code):
        c3.parse_requirement_plan(json.dumps(payload), build_block_catalog(request().contexts), "en")


@pytest.mark.parametrize("status", ["missing", "uncertain"])
def test_unsupported_plan_cannot_be_realized(status):
    req = request()
    catalog = build_block_catalog(req.contexts)
    payload = plan_payload()
    payload["requirements"][1].update(status=status, evidence_ids=[])
    plan = c3.parse_requirement_plan(json.dumps(payload), catalog, "en")
    assert not plan.supported
    for action in [lambda: c3.realization_messages(req.query, catalog, plan, "en"),
                   lambda: c3.realization_grammar(plan, catalog, "en"),
                   lambda: c3.grounded_requirement_answer(json.dumps(answer_payload()), catalog,
                                                          req.contexts, plan, "en")]:
        with pytest.raises(WorkerError, match="generation_unsupported_plan"):
            action()


@pytest.mark.parametrize("change", [
    lambda p: p["claims"].pop(),
    lambda p: p["claims"].append({"requirement_id": 3, "text": "Extra fact."}),
    lambda p: p["claims"][1].update(requirement_id=1),
    lambda p: p["claims"][1].update(requirement_id=3),
    lambda p: p["claims"].reverse(),
    lambda p: p["claims"][0].update(evidence_ids=[0]),
    lambda p: p["claims"][0].update(citations=[]),
    lambda p: p["claims"][0].update(text=" "),
    lambda p: p["claims"][0].update(text="x" * 2001),
    lambda p: p.update(status="abstained"),
    lambda p: p.update(claims=[]),
    lambda p: p.update(reason="insufficient_evidence"),
])
def test_bad_slots_fail_atomically(change):
    req, catalog, plan = prepared()
    payload = answer_payload()
    change(payload)
    with pytest.raises(WorkerError, match="generation_invalid_schema"):
        c3.grounded_requirement_answer(json.dumps(payload), catalog, req.contexts, plan, "en")


@pytest.mark.parametrize("raw", ['{"requirements":[],"requirements":[]}', '{bad', 'NaN'])
def test_json_is_strict(raw):
    with pytest.raises(WorkerError, match="generation_invalid_json"):
        c3.parse_requirement_plan(raw, build_block_catalog(request().contexts), "en")


def test_plan_snapshot_and_catalog_tampering():
    req, catalog, plan = prepared()
    payload = plan.payload()
    payload["requirements"][0]["evidence_ids"].clear()
    assert plan.requirements[0].evidence_ids == (2, 0)
    with pytest.raises(FrozenInstanceError):
        plan.requirements[0].need = "tampered"
    altered = replace(catalog, spans=(replace(catalog.spans[0], quote="x"), *catalog.spans[1:]))
    with pytest.raises(WorkerError, match="generation_invalid_evidence"):
        c3.realization_messages(req.query, altered, plan, "en")
    req.contexts[0].revision += 1
    with pytest.raises(WorkerError, match="generation_invalid_evidence"):
        c3.grounded_requirement_answer(json.dumps(answer_payload()), catalog, req.contexts, plan, "en")


def test_language_guard_and_whole_abstention():
    req, catalog, plan = prepared()
    payload = answer_payload()
    payload["claims"][1]["text"] = "한국어 문장입니다."
    with pytest.raises(WorkerError, match="generation_language_mismatch"):
        c3.grounded_requirement_answer(json.dumps(payload), catalog, req.contexts, plan, "en")
    ko = plan_payload()
    for row in ko["requirements"]:
        row["need"] = "필요 사항"
    korean_plan = c3.parse_requirement_plan(json.dumps(ko), catalog, "ko")
    for row in payload["claims"]:
        row["text"] = "자료에서 확인된 문장입니다."
    assert c3.grounded_requirement_answer(json.dumps(payload), catalog, req.contexts,
                                          korean_plan, "ko")["status"] == "answered"
    assert c3.grounded_requirement_answer('{"status":"abstained","claims":[]}', catalog,
                                          req.contexts, plan, "en") == c3.abstained_answer()
    assert c3.abstention_message("ko").startswith("제공된 근거만으로")
    with pytest.raises(WorkerError, match="generation_language_mismatch"):
        c3.parse_requirement_plan(json.dumps(plan_payload()), catalog, "ko")


def test_grammars_bind_request_ids_without_source_or_need_text():
    _, catalog, plan = prepared()
    first = c3.requirement_plan_grammar(catalog)
    assert 'evidence-id ::= "0" | "2"' in first
    assert 'r6 ::=' in first and 'r7' not in first
    second = c3.realization_grammar(plan, catalog, "en")
    assert 's1 "," s2' in second and 's3' not in second
    assert "evidence-id" not in second
    for text in ["Synthetic copper badge", "Describe badge", "| Key |"]:
        assert text not in first + second


def test_schema_does_not_pretend_to_prove_semantic_truth_or_coverage():
    req, catalog, _ = prepared()
    payload = {"requirements": [{"requirement_id": 1, "need": "One invented need",
                                "status": "supported", "evidence_ids": [0]}]}
    plan = c3.parse_requirement_plan(json.dumps(payload), catalog, "en")
    result = c3.grounded_requirement_answer(json.dumps({"status": "answered", "claims": [
        {"requirement_id": 1, "text": "A clearly unsupported purple dragon exists."}]}),
        catalog, req.contexts, plan, "en")
    assert result["status"] == "answered"  # independent semantic review is still required


@pytest.mark.parametrize("count", range(1, 7))
def test_one_to_six_sequential_requirements_map_without_extra_claims(count):
    req = request()
    catalog = build_block_catalog(req.contexts)
    payload = {"requirements": [{"requirement_id": i, "need": "Synthetic requirement",
                                "status": "supported", "evidence_ids": [0, 2]}
                               for i in range(1, count + 1)]}
    plan = c3.parse_requirement_plan(json.dumps(payload), catalog, "en")
    answer = {"status": "answered", "claims": [{"requirement_id": i,
              "text": "A synthetic sentence."} for i in range(1, count + 1)]}
    result = c3.grounded_requirement_answer(json.dumps(answer), catalog, req.contexts, plan, "en")
    assert len(result["claims"]) == count
    assert all(len(c["citations"]) == 2 for c in result["claims"])
