"""Once-only synthetic host-proof profiling; never executes a quality entrypoint.

The measured repository is mechanically generated. Real project code is read only
to verify the committed implementation in setup. No synthetic Python is executed.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import socket
import statistics
import subprocess
import sys
import time
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_meeting_thinking_inputs as prep

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ".local/meetings-host-proof-profile-v1"
FREEZE = "data/evaluation/meetings-host-proof-profile-source-freeze-v1.json"
PLAN = "docs/MEETINGS-HOST-PROOF-PROFILE-PLAN.md"
PROTOCOL = "data/evaluation/meetings-host-proof-profile-protocol-v1.json"
OWNED = ("scripts/profile_meeting_host_proof.py", "tests/test_profile_meeting_host_proof.py")
HELPER = "scripts/synthetic_profile_helper.py"
SEEDS = tuple(sorted(prep.NEW_FILES))
SPEC = {"python_files": 13, "small_json_files": 72, "large_json_files": 49,
        "small_bytes": 4096, "large_bytes": 32768}
ORDER = ("head", "ast_paths", "snapshot_hash", "metadata_validation", "git_proof",
         "unchanged", "head_recheck", "archive")
ZERO = {key: 0 for key in ("model_calls", "native_calls", "tokenizer_calls", "http_calls",
                          "downloads", "quality_calls", "closed_artifact_body_reads")}
LIMIT_NS = 300_000_000_000


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("ascii")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def synthetic_bytes(ordinal, size, *, python=False):
    """Exact ASCII/LF generator; no content is copied from any evaluation file."""
    if python:
        prefix = ("import scripts.synthetic_profile_helper\n" if ordinal < 12 else
                  "import scripts.synthetic_profile_absent\n").encode("ascii")
        prefix += f"# synthetic ordinal {ordinal:03d}\n# ".encode("ascii")
        if size <= len(prefix):
            raise ValueError("profile_fixture_size")
        return prefix + bytes([65 + ordinal % 26]) * (size - len(prefix) - 1) + b"\n"
    value = {"schema_version": 1, "ordinal": ordinal, "padding": ""}
    padding = size - len(canonical(value)) - 1
    if padding < 0:
        raise ValueError("profile_fixture_size")
    value["padding"] = chr(65 + ordinal % 26) * padding
    return canonical(value) + b"\n"


def fixture_manifest(spec=None):
    """Pure metadata helper: builds neither files nor a Git repository."""
    spec = SPEC if spec is None else spec
    if set(spec) != set(SPEC) or spec["python_files"] != 13 or len(SEEDS) != 12:
        raise ValueError("profile_fixture_spec")
    if any(type(v) is not int or v <= 0 for v in spec.values()):
        raise ValueError("profile_fixture_spec")
    names = [*SEEDS, HELPER]
    count = spec["small_json_files"] + spec["large_json_files"]
    names += [f"metadata/record-{i:03d}.json" for i in range(count)]
    entries = []
    for ordinal, name in enumerate(names):
        size = spec["small_bytes"] if ordinal < 13 + spec["small_json_files"] else spec["large_bytes"]
        raw = synthetic_bytes(ordinal, size, python=ordinal < 13)
        entries.append({"file": name, "ordinal": ordinal, "bytes": size,
                        "kind": "python" if ordinal < 13 else "json", "sha256": digest(raw)})
    closure = set(SEEDS) | {HELPER} | set(prep.PINNED) | prep.SERVICE_FILES | prep.HELPER_FILES
    closure |= prep.JAVA_PARITY_FILES | {"pyproject.toml", "uv.lock"}
    candidates = set()
    for entry in entries[:13]:
        raw = synthetic_bytes(entry["ordinal"], entry["bytes"], python=True)
        candidates.update(_module_candidates(ast.parse(raw), entry["file"]))
    return {"schema_version": 1, "spec": dict(spec), "files": entries,
            "source_files_return": sorted(closure),
            "import_candidates": {name: name in names for name in sorted(candidates)},
            "negative_module": "scripts.synthetic_profile_absent"}


def _module_candidates(tree, name):
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


def implementation_manifest(root=ROOT, *, sealed=None):
    """Read Python code only; expose exact dependency and negative-candidate lists.

    This setup helper never calls source_files against the actual project and
    never follows data paths named by imported modules. Parents can seal its
    result before execution without creating an official reservation.
    """
    root = Path(root).resolve()
    pending, found, candidates = list(OWNED), {}, set()
    while pending:
        name = pending.pop()
        if name in found:
            continue
        if not name.endswith(".py"):
            raise ValueError("profile_code_only")
        if sealed is not None and name not in sealed["code_roster"]:
            raise ValueError("profile_implementation_freeze")
        raw = prep.snapshot(prep.path(name, root))[0]
        found[name] = digest(raw)
        if sealed is not None and found[name] != sealed["bound_files"].get(name):
            raise ValueError("profile_implementation_freeze")
        for candidate in _module_candidates(ast.parse(raw), name):
            candidates.add(candidate)
            exists = prep.path(candidate, root).is_file()
            if sealed is not None and (sealed["import_candidates"].get(candidate) is not exists
                                       or exists and candidate not in sealed["code_roster"]):
                raise ValueError("profile_implementation_freeze")
            if exists and candidate not in found:
                pending.append(candidate)
    bound = dict(sorted(found.items()))
    for name in (PLAN, PROTOCOL):
        bound[name] = digest(prep.snapshot(prep.path(name, root))[0])
    manifest = fixture_manifest()
    return {"schema_version": 1, "id": "meetings-host-proof-profile-v1",
            "bound_files": bound, "code_roster": sorted(found),
            "import_candidates": {n: prep.path(n, root).is_file() for n in sorted(candidates)},
            "fixture_manifest": manifest, "fixture_manifest_sha256": digest(canonical(manifest))}


def safe_failure(error):
    message = str(error)
    code = message if isinstance(error, ValueError) and re.fullmatch(r"(?:profile|c4|preparation)_[a-z0-9_]+", message) else "profile_failed_closed"
    return {"code": code, "type": type(error).__name__}


class Deadline:
    def __init__(self, clock=time.perf_counter_ns, limit_ns=LIMIT_NS):
        self.clock, self.start, self.limit = clock, clock(), limit_ns

    def check(self):
        if self.clock() - self.start >= self.limit:
            raise ValueError("profile_deadline")

    def timeout(self):
        self.check()
        return max(0.001, min(15, (self.limit - (self.clock() - self.start)) / 1e9))


class Recorder:
    """Function counts, not syscall counts; nested timings are never added twice."""
    def __init__(self, clock=time.perf_counter_ns, deadline=None):
        self.clock, self.deadline = clock, deadline
        self.stack, self.metrics = [], {}

    @contextmanager
    def span(self, name):
        if self.deadline:
            self.deadline.check()
        frame = {"name": name, "start": self.clock(), "child": 0, "counters": {}}
        self.stack.append(frame)
        try:
            yield
        finally:
            elapsed = self.clock() - frame["start"]
            self.stack.pop()
            if self.stack:
                self.stack[-1]["child"] += elapsed
            row = self.metrics.setdefault(name, {"function_calls": 0,
                "inclusive_elapsed_ns": 0, "exclusive_elapsed_ns": 0, "counters": {}})
            row["function_calls"] += 1
            row["inclusive_elapsed_ns"] += elapsed
            row["exclusive_elapsed_ns"] += max(0, elapsed - frame["child"])
            for key, value in frame["counters"].items():
                row["counters"][key] = row["counters"].get(key, 0) + value

    def add(self, key, amount=1):
        for frame in self.stack:
            frame["counters"][key] = frame["counters"].get(key, 0) + amount


def _deny(*args, **kwargs):
    raise ValueError("profile_forbidden_operation")


def git_env():
    """Isolate fixture Git from inherited repo overrides, hooks and signing."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", GIT_CONFIG_COUNT="3",
               GIT_CONFIG_KEY_0="core.hooksPath", GIT_CONFIG_VALUE_0=os.devnull,
               GIT_CONFIG_KEY_1="commit.gpgSign", GIT_CONFIG_VALUE_1="false",
               GIT_CONFIG_KEY_2="core.autocrlf", GIT_CONFIG_VALUE_2="false")
    return env


