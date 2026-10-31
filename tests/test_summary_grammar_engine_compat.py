"""Tiny fake packages/runners only: no actual payload copy, process or network."""
import copy
import json
import os
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import FunctionType, SimpleNamespace

import pytest

from scripts import build_summary_grammar_engine_compat as compat
from scripts import prepare_summary_grammar_engine as prep
from tools.summary_grammar import runtime as rt


@pytest.mark.parametrize("ending", [b"\n", b"\r\n"])
def test_patch_exact_one_line_and_other_bytes_unchanged(ending):
    data = ending.join([b"# unchanged"] * 124 + [compat.OLD, b"# final"]) + ending
    result = compat.patch_module(data)
    assert result == data.replace(compat.OLD, compat.NEW)
    assert result.replace(compat.NEW, compat.OLD) == data


@pytest.mark.parametrize("variant", ["missing", "line124", "duplicate", "already", "spaces"])
def test_patch_rejects_unfixed_module(variant):
    data = b"#\n" * 124 + compat.OLD + b"\n"
    if variant == "missing":
        data = data.replace(compat.OLD, b"# absent")
    elif variant == "line124":
        data = data[2:]
    elif variant == "duplicate":
        data += compat.OLD + b"\n"
    elif variant == "already":
        data = data.replace(compat.OLD, compat.NEW)
    else:
        data = data.replace(compat.OLD, b" " + compat.OLD)
    with pytest.raises(rt.BoundaryError, match="compat_patch"):
        compat.patch_module(data)


@pytest.mark.parametrize("value", [r"C:\tools\clang.exe", r"C:\개인프로젝트\bin\clang++.exe"])
def test_canonical_compiler_identity_normalization_scope(value):
    assert compat.canonical_compiler(value) == value


@pytest.mark.parametrize("value", [r"C:clang.exe", r"\bin\clang.exe", r"C:\x\..\clang.exe", r"C:\x\.\clang.exe",
                                  r"C:\\x\clang.exe", "C:/x/clang.exe", r"\\?\C:\x\clang.exe", r"\\server\x\clang.exe",
                                  r"C:\x\clang.exe;arg", "C:\\x\\clang.exe\n", r'C:\x\"clang.exe', r"C:\x.\clang.exe",
                                  r"C:\x \clang.exe", r"C:\x\clang.exe:stream"])
def test_noncanonical_compiler_rejected(value):
    with pytest.raises(rt.BoundaryError, match="compiler_path_not_canonical"):
        compat.canonical_compiler(value)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    original, output, bundle = tmp_path / "acquired", tmp_path / "compat", tmp_path / "bundle"
    original.mkdir()
    bundle.mkdir()
    for name, data in {"candidate.gbnf": b"root ::= \"a\"\n", "expected.json": b"[]", "prefix-witnesses.json": b"[]"}.items():
        (bundle / name).write_bytes(data)
    monkeypatch.setattr(rt, "BUNDLE", bundle)
    monkeypatch.delenv("SystemRoot", raising=False)
    monkeypatch.delenv("WINDIR", raising=False)
    if os.name != "nt":
        # Portable fake paths only; Windows canonical validation is tested above.
        monkeypatch.setattr(compat, "canonical_compiler", lambda path: str(path))
    packages = {
        "cmake": {"pkg/bin/cmake.exe": b"fake-cmake", "pkg/LICENSE": b"fake-license",
                  "pkg/" + compat.MODULE: b"# fixed-prefix\r\n" * 124 + compat.OLD + b"\r\n# end\r\n",
                  "pkg/share/cmake-3.31/Modules/Platform/Windows-GNU.cmake": b"# prefix\n" * 60 + prep.LD_SOURCE.encode() + b"\n"},
        "llvm": {"bin/clang.exe": b"fake-c", "bin/clang++.exe": b"fake-cxx", "bin/clang-20.exe": b"fake-driver",
                 "lib/clang/20/include/fake.h": b"fake-resource"},
        "ninja": {"ninja.exe": b"fake-ninja"},
    }
    tools = []
    for name, files in packages.items():
        directory = original / "tools" / name
        for filename, body in files.items():
            path = directory / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        tools.append({"name": name + ".zip", "directory": "tools/" + name, "inventory": rt.inventory(directory),
                      "archive_sha256": "a" * 64, "url": "https://unused.invalid/" + name})
    (original / "source").mkdir()
    (original / "source/LICENSE").write_bytes(b"fake-engine-license")
    (original / "build-attempt.json").write_bytes(b"old consumed failure; never replaced")
    lock = {"engine_commit": "b" * 40, "tools": tools, "bundle": rt.inventory(bundle),
            "source": rt.inventory(original / "source"),
            "licenses": [rt.reference(original / "tools/cmake/pkg/LICENSE", original)]}
    lock["runtime_bindings"] = prep.runtime_bindings(original, lock)
    lock["payload"] = rt.inventory(original)
    rt.write(original / "acquisition.json", lock)
    frozen = rt.inventory(original)
    calls, checks = [], []
    def acquired(root, sha):
        assert root == original and sha == "f" * 64
        rt.require(rt.inventory(original) == frozen, "fake_original_changed")
        checks.append((root, sha))
        return copy.deepcopy(lock)
    monkeypatch.setattr(prep, "check_acquired", acquired)
    native_rows = [{"raw": b"a", "suffix": b"", "expected": "complete"}]
    monkeypatch.setattr(rt, "bundle", lambda: (native_rows, ["raw-surrogate"]))
    def runner(argv, **kwargs):
        calls.append((list(map(str, argv)), kwargs))
        prefix = kwargs["log_prefix"]
        for extension in (".stdout", ".stderr"):
            Path(str(prefix) + extension).write_bytes(b"")
        receipt = {"status": "process_exited_zero_not_semantic_success", "exit": 0, "within_shared_deadline": True,
                   "cleanup": {"all_absent": True, "errors": [], "identities": []}}
        rt.write(Path(str(prefix) + ".json"), receipt)
        if prefix.name == "configure":
            module = output / "cmake/pkg/share/cmake-3.31/Modules/Platform/Windows-GNU.cmake"
            (output / "configure-trace.jsonl").write_text(json.dumps({"cmd": "execute_process", "args": prep.LD_ARGS,
                                                                    "line": 61, "file": str(module)}) + "\n", encoding="utf-8")
        elif prefix.name == "compile":
            binary = output / "build/bin/summary-grammar-validator.exe"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"synthetic-not-executable")
        else:
            protocol = [{"init_ms": 1, "rules": 1},
                        {"case": 0, "state": "complete", "witness": None, "clone_ms": 1, "elapsed_ms": 1},
                        {"done": 1, "clone_total_ms": 1, "longest_ms": 1, "total_ms": 3}]
            Path(str(prefix) + ".stdout").write_text("".join(json.dumps(row) + "\n" for row in protocol), encoding="utf-8")
        return receipt
    return SimpleNamespace(original=original, output=output, bundle=bundle, lock=lock, frozen=frozen,
                           runner=runner, calls=calls, checks=checks, sha="f" * 64, clock=lambda: 0)


