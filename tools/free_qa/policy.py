"""Pure, closed policies for the separately registered six-case QA comparison."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

BASE = "ministral3-3b-q5km"
CANDIDATE = "qwen25-7b-q4km"
PROFILE_PINS = MappingProxyType({
    BASE: ("data/models/meetings-generation-ministral3-v1.json", "2b4d19c14af2697188d6a07a41b1ea971c1eaefec68fbc9beb035d74906f1de7"),
    CANDIDATE: ("data/models/meetings-generation-qwen25-7b-q4km-v1.json", "6cb34ab578e55c61e20b7c5d49fc7cbb9086fd06cd57359e6b2ccd1ff67f97c7"),
})
RUNTIME_COMMIT = "d81235049384534c167caea52b85a694f6103d14"
CATALOGS = frozenset({"C1-C5", "M5", "v4-v7", "questions", "validation", "reserved", "protected", "finaltest"})
LIMITS = MappingProxyType({"input_tokens": 4096, "qa_tokens": 256, "request_seconds": 60,
    "startup_seconds": 120, "active_seconds": 900, "cleanup_seconds": 5, "whole_seconds": 1025,
    "quality_cases": 6, "total_completions": 13, "total_requested_tokens": 3328,
    "ctx": 6144, "parallel": 1, "gpu_layers": 99, "startup_available_bytes": 8 * 1024**3,
    "active_available_bytes": 2 * 1024**3, "native_rss_bytes": 6 * 1024**3})


class ContractError(ValueError):
    """A safe error code; no private source or answer in its message."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def need(value, code):
    if not value:
        raise ContractError("free_qa_" + code)


def canonical(value):
    return json.dumps(thaw(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    need(type(value) in (str, int, float, bool, type(None)), "policy_value")
    return value


def thaw(value):
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


def parse(data):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, "duplicate_key")
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=object_pairs,
                          parse_constant=lambda _: need(False, "nonfinite"))
    except (ValueError, UnicodeError) as error:
        raise ContractError("free_qa_json") from error


def exact(value, keys, code):
    need(isinstance(value, Mapping) and set(value) == set(keys.split()), code)


def digest_value(value):
    need(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "sha256")
    return value


def reference(value):
    exact(value, "file sha256 size_bytes", "reference")
    digest_value(value["sha256"])
    need(type(value["size_bytes"]) is int and value["size_bytes"] >= 0, "reference_size")
    name = value["file"]
    need(isinstance(name, str) and name and "\\" not in name and ":" not in name
         and not name.startswith("/") and all(x not in ("", ".", "..") for x in name.split("/")), "reference_path")
    return value


@dataclass(frozen=True)
class ModelPolicy:
    model_id: str
    profile_path: str
    profile_sha256: str
    shards: tuple
    entry: str
    alias: str
    reviewed: Mapping
    runtime: Mapping

    def __post_init__(self):
        for name in ("shards", "reviewed", "runtime"):
            object.__setattr__(self, name, freeze(getattr(self, name)))


@dataclass(frozen=True)
class EpochPolicy:
    name: str
    model_id: str
    calls: int
    active_seconds: int
    whole_seconds: int


EPOCHS = MappingProxyType({
    "neutral": EpochPolicy("neutral", CANDIDATE, 1, 60, 185),
    "baseline": EpochPolicy("baseline", BASE, 6, 900, 1025),
    "candidate": EpochPolicy("candidate", CANDIDATE, 6, 900, 1025),
})


@dataclass(frozen=True)
class ComparisonContract:
    data: Mapping
    sha256: str

    def __post_init__(self):
        object.__setattr__(self, "data", freeze(self.data))


