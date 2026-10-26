"""Synthetic request/lifetime boundaries only: no model, tokenizer or native execution."""
import copy
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts import probe_meeting_local_candidate as probe


def documents():
    text = "목적: 안전한 변경을 검토한다.\n결정: 변경을 승인했다.\n작업: 담당자가 후속 점검을 한다.\n"
    return [{"id": f"doc-{i}", "document_id": f"00000000-0000-0000-0000-{i:012d}",
             "revision": 1, "title": "합성 회의", "content": text, "content_sha256": probe.sha(text.encode()),
             "question": {"id": f"question-{i}", "text": "어떤 결정을 내렸나?"}} for i in range(1, 5)]


def input_data():
    return {"schema_version": 1, "diagnostic": probe.ID, "documents": documents()}


class Clock:
    def __init__(self):
        self.now = 0.0
    def __call__(self):
        return self.now


def adapter_fixture(tmp_path, *, alter=None, clock=None):
    clock = clock or Clock()
    requests, observed = [], []
    def handle(request):
        payload = json.loads(request.content) if request.content else None
        requests.append((request.url.path, copy.deepcopy(payload)))
        if request.url.path == "/apply-template":
            response = {"prompt": "EMBEDDED-MISTRAL-TEMPLATE " + json.dumps(payload["messages"], ensure_ascii=False)}
        elif request.url.path == "/tokenize":
            response = {"tokens": [101, 102, 103]}
        else:
            assert request.url.path == "/completion"
            stage = adapter.stage
            raw = ({"status": "draft", "claims": [{"text": "변경을 승인했다.", "evidence": [1]}]}
                   if stage == "summary" else {"claims": [[0, "supported"]], "coverage": "sufficient"}
                   if stage == "review" else {"status": "answered", "claims": [{"text": "변경을 승인했다.", "evidence": [1]}]})
            response = {"model": probe.MODEL_SHA, "generation_settings": copy.deepcopy(payload),
                        "truncated": False, "stop": True, "stop_type": "eos", "tokens_predicted": 2,
                        "tokens": [201, 202], "tokens_evaluated": len(payload["prompt"]),
                        "timings": {"cache_n": 0, "prompt_n": len(payload["prompt"]), "predicted_n": 2},
                        "content": json.dumps(raw, ensure_ascii=False)}
        if alter:
            replacement = alter(adapter, request.url.path, payload, response, clock)
            if isinstance(replacement, httpx.Response):
                return replacement
        return httpx.Response(200, json=response)
    adapter = probe.CandidateAdapter("http://127.0.0.1:54321", "t" * 40, tmp_path / "profile.json",
            clock=clock, transport=httpx.MockTransport(handle), observe=lambda *x: observed.append(x))
    adapter._alias = probe.MODEL_SHA
    return adapter, requests, observed, clock


def test_input_preserves_exact_content_and_question():
    data = input_data()
    result = probe.validate_input(data)
    assert result == data["documents"] and result is not data["documents"]
    result[0]["question"]["text"] = "changed"
    assert data["documents"][0]["question"]["text"] != "changed"


@pytest.mark.parametrize("change", ["three", "digest", "question", "private", "duplicate", "revision"])
def test_input_rejects_substitution_or_extra_private_fields(change):
    data = input_data()
    if change == "three":
        data["documents"].pop()
    elif change == "digest":
        data["documents"][0]["content"] += "secretly changed"
    elif change == "question":
        data["documents"][0]["question"]["text"] = " "
    elif change == "private":
        data["documents"][0]["question"]["witness"] = "must not reach a model"
    elif change == "duplicate":
        data["documents"][1]["question"]["id"] = data["documents"][0]["question"]["id"]
    else:
        data["documents"][0]["revision"] = True
    with pytest.raises((probe.CandidateFailure, ValueError)):
        probe.validate_input(data)