def built(f):
    manifest = compat.build(f.original, f.output, f.sha, runner=f.runner, clock=f.clock)
    return manifest, rt.digest((f.output / "build-manifest.json").read_bytes())


def test_fake_build_preserves_originals_maps_runtime_and_shared_limits(fixture):
    f = fixture
    result, sha = built(f)
    assert rt.inventory(f.original) == f.frozen and len(f.checks) == 2
    assert result["status"] == compat.STATUS and result["native_batch_runs"] == 0
    assert result["inputs"]["review_artifact_sha256"] == f.sha
    assert result["inputs"]["actual_acquisition"]["sha256"] != f.sha
    assert result["inputs"]["optional_ld_query"]["module"]["file"].startswith("cmake/")
    for _, kwargs in f.calls:
        assert kwargs["deadline"] == 900 and kwargs["root"] == f.output
        assert kwargs["rss"] == kwargs["host"] == 2 * 1024**3 and kwargs["start"] == 4 * 1024**3
        assert f.original / "tools/llvm/bin/clang-20.exe" in kwargs["allowed"]
        assert f.output / "cmake/pkg/bin/cmake.exe" in kwargs["allowed"]
        assert f.original / "tools/cmake/pkg/bin/cmake.exe" not in kwargs["allowed"]
        assert Path(kwargs["env"]["TEMP"]).is_relative_to(f.output)
    assert f.calls[1][0][-4:] == ["--target", "summary-grammar-validator", "--parallel", "2"]
    assert str(f.bundle) in f.calls[0][0]
    assert compat.check_build(f.output, sha) == result
    with pytest.raises(rt.BoundaryError, match="compat_build_once"):
        compat.build(f.original, f.output, f.sha, runner=f.runner)
    assert len(f.calls) == 2


