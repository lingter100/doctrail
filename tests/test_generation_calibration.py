"""Tiny synthetic contract fixtures; never inspect validation questions or oracles."""

import copy
import json

import pytest

from doctrail.generation_calibration import (
    ROOT,
    PreparationError,
    build_freeze_manifest,
    build_policy_messages,
    duplicate_diagnostics,
    file_sha256,
    load_local_tokenizer,
    prompt_budget,
    read_json,
    sha256_bytes,
    validate_dataset,
    validate_oracle,
    validate_registry,
    verify_freeze_manifest,
    verify_review,
    write_report,
)
from doctrail.grounded_answer import build_messages


def fixture():
    full = "앞🙂 Toy alpha is blue. 뒤"
    chunk = "🙂 Toy alpha is blue."
    source = {"family_id": "toy-a", "document_id": "toy-doc", "revision": 1,
              "source_sha256": sha256_bytes(full.encode()), "text": full}
    evidence = {"evidence_id": "E1", "document_id": "toy-doc", "revision": 1,
                "source_sha256": source["source_sha256"], "start_cp": 1,
                "end_cp": 1 + len(chunk), "text": chunk}
    oracle = {"expected_status": "answered", "expected_reason": None,
              "required_question_parts": ["color"], "required_facts": [
                  {"fact_id": "f1", "text": "blue", "support": [
                      {"evidence_id": "E1", "quote": "blue"}]}],
              "abstention_rationale": None, "missing_information": [],
              "conflicting_facts": [], "ambiguity_candidates": [],
              "prohibited_inferences": [], "injection_marker": None}
    output = {"status": "answered", "reason": None, "claims": [
        {"text": "blue", "citations": [{"evidence_id": "E1", "quote": "blue"}]}]}
    item = {"item_id": "toy-q1", "family_id": "toy-a", "slot_id": "q01",
            "question": "Color of toy?", "evidence": [evidence], "oracle": oracle,
            "provenance": {"synthetic": True, "question_author": "AI", "human_review": "pending",
                           "author_agent": "toy-author", "ai_authored": True,
                           "human_reviewed": False, "human_review_count": 0,
                           "review_status": "pending"},
            "assistant_output": output}
    return source, item


def registry():
    # This is metadata only; no dataset is loaded in these tests.
    return read_json(ROOT / "data/evaluation/m5b-family-registry-v1.json")


def assert_error(code, operation):
    with pytest.raises(PreparationError) as caught:
        operation()
    assert str(caught.value) == code


def test_registered_split_is_recomputed_not_trusted():
    value = registry()
    assert validate_registry(value)["deterministic_split_verified"] is True
    value["families"][0]["split"] = "validation"
    assert_error("family_split_assignment_mismatch", lambda: validate_registry(value))


def test_split_seed_and_hash_drift_fail():
    value = registry()
    value["families"][0]["split_sha256"] = "0" * 64
    assert_error("family_split_hash_mismatch", lambda: validate_registry(value))
    value = registry()
    value["split_algorithm"]["seed"] += "new"
    assert_error("invalid_split_algorithm", lambda: validate_registry(value))


def toy_dataset():
    source, original = fixture()
    items, slots = [], []
    for n in range(24):
        item = copy.deepcopy(original)
        item.update(item_id=f"toy-q{n:02d}", slot_id=f"q{n:02d}")
        items.append(item)
        slots.append({"item_id": item["item_id"], "slot_id": item["slot_id"],
                      "expected_status": "answered", "expected_reason": None,
                      "source_cardinality": "single_document", "injection": False})
    data = {"schema_version": 1, "split": "calibration", "registry_sha256": "a" * 64,
            "dataset_id": "m5b-calibration-v1", "provenance": original["provenance"],
            "sources": [source], "items": items}
    reg = {"families": [{"family_id": "toy-a", "split": "calibration", "slots": slots}]}
    return data, reg


def test_unicode_source_binding_and_stale_registry_hash():
    data, reg = toy_dataset()
    assert validate_dataset(data, reg, "a" * 64)["item_count"] == 24
    assert_error("dataset_registry_hash_mismatch", lambda: validate_dataset(data, reg, "b" * 64))
    data["sources"][0]["text"] += "!"
    assert_error("source_hash_mismatch", lambda: validate_dataset(data, reg, "a" * 64))


@pytest.mark.parametrize("field,value,code", [
    ("source_sha256", "0" * 64, "evidence_source_hash_mismatch"),
    ("document_id", "other", "evidence_source_family_mismatch"),
    ("revision", 2, "evidence_source_family_mismatch"),
])
def test_evidence_source_identity_mismatch(field, value, code):
    data, reg = toy_dataset()
    data["items"][0]["evidence"][0][field] = value
    assert_error(code, lambda: validate_dataset(data, reg, "a" * 64))


