"""Tiny fake packages/runners only: no actual payload copy, process or network."""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

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
