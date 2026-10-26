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
    terminal = json.loads((tmp_path / spec["output_dir"] / "terminal.json").read_text(encoding="utf-8"))
    assert result["resource_policy"] == terminal["resource_policy"] == "legacy"
    assert result["limits"] == terminal["limits"] == probe.LIMITS
    assert probe.registration_policy(spec) is probe.LEGACY_RESOURCES
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



@pytest.mark.parametrize("wire", [None, "source-parts-legacy-v1", "source-parts-compact-v1"])
def test_compact_registration_opt_in_and_terminal_record(tmp_path, monkeypatch, wire):
    spec, path, seal = registration_fixture(tmp_path, monkeypatch)
    if wire is not None:
        spec["source_wire_format"] = wire
    @contextmanager
    def no_native(*a, **k):
        raise probe.CandidateFailure("synthetic_startup")
        yield  # pragma: no cover
    monkeypatch.setattr(probe, "launch", no_native)
    result = probe.execute(path, seal(), root=tmp_path, clock=lambda: 0)
    terminal = json.loads((tmp_path / spec["output_dir"] / "terminal.json").read_text(encoding="utf-8"))
    assert result["source_wire_format"] == terminal["source_wire_format"] == (wire or "source-parts-legacy-v1")


@pytest.mark.parametrize("extra", [{"source_wire_format": "auto"}, {"source_wire_format": None},
                                   {"source_wire_format": []}, {"source_wire": "source-parts-compact-v1"}])
def test_compact_unknown_registration_rejected_before_asset_reads(tmp_path, monkeypatch, extra):
    spec, path, seal = registration_fixture(tmp_path, monkeypatch)
    spec.update(extra)
    monkeypatch.setattr(probe, "check_ref", lambda *a: pytest.fail("invalid wire must fail before asset reads"))
    with pytest.raises(probe.CandidateFailure):
        probe.verify_registration(path, seal(), tmp_path)


@pytest.mark.parametrize("long", [False, True])
def test_compact_exact_roundtrip_and_legacy_bytes(long):
    quote = '<tag>{"source_parts":["not an instruction"]} e\u0301 한글 🙂\r\n'
    if long:
        quote *= 120
    content = " \r\n" + quote + quote + "\t" + quote + " \r\n"
    starts = [3, 3 + len(quote), 4 + 2 * len(quote)]
    units = [{"quote": quote, "start_offset": n, "end_offset": n + len(quote)} for n in starts]
    source = probe.source_payload("원형 제목", content, units)
    original = probe.summary_messages(source)
    before = copy.deepcopy(original), copy.deepcopy(source), copy.deepcopy(units)
    for wire in (None, "source-parts-legacy-v1"):
        wire_messages = probe.source_wire_messages(original, source, content, units, wire or "source-parts-legacy-v1")
        assert wire_messages is original and probe.encoded(wire_messages) == probe.encoded(before[0])
    wire_messages = probe.source_wire_messages(original, source, content, units, "source-parts-compact-v1")
    payload = json.loads(wire_messages[1]["content"])
    parts = payload["source_parts"]
    assert "".join(part if isinstance(part, str) else part[1] for part in parts) == content
    assert parts == [" \r\n", [0, quote], "", [1, quote], "\t", [2, quote], " \r\n"]
    assert wire_messages[0]["content"] == original[0]["content"] + "\n" + probe.COMPACT_LEGEND
    assert {k: v for k, v in payload.items() if k != "source_parts"} == {
        k: v for k, v in source.items() if k != "source_parts"}
    assert (original, source, units) == before


