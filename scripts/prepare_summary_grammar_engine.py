"""Acquire an unreviewed local source/tool lock, or build only an explicitly reviewed lock."""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import math
import os
import re
import secrets
import stat
import sys
import time
import urllib.error
import urllib.request
import zipfile
from contextlib import contextmanager, nullcontext
from functools import wraps
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
    parse_json,
    pins,
    reference,
    require,
    run_owned,
    safe_path,
    write,
    write_bounded,
)

ACQUISITION_PROFILE = "llvm-x64-sampled-50ms-v1"
ACQUISITION_PROFILE_1800 = "llvm-x64-sampled-50ms-1800s-v1"
LLVM_PREFIX = "llvm-mingw-20250709-ucrt-x86_64/"
LLVM_SHA = "82babcd6aae4dc3606e8e0471d816989c384b4bf86a139f184a8b4a1b2c2758d"


def validate_acquisition_profile(value):
    require(value in (None, ACQUISITION_PROFILE, ACQUISITION_PROFILE_1800), "acquisition_profile")
    return value


def acquisition_seconds(profile):
    validate_acquisition_profile(profile)
    return 1800 if profile == ACQUISITION_PROFILE_1800 else 600


def budget_guard(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        if self.profile and self.failure is not None:
            raise self.failure
        try:
            return method(self, *args, **kwargs)
        except Exception as error:
            if self.profile:
                self.failure = self.failure or error
                raise self.failure
            raise
    return guarded


class Budget:
    def __init__(self, root, ps=None, clock=time.monotonic, acquisition_profile=None):
        if ps is None:
            import psutil as ps
        self.profile = validate_acquisition_profile(acquisition_profile)
        self.failure, self.last_sample_start = None, None
        self.samples, self.sample_attempts, self.max_sample_gap, self.forced_samples = 0, 0, 0.0, {}
        self.terminal_observation = "not_attempted"
        self.root, self.ps, self.clock = root, ps, clock
        self.seconds = acquisition_seconds(self.profile)
        self.end, self.downloaded = clock() + self.seconds, 0
        self.written = self.scan_count = self.scan_entries = 0
        self.scan_seconds = 0.0
        self.files = {}
        self.total = 0
        self.logs = {"acquisition-supervision.stdout", "acquisition-supervision.stderr"}
        require(ps.virtual_memory().available >= 4 * 1024**3, "preparation_startup_ram")
        if self.profile:
            require(self.clock() < self.end, "preparation_budget")
            self.check(force="start")
        self.scan(initial=True)

    @budget_guard
    def check(self, incoming=0, force=None):
        if self.profile:
            self.downloaded += incoming
            require(self.downloaded <= DOWNLOAD and self.clock() < self.end, "preparation_budget")
            self.log_growth()
            require(self.clock() < self.end, "preparation_budget")
            started = self.clock()
            if force or self.last_sample_start is None or started - self.last_sample_start >= 0.050:
                self.sample_attempts += 1
                if self.last_sample_start is not None:
                    self.max_sample_gap = max(self.max_sample_gap, started - self.last_sample_start)
                process = self.ps.Process()
                rss = process.memory_info().rss + sum(p.memory_info().rss for p in process.children(recursive=True))
                require(rss <= 2 * 1024**3 and self.ps.virtual_memory().available >= 2 * 1024**3, "preparation_resources")
                require(self.clock() < self.end, "preparation_budget")
                self.last_sample_start = started
                self.samples += 1
                if force:
                    self.forced_samples[force] = self.forced_samples.get(force, 0) + 1
            return self.total
        self.downloaded += incoming
        require(self.downloaded <= DOWNLOAD and self.clock() < self.end, "preparation_budget")
        process = self.ps.Process()
        rss = process.memory_info().rss + sum(p.memory_info().rss for p in process.children(recursive=True))
        require(rss <= 2 * 1024**3 and self.ps.virtual_memory().available >= 2 * 1024**3, "preparation_resources")
        self.log_growth()
        return self.total

    @budget_guard
    def log_growth(self):
        for name in self.logs:
            path = safe_path(self.root, name)
            try:
                attrs = path.lstat()
            except FileNotFoundError:
                require(name not in self.files, "ledger_file_missing")
                continue
            require(not stat.S_ISLNK(attrs.st_mode) and not getattr(attrs, "st_file_attributes", 0) & 1024,
                    "reparse_path")
            require(stat.S_ISREG(attrs.st_mode), "log_type")
            size = attrs.st_size
            require(size >= self.files.get(name, 0) and size <= 8 * 1024**2, "log_budget")
            self.total += size - self.files.get(name, 0)
            self.files[name] = size
        require(self.total <= DISK, "disk_budget")

    @budget_guard
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
                attrs = path.lstat()
                require(not stat.S_ISLNK(attrs.st_mode) and not getattr(attrs, "st_file_attributes", 0) & 1024,
                        "reparse_path")
                if stat.S_ISREG(attrs.st_mode):
                    observed[name] = attrs.st_size
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

    @budget_guard
    def write_chunk(self, out, data, terminal=False):
        if terminal and not self.profile:
            self.log_growth()
        else:
            self.check()
        path = Path(out.name)
        name = path.relative_to(self.root).as_posix()
        safe_path(self.root, name)
        require(path.stat().st_size == self.files.get(name, 0), "disk_ledger_mismatch")
        require(self.total + len(data) <= DISK, "disk_budget")
        if self.profile:
            require(self.clock() < self.end, "preparation_budget")
        # Reserve before writing. A partial write fails without refund or reuse.
        self.total += len(data)
        self.written += len(data)
        self.files[name] = self.files.get(name, 0) + len(data)
        require(out.write(data) == len(data), "short_write")
        out.flush()
        if self.profile:
            self.check()

    @budget_guard
    def write_json(self, path, value, terminal=False):
        data = (json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode()
        with path.open("xb") as stream:
            self.write_chunk(stream, data, terminal=terminal)

    @budget_guard
    def event(self, phase, state, terminal=False):
        require(phase in {"download-llvm", "extract-llvm", "inventory-llvm", "download-cmake", "extract-cmake", "inventory-cmake",
                          "download-ninja", "extract-ninja", "inventory-ninja", "source-metadata", "sources", "licenses", "manifest"}, "phase_name")
        path = self.root / "acquisition-phases.jsonl"
        data = (json.dumps({"phase": phase, "state": state, "elapsed_seconds": self.clock() - (self.end - self.seconds),
                           "download_body_bytes": self.downloaded, "written_bytes": self.written,
                           "scan_count": self.scan_count, "scan_entries": self.scan_entries,
                           "scan_seconds": self.scan_seconds,
                           **({"resource_sampling": self.sampling("phase:" + phase + ":" + state)} if self.profile else {})}, allow_nan=False) + "\n").encode()
        require(self.files.get(path.name, 0) + len(data) <= 32768, "phase_metadata_budget")
        with path.open("ab") as stream:
            self.write_chunk(stream, data, terminal=terminal)

    def sampling(self, point):
        return {"profile": self.profile, "interval_seconds": 0.050, "observation_point": point,
                "sample_count": self.samples, "sample_count_basis": "successful_resource_calls",
                "attempted_sample_count": self.sample_attempts, "forced_reasons": dict(self.forced_samples),
                "maximum_observed_start_gap_seconds": self.max_sample_gap,
                "terminal_observation": self.terminal_observation,
                "failure_latched": self.failure is not None,
                "scope": "checkpoint_schedule_not_hard_timer_or_peak_guarantee"}

    def failure_terminal(self):
        # A sticky failure cannot be cleared to take another sample or publish success.
        self.terminal_observation = "skipped_prior_failure" if self.failure else "skipped_deadline"

    @contextmanager
    def phase(self, name):
        if self.profile:
            self.check(force="phase-start:" + name)
        self.scan()
        self.event(name, "start")
        try:
            yield
            self.scan()
        except Exception as error:
            if self.profile:
                self.failure = self.failure or error
                self.failure_terminal()
            try:
                self.event(name, "failed", terminal=True)
            except Exception as reporting_error:  # noqa: BLE001 - retain the original phase failure
                error.add_note("phase_metadata_failed:" + type(reporting_error).__name__)
            if self.profile:
                raise self.failure
            raise
        if self.profile:
            self.check(force="phase-complete:" + name)
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


class SourceHTTPS:
    """One owned, verified-TLS connection for serial source GETs; never retry."""
    def __init__(self):
        self.connection = self.origin = self.response = None

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        self.discard(error)

    def close(self):
        response, connection = self.response, self.connection
        self.response = self.connection = self.origin = None
        try:
            if response is not None:
                response.closed = True
                response.raw.close()
        finally:
            if connection is not None:
                primary = sys.exception()
                try:
                    connection.close()
                except Exception as error:
                    if primary is None:
                        raise
                    primary.add_note("source_https_connection_close_failed:" + type(error).__name__)

    def discard(self, error=None):
        try:
            self.close()
        except Exception as closing_error:  # Retain the first request/body/phase failure.
            if error is None:
                raise
            error.add_note("source_https_close_failed:" + type(closing_error).__name__)

    def open(self, request, timeout):
        try:
            parts = urlparse(checked_url(request.full_url))
            require(request.get_method() == "GET", "source_http_method")
            origin = (parts.hostname, 443)
            if self.response is not None or self.origin != origin:
                self.close()
            if self.connection is None:
                # HTTPSConnection's default context verifies certificates and hostnames.
                # No urllib proxy/config handlers, credentials, or retry layer are used.
                self.connection = http.client.HTTPSConnection(origin[0], port=443, timeout=timeout)
                self.origin = origin
            self.connection.timeout = timeout
            if self.connection.sock is not None:
                self.connection.sock.settimeout(timeout)
            self.connection.request("GET", request.selector, headers=dict(request.header_items()))
            raw = self.connection.getresponse()
            self.response = SourceResponse(self, raw, request.full_url)
            if raw.status == 200:
                lengths = raw.headers.get_all("Content-Length", [])
                transfers = raw.headers.get_all("Transfer-Encoding", [])
                require(not lengths or (len(lengths) == 1 and re.fullmatch(r"[0-9]+", lengths[0].strip())), "source_http_framing")
                require(not transfers or (len(transfers) == 1 and transfers[0].lower().strip() == "chunked" and not lengths), "source_http_framing")
            return self.response
        except Exception as error:
            self.discard(error)
            raise


class SourceResponse:
    def __init__(self, owner, raw, url):
        self.owner, self.raw, self.url = owner, raw, url
        self.status, self.headers = raw.status, raw.headers
        self.complete = self.closed = False

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        if error is not None:
            self.owner.discard(error)
        else:
            self.close()

    def read(self, size):
        try:
            data = self.raw.read(size)
            if not data and size != 0:
                require(self.raw.length in (None, 0), "source_http_truncated")
                self.complete = True
            return data
        except Exception as error:
            self.owner.discard(error)
            raise

    def close(self):
        if self.closed:
            return
        primary = sys.exception()
        try:
            if not self.complete or self.status != 200 or self.raw.will_close:
                self.owner.close()
            else:
                self.raw.close()
                self.closed = True
                self.owner.response = None
        except Exception as error:
            if primary is not None:
                primary.add_note("source_https_close_failed:" + type(error).__name__)
            self.owner.discard(primary if primary is not None else error)
            if primary is None:
                raise


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


def llvm_selection(infos, dest, initial=0, checkpoint=lambda: None):
    require(len(infos) <= 50000, "archive_entry_count")
    keep = {"bin", "include", "lib", "share", "x86_64-w64-mingw32"}
    omit = {"aarch64-w64-mingw32", "armv7-w64-mingw32", "i686-w64-mingw32", "python"}
    seen, expanded, selected, parents = set(), 0, [], set()
    for info in infos:
        checkpoint()
        name = info.filename[:-1] if info.is_dir() else info.filename
        safe_path(dest, name)
        require(name.casefold() not in seen, "archive_duplicate")
        seen.add(name.casefold())
        mode = info.external_attr >> 16
        require(not stat.S_ISLNK(mode) and stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR)
                and not info.flag_bits & 1, "archive_type")
        require(info.file_size >= 0, "archive_size")
        expanded += info.file_size
        require(expanded + initial <= DISK, "archive_expanded_budget")
        require(name == LLVM_PREFIX[:-1] or name.startswith(LLVM_PREFIX), "llvm_root")
        relative = name[len(LLVM_PREFIX):] if name.startswith(LLVM_PREFIX) else ""
        top = relative.split("/")[0]
        license_file = not info.is_dir() and any(x in Path(name).name.lower() for x in ("license", "copying", "copyright"))
        require(not relative or top in keep | omit or ("/" not in relative and license_file), "llvm_unknown_top_level")
        if not relative or top in keep or license_file:
            selected.append(info)
            parents.update(str(parent).replace("\\", "/") for parent in Path(name).parents if str(parent) != ".")
        checkpoint()
    selected_names = {i.filename for i in selected}
    selected.extend(i for i in infos if i.is_dir() and i.filename.rstrip("/") in parents and i.filename not in selected_names)
    selected.sort(key=lambda i: i.filename)
    files = {i.filename: i for i in selected if not i.is_dir()}
    for name in ("bin/clang.exe", "bin/clang++.exe", "bin/clang-20.exe", "LICENSE.TXT",
                 "include/windows.h", "include/_mingw.h", "include/c++/v1/__config"):
        require(LLVM_PREFIX + name in files and files[LLVM_PREFIX + name].file_size > 0, "llvm_required_file")
    drivers = [name for name in files if re.fullmatch(r"clang-[0-9]+\.exe", Path(name).name)]
    require(drivers == [LLVM_PREFIX + "bin/clang-20.exe"], "llvm_required_driver")
    for prefix in ("bin/", "include/", "lib/", "share/", "lib/clang/20/include/", "x86_64-w64-mingw32/lib/"):
        require(any(name.startswith(LLVM_PREFIX + prefix) and info.file_size > 0 for name, info in files.items()), "llvm_required_subtree")
    rows = [[i.filename, i.file_size, i.CRC, i.external_attr] for i in selected]
    descriptor = {"policy": ACQUISITION_PROFILE, "prefix": LLVM_PREFIX,
                  "selection_sha256": digest(json.dumps(rows, ensure_ascii=True, separators=(",", ":")).encode()),
                  "selected_entries": len(selected), "excluded_entries": len(infos) - len(selected),
                  "selected_bytes": sum(i.file_size for i in selected),
                  "excluded_bytes": expanded - sum(i.file_size for i in selected)}
    checkpoint()
    return selected, descriptor


def extract_llvm_x64(archive, dest, budget):
    require(digest(archive.read_bytes()) == LLVM_SHA, "llvm_archive_pin")
    budget.check()
    dest.mkdir()
    with zipfile.ZipFile(archive) as source:
        selected, descriptor = llvm_selection(source.infolist(), dest, budget.check(), budget.check)
        for info in selected:
            budget.check()
            target = safe_path(dest, info.filename.rstrip("/"))
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
    budget.check()
    return descriptor


def selected_source(path):
    parts = path.split("/")
    require(parts[0].lower() != "models" and not any(x.lower() in {".git", "node_modules"} for x in parts), "source_payload")
    require(not path.lower().endswith((".gguf", ".safetensors", ".model", ".tiktoken", ".vocab", ".bin")), "source_payload")
    return path in {"CMakeLists.txt", "LICENSE"} or parts[0] in {"cmake", "include", "src", "ggml", "vendor"}


def write_metadata(root, path, value, deadline=None, clock=time.monotonic):
    """Supervisor/early-failure metadata is bounded by the same workspace byte limit."""
    write_bounded(root, path, value, deadline=deadline, clock=clock, limit=DISK)


def acquire(root, opener=None, budget_factory=Budget, worker_token=None, acquisition_profile=None):
    profile = validate_acquisition_profile(acquisition_profile)
    root = Path(root).absolute()
    safe_path(root.parent, root.name)
    if worker_token is None:
        require(profile is None, "profile_requires_supervision")
        root.mkdir(exist_ok=False)
    else:
        require(os.environ.get("DOCTRAIL_ACQUIRE_TOKEN") == worker_token
                and load(root / "acquisition-attempt.json")["worker_token"] == worker_token, "worker_binding")
        attempt = load(root / "acquisition-attempt.json")
        require(attempt.get("acquisition_profile") == profile, "worker_profile_binding")
        if profile:
            require(type(attempt.get("shared_seconds")) is int
                    and attempt["shared_seconds"] == acquisition_seconds(profile), "worker_duration_binding")
            require(attempt["argv"] == [sys.executable, "-B", str(Path(__file__).resolve()), "_acquire-worker",
                    "--workspace", str(root), "--worker-token", worker_token,
                    "--acquisition-profile", profile], "worker_attempt_binding")
    budget = None
    try:
        budget = budget_factory(root, acquisition_profile=profile) if profile else budget_factory(root)
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
            selection = None
            with budget.phase("extract-" + tool):
                if profile and tool == "llvm":
                    selection = extract_llvm_x64(archive, destination, budget)
                else:
                    extract_zip(archive, destination, budget)
            with budget.phase("inventory-" + tool):
                tools.append({"name": item["name"], "url": item["asset"], "archive_sha256": h,
                              "publisher_sha256": item["published_sha256"], "inventory": inventory(destination),
                              "directory": destination.relative_to(root).as_posix(),
                              **({"selection": selection} if selection is not None else {})})
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
        with budget.phase("sources"), (nullcontext(opener) if opener is not None else SourceHTTPS()) as source_opener:
            for entry in tree["tree"]:
                budget.check()
                path = entry["path"]
                if not (path in {"CMakeLists.txt", "LICENSE"} or path.split("/")[0] in {"cmake", "include", "src", "ggml", "vendor"}):
                    continue
                if entry["type"] == "tree":
                    continue
                require(entry["type"] == "blob" and entry["mode"] in ("100644", "100755") and selected_source(path), "source_type")
                require(type(entry["size"]) is int and 0 <= entry["size"] <= 16 * 1024**2, "source_size")
                target = safe_path(source_root, path)
                target.parent.mkdir(parents=True, exist_ok=True)
                url = f"https://raw.githubusercontent.com/ggml-org/llama.cpp/{COMMIT}/{path}"
                fetch(url, target, budget, opener=source_opener, max_bytes=entry["size"])
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
            if profile:
                result["schema_version"] = 2
                result["acquisition_profile"] = profile
                result["worker_sampling"] = budget.sampling("manifest_before_raw_write")
            budget.write_json(root / "raw-acquisition.json", result)
        budget.scan()
        if profile:
            budget.check(force="success-terminal")
            budget.terminal_observation = "observed_success_terminal"
            budget.write_json(root / "worker-terminal.json", budget.sampling("success_terminal_before_receipt_write"))
            budget.check()
        return result
    except Exception as error:
        if profile and budget is not None:
            budget.failure = budget.failure or error
            budget.failure_terminal()
            error = budget.failure
        failure = {"error": type(error).__name__, "reason": str(error)[:4000], "partial_files_preserved": True, "execution": 0}
        try:
            if budget is None or profile:
                if profile and budget is not None:
                    failure["worker_sampling"] = budget.sampling("failure_before_receipt_write")
                write_metadata(root, root / "acquisition-failure.json", failure)
            else:
                budget.write_json(root / "acquisition-failure.json", failure, terminal=True)
        except Exception as reporting_error:  # noqa: BLE001 - never replace the acquisition failure
            error.add_note("failure_metadata_failed:" + type(reporting_error).__name__)
        if profile and budget is not None:
            raise budget.failure
        raise


def acquire_supervised(root, runner=run_owned, clock=time.monotonic, acquisition_profile=None):
    """The supervisor can stop a blocked DNS/socket/extraction worker at the shared deadline."""
    profile = validate_acquisition_profile(acquisition_profile)
    seconds = acquisition_seconds(profile)
    deadline = clock() + seconds
    def checkpoint():
        require(clock() < deadline, "shared_deadline")
    root = Path(root).absolute()
    safe_path(root.parent, root.name)
    root.mkdir(exist_ok=False)
    token = secrets.token_hex(24)
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "_acquire-worker",
               "--workspace", str(root), "--worker-token", token]
    if profile:
        command.extend(["--acquisition-profile", profile])
    write_metadata(root, root / "acquisition-attempt.json", {"worker_token": token, "argv": command,
          "shared_seconds": seconds, "retry": False, **({"acquisition_profile": profile} if profile else {})}, deadline=deadline, clock=clock)
    allowed = [Path(sys.executable), Path(getattr(sys, "_base_executable", sys.executable))]
    if "SystemRoot" in os.environ:
        allowed.append(Path(os.environ["SystemRoot"]) / "System32/conhost.exe")
    env = clean_environment([Path(sys.executable).parent], root, "acquisition-tmp")
    env["DOCTRAIL_ACQUIRE_TOKEN"] = token
    try:
        runner(command, cwd=root, env=env, root=root, log_prefix=root / "acquisition-supervision",
               deadline=deadline, rss=2 * 1024**3, host=2 * 1024**3, start=4 * 1024**3,
               allowed=allowed, clock=clock, **({"acquisition_profile": profile} if profile else {}))
        checkpoint()
        result = load(root / "raw-acquisition.json")
        if profile:
            require(result.get("acquisition_profile") == profile, "raw_profile_binding")
            check_profile_records(root, result, profile)
            result["worker_terminal"] = reference(root / "worker-terminal.json", root)
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
    require(len(lines) >= 61 and lines[60] == LD_SOURCE and lines.count(LD_SOURCE) == 1, "optional_probe_source")
    refs = [reference(p, root) for p in [*wrappers, driver, module]]
    # Verify every binding against an archive inventory before recording it.
    for path in [*wrappers, driver, module]:
        tool = llvm if path != module else cmake
        rel = path.relative_to(root / tool["directory"]).as_posix()
        check_refs(root / tool["directory"], [next(r for r in tool["inventory"] if r["file"] == rel)])
    return {"basis": "archive_inventory_and_pinned_source_not_runtime_version_observation",
            "wrapper_driver_edges": [{"wrapper": ref, "driver": refs[2]} for ref in refs[:2]],
            "optional_ld_query": {"module": refs[3], "line": 61, "args": LD_ARGS}}


