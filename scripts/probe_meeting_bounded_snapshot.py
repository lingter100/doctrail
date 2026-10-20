"""Once-only synthetic comparison of one-read and 64 KiB snapshot readers.

No quality orchestration, model, HTTP, tokenizer, cache optimization, or mutation
options. The six consumers below mirror C5's source_manifest/code_contract core;
they are an explicit synthetic composition, not a replay of C5.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from doctrail.meeting_bounded_snapshot import BYTE_LIMIT, Meter, read_snapshot

ROOT = Path(__file__).resolve().parents[1]
DESIGN = "docs/MEETINGS-PROOF-EPOCH-PLAN.md"
PROTOCOL = "data/evaluation/meetings-proof-epoch-protocol-v1.json"
FREEZE = "data/evaluation/meetings-proof-epoch-source-freeze-v1.json"
SPEC = "data/evaluation/meetings-proof-epoch-fixture-spec-v1.json"
CI = "experiments/results/meetings-proof-epoch-ci-v1.json"
OUTPUT = ".local/meetings-proof-epoch-v1"
PINNED = {DESIGN: "ddeda6f09537d32bf986a852a78f32c00583bdec9abc6737f014ee511ff642c5",
          PROTOCOL: "72d303f533d4840c8f14891df648bc3aef0da25443dca6b29b0511f56eddc57b"}
OWNED = ("src/doctrail/meeting_bounded_snapshot.py",
         "scripts/probe_meeting_bounded_snapshot.py",
         "tests/test_meeting_bounded_snapshot.py", "tests/test_probe_meeting_bounded_snapshot.py")
ORDER = ("reference/request_start", "reference/before_dispatch",
         "candidate/request_start", "candidate/before_dispatch")
CONSUMERS = ("inner_bound_snapshot", "source_manifest_unchanged", "caller_bound_snapshot",
             "git_ci_head", "git_head", "caller_unchanged")
MANIFEST = "fixture-manifest.json"
GIT_IDENTITY = {"name": "DocTrail synthetic fixture", "email": "fixture@example.invalid",
                "date": "2000-01-01T00:00:00+00:00", "branch": "fixture",
                "message": "synthetic bounded reader fixture v1"}


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def digest(raw, meter=None):
    if meter is not None:
        meter.counts["hash_calls"] += 1
        meter.counts["hash_bytes"] += len(raw)
    return hashlib.sha256(raw).hexdigest()


def fail(code):
    raise ValueError("reader_" + code)


def safe_failure(error):
    code = str(error)
    if not re.fullmatch(r"(?:reader|preparation)_[a-z0-9_]{1,80}", code):
        code = "reader_" + ("io_error" if isinstance(error, OSError) else "failed_closed")
    return {"code": code, "type": type(error).__name__}


class Deadline:
    def __init__(self, seconds=300, clock=time.monotonic):
        self.clock, self.start, self.seconds = clock, clock(), seconds

    def elapsed(self):
        return self.clock() - self.start

    def remaining(self):
        remaining = self.seconds - self.elapsed()
        if remaining <= 0:
            fail("deadline")
        return remaining


def checked_path(root, name, meter):
    """Same relative/reparse/containment checks as the frozen path primitive."""
    meter.counts["path_checks"] += 1
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or Path(name).is_absolute() or any(p in {"", ".", ".."} for p in name.split("/"))):
        fail("relative_path")
    current = Path(root).resolve()
    for part in name.split("/"):
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if current.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            fail("linked_path")
    if not current.resolve().is_relative_to(Path(root).resolve()):
        fail("path_escape")
    return current


def module_candidates(tree, name):
    """The frozen static resolver's candidate expansion, without default roots."""
    package = Path(name).with_suffix("").parts[:-1]
    if package and package[0] == "src":
        package = package[1:]
    for node in ast.walk(tree):
        modules = []
        if isinstance(node, ast.Import):
            modules = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = package[:len(package) - node.level + 1] if node.level else ()
            module = ".".join((*base, *((node.module or "").split("."))))
            modules = [module, *(module + "." + a.name for a in node.names)]
        for module in modules:
            parts = module.split(".")
            candidates = [module.replace(".", "/") + ".py"]
            candidates += ["/".join(parts[:n]) + "/__init__.py" for n in range(1, len(parts) + 1)]
            for candidate in candidates:
                for prefix in ("", "src/"):
                    yield prefix + candidate


