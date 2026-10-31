"""Inventory whole adopted source documents using the existing service functions.

Run each split only in its authorized source-custodian role. This preparation
does not select contexts, author questions/synthetic documents, tokenize, infer,
fetch URLs or establish Java parity. `adopted-public` explicitly records excluded
nonpublic entries instead of silently treating a partial corpus as complete.
`adopted-all` requires every registered source, including synthetic sources, to
be finalized in a separately registered complete manifest before processing.
Outputs contain complete source text and belong in a NEW local artifact folder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path

from doctrail.ingest import MAX_FILE_BYTES, extract
from doctrail.meeting_contract import strict_json
from doctrail.retrieval import chunk_content

ROOT = Path(__file__).resolve().parents[1]
HELPER_FILES = {"scripts/prepare_meeting_source_inventory.py",
                "tests/test_prepare_meeting_source_inventory.py"}
SERVICE_FILES = {"src/doctrail/ingest.py", "src/doctrail/retrieval.py",
    "server/src/main/java/io/doctrail/Ingest.java", "server/src/main/java/io/doctrail/Retrieval.java"}
MAX_METADATA_BYTES = 2 * 1024 * 1024
CHUNK_CONTRACT = {"max_codepoints": 1000, "boundary_search_min_codepoints": 500,
                  "overlap_codepoints": 150, "boundary_characters": ["LF", "ASCII SPACE"]}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def contained(path):
    """Resolve inside the workspace and reject links/junctions before file reads."""
    path = Path(path)
    absolute = path if path.is_absolute() else ROOT / path
    if ".." in absolute.parts:
        raise ValueError("source_inventory_invalid_path")
    root = ROOT.resolve()
    if not absolute.is_relative_to(root):
        raise ValueError("source_inventory_outside_repository")
    current = root
    for part in absolute.relative_to(root).parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if current.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("source_inventory_linked_path")
    resolved = absolute.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("source_inventory_outside_repository")
    return resolved


def local(name):
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError("source_inventory_invalid_path")
    return contained(name)


def digest(value, length=64):
    return isinstance(value, str) and re.fullmatch(rf"[a-f0-9]{{{length}}}", value) is not None


class Snapshots:
    """One bounded byte read per file; checks and parsers use the same capture."""
    def __init__(self):
        self.files = {}

    def read(self, path, limit=MAX_METADATA_BYTES):
        path = contained(path)
        if path not in self.files:
            with path.open("rb") as stream:
                raw = stream.read(limit + 1)
            if len(raw) > limit:
                raise ValueError("source_inventory_file_limit")
            self.files[path] = raw
        raw = self.files[path]
        if len(raw) > limit:
            raise ValueError("source_inventory_file_limit")
        return raw

    def bound(self, name, expected):
        if not digest(expected):
            raise ValueError("source_inventory_invalid_hash")
        raw = self.read(local(name))
        if sha(raw) != expected:
            raise ValueError("source_inventory_binding_changed")
        return raw


def classify(manifest, phase, mode):
    if (type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1
            or manifest.get("phase") != phase or phase not in {"calibration", "validation"}
            or mode not in {"adopted-public", "adopted-all"}
            or not isinstance(manifest.get("families"), list)
            or not manifest["families"]):
        raise ValueError("source_inventory_manifest_contract")
    selected, excluded, ids, documents, ordinals, families = [], [], set(), set(), set(), set()
    for family in manifest["families"]:
        identity, origin = family.get("family_id"), family.get("origin")
        if (not isinstance(identity, str) or not identity or identity in families
                or origin not in {"public", "synthetic"}
                or not isinstance(family.get("sources"), list) or not family["sources"]):
            raise ValueError("source_inventory_family_contract")
        families.add(identity)
        for source in family["sources"]:
            source_id, doc_id, ordinal = (source.get("source_id"), source.get("document_id"),
                                          source.get("registration_ordinal"))
            if (any(not isinstance(i, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", i)
                    for i in (source_id, doc_id))
                    or source_id in ids or doc_id in documents or type(ordinal) is not int
                    or ordinal < 0 or ordinal in ordinals or type(source.get("revision")) is not int
                    or source["revision"] != 1 or source.get("origin", origin) != origin):
                raise ValueError("source_inventory_source_identity")
            ids.add(source_id)
            documents.add(doc_id)
            ordinals.add(ordinal)
            if origin == "synthetic" and mode == "adopted-public":
                excluded.append({"source_id": source_id, "family_id": identity, "origin": origin,
                    "registration_ordinal": ordinal, "reason": "excluded_by_explicit_adopted_public_mode"})
                continue
            if (family.get("source_suitability", {}).get("verdict") != "ADOPTED"
                    or source.get("adoption_verdict") !=
                    f"ADOPTED_FOR_{phase.upper()}_SOURCE_WITH_REGISTERED_CONSTRAINTS"
                    or not isinstance(source.get("title"), str) or not source["title"].strip()
                    or source.get("page", "missing") is not None
                    or "meeting_date" not in source
                    or source["meeting_date"] is not None and (
                        not isinstance(source["meeting_date"], str)
                        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", source["meeting_date"]))):
                raise ValueError("source_inventory_source_not_adopted")
            if (not digest(source.get("raw_sha256")) or not digest(source.get("processed_sha256"))
                    or origin == "public" and not digest(source.get("git_blob_sha1"), 40)
                    or type(source.get("raw_size_bytes")) is not int
                    or not 0 < source["raw_size_bytes"] <= MAX_FILE_BYTES
                    or type(source.get("processed_codepoints")) is not int
                    or source["processed_codepoints"] <= 0 or source.get("raw_encoding") != "UTF-8"):
                raise ValueError("source_inventory_source_hash_contract")
            if origin == "synthetic":
                provenance = source.get("synthetic_provenance", {})
                if (provenance.get("ai_authored") is not True or provenance.get("fictional") is not True
                        or any(not isinstance(provenance.get(k), str) or not provenance[k].strip()
                               for k in ("author_role", "notice"))
                        or source.get("git_blob_sha1") is not None):
                    raise ValueError("source_inventory_synthetic_provenance")
            raw_path = local(source.get("local_raw_snapshot"))
            upstream_path = source.get("path")
            if not isinstance(upstream_path, str) or Path(upstream_path).suffix.lower() not in {".md", ".txt"}:
                raise ValueError("source_inventory_text_sources_only")
            selected.append((family, source, raw_path))
    if not selected or ordinals != set(range(len(ordinals))):
        raise ValueError("source_inventory_registration_ordinals")
    return (sorted(selected, key=lambda item: item[1]["registration_ordinal"]),
            sorted(excluded, key=lambda item: item["registration_ordinal"]))


def document_record(family, source, raw):
    if (len(raw) != source["raw_size_bytes"] or sha(raw) != source["raw_sha256"]
            or family["origin"] == "public" and git_blob(raw) != source["git_blob_sha1"]):
        raise ValueError("source_inventory_raw_mismatch")
    raw_text = raw.decode("utf-8")
    content, pages = extract(raw, Path(source["path"]).suffix.lower()[1:])
    observations = {"bom": raw.startswith(b"\xef\xbb\xbf"), "lf_count": raw_text.count("\n"),
        "cr_count": raw_text.count("\r"), "trailing_lf": raw_text.endswith("\n"),
        "nfc_identity_verified": unicodedata.is_normalized("NFC", raw_text),
        "service_normalization_identity_verified": raw_text == content}
    if any(type(source.get(k)) is not type(v) or source[k] != v for k, v in observations.items()):
        raise ValueError("source_inventory_normalization_observations")
    if (len(content) != source["processed_codepoints"] or sha(content.encode()) != source["processed_sha256"]
            or pages != [(0, len(content), None)]):
        raise ValueError("source_inventory_processed_mismatch")
    if family["origin"] == "synthetic" and source["synthetic_provenance"]["notice"] not in content:
        raise ValueError("source_inventory_synthetic_notice_missing")
    chunks = []
    for chunk in chunk_content(content, pages):
        if chunk.text != content[chunk.start_offset:chunk.end_offset]:
            raise ValueError("source_inventory_chunk_not_exact")
        chunks.append({"chunk_id": f"{source['document_id']}-r{source['revision']}-c{chunk.ordinal:04d}",
            "text": chunk.text, "page": chunk.page, "start_offset": chunk.start_offset,
            "end_offset": chunk.end_offset, "ordinal": chunk.ordinal,
            "text_sha256": sha(chunk.text.encode())})
    provenance = {"origin": family["origin"], "adoption_verdict": source["adoption_verdict"],
        "source_suitability": family["source_suitability"],
        "processing_notice": "Full source normalized and chunked with existing service functions; attribution is outside source text."}
    if family["origin"] == "public":
        provenance.update(repository=family["repository"], immutable_commit=family["immutable_commit"],
            upstream_path=source["path"], immutable_url=source["immutable_url"],
            license_id=source["license_id"], license=family["license"])
    else:
        provenance["synthetic_provenance"] = source["synthetic_provenance"]
    return {"source_id": source["source_id"], "document_id": source["document_id"],
        "revision": source["revision"], "registration_ordinal": source["registration_ordinal"],
        "family_id": family["family_id"], "title": source["title"], "meeting_date": source["meeting_date"],
        "raw_snapshot": source["local_raw_snapshot"], "raw_sha256": source["raw_sha256"],
        "raw_size_bytes": len(raw), "git_blob_sha1": source.get("git_blob_sha1"),
        "processed_sha256": source["processed_sha256"], "processed_codepoints": len(content),
        "content": content, "pages": [{"start_offset": start, "end_offset": end, "page": page}
                                       for start, end, page in pages], "chunks": chunks,
        "provenance": provenance}


def prepare(manifest_path, output, phase, mode):
    manifest_path, output = contained(manifest_path), contained(output)
    if (output.exists() or output == manifest_path or manifest_path.is_relative_to(output)
            or not output.is_relative_to(ROOT.resolve() / ".local")):
        raise ValueError("source_inventory_output_exists_or_invalid")
    captured = Snapshots()
    manifest_bytes = captured.read(manifest_path)
    manifest = strict_json(manifest_bytes.decode("utf-8"))
    selected, excluded = classify(manifest, phase, mode)
    protocol = manifest["processing_protocol"]
    service = protocol["existing_service_reference_sha256"]
    if (set(service) != SERVICE_FILES or any(protocol["chunk_algorithm"].get(k) != v
                                           for k, v in CHUNK_CONTRACT.items())
            or protocol.get("chunk_id_format") != "{document_id}-r1-c{ordinal:04d}"):
        raise ValueError("source_inventory_processing_contract")
    bindings = {}
    for name, expected in service.items():
        captured.bound(name, expected)
        bindings[name] = expected
    for name in sorted(HELPER_FILES):
        bindings[name] = sha(captured.read(local(name)))
    references = {}
    for name in ("family_registry", "active_comparison_source_freeze"):
        reference = manifest[name]
        captured.bound(reference["path"], reference["sha256"])
        references[name] = {"path": reference["path"], "sha256": reference["sha256"]}
    # Preflight every raw path/collision before opening any raw document.
    paths = [manifest_path, *captured.files, *(path for _, _, path in selected)]
    if any(path == output or path.is_relative_to(output) for path in paths):
        raise ValueError("source_inventory_output_collision")
    raw_paths = [path for _, _, path in selected]
    if len(set(raw_paths)) != len(raw_paths):
        raise ValueError("source_inventory_duplicate_raw_path")
    documents = [document_record(family, source, captured.read(path, MAX_FILE_BYTES))
                 for family, source, path in selected]
    inventory = {"schema_version": 1, "phase": phase, "mode": mode,
        "manifest_sha256": sha(manifest_bytes), "documents": documents, "excluded_sources": excluded}
    inventory_bytes = encoded(inventory)
    receipt = {"schema_version": 1, "phase": phase, "mode": mode,
        "manifest": {"path": manifest_path.relative_to(ROOT.resolve()).as_posix(),
                     "sha256": sha(manifest_bytes)}, "bound_files": bindings,
        "references": references, "inventory_sha256": sha(inventory_bytes),
        "processing_protocol": protocol["id"], "documents": [{k: doc[k] for k in (
            "source_id", "document_id", "revision", "raw_sha256", "raw_size_bytes", "git_blob_sha1",
            "processed_sha256", "processed_codepoints")} | {"chunks": len(doc["chunks"])}
            for doc in documents], "excluded_sources": excluded,
        "counts": {"registered_sources": len(documents) + len(excluded), "processed_documents": len(documents),
            "chunks": sum(len(doc["chunks"]) for doc in documents), "excluded_sources": len(excluded),
            "selected_contexts": 0, "questions": 0, "oracles": 0, "synthetic_bodies_authored": 0,
            "tokenizer_runs": 0, "model_calls": 0, "downloads": 0, "human_reviews": 0},
        "java_parity_verified": False}
    receipt_bytes = encoded(receipt)
    output.mkdir(parents=True, exist_ok=False)
    for filename, content in (("inventory.json", inventory_bytes), ("receipt.json", receipt_bytes)):
        with (output / filename).open("xb") as stream:
            stream.write(content)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("calibration", "validation"), required=True)
    parser.add_argument("--mode", choices=("adopted-public", "adopted-all"), required=True)
    args = parser.parse_args()
    try:
        receipt = prepare(args.manifest, args.output, args.phase, args.mode)
    except Exception:  # noqa: BLE001 - raw source text and local exceptions never enter console logs
        parser.exit(1, "source_inventory_preparation_failed\n")
    print(json.dumps({"phase": args.phase, "mode": args.mode, "counts": receipt["counts"],
                      "java_parity_verified": False}))


if __name__ == "__main__":
    main()
