"""Injected process/thread/HTTP/clock tests only. No server, tokenizer or model starts."""
import copy
import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest

from doctrail.model_retrieval import load_model_manifest
from scripts import serve_meeting_rag_service as launcher
from scripts.java_runtime import JavaRuntimeError, java_executable


def test_default_java_resolver_is_nonfrozen_unicode_protocol():
    assert launcher.start_services.__wrapped__.__kwdefaults__["java_resolver"] is java_executable


@pytest.mark.parametrize("code", sorted(JavaRuntimeError.CODES))
def test_java_discovery_error_is_preserved_before_any_service_start(rig, code):
    def fail():
        raise JavaRuntimeError(code)
    rig.kwargs["java_resolver"] = fail
    with (pytest.raises(launcher.LaunchError, match=f"^{code}$"),
          launcher.start_services(**rig.kwargs)):
        pytest.fail("discovery failure must not start services")
    assert rig.events == []
    assert rig.metrics["failure"] == code and rig.metrics["native_attempted"] is False
    assert rig.metrics["cleanup"]["accepted"] is True


def test_java_discovery_time_consumes_existing_startup_window(rig):
    def late():
        rig.now += 120
        return "synthetic-direct-java.exe"
    rig.kwargs["java_resolver"] = late
    with (pytest.raises(launcher.LaunchError, match="^startup_timeout$"),
          launcher.start_services(**rig.kwargs)):
        pytest.fail("Java discovery must not renew the startup window")
    assert rig.events == [] and rig.metrics["native_attempted"] is False


