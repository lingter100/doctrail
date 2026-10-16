"""One private neutral GPU24/28 resource pair. No closed evaluation data is read."""
from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_thinking_transport import (
    GGUF_SHA256,
    MANIFEST_SHA256,
    MODEL_ID,
    MODEL_REVISION,
    PREAMBLE,
    RUNTIME_COMMIT,
    ThinkingGenerator,
    request_body,
)
from scripts import prepare_meeting_thinking_inputs as primitives
from scripts.check_meeting_review_token_budget import load_tokenizer
from scripts.prepare_meeting_budget_inputs import _tokenizer_metadata
from scripts.probe_meeting_blocks_resources import owned_watchdog
from scripts.profile_meeting_host_proof import _module_candidates
from scripts.serve_meeting_gpu_placement import normalized_argv, start_llama
from scripts.serve_meeting_thinking_compat import cleanup_owned

ROOT = Path(__file__).resolve().parents[1]
ID = "meetings-gpu-placement-v1"
DESIGN = "docs/MEETINGS-GPU-PLACEMENT-PLAN.md"
PROTOCOL = "data/evaluation/meetings-gpu-placement-protocol-v1.json"
MANIFEST = "data/models/meetings-generation-qwen35-v1.json"
FREEZE = "data/evaluation/meetings-gpu-placement-source-freeze-v1.json"
PLAN = "data/evaluation/meetings-gpu-placement-execution-plan-v1.json"
RECEIPT = "data/evaluation/meetings-gpu-placement-preparation-v1.json"
PREPARATION = ".local/meetings-gpu-placement-preparation-v1"
OUTPUT = ".local/meetings-gpu-placement-v1"
OWNED = ("scripts/serve_meeting_gpu_placement.py", "scripts/probe_meeting_gpu_placement.py",
         "tests/test_meeting_gpu_placement_launcher.py", "tests/test_probe_meeting_gpu_placement.py")
PINNED = {DESIGN: "5cd3a9cf602b4b8371c0c869728e9009ef1c4b36d6558900e9a61f9f8e3a52f4",
          PROTOCOL: "8cad4fe8536b9f5707649150f48c2d7e41de89240582143146bcf7f886ce1b08",
          MANIFEST: MANIFEST_SHA256}
ARMS = (("gpu24-control", 24), ("gpu28-candidate", 28))
SCHEMA = {"type": "object", "properties": {"marker": {"type": "string", "const": "teal"}},
          "required": ["marker"], "additionalProperties": False}
CHECKPOINTS = ("before_launch", "immediately_before_send", "request_terminal", "after_cleanup")


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii") + b"\n"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def messages():
    return [{"role": "system", "content": "New neutral GPU placement comparison. Ignore the "
             "mechanical filler. Think briefly, then return exactly the JSON object "
             '{"marker":"teal"} and finish naturally.'},
            {"role": "user", "content": "New placement filler begins: " + "u " * 5000
             + "\nThe filler has no factual meaning. Return the fixed marker now."}]


def fixture_spec():
    return {"padding_unit": "u ", "padding_repetitions": 5000,
            "messages_sha256": sha(encoded(messages())), "schema_sha256": sha(encoded(SCHEMA)),
            "request_sha256": sha(encoded(request_body(messages(), SCHEMA))),
            "arms": [{"id": name, "gpu_layers_requested": layers,
                      "normalized_argv": normalized_argv(layers)} for name, layers in ARMS]}


