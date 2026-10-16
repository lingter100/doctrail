"""Synthetic launch and OS-admission checks; never starts a real model."""
import json
from contextlib import nullcontext

import pytest

from doctrail.inference import WorkerError
from doctrail.meeting_qwen35 import GGUF_SHA256, MODEL_ID, MODEL_REVISION
from doctrail.meeting_worker import worker_lease
from scripts import serve_meeting_qwen35 as launcher


def configured(tmp_path, monkeypatch, fail=False):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"model": MODEL_ID, "revision": MODEL_REVISION,
                                   "gguf": {"sha256": GGUF_SHA256}}), encoding="utf-8")
    calls, stopped, prepare_calls = [], [], []
    child = object()
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    def prepare(*args, **kwargs):
        prepare_calls.append(kwargs)
        return {"server_path": "runtime/llama-server.exe", "model": {"path": "model.gguf"}}
    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        return child
    def ready(*args, **kwargs):
        if fail:
            raise TimeoutError("synthetic failure")
        return {"status": "ok"}
    monkeypatch.setattr(launcher, "prepare", prepare)
    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    monkeypatch.setattr(launcher, "wait_ready", ready)
    monkeypatch.setattr(launcher, "stop_process", stopped.append)
    return manifest, calls, stopped, prepare_calls, child


def test_fixed_offload_reasoning_auth_offline_and_cleanup(tmp_path, monkeypatch):
    manifest, calls, stopped, prepared, child = configured(tmp_path, monkeypatch)
    monkeypatch.setenv("LLAMA_ARG_N_GPU_LAYERS", "99")
    monkeypatch.setenv("LLAMA_ARG_REASONING", "on")
    token = "s" * 48
    with launcher.start_llama(log_dir=tmp_path, model_dir=tmp_path,
                             manifest=manifest, port=9000, token=token) as service:
        command, options = calls[0]
        for flag, value in {"--n-gpu-layers": "24", "--reasoning": "off", "--ctx-size": "6144",
                            "--batch-size": "512", "--ubatch-size": "128", "--fit": "off",
                            "--parallel": "1", "--host": "127.0.0.1", "--alias": GGUF_SHA256}.items():
            assert command[command.index(flag) + 1] == value
        assert all(flag in command for flag in ("--no-context-shift", "--no-webui", "--log-disable"))
        assert token not in repr(service) and token not in repr(command)
        assert options["env"]["LLAMA_API_KEY"] == token
        assert not any(key.startswith("LLAMA_ARG_") for key in options["env"])
        assert options["env"]["HF_HUB_OFFLINE"] == "1"
    assert stopped == [child] and prepared == [{"allow_download": False}]


@pytest.mark.parametrize("lock", ["meeting-generation.gpu.lock", "meeting-generation.worker.lock",
                                  "meeting-llama.lease"])
def test_shared_4b_or_torch_ownership_prevents_9b_allocation(tmp_path, monkeypatch, lock):
    manifest, calls, stopped, prepared, _ = configured(tmp_path, monkeypatch)
    with (worker_lease(tmp_path / ".local" / lock),
          pytest.raises(WorkerError, match="already_running"),
          launcher.start_llama(log_dir=tmp_path, model_dir=tmp_path, manifest=manifest, port=9000)):
        pytest.fail("concurrent model must not start")
    assert not calls and not stopped and not prepared


@pytest.mark.parametrize("fail", [False, True])
def test_lease_is_held_until_owned_child_stops(tmp_path, monkeypatch, fail):
    manifest, _, stopped, _, child = configured(tmp_path, monkeypatch, fail=fail)
    gpu = tmp_path / ".local/meeting-generation.gpu.lock"
    def stop(process):
        with pytest.raises(WorkerError, match="already_running"), worker_lease(gpu):
            pytest.fail("GPU lease released before native child stop")
        stopped.append(process)
    monkeypatch.setattr(launcher, "stop_process", stop)
    outcome = pytest.raises(TimeoutError) if fail else nullcontext()
    with outcome, launcher.start_llama(log_dir=tmp_path, model_dir=tmp_path,
                                      manifest=manifest, port=9000):
        pass
    assert stopped == [child]
    with worker_lease(gpu):
        pass


def test_manifest_cannot_select_other_model(tmp_path, monkeypatch):
    manifest, calls, _, _, _ = configured(tmp_path, monkeypatch)
    manifest.write_text(json.dumps({"model": "other/model", "revision": MODEL_REVISION,
                                   "gguf": {"sha256": GGUF_SHA256}}), encoding="utf-8")
    with pytest.raises(ValueError, match="identity_mismatch"), launcher.start_llama(
            log_dir=tmp_path, model_dir=tmp_path, manifest=manifest, port=9000):
        pytest.fail("wrong model selected")
    assert not calls


@pytest.mark.parametrize("options", [{"port": True}, {"port": -1}, {"port": 70000},
                                    {"token": "short"}, {"runtime_dir": "other"}])
def test_invalid_config_never_starts(tmp_path, monkeypatch, options):
    manifest, calls, _, _, _ = configured(tmp_path, monkeypatch)
    with pytest.raises(ValueError), launcher.start_llama(log_dir=tmp_path, model_dir=tmp_path,
                                                        manifest=manifest, **options):
        pytest.fail("invalid configuration accepted")
    assert not calls