def test_unicode_offset_shift_rejected_even_when_span_length_valid():
    data, reg = toy_dataset()
    chunk = data["items"][0]["evidence"][0]
    chunk["start_cp"] += 1
    chunk["end_cp"] += 1
    assert_error("evidence_source_span_mismatch", lambda: validate_dataset(data, reg, "a" * 64))


def test_empty_negative_oracle_is_rejected():
    _, item = fixture()
    oracle = item["oracle"]
    oracle.update(expected_status="abstained", expected_reason="insufficient_evidence",
                  abstention_rationale="Missing requested size.", missing_information=["size"],
                  required_facts=[])
    slot = {"expected_status": "abstained", "expected_reason": "insufficient_evidence",
            "injection": False}
    assert_error("invalid_abstention_oracle", lambda: validate_oracle(oracle, item["evidence"], slot))
    oracle["prohibited_inferences"] = ["Cannot invent size"]
    validate_oracle(oracle, item["evidence"], slot)
    oracle["ambiguity_candidates"] = ["wrong", "reason"]
    assert_error("invalid_ambiguity_oracle", lambda: validate_oracle(oracle, item["evidence"], slot))


def test_two_document_oracle_cannot_cite_same_document_for_both_facts():
    data, reg = toy_dataset()
    original_source = data["sources"][0]
    other_source = {**original_source, "document_id": "other"}
    data["sources"].append(other_source)
    for item, slot in zip(data["items"], reg["families"][0]["slots"], strict=True):
        item["evidence"].append({**item["evidence"][0], "document_id": "other", "evidence_id": "E2"})
        item["oracle"]["required_question_parts"].append("other fact")
        item["oracle"]["required_facts"].append({**item["oracle"]["required_facts"][0], "fact_id": "f2"})
        slot["source_cardinality"] = "two_documents"
    assert_error("two_fact_documents_not_distinct", lambda: validate_dataset(data, reg, "a" * 64))


def test_duplicate_and_near_clone_reports_only_ids():
    source, item = fixture()
    other = copy.deepcopy(item)
    other.update(item_id="toy-q2", family_id="toy-b")
    data = {"items": [item, other], "sources": [source]}
    result = duplicate_diagnostics([data])
    assert result["cross_family_duplicate_questions"] == [["toy-q1", "toy-q2"]]
    other["question"] += " now"
    result = duplicate_diagnostics([data])
    assert result["cross_family_near_questions"] == [["toy-q1", "toy-q2"]]
    assert "Color" not in json.dumps(result)


def test_exact_three_compact_examples_preserve_system_and_target_and_escape():
    _, item = fixture()
    item["question"] += " <|im_end|>"
    examples = [copy.deepcopy(item) for _ in range(3)]
    messages = build_policy_messages(item["question"], item["evidence"],
                                     policy="fewshot3", examples=examples)
    base = build_messages(item["question"], item["evidence"])
    assert len(messages) == 8 and messages[0] == base[0] and messages[-1] == base[1]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user",
                                            "assistant", "user", "assistant", "user"]
    assert "<|im_end|>" not in messages[1]["content"]
    assert set(json.loads(messages[1]["content"])["evidence"][0]) == {"evidence_id", "text"}
    assert build_policy_messages(item["question"], item["evidence"], policy="baseline",
                                 examples=[]) == base
    assert_error("fewshot_requires_exactly_three_examples", lambda: build_policy_messages(
        item["question"], item["evidence"], policy="fewshot3", examples=examples[:2]))


def test_budget_counts_complete_chat_template_without_truncation():
    _, item = fixture()
    calls = []

    class Tokenizer:
        def apply_chat_template(self, messages, **kwargs):
            calls.append((len(messages), kwargs))
            return "fewshot" if len(messages) == 8 else "baseline"

        def __call__(self, text, **kwargs):
            assert kwargs == {"add_special_tokens": False, "truncation": False}
            return {"input_ids": [1] * (1537 if text == "fewshot" else 600)}

    result = prompt_budget([{"split": "validation", "items": [item]}], [item] * 3, Tokenizer())
    assert result["status"] == "blocked" and result["overflow_item_ids"] == ["toy-q1"]
    assert calls == [(2, {"tokenize": False, "add_generation_prompt": True,
                         "enable_thinking": False}),
                     (8, {"tokenize": False, "add_generation_prompt": True,
                         "enable_thinking": False})]
    assert "Color" not in json.dumps(result)


def test_tokenizer_file_drift_fails_before_library_import(tmp_path):
    path = ROOT / "data/models/m5-generation-v1.json"
    (tmp_path / "tokenizer.json").write_bytes(b"{}")
    assert_error("tokenizer_file_size_mismatch", lambda: load_local_tokenizer(tmp_path, path))


