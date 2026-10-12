"""Guarded M4 E5 feasibility probe and one bounded run. CUDA only; no fallback."""

from __future__ import annotations

import argparse
import contextlib
import gc
import importlib
import json
import math
import os
import random
import time
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

from doctrail.model_retrieval import file_sha256, masked_mean_pool, verify_snapshot
from doctrail.training import (
    UpdateProgress,
    constant_learning_rate,
    optimizer_batches,
    per_query_contrastive_loss,
)
from scripts import prepare_training as pilot
from scripts import prepare_training_ready as ready

ROOT = pilot.ROOT
REQUIRED_SOURCES = {"scripts/train_embedding.py", "src/doctrail/training.py",
                    "src/doctrail/model_retrieval.py"}
EVALUATION_CONTRACT = {
    "execution": "deferred_separate_frozen_evaluation",
    "calibration_corpus": "all_original_train_documents_with_frozen_chunks",
    "main_dev": "not_accessed_by_training_command", "test": "locked", "service_adoption": False,
}
READINESS_ARGUMENTS = {"readiness_plan", "pilot_dir", "drafts", "author_packs",
                       "positive_reviews", "negative_reviews", "review_pack_dir",
                       "token_receipt", "e5_snapshot"}
READINESS_MODULES = {"m4-readiness-plan-v1": "scripts.prepare_training_ready",
                     "m4-readiness-plan-v2": "scripts.prepare_training_ready_v2"}


def readiness_module(execution: dict):
    name = READINESS_MODULES.get(execution.get("readiness_contract"))
    if name is None:
        raise ValueError("unsupported_readiness_contract")
    return importlib.import_module(name)


def verified_data(execution: dict, manifest_path: Path) -> tuple[dict, dict]:
    """Recompute all readiness gates, not just trust a serialized data_ready flag."""
    if not ready.relative(manifest_path).startswith("data/training/"):
        raise ValueError("training_manifest_path_outside_train_artifacts")
    raw = manifest_path.read_bytes()
    if pilot.sha256(raw) != execution["ready_manifest_sha256"]:
        raise ValueError("training_manifest_checksum_mismatch")
    settings = execution["readiness_arguments"]
    expected_arguments = READINESS_ARGUMENTS | (
        {"v1_manifest", "v1_token_receipt"}
        if execution.get("readiness_contract") == "m4-readiness-plan-v2" else set())
    if set(settings) != expected_arguments:
        raise ValueError("readiness_arguments_missing_or_extra")
    kwargs = {key: [ROOT / item for item in value] if isinstance(value, list)
              else ROOT / value for key, value in settings.items()}
    for value in kwargs.values():
        for path in value if isinstance(value, list) else [value]:
            name = ready.relative(path)
            if not name.startswith(("data/training/", ".local/", "models/")):
                raise ValueError("readiness_input_outside_train_artifacts")
    args = SimpleNamespace(command="replay", output=manifest_path, **kwargs)
    context = readiness_module(execution).load_ready_data(args)
    expected = context["manifest"]
    if len(expected["triplets"]) != 64 or len(expected["calibration"]) != 16:
        raise ValueError("frozen_training_denominator_changed")
    context["readiness_contract"] = execution["readiness_contract"]
    if execution["readiness_contract"] == "m4-readiness-plan-v1":
        receipt = json.loads(args.token_receipt.read_bytes())
        context["negative_input_ids_sha256"] = {
            row["chunk_id"]: row["input_ids_sha256"] for row in receipt["candidates"]}
    return expected, context


