"""Synthetic-only host-proof regression checks; never reserve the project output."""
from __future__ import annotations

import json
import os
import socket
import subprocess
from pathlib import Path

import pytest

from scripts import prepare_meeting_budget_inputs as budget
from scripts import profile_meeting_host_proof as profile

SMALL = {"python_files": 13, "small_json_files": 1, "large_json_files": 1,
         "small_bytes": 256, "large_bytes": 512}


def make_fixture(tmp_path, name="fixture"):
    parent = tmp_path / name
    parent.mkdir()
    return profile.prepare_fixture(parent / "fixture", SMALL)


def measure(fixture, *, instrumented=True, index=0, proof=None):
    proof = proof or profile.prep.GitProof(fixture["root"])
    return profile.measure_pass(fixture, proof, profile.Recorder(), index=index,
                                instrumented=instrumented)


def outcomes(tmp_path, change):
    results = []
    for instrumented in (False, True):
        fixture = make_fixture(tmp_path, str(instrumented))
        change(fixture)
        results.append(measure(fixture, instrumented=instrumented))
    assert [r["status"] for r in results] == ["failed", "failed"]
    return results


def test_exact_official_manifest_is_pure_and_deterministic(tmp_path):
    first = profile.fixture_manifest()
    assert first == profile.fixture_manifest()
    assert len(first["files"]) == 134
    assert sum(e["kind"] == "python" for e in first["files"]) == 13
    assert sum(e["kind"] == "json" for e in first["files"]) == 121
    assert sum(e["bytes"] == 4096 for e in first["files"]) == 85
    assert sum(e["bytes"] == 32768 for e in first["files"]) == 49
    for entry in first["files"]:
        raw = profile.synthetic_bytes(entry["ordinal"], entry["bytes"], python=entry["kind"] == "python")
        assert len(raw) == entry["bytes"] and profile.digest(raw) == entry["sha256"]
        assert raw.isascii() and raw.endswith(b"\n") and b"\r" not in raw
        if entry["kind"] == "json":
            assert set(json.loads(raw)) == {"schema_version", "ordinal", "padding"}
    assert list(tmp_path.iterdir()) == []


def test_clean_reference_equal_instrumented_and_warm_git_cache(tmp_path):
    fixture = make_fixture(tmp_path)
    reference = measure(fixture, instrumented=False)
    proof = profile.prep.GitProof(fixture["root"])
    cold = measure(fixture, index=1, proof=proof)
    warm = measure(fixture, index=2, proof=proof)
    for row in (reference, cold, warm):
        assert row["status"] == "passed", row.get("error")
        assert row["bound_files"] == reference["bound_files"]
        assert row["source_files_return"] == reference["source_files_return"]
        assert row["head"] == fixture["head"]
        assert row["components_completed"] == list(profile.ORDER)
    count = len(fixture["manifest"]["files"])
    cold_git = cold["metrics"]["primitive.git_subprocess"]["counters"]
    warm_git = warm["metrics"]["primitive.git_subprocess"]["counters"]
    assert cold_git["git_show_count"] == count
    assert warm_git.get("git_show_count", 0) == 0
    assert cold_git["git_rev_parse_count"] == warm_git["git_rev_parse_count"] == 3
    assert cold["metrics"]["primitive.snapshot"]["counters"]["snapshot_reads"] == 13 + 4 * count
    assert warm["metrics"]["primitive.snapshot"]["counters"]["snapshot_reads"] == 13 + 3 * count
    archive = warm["metrics"]["component.archive"]["counters"]
    assert archive["written_bytes"] == 17 * 4096
    assert archive["fsync_count"] == archive["flush_count"] == archive["archive_writes"] == 17
    assert warm["metrics"]["primitive.ast_parse"]["function_calls"] == 13
    for value in warm["metrics"].values():
        assert 0 <= value["exclusive_elapsed_ns"] <= value["inclusive_elapsed_ns"]


def test_byte_drift_with_same_size_and_mtime_rejected_by_both(tmp_path):
    def change(fixture):
        entry = fixture["manifest"]["files"][-1]
        target = fixture["root"] / entry["file"]
        stamp = target.stat()
        raw = target.read_bytes()
        target.write_bytes(raw.replace(b"padding", b"paddinx", 1))
        os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        assert target.stat().st_size == stamp.st_size
    results = outcomes(tmp_path, change)
    assert all(r["error"]["code"] == "c4_hash_changed" for r in results)