def bind_policy(profile_bytes, reviewed_binding, runtime_refs):
    """No I/O or inferred metadata. A separate trusted lock must authorize this binding."""
    digest = sha(profile_bytes)
    matches = [key for key, value in PROFILE_PINS.items() if value[1] == digest]
    need(len(matches) == 1, "profile_pin")
    model_id = matches[0]
    profile = parse(profile_bytes)
    gguf = profile["gguf"]
    shards = [gguf] if model_id == BASE else gguf["shards"]
    shards = [{key: item[key] for key in ("filename", "size_bytes", "sha256")} for item in shards]
    need(len(shards) == (1 if model_id == BASE else 2), "shards")
    for shard in shards:
        need(isinstance(shard["filename"], str) and "/" not in shard["filename"]
             and "\\" not in shard["filename"] and shard["size_bytes"] > 0, "shard_name")
        digest_value(shard["sha256"])
    if model_id == CANDIDATE:
        need(sum(s["size_bytes"] for s in shards) == 4683073632
             and gguf["entry_filename"] == shards[0]["filename"], "split_entry")
    exact(runtime_refs, "root tag commit server files", "runtime")
    need(runtime_refs["tag"] == "b11429" and runtime_refs["commit"] == RUNTIME_COMMIT, "runtime_version")
    rows = runtime_refs["files"]
    need(isinstance(rows, list) and len(rows) == 55 and len({r["file"].casefold() for r in rows}) == 55, "runtime55")
    for row in rows:
        reference(row)
    need(runtime_refs["server"] in {r["file"] for r in rows}
         and runtime_refs["server"].split("/")[-1] == "llama-server.exe", "runtime_server")
    if model_id == CANDIDATE:
        pinned = profile["runtime_reuse"]["runtime_files"]
        need({r["file"]: {k: r[k] for k in ("size_bytes", "sha256")} for r in rows} == pinned, "runtime_pins")
    exact(reviewed_binding, "schema_version model_id profile_sha256 runtime_sha256 metadata template_sha256 tokenizer_sha256 metadata_receipt review_receipt acquisition_gate", "reviewed_binding")
    need(type(reviewed_binding["schema_version"]) is int and reviewed_binding["schema_version"] == 1
         and reviewed_binding["model_id"] == model_id and reviewed_binding["profile_sha256"] == digest
         and reviewed_binding["runtime_sha256"] == sha(canonical(runtime_refs)), "reviewed_profile_runtime")
    for key in ("metadata_receipt", "review_receipt", "acquisition_gate"):
        reference(reviewed_binding[key])
    metadata = reviewed_binding["metadata"]
    need(isinstance(metadata, list) and len(metadata) == len(shards), "reviewed_embedded_metadata")
    need(all(isinstance(row, dict) and row.get("version") == 3 and row.get("tensor_descriptors_or_payload_parsed") is False for row in metadata), "metadata_version")
    first = metadata[0]
    need(first.get("template") and first.get("tokenizer"), "unreviewed_template_tokenizer")
    need(first["template"]["raw_utf8_sha256"] == digest_value(reviewed_binding["template_sha256"])
         and sha(canonical(first["tokenizer"])) == digest_value(reviewed_binding["tokenizer_sha256"]), "metadata_digest")
    if model_id == CANDIDATE:
        from tools.free_qa.assets import validate_metadata
        validate_metadata(metadata)  # Qwen-only format checks; never applied to Ministral.
    else:
        need(first["scalars"].get("general.architecture", {}).get("type") == 8
             and isinstance(first["scalars"]["general.architecture"]["value"], str)
             and first["scalars"]["general.architecture"]["value"], "baseline_architecture_review")
    alias = sha(canonical({"profile_sha256": digest, "shards": shards}))
    return ModelPolicy(model_id, PROFILE_PINS[model_id][0], digest, freeze(shards), shards[0]["filename"],
                       alias, freeze(reviewed_binding), freeze(runtime_refs))