def fixture_payload():
    """Pure deterministic bytes; no files, imports, Git, or artifacts created."""
    names = ["__init__", "entry", *[f"helper_{i:02d}" for i in range(6)]]
    files = {}
    for ordinal, stem in enumerate(names):
        text = f"# synthetic AST only, ordinal {ordinal}\n"
        if stem == "entry":
            text += "".join(f"import scripts.epoch_fixture.helper_{i:02d}\n" for i in range(6))
            text += "".join(f"import scripts.epoch_fixture.absent_{i:02d}\n" for i in range(32))
        raw = text.encode("ascii")
        files[f"scripts/epoch_fixture/{stem}.py"] = raw + b"#" + b" " * (4094-len(raw)) + b"\n"
    for ordinal in range(32):
        value = {"schema_version": 1, "ordinal": ordinal, "padding": ""}
        size = 4096 if ordinal < 24 else 32768
        value["padding"] = "x" * (size - len(encoded(value)))
        files[f"metadata/{ordinal:02d}.json"] = encoded(value)
    return dict(sorted(files.items()))


def fixture_manifest(meter=None):
    files = fixture_payload()
    candidates = set()
    for name, raw in files.items():
        if name.endswith(".py"):
            if meter is not None:
                meter.counts["ast_parse_calls"] += 1
            candidates.update(module_candidates(ast.parse(raw), name))
    manifest = {"schema_version": 1,
                "bound_files": {n: digest(raw, meter) for n, raw in files.items()},
                "code_roster": [n for n in files if n.endswith(".py")],
                "import_candidates": {n: n in files for n in sorted(candidates)}}
    raw = encoded(manifest)
    return {"schema_version": 1, "generator": "fixed-ascii-lf-v1", "git": dict(GIT_IDENTITY),
            "payload_bytes": sum(map(len, files.values())),
            "files": {n: {"bytes": len(b), "sha256": digest(b, meter)} for n, b in files.items()},
            "manifest": manifest, "manifest_bytes": len(raw), "manifest_sha256": digest(raw, meter)}


class Files:
    """Per-consumer capture with the original alias and fresh-unchanged semantics."""
    def __init__(self, root, meter, candidate=False):
        self.root, self.meter, self.candidate = Path(root), meter, candidate
        self.raw, self.hashes, self.identities = {}, {}, set()

    def get(self, name, expected=None):
        target = checked_path(self.root, name, self.meter)
        if name not in self.raw:
            self.meter.counts["stat_calls"] += 1
            info = target.stat()
            identity = info.st_dev, info.st_ino
            self.meter.counts["alias_checks"] += 1
            if (info.st_ino and identity in self.identities or not info.st_ino and
                    any(target.samefile(checked_path(self.root, n, self.meter)) for n in self.raw)):
                fail("file_alias")
            raw = read_snapshot(target, self.meter, candidate=self.candidate)[0]
            self.identities.add(identity)
            self.raw[name], self.hashes[name] = raw, digest(raw, self.meter)
        if expected is not None and self.hashes[name] != expected:
            fail("hash_changed")
        return self.raw[name]

    def unchanged(self):
        fresh = Files(self.root, self.meter, self.candidate)
        for name, expected in self.hashes.items():
            fresh.get(name, expected)


def candidate_states(root, sealed, meter):
    for name, expected in sealed["import_candidates"].items():
        meter.counts["candidate_checks"] += 1
        if checked_path(root, name, meter).is_file() is not expected:
            fail("import_candidate_changed")