class Harness:
    def __init__(self, tmp_path):
        self.now = 100.0
        self.events, self.processes, self.waits, self.probes = [], [], [], []
        self.native_delay = self.stop_delay = self.join_delay = 0
        self.terminate_delay = 0
        self.enter_failure = False
        self.cleanup_overrides = {}
        self.probe_delay = 0
        self.stop_ok, self.context_error, self.worker_error = True, False, False
        self.not_ready = 0
        self.native_stopped = False
        self.tokens = iter(["A" * 48, "B" * 48])
        self.metrics = {}
        self.jar = tmp_path / "service.jar"
        self.jar.write_bytes(b"synthetic pinned jar")
        self.kwargs = {"jar": self.jar,
            "jar_sha256": hashlib.sha256(self.jar.read_bytes()).hexdigest(),
            "database": tmp_path / "isolated.sqlite3", "log_dir": tmp_path / "run",
            "java_port": 18000, "retrieval_port": 18001, "generation_port": 18002,
            "metrics": self.metrics, "native_factory": self.native_factory,
            "process_factory": self.process_factory, "server_factory": self.server_factory,
            "thread_factory": self.thread_factory, "probe": self.probe, "clock": lambda: self.now,
            "sleep": self.sleep, "token_factory": lambda: next(self.tokens),
            "java_resolver": lambda: "direct-java.exe",
            "environment": {"DOCTRAIL_GENERATION_TOKEN": "inherited-private",
                         "DOCTRAIL_DB": "private-user-database",
                         "LLAMA_API_KEY": "inherited-native-secret"}}
        metadata = {"repo_id": launcher.MODEL_ID, "original_revision": launcher.MODEL_REVISION,
            "revision": "gguf-sha256:" + launcher.GGUF_SHA256,
            "artifact": {"sha256": launcher.GGUF_SHA256}, "runtime": {
                "commit": launcher.RUNTIME_COMMIT, "context_tokens": 6144,
                "max_input_tokens": 5120, "max_new_tokens": 928, "deadline_seconds": 90}}
        self.generation_health = {"status": "ready", "protocol": launcher.PROTOCOL,
            "model": launcher.MODEL_ID, "revision": metadata["revision"],
            "answer": {**copy.deepcopy(metadata), "candidate_id": launcher.CANDIDATE_ID},
            "extraction": {"runtime": copy.deepcopy(metadata),
                "classification": launcher.classification_metadata("single"),
                "limits": {"input_tokens": 4096, "output_tokens": 768, "deadline_seconds": 120}}}
        specs = load_model_manifest()["models"]
        self.retrieval_health = {"status": "ready", "runtime": {"device": "cpu",
            "embedding_dtype": "torch.float32", "reranker_dtype": "torch.float32"},
            **{field: {"model": specs[key]["repo_id"], "revision": specs[key]["revision"],
                      "max_length": 512} for key, field in
               (("e5", "embedding"), ("reranker", "reranker"))}}
        self.retrieval_health["embedding"]["dimension"] = 384
        self.java_health = {"status": "ok", "version": "0.1.0"}
        self.app = SimpleNamespace(state=SimpleNamespace())
        self.thread = None

    def sleep(self, seconds):
        self.now += seconds

    def process_factory(self, argv, **kwargs):
        name = "retrieval" if "doctrail.inference" in argv else "java"
        harness = self
        class Process:
            alive = True
            def poll(self):
                return None if self.alive else 0
            def terminate(self):
                harness.events.append(name + "_terminate")
                harness.now += harness.terminate_delay
                self.alive = False
            def kill(self):
                harness.events.append(name + "_kill")
                self.alive = False
            def wait(self, timeout):
                harness.waits.append((name, timeout, harness.now))
                if self.alive:
                    raise subprocess.TimeoutExpired(name, timeout)
                return 0
        process = Process()
        process.argv, process.env = argv, kwargs["env"]
        assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        self.processes.append(process)
        self.events.append(name + "_start")
        return process

    def native_factory(self, **kwargs):
        harness = self
        self.native_policy = kwargs["analysis_policy"]
        assert kwargs["token"] == "A" * 48
        self.native_metrics = kwargs["telemetry"].setdefault("native", {})
        class Native:
            def __enter__(self):
                harness.events.append("native_enter")
                harness.now += harness.native_delay
                harness.native_metrics.update(process_started=True, stopped=False)
                if harness.enter_failure:
                    harness.stop_native()
                    harness.events.append("native_internal_unwind")
                    raise RuntimeError("private startup error after native cleanup")
                return harness.app
            def __exit__(self, *args):
                harness.events.append("native_exit")
                if not harness.native_stopped:
                    harness.stop_native()
                if harness.context_error:
                    raise RuntimeError("private native exception")
        return Native()

    def stop_native(self):
        self.events.append("native_stop")
        self.now += self.stop_delay
        self.native_stopped = True
        self.native_metrics.update(stopped=True, within_budget=self.stop_ok,
            cleanup_attempted=True, seconds=self.stop_delay, cleanup_errors=0,
            drain={"joined": True, "read_errors": 0, "join_errors": 0})
        self.native_metrics.update(self.cleanup_overrides)
        return self.stop_ok

    def server_factory(self, app, port):
        harness = self
        assert port == 18002
        class Server:
            should_exit = False
            force_exit = False
            def run(self):
                harness.events.append("worker_run")
                if harness.worker_error:
                    raise RuntimeError("private native exception")
                app.state.runtime = SimpleNamespace(_stop=harness.stop_native)
        self.server = Server()
        return self.server

    def thread_factory(self, *, target, name, daemon):
        harness = self
        class Thread:
            alive = False
            def start(self):
                self.alive = True
                target()
            def is_alive(self):
                return self.alive
            def join(self, timeout):
                harness.events.append("worker_join")
                harness.waits.append(("worker", timeout, harness.now))
                assert harness.native_stopped
                assert harness.server.should_exit
                spent = min(timeout, harness.join_delay)
                harness.now += spent
                self.alive = harness.join_delay > timeout
        self.thread = Thread()
        return self.thread

    def probe(self, url, token, timeout):
        self.probes.append((url, token, timeout, self.now))
        self.now += self.probe_delay
        if self.not_ready:
            self.not_ready -= 1
            return None
        if ":18002/" in url:
            assert token == "A" * 48
            return copy.deepcopy(self.generation_health)
        if ":18001/" in url:
            assert token == "B" * 48
            return copy.deepcopy(self.retrieval_health)
        assert token is None
        return copy.deepcopy(self.java_health)

    def assert_stopped(self):
        assert all(process.poll() is not None for process in self.processes)
        assert self.thread is None or not self.thread.is_alive()
        assert self.native_stopped

    def record(self):
        return json.loads((self.kwargs["log_dir"] / "lifecycle.json").read_text())


