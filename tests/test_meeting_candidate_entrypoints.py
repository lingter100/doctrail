"""Synthetic startup/cleanup boundaries; no real model or Java process is launched."""
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from doctrail import meeting_worker_grammar as worker_entry
from doctrail.meeting_answer_grammar import DECODER_POLICY, GRAMMAR_SHA256
from doctrail.meeting_answer_v2 import ANSWER_POLICY, EvidenceFirstMeetingRuntime
from doctrail.meeting_worker import create_app
from scripts import serve_meetings_candidate as launcher

TOKEN = "synthetic-worker-token-" + "x" * 32
NATIVE_TOKEN = "synthetic-native-token-" + "y" * 32


@pytest.fixture
def launched(tmp_path, monkeypatch):
    jar = tmp_path / "app.jar"
    jar.write_bytes(b"synthetic")
    state = SimpleNamespace(processes=[], stopped=[], events=[], waits=[], fail_at=None,
        health={"experimental": True, "answer_policy": ANSWER_POLICY,
                "runtime": {"answer_decoder": {"policy": DECODER_POLICY,
                                                 "grammar_sha256": GRAMMAR_SHA256}}})

    @contextmanager
    def native(**kwargs):
        state.events.append("native_started")
        state.native_args = kwargs
        try:
            yield SimpleNamespace(process="owned-native", token=NATIVE_TOKEN,
                url="http://127.0.0.1:19003", manifest=tmp_path / "manifest.json")
        finally:
            state.events.append("native_stopped")

    def popen(arguments, **kwargs):
        process = SimpleNamespace(number=len(state.processes), args=arguments, kwargs=kwargs)
        state.processes.append(process)
        return process

    def stop(process):
        state.stopped.append(process.number)
        state.events.append(f"stopped_{process.number}")

    def ready(process, url, **kwargs):
        state.waits.append((url, kwargs))
        if state.fail_at == len(state.waits):
            raise RuntimeError("PRIVATE child readiness failure")
        return state.health if "/api/health" not in url else {"status": "ok"}

    monkeypatch.setattr(launcher, "start_llama", native)
    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    monkeypatch.setattr(launcher, "stop_process", stop)
    monkeypatch.setattr(launcher, "wait_ready", ready)
    monkeypatch.setattr(launcher, "java_executable", lambda: "java")
    state.arguments = {"jar": jar, "database": tmp_path / "candidate.sqlite3",
        "log_dir": tmp_path / "logs", "java_port": 19001, "worker_port": 19002,
        "llama_port": 19003, "retrieval_port": 19004, "token": TOKEN}
    return state


def test_candidate_starts_explicit_worker_loopback_and_scoped_credentials(launched, monkeypatch):
    monkeypatch.setenv("DOCTRAIL_LLAMA_TOKEN", "stale-secret")
    monkeypatch.setenv("DOCTRAIL_INFERENCE_URL", "http://remote.invalid")
    monkeypatch.setenv("DOCTRAIL_INFERENCE_TOKEN", "stale-inference-secret")
    monkeypatch.setenv("DOCTRAIL_EMBEDDING_PROFILE", "terminal")
    with launcher.start_services(**launched.arguments) as services:
        assert services.llama == "owned-native" and services.retrieval is None
        worker, java = launched.processes
        assert "doctrail.meeting_worker_grammar" in worker.args
        assert "--server.address=127.0.0.1" in java.args
        assert worker.kwargs["env"]["DOCTRAIL_LLAMA_TOKEN"] == NATIVE_TOKEN
        assert java.kwargs["env"]["DOCTRAIL_GENERATION_TOKEN"] == TOKEN
        assert "DOCTRAIL_LLAMA_TOKEN" not in java.kwargs["env"]
        for process in (worker, java):
            assert TOKEN not in repr(process.args) and NATIVE_TOKEN not in repr(process.args)
            assert process.kwargs["env"]["DOCTRAIL_EMBEDDING_PROFILE"] == "base"
            assert "DOCTRAIL_INFERENCE_URL" not in process.kwargs["env"]
            assert process.kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        assert launched.waits[0][1]["headers"] == {"Authorization": "Bearer " + TOKEN}
    assert launched.stopped == [1, 0]
    assert launched.events[-1] == "native_stopped"
    assert all(p.kwargs["stdout"].closed for p in launched.processes)


def test_retrieval_is_base_cpu_and_cannot_use_generation_tokens(launched):
    with launcher.start_services(**launched.arguments, retrieval=True) as services:
        worker, retrieval, java = launched.processes
        assert services.retrieval is retrieval
        assert retrieval.args[retrieval.args.index("--device") + 1] == "cpu"
        assert retrieval.kwargs["env"]["CUDA_VISIBLE_DEVICES"] == ""
        assert "DOCTRAIL_GENERATION_TOKEN" not in retrieval.kwargs["env"]
        assert "DOCTRAIL_LLAMA_TOKEN" not in retrieval.kwargs["env"]
        retrieval_token = retrieval.kwargs["env"]["DOCTRAIL_INFERENCE_TOKEN"]
        assert retrieval_token != TOKEN
        assert java.kwargs["env"]["DOCTRAIL_INFERENCE_TOKEN"] == retrieval_token
        assert "DOCTRAIL_INFERENCE_TOKEN" not in worker.kwargs["env"]
    assert launched.stopped == [2, 1, 0]
    assert launched.events[-1] == "native_stopped"


