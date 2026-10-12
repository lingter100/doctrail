"""Synthetic contract checks, not model quality or human review evidence."""

import builtins
import copy
import inspect
import json
import random

import pytest

from doctrail.model_retrieval import rrf_fuse
from scripts import evaluate_candidates as experiment
from scripts.evaluate_retrieval import (
    METHODS,
    build_outcome,
    compact_hits,
    fusion_diagnostic,
    paired_changes,
)


def chunks(count=100):
    return [
        {
            "chunk_id": f"d:{i}",
            "document_id": "d",
            "start_offset": 0,
            "end_offset": 4,
            "page": None,
            "text": "text",
            "title": "Synthetic",
            "filename": "d.md",
        }
        for i in range(count)
    ]


def ids(rows):
    return [r["chunk_id"] for r in rows]


def synthetic_source():
    corpus = chunks()
    documents = {"d": {"content": "text", "language": "en"}}
    question = {
        "id": "synthetic-dev-001",
        "question_family_id": "synthetic-family",
        "query": "Synthetic private query",
        "category": "same_language",
        "answerability": "answerable",
        "language": "en",
        "human_review": "pending",
        "relevant_document_ids": ["d"],
        "evidence": [
            {
                "document_id": "d",
                "evidence_group_id": "fact-1",
                "grade": 2,
                "start_offset": 0,
                "end_offset": 4,
                "quote": "text",
            }
        ],
    }
    bm25 = [{**r, "score": 100 - i} for i, r in enumerate(corpus[:50])]
    dense = [{**r, "score": 1 - i / 100} for i, r in enumerate(corpus[30:80])]
    hybrid = rrf_fuse([bm25, dense], corpus, limit=50)
    budget = rrf_fuse([bm25[:25], dense[:25]], corpus, limit=50)
    pools = {
        "bm25": bm25,
        "dense_e5": dense,
        "hybrid": hybrid,
        "hybrid_reranked": hybrid,
        "hybrid_budget50": budget,
    }
    methods = {}
    for method in METHODS:
        final = (
            [{**r, "score": float(100 - i)} for i, r in enumerate(reversed(hybrid))][:10]
            if method == "hybrid_reranked"
            else pools[method][:10]
        )
        row = build_outcome(question, final, pools[method], documents)
        if method in ("hybrid", "hybrid_reranked", "hybrid_budget50"):
            left, right = (bm25[:25], dense[:25]) if method == "hybrid_budget50" else (bm25, dense)
            row["fusion_candidate_diagnostic"] = fusion_diagnostic(
                question, left, right, pools[method]
            )
        methods[method] = experiment.method_report([row])
    comparisons = {
        f"{m}_vs_bm25": paired_changes(methods["bm25"]["questions"], methods[m]["questions"])
        for m in METHODS
        if m != "bm25"
    }
    comparisons["hybrid_reranked_vs_hybrid"] = paired_changes(
        methods["hybrid"]["questions"], methods["hybrid_reranked"]["questions"]
    )
    return {"methods": methods, "paired_comparisons": comparisons}, [question], documents, corpus


def test_disjoint_branches_preserve_exact_top25_and_original_full_rrf_order():
    corpus = chunks()
    selected, stats = experiment.select_candidates(corpus[:50], corpus[50:], corpus)
    assert set(ids(selected)) == set(ids(corpus[:25] + corpus[50:75]))
    expected = rrf_fuse([corpus[:50], corpus[50:]], corpus, limit=100)
    assert selected == [r for r in expected if r["chunk_id"] in set(ids(selected))]
    assert stats["consumed_rank_depth"] == {"bm25": 25, "dense_e5": 25}


def test_deduplication_refills_and_b_before_d_stopping_edge():
    corpus = chunks()
    bm25, dense = corpus[:50], [corpus[0], *corpus[50:99]]
    selected, stats = experiment.select_candidates(bm25, dense, corpus)
    assert len(selected) == 50
    assert stats["duplicate_visits"] == 1
    assert stats["consumed_rank_depth"] == {"bm25": 26, "dense_e5": 25}
    assert corpus[25]["chunk_id"] in ids(selected)
    assert corpus[74]["chunk_id"] not in ids(selected)


def test_complete_overlap_consumes_depth50_but_stops_before_last_duplicate():
    corpus = chunks(50)
    selected, stats = experiment.select_candidates(corpus, corpus, corpus)
    assert len(selected) == 50
    assert stats["consumed_rank_depth"] == {"bm25": 50, "dense_e5": 49}
    assert stats["visited_branch_entries"] == 99


def test_rrf_uses_unconsumed_ranks_and_canonical_ties_not_acquisition_order():
    corpus = chunks(100)
    bm25 = corpus[:50]
    dense = [*corpus[50:99], corpus[0]]
    selected, stats = experiment.select_candidates(bm25, dense, corpus)
    score = next(r["score"] for r in selected if r["chunk_id"] == corpus[0]["chunk_id"])
    assert score == 1 / 61 + 1 / 110
    assert stats["consumed_rank_depth"]["dense_e5"] == 25
    tiny, _ = experiment.select_candidates([corpus[1]], [corpus[0]], corpus)
    assert ids(tiny) == ids(corpus[:2])
    assert stats["b25_d25_union_preserved"]