def source_manifest(root=ROOT, *, sealed=None):
    """Pre-freeze code-only discovery; sealed mode rejects new bodies before reads."""
    root = Path(root)
    pending, bound, candidates = list(OWNED), {}, {}
    while pending:
        name = pending.pop()
        if name in bound:
            continue
        if not name.endswith(".py") or sealed is not None and name not in sealed["code_roster"]:
            raise ValueError("placement_code_allowlist")
        raw = primitives.snapshot(primitives.path(name, root))[0]
        bound[name] = sha(raw)
        if sealed is not None and bound[name] != sealed["bound_files"].get(name):
            raise ValueError("placement_source_changed")
        for candidate in _module_candidates(ast.parse(raw), name):
            exists = primitives.path(candidate, root).is_file()
            candidates[candidate] = exists
            if sealed is not None and (sealed["import_candidates"].get(candidate) is not exists
                                       or exists and candidate not in sealed["code_roster"]):
                raise ValueError("placement_code_allowlist")
            if exists and candidate not in bound:
                pending.append(candidate)
    roster = sorted(bound)
    for name, expected in PINNED.items():
        actual = sha(primitives.snapshot(primitives.path(name, root))[0])
        if actual != expected:
            raise ValueError("placement_pinned_identity")
        bound[name] = actual
    for name in ("pyproject.toml", "uv.lock"):
        bound[name] = sha(primitives.snapshot(primitives.path(name, root))[0])
    return {"schema_version": 1, "id": ID, "bound_files": dict(sorted(bound.items())),
            "code_roster": roster, "import_candidates": dict(sorted(candidates.items())),
            "fixture_spec": fixture_spec()}


def safe_error(error):
    code = error.code if isinstance(error, GenerationError) else str(error)
    if not isinstance(code, str) or not re.fullmatch(r"(?:placement|generation|c4|preparation)_[a-z0-9_]+", code):
        code = "placement_failed_closed"
    return {"code": code, "type": type(error).__name__}


class CommonFailure(ValueError):
    pass


def write_new(root, name, value):
    try:
        target = primitives.path(name, root)
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = value if isinstance(value, bytes) else encoded(value)
        primitives.write_new(name, raw, root)
    except (OSError, ValueError, TypeError) as error:
        raise CommonFailure("placement_evidence_persistence") from error
    return {"sha256": sha(raw), "bytes": len(raw)}


def save(root, name, value):
    temporary = name + "." + uuid.uuid4().hex + ".tmp"
    write_new(root, temporary, value)
    try:
        os.replace(primitives.path(temporary, root), primitives.path(name, root))
    except (OSError, ValueError, TypeError) as error:
        raise CommonFailure("placement_evidence_persistence") from error


def read(root, name):
    return primitives.strict_json(primitives.snapshot(primitives.path(name, root))[0].decode("utf-8"))


def integrity(root=ROOT, *, proof=None):
    root = Path(root)
    proof = proof or primitives.GitProof(root)
    try:
        proof([FREEZE], root=root)  # Committed bytes before the allowlist authorizes code reads.
        frozen = read(root, FREEZE)
        actual = source_manifest(root, sealed=frozen)
        if encoded(actual) != encoded(frozen):
            raise ValueError("placement_source_freeze")
        proof(actual["bound_files"], root=root)
        return {"head": proof.head, "freeze_sha256": sha(primitives.snapshot(primitives.path(FREEZE, root))[0]),
                "bound_files": actual["bound_files"], "fixture_spec": actual["fixture_spec"]}, proof
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise CommonFailure("placement_common_integrity") from error