def test_full_fixed_schedule_source_gaps_and_qa_evidence(tmp_path):
    adapter, requests, _observed, clock = adapter_fixture(tmp_path)
    events = []
    docs = documents()
    report = probe.diagnose(docs, adapter, active_deadline=900, clock=clock, emit=lambda *x: events.append(x))
    adapter.close()
    assert report["mechanically_complete"] and report["counts"] == {
        "summary": 4, "review": 4, "qa": 4, "requested_tokens": 4608, "http": 36}
    assert [x[1]["document"] for x in events if x[0] == "source"] == [d["id"] for d in docs]
    templates = [body for path, body in requests if path == "/apply-template"]
    assert all(set(body) == {"messages"} for body in templates)
    for index, body in enumerate(templates):
        payload = json.loads(body["messages"][-1]["content"])
        assert "".join(x["text"] for x in payload["source_parts"]) == docs[index // 3]["content"]
        if index % 3 == 2:
            assert payload["question"] == docs[index // 3]["question"]["text"]
    qa = next(value["parsed"] for kind, value in events if kind == "qa")
    cite = qa["claims"][0]["citations"][0]
    assert docs[0]["content"][cite["start_offset"]:cite["end_offset"]] == cite["quote"]
    assert cite["chunk_id"].startswith(docs[0]["document_id"] + ":1:")


@pytest.mark.parametrize("stage", ["summary", "review", "qa"])
def test_content_rejection_preserved_next_fixed_items_continue(tmp_path, stage):
    fired = []
    def alter(adapter, path, _payload, response, _clock):
        if path == "/completion" and adapter.stage == stage and not fired:
            fired.append(True)
            response["content"] = ('{"claims":[[0,"unsupported"]],"coverage":"insufficient"}'
                if stage == "review" else '{"status":"draft","claims":[{"text":"오류","evidence":[999]}]}'
                if stage == "summary" else '{"status":"answered","claims":[{"text":"오류","evidence":[999]}]}')
    adapter, _requests, _observed, clock = adapter_fixture(tmp_path, alter=alter)
    events = []
    report = probe.diagnose(documents(), adapter, active_deadline=900, clock=clock, emit=lambda *x: events.append(x))
    adapter.close()
    assert report["operational_complete"] and not report["mechanically_complete"]
    assert report["documents"][0][stage]["status"] == "rejected"
    assert report["documents"][-1]["qa"]["status"] == "valid"
    assert report["counts"]["summary"] == report["counts"]["qa"] == 4
    assert report["counts"]["review"] == (3 if stage == "summary" else 4)
    assert report["first_failure"]["stage"] == stage


@pytest.mark.parametrize("fault", ["token-count", "settings", "deadline", "resource"])
def test_operational_failure_blocks_remaining_calls(tmp_path, fault):
    def alter(_adapter, path, _payload, response, clock):
        if path == "/completion":
            if fault == "token-count":
                response["tokens"] = []
            elif fault == "settings":
                response["generation_settings"]["temperature"] = 0.7
            elif fault == "deadline":
                clock.now = 120
    adapter, requests, _observed, clock = adapter_fixture(tmp_path, alter=alter)
    if fault == "resource":
        def fail_resource():
            raise probe.CandidateFailure("resources")
        adapter.resource_check = fail_resource
    report = probe.diagnose(documents(), adapter, active_deadline=900, clock=clock, emit=lambda *x: None)
    before = len(requests)
    with pytest.raises(probe.CandidateFailure):
        adapter.complete("other", "qa", [], 900)
    adapter.close()
    assert len(requests) == before and not report["operational_complete"]
    assert report["documents"][0]["qa"]["status"] == "unexecuted"
    assert all(row["summary"]["status"] == "unexecuted" for row in report["documents"][1:])


def test_shared_summary_review_deadline_does_not_restart(tmp_path):
    def alter(adapter, path, _payload, _response, clock):
        if path == "/completion" and adapter.stage == "summary":
            clock.now = 119
        elif path == "/apply-template" and adapter.stage == "review":
            clock.now += 2
    adapter, requests, _observed, clock = adapter_fixture(tmp_path, alter=alter)
    report = probe.diagnose(documents(), adapter, active_deadline=900, clock=clock, emit=lambda *x: None)
    adapter.close()
    assert report["counts"]["summary"] == 1 and report["counts"]["review"] == report["counts"]["qa"] == 0
    assert len([x for x in requests if x[0] == "/completion"]) == 1
    assert report["stop_reason"]


def test_input_overflow_never_truncates_or_completes(tmp_path):
    def alter(_adapter, path, _payload, response, _clock):
        if path == "/tokenize":
            response["tokens"] = list(range(4097))
    adapter, requests, _observed, clock = adapter_fixture(tmp_path, alter=alter)
    report = probe.diagnose(documents(), adapter, active_deadline=900, clock=clock, emit=lambda *x: None)
    adapter.close()
    assert report["operational_complete"] and report["counts"]["requested_tokens"] == 0
    assert not any(path == "/completion" for path, _ in requests)
    assert all(row["summary"]["status"] == row["qa"]["status"] == "rejected" for row in report["documents"])


def test_completion_cap_and_duplicate_stage_never_send(tmp_path):
    adapter, requests, _observed, _clock = adapter_fixture(tmp_path)
    for i in range(4):
        adapter.complete(str(i), "summary", [], 120)
    count = len(requests)
    with pytest.raises(probe.CandidateFailure, match="stage_repeated"):
        adapter.complete("0", "summary", [], 120)
    assert len(requests) == count
    with pytest.raises(probe.CandidateFailure, match="completion_cap"):
        adapter.complete("fifth", "summary", [], 120)
    assert len([x for x in requests if x[0] == "/completion"]) == 4
    adapter.close()


def test_cli_requires_explicit_once_without_process(monkeypatch):
    monkeypatch.setattr(probe, "execute", lambda *args: pytest.fail("must not execute"))
    with pytest.raises(SystemExit) as error:
        probe.main(["--registration", "not-read.json"])
    assert error.value.code == 2


def test_candidate_argv_is_explicit_and_no_qwen_reasoning():
    argv = probe.command("server", "model", 1234)
    for flag, value in (("--host", "127.0.0.1"), ("--alias", probe.MODEL_SHA), ("--n-gpu-layers", "99"),
                        ("--ctx-size", "6144"), ("--parallel", "1"), ("--cache-type-k", "f16"),
                        ("--cache-type-v", "f16"), ("--reasoning", "off"), ("--fit", "off")):
        assert argv[argv.index(flag) + 1] == value
    assert all(flag in argv for flag in ("--no-warmup", "--no-context-shift", "--log-disable"))
    assert "--reasoning-budget" not in argv


@pytest.mark.parametrize("fault", ["identity", "drain", "readiness", "body"])
def test_launch_reuses_cleanup_on_exact_returned_handle(monkeypatch, tmp_path, fault):
    import psutil
    seen, environment = [], {}
    process = SimpleNamespace(pid=999, stdout=object())
    @contextmanager
    def lease(path):
        seen.append(("lease", path.name))
        yield
        seen.append(("release", path.name))
    @contextmanager
    def arm(*args):
        yield
    monkeypatch.setattr(probe, "worker_lease", lease)
    spec, registration, seal = registration_fixture(tmp_path, monkeypatch)
    prepared = probe.verify_registration(registration, seal(), tmp_path)[3]
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(available=10 * 1024**3))
    monkeypatch.setattr(probe, "unused_port", lambda: 1234)
    monkeypatch.setenv("LLAMA_ARG_N_GPU_LAYERS", "0")
    monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **k: environment.update(k["env"]) or process)
    def identity(p):
        assert p is process
        if fault == "identity":
            raise ValueError("first identity failure")
        return 123.0
    monkeypatch.setattr(probe, "owned_create_time", identity)
    class Drain:
        def __init__(self, stream):
            assert stream is process.stdout
            if fault == "drain":
                raise ValueError("first drain failure")
        def start(self):
            pass
    monkeypatch.setattr(probe, "DiscardDrain", Drain)
    monkeypatch.setattr(probe, "ResourceGuard", lambda *a, **k: SimpleNamespace(arm=arm))
    def ready(*a, **k):
        if fault == "readiness":
            raise ValueError("first readiness failure")
    monkeypatch.setattr(probe, "wait_ready", ready)
    monkeypatch.setattr(probe, "cleanup_owner", lambda p, d, m, **k: seen.append(("cleanup", p)))
    with pytest.raises(ValueError, match="first"):  # noqa: SIM117
        with probe.launch(tmp_path / probe.PROFILE, tmp_path / spec["model_root"], 120, {},
                          prepared=prepared, root=tmp_path, clock=lambda: 0):
            raise ValueError("first body failure")
    assert len([x for x in seen if x[0] == "cleanup"]) == 1
    assert next(x[1] for x in seen if x[0] == "cleanup") is process
    assert "LLAMA_ARG_N_GPU_LAYERS" not in environment and environment["LLAMA_API_KEY"]
    assert environment["HF_HUB_OFFLINE"] == environment["TRANSFORMERS_OFFLINE"] == "1"



