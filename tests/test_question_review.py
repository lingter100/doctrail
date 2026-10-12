import copy
import json

import pytest

from scripts.benchmark_api import select_queries
from scripts.build_questions import compile_questions
from scripts.question_dataset import row_digest, validate_questions
from scripts.review_questions import build_packet, render_packet, validate_review
from scripts.revise_questions import apply_exclusions


@pytest.fixture
def dataset():
    content = "First grounded fact. 두 번째 사실입니다. </script><script>alert(1)</script>"
    docs = [
        {
            "id": "a",
            "family_id": "family-a",
            "sha256": "a" * 64,
            "normalized_sha256": "b" * 64,
            "split": "dev",
            "language": "en",
            "title": "Example",
            "source_url": "https://example.com/source",
            "path": "content/en/docs/example.md",
            "content": content,
        }
    ]
    question = {
        "schema_version": 2,
        "id": "q1",
        "question_family_id": "q-family-1",
        "query": "What is the first fact?",
        "language": "en",
        "split": "dev",
        "category": "single_document",
        "answerability": "answerable",
        "created_by": "ai",
        "generator_model": "gpt-6-astra",
        "generator_reasoning_effort": "high",
        "generation_prompt_sha256": "f" * 64,
        "human_review": "pending",
        "human_reviewer": None,
        "human_reviewed_at": None,
        "reference_answer": "First grounded fact.",
        "relevant_document_ids": ["a"],
        "evidence": [
            {
                "document_id": "a",
                "quote": "First grounded fact.",
                "start_offset": 0,
                "end_offset": 20,
                "grade": 2,
                "evidence_group_id": "fact1",
            }
        ],
    }
    return docs, [question]


def review_for(rows):
    return {
        "schema_version": 1,
        "kind": "self_declared_user_review",
        "split": "dev",
        "manifest_sha256": "a" * 64,
        "questions_sha256": "b" * 64,
        "decisions": [
            {
                "question_id": rows[0]["id"],
                "question_sha256": row_digest(rows[0]),
                "reviewer": "UNIT TEST ONLY",
                "decision": "approved",
                "note": "",
                "checked_query": True,
                "checked_evidence": True,
                "reviewed_at": "2025-01-01T00:00:00Z",
            }
        ],
    }


def test_checks_do_not_claim_human_semantic_review(dataset):
    docs, rows = dataset
    result = validate_questions(rows, docs)
    assert result["validation_scope"] == "verified_source_spans"
    assert result["human_reviewed"] == 0
    result = validate_questions(rows, [{k: v for k, v in docs[0].items() if k != "content"}])
    assert result["validation_scope"] == "metadata_only"


@pytest.mark.parametrize(
    "change,match",
    [
        ({"end_offset": 19}, "length mismatch"),
        ({"quote": "Wrong grounded fact."}, "offset mismatch"),
        ({"start_offset": True}, "codepoint"),
    ],
)
def test_evidence_rejects_wrong_offsets_or_text(dataset, change, match):
    docs, rows = dataset
    rows[0]["evidence"][0].update(change)
    with pytest.raises(ValueError, match=match):
        validate_questions(rows, docs)


def test_normalized_duplicate_leak_rejected(dataset):
    docs, rows = dataset
    docs.append({**docs[0], "id": "b", "family_id": "b", "sha256": "c" * 64, "split": "test"})
    with pytest.raises(ValueError, match="normalized_sha256 crosses"):
        validate_questions(rows, docs)


def test_multiple_alternatives_are_not_multidocument_reasoning(dataset):
    docs, rows = dataset
    docs.append({**docs[0], "id": "b", "sha256": "c" * 64, "language": "ko"})
    rows[0]["evidence"].append({**rows[0]["evidence"][0], "document_id": "b"})
    rows[0]["relevant_document_ids"].append("b")
    assert validate_questions(rows, docs)["checks"] == "passed"
    rows[0]["category"] = "multi_document"
    with pytest.raises(ValueError, match="must require facts across"):
        validate_questions(rows, docs)


def test_missing_relevance_and_fabricated_human_stamp_rejected(dataset):
    docs, rows = dataset
    rows[0]["human_review"] = "approved"
    rows[0]["human_reviewer"] = "AI pretending to be user"
    with pytest.raises(ValueError, match="human-pending"):
        validate_questions(rows, docs)