def optional_probe_guard(root, binding, env, application_dir):
    """No executable permission for ld. Check Windows search locations, never ambient PATH."""
    check_refs(root, [binding["module"]])
    require(binding["line"] == 61 and binding["args"] == LD_ARGS, "optional_probe_binding")
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


def check_profile_records(root, lock, profile):
    require(profile in (ACQUISITION_PROFILE, ACQUISITION_PROFILE_1800)
            and lock.get("acquisition_profile") == profile, "acquisition_profile_binding")
    require(not (root / "acquisition-failure.json").exists(), "acquisition_worker_failed")
    attempt, raw = load(root / "acquisition-attempt.json"), load(root / "raw-acquisition.json")
    supervision = load(root / "acquisition-supervision.json")
    require(all(row.get("acquisition_profile") == profile for row in (attempt, raw, supervision)), "acquisition_profile_binding")
    expected_raw = {k: v for k, v in lock.items() if k not in {"acquisition_cleanup", "worker_terminal"}}
    require(raw == expected_raw, "raw_acquisition_changed")
    argv = attempt.get("argv", [])
    require(len(argv) == 10 and argv[-2:] == ["--acquisition-profile", profile]
            and argv[3] == "_acquire-worker" and argv[4:8] == ["--workspace", str(root), "--worker-token", attempt.get("worker_token")]
            and supervision.get("argv") == argv and type(attempt.get("shared_seconds")) is int
            and attempt["shared_seconds"] == acquisition_seconds(profile)
            and attempt.get("retry") is False, "acquisition_attempt_binding")
    require(supervision.get("status") == "process_exited_zero_not_semantic_success" and supervision.get("exit") == 0
            and supervision.get("within_shared_deadline") is True and supervision.get("failure_latched") is False
            and not supervision.get("error"), "acquisition_supervision_failed")
    require(supervision.get("cleanup", {}).get("all_absent") is True
            and supervision["cleanup"].get("errors") == [], "acquisition_cleanup_failed")
    sample = supervision.get("resource_sampling", {})
    require(sample.get("interval_seconds") == 0.050 and sample.get("sample_count", 0) > 0
            and sample.get("terminal_observation") == "observed", "acquisition_sampling_binding")
    if "acquisition_cleanup" in lock:
        require(lock.get("worker_terminal", {}).get("file") == "worker-terminal.json", "worker_terminal_binding")
        check_refs(root, [lock["worker_terminal"]])
    terminal = load(root / "worker-terminal.json")
    require(terminal.get("profile") == profile and terminal.get("interval_seconds") == 0.050
            and terminal.get("failure_latched") is False and terminal.get("terminal_observation") == "observed_success_terminal"
            and terminal.get("forced_reasons", {}).get("success-terminal") == 1, "worker_terminal_binding")
    require(raw.get("worker_sampling", {}).get("profile") == profile
            and raw["worker_sampling"].get("failure_latched") is False, "worker_sampling_binding")