def validate_contract(contract, trusted_locks):
    """Trust comes from the separate fixed lock source, never registration-provided denylists."""
    exact(contract, "schema_version id models cases neutral order epochs limits code prompt exclusion criteria packet preflight_review", "contract")
    exact(trusted_locks, "schema_version contract_sha256 reviewed_bindings runtime_sha256 exclusion allowed_cases criteria packet code prompt predecessors preflight_review", "trusted_locks")
    need(type(contract["schema_version"]) is int and contract["schema_version"] == 1
         and type(trusted_locks["schema_version"]) is int and trusted_locks["schema_version"] == 1, "schema")
    need(isinstance(contract["id"], str) and contract["id"], "contract_id")
    exact(trusted_locks["reviewed_bindings"], BASE + " " + CANDIDATE, "trusted_models")
    exact(trusted_locks["predecessors"], "neutral baseline candidate", "trusted_epochs")
    need(sha(canonical(contract)) == trusted_locks["contract_sha256"], "trusted_contract")
    need(canonical(contract["limits"]) == canonical(LIMITS) and contract["epochs"] == ["neutral", "baseline", "candidate"], "limits_or_order")
    need(isinstance(contract["models"], list) and len(contract["models"]) == 2
         and [x["id"] for x in contract["models"]] == [BASE, CANDIDATE], "model_order")
    for model in contract["models"]:
        exact(model, "id profile binding runtime model_root asset_files", "model_contract")
        reference(model["profile"])
        reference(model["binding"])
        need((model["profile"]["file"], model["profile"]["sha256"]) == PROFILE_PINS[model["id"]]
             and model["binding"]["sha256"] == trusted_locks["reviewed_bindings"][model["id"]]
             and sha(canonical(model["runtime"])) == trusted_locks["runtime_sha256"], "trusted_model")
        need(isinstance(model["asset_files"], list) and model["asset_files"]
             and len({r["file"].casefold() for r in model["asset_files"]}) == len(model["asset_files"]), "asset_set")
        for row in model["asset_files"]:
            reference(row)
    for key in ("exclusion", "criteria", "packet", "preflight_review"):
        reference(contract[key])
        need(canonical(contract[key]) == canonical(trusted_locks[key]), "trusted_" + key)
    need(canonical(contract["code"]) == canonical(trusted_locks["code"])
         and canonical(contract["prompt"]) == canonical(trusted_locks["prompt"]), "trusted_code_prompt")
    cases = contract["cases"]
    need(isinstance(cases, list) and len(cases) == 6 and [row["id"] for row in cases] == contract["order"]
         == trusted_locks["allowed_cases"] and len(set(contract["order"])) == 6, "six_case_order")
    families, contents, questions = set(), set(), set()
    for row in cases:
        exact(row, "id family aliases ancestors content_sha256 question_sha256 input sidecar messages_sha256", "case")
        need(isinstance(row["aliases"], list) and isinstance(row["ancestors"], list), "case_lineage")
        lineage = [row["family"], *row["aliases"], *row["ancestors"]]
        need(all(isinstance(x, str) and x for x in lineage) and len(set(lineage)) == len(lineage)
             and not families.intersection(lineage), "family_overlap")
        need(row["content_sha256"] not in contents and row["question_sha256"] not in questions, "case_digest_overlap")
        families.update(lineage)
        contents.add(digest_value(row["content_sha256"]))
        questions.add(digest_value(row["question_sha256"]))
        digest_value(row["messages_sha256"])
        reference(row["input"])
        reference(row["sidecar"])
    exact(contract["neutral"], "id input sidecar content_sha256 question_sha256 messages_sha256", "neutral_case")
    reference(contract["neutral"]["input"])
    reference(contract["neutral"]["sidecar"])
    need(contract["neutral"]["id"] not in set(contract["order"])
         and digest_value(contract["neutral"]["content_sha256"]) not in contents
         and digest_value(contract["neutral"]["question_sha256"]) not in questions, "neutral_separate")
    digest_value(contract["neutral"]["messages_sha256"])
    return ComparisonContract(freeze(contract), sha(canonical(contract)))


def review_case_bindings(contract):
    """Opaque ordered source bindings only; never a case-to-verdict mapping."""
    keys = ("id", "input", "sidecar", "content_sha256", "question_sha256", "messages_sha256")
    return [{key: thaw(row[key]) for key in keys} for row in contract["cases"]]


def validate_preflight_review(review, contract):
    """The runner hashes this receipt against the separate custodian's fixed lock.

    Source-only reviewers own the private per-case classifications. Neither an
    approved flag nor a registrant-supplied aggregate is an authority here.
    """
    exact(review, "schema_version role comparison_id cases criteria aggregate", "preflight_review")
    need(type(review["schema_version"]) is int and review["schema_version"] == 1
         and review["role"] == "source-only-preflight-review"
         and review["comparison_id"] == contract["id"], "preflight_authority")
    need(canonical(review["cases"]) == canonical(review_case_bindings(contract))
         and canonical(review["criteria"]) == canonical(contract["criteria"]), "preflight_bindings")
    aggregate = review["aggregate"]
    exact(aggregate, "answerable abstained abstention_types source_kinds languages", "preflight_aggregate")
    need(type(aggregate["answerable"]) is int and aggregate["answerable"] == 4
         and type(aggregate["abstained"]) is int and aggregate["abstained"] == 2, "four_plus_two")
    exact(aggregate["abstention_types"], "insufficient unresolved_conflict", "preflight_abstentions")
    need(all(type(value) is int and value == 1 for value in aggregate["abstention_types"].values()), "two_abstention_types")
    for key, names in (("source_kinds", "single_document multiple_meetings mixed"), ("languages", "ko en mixed")):
        exact(aggregate[key], names, "preflight_coverage")
        counts = aggregate[key].values()
        need(all(type(count) is int and count > 0 for count in counts) and sum(counts) == 6, "preflight_coverage")
    return freeze(review)
