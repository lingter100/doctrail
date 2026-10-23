import json
import os
import subprocess

import pytest

from doctrail.meeting_bounded_snapshot import Meter
from scripts import probe_meeting_bounded_snapshot as probe


class FakeGit:
    def __init__(self):
        self.blobs, self.head, self.bad_blob = {}, "1" * 40, False

    def __call__(self, root, args, meter, deadline):
        deadline.remaining()
        if args[0] == "rev-parse":
            raw = (self.head + "\n").encode()
        elif args[0] == "show":
            name = args[1].split(":", 1)[1]
            raw = b"mismatch" if self.bad_blob else self.blobs[name]
        else:
            raise AssertionError(args)
        meter.git.append({"command_kind": args[0], "start_attempts": 1, "created": True,
                          "completed": True, "return_code": 0, "timeout": False,
                          "stdout_returned_bytes": len(raw), "stderr_returned_bytes": 0,
                          "cleanup_failed": False, "first_failure": None, "cleanup_failure": None})
        return raw

    def build(self, root, meter, deadline, command):
        root.mkdir()
        self.blobs = probe.fixture_payload() | {
            probe.MANIFEST: probe.encoded(probe.fixture_manifest()["manifest"])}
        for name, raw in self.blobs.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        return root


def fixture(tmp_path):
    git = FakeGit()
    deadline = probe.Deadline()
    root = git.build(tmp_path / "fixture", Meter(), deadline, git)
    return root, git, deadline


def execute(tmp_path, **kwargs):
    git = FakeGit()
    return probe.run(tmp_path / "output", project_root=tmp_path,
                     verify=lambda *a: {"execution_commit": "1" * 40},
                     build=git.build, command=git, **kwargs)


def test_fixture_exact_pure_spec():
    first, second = probe.fixture_manifest(), probe.fixture_manifest()
    assert first == second
    files = probe.fixture_payload()
    assert len(files) == 40
    assert sum(map(len, files.values())) == 393216
    assert len(first["manifest"]["code_roster"]) == 8
    assert all(len(b) == 4096 for n, b in files.items() if n.endswith(".py"))
    assert len([n for n in files if n.endswith(".json") and len(files[n]) == 4096]) == 24
    assert len([n for n in files if n.endswith(".json") and len(files[n]) == 32768]) == 8
    assert not first["manifest"]["import_candidates"]["scripts/epoch_fixture/absent_00.py"]


def test_four_boundaries_equal_consumers_counters_and_persistence(tmp_path):
    report = execute(tmp_path)
    assert report["status"] == "completed"
    assert [r["label"] for r in report["boundaries"]] == list(probe.ORDER)
    probe.equivalence(report["boundaries"])
    first, warm, candidate, candidate_warm = report["boundaries"]
    assert first["consumers"] == list(probe.CONSUMERS)
    assert first["meter"]["counts"]["snapshot_calls"] == 326
    assert warm["meter"]["counts"]["snapshot_calls"] == 244
    assert first["meter"]["counts"]["hash_calls"] == 244
    assert first["meter"]["counts"]["ast_parse_calls"] == 8
    assert first["meter"]["counts"]["json_parse_calls"] == 1
    assert len([r for r in first["meter"]["git"] if r["command_kind"] == "show"]) == 82
    assert not [r for r in warm["meter"]["git"] if r["command_kind"] == "show"]
    assert max(map(int, candidate["meter"]["read_requested_lengths"])) == 65536
    assert max(map(int, candidate_warm["meter"]["read_requested_lengths"])) == 65536
    disk = json.loads((tmp_path / "output/receipt.json").read_bytes())
    assert disk["status"] == "completed"
    assert report["persistence_meter"]["counts"]["fsync_calls"] == 1


@pytest.mark.parametrize("stage", ["source_manifest_unchanged", "caller_bound_snapshot",
                                   "git_ci_head", "git_head", "caller_unchanged"])
