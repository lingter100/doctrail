"""Tokenizer-only C1 readiness estimates; never generation or quality evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from doctrail.meeting_answer_review import review_messages, revision_messages
from doctrail.meeting_answer_spans import answer_messages_spans, build_span_catalog
from doctrail.meeting_contract import AnswerRequest, strict_json
from doctrail.meeting_qwen35 import MODEL_ID, MODEL_REVISION, NONTHINKING_PREAMBLE

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja",
          "special_tokens_map.json", "added_tokens.json", "vocab.json", "merges.txt")
BOUND_CODE = ("src/doctrail/meeting_answer_spans.py", "src/doctrail/meeting_answer_review.py",
              "src/doctrail/meeting_answer_v2.py", "src/doctrail/meeting_contract.py",
              "src/doctrail/meeting_worker.py", "src/doctrail/meeting_qwen35.py",
              "scripts/check_meeting_review_token_budget.py")
INPUT_LIMIT = 4096
SERIALIZATION_MARGIN = 256


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_cases(path, expected_sha):
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha):
        raise ValueError("invalid_expected_sha")
    with Path(path).open("rb") as stream:
        raw = stream.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("input_file_limit")
    if sha(raw) != expected_sha:
        raise ValueError("input_hash_mismatch")
    cases = strict_json(raw.decode("utf-8")).get("cases", [])
    if not cases or any(c.get("operation") != "answer" for c in cases):
        raise ValueError("answer_cases_required")
    ids = [c.get("id") for c in cases]
    # IDs are the only case text included in the saved report, never console output.
    if any(not isinstance(i, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", i)
           for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("invalid_case_ids")
    requests = [AnswerRequest.model_validate(c["payload"]) for c in cases]
    if any(not request.contexts for request in requests):
        raise ValueError("contexts_required")
    return list(zip(ids, requests, strict=True))


def load_tokenizer(allow_download=False):
    """Download only explicitly named tokenizer assets, never config/model weights."""
    import transformers
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer

    folder = Path(snapshot_download(repo_id=MODEL_ID, revision=MODEL_REVISION,
        allow_patterns=list(ASSETS), local_files_only=not allow_download))
    contents = {name: (folder / name).read_bytes() for name in ASSETS
                if (folder / name).is_file()}
    assets = {name: sha(raw) for name, raw in contents.items()}
    if not {"tokenizer.json", "tokenizer_config.json", "chat_template.jinja"} <= assets.keys():
        raise ValueError("tokenizer_assets_incomplete")
    # The cache snapshot may already contain model/config files from another task.
    # Isolate precisely the hashed tokenizer bytes so AutoTokenizer cannot silently
    # read an unrecorded root config or cached alternative tokenizer. Missing assets
    # fail locally rather than falling back to repository/model downloads.
    with tempfile.TemporaryDirectory(prefix="doctrail-tokenizer-only-") as isolated:
        for name, raw in contents.items():
            (Path(isolated) / name).write_bytes(raw)
        tokenizer = AutoTokenizer.from_pretrained(isolated, local_files_only=True,
                                                  trust_remote_code=False)
    return tokenizer, {"repo_id": MODEL_ID, "revision": MODEL_REVISION,
        "transformers_version": transformers.__version__, "assets_sha256": assets,
        "trust_remote_code": False, "download_authorized": allow_download}


def count_prompt(tokenizer, messages):
    rendered = tokenizer.apply_chat_template(messages, tokenize=False,
        add_generation_prompt=True, enable_thinking=False)
    if not isinstance(rendered, str) or not rendered.endswith(NONTHINKING_PREAMBLE):
        raise ValueError("nonthinking_preamble_mismatch")
    tokens = tokenizer.encode(rendered, add_special_tokens=False)
    if not isinstance(tokens, list) or not tokens or any(type(t) is not int for t in tokens):
        raise ValueError("invalid_tokenizer_result")
    return len(tokens)


def measure(cases, tokenizer):
    rows = []
    for identity, request in cases:
        catalog = build_span_catalog(request.contexts)
        skeletons = {
            "empty": {"status": "abstained", "claims": []},
            "fixed_synthetic": {"status": "answered", "claims": [
                {"evidence_ids": [catalog.eligible_ids[0]], "text": "Synthetic draft claim."}]}}
        counts = {"D0": count_prompt(tokenizer, answer_messages_spans(request.query, catalog))}
        for name, draft in skeletons.items():
            indices = list(range(len(draft["claims"])))
            review = {"claim_checks": [{"claim_index": i, "verdict": "uncertain"} for i in indices],
                "question_parts": [{"description": "Synthetic question requirement",
                                    "claim_indices": indices, "status": "uncertain"}],
                "source_sufficiency": "uncertain", "language_ok": True}
            counts[f"V0_{name}"] = count_prompt(tokenizer,
                review_messages(request.query, catalog, draft))
            # V1 has the identical review contract with an unknown revised draft.
            counts[f"V1_{name}"] = counts[f"V0_{name}"]
            counts[f"D1_{name}"] = count_prompt(tokenizer,
                revision_messages(request.query, catalog, draft, review))
        estimates = {stage: tokens + (0 if stage == "D0" else
            (768 + 512 + SERIALIZATION_MARGIN if stage.startswith("D1")
             else 768 + SERIALIZATION_MARGIN)) for stage, tokens in counts.items()}
        rows.append({"id": identity, "placeholder_prompt_tokens": counts,
            "planning_prompt_tokens_with_headroom": estimates,
            "d0_within_limit": counts["D0"] <= INPUT_LIMIT,
            "planning_within_limit": all(n <= INPUT_LIMIT for n in estimates.values())})
    return rows


def prepare(input_path, expected_sha, output_path, *, allow_download=False, loader=load_tokenizer):
    output = Path(output_path)
    if output.exists():
        raise ValueError("output_exists")
    cases = read_cases(input_path, expected_sha)
    code_hashes = {name: sha((ROOT / name).read_bytes()) for name in BOUND_CODE}
    tokenizer, metadata = loader(allow_download)
    rows = measure(cases, tokenizer)
    if any(sha((ROOT / name).read_bytes()) != digest for name, digest in code_hashes.items()):
        raise ValueError("candidate_code_changed")
    report = {"schema_version": 1, "candidate": "meeting-answer-review-c1",
        "purpose": "tokenizer_only_input_readiness_estimate", "input_sha256": expected_sha,
        "tokenizer": metadata, "candidate_code_sha256": code_hashes, "cases": rows,
        "model_calls": 0, "native_calls": 0, "input_limit": INPUT_LIMIT,
        "headroom": {"draft_output_tokens": 768, "review_output_tokens": 512,
                     "serialization_margin_tokens": SERIALIZATION_MARGIN},
        "limitations": ["Dynamic draft/review content is unknown before generation.",
            "Headroom is a planning estimate, not a mathematical worst-case guarantee.",
            "Official Transformers token counts are not verified identical to native GGUF counts.",
            "Frozen native per-stage token guards remain authoritative; this is not quality evidence.",
            "V1 uses the same placeholder review input as V0, not a generated revised draft."],
        "summary": {"cases": len(rows), "all_d0_within_limit": all(r["d0_within_limit"] for r in rows),
                    "all_planning_within_limit": all(r["planning_within_limit"] for r in rows),
                    "max_placeholder_tokens": max(max(r["placeholder_prompt_tokens"].values()) for r in rows),
                    "max_planning_tokens": max(max(r["planning_prompt_tokens_with_headroom"].values()) for r in rows)}}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-download", action="store_true")
    args = parser.parse_args()
    try:
        # Dependency progress/warnings may contain cache paths. The CLI publishes
        # only its aggregate result or the fixed safe error envelope.
        with (open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink)):
            report = prepare(args.input, args.expected_sha, args.output,
                             allow_download=args.allow_download)
    except Exception:  # noqa: BLE001 - tokenizer/input exceptions may include private contents
        parser.exit(1, '{"error":"token_readiness_failed","model_calls":0,"native_calls":0}\n')
    print(json.dumps({**report["summary"], "model_calls": 0, "native_calls": 0}))
    raise SystemExit(0 if report["summary"]["all_planning_within_limit"] else 2)


if __name__ == "__main__":
    main()
