"""Synthetic boundaries only. No network, compiler, native engine, host sampling or helper processes."""
import io
import json
import stat
import struct
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import prepare_summary_grammar_engine as prep
from scripts import verify_summary_grammar_engine as verify
from tools.summary_grammar import runtime as rt

# Public pinned CMake 3.31.8 Windows-GNU.cmake lines 55-64; source data only.
WINDOWS_GNU_EXCERPT_55_TO_64 = (
    '',
    'set(CMAKE_GNULD_IMAGE_VERSION',
    '  "-Wl,--major-image-version,<TARGET_VERSION_MAJOR>,--minor-image-version,<TARGET_VERSION_MINOR>")',
    '',
    '# Check if GNU ld is too old to support @FILE syntax.',
    'set(__WINDOWS_GNU_LD_RESPONSE 1)',
    'execute_process(COMMAND ld -v OUTPUT_VARIABLE _help ERROR_VARIABLE _help)',
    'if("${_help}" MATCHES "GNU ld .* 2\\\\.1[1-6]")',
    '  set(__WINDOWS_GNU_LD_RESPONSE 0)',
    'endif()',
)
SYNTHETIC_WINDOWS_GNU = "# synthetic prefix\n" * 54 + "\n".join(WINDOWS_GNU_EXCERPT_55_TO_64) + "\n"


def test_public_bundle_preserves_all106_and_prebound_prefix10():
    native, rejected = rt.bundle()
    corpus = rt.load(rt.BUNDLE / "corpus.json")
    assert len(corpus) == 106 and len(native) == 105 and rejected == ["raw-surrogate"]
    assert rt.digest((rt.BUNDLE / "candidate.gbnf").read_bytes()) == rt.GRAMMAR_SHA
    assert rt.digest((rt.BUNDLE / "corpus.json").read_bytes()) == rt.CORPUS_SHA
    assert sum(bool(x["suffix"]) for x in native) == 10
    for row in native:
        original = next(r for r in corpus if r["id"] == row["id"])
        assert row["raw"] == original["raw"].encode("utf-8", "strict")
    raw = next(x for x in corpus if x["id"] == "raw-surrogate")["raw"]
    with pytest.raises(UnicodeEncodeError):
        raw.encode("utf-8", "strict")
    assert next(x for x in native if x["id"] == "surrogate-high")["raw"].find(b"\\uD800") >= 0
    assert next(x for x in native if x["id"] == "pair-upper")["raw"].find(b"\\uD83D\\uDE00") >= 0


def test_batch_is_lossless_binary_not_json_reserialization():
    rows, _ = rt.bundle()
    data = verify.encode_batch(rows)
    assert data[:4] == b"SGE1" and struct.unpack_from("<I", data, 4)[0] == 105
    offset = 8
    for row in rows:
        expected = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        assert expected == {"dead": 0, "prefix": 1, "complete": 2}[row["expected"]]
        for field in ("raw", "suffix"):
            size = struct.unpack_from("<I", data, offset)[0]
            offset += 4
            assert data[offset:offset + size] == row[field]
            offset += size
    assert offset == len(data)


@pytest.mark.parametrize("name", ["../x", "/x", "a/../../x", "C:/x", "a\\x", "a//x", "a/./x", "x:stream", "CON", "nul.txt", "COM1.txt", "x.", "x "])
def test_path_escape_and_windows_alias_rejected(tmp_path, name):
    with pytest.raises(rt.BoundaryError):
        rt.safe_path(tmp_path, name)


def test_reparse_and_reference_change_are_rejected(tmp_path, monkeypatch):
    p = tmp_path / "x"
    p.write_bytes(b"old")
    ref = rt.reference(p, tmp_path)
    p.write_bytes(b"new")
    with pytest.raises(rt.BoundaryError, match="reference_changed"):
        rt.check_refs(tmp_path, [ref])
    original = Path.lstat
    def reparse(path):
        value = original(path)
        if path == p:
            return SimpleNamespace(st_mode=value.st_mode, st_file_attributes=1024)
        return value
    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(rt.BoundaryError, match="reparse"):
        rt.safe_path(tmp_path, "x")


class FakeBudget(prep.Budget):
    def __init__(self, root):
        super().__init__(root, ps=FakePS(root), clock=lambda: 0)
    def check(self, incoming=0):
        result = super().check(incoming)
        rt.require(self.downloaded <= rt.DOWNLOAD, "preparation_budget")
        return result


def test_archive_roundtrip_and_disk_bound(tmp_path, monkeypatch):
    archive = tmp_path / "good.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("dir/file.txt", b"x\r\ny")
    prep.extract_zip(archive, tmp_path / "expanded", FakeBudget(tmp_path))
    assert (tmp_path / "expanded/dir/file.txt").read_bytes() == b"x\r\ny"
    budget = FakeBudget(tmp_path)
    monkeypatch.setattr(prep, "DISK", budget.total + 1)
    with pytest.raises(rt.BoundaryError, match="archive_expanded_budget"):
        prep.extract_zip(archive, tmp_path / "oversize", budget)


