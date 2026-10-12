"""M4 train-only review packs and data readiness; never train or probe a model.

`packs` writes full source context only below .local. `tokenize` loads only a pinned
CPU tokenizer (use uv run --group retrieval). `compile` and `replay` are model-free
structural checks of saved token evidence, not fresh tokenization or AI review.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from importlib.metadata import version
from pathlib import Path

from scripts import prepare_training as pilot
from scripts.analyze_candidates import (
    open_tokenizer,
    span_visibility,
    tokenize_input,
    verify_tokenizer_files,
)
from scripts.validate_training_reviews import question_hash, validate_reviews

ROOT = pilot.ROOT
SOURCES = (
    "scripts/prepare_training_ready.py", "scripts/prepare_training.py",
    "scripts/validate_training_reviews.py", "scripts/analyze_candidates.py",
    "scripts/prepare_corpus.py", "src/doctrail/ingest.py", "src/doctrail/retrieval.py",
    "src/doctrail/model_retrieval.py",
)
SHARDS = {"A": "m4_gate_design", "B": "m4_supp_author"}
LABELS = {"negative", "relevant", "ambiguous", "unknown"}
ARTIFACTS = ("questions.jsonl", "positive-pairs.jsonl", "negative-candidates.jsonl", "report.json")


def rows(raw: bytes) -> list[dict]:
    return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]


def relative(path: Path, root: Path = ROOT) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("Input and output paths must be inside repository")
    return resolved.relative_to(root.resolve()).as_posix()


def read_snapshot(path: Path, bindings: dict, root: Path = ROOT) -> bytes:
    name = relative(path, root)
    raw = path.read_bytes()
    digest = pilot.sha256(raw)
    if bindings.setdefault(name, digest) != digest:
        raise ValueError("Input changed during execution")
    return raw


def source_hashes(root: Path = ROOT) -> dict:
    return {name: pilot.sha256((root / name).read_bytes().replace(b"\r\n", b"\n"))
            for name in SOURCES}


def reviewer(agent: str) -> dict:
    return {"agent": agent, "model": "gpt-6-astra", "reasoning": "xhigh",
            "review_kind": "independent_ai"}


def shard_for(identifier: str) -> str:
    match = re.fullmatch(r"m4-fit-(\d{3})", identifier)
    if not match or not 1 <= int(match[1]) <= 64:
        raise ValueError("Unexpected frozen fit question ID")
    return "A" if int(match[1]) <= 32 else "B"


def verify_ref(reference: dict, chunks: dict, part: str, plan: dict) -> dict:
    chunk = chunks.get(reference.get("chunk_id"))
    if (chunk is None or any(reference.get(key) != value
                             for key, value in pilot.compact_chunk(chunk).items())
            or pilot.sha256(chunk["text"].encode()) != chunk["text_sha256"]
            or pilot.partition_for(chunk["family_id"], plan) != part):
        raise ValueError("Chunk binding or train partition mismatch")
    return chunk


def build_review_packs(questions: list[dict], drafts: list[dict], candidates: list[dict],
                       chunks: dict, plan: dict, readiness_sha256: str) -> dict[str, dict]:
    draft_map = {row["id"]: row for row in drafts}
    if len(draft_map) != len(drafts):
        raise ValueError("Duplicate draft ID")
    fit = sorted((q for q in questions if q["partition"] == "fit"), key=lambda q: q["id"])
    if [q["id"] for q in fit] != [f"m4-fit-{i:03d}" for i in range(1, 65)]:
        raise ValueError("Frozen 64 fit questions required")
    packs = {shard: {"schema_version": 1, "shard": shard,
                    "readiness_plan_sha256": readiness_sha256,
                    "reviewer": reviewer(agent), "human_review": "pending", "items": []}
             for shard, agent in SHARDS.items()}
    seen = set()
    for candidate in candidates:
        key = candidate["question_id"], candidate["chunk_id"]
        if key in seen:
            raise ValueError("Duplicate mined candidate")
        seen.add(key)
        verify_ref(candidate, chunks, candidate["partition"], plan)
    for question in fit:
        identifier = question["id"]
        positives = [chunks[chunk_id] for chunk_id in question["positive_chunk_ids"]]
        positives.sort(key=lambda row: int(row["chunk_id"].rsplit(":", 1)[1]))
        if not positives:
            raise ValueError("Review requires positive chunk context")
        for chunk in positives:
            verify_ref(pilot.compact_chunk(chunk), chunks, "fit", plan)
        pool = sorted((c for c in candidates if c["question_id"] == identifier
                       and c["status"] == "unreviewed"),
                      key=lambda c: (c["rank"], c["chunk_id"]))[:4]
        if len(pool) != 4:
            raise ValueError("Frozen first-four review pool incomplete; new plan required")
        positive_refs = [pilot.compact_chunk(chunk) for chunk in positives]
        positive_ids = set(question["positive_chunk_ids"])
        for candidate in pool:
            if (candidate["partition"] != "fit" or candidate["chunk_id"] in positive_ids
                    or candidate["quarantine_reasons"] or candidate["negative_label"] is not None
                    or candidate["semantic_review"] != "pending"
                    or candidate["human_review"] != "pending"
                    or candidate["eligible_for_training"] is not False):
                raise ValueError("Unsafe candidate in independent review pool")
        packs[shard_for(identifier)]["items"].append({
            "question": question, "question_sha256": question_hash(draft_map[identifier]),
            "compiled_question_sha256": question_hash(question),
            "positive_context_sha256": pilot.fingerprint(positive_refs),
            "positives": [{**ref, "text": chunk["text"]}
                          for ref, chunk in zip(positive_refs, positives, strict=True)],
            "candidates": [{**candidate, "candidate_sha256": question_hash(candidate),
                            "text": chunks[candidate["chunk_id"]]["text"]}
                           for candidate in pool],
        })
    return packs


def event_binding(pack: dict, item: dict, candidate: dict, pack_sha256: str | None = None) -> dict:
    return {
        "question_id": item["question"]["id"],
        "candidate_chunk_id": candidate["chunk_id"],
        "question_sha256": item["question_sha256"],
        "compiled_question_sha256": item["compiled_question_sha256"],
        "positive_context_sha256": item["positive_context_sha256"],
        "candidate_sha256": candidate["candidate_sha256"],
        "candidate_text_sha256": candidate["text_sha256"],
        "review_pack_sha256": pack_sha256 or pilot.fingerprint(pack),
        "readiness_plan_sha256": pack["readiness_plan_sha256"],
        "reviewer": pack["reviewer"], "human_review": "pending",
    }


def validate_negative_reviews(packs: dict[str, dict], events: list[dict]) -> dict:
    hashes = {shard: pilot.fingerprint(pack) for shard, pack in packs.items()}
    expected = {(item["question"]["id"], candidate["chunk_id"]):
                event_binding(pack, item, candidate, hashes[shard])
                for shard, pack in packs.items() for item in pack["items"]
                for candidate in item["candidates"]}
    actual = {(event.get("question_id"), event.get("candidate_chunk_id")): event
              for event in events}
    if len(actual) != len(events) or set(actual) != set(expected):
        raise ValueError("Negative review coverage must be exact; missing/extra/duplicate receipt")
    for key, binding in expected.items():
        event = actual[key]
        if any(event.get(field) != value for field, value in binding.items()):
            raise ValueError("Negative review hash, role or human-pending binding mismatch")
        if (event.get("label") not in LABELS or not isinstance(event.get("reason"), str)
                or not event["reason"].strip()):
            raise ValueError("Negative review needs explicit valid label and reason")
    selected, shortfalls = {}, []
    for pack in packs.values():
        for item in pack["items"]:
            identifier = item["question"]["id"]
            accepted = [candidate for candidate in item["candidates"]
                        if actual[(identifier, candidate["chunk_id"])]["label"] == "negative"][:2]
            selected[identifier] = [pilot.compact_chunk(c) for c in accepted]
            if len(accepted) != 2:
                shortfalls.append(identifier)
    return {"selected": selected, "shortfalls": sorted(shortfalls),
            "labels": dict(sorted(Counter(e["label"] for e in events).items()))}


def validate_positive_reviews(drafts: list[dict], events: list[dict], packs: dict) -> dict:
    original = [q for q in drafts if q["id"] not in {"m4-cal-015", "m4-cal-016"}]
    supplemental = [q for q in drafts if q["id"] in {"m4-cal-015", "m4-cal-016"}]
    original_ids = {q["id"] for q in original}
    if (len(original) != 78 or len(supplemental) != 2
            or len({q["id"] for q in drafts}) != 80
            or len(events) != 80 or len({e["question_id"] for e in events}) != 80
            or {e["question_id"] for e in events} != {q["id"] for q in drafts}):
        raise ValueError("Positive review requires frozen 78 plus exactly 2 supplemental questions")
    old_report = validate_reviews(original, [e for e in events if e["question_id"] in original_ids],
                                  packs)
    by_id = {event["question_id"]: event for event in events}
    for question in supplemental:
        event = by_id[question["id"]]
        pack = packs[question["author_pack_sha256"]]
        document = next(d for d in pack["documents"]
                        if d["id"] == question["evidence"][0]["document_id"])
        if (question["partition"] != "calibration" or pack["partition"] != "calibration"
                or event.get("question_sha256") != question_hash(question)
                or event.get("author_pack_sha256") != question["author_pack_sha256"]
                or event.get("document_sha256") != document["normalized_sha256"]
                or event.get("reviewer") != reviewer("m4_gate_design")
                or event.get("human_review") != "pending"
                or event.get("decision") not in {"accept", "revise", "reject"}
                or not isinstance(event.get("reason"), str) or not event["reason"].strip()):
            raise ValueError("Supplemental independent positive review binding mismatch")
    return {"all_ai_accepted": old_report["all_ai_accepted"]
            and all(by_id[q["id"]]["decision"] == "accept" for q in supplemental),
            "decisions": dict(sorted(Counter(e["decision"] for e in events).items())),
            "human_reviewed_questions": 0}


def token_payload(questions: list[dict], chunks: dict, review_packs: dict, tokenizer,
                  provenance: dict, bindings: dict, sources: dict,
                  selected_negatives: dict | None = None) -> dict:
    checks = []
    for question in sorted(questions, key=lambda q: q["id"]):
        query = tokenizer("query: " + question["question"], truncation=False, padding=False)
        query_after = tokenizer("query: " + question["question"], truncation=True,
                                max_length=512, padding=False)
        positives = []
        for chunk_id in sorted(question["positive_chunk_ids"],
                               key=lambda value: int(value.rsplit(":", 1)[1])):
            chunk = chunks[chunk_id]
            tokens = tokenize_input(tokenizer, chunk)
            positives.append({**pilot.compact_chunk(chunk),
                              "tokens_before": tokens["tokens_before"],
                              "tokens_after": tokens["tokens_after"],
                              "truncated": tokens["truncated"],
                              "visibility": span_visibility(chunk, question["evidence"][0], tokens)})
        checks.append({"question_id": question["id"],
                       "compiled_question_sha256": question_hash(question),
                       "query_tokens": len(query["input_ids"]),
                       "query_input_ids_sha256": pilot.fingerprint(query["input_ids"]),
                       "query_retained_input_ids_sha256": pilot.fingerprint(query_after["input_ids"]),
                       "positives": positives,
                       "selected_positive_chunk_id": next((p["chunk_id"] for p in positives
                           if p["visibility"]["all_evidence_overlapping_tokens_retained"]), None)})
    candidates = []
    candidate_ids = sorted({c["chunk_id"] for p in review_packs.values()
                            for item in p["items"] for c in item["candidates"]})
    for chunk_id in candidate_ids:
        chunk = chunks[chunk_id]
        tokens = tokenize_input(tokenizer, chunk)
        before = tokenizer("passage: " + chunk["text"], truncation=False, padding=False)
        after = tokenizer("passage: " + chunk["text"], truncation=True,
                          max_length=512, padding=False)
        candidates.append({**pilot.compact_chunk(chunk), "tokens_before": tokens["tokens_before"],
                           "tokens_after": tokens["tokens_after"], "truncated": tokens["truncated"],
                           "input_ids_sha256": pilot.fingerprint(before["input_ids"]),
                           "retained_input_ids_sha256": pilot.fingerprint(after["input_ids"])})
    payload = {"schema_version": 1, "execution": "actual_pinned_e5_cpu_tokenization",
               "model_weights_loaded": False, "training_executed": False,
               "inputs_sha256": bindings, "source_sha256_lf": sources,
               "tokenizer": provenance, "max_length": 512, "query_prefix": "query: ",
               "passage_prefix": "passage: ", "questions": checks, "candidates": candidates,
               "selected_negatives": selected_negatives or {},
               "limitations": ["Token survival does not prove literal interval coverage or semantics.",
                               "Saved-receipt structural replay does not rerun tokenization."]}
    return {**payload, "payload_sha256": pilot.fingerprint(payload)}


def validate_token_receipt(receipt: dict, questions: list[dict], chunks: dict, review_packs: dict,
                           bindings: dict, sources: dict, spec: dict) -> dict:
    payload = {key: value for key, value in receipt.items() if key != "payload_sha256"}
    files = {name: value["sha256"] for name, value in spec["files"].items()
             if not name.endswith(".safetensors")}
    if (receipt.get("payload_sha256") != pilot.fingerprint(payload)
            or receipt.get("inputs_sha256") != bindings
            or receipt.get("source_sha256_lf") != sources
            or receipt.get("execution") != "actual_pinned_e5_cpu_tokenization"
            or receipt.get("max_length") != 512 or receipt.get("query_prefix") != "query: "
            or receipt.get("passage_prefix") != "passage: "
            or receipt.get("model_weights_loaded") is not False
            or receipt.get("training_executed") is not False
            or receipt.get("tokenizer", {}).get("verified_files_sha256") != files
            or receipt.get("tokenizer", {}).get("repo_id") != spec.get("repo_id")
            or receipt.get("tokenizer", {}).get("revision") != spec.get("revision")
            or not receipt.get("tokenizer", {}).get("class")
            or not receipt.get("tokenizer", {}).get("transformers_version")
            or not receipt.get("tokenizer", {}).get("tokenizers_version")
            or receipt.get("tokenizer", {}).get("is_fast") is not True
            or receipt.get("tokenizer", {}).get("truncation_side") != "right"):
        raise ValueError("Token receipt input, source, tokenizer or payload drift")
    expected_questions = {q["id"]: q for q in questions}
    checks = receipt.get("questions", [])
    if (len(checks) != len(questions)
            or {row["question_id"] for row in checks} != set(expected_questions)):
        raise ValueError("Token receipt must cover all questions exactly once")
    selected, failures = {}, []
    for check in checks:
        question = expected_questions[check["question_id"]]
        if check.get("compiled_question_sha256") != question_hash(question):
            raise ValueError("Token question checksum mismatch")
        positive_ids = sorted(question["positive_chunk_ids"],
                              key=lambda value: int(value.rsplit(":", 1)[1]))
        if [c["chunk_id"] for c in check["positives"]] != positive_ids:
            raise ValueError("Token receipt positive coverage/order mismatch")
        choices = []
        for positive in check["positives"]:
            chunk = chunks[positive["chunk_id"]]
            if any(positive.get(k) != v for k, v in pilot.compact_chunk(chunk).items()):
                raise ValueError("Token positive checksum mismatch")
            validate_token_counts(positive)
            visibility = positive["visibility"]
            before = visibility["overlapping_tokens_before"]
            after = visibility["overlapping_tokens_after"]
            retained = visibility["all_evidence_overlapping_tokens_retained"]
            if (type(before) is not int or type(after) is not int or not 0 <= after <= before
                    or visibility["evidence_tokens_lost_to_truncation"] != before - after
                    or retained != (visibility["full_source_span_in_chunk"]
                                    and before > 0 and before == after)):
                raise ValueError("Inconsistent token visibility evidence")
            if retained:
                choices.append(pilot.compact_chunk(chunk))
        query_tokens = check["query_tokens"]
        for field in ("query_input_ids_sha256", "query_retained_input_ids_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", check.get(field, "")):
                raise ValueError("Missing query token hash evidence")
        if type(query_tokens) is not int or query_tokens <= 0:
            raise ValueError("Invalid query token count")
        if check.get("selected_positive_chunk_id") != (choices[0]["chunk_id"] if choices else None):
            raise ValueError("Token selected positive differs from frozen earliest retained ordinal")
        if (not choices or query_tokens > 512
                or check.get("query_input_ids_sha256") !=
                check.get("query_retained_input_ids_sha256")):
            failures.append(question["id"])
        else:
            selected[question["id"]] = choices[0]
    expected_candidates = sorted({c["chunk_id"] for p in review_packs.values()
                                  for item in p["items"] for c in item["candidates"]})
    if [c["chunk_id"] for c in receipt.get("candidates", [])] != expected_candidates:
        raise ValueError("Token candidate coverage mismatch")
    for candidate in receipt["candidates"]:
        for field in ("input_ids_sha256", "retained_input_ids_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", candidate.get(field, "")):
                raise ValueError("Missing candidate token hash evidence")
        if any(candidate.get(k) != v for k, v in
               pilot.compact_chunk(chunks[candidate["chunk_id"]]).items()):
            raise ValueError("Token candidate checksum mismatch")
        validate_token_counts(candidate)
    return {"selected": selected, "failures": sorted(failures)}


def validate_token_counts(row: dict) -> None:
    before, after = row["tokens_before"], row["tokens_after"]
    if (type(before) is not int or type(after) is not int or before <= 0
            or after != min(before, 512) or row["truncated"] != (before > 512)):
        raise ValueError("Invalid tokenizer length/truncation evidence")


def public_safe(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"text", "content"}:
                raise ValueError("Full source text forbidden in public readiness artifacts")
            public_safe(key)
            public_safe(item)
    elif isinstance(value, list):
        for item in value:
            public_safe(item)
    elif isinstance(value, str) and (re.search(r"[A-Za-z]:[\\/]", value)
                                    or value.startswith(("/", "\\"))):
        raise ValueError("Absolute personal paths forbidden in public readiness artifacts")


def load_context(args, root: Path = ROOT) -> dict:
    bindings = {}
    readiness_raw = read_snapshot(args.readiness_plan, bindings, root)
    readiness = json.loads(readiness_raw)
    if (readiness.get("plan_id") != "m4-readiness-plan-v1"
            or readiness["negative_review"]["review_per_query"] != 4
            or readiness["negative_review"]["training_negative_count_per_fit_query"] != 2
            or any(readiness["negative_review"]["roles"][shard]["reviewer"] != reviewer(agent)
                   for shard, agent in SHARDS.items())):
        raise ValueError("Unsupported readiness plan")
    for name, digest in readiness["frozen_input_sha256"].items():
        if pilot.sha256(read_snapshot(root / name, bindings, root)) != digest:
            raise ValueError("Frozen input checksum drift: " + name)
    sources = source_hashes(root)
    if any(sources.get(name) != digest for name, digest
           in readiness["frozen_source_sha256_lf"].items()):
        raise ValueError("Frozen implementation source drift")
    parent_path = root / readiness["parent_plan_path"]
    plan, documents = pilot.load_inputs(parent_path, root)
    inventory = pilot.build_inventory(plan, documents, readiness["parent_plan_sha256"])
    if pilot.json_bytes(inventory) != (root / "data/training/m4-inventory-v3.json").read_bytes():
        raise ValueError("Frozen inventory replay mismatch")
    packs = {}
    for path in args.author_packs:
        raw = read_snapshot(path, bindings, root)
        packs[pilot.sha256(raw)] = json.loads(raw)
    drafts, draft_hashes = [], {}
    for path in args.drafts:
        raw = read_snapshot(path, bindings, root)
        if path.name in draft_hashes:
            raise ValueError("Duplicate draft filename")
        draft_hashes[path.name] = pilot.sha256(raw)
        drafts.extend(rows(raw))
    compiled = pilot.compile_dataset(plan, inventory, documents, packs, drafts, draft_hashes)
    for name, raw in compiled.items():
        if read_snapshot(args.pilot_dir / name, bindings, root) != raw:
            raise ValueError("Combined pilot differs from frozen compiler replay: " + name)
    questions = rows(compiled["questions.jsonl"])
    original = rows((root / "data/training/m4-pilot-v1/questions.jsonl").read_bytes())
    combined = {row["id"]: row for row in questions}
    if any(combined.get(row["id"]) != row for row in original):
        raise ValueError("Frozen original pilot question modified or removed")
    if args.command != "packs":
        extra = [q for q in questions if q["id"] not in {q["id"] for q in original}]
        if (len(questions) != 80 or {q["id"] for q in extra} != {"m4-cal-015", "m4-cal-016"}
                or any(q["partition"] != "calibration" or q["evidence"][0]["document_id"]
                       not in readiness["supplement"]["document_ids"] for q in extra)):
            raise ValueError("Combined pilot must preserve 78 plus selected calibration supplement")
        for question in extra:
            if packs[question["author_pack_sha256"]]["allowed_document_ids"] != \
                    readiness["supplement"]["document_ids"]:
                raise ValueError("Supplement author pack exceeds preregistered document scope")
    chunks = {chunk["chunk_id"]: chunk for chunk in pilot.chunks_for(documents)}
    review_packs = build_review_packs(questions, drafts, rows(compiled["negative-candidates.jsonl"]),
                                    chunks, plan, pilot.sha256(readiness_raw))
    return {"bindings": bindings, "sources": sources, "readiness": readiness,
            "plan": plan, "documents": documents, "chunks": chunks, "questions": questions,
            "drafts": drafts, "author_packs": packs, "review_packs": review_packs,
            "pilot_report": json.loads(compiled["report.json"])}


def load_reviews(args, context: dict, root: Path = ROOT) -> tuple[dict, dict]:
    if not args.positive_reviews or not args.negative_reviews:
        raise ValueError("Positive and negative review receipt paths are required")
    positives, negatives = [], []
    for path in args.positive_reviews:
        positives.extend(rows(read_snapshot(path, context["bindings"], root)))
    for path in args.negative_reviews:
        negatives.extend(rows(read_snapshot(path, context["bindings"], root)))
    positive = validate_positive_reviews(context["drafts"], positives, context["author_packs"])
    negative = validate_negative_reviews(context["review_packs"], negatives)
    for shard, pack in context["review_packs"].items():
        path = args.review_pack_dir / f"m4-negative-review-{shard.lower()}-v1.json"
        if read_snapshot(path, context["bindings"], root) != pilot.json_bytes(pack):
            raise ValueError("Local negative review pack replay mismatch")
    return positive, negative


def readiness_manifest(context: dict, positive: dict, negative: dict,
                        receipt: dict, token_result: dict, token_sha256: str) -> dict:
    negative_tokens = {row["chunk_id"]: row for row in receipt["candidates"]}
    truncations = sorted(identifier for identifier, selected in negative["selected"].items()
                         if any(negative_tokens[c["chunk_id"]]["truncated"]
                                or negative_tokens[c["chunk_id"]]["input_ids_sha256"] !=
                                negative_tokens[c["chunk_id"]]["retained_input_ids_sha256"]
                                for c in selected))
    if receipt.get("selected_negatives") != negative["selected"]:
        raise ValueError("Token receipt negative selection differs from independently reviewed rank")
    gates = {"pilot_data_gates": all(context["pilot_report"]["pilot_data_gates"].values()),
             "all_positive_reviews_accepted": positive["all_ai_accepted"],
             "two_reviewed_negatives_per_fit_question": not negative["shortfalls"],
             "all_query_and_positive_tokens_retained": not token_result["failures"],
             "selected_negative_inputs_untruncated": not truncations}
    questions = {q["id"]: q for q in context["questions"]}
    triplets = [{"question_id": identifier, "question_sha256": question_hash(questions[identifier]),
                 "positive": token_result["selected"].get(identifier),
                 "negatives": negative["selected"][identifier], "partition": "fit",
                 "eligible_for_training": all(gates.values())}
                for identifier in sorted(negative["selected"])]
    result = {"schema_version": 1, "scope": "provisional_ai_label_data_readiness",
              "data_ready": all(gates.values()), "probe_allowed": all(gates.values()),
              "resource_probe_result": "not_run", "training_ready": False,
              "training_executed": False, "human_review": "pending", "human_reviewed_questions": 0,
              "inputs_sha256": context["bindings"], "source_sha256_lf": context["sources"],
              "token_receipt_sha256": token_sha256,
              "validation_mode": "deterministic_structural_replay_of_saved_tokenization",
              "gates": gates, "counts": context["pilot_report"]["counts"],
              "positive_review_decisions": positive["decisions"],
              "negative_review_labels": negative["labels"],
              "excluded_rows_and_reasons": {"insufficient_reviewed_negatives": negative["shortfalls"],
                                           "query_or_positive_token_loss": token_result["failures"],
                                           "negative_truncation": truncations},
              "triplets": triplets,
              "calibration": [{"question_id": identifier,
                               "question_sha256": question_hash(questions[identifier]),
                               "positive": token_result["selected"].get(identifier)}
                              for identifier in sorted(questions)
                              if questions[identifier]["partition"] == "calibration"],
              "limitations": ["All labels are provisional AI reviews; human review is pending.",
                              "Saved receipt replay verifies structure and bindings, not tokenization anew.",
                              "No model resource probe, training or retrieval improvement is claimed.",
                              "Any failed row blocks the entire 64-question training denominator."]}
    public_safe(result)
    return result


def replay_manifest(args, context: dict | None = None, root: Path = ROOT) -> tuple[dict, dict]:
    """Rebuild deterministic manifest from validated source and saved token evidence."""
    context = context or load_context(args, root)
    positive, negative = load_reviews(args, context, root)
    spec = json.loads((root / "data/models/m3-models.json").read_bytes())["models"]["e5"]
    if not args.token_receipt:
        raise ValueError("--token-receipt is required")
    token_raw = args.token_receipt.read_bytes()
    receipt = json.loads(token_raw)
    if verify_tokenizer_files(args.e5_snapshot, spec) != \
            receipt.get("tokenizer", {}).get("verified_files_sha256"):
        raise ValueError("Actual local tokenizer files differ from saved receipt")
    token_result = validate_token_receipt(receipt, context["questions"], context["chunks"],
                                         context["review_packs"], context["bindings"],
                                         context["sources"], spec)
    context["bindings"][relative(args.token_receipt, root)] = pilot.sha256(token_raw)
    manifest = readiness_manifest(context, positive, negative, receipt, token_result,
                                  pilot.sha256(token_raw))
    return manifest, context


def load_ready_data(args, root: Path = ROOT) -> dict:
    """Fail closed before a separate resource probe; never load model weights here.

    args uses this module's parser fields, command='replay', and output is the
    saved training-manifest. The returned texts remain process-local. A successful
    return permits only the separate preregistered probe; it does not assert that
    training, a resource probe, or fresh tokenization has happened.
    """
    manifest, context = replay_manifest(args, root=root)
    if not args.output:
        raise ValueError("Saved training manifest required")
    relative(args.output, root)
    pilot.write_or_verify(args.output, pilot.json_bytes(manifest), verify=True)
    if not manifest["data_ready"] or not manifest["probe_allowed"]:
        raise ValueError("Data readiness gates failed; resource probe and training forbidden")
    return {"manifest": manifest, "questions": context["questions"],
            "chunks": context["chunks"], "plan": context["plan"]}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=("packs", "tokenize", "compile", "replay"))
    result.add_argument("--readiness-plan", type=Path,
                        default=ROOT / "data/training/m4-readiness-plan-v1.json")
    result.add_argument("--pilot-dir", type=Path, required=True)
    result.add_argument("--drafts", type=Path, nargs="+", required=True)
    result.add_argument("--author-packs", type=Path, nargs="+", required=True)
    result.add_argument("--positive-reviews", type=Path, nargs="+")
    result.add_argument("--negative-reviews", type=Path, nargs="+")
    result.add_argument("--review-pack-dir", type=Path, default=ROOT / ".local")
    result.add_argument("--e5-snapshot", type=Path, default=ROOT / "models/e5")
    result.add_argument("--token-receipt", type=Path)
    result.add_argument("--output", type=Path)
    result.add_argument("--verify", action="store_true",
                        help="Compare existing bytes; tokenize --verify reruns actual tokenization")
    return result


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    context = load_context(args)
    if args.command == "packs":
        if not args.review_pack_dir.resolve().is_relative_to((ROOT / ".local").resolve()):
            raise ValueError("Full-text review packs must remain inside .local")
        for shard, pack in context["review_packs"].items():
            path = args.review_pack_dir / f"m4-negative-review-{shard.lower()}-v1.json"
            pilot.write_or_verify(path, pilot.json_bytes(pack), args.verify)
        print(json.dumps({"review_candidates": 256, "independent_ai_review": "pending",
                          "data_ready": False, "training_executed": False}))
        return
    if not args.token_receipt:
        raise ValueError("--token-receipt is required")
    relative(args.token_receipt)
    if args.command == "tokenize":
        _, negative = load_reviews(args, context)
        spec = json.loads((ROOT / "data/models/m3-models.json").read_bytes())["models"]["e5"]
        tokenizer, provenance = open_tokenizer(args.e5_snapshot, spec)
        provenance.update({"repo_id": spec["repo_id"], "revision": spec["revision"],
                           "transformers_version": version("transformers"),
                           "tokenizers_version": version("tokenizers")})
        receipt = token_payload(context["questions"], context["chunks"], context["review_packs"],
                                tokenizer, provenance, dict(context["bindings"]), context["sources"],
                                negative["selected"])
        if verify_tokenizer_files(args.e5_snapshot, spec) != provenance["verified_files_sha256"]:
            raise ValueError("Tokenizer changed during execution")
        public_safe(receipt)
        pilot.write_or_verify(args.token_receipt, pilot.json_bytes(receipt), args.verify)
        print(json.dumps({"actual_cpu_tokenization": True, "questions": len(context["questions"]),
                          "model_weights_loaded": False, "training_executed": False}))
        return
    manifest, _ = replay_manifest(args, context)
    if not args.output:
        raise ValueError("--output training-manifest path is required")
    relative(args.output)
    pilot.write_or_verify(args.output, pilot.json_bytes(manifest),
                          args.verify or args.command == "replay")
    print(json.dumps({key: manifest[key] for key in
                      ("data_ready", "probe_allowed", "training_ready", "training_executed", "gates")}))


if __name__ == "__main__":
    main()