@pytest.mark.parametrize("kind", ["runner", "copy", "source_drift", "derived_drift", "license_missing"])
def test_fake_failures_do_not_publish_success_and_preserve_once(fixture, monkeypatch, kind):
    f = fixture
    runner = f.runner
    if kind == "copy":
        original_open = Path.open
        def fail_copy(path, mode="r", *args, **kwargs):
            if path == f.output / "cmake/pkg/LICENSE" and mode == "xb":
                raise OSError("synthetic copy write failure")
            return original_open(path, mode, *args, **kwargs)
        monkeypatch.setattr(Path, "open", fail_copy)
    elif kind == "license_missing":
        original_inputs = compat.inputs
        def fail_license(*args):
            record, patched = original_inputs(*args)
            record["derived_licenses"] = [dict(record["derived_licenses"][0], sha256="0" * 64)]
            return record, patched
        monkeypatch.setattr(compat, "inputs", fail_license)
    else:
        def runner(argv, **kwargs):
            if kind == "runner":
                raise rt.BoundaryError("synthetic configure failure")
            value = f.runner(argv, **kwargs)
            if kwargs["log_prefix"].name == "compile":
                path = f.original / "source/LICENSE" if kind == "source_drift" else f.output / "cmake/pkg/LICENSE"
                path.write_bytes(b"injected drift")
            return value
    with pytest.raises((rt.BoundaryError, OSError)):
        compat.build(f.original, f.output, f.sha, runner=runner, clock=f.clock)
    assert (f.output / "build-issued.json").exists() and (f.output / "build-failure.json").exists()
    assert "requires separate closeout" in rt.load(f.output / "build-failure.json")["original_input_preservation"]
    assert not (f.output / "build-manifest.json").exists()
    if kind != "source_drift":
        assert rt.inventory(f.original) == f.frozen
    with pytest.raises(rt.BoundaryError, match="compat_build_once"):
        compat.build(f.original, f.output, f.sha, runner=f.runner)


def test_optional_probe_original_path_cannot_authorize_derived_execution(fixture):
    f = fixture
    def runner(argv, **kwargs):
        value = f.runner(argv, **kwargs)
        path = f.output / "configure-trace.jsonl"
        record = json.loads(path.read_text())
        record["file"] = str(f.original / f.lock["runtime_bindings"]["optional_ld_query"]["module"]["file"])
        path.write_text(json.dumps(record) + "\n")
        return value
    with pytest.raises(rt.BoundaryError, match="configure_unapproved_executable"):
        compat.build(f.original, f.output, f.sha, runner=runner, clock=f.clock)
    assert len(f.calls) == 1 and not (f.output / "build-manifest.json").exists()


@pytest.mark.parametrize("target", ["same", "child", "parent", "bundle"])
def test_overlapping_output_rejected_before_writes(fixture, target):
    f = fixture
    output = {"same": f.original, "child": f.original / "new", "parent": f.original.parent, "bundle": f.bundle / "new"}[target]
    with pytest.raises(rt.BoundaryError, match="compat_roots_overlap"):
        compat.build(f.original, output, f.sha, runner=f.runner)
    assert not f.calls and rt.inventory(f.original) == f.frozen


@pytest.mark.parametrize("kind", ["digest", "schema", "driver", "mapping", "derived", "extra", "original", "executable_ref"])
def test_reviewed_manifest_and_inputs_reject_tampering(fixture, kind):
    f = fixture
    manifest, sha = built(f)
    if kind == "derived":
        (f.output / "cmake/pkg/LICENSE").write_bytes(b"changed")
    elif kind == "extra":
        (f.output / "cmake/extra").write_bytes(b"extra")
    elif kind == "original":
        (f.original / "source/LICENSE").write_bytes(b"changed")
    else:
        if kind == "schema":
            manifest["schema"] = "legacy"
        elif kind == "driver":
            manifest["sources"][0]["sha256"] = "0" * 64
        elif kind == "mapping":
            manifest["inputs"]["optional_ld_query"]["module"]["file"] = "tools/cmake/old-module"
        elif kind == "executable_ref":
            manifest["executable"]["file"] = "cmake/pkg/bin/cmake.exe"
        else:
            manifest["status"] = "tampered"
        path = f.output / "build-manifest.json"
        path.write_text(json.dumps(manifest))
        if kind != "digest":
            sha = rt.digest(path.read_bytes())
    with pytest.raises(rt.BoundaryError):
        compat.check_build(f.output, sha)
    assert len(f.calls) == 2


def test_fake_native_review_once_and_limits(fixture):
    f = fixture
    _, sha = built(f)
    result = compat.verify(f.output, sha, runner=f.runner, ps=SimpleNamespace(), clock=f.clock)
    assert result["status"] == "FINITE_ENGINE_CHECK_PASS_NOT_PRODUCT_ACCEPTANCE"
    assert result["model_tokenizer_calls"] == 0 and not result["semantics_verified"]
    _, kwargs = f.calls[-1]
    assert kwargs["deadline"] == 60 and kwargs["rss"] == 512 * 1024**2
    assert kwargs["host"] == 2 * 1024**3 and kwargs["start"] == 5 * 1024**3 // 2
    with pytest.raises(rt.BoundaryError, match="native_once"):
        compat.verify(f.output, sha, "another", runner=f.runner, ps=SimpleNamespace())
    assert len(f.calls) == 3 and rt.inventory(f.original) == f.frozen