@pytest.mark.parametrize("fault", ["escape", "symlink", "duplicate", "case-alias", "device"])
def test_archive_unsafe_members_fail_closed(tmp_path, fault):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        if fault == "symlink":
            info = zipfile.ZipInfo("link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, "elsewhere")
        elif fault in ("duplicate", "case-alias"):
            z.writestr("one", "x")
            z.writestr("one" if fault == "duplicate" else "ONE", "y")
        else:
            z.writestr("../escape" if fault == "escape" else "NUL.txt", "x")
    with pytest.raises(rt.BoundaryError):
        prep.extract_zip(archive, tmp_path / "new", FakeBudget(tmp_path))
    assert not (tmp_path.parent / "escape").exists()


class Response(io.BytesIO):
    status = 200
    def geturl(self):
        return "https://raw.githubusercontent.com/example/source"


@pytest.mark.parametrize("fault", [None, "hash", "bytecap", "redirect", "totalcap"])
def test_download_mocked_stream_budget_hash_and_partial_preservation(tmp_path, monkeypatch, fault):
    body = b"payload"
    response = Response(body)
    if fault == "redirect":
        response.geturl = lambda: "https://untrusted.invalid/file"
    budget = FakeBudget(tmp_path)
    if fault == "totalcap":
        monkeypatch.setattr(rt, "DOWNLOAD", 3)
    opener = SimpleNamespace(open=lambda *a, **k: response)
    path = tmp_path / "partial"
    kwargs = {"expected": "0" * 64 if fault == "hash" else rt.digest(body), "max_bytes": 2 if fault == "bytecap" else 100}
    if fault:
        with pytest.raises(rt.BoundaryError):
            prep.fetch("https://raw.githubusercontent.com/example/source", path, budget, opener=opener, **kwargs)
    else:
        assert prep.fetch("https://raw.githubusercontent.com/example/source", path, budget, opener=opener, **kwargs) == rt.digest(body)
        assert path.read_bytes() == body and budget.downloaded == len(body)
    if fault == "hash":
        assert path.read_bytes() == body  # failure evidence is retained, not repaired


@pytest.mark.parametrize("url", ["http://github.com/x", "https://evil.test/x", "https://user@github.com/x", "https://github.com:444/x"])
def test_no_arbitrary_download_origin(url):
    with pytest.raises(rt.BoundaryError):
        prep.checked_url(url)


def test_ninja_unknown_pin_is_not_an_executable_lock(tmp_path, monkeypatch):
    assert rt.pins()["status"] == "ACQUISITION_ONLY_NOT_EXECUTABLE"
    ninja = next(x for x in rt.pins()["tools"] if x["name"] == "ninja-win.zip")
    assert ninja["published_sha256"] is None
    monkeypatch.setattr(prep, "run_owned", lambda *a, **k: pytest.fail("must not execute"))
    for value in (None, "", "0" * 64):
        with pytest.raises((rt.BoundaryError, FileNotFoundError)):
            prep.check_acquired(tmp_path, value)


@pytest.mark.parametrize("fault", ["git", "download", "fetch", "run", "unknownexe", "empty"])
def test_configure_trace_rejects_git_network_or_unapproved_execution(tmp_path, fault):
    path = tmp_path / "trace.jsonl"
    exe = tmp_path / "cmake.exe"
    row = {"cmd": "execute_process", "args": ["COMMAND", str(exe), "--version"]}
    if fault == "git":
        row["args"] = ["COMMAND", "git", "rev-parse", "HEAD"]
    elif fault == "download":
        row = {"cmd": "file", "args": ["DOWNLOAD", "https://example.com"]}
    elif fault == "fetch":
        row = {"cmd": "FetchContent_MakeAvailable", "args": ["x"]}
    elif fault == "run":
        row = {"cmd": "try_run", "args": []}
    elif fault == "unknownexe":
        row["args"] = ["COMMAND", "unknown.exe"]
    path.write_text((json.dumps(row) + "\n") if fault != "empty" else "")
    with pytest.raises(rt.BoundaryError):
        prep.audit_trace(path, [exe])


def test_configure_trace_allows_only_explicit_tools_and_disables_git_in_cmake(tmp_path):
    exe = tmp_path / "cmake.exe"
    trace = tmp_path / "trace"
    trace.write_text(json.dumps({"cmd": "execute_process", "args": ["COMMAND", str(exe), "--version"]}) + "\n")
    assert prep.audit_trace(trace, [exe]) == 1
    cmake = (rt.BUNDLE / "CMakeLists.txt").read_text()
    for marker in ('CMAKE_DISABLE_FIND_PACKAGE_Git TRUE', 'GIT_EXECUTABLE ""', 'GIT_EXE ""', 'EXCLUDE_FROM_ALL', 'GGML_NATIVE', 'LLAMA_OPENSSL', 'LLAMA_BUILD_TESTS'):
        assert marker in cmake
    assert "ctest" not in cmake


def good_protocol(rows):
    result = [{"init_ms": 1, "rules": 1452}]
    result.extend({"case": i, "state": r["expected"], "witness": "complete" if r["suffix"] else None, "clone_ms": 0.1, "elapsed_ms": 0.2} for i, r in enumerate(rows))
    result.append({"done": len(rows), "clone_total_ms": 10.5, "longest_ms": 0.2, "total_ms": 30})
    return result


@pytest.mark.parametrize("fault", [None, "missing", "order", "unexpected-prefix", "wrong-witness", "rules", "nan", "duplicate-key", "partial"])
def test_engine_protocol_cannot_turn_prefix_missing_or_zero_exit_into_pass(fault):
    rows, _ = rt.bundle()
    result = good_protocol(rows)
    if fault == "missing": result.pop(2)
    elif fault == "order": result[1]["case"] = 99
    elif fault == "unexpected-prefix": result[1]["state"] = "prefix"
    elif fault == "wrong-witness": next(r for r in result if r.get("witness") == "complete")["witness"] = "prefix"
    elif fault == "rules": result[0]["rules"] = 20001
    elif fault == "nan": result[0]["init_ms"] = float("nan")
    data = ("\n".join(json.dumps(x) for x in result) + "\n").encode()
    if fault == "duplicate-key": data = data.replace(b'"rules": 1452', b'"rules": 0, "rules": 1452', 1)
    if fault == "partial": data = data[:-1]
    if fault:
        with pytest.raises(rt.BoundaryError): verify.protocol(data, rows)
    else:
        assert len(verify.protocol(data, rows)["cases"]) == 105


class Clock:
    now = 0
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += seconds


class FakePS:
    class NoSuchProcess(Exception): pass
    class AccessDenied(Exception): pass
    def __init__(self, root, fault=None):
        self.root, self.fault, self.killed = root, fault, []
        self.alive = {10: True, 20: True}
        self.reused = False
        self.memory_samples = 0
    def virtual_memory(self):
        self.memory_samples += 1
        return SimpleNamespace(available=0 if self.fault == "start" or (self.fault == "host" and self.memory_samples > 1) else 10 * 1024**3)
    def Process(self, pid=10):
        if self.fault == "capture" and pid == 10:
            raise self.AccessDenied()
        if not self.alive[pid]: raise self.NoSuchProcess()
        ps = self
        class Process:
            def __init__(self): self.pid = pid
            def create_time(self): return 2 if ps.reused else 1
            def exe(self): return str(ps.root / ("root.exe" if pid == 10 else "bad.exe" if ps.fault == "unexpected" else "child.exe"))
            def children(self, recursive=True): return [ps.Process(20)] if pid == 10 and ps.alive[20] else []
            def memory_info(self):
                if ps.fault == "observation": raise ps.AccessDenied()
                return SimpleNamespace(rss=300 if ps.fault == "rss" else 1)
            def kill(self):
                if ps.fault == "cleanup-denied": raise ps.AccessDenied()
                ps.killed.append(pid); ps.alive[pid] = False
        return Process()


class FakePopen:
    pid = 10
    returncode = None
    def __init__(self, ps, clock):
        self.ps, self.clock, self.polls, self.handle_kills = ps, clock, 0, 0
        self.closed = False
        self._handle = SimpleNamespace(Close=lambda: setattr(self, "closed", True))
    def poll(self):
        self.polls += 1
        if self.ps.fault not in ("timeout", "capture", "cleanup-denied") and self.polls >= 2:
            self.ps.alive = {10: False, 20: False}; self.returncode = 0
        return self.returncode
    def wait(self, timeout):
        if self.ps.fault == "cleanup-denied": raise subprocess.TimeoutExpired("synthetic", timeout)
        self.returncode = 0; return 0
    def kill(self): self.handle_kills += 1; self.ps.alive[10] = False


@pytest.mark.parametrize("fault", [None, "start", "capture", "rss", "host", "observation", "unexpected", "timeout", "log", "cleanup-denied"])
def test_owned_tree_mocked_resource_failure_cleanup_and_no_unrelated_kill(tmp_path, fault):
    clock = Clock(); ps = FakePS(tmp_path, fault); process = FakePopen(ps, clock)
    def launch(*a, **k):
        if fault == "log":
            k["stdout"].write(b"x" * (8 * 1024**2 + 1)); k["stdout"].flush()
        return process
    kwargs = {"cwd": tmp_path, "env": rt.clean_environment([], tmp_path, "tmp"), "root": tmp_path, "log_prefix": tmp_path / "run", "deadline": 6,
                  "rss": 100, "host": 1, "start": 1, "allowed": [tmp_path / "root.exe", tmp_path / "child.exe"],
                  "ps": ps, "popen": launch, "clock": clock, "sleeper": clock.sleep}
    if fault:
        with pytest.raises((rt.BoundaryError, FakePS.AccessDenied)):
            rt.run_owned([tmp_path / "root.exe"], **kwargs)
        if fault == "capture":
            assert process.handle_kills == 1 and process.closed
            receipt = rt.load(tmp_path / "run.json")
            assert receipt["cleanup"]["descendant_absence_unverified"] and not receipt["cleanup"]["all_absent"]
        if fault == "cleanup-denied":
            receipt = rt.load(tmp_path / "run.json")
            assert not receipt["cleanup"]["all_absent"] and receipt["cleanup"]["errors"]
            assert not process.closed and ps.killed == [] and clock.now >= 5
    else:
        result = rt.run_owned([tmp_path / "root.exe"], **kwargs)
        assert result["cleanup"]["all_absent"] and process.closed
        assert result["cleanup"]["sample_count"] >= 1 and result["cleanup"]["sampled_peak_rss"] == 2
        assert result["cleanup"]["sampled_minimum_host_available"] == 10 * 1024**3
        assert result["within_shared_deadline"] and result["elapsed_seconds"] < 6
    assert set(ps.killed) <= {10, 20}


def test_identity_reuse_is_never_killed(tmp_path):
    clock = Clock(); ps = FakePS(tmp_path); process = FakePopen(ps, clock)
    tree = rt.OwnedTree(process, [tmp_path / "root.exe", tmp_path / "child.exe"], ps, clock)
    tree.capture(ps.Process(10)); ps.reused = True
    result = tree.cleanup(5)
    assert result["errors"] and ps.killed == []


def test_preparation_resource_budget_is_mocked_and_cumulative(tmp_path):
    clock = Clock(); ps = FakePS(tmp_path)
    budget = prep.Budget(tmp_path, ps=ps, clock=clock)
    budget.check(rt.DOWNLOAD)
    with pytest.raises(rt.BoundaryError, match="preparation_budget"): budget.check(1)
    budget = prep.Budget(tmp_path, ps=ps, clock=clock)
    clock.now = 600
    with pytest.raises(rt.BoundaryError, match="preparation_budget"): budget.check()


def test_frozen_parser_expectations_stay_distinct_from_grammar():
    expected = rt.load(rt.BUNDLE / "expected.json")
    abstain = next(x for x in expected if x["id"] == "abstain")
    assert abstain["expected_state"] == "complete" and not abstain["expected_frozen_parser_accept"]
    assert any(r["expected_state"] == "dead" and r["expected_frozen_parser_accept"] for r in expected)


def test_no_private_runtime_dependency_or_model_calls():
    for path in [rt.BUNDLE / "runtime.py", rt.BUNDLE / "harness.cpp", Path(prep.__file__), Path(verify.__file__)]:
        text = path.read_text(encoding="utf-8-sig")
        assert ".local/" not in text and "git show" not in text and "C:\\Users" not in text
    harness = (rt.BUNDLE / "harness.cpp").read_text()
    for api in ("llama_grammar_init_impl(nullptr", "llama_grammar_clone_impl", "llama_grammar_free_impl", "llama_grammar_get_stacks", "unicode_cpts_from_utf8"):
        assert api in harness
    for prohibited in ("llama_model_load", "llama_tokenize", "llama_sampler", "llama_backend_init"):
        assert prohibited not in harness


@pytest.mark.parametrize("fault", [None, "wrong-verdict"])
def test_full_verifier_mocked_single_batch_shared_budget_and_preserved_failure(tmp_path, monkeypatch, fault):
    rows, _ = rt.bundle()
    exe = tmp_path / "validator.exe"; exe.write_bytes(b"synthetic-not-executable")
    trace = tmp_path / "trace"; trace.write_bytes(b"synthetic")
    previous = tmp_path / "previous.json"
    rt.write(previous, {"cleanup": {"all_absent": True, "errors": [], "identities": []}})
    manifest = {"status": "BUILT_UNREVIEWED_NOT_ENGINE_VALIDATED", "acquisition_sha256": "0" * 64,
                "executable": rt.reference(exe, tmp_path), "configure_trace": rt.reference(trace, tmp_path),
                "build_logs": [], "cleanup_receipts": [rt.reference(previous, tmp_path)]}
    rt.write(tmp_path / "build-manifest.json", manifest)
    reviewed_sha = rt.digest((tmp_path / "build-manifest.json").read_bytes())
    monkeypatch.setattr(verify, "check_acquired", lambda *a: {})
    calls = []
    def runner(argv, **kwargs):
        calls.append(argv)
        assert kwargs["deadline"] == 60 and kwargs["rss"] == 512 * 1024**2
        assert kwargs["start"] == 2684354560 and kwargs["host"] == 2147483648
        assert (tmp_path / "native-issued.json").exists()  # fixed before mock output
        assert rt.validate_temporary(tmp_path, kwargs["env"]) == tmp_path / "engine-check/tmp"
        output = good_protocol(rows)
        if fault: output[1]["state"] = "prefix"
        Path(str(kwargs["log_prefix"]) + ".stdout").write_bytes(("\n".join(json.dumps(r) for r in output) + "\n").encode())
        return {"cleanup": {"all_absent": True, "errors": []}}
    if fault:
        with pytest.raises(rt.BoundaryError, match="verdict_mismatch"):
            verify.verify(tmp_path, reviewed_sha, runner=runner, ps=FakePS(tmp_path), clock=lambda: 0)
        assert (tmp_path / "engine-check/failure.json").exists()
        assert (tmp_path / "engine-check/engine.stdout").exists()
    else:
        result = verify.verify(tmp_path, reviewed_sha, runner=runner, ps=FakePS(tmp_path), clock=lambda: 0)
        assert result["native_cases"] == 105 and result["carrier_rejections"] == ["raw-surrogate"]
        assert not result["semantics_verified"]
    with pytest.raises(rt.BoundaryError, match="native_once"):
        verify.verify(tmp_path, reviewed_sha, result_name="another", runner=runner, ps=FakePS(tmp_path), clock=lambda: 0)
    assert len(calls) == 1


def test_build_mocked_only_target2_jobs_and_shared900_seconds(tmp_path, monkeypatch):
    monkeypatch.delenv("SystemRoot", raising=False)
    tools = []
    for name, executables in [("cmake", ["cmake.exe"]), ("ninja", ["ninja.exe"]), ("llvm", ["bin/clang.exe", "bin/clang++.exe", "bin/clang-20.exe", "lib/clang/20/include/synthetic.h"])]:
        folder = tmp_path / "tools" / name; folder.mkdir(parents=True)
        for exe in executables:
            (folder / exe).parent.mkdir(parents=True, exist_ok=True)
            (folder / exe).write_bytes(b"not-executable")
        if name == "cmake":
            module = folder / "share/cmake-3.31/Modules/Platform/Windows-GNU.cmake"
            module.parent.mkdir(parents=True)
            module.write_text(SYNTHETIC_WINDOWS_GNU)
        tools.append({"directory": "tools/" + name, "inventory": rt.inventory(folder)})
    lock = {"tools": tools, "bundle": []}
    lock["runtime_bindings"] = prep.runtime_bindings(tmp_path, lock)
    monkeypatch.setattr(prep, "check_acquired", lambda *a: lock)
    calls = []
    def runner(argv, **kwargs):
        calls.append([str(x) for x in argv])
        assert kwargs["deadline"] == 900 and kwargs["rss"] == 2 * 1024**3
        assert tmp_path / "tools/llvm/bin/clang-20.exe" in kwargs["allowed"]
        assert rt.validate_temporary(tmp_path, kwargs["env"]) == tmp_path / "build-tmp"
        prefix = kwargs["log_prefix"]
        for extension in (".stdout", ".stderr"): Path(str(prefix) + extension).write_bytes(b"")
        rt.write(Path(str(prefix) + ".json"), {"cleanup": {"all_absent": True, "errors": [], "identities": []}})
        if len(calls) == 1:
            rtpath = tmp_path / "configure-trace.jsonl"
            rtpath.write_text(json.dumps({"cmd": "execute_process", "args": ["COMMAND", str(argv[0]), "--version"]}) + "\n")
        else:
            binary = tmp_path / "build/bin"; binary.mkdir(parents=True)
            (binary / "summary-grammar-validator.exe").write_bytes(b"not-executable")
        return {}
    result = prep.build(tmp_path, "a" * 64, runner=runner, clock=lambda: 0)
    assert result["status"] == "BUILT_UNREVIEWED_NOT_ENGINE_VALIDATED" and result["native_batch_runs"] == 0
    assert calls[1][-4:] == ["--target", "summary-grammar-validator", "--parallel", "2"]
    with pytest.raises(rt.BoundaryError, match="build_once"):
        prep.build(tmp_path, "a" * 64, runner=runner, clock=lambda: 0)
    assert len(calls) == 2


@pytest.mark.parametrize("source_transport", ["injected", "owned"])
@pytest.mark.parametrize("mode", ["100644", "100755"])
@pytest.mark.parametrize("bad_blob", [False, True])
def test_full_acquisition_mocked_tree_blobs_archives_unknown_ninja_and_no_execution(tmp_path, monkeypatch, bad_blob, mode, source_transport):
    import hashlib
    root = tmp_path / "owned"
    urls, toolpins = {}, []
    for name, exe in [("llvm-synthetic.zip", "bin/clang.exe"), ("cmake-synthetic.zip", "cmake.exe"), ("ninja-win.zip", "ninja.exe")]:
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as z:
            z.writestr(exe, b"not-executable")
            if name.startswith("llvm"):
                z.writestr("bin/clang++.exe", b"not-executable")
                z.writestr("bin/clang-20.exe", b"not-executable")
                z.writestr("lib/clang/20/include/synthetic.h", b"synthetic")
            if name.startswith("cmake"):
                z.writestr("share/cmake-3.31/Modules/Platform/Windows-GNU.cmake", SYNTHETIC_WINDOWS_GNU)
            if not name.startswith("ninja"): z.writestr("LICENSE", b"synthetic-license")
        url = "https://github.com/synthetic/" + name
        urls[url] = data.getvalue()
        toolpins.append({"name": name, "asset": url, "published_sha256": None if name.startswith("ninja") else rt.digest(data.getvalue())})
    monkeypatch.setattr(prep, "pins", lambda: {"tools": toolpins})
    tree = []
    for name in ["CMakeLists.txt", "LICENSE", "src/llama-grammar.h", "src/llama-grammar.cpp", "src/models/example.cpp", "ggml/src/ggml-cann/CMakeLists.txt"]:
        body = b"synthetic source " + name.encode()
        url = f"https://raw.githubusercontent.com/ggml-org/llama.cpp/{rt.COMMIT}/{name}"
        urls[url] = body
        blob = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
        tree.append({"path": name, "type": "blob", "mode": mode, "size": len(body), "sha": "0" * 40 if bad_blob and name == "LICENSE" else blob})
    api = "https://api.github.com/repos/ggml-org/llama.cpp/git/"
    urls[api + "commits/" + rt.COMMIT] = json.dumps({"sha": rt.COMMIT, "tree": {"sha": "a" * 40}}).encode()
    urls[api + "trees/" + "a" * 40 + "?recursive=1"] = json.dumps({"sha": "a" * 40, "truncated": False, "tree": tree}).encode()
    urls["https://raw.githubusercontent.com/ninja-build/ninja/v1.12.1/COPYING"] = b"synthetic ninja license"
    calls = []
    ordinary_requests = []
    def ordinary_open(request, **kwargs):
        ordinary_requests.append(request.full_url)
        return Response(urls[request.full_url])
    opener = SimpleNamespace(open=ordinary_open)
    source_urls = [f"https://raw.githubusercontent.com/ggml-org/llama.cpp/{rt.COMMIT}/{row['path']}" for row in tree]
    connections, requests, _ = source_https_connections(monkeypatch, [source_http_wire(urls[url]) for url in source_urls])
    if source_transport == "owned":
        monkeypatch.setattr(prep.urllib.request, "build_opener", lambda *args: opener)
    def runner(argv, **kwargs):
        calls.append(argv)
        assert kwargs["deadline"] == 600 and kwargs["rss"] == 2147483648
        assert rt.validate_temporary(root, kwargs["env"]) == root / "acquisition-tmp"
        token = argv[-1]
        monkeypatch.setenv("DOCTRAIL_ACQUIRE_TOKEN", token)
        prep.acquire(root, opener=opener if source_transport == "injected" else None, budget_factory=FakeBudget, worker_token=token)
        rt.write(root / "acquisition-supervision.json", {"cleanup": {"all_absent": True, "errors": [], "identities": []}})
    if bad_blob:
        with pytest.raises(rt.BoundaryError, match="source_blob"):
            prep.acquire_supervised(root, runner=runner, clock=lambda: 0)
        assert (root / "source/LICENSE").is_file()
        assert (root / "acquisition-failure.json").is_file() and not (root / "acquisition.json").exists()
    else:
        result = prep.acquire_supervised(root, runner=runner, clock=lambda: 0)
        assert result["status"] == "ACQUIRED_UNREVIEWED_DO_NOT_EXECUTE"
        ninja = next(x for x in result["tools"] if x["name"] == "ninja-win.zip")
        assert ninja["publisher_sha256"] is None and len(ninja["archive_sha256"]) == 64
        assert result["compiler_native_execution"] == 0 and len(result["source"]) == 6
        observed_path = "ggml/src/ggml-cann/CMakeLists.txt"
        assert (root / "source" / observed_path).read_bytes() == b"synthetic source " + observed_path.encode()
        assert {row["file"] for row in result["source"]} == {row["path"] for row in tree}
        reviewed = rt.digest((root / "acquisition.json").read_bytes())
        assert prep.check_acquired(root, reviewed)["runtime_bindings"] == result["runtime_bindings"]
        with pytest.raises(rt.BoundaryError, match="review_digest_mismatch"):
            prep.check_acquired(root, "0" * 64)
        result["runtime_bindings"]["wrapper_driver_edges"][0]["driver"]["sha256"] = "0" * 64
        (root / "acquisition.json").write_text(json.dumps(result))
        with pytest.raises(rt.BoundaryError, match="runtime_bindings_changed"):
            prep.check_acquired(root, rt.digest((root / "acquisition.json").read_bytes()))
    assert len(calls) == 1
    if source_transport == "owned":
        assert len(connections) == 1 and connections[0].closed
        assert len(requests) == (2 if bad_blob else 6)
        assert all(url not in source_urls for url in ordinary_requests)
    else:
        assert not connections and not requests
    with pytest.raises(FileExistsError): prep.acquire_supervised(root, runner=runner, clock=lambda: 0)


@pytest.mark.parametrize("path", ["models/weights.gguf", "src/models/weights.gguf", "src/tokenizer.vocab", "vendor/file.bin", "ggml/.git/config"])
def test_source_payloads_never_become_engine_sources(path):
    with pytest.raises(rt.BoundaryError): prep.selected_source(path)


def test_engine_model_architecture_cpp_is_code_not_model_payload():
    assert prep.selected_source("src/models/example.cpp")



def synthetic_binding_tree(root):
    tools = []
    for name, files in [("llvm", ["bin/clang.exe", "bin/clang++.exe", "bin/clang-20.exe", "lib/clang/20/include/x.h"]),
                        ("cmake", ["bin/cmake.exe", "share/cmake-3.31/Modules/Platform/Windows-GNU.cmake"])]:
        folder = root / "tools" / name
        for file in files:
            path = folder / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((SYNTHETIC_WINDOWS_GNU).encode() if file.endswith(".cmake") else b"not-executable")
        tools.append({"directory": "tools/" + name, "inventory": rt.inventory(folder)})
    lock = {"tools": tools}
    lock["runtime_bindings"] = prep.runtime_bindings(root, lock)
    return lock


@pytest.mark.parametrize("fault", [None, "unknown-child", "driver-bytes", "wrapper-bytes", "missing", "multiple", "resource-major"])
def test_review_bound_versioned_driver_only_not_a_runtime_pattern(tmp_path, fault):
    lock = synthetic_binding_tree(tmp_path)
    binding = lock["runtime_bindings"]
    driver = tmp_path / binding["wrapper_driver_edges"][0]["driver"]["file"]
    if fault == "driver-bytes": driver.write_bytes(b"changed")
    if fault == "wrapper-bytes": (tmp_path / "tools/llvm/bin/clang.exe").write_bytes(b"changed")
    if fault in {"missing", "multiple", "resource-major"}:
        rows = lock["tools"][0]["inventory"]
        if fault == "missing": rows[:] = [x for x in rows if "clang-20.exe" not in x["file"]]
        elif fault == "multiple": rows.append({"file": "bin/clang-21.exe"})
        else: rows[:] = [x for x in rows if "/20/" not in x["file"]]
    if fault not in {None, "unknown-child"}:
        with pytest.raises(rt.BoundaryError): prep.runtime_bindings(tmp_path, lock)
        return
    assert prep.runtime_bindings(tmp_path, lock) == binding
    assert "not_runtime_version_observation" in binding["basis"]
    allowed = [tmp_path / edge[k]["file"] for edge in binding["wrapper_driver_edges"] for k in ("wrapper", "driver")]
    process = SimpleNamespace(pid=7, create_time=lambda: 123, exe=lambda: str(driver if fault is None else driver.with_name("clang-21.exe")))
    tree = rt.OwnedTree(None, allowed, None, lambda: 0)
    if fault:
        with pytest.raises(rt.BoundaryError, match="unexpected_child"): tree.capture(process)
    else:
        tree.capture(process)
        assert next(iter(tree.seen))[0:2] == (7, 123)


@pytest.mark.parametrize("fault", [None, "args", "relative-module", "other-module", "line", "module-hash", "relative-command", "git", "download", "try_run"])
def test_exact_optional_ld_trace_requires_reviewed_module_position_and_args(tmp_path, fault):
    lock = synthetic_binding_tree(tmp_path)
    binding = lock["runtime_bindings"]["optional_ld_query"]
    module = tmp_path / binding["module"]["file"]
    env = rt.clean_environment([tmp_path / "tools/llvm/bin"], tmp_path, "tmp")
    env.pop("SystemRoot", None)  # no machine paths in this synthetic test
    guard = prep.optional_probe_guard(tmp_path, binding, env, tmp_path / "tools/cmake/bin")
    row = {"cmd": "execute_process", "args": list(prep.LD_ARGS), "file": str(module), "line": 61}
    if fault == "args": row["args"][2] = "--version"
    elif fault == "relative-module": row["file"] = binding["module"]["file"]
    elif fault == "other-module": row["file"] = str(tmp_path / "other.cmake")
    elif fault == "line": row["line"] = 55
    elif fault == "module-hash": module.write_bytes(b"changed")
    elif fault == "relative-command": row["args"][1] = "cmake.exe"
    elif fault == "git": row["args"] = ["COMMAND", "git", "--version"]
    elif fault == "download": row.update(cmd="file", args=["DOWNLOAD", "https://example.com"])
    elif fault == "try_run": row["cmd"] = "try_run"
    trace = tmp_path / "trace"
    trace.write_text(json.dumps(row) + "\n")
    if fault:
        with pytest.raises(rt.BoundaryError): prep.audit_trace(trace, [tmp_path / "tools/cmake/bin/cmake.exe"], guard, tmp_path)
    else:
        assert prep.audit_trace(trace, [], guard, tmp_path) == 1
        assert "not_an_execution_result" in guard["scope"]
        tree = rt.OwnedTree(None, [], None, lambda: 0)
        with pytest.raises(rt.BoundaryError, match="unexpected_child"):
            tree.capture(SimpleNamespace(pid=8, create_time=lambda: 1, exe=lambda: str(tmp_path / "ld.exe")))


@pytest.mark.parametrize("where", ["application", "cwd", "path", "system", "permission"])
def test_optional_ld_present_or_unobservable_never_permitted(tmp_path, monkeypatch, where):
    binding = synthetic_binding_tree(tmp_path)["runtime_bindings"]["optional_ld_query"]
    dirs = {key: tmp_path / key for key in ("application", "path", "system")}
    for path in dirs.values(): path.mkdir()
    dirs["cwd"] = tmp_path
    env = {"PATH": str(dirs["path"]), "SystemRoot": str(dirs["system"])}
    if where == "permission":
        original = Path.lstat
        def denied(path):
            if path.name == "ld.exe": raise PermissionError("mocked")
            return original(path)
        monkeypatch.setattr(Path, "lstat", denied)
    else: (dirs[where] / "ld.exe").write_bytes(b"unapproved")
    with pytest.raises((rt.BoundaryError, PermissionError)):
        prep.optional_probe_guard(tmp_path, binding, env, dirs["application"])


def test_owned_temp_rejects_hostile_inheritance_and_counts_retained_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMP", str(tmp_path.parent / "shared-hostile"))
    monkeypatch.setenv("TMP", str(tmp_path.parent / "another-shared"))
    before = dict(rt.os.environ)
    env = rt.clean_environment([], tmp_path, "phase-tmp")
    temp = rt.validate_temporary(tmp_path, env)
    assert temp == tmp_path / "phase-tmp" and dict(rt.os.environ) == before
    (temp / "response.rsp").write_bytes(b"retained on failure")
    assert rt.disk_bytes(tmp_path) == 19
    assert rt.inventory(tmp_path)[0]["file"] == "phase-tmp/response.rsp"
    monkeypatch.setattr(rt, "DISK", 18)
    with pytest.raises(rt.BoundaryError, match="disk_budget"): rt.disk_bytes(tmp_path)
    assert (temp / "response.rsp").read_bytes() == b"retained on failure"


@pytest.mark.parametrize("fault", ["external", "different", "missing", "reparse", "reuse", "parent-reparse"])
def test_temp_scope_fails_closed_before_any_process(tmp_path, monkeypatch, fault):
    env = rt.clean_environment([], tmp_path, "phase-tmp")
    temp = tmp_path / "phase-tmp"
    if fault == "external": env.update(TEMP=str(tmp_path.parent), TMP=str(tmp_path.parent))
    elif fault == "different": env["TMP"] += "other"
    elif fault == "missing": env.update(TEMP=str(tmp_path / "missing"), TMP=str(tmp_path / "missing"))
    elif fault in {"reparse", "parent-reparse"}:
        original = Path.lstat
        def reparse(path):
            value = original(path)
            if path == (temp if fault == "reparse" else tmp_path):
                return SimpleNamespace(st_mode=value.st_mode, st_file_attributes=1024)
            return value
        monkeypatch.setattr(Path, "lstat", reparse)
    if fault == "reuse":
        with pytest.raises(FileExistsError): rt.clean_environment([], tmp_path, "phase-tmp")
    else:
        with pytest.raises(rt.BoundaryError): rt.validate_temporary(tmp_path, env)


@pytest.mark.parametrize("missing", [False, True])
def test_metadata_safe_path_one_nonfollow_read_per_component_without_cache(tmp_path, monkeypatch, missing):
    target = tmp_path / "nested" / "leaf"
    calls, resolves = [], []
    def snapshot(path):
        calls.append(path)
        if missing and path == target: raise FileNotFoundError("not created yet")
        return SimpleNamespace(st_mode=stat.S_IFREG if path == target else stat.S_IFDIR)
    def forbidden(*args, **kwargs): raise AssertionError("redundant metadata lookup")
    def resolve(path):
        resolves.append(path)
        return path
    monkeypatch.setattr(Path, "lstat", snapshot)
    monkeypatch.setattr(Path, "exists", forbidden)
    monkeypatch.setattr(Path, "is_symlink", forbidden)
    monkeypatch.setattr(Path, "resolve", resolve)
    for _ in range(2): assert rt.safe_path(tmp_path, "nested/leaf") == target
    assert calls == [tmp_path, target.parent, target] * 2
    assert resolves == [target, tmp_path] * 2


@pytest.mark.parametrize("location", ["root", "ancestor", "leaf"])
@pytest.mark.parametrize("fault", ["symlink", "reparse", "permission", "io"])
def test_metadata_safe_path_rechecks_replaced_components_and_propagates_errors(tmp_path, monkeypatch, location, fault):
    target = tmp_path / "nested" / "leaf"
    changed = {"root": tmp_path, "ancestor": target.parent, "leaf": target}[location]
    replaced = False
    def snapshot(path):
        if replaced and path == changed:
            if fault == "permission": raise PermissionError("synthetic")
            if fault == "io": raise OSError("synthetic")
            return SimpleNamespace(st_mode=stat.S_IFLNK if fault == "symlink" else stat.S_IFDIR,
                                   st_file_attributes=1024 if fault == "reparse" else 0)
        return SimpleNamespace(st_mode=stat.S_IFREG if path == target else stat.S_IFDIR)
    monkeypatch.setattr(Path, "lstat", snapshot)
    monkeypatch.setattr(Path, "resolve", lambda path: path)
    assert rt.safe_path(tmp_path, "nested/leaf") == target
    replaced = True
    expected = PermissionError if fault == "permission" else OSError if fault == "io" else rt.BoundaryError
    with pytest.raises(expected): rt.safe_path(tmp_path, "nested/leaf")


@pytest.mark.parametrize("operation", ["disk", "scan", "log"])
def test_metadata_kind_and_size_share_one_nonfollow_read(tmp_path, monkeypatch, operation):
    leaf = tmp_path / "acquisition-supervision.stdout"
    leaf.write_bytes(b"abc")
    budget = FakeBudget(tmp_path)
    budget.logs = {leaf.name}
    snapshots, checked, safe_calls = [], [], []
    original_stat = Path.stat
    def snapshot(path, *, follow_symlinks=True):
        assert follow_symlinks is False
        snapshots.append(path)
        return original_stat(path, follow_symlinks=False)
    def safe(root, name):
        safe_calls.append(name)
        return root / name
    monkeypatch.setattr(Path, "stat", snapshot)
    monkeypatch.setattr(Path, "rglob", lambda path, pattern: iter([leaf]))
    monkeypatch.setattr(rt, "safe_path", safe)
    monkeypatch.setattr(prep, "safe_path", safe)
    monkeypatch.setattr(budget, "check", lambda: checked.append("check"))
    if operation == "disk":
        assert rt.disk_bytes(tmp_path, checked.append) == 3
        assert checked == ["start", "before_entry", "after_entry", "complete"]
    elif operation == "scan":
        assert budget.scan() == 3
        assert checked == ["check"] * 4
    else:
        budget.log_growth()
        assert budget.total == 3
    assert snapshots == [leaf] and safe_calls == [leaf.name]


@pytest.mark.parametrize("operation", ["disk", "scan", "log"])
@pytest.mark.parametrize("fault", ["permission", "io", "disappeared", "symlink", "reparse"])
def test_metadata_entry_replacement_or_loss_after_path_check_fails_closed(tmp_path, monkeypatch, operation, fault):
    leaf = tmp_path / "acquisition-supervision.stdout"
    leaf.write_bytes(b"abc")
    budget = FakeBudget(tmp_path)
    budget.logs = {leaf.name}
    original_safe, original_lstat = rt.safe_path, Path.lstat
    checked = False
    def safe(root, name):
        nonlocal checked
        result = original_safe(root, name)
        checked = True
        return result
    def changed(path):
        if checked and path == leaf:
            if fault == "permission": raise PermissionError("synthetic")
            if fault == "io": raise OSError("synthetic")
            if fault == "disappeared": raise FileNotFoundError("synthetic")
            return SimpleNamespace(st_mode=stat.S_IFLNK if fault == "symlink" else stat.S_IFREG,
                                   st_file_attributes=1024 if fault == "reparse" else 0, st_size=3)
        return original_lstat(path)
    monkeypatch.setattr(rt, "safe_path", safe)
    monkeypatch.setattr(prep, "safe_path", safe)
    monkeypatch.setattr(Path, "lstat", changed)
    monkeypatch.setattr(Path, "rglob", lambda path, pattern: iter([leaf]))
    monkeypatch.setattr(budget, "check", lambda: None)
    expected = (OSError, rt.BoundaryError)
    with pytest.raises(expected):
        if operation == "disk": rt.disk_bytes(tmp_path)
        elif operation == "scan": budget.scan()
        else: budget.log_growth()
    assert checked


def test_worker_many_chunk_writes_have_constant_full_scan_count(tmp_path):
    budget = FakeBudget(tmp_path)
    with budget.phase("sources"):
        for index in range(24):
            path = tmp_path / str(index)
            body = bytes([index]) * 131073
            prep.fetch("https://github.com/synthetic/" + str(index), path, budget,
                       opener=SimpleNamespace(open=lambda *a, body=body, **k: Response(body)))
            assert path.read_bytes() == body
    assert budget.scan_count == 3  # initial + stage start/end, independent of 72 body chunks
    assert budget.downloaded == 24 * 131073
    assert budget.scan() == rt.disk_bytes(tmp_path)
    assert budget.scan_count == 4
    events = [json.loads(line) for line in (tmp_path / "acquisition-phases.jsonl").read_text().splitlines()]
    assert [row["state"] for row in events] == ["start", "end"]
    assert events[-1]["scan_count"] == 3 and events[-1]["download_body_bytes"] == budget.downloaded


@pytest.mark.parametrize("extra", [0, 1])
def test_archive_declared_total_is_counted_once_at_exact_disk_boundary(tmp_path, monkeypatch, extra):
    archive = tmp_path / "archive.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("empty", b"")
        stream.writestr("first", b"a" * 70)
        stream.writestr("second", b"b" * 30)
    budget = FakeBudget(tmp_path)
    monkeypatch.setattr(prep, "DISK", archive.stat().st_size + 100 - extra)
    if extra:
        with pytest.raises(rt.BoundaryError, match="archive_expanded_budget"):
            prep.extract_zip(archive, tmp_path / "out", budget)
        assert (tmp_path / "out/first").read_bytes() == b"a" * 70
    else:
        prep.extract_zip(archive, tmp_path / "out", budget)
        assert budget.scan() == prep.DISK
        assert (tmp_path / "out/empty").read_bytes() == b""
        assert (tmp_path / "out/second").read_bytes() == b"b" * 30


@pytest.mark.parametrize("fault", ["unknown", "unknown-empty", "temporary", "modified", "removed", "same-total-different-file", "stat"])
def test_worker_phase_boundary_rejects_unaccounted_files_and_observation_errors(tmp_path, monkeypatch, fault):
    (tmp_path / "known").write_bytes(b"known")
    budget = FakeBudget(tmp_path)
    if fault in {"unknown", "unknown-empty", "temporary"}:
        folder = tmp_path / "tmp" if fault == "temporary" else tmp_path
        folder.mkdir(exist_ok=True)
        (folder / "unknown").write_bytes(b"" if fault == "unknown-empty" else b"x")
    elif fault == "modified": (tmp_path / "known").write_bytes(b"more bytes")
    elif fault == "removed": (tmp_path / "known").unlink()
    elif fault == "same-total-different-file": (tmp_path / "known").rename(tmp_path / "other")
    else:
        original = Path.stat
        def denied(path, *a, **k):
            if path == tmp_path / "known": raise PermissionError("synthetic")
            return original(path, *a, **k)
        monkeypatch.setattr(Path, "stat", denied)
    with pytest.raises((rt.BoundaryError, PermissionError)):
        budget.scan()


@pytest.mark.parametrize("fault", [None, "oversize", "shrink", "stat"])
def test_worker_direct_log_growth_is_accounted_without_recursive_scans(tmp_path, monkeypatch, fault):
    log = tmp_path / "acquisition-supervision.stderr"
    log.write_bytes(b"old")
    budget = FakeBudget(tmp_path)
    if fault == "stat":
        original = Path.stat
        def denied(path, *a, **k):
            if path == log: raise PermissionError("synthetic")
            return original(path, *a, **k)
        monkeypatch.setattr(Path, "stat", denied)
    else: log.write_bytes(b"x" * (8 * 1024**2 + 1) if fault == "oversize" else b"" if fault == "shrink" else b"growing")
    if fault:
        with pytest.raises((rt.BoundaryError, PermissionError)): budget.check()
    else:
        assert budget.check() == 7 and budget.scan_count == 1
        assert budget.scan() == 7


def test_worker_short_write_is_reserved_not_refunded_or_reused(tmp_path):
    budget = FakeBudget(tmp_path)
    path = tmp_path / "partial"
    with path.open("xb") as stream:
        class ShortWriter:
            name = str(path)
            def write(self, body):
                stream.write(body[:2]); stream.flush(); return 2
            def flush(self): stream.flush()
        with pytest.raises(rt.BoundaryError, match="short_write"):
            budget.write_chunk(ShortWriter(), b"payload")
    assert path.read_bytes() == b"pa" and budget.total == budget.written == 7
    with pytest.raises(rt.BoundaryError, match="disk_ledger_mismatch"): budget.scan()
    with pytest.raises(FileExistsError): budget.write_json(path, {})


def test_worker_all_metadata_bytes_and_bounded_events_count_in_ledger(tmp_path, monkeypatch):
    budget = FakeBudget(tmp_path)
    budget.write_json(tmp_path / "metadata.json", {"metadata": "synthetic"})
    budget.event("sources", "start")
    assert budget.scan() == rt.disk_bytes(tmp_path) == budget.written
    size = budget.total
    monkeypatch.setattr(prep, "DISK", size)
    with pytest.raises(rt.BoundaryError, match="disk_budget"): budget.write_json(tmp_path / "overflow", {})
    assert (tmp_path / "overflow").stat().st_size == 0
    monkeypatch.setattr(prep, "DISK", rt.DISK)
    metadata = tmp_path / "acquisition-phases.jsonl"
    budget.files[metadata.name] = 32768
    with pytest.raises(rt.BoundaryError, match="phase_metadata_budget"): budget.event("sources", "end")


@pytest.mark.parametrize("difference", [-1, 1])
def test_archive_stream_length_mismatch_preserves_partial_bytes(tmp_path, monkeypatch, difference):
    archive = tmp_path / "archive.zip"
    with zipfile.ZipFile(archive, "w") as stream: stream.writestr("entry", b"12345")
    original = zipfile.ZipFile.open
    def changed(self, name, mode="r", *a, **k):
        if mode == "r": return io.BytesIO(b"x" * (5 + difference))
        return original(self, name, mode, *a, **k)
    monkeypatch.setattr(zipfile.ZipFile, "open", changed)
    with pytest.raises(rt.BoundaryError, match="archive_size|archive_byte_budget"):
        prep.extract_zip(archive, tmp_path / "out", FakeBudget(tmp_path))
    assert (tmp_path / "out/entry").exists()


class DispatchBody(io.BytesIO):
    def __init__(self, data): super().__init__(data); self.reads = []
    def read(self, size=-1):
        assert size >= 0, "unbounded_body_read"
        self.reads.append(size)
        return super().read(size)


def dispatch_opener(responses, clock=None):
    import email.message
    import urllib.response
    calls, bodies = [], []
    class SyntheticHTTPS(prep.urllib.request.HTTPSHandler):
        def https_open(self, request):
            calls.append((request.full_url, request.timeout))
            status, location, body = responses[len(calls) - 1]
            headers = email.message.Message()
            if location is not None: headers["Location"] = location
            payload = DispatchBody(body); bodies.append(payload)
            response = urllib.response.addinfourl(payload, headers, request.full_url, status)
            response.msg = "synthetic"
            if clock is not None: clock.now += 1
            return response
    opener = prep.urllib.request.build_opener(SyntheticHTTPS(), prep.Redirects(), prep.ClosedErrors())
    return opener, calls, bodies


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_real_urllib_redirect_dispatch_closes_without_reading_body(tmp_path, code):
    opener, calls, bodies = dispatch_opener([(code, "/next", b"discarded"), (200, None, b"data")])
    budget = FakeBudget(tmp_path)
    assert prep.fetch("https://github.com/start", tmp_path / "file", budget, opener=opener) == rt.digest(b"data")
    assert [row[0] for row in calls] == ["https://github.com/start", "https://github.com/next"]
    assert bodies[0].reads == [] and all(body.closed for body in bodies)
    assert budget.downloaded == 4


@pytest.mark.parametrize("fault", ["origin", "credentials", "port", "loop", "hops", "missing", "error", "deadline", "totalcap"])
def test_real_urllib_dispatch_rejects_redirect_error_and_budget_faults(tmp_path, monkeypatch, fault):
    clock = Clock()
    responses = [(302, "/next", b"never read"), (200, None, b"payload")]
    if fault == "origin": responses[0] = (302, "http://github.com/x", b"never read")
    elif fault == "credentials": responses[0] = (302, "https://u@github.com/x", b"never read")
    elif fault == "port": responses[0] = (302, "https://github.com:444/x", b"never read")
    elif fault == "loop": responses[0] = (302, "/start", b"never read")
    elif fault == "hops": responses = [(302, "/" + str(i), b"never read") for i in range(6)]
    elif fault == "missing": responses[0] = (302, None, b"never read")
    elif fault == "error": responses[0] = (500, None, b"never read")
    elif fault == "totalcap": monkeypatch.setattr(prep, "DOWNLOAD", 3)
    budget = prep.Budget(tmp_path, ps=FakePS(tmp_path), clock=clock)
    if fault == "deadline": clock.now = 599.5
    opener, calls, bodies = dispatch_opener(responses, clock)
    with pytest.raises(rt.BoundaryError): prep.fetch("https://github.com/start", tmp_path / "file", budget, opener=opener)
    assert all(body.closed for body in bodies)
    if fault != "totalcap": assert all(body.reads == [] for body in bodies)
    assert len(calls) <= 6


def test_redirect_hops_share_remaining_time_and_close_http_error(tmp_path):
    clock = Clock(); budget = prep.Budget(tmp_path, ps=FakePS(tmp_path), clock=clock)
    clock.now = 597
    opener, calls, bodies = dispatch_opener([(302, "/next", b"discard"), (200, None, b"data")], clock)
    prep.fetch("https://github.com/start", tmp_path / "file", budget, opener=opener)
    assert [row[1] for row in calls] == [3, 2] and all(body.closed for body in bodies)
    error_body = DispatchBody(b"never consumed")
    def denied(*a, **k): raise prep.urllib.error.HTTPError("https://github.com/x", 403, "synthetic", {}, error_body)
    with pytest.raises(rt.BoundaryError, match="http_status"):
        prep.fetch("https://github.com/x", tmp_path / "error", budget, opener=SimpleNamespace(open=denied))
    assert error_body.closed and error_body.reads == []


def test_disk_optional_checkpoint_order_and_original_return_errors(tmp_path, monkeypatch):
    (tmp_path / "one").write_bytes(b"123")
    (tmp_path / "two").write_bytes(b"45")
    events = []
    assert rt.disk_bytes(tmp_path, checkpoint=events.append) == rt.disk_bytes(tmp_path) == 5
    assert events == ["start", "before_entry", "after_entry", "before_entry", "after_entry", "complete"]
    monkeypatch.setattr(rt, "DISK", 4)
    with pytest.raises(rt.BoundaryError, match="disk_budget"): rt.disk_bytes(tmp_path)
    with pytest.raises(rt.BoundaryError, match="disk_budget"): rt.disk_bytes(tmp_path, checkpoint=lambda event: None)


@pytest.mark.parametrize("fault", ["deadline", "rss", "host", "log", "identity", "observation"])
def test_supervisor_scan_checks_mid_traversal_and_preserves_owned_cleanup(tmp_path, monkeypatch, fault):
    clock = Clock(); ps = FakePS(tmp_path); process = FakePopen(ps, clock)
    env = rt.clean_environment([], tmp_path, "tmp")
    (tmp_path / "first").write_bytes(b"x")
    (tmp_path / "second").write_bytes(b"y")
    launched = False
    changed = False
    original = rt.safe_path
    def mutate(root, name):
        nonlocal changed
        result = original(root, name)
        if launched and not changed:
            changed = True
            if fault == "deadline": clock.now = 1.1
            elif fault == "rss": ps.fault = "rss"
            elif fault == "host": ps.fault = "host"
            elif fault == "observation": ps.fault = "observation"
            elif fault == "identity": ps.reused = True
            else:
                with (tmp_path / "run.stderr").open("ab") as stream: stream.write(b"x" * (8 * 1024**2 + 1))
        return result
    def launch(*a, **k):
        nonlocal launched
        launched = True
        return process
    monkeypatch.setattr(rt, "safe_path", mutate)
    with pytest.raises((rt.BoundaryError, FakePS.AccessDenied)):
        rt.run_owned([tmp_path / "root.exe"], cwd=tmp_path, env=env, root=tmp_path,
                     log_prefix=tmp_path / "run", deadline=6, rss=100, host=1, start=1,
                     allowed=[tmp_path / "root.exe", tmp_path / "child.exe"], ps=ps, popen=launch,
                     clock=clock, sleeper=clock.sleep)
    result = rt.load(tmp_path / "run.json")
    assert changed and result["active_disk_scans"]["count"] == 1
    assert result["active_disk_scans"]["entries"] == 1
    assert result["budget"]["cleanup_reserved_seconds"] == 5
    assert set(ps.killed) <= {10, 20}
    if fault == "identity": assert result["cleanup"]["errors"] and not ps.killed
    else: assert result["cleanup"]["all_absent"]


def test_startup_scan_deadline_stops_before_launch(tmp_path, monkeypatch):
    clock = Clock(); ps = FakePS(tmp_path)
    env = rt.clean_environment([], tmp_path, "tmp")
    original = rt.safe_path
    def slow(root, name):
        result = original(root, name)
        clock.now += 0.6
        return result
    monkeypatch.setattr(rt, "safe_path", slow)
    with pytest.raises(rt.BoundaryError, match="deadline_before_start"):
        rt.run_owned([], cwd=tmp_path, env=env, root=tmp_path, log_prefix=tmp_path / "run",
                     deadline=6, rss=100, host=1, start=1, allowed=[], ps=ps,
                     popen=lambda *a, **k: pytest.fail("no process may start"), clock=clock, sleeper=clock.sleep)


def test_archive_crc_rejection_is_not_bypassed_by_ledger(tmp_path):
    archive = tmp_path / "crc.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as stream:
        stream.writestr("entry", b"unique CRC payload")
    original = archive.read_bytes()
    archive.write_bytes(original.replace(b"unique CRC payload", b"broken CRC payload", 1))
    with pytest.raises(zipfile.BadZipFile, match="CRC"):
        prep.extract_zip(archive, tmp_path / "out", FakeBudget(tmp_path))
    assert archive.read_bytes() != original and (tmp_path / "out/entry").exists()


def test_phase_reporting_failure_keeps_original_exception(tmp_path, monkeypatch):
    budget = FakeBudget(tmp_path)
    original = budget.event
    def broken(phase, state, **kwargs):
        if state == "failed": raise OSError("synthetic reporting failure")
        original(phase, state, **kwargs)
    monkeypatch.setattr(budget, "event", broken)
    with pytest.raises(ValueError, match="original") as error, budget.phase("sources"):
        raise ValueError("original")
    assert error.value.__notes__ == ["phase_metadata_failed:OSError"]


@pytest.mark.parametrize("remaining", [-1, 0, 1])
def test_bounded_metadata_serialized_bytes_fit_exact_or_reject_before_write(tmp_path, remaining):
    (tmp_path / "payload").write_bytes(b"abc")
    value = {"cleanup": {"all_absent": True}, "unicode": "한글"}
    encoded = (json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode()
    path = tmp_path / "receipt.json"
    if remaining < 0:
        with pytest.raises(rt.BoundaryError, match="disk_budget"):
            rt.write_bounded(tmp_path, path, value, limit=3 + len(encoded) + remaining)
        assert not path.exists() and rt.disk_bytes(tmp_path) == 3
    else:
        rt.write_bounded(tmp_path, path, value, limit=3 + len(encoded) + remaining)
        assert path.read_bytes() == encoded and rt.disk_bytes(tmp_path) == 3 + len(encoded)


def metadata_stream_fault(monkeypatch, target_name, fault, clock=None):
    original = Path.open
    def opening(path, mode="r", *args, **kwargs):
        stream = original(path, mode, *args, **kwargs)
        if path.name != target_name or mode != "xb": return stream
        class Stream:
            def __enter__(self): return self
            def __exit__(self, *args): stream.close()
            def write(self, data):
                if fault == "short": return stream.write(data[:-1])
                if fault == "write": raise OSError("synthetic write failure")
                count = stream.write(data)
                if fault == "late-write": clock.now = 611
                return count
            def flush(self):
                if fault == "flush": raise OSError("synthetic flush failure")
                stream.flush()
                if fault == "late-flush": clock.now = 611
        return Stream()
    monkeypatch.setattr(Path, "open", opening)


@pytest.mark.parametrize("fault", ["short", "write", "flush", "disk-over", "disk-exact", "disk-spare"])
@pytest.mark.parametrize("process_fault", [None, "rss"])
def test_supervision_receipt_faults_preserve_primary_and_cleanup(tmp_path, monkeypatch, fault, process_fault):
    clock = Clock(); ps = FakePS(tmp_path, process_fault); process = FakePopen(ps, clock)
    original = rt.write_bounded
    observed = {}
    def writer(root, path, record, **kwargs):
        observed["record"] = record
        if fault.startswith("disk-"):
            size = len((json.dumps(record, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode())
            cap = rt.disk_bytes(root) + size + {"disk-over": -1, "disk-exact": 0, "disk-spare": 1}[fault]
            kwargs["limit"] = cap
            observed["cap"] = cap
        return original(root, path, record, **kwargs)
    monkeypatch.setattr(rt, "write_bounded", writer)
    metadata_stream_fault(monkeypatch, "run.json", fault)
    kwargs = {"cwd": tmp_path, "env": rt.clean_environment([], tmp_path, "tmp"), "root": tmp_path,
              "log_prefix": tmp_path / "run", "deadline": 6, "rss": 100, "host": 1, "start": 1,
              "allowed": [tmp_path / "root.exe", tmp_path / "child.exe"], "ps": ps,
              "popen": lambda *a, **k: process, "clock": clock, "sleeper": clock.sleep}
    fails = fault not in {"disk-exact", "disk-spare"}
    if process_fault or fails:
        with pytest.raises((rt.BoundaryError, OSError)) as caught:
            rt.run_owned([tmp_path / "root.exe"], **kwargs)
        assert caught.value.supervision_record is observed["record"]
        if process_fault:
            assert str(caught.value) == "resource_budget"
            if fails: assert caught.value.__notes__[0].startswith("supervision_receipt_failed:")
    else:
        result = rt.run_owned([tmp_path / "root.exe"], **kwargs)
        assert result["within_shared_deadline"]
    assert observed["record"]["cleanup"]["all_absent"] and process.closed
    assert set(ps.killed) <= {10, 20}
    if fault == "disk-over": assert not (tmp_path / "run.json").exists()
    if fault in {"disk-exact", "disk-spare"}:
        assert rt.disk_bytes(tmp_path) <= observed["cap"]


@pytest.mark.parametrize("fault", [None, "scan", "read", "late-write", "late-flush", "publish", "short", "flush"])
def test_acquisition_finalization_shares_absolute_deadline_and_never_accepts_late_lock(tmp_path, monkeypatch, fault):
    root = tmp_path / "new"
    clock = Clock(); clock.now = 10
    finished = False
    calls = []
    def runner(argv, **kwargs):
        nonlocal finished
        calls.append(kwargs["deadline"])
        assert kwargs["deadline"] == 610
        rt.write(root / "raw-acquisition.json", {"status": "ACQUIRED_UNREVIEWED_DO_NOT_EXECUTE"})
        rt.write(root / "acquisition-supervision.json", {"cleanup": {"all_absent": True, "errors": []}})
        clock.now = 609
        finished = True
    original_safe = rt.safe_path
    def safe(folder, name):
        value = original_safe(folder, name)
        if finished and fault == "scan" and name == "raw-acquisition.json": clock.now = 611
        return value
    monkeypatch.setattr(rt, "safe_path", safe)
    original_load = prep.load
    def load(path):
        value = original_load(path)
        if fault == "read" and path.name == "raw-acquisition.json": clock.now = 611
        return value
    monkeypatch.setattr(prep, "load", load)
    original_rename = Path.rename
    def rename(path, target):
        value = original_rename(path, target)
        if fault == "publish" and path.name == "acquisition-pending.json": clock.now = 611
        return value
    monkeypatch.setattr(Path, "rename", rename)
    metadata_stream_fault(monkeypatch, "acquisition-pending.json", fault, clock)
    if fault:
        with pytest.raises((rt.BoundaryError, OSError)):
            prep.acquire_supervised(root, runner=runner, clock=clock)
        assert not (root / "acquisition.json").exists()
        assert (root / "raw-acquisition.json").exists()
        assert (root / "acquisition-supervision-failure.json").exists()
        with pytest.raises(rt.BoundaryError, match="acquisition_finalization_failed"):
            prep.check_acquired(root, "0" * 64)
    else:
        result = prep.acquire_supervised(root, runner=runner, clock=clock)
        assert result["status"] == "ACQUIRED_UNREVIEWED_DO_NOT_EXECUTE"
        assert (root / "acquisition.json").exists()
        assert not (root / "acquisition-pending.json").exists()
        assert clock.now == 609
    assert calls == [610]


def test_acquisition_reporting_failure_retains_original_error_without_new_budget(tmp_path, monkeypatch):
    root = tmp_path / "new"; clock = Clock()
    original = rt.BoundaryError("original worker failure")
    def runner(*args, **kwargs):
        clock.now = kwargs["deadline"] + 1
        raise original
    metadata_stream_fault(monkeypatch, "acquisition-supervision-failure.json", "flush")
    with pytest.raises(rt.BoundaryError) as caught:
        prep.acquire_supervised(root, runner=runner, clock=clock)
    assert caught.value is original
    assert original.__notes__ == ["supervision_metadata_failed:OSError"]
    assert clock.now == 601 and not (root / "acquisition.json").exists()


@pytest.mark.parametrize("fault", ["scan", "late-write", "late-flush"])
def test_supervision_receipt_scan_and_write_deadline_cannot_return_success(tmp_path, monkeypatch, fault):
    clock = Clock(); ps = FakePS(tmp_path); process = FakePopen(ps, clock)
    original = rt.write_bounded
    def writer(*args, **kwargs):
        clock.now = 609
        if fault == "scan":
            original_safe = rt.safe_path
            def safe(root, name):
                result = original_safe(root, name)
                if name == "run.stdout": clock.now = 611
                return result
            monkeypatch.setattr(rt, "safe_path", safe)
        return original(*args, **kwargs)
    monkeypatch.setattr(rt, "write_bounded", writer)
    metadata_stream_fault(monkeypatch, "run.json", fault, clock)
    with pytest.raises(rt.BoundaryError, match="shared_deadline") as caught:
        rt.run_owned([], cwd=tmp_path, env=rt.clean_environment([], tmp_path, "tmp"), root=tmp_path,
                     log_prefix=tmp_path / "run", deadline=610, rss=100, host=1, start=1,
                     allowed=[tmp_path / "root.exe", tmp_path / "child.exe"], ps=ps,
                     popen=lambda *a, **k: process, clock=clock, sleeper=clock.sleep)
    assert caught.value.supervision_record["cleanup"]["all_absent"] and process.closed
    assert clock.now == 611


def test_late_publication_rollback_error_preserves_timeout_and_rejects_lock(tmp_path, monkeypatch):
    root = tmp_path / "new"; clock = Clock()
    def runner(*args, **kwargs):
        rt.write(root / "raw-acquisition.json", {"status": "ACQUIRED_UNREVIEWED_DO_NOT_EXECUTE"})
        rt.write(root / "acquisition-supervision.json", {"cleanup": {"all_absent": True, "errors": []}})
    original = Path.rename
    def rename(path, target):
        if path.name == "acquisition.json": raise OSError("synthetic rollback failure")
        result = original(path, target)
        clock.now = 601
        return result
    monkeypatch.setattr(Path, "rename", rename)
    with pytest.raises(rt.BoundaryError, match="shared_deadline") as caught:
        prep.acquire_supervised(root, runner=runner, clock=clock)
    assert caught.value.__notes__ == ["late_lock_invalidation_failed:OSError"]
    assert (root / "acquisition.json").exists()
    with pytest.raises(rt.BoundaryError, match="acquisition_finalization_failed"):
        prep.check_acquired(root, rt.digest((root / "acquisition.json").read_bytes()))

# Explicit v3 policy tests use only fake clocks/processes and small synthetic archives.
def v3_external_fixture(root, mutate=None, profile=prep.ACQUISITION_PROFILE):
    """Synthetic tmp-only claims: no observer/session/approval or actual run exists.

    Supplying this self-asserted digest is ONLY a test input, never operational
    authorization. Pure hashes cannot establish the truth of these assertions.
    """
    folder = root.with_name(root.name + ".external-review")
    folder.mkdir(exist_ok=True)
    def put(name, value):
        data = value if isinstance(value, bytes) else (json.dumps(value, allow_nan=True) + "\n").encode()
        (folder / name).write_bytes(data)
    put("cli.stdout", b'{"status": "ACQUIRED_UNREVIEWED_DO_NOT_EXECUTE"}\n')
    put("cli.stderr", b"synthetic fixture only\n")
    repo = Path(prep.__file__).resolve().parents[1]
    sources = [rt.reference(repo / name, repo) for name in ("scripts/prepare_summary_grammar_engine.py", "tools/summary_grammar/runtime.py", "tools/summary_grammar/pins.json")]
    attempt = rt.reference(root / "acquisition-attempt.json", root)
    manifest = rt.reference(root / "acquisition.json", root)
    python = prep.os.path.normcase(str(Path(prep.sys.executable).resolve()))
    observer = {"pid": 100, "create_time": 1.0, "executable": python, "source_sha256": "1" * 64}
    cli = {"pid": 101, "create_time": 2.0, "executable": python}
    common = {"profile": profile, "workspace": str(root.resolve())}
    terminal = {"schema": "engine-v3-external-terminal-v1", "evidence_kind": "external_actual_cli_observation", **common,
        "attempt_sha256": attempt["sha256"], "manifest_sha256": manifest["sha256"],
        "stdout_sha256": rt.reference(folder / "cli.stdout", folder)["sha256"], "stderr_sha256": rt.reference(folder / "cli.stderr", folder)["sha256"],
        "argv": rt.load(root / "acquisition-attempt.json")["argv"][:3] + ["acquire", "--workspace", str(root), "--acquisition-profile", profile],
        "observer": observer, "cli": cli, "sources_before": sources, "sources_after": sources,
        "exit_code": 0, "terminal_observed": True, "elapsed_seconds": 4.0, "budget_seconds": prep.acquisition_seconds(profile),
        "cleanup_reserved_seconds": 5, "limits_pass": True, "first_failure": None}
    custody = {"schema": "engine-v3-external-custody-v1", **common, "attempt_sha256": attempt["sha256"], "manifest_sha256": manifest["sha256"],
        "observer_terminal_sha256": "pending", "identities": [{**cli, "absent": True}, {"pid": 202, "create_time": 2.0, "executable": python, "absent": True}],
        "all_absent": True, "errors": []}
    acceptance = {"schema": "engine-v3-external-acceptance-v1", **common, "attempt": attempt, "manifest": manifest,
        "stdout": rt.reference(folder / "cli.stdout", folder), "stderr": rt.reference(folder / "cli.stderr", folder),
        "observer_terminal": {}, "custody": {}, "sources": sources}
    if mutate:
        mutate("terminal", terminal)
    put("observer-terminal.json", terminal)
    acceptance["observer_terminal"] = rt.reference(folder / "observer-terminal.json", folder)
    custody["observer_terminal_sha256"] = acceptance["observer_terminal"]["sha256"]
    if mutate:
        mutate("custody", custody)
    put("custody.json", custody)
    acceptance["custody"] = rt.reference(folder / "custody.json", folder)
    if mutate:
        mutate("acceptance", acceptance)
    put("acceptance.json", acceptance)
    return rt.digest((folder / "acceptance.json").read_bytes())


def v3_budget(root, clock=None, ps=None):
    return prep.Budget(root, ps=ps or FakePS(root), clock=clock or Clock(), acquisition_profile=prep.ACQUISITION_PROFILE)


def test_v3_worker_interval_forced_phases_and_legacy_per_checkpoint(tmp_path):
    clock = Clock(); ps = FakePS(tmp_path)
    budget = v3_budget(tmp_path, clock, ps)
    first = budget.samples
    for _ in range(4): budget.check()
    clock.now = 0.049; budget.check()
    assert budget.samples == first
    clock.now = 0.050; budget.check()
    assert budget.samples == first + 1
    clock.now = 0.400; budget.check()
    assert budget.samples == first + 2  # no catch-up burst
    with budget.phase("sources"):
        budget.check()
    budget.check(force="success-terminal")
    assert budget.forced_samples == {"start": 1, "phase-start:sources": 1, "phase-complete:sources": 1, "success-terminal": 1}
    assert budget.max_sample_gap == pytest.approx(0.350)
    legacy = prep.Budget(tmp_path, ps=ps, clock=clock)
    before = ps.memory_samples
    legacy.check(); legacy.check()
    assert ps.memory_samples == before + 2


@pytest.mark.parametrize("fault", ["deadline", "download", "disk", "log", "log-shrink"])
def test_v3_worker_cheap_limits_and_sticky_failure_between_samples(tmp_path, monkeypatch, fault):
    clock = Clock(); budget = v3_budget(tmp_path, clock)
    if fault == "deadline": clock.now = 600
    elif fault == "download": budget.downloaded = rt.DOWNLOAD + 1
    elif fault == "disk": budget.total = prep.DISK + 1
    else:
        path = tmp_path / "acquisition-supervision.stdout"
        if fault == "log":
            with path.open("wb") as stream: stream.truncate(8 * 1024**2 + 1)
        else:
            path.write_bytes(b"abc"); budget.check(); path.write_bytes(b"a")
    count = budget.samples
    with pytest.raises(rt.BoundaryError) as caught: budget.check()
    clock.now = 0; budget.downloaded = budget.total = 0
    with pytest.raises(rt.BoundaryError) as repeated: budget.check(force="success-terminal")
    assert repeated.value is caught.value and budget.samples == count


@pytest.mark.parametrize("fault", ["rss", "host", "observation", "slow-os"])
def test_v3_worker_scheduled_resources_and_post_os_deadline_latch(tmp_path, monkeypatch, fault):
    clock = Clock(); ps = FakePS(tmp_path); budget = v3_budget(tmp_path, clock, ps)
    if fault == "rss":
        monkeypatch.setattr(ps, "Process", lambda: SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=3 * 1024**3), children=lambda **k: []))
    elif fault == "slow-os":
        original = ps.virtual_memory
        def slow():
            result = original(); clock.now = 601; return result
        monkeypatch.setattr(ps, "virtual_memory", slow)
    else: ps.fault = fault
    budget.check()  # below interval does not observe the expensive fault
    clock.now = 0.050
    with pytest.raises((rt.BoundaryError, FakePS.AccessDenied)) as caught: budget.check()
    ps.fault = None; clock.now = 0
    with pytest.raises(type(caught.value)) as repeated: budget.check()
    assert caught.value is repeated.value


def test_v3_phase_failure_and_metadata_failure_preserve_original(tmp_path, monkeypatch):
    budget = v3_budget(tmp_path)
    original = ValueError("original phase failure")
    with pytest.raises(ValueError) as caught, budget.phase("sources"):
        raise original
    assert caught.value is original and budget.failure is original
    assert budget.terminal_observation == "skipped_prior_failure"
    with pytest.raises(ValueError) as repeated:
        budget.write_json(tmp_path / "success.json", {"status": "success"})
    assert repeated.value is original and not (tmp_path / "success.json").exists()


def v3_run_wrapper(monkeypatch):
    original = rt.run_owned
    def run(*args, **kwargs):
        return original(*args, **kwargs, acquisition_profile=prep.ACQUISITION_PROFILE)
    monkeypatch.setattr(rt, "run_owned", run)


@pytest.mark.parametrize("fault", [None, "start", "capture", "rss", "host", "observation", "unexpected", "timeout", "log", "cleanup-denied"])
def test_v3_owned_failure_cleanup_regressions(tmp_path, monkeypatch, fault):
    v3_run_wrapper(monkeypatch)
    test_owned_tree_mocked_resource_failure_cleanup_and_no_unrelated_kill(tmp_path, fault)


@pytest.mark.parametrize("fault", ["short", "write", "flush", "disk-over", "disk-exact", "disk-spare"])
@pytest.mark.parametrize("process_fault", [None, "rss"])
def test_v3_receipt_fault_regressions(tmp_path, monkeypatch, fault, process_fault):
    v3_run_wrapper(monkeypatch)
    test_supervision_receipt_faults_preserve_primary_and_cleanup(tmp_path, monkeypatch, fault, process_fault)


@pytest.mark.parametrize("fault", ["scan", "late-write", "late-flush"])
def test_v3_receipt_deadline_regressions(tmp_path, monkeypatch, fault):
    v3_run_wrapper(monkeypatch)
    test_supervision_receipt_scan_and_write_deadline_cannot_return_success(tmp_path, monkeypatch, fault)


def test_v3_supervisor_sampling_boundaries_and_no_catchup(tmp_path, monkeypatch):
    clock = Clock(); ps = FakePS(tmp_path); process = FakePopen(ps, clock)
    observed, checkpoints = [], []
    original_sample, original_disk = rt.OwnedTree.sample, rt.disk_bytes
    def sample(self, *args):
        observed.append(clock.now)
        return original_sample(self, *args)
    def disk(root, checkpoint=None):
        if checkpoint and checkpoint.__name__ == "scan_checkpoint":
            checkpoint("start")
            before = len(observed)
            clock.now += 0.049; checkpoint("before_entry"); checkpoints.append(len(observed) - before)
            clock.now += 0.001; checkpoint("after_entry"); checkpoints.append(len(observed) - before)
            clock.now += 0.5; checkpoint("before_entry"); checkpoints.append(len(observed) - before)
            checkpoint("complete")
            return 0
        return original_disk(root, checkpoint)
    monkeypatch.setattr(rt.OwnedTree, "sample", sample)
    monkeypatch.setattr(rt, "disk_bytes", disk)
    result = rt.run_owned([], cwd=tmp_path, env=rt.clean_environment([], tmp_path, "tmp"), root=tmp_path,
                          log_prefix=tmp_path / "run", deadline=60, rss=100, host=1, start=1,
                          allowed=[tmp_path / "root.exe", tmp_path / "child.exe"], ps=ps,
                          popen=lambda *a, **k: process, clock=clock, sleeper=clock.sleep,
                          acquisition_profile=prep.ACQUISITION_PROFILE)
    assert checkpoints[:3] == [0, 1, 2]
    reasons = result["resource_sampling"]["forced_reasons"]
    assert reasons == {"child_capture": 1, "scan_start": 2, "scan_complete": 2, "process_terminal": 1, "before_cleanup": 1}
    assert result["resource_sampling"]["startup_forced_reasons"] == {"host_gate": 1, "start": 1, "complete": 1, "before_spawn": 1}
    assert result["resource_sampling"]["sample_count"] == len(observed)
    assert result["resource_sampling"]["terminal_observation"] == "observed"


@pytest.mark.parametrize("fault", ["deadline", "log", "disk", "slow-sample", "identity", "unexpected", "observation", "rss", "host"])
def test_v3_supervisor_checkpoint_failures_cleanup_and_first_cause(tmp_path, monkeypatch, fault):
    clock = Clock(); ps = FakePS(tmp_path); process = FakePopen(ps, clock)
    original_disk, original_sample = rt.disk_bytes, rt.OwnedTree.sample
    def sample(self, *args):
        result = original_sample(self, *args)
        if fault == "slow-sample": clock.now = 56
        return result
    def disk(root, checkpoint=None):
        if checkpoint and checkpoint.__name__ == "scan_checkpoint":
            checkpoint("start")
            if fault == "deadline": clock.now = 56
            elif fault == "log":
                with (tmp_path / "run.stdout").open("ab") as stream: stream.truncate(8 * 1024**2 + 1)
            elif fault == "disk": raise rt.BoundaryError("disk_budget")
            elif fault == "identity": ps.reused = True; clock.now = 0.050
            else: ps.fault = fault; clock.now = 0.050
            checkpoint("before_entry")
            return 0
        return original_disk(root, checkpoint)
    monkeypatch.setattr(rt, "disk_bytes", disk)
    monkeypatch.setattr(rt.OwnedTree, "sample", sample)
    with pytest.raises((rt.BoundaryError, FakePS.AccessDenied)) as caught:
        rt.run_owned([], cwd=tmp_path, env=rt.clean_environment([], tmp_path, "tmp"), root=tmp_path,
                     log_prefix=tmp_path / "run", deadline=60, rss=100, host=1, start=1,
                     allowed=[tmp_path / "root.exe", tmp_path / "child.exe"], ps=ps,
                     popen=lambda *a, **k: process, clock=clock, sleeper=clock.sleep,
                     acquisition_profile=prep.ACQUISITION_PROFILE)
    record = caught.value.supervision_record
    assert record["failure_latched"] and record["status"] == "failed"
    assert record["resource_sampling"]["terminal_observation"] == "skipped_prior_failure"
    if fault == "identity": assert ps.killed == []
    else: assert record["cleanup"]["all_absent"]
    assert clock.now <= 60


def llvm_fixture_rows():
    return {prep.LLVM_PREFIX + name: b"synthetic" for name in (
        "bin/clang.exe", "bin/clang++.exe", "bin/clang-20.exe", "bin/helper.dll", "bin/driver-wrapper",
        "include/shared.h", "lib/shared.a", "share/doc/readme.txt", "lib/clang/20/include/resource.h",
        "include/windows.h", "include/_mingw.h", "include/c++/v1/__config",
        "x86_64-w64-mingw32/lib/kernel32.a", "LICENSE.TXT",
        "i686-w64-mingw32/lib/unused.a", "python/unused.py", "aarch64-w64-mingw32/include/unused.h",
        "armv7-w64-mingw32/COPYING", "python/nested/COPYRIGHT.txt")}


def llvm_fixture_zip(path, rows=None):
    with zipfile.ZipFile(path, "w") as archive:
        for name, body in (rows or llvm_fixture_rows()).items(): archive.writestr(name, body)
    return path


def test_v3_selection_retains_licenses_dependencies_and_never_opens_excluded(tmp_path, monkeypatch):
    archive = llvm_fixture_zip(tmp_path / "llvm.zip")
    monkeypatch.setattr(prep, "LLVM_SHA", rt.digest(archive.read_bytes()))
    original = zipfile.ZipFile.open
    opened = []
    def opening(self, member, *args, **kwargs):
        opened.append(member.filename)
        assert not member.filename.endswith(("unused.a", "unused.py", "unused.h"))
        return original(self, member, *args, **kwargs)
    monkeypatch.setattr(zipfile.ZipFile, "open", opening)
    budget = v3_budget(tmp_path)
    summary = prep.extract_llvm_x64(archive, tmp_path / "out", budget)
    assert summary["excluded_entries"] == 3 and summary["selected_entries"] == 16
    assert not (tmp_path / "out" / prep.LLVM_PREFIX / "x86_64-w64-mingw32/include").exists()
    assert set(opened) == {r["file"] for r in rt.inventory(tmp_path / "out")}
    assert (tmp_path / "out" / prep.LLVM_PREFIX / "python/nested/COPYRIGHT.txt").is_file()
    budget.scan()
    assert budget.total == rt.disk_bytes(tmp_path)
    with zipfile.ZipFile(archive) as source:
        infos, same = prep.llvm_selection(list(reversed(source.infolist())), tmp_path / "out")
    assert same == summary
    encoded = json.dumps([[i.filename, i.file_size, i.CRC, i.external_attr] for i in infos], ensure_ascii=True, separators=(",", ":")).encode()
    assert summary["selection_sha256"] == rt.digest(encoded)


@pytest.mark.parametrize("missing", ["bin/clang.exe", "bin/clang++.exe", "bin/clang-20.exe", "lib/clang/20/include/resource.h", "include/windows.h", "include/_mingw.h", "include/c++/v1/__config", "share/doc/readme.txt", "x86_64-w64-mingw32/lib/kernel32.a", "LICENSE.TXT"])
@pytest.mark.parametrize("empty", [False, True])
def test_v3_selection_requires_nonempty_x64_dependencies(tmp_path, missing, empty):
    rows = llvm_fixture_rows()
    if empty: rows[prep.LLVM_PREFIX + missing] = b""
    else: del rows[prep.LLVM_PREFIX + missing]
    with zipfile.ZipFile(llvm_fixture_zip(tmp_path / "llvm.zip", rows)) as archive, pytest.raises(rt.BoundaryError, match="llvm_required"):
        prep.llvm_selection(archive.infolist(), tmp_path / "out")


def test_v3_selection_rejects_target_only_header_witnesses(tmp_path):
    rows = llvm_fixture_rows()
    for name in ("include/windows.h", "include/_mingw.h", "include/c++/v1/__config"):
        rows[prep.LLVM_PREFIX + "x86_64-w64-mingw32/" + name] = rows.pop(prep.LLVM_PREFIX + name)
    with zipfile.ZipFile(llvm_fixture_zip(tmp_path / "llvm.zip", rows)) as archive, pytest.raises(rt.BoundaryError, match="llvm_required_file"):
        prep.llvm_selection(archive.infolist(), tmp_path / "out")


@pytest.mark.parametrize("fault", ["root", "unknown", "unsafe", "duplicate", "symlink", "encrypted", "oversize", "count", "extra-driver"])
def test_v3_entire_central_directory_checked_before_selected_bodies(tmp_path, monkeypatch, fault):
    rows = llvm_fixture_rows(); path = tmp_path / "llvm.zip"
    if fault == "root": rows["other/readme"] = b"x"
    elif fault == "unknown": rows[prep.LLVM_PREFIX + "new-platform/a"] = b"x"
    elif fault == "unsafe": rows[prep.LLVM_PREFIX + "python/../escape"] = b"x"
    elif fault == "duplicate": rows[prep.LLVM_PREFIX + "python/UNUSED.py"] = b"x"
    elif fault == "extra-driver": rows[prep.LLVM_PREFIX + "bin/clang-19.exe"] = b"x"
    llvm_fixture_zip(path, rows)
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
    excluded = next(i for i in infos if i.filename.endswith("unused.py"))
    if fault == "symlink": excluded.external_attr = (stat.S_IFLNK | 0o777) << 16
    elif fault == "encrypted": excluded.flag_bits |= 1
    elif fault == "oversize": excluded.file_size = prep.DISK
    elif fault == "count": infos = infos * 3000
    with pytest.raises(rt.BoundaryError): prep.llvm_selection(infos, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("operation", ["inspect", "build"])
def test_v3_profile_cli_rejects_nonacquisition_before_any_action(monkeypatch, operation):
    monkeypatch.setattr(prep.sys, "argv", ["prepare", operation, "--acquisition-profile", prep.ACQUISITION_PROFILE])
    with pytest.raises(rt.BoundaryError, match="acquisition_profile_operation"): prep.main()


@pytest.mark.parametrize("profile", ["", "unknown", "LLVM-X64", 50])
def test_v3_unknown_profile_rejected_before_root_or_resources(tmp_path, profile):
    with pytest.raises(rt.BoundaryError, match="acquisition_profile"):
        prep.acquire_supervised(tmp_path / "new", acquisition_profile=profile)
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("fault", ["profile", "token", "argv", "missing-profile"])
def test_v3_worker_attempt_binding_before_budget(tmp_path, monkeypatch, fault):
    root = tmp_path
    token = "synthetic-token"
    argv = [prep.sys.executable, "-B", str(Path(prep.__file__).resolve()), "_acquire-worker", "--workspace", str(root), "--worker-token", token, "--acquisition-profile", prep.ACQUISITION_PROFILE]
    attempt = {"worker_token": token, "argv": argv, "acquisition_profile": prep.ACQUISITION_PROFILE, "shared_seconds": 600}
    if fault == "profile": attempt["acquisition_profile"] = "other"
    elif fault == "missing-profile": del attempt["acquisition_profile"]
    elif fault == "token": attempt["worker_token"] = "other"
    else: attempt["argv"][-1] = "other"
    rt.write(root / "acquisition-attempt.json", attempt)
    monkeypatch.setenv("DOCTRAIL_ACQUIRE_TOKEN", token)
    with pytest.raises(rt.BoundaryError, match="worker_"):
        prep.acquire(root, worker_token=token, acquisition_profile=prep.ACQUISITION_PROFILE,
                     budget_factory=lambda *a, **k: pytest.fail("must reject before budget"))


def v3_mocked_acquisition(root, monkeypatch, clock=None, runner_fault=None, profile=prep.ACQUISITION_PROFILE):
    import hashlib
    clock = clock or Clock()
    urls, toolpins = {}, []
    for name in ("llvm-synthetic.zip", "cmake-synthetic.zip", "ninja-win.zip"):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            if name.startswith("llvm"):
                for file, body in llvm_fixture_rows().items(): archive.writestr(file, body)
            elif name.startswith("cmake"):
                archive.writestr("cmake.exe", b"synthetic")
                archive.writestr("LICENSE", b"synthetic license")
                archive.writestr("share/cmake-3.31/Modules/Platform/Windows-GNU.cmake", SYNTHETIC_WINDOWS_GNU)
            else: archive.writestr("ninja.exe", b"synthetic")
        url = "https://github.com/synthetic/" + name
        urls[url] = data.getvalue()
        toolpins.append({"name": name, "asset": url, "published_sha256": None if name.startswith("ninja") else rt.digest(data.getvalue())})
    monkeypatch.setattr(prep, "pins", lambda: {"tools": toolpins})
    monkeypatch.setattr(prep, "LLVM_SHA", toolpins[0]["published_sha256"])
    tree = []
    for name in ("CMakeLists.txt", "LICENSE", "src/llama-grammar.h", "src/llama-grammar.cpp"):
        body = b"synthetic source " + name.encode()
        urls[f"https://raw.githubusercontent.com/ggml-org/llama.cpp/{rt.COMMIT}/{name}"] = body
        tree.append({"path": name, "type": "blob", "mode": "100644", "size": len(body),
                     "sha": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()})
    api = "https://api.github.com/repos/ggml-org/llama.cpp/git/"
    urls[api + "commits/" + rt.COMMIT] = json.dumps({"sha": rt.COMMIT, "tree": {"sha": "a" * 40}}).encode()
    urls[api + "trees/" + "a" * 40 + "?recursive=1"] = json.dumps({"sha": "a" * 40, "truncated": False, "tree": tree}).encode()
    urls["https://raw.githubusercontent.com/ninja-build/ninja/v1.12.1/COPYING"] = b"synthetic license"
    opener = SimpleNamespace(open=lambda request, **k: Response(urls[request.full_url]))
    calls = []
    def runner(argv, **kwargs):
        calls.append(argv)
        assert kwargs["acquisition_profile"] == profile
        assert kwargs["deadline"] == prep.acquisition_seconds(profile) and kwargs["rss"] == 2 * 1024**3
        assert argv[-2:] == ["--acquisition-profile", profile]
        token = argv[argv.index("--worker-token") + 1]
        monkeypatch.setenv("DOCTRAIL_ACQUIRE_TOKEN", token)
        prep.acquire(root, opener=opener, budget_factory=lambda folder, **options: prep.Budget(folder, ps=FakePS(folder), clock=clock, **options),
                     worker_token=token, acquisition_profile=profile)
        rt.write(root / "acquisition-supervision.json", {"acquisition_profile": profile, "argv": argv,
                 "status": "process_exited_zero_not_semantic_success", "exit": 0, "within_shared_deadline": True,
                 "failure_latched": False, "cleanup": {"all_absent": True, "errors": [],
                     "identities": [[202, 2.0, prep.os.path.normcase(str(Path(prep.sys.executable).resolve()))]]},
                 "resource_sampling": {"interval_seconds": 0.050, "sample_count": 3, "terminal_observation": "observed"}})
        if runner_fault: runner_fault(root)
    result = prep.acquire_supervised(root, runner=runner, clock=clock, acquisition_profile=profile)
    assert len(calls) == 1
    return result


def test_v3_full_mocked_acquisition_and_exact_lock_verification(tmp_path, monkeypatch):
    root = tmp_path / "new"
    result = v3_mocked_acquisition(root, monkeypatch)
    checked = prep.check_acquired(root, v3_external_fixture(root))
    assert checked == result and result["schema_version"] == 2
    assert result["tools"][0]["selection"]["excluded_entries"] == 3
    assert result["worker_sampling"]["observation_point"] == "manifest_before_raw_write"
    terminal = rt.load(root / "worker-terminal.json")
    assert terminal["forced_reasons"]["success-terminal"] == 1
    phases = [json.loads(line) for line in (root / "acquisition-phases.jsonl").read_text().splitlines()]
    assert all(row["resource_sampling"]["observation_point"].startswith("phase:") for row in phases)
    with pytest.raises(FileExistsError): prep.acquire_supervised(root, acquisition_profile=prep.ACQUISITION_PROFILE)


@pytest.mark.parametrize("fault", ["final-profile", "raw-profile", "attempt-profile", "supervision-profile", "all-profiles", "selection-hash", "selection-inventory", "archive", "failure-latch", "worker-failure", "cleanup", "terminal", "terminal-ref", "attempt-argv", "raw-content", "worker-sampling", "supervisor-sampling"])
def test_v3_profile_selection_and_terminal_tampering_rejected(tmp_path, monkeypatch, fault):
    root = tmp_path / "new"
    lock = v3_mocked_acquisition(root, monkeypatch)
    def change(name, action):
        path = root / name; value = rt.load(path); action(value); path.write_text(json.dumps(value))
    if fault.endswith("-profile"):
        name = {"final-profile": "acquisition.json", "raw-profile": "raw-acquisition.json", "attempt-profile": "acquisition-attempt.json", "supervision-profile": "acquisition-supervision.json"}[fault]
        change(name, lambda value: value.pop("acquisition_profile"))
    elif fault == "all-profiles":
        for name in ("acquisition.json", "raw-acquisition.json", "acquisition-attempt.json", "acquisition-supervision.json"):
            change(name, lambda value: value.pop("acquisition_profile"))
    elif fault == "selection-hash":
        change("raw-acquisition.json", lambda value: value["tools"][0]["selection"].update(selection_sha256="0" * 64))
        change("acquisition.json", lambda value: value["tools"][0]["selection"].update(selection_sha256="0" * 64))
    elif fault == "selection-inventory":
        target = root / "tools/llvm" / prep.LLVM_PREFIX / "python/unused.py"
        target.write_bytes(b"extra")
        for name in ("raw-acquisition.json", "acquisition.json"):
            change(name, lambda value: value["tools"][0].update(inventory=rt.inventory(root / "tools/llvm")))
    elif fault == "archive": (root / "archives" / lock["tools"][0]["name"]).write_bytes(b"changed")
    elif fault == "failure-latch": change("acquisition-supervision.json", lambda value: value.update(failure_latched=True))
    elif fault == "worker-failure": rt.write(root / "acquisition-failure.json", {"reason": "synthetic"})
    elif fault == "cleanup": change("acquisition-supervision.json", lambda value: value["cleanup"].update(all_absent=False))
    elif fault == "terminal": change("worker-terminal.json", lambda value: value.update(failure_latched=True))
    elif fault == "terminal-ref": change("acquisition.json", lambda value: value.pop("worker_terminal"))
    elif fault == "attempt-argv": change("acquisition-attempt.json", lambda value: value["argv"].append("extra"))
    elif fault == "raw-content": change("raw-acquisition.json", lambda value: value.update(download_bytes=0))
    elif fault == "worker-sampling":
        for name in ("raw-acquisition.json", "acquisition.json"):
            change(name, lambda value: value["worker_sampling"].update(failure_latched=True))
    elif fault == "supervisor-sampling": change("acquisition-supervision.json", lambda value: value["resource_sampling"].update(interval_seconds=1))
    # Rebind the changed receipt itself to exercise semantic checks beyond file hashing.
    change("acquisition.json", lambda value: value.update(acquisition_cleanup=rt.reference(root / "acquisition-supervision.json", root)))
    expected = v3_external_fixture(root)
    with pytest.raises(rt.BoundaryError) as caught:
        prep.check_acquired(root, expected)
    # These tests must exercise the existing internal validators, not fail early
    # merely because the newly required external fixture was missing or stale.
    assert not str(caught.value).startswith("external_")


@pytest.mark.parametrize("fault", ["publish", "rollback", "late-write", "late-flush", "short", "flush"])
def test_v3_finalization_faults_preserve_failure_and_reject_late_lock(tmp_path, monkeypatch, fault):
    clock = Clock(); root = tmp_path / "new"
    original = Path.rename
    def rename(path, target):
        if fault == "rollback" and path.name == "acquisition.json": raise OSError("synthetic rollback failure")
        result = original(path, target)
        if fault in {"publish", "rollback"} and path.name == "acquisition-pending.json": clock.now = 601
        return result
    monkeypatch.setattr(Path, "rename", rename)
    metadata_stream_fault(monkeypatch, "acquisition-pending.json", fault, clock)
    with pytest.raises((rt.BoundaryError, OSError)):
        v3_mocked_acquisition(root, monkeypatch, clock)
    assert (root / "acquisition-supervision-failure.json").exists()
    if fault == "rollback": assert (root / "acquisition.json").exists()
    else: assert not (root / "acquisition.json").exists()
    with pytest.raises(rt.BoundaryError, match="acquisition_finalization_failed"):
        prep.check_acquired(root, "0" * 64)


def test_v3_worker_write_os_deadline_and_no_refund_latch(tmp_path):
    clock = Clock(); budget = v3_budget(tmp_path, clock)
    path = tmp_path / "payload"; path.write_bytes(b"")
    class SlowWriter:
        name = str(path)
        def write(self, data):
            path.write_bytes(data); clock.now = 601; return len(data)
        def flush(self): pass
    with pytest.raises(rt.BoundaryError, match="preparation_budget") as caught:
        budget.write_chunk(SlowWriter(), b"partial")
    assert budget.written == 7 and path.read_bytes() == b"partial"
    clock.now = 0
    with pytest.raises(rt.BoundaryError) as repeated: budget.check()
    assert repeated.value is caught.value


def test_v3_phase_reraises_first_latch_after_caught_failure_and_later_error(tmp_path):
    budget = v3_budget(tmp_path)
    first = None
    with pytest.raises(rt.BoundaryError) as caught, budget.phase("sources"):
        budget.downloaded = rt.DOWNLOAD + 1
        try: budget.check()
        except rt.BoundaryError as error: first = error
        raise ValueError("later unrelated error")
    assert caught.value is first and budget.failure is first


def test_v3_direct_log_failure_latches_before_restored_state(tmp_path):
    budget = v3_budget(tmp_path)
    path = tmp_path / "acquisition-supervision.stdout"
    path.write_bytes(b"abc"); budget.log_growth(); path.write_bytes(b"a")
    with pytest.raises(rt.BoundaryError) as caught: budget.log_growth()
    path.write_bytes(b"abc")
    with pytest.raises(rt.BoundaryError) as repeated: budget.check()
    assert caught.value is repeated.value


def test_v3_attempt_counts_distinguish_failed_observation_without_catchup(tmp_path):
    clock = Clock(); ps = FakePS(tmp_path); budget = v3_budget(tmp_path, clock, ps)
    successful = budget.samples
    ps.fault = "observation"; clock.now = 0.075
    with pytest.raises(FakePS.AccessDenied): budget.check()
    record = budget.sampling("failure")
    assert record["sample_count_basis"] == "successful_resource_calls"
    assert record["sample_count"] == successful and record["attempted_sample_count"] == successful + 1
    assert record["maximum_observed_start_gap_seconds"] == 0.075
    assert budget.last_sample_start == 0


EXTERNAL_KEYS = {
    "acceptance": ["schema", "profile", "workspace", "attempt", "manifest", "stdout", "stderr", "observer_terminal", "custody", "sources"],
    "terminal": ["schema", "evidence_kind", "profile", "workspace", "attempt_sha256", "manifest_sha256", "stdout_sha256", "stderr_sha256", "argv", "observer", "cli", "sources_before", "sources_after", "exit_code", "terminal_observed", "elapsed_seconds", "budget_seconds", "cleanup_reserved_seconds", "limits_pass", "first_failure"],
    "custody": ["schema", "profile", "workspace", "attempt_sha256", "manifest_sha256", "observer_terminal_sha256", "identities", "all_absent", "errors"],
}


@pytest.fixture(scope="module")
def external_template(tmp_path_factory):
    """Produce one synthetic tree; external-only tests clone it, never reuse WORK."""
    root = tmp_path_factory.mktemp("external-template") / "new"
    with pytest.MonkeyPatch.context() as patch:
        v3_mocked_acquisition(root, patch)
        toolpins, llvm_sha = prep.pins(), prep.LLVM_SHA
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}, toolpins, llvm_sha


@pytest.fixture
def external_acquisition(external_template, monkeypatch):
    return clone_acquisition_template(external_template, monkeypatch)


def clone_acquisition_template(template, monkeypatch):
    files, toolpins, llvm_sha = template
    monkeypatch.setattr(prep, "pins", lambda: toolpins)
    monkeypatch.setattr(prep, "LLVM_SHA", llvm_sha)
    def clone(root):
        for name, data in files.items():
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        for name in ("acquisition-attempt.json", "acquisition-supervision.json"):
            path = root / name; row = rt.load(path); row["argv"][5] = str(root); path.write_text(json.dumps(row))
        lock = rt.load(root / "acquisition.json")
        lock["acquisition_cleanup"] = rt.reference(root / "acquisition-supervision.json", root)
        (root / "acquisition.json").write_text(json.dumps(lock))
        return lock
    return clone


@pytest.fixture(scope="module", params=[prep.ACQUISITION_PROFILE, prep.ACQUISITION_PROFILE_1800])
def duration_template(tmp_path_factory, request):
    root = tmp_path_factory.mktemp("duration-template") / "new"
    with pytest.MonkeyPatch.context() as patch:
        v3_mocked_acquisition(root, patch, profile=request.param)
        toolpins, llvm_sha = prep.pins(), prep.LLVM_SHA
    files = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    return request.param, (files, toolpins, llvm_sha)


@pytest.fixture
def duration_acquisition(duration_template, monkeypatch):
    profile, template = duration_template
    return profile, clone_acquisition_template(template, monkeypatch)


@pytest.mark.parametrize("profile,seconds", [(None, 600), (prep.ACQUISITION_PROFILE, 600), (prep.ACQUISITION_PROFILE_1800, 1800)])
def test_duration_worker_fixed_origin_phase_and_exact_deadline(tmp_path, profile, seconds):
    clock = Clock(); clock.now = 11
    budget = prep.Budget(tmp_path, ps=FakePS(tmp_path), clock=clock, acquisition_profile=profile)
    assert budget.end == 11 + seconds
    clock.now = 31
    with budget.phase("sources"):
        clock.now = 41
    events = [json.loads(row) for row in (tmp_path / "acquisition-phases.jsonl").read_text().splitlines()]
    assert [row["elapsed_seconds"] for row in events] == [20, 30]
    assert budget.end == 11 + seconds
    clock.now = budget.end - 0.001; budget.check()
    clock.now = budget.end
    with pytest.raises(rt.BoundaryError, match="preparation_budget") as caught: budget.check()
    if profile:
        clock.now = 12
        with pytest.raises(rt.BoundaryError) as repeated: budget.check(force="success-terminal")
        assert caught.value is repeated.value


@pytest.mark.parametrize("profile,seconds", [(None, 600), (prep.ACQUISITION_PROFILE, 600), (prep.ACQUISITION_PROFILE_1800, 1800)])
def test_duration_supervisor_uses_one_absolute_deadline_and_attempt(tmp_path, profile, seconds):
    clock = Clock(); clock.now = 17
    def runner(argv, **kwargs):
        assert kwargs["deadline"] == 17 + seconds
        attempt = rt.load(tmp_path / "new/acquisition-attempt.json")
        assert attempt["shared_seconds"] == seconds
        assert attempt.get("acquisition_profile") == profile
        clock.now += 100
        assert kwargs["deadline"] == 17 + seconds
        raise RuntimeError("synthetic stop")
    with pytest.raises(RuntimeError, match="synthetic stop"):
        prep.acquire_supervised(tmp_path / "new", runner=runner, clock=clock, acquisition_profile=profile)


@pytest.mark.parametrize("profile", [prep.ACQUISITION_PROFILE, prep.ACQUISITION_PROFILE_1800])
def test_duration_supervisor_reserves_last_five_seconds_and_keeps_cleanup(tmp_path, profile):
    seconds = prep.acquisition_seconds(profile)
    clock = Clock(); ps = FakePS(tmp_path, "timeout"); process = FakePopen(ps, clock)
    def jump(duration): clock.now = seconds - 5
    with pytest.raises(rt.BoundaryError) as caught:
        rt.run_owned([], cwd=tmp_path, env=rt.clean_environment([], tmp_path, "tmp"), root=tmp_path,
                     log_prefix=tmp_path / "run", deadline=seconds, rss=100, host=1, start=1,
                     allowed=[tmp_path / "root.exe", tmp_path / "child.exe"], ps=ps,
                     popen=lambda *a, **k: process, clock=clock, sleeper=jump, acquisition_profile=profile)
    record = caught.value.supervision_record
    assert record["failure_latched"] and record["cleanup"]["all_absent"]
    assert record["acquisition_profile"] == profile and seconds - 5 <= clock.now <= seconds
    assert set(ps.killed) <= {10, 20}


@pytest.mark.parametrize("profile", ["", "unknown", "llvm-x64-sampled-50ms-1801s-v1", "1800", 1800])
def test_duration_unknown_profile_rejected_before_creation(tmp_path, profile):
    with pytest.raises(rt.BoundaryError, match="acquisition_profile"):
        prep.acquire_supervised(tmp_path / "new", acquisition_profile=profile)
    assert not (tmp_path / "new").exists()


def test_duration_arbitrary_cli_seconds_not_available(tmp_path, monkeypatch):
    monkeypatch.setattr(prep.sys, "argv", ["prepare", "acquire", "--workspace", str(tmp_path / "new"), "--acquisition-seconds", "1800"])
    with pytest.raises(SystemExit) as caught: prep.main()
    assert caught.value.code == 2 and not (tmp_path / "new").exists()


@pytest.mark.parametrize("profile", [prep.ACQUISITION_PROFILE, prep.ACQUISITION_PROFILE_1800])
@pytest.mark.parametrize("fault", ["other-duration", "float-duration"])
def test_duration_worker_rejects_mixed_attempt_before_budget(tmp_path, monkeypatch, profile, fault):
    token = "synthetic-token"
    seconds = prep.acquisition_seconds(profile)
    invalid = (1800 if seconds == 600 else 600) if fault == "other-duration" else float(seconds)
    argv = [prep.sys.executable, "-B", str(Path(prep.__file__).resolve()), "_acquire-worker", "--workspace", str(tmp_path), "--worker-token", token, "--acquisition-profile", profile]
    rt.write(tmp_path / "acquisition-attempt.json", {"worker_token": token, "argv": argv, "acquisition_profile": profile, "shared_seconds": invalid})
    monkeypatch.setenv("DOCTRAIL_ACQUIRE_TOKEN", token)
    with pytest.raises(rt.BoundaryError, match="worker_duration_binding"):
        prep.acquire(tmp_path, worker_token=token, acquisition_profile=profile,
                     budget_factory=lambda *args, **kwargs: pytest.fail("budget must not start"))


def test_duration_complete_lock_and_selection_policy_are_distinct(tmp_path, duration_acquisition):
    profile, clone = duration_acquisition
    root = tmp_path / "new"; lock = clone(root)
    expected = v3_external_fixture(root, profile=profile)
    assert prep.check_acquired(root, expected) == lock
    assert lock["acquisition_profile"] == profile
    assert lock["tools"][0]["selection"]["policy"] == prep.ACQUISITION_PROFILE
    assert lock["tools"][0]["selection"]["selected_entries"] == 16


@pytest.mark.parametrize("fault", ["attempt-seconds", "attempt-float", "attempt-profile", "raw-profile", "manifest-profile", "supervision-profile", "worker-profile", "sampling-profile", "latch"])
def test_duration_mixed_internal_records_rejected(tmp_path, duration_acquisition, fault):
    profile, clone = duration_acquisition
    root = tmp_path / "new"; clone(root)
    other = prep.ACQUISITION_PROFILE_1800 if profile == prep.ACQUISITION_PROFILE else prep.ACQUISITION_PROFILE
    def change(name, action):
        path = root / name; value = rt.load(path); action(value); path.write_text(json.dumps(value))
    if fault == "attempt-seconds": change("acquisition-attempt.json", lambda row: row.update(shared_seconds=prep.acquisition_seconds(other)))
    elif fault == "attempt-float": change("acquisition-attempt.json", lambda row: row.update(shared_seconds=float(prep.acquisition_seconds(profile))))
    elif fault == "attempt-profile": change("acquisition-attempt.json", lambda row: row.update(acquisition_profile=other))
    elif fault == "raw-profile": change("raw-acquisition.json", lambda row: row.update(acquisition_profile=other))
    elif fault == "manifest-profile": change("acquisition.json", lambda row: row.update(acquisition_profile=other))
    elif fault == "supervision-profile": change("acquisition-supervision.json", lambda row: row.update(acquisition_profile=other))
    elif fault == "worker-profile": change("worker-terminal.json", lambda row: row.update(profile=other))
    elif fault == "sampling-profile":
        for name in ("raw-acquisition.json", "acquisition.json"):
            change(name, lambda row: row["worker_sampling"].update(profile=other))
    else: change("acquisition-supervision.json", lambda row: row.update(failure_latched=True))
    change("acquisition.json", lambda row: row.update(acquisition_cleanup=rt.reference(root / "acquisition-supervision.json", root), worker_terminal=rt.reference(root / "worker-terminal.json", root)))
    with pytest.raises(rt.BoundaryError): prep.check_acquired(root, v3_external_fixture(root, profile=profile))


@pytest.mark.parametrize("fault", [None, "late", "other-budget", "float-budget", "acceptance-profile", "terminal-profile", "custody-profile", "not-terminal"])
def test_duration_external_exact_boundary_and_mixed_policy_rejected(tmp_path, duration_acquisition, fault):
    profile, clone = duration_acquisition
    root = tmp_path / "new"; clone(root)
    seconds = prep.acquisition_seconds(profile)
    other = prep.ACQUISITION_PROFILE_1800 if profile == prep.ACQUISITION_PROFILE else prep.ACQUISITION_PROFILE
    def mutate(at, row):
        if at == "terminal":
            row["elapsed_seconds"] = seconds
            if fault == "late": row["elapsed_seconds"] += 0.001
            elif fault == "other-budget": row["budget_seconds"] = prep.acquisition_seconds(other)
            elif fault == "float-budget": row["budget_seconds"] = float(seconds)
            elif fault == "not-terminal": row["terminal_observed"] = False
        if fault == at + "-profile": row["profile"] = other
    expected = v3_external_fixture(root, mutate, profile)
    if fault:
        with pytest.raises(rt.BoundaryError): prep.check_acquired(root, expected)
    else:
        assert prep.check_acquired(root, expected)["acquisition_profile"] == profile


@pytest.mark.parametrize("kind,key", [(kind, key) for kind, keys in EXTERNAL_KEYS.items() for key in keys] + [(kind, "extra") for kind in EXTERNAL_KEYS])
def test_external_exact_top_level_schema(tmp_path, monkeypatch, external_acquisition, kind, key):
    root = tmp_path / "new"; external_acquisition(root)
    def mutate(at, value):
        if at == kind:
            if key == "extra": value[key] = None
            else: value.pop(key)
    expected = v3_external_fixture(root, mutate)
    with pytest.raises(rt.BoundaryError, match="external_schema"):
        prep.check_acquired(root, expected)



@pytest.mark.parametrize("kind,key,value", [
    ("acceptance", "schema", "other"), ("acceptance", "profile", None), ("acceptance", "workspace", "/other"),
    ("terminal", "evidence_kind", "synthetic"), ("terminal", "evidence_kind", "self_reported"),
    ("terminal", "evidence_kind", "pending"), ("terminal", "evidence_kind", "unknown"),
    ("terminal", "schema", "other"), ("terminal", "profile", None), ("terminal", "workspace", "/other"),
    *[("terminal", key, "0" * 64) for key in ("attempt_sha256", "manifest_sha256", "stdout_sha256", "stderr_sha256")],
    ("terminal", "argv", []), ("terminal", "exit_code", 1), ("terminal", "exit_code", False),
    ("terminal", "terminal_observed", False), ("terminal", "terminal_observed", 1),
    ("terminal", "limits_pass", False), ("terminal", "limits_pass", 1), ("terminal", "first_failure", "shared_deadline"),
    *[("terminal", "elapsed_seconds", value) for value in (-1, 601, True, "4", None, float("nan"), float("inf"), -float("inf"))],
    ("terminal", "budget_seconds", 601), ("terminal", "budget_seconds", 600.0),
    ("terminal", "cleanup_reserved_seconds", 6), ("terminal", "cleanup_reserved_seconds", 5.0),
    ("terminal", "sources_before", []), ("terminal", "sources_after", []),
    ("custody", "schema", "other"), ("custody", "profile", None), ("custody", "workspace", "/other"),
    *[("custody", key, "0" * 64) for key in ("attempt_sha256", "manifest_sha256", "observer_terminal_sha256")],
    ("custody", "all_absent", False), ("custody", "all_absent", 1), ("custody", "errors", ["unknown"]),
    ("custody", "identities", []), ("acceptance", "sources", []),
])
def test_external_bound_fields_reject_self_asserted_bad_evidence(tmp_path, monkeypatch, external_acquisition, kind, key, value):
    root = tmp_path / "new"; external_acquisition(root)
    expected = v3_external_fixture(root, lambda at, row: row.update({key: value}) if at == kind else None)
    with pytest.raises((rt.BoundaryError, ValueError)):
        prep.check_acquired(root, expected)



@pytest.mark.parametrize("role", ["attempt", "manifest", "stdout", "stderr", "observer_terminal", "custody", "source"])
@pytest.mark.parametrize("fault", ["extra", "missing", "absolute", "parent", "backslash", "case", "alias", "role", "size-bool", "size-negative", "size-wrong", "sha-upper", "sha-wrong"])
def test_external_reference_schema_names_and_bytes(tmp_path, monkeypatch, external_acquisition, role, fault):
    root = tmp_path / "new"; external_acquisition(root)
    def mutate(at, row):
        if at != "acceptance": return
        ref = row["sources"][0] if role == "source" else row[role]
        if fault == "extra": ref["extra"] = 0
        elif fault == "missing": ref.pop("sha256")
        elif fault == "absolute": ref["file"] = str(root / "acquisition.json")
        elif fault == "parent": ref["file"] = "../" + ref["file"]
        elif fault == "backslash": ref["file"] = "other\\" + ref["file"]
        elif fault == "case": ref["file"] = ref["file"].upper()
        elif fault == "alias": ref["file"] += ". "
        elif fault == "role": ref["file"] = "cli.stdout"
        elif fault == "size-bool": ref["size_bytes"] = True
        elif fault == "size-negative": ref["size_bytes"] = -1
        elif fault == "size-wrong": ref["size_bytes"] += 1
        elif fault == "sha-upper": ref["sha256"] = "A" * 64
        elif fault == "sha-wrong": ref["sha256"] = "0" * 64
    if role == "stdout" and fault == "role":
        # A role cannot alias another role even if its own basename is valid.
        fault = "parent"
    expected = v3_external_fixture(root, mutate)
    with pytest.raises(rt.BoundaryError): prep.check_acquired(root, expected)



@pytest.mark.parametrize("kind", ["observer", "cli", "custody"])
@pytest.mark.parametrize("fault", ["extra", "missing", "pid-bool", "pid-zero", "time-bool", "time-zero", "time-infinite", "relative", "alias"])
def test_external_identity_strict_schema_and_types(tmp_path, monkeypatch, external_acquisition, kind, fault):
    root = tmp_path / "new"; external_acquisition(root)
    def mutate(at, row):
        if at != ("custody" if kind == "custody" else "terminal"): return
        ident = row["identities"][0] if kind == "custody" else row[kind]
        if fault == "extra": ident["unknown"] = True
        elif fault == "missing": ident.pop("pid")
        elif fault == "pid-bool": ident["pid"] = True
        elif fault == "pid-zero": ident["pid"] = 0
        elif fault == "time-bool": ident["create_time"] = True
        elif fault == "time-zero": ident["create_time"] = 0
        elif fault == "time-infinite": ident["create_time"] = float("inf")
        elif fault == "relative": ident["executable"] = "python.exe"
        elif fault == "alias": ident["executable"] = str(Path(ident["executable"]).parent / ".." / "python.exe")
    expected = v3_external_fixture(root, mutate)
    with pytest.raises(rt.BoundaryError): prep.check_acquired(root, expected)



@pytest.mark.parametrize("fault", ["duplicate", "observer", "missing-cli", "missing-worker", "reused-cli", "present", "unknown", "too-many", "observer-is-cli", "observer-sha", "wrong-executable", "worker-argv", "source-before", "source-after", "source-order"])
def test_external_ownership_and_before_after_binding(tmp_path, monkeypatch, external_acquisition, fault):
    root = tmp_path / "new"; external_acquisition(root)
    def mutate(at, row):
        if at == "terminal":
            if fault == "observer-is-cli": row["observer"].update(row["cli"])
            elif fault == "observer-sha": row["observer"]["source_sha256"] = "not-sha"
            elif fault == "wrong-executable": row["cli"]["executable"] = prep.os.path.normcase(str((root / "other.exe").resolve()))
            elif fault == "worker-argv": row["argv"][3] = "_acquire-worker"
            elif fault == "source-before": row["sources_before"] = [{**ref, "sha256": "0" * 64} for ref in row["sources_before"]]
            elif fault == "source-after": row["sources_after"] = [{**ref, "size_bytes": True} for ref in row["sources_after"]]
        elif at == "custody":
            rows = row["identities"]
            if fault == "duplicate": rows.append(dict(rows[0]))
            elif fault == "observer": rows.append({**rows[0], "pid": 100, "create_time": 1.0})
            elif fault == "missing-cli": rows.pop(0)
            elif fault == "missing-worker": rows.pop()
            elif fault == "reused-cli": rows[0]["create_time"] = 1000.0
            elif fault == "present": rows[0]["absent"] = False
            elif fault == "unknown": rows[0]["absent"] = "unknown"
            elif fault == "too-many": rows.extend([{**rows[1], "pid": n + 300} for n in range(127)])
        elif at == "acceptance" and fault == "source-order": row["sources"].reverse()
    expected = v3_external_fixture(root, mutate)
    with pytest.raises(rt.BoundaryError): prep.check_acquired(root, expected)



@pytest.mark.parametrize("raw", [b'', b'{"status": "ACQUIRED_UNREVIEWED_DO_NOT_EXECUTE"}', b'{}\n',
    b'{"status":"ACQUIRED_UNREVIEWED_DO_NOT_EXECUTE"}\n', b'prefix\n{"status": "ACQUIRED_UNREVIEWED_DO_NOT_EXECUTE"}\n',
    b'{"status": "ACQUIRED_UNREVIEWED_DO_NOT_EXECUTE"}\n\n', b'{"status": "ACQUIRED_UNREVIEWED_DO_NOT_EXECUTE"}\n' * 2])
def test_external_stdout_is_exact_original_protocol(tmp_path, monkeypatch, external_acquisition, raw):
    root = tmp_path / "new"; external_acquisition(root)
    folder = root.with_name(root.name + ".external-review")
    def mutate(at, row):
        if at == "terminal":
            (folder / "cli.stdout").write_bytes(raw)
            row["stdout_sha256"] = rt.digest(raw)
        elif at == "acceptance": row["stdout"] = rt.reference(folder / "cli.stdout", folder)
    expected = v3_external_fixture(root, mutate)
    with pytest.raises(rt.BoundaryError, match="external_stdout_protocol"): prep.check_acquired(root, expected)



@pytest.mark.parametrize("fault", ["missing", "manifest-sha", "wrong-sha", "self-marker", "strip-profiles"])
def test_external_digest_is_never_automatically_approved_or_legacy_fallback(tmp_path, monkeypatch, external_acquisition, fault):
    root = tmp_path / "new"; external_acquisition(root)
    if fault in {"manifest-sha", "wrong-sha"}: v3_external_fixture(root)
    if fault == "self-marker": (root / "success.json").write_text('{"success":true}')
    if fault == "strip-profiles":
        for name in ("acquisition.json", "raw-acquisition.json", "acquisition-attempt.json", "acquisition-supervision.json"):
            path = root / name; value = rt.load(path); value.pop("acquisition_profile"); path.write_text(json.dumps(value))
        lock = rt.load(root / "acquisition.json")
        lock["acquisition_cleanup"] = rt.reference(root / "acquisition-supervision.json", root)
        (root / "acquisition.json").write_text(json.dumps(lock))
    expected = "0" * 64 if fault == "wrong-sha" else rt.digest((root / "acquisition.json").read_bytes())
    with pytest.raises(rt.BoundaryError, match="external_"): prep.check_acquired(root, expected)



@pytest.mark.parametrize("fault", ["extra-file", "extra-directory", "case-alias", "other-root", "hardlink", "reparse"])
def test_external_sibling_and_reference_path_boundaries(tmp_path, monkeypatch, external_acquisition, fault):
    root = tmp_path / "new"; external_acquisition(root)
    expected = v3_external_fixture(root); folder = root.with_name(root.name + ".external-review")
    if fault == "extra-file": (folder / "extra").write_bytes(b'')
    elif fault == "extra-directory": (folder / "extra").mkdir()
    elif fault == "case-alias": (folder / "acceptance.json").rename(folder / "Acceptance.json")
    elif fault == "other-root": folder.rename(tmp_path / "different.external-review")
    elif fault == "hardlink":
        # Model equal filesystem identities: Windows restricted environments
        # need not permit creating a real hardlink for this pure boundary test.
        (folder / "cli.stderr").write_bytes((folder / "cli.stdout").read_bytes())
        acceptance = rt.load(folder / "acceptance.json"); acceptance["stderr"] = rt.reference(folder / "cli.stderr", folder)
        (folder / "acceptance.json").write_text(json.dumps(acceptance)); expected = rt.digest((folder / "acceptance.json").read_bytes())
        original_stat = Path.stat
        def same_identity(path, *args, **kwargs):
            return original_stat(folder / "cli.stdout" if path == folder / "cli.stderr" else path, *args, **kwargs)
        monkeypatch.setattr(Path, "stat", same_identity)
    elif fault == "reparse":
        original = Path.lstat
        def lstat(path, *args, **kwargs):
            if path == folder: return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=1024)
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(rt.BoundaryError) as caught: prep.check_acquired(root, expected)
    if fault == "hardlink": assert str(caught.value) == "external_file_alias"



def test_external_orphan_compound_finalization_failure_has_no_acceptance(tmp_path, monkeypatch):
    root = tmp_path / "new"; clock = Clock(); original = Path.rename; write_metadata = prep.write_metadata
    def rename(path, target):
        if path.name == "acquisition.json": raise OSError("synthetic rollback failure")
        result = original(path, target)
        if path.name == "acquisition-pending.json": clock.now = 601
        return result
    def write(root, path, *args, **kwargs):
        if path.name == "acquisition-supervision-failure.json": raise OSError("synthetic marker failure")
        return write_metadata(root, path, *args, **kwargs)
    monkeypatch.setattr(Path, "rename", rename); monkeypatch.setattr(prep, "write_metadata", write)
    with pytest.raises(rt.BoundaryError, match="shared_deadline") as caught: v3_mocked_acquisition(root, monkeypatch, clock)
    assert len(caught.value.__notes__) == 2
    assert (root / "acquisition.json").exists()
    assert not (root / "acquisition-pending.json").exists() and not (root / "acquisition-supervision-failure.json").exists()
    with pytest.raises(rt.BoundaryError, match="external_acceptance_missing"):
        prep.check_acquired(root, rt.digest((root / "acquisition.json").read_bytes()))
    expected = v3_external_fixture(root, lambda at, row: row.update(exit_code=1, elapsed_seconds=601, first_failure="shared_deadline") if at == "terminal" else None)
    with pytest.raises(rt.BoundaryError, match="external_terminal_failed"): prep.check_acquired(root, expected)


@pytest.mark.parametrize("name,limit", [("acceptance.json", 64 * 1024), ("observer-terminal.json", 128 * 1024),
    ("custody.json", 256 * 1024), ("cli.stdout", 4 * 1024), ("cli.stderr", 8 * 1024**2),
    ("acquisition-attempt.json", 16 * 1024), ("acquisition.json", 16 * 1024**2),
    ("prepare.py", 256 * 1024), ("runtime.py", 128 * 1024), ("pins.json", 32 * 1024)])
def test_external_reads_are_bounded_before_open_and_during_read(tmp_path, monkeypatch, name, limit):
    path = tmp_path / name; path.write_bytes(b'x' * (limit + 1))
    original = Path.open
    def forbidden(path, *args, **kwargs): raise AssertionError("oversize file must not be opened")
    monkeypatch.setattr(Path, "open", forbidden)
    with pytest.raises(rt.BoundaryError, match="external_read_limit"): prep.external_read(tmp_path, name, limit, set())
    monkeypatch.setattr(Path, "open", original); path.write_bytes(b'x' * limit)
    calls = []
    class Tracking:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self
        def __exit__(self, *args): self.stream.close()
        def fileno(self): return self.stream.fileno()
        def read(self, size): calls.append(size); return self.stream.read(size)
    monkeypatch.setattr(Path, "open", lambda path, *args, **kwargs: Tracking(original(path, *args, **kwargs)))
    assert prep.external_read(tmp_path, name, limit, set()) == b'x' * limit
    assert all(0 < size <= 65536 for size in calls)


@pytest.mark.parametrize("fault", ["growth", "short", "changed-stat", "observation"])
def test_external_read_rejects_observed_races_and_io_errors(tmp_path, monkeypatch, fault):
    path = tmp_path / "record"; path.write_bytes(b'abcd'); original = Path.open
    class Faulty:
        def __init__(self, stream): self.stream = stream; self.calls = 0
        def __enter__(self): return self
        def __exit__(self, *args): self.stream.close()
        def fileno(self): return self.stream.fileno()
        def read(self, size):
            self.calls += 1
            if fault == "observation": raise OSError("synthetic read failure")
            if fault == "growth": return b'x' * 5
            if fault == "short": return b''
            data = self.stream.read(size)
            if self.calls == 1:
                with original(path, "ab") as out: out.write(b'x')
            return data
    monkeypatch.setattr(Path, "open", lambda path, *args, **kwargs: Faulty(original(path, *args, **kwargs)))
    with pytest.raises((rt.BoundaryError, OSError)): prep.external_read(tmp_path, "record", 4, set())


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"outer":{"a":1,"a":2}}', b'{"x":NaN}', b'{"x":Infinity}',
    b'{"x":-Infinity}', b'\xff', '{}'.encode('utf-16'), b'{} garbage'])
