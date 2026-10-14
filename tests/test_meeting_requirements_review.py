"""Fresh synthetic oracle/answer/diagnostic fixtures; no quality-pool reads."""
import copy
import json

import pytest

from doctrail import meeting_comparison_review as old
from doctrail import meeting_requirements_review as review


def corpus(phase="calibration"):
    cases, oracles = [], []
    for family in review.FAMILIES[phase]:
        contexts = []
        for n in range(2):
            text = f"Synthetic {family} fragment {n}. 😀 e\u0301.\r\n"
            contexts.append({"document_id": f"doc-{family}-{n}", "revision": 1,
                "chunk_id": f"chunk-{family}-{n}", "title": "Synthetic fixture", "page": None,
                "meeting_date": None, "start_offset": 5, "end_offset": 5 + len(text), "text": text})
        languages = (["en", "ko", "ko"] if family == "C3-F01" else ["ko", "en", "en"])
        if phase == "validation":
            languages = ["en", "ko", "en", "ko"]
        for n, language in enumerate(languages):
            answered = n < 2
            identity = f"synthetic-{family}-{n}"
            evidence = [{k: c[k] for k in ("chunk_id", "start_offset", "end_offset")}
                        | {"quote": c["text"]} for c in contexts]
            cases.append({"id": identity, "response_language": language,
                "payload": {"schema_version": 1, "query": "Synthetic question; language is explicit.",
                            "contexts": copy.deepcopy(contexts)}})
            facts = [{"id": f"f{i}", "text": f"Synthetic required fact {i}",
                      "evidence_alternatives": [[copy.deepcopy(evidence[i % 2])]]}
                     for i in range(3 if answered else 2)]
            if not answered:
                facts[-1]["evidence_alternatives"] = []
            oracles.append({"id": identity, "family_id": family,
                "provenance": "public" if family in {"C3-F01", "C3-F03"} else "synthetic",
                "language": language, "expected_status": "answered" if answered else "abstained",
                "required_facts": facts, "unanswerable_reason": None if answered else "Missing essential fact.",
                "forbidden_inferences": ["Do not invent a fact."], "limitations": ["Synthetic test only."],
                "question_author": "writer", "oracle_author": "writer",
                "independent_prereviewer": "prereviewer", "human_review_count": 0})
    return ({"schema_version": 1, "phase": phase, "cases": cases},
            {"schema_version": 1, "phase": phase, "cases": oracles})


def sample_and_judgment():
    draft, oracles = corpus()
    oracle = copy.deepcopy(oracles["cases"][0])
    contexts = draft["cases"][0]["payload"]["contexts"]
    oracle["id"] = "sample-1"
    citations = [{k: c[k] for k in ("chunk_id", "start_offset", "end_offset")}
                 | {"quote": c["text"]} for c in contexts]
    sample = {"sample_id": "sample-1", "question": "Synthetic question.", "response_language": "en",
              "oracle": oracle, "contexts": contexts, "answer": {"status": "answered", "reason": None,
              "claims": [{"text": "Synthetic complete answer.", "citations": citations}]}}
    judgment = {"sample_id": "sample-1", "quality": {k: True for k in old.Quality.model_fields},
        "claims": [{"claim_index": 0, "facts": [{"text": f"Fact {n}", "supported": True,
            "support": [{"citation_index": n % 2, "start_offset": 5, "end_offset": 10}]}
            for n in range(3)], "citations": [{"citation_index": i, "relevant": True,
                                               "reason": "Synthetic support."} for i in range(2)]}],
        "required_facts": [{"fact_id": f["id"], "present": True, "reason": "Present."}
                           for f in oracle["required_facts"]],
        "full_correct": True, "reason": "Synthetic review only.",
        "masking_guess": {"unit_style": "unknown", "confidence": "none", "reason": "Unknown."}}
    return sample, judgment


def attestation():
    return {"schema_version": 1, "reviewer_id": "judge", "registered_at": "2026-10-14T00:00:00+00:00",
        "actual_model": "gpt-6-astra", "actual_effort": "xhigh", "role_nonparticipation": True,
        "participating_roles": [], "mapping_seen": False, "plan_seen": False, "raw_trace_seen": False,
        "prior_judgments_seen": False, "model_metadata_seen": True, "hypothesis_metadata_seen": True,
        "prior_results_metadata_seen": True, "self_report_basis": "Injected project metadata seen.",
        "human_review_count": 0}


@pytest.mark.parametrize("phase", ["calibration", "validation"])
def test_registered_six_eight_and_explicit_language(phase):
    draft, oracles = corpus(phase)
    result = review.validate_oracles(draft, oracles, phase)
    assert len(result.cases) == review.COUNTS[phase]
    assert all("explicit" in c["payload"]["query"] for c in draft["cases"])
    with pytest.raises(ValueError):
        old.validate_oracles(draft, oracles, phase)


