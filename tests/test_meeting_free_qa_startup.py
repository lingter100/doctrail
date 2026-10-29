"""Synthetic startup admission/HTTP/lifecycle checks. Never launch a real service."""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
import test_meeting_free_qa as q

from scripts import probe_meeting_free_qa_startup as s
from tools.free_qa import policy as p
from tools.free_qa import runner as r
from tools.free_qa.adapter import validate_props


def startup_metadata(tmp_path, monkeypatch):
    """Reuse existing public synthetic metadata; no asset/download or private input."""
    contract, locks = q.metadata_tree(tmp_path, monkeypatch)
    monkeypatch.setattr(s, "CODE_FILES", r.CODE_FILES)
    spec = {"schema_version": 1, "diagnostic": s.ID, "model": contract["models"][1],
            "code": contract["code"], "limits": dict(s.LIMITS), "once_sha256": "1" * 64,
            "output_dir": s.NAMESPACE + "/runs/" + "1" * 64}
    lock = {"schema_version": 1, "diagnostic": s.ID, "registration_sha256": "",
            "model_sha256": p.sha(p.canonical(spec["model"])),
            "binding_sha256": locks["reviewed_bindings"][p.CANDIDATE],
            "runtime_sha256": locks["runtime_sha256"], "code_sha256": p.sha(p.canonical(spec["code"]))}
    path = tmp_path / s.NAMESPACE / "registrations" / "synthetic.json"
    def save():
        registration = q.put(tmp_path, path.relative_to(tmp_path).as_posix(), p.canonical(spec))
        lock["registration_sha256"] = registration["sha256"]
        q.put(tmp_path, s.TRUSTED_LOCK_FILE, p.canonical(lock))
        return registration["sha256"]
    return spec, lock, path, save


def test_startup_public_admission_uses_fixed_trust_and_no_qa_reads(tmp_path, monkeypatch):
    spec, _, path, save = startup_metadata(tmp_path, monkeypatch)
    digest = save()
    original = r.read_ref
    reads = []
    def observed(row, root, **kwargs):
        reads.append(row["file"])
        assert not row["file"].startswith("inputs/")
        assert all(word not in row["file"] for word in ("criteria", "packet", "exclusion", "preflight-review"))
        return original(row, root, **kwargs)
    monkeypatch.setattr(r, "read_ref", observed)
    monkeypatch.setattr(r, "verify_contract", lambda *a, **k: pytest.fail("QA contract forbidden"))
    monkeypatch.setattr(r, "load_registration", lambda *a, **k: pytest.fail("QA registration forbidden"))
    monkeypatch.setattr(r.subprocess, "Popen", lambda *a, **k: pytest.fail("native forbidden"))
    actual, admitted, output, refs = s.verify_registration(path, digest, root=tmp_path)
    assert actual == spec and admitted.policy.model_id == p.CANDIDATE and len(refs) == 2
    assert not output.exists() and not (tmp_path / s.NAMESPACE / "once").exists()
    assert reads and admitted.seal is r._ADMITTED


@pytest.mark.parametrize("fault", ["lock_missing", "lock_registration", "lock_model", "lock_binding", "lock_runtime",
    "lock_code", "self_authority", "code_changed", "limit", "output", "model", "profile", "runtime", "gate",
    "extra", "boolean", "namespace", "once"])