@pytest.fixture
def rig(tmp_path):
    harness = Harness(tmp_path)
    yield harness
    # Tests that intentionally model a surviving thread release the fake handle.
    # These are plain Python objects, never OS resources.
    if harness.thread:
        harness.thread.alive = False
    for process in harness.processes:
        process.alive = False


def test_assembly_auth_identity_explicit_java_config_and_cleanup_order(rig):
    with launcher.start_services(**rig.kwargs) as service:
        assert service.java_url == "http://127.0.0.1:18000"
        assert rig.metrics["startup_accepted"]
        retrieval, java = rig.processes
        assert retrieval.argv[retrieval.argv.index("--device") + 1] == "cpu"
        assert retrieval.env["CUDA_VISIBLE_DEVICES"] == ""
        assert "--doctrail.rag-answer-enabled=true" in java.argv
        assert "--doctrail.embedding-profile=base" in java.argv
        assert "private-user-database" not in repr(java.argv)
        assert java.env["DOCTRAIL_GENERATION_TOKEN"] != java.env["DOCTRAIL_INFERENCE_TOKEN"]
        assert "LLAMA_API_KEY" not in java.env
    assert rig.events == ["retrieval_start", "native_enter", "worker_run", "java_start",
                          "java_terminate", "retrieval_terminate", "native_stop",
                          "worker_join", "native_exit"]
    rig.assert_stopped()
    record = rig.record()
    assert record["cleanup"]["accepted"]
    assert record["java_config"]["verification"] == "pinned_jar_and_explicit_arguments_only"
    for secret in ("A" * 48, "B" * 48, "inherited-private", "inherited-native-secret"):
        assert secret not in json.dumps(record) and secret not in repr(service)


def test_late_native_entry_is_startup_failure_and_no_java_or_worker(rig):
    rig.native_delay = 121
    with (pytest.raises(launcher.LaunchError, match="startup_timeout"),
          launcher.start_services(**rig.kwargs)):
        pytest.fail("must not accept expired startup")
    assert "java_start" not in rig.events and "worker_run" not in rig.events
    assert rig.record()["startup_seconds"] == 121
    rig.assert_stopped()


def test_all_http_readiness_consumes_one_startup_budget(rig):
    rig.native_delay = 115
    rig.probe_delay = 1.5
    with (pytest.raises(launcher.LaunchError, match="startup_timeout"),
          launcher.start_services(**rig.kwargs)):
        pytest.fail("must not accept expired Java readiness")
    assert rig.record()["startup_accepted"] is False
    assert rig.probes[-1][2] <= 0.5
    rig.assert_stopped()


@pytest.mark.parametrize("field", ["model", "revision", "protocol"])
def test_wrong_generation_identity_never_starts_java(rig, field):
    rig.generation_health[field] = "wrong"
    with (pytest.raises(launcher.LaunchError, match="generation_health_identity"),
          launcher.start_services(**rig.kwargs)):
        pytest.fail("wrong identity accepted")
    assert "java_start" not in rig.events
    rig.assert_stopped()


@pytest.mark.parametrize("field,value", [("device", "cuda"), ("embedding_dtype", "torch.float16")])
def test_retrieval_cpu_and_base_identity_required(rig, field, value):
    rig.retrieval_health["runtime"][field] = value
    with (pytest.raises(launcher.LaunchError, match="retrieval_health_identity"),
          launcher.start_services(**rig.kwargs)):
        pytest.fail("wrong CPU worker accepted")
    rig.assert_stopped()


