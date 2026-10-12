"""Synthetic diagnostic contracts; no dev outcome computation or quality claim."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.analyze_candidates import (
    classify_groups,
    main,
    occupancy,
    open_tokenizer,
    source_tokens,
    span_visibility,
    tokenize_input,
    uncovered_intervals,
    verified_hits,
    verify_tokenizer_files,
)


def chunk(key="a", start=0, end=10, document="doc"):
    return {"chunk_id": key, "document_id": document, "start_offset": start,
            "end_offset": end, "page": None, "text": "x" * (end - start)}


def span(start=2, end=5, document="doc", group="fact", grade=2):
    return {"start_offset": start, "end_offset": end, "document_id": document,
            "evidence_group_id": group, "grade": grade}


def test_group_or_alternative_avoids_false_chunking_failure():
    question = {"evidence": [span(0, 20), span(2, 5, document="alternative")]}
    corpus = [chunk(), chunk("alt", document="alternative")]
    result = classify_groups(question, [], corpus)
    assert result["groups"][0]["category"] == "evidence_document_absent"
    assert result["groups"][0]["representable_alternative_indices"] == [1]
    assert classify_groups(question, corpus[1:], corpus)["all_groups_covered"] is True


def test_disjoint_group_reasons_and_overlapping_question_flags():
    question = {"evidence": [span(0, 20, group="boundary"),
                             span(document="absent", group="absent"),
                             span(12, 15, group="other"), span(group="covered")]}
    corpus = [chunk(), chunk("later", 10, 18), chunk("abs", document="absent")]
    result = classify_groups(question, corpus[:1], corpus)
    assert {row["group_id"]: row["category"] for row in result["groups"]} == {
        "boundary": "no_representable_full_span_chunk", "absent": "evidence_document_absent",
        "other": "correct_document_other_chunks", "covered": "covered"}
    assert all(result["question_overlapping_flags"].values())
    assert result["all_groups_covered"] is False


def test_grade_one_and_empty_questions_have_no_required_groups():
    assert classify_groups({"evidence": [span(grade=1)]}, [], [chunk()])["all_groups_covered"] is None


def test_present_unrepresentable_alternative_does_not_hide_missing_representable_document():
    question = {"evidence": [span(0, 20), span(document="alternative")]}
    corpus = [chunk(), chunk("alt", document="alternative")]
    row = classify_groups(question, corpus[:1], corpus)["groups"][0]
    assert row["category"] == "evidence_document_absent"
    assert row["present_evidence_document_ids"] == ["doc"]
    assert row["present_representable_alternative_document_ids"] == []


def test_partial_spans_across_two_chunks_never_count_as_one_full_span():
    result = classify_groups({"evidence": [span(5, 15)]},
                             [chunk(), chunk("b", 10, 20)], [chunk(), chunk("b", 10, 20)])
    assert result["groups"][0]["category"] == "no_representable_full_span_chunk"


def test_occupancy_uses_positive_geometric_overlap_and_manifest_family_only():
    docs = {"doc": {"family_id": "f", "language": "en"},
            "ko": {"family_id": "f", "language": "ko"}}
    rows = [chunk(), chunk("b", 8, 18), chunk("c", 18, 20), chunk("ko", document="ko")]
    result = occupancy(rows, docs)
    assert result["same_document_positive_overlap_pairs"] == [
        {"chunk_ids": ["a", "b"], "intersection_codepoints": 2}]
    assert result["chunks_beyond_first_per_document"] == 2
    assert result["multilanguage_family_count"] == 1


def test_verified_hits_rejects_duplicates_unknown_and_changed_offsets():
    good = chunk()
    assert verified_hits([good], {"a": good}) == [good]
    for bad in ([good, good], [chunk("unknown")], [{**good, "end_offset": 9}]):
        with pytest.raises(ValueError):
            verified_hits(bad, {"a": good})


def test_union_keeps_leading_internal_and_trailing_gaps():
    assert uncovered_intervals(0, 10, [(1, 3), (2, 4), (6, 8)]) == [[0, 1], [4, 6], [8, 10]]
    assert uncovered_intervals(2, 8, [(0, 5), (5, 9)]) == []


def test_token_retention_does_not_claim_whitespace_or_normalization_coverage():
    row = chunk(end=9)
    tokens = {"before": [(1, 1, 3), (2, 4, 9)], "after": [(1, 1, 3), (2, 4, 9)]}
    result = span_visibility(row, span(0, 9), tokens)
    assert result["full_source_span_in_chunk"]
    assert result["all_evidence_overlapping_tokens_retained"]
    assert not result["offset_union_covers_entire_span_after"]
    assert result["uncovered_source_intervals_after"] == [[0, 1], [3, 4]]
    assert result["evidence_tokens_lost_to_truncation"] == 0


def test_truncation_loses_overlapping_token_even_if_other_token_reaches_max_end():
    tokens = {"before": [(1, 0, 10), (2, 4, 6)], "after": [(1, 0, 10)]}
    result = span_visibility(chunk(), span(4, 6), tokens)
    assert result["offset_union_covers_entire_span_after"]
    assert result["evidence_tokens_lost_to_truncation"] == 1
    assert not result["all_evidence_overlapping_tokens_retained"]


def test_noncontaining_chunk_and_empty_offsets_never_prove_visibility():
    result = span_visibility(chunk(start=3), span(2, 6), {"before": [], "after": []})
    assert not result["full_source_span_in_chunk"]
    assert not result["all_evidence_overlapping_tokens_retained"]
    assert not result["offset_union_covers_entire_span_after"]


class Encoding(dict):
    def __init__(self, tokens, offsets, sequence):
        super().__init__(input_ids=tokens, offset_mapping=offsets)
        self.sequence = sequence

    def sequence_ids(self):
        return self.sequence


def test_prefix_query_special_tokens_excluded_and_unicode_uses_codepoints():
    # Source ' 한글e\u0301!' has six Python codepoints, irrespective of UTF-8 width.
    encoding = Encoding([0, 1, 2, 3, 4, 5, 6],
                        [(0, 0), (0, 8), (10, 12), (12, 14), (14, 15), (0, 5), (0, 0)],
                        [None, 0, 0, 0, 0, 1, None])
    assert source_tokens(encoding, 0, 9, 6) == [(2, 1, 3), (3, 3, 5), (4, 5, 6)]
    assert source_tokens(encoding, 1, 0, 6) == [(5, 0, 5)]
    with pytest.raises(ValueError, match="invalid_tokenizer_offset"):
        source_tokens(Encoding([1], [(0, 99)], [0]), 0, 0, 6)


class StubTokenizer:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if kwargs.get("add_special_tokens") is False:
            return {"input_ids": [10]}
        prefix = 9 if len(args) == 1 else 0
        sequence = 0 if len(args) == 1 else 1
        return Encoding([0, 1, 2], [(0, 0), (prefix, prefix + 3), (0, 0)],
                        [None, sequence, None])

    def num_special_tokens_to_add(self, pair):
        return 4


def test_tokenizer_settings_match_frozen_e5_and_bge():
    tokenizer = StubTokenizer()
    tokenize_input(tokenizer, chunk(end=3))
    assert tokenizer.calls[0][0] == ("passage: xxx",)
    assert tokenizer.calls[1][1]["truncation"] is True
    assert tokenizer.calls[1][1]["max_length"] == 512
    tokenizer = StubTokenizer()
    tokenize_input(tokenizer, chunk(end=3), "question")
    assert tokenizer.calls[1][0] == ("question", "xxx")
    assert tokenizer.calls[2][1]["truncation"] == "only_second"


def test_tokenizer_files_verified_without_weights_and_reject_extra_code(tmp_path):
    data = b'{}'
    (tmp_path / "tokenizer.json").write_bytes(data)
    spec = {"files": {"tokenizer.json": {"size_bytes": 2, "sha256": hashlib.sha256(data).hexdigest()},
                       "model.safetensors": {"size_bytes": 999, "sha256": "not-read"}}}
    assert list(verify_tokenizer_files(tmp_path, spec)) == ["tokenizer.json"]
    (tmp_path / "tokenizer.json").write_bytes(b'[]')
    with pytest.raises(ValueError, match="hash_mismatch"):
        verify_tokenizer_files(tmp_path, spec)
    (tmp_path / "model.py").write_text("unsafe")
    with pytest.raises(ValueError, match="unexpected"):
        verify_tokenizer_files(tmp_path, spec)


@pytest.mark.parametrize("extra", [["--split", "test"], []])
def test_cli_refuses_test_or_existing_output_without_analyzing(tmp_path, monkeypatch, capsys, extra):
    output = tmp_path / "past.json"
    output.write_text("preserved")
    monkeypatch.setattr("scripts.analyze_candidates.analyze", lambda **kwargs: pytest.fail("must not analyze"))
    with pytest.raises(SystemExit):
        main(["--output", str(output), *extra])
    assert output.read_text() == "preserved"
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_failure_journal_redacts_exception_and_refuses_reuse(tmp_path, monkeypatch, capsys):
    def fail(**kwargs):
        raise RuntimeError("secret raw query and C:/private/path")
    monkeypatch.setattr("scripts.analyze_candidates.analyze", fail)
    report = tmp_path / "input.json"
    report.write_text("{}")
    output = tmp_path / "new.json"
    args = ["--report", str(report), "--output", str(output)]
    with pytest.raises(SystemExit):
        main(args)
    journal = output.with_suffix(".journal.jsonl")
    original = journal.read_text()
    assert [json.loads(line)["event"] for line in original.splitlines()] == ["started", "failed"]
    assert "secret" not in original + capsys.readouterr().out
    assert not output.exists()
    with pytest.raises(SystemExit):
        main(args)
    assert journal.read_text() == original


@pytest.mark.parametrize("model_key", ["e5", "reranker"])
def test_verified_local_tokenizers_on_synthetic_unicode_and_repeated_text(model_key):
    root = Path(__file__).resolve().parents[1]
    snapshot = root / "models" / model_key
    if not (snapshot / "tokenizer.json").is_file():
        pytest.skip("Optional verified local tokenizer fixture absent; no download")
    pytest.importorskip("transformers")
    spec = json.loads((root / "data/models/m3-models.json").read_text(encoding="utf-8"))["models"][model_key]
    tokenizer, provenance = open_tokenizer(snapshot, spec)
    text = " \t한글 e\u0301! 반복.\nrepeat?! <s> " * 150
    row = {**chunk(end=len(text)), "text": text}
    tokens = tokenize_input(tokenizer, row, "한글? repeat" if model_key == "reranker" else None)
    assert provenance["is_fast"] and tokens["tokens_before"] > 512
    assert tokens["tokens_after"] == 512
    assert tokens["after"] == tokens["before"][:len(tokens["after"])]
    for _, start, end in tokens["before"]:
        assert 0 <= start < end <= len(text)
    # Exact positions distinguish repeated text; no substring-search alignment.
    for start in (text.index("반복"), text.rindex("반복")):
        result = span_visibility(row, span(start, start + 2), tokens)
        assert result["overlapping_tokens_before"] > 0
        if start == text.rindex("반복"):
            assert result["overlapping_tokens_after"] == 0
            assert not result["all_evidence_overlapping_tokens_retained"]
