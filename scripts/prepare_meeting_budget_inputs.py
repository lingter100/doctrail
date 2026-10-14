"""Offline, once-only survey/prepare for the registered 5120-token follow-up.

Validation preparation belongs to an isolated custodian and precedes generation
selection; it never authorizes validation inference. All original payloads remain
unchanged. Every measurable arm is counted, including after a budget failure.
Only a completely successful survey writes input.json; receipt.json is written
once, including failure/unknown counts, and never enriched after publication.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from doctrail.meeting_answer_blocks import answer_messages_blocks, build_block_catalog
from doctrail.meeting_answer_spans import (
    answer_messages_spans,
    build_span_catalog,
    span_answer_grammar,
)
from doctrail.meeting_contract import AnswerRequest, strict_json
from doctrail.meeting_gguf import GREEDY, MAX_REQUEST_BYTES
from doctrail.meeting_input_budget import MAX_INPUT_TOKENS, MAX_NEW_TOKENS, PROTOCOL
from doctrail.meeting_qwen35 import MODEL_ID, MODEL_REVISION

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_FILE = "data/evaluation/meetings-c2-input-budget-protocol-v1.json"
PROTOCOL_SHA256 = "17f361118b2c7f48b092f3d2d83167f7d2731048aed16e4f80c1a431f743be87"
# Kept separately for the two immutable generations of source contracts.
LEGACY_FREEZES = (
    "data/evaluation/meetings-c2-comparison-source-freeze-v2.json",
    "data/evaluation/meetings-c2-source-processing-freeze-v2.json",
)
FILES = {"src/doctrail/meeting_input_budget.py", "scripts/prepare_meeting_budget_inputs.py",
         "tests/test_meeting_input_budget.py", "tests/test_prepare_meeting_budget_inputs.py"}
COUNTS = {"calibration": 8, "validation": 12}
PHASE_PATHS = {
    "calibration": ("data/evaluation/meetings-c2-calibration-v1/draft.json",
                    "data/evaluation/meetings-c2-calibration-v1/item-freeze-v1.json"),
    "validation": ("data/evaluation/meetings-c2-validation-v1/draft-v2.json",
                   "data/evaluation/meetings-c2-validation-v1/item-freeze-v2.json"),
}
BYTE_LIMIT = 16 * 1024 * 1024
ARMS = {"L0": (build_span_catalog, answer_messages_spans),
        "C2": (build_block_catalog, answer_messages_blocks)}


class PreparationError(ValueError):
    """A fixed safe code, never a tokenizer/DTO exception body."""


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def contained(path, *, output=False):
    root = ROOT.resolve()
    path = Path(path)
    absolute = path if path.is_absolute() else root / path
    if ".." in absolute.parts or not absolute.is_relative_to(root):
        raise PreparationError("preparation_path_outside_repository")
    current = root
    for part in absolute.relative_to(root).parts:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if current.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise PreparationError("preparation_linked_path")
    resolved = absolute.resolve()
    if (not resolved.is_relative_to(root) or output and
            (not resolved.is_relative_to(root / ".local") or resolved == root / ".local")):
        raise PreparationError("preparation_path_outside_repository")
    return resolved


def stamp(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def snapshot(path):
    before = stamp(path)
    with path.open("rb") as stream:
        raw = stream.read(BYTE_LIMIT + 1)
    if len(raw) > BYTE_LIMIT:
        raise PreparationError("preparation_file_limit")
    if stamp(path) != before:
        raise PreparationError("preparation_snapshot_changed")
    return raw, before


def _name(path):
    return path.relative_to(ROOT.resolve()).as_posix()


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)


def _bindings(value):
    bindings = value.get("bound_files")
    if (not isinstance(bindings, dict) or not bindings or
            any(not isinstance(n, str) or not _digest(h) for n, h in bindings.items())):
        raise PreparationError("preparation_binding_contract")
    return bindings


def _tokenizer_metadata(metadata):
    if (not isinstance(metadata, dict) or metadata.get("repo_id") != MODEL_ID
            or metadata.get("revision") != MODEL_REVISION
            or metadata.get("trust_remote_code") is not False
            or metadata.get("download_authorized") is not False
            or not isinstance(metadata.get("transformers_version"), str)
            or not isinstance(metadata.get("assets_sha256"), dict)
            or not {"tokenizer.json", "tokenizer_config.json", "chat_template.jinja"}
            <= metadata["assets_sha256"].keys()
            or any(not _digest(h) for h in metadata["assets_sha256"].values())):
        raise PreparationError("preparation_tokenizer_metadata")


def _summary(rows, total):
    values = [r["official_input_tokens"] for case in rows for r in case["arms"].values()
              if type(r["official_input_tokens"]) is int]
    return {"total_arms": total, "measured_arms": len(values),
        "unknown_arms": total - len(values),
        "failed_arms": sum(r["error_code"] is not None for c in rows for r in c["arms"].values()),
        "old_4096_pass": sum(n <= 4096 for n in values),
        "old_4096_fail": sum(n > 4096 for n in values),
        "new_5120_pass": sum(n <= MAX_INPUT_TOKENS for n in values),
        "new_5120_fail": sum(n > MAX_INPUT_TOKENS for n in values),
        "token_range": {arm: {"min": min(v) if v else None, "max": max(v) if v else None}
            for arm in ARMS for v in [[c["arms"][arm]["official_input_tokens"] for c in rows
                if type(c["arms"][arm]["official_input_tokens"]) is int]]}}


def prepare(draft_path, output, phase, *, item_freeze_path, source_freeze_path,
            protocol_path=None, baseline_input_path=None, loader=None, counter=None):
    """Read bound snapshots once; source_freeze_path is the NEW code freeze.

    The protocol pins draft/item-freeze bytes. A corpus source freeze is bound by
    the item freeze. No oracle/review/body referenced by a freeze is
    read. Calibration additionally compares a registered baseline input artifact.
    Source code is rehashed at completion; captured inputs receive stat-drift
    checks (not a second body read). No concurrent writers are supported.
    """
    if phase not in COUNTS:
        raise PreparationError("preparation_invalid_phase")
    paths = {"draft": contained(draft_path), "item_freeze": contained(item_freeze_path),
             "source_freeze": contained(source_freeze_path),
             "protocol": contained(protocol_path or ROOT / PROTOCOL_FILE)}
    if baseline_input_path is not None:
        paths["baseline_input"] = contained(baseline_input_path)
    output = contained(output, output=True)
    if output.exists() or any(output == p or p.is_relative_to(output) or
                              output.is_relative_to(p) for p in paths.values()):
        raise PreparationError("preparation_output_exists_or_collision")
    if len(set(paths.values())) != len(paths):
        raise PreparationError("preparation_input_alias")
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "candidate": PROTOCOL, "phase": phase, "status": "failed",
        "original_protocol_status": "preflight_failed_input_budget",
        "protocol_deviation": "equal_input_cap_4096_to_5120_after_length_metadata",
        "verification_scope": "code_draft_item_and_corpus_freeze_metadata",
        "referenced_body_oracle_bytes_rechecked": False,
        "snapshots": {}, "bound_files": {}, "cases": [], "tokenizer": None,
        "payloads_preserved": False, "input_sha256": None, "input_bytes": None,
        "model_calls": 0, "native_calls": 0, "downloads": 0, "errors": []}
    captures, stamps, code = {}, {}, {}

    def capture(path):
        path = contained(path)
        if path in captures:
            return captures[path]
        if output == path or output.is_relative_to(path) or path.is_relative_to(output):
            raise PreparationError("preparation_output_collision")
        raw, observed = snapshot(path)
        captures[path], stamps[path] = raw, observed
        report["snapshots"][_name(path)] = {"sha256": sha(raw), "bytes": len(raw)}
        return raw

    def bound(path, digest):
        raw = capture(path)
        if sha(raw) != digest:
            raise PreparationError("preparation_hash_mismatch")
        return strict_json(raw.decode("utf-8"))

    input_bytes = None
    try:
        if tuple(_name(paths[k]) for k in ("draft", "item_freeze")) != PHASE_PATHS[phase]:
            raise PreparationError("preparation_phase_path_mismatch")
        protocol = bound(paths["protocol"], PROTOCOL_SHA256)
        if protocol.get("candidate") != PROTOCOL:
            raise PreparationError("preparation_protocol_contract")
        registered = _bindings(protocol)
        # Read metadata first; reject an unregistered draft before opening it.
        if any(_name(paths[k]) not in registered for k in ("draft", "item_freeze")):
            raise PreparationError("preparation_unregistered_input")
        item = bound(paths["item_freeze"], registered[_name(paths["item_freeze"])])
        item_bindings = _bindings(item)
        if item_bindings.get(_name(paths["draft"])) != registered[_name(paths["draft"])]:
            raise PreparationError("preparation_item_binding")
        freeze = strict_json(capture(paths["source_freeze"]).decode("utf-8"))
        bindings = _bindings(freeze)
        if not (FILES | {PROTOCOL_FILE, *LEGACY_FREEZES}) <= bindings.keys():
            raise PreparationError("preparation_source_freeze_incomplete")
        if bindings[PROTOCOL_FILE] != PROTOCOL_SHA256:
            raise PreparationError("preparation_protocol_binding")
        # Only code/metadata bindings of the original 41/18 freezes are traversed.
        for name in LEGACY_FREEZES:
            legacy = bound(ROOT / name, registered[name])
            if bindings[name] != registered[name]:
                raise PreparationError("preparation_legacy_freeze_binding")
            for filename, digest in _bindings(legacy).items():
                if filename in code and code[filename] != digest:
                    raise PreparationError("preparation_conflicting_binding")
                code[filename] = digest
        for name in FILES:
            code[name] = bindings[name]
        # Registered design is part of the follow-up, not mutable commentary.
        for name, digest in registered.items():
            if name.startswith("docs/"):
                code[name] = digest
        for name, digest in code.items():
            if sha(capture(ROOT / name)) != digest:
                raise PreparationError("preparation_source_hash_mismatch")
        report["bound_files"] = dict(sorted(code.items()))
        corpus = [n for n in item_bindings if n.endswith("/source-freeze-v1.json")]
        if len(corpus) != 1 or Path(corpus[0]).parent != Path(_name(paths["draft"])).parent:
            raise PreparationError("preparation_corpus_freeze_binding")
        for name in LEGACY_FREEZES:
            if item_bindings.get(name) != registered[name]:
                raise PreparationError("preparation_item_legacy_binding")
        for name in corpus:
            bound(ROOT / name, item_bindings[name])
        draft = bound(paths["draft"], registered[_name(paths["draft"])])
        if (set(draft) != {"schema_version", "phase", "cases"}
                or type(draft.get("schema_version")) is not int or draft["schema_version"] != 1
                or draft.get("phase") != phase or not isinstance(draft.get("cases"), list)
                or len(draft["cases"]) != COUNTS[phase]):
            raise PreparationError("preparation_draft_contract")
        cases = draft["cases"]
        ids = [c.get("id") if isinstance(c, dict) else None for c in cases]
        if (any(not isinstance(i, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", i) for i in ids)
                or len(set(ids)) != len(ids)
                or any(set(c) != {"id", "payload"} for c in cases)):
            raise PreparationError("preparation_case_contract")
        baseline = None
        if "baseline_input" in paths:
            name = _name(paths["baseline_input"])
            if name not in bindings:
                raise PreparationError("preparation_baseline_unregistered")
            baseline = bound(paths["baseline_input"], bindings[name])
            if (type(baseline.get("schema_version")) is not int or baseline["schema_version"] != 1
                    or baseline.get("phase") != phase or not isinstance(baseline.get("cases"), list)
                    or [{"id": c.get("id"), "payload": c.get("payload")}
                        for c in baseline["cases"]] != cases):
                raise PreparationError("preparation_baseline_payload_mismatch")
            if any(not isinstance(c.get("official_input_tokens"), dict)
                   or set(c["official_input_tokens"]) != set(ARMS)
                   or any(type(n) is not int or not 0 < n <= 4096
                          for n in c["official_input_tokens"].values()) for c in baseline["cases"]):
                raise PreparationError("preparation_baseline_token_contract")
        if phase == "calibration" and baseline is None:
            raise PreparationError("preparation_baseline_required")
        for case in cases:
            report["cases"].append({"id": case["id"],
                "payload_sha256": sha(canonical(case["payload"])),
                "payload_bytes": len(canonical(case["payload"])), "payload_preserved": True,
                "arms": {arm: {"official_input_tokens": None, "old_4096_pass": None,
                    "new_5120_pass": None, "error_code": None} for arm in ARMS}})
        from scripts.check_meeting_review_token_budget import count_prompt, load_tokenizer
        tokenizer, metadata = (loader or load_tokenizer)(False)
        _tokenizer_metadata(metadata)
        report["tokenizer"] = metadata
        for index, (case, row) in enumerate(zip(cases, report["cases"], strict=True)):
            try:
                request = AnswerRequest.model_validate(case["payload"])
                if not request.contexts:
                    raise PreparationError("preparation_contexts_required")
                # Excluding unset fields preserves omissions rather than inserting defaults.
                if canonical(request.model_dump(exclude_unset=True)) != canonical(case["payload"]):
                    raise PreparationError("preparation_payload_coercion")
            except Exception:  # noqa: BLE001 - no DTO source text in receipt
                row["payload_preserved"] = False
                for arm in ARMS:
                    row["arms"][arm]["error_code"] = "invalid_payload"
                continue
            for arm, (catalog_fn, prompt_fn) in ARMS.items():
                measured = row["arms"][arm]
                try:
                    catalog = catalog_fn(request.contexts)
                    prompt = prompt_fn(request.query, catalog)
                    grammar = span_answer_grammar(catalog)
                    measured.update(prompt_sha256=sha(canonical(prompt)),
                        grammar_sha256=sha(grammar.encode("utf-8")),
                        supplied_chunks=len(catalog.sources), supplied_units=len(catalog.spans))
                    template = {"messages": prompt, "chat_template_kwargs": {"enable_thinking": False}}
                    measured["template_request_bytes"] = len(json.dumps(template, ensure_ascii=False,
                                                                        allow_nan=False).encode())
                    if measured["template_request_bytes"] > MAX_REQUEST_BYTES:
                        raise PreparationError("template_request_byte_limit")
                except Exception:  # noqa: BLE001 - source details remain isolated
                    measured["error_code"] = "static_structure_or_byte_limit"
                    continue
                try:
                    count = (counter or count_prompt)(tokenizer, prompt)
                    if type(count) is not int or count <= 0:
                        raise PreparationError("invalid_official_token_count")
                except Exception:  # noqa: BLE001 - tokenizer errors may contain private text
                    measured["error_code"] = "token_count_failed"
                    continue
                measured.update(official_input_tokens=count, old_4096_pass=count <= 4096,
                                new_5120_pass=count <= MAX_INPUT_TOKENS)
                # Zeros are a lower bound only, never claimed as real native IDs.
                # Bound the diagnostic allocation even for an erroneous huge count.
                skeleton = {**GREEDY, "n_predict": MAX_NEW_TOKENS, "grammar": grammar,
                    "prompt": [], "cache_prompt": False, "return_tokens": True}
                empty_size = len(json.dumps(skeleton, ensure_ascii=False, allow_nan=False).encode())
                lower_bytes = empty_size + count * 3 - 2
                measured.update(native_request_bytes=None, native_request_bytes_verified=False,
                    completion_bytes_lower_bound_at_official_count=lower_bytes,
                    native_byte_guard="required_at_actual_native_dispatch")
                if count > MAX_INPUT_TOKENS:
                    measured["error_code"] = "input_budget_exceeded"
                elif lower_bytes > MAX_REQUEST_BYTES:
                    measured["error_code"] = "completion_request_byte_limit"
                elif baseline is not None and baseline["cases"][index].get(
                        "official_input_tokens", {}).get(arm) != count:
                    measured["error_code"] = "baseline_token_count_mismatch"
        report["payloads_preserved"] = all(c["payload_preserved"] for c in report["cases"])
        if any(r["error_code"] for c in report["cases"] for r in c["arms"].values()):
            raise PreparationError("preparation_survey_failed")
        prepared = {"schema_version": 1, "phase": phase, "cases": [{**case,
            "official_input_tokens": {arm: row["arms"][arm]["official_input_tokens"] for arm in ARMS}}
            for case, row in zip(cases, report["cases"], strict=True)]}
        report["payloads_preserved"] = all(c["payload"] == p["payload"] for c, p in
                                          zip(cases, prepared["cases"], strict=True))
        input_bytes = encoded(prepared)
        if len(input_bytes) > BYTE_LIMIT:
            raise PreparationError("preparation_file_limit")
        report.update(status="passed", input_sha256=sha(input_bytes), input_bytes=len(input_bytes))
    except Exception as error:  # noqa: BLE001 - receipt never stores raw exception details
        report["errors"].append(str(error) if type(error) is PreparationError
                                else "preparation_failed")
    # A failed survey is evidence too: detect drift even after partial counts.
    try:
        for path, observed in stamps.items():
            if stamp(contained(path)) != observed:
                raise PreparationError("preparation_snapshot_changed")
        for name, digest in code.items():
            if sha(snapshot(contained(ROOT / name))[0]) != digest:
                raise PreparationError("preparation_source_changed")
    except Exception as error:  # noqa: BLE001 - safe diagnostic, no input reread
        report.update(status="failed", input_sha256=None, input_bytes=None)
        report["errors"].append(str(error) if type(error) is PreparationError
                                else "preparation_integrity_check_failed")
    report["summary"] = _summary(report["cases"], COUNTS[phase] * 2)
    if report["status"] == "passed":
        try:
            with (contained(output) / "input.json").open("xb") as stream:
                stream.write(input_bytes)
        except Exception:  # noqa: BLE001 - retain the claimed directory and safe failure
            report.update(status="failed", input_sha256=None)
            report["errors"].append("preparation_input_write_failed")
    with (contained(output) / "receipt.json").open("xb") as stream:
        stream.write(encoded(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=COUNTS, required=True)
    parser.add_argument("--item-freeze", type=Path, required=True)
    parser.add_argument("--source-freeze", type=Path, required=True)
    parser.add_argument("--baseline-input", type=Path)
    args = parser.parse_args()
    try:
        with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
            result = prepare(args.draft, args.output, args.phase,
                item_freeze_path=args.item_freeze, source_freeze_path=args.source_freeze,
                baseline_input_path=args.baseline_input)
    except Exception:  # noqa: BLE001 - paths and tokenizer details are private
        parser.exit(1, "budget_input_preparation_failed\n")
    print(json.dumps({"status": result["status"], **result["summary"],
                      "model_calls": 0, "native_calls": 0, "downloads": 0}))
    raise SystemExit(0 if result["status"] == "passed" else 2)


if __name__ == "__main__":
    main()
