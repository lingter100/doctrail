"""Fresh synthetic source snapshots only; never read either evaluation split."""
import copy
import json
import unicodedata
from types import SimpleNamespace

import pytest

from doctrail.ingest import extract
from scripts import prepare_meeting_source_inventory as probe


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(probe.encoded(value))


def source_record(root, identity, ordinal, raw, phase="calibration"):
    name = f".local/raw/{identity}.md"
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    content, _ = extract(raw, "md")
    original = raw.decode("utf-8")
    return {"source_id": identity, "document_id": identity, "revision": 1,
        "registration_ordinal": ordinal, "origin": "public", "title": "Synthetic source fixture",
        "path": f"{identity}.md", "immutable_url": f"https://example.invalid/pinned/{identity}.md",
        "local_raw_snapshot": name, "raw_sha256": probe.sha(raw), "processed_sha256": probe.sha(content.encode()),
        "git_blob_sha1": probe.git_blob(raw), "raw_size_bytes": len(raw), "processed_codepoints": len(content),
        "raw_encoding": "UTF-8", "bom": raw.startswith(b"\xef\xbb\xbf"),
        "lf_count": original.count("\n"), "cr_count": original.count("\r"),
        "trailing_lf": original.endswith("\n"),
        "nfc_identity_verified": unicodedata.is_normalized("NFC", original),
        "service_normalization_identity_verified": original == content,
        "license_id": "synthetic-test-license", "page": None, "meeting_date": None,
        "adoption_verdict": f"ADOPTED_FOR_{phase.upper()}_SOURCE_WITH_REGISTERED_CONSTRAINTS"}


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    monkeypatch.setattr(probe, "HELPER_FILES", {"new-helper.py", "new-tests.py"})
    monkeypatch.setattr(probe, "SERVICE_FILES", {"ingest.py", "retrieval.py", "Ingest.java", "Retrieval.java"})
    for name in probe.HELPER_FILES | probe.SERVICE_FILES:
        (tmp_path / name).write_text("# synthetic dependency\n")
    for name in ("registry.json", "freeze.json"):
        (tmp_path / name).write_text('{"metadata":"synthetic"}')
    records = [source_record(tmp_path, "synthetic-a", 0, b"First synthetic document.\n"),
               source_record(tmp_path, "synthetic-b", 1, b"Second synthetic document.\n")]
    manifest = {"schema_version": 1, "phase": "calibration", "families": [{
        "family_id": "SYNTHETIC-PUBLIC-FIXTURE", "origin": "public", "repository": "synthetic/test",
        "immutable_commit": "a" * 40, "license": {"spdx": "synthetic-test-license"},
        "source_suitability": {"verdict": "ADOPTED"}, "sources": records}, {
        "family_id": "SYNTHETIC-PENDING-FIXTURE", "origin": "synthetic",
        "sources": [{"source_id": "synthetic-pending", "document_id": "synthetic-pending",
                     "revision": 1, "registration_ordinal": 2, "raw_sha256": None}]}],
        "processing_protocol": {"id": "synthetic-processing-v1",
            "existing_service_reference_sha256": {name: probe.sha((tmp_path / name).read_bytes())
                                                  for name in probe.SERVICE_FILES},
            "chunk_algorithm": copy.deepcopy(probe.CHUNK_CONTRACT),
            "chunk_id_format": "{document_id}-r1-c{ordinal:04d}"},
        "family_registry": {"path": "registry.json", "sha256": probe.sha((tmp_path / "registry.json").read_bytes())},
        "active_comparison_source_freeze": {"path": "freeze.json", "sha256": probe.sha((tmp_path / "freeze.json").read_bytes())}}
    path = tmp_path / "manifest.json"
    write(path, manifest)
    return SimpleNamespace(root=tmp_path, path=path, manifest=manifest, records=records,
                           output=tmp_path / ".local/inventory")


def run(source, phase="calibration", mode="adopted-public"):
    return probe.prepare(source.path, source.output, phase, mode)


def inventory(source):
    return json.loads((source.output / "inventory.json").read_bytes())


def replace_first(source, raw):
    source.records[0] = source_record(source.root, "synthetic-a", 0, raw)
    write(source.path, source.manifest)