def test_external_json_rejects_duplicates_nonfinite_and_non_utf8(raw):
    with pytest.raises((rt.BoundaryError, ValueError)): prep.external_json(raw)


@pytest.mark.parametrize("fault", ["companion", "manifest", "stdout", "source-ref", None])
def test_external_build_double_check_and_verifier_review_artifact_forwarding(tmp_path, monkeypatch, external_acquisition, fault):
    monkeypatch.delenv("SystemRoot", raising=False)
    root = tmp_path / "new"; external_acquisition(root)
    expected = v3_external_fixture(root); folder = root.with_name(root.name + ".external-review")
    calls, checks = [], []
    check = prep.check_acquired
    def checked(where, sha):
        checks.append(sha)
        return check(where, sha)
    monkeypatch.setattr(prep, "check_acquired", checked)
    def runner(argv, **kwargs):
        calls.append(argv)
        prefix = kwargs["log_prefix"]
        for ext in (".stdout", ".stderr"): Path(str(prefix) + ext).write_bytes(b'')
        rt.write(Path(str(prefix) + ".json"), {"cleanup": {"all_absent": True, "errors": [], "identities": []}})
        if len(calls) == 1:
            (root / "configure-trace.jsonl").write_text(json.dumps({"cmd": "execute_process", "args": ["COMMAND", str(argv[0]), "--version"]}) + "\n")
        else:
            target = root / "build/bin"; target.mkdir(parents=True); (target / "summary-grammar-validator.exe").write_bytes(b'not-executable')
            if fault == "companion": (folder / "acceptance.json").write_bytes(b'{}')
            elif fault == "manifest": (root / "acquisition.json").write_bytes(b'{}')
            elif fault == "stdout": (folder / "cli.stdout").write_bytes(b'{}\n')
            elif fault == "source-ref":
                acceptance = rt.load(folder / "acceptance.json"); acceptance["sources"][0]["sha256"] = "0" * 64
                (folder / "acceptance.json").write_text(json.dumps(acceptance))
        return {}
    if fault:
        with pytest.raises(rt.BoundaryError, match="external_"): prep.build(root, expected, runner=runner, clock=lambda: 0)
        assert not (root / "build-manifest.json").exists()
    else:
        result = prep.build(root, expected, runner=runner, clock=lambda: 0)
        assert result["acquisition_sha256"] == expected
        assert rt.load(root / "build-attempt.json")["acquisition_sha256"] == expected
        assert check(root, expected)["schema_version"] == 2  # Build additions are permitted.
        class Forwarded(Exception): pass
        def verifier_gate(where, sha):
            assert sha == expected and check(where, sha)["schema_version"] == 2
            raise Forwarded("stop before any verification/native work")
        monkeypatch.setattr(verify, "check_acquired", verifier_gate)
        with pytest.raises(Forwarded): verify.verify(root, rt.digest((root / "build-manifest.json").read_bytes()))
    assert checks == [expected, expected] and len(calls) == 2



