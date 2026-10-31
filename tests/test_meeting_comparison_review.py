"""Fresh synthetic review contracts; no inference, published sources or old pools."""
import copy

import pytest
from pydantic import ValidationError

from doctrail.meeting_comparison_review import (
    JudgmentFile,
    Oracle,
    Quality,
    requires_multiple_sources,
    score_sample,
    summarize,
    validate_oracles,
)


def pair_fixture(phase="calibration"):
    """Return (input JSON, oracle JSON), satisfying the registered split quotas.

    Each case has two new synthetic documents; answered pairs require both.
    Partial-insufficiency cases ask for known marker A and unprovided marker C.
    This helper is safe to reuse in model-free audit integration tests.
    """
    per_family, answered = (4, 3) if phase == "calibration" else (6, 4)
    families = ("C2-F01", "C2-F02") if phase == "calibration" else ("C2-F03", "C2-F04")
    inputs, oracles = [], []
    for family in families:
        for index in range(per_family):
            identity = f"{family}-{index}"
            language = "ko" if index < per_family // 2 else "en"
            status = "answered" if index < answered else "abstained"
            pair = index < answered - 1
            contexts = [{"document_id": f"{identity}-doc-{letter}", "revision": 1,
                         "chunk_id": f"{identity}-chunk-{letter}", "title": "Synthetic markers",
                         "meeting_date": None, "page": None, "start_offset": 7,
                         "end_offset": 7 + len(text), "text": text}
                        for letter, text in (("a", "Marker A is mint.\n"),
                                             ("b", "Marker B is amber.\n"))]

            def fact(index_, text, contexts=contexts):
                source = contexts[index_]
                return {"id": f"fact-{index_}", "text": text, "evidence_alternatives": [[{
                    "chunk_id": source["chunk_id"], "start_offset": source["start_offset"],
                    "end_offset": source["end_offset"], "quote": source["text"]}]]}
            facts = [fact(0, "Marker A is mint.")]
            if pair:
                facts.append(fact(1, "Marker B is amber."))
            if status == "abstained":
                facts.append({"id": "missing", "text": "The hue of marker C.",
                              "evidence_alternatives": []})
            query = ("표지 A와 C의 색은 무엇인가요?" if status == "abstained" else
                     "표지 A와 B의 색은 무엇인가요?" if pair else "표지 A의 색은 무엇인가요?")
            if language == "en":
                query = ("What are the hues of markers A and C?" if status == "abstained" else
                         "What are the hues of markers A and B?" if pair else
                         "What is the hue of marker A?")
            inputs.append({"id": identity, "payload": {"schema_version": 1, "query": query,
                           "contexts": contexts}, "official_input_tokens": {"L0": 200, "C2": 200}})
            oracles.append({"id": identity, "family_id": family,
                "provenance": "public" if family in {"C2-F01", "C2-F03"} else "synthetic",
                "language": language, "expected_status": status, "required_facts": facts,
                "unanswerable_reason": "Marker C is not provided." if status == "abstained" else None,
                "forbidden_inferences": ["Do not guess unprovided markers."], "limitations": [],
                "question_author": "synthetic-question-author", "oracle_author": "synthetic-oracle-author",
                "independent_prereviewer": "synthetic-prereviewer", "human_review_count": 0})
    return ({"schema_version": 1, "phase": phase, "cases": inputs},
            {"schema_version": 1, "phase": phase, "cases": oracles})


def sample_fixture(*, abstained=False, identity="sample-01"):
    inputs, oracles = pair_fixture()
    index = 3 if abstained else 0
    item, oracle = inputs["cases"][index], copy.deepcopy(oracles["cases"][index])
    oracle["id"] = identity
    citations = [f["evidence_alternatives"][0][0] for f in oracle["required_facts"]
                 if f["evidence_alternatives"]]
    answer = {"status": "abstained" if abstained else "answered",
              "reason": "insufficient_evidence" if abstained else None,
              "claims": [] if abstained else [{"text": "표지 A는 민트색이고 B는 호박색이다.",
                                                "citations": copy.deepcopy(citations)}]}
    quality = {k: True for k in Quality.model_fields}
    judgment = {"sample_id": identity, "quality": quality, "claims": [] if abstained else [{
        "claim_index": 0, "facts": [{"text": f["text"], "supported": True, "support": [{
            "citation_index": i, "start_offset": citations[i]["start_offset"],
            "end_offset": citations[i]["end_offset"]}]} for i, f in enumerate(oracle["required_facts"])],
        "citations": [{"citation_index": i, "relevant": True, "reason": "Supplies required fact."}
                      for i in range(len(citations))]}],
        "required_facts": [{"fact_id": f["id"], "present": not abstained,
                            "reason": "Present." if not abstained else "Whole answer withheld."}
                           for f in oracle["required_facts"]],
        "full_correct": True, "reason": "Synthetic independent judgment.",
        "masking_guess": {"unit_style": "unknown", "confidence": "none", "reason": "No guess."}}
    sample = {"sample_id": identity, "question": item["payload"]["query"],
              "contexts": copy.deepcopy(item["payload"]["contexts"]), "oracle": oracle, "answer": answer}
    return sample, judgment