def test_boolean_predicted_count_is_protocol_failure(tmp_path):
    def alter(_adapter, path, _payload, response, _clock):
        if path == "/completion":
            response.update(tokens_predicted=1, tokens=[201])
            response["timings"]["predicted_n"] = True
    adapter, _requests, _events, clock = adapter_fixture(tmp_path, alter=alter)
    report = probe.diagnose(documents(), adapter, active_deadline=900, clock=clock, emit=lambda *x: None)
    adapter.close()
    assert not report["operational_complete"]


def registration_fixture(tmp_path, monkeypatch):
    def write(name, data):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else probe.encoded(data))
        return {"file": name, "size_bytes": path.stat().st_size, "sha256": probe.sha(path.read_bytes())}
    metadata = {"size_bytes": len(b"synthetic artifact"), "sha256": probe.sha(b"synthetic artifact")}
    profile = write(probe.PROFILE, {"schema_version": 1,
                    "gguf": {"filename": "model.gguf", **metadata},
                    "llama": {"assets": [{"filename": "runtime.zip", **metadata}]},
                    "licenses": [{"filename": "license.txt", **metadata}]})
    monkeypatch.setattr(probe, "MODEL_SHA", metadata["sha256"])
    monkeypatch.setattr(probe, "PROFILE_SHA", profile["sha256"])
    monkeypatch.setattr(probe, "CODE_FILES", ("scripts/fake_driver.py",))
    code = write("scripts/fake_driver.py", b"# test-only code binding")
    source = write(".local/input.json", input_data())
    criteria = {key: write(".local/" + key + "-lock.json", b"PRIVATE CRITERION NOT MODEL INPUT") for key in ("summary", "qa")}
    model_root = "models/candidate"
    assets = [write(model_root + "/" + name, b"synthetic artifact")
              for name in ("model.gguf", "runtime/llama-server.exe", "licenses/license.txt", "downloads/runtime.zip")]
    assets.append(write(model_root + "/setup-receipt.json", {"schema_version": 1, "manifest_sha256": profile["sha256"],
                 "model": {"path": "model.gguf", **metadata}, "quality_verified": False,
                 "server_path": "runtime/llama-server.exe",
                 "runtime_files": {"llama-server.exe": metadata}, "licenses": {"licenses/license.txt": metadata}}))
    spec = {"schema_version": 1, "diagnostic": probe.ID, "prepared": True, "limits": probe.LIMITS,
            "profile": profile, "input": source, "criteria_locks": criteria, "code": [code], "assets": assets,
            "model_root": model_root, "output_dir": ".local/run/" + probe.ID, "order": [d["id"] for d in documents()]}
    path = tmp_path / "registration.json"
    def seal():
        path.write_bytes(probe.encoded(spec))
        return probe.sha(path.read_bytes())
    return spec, path, seal