def validate_execution(execution: dict) -> dict:
    if execution.get("schema_version") != 1 or execution.get("execution_id") != "m4-e5-execution-v1":
        raise ValueError("unsupported_training_execution_plan")
    plan_path = ROOT / "data/training/m4-plan-v1.json"
    if file_sha256(plan_path) != execution["parent_plan_sha256"]:
        raise ValueError("original_training_plan_changed")
    plan = json.loads(plan_path.read_bytes())
    module = READINESS_MODULES.get(execution.get("readiness_contract"), "")
    required_sources = REQUIRED_SOURCES | {module.replace(".", "/") + ".py"}
    if (execution.get("evaluation_contract") != EVALUATION_CONTRACT
            or execution.get("readiness_contract") not in READINESS_MODULES
            or not required_sources <= set(execution.get("source_sha256_lf", {}))):
        raise ValueError("missing_frozen_source_or_evaluation_contract")
    if file_sha256(ROOT / "uv.lock") != plan["training_proposal"]["dependency_lock_sha256"]:
        raise ValueError("dependency_lock_changed")
    for name, expected in execution["source_sha256_lf"].items():
        if not name.startswith(("scripts/", "src/", "tests/")) or not name.endswith(".py"):
            raise ValueError("execution_source_path_not_python_source")
        path = ROOT / name
        ready.relative(path)
        if pilot.sha256(path.read_bytes().replace(b"\r\n", b"\n")) != expected:
            raise ValueError("training_source_changed")
    details = execution["implementation"]
    required = {"scheduler": "linear_warmup_then_constant", "adamw_foreach": False,
                "probe_query_count": 8, "probe_order": "max_input_tokens_desc_then_question_id",
                "shuffle": "sorted_question_ids_then_python_random_seed_plus_epoch",
                "accumulation_weight": "microbatch_query_count_divided_by_optimizer_group_query_count",
                "stop_on_skipped_update": True, "save_checkpoint": "terminal_only"}
    if any(details.get(key) != value for key, value in required.items()):
        raise ValueError("unsupported_training_implementation_contract")
    proposal = plan["training_proposal"]
    if file_sha256(ROOT / proposal["model_manifest_path"]) != proposal["model_manifest_sha256"]:
        raise ValueError("model_manifest_changed")
    return plan["training_proposal"]


def seed_runtime(torch, seed: int) -> None:
    import numpy as np

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True)


def input_texts(batch: list[dict], questions: dict, chunks: dict) -> list[str]:
    query_texts = ["query: " + questions[row["question_id"]]["question"] for row in batch]
    passages = ["passage: " + chunks[ref["chunk_id"]]["text"]
                for row in batch for ref in [row["positive"], *row["negatives"]]]
    return query_texts + passages


def verify_negative_input(reference: dict, input_ids: list[int], attention_mask: list[int],
                           context: dict) -> None:
    """Remove only trailing masked padding, then bind the exact actual model input."""
    if (len(input_ids) != len(attention_mask) or not input_ids or len(input_ids) > 512
            or any(type(token) is not int or token < 0 for token in input_ids)
            or any(type(mask) is not int or mask not in (0, 1) for mask in attention_mask)):
        raise ValueError("invalid_negative_model_input")
    length = sum(attention_mask)
    if length < 1 or attention_mask != [1] * length + [0] * (len(attention_mask) - length):
        raise ValueError("only_right_masked_padding_allowed")
    ids, mask = input_ids[:length], attention_mask[:length]
    identifier = reference["chunk_id"]
    contract = context.get("readiness_contract")
    if contract == "m4-readiness-plan-v2":
        expected = context.get("negative_model_input_sha256", {}).get(identifier)
        actual = pilot.fingerprint({"input_ids": ids, "attention_mask": mask})
    elif contract == "m4-readiness-plan-v1":
        expected = context.get("negative_input_ids_sha256", {}).get(identifier)
        actual = pilot.fingerprint(ids)
    else:
        raise ValueError("unsupported_readiness_contract")
    if expected is None or expected != actual:
        raise ValueError("negative_actual_model_input_checksum_mismatch")


def verify_all_negative_inputs(tokenizer, records: list[dict], context: dict) -> None:
    """Fresh tokenization before model loading/any probe or training forward."""
    for row in records:
        for reference in row["negatives"]:
            text = context["chunks"][reference["chunk_id"]]["text"]
            encoded = tokenizer("passage: " + text, max_length=512, truncation=True, padding=False,
                                return_attention_mask=True)
            verify_negative_input(reference, encoded["input_ids"], encoded["attention_mask"], context)


def verify_batch_negative_inputs(encoded, batch: list[dict], context: dict) -> None:
    """Repeat the binding check on actual padded tensors immediately before forward."""
    ids, masks = encoded["input_ids"].tolist(), encoded["attention_mask"].tolist()
    if len(ids) != len(batch) * 4 or len(masks) != len(ids):
        raise ValueError("invalid_explicit_negative_batch_layout")
    for index, row in enumerate(batch):
        for negative_index, reference in enumerate(row["negatives"]):
            offset = len(batch) + index * 3 + 1 + negative_index
            verify_negative_input(reference, ids[offset], masks[offset], context)


