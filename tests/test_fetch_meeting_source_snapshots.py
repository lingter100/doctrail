"""Synthetic byte fixtures only; never read calibration or validation questions."""
import hashlib
import json
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from scripts import fetch_meeting_source_snapshots as module


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "ROOT", tmp_path)
    raw = b"# Fictional fixture\nNo real meeting.\n"
    commit = "a" * 40
    source = {"source_id": "synthetic-test-public", "path": "docs/policy.md",
        "local_raw_snapshot": ".local/raw/policy.md", "raw_sha256": module.sha(raw),
        "raw_size_bytes": len(raw),
        "git_blob_sha1": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
        "raw_url": f"https://raw.githubusercontent.com/example/fixture/{commit}/docs/policy.md",
        "adoption_verdict": "ADOPTED_FOR_CALIBRATION_SOURCE_WITH_REGISTERED_CONSTRAINTS"}
    manifest = {"schema_version": 1, "phase": "calibration", "families": [
        {"origin": "public", "repository": "example/fixture", "immutable_commit": commit,
         "source_suitability": {"verdict": "ADOPTED"}, "sources": [source]},
        {"origin": "synthetic", "sources": [{"local_raw_snapshot": "must-not-open.md"}]}]}
    path = tmp_path / "manifest.json"
    def save():
        path.write_text(json.dumps(manifest), encoding="utf-8")
    save()
    return SimpleNamespace(root=tmp_path, raw=raw, source=source, manifest=manifest,
                           path=path, save=save, output=tmp_path / ".local/replay")


def test_clean_checkout_restores_exact_bytes_then_offline_cache_verifies(fixture):
    s = fixture
    calls = []
    def fetch(url, limit):
        calls.append((url, limit))
        return s.raw
    result = module.restore(s.path, s.output, "calibration", download=True, fetcher=fetch)
    target = s.root / s.source["local_raw_snapshot"]
    assert target.read_bytes() == s.raw
    assert result["status"] == "passed" and result["sources"][0]["created"]
    assert calls == [(s.source["raw_url"], len(s.raw))]
    cached = module.restore(s.path, s.root / ".local/offline", "calibration", fetcher=fetch)
    assert cached["network_attempts"] == 0 and not cached["sources"][0]["created"]
    assert len(calls) == 1
    assert not (s.root / "must-not-open.md").exists()


def test_network_requires_explicit_flag_even_if_verify_remote(fixture):
    s = fixture
    with pytest.raises(module.FetchError, match="missing_download_disabled"):
        module.restore(s.path, s.output, "calibration")
    with pytest.raises(module.FetchError, match="download_not_authorized"):
        module.restore(s.path, s.output, "calibration", verify_remote=True)
    assert not s.output.exists()


def test_remote_verification_preserves_existing_bytes_and_records_failures(fixture):
    s = fixture
    target = s.root / s.source["local_raw_snapshot"]
    target.parent.mkdir(parents=True)
    target.write_bytes(s.raw)
    before = target.stat().st_mtime_ns
    result = module.restore(s.path, s.output, "calibration", download=True, verify_remote=True,
                            fetcher=lambda *_: s.raw)
    assert result["network_attempts"] == 1 and target.stat().st_mtime_ns == before
    failed = s.root / ".local/failed"
    with pytest.raises(module.FetchError, match="bytes_mismatch"):
        module.restore(s.path, failed, "calibration", download=True, verify_remote=True,
                       fetcher=lambda *_: b"not the registered bytes")
    assert target.read_bytes() == s.raw and target.stat().st_mtime_ns == before
    receipt = json.loads((failed / "receipt.json").read_bytes())
    assert receipt["status"] == "failed" and receipt["network_attempts"] == 1
    assert receipt["sources"] == []


def test_all_existing_files_checked_before_any_download(fixture):
    s = fixture
    second = dict(s.source, source_id="second", local_raw_snapshot=".local/raw/second.md")
    s.manifest["families"][0]["sources"].append(second)
    s.save()
    target = s.root / second["local_raw_snapshot"]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"user existing content")
    def no_fetch(*_):
        pytest.fail("network must not run on a mismatched existing snapshot")
    with pytest.raises(module.FetchError, match="bytes_mismatch"):
        module.restore(s.path, s.output, "calibration", download=True, fetcher=no_fetch)
    assert target.read_bytes() == b"user existing content" and not s.output.exists()