def closure(files, seeds, sealed=None):
    pending, roster, candidates = sorted(seeds), set(), {}
    if sealed is not None:
        candidate_states(files.root, sealed, files.meter)
    while pending:
        name = pending.pop()
        if name in roster:
            continue
        if not name.endswith(".py") or sealed is not None and name not in sealed["code_roster"]:
            fail("code_allowlist")
        raw = files.get(name, sealed["bound_files"].get(name) if sealed else None)
        files.meter.counts["ast_parse_calls"] += 1
        tree = ast.parse(raw)
        roster.add(name)
        for imported in module_candidates(tree, name):
            files.meter.counts["candidate_checks"] += 1
            exists = checked_path(files.root, imported, files.meter).is_file()
            candidates[imported] = exists
            if sealed is not None and (sealed["import_candidates"].get(imported) is not exists
                                       or exists and imported not in sealed["code_roster"]):
                fail("code_allowlist")
            if exists and imported not in roster:
                pending.append(imported)
    return sorted(roster), dict(sorted(candidates.items()))


def implementation_manifest(root=ROOT, *, sealed=None, meter=None):
    """Code-only closure plus explicit design/environment hashes; creates nothing.

    Never follows data constants, closed artifact defaults, or old orchestration.
    Sealed discovery refuses new candidates before reading their bodies.
    """
    files = Files(root, meter or Meter())
    roster, candidates = closure(files, OWNED, sealed)
    for name in (*PINNED, "pyproject.toml", "uv.lock"):
        files.get(name, PINNED.get(name))
    files.unchanged()
    if sealed is not None:
        candidate_states(root, sealed, files.meter)
    result = {"schema_version": 1, "code_roster": roster, "import_candidates": candidates,
              "bound_files": dict(sorted(files.hashes.items()))}
    if sealed is not None and result != sealed:
        fail("implementation_freeze")
    return result


def git_environment():
    # Explicit environment prevents inherited Git config/dir/worktree overrides.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": GIT_IDENTITY["name"],
                "GIT_COMMITTER_NAME": GIT_IDENTITY["name"],
                "GIT_AUTHOR_EMAIL": GIT_IDENTITY["email"],
                "GIT_COMMITTER_EMAIL": GIT_IDENTITY["email"],
                "GIT_AUTHOR_DATE": GIT_IDENTITY["date"], "GIT_COMMITTER_DATE": GIT_IDENTITY["date"]})
    return env


