"""Literal-text compatibility tests with synthetic sources only."""
import copy
import json

import pytest

from scripts import prepare_meeting_plaintext_source_inventory as probe
from tests import test_prepare_meeting_source_inventory as fixtures
from tests.test_prepare_meeting_source_inventory import source_record, write

source = fixtures.source


@pytest.fixture(autouse=True)
def environment(source, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", source.root)
    monkeypatch.setattr(probe, "HELPER_FILES", probe.legacy.HELPER_FILES)
    monkeypatch.setattr(probe, "SERVICE_FILES", probe.legacy.SERVICE_FILES)


def run(source):
    return probe.prepare(source.path, source.output, "calibration", "adopted-public")


def test_rst_stays_literal_and_preserves_original_identity(source):
    raw = "Heading\n=======\n\n.. include:: missing-secret.txt\n\n:role:`한글🙂` and *markup*.\n".encode()
    item = source_record(source.root, "synthetic-a", 0, raw)
    item.update(path="developers/guide.rst", ingestion_kind="txt")
    source.records[0] = item
    write(source.path, source.manifest)
    manifest_before = source.path.read_bytes()
    receipt = run(source)
    inventory = json.loads((source.output / "inventory.json").read_bytes())
    document = inventory["documents"][0]
    assert document["content"] == raw.decode()
    assert document["chunks"][0]["text"] == raw.decode()
    assert document["source_path"] == document["provenance"]["upstream_path"] == "developers/guide.rst"
    assert document["ingestion_kind"] == "txt"
    assert receipt["manifest"]["sha256"] == probe.sha(manifest_before)
    assert source.path.read_bytes() == manifest_before
    assert inventory["source_processing_version"] == 2
    assert receipt["counts"]["model_calls"] == 0


@pytest.mark.parametrize("declared", [None, "md", "rst", "pdf", True])
def test_rst_needs_explicit_txt_before_raw_read(source, monkeypatch, declared):
    source.records[0]["path"] = "guide.rst"
    if declared is not None:
        source.records[0]["ingestion_kind"] = declared
    write(source.path, source.manifest)
    monkeypatch.setattr(probe, "document_record", lambda *_: pytest.fail("raw document processed"))
    with pytest.raises(ValueError, match="explicit_text_kind_required"):
        run(source)
    assert not source.output.exists()


def test_original_markdown_bytes_chunks_and_metadata_survive(source):
    original = copy.deepcopy(source.records[0])
    run(source)
    document = json.loads((source.output / "inventory.json").read_bytes())["documents"][0]
    expected = probe.legacy.document_record(source.manifest["families"][0], original,
                                           (source.root / original["local_raw_snapshot"]).read_bytes())
    assert document == expected | {"source_path": original["path"], "ingestion_kind": "md"}


def test_does_not_mutate_manifest_when_kind_routing(source):
    source.records[0].update(path="guide.rst", ingestion_kind="txt")
    before = copy.deepcopy(source.manifest)
    selected, _ = probe.classify(source.manifest, "calibration", "adopted-public")
    assert selected[0][1] is source.records[0]
    assert source.manifest == before


def test_new_entrypoint_still_rejects_reused_output(source):
    run(source)
    with pytest.raises(ValueError, match="output_exists_or_invalid"):
        run(source)


def test_pending_synthetic_sources_still_fail_all_mode(source):
    with pytest.raises(ValueError):
        probe.prepare(source.path, source.output, "calibration", "adopted-all")
    assert not source.output.exists()


@pytest.mark.parametrize("path,kind", [("guide.html", "txt"), ("guide.md", "txt"), ("guide.txt", "md")])
def test_unsupported_or_mismatched_kind_is_rejected(source, path, kind):
    source.records[0].update(path=path, ingestion_kind=kind)
    write(source.path, source.manifest)
    with pytest.raises(ValueError, match="explicit_text_kind_required"):
        run(source)
