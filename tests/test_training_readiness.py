"""Synthetic readiness boundary checks, not semantic reviews or real token runs."""

import copy
import json
from types import SimpleNamespace

import pytest

from scripts import prepare_training as pilot
from scripts import prepare_training_ready as ready


class Encoding(dict):
    def sequence_ids(self):
        return [None] + [0] * (len(self["input_ids"]) - 2) + [None]


class CharacterTokenizer:
    """Deliberately simple synthetic fast-tokenizer substitute."""

    def __call__(self, text, truncation=False, max_length=None, **kwargs):
        chars = text[:max_length - 2] if truncation else text
        return Encoding(input_ids=[1] + [ord(c) for c in chars] + [2],
                        offset_mapping=[(0, 0)] + [(i, i + 1) for i in range(len(chars))] + [(0, 0)])


def chunk(identifier, family, text, ordinal=0, start=0):
    return {"document_id": identifier, "family_id": family, "chunk_id": f"{identifier}:{ordinal}",
            "start_offset": start, "end_offset": start + len(text),
            "text": text, "text_sha256": pilot.sha256(text.encode())}


@pytest.fixture
def corpus():
    plan = {"split": {"seed": "doctrail-m4-train-v1"}}
    fit = [f"family-{i}" for i in range(100)
           if pilot.partition_for(f"family-{i}", plan) == "fit"]
    positive = chunk("positive", fit[0], "The required fact is blue.")
    negatives = [chunk("negative", fit[1], f"Different synthetic fact {i}.", i)
                 for i in range(4)]
    chunks = {row["chunk_id"]: row for row in [positive, *negatives]}
    questions, drafts, candidates = [], [], []
    for index in range(1, 65):
        identifier = f"m4-fit-{index:03d}"
        draft = {"id": identifier, "partition": "fit", "question": f"Which color fact {index}?"}
        drafts.append(draft)
        question = {**draft, "evidence": [{"document_id": "positive", "start_offset": 0,
                                          "end_offset": len(positive["text"])}],
                    "positive_chunk_ids": [positive["chunk_id"]]}
        questions.append(question)
        candidates.extend({**pilot.compact_chunk(c), "question_id": identifier,
                           "partition": "fit", "rank": rank, "score": 1 / rank,
                           "status": "unreviewed", "quarantine_reasons": [],
                           "negative_label": None, "semantic_review": "pending",
                           "human_review": "pending", "eligible_for_training": False}
                          for rank, c in enumerate(negatives, 1))
    packs = ready.build_review_packs(questions, drafts, candidates, chunks, plan, "a" * 64)
    hashes = {shard: pilot.fingerprint(pack) for shard, pack in packs.items()}
    events = [{**ready.event_binding(pack, item, candidate, hashes[shard]), "label": "negative",
               "reason": "Synthetic test judgment: unrelated fixture fact."}
              for shard, pack in packs.items() for item in pack["items"]
              for candidate in item["candidates"]]
    return SimpleNamespace(plan=plan, chunks=chunks, questions=questions, drafts=drafts,
                           candidates=candidates, packs=packs, events=events)


@pytest.fixture
def tokens(corpus):
    spec = {"repo_id": "synthetic", "revision": "synthetic",
            "files": {"tokenizer.json": {"sha256": "b" * 64}}}
    provenance = {"verified_files_sha256": {"tokenizer.json": "b" * 64},
                  "is_fast": True, "truncation_side": "right", "repo_id": "synthetic",
                  "revision": "synthetic", "class": "CharacterTokenizer",
                  "transformers_version": "synthetic", "tokenizers_version": "synthetic"}
    bindings, sources = {"data/example.json": "c" * 64}, {"scripts/example.py": "d" * 64}
    negative = ready.validate_negative_reviews(corpus.packs, corpus.events)
    receipt = ready.token_payload(corpus.questions, corpus.chunks, corpus.packs,
                                  CharacterTokenizer(), provenance, bindings, sources,
                                  negative["selected"])
    return SimpleNamespace(spec=spec, bindings=bindings, sources=sources, receipt=receipt,
                           negative=negative)


def validate_tokens(corpus, tokens):
    return ready.validate_token_receipt(tokens.receipt, corpus.questions, corpus.chunks,
                                        corpus.packs, tokens.bindings, tokens.sources, tokens.spec)


def reseal(receipt):
    receipt["payload_sha256"] = pilot.fingerprint(
        {key: value for key, value in receipt.items() if key != "payload_sha256"})