def test_uvicorn_exception_relay_is_redacted_and_stops_owned_resources(rig):
    rig.worker_error = True
    with (pytest.raises(launcher.LaunchError, match="worker_thread_failed"),
          launcher.start_services(**rig.kwargs)):
        pytest.fail("failed worker accepted")
    assert "private native exception" not in json.dumps(rig.record())
    assert rig.events.index("native_exit") < rig.events.index("worker_join")
    rig.assert_stopped()


def test_child_failure_after_readiness_stops_new_work_without_restart(rig):
    with (pytest.raises(launcher.LaunchError, match="retrieval_exited"),
          launcher.start_services(**rig.kwargs) as service):
        rig.processes[0].alive = False
        service.monitor()
    assert rig.events.count("retrieval_start") == rig.events.count("java_start") == 1
    rig.assert_stopped()


def test_unhealthy_generation_after_startup_causes_cleanup(rig):
    with (pytest.raises(launcher.LaunchError, match="service_unhealthy"),
          launcher.start_services(**rig.kwargs) as service):
        rig.not_ready = 1
        service.monitor()
    assert rig.events.index("java_terminate") < rig.events.index("native_stop")
    rig.assert_stopped()


def test_native_cleanup_precedes_join_and_all_waits_use_remaining_five(rig):
    rig.stop_delay = 3
    rig.join_delay = 1
    with launcher.start_services(**rig.kwargs):
        pass
    assert rig.waits[0][0:2] == ("worker", 2)
    assert rig.waits[1][0:2] == ("java", 1)
    assert rig.waits[2][0:2] == ("retrieval", 1)
    assert rig.record()["cleanup"]["elapsed_seconds"] == 4
    rig.assert_stopped()


def test_slow_synchronous_native_cleanup_is_failure_but_context_still_closed(rig):
    rig.stop_delay = 6
    with (pytest.raises(launcher.LaunchError, match="owned_cleanup_failed"),
          launcher.start_services(**rig.kwargs)):
        pass
    record = rig.record()
    assert record["cleanup"]["elapsed_seconds"] == 6
    assert all(timeout == 0 for _, timeout, _ in rig.waits)
    assert rig.events[-1] == "native_exit"
    rig.assert_stopped()


def test_surviving_worker_is_not_claimed_stopped_and_context_cleanup_continues(rig):
    rig.join_delay = 8
    with (pytest.raises(launcher.LaunchError, match="owned_cleanup_failed"),
          launcher.start_services(**rig.kwargs)):
        pass
    record = rig.record()
    assert record["cleanup"]["alive"]["worker"]
    assert "worker_join_incomplete" in record["cleanup"]["errors"]
    assert rig.events[-1] == "native_exit" and rig.server.force_exit
    assert all(process.poll() is not None for process in rig.processes)


def test_both_primary_failure_and_cleanup_error_are_preserved(rig):
    rig.context_error = True
    with (pytest.raises(launcher.LaunchError, match="owned_cleanup_failed"),
          launcher.start_services(**rig.kwargs)):
        raise RuntimeError("private user text")
    record = rig.record()
    assert record["failure"] == "service_failed"
    assert "native_context_cleanup_failed" in record["cleanup"]["errors"]
    assert "private user text" not in json.dumps(record)
    rig.assert_stopped()


def test_duplicate_tokens_fail_before_process_creation(rig):
    rig.kwargs["token_factory"] = lambda: "same" * 12
    with (pytest.raises(launcher.LaunchError, match="token_factory_failed"),
          launcher.start_services(**rig.kwargs)):
        pytest.fail("duplicate credentials")
    assert rig.processes == []