@pytest.mark.parametrize("fault", [None, "digest", "criteria", "code", "asset", "existing", "outside", "order", "limits"])
def test_registration_binds_only_declared_files_and_refuses_changes(tmp_path, monkeypatch, fault):
    spec, path, seal = registration_fixture(tmp_path, monkeypatch)
    if fault == "criteria":
        (tmp_path / spec["criteria_locks"]["qa"]["file"]).write_bytes(b"changed")
    elif fault in ("code", "asset"):
        spec["code" if fault == "code" else "assets"].pop()
    elif fault == "existing":
        (tmp_path / spec["output_dir"]).mkdir(parents=True)
    elif fault == "outside":
        spec["output_dir"] = "../escape/" + probe.ID
    elif fault == "order":
        spec["order"] = list(reversed(spec["order"]))
    elif fault == "limits":
        spec["limits"] = {**probe.LIMITS, "qa_tokens": 257}
    digest = seal()
    monkeypatch.setattr(probe, "prepare", lambda *a, **k: pytest.fail("registration must not prepare"), raising=False)
    if fault:
        with pytest.raises((probe.CandidateFailure, ValueError)):
            probe.verify_registration(path, "0" * 64 if fault == "digest" else digest, tmp_path)
    else:
        verified, docs, output, prepared = probe.verify_registration(path, digest, tmp_path)
        assert prepared.model_root == tmp_path / spec["model_root"]
        assert verified == spec and docs == documents() and not output.exists()
        assert "PRIVATE CRITERION" not in json.dumps(docs)