def test_external_valid_crlf_boundary_time_and_unprovable_observer_truth(tmp_path, monkeypatch, external_acquisition):
    root = tmp_path / "new"; result = external_acquisition(root)
    folder = root.with_name(root.name + ".external-review")
    def mutate(at, row):
        if at == "terminal":
            raw = b'{"status": "ACQUIRED_UNREVIEWED_DO_NOT_EXECUTE"}\r\n'
            (folder / "cli.stdout").write_bytes(raw); row["stdout_sha256"] = rt.digest(raw); row["elapsed_seconds"] = 600
        elif at == "acceptance": row["stdout"] = rt.reference(folder / "cli.stdout", folder)
    expected = v3_external_fixture(root, mutate)
    # Deliberately synthetic claims can pass structure if a caller supplies their
    # digest. This demonstrates the external-review trust boundary, not approval.
    assert prep.check_acquired(root, expected) == result

def test_duration_external_and_internal_profiles_cannot_diverge(tmp_path, duration_acquisition):
    profile, clone = duration_acquisition
    root = tmp_path / "new"; clone(root)
    other = prep.ACQUISITION_PROFILE_1800 if profile == prep.ACQUISITION_PROFILE else prep.ACQUISITION_PROFILE
    expected = v3_external_fixture(root, profile=other)
    with pytest.raises(rt.BoundaryError, match="acquisition_profile_binding"):
        prep.check_acquired(root, expected)

