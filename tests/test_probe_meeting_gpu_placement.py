"""Only synthetic tokenizer/HTTP/process evidence; official paths never reserved."""
import copy
import dataclasses
import json
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_thinking_transport import GGUF_SHA256, SETTINGS, ThinkingResult
from scripts import probe_meeting_gpu_placement as probe

PROMPT = "new synthetic input\n" + probe.PREAMBLE
TOKENS = list(range(5000))


def response():
    content, reasoning, n, output = '{"marker":"teal"}', "A new neutral check.", 5000, 20
    return {"object": "chat.completion", "model": GGUF_SHA256, "system_fingerprint": "b11429-d81235049",
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content,
            "reasoning_content": reasoning}}], "usage": {"prompt_tokens": n, "completion_tokens": output,
            "total_tokens": n + output, "prompt_tokens_details": {"cached_tokens": 0}},
        "__verbose": {"model": GGUF_SHA256, "prompt": PROMPT,
            "content": reasoning + "\n</think>\n" + content, "tokens": list(range(output)),
            "tokens_predicted": output, "tokens_evaluated": n, "stop": True, "truncated": False,
            "stop_type": "eos", "generation_settings": {**copy.deepcopy(SETTINGS), "stop": [], "grammar": "root"},
            "timings": {"prompt_n": n, "predicted_n": output, "cache_n": 0}}}


def transport_generator(handler):
    generator = probe.PlacementGenerator("http://127.0.0.1:8123", "x" * 40, "unused",
                                         transport=httpx.MockTransport(handler))
    generator._alias = GGUF_SHA256
    generator.outer_deadline = time.monotonic() + 90
    return generator


def test_fresh_fixed_fixture_same_payload_for_both_arms():
    assert probe.messages()[1]["content"].count("u ") == 5000
    assert probe.fixture_spec()["padding_repetitions"] == 5000
    assert probe.SCHEMA["properties"]["marker"] == {"type": "string", "const": "teal"}
    assert [r["gpu_layers_requested"] for r in probe.fixture_spec()["arms"]] == [24, 28]


@pytest.mark.parametrize("fault", [None, "eos", "final_length", "late_send", "late_observer"])
def test_frozen_normal_contract_and_outer_deadline_send_hook(monkeypatch, fault):
    now, sends, observations = [10.0], [], []
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    def handler(request):
        payload = json.loads(request.content)
        if request.url.path == "/apply-template":
            return httpx.Response(200, json={"prompt": PROMPT})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"tokens": TOKENS if payload["parse_special"] else list(range(385 if fault == "final_length" else 8))})
        sends.append(request)
        raw = response()
        if fault == "eos":
            raw["__verbose"]["stop_type"] = "limit"
        return httpx.Response(200, json=raw)
    gen = transport_generator(handler)
    gen.outer_deadline = 20
    def observer(kind, value):
        observations.append(kind)
        if fault == "late_observer" and kind == "http_send_attempt":
            now[0] = 21
    gen.observer = observer
    def before(*args):
        if fault == "late_send":
            now[0] = 21
    try:
        if fault:
            with pytest.raises(GenerationError):
                gen.generate_neutral(probe.messages(), probe.SCHEMA, before_dispatch=before, observe=observer)
        else:
            result = gen.generate_neutral(probe.messages(), probe.SCHEMA, before_dispatch=before, observe=observer)
            assert result.final_retokenized_tokens == 8 and result.finish_reason == "eos"
        assert len(sends) == (0 if fault in {"late_send", "late_observer"} else 1)
        assert gen._deadline is None
    finally:
        gen.close()


