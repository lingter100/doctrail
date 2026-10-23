"""Provenance checks for the small real-data integration corpus (no model calls)."""

import json

from scripts.prepare_meeting_fixtures import MANIFEST, ROOT, sanitize, verify


def test_public_fixture_hashes_and_license_are_reproducible():
    report = verify()
    assert report["synthetic"] is False
    assert len(report["files"]) == 4
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert len({source["revision"] for source in manifest["sources"]}) == 1
    for source in manifest["sources"]:
        assert source["license"] == "BSD-3-Clause"
        assert source["revision"] in source["raw_url"]
        text = (ROOT / source["fixture"]).read_text(encoding="utf-8")
        assert "pwd=" not in text
        assert "@googlegroups.com" not in text
    license_text = (ROOT / manifest["sources"][0]["fixture"]).read_text(encoding="utf-8")
    assert "Copyright (c) 2017, Project Jupyter Contributors" in license_text


def test_sanitization_removes_call_access_without_rewriting_discussion():
    raw = (b"# Notes\r\n**Video-conference link:** secret\r\n"
           b"contact list@googlegroups.com\r\nDecision: keep seven days.\r\n")
    assert sanitize(raw) == b"# Notes\nDecision: keep seven days.\n"