def test_startup_metadata_denials_create_no_once_or_launch(tmp_path, monkeypatch, fault):
    spec, lock, path, save = startup_metadata(tmp_path, monkeypatch)
    if fault.startswith("lock_") and fault not in {"lock_missing", "lock_registration"}:
        lock[{"lock_model": "model_sha256", "lock_binding": "binding_sha256", "lock_runtime": "runtime_sha256",
              "lock_code": "code_sha256"}[fault]] = "0" * 64
    if fault == "self_authority": spec["trusted_locks"] = lock
    if fault == "limit": spec["limits"]["startup_seconds"] = 121
    if fault == "output": spec["output_dir"] = ".local/closed-comparison"
    if fault == "model": spec["model"]["id"] = p.BASE
    if fault == "profile": spec["model"]["profile"]["sha256"] = "0" * 64
    if fault == "runtime": spec["model"]["runtime"]["tag"] = "b1"
    if fault == "extra": spec["question"] = "PRIVATE forbidden"
    if fault == "boolean": spec["schema_version"] = True
    if fault == "once": spec["once_sha256"] = "wrong"
    if fault == "gate":
        raw = p.parse((tmp_path / spec["model"]["binding"]["file"]).read_bytes())
        gate = p.parse((tmp_path / raw["acquisition_gate"]["file"]).read_bytes())
        gate["actual_cli_exit"] = 1
        raw["acquisition_gate"] = q.put(tmp_path, raw["acquisition_gate"]["file"], p.canonical(gate))
        spec["model"]["binding"] = q.put(tmp_path, spec["model"]["binding"]["file"], p.canonical(raw))
        lock["binding_sha256"] = spec["model"]["binding"]["sha256"]
    if fault in {"model", "profile", "runtime", "gate"}:
        lock["model_sha256"] = p.sha(p.canonical(spec["model"]))
    digest = save()
    if fault == "lock_registration":
        lock["registration_sha256"] = "0" * 64
        q.put(tmp_path, s.TRUSTED_LOCK_FILE, p.canonical(lock))
    if fault == "lock_missing": (tmp_path / s.TRUSTED_LOCK_FILE).unlink()
    if fault == "code_changed": (tmp_path / spec["code"][0]["file"]).write_bytes(b"changed")
    if fault == "namespace": path = tmp_path / "elsewhere.json"
    monkeypatch.setattr(r.subprocess, "Popen", lambda *a, **k: pytest.fail("native forbidden"))
    with pytest.raises((ValueError, OSError, r.assets.BoundaryError)):
        s.verify_registration(path, digest, root=tmp_path)
    assert not (tmp_path / s.NAMESPACE / "once").exists()


def test_real_metadata_then_asset_denial_consumes_once_without_launch(tmp_path, monkeypatch):
    spec, _, path, save = startup_metadata(tmp_path, monkeypatch)
    digest = save()
    @contextmanager
    def lease(_): yield
    monkeypatch.setattr(r, "worker_lease", lease)
    def forbidden(*a, **k): pytest.fail("asset inventory denial must precede launch")
    report = s.run_startup(path, digest, spec["once_sha256"], root=tmp_path, clock=q.Clock(), launcher=forbidden)
    assert report["status"] == "stopped" and report["first_failure"]["code"] == "free_qa_model_inventory"
    assert report["counts"] == {"completions": 0, "requested_tokens": 0} and report["props_requests"] == 0
    assert len(list((tmp_path / s.NAMESPACE / "once").glob("*.json"))) == 2
    with pytest.raises(ValueError): s.run_startup(path, digest, spec["once_sha256"], root=tmp_path, launcher=forbidden)


@pytest.mark.parametrize("value", [None, {}, SimpleNamespace(seal=None)])
def test_preparer_rejects_unadmitted_objects(value):
    with pytest.raises(ValueError, match="admitted_model_required"):
        r.prepare_admitted_model(value, 120, clock=q.Clock())


def tiny_props(prepared):
    return {"model_alias": prepared.policy.alias, "build_info": "b11429-" + p.RUNTIME_COMMIT[:7],
            "model_path": str(prepared.entry), "default_generation_settings": {"n_ctx": 6144},
            "total_slots": 1, "is_sleeping": False, "chat_template": "SYNTHETIC TEMPLATE"}