@pytest.fixture
def preparation(tmp_path, monkeypatch):
    binding = {"head": "a" * 40, "freeze_sha256": "b" * 64,
               "bound_files": {"synthetic.py": "c" * 64}, "fixture_spec": probe.fixture_spec()}
    class Proof:
        head = "a" * 40
        def __call__(self, *args, **kwargs):
            pass
    monkeypatch.setattr(probe, "integrity", lambda root, proof=None: (copy.deepcopy(binding), proof or Proof()))
    metadata = {"repo_id": probe.MODEL_ID, "revision": probe.MODEL_REVISION,
                "trust_remote_code": False, "download_authorized": False, "transformers_version": "synthetic",
                "assets_sha256": {name: "a" * 64 for name in ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja")}}
    calls = []
    class Tokenizer:
        def apply_chat_template(self, messages, **kwargs):
            calls.append("template")
            return PROMPT
        def encode(self, prompt, **kwargs):
            calls.append("encode")
            return TOKENS
    def loader(allow_download):
        assert allow_download is False
        calls.append("load")
        return Tokenizer(), metadata
    return tmp_path, calls, loader


def test_register_once_exact_count_and_private_public_split(preparation):
    root, calls, loader = preparation
    result = probe.register(root, loader=loader)
    assert result["status"] == "passed" and calls == ["load", "template", "encode"]
    prepared = probe.check(root)
    assert prepared["private"]["prompt"] == PROMPT
    public = (root / probe.PLAN).read_text() + (root / probe.RECEIPT).read_text()
    assert PROMPT not in public and "A new neutral check" not in public and "token_ids\":" not in public
    with pytest.raises(FileExistsError):
        probe.register(root, loader=loader)
    assert calls == ["load", "template", "encode"]


def test_out_of_range_preparation_consumes_once_without_search(preparation):
    root, _calls, loader = preparation
    tokenizer, metadata = loader(False)
    tokenizer.encode = lambda *a, **k: [1] * 5121
    result = probe.register(root, loader=lambda _: (tokenizer, metadata))
    assert result["status"] == "failed" and result["input_tokens"] == 5121
    assert not (root / probe.PLAN).exists()
    with pytest.raises(FileExistsError):
        probe.register(root, loader=loader)


def test_private_input_drift_rejected_before_generation(preparation):
    root, _, loader = preparation
    probe.register(root, loader=loader)
    target = root / probe.PREPARATION / "input.json"
    target.write_bytes(target.read_bytes().replace(b"new synthetic", b"bad synthetic", 1))
    with pytest.raises(probe.CommonFailure):
        probe.check(root)


def run_fixture(preparation, monkeypatch, fault=None):
    root, _, loader = preparation
    probe.register(root, loader=loader)
    prepared = probe.check(root)
    launches, generated, checkpoints = [], [], []
    active = [None]
    if fault == "source_before_send":
        original_verify, verifies = probe.verify, []
        def drift(prepared):
            verifies.append(True)
            if len(verifies) == 4:
                raise probe.CommonFailure("placement_common_integrity")
            original_verify(prepared)
        monkeypatch.setattr(probe, "verify", drift)
    @contextmanager
    def factory(*, gpu_layers, telemetry, **kwargs):
        launches.append(gpu_layers)
        active[0] = gpu_layers
        telemetry.update(process_started=False, process_absence_confirmed=True)
        if fault == "startup" and gpu_layers == 24:
            raise OSError("synthetic startup failure")
        telemetry.update(process_started=True, process_absence_confirmed=False)
        service = SimpleNamespace(url="unused", token="not-logged", manifest="unused", process=SimpleNamespace(pid=1),
                                  drain=None, cleanup=telemetry)
        try:
            yield service
        finally:
            telemetry.update(stopped=True, within_budget=not (fault == "cleanup" and gpu_layers == 24),
                cleanup_errors=0, seconds=0.01, cleanup_attempted=True,
                drain={"eof": True, "joined": True, "read_errors": 0, "join_errors": 0,
                       "emitted_bytes": 7 if fault == "diagnostics" and gpu_layers == 24 else 0})
    monkeypatch.setattr(probe, "cleanup_owned", lambda *args: None)
    class Generator:
        def __init__(self, *args):
            self.observer = None
        def load(self):
            if fault == "identity" and active[0] == 24:
                raise GenerationError("generation_identity_mismatch")
        def public_metadata(self):
            return {"identity": "same"}
        def _remaining(self):
            remaining = self.outer_deadline - time.monotonic()
            if remaining <= 0:
                raise GenerationError("generation_deadline_exceeded")
            return remaining
        def close(self):
            pass
        def generate_neutral(self, messages, schema, *, stress, before_dispatch, observe):
            assert stress is False
            generated.append(active[0])
            before_dispatch(PROMPT, TOKENS, probe.request_body(messages, schema))
            self.observer("http_send_attempt", True)
            if fault in {"timeout", "timeout_and_join"} and active[0] == 24:
                raise GenerationError("generation_deadline_exceeded")
            self.observer("native_response", response())
            return ThinkingResult('{"marker":"teal"}', "A new neutral check.", 5000,
                21 if fault == "different_tokens" and active[0] == 28 else 20, 8, "eos", 0.01,
                {"grammar_sha256": "a" * 64})
    @contextmanager
    def watchdog(process, metrics, seconds):
        metrics.update(watchdog_fired=False, watchdog_joined=True)
        try:
            yield
        finally:
            if fault == "timeout_and_join" and active[0] == 24:
                metrics["watchdog_joined"] = False
                raise OSError("later cleanup failure")
    @contextmanager
    def rss(process, metrics, deadline):
        metrics.update(joined=True, sample_count=0, max_sample_bytes=None)
        yield
    def gpu(identity):
        checkpoints.append(identity)
        return {"query_stopped": fault != "gpu_child", "uuid": "GPU-11111111", "error": None,
                "total_mib": 6141, "used_mib": 123, "free_mib": 6018, "process_vram_mib": None}
    report = probe.run(prepared, factory=factory, generator_factory=Generator, gpu=gpu, rss=rss, watchdog=watchdog)
    return report, launches, generated, checkpoints, prepared


@pytest.mark.parametrize("fault,expected", [(None, [24, 28]), ("timeout", [24, 28]),
    ("startup", [24, 28]), ("diagnostics", [24, 28]), ("cleanup", [24]), ("identity", [24]), ("gpu_child", [])])
def test_control_failure_continuation_requires_safe_common_state(preparation, monkeypatch, fault, expected):
    report, launches, _, _, _ = run_fixture(preparation, monkeypatch, fault)
    assert launches == expected
    if fault in {"timeout", "startup", "diagnostics"}:
        assert report["arms"][0]["status"] == "failed"
        assert report["arms"][1]["status"] == "passed_resources_only"
        assert report["pair_execution_completed"] and not report["resources_all_passed"]
    if fault in {"cleanup", "identity", "gpu_child"}:
        assert report["unexecuted_arms"] == ["gpu28-candidate"]
    if fault is None:
        assert all(r["status"] == "passed_resources_only" for r in report["arms"])
        for row in report["arms"]:
            assert [row[k] for k in ("dispatch_reservations", "http_send_attempts", "parsed_native_responses", "contract_valid_results")] == [1, 1, 1, 1]


def test_pair_is_once_only_and_public_contains_no_raw_values(preparation, monkeypatch):
    report, _, _, checkpoints, prepared = run_fixture(preparation, monkeypatch)
    assert len(checkpoints) == 8
    public = probe.encoded(report)
    for private in (PROMPT.encode(), b"A new neutral check.", b'"token_ids":', b'"content":', b"not-logged"):
        assert private not in public
    with pytest.raises(FileExistsError):
        probe.run(prepared)


def test_unequal_output_counts_never_report_latency_ratio(preparation, monkeypatch):
    report, *_ = run_fixture(preparation, monkeypatch, "different_tokens")
    assert report["observed_latency_ratio_24_over_28"] is None


def test_common_source_drift_before_send_blocks_both_generations(preparation, monkeypatch):
    report, launches, _, _, _ = run_fixture(preparation, monkeypatch, "source_before_send")
    assert launches == [24]
    assert report["arms"][0]["http_send_attempts"] == 0
    assert report["arms"][0]["dispatch_reservations"] == 0
    assert report["unexecuted_arms"] == ["gpu28-candidate"]


def test_first_native_failure_survives_later_watchdog_cleanup_error(preparation, monkeypatch):
    report, launches, *_ = run_fixture(preparation, monkeypatch, "timeout_and_join")
    row = report["arms"][0]
    assert launches == [24]
    assert row["error"]["code"] == "generation_deadline_exceeded"
    assert row["later_cleanup_error"]["type"] == "OSError"
    assert row["parsed_native_responses"] == row["contract_valid_results"] == 0


def test_missing_gpu_is_null_and_no_launch(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", lambda _: None)
    row = probe.gpu_checkpoint()
    assert row["total_mib"] is None and row["error"] == "utility_unavailable" and row["query_stopped"]


def test_rss_stops_at_deadline_without_sampling_fake_pid():
    metrics = {}
    with probe.bounded_rss(SimpleNamespace(pid=-1), metrics, time.monotonic() - 1):
        pass
    assert metrics["joined"] and metrics["sample_count"] == 0 and metrics["max_sample_bytes"] is None


def test_rss_list_is_bounded_to_361_with_same_quarter_second_interval(monkeypatch):
    import psutil
    waits = []
    class Event:
        def is_set(self):
            return False
        def wait(self, seconds):
            waits.append(seconds)
        def set(self):
            pass
    class Thread:
        def __init__(self, target, **kwargs):
            self.target = target
        def start(self):
            self.target()
        def join(self, **kwargs):
            pass
        def is_alive(self):
            return False
    monkeypatch.setattr(probe.threading, "Event", Event)
    monkeypatch.setattr(probe.threading, "Thread", Thread)
    monkeypatch.setattr(time, "monotonic", lambda: 0)
    monkeypatch.setattr(psutil, "Process", lambda _: SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=123)))
    metrics = {}
    with probe.bounded_rss(SimpleNamespace(pid=123), metrics, 1):
        pass
    assert metrics["sample_count"] == 361 and len(metrics["samples"]) == 361
    assert set(waits) == {0.25} and metrics["max_sample_bytes"] == 123


def test_gpu_late_success_is_null_and_cleanup_is_separate(monkeypatch):
    now = [0.0]
    class Process:
        returncode = 0
        stdout = None
        def communicate(self, timeout):
            assert 0 < timeout <= 1
            now[0] = 1.01
            return b"GPU-11111111, 6141, 123, 6018\n", None
        def poll(self):
            return 0
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    monkeypatch.setattr(probe.shutil, "which", lambda _: "synthetic-utility")
    monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **k: Process())
    row = probe.gpu_checkpoint()
    assert row["error"] == "gpu_query_unavailable" and row["used_mib"] is None
    assert row["query_stopped"] and row["query_seconds"] == 1.01 and row["cleanup_seconds"] == 0