def probe_group(records: list[dict], questions: dict, chunks: dict, tokenizer) -> dict:
    ranked = []
    for row in records:
        lengths = [len(ids) for ids in tokenizer(input_texts([row], questions, chunks),
                                                truncation=False, padding=False)["input_ids"]]
        ranked.append((max(min(length, 512) for length in lengths), row["question_id"], row, lengths))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = ranked[:8]
    return {"epoch": 0, "optimizer_step": 1, "question_count": len(selected),
            "microbatches": [[entry[2] for entry in selected[i:i + 2]]
                             for i in range(0, len(selected), 2)],
            "probe_selection": [{"question_id": entry[1], "raw_input_token_lengths": entry[3]}
                                for entry in selected]}


def run_updates(model, tokenizer, torch, records: list[dict], context: dict, recipe: dict,
                *, probe: bool, progress: UpdateProgress | None = None) -> dict:
    import psutil

    progress = progress or UpdateProgress({})
    state = progress.state
    questions = {row["id"]: row for row in context["questions"]}
    chunks = context["chunks"]
    model.train()
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    optimizer = torch.optim.AdamW(model.parameters(), lr=recipe["learning_rate"],
                                 weight_decay=recipe["weight_decay"], foreach=False)
    # GradScaler can skip optimizer.step. Hooks record only actual optimizer calls.
    optimizer.register_step_pre_hook(lambda *_: progress.entered())
    optimizer.register_step_post_hook(lambda *_: progress.completed())
    scaler = torch.amp.GradScaler("cuda")
    if any(parameter.dtype != torch.float32 or not parameter.requires_grad
           for parameter in model.parameters()):
        raise ValueError("full_weight_fp32_training_required")
    schedule = ([probe_group(records, questions, chunks, tokenizer)] if probe else list(
        optimizer_batches(records, seed=recipe["seed"], epochs=recipe["epochs"],
                          microbatch=recipe["microbatch_queries"],
                          accumulation=recipe["gradient_accumulation_steps"],
                          max_steps=recipe["max_optimizer_steps"])))
    torch.cuda.synchronize()
    started = time.perf_counter()
    process = psutil.Process()
    state.update({"trainable_parameters": sum(p.numel() for p in model.parameters()),
                  "probe_selection": schedule[0].get("probe_selection") if probe else None,
                  "cpu_rss_peak_sampled_bytes": process.memory_info().rss})
    for group in schedule:
        step_started = time.perf_counter()
        step = group["optimizer_step"]
        learning_rate = constant_learning_rate(step, recipe["max_optimizer_steps"],
                                               recipe["warmup_optimizer_steps"], recipe["learning_rate"])
        for parameter_group in optimizer.param_groups:
            parameter_group["lr"] = learning_rate
        step_log = {"epoch": group["epoch"], "optimizer_step": step,
                    "question_ids": [], "question_count": group["question_count"],
                    "learning_rate": learning_rate, "losses": [], "microbatch_tensor_shapes": [],
                    "optimizer_update_verified": False, "weight_change_observed": False,
                    "status": "started"}
        state["steps"].append(step_log)
        state["optimizer_groups_started"] += 1
        progress.emit("optimizer_group_started", optimizer_step=step, epoch=group["epoch"])
        witness = None
        call_count_before = state["optimizer_step_calls"]
        try:
            optimizer.zero_grad(set_to_none=True)
            for batch in group["microbatches"]:
                step_log["question_ids"].extend(row["question_id"] for row in batch)
                encoded = tokenizer(input_texts(batch, questions, chunks), max_length=512,
                                    truncation=True, padding=True, return_tensors="pt")
                verify_batch_negative_inputs(encoded, batch, context)
                encoded = encoded.to("cuda")
                step_log["microbatch_tensor_shapes"].append(list(encoded["input_ids"].shape))
                with torch.autocast(device_type="cuda", dtype=torch.float16):
                    outputs = model(**encoded)
                    embeddings = masked_mean_pool(outputs.last_hidden_state, encoded["attention_mask"])
                    count = len(batch)
                    loss = per_query_contrastive_loss(embeddings[:count],
                                                      embeddings[count:].reshape(count, 3, -1),
                                                      recipe["temperature"])
                if not bool(torch.isfinite(loss)):
                    raise FloatingPointError("nonfinite_loss")
                weight = len(batch) / group["question_count"]
                step_log["losses"].append(float(loss.detach().cpu()) * weight)
                scaler.scale(loss * weight).backward()
                del outputs, embeddings, loss, encoded
                state["cpu_rss_peak_sampled_bytes"] = max(
                    state["cpu_rss_peak_sampled_bytes"], process.memory_info().rss)
                progress.emit("microbatch_backward_completed", optimizer_step=step,
                              microbatch=len(step_log["losses"]), loss=step_log["losses"][-1])
            scaler.unscale_(optimizer)
            norm = torch.nn.utils.clip_grad_norm_(model.parameters(), recipe["max_grad_norm"],
                                                 error_if_nonfinite=True, foreach=False)
            step_log["gradient_norm_before_clip"] = float(norm)
            # Select a real nonzero gradient; padding rows may never change.
            for name, parameter in model.named_parameters():
                if parameter.grad is None:
                    continue
                gradient = parameter.grad.detach().reshape(-1)
                index = int(gradient.abs().argmax())
                if float(gradient[index].abs()) > 0:
                    witness = (name, parameter, index, float(parameter.detach().reshape(-1)[index]))
                    break
            if witness is None:
                raise FloatingPointError("no_nonzero_gradient")
            previous_scale = scaler.get_scale()
            progress.attempt(step)
            scaler.step(optimizer)
            scaler.update()
            torch.cuda.synchronize()
            name, parameter, index, before = witness
            after = float(parameter.detach().reshape(-1)[index])
            step_log.update({"witness_parameter": name, "witness_flat_index": index,
                             "witness_before": before, "witness_after": after,
                             "grad_scaler_scale": scaler.get_scale()})
            progress.observed(step_log, before != after)
            if (not math.isfinite(after) or scaler.get_scale() < previous_scale or before == after
                    or state["optimizer_step_calls"] != call_count_before + 1
                    or int(optimizer.state[parameter]["step"]) != step):
                raise FloatingPointError("optimizer_update_not_verified")
            step_log["optimizer_update_verified"] = True
            state["optimizer_steps_verified"] += 1
            # Persist the real update before a later resource check can fail.
            progress.emit("optimizer_update_verified", optimizer_step=step)
            allocated = torch.cuda.max_memory_allocated() / 2**20
            reserved = torch.cuda.max_memory_reserved() / 2**20
            step_log.update({"loss": sum(step_log["losses"]), "peak_allocated_mib": allocated,
                             "peak_reserved_mib": reserved})
            if allocated > recipe["resource_peak_allocated_limit_mib"]:
                raise MemoryError("resource_allocated_limit_exceeded")
            step_log["status"] = "passed"
            progress.emit("optimizer_group_passed", optimizer_step=step)
        except BaseException:
            step_log["status"] = "failed"
            if witness is not None and state["optimizer_step_calls"] > call_count_before:
                try:
                    name, parameter, index, before = witness
                    after = float(parameter.detach().reshape(-1)[index])
                    step_log.update({"witness_parameter": name, "witness_flat_index": index,
                                     "witness_before": before, "witness_after": after})
                    progress.observed(step_log, before != after)
                except (RuntimeError, ValueError, OSError) as witness_error:
                    step_log["post_failure_witness_error_type"] = type(witness_error).__name__
                    if not step_log["weight_change_observed"]:
                        state["current_optimizer_weight_update_status"] = "unknown_after_step_failure"
                        if not state["weight_updates_observed"]:
                            state["weight_update_status"] = "unknown_after_step_failure"
            progress.emit("optimizer_group_failed", optimizer_step=step,
                          update_verified=step_log["optimizer_update_verified"])
            raise
        finally:
            step_log["elapsed_ms"] = (time.perf_counter() - step_started) * 1000
            state["elapsed_ms"] = (time.perf_counter() - started) * 1000
    state.update({"status": "passed", "peak_allocated_mib": torch.cuda.max_memory_allocated() / 2**20,
                  "peak_reserved_mib": torch.cuda.max_memory_reserved() / 2**20})
    return state