def test_same_size_mtime_mutation_at_each_fresh_consumer(tmp_path, stage):
    outcomes = []
    for candidate in (False, True):
        directory = tmp_path / str(candidate)
        directory.mkdir()
        root, git, deadline = fixture(directory)
        def hook(event, state, root=root):
            if event == stage:
                target = root / "metadata/00.json"
                old = target.stat()
                target.write_bytes(target.read_bytes().replace(b"xxxx", b"yyyy", 1))
                os.utime(target, ns=(old.st_atime_ns, old.st_mtime_ns))
        with pytest.raises(ValueError) as caught:
            probe.boundary(root, probe.fixture_manifest(), probe.GitProof(root, deadline, git),
                           Meter(), ("candidate" if candidate else "reference") + "/request_start",
                           deadline, hook)
        outcomes.append(probe.safe_failure(caught.value))
    assert outcomes[0] == outcomes[1] == {"code": "reader_hash_changed", "type": "ValueError"}


@pytest.mark.parametrize("candidate", [False, True])
def test_visible_aba_detected_before_later_restore(tmp_path, candidate):
    root, git, deadline = fixture(tmp_path)
    target = root / "metadata/00.json"
    original, old = target.read_bytes(), target.stat()
    def hook(event, state):
        if event == "source_manifest_unchanged":
            target.write_bytes(original.replace(b"xxxx", b"yyyy", 1))
            os.utime(target, ns=(old.st_atime_ns, old.st_mtime_ns))
    try:
        with pytest.raises(ValueError, match="reader_hash_changed"):
            probe.boundary(root, probe.fixture_manifest(), probe.GitProof(root, deadline, git),
                           Meter(), ("candidate" if candidate else "reference") + "/request_start",
                           deadline, hook)
    finally:
        target.write_bytes(original)
        os.utime(target, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert target.read_bytes() == original


@pytest.mark.parametrize("candidate", [False, True])
def test_new_negative_candidate_rejected_without_body_read(tmp_path, candidate):
    root, git, deadline = fixture(tmp_path)
    forbidden = root / "scripts/epoch_fixture/absent_00.py"
    forbidden.write_bytes(b"not valid Python body")
    meter = Meter()
    with pytest.raises(ValueError, match="reader_import_candidate_changed"):
        probe.boundary(root, probe.fixture_manifest(), probe.GitProof(root, deadline, git),
                       meter, ("candidate" if candidate else "reference") + "/request_start", deadline)
    assert meter.counts["snapshot_calls"] == 1  # Only the sealed manifest was read.
    assert meter.counts["ast_parse_calls"] == 0


def test_negative_candidate_created_before_final_check(tmp_path):
    def hook(event, state):
        if event == "final_checks":
            (state["root"] / "scripts/epoch_fixture/absent_31.py").write_bytes(b"invalid")
    report = execute(tmp_path, hook=hook)
    assert report["first_failure"]["code"] == "reader_import_candidate_changed"
    assert len(report["boundaries"]) == 1
    assert len(report["unexecuted"]) == 3


@pytest.mark.parametrize("kind", ["head", "blob"])
def test_head_and_committed_byte_guards(tmp_path, kind):
    root, git, deadline = fixture(tmp_path)
    def hook(event, state):
        if event == "git_ci_head":
            if kind == "head":
                git.head = "2" * 40
            else:
                git.bad_blob = True
    with pytest.raises(ValueError, match="reader_git_head_changed|reader_uncommitted_bytes"):
        probe.boundary(root, probe.fixture_manifest(), probe.GitProof(root, deadline, git),
                       Meter(), "reference/request_start", deadline, hook)


def test_change_between_boundaries_not_reused_as_proof(tmp_path):
    root, git, deadline = fixture(tmp_path)
    proof = probe.GitProof(root, deadline, git)
    probe.boundary(root, probe.fixture_manifest(), proof, Meter(), "reference/request_start", deadline)
    target = root / "metadata/00.json"
    target.write_bytes(target.read_bytes().replace(b"xxxx", b"zzzz", 1))
    with pytest.raises(ValueError, match="reader_hash_changed"):
        probe.boundary(root, probe.fixture_manifest(), proof, Meter(), "reference/before_dispatch", deadline)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "bad\\path", "a//b", "a/./b"])
def test_path_guard(tmp_path, name):
    with pytest.raises(ValueError, match="reader_relative_path"):
        probe.checked_path(tmp_path, name, Meter())