@pytest.mark.parametrize("phase", ["calibration", "validation"])
def test_registered_family_and_complexity_quotas(phase):
    inputs, oracle = pair_fixture(phase)
    parsed = validate_oracles(inputs, oracle, phase)
    assert len(parsed.cases) == (8 if phase == "calibration" else 12)


def test_global_language_balance_cannot_replace_per_family_balance():
    inputs, oracle = pair_fixture()
    for index, (case, answer) in enumerate(zip(inputs["cases"], oracle["cases"], strict=True)):
        answer["language"] = "ko" if index < 4 else "en"
        case["payload"]["query"] = "표지 색은?" if index < 4 else "What hue?"
    with pytest.raises(ValueError, match="composition"):
        validate_oracles(inputs, oracle, "calibration")


def test_global_answerability_balance_cannot_replace_per_family_balance():
    inputs, oracle = pair_fixture()
    a, b = oracle["cases"][3], oracle["cases"][4]
    a["expected_status"], a["unanswerable_reason"] = "answered", None
    a["required_facts"].pop()
    b["expected_status"], b["unanswerable_reason"] = "abstained", "Second marker missing."
    b["required_facts"][1]["evidence_alternatives"] = []
    with pytest.raises(ValueError, match="composition"):
        validate_oracles(inputs, oracle, "calibration")


def test_language_label_must_match_actual_request():
    inputs, oracle = pair_fixture()
    inputs["cases"][0]["payload"]["query"] = "What hue?"
    with pytest.raises(ValueError, match="oracle_language"):
        validate_oracles(inputs, oracle, "calibration")


@pytest.mark.parametrize("phase", ["calibration", "validation"])
def test_multifactual_quota_only_counts_answered_cases(phase):
    inputs, oracle = pair_fixture(phase)
    oracle["cases"][0]["required_facts"].pop()
    with pytest.raises(ValueError, match="complexity"):
        validate_oracles(inputs, oracle, phase)


def test_each_family_needs_partial_insufficiency_not_only_missing_facts():
    inputs, oracle = pair_fixture()
    oracle["cases"][3]["required_facts"].pop(0)
    with pytest.raises(ValueError, match="complexity"):
        validate_oracles(inputs, oracle, "calibration")


def test_same_document_multiple_chunks_do_not_count_as_multiple_sources():
    inputs, oracle = pair_fixture()
    item = inputs["cases"][0]
    parsed = Oracle.model_validate(oracle["cases"][0])
    contexts = copy.deepcopy(item["payload"]["contexts"])
    assert requires_multiple_sources(parsed, contexts)
    contexts[1]["document_id"] = contexts[0]["document_id"]
    assert not requires_multiple_sources(parsed, contexts)
    contexts[1]["revision"] = 2
    assert requires_multiple_sources(parsed, contexts)


def test_any_sufficient_single_source_combination_defeats_multisource_label():
    inputs, oracle = pair_fixture()
    row = oracle["cases"][0]
    contexts = inputs["cases"][0]["payload"]["contexts"]
    # A new alternative is declared sufficient by this synthetic oracle; its
    # semantic validity remains a prereview duty, never inferred by the counter.
    row["required_facts"][1]["evidence_alternatives"].append(
        copy.deepcopy(row["required_facts"][0]["evidence_alternatives"][0]))
    assert not requires_multiple_sources(Oracle.model_validate(row), contexts)


def test_every_family_needs_one_genuinely_multisource_case():
    inputs, oracle = pair_fixture()
    for case in inputs["cases"][:4]:
        case["payload"]["contexts"][1]["document_id"] = case["payload"]["contexts"][0]["document_id"]
    with pytest.raises(ValueError, match="complexity"):
        validate_oracles(inputs, oracle, "calibration")


def test_validation_requires_four_multisource_cases():
    inputs, oracle = pair_fixture("validation")
    for index in (0, 1, 6):
        contexts = inputs["cases"][index]["payload"]["contexts"]
        contexts[1]["document_id"] = contexts[0]["document_id"]
    with pytest.raises(ValueError, match="complexity"):
        validate_oracles(inputs, oracle, "validation")


