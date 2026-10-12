"""Synthetic corruption/selection checks; these are not real semantic/tokenizer reviews."""

import copy
from types import SimpleNamespace

import pytest
from test_training_readiness import CharacterTokenizer, chunk, corpus  # noqa: F401

from scripts import prepare_training as pilot
from scripts import prepare_training_ready as v1
from scripts import prepare_training_ready_v2 as ready
from scripts.validate_training_reviews import question_hash


class SyntheticTokenizer(CharacterTokenizer):
    def __call__(self, text, **kwargs):
        result = super().__call__(text, **kwargs)
        size = len(result["input_ids"])
        result["special_tokens_mask"] = [1] + [0] * (size - 2) + [1]
        result["attention_mask"] = [1] * size
        return result

    def decode(self, ids, **kwargs):
        return "".join(chr(i) for i in ids[1:-1])


@pytest.fixture
def example(corpus):  # noqa: F811
    old_labels = copy.deepcopy(corpus.events)
    for event in old_labels:
        if event["question_id"] == ready.TARGET:
            event["label"] = "ambiguous"
    negative = v1.validate_negative_reviews(corpus.packs, old_labels)
    target = next(c for c in corpus.candidates if c["question_id"] == ready.TARGET)
    candidates = copy.deepcopy(corpus.candidates)
    extra = []
    for i in range(4):
        c = chunk("supplement", target["family_id"], "x" * (650 if i == 0 else 25), i)
        corpus.chunks[c["chunk_id"]] = c
        extra.append({**target, **pilot.compact_chunk(c), "rank": i + 5})
    candidates.extend(extra)
    provenance = {"verified_files_sha256": {"tokenizer.json": "b" * 64},
                  "is_fast": True, "truncation_side": "right", "repo_id": "synthetic",
                  "revision": "synthetic", "class": "SyntheticTokenizer",
                  "transformers_version": "synthetic", "tokenizers_version": "synthetic"}
    plan = {"supplemental_negative_review": {"question_id": ready.TARGET,
            "skip_first_eligible": 4, "take_next_eligible": 4, "selected_candidates": extra,
            "reviewer": v1.reviewer("m4_supp_author")},
            "actual_tokenization": {"tokenizer_provenance": provenance},
            "actual_truncated_review": {"pack_path": ".local/truncated.json"}}
    manifest = {"triplets": [{"question_id": qid, "negatives": refs, "positive": {},
                              "eligible_for_training": False}
                             for qid, refs in negative["selected"].items()],
                "gates": {"pilot_data_gates": True, "all_positive_reviews_accepted": True,
                          "all_query_and_positive_tokens_retained": True},
                "counts": {"fit": {"questions": 64}, "calibration": {"questions": 16}},
                "calibration": [], "excluded_rows_and_reasons": {"negative_truncation": ["frozen"]},
                "negative_review_labels": negative["labels"]}
    context = {"v2_plan": plan, "v2_plan_sha256": "a" * 64, "review_packs": corpus.packs,
               "chunks": corpus.chunks, "plan": corpus.plan, "v1_manifest": manifest,
               "bindings": {"input.json": "b" * 64}, "sources": {"source.py": "c" * 64},
               "v1_receipt": {"questions": [], "candidates": []}}
    pack = ready.supplement_pack(context, candidates)
    context["supplement_pack"] = pack
    events = [{**v1.event_binding(pack, item, c), "review_scope": "supplemental_full_context",
               "label": "negative", "reason": "Synthetic unrelated fact."}
              for item in pack["items"] for c in item["candidates"]]
    selected = ready.select_negatives(manifest, pack, events)
    context["full_reviews"] = {(e["question_id"], e["candidate_chunk_id"]): e
                               for e in old_labels + events}
    context["supplement_labels"] = {"negative": 4}
    views = {cid: ready.actual_view(SyntheticTokenizer(), corpus.chunks[cid]["text"])
             for cid in ready.selected_ids(selected)}
    payload = ready.token_receipt(context, selected, views, provenance)
    actual_pack = ready.truncated_pack(context, selected, payload["candidates"], views,
                                       payload["payload_sha256"])
    receipt = ready.finalize_receipt(context, selected, payload, actual_pack)
    digest = pilot.fingerprint(receipt)
    actual_events = [{**b, "token_receipt_sha256": digest,
                      "readiness_plan_sha256": context["v2_plan_sha256"],
                      "review_pack_sha256": receipt["actual_review_pack_sha256"],
                      "label": "negative", "reason": "Synthetic retained input unrelated."}
                     for b in receipt["actual_review_bindings"]]
    spec = {"repo_id": "synthetic", "revision": "synthetic",
            "files": {"tokenizer.json": {"sha256": "b" * 64}}}
    return SimpleNamespace(context=context, pack=pack, events=events, selected=selected,
                           candidates=candidates, views=views, receipt=receipt,
                           actual_pack=actual_pack, actual_events=actual_events,
                           digest=digest, spec=spec)