@pytest.mark.parametrize("fault", [None, "alias", "build", "path", "ctx", "slot", "sleep", "template", "missing"])
def test_pure_props_validator_uses_same_runtime_identity(tmp_path, fault):
    verified, _, _ = q.tiny_preparation(tmp_path)
    prepared = r.prepare_model(verified, p.BASE, 120, clock=q.Clock())
    props = tiny_props(prepared)
    if fault == "alias": props["model_alias"] = "wrong"
    if fault == "build": props["build_info"] = "b11429-0000000"
    if fault == "path": props["model_path"] += "changed"
    if fault == "ctx": props["default_generation_settings"]["n_ctx"] = True
    if fault == "slot": props["total_slots"] = True
    if fault == "sleep": props["is_sleeping"] = True
    if fault == "template": props["chat_template"] += "PRIVATE"
    if fault == "missing": del props["model_path"]
    if fault:
        with pytest.raises((ValueError, KeyError)): validate_props(props, prepared)
    else:
        assert validate_props(props, prepared) == {"build": props["build_info"], "context_tokens": 6144, "slots": 1}


@pytest.mark.parametrize("fault", [None, "redirect", "timeout", "network", "status", "length", "oversize",
    "encoding", "json", "list", "duplicate", "late", "resource", "url", "token", "exact_limit", "client_late"])
def test_props_is_one_bounded_get_with_no_generation_or_response_retention(tmp_path, monkeypatch, fault):
    verified, _, _ = q.tiny_preparation(tmp_path)
    clock = q.Clock()
    prepared = r.prepare_model(verified, p.BASE, 120, clock=clock)
    service = SimpleNamespace(url="http://127.0.0.1:54321", token="t" * 40)
    if fault == "url": service.url = "https://example.invalid"
    if fault == "token": service.token = "PRIVATE\n"
    sent, settings = [], []
    original_client = httpx.Client
    def client(**kwargs):
        settings.append(kwargs)
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        if fault == "client_late": clock.now = 121
        return original_client(**kwargs)
    monkeypatch.setattr(s.httpx, "Client", client)
    def handler(request):
        sent.append((request.method, request.url.path))
        assert request.content == b""
        if fault == "redirect": return httpx.Response(302, headers={"location": "https://example.invalid"})
        if fault == "timeout": raise httpx.ReadTimeout("PRIVATE token")
        if fault == "network": raise httpx.ConnectError("PRIVATE token")
        if fault == "status": return httpx.Response(500, content=b"PRIVATE error")
        if fault == "length": return httpx.Response(200, headers={"content-length": str(1024**2 + 1)})
        if fault == "oversize": return httpx.Response(200, stream=httpx.ByteStream(b"x" * (1024**2 + 1)))
        if fault == "encoding": return httpx.Response(200, headers={"content-encoding": "gzip"})
        if fault == "json": return httpx.Response(200, stream=httpx.ByteStream(b"PRIVATE broken"))
        if fault == "list": return httpx.Response(200, stream=httpx.ByteStream(b"[]"))
        if fault == "duplicate": return httpx.Response(200, stream=httpx.ByteStream(b'{"x":1,"x":2}'))
        if fault == "late": clock.now = 121
        if fault == "exact_limit":
            body = p.canonical(tiny_props(prepared))
            return httpx.Response(200, stream=httpx.ByteStream(body + b" " * (1024**2 - len(body))))
        return httpx.Response(200, stream=httpx.ByteStream(p.canonical(tiny_props(prepared))))
    def check():
        if fault == "resource": raise ValueError("summary_mode_resources")
    metrics = {"props_requests": 0, "props_valid": False}
    if fault not in {None, "exact_limit"}:
        with pytest.raises((ValueError, TypeError)):
            s.fetch_props(service, prepared, 120, metrics, check, clock=clock, transport=httpx.MockTransport(handler))
    else:
        s.fetch_props(service, prepared, 120, metrics, check, clock=clock, transport=httpx.MockTransport(handler))
        assert metrics["props_valid"] is True
        with pytest.raises(ValueError, match="once"):
            s.fetch_props(service, prepared, 120, metrics, check, clock=clock, transport=httpx.MockTransport(handler))
    assert sent == ([] if fault in {"url", "token", "resource", "client_late"} else [("GET", "/props")])
    assert metrics["props_requests"] == len(sent)
    assert set(metrics) == {"props_requests", "props_valid"}
    assert "PRIVATE" not in p.canonical(metrics).decode()