def test_correct_answer_and_correct_abstention_denominators():
    sample, judgment = sample_fixture()
    score = score_sample(sample, judgment)
    assert score["full_correct"] and score["citation_exact_rate"] == 1
    assert score["citation_precision"] == score["fact_support_rate"] == 1
    assert score["facts"] == score["supported_facts"] == 2
    sample, judgment = sample_fixture(abstained=True)
    score = score_sample(sample, judgment)
    assert score["full_correct"] and score["citations"] == score["facts"] == 0
    assert score["citation_exact_rate"] is score["citation_precision"] is score["fact_support_rate"] is None


def test_unsupported_optional_fact_counts_in_denominator_and_fails_full_gate():
    sample, judgment = sample_fixture()
    sample["answer"]["claims"][0]["text"] += " 이 표지는 어제 도착했다."
    judgment["claims"][0]["facts"].append({"text": "Markers arrived yesterday.",
                                          "supported": False, "support": []})
    judgment["quality"]["claim_support"] = judgment["full_correct"] = False
    score = score_sample(sample, judgment)
    assert score["facts"] == 3 and score["supported_facts"] == 2
    assert score["fact_support_rate"] == 2 / 3 and not score["full_correct"]
    judgment["quality"]["claim_support"] = True
    with pytest.raises(ValueError, match="quality_inconsistent"):
        score_sample(sample, judgment)


def test_irrelevant_citation_fails_full_even_when_all_quality_flags_true():
    sample, judgment = sample_fixture()
    sample["answer"]["claims"][0]["citations"].append(
        copy.deepcopy(sample["answer"]["claims"][0]["citations"][0]))
    judgment["claims"][0]["citations"].append({"citation_index": 2, "relevant": False,
                                               "reason": "Redundant exact duplicate."})
    judgment["full_correct"] = False
    score = score_sample(sample, judgment)
    assert score["citation_precision"] == 2 / 3 and score["irrelevant_citation_links"] == 1
    assert score["citation_duplicate_codepoints"] == len(sample["contexts"][0]["text"])
    judgment["full_correct"] = True
    with pytest.raises(ValueError, match="full_inconsistent"):
        score_sample(sample, judgment)


def test_duplicate_citations_across_claims_have_document_revision_union_metrics():
    sample, judgment = sample_fixture()
    sample["answer"]["claims"].append(copy.deepcopy(sample["answer"]["claims"][0]))
    review = copy.deepcopy(judgment["claims"][0])
    review["claim_index"] = 1
    judgment["claims"].append(review)
    score = score_sample(sample, judgment)
    assert score["citation_codepoints"] == 2 * score["citation_unique_codepoints"]
    assert score["citation_duplicate_codepoints"] == score["citation_unique_codepoints"]


@pytest.mark.parametrize("change", [
    lambda j: j["claims"][0]["facts"][0]["support"][0].update(start_offset=0),
    lambda j: j["claims"][0]["facts"][0]["support"][0].update(end_offset=500),
    lambda j: j["claims"][0]["facts"][0]["support"][0].update(citation_index=7),
    lambda j: j["claims"][0]["citations"][0].update(relevant=False),
    lambda j: j["claims"][0]["facts"][0].update(supported=False),
])
def test_invalid_support_range_or_support_relevance_rejected(change):
    sample, judgment = sample_fixture()
    change(judgment)
    with pytest.raises(ValueError):
        score_sample(sample, judgment)


def test_missing_claim_and_required_fact_reviews_never_default_to_success():
    sample, judgment = sample_fixture()
    for key in ("claims", "required_facts"):
        partial = copy.deepcopy(judgment)
        partial[key] = []
        with pytest.raises(ValueError, match="coverage"):
            score_sample(sample, partial)


@pytest.mark.parametrize("value", [0, 1, "true", "false", None])
def test_quality_flags_are_strict_booleans(value):
    sample, judgment = sample_fixture()
    judgment["quality"]["claim_support"] = value
    with pytest.raises(ValidationError):
        score_sample(sample, judgment)


def judgment_file(judgments, reviewer="independent-synthetic-reviewer"):
    return {"schema_version": 1, "reviewer_id": reviewer, "mapping_not_seen": True,
            "independent_of_authors_and_designers": True, "human_review_count": 0,
            "judgments": judgments}


@pytest.mark.parametrize("field,value", [("mapping_not_seen", 1),
    ("independent_of_authors_and_designers", 1), ("human_review_count", False),
    ("schema_version", True)])
def test_literals_cannot_coerce_booleans_and_integers(field, value):
    _, judgment = sample_fixture()
    body = judgment_file([judgment])
    body[field] = value
    with pytest.raises(ValidationError):
        JudgmentFile.model_validate(body)