def test_head_drift_rejected_by_both(tmp_path):
    def change(fixture):
        fixture["head"] = "a" * 40
    assert all(r["error"]["code"] == "profile_head_changed" for r in outcomes(tmp_path, change))


def test_metadata_tamper_rejected_even_if_file_hash_is_resealed(tmp_path):
    def change(fixture):
        entry = fixture["manifest"]["files"][-1]
        target = fixture["root"] / entry["file"]
        value = json.loads(target.read_bytes())
        value["ordinal"] = 999
        raw = profile.canonical(value) + b"\n"
        target.write_bytes(raw)
        entry["sha256"] = profile.digest(raw)
    results = outcomes(tmp_path, change)
    assert all(r["error"]["code"] == "profile_metadata_changed" for r in results)


def test_new_previously_absent_import_candidate_rejected(tmp_path):
    def change(fixture):
        (fixture["root"] / "scripts/synthetic_profile_absent.py").write_bytes(b"# new candidate\n")
    results = outcomes(tmp_path, change)
    assert results[0]["error"]["code"] == "profile_closure_changed"
    # Guarded path rejects before reading the new unsealed Python body.
    assert results[1]["error"]["code"] == "profile_forbidden_read"


@pytest.mark.parametrize("instrumented", [False, True])
def test_snapshot_mid_read_mutation_is_not_hidden(tmp_path, monkeypatch, instrumented):
    fixture = make_fixture(tmp_path)
    original = budget.stamp
    calls = 0
    def drifting_stamp(path):
        nonlocal calls
        value = original(path)
        calls += 1
        return (*value[:-1], value[-1] + (calls % 2 == 0))
    monkeypatch.setattr(budget, "stamp", drifting_stamp)
    row = measure(fixture, instrumented=instrumented)
    assert row["status"] == "failed"
    assert row["error"]["code"] == "preparation_snapshot_changed"
    if instrumented:
        assert row["metrics"]["primitive.snapshot"]["counters"]["read_bytes"] == 256


@pytest.mark.parametrize("instrumented", [False, True])
def test_path_escape_primitive_is_preserved(tmp_path, instrumented):
    fixture = make_fixture(tmp_path)
    with (profile.instrument(fixture, profile.Recorder(), enabled=instrumented),
          pytest.raises(ValueError, match="c4_relative_path")):
        profile.prep.path("../escape", fixture["root"])


@pytest.mark.parametrize("instrumented", [False, True])
def test_hardlink_alias_rejected(tmp_path, instrumented):
    fixture = make_fixture(tmp_path)
    left, right = fixture["manifest"]["files"][-2:]
    target = fixture["root"] / right["file"]
    target.unlink()
    try:
        target.hardlink_to(fixture["root"] / left["file"])
    except OSError:
        pytest.skip("This platform does not permit hard links")
    right["sha256"] = left["sha256"]
    row = measure(fixture, instrumented=instrumented)
    assert row["error"]["code"] == "c4_file_alias"


@pytest.mark.parametrize("instrumented", [False, True])
def test_symlink_reparse_path_rejected(tmp_path, instrumented):
    fixture = make_fixture(tmp_path)
    left, right = fixture["manifest"]["files"][-2:]
    target = fixture["root"] / right["file"]
    target.unlink()
    try:
        target.symlink_to(fixture["root"] / left["file"])
    except OSError:
        pytest.skip("This Windows token/platform does not permit symbolic links")
    row = measure(fixture, instrumented=instrumented)
    assert row["error"]["code"] == "c4_linked_path"


def test_archive_fsync_failure_counts_written_bytes_and_preserves_first_error(tmp_path, monkeypatch):
    fixture = make_fixture(tmp_path)
    def failed_fsync(fd):
        raise OSError("synthetic private detail must not be logged")
    monkeypatch.setattr(profile.os, "fsync", failed_fsync)
    row = measure(fixture)
    assert row["status"] == "failed" and row["error"]["type"] == "OSError"
    counters = row["metrics"]["component.archive"]["counters"]
    assert counters["written_bytes"] == 4096 and counters["fsync_count"] == 1
    assert counters.get("archive_writes", 0) == 0
    assert "synthetic private detail" not in json.dumps(row)
    assert (fixture["root"].parent / "pass-0/record-00.json").stat().st_size == 4096