@pytest.mark.parametrize("mutate", [
    lambda d, o: o["cases"].pop(),
    lambda d, o: o["cases"][0].update(family_id="C3-F03"),
    lambda d, o: o["cases"][0].update(language="ko"),
    lambda d, o: o["cases"][0].update(independent_prereviewer="writer"),
    lambda d, o: o["cases"][0].update(human_review_count=False),
    lambda d, o: o["cases"][0].update(provenance="synthetic"),
    lambda d, o: o["cases"][0]["required_facts"].pop(),
    lambda d, o: o["cases"][2]["required_facts"][0].update(evidence_alternatives=[]),
    lambda d, o: o["cases"][0]["required_facts"][0]["evidence_alternatives"][0][0].update(end_offset=10),
    lambda d, o: d["cases"][0].update(response_language="ko"),
])
def test_invalid_composition_roles_evidence_and_types_fail(mutate):
    draft, oracles = corpus()
    mutate(draft, oracles)
    with pytest.raises(ValueError):
        review.validate_oracles(draft, oracles, "calibration")


def test_all_alternatives_must_require_multiple_document_revisions():
    draft, oracles = corpus()
    first = review.C3Oracle.model_validate(oracles["cases"][0])
    contexts = draft["cases"][0]["payload"]["contexts"]
    assert review.requires_multiple_sources(first, contexts)
    # Add a sufficient one-document alternative for every fact: no longer mandatory multi-doc.
    evidence = copy.deepcopy(first.required_facts[0].evidence_alternatives[0][0])
    for fact in first.required_facts:
        fact.evidence_alternatives.append([evidence])
    assert not review.requires_multiple_sources(first, contexts)
    # One alternative containing both documents is an AND, never an OR of its fragments.
    first.required_facts[1].evidence_alternatives = [[evidence,
        review.C3Oracle.model_validate(oracles["cases"][0]).required_facts[1].evidence_alternatives[0][0]]]
    assert review.requires_multiple_sources(first, contexts)


def test_cross_language_and_minimum_multi_document_are_required():
    draft, oracles = corpus()
    for case, oracle in zip(draft["cases"], oracles["cases"], strict=True):
        for fact in oracle["required_facts"]:
            if fact["evidence_alternatives"]:
                fact["evidence_alternatives"] = copy.deepcopy(oracle["required_facts"][0]["evidence_alternatives"])
    with pytest.raises(ValueError, match="review_oracle_complexity"):
        review.validate_oracles(draft, oracles, "calibration")


@pytest.mark.parametrize("kind", ["correct", "unsupported", "incomplete", "abstained", "wrong_abstention"])
def test_score_arithmetic_is_identical_without_production_family_substitution(kind):
    sample, judgment = sample_and_judgment()
    if kind == "unsupported":
        judgment["claims"][0]["facts"][0].update(supported=False, support=[])
        judgment["quality"]["claim_support"] = judgment["full_correct"] = False
    elif kind == "incomplete":
        judgment["required_facts"][0]["present"] = False
        judgment["quality"]["completeness"] = judgment["full_correct"] = False
    elif kind in {"abstained", "wrong_abstention"}:
        sample["answer"] = {"status": "abstained", "reason": "insufficient_evidence", "claims": []}
        judgment["claims"] = []
        for fact in judgment["required_facts"]:
            fact["present"] = False
        if kind == "abstained":
            sample["oracle"]["expected_status"] = "abstained"
            sample["oracle"]["unanswerable_reason"] = "Missing essential fact."
            sample["oracle"]["required_facts"][-1]["evidence_alternatives"] = []
        else:
            judgment["quality"]["completeness"] = False
            judgment["quality"]["correct_abstention_or_answer"] = judgment["full_correct"] = False
    legacy_sample = copy.deepcopy(sample)
    legacy_sample["oracle"]["family_id"] = "C2-F01"  # fixture only, never production routing
    assert review.score_sample(sample, judgment) == old.score_sample(legacy_sample, judgment)
    if kind == "abstained":
        assert review.score_sample(sample, judgment)["fact_support_rate"] is None


@pytest.mark.parametrize("mutation", [
    lambda j: j["claims"][0]["facts"][0]["support"][0].update(citation_index=5),
    lambda j: j["claims"][0]["facts"][0]["support"][0].update(end_offset=500),
    lambda j: j["claims"][0]["citations"].pop(),
    lambda j: j["quality"].update(completeness=False),
    lambda j: j.update(full_correct=False),
])
def test_score_error_parity(mutation):
    sample, judgment = sample_and_judgment()
    mutation(judgment)
    legacy = copy.deepcopy(sample)
    legacy["oracle"]["family_id"] = "C2-F01"
    with pytest.raises(ValueError) as a:
        review.score_sample(sample, judgment)
    with pytest.raises(ValueError) as b:
        old.score_sample(legacy, judgment)
    assert str(a.value) == str(b.value)


