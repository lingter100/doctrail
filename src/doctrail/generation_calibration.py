"""Model-free M5-B preparation; no generation or held-out quality claims.

Diagnostics contain safe identifiers and counts only. Structural oracle checks
cannot establish entailment; hash-bound independent AI review remains separate.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from doctrail.grounded_answer import (
    GroundedAnswerError,
    build_messages,
    validate_input,
    validate_output,
)

ROOT = Path(__file__).resolve().parents[2]
IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
POLICIES = ("baseline", "fewshot3")
TOKEN_LIMIT = 1536
TOKENIZER_FILES = ("tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt")
SPLIT_SEED = "doctrail:m5b:family-split:v1"


class PreparationError(ValueError):
    """Safe error codes, never question, source, oracle, or filesystem text."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def require(condition: bool, code: str) -> None:
    if not condition:
        raise PreparationError(code)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs,
                           parse_constant=lambda _: require(False, "invalid_json_constant"))
        require(type(value) is dict, "invalid_json_document")
        return value
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise PreparationError("unreadable_json_document") from None


def checked_path(root: Path, relative: str) -> Path:
    require(type(relative) is str and bool(relative), "invalid_bound_path")
    path = (root / relative).resolve()
    require(path.is_relative_to(root.resolve()) and not Path(relative).is_absolute(),
            "invalid_bound_path")
    return path


def _identifier(value: Any) -> str:
    require(type(value) is str and bool(IDENTIFIER.fullmatch(value)), "invalid_identifier")
    return value


def _strings(value: Any, *, nonempty=False) -> list[str]:
    require(type(value) is list and (bool(value) or not nonempty), "invalid_oracle_list")
    require(all(type(x) is str and bool(x.strip()) for x in value), "invalid_oracle_text")
    require(len(value) == len(set(value)), "duplicate_oracle_text")
    return value


def _support(support: Any, evidence: dict) -> None:
    require(type(support) is list and bool(support), "missing_fact_support")
    for citation in support:
        require(type(citation) is dict and set(citation) == {"evidence_id", "quote"},
                "invalid_fact_support")
        item = evidence.get(citation["evidence_id"])
        quote = citation["quote"]
        require(item is not None and type(quote) is str and bool(quote.strip()),
                "invalid_fact_support")
        require(item["text"].count(quote) == 1, "fact_support_not_unique_exact_quote")