def test_failed_native_protocol_consumes_global_once(fixture):
    f = fixture
    _, sha = built(f)
    def runner(argv, **kwargs):
        value = f.runner(argv, **kwargs)
        Path(str(kwargs["log_prefix"]) + ".stdout").write_bytes(b"{}\n")
        return value
    with pytest.raises(rt.BoundaryError, match="protocol_count"):
        compat.verify(f.output, sha, runner=runner, ps=SimpleNamespace(), clock=f.clock)
    assert (f.output / "engine-check/failure.json").exists()
    assert not (f.output / "engine-check/result.json").exists()
    with pytest.raises(rt.BoundaryError, match="native_once"):
        compat.verify(f.output, sha, "other-result", runner=f.runner, ps=SimpleNamespace())


@pytest.mark.parametrize("phase", ["build", "native"])
def test_failure_record_write_cannot_mask_first_error(fixture, monkeypatch, phase):
    f = fixture
    sha = built(f)[1] if phase == "native" else None
    original_write = rt.write
    def write(path, data):
        if path.name in {"build-failure.json", "failure.json"}:
            raise OSError("synthetic failure-record disk error")
        return original_write(path, data)
    monkeypatch.setattr(rt, "write", write)
    def runner(*args, **kwargs):
        raise rt.BoundaryError("original_owned_process_failure")
    with pytest.raises(rt.BoundaryError, match="original_owned_process_failure") as caught:
        if phase == "build":
            compat.build(f.original, f.output, f.sha, runner=runner, clock=f.clock)
        else:
            compat.verify(f.output, sha, runner=runner, ps=SimpleNamespace(), clock=f.clock)
    assert str(caught.value) == "original_owned_process_failure"
    assert caught.value.__notes__ == ["compat_failure_record_failed:OSError"]
    once = "build-issued.json" if phase == "build" else "native-issued.json"
    assert (f.output / once).exists()
    assert rt.inventory(f.original) == f.frozen


@pytest.mark.parametrize("phase", ["build", "native"])
@pytest.mark.parametrize("reporting_fails", [False, True])
def test_success_metadata_counts_toward_whole_output_disk_limit(fixture, monkeypatch, phase, reporting_fails):
    f = fixture
    sha = built(f)[1] if phase == "native" else None
    original_disk, original_write = rt.disk_bytes, rt.write
    ready = f.output / ("build/bin/summary-grammar-validator.exe" if phase == "build" else "engine-check/engine.stdout")
    def disk(root, checkpoint=None):
        assert Path(root) == f.output  # Native result must account for the whole output.
        if ready.exists():
            if checkpoint is not None:
                checkpoint("start")
            return rt.DISK - 1  # Files fit; serialized success metadata does not.
        return original_disk(root, checkpoint=checkpoint)
    def write(path, data):
        if reporting_fails and path.name in {"build-failure.json", "failure.json"}:
            raise OSError("synthetic reporting disk failure")
        return original_write(path, data)
    monkeypatch.setattr(rt, "disk_bytes", disk)
    monkeypatch.setattr(rt, "write", write)
    with pytest.raises(rt.BoundaryError, match="disk_budget") as caught:
        if phase == "build":
            compat.build(f.original, f.output, f.sha, runner=f.runner, clock=f.clock)
        else:
            compat.verify(f.output, sha, runner=f.runner, ps=SimpleNamespace(), clock=f.clock)
    assert str(caught.value) == "disk_budget"
    success = f.output / ("build-manifest.json" if phase == "build" else "engine-check/result.json")
    failure = f.output / ("build-failure.json" if phase == "build" else "engine-check/failure.json")
    once = f.output / ("build-issued.json" if phase == "build" else "native-issued.json")
    assert not success.exists() and once.exists()
    if reporting_fails:
        assert caught.value.__notes__ == ["compat_failure_record_failed:OSError"]
    else:
        assert rt.load(failure)["reason"] == "disk_budget"
    assert rt.inventory(f.original) == f.frozen


@pytest.mark.parametrize("name", ["cmake/new", "build/new", "cmake", "build", "build-tmp", "../escape"])
def test_native_result_cannot_modify_build_inputs(fixture, name):
    f = fixture
    _, sha = built(f)
    with pytest.raises(rt.BoundaryError, match="compat_result_directory"):
        compat.verify(f.output, sha, name, runner=f.runner, ps=SimpleNamespace())
    assert len(f.calls) == 2 and not (f.output / "native-issued.json").exists()