def git(command, root, deadline=None):
    result = subprocess.run(["git", *command], cwd=root, capture_output=True,
                            check=False, timeout=deadline.timeout() if deadline else 15,
                            env=git_env())
    if result.returncode:
        raise ValueError("profile_git_failed")
    return result.stdout


def head(root, deadline=None):
    value = git(["rev-parse", "HEAD"], root, deadline).decode("ascii").strip()
    if not prep.digest(value, 40):
        raise ValueError("profile_head_invalid")
    return value


def prepare_fixture(root, spec=None, *, deadline=None):
    """Create a fresh synthetic repository; callers must own its fresh parent."""
    root = Path(root).resolve()
    root.mkdir(exist_ok=False)
    manifest = fixture_manifest(spec)
    for entry in manifest["files"]:
        if deadline:
            deadline.check()
        target = prep.path(entry["file"], root)
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = synthetic_bytes(entry["ordinal"], entry["bytes"], python=entry["kind"] == "python")
        prep.write_new(entry["file"], raw, root)
    git(["init", "--quiet", "--template="], root, deadline)
    git(["add", "--", *[e["file"] for e in manifest["files"]]], root, deadline)
    git(["-c", "user.name=Synthetic Profile", "-c", "user.email=synthetic@invalid.local",
         "commit", "--quiet", "--no-verify", "-m", "Synthetic fixture only"], root, deadline)
    return {"root": root, "manifest": manifest, "head": head(root, deadline)}


