"""Build a separately reviewed CMake derivative; never alter acquired inputs.

Only canonical single C/CXX compiler paths are supported. The one-line legacy
conversion is not a general substitute for cmake_path NORMALIZE. Copy/input
checks are outside the existing shared 900-second configure/compile budget.
Native verification remains a separately reviewed, model-free, one-shot batch.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import re
import stat
import sys
import time
from pathlib import Path, PureWindowsPath
from types import CodeType

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
LIVE_SCAN_POLICY = "compat-owned-active-lstat-v1"
RUNTIME_SHA256 = "b1422ea8466d127b38493d8b05c893483aa8c554d65ed7ffe0d3bb06961009c8"
OWNED_RUN_CODE = rt.run_owned.__code__
OWNED_SCAN_CODES = [code for code in OWNED_RUN_CODE.co_consts if isinstance(code, CodeType) and code.co_name == "scan_checkpoint"]
rt.require(len(OWNED_SCAN_CODES) == 1, "live_scan_runtime_code")
OWNED_SCAN_CODE = OWNED_SCAN_CODES[0]
BASE_OWNED_TREE = rt.OwnedTree
NINJA_SHELL_POLICY = "compat-owned-ninja-shell-v1"
RECIPE_LIMIT = 8 * 1024**2
CONDA_HOOK_SHA256 = "6b9042735e64563efdeaeefe2f4f6b599094f3cc67b7d11c8f91a5e1cfe03a7e7"
CONDA_HOOK_GUARD = "@IF DEFINED CONDA_SHLVL GOTO :EOF"


def shell_path(path):
    value = str(path)
    rt.require(value and not any(ord(c) < 32 or c in '&|<>^()%!"' for c in value), "ninja_shell_unsafe_path")
    return Path(path)


def autorun_hook_reference(value):
    path = Path(value)
    rt.safe_path(path.parent, path.name)
    attrs = path.lstat()
    rt.require(stat.S_ISREG(attrs.st_mode) and not getattr(attrs, "st_file_attributes", 0) & 1024
               and attrs.st_size <= 64 * 1024 and str(path.resolve()) == str(path), "ninja_shell_hook_file")
    with path.open("rb") as stream:
        raw = stream.read(64 * 1024 + 1)
    rt.require(len(raw) == attrs.st_size <= 64 * 1024, "ninja_shell_hook_file")
    lines = [line.strip() for line in raw.decode("utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("::")]
    return {"path": str(path), "size_bytes": len(raw), "sha256": rt.digest(raw),
            "first_statement": lines[0] if lines else None}


def check_autorun(reader, hook_reader=autorun_hook_reference):
    rows = []
    for hive in ("HKCU", "HKLM"):
        value = reader(hive)
        row = {"hive": hive, "view": 64, "value": value}
        if value is not None and value != "":
            rt.require(hive == "HKCU" and type(value) is str, "ninja_shell_autorun")
            match = re.fullmatch(r'if exist "([^"\r\n]+)" "\1"', value)
            rt.require(match is not None, "ninja_shell_autorun")
            path = canonical_compiler(match[1])
            rt.require(PureWindowsPath(path).parts[-2:] == ("condabin", "conda_hook.bat"), "ninja_shell_hook_path")
            shell_path(path)
            hook = hook_reader(path)
            rt.require(hook.get("path") == path and hook.get("sha256") == CONDA_HOOK_SHA256
                       and hook.get("first_statement") == CONDA_HOOK_GUARD
                       and type(hook.get("size_bytes")) is int and 0 < hook["size_bytes"] <= 64 * 1024,
                       "ninja_shell_hook_binding")
            row["hook"] = hook
        rows.append(row)
    return rows


def check_extensions(reader):
    values = {hive: reader(hive) for hive in ("HKCU", "HKLM")}
    rt.require(all(value is None or type(value) is int and value in (0, 1) for value in values.values()), "ninja_shell_extensions_type")
    effective = values["HKCU"] if values["HKCU"] is not None else values["HKLM"]
    rt.require(effective in (None, 1), "ninja_shell_extensions_disabled")
    return {"view": 64, "values": values, "effective_enabled": True}


def shell_child_environment(env, environment):
    """Copy only: clean_environment strips CONDA variables, so apply afterwards."""
    result = dict(env)
    expected = {"CONDA_SHLVL": "0"} if any("hook" in row for row in environment["autorun"]) else {}
    rt.require(environment.get("child_env", {}) == expected, "ninja_shell_child_env_policy")
    if expected:
        rt.require(environment.get("extensions", {}).get("effective_enabled") is True, "ninja_shell_extensions_disabled")
    result.update(expected)
    return result


def shell_environment():
    """Read-only native System32/64-bit registry view; never change AutoRun."""
    rt.require(os.name == "nt" and ctypes.sizeof(ctypes.c_void_p) == 8, "ninja_shell_windows_x64")
    import winreg
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.GetSystemDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    api.GetSystemDirectoryW.restype = ctypes.c_uint32
    buffer = ctypes.create_unicode_buffer(32768)
    size = api.GetSystemDirectoryW(buffer, len(buffer))
    rt.require(0 < size < len(buffer), "ninja_shell_system_directory")
    command = shell_path(Path(buffer.value) / "cmd.exe").resolve()
    rt.safe_path(command.parent, command.name)
    rt.require(command.is_file(), "ninja_shell_system_command")

    def reader(hive, name="AutoRun"):
        key = winreg.HKEY_CURRENT_USER if hive == "HKCU" else winreg.HKEY_LOCAL_MACHINE
        try:
            with winreg.OpenKey(key, r"Software\Microsoft\Command Processor", 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as handle:
                value, kind = winreg.QueryValueEx(handle, name)
                rt.require(kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) if name == "AutoRun" else kind == winreg.REG_DWORD,
                           "ninja_shell_registry_type")
                return value
        except FileNotFoundError:
            return None

    autorun = check_autorun(reader)
    child_env = {"CONDA_SHLVL": "0"} if any("hook" in row for row in autorun) else {}
    return {"command": str(command), "command_reference": rt.reference(command, command.parent),
            "autorun": autorun, "extensions": check_extensions(lambda hive: reader(hive, "EnableExtensions")),
            "child_env": child_env, "registry_writes": 0}


class NinjaShellPolicy:
    """Trust only fixed-input Ninja recipes and the live owned process lineage.

    The shell body is recorded, not interpreted as a general Windows language.
    This exception is unsuitable for builds containing user-controlled recipes.
    """
    def __init__(self, output, ninja, cmake, environment, source=None):
        self.output = shell_path(output).resolve()
        self.build = self.output / "build"
        self.ninja, self.cmake = (os.path.normcase(str(shell_path(path).resolve())) for path in (ninja, cmake))
        self.source = shell_path(rt.BUNDLE if source is None else source).resolve()
        self.command = os.path.normcase(str(Path(environment["command"]).resolve()))
        shell_child_environment({}, environment)
        self.environment, self.recipes, self.accepted = environment, {}, []
        self.ninja_ref = rt.reference(Path(ninja), Path(ninja).parent)
        self.record = {"policy": NINJA_SHELL_POLICY, "environment": environment, "ninja": str(Path(ninja).resolve()),
                       "ninja_reference": self.ninja_ref, "cmake": str(Path(cmake).resolve()),
                       "canonical_output": str(self.output), "shells": self.accepted}

    def phase(self, tree, ninja):
        process = ninja
        for _ in range(32):
            process = tree.ps.Process(process.ppid())
            identity = tree.identity(process)
            rt.require(identity in tree.seen and process.is_running(), "ninja_shell_unowned_ancestor")
            if identity[2] == self.cmake:
                argv = process.cmdline()
                rt.require(argv and os.path.normcase(str(Path(argv[0]).resolve())) == self.cmake, "ninja_shell_cmake_argv")
                if "--build" in argv:
                    index = argv.index("--build")
                    rt.require(index + 1 < len(argv) and Path(argv[index + 1]).resolve() == self.build, "ninja_shell_phase")
                    return "compile"
                if "-B" in argv and "-S" in argv:
                    index, source = argv.index("-B"), argv.index("-S")
                    rt.require(index + 1 < len(argv) and source + 1 < len(argv)
                               and Path(argv[index + 1]).resolve() == self.build
                               and Path(argv[source + 1]).resolve() == self.source, "ninja_shell_phase")
                    return "configure"
        raise rt.BoundaryError("ninja_shell_phase")

    def recipe_refs(self, cwd):
        rows = []
        for name in ("build.ninja", "CMakeFiles/rules.ninja"):
            path = rt.safe_path(cwd, name)
            before = path.lstat()
            rt.require(stat.S_ISREG(before.st_mode) and not getattr(before, "st_file_attributes", 0) & 1024
                       and before.st_size <= RECIPE_LIMIT, "ninja_shell_recipe")
            with path.open("rb") as stream:
                raw = stream.read(RECIPE_LIMIT + 1)
            after = path.lstat()
            rt.require(len(raw) == before.st_size <= RECIPE_LIMIT
                       and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                       == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), "ninja_shell_recipe_changed")
            rows.append({"file": name, "sha256": rt.digest(raw), "size_bytes": len(raw)})
        return rows

    def admit(self, tree, process, identity):
        rt.require(identity[2] == self.command, "unexpected_child_executable")
        rt.check_refs(Path(self.environment["command"]).parent, [self.environment["command_reference"]])
        args = process.cmdline()
        rt.require(len(args) == 3 and args[1] == "/C" and isinstance(args[2], str) and args[2]
                   and not any(c in args[2] for c in "\x00\r\n")
                   and (args[0].lower() == "cmd.exe" or os.path.normcase(str(Path(args[0]).resolve())) == self.command),
                   "ninja_shell_argv")
        parent = tree.ps.Process(process.ppid())
        parent_identity = tree.identity(parent)
        rt.require(parent_identity in tree.seen and parent_identity[2] == self.ninja
                   and parent_identity[1] <= identity[1] and parent.is_running(), "ninja_shell_parent")
        for name, value in self.environment.get("child_env", {}).items():
            rt.require(process.environ().get(name) == value and parent.environ().get(name) == value, "ninja_shell_child_env")
        parent_args = parent.cmdline()
        rt.require(parent_args and os.path.normcase(str(Path(parent_args[0]).resolve())) == self.ninja
                   and not any(arg.startswith(("-f", "--file")) for arg in parent_args[1:]), "ninja_shell_recipe_override")
        rt.check_refs(Path(self.ninja).parent, [self.ninja_ref])
        phase = self.phase(tree, parent)
        cwd, parent_cwd = Path(process.cwd()).resolve(), Path(parent.cwd()).resolve()
        rt.require(cwd == parent_cwd and cwd.is_relative_to(self.build), "ninja_shell_cwd")
        rt.safe_path(self.output, cwd.relative_to(self.output).as_posix())
        refs = self.recipe_refs(cwd)
        previous = self.recipes.setdefault(parent_identity, {"cwd": str(cwd), "recipes": refs})
        rt.require(previous == {"cwd": str(cwd), "recipes": refs}, "ninja_shell_recipe_changed")
        row = {"identity": list(identity), "parent_identity": list(parent_identity), "phase": phase,
               "cwd": str(cwd), "argv": args, "recipes": refs}
        previous_shell = next((item for item in self.accepted if item["identity"] == list(identity)), None)
        rt.require(previous_shell is None or previous_shell == row, "ninja_shell_identity_changed")
        if previous_shell is None:
            self.accepted.append(row)


class NinjaOwnedTree(BASE_OWNED_TREE):
    """Shared by inner runner and external observer; cmd is never allowlisted."""
    def __init__(self, *args, shell_policy, **kwargs):
        super().__init__(*args, **kwargs)
        self.shell_policy = shell_policy
        rt.require(shell_policy.command not in self.allowed, "ninja_shell_general_allowlist")

    def capture(self, process):
        identity = self.identity(process)
        self.seen[identity] = process  # Failed admission must still retain cleanup ownership.
        if identity[2] not in self.allowed:
            self.shell_policy.admit(self, process, identity)


class NinjaShellScope:
    def __init__(self, policy, phase):
        self.policy, self.original = policy, rt.OwnedTree
        self.record = {"phase": phase, "restored": False}

    def run(self, runner, argv, **kwargs):
        rt.require(rt.OwnedTree is self.original is BASE_OWNED_TREE, "ninja_shell_adapter_changed")
        policy, error = self.policy, None

        class BoundTree(NinjaOwnedTree):
            def __init__(self, *args, **kw):
                super().__init__(*args, shell_policy=policy, **kw)

        rt.OwnedTree = BoundTree
        try:
            return runner(argv, **kwargs)
        except BaseException as exc:
            error = exc
            raise
        finally:
            changed = rt.OwnedTree is not BoundTree
            rt.OwnedTree = self.original
            self.record["restored"] = rt.OwnedTree is self.original
            if changed:
                if error is None:
                    raise rt.BoundaryError("ninja_shell_adapter_changed")
                error.add_note("ninja_shell_adapter_changed_before_restore")


def live_scan_policy():
    path = Path(rt.__file__).resolve()
    reference = rt.reference(path, path.parents[2])
    rt.require(reference["sha256"] == RUNTIME_SHA256 and rt.run_owned.__code__ is OWNED_RUN_CODE, "live_scan_runtime_changed")
    return {"policy": LIVE_SCAN_POLICY, "original_runtime": reference,
            "scope": "Exact run_owned scan_checkpoint code object and designated native output root only; all other scans strict."}


class LiveDiskScan:
    """Serial per-run adapter; never installed during input checks or publication."""
    def __init__(self, output, native_root, paths, phase):
        self.output, self.root, self.paths = Path(output).resolve(), Path(native_root), paths
        self.original = rt.disk_bytes
        self.identity = (self.output.stat().st_dev, self.output.stat().st_ino)
        self.record = {"phase": phase, "canonical_root": str(self.output), "native_root": str(native_root),
                       "active_scans": 0, "disappeared_entries": 0, "restored": False}

    def valid_root(self):
        self.paths.check()
        rt.safe_path(self.output, "live-scan-root-check")
        attrs = self.output.lstat()
        rt.require(stat.S_ISDIR(attrs.st_mode) and not stat.S_ISLNK(attrs.st_mode)
                   and not getattr(attrs, "st_file_attributes", 0) & 1024
                   and (attrs.st_dev, attrs.st_ino) == self.identity, "live_scan_root_changed")
        rt.require(str(self.paths.path(self.output)) == str(self.root)
                   and self.root.resolve() == self.output and self.root.samefile(self.output), "live_scan_root_changed")

    def dispatch(self, root, checkpoint=None):
        if getattr(checkpoint, "__code__", None) is not OWNED_SCAN_CODE or str(root) != str(self.root):
            return self.original(root, checkpoint=checkpoint)
        checkpoint("start")
        self.valid_root()
        self.record["active_scans"] += 1
        total = 0
        for path in Path(root).rglob("*"):
            checkpoint("before_entry")
            rt.safe_path(root, path.relative_to(root).as_posix())
            try:
                attrs = path.lstat()
            except FileNotFoundError:
                # Only this entry's lstat may race a compiler unlink. Root/alias loss is fatal.
                self.valid_root()
                self.record["disappeared_entries"] += 1
                checkpoint("after_entry")
                continue
            rt.require(not stat.S_ISLNK(attrs.st_mode) and not getattr(attrs, "st_file_attributes", 0) & 1024, "reparse_path")
            if stat.S_ISREG(attrs.st_mode):
                total += attrs.st_size
                rt.require(total <= rt.DISK, "disk_budget")
            checkpoint("after_entry")
        self.valid_root()
        checkpoint("complete")
        return total

    def run(self, runner, argv, **kwargs):
        live_scan_policy()
        rt.require(rt.disk_bytes is self.original, "live_scan_adapter_changed")
        replacement, error = self.dispatch, None
        rt.disk_bytes = replacement
        try:
            return runner(argv, **kwargs)
        except BaseException as exc:
            error = exc
            raise
        finally:
            changed = rt.disk_bytes is not replacement
            rt.disk_bytes = self.original
            self.record["restored"] = rt.disk_bytes is self.original
            if changed:
                if error is None:
                    raise rt.BoundaryError("live_scan_adapter_changed")
                error.add_note("live_scan_adapter_changed_before_restore")


class DosDevices:
    """Current Windows DOS namespace only; no subprocess or persistent settings."""
    def __init__(self):
        rt.require(os.name == "nt", "native_drive_windows_only")
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.QueryDosDeviceW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        self.api.QueryDosDeviceW.restype = ctypes.c_uint32
        self.api.DefineDosDeviceW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p]
        self.api.DefineDosDeviceW.restype = ctypes.c_int
        self.api.GetLogicalDrives.restype = ctypes.c_uint32

    def query(self, drive):
        buffer = ctypes.create_unicode_buffer(32768)
        size = self.api.QueryDosDeviceW(drive, buffer, len(buffer))
        if not size:
            code = ctypes.get_last_error()
            if code == 2:  # ERROR_FILE_NOT_FOUND is the only accepted absence.
                return []
            raise ctypes.WinError(code)
        return buffer[:size].rstrip("\0").split("\0")

    def occupied(self, drive):
        mask = self.api.GetLogicalDrives()
        if not mask:
            raise ctypes.WinError(ctypes.get_last_error())
        return bool(mask & (1 << (ord(drive[0]) - ord("A"))))

    def create(self, drive, target):
        if not self.api.DefineDosDeviceW(0x1 | 0x8, drive, target):
            raise ctypes.WinError(ctypes.get_last_error())

    def remove(self, drive, target):
        # RAW_TARGET_PATH | REMOVE_DEFINITION | EXACT_MATCH_ON_REMOVE | NO_BROADCAST_SYSTEM
        if not self.api.DefineDosDeviceW(0x1 | 0x2 | 0x4 | 0x8, drive, target):
            raise ctypes.WinError(ctypes.get_last_error())

    def same(self, alias, canonical):
        alias = Path(alias)
        return alias.resolve() == canonical.resolve() and alias.samefile(canonical)


class NativeDrive:
    """One opt-in lease. Canonical input checks never use its aliases."""
    def __init__(self, drive, output, receipt, backend=None):
        rt.require(drive is None or isinstance(drive, str) and re.fullmatch(r"[D-Z]:", drive), "native_drive_letter")
        self.drive, self.output, self.receipt = drive, output, receipt
        self.backend = backend
        self.target = REPO.resolve()
        self.raw_target = "\\??\\" + str(self.target)
        self.owned, self.children_closed = False, True
        self.record = None

    def __enter__(self):
        if self.drive is None:
            return self
        self.backend = self.backend or DosDevices()
        self.record = {"drive": self.drive, "canonical_repository": str(self.target), "raw_target": self.raw_target,
                       "prior_absent": False, "created": False, "paths": [], "invocations": [], "cleanup": None}
        try:
            rt.require(not self.backend.query(self.drive) and not self.backend.occupied(self.drive), "native_drive_occupied")
            self.record["prior_absent"] = True
            self.backend.create(self.drive, self.raw_target)
            self.owned = self.record["created"] = True
            self.check()
            self.path(self.target)
            return self
        except Exception as error:
            self.__exit__(type(error), error, error.__traceback__)
            raise

    def check(self):
        if self.drive:
            rt.require(self.owned and self.backend.query(self.drive) == [self.raw_target], "native_drive_changed")

    def path(self, path):
        path = Path(path)
        if self.drive is None:
            return path
        self.check()
        canonical = path.resolve()
        rt.require(canonical.is_relative_to(self.target), "native_drive_outside_repository")
        alias = PureWindowsPath(self.drive + "\\") / canonical.relative_to(self.target)
        rt.require(str(alias).isascii(), "native_drive_non_ascii_suffix")
        # For outputs not yet created, bind their nearest existing ancestor.
        ancestor, alias_ancestor = canonical, alias
        while not ancestor.exists():
            ancestor, alias_ancestor = ancestor.parent, alias_ancestor.parent
        rt.require(self.backend.same(alias_ancestor, ancestor), "native_drive_identity")
        row = {"canonical": str(canonical), "alias": str(alias)}
        if row not in self.record["paths"]:
            self.record["paths"].append(row)
        return alias

    def environment(self, env):
        if self.drive is None:
            return env
        mapped = dict(env)
        mapped["PATH"] = ";".join(str(self.path(p)) for p in env["PATH"].split(os.pathsep))
        for name in ("TEMP", "TMP"):
            mapped[name] = str(self.path(env[name]))
        rt.require(all(str(value).isascii() for value in mapped.values()), "native_drive_environment_not_ascii")
        return mapped

    def run(self, runner, argv, **kwargs):
        if self.drive is None:
            return runner(argv, **kwargs)
        self.check()
        self.record["invocations"].append({"argv": list(map(str, argv)),
            **{name: str(kwargs[name]) for name in ("cwd", "root", "log_prefix")}, "env": kwargs["env"]})
        rt.write_bounded(self.output, self.output / (self.receipt + f"-attempt-{len(self.record['invocations'])}.json"), self.record)
        self.children_closed = False
        try:
            result = runner(argv, **kwargs)
        except Exception as error:
            receipt = getattr(error, "supervision_record", {})
            self.children_closed = receipt.get("cleanup", {}).get("all_absent") is True
            raise
        else:
            self.children_closed = result.get("cleanup", {}).get("all_absent") is True
            self.check()
            return result

    def __exit__(self, kind, error, traceback):
        if self.drive is None:
            return False
        cleanup_error = None
        self.record["cleanup"] = {"children_closed": self.children_closed, "removed": False}
        try:
            if self.owned:
                rt.require(self.children_closed, "native_drive_children_unconfirmed")
                self.check()
                self.backend.remove(self.drive, self.raw_target)
                self.owned = False
                rt.require(not self.backend.query(self.drive), "native_drive_cleanup_changed")
                self.record["cleanup"]["removed"] = True
        except Exception as exc:  # noqa: BLE001 - cleanup must never replace the primary native failure
            cleanup_error = exc
            self.record["cleanup"]["error"] = type(exc).__name__ + ":" + str(exc)
        try:
            rt.write_bounded(self.output, self.output / (self.receipt + ".json"), self.record)
        except Exception as exc:  # noqa: BLE001 - retain mapping cleanup and original failure
            if cleanup_error is None:
                cleanup_error = exc
            else:
                cleanup_error.add_note("native_drive_receipt_failed:" + type(exc).__name__)
        if cleanup_error is not None:
            if error is None:
                raise cleanup_error
            error.add_note("native_drive_cleanup_failed:" + str(cleanup_error))
        return False


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


def check_drive_history(output, manifest):
    """Validate saved canonical bindings without reopening an expired drive lease."""
    record = manifest.get("native_drive")
    receipt = manifest.get("native_drive_receipt")
    attempt = rt.load(output / "build-attempt.json")
    if record is None:
        rt.require(receipt is None and attempt.get("native_drive") is None, "native_drive_history")
        return
    rt.require(isinstance(record, dict) and re.fullmatch(r"[D-Z]:", record.get("drive", ""))
               and record.get("canonical_repository") == str(REPO.resolve())
               and record.get("raw_target") == "\\??\\" + str(REPO.resolve())
               and record.get("prior_absent") is True and record.get("created") is True
               and record.get("cleanup") == {"children_closed": True, "removed": True}
               and isinstance(receipt, dict) and receipt.get("file") == "build-native-drive.json", "native_drive_history")
    rt.check_refs(output, [receipt])
    rt.require(rt.load(output / receipt["file"]) == record, "native_drive_history")
    def alias(path):
        canonical = Path(path).resolve()
        rt.require(canonical.is_relative_to(REPO.resolve()), "native_drive_history_path")
        return str(PureWindowsPath(record["drive"] + "\\") / canonical.relative_to(REPO.resolve()))
    rt.require(record.get("paths") and all(row == {"canonical": str(Path(row["canonical"]).resolve()), "alias": alias(row["canonical"])}
                                          and row["alias"].isascii() for row in record["paths"]), "native_drive_history_path")
    invocations = record.get("invocations", [])
    rt.require(len(invocations) == 2, "native_drive_history_invocations")
    planned = attempt.get("native_drive", {})
    rt.require(all(planned.get(name) == record[name] for name in ("drive", "canonical_repository", "raw_target", "prior_absent", "created"))
               and planned.get("cleanup") is None and planned.get("invocations") == []
               and all(row in record["paths"] for row in planned.get("paths", [])), "native_drive_history")
    for name, invocation in zip(("configure", "compile"), invocations, strict=True):
        saved = rt.load(output / (name + ".json"))
        rt.require(invocation["argv"] == saved["argv"] and invocation["root"] == alias(output)
                   and invocation["cwd"] == alias(output) and invocation["log_prefix"] == alias(output / name)
                   and invocation["env"]["TEMP"] == invocation["env"]["TMP"] == alias(output / "build-tmp")
                   and saved["temporary_directory"] == invocation["env"]["TEMP"]
                   and all(PureWindowsPath(p).is_relative_to(record["drive"] + "\\") for p in invocation["env"]["PATH"].split(";"))
                   and all(value.isascii() for value in invocation["env"].values()), "native_drive_history_invocations")
    rt.require(invocations[0]["argv"] == attempt["command"], "native_drive_history_invocations")


def check_live_scan_history(output, manifest):
    policy = live_scan_policy()
    attempt = rt.load(output / "build-attempt.json")
    saved = manifest.get("live_disk_scan", {})
    rt.require(attempt.get("live_disk_scan") == policy
               and {key: saved.get(key) for key in policy} == policy, "live_scan_history")
    phases = saved.get("phases", [])
    drive = manifest.get("native_drive")
    native_root = str(PureWindowsPath(drive["drive"] + "\\") / output.resolve().relative_to(REPO.resolve())) if drive else str(output)
    rt.require(len(phases) == 2, "live_scan_history")
    for name, row in zip(("configure", "compile"), phases, strict=True):
        rt.require(row.get("phase") == name and row.get("restored") is True
                   and row.get("canonical_root") == str(output.resolve()) and row.get("native_root") == native_root
                   and type(row.get("active_scans")) is int and row["active_scans"] >= 0
                   and type(row.get("disappeared_entries")) is int and row["disappeared_entries"] >= 0,
                   "live_scan_history")


def check_shell_history(output, manifest):
    saved = manifest.get("ninja_shell", {})
    attempt = rt.load(output / "build-attempt.json").get("ninja_shell", {})
    rt.require(saved.get("policy") == NINJA_SHELL_POLICY and saved.get("canonical_output") == str(output.resolve())
               and attempt == {key: value for key, value in saved.items() if key not in ("shells", "phases")}, "ninja_shell_history")
    environment = saved["environment"]
    autorun = environment["autorun"]
    hooks = [row["hook"] for row in autorun if "hook" in row]
    rt.require(autorun == check_autorun(lambda hive: next(row["value"] for row in autorun if row["hive"] == hive),
                                      hook_reader=lambda path: next(row for row in hooks if row["path"] == path)), "ninja_shell_history")
    if "extensions" in environment:
        rt.require(environment["extensions"] == check_extensions(lambda hive: environment["extensions"]["values"][hive]), "ninja_shell_history")
    child_env = shell_child_environment({}, environment)
    rt.require(saved.get("phases") == [{"phase": name, "restored": True} for name in ("configure", "compile")], "ninja_shell_history")
    if child_env and manifest.get("native_drive"):
        rt.require(all(all(invocation["env"].get(key) == value for key, value in child_env.items())
                       for invocation in manifest["native_drive"]["invocations"]), "ninja_shell_child_env_history")
    for row in saved.get("shells", []):
        rt.require(row["phase"] in ("configure", "compile") and Path(row["cwd"]).is_relative_to(output / "build")
                   and row["identity"][2] == os.path.normcase(saved["environment"]["command"])
                   and row["parent_identity"][2] == os.path.normcase(saved["ninja"])
                   and len(row["argv"]) == 3 and row["argv"][1] == "/C"
                   and [ref["file"] for ref in row["recipes"]] == ["build.ninja", "CMakeFiles/rules.ninja"], "ninja_shell_history")


def build(original, output, reviewed_sha, runner=rt.run_owned, clock=time.monotonic, native_drive=None, mapping_backend=None):
    original, output = roots(original, output)
    rt.require(not output.exists(), "compat_build_once")
    lock = prep.check_acquired(original, reviewed_sha)
    record, patched = inputs(original, output, lock, reviewed_sha)
    sources = source_refs()
    scan_policy, scan_phases = live_scan_policy(), []
    shell_env = shell_environment()
    for path in (original, output, REPO, rt.BUNDLE):
        shell_path(path)
    shell_policy, shell_phases = None, []
    output.mkdir(parents=True)
    rt.write(output / "build-issued.json", {"original_root": str(original), "review_artifact_sha256": reviewed_sha,
             "sources": sources, "retry": False, "shared_runner_seconds": 900, "whole_cli_900_bound": False})
    try:
        copy_cmake(original, output, record, patched)
        cmake, ninja, cc, cxx, allowed = executables(original, output, lock)
        for path in (cmake, ninja, cc, cxx):
            shell_path(path)
        shell_policy = NinjaShellPolicy(output, ninja, cmake, shell_env)
        deadline = clock() + 900
        trace = output / "configure-trace.jsonl"
        with NativeDrive(native_drive, output, "build-native-drive", mapping_backend) as paths:
            env = paths.environment(shell_child_environment(
                rt.clean_environment([cc.parent, cmake.parent, ninja.parent], output, "build-tmp"), shell_env))
            native_output, native_cmake = paths.path(output), paths.path(cmake)
            probe = prep.optional_probe_guard(native_output, record["optional_ld_query"], env, native_cmake.parent)
            configure = [native_cmake, "-S", paths.path(rt.BUNDLE), "-B", paths.path(output / "build"), "-G", "Ninja", "--trace-expand",
                         "--trace-format=json-v1", "--trace-redirect=" + str(paths.path(trace)), "-DLLAMA_SOURCE=" + str(paths.path(original / "source")),
                         "-DCMAKE_C_COMPILER=" + str(paths.path(cc)), "-DCMAKE_CXX_COMPILER=" + str(paths.path(cxx)),
                         "-DCMAKE_MAKE_PROGRAM=" + str(paths.path(ninja)), "-DCMAKE_BUILD_TYPE=Release"]
            rt.write(output / "build-attempt.json", {"command": list(map(str, configure)), "inputs": record,
                     "optional_probe_preflight": probe, "deadline_seconds": 900, "retry": False,
                     "native_drive": paths.record, "live_disk_scan": scan_policy,
                     "ninja_shell": {key: value for key, value in shell_policy.record.items() if key != "shells"}})
            kwargs = {"cwd": native_output, "env": env, "root": native_output, "deadline": deadline, "rss": 2 * 1024**3,
                      "host": 2 * 1024**3, "start": 4 * 1024**3, "allowed": allowed}
            configure_scan = LiveDiskScan(output, native_output, paths, "configure")
            scan_phases.append(configure_scan.record)
            configure_shell = NinjaShellScope(shell_policy, "configure")
            shell_phases.append(configure_shell.record)
            paths.run(lambda argv, **kw: configure_shell.run(lambda args, **opts: configure_scan.run(runner, args, **opts), argv, **kw),
                      configure, log_prefix=paths.path(output / "configure"), **kwargs)
            receipt_ok(output, "configure")
            rt.require(probe == prep.optional_probe_guard(native_output, record["optional_ld_query"], env, native_cmake.parent), "optional_probe_changed")
            traced = prep.audit_trace(trace, allowed, probe, output)
            compile_scan = LiveDiskScan(output, native_output, paths, "compile")
            scan_phases.append(compile_scan.record)
            compile_shell = NinjaShellScope(shell_policy, "compile")
            shell_phases.append(compile_shell.record)
            paths.run(lambda argv, **kw: compile_shell.run(lambda args, **opts: compile_scan.run(runner, args, **opts), argv, **kw),
                      [native_cmake, "--build", paths.path(output / "build"), "--target", "summary-grammar-validator", "--parallel", "2"],
                      log_prefix=paths.path(output / "compile"), **kwargs)
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
                  "native_drive": paths.record,
                  "native_drive_receipt": rt.reference(output / "build-native-drive.json", output) if native_drive else None,
                  "live_disk_scan": dict(scan_policy, phases=scan_phases),
                  "ninja_shell": dict(shell_policy.record, phases=shell_phases),
                  "disk_scope": "4 GiB writable derivative/build/temp output only; original inputs remain separate read-only. No combined peak bound."}
        rt.write_bounded(output, output / "build-manifest.json", result)
        return result
    except Exception as error:
        failure_record(output / "build-failure.json", {"error": type(error).__name__, "reason": str(error), "no_retry": True,
                       "live_disk_scan": dict(scan_policy, phases=scan_phases),
                       "ninja_shell": dict(shell_policy.record, phases=shell_phases) if shell_policy else {"environment": shell_env},
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
    check_drive_history(output, manifest)
    check_live_scan_history(output, manifest)
    check_shell_history(output, manifest)
    return manifest


def verify(output, build_sha, result_name="engine-check", runner=rt.run_owned, ps=None, clock=time.monotonic,
           native_drive=None, mapping_backend=None):
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
        with NativeDrive(native_drive, output, "verify-native-drive", mapping_backend) as paths:
            process = paths.run(runner, [paths.path(executable), paths.path(result / "grammar.gbnf"), paths.path(result / "batch.bin")],
                                cwd=paths.path(result), env=paths.environment(rt.clean_environment([executable.parent], output, result_name + "/tmp")),
                                root=paths.path(output), log_prefix=paths.path(result / "engine"), deadline=deadline, rss=512 * 1024**2,
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
                "native_drive": paths.record,
                "native_drive_receipt": rt.reference(output / "verify-native-drive.json", output) if native_drive else None,
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
    parser.add_argument("--native-drive", help="Opt-in unused D: through Z: alias for this repository; removed only after owned children close.")
    args = parser.parse_args()
    if args.operation == "build":
        rt.require(args.acquisition_workspace is not None and args.reviewed_build_sha256 is None, "compat_build_arguments")
        result = build(args.acquisition_workspace, args.workspace, args.reviewed_acquisition_sha256, native_drive=args.native_drive)
    else:
        rt.require(args.acquisition_workspace is None and args.reviewed_acquisition_sha256 is None, "compat_verify_arguments")
        result = verify(args.workspace, args.reviewed_build_sha256, args.result_name, native_drive=args.native_drive)
    print(result["status"])


if __name__ == "__main__":
    try:
        main()
    except (rt.BoundaryError, OSError, ValueError) as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        raise SystemExit(1) from error