@pytest.mark.parametrize("count", [0, 1, 12, 49])
def test_short_unions_return_every_unique_candidate(count):
    corpus = chunks(count)
    result, stats = experiment.select_candidates(corpus, list(reversed(corpus)), corpus)
    assert len(result) == count
    assert stats["union_unique_count"] == count


def test_randomized_overlap_invariants_and_determinism_without_labels():
    rng = random.Random(88)
    corpus = chunks()
    for _ in range(40):
        bm25, dense = rng.sample(corpus, 50), rng.sample(corpus, 50)
        first = experiment.select_candidates(bm25, dense, corpus)
        assert first == experiment.select_candidates(bm25, dense, corpus)
        result, _ = first
        assert len(result) == len(set(ids(result))) == 50
        assert set(ids(bm25[:25] + dense[:25])) <= set(ids(result))
    assert list(inspect.signature(experiment.select_candidates).parameters) == [
        "bm25",
        "dense",
        "corpus",
    ]
    # Scores are intentionally incomparable and must not affect selection or order.
    altered = [{**r, "score": -99999, "evidence": "DO_NOT_READ"} for r in bm25]
    assert experiment.select_candidates(altered, dense, corpus) == first


@pytest.mark.parametrize("mode", ["duplicate", "unknown", "budget"])
def test_invalid_branch_membership_rejected(mode):
    corpus = chunks()
    branch = (
        [corpus[0], corpus[0]]
        if mode == "duplicate"
        else [{"chunk_id": "unknown"}]
        if mode == "unknown"
        else corpus[:51]
    )
    with pytest.raises(ValueError):
        experiment.select_candidates(branch, [], corpus)


def test_all_five_original_methods_roundtrip_without_inference():
    source, questions, documents, corpus = synthetic_source()
    branches = experiment.replay_source(source, questions, documents, corpus)
    assert len(branches) == 1
    assert (
        compact_hits(branches[0][0])
        == source["methods"]["bm25"]["questions"][0]["candidate_chunks"]
    )


@pytest.mark.parametrize(
    "location", ["offset", "metric", "aggregate", "paired", "question_order", "rrf"]
)
def test_replay_rejects_drift_at_every_saved_layer(location):
    source, questions, documents, corpus = synthetic_source()
    row = source["methods"]["hybrid"]["questions"][0]
    if location == "offset":
        row["candidate_chunks"][0]["start_offset"] = 1
    elif location == "metric":
        row["metrics"]["evidence_all_at_5_chunks"] = False
    elif location == "aggregate":
        source["methods"]["dense_e5"]["metrics"]["questions"] = 0
    elif location == "paired":
        source["paired_comparisons"] = {}
    elif location == "question_order":
        row["id"] = "unexpected"
    else:
        row["candidate_chunks"][0]["score"] += 0.1
    with pytest.raises(ValueError, match="drift"):
        experiment.replay_source(source, questions, documents, corpus)


def test_hash_subset_allows_new_script_but_rejects_old_source_drift():
    experiment.verify_hashes({"old.py": "aaa", "new.py": "bbb"}, {"old.py": "aaa"})
    with pytest.raises(ValueError, match="drift"):
        experiment.verify_hashes({"old.py": "changed"}, {"old.py": "aaa"})


def test_runtime_gate_rejects_library_cuda_flag_and_dtype_drift():
    actual = {
        "python": "3.11",
        "os": "Windows",
        "gpu_name": "fixture",
        "cuda_runtime": "12",
        "cudnn": 1,
        "packages": {"torch": "2"},
        "torch_cuda_matmul_allow_tf32": False,
        "torch_cudnn_allow_tf32": True,
        "torch_deterministic_algorithms": False,
        "torch_cudnn_deterministic": False,
        "torch_cudnn_benchmark": False,
        "seed": 42,
        "reranker_dtype": "torch.float16",
    }
    original = {**actual, "model_dtypes": {"reranker": "torch.float16"}}
    assert experiment.verify_runtime(actual, original)["passed"]
    for key in actual:
        changed = {**actual, key: "drift"}
        with pytest.raises(ValueError, match="drift"):
            experiment.verify_runtime(changed, original)