@contextmanager
def instrument(fixture, recorder, *, enabled=True):
    """Keep primitive return values/exceptions; restrict every workload read."""
    if not enabled:
        yield
        return
    root = fixture["root"].resolve()
    output = root.parent
    names = {e["file"] for e in fixture["manifest"]["files"]}
    originals = {"path": prep.path, "snapshot": prep.snapshot, "sha": prep.sha,
                 "parse": ast.parse, "run": subprocess.run, "fsync": os.fsync,
                 "write_new": prep.write_new, "open": Path.open}

    @contextmanager
    def span(name):
        if enabled:
            with recorder.span("primitive." + name):
                yield
        else:
            yield

    def guarded_path(name, base=prep.ROOT):
        with span("path"):
            if Path(base).resolve() not in {root, output}:
                raise ValueError("profile_workload_root")
            if enabled:
                recorder.add("path_checks")
            return originals["path"](name, base)

    def guarded_snapshot(target):
        with span("snapshot"):
            target = Path(target)
            # Lexical relative path first, then the original path primitive checks links.
            try:
                name = target.relative_to(root).as_posix()
            except ValueError:
                raise ValueError("profile_forbidden_read") from None
            if name not in names:
                raise ValueError("profile_forbidden_read")
            originals["path"](name, root)
            if enabled:
                recorder.add("snapshot_reads")
            return originals["snapshot"](target)

    def measured_sha(raw):
        with span("sha256"):
            if enabled:
                recorder.add("hashed_bytes", len(raw))
            return originals["sha"](raw)

    def measured_parse(raw, *args, **kwargs):
        with span("ast_parse"):
            if enabled:
                recorder.add("ast_parses")
                recorder.add("ast_input_bytes", len(raw))
            return originals["parse"](raw, *args, **kwargs)

    def measured_run(command, *args, **kwargs):
        with span("git_subprocess"):
            if (args or not isinstance(command, list) or len(command) < 2 or command[0] != "git"
                    or Path(kwargs.get("cwd", "")).resolve() != root):
                raise ValueError("profile_forbidden_subprocess")
            kind = command[1]
            if not (command == ["git", "rev-parse", "HEAD"]
                    or kind == "show" and len(command) == 3 and command[2].startswith("HEAD:")
                    and command[2][5:] in names):
                raise ValueError("profile_forbidden_git_command")
            if enabled:
                recorder.add("git_subprocess_count")
                recorder.add("git_" + kind.replace("-", "_") + "_count")
            kwargs["env"] = git_env()
            if recorder.deadline:
                kwargs["timeout"] = recorder.deadline.timeout()
            result = originals["run"](command, **kwargs)
            if enabled:
                recorder.add("git_stdout_bytes", len(result.stdout))
                recorder.add("git_stderr_bytes", len(result.stderr))
            return result

    def measured_fsync(fd):
        with span("fsync"):
            if enabled:
                recorder.add("fsync_count")
            return originals["fsync"](fd)

    def measured_write(name, value, base=prep.ROOT):
        with span("archive_write"):
            if Path(base).resolve() != output or not re.fullmatch(r"pass-[0-6]/record-[0-9]{2}\.json", name):
                raise ValueError("profile_archive_path")
            result = originals["write_new"](name, value, base)
            if enabled:
                recorder.add("archive_writes")
            return result

    class ObservedStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def write(self, raw):
            result = self.stream.write(raw)
            recorder.add("written_bytes", result)
            return result

        def read(self, *args):
            result = self.stream.read(*args)
            recorder.add("read_bytes", len(result))
            return result

        def flush(self):
            result = self.stream.flush()
            recorder.add("flush_count")
            return result

        def fileno(self):
            return self.stream.fileno()

    def guarded_open(target, mode="r", *args, **kwargs):
        target = Path(target)
        if mode == "rb" and target.is_relative_to(root) and target.relative_to(root).as_posix() in names:
            originals["path"](target.relative_to(root).as_posix(), root)
            return ObservedStream(originals["open"](target, mode, *args, **kwargs))
        if (mode == "xb" and target.is_relative_to(output)
                and re.fullmatch(r"pass-[0-6]/record-[0-9]{2}\.json", target.relative_to(output).as_posix())):
            return ObservedStream(originals["open"](target, mode, *args, **kwargs))
        raise ValueError("profile_forbidden_read_or_write")

    with ExitStack() as stack:
        for owner, name, replacement in ((prep, "path", guarded_path), (prep, "snapshot", guarded_snapshot),
                (prep, "sha", measured_sha), (ast, "parse", measured_parse),
                (subprocess, "run", measured_run), (os, "fsync", measured_fsync),
                (prep, "write_new", measured_write), (prep, "load_tokenizer", _deny),
                (prep, "prepare", _deny), (prep, "load_material", _deny),
                (prep, "code_contract", _deny), (socket.socket, "connect", _deny),
                (socket.socket, "connect_ex", _deny), (socket, "create_connection", _deny),
                (Path, "open", guarded_open)):
            stack.enter_context(patch.object(owner, name, replacement))
        yield


