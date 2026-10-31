"""Real CLI parser subprocesses only; never pass a complete execution request."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def invoke_parser(*arguments):
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() != "PYTHONPATH"}
    return subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-m", "scripts.probe_meeting_summary_mode",
         *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def test_module_help_reaches_parser_without_inherited_pythonpath(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "unused-import-path"))
    result = invoke_parser("--help")
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
    assert "--registration REGISTRATION" in result.stdout
    assert "--execute-once-sha256 EXECUTE_ONCE_SHA256" in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize("case, expected", [
    ("missing-both", "the following arguments are required:"),
    ("missing-hash", "the following arguments are required: --execute-once-sha256"),
    ("missing-value", "argument --registration: expected one argument"),
])
def test_incomplete_arguments_reject_before_registration(case, expected, monkeypatch, tmp_path):
    missing_registration = tmp_path / "must-not-be-read.json"
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "unused-import-path"))
    arguments = {
        "missing-both": [],
        "missing-hash": ["--registration", str(missing_registration)],
        "missing-value": ["--registration"],
    }[case]
    result = invoke_parser(*arguments)
    assert result.returncode == 2, result.stderr
    assert expected in result.stderr
    assert "usage:" in result.stderr
    assert "Traceback" not in result.stderr
    assert "ModuleNotFoundError" not in result.stderr
    assert result.stdout == ""  # main never reached registration or terminal handling
    assert not missing_registration.exists()