def test_boundaries_block_native_network_tokenizer_and_closed_paths(tmp_path):
    fixture = make_fixture(tmp_path)
    forbidden = tmp_path / "closed-input.json"
    forbidden.write_bytes(b"must never read")
    with profile.instrument(fixture, profile.Recorder()):
        calls = [lambda: profile.prep.load_tokenizer(), lambda: profile.prep.prepare("calibration", {}),
                 lambda: socket.create_connection(("localhost", 1)),
                 lambda: subprocess.run(["python", "native.py"], cwd=fixture["root"], check=False),
                 lambda: profile.prep.snapshot(forbidden), lambda: forbidden.read_bytes(),
                 lambda: profile.prep.source_files(tmp_path),
                 lambda: subprocess.run(["git", "status"], cwd=fixture["root"], check=False)]
        for call in calls:
            with pytest.raises(ValueError, match="profile_"):
                call()


def test_recorder_nested_exclusive_time_and_counts():
    values = iter([0, 10, 30, 50])
    recorder = profile.Recorder(clock=lambda: next(values))
    with recorder.span("outer"), recorder.span("inner"):
        recorder.add("read_bytes", 7)
    assert recorder.metrics["outer"]["inclusive_elapsed_ns"] == 50
    assert recorder.metrics["outer"]["exclusive_elapsed_ns"] == 30
    assert recorder.metrics["inner"]["inclusive_elapsed_ns"] == 20
    assert recorder.metrics["outer"]["counters"]["read_bytes"] == 7


def fake_project_setup(monkeypatch):
    original_prepare, original_head = profile.prepare_fixture, profile.head
    monkeypatch.setattr(profile, "_verify_implementation", lambda root, deadline: {
        "implementation_commit": "a" * 40, "source_freeze_sha256": "b" * 64})
    monkeypatch.setattr(profile, "prepare_fixture", lambda root, deadline=None:
                        original_prepare(root, SMALL, deadline=deadline))
    monkeypatch.setattr(profile, "head", lambda root, deadline=None:
                        original_head(root, deadline) if Path(root).name == "fixture" else "a" * 40)


def test_exact_seven_passes_exclusive_reservation_no_retry(tmp_path, monkeypatch):
    fake_project_setup(monkeypatch)
    report = profile.run_profile(tmp_path)
    assert report["status"] == "passed", report.get("error")
    assert len(report["passes"]) == 7 and report["unexecuted_passes"] == []
    assert report["counters"] == profile.ZERO
    assert len(report["warm_component_summary_ns"]) == 8
    assert report["passes"][0]["cache"] == "cold"
    assert [p["cache"] for p in report["passes"][1:]] == ["warm"] * 6
    saved = (tmp_path / profile.OUTPUT / "receipt.json").read_bytes()
    with pytest.raises(FileExistsError):
        profile.run_profile(tmp_path)
    assert (tmp_path / profile.OUTPUT / "receipt.json").read_bytes() == saved


def test_setup_failure_consumes_reservation_and_keeps_unexecuted_passes(tmp_path, monkeypatch):
    def fail(*args):
        raise ValueError("profile_implementation_freeze")
    monkeypatch.setattr(profile, "_verify_implementation", fail)
    report = profile.run_profile(tmp_path)
    assert report["status"] == "failed" and report["passes"] == []
    assert report["unexecuted_passes"] == list(range(7))
    assert report["error"]["code"] == "profile_implementation_freeze"
    assert (tmp_path / profile.OUTPUT / "receipt.json").is_file()


def test_failed_pass_stops_no_retry_and_receipt_failure_keeps_first_cause(tmp_path, monkeypatch):
    fake_project_setup(monkeypatch)
    calls, receipt_calls = [], []
    def fail_pass(*args, **kwargs):
        calls.append(kwargs["index"])
        return {"index": 0, "status": "failed", "error": {"code": "c4_hash_changed", "type": "ValueError"}}
    original = profile._receipt
    def fail_final(output, report):
        receipt_calls.append(report["status"])
        if report["status"] == "failed":
            raise OSError("second failure")
        original(output, report)
    monkeypatch.setattr(profile, "measure_pass", fail_pass)
    monkeypatch.setattr(profile, "_receipt", fail_final)
    report = profile.run_profile(tmp_path)
    assert calls == [0] and report["unexecuted_passes"] == list(range(1, 7))
    assert report["error"]["code"] == "c4_hash_changed"
    assert report["receipt_error"]["type"] == "OSError"


