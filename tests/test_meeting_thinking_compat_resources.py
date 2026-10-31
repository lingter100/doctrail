"""Compatibility contracts with synthetic tokenizer/transport, never actual models."""
import ast
import copy
import hashlib
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_thinking_transport import PREAMBLE, ThinkingResult
from scripts import probe_meeting_thinking_compat_resources as probe


class Tokenizer:
    literal_tokens = 2049
    def apply_chat_template(self, payload, **kwargs):
        assert kwargs == {"tokenize": False, "add_generation_prompt": True, "enable_thinking": True}
        return json.dumps(payload, sort_keys=True) + PREAMBLE
    def encode(self, text, *, add_special_tokens):
        assert add_special_tokens is False
        if text == probe.COMPLETE_JSON:
            return list(range(self.literal_tokens))
        return list(range(100 + text.count("bx ")))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    originals = {f"old/source-{i}.py": hashlib.sha256(b"# original\n").hexdigest() for i in range(43)}
    for name in originals:
        target = probe.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"# original\n")
    metadata = {"repo_id": "synthetic", "assets_sha256": {"tokenizer.json": "b" * 64}}
    fixtures = [(probe.ORIGINAL_FREEZE, {"bound_files": originals}, "ORIGINAL_FREEZE_SHA"),
        (probe.ORIGINAL_PLAN, {"tokenizer": metadata}, "ORIGINAL_PLAN_SHA"),
        (probe.ORIGINAL_REPORT, {"status": "failed_closed"}, "ORIGINAL_REPORT_SHA"),
        (probe.PROTOCOL_FILE, {"followup_id": probe.FOLLOWUP}, "PROTOCOL_SHA")]
    for name, content, constant in fixtures:
        probe.write_new(name, content)
        monkeypatch.setattr(probe, constant, probe.snapshot(name)[1])
    files = set(originals) | {row[0] for row in fixtures}
    monkeypatch.setattr(probe, "source_files", lambda: files)
    bound = {p: probe.snapshot(p)[1] for p in files}
    probe.write_new("freeze.json", {"followup_id": probe.FOLLOWUP, "bound_files": bound})
    monkeypatch.setattr(probe, "committed", lambda _: None)
    def register(tokenizer=None):
        return probe.register("plan.json", ".local/run", "freeze.json",
                              loader=lambda download: (tokenizer or Tokenizer(), metadata))
    return register, metadata


def test_fixed_const_literal_and_complete_json():
    assert len(probe.LITERAL.encode("ascii")) == 4095
    assert len(probe.COMPLETE_JSON.encode("ascii")) == 4109
    assert probe.LITERAL.split(" ") == ["z"] * 2048
    assert probe.STRESS_SCHEMA["properties"]["padding"] == {"const": probe.LITERAL}


def test_new_local_imports_are_all_in_declared_source_closure():
    files = probe.source_files()
    for name in probe.NEW_FILES:
        for node in ast.walk(ast.parse(probe.path(name).read_bytes())):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0
                modules = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
            elif isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            else:
                continue
            for module in modules:
                for candidate in (module.replace(".", "/") + ".py",
                                  "src/" + module.replace(".", "/") + ".py"):
                    if probe.path(candidate).is_file():
                        assert candidate in files


def test_replace_rejects_existing_temporary_file(setup):
    probe.path("report.json.tmp").write_bytes(b"sentinel")
    with pytest.raises(FileExistsError):
        probe.replace("report.json", {"synthetic": True})
    assert probe.path("report.json.tmp").read_bytes() == b"sentinel"


def test_replace_rejects_linked_temporary_path(setup, tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside.txt")
    outside.write_bytes(b"sentinel")
    try:
        probe.path("report.json.tmp").symlink_to(outside)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    with pytest.raises(ValueError, match="compat_path_invalid"):
        probe.replace("report.json", {"synthetic": True})
    assert outside.read_bytes() == b"sentinel"


def test_preparation_is_atomic_once_and_bound_to_source_and_tokenizer(setup):
    register, metadata = setup
    plan = register()
    assert plan["complete_json_retokenized_tokens"] == 2049
    assert probe.check("plan.json")["plan"]["tokenizer"] == metadata
    with pytest.raises(ValueError, match="compat_output_exists"):
        register()
    probe.path("plan.json").unlink()
    with pytest.raises(FileExistsError):
        register()


def test_short_literal_closes_preparation_without_adjustment_or_second_load(setup):
    register, _ = setup
    tokenizer = Tokenizer()
    tokenizer.literal_tokens = 928
    with pytest.raises(ValueError, match="compat_literal_too_short"):
        register(tokenizer)
    receipt, _ = probe.read("plan.preparation.json")
    assert receipt["status"] == "failed_closed" and receipt["complete_json_retokenized_tokens"] == 928
    with pytest.raises(FileExistsError):
        register()
    assert not probe.path("plan.json").exists()


def test_tokenizer_asset_identity_mismatch_closes_before_literal_measurement(setup):
    _, metadata = setup
    altered = copy.deepcopy(metadata)
    altered["assets_sha256"]["tokenizer.json"] = "c" * 64
    with pytest.raises(ValueError, match="compat_tokenizer_identity"):
        probe.register("plan.json", ".local/run", "freeze.json", loader=lambda _: (Tokenizer(), altered))
    assert probe.read("plan.preparation.json")[0]["literal_measured"] is False


def test_uncommitted_source_prevents_tokenizer_load(setup, monkeypatch):
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout=b""))
    # Restore the real function after setup's test-only replacement.
    with pytest.raises(ValueError, match="compat_uncommitted_contract"):
        committed_actual({"freeze.json"})
    def reject(_):
        raise ValueError("compat_uncommitted_contract")
    monkeypatch.setattr(probe, "committed", reject)
    with pytest.raises(ValueError, match="compat_uncommitted_contract"):
        probe.register("plan.json", ".local/run", "freeze.json", loader=lambda _: pytest.fail("load"))
    assert not probe.path("plan.preparation.json").exists()