def test_source_allowlist_rejects_new_candidate_before_read(tmp_path, monkeypatch):
    for name in ("pyproject.toml", "uv.lock"):
        (tmp_path / name).write_bytes(b"synthetic environment contract\n")
    for name in probe.OWNED:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"import scripts.new_negative_candidate\n")
    monkeypatch.setattr(probe, "PINNED", {})
    frozen = probe.source_manifest(tmp_path)
    target = tmp_path / "scripts/new_negative_candidate.py"
    target.write_bytes(b"raise AssertionError('never read or execute')\n")
    original, reads = probe.primitives.snapshot, []
    def observed(path):
        reads.append(Path(path))
        return original(path)
    monkeypatch.setattr(probe.primitives, "snapshot", observed)
    with pytest.raises(ValueError, match="placement_code_allowlist"):
        probe.source_manifest(tmp_path, sealed=frozen)
    assert target not in reads


@pytest.mark.parametrize("fault", ["path", "mkdir", "serialization"])
def test_all_evidence_write_failures_are_common(tmp_path, monkeypatch, fault):
    if fault == "path":
        def fail(*args):
            raise ValueError("c4_relative_path")
        monkeypatch.setattr(probe.primitives, "path", fail)
    elif fault == "mkdir":
        def fail(*args, **kwargs):
            raise OSError("synthetic mkdir failure")
        monkeypatch.setattr(Path, "mkdir", fail)
    with pytest.raises(probe.CommonFailure, match="placement_evidence_persistence"):
        probe.write_new(tmp_path, "new/artifact.json", {"invalid": object()} if fault == "serialization" else {})


