"""Fresh synthetic transport/resource tests. No datasets, GPU, network or tokenizer."""
import copy
import hashlib
import json
import subprocess
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from doctrail.meeting_gguf import GREEDY, GGUFResult
from doctrail.meeting_input_budget import PROTOCOL
from doctrail.meeting_qwen35 import GGUF_SHA256, MODEL_ID, MODEL_REVISION, PREAMBLE_SHA256
from scripts import probe_meeting_budget_resources as probe


def metadata():
    return {"repo_id": MODEL_ID, "revision": "gguf-sha256:" + GGUF_SHA256,
        "original_revision": MODEL_REVISION, "artifact": {"sha256": GGUF_SHA256},
        "generation_protocol": PROTOCOL, "runtime": {"backend": "llama.cpp",
            "context_tokens": 6144, "max_input_tokens": 5120, "max_new_tokens": 384,
            "deadline_seconds": 90}, "nonthinking": {"enable_thinking_requested": False,
            "assistant_preamble_sha256": PREAMBLE_SHA256,
            "policy": "qwen35-terminal-assistant-preamble-v1", "last_template_verified": False,
            "verification_scope": "terminal_assistant_preamble_per_prompt"}}


def tokenizer_metadata():
    return {"repo_id": MODEL_ID, "revision": MODEL_REVISION,
        "trust_remote_code": False, "download_authorized": False,
        "transformers_version": "synthetic-test", "assets_sha256": {
            "tokenizer.json": "a" * 64, "tokenizer_config.json": "b" * 64,
            "chat_template.jinja": "c" * 64}}


class Process:
    def __init__(self):
        self.stopped = False

    def poll(self):
        return 0 if self.stopped else None

    def terminate(self):
        self.stopped = True

    def kill(self):
        self.stopped = True

    def wait(self, timeout):
        assert timeout <= 5
        return 0


class Base:
    def __init__(self, observer, fail=False, count_delta=0):
        self.observer, self.fail, self.count_delta = observer, fail, count_delta
        self.closed, self.last_effective_config = False, None

    def public_metadata(self):
        return metadata()

    def begin_request(self, deadline):
        self.last_effective_config = None

    def end_request(self):
        pass

    def count_tokens(self, prompt):
        return (5000 if "resource test" in prompt[-1]["content"] else 500) + self.count_delta

    def _complete(self, prompt, deadline, limit, grammar):
        count = self.count_tokens(prompt)
        stress = grammar == probe.STRESS_GRAMMAR
        output_tokens = 384 if stress else 18
        text = "z " * 384 if stress else json.dumps({"status": "answered", "claims": [{
            "text": "The synthetic badge is copper.", "evidence_ids": [0]}]})
        config = {**GREEDY, "n_predict": limit, "grammar": grammar}
        payload = {**config, "prompt": [17] * count, "cache_prompt": False, "return_tokens": True}
        raw = {"content": text, "model": GGUF_SHA256, "generation_settings": config,
            "stop": True, "truncated": False, "stop_type": "limit" if stress else "eos",
            "tokens_evaluated": count, "tokens_predicted": output_tokens,
            "timings": {"cache_n": 0, "prompt_n": count, "prompt_ms": 0.,
                        "predicted_n": output_tokens, "predicted_ms": 0.}}

        def dispatch():
            if self.fail:
                raise ValueError("synthetic_native_failure")
            return raw
        self.observer("POST", "/completion", payload, deadline, dispatch)
        self.last_effective_config = {"backend": "llama.cpp", **config,
            "cache_prompt_requested": False, "observed_cache_tokens": 0,
            "observed_nonthinking_preamble_sha256": PREAMBLE_SHA256,
            "enable_thinking_requested": False}
        return GGUFResult(text, "length" if stress else "eos", count, output_tokens, 0.,
                          {"native_timings": raw["timings"]})

    def close(self):
        self.closed = True