def test_review_html_cannot_execute_source_markup(dataset):
    docs, rows = dataset
    packet = build_packet(rows, docs, "a" * 64, "b" * 64)
    rendered = render_packet(packet)
    assert "</script><script>alert(1)</script>" not in rendered
    payload = rendered.split('<script id="packet" type="application/json">', 1)[1].split(
        "</script>", 1
    )[0]
    assert (
        json.loads(payload)["questions"][0]["review_evidence"][0]["context"] == docs[0]["content"]
    )


def test_review_is_bound_to_question_and_does_not_unlock_test(dataset):
    _, rows = dataset
    review = review_for(rows)
    summary = validate_review(review, rows, "a" * 64, "b" * 64)
    assert summary["identity_verification"] == "not_performed"
    assert summary["test_evaluation_unlocked"] is False
    changed = copy.deepcopy(rows)
    changed[0]["query"] += " Changed"
    with pytest.raises(ValueError, match="changed after review"):
        validate_review(review, changed, "a" * 64, "b" * 64)


@pytest.mark.parametrize(
    "change,match",
    [
        ({"checked_evidence": False}, "explicit query and evidence"),
        ({"decision": "needs_revision", "note": ""}, "rationale"),
        ({"reviewed_at": "2025-01-01"}, "timestamp"),
    ],
)
def test_review_rejects_incomplete_attestations(dataset, change, match):
    _, rows = dataset
    review = review_for(rows)
    review["decisions"][0].update(change)
    with pytest.raises(ValueError, match=match):
        validate_review(review, rows, "a" * 64, "b" * 64)


def test_long_query_cannot_bypass_api_limit_with_whitespace(dataset):
    docs, rows = dataset
    rows[0]["query"] = "x" * 490 + " " * 20
    with pytest.raises(ValueError, match="invalid query"):
        validate_questions(rows, docs)


def test_compiler_anchors_exact_quotes_and_never_fabricates_human_review(dataset):
    docs, rows = dataset
    source = copy.deepcopy(rows[0])
    source["id"] = "job-001"
    source["human_review"] = "approved"
    source["evidence"][0].pop("start_offset")
    source["evidence"][0].pop("end_offset")
    job = {
        "id": "job",
        "split": "dev",
        "model": "gpt-6-astra",
        "reasoning_effort": "xhigh",
        "allowed_document_ids": ["a"],
        "category_targets": {"single_document": 1},
        "language_targets": {"en": 1},
    }
    result = compile_questions(
        {"job_id": "job", "questions": [source]}, job, docs, "a" * 64, "b" * 64
    )
    assert result[0]["human_review"] == "pending"
    assert result[0]["evidence"][0]["end_offset"] == 20
    docs[0]["content"] += "First grounded fact."
    with pytest.raises(ValueError, match="match uniquely"):
        compile_questions({"job_id": "job", "questions": [source]}, job, docs, "a" * 64, "b" * 64)


def test_api_benchmark_refuses_test_and_selects_without_ranking(dataset):
    _, rows = dataset
    assert select_queries(rows) == rows
    rows[0]["split"] = "test"
    with pytest.raises(ValueError, match="test is locked"):
        select_queries(rows)


def test_review_rejects_executable_source_links(dataset):
    docs, rows = dataset
    docs[0]["source_url"] = "javascript:alert(1)"
    with pytest.raises(ValueError, match="HTTPS"):
        build_packet(rows, docs, "a" * 64, "b" * 64)


def test_revision_preserves_original_and_rejects_test_or_unknown_exclusion(dataset):
    _, rows = dataset
    rows.append({**copy.deepcopy(rows[0]), "id": "q2"})
    original = copy.deepcopy(rows)
    revision = {
        "schema_version": 1,
        "decision_actor": "ai",
        "excluded_questions": [
            {
                "id": "q1",
                "reason": "A source independently supports the entire answer; multi-document label is not justified.",
            }
        ],
    }
    result = apply_exclusions(rows, revision)
    assert [row["id"] for row in result] == ["q2"]
    assert rows == original
    revision["excluded_questions"][0]["id"] = "unknown"
    with pytest.raises(ValueError, match="proper subset"):
        apply_exclusions(rows, revision)
    rows[0]["split"] = "test"
    with pytest.raises(ValueError, match="development-only"):
        apply_exclusions(rows, revision)