def external_keys(value, keys):
    require(type(value) is dict and set(value) == set(keys.split()), "external_schema")


def external_sha(value):
    require(type(value) is str and re.fullmatch("[0-9a-f]{64}", value), "external_sha")
    return value


def external_number(value, minimum=0):
    require(type(value) in (int, float) and minimum <= value <= sys.float_info.max
            and math.isfinite(value), "external_number")
    return value


def external_absolute(value):
    require(type(value) is str and Path(value).is_absolute()
            and value == os.path.normcase(str(Path(value).resolve())), "external_absolute_path")
    return value


def external_identity(value, kind="cli"):
    external_keys(value, "pid create_time executable" + (" source_sha256" if kind == "observer" else " absent" if kind == "custody" else ""))
    require(type(value["pid"]) is int and value["pid"] > 0, "external_pid")
    require(external_number(value["create_time"]) > 0, "external_create_time")
    executable = external_absolute(value["executable"])
    if kind == "observer":
        external_sha(value["source_sha256"])
    if kind == "custody":
        require(value["absent"] is True, "external_identity_present")
    return value["pid"], value["create_time"], executable


def external_root(root):
    root = Path(root).absolute()
    safe_path(Path(root.anchor), root.relative_to(root.anchor).as_posix())
    require(root.is_dir(), "external_root")
    return root