def test_pack_exact_shards_context_and_first_four(corpus):
    assert len(corpus.packs["A"]["items"]) == len(corpus.packs["B"]["items"]) == 32
    assert corpus.packs["B"]["items"][0]["question"]["id"] == "m4-fit-033"
    item = corpus.packs["A"]["items"][0]
    assert [c["rank"] for c in item["candidates"]] == [1, 2, 3, 4]
    assert all(c["text"] for c in item["candidates"] + item["positives"])
    assert len(corpus.events) == 256


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "extra"])
def test_review_coverage_exact(corpus, mutation):
    if mutation == "missing":
        corpus.events.pop()
    elif mutation == "duplicate":
        corpus.events.append(copy.deepcopy(corpus.events[0]))
    else:
        corpus.events[0]["candidate_chunk_id"] = "injected:0"
    with pytest.raises(ValueError, match="coverage"):
        ready.validate_negative_reviews(corpus.packs, corpus.events)


@pytest.mark.parametrize("field,value", [
    ("question_sha256", "e" * 64), ("compiled_question_sha256", "e" * 64),
    ("positive_context_sha256", "e" * 64), ("candidate_sha256", "e" * 64),
    ("candidate_text_sha256", "e" * 64), ("review_pack_sha256", "e" * 64),
    ("readiness_plan_sha256", "e" * 64), ("human_review", "approved"),
    ("reviewer", ready.reviewer("wrong_agent")),
])
def test_review_hashes_roles_and_human_boundary(corpus, field, value):
    corpus.events[0][field] = value
    with pytest.raises(ValueError, match="binding"):
        ready.validate_negative_reviews(corpus.packs, corpus.events)


def test_nonnegative_never_enters_loss_and_no_pool_expansion(corpus):
    for event, label in zip(corpus.events[:4], ["relevant", "ambiguous", "unknown", "negative"]):
        event["label"] = label
    result = ready.validate_negative_reviews(corpus.packs, corpus.events)
    assert result["shortfalls"] == ["m4-fit-001"]
    assert [c["chunk_id"] for c in result["selected"]["m4-fit-001"]] == ["negative:3"]


def test_same_document_distinct_chunks_allowed_and_rank_frozen(corpus):
    corpus.events[0]["label"] = "relevant"
    result = ready.validate_negative_reviews(corpus.packs, corpus.events)
    assert [c["chunk_id"] for c in result["selected"]["m4-fit-001"]] == ["negative:1", "negative:2"]
    assert not result["shortfalls"]


@pytest.mark.parametrize("label,reason", [("unreviewed", "reason"), ("negative", " ")])
def test_explicit_label_and_reason_required(corpus, label, reason):
    corpus.events[0].update(label=label, reason=reason)
    with pytest.raises(ValueError, match="label and reason"):
        ready.validate_negative_reviews(corpus.packs, corpus.events)


def test_cross_partition_or_candidate_hash_rejected(corpus):
    for field, value in (("partition", "calibration"), ("text_sha256", "f" * 64)):
        candidates = copy.deepcopy(corpus.candidates)
        candidates[0][field] = value
        with pytest.raises(ValueError, match="partition mismatch"):
            ready.build_review_packs(corpus.questions, corpus.drafts, candidates, corpus.chunks,
                                      corpus.plan, "a" * 64)


def test_missing_fit_or_candidate_never_silently_shrinks(corpus):
    with pytest.raises(ValueError, match="64 fit"):
        ready.build_review_packs(corpus.questions[1:], corpus.drafts, corpus.candidates,
                                  corpus.chunks, corpus.plan, "a" * 64)
    with pytest.raises(ValueError, match="first-four"):
        ready.build_review_packs(corpus.questions, corpus.drafts, corpus.candidates[1:],
                                  corpus.chunks, corpus.plan, "a" * 64)


def test_tokens_model_free_receipt_replay(corpus, tokens):
    result = validate_tokens(corpus, tokens)
    assert not result["failures"]
    assert len(result["selected"]) == 64


def test_token_receipt_tamper(corpus, tokens):
    tokens.receipt["questions"][0]["query_tokens"] += 1
    with pytest.raises(ValueError, match="drift"):
        validate_tokens(corpus, tokens)


@pytest.mark.parametrize("target", ["inputs_sha256", "source_sha256_lf", "tokenizer"])
def test_token_replay_checks_actual_inputs_and_source(corpus, tokens, target):
    tokens.receipt[target] = {}
    reseal(tokens.receipt)
    with pytest.raises(ValueError, match="drift"):
        validate_tokens(corpus, tokens)


def test_positive_truncation_blocks_without_removing_question(corpus, tokens):
    check = tokens.receipt["questions"][0]
    visibility = check["positives"][0]["visibility"]
    visibility.update(all_evidence_overlapping_tokens_retained=False,
                      overlapping_tokens_after=0,
                      evidence_tokens_lost_to_truncation=visibility["overlapping_tokens_before"])
    check["selected_positive_chunk_id"] = None
    reseal(tokens.receipt)
    result = validate_tokens(corpus, tokens)
    assert result["failures"] == ["m4-fit-001"]
    assert len(tokens.receipt["questions"]) == 64


