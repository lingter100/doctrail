"""C4 synthetic composition and independent-judgment arithmetic only."""
import copy

import pytest

from doctrail import meeting_thinking_review as review
from doctrail.meeting_comparison_review import Quality
from tests.test_meeting_requirements_review import attestation as base_attestation


def corpus(phase="calibration"):
    cases, oracles = [], []
    for family_index, family in enumerate(review.FAMILIES[phase]):
        documents, contexts = [], []
        for n in range(3):
            date = None if n == 0 else f"2026-01-0{n}"
            text = f"Synthetic {family} document {n} contains a fact. 한글 😀."
            identity = f"doc-{family}-{n}"
            documents.append({"document_id": identity, "revision": 1, "kind": "general" if n == 0 else "meeting",
                              "language": "en" if n == 0 else "ko", "meeting_date": date})
            contexts.append({"document_id": identity, "revision": 1, "chunk_id": identity + "-r1-c0000",
                "title": "Synthetic source", "meeting_date": date, "page": None,
                "start_offset": 0, "end_offset": len(text), "text": text})
        languages = ["ko", "en", "ko" if family_index == 0 else "en"]
        if phase == "validation":
            languages = ["ko", "en", "ko", "en"]
        evidence = [{k: c[k] for k in ("chunk_id", "start_offset", "end_offset")} | {"quote": c["text"]} for c in contexts]
        for n, language in enumerate(languages):
            answered = n < 2
            mode = [0, 1, 0] if family_index == 1 and n == 0 else [1, 2, 1] if n == 1 else [0, 0, 0]
            identity = f"C4-{'CAL' if phase == 'calibration' else 'VAL'}-{len(cases) + 1:02d}"
            facts = [{"id": identity + f"-fact-{i}", "text": f"Synthetic required fact {i}.",
                      "evidence_alternatives": [[copy.deepcopy(evidence[d])]]} for i, d in enumerate(mode)]
            if not answered:
                facts[-1]["evidence_alternatives"] = []
            cases.append({"id": identity, "response_language": language, "payload": {"schema_version": 1,
                "query": "Synthetic question with explicitly requested language.", "contexts": copy.deepcopy(contexts)}})
            oracles.append({"id": identity, "family_id": family, "provenance": "public" if family_index == 0 else "synthetic",
                "language": language, "expected_status": "answered" if answered else "abstained", "required_facts": facts,
                "source_documents": copy.deepcopy(documents), "unanswerable_reason": None if answered else "Missing required fact.",
                "forbidden_inferences": ["No invented condition."], "limitations": ["Synthetic fixture only."],
                "question_author": "writer", "oracle_author": "writer", "independent_prereviewer": "item-reviewer", "human_review_count": 0})
    return {"schema_version": 1, "phase": phase, "cases": cases}, {"schema_version": 1, "phase": phase, "cases": oracles}


def attestation(reviewer="judge"):
    return base_attestation() | {"reviewer_id": reviewer, "registered_at": "2000-01-01T00:00:00+00:00", "reasoning_seen": False}


def judgment(sample, full=True):
    claims = []
    for i, claim in enumerate(sample["answer"]["claims"]):
        citations = claim["citations"]
        claims.append({"claim_index": i, "facts": [{"text": "Synthetic fact.", "supported": True,
            "support": [{"citation_index": 0, "start_offset": citations[0]["start_offset"], "end_offset": citations[0]["end_offset"]}]}],
            "citations": [{"citation_index": j, "relevant": True, "reason": "Synthetic relevant evidence."} for j in range(len(citations))]})
    quality = {k: True for k in Quality.model_fields}
    quality["language"] = full
    return {"sample_id": sample["sample_id"], "quality": quality, "claims": claims,
        "required_facts": [{"fact_id": f["id"], "present": True, "reason": "Synthetic present."} for f in sample["oracle"]["required_facts"]],
        "full_correct": full, "reason": "Synthetic judgment, not model evaluation.",
        "masking_guess": {"unit_style": "unknown", "confidence": "none", "reason": "Unknown."}}


def sample():
    draft, oracles = corpus()
    case, oracle = draft["cases"][0], oracles["cases"][0]
    citation = oracle["required_facts"][0]["evidence_alternatives"][0][0]
    return {"sample_id": "sample-001", "question": case["payload"]["query"], "response_language": "ko",
        "contexts": case["payload"]["contexts"], "oracle": oracle,
        "answer": {"status": "answered", "reason": None, "claims": [{"text": "합성 답입니다.", "citations": [citation]}]}}