def test_invalid_cli_is_safe_and_does_not_reserve(monkeypatch, capsys):
    monkeypatch.setattr(probe, "register", lambda: pytest.fail("not authorized"))
    assert probe.main(["run", "--retry"]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "placement_cli_arguments"


def test_cli_pair_completion_is_separate_from_resources(monkeypatch, capsys):
    monkeypatch.setattr(probe, "check", dict)
    monkeypatch.setattr(probe, "run", lambda _: {"status": "completed_pair", "pair_execution_completed": True,
        "resources_all_passed": False, "arms": [{"id": name, "status": "failed"} for name, _ in probe.ARMS]})
    assert probe.main(["run"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["pair_execution_completed"] and not summary["resources_all_passed"]
    assert all(row["status"] == "failed" for row in summary["arms"])


def test_result_dataclass_has_no_effective_gpu_claim():
    result = ThinkingResult("synthetic", "synthetic", 1, 1, 1, "eos", 1, {})
    assert "gpu_layers_effective" not in dataclasses.asdict(result)


def test_stage_accounting_keeps_unobserved_boundaries_null():
    failed = {"request_seconds": 4.0, "stages_seconds": {"timed_verify": 1.0}}
    probe.summarize_stage_timing(failed)
    assert failed["stages_seconds"]["native_http"] is None
    assert failed["stage_timing"]["unattributed_request_seconds"] is None
    assert len(failed["stage_timing"]["missing_stage_boundaries"]) == 4
    complete = {"request_seconds": 7.0,
                "stages_seconds": dict.fromkeys(failed["stages_seconds"], 1.0),
                "http_seconds": {"native_http_seconds": 1.0}}
    probe.summarize_stage_timing(complete)
    assert complete["stage_timing"]["stage_sum_seconds"] == 5.0
    assert complete["stage_timing"]["unattributed_request_seconds"] == 2.0
