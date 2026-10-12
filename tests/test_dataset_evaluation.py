"""Hand-computed retrieval failures protect metric meaning, not scoring internals."""

import json

import pytest

from scripts import evaluate_dataset as evaluation


def document(doc_id, content="0123456789" * 20, language="en", split="dev"):
    digest = evaluation.sha256(content.encode())
    return {
        "id": doc_id,
        "family_id": doc_id,
        "split": split,
        "sha256": digest,
        "normalized_sha256": digest,
        "language": language,
        "title": doc_id,
        "content": content,
    }


def evidence(doc, start, end, group="fact", grade=2):
    return {
        "document_id": doc["id"],
        "quote": doc["content"][start:end],
        "start_offset": start,
        "end_offset": end,
        "grade": grade,
        "evidence_group_id": group,
    }


def question(spans, category="single_document", language="en"):
    return {
        "schema_version": 2,
        "id": "question",
        "question_family_id": "question-family",
        "query": "What evidence is required?",
        "split": "dev",
        "category": category,
        "answerability": "answerable",
        "language": language,
        "relevant_document_ids": sorted({s["document_id"] for s in spans if s["grade"] == 2}),
        "evidence": spans,
        "human_review": "pending",
        "human_reviewer": None,
        "human_reviewed_at": None,
        "created_by": "ai",
        "generator_model": "gpt-6-astra",
        "generator_reasoning_effort": "high",
        "generation_prompt_sha256": "a" * 64,
        "reference_answer": "Synthetic regression fixture, not a reviewed answer.",
    }


def hit(doc, start=0, end=100):
    return {
        "document_id": doc["id"],
        "chunk_id": f"{doc['id']}:{start}",
        "score": 1.0,
        "start_offset": start,
        "end_offset": end,
        "page": None,
        "text": doc["content"][start:end],
    }


def test_multi_document_partial_hit_is_not_complete_evidence():
    a, b = document("a"), document("b")
    row = question([evidence(a, 10, 20, "first"), evidence(b, 20, 30, "second")], "multi_document")
    scored = evaluation.score_question(row, [hit(a)], {"a": a, "b": b})
    assert scored["metrics"] == {
        "document_hit_at_5_within_10_chunks": True,
        "document_recall_at_5_within_10_chunks": 0.5,
        "document_reciprocal_rank_within_10_chunks": 1.0,
        "evidence_any_at_5_chunks": True,
        "evidence_all_at_5_chunks": False,
        "evidence_group_recall_at_5_chunks": 0.5,
    }


def test_alternative_spans_or_together_and_grade_one_is_not_required():
    a, b, c = document("a"), document("b", language="ko"), document("c")
    row = question([evidence(a, 10, 20), evidence(b, 10, 20), evidence(c, 10, 20, "background", 1)])
    scored = evaluation.score_question(row, [hit(b)], {"a": a, "b": b, "c": c})
    assert scored["metrics"]["evidence_all_at_5_chunks"] is True
    assert scored["metrics"]["evidence_group_recall_at_5_chunks"] == 1.0
    assert scored["metrics"]["document_recall_at_5_within_10_chunks"] == 0.5
    assert scored["cross_language"] == "same_language_sufficient_with_cross_language_alternatives"


def test_duplicate_document_chunks_do_not_consume_document_ranks_but_do_consume_span_ranks():
    distractor, relevant = document("distractor"), document("relevant")
    hits = [hit(distractor, i, i + 100) for i in range(5)] + [hit(relevant)]
    scored = evaluation.score_question(
        question([evidence(relevant, 10, 20)]),
        hits,
        {"distractor": distractor, "relevant": relevant},
    )
    assert scored["first_relevant_unique_document_rank_within_10_chunks"] == 2
    assert scored["metrics"]["document_reciprocal_rank_within_10_chunks"] == 0.5
    assert scored["metrics"]["document_hit_at_5_within_10_chunks"] is True
    assert scored["metrics"]["evidence_any_at_5_chunks"] is False
    assert scored["evidence_spans"][0]["covering_chunk_ranks_within_10"] == [6]


def test_exact_offset_boundary_not_matching_quote_elsewhere_or_two_partial_chunks():
    doc = document("doc")  # Repeated text deliberately makes quote-string matching insufficient.
    row = question([evidence(doc, 90, 110)])
    partial = evaluation.score_question(row, [hit(doc, 0, 100), hit(doc, 100, 200)], {"doc": doc})
    assert partial["metrics"]["evidence_any_at_5_chunks"] is False
    exact = evaluation.score_question(row, [hit(doc, 90, 110)], {"doc": doc})
    assert exact["metrics"]["evidence_all_at_5_chunks"] is True