def register(root=ROOT, *, loader=load_tokenizer):
    root = Path(root)
    binding, proof = integrity(root)
    target = primitives.path(PREPARATION, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(exist_ok=False)
    receipt = {"schema_version": 1, "id": ID, "status": "started", "tokenizer_loads": 0,
               "unique_prompt_counts": 0, "native_calls": 0, "downloads": 0, "binding": binding}
    try:
        save(root, PREPARATION + "/receipt.json", receipt)
        receipt["tokenizer_loads"] = 1
        save(root, PREPARATION + "/receipt.json", receipt)
        tokenizer, metadata = loader(False)
        _tokenizer_metadata(metadata)
        if metadata["repo_id"] != MODEL_ID or metadata["revision"] != MODEL_REVISION:
            raise ValueError("placement_tokenizer_identity")
        prompt = tokenizer.apply_chat_template(messages(), tokenize=False,
            add_generation_prompt=True, enable_thinking=True)
        if not isinstance(prompt, str) or not prompt.endswith(PREAMBLE):
            raise ValueError("placement_template")
        receipt["unique_prompt_counts"] = 1
        tokens = tokenizer.encode(prompt, add_special_tokens=False)
        if not isinstance(tokens, list) or not tokens or any(type(t) is not int or t < 0 for t in tokens):
            raise ValueError("placement_tokens")
        private = {"messages": messages(), "schema": SCHEMA, "prompt": prompt, "token_ids": tokens}
        receipt.update(tokenizer=metadata, input_tokens=len(tokens), prompt_sha256=sha(prompt.encode("utf-8")),
                       token_ids_sha256=sha(encoded(tokens)),
                       private_input=write_new(root, PREPARATION + "/input.json", private))
        if not 4992 <= len(tokens) <= 5120:
            raise ValueError("placement_input_range")
        if integrity(root, proof=proof)[0] != binding:
            raise CommonFailure("placement_common_integrity")
        receipt["status"] = "passed"
        save(root, PREPARATION + "/receipt.json", receipt)
        reference = write_new(root, RECEIPT, receipt)
        plan = {"schema_version": 1, "id": ID, "binding": binding,
                "receipt": reference, "fixture_spec": fixture_spec(),
                "private_input": receipt["private_input"], "input_tokens": len(tokens),
                "prompt_sha256": receipt["prompt_sha256"], "token_ids_sha256": receipt["token_ids_sha256"]}
        write_new(root, PLAN, plan)
        return receipt
    except Exception as error:  # noqa: BLE001 - exclusive preparation stays consumed.
        receipt.update(status="failed", error=safe_error(error))
        try:
            save(root, PREPARATION + "/receipt.json", receipt)
        except Exception as later:  # noqa: BLE001 - preserve the first failure.
            receipt["persistence_error"] = safe_error(later)
        return receipt


def check(root=ROOT, *, proof=None):
    root = Path(root)
    binding, proof = integrity(root, proof=proof)
    try:
        proof([PLAN, RECEIPT], root=root)
        plan, receipt = read(root, PLAN), read(root, RECEIPT)
        raw = primitives.snapshot(primitives.path(PREPARATION + "/input.json", root))[0]
        private = primitives.strict_json(raw.decode("utf-8"))
        receipt_raw = primitives.snapshot(primitives.path(RECEIPT, root))[0]
        if (plan.get("id") != ID or plan.get("fixture_spec") != fixture_spec()
                or plan.get("binding", {}).get("bound_files") != binding["bound_files"]
                or plan["binding"].get("freeze_sha256") != binding["freeze_sha256"]
                or plan.get("receipt") != {"sha256": sha(receipt_raw), "bytes": len(receipt_raw)}
                or receipt.get("status") != "passed" or receipt.get("tokenizer_loads") != 1
                or receipt.get("unique_prompt_counts") != 1 or receipt.get("native_calls") != 0
                or receipt.get("downloads") != 0 or receipt.get("binding") != plan["binding"]
                or plan.get("private_input") != {"sha256": sha(raw), "bytes": len(raw)}
                or receipt.get("private_input") != plan["private_input"]
                or private.get("messages") != messages() or private.get("schema") != SCHEMA
                or type(plan.get("input_tokens")) is not int or not 4992 <= plan["input_tokens"] <= 5120
                or not isinstance(private.get("prompt"), str) or not private["prompt"].endswith(PREAMBLE)
                or not isinstance(private.get("token_ids"), list)
                or any(type(t) is not int or t < 0 for t in private["token_ids"])
                or len(private["token_ids"]) != plan["input_tokens"]
                or sha(private["prompt"].encode("utf-8")) != plan.get("prompt_sha256")
                or sha(encoded(private["token_ids"])) != plan.get("token_ids_sha256")
                or any(receipt.get(k) != plan.get(k) for k in ("input_tokens", "prompt_sha256", "token_ids_sha256"))):
            raise ValueError("placement_plan_binding")
        _tokenizer_metadata(receipt["tokenizer"])
        return {"root": root, "plan": plan, "private": private, "proof": proof,
                "head": binding["head"], "plan_sha256": sha(primitives.snapshot(primitives.path(PLAN, root))[0])}
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise CommonFailure("placement_common_integrity") from error


def verify(prepared):
    current = check(prepared["root"], proof=prepared["proof"])
    if any(current[k] != prepared[k] for k in ("head", "plan_sha256", "plan", "private")):
        raise CommonFailure("placement_common_integrity")


class PlacementGenerator(ThinkingGenerator):
    """Only add observation hooks and an earlier outer deadline to frozen transport."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outer_deadline, self.observer = None, None
        self._client.event_hooks["request"].append(self._send)
        self._client.event_hooks["response"].append(self._status)

    def _remaining(self, deadline=None):
        candidates = [d for d in (deadline, self._deadline, self.outer_deadline) if d is not None]
        return super()._remaining(min(candidates) if candidates else None)

    def _send(self, request):
        remaining = self._remaining()
        if request.method == "POST" and request.url.path == "/v1/chat/completions":
            if self.observer:
                self.observer("http_send_attempt", True)
            remaining = self._remaining()  # Observer/fsync can consume the last millisecond.
        request.extensions["timeout"] = {key: min(value, remaining) if value is not None else remaining
            for key, value in request.extensions.get("timeout", {}).items()}

    def _status(self, response):
        if self.observer and response.request.url.path == "/v1/chat/completions":
            self.observer("native_http_status", response.status_code)

    def _request(self, method, path, payload=None, deadline=None):
        operation = {"/apply-template": "template", "/tokenize": "input_tokenize" if payload and payload.get("parse_special") else "final_tokenize",
                     "/v1/chat/completions": "native"}.get(path)
        start = time.monotonic()
        returned_at = None
        try:
            response = super()._request(method, path, payload, deadline)
            returned_at = time.monotonic()
            if self.observer and operation:
                self.observer(operation + "_response", response)
            return response
        finally:
            if self.observer and operation:
                self.observer(operation + "_http_seconds", (returned_at or time.monotonic()) - start)


@contextmanager
def bounded_rss(process, metrics, deadline):
    import psutil
    stop, samples = threading.Event(), []
    def sample():
        while not stop.is_set() and time.monotonic() <= deadline and len(samples) < 361:
            try:
                samples.append({"at": time.monotonic(), "bytes": psutil.Process(process.pid).memory_info().rss})
            except (psutil.Error, OSError):
                metrics["missing_reason"] = "rss_unavailable"
                break
            stop.wait(0.25)
    worker = threading.Thread(target=sample, daemon=True)
    metrics.update(scope="owned_pid_sampled_rss_not_gpu_not_peak", samples=samples,
                   interval_seconds=0.25, maximum_samples=361)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=1)
        metrics.update(joined=not worker.is_alive(), sample_count=len(samples),
                       max_sample_bytes=max((s["bytes"] for s in samples), default=None))


def gpu_checkpoint(expected_uuid=None):
    started = time.monotonic()
    deadline = started + 1
    row = {"at": started, "uuid": expected_uuid, "total_mib": None, "used_mib": None,
           "free_mib": None, "process_vram_mib": None, "scope": "device_wide_sample_not_process_not_peak",
           "query_started": False, "query_stopped": True, "error": None}
    utility = shutil.which("nvidia-smi")
    if utility is None:
        row["error"] = "utility_unavailable"
        return row
    command = [utility, "--query-gpu=uuid,memory.total,memory.used,memory.free", "--format=csv,noheader,nounits"]
    if expected_uuid:
        command += ["--id=" + expected_uuid]
    process = None
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        row.update(query_started=True, query_stopped=False)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, 1)
        raw, _ = process.communicate(timeout=remaining)
        if time.monotonic() > deadline:
            raise subprocess.TimeoutExpired(command, 1)
        if len(raw) > 8192 or process.returncode:
            raise ValueError("gpu_query_failed")
        lines = raw.decode("ascii").strip().splitlines()
        if len(lines) != 1:
            raise ValueError("gpu_identity_ambiguous")
        identity, *numbers = [part.strip() for part in lines[0].split(",")]
        if not re.fullmatch(r"GPU-[a-fA-F0-9-]{8,80}", identity) or len(numbers) != 3:
            raise ValueError("gpu_query_format")
        if expected_uuid and identity != expected_uuid:
            raise ValueError("gpu_identity_changed")
        values = [float(n) for n in numbers]
        if any(not math.isfinite(n) or n < 0 for n in values):
            raise ValueError("gpu_query_format")
        row.update(uuid=identity, total_mib=values[0], used_mib=values[1], free_mib=values[2])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        row["error"] = "gpu_query_unavailable"
    finally:
        cleanup_start = time.monotonic()
        row["query_seconds"] = cleanup_start - started
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=1)
                row["query_stopped"] = process.poll() is not None
            except (OSError, subprocess.TimeoutExpired):
                row["query_stopped"] = False
            if process.stdout is not None and row["query_stopped"]:
                process.stdout.close()
        row["elapsed_seconds"] = time.monotonic() - started
        row["cleanup_seconds"] = time.monotonic() - cleanup_start
    return row


def cleanup_safe(metrics):
    if metrics.get("process_started") is not True:
        return metrics.get("process_absence_confirmed") is True
    drain = metrics.get("drain", {})
    return (metrics.get("stopped") is True and metrics.get("within_budget") is True
            and metrics.get("cleanup_errors") == 0 and drain.get("eof") is True
            and drain.get("joined") is True and drain.get("read_errors") == 0 and drain.get("join_errors") == 0)


@contextmanager
def request_boundary(row):
    try:
        yield
    except Exception as error:
        row.setdefault("error", safe_error(error))
        row["_first_common_failure"] = common_error(error)
        raise
    finally:
        row["_request_terminal_at"] = time.monotonic()


def common_error(error):
    return isinstance(error, CommonFailure) or safe_error(error)["code"] in {
        "generation_identity_mismatch", "placement_manifest_identity", "placement_asset_identity",
        "placement_phase_deadline"}


def summarize_stage_timing(row):
    names = ("timed_verify", "template_and_input_tokenize", "before_send_attestation_and_reservation",
             "native_http", "finalize_validation_retokenization_and_required_persistence")
    stages = row["stages_seconds"]
    for name in names:
        stages.setdefault(name, None)
    missing = [name for name in names if stages[name] is None]
    total = row.get("request_seconds")
    stage_sum = sum(stages.values()) if not missing else None
    row["stage_timing"] = {
        "scope": "Ordered request stages; HTTP detail and native reported timings overlap these stages and must not be added",
        "missing_stage_boundaries": missing,
        "missing_semantics": "Null means no complete boundary pair observed; a failed native HTTP interval can end at its raised error",
        "stage_sum_seconds": stage_sum,
        "unattributed_request_seconds": total - stage_sum if total is not None and stage_sum is not None else None,
        "unattributed_semantics": "Signed request total minus observed five-stage sum; includes hook entry gaps and request context entry, not assumed zero",
    }


def run(prepared, *, factory=start_llama, generator_factory=PlacementGenerator,
        gpu=gpu_checkpoint, rss=bounded_rss, watchdog=owned_watchdog):
    verify(prepared)
    root, plan = prepared["root"], prepared["plan"]
    output = primitives.path(OUTPUT, root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)
    pair_start, gpu_uuid, identity = time.monotonic(), None, None
    report = {"id": ID, "status": "running", "head": prepared["head"],
              "plan_sha256": prepared["plan_sha256"], "arms": [], "unexecuted_arms": [a[0] for a in ARMS],
              "source_freeze_sha256": plan["binding"]["freeze_sha256"],
              "model_sha256": GGUF_SHA256, "model_manifest_sha256": MANIFEST_SHA256,
              "runtime_commit": RUNTIME_COMMIT, "prompt_sha256": plan["prompt_sha256"],
              "input_token_ids_sha256": plan["token_ids_sha256"],
              "messages_sha256": fixture_spec()["messages_sha256"],
              "schema_sha256": fixture_spec()["schema_sha256"],
              "request_sha256": fixture_spec()["request_sha256"],
              "quality_calls": 0, "downloads": 0, "retries": 0, "warmups": 0,
              "send_hook_is_not_wire_or_completion_proof": True,
              "receipt_pass_requires_successful_terminal_cli": True}
    def publish():
        save(root, OUTPUT + "/report.json", report)
    def checkpoint(row, name, *, post_failure=False):
        nonlocal gpu_uuid
        value = gpu(gpu_uuid)
        value["post_failure_cleanup"] = post_failure
        row["gpu"][name] = value
        if not value.get("query_stopped"):
            raise CommonFailure("placement_gpu_query_ownership")
        if value.get("error") is None and value.get("uuid"):
            if gpu_uuid and value["uuid"] != gpu_uuid:
                value.update(error="gpu_identity_changed", total_mib=None, used_mib=None, free_mib=None)
            else:
                gpu_uuid = value["uuid"]
    try:
        publish()
        for arm, layers in ARMS:
            verify(prepared)
            if time.monotonic() - pair_start >= 1200:
                raise CommonFailure("placement_phase_deadline")
            row = {"id": arm, "gpu_layers_requested": layers, "gpu_layers_effective": None,
                   "flash_attention_requested": "auto_default_unchanged", "flash_attention_effective": None,
                   "status": "running", "arm_launch_attempts": 0, "dispatch_reservations": 0,
                   "dispatch_reservation_attempts": 0,
                   "http_send_attempts": 0, "parsed_native_responses": 0, "contract_valid_results": 0,
                   "input_tokens": None, "output_tokens": None, "final_retokenized_tokens": None,
                   "normalized_argv": normalized_argv(layers), "normalized_argv_sha256": sha(encoded(normalized_argv(layers))),
                   "gpu": {name: {"error": "not_reached",
                   "total_mib": None, "used_mib": None, "free_mib": None, "process_vram_mib": None,
                   "query_stopped": True} for name in CHECKPOINTS}, "artifacts": [], "cleanup": {},
                   "http_seconds": {}, "stages_seconds": {},
                   "http_interval_scope": "client transport including header hooks, excluding post-return response archival; overlaps native reported timing"}
            report["arms"].append(row)
            report["unexecuted_arms"].remove(arm)
            fatal, started, cleanup_started, request_finished = False, None, None, None
            service, generator, sequence = None, None, 0
            active_context = {"generator": None}
            def archive(kind, value, arm=arm, row=row):
                nonlocal sequence
                if sequence >= 32:
                    raise CommonFailure("placement_artifact_limit")
                metadata = write_new(root, f"{OUTPUT}/{arm}/observation-{sequence:02d}.json",
                                     {"kind": kind, "value": value})
                row["artifacts"].append({"ordinal": sequence, "kind": kind, **metadata})
                sequence += 1
            def observe(kind, value, row=row, archive=archive, context=active_context):
                if kind.endswith("_http_seconds"):
                    row["http_seconds"][kind] = value
                    if kind == "native_http_seconds":
                        row["stages_seconds"]["native_http"] = value
                    return
                if kind == "http_send_attempt":
                    if row["http_send_attempts"] or row["dispatch_reservations"] != 1:
                        raise CommonFailure("placement_send_budget")
                    row["http_send_attempts"] += 1
                    row["remaining_before_send_seconds"] = context["generator"]._remaining()
                elif kind == "native_response":
                    row["parsed_native_responses"] += 1
                    row["_native_return_at"] = time.monotonic()
                    timing = value.get("__verbose", {}).get("timings", {})
                    observed_n = value.get("__verbose", {}).get("tokens_predicted")
                    row["observed_native_output_tokens"] = observed_n if type(observed_n) is int and observed_n >= 0 else None
                    row["native_timings"] = {k: timing[k] for k in
                        ("prompt_n", "prompt_ms", "predicted_n", "predicted_ms", "cache_n")
                        if type(timing.get(k)) in (int, float) and math.isfinite(timing[k])}
                elif kind == "native_http_status":
                    row["native_http_status"] = value
                archive(kind, value)
            try:
                checkpoint(row, "before_launch")
                row["arm_launch_attempts"] = 1
                publish()  # Durable arm reservation precedes process creation.
                setup_start = time.monotonic()
                with factory(gpu_layers=layers, log_dir=output / arm / "native",
                             phase_deadline=min(pair_start + 1200, setup_start + 240), telemetry=row["cleanup"]) as service:
                    generator = generator_factory(service.url, service.token, service.manifest)
                    active_context["generator"] = generator
                    try:
                        generator.load()
                        current_identity = generator.public_metadata()
                        if identity is not None and current_identity != identity:
                            raise CommonFailure("placement_common_identity")
                        identity = current_identity
                        row["identity_sha256"] = sha(encoded(identity))
                        row["setup_seconds"] = time.monotonic() - setup_start
                        if row["setup_seconds"] > 240:
                            raise ValueError("placement_readiness_timeout")
                        started = time.monotonic()
                        generator.outer_deadline = started + 90
                        generator.observer = observe
                        with watchdog(service.process, row.setdefault("watchdog", {}), 90), \
                                rss(service.process, row.setdefault("rss", {}), started + 90), request_boundary(row):
                            stage = time.monotonic()
                            verify(prepared)
                            generator._remaining()
                            row["stages_seconds"]["timed_verify"] = time.monotonic() - stage
                            row["_after_verify_at"] = time.monotonic()
                            def before(prompt, tokens, payload, row=row, generator=generator, archive=archive):
                                stage = time.monotonic()
                                row["stages_seconds"]["template_and_input_tokenize"] = stage - row.pop("_after_verify_at")
                                verify(prepared)
                                if (prompt != prepared["private"]["prompt"] or tokens != prepared["private"]["token_ids"]
                                        or encoded(payload) != encoded(request_body(messages(), SCHEMA))):
                                    raise CommonFailure("placement_native_input_drift")
                                row["input_tokens"] = len(tokens)
                                if row["dispatch_reservations"]:
                                    raise CommonFailure("placement_send_budget")
                                row["dispatch_reservation_attempts"] = 1
                                archive("dispatch_reservation", {"prompt_sha256": plan["prompt_sha256"],
                                        "token_ids_sha256": plan["token_ids_sha256"],
                                        "request_sha256": fixture_spec()["request_sha256"]})
                                row["dispatch_reservations"] = 1
                                publish()
                                checkpoint(row, "immediately_before_send")
                                generator._remaining()
                                row["stages_seconds"]["before_send_attestation_and_reservation"] = time.monotonic() - stage
                            result = generator.generate_neutral(messages(), SCHEMA, stress=False,
                                                                before_dispatch=before, observe=observe)
                            archive("result", dataclasses.asdict(result))
                            checkpoint(row, "request_terminal")
                            row.update(input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                                final_retokenized_tokens=result.final_retokenized_tokens,
                                grammar_sha256=result.telemetry.get("grammar_sha256"), finish_reason=result.finish_reason)
                            publish()
                            generator._remaining()
                            request_finished = time.monotonic()
                            if "_native_return_at" in row:
                                row["stages_seconds"]["finalize_validation_retokenization_and_required_persistence"] = (
                                    request_finished - row["_native_return_at"])
                            row["contract_valid_results"] = 1
                            cleanup_started = request_finished
                    finally:
                        cleanup_started = cleanup_started or row.get("_request_terminal_at") or time.monotonic()
                        if started is not None:
                            row["request_seconds"] = (request_finished or cleanup_started) - started
                        generator.close()
                        cleanup_owned(service.process, service.drain, service.cleanup)
            except Exception as error:  # noqa: BLE001 - arm failures never trigger retries.
                if "error" in row and row["error"] != safe_error(error):
                    row["later_cleanup_error"] = safe_error(error)
                row.setdefault("error", safe_error(error))
                fatal = common_error(error) or row.get("_first_common_failure", False)
                cleanup_started = cleanup_started or time.monotonic()
            finally:
                terminal = time.monotonic()
                row["outer_cleanup_seconds"] = terminal - (cleanup_started or terminal)
                row["outer_cleanup_seconds"] = max(row["outer_cleanup_seconds"], row["cleanup"].get("seconds", 0))
                row.pop("_request_terminal_at", None)
                for key in ("_first_common_failure", "_native_return_at", "_after_verify_at"):
                    row.pop(key, None)
                if started is not None:
                    row.setdefault("request_seconds", terminal - started)
                    row["request_to_cleanup_seconds"] = terminal - started
                summarize_stage_timing(row)
                try:
                    if row["gpu"]["request_terminal"].get("error") == "not_reached" and started is not None:
                        checkpoint(row, "request_terminal", post_failure=True)
                    checkpoint(row, "after_cleanup", post_failure="error" in row)
                    row["outer_cleanup_seconds"] += time.monotonic() - terminal
                    if started is not None:
                        row["request_to_cleanup_seconds"] = time.monotonic() - started
                    verify(prepared)
                except Exception as later:  # noqa: BLE001 - later errors remain distinct.
                    row["finalization_error"] = safe_error(later)
                    fatal = True
                safe = (cleanup_safe(row["cleanup"]) and row["outer_cleanup_seconds"] <= 5
                    and row.get("request_to_cleanup_seconds", 0) <= 120
                    and row.get("rss", {}).get("joined", True) is True
                    and row.get("watchdog", {}).get("watchdog_joined", True) is True
                    and all(v.get("query_stopped", True) for v in row["gpu"].values()))
                row["safe_for_next_arm"] = safe and not fatal
                passed = ("error" not in row and "finalization_error" not in row and safe
                    and row["contract_valid_results"] == 1 and row.get("request_seconds", 91) <= 90
                    and row.get("watchdog", {}).get("watchdog_fired") is False
                    and row["cleanup"].get("drain", {}).get("emitted_bytes") == 0)
                row["status"] = "passed_resources_only" if passed else "failed"
                publish()
            if not row["safe_for_next_arm"]:
                break
        report["status"] = "completed_pair" if len(report["arms"]) == 2 else "stopped_pair"
    except Exception as error:  # noqa: BLE001 - preserve partial evidence and first common failure.
        report.setdefault("error", safe_error(error))
        report["status"] = "failed_closed"
    report["elapsed_seconds"] = time.monotonic() - pair_start
    report["elapsed_boundary"] = "Before terminal report write; late post-write return is checked and gets at most one failed amendment"
    if report["elapsed_seconds"] > 1200:
        report["status"] = "failed_closed"
        report.setdefault("error", {"code": "placement_phase_deadline", "type": "ValueError"})
    rows = report["arms"]
    report["pair_execution_completed"] = len(rows) == 2 and report["status"] == "completed_pair"
    report["resources_all_passed"] = (report["pair_execution_completed"]
                                       and all(r["status"] == "passed_resources_only" for r in rows))
    report["observed_latency_ratio_24_over_28"] = None
    report["memory_comparison_available"] = (len(rows) == 2 and all(
        value.get("error") is None and value.get("uuid") == gpu_uuid
        and all(value.get(k) is not None for k in ("total_mib", "used_mib", "free_mib"))
        for row in rows for value in row["gpu"].values()))
    if (len(rows) == 2 and all(r["status"] == "passed_resources_only" for r in rows)
            and all(rows[0].get(k) == rows[1].get(k) for k in
                    ("input_tokens", "output_tokens", "identity_sha256", "grammar_sha256"))
            and rows[1]["request_seconds"] > 0):
        report["observed_latency_ratio_24_over_28"] = rows[0]["request_seconds"] / rows[1]["request_seconds"]
    try:
        publish()
    except Exception as later:  # noqa: BLE001 - disk receipts alone are not terminal success.
        report["persistence_error"] = safe_error(later)
        report["status"] = "failed_closed"
        report["resources_all_passed"] = False
    if time.monotonic() - pair_start > 1200:
        report["status"] = "failed_closed"
        report["resources_all_passed"] = False
        report.setdefault("error", {"code": "placement_phase_deadline", "type": "ValueError"})
        try:
            publish()
        except Exception as later:  # noqa: BLE001 - at most one failed amendment.
            report["persistence_error"] = safe_error(later)
    return report


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv not in (["register"], ["run"]):
            raise ValueError("placement_cli_arguments")
        result = register() if argv == ["register"] else run(check())
        ok = result["status"] in {"passed", "completed_pair"} and "error" not in result and "persistence_error" not in result
        print(json.dumps({"status": result["status"], "error": result.get("error"),
                          "persistence_error": result.get("persistence_error"), "terminal_success": ok,
                          "pair_execution_completed": result.get("pair_execution_completed", False),
                          "resources_all_passed": result.get("resources_all_passed", False),
                          "arms": [{"id": r["id"], "status": r["status"]} for r in result.get("arms", [])]}))
        return 0 if ok else 1
    except Exception as error:  # noqa: BLE001 - no paths, credentials or diagnostic text.
        print(json.dumps({"status": "failed_closed", "error": safe_error(error), "terminal_success": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
