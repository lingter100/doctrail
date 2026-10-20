"""Temporary synthetic unit verification, never the official diagnostic run."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import diagnose_meeting_admission as diagnostic


@pytest.fixture
def binding(tmp_path):
    root = (tmp_path / "synthetic-git").resolve()
    assert root.is_relative_to(tmp_path.resolve())
    root.mkdir()
    (root / "proof.txt").write_bytes(b"synthetic proof\n")
    hooks = root / "empty-hooks"
    hooks.mkdir()
    commands = [
        ["init", "--quiet"],
        ["add", "--", "proof.txt"],
        ["-c", "user.name=Synthetic Diagnostic Unit",
         "-c", "user.email=diagnostic@example.invalid",
         "-c", f"core.hooksPath={hooks}", "-c", "commit.gpgsign=false",
         "commit", "--quiet", "-m", "Synthetic unit proof"],
    ]
    for args in commands:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return diagnostic.Binding(
        root, {"proof.txt": diagnostic.sha(b"synthetic proof\n")}, ("proof.txt",)
    )


def rows(output):
    return [json.loads(line) for line in (output / "rows.jsonl").read_bytes().splitlines()]


def test_fixed_matrix_real_functions_once_and_consumed_output(tmp_path, binding):
    from scripts.prepare_meeting_c7_inputs import family_admission

    calls = []

    def profile(frame, event, _):
        if event == "call" and frame.f_code is family_admission.__code__:
            calls.append(frame.f_locals["family"]["family_id"])

    output = tmp_path / "unit-matrix"
    previous = sys.getprofile()
    try:
        sys.setprofile(profile)
        summary = diagnostic.run_unit(output, binding)
    finally:
        sys.setprofile(previous)
    assert summary["status"] == "passed", summary
    assert summary["kind"] == "unit_verification"
    assert summary["completed_ids"] == list(diagnostic.IDS)
    assert len(calls) == 12
    measured = rows(output)
    assert [r["id"] for r in measured] == list(diagnostic.IDS)
    assert all(r["family_admission_calls"] == 1 for r in measured)
    assert [r["id"] for r in measured if r["original_admission"]["status"] != "passed"] == [
        "F04", "F07", "F12"
    ]
    for index in (3, 6, 11):
        assert measured[index]["original_admission"]["renderings"] == {}
        assert all(r["scope"] == "diagnostic_only"
                   for r in measured[index]["renderings"].values())
    assert measured[-1]["totals"]["max_block_utf8_bytes"] == 2049
    assert measured[-1]["totals"]["all_blocks_within_2048_bytes"] is False
    assert measured[-1]["chunk_bound_implies_block_bound"] is True
    raw = (output / "rows.jsonl").read_bytes()
    assert summary["rows_sha256"] == diagnostic.sha(raw)
    assert summary["rows_bytes"] == len(raw)
    assert json.loads((output / "receipt.json").read_bytes())["summary"] == summary
    reservation = (output / "reservation.json").read_bytes()
    with pytest.raises(FileExistsError):
        diagnostic.run_unit(output, binding)
    assert (output / "reservation.json").read_bytes() == reservation


def test_strict_fixture_bytes_and_json():
    raw = diagnostic.read_bound(diagnostic.ROOT, diagnostic.FIXTURE)
    assert len(diagnostic.load_fixtures(raw)) == 12
    with pytest.raises(ValueError, match="fixture_hash"):
        diagnostic.load_fixtures(raw + b"\n")
    with pytest.raises(ValueError, match="duplicate_key"):
        diagnostic.strict_json(b'{"a":1,"a":2}')
    with pytest.raises(ValueError, match="nonfinite"):
        diagnostic.strict_json(b'{"a":NaN}')


def test_binding_working_bytes_committed_bytes_and_head(tmp_path, binding):
    assert binding.verify(committed=True)["implementation_commit"]
    path = binding.root / "proof.txt"
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash_mismatch"):
        binding.verify()
    changed = diagnostic.Binding(binding.root, {"proof.txt": diagnostic.sha(b"changed")})
    with pytest.raises(ValueError, match="committed_mismatch"):
        changed.verify(committed=True)
    path.write_bytes(b"synthetic proof\n")
    subprocess.run([
        "git", "-c", "user.name=Synthetic Diagnostic Unit",
        "-c", "user.email=diagnostic@example.invalid",
        "-c", f"core.hooksPath={binding.root / 'empty-hooks'}",
        "-c", "commit.gpgsign=false", "commit", "--allow-empty", "--quiet",
        "-m", "Synthetic unit HEAD drift",
    ], cwd=binding.root, check=True, capture_output=True)
    with pytest.raises(ValueError, match="head_drift"):
        binding.verify()


@pytest.mark.parametrize("content_changed", [False, True])
def test_read_bound_ignores_atime_only(tmp_path, monkeypatch, content_changed):
    path = tmp_path / "proof.txt"
    path.write_bytes(b"proof")
    info = path.stat()
    real_stat = Path.stat
    count = 0

    def stat(self, *args, **kwargs):
        nonlocal count
        if self == path and not kwargs.get("follow_symlinks") is False:
            count += 1
            values = {key: getattr(info, key) for key in (
                "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"
            )}
            values["st_atime_ns"] = info.st_atime_ns + count
            if content_changed and count >= 2:
                values["st_mtime_ns"] += 1
            return SimpleNamespace(**values)
        return real_stat(self, *args, **kwargs)

    # Path traversal is independently exercised by Binding; isolate stat comparison.
    monkeypatch.setattr(diagnostic, "safe_file", lambda *_: path)
    monkeypatch.setattr(Path, "stat", stat)
    if content_changed:
        with pytest.raises(ValueError, match="unstable_file"):
            diagnostic.read_bound(tmp_path, "proof.txt")
    else:
        assert diagnostic.read_bound(tmp_path, "proof.txt") == b"proof"


def test_preflight_failure_consumes_reservation_before_measurement(tmp_path, monkeypatch):
    output = tmp_path / "unit-preflight"
    calls = []

    def setup():
        calls.append("setup")
        raise ValueError("synthetic fixture hash failure")

    monkeypatch.setattr(diagnostic, "measure_fixture",
                        lambda _: pytest.fail("measurement after preflight failure"))
    summary = diagnostic._run(output, setup, "unit_verification")
    assert summary["status"] == "failed"
    assert summary["first_error"]["stage"] == "initial_binding"
    assert summary["attempted_ids"] == []
    assert summary["unexecuted_ids"] == list(diagnostic.IDS)
    assert (output / "reservation.json").exists()
    assert json.loads((output / "receipt.json").read_bytes())["summary"] == summary
    with pytest.raises(FileExistsError):
        diagnostic._run(output, setup, "unit_verification")
    assert calls == ["setup"]


def test_boundary_drift_stops_before_second_fixture(tmp_path, binding, monkeypatch):
    verify = binding.verify
    calls = 0

    def drift(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            (binding.root / "proof.txt").write_bytes(b"synthetic drift")
        return verify(**kwargs)

    monkeypatch.setattr(binding, "verify", drift)
    summary = diagnostic.run_unit(tmp_path / "unit-drift", binding)
    assert summary["completed_ids"] == ["F01"]
    assert summary["attempted_ids"] == ["F01"]
    assert "hash_mismatch" in summary["first_error"]["message"]


def test_measurement_failure_precedes_partial_row_and_terminal_failures(
    tmp_path, binding, monkeypatch
):
    # Controlled diagnostic boundary failures; frozen functions are never replaced.
    def failed_measurement(_):
        return {"id": "F01", "status": "discrepancy", "unexpected_error": None,
                "discrepancies": [{"invariant": "synthetic persistence test"}]}

    write = diagnostic.durable_write

    def fail_write(path, raw, *, append=False):
        if append:
            write(path, raw[:17], append=True)
            raise OSError("synthetic partial row")
        if path.name == "receipt.pending.json":
            raise OSError("synthetic terminal failure")
        write(path, raw, append=append)

    monkeypatch.setattr(diagnostic, "measure_fixture", failed_measurement)
    monkeypatch.setattr(diagnostic, "durable_write", fail_write)
    output = tmp_path / "unit-combined-failure"
    summary = diagnostic.run_unit(output, binding)
    assert summary["status"] == "failed"
    assert summary["first_error"]["stage"] == "fixture"
    assert summary["completed_ids"] == []
    assert summary["attempted_ids"] == ["F01"]
    assert summary["rows_bytes"] == 17
    assert summary["rows_sha256"] == diagnostic.sha((output / "rows.jsonl").read_bytes())
    assert [r["stage"] for r in summary["later_persistence_errors"]] == [
        "execution_or_persistence", "terminal_persistence"
    ]
    assert summary["terminal_durable"] is False


def test_rows_read_failure_preserves_first_cause_and_attempts_terminal(
    tmp_path, binding, monkeypatch
):
    (binding.root / "proof.txt").write_bytes(b"synthetic initial drift")
    original = diagnostic.read_bound

    def fail_rows(root, name):
        if name == "rows.jsonl":
            raise OSError("synthetic read failure")
        return original(root, name)

    output = tmp_path / "unit-rows-read-failure"
    write = diagnostic.durable_write

    def reservation_creates_rows(path, raw, *, append=False):
        write(path, raw, append=append)
        if path.name == "reservation.json":
            write(output / "rows.jsonl", b"partial synthetic rows")

    monkeypatch.setattr(diagnostic, "durable_write", reservation_creates_rows)
    monkeypatch.setattr(diagnostic, "read_bound", fail_rows)
    summary = diagnostic.run_unit(output, binding)
    assert summary["first_error"]["stage"] == "initial_binding"
    assert summary["later_persistence_errors"][0]["stage"] == "rows_read"
    assert summary["rows_sha256"] is None and summary["rows_bytes"] is None
    assert summary["terminal_durable"] is True
    assert json.loads((output / "receipt.json").read_bytes())["summary"] == summary


def test_unit_rejects_official_output(binding):
    with pytest.raises(ValueError, match="temporary_directory"):
        diagnostic.run_unit(diagnostic.ROOT / diagnostic.OUTPUT, binding)
    assert not (diagnostic.ROOT / diagnostic.OUTPUT).exists()


def test_full_pending_terminal_fsync_failure_never_publishes_receipt(
    tmp_path, binding, monkeypatch
):
    write = diagnostic.durable_write
    real_fsync = diagnostic.os.fsync

    def fail_pending(path, raw, *, append=False):
        if path.name == "receipt.pending.json":
            def fail_fsync(_):
                raise OSError("synthetic fsync after full terminal write")
            monkeypatch.setattr(diagnostic.os, "fsync", fail_fsync)
            try:
                write(path, raw, append=append)
            finally:
                monkeypatch.setattr(diagnostic.os, "fsync", real_fsync)
        else:
            write(path, raw, append=append)

    monkeypatch.setattr(diagnostic, "durable_write", fail_pending)
    output = tmp_path / "unit-terminal-fsync"
    summary = diagnostic.run_unit(output, binding)
    assert summary["status"] == "failed" and summary["terminal_durable"] is False
    assert not (output / "receipt.json").exists()
    assert summary["completed_ids"] == list(diagnostic.IDS)
    pending = json.loads((output / "receipt.pending.json").read_bytes())
    assert pending["summary"]["status"] == "passed"
    assert summary["first_error"]["stage"] == "terminal_persistence"
