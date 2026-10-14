"""Once-only C3 stage-1 offline preparation; stage 2 stays dynamic_unmeasured.

Freeze envelopes use schema_version/candidate/phase/kind/bound_files/files.
`files` maps roles to repository-relative paths, all present in bound_files:
source: manifest, inventory, processing_receipt, prereview, java_parity; item: draft, oracle,
context_selection, prereview, source_freeze, code_freeze. Source/item prereviews
declare reviewer_id, author_ids, accepted_ids, rejected_ids, verdict=accepted,
human_review_count=0; item also declares whole_family_absence_checked=true.
Each source declares adoption_author_role; source prereview author_ids must equal
these roles plus synthetic_provenance.author_role for synthetic originals.
Source inventories are the existing literal-text helper's complete output.
Data references must be under data/evaluation/meetings-c3-{phase}-*/ or
.local/meetings-c3-{phase}-*/; unrelated pools are rejected before body reads.
Preparation verifies receipts, not the truth of their human/AI semantic judgments.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from doctrail.meeting_answer_blocks import build_block_catalog
from doctrail.meeting_answer_requirements import (
    ANSWER_POLICY,
    requirement_messages,
    requirement_plan_grammar,
)
from doctrail.meeting_contract import AnswerRequest, strict_json
from doctrail.meeting_gguf import GREEDY, MAX_REQUEST_BYTES
from doctrail.meeting_input_budget import MAX_INPUT_TOKENS, MAX_NEW_TOKENS
from doctrail.meeting_requirements_review import (
    COUNTS,
    FAMILIES,
    SOURCE_LANGUAGES,
    validate_oracles,
)
from scripts.prepare_meeting_budget_inputs import (
    BYTE_LIMIT,
    _tokenizer_metadata,
    canonical,
    encoded,
    sha,
    snapshot,
    stamp,
)
from scripts.prepare_meeting_plaintext_source_inventory import (
    CHUNK_CONTRACT,
    HELPER_FILES,
    SERVICE_FILES,
    document_record,
)

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_FREEZE = "data/evaluation/meetings-c3-candidate-source-freeze-v1.json"
CANDIDATE_FREEZE_SHA256 = "6ce55cb17d264f8da7c587c685947da8d95ff1199ef65f7f34de7d1a275798c6"
TOOLCHAIN_FREEZE = "data/evaluation/meetings-c3-toolchain-source-freeze-v1.json"
CONTRACT = "docs/MEETINGS-C3-EXECUTION-CONTRACT.md"
CONTRACT_SHA256 = "25258b88f8cfba96a70ff24f5803d113ede7c405fe5b41238d685ffb863758b7"
REGISTRY = "data/evaluation/meetings-c3-family-registry-v1.json"
NEW_FILES = {"src/doctrail/meeting_requirements_review.py", "tests/test_meeting_requirements_review.py",
    "scripts/prepare_meeting_requirements_inputs.py", "tests/test_prepare_meeting_requirements_inputs.py",
    "scripts/probe_meeting_requirements.py", "tests/test_probe_meeting_requirements.py",
    "scripts/audit_meeting_requirements.py", "tests/test_audit_meeting_requirements.py"}
JAVA_PARITY_FILES = {"server/src/main/java/io/doctrail/Ingest.java",
    "server/src/main/java/io/doctrail/Retrieval.java", "server/src/test/java/io/doctrail/MeetingSourceParityTest.java"}
REUSED_FILES = {"src/doctrail/meeting_comparison_review.py", "src/doctrail/meeting_answer_review.py",
    "scripts/prepare_meeting_budget_inputs.py", "scripts/check_meeting_review_token_budget.py",
    "scripts/prepare_meeting_source_inventory.py", "scripts/prepare_meeting_plaintext_source_inventory.py",
    "src/doctrail/ingest.py", "src/doctrail/retrieval.py"} | SERVICE_FILES | HELPER_FILES | JAVA_PARITY_FILES
ROLES = {"source": {"manifest", "inventory", "processing_receipt", "prereview", "java_parity"},
         "item": {"draft", "oracle", "context_selection", "prereview", "source_freeze", "code_freeze"}}


class PreparationError(ValueError):
    """Safe fixed error codes only."""


def contained(path, *, root=None, output=False):
    root = Path(root or ROOT).resolve()
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


def relative(name, root=None):
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or Path(name).is_absolute() or Path(name).as_posix() != name
            or any(p in {".", ".."} for p in name.split("/"))):
        raise PreparationError("preparation_relative_path_required")
    return contained(name, root=root)


def bindings(value):
    rows = value.get("bound_files")
    if (not isinstance(rows, dict) or not rows or any(not isinstance(n, str)
            or not isinstance(h, str) or not re.fullmatch(r"[a-f0-9]{64}", h) for n, h in rows.items())):
        raise PreparationError("preparation_binding_contract")
    return rows


def phase_data_path(name, phase):
    """Reject old pools and the other split before opening a referenced body."""
    path = relative(name)
    parts = Path(name).parts
    prefix = f"meetings-c3-{phase}-"
    if not ((len(parts) >= 4 and parts[:2] == ("data", "evaluation")
             and parts[2].startswith(prefix))
            or (len(parts) >= 3 and parts[0] == ".local" and parts[1].startswith(prefix))):
        raise PreparationError("preparation_phase_data_path")
    return path


def freeze_roles(value, kind, phase):
    if (set(value) != {"schema_version", "candidate", "phase", "kind", "bound_files", "files"}
            or type(value.get("schema_version")) is not int or value["schema_version"] != 1
            or value.get("candidate") != ANSWER_POLICY or value.get("phase") != phase
            or value.get("kind") != kind or not isinstance(value.get("files"), dict)
            or set(value["files"]) != ROLES[kind]
            or not all(isinstance(n, str) for n in value["files"].values())
            or len(set(value["files"].values())) != len(value["files"])
            or not set(value["files"].values()) <= bindings(value).keys()):
        raise PreparationError("preparation_freeze_contract")
    return value["files"]


def check_prereview(value, ids, *, authors=None, partial_missing=False):
    if (type(value.get("schema_version")) is not int or value["schema_version"] != 1
            or value.get("verdict") != "accepted" or value.get("rejected_ids") != []
            or value.get("accepted_ids") != ids or not isinstance(value.get("author_ids"), list)
            or not value["author_ids"] or not isinstance(value.get("reviewer_id"), str)
            or not value["reviewer_id"] or value["reviewer_id"] in value["author_ids"]
            or any(not isinstance(a, str) or not a for a in value["author_ids"])
            or type(value.get("human_review_count")) is not int or value["human_review_count"] != 0
            or authors is not None and set(value["author_ids"]) != authors
            or partial_missing and value.get("whole_family_absence_checked") is not True):
        raise PreparationError("preparation_prereview_not_accepted")


def validate_draft(data, phase):
    if (not isinstance(data, dict) or set(data) != {"schema_version", "phase", "cases"}
            or type(data["schema_version"]) is not int or data["schema_version"] != 1
            or data["phase"] != phase or phase not in COUNTS or not isinstance(data["cases"], list)
            or len(data["cases"]) != COUNTS[phase]):
        raise PreparationError("preparation_draft_contract")
    ids = []
    for case in data["cases"]:
        if (not isinstance(case, dict) or set(case) != {"id", "response_language", "payload"}
                or not isinstance(case["id"], str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", case["id"])
                or case["response_language"] not in ("ko", "en")):
            raise PreparationError("preparation_case_contract")
        ids.append(case["id"])
        request = AnswerRequest.model_validate(case["payload"])
        if not request.contexts:
            raise PreparationError("preparation_contexts_required")
        if canonical(request.model_dump(exclude_unset=True)) != canonical(case["payload"]):
            raise PreparationError("preparation_payload_coercion")
    if len(set(ids)) != len(ids):
        raise PreparationError("preparation_duplicate_case")
    return data


def validate_inventory(manifest, inventory, phase, read_bound):
    """Rebuild all generic inventory records from frozen raw bytes; no language detection."""
    if (type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1
            or type(inventory.get("schema_version")) is not int or inventory["schema_version"] != 1
            or type(inventory.get("source_processing_version")) is not int
            or inventory["source_processing_version"] != 2
            or manifest.get("phase") != phase or inventory.get("phase") != phase
            or inventory.get("mode") != "adopted-all" or inventory.get("excluded_sources") != []
            or not isinstance(manifest.get("families"), list)
            or len(manifest["families"]) != 2
            or {f.get("family_id") for f in manifest["families"]} != set(FAMILIES[phase])):
        raise PreparationError("preparation_source_composition")
    documents, source_ids, raw_paths = [], set(), set()
    for family in manifest["families"]:
        family_id = family["family_id"]
        if (family.get("source_language") != SOURCE_LANGUAGES[family_id]
                or family.get("origin") != ("public" if family_id in {"C3-F01", "C3-F03"} else "synthetic")
                or family.get("source_suitability", {}).get("verdict") != "ADOPTED"
                or not isinstance(family.get("sources"), list) or not 1 <= len(family["sources"]) <= 2):
            raise PreparationError("preparation_source_not_adopted")
        for source in family["sources"]:
            if (source.get("adoption_verdict") !=
                    f"ADOPTED_FOR_{phase.upper()}_SOURCE_WITH_REGISTERED_CONSTRAINTS"
                    or type(source.get("revision")) is not int or source["revision"] != 1
                    or type(source.get("registration_ordinal")) is not int
                    or any(not isinstance(source.get(k), str)
                           or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", source[k])
                           for k in ("source_id", "document_id"))
                    or source["source_id"] in source_ids
                    or source["local_raw_snapshot"] in raw_paths
                    or len({s["path"] for s in family["sources"]}) != len(family["sources"])
                    or source.get("origin", family["origin"]) != family["origin"]
                    or not isinstance(source.get("title"), str) or not source["title"].strip()
                    or source.get("page", "missing") is not None
                    or "meeting_date" not in source
                    or source["meeting_date"] is not None and (not isinstance(source["meeting_date"], str)
                        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", source["meeting_date"]))
                    or not isinstance(source.get("adoption_author_role"), str)
                    or not source["adoption_author_role"].strip()
                    or source.get("raw_encoding") != "UTF-8"
                    or type(source.get("raw_size_bytes")) is not int or source["raw_size_bytes"] <= 0
                    or type(source.get("processed_codepoints")) is not int or source["processed_codepoints"] <= 0
                    or any(not isinstance(source.get(k), str) or not re.fullmatch(r"[a-f0-9]{64}", source[k])
                           for k in ("raw_sha256", "processed_sha256"))):
                raise PreparationError("preparation_source_not_adopted")
            if family["origin"] == "synthetic":
                provenance = source.get("synthetic_provenance", {})
                if (provenance.get("ai_authored") is not True or provenance.get("fictional") is not True
                        or source.get("git_blob_sha1") is not None
                        or any(not isinstance(provenance.get(k), str) or not provenance[k].strip()
                               for k in ("author_role", "notice"))):
                    raise PreparationError("preparation_synthetic_provenance")
            elif not isinstance(source.get("git_blob_sha1"), str) or not re.fullmatch(r"[a-f0-9]{40}", source["git_blob_sha1"]):
                raise PreparationError("preparation_public_provenance")
            source_ids.add(source["source_id"])
            raw_paths.add(source["local_raw_snapshot"])
            raw = read_bound(source["local_raw_snapshot"], source["raw_sha256"])
            documents.append(document_record(family, source, raw))
    documents.sort(key=lambda d: d["registration_ordinal"])
    if (documents != inventory.get("documents")
            or [d["registration_ordinal"] for d in documents] != list(range(len(documents)))
            or len({d["document_id"] for d in documents}) != len(documents)):
        raise PreparationError("preparation_inventory_mismatch")
    chunks = {}
    for document in documents:
        for chunk in document["chunks"]:
            if chunk["chunk_id"] in chunks:
                raise PreparationError("preparation_inventory_duplicate_chunk")
            context = {k: document[k] for k in ("document_id", "revision", "title", "meeting_date")}
            context.update({k: chunk[k] for k in ("chunk_id", "text", "page", "start_offset", "end_offset")})
            chunks[chunk["chunk_id"]] = (document["family_id"], context)
    return documents, chunks


def validate_processing_receipts(manifest, inventory, processing, parity, documents, code,
                                 *, manifest_name, manifest_sha, inventory_sha, phase):
    """Validate original v2 Python and actual Java receipt shapes without rerunning them."""
    protocol = manifest.get("processing_protocol", {})
    service = {n: code[n] for n in SERVICE_FILES}
    if (protocol.get("existing_service_reference_sha256") != service
            or protocol.get("chunk_algorithm") != CHUNK_CONTRACT
            or protocol.get("chunk_id_format") != "{document_id}-r1-c{ordinal:04d}"
            or not isinstance(protocol.get("id"), str) or not protocol["id"].strip()):
        raise PreparationError("preparation_processing_protocol")
    expected_rows = [{k: d[k] for k in ("source_id", "document_id", "revision", "raw_sha256",
        "raw_size_bytes", "git_blob_sha1", "processed_sha256", "processed_codepoints")}
        | {"chunks": len(d["chunks"])} for d in documents]
    counts = {"registered_sources": len(documents), "processed_documents": len(documents),
        "chunks": sum(len(d["chunks"]) for d in documents), "excluded_sources": 0,
        "selected_contexts": 0, "questions": 0, "oracles": 0, "synthetic_bodies_authored": 0,
        "tokenizer_runs": 0, "model_calls": 0, "downloads": 0, "human_reviews": 0}
    expected = {"schema_version": 1, "source_processing_version": 2, "phase": phase,
        "mode": "adopted-all", "manifest": {"path": manifest_name, "sha256": manifest_sha},
        "bound_files": {n: code[n] for n in SERVICE_FILES | HELPER_FILES},
        "references": {r: manifest[r] for r in ("family_registry", "active_comparison_source_freeze")},
        "inventory_sha256": inventory_sha, "processing_protocol": protocol["id"],
        "documents": expected_rows, "excluded_sources": [], "counts": counts,
        "java_parity_verified": False}
    if canonical(processing) != canonical(expected):
        raise PreparationError("preparation_processing_receipt")
    parity_rows = [{"document_id": d["document_id"], "raw_sha256": d["raw_sha256"],
        "processed_sha256": d["processed_sha256"], "codepoints": d["processed_codepoints"],
        "chunks": len(d["chunks"])} for d in documents]
    expected_parity = {"schema_version": 1, "kind": "actual_java_python_document_chunk_parity",
        "inventory_sha256": inventory_sha, "java_version": parity.get("java_version"),
        "bound_files": {n: code[n] for n in JAVA_PARITY_FILES}, "documents": parity_rows,
        "document_count": len(documents), "chunk_count": counts["chunks"],
        "exact_content_pages_chunk_text_offsets_ordinals_ids": True,
        "model_calls": 0, "semantic_quality_measured": False}
    if (not isinstance(parity.get("java_version"), str)
            or not re.fullmatch(r"21(?:[.+-].*)?", parity["java_version"])
            or canonical(parity) != canonical(expected_parity)):
        raise PreparationError("preparation_java_parity_receipt")


def prepare(draft_path, output, phase, *, oracle_path, source_freeze_path, item_freeze_path,
            code_freeze_path, loader=None, counter=None):
    """Claim once, hash all sealed inputs, then survey every stage-1 input without repairs."""
    if phase not in COUNTS:
        raise PreparationError("preparation_invalid_phase")
    root = ROOT.resolve()
    paths = {k: contained(v) for k, v in {"draft": draft_path, "oracle": oracle_path,
        "source_freeze": source_freeze_path, "item_freeze": item_freeze_path,
        "code_freeze": code_freeze_path}.items()}
    # This is shared metadata, never an arbitrary phase/body path. Check before
    # any capture, including before reading the claimed code-freeze contents.
    if paths["code_freeze"] != relative(TOOLCHAIN_FREEZE):
        raise PreparationError("preparation_code_freeze_path")
    for role in ("draft", "oracle", "source_freeze", "item_freeze"):
        phase_data_path(paths[role].relative_to(root).as_posix(), phase)
    output = contained(output, output=True)
    if output.exists() or any(output == p or p.is_relative_to(output) or output.is_relative_to(p)
                              for p in paths.values()):
        raise PreparationError("preparation_output_exists_or_collision")
    if len(set(paths.values())) != len(paths):
        raise PreparationError("preparation_input_alias")
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "candidate": ANSWER_POLICY, "phase": phase, "status": "failed",
        "stage2_readiness": "dynamic_unmeasured", "snapshots": {}, "bound_files": {}, "cases": [],
        "tokenizer": None, "payloads_preserved": False, "input_sha256": None,
        "model_calls": 0, "native_calls": 0, "downloads": 0, "errors": []}
    captures, stamps, code, input_bytes = {}, {}, {}, None

    def capture(path):
        path = contained(path)
        if path in captures:
            return captures[path]
        if path == output or path.is_relative_to(output) or output.is_relative_to(path):
            raise PreparationError("preparation_output_collision")
        raw, observed = snapshot(path)
        if any(path.samefile(other) for other in captures):
            raise PreparationError("preparation_input_alias")
        captures[path], stamps[path] = raw, observed
        report["snapshots"][path.relative_to(root).as_posix()] = {"sha256": sha(raw), "bytes": len(raw)}
        return raw

    def bound(name, digest):
        raw = capture(relative(name))
        if sha(raw) != digest:
            raise PreparationError("preparation_hash_mismatch")
        return raw

    def read(path):
        return strict_json(capture(path).decode("utf-8"))

    try:
        # All candidate bindings remain immutable; exact toolchain membership is enforced.
        candidate = strict_json(bound(CANDIDATE_FREEZE, CANDIDATE_FREEZE_SHA256).decode("utf-8"))
        code_freeze = read(paths["code_freeze"])
        if (set(code_freeze) != {"schema_version", "candidate", "kind", "bound_files"}
                or type(code_freeze.get("schema_version")) is not int or code_freeze["schema_version"] != 1
                or code_freeze.get("candidate") != ANSWER_POLICY or code_freeze.get("kind") != "toolchain"):
            raise PreparationError("preparation_code_freeze_contract")
        code = bindings(code_freeze)
        expected = set(bindings(candidate)) | NEW_FILES | REUSED_FILES | {CANDIDATE_FREEZE, CONTRACT}
        if (len(bindings(candidate)) != 28 or set(code) != expected
                or code[CANDIDATE_FREEZE] != CANDIDATE_FREEZE_SHA256
                or code[CONTRACT] != CONTRACT_SHA256
                or any(code[n] != h for n, h in bindings(candidate).items())):
            raise PreparationError("preparation_code_freeze_contract")
        for name, digest in code.items():
            bound(name, digest)
        report["bound_files"] = code
        source, item = read(paths["source_freeze"]), read(paths["item_freeze"])
        source_files = freeze_roles(source, "source", phase)
        item_files = freeze_roles(item, "item", phase)
        for role in ("draft", "oracle", "source_freeze", "code_freeze"):
            if relative(item_files[role]) != paths[role]:
                raise PreparationError("preparation_item_role_mismatch")
        code_name = paths["code_freeze"].relative_to(root).as_posix()
        if set(bindings(item)) != set(item_files.values()):
            raise PreparationError("preparation_item_binding_set")
        # Validate every namespace before any referenced source/item body is opened.
        for name in bindings(source):
            phase_data_path(name, phase)
        for name in bindings(item):
            if name != code_name:
                phase_data_path(name, phase)
        manifest_raw = bound(source_files["manifest"], bindings(source)[source_files["manifest"]])
        declared_manifest = strict_json(manifest_raw.decode("utf-8"))
        raw_names = {s["local_raw_snapshot"] for f in declared_manifest["families"] for s in f["sources"]}
        if set(bindings(source)) != set(source_files.values()) | raw_names:
            raise PreparationError("preparation_source_binding_set")
        for freeze in (source, item):
            for name, digest in bindings(freeze).items():
                bound(name, digest)
        manifest, inventory = (read(relative(source_files[r])) for r in ("manifest", "inventory"))
        registry = read(relative(REGISTRY))
        registered = {f["family_id"]: f for f in registry["families"] if f["split"] == phase}
        if set(registered) != set(FAMILIES[phase]):
            raise PreparationError("preparation_registry_composition")
        for family in manifest["families"]:
            entry = registered[family["family_id"]]
            if any(family.get(k) != entry.get(k) for k in ("origin", "source_language")):
                raise PreparationError("preparation_registry_family")
            if entry["origin"] == "public":
                allowed = {s["path"]: s["sha"] for s in entry["source_candidates"]}
                if (any(family.get(k) != entry[k] for k in ("repository", "immutable_commit"))
                        or any(allowed.get(s["path"]) != s.get("git_blob_sha1") for s in family["sources"])):
                    raise PreparationError("preparation_registry_source")
        if inventory.get("manifest_sha256") != sha(capture(relative(source_files["manifest"]))):
            raise PreparationError("preparation_manifest_binding")
        for role, name in (("family_registry", REGISTRY),
                           ("active_comparison_source_freeze", paths["code_freeze"].relative_to(root).as_posix())):
            if manifest.get(role) != {"path": name, "sha256": sha(capture(relative(name)))}:
                raise PreparationError("preparation_source_reference")
        def source_bound(name, digest):
            if bindings(source).get(name) != digest:
                raise PreparationError("preparation_unbound_source")
            return bound(name, digest)
        documents, chunks = validate_inventory(manifest, inventory, phase, source_bound)
        source_prereview = read(relative(source_files["prereview"]))
        check_prereview(source_prereview, [d["document_id"] for d in documents])
        source_authors = {s["adoption_author_role"] for f in manifest["families"] for s in f["sources"]}
        source_authors |= {s["synthetic_provenance"]["author_role"] for f in manifest["families"]
                           if f["origin"] == "synthetic" for s in f["sources"]}
        if source_authors != set(source_prereview["author_ids"]):
            raise PreparationError("preparation_source_author_mismatch")
        parity = read(relative(source_files["java_parity"]))
        validate_processing_receipts(manifest, inventory,
            read(relative(source_files["processing_receipt"])), parity, documents, code,
            manifest_name=source_files["manifest"], manifest_sha=sha(manifest_raw),
            inventory_sha=sha(capture(relative(source_files["inventory"]))), phase=phase)
        draft = validate_draft(read(paths["draft"]), phase)
        oracles = validate_oracles(draft, read(paths["oracle"]), phase)
        prereview = read(relative(item_files["prereview"]))
        authors = {a for o in oracles.cases for a in (o.question_author, o.oracle_author)}
        check_prereview(prereview, [c["id"] for c in draft["cases"]], authors=authors, partial_missing=True)
        if any(o.independent_prereviewer != prereview["reviewer_id"] for o in oracles.cases):
            raise PreparationError("preparation_prereviewer_mismatch")
        selections = read(relative(item_files["context_selection"]))
        expected_selection = {"schema_version": 1, "phase": phase, "cases": [
            {"id": c["id"], "chunk_ids": [x["chunk_id"] for x in c["payload"]["contexts"]]}
            for c in draft["cases"]]}
        if canonical(selections) != canonical(expected_selection):
            raise PreparationError("preparation_context_selection_mismatch")
        for case, oracle in zip(draft["cases"], oracles.cases, strict=True):
            for context in case["payload"]["contexts"]:
                if chunks.get(context["chunk_id"]) != (oracle.family_id, context):
                    raise PreparationError("preparation_whole_context_mismatch")
            report["cases"].append({"id": case["id"], "response_language": case["response_language"],
                "payload_sha256": sha(canonical(case["payload"])), "payload_preserved": True,
                "official_stage1_tokens": None, "stage2_readiness": "dynamic_unmeasured", "error_code": None})
        from scripts.check_meeting_review_token_budget import count_prompt, load_tokenizer
        tokenizer, metadata = (loader or load_tokenizer)(False)
        _tokenizer_metadata(metadata)
        report["tokenizer"] = metadata
        for case, row in zip(draft["cases"], report["cases"], strict=True):
            try:
                catalog = build_block_catalog(AnswerRequest.model_validate(case["payload"]).contexts)
                prompt = requirement_messages(case["payload"]["query"], catalog, case["response_language"])
                grammar = requirement_plan_grammar(catalog)
                template = {"messages": prompt, "chat_template_kwargs": {"enable_thinking": False}}
                row.update(stage1_prompt_sha256=sha(canonical(prompt)),
                    stage1_grammar_sha256=sha(grammar.encode()), supplied_units=len(catalog.spans),
                    template_request_bytes=len(json.dumps(template, ensure_ascii=False).encode()))
                if row["template_request_bytes"] > MAX_REQUEST_BYTES:
                    raise PreparationError("preparation_template_byte_limit")
                count = (counter or count_prompt)(tokenizer, prompt)
                if type(count) is not int or count <= 0:
                    raise PreparationError("preparation_token_count_failed")
                row["official_stage1_tokens"] = count
                skeleton = {**GREEDY, "n_predict": MAX_NEW_TOKENS, "grammar": grammar,
                            "prompt": [], "cache_prompt": False, "return_tokens": True}
                lower_bytes = len(json.dumps(skeleton, ensure_ascii=False).encode()) + count * 3 - 2
                row.update(native_request_bytes_verified=False, native_request_bytes=None,
                           completion_bytes_lower_bound_at_official_count=lower_bytes)
                if count > MAX_INPUT_TOKENS:
                    raise PreparationError("preparation_input_budget_exceeded")
                if lower_bytes > MAX_REQUEST_BYTES:
                    raise PreparationError("preparation_completion_byte_limit")
            except Exception as error:  # noqa: BLE001 - private text never enters diagnostics
                row["error_code"] = str(error) if type(error) is PreparationError else "preparation_stage1_failed"
        report["payloads_preserved"] = True
        if any(r["error_code"] for r in report["cases"]):
            raise PreparationError("preparation_survey_failed")
        prepared = {**draft, "cases": [{**c, "official_stage1_tokens": r["official_stage1_tokens"]}
                    for c, r in zip(draft["cases"], report["cases"], strict=True)]}
        input_bytes = encoded(prepared)
        if len(input_bytes) > BYTE_LIMIT:
            raise PreparationError("preparation_file_limit")
        report.update(status="passed", input_sha256=sha(input_bytes), input_bytes=len(input_bytes))
    except Exception as error:  # noqa: BLE001 - safe local receipt; no source exception text
        report["errors"].append(str(error) if type(error) is PreparationError else "preparation_failed")
    try:
        for path, observed in stamps.items():
            if stamp(contained(path)) != observed:
                raise PreparationError("preparation_snapshot_changed")
        for name, digest in code.items():
            if sha(snapshot(relative(name))[0]) != digest:
                raise PreparationError("preparation_source_changed")
    except Exception as error:  # noqa: BLE001 - preserve failure even after counts
        report.update(status="failed", input_sha256=None)
        report["errors"].append(str(error) if type(error) is PreparationError else "preparation_integrity_failed")
    values = [r["official_stage1_tokens"] for r in report["cases"]
              if type(r["official_stage1_tokens"]) is int]
    report["summary"] = {"total_cases": COUNTS[phase], "measured_cases": len(values),
        "unmeasured_cases": COUNTS[phase] - len(values),
        "failed_cases": sum(r["error_code"] is not None for r in report["cases"]),
        "min_stage1_tokens": min(values) if values else None, "max_stage1_tokens": max(values) if values else None}
    if report["status"] == "passed":
        try:
            with (contained(output) / "input.json").open("xb") as stream:
                stream.write(input_bytes)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:  # noqa: BLE001 - claim remains consumed on write failure
            report.update(status="failed", input_sha256=None)
            report["errors"].append("preparation_input_write_failed")
    with (contained(output) / "receipt.json").open("xb") as stream:
        raw = encoded(report)
        if len(raw) > BYTE_LIMIT:
            raise PreparationError("preparation_file_limit")
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare"])
    parser.add_argument("--phase", choices=COUNTS, required=True)
    for name in ("draft", "oracle", "source-freeze", "item-freeze", "code-freeze", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
            result = prepare(args.draft, args.output, args.phase, oracle_path=args.oracle,
                source_freeze_path=args.source_freeze, item_freeze_path=args.item_freeze,
                code_freeze_path=args.code_freeze)
    except Exception:  # noqa: BLE001 - never print private paths or source text
        parser.exit(1, "requirements_input_preparation_failed\n")
    print(json.dumps({"status": result["status"], **result["summary"], "model_calls": 0,
                      "native_calls": 0, "downloads": 0, "stage2_readiness": "dynamic_unmeasured"}))
    raise SystemExit(0 if result["status"] == "passed" else 2)


if __name__ == "__main__":
    main()
