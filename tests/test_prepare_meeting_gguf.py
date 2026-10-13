"""Synthetic setup safety tests; no network, model or GPU use."""
import hashlib
import io
import json
import stat
import zipfile

import pytest

from scripts.prepare_meeting_gguf import (
    digest,
    download,
    extract_runtime,
    prepare,
    safe_member,
)


def spec(name, content):
    return {"filename": name, "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(), "url": "https://example.test/" + name}


class Response(io.BytesIO):
    def geturl(self):
        return "https://example.test/download"


def archive(path, entries):
    with zipfile.ZipFile(path, "w") as stream:
        for name, content in entries:
            if isinstance(name, str) and "\\" in name:
                raw = zipfile.ZipInfo()
                raw.filename = name
                name = raw
            stream.writestr(name, content)
    return path


@pytest.mark.parametrize("name", ["../bad", "/bad", "C:/bad", "a\\bad", "a/../bad",
                                      "a:stream", "CON", "a/NUL.txt", "a.", "a ", "a?b"])
def test_unsafe_paths(name):
    with pytest.raises(ValueError, match="unsafe_archive_path"):
        safe_member(name)


def test_download_requires_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("network"))
    with pytest.raises(ValueError, match="artifact_missing"):
        download(spec("model.gguf", b"abc"), tmp_path, allow_download=False)


def test_download_atomic_verified_and_reusable(tmp_path, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response(b"abc"))
    expected = spec("model.gguf", b"abc")
    target = download(expected, tmp_path, allow_download=True)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("network"))
    assert download(expected, tmp_path, allow_download=False) == target
    assert list(tmp_path.iterdir()) == [target]
    target.write_bytes(b"bad")
    with pytest.raises(ValueError, match="digest_mismatch"):
        download(expected, tmp_path, allow_download=True)
    assert target.read_bytes() == b"bad"


@pytest.mark.parametrize("bad", [b"bad", b"too long", b"ab"])
def test_failed_download_leaves_no_artifact(tmp_path, monkeypatch, bad):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response(bad))
    with pytest.raises(ValueError):
        download(spec("model.gguf", b"abc"), tmp_path, allow_download=True)
    assert not list(tmp_path.iterdir())


def test_runtime_reverification_detects_modified_and_extra_files(tmp_path):
    source = archive(tmp_path / "runtime.zip", [("bin/llama-server.exe", b"exe"),
                                               ("bin/cuda.dll", b"dll")])
    target = tmp_path / "runtime"
    expected = extract_runtime([source], target)
    assert expected["bin/llama-server.exe"]["sha256"] == hashlib.sha256(b"exe").hexdigest()
    assert extract_runtime([source], target) == expected
    (target / "extra.dll").write_bytes(b"unknown")
    with pytest.raises(ValueError, match="existing_runtime_mismatch"):
        extract_runtime([source], target)
    assert (target / "extra.dll").read_bytes() == b"unknown"
    assert not list(tmp_path.glob(".runtime-*"))


@pytest.mark.parametrize("name", ["../outside", "C:/outside", "x\\outside"])
def test_extraction_rejects_traversal_without_publication(tmp_path, name):
    source = archive(tmp_path / "bad.zip", [("llama-server.exe", b"exe"), (name, b"bad")])
    with pytest.raises(ValueError):
        extract_runtime([source], tmp_path / "runtime")
    assert not (tmp_path / "runtime").exists()


def test_extraction_rejects_symlink(tmp_path):
    entry = zipfile.ZipInfo("link")
    entry.create_system = 3
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    source = archive(tmp_path / "bad.zip", [(entry, b"target")])
    with pytest.raises(ValueError, match="unsupported_archive_entry"):
        extract_runtime([source], tmp_path / "runtime")


def test_extraction_rejects_case_collisions_and_zip_bomb_budget(tmp_path, monkeypatch):
    source = archive(tmp_path / "dup.zip", [("llama-server.exe", b"exe"),
                                          ("LLAMA-SERVER.EXE", b"bad")])
    with pytest.raises(ValueError, match="duplicate_archive_path"):
        extract_runtime([source], tmp_path / "runtime")
    monkeypatch.setattr("scripts.prepare_meeting_gguf.MAX_UNPACKED", 2)
    with pytest.raises(ValueError, match="archive_size_exceeded"):
        extract_runtime([source], tmp_path / "runtime")


def test_prepare_offline_receipt_and_tamper_detection(tmp_path):
    root = tmp_path / "models"
    (root / "downloads").mkdir(parents=True)
    (root / "licenses").mkdir()
    model = root / "model.gguf"
    model.write_bytes(b"gguf")
    runtime = archive(root / "downloads/runtime.zip", [("llama-server.exe", b"exe")])
    license_file = root / "licenses/LICENSE.txt"
    license_file.write_bytes(b"MIT")
    manifest = {"schema_version": 1, "gguf": spec(model.name, model.read_bytes()),
                "llama": {"assets": [spec(runtime.name, runtime.read_bytes())]},
                "licenses": [spec(license_file.name, license_file.read_bytes())]}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    receipt = prepare(manifest_path, root)
    assert receipt["model"] == {"path": "model.gguf", **digest(model)}
    assert receipt["server_path"] == "runtime/llama-server.exe"
    assert str(tmp_path) not in json.dumps(receipt)
    assert prepare(manifest_path, root) == receipt
    (root / "runtime/llama-server.exe").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="existing_runtime_mismatch"):
        prepare(manifest_path, root)
