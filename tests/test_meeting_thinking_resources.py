"""Synthetic plans/processes only; never starts a model or reads quality pools."""
import copy
import hashlib
import json
import subprocess
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from doctrail.meeting_thinking_transport import PREAMBLE, ThinkingResult
from scripts import probe_meeting_thinking_resources as probe
from scripts import serve_meeting_thinking as launcher


class Process:
    def __init__(self):
        self.stopped = False
        self.pid = 123
        self.terminated = 0
        self.killed = 0

    def poll(self):
        return 0 if self.stopped else None

    def terminate(self):
        self.terminated += 1
        self.stopped = True

    def kill(self):
        self.killed += 1
        self.stopped = True

    def wait(self, timeout):
        assert timeout <= 5
        return 0


@pytest.fixture
def fake_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    source = tmp_path / "source.py"
    source.write_bytes(b"# source\n")
    protocol = tmp_path / probe.PROTOCOL_FILE
    protocol.parent.mkdir(parents=True)
    protocol.write_bytes(b"{}")
    monkeypatch.setattr(probe, "PROTOCOL_SHA", hashlib.sha256(b"{}").hexdigest())
    monkeypatch.setattr(probe, "source_files", lambda: {"source.py", probe.PROTOCOL_FILE})
    bound = {p: probe.snapshot(p)[1] for p in probe.source_files()}
    freeze = {"candidate": probe.PROTOCOL, "bound_files": bound}
    probe.write_new("freeze.json", freeze)
    cases = [{"id": kind, "padding": 0 if kind == "normal" else 5000,
        "messages": probe.messages(kind, 0 if kind == "normal" else 5000),
        "schema": probe.NORMAL_SCHEMA if kind == "normal" else probe.STRESS_SCHEMA,
        "input_tokens": 100 if kind == "normal" else 5000,
        "prompt_sha256": hashlib.sha256((kind + PREAMBLE).encode()).hexdigest()}
        for kind in ("normal", "stress")]
    probe.write_new("plan.json", {"candidate": probe.PROTOCOL, "bound_files": bound,
        "source_freeze": {"path": "freeze.json", "sha256": probe.snapshot("freeze.json")[1]},
        "output_dir": ".local/once", "cases": cases})
    return probe.check("plan.json")


@pytest.mark.parametrize("mutation", ["source", "plan", "freeze", "protocol"])
def test_source_and_plan_drift_rejected(fake_plan, mutation):
    target = {"source": "source.py", "plan": "plan.json", "freeze": "freeze.json",
              "protocol": probe.PROTOCOL_FILE}[mutation]
    probe.path(target).write_bytes(probe.path(target).read_bytes() + b"\n")
    with pytest.raises(ValueError):
        probe.verify(fake_plan)


def test_no_existing_output_or_path_escape(fake_plan):
    with pytest.raises(ValueError):
        probe.path("../outside")
    with pytest.raises(ValueError):
        probe.path(".local", local=True)
    fake_plan["output"].mkdir(parents=True)
    with pytest.raises(ValueError, match="thinking_output_exists"):
        probe.check("plan.json")
    assert probe.check("plan.json", allow_output=True)["sha256"] == fake_plan["sha256"]


def test_uncommitted_contract_blocks_actual_run(fake_plan, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout=b""))
    with pytest.raises(ValueError, match="thinking_uncommitted_contract"):
        probe.run(fake_plan, factory=lambda **kwargs: pytest.fail("must not start"))
    assert not fake_plan["output"].exists()


def test_source_freeze_requires_transitive_helper(fake_plan):
    freeze, _ = probe.read("freeze.json")
    del freeze["bound_files"]["source.py"]
    probe.path("freeze.json").write_bytes(probe.encoded(freeze))
    with pytest.raises(ValueError, match="thinking_source_freeze_mismatch"):
        probe.bindings("freeze.json")


