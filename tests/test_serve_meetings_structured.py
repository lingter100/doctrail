"""Fake owned children/HTTP thread only: no registry, GPU, model or server."""
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import serve_meetings_structured as m


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    model = tmp_path / "model"
    model.mkdir()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"model": m.MODEL_ID, "gguf": {"sha256": m.MODEL_SHA256}}))
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"not executable")
    children, waits, leases, calls = [], [], [], []
    state = SimpleNamespace(fail=None, terminate_error=False)
    @contextmanager
    def lease(path):
        leases.append(("enter", path.name))
        try:
            yield
        finally:
            leases.append(("exit", path.name))
    def prepare(manifest_path, model_path, **options):
        calls.append(("prepare", options))
        assert manifest_path == manifest and model_path == model and options == {"allow_download": False}
        if state.fail == "prepare":
            raise RuntimeError("private preparation failure")
        return {"server_path": "runtime/server.exe", "model": {"path": "model.gguf"}}
    class Child:
        def __init__(self, argv, **kwargs):
            if state.fail == "java" and len(children) == 1:
                raise OSError("private Java launch failure")
            self.argv, self.kwargs, self.stopped = argv, kwargs, False
            children.append(self)
        def poll(self):
            return 0 if self.stopped else None
        def terminate(self):
            if state.terminate_error:
                raise OSError("private terminate failure")
            self.stopped = True
        def kill(self):
            self.stopped = True
        def wait(self, timeout):
            return 0
    class Thread:
        def __init__(self, **kwargs):
            self.live = False
        def start(self):
            self.live = True
        def join(self, timeout):
            self.live = False
        def is_alive(self):
            return self.live
    class Generator:
        close_error = None
        def __init__(self, *args, **kwargs):
            calls.append(("generator", args))
            calls.append(("generator_options", kwargs))
            self.profile = kwargs["profile"]
        def begin_request(self, deadline):
            calls.append(("begin", deadline))
        def end_request(self):
            calls.append(("end",))
        def load(self):
            if state.fail == "load":
                raise RuntimeError("private identity failure")
        def public_metadata(self):
            return {"repo_id": m.MODEL_ID, "revision": "gguf-sha256:" + m.MODEL_SHA256}
        def close(self):
            calls.append(("close",))
    def ready(process, url, **kwargs):
        waits.append((url, kwargs))
        if state.fail == "ready":
            raise TimeoutError("private health failure")
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace())
    monkeypatch.setattr(m, "MANIFEST", manifest)
    monkeypatch.setattr(m, "MODEL", model)
    monkeypatch.setattr(m, "worker_lease", lease)
    monkeypatch.setattr(m, "prepare", prepare)
    monkeypatch.setattr(m, "StructuredGenerator", Generator)
    monkeypatch.setattr(m.subprocess, "Popen", Child)
    monkeypatch.setattr(m.threading, "Thread", Thread)
    monkeypatch.setattr(m, "java_executable", lambda: Path("fake-java.exe"))
    monkeypatch.setattr(m, "wait_ready", ready)
    monkeypatch.setattr(m, "make_server", lambda app, port: SimpleNamespace(run=lambda: None, should_exit=False))
    return SimpleNamespace(jar=jar, database=tmp_path / "isolated.sqlite3", state=state, children=children,
                           waits=waits, leases=leases, calls=calls, manifest=manifest)


def run(f, **kwargs):
    return m.start_services(jar=f.jar, database=f.database, java_port=12341, worker_port=12342,
                            native_port=12343, enable_structured=True, **kwargs)


def test_explicit_opt_in_before_leases_or_preparation(launcher):
    with pytest.raises(ValueError, match="explicit_opt_in"), m.start_services(jar=launcher.jar, database=launcher.database):
        pass
    assert not launcher.calls and not launcher.leases and not launcher.children