def synthetic_run(tmp_path, monkeypatch, fault):
    """Reuse tiny preparation plus an explicit metadata-boundary double, never fake PreparedModel."""
    verified, _, _ = q.tiny_preparation(tmp_path)
    admitted = verified.admitted_models[0]
    policy_raw = p.thaw(admitted.policy.reviewed)
    for key in ("metadata_receipt", "review_receipt", "acquisition_gate"):
        policy_raw[key] = q.put(tmp_path, f"synthetic/{key}.json", b'{"synthetic":true}')
    policy = replace(admitted.policy, reviewed=policy_raw)
    model = p.thaw(admitted.descriptor)
    model.update(profile=q.put(tmp_path, "synthetic/profile.json", b'{"synthetic":true}'),
                 binding=q.put(tmp_path, "synthetic/binding.json", p.canonical(policy_raw)), runtime=p.thaw(policy.runtime))
    admitted = replace(admitted, descriptor=p.freeze(model), policy=policy)
    once = "1" * 64
    spec = {"code": [], "once_sha256": once}
    fixed = (q.put(tmp_path, "synthetic/fixed.json", b"synthetic"),)
    output = tmp_path / s.NAMESPACE / "runs" / once
    clock, launched, prepared_calls = q.Clock(), [], []
    monkeypatch.setattr(s, "verify_registration", lambda *a, **k: (spec, admitted, output, fixed))
    @contextmanager
    def lease(_):
        if fault == "lease": raise ValueError("PRIVATE lease detail")
        yield
    monkeypatch.setattr(r, "worker_lease", lease)
    @contextmanager
    def launcher(prepared, deadline, metrics, **kwargs):
        launched.append(1)
        assert deadline == 120
        metrics.update(process_creation_attempted=True, owned_create_time=1)
        try:
            with r.diagnostic_phase(metrics, "native_readiness", clock):
                clock.now += 4
                if fault in {"readiness", "dual", "exit"}:
                    error = RuntimeError("service_startup_exited") if fault == "exit" else TimeoutError("service_startup_timeout")
                    metrics["readiness_error"] = r.safe_error(error)
                    metrics["readiness_guard_failure"] = "summary_mode_resources" if fault == "dual" else None
                    if fault == "dual": raise ValueError("summary_mode_resources")
                    raise error
            yield SimpleNamespace(url="http://127.0.0.1:54321", token="t" * 40, process=q.FakeProcess())
        finally:
            metrics.update(within_budget=fault != "cleanup", process_absence_confirmed=fault != "cleanup",
                           native_returncode_before_cleanup=17 if fault == "exit" else None)
    def preparer(value, deadline, **kwargs):
        prepared_calls.append(1)
        assert value is admitted and deadline == 120
        if fault == "prepare": raise ValueError("PRIVATE preparation")
        if fault == "prelaunch_changed": (tmp_path / fixed[0]["file"]).write_bytes(b"changed before launch")
        return r.prepare_admitted_model(value, deadline, **kwargs)
    class Guard(q.FakeGuard):
        failure = None
        @contextmanager
        def arm(self, deadline, target):
            try: yield
            finally:
                if fault == "props_dual":
                    self.failure = "ownership"
                    raise ValueError("summary_mode_ownership")
    def guard(*a, **k):
        if fault == "guard": raise ValueError("summary_mode_ownership")
        return Guard()
    monkeypatch.setattr(r, "make_resource_guard", guard)
    requests = []
    def handler(request):
        requests.append((request.method, request.url.path))
        if fault in {"props", "props_dual"}: return httpx.Response(500, content=b"PRIVATE response")
        if fault == "changed": (tmp_path / fixed[0]["file"]).write_bytes(b"changed")
        if fault == "startup_late": clock.now = 121
        if fault == "whole_late": clock.now = 186
        if fault == "storage": (output / "report.json").write_bytes(b"preserved collision")
        prepared = r.prepare_admitted_model(admitted, 300, clock=q.Clock())
        return httpx.Response(200, stream=httpx.ByteStream(p.canonical(tiny_props(prepared))))
    def run():
        return s.run_startup("synthetic", "2" * 64, once, root=tmp_path, clock=clock,
                             preparer=preparer, launcher=launcher, transport=httpx.MockTransport(handler))
    return run, output, launched, prepared_calls, requests


