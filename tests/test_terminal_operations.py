"""Operational harness lifecycle/privacy checks with no models or service launches."""
import json
import os
import sys

import pytest

from scripts import verify_terminal_service as operations


def test_model_lock_does_not_remove_another_run_lock(tmp_path):
    lock = tmp_path / ".local/m4-execution/active.lock"
    with operations.exclusive_model_check(tmp_path):
        original = lock.read_bytes()
        with pytest.raises(FileExistsError), operations.exclusive_model_check(tmp_path):
            pytest.fail("concurrent model run entered")
        assert lock.read_bytes() == original
    assert not lock.exists()


@pytest.mark.parametrize("prior", [None, "m4-terminal-v1"])
def test_explicit_base_environment_is_restored_on_failure(monkeypatch, prior):
    if prior is None:
        monkeypatch.delenv("DOCTRAIL_EMBEDDING_PROFILE", raising=False)
    else:
        monkeypatch.setenv("DOCTRAIL_EMBEDDING_PROFILE", prior)
    with pytest.raises(RuntimeError), operations.explicit_base_environment():
        assert os.environ["DOCTRAIL_EMBEDDING_PROFILE"] == "base"
        raise RuntimeError("synthetic failure")
    assert os.environ.get("DOCTRAIL_EMBEDDING_PROFILE") == prior


def test_partial_failure_receipt_is_preserved_without_exception_text(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(operations, "ROOT", tmp_path)
    monkeypatch.setattr(operations.subprocess, "check_output", lambda *a, **k: "f" * 40 if k.get("text") else b"")
    def fail(args, report, completed):
        completed("synthetic_completed_stage")
        raise RuntimeError("SECRET_RAW_DOCUMENT_AND_TOKEN")
    monkeypatch.setattr(operations, "run", fail)
    monkeypatch.setattr(operations, "exclusive_model_check", lambda: operations_context(tmp_path))
    output = tmp_path / ".local/attempt"
    monkeypatch.setattr(sys, "argv", ["verify", "--output-dir", str(output)])
    with pytest.raises(SystemExit) as error:
        operations.main()
    assert error.value.code == 1
    report = json.loads((output / "report.json").read_bytes())
    assert report["status"] == "failed" and report["checks"] == ["synthetic_completed_stage"]
    assert report["failure_location"]["file"] == "test_terminal_operations.py"
    assert report["quality_evaluated"] is False and report["service_adoption"] is False
    assert "SECRET_RAW_DOCUMENT_AND_TOKEN" not in (output / "report.json").read_text(encoding="utf-8") + capsys.readouterr().out
    assert json.loads((output / "progress.jsonl").read_bytes())["check"] == "synthetic_completed_stage"
    before = (output / "report.json").read_bytes()
    with pytest.raises(SystemExit) as again:
        operations.main()
    assert again.value.code == 2 and (output / "report.json").read_bytes() == before


# Capture the original helper before a test injects its zero-argument entry point.
operations_context = operations.exclusive_model_check


def test_terminal_profile_does_not_label_bm25_or_base():
    operations.assert_profile({"embedding_profile": operations.TERMINAL}, operations.TERMINAL, "dense")
    operations.assert_profile({}, operations.TERMINAL, "bm25")
    with pytest.raises(AssertionError):
        operations.assert_profile({"embedding_profile": operations.BASE}, operations.TERMINAL, "dense")
    with pytest.raises(AssertionError):
        operations.assert_profile({"embedding_profile": operations.TERMINAL}, operations.TERMINAL, "bm25")
