"""Prospective, once-only summary mode diagnostic; never a product runtime.

No execution occurs on import. Actual CLI execution requires a separately prepared,
hash-bound registration and its explicit digest. Tests inject HTTP, clocks and owners.
Budgets are admission/postcondition checks, not a claim of hard I/O preemption.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import secrets
import subprocess
import threading
import time
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path

import httpx

from doctrail.inference import WorkerError
from doctrail.meeting_contract import strict_json
from doctrail.meeting_gguf import GREEDY, GGUFGenerator, _integer, _same_setting
from doctrail.meeting_grounded_summary import (
    REVIEW_GRAMMAR,
    parse_draft,
    parse_review,
    source_payload,
    summary_messages,
    summary_projection,
)
from doctrail.meeting_qwen35 import NONTHINKING_PREAMBLE
from doctrail.meeting_thinking_transport import (
    GGUF_SHA256,
    MANIFEST_SHA256,
    MODEL_ID,
    MODEL_REVISION,
    PREAMBLE,
    RUNTIME_COMMIT,
)
from doctrail.meeting_worker import partitions, worker_lease
from scripts.prepare_meeting_gguf import digest, linked, prepare
from scripts.serve_meeting_gpu_placement import command, normalized_argv
from scripts.serve_meeting_thinking import DEFAULT_ROOT, MANIFEST
from scripts.serve_meeting_thinking_compat import CompatService, DiscardDrain, cleanup_owned
from scripts.serve_models import unused_port, wait_ready

ROOT = Path(__file__).resolve().parents[1]
ID = "summary-mode-development-v1"
PLAN = "docs/MEETINGS-SUMMARY-QUALITY-NEXT.md"
PLAN_SHA = "fb32d66f4c2264edec160b908b83fa1050731c455099636b985793db40d0b329"
AMENDMENT = "docs/MEETINGS-SUMMARY-MODE-LAUNCHER-REPAIR.md"
AMENDMENT_SHA = "7bbd6e2c35c4cea5970a2150bdbbdb74296085eb11a40ca4426aba93fb340a5b"
LIMITS = {"input_tokens": 4096, "generation_tokens": 1312, "reasoning_requested": 512,
          "final_retokenized_tokens": 768, "review_tokens": 128, "arm_seconds": 180,
          "generation_seconds": 150, "startup_seconds": 120, "active_seconds": 1500,
          "cleanup_seconds": 5, "whole_seconds": 1625, "completion_calls": 16,
          "output_tokens": 11520, "sample_seconds": 0.25, "samples_per_arm": 721,
          "startup_available_bytes": 10 * 1024**3, "active_available_bytes": 2 * 1024**3,
          "native_rss_bytes": 8 * 1024**3}
CLAIM_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["evidence", "text"], "properties": {
        "evidence": {"type": "array", "minItems": 1, "maxItems": 4,
                     "items": {"type": "integer", "minimum": 0, "maximum": 159}},
        "text": {"type": "string", "minLength": 1}}}
# The existing grammar limits fields/counts, while parse_draft enforces language,
# distinct ordered IDs, per-claim 240 and aggregate 1200 Unicode code points.
DRAFT_SCHEMA = {"oneOf": [
    {"type": "object", "additionalProperties": False, "required": ["status", "claims"],
     "properties": {"status": {"const": "draft"}, "claims": {"type": "array",
         "minItems": 1, "maxItems": 6, "items": CLAIM_SCHEMA}}},
    {"type": "object", "additionalProperties": False, "required": ["status", "claims"],
     "properties": {"status": {"const": "abstained"},
                    "claims": {"type": "array", "maxItems": 0}}}]}


def fail(code):
    raise ValueError("summary_mode_" + code)


def check_time(clock, deadline):
    if clock() >= deadline:
        fail("deadline")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def error_record(error):
    code = getattr(error, "code", None)
    if isinstance(error, ValueError) and re.fullmatch(r"summary_mode_[a-z_]+", str(error)):
        code = str(error)
    return {"code": code or "summary_mode_failed_closed", "type": type(error).__name__}


def record_failure(report, record, *, operational=False, stop=False):
    """Write-once first causes; keep later stopping/cleanup failures independently."""
    record = copy.deepcopy(record)
    if operational:
        record.setdefault("kind", "operational")
    if report.get("first_failure") is None:
        report["first_failure"] = record
    history = report.setdefault("failure_history", [])
    if not history or history[-1] != record:
        history.append(record)
    if operational and report.get("operational_failure") is None:
        report["operational_failure"] = record
    if stop and report.get("stop_reason") is None:
        report["stop_reason"] = record


def order(documents):
    return [{"document": row["id"], "mode": mode}
            for i, row in enumerate(documents)
            for mode in (("A", "B") if i % 2 == 0 else ("B", "A"))]


def validate_input(data):
    if (not isinstance(data, dict) or set(data) != {"schema_version", "diagnostic", "documents"}
            or type(data["schema_version"]) is not int or data["schema_version"] != 1
            or data["diagnostic"] != ID or not isinstance(data["documents"], list)
            or len(data["documents"]) != 4):
        fail("input_contract")
    ids, identities = set(), set()
    for row in data["documents"]:
        if (not isinstance(row, dict) or set(row) != {"id", "document_id", "revision", "title",
                "content", "content_sha256"} or not isinstance(row["id"], str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", row["id"])
                or type(row["revision"]) is not int or row["revision"] < 1
                or any(not isinstance(row[k], str) or not row[k].strip()
                       for k in ("title", "content", "document_id"))):
            fail("document_contract")
        try:
            if str(uuid.UUID(row["document_id"])) != row["document_id"]:
                fail("document_identity")
            actual = sha(row["content"].encode("utf-8"))
        except (ValueError, UnicodeError):
            fail("document_identity")
        if (actual != row["content_sha256"] or row["id"] in ids
                or row["document_id"] in identities):
            fail("document_identity")
        ids.add(row["id"])
        identities.add(row["document_id"])
    return copy.deepcopy(data["documents"])


def generation_settings(thinking):
    return {**GREEDY, "grammar_triggers": [], "n_predict": 1312, "max_tokens": 1312,
            "reasoning_format": "deepseek", "reasoning_in_content": False,
            "generation_prompt": PREAMBLE if thinking else NONTHINKING_PREAMBLE}


def generation_body(messages, thinking):
    return {**{k: v for k, v in generation_settings(thinking).items()
               if k not in {"generation_prompt", "reasoning_in_content"}},
        "model": GGUF_SHA256, "messages": copy.deepcopy(messages), "cache_prompt": False,
        "return_tokens": True, "verbose": True,
        "chat_template_kwargs": {"enable_thinking": thinking},
        "reasoning_budget_tokens": 512, "reasoning_control": False,
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "meeting_summary", "strict": True, "schema": copy.deepcopy(DRAFT_SCHEMA)}}}


def validate_generation(response, prompt, input_n, thinking):
    """New 1312 contract; no C4/C5 validator or mutable budget globals."""
    try:
        native = response["__verbose"]
        settings, timing = native["generation_settings"], native["timings"]
        expected = generation_settings(thinking)
        if any(not _same_setting(settings.get(k), v) for k, v in expected.items()
               if k != "stop"):
            fail("effective_settings")
        if (not isinstance(settings.get("stop"), list)
                or any(s not in {"<|im_end|>", "<|endoftext|>"} for s in settings["stop"])
                or not isinstance(settings.get("grammar"), str) or not settings["grammar"]):
            fail("effective_settings")
        choices, usage = response["choices"], response["usage"]
        if not isinstance(choices, list) or len(choices) != 1:
            fail("response_shape")
        message, count, tokens = choices[0]["message"], native["tokens_predicted"], native["tokens"]
        if (response.get("model") != GGUF_SHA256 or native.get("model") != GGUF_SHA256
                or response.get("object") != "chat.completion"
                or response.get("system_fingerprint") != "b11429-d81235049"
                or native.get("prompt") != prompt or native.get("truncated") is not False
                or native.get("stop") is not True or not _integer(count, 1) or count > 1312
                or not isinstance(tokens, list) or len(tokens) != count
                or not all(_integer(t) for t in tokens)
                or not _same_setting(native.get("tokens_evaluated"), input_n)
                or not _same_setting(timing.get("prompt_n"), input_n)
                or not _same_setting(timing.get("predicted_n"), count)
                or not _same_setting(timing.get("cache_n"), 0)
                or not _same_setting(usage.get("prompt_tokens"), input_n)
                or not _same_setting(usage.get("completion_tokens"), count)
                or not _same_setting(usage.get("total_tokens"), input_n + count)
                or not _same_setting(usage.get("prompt_tokens_details", {}).get("cached_tokens"), 0)
                or message.get("role") != "assistant" or message.get("tool_calls")
                or not isinstance(message.get("content"), str)):
            fail("response_integrity")
        if native.get("stop_type") != "eos" or choices[0].get("finish_reason") != "stop":
            fail("non_eos")
        content, reasoning, raw = message["content"], message.get("reasoning_content"), native["content"]
        if not isinstance(raw, str) or any(t in content for t in ("<think>", "</think>")):
            fail("reasoning_split")
        if thinking:
            if (not isinstance(reasoning, str) or not reasoning.strip()
                    or raw.count("</think>") != 1 or "<think>" in raw):
                fail("reasoning_split")
            before, _, framing = raw.partition("</think>")
            if before.strip() != reasoning.strip():
                fail("reasoning_split")
        else:
            if reasoning not in (None, "") or any(t in raw for t in ("<think>", "</think>")):
                fail("reasoning_split")
            framing = raw
        framing = framing.strip()
        fenced = framing.startswith("```json") and framing.endswith("```")
        if fenced:
            framing = framing[7:-3].strip()
        if framing != content.strip():
            fail("reasoning_split")
        strict_json(content)  # duplicate keys and concatenated JSON fail before parsers
        return {"content": content, "reasoning": reasoning or "", "output_tokens": count,
            "input_tokens": input_n, "finish_reason": "eos", "telemetry": {
                "reasoning_budget_tokens_requested": 512,
                "reasoning_budget_effective_serialized": False,
                "independent_reasoning_hard_cap_verified": False,
                "native_total_cap": 1312, "native_json_framing": "fenced" if fenced else "bare",
                "final_token_measurement": "retokenized_content_not_generated_segment",
                "grammar_sha256": sha(settings["grammar"].encode()), "native_timings": timing}}
    except (KeyError, TypeError, AttributeError):
        fail("response_shape")


class DispatchTrace(httpx.BaseTransport):
    """Observe the exact handoff to the HTTP transport, not request-function entry."""
    def __init__(self, adapter, transport):
        self.adapter, self.transport = adapter, transport

    def handle_request(self, request):
        adapter, row = self.adapter, self.adapter.current_request
        adapter._remaining(row["deadline"])
        adapter.observe("http_dispatch_admission", {"request_id": row["id"], "path": row["path"]})
        adapter._remaining(row["deadline"])
        # No observer or further admission is between these counters and handoff.
        row["client_dispatched"] = True
        adapter.counts["http"] += 1
        if row["category"]:
            adapter.counts[row["category"]] += 1
        response = self.transport.handle_request(request)
        row["response_received"] = True
        adapter.counts["http_responses"] += 1
        if row["category"]:
            adapter.counts[row["category"] + "_responses"] += 1
        return response

    def close(self):
        self.transport.close()


class ModeAdapter(GGUFGenerator):
    def __init__(self, *args, clock=time.monotonic, observe=None, resource_check=None, **kwargs):
        transport = kwargs.pop("transport", None)
        transport = transport if transport is not None else httpx.HTTPTransport(retries=0, trust_env=False)
        super().__init__(*args, transport=DispatchTrace(self, transport), **kwargs)
        self.clock = clock
        self.observe = observe or (lambda event, value: None)
        self.resource_check = resource_check or (lambda: None)
        self.counts = {"http": 0, "template": 0, "tokenize": 0, "generation": 0, "review": 0}
        self.counts.update({key + suffix: 0 for key in list(self.counts)
                            for suffix in ("_attempts", "_responses")})
        self.counts.update(generation_validated=0, review_validated=0)
        self.request_log, self.current_request = [], None

    def _remaining(self, deadline=None):
        deadline = self._deadline if deadline is None else deadline
        if deadline is None:
            fail("unbounded_request")
        check_time(self.clock, deadline)
        self.resource_check()
        return deadline - self.clock()

    def _request(self, method, path, payload=None, deadline=None):
        category = {"/apply-template": "template", "/tokenize": "tokenize",
                    "/v1/chat/completions": "generation", "/completion": "review"}.get(path)
        if category in ("generation", "review") and (sum(
                self.counts[k] for k in ("generation_attempts", "review_attempts")) >= 16
                or self.counts["generation"] + self.counts["review"] >= 16):
            fail("completion_cap")
        row = {"id": len(self.request_log) + 1, "path": path, "category": category,
               "deadline": self._deadline if deadline is None else deadline,
               "client_dispatched": False, "response_received": False,
               "parsed_response": False, "status": "attempted_failed"}
        self.request_log.append(row)
        self.current_request = row
        self.counts["http_attempts"] += 1
        if category:
            self.counts[category + "_attempts"] += 1
        try:
            self._remaining(deadline)
            self.observe("http_request", {"request_id": row["id"], "method": method,
                                          "path": path, "body": payload})
            response = super()._request(method, path, payload, deadline)
            row["parsed_response"] = True
            self.observe("http_response", {"request_id": row["id"], "path": path, "response": response})
            self._remaining(deadline)
            row["status"] = "returned"
            return response
        except Exception as error:
            row["error"] = error_record(error)
            try:
                self.observe("http_failure", {"request_id": row["id"], "path": path, **row["error"]})
            except Exception as evidence_error:  # noqa: BLE001 - original failure remains causal
                row["failure_evidence_error"] = error_record(evidence_error)
            raise
        finally:
            self.current_request = None

    def load(self):
        if sha(self.manifest_path.read_bytes()) != MANIFEST_SHA256:
            fail("manifest_identity")
        super().load()
        meta = self._metadata
        if (meta["repo_id"] != MODEL_ID or meta["original_revision"] != MODEL_REVISION
                or meta["artifact"]["sha256"] != GGUF_SHA256
                or meta["runtime"]["tag"] != "b11429"
                or meta["runtime"]["commit"] != RUNTIME_COMMIT
                or meta["runtime"]["context_tokens"] != 6144):
            fail("runtime_identity")
        self._remaining()
        return self

    def tokenize(self, text, special, deadline):
        tokens = self._request("POST", "/tokenize", {"content": text, "add_special": False,
            "parse_special": special, "with_pieces": False}, deadline).get("tokens")
        if not isinstance(tokens, list) or not all(_integer(t) for t in tokens):
            fail("token_shape")
        return tokens

    def prepare(self, messages, thinking, deadline, *, enforce=True):
        prompt = self._request("POST", "/apply-template", {"messages": messages,
            "chat_template_kwargs": {"enable_thinking": thinking}}, deadline).get("prompt")
        suffix = PREAMBLE if thinking else NONTHINKING_PREAMBLE
        if not isinstance(prompt, str) or not prompt.endswith(suffix):
            fail("template_preamble")
        tokens = self.tokenize(prompt, True, deadline)
        if not tokens or (enforce and len(tokens) > 4096):
            fail("input_limit")
        return {"prompt": prompt, "tokens": tokens}

    def count_tokens(self, messages):
        # Existing partitions decides whether to split; do not introduce a new splitter.
        return len(self.prepare(messages, False, self._deadline, enforce=False)["tokens"])

    def generate(self, messages, thinking, prepared, deadline):
        current = self.prepare(messages, thinking, deadline)
        if current != prepared:
            fail("template_drift")
        response = self._request("POST", "/v1/chat/completions",
                                 generation_body(messages, thinking), deadline)
        result = validate_generation(response, current["prompt"], len(current["tokens"]), thinking)
        tokens = self.tokenize(result["content"], False, deadline)
        if not 1 <= len(tokens) <= 768:
            fail("final_limit")
        result["final_retokenized_tokens"] = len(tokens)
        self._remaining(deadline)
        self.counts["generation_validated"] += 1
        return result

    def review(self, messages, deadline):
        prepared = self.prepare(messages, False, deadline)
        expected = {**GREEDY, "n_predict": 128, "grammar": REVIEW_GRAMMAR}
        response = self._request("POST", "/completion", {**expected, "prompt": prepared["tokens"],
            "cache_prompt": False, "return_tokens": True}, deadline)
        settings, timing = response.get("generation_settings", {}), response.get("timings", {})
        count, tokens, input_n = response.get("tokens_predicted"), response.get("tokens"), len(prepared["tokens"])
        if any(not _same_setting(settings.get(k), v) for k, v in expected.items()):
            fail("review_settings")
        if (response.get("model") != GGUF_SHA256 or response.get("truncated") is not False
                or response.get("stop") is not True or response.get("stop_type") != "eos"
                or not _integer(count, 1) or count > 128 or not isinstance(tokens, list)
                or len(tokens) != count or not all(_integer(t) for t in tokens)
                or not _same_setting(response.get("tokens_evaluated"), input_n)
                or not _same_setting(timing.get("prompt_n"), input_n)
                or not _same_setting(timing.get("predicted_n"), count)
                or not _same_setting(timing.get("cache_n"), 0)
                or not isinstance(response.get("content"), str)):
            fail("review_integrity")
        self._remaining(deadline)
        self.counts["review_validated"] += 1
        return {"content": response["content"], "input_tokens": input_n, "output_tokens": count}


class ResourceGuard:
    """Check identity before samples or termination; at most 721 samples per arm."""
    def __init__(self, process, *, clock=time.monotonic, ps=None, expected_created=None):
        if ps is None:
            import psutil as ps
        self.ps, self.process, self.clock = ps, process, clock
        self.created = ps.Process(process.pid).create_time()
        if expected_created is not None and self.created != expected_created:
            fail("ownership")
        self.failure = None

    def check(self):
        if self.failure:
            fail(self.failure)
        try:
            native = self.ps.Process(self.process.pid)
            if native.create_time() != self.created or self.process.poll() is not None:
                fail("ownership")
            row = {"at": self.clock(), "rss": native.memory_info().rss,
                   "available": self.ps.virtual_memory().available}
            if row["rss"] > LIMITS["native_rss_bytes"] or row["available"] < LIMITS["active_available_bytes"]:
                fail("resources")
            return row
        except Exception as error:
            self.failure = "ownership" if not isinstance(error, ValueError) else str(error).removeprefix("summary_mode_")
            raise ValueError("summary_mode_" + self.failure) from error

    def stop_owned(self):
        # A failed identity check never authorizes killing a possibly reused PID.
        try:
            if (self.ps.Process(self.process.pid).create_time() == self.created
                    and self.process.poll() is None):
                self.process.kill()
        except Exception:  # noqa: BLE001 - never terminate an uncertain process identity
            self.failure = self.failure or "ownership"

    @contextmanager
    def arm(self, deadline, metrics):
        event, rows = threading.Event(), []
        def sample():
            while not event.is_set() and len(rows) < 721:
                try:
                    check_time(self.clock, deadline)
                    rows.append(self.check())
                except Exception:  # noqa: BLE001 - background monitor fails closed
                    self.failure = self.failure or "deadline"
                    self.stop_owned()
                    return
                event.wait(0.25)
        thread = threading.Thread(target=sample, daemon=True, name="summary-mode-resource")
        thread.start()
        try:
            yield
            self.check()
        finally:
            event.set()
            thread.join(timeout=max(0, min(0.25, deadline - self.clock())))
            metrics.update(samples=rows, joined=not thread.is_alive(), sample_cap=721,
                sample_scope="native_rss_and_available_ram_samples_not_peak_not_vram")
            if thread.is_alive():
                self.failure = self.failure or "sampler_join"
            if self.failure:
                fail(self.failure)


def owned_create_time(process):
    import psutil
    created = psutil.Process(process.pid).create_time()
    if type(created) not in (int, float) or not math.isfinite(created) or created <= 0:
        fail("ownership")
    return created


def cleanup_owner(process, drain, metrics, *, clock=time.monotonic):
    """One cleanup interval, using only the original returned Popen/Windows handle.

    A missing or unstarted drain has no joined thread. No PID lookup is used for
    termination. A second call observes the owned handle but never gets another 5s.
    """
    if metrics.get("cleanup_entered"):
        metrics["duplicate_cleanup_observations"] = metrics.get("duplicate_cleanup_observations", 0) + 1
        if process is not None:
            try:
                metrics["process_absence_confirmed"] = process.poll() is not None
            except Exception as error:  # noqa: BLE001 - no new owner or cleanup attempt
                metrics.setdefault("cleanup_failures", []).append(error_record(error))
                metrics["process_absence_confirmed"] = None
            if metrics["process_absence_confirmed"] is not True:
                metrics["within_budget"] = False
        return
    metrics["cleanup_entered"] = True
    started = clock()
    deadline = started + 5
    metrics.update(cleanup_started_at=started, cleanup_deadline=deadline, cleanup_attempted=True)
    errors = metrics.setdefault("cleanup_failures", [])
    if process is None:
        metrics.update(process_absence_confirmed=(True if not metrics.get("process_creation_attempted") else None),
            drain_state="absent", drain={"started": False, "joined": False},
            stopped=None, owned_pipes_closed=None, remaining_drain_thread=None,
            seconds=clock() - started, within_budget=not metrics.get("process_creation_attempted"))
        return
    helper_ok = True
    drain_started = False
    if drain is not None:
        try:
            drain_started = bool(drain.started or drain.thread.is_alive()
                                 or getattr(drain.thread, "ident", None) is not None)
        except Exception as error:  # noqa: BLE001 - retain uncertain drain state
            errors.append(error_record(error))
    metrics["drain_state"] = "started" if drain_started else "not_started" if drain else "absent"
    try:
        if drain_started:
            helper_metrics = {"seconds": max(0, clock() - started)}
            cleanup_owned(process, drain, helper_metrics)
            helper_ok = helper_metrics.get("within_budget") is True
            metrics["shared_cleanup"] = helper_metrics
            metrics["drain"] = helper_metrics.get("drain", {})
        else:
            # Drain construction/start can fail after Popen. Preserve that failure;
            # this minimal branch closes only the exact handle and its own pipes.
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=min(2, max(0, deadline - clock())))
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=max(0, deadline - clock()))
            metrics["drain"] = {"started": False, "joined": False}
    except Exception as error:  # noqa: BLE001 - cleanup never replaces the original cause
        errors.append(error_record(error))
        if not drain_started:
            try:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=max(0, deadline - clock()))
            except Exception as subsequent:  # noqa: BLE001 - same owner, same remaining allowance
                errors.append(error_record(subsequent))
    finally:
        thread_alive = None
        try:
            thread_alive = drain.thread.is_alive() if drain is not None else False
        except Exception as error:  # noqa: BLE001
            errors.append(error_record(error))
        pipes_closed, seen = True, set()
        if thread_alive is False:
            for name in ("stdout", "stderr", "stdin"):
                pipe = getattr(process, name, None)
                if pipe is not None and id(pipe) not in seen:
                    seen.add(id(pipe))
                    try:
                        if not getattr(pipe, "closed", False):
                            pipe.close()
                        if getattr(pipe, "closed", True) is not True:
                            pipes_closed = False
                    except Exception as error:  # noqa: BLE001
                        pipes_closed = False
                        errors.append(error_record(error))
        else:
            pipes_closed = False  # never race a live drain's read with a close
        try:
            absent = process.poll() is not None
        except Exception as error:  # noqa: BLE001
            absent = None
            errors.append(error_record(error))
        handle = getattr(process, "_handle", None)
        handle_state = "not_exposed" if handle is None else "unverified"
        if handle is not None and absent is True and thread_alive is False:
            try:
                if not getattr(handle, "closed", False):
                    handle.Close()
                handle_state = "closed" if getattr(handle, "closed", False) else "unverified"
            except Exception as error:  # noqa: BLE001 - close only the returned process handle
                errors.append(error_record(error))
        terminal = clock()
        metrics.update(cleanup_finished_at=terminal, seconds=terminal - started,
            stopped=absent, process_absence_confirmed=absent, remaining_drain_thread=thread_alive,
            owned_pipes_closed=pipes_closed, owned_process_handle=handle_state, cleanup_errors=len(errors),
            within_budget=(terminal <= deadline and absent is True and thread_alive is False
                           and pipes_closed and not errors and helper_ok
                           and handle_state in ("closed", "not_exposed")))


@contextmanager
def owned_launcher(*, gpu_layers, log_dir, model_dir=DEFAULT_ROOT, manifest=MANIFEST,
                   phase_deadline=None, telemetry=None, port=0, token=None,
                   expected_argv=None, clock=time.monotonic):
    """Local ownership repair only; preserve the frozen launch profile and leases."""
    metrics = telemetry if telemetry is not None else {}
    if gpu_layers != 28 or type(gpu_layers) is not int or phase_deadline is None:
        fail("launcher_contract")
    profile = normalized_argv(28)
    if expected_argv is not None and profile != expected_argv:
        fail("launcher_argv")
    metrics.update(process_started=False, process_creation_attempted=False, process_returned=False,
        process_owned=False, process_absence_confirmed=True, cleanup_attempted=False,
        gpu_layers_requested=28, gpu_layers_effective=None,
        flash_attention_requested="auto_default_unchanged", flash_attention_effective=None,
        metadata_gpu_fields={"manifest_local_execution_gpu_layers": 24,
                             "scope": "frozen_artifact_declaration_not_effective_placement"},
        normalized_argv=profile)
    model_dir, manifest, log_dir = Path(model_dir), Path(manifest), Path(log_dir)
    if sha(manifest.read_bytes()) != MANIFEST_SHA256:
        fail("manifest_identity")
    if type(port) is not int or not 0 <= port <= 65535:
        fail("launcher_port")
    token = token or secrets.token_urlsafe(48)
    if not isinstance(token, str) or not 32 <= len(token) <= 256 or any(not 33 <= ord(c) <= 126 for c in token):
        fail("launcher_token")
    with ExitStack() as stack:
        stack.enter_context(worker_lease(ROOT / ".local/meeting-generation.gpu.lock"))
        with worker_lease(ROOT / ".local/meeting-generation.worker.lock"):
            pass
        stack.enter_context(worker_lease(ROOT / ".local/meeting-llama.lease"))
        metrics["startup_stage"] = "asset_preparation"
        receipt = prepare(manifest, model_dir, allow_download=False)
        check_time(clock, phase_deadline)
        server = (model_dir / receipt["server_path"]).resolve()
        model = (model_dir / receipt["model"]["path"]).resolve()
        log_dir.mkdir(parents=True, exist_ok=False)
        environment = {k: v for k, v in os.environ.items() if not k.startswith("LLAMA_ARG_")}
        environment.update(LLAMA_API_KEY=token, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        port = port or unused_port()
        argv = command(server, model, port, 28)
        if argv != [str(server) if value == "<verified-server>" else
                    str(model) if value == "<verified-model>" else
                    str(port) if value == "<loopback-port>" else value for value in profile]:
            fail("launcher_argv")
        process, drain, yielded = None, None, False
        # The cleanup obligation exists BEFORE Popen and every later constructor.
        try:
            check_time(clock, phase_deadline)
            metrics["startup_stage"] = "process_creation"
            metrics.update(process_creation_attempted=True, process_absence_confirmed=None)
            process = subprocess.Popen(argv, cwd=server.parent, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            metrics.update(process_returned=True, process_owned=True, process_started=True,
                           owned_pid=process.pid, owner_basis="original_returned_popen_handle")
            metrics["startup_stage"] = "create_time"
            metrics["owned_create_time"] = owned_create_time(process)
            metrics["startup_stage"] = "drain_construction"
            drain = DiscardDrain(process.stdout)
            metrics["startup_stage"] = "drain_start"
            drain.start()
            check_time(clock, phase_deadline)
            url = f"http://127.0.0.1:{port}"
            metrics["startup_stage"] = "readiness"
            wait_ready(process, url + "/health", headers={"Authorization": "Bearer " + token},
                       timeout=min(240, max(0.01, phase_deadline - clock())))
            check_time(clock, phase_deadline)
            yielded = True
            metrics["startup_stage"] = "yielded"
            yield CompatService(process, url, token, manifest, receipt, metrics, drain)
        except Exception as error:
            metrics.setdefault("owner_context_failure" if yielded else "startup_failure", error_record(error))
            raise
        finally:
            cleanup_owner(process, drain, metrics, clock=clock)


def source_catalog(document, adapter):
    units = [u for group in partitions(document["content"], adapter) for u in group]
    source = source_payload(document["title"], document["content"], units)
    return {"identity": {k: document[k] for k in ("id", "document_id", "revision", "content_sha256")},
            "source": source, "units": units, "catalog_sha256": sha(encoded(source))}


def stage_call(row, name, adapter, call):
    row[name + "_status"] = "attempted_failed"
    row[name + "_attempted"] = True
    before = len(adapter.request_log)
    try:
        result = call()
        row[name + "_status"] = "returned"
        return result
    finally:
        requests = [r for r in adapter.request_log[before:] if r["category"] == name]
        row[name + "_transport"] = {
            "request_entries": len(requests),
            "client_dispatches": sum(r["client_dispatched"] for r in requests),
            "responses_received": sum(r["response_received"] for r in requests),
            "validated_completion": row[name + "_status"] == "returned",
            "request_ids": [r["id"] for r in requests],
            "scope": "client_handoff_and_response_not_server_execution_proof",
            "validation_scope": "native_response_before_draft_or_review_parser"}


def arm_body(row, report, document, entry, prepared, adapter, *, generation_end, end, emit, clock):
    assigned = {k: row[k] for k in ("document", "mode")}
    if sha(encoded(entry["source"])) != entry["catalog_sha256"]:
        fail("catalog_drift")
    check_time(clock, generation_end)
    generated = stage_call(row, "generation", adapter, lambda: adapter.generate(
        summary_messages(entry["source"]), row["mode"] == "B", prepared, generation_end))
    emit("generation", {**assigned, **generated})
    row["generation"] = {k: v for k, v in generated.items() if k not in ("content", "reasoning")}
    try:
        claims = parse_draft(generated["content"], entry["units"], document["content"])
        row["generation_contract_validated"] = True
    except WorkerError as error:
        if error.code != "generation_summary_insufficient":
            raise
        row.update(status="generation_abstained", model_review_accepted=False,
                   generation_contract_validated=True,
                   review_not_started_reason="generation_abstained_no_claims")
        record_failure(report, {**assigned, **error_record(error), "kind": "semantic_abstention"}, stop=True)
        return
    projection = summary_projection(claims, document["content"])
    emit("judge_candidate", {"source": entry["source"], "claims": claims})
    check_time(clock, end)
    review = stage_call(row, "review", adapter, lambda: adapter.review(summary_messages(entry["source"], claims), end))
    emit("review", {**assigned, **review})
    row["review"] = {k: v for k, v in review.items() if k != "content"}
    try:
        parse_review(review["content"], len(claims))
        row.update(status="accepted", model_review_accepted=True, review_contract_validated=True)
    except WorkerError as error:
        if error.code != "generation_summary_review_rejected":
            raise
        row.update(status="semantic_review_rejected", model_review_accepted=False, review_contract_validated=True)
        rejection = {**assigned, **error_record(error), "kind": "semantic_review"}
        report["semantic_rejections"].append(rejection)
        record_failure(report, rejection)
    emit("arm", {**row, "projection": projection})
    check_time(clock, end)


def diagnose(documents, adapter, *, active_deadline, emit, clock=time.monotonic,
             guard=None, checkpoint=None):
    """No product writes, retries or repair. All eight admissions precede completions."""
    schedule = order(documents)
    report = {"diagnostic": ID, "order": schedule, "arms": [], "unexecuted": copy.deepcopy(schedule),
              "first_failure": None, "semantic_rejections": [], "status": "running"}
    catalog, prepared = {}, {}
    common_start = clock()
    try:
        adapter.begin_request(active_deadline)
        for document in documents:
            check_time(clock, active_deadline)
            entry = source_catalog(document, adapter)
            catalog[document["id"]] = entry
            messages = summary_messages(entry["source"])
            pair = {mode: adapter.prepare(messages, mode == "B", active_deadline) for mode in ("A", "B")}
            if (pair["A"]["prompt"].removesuffix(NONTHINKING_PREAMBLE)
                    != pair["B"]["prompt"].removesuffix(PREAMBLE)):
                fail("mode_template_difference")
            prepared[document["id"]] = pair
            emit("catalog", {"document": document["id"], **entry, "prepared": pair})
        report["common_preparation_seconds"] = clock() - common_start
        adapter.end_request()
        by_id = {row["id"]: row for row in documents}
        for assigned in schedule:
            check_time(clock, active_deadline)
            started = clock()
            end = min(active_deadline, started + 180)
            generation_end = min(end, started + 150)
            row = {**assigned, "status": "started", "resources": {},
                   "generation_status": "not_started", "review_status": "not_started",
                   "generation_attempted": False, "review_attempted": False,
                   "generation_contract_validated": False, "review_contract_validated": False,
                   "model_review_accepted": None}
            report["arms"].append(row)
            report["unexecuted"].pop(0)
            adapter.begin_request(end)
            @contextmanager
            def no_guard():
                yield
            arm_error = None
            try:
                with guard.arm(end, row["resources"]) if guard else no_guard():
                    try:
                        if checkpoint:
                            row["gpu"] = checkpoint()
                        arm_body(row, report, by_id[assigned["document"]], catalog[assigned["document"]],
                            prepared[assigned["document"]][assigned["mode"]], adapter,
                            generation_end=generation_end, end=end, emit=emit, clock=clock)
                    except Exception as error:
                        record_failure(report, {**assigned, **error_record(error)}, operational=True, stop=True)
                        raise
            except Exception as error:  # noqa: BLE001 - retain body failure before guard exit failure
                arm_error = error
                record_failure(report, {**assigned, **error_record(error)}, operational=True, stop=True)
            adapter.end_request()
            try:
                row["elapsed_seconds"] = clock() - started
                emit("arm_terminal", row)
                terminal = clock()
                row["elapsed_seconds"] = terminal - started
                if terminal >= end:
                    fail("deadline")
            except Exception as error:  # noqa: BLE001 - guard exit and writes share the original arm cap
                record_failure(report, {**assigned, **error_record(error)}, operational=True, stop=True)
                arm_error = arm_error or error
            if arm_error is not None:
                raise arm_error
            if row["status"] == "generation_abstained":
                break
        report["status"] = ("completed" if not report["unexecuted"] and all(
            row["status"] in ("accepted", "semantic_review_rejected") for row in report["arms"])
            else "stopped")
    except Exception as error:  # noqa: BLE001 - terminal custody preserves every failure
        record = error_record(error)
        if report["arms"]:
            report["arms"][-1].update(status="operational_failed", failure=record)
        record_failure(report, record, operational=True, stop=True)
        report["status"] = "stopped"
    finally:
        adapter.end_request()
        report["counts"] = dict(adapter.counts)
        report["request_log"] = copy.deepcopy(adapter.request_log)
        report["count_scope"] = "request_entries_vs_client_dispatches_vs_response_headers_vs_validated_completion"
        report["elapsed_active_seconds"] = clock() - common_start
        try:
            emit("diagnostic", report)
        except Exception as error:  # noqa: BLE001 - preserve earlier causes if final evidence fails
            record_failure(report, error_record(error), operational=True, stop=True)
            report["status"] = "stopped"
    return report


def bound_path(name, root):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        fail("path")
    candidate = root / name
    if Path(name).is_absolute() or ".." in Path(name).parts or not candidate.resolve().is_relative_to(root.resolve()):
        fail("path")
    for part in [candidate, *candidate.parents]:
        if part == root.parent:
            break
        if linked(part):
            fail("linked_path")
    return candidate


def check_ref(reference, root):
    if not isinstance(reference, dict) or set(reference) != {"file", "sha256", "size_bytes"}:
        fail("reference")
    path = bound_path(reference["file"], root)
    if digest(path) != {k: reference[k] for k in ("sha256", "size_bytes")}:
        fail("binding_changed")
    return path


def verify_registration(path, expected_sha, root=ROOT):
    """Read-only admission. Never creates a registration, run, model or output directory."""
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha) or sha(path.read_bytes()) != expected_sha:
        fail("registration_identity")
    spec = strict_json(path.read_text(encoding="utf-8"))
    required = {"schema_version", "diagnostic", "prepared", "limits", "input", "plan", "amendment", "code",
                "assets", "source_receipt", "source_lock", "order", "output_dir", "runtime"}
    if (not isinstance(spec, dict) or set(spec) != required
            or type(spec["schema_version"]) is not int or spec["schema_version"] != 1
            or spec["diagnostic"] != ID or spec["prepared"] is not True
            or encoded(spec["limits"]) != encoded(LIMITS)
            or spec["plan"] != {"file": PLAN, "sha256": PLAN_SHA, "size_bytes": 18650}
            or spec["amendment"] != {"file": AMENDMENT, "sha256": AMENDMENT_SHA, "size_bytes": 11215}
            or spec["runtime"] != {"manifest_sha256": MANIFEST_SHA256, "model_sha256": GGUF_SHA256,
                "commit": RUNTIME_COMMIT, "argv": normalized_argv(28)}):
        fail("registration_contract")
    code_names = {p.relative_to(root).as_posix() for pattern in ("src/doctrail/*.py", "scripts/*.py")
                  for p in root.glob(pattern)} | {"pyproject.toml", "uv.lock", "tests/test_probe_meeting_summary_mode.py"}
    if (not isinstance(spec["code"], list) or {r["file"] for r in spec["code"]} != code_names
            or len(spec["code"]) != len(code_names)):
        fail("code_binding")
    model_root = bound_path("models/meetings-qwen35-v1", root)
    asset_names = {p.relative_to(root).as_posix() for p in model_root.rglob("*") if p.is_file()}
    if (not asset_names or not isinstance(spec["assets"], list)
            or {r["file"] for r in spec["assets"]} != asset_names or len(spec["assets"]) != len(asset_names)
            or "models/meetings-qwen35-v1/setup-receipt.json" not in asset_names):
        fail("asset_binding")
    for reference in [spec[k] for k in ("plan", "amendment", "input", "source_receipt", "source_lock")] + spec["code"] + spec["assets"]:
        check_ref(reference, root)
    if sha((root / "data/models/meetings-generation-qwen35-v1.json").read_bytes()) != MANIFEST_SHA256:
        fail("manifest_identity")
    documents = validate_input(strict_json(check_ref(spec["input"], root).read_text(encoding="utf-8")))
    if spec["order"] != order(documents):
        fail("order_binding")
    output = bound_path(spec["output_dir"], root)
    if not output.is_relative_to(root / ".local") or output.exists() or output.name != ID:
        fail("output_exists_or_scope")
    # Source-specific receipt/lock contents belong to separate custodians. Only hash
    # and role-neutral registration bindings are used by this executor.
    return spec, documents, output


class Evidence:
    def __init__(self, output):
        self.output, self.index, self.count = output, [], 0

    def __call__(self, kind, value):
        self.count += 1
        filename = f"{self.count:04d}-{kind}.json"
        data = encoded(value) + b"\n"
        with (self.output / filename).open("xb") as stream:
            stream.write(data)
        self.index.append({"file": filename, "size_bytes": len(data), "sha256": sha(data)})

    def seal(self, report):
        self("final-report", report)
        self("index", list(self.index))


def finalize(report, emit, *, clock, started, active_start=None, cleanup_seconds=0):
    """Seal, then measure. A late invalidation is append-only, never overwrites proof.

    The after-seal observation is returned to the caller for its external receipt.
    A file cannot contain the measured duration of its own future write. Eligibility
    therefore always requires the caller's returned terminal receipt as well.
    """
    arms, counts = report.get("arms", []), report.get("counts", {})
    completed = (report.get("status") == "completed" and len(arms) == 8
        and report.get("unexecuted") == [] and all(
            row.get("status") in ("accepted", "semantic_review_rejected")
            and row.get("generation_status") == row.get("review_status") == "returned" for row in arms)
        and all(counts.get(key) == 8 for key in ("generation", "review", "generation_validated", "review_validated")))
    report["eligible"] = (completed and not report.get("operational_failure")
                          and report.get("bindings_unchanged") is True)
    report["eligibility_scope"] = "operational_diagnostic_completion_not_independent_quality"
    report["independent_quality_acceptance"] = "not_evaluated"
    report["requires_terminal_receipt"] = True
    report["whole_seconds_before_final_writes"] = clock() - started
    report["sealing_status"], report["evidence_sealed"] = "pending", False
    try:
        emit.seal(report)
    except Exception as error:  # noqa: BLE001 - retain custody even when disk evidence fails
        report["eligible"] = False
        report["sealing_status"] = "failed"
        record_failure(report, {**error_record(error), "stage": "final_seal"}, operational=True, stop=True)
    else:
        report["sealing_status"], report["evidence_sealed"] = "complete", True
    terminal = clock()
    elapsed = terminal - started
    active_elapsed = None if active_start is None else terminal - active_start - cleanup_seconds
    late = []
    if elapsed >= 1625:
        late.append("summary_mode_whole_deadline")
    if active_elapsed is not None and active_elapsed >= 1500:
        late.append("summary_mode_active_deadline")
    if late:
        report["eligible"] = False
        for code in late:
            record_failure(report, {"code": code}, operational=True, stop=True)
        if report["evidence_sealed"]:
            try:
                emit("finalization-failure", {"elapsed_after_seal": elapsed,
                    "active_elapsed_after_seal": active_elapsed, "eligible": False, "codes": late})
            except Exception as error:  # noqa: BLE001 - no recursive write to report a write failure
                report["sealing_status"], report["evidence_sealed"] = "failed", False
                record_failure(report, {**error_record(error), "stage": "final_invalidation"},
                               operational=True, stop=True)
            terminal = clock()  # after successful or failed append, never promoted
    report["terminal_observed_at"] = terminal
    report["operational_eligible"] = report["eligible"]
    report["whole_seconds_after_final_writes"] = terminal - started
    report["active_seconds_after_final_writes"] = (None if active_start is None
                                                 else terminal - active_start - cleanup_seconds)
    return report


def execute(path, expected_sha, *, root=ROOT, clock=time.monotonic):
    """CLI once entry; tests replace owners/HTTP and use temporary synthetic paths."""
    started = clock()
    spec, documents, output = verify_registration(path, expected_sha, root)
    check_time(clock, started + 120)
    import psutil
    if psutil.virtual_memory().available < LIMITS["startup_available_bytes"]:
        fail("startup_ram")
    output.mkdir(exist_ok=False)
    emit, metrics, report = Evidence(output), {}, {"diagnostic": ID, "first_failure": None,
        "arms": [], "unexecuted": order(documents), "status": "stopped"}
    adapter, active_start, close_attempted = None, None, False

    def close_client():
        nonlocal close_attempted
        if adapter is None or close_attempted:
            return
        close_attempted = True  # the first close may throw; never grant another attempt
        try:
            adapter.close()
        except Exception as error:  # noqa: BLE001 - preserve primary startup/body failure
            record_failure(report, {**error_record(error), "stage": "client_close"},
                           operational=True, stop=True)

    try:
        with owned_launcher(gpu_layers=28, log_dir=output / "native", model_dir=root / DEFAULT_ROOT.relative_to(ROOT),
                manifest=root / MANIFEST.relative_to(ROOT), phase_deadline=started + 120, telemetry=metrics,
                expected_argv=spec["runtime"]["argv"], clock=clock) as service:
            guard = ResourceGuard(service.process, clock=clock, expected_created=metrics.get("owned_create_time"))
            metrics["owned_create_time"] = guard.created
            adapter = ModeAdapter(service.url, service.token, service.manifest, clock=clock,
                                  observe=emit, resource_check=guard.check)
            adapter.begin_request(started + 120)
            adapter.load()
            check_time(clock, started + 120)
            active_start = clock()
            from scripts.probe_meeting_gpu_placement import gpu_checkpoint
            gpu_identity = None
            def checkpoint():
                nonlocal gpu_identity
                row = gpu_checkpoint(expected_uuid=gpu_identity)
                if not row["query_stopped"] or row.get("error"):
                    fail("gpu_checkpoint")
                gpu_identity = row["uuid"]
                return row
            try:
                report = diagnose(documents, adapter, active_deadline=min(started + 1620, active_start + 1500),
                    emit=emit, clock=clock, guard=guard, checkpoint=checkpoint)
                check_time(clock, active_start + 1500)
            except Exception as error:  # noqa: BLE001 - retain body cause before client shutdown
                record_failure(report, error_record(error), operational=True, stop=True)
            finally:
                close_client()
    except Exception as error:  # noqa: BLE001 - retain startup/owner/cleanup failures
        record_failure(report, error_record(error), operational=True, stop=True)
    finally:
        if adapter:
            close_client()
            report["counts"] = dict(adapter.counts)
        report.update(cleanup=metrics, registration_sha256=expected_sha, limits=LIMITS,
            hard_blocking_io_preemption_proven=False, product_writes=0, retries=0, warmups=0,
            effective_offload_layers=None, effective_flash_attention=None)
        if metrics.get("process_creation_attempted") and (metrics.get("within_budget") is not True
                or metrics.get("process_absence_confirmed") is not True):
            record_failure(report, {"code": "summary_mode_cleanup"}, operational=True, stop=True)
        # Post-custody proof remains inside whole elapsed accounting; it is not an
        # extra model/resource call. Recheck exact bound files without touching outputs.
        try:
            if sha(path.read_bytes()) != expected_sha:
                fail("registration_identity")
            if sha((root / "data/models/meetings-generation-qwen35-v1.json").read_bytes()) != MANIFEST_SHA256:
                fail("manifest_identity")
            for reference in [spec[k] for k in ("plan", "amendment", "input", "source_receipt", "source_lock")] + spec["code"] + spec["assets"]:
                check_ref(reference, root)
            report["bindings_unchanged"] = True
        except Exception as error:  # noqa: BLE001 - custody errors invalidate execution
            report["bindings_unchanged"] = False
            record_failure(report, error_record(error), operational=True, stop=True)
        finalize(report, emit, clock=clock, started=started, active_start=active_start,
                 cleanup_seconds=metrics.get("seconds", 0))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--execute-once-sha256", required=True)
    args = parser.parse_args()
    try:
        report = execute(args.registration, args.execute_once_sha256)
    except Exception as error:  # noqa: BLE001 - CLI terminal receipt, never a retry
        print(json.dumps({"eligible": False, "receipt_scope": "unbound_rejection",
                          "failure": error_record(error)}))
        return 1
    print(json.dumps({"receipt_scope": "bound_terminal", **{key: report.get(key) for key in (
        "eligible", "operational_eligible", "status", "registration_sha256", "terminal_observed_at",
        "first_failure", "operational_failure", "failure_history", "stop_reason", "counts", "cleanup",
        "bindings_unchanged", "retries", "unexecuted", "sealing_status", "evidence_sealed",
        "requires_terminal_receipt", "eligibility_scope", "independent_quality_acceptance",
        "whole_seconds_after_final_writes", "active_seconds_after_final_writes")}}))
    return 0 if report["eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