def test_execute_preserves_startup_cause_and_once_output(tmp_path, monkeypatch):
    spec, path, seal = registration_fixture(tmp_path, monkeypatch)
    digest = seal()
    seen = []
    @contextmanager
    def launcher(*args, **kwargs):
        seen.append("once")
        raise probe.CandidateFailure("synthetic_startup")
        yield  # pragma: no cover - contextmanager shape only
    monkeypatch.setattr(probe, "launch", launcher)
    result = probe.execute(path, digest, root=tmp_path, clock=lambda: 0)
    assert result["first_failure"]["code"] == "local_candidate_synthetic_startup"
    assert (tmp_path / spec["output_dir"] / "report.json").is_file()
    with pytest.raises(probe.CandidateFailure, match="output_scope"):
        probe.execute(path, digest, root=tmp_path, clock=lambda: 0)
    assert seen == ["once"]



@pytest.mark.parametrize("fault", ["body-close", "late-seal"])
def test_execute_first_cause_and_terminal_deadline(tmp_path, monkeypatch, fault):
    from scripts import probe_meeting_gpu_placement as gpu
    _spec, path, seal = registration_fixture(tmp_path, monkeypatch)
    digest = seal()
    clock, calls = Clock(), []
    @contextmanager
    def launcher(*args, **kwargs):
        metrics = args[3]
        metrics["owned_create_time"] = 1.0
        yield SimpleNamespace(process=object(), url="http://127.0.0.1:1234", token="t" * 40)
        metrics["within_budget"] = True
    class Adapter:
        def __init__(self, *args, **kwargs):
            self.counts = {}
        def begin_request(self, deadline):
            pass
        def load(self):
            if fault == "body-close":
                raise probe.CandidateFailure("original_body")
        def close(self):
            calls.append("close")
            if fault == "body-close":
                raise probe.CandidateFailure("secondary_close")
    monkeypatch.setattr(probe, "launch", launcher)
    monkeypatch.setattr(probe, "CandidateAdapter", Adapter)
    monkeypatch.setattr(probe, "ResourceGuard", lambda *a, **k: SimpleNamespace(check=lambda: None))
    monkeypatch.setattr(gpu, "gpu_checkpoint", lambda **k: {"uuid": "GPU-synthetic", "query_stopped": True, "error": None})
    monkeypatch.setattr(probe, "diagnose", lambda *a, **k: {"status": "completed", "operational_complete": True,
                        "mechanically_complete": True, "first_failure": None, "stop_reason": None})
    original_seal = probe.Evidence.seal
    def late_seal(self, report):
        original_seal(self, report)
        clock.now = 1026
    if fault == "late-seal":
        monkeypatch.setattr(probe.Evidence, "seal", late_seal)
    result = probe.execute(path, digest, root=tmp_path, clock=clock)
    output = tmp_path / ".local/run" / probe.ID
    assert not result["mechanically_complete"] and calls == ["close"]
    terminal = json.loads((output / "terminal.json").read_text(encoding="utf-8"))
    assert not terminal["mechanically_complete"]
    if fault == "body-close":
        assert result["first_failure"]["code"] == "local_candidate_original_body"
        assert result["secondary_failures"][0]["code"] == "local_candidate_secondary_close"
    else:
        assert (output / "late-invalidation.json").is_file()
        assert terminal["elapsed_seconds_after_report_write"] > 1025


