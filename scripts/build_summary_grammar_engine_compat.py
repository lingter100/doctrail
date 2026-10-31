"""Build a separately reviewed CMake derivative; never alter acquired inputs.

Only canonical single C/CXX compiler paths are supported. The one-line legacy
conversion is not a general substitute for cmake_path NORMALIZE. Copy/input
checks are outside the existing shared 900-second configure/compile budget.
Native verification remains a separately reviewed, model-free, one-shot batch.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import prepare_summary_grammar_engine as prep
from scripts import verify_summary_grammar_engine as native
from tools.summary_grammar import runtime as rt

REPO = Path(__file__).resolve().parents[1]
MODULE = "share/cmake-3.31/Modules/CMakeDetermineCompiler.cmake"
OLD = b'    cmake_path(CONVERT "${CMAKE_${lang}_COMPILER}" TO_CMAKE_PATH_LIST CMAKE_${lang}_COMPILER NORMALIZE)'
NEW = b'    file(TO_CMAKE_PATH "${CMAKE_${lang}_COMPILER}" CMAKE_${lang}_COMPILER)'
SCHEMA = "engine-cmake-path-compat-build-v1"
STATUS = "COMPAT_BUILT_UNREVIEWED_NOT_ENGINE_VALIDATED"
TOOLS = {"cmake.exe", "ninja.exe", "clang.exe", "clang++.exe", "ld.lld.exe", "lld.exe",
         "llvm-ar.exe", "llvm-ranlib.exe", "llvm-rc.exe", "llvm-mt.exe"}
SOURCES = ("scripts/build_summary_grammar_engine_compat.py", "scripts/prepare_summary_grammar_engine.py",
           "scripts/verify_summary_grammar_engine.py", "tools/summary_grammar/runtime.py")


def canonical_compiler(value):
    """The accepted Windows inputs need only slash conversion, not normalization."""
    value = str(value)
    rt.require(bool(re.fullmatch(r"[A-Za-z]:\\[^\x00-\x1f;\"/]+", value))
               and not value.startswith("\\\\") and str(PureWindowsPath(value)) == value,
               "compiler_path_not_canonical_single_absolute")
    parts = value[3:].split("\\")
    rt.require(all(part and part not in (".", "..") and part == part.rstrip(" .")
                   and ":" not in part for part in parts), "compiler_path_not_canonical_single_absolute")
    return value


def patch_module(data):
    lines = data.splitlines(keepends=True)
    rt.require(len(lines) >= 125 and data.count(OLD) == 1 and NEW not in data, "compat_patch_occurrence")
    line = lines[124]
    ending = b"\r\n" if line.endswith(b"\r\n") else b"\n" if line.endswith(b"\n") else b""
    rt.require(ending and line == OLD + ending, "compat_patch_line125")
    lines[124] = NEW + ending
    return b"".join(lines)


def roots(original, output):
    original, output = Path(original).absolute(), Path(output).absolute()
    for path in (original, output):
        # Check all existing ancestors, including junctions above the workspace.
        for parent in (path, *path.parents):
            rt.safe_path(parent, "compat-path-check")
    for first, second in ((original, output), (rt.BUNDLE, output)):
        a, b = first.resolve(), second.resolve()
        rt.require(not a.is_relative_to(b) and not b.is_relative_to(a), "compat_roots_overlap")
    return original, output


def source_refs():
    return [rt.reference(REPO / name, REPO) for name in SOURCES]


def tool(lock, name):
    matches = [row for row in lock["tools"] if row["directory"] == "tools/" + name]
    rt.require(len(matches) == 1, "compat_tool_set")
    return matches[0]


def inputs(original, output, lock, reviewed_sha):
    cmake = tool(lock, "cmake")
    modules = [row for row in cmake["inventory"] if row["file"].endswith("/" + MODULE) or row["file"] == MODULE]
    rt.require(len(modules) == 1, "compat_module_set")
    module = modules[0]
    source = rt.safe_path(original / cmake["directory"], module["file"])
    rt.check_refs(original / cmake["directory"], [module])
    patched = patch_module(source.read_bytes())
    derived = dict(module, sha256=rt.digest(patched), size_bytes=len(patched))
    expected = [derived if row == module else row for row in cmake["inventory"]]
    compilers = [canonical_compiler(prep.executable(original, lock, "llvm", name))
                 for name in ("clang.exe", "clang++.exe")]
    old_probe = lock["runtime_bindings"]["optional_ld_query"]
    prefix = cmake["directory"] + "/"
    rt.require(old_probe["module"]["file"].startswith(prefix), "compat_probe_mapping")
    mapped = dict(old_probe, module=dict(old_probe["module"], file="cmake/" + old_probe["module"]["file"][len(prefix):]))
    licenses = [dict(row, file="cmake/" + row["file"][len(prefix):])
                for row in lock["licenses"] if row["file"].startswith(prefix)]
    rt.require(licenses, "compat_cmake_license")
    return {"original_root": str(original), "review_artifact_sha256": reviewed_sha,
            "actual_acquisition": rt.reference(original / "acquisition.json", original),
            "engine_commit": lock["engine_commit"], "bundle": lock["bundle"], "source": lock["source"],
            "original_input_payload_bytes": sum(row["size_bytes"] for row in lock["payload"]),
            "original_input_size_scope": "Accepted payload list; excludes original metadata and closed build outputs.",
            "licenses": lock["licenses"], "original_cmake": cmake,
            "compiler_paths": compilers, "original_runtime_bindings": lock["runtime_bindings"],
            "derived_inventory": expected, "derived_licenses": licenses, "optional_ld_query": mapped,
            "transformation": {"file": module["file"], "line": 125, "original": module, "derived": derived,
                               "from": OLD.decode(), "to": NEW.decode(), "scope": "canonical_single_c_cxx_paths_only"}}, patched


def copy_cmake(original, output, record, patched):
    cmake = record["original_cmake"]
    rt.check_refs(original / cmake["directory"], cmake["inventory"], exact=True)
    destination = output / "cmake"
    destination.mkdir()
    total = rt.disk_bytes(output)
    for row in cmake["inventory"]:
        source = rt.safe_path(original / cmake["directory"], row["file"])
        raw = source.read_bytes()
        rt.require(len(raw) == row["size_bytes"] and rt.digest(raw) == row["sha256"], "compat_copy_source_changed")
        if row["file"] == record["transformation"]["file"]:
            rt.require(patch_module(raw) == patched, "compat_patch_changed")
            raw = patched
        total += len(raw)
        rt.require(total <= rt.DISK, "disk_budget")
        target = rt.safe_path(destination, row["file"])
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            rt.require(stream.write(raw) == len(raw), "compat_short_write")
    rt.check_refs(destination, record["derived_inventory"], exact=True)
    rt.check_refs(output, record["derived_licenses"])
    rt.disk_bytes(output)


def executables(original, output, lock):
    cmake_original = prep.executable(original, lock, "cmake", "cmake.exe")
    cmake_root = original / tool(lock, "cmake")["directory"]
    cmake = rt.safe_path(output / "cmake", cmake_original.relative_to(cmake_root).as_posix())
    ninja = prep.executable(original, lock, "ninja", "ninja.exe")
    cc, cxx = [prep.executable(original, lock, "llvm", name) for name in ("clang.exe", "clang++.exe")]
    allowed = []
    for row in lock["tools"]:
        root = output / "cmake" if row["directory"] == "tools/cmake" else original / row["directory"]
        allowed.extend(rt.safe_path(root, item["file"]) for item in row["inventory"] if Path(item["file"]).name.lower() in TOOLS)
    allowed.extend(rt.safe_path(original, edge["driver"]["file"]) for edge in lock["runtime_bindings"]["wrapper_driver_edges"])
    if "SystemRoot" in os.environ:
        allowed.append(Path(os.environ["SystemRoot"]) / "System32/conhost.exe")
    return cmake, ninja, cc, cxx, allowed


def check_inputs(original, output, record, reviewed_sha):
    lock = prep.check_acquired(original, reviewed_sha)
    expected, _ = inputs(original, output, lock, reviewed_sha)
    rt.require(record == expected, "compat_input_binding")
    rt.check_refs(rt.BUNDLE, record["bundle"], exact=True)
    rt.check_refs(output / "cmake", record["derived_inventory"], exact=True)
    rt.check_refs(output, record["derived_licenses"])
    return lock


def receipt_ok(root, name):
    row = rt.load(root / (name + ".json"))
    rt.require(row.get("status") == "process_exited_zero_not_semantic_success" and row.get("exit") == 0
               and row.get("within_shared_deadline") is True and row["cleanup"]["all_absent"]
               and not row["cleanup"]["errors"], "compat_runner_failed")


def failure_record(path, data, error):
    try:
        rt.write(path, data)
    except Exception as reporting_error:  # noqa: BLE001 - preserve the first failure if reporting also fails
        error.add_note("compat_failure_record_failed:" + type(reporting_error).__name__)


def build(original, output, reviewed_sha, runner=rt.run_owned, clock=time.monotonic):
    original, output = roots(original, output)
    rt.require(not output.exists(), "compat_build_once")
    lock = prep.check_acquired(original, reviewed_sha)
    record, patched = inputs(original, output, lock, reviewed_sha)
    sources = source_refs()
    output.mkdir(parents=True)
    rt.write(output / "build-issued.json", {"original_root": str(original), "review_artifact_sha256": reviewed_sha,
             "sources": sources, "retry": False, "shared_runner_seconds": 900, "whole_cli_900_bound": False})
    try:
        copy_cmake(original, output, record, patched)
        cmake, ninja, cc, cxx, allowed = executables(original, output, lock)
        deadline = clock() + 900
        env = rt.clean_environment([cc.parent, cmake.parent, ninja.parent], output, "build-tmp")
        probe = prep.optional_probe_guard(output, record["optional_ld_query"], env, cmake.parent)
        trace = output / "configure-trace.jsonl"
        configure = [cmake, "-S", rt.BUNDLE, "-B", output / "build", "-G", "Ninja", "--trace-expand",
                     "--trace-format=json-v1", "--trace-redirect=" + str(trace), "-DLLAMA_SOURCE=" + str(original / "source"),
                     "-DCMAKE_C_COMPILER=" + str(cc), "-DCMAKE_CXX_COMPILER=" + str(cxx),
                     "-DCMAKE_MAKE_PROGRAM=" + str(ninja), "-DCMAKE_BUILD_TYPE=Release"]
        rt.write(output / "build-attempt.json", {"command": list(map(str, configure)), "inputs": record,
                 "optional_probe_preflight": probe, "deadline_seconds": 900, "retry": False})
        kwargs = {"cwd": output, "env": env, "root": output, "deadline": deadline, "rss": 2 * 1024**3,
                  "host": 2 * 1024**3, "start": 4 * 1024**3, "allowed": allowed}
        runner(configure, log_prefix=output / "configure", **kwargs)
        receipt_ok(output, "configure")
        rt.require(probe == prep.optional_probe_guard(output, record["optional_ld_query"], env, cmake.parent), "optional_probe_changed")
        traced = prep.audit_trace(trace, allowed, probe, output)
        runner([cmake, "--build", output / "build", "--target", "summary-grammar-validator", "--parallel", "2"],
               log_prefix=output / "compile", **kwargs)
        receipt_ok(output, "compile")
        check_inputs(original, output, record, reviewed_sha)
        rt.check_refs(REPO, sources)
        exe = rt.safe_path(output, "build/bin/summary-grammar-validator.exe")
        rt.require(exe.is_file(), "validator_missing")
        result = {"schema": SCHEMA, "status": STATUS, "workspace": str(output), "inputs": record, "sources": sources,
                  "executable": rt.reference(exe, output), "configure_trace": rt.reference(trace, output), "trace_commands": traced,
                  "issued": rt.reference(output / "build-issued.json", output),
                  "attempt": rt.reference(output / "build-attempt.json", output),
                  "cleanup_receipts": [rt.reference(output / (name + ".json"), output) for name in ("configure", "compile")],
                  "build_logs": [rt.reference(output / (name + ext), output) for name in ("configure", "compile") for ext in (".stdout", ".stderr")],
                  "native_batch_runs": 0, "disk_bytes": rt.disk_bytes(output), "whole_cli_900_bound": False,
                  "disk_scope": "4 GiB writable derivative/build/temp output only; original inputs remain separate read-only. No combined peak bound."}
        rt.write_bounded(output, output / "build-manifest.json", result)
        return result
    except Exception as error:
        failure_record(output / "build-failure.json", {"error": type(error).__name__, "reason": str(error), "no_retry": True,
                       "partial_files_preserved": True, "driver_does_not_write_original_inputs": True,
                       "original_input_preservation": "Not inferred on failure; requires separate closeout."}, error)
        raise


def check_build(output, build_sha):
    output = Path(output).absolute()
    rt.require(not (output / "build-failure.json").exists(), "compat_build_failed")
    manifest = rt.reviewed(output / "build-manifest.json", build_sha)
    rt.require(manifest.get("schema") == SCHEMA and manifest.get("status") == STATUS
               and manifest.get("workspace") == str(output), "compat_build_contract")
    record = manifest["inputs"]
    original, output = roots(record["original_root"], output)
    rt.require(manifest["sources"] == source_refs(), "compat_driver_changed")
    check_inputs(original, output, record, record["review_artifact_sha256"])
    rt.require(manifest["executable"]["file"] == "build/bin/summary-grammar-validator.exe"
               and manifest["configure_trace"]["file"] == "configure-trace.jsonl"
               and manifest["issued"]["file"] == "build-issued.json" and manifest["attempt"]["file"] == "build-attempt.json"
               and [row["file"] for row in manifest["cleanup_receipts"]] == ["configure.json", "compile.json"]
               and [row["file"] for row in manifest["build_logs"]] == [name + ext for name in ("configure", "compile") for ext in (".stdout", ".stderr")],
               "compat_build_references")
    rt.check_refs(output, [manifest["executable"], manifest["configure_trace"], manifest["issued"], manifest["attempt"],
                          *manifest["cleanup_receipts"], *manifest["build_logs"]])
    for name in ("configure", "compile"):
        receipt_ok(output, name)
    return manifest


def verify(output, build_sha, result_name="engine-check", runner=rt.run_owned, ps=None, clock=time.monotonic):
    output = Path(output).absolute()
    rt.require(isinstance(result_name, str) and "/" not in result_name
               and result_name not in {"cmake", "build", "build-tmp"}, "compat_result_directory")
    result = rt.safe_path(output, result_name)
    rt.require(not result.exists() and not (output / "native-issued.json").exists(), "native_once")
    manifest = check_build(output, build_sha)
    rows, carrier = rt.bundle()
    if ps is None:
        import psutil as ps
    native.prior_absent(output, manifest, ps)
    batch = native.encode_batch(rows)
    grammar = (rt.BUNDLE / "candidate.gbnf").read_bytes()
    rt.write(output / "native-issued.json", {"reviewed_build_sha256": build_sha, "result": result_name,
             "batch_sha256": rt.digest(batch), "grammar_sha256": rt.digest(grammar), "native_cases": len(rows),
             "carrier_rejected": carrier, "expected_before_run": rt.reference(rt.BUNDLE / "expected.json", rt.BUNDLE),
             "witnesses_before_run": rt.reference(rt.BUNDLE / "prefix-witnesses.json", rt.BUNDLE), "retry": False})
    try:
        result.mkdir()
        (result / "batch.bin").write_bytes(batch)
        (result / "grammar.gbnf").write_bytes(grammar)
        executable = rt.safe_path(output, manifest["executable"]["file"])
        deadline = clock() + 60
        allowed = [executable]
        if "SystemRoot" in os.environ:
            allowed.append(Path(os.environ["SystemRoot"]) / "System32/conhost.exe")
        process = runner([executable, result / "grammar.gbnf", result / "batch.bin"], cwd=result,
                         env=rt.clean_environment([executable.parent], output, result_name + "/tmp"), root=output,
                         log_prefix=result / "engine", deadline=deadline, rss=512 * 1024**2,
                         host=2 * 1024**3, start=5 * 1024**3 // 2, allowed=allowed, ps=ps, clock=clock)
        receipt_ok(result, "engine")
        parsed = native.protocol((result / "engine.stdout").read_bytes(), rows)
        rt.require(clock() <= deadline, "whole_batch_deadline")
        rt.require((result / "batch.bin").read_bytes() == batch and (result / "grammar.gbnf").read_bytes() == grammar, "batch_input_changed")
        rt.check_refs(output, [manifest["executable"]])
        rt.check_refs(REPO, manifest["sources"])
        rt.bundle()
        data = {"status": "FINITE_ENGINE_CHECK_PASS_NOT_PRODUCT_ACCEPTANCE", "native_cases": len(rows),
                "carrier_rejections": carrier, "total_manifest_cases": 106, "prefix_witnesses": 10,
                "engine": parsed, "process": process, "reviewed_build_sha256": build_sha,
                "review_artifact_sha256": manifest["inputs"]["review_artifact_sha256"],
                "actual_acquisition": manifest["inputs"]["actual_acquisition"], "model_tokenizer_calls": 0,
                "semantics_verified": False, "all_strings_equivalent": False,
                "limit_scope": "sampled stop thresholds; not OS hard peak bounds"}
        rt.write_bounded(output, result / "result.json", data)
        return data
    except Exception as error:
        failure_record(result / "failure.json" if result.is_dir() else output / "native-failure.json",
                       {"status": "FAILED_NO_RETRY", "error": type(error).__name__,
                        "reason": str(error), "partial_output_preserved": True, "model_calls": 0}, error)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["build", "verify"])
    parser.add_argument("--workspace", type=Path, required=True, help="New disjoint derivative/build output; never the acquisition workspace.")
    parser.add_argument("--acquisition-workspace", type=Path)
    parser.add_argument("--reviewed-acquisition-sha256")
    parser.add_argument("--reviewed-build-sha256")
    parser.add_argument("--result-name", default="engine-check")
    args = parser.parse_args()
    if args.operation == "build":
        rt.require(args.acquisition_workspace is not None and args.reviewed_build_sha256 is None, "compat_build_arguments")
        result = build(args.acquisition_workspace, args.workspace, args.reviewed_acquisition_sha256)
    else:
        rt.require(args.acquisition_workspace is None and args.reviewed_acquisition_sha256 is None, "compat_verify_arguments")
        result = verify(args.workspace, args.reviewed_build_sha256, args.result_name)
    print(result["status"])


if __name__ == "__main__":
    try:
        main()
    except (rt.BoundaryError, OSError, ValueError) as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        raise SystemExit(1) from error
