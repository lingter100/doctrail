"""Protect diagnostic distinctions that can otherwise misdirect retrieval work."""

import pytest

from scripts.analyze_failures import analyze


def test_one_recoverable_alternative_prevents_false_chunk_boundary_diagnosis():
    # 800:1100 straddles both chunks; 20:30 in the same fact group is a valid OR alternative.
    corpus = [{"id": "doc", "content": "a" * 1500}]
    evidence = [
        {
            "document_id": "doc",
            "grade": 2,
            "evidence_group_id": "fact",
            "start_offset": start,
            "end_offset": end,
        }
        for start, end in [(800, 1100), (20, 30)]
    ]
    questions = [
        {
            "id": "q",
            "split": "dev",
            "category": "single_document",
            "answerability": "answerable",
            "evidence": evidence,
        }
    ]
    report = {
        "questions": [
            {
                "id": "q",
                "ranked_chunk_document_ids": ["doc"],
                "cross_language": "same_language_only",
                "metrics": {"evidence_all_at_5_chunks": False},
            }
        ]
    }
    outcome = analyze(report, questions, corpus)["details"][0]
    assert outcome["unrepresentable_groups"] == []
    assert outcome["diagnosis"] == "required_span_missing_from_top5_despite_document_candidates"
    questions[0]["evidence"] = evidence[:1]
    outcome = analyze(report, questions, corpus)["details"][0]
    assert outcome["unrepresentable_groups"] == ["fact"]
    assert outcome["diagnosis"] == "required_span_unrepresentable_in_current_chunks"


def test_failure_analysis_cannot_open_test_split():
    with pytest.raises(ValueError, match="development-only"):
        analyze({"questions": []}, [{"split": "test"}], [])
