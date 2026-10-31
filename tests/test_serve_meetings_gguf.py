"""Synthetic launcher configuration/cleanup tests, without GPU or network."""
import json
from contextlib import nullcontext

import pytest

from doctrail.inference import WorkerError
from doctrail.meeting_worker import worker_lease
from scripts import serve_meetings_gguf as launcher


def fixture(monkeypatch, tmp_path, *, fail=False):
    calls, stopped = [], []
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"gguf": {"sha256": "a" * 64}}), encoding="utf-8")
    receipt = {"server_path": "runtime/llama-server.exe", "model": {"path": "model.gguf"}}
    monkeypatch.setattr(launcher, "worker_lease", lambda p: nullcontext())
    monkeypatch.setattr(launcher, "prepare", lambda *a, **k: receipt)
    monkeypatch.setattr(launcher, "stop_process", stopped.append)
    child = object()

    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        return child

    def ready(*args, **kwargs):
        if fail:
            raise TimeoutError("test_timeout")
        return {"status": "ok"}

    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    monkeypatch.setattr(launcher, "wait_ready", ready)
    return manifest, calls, stopped, child


def test_configuration_auth_and_owned_cleanup(tmp_path, monkeypatch):
    manifest, calls, stopped, child = fixture(monkeypatch, tmp_path)
    monkeypatch.setenv("LLAMA_ARG_HOST", "0.0.0.0")
    token = "s" * 48
    with launcher.start_llama(log_dir=tmp_path / "logs", model_dir=tmp_path,
                             manifest=manifest, port=9000, token=token) as service:
        assert service.url == "http://127.0.0.1:9000"
        assert service.manifest == manifest
        assert token not in repr(service)
        command, options = calls[0]
        assert token not in " ".join(command)
        assert command[command.index("--host") + 1] == "127.0.0.1"
        assert command[command.index("--alias") + 1] == "a" * 64
        assert options["env"]["LLAMA_API_KEY"] == token
        assert "LLAMA_ARG_HOST" not in options["env"]
        assert "--log-disable" in command and "--no-webui" in command
        assert not stopped
    assert stopped == [child]


def test_failed_startup_stops_only_owned_child(tmp_path, monkeypatch):
    manifest, calls, stopped, child = fixture(monkeypatch, tmp_path, fail=True)
    with (pytest.raises(TimeoutError),
          launcher.start_llama(log_dir=tmp_path, model_dir=tmp_path, manifest=manifest, port=9000)):
        pytest.fail("startup must fail")
    assert len(calls) == 1 and stopped == [child]


@pytest.mark.parametrize("kwargs", [{"token": "short"}, {"token": "x" * 32 + "\n"},
                                    {"port": 65536}, {"runtime_dir": "elsewhere"}])
def test_invalid_configuration_never_starts(tmp_path, monkeypatch, kwargs):
    manifest, calls, _, _ = fixture(monkeypatch, tmp_path)
    with (pytest.raises(ValueError),
          launcher.start_llama(log_dir=tmp_path, model_dir=tmp_path, manifest=manifest, **kwargs)):
        pytest.fail("invalid configuration")
    assert not calls


@pytest.mark.parametrize("lock_name", ["meeting-generation.worker.lock",
                                       "meeting-generation.gpu.lock"])
def test_existing_worker_or_gpu_owner_blocks_before_allocation(tmp_path, monkeypatch, lock_name):
    manifest, calls, stopped, _ = fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher, "worker_lease", worker_lease)
    with (worker_lease(tmp_path / ".local" / lock_name),
          pytest.raises(WorkerError, match="generation_worker_already_running"),
          launcher.start_llama(log_dir=tmp_path, model_dir=tmp_path, manifest=manifest, port=9000)):
        pytest.fail("existing owner must prevent GPU allocation")
    assert not calls and not stopped


@pytest.mark.parametrize("fail", [False, True])
def test_shared_gpu_lease_covers_spawn_readiness_and_cleanup(tmp_path, monkeypatch, fail):
    manifest, _, stopped, child = fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher, "worker_lease", worker_lease)
    shared = tmp_path / ".local/meeting-generation.gpu.lock"
    worker = tmp_path / ".local/meeting-generation.worker.lock"
    observed = []

    def assert_held(stage):
        with (pytest.raises(WorkerError, match="generation_worker_already_running"),
              worker_lease(shared)):
            pytest.fail("GPU lease must be held")
        # The admission probe must not prevent the new GGUF worker from starting.
        with worker_lease(worker):
            pass
        observed.append(stage)

    def spawn(*args, **kwargs):
        assert_held("spawn")
        return child

    def ready(*args, **kwargs):
        assert_held("ready")
        if fail:
            raise TimeoutError("test_timeout")
        return {"status": "ok"}

    def stop(process):
        assert_held("stop")
        stopped.append(process)

    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    monkeypatch.setattr(launcher, "wait_ready", ready)
    monkeypatch.setattr(launcher, "stop_process", stop)
    outcome = pytest.raises(TimeoutError) if fail else nullcontext()
    with (outcome,
          launcher.start_llama(log_dir=tmp_path, model_dir=tmp_path, manifest=manifest, port=9000)):
        assert_held("service")
    assert observed == (["spawn", "ready", "stop"] if fail
                        else ["spawn", "ready", "service", "stop"])
    assert stopped == [child]
    with worker_lease(shared):
        pass