def external_read(root, name, limit, seen, ref=None, expected=None):
    """Bound every read, hash original bytes, and reject aliases and observed mutation."""
    if ref is not None:
        external_keys(ref, "file size_bytes sha256")
        require(ref["file"] == name and type(ref["size_bytes"]) is int
                and 0 <= ref["size_bytes"] <= limit, "external_reference")
        external_sha(ref["sha256"])
    path = safe_path(root, name)
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and before.st_size <= limit, "external_read_limit")
    identity = before.st_dev, before.st_ino
    require(identity not in seen, "external_file_alias")
    seen.add(identity)
    if ref is not None:
        require(before.st_size == ref["size_bytes"], "external_reference_size")
    def stamp(row):
        # Python 3.12 Windows stat may expose birth time as ctime while fstat
        # exposes change time. Compare stable cross-API fields, then compare
        # ctime separately within each API before/after the read.
        return row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, getattr(row, "st_birthtime_ns", None)
    chunks, size, hasher = [], 0, hashlib.sha256()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        require(stamp(opened) == stamp(before), "external_file_changed")
        while True:
            chunk = stream.read(min(65536, limit - size + 1))
            if not chunk:
                break
            size += len(chunk)
            require(size <= limit and size <= before.st_size, "external_read_limit")
            hasher.update(chunk)
            chunks.append(chunk)
        closed = os.fstat(stream.fileno())
        require(stamp(closed) == stamp(opened) and closed.st_ctime_ns == opened.st_ctime_ns, "external_file_changed")
    safe_path(root, name)
    after = path.stat()
    require(stamp(after) == stamp(before) and after.st_ctime_ns == before.st_ctime_ns
            and size == before.st_size, "external_file_changed")
    sha = hasher.hexdigest()
    if ref is not None:
        require(size == ref["size_bytes"] and sha == ref["sha256"], "external_reference_changed")
    if expected is not None:
        require(sha == external_sha(expected), "external_review_digest_mismatch")
    return b"".join(chunks)