def test_startup_ram_gate_precedes_process_creation(monkeypatch, tmp_path):
    import psutil
    @contextmanager
    def lease(path):
        yield
    monkeypatch.setattr(probe, "worker_lease", lease)
    spec, registration, seal = registration_fixture(tmp_path, monkeypatch)
    prepared = probe.verify_registration(registration, seal(), tmp_path)[3]
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(available=10 * 1024**3 - 1))
    monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **k: pytest.fail("RAM gate must precede Popen"))
    with pytest.raises(probe.CandidateFailure, match="startup_ram"):  # noqa: SIM117
        with probe.launch(tmp_path / probe.PROFILE, tmp_path / spec["model_root"], 120, {},
                          prepared=prepared, root=tmp_path, clock=lambda: 0):
            pytest.fail("must not yield")



def test_load_artifact_verification_cannot_reset_startup_deadline(monkeypatch, tmp_path):
    clock = Clock()
    path = tmp_path / "profile.json"
    path.write_bytes(b"synthetic profile identity")
    monkeypatch.setattr(probe, "PROFILE_SHA", probe.sha(path.read_bytes()))
    def fake_load(self):
        self._alias = probe.MODEL_SHA
        self._metadata = {"runtime": {"context_tokens": 6144}}
        clock.now = 121
        return self
    monkeypatch.setattr(probe.GGUFGenerator, "load", fake_load)
    adapter = probe.CandidateAdapter("http://127.0.0.1:54321", "t" * 40, path,
                                     clock=clock, transport=httpx.MockTransport(lambda request: pytest.fail("no HTTP")))
    adapter.begin_request(120)
    with pytest.raises(probe.CandidateFailure, match="deadline"):
        adapter.load()
    adapter.close()



@pytest.mark.parametrize("stage, malformed", [
    ("summary", "not JSON"),
    ("review", '{"claims":[],"coverage":NaN}'),
    ("qa", '{"status":"answered","status":"abstained","claims":[]}'),
])
def test_lc_r1_model_json_rejection_continues_fixed_schedule(tmp_path, stage, malformed):
    fired = []
    def alter(adapter, path, _payload, response, _clock):
        if path == "/completion" and adapter.stage == stage and not fired:
            fired.append(True)
            response["content"] = malformed
    adapter, _requests, observed, clock = adapter_fixture(tmp_path, alter=alter)
    report = probe.diagnose(documents(), adapter, active_deadline=900, clock=clock, emit=lambda *x: None)
    adapter.close()
    rejected = report["documents"][0][stage]
    assert rejected["status"] == "rejected" and rejected["error"]["code"] == "generation_invalid_json"
    assert report["operational_complete"] and not report["mechanically_complete"]
    assert report["stop_reason"] is None and not adapter.halted
    assert report["documents"][-1]["qa"]["status"] == "valid"
    assert report["counts"]["summary"] == report["counts"]["qa"] == 4
    assert report["counts"]["review"] == (3 if stage == "summary" else 4)
    assert report["counts"]["requested_tokens"] == (4480 if stage == "summary" else 4608)
    assert sum(1 for kind, value in observed if kind == "response" and value["path"] == "/completion"
               and value["body"]["content"] == malformed) == 1


