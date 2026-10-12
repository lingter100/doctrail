"""Synthetic checks of M4 data boundaries; these are not semantic/human reviews."""

import copy
import json

import pytest

from scripts import prepare_training as training


@pytest.fixture
def plan():
    return {
        "schema_version": 1,
        "split": {
            "seed": "doctrail-m4-train-v1", "hash_algorithm": "sha256",
            "hash_prefix_hex_chars": 16, "bucket_modulus": 100,
            "fit_buckets": [0, 79], "calibration_buckets": [80, 99],
            "group_field": "family_id", "source_split": "train",
        },
        "corpus": {"manifest_path": "manifest.json", "manifest_sha256": "a" * 64},
        "negative_mining": {"method": "bm25", "top_k": 20, "near_duplicate_threshold": 0.8,
                            "pool": "same_partition_only"},
        "positive_gates": {
            "question_duplicate_method": "casefolded normalized character trigram Jaccard",
            "question_duplicate_threshold": 0.8,
        },
    }


def document(identifier, family, text, language="en", canonical=None):
    return {
        "id": identifier, "family_id": family, "split": "train", "content": text,
        "normalized_sha256": training.sha256(text.encode()), "sha256": "b" * 64,
        "title": identifier, "language": language, "canonical_path": canonical or identifier,
        "source_url": "https://example.com/synthetic/" + identifier,
        "license": "CC-BY-4.0", "author": "Synthetic fixture", "revision": "synthetic",
    }


@pytest.fixture
def inputs(plan):
    groups = {part: [f"family-{i}" for i in range(100)
                     if training.partition_for(f"family-{i}", plan) == part]
              for part in ("fit", "calibration")}
    docs = [
        document("fit-positive", groups["fit"][0],
                 "배경입니다.\nA pod's containers share the same network namespace.\nMore details."),
        document("fit-translation", groups["fit"][0], "같은 파드의 컨테이너들은 네트워크 공간을 공유합니다.",
                 "ko", canonical="fit-positive"),
        document("fit-unreviewed", groups["fit"][1],
                 "The network is inspected with the status command and a network report."),
        document("fit-quote-copy", groups["fit"][2],
                 "Other context. A pod's containers share the same network namespace. More."),
        document("calibration", groups["calibration"][0],
                 "Controllers operate network reconciliation loops in a cluster."),
    ]
    inventory = training.build_inventory(plan, docs, "c" * 64)
    pack = training.build_author_pack(inventory, docs, "fit", ["fit-positive"])
    digest = training.fingerprint(pack)
    draft = {
        "id": "m4-fit-001", "partition": "fit", "question": "What network do pod containers share?",
        "language": "en", "query_type": "semantic", "question_family_id": "pod-network",
        "evidence": [{"document_id": "fit-positive",
                      "quote": "A pod's containers share the same network namespace.", "occurrence": 0}],
        "expected_answer": "The same network namespace.", "rationale": "Asks one explicit fact.",
        "author_pack_sha256": digest,
        "provenance": {"authorship": "ai_authored", "source_kind": "public_real",
                       "author_model": "gpt-6-astra", "author_reasoning": "high",
                       "human_review": "pending"},
        "semantic_review": {"status": "pending"},
    }
    return docs, inventory, {digest: pack}, draft


def compile_one(plan, inputs, drafts=None):
    docs, inventory, packs, draft = inputs
    return training.compile_dataset(plan, inventory, docs, packs, drafts or [draft], {})


def lines(raw):
    return [json.loads(line) for line in raw.splitlines()]


def test_stable_partition_and_translation_group(plan, inputs):
    docs, inventory, _, _ = inputs
    assert training.build_inventory(plan, list(reversed(docs)), "c" * 64) == inventory
    assert {row["partition"] for row in inventory["documents"]
            if row["family_id"] == docs[0]["family_id"]} == {"fit"}
    assert sum(row["documents"] for row in inventory["counts"].values()) == len(docs)


def test_hash_tampering_rejected(plan, inputs):
    inputs[0][0]["content"] += "tampered"
    with pytest.raises(ValueError, match="integrity|checksum"):
        compile_one(plan, inputs)


def test_manifest_hash_rejected_before_loader(tmp_path, plan, monkeypatch):
    (tmp_path / "manifest.json").write_text("{}")
    (tmp_path / "protocol.md").write_bytes(b"instructions")
    plan["draft_contract"] = {"protocol_path": "protocol.md",
                              "protocol_sha256": training.sha256(b"instructions")}
    plan_path = tmp_path / "plan.json"
    plan_path.write_bytes(training.json_bytes(plan))
    monkeypatch.setattr(training, "load_verified_corpus", lambda *_: pytest.fail("Must not load"))
    with pytest.raises(ValueError, match="manifest checksum"):
        training.load_inputs(plan_path, tmp_path)


