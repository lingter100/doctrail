"""Once-only C3 registration and native execution, with replayable stage traces.

No automatic adoption, retry, warmup, source selection or context truncation.
All public console errors are safe codes. Private text belongs only in artifacts.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import threading
import time
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

import psutil

from doctrail.meeting_answer_blocks import build_block_catalog
from doctrail.meeting_answer_requirements import (
    ANSWER_POLICY,
    DECODER_POLICY,
    abstained_answer,
    grounded_requirement_answer,
    parse_requirement_plan,
    realization_grammar,
    realization_messages,
    requirement_messages,
    requirement_plan_grammar,
)
from doctrail.meeting_contract import AnswerRequest, strict_json
from doctrail.meeting_gguf import GREEDY, MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, _same_setting
from doctrail.meeting_qwen35 import (
    GGUF_SHA256,
    MODEL_ID,
    MODEL_REVISION,
    NONTHINKING_PREAMBLE,
    PREAMBLE_SHA256,
)
from doctrail.meeting_requirements_review import COUNTS, validate_attestation, validate_oracles
from doctrail.meeting_requirements_runtime import (
    RequirementsGenerator,
    RequirementsGGUFGenerator,
    RequirementsRuntime,
)
from scripts import prepare_meeting_requirements_inputs as prep
from scripts.prepare_meeting_budget_inputs import _tokenizer_metadata, canonical, encoded
from scripts.probe_meeting_answer_review import native_service, safe_error
from scripts.probe_meeting_blocks_resources import rss_samples

ROOT = Path(__file__).resolve().parents[1]
BYTE_LIMIT = 16 * 1024 * 1024
LIMITS = {"input_tokens_per_stage": 5120, "output_tokens_per_stage": 384,
    "output_tokens_per_request": 768, "context_tokens": 6144, "request_seconds": 90,
    "cleanup_seconds": 5, "request_through_cleanup_seconds": 120, "phase_seconds": 2400,
    "neutral_native_calls": 4, "calibration_native_calls": 12, "validation_native_calls": 16,
    "total_native_calls": 32, "warmup_calls": 0, "retries": 0, "metadata_restarts": 1}
EXCLUDED_ROLES = {"/root", "/root/c2_comparison_runner", "/root/c2_budget_followup",
                  "/root/meeting_span_semantic", "/root/requirements_candidate",
                  "/root/knowledge_recovery_review"}
STRESS_GRAMMAR = 'root ::= ("load "){700}\n'


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def finite(value, limit, *, inclusive=True):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value and (value <= limit if inclusive else value < limit)


def path(name, root=ROOT, *, local=False):
    result = prep.relative(name, root)
    if local:
        prep.contained(result, root=root, output=True)
    return result


def named(value, root=ROOT):
    return prep.contained(value, root=root).relative_to(Path(root).resolve()).as_posix()


def phase_path(name, phase, root=ROOT):
    item = path(name, root)
    parts = Path(name).parts
    prefix = f"meetings-c3-{phase}-"
    if not ((len(parts) >= 4 and parts[:2] == ("data", "evaluation") and parts[2].startswith(prefix))
            or (len(parts) >= 3 and parts[0] == ".local" and parts[1].startswith(prefix))):
        raise ValueError("c3_phase_path")
    return item


def survey_path(name, phase, root=ROOT):
    if name not in {f"data/evaluation/meetings-c3-{phase}-inputs-v1/receipt.json",
                    f".local/meetings-c3-{phase}-prepared-v1/receipt.json"}:
        raise ValueError("c3_preparation_metadata_path")
    return path(name, root)


def ref(value, root=ROOT):
    if not isinstance(value, dict) or set(value) != {"file", "sha256"} or not digest(value["sha256"]):
        raise ValueError("c3_reference")
    return path(value["file"], root)


class Snapshots:
    def __init__(self, root=ROOT):
        self.root, self.raw, self.hashes = Path(root), {}, {}

    def get(self, name, expected=None):
        target = path(name, self.root)
        if name not in self.raw:
            with target.open("rb") as stream:
                raw = stream.read(BYTE_LIMIT + 1)
            if len(raw) > BYTE_LIMIT:
                raise ValueError("c3_snapshot_limit")
            self.raw[name], self.hashes[name] = raw, sha(raw)
        if expected is not None and self.hashes[name] != expected:
            raise ValueError("c3_hash_changed")
        return self.raw[name]

    def read(self, reference):
        ref(reference, self.root)
        return strict_json(self.get(reference["file"], reference["sha256"]).decode("utf-8"))

    def unchanged(self):
        current = Snapshots(self.root)
        for name, value in self.hashes.items():
            current.get(name, value)


def write_new(name, value, root=ROOT):
    target = path(name, root)
    raw = encoded(value)
    if len(raw) > BYTE_LIMIT:
        raise ValueError("c3_artifact_limit")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return {"file": name, "sha256": sha(raw)}


def save(directory, report, root=ROOT):
    target = path(directory, root, local=True) / "report.json"
    temporary = path(target.with_suffix(".tmp").relative_to(Path(root).resolve()).as_posix(), root)
    raw = encoded(report)
    if len(raw) > BYTE_LIMIT:
        raise ValueError("c3_artifact_limit")
    with temporary.open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    for index, delay in enumerate((.02, .05, 0)):
        try:
            temporary.replace(target)
            return
        except PermissionError:
            if index == 2:
                raise
            time.sleep(delay)


def verify_code(reference, snapshots):
    if reference.get("file") != prep.TOOLCHAIN_FREEZE:
        raise ValueError("c3_code_freeze_path")
    code = snapshots.read(reference)
    candidate = snapshots.read({"file": prep.CANDIDATE_FREEZE, "sha256": prep.CANDIDATE_FREEZE_SHA256})
    expected = set(prep.bindings(candidate)) | prep.NEW_FILES | prep.REUSED_FILES | {prep.CANDIDATE_FREEZE, prep.CONTRACT}
    bindings = prep.bindings(code)
    if (set(code) != {"schema_version", "candidate", "kind", "bound_files"}
            or type(code["schema_version"]) is not int or code["schema_version"] != 1
            or code["candidate"] != ANSWER_POLICY or code["kind"] != "toolchain"
            or len(prep.bindings(candidate)) != 28 or set(bindings) != expected
            or bindings[prep.CANDIDATE_FREEZE] != prep.CANDIDATE_FREEZE_SHA256
            or bindings[prep.CONTRACT] != prep.CONTRACT_SHA256
            or any(bindings[n] != h for n, h in prep.bindings(candidate).items())):
        raise ValueError("c3_code_contract")
    for name, value in bindings.items():
        snapshots.get(name, value)
    return bindings


def common(plan, snapshots):
    if (type(plan.get("schema_version")) is not int or plan["schema_version"] != 1
            or plan.get("candidate") != ANSWER_POLICY or fingerprint(plan.get("limits")) != fingerprint(LIMITS)
            or not digest(plan.get("runtime_receipt_sha256"))):
        raise ValueError("c3_plan_contract")
    bindings = verify_code(plan["code_freeze"], snapshots)
    if plan.get("bound_files") != bindings or plan.get("registry") != {"file": prep.REGISTRY, "sha256": bindings[prep.REGISTRY]}:
        raise ValueError("c3_registry_or_code_binding")
    _tokenizer_metadata(plan["tokenizer"])
    return bindings


def metadata_paths(plan, root=ROOT):
    """All shared refs and both phase namespaces checked before any semantic read."""
    if set(plan.get("phases", {})) != set(COUNTS) or set(plan.get("audit", {})) != set(COUNTS):
        raise ValueError("c3_phase_registration")
    excluded = plan.get("excluded_roles")
    if (not isinstance(excluded, list) or len(set(excluded)) != len(excluded)
            or any(not isinstance(x, str) or not x for x in excluded) or not EXCLUDED_ROLES <= set(excluded)):
        raise ValueError("c3_excluded_roles")
    protected, reviewers = [path(LEDGER, root)], []
    for phase, count in COUNTS.items():
        spec, audit = plan["phases"][phase], plan["audit"][phase]
        if (set(spec) != {"case_ids", "input", "oracle", "item_freeze", "source_freeze", "preparation_receipt", "output_dir"}
                or set(audit) != {"reviewer_id", "seed", "output_dir", "attestation"}
                or len(spec["case_ids"]) != count or len(set(spec["case_ids"])) != count
                or any(not isinstance(i, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", i) for i in spec["case_ids"])
                or not isinstance(audit["reviewer_id"], str) or not audit["reviewer_id"]
                or audit["reviewer_id"] in excluded):
            raise ValueError("c3_audit_registration")
        reviewers.append(audit["reviewer_id"])
        for role in ("input", "oracle", "item_freeze", "source_freeze", "preparation_receipt"):
            ref(spec[role], root)
            protected.append(phase_path(spec[role]["file"], phase, root))
        survey_path(spec["preparation_receipt"]["file"], phase, root)
        if (audit["output_dir"] != f".local/meetings-c3-audit-{phase}-v1"
                or spec["output_dir"] != f".local/meetings-c3-run-{phase}-v1"):
            raise ValueError("c3_audit_directory")
        for role in ("seed", "attestation"):
            filename = "seed.bin" if role == "seed" else "attestation.json"
            if audit[role].get("file") != f".local/meetings-c3-review-metadata-v1/{phase}/{filename}":
                raise ValueError("c3_review_metadata_path")
            protected.append(ref(audit[role], root))
            path(audit[role]["file"], root, local=True)
        protected.extend(path(v["output_dir"], root, local=True) for v in (spec, audit))
    if len(set(reviewers)) != 2:
        raise ValueError("c3_judge_separation")
    for role in ("code_freeze", "registry", "resource_plan", "resource_report"):
        protected.append(ref(plan[role], root))
    if plan["code_freeze"]["file"] != prep.TOOLCHAIN_FREEZE or plan["registry"]["file"] != prep.REGISTRY:
        raise ValueError("c3_metadata_path")
    for role in ("resource_plan", "resource_report"):
        name = plan[role]["file"]
        if not name.startswith(("data/evaluation/meetings-c3-neutral-", "experiments/results/meetings-c3-resources-",
                                ".local/meetings-c3-neutral-")):
            raise ValueError("c3_resource_path")
    for index, target in enumerate(protected):
        if any(target.is_relative_to(other) or other.is_relative_to(target) for other in protected[:index]):
            raise ValueError("c3_path_collision")
        if target.exists() and any(other.exists() and target.samefile(other) for other in protected[:index]):
            raise ValueError("c3_path_alias")
    for name in plan.get("bound_files", {}):
        target = path(name, root)
        # Registry is intentionally a shared code metadata binding.
        if name == prep.REGISTRY:
            continue
        if any(target.is_relative_to(p) or p.is_relative_to(target) for p in protected):
            raise ValueError("c3_code_data_collision")


def verify_preparation(receipt, phase, plan, spec, snapshots):
    count = COUNTS[phase]
    rows = receipt.get("cases", [])
    if (receipt.get("candidate") != ANSWER_POLICY or receipt.get("phase") != phase
            or receipt.get("status") != "passed" or receipt.get("errors") != []
            or receipt.get("payloads_preserved") is not True or receipt.get("stage2_readiness") != "dynamic_unmeasured"
            or receipt.get("input_sha256") != spec["input"]["sha256"]
            or receipt.get("bound_files") != plan["bound_files"]
            or fingerprint(receipt.get("tokenizer")) != fingerprint(plan["tokenizer"])
            or any(type(receipt.get(k)) is not int or receipt[k] != 0 for k in ("model_calls", "native_calls", "downloads"))
            or [r.get("id") for r in rows] != spec["case_ids"]
            or any(type(receipt.get("summary", {}).get(k)) is not int or receipt["summary"][k] != v
                   for k, v in {"total_cases": count, "measured_cases": count, "unmeasured_cases": 0, "failed_cases": 0}.items())):
        raise ValueError("c3_preparation_receipt")
    for reference in (spec["oracle"], spec["source_freeze"], spec["item_freeze"], plan["code_freeze"]):
        if receipt.get("snapshots", {}).get(reference["file"], {}).get("sha256") != reference["sha256"]:
            raise ValueError("c3_preparation_snapshot")
    for row in rows:
        if (type(row.get("official_stage1_tokens")) is not int or not 0 < row["official_stage1_tokens"] <= 5120
                or row.get("error_code") is not None or row.get("payload_preserved") is not True
                or row.get("stage2_readiness") != "dynamic_unmeasured"):
            raise ValueError("c3_preparation_count")
    values = [r["official_stage1_tokens"] for r in rows]
    if receipt["summary"].get("min_stage1_tokens") != min(values) or receipt["summary"].get("max_stage1_tokens") != max(values):
        raise ValueError("c3_preparation_summary")


def load_phase(plan, phase, snapshots):
    spec = plan["phases"][phase]
    # Metadata freezes first; every transitive name is checked before any bound body.
    source, item = snapshots.read(spec["source_freeze"]), snapshots.read(spec["item_freeze"])
    source_roles, item_roles = prep.freeze_roles(source, "source", phase), prep.freeze_roles(item, "item", phase)
    for freeze in (source, item):
        for name in prep.bindings(freeze):
            if name != prep.TOOLCHAIN_FREEZE:
                phase_path(name, phase, snapshots.root)
    if (item_roles["oracle"] != spec["oracle"]["file"] or item_roles["source_freeze"] != spec["source_freeze"]["file"]
            or item_roles["code_freeze"] != prep.TOOLCHAIN_FREEZE
            or prep.bindings(item).get(item_roles["oracle"]) != spec["oracle"]["sha256"]
            or prep.bindings(item).get(item_roles["source_freeze"]) != spec["source_freeze"]["sha256"]
            or prep.bindings(item).get(prep.TOOLCHAIN_FREEZE) != plan["code_freeze"]["sha256"]):
        raise ValueError("c3_item_binding")
    for freeze in (source, item):
        for name, value in prep.bindings(freeze).items():
            snapshots.get(name, value)
    manifest = strict_json(snapshots.get(source_roles["manifest"], source["bound_files"][source_roles["manifest"]]).decode())
    authors = set()
    for family in manifest["families"]:
        for source_row in family["sources"]:
            authors.add(source_row["adoption_author_role"])
            if family["origin"] == "synthetic":
                authors.add(source_row["synthetic_provenance"]["author_role"])
    if not authors <= set(plan["excluded_roles"]):
        raise ValueError("c3_source_author_exclusion")
    for roles, freeze in ((source_roles, source), (item_roles, item)):
        review = strict_json(snapshots.get(roles["prereview"], prep.bindings(freeze)[roles["prereview"]]).decode())
        roles_seen = {review["reviewer_id"], *review["author_ids"]}
        if not roles_seen <= set(plan["excluded_roles"]):
            raise ValueError("c3_source_author_exclusion")
    receipt = snapshots.read(spec["preparation_receipt"])
    verify_preparation(receipt, phase, plan, spec, snapshots)
    inputs = snapshots.read(spec["input"])
    draft = strict_json(snapshots.get(item_roles["draft"], prep.bindings(item)[item_roles["draft"]]).decode())
    if receipt["snapshots"].get(item_roles["draft"], {}).get("sha256") != prep.bindings(item)[item_roles["draft"]]:
        raise ValueError("c3_draft_binding")
    prep.validate_draft(draft, phase)
    if (type(inputs.get("schema_version")) is not int or inputs["schema_version"] != 1 or inputs.get("phase") != phase
            or [c.get("id") for c in inputs.get("cases", [])] != spec["case_ids"]):
        raise ValueError("c3_input_contract")
    for case, original, row in zip(inputs["cases"], draft["cases"], receipt["cases"], strict=True):
        if (set(case) != {"id", "response_language", "payload", "official_stage1_tokens"}
                or fingerprint({k: case[k] for k in original}) != fingerprint(original)
                or type(case["official_stage1_tokens"]) is not int or case["official_stage1_tokens"] != row["official_stage1_tokens"]):
            raise ValueError("c3_original_payload")
        request = AnswerRequest.model_validate(case["payload"])
        catalog = build_block_catalog(request.contexts)
        if (row["payload_sha256"] != fingerprint(case["payload"]) or row["response_language"] != case["response_language"]
                or row["stage1_prompt_sha256"] != fingerprint(requirement_messages(request.query, catalog, case["response_language"]))
                or row["stage1_grammar_sha256"] != sha(requirement_plan_grammar(catalog).encode())
                or row["supplied_units"] != len(catalog.spans)):
            raise ValueError("c3_stage1_binding")
    oracle = snapshots.read(spec["oracle"])
    validate_oracles(inputs, oracle, phase)
    if any(not {o[k] for k in ("question_author", "oracle_author", "independent_prereviewer")}
           <= set(plan["excluded_roles"]) for o in oracle["cases"]):
        raise ValueError("c3_oracle_author_exclusion")
    return inputs, receipt


def check_model(metadata):
    runtime, nonthinking = metadata.get("runtime", {}), metadata.get("nonthinking", {})
    if (metadata.get("repo_id") != MODEL_ID or metadata.get("original_revision") != MODEL_REVISION
            or metadata.get("revision") != "gguf-sha256:" + GGUF_SHA256
            or metadata.get("artifact", {}).get("sha256") != GGUF_SHA256
            or metadata.get("generation_protocol") != ANSWER_POLICY
            or any(type(runtime.get(k)) is not int or runtime[k] != v for k, v in
                   {"context_tokens": 6144, "max_input_tokens": 5120, "max_new_tokens": 384, "deadline_seconds": 90}.items())
            or runtime.get("backend") != "llama.cpp"
            or runtime.get("tag") != "b11429"
            or runtime.get("commit") != "d81235049384534c167caea52b85a694f6103d14"
            or not re.search(r"b11429[- ]d81235049", str(runtime.get("observed_build", "")))
            or runtime.get("identity_check") != "local_gguf_sha256_and_server_alias"
            or nonthinking.get("enable_thinking_requested") is not False
            or nonthinking.get("assistant_preamble_sha256") != PREAMBLE_SHA256):
        raise ValueError("c3_model_identity")


def check_trace(stage, messages, grammar, metadata, *, expected_tokens=None, finish="eos"):
    """Replay messages -> template -> tokens -> payload -> native response, no tokenizer."""
    template, tokenize, payload, native = (stage.get(k, {}) for k in ("template", "tokenize", "payload", "raw_response"))
    rendered = template.get("response", {}).get("prompt")
    tokens = tokenize.get("response", {}).get("tokens")
    if (stage.get("status") != "returned" or stage.get("dispatch_started") is not True
            or stage.get("messages_sha256") != fingerprint(messages)
            or fingerprint(template.get("request")) != fingerprint({"messages": messages, "chat_template_kwargs": {"enable_thinking": False}})
            or not isinstance(rendered, str) or not rendered.endswith(NONTHINKING_PREAMBLE)
            or stage.get("rendered_sha256") != sha(rendered.encode())
            or fingerprint(tokenize.get("request")) != fingerprint({"content": rendered, "add_special": False, "parse_special": True, "with_pieces": False})
            or not isinstance(tokens, list) or not 0 < len(tokens) <= 5120
            or any(type(t) is not int or t < 0 for t in tokens)
            or expected_tokens is not None and len(tokens) != expected_tokens
            or fingerprint(payload) != fingerprint({**GREEDY, "prompt": tokens, "n_predict": 384, "grammar": grammar, "cache_prompt": False, "return_tokens": True})
            or stage.get("payload_sha256") != fingerprint(payload)
            or stage.get("grammar_sha256") != sha(grammar.encode())
            or type(stage.get("input_tokens")) is not int or stage["input_tokens"] != len(tokens)
            or any(len(json.dumps(v, ensure_ascii=False).encode()) > MAX_REQUEST_BYTES
                   for v in (template["request"], tokenize["request"], payload))
            or any(len(json.dumps(v, ensure_ascii=False).encode()) > MAX_RESPONSE_BYTES
                   for v in (native, template.get("response"), tokenize.get("response")))):
        raise ValueError("c3_native_trace")
    settings, timings = native.get("generation_settings", {}), native.get("timings", {})
    expected = {**GREEDY, "n_predict": 384, "grammar": grammar}
    if (any(k not in settings or not _same_setting(settings[k], v) for k, v in expected.items())
            or native.get("model") != metadata["artifact"]["sha256"] or native.get("stop") is not True
            or native.get("truncated") is not False or native.get("stop_type") != ("limit" if finish == "length" else "eos")
            or type(native.get("tokens_evaluated")) is not int or native["tokens_evaluated"] != len(tokens)
            or type(native.get("tokens_predicted")) is not int or not 0 < native["tokens_predicted"] <= 384
            or finish == "length" and native["tokens_predicted"] != 384
            or not isinstance(native.get("content"), str)
            or type(timings.get("cache_n")) is not int or timings["cache_n"] != 0
            or type(timings.get("prompt_n")) is not int or timings["prompt_n"] != len(tokens)
            or type(timings.get("predicted_n")) is not int or not 0 < timings["predicted_n"] <= 384
            or any(not finite(timings.get(k), 90000) for k in ("prompt_ms", "predicted_ms"))):
        raise ValueError("c3_native_observation")
    config = {"backend": "llama.cpp", **expected, "cache_prompt_requested": False,
        "observed_cache_tokens": 0, "observed_nonthinking_preamble_sha256": PREAMBLE_SHA256,
        "enable_thinking_requested": False}
    if fingerprint(stage.get("effective_config")) != fingerprint(config):
        raise ValueError("c3_effective_config")


def replay_request(case, row, calls, metadata):
    request = AnswerRequest.model_validate(case["payload"])
    language = case["response_language"]
    catalog = build_block_catalog(request.contexts)
    if (not request.contexts or row.get("id") != case["id"] or row.get("status") != "passed"
            or row.get("payload_sha256") != fingerprint(case["payload"])
            or row.get("response_language") != language or not 1 <= len(calls) <= 2
            or [c.get("stage") for c in calls] != list(range(1, len(calls) + 1))
            or any(c.get("case_id") != case["id"] for c in calls)
            or not finite(row.get("elapsed_ms"), 90000, inclusive=False)
            or row.get("watchdog_fired") is not False or row.get("watchdog_joined") is not True):
        raise ValueError("c3_request_integrity")
    first = calls[0]
    check_trace(first, requirement_messages(request.query, catalog, language), requirement_plan_grammar(catalog),
                metadata, expected_tokens=case["official_stage1_tokens"])
    plan = parse_requirement_plan(first["raw_response"]["content"], catalog, language)
    if len(calls) != (2 if plan.supported else 1):
        raise ValueError("c3_stage_branch")
    answer = abstained_answer()
    if plan.supported:
        check_trace(calls[1], realization_messages(request.query, catalog, plan, language),
                    realization_grammar(plan, catalog, language), metadata)
        answer = grounded_requirement_answer(calls[1]["raw_response"]["content"], catalog, request.contexts, plan, language)
    telemetry = row.get("telemetry", {})
    expected_identity = {**metadata, "answer_decoder": {"policy": DECODER_POLICY, "answer_policy": ANSWER_POLICY,
        "grammar_sha256": None, "grammar_scope": "current_stage_catalog_or_requirement_ids",
        "guarantee_scope": "structure_and_catalog_membership_only"}}
    if (row.get("answer") != answer or row.get("plan_sha256") != fingerprint(plan.payload())
            or fingerprint(telemetry.get("resource_identity")) != fingerprint(expected_identity)
            or telemetry.get("answer_policy") != ANSWER_POLICY
            or telemetry.get("semantic_support_verified") is not False
            or telemetry.get("question_completeness_verified") is not False
            or telemetry.get("requirements") != [{"requirement_id": r.requirement_id,
                "status": r.status, "evidence_count": len(r.evidence_ids)} for r in plan.requirements]
            or row.get("stage2_readiness") != ("measured_at_runtime" if plan.supported else "not_required")
            or any(type(telemetry.get(k)) is not int or telemetry[k] != len(calls)
                   for k in ("completion_attempts", "completed_stages", "validated_stages"))
            or telemetry.get("response_language") != language or telemetry.get("language_source") != "explicit"
            or "error_code" in telemetry or not finite(telemetry.get("elapsed_ms"), 90000, inclusive=False)
            or telemetry["elapsed_ms"] > row["elapsed_ms"] + 1 or not finite(telemetry.get("cleanup_ms"), 5000)
            or len(telemetry.get("calls", [])) != len(calls)):
        raise ValueError("c3_answer_replay")
    for metric, call in zip(telemetry["calls"], calls, strict=True):
        native = call["raw_response"]
        if (metric.get("stage") != call["stage"] or metric.get("input_tokens") != call["input_tokens"]
                or type(metric.get("output_token_limit")) is not int or metric["output_token_limit"] != 384
                or not finite(metric.get("completion_wrapper_ms"), 90000, inclusive=False)
                or metric.get("output_tokens") != native["tokens_predicted"] or metric.get("finish_reason") != "eos"
                or metric.get("grammar_sha256") != call["grammar_sha256"]
                or metric.get("native_timings") != {k: v for k, v in native["timings"].items()
                    if k in {"cache_n", "prompt_n", "prompt_ms", "predicted_n", "predicted_ms"} and type(v) in (int, float)}
                or not finite(metric.get("elapsed_seconds"), 90, inclusive=False)
                or metric["elapsed_seconds"] * 1000 > telemetry["elapsed_ms"] + 1):
            raise ValueError("c3_stage_telemetry")
    return answer, plan.payload()


LEDGER = ".local/meetings-c3-native-ledger-v1.json"


def model_free_gate(plan, plan_sha, phase, gate_path, root):
    if phase != "validation":
        return None
    from scripts.audit_meeting_requirements import verify_validation_gate
    return verify_validation_gate(plan, plan_sha, gate_path, root=root)


def read_plan(plan_path, root=ROOT):
    snapshots = Snapshots(root)
    name = named(plan_path, root)
    parts = Path(name).parts
    if not (name.endswith(".json") and "-plan-" in parts[-1] and
            (len(parts) == 3 and name.startswith("data/evaluation/meetings-c3-")
             or len(parts) == 2 and name.startswith(".local/meetings-c3-"))):
        raise ValueError("c3_plan_path")
    raw = snapshots.get(name)
    return strict_json(raw.decode()), sha(raw), snapshots, name


def validate_review_metadata(plan, snapshots):
    """Check both metadata namespaces before reading either seed or attestation.

    This UTC instant is a preflight cutoff, not a future pack disclosure time.
    The audit independently checks its actual pack disclosure timestamp later.
    """
    metadata_paths(plan, snapshots.root)
    checked_at = datetime.now(UTC).isoformat()
    for phase in COUNTS:
        registration = plan["audit"][phase]
        seed = snapshots.get(registration["seed"]["file"], registration["seed"]["sha256"])
        if not 32 <= len(seed) <= 128:
            raise ValueError("c3_seed_length")
        attestation = snapshots.read(registration["attestation"])
        validate_attestation(attestation, registration["reviewer_id"], plan["excluded_roles"],
                             pack_opened_at=checked_at)


def check(plan_path, phase, gate_path=None, *, root=ROOT):
    plan, plan_sha, snapshots, name = read_plan(plan_path, root)
    if phase not in COUNTS or plan.get("kind") != "quality":
        raise ValueError("c3_quality_plan")
    validate_review_metadata(plan, snapshots)
    common(plan, snapshots)
    gate = model_free_gate(plan, plan_sha, phase, gate_path, root)
    resource = resource_evidence(plan, snapshots)
    inputs, receipt = load_phase(plan, phase, snapshots)
    expected_ledger = resource["ledger_entries"] if phase == "calibration" else gate["ledger_entries"]
    return {"plan": plan, "plan_sha256": plan_sha, "plan_file": name, "snapshots": snapshots,
        "phase": phase, "cases": inputs["cases"], "receipt": receipt, "gate": gate, "gate_path": gate_path,
        "output_dir": plan["phases"][phase]["output_dir"], "root": Path(root), "expected_ledger": expected_ledger}


def verify(prepared):
    if prepared["phase"] != "neutral":
        # Fresh, bounded metadata snapshots reject drift even before gate replay.
        # The original preflight snapshots also retain all four SHA bindings.
        validate_review_metadata(prepared["plan"], Snapshots(prepared["root"]))
    # Replaying selection always precedes hashing held-out input snapshots.
    gate = model_free_gate(prepared["plan"], prepared["plan_sha256"], prepared["phase"],
                           prepared.get("gate_path"), prepared["root"])
    if gate != prepared.get("gate"):
        raise ValueError("c3_gate_changed")
    original = strict_json(prepared["snapshots"].get(prepared["plan_file"], prepared["plan_sha256"]).decode())
    if fingerprint(original) != fingerprint(prepared["plan"]):
        raise ValueError("c3_prepared_plan_changed")
    if prepared["phase"] == "neutral" and original["kind"] == "neutral":
        expected_cases = [original["normal"], {"id": "stress"}]
        expected_output = original["output_dir"]
    elif prepared["phase"] in COUNTS and original["kind"] == "quality":
        spec = original["phases"][prepared["phase"]]
        expected_cases = prepared["snapshots"].read(spec["input"])["cases"]
        expected_output = spec["output_dir"]
    else:
        raise ValueError("c3_prepared_phase_changed")
    if fingerprint(prepared["cases"]) != fingerprint(expected_cases) or prepared["output_dir"] != expected_output:
        raise ValueError("c3_prepared_payload_changed")
    prepared["snapshots"].unchanged()


def report_integrity(report, plan, plan_sha, phase, expected_ids):
    if (type(report.get("schema_version")) is not int or report["schema_version"] != 1
            or report.get("candidate") != ANSWER_POLICY or report.get("plan_sha256") != plan_sha
            or report.get("phase") != phase or report.get("status") != "completed"
            or report.get("bound_files") != plan["bound_files"]
            or report.get("code_freeze") != plan["code_freeze"]
            or report.get("sources_unchanged") is not True or report.get("processes_stopped") is not True
            or report.get("metadata_recovery") is not True or report.get("unexecuted") != []
            or type(report.get("metadata_restart_attempts")) is not int or report["metadata_restart_attempts"] != 1
            or any(k in report for k in ("failure", "source_error", "recovery_error", "integrity_error"))
            or any(type(report.get(k)) is not int or report[k] != 0 for k in
                   ("native_log_bytes", "paid_calls", "warmup_calls", "retries", "human_review_count", "recovery_native_calls"))
            or [r.get("id") for r in report.get("results", [])] != expected_ids
            or len(report.get("calls", [])) > LIMITS[phase + "_native_calls"]
            or any(type(c.get("sequence")) is not int or type(c.get("stage")) is not int for c in report["calls"])
            or [c.get("sequence") for c in report["calls"]] != list(range(len(report["calls"])))):
        raise ValueError("c3_report_incomplete")
    for key, limit in (("owned_cleanup_ms", 5000), ("recovery_cleanup_ms", 5000),
                       ("last_request_through_cleanup_ms", 120000), ("elapsed_seconds", 2400)):
        if not finite(report.get(key), limit):
            raise ValueError("c3_resource_time")
    for row in report["results"]:
        if (type(row.get("native_rss_sample_count")) is not int or row["native_rss_sample_count"] <= 0
                or not finite(row.get("native_rss_max_sample_mib"), 10**9)
                or any(type(row.get(k)) is not int or row[k] <= 0
                       for k in ("available_ram_before_bytes", "available_ram_after_bytes"))):
            raise ValueError("c3_memory_observation")
    check_model(report["model_runtime"])
    check_model(report["recovered_identity"])
    if fingerprint(report["model_runtime"]) != fingerprint(report["recovered_identity"]):
        raise ValueError("c3_recovery_identity")
    entries = report.get("ledger_entries", [])
    own = [{"phase": phase, "plan_sha256": plan_sha, "case_id": c["case_id"],
            "stage": c["stage"], "sequence": c["sequence"]} for c in report["calls"]]
    if (not own or entries[-len(own):] != own or len(entries) > 32
            or type(report.get("actual_native_posts")) is not int or report["actual_native_posts"] != len(own)):
        raise ValueError("c3_call_ledger")


def resource_evidence(plan, snapshots):
    registration, report = snapshots.read(plan["resource_plan"]), snapshots.read(plan["resource_report"])
    neutral_check(registration, snapshots)
    if (registration.get("kind") != "neutral" or registration.get("code_freeze") != plan["code_freeze"]
            or registration.get("bound_files") != plan["bound_files"]
            or registration.get("runtime_receipt_sha256") != plan["runtime_receipt_sha256"]
            or registration.get("survey_receipts") != {phase: plan["phases"][phase]["preparation_receipt"] for phase in COUNTS}
            or fingerprint(registration.get("tokenizer")) != fingerprint(plan["tokenizer"])):
        raise ValueError("c3_resource_binding")
    validate_neutral_report(registration, plan["resource_plan"]["sha256"], report)
    return report


class Observer:
    def __init__(self, prepared, report):
        self.prepared, self.report = prepared, report
        self.row, self.case, self.current, self.deadline = None, None, None, None
        self.stress = False

    def expected(self, stage):
        if self.stress:
            item = self.prepared["plan"]["stress"][stage - 1]
            return item["messages"], STRESS_GRAMMAR, item["official_tokens"]
        request = AnswerRequest.model_validate(self.case["payload"])
        catalog = build_block_catalog(request.contexts)
        language = self.case["response_language"]
        if stage == 1:
            return requirement_messages(request.query, catalog, language), requirement_plan_grammar(catalog), self.case["official_stage1_tokens"]
        first = next(c for c in self.report["calls"] if c["case_id"] == self.case["id"] and c["stage"] == 1)
        plan = parse_requirement_plan(first["raw_response"]["content"], catalog, language)
        return realization_messages(request.query, catalog, plan, language), realization_grammar(plan, catalog, language), None

    def before_complete(self, messages, deadline, token_limit, grammar):
        if self.row is None or self.current is None or token_limit != 384 or time.monotonic() >= self.deadline:
            raise ValueError("c3_hidden_or_late_completion")
        expected_messages, expected_grammar, count = self.expected(self.current["stage"])
        tokens = self.current["tokenize"]["response"]["tokens"]
        if (fingerprint(messages) != fingerprint(expected_messages) or grammar != expected_grammar
                or not 0 < len(tokens) <= 5120 or count is not None and count != len(tokens)):
            raise ValueError("c3_stage_dispatch_binding")
        self.current.update(grammar_sha256=sha(grammar.encode()), input_tokens=len(tokens))
        return min(deadline, self.deadline)

    def request(self, send, method, route, payload, deadline):
        if route == "/props" and method == "GET" and self.row is None:
            return send()
        if self.row is None or method != "POST" or time.monotonic() >= self.deadline:
            raise ValueError("c3_unregistered_native_request")
        if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_REQUEST_BYTES:
            raise ValueError("c3_request_bytes")
        if route == "/apply-template":
            stage = len(self.row["preparations"]) + 1
            if stage > 2 or self.current is not None and self.current.get("status") != "returned":
                raise ValueError("c3_duplicate_preparation")
            messages, _, _ = self.expected(stage)
            if payload != {"messages": messages, "chat_template_kwargs": {"enable_thinking": False}}:
                raise ValueError("c3_template_binding")
            self.current = {"case_id": self.case["id"], "stage": stage, "messages_sha256": fingerprint(messages),
                            "template": {"request": copy.deepcopy(payload)}, "status": "preparing"}
            self.row["preparations"].append(self.current)
            response = send()
            self.current["template"]["response"] = copy.deepcopy(response)
            prompt = response.get("prompt")
            if not isinstance(prompt, str) or not prompt.endswith(NONTHINKING_PREAMBLE):
                raise ValueError("c3_template_preamble")
            self.current["rendered_sha256"] = sha(prompt.encode())
            return response
        if route == "/tokenize":
            if self.current is None or "tokenize" in self.current:
                raise ValueError("c3_duplicate_tokenize")
            rendered = self.current["template"]["response"]["prompt"]
            if payload != {"content": rendered, "add_special": False, "parse_special": True, "with_pieces": False}:
                raise ValueError("c3_tokenize_binding")
            response = send()
            self.current["tokenize"] = {"request": copy.deepcopy(payload), "response": copy.deepcopy(response)}
            save(self.prepared["output_dir"], self.report, self.prepared["root"])
            return response
        if route != "/completion" or self.current is None or self.current.get("dispatch_started"):
            raise ValueError("c3_unregistered_completion")
        verify(self.prepared)
        messages, grammar, _count = self.expected(self.current["stage"])
        self.before_complete(messages, deadline, payload.get("n_predict"), payload.get("grammar"))
        tokens = self.current["tokenize"]["response"]["tokens"]
        if (payload != {**GREEDY, "prompt": tokens, "grammar": grammar, "n_predict": 384,
                       "cache_prompt": False, "return_tokens": True}
                or len(self.report["calls"]) >= LIMITS[self.prepared["phase"] + "_native_calls"]):
            raise ValueError("c3_native_budget")
        call = self.current
        call.update(sequence=len(self.report["calls"]), dispatch_started=True, status="started",
                    payload=copy.deepcopy(payload), payload_sha256=fingerprint(payload))
        self.report["calls"].append(call)
        entry = {"phase": self.prepared["phase"], "plan_sha256": self.prepared["plan_sha256"],
                 "case_id": call["case_id"], "stage": call["stage"], "sequence": call["sequence"]}
        prior = self.report["ledger_entries"]
        stored = Snapshots(self.prepared["root"]).get(LEDGER)
        if (fingerprint(strict_json(stored.decode())) != fingerprint({"schema_version": 1,
                "code_freeze": self.prepared["plan"]["code_freeze"], "entries": prior}) or len(prior) >= 32):
            raise ValueError("c3_ledger_changed")
        self.report["ledger_entries"] = [*prior, entry]
        save(self.prepared["output_dir"], self.report, self.prepared["root"])
        write_ledger(self.report["ledger_entries"], self.prepared["plan"]["code_freeze"], self.prepared["root"])
        self.report["actual_native_posts"] += 1
        try:
            response = send()
            call.update(raw_response=copy.deepcopy(response), status="returned")
            return response
        except Exception as error:
            call["error"] = safe_error(error)
            raise
        finally:
            save(self.prepared["output_dir"], self.report, self.prepared["root"])


class ObservedGenerator(RequirementsGGUFGenerator):
    def __init__(self, *args, observer, **kwargs):
        self.observer = observer
        super().__init__(*args, **kwargs)

    def _request(self, method, path, payload=None, deadline=None):
        return self.observer.request(lambda: super(ObservedGenerator, self)._request(method, path, payload, deadline),
                                     method, path, payload, deadline)

    def _complete(self, messages, deadline, token_limit, grammar=""):
        deadline = self.observer.before_complete(messages, deadline, token_limit, grammar)
        result = super()._complete(messages, deadline, token_limit, grammar)
        self.observer.current["effective_config"] = copy.deepcopy(self.last_effective_config)
        save(self.observer.prepared["output_dir"], self.observer.report, self.observer.prepared["root"])
        return result


def write_ledger(entries, code_freeze, root):
    target = path(LEDGER, root, local=True)
    temp = path(target.with_suffix(".tmp").relative_to(Path(root).resolve()).as_posix(), root, local=True)
    with temp.open("xb") as stream:
        stream.write(encoded({"schema_version": 1, "code_freeze": code_freeze, "entries": entries}))
        stream.flush(); os.fsync(stream.fileno())
    temp.replace(target)


def stop_owned(process):
    started = time.monotonic()
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)
    elapsed = (time.monotonic() - started) * 1000
    if process.poll() is None or elapsed > 5000:
        raise ValueError("c3_cleanup_failed")
    return elapsed


@contextmanager
def watchdog(process, row):
    row.update(watchdog_fired=False, watchdog_joined=False)
    def fire():
        row["watchdog_fired"] = True
        if process.poll() is None:
            process.kill()
    timer = threading.Timer(90, fire)
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        timer.cancel(); timer.join(timeout=1)
        row["watchdog_joined"] = not timer.is_alive()


def run(prepared, *, factory=native_service, base_factory=None):
    if prepared["phase"] not in COUNTS:
        raise ValueError("c3_quality_only")
    return execute(prepared, factory=factory, base_factory=base_factory)


def execute(prepared, *, factory=native_service, base_factory=None):
    verify(prepared)
    root, plan, phase = prepared["root"], prepared["plan"], prepared["phase"]
    output = path(prepared["output_dir"], root, local=True)
    if output.exists():
        raise FileExistsError("c3_output_consumed")
    if phase == "neutral":
        write_new(LEDGER, {"schema_version": 1, "code_freeze": plan["code_freeze"], "entries": []}, root)
    ledger = strict_json(Snapshots(root).get(LEDGER).decode())
    if ledger != {"schema_version": 1, "code_freeze": plan["code_freeze"], "entries": prepared["expected_ledger"]}:
        raise ValueError("c3_ledger_prefix")
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "candidate": ANSWER_POLICY, "phase": phase,
        "plan_sha256": prepared["plan_sha256"], "code_freeze": plan["code_freeze"], "bound_files": plan["bound_files"],
        "gate": prepared.get("gate"), "status": "running", "calls": [], "results": [],
        "ledger_entries": copy.deepcopy(prepared["expected_ledger"]), "actual_native_posts": 0,
        "metadata_restart_attempts": 0,
        "human_review_count": 0, "paid_calls": 0, "warmup_calls": 0, "retries": 0, "recovery_native_calls": 0,
        "sources_unchanged": False, "processes_stopped": False, "metadata_recovery": False,
        "memory_scope": "sampled_native_rss_and_system_available_ram_endpoints; GPU not measured; not a peak", "started_at": datetime.now(UTC).isoformat()}
    save(prepared["output_dir"], report, root)
    observer = Observer(prepared, report)
    base_factory = base_factory or (lambda service, observer: ObservedGenerator(service.url, service.token, service.manifest, observer=observer).load())
    started, last_started, launched = time.monotonic(), None, False
    try:
        with factory(output / "native-logs", 2400) as service:
            launched = True
            try:
                if fingerprint(service.receipt) != plan["runtime_receipt_sha256"]:
                    raise ValueError("c3_runtime_receipt")
                base = base_factory(service, observer)
                try:
                    report["model_runtime"] = base.public_metadata()
                    check_model(report["model_runtime"])
                    runtime = RequirementsRuntime(RequirementsGenerator(base))
                    for case in prepared["cases"]:
                        verify(prepared)
                        row = {"id": case["id"], "payload_sha256": fingerprint(case.get("payload")),
                            "response_language": case.get("response_language"), "status": "failed", "preparations": []}
                        report["results"].append(row)
                        request_started = last_started = time.monotonic()
                        row["available_ram_before_bytes"] = psutil.virtual_memory().available
                        observer.row, observer.case, observer.current = row, case, None
                        observer.deadline = min(request_started + 90, started + 2400)
                        observer.stress = phase == "neutral" and case["id"] == "stress"
                        try:
                            with watchdog(service.process, row), rss_samples(service.process, row):
                                if observer.stress:
                                    run_stress(base, observer)
                                else:
                                    result = runtime.answer(AnswerRequest.model_validate(case["payload"]), language=case["response_language"])
                                    row["answer"] = {k: result[k] for k in ("status", "reason", "claims")}
                                    row["telemetry"] = copy.deepcopy(runtime.last_telemetry)
                            row["elapsed_ms"] = (time.monotonic() - request_started) * 1000
                            calls = [c for c in report["calls"] if c["case_id"] == case["id"]]
                            row["status"] = "passed"
                            if not observer.stress:
                                catalog = build_block_catalog(AnswerRequest.model_validate(case["payload"]).contexts)
                                parsed = parse_requirement_plan(calls[0]["raw_response"]["content"], catalog, case["response_language"])
                                row.update(plan_sha256=fingerprint(parsed.payload()), stage2_readiness="measured_at_runtime" if parsed.supported else "not_required")
                                replay_request(case, row, calls, report["model_runtime"])
                                if phase == "neutral":
                                    normal_check(plan, row, calls)
                        except Exception as error:
                            row.update(status="failed", error=safe_error(error))
                            raise
                        finally:
                            row["available_ram_after_bytes"] = psutil.virtual_memory().available
                            row["elapsed_ms"] = (time.monotonic() - request_started) * 1000
                            if not observer.stress:
                                row["telemetry"] = copy.deepcopy(runtime.last_telemetry)
                            observer.row, observer.case, observer.current = None, None, None
                            save(prepared["output_dir"], report, root)
                finally:
                    base.close()
            finally:
                report["owned_cleanup_ms"] = stop_owned(service.process)
                report["processes_stopped"] = True
    except Exception as error:  # noqa: BLE001 - preserve partial evidence; never continue
        report["failure"] = safe_error(error)
    finally:
        if last_started is not None:
            report["last_request_through_cleanup_ms"] = (time.monotonic() - last_started) * 1000
        # This restart performs identity metadata only, never a generation retry.
        if launched and time.monotonic() - started < 2375:
            try:
                report["metadata_restart_attempts"] += 1
                save(prepared["output_dir"], report, root)
                with factory(output / "recovery-logs", 2400 - (time.monotonic() - started)) as recovery:
                    try:
                        if fingerprint(recovery.receipt) != plan["runtime_receipt_sha256"]:
                            raise ValueError("c3_recovery_receipt")
                        recovered = base_factory(recovery, observer)
                        try:
                            report["recovered_identity"] = recovered.public_metadata()
                            check_model(report["recovered_identity"])
                            report["metadata_recovery"] = fingerprint(report["recovered_identity"]) == fingerprint(report.get("model_runtime"))
                        finally:
                            recovered.close()
                    finally:
                        report["recovery_cleanup_ms"] = stop_owned(recovery.process)
            except Exception as error:  # noqa: BLE001
                report["recovery_error"] = safe_error(error)
        try:
            verify(prepared)
            report["sources_unchanged"] = True
        except Exception as error:  # noqa: BLE001
            report["source_error"] = safe_error(error)
        report["native_log_bytes"] = sum(p.stat().st_size for p in output.rglob("*.log"))
        report["elapsed_seconds"] = time.monotonic() - started
        report["unexecuted"] = [c["id"] for c in prepared["cases"] if c["id"] not in {r["id"] for r in report["results"]}]
        report["status"] = "completed" if not any(k in report for k in ("failure", "source_error", "recovery_error")) else "failed"
        try:
            report_integrity(report, plan, prepared["plan_sha256"], phase, [c["id"] for c in prepared["cases"]])
            if phase == "neutral":
                validate_neutral_report(plan, prepared["plan_sha256"], report)
        except Exception as error:  # noqa: BLE001
            report.update(status="failed", integrity_error=safe_error(error))
        save(prepared["output_dir"], report, root)
    return report


def verify_survey(reference, phase, code, code_ref, snapshots):
    survey_path(reference["file"], phase, snapshots.root)
    receipt = snapshots.read(reference)
    rows, summary = receipt.get("cases", []), receipt.get("summary", {})
    count = COUNTS[phase]
    if (receipt.get("candidate") != ANSWER_POLICY or receipt.get("phase") != phase
            or receipt.get("status") != "passed" or receipt.get("errors") != []
            or receipt.get("bound_files") != code or receipt.get("payloads_preserved") is not True
            or receipt.get("stage2_readiness") != "dynamic_unmeasured" or not digest(receipt.get("input_sha256"))
            or receipt.get("snapshots", {}).get(code_ref["file"], {}).get("sha256") != code_ref["sha256"]
            or any(type(receipt.get(k)) is not int or receipt[k] != 0 for k in ("model_calls", "native_calls", "downloads"))
            or len(rows) != count or len({r["id"] for r in rows}) != count
            or any(type(summary.get(k)) is not int or summary[k] != v for k, v in
                   {"total_cases": count, "measured_cases": count, "unmeasured_cases": 0, "failed_cases": 0}.items())):
        raise ValueError("c3_survey_not_ready")
    _tokenizer_metadata(receipt["tokenizer"])
    for row in rows:
        if (type(row.get("official_stage1_tokens")) is not int or not 0 < row["official_stage1_tokens"] <= 5120
                or row.get("payload_preserved") is not True or row.get("error_code") is not None
                or row.get("stage2_readiness") != "dynamic_unmeasured"):
            raise ValueError("c3_survey_rows")
    values = [r["official_stage1_tokens"] for r in rows]
    if summary.get("min_stage1_tokens") != min(values) or summary.get("max_stage1_tokens") != max(values):
        raise ValueError("c3_survey_summary")
    return receipt


def normal_case():
    text = "The fictional beacon is turquoise.\n"
    return {"id": "normal", "response_language": "en", "payload": {"schema_version": 1,
        "query": "What color is the fictional beacon?", "contexts": [{"document_id": "c3-neutral-beacon",
        "revision": 1, "chunk_id": "c3-neutral-beacon-0", "title": "Fictional C3 resource fixture",
        "page": None, "meeting_date": None, "text": text, "start_offset": 0, "end_offset": len(text)}]}}


def stress_messages(stage, size, forced_plan):
    return [{"role": "system", "content": "Resource-only synthetic load. Repeat load with spaces."},
            {"role": "user", "content": json.dumps({"resource_stage": stage,
                "independent_fixed_plan": forced_plan, "padding": "load marker " * size})}]


def register_neutral(plan_path, output, *, code_freeze, calibration_receipt, validation_receipt,
                     runtime_receipt, root=ROOT, loader=None, counter=None):
    """Future offline tokenizer registration only. No weights or generation here."""
    from scripts.check_meeting_review_token_budget import count_prompt, load_tokenizer
    snapshots = Snapshots(root)
    plan_name, output_name = named(plan_path, root), named(output, root)
    if (not re.fullmatch(r"(?:data/evaluation|\.local)/meetings-c3-neutral-plan-[A-Za-z0-9_-]+\.json", plan_name)
            or not re.fullmatch(r"\.local/meetings-c3-neutral-[A-Za-z0-9_-]+", output_name)):
        raise ValueError("c3_neutral_output_path")
    path(output_name, root, local=True)
    for phase, value in (("calibration", calibration_receipt), ("validation", validation_receipt)):
        survey_path(named(value, root), phase, root)
    runtime_name = named(runtime_receipt, root)
    if runtime_name != "models/meetings-qwen35-v1/setup-receipt.json":
        raise ValueError("c3_runtime_metadata_path")
    if path(plan_name, root).exists() or path(output_name, root).exists() or path(LEDGER, root).exists():
        raise FileExistsError("c3_neutral_consumed")
    code_name = named(code_freeze, root)
    if code_name != prep.TOOLCHAIN_FREEZE:
        raise ValueError("c3_code_freeze_path")
    code_ref = {"file": code_name, "sha256": sha(snapshots.get(code_name))}
    code = verify_code(code_ref, snapshots)
    refs = {}
    surveys = []
    for phase, value in (("calibration", calibration_receipt), ("validation", validation_receipt)):
        name = named(value, root)
        phase_path(name, phase, root)
        refs[phase] = {"file": name, "sha256": sha(snapshots.get(name))}
        surveys.append(verify_survey(refs[phase], phase, code, code_ref, snapshots))
    runtime = strict_json(snapshots.get(runtime_name).decode())
    with open(os.devnull, "w", encoding="utf-8") as sink, redirect_stdout(sink), redirect_stderr(sink):
        tokenizer, metadata = (loader or load_tokenizer)(False)
    _tokenizer_metadata(metadata)
    if any(fingerprint(s["tokenizer"]) != fingerprint(metadata) for s in surveys):
        raise ValueError("c3_tokenizer_changed")
    def count(tokenizer, messages):
        with open(os.devnull, "w", encoding="utf-8") as sink, redirect_stdout(sink), redirect_stderr(sink):
            return (counter or count_prompt)(tokenizer, messages)
    normal = normal_case()
    request = AnswerRequest.model_validate(normal["payload"])
    catalog = build_block_catalog(request.contexts)
    n = count(tokenizer, requirement_messages(request.query, catalog, "en"))
    if type(n) is not int or not 0 < n <= 1024:
        raise ValueError("c3_neutral_normal_budget")
    normal["official_stage1_tokens"] = n
    forced = {"requirements": [{"requirement_id": 1, "need": "Synthetic resource load only",
                              "status": "supported", "evidence_ids": [0]}]}
    stress = []
    for stage in (1, 2):
        lo, hi, found = 1, 16000, None
        for _ in range(15):
            size = (lo + hi) // 2
            messages = stress_messages(stage, size, forced)
            tokens = count(tokenizer, messages)
            if type(tokens) is not int or tokens <= 0:
                raise ValueError("c3_stress_count")
            if 4992 <= tokens <= 5120:
                found = {"stage": stage, "messages": messages, "grammar": STRESS_GRAMMAR,
                         "official_tokens": tokens, "fixed_plan": forced,
                         "resource_only_independent_of_stage1_output": True}
                break
            if tokens > 5120: hi = size - 1
            else: lo = size + 1
            if lo > hi: break
        if found is None:
            raise ValueError("c3_stress_target_unreachable")
        stress.append(found)
    plan = {"schema_version": 1, "candidate": ANSWER_POLICY, "kind": "neutral", "limits": LIMITS,
        "code_freeze": code_ref, "bound_files": code, "registry": {"file": prep.REGISTRY, "sha256": code[prep.REGISTRY]},
        "runtime_receipt_sha256": fingerprint(runtime), "tokenizer": metadata, "survey_receipts": refs,
        "normal": normal, "normal_expected_terms": ["turquoise"], "normal_stage2_readiness": "dynamic_unmeasured",
        "normal_stage1_prompt_sha256": fingerprint(requirement_messages(request.query, catalog, "en")),
        "normal_stage1_grammar_sha256": sha(requirement_plan_grammar(catalog).encode()),
        "dynamic_stage2_builder_sha256": code["src/doctrail/meeting_answer_requirements.py"],
        "stress": stress, "output_dir": output_name, "model_calls": 0, "downloads": 0,
        "human_review_count": 0, "ledger_file": LEDGER}
    snapshots.unchanged()
    write_new(plan_name, plan, root)
    return plan


def neutral_check(plan, snapshots):
    if not re.fullmatch(r"\.local/meetings-c3-neutral-[A-Za-z0-9_-]+", plan.get("output_dir", "")):
        raise ValueError("c3_neutral_output_path")
    for phase in COUNTS:
        survey_path(plan["survey_receipts"][phase]["file"], phase, snapshots.root)
    common(plan, snapshots)
    request = AnswerRequest.model_validate(normal_case()["payload"])
    catalog = build_block_catalog(request.contexts)
    if (plan.get("kind") != "neutral" or plan.get("ledger_file") != LEDGER
            or plan.get("normal_stage1_prompt_sha256") != fingerprint(requirement_messages(request.query, catalog, "en"))
            or plan.get("normal_stage1_grammar_sha256") != sha(requirement_plan_grammar(catalog).encode())
            or plan.get("normal_stage2_readiness") != "dynamic_unmeasured"
            or plan.get("dynamic_stage2_builder_sha256") != plan["bound_files"]["src/doctrail/meeting_answer_requirements.py"]
            or plan.get("normal_expected_terms") != ["turquoise"]
            or {k: plan["normal"][k] for k in ("id", "payload", "response_language")} != normal_case()
            or type(plan["normal"].get("official_stage1_tokens")) is not int
            or not 0 < plan["normal"]["official_stage1_tokens"] <= 1024
            or len(plan.get("stress", [])) != 2):
        raise ValueError("c3_neutral_contract")
    for phase in COUNTS:
        receipt = verify_survey(plan["survey_receipts"][phase], phase, plan["bound_files"], plan["code_freeze"], snapshots)
        if fingerprint(receipt["tokenizer"]) != fingerprint(plan["tokenizer"]):
            raise ValueError("c3_neutral_tokenizer")
    for stage, value in enumerate(plan["stress"], 1):
        if (value.get("stage") != stage or value.get("grammar") != STRESS_GRAMMAR
                or value.get("resource_only_independent_of_stage1_output") is not True
                or type(value.get("official_tokens")) is not int or not 4992 <= value["official_tokens"] <= 5120
                or not isinstance(value.get("messages"), list) or not isinstance(value.get("fixed_plan"), dict)):
            raise ValueError("c3_neutral_stress_contract")
    path(plan["output_dir"], snapshots.root, local=True)


def run_neutral(plan_path, *, root=ROOT, factory=native_service, base_factory=None):
    plan, plan_sha, snapshots, name = read_plan(plan_path, root)
    neutral_check(plan, snapshots)
    prepared = {"plan": plan, "plan_sha256": plan_sha, "plan_file": name, "snapshots": snapshots,
        "phase": "neutral", "cases": [plan["normal"], {"id": "stress"}], "gate": None,
        "root": Path(root), "output_dir": plan["output_dir"], "expected_ledger": []}
    return execute(prepared, factory=factory, base_factory=base_factory)


def normal_check(plan, row, calls):
    if (len(calls) != 2 or row["answer"]["status"] != "answered"
            or not all(t.lower() in " ".join(c["text"] for c in row["answer"]["claims"]).lower()
                       for t in plan["normal_expected_terms"])):
        raise ValueError("c3_normal_not_realized")


def run_stress(base, observer):
    # Separate path; never imported into a quality request or passed to its runtime.
    base.begin_request(observer.deadline)
    try:
        for stage in observer.prepared["plan"]["stress"]:
            count = base.count_tokens(stage["messages"])
            if type(count) is not int or count != stage["official_tokens"]:
                raise ValueError("c3_stress_native_count")
            result = base._complete(stage["messages"], observer.deadline, 384, STRESS_GRAMMAR)
            if result.finish_reason != "length" or result.output_tokens != 384:
                raise ValueError("c3_stress_not_length")
    finally:
        base.end_request()


def validate_neutral_report(plan, plan_sha, report):
    report_integrity(report, plan, plan_sha, "neutral", ["normal", "stress"])
    calls = report["calls"]
    if (len(calls) != 4 or [(c["case_id"], c["stage"]) for c in calls] != [("normal", 1), ("normal", 2), ("stress", 1), ("stress", 2)]
            or len(report["ledger_entries"]) != 4):
        raise ValueError("c3_neutral_four_calls")
    replay_request(plan["normal"], report["results"][0], calls[:2], report["model_runtime"])
    normal_check(plan, report["results"][0], calls[:2])
    stress = report["results"][1]
    if (stress.get("status") != "passed" or not finite(stress.get("elapsed_ms"), 90000, inclusive=False)
            or stress.get("watchdog_fired") is not False or stress.get("watchdog_joined") is not True):
        raise ValueError("c3_stress_deadline")
    for call, registered in zip(calls[2:], plan["stress"], strict=True):
        check_trace(call, registered["messages"], STRESS_GRAMMAR, report["model_runtime"],
                    expected_tokens=registered["official_tokens"], finish="length")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("register-neutral", "check", "run-neutral", "run"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--phase", choices=COUNTS)
    parser.add_argument("--gate", type=Path)
    for name in ("output", "code-freeze", "calibration-receipt", "validation-receipt", "runtime-receipt"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.operation == "register-neutral":
            register_neutral(args.plan, args.output, code_freeze=args.code_freeze,
                calibration_receipt=args.calibration_receipt, validation_receipt=args.validation_receipt,
                runtime_receipt=args.runtime_receipt)
            result = {"registered": True, "native_calls": 0}
        elif args.operation == "run-neutral":
            report = run_neutral(args.plan)
            result = {"status": report["status"], "native_calls": len(report["calls"])}
        else:
            prepared = check(args.plan, args.phase, args.gate)
            if args.operation == "check": result = {"prepared": True, "native_calls": 0}
            else:
                report = run(prepared)
                result = {"status": report["status"], "native_calls": len(report["calls"])}
        print(json.dumps(result))
        if result.get("status", "completed") != "completed": raise SystemExit(1)
    except Exception:  # noqa: BLE001 - never emit private payloads or backend errors
        parser.exit(1, "c3_probe_failed\n")


if __name__ == "__main__":
    main()