def measure_pass(fixture, proof, recorder, *, index=0, instrumented=True):
    root, manifest = fixture["root"], fixture["manifest"]
    expected = {e["file"]: e["sha256"] for e in manifest["files"]}
    snapshots = prep.Snapshots(root)
    start, completed = recorder.clock(), []
    result = {"index": index, "cache": "cold" if index == 0 else "warm", "status": "running",
              "components_completed": completed, "metrics": recorder.metrics}
    try:
        with instrument(fixture, recorder, enabled=instrumented):
            for component in ORDER:
                with recorder.span("component." + component):
                    if component in {"head", "head_recheck"}:
                        if head(root, recorder.deadline) != fixture["head"]:
                            raise ValueError("profile_head_changed")
                    elif component == "ast_paths":
                        closure = sorted(prep.source_files(root))
                        if closure != manifest["source_files_return"]:
                            raise ValueError("profile_closure_changed")
                    elif component == "snapshot_hash":
                        for name, value in expected.items():
                            snapshots.get(name, value)
                    elif component == "metadata_validation":
                        for entry in manifest["files"]:
                            if entry["kind"] == "json":
                                value = snapshots.json(entry["file"])
                                if (set(value) != {"schema_version", "ordinal", "padding"}
                                        or type(value["schema_version"]) is not int or value["schema_version"] != 1
                                        or type(value["ordinal"]) is not int or value["ordinal"] != entry["ordinal"]
                                        or not isinstance(value["padding"], str)
                                        or set(value["padding"]) != {chr(65 + entry["ordinal"] % 26)}):
                                    raise ValueError("profile_metadata_changed")
                                recorder.add("metadata_validations")
                    elif component == "git_proof":
                        proof(expected, root=root)
                    elif component == "unchanged":
                        snapshots.unchanged()
                    elif component == "archive":
                        prep.path(f"pass-{index}", root.parent).mkdir(exist_ok=False)
                        for ordinal in range(17):
                            prep.write_new(f"pass-{index}/record-{ordinal:02d}.json",
                                           synthetic_bytes(ordinal, 4096), root.parent)
                completed.append(component)
        if recorder.deadline:
            recorder.deadline.check()
        result.update(status="passed", head=fixture["head"], bound_files=snapshots.hashes,
                      source_files_return=closure)
    except Exception as error:  # noqa: BLE001 - preserve safe first failure in the partial receipt.
        result.update(status="failed", error=safe_failure(error))
    result["elapsed_ns"] = recorder.clock() - start
    return result