@pytest.mark.parametrize("fault", [None, "prepare", "readiness", "dual", "exit", "guard", "props", "props_dual",
    "cleanup", "changed", "startup_late", "whole_late", "storage", "lease", "prelaunch_changed"])
def test_startup_lifecycle_retains_errors_cleanup_custody_and_once(tmp_path, monkeypatch, fault):
    run, output, launched, prepared, requests = synthetic_run(tmp_path, monkeypatch, fault)
    if fault in {"lease", "storage", "whole_late"}:
        with pytest.raises((ValueError, OSError)): run()
        if fault == "lease":
            assert not output.exists() and not prepared and not launched
            return
        assert (output / "late-invalidation.json").exists()
    else:
        report = run()
        assert report["status"] == ("startup_validated" if fault is None else "stopped")
        assert report["counts"] == {"completions": 0, "requested_tokens": 0}
        assert report["health_requests"] == "not_instrumented" and report["requires_external_terminal_custody"] is True
        assert report["health_ready"] is (fault not in {"prepare", "readiness", "dual", "exit", "prelaunch_changed"})
        assert report["props_requests"] == len(requests) <= 1
        assert report["props_valid"] is (fault in {None, "cleanup", "changed"})
        assert report["bindings_unchanged"] is (fault not in {"cleanup", "changed", "prelaunch_changed"})
        if fault == "prelaunch_changed": assert launched == [] and requests == []
        assert "PRIVATE" not in p.canonical(report).decode()
        assert report["phases"][-1]["phase"] == "final_custody"
        if fault == "dual":
            assert report["first_failure"]["code"] == "service_startup_timeout"
            assert report["secondary_failures"][0]["code"] == "summary_mode_resources"
        if fault == "props_dual":
            assert report["first_failure"]["code"] == "free_qa_startup_props_status"
            assert report["secondary_failures"][0]["code"] == "summary_mode_ownership"
        if fault == "exit": assert report["native_failure_classification"] == "native_startup_unknown"
        if fault in {"guard", "props", "cleanup", "changed", "startup_late"}:
            expected = {"guard": "summary_mode_ownership", "props": "free_qa_startup_props_status",
                        "cleanup": "free_qa_startup_cleanup", "changed": "free_qa_boundary",
                        "startup_late": "free_qa_deadline"}
            assert report["first_failure"]["code"] == expected[fault]
        terminal = p.parse((output / "terminal.json").read_bytes())
        assert terminal["diagnostic"] == s.ID and "epoch" not in terminal and "contract_sha256" not in terminal
        assert terminal["report_sha256"] == p.sha((output / "report.json").read_bytes())
    before = (len(launched), len(prepared), len(requests))
    with pytest.raises(FileExistsError): run()
    assert before == (len(launched), len(prepared), len(requests))
    assert all(item == ("GET", "/props") for item in requests)


def test_cli_verify_cannot_execute_and_errors_are_opaque(monkeypatch, capsys):
    called = []
    monkeypatch.setattr(s, "verify_registration", lambda *a, **k: called.append(1))
    monkeypatch.setattr(s, "run_startup", lambda *a, **k: pytest.fail("run forbidden"))
    assert s.main(["verify", "--registration", "synthetic", "--sha256", "a" * 64]) == 0
    assert called == [1] and json.loads(capsys.readouterr().out)["execution_approved"] is False
    def denied(*a, **k): raise OSError("PRIVATE path token")
    monkeypatch.setattr(s, "verify_registration", denied)
    assert s.main(["verify", "--registration", "synthetic", "--sha256", "a" * 64]) == 1
    assert "PRIVATE" not in capsys.readouterr().out
