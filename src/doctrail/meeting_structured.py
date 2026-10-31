"""Explicit pinned local JSON-schema profiles and grounded summary assembly.

Schema compliance and same-model review are not semantic acceptance. Existing
generic QA citations, native identity verification and classification are reused.
No prompt truncation, output repair, compiler or alternate model fallback exists.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import stat
import time
from pathlib import Path

from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_contract import metadata_values, strict_json
from doctrail.meeting_extraction_coverage import _validate
from doctrail.meeting_gguf import GREEDY, GGUFGenerator, GGUFResult, _fail, _integer, _same_setting
from doctrail.meeting_grounded_summary import (
    classified_analysis,
    parse_draft,
    parse_review,
    source_payload,
    summary_messages,
    summary_projection,
    validate_summary_analysis,
)
from doctrail.meeting_runtime import DEADLINE_SECONDS, MAX_NEW_TOKENS, PROTOCOL
from doctrail.meeting_runtime import MAX_INPUT_TOKENS as CLASSIFICATION_INPUT_TOKENS
from doctrail.meeting_worker import LABELS, MeetingRuntime, classification_messages, partitions

PROFILE = "ministral3-json-schema-grounded-v1"
QWEN_PROFILE = "qwen25-7b-q4km-json-schema-grounded-v1"
STRUCTURED_PROFILES = (PROFILE, QWEN_PROFILE)
QWEN_MANIFEST_SHA256 = "6cb34ab578e55c61e20b7c5d49fc7cbb9086fd06cd57359e6b2ccd1ff67f97c7"
INPUT_TOKENS = 6144
CONTEXT_TOKENS = 8192
SUMMARY_TOKENS = 768
REVIEW_TOKENS = 128
MODEL_ID = "mistralai/Ministral-3-3B-Instruct-2512"
MODEL_SHA256 = "e23dd88b0e0951d3f5784d6d4092210cda2b006b251f33b226b283a6c9d1f6bb"
METADATA_POLICY = "literal_optional_v1"


def literal_optional_analysis(units, labels):
    """Project optional literal metadata; original model labels are not corrected."""
    _validate(units, labels)
    fields = {"meeting_title", "meeting_date", "participants", "purpose"}
    selected = [(index, LABELS[row["label"]]) for index, row in enumerate(labels)
                if LABELS[row["label"]] in fields]
    if len(selected) > 30:
        raise WorkerError("generation_metadata_limit", 422)
    # The unchanged helper still validates and constructs every nonmetadata item.
    analysis = classified_analysis(units, [
        {"label": 0} if LABELS[row["label"]] in fields else dict(row) for row in labels])
    supported = {field: [] for field in fields}
    warnings = {}
    participants_out_of_bounds = False
    def warn(index, field, reason):
        warnings[index] = {"field": field, "unit_index": index, "reason": reason}
    for index, field in selected:
        quote = units[index]["quote"]
        eligible = True
        if field == "meeting_date":
            eligible = bool(re.fullmatch(r"(?:#{1,6}[ \t]+)?\d{4}-\d{2}-\d{2}", quote)
                or re.match(r"(?:\*\*)?(?:date|meeting[ \t]+date|날짜|회의[ \t]*날짜)(?:\*\*)?\s*[:：]", quote, re.IGNORECASE))
        elif field == "participants":
            # No generic table first-cell inference. Attendance-table provenance
            # is not established by the classifier label alone.
            eligible = not quote.startswith("|") and "\n" not in quote
        elif field == "meeting_title":
            eligible = "\n" not in quote and "\r" not in quote
        values = metadata_values(field, quote) if eligible else []
        if not values:
            warn(index, field, "unsupported_source_format")
            continue
        cap = 2000 if field == "purpose" else 200
        if (any(not value.strip() or len(value) > cap or value not in quote for value in values)
                or field == "participants" and len(set(values)) > 100):
            warn(index, field, "value_out_of_bounds")
            participants_out_of_bounds |= field == "participants"
            continue
        supported[field].append((index, values))
    for field, candidates in supported.items():
        distinct = list(dict.fromkeys(value for _, values in candidates for value in values))
        if field == "participants":
            if participants_out_of_bounds or len(distinct) > 100:
                for index, _ in candidates:
                    warn(index, field, "value_out_of_bounds")
                continue
            analysis[field] = distinct
        elif len(distinct) > 1:
            for index, _ in candidates:
                warn(index, field, "ambiguous_source_value")
            continue
        elif distinct:
            analysis[field] = distinct[0]
        for index, _ in candidates:
            analysis["metadata_evidence"].append({**units[index], "field": field})
    analysis["metadata_evidence"].sort(key=lambda row: row["start_offset"])
    return analysis, {"metadata_policy": METADATA_POLICY,
                      "metadata_warnings": [warnings[index] for index in sorted(warnings)]}


def _asset_stamp(path):
    path = Path(path)
    for parent in (path, *path.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            _fail("generation_identity_mismatch")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        _fail("generation_identity_mismatch")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def prepare_qwen_assets(manifest_path, model_root, runtime_root, deadline):
    """Read-only startup verification of the pinned split model and reused runtime."""
    def remaining():
        if time.monotonic() >= deadline:
            _fail("generation_deadline_exceeded")
    def verify(path, expected):
        remaining()
        before = _asset_stamp(path)
        if before[2] != expected["size_bytes"]:
            _fail("generation_identity_mismatch")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(8 * 1024**2):
                remaining()
                digest.update(chunk)
        remaining()
        if digest.hexdigest() != expected["sha256"] or _asset_stamp(path) != before:
            _fail("generation_identity_mismatch")
        return path, before
    manifest_path, model_root, runtime_root = map(Path, (manifest_path, model_root, runtime_root))
    remaining()
    if _asset_stamp(manifest_path)[2] > 65536:
        _fail("generation_identity_mismatch")
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != QWEN_MANIFEST_SHA256:
        _fail("generation_identity_mismatch")
    manifest = json.loads(raw)
    gguf, runtime = manifest["gguf"], manifest["runtime_reuse"]
    stamps = [(manifest_path, _asset_stamp(manifest_path))]
    if {p.name for p in model_root.iterdir()} != {shard["filename"] for shard in gguf["shards"]}:
        _fail("generation_identity_mismatch")
    for shard in gguf["shards"]:
        stamps.append(verify(model_root / shard["filename"], shard))
    if {p.name for p in runtime_root.iterdir()} != set(runtime["runtime_files"]):
        _fail("generation_identity_mismatch")
    for name, expected in runtime["runtime_files"].items():
        stamps.append(verify(runtime_root / name, expected))
    return {"manifest": manifest, "manifest_path": manifest_path.resolve(), "stamps": stamps,
            "entry": (model_root / gguf["entry_filename"]).resolve(),
            "binary": (runtime_root / "llama-server.exe").resolve(), "alias": gguf["shards"][0]["sha256"]}


def claims_schema(status, text_limit):
    return {"type": "object", "additionalProperties": False, "required": ["status", "claims"],
            "properties": {"status": {"type": "string", "enum": [status, "abstained"]},
                "claims": {"type": "array", "minItems": 0, "maxItems": 6,
                    "items": {"type": "object", "additionalProperties": False,
                        "required": ["evidence", "text"], "properties": {
                            "evidence": {"type": "array", "minItems": 1, "maxItems": 4,
                                         "items": {"type": "integer", "minimum": 0}},
                            "text": {"type": "string", "minLength": 1, "maxLength": text_limit}}}}}}


QA_SCHEMA = claims_schema("answered", 2000)
DRAFT_SCHEMA = claims_schema("draft", 240)
REVIEW_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["claims", "coverage"],
    "properties": {"claims": {"type": "array", "minItems": 1, "maxItems": 6,
        "items": {"type": "array", "minItems": 2, "maxItems": 2, "prefixItems": [
            {"type": "integer", "minimum": 0, "maximum": 5},
            {"type": "string", "enum": ["supported", "unsupported", "uncertain"]}]}},
        "coverage": {"type": "string", "enum": ["sufficient", "insufficient", "uncertain"]}}}


def chat_content_matches(native, content):
    """Pinned d812 auto-parser framing, not output repair or JSON extraction."""
    if not isinstance(native, str) or not isinstance(content, str):
        return False
    if max(len(native.encode("utf-8")), len(content.encode("utf-8"))) > 65536:
        return False
    space = r"[ \t\r\n]*"
    exact = re.escape(content)
    return bool(re.fullmatch(space + "(?:" + exact + "|```json" + space + exact + space + "```)" + space, native))


class StructuredGenerator(GGUFGenerator):
    """The selected artifact's embedded template; no external template override."""
    def __init__(self, *args, profile=PROFILE, qwen_assets=None, **kwargs):
        if profile not in STRUCTURED_PROFILES:
            raise ValueError("unknown_structured_profile")
        self.profile, self.qwen_assets = profile, qwen_assets
        super().__init__(*args, **kwargs)
        self._prompts = {}
        self.close_error = None
        self._closed = False
        self.last_call = None
        self._client.event_hooks["response"].append(self._response_status)

    def _response_status(self, response):
        if self.last_call is not None and response.request.url.path == "/v1/chat/completions":
            self.last_call["http_status"] = response.status_code

    def load(self):
        if self.profile == QWEN_PROFILE:
            try:
                return self._load_qwen()
            except GenerationError:
                self.close()
                raise
            except (OSError, KeyError, TypeError, ValueError):
                self.close()
                _fail("generation_identity_mismatch")
        super().load()
        if (self._metadata["repo_id"] != MODEL_ID or self._alias != MODEL_SHA256
                or self._metadata["runtime"]["context_tokens"] != CONTEXT_TOKENS):
            self.close()
            _fail("generation_identity_mismatch")
        return self

    def _load_qwen(self):
        assets = self.qwen_assets
        if assets is None or self.manifest_path.resolve() != assets["manifest_path"]:
            _fail("generation_identity_mismatch")
        for path, expected in assets["stamps"]:
            self._remaining()
            if _asset_stamp(path) != expected:
                _fail("generation_identity_mismatch")
        manifest = assets["manifest"]
        gguf, runtime = manifest["gguf"], manifest["runtime_reuse"]
        props = self._request("GET", "/props")
        build = re.fullmatch(r"b([0-9]+)-([a-f0-9]{7,40})", props.get("build_info", ""))
        settings = props["default_generation_settings"]
        if (props.get("model_alias") != assets["alias"] or not build
                or "b" + build[1] != runtime["tag"] or not runtime["commit"].startswith(build[2])
                or Path(props["model_path"]).resolve() != assets["entry"]
                or not _same_setting(settings.get("n_ctx"), CONTEXT_TOKENS)
                or type(props.get("total_slots")) is not int or props["total_slots"] != 1
                or props.get("is_sleeping") is not False):
            _fail("generation_identity_mismatch")
        self._alias = assets["alias"]
        self._metadata = {"repo_id": manifest["provenance"]["base_model_name"],
            "revision": "gguf-revision:" + gguf["revision"], "original_revision": None,
            "conversion_base_commit": None, "experimental": True,
            "generation_protocol": PROTOCOL, "server_alias_kind": "entry_shard_sha256",
            "artifact": {"repo_id": gguf["repo_id"], "revision": gguf["revision"],
                "quantization": gguf["quantization"], "entry_filename": gguf["entry_filename"],
                "shards": [{key: shard[key] for key in ("filename", "sha256", "size_bytes")} for shard in gguf["shards"]]},
            "runtime": {"backend": "llama.cpp", "tag": runtime["tag"], "commit": runtime["commit"],
                "observed_build": props["build_info"], "identity_check": "two_shard_sha256_runtime_files_and_server_props",
                "context_tokens": settings["n_ctx"], "max_input_tokens": INPUT_TOKENS,
                "max_new_tokens": MAX_NEW_TOKENS, "deadline_seconds": DEADLINE_SECONDS,
                "memory_telemetry": "not_measured"}}
        return self

    def public_metadata(self):
        metadata = super().public_metadata()
        metadata["runtime"]["max_input_tokens"] = INPUT_TOKENS
        metadata["structured_output"] = {"profile": self.profile, "opt_in": True,
            "metadata_policy": METADATA_POLICY,
            "endpoint": "/v1/chat/completions", "format": "json_schema", "qa_tokens": MAX_NEW_TOKENS,
            "input_count_endpoint": "/v1/chat/completions/input_tokens",
            "content_framing": "pinned_d812_json_schema_autoparser",
            "summary_tokens": SUMMARY_TOKENS, "review_tokens": REVIEW_TOKENS,
            "input_tokens": INPUT_TOKENS, "native_context_tokens": CONTEXT_TOKENS,
            "classification_input_tokens": CLASSIFICATION_INPUT_TOKENS, "shared_request_seconds": DEADLINE_SECONDS,
            "semantic_quality_accepted": False, "review": "same_model_not_independent"}
        return metadata

    def begin_request(self, deadline):
        self._prompts.clear()
        self.last_call = None
        super().begin_request(deadline)

    def end_request(self):
        self._prompts.clear()
        super().end_request()

    def _chat_body(self, messages, name, schema, cap):
        return {**GREEDY, "n_predict": cap, "max_tokens": cap, "model": self._alias,
                "messages": copy.deepcopy(messages), "cache_prompt": False,
                "return_tokens": True, "verbose": True,
                "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": name, "strict": True, "schema": copy.deepcopy(schema)}}}

    def _prepare_chat(self, body, deadline=None):
        # Classification keeps GGUFGenerator._prepare and its token-array protocol.
        # Both chat endpoints run the pinned server's OAI parser on this full body.
        self._remaining(deadline)
        key = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        if key in self._prompts:
            return self._prompts[key]
        response = self._request("POST", "/apply-template", body, deadline)
        prompt = response.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            _fail()
        counted = self._request("POST", "/v1/chat/completions/input_tokens", body, deadline)
        count = counted.get("input_tokens")
        if counted.get("object") != "response.input_tokens" or not _integer(count, 1):
            _fail()
        self._prompts[key] = prompt, count
        while len(self._prompts) > 8:
            self._prompts.pop(next(iter(self._prompts)))
        return prompt, count

    def count_structured_tokens(self, messages, name, schema, cap):
        return self._prepare_chat(self._chat_body(messages, name, schema, cap))[1]

    def structured(self, messages, deadline, name, schema, cap):
        try:
            return self._structured(messages, deadline, name, schema, cap)
        except (GenerationError, WorkerError) as error:
            if self.last_call is not None:
                self.last_call["error_code"] = error.code
            raise

    def _structured(self, messages, deadline, name, schema, cap):
        started = time.monotonic()
        self.last_effective_config = None
        self.last_call = {"operation": name, "output_cap": cap, "input_cap": INPUT_TOKENS,
                          "dispatched": False, "returned": False, "accepted": False, "validation_stage": "input"}
        body = self._chat_body(messages, name, schema, cap)
        prompt, input_tokens = self._prepare_chat(body, deadline)
        self.last_call["input_tokens"] = input_tokens
        if input_tokens > INPUT_TOKENS:
            _fail("generation_input_limit")
        expected = {**GREEDY, "n_predict": cap}
        self.last_call["dispatched"] = True
        self.last_call["validation_stage"] = "http"
        response = self._request("POST", "/v1/chat/completions", body, deadline)
        self.last_call["returned"] = True
        self.last_call["validation_stage"] = "native_metadata"
        try:
            native = response["__verbose"]
            settings, timing = native["generation_settings"], native["timings"]
            for field in ("tokens_predicted", "tokens_evaluated"):
                value = native.get(field)
                if type(value) is int and 0 <= value <= 2**31:
                    self.last_call["observed_" + field] = value
            self.last_call["observed_stop_type"] = native.get("stop_type") if native.get("stop_type") in ("eos", "limit", "word") else "other"
            self.last_call["validation_stage"] = "effective_settings"
            if (any(not _same_setting(settings.get(key), value) for key, value in expected.items())
                    or not isinstance(settings.get("grammar"), str) or not settings["grammar"]):
                _fail("generation_effective_config_mismatch")
            choices, usage = response["choices"], response["usage"]
            if not isinstance(choices, list) or len(choices) != 1:
                _fail()
            message = choices[0]["message"]
            count, generated = native["tokens_predicted"], native["tokens"]
            self.last_call["validation_stage"] = "token_identity_integrity"
            if (response.get("object") != "chat.completion" or response.get("model") != self._alias
                    or response.get("system_fingerprint") != self._metadata["runtime"]["observed_build"]
                    or native.get("model") != self._alias or native.get("prompt") != prompt
                    or native.get("truncated") is not False or native.get("stop") is not True
                    or not _integer(count, 1) or count > cap or not isinstance(generated, list)
                    or len(generated) != count or not all(_integer(token) for token in generated)
                    or not _same_setting(native.get("tokens_evaluated"), input_tokens)
                    or not _same_setting(timing.get("prompt_n"), input_tokens)
                    or not _same_setting(timing.get("predicted_n"), count)
                    or not _same_setting(timing.get("cache_n"), 0)
                    or not _same_setting(usage.get("prompt_tokens"), input_tokens)
                    or not _same_setting(usage.get("completion_tokens"), count)
                    or not _same_setting(usage.get("total_tokens"), input_tokens + count)
                    or not _same_setting(usage.get("prompt_tokens_details", {}).get("cached_tokens"), 0)
                    or message.get("role") != "assistant" or message.get("tool_calls")
                    or message.get("reasoning_content") not in (None, "")
                    or not chat_content_matches(native.get("content"), message.get("content"))):
                _fail()
            self.last_call["validation_stage"] = "eos"
            if native.get("stop_type") != "eos" or choices[0].get("finish_reason") != "stop":
                _fail("generation_output_truncated")
            self.last_call["validation_stage"] = "json"
            if not isinstance(strict_json(message["content"]), dict):
                _fail("generation_invalid_schema")
        except (KeyError, TypeError, AttributeError):
            _fail()
        self._remaining(deadline)
        schema_sha = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
        self.last_effective_config = {"backend": "llama.cpp", "profile": self.profile, **expected,
            "schema_sha256": schema_sha, "observed_grammar_sha256": hashlib.sha256(settings["grammar"].encode()).hexdigest(),
            "cache_prompt_requested": False, "observed_cache_tokens": 0}
        self.last_call.update(accepted=True, output_tokens=count, finish_reason="eos", validation_stage="accepted")
        return GGUFResult(message["content"], "eos", input_tokens, count, time.monotonic() - started,
                          {"backend": "llama.cpp", "operation": name, "schema_sha256": schema_sha})

    def generate_bounded(self, messages, deadline):
        return self.structured(messages, deadline, "meeting_qa", QA_SCHEMA, MAX_NEW_TOKENS)

    def summary_bounded(self, messages, deadline):
        return self.structured(messages, deadline, "meeting_summary", DRAFT_SCHEMA, SUMMARY_TOKENS)

    def review_bounded(self, messages, deadline):
        return self.structured(messages, deadline, "meeting_summary_review", REVIEW_SCHEMA, REVIEW_TOKENS)

    def close(self):
        if self._closed:
            return
        self._prompts.clear()
        try:
            super().close()
            self._closed = True
        except Exception as error:
            self.close_error = error
            raise