def test_complete_documents_chunks_and_explicit_pending_exclusions(source):
    receipt = run(source)
    data = inventory(source)
    assert len(data["documents"]) == 2 and len(data["excluded_sources"]) == 1
    first = data["documents"][0]
    assert first["content"] == "First synthetic document.\n"
    assert first["pages"] == [{"start_offset": 0, "end_offset": 26, "page": None}]
    assert first["chunks"] == [{"chunk_id": "synthetic-a-r1-c0000", "ordinal": 0,
        "text": first["content"], "text_sha256": first["processed_sha256"],
        "start_offset": 0, "end_offset": 26, "page": None}]
    assert first["provenance"]["upstream_path"] == "synthetic-a.md"
    assert "attribution" in first["provenance"]["processing_notice"]
    assert data["excluded_sources"][0]["reason"] == "excluded_by_explicit_adopted_public_mode"
    assert receipt["inventory_sha256"] == probe.sha((source.output / "inventory.json").read_bytes())
    assert receipt["manifest"]["sha256"] == probe.sha(source.path.read_bytes())
    assert receipt["counts"]["registered_sources"] == 3
    assert receipt["counts"]["processed_documents"] == 2 and receipt["java_parity_verified"] is False
    assert all(receipt["counts"][name] == 0 for name in (
        "selected_contexts", "questions", "oracles", "synthetic_bodies_authored",
        "tokenizer_runs", "model_calls", "downloads", "human_reviews"))
    assert set(receipt["bound_files"]) == probe.SERVICE_FILES | probe.HELPER_FILES


def test_natural_manifest_order_is_sorted_by_registered_ordinal(source):
    source.records.reverse()
    source.manifest["families"].reverse()
    write(source.path, source.manifest)
    run(source)
    assert [doc["document_id"] for doc in inventory(source)["documents"]] == ["synthetic-a", "synthetic-b"]


def test_preparation_is_deterministic_in_distinct_new_directories(source):
    before = run(source)
    data = (source.output / "inventory.json").read_bytes()
    source.output = source.root / ".local/second-inventory"
    assert run(source) == before
    assert (source.output / "inventory.json").read_bytes() == data


def test_existing_ingest_handles_bom_crlf_cr_nfc_and_unicode_codepoints(source):
    raw = b"\xef\xbb\xbf" + "Cafe\u0301\r\n한글 🧊\rTail\n".encode()
    replace_first(source, raw)
    run(source)
    document = inventory(source)["documents"][0]
    assert document["content"] == "Café\n한글 🧊\nTail\n"
    assert document["processed_codepoints"] == len("Café\n한글 🧊\nTail\n")
    assert document["raw_sha256"] != document["processed_sha256"]
    assert document["raw_size_bytes"] == len(raw)


def test_chunk_offsets_use_codepoints_and_keep_natural_150_overlap(source):
    replace_first(source, ("🧊" * 2300).encode())
    run(source)
    doc = inventory(source)["documents"][0]
    assert [(c["start_offset"], c["end_offset"], c["ordinal"]) for c in doc["chunks"]] == [
        (0, 1000, 0), (850, 1850, 1), (1700, 2300, 2)]
    assert [len(c["text"].encode()) for c in doc["chunks"]] == [4000, 4000, 2400]
    assert all(c["text"] == doc["content"][c["start_offset"]:c["end_offset"]] for c in doc["chunks"])


def test_existing_ascii_space_boundary_search_is_preserved(source):
    content = "a" * 700 + " " + "b" * 699 + " " + "c" * 700
    replace_first(source, content.encode())
    run(source)
    chunks = inventory(source)["documents"][0]["chunks"]
    assert [(c["start_offset"], c["end_offset"]) for c in chunks] == [(0, 701), (551, 1401), (1251, 2101)]


def test_existing_blank_chunk_omission_does_not_trim_whole_document(source):
    replace_first(source, (" " * 1200 + "x").encode())
    run(source)
    doc = inventory(source)["documents"][0]
    assert doc["content"] == " " * 1200 + "x"
    assert [(c["start_offset"], c["end_offset"], c["ordinal"]) for c in doc["chunks"]] == [(850, 1201, 0)]


@pytest.mark.parametrize("field,value", [("raw_sha256", "0" * 64), ("processed_sha256", "0" * 64),
    ("git_blob_sha1", "0" * 40), ("raw_size_bytes", 100), ("processed_codepoints", 100),
    ("bom", True), ("lf_count", 0), ("cr_count", 1), ("trailing_lf", False),
    ("service_normalization_identity_verified", False), ("nfc_identity_verified", False)])