class FakeDosDevices:
    """No Windows calls/mappings. Translate fake aliases only inside fake I/O."""
    def __init__(self, target):
        self.target = target
        self.definitions = []
        self.logical_occupied = False
        self.created = []
        self.removed = []
        self.same_ok = True

    def query(self, drive):
        return self.definitions[:]

    def occupied(self, drive):
        return self.logical_occupied

    def create(self, drive, target):
        self.created.append((drive, target))
        self.definitions = [target]

    def remove(self, drive, target):
        self.removed.append((drive, target))
        self.definitions = []

    def canonical(self, value):
        value = str(value)
        if value.startswith("R:\\"):
            return self.target.joinpath(*PureWindowsPath(value).parts[1:])
        return Path(value)

    def same(self, alias, canonical):
        return self.same_ok and self.canonical(alias) == canonical


@pytest.mark.parametrize("host_separator", [";", ":"])
def test_native_drive_windows_path_list_independent_of_fake_host(tmp_path, monkeypatch, host_separator):
    # Model CI's POSIX fixture paths on either host without creating a DOS mapping.
    root = PurePosixPath("/repo")
    directories = [root / name for name in ("llvm/bin", "cmake/bin", "ninja")]
    lease = compat.NativeDrive(None, tmp_path, "unused")
    lease.drive = "R:"
    lease.path = lambda p: PureWindowsPath("R:/") / PurePosixPath(p).relative_to(root)
    monkeypatch.setattr(compat, "os", SimpleNamespace(pathsep=host_separator))
    actual = lease.environment({"PATH": host_separator.join(map(str, directories)), "TEMP": "/repo/tmp", "TMP": "/repo/tmp"})
    expected = r"R:\llvm\bin;R:\cmake\bin;R:\ninja"
    assert actual["PATH"] == expected
    # Splitting at POSIX ':' destroys the drive prefix and reproduces the CI guard's relative search entries.
    assert not all(PureWindowsPath(p).is_absolute() for p in expected.split(":"))
    backend = FakeDosDevices(root)
    canonical = [backend.canonical(p) for p in actual["PATH"].split(";")]
    assert canonical == directories and all(p.is_absolute() for p in canonical)


@pytest.fixture
def drive_fixture(fixture, monkeypatch):
    f = fixture
    sources = compat.source_refs()
    monkeypatch.setattr(compat, "REPO", f.original.parent)
    monkeypatch.setattr(compat, "source_refs", lambda: sources)
    # Preserve real source validation through the already captured dependency refs.
    check_refs = rt.check_refs
    real_repo = Path(__file__).resolve().parents[1]
    def checked(root, refs, *args, **kwargs):
        if root == f.original.parent and refs == sources:
            root = real_repo
        return check_refs(root, refs, *args, **kwargs)
    monkeypatch.setattr(rt, "check_refs", checked)
    backend = FakeDosDevices(f.original.parent.resolve())
    probe = prep.optional_probe_guard
    def canonical_env(env):
        return dict(env, PATH=os.pathsep.join(str(backend.canonical(p)) for p in env["PATH"].split(";")),
                    TEMP=str(backend.canonical(env["TEMP"])), TMP=str(backend.canonical(env["TMP"])))
    def fake_probe(root, binding, env, app):
        return probe(backend.canonical(root), binding, canonical_env(env), backend.canonical(app))
    monkeypatch.setattr(prep, "optional_probe_guard", fake_probe)
    calls = []
    def runner(argv, **kwargs):
        calls.append((list(map(str, argv)), dict(kwargs)))
        assert all(str(value).isascii() for value in argv)
        root, temporary = PureWindowsPath(str(kwargs["root"])), PureWindowsPath(kwargs["env"]["TEMP"])
        assert temporary.is_relative_to(root) and temporary != root
        translated = dict(kwargs)
        for name in ("cwd", "root", "log_prefix"):
            translated[name] = backend.canonical(kwargs[name])
        translated["env"] = canonical_env(kwargs["env"])
        rt.validate_temporary(translated["root"], translated["env"])
        receipt = f.runner(argv, **translated)
        receipt["argv"] = list(map(str, argv))
        receipt["temporary_directory"] = kwargs["env"]["TEMP"]
        Path(str(translated["log_prefix"]) + ".json").write_text(json.dumps(receipt), encoding="utf-8")
        return receipt
    return f, backend, runner, calls


@pytest.mark.parametrize("occupied", ["query", "logical"])
def test_native_drive_never_replaces_occupied_drive(tmp_path, monkeypatch, occupied):
    monkeypatch.setattr(compat, "REPO", tmp_path)
    backend = FakeDosDevices(tmp_path)
    backend.definitions = ["other"] if occupied == "query" else []
    backend.logical_occupied = occupied == "logical"
    with pytest.raises(rt.BoundaryError, match="native_drive_occupied"), compat.NativeDrive("R:", tmp_path, "lease", backend):
        pytest.fail("occupied drive entered")
    assert backend.created == backend.removed == []