def git_command(root, args, meter, deadline, *, popen=subprocess.Popen):
    row = {"command_kind": args[0], "start_attempts": 1, "created": False,
           "completed": False, "return_code": None, "timeout": False,
           "stdout_returned_bytes": 0, "stderr_returned_bytes": 0, "cleanup_failed": False,
           "first_failure": None, "cleanup_failure": None}
    meter.git.append(row)
    deadline.remaining()
    process = popen(["git", "-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgSign=false",
                     "-c", "core.autocrlf=false", "-c", "core.safecrlf=false", *args],
                    cwd=root, env=git_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    row["created"] = True
    try:
        stdout, stderr = process.communicate(timeout=min(15, deadline.remaining()))
    except Exception as error:  # Always reap the owned process, then re-raise its first failure.
        row["timeout"] = isinstance(error, subprocess.TimeoutExpired)
        row["first_failure"] = ({"code": "reader_git_timeout", "type": type(error).__name__}
                                if row["timeout"] else safe_failure(error))
        try:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            row.update(stdout_returned_bytes=len(stdout), stderr_returned_bytes=len(stderr),
                       return_code=process.returncode)
        except Exception as cleanup:  # noqa: BLE001 - cleanup evidence must not replace first cause
            row["cleanup_failed"] = True
            row["cleanup_failure"] = safe_failure(cleanup)
        if row["timeout"]:
            fail("git_timeout")
        raise
    row.update(completed=True, return_code=process.returncode,
               stdout_returned_bytes=len(stdout), stderr_returned_bytes=len(stderr))
    deadline.remaining()
    if process.returncode:
        fail("git_failed")
    return stdout


class GitProof:
    """Only the existing revision/name blob-proof cache, with fresh worktree reads."""
    def __init__(self, root, deadline, command=git_command):
        self.root, self.deadline, self.command = root, deadline, command
        self.head, self.proven = None, {}

    def current_head(self, meter):
        meter.counts["head_checks"] += 1
        head = self.command(self.root, ["rev-parse", "HEAD"], meter, self.deadline).decode("ascii").strip()
        if not re.fullmatch("[0-9a-f]{40}", head) or self.head is not None and head != self.head:
            fail("git_head_changed")
        self.head = head
        return head

    def verify(self, bound, revision, meter, candidate=False):
        self.current_head(meter)
        for name in sorted(bound):
            target = checked_path(self.root, name, meter)
            raw = read_snapshot(target, meter, candidate=candidate)[0]
            current = digest(raw, meter)
            if current != bound[name]:
                fail("hash_changed")
            key = revision, name
            if key not in self.proven:
                # Original committed helper performs its own additional fresh read.
                raw = read_snapshot(checked_path(self.root, name, meter), meter,
                                    candidate=candidate)[0]
                committed = self.command(self.root, ["show", f"{revision}:{name}"], meter, self.deadline)
                if committed != raw:
                    fail("uncommitted_bytes")
                self.proven[key] = current
            elif current != self.proven[key]:
                fail("git_bytes_changed")


def make_fixture(root, meter, deadline, command=git_command):
    root = Path(root)
    root.mkdir()  # Exclusive new child; never an existing checkout.
    files = fixture_payload()
    files[MANIFEST] = encoded(fixture_manifest(meter)["manifest"])
    for name, raw in files.items():
        target = checked_path(root, name, meter)
        target.parent.mkdir(parents=True, exist_ok=True)
        write_bytes(target, raw, meter)
    command(root, ["init", "--initial-branch=" + GIT_IDENTITY["branch"], "--template="], meter, deadline)
    command(root, ["add", "--", *sorted(files)], meter, deadline)
    command(root, ["commit", "--no-verify", "-m", GIT_IDENTITY["message"]], meter, deadline)
    if command(root, ["remote"], meter, deadline).strip():
        fail("fixture_remote")
    return root


def boundary(root, spec, proof, meter, label, deadline, hook=lambda event, state: None):
    started = deadline.clock()
    candidate = label.startswith("candidate/")
    state = {"root": root, "label": label, "meter": meter}
    completed = []
    deadline.remaining()
    head = proof.current_head(meter)
    caller = Files(root, meter, candidate)
    manifest_raw = caller.get(MANIFEST, spec["manifest_sha256"])
    meter.counts["json_parse_calls"] += 1
    sealed = json.loads(manifest_raw)
    if sealed != spec["manifest"]:
        fail("fixture_manifest")
    inner = Files(root, meter, candidate)
    for consumer in CONSUMERS:
        hook(consumer, state)
        deadline.remaining()
        if consumer == "inner_bound_snapshot":
            roster, candidates = closure(inner, sealed["code_roster"], sealed)
            if roster != sealed["code_roster"] or candidates != sealed["import_candidates"]:
                fail("fixture_closure")
            for name, expected in sealed["bound_files"].items():
                inner.get(name, expected)
        elif consumer == "source_manifest_unchanged":
            inner.unchanged()
        elif consumer == "caller_bound_snapshot":
            for name, expected in sealed["bound_files"].items():
                caller.get(name, expected)
        elif consumer in {"git_ci_head", "git_head"}:
            proof.verify(sealed["bound_files"] | {MANIFEST: spec["manifest_sha256"]},
                         head if consumer == "git_ci_head" else "HEAD", meter, candidate)
        else:
            caller.unchanged()
        completed.append(consumer)
    hook("final_checks", state)
    candidate_states(root, sealed, meter)
    proof.current_head(meter)
    deadline.remaining()
    return {"label": label, "status": "passed", "consumers": completed,
            "elapsed_seconds": deadline.clock() - started, "hashes": caller.hashes,
            "meter": meter.export()}


def write_bytes(target, raw, meter):
    if len(raw) > BYTE_LIMIT:
        fail("artifact_limit")
    meter.counts["write_calls"] += 1
    with target.open("xb") as stream:
        count = stream.write(raw)
        meter.counts["write_returned_bytes"] += count
        if count != len(raw):
            fail("short_write")
        stream.flush()
        meter.counts["fsync_calls"] += 1
        os.fsync(stream.fileno())


def persist(output, report, meter):
    temp = output / ("receipt-" + uuid.uuid4().hex + ".tmp")
    write_bytes(temp, encoded(report), meter)
    meter.counts["replace_calls"] += 1
    os.replace(temp, output / "receipt.json")


def verify_implementation(root, meter, deadline, command=git_command):
    proof = GitProof(root, deadline, command)
    head = proof.current_head(meter)
    files = Files(root, meter)
    # Authorize the allowlist from committed bytes before any code discovery.
    for name in (FREEZE, SPEC, CI):
        raw = files.get(name)
        if command(root, ["show", f"HEAD:{name}"], meter, deadline) != raw:
            fail("uncommitted_setup")
    values = {}
    for name in (FREEZE, SPEC, CI):
        meter.counts["json_parse_calls"] += 1
        values[name] = json.loads(files.raw[name])
    frozen, spec, ci = values[FREEZE], values[SPEC], values[CI]
    if spec != fixture_manifest(meter):
        fail("fixture_spec")
    if (ci.get("source_freeze") != {"file": FREEZE, "sha256": files.hashes[FREEZE]}
            or ci.get("fixture_spec") != {"file": SPEC, "sha256": files.hashes[SPEC]}
            or not re.fullmatch("[0-9a-f]{40}", str(ci.get("head_sha")))
            or sorted(r.get("event", "") for r in ci.get("runs", [])) != ["pull_request", "push"]
            or any(type(r.get("run_id")) is not int or r["run_id"] <= 0
                   or r.get("status") != "completed" or r.get("conclusion") != "success"
                   or not re.fullmatch(r"https://github\.com/[^/]+/[^/]+/actions/runs/" + str(r["run_id"]),
                                       str(r.get("url")))
                   or r.get("head_sha") != ci["head_sha"] or r.get("jobs") !=
                   {"backend": "success", "java-service": "success", "web": "success"}
                   for r in ci["runs"])):
        fail("ci_contract")
    implementation_manifest(root, sealed=frozen, meter=meter)
    bound = frozen["bound_files"] | {FREEZE: files.hashes[FREEZE], SPEC: files.hashes[SPEC]}
    proof.verify(bound, ci["head_sha"], meter)
    proof.verify(bound | {CI: files.hashes[CI]}, "HEAD", meter)
    files.unchanged()
    candidate_states(root, frozen, meter)
    proof.current_head(meter)
    return {"execution_commit": head, "protocol_sha256": frozen["bound_files"][PROTOCOL],
            "freeze_sha256": files.hashes[FREEZE], "spec_sha256": files.hashes[SPEC],
            "ci_sha256": files.hashes[CI]}


def equivalence(rows):
    for offset in (0, 1):
        a, b = rows[offset], rows[offset + 2]
        ac, bc = a["meter"]["counts"].copy(), b["meter"]["counts"].copy()
        ac.pop("read_calls")
        bc.pop("read_calls")
        if (a["hashes"] != b["hashes"] or a["consumers"] != b["consumers"] or ac != bc
                or a["meter"]["git"] != b["meter"]["git"]):
            fail("equivalence")


def run(output, *, project_root=ROOT, deadline=None, verify=verify_implementation,
        build=make_fixture, command=git_command, save=persist, hook=lambda event, state: None,
        setup_meter=None):
    """Explicit temp-root injection for synthetic tests; official CLI has no options."""
    deadline = deadline or Deadline()
    output = Path(output)
    output.mkdir()  # Failure/reservation never overwritten or resumed.
    setup, storage = setup_meter or Meter(), Meter()
    report = {"schema_version": 1, "status": "running", "boundaries": [],
              "first_failure": None, "later_failures": [], "unexecuted": list(ORDER),
              "completion_provisional_until_matching_terminal_summary_and_exit_zero": True,
              "timing_semantics": "boundary checks exclude persistence; total checkpoint precedes terminal write",
              "accounting_semantics": "Python returned bytes/calls; failed OS internal transfers unknown; no nested sums",
              "ci_trust": "offline validates committed parent observation bytes and HEAD; no GitHub authentication",
              "blocking_io_preemption": False, "C5_causal_or_quality_claim": False}
    active = None
    try:
        report["implementation"] = verify(project_root, setup, deadline)
        spec = fixture_manifest(setup)
        root = build(output / "fixture", setup, deadline, command)
        for arm in ("reference", "candidate"):
            proof = GitProof(root, deadline, command)
            for phase in ("request_start", "before_dispatch"):
                label = arm + "/" + phase
                active = {"label": label, "meter": Meter(), "start": deadline.clock()}
                row = boundary(root, spec, proof, active["meter"], label, deadline, hook)
                report["boundaries"].append(row)
                report["unexecuted"].remove(label)
                active = None
        equivalence(report["boundaries"])
        if verify(project_root, setup, deadline) != report["implementation"]:
            fail("implementation_changed")
        report["status"] = "completed"
        report["observed_improvement"] = all(
            report["boundaries"][i+2]["elapsed_seconds"] < report["boundaries"][i]["elapsed_seconds"]
            for i in (0, 1))
    except Exception as error:  # noqa: BLE001 - safe partial failure receipt
        report["first_failure"] = safe_failure(error)
        report["status"] = "failed"
        if active:
            report["boundaries"].append({"label": active["label"], "status": "failed",
                "elapsed_seconds": deadline.clock()-active["start"], "meter": active["meter"].export()})
            report["unexecuted"].remove(active["label"])
    report["setup_meter"] = setup.export()
    report["total_before_terminal_write_seconds"] = deadline.elapsed()
    started = deadline.clock()
    receipt_hash = None
    try:
        expected_receipt_hash = digest(encoded(report), storage)
        save(output, report, storage)
        receipt_hash = expected_receipt_hash
        deadline.remaining()
    except Exception as error:  # noqa: BLE001 - preserve terminal persistence/deadline failure
        failure = safe_failure(error)
        if report["first_failure"] is None:
            report["first_failure"] = failure
        else:
            report["later_failures"].append(failure)
        report["status"] = "failed"
        try:
            expected_receipt_hash = digest(encoded(report), storage)
            save(output, report, storage)
            receipt_hash = expected_receipt_hash
        except Exception as later:  # noqa: BLE001 - bounded fallback preserves first failure
            report["later_failures"].append(safe_failure(later))
            try:
                write_bytes(output / "failed-final-save.json", encoded(report), storage)
            except Exception as last:  # noqa: BLE001 - disk failure still reaches safe terminal summary
                report["later_failures"].append(safe_failure(last))
    report["terminal_persistence_seconds"] = deadline.clock()-started
    report["total_through_terminal_persistence_seconds"] = deadline.elapsed()
    report["persistence_meter"] = storage.export()
    report["last_written_receipt_sha256"] = receipt_hash
    return report


def main(argv=None, *, root=ROOT, runner=run):
    # Root/runner injection is for synthetic tests; the CLI accepts no options.
    deadline, setup = Deadline(), Meter()
    try:
        if (sys.argv[1:] if argv is None else argv):
            fail("no_arguments")
        output = checked_path(root, OUTPUT, setup)
        result = runner(output, project_root=root, deadline=deadline, setup_meter=setup)
        summary = {"status": result["status"], "first_failure": result["first_failure"],
                   "later_failures": result["later_failures"],
                   "boundaries": len(result["boundaries"]),
                   "last_written_receipt_sha256": result["last_written_receipt_sha256"],
                   "terminal_persistence_seconds": result["terminal_persistence_seconds"],
                   "total_through_terminal_persistence_seconds": result["total_through_terminal_persistence_seconds"],
                   "persistence_meter": result["persistence_meter"]}
        print(json.dumps(summary, sort_keys=True))
        return 0 if result["status"] == "completed" else 1
    except Exception as error:  # noqa: BLE001 - CLI never emits raw exception bodies
        print(json.dumps({"status": "failed", "first_failure": safe_failure(error),
                          "elapsed_seconds": deadline.elapsed(), "setup_meter": setup.export()},
                         sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