@pytest.mark.parametrize("entry_type,mode,path,error", [
    ("blob", "120000", "src/link.h", "source_type"),
    ("commit", "160000", "src/submodule", "source_type"),
    ("blob", "160000", "src/invalid.h", "source_type"),
    ("blob", "100664", "src/invalid.h", "source_type"),
    ("unknown", "100755", "src/invalid.h", "source_type"),
    (None, "100755", "src/invalid.h", "source_type"),
    (["blob"], "100755", "src/invalid.h", "source_type"),
    ("blob", None, "src/invalid.h", "source_type"),
    ("blob", 100755, "src/invalid.h", "source_type"),
    ("blob", ["100755"], "src/invalid.h", "source_type"),
    ("blob", {"mode": "100755"}, "src/invalid.h", "source_type"),
    ("blob", "100755", "src/weights.gguf", "source_payload"),
])
def test_source_modes_reject_before_entry_fetch(tmp_path, monkeypatch, entry_type, mode, path, error):
    root = tmp_path / "owned"
    api = "https://api.github.com/repos/ggml-org/llama.cpp/git/"
    urls = {
        api + "commits/" + rt.COMMIT: json.dumps({"sha": rt.COMMIT, "tree": {"sha": "a" * 40}}).encode(),
        api + "trees/" + "a" * 40 + "?recursive=1": json.dumps({"sha": "a" * 40, "truncated": False,
            "tree": [{"path": path, "type": entry_type, "mode": mode, "size": 1, "sha": "0" * 40}]}).encode(),
    }
    fetched = []
    def opened(request, **kwargs):
        fetched.append(request.full_url)
        assert request.full_url in urls, "invalid entry must be rejected before fetch"
        return Response(urls[request.full_url])
    monkeypatch.setattr(prep, "pins", lambda: {"tools": []})
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("no native execution"))
    with pytest.raises(rt.BoundaryError, match=error):
        prep.acquire(root, opener=SimpleNamespace(open=opened), budget_factory=FakeBudget)
    assert fetched == list(urls)
    assert not any((root / "source").iterdir())
    assert rt.load(root / "acquisition-failure.json")["reason"] == error
    assert not (root / "acquisition.json").exists()

