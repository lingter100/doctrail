from pathlib import Path

import pytest

from scripts import benchmark_api


def test_transient_windows_file_lock_is_retried_without_losing_completed_run(tmp_path, monkeypatch):
    target = tmp_path / "doctrail-http-test"
    target.mkdir()
    (target / "benchmark.sqlite3").write_bytes(b"TEST ONLY")
    actual_delete = benchmark_api.shutil.rmtree
    attempts = []

    def flaky_delete(path):
        attempts.append(Path(path))
        if len(attempts) < 3:
            raise PermissionError("simulated Windows file lock")
        actual_delete(path)

    monkeypatch.setattr(benchmark_api.shutil, "rmtree", flaky_delete)
    monkeypatch.setattr(benchmark_api.time, "sleep", lambda _: None)
    benchmark_api.cleanup_task_directory(target, tmp_path)
    assert len(attempts) == 3
    assert not target.exists()


def test_cleanup_refuses_paths_outside_named_benchmark_scope(tmp_path):
    protected = tmp_path / "user-data"
    protected.mkdir()
    with pytest.raises(ValueError, match="Refusing cleanup"):
        benchmark_api.cleanup_task_directory(protected, tmp_path)
    assert protected.exists()


def test_persistent_lock_is_reported_after_bounded_retries(tmp_path, monkeypatch):
    target = tmp_path / "doctrail-http-locked"
    target.mkdir()
    attempts = []

    def locked(path):
        attempts.append(path)
        raise PermissionError("simulated persistent lock")

    monkeypatch.setattr(benchmark_api.shutil, "rmtree", locked)
    monkeypatch.setattr(benchmark_api.time, "sleep", lambda _: None)
    with pytest.raises(PermissionError):
        benchmark_api.cleanup_task_directory(target, tmp_path)
    assert len(attempts) == 6
    assert target.exists()