def test_raw_processed_git_blob_and_observation_tampering_fails(source, field, value):
    source.records[0][field] = value
    write(source.path, source.manifest)
    with pytest.raises(ValueError):
        run(source)
    assert not source.output.exists()


@pytest.mark.parametrize("change", [lambda s: s.manifest.update(schema_version=True),
    lambda s: s.records[0].update(revision=True), lambda s: s.records[0].update(registration_ordinal=True),
    lambda s: s.records[1].update(document_id=s.records[0]["document_id"]),
    lambda s: s.records[1].update(source_id=s.records[0]["source_id"]),
    lambda s: s.records[0].update(adoption_verdict="HOLD"),
    lambda s: s.manifest["families"][0]["source_suitability"].update(verdict="HOLD"),
    lambda s: s.manifest["processing_protocol"]["chunk_algorithm"].update(overlap_codepoints=149),
    lambda s: s.records[0].update(local_raw_snapshot="../outside.md"),
    lambda s: s.records[0].update(local_raw_snapshot="C:/outside.md"),
    lambda s: s.records[0].update(path="source.html")])
def test_invalid_registration_protocol_or_source_paths_fail_closed(source, change):
    change(source)
    write(source.path, source.manifest)
    with pytest.raises(ValueError):
        run(source)
    assert not source.output.exists()


def test_explicit_mode_and_phase_required_before_any_source_open(source, monkeypatch):
    original = probe.Snapshots.read

    def guarded(self, path, *args):
        assert Path(path) == source.path
        return original(self, path, *args)
    from pathlib import Path
    monkeypatch.setattr(probe.Snapshots, "read", guarded)
    for phase, mode in (("validation", "adopted-public"), ("calibration", "all")):
        with pytest.raises(ValueError, match="manifest_contract"):
            run(source, phase, mode)


def test_pending_nonpublic_paths_are_never_read(source, monkeypatch):
    pending = source.manifest["families"][1]["sources"][0]
    pending["local_raw_snapshot"] = "/MUST-NOT-READ-SEALED-SOURCE"
    write(source.path, source.manifest)
    run(source)
    assert inventory(source)["excluded_sources"][0]["source_id"] == "synthetic-pending"


def test_bound_service_and_metadata_source_hash_failures(source):
    for filename in ("ingest.py", "registry.json", "freeze.json"):
        path = source.root / filename
        original = path.read_bytes()
        path.write_bytes(b"changed")
        with pytest.raises(ValueError, match="binding_changed"):
            run(source)
        path.write_bytes(original)
    assert not source.output.exists()


def test_output_must_be_new_contained_local_directory_and_never_overwrites(source):
    run(source)
    before = {p.name: p.read_bytes() for p in source.output.iterdir()}
    with pytest.raises(ValueError, match="output_exists_or_invalid"):
        run(source)
    assert {p.name: p.read_bytes() for p in source.output.iterdir()} == before
    source.output = source.root / "public-output"
    with pytest.raises(ValueError, match="output_exists_or_invalid"):
        run(source)
    source.output = source.root.parent / "outside"
    with pytest.raises(ValueError, match="outside_repository"):
        run(source)


def test_each_raw_snapshot_is_read_once_then_checked_and_processed_from_same_bytes(source, monkeypatch):
    original = probe.Snapshots.read
    seen = []

    def replacing(self, path, limit=probe.MAX_METADATA_BYTES):
        raw = original(self, path, limit)
        if path == source.root / source.records[0]["local_raw_snapshot"]:
            seen.append(path)
            path.write_bytes(b"changed after snapshot")
        return raw
    monkeypatch.setattr(probe.Snapshots, "read", replacing)
    run(source)
    assert len(seen) == 1
    assert inventory(source)["documents"][0]["content"] == "First synthetic document.\n"


def test_duplicate_json_keys_bounded_read_and_bad_utf8_are_not_repaired(source):
    source.path.write_bytes(b'{"schema_version":1,"schema_version":1}')
    from doctrail.inference import WorkerError
    with pytest.raises(WorkerError):
        run(source)
    with pytest.raises(ValueError, match="file_limit"):
        probe.Snapshots().read(source.path, limit=2)
    write(source.path, source.manifest)
    raw = b"\xff"
    row = source.records[0]
    (source.root / row["local_raw_snapshot"]).write_bytes(raw)
    row.update(raw_sha256=probe.sha(raw), git_blob_sha1=probe.git_blob(raw), raw_size_bytes=1)
    write(source.path, source.manifest)
    with pytest.raises(UnicodeDecodeError):
        run(source)


