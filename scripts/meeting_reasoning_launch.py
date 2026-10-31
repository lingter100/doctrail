"""Small 9B launch boundaries; the outer owned-process supervisor enforces startup."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading
import time
import zipfile
from pathlib import Path

import psutil

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_reasoning_service import LIMITS, MANIFEST_SHA256, PROFILE
from scripts.prepare_meeting_gguf import inventory, linked, safe_member, verify_file
from tools.summary_grammar.runtime import OwnedTree


def verify_existing_assets(manifest_path, root):
    """Read-only pinned verification. Never extract, download or write old roots."""
    manifest_path, root = Path(manifest_path), Path(root)
    if (linked(manifest_path) or manifest_path.stat().st_size > 65536
            or hashlib.sha256(manifest_path.read_bytes()).hexdigest() != MANIFEST_SHA256):
        raise GenerationError("generation_identity_mismatch")
    spec = json.loads(manifest_path.read_bytes())
    if any(linked(p) or not p.is_dir() for p in (root, root / "downloads", root / "licenses", root / "runtime")):
        raise GenerationError("generation_identity_mismatch")
    model = root / safe_member(spec["gguf"]["filename"])
    model_digest = verify_file(model, spec["gguf"])
    expected, names = {}, set()
    for artifact in spec["llama"]["assets"]:
        archive = root / "downloads" / safe_member(artifact["filename"])
        verify_file(archive, artifact)
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                relative = safe_member(member.orig_filename).as_posix()
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise GenerationError("generation_identity_mismatch")
                if member.is_dir():
                    continue
                if relative.casefold() in names:
                    raise GenerationError("generation_identity_mismatch")
                names.add(relative.casefold())
                sha = hashlib.sha256()
                with zipped.open(member) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        sha.update(block)
                expected[relative] = {"size_bytes": member.file_size, "sha256": sha.hexdigest()}
    if inventory(root / "runtime") != expected:
        raise GenerationError("generation_identity_mismatch")
    servers = [name for name in expected if Path(name).name == "llama-server.exe"]
    if len(servers) != 1:
        raise GenerationError("generation_identity_mismatch")
    licenses = {}
    for artifact in spec["licenses"]:
        path = root / "licenses" / safe_member(artifact["filename"])
        licenses[path.relative_to(root).as_posix()] = verify_file(path, artifact)
    receipt = {"schema_version": 1, "manifest_sha256": MANIFEST_SHA256,
        "model": {"path": model.relative_to(root).as_posix(), **model_digest},
        "runtime_files": expected, "server_path": "runtime/" + servers[0],
        "licenses": licenses, "quality_verified": False}
    old = root / "setup-receipt.json"
    if linked(old) or not old.is_file() or json.loads(old.read_bytes()) != receipt:
        raise GenerationError("generation_identity_mismatch")
    return receipt


class StartupMarker:
    def __init__(self, path, run_id, *, clock=time.monotonic, process=None):
        self.path, self.clock = Path(path), clock
        if (not re.fullmatch(r"[0-9a-f]{32}", run_id or "") or self.path.exists()
                or linked(self.path) or linked(self.path.parent)):
            raise ValueError("invalid_fresh_startup_marker")
        proc = process or psutil.Process()
        self.value = {"schema_version": 1, "profile": PROFILE, "run_id": run_id,
            "pid": proc.pid, "create_time": proc.create_time(), "phase": "starting",
            "started_monotonic": clock(), "ready_monotonic": None}
        self.publish("starting")

    def publish(self, phase):
        if phase not in {"starting", "ready", "failed"}:
            raise ValueError("invalid_startup_phase")
        self.value["phase"] = phase
        if phase == "ready":
            self.value["ready_monotonic"] = self.clock()
        temporary = self.path.with_name(self.path.name + ".tmp")
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(self.value, stream, separators=(",", ":"))
        os.replace(temporary, self.path)


def startup_ready(path, run_id, owned_identities, cli_started, now):
    """Outer calls after OwnedTree.sample; raise => existing exact-tree cleanup.

    Original CLI-start+120 is stricter than the later service-start marker. A
    boolean return alone is not supervision: caller MUST terminate on exception.
    """
    path = Path(path)
    if not path.exists():
        if now >= cli_started + 120:
            raise GenerationError("generation_startup_timeout")
        return False
    if linked(path) or path.stat().st_size > 4096:
        raise GenerationError("generation_startup_identity")
    data = json.loads(path.read_bytes())
    keys = {"schema_version", "profile", "run_id", "pid", "create_time", "phase", "started_monotonic", "ready_monotonic"}
    if (not isinstance(data, dict) or set(data) != keys or type(data["schema_version"]) is not int or data["schema_version"] != 1
            or data["profile"] != PROFILE or data["run_id"] != run_id
            or type(data["pid"]) is not int or type(data["create_time"]) not in (int, float)
            or not any(i[0] == data["pid"] and i[1] == data["create_time"] for i in owned_identities)
            or type(data["started_monotonic"]) not in (int, float)
            or not cli_started <= data["started_monotonic"] <= now):
        raise GenerationError("generation_startup_identity")
    if data["phase"] == "ready":
        ready = data["ready_monotonic"]
        if (type(ready) not in (int, float) or not data["started_monotonic"] <= ready <= now
                or ready >= cli_started + 120):
            raise GenerationError("generation_startup_timeout")
        return True
    if data["phase"] != "starting":
        raise GenerationError("generation_startup_failed")
    if data["ready_monotonic"] is not None:
        raise GenerationError("generation_startup_identity")
    if now >= cli_started + 120:
        raise GenerationError("generation_startup_timeout")
    return False


class ReasoningResourceGuard:
    """Reuse the fixed OwnedTree sampler; outer remains hard termination authority."""
    def __init__(self, allowed, processes, report, *, ps=psutil):
        self.ps, self.processes, self.report = ps, processes, report
        self.stop, self.error, self.thread = threading.Event(), None, None
        root = ps.Process()
        self.tree = OwnedTree(root, allowed, ps, time.monotonic)
        self.tree.capture(root)

    def sample(self):
        self.tree.sample(LIMITS["owned_rss_bytes"], LIMITS["active_available_ram_bytes"])

    def start(self):
        if self.ps.virtual_memory().available < LIMITS["start_available_ram_bytes"]:
            raise GenerationError("generation_resource_limit")
        self.sample()
        self.thread = threading.Thread(target=self.monitor, daemon=True, name="reasoning-owned-resource-guard")
        self.thread.start()
        return self

    def monitor(self):
        while not self.stop.wait(.05):
            try:
                self.sample()
            except Exception:  # noqa: BLE001 - any sampler failure is fail-closed
                self.error = GenerationError("generation_resource_limit")
                # Exact Popen handles only. Outer owns full-tree uncertain cleanup.
                for process in reversed(tuple(self.processes)):
                    try:
                        if process.poll() is None:
                            process.kill()
                    except Exception:  # noqa: BLE001 - retain resource failure; outer performs full cleanup
                        self.report["resource_guard_kill_unconfirmed"] = True
                return

    def check(self):
        if self.error is not None:
            raise self.error

    def close(self, *, timeout=1):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=max(0, timeout))
            if self.thread.is_alive():
                self.error = self.error or GenerationError("generation_resource_limit")
        self.report["reasoning_resource_guard"] = {"sampled_peak_rss": self.tree.peak,
            "sampled_minimum_host_available": self.tree.minimum_host, "samples": self.tree.samples,
            "failed": self.error is not None, "scope": "service process and owned descendants; outer also includes CLI shim"}
        self.check()