def test_abstention_with_claims_and_error_are_invalid_answers():
    sample, judgment = sample_fixture()
    sample["answer"].update(status="abstained", reason="insufficient_evidence")
    with pytest.raises(ValueError, match="answer_contract"):
        score_sample(sample, judgment)


def test_incorrect_abstention_is_failure_with_na_citation_and_fact_rates():
    sample, judgment = sample_fixture()
    sample["answer"] = {"status": "abstained", "reason": "insufficient_evidence", "claims": []}
    judgment["claims"] = []
    for fact in judgment["required_facts"]:
        fact["present"] = False
    judgment["quality"]["completeness"] = False
    judgment["quality"]["correct_abstention_or_answer"] = False
    judgment["full_correct"] = False
    score = score_sample(sample, judgment)
    assert not score["full_correct"]
    assert score["citation_exact_rate"] is score["fact_support_rate"] is None
    sample["answer"] = {"status": "error", "reason": "native_failed", "claims": []}
    with pytest.raises(ValueError, match="answer_contract"):
        score_sample(sample, judgment)


def summary_fixture(phase="calibration", improvement=True):
    samples, judgments, links = [], [], []
    count = 8 if phase == "calibration" else 12
    arms = ("L0", "C2") if phase == "calibration" else ("C2",)
    for case in range(count):
        for arm in arms:
            identity = f"sample-{len(samples):02}"
            sample, judgment = sample_fixture(identity=identity)
            if improvement and case == 0 and arm == "L0":
                judgment["quality"]["language"] = judgment["full_correct"] = False
            samples.append(sample)
            judgments.append(judgment)
            links.append({"sample_id": identity, "case_id": f"case-{case}", "arm": arm})
    return {"samples": samples}, judgment_file(judgments), {"mappings": links}


def test_calibration_gate_requires_eight_correct_and_observed_improvement():
    pack, judgments, mapping = summary_fixture()
    result = summarize(pack, judgments, mapping, "calibration", "independent-synthetic-reviewer", [])
    assert result["passed"] and result["correct"] == {"C2": 8, "L0": 7}
    assert result["improvements"] == 1 and result["regressions"] == 0
    pack, judgments, mapping = summary_fixture(improvement=False)
    assert not summarize(pack, judgments, mapping, "calibration", "independent-synthetic-reviewer", [])["passed"]


def test_one_candidate_regression_defeats_separate_improvement():
    pack, judgments, mapping = summary_fixture()
    judgments["judgments"][3]["quality"]["language"] = False
    judgments["judgments"][3]["full_correct"] = False
    result = summarize(pack, judgments, mapping, "calibration", "independent-synthetic-reviewer", [])
    assert result["improvements"] == 1 and result["regressions"] == 1
    assert result["correct"]["C2"] == 7 and not result["passed"]


def test_partial_reordered_or_duplicate_samples_fail_closed():
    pack, judgments, mapping = summary_fixture()
    for change in ("partial", "reordered", "duplicate"):
        p, j, m = copy.deepcopy((pack, judgments, mapping))
        if change == "partial":
            p["samples"] = p["samples"][:-2]
            j["judgments"] = j["judgments"][:-2]
            m["mappings"] = m["mappings"][:-2]
        elif change == "reordered":
            j["judgments"].reverse()
        else:
            m["mappings"][1]["arm"] = "L0"
        with pytest.raises(ValueError):
            summarize(p, j, m, "calibration", "independent-synthetic-reviewer", [])


@pytest.mark.parametrize("reviewer", ["synthetic-question-author", "synthetic-oracle-author",
    "synthetic-prereviewer", "excluded-designer"])
def test_author_prereviewer_and_designer_are_not_independent_reviewers(reviewer):
    pack, judgments, mapping = summary_fixture()
    judgments["reviewer_id"] = reviewer
    with pytest.raises(ValueError, match="role_conflict"):
        summarize(pack, judgments, mapping, "calibration", reviewer, ["excluded-designer"])


def test_validation_gate_requires_twelve_selected_candidate_results():
    pack, judgments, mapping = summary_fixture("validation")
    result = summarize(pack, judgments, mapping, "validation", "independent-synthetic-reviewer", [])
    assert result["passed"] and result["correct"] == {"C2": 12}
    assert result["improvements"] is result["regressions"] is None
    judgments["judgments"][0]["quality"]["conditions"] = False
    judgments["judgments"][0]["full_correct"] = False
    assert not summarize(pack, judgments, mapping, "validation", "independent-synthetic-reviewer", [])["passed"]