@pytest.mark.parametrize("phase", list(review.COUNTS))
def test_registered_composition(phase):
    data, oracles = corpus(phase)
    assert len(review.validate_oracles(data, oracles, phase).cases) == review.COUNTS[phase]


@pytest.mark.parametrize("change", [
    lambda d, o: o["cases"][0].update(family_id="C3-F01"),
    lambda d, o: o["cases"][0].update(language="en"),
    lambda d, o: o["cases"][0].update(human_review_count=False),
    lambda d, o: o["cases"][0].update(independent_prereviewer="writer"),
    lambda d, o: o["cases"][0]["required_facts"].pop(),
    lambda d, o: o["cases"][0]["source_documents"][1].update(meeting_date=None),
    lambda d, o: o["cases"][0]["source_documents"][1].update(meeting_date="2026-01-02"),
    lambda d, o: o["cases"][0]["source_documents"][0].update(revision=True),
    lambda d, o: o["cases"][0]["required_facts"][0]["evidence_alternatives"][0][0].update(quote="wrong"),
    lambda d, o: d["cases"][0].update(response_language="en"),
    lambda d, o: d["cases"][0]["payload"].update(contexts=[]),
])
def test_composition_rejects_coercion_missing_facts_and_bad_sources(change):
    data, oracles = corpus()
    change(data, oracles)
    with pytest.raises(ValueError):
        review.validate_oracles(data, oracles, "calibration")


def test_single_document_alternative_does_not_count_as_required_multi_document():
    data, oracles = corpus()
    for oracle in oracles["cases"]:
        if oracle["expected_status"] == "answered":
            first = copy.deepcopy(oracle["required_facts"][0]["evidence_alternatives"][0])
            for fact in oracle["required_facts"]:
                fact["evidence_alternatives"].append(first)
    with pytest.raises(ValueError, match="complexity"):
        review.validate_oracles(data, oracles, "calibration")


@pytest.mark.parametrize("field", ["reasoning_seen", "mapping_seen", "raw_trace_seen", "prior_judgments_seen", "plan_seen"])
def test_exposure_disqualifies_output_judge(field):
    value = attestation() | {field: True}
    with pytest.raises(ValueError):
        review.validate_attestation(value, "judge", [], pack_opened_at="2026-01-01T00:00:00+00:00")


def test_future_excluded_and_non_boolean_attestation_fail():
    for value, excluded in ((attestation() | {"registered_at": "2099-01-01T00:00:00+00:00"}, []),
                            (attestation(), ["judge"]), (attestation() | {"reasoning_seen": 0}, [])):
        with pytest.raises(ValueError):
            review.validate_attestation(value, "judge", excluded, pack_opened_at="2026-01-01T00:00:00+00:00")


def test_independent_score_support_and_optional_fact_accounting():
    value = sample()
    vote = judgment(value)
    row = review.score_sample(value, vote)
    assert row["full_correct"] and row["fact_support_rate"] == 1 and row["exact_citations"] == 1
    vote["claims"][0]["facts"].append({"text": "Optional fabricated explanation", "supported": False, "support": []})
    vote["quality"]["claim_support"] = False
    vote["full_correct"] = False
    row = review.score_sample(value, vote)
    assert row["fact_support_rate"] == .5 and row["full_correct"] is False


def test_abstained_claims_and_irrelevant_support_cannot_pass():
    value = sample()
    with pytest.raises(ValueError):
        review.score_sample(value | {"answer": value["answer"] | {"status": "abstained"}}, judgment(value))
    vote = judgment(value)
    vote["claims"][0]["citations"][0]["relevant"] = False
    with pytest.raises(ValueError, match="support_range"):
        review.score_sample(value, vote)


def test_missing_coverage_or_forged_full_flag_rejected():
    value = sample()
    for field in ("claims", "required_facts"):
        vote = judgment(value)
        vote[field] = []
        with pytest.raises(ValueError):
            review.score_sample(value, vote)
    vote = judgment(value, full=False) | {"full_correct": True}
    with pytest.raises(ValueError, match="full_inconsistent"):
        review.score_sample(value, vote)