@contextmanager
def fake_memory(process, row):
    yield
    row["memory"] = {"sample_count": 1, "sampler_joined": True,
                     "scope": "synthetic_test_not_hardware"}


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    monkeypatch.setattr(probe, "memory_samples", fake_memory)
    (tmp_path / "synthetic.py").write_text("# only a synthetic source\n")
    bindings = {"synthetic.py": probe.snapshot("synthetic.py")[1]}
    freeze = tmp_path / "source.json"
    probe.write_new(freeze, {"bound_files": bindings})
    monkeypatch.setattr(probe, "source_bindings", lambda _: {
        "synthetic.py": probe.snapshot("synthetic.py")[1]})
    monkeypatch.setattr(probe, "survey_reference", lambda value, phase, freeze_path: {
        "file": probe.name(value), "sha256": probe.snapshot(value)[1]})
    refs = {}
    for phase in ("calibration", "validation"):
        p = tmp_path / f"{phase}.json"
        probe.write_new(p, {"synthetic": True, "tokenizer": tokenizer_metadata()})
        refs[phase] = {"file": probe.name(p), "sha256": probe.snapshot(p)[1]}
    requests = [probe.dto(["The synthetic badge is copper."], "What color is the synthetic badge?"),
                probe.dto(["Synthetic capacity marker."], "Repeat z for this resource test.")]
    cases = []
    for kind, request in zip(("normal", "stress"), requests, strict=True):
        meta = probe.describe(request, None, lambda _, prompt, kind=kind: 5000 if kind == "stress" else 500)
        cases.append({"id": kind, "payload": request.model_dump(),
            "official_input_tokens": {a: m["input_tokens"] for a, m in meta.items()},
            "prompt_sha256": {a: m["prompt_sha256"] for a, m in meta.items()},
            "grammar_sha256": {a: m["grammar_sha256"] for a, m in meta.items()}})
    plan = {"schema_version": 1, "candidate": probe.CANDIDATE,
        "protocol_sha256": probe.PROTOCOL_SHA256, "limits": probe.LIMITS,
        "bound_files": bindings, "source_freeze": {"file": "source.json",
            "sha256": probe.snapshot(freeze)[1]}, "survey_receipts": refs,
        "runtime_receipt_sha256": probe.fingerprint({"synthetic_runtime": True}),
        "tokenizer": tokenizer_metadata(),
        "output_dir": ".local/neutral-new", "stress_grammar": probe.STRESS_GRAMMAR,
        "normal_expected_terms": ["copper"], "cases": cases,
        "fixture_sha256": probe.fingerprint(cases)}
    target = tmp_path / "plan.json"
    probe.write_new(target, plan)
    processes, bases = [], []

    @contextmanager
    def factory(*args):
        process = Process()
        processes.append(process)
        try:
            yield SimpleNamespace(process=process, receipt={"synthetic_runtime": True})
        finally:
            process.kill()

    def base_factory(service, observer):
        base = Base(observer)
        bases.append(base)
        return base
    return SimpleNamespace(root=tmp_path, path=target, plan=plan, processes=processes,
                           bases=bases, factory=factory, base_factory=base_factory)


def test_four_dispatches_mapper_replay_owned_cleanup_and_no_generation_restart(source):
    report = probe.run(probe.prepare(source.path), source.factory, source.base_factory)
    assert report["readiness_passed"], report
    assert report["status"] == "completed_resource_only"
    assert [c["id"] for c in report["calls"]] == ["normal-L0", "normal-C2", "stress-C2", "stress-L0"]
    assert len(source.processes) == len(source.bases) == 2
    assert all(p.poll() == 0 for p in source.processes) and all(b.closed for b in source.bases)
    assert report["recovery_generation_calls"] == 0 and report["model_quality_evaluated"] is False
    assert report["unexecuted"] == []
    assert json.loads((source.root / ".local/neutral-new/report.json").read_bytes()) == report
    with pytest.raises(ValueError, match="output_exists"):
        probe.prepare(source.path)


@pytest.mark.parametrize("mode", ["failure", "count", "source", "startup"])
def test_failure_preserves_partial_evidence_and_stops_remaining_calls(source, mode):
    def base_factory(service, observer):
        if mode == "startup":
            raise ValueError("synthetic_startup_failure")
        base = Base(observer, fail=mode == "failure", count_delta=1 if mode == "count" else 0)
        if mode == "source":
            (source.root / "synthetic.py").write_text("# changed synthetic source\n")
        return base
    report = probe.run(probe.prepare(source.path), source.factory, base_factory)
    assert report["status"] == "failed" and not report["readiness_passed"]
    assert len(report["calls"]) == (1 if mode == "failure" else 0)
    assert len(source.processes) == 1 and source.processes[0].poll() == 0
    assert not report["metadata_recovery"]
    assert len(report["unexecuted"]) == 4 - len(report["calls"])