def validate_registry(registry: dict) -> dict:
    require(registry.get("schema_version") == 1
            and registry.get("registry_id") == "m5b-family-registry-v1", "invalid_registry")
    algorithm = registry.get("split_algorithm", {})
    require(algorithm.get("seed") == SPLIT_SEED
            and algorithm.get("hash_input") == "seed + LF + family_id + LF + slug; no trailing LF"
            and algorithm.get("sort") == "ascending (split_sha256, family_id)"
            and algorithm.get("calibration_ranks") == list(range(1, 7))
            and algorithm.get("validation_ranks") == list(range(7, 13))
            and algorithm.get("seed_or_topic_search_permitted") is False,
            "invalid_split_algorithm")
    families = registry.get("families")
    examples = registry.get("exemplar_families")
    require(type(families) is list and len(families) == 12
            and type(examples) is list and len(examples) == 3, "invalid_family_count")
    ids = [_identifier(f["family_id"]) for f in families + examples]
    require(len(set(ids)) == 15, "duplicate_family_id")
    slugs = [_identifier(f["slug"]) for f in families + examples]
    require(len(set(slugs)) == 15, "duplicate_family_slug")
    ordered = []
    for family in families:
        value = f"{SPLIT_SEED}\n{family['family_id']}\n{family['slug']}"
        digest = sha256_bytes(value.encode("utf-8"))
        require(family["split_sha256"] == digest, "family_split_hash_mismatch")
        ordered.append((digest, family["family_id"], family))
    item_ids = set()
    counters = {split: Counter() for split in ("calibration", "validation")}
    for rank, (_, _, family) in enumerate(sorted(ordered), 1):
        split = "calibration" if rank <= 6 else "validation"
        require(family["global_rank"] == rank and family["split"] == split
                and family["split_rank"] == (rank if rank <= 6 else rank - 6),
                "family_split_assignment_mismatch")
        slots = family.get("slots")
        require(type(slots) is list and len(slots) == 4, "invalid_family_slot_count")
        require(len({s["slot_id"] for s in slots}) == 4, "duplicate_slot_id")
        statuses = Counter()
        for slot in slots:
            item_id = _identifier(slot["item_id"])
            require(item_id not in item_ids, "duplicate_registered_item_id")
            item_ids.add(item_id)
            status, reason = slot["expected_status"], slot["expected_reason"]
            require((status == "answered" and reason is None) or (status == "abstained"
                    and reason in {"insufficient_evidence", "conflicting_evidence",
                                   "ambiguous_question"}), "invalid_slot_oracle")
            require(slot["source_cardinality"] in {
                "single_document", "single_document_partial_support", "two_documents"}
                    and type(slot["injection"]) is bool and type(slot["cross_language"]) is bool,
                    "invalid_slot_metadata")
            require(slot["question_language"] in {"ko", "en"}
                    and slot["evidence_language"] in {"ko", "en"}
                    and slot["cross_language"] == (
                        slot["question_language"] != slot["evidence_language"]),
                    "invalid_slot_language")
            statuses[status] += 1
            counters[split][status] += 1
            counters[split][reason] += 1
            counters[split]["injection"] += slot["injection"]
            counters[split]["cross_language"] += slot["cross_language"]
            counters[split]["english_question"] += slot["question_language"] == "en"
            if status == "answered":
                counters[split][slot["source_cardinality"]] += 1
        require(statuses == {"answered": 2, "abstained": 2}, "invalid_family_status_balance")
    for counter in counters.values():
        for key, expected in {"answered": 12, "abstained": 12, "insufficient_evidence": 4,
            "conflicting_evidence": 4, "ambiguous_question": 4, "injection": 4,
            "cross_language": 4, "english_question": 1, "single_document": 6,
            "two_documents": 6}.items():
            require(counter[key] == expected, "invalid_split_balance")
    require({x["case"] for x in examples} == {"complete_two_document_answer",
            "conflicting_evidence", "insufficient_evidence_not_ambiguity"},
            "invalid_exemplar_families")
    return {"evaluation_families": 12, "example_families": 3, "calibration_items": 24,
            "validation_items": 24, "deterministic_split_verified": True}


