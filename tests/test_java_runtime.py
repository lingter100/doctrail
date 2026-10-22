"""Synthetic subprocess contracts only; no Java executable is started by these tests."""
import base64
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import java_runtime as runtime


@pytest.fixture
def probe(tmp_path, monkeypatch):
    command = tmp_path / "PATH launcher.exe"
    command.write_bytes(b"synthetic launcher")
    home = tmp_path / "한글 JVM 😀 e\u0301"
    executable = home / "bin" / ("java.exe" if os.name == "nt" else "java")
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"synthetic real JVM")
    state = SimpleNamespace(source=None, error=None, calls=0, stdout=(runtime.PREFIX
        + base64.b64encode(str(home).encode("utf-8")) + b"\r\n"), returncode=0)
    monkeypatch.setattr(runtime.shutil, "which", lambda _: str(command))
    def run(argv, **kwargs):
        state.calls += 1
        assert argv[:3] == [str(command.resolve()), "--source", "21"]
        state.source = Path(argv[3])
        assert state.source.read_text(encoding="ascii") == runtime.PROBE
        assert kwargs["timeout"] == 10 and kwargs["capture_output"] is True
        assert "text" not in kwargs and "encoding" not in kwargs
        if state.error:
            raise state.error
        return SimpleNamespace(stdout=state.stdout, stderr=b"localized invalid UTF8: \xb0\xa1",
                               returncode=state.returncode)
    monkeypatch.setattr(runtime.subprocess, "run", run)
    state.executable = executable
    return state


def test_exact_unicode_java_home_and_localized_stderr_are_independent(probe):
    assert runtime.java_executable() == probe.executable.resolve()
    assert probe.calls == 1 and not probe.source.parent.exists()


@pytest.mark.parametrize("stdout", [b"", b"wrong=YWJj\n", runtime.PREFIX + b"%%%\n",
    runtime.PREFIX + base64.b64encode(b"\xff"), runtime.PREFIX + base64.b64encode(b"relative"),
    runtime.PREFIX + base64.b64encode(b"/contains\x00null"),
    runtime.PREFIX + base64.b64encode(b"/path") + b"\nextra\n"])
def test_malformed_protocol_is_rejected_without_replacement_decode(probe, stdout):
    probe.stdout = stdout
    with pytest.raises(runtime.JavaRuntimeError, match="^java_discovery_invalid_response$"):
        runtime.java_executable()
    assert not probe.source.parent.exists()


@pytest.mark.parametrize("kind,code", [("timeout", "java_discovery_timeout"),
    ("nonzero", "java_discovery_failed"), ("oserror", "java_discovery_unavailable"),
    ("missing", "java_runtime_executable_missing")])
def test_safe_failures_and_temporary_source_cleanup(probe, kind, code):
    if kind == "timeout":
        probe.error = subprocess.TimeoutExpired("private command", 10, stderr=b"private details")
    elif kind == "nonzero":
        probe.returncode = 1
    elif kind == "oserror":
        probe.error = OSError("private path")
    else:
        probe.executable.unlink()
    with pytest.raises(runtime.JavaRuntimeError) as failure:
        runtime.java_executable()
    assert str(failure.value) == code
    assert not probe.source.parent.exists()


def test_no_java_on_path_is_safe(monkeypatch):
    monkeypatch.setattr(runtime.shutil, "which", lambda _: None)
    with pytest.raises(runtime.JavaRuntimeError, match="^java_discovery_unavailable$"):
        runtime.java_executable()