def test_lc_r1_native_envelope_json_error_stops_without_later_dispatch(tmp_path):
    def alter(_adapter, path, _payload, _response, _clock):
        if path == "/completion":
            return httpx.Response(200, content=b'{broken native JSON', headers={"content-type": "application/json"})
        return None
    adapter, requests, _observed, clock = adapter_fixture(tmp_path, alter=alter)
    report = probe.diagnose(documents(), adapter, active_deadline=900, clock=clock, emit=lambda *x: None)
    count = len(requests)
    with pytest.raises(probe.CandidateFailure, match="halted"):
        adapter.complete("another", "qa", [], 900)
    adapter.close()
    assert len(requests) == count and sum(path == "/completion" for path, _ in requests) == 1
    assert report["stop_reason"]["code"] == "generation_backend_protocol" and adapter.halted
    assert not report["operational_complete"]
    assert report["documents"][0]["qa"]["status"] == "unexecuted"
    assert all(row["summary"]["status"] == "unexecuted" for row in report["documents"][1:])


@pytest.mark.parametrize("fault", ["manifest", "model", "runtime_digest", "server", "license", "archive", "extra", "missing", "reparse"])
def test_startup_checked_asset_relationships_before_popen(tmp_path, monkeypatch, fault):
    from scripts import prepare_meeting_gguf as setup
    spec, path, seal = registration_fixture(tmp_path, monkeypatch)
    model_root = tmp_path / spec["model_root"]
    receipt_path = model_root / "setup-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if fault == "manifest":
        receipt["manifest_sha256"] = "0" * 64
    elif fault == "model":
        receipt["model"]["sha256"] = "0" * 64
    elif fault == "runtime_digest":
        receipt["runtime_files"]["llama-server.exe"]["sha256"] = "0" * 64
    elif fault == "server":
        receipt["server_path"] = "downloads/runtime.zip"
    elif fault == "license":
        receipt["licenses"]["licenses/license.txt"]["sha256"] = "0" * 64
    elif fault == "archive":
        archive = model_root / "downloads/runtime.zip"
        archive.write_bytes(b"different registered archive")
        for reference in spec["assets"]:
            if reference["file"].endswith("runtime.zip"):
                reference.update(size_bytes=archive.stat().st_size, sha256=probe.sha(archive.read_bytes()))
    elif fault == "extra":
        (model_root / "runtime/extra.dll").write_bytes(b"extra")
    elif fault == "missing":
        (model_root / "runtime/llama-server.exe").unlink()
    else:
        # Simulate Windows junction metadata even where creating symlinks requires privileges.
        directory = model_root / "runtime/junction"
        directory.mkdir()
        monkeypatch.setattr(probe, "linked", lambda p: Path(p) == directory, raising=False)
    receipt_path.write_bytes(probe.encoded(receipt))
    for reference in spec["assets"]:
        if reference["file"].endswith("setup-receipt.json"):
            reference.update(size_bytes=receipt_path.stat().st_size, sha256=probe.sha(receipt_path.read_bytes()))
    monkeypatch.setattr(setup, "prepare", lambda *a, **k: pytest.fail("no preparation"))
    monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **k: pytest.fail("no native launch"))
    with pytest.raises((probe.CandidateFailure, ValueError)):
        probe.verify_registration(path, seal(), tmp_path)


