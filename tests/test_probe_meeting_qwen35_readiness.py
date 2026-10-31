"""Mocked readiness orchestration/resources; no native, GPU or document calls."""
import hashlib
import json
import subprocess
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_qwen35 import PREAMBLE_SHA256
from scripts import probe_meeting_qwen35_readiness as probe


@pytest.fixture
def harness(tmp_path, monkeypatch):
    source = tmp_path / "bound.py"
    source.write_text("synthetic bound source", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"kind": "synthetic", "bound_files": {"bound.py": digest},
                                    "inputs": "DO_NOT_QUERY_KNOWN_QUESTIONS"}), encoding="utf-8")
    state = SimpleNamespace(events=[], generated=[], fail_load=False, failure=None,
                            fail_verify=False, mutate=False, mutate_plan=False, finish="eos",
                            text='{"status":"abstained","claims":[]}')
    monkeypatch.setattr(probe, "ROOT", tmp_path)

    def verify(plan):
        state.events.append("verify")
        if state.fail_verify or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError("candidate_source_binding_mismatch")
        return {"cases": [{"query": "KNOWN QUESTION MUST NOT BE CALLED"}]}

    @contextmanager
    def native(**kwargs):
        assert state.events == ["verify"]
        state.events.append("native_start")
        try:
            yield SimpleNamespace(url="http://127.0.0.1:19003", token="PRIVATE-token",
                                  manifest=tmp_path / "manifest.json", process=SimpleNamespace(pid=123))
        finally:
            state.events.append("native_stop")
            if state.mutate:
                source.write_text("changed", encoding="utf-8")
            if state.mutate_plan:
                plan_path.write_bytes(plan_path.read_bytes() + b"\n")

    class Generator:
        def __init__(self, *args):
            self.last_effective_config = None
        def load(self):
            state.events.append("load")
            if state.fail_load:
                raise RuntimeError("PRIVATE-token C:/private/file")
            return self
        def public_metadata(self):
            return {"repo_id": "synthetic/model", "revision": "synthetic-revision",
                    "nonthinking": {"last_template_verified": True}}
        def begin_request(self, deadline):
            state.events.append("begin")
        def end_request(self):
            state.events.append("end")
        def _request(self, method, path, payload=None, deadline=None):
            return {"content": state.text, "model": "a" * 64, "stop_type": "eos",
                    "generation_settings": {"temperature": 0, "grammar": "synthetic"},
                    "prompt": "PRIVATE prompt excluded", "model_path": "C:/private/model"}
        def generate_bounded(self, messages, deadline):
            state.generated.append(messages)
            self._request("POST", "/completion", {}, deadline)
            if state.failure:
                raise GenerationError(state.failure)
            self.last_effective_config = {"observed_nonthinking_preamble_sha256": PREAMBLE_SHA256,
                                          "temperature": 0}
            return SimpleNamespace(text=state.text, finish_reason=state.finish, input_tokens=20,
                                   output_tokens=10, elapsed_seconds=0.1)
        def close(self):
            state.events.append("close")

    class Sampler:
        def __init__(self, pid):
            assert pid == 123
        def start(self):
            state.events.append("sample_start")
        def stop(self):
            state.events.append("sample_stop")
        def summary(self):
            return {"sample_count": 1, "startup_measured": False, "exact_peak_measured": False}

    monkeypatch.setattr(probe, "verify_plan", verify)
    monkeypatch.setattr(probe, "start_llama", native)
    monkeypatch.setattr(probe, "Qwen35Generator", Generator)
    monkeypatch.setattr(probe, "ResourceSampler", Sampler)
    state.plan, state.output = plan_path, tmp_path / "output"
    return state


def test_exact_two_neutral_inputs_and_before_after_binding(harness):
    report = probe.run(harness.plan, harness.output)
    assert report["status"] == "passed_neutral_readiness_only"
    assert report["attempt_count"] == 2 and report["quality_cases_queried"] == 0
    assert harness.generated == [[{"role": "system", "content": probe.SYSTEM},
                                  {"role": "user", "content": text}] for text in probe.NEUTRAL_INPUTS]
    assert len(probe.NEUTRAL_INPUTS[1].splitlines()) == 300
    assert report["bound_files_after"] == report["bound_files"]
    assert report["plan_sha256_after"] == report["plan_sha256"]
    assert harness.events == ["verify", "native_start", "load", "sample_start", "begin", "end",
                              "begin", "end", "sample_stop", "close", "native_stop", "verify"]
    assert report["worker_http_measured"] is False and report["java_service_measured"] is False
    serialized = (harness.output / "report.json").read_text(encoding="utf-8")
    assert "PRIVATE" not in serialized and "C:/private" not in serialized
    assert "native_response" in report["attempts"][0]
    assert report["attempts"][0]["effective_config"]["temperature"] == 0