def test_jar_pin_mismatch_and_reused_log_directory_fail_before_process_creation(rig):
    rig.kwargs["jar_sha256"] = "0" * 64
    with (pytest.raises(launcher.LaunchError, match="jar_pin_mismatch"),
          launcher.start_services(**rig.kwargs)):
        pytest.fail("wrong jar")
    rig.kwargs["jar_sha256"] = hashlib.sha256(rig.jar.read_bytes()).hexdigest()
    rig.kwargs["log_dir"].mkdir()
    with (pytest.raises(FileExistsError),
          launcher.start_services(**rig.kwargs)):
        pytest.fail("reused log directory")
    assert rig.processes == []


def test_no_optin_cli_never_starts_resources():
    with pytest.raises(SystemExit) as error:
        launcher.main([])
    assert error.value.code == 2


def test_foreign_launch_error_text_never_enters_lifecycle_record(rig):
    with (pytest.raises(launcher.LaunchError, match="service_failed"),
          launcher.start_services(**rig.kwargs)):
        raise launcher.LaunchError("A" * 48)
    assert "A" * 48 not in json.dumps(rig.record())
    rig.assert_stopped()


def test_process_observation_failure_does_not_skip_native_cleanup(rig):
    with (pytest.raises(launcher.LaunchError, match="owned_cleanup_failed"),
          launcher.start_services(**rig.kwargs)):
        java = rig.processes[1]
        original = java.poll
        observations = [0]
        def fail_once():
            observations[0] += 1
            if observations[0] == 1:
                raise OSError("private process detail")
            return original()
        java.poll = fail_once
    assert "java_poll_failed" in rig.record()["cleanup"]["errors"]
    assert rig.events[-1] == "native_exit"
    rig.assert_stopped()


def test_owned_native_cleanup_failure_is_retained(rig):
    rig.stop_ok = False
    with (pytest.raises(launcher.LaunchError, match="owned_cleanup_failed"),
          launcher.start_services(**rig.kwargs)):
        pass
    assert "native_cleanup_failed" in rig.record()["cleanup"]["errors"]
    rig.assert_stopped()


@pytest.mark.parametrize("overrides,seconds", [
    ({"within_budget": False}, 2),
    ({"cleanup_errors": 1}, 2),
    ({"drain": {"joined": True, "read_errors": 1, "join_errors": 0}}, 2),
    ({"drain": {"joined": True, "read_errors": 0, "join_errors": 1}}, 2),
    ({"within_budget": False}, 6),
])
def test_enter_failure_preserves_prior_native_cleanup_failure(rig, overrides, seconds):
    rig.enter_failure, rig.stop_delay, rig.cleanup_overrides = True, seconds, overrides
    with (pytest.raises(launcher.LaunchError, match="owned_cleanup_failed"),
          launcher.start_services(**rig.kwargs)):
        pytest.fail("startup failure must not yield")
    record = rig.record()
    assert record["failure"] == "service_failed"
    assert record["cleanup"]["accepted"] is False
    assert "native_cleanup_failed" in record["cleanup"]["errors"]
    assert record["cleanup"]["prior_native_cleanup_seconds"] == seconds
    assert record["cleanup"]["elapsed_seconds"] == seconds
    assert rig.waits[0][1] == max(0, 5 - seconds)
    assert rig.events.count("native_stop") == 1
    rig.assert_stopped()


@pytest.mark.parametrize("outer_seconds,accepted", [(0, True), (4, False)])
def test_prior_successful_native_cleanup_consumes_whole_cleanup_budget(rig, outer_seconds, accepted):
    rig.enter_failure, rig.stop_delay, rig.terminate_delay = True, 2, outer_seconds
    with (pytest.raises(launcher.LaunchError,
                        match="service_failed" if accepted else "owned_cleanup_failed"),
          launcher.start_services(**rig.kwargs)):
        pytest.fail("startup failure must not yield")
    cleanup = rig.record()["cleanup"]
    assert cleanup["accepted"] is accepted
    assert cleanup["prior_native_cleanup_seconds"] == 2
    assert cleanup["outer_elapsed_seconds"] == outer_seconds
    assert cleanup["elapsed_seconds"] == 2 + outer_seconds
    assert rig.waits[0][1] == max(0, 3 - outer_seconds)
    rig.assert_stopped()