def test_results_after_ten_chunks_cannot_improve_metrics():
    a, b = document("a"), document("b")
    scored = evaluation.score_question(
        question([evidence(b, 10, 20)]), [hit(a)] * 10 + [hit(b)], {"a": a, "b": b}
    )
    assert scored["metrics"]["document_reciprocal_rank_within_10_chunks"] == 0.0
    assert len(scored["ranked_chunks"]) == 10


def test_no_evidence_diagnostic_does_not_inflate_positive_metrics():
    doc = document("doc")
    positive = evaluation.score_question(question([evidence(doc, 10, 20)]), [], {"doc": doc})
    absent = question([], "no_evidence")
    absent["answerability"] = "unanswerable"
    negative = evaluation.score_question(absent, [], {"doc": doc})
    summary = evaluation.summarize([positive, negative])
    assert summary["annotated_positive_questions"] == 1
    assert summary["document_hit_at_5_within_10_chunks"] == 0.0
    assert summary["no_evidence_empty_result_rate_diagnostic_only"] == 1.0
    assert all(value is None for value in negative["metrics"].values())


def test_test_split_is_refused_before_io_even_if_inputs_do_not_exist(tmp_path):
    with pytest.raises(ValueError, match="held-out test evaluation is locked"):
        evaluation.evaluate(tmp_path / "absent.json", tmp_path / "absent.jsonl", "test")
    with pytest.raises(SystemExit, match="held-out test evaluation is locked"):
        evaluation.main(
            [
                "--manifest",
                str(tmp_path / "absent.json"),
                "--questions",
                str(tmp_path / "absent.jsonl"),
                "--split",
                "test",
                "--output",
                str(tmp_path / "result.json"),
            ]
        )
    assert not (tmp_path / "result.json").exists()


def test_past_report_is_not_overwritten(tmp_path):
    report = tmp_path / "result.json"
    report.write_text("past-run")
    with pytest.raises(SystemExit, match="overwrite"):
        evaluation.main(
            ["--manifest", "absent.json", "--questions", "absent.jsonl", "--output", str(report)]
        )
    assert report.read_text() == "past-run"


def setup_run(tmp_path, monkeypatch, corpus):
    from scripts import prepare_corpus

    manifest, questions = tmp_path / "manifest.json", tmp_path / "questions.jsonl"
    manifest.write_text("{}")
    questions.write_text(json.dumps(question([evidence(corpus[0], 0, 12)])))
    (tmp_path / "uv.lock").write_text("synthetic-lock")
    (tmp_path / "pyproject.toml").write_text("synthetic-config")
    monkeypatch.setattr(prepare_corpus, "load_verified_corpus", lambda *args, **kwargs: corpus)
    monkeypatch.setattr(evaluation.subprocess, "check_output", lambda *args, **kwargs: "test")
    return manifest, questions


def test_evaluation_rejects_normalized_checksum_drift(tmp_path, monkeypatch):
    doc = document("doc", "Grounded evidence supports retrieval.")
    doc["normalized_sha256"] = "0" * 64
    manifest, questions = setup_run(tmp_path, monkeypatch, [doc])
    with pytest.raises(ValueError, match="checksum drift"):
        evaluation.evaluate(manifest, questions, root=tmp_path)


def test_offline_run_indexes_every_manifest_split_and_records_real_service_spans(
    tmp_path, monkeypatch
):
    corpus = [
        document("dev", "Grounded evidence supports retrieval."),
        document("test", "A separate held-out corpus document.", split="test"),
        document("smoke", "An older smoke corpus document.", split="smoke"),
    ]
    manifest, questions = setup_run(tmp_path, monkeypatch, corpus)
    report = evaluation.evaluate(manifest, questions, root=tmp_path)
    assert report["dataset"]["indexed_document_splits"] == {"dev": 1, "test": 1, "smoke": 1}
    assert report["dataset"]["chunks"] == 3
    assert report["metrics"]["evidence_all_at_5_chunks"] == 1.0
    assert report["evaluated_corpus_sha256"]["dev"]["actual_ingested_sha256"] == corpus[0]["sha256"]
    assert report["dataset"]["validation"]["validation_scope"] == "verified_source_spans"
    assert report["questions"][0]["ranked_chunks"][0]["start_offset"] == 0
    assert "text" not in report["questions"][0]["ranked_chunks"][0]


def test_drifting_input_during_rank_aborts_report(tmp_path, monkeypatch):
    corpus = [document("dev", "Grounded evidence supports retrieval.")]
    manifest, questions = setup_run(tmp_path, monkeypatch, corpus)
    real_rank = evaluation.rank_chunks

    def drifting_rank(query, candidates, limit):
        questions.write_text(questions.read_text() + "\n")
        return real_rank(query, candidates, limit)

    monkeypatch.setattr(evaluation, "rank_chunks", drifting_rank)
    with pytest.raises(ValueError, match="checksum drift during run"):
        evaluation.evaluate(manifest, questions, root=tmp_path)