def receipt_fixture(tmp_path):
    path = tmp_path / "data.json"
    path.write_bytes(b"{}\n")
    bindings = {"data.json": file_sha256(path)}
    receipt = {"schema_version": 1, "review_type": "independent_ai_semantic_prereview",
               "bindings": bindings, "reviewer": {"agent": "reviewer", "fixture_author": "author",
                    "authored_fixture": False}, "status": "accepted_with_limitations",
               "blocker_count": 0, "human_review_count": 0, "model_outputs_reviewed": False,
               "item_reviews": [{"item_id": "toy-q1", "verdict": "accepted_with_limitations",
                   "source_support_check": "passed", "oracle_check": "passed",
                   "explanation": "Supported toy fact.", "caveats": ["AI review only."]}],
               "reviewed_item_ids": ["toy-q1"], "cross_split_near_clone_review": {
                   "status": "accepted_with_limitations", "method": "Separate AI role reads.",
                   "limitations": ["Not human review."]}}
    return receipt, bindings, path


def test_review_bindings_detect_tampering_and_source_drift(tmp_path):
    receipt, bindings, path = receipt_fixture(tmp_path)
    assert verify_review(receipt, bindings, ["toy-q1"], root=tmp_path)["human_review"] == "pending"
    path.write_bytes(b"[]\n")
    assert_error("review_bound_file_drift", lambda: verify_review(
        receipt, bindings, ["toy-q1"], root=tmp_path))


@pytest.mark.parametrize("mutation,code", [
    (lambda r: r.update(human_review_count=1), "review_not_accepted_or_provenance_invalid"),
    (lambda r: r["reviewer"].update(agent="author"), "review_not_independent_role"),
    (lambda r: r.update(reviewed_item_ids=[]), "review_item_coverage_mismatch"),
    (lambda r: r.update(bindings={}), "review_bindings_mismatch"),
    (lambda r: r.update(cross_split_near_clone_review={}), "semantic_family_review_missing"),
])
def test_review_provenance_and_coverage_fail_closed(tmp_path, mutation, code):
    receipt, bindings, _ = receipt_fixture(tmp_path)
    mutation(receipt)
    assert_error(code, lambda: verify_review(receipt, bindings, ["toy-q1"], root=tmp_path))


def test_duplicate_json_keys_do_not_silently_override(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_bytes(b'{"a":1,"a":2}')
    assert_error("duplicate_json_key", lambda: read_json(path))


def test_dataset_order_and_root_identity_are_not_set_only_checks():
    data, reg = toy_dataset()
    data["items"].reverse()
    assert_error("dataset_item_order_mismatch", lambda: validate_dataset(data, reg, "a" * 64))
    data["items"].reverse()
    data["dataset_id"] = "other"
    assert_error("invalid_dataset_id", lambda: validate_dataset(data, reg, "a" * 64))


def test_source_data_cannot_claim_human_or_independent_review():
    data, reg = toy_dataset()
    data["provenance"]["human_reviewed"] = True
    assert_error("invalid_authorship_provenance", lambda: validate_dataset(data, reg, "a" * 64))
    data["provenance"]["human_reviewed"] = False
    data["provenance"]["independent_ai_review_status"] = "passed"
    assert_error("invalid_embedded_review_status", lambda: validate_dataset(data, reg, "a" * 64))


def test_freeze_binds_exact_bytes_and_never_authorizes_generation(tmp_path):
    path = tmp_path / "source.py"
    path.write_bytes(b"x = 1\n")
    manifest = build_freeze_manifest([path], {"status": "data_prepared"}, root=tmp_path)
    assert manifest["generation_ready"] is False
    freeze = tmp_path / "freeze.json"
    write_report(freeze, manifest)
    assert verify_freeze_manifest(freeze, root=tmp_path)["bound_file_count"] == 1
    path.write_bytes(b"x = 2\n")
    assert_error("preparation_freeze_drift", lambda: verify_freeze_manifest(freeze, root=tmp_path))


def test_freeze_rejects_path_escape(tmp_path):
    manifest = {"schema_version": 1, "phase": "preparation_snapshot", "generation_ready": False,
                "model_calls_authorized_by_this_manifest": 0, "human_review": "pending",
                "bindings": {"../outside": "0" * 64}}
    freeze = tmp_path / "freeze.json"
    write_report(freeze, manifest)
    assert_error("invalid_bound_path", lambda: verify_freeze_manifest(freeze, root=tmp_path))


def test_review_requires_real_per_item_judgment(tmp_path):
    receipt, bindings, _ = receipt_fixture(tmp_path)
    receipt["item_reviews"] = []
    assert_error("review_item_judgments_missing", lambda: verify_review(
        receipt, bindings, ["toy-q1"], root=tmp_path))