@pytest.mark.parametrize("symbolic", [False, True])
def test_alias_and_link_guards(tmp_path, symbolic):
    source, link = tmp_path / "source", tmp_path / "link"
    source.write_bytes(b"synthetic")
    try:
        if symbolic:
            link.symlink_to(source)
        else:
            os.link(source, link)
    except (OSError, NotImplementedError) as error:
        pytest.skip("OS link operation unavailable: " + type(error).__name__)
    files = probe.Files(tmp_path, Meter())
    files.get("source")
    with pytest.raises(ValueError, match="reader_linked_path|reader_file_alias"):
        files.get("link")


def test_once_only_reservation_keeps_first_receipt(tmp_path):
    execute(tmp_path)
    original = (tmp_path / "output/receipt.json").read_bytes()
    with pytest.raises(FileExistsError):
        execute(tmp_path)
    assert (tmp_path / "output/receipt.json").read_bytes() == original


def test_first_failure_and_later_persistence_failure_are_separate(tmp_path):
    def hook(event, state):
        raise ValueError("reader_injected_first")
    def save(output, report, meter):
        raise OSError("private persistence detail")
    report = execute(tmp_path, hook=hook, save=save)
    assert report["first_failure"]["code"] == "reader_injected_first"
    assert len(report["later_failures"]) == 2
    assert (tmp_path / "output/failed-final-save.json").exists()
    assert report["boundaries"][0]["meter"]["counts"]["snapshot_calls"] == 1


def test_last_terminal_write_overrun_and_failed_amendment(tmp_path):
    clock = [0.0]
    deadline = probe.Deadline(clock=lambda: clock[0])
    calls = []
    def save(output, report, meter):
        calls.append(report["status"])
        if len(calls) == 1:
            probe.persist(output, report, meter)
            clock[0] = 301
        else:
            raise OSError("amendment")
    report = execute(tmp_path, deadline=deadline, save=save)
    assert report["status"] == "failed"
    assert report["first_failure"]["code"] == "reader_deadline"
    assert calls == ["completed", "failed"]
    disk = json.loads((tmp_path / "output/receipt.json").read_bytes())
    assert disk["status"] == "completed"
    assert disk["completion_provisional_until_matching_terminal_summary_and_exit_zero"]
    assert (tmp_path / "output/failed-final-save.json").exists()
    assert report["total_through_terminal_persistence_seconds"] == 301


def test_deadline_before_first_consumer_retains_partial_counts(tmp_path):
    clock = [0.0]
    def hook(event, state):
        clock[0] = 301
    report = execute(tmp_path, deadline=probe.Deadline(clock=lambda: clock[0]), hook=hook)
    assert report["first_failure"]["code"] == "reader_deadline"
    assert len(report["boundaries"]) == 1
    assert report["boundaries"][0]["elapsed_seconds"] == 301


@pytest.mark.parametrize("mode", ["create_failure", "timeout", "nonzero"])
def test_subprocess_failure_accounting_and_cleanup(tmp_path, mode):
    class Process:
        returncode = 1 if mode == "nonzero" else -9
        killed = False
        def communicate(self, timeout):
            if mode == "timeout" and not self.killed:
                raise subprocess.TimeoutExpired("git", timeout)
            return b"out", b"err"
        def kill(self):
            self.killed = True
    process = Process()
    def popen(*args, **kwargs):
        if mode == "create_failure":
            raise OSError("create")
        return process
    meter = Meter()
    with pytest.raises((ValueError, OSError)):
        probe.git_command(tmp_path, ["rev-parse", "HEAD"], meter, probe.Deadline(), popen=popen)
    row = meter.git[0]
    assert row["start_attempts"] == 1
    assert row["created"] is (mode != "create_failure")
    assert row["timeout"] is (mode == "timeout")
    if mode == "timeout":
        assert process.killed
        assert row["stdout_returned_bytes"] == 3


