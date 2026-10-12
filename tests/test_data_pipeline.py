import hashlib

import pytest

from scripts.prepare_pilot import normalize_markdown, verified_processed
from scripts.validate_splits import validate


def test_normalizer_preserves_meaningful_tooltip_text():
    source = b'---\ntitle: ignored\n---\nUse {{< glossary_tooltip text="Secret" term_id="secret" >}} now.\n'
    assert normalize_markdown(source) == "Use Secret now.\n"


def test_split_validator_rejects_translations_across_splits():
    with pytest.raises(ValueError, match="crosses splits"):
        validate(
            [
                {"id": "en", "family_id": "same", "sha256": "a", "split": "train"},
                {"id": "ko", "family_id": "same", "sha256": "b", "split": "test"},
            ],
            [],
        )


def test_split_validator_rejects_evidence_crossing_splits():
    with pytest.raises(ValueError, match="evidence"):
        validate(
            [{"id": "a", "family_id": "a", "sha256": "x", "split": "train"}],
            [{"id": "q", "query": "why", "split": "test", "relevant_document_ids": ["a"]}],
        )


def test_split_validator_rejects_invented_human_review():
    with pytest.raises(ValueError, match="reviewer"):
        validate(
            [],
            [
                {
                    "id": "q",
                    "query": "why",
                    "split": "smoke",
                    "relevant_document_ids": [],
                    "human_review": "approved",
                }
            ],
        )


def test_split_validator_rejects_cross_split_evidence_annotation():
    with pytest.raises(ValueError, match="annotation"):
        validate(
            [
                {"id": "smoke-doc", "family_id": "a", "sha256": "a", "split": "smoke"},
                {"id": "test-doc", "family_id": "b", "sha256": "b", "split": "test"},
            ],
            [
                {
                    "id": "q",
                    "query": "why",
                    "split": "smoke",
                    "relevant_document_ids": ["smoke-doc"],
                    "evidence": [{"document_id": "test-doc", "quote": "leaked"}],
                }
            ],
        )


def test_evaluation_rejects_processed_corpus_drift(tmp_path):
    raw = b"Grounded source text.\n"
    raw_path = tmp_path / "data/raw/kubernetes-pilot/doc.md"
    processed = tmp_path / "data/processed/kubernetes-pilot/doc.md"
    raw_path.parent.mkdir(parents=True)
    processed.parent.mkdir(parents=True)
    raw_path.write_bytes(raw)
    processed.write_bytes(b"Silently changed content.\n")
    with pytest.raises(ValueError, match="drift"):
        verified_processed({"id": "doc", "sha256": hashlib.sha256(raw).hexdigest()}, tmp_path)