# Real stdlib HTTPResponse framing over fake sockets; never contact a server.
def source_http_wire(body=b"data", status=200, headers=()):
    values = list(headers)
    if not any(key.lower() in {"content-length", "transfer-encoding"} for key, _ in values):
        values.append(("Content-Length", str(len(body))))
    return (f"HTTP/1.1 {status} synthetic\r\n" + "".join(f"{key}: {value}\r\n" for key, value in values) + "\r\n").encode() + body


def source_https_connections(monkeypatch, responses, fault=None):
    connections, requests, bodies = [], [], []
    queue = list(responses)
    class Socket:
        def __init__(self, stream=None): self.stream, self.timeouts = stream, []
        def makefile(self, mode): return self.stream
        def settimeout(self, value): self.timeouts.append(value)
    class Connection:
        def __init__(self, host, *, port, timeout):
            assert port == 443  # No custom TLS context disabling normal verification.
            self.host, self.timeout, self.closed = host, timeout, False
            self.sock = Socket(); connections.append(self)
        def request(self, method, target, *, headers):
            assert method == "GET" and not self.closed
            assert not any(key.lower() in {"authorization", "proxy-authorization"} for key in headers)
            requests.append((self.host, target, self.timeout))
            if fault == "request": raise OSError("synthetic socket failure")
        def getresponse(self):
            if fault == "response": raise prep.http.client.RemoteDisconnected("synthetic disconnect")
            body = DispatchBody(queue.pop(0)); bodies.append(body)
            response = prep.http.client.HTTPResponse(Socket(body)); response.begin()
            if fault == "read":
                def failed(size): raise OSError("synthetic TLS read failure")
                response.read = failed
            return response
        def close(self): self.closed = True
    monkeypatch.setattr(prep.http.client, "HTTPSConnection", Connection)
    return connections, requests, bodies


