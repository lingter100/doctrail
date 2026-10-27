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


class FakeBudget:
    def __init__(self, root):
        self.root, self.downloaded, self.end = root, 0, 100
        self.clock = lambda: 0
    def check(self, incoming=0):
        self.downloaded += incoming
        rt.require(self.downloaded <= rt.DOWNLOAD, "preparation_budget")
        return rt.disk_bytes(self.root)


def test_archive_roundtrip_and_disk_bound(tmp_path, monkeypatch):
    archive = tmp_path / "good.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("dir/file.txt", b"x\r\ny")
    prep.extract_zip(archive, tmp_path / "expanded", FakeBudget(tmp_path))
    assert (tmp_path / "expanded/dir/file.txt").read_bytes() == b"x\r\ny"
    monkeypatch.setattr(prep, "DISK", 1)
    with pytest.raises(rt.BoundaryError, match="archive_expanded_budget"):
        prep.extract_zip(archive, tmp_path / "oversize", FakeBudget(tmp_path))


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
            module.write_text("# synthetic\n" * 54 + prep.LD_SOURCE + "\n")
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


@pytest.mark.parametrize("bad_blob", [False, True])
def test_full_acquisition_mocked_tree_blobs_archives_unknown_ninja_and_no_execution(tmp_path, monkeypatch, bad_blob):
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
                z.writestr("share/cmake-3.31/Modules/Platform/Windows-GNU.cmake", "# synthetic\n" * 54 + prep.LD_SOURCE + "\n")
            if not name.startswith("ninja"): z.writestr("LICENSE", b"synthetic-license")
        url = "https://github.com/synthetic/" + name
        urls[url] = data.getvalue()
        toolpins.append({"name": name, "asset": url, "published_sha256": None if name.startswith("ninja") else rt.digest(data.getvalue())})
    monkeypatch.setattr(prep, "pins", lambda: {"tools": toolpins})
    tree = []
    for name in ["CMakeLists.txt", "LICENSE", "src/llama-grammar.h", "src/llama-grammar.cpp", "src/models/example.cpp"]:
        body = b"synthetic source " + name.encode()
        url = f"https://raw.githubusercontent.com/ggml-org/llama.cpp/{rt.COMMIT}/{name}"
        urls[url] = body
        blob = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
        tree.append({"path": name, "type": "blob", "mode": "100644", "size": len(body), "sha": "0" * 40 if bad_blob and name == "LICENSE" else blob})
    api = "https://api.github.com/repos/ggml-org/llama.cpp/git/"
    urls[api + "commits/" + rt.COMMIT] = json.dumps({"sha": rt.COMMIT, "tree": {"sha": "a" * 40}}).encode()
    urls[api + "trees/" + "a" * 40 + "?recursive=1"] = json.dumps({"sha": "a" * 40, "truncated": False, "tree": tree}).encode()
    urls["https://raw.githubusercontent.com/ninja-build/ninja/v1.12.1/COPYING"] = b"synthetic ninja license"
    calls = []
    opener = SimpleNamespace(open=lambda request, **k: Response(urls[request.full_url]))
    def runner(argv, **kwargs):
        calls.append(argv)
        assert kwargs["deadline"] == 600 and kwargs["rss"] == 2147483648
        assert rt.validate_temporary(root, kwargs["env"]) == root / "acquisition-tmp"
        token = argv[-1]
        monkeypatch.setenv("DOCTRAIL_ACQUIRE_TOKEN", token)
        prep.acquire(root, opener=opener, budget_factory=FakeBudget, worker_token=token)
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
        assert result["compiler_native_execution"] == 0 and len(result["source"]) == 5
        reviewed = rt.digest((root / "acquisition.json").read_bytes())
        assert prep.check_acquired(root, reviewed)["runtime_bindings"] == result["runtime_bindings"]
        with pytest.raises(rt.BoundaryError, match="review_digest_mismatch"):
            prep.check_acquired(root, "0" * 64)
        result["runtime_bindings"]["wrapper_driver_edges"][0]["driver"]["sha256"] = "0" * 64
        (root / "acquisition.json").write_text(json.dumps(result))
        with pytest.raises(rt.BoundaryError, match="runtime_bindings_changed"):
            prep.check_acquired(root, rt.digest((root / "acquisition.json").read_bytes()))
    assert len(calls) == 1
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
            path.write_bytes(("# synthetic\n" * 54 + prep.LD_SOURCE + "\n").encode() if file.endswith(".cmake") else b"not-executable")
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
    row = {"cmd": "execute_process", "args": list(prep.LD_ARGS), "file": str(module), "line": 55}
    if fault == "args": row["args"][2] = "--version"
    elif fault == "relative-module": row["file"] = binding["module"]["file"]
    elif fault == "other-module": row["file"] = str(tmp_path / "other.cmake")
    elif fault == "line": row["line"] = 54
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