@pytest.mark.parametrize("available", [10 * 1024**3 - 1, 10 * 1024**3])
def test_startup_no_prepare_single_ram_sample_and_exact_checked_paths(tmp_path, monkeypatch, available):
    import psutil

    from scripts import prepare_meeting_gguf as setup
    spec, path, seal = registration_fixture(tmp_path, monkeypatch)
    result = probe.verify_registration(path, seal(), tmp_path)
    extra = {"prepared": result[3]} if len(result) == 4 else {}
    calls, metrics = [], {}
    @contextmanager
    def lease(path):
        yield
    def sample():
        calls.append("ram")
        return SimpleNamespace(available=available)
    def forbidden(*a, **k):
        pytest.fail("launch must not prepare, extract, download, or rehash")
    def popen(argv, **kwargs):
        calls.append("Popen")
        assert Path(argv[0]) == tmp_path / spec["model_root"] / "runtime/llama-server.exe"
        assert Path(argv[argv.index("--model") + 1]) == tmp_path / spec["model_root"] / "model.gguf"
        raise ValueError("synthetic Popen sentinel")
    for name in ("prepare", "extract_runtime", "download"):
        monkeypatch.setattr(setup, name, forbidden)
    monkeypatch.setattr(probe, "prepare", forbidden, raising=False)
    monkeypatch.setattr(probe, "check_ref", forbidden)
    monkeypatch.setattr(probe, "worker_lease", lease)
    monkeypatch.setattr(psutil, "virtual_memory", sample)
    monkeypatch.setattr(probe, "unused_port", lambda: 1234)
    monkeypatch.setattr(probe.subprocess, "Popen", popen)
    monkeypatch.setattr(probe, "cleanup_owner", lambda *a, **k: None)
    expected = probe.CandidateFailure if available < 10 * 1024**3 else ValueError
    with pytest.raises(expected):  # noqa: SIM117
        with probe.launch(tmp_path / probe.PROFILE, tmp_path / spec["model_root"], 120,
                          metrics, root=tmp_path, clock=lambda: 7, **extra):
            pytest.fail("must not yield")
    assert calls == (["ram"] if available < 10 * 1024**3 else ["ram", "Popen"])
    assert metrics["startup_ram_gate"] == {"stage": "before_native_popen", "available_bytes": available,
        "minimum_bytes": 10 * 1024**3, "passed": available >= 10 * 1024**3, "elapsed_seconds": 7}



def test_startup_low_ram_survives_report_terminal_and_cleanup_path(tmp_path, monkeypatch):
    import psutil
    spec, registration, seal = registration_fixture(tmp_path, monkeypatch)
    samples = []
    def sample():
        samples.append(True)
        return SimpleNamespace(available=10 * 1024**3 - 1)
    monkeypatch.setattr(psutil, "virtual_memory", sample)
    monkeypatch.setattr(probe, "unused_port", lambda: 1234)
    monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **k: pytest.fail("low RAM cannot start"))
    result = probe.execute(registration, seal(), root=tmp_path, clock=lambda: 0)
    output = tmp_path / spec["output_dir"]
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    terminal = json.loads((output / "terminal.json").read_text(encoding="utf-8"))
    assert samples == [True]
    assert result["first_failure"]["code"] == "local_candidate_startup_ram"
    assert terminal["startup_ram_gate"] == report["cleanup"]["startup_ram_gate"]
    assert terminal["startup_ram_gate"]["available_bytes"] == 10 * 1024**3 - 1
    assert not terminal["startup_ram_gate"]["passed"]
    assert not report["cleanup"].get("process_creation_attempted")
    assert report["bindings_unchanged"] and all(row["qa"]["status"] == "unexecuted" for row in report["documents"])


@pytest.mark.parametrize("fault", ["extra", "missing", "reparse"])
def test_startup_rechecks_runtime_names_after_verification(tmp_path, monkeypatch, fault):
    spec, path, seal = registration_fixture(tmp_path, monkeypatch)
    prepared = probe.verify_registration(path, seal(), tmp_path)[3]
    runtime = prepared.model_root / "runtime"
    if fault == "extra":
        (runtime / "extra.dll").write_bytes(b"extra")
    elif fault == "missing":
        prepared.server.unlink()
    else:
        child = runtime / "junction"
        child.mkdir()
        monkeypatch.setattr(probe, "linked", lambda p: p == child)
    monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **k: pytest.fail("changed runtime cannot start"))
    with pytest.raises(probe.CandidateFailure):  # noqa: SIM117
        with probe.launch(tmp_path / probe.PROFILE, tmp_path / spec["model_root"], 120, {},
                          prepared=prepared, root=tmp_path, clock=lambda: 0):
            pytest.fail("must not yield")