def test_additive_selection_preserves_63_and_first_two_rank(example):
    assert [c["rank"] for c in example.pack["items"][0]["candidates"]] == [5, 6, 7, 8]
    assert [c["chunk_id"] for c in example.selected[ready.TARGET]] == ["supplement:0", "supplement:1"]
    for triplet in example.context["v1_manifest"]["triplets"]:
        if triplet["question_id"] != ready.TARGET:
            assert triplet["negatives"] == example.selected[triplet["question_id"]]


@pytest.mark.parametrize("mutation", ["missing", "extra", "reorder", "wrong_role", "wrong_hash"])
def test_supplement_review_fail_closed(example, mutation):
    events = example.events
    if mutation == "missing":
        events.pop()
    elif mutation == "extra":
        events.append(copy.deepcopy(events[0]))
    elif mutation == "reorder":
        events.reverse()
    elif mutation == "wrong_role":
        events[0]["reviewer"] = v1.reviewer("train_author")
    else:
        events[0]["candidate_text_sha256"] = "d" * 64
    with pytest.raises(ValueError):
        ready.select_negatives(example.context["v1_manifest"], example.pack, events)


def test_new_rank_or_quarantine_cannot_enter_supplement(example):
    example.candidates[-1]["rank"] = 1
    with pytest.raises(ValueError, match="next four"):
        ready.supplement_pack(example.context, example.candidates)


def test_truncation_is_reviewed_without_selecting_shorter_candidate(example):
    assert example.actual_pack["items"][0]["candidate"]["chunk_id"] == "supplement:0"
    assert len(example.actual_events) == 1
    assert "supplement:0" in [c["chunk_id"] for c in example.selected[ready.TARGET]]
    ready.validate_tokens(example.context, example.selected, example.receipt, example.spec)
    ready.validate_actual_reviews(example.context, example.selected, example.receipt,
                                   example.digest, example.actual_events)
    item = example.actual_pack["items"][0]
    assert item["full_context_review_sha256"] == question_hash(item["full_context_review"])


@pytest.mark.parametrize("field", ["candidate_text_sha256", "question_sha256", "positive_context_sha256",
                                  "full_context_review_sha256", "model_input_sha256", "token_view_sha256",
                                  "token_receipt_sha256", "review_pack_sha256", "readiness_plan_sha256"])
def test_actual_review_all_context_hashes_bound(example, field):
    example.actual_events[0][field] = "f" * 64
    with pytest.raises(ValueError, match="binding"):
        ready.validate_actual_reviews(example.context, example.selected, example.receipt,
                                       example.digest, example.actual_events)


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong_question", "human_approved", "author_role"])
def test_actual_review_exact_coverage_and_independence(example, mutation):
    events = example.actual_events
    if mutation == "missing":
        events.clear()
    elif mutation == "extra":
        events.append(copy.deepcopy(events[0]))
    elif mutation == "wrong_question":
        events[0]["question_id"] = "m4-fit-001"
    elif mutation == "human_approved":
        events[0]["human_review"] = "approved"
    else:
        events[0]["reviewer"] = v1.reviewer("train_author")
    with pytest.raises(ValueError):
        ready.validate_actual_reviews(example.context, example.selected, example.receipt,
                                       example.digest, events)