@pytest.mark.parametrize("fail_at,expected", [(1, [0]), (2, [1, 0]), (3, [2, 1, 0])])
def test_readiness_failure_unwinds_only_owned_children(launched, fail_at, expected):
    launched.fail_at = fail_at
    with pytest.raises(RuntimeError, match="readiness failure"), launcher.start_services(
            **launched.arguments, retrieval=True):
        pytest.fail("failed startup yielded services")
    assert launched.stopped == expected
    assert launched.events[-1] == "native_stopped"
    assert all(p.kwargs["stdout"].closed for p in launched.processes)


def test_wrong_answer_policy_health_never_starts_java(launched):
    launched.health["answer_policy"] = "other"
    with pytest.raises(RuntimeError, match="identity_mismatch"), launcher.start_services(
            **launched.arguments):
        pytest.fail("wrong policy accepted")
    assert len(launched.processes) == 1 and launched.stopped == [0]


@pytest.mark.parametrize("change", [{"java_port": True}, {"worker_port": -1},
    {"llama_port": 70000}, {"worker_port": 19001}, {"token": "too-short"}])
def test_invalid_configuration_fails_before_any_child(launched, change):
    with pytest.raises(ValueError), launcher.start_services(**{**launched.arguments, **change}):
        pytest.fail("invalid startup accepted")
    assert not launched.processes and not launched.events


@pytest.fixture
def worker_cli(tmp_path, monkeypatch):
    state = SimpleNamespace(events=[], load_error=False, serve_error=False)
    monkeypatch.setenv("DOCTRAIL_GENERATION_TOKEN", TOKEN)
    monkeypatch.setenv("DOCTRAIL_LLAMA_TOKEN", NATIVE_TOKEN)
    monkeypatch.setattr("sys.argv", ["worker", "--llama-url", "http://127.0.0.1:19003",
                                    "--llama-manifest", str(tmp_path / "manifest.json")])

    @contextmanager
    def admission(root, *, external_gpu_owner):
        assert external_gpu_owner is True
        state.events.append("lease_enter")
        try:
            yield
        finally:
            state.events.append("lease_exit")

    class Generator:
        def __init__(self, url, token, manifest):
            assert token == NATIVE_TOKEN and state.events == ["lease_enter"]
        def load(self):
            state.events.append("load")
            if state.load_error:
                raise RuntimeError("PRIVATE credential and document")
            return self
        def public_metadata(self):
            return {"repo_id": "synthetic", "revision": "synthetic"}
        def close(self):
            state.events.append("close")

    def serve(app, **kwargs):
        state.events.append("serve")
        assert kwargs == {"host": "127.0.0.1", "port": 8092,
                          "access_log": False, "log_level": "critical"}
        if state.serve_error:
            raise RuntimeError("PRIVATE model output")

    monkeypatch.setattr(worker_entry, "worker_admission", admission)
    monkeypatch.setattr(worker_entry, "GrammarAnswerGenerator", Generator)
    monkeypatch.setattr("uvicorn.run", serve)
    return state


def test_worker_cli_load_and_lifetime_are_inside_existing_worker_lease(worker_cli):
    worker_entry.main()
    assert worker_cli.events == ["lease_enter", "load", "serve", "close", "lease_exit"]


@pytest.mark.parametrize("failure", ["load_error", "serve_error"])
def test_worker_cli_errors_close_generator_release_lease_and_redact(worker_cli, capsys, failure):
    setattr(worker_cli, failure, True)
    with pytest.raises(SystemExit) as raised:
        worker_entry.main()
    assert raised.value.code == 2
    assert worker_cli.events[-2:] == ["close", "lease_exit"]
    assert capsys.readouterr().err == "experimental_generation_startup_failed\n"


def test_http_candidate_auth_and_failed_answer_never_fallback():
    class Generator:
        def public_metadata(self):
            return {"repo_id": "synthetic", "revision": "synthetic"}
        def count_tokens(self, prompt):
            return 100
        def generate_bounded(self, prompt, deadline):
            return SimpleNamespace(text=json.dumps({"status": "answered", "claims": [
                {"evidence": [{"id": 0, "quote": "PRIVATE invented quote"}], "text": "A claim."}]}),
                finish_reason="eos", input_tokens=100, output_tokens=20, elapsed_seconds=0.1)
        def close(self):
            pass

    with TestClient(create_app(TOKEN, lambda: EvidenceFirstMeetingRuntime(Generator()))) as client:
        assert client.get("/health").status_code == 401
        response = client.post("/answer", headers={"Authorization": "Bearer " + TOKEN}, json={
            "schema_version": 1, "query": "What happened?", "contexts": [{"document_id": "d",
                "revision": 1, "chunk_id": "c", "title": "source", "meeting_date": None,
                "page": None, "start_offset": 0, "end_offset": 13, "text": "Exact source."}]})
        assert response.status_code == 502
        assert "generation_invalid_evidence" in response.text
        assert "PRIVATE" not in response.text and "claims" not in response.json()
