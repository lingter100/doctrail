"""Synthetic metric and failure fixtures; never evidence of model semantic quality."""

import json

import pytest

from scripts import evaluate_retrieval as comparison


def doc(identifier="a", language="en"):
    return {"id": identifier, "language": language, "content": "0123456789" * 20}


def span(document, start=10, end=20, group="fact", grade=2):
    return {"document_id": document["id"], "start_offset": start, "end_offset": end,
            "quote": document["content"][start:end], "evidence_group_id": group, "grade": grade}


def hit(document, start=0, end=100):
    return {"document_id": document["id"], "chunk_id": f"{document['id']}:{start}",
            "start_offset": start, "end_offset": end, "text": document["content"][start:end],
            "page": None, "score": 1.0}


def question(evidence):
    return {"id": "synthetic-question", "question_family_id": "synthetic-family",
            "query": "Synthetic fixture only", "category": "single_document",
            "answerability": "answerable", "language": "en", "human_review": "pending",
            "relevant_document_ids": sorted({s["document_id"] for s in evidence if s["grade"] == 2}),
            "evidence": evidence}


def test_candidate_ceiling_can_be_complete_while_final_top_five_misses():
    first, last = doc("first"), doc("last")
    row = question([span(first, group="one"), span(last, group="two")])
    hits = [hit(first, i, i + 100) for i in range(5)] + [hit(last)]
    outcome = comparison.build_outcome(row, hits, hits, {"first": first, "last": last})
    assert outcome["metrics"]["evidence_all_at_5_chunks"] is False
    assert outcome["candidates"]["all_required_evidence_recall_at_50"] is True
    assert outcome["candidates"]["unique_candidate_count"] == 6
    assert outcome["candidate_vs_final_diagnostic"] == "candidate_ceiling_sufficient_final_top5_missed"


def test_candidate_cutoff_is_fifty_and_distinguishes_unique_counts():
    target, distractor = doc("target"), doc("noise")
    row = question([span(target)])
    coverage = comparison.candidate_coverage(row, [hit(distractor)] * 50 + [hit(target)])
    assert coverage["candidate_count"] == 50
    assert coverage["unique_candidate_count"] == 1
    assert coverage["all_required_evidence_recall_at_50"] is False


def test_candidate_alternatives_are_or_required_groups_and_background_excluded():
    a, b, c = doc("a"), doc("b", "ko"), doc("c")
    row = question([span(a), span(b), span(c, group="other"), span(c, group="background", grade=1)])
    partial = comparison.candidate_coverage(row, [hit(b)])
    complete = comparison.candidate_coverage(row, [hit(b), hit(c)])
    assert partial["evidence_group_recall_at_50"] == 0.5
    assert partial["all_required_evidence_recall_at_50"] is False
    assert complete["all_required_evidence_recall_at_50"] is True
    assert complete["required_evidence_groups"] == ["fact", "other"]


def test_candidate_partial_chunks_cannot_collectively_cover_one_span():
    document = doc()
    row = question([span(document, 90, 110)])
    result = comparison.candidate_coverage(row, [hit(document), hit(document, 100, 200)])
    assert result["all_required_evidence_recall_at_50"] is False


def test_unannotated_candidate_recall_is_null_and_excluded_from_denominator():
    document = doc()
    positive = comparison.build_outcome(question([span(document)]), [], [], {"a": document})
    absent = question([])
    absent.update(category="no_evidence", answerability="unanswerable")
    negative = comparison.build_outcome(absent, [], [], {"a": document})
    assert negative["candidates"]["all_required_evidence_recall_at_50"] is None
    summary = comparison.coverage_summary([positive, negative])
    assert summary["annotated_positive_questions"] == 1
    assert summary["all_required_evidence_recall_at_50"] == 0


def test_reranking_keeps_original_candidate_ceiling():
    target = doc()
    row = question([span(target)])
    # Empty final ranking deliberately probes reporting; no fake model quality assertion.
    outcome = comparison.build_outcome(row, [], [hit(target)], {"a": target})
    assert outcome["candidate_chunks"][0]["chunk_id"] == "a:0"
    assert outcome["metrics"]["evidence_all_at_5_chunks"] is False
    assert outcome["candidates"]["all_required_evidence_recall_at_50"] is True


def test_paired_changes_track_gains_regressions_ties_and_exclude_nulls():
    def rows(values):
        return [{"id": str(index), "metrics": dict.fromkeys(comparison.METRIC_KEYS, value)}
                for index, value in enumerate(values)]
    changes = comparison.paired_changes(rows([0, 1, 0.5, None]), rows([1, 0, 0.5, None]))
    metric = changes["evidence_all_at_5_chunks"]
    assert metric["gain_ids"] == ["0"]
    assert metric["regression_ids"] == ["1"]
    assert metric["tie_ids"] == ["2"]
    assert metric["paired_positive_questions"] == 3
    assert metric["mean_delta"] == 0
    with pytest.raises(ValueError, match="Paired question IDs"):
        comparison.paired_changes(rows([0, 1]), rows([1]))