def validate_oracle(oracle: dict, evidence: list[dict], slot: dict) -> None:
    expected_keys = {"expected_status", "expected_reason", "required_question_parts",
                     "required_facts", "abstention_rationale", "missing_information",
                     "conflicting_facts", "ambiguity_candidates", "prohibited_inferences",
                     "injection_marker"}
    require(type(oracle) is dict and set(oracle) == expected_keys, "invalid_oracle_schema")
    status, reason = oracle["expected_status"], oracle["expected_reason"]
    require(status == slot["expected_status"] and reason == slot["expected_reason"],
            "oracle_registry_mismatch")
    _strings(oracle["required_question_parts"], nonempty=True)
    for key in ("missing_information", "ambiguity_candidates", "prohibited_inferences"):
        _strings(oracle[key])
    facts, conflicts = oracle["required_facts"], oracle["conflicting_facts"]
    require(type(facts) is list and type(conflicts) is list, "invalid_oracle_facts")
    by_id = {item["evidence_id"]: item for item in evidence}
    fact_ids = []
    for fact in facts:
        require(type(fact) is dict and set(fact) == {"fact_id", "text", "support"},
                "invalid_required_fact")
        fact_ids.append(_identifier(fact["fact_id"]))
        require(type(fact["text"]) is str and bool(fact["text"].strip()), "invalid_fact_text")
        _support(fact["support"], by_id)
    require(len(fact_ids) == len(set(fact_ids)), "duplicate_fact_id")
    for fact in conflicts:
        require(type(fact) is dict and set(fact) == {"text", "support"}, "invalid_conflict_fact")
        require(type(fact["text"]) is str and bool(fact["text"].strip()), "invalid_fact_text")
        _support(fact["support"], by_id)
    if status == "answered":
        require(reason is None and bool(facts) and oracle["abstention_rationale"] is None,
                "invalid_answer_oracle")
        require(not conflicts and not oracle["missing_information"]
                and not oracle["ambiguity_candidates"], "invalid_answer_oracle")
    else:
        require(status == "abstained" and reason in {
            "insufficient_evidence", "conflicting_evidence", "ambiguous_question"},
            "invalid_abstention_reason")
        require(not facts and type(oracle["abstention_rationale"]) is str
                and bool(oracle["abstention_rationale"].strip())
                and bool(oracle["prohibited_inferences"]), "invalid_abstention_oracle")
        require(bool(oracle["missing_information"]) == (reason == "insufficient_evidence"),
                "invalid_missing_information_oracle")
        require((len(conflicts) >= 2) if reason == "conflicting_evidence" else not conflicts,
                "invalid_conflict_oracle")
        require((len(oracle["ambiguity_candidates"]) >= 2) if reason == "ambiguous_question"
                else not oracle["ambiguity_candidates"], "invalid_ambiguity_oracle")
    marker = oracle["injection_marker"]
    if slot["injection"]:
        require(type(marker) is str and bool(marker)
                and any(marker in item["text"] for item in evidence)
                and bool(oracle["prohibited_inferences"]), "invalid_injection_oracle")
    else:
        require(marker is None, "unexpected_injection_marker")