def test_source_https_reuses_one_connection_and_charges_exact_bodies(tmp_path, monkeypatch):
    import hashlib
    payloads = [b"a" * 70000, b"second"]
    connections, requests, bodies = source_https_connections(monkeypatch, [source_http_wire(x) for x in payloads])
    budget = FakeBudget(tmp_path)
    with prep.SourceHTTPS() as opener:
        for index, body in enumerate(payloads):
            path = tmp_path / str(index)
            assert prep.fetch(f"https://raw.githubusercontent.com/source/{index}", path, budget,
                              expected=rt.digest(body), max_bytes=len(body), opener=opener) == rt.digest(body)
            assert hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + path.read_bytes()).digest() == hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).digest()
        assert len(connections) == 1 and not connections[0].closed
    assert connections[0].closed and len(requests) == 2 and budget.downloaded == sum(map(len, payloads))
    assert all(body.closed and all(0 < size <= 65536 for size in body.reads) for body in bodies)


def test_source_https_server_close_reconnects_only_for_next_file(tmp_path, monkeypatch):
    connections, requests, _ = source_https_connections(monkeypatch, [source_http_wire(headers=[("Connection", "close")]), source_http_wire()])
    with prep.SourceHTTPS() as opener:
        for index in range(2): prep.fetch(f"https://github.com/{index}", tmp_path / str(index), FakeBudget(tmp_path), opener=opener)
    assert len(connections) == len(requests) == 2 and all(c.closed for c in connections)
    assert [r[1] for r in requests] == ["/0", "/1"]