def test_test_split_refused_before_imports_or_file_creation(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="test evaluation is locked"):
        comparison.evaluate(missing, missing, missing, missing, missing, None, "test")
    with pytest.raises(SystemExit, match="test evaluation is locked"):
        comparison.main(["--manifest", str(missing), "--questions", str(missing),
                         "--split", "test", "--output", str(tmp_path / "run.json")])
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("existing", ["run.json", "run.json.stages.jsonl"])
def test_report_and_failure_journal_cannot_be_overwritten(tmp_path, existing):
    path = tmp_path / existing
    path.write_text("past-run")
    with pytest.raises(SystemExit, match="overwrite"):
        comparison.main(["--manifest", "missing", "--questions", "missing",
                         "--output", str(tmp_path / "run.json")])
    assert path.read_text() == "past-run"


def test_failure_preserves_safe_stage_checkpoint_without_raw_exception(tmp_path, monkeypatch):
    def fail(*args):
        journal = args[5]
        journal.stage = "synthetic_stage"
        journal.write("query_completed", question_id="synthetic-id", elapsed_ms=1.5)
        raise RuntimeError("private raw question and C:/Users/private-path")
    monkeypatch.setattr(comparison, "evaluate", fail)
    with pytest.raises(SystemExit, match="M3_EVALUATION_FAILED"):
        comparison.main(["--manifest", "missing", "--questions", "missing",
                         "--output", str(tmp_path / "run.json")])
    journal = (tmp_path / "run.json.stages.jsonl").read_text()
    assert "private" not in journal
    events = [json.loads(line) for line in journal.splitlines()]
    assert events[-2]["question_id"] == "synthetic-id"
    assert events[-1]["event"] == "run_failed"
    assert events[-1]["exception_type"] == "RuntimeError"
    assert events[-1]["stage"] == "synthetic_stage"
    assert not (tmp_path / "run.json").exists()


def test_drifted_frozen_inputs_rejected_before_corpus_load(tmp_path):
    with pytest.raises(ValueError, match="unchanged frozen M2"):
        comparison.prepare_inputs(tmp_path / "none", tmp_path / "none", {}, tmp_path)


def test_stage_tokens_and_latency_are_separate_from_warmups():
    assert comparison.telemetry_delta(
        {"tokenized_inputs": 2, "truncated_inputs": 1, "tokens_before_truncation": 600},
        {"tokenized_inputs": 3, "truncated_inputs": 1, "tokens_before_truncation": 650},
    ) == {"tokenized_inputs": 1, "truncated_inputs": 0, "tokens_before_truncation": 50}
    timings = comparison.timing_summary([4, 1, 3, 2])
    assert timings["p50_ms"] == 2
    assert timings["p95_ms"] == 4
    assert timings["samples_ms"] == [4, 1, 3, 2]


def test_baseline_parity_rejects_metric_or_rank_drift():
    document = doc()
    row = comparison.build_outcome(question([span(document)]), [hit(document)],
                                   [hit(document)], {"a": document})
    baseline = {"questions": [row], "metrics": comparison.summarize([row])}
    assert comparison.verify_baseline_parity([row], baseline)["passed"]
    changed = {**row, "ranked_chunks": []}
    with pytest.raises(ValueError, match="baseline ranking or metric drift"):
        comparison.verify_baseline_parity([changed], baseline)


def test_token_maximum_is_not_subtracted_or_mislabeled_as_stage_maximum():
    assert comparison.telemetry_delta(
        {"max_tokens_before_truncation": 700}, {"max_tokens_before_truncation": 710}
    ) == {"max_tokens_before_truncation_since_model_load": 710}


def test_fusion_reports_union_evidence_lost_when_reduced_to_fifty():
    target, noise = doc("target"), doc("noise")
    row = question([span(target)])
    lexical = [{**hit(noise), "chunk_id": f"noise:{i}"} for i in range(50)]
    dense = [hit(target), *lexical[:49]]
    diagnostic = comparison.fusion_diagnostic(row, lexical, dense, lexical)
    assert diagnostic["intersection_unique_count"] == 49
    assert diagnostic["union_unique_count"] == 51
    assert diagnostic["dropped_unique_count"] == 1
    assert diagnostic["all_required_evidence_recall_in_union"] is True
    assert comparison.candidate_coverage(row, lexical)["all_required_evidence_recall_at_50"] is False


def test_input_token_records_preserve_identity_alignment_and_reject_missing_samples():
    tokens = [{"tokens_before_truncation": 600, "truncated": True}]
    records = comparison.input_records(tokens, ["doc:0"], "chunk_id")
    assert records == [{"chunk_id": "doc:0", **tokens[0]}]
    with pytest.raises(ValueError, match="input identities"):
        comparison.input_records(tokens, [], "chunk_id")
