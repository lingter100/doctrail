"""Synthetic process lifecycle and argv checks; never starts llama.cpp."""
import hashlib
import subprocess
import sys
from contextlib import nullcontext

import pytest

from scripts import serve_meeting_gpu_placement as launcher


def test_exactly_one_inference_argument_changes_and_all_guards_stay():
    control, candidate = [launcher.normalized_argv(n) for n in (24, 28)]
    assert [(a, b) for a, b in zip(control, candidate, strict=True) if a != b] == [("24", "28")]
    for flag in ("--no-warmup", "--no-context-shift", "--log-disable"):
        assert flag in control
    assert "--flash-attn" not in control and "--flash-attn" not in candidate
    assert control[control.index("--ctx-size") + 1] == "6144"
    for invalid in (True, 23, 25, 29, "28", None):
        with pytest.raises(ValueError, match="placement_gpu_layers"):
            launcher.normalized_argv(invalid)


def synthetic_launcher(tmp_path, monkeypatch, *, output=b"", startup_failure=False):
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b"{}")
    monkeypatch.setattr(launcher, "MANIFEST_SHA256", hashlib.sha256(b"{}").hexdigest())
    monkeypatch.setattr(launcher, "worker_lease", lambda _: nullcontext())
    monkeypatch.setattr(launcher, "prepare", lambda *a, **k: {"server_path": "server", "model": {"path": "model"}})
    original = subprocess.Popen
    seen = []
    def launch(argv, **kwargs):
        seen.append((argv, kwargs["env"]))
        return original([sys.executable, "-c", f"import os; os.write(2,{output!r})"],
                        stdout=kwargs["stdout"], stderr=kwargs["stderr"], bufsize=0,
                        creationflags=kwargs["creationflags"])
    monkeypatch.setattr(launcher.subprocess, "Popen", launch)
    def ready(process, *args, **kwargs):
        process.wait(timeout=5)
        if startup_failure:
            raise RuntimeError("private startup error")
    monkeypatch.setattr(launcher, "wait_ready", ready)
    return manifest, seen


@pytest.mark.parametrize("layers", [24, 28])
def test_owned_synthetic_start_discard_and_cleanup(tmp_path, monkeypatch, layers):
    manifest, seen = synthetic_launcher(tmp_path, monkeypatch)
    metrics = {}
    with launcher.start_llama(gpu_layers=layers, log_dir=tmp_path / "reservation",
                              manifest=manifest, model_dir=tmp_path, telemetry=metrics) as service:
        assert service.process.pid == metrics["owned_pid"]
    assert metrics["stopped"] and metrics["within_budget"] and metrics["drain"]["eof"]
    assert metrics["drain"]["emitted_bytes"] == 0
    assert metrics["gpu_layers_effective"] is None
    assert metrics["metadata_gpu_fields"]["manifest_local_execution_gpu_layers"] == 24
    assert seen[0][0][seen[0][0].index("--n-gpu-layers") + 1] == str(layers)
    token = seen[0][1]["LLAMA_API_KEY"]
    assert token not in repr(metrics) and token not in repr(seen[0][0])


def test_failed_startup_keeps_diagnostic_count_without_content(tmp_path, monkeypatch):
    manifest, _ = synthetic_launcher(tmp_path, monkeypatch, output=b"synthetic-private-error", startup_failure=True)
    metrics = {}
    with pytest.raises(RuntimeError), launcher.start_llama(gpu_layers=28, log_dir=tmp_path / "reservation",
            manifest=manifest, model_dir=tmp_path, telemetry=metrics):
        pytest.fail("startup must fail")
    assert metrics["stopped"] and metrics["drain"]["emitted_bytes"] == 23
    assert "synthetic-private-error" not in repr(metrics)


def test_popen_failure_proves_no_child_and_identity_failure_is_common(tmp_path, monkeypatch):
    manifest, _ = synthetic_launcher(tmp_path, monkeypatch)
    def unavailable(*args, **kwargs):
        raise OSError("synthetic executable unavailable")
    monkeypatch.setattr(launcher.subprocess, "Popen", unavailable)
    metrics = {}
    with pytest.raises(OSError), launcher.start_llama(gpu_layers=24, log_dir=tmp_path / "reservation",
            manifest=manifest, model_dir=tmp_path, telemetry=metrics):
        pytest.fail("no process")
    assert metrics["process_absence_confirmed"] and not metrics["process_started"]
    monkeypatch.setattr(launcher, "prepare", unavailable)
    with pytest.raises(ValueError, match="placement_asset_identity"), launcher.start_llama(gpu_layers=24,
            log_dir=tmp_path / "second", manifest=manifest, model_dir=tmp_path):
        pytest.fail("identity must stop launch")
