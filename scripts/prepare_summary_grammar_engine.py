"""Acquire an unreviewed local source/tool lock, or build only an explicitly reviewed lock."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import time
import urllib.error
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.summary_grammar.runtime import (
    BUNDLE,
    COMMIT,
    DISK,
    DOWNLOAD,
    BoundaryError,
    check_refs,
    clean_environment,
    digest,
    disk_bytes,
    inventory,
    load,
    pins,
    reference,
    require,
    reviewed,
    run_owned,
    safe_path,
    write,
    write_bounded,
)


class Budget:
    def __init__(self, root, ps=None, clock=time.monotonic):
        if ps is None:
            import psutil as ps
        self.root, self.ps, self.clock = root, ps, clock
        self.end, self.downloaded = clock() + 600, 0
        self.written = self.scan_count = self.scan_entries = 0
        self.scan_seconds = 0.0
        self.files = {}
        self.total = 0
        self.logs = {"acquisition-supervision.stdout", "acquisition-supervision.stderr"}
        require(ps.virtual_memory().available >= 4 * 1024**3, "preparation_startup_ram")
        self.scan(initial=True)

    def check(self, incoming=0):
        self.downloaded += incoming
        require(self.downloaded <= DOWNLOAD and self.clock() < self.end, "preparation_budget")
        process = self.ps.Process()
        rss = process.memory_info().rss + sum(p.memory_info().rss for p in process.children(recursive=True))
        require(rss <= 2 * 1024**3 and self.ps.virtual_memory().available >= 2 * 1024**3, "preparation_resources")
        self.log_growth()
        return self.total

    def log_growth(self):
        for name in self.logs:
            path = safe_path(self.root, name)
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                require(name not in self.files, "ledger_file_missing")
                continue
            require(path.is_file(), "log_type")
            require(size >= self.files.get(name, 0) and size <= 8 * 1024**2, "log_budget")
            self.total += size - self.files.get(name, 0)
            self.files[name] = size
        require(self.total <= DISK, "disk_budget")

    def scan(self, initial=False):
        started = self.clock()
        observed = {}
        self.scan_count += 1
        try:
            self.check()
            for path in self.root.rglob("*"):
                self.check()
                name = path.relative_to(self.root).as_posix()
                safe_path(self.root, name)
                if path.is_file():
                    observed[name] = path.stat().st_size
                self.scan_entries += 1
                self.check()
            self.check()
            # Logs may grow while scanning. Reconcile their latest directly observed sizes.
            for name in self.logs:
                if name in self.files:
                    observed[name] = self.files[name]
            actual = sum(observed.values())
            require(actual <= DISK, "disk_budget")
            if initial:
                self.files, self.total = observed, actual
            else:
                require(observed == self.files and actual == self.total, "disk_ledger_mismatch")
            return actual
        finally:
            self.scan_seconds += self.clock() - started

    def write_chunk(self, out, data, terminal=False):
        if terminal:
            self.log_growth()
        else:
            self.check()
        path = Path(out.name)
        name = path.relative_to(self.root).as_posix()
        safe_path(self.root, name)
        require(path.stat().st_size == self.files.get(name, 0), "disk_ledger_mismatch")
        require(self.total + len(data) <= DISK, "disk_budget")
        # Reserve before writing. A partial write fails without refund or reuse.
        self.total += len(data)
        self.written += len(data)
        self.files[name] = self.files.get(name, 0) + len(data)
        require(out.write(data) == len(data), "short_write")
        out.flush()

    def write_json(self, path, value, terminal=False):
        data = (json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode()
        with path.open("xb") as stream:
            self.write_chunk(stream, data, terminal=terminal)

    def event(self, phase, state, terminal=False):
        require(phase in {"download-llvm", "extract-llvm", "inventory-llvm", "download-cmake", "extract-cmake", "inventory-cmake",
                          "download-ninja", "extract-ninja", "inventory-ninja", "source-metadata", "sources", "licenses", "manifest"}, "phase_name")
        path = self.root / "acquisition-phases.jsonl"
        data = (json.dumps({"phase": phase, "state": state, "elapsed_seconds": self.clock() - (self.end - 600),
                           "download_body_bytes": self.downloaded, "written_bytes": self.written,
                           "scan_count": self.scan_count, "scan_entries": self.scan_entries,
                           "scan_seconds": self.scan_seconds}, allow_nan=False) + "\n").encode()
        require(self.files.get(path.name, 0) + len(data) <= 32768, "phase_metadata_budget")
        with path.open("ab") as stream:
            self.write_chunk(stream, data, terminal=terminal)

    @contextmanager
    def phase(self, name):
        self.scan()
        self.event(name, "start")
        try:
            yield
            self.scan()
        except Exception as error:
            try:
                self.event(name, "failed", terminal=True)
            except Exception as reporting_error:  # noqa: BLE001 - retain the original phase failure
                error.add_note("phase_metadata_failed:" + type(reporting_error).__name__)
            raise
        self.event(name, "end")


ALLOWED_HOSTS = {"github.com", "api.github.com", "raw.githubusercontent.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}


def checked_url(url):
    parts = urlparse(url)
    require(parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS and not parts.username
            and not parts.password and parts.port in (None, 443), "download_origin")
    return url


class Redirects(urllib.request.HTTPRedirectHandler):
    # Returning the response prevents urllib's default fp.read() and recursive dispatch.
    def http_error_302(self, req, fp, code, msg, headers):
        return fp

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


class ClosedErrors(urllib.request.HTTPDefaultErrorHandler):
    def http_error_default(self, req, fp, code, msg, headers):
        fp.close()
        raise BoundaryError("http_status")


def open_download(url, budget, opener):
    seen = set()
    for hop in range(6):
        budget.check()
        checked_url(url)
        require(url not in seen, "redirect_loop")
        seen.add(url)
        request = urllib.request.Request(url, headers={"User-Agent": "DocTrail-model-free-grammar-preparation", "Accept": "application/vnd.github+json"})
        try:
            response = opener.open(request, timeout=min(10, max(0.001, budget.end - budget.clock())))
        except urllib.error.HTTPError as error:
            error.close()
            raise BoundaryError("http_status") from error
        try:
            budget.check()
            checked_url(response.geturl())
            if response.status == 200:
                return response
            require(response.status in {301, 302, 303, 307, 308}, "http_status")
            require(hop < 5, "redirect_hops")
            location = response.headers.get("Location")
            require(isinstance(location, str) and 0 < len(location) <= 8192, "redirect_location")
            url = checked_url(urljoin(url, location))
        except Exception:
            response.close()
            raise
        response.close()  # Never consume a redirect body, including an error response body.
    raise BoundaryError("redirect_hops")


def fetch(url, path, budget, expected=None, opener=None, max_bytes=DOWNLOAD):
    opener = opener or urllib.request.build_opener(Redirects(), ClosedErrors())
    checked_url(url)
    budget.check()
    size = 0
    with open_download(url, budget, opener) as response, path.open("xb") as out:
        budget.files[path.relative_to(budget.root).as_posix()] = 0
        while True:
            budget.check()
            chunk = response.read(min(65536, max_bytes - size + 1))
            if not chunk:
                break
            size += len(chunk)
            budget.check(len(chunk))
            require(size <= max_bytes, "download_byte_budget")
            budget.write_chunk(out, chunk)
    actual = digest(path.read_bytes())
    require(expected is None or expected == actual, "download_hash_mismatch")
    return actual


def extract_zip(archive, dest, budget):
    dest.mkdir()
    seen, expanded = set(), 0
    initial = budget.check()
    with zipfile.ZipFile(archive) as source:
        infos = source.infolist()
        require(len(infos) <= 50000, "archive_entry_count")
        for info in infos:
            budget.check()
            name = info.filename[:-1] if info.is_dir() else info.filename
            target = safe_path(dest, name)
            require(name.casefold() not in seen, "archive_duplicate")
            seen.add(name.casefold())
            mode = info.external_attr >> 16
            require(not stat.S_ISLNK(mode) and (stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR))
                    and not info.flag_bits & 1, "archive_type")
            expanded += info.file_size
            require(expanded + initial <= DISK, "archive_expanded_budget")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info) as src, target.open("xb") as out:
                budget.files[target.relative_to(budget.root).as_posix()] = 0
                count = 0
                while chunk := src.read(65536):
                    budget.check()
                    count += len(chunk)
                    require(count <= info.file_size, "archive_byte_budget")
                    budget.write_chunk(out, chunk)
            require(count == info.file_size, "archive_size")
    budget.check()


def selected_source(path):
    parts = path.split("/")
    require(parts[0].lower() != "models" and not any(x.lower() in {".git", "node_modules"} for x in parts), "source_payload")
    require(not path.lower().endswith((".gguf", ".safetensors", ".model", ".tiktoken", ".vocab", ".bin")), "source_payload")
    return path in {"CMakeLists.txt", "LICENSE"} or parts[0] in {"cmake", "include", "src", "ggml", "vendor"}


def write_metadata(root, path, value, deadline=None, clock=time.monotonic):
    """Supervisor/early-failure metadata is bounded by the same workspace byte limit."""
    write_bounded(root, path, value, deadline=deadline, clock=clock, limit=DISK)


def acquire(root, opener=None, budget_factory=Budget, worker_token=None):
    root = Path(root).absolute()
    safe_path(root.parent, root.name)
    if worker_token is None:
        root.mkdir(exist_ok=False)
    else:
        require(os.environ.get("DOCTRAIL_ACQUIRE_TOKEN") == worker_token
                and load(root / "acquisition-attempt.json")["worker_token"] == worker_token, "worker_binding")
    budget = None
    try:
        budget = budget_factory(root)
        specification = pins()
        (root / "archives").mkdir()
        (root / "tools").mkdir()
        tools = []
        for item in specification["tools"]:
            tool = "llvm" if "llvm" in item["name"] else "cmake" if "cmake" in item["name"] else "ninja"
            archive = safe_path(root / "archives", item["name"])
            with budget.phase("download-" + tool):
                h = fetch(item["asset"], archive, budget, item["published_sha256"], opener)
            destination = root / "tools" / tool
            with budget.phase("extract-" + tool):
                extract_zip(archive, destination, budget)
            with budget.phase("inventory-" + tool):
                tools.append({"name": item["name"], "url": item["asset"], "archive_sha256": h,
                              "publisher_sha256": item["published_sha256"], "inventory": inventory(destination),
                              "directory": destination.relative_to(root).as_posix()})
        api = "https://api.github.com/repos/ggml-org/llama.cpp/git/"
        with budget.phase("source-metadata"):
            fetch(api + "commits/" + COMMIT, root / "commit.json", budget, opener=opener, max_bytes=2 * 1024**2)
            commit = load(root / "commit.json")
            require(commit["sha"] == COMMIT, "source_commit")
            tree_sha = commit["tree"]["sha"]
            require(len(tree_sha) == 40 and all(c in "0123456789abcdef" for c in tree_sha), "tree_identity")
            fetch(api + "trees/" + tree_sha + "?recursive=1", root / "tree.json", budget, opener=opener, max_bytes=8 * 1024**2)
            tree = load(root / "tree.json")
            require(tree["sha"] == tree_sha and tree.get("truncated") is False and len(tree["tree"]) <= 50000, "tree_truncated")
        source_root = root / "source"
        source_root.mkdir()
        sources = []
        with budget.phase("sources"):
            for entry in tree["tree"]:
                budget.check()
                path = entry["path"]
                if not (path in {"CMakeLists.txt", "LICENSE"} or path.split("/")[0] in {"cmake", "include", "src", "ggml", "vendor"}):
                    continue
                if entry["type"] == "tree":
                    continue
                require(entry["type"] == "blob" and entry["mode"] == "100644" and selected_source(path), "source_type")
                require(type(entry["size"]) is int and 0 <= entry["size"] <= 16 * 1024**2, "source_size")
                target = safe_path(source_root, path)
                target.parent.mkdir(parents=True, exist_ok=True)
                url = f"https://raw.githubusercontent.com/ggml-org/llama.cpp/{COMMIT}/{path}"
                fetch(url, target, budget, opener=opener, max_bytes=entry["size"])
                data = target.read_bytes()
                require(len(data) == entry["size"] and hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == entry["sha"], "source_blob")
                sources.append({**reference(target, source_root), "blob_id": entry["sha"], "url": url})
        require({"CMakeLists.txt", "LICENSE", "src/llama-grammar.cpp", "src/llama-grammar.h"} <= {r["file"] for r in sources}, "source_incomplete")
        # Ninja's tiny release zip may omit COPYING. Preserve the pinned upstream license separately.
        with budget.phase("licenses"):
            fetch("https://raw.githubusercontent.com/ninja-build/ninja/v1.12.1/COPYING", root / "ninja-COPYING", budget, opener=opener, max_bytes=65536)
            license_refs = [reference(root / "ninja-COPYING", root), reference(source_root / "LICENSE", root)]
            for tool in tools:
                found = [r for r in tool["inventory"] if any(x in Path(r["file"]).name.lower() for x in ("license", "copying", "copyright"))]
                require(found or tool["directory"] == "tools/ninja", "tool_license_missing")
                license_refs.extend(reference(root / tool["directory"] / r["file"], root) for r in found)
        with budget.phase("manifest"):
            result = {"schema_version": 1, "status": "ACQUIRED_UNREVIEWED_DO_NOT_EXECUTE", "engine_commit": COMMIT,
                      "tree_id": tree_sha, "source": sources, "tools": tools, "licenses": license_refs,
                      "runtime_bindings": runtime_bindings(root, {"tools": tools}),
                      "bundle": inventory(BUNDLE), "download_bytes": budget.downloaded, "disk_bytes": budget.check(),
                      "compiler_native_execution": 0, "review": "A separate reviewed SHA256 of this exact lock is required by build."}
            budget.write_json(root / "raw-acquisition.json", result)
        budget.scan()
        return result
    except Exception as error:
        failure = {"error": type(error).__name__, "reason": str(error)[:4000], "partial_files_preserved": True, "execution": 0}
        try:
            if budget is None:
                write_metadata(root, root / "acquisition-failure.json", failure)
            else:
                budget.write_json(root / "acquisition-failure.json", failure, terminal=True)
        except Exception as reporting_error:  # noqa: BLE001 - never replace the acquisition failure
            error.add_note("failure_metadata_failed:" + type(reporting_error).__name__)
        raise


def acquire_supervised(root, runner=run_owned, clock=time.monotonic):
    """The supervisor can stop a blocked DNS/socket/extraction worker at the shared deadline."""
    deadline = clock() + 600
    def checkpoint():
        require(clock() < deadline, "shared_deadline")
    root = Path(root).absolute()
    safe_path(root.parent, root.name)
    root.mkdir(exist_ok=False)
    token = secrets.token_hex(24)
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "_acquire-worker",
               "--workspace", str(root), "--worker-token", token]
    write_metadata(root, root / "acquisition-attempt.json", {"worker_token": token, "argv": command,
          "shared_seconds": 600, "retry": False}, deadline=deadline, clock=clock)
    allowed = [Path(sys.executable), Path(getattr(sys, "_base_executable", sys.executable))]
    if "SystemRoot" in os.environ:
        allowed.append(Path(os.environ["SystemRoot"]) / "System32/conhost.exe")
    env = clean_environment([Path(sys.executable).parent], root, "acquisition-tmp")
    env["DOCTRAIL_ACQUIRE_TOKEN"] = token
    try:
        runner(command, cwd=root, env=env, root=root, log_prefix=root / "acquisition-supervision",
               deadline=deadline, rss=2 * 1024**3, host=2 * 1024**3, start=4 * 1024**3,
               allowed=allowed, clock=clock)
        checkpoint()
        result = load(root / "raw-acquisition.json")
        checkpoint()
        result["acquisition_cleanup"] = reference(root / "acquisition-supervision.json", root)
        checkpoint()
        candidate = root / "acquisition-pending.json"
        write_metadata(root, candidate, result, deadline=deadline, clock=clock)
        checkpoint()
        candidate.rename(root / "acquisition.json")
        try:
            checkpoint()
        except Exception as error:
            # Keep late publication as unaccepted evidence, never return it as success.
            try:
                (root / "acquisition.json").rename(candidate)
            except OSError as invalidation_error:
                error.add_note("late_lock_invalidation_failed:" + type(invalidation_error).__name__)
            raise
        return result
    except Exception as error:
        try:
            write_metadata(root, root / "acquisition-supervision-failure.json", {"error": type(error).__name__,
                           "reason": str(error)[:4000], "partial_files_preserved": True, "no_retry": True})
        except Exception as reporting_error:  # noqa: BLE001 - retain original supervision failure
            error.add_note("supervision_metadata_failed:" + type(reporting_error).__name__)
        raise


def executable(root, lock, tool, basename):
    row = next(x for x in lock["tools"] if x["directory"] == "tools/" + tool)
    matches = [x for x in row["inventory"] if Path(x["file"]).name.lower() == basename]
    require(len(matches) == 1, "tool_executable_ambiguous")
    return safe_path(root / row["directory"], matches[0]["file"])


LD_ARGS = ["COMMAND", "ld", "-v", "OUTPUT_VARIABLE", "_help", "ERROR_VARIABLE", "_help"]
LD_SOURCE = "execute_process(COMMAND ld -v OUTPUT_VARIABLE _help ERROR_VARIABLE _help)"


def runtime_bindings(root, lock):
    """Bind archive identities for later review; never execute or infer installed versions."""
    llvm = next(x for x in lock["tools"] if x["directory"] == "tools/llvm")
    drivers = [r for r in llvm["inventory"] if re.fullmatch(r"clang-[0-9]+\.exe", Path(r["file"]).name)]
    require(len(drivers) == 1, "versioned_driver_ambiguous")
    driver = safe_path(root / llvm["directory"], drivers[0]["file"])
    require(driver.parent.name == "bin", "driver_bin_directory")
    major = driver.stem.removeprefix("clang-")
    wrappers = [executable(root, lock, "llvm", name) for name in ("clang.exe", "clang++.exe")]
    require(all(p.parent == driver.parent for p in wrappers), "driver_wrapper_directory")
    resource_prefix = driver.parent.parent.relative_to(root / llvm["directory"]).as_posix()
    resource_prefix = (resource_prefix + "/" if resource_prefix != "." else "") + "lib/clang/" + major + "/"
    require(any(r["file"].startswith(resource_prefix) for r in llvm["inventory"]), "driver_resource_major")
    cmake = next(x for x in lock["tools"] if x["directory"] == "tools/cmake")
    modules = [r for r in cmake["inventory"] if r["file"].endswith("share/cmake-3.31/Modules/Platform/Windows-GNU.cmake")]
    require(len(modules) == 1, "optional_probe_module")
    module = safe_path(root / cmake["directory"], modules[0]["file"])
    lines = module.read_text(encoding="utf-8").splitlines()
    require(len(lines) >= 55 and lines[54] == LD_SOURCE and lines.count(LD_SOURCE) == 1, "optional_probe_source")
    refs = [reference(p, root) for p in [*wrappers, driver, module]]
    # Verify every binding against an archive inventory before recording it.
    for path in [*wrappers, driver, module]:
        tool = llvm if path != module else cmake
        rel = path.relative_to(root / tool["directory"]).as_posix()
        check_refs(root / tool["directory"], [next(r for r in tool["inventory"] if r["file"] == rel)])
    return {"basis": "archive_inventory_and_pinned_source_not_runtime_version_observation",
            "wrapper_driver_edges": [{"wrapper": ref, "driver": refs[2]} for ref in refs[:2]],
            "optional_ld_query": {"module": refs[3], "line": 55, "args": LD_ARGS}}


def optional_probe_guard(root, binding, env, application_dir):
    """No executable permission for ld. Check Windows search locations, never ambient PATH."""
    check_refs(root, [binding["module"]])
    require(binding["line"] == 55 and binding["args"] == LD_ARGS, "optional_probe_binding")
    directories = [Path(application_dir), Path(root), *map(Path, env["PATH"].split(os.pathsep))]
    require(all(p.is_absolute() for p in directories), "optional_probe_relative_search")
    if "SystemRoot" in env:
        system = Path(env["SystemRoot"])
        require(system.is_absolute(), "optional_probe_system_root")
        directories.extend([system / "System32", system / "System", system])
    candidates = []
    for folder in dict.fromkeys(directories):
        # CreateProcess appends .exe to the extensionless command. Also reject
        # command-script aliases conservatively; the extensionless POSIX ld
        # wrapper in LLVM-MinGW is not a Windows executable permission.
        for name in ("ld.exe", "ld.com", "ld.cmd", "ld.bat"):
            candidate = folder / name
            try:
                candidate.lstat()
            except FileNotFoundError:
                candidates.append(str(candidate))
            else:
                raise BoundaryError("optional_ld_executable_present")
    return {"binding": binding, "absent_candidates": candidates,
            "scope": "preflight_absence_not_an_execution_result; observed_ld_children_still_forbidden"}


def check_acquired(root, reviewed_sha):
    require(not (root / "acquisition-pending.json").exists()
            and not (root / "acquisition-supervision-failure.json").exists(), "acquisition_finalization_failed")
    lock = reviewed(root / "acquisition.json", reviewed_sha)
    require(lock["status"] == "ACQUIRED_UNREVIEWED_DO_NOT_EXECUTE" and lock["engine_commit"] == COMMIT, "acquisition_contract")
    check_refs(root, [lock["acquisition_cleanup"]])
    cleanup = load(root / lock["acquisition_cleanup"]["file"])["cleanup"]
    require(cleanup["all_absent"] and not cleanup["errors"], "acquisition_cleanup_failed")
    check_refs(BUNDLE, lock["bundle"], exact=True)
    check_refs(root / "source", [{k: row[k] for k in ("file", "size_bytes", "sha256")} for row in lock["source"]])
    require({r["file"] for r in inventory(root / "source")} == {r["file"] for r in lock["source"]}, "extra_source")
    configured = pins()["tools"]
    require([row["name"] for row in lock["tools"]] == [row["name"] for row in configured], "tool_set")
    for row, pin in zip(lock["tools"], configured, strict=True):
        require(isinstance(row["archive_sha256"], str) and len(row["archive_sha256"]) == 64
                and all(c in "0123456789abcdef" for c in row["archive_sha256"]), "tool_hash_unfixed")
        require(row["url"] == pin["asset"] and (pin["published_sha256"] is None
                or row["archive_sha256"] == pin["published_sha256"]), "tool_pin_changed")
        require(digest(safe_path(root / "archives", row["name"]).read_bytes()) == row["archive_sha256"], "archive_changed")
        check_refs(root / row["directory"], row["inventory"], exact=True)
    check_refs(root, lock["licenses"])
    require(lock["runtime_bindings"] == runtime_bindings(root, lock), "runtime_bindings_changed")
    return lock


def audit_trace(path, allowed, optional_probe=None, root=None):
    require(path.is_file() and path.stat().st_size <= 8 * 1024**2, "trace_missing_or_large")
    allowed = {os.path.normcase(str(Path(p).resolve())) for p in allowed}
    if optional_probe is not None:
        check_refs(root, [optional_probe["binding"]["module"]])
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if "version" in row:
            continue
        command, args = row.get("cmd", "").lower(), row.get("args", [])
        lowered = [str(x).lower() for x in args]
        require(not command.startswith(("fetchcontent_", "externalproject_")) and not (command == "file" and lowered and lowered[0] in {"download", "upload"}), "configure_network")
        if command in {"execute_process", "exec_program", "try_run"}:
            require(command == "execute_process", "unexpected_configure_execution")
            if optional_probe is not None:
                binding = optional_probe["binding"]
                module = safe_path(root, binding["module"]["file"])
                if (args == LD_ARGS and row.get("line") == binding["line"]
                        and Path(row.get("file", "")).is_absolute()
                        and Path(row["file"]).resolve() == module.resolve()):
                    count += 1
                    continue
            calls = [args[i + 1] for i, a in enumerate(args[:-1]) if a.upper() == "COMMAND"]
            require(calls and all(Path(x).is_absolute() and os.path.normcase(str(Path(x).resolve())) in allowed for x in calls), "configure_unapproved_executable")
            require(not any("git" == Path(x).stem.lower() or "curl" in x or "wget" in x for x in lowered), "configure_git_or_download")
        count += 1
    require(count > 0, "empty_trace")
    return count


def build(root, reviewed_sha, runner=run_owned, clock=time.monotonic):
    root = Path(root).absolute()
    require(not (root / "build-attempt.json").exists(), "build_once")
    lock = check_acquired(root, reviewed_sha)
    cmake = executable(root, lock, "cmake", "cmake.exe")
    ninja = executable(root, lock, "ninja", "ninja.exe")
    cc = executable(root, lock, "llvm", "clang.exe")
    cxx = executable(root, lock, "llvm", "clang++.exe")
    allowed = [root / t["directory"] / f["file"] for t in lock["tools"] for f in t["inventory"] if Path(f["file"]).name.lower() in {"cmake.exe", "ninja.exe", "clang.exe", "clang++.exe", "ld.lld.exe", "lld.exe", "llvm-ar.exe", "llvm-ranlib.exe", "llvm-rc.exe", "llvm-mt.exe"}]
    if "SystemRoot" in os.environ:
        allowed.append(Path(os.environ["SystemRoot"]) / "System32/conhost.exe")
    bindings = lock["runtime_bindings"]
    require(bindings == runtime_bindings(root, lock), "runtime_bindings_changed")
    allowed.extend(safe_path(root, edge["driver"]["file"]) for edge in bindings["wrapper_driver_edges"])
    deadline = clock() + 900
    env = clean_environment([cc.parent, cmake.parent, ninja.parent], root, "build-tmp")
    probe = optional_probe_guard(root, bindings["optional_ld_query"], env, cmake.parent)
    target = root / "build"
    trace = root / "configure-trace.jsonl"
    configure = [cmake, "-S", BUNDLE, "-B", target, "-G", "Ninja", "--trace-expand", "--trace-format=json-v1", "--trace-redirect=" + str(trace),
                 "-DLLAMA_SOURCE=" + str(root / "source"), "-DCMAKE_C_COMPILER=" + str(cc), "-DCMAKE_CXX_COMPILER=" + str(cxx),
                 "-DCMAKE_MAKE_PROGRAM=" + str(ninja), "-DCMAKE_BUILD_TYPE=Release"]
    write(root / "build-attempt.json", {"acquisition_sha256": reviewed_sha, "command": list(map(str, configure)), "deadline_seconds": 900, "retry": False,
          "runtime_bindings": bindings, "optional_probe_preflight": probe, "temporary_directory": env["TEMP"]})
    try:
        kwargs = {"cwd": root, "env": env, "root": root, "deadline": deadline, "rss": 2 * 1024**3, "host": 2 * 1024**3, "start": 4 * 1024**3, "allowed": allowed}
        runner(configure, log_prefix=root / "configure", **kwargs)
        require(probe == optional_probe_guard(root, bindings["optional_ld_query"], env, cmake.parent), "optional_probe_changed")
        traced = audit_trace(trace, allowed, probe, root)
        runner([cmake, "--build", target, "--target", "summary-grammar-validator", "--parallel", "2"], log_prefix=root / "compile", **kwargs)
        check_acquired(root, reviewed_sha)
        exe = safe_path(target, "bin/summary-grammar-validator.exe")
        require(exe.is_file(), "validator_missing")
        result = {"status": "BUILT_UNREVIEWED_NOT_ENGINE_VALIDATED", "acquisition_sha256": reviewed_sha,
                  "executable": reference(exe, root), "configure_trace": reference(trace, root), "trace_commands": traced,
                  "bundle": lock["bundle"], "cleanup_receipts": [reference(root / (x + ".json"), root) for x in ("configure", "compile")],
                  "build_logs": [reference(root / (x + ext), root) for x in ("configure", "compile") for ext in (".stdout", ".stderr")],
                  "native_batch_runs": 0, "disk_bytes": disk_bytes(root)}
        write(root / "build-manifest.json", result)
        return result
    except Exception as error:
        write(root / "build-failure.json", {"error": type(error).__name__, "reason": str(error), "no_retry": True, "partial_files_preserved": True})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["inspect", "acquire", "build", "_acquire-worker"])
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--worker-token", help=argparse.SUPPRESS)
    parser.add_argument("--reviewed-acquisition-sha256")
    args = parser.parse_args()
    if args.operation == "inspect":
        print(json.dumps({"pins": pins(), "executable_ready": False}))
    else:
        require(args.workspace is not None, "workspace_required")
        if args.operation == "_acquire-worker":
            require(args.worker_token is not None, "worker_token_required")
            result = acquire(args.workspace, worker_token=args.worker_token)
        elif args.operation == "acquire":
            result = acquire_supervised(args.workspace)
        else:
            result = build(args.workspace, args.reviewed_acquisition_sha256)
        print(json.dumps({"status": result["status"]}))


if __name__ == "__main__":
    try:
        main()
    except (BoundaryError, OSError, ValueError) as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        raise SystemExit(1) from error