def external_json(data):
    # Explicit UTF-8 rejects JSON's automatic UTF-16/32 byte detection.
    return parse_json(data.decode("utf-8"))


def check_external_acceptance(root, expected):
    """Expected SHA must come from a separately assigned human/parent external review.

    Hashes cannot authenticate an observer or prove self-asserted JSON is truthful.
    Never derive approval from these files, an environment variable or a registry.
    This validates fixed acquisition-terminal custody, not later build WORK contents.
    """
    root = external_root(root)
    companion = external_root(root.with_name(root.name + ".external-review"))
    names = {"acceptance.json", "observer-terminal.json", "custody.json", "cli.stdout", "cli.stderr"}
    observed = set()
    for path in companion.iterdir():
        require(path.name in names and path.name not in observed, "external_companion_files")
        observed.add(path.name)
    require(observed == names, "external_companion_files")
    seen = set()
    acceptance = external_json(external_read(companion, "acceptance.json", 64 * 1024, seen, expected=expected))
    external_keys(acceptance, "schema profile workspace attempt manifest stdout stderr observer_terminal custody sources")
    profile = acceptance["profile"]
    require(profile in (ACQUISITION_PROFILE, ACQUISITION_PROFILE_1800), "external_contract")
    seconds = acquisition_seconds(profile)
    workspace = str(root.resolve())
    def bound(value, schema):
        require(value["schema"] == schema and value["profile"] == profile
                and value["workspace"] == workspace, "external_contract")
    bound(acceptance, "engine-v3-external-acceptance-v1")
    manifest = external_json(external_read(root, "acquisition.json", 16 * 1024**2, seen, acceptance["manifest"]))
    attempt = external_json(external_read(root, "acquisition-attempt.json", 16 * 1024, seen, acceptance["attempt"]))
    require(manifest.get("acquisition_profile") == attempt.get("acquisition_profile") == profile, "acquisition_profile_binding")
    stdout = external_read(companion, "cli.stdout", 4 * 1024, seen, acceptance["stdout"])
    external_read(companion, "cli.stderr", 8 * 1024**2, seen, acceptance["stderr"])
    terminal = external_json(external_read(companion, "observer-terminal.json", 128 * 1024, seen, acceptance["observer_terminal"]))
    custody = external_json(external_read(companion, "custody.json", 256 * 1024, seen, acceptance["custody"]))
    sources = acceptance["sources"]
    require(type(sources) is list and len(sources) == 3, "external_sources")
    repo = external_root(Path(__file__).resolve().parents[1])
    for ref, name, limit in zip(sources, ("scripts/prepare_summary_grammar_engine.py", "tools/summary_grammar/runtime.py", "tools/summary_grammar/pins.json"),
                                (256 * 1024, 128 * 1024, 32 * 1024), strict=True):
        external_read(repo, name, limit, seen, ref)
    external_keys(terminal, "schema evidence_kind profile workspace attempt_sha256 manifest_sha256 stdout_sha256 stderr_sha256 argv observer cli sources_before sources_after exit_code terminal_observed elapsed_seconds budget_seconds cleanup_reserved_seconds limits_pass first_failure")
    bound(terminal, "engine-v3-external-terminal-v1")
    require(terminal["evidence_kind"] == "external_actual_cli_observation", "external_evidence_kind")
    for key in ("attempt", "manifest", "stdout", "stderr"):
        require(terminal[key + "_sha256"] == acceptance[key]["sha256"], "external_terminal_binding")
    # Compare strict revalidated refs, not Python equality (where True equals 1).
    for key in ("sources_before", "sources_after"):
        require(type(terminal[key]) is list and len(terminal[key]) == 3, "external_sources")
        for actual, ref in zip(terminal[key], sources, strict=True):
            external_keys(actual, "file size_bytes sha256")
            require(type(actual["size_bytes"]) is int and actual == ref, "external_sources_changed")
    observer = external_identity(terminal["observer"], "observer")
    cli = external_identity(terminal["cli"])
    require(observer != cli and observer[0] != cli[0], "external_observer_is_cli")
    require(type(attempt) is dict and type(attempt.get("argv")) is list and len(attempt["argv"]) >= 3, "external_attempt_argv")
    prefix = attempt["argv"][:3]
    require(all(type(item) is str for item in prefix) and prefix[1] == "-B"
            and Path(prefix[0]).is_absolute() and Path(prefix[2]).is_absolute()
            and Path(prefix[2]).resolve() == Path(__file__).resolve(), "external_attempt_argv")
    require(terminal["argv"] == prefix + ["acquire", "--workspace", str(root), "--acquisition-profile", profile]
            and cli[2] == os.path.normcase(str(Path(prefix[0]).resolve())), "external_cli_argv")
    require(type(terminal["exit_code"]) is int and terminal["exit_code"] == 0
            and terminal["terminal_observed"] is True and terminal["limits_pass"] is True
            and terminal["first_failure"] is None, "external_terminal_failed")
    require(external_number(terminal["elapsed_seconds"]) <= seconds
            and type(terminal["budget_seconds"]) is int and terminal["budget_seconds"] == seconds
            and type(terminal["cleanup_reserved_seconds"]) is int and terminal["cleanup_reserved_seconds"] == 5,
            "external_time_budget")
    require(stdout in (b'{"status": "ACQUIRED_UNREVIEWED_DO_NOT_EXECUTE"}\n',
                       b'{"status": "ACQUIRED_UNREVIEWED_DO_NOT_EXECUTE"}\r\n'), "external_stdout_protocol")
    external_keys(custody, "schema profile workspace attempt_sha256 manifest_sha256 observer_terminal_sha256 identities all_absent errors")
    bound(custody, "engine-v3-external-custody-v1")
    for key in ("attempt", "manifest", "observer_terminal"):
        require(custody[key + "_sha256"] == acceptance[key]["sha256"], "external_custody_binding")
    require(custody["all_absent"] is True and custody["errors"] == [], "external_custody_failed")
    rows = custody["identities"]
    require(type(rows) is list and 1 <= len(rows) <= 128, "external_custody_identities")
    identities = [external_identity(row, "custody") for row in rows]
    require(len(set(identities)) == len(identities) and cli in identities
            and all(row[0] != observer[0] for row in identities), "external_custody_ownership")
    # Keep the internal receipt checks below; require its owned identities too.
    require(type(manifest) is dict and type(manifest.get("acquisition_cleanup")) is dict
            and manifest["acquisition_cleanup"].get("file") == "acquisition-supervision.json", "external_cleanup_binding")
    supervision = external_json(external_read(root, "acquisition-supervision.json", 128 * 1024, seen, manifest["acquisition_cleanup"]))
    owned = supervision.get("cleanup", {}).get("identities")
    require(type(owned) is list and 1 <= len(owned) <= 128, "external_internal_identities")
    for row in owned:
        require(type(row) is list and len(row) == 3, "external_internal_identity")
        ident = external_identity(dict(zip(("pid", "create_time", "executable"), row, strict=True)))
        require(ident in identities, "external_custody_incomplete")
    return manifest