@pytest.mark.parametrize("change", [
    {"raw_url": "https://example.com/fetch"},
    {"raw_url": "http://raw.githubusercontent.com/example/fixture/" + "a" * 40 + "/docs/policy.md"},
    {"raw_size_bytes": True}, {"raw_size_bytes": module.MAX_BYTES + 1},
    {"local_raw_snapshot": "outside.md"}, {"local_raw_snapshot": ".local/../outside.md"},
    {"local_raw_snapshot": ".local/file:stream"}, {"path": "../outside.md"},
])
def test_unregistered_or_unsafe_paths_fail_before_network(fixture, change):
    s = fixture
    s.source.update(change); s.save()
    with pytest.raises(module.FetchError):
        module.restore(s.path, s.output, "calibration", download=True,
                       fetcher=lambda *_: pytest.fail("unexpected network"))
    assert not s.output.exists()


def test_phase_and_mutable_revision_are_rejected(fixture):
    s = fixture
    with pytest.raises(module.FetchError, match="manifest_contract"):
        module.restore(s.path, s.output, "validation")
    s.manifest["families"][0]["immutable_commit"] = "main"; s.save()
    with pytest.raises(module.FetchError, match="family_contract"):
        module.restore(s.path, s.output, "calibration")


def test_output_and_source_ancestor_collision(fixture):
    s = fixture
    with pytest.raises(module.FetchError, match="output_collision"):
        module.restore(s.path, s.root / ".local/raw", "calibration", download=True)
    other = dict(s.source, source_id="other", local_raw_snapshot=".local/raw/policy.md/nested")
    s.manifest["families"][0]["sources"].append(other); s.save()
    with pytest.raises(module.FetchError, match="duplicate_target"):
        module.restore(s.path, s.output, "calibration", download=True)


def test_manifest_changes_during_fetch_do_not_write_snapshot(fixture):
    s = fixture
    def fetch(*_):
        s.path.write_text("{}", encoding="utf-8")
        return s.raw
    with pytest.raises(module.FetchError, match="manifest_changed"):
        module.restore(s.path, s.output, "calibration", download=True, fetcher=fetch)
    assert not (s.root / s.source["local_raw_snapshot"]).exists()


def test_network_error_message_is_redacted(fixture):
    s = fixture
    def fetch(*_):
        raise RuntimeError("PRIVATE REMOTE BODY")
    with pytest.raises(module.FetchError, match="fetch_or_io_failed") as raised:
        module.restore(s.path, s.output, "calibration", download=True, fetcher=fetch)
    assert "PRIVATE" not in str(raised.value)
    assert b"PRIVATE" not in (s.output / "receipt.json").read_bytes()


def test_redirects_are_never_followed():
    request = Request("https://raw.githubusercontent.com/example/a/" + "a" * 40 + "/a.md")
    with pytest.raises(HTTPError):
        module.NoRedirect().redirect_request(request, None, 302, "redirect", {}, "http://localhost")


@pytest.mark.parametrize("header,body", [("9", b"1234"), (None, b"12345"), ("bad", b"1234")])
def test_remote_size_bound_without_real_network(monkeypatch, header, body):
    class Response:
        status = 200
        headers = {} if header is None else {"Content-Length": header}
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def geturl(self): return "https://example.test/pinned"
        def read(self, limit): return body[:limit]
    class Opener:
        def open(self, request, timeout):
            assert timeout == 30
            return Response()
    monkeypatch.setattr(module, "build_opener", lambda *_: Opener())
    with pytest.raises(module.FetchError, match="remote_size"):
        module.download_bytes("https://example.test/pinned", 4)


def test_symlink_target_is_rejected(fixture):
    s = fixture
    (s.root / ".local").mkdir()
    external = s.root / "other"
    external.mkdir()
    try:
        (s.root / ".local/raw").symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    with pytest.raises(module.FetchError, match="linked_path"):
        module.restore(s.path, s.output, "calibration", download=True)