def test_existing_output_is_not_overwritten_or_loaded(harness):
    harness.output.mkdir()
    marker = harness.output / "previous.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="candidate_output_exists"):
        probe.run(harness.plan, harness.output)
    assert marker.read_text(encoding="utf-8") == "keep" and not harness.events


def test_preflight_binding_failure_prevents_any_native_load(harness):
    harness.fail_verify = True
    with pytest.raises(ValueError, match="binding_mismatch"):
        probe.run(harness.plan, harness.output)
    assert harness.events == ["verify"] and not harness.output.exists()


@pytest.mark.parametrize("failure", ["generation_deadline_exceeded", "generation_input_limit",
                                     "generation_nonthinking_template_mismatch"])
def test_first_failed_attempt_stops_without_retry(harness, failure):
    harness.failure = failure
    report = probe.run(harness.plan, harness.output)
    assert report["status"] == "failed" and report["attempt_count"] == 1
    assert report["attempts"][0]["error"] == failure
    assert report["attempts"][0]["native_response"]["content"] == harness.text
    assert harness.events[-4:] == ["sample_stop", "close", "native_stop", "verify"]


@pytest.mark.parametrize("text", ['{"status":"answered","claims":[]}',
    '{"status":"abstained","claims":[],"other":true}',
    '{"status":"abstained","status":"abstained","claims":[]}'])
def test_unexpected_json_fails_after_one_call(harness, text):
    harness.text = text
    report = probe.run(harness.plan, harness.output)
    assert report["status"] == "failed" and report["attempt_count"] == 1
    assert report["attempts"][0]["output"]["text"] == text


def test_load_failure_records_safe_error_and_closes_without_sampling(harness):
    harness.fail_load = True
    report = probe.run(harness.plan, harness.output)
    assert report["attempt_count"] == 0 and report["status"] == "failed"
    assert report["error"] == "RuntimeError"
    assert "sample_start" not in harness.events
    assert harness.events[-3:] == ["close", "native_stop", "verify"]


def test_changed_bound_source_marks_completed_calls_failed(harness):
    harness.mutate = True
    report = probe.run(harness.plan, harness.output)
    assert report["attempt_count"] == 2 and report["status"] == "failed"
    assert report["sources_unchanged"] is False
    assert report["bound_files_after"] != report["bound_files"]


def test_changed_plan_bytes_fail_even_when_bound_files_match(harness):
    harness.mutate_plan = True
    report = probe.run(harness.plan, harness.output)
    assert report["status"] == "failed" and report["sources_unchanged"] is False
    assert report["source_check_error"] == "readiness_plan_changed"


def test_length_stop_never_counts_as_readiness_pass(harness):
    harness.finish = "length"
    report = probe.run(harness.plan, harness.output)
    assert report["status"] == "failed" and report["attempt_count"] == 1
    assert report["attempts"][0]["error"] == "readiness_output_truncated"


def test_sampler_joins_owned_thread_and_labels_sampled_max(monkeypatch):
    ready = threading.Event()
    def sample(pid):
        assert pid == 123
        ready.set()
        return {"native_rss_mib": 42.0, "device_memory_mib": {"0": 100}, "errors": []}
    monkeypatch.setattr(probe, "sample_resources", sample)
    sampler = probe.ResourceSampler(123)
    sampler.start()
    assert ready.wait(1)
    sampler.stop()
    assert not sampler._thread.is_alive()
    summary = sampler.summary()
    assert summary["sample_count"] >= 1
    assert summary["native_rss_sampled_max_mib"] == 42.0
    assert summary["whole_device_memory_sampled_max_mib"] == {"0": 100}
    assert not summary["startup_measured"] and not summary["exact_peak_measured"]
    assert not summary["device_memory_is_model_specific"]


def test_resource_command_is_bounded_hidden_and_parsed_without_real_sampling(monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(
        memory_info=lambda: SimpleNamespace(rss=12 * 1024 * 1024)))
    calls = []
    def command(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="0, 321\n1, 654\n")
    monkeypatch.setattr(probe.subprocess, "run", command)
    sample = probe.sample_resources(123)
    assert sample["native_rss_mib"] == 12 and sample["device_memory_mib"] == {"0": 321, "1": 654}
    assert calls[0][1]["timeout"] == 2
    assert calls[0][1]["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_resource_failure_is_missing_data_not_zero_or_raw_error(monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(
        memory_info=lambda: SimpleNamespace(rss=12 * 1024 * 1024)))
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("PRIVATE native command", 2)
    monkeypatch.setattr(probe.subprocess, "run", fail)
    sample = probe.sample_resources(123)
    assert sample["device_memory_mib"] == {} and sample["errors"] == ["device_memory_unavailable"]
    assert "PRIVATE" not in json.dumps(sample)