@pytest.mark.parametrize("field,value", [
    ("candidate", "old"), ("limits", {"input_tokens": 4096}),
    ("fixture_sha256", "0" * 64), ("stress_grammar", 'root ::= "wrong"\n'),
    ("output_dir", "../escape"), ("schema_version", True),
])
def test_plan_tampering_fails_before_service(source, field, value):
    plan = copy.deepcopy(source.plan)
    plan[field] = value
    source.path.write_bytes(probe.encoded(plan))
    with pytest.raises(ValueError):
        probe.prepare(source.path)
    assert not source.processes


@pytest.mark.parametrize("counts", [{"L0": 4096, "C2": 5000}, {"L0": 4900, "C2": 4991},
                                   {"L0": 5121, "C2": 5000}, {"L0": True, "C2": 5000}])
def test_both_arm_stress_targets_are_required(source, counts):
    plan = copy.deepcopy(source.plan)
    plan["cases"][1]["official_input_tokens"] = counts
    plan["fixture_sha256"] = probe.fingerprint(plan["cases"])
    source.path.write_bytes(probe.encoded(plan))
    with pytest.raises(ValueError, match="token_target"):
        probe.prepare(source.path)


def test_fixture_builder_is_deterministic_and_limits_whole_units(monkeypatch):
    calls = []

    def counter(_, prompt):
        calls.append(prompt)
        if "badge" in prompt[-1]["content"]:
            return 500
        # Both arms share the exact neutral strings, producing reproducible
        # simulated counts. Real official counts are intentionally not guessed.
        return 5000
    a = probe.synthetic_cases(None, counter)
    b = probe.synthetic_cases(None, counter)
    assert a == b and len(calls) == 8
    assert a[0]["payload"]["contexts"][0]["text"] == "The synthetic badge is copper."
    assert len(a[1]["payload"]["contexts"]) == 10
    assert all(len(c["text"]) <= 1024 for c in a[1]["payload"]["contexts"])
    with pytest.raises(ValueError, match="unreachable"):
        probe.synthetic_cases(None, lambda _, prompt: 500 if "badge" in prompt[-1]["content"] else 6000)


def code_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    monkeypatch.setattr(probe, "NEW_FILES", {"new.py"})
    monkeypatch.setattr(probe, "PREPARATION_FILES", {"new.py"})
    monkeypatch.setattr(probe, "LEGACY_FREEZES", ("legacy.json",))
    monkeypatch.setattr(probe, "PROTOCOL_FILE", "protocol.json")
    (tmp_path / "new.py").write_bytes(b"new synthetic source")
    (tmp_path / "old.py").write_bytes(b"old synthetic source")
    probe.write_new("legacy.json", {"bound_files": {"old.py": probe.snapshot("old.py")[1]}})
    probe.write_new("protocol.json", {"bound_files": {"legacy.json": probe.snapshot("legacy.json")[1],
        **{p: "d" * 64 for paths in probe.PHASE_PATHS.values() for p in paths},
        "never-read-oracle.json": "f" * 64}})
    monkeypatch.setattr(probe, "PROTOCOL_SHA256", probe.snapshot("protocol.json")[1])
    files = {p: probe.snapshot(p)[1] for p in ("new.py", "old.py", "legacy.json", "protocol.json")}
    probe.write_new("freeze.json", {"bound_files": files})
    return files


def test_source_binding_checks_old_files_without_reading_oracles(tmp_path, monkeypatch):
    files = code_tree(tmp_path, monkeypatch)
    result = probe.source_bindings("freeze.json")
    assert set(result) == set(files) | {"old.py"}
    (tmp_path / "old.py").write_bytes(b"changed")
    with pytest.raises(ValueError, match="source_changed"):
        probe.source_bindings("freeze.json")