def _receipt(output, report):
    """Atomic report refresh never overwrites any fixture or archive evidence."""
    raw = canonical(report) + b"\n"
    temporary = output / ("receipt-" + uuid.uuid4().hex + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, output / "receipt.json")


def _verify_implementation(root, deadline):
    raw = prep.snapshot(prep.path(FREEZE, root))[0]
    current = head(root, deadline)
    if git(["show", f"{current}:{FREEZE}"], root, deadline) != raw:
        raise ValueError("profile_uncommitted_implementation")
    frozen = prep.strict_json(raw.decode("utf-8"))
    if (not isinstance(frozen, dict) or not isinstance(frozen.get("code_roster"), list)
            or any(not isinstance(n, str) or not n.endswith(".py") for n in frozen["code_roster"])
            or not isinstance(frozen.get("import_candidates"), dict)
            or not isinstance(frozen.get("bound_files"), dict)):
        raise ValueError("profile_implementation_freeze")
    actual = implementation_manifest(root, sealed=frozen)
    if canonical(frozen) != canonical(actual):
        raise ValueError("profile_implementation_freeze")
    # Real code proof is setup only, not part of any synthetic component timing.
    for name in [*actual["bound_files"], FREEZE]:
        deadline.check()
        if git(["show", f"{current}:{name}"], root, deadline) != prep.snapshot(prep.path(name, root))[0]:
            raise ValueError("profile_uncommitted_implementation")
    if head(root, deadline) != current:
        raise ValueError("profile_project_head_changed")
    return {"implementation_commit": current, "source_freeze_sha256": digest(raw),
            "fixture_manifest_sha256": actual["fixture_manifest_sha256"],
            "fixture_spec_sha256": digest(canonical(actual["fixture_manifest"]["spec"])),
            "protocol_sha256": actual["bound_files"][PROTOCOL],
            "dependency_bindings_sha256": digest(canonical(actual["bound_files"])),
            "code_roster": actual["code_roster"]}


