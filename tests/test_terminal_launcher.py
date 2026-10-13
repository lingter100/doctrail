"""Synthetic child-process lifecycle checks; no JVM/GPU work is launched."""

from pathlib import Path

import pytest

from doctrail.terminal_inference import PROFILE, TERMINAL_MODEL, TERMINAL_REVISION
from scripts import serve_terminal_models as launcher

TOKEN = "synthetic-launcher-token-" + "x" * 32


@pytest.fixture
def launch_setup(tmp_path, monkeypatch):
    jar = tmp_path / "synthetic.jar"
    jar.write_bytes(b"synthetic")
    args = {"jar": jar, "database": tmp_path / "db.sqlite3", "model_root": tmp_path / "models",
            "device": "cpu", "token": TOKEN, "log_dir": tmp_path / "logs", "java_port": 12001,
            "worker_port": 12002}
    monkeypatch.setattr(launcher, "preflight", lambda *args: ({}, tmp_path / "checkpoint", {}))
    monkeypatch.setattr(launcher, "java_executable", lambda: Path("synthetic-java"))
    processes, starts, stops = [], [], []

    class Process:
        def poll(self):
            return None

    def start(command, **kwargs):
        process = Process()
        processes.append(process)
        starts.append((command, kwargs))
        return process

    monkeypatch.setattr(launcher.subprocess, "Popen", start)
    monkeypatch.setattr(launcher, "stop_process", lambda process: stops.append(process))
    health = {"schema_version": 1, "status": "ready",
              "embedding": {"model": TERMINAL_MODEL, "revision": TERMINAL_REVISION,
                            "dimension": 384, "max_length": 512},
              "reranker": {"model": "BAAI/bge-reranker-v2-m3",
                           "revision": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e", "max_length": 512},
              "runtime": {"device": "cpu", "embedding_dtype": "torch.float32",
                          "reranker_dtype": "torch.float32"}}

    def ready(process, url, **kwargs):
        if url.endswith("/api/health"):
            return {"status": "ok"}
        assert kwargs["headers"] == {"Authorization": "Bearer " + TOKEN}
        return health

    monkeypatch.setattr(launcher, "wait_ready", ready)
    return args, processes, starts, stops, health


def test_explicit_profile_token_env_only_loopback_and_owned_cleanup(launch_setup, monkeypatch):
    args, processes, starts, stops, _ = launch_setup
    monkeypatch.setenv("DOCTRAIL_EMBEDDING_PROFILE", "inherited-untrusted-profile")
    with launcher.start_terminal_services(**args) as services:
        assert services.worker is processes[0] and services.java is processes[1]
        assert services.java_url == "http://127.0.0.1:12001"
        assert not stops
        for command, options in starts:
            assert TOKEN not in " ".join(command)
            assert options["env"]["DOCTRAIL_INFERENCE_TOKEN"] == TOKEN
            assert options["env"]["DOCTRAIL_EMBEDDING_PROFILE"] == PROFILE
            assert options["env"]["HF_HUB_OFFLINE"] == "1"
            assert options["env"]["TRANSFORMERS_OFFLINE"] == "1"
        assert "doctrail.terminal_inference" in starts[0][0]
        assert "--server.address=127.0.0.1" in starts[1][0]
    assert stops == processes[::-1]
    assert all(TOKEN not in path.read_text() for path in args["log_dir"].iterdir())


def test_wrong_worker_identity_stops_worker_before_java(launch_setup):
    args, processes, _, stops, health = launch_setup
    health["embedding"]["revision"] = "synthetic-wrong-checkpoint"
    with (pytest.raises(ValueError, match="terminal_worker_identity_mismatch"),
          launcher.start_terminal_services(**args)):
        pytest.fail("must fail")
    assert len(processes) == 1 and stops == processes


def test_java_readiness_failure_cleans_both_owned_children(launch_setup, monkeypatch):
    args, processes, _, stops, _ = launch_setup
    original = launcher.wait_ready

    def readiness(process, url, **kwargs):
        if url.endswith("/api/health"):
            raise TimeoutError("synthetic startup timeout")
        return original(process, url, **kwargs)

    monkeypatch.setattr(launcher, "wait_ready", readiness)
    with pytest.raises(TimeoutError), launcher.start_terminal_services(**args):
        pytest.fail("must fail")
    assert len(processes) == 2 and stops == processes[::-1]


def test_preflight_refusal_starts_no_children(launch_setup, monkeypatch):
    args, processes, _, stops, _ = launch_setup

    def fail(*args):
        raise ValueError("public_receipt_hash_mismatch")

    monkeypatch.setattr(launcher, "preflight", fail)
    with (pytest.raises(ValueError, match="public_receipt_hash_mismatch"),
          launcher.start_terminal_services(**args)):
        pytest.fail("must fail")
    assert not processes and not stops


@pytest.mark.parametrize("change", [{"token": "weak"}, {"device": "automatic"},
                                    {"java_port": 12002}, {"worker_port": -1}])
def test_invalid_launch_arguments_start_no_children(launch_setup, change):
    args, processes, _, _, _ = launch_setup
    args.update(change)
    with pytest.raises(ValueError), launcher.start_terminal_services(**args):
        pytest.fail("must fail")
    assert not processes