def validate_probe_report(report: dict, execution_sha256: str, manifest_sha256: str,
                           recipe: dict) -> None:
    if (report.get("command") != "probe" or report.get("status") != "passed"
            or report.get("execution_plan_sha256") != execution_sha256
            or report.get("ready_manifest_sha256") != manifest_sha256
            or report.get("recipe") != recipe
            or report.get("optimizer_steps_attempted") != 1
            or report.get("optimizer_step_calls") != 1
            or report.get("optimizer_steps_completed") != 1
            or report.get("optimizer_steps_verified") != 1
            or report.get("optimizer_steps") != 1
            or report.get("probe_weight_update_executed") is not True
            or report.get("training_executed") is not False
            or report.get("quality_evaluation_executed") is not False
            or len(report.get("steps", [])) != 1
            or report["steps"][0].get("status") != "passed"
            or report["steps"][0].get("optimizer_update_verified") is not True
            or not 0 < report.get("peak_allocated_mib", 0) <=
            recipe["resource_peak_allocated_limit_mib"]):
        raise ValueError("probe_did_not_pass_same_frozen_inputs")


@contextlib.contextmanager
def execution_guard(root: Path, execution_sha256: str, command: str):
    """One local runner and one attempt per frozen command; never retry silently."""
    directory = root / ".local" / "m4-execution"
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "active.lock"
    try:
        handle = lock.open("xb")
    except FileExistsError as error:
        raise RuntimeError("another_model_execution_or_stale_lock_requires_investigation") from error
    try:
        with handle:
            handle.write(pilot.json_bytes({"pid": os.getpid(), "execution_sha256": execution_sha256,
                                           "command": command}))
            handle.flush()
            os.fsync(handle.fileno())
        claim = directory / f"{execution_sha256}-{command}.json"
        pilot.write_or_verify(claim, pilot.json_bytes({"execution_sha256": execution_sha256,
                                                       "command": command, "attempted": True}))
        yield
    finally:
        lock.unlink(missing_ok=True)