def test_import_closure_includes_lazy_project_imports(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    monkeypatch.setattr(probe, "ENTRY_FILES", {"scripts/start.py"})
    monkeypatch.setattr(probe, "METADATA_FILES", set())
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src/doctrail").mkdir(parents=True)
    (tmp_path / "scripts/start.py").write_text("def later():\n import doctrail.helper\n")
    (tmp_path / "src/doctrail/helper.py").write_text("from scripts.more import read\n")
    (tmp_path / "scripts/more.py").write_text("def read(): pass\n")
    assert probe.source_files() == {"scripts/start.py", "src/doctrail/helper.py", "scripts/more.py"}


def test_import_closure_resolves_relative_modules_and_package_imports(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    monkeypatch.setattr(probe, "ENTRY_FILES", {"src/sample/app.py"})
    monkeypatch.setattr(probe, "METADATA_FILES", set())
    sources = {
        "src/sample/__init__.py": "from . import package_helper\n",
        "src/sample/app.py": "from .db import connect\nfrom . import helper\nfrom .nested import work\n",
        "src/sample/db.py": "def connect(): pass\n",
        "src/sample/helper.py": "# helper\n",
        "src/sample/package_helper.py": "# package helper\n",
        "src/sample/nested/__init__.py": "# nested package\n",
        "src/sample/nested/work.py": "from .. import ancestor_helper\n",
        "src/sample/ancestor_helper.py": "# ancestor helper\n",
    }
    for name, content in sources.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    assert probe.source_files() == set(sources)


@pytest.mark.parametrize("fail", [False, True])
def test_once_only_dispatch_and_failure_preservation(fake_plan, monkeypatch, fail):
    processes = []
    @contextmanager
    def factory(**kwargs):
        kwargs["log_dir"].mkdir()
        (kwargs["log_dir"] / "native.log").write_bytes(b"")
        process, cleanup = Process(), {}
        processes.append(process)
        try:
            yield SimpleNamespace(process=process, cleanup=cleanup, url="unused", token="unused",
                                  manifest="unused")
        finally:
            if not cleanup:
                launcher.stop_owned(process, cleanup)
    @contextmanager
    def watchdog(process, metrics, seconds=90):
        metrics.update(watchdog_fired=False, watchdog_joined=True)
        yield
    @contextmanager
    def memory(process, metrics):
        metrics["memory_scope"] = "synthetic"
        yield
    class Generator:
        calls = 0
        def __init__(self, *args):
            pass
        def load(self):
            return self
        def public_metadata(self):
            return {"identity": "synthetic"}
        def close(self):
            pass
        def generate_neutral(self, messages, schema, *, stress, before_dispatch, observe):
            kind = "stress" if stress else "normal"
            before_dispatch(kind + PREAMBLE, list(range(5000 if stress else 100)), {})
            Generator.calls += 1
            observe("response", {"synthetic": True})
            if fail:
                raise ValueError("synthetic_failure")
            observe("final_token_ids", [1])
            return ThinkingResult("{}", "synthetic", 5000 if stress else 100, 928 if stress else 10,
                                  1, "length" if stress else "eos", 0.01, {})
    monkeypatch.setattr(probe, "committed", lambda _: None)
    monkeypatch.setattr(probe, "owned_watchdog", watchdog)
    monkeypatch.setattr(probe, "rss_samples", memory)
    report = probe.run(fake_plan, factory=factory, generator_factory=Generator)
    assert report["status"] == ("failed_closed" if fail else "passed_resources_only")
    assert Generator.calls == (1 if fail else 2)
    assert all(p.stopped for p in processes)
    assert report["restarts"] == (0 if fail else 1)
    assert report["calls"][0]["response"] == {"synthetic": True}
    assert json.loads((fake_plan["output"] / "report.json").read_text())["status"] == report["status"]
    with pytest.raises(FileExistsError):
        probe.run(fake_plan, factory=factory, generator_factory=Generator)


def test_effective_launcher_contract_and_owned_cleanup():
    args = launcher.command("server", "model", 8123)
    for key, value in {"--host": "127.0.0.1", "--reasoning": "on", "--ctx-size": "6144",
        "--reasoning-format": "deepseek", "--reasoning-budget": "512", "--n-gpu-layers": "24",
        "--parallel": "1", "--fit": "off", "--cache-ram": "0"}.items():
        assert args[args.index(key) + 1] == value
    assert {"--jinja", "--no-warmup", "--log-disable", "--no-context-shift"} <= set(args)
    process, metrics = Process(), {}
    launcher.stop_owned(process, metrics)
    assert process.terminated == 1 and process.killed == 0
    assert metrics["stopped"] and metrics["within_budget"]


def test_cleanup_escalates_only_owned_process():
    process = Process()
    process.terminate = lambda: None
    original_wait = process.wait
    def wait(timeout):
        if not process.stopped:
            raise subprocess.TimeoutExpired("synthetic", timeout)
        return original_wait(timeout)
    process.wait = wait
    metrics = {}
    launcher.stop_owned(process, metrics)
    assert process.killed == 1 and metrics["within_budget"]


def test_double_cleanup_preserves_first_over_budget_measurement(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(launcher.time, "monotonic", lambda: now[0])
    process, metrics = Process(), {}
    def delayed_wait(timeout):
        now[0] = 6.0
    process.wait = delayed_wait
    launcher.stop_owned(process, metrics)
    original = copy.deepcopy(metrics)
    launcher.stop_owned(process, metrics)
    assert metrics == original == {"seconds": 6.0, "stopped": True, "within_budget": False}
    assert process.terminated == 1


def test_cleanup_retry_cannot_hide_first_failure():
    process = Process()
    metrics = {"seconds": 5.0, "stopped": False, "within_budget": False}
    launcher.stop_owned(process, metrics)
    assert metrics["stopped"] is True and metrics["within_budget"] is False
    assert metrics["seconds"] >= 5


def test_launcher_rejects_manifest_before_prepare_or_process(tmp_path, monkeypatch):
    manifest = tmp_path / "wrong.json"
    manifest.write_bytes(b"{}")
    monkeypatch.setattr(launcher, "prepare", lambda *a, **k: pytest.fail("prepare forbidden"))
    with pytest.raises(ValueError, match="thinking_manifest_mismatch"), launcher.start_llama(
            log_dir=tmp_path / "logs", manifest=manifest):
        pytest.fail("not reached")


def test_replay_rejects_false_pass_and_plan_swap(fake_plan):
    probe.write_new("report.json", {"candidate": probe.PROTOCOL, "plan_sha256": fake_plan["sha256"],
                                   "status": "passed_resources_only", "calls": []})
    with pytest.raises(ValueError, match="thinking_replay_status_mismatch"):
        probe.replay("plan.json", "report.json")
    raw, _ = probe.read("report.json")
    raw["plan_sha256"] = "0" * 64
    probe.path("report.json").write_bytes(probe.encoded(raw))
    with pytest.raises(ValueError, match="thinking_report_binding"):
        probe.replay("plan.json", "report.json")


def test_stress_input_and_schema_are_closed_to_quality_payloads(fake_plan):
    raw = copy.deepcopy(fake_plan["plan"])
    raw["cases"][0]["messages"][0]["content"] = "A real question"
    probe.path("plan.json").write_bytes(probe.encoded(raw))
    with pytest.raises(ValueError, match="thinking_input_contract_mismatch"):
        probe.check("plan.json")