def validate_dataset(dataset: dict, registry: dict, registry_hash: str) -> dict:
    split = dataset.get("split")
    require(split in {"calibration", "validation", "examples"}, "invalid_dataset_split")
    require(dataset.get("schema_version") == 1
            and dataset.get("registry_sha256") == registry_hash, "dataset_registry_hash_mismatch")
    expected_id = {"calibration": "m5b-calibration-v1", "validation": "m5b-validation-v1",
                   "examples": "m5b-policy-examples-v1"}[split]
    require(dataset.get("dataset_id") == expected_id, "invalid_dataset_id")
    _validate_provenance(dataset.get("provenance", {}))
    sources, items = dataset.get("sources"), dataset.get("items")
    require(type(sources) is list and type(items) is list
            and len(items) == (3 if split == "examples" else 24),
            "invalid_dataset_size")
    source_map = {}
    for source in sources:
        require(type(source) is dict and set(source) == {
            "family_id", "document_id", "revision", "source_sha256", "text"},
            "invalid_source_schema")
        _identifier(source["family_id"])
        _identifier(source["document_id"])
        require(type(source["revision"]) is int and source["revision"] > 0
                and type(source["text"]) is str and bool(source["text"].strip()),
                "invalid_source")
        require(sha256_bytes(source["text"].encode("utf-8")) == source["source_sha256"],
                "source_hash_mismatch")
        key = (source["document_id"], source["revision"])
        require(key not in source_map, "duplicate_source_key")
        source_map[key] = source
    slots = {}
    for family in sorted(registry["families"], key=lambda f: f.get("split_rank", 0)):
        if family["split"] == split:
            for slot in sorted(family["slots"], key=lambda s: s["slot_id"]):
                slots[slot["item_id"]] = (family["family_id"], slot)
    if split == "examples":
        for family in sorted(registry["exemplar_families"], key=lambda f: f["family_id"]):
            case = family["case"]
            slots[family["family_id"] + "-Q01"] = (family["family_id"], {
                "slot_id": "q01", "expected_status": "answered" if case ==
                "complete_two_document_answer" else "abstained", "expected_reason":
                None if case == "complete_two_document_answer" else "conflicting_evidence"
                if case == "conflicting_evidence" else "insufficient_evidence",
                "source_cardinality": "single_document" if case ==
                "insufficient_evidence_not_ambiguity" else "two_documents", "injection": False})
    require(len(slots) == len(items), "invalid_registered_slot_count")
    require([item.get("item_id") for item in items] == list(slots), "dataset_item_order_mismatch")
    ids, used_sources = set(), set()
    counts = Counter()
    for item in items:
        item_id = _identifier(item.get("item_id"))
        require(item_id not in ids and item_id in slots, "duplicate_or_unregistered_item")
        ids.add(item_id)
        family_id, slot = slots[item_id]
        require(item.get("family_id") == family_id and item.get("slot_id") == slot["slot_id"],
                "item_family_slot_mismatch")
        provenance = item.get("provenance", {})
        _validate_provenance(provenance)
        require(provenance.get("synthetic") is True and provenance.get("question_author") == "AI"
                and provenance.get("human_review") == "pending"
                and type(provenance.get("author_agent")) is str
                and bool(provenance["author_agent"]), "invalid_item_provenance")
        try:
            evidence = validate_input(item.get("question"), item.get("evidence"))
        except GroundedAnswerError:
            raise PreparationError("invalid_grounded_input") from None
        require(bool(evidence), "empty_evidence_not_model_case")
        documents = set()
        for chunk in evidence:
            key = (chunk["document_id"], chunk["revision"])
            source = source_map.get(key)
            require(source is not None and source["family_id"] == family_id,
                    "evidence_source_family_mismatch")
            require(source["source_sha256"] == chunk["source_sha256"],
                    "evidence_source_hash_mismatch")
            require(source["text"][chunk["start_cp"]:chunk["end_cp"]] == chunk["text"],
                    "evidence_source_span_mismatch")
            documents.add(key)
            used_sources.add(key)
        require(len(documents) == {"single_document": 1, "single_document_partial_support": 1,
                                  "two_documents": 2}[
            slot["source_cardinality"]], "source_cardinality_mismatch")
        validate_oracle(item["oracle"], evidence, slot)
        if slot["expected_status"] == "answered":
            required = 2 if slot["source_cardinality"] == "two_documents" else 1
            oracle = item["oracle"]
            require(len(oracle["required_question_parts"]) == required
                    and len(oracle["required_facts"]) == required, "required_fact_count_mismatch")
            if required == 2:
                by_id = {chunk["evidence_id"]: chunk for chunk in evidence}
                supporting_documents = [{by_id[c["evidence_id"]]["document_id"]
                    for c in fact["support"]} for fact in oracle["required_facts"]]
                require(all(len(docs) == 1 for docs in supporting_documents)
                        and supporting_documents[0] != supporting_documents[1],
                        "two_fact_documents_not_distinct")
        if split == "examples":
            output = item.get("assistant_output")
            try:
                validated = validate_output(json.dumps(output, ensure_ascii=False), evidence,
                                            finish_reason="eos")
            except GroundedAnswerError:
                raise PreparationError("invalid_fewshot_output") from None
            require(validated["status"] == slot["expected_status"]
                    and validated["reason"] == slot["expected_reason"],
                    "fewshot_oracle_mismatch")
            if validated["status"] == "answered":
                require(len(validated["claims"]) == 2 and len(item["oracle"]["required_facts"]) == 2,
                        "fewshot_incomplete_two_fact_answer")
        counts[item["oracle"]["expected_status"]] += 1
    require(ids == set(slots) and used_sources == set(source_map), "unused_or_missing_dataset_members")
    return {"split": split, "item_count": len(items), "family_count": len({
        item["family_id"] for item in items}), "source_count": len(sources),
        "expected_status_counts": dict(sorted(counts.items()))}


