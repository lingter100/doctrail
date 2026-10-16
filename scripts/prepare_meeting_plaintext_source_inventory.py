"""Versioned literal-text source preparation; retains the frozen v1 helper.

RST is accepted only with ingestion_kind=txt. No directives, includes or markup
are executed. Original upstream paths and hashes remain provenance identities.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from doctrail.ingest import MAX_FILE_BYTES
from doctrail.meeting_contract import strict_json
from scripts import prepare_meeting_source_inventory as legacy
from scripts.prepare_meeting_source_inventory import (
    CHUNK_CONTRACT,
    ROOT,
    SERVICE_FILES,
    Snapshots,
    contained,
    encoded,
    local,
    sha,
)

HELPER_FILES = legacy.HELPER_FILES | {
    "scripts/prepare_meeting_plaintext_source_inventory.py",
    "tests/test_prepare_meeting_plaintext_source_inventory.py",
}


def ingestion_kind(source):
    suffix = Path(source.get("path", "")).suffix.lower()
    expected = {".md": "md", ".txt": "txt", ".rst": "txt"}.get(suffix)
    declared = source.get("ingestion_kind", expected if suffix != ".rst" else None)
    if expected is None or declared != expected:
        raise ValueError("source_inventory_explicit_text_kind_required")
    return expected


def classify(manifest, phase, mode):
    # v1 validates all source identities/adoption/provenance before raw reads.
    # Its suffix check is reused on a private type-routing copy, never published.
    routed = copy.deepcopy(manifest)
    originals = {}
    for family, proxy_family in zip(manifest.get("families", []), routed.get("families", []), strict=True):
        for source, proxy in zip(family["sources"], proxy_family["sources"], strict=True):
            if family.get("origin") == "synthetic" and mode == "adopted-public":
                continue
            kind = ingestion_kind(source)
            proxy["path"] = f"source.{kind}"
            originals[source["source_id"]] = (family, source)
    selected, excluded = legacy.classify(routed, phase, mode)
    return [(originals[source["source_id"]][0], originals[source["source_id"]][1], path)
            for _, source, path in selected], excluded


def document_record(family, source, raw):
    # Only the existing extractor's kind routing uses this transient filename.
    # Raw snapshot path, SHA, original manifest and all text remain unchanged.
    kind = ingestion_kind(source)
    routed = dict(source, path=f"source.{kind}")
    record = legacy.document_record(family, routed, raw)
    if family["origin"] == "public":
        record["provenance"]["upstream_path"] = source["path"]
    record["source_path"] = source["path"]
    record["ingestion_kind"] = kind
    return record


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
    inventory = {"schema_version": 1, "source_processing_version": 2, "phase": phase, "mode": mode,
        "manifest_sha256": sha(manifest_bytes), "documents": documents, "excluded_sources": excluded}
    inventory_bytes = encoded(inventory)
    receipt = {"schema_version": 1, "source_processing_version": 2, "phase": phase, "mode": mode,
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