def test_bad_cli_arguments_safe_no_reservation(capsys):
    assert probe.main(["--unregistered"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["first_failure"]["code"] == "reader_no_arguments"
    assert "Traceback" not in str(output)


def test_real_git_fixture_commit_and_reader_proof(tmp_path):
    meter, deadline = Meter(), probe.Deadline()
    root = probe.make_fixture(tmp_path / "real", meter, deadline)
    spec = probe.fixture_manifest()
    rows = []
    for arm in ("reference", "candidate"):
        proof = probe.GitProof(root, deadline)
        for phase in ("request_start", "before_dispatch"):
            rows.append(probe.boundary(root, spec, proof, Meter(), arm+"/"+phase, deadline))
    probe.equivalence(rows)
    assert all(row["status"] == "passed" for row in rows)
    assert (root / ".git").is_dir()
    assert not (tmp_path / ".git").exists()


def synthetic_implementation(root):
    """NEW code placeholders and permitted design metadata only, all under tmp."""
    for name in probe.OWNED:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"import scripts.never_read_negative\n")
    for name in probe.PINNED:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((probe.ROOT / name).read_bytes())
    for name in ("pyproject.toml", "uv.lock"):
        (root / name).write_bytes(b"# synthetic environment binding\n")
    frozen = probe.implementation_manifest(root)
    spec = probe.fixture_manifest()
    for name, value in ((probe.FREEZE, frozen), (probe.SPEC, spec)):
        (root / name).write_bytes(probe.encoded(value))
    ci = {"head_sha": "1" * 40,
          "source_freeze": {"file": probe.FREEZE, "sha256": probe.digest(probe.encoded(frozen))},
          "fixture_spec": {"file": probe.SPEC, "sha256": probe.digest(probe.encoded(spec))},
          "runs": [{"head_sha": "1" * 40, "run_id": i, "event": event,
                    "status": "completed", "conclusion": "success",
                    "url": f"https://github.com/example/synthetic/actions/runs/{i}",
                    "jobs": {"backend": "success", "java-service": "success", "web": "success"}}
                   for i, event in enumerate(("push", "pull_request"), 1)]}
    target = root / probe.CI
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(probe.encoded(ci))
    git = FakeGit()
    git.blobs = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    return git, frozen


def test_committed_implementation_and_ci_contract(tmp_path):
    git, frozen = synthetic_implementation(tmp_path)
    meter = Meter()
    result = probe.verify_implementation(tmp_path, meter, probe.Deadline(), git)
    assert result["execution_commit"] == "1" * 40
    assert result["protocol_sha256"] == probe.PINNED[probe.PROTOCOL]
    assert meter.counts["json_parse_calls"] == 3
    assert meter.counts["ast_parse_calls"] == 8 + len(frozen["code_roster"])


@pytest.mark.parametrize("name", [probe.FREEZE, probe.SPEC, probe.CI])
def test_uncommitted_setup_metadata_rejected_before_discovery(tmp_path, name):
    git, _ = synthetic_implementation(tmp_path)
    (tmp_path / name).write_bytes(b"uncommitted and not JSON")
    meter = Meter()
    with pytest.raises(ValueError, match="reader_uncommitted_setup"):
        probe.verify_implementation(tmp_path, meter, probe.Deadline(), git)
    assert meter.counts["ast_parse_calls"] == 0
    assert meter.counts["json_parse_calls"] == 0


def test_setup_negative_candidate_rejected_before_body(tmp_path):
    git, _ = synthetic_implementation(tmp_path)
    (tmp_path / "scripts/never_read_negative.py").write_bytes(b"invalid syntax: never read")
    meter = Meter()
    with pytest.raises(ValueError, match="reader_import_candidate_changed"):
        probe.verify_implementation(tmp_path, meter, probe.Deadline(), git)
    assert meter.counts["snapshot_calls"] == 3
    assert meter.counts["ast_parse_calls"] == 8  # Generated fixture only; code bodies zero.


@pytest.mark.parametrize("revision", ["1" * 40, "HEAD"])
def test_ci_and_head_committed_bound_bytes_are_separate_proofs(tmp_path, revision):
    git, _ = synthetic_implementation(tmp_path)
    def command(root, args, meter, deadline):
        raw = git(root, args, meter, deadline)
        if args == ["show", f"{revision}:pyproject.toml"]:
            return b"wrong committed environment"
        return raw
    with pytest.raises(ValueError, match="reader_uncommitted_bytes"):
        probe.verify_implementation(tmp_path, Meter(), probe.Deadline(), command)


@pytest.mark.parametrize("failure", ["io", "cleanup", "popen_late"])
def test_owned_process_cleanup_on_non_timeout_and_popen_overrun(tmp_path, failure):
    clock = [0.0]
    class Process:
        killed = False
        returncode = -9
        def communicate(self, timeout):
            if not self.killed:
                raise OSError("private read detail")
            if failure == "cleanup":
                raise OSError("private cleanup detail")
            return b"", b""
        def kill(self):
            self.killed = True
    process = Process()
    def popen(*args, **kwargs):
        if failure == "popen_late":
            clock[0] = 301
        return process
    meter = Meter()
    with pytest.raises((OSError, ValueError)):
        probe.git_command(tmp_path, ["rev-parse", "HEAD"], meter,
                          probe.Deadline(clock=lambda: clock[0]), popen=popen)
    assert process.killed
    row = meter.git[0]
    assert row["cleanup_failed"] is (failure == "cleanup")
    assert row["first_failure"]["code"] == (
        "reader_deadline" if failure == "popen_late" else "reader_io_error")
    if failure == "cleanup":
        assert row["cleanup_failure"]["code"] == "reader_io_error"


def test_fixture_generation_hash_and_parse_accounting():
    meter = Meter()
    probe.fixture_manifest(meter)
    assert meter.counts["ast_parse_calls"] == 8
    assert meter.counts["hash_calls"] == 81
    assert meter.counts["hash_bytes"] == 2 * 393216 + probe.fixture_manifest()["manifest_bytes"]


@pytest.mark.parametrize("field,value", [("run_id", True), ("run_id", 0), ("event", "push"),
    ("status", "in_progress"), ("conclusion", "failure"), ("head_sha", "2" * 40),
    ("jobs", {"backend": "success"}), ("url", "https://example.invalid/unverified")])
def test_ci_gate_rejects_incomplete_or_wrong_observation(tmp_path, field, value):
    git, _ = synthetic_implementation(tmp_path)
    target = tmp_path / probe.CI
    ci = json.loads(target.read_bytes())
    ci["runs"][1][field] = value
    raw = probe.encoded(ci)
    target.write_bytes(raw)
    git.blobs[probe.CI] = raw
    with pytest.raises(ValueError, match="reader_ci_contract"):
        probe.verify_implementation(tmp_path, Meter(), probe.Deadline(), git)


def test_sealed_code_hash_rejected_before_ast_of_changed_code(tmp_path):
    git, _ = synthetic_implementation(tmp_path)
    target = tmp_path / max(probe.OWNED)
    target.write_bytes(b"not syntactically valid Python")
    meter = Meter()
    with pytest.raises(ValueError, match="reader_hash_changed"):
        probe.verify_implementation(tmp_path, meter, probe.Deadline(), git)
    assert meter.counts["ast_parse_calls"] == 8


def test_cli_output_path_guard_uses_shared_setup_meter_and_deadline(tmp_path, capsys):
    calls = []
    def runner(output, *, project_root, deadline, setup_meter):
        assert project_root == tmp_path
        assert output == tmp_path / probe.OUTPUT
        assert setup_meter.counts["path_checks"] == 1
        assert deadline.elapsed() >= 0
        assert deadline.remaining() <= 300
        calls.append(output)
        return {"status": "failed", "first_failure": {"code": "reader_synthetic_stop"},
                "later_failures": [], "boundaries": [], "last_written_receipt_sha256": None,
                "terminal_persistence_seconds": 0, "total_through_terminal_persistence_seconds": 0,
                "persistence_meter": Meter().export()}
    assert probe.main([], root=tmp_path, runner=runner) == 1
    assert len(calls) == 1
    assert json.loads(capsys.readouterr().out)["first_failure"]["code"] == "reader_synthetic_stop"
    assert not (tmp_path / probe.OUTPUT).exists()


def test_injected_setup_meter_retained_through_run(tmp_path):
    setup = Meter()
    setup.counts["path_checks"] = 1
    def fail_setup(*args):
        raise ValueError("reader_stop_setup")
    result = probe.run(tmp_path / "output", project_root=tmp_path, setup_meter=setup, verify=fail_setup)
    assert result["setup_meter"]["counts"]["path_checks"] == 1
    assert result["first_failure"]["code"] == "reader_stop_setup"