def _validate_provenance(provenance: dict) -> None:
    require(type(provenance) is dict and provenance.get("synthetic") is True
            and provenance.get("ai_authored") is True
            and provenance.get("human_reviewed") is False
            and type(provenance.get("human_review_count")) is int
            and provenance["human_review_count"] == 0
            and type(provenance.get("author_agent")) is str
            and bool(provenance["author_agent"])
            and provenance.get("review_status") == "pending", "invalid_authorship_provenance")
    for field in ("automated_review_status", "independent_ai_review_status", "human_review"):
        require(field not in provenance or provenance[field] == "pending",
                "invalid_embedded_review_status")


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def duplicate_diagnostics(datasets: list[dict]) -> dict:
    """Cross-family lexical diagnostics are flags, never semantic independence proof."""
    rows = [item for dataset in datasets for item in dataset["items"]]
    duplicates, near = [], []
    for index, left in enumerate(rows):
        for right in rows[index + 1:]:
            if left["family_id"] == right["family_id"]:
                continue
            a, b = _normalized(left["question"]), _normalized(right["question"])
            pair = [left["item_id"], right["item_id"]]
            if a == b:
                duplicates.append(pair)
            elif SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.85:
                near.append(pair)
    source_rows = [source for dataset in datasets for source in dataset["sources"]]
    source_duplicates = []
    source_near = []
    for index, left in enumerate(source_rows):
        for right in source_rows[index + 1:]:
            if left["family_id"] == right["family_id"]:
                continue
            a, b = _normalized(left["text"]), _normalized(right["text"])
            pair = [left["document_id"], right["document_id"]]
            if a == b:
                source_duplicates.append(pair)
            elif SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.85:
                source_near.append(pair)
    return {"cross_family_duplicate_questions": duplicates,
            "cross_family_near_questions": near,
            "cross_family_duplicate_sources": source_duplicates,
            "cross_family_near_sources": source_near,
            "near_clone_threshold": 0.85, "semantic_independence": "requires_independent_review"}


def build_policy_messages(question, evidence, *, policy: str, examples: list[dict]):
    base = build_messages(question, evidence)
    require(policy in POLICIES, "unknown_prompt_policy")
    if policy == "baseline":
        return base
    require(type(examples) is list and len(examples) == 3, "fewshot_requires_exactly_three_examples")
    messages = [base[0]]
    for example in examples:
        checked = validate_input(example["question"], example["evidence"])
        compact = {"question": example["question"], "evidence": [
            {"evidence_id": e["evidence_id"], "text": e["text"]} for e in checked]}
        user = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        output = example["assistant_output"]
        serialized = json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        try:
            validate_output(serialized, example["evidence"], finish_reason="eos")
        except GroundedAnswerError:
            raise PreparationError("invalid_fewshot_output") from None
        messages.extend([{"role": "user", "content": user.replace("<", "\\u003c").replace(
            ">", "\\u003e")}, {"role": "assistant", "content": serialized.replace(
            "<", "\\u003c").replace(">", "\\u003e")}])
    return messages + [base[1]]


def prompt_budget(datasets: list[dict], examples: list[dict], tokenizer) -> dict:
    rows = []
    for dataset in datasets:
        for item in dataset["items"]:
            lengths, hashes = {}, {}
            for policy in POLICIES:
                messages = build_policy_messages(item["question"], item["evidence"],
                                                 policy=policy, examples=examples)
                rendered = tokenizer.apply_chat_template(messages, tokenize=False,
                    add_generation_prompt=True, enable_thinking=False)
                tokens = tokenizer(rendered, add_special_tokens=False,
                                   truncation=False)["input_ids"]
                require(type(tokens) is list and all(type(x) is int for x in tokens),
                        "invalid_tokenizer_result")
                lengths[policy] = len(tokens)
                hashes[policy] = sha256_bytes(rendered.encode("utf-8"))
            rows.append({"item_id": item["item_id"], "split": dataset["split"],
                         "input_tokens": lengths, "rendered_prompt_sha256": hashes})
    overflow = [row["item_id"] for row in rows
                if any(length > TOKEN_LIMIT for length in row["input_tokens"].values())]
    return {"status": "passed" if not overflow else "blocked", "max_input_tokens": TOKEN_LIMIT,
            "enable_thinking": False, "truncation": False, "rows": rows,
            "overflow_item_ids": overflow, "policy_counts": {p: len(rows) for p in POLICIES},
            "max_tokens_by_policy": {p: max((r["input_tokens"][p] for r in rows), default=0)
                                     for p in POLICIES}}


