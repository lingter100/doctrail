"""Launcher assembly only: no assets loaded, process started, or network called."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from scripts import serve_meeting_service_rag as launcher


@pytest.mark.parametrize("policy,assembly", [("single", "legacy"), ("batch-v1", "legacy"),
    ("batch-v2", "legacy"), ("batch-v2", "coverage-v1"), ("batch-v2", "grounded-summary-v1"),
    ("batch-v2", "grounded-summary-v2"), ("batch-v2", "grounded-summary-v3")])
def test_gpu28_native_then_worker_admission_and_owned_cleanup(monkeypatch, tmp_path, policy, assembly):
    events, metrics = [], {}
    native = SimpleNamespace(process=object(), drain=object(), cleanup={})
    @contextmanager
    def start_llama(**kwargs):
        events.append(("native", kwargs["gpu_layers"]))
        assert kwargs["phase_deadline"] > 0
        yield native
        events.append("native_exit")
    @contextmanager
    def admission(root, **kwargs):
        assert kwargs == {"external_gpu_owner": True}
        events.append("worker")
        yield
        events.append("worker_exit")
    def cleanup(process, drain, values):
        assert process is native.process and drain is native.drain
        values["within_budget"] = True
        events.append("cleanup")
    class Runtime:
        closed = False
        def close(self):
            if not self.closed:
                self.closed = True
                assert self.cleanup()
    def load(native_arg, *, cleanup, startup_deadline, analysis_policy, extraction_assembly):
        assert native_arg is native
        assert analysis_policy == policy and extraction_assembly == assembly
        assert startup_deadline > 0
        result = Runtime()
        result.cleanup = cleanup
        events.append("load")
        return result
    monkeypatch.setattr(launcher, "start_llama", start_llama)
    monkeypatch.setattr(launcher, "worker_admission", admission)
    monkeypatch.setattr(launcher, "cleanup_owned", cleanup)
    monkeypatch.setattr(launcher, "load_runtime", load)
    with launcher.start_service(token="x" * 40, log_dir=tmp_path / "new", telemetry=metrics,
                                analysis_policy=policy, extraction_assembly=assembly):
        events.append("serve")
    assert events == [("native", 28), "worker", "load", "serve",
                      "cleanup", "worker_exit", "native_exit"]
    assert metrics["native_adapter_startup_seconds"] >= 0
    assert metrics["analysis_policy"] == policy
    assert metrics["extraction_assembly"] == assembly
    if assembly in launcher.GROUNDED_ASSEMBLIES:
        assert metrics["grounded_summary"] == launcher.summary_metadata(assembly)
    else:
        assert "grounded_summary" not in metrics


def test_cli_requires_explicit_opt_in_before_any_start(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "start_service", lambda **kwargs: pytest.fail("started"))
    with pytest.raises(SystemExit) as error:
        launcher.main(["--log-dir", str(tmp_path)])
    assert error.value.code == 2


def test_expired_identity_load_never_serves_and_closes_owned_native(monkeypatch, tmp_path):
    clock, events = [10.0], []
    @contextmanager
    def native(**kwargs):
        try:
            yield SimpleNamespace(process=None, drain=None, cleanup={})
        finally:
            events.append("native_exit")
    @contextmanager
    def admission(*args, **kwargs):
        yield
    class Runtime:
        def close(self):
            events.append("closed")
    def load(*args, **kwargs):
        assert kwargs["startup_deadline"] == 130
        clock[0] = 131
        return Runtime()
    monkeypatch.setattr(launcher.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(launcher, "start_llama", native)
    monkeypatch.setattr(launcher, "worker_admission", admission)
    monkeypatch.setattr(launcher, "load_runtime", load)
    with (pytest.raises(ValueError, match="generation_startup_timeout"),
          launcher.start_service(token="x" * 40, log_dir=tmp_path)):
        pytest.fail("must not serve expired startup")
    assert events == ["closed", "native_exit"]


@pytest.mark.parametrize("policy", [None, "batch-v1", "batch-v2"])
def test_cli_passes_explicit_analysis_policy_without_server(monkeypatch, tmp_path, policy):
    import uvicorn
    seen = []
    @contextmanager
    def start(**kwargs):
        seen.append(kwargs["analysis_policy"])
        yield object()
    monkeypatch.setattr(launcher, "start_service", start)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)
    args = ["--enable-service-rag", "--log-dir", str(tmp_path)]
    if policy:
        args.extend(["--analysis-policy", policy])
    launcher.main(args)
    assert seen == [policy or "single"]


def test_invalid_analysis_policy_rejected_before_native(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "start_llama", lambda **kwargs: pytest.fail("native attempted"))
    with (pytest.raises(ValueError, match="invalid_analysis_policy"),
          launcher.start_service(token="x" * 40, log_dir=tmp_path, analysis_policy="auto")):
        pytest.fail("invalid policy admitted")

@pytest.mark.parametrize("policy,assembly", [("single", "coverage-v1"), ("batch-v1", "coverage-v1"),
    ("single", "grounded-summary-v1"), ("batch-v1", "grounded-summary-v1"),
    ("single", "grounded-summary-v2"), ("batch-v1", "grounded-summary-v2"),
    ("single", "grounded-summary-v3"), ("batch-v1", "grounded-summary-v3"),
    ("batch-v2", "auto")])
def test_incompatible_assembly_rejected_before_native(monkeypatch, tmp_path, policy, assembly):
    monkeypatch.setattr(launcher, "start_llama", lambda **kwargs: pytest.fail("native attempted"))
    with (pytest.raises(ValueError, match="invalid_extraction_assembly"),
          launcher.start_service(token="x" * 40, log_dir=tmp_path, analysis_policy=policy,
                                 extraction_assembly=assembly)):
        pytest.fail("invalid assembly admitted")


@pytest.mark.parametrize("assembly", [None, "legacy", "coverage-v1", "grounded-summary-v1", "grounded-summary-v2", "grounded-summary-v3"])
def test_worker_cli_forwards_assembly(monkeypatch, tmp_path, assembly):
    import uvicorn
    seen = []
    @contextmanager
    def start(**kwargs):
        seen.append((kwargs["analysis_policy"], kwargs["extraction_assembly"]))
        yield object()
    monkeypatch.setattr(launcher, "start_service", start)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)
    args = ["--enable-service-rag", "--log-dir", str(tmp_path), "--analysis-policy", "batch-v2"]
    if assembly is not None:
        args.extend(["--extraction-assembly", assembly])
    launcher.main(args)
    assert seen == [("batch-v2", assembly or "legacy")]