def test_survey_requires_both_successful_counts_and_same_source_freeze(tmp_path, monkeypatch):
    files = code_tree(tmp_path, monkeypatch)
    receipt = {"candidate": PROTOCOL, "phase": "validation", "status": "passed", "payloads_preserved": True,
        "model_calls": 0, "native_calls": 0, "downloads": 0, "errors": [],
        "protocol_deviation": "equal_input_cap_4096_to_5120_after_length_metadata",
        "bound_files": {k: files[k] for k in ("new.py", "old.py")},
        "tokenizer": tokenizer_metadata(),
        "snapshots": {"freeze.json": {"sha256": probe.snapshot("freeze.json")[1]},
                      "protocol.json": {"sha256": probe.PROTOCOL_SHA256},
                      **{p: {"sha256": "d" * 64} for p in probe.PHASE_PATHS["validation"]}},
        "cases": [{"id": f"synthetic-{i}", "payload_preserved": True,
            "arms": {a: {"official_input_tokens": 5000, "error_code": None,
                         "old_4096_pass": False, "new_5120_pass": True} for a in ("L0", "C2")}}
            for i in range(12)],
        "summary": {"total_arms": 24, "measured_arms": 24, "unknown_arms": 0,
                    "failed_arms": 0, "new_5120_pass": 24, "new_5120_fail": 0,
                    "old_4096_pass": 0, "old_4096_fail": 24}}
    probe.write_new("receipt.json", receipt)
    assert probe.survey_reference("receipt.json", "validation", "freeze.json")["file"] == "receipt.json"
    for field, value in [("status", "failed"), ("payloads_preserved", False), ("native_calls", 1)]:
        changed = {**receipt, field: value}
        (tmp_path / "receipt.json").write_bytes(probe.encoded(changed))
        with pytest.raises(ValueError, match="survey_not_passed"):
            probe.survey_reference("receipt.json", "validation", "freeze.json")
    for field, value in [("official_input_tokens", 5121), ("official_input_tokens", None),
                         ("old_4096_pass", True), ("error_code", "synthetic_failure")]:
        changed = copy.deepcopy(receipt)
        changed["cases"][0]["arms"]["C2"][field] = value
        (tmp_path / "receipt.json").write_bytes(probe.encoded(changed))
        with pytest.raises(ValueError, match="survey_rows"):
            probe.survey_reference("receipt.json", "validation", "freeze.json")
    changed = copy.deepcopy(receipt)
    changed["snapshots"][probe.PHASE_PATHS["validation"][0]]["sha256"] = "e" * 64
    (tmp_path / "receipt.json").write_bytes(probe.encoded(changed))
    with pytest.raises(ValueError, match="survey_not_passed"):
        probe.survey_reference("receipt.json", "validation", "freeze.json")


def test_source_freeze_extra_or_changed_binding_fails_before_resource(tmp_path, monkeypatch):
    files = code_tree(tmp_path, monkeypatch)
    for changed in ({**files, "extra.txt": "a" * 64}, {**files, "old.py": "b" * 64}):
        (tmp_path / "freeze.json").write_bytes(probe.encoded({"bound_files": changed}))
        with pytest.raises(ValueError, match="source_freeze_mismatch"):
            probe.source_bindings("freeze.json")


def test_paths_bytes_and_exclusive_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    for value in ("../outside", "file:stream", "source/../../outside"):
        with pytest.raises(ValueError, match="path_invalid"):
            probe.path(value)
    with pytest.raises(ValueError, match="output_invalid"):
        probe.path("data", local=True)
    probe.write_new("a.json", {"new": True})
    with pytest.raises(FileExistsError):
        probe.write_new("a.json", {"new": False})
    monkeypatch.setattr(probe, "BYTE_LIMIT", 2)
    with pytest.raises(ValueError, match="snapshot_limit"):
        probe.snapshot("a.json")
    with pytest.raises(ValueError, match="snapshot_limit"):
        probe.write_new("b.json", {"long": True})


def test_cleanup_escalates_only_owned_process():
    class Slow(Process):
        def __init__(self):
            super().__init__()
            self.waits = []

        def terminate(self):
            pass

        def wait(self, timeout):
            self.waits.append(timeout)
            if not self.stopped:
                raise subprocess.TimeoutExpired("synthetic owned child", timeout)
    owned, unrelated = Slow(), Process()
    report = {}
    probe.stop_owned(owned, report)
    assert owned.stopped and not unrelated.stopped and owned.waits == [3, 2]
    assert report["owned_cleanup_ms"] <= 5000