@pytest.mark.parametrize("value", ["r:", "C:", "R", "R:\\", "R:evil", "AA:", "한:"])
def test_native_drive_requires_explicit_safe_letter(tmp_path, value):
    with pytest.raises(rt.BoundaryError, match="native_drive_letter"):
        compat.NativeDrive(value, tmp_path, "lease", FakeDosDevices(tmp_path))


@pytest.mark.parametrize("failure", ["changed", "identity", "children", "remove"])
def test_native_drive_cleanup_retains_primary_and_never_removes_changed_mapping(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(compat, "REPO", tmp_path)
    backend = FakeDosDevices(tmp_path)
    with pytest.raises(ValueError, match="first failure") as caught, compat.NativeDrive("R:", tmp_path, "lease", backend) as lease:
        if failure == "changed":
            backend.definitions = ["someone-else"]
        elif failure == "children":
            lease.children_closed = False
        elif failure == "remove":
            monkeypatch.setattr(backend, "remove", lambda *args: (_ for _ in ()).throw(OSError("remove failure")))
        else:
            backend.same_ok = False
            with pytest.raises(rt.BoundaryError, match="native_drive_identity"):
                lease.path(tmp_path)
        raise ValueError("first failure")
    if failure == "identity":
        assert len(backend.removed) == 1  # Same mapping, no child launched.
    else:
        assert backend.removed == []
        assert caught.value.__notes__[0].startswith("native_drive_cleanup_failed:")


def test_native_drive_maps_long_paths_without_short_names_and_rejects_suffix_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(compat, "REPO", tmp_path)
    backend = FakeDosDevices(tmp_path)
    with compat.NativeDrive("R:", tmp_path, "lease", backend) as lease:
        long_path = tmp_path / ("ascii" * 30) / ("name" * 35) / "tool.exe"
        alias = lease.path(long_path)
        assert str(alias).isascii() and len(str(alias)) > 260 and backend.canonical(alias) == long_path
        with pytest.raises(rt.BoundaryError, match="outside_repository"):
            lease.path(tmp_path.parent / "outside")
        with pytest.raises(rt.BoundaryError, match="non_ascii_suffix"):
            lease.path(tmp_path / "남은한글")
    assert backend.definitions == []


def test_native_drive_build_actual_alias_argv_environment_and_historical_verification(drive_fixture):
    f, backend, runner, calls = drive_fixture
    manifest = compat.build(f.original, f.output, f.sha, runner=runner, clock=f.clock, native_drive="R:", mapping_backend=backend)
    assert len(calls) == 2 and len(backend.created) == len(backend.removed) == 1 and backend.definitions == []
    for argv, kwargs in calls:
        assert argv[0].startswith("R:\\") and all(str(kwargs[k]).startswith("R:\\") for k in ("cwd", "root", "log_prefix"))
        assert kwargs["deadline"] == 900 and kwargs["allowed"][0].is_relative_to(f.output)
        assert kwargs["env"]["TEMP"] == kwargs["env"]["TMP"] and kwargs["env"]["PATH"].startswith("R:\\")
    assert manifest["native_drive"]["cleanup"] == {"children_closed": True, "removed": True}
    sha = rt.digest((f.output / "build-manifest.json").read_bytes())
    assert compat.check_build(f.output, sha) == manifest  # No live mapping/query required.
    result = compat.verify(f.output, sha, runner=runner, ps=SimpleNamespace(), clock=f.clock,
                           native_drive="R:", mapping_backend=backend)
    assert len(backend.created) == len(backend.removed) == 2 and len(calls) == 3
    assert result["native_drive"]["cleanup"]["removed"] and calls[-1][1]["deadline"] == 60
    assert rt.inventory(f.original) == f.frozen


@pytest.mark.parametrize("cleanup_known", [False, True])
def test_native_drive_failed_runner_only_removes_after_confirmed_owned_cleanup(drive_fixture, cleanup_known):
    f, backend, _, _ = drive_fixture
    def fail(*args, **kwargs):
        error = rt.BoundaryError("native primary")
        if cleanup_known:
            error.supervision_record = {"cleanup": {"all_absent": True, "errors": ["BoundaryError"]}}
        raise error
    with pytest.raises(rt.BoundaryError, match="native primary"):
        compat.build(f.original, f.output, f.sha, runner=fail, clock=f.clock, native_drive="R:", mapping_backend=backend)
    assert bool(backend.removed) == cleanup_known
    assert not (f.output / "build-manifest.json").exists()
    assert rt.load(f.output / "build-failure.json")["reason"] == "native primary"


@pytest.mark.parametrize("field", ["canonical_repository", "cleanup", "paths", "invocations"])
def test_native_drive_historical_tampering_rejected(drive_fixture, field):
    f, backend, runner, _ = drive_fixture
    manifest = compat.build(f.original, f.output, f.sha, runner=runner, clock=f.clock, native_drive="R:", mapping_backend=backend)
    manifest["native_drive"][field] = {"cleanup": {"removed": False}, "paths": [], "invocations": [], "canonical_repository": "wrong"}[field]
    (f.output / "build-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(rt.BoundaryError, match="native_drive_history"):
        compat.check_build(f.output, rt.digest((f.output / "build-manifest.json").read_bytes()))


def test_native_drive_cleanup_failure_blocks_success(drive_fixture, monkeypatch):
    f, backend, runner, _ = drive_fixture
    monkeypatch.setattr(backend, "remove", lambda *args: (_ for _ in ()).throw(OSError("remove failed")))
    with pytest.raises(OSError, match="remove failed"):
        compat.build(f.original, f.output, f.sha, runner=runner, clock=f.clock, native_drive="R:", mapping_backend=backend)
    assert not (f.output / "build-manifest.json").exists()
    assert backend.definitions and rt.load(f.output / "build-native-drive.json")["cleanup"]["removed"] is False


def test_native_drive_creation_race_retains_changed_mapping(tmp_path, monkeypatch):
    monkeypatch.setattr(compat, "REPO", tmp_path)
    backend = FakeDosDevices(tmp_path)
    def race(drive, target):
        backend.definitions = [target, "concurrent-other-definition"]
    monkeypatch.setattr(backend, "create", race)
    with pytest.raises(rt.BoundaryError, match="native_drive_changed"), compat.NativeDrive("R:", tmp_path, "lease", backend):
        pytest.fail("raced mapping admitted")
    assert backend.removed == [] and len(backend.definitions) == 2


def test_native_drive_receipt_error_does_not_mask_primary(tmp_path, monkeypatch):
    monkeypatch.setattr(compat, "REPO", tmp_path)
    backend = FakeDosDevices(tmp_path)
    monkeypatch.setattr(rt, "write_bounded", lambda *args: (_ for _ in ()).throw(OSError("receipt failed")))
    with pytest.raises(ValueError, match="primary") as caught, compat.NativeDrive("R:", tmp_path, "lease", backend):
        raise ValueError("primary")
    assert backend.definitions == [] and caught.value.__notes__ == ["native_drive_cleanup_failed:receipt failed"]


def test_native_drive_history_cannot_drop_mapping(drive_fixture):
    f, backend, runner, _ = drive_fixture
    manifest = compat.build(f.original, f.output, f.sha, runner=runner, clock=f.clock, native_drive="R:", mapping_backend=backend)
    manifest["native_drive"] = manifest["native_drive_receipt"] = None
    (f.output / "build-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(rt.BoundaryError, match="native_drive_history"):
        compat.check_build(f.output, rt.digest((f.output / "build-manifest.json").read_bytes()))


def active_scan_checkpoint(events, resource=None):
    """Use the unchanged runner's actual nested code, with tiny sampled fake cells."""
    def cell(value):
        return (lambda: value).__closure__[0]
    values = {"sampled": True, "record": {"active_disk_scans": {"entries": 0}},
              "resource_checkpoint": resource or events.append}
    closure = tuple(cell(values.get(name)) for name in compat.OWNED_SCAN_CODE.co_freevars)
    return FunctionType(compat.OWNED_SCAN_CODE, rt.run_owned.__globals__, closure=closure)


@pytest.mark.parametrize("mode", ["vanish", "permission", "oserror", "rootgone", "aliasgone", "link", "budget", "deadline_after_skip"])
def test_live_scan_entry_race_preserves_guards_and_checkpoints(tmp_path, monkeypatch, mode):
    entry = tmp_path / "object.o"
    entry.write_bytes(b"object")
    paths = compat.NativeDrive(None, tmp_path, "unused")
    scanner = compat.LiveDiskScan(tmp_path, tmp_path, paths, "configure")
    original, lstat = rt.disk_bytes, Path.lstat
    calls, events = [0], []
    def attrs(path, *args, **kwargs):
        if path == entry:
            calls[0] += 1
            if calls[0] == 2:  # safe_path succeeds; only the scanner's lstat races unlink.
                if mode == "permission":
                    raise PermissionError("denied")
                if mode == "oserror":
                    raise OSError("io failure")
                if mode == "link":
                    return SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
                if mode != "budget":
                    raise FileNotFoundError("compiler removed object")
        if path == tmp_path and mode == "rootgone" and calls[0] >= 2:
            raise FileNotFoundError("output root gone")
        return lstat(path, *args, **kwargs)
    monkeypatch.setattr(Path, "lstat", attrs)
    def alias_check():
        if mode == "aliasgone" and calls[0] >= 2:
            raise rt.BoundaryError("native_drive_changed")
    monkeypatch.setattr(paths, "check", alias_check)
    if mode == "budget":
        monkeypatch.setattr(rt, "DISK", 1)
    def checkpoint(event):
        events.append(event)
        if mode == "deadline_after_skip" and events.count(None) == 2:
            raise rt.BoundaryError("shared_deadline")
    active = active_scan_checkpoint(events, checkpoint)
    run = lambda *a, **kw: rt.disk_bytes(tmp_path, checkpoint=active)
    if mode == "vanish":
        assert scanner.run(run, []) == 0
        assert events == ["scan_start", None, None, "scan_complete"]
        assert scanner.record["disappeared_entries"] == 1
    else:
        with pytest.raises((OSError, rt.BoundaryError)):
            scanner.run(run, [])
    assert rt.disk_bytes is original and scanner.record["restored"] is True


@pytest.mark.parametrize("mode", ["static", "same_name", "wrong_root", "write_bounded", "safe_path", "iteration", "checkpoint"])
def test_live_scan_only_exact_active_code_and_entry_lstat_are_tolerated(tmp_path, monkeypatch, mode):
    entry = tmp_path / "object.o"
    entry.write_bytes(b"object")
    scanner = compat.LiveDiskScan(tmp_path, tmp_path, compat.NativeDrive(None, tmp_path, "unused"), "configure")
    original, lstat, safe = rt.disk_bytes, Path.lstat, rt.safe_path
    calls = [0]
    def attrs(path, *args, **kwargs):
        if path == entry:
            calls[0] += 1
            if calls[0] == 2:
                raise FileNotFoundError("entry")
        return lstat(path, *args, **kwargs)
    monkeypatch.setattr(Path, "lstat", attrs)
    callback = active_scan_checkpoint([])
    if mode == "static":
        callback = None
    elif mode == "same_name":
        def scan_checkpoint(event):
            pass
        callback = scan_checkpoint
    elif mode == "wrong_root":
        scanner.root = tmp_path / "another"
    elif mode == "safe_path":
        def guard(root, name):
            if name == "object.o":
                raise FileNotFoundError("safe_path failure")
            return safe(root, name)
        monkeypatch.setattr(rt, "safe_path", guard)
    elif mode == "iteration":
        monkeypatch.setattr(Path, "rglob", lambda *a: (_ for _ in ()).throw(FileNotFoundError("whole iteration")))
    elif mode == "checkpoint":
        callback = active_scan_checkpoint([], lambda event: (_ for _ in ()).throw(FileNotFoundError("checkpoint")))
    def runner(*args, **kwargs):
        if mode == "write_bounded":
            return rt.write_bounded(tmp_path, tmp_path / "receipt.json", {})
        return rt.disk_bytes(tmp_path, checkpoint=callback)
    with pytest.raises(FileNotFoundError):
        scanner.run(runner, [])
    assert rt.disk_bytes is original and scanner.record["restored"] and scanner.record["disappeared_entries"] == 0


def test_live_scan_restores_after_primary_failure_even_if_replacement_changes(tmp_path):
    scanner = compat.LiveDiskScan(tmp_path, tmp_path, compat.NativeDrive(None, tmp_path, "unused"), "configure")
    original = rt.disk_bytes
    def fail(*args, **kwargs):
        rt.disk_bytes = lambda *a, **kw: 0
        raise ValueError("primary")
    with pytest.raises(ValueError, match="primary") as caught:
        scanner.run(fail, [])
    assert rt.disk_bytes is original and scanner.record["restored"]
    assert caught.value.__notes__ == ["live_scan_adapter_changed_before_restore"]


def test_live_scan_build_records_policy_counts_and_rejects_tampered_history(fixture):
    f, original = fixture, rt.disk_bytes
    def runner(argv, **kwargs):
        assert rt.disk_bytes is not original
        rt.disk_bytes(f.output, checkpoint=active_scan_checkpoint([]))
        return f.runner(argv, **kwargs)
    manifest = compat.build(f.original, f.output, f.sha, runner=runner, clock=f.clock)
    assert rt.disk_bytes is original and rt.inventory(f.original) == f.frozen
    phases = manifest["live_disk_scan"]["phases"]
    assert [p["phase"] for p in phases] == ["configure", "compile"]
    assert all(p["active_scans"] == 1 and p["disappeared_entries"] == 0 and p["restored"] for p in phases)
    sha = rt.digest((f.output / "build-manifest.json").read_bytes())
    assert compat.check_build(f.output, sha) == manifest
    phases[0]["restored"] = False
    (f.output / "build-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(rt.BoundaryError, match="live_scan_history"):
        compat.check_build(f.output, rt.digest((f.output / "build-manifest.json").read_bytes()))