@pytest.mark.parametrize("field,value", [("mapping_seen", True), ("plan_seen", True),
    ("raw_trace_seen", True), ("prior_judgments_seen", True), ("role_nonparticipation", False),
    ("participating_roles", ["candidate_author"]), ("human_review_count", False),
    ("actual_model", "other"), ("actual_effort", "high"), ("registered_at", "2026-10-14")])
def test_prior_exposure_or_invalid_attestation_blocks_review(field, value):
    data = attestation()
    data[field] = value
    with pytest.raises(ValueError):
        review.validate_attestation(data, "judge", [])


def test_metadata_exposure_is_disclosed_and_late_or_conflicted_attestation_rejected():
    value = review.validate_attestation(attestation(), "judge", [], pack_opened_at="2026-10-14T01:00:00Z")
    assert review.exposure_label(value) == "metadata-exposed, label-masked"
    with pytest.raises(ValueError, match="not_preregistered"):
        review.validate_attestation(attestation(), "judge", [], pack_opened_at="2026-10-13T00:00:00Z")
    with pytest.raises(ValueError, match="conflict"):
        review.validate_attestation(attestation(), "judge", ["judge"])


def diagnostic():
    sample, _ = sample_and_judgment()
    sample.update(plan_sha256="a" * 64, plan={"requirements": [
        {"requirement_id": 1, "need": "Synthetic need", "status": "supported", "evidence_ids": [0, 1]}]})
    item = {"sample_id": "sample-1", "plan_sha256": "a" * 64, "requirements": [
        {"requirement_id": 1, "oracle_fact_ids": ["f0", "f1", "f2"], "need_relevant": True,
         "support_assessment": "sufficient", "status_justified": True, "reason": "Synthetic reason.",
         "support_offsets": [{"evidence_id": 0, "start_offset": 5, "end_offset": 10}]}],
        "oracle_coverage": [{"fact_id": f"f{i}", "requirement_ids": [1], "need_covered": True,
                             "reason": "Covered."} for i in range(3)],
        "realization_checks": [{"requirement_id": 1, "fully_realized": True, "added_inference": False,
                                "reason": "Synthetic check."}],
        "abstention_branch": None, "abstention_appropriate": None, "abstention_reason": None,
        "failure_categories": []}
    return sample, {"schema_version": 1, "purpose": "post_lock_plan_diagnostic", "reviewer_id": "judge",
        "answer_lock_sha256": "b" * 64, "plan_pack_sha256": "c" * 64,
        "human_review_count": 0, "items": [item]}


def validate_diagnostic(data, sample):
    return review.validate_plan_diagnostics(data, [sample], reviewer_id="judge",
        answer_lock_sha256="b" * 64, plan_pack_sha256="c" * 64)


@pytest.mark.parametrize("change", [
    lambda d: d.update(answer_lock_sha256="d" * 64),
    lambda d: d["items"].clear(),
    lambda d: d["items"][0]["requirements"].clear(),
    lambda d: d["items"][0]["requirements"][0].update(oracle_fact_ids=["unknown"]),
    lambda d: d["items"][0]["requirements"][0].update(oracle_fact_ids=[]),
    lambda d: d["items"][0]["requirements"][0].update(support_offsets=[]),
    lambda d: d["items"][0]["requirements"][0].update(support_assessment="partial", support_offsets=[]),
    lambda d: d["items"][0]["requirements"][0]["support_offsets"][0].update(end_offset=900),
    lambda d: d["items"][0]["requirements"][0]["support_offsets"][0].update(evidence_id=5),
    lambda d: d["items"][0]["oracle_coverage"][0].update(requirement_ids=[2]),
    lambda d: d["items"][0]["realization_checks"].clear(),
    lambda d: d["items"][0].update(abstention_branch="stage1"),
])
def test_diagnostic_hash_row_and_offset_boundaries(change):
    sample, data = diagnostic()
    change(data)
    with pytest.raises(ValueError):
        validate_diagnostic(data, sample)


def test_plan_diagnostics_do_not_change_answer_scores():
    sample, data = diagnostic()
    answer_sample, judgment = sample_and_judgment()
    before = review.score_sample(answer_sample, judgment)
    row = data["items"][0]["requirements"][0]
    row.update(support_assessment="not_assessable", status_justified=False, support_offsets=[])
    validate_diagnostic(data, sample)
    assert review.score_sample(answer_sample, judgment) == before
    assert json.loads(json.dumps(data))["purpose"] == "post_lock_plan_diagnostic"


@pytest.mark.parametrize("supported", [True, False])
def test_diagnostic_abstention_branch(supported):
    sample, data = diagnostic()
    if not supported:
        sample["plan"]["requirements"][0].update(status="missing", evidence_ids=[])
        data["items"][0]["requirements"][0].update(support_offsets=[], support_assessment="unsupported")
    sample["answer"] = {"status": "abstained", "reason": "insufficient_evidence", "claims": []}
    data["items"][0].update(realization_checks=[], abstention_branch="stage2" if supported else "stage1",
                            abstention_appropriate=True, abstention_reason="Synthetic review.")
    assert validate_diagnostic(data, sample)
