"""Explicit offline candidate pilot, never a service or an automatic model retry.

Use only a separately reviewed registration and explicit once digest. Import and
--help never prepare assets, tokenize, launch a process or read private inputs.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import secrets
import subprocess
import time
from contextlib import ExitStack, contextmanager, nullcontext
from pathlib import Path

from doctrail.inference import WorkerError
from doctrail.meeting_contract import grounded_answer_refs, meeting_units, strict_json
from doctrail.meeting_gguf import GGUFGenerator, _integer
from doctrail.meeting_grounded_summary import (
    REVIEW_GRAMMAR,
    parse_draft,
    parse_review,
    source_payload,
    summary_messages,
)
from doctrail.meeting_worker import ANSWER_PROMPT, messages, worker_lease
from scripts.prepare_meeting_gguf import prepare
from scripts.probe_meeting_summary_mode import (
    Evidence,
    ResourceGuard,
    bound_path,
    check_ref,
    cleanup_owner,
    encoded,
    error_record,
    owned_create_time,
    sha,
)
from scripts.probe_meeting_summary_mode import (
    validate_input as validate_summary_input,
)
from scripts.serve_meeting_thinking_compat import CompatService, DiscardDrain
from scripts.serve_models import unused_port, wait_ready

ROOT = Path(__file__).resolve().parents[1]
ID = "local-candidate-development-v1"
PROFILE = "data/models/meetings-generation-ministral3-v1.json"
PROFILE_SHA = "2b4d19c14af2697188d6a07a41b1ea971c1eaefec68fbc9beb035d74906f1de7"
MODEL_SHA = "e23dd88b0e0951d3f5784d6d4092210cda2b006b251f33b226b283a6c9d1f6bb"
LIMITS = {"input_tokens": 4096, "summary_tokens": 768, "review_tokens": 128,
          "qa_tokens": 256, "summary_seconds": 120, "qa_seconds": 60,
          "startup_seconds": 120, "active_seconds": 900, "cleanup_seconds": 5,
          "whole_seconds": 1025, "completion_calls": 12, "generation_calls": 8,
          "requested_tokens": 4608, "startup_available_bytes": 10 * 1024**3,
          "active_available_bytes": 2 * 1024**3, "native_rss_bytes": 8 * 1024**3}
CONTENT_ERRORS = frozenset({"generation_invalid_json", "generation_invalid_schema", "generation_invalid_evidence",
    "generation_summary_insufficient", "generation_summary_review_rejected",
    "generation_language_mismatch", "generation_input_limit", "generation_partition_limit",
    "generation_output_limit"})
# Filled with an explicit reviewed import closure, not runtime repository discovery.
CODE_FILES = (
    'pyproject.toml',
    'scripts/backup_db.py',
    'scripts/benchmark_api.py',
    'scripts/check_meeting_review_token_budget.py',
    'scripts/evaluate_dataset.py',
    'scripts/prepare_corpus.py',
    'scripts/prepare_meeting_budget_inputs.py',
    'scripts/prepare_meeting_gguf.py',
    'scripts/prepare_meeting_plaintext_source_inventory.py',
    'scripts/prepare_meeting_requirements_inputs.py',
    'scripts/prepare_meeting_source_inventory.py',
    'scripts/prepare_meeting_thinking_inputs.py',
    'scripts/probe_meeting_answer_review.py',
    'scripts/probe_meeting_blocks_resources.py',
    'scripts/probe_meeting_gpu_placement.py',
    'scripts/probe_meeting_local_candidate.py',
    'scripts/probe_meeting_summary_mode.py',
    'scripts/probe_meeting_thinking_resources.py',
    'scripts/profile_meeting_host_proof.py',
    'scripts/question_dataset.py',
    'scripts/serve_meeting_gpu_placement.py',
    'scripts/serve_meeting_thinking.py',
    'scripts/serve_meeting_thinking_compat.py',
    'scripts/serve_meetings.py',
    'scripts/serve_meetings_gguf.py',
    'scripts/serve_models.py',
    'scripts/validate_splits.py',
    'scripts/verify_java_service.py',
    'src/doctrail/__init__.py',
    'src/doctrail/app.py',
    'src/doctrail/db.py',
    'src/doctrail/generation_runtime.py',
    'src/doctrail/generation_runtime_v2.py',
    'src/doctrail/inference.py',
    'src/doctrail/ingest.py',
    'src/doctrail/meeting_analysis_batch.py',
    'src/doctrail/meeting_answer_blocks.py',
    'src/doctrail/meeting_answer_grammar.py',
    'src/doctrail/meeting_answer_lines_bounded.py',
    'src/doctrail/meeting_answer_requirements.py',
    'src/doctrail/meeting_answer_review.py',
    'src/doctrail/meeting_answer_spans.py',
    'src/doctrail/meeting_answer_thinking.py',
    'src/doctrail/meeting_answer_v2.py',
    'src/doctrail/meeting_comparison_review.py',
    'src/doctrail/meeting_contract.py',
    'src/doctrail/meeting_extraction_coverage.py',
    'src/doctrail/meeting_gguf.py',
    'src/doctrail/meeting_grounded_summary.py',
    'src/doctrail/meeting_input_budget.py',
    'src/doctrail/meeting_qwen35.py',
    'src/doctrail/meeting_requirements_review.py',
    'src/doctrail/meeting_runtime.py',
    'src/doctrail/meeting_thinking_review.py',
    'src/doctrail/meeting_thinking_transport.py',
    'src/doctrail/meeting_worker.py',
    'src/doctrail/model_retrieval.py',
    'src/doctrail/retrieval.py',
    'tests/test_probe_meeting_local_candidate.py',
    'uv.lock',
)


class CandidateFailure(RuntimeError):
    def __init__(self, code):
        self.code = "local_candidate_" + code
        super().__init__(self.code)


def require(value, code):
    if not value:
        raise CandidateFailure(code)


def remaining(clock, deadline):
    value = deadline - clock()
    require(value > 0, "deadline")
    return value


def validate_input(data):
    require(isinstance(data, dict) and set(data) == {"schema_version", "diagnostic", "documents"}
            and type(data["schema_version"]) is int and data["schema_version"] == 1
            and data["diagnostic"] == ID and isinstance(data["documents"], list)
            and len(data["documents"]) == 4, "input_contract")
    projected, questions = [], set()
    for row in data["documents"]:
        require(isinstance(row, dict) and set(row) == {"id", "document_id", "revision", "title",
                "content", "content_sha256", "question"}, "document_contract")
        question = row["question"]
        require(isinstance(question, dict) and set(question) == {"id", "text"}
                and isinstance(question["id"], str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", question["id"])
                and question["id"] not in questions and isinstance(question["text"], str)
                and question["text"].strip(), "question_contract")
        question["text"].encode("utf-8")
        questions.add(question["id"])
        projected.append({k: v for k, v in row.items() if k != "question"})
    validate_summary_input({"schema_version": 1, "diagnostic": "summary-mode-development-v1",
                            "documents": projected})
    return copy.deepcopy(data["documents"])


class CandidateAdapter(GGUFGenerator):
    """Embedded template, existing bounded HTTP/completion validation, no Qwen suffix."""
    def __init__(self, *args, clock=time.monotonic, observe=None, resource_check=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.clock, self.observe = clock, observe or (lambda *args: None)
        self.resource_check = resource_check or (lambda: None)
        self.counts = {"summary": 0, "review": 0, "qa": 0, "requested_tokens": 0, "http": 0}
        self.used, self.halted, self.stage = set(), False, None

    def _remaining(self, deadline=None):
        require(not self.halted, "halted")
        deadline = self._deadline if deadline is None else deadline
        require(deadline is not None, "unbounded_request")
        self.resource_check()
        return remaining(self.clock, deadline)

    def _request(self, method, path, payload=None, deadline=None):
        try:
            self._remaining(deadline)
            if path == "/completion":
                require(self.stage in ("summary", "review", "qa"), "completion_stage")
                budget = LIMITS[self.stage + "_tokens"]
                require(self.counts[self.stage] < 4 and payload.get("n_predict") == budget
                        and sum(self.counts[k] for k in ("summary", "review", "qa")) < 12
                        and self.counts["requested_tokens"] + budget <= 4608, "completion_cap")
                # Charge once before dispatch, including a request whose response is lost.
                self.counts[self.stage] += 1
                self.counts["requested_tokens"] += budget
            self.counts["http"] += 1
            self.observe("request", {"stage": self.stage, "path": path, "body": payload})
            response = super()._request(method, path, payload, deadline)
            self.observe("response", {"stage": self.stage, "path": path, "body": response})
            if path == "/completion":
                tokens, count = response.get("tokens"), response.get("tokens_predicted")
                require(isinstance(tokens, list) and _integer(count, 1) and len(tokens) == count
                        and all(_integer(t) for t in tokens)
                        and type(response.get("timings", {}).get("predicted_n")) is int
                        and response["timings"]["predicted_n"] == count,
                        "response_token_integrity")
            self._remaining(deadline)
            return response
        except Exception as error:
            if getattr(error, "code", None) not in CONTENT_ERRORS:
                self.halted = True
            raise

    def _prepare(self, request_messages, deadline=None):
        prompt = self._request("POST", "/apply-template", {"messages": request_messages}, deadline).get("prompt")
        require(isinstance(prompt, str) and bool(prompt), "template_protocol")
        tokens = self._request("POST", "/tokenize", {"content": prompt, "add_special": False,
            "parse_special": True, "with_pieces": False}, deadline).get("tokens")
        require(isinstance(tokens, list) and bool(tokens) and all(_integer(t) for t in tokens), "token_protocol")
        return tokens

    def load(self):
        require(sha(self.manifest_path.read_bytes()) == PROFILE_SHA, "profile_identity")
        super().load()
        require(self._alias == MODEL_SHA and self._metadata["runtime"]["context_tokens"] == 6144,
                "runtime_identity")
        self._remaining()  # include the reused loader's full artifact hash in startup time
        return self

    def complete(self, document_id, stage, request_messages, deadline):
        require(stage in ("summary", "review", "qa") and (document_id, stage) not in self.used,
                "stage_repeated")
        self.used.add((document_id, stage))
        self.stage = stage
        self.begin_request(deadline)
        try:
            result = self._complete(request_messages, deadline, LIMITS[stage + "_tokens"],
                                    REVIEW_GRAMMAR if stage == "review" else "")
            self._remaining(deadline)
            if result.finish_reason != "eos":
                raise WorkerError("generation_output_limit", 502)
            return result
        except Exception as error:
            if getattr(error, "code", None) not in CONTENT_ERRORS:
                self.halted = True
            raise
        finally:
            self.end_request()
            self.stage = None


def diagnose(documents, adapter, *, active_deadline, emit, clock=time.monotonic, guard=None, checkpoint=None):
    report = {"diagnostic": ID, "documents": [{"id": d["id"], "question_id": d["question"]["id"],
              **{k: {"status": "unexecuted"} for k in ("summary", "review", "qa")}} for d in documents],
              "first_failure": None, "stop_reason": None, "summary_denominator": 4, "qa_denominator": 4}

    def invoke(document, row, stage, request_messages, deadline, parse):
        metrics, stage_started = {}, clock()
        try:
            remaining(clock, deadline)
            with guard.arm(deadline, metrics) if guard else nullcontext():
                if checkpoint:
                    checkpoint()
                result = adapter.complete(document["id"], stage, request_messages, deadline)
                parsed = parse(result.text)
                if checkpoint:
                    checkpoint()
                remaining(clock, deadline)
                emit(stage, {"document": document["id"], "parsed": parsed,
                             "input_tokens": result.input_tokens, "output_tokens": result.output_tokens})
            row[stage] = {"status": "valid", "input_tokens": result.input_tokens,
                          "output_tokens": result.output_tokens, "resources": metrics,
                          "elapsed_seconds": clock() - stage_started}
            if stage == "qa":
                row[stage]["answer_status"] = parsed["status"]
            return parsed
        except Exception as error:
            record = {"document": document["id"], "stage": stage, **error_record(error)}
            rejection = getattr(error, "code", None) in CONTENT_ERRORS
            row[stage] = {"status": "rejected" if rejection else "failed", "error": record, "resources": metrics,
                          "elapsed_seconds": clock() - stage_started}
            report["first_failure"] = report["first_failure"] or record
            emit("failure", record)
            if not rejection:
                adapter.halted = True
                report["stop_reason"] = record
                raise
            return None

    for document, row in zip(documents, report["documents"], strict=True):
        try:
            remaining(clock, active_deadline)
            units = meeting_units(document["content"])
            source = source_payload(document["title"], document["content"], units)
            emit("source", {"document": document["id"], "source": source, "question": document["question"]})
            summary_end = min(active_deadline, clock() + 120)
            claims = invoke(document, row, "summary", summary_messages(source), summary_end,
                            lambda raw, units=units, content=document["content"]: parse_draft(raw, units, content))
            if claims is not None:
                invoke(document, row, "review", summary_messages(source, claims), summary_end,
                       lambda raw, claims=claims: parse_review(raw, len(claims)))
            else:
                row["review"] = {"status": "not_applicable", "reason": "no_valid_draft"}
            mapping = {index: {**unit, "chunk_id": f"{document['document_id']}:{document['revision']}:{index}"}
                       for index, unit in enumerate(units)}
            qa_messages = messages(ANSWER_PROMPT, {**source, "question": document["question"]["text"]})
            invoke(document, row, "qa", qa_messages, min(active_deadline, clock() + 60),
                   lambda raw, mapping=mapping: grounded_answer_refs(raw, mapping))
        except Exception as error:  # noqa: BLE001 - retain safe failure, stop or rethrow
            record = {"document": document["id"], "stage": "source_or_execution", **error_record(error)}
            report["first_failure"] = report["first_failure"] or record
            if getattr(error, "code", None) in CONTENT_ERRORS:
                for stage in ("summary", "qa"):
                    if row[stage]["status"] == "unexecuted":
                        row[stage] = {"status": "rejected", "error": record}
                row["review"] = {"status": "not_applicable", "reason": "source_rejected"}
                emit("failure", record)
                continue
            adapter.halted = True
            report["stop_reason"] = report["stop_reason"] or record
            break
    report["counts"] = dict(adapter.counts)
    report["operational_complete"] = report["stop_reason"] is None
    report["mechanically_complete"] = report["operational_complete"] and all(
        all(row[s]["status"] == "valid" for s in ("summary", "review", "qa"))
        and row["qa"].get("answer_status") == "answered" for row in report["documents"])
    report["status"] = ("stopped" if not report["operational_complete"] else
                        "completed" if report["mechanically_complete"] else "completed_with_rejections")
    return report


def command(server, model, port):
    return [str(server), "--model", str(model), "--host", "127.0.0.1", "--port", str(port),
            "--alias", MODEL_SHA, "--ctx-size", "6144", "--parallel", "1", "--n-gpu-layers", "99",
            "--cache-type-k", "f16", "--cache-type-v", "f16", "--fit", "off", "--jinja",
            "--reasoning", "off", "--no-warmup", "--cache-ram", "0", "--no-context-shift",
            "--no-webui", "--log-disable"]


@contextmanager
def launch(profile, model_root, deadline, metrics, *, root=ROOT, clock=time.monotonic):
    """Small profile seam; leases, readiness, drain and cleanup are shared primitives."""
    import psutil
    with ExitStack() as stack:
        for name in ("meeting-generation.gpu.lock", "meeting-generation.worker.lock", "meeting-llama.lease"):
            stack.enter_context(worker_lease(root / ".local" / name))
        receipt = prepare(profile, model_root, allow_download=False)
        remaining(clock, deadline)
        require(psutil.virtual_memory().available >= LIMITS["startup_available_bytes"], "startup_ram")
        server, model = model_root / receipt["server_path"], model_root / receipt["model"]["path"]
        port, token = unused_port(), secrets.token_urlsafe(48)
        environment = {k: v for k, v in os.environ.items() if not k.startswith("LLAMA_ARG_")}
        environment.update(LLAMA_API_KEY=token, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        process, drain = None, None
        try:
            metrics["process_creation_attempted"] = True
            process = subprocess.Popen(command(server, model, port), cwd=server.parent,
                env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            metrics.update(owned_pid=process.pid, owned_create_time=owned_create_time(process))
            drain = DiscardDrain(process.stdout)
            drain.start()
            guard = ResourceGuard(process, clock=clock, expected_created=metrics["owned_create_time"])
            with guard.arm(deadline, metrics.setdefault("startup_resources", {})):
                wait_ready(process, f"http://127.0.0.1:{port}/health",
                           headers={"Authorization": "Bearer " + token}, timeout=remaining(clock, deadline))
                remaining(clock, deadline)
            yield CompatService(process, f"http://127.0.0.1:{port}", token, profile, receipt, metrics, drain)
        finally:
            cleanup_owner(process, drain, metrics, clock=clock)


def verify_registration(path, expected_sha, root=ROOT):
    require(re.fullmatch(r"[a-f0-9]{64}", expected_sha) and sha(path.read_bytes()) == expected_sha,
            "registration_identity")
    spec = strict_json(path.read_text(encoding="utf-8"))
    require(isinstance(spec, dict) and set(spec) == {"schema_version", "diagnostic", "prepared", "limits",
            "profile", "input", "criteria_locks", "code", "assets", "model_root", "output_dir", "order"}
            and type(spec["schema_version"]) is int and spec["schema_version"] == 1
            and spec["diagnostic"] == ID and spec["prepared"] is True
            and encoded(spec["limits"]) == encoded(LIMITS), "registration_contract")
    require(spec["profile"]["file"] == PROFILE and spec["profile"]["sha256"] == PROFILE_SHA,
            "profile_binding")
    require(isinstance(spec["criteria_locks"], dict) and set(spec["criteria_locks"]) == {"summary", "qa"},
            "criteria_binding")
    require(isinstance(spec["code"], list) and {r["file"] for r in spec["code"]} == set(CODE_FILES)
            and len(spec["code"]) == len(CODE_FILES), "code_binding")
    model_root = bound_path(spec["model_root"], root)
    require(model_root.is_relative_to(root / "models"), "model_root")
    receipt_path = model_root / "setup-receipt.json"
    require(any(r["file"] == receipt_path.relative_to(root).as_posix() for r in spec["assets"]), "asset_receipt")
    for reference in [spec["profile"], spec["input"], *spec["criteria_locks"].values(), *spec["code"], *spec["assets"]]:
        check_ref(reference, root)
    receipt = strict_json(receipt_path.read_text(encoding="utf-8"))
    profile = strict_json((root / PROFILE).read_text(encoding="utf-8"))
    asset_names = {"setup-receipt.json", receipt["model"]["path"],
                   *("runtime/" + name for name in receipt["runtime_files"]), *receipt["licenses"],
                   *("downloads/" + a["filename"] for a in profile["llama"]["assets"])}
    require({r["file"] for r in spec["assets"]} == {
            (model_root / name).relative_to(root).as_posix() for name in asset_names}
            and len(spec["assets"]) == len(asset_names), "asset_binding")
    documents = validate_input(strict_json((root / spec["input"]["file"]).read_text(encoding="utf-8")))
    require(spec["order"] == [d["id"] for d in documents], "source_order")
    output = bound_path(spec["output_dir"], root)
    require(output.is_relative_to(root / ".local") and output.name == ID and not output.exists(), "output_scope")
    return spec, documents, output


def execute(path, expected_sha, *, root=ROOT, clock=time.monotonic):
    started = clock()
    spec, documents, output = verify_registration(path, expected_sha, root)
    output.mkdir(parents=True, exist_ok=False)  # reservation survives every subsequent failure
    private = output / "private"
    private.mkdir()
    emit, metrics, adapter = Evidence(private), {}, None
    gpu_samples = []
    def checkpoint():
        from scripts.probe_meeting_gpu_placement import gpu_checkpoint
        sample = gpu_checkpoint(expected_uuid=gpu_samples[0]["uuid"] if gpu_samples else None)
        require(sample["query_stopped"] and not sample.get("error"), "gpu_observation")
        gpu_samples.append(sample)
    report = {"diagnostic": ID, "status": "stopped", "operational_complete": False,
              "mechanically_complete": False, "first_failure": None, "stop_reason": None,
              "documents": [{"id": d["id"], **{s: {"status": "unexecuted"}
                  for s in ("summary", "review", "qa")}} for d in documents]}
    try:
        remaining(clock, started + 120)
        with launch(root / PROFILE, root / spec["model_root"], started + 120, metrics, root=root, clock=clock) as service:
            guard = ResourceGuard(service.process, clock=clock, expected_created=metrics["owned_create_time"])
            adapter = CandidateAdapter(service.url, service.token, root / PROFILE, clock=clock,
                                       observe=emit, resource_check=guard.check)
            adapter.begin_request(started + 120)
            try:
                checkpoint()
                adapter.load()
                active_started = clock()
                report = diagnose(documents, adapter, active_deadline=min(started + 1020, active_started + 900),
                                  emit=emit, clock=clock, guard=guard, checkpoint=checkpoint)
            except Exception as error:  # noqa: BLE001 - preserve body cause before client shutdown
                record = error_record(error)
                report["first_failure"] = report["first_failure"] or record
                report["stop_reason"] = report["stop_reason"] or record
                report.update(status="stopped", operational_complete=False, mechanically_complete=False)
            finally:
                try:
                    adapter.close()
                except Exception as error:  # noqa: BLE001 - close failure is secondary to first cause
                    record = error_record(error)
                    report.setdefault("secondary_failures", []).append({"stage": "client_close", **record})
                    report["first_failure"] = report["first_failure"] or record
                    report["stop_reason"] = report["stop_reason"] or record
                    report.update(status="stopped", operational_complete=False, mechanically_complete=False)
    except Exception as error:  # noqa: BLE001 - retain safe failure, stop or rethrow
        record = error_record(error)
        report["first_failure"] = report["first_failure"] or record
        report["stop_reason"] = report["stop_reason"] or record
        report.update(status="stopped", operational_complete=False, mechanically_complete=False)
    finally:
        report.update(cleanup=metrics, registration_sha256=expected_sha, limits=LIMITS,
                      retries=0, AI_quality=False, effective_offload_layers=None,
                      gpu_layers_requested=99, gpu_samples=gpu_samples,
                      gpu_scope="device_wide_samples_not_process_peak_or_exclusive_ownership",
                      requires_parent_fresh_external_process_GPU_readiness=True,
                      requires_terminal_receipt=True, hard_blocking_io_preemption_proven=False)
        try:
            require(not metrics.get("process_creation_attempted") or metrics.get("within_budget") is True, "cleanup")
            require(sha(path.read_bytes()) == expected_sha, "registration_changed")
            for reference in [spec["profile"], spec["input"], *spec["criteria_locks"].values(), *spec["code"], *spec["assets"]]:
                check_ref(reference, root)
            remaining(clock, started + 1025)
            report["bindings_unchanged"] = True
        except Exception as error:  # noqa: BLE001 - retain safe failure, stop or rethrow
            record = error_record(error)
            report["first_failure"] = report["first_failure"] or record
            report["stop_reason"] = report["stop_reason"] or record
            report.update(status="stopped", operational_complete=False, mechanically_complete=False)
        samples = list(metrics.get("startup_resources", {}).get("samples", []))
        for row in report.get("documents", []):
            for stage in ("summary", "review", "qa"):
                samples.extend(row.get(stage, {}).get("resources", {}).get("samples", []))
        report["sampled_max_native_rss_bytes"] = max((x["rss"] for x in samples), default=None)
        report["sampled_min_available_ram_bytes"] = min((x["available"] for x in samples), default=None)
        report["sampled_max_device_vram_mib"] = max(
            (x["used_mib"] for x in gpu_samples if x.get("used_mib") is not None), default=None)
        report["elapsed_seconds"] = clock() - started
        if adapter:
            report["counts"] = dict(adapter.counts)
        emit.seal(report)
        with (output / "report.json").open("xb") as stream:
            stream.write(encoded(report) + b"\n")
        if clock() - started > 1025:
            report.update(status="stopped", operational_complete=False, mechanically_complete=False)
            report["stop_reason"] = report["stop_reason"] or {"code": "local_candidate_whole_deadline"}
        terminal = {"status": report["status"], "mechanically_complete": report["mechanically_complete"],
                    "operational_complete": report["operational_complete"], "stop_reason": report["stop_reason"],
                    "registration_sha256": expected_sha, "report_sha256": sha((output / "report.json").read_bytes()),
                    "elapsed_seconds_after_report_write": clock() - started}
        with (output / "terminal.json").open("xb") as stream:
            stream.write(encoded(terminal) + b"\n")
        if clock() - started > 1025:
            report.update(status="stopped", operational_complete=False, mechanically_complete=False)
            with (output / "late-invalidation.json").open("xb") as stream:
                stream.write(encoded({"code": "local_candidate_whole_deadline", "elapsed_seconds": clock() - started}))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registration", required=True, type=Path)
    parser.add_argument("--execute-once-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        report = execute(args.registration, args.execute_once_sha256)
    except Exception as error:  # noqa: BLE001 - retain safe failure, stop or rethrow
        print(json.dumps({"status": "unbound_rejection", "error": error_record(error)}))
        return 1
    print(json.dumps({k: report.get(k) for k in ("status", "mechanically_complete", "operational_complete",
          "first_failure", "stop_reason", "counts", "registration_sha256", "elapsed_seconds")}))
    return 0 if report["mechanically_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