@pytest.mark.parametrize("split", ["dev", "test", "smoke"])
def test_nontrain_documents_rejected(plan, inputs, split):
    inputs[0][0]["split"] = split
    with pytest.raises(ValueError, match="train"):
        training.build_inventory(plan, inputs[0], "c" * 64)


@pytest.mark.parametrize("doc_id", ["calibration", "fit-unreviewed", "missing-dev"])
def test_evidence_must_belong_to_exact_author_pack(plan, inputs, doc_id):
    inputs[3]["evidence"][0]["document_id"] = doc_id
    with pytest.raises(ValueError, match="outside allowed"):
        compile_one(plan, inputs)


def test_author_pack_tampering_rejected(plan, inputs):
    next(iter(inputs[2].values()))["allowed_document_ids"].append("calibration")
    with pytest.raises(ValueError, match="checksum"):
        compile_one(plan, inputs)


def test_unicode_offsets_and_whole_span_positive(plan, inputs):
    result = compile_one(plan, inputs)
    question = lines(result["questions.jsonl"])[0]
    span = question["evidence"][0]
    assert span["start_offset"] == len("배경입니다.\n")
    assert inputs[0][0]["content"][span["start_offset"]:span["end_offset"]] == span["quote"]
    pair = lines(result["positive-pairs.jsonl"])[0]
    assert pair["positive"]["start_offset"] <= span["start_offset"]
    assert pair["positive"]["end_offset"] >= span["end_offset"]
    assert pair["human_review"] == "pending" and not pair["eligible_for_training"]


def test_false_negative_quarantine_and_unknown_not_negative(plan, inputs):
    result = compile_one(plan, inputs)
    candidates = lines(result["negative-candidates.jsonl"])
    assert candidates
    assert all(row["partition"] == "fit" and row["document_id"] != "calibration"
               for row in candidates)
    by_document = {row["document_id"]: row for row in candidates}
    assert by_document["fit-positive"]["status"] == "quarantined_false_negative_risk"
    assert "contains_known_evidence_quote" in by_document["fit-quote-copy"]["quarantine_reasons"]
    assert by_document["fit-unreviewed"]["status"] == "unreviewed"
    assert all(row["negative_label"] is None and not row["eligible_for_training"]
               for row in candidates)


def test_long_quote_has_no_false_positive_chunk(plan, inputs):
    docs, _, _, draft = inputs
    quote = "abcdefghij " * 120
    docs[0]["content"] = quote
    docs[0]["normalized_sha256"] = training.sha256(quote.encode())
    inventory = training.build_inventory(plan, docs, "c" * 64)
    pack = training.build_author_pack(inventory, docs, "fit", [docs[0]["id"]])
    draft["author_pack_sha256"] = training.fingerprint(pack)
    draft["evidence"][0]["quote"] = quote
    result = training.compile_dataset(plan, inventory, docs,
                                      {training.fingerprint(pack): pack}, [draft], {})
    assert result["positive-pairs.jsonl"] == b""
    assert "evidence_not_covered_by_one_chunk" in lines(result["questions.jsonl"])[0][
        "quarantine_reasons"]


@pytest.mark.parametrize("field,value", [("authorship", "human"), ("human_review", "approved"),
                                        ("author_model", "unknown")])
def test_false_provenance_rejected(plan, inputs, field, value):
    inputs[3]["provenance"][field] = value
    with pytest.raises(ValueError, match="provenance"):
        compile_one(plan, inputs)


def test_near_duplicate_questions_are_quarantined(plan, inputs):
    draft = inputs[3]
    other = copy.deepcopy(draft)
    other["id"] = "m4-fit-002"
    other["question"] = draft["question"] + "!"
    result = compile_one(plan, inputs, [draft, other])
    assert all("near_duplicate_question" in row["quarantine_reasons"]
               for row in lines(result["questions.jsonl"]))
    assert all(row["quarantined"] for row in lines(result["positive-pairs.jsonl"]))


def test_exact_duplicate_question_rejected(plan, inputs):
    other = copy.deepcopy(inputs[3])
    other["id"] = "m4-fit-002"
    with pytest.raises(ValueError, match="Exact duplicate"):
        compile_one(plan, inputs, [inputs[3], other])


def test_replay_determinism_and_no_overwrite(plan, inputs, tmp_path):
    first = compile_one(plan, inputs)
    assert compile_one(plan, inputs) == first
    path = tmp_path / "report.json"
    training.write_or_verify(path, first["report.json"])
    with pytest.raises(FileExistsError):
        training.write_or_verify(path, first["report.json"])
    training.write_or_verify(path, first["report.json"], verify=True)
    with pytest.raises(ValueError, match="Replay mismatch"):
        training.write_or_verify(path, b"tampered", verify=True)
    assert json.loads(first["report.json"])["training_ready"] is False


