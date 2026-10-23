"""Fixed, data-free observation of frozen admission; never a source admission.

The CLI has no selection/configuration options and consumes its fixed directory.
Unit callers use run_unit with temporary outputs, never the official directory.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN = "docs/MEETINGS-ADMISSION-DIAGNOSTIC.md"
DESIGN_SHA = "b5d64fa09092982461188cb219035a246407cfabe45bc773a1598f6045faa093"
FREEZE = "data/evaluation/meetings-c7-toolchain-freeze-v1.json"
FREEZE_SHA = "6f829eeb829b957683fb2a7c4b6182a14aab787d816ede11b1c017bbe69a65ca"
FIXTURE = "tests/fixtures/meeting-admission-diagnostic-v1.json"
FIXTURE_SHA = "ac7c452afd1fee257cf01e4f0b7752ac17e0636747521ce7025d2016bc09fa48"
OWN_FILES = (FIXTURE, "scripts/diagnose_meeting_admission.py",
             "tests/test_diagnose_meeting_admission.py")
OUTPUT = ".local/meetings-admission-diagnostic-v1"
IDS = tuple(f"F{i:02d}" for i in range(1, 13))
ZERO_COUNTERS = {"model_calls": 0, "network_calls": 0, "tokenizer_calls": 0,
                 "native_calls": 0, "downloads": 0, "actual_source_admissions": 0}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("diagnostic_duplicate_key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(
                          ValueError("diagnostic_nonfinite_json")))


def load_fixtures(raw):
    # Exact byte pin fixes inputs AND their independently entered expectations.
    if sha(raw) != FIXTURE_SHA:
        raise ValueError("diagnostic_fixture_hash")
    value = strict_json(raw)
    if (set(value) != {"schema_version", "kind", "expectation_origin", "fixtures"}
            or value["schema_version"] != 1
            or value["kind"] != "fixed_synthetic_admission_diagnostic_fixtures"
            or tuple(row["id"] for row in value["fixtures"]) != IDS):
        raise ValueError("diagnostic_fixture_contract")
    return value["fixtures"]


def measure_fixture(fixture):
    """One unchanged pure admission call, then separate real observations."""
    from doctrail.ingest import extract
    from doctrail.meeting_answer_blocks import build_block_catalog
    from doctrail.meeting_answer_thinking import (
        answer_messages_thinking,
        answer_schema_thinking,
    )
    from doctrail.meeting_contract import Context
    from doctrail.meeting_thinking_transport import request_body
    from doctrail.meeting_worker import safe_payload
    from doctrail.retrieval import chunk_content
    from scripts.prepare_meeting_budget_inputs import canonical
    from scripts.prepare_meeting_c7_inputs import family_admission, whole_contexts

    row = {"id": fixture["id"], "status": "failed", "original_admission": None,
           "family_admission_calls": 0, "discrepancies": [], "documents": [],
           "blocks": [], "renderings": {}, "unexpected_error": None}
    original_fixture = encoded(fixture)

    def compare(name, actual, expected):
        if actual != expected:
            row["discrepancies"].append({"invariant": name, "actual": actual,
                                         "expected": expected})
    try:
        documents, sources = [], []
        for item in fixture["documents"]:
            metadata, expected = item["metadata"], item["expected"]
            raw = item["raw"].encode("utf-8")
            content, pages = extract(raw, "md")
            chunks = [{**asdict(c), "chunk_id": f"{metadata['document_id']}-r1-c{c.ordinal:04d}"}
                      for c in chunk_content(content, pages)]
            document = {**metadata, "content": content, "raw_sha256": sha(raw),
                        "processed_sha256": sha(content.encode()), "chunks": chunks}
            sources.append(copy.deepcopy(metadata))
            documents.append(document)
            covered = {i for c in chunks for i in range(c["start_offset"], c["end_offset"])}
            observations = {
                "document_id": metadata["document_id"], "metadata": copy.deepcopy(metadata),
                "metadata_sha256": sha(canonical({k: metadata[k] for k in (
                    "document_id", "revision", "title", "kind", "language", "meeting_date",
                    "page")})),
                "raw_sha256": sha(raw), "raw_utf8_bytes": len(raw),
                "raw_codepoints": len(item["raw"]), "processed_sha256": sha(content.encode()),
                "processed_content": content, "processed_codepoints": len(content),
                "processed_utf8_bytes": len(content.encode()), "pages": pages,
                "normalization_identity": content == item["raw"],
                "chunks": [{**c, "text_sha256": sha(c["text"].encode()),
                            "utf8_bytes": len(c["text"].encode())} for c in chunks],
                "chunk_count": len(chunks), "unique_covered_codepoints": len(covered),
                "overlap_codepoints": sum(len(c["text"]) for c in chunks) - len(covered),
                "emitted_chunk_utf8_bytes": sum(len(c["text"].encode()) for c in chunks),
            }
            row["documents"].append(observations)
            for key in ("processed_content", "raw_utf8_bytes", "processed_codepoints",
                        "processed_utf8_bytes"):
                compare(f"{metadata['document_id']}.{key}", observations[key], expected[key])
            compare(f"{metadata['document_id']}.pages", pages,
                    [(0, expected["processed_codepoints"], None)])
            compare(f"{metadata['document_id']}.chunk_offsets",
                    [[c["start_offset"], c["end_offset"]] for c in chunks],
                    [[c["start_offset"], c["end_offset"]] for c in expected["chunks"]])
        family = {"family_id": "c7-f01", "sources": sources}
        originals = encoded({"family": family, "documents": documents})
        row["originals_before_sha256"] = sha(originals)
        row["family_admission_calls"] = 1
        row["original_admission"] = family_admission("calibration", family, documents, FREEZE_SHA)
        admission_bytes = encoded(row["original_admission"])
        contexts = whole_contexts(documents)
        catalog = build_block_catalog([Context.model_validate(c) for c in contexts])
        for span in catalog.spans:
            row["blocks"].append({
                **asdict(span), "quote_sha256": sha(span.quote.encode()),
                "codepoints": len(span.quote), "utf8_bytes": len(span.quote.encode()),
                "eligible": span.span_id in catalog.eligible_ids,
                "whitespace_only": not span.quote.strip(),
            })
        for item, document in zip(fixture["documents"], documents, strict=True):
            for index, chunk in enumerate(document["chunks"]):
                spans = [s for s in catalog.spans if s.chunk_id == chunk["chunk_id"]]
                expected = item["expected"]["chunks"][index]
                compare(f"{chunk['chunk_id']}.block_quotes", [s.quote for s in spans],
                        expected["block_quotes"])
                compare(f"{chunk['chunk_id']}.reconstruction",
                        "".join(s.quote for s in spans), chunk["text"])
                offset = chunk["start_offset"]
                for span in spans:
                    compare(f"{chunk['chunk_id']}.{span.span_id}.contiguous",
                            span.start_offset, offset)
                    compare(f"{chunk['chunk_id']}.{span.span_id}.slice",
                            document["content"][span.start_offset:span.end_offset], span.quote)
                    offset = span.end_offset
                compare(f"{chunk['chunk_id']}.end", offset, chunk["end_offset"])
        expected = fixture["expected"]
        totals = {
            "chunks": len(contexts), "blocks": len(catalog.spans),
            "eligible": len(catalog.eligible_ids),
            "whitespace": sum(not s.quote.strip() for s in catalog.spans),
            "raw_utf8_bytes": sum(d["raw_utf8_bytes"] for d in row["documents"]),
            "processed_utf8_bytes": sum(d["processed_utf8_bytes"] for d in row["documents"]),
            "emitted_chunk_utf8_bytes": sum(len(c["text"].encode()) for c in contexts),
            "overlap_codepoints": sum(d["overlap_codepoints"] for d in row["documents"]),
            "unique_covered_codepoints": sum(d["unique_covered_codepoints"]
                                           for d in row["documents"]),
            "max_block_codepoints": max(len(s.quote) for s in catalog.spans),
            "max_block_utf8_bytes": max(len(s.quote.encode()) for s in catalog.spans),
            "all_contexts_within_2048_bytes": all(len(c["text"].encode()) <= 2048
                                                 for c in contexts),
            "all_blocks_within_2048_bytes": all(len(s.quote.encode()) <= 2048
                                               for s in catalog.spans),
        }
        row["totals"] = totals
        for key in totals.keys() & expected.keys():
            compare(key, totals[key], expected[key])
        # F12 correctly has both booleans false; implication is conditional.
        row["chunk_bound_implies_block_bound"] = all(
            len(c["text"].encode()) > 2048 or all(len(s.quote.encode()) <= 2048
                for s in catalog.spans if s.chunk_id == c["chunk_id"]) for c in contexts)
        compare("chunk_bound_implies_block_bound", row["chunk_bound_implies_block_bound"], True)
        compare("status", row["original_admission"]["status"], expected["status"])
        compare("rejection_codes", row["original_admission"]["safe_rejection_codes"],
                expected["rejection_codes"])
        schema = answer_schema_thinking(catalog)
        schema_bytes = len(canonical(schema))
        for language in ("ko", "en"):
            messages = answer_messages_thinking("", catalog, language)
            payload = safe_payload(messages).encode("utf-8")
            wire_bytes = len(json.dumps(request_body(messages, schema)).encode("utf-8"))
            observation = {"M0_sha256": sha(payload), "M0_bytes": len(payload),
                           "schema_bytes": schema_bytes, "wire_bytes": wire_bytes}
            original = row["original_admission"]["renderings"].get(language)
            bounds = {"envelope": len(payload) <= 6656, "schema": schema_bytes <= 4096,
                      "reserved_wire": wire_bytes + 4096 <= 32768}
            row["renderings"][language] = {
                **observation, "bounds": bounds,
                "limits": {"envelope": 6656, "schema": 4096, "wire": 32768},
                "reserves": {"question_increment": 1024, "wrapper": 512, "wire": 4096},
                "scope": "diagnostic_only" if original is None else "original_comparison",
            }
            compare(f"{language}.render_bounds", bounds, expected["render_bounds"][language])
            if original is not None:
                compare(f"{language}.original_rendering", observation, original)
        row["originals_after_sha256"] = sha(encoded({"family": family, "documents": documents}))
        compare("originals_unchanged", row["originals_after_sha256"], sha(originals))
        compare("fixture_unchanged", encoded(fixture).decode(), original_fixture.decode())
        compare("admission_unchanged", encoded(row["original_admission"]).decode(),
                admission_bytes.decode())
        row["status"] = "passed" if not row["discrepancies"] else "discrepancy"
    except Exception as error:  # noqa: BLE001 - preserve any first unexpected failure.
        row["unexpected_error"] = {"type": type(error).__name__, "message": str(error)}
    return row


def safe_file(root, name):
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or name.startswith("/") or any(p in {"", ".", ".."} for p in name.split("/"))):
        raise ValueError("diagnostic_path")
    path = Path(root)
    for part in name.split("/"):
        path /= part
        info = path.lstat()
        if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("diagnostic_linked_path")
    return path


def read_bound(root, name):
    path = safe_file(root, name)
    before = path.stat()
    with path.open("rb") as stream:
        raw = stream.read(16 * 1024 * 1024 + 1)
    stable = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    after = path.stat()
    if (len(raw) > 16 * 1024 * 1024
            or any(getattr(before, key) != getattr(after, key) for key in stable)):
        raise ValueError("diagnostic_unstable_file")
    return raw


class Binding:
    """Small read-only Git/working-byte proof; never reads beyond explicit paths."""

    def __init__(self, root, expected, implementation_paths=()):
        self.root, self.expected = Path(root), dict(expected)
        self.implementation_paths = tuple(implementation_paths)
        self.evidence = {"head": None, "implementation_commit": None, "hashes": {}}

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True,
                              capture_output=True).stdout

    def verify(self, *, committed=False):
        head = self.git("rev-parse", "HEAD").decode("ascii").strip()
        if not re.fullmatch(r"[a-f0-9]{40}", head):
            raise ValueError("diagnostic_head")
        if self.evidence["head"] not in (None, head):
            raise ValueError("diagnostic_head_drift")
        self.evidence["head"] = head
        identities = set()
        observed = {}
        for name, expected in sorted(self.expected.items()):
            target = safe_file(self.root, name)
            info = target.stat()
            identity = (info.st_dev, info.st_ino)
            if info.st_ino and identity in identities:
                raise ValueError("diagnostic_file_alias")
            identities.add(identity)
            raw = read_bound(self.root, name)
            observed[name] = sha(raw)
            if observed[name] != expected:
                raise ValueError(f"diagnostic_hash_mismatch:{name}")
            if committed and self.git("show", f"{head}:{name}") != raw:
                raise ValueError(f"diagnostic_committed_mismatch:{name}")
        if self.git("rev-parse", "HEAD").decode("ascii").strip() != head:
            raise ValueError("diagnostic_head_drift")
        self.evidence["hashes"] = observed
        if committed and self.implementation_paths:
            self.evidence["implementation_commit"] = self.git(
                "log", "-1", "--format=%H", head, "--", *self.implementation_paths
            ).decode("ascii").strip()
        return copy.deepcopy(self.evidence)


def official_binding():
    raw = read_bound(ROOT, FREEZE)
    if sha(raw) != FREEZE_SHA:
        raise ValueError("diagnostic_freeze_hash")
    frozen = strict_json(raw)["bound_files"]
    if len(frozen) != 77:
        raise ValueError("diagnostic_freeze_count")
    expected = {**frozen, FREEZE: FREEZE_SHA, DESIGN: DESIGN_SHA,
                **{name: sha(read_bound(ROOT, name)) for name in OWN_FILES}}
    if expected[FIXTURE] != FIXTURE_SHA:
        raise ValueError("diagnostic_fixture_hash")
    return Binding(ROOT, expected, OWN_FILES)


def durable_write(path, raw, *, append=False):
    with Path(path).open("ab" if append else "xb") as stream:
        if stream.write(raw) != len(raw):
            raise OSError("diagnostic_short_write")
        stream.flush()
        os.fsync(stream.fileno())


def _run(output, setup, kind):
    """Internal common runner. The CLI fixes all arguments; units use temp paths."""
    output = Path(output)
    output.mkdir()  # Exclusive reservation, never overwrite or resume.
    first_error, later_errors, completed, attempted = None, [], [], []
    start = datetime.now(UTC).isoformat()
    reservation = {"kind": kind, "started_at": start, "inputs": None}
    rows_path = output / "rows.jsonl"
    before, binding, fixtures = None, None, None
    try:
        binding, fixtures = setup()
        before = binding.verify(committed=True)
        reservation["inputs"] = before
    except Exception as error:  # noqa: BLE001 - terminal evidence requires every failure.
        first_error = {"stage": "initial_binding", "type": type(error).__name__,
                       "message": str(error)}
        reservation["inputs"] = copy.deepcopy(binding.evidence) if binding else None
    try:
        durable_write(output / "reservation.json", encoded(reservation))
        if first_error is None:
            durable_write(rows_path, b"")
            for fixture in fixtures:
                binding.verify()
                attempted.append(fixture["id"])
                row = measure_fixture(fixture)
                if row["status"] != "passed":
                    first_error = {"stage": "fixture", "fixture": fixture["id"],
                                   "type": row["status"],
                                   "unexpected_error": row["unexpected_error"],
                                   "discrepancies": row["discrepancies"]}
                durable_write(rows_path, encoded(row), append=True)
                completed.append(fixture["id"])
                if first_error is not None:
                    break
            if first_error is None:
                binding.verify(committed=True)
    except Exception as error:  # noqa: BLE001 - retain first cause and later save failures.
        failure = {"stage": "execution_or_persistence", "type": type(error).__name__,
                   "message": str(error)}
        if first_error is None:
            first_error = failure
        else:
            later_errors.append(failure)
    rows_hash, rows_bytes = None, None
    try:
        rows_raw = read_bound(output, "rows.jsonl") if rows_path.exists() else b""
        rows_hash, rows_bytes = sha(rows_raw), len(rows_raw)
    except Exception as error:  # noqa: BLE001 - attempt terminal even if row read fails.
        failure = {"stage": "rows_read", "type": type(error).__name__,
                   "message": str(error)}
        if first_error is None:
            first_error = failure
        else:
            later_errors.append(failure)
    summary = {"kind": kind, "status": "passed" if first_error is None else "failed",
               "completed_ids": completed, "attempted_ids": attempted,
               "unexecuted_ids": [name for name in IDS if name not in attempted],
               "rows_sha256": rows_hash, "rows_bytes": rows_bytes,
               "terminal_durable": True, "first_error": first_error,
               "later_persistence_errors": later_errors,
               "quality_candidate_created": False, **ZERO_COUNTERS}
    terminal = {"summary": summary, "started_at": start,
                "finished_at": datetime.now(UTC).isoformat(),
                "input_binding_before": before,
                "input_binding_last_verified": copy.deepcopy(binding.evidence) if binding else None}
    try:
        # A failed fsync must leave only a non-authoritative pending artifact.
        # Exclusive hard-link publication cannot overwrite an existing receipt.
        pending = output / "receipt.pending.json"
        durable_write(pending, encoded(terminal))
        os.link(pending, output / "receipt.json")
    except Exception as error:  # noqa: BLE001 - never report success after failed publish.
        failure = {"stage": "terminal_persistence", "type": type(error).__name__,
                   "message": str(error)}
        if first_error is None:
            summary["first_error"] = failure
        else:
            later_errors.append(failure)
        summary["status"], summary["terminal_durable"] = "failed", False
    return summary


def run_unit(output, binding):
    output = Path(output).absolute()
    if (not output.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
            or output.resolve() == (ROOT / OUTPUT).resolve()):
        raise ValueError("diagnostic_unit_output_requires_temporary_directory")
    return _run(output, lambda: (binding, load_fixtures(read_bound(ROOT, FIXTURE))),
                "unit_verification")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)  # Deliberately no filter, cap, path, resume or retry flags.
    try:
        if (ROOT / OUTPUT).exists():
            raise FileExistsError("diagnostic_output_consumed")
        safe_file(ROOT, ".local")
        summary = _run(
            ROOT / OUTPUT,
            lambda: (official_binding(), load_fixtures(read_bound(ROOT, FIXTURE))),
            "synthetic_admission_diagnostic",
        )
    except Exception as error:  # noqa: BLE001 - CLI must report reservation/setup failure.
        summary = {"kind": "synthetic_admission_diagnostic", "status": "failed",
                   "terminal_durable": False, "first_error": {
                       "type": type(error).__name__, "message": str(error)},
                   "quality_candidate_created": False, **ZERO_COUNTERS}
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0 if summary["status"] == "passed" and summary["terminal_durable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