def test_deadline_stops_before_dispatch_and_preserves_completed_components(tmp_path):
    fixture = make_fixture(tmp_path)
    deadline = profile.Deadline(limit_ns=1)
    row = profile.measure_pass(fixture, profile.prep.GitProof(fixture["root"]),
                               profile.Recorder(deadline=deadline))
    assert row["status"] == "failed" and row["error"]["code"] == "profile_deadline"
    assert row["components_completed"] == []


def test_last_archive_io_can_overrun_but_never_return_success(tmp_path, monkeypatch):
    fixture = make_fixture(tmp_path)
    elapsed = [0]
    deadline = profile.Deadline(clock=lambda: elapsed[0])
    original = profile.os.fsync
    fsyncs = []
    def slow_last(fd):
        result = original(fd)
        fsyncs.append(fd)
        if len(fsyncs) == 17:
            elapsed[0] = profile.LIMIT_NS + 1
        return result
    monkeypatch.setattr(profile.os, "fsync", slow_last)
    row = profile.measure_pass(fixture, profile.prep.GitProof(fixture["root"]),
                               profile.Recorder(deadline=deadline))
    assert row["status"] == "failed" and row["error"]["code"] == "profile_deadline"
    assert row["components_completed"] == list(profile.ORDER)
    assert row["metrics"]["component.archive"]["counters"]["written_bytes"] == 17 * 4096


@pytest.mark.parametrize("operation", ["fsync", "replace"])
def test_initial_receipt_failure_preserves_temp_and_final_first_cause(tmp_path, monkeypatch, operation):
    original = getattr(profile.os, operation)
    attempts = []
    def fail_first(*args):
        attempts.append(args)
        if len(attempts) == 1:
            raise OSError("initial persistence failure")
        return original(*args)
    monkeypatch.setattr(profile.os, operation, fail_first)
    report = profile.run_profile(tmp_path)
    output = tmp_path / profile.OUTPUT
    assert report["status"] == "failed" and report["error"]["type"] == "OSError"
    assert report["passes"] == [] and report["unexecuted_passes"] == list(range(7))
    residual = list(output.glob("receipt-*.tmp"))
    assert len(residual) == 1
    assert json.loads(residual[0].read_bytes())["status"] == "running"
    assert json.loads((output / "receipt.json").read_bytes())["error"] == report["error"]


def test_terminal_receipt_overrun_gets_one_failed_amendment(tmp_path, monkeypatch):
    fake_project_setup(monkeypatch)
    elapsed = [0]
    real_deadline = profile.Deadline
    monkeypatch.setattr(profile, "Deadline", lambda: real_deadline(clock=lambda: elapsed[0]))
    original = profile._receipt
    terminal = []
    def slow_success(output, report):
        original(output, report)
        if report["status"] in {"passed", "failed"}:
            terminal.append(report["status"])
        if report["status"] == "passed":
            elapsed[0] = profile.LIMIT_NS + 1
    monkeypatch.setattr(profile, "_receipt", slow_success)
    report = profile.run_profile(tmp_path)
    assert report["status"] == "failed" and report["error"]["code"] == "profile_deadline"
    assert terminal == ["passed", "failed"]
    assert report["post_write_elapsed_ns"] > profile.LIMIT_NS
    saved = json.loads((tmp_path / profile.OUTPUT / "receipt.json").read_bytes())
    assert saved["status"] == "failed" and saved["post_write_elapsed_ns"] > profile.LIMIT_NS