def check_acquired(root, reviewed_sha):
    """Legacy SHA reviews acquisition.json; v3 SHA reviews external acceptance.json.

    The caller supplies an independently reviewed digest, never automatic approval.
    SHA binding alone does not authenticate the observer or its assertions.
    """
    root = Path(root)
    require(not (root / "acquisition-pending.json").exists()
            and not (root / "acquisition-supervision-failure.json").exists(), "acquisition_finalization_failed")
    companion = root.with_name(root.name + ".external-review")
    external = companion.exists() or companion.is_symlink()
    if external:
        lock = check_external_acceptance(root, reviewed_sha)
    else:
        # Preserve legacy digest semantics while bounding the pre-profile read.
        require(isinstance(reviewed_sha, str) and re.fullmatch("[0-9a-f]{64}", reviewed_sha), "review_digest_required")
        raw = external_read(external_root(root), "acquisition.json", 16 * 1024**2, set())
        require(digest(raw) == reviewed_sha, "review_digest_mismatch")
        lock = external_json(raw)
    require(lock["status"] == "ACQUIRED_UNREVIEWED_DO_NOT_EXECUTE" and lock["engine_commit"] == COMMIT, "acquisition_contract")
    check_refs(root, [lock["acquisition_cleanup"]])
    supervision = load(root / lock["acquisition_cleanup"]["file"])
    records = [lock, supervision]
    for name in ("acquisition-attempt.json", "raw-acquisition.json"):
        if (root / name).exists():
            records.append(load(root / name))
    profiles = [row.get("acquisition_profile") for row in records]
    selected = (any("selection" in row for row in lock.get("tools", []))
                or (root / "worker-terminal.json").exists() or "worker_terminal" in lock
                or "worker_sampling" in lock or lock.get("schema_version", 1) == 2
                or any("worker_sampling" in row or row.get("schema_version", 1) == 2
                       or "--acquisition-profile" in row.get("argv", [])
                       or any("selection" in tool for tool in row.get("tools", [])) for row in records))
    if any(value is not None for value in profiles) or selected:
        require(external, "external_acceptance_missing")
        profile = profiles[0]
        require(profile in (ACQUISITION_PROFILE, ACQUISITION_PROFILE_1800)
                and all(value == profile for value in profiles), "acquisition_profile_binding")
        check_profile_records(root, lock, profile)
    else:
        require(not external, "external_profile_missing")
    cleanup = supervision["cleanup"]
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
        if lock.get("acquisition_profile") and row["directory"] == "tools/llvm":
            require(row["archive_sha256"] == LLVM_SHA, "llvm_archive_pin")
            with zipfile.ZipFile(root / "archives" / row["name"]) as archive:
                infos, selection = llvm_selection(archive.infolist(), root / row["directory"])
            require(row.get("selection") == selection, "llvm_selection_changed")
            require({(r["file"], r["size_bytes"]) for r in row["inventory"]}
                    == {(i.filename, i.file_size) for i in infos if not i.is_dir()}, "llvm_selection_inventory")
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
    parser.add_argument("--reviewed-acquisition-sha256", help="Externally reviewed artifact SHA256: legacy acquisition.json; v3 sibling external-review/acceptance.json. Supply only after independent CLI-terminal and custody review; hashes do not authenticate self-asserted observations.")
    parser.add_argument("--acquisition-profile", choices=[ACQUISITION_PROFILE, ACQUISITION_PROFILE_1800])
    args = parser.parse_args()
    require(args.acquisition_profile is None or args.operation in {"acquire", "_acquire-worker"}, "acquisition_profile_operation")
    if args.operation == "inspect":
        print(json.dumps({"pins": pins(), "executable_ready": False}))
    else:
        require(args.workspace is not None, "workspace_required")
        if args.operation == "_acquire-worker":
            require(args.worker_token is not None, "worker_token_required")
            result = acquire(args.workspace, worker_token=args.worker_token, acquisition_profile=args.acquisition_profile)
        elif args.operation == "acquire":
            result = acquire_supervised(args.workspace, acquisition_profile=args.acquisition_profile)
        else:
            result = build(args.workspace, args.reviewed_acquisition_sha256)
        print(json.dumps({"status": result["status"]}))


if __name__ == "__main__":
    try:
        main()
    except (BoundaryError, OSError, ValueError) as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        raise SystemExit(1) from error
