"""Additive M4 readiness replay, with independent review of actual truncated inputs.

Only ``tokenize`` loads the pinned CPU tokenizer. Full text and token views stay
under .local. Saved evidence replay is structural verification, not fresh review.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from importlib.metadata import version
from pathlib import Path

from scripts import prepare_training as pilot
from scripts import prepare_training_ready as v1
from scripts.validate_training_reviews import question_hash

ROOT = pilot.ROOT
SOURCE = "scripts/prepare_training_ready_v2.py"
TARGET = "m4-fit-048"
PLAN_SHA256 = "aa6464441d7c02b14977ab79656b3c48d57a1a4a0af5a29f9186a520d7a5405c"


def ordered_reviews(pack: dict, events: list[dict], scope: str) -> dict:
    """Require exact ordered receipt coverage, including role and all context hashes."""
    expected = []
    for item in pack["items"]:
        for candidate in item["candidates"]:
            binding = {**v1.event_binding(pack, item, candidate), "review_scope": scope}
            expected.append(binding)
    if len(events) != len(expected):
        raise ValueError("Review coverage missing/extra/duplicate")
    for event, binding in zip(events, expected, strict=True):
        if set(event) != set(binding) | {"label", "reason"}:
            raise ValueError("Review receipt schema mismatch")
        if any(event.get(k) != value for k, value in binding.items()):
            raise ValueError("Review binding or order mismatch")
        if (event["label"] not in v1.LABELS or not isinstance(event["reason"], str)
                or not event["reason"].strip()):
            raise ValueError("Review requires explicit label and reason")
    return {(e["question_id"], e["candidate_chunk_id"]): e for e in events}


def supplement_pack(context: dict, candidates: list[dict]) -> dict:
    plan = context["v2_plan"]
    contract = plan["supplemental_negative_review"]
    if (contract["question_id"] != TARGET or contract["skip_first_eligible"] != 4
            or contract["take_next_eligible"] != 4
            or contract["reviewer"] != v1.reviewer("m4_supp_author")):
        raise ValueError("Unsupported supplemental selection contract")
    pool = sorted((c for c in candidates if c["question_id"] == TARGET
                   and c["status"] == "unreviewed"), key=lambda c: (c["rank"], c["chunk_id"]))
    selected = pool[4:8]
    if len(selected) != 4 or selected != contract["selected_candidates"]:
        raise ValueError("Supplement must be the preregistered next four original candidates")
    old = next(item for p in context["review_packs"].values() for item in p["items"]
               if item["question"]["id"] == TARGET)
    if pool[:4] != [{k: value for k, value in c.items()
                     if k not in {"text", "candidate_sha256"}} for c in old["candidates"]]:
        raise ValueError("Original first four candidates changed")
    for c in selected:
        v1.verify_ref(c, context["chunks"], "fit", context["plan"])
        if (c["partition"] != "fit" or c["quarantine_reasons"] or c["negative_label"] is not None
                or c["semantic_review"] != "pending" or c["human_review"] != "pending"
                or c["eligible_for_training"] is not False
                or c["chunk_id"] in old["question"]["positive_chunk_ids"]):
            raise ValueError("Unsafe supplemental candidate")
    item = {**old, "candidates": [{**c, "candidate_sha256": question_hash(c),
                                  "text": context["chunks"][c["chunk_id"]]["text"]}
                                 for c in selected]}
    return {"schema_version": 2, "readiness_plan_sha256": context["v2_plan_sha256"],
            "reviewer": contract["reviewer"], "human_review": "pending", "items": [item]}


def select_negatives(manifest: dict, pack: dict, events: list[dict]) -> dict:
    labels = ordered_reviews(pack, events, "supplemental_full_context")
    selected = {t["question_id"]: copy.deepcopy(t["negatives"]) for t in manifest["triplets"]}
    if list(selected) != [f"m4-fit-{i:03d}" for i in range(1, 65)] or selected[TARGET]:
        raise ValueError("Frozen v1 selection must contain 64 questions and zero for fit-048")
    selected[TARGET] = [pilot.compact_chunk(c) for c in pack["items"][0]["candidates"]
                        if labels[(TARGET, c["chunk_id"])]["label"] == "negative"][:2]
    return selected


def validate_view(view: dict, source: str) -> None:
    fields = {"full_input_ids", "retained_input_ids", "full_offsets", "retained_offsets",
              "decoded_retained_input", "special_tokens_mask_full", "special_tokens_mask_retained",
              "retained_attention_mask", "offset_visible_source"}
    if set(view) != fields or not isinstance(view["decoded_retained_input"], str):
        raise ValueError("Actual token view schema mismatch")
    for prefix, mask_name in (("full", "full"), ("retained", "retained")):
        ids, offsets = view[f"{prefix}_input_ids"], view[f"{prefix}_offsets"]
        masks = view[f"special_tokens_mask_{mask_name}"]
        if not ids or len(ids) != len(offsets) or len(ids) != len(masks):
            raise ValueError("Token view lengths inconsistent")
        for token, offset, mask in zip(ids, offsets, masks, strict=True):
            if (type(token) is not int or token < 0 or type(mask) is not int or mask not in {0, 1}
                    or not isinstance(offset, list) or len(offset) != 2
                    or any(type(x) is not int for x in offset)
                    or not 0 <= offset[0] <= offset[1] <= len(source)
                    or (mask and offset != [0, 0])):
                raise ValueError("Invalid actual token ID, offset or special-token mask")
    full, retained = view["full_input_ids"], view["retained_input_ids"]
    if len(retained) != min(len(full), 512):
        raise ValueError("Token view max-length mismatch")
    before = [(t, o) for t, o, m in zip(full, view["full_offsets"],
                                      view["special_tokens_mask_full"], strict=True) if not m]
    after = [(t, o) for t, o, m in zip(retained, view["retained_offsets"],
                                     view["special_tokens_mask_retained"], strict=True) if not m]
    if after != before[:len(after)] or (len(full) <= 512 and full != retained):
        raise ValueError("Retained token view differs from right truncation prefix")
    if (view["retained_attention_mask"] != [1] * len(retained)
            or any(type(x) is not int for x in view["retained_attention_mask"])
            or view["offset_visible_source"] != visible_source(view, source[9:])):
        raise ValueError("Actual input attention mask or source prefix mismatch")


def visible_source(view: dict, text: str) -> dict:
    end = max((o[1] for o, m in zip(view["retained_offsets"],
                                  view["special_tokens_mask_retained"], strict=True) if not m),
              default=9)
    end = max(0, min(len(text), end - 9))
    return {"start_offset": 0, "end_offset": end, "text": text[:end],
            "interpretation": "Exact source prefix associated with retained token offsets; "
                              "not decoder output or proof every character was encoded."}


def token_row(chunk: dict, view: dict) -> dict:
    validate_view(view, "passage: " + chunk["text"])
    return {**pilot.compact_chunk(chunk), "tokens_before": len(view["full_input_ids"]),
            "tokens_after": len(view["retained_input_ids"]),
            "truncated": len(view["full_input_ids"]) > 512,
            "input_ids_sha256": pilot.fingerprint(view["full_input_ids"]),
            "retained_input_ids_sha256": pilot.fingerprint(view["retained_input_ids"]),
            "model_input_sha256": pilot.fingerprint({"input_ids": view["retained_input_ids"],
                                                     "attention_mask": view["retained_attention_mask"]}),
            "retained_offsets_sha256": pilot.fingerprint(view["retained_offsets"]),
            "special_tokens_mask_retained_sha256": pilot.fingerprint(view["special_tokens_mask_retained"]),
            "decoded_retained_input_sha256": pilot.sha256(view["decoded_retained_input"].encode()),
            "offset_visible_source_sha256": pilot.sha256(view["offset_visible_source"]["text"].encode()),
            "offset_visible_source_end": view["offset_visible_source"]["end_offset"],
            "view_sha256": pilot.fingerprint(view)}


def actual_view(tokenizer, text: str) -> dict:
    options = {"padding": False, "return_offsets_mapping": True,
               "return_special_tokens_mask": True}
    before = tokenizer("passage: " + text, truncation=False, **options)
    after = tokenizer("passage: " + text, truncation=True, max_length=512, **options)
    view = {"full_input_ids": before["input_ids"], "retained_input_ids": after["input_ids"],
            "full_offsets": [list(o) for o in before["offset_mapping"]],
            "retained_offsets": [list(o) for o in after["offset_mapping"]],
            "special_tokens_mask_full": before["special_tokens_mask"],
            "special_tokens_mask_retained": after["special_tokens_mask"],
            "retained_attention_mask": after["attention_mask"],
            "decoded_retained_input": tokenizer.decode(after["input_ids"],
                                                        skip_special_tokens=True,
                                                        clean_up_tokenization_spaces=False)}
    view["offset_visible_source"] = visible_source(view, text)
    return view


def truncated_pack(context: dict, selected: dict, token_rows: list[dict], views: dict,
                   payload_sha256: str) -> dict:
    rows = {r["chunk_id"]: r for r in token_rows}
    old_items = {i["question"]["id"]: i for p in context["review_packs"].values()
                 for i in p["items"]}
    items = []
    for qid, refs in selected.items():
        original = old_items[qid]
        candidates = original["candidates"] + (context["supplement_pack"]["items"][0]["candidates"]
                                               if qid == TARGET else [])
        for ref in refs:
            cid = ref["chunk_id"]
            if rows[cid]["truncated"]:
                candidate = next(c for c in candidates if c["chunk_id"] == cid)
                items.append({**{k: v for k, v in original.items() if k != "candidates"},
                              "candidate": candidate, "token_evidence": rows[cid],
                              "actual_view": views[cid],
                              "full_context_review": context["full_reviews"][(qid, cid)],
                              "full_context_review_sha256": question_hash(context["full_reviews"][(qid, cid)])})
    return {"schema_version": 2, "readiness_plan_sha256": context["v2_plan_sha256"],
            "reviewer": v1.reviewer("m4_gate_design"), "human_review": "pending", "items": items,
            "token_payload_sha256": payload_sha256}


def local_path(value: str, root: Path = ROOT) -> Path:
    path = root / value
    if not path.resolve().is_relative_to((root / ".local").resolve()):
        raise ValueError("Full context and token views must remain under .local")
    return path


def load_context(args, root: Path = ROOT) -> dict:
    bindings = {}
    raw = v1.read_snapshot(args.readiness_plan, bindings, root)
    plan = json.loads(raw)
    if plan.get("plan_id") != "m4-readiness-plan-v2" or pilot.sha256(raw) != PLAN_SHA256:
        raise ValueError("Unsupported readiness plan")
    for name, digest in plan["frozen_input_sha256"].items():
        if pilot.sha256(v1.read_snapshot(root / name, bindings, root)) != digest:
            raise ValueError("Frozen v2 dependency drift: " + name)
    sources = v1.source_hashes(root)
    if plan["frozen_source_sha256_lf"] != sources:
        raise ValueError("Frozen v1 implementation changed")
    original = copy.copy(args)
    original.command = "replay"
    original.readiness_plan = root / plan["parent_readiness_plan_path"]
    original.token_receipt = args.v1_token_receipt
    original.output = args.v1_manifest
    manifest, context = v1.replay_manifest(original, root=root)
    manifest_raw = v1.read_snapshot(args.v1_manifest, bindings, root)
    if manifest_raw != pilot.json_bytes(manifest):
        raise ValueError("Frozen v1 manifest replay mismatch")
    if (manifest["data_ready"] or manifest["counts"]["fit"]["questions"] != 64
            or manifest["counts"]["calibration"]["questions"] != 16
            or manifest["negative_review_labels"] != {"negative": 244, "relevant": 4, "ambiguous": 8}
            or manifest["excluded_rows_and_reasons"]["insufficient_reviewed_negatives"] != [TARGET]
            or len(manifest["excluded_rows_and_reasons"]["negative_truncation"]) != 12
            or manifest["excluded_rows_and_reasons"]["query_or_positive_token_loss"]
            or not manifest["gates"]["all_query_and_positive_tokens_retained"]
            or manifest["excluded_rows_and_reasons"] !=
            plan["observed_v1_failure"]["excluded_rows_and_reasons"]):
        raise ValueError("Unexpected v1 baseline; new design required")
    bindings.update(context["bindings"])
    sources[SOURCE] = pilot.sha256((root / SOURCE).read_bytes().replace(b"\r\n", b"\n"))
    context.update(bindings=bindings, sources=sources, v2_plan=plan,
                   v2_plan_sha256=pilot.sha256(raw), v1_manifest=manifest,
                   v1_receipt=json.loads(args.v1_token_receipt.read_bytes()))
    candidates = v1.rows(v1.read_snapshot(root / plan["supplemental_negative_review"]["candidate_source"],
                                         bindings, root))
    context["supplement_pack"] = supplement_pack(context, candidates)
    return context


def load_supplement(context: dict, root: Path = ROOT) -> dict:
    contract = context["v2_plan"]["supplemental_negative_review"]
    pack = context["supplement_pack"]
    if v1.read_snapshot(local_path(contract["pack_path"], root), context["bindings"], root) != \
            pilot.json_bytes(pack):
        raise ValueError("Supplemental review pack replay mismatch")
    events = v1.rows(v1.read_snapshot(root / contract["receipt_path"], context["bindings"], root))
    selected = select_negatives(context["v1_manifest"], pack, events)
    original = []
    for name in context["v1_manifest"]["inputs_sha256"]:
        if name.startswith("data/training/reviews/m4-negative-"):
            original.extend(v1.rows(v1.read_snapshot(root / name, context["bindings"], root)))
    context["full_reviews"] = {(e["question_id"], e["candidate_chunk_id"]): e
                               for e in [*original, *events]}
    context["supplement_labels"] = dict(sorted(Counter(e["label"] for e in events).items()))
    for qid, refs in selected.items():
        if any(context["full_reviews"][(qid, ref["chunk_id"])]["label"] != "negative" for ref in refs):
            raise ValueError("Selected full-context label must be negative")
    return selected


def selected_ids(selected: dict) -> list[str]:
    return sorted({c["chunk_id"] for refs in selected.values() for c in refs})


def seal(payload: dict) -> dict:
    return {**copy.deepcopy(payload), "payload_sha256": pilot.fingerprint(payload)}


def token_receipt(context: dict, selected: dict, views: dict, provenance: dict) -> dict:
    return seal({"schema_version": 2, "execution": "actual_pinned_e5_cpu_tokenization",
                 "model_weights_loaded": False, "training_executed": False,
                 "inputs_sha256": dict(context["bindings"]), "source_sha256_lf": context["sources"],
                 "tokenizer": provenance, "max_length": 512, "query_prefix": "query: ",
                 "passage_prefix": "passage: ", "selected_negatives": selected,
                 "question_evidence_scope": "carried_forward_exact_frozen_v1_query_and_positive_token_evidence",
                 "questions": context["v1_receipt"]["questions"],
                 "views_sha256": pilot.fingerprint(views),
                 "candidates": [token_row(context["chunks"][cid], views[cid])
                                for cid in selected_ids(selected)]})


def validate_tokens(context: dict, selected: dict, receipt: dict, spec: dict) -> None:
    payload = receipt["payload"]
    if set(payload) != {"schema_version", "execution", "model_weights_loaded", "training_executed",
                        "inputs_sha256", "source_sha256_lf", "tokenizer", "max_length", "query_prefix",
                        "passage_prefix", "selected_negatives", "questions", "views_sha256", "candidates",
                        "payload_sha256", "question_evidence_scope"}:
        raise ValueError("Token payload schema mismatch")
    for digest in (payload["views_sha256"], receipt["actual_review_pack_sha256"]):
        if (not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)):
            raise ValueError("Invalid saved view/pack hash")
    if [r["chunk_id"] for r in payload["candidates"]] != selected_ids(selected):
        raise ValueError("Actual token candidate coverage or order mismatch")
    for row in payload["candidates"]:
        ref = pilot.compact_chunk(context["chunks"][row["chunk_id"]])
        if any(row.get(k) != value for k, value in ref.items()):
            raise ValueError("Actual token candidate source drift")
        v1.validate_token_counts(row)
        hashes = ["input_ids_sha256", "retained_input_ids_sha256", "model_input_sha256", "view_sha256",
                  "retained_offsets_sha256", "special_tokens_mask_retained_sha256",
                  "decoded_retained_input_sha256", "offset_visible_source_sha256"]
        if set(row) != set(ref) | set(hashes) | {"tokens_before", "tokens_after", "truncated", "offset_visible_source_end"}:
            raise ValueError("Actual token candidate schema mismatch")
        if any(not isinstance(row[k], str) or len(row[k]) != 64
               or any(c not in "0123456789abcdef" for c in row[k]) for k in hashes):
            raise ValueError("Invalid token hash")
        if not row["truncated"] and row["input_ids_sha256"] != row["retained_input_ids_sha256"]:
            raise ValueError("Untruncated full/retained input mismatch")
        end = row["offset_visible_source_end"]
        text = context["chunks"][row["chunk_id"]]["text"]
        if (type(end) is not int or not 0 <= end <= len(text)
                or row["offset_visible_source_sha256"] != pilot.sha256(text[:end].encode())):
            raise ValueError("Visible source prefix hash mismatch")
        old = next((r for r in context["v1_receipt"]["candidates"] if r["chunk_id"] == row["chunk_id"]), None)
        if old and any(row[k] != old[k] for k in old):
            raise ValueError("Frozen v1 candidate token evidence changed")
    expected = seal({**{k: value for k, value in payload.items() if k != "payload_sha256"},
                     "inputs_sha256": dict(context["bindings"]),
                     "source_sha256_lf": context["sources"], "selected_negatives": selected,
                     "schema_version": 2, "execution": "actual_pinned_e5_cpu_tokenization",
                     "model_weights_loaded": False, "training_executed": False,
                     "questions": context["v1_receipt"]["questions"],
                     "question_evidence_scope": "carried_forward_exact_frozen_v1_query_and_positive_token_evidence",
                     "max_length": 512, "query_prefix": "query: ", "passage_prefix": "passage: "})
    files = {name: value["sha256"] for name, value in spec["files"].items()
             if not name.endswith(".safetensors")}
    tokenizer = payload.get("tokenizer", {})
    if (payload != expected or tokenizer.get("verified_files_sha256") != files
            or tokenizer.get("repo_id") != spec["repo_id"]
            or tokenizer.get("revision") != spec["revision"]
            or tokenizer.get("is_fast") is not True or tokenizer.get("truncation_side") != "right"
            or not all(tokenizer.get(k) for k in ("class", "transformers_version", "tokenizers_version"))):
        raise ValueError("Actual token receipt input/source/view/tokenizer drift")
    if tokenizer != context["v2_plan"]["actual_tokenization"]["tokenizer_provenance"]:
        raise ValueError("Tokenizer provenance changed from the frozen v1 execution")


def build_manifest(context: dict, selected: dict, receipt: dict, events: list[dict]) -> dict:
    labels = {(e["question_id"], e["candidate_chunk_id"]): e for e in events}
    rejected = [{"question_id": qid, "candidate_chunk_id": cid, "label": event["label"]}
                for (qid, cid), event in labels.items() if event["label"] != "negative"]
    shortfalls = [qid for qid, refs in selected.items() if len(refs) != 2]
    old = context["v1_manifest"]
    gates = {"frozen_v1_replayed": True,
             "pilot_data_gates": old["gates"]["pilot_data_gates"],
             "all_positive_reviews_accepted": old["gates"]["all_positive_reviews_accepted"],
             "all_query_and_positive_tokens_retained": old["gates"]["all_query_and_positive_tokens_retained"],
             "two_reviewed_negatives_per_fit_question": not shortfalls,
             "all_truncated_negative_inputs_independently_negative": not rejected}
    ready = all(gates.values())
    result = {"schema_version": 2, "scope": "provisional_ai_label_data_readiness",
              "data_ready": ready, "probe_allowed": ready, "training_ready": False,
              "resource_probe_result": "not_run", "training_executed": False,
              "human_review": "pending", "human_reviewed_questions": 0,
              "counts": old["counts"], "gates": gates,
              "inputs_sha256": context["bindings"], "source_sha256_lf": context["sources"],
              "v1_failure_preserved": old["excluded_rows_and_reasons"],
              "v1_negative_review_labels": old["negative_review_labels"],
              "supplemental_negative_review_labels": context["supplement_labels"],
              "truncated_input_review_labels": dict(sorted(Counter(e["label"] for e in events).items())),
              "excluded_rows_and_reasons": {"insufficient_reviewed_negatives": shortfalls,
                                           "truncated_input_not_negative": rejected},
              "triplets": [{**t, "negatives": selected[t["question_id"]], "eligible_for_training": ready}
                           for t in old["triplets"]], "calibration": old["calibration"],
              "token_candidates": receipt["payload"]["candidates"],
              "validation_mode": "deterministic_structural_replay_of_saved_tokenization",
              "limitations": ["All semantic labels are independent provisional AI reviews; no human review.",
                              "Saved receipt replay does not rerun tokenization or establish semantic truth.",
                              "Fresh model-free replay validates saved hashes and bindings; it cannot regenerate actual token views.",
                              "Any failure blocks all 64 fit questions; all 80 questions remain in the denominator.",
                              "No resource probe, training, retrieval improvement or Java performance is claimed."]}
    v1.public_safe(result)
    return result


def actual_bindings(context: dict, selected: dict, receipt: dict) -> list[dict]:
    """Rebuild public pair bindings using source context, without loading token views."""
    rows = {r["chunk_id"]: r for r in receipt["payload"]["candidates"]}
    items = {i["question"]["id"]: i for p in context["review_packs"].values() for i in p["items"]}
    pack = {"readiness_plan_sha256": context["v2_plan_sha256"],
            "reviewer": v1.reviewer("m4_gate_design")}
    bindings = []
    for qid, refs in selected.items():
        item = items[qid]
        pool = item["candidates"] + (context["supplement_pack"]["items"][0]["candidates"]
                                      if qid == TARGET else [])
        for ref in refs:
            cid = ref["chunk_id"]
            row = rows[cid]
            if not row["truncated"]:
                continue
            candidate = next(c for c in pool if c["chunk_id"] == cid)
            binding = v1.event_binding(pack, item, candidate, receipt["actual_review_pack_sha256"])
            binding.update(review_scope="actual_truncated_model_input",
                           token_view_sha256=row["view_sha256"],
                           model_input_sha256=row["model_input_sha256"],
                           retained_input_ids_sha256=row["retained_input_ids_sha256"],
                           full_context_review_sha256=question_hash(context["full_reviews"][(qid, cid)]))
            del binding["review_pack_sha256"]
            del binding["readiness_plan_sha256"]
            bindings.append(binding)
    return bindings


def finalize_receipt(context: dict, selected: dict, payload: dict, pack: dict) -> dict:
    receipt = {"schema_version": 2, "payload": payload,
               "actual_review_pack_sha256": pilot.fingerprint(pack)}
    receipt["actual_review_bindings"] = actual_bindings(context, selected, receipt)
    return receipt


def validate_actual_reviews(context: dict, selected: dict, receipt: dict,
                            receipt_sha256: str, events: list[dict]) -> None:
    expected = actual_bindings(context, selected, receipt)
    if set(receipt) != {"schema_version", "payload", "actual_review_pack_sha256", "actual_review_bindings"}:
        raise ValueError("Actual review receipt schema mismatch")
    if receipt["schema_version"] != 2 or receipt["actual_review_bindings"] != expected:
        raise ValueError("Public actual-review pair bindings drift")
    if len(events) != len(expected):
        raise ValueError("Actual review coverage missing/extra/duplicate")
    for event, binding in zip(events, expected, strict=True):
        binding = {**binding, "token_receipt_sha256": receipt_sha256,
                   "review_pack_sha256": receipt["actual_review_pack_sha256"],
                   "readiness_plan_sha256": context["v2_plan_sha256"]}
        if set(event) != set(binding) | {"label", "reason"}:
            raise ValueError("Actual review schema mismatch")
        if any(event.get(k) != value for k, value in binding.items()):
            raise ValueError("Actual review binding or order mismatch")
        if (event["label"] not in v1.LABELS or not isinstance(event["reason"], str)
                or not event["reason"].strip()):
            raise ValueError("Actual review needs explicit label and reason")


def verify_local_pack(context: dict, selected: dict, receipt: dict, root: Path = ROOT,
                      required: bool = False) -> bool:
    path = local_path(context["v2_plan"]["actual_truncated_review"]["pack_path"], root)
    if not path.exists():
        if required:
            raise ValueError("Actual local truncated review pack required before resource probe")
        return False
    raw = path.read_bytes()
    pack = json.loads(raw)
    if pilot.sha256(raw) != receipt["actual_review_pack_sha256"]:
        raise ValueError("Local actual review pack hash drift")
    views = {}
    for item in pack["items"]:
        candidate = item["candidate"]
        cid = candidate["chunk_id"]
        view = item["actual_view"]
        if token_row(context["chunks"][cid], view) != item["token_evidence"]:
            raise ValueError("Local actual model input view drift")
        if cid in views and views[cid] != view:
            raise ValueError("Inconsistent repeated actual token view")
        views[cid] = view
    expected = truncated_pack(context, selected, receipt["payload"]["candidates"], views,
                              receipt["payload"]["payload_sha256"])
    if pack != expected:
        raise ValueError("Local actual review context/order replay mismatch")
    return True


def replay_manifest(args, context: dict | None = None, root: Path = ROOT) -> tuple[dict, dict]:
    context = context or load_context(args, root)
    selected = load_supplement(context, root)
    raw = args.token_receipt.read_bytes()
    receipt = json.loads(raw)
    spec = json.loads((root / "data/models/m3-models.json").read_bytes())["models"]["e5"]
    if v1.verify_tokenizer_files(args.e5_snapshot, spec) != \
            receipt["payload"]["tokenizer"]["verified_files_sha256"]:
        raise ValueError("Actual local tokenizer file drift")
    validate_tokens(context, selected, receipt, spec)
    contract = context["v2_plan"]["actual_truncated_review"]
    events = v1.rows(v1.read_snapshot(root / contract["receipt_path"], context["bindings"], root))
    validate_actual_reviews(context, selected, receipt, pilot.sha256(raw), events)
    verify_local_pack(context, selected, receipt, root)
    context["bindings"][v1.relative(args.token_receipt, root)] = pilot.sha256(raw)
    context["bindings"][contract["pack_path"]] = receipt["actual_review_pack_sha256"]
    context["selected_negatives"], context["v2_receipt"] = selected, receipt
    return build_manifest(context, selected, receipt, events), context


def load_ready_data(args, root: Path = ROOT) -> dict:
    manifest, context = replay_manifest(args, root=root)
    pilot.write_or_verify(args.output, pilot.json_bytes(manifest), verify=True)
    verify_local_pack(context, context["selected_negatives"], context["v2_receipt"], root, required=True)
    if not manifest["data_ready"] or not manifest["probe_allowed"]:
        raise ValueError("Data readiness failed; resource probe and training forbidden")
    return {"manifest": manifest, "questions": context["questions"], "chunks": context["chunks"],
            "plan": context["plan"], "negative_model_input_sha256":
            {r["chunk_id"]: r["model_input_sha256"] for r in manifest["token_candidates"]}}


def parser():
    result = v1.parser()
    result.description = __doc__
    result.set_defaults(readiness_plan=ROOT / "data/training/m4-readiness-plan-v2.json",
                        token_receipt=ROOT / "data/training/m4-tokenizer-receipt-v2.json",
                        output=ROOT / "data/training/m4-training-manifest-v2.json")
    result.add_argument("--v1-manifest", type=Path, default=ROOT / "data/training/m4-training-manifest-v1.json")
    result.add_argument("--v1-token-receipt", type=Path, default=ROOT / "data/training/m4-tokenizer-receipt-v1.json")
    return result


def preflight_token_outputs(receipt_path: Path, pack_path: Path, verify: bool) -> None:
    if receipt_path.resolve() == pack_path.resolve():
        raise ValueError("Token receipt and private pack must have distinct output paths")
    for path in (receipt_path, pack_path):
        if verify and not path.is_file():
            raise ValueError("Verify requires both existing token receipt and private pack")
        if not verify and path.exists():
            raise ValueError("Token output already exists; use --verify without overwriting")


def write_token_outputs(receipt_path: Path, receipt: dict, pack_path: Path,
                         pack: dict, verify: bool) -> None:
    preflight_token_outputs(receipt_path, pack_path, verify)
    # Publish the final public receipt only after its complete private context exists.
    pilot.write_or_verify(pack_path, pilot.json_bytes(pack), verify)
    pilot.write_or_verify(receipt_path, pilot.json_bytes(receipt), verify)


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    context = load_context(args)
    if args.command == "packs":
        path = local_path(context["v2_plan"]["supplemental_negative_review"]["pack_path"])
        pilot.write_or_verify(path, pilot.json_bytes(context["supplement_pack"]), args.verify)
        print(json.dumps({"supplement_review_candidates": 4, "data_ready": False}))
        return
    if args.command == "tokenize":
        selected = load_supplement(context)
        path = local_path(context["v2_plan"]["actual_truncated_review"]["pack_path"])
        v1.relative(args.token_receipt)
        preflight_token_outputs(args.token_receipt, path, args.verify)
        spec = json.loads((ROOT / "data/models/m3-models.json").read_bytes())["models"]["e5"]
        tokenizer, provenance = v1.open_tokenizer(args.e5_snapshot, spec)
        provenance.update(repo_id=spec["repo_id"], revision=spec["revision"],
                          transformers_version=version("transformers"), tokenizers_version=version("tokenizers"))
        views = {cid: actual_view(tokenizer, context["chunks"][cid]["text"])
                 for cid in selected_ids(selected)}
        payload = token_receipt(context, selected, views, provenance)
        pack = truncated_pack(context, selected, payload["candidates"], views, payload["payload_sha256"])
        receipt = finalize_receipt(context, selected, payload, pack)
        validate_tokens(context, selected, receipt, spec)
        if v1.verify_tokenizer_files(args.e5_snapshot, spec) != provenance["verified_files_sha256"]:
            raise ValueError("Tokenizer changed during actual execution")
        v1.public_safe(receipt)
        write_token_outputs(args.token_receipt, receipt, path, pack, args.verify)
        print(json.dumps({"actual_cpu_tokenization": True, "truncated_pairs": len(pack["items"]),
                          "model_weights_loaded": False, "training_executed": False}))
        return
    manifest, _ = replay_manifest(args, context)
    v1.relative(args.output)
    pilot.write_or_verify(args.output, pilot.json_bytes(manifest), args.verify or args.command == "replay")
    print(json.dumps({k: manifest[k] for k in ("data_ready", "probe_allowed", "training_ready", "gates")}))


if __name__ == "__main__":
    main()