def test_nvidia_optional_measurement_is_sanitized(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", lambda _: None)
    assert probe.nvidia_sample() is None
    monkeypatch.setattr(probe.shutil, "which", lambda _: "synthetic-nvidia")
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="0, 123, 6141\n"))
    assert probe.nvidia_sample() == [{"index": 0, "used_mib": 123, "total_mib": 6141}]
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="PRIVATE malformed"))
    assert probe.nvidia_sample() is None


def test_receipt_is_persisted_before_dispatch(source):
    def base_factory(service, observer):
        def observed(method, route, payload, deadline, dispatch):
            def inspect():
                report = json.loads((source.root / ".local/neutral-new/report.json").read_bytes())
                assert report["calls"][-1]["dispatch_attempted"] is True
                assert "raw_response" not in report["calls"][-1]
                return dispatch()
            return observer(method, route, payload, deadline, inspect)
        return Base(observed)
    result = probe.run(probe.prepare(source.path), source.factory, base_factory)
    assert result["readiness_passed"], result


def test_resource_grammar_is_sealed_and_distinct_from_answer_grammar():
    from doctrail.meeting_answer_spans import build_span_catalog, span_answer_grammar
    request = probe.dto(["Neutral sample"], "Which sample?")
    grammar = span_answer_grammar(build_span_catalog(request.contexts))
    assert probe.STRESS_GRAMMAR != grammar
    assert hashlib.sha256(grammar.encode()).hexdigest() != hashlib.sha256(probe.STRESS_GRAMMAR.encode()).hexdigest()


def test_registration_is_tokenizer_only_and_consumes_no_existing_plan(source, monkeypatch):
    receipt = source.root / "runtime.json"
    probe.write_new(receipt, {"synthetic_runtime": True})
    loads = []

    def loader(download):
        loads.append(download)
        return None, tokenizer_metadata()
    monkeypatch.setattr(probe, "synthetic_cases", lambda *args: copy.deepcopy(source.plan["cases"]))
    kwargs = {"source_freeze": source.root / "source.json",
        "calibration_receipt": source.root / "calibration.json",
        "validation_receipt": source.root / "validation.json", "runtime_receipt": receipt,
        "loader": loader}
    target = source.root / "new-plan.json"
    result = probe.register(target, source.root / ".local/new-output", **kwargs)
    assert loads == [False] and not source.processes
    assert result["native_calls"] == result["model_calls"] == 0
    assert result["fixture_sha256"] == probe.fingerprint(result["cases"])
    assert probe.prepare(target)["plan"] == result
    original = target.read_bytes()
    with pytest.raises(ValueError, match="output_exists"):
        probe.register(target, source.root / ".local/new-output", **kwargs)
    assert target.read_bytes() == original and loads == [False]


def test_failed_survey_prevents_even_offline_tokenizer_load(source, monkeypatch):
    def rejected(*args):
        raise ValueError("resource_survey_not_passed")
    monkeypatch.setattr(probe, "survey_reference", rejected)
    loaded = []
    with pytest.raises(ValueError, match="survey_not_passed"):
        probe.register(source.root / "later-plan.json", source.root / ".local/later",
            source_freeze=source.root / "source.json", calibration_receipt="calibration.json",
            validation_receipt="validation.json", runtime_receipt="never-open.json",
            loader=lambda *args: loaded.append(args))
    assert not loaded and not (source.root / "later-plan.json").exists()


def test_validation_survey_cannot_be_omitted(source):
    plan = copy.deepcopy(source.plan)
    del plan["survey_receipts"]["validation"]
    source.path.write_bytes(probe.encoded(plan))
    with pytest.raises(ValueError, match="plan_mismatch"):
        probe.prepare(source.path)


def test_source_drift_after_registration_is_rejected_before_native(source):
    prepared = probe.prepare(source.path)
    (source.root / "synthetic.py").write_bytes(b"changed after preparation")
    with pytest.raises(ValueError, match="source_changed"):
        probe.run(prepared, source.factory, source.base_factory)
    assert not source.processes and not prepared["output"].exists()