def journal_sink(path: Path):
    """Append only safe metadata with a durable flush after every event."""
    def persist(event: dict) -> None:
        ready.public_safe(event)
        with path.open("ab") as handle:
            handle.write(pilot.jsonl_bytes([finite_metadata(event)]))
            handle.flush()
            os.fsync(handle.fileno())
    return persist


def finite_metadata(value):
    """Failure evidence must remain valid JSON even after numerical corruption."""
    if isinstance(value, float) and not math.isfinite(value):
        return "nonfinite_nan" if math.isnan(value) else (
            "nonfinite_positive_infinity" if value > 0 else "nonfinite_negative_infinity")
    if isinstance(value, dict):
        return {key: finite_metadata(item) for key, item in value.items()}
    if isinstance(value, list):
        return [finite_metadata(item) for item in value]
    return value


def execute_run(args, execution_raw: bytes, recipe: dict, manifest: dict, context: dict) -> dict:
    """Execute only after all data gates; always preserve partial execution evidence."""
    output = args.output_dir.resolve()
    output.mkdir(parents=True)
    report = {"schema_version": 1, "command": args.command, "status": "started",
              "execution_plan_sha256": pilot.sha256(execution_raw),
              "ready_manifest_sha256": file_sha256(args.ready_manifest),
              "precision": recipe["mixed_precision"], "recipe": recipe,
              "paid_api_requests": 0, "financial_cost": "not_measured",
              "human_review": "pending", "training_executed": False,
              "quality_evaluation_executed": False, "terminal_checkpoint_saved": False,
              "execution_flag_definition": "training_executed means the optimizer was entered; "
              "partial failures retain separate completed, verified and observed-weight counts"}
    progress = UpdateProgress(report, journal_sink(output / "progress.jsonl"))
    torch, model = None, None
    started = time.perf_counter()
    try:
        progress.emit("run_started", command=args.command)
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
        import torch
        from transformers import AutoModel, AutoTokenizer

        if not torch.cuda.is_available():
            raise RuntimeError("cuda_required_no_cpu_fallback")
        specification = json.loads((ROOT / "data/models/m3-models.json").read_bytes())["models"]["e5"]
        verified = verify_snapshot(args.e5_snapshot, specification)
        report.update({"base_revision": specification["revision"], "verified_base_files": verified,
                       "runtime": {name: version(name) for name in ("torch", "transformers", "tokenizers")},
                       "device": torch.cuda.get_device_name(), "total_device_bytes":
                       torch.cuda.get_device_properties(0).total_memory,
                       "device_free_bytes_before_load": torch.cuda.mem_get_info()[0]})
        torch.cuda.reset_peak_memory_stats()
        seed_runtime(torch, recipe["seed"])
        tokenizer = AutoTokenizer.from_pretrained(str(args.e5_snapshot), local_files_only=True,
                                                  trust_remote_code=False, use_fast=True)
        if not tokenizer.is_fast or tokenizer.truncation_side != "right":
            raise ValueError("fast_right_truncating_tokenizer_required")
        verify_all_negative_inputs(tokenizer, manifest["triplets"], context)
        progress.emit("all_selected_negative_model_inputs_verified")
        # Probe and train both load a fresh immutable base; no probe state is reused.
        model = AutoModel.from_pretrained(str(args.e5_snapshot), local_files_only=True,
                                         trust_remote_code=False, use_safetensors=True,
                                         torch_dtype=torch.float32, attn_implementation="eager").to("cuda")
        progress.emit("fresh_base_model_loaded")
        run_updates(model, tokenizer, torch, manifest["triplets"], context, recipe,
                    probe=args.command == "probe", progress=progress)
        if args.command == "train":
            checkpoint = output / "terminal"
            model.save_pretrained(checkpoint, safe_serialization=True)
            tokenizer.save_pretrained(checkpoint)
            report["checkpoint_sha256"] = {path.name: file_sha256(path)
                                           for path in sorted(checkpoint.iterdir()) if path.is_file()}
            report["checkpoint_path"] = ready.relative(checkpoint)
            report["terminal_checkpoint_saved"] = True
            progress.emit("terminal_checkpoint_saved")
        if verify_snapshot(args.e5_snapshot, specification) != verified:
            raise ValueError("base_snapshot_changed_during_execution")
        validate_execution(json.loads(execution_raw))
        report["status"] = "passed"
        progress.emit("run_passed")
    except BaseException as error:
        safe_codes = {"cuda_required_no_cpu_fallback", "nonfinite_loss", "no_nonzero_gradient",
                      "optimizer_update_not_verified", "resource_allocated_limit_exceeded",
                      "base_snapshot_changed_during_execution", "full_weight_fp32_training_required"}
        is_oom = torch is not None and isinstance(error, torch.OutOfMemoryError)
        report.update({"status": "failed", "failure_type": type(error).__name__,
                       "failure_code": "oom" if is_oom else str(error)
                       if str(error) in safe_codes else "runtime_failed_stop_no_automatic_retry"})
        # Update in-memory state even when persisting a final event itself fails.
        with contextlib.suppress(Exception):
            progress.emit("run_failed", failure_code=report["failure_code"])
        raise
    finally:
        report.update(progress.execution_flags(args.command))
        report["total_elapsed_ms"] = (time.perf_counter() - started) * 1000
        if torch is not None:
            with contextlib.suppress(Exception):
                report.update({"peak_allocated_mib": torch.cuda.max_memory_allocated() / 2**20,
                               "peak_reserved_mib": torch.cuda.max_memory_reserved() / 2**20})
        safe_report = finite_metadata(report)
        report.clear()
        report.update(safe_report)
        ready.public_safe(report)
        pilot.write_or_verify(output / "report.json", pilot.json_bytes(report))
        model = None
        gc.collect()
        if torch is not None:
            with contextlib.suppress(Exception):
                torch.cuda.empty_cache()
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("probe", "train"))
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument("--ready-manifest", type=Path, required=True)
    parser.add_argument("--probe-report", type=Path)
    parser.add_argument("--e5-snapshot", type=Path, default=ROOT / "models/e5")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="New directory inside .local, including any saved weights")
    args = parser.parse_args(argv)
    execution_raw = args.execution_plan.read_bytes()
    execution = json.loads(execution_raw)
    recipe = validate_execution(execution)
    manifest, context = verified_data(execution, args.ready_manifest)
    snapshot_setting = ROOT / execution["readiness_arguments"]["e5_snapshot"]
    if args.e5_snapshot.resolve() != snapshot_setting.resolve():
        raise ValueError("snapshot_differs_from_readiness_contract")
    output = args.output_dir.resolve()
    if not output.is_relative_to((ROOT / ".local").resolve()) or output.exists():
        raise ValueError("training_output_must_be_new_local_directory")
    if args.command == "train":
        if args.probe_report is None:
            raise ValueError("verified_probe_report_required")
        validate_probe_report(json.loads(args.probe_report.read_bytes()), pilot.sha256(execution_raw),
                              file_sha256(args.ready_manifest), recipe)
    with execution_guard(ROOT, pilot.sha256(execution_raw), args.command):
        report = execute_run(args, execution_raw, recipe, manifest, context)
    print(json.dumps({"status": report["status"], "optimizer_steps": report["optimizer_steps"],
                      "training_executed": report["training_executed"],
                      "quality_evaluation_executed": False}))


if __name__ == "__main__":
    main()