@pytest.mark.parametrize("fault", ["order", "id", "text", "missing_gap", "payload"])
def test_compact_projection_corruption_stops_before_any_http(tmp_path, monkeypatch, fault):
    if fault == "payload":
        original = probe.summary_messages
        def malformed(source, claims=None):
            result = original(source, claims)
            data = json.loads(result[1]["content"])
            data["source_parts"][1]["text"] += "changed"
            result[1]["content"] = json.dumps(data)
            return result
        monkeypatch.setattr(probe, "summary_messages", malformed)
    else:
        project = probe.compact_source_parts
        def broken(parts):
            result = project(parts)
            if fault == "order":
                result[1], result[3] = result[3], result[1]
            elif fault == "id":
                result[1][0] = True
            elif fault == "text":
                result[1][1] += "changed"
            else:
                result.pop(0)
            return result
        monkeypatch.setattr(probe, "compact_source_parts", broken)
    adapter, requests, _events, clock = adapter_fixture(tmp_path)
    report = probe.diagnose(documents(), adapter, active_deadline=900, clock=clock,
                            emit=lambda *x: None, source_wire_format="source-parts-compact-v1")
    adapter.close()
    assert requests == [] and report["stop_reason"]["code"] == "local_candidate_source_wire_integrity"
    assert not report["operational_complete"] and adapter.halted
    assert all(row["qa"]["status"] == "unexecuted" for row in report["documents"])