def test_duplicate_intent_is_quarantined_even_without_lexical_overlap(plan, inputs):
    other = copy.deepcopy(inputs[3])
    other["id"] = "m4-fit-002"
    other["question"] = "Describe the shared namespace of these units."
    result = compile_one(plan, inputs, [inputs[3], other])
    assert all("duplicate_question_intent" in row["quarantine_reasons"]
               for row in lines(result["questions.jsonl"]))


def test_cross_language_is_derived_not_claimed(plan, inputs):
    inputs[3]["query_type"] = "cross_lingual"
    with pytest.raises(ValueError, match="evidence language"):
        compile_one(plan, inputs)
    inputs[3]["language"] = "ko"
    result = compile_one(plan, inputs)
    assert lines(result["questions.jsonl"])[0]["cross_language"] is True
    assert json.loads(result["report.json"])["counts"]["fit"]["cross_language"] == 1


def test_policy_changes_rejected(plan, inputs):
    plan["negative_mining"]["top_k"] = 50
    with pytest.raises(ValueError, match="mining policy"):
        compile_one(plan, inputs)


def test_shortfalls_reported_without_claiming_ready(plan, inputs):
    plan["pilot"] = {"target_fit_queries": 64, "target_calibration_queries": 16,
                     "min_fit_families": 16, "min_calibration_families": 4,
                     "min_english_queries": 8, "min_korean_queries_with_english_evidence": 16}
    report = json.loads(compile_one(plan, inputs)["report.json"])
    assert "fit_query_target" in report["unmet_pilot_data_gates"]
    assert "calibration_family_target" in report["unmet_pilot_data_gates"]
    assert "english_queries" in report["unmet_pilot_data_gates"]
    assert report["training_ready"] is False


def test_tampered_protocol_rejected_before_corpus(tmp_path, plan, monkeypatch):
    (tmp_path / "protocol.md").write_bytes(b"tampered")
    plan["draft_contract"] = {"protocol_path": "protocol.md", "protocol_sha256": "a" * 64}
    plan_path = tmp_path / "plan.json"
    plan_path.write_bytes(training.json_bytes(plan))
    monkeypatch.setattr(training, "load_verified_corpus", lambda *_: pytest.fail("Must not load"))
    with pytest.raises(ValueError, match="protocol checksum"):
        training.load_inputs(plan_path, tmp_path)


def test_quote_occurrence_and_fabricated_offset():
    doc = document("repeat", "f", "Unicode 인용 구절. More. Unicode 인용 구절.")
    item = {"quote": "Unicode 인용 구절.", "occurrence": 1}
    span = training.evidence_span(item, doc)
    assert span["start_offset"] == doc["content"].rfind(item["quote"])
    item["start_offset"] = 0
    with pytest.raises(ValueError, match="computed Unicode span"):
        training.evidence_span(item, doc)


def test_intent_family_cannot_cross_partitions(plan, inputs):
    docs, inventory, packs, draft = inputs
    pack = training.build_author_pack(inventory, docs, "calibration", ["calibration"])
    digest = training.fingerprint(pack)
    packs[digest] = pack
    other = copy.deepcopy(draft)
    other.update(id="m4-cal-001", partition="calibration", question="What does reconciliation do?",
                 author_pack_sha256=digest, evidence=[{"document_id": "calibration",
                                                     "quote": docs[-1]["content"]}])
    with pytest.raises(ValueError, match="intent family crosses"):
        compile_one(plan, inputs, [draft, other])


def test_near_duplicate_cross_partition_flag(plan, inputs):
    docs, inventory, packs, draft = inputs
    pack = training.build_author_pack(inventory, docs, "calibration", ["calibration"])
    digest = training.fingerprint(pack)
    packs[digest] = pack
    other = copy.deepcopy(draft)
    other.update(id="m4-cal-001", partition="calibration", question=draft["question"] + "!",
                 question_family_id="different-intent", author_pack_sha256=digest,
                 evidence=[{"document_id": "calibration", "quote": docs[-1]["content"]}])
    result = compile_one(plan, inputs, [draft, other])
    flags = json.loads(result["report.json"])["near_duplicate_flags"]
    assert len(flags) == 1 and flags[0]["cross_partition"] is True
    assert all(row["quarantined"] for row in lines(result["positive-pairs.jsonl"]))


def test_max_family_query_gate(plan, inputs):
    drafts = []
    for i, query in enumerate([
        "What namespace is shared?", "Does this pod separate its containers?",
        "Explain the network arrangement within a pod.", "Where do workloads communicate?",
        "Name the shared connection environment.",
    ]):
        draft = copy.deepcopy(inputs[3])
        draft.update(id=f"m4-fit-{i}", question=query, question_family_id=f"intent-{i}")
        drafts.append(draft)
    report = json.loads(compile_one(plan, inputs, drafts)["report.json"])
    assert report["pilot_data_gates"]["max_queries_per_family"] is False