def test_query_truncation_blocks(corpus, tokens):
    tokens.receipt["questions"][0]["query_tokens"] = 513
    reseal(tokens.receipt)
    assert validate_tokens(corpus, tokens)["failures"] == ["m4-fit-001"]


def test_token_positive_false_retention_flag_rejected(corpus, tokens):
    tokens.receipt["questions"][0]["positives"][0]["visibility"]["overlapping_tokens_after"] = 0
    reseal(tokens.receipt)
    with pytest.raises(ValueError, match="visibility"):
        validate_tokens(corpus, tokens)


def test_earliest_retained_ordinal_not_lexicographic(corpus, tokens):
    question = copy.deepcopy(corpus.questions[0])
    old = corpus.chunks["positive:0"]
    chunks = {**corpus.chunks, "positive:2": {**old, "chunk_id": "positive:2"},
              "positive:10": {**old, "chunk_id": "positive:10"}}
    question["positive_chunk_ids"] = ["positive:10", "positive:2"]
    receipt = ready.token_payload([question], chunks, corpus.packs, CharacterTokenizer(),
                                  tokens.receipt["tokenizer"], tokens.bindings, tokens.sources)
    assert receipt["questions"][0]["selected_positive_chunk_id"] == "positive:2"


def test_quote_straddling_truncation_loses_final_token():
    text = "x" * 498 + "quoted fact"
    source = chunk("synthetic", "family", text)
    span = {"document_id": "synthetic", "start_offset": 498, "end_offset": len(text)}
    encoded = ready.tokenize_input(CharacterTokenizer(), source)
    visibility = ready.span_visibility(source, span, encoded)
    assert visibility["overlapping_tokens_after"] > 0
    assert visibility["all_evidence_overlapping_tokens_retained"] is False


def test_negative_truncation_blocks_whole_manifest_no_substitution(corpus, tokens):
    token_result = validate_tokens(corpus, tokens)
    candidate = tokens.receipt["candidates"][0]
    candidate.update(tokens_before=513, tokens_after=512, truncated=True)
    context = {"questions": corpus.questions, "bindings": tokens.bindings, "sources": tokens.sources,
               "pilot_report": {"pilot_data_gates": {"synthetic": True}, "counts": {}}}
    manifest = ready.readiness_manifest(context, {"all_ai_accepted": True, "decisions": {"accept": 64}},
                                       tokens.negative, tokens.receipt, token_result, "a" * 64)
    assert not manifest["data_ready"] and not manifest["probe_allowed"]
    assert manifest["training_ready"] is False and manifest["resource_probe_result"] == "not_run"
    assert len(manifest["triplets"]) == 64
    assert manifest["triplets"][0]["negatives"][0]["chunk_id"] == "negative:0"


@pytest.mark.parametrize("value", [{"text": "full source"}, {"x": "C:\\Users\\private"},
                                   {"x": "/home/private"}])
def test_public_artifact_text_and_personal_path_rejected(value):
    with pytest.raises(ValueError):
        ready.public_safe(value)


def test_no_overwrite_and_exact_lf_replay(tmp_path):
    path = tmp_path / "original-v1.json"
    raw = pilot.json_bytes({"keep": "한글"})
    pilot.write_or_verify(path, raw)
    pilot.write_or_verify(path, raw, verify=True)
    with pytest.raises(FileExistsError):
        pilot.write_or_verify(path, b"modified")
    with pytest.raises(ValueError, match="Replay mismatch"):
        pilot.write_or_verify(path, raw.replace(b"\n", b"\r\n"), verify=True)
    assert path.read_bytes() == raw
    assert json.loads(raw) == {"keep": "한글"}


def test_missing_positive_review_fails_closed():
    with pytest.raises(ValueError, match="78 plus exactly 2"):
        ready.validate_positive_reviews([], [], {})


@pytest.mark.parametrize("is_ready", [True, False])
def test_training_loader_requires_exact_saved_manifest_and_all_data_gates(
        tmp_path, monkeypatch, is_ready):
    manifest = {"data_ready": is_ready, "probe_allowed": is_ready, "training_ready": False}
    context = {"questions": [], "chunks": {}, "plan": {"synthetic": True}}
    monkeypatch.setattr(ready, "replay_manifest", lambda args, root: (manifest, context))
    args = SimpleNamespace(output=tmp_path / "manifest.json")
    args.output.write_bytes(pilot.json_bytes(manifest))
    if is_ready:
        result = ready.load_ready_data(args, tmp_path)
        assert result["manifest"]["training_ready"] is False
    else:
        with pytest.raises(ValueError, match="readiness gates failed"):
            ready.load_ready_data(args, tmp_path)
    args.output.write_bytes(pilot.json_bytes({**manifest, "tampered": True}))
    with pytest.raises(ValueError, match="Replay mismatch"):
        ready.load_ready_data(args, tmp_path)