def test_pinned_native_args_truthful_gpu_context_worker_and_cleanup(launcher):
    f = launcher
    with run(f) as services:
        assert services["java_url"] == "http://127.0.0.1:12341"
        native, java = f.children
        for flag, value in (("--ctx-size", "8192"), ("--parallel", "1"), ("--n-gpu-layers", "99"),
                            ("--threads", "2"), ("--threads-batch", "2"), ("--alias", m.MODEL_SHA256), ("--fit", "off")):
            assert native.argv[native.argv.index(flag) + 1] == value
        assert "--no-context-shift" in native.argv and "--no-warmup" in native.argv
        assert java.kwargs["env"]["DOCTRAIL_GENERATION_URL"] == services["worker_url"]
        assert "--doctrail.rag-answer-enabled=false" in java.argv
        assert "--doctrail.answer-neighbors-enabled=true" in java.argv
        assert services["report"]["answer_neighbors_enabled"] is True
        assert len(f.waits) == 3 and all(0 < options["timeout"] <= 120 for _, options in f.waits)
        assert services["report"]["native_settings"]["gpu_layers"] == 99
        token = native.kwargs["env"]["LLAMA_API_KEY"]
        assert token not in json.dumps(services["report"]) and token not in str(native.argv)
        report = services["report"]
        assert services["runtime"].generator is services["generator"]
        assert report["startup_stage"] == "ready"
    assert all(child.stopped for child in f.children)
    assert report["cleanup"]["owned_children_absent"] and report["cleanup"]["worker_stopped"]
    assert report["owned_exit_codes"] == [0, 0]
    assert len(f.leases) == 6 and [name for action, name in f.leases if action == "exit"] == [
        "meeting-llama.lease", "meeting-generation.worker.lock", "meeting-generation.gpu.lock"]


@pytest.mark.parametrize("stage,children", [("prepare", 0), ("ready", 1), ("load", 1), ("java", 1)])
def test_startup_failure_closes_only_owned_processes(launcher, stage, children):
    f = launcher
    f.state.fail = stage
    report = m.FailureRecord({"first_failure": None, "secondary_failures": []})
    with pytest.raises((RuntimeError, TimeoutError, OSError)), run(f, report=report):
        pytest.fail("must not yield")
    assert len(f.children) == children and all(child.stopped for child in f.children)
    assert report["first_failure"] is not None and "private" not in json.dumps(report)
    assert report["cleanup"]["owned_children_absent"]


def test_cleanup_failure_preserves_original_body_error(launcher):
    f = launcher
    original = ValueError("private body failure")
    report = m.FailureRecord({"first_failure": None, "secondary_failures": []})
    with pytest.raises(ValueError) as caught, run(f, report=report):
        f.state.terminate_error = True
        raise original
    assert caught.value is original and report.errors[0] is original
    assert report["secondary_failures"] and all(child.stopped for child in f.children)


def test_success_cannot_hide_cleanup_failure(launcher):
    with pytest.raises(RuntimeError, match="owned_cleanup"), run(launcher):
        launcher.state.terminate_error = True


def test_other_identity_rejected_before_native_dispatch(launcher):
    launcher.manifest.write_text(json.dumps({"model": "other/model", "gguf": {"sha256": "0" * 64}}))
    with pytest.raises(ValueError, match="identity"), run(launcher):
        pass
    assert not launcher.children



def test_unknown_profile_rejected_before_owned_side_effects(launcher):
    with pytest.raises(ValueError, match="unknown_structured_profile"), run(launcher, profile="other"):
        pass
    assert not launcher.calls and not launcher.leases and not launcher.children


def test_qwen_launches_first_shard_with_explicit_instance_profile(launcher, monkeypatch):
    f = launcher
    binding = {"binary": f.jar.parent / "shared-runtime/llama-server.exe",
               "entry": f.jar.parent / "00001.gguf", "alias": "a" * 64}
    calls = []
    def prepare(manifest, assets, runtime, deadline):
        calls.append((manifest, assets, runtime, deadline))
        return binding
    monkeypatch.setattr(m, "prepare_qwen_assets", prepare)
    with run(f, profile=m.QWEN_PROFILE) as service:
        argv = f.children[0].argv
        assert argv[argv.index("--model") + 1] == str(binding["entry"])
        assert argv[argv.index("--alias") + 1] == binding["alias"]
        assert service["report"]["profile"] == m.QWEN_PROFILE
        assert ("generator_options", {"profile": m.QWEN_PROFILE, "qwen_assets": binding}) in f.calls
        assert not any(call[0] == "prepare" for call in f.calls)
        assert len(calls) == 1 and len(f.leases) == 3
    assert all(child.stopped for child in f.children)