def load_local_tokenizer(snapshot: Path, model_manifest: Path):
    """Read only pinned tokenizer files. No model, weights, torch, CUDA, or network."""
    require(file_sha256(model_manifest) ==
            "04ffa1bb70bd7fb853efebb11e13455647c0182c2960be8e197d758cb0198fa1",
            "tokenizer_manifest_hash_mismatch")
    manifest = read_json(model_manifest)
    model = manifest.get("model", {})
    require(model.get("repo_id") == "Qwen/Qwen3-1.7B" and model.get("revision") ==
            "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e", "unsupported_tokenizer_revision")
    verified = {}
    for name in TOKENIZER_FILES:
        expected = model["files"][name]
        path = snapshot / name
        require(path.is_file() and path.stat().st_size == expected["size_bytes"],
                "tokenizer_file_size_mismatch")
        digest = file_sha256(path)
        require(digest == expected["sha256"], "tokenizer_file_hash_mismatch")
        verified[name] = digest
    # Run CLI in a fresh process: transformers caches backend availability on import.
    # Restore environment even on failure; never touch a model or CUDA API.
    settings = {"USE_TORCH": "0", "USE_TF": "0", "USE_FLAX": "0",
                "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    previous = {key: os.environ.get(key) for key in settings}
    try:
        os.environ.update(settings)
        from transformers import AutoTokenizer

        # Prevent local chat_template.jinja or special_tokens_map overrides from
        # entering AutoTokenizer through unbound files in the model snapshot.
        with tempfile.TemporaryDirectory(prefix="doctrail-m5b-tokenizer-") as directory:
            target = Path(directory)
            for name in TOKENIZER_FILES:
                shutil.copyfile(snapshot / name, target / name)
                require(file_sha256(target / name) == verified[name], "tokenizer_copy_hash_mismatch")
            tokenizer = AutoTokenizer.from_pretrained(str(target), local_files_only=True,
                                                      trust_remote_code=False)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return tokenizer, verified


def verify_review(receipt: dict, expected_bindings: dict[str, str], item_ids: list[str],
                  *, root: Path = ROOT) -> dict:
    """Integrity and declared role separation; no claim of human attestation."""
    require(receipt.get("schema_version") == 1
            and receipt.get("review_type") == "independent_ai_semantic_prereview",
            "invalid_review_type")
    require(receipt.get("bindings") == expected_bindings, "review_bindings_mismatch")
    for name, digest in expected_bindings.items():
        require(file_sha256(checked_path(root, name)) == digest, "review_bound_file_drift")
    reviewer = receipt.get("reviewer", {})
    require(type(reviewer.get("agent")) is str and bool(reviewer["agent"])
            and type(reviewer.get("fixture_author")) is str and bool(reviewer["fixture_author"])
            and reviewer["agent"] != reviewer["fixture_author"]
            and reviewer.get("authored_fixture") is False, "review_not_independent_role")
    require(receipt.get("status") == "accepted_with_limitations"
            and receipt.get("blocker_count") == 0
            and type(receipt.get("blocker_count")) is int
            and receipt.get("human_review_count") == 0
            and type(receipt.get("human_review_count")) is int
            and receipt.get("model_outputs_reviewed") is False,
            "review_not_accepted_or_provenance_invalid")
    reviewed = receipt.get("reviewed_item_ids")
    require(type(reviewed) is list and sorted(reviewed) == sorted(item_ids)
            and len(reviewed) == len(set(reviewed)), "review_item_coverage_mismatch")
    judgments = receipt.get("item_reviews")
    require(type(judgments) is list and len(judgments) == len(item_ids),
            "review_item_judgments_missing")
    require(sorted(j.get("item_id", "") for j in judgments) == sorted(item_ids),
            "review_judgment_coverage_mismatch")
    for judgment in judgments:
        require(judgment.get("verdict") == "accepted_with_limitations"
                and judgment.get("source_support_check") == "passed"
                and judgment.get("oracle_check") == "passed"
                and type(judgment.get("explanation")) is str
                and bool(judgment["explanation"].strip()), "invalid_item_review_judgment")
        _strings(judgment.get("caveats"), nonempty=True)
    semantic = receipt.get("cross_split_near_clone_review", {})
    require(semantic.get("status") == "accepted_with_limitations"
            and type(semantic.get("method")) is str and bool(semantic["method"].strip())
            and type(semantic.get("limitations")) is list and bool(semantic["limitations"]),
            "semantic_family_review_missing")
    return {"status": "accepted_with_limitations", "reviewed_item_count": len(item_ids),
            "human_review_count": 0, "human_review": "pending",
            "reviewer_agent": reviewer["agent"], "semantic_review": "AI_only"}


def prepare(registry_path: Path, calibration_path: Path, validation_path: Path,
            examples_path: Path, *, snapshot: Path | None = None,
            model_manifest: Path | None = None, review_paths: list[Path] | None = None,
            root: Path = ROOT) -> dict:
    paths = [registry_path, calibration_path, validation_path, examples_path]
    names = []
    for path in paths:
        require(path.resolve().is_relative_to(root.resolve()), "invalid_bound_path")
        names.append(path.resolve().relative_to(root.resolve()).as_posix())
    bindings = {name: file_sha256(path) for name, path in zip(names, paths, strict=True)}
    registry, calibration, validation, examples = [read_json(p) for p in paths]
    require(calibration.get("split") == "calibration" and validation.get("split") == "validation"
            and examples.get("split") == "examples", "dataset_argument_split_mismatch")
    registry_summary = validate_registry(registry)
    dataset_summaries = [validate_dataset(d, registry, bindings[names[0]])
                         for d in (calibration, validation, examples)]
    document_ids = [source["document_id"] for dataset in (calibration, validation, examples)
                    for source in dataset["sources"]]
    require(len(document_ids) == len(set(document_ids)), "duplicate_dataset_document_id")
    diagnostic = duplicate_diagnostics([calibration, validation, examples])
    exact_duplicates = bool(diagnostic["cross_family_duplicate_questions"]
                            or diagnostic["cross_family_duplicate_sources"])
    reviews = []
    for path in review_paths or []:
        receipt = read_json(path)
        reviewed_ids = receipt.get("reviewed_item_ids", [])
        all_ids = {item["item_id"] for dataset in (calibration, validation, examples)
                   for item in dataset["items"]}
        require(set(reviewed_ids).issubset(all_ids), "review_unregistered_item")
        # Each receipt binds the complete dataset boundary, even for a partial role review.
        result = verify_review(receipt, bindings, reviewed_ids, root=root)
        by_id = {item["item_id"]: item for dataset in (calibration, validation, examples)
                 for item in dataset["items"]}
        for judgment in receipt["item_reviews"]:
            item = by_id[judgment["item_id"]]
            require(receipt["reviewer"]["agent"] != item["provenance"].get("author_agent"),
                    "item_review_by_author")
            require(judgment.get("expected_status") == item["oracle"]["expected_status"]
                    and judgment.get("expected_reason") == item["oracle"]["expected_reason"],
                    "review_oracle_expectation_mismatch")
        result["receipt_sha256"] = file_sha256(path)
        result["reviewed_item_ids"] = reviewed_ids
        reviews.append(result)
    reviewed_union = {identifier for review in reviews for identifier in review["reviewed_item_ids"]}
    all_ids = {item["item_id"] for dataset in (calibration, validation, examples)
               for item in dataset["items"]}
    review_complete = reviewed_union == all_ids
    budget = {"status": "not_run", "reason": "local_tokenizer_snapshot_not_supplied"}
    if snapshot is not None:
        require(model_manifest is not None, "missing_tokenizer_manifest")
        tokenizer, verified = load_local_tokenizer(snapshot, model_manifest)
        budget = prompt_budget([calibration, validation], examples["items"], tokenizer)
        budget["verified_tokenizer_files"] = verified
        budget["manifest_sha256"] = file_sha256(model_manifest)
    data_ready = not exact_duplicates and review_complete and budget["status"] == "passed"
    message_hashes = []
    for dataset in (calibration, validation):
        for item in dataset["items"]:
            message_hashes.append({"item_id": item["item_id"], "split": dataset["split"],
                "canonical_messages_sha256": {policy: sha256_bytes(json.dumps(
                    build_policy_messages(item["question"], item["evidence"], policy=policy,
                                          examples=examples["items"]),
                    ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
                    for policy in POLICIES}})
    return {"schema_version": 1, "phase": "model_free_data_preparation",
            "status": "data_prepared" if data_ready else "preparation_incomplete",
            "generation_ready": False, "generation_calls": 0, "human_review_count": 0,
            "human_review": "pending", "final_test": "locked", "bindings": bindings,
            "registry": registry_summary, "datasets": dataset_summaries,
            "prompt_message_hashes": message_hashes,
            "model_free_prerequisites_passed": not exact_duplicates and review_complete,
            "duplicate_diagnostics": diagnostic, "reviews": reviews,
            "independent_ai_review_complete": review_complete, "prompt_budget": budget,
            "limitations": ["Synthetic AI-authored development data; not held-out quality.",
                            "No model outputs, GPU run, or service adoption in this milestone.",
                            "Generation requires a separately frozen execution plan and quota."]}


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
                      + "\n").encode("utf-8"))


def build_freeze_manifest(paths: list[Path], report: dict, *, root: Path = ROOT) -> dict:
    """A data/code/docs snapshot only; deliberately cannot grant execution readiness."""
    bindings = {}
    for path in paths:
        require(path.resolve().is_relative_to(root.resolve()), "invalid_bound_path")
        name = path.resolve().relative_to(root.resolve()).as_posix()
        bindings[name] = file_sha256(path)
    return {"schema_version": 1, "phase": "preparation_snapshot", "bindings": bindings,
            "preparation_status": report["status"], "generation_ready": False,
            "model_calls_authorized_by_this_manifest": 0, "human_review": "pending"}


def verify_freeze_manifest(manifest_path: Path, *, root: Path = ROOT) -> dict:
    manifest = read_json(manifest_path)
    require(manifest.get("schema_version") == 1 and manifest.get("phase") == "preparation_snapshot"
            and manifest.get("generation_ready") is False
            and type(manifest.get("model_calls_authorized_by_this_manifest")) is int
            and manifest["model_calls_authorized_by_this_manifest"] == 0
            and manifest.get("human_review") == "pending", "invalid_preparation_freeze")
    bindings = manifest.get("bindings")
    require(type(bindings) is dict and bool(bindings), "empty_preparation_freeze")
    for name, digest in bindings.items():
        require(type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
                "invalid_freeze_digest")
        require(file_sha256(checked_path(root, name)) == digest, "preparation_freeze_drift")
    return {"status": "verified", "bound_file_count": len(bindings),
            "generation_ready": False, "generation_calls": 0, "human_review": "pending"}
