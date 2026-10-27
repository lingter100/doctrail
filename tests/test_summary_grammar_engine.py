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