def test_unconfirmed_prior_cleanup_time_fails_closed_without_new_wait_budget(rig):
    rig.enter_failure, rig.cleanup_overrides = True, {"seconds": None}
    with (pytest.raises(launcher.LaunchError, match="owned_cleanup_failed"),
          launcher.start_services(**rig.kwargs)):
        pytest.fail("startup failure must not yield")
    cleanup = rig.record()["cleanup"]
    assert cleanup["accepted"] is False
    assert "native_cleanup_time_unconfirmed" in cleanup["errors"]
    assert cleanup["prior_native_cleanup_seconds"] is None
    assert cleanup["elapsed_seconds"] is None
    assert rig.waits[0][1] == 0
    rig.assert_stopped()


@pytest.mark.parametrize("policy", ["single", "batch-v1", "batch-v2"])
def test_requested_policy_reaches_native_health_and_lifecycle(rig, policy):
    rig.kwargs["analysis_policy"] = policy
    rig.generation_health["extraction"]["classification"] = launcher.classification_metadata(policy)
    with launcher.start_services(**rig.kwargs):
        assert rig.native_policy == policy
    lifecycle = json.loads((rig.kwargs["log_dir"] / "lifecycle.json").read_text())
    assert lifecycle["analysis_policy"] == policy and lifecycle["cleanup"]["accepted"] is True


@pytest.mark.parametrize("field,value", [("policy", "single"), ("batch_cap", 7),
    ("output_cap", 127), ("prompt_sha256", "a" * 64), ("grammar_policy_sha256", "a" * 64)])
@pytest.mark.parametrize("policy", ["batch-v1", "batch-v2"])
def test_batch_health_mismatch_fails_closed(rig, field, value, policy):
    rig.kwargs["analysis_policy"] = policy
    metadata = launcher.classification_metadata(policy)
    metadata[field] = value
    rig.generation_health["extraction"]["classification"] = metadata
    with (pytest.raises(launcher.LaunchError, match="generation_health_identity"),
          launcher.start_services(**rig.kwargs)):
        pytest.fail("mismatched policy ready")
    assert rig.metrics["cleanup"]["accepted"] and all(p.poll() is not None for p in rig.processes)


def test_unknown_policy_rejected_before_any_resource(rig):
    rig.kwargs["analysis_policy"] = "auto"
    with (pytest.raises(launcher.LaunchError, match="invalid_analysis_policy"),
          launcher.start_services(**rig.kwargs)):
        pytest.fail("invalid policy")
    assert not rig.events and not rig.kwargs["log_dir"].exists()


@pytest.mark.parametrize("policy", [None, "batch-v1", "batch-v2"])
def test_combined_cli_policy_forwarding(monkeypatch, tmp_path, policy):
    from contextlib import contextmanager
    seen = []
    @contextmanager
    def start(**kwargs):
        seen.append(kwargs["analysis_policy"])
        yield SimpleNamespace(java_url="synthetic", monitor=lambda: None)
    monkeypatch.setattr(launcher, "start_services", start)
    args = ["--enable-service-rag", "--jar-sha256", "a" * 64,
            "--database", str(tmp_path / "db"), "--log-dir", str(tmp_path / "logs")]
    if policy:
        args.extend(["--analysis-policy", policy])
    launcher.main(args)
    assert seen == [policy or "single"]


@pytest.mark.parametrize("requested,reported", [("batch-v1", "batch-v2"), ("batch-v2", "batch-v1")])
def test_health_cannot_substitute_another_batch_prompt_policy(rig, requested, reported):
    rig.kwargs["analysis_policy"] = requested
    rig.generation_health["extraction"]["classification"] = launcher.classification_metadata(reported)
    with (pytest.raises(launcher.LaunchError, match="generation_health_identity"),
          launcher.start_services(**rig.kwargs)):
        pytest.fail("wrong batch prompt policy became ready")
    assert rig.metrics["cleanup"]["accepted"] is True