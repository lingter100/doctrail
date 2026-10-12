from copy import deepcopy

import pytest

from scripts.prepare_training import json_bytes, sha256
from scripts.validate_training_reviews import ROLES, question_hash, read_rows, validate_reviews


@pytest.fixture
def inputs():
    drafts, reviews, packs = [], [], {}
    for part, role in ROLES.items():
        doc = {"id": f"doc-{part}", "content": "A supported source statement."}
        doc["normalized_sha256"] = sha256(doc["content"].encode())
        pack = {"partition": part, "documents": [doc], "allowed_document_ids": [doc["id"]]}
        digest = sha256(json_bytes(pack))
        packs[digest] = pack
        draft = {"id": f"query-{part}", "partition": part, "question": "지원되는 사실은?",
                 "evidence": [{"document_id": doc["id"]}], "author_pack_sha256": digest,
                 "provenance": {"human_review": "pending"}}
        drafts.append(draft)
        reviews.append({
            "question_id": draft["id"], "question_sha256": question_hash(draft),
            "author_pack_sha256": digest, "document_sha256": doc["normalized_sha256"],
            "decision": "accept", "reason": "Directly supported by the quoted statement.",
            "reviewer": {"agent": role["reviewer"], "model": "gpt-6-astra",
                         "reasoning": "xhigh", "review_kind": "independent_ai"},
            "human_review": "pending",
        })
    return drafts, reviews, packs


def test_acceptance_does_not_authorize_training(inputs):
    report = validate_reviews(*inputs)
    assert report["decisions"] == {"accept": 2}
    assert report["all_ai_accepted"] is True
    assert report["human_reviewed_questions"] == 0
    assert report["training_ready"] is False


def test_revision_is_preserved(inputs):
    inputs[1][0]["decision"] = "revise"
    report = validate_reviews(*inputs)
    assert report["needs_revision"] == ["query-fit"]
    assert report["all_ai_accepted"] is False


@pytest.mark.parametrize("change", ["missing", "duplicate", "extra"])
def test_exact_review_coverage(inputs, change):
    drafts, reviews, packs = inputs
    if change == "missing":
        reviews.pop()
    else:
        event = deepcopy(reviews[0])
        if change == "extra":
            event["question_id"] = "unknown"
        reviews.append(event)
    with pytest.raises(ValueError, match="exactly once"):
        validate_reviews(drafts, reviews, packs)


@pytest.mark.parametrize("field", ["question_sha256", "author_pack_sha256", "document_sha256"])
def test_stale_receipt_rejected(inputs, field):
    inputs[1][0][field] = "0" * 64
    with pytest.raises(ValueError, match="binding mismatch"):
        validate_reviews(*inputs)


def test_draft_edit_invalidates_review(inputs):
    inputs[0][0]["question"] += " Changed"
    with pytest.raises(ValueError, match="binding mismatch"):
        validate_reviews(*inputs)


@pytest.mark.parametrize("field,value", [("agent", "train_author"), ("model", "unverified"),
                                         ("reasoning", "high")])
def test_self_or_unassigned_reviewer_rejected(inputs, field, value):
    inputs[1][0]["reviewer"][field] = value
    with pytest.raises(ValueError, match="independently assigned"):
        validate_reviews(*inputs)


def test_ai_cannot_mark_human_reviewed(inputs):
    inputs[1][0]["human_review"] = "approved"
    with pytest.raises(ValueError, match="human review pending"):
        validate_reviews(*inputs)


def test_source_tampering_rejected(inputs):
    next(iter(inputs[2].values()))["documents"][0]["content"] += " Edited"
    with pytest.raises(ValueError, match="checksum mismatch"):
        validate_reviews(*inputs)


def test_empty_reason_rejected(inputs):
    inputs[1][0]["reason"] = " "
    with pytest.raises(ValueError, match="reason is required"):
        validate_reviews(*inputs)


def test_parsed_rows_and_hash_share_one_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "reviews.jsonl"
    first, second = b'{"decision":"revise"}\n', b'{"decision":"accept"}\n'
    reads = []

    def changing_read(self):
        reads.append(self)
        return first if len(reads) == 1 else second

    monkeypatch.setattr(type(path), "read_bytes", changing_read)
    rows, hashes = read_rows([path])
    assert reads == [path]
    assert rows == [{"decision": "revise"}]
    assert hashes == {"reviews.jsonl": sha256(first)}