@pytest.mark.parametrize("location,valid", [("https://raw.githubusercontent.com/next", True), ("https://evil.test/next", False),
    ("http://github.com/next", False), ("https://u@github.com/next", False), ("https://github.com:444/next", False)])
def test_source_https_redirects_discard_unread_connection(tmp_path, monkeypatch, location, valid):
    connections, requests, bodies = source_https_connections(monkeypatch, [source_http_wire(b"never consumed", 302, [("Location", location)]), source_http_wire()])
    budget = FakeBudget(tmp_path)
    with prep.SourceHTTPS() as opener:
        if valid: prep.fetch("https://github.com/start", tmp_path / "out", budget, opener=opener)
        else:
            with pytest.raises(rt.BoundaryError): prep.fetch("https://github.com/start", tmp_path / "out", budget, opener=opener)
    assert len(requests) == len(connections) == (2 if valid else 1)
    assert all(c.closed for c in connections) and bodies[0].reads == [] and bodies[0].closed
    assert budget.downloaded == (4 if valid else 0)


@pytest.mark.parametrize("fault", ["truncated", "malformed-length", "duplicate-length", "ambiguous-framing", "chunked-truncated", "error-status", "oversize", "request", "response", "read"])
def test_source_https_faults_close_and_never_replay(tmp_path, monkeypatch, fault):
    wire = source_http_wire()
    if fault == "truncated": wire = source_http_wire(b"abc", headers=[("Content-Length", "10")])
    elif fault == "malformed-length": wire = source_http_wire(headers=[("Content-Length", "invalid")])
    elif fault == "duplicate-length": wire = source_http_wire(headers=[("Content-Length", "4"), ("Content-Length", "4")])
    elif fault == "ambiguous-framing": wire = source_http_wire(headers=[("Content-Length", "4"), ("Transfer-Encoding", "chunked")])
    elif fault == "chunked-truncated": wire = source_http_wire(b"3\r\nab", headers=[("Transfer-Encoding", "chunked")])
    elif fault == "error-status": wire = source_http_wire(b"discarded", 500)
    connections, requests, bodies = source_https_connections(monkeypatch, [wire], fault)
    budget = FakeBudget(tmp_path)
    with prep.SourceHTTPS() as opener:
        with pytest.raises((rt.BoundaryError, OSError, prep.http.client.HTTPException)):
            prep.fetch("https://github.com/file", tmp_path / "out", budget, max_bytes=2 if fault == "oversize" else 100, opener=opener)
        assert opener.connection is None
    assert len(connections) == len(requests) == 1 and connections[0].closed and all(b.closed for b in bodies)
    if fault in {"malformed-length", "duplicate-length", "ambiguous-framing", "error-status"}: assert bodies[0].reads == []
    if fault == "oversize": assert budget.downloaded == 3


def test_source_https_early_close_discards_without_drain(tmp_path, monkeypatch):
    connections, requests, bodies = source_https_connections(monkeypatch, [source_http_wire(b"unread")])
    with prep.SourceHTTPS() as opener:
        response = prep.open_download("https://github.com/file", FakeBudget(tmp_path), opener)
        response.close()
        assert opener.connection is None
    assert len(requests) == 1 and connections[0].closed and bodies[0].reads == []


def test_source_https_remaining_deadline_updates_reused_socket(tmp_path, monkeypatch):
    connections, requests, _ = source_https_connections(monkeypatch, [source_http_wire(), source_http_wire()])
    clock = Clock(); budget = prep.Budget(tmp_path, ps=FakePS(tmp_path), clock=clock)
    with prep.SourceHTTPS() as opener:
        clock.now = 597
        prep.fetch("https://github.com/one", tmp_path / "one", budget, opener=opener)
        clock.now = 599
        prep.fetch("https://github.com/two", tmp_path / "two", budget, opener=opener)
        clock.now = 600
        with pytest.raises(rt.BoundaryError): prep.fetch("https://github.com/expired", tmp_path / "three", budget, opener=opener)
    assert len(connections) == 1 and [r[2] for r in requests] == [3, 1]
    assert connections[0].sock.timeouts == [3, 1] and connections[0].closed


def test_source_https_preserves_phase_error_if_close_fails(monkeypatch):
    opener = prep.SourceHTTPS()
    monkeypatch.setattr(opener, "close", lambda: (_ for _ in ()).throw(OSError("close failed")))
    error = rt.BoundaryError("first failure")
    with pytest.raises(rt.BoundaryError) as caught, opener:
        raise error
    assert caught.value is error and error.__notes__ == ["source_https_close_failed:OSError"]

@pytest.mark.parametrize("rejection", ["status", "redirect"])
@pytest.mark.parametrize("closing", ["raw", "connection"])
def test_source_https_close_preserves_open_download_rejection(tmp_path, monkeypatch, rejection, closing):
    wire = source_http_wire(b"unread", 500) if rejection == "status" else source_http_wire(b"unread", 302, [("Location", "https://evil.test/file")])
    connections, requests, bodies = source_https_connections(monkeypatch, [wire])
    original_response = prep.http.client.HTTPSConnection.getresponse
    original_close = prep.http.client.HTTPSConnection.close
    cleanup_error = OSError("synthetic disposal failure")
    disposal = []
    def close_connection(connection):
        disposal.append("connection"); original_close(connection)
        if closing == "connection": raise cleanup_error
    def getresponse(connection):
        raw = original_response(connection); original = raw.close
        def close_raw():
            disposal.append("raw"); original()
            if closing == "raw": raise cleanup_error
        raw.close = close_raw
        return raw
    monkeypatch.setattr(prep.http.client.HTTPSConnection, "close", close_connection)
    monkeypatch.setattr(prep.http.client.HTTPSConnection, "getresponse", getresponse)
    wanted = "http_status" if rejection == "status" else "download_origin"
    original_require, primary = prep.require, []
    def require(ok, reason):
        try: original_require(ok, reason)
        except rt.BoundaryError as error:
            if reason == wanted: primary.append(error)
            raise
    monkeypatch.setattr(prep, "require", require)
    with prep.SourceHTTPS() as opener, pytest.raises(rt.BoundaryError, match=wanted) as caught:
        prep.open_download("https://github.com/start", FakeBudget(tmp_path), opener)
    assert len(primary) == 1 and caught.value is primary[0]
    note = "source_https_connection_close_failed:OSError" if closing == "connection" else "source_https_close_failed:OSError"
    assert note in caught.value.__notes__
    assert len(requests) == len(connections) == 1 and connections[0].closed
    assert "connection" in disposal and bodies[0].closed and bodies[0].reads == []
    assert opener.connection is opener.response is None


@pytest.mark.parametrize("has_primary", [False, True])
@pytest.mark.parametrize("connection_also_fails", [False, True])
def test_source_https_complete_close_primary_and_cleanup_failures(tmp_path, monkeypatch, has_primary, connection_also_fails):
    connections, requests, _ = source_https_connections(monkeypatch, [source_http_wire()])
    with prep.SourceHTTPS() as opener:
        response = prep.open_download("https://github.com/file", FakeBudget(tmp_path), opener)
        assert response.read(4) == b"data" and response.read(4) == b"" and response.complete
        original_raw, original_connection = response.raw.close, connections[0].close
        primary, raw_error, connection_error = rt.BoundaryError("primary"), OSError("raw close"), RuntimeError("connection close")
        disposal = []
        def close_raw():
            disposal.append("raw"); original_raw(); raise raw_error
        def close_connection():
            disposal.append("connection"); original_connection()
            if connection_also_fails: raise connection_error
        monkeypatch.setattr(response.raw, "close", close_raw)
        monkeypatch.setattr(connections[0], "close", close_connection)
        with pytest.raises(rt.BoundaryError if has_primary else OSError) as caught:
            if has_primary:
                try: raise primary
                except rt.BoundaryError:
                    response.close()
                    raise
            else: response.close()
        assert caught.value is (primary if has_primary else raw_error)
        assert "connection" in disposal and connections[0].closed
        assert opener.connection is opener.response is None and len(requests) == 1
        if has_primary: assert "source_https_close_failed:OSError" in primary.__notes__


@pytest.mark.parametrize("closing", ["raw", "connection"])
def test_source_https_early_close_without_primary_propagates_cleanup(tmp_path, monkeypatch, closing):
    connections, requests, bodies = source_https_connections(monkeypatch, [source_http_wire()])
    with prep.SourceHTTPS() as opener:
        response = prep.open_download("https://github.com/file", FakeBudget(tmp_path), opener)
        target = response.raw if closing == "raw" else connections[0]
        original = target.close; error = OSError("first cleanup failure")
        def close(): original(); raise error
        monkeypatch.setattr(target, "close", close)
        with pytest.raises(OSError) as caught: response.close()
        assert caught.value is error and opener.connection is opener.response is None
    assert len(requests) == 1 and connections[0].closed and bodies[0].reads == []


def test_source_https_early_close_without_primary_preserves_first_of_two_errors(tmp_path, monkeypatch):
    connections, requests, bodies = source_https_connections(monkeypatch, [source_http_wire()])
    with prep.SourceHTTPS() as opener:
        response = prep.open_download("https://github.com/file", FakeBudget(tmp_path), opener)
        raw_error, connection_error = OSError("first raw close"), RuntimeError("second connection close")
        original_raw, original_connection = response.raw.close, connections[0].close
        attempts = []
        def close_raw():
            attempts.append("raw"); original_raw(); raise raw_error
        def close_connection():
            attempts.append("connection"); original_connection(); raise connection_error
        monkeypatch.setattr(response.raw, "close", close_raw)
        monkeypatch.setattr(connections[0], "close", close_connection)
        with pytest.raises(OSError) as caught: response.close()
        assert caught.value is raw_error
        assert raw_error.__notes__ == ["source_https_connection_close_failed:RuntimeError"]
        assert attempts == ["raw", "connection"]
        assert opener.connection is opener.response is opener.origin is None and response.closed
    assert len(requests) == 1 and connections[0].closed and bodies[0].reads == []

@pytest.mark.parametrize("fault", [None, "old55", "shift60", "shift62", "duplicate", "args", "hash", "binding55"])
def test_optional_probe_fixed61_independent_public_excerpt(tmp_path, fault):
    lock = synthetic_binding_tree(tmp_path)
    binding = lock["runtime_bindings"]["optional_ld_query"]
    module = tmp_path / binding["module"]["file"]
    lines = module.read_text().splitlines()
    command = "execute_process(COMMAND ld -v OUTPUT_VARIABLE _help ERROR_VARIABLE _help)"
    assert lines[54] == "" and lines[60] == command and lines.count(command) == 1
    assert binding["line"] == 61
    assert binding["args"] == ["COMMAND", "ld", "-v", "OUTPUT_VARIABLE", "_help", "ERROR_VARIABLE", "_help"]
    if fault in {"old55", "shift60", "shift62"}:
        target = {"old55": 54, "shift60": 59, "shift62": 61}[fault]
        lines[60] = ""; lines[target] = command
    elif fault == "duplicate": lines.append(command)
    elif fault == "args": lines[60] = command.replace("ld -v", "ld --version")
    elif fault == "hash": lines[0] = "# modified despite valid source line"
    if fault not in {None, "binding55"}:
        module.write_text("\n".join(lines) + "\n")
        with pytest.raises(rt.BoundaryError): prep.runtime_bindings(tmp_path, lock)
        return
    env = rt.clean_environment([tmp_path / "tools/llvm/bin"], tmp_path, "tmp")
    env.pop("SystemRoot", None)
    if fault == "binding55":
        binding["line"] = 55
        with pytest.raises(rt.BoundaryError, match="optional_probe_binding"):
            prep.optional_probe_guard(tmp_path, binding, env, tmp_path / "tools/cmake/bin")
    else:
        guard = prep.optional_probe_guard(tmp_path, binding, env, tmp_path / "tools/cmake/bin")
        trace = tmp_path / "trace"
        trace.write_text(json.dumps({"cmd": "execute_process", "file": str(module), "line": 61,
            "args": ["COMMAND", "ld", "-v", "OUTPUT_VARIABLE", "_help", "ERROR_VARIABLE", "_help"]}) + "\n")
        assert prep.audit_trace(trace, [], guard, tmp_path) == 1
