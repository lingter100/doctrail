"""Prepare NEW C2 comparison inputs with the pinned offline official tokenizer.

No generation, weight loading, download, question authoring, repair or retry is
performed. Validation drafts may be handled only by the isolated custodian.
This pre-execution token preparation is separate from, and cannot satisfy, the
calibration selection gate required before any validation model generation.
Existing evaluation pools and completed probe entrypoints are never executed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from doctrail.meeting_answer_blocks import answer_messages_blocks, build_block_catalog
from doctrail.meeting_answer_spans import (
    answer_messages_spans,
    build_span_catalog,
    span_answer_grammar,
)
from doctrail.meeting_contract import AnswerRequest, strict_json
from scripts.probe_meeting_blocks_comparison import FILES as COMPARISON_FILES

ROOT = Path(__file__).resolve().parents[1]
FILES = COMPARISON_FILES | {"scripts/prepare_meeting_blocks_inputs.py",
                            "tests/test_prepare_meeting_blocks_inputs.py"}
COUNTS = {"calibration": 8, "validation": 12}
BYTE_LIMIT = 16 * 1024 * 1024


def snapshot(path):
    """Hash and parse callers' exact same bounded snapshot, never a second read."""
    with Path(path).open("rb") as stream:
        raw = stream.read(BYTE_LIMIT + 1)
    if len(raw) > BYTE_LIMIT:
        raise ValueError("input_preparation_file_limit")
    return raw, hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def within_root(path):
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(ROOT.resolve()):
        raise ValueError("input_preparation_path_outside_repository")
    return resolved


def source_bindings():
    return {name: snapshot(within_root(ROOT / name))[1] for name in sorted(FILES)}


def prepare(draft_path, output, phase, *, loader=None, counter=None):
    from scripts.check_meeting_review_token_budget import count_prompt, load_tokenizer

    if phase not in COUNTS:
        raise ValueError("input_preparation_invalid_phase")
    draft_path, output = within_root(draft_path), within_root(output)
    if output.exists() or draft_path == output or draft_path.is_relative_to(output):
        raise ValueError("input_preparation_output_exists_or_collision")
    sources = source_bindings()
    raw, draft_sha = snapshot(draft_path)
    draft = strict_json(raw.decode("utf-8"))
    if (set(draft) != {"schema_version", "phase", "cases"}
            or type(draft.get("schema_version")) is not int or draft["schema_version"] != 1
            or draft.get("phase") != phase or not isinstance(draft.get("cases"), list)
            or len(draft["cases"]) != COUNTS[phase]):
        raise ValueError("input_preparation_draft_contract")
    cases, ids = draft["cases"], []
    requests = []
    for case in cases:
        if (not isinstance(case, dict) or set(case) != {"id", "payload"}
                or not isinstance(case.get("id"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", case["id"])):
            raise ValueError("input_preparation_case_contract")
        ids.append(case["id"])
        request = AnswerRequest.model_validate(case["payload"])
        if not request.contexts:
            raise ValueError("input_preparation_contexts_required")
        requests.append(request)
    if len(set(ids)) != len(ids):
        raise ValueError("input_preparation_duplicate_ids")
    # Validate both unchanged catalogs/grammars before touching even a tokenizer.
    prompts = []
    for request in requests:
        arms = {}
        for arm, catalog_fn, messages_fn in (
                ("L0", build_span_catalog, answer_messages_spans),
                ("C2", build_block_catalog, answer_messages_blocks)):
            catalog = catalog_fn(request.contexts)
            span_answer_grammar(catalog)
            arms[arm] = messages_fn(request.query, catalog)
        prompts.append(arms)
    tokenizer, metadata = (loader or load_tokenizer)(False)
    if not isinstance(metadata, dict):
        raise TypeError("input_preparation_tokenizer_metadata")
    prepared_cases, token_rows = [], []
    for case, messages in zip(cases, prompts, strict=True):
        counts = {arm: (counter or count_prompt)(tokenizer, prompt)
                  for arm, prompt in messages.items()}
        if any(type(count) is not int or not 0 < count <= 4096 for count in counts.values()):
            raise ValueError("input_preparation_token_limit")
        # Preserve each payload exactly as supplied, including omissions and text.
        prepared_cases.append({**case, "official_input_tokens": counts})
        token_rows.append({"id": case["id"], "official_input_tokens": counts})
    prepared = {"schema_version": 1, "phase": phase, "cases": prepared_cases}
    input_bytes = encoded(prepared)
    if len(input_bytes) > BYTE_LIMIT:
        raise ValueError("input_preparation_file_limit")
    if source_bindings() != sources:
        raise ValueError("input_preparation_source_changed")
    receipt = {"schema_version": 1, "phase": phase, "bound_files": sources,
        "draft_sha256": draft_sha, "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
        "tokenizer": metadata, "cases": token_rows,
        "token_range": {arm: {"min": min(r["official_input_tokens"][arm] for r in token_rows),
                              "max": max(r["official_input_tokens"][arm] for r in token_rows)}
                        for arm in ("L0", "C2")}, "model_calls": 0, "downloads": 0}
    receipt_bytes = encoded(receipt)
    # Claim only after all preflight succeeds; any subsequent write failure leaves
    # the claimed directory as evidence and requires a separately named attempt.
    output.mkdir(parents=True, exist_ok=False)
    for filename, contents in (("input.json", input_bytes), ("receipt.json", receipt_bytes)):
        with (output / filename).open("xb") as stream:
            stream.write(contents)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=COUNTS, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.draft, args.output, args.phase)
    except Exception:  # noqa: BLE001 - never print question, source or tokenizer exception contents
        parser.exit(1, "input_preparation_failed\n")
    print(json.dumps({"phase": args.phase, "cases": len(result["cases"]),
                      "model_calls": 0, "downloads": 0}))


if __name__ == "__main__":
    main()
