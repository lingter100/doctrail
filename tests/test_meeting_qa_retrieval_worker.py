"""Synthetic diagnostics tests; no model or server is launched."""
import json

import pytest

from scripts import meeting_qa_retrieval_worker as worker

TOKEN = "synthetic-test-token-" + "x" * 32


def startup_failure_fixture(monkeypatch, flag):
    monkeypatch.setattr(worker.sys, "argv", ["inference", "--device", "cpu"])
    monkeypatch.setenv("DOCTRAIL_INFERENCE_TOKEN", TOKEN)
    if flag is None:
        monkeypatch.delenv("DOCTRAIL_STARTUP_DIAGNOSTICS", raising=False)
    else:
        monkeypatch.setenv("DOCTRAIL_STARTUP_DIAGNOSTICS", flag)
    def fail(*args):
        try:
            raise OSError("PRIVATE C:\\secret\\weights TOKEN question document")
        except OSError as cause:
            raise ValueError("PRIVATE secret model details") from cause
    monkeypatch.setattr(worker.inference.InferenceRuntime, "load", fail)


@pytest.mark.parametrize("flag", [None, "0"])
def test_default_keeps_frozen_main_exact_stderr_and_exit(monkeypatch, capsys, flag):
    startup_failure_fixture(monkeypatch, flag)
    with pytest.raises(SystemExit) as error:
        worker.main()
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.err == "inference_startup_failed\n" and captured.out == ""


def test_opt_in_reads_actual_frozen_main_context_without_messages(monkeypatch, capsys):
    startup_failure_fixture(monkeypatch, "1")
    with pytest.raises(SystemExit) as error:
        worker.main()
    assert error.value.code == 2
    assert isinstance(error.value.__context__, ValueError)
    text = capsys.readouterr().err
    normal, structured = text.splitlines()
    payload = json.loads(structured)
    assert normal == "inference_startup_failed"
    assert payload["stage"] == "worker_entrypoint"
    assert [row["type"] for row in payload["exceptions"]] == ["ValueError", "OSError"]
    frames = [frame for row in payload["exceptions"] for frame in row["frames"]]
    assert any(frame["file"] == "test_meeting_qa_retrieval_worker.py"
               and frame["function"] == "fail" for frame in frames)
    assert all(set(frame) == {"file", "function", "line"} and frame["line"] > 0 for frame in frames)
    assert not any(value in text for value in ("PRIVATE", "secret", TOKEN, "weights", "document"))


def test_chain_and_trace_are_bounded_and_cycles_terminate():
    def fail(depth):
        if depth:
            return fail(depth - 1)
        raise ValueError("PRIVATE")
    previous = None
    for _ in range(6):
        try:
            fail(70)
        except ValueError as error:
            error.__cause__ = previous
            previous = error
    payload = worker.startup_diagnostic(previous)
    assert len(payload["exceptions"]) == 4 and payload["chain_truncated"]
    assert all(len(row["frames"]) == 8 and row["frames_truncated"] for row in payload["exceptions"])
    assert len(json.dumps(payload).encode()) < 16384
    previous.__cause__ = previous
    assert len(worker.startup_diagnostic(previous)["exceptions"]) == 1


def test_diagnostic_write_failure_does_not_replace_frozen_exit(monkeypatch, capsys):
    startup_failure_fixture(monkeypatch, "1")
    original_write = worker.sys.stderr.write
    def write(text):
        if text.startswith("{"):
            raise OSError("PRIVATE emission failure")
        return original_write(text)
    monkeypatch.setattr(worker.sys.stderr, "write", write)
    with pytest.raises(SystemExit) as error:
        worker.main()
    assert error.value.code == 2 and isinstance(error.value.__context__, ValueError)
    assert capsys.readouterr().err == "inference_startup_failed\n"


def test_success_delegates_once_without_output(monkeypatch, capsys):
    calls, marker = [], object()
    def main():
        calls.append(True)
        return marker
    monkeypatch.setenv("DOCTRAIL_STARTUP_DIAGNOSTICS", "1")
    monkeypatch.setattr(worker.inference, "main", main)
    assert worker.main() is marker and calls == [True]
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("context", [None, ValueError("PRIVATE")])
def test_same_system_exit_identity_and_code_are_preserved(monkeypatch, capsys, context):
    original = SystemExit(2)
    original.__context__ = context
    def main():
        raise original
    monkeypatch.setenv("DOCTRAIL_STARTUP_DIAGNOSTICS", "1")
    monkeypatch.setattr(worker.inference, "main", main)
    with pytest.raises(SystemExit) as error:
        worker.main()
    assert error.value is original and error.value.code == 2
    captured = capsys.readouterr().err
    assert "PRIVATE" not in captured
    assert bool(captured) == (context is not None)