def test_compact_shared_summary_review_qa_boundary_preserves_claim_links(tmp_path):
    docs = documents()
    # Repeat an identical unit at a distinct offset; the review must retain ID 1.
    for doc in docs:
        doc["content"] = "결정: 변경을 승인했다.\n결정: 변경을 승인했다.\n"
        doc["content_sha256"] = probe.sha(doc["content"].encode())
    captures = {}
    for wire in ("source-parts-legacy-v1", "source-parts-compact-v1"):
        adapter, requests, _events, clock = adapter_fixture(tmp_path)
        report = probe.diagnose(docs, adapter, active_deadline=900, clock=clock,
                                emit=lambda *x: None, source_wire_format=wire)
        adapter.close()
        assert report["mechanically_complete"] and report["counts"]["requested_tokens"] == 4608
        assert report["source_wire_format"] == wire
        captures[wire] = [body["messages"] for path, body in requests if path == "/apply-template"]
    legacy, compact = captures.values()
    for index, (before, after) in enumerate(zip(legacy, compact, strict=True)):
        old_payload, new_payload = json.loads(before[1]["content"]), json.loads(after[1]["content"])
        assert {k:v for k,v in old_payload.items() if k != "source_parts"} == {
            k:v for k,v in new_payload.items() if k != "source_parts"}
        assert after[0]["content"] == before[0]["content"] + "\n" + probe.COMPACT_LEGEND
        assert "".join(p if isinstance(p, str) else p[1] for p in new_payload["source_parts"]) == docs[index // 3]["content"]
        if index % 3 == 1:
            assert new_payload["candidate_claims"][0]["evidence"] == [1]
        elif index % 3 == 2:
            assert new_payload["question"] == docs[index // 3]["question"]["text"]


@pytest.mark.parametrize("evidence", [[1, 1], [999], [True], ["1"]])
@pytest.mark.parametrize("stage", ["summary", "qa"])
def test_compact_keeps_existing_evidence_rejections(tmp_path, evidence, stage):
    def alter(adapter, path, _payload, response, _clock):
        if path == "/completion" and adapter.stage == stage:
            data = json.loads(response["content"])
            data["claims"][0]["evidence"] = evidence
            response["content"] = json.dumps(data, ensure_ascii=False)
    adapter, _requests, _events, clock = adapter_fixture(tmp_path, alter=alter)
    result = probe.diagnose(documents(), adapter, active_deadline=900, clock=clock,
                            emit=lambda *x: None, source_wire_format="source-parts-compact-v1")
    adapter.close()
    assert all(row[stage]["status"] == "rejected" for row in result["documents"])
    assert result["operational_complete"] and not result["mechanically_complete"]


def test_compact_mandatory_review_still_checks_4096_and_cannot_pass(tmp_path):
    def alter(adapter, path, _payload, response, _clock):
        if path == "/tokenize" and adapter.stage == "review":
            response["tokens"] = list(range(4097))
    adapter, requests, _events, clock = adapter_fixture(tmp_path, alter=alter)
    result = probe.diagnose(documents(), adapter, active_deadline=900, clock=clock,
                            emit=lambda *x: None, source_wire_format="source-parts-compact-v1")
    adapter.close()
    assert result["counts"]["summary"] == result["counts"]["qa"] == 4
    assert result["counts"]["review"] == 0 and result["counts"]["requested_tokens"] == 4096
    assert all(row["review"]["status"] == "rejected" for row in result["documents"])
    assert not result["mechanically_complete"]
    assert sum(path == "/completion" for path, _ in requests) == 8


def rss6_registration(spec):
    spec.update(schema_version=2, resource_policy="native-rss6-host2-v1",
                limits={**probe.LIMITS, "native_rss_bytes": 6 * 1024**3,
                        "startup_available_bytes": 8 * 1024**3})
    return spec


def test_resource_policy_schema2_is_explicit_and_immutable(tmp_path, monkeypatch):
    spec, path, seal = registration_fixture(tmp_path, monkeypatch)
    rss6_registration(spec)
    verified = probe.verify_registration(path, seal(), tmp_path)[0]
    policy = probe.registration_policy(verified)
    assert policy.name == "native-rss6-host2-v1"
    assert policy.limits["startup_available_bytes"] == 8 * 1024**3
    assert policy.limits["native_rss_bytes"] == 6 * 1024**3
    assert policy.limits["active_available_bytes"] == 2 * 1024**3
    with pytest.raises(TypeError):
        policy.limits["native_rss_bytes"] = 99
    assert probe.LIMITS["native_rss_bytes"] == 8 * 1024**3


@pytest.mark.parametrize("fault", ["schema", "bool-schema", "missing-policy", "unknown-policy", "legacy-policy",
                                   "old-limits", "host", "tokens", "extra", "extra-limit"])
def test_resource_policy_rejects_mismatch_before_bound_reads(tmp_path, monkeypatch, fault):
    spec, path, seal = registration_fixture(tmp_path, monkeypatch)
    rss6_registration(spec)
    if fault == "schema":
        spec["schema_version"] = 3
    elif fault == "bool-schema":
        spec["schema_version"] = True
    elif fault == "missing-policy":
        del spec["resource_policy"]
    elif fault == "unknown-policy":
        spec["resource_policy"] = "native-rss7-host2-v1"
    elif fault == "legacy-policy":
        spec["schema_version"] = 1
    elif fault == "old-limits":
        spec["limits"] = dict(probe.LIMITS)
    elif fault == "host":
        spec["limits"]["active_available_bytes"] -= 1
    elif fault == "tokens":
        spec["limits"]["summary_tokens"] -= 1
    elif fault == "extra":
        spec["override"] = True
    else:
        spec["limits"]["arbitrary"] = 1
    monkeypatch.setattr(probe, "check_ref", lambda *a: pytest.fail("invalid policy must precede asset reads"))
    with pytest.raises(probe.CandidateFailure, match="registration_contract"):
        probe.verify_registration(path, seal(), tmp_path)


class PolicyPS:
    def __init__(self):
        self.created, self.rss, self.available = 1.0, 1, 10 * 1024**3
        self.rss_reads, self.ram_reads, self.access_error = 0, 0, False
    def Process(self, pid):
        if self.access_error:
            raise PermissionError("synthetic")
        def memory():
            self.rss_reads += 1
            return SimpleNamespace(rss=self.rss)
        return SimpleNamespace(create_time=lambda: self.created, memory_info=memory)
    def virtual_memory(self):
        self.ram_reads += 1
        return SimpleNamespace(available=self.available)


def policy_process():
    process = SimpleNamespace(pid=123, returncode=None, kills=[])
    process.poll = lambda: process.returncode
    def kill():
        process.kills.append(123)
        process.returncode = -1
    process.kill = kill
    return process


@pytest.mark.parametrize("policy", [probe.LEGACY_RESOURCES, probe.RSS6_RESOURCES])
def test_resource_policy_rss_and_host_boundaries_share_one_sample(policy):
    from scripts import probe_meeting_summary_mode as frozen
    before = dict(frozen.LIMITS)
    for field, threshold in (("rss", policy.limits["native_rss_bytes"]),
                             ("available", policy.limits["active_available_bytes"])):
        for delta in (-1, 0, 1):
            ps, process = PolicyPS(), policy_process()
            setattr(ps, field, threshold + delta)
            guard = probe.make_resource_guard(process, policy, ps=ps, clock=lambda: 7, expected_created=1)
            fails = delta > 0 if field == "rss" else delta < 0
            if fails:
                with pytest.raises(ValueError, match="summary_mode_resources"):
                    guard.check()
                ps.rss, ps.available = 1, 10 * 1024**3
                with pytest.raises(ValueError, match="summary_mode_resources"):
                    guard.check()
                assert guard.failure == "resources"
            else:
                row = guard.check()
                assert row == {"at": 7, "rss": ps.rss, "available": ps.available}
            assert ps.rss_reads == ps.ram_reads == 1
    assert frozen.LIMITS == before and probe.LIMITS["native_rss_bytes"] == 8 * 1024**3
    if policy is probe.LEGACY_RESOURCES:
        assert type(guard) is probe.ResourceGuard


@pytest.mark.parametrize("fault", ["initial-identity", "reused", "access", "exited"])
def test_resource_policy_ownership_never_kills_uncertain_identity(fault):
    ps, process = PolicyPS(), policy_process()
    if fault == "initial-identity":
        with pytest.raises(ValueError, match="ownership"):
            probe.make_resource_guard(process, probe.RSS6_RESOURCES, ps=ps, expected_created=2)
    else:
        guard = probe.make_resource_guard(process, probe.RSS6_RESOURCES, ps=ps, expected_created=1)
        if fault == "reused":
            ps.created = 2
        elif fault == "access":
            ps.access_error = True
        else:
            process.returncode = 0
        with pytest.raises(ValueError, match="ownership"):
            guard.check()
        guard.stop_owned()
        assert guard.failure == "ownership"
    assert process.kills == [] and ps.rss_reads == ps.ram_reads == 0


def test_resource_policy_inherited_arm_latches_resources_and_blocks_http(tmp_path, monkeypatch):
    from scripts import probe_meeting_summary_mode as frozen
    ps, process = PolicyPS(), policy_process()
    ps.rss = 6 * 1024**3 + 1
    guard = probe.make_resource_guard(process, probe.RSS6_RESOURCES, ps=ps, clock=lambda: 0, expected_created=1)
    class InlineThread:
        def __init__(self, *, target, **kwargs):
            self.target = target
        def start(self):
            self.target()
        def join(self, **kwargs):
            pass
        def is_alive(self):
            return False
    monkeypatch.setattr(frozen.threading, "Thread", InlineThread)
    adapter, requests, _, _ = adapter_fixture(tmp_path)
    adapter.resource_check = guard.check
    adapter.begin_request(120)
    metrics = {}
    with pytest.raises(ValueError, match="summary_mode_resources"):  # noqa: SIM117
        with guard.arm(120, metrics):
            adapter._request("POST", "/completion", {"n_predict": 768}, 120)
    assert guard.failure == "resources" and process.kills == [123]
    assert adapter.halted and requests == [] and adapter.counts["summary"] == 0
    assert metrics["joined"] and metrics["samples"] == []
    adapter.close()


@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_resource_policy_startup_external_interpretation_matches_single_internal_sample(tmp_path, monkeypatch, delta):
    import psutil
    spec, path, seal = registration_fixture(tmp_path, monkeypatch)
    rss6_registration(spec)
    # Pure interpretation has no resource sampling or asset access; future observers use this limit.
    policy = probe.registration_policy(spec)
    available = policy.limits["startup_available_bytes"] + delta
    calls = []
    def sample():
        calls.append("ram")
        return SimpleNamespace(available=available)
    def popen(*args, **kwargs):
        calls.append("Popen")
        raise ValueError("synthetic Popen sentinel")
    monkeypatch.setattr(psutil, "virtual_memory", sample)
    monkeypatch.setattr(probe, "unused_port", lambda: 1234)
    monkeypatch.setattr(probe.subprocess, "Popen", popen)
    result = probe.execute(path, seal(), root=tmp_path, clock=lambda: 0)
    output = tmp_path / spec["output_dir"]
    terminal = json.loads((output / "terminal.json").read_text(encoding="utf-8"))
    assert calls == (["ram"] if delta < 0 else ["ram", "Popen"])
    gate = result["cleanup"]["startup_ram_gate"]
    assert gate == terminal["startup_ram_gate"]
    assert gate["available_bytes"] == available and gate["minimum_bytes"] == 8 * 1024**3
    assert gate["passed"] is (delta >= 0)
    assert result["resource_policy"] == terminal["resource_policy"] == policy.name
    assert result["limits"] == terminal["limits"] == dict(policy.limits)
    assert result["cleanup"]["effective_limits"] == dict(policy.limits)
    if delta < 0:
        assert result["first_failure"]["code"] == "local_candidate_startup_ram"
        assert not result["cleanup"].get("process_creation_attempted")


@pytest.mark.parametrize("fail_after_completion", [False, True])
def test_resource_policy_two_guards_http_callback_cleanup_and_no_later_completion(tmp_path, monkeypatch, fail_after_completion):
    import psutil

    from scripts import probe_meeting_gpu_placement as gpu
    spec, path, seal = registration_fixture(tmp_path, monkeypatch)
    rss6_registration(spec)
    ps, process = PolicyPS(), policy_process()
    process.stdout = object()
    guards, cleaned = [], []
    original_factory = probe.make_resource_guard
    def factory(p, policy, **kwargs):
        assert p is process and policy is probe.RSS6_RESOURCES
        guard = original_factory(p, policy, ps=ps, **kwargs)
        guards.append(guard)
        return guard
    @contextmanager
    def arm(self, deadline, metrics):
        self.check()
        try:
            yield
            self.check()
        finally:
            metrics.update(joined=True, samples=[], sample_cap=721)
    monkeypatch.setattr(probe.ResourceGuard, "arm", arm)
    monkeypatch.setattr(probe, "make_resource_guard", factory)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(available=8 * 1024**3))
    monkeypatch.setattr(probe, "unused_port", lambda: 1234)
    monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(probe, "owned_create_time", lambda p: 1.0)
    monkeypatch.setattr(probe, "DiscardDrain", lambda stream: SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(probe, "wait_ready", lambda *a, **k: guards[0].check())
    def cleanup(p, drain, metrics, **kwargs):
        cleaned.append(p)
        metrics["within_budget"] = True
    monkeypatch.setattr(probe, "cleanup_owner", cleanup)
    monkeypatch.setattr(gpu, "gpu_checkpoint", lambda **k: {"uuid": "synthetic", "query_stopped": True})
    def alter(adapter, endpoint, payload, response, clock):
        if fail_after_completion and endpoint == "/completion":
            ps.rss = 6 * 1024**3 + 1
    adapter, requests, _, clock = adapter_fixture(tmp_path, alter=alter)
    def candidate(*args, **kwargs):
        adapter.resource_check = kwargs["resource_check"]
        assert adapter.resource_check.__self__ is guards[1]
        adapter.load = lambda: adapter.resource_check()
        return adapter
    monkeypatch.setattr(probe, "CandidateAdapter", candidate)
    result = probe.execute(path, seal(), root=tmp_path, clock=clock)
    assert len(guards) == 2 and all(type(g) is probe.CandidateResourceGuard for g in guards)
    assert cleaned == [process] and result["cleanup"]["within_budget"]
    completions = [r for r in requests if r[0] == "/completion"]
    assert len(completions) == (1 if fail_after_completion else 12)
    assert result["limits"] == dict(probe.RSS6_RESOURCES.limits)
    if fail_after_completion:
        assert result["stop_reason"]["code"] == "summary_mode_resources"
        assert adapter.halted and guards[1].failure == "resources"
        assert all(row["qa"]["status"] == "unexecuted" for row in result["documents"])
    else:
        assert result["mechanically_complete"]