def test_symlink_source_is_rejected_before_read(source):
    target = source.root / source.records[0]["local_raw_snapshot"]
    link = source.root / ".local/linked.md"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Creating symlinks requires a Windows privilege")
    source.records[0]["local_raw_snapshot"] = ".local/linked.md"
    write(source.path, source.manifest)
    with pytest.raises(ValueError, match="linked_path"):
        run(source)


def test_split_capable_validation_mode_uses_only_supplied_synthetic_fixture(source):
    source.manifest["phase"] = "validation"
    for row in source.records:
        row["adoption_verdict"] = "ADOPTED_FOR_VALIDATION_SOURCE_WITH_REGISTERED_CONSTRAINTS"
    write(source.path, source.manifest)
    assert run(source, phase="validation")["phase"] == "validation"


def test_cli_reports_only_safe_failure_code(source, monkeypatch, capsys):
    def fail(*args):
        raise ValueError("PRIVATE_SOURCE_TEXT")
    monkeypatch.setattr(probe, "prepare", fail)
    monkeypatch.setattr("sys.argv", ["inventory", "--manifest", str(source.path), "--output",
        str(source.output), "--phase", "calibration", "--mode", "adopted-public"])
    with pytest.raises(SystemExit) as error:
        probe.main()
    out = capsys.readouterr()
    assert error.value.code == 1 and out.err == "source_inventory_preparation_failed\n"
    assert "PRIVATE" not in out.out + out.err


def finalize_synthetic_fixture(source):
    notice = "AI-authored synthetic test document."
    raw = (notice + "\n새 합성 표지 🧊는 민트색이다.\n").encode()
    row = source_record(source.root, "synthetic-pending", 2, raw)
    row.update(origin="synthetic", synthetic_provenance={"ai_authored": True, "fictional": True,
               "author_role": "synthetic-fixture-author", "notice": notice})
    for key in ("git_blob_sha1", "immutable_url", "license_id"):
        del row[key]
    family = source.manifest["families"][1]
    family["source_suitability"] = {"verdict": "ADOPTED"}
    family["sources"] = [row]
    write(source.path, source.manifest)
    return row


def test_adopted_all_requires_pending_synthetic_finalization_before_reading_raw(source, monkeypatch):
    def forbidden(*args):
        pytest.fail("No raw bytes should be read before every registration validates")
    monkeypatch.setattr(probe, "document_record", forbidden)
    with pytest.raises(ValueError, match="source_not_adopted"):
        run(source, mode="adopted-all")
    assert not source.output.exists()


def test_adopted_all_keeps_finalized_synthetic_unicode_and_ai_provenance(source):
    row = finalize_synthetic_fixture(source)
    receipt = run(source, mode="adopted-all")
    data = inventory(source)
    assert len(data["documents"]) == 3 and not data["excluded_sources"]
    document = data["documents"][2]
    assert document["provenance"]["origin"] == "synthetic"
    assert document["provenance"]["synthetic_provenance"] == row["synthetic_provenance"]
    assert document["git_blob_sha1"] is None and "repository" not in document["provenance"]
    assert "새 합성 표지 🧊" in document["content"]
    assert document["chunks"][0]["text"] == document["content"]
    assert receipt["counts"]["excluded_sources"] == 0


@pytest.mark.parametrize("field,value", [("ai_authored", False), ("fictional", 1),
    ("author_role", ""), ("notice", ""), ("notice", "A nonexistent notice.")])
def test_synthetic_provenance_and_in_body_notice_required(source, field, value):
    row = finalize_synthetic_fixture(source)
    row["synthetic_provenance"][field] = value
    write(source.path, source.manifest)
    with pytest.raises(ValueError, match="synthetic"):
        run(source, mode="adopted-all")
    assert not source.output.exists()


def test_public_only_mode_explicitly_excludes_even_finalized_synthetic_without_read(source):
    row = finalize_synthetic_fixture(source)
    (source.root / row["local_raw_snapshot"]).write_bytes(b"changed")
    receipt = run(source, mode="adopted-public")
    assert receipt["counts"]["processed_documents"] == 2 and receipt["counts"]["excluded_sources"] == 1
