"""Tiny files and fake processes only; no real models, registry or native calls."""
import hashlib
import json
import zipfile
from types import SimpleNamespace

import pytest

from scripts import meeting_reasoning_launch as m


def digest(data):
    return {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


@pytest.fixture
def assets(tmp_path, monkeypatch):
    root = tmp_path / "assets"
    for name in ("downloads", "licenses", "runtime"):
        (root / name).mkdir(parents=True)
    (root / "model.gguf").write_bytes(b"model")
    (root / "licenses/LICENSE").write_bytes(b"license")
    files = {"llama-server.exe": b"server", "runtime.dll": b"dll"}
    archive = root / "downloads/runtime.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        for name, data in files.items():
            stream.writestr(name, data)
            (root / "runtime" / name).write_bytes(data)
    spec = {"gguf": {"filename": "model.gguf", **digest(b"model")},
            "llama": {"assets": [{"filename": archive.name, **digest(archive.read_bytes())}]},
            "licenses": [{"filename": "LICENSE", **digest(b"license")}]}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(spec))
    sha = digest(manifest.read_bytes())["sha256"]
    monkeypatch.setattr(m, "MANIFEST_SHA256", sha)
    receipt = {"schema_version": 1, "manifest_sha256": sha,
               "model": {"path": "model.gguf", **digest(b"model")},
               "runtime_files": {name: digest(data) for name, data in files.items()},
               "server_path": "runtime/llama-server.exe",
               "licenses": {"licenses/LICENSE": digest(b"license")}, "quality_verified": False}
    (root / "setup-receipt.json").write_text(json.dumps(receipt))
    return manifest, root, receipt


def test_assets_verified_read_only(assets):
    manifest, root, receipt = assets
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert m.verify_existing_assets(manifest, root) == receipt
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("target", ["model.gguf", "downloads/runtime.zip", "runtime/runtime.dll",
                                    "licenses/LICENSE", "setup-receipt.json", "runtime/extra.dll"])
def test_assets_mutation_rejected(assets, target):
    manifest, root, _ = assets
    (root / target).write_bytes(b"changed")
    with pytest.raises((ValueError, m.GenerationError)):
        m.verify_existing_assets(manifest, root)


def test_assets_reparse_rejected(assets, monkeypatch):
    manifest, root, _ = assets
    monkeypatch.setattr(m, "linked", lambda p: p == root / "runtime")
    with pytest.raises(m.GenerationError):
        m.verify_existing_assets(manifest, root)


def marker(tmp_path):
    clock = [10.0]
    obj = m.StartupMarker(tmp_path / "startup.json", "a" * 32, clock=lambda: clock[0],
                          process=SimpleNamespace(pid=5, create_time=lambda: 12.5))
    return obj, clock


def test_marker_atomic_ready_bound_to_owned_identity_and_original_start(tmp_path):
    obj, clock = marker(tmp_path)
    assert not m.startup_ready(obj.path, "a" * 32, [(5, 12.5)], 9, 11)
    clock[0] = 20
    obj.publish("ready")
    assert m.startup_ready(obj.path, "a" * 32, [(5, 12.5)], 9, 25)
    assert not obj.path.with_name("startup.json.tmp").exists()
    with pytest.raises(ValueError):
        m.StartupMarker(obj.path, "a" * 32)


@pytest.mark.parametrize("change", [{"run_id": "b" * 32}, {"pid": 6}, {"create_time": 12.6},
                                    {"schema_version": True}, {"started_monotonic": 8},
                                    {"phase": "failed"}, {"phase": "ready", "ready_monotonic": 129}])
def test_marker_stale_or_changed_fails_closed(tmp_path, change):
    obj, _ = marker(tmp_path)
    obj.value.update(change)
    obj.path.write_text(json.dumps(obj.value))
    with pytest.raises(m.GenerationError):
        m.startup_ready(obj.path, "a" * 32, [(5, 12.5)], 9, 130)


def test_missing_marker_timeout_uses_original_cli_start(tmp_path):
    path = tmp_path / "missing.json"
    assert not m.startup_ready(path, "a" * 32, [], 10, 129.9)
    with pytest.raises(m.GenerationError, match="generation_startup_timeout"):
        m.startup_ready(path, "a" * 32, [], 10, 130)


def test_guard_resource_failure_kills_only_owned_handles_and_records(monkeypatch):
    class Tree:
        peak, minimum_host, samples = 40, 50, 1
        def __init__(self, *args):
            pass
        def capture(self, process):
            pass
        def sample(self, rss, host):
            assert (rss, host) == (8 * 1024**3, 2 * 1024**3)
            raise RuntimeError("resource")
    monkeypatch.setattr(m, "OwnedTree", Tree)
    killed = []
    child = SimpleNamespace(poll=lambda: None, kill=lambda: killed.append("owned"))
    ps = SimpleNamespace(Process=lambda: object(), virtual_memory=lambda: SimpleNamespace(available=11 * 1024**3))
    report = {}
    guard = m.ReasoningResourceGuard([], [child], report, ps=ps)
    guard.stop = SimpleNamespace(wait=lambda seconds: False, set=lambda: None)
    guard.monitor()
    assert killed == ["owned"]
    with pytest.raises(m.GenerationError):
        guard.close(timeout=0)
    assert report["reasoning_resource_guard"]["failed"] is True


def test_guard_start_ram_before_thread(monkeypatch):
    monkeypatch.setattr(m, "OwnedTree", lambda *args: SimpleNamespace(capture=lambda p: None))
    ps = SimpleNamespace(Process=lambda: object(), virtual_memory=lambda: SimpleNamespace(available=10 * 1024**3 - 1))
    guard = m.ReasoningResourceGuard([], [], {}, ps=ps)
    with pytest.raises(m.GenerationError, match="generation_resource_limit"):
        guard.start()
    assert guard.thread is None