def run_profile(root=ROOT):
    root = Path(root).resolve()
    deadline = Deadline()
    output = prep.path(OUTPUT, root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)  # Irrevocable reservation, including setup failures.
    report = {"schema_version": 1, "id": "meetings-host-proof-profile-v1", "status": "running",
              "receipt_status_semantics": "A persisted passed status is provisional until the CLI exits zero with a passed terminal summary. A post-write failure and failed amendment can leave an older passed receipt; never accept the receipt alone.",
              "counters": dict(ZERO), "passes": [], "unexecuted_passes": list(range(7)),
              "count_semantics": "Instrumented function calls, not syscalls. Bytes are returned file-object read/write counts; failed OS-internal transfers are unknown. Nested primitive and component counters overlap and must not be added together.",
              "time_semantics": "Component intervals are disjoint. Primitive inclusive intervals overlap; do not sum them.",
              "elapsed_boundary": "elapsed_to_terminal_checkpoint_ns excludes the terminal receipt write. The post-write boundary is checked once; an observed deadline overrun gets one failure amendment. The returned in-memory post_write_elapsed_ns is persisted only in that amendment.",
              "limits": {"total_seconds": 300, "passes": 7, "retries": 0},
              "limitations": ["Synthetic primitive workload, not closed C4 replay or native latency prediction",
                              "Cold means empty in-process proof cache, not empty OS cache",
                              "Concurrent load and instrumentation overhead are uncontrolled",
                              "Deadline is checked at operation boundaries; blocking file I/O can overrun before failure is recorded",
                              "Failed receipt writes retain uniquely named temporary bytes; durability is unconfirmed if fsync fails"]}
    first_error = None
    try:
        _receipt(output, report)
        setup_start = deadline.clock()
        report["implementation"] = _verify_implementation(root, deadline)
        fixture = prepare_fixture(output / "fixture", deadline=deadline)
        report["fixture"] = {"head": fixture["head"], "manifest": fixture["manifest"]}
        report["setup_elapsed_ns"] = deadline.clock() - setup_start
        _receipt(output, report)
        proof = prep.GitProof(fixture["root"])
        for index in range(7):
            deadline.check()
            row = measure_pass(fixture, proof, Recorder(deadline=deadline), index=index)
            report["passes"].append(row)
            report["unexecuted_passes"] = list(range(index + 1, 7))
            if row["status"] != "passed":
                first_error = row["error"]
                break
            _receipt(output, report)
        if first_error is None:
            deadline.check()
            if head(root, deadline) != report["implementation"]["implementation_commit"]:
                raise ValueError("profile_project_head_changed")
            warm = [r["elapsed_ns"] for r in report["passes"][1:]]
            report["warm_summary_ns"] = {"median": statistics.median(warm), "minimum": min(warm), "maximum": max(warm)}
            report["warm_component_summary_ns"] = {}
            for component in ORDER:
                values = [r["metrics"]["component." + component]["inclusive_elapsed_ns"] for r in report["passes"][1:]]
                report["warm_component_summary_ns"][component] = {
                    "median": statistics.median(values), "minimum": min(values), "maximum": max(values)}
    except Exception as error:  # noqa: BLE001 - reserve and preserve all bounded execution failures.
        if first_error is None:
            first_error = safe_failure(error)
    report["status"] = "failed" if first_error else "passed"
    if first_error:
        report["error"] = first_error
    report["elapsed_to_terminal_checkpoint_ns"] = deadline.clock() - deadline.start
    try:
        _receipt(output, report)
    except Exception as error:  # noqa: BLE001 - never replace the first failure with persistence failure.
        # Preserve the first failure even if receipt persistence also fails.
        report["status"] = "failed"
        report.setdefault("error", safe_failure(error))
        report["receipt_error"] = safe_failure(error)
    report["post_write_elapsed_ns"] = deadline.clock() - deadline.start
    if report["post_write_elapsed_ns"] >= deadline.limit:
        report["status"] = "failed"
        report.setdefault("error", {"code": "profile_deadline", "type": "ValueError"})
        # One bounded amendment, never an unbounded attempt to time its own write.
        try:
            _receipt(output, report)
        except Exception as error:  # noqa: BLE001 - preserve first cause and partial temporary bytes.
            report["receipt_error"] = safe_failure(error)
    return report


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv:
            raise ValueError("profile_no_cli_arguments")
        report = run_profile()
    except Exception as error:  # noqa: BLE001 - CLI emits safe metadata only.
        print(json.dumps({"status": "failed", "error": safe_failure(error)}))
        return 1
    print(json.dumps({"status": report["status"], "completed_passes": len(report["passes"]),
                      "error": report.get("error"), "receipt_error": report.get("receipt_error")}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