committed_actual = probe.committed


@pytest.mark.parametrize("name", ["old/source-0.py", "freeze.json", "plan.preparation.json", "plan.json"])
def test_source_plan_and_preparation_drift(setup, name):
    setup[0]()
    prepared = probe.check("plan.json")
    probe.path(name).write_bytes(probe.path(name).read_bytes() + b"\n")
    with pytest.raises(ValueError):
        probe.verify(prepared)


def test_missing_original_dependency_rejected_before_preparation(setup):
    freeze, _ = probe.read("freeze.json")
    del freeze["bound_files"]["old/source-0.py"]
    probe.replace("freeze.json", freeze)
    with pytest.raises(ValueError, match="compat_source_freeze_mismatch"):
        setup[0]()


def clean_metrics():
    return {"process_started": True, "cleanup_attempted": True, "stopped": True,
        "within_budget": True, "seconds": 0.01, "cleanup_errors": 0,
        "drain": {"emitted_bytes": 0, "eof": True, "read_errors": 0, "join_errors": 0,
                  "started": True, "joined": True, "chunk_bytes": 8192, "raw_content_retained": False}}


@pytest.mark.parametrize("mutation", [{"eof": False}, {"read_errors": 1}, {"join_errors": 1},
    {"emitted_bytes": 1}, {"emitted_bytes": None}, {"started": False}])
def test_zero_file_output_cannot_replace_drain_success(mutation):
    metrics = clean_metrics()
    metrics["drain"].update(mutation)
    assert not probe.drain_pass(metrics)


@pytest.mark.parametrize("fault", [None, "timeout", "drift", "startup", "diagnostic"])
def test_run_once_failure_and_startup_telemetry(setup, monkeypatch, fault):
    setup[0]()
    prepared = probe.check("plan.json")
    generations, launches = [], []
    @contextmanager
    def factory(*, telemetry, **kwargs):
        launches.append(telemetry)
        if fault == "startup":
            telemetry.update(clean_metrics())
            telemetry["drain"]["emitted_bytes"] = 37
            raise RuntimeError("synthetic startup diagnostic")
        yield SimpleNamespace(process=object(), url="none", token="none", manifest="none",
            cleanup=telemetry, drain=SimpleNamespace(emitted_bytes=0, read_errors=0))
    def cleanup(process, drain, metrics):
        metrics.update(clean_metrics())
        if fault == "diagnostic":
            metrics["drain"]["emitted_bytes"] = 9
    @contextmanager
    def watchdog(process, metrics, seconds=90):
        metrics.update(watchdog_fired=False, watchdog_joined=True)
        yield
    @contextmanager
    def memory(*args):
        yield
    class Generator:
        def __init__(self, *args):
            pass
        def load(self):
            pass
        def public_metadata(self):
            return {"generation_protocol": probe.PROTOCOL}
        def close(self):
            pass
        def generate_neutral(self, payload, schema, *, stress, before_dispatch, observe):
            rendered = Tokenizer().apply_chat_template(payload, tokenize=False,
                add_generation_prompt=True, enable_thinking=True)
            tokens = Tokenizer().encode(rendered, add_special_tokens=False)
            if fault == "drift":
                probe.path("old/source-0.py").write_bytes(b"changed")
            before_dispatch(rendered, tokens, {})
            generations.append(stress)
            if fault == "timeout":
                raise GenerationError("generation_deadline_exceeded")
            observe("response", {"synthetic": True})
            return ThinkingResult("{}", "synthetic", len(tokens), 928 if stress else 10, 1,
                                  "length" if stress else "eos", 0.01, {})
    monkeypatch.setattr(probe, "cleanup_owned", cleanup)
    monkeypatch.setattr(probe, "owned_watchdog", watchdog)
    monkeypatch.setattr(probe, "rss_samples", memory)
    report = probe.run(prepared, factory=factory, generator_factory=Generator)
    assert report["status"] == ("passed_resources_only" if fault is None else "failed_closed")
    assert len(generations) == (0 if fault in {"startup", "drift"} else 1 if fault == "timeout" else 2)
    assert report["restarts"] == (1 if fault is None else 0)
    if fault == "startup":
        assert report["cleanup"][0]["drain"]["emitted_bytes"] == 37
    assert len(launches) == (2 if fault is None else 1)
    with pytest.raises((ValueError, FileExistsError)):
        probe.run(prepared, factory=factory, generator_factory=Generator)


def test_replay_preserves_failure_and_rejects_false_pass(setup):
    setup[0]()
    prepared = probe.check("plan.json")
    report = {"followup_id": probe.FOLLOWUP, "generation_protocol": probe.PROTOCOL,
        "plan_sha256": prepared["sha256"], "original_failure_sha256": probe.ORIGINAL_REPORT_SHA,
        "calls": [], "status": "failed_closed", "error": "synthetic_failure"}
    probe.write_new("report.json", report)
    assert probe.replay("plan.json", "report.json")["status"] == "failed_closed"
    report["status"] = "passed_resources_only"
    probe.replace("report.json", report)
    with pytest.raises(ValueError, match="compat_replay_status_mismatch"):
        probe.replay("plan.json", "report.json")