@pytest.mark.parametrize("drift", [False, True])
def test_candidate_only_runs_complete_synthetic_replay_without_heavy_imports_or_weights(
    tmp_path, monkeypatch, drift
):
    source, questions, documents, corpus = synthetic_source()
    corpus_hashes = {"d": {"actual_normalized_sha256": experiment.sha256(b"text")}}
    source.update(
        {
            "source_sha256": {},
            "model_manifest_sha256": "model-digest",
            "model_specifications": {},
            "candidate_sha256": experiment.digest_json(corpus),
            "evaluated_corpus_sha256": corpus_hashes,
            "dataset": {"questions": 1},
        }
    )
    source_path = tmp_path / experiment.SOURCE_REPORT
    source_path.parent.mkdir(parents=True)
    source_path.write_text(json.dumps(source), encoding="utf-8")
    frozen = {experiment.SOURCE_REPORT: experiment.SOURCE_SHA256, "model_manifest": "model-digest"}
    calls = 0

    def hashes(*args):
        nonlocal calls
        calls += 1
        return {**frozen, **({"late_change": "drift"} if drift and calls > 1 else {})}

    monkeypatch.setattr(experiment, "frozen_hashes", hashes)
    monkeypatch.setattr(experiment, "load_model_manifest", lambda p: {"models": {}})
    monkeypatch.setattr(
        experiment,
        "prepare_inputs",
        lambda *a: ([], questions, {}, documents, corpus, corpus_hashes),
    )
    monkeypatch.setattr(experiment, "verify_snapshot", lambda *a: pytest.fail("no model weights"))
    monkeypatch.setattr(experiment.subprocess, "check_output", lambda *a, **kw: "")
    from scripts import prepare_corpus

    monkeypatch.setattr(
        prepare_corpus, "load_verified_corpus", lambda *a, **kw: [{"id": "d", "content": "text"}]
    )
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "transformers", "numpy", "psutil"}:
            pytest.fail("candidate replay must not import heavy runtime")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    journal = experiment.Journal(tmp_path / "journal.jsonl")
    try:
        if drift:
            with pytest.raises(ValueError, match="run_source_or_input_drift"):
                experiment.evaluate(
                    None, None, None, None, journal, candidate_only=True, root=tmp_path
                )
        else:
            report = experiment.evaluate(
                None, None, None, None, journal, candidate_only=True, root=tmp_path
            )
            assert report["status"] == "candidate_replay_only_no_inference"
            assert report["reranker_all_selected_rankings"] == []
            assert report["timing"]["rerank"]["requests"] == 0
            assert report["runtime_identity_comparison"] is None
            assert report["source_replay"]["passed"]
    finally:
        journal.close()
    assert "Synthetic private query" not in (tmp_path / "journal.jsonl").read_text(encoding="utf-8")


def test_inclusion_reports_group_gains_losses_and_chunk_changes():
    source, _, _, _ = synthetic_source()
    old = source["methods"]["hybrid"]["questions"]
    new = copy.deepcopy(old)
    new[0]["candidates"]["all_required_evidence_recall_at_50"] = False
    new[0]["candidates"]["covered_evidence_groups"] = []
    new[0]["candidate_chunks"].pop()
    report = experiment.inclusion_changes(old, new)
    assert report["regression_ids"] == [old[0]["id"]]
    assert report["per_question"][0]["lost_evidence_groups"] == ["fact-1"]
    assert len(report["per_question"][0]["removed_chunk_ids"]) == 1


def test_locked_test_split_precedes_any_io(tmp_path, monkeypatch):
    monkeypatch.setattr(experiment, "evaluate", lambda *a, **kw: pytest.fail("must not evaluate"))
    path = tmp_path / "result.json"
    with pytest.raises(SystemExit, match="M3_CANDIDATE_EVALUATION_FAILED"):
        experiment.main(["--split", "test", "--output", str(path)])
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("existing", ["result.json", "result.json.stages.jsonl"])
def test_never_overwrites_report_or_journal(tmp_path, existing, monkeypatch):
    path = tmp_path / existing
    path.write_text("KEEP", encoding="utf-8")
    monkeypatch.setattr(experiment, "evaluate", lambda *a, **kw: pytest.fail("must not evaluate"))
    with pytest.raises(SystemExit):
        experiment.main(["--output", str(tmp_path / "result.json")])
    assert path.read_text(encoding="utf-8") == "KEEP"


def test_failure_journal_and_stderr_hide_query_paths_and_exception_text(tmp_path, monkeypatch):
    private = "SECRET_QUERY C:/Users/private/upload.txt"

    def fail(*args, **kwargs):
        raise RuntimeError(private)

    monkeypatch.setattr(experiment, "evaluate", fail)
    path = tmp_path / "result.json"
    with pytest.raises(SystemExit) as error:
        experiment.main(["--candidate-only", "--output", str(path)])
    journal = path.with_suffix(".json.stages.jsonl").read_text(encoding="utf-8")
    assert private not in journal + str(error.value)
    assert '"exception_type": "RuntimeError"' in journal
    assert not path.exists()


def test_candidate_only_cli_passes_flag_and_writes_no_inference_report(tmp_path, monkeypatch):
    def candidate_only(*args, **kwargs):
        assert kwargs["candidate_only"]
        return {"status": "candidate_replay_only_no_inference", "methods": {}}

    monkeypatch.setattr(experiment, "evaluate", candidate_only)
    path = tmp_path / "result.json"
    experiment.main(["--candidate-only", "--output", str(path)])
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["status"] == "candidate_replay_only_no_inference"
    # This path never requests a runtime. Other tests may have imported torch independently.
    assert report["invocation"]["arguments"]["candidate_only"]
