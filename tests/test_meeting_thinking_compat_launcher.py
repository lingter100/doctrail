"""Small synthetic child processes exercise diagnostic pipes; no native/model launch."""
import io
import subprocess
import sys
import threading
from contextlib import nullcontext

import pytest

from scripts import serve_meeting_thinking_compat as launcher


def child(code):
    return subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, bufsize=0,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


@pytest.mark.parametrize("size", [0, 200_000])
def test_real_synthetic_stdout_stderr_all_counted_and_discarded(size):
    process = child(f"import os; os.write(1,b'a'*{size}); os.write(2,b'b'*{size})")
    drain = launcher.DiscardDrain(process.stdout).start()
    metrics = {"process_started": True}
    try:
        process.wait(timeout=5)
    finally:
        launcher.cleanup_owned(process, drain, metrics)
    assert metrics["within_budget"]
    assert metrics["drain"]["emitted_bytes"] == 2 * size
    assert metrics["drain"]["eof"] and metrics["drain"]["joined"]
    assert metrics["drain"]["read_errors"] == metrics["drain"]["join_errors"] == 0
    assert metrics["drain"]["raw_content_retained"] is False
    assert not any(isinstance(value, bytes) for value in vars(drain).values())
    original = dict(metrics)
    launcher.cleanup_owned(process, drain, metrics)
    assert metrics == original


def test_fixed_reads_do_not_stop_after_large_output():
    class Stream(io.BytesIO):
        def __init__(self, value):
            super().__init__(value)
            self.sizes = []
        def read(self, size):
            self.sizes.append(size)
            return super().read(size)
    stream = Stream(b"x" * 100_001)
    drain = launcher.DiscardDrain(stream).start()
    drain.join(2)
    assert set(stream.sizes) == {8192}
    assert drain.metadata()["emitted_bytes"] == 100_001
    assert drain.metadata()["eof"]


def test_read_error_does_not_report_eof_or_retain_exception():
    class Broken:
        def read(self, size):
            raise OSError("private diagnostic body")
    drain = launcher.DiscardDrain(Broken()).start()
    drain.join(2)
    assert drain.metadata()["read_errors"] == 1
    assert drain.metadata()["eof"] is False
    assert "private" not in repr(vars(drain))


def test_join_failure_is_sticky_even_after_later_eof():
    unblock = threading.Event()
    class Blocked:
        def read(self, size):
            unblock.wait(2)
            return b""
    drain = launcher.DiscardDrain(Blocked()).start()
    drain.join(0)
    assert drain.metadata()["join_errors"] == 1 and not drain.metadata()["joined"]
    unblock.set()
    drain.join(2)
    assert drain.metadata()["eof"] and drain.metadata()["join_errors"] == 1


def test_unstarted_drain_is_not_success():
    drain = launcher.DiscardDrain(io.BytesIO(b""))
    assert not drain.metadata()["started"] and not drain.metadata()["joined"]
    drain.join(0)
    assert drain.metadata()["join_errors"] == 1 and not drain.metadata()["eof"]


def test_startup_failure_retains_numeric_diagnostic_and_cleanup(tmp_path, monkeypatch):
    import hashlib
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b"{}")
    monkeypatch.setattr(launcher, "MANIFEST_SHA256", hashlib.sha256(b"{}").hexdigest())
    monkeypatch.setattr(launcher, "worker_lease", lambda _: nullcontext())
    monkeypatch.setattr(launcher, "prepare", lambda *a, **k: {
        "server_path": "server", "model": {"path": "model"}})
    monkeypatch.setattr(launcher, "command", lambda *a: [sys.executable, "-c",
        "import os; os.write(2,b'private-native-error')"])
    original_popen = subprocess.Popen
    def launch(*args, **kwargs):
        kwargs["cwd"] = tmp_path
        return original_popen(*args, **kwargs)
    monkeypatch.setattr(launcher.subprocess, "Popen", launch)
    def not_ready(process, *args, **kwargs):
        process.wait(timeout=5)
        raise RuntimeError("startup_failed")
    monkeypatch.setattr(launcher, "wait_ready", not_ready)
    metrics = {}
    with pytest.raises(RuntimeError, match="startup_failed"), launcher.start_llama(
            log_dir=tmp_path / "reserve", model_dir=tmp_path, manifest=manifest, telemetry=metrics):
        pytest.fail("startup cannot yield")
    assert metrics["process_started"] and metrics["cleanup_attempted"] and metrics["stopped"]
    assert metrics["drain"]["emitted_bytes"] == len(b"private-native-error")
    assert metrics["drain"]["eof"]
    assert "private-native-error" not in repr(metrics)
    assert list((tmp_path / "reserve").iterdir()) == []


def test_prelaunch_identity_failure_records_unknown_not_zero(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b"{}")
    metrics = {}
    with pytest.raises(ValueError, match="compat_manifest_mismatch"), launcher.start_llama(
            log_dir=tmp_path / "reserve", manifest=manifest, telemetry=metrics):
        pytest.fail("must not launch")
    assert metrics["process_started"] is False
    assert metrics["drain"]["emitted_bytes"] is None and metrics["drain"]["eof"] is False


def test_failed_first_cleanup_cannot_be_overwritten():
    process = child("pass")
    drain = launcher.DiscardDrain(process.stdout).start()
    process.wait(timeout=5)
    metrics = {"process_started": True, "cleanup_attempted": True, "seconds": 5.5,
               "within_budget": False, "stopped": False}
    drain.join(2)
    before = dict(metrics)
    launcher.cleanup_owned(process, drain, metrics)
    assert metrics == before