@pytest.mark.parametrize("label", ["relevant", "ambiguous", "unknown"])
def test_nonnegative_actual_input_blocks_entire_denominator(example, label):
    example.actual_events[0]["label"] = label
    result = ready.build_manifest(example.context, example.selected, example.receipt, example.actual_events)
    assert not result["data_ready"] and not result["probe_allowed"]
    assert len(result["triplets"]) == 64 and result["counts"]["calibration"]["questions"] == 16
    assert not any(t["eligible_for_training"] for t in result["triplets"])
    assert result["v1_failure_preserved"] == {"negative_truncation": ["frozen"]}
    assert result["triplets"][47]["negatives"] == example.selected[ready.TARGET]


@pytest.mark.parametrize("mutation", ["id", "offset", "mask", "source_prefix"])
def test_actual_view_corruption_rejected(example, mutation):
    view = example.views["supplement:0"]
    if mutation == "id":
        view["retained_input_ids"][3] += 1
    elif mutation == "offset":
        view["retained_offsets"][3] = [9999, 10000]
    elif mutation == "mask":
        view["retained_attention_mask"][3] = 0
    else:
        view["offset_visible_source"]["text"] += "invented"
    with pytest.raises(ValueError):
        ready.validate_view(view, "passage: " + "x" * 650)


@pytest.mark.parametrize("mutation", ["selection", "missing", "reorder", "source", "provenance"])
def test_public_replay_detects_resealed_drift(example, mutation):
    payload = example.receipt["payload"]
    if mutation == "selection":
        payload["selected_negatives"][ready.TARGET].reverse()
    elif mutation == "missing":
        payload["candidates"].pop()
    elif mutation == "reorder":
        payload["candidates"].reverse()
    elif mutation == "source":
        payload["source_sha256_lf"] = {}
    else:
        payload["tokenizer"]["class"] = "WrongTokenizer"
    payload["payload_sha256"] = pilot.fingerprint({k: v for k, v in payload.items() if k != "payload_sha256"})
    with pytest.raises(ValueError):
        ready.validate_tokens(example.context, example.selected, example.receipt, example.spec)


def test_local_pack_required_only_for_runtime_and_tamper_rejected(example, tmp_path):
    assert not ready.verify_local_pack(example.context, example.selected, example.receipt, tmp_path)
    with pytest.raises(ValueError, match="required"):
        ready.verify_local_pack(example.context, example.selected, example.receipt, tmp_path, required=True)
    path = tmp_path / ".local/truncated.json"
    pilot.write_or_verify(path, pilot.json_bytes(example.actual_pack), False)
    assert ready.verify_local_pack(example.context, example.selected, example.receipt, tmp_path, required=True)
    example.actual_pack["items"][0]["actual_view"]["decoded_retained_input"] += "changed"
    path.write_bytes(pilot.json_bytes(example.actual_pack))
    with pytest.raises(ValueError, match="hash drift"):
        ready.verify_local_pack(example.context, example.selected, example.receipt, tmp_path)


@pytest.mark.parametrize("existing", ["receipt", "pack"])
def test_token_output_conflict_leaves_other_output_absent(tmp_path, existing):
    receipt, pack = tmp_path / "receipt.json", tmp_path / "pack.json"
    path = receipt if existing == "receipt" else pack
    path.write_bytes(b"preserve")
    with pytest.raises(ValueError, match="already exists"):
        ready.write_token_outputs(receipt, {}, pack, {}, False)
    assert path.read_bytes() == b"preserve"
    assert not (pack if existing == "receipt" else receipt).exists()


def test_token_verify_does_not_write_on_success_or_failure(tmp_path):
    receipt, pack = tmp_path / "receipt.json", tmp_path / "pack.json"
    ready.write_token_outputs(receipt, {"r": 1}, pack, {"p": 1}, False)
    before = (receipt.read_bytes(), pack.read_bytes(), receipt.stat().st_mtime_ns, pack.stat().st_mtime_ns)
    ready.write_token_outputs(receipt, {"r": 1}, pack, {"p": 1}, True)
    with pytest.raises(ValueError, match="Replay mismatch"):
        ready.write_token_outputs(receipt, {"r": 1}, pack, {"p": 2}, True)
    assert before == (receipt.read_bytes(), pack.read_bytes(), receipt.stat().st_mtime_ns, pack.stat().st_mtime_ns)
