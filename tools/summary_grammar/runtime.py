"""Bounded, explicit preparation helpers. Importing never probes resources or runs tools."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import time
from pathlib import Path, PurePosixPath

BUNDLE = Path(__file__).resolve().parent
COMMIT = "d81235049384534c167caea52b85a694f6103d14"
GRAMMAR_SHA = "e744497da34d0af79e2cc0419de0241d093136ec84b62a51bad905b982f8e290"
CORPUS_SHA = "722fd6f6ac6ac5c2a39c7ab23efcdc32a79dc8776df638b0a99c28a8c43c65cb"
EXPECTED_SHA = "9351c131aa3c9c00b06ebf2c7cd3fd1be7aacc9561aa04af0defe5c0688ddc9e"
PINS_SHA = "4de0a7e547ccdd10a3ac72b6b86d54eea8e63f86dc76e6701d05c4613ea6d6d2"
DISK = 4 * 1024**3
DOWNLOAD = 512 * 1024**2


class BoundaryError(RuntimeError):
    pass


def require(ok, reason):
    if not ok:
        raise BoundaryError(reason)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def parse_json(data):
    def pairs(rows):
        result = {}
        for k, v in rows:
            require(k not in result, "duplicate_json_key")
            result[k] = v
        return result
    return json.loads(data, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(BoundaryError("json_constant")))


def load(path):
    return parse_json(Path(path).read_bytes())


def write(path, data):
    with Path(path).open("xb") as stream:
        stream.write((json.dumps(data, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode())


def reference(path, root):
    path = Path(path)
    return {"file": path.relative_to(root).as_posix(), "size_bytes": path.stat().st_size,
            "sha256": digest(path.read_bytes())}


def safe_path(root, name):
    require(isinstance(name, str) and name and "\\" not in name and ":" not in name, "unsafe_path")
    rel = PurePosixPath(name)
    require(not rel.is_absolute() and all(x not in (".", "..", "") for x in name.split("/")), "unsafe_path")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    require(all(x == x.rstrip(" .") and x.split(".")[0].upper() not in reserved for x in rel.parts), "unsafe_path")
    root = Path(root).absolute()
    current = root
    for part in (None, *rel.parts):
        if part is not None:
            current /= part
        if current.exists() or current.is_symlink():
            attrs = current.lstat()
            require(not stat.S_ISLNK(attrs.st_mode) and not getattr(attrs, "st_file_attributes", 0) & 1024,
                    "reparse_path")
    require(current.resolve().is_relative_to(root.resolve()), "path_escape")
    return current


def inventory(root):
    rows = []
    for p in sorted(Path(root).rglob("*")):
        safe_path(root, p.relative_to(root).as_posix())
        if p.is_file():
            rows.append(reference(p, root))
    return rows


def disk_bytes(root, checkpoint=None):
    def check(event):
        if checkpoint is not None:
            checkpoint(event)
    check("start")
    total = 0
    for p in Path(root).rglob("*"):
        check("before_entry")
        safe_path(root, p.relative_to(root).as_posix())
        if p.is_file():
            total += p.stat().st_size
            require(total <= DISK, "disk_budget")
        check("after_entry")
    check("complete")
    return total


def write_bounded(root, path, value, deadline=None, clock=time.monotonic, limit=DISK):
    """Account for serialized metadata before writing; a late/partial write is failure."""
    def checkpoint(event=None):
        if deadline is not None:
            require(clock() < deadline, "shared_deadline")
    checkpoint()
    data = (json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode()
    safe_path(root, Path(path).relative_to(root).as_posix())
    require(disk_bytes(root, checkpoint=checkpoint) + len(data) <= limit, "disk_budget")
    checkpoint()
    with Path(path).open("xb") as stream:
        checkpoint()
        require(stream.write(data) == len(data), "short_write")
        stream.flush()
        checkpoint()
    checkpoint()


def check_refs(root, rows, exact=False):
    names = set()
    for row in rows:
        require(set(row) == {"file", "sha256", "size_bytes"}, "reference_schema")
        require(row["file"].casefold() not in names, "duplicate_path")
        names.add(row["file"].casefold())
        path = safe_path(root, row["file"])
        require(reference(path, root) == row, "reference_changed")
    if exact:
        require(inventory(root) == rows, "inventory_changed")


def reviewed(path, expected):
    require(isinstance(expected, str) and re.fullmatch("[0-9a-f]{64}", expected), "review_digest_required")
    require(digest(Path(path).read_bytes()) == expected, "review_digest_mismatch")
    return load(path)


def pins():
    require(digest((BUNDLE / "pins.json").read_bytes()) == PINS_SHA, "pins_changed")
    return load(BUNDLE / "pins.json")


def bundle():
    from tools.summary_grammar.witness_pin import WITNESS_SHA
    for name, h in [("candidate.gbnf", GRAMMAR_SHA), ("corpus.json", CORPUS_SHA),
                    ("expected.json", EXPECTED_SHA), ("prefix-witnesses.json", WITNESS_SHA)]:
        require(digest((BUNDLE / name).read_bytes()) == h, "bundle_changed")
    rows, expected = load(BUNDLE / "corpus.json"), load(BUNDLE / "expected.json")
    witnesses = {x["id"]: x for x in load(BUNDLE / "prefix-witnesses.json")}
    by_id = {r["id"]: r for r in rows}
    native, carrier = [], []
    require(len(rows) == len(expected) == len(by_id) == 106 and len(witnesses) == 10, "case_count")
    for row, exp in zip(rows, expected, strict=True):
        require(row["id"] == exp["id"], "expected_order")
        state = "complete" if row["expected_complete_boundary_language"] else "prefix" if row["expected_extendable_prefix"] else "dead"
        require(exp["expected_state"] == state and exp["expected_frozen_parser_accept"] == row["expected_frozen_parser_accept"], "expected_changed")
        try:
            raw = row["raw"].encode("utf-8", "strict")
        except UnicodeEncodeError:
            require(row["id"] == "raw-surrogate" and exp["carrier"] == "strict_utf8_rejection" and exp["raw_utf8_sha256"] is None, "carrier_changed")
            carrier.append(row["id"])
            continue
        require(exp["carrier"] == "utf8" and digest(raw) == exp["raw_utf8_sha256"], "carrier_hash")
        suffix = b""
        if state == "prefix":
            w = witnesses[row["id"]]
            complete = by_id[w["complete_case_id"]]
            whole = complete["raw"].encode("utf-8", "strict")
            require(complete["expected_complete_boundary_language"] and whole.startswith(raw), "witness_prefix")
            suffix = whole[len(raw):]
            require(suffix and digest(suffix) == w["suffix_utf8_sha256"] and digest(whole) == w["complete_utf8_sha256"], "witness_hash")
        native.append({"id": row["id"], "raw": raw, "suffix": suffix, "expected": state})
    require(len(native) == 105 and carrier == ["raw-surrogate"], "carrier_count")
    return native, carrier


def clean_environment(bin_dirs, root, temp_name):
    """Fresh per-phase temporary storage stays counted and preserved under root."""
    temporary = safe_path(root, temp_name)
    temporary.mkdir(exist_ok=False)
    safe_path(root, temp_name)
    disk_bytes(root)
    # No inherited compiler flags, CMake presets, proxy downloads, Git, or Python paths.
    env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR") if k in os.environ}
    env.update(PATH=os.pathsep.join(str(Path(p).absolute()) for p in bin_dirs),
               TEMP=str(temporary), TMP=str(temporary), SOURCE_DATE_EPOCH="0",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    return env


def validate_temporary(root, env):
    require(env.get("TEMP") == env.get("TMP") and bool(env.get("TEMP")), "owned_temp_required")
    path = Path(env["TEMP"])
    require(path.is_absolute() and path != Path(root).absolute()
            and path.is_relative_to(Path(root).absolute()), "owned_temp_escape")
    safe_path(root, path.relative_to(Path(root).absolute()).as_posix())
    require(path.is_dir(), "owned_temp_missing")
    return path


class OwnedTree:
    """Sampled limits and identity-safe cleanup; never claims an OS hard peak limit."""
    def __init__(self, process, allowed, ps, clock, sleeper=time.sleep):
        self.process, self.ps, self.clock, self.sleeper = process, ps, clock, sleeper
        self.allowed = {os.path.normcase(str(Path(x).resolve())) for x in allowed}
        self.seen, self.peak = {}, 0
        self.minimum_host, self.samples = None, 0

    def identity(self, proc):
        return (proc.pid, proc.create_time(), os.path.normcase(str(Path(proc.exe()).resolve())))

    def capture(self, proc):
        ident = self.identity(proc)
        self.seen[ident] = proc
        require(ident[2] in self.allowed, "unexpected_child_executable")

    def live(self):
        live = []
        for ident in list(self.seen):
            try:
                proc = self.ps.Process(ident[0])
                require(self.identity(proc) == ident, "owned_identity_changed")
                live.append(proc)
                for child in proc.children(recursive=True):
                    try:
                        self.capture(child)
                    except self.ps.NoSuchProcess:
                        continue
            except self.ps.NoSuchProcess:
                continue
        return live

    def sample(self, rss, host):
        self.live()
        total = 0
        for ident in list(self.seen):
            try:
                proc = self.ps.Process(ident[0])
                require(self.identity(proc) == ident, "owned_identity_changed")
                total += proc.memory_info().rss
            except self.ps.NoSuchProcess:
                continue
        self.peak = max(self.peak, total)
        available = self.ps.virtual_memory().available
        self.minimum_host = available if self.minimum_host is None else min(self.minimum_host, available)
        self.samples += 1
        require(total <= rss and available >= host, "resource_budget")
        return total

    def cleanup(self, deadline):
        failures = []
        try:
            self.live()
        except Exception as error:  # noqa: BLE001 - preserve unknown cleanup state as failure
            failures.append(type(error).__name__)
        for ident in reversed(list(self.seen)):
            try:
                proc = self.ps.Process(ident[0])
                require(self.identity(proc) == ident, "cleanup_identity_unknown")
                proc.kill()
            except self.ps.NoSuchProcess:
                pass
            except Exception as error:  # noqa: BLE001 - preserve unknown cleanup state as failure
                failures.append(type(error).__name__)
        # Release only our Popen handle after observing its terminal result.
        try:
            self.process.wait(timeout=max(0.001, deadline - self.clock()))
        except Exception as error:  # noqa: BLE001 - preserve unknown cleanup state as failure
            failures.append(type(error).__name__)
        handle = getattr(self.process, "_handle", None)
        if handle is not None and self.process.returncode is not None:
            try:
                handle.Close()
            except Exception as error:  # noqa: BLE001 - record original handle close failure
                failures.append(type(error).__name__)
        absent = []
        while self.clock() < deadline:
            absent = []
            for ident in self.seen:
                try:
                    proc = self.ps.Process(ident[0])
                    absent.append(self.identity(proc) != ident)
                except self.ps.NoSuchProcess:
                    absent.append(True)
                except Exception:  # noqa: BLE001 - unknown is never absence
                    absent.append(False)
            if all(absent):
                break
            self.sleeper(0.02)
        return {"identities": [list(x) for x in self.seen], "all_absent": bool(absent) and all(absent),
                "errors": failures, "sampled_peak_rss": self.peak,
                "sampled_minimum_host_available": self.minimum_host, "sample_count": self.samples}


def run_owned(argv, cwd, env, root, log_prefix, deadline, rss, host, start, allowed,
              ps=None, popen=subprocess.Popen, clock=time.monotonic, sleeper=time.sleep):
    if ps is None:
        import psutil as ps
    validate_temporary(root, env)
    require(clock() < deadline - 5, "deadline_before_start")
    require(ps.virtual_memory().available >= start, "startup_resource_gate")
    def startup_checkpoint(event):
        require(clock() < deadline - 5, "deadline_before_start")
        require(ps.virtual_memory().available >= start, "startup_resource_gate")
    disk_bytes(root, checkpoint=startup_checkpoint)
    started = clock()
    record = {"argv": [str(x) for x in argv], "status": "failed", "cleanup": None,
              "budget": {"rss": rss, "host_available": host, "startup_available": start,
                         "shared_seconds_remaining": deadline - started, "cleanup_reserved_seconds": 5},
              "resource_scope": "sampled_owned_tree_not_OS_hard_peak_limit",
              "temporary_directory": env["TEMP"],
              "active_disk_scans": {"count": 0, "entries": 0, "seconds": 0.0}}
    process, tree = None, None
    error = None
    try:
        with Path(str(log_prefix) + ".stdout").open("xb") as out, Path(str(log_prefix) + ".stderr").open("xb") as err:
            process = popen([str(x) for x in argv], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=out, stderr=err, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            tree = OwnedTree(process, allowed, ps, clock, sleeper)
            tree.capture(ps.Process(process.pid))
            def scan_checkpoint(event):
                if event == "before_entry":
                    record["active_disk_scans"]["entries"] += 1
                tree.sample(rss, host)
                require(clock() < deadline - 5, "shared_deadline")
                require(Path(out.name).stat().st_size <= 8 * 1024**2 and Path(err.name).stat().st_size <= 8 * 1024**2, "log_budget")
            while True:
                tree.sample(rss, host)
                require(clock() < deadline - 5, "shared_deadline")
                scan_started = clock()
                record["active_disk_scans"]["count"] += 1
                try:
                    disk_bytes(root, checkpoint=scan_checkpoint)
                finally:
                    record["active_disk_scans"]["seconds"] += clock() - scan_started
                require(Path(out.name).stat().st_size <= 8 * 1024**2 and Path(err.name).stat().st_size <= 8 * 1024**2, "log_budget")
                if process.poll() is not None:
                    break
                sleeper(0.05)
            record["exit"] = process.wait(timeout=max(0.001, deadline - clock() - 5))
            require(record["exit"] == 0, "tool_exit")
            record["status"] = "process_exited_zero_not_semantic_success"
    except Exception as exc:  # noqa: BLE001 - retain cause before bounded cleanup
        error = exc
        record["error"] = type(exc).__name__ + ":" + str(exc)
    finally:
        if tree is not None and tree.seen:
            record["cleanup"] = tree.cleanup(min(deadline, clock() + 5))
        elif process is not None:
            # The original returned Popen handle owns this child even if psutil cannot identify it.
            # Never turn this fallback into verified identity/absence or native success.
            failures = ["identity_capture_failed"]
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=max(0.001, min(deadline, clock() + 5) - clock()))
                handle = getattr(process, "_handle", None)
                if handle is not None and process.returncode is not None:
                    handle.Close()
            except Exception as cleanup_error:  # noqa: BLE001 - handle cleanup failure stays failure
                failures.append(type(cleanup_error).__name__)
            record["cleanup"] = {"all_absent": False, "errors": failures,
                "original_Popen_handle_only": True, "root_terminal": process.returncode is not None,
                "descendant_absence_unverified": True}
        record["elapsed_seconds"] = clock() - started
        record["within_shared_deadline"] = clock() <= deadline
        if error is None:
            if not (record["cleanup"] is not None and record["cleanup"]["all_absent"] and not record["cleanup"]["errors"]):
                error = BoundaryError("cleanup_failed")
            elif not record["within_shared_deadline"]:
                error = BoundaryError("cleanup_or_process_exceeded_shared_deadline")
        try:
            # Failure reporting is best effort, never a fresh successful execution budget.
            write_bounded(root, Path(str(log_prefix) + ".json"), record,
                          deadline=deadline if error is None else None, clock=clock, limit=DISK)
        except Exception as reporting_error:  # noqa: BLE001 - preserve original cause and cleanup evidence
            if error is None:
                error = reporting_error
            else:
                error.add_note("supervision_receipt_failed:" + type(reporting_error).__name__)
    if error:
        error.supervision_record = record
        raise error
    return record