def test_overrun_and_failed_amendment_leave_provisional_receipt_but_cli_fails(tmp_path, monkeypatch, capsys):
    fake_project_setup(monkeypatch)
    elapsed = [0]
    real_deadline = profile.Deadline
    monkeypatch.setattr(profile, "Deadline", lambda: real_deadline(clock=lambda: elapsed[0]))
    monkeypatch.setattr(profile, "measure_pass", lambda *args, index, **kwargs: {
        "status": "passed", "index": index, "elapsed_ns": 1,
        "metrics": {"component." + name: {"inclusive_elapsed_ns": 1} for name in profile.ORDER}})
    original = profile._receipt
    def failed_amendment(output, report):
        if report["status"] == "failed":
            raise OSError("amendment failed")
        original(output, report)
        if report["status"] == "passed":
            elapsed[0] = profile.LIMIT_NS + 1
    monkeypatch.setattr(profile, "_receipt", failed_amendment)
    report = profile.run_profile(tmp_path)
    assert report["status"] == "failed" and report["error"]["code"] == "profile_deadline"
    assert report["receipt_error"]["type"] == "OSError"
    saved = json.loads((tmp_path / profile.OUTPUT / "receipt.json").read_bytes())
    assert saved["status"] == "passed" and "provisional" in saved["receipt_status_semantics"]
    monkeypatch.setattr(profile, "run_profile", lambda: report)
    assert profile.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def make_implementation(tmp_path):
    for name, raw in {
        profile.OWNED[0]: b"import scripts.synthetic_dependency\nimport scripts.absent_dependency\n",
        profile.OWNED[1]: b"# Synthetic unit test file\n",
        "scripts/synthetic_dependency.py": b"# Synthetic code\n",
        profile.PLAN: b"Synthetic plan, not actual evaluation content\n",
        profile.PROTOCOL: b'{"synthetic":true}\n',
    }.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    value = profile.implementation_manifest(tmp_path)
    (tmp_path / profile.FREEZE).write_bytes(profile.canonical(value) + b"\n")
    profile.git(["init", "--quiet", "--template="], tmp_path)
    profile.git(["add", "--", *value["bound_files"], profile.FREEZE], tmp_path)
    profile.git(["-c", "user.name=Synthetic Test", "-c", "user.email=synthetic@invalid.local",
                 "commit", "--quiet", "--no-verify", "-m", "Synthetic implementation proof"], tmp_path)
    return value


def test_real_synthetic_git_implementation_proof_records_exact_hashes(tmp_path):
    expected = make_implementation(tmp_path)
    actual = profile._verify_implementation(tmp_path, profile.Deadline())
    assert actual["implementation_commit"] == profile.head(tmp_path)
    assert actual["protocol_sha256"] == expected["bound_files"][profile.PROTOCOL]
    assert actual["fixture_spec_sha256"] == profile.digest(profile.canonical(profile.SPEC))
    assert actual["dependency_bindings_sha256"] == profile.digest(profile.canonical(expected["bound_files"]))
    assert actual["code_roster"] == expected["code_roster"]


def test_implementation_rejects_new_negative_import_candidate_before_body_read(tmp_path, monkeypatch):
    make_implementation(tmp_path)
    target = tmp_path / "scripts/absent_dependency.py"
    target.write_bytes(b"# Newly appeared code\n")
    original, reads = profile.prep.snapshot, []
    def observed(path):
        reads.append(Path(path))
        return original(path)
    monkeypatch.setattr(profile.prep, "snapshot", observed)
    with pytest.raises(ValueError, match="profile_implementation_freeze"):
        profile._verify_implementation(tmp_path, profile.Deadline())
    assert target not in reads


def test_implementation_rejects_uncommitted_equivalent_freeze_before_code_read(tmp_path, monkeypatch):
    make_implementation(tmp_path)
    target = tmp_path / profile.FREEZE
    target.write_bytes(target.read_bytes() + b"\n")
    original, reads = profile.prep.snapshot, []
    def observed(path):
        reads.append(Path(path))
        return original(path)
    monkeypatch.setattr(profile.prep, "snapshot", observed)
    with pytest.raises(ValueError, match="profile_uncommitted_implementation"):
        profile._verify_implementation(tmp_path, profile.Deadline())
    assert reads == [target]


def test_cli_does_not_accept_paths_or_bypasses(monkeypatch, capsys):
    monkeypatch.setattr(profile, "run_profile", lambda: pytest.fail("CLI must not run"))
    for argv in (["--output", "elsewhere"], ["--skip-freeze"], ["--phase", "validation"]):
        assert profile.main(argv) == 1
        assert json.loads(capsys.readouterr().out) == {
            "status": "failed", "error": {"code": "profile_no_cli_arguments", "type": "ValueError"}}


def test_git_environment_drops_external_repository_and_hook_settings(monkeypatch):
    monkeypatch.setenv("GIT_DIR", "some-user-repository")
    monkeypatch.setenv("GIT_WORK_TREE", "external-worktree")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.hooksPath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "external-hooks")
    env = profile.git_env()
    assert "GIT_DIR" not in env and "GIT_WORK_TREE" not in env
    assert env["GIT_CONFIG_VALUE_0"] == os.devnull
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