class StructuredMeetingRuntime(MeetingRuntime):
    """One request lock/deadline for classification, natural draft and review."""
    def health(self):
        result = super().health()
        result["limits"]["input_tokens"] = INPUT_TOKENS
        result["limits"]["native_context_tokens"] = CONTEXT_TOKENS
        result["structured_profile"] = getattr(self.generator, "profile", PROFILE)
        return result

    def _generate(self, prompt, deadline, telemetry):
        self.last_stage = "qa"
        if self.generator.count_structured_tokens(prompt, "meeting_qa", QA_SCHEMA, MAX_NEW_TOKENS) > INPUT_TOKENS:
            raise WorkerError("generation_input_limit", 422)
        output = self.generator.generate_bounded(prompt, deadline)
        telemetry.append({"operation": "qa", "input_tokens": output.input_tokens,
                          "output_cap": MAX_NEW_TOKENS,
                          "output_tokens": output.output_tokens, "elapsed_seconds": output.elapsed_seconds,
                          "finish_reason": output.finish_reason, **output.telemetry})
        if output.finish_reason != "eos":
            raise WorkerError("generation_output_truncated", 502)
        return output.text

    def answer(self, request):
        if not request.contexts:
            return self._run(lambda deadline, telemetry: {
                "status": "abstained", "reason": "insufficient_evidence", "claims": []})
        return super().answer(request)

    def _run(self, operation):
        if not self.lock.acquire(blocking=False):
            raise WorkerError("model_busy", 503)
        started, telemetry, failure, result = time.monotonic(), [], None, None
        self.last_telemetry = {}
        self.last_stage = "request"
        try:
            self.generator.begin_request(started + DEADLINE_SECONDS)
            result = operation(started + DEADLINE_SECONDS, telemetry)
            if time.monotonic() - started >= DEADLINE_SECONDS:
                raise WorkerError("generation_deadline_exceeded", 504)
        except WorkerError as error:
            failure = error
        except GenerationError as error:
            status = {"generation_deadline_exceeded": 504, "generation_input_limit": 422}.get(error.code, 503)
            failure = WorkerError(error.code if status != 503 else "generation_failed", status)
        except Exception:  # noqa: BLE001 - never expose source/native exception text
            failure = WorkerError("generation_failed", 503)
        finally:
            try:
                self.generator.end_request()
            except Exception:  # noqa: BLE001 - cleanup cannot mask the first request failure
                if failure is None:
                    failure = WorkerError("generation_failed", 503)
            finally:
                receipt = {"calls": telemetry, "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                    "status": "failed" if failure else "complete", "effective_generation_config": self.generator.last_effective_config,
                    "last_structured_call": copy.deepcopy(self.generator.last_call), "stage": self.last_stage,
                    "failure_code": failure.code if failure else None}
                self.last_telemetry = receipt
                self.lock.release()
        if failure:
            raise failure
        return {"schema_version": 1, "model": self.model, "revision": self.revision,
                **result, "telemetry": receipt}

    def analyze(self, request):
        def run(deadline, telemetry):
            def check_time():
                if time.monotonic() >= deadline:
                    raise WorkerError("generation_deadline_exceeded", 504)
            check_time()
            self.last_stage = "partition"
            units = [unit for group in partitions(request.content, self.generator) for unit in group]
            source = source_payload(request.title, request.content, units)
            draft_messages = summary_messages(source)
            if self.generator.count_structured_tokens(draft_messages, "meeting_summary", DRAFT_SCHEMA, SUMMARY_TOKENS) > INPUT_TOKENS:
                raise WorkerError("generation_input_limit", 422)
            check_time()
            self.last_stage = "classification"
            labels, metrics = self.generator.classify_bounded([classification_messages(unit) for unit in units], deadline)
            telemetry.append(metrics)
            self.last_stage = "metadata"
            analysis, metadata_diagnostics = literal_optional_analysis(units, labels)
            telemetry.append(metadata_diagnostics)
            check_time()
            self.last_stage = "summary"
            draft = self.generator.summary_bounded(draft_messages, deadline)
            telemetry.append({"operation": "summary", "input_tokens": draft.input_tokens,
                              "output_cap": SUMMARY_TOKENS,
                              "output_tokens": draft.output_tokens, "finish_reason": draft.finish_reason})
            if draft.finish_reason != "eos":
                raise WorkerError("generation_output_truncated", 502)
            claims = parse_draft(draft.text, units, request.content)
            check_time()
            self.last_stage = "review"
            review = self.generator.review_bounded(summary_messages(source, claims), deadline)
            telemetry.append({"operation": "summary_review", "input_tokens": review.input_tokens,
                              "output_cap": REVIEW_TOKENS,
                              "output_tokens": review.output_tokens, "finish_reason": review.finish_reason})
            if review.finish_reason != "eos":
                raise WorkerError("generation_output_truncated", 502)
            reviewed = parse_review(review.text, len(claims))
            analysis.update(summary_version=2, summary_claims=claims, **summary_projection(claims, request.content))
            validate_summary_analysis(analysis, request.content)
            self.last_stage = "assembled"
            return {"analysis": analysis, "summary_review": reviewed}
        return self._run(run)
