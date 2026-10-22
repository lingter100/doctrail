"""Synthetic contracts only: no accepted source, questions, models or browser launch."""
import json
import shutil
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_contract import AnalyzeRequest
from doctrail.meeting_service_rag import ObservedAnalysisGenerator, ServiceRuntime
from scripts import run_meeting_rag_acceptance as driver


def binding(path):
    data = path.read_bytes()
    return {"path": str(path.resolve()), "bytes": len(data), "sha256": driver.digest(data)}


def write(path, value):
    path.write_bytes(driver.canonical(value))
    return binding(path)


@pytest.fixture
def fixture(tmp_path):
    run = tmp_path / "run"
    code = [binding(driver.ROOT / name) for name in driver.CODE]
    roles = write(tmp_path / "roles.json", {
        "executor": {"role_id": "runner", "accepted": True, "phase": "calibration"},
        "final_judge": {"role_id": "judge", "accepted": True, "phase": "calibration",
                        "model": "registered-model", "exposure": "generic metadata only"},
        "excluded_final_judges": ["runner", "author", "implementer"]})
    source_freeze = write(tmp_path / "source-freeze.json", {"opaque": "accepted synthetic binding"})
    item_freeze = write(tmp_path / "item-freeze.json", {"opaque": "never follows oracle paths"})
    ci = write(tmp_path / "ci.json", {"commit": "a" * 40, "jobs": {
        "backend": "success", "java-service": "success", "web": "success"}, "code": code})
    families = [{"id": f"family{i}", "principal": f"actor{i}", "source_kind": kind}
                for i, kind in ((1, "public"), (2, "synthetic"))]
    sources = []
    for i in range(6):
        raw = tmp_path / f"synthetic{i}.md"
        raw.write_text(f"Synthetic source {i}.", encoding="utf-8")
        text = raw.read_text()
        sources.append({"source_id": f"s{i}", "family_id": f"family{i // 3 + 1}",
            "title": f"Synthetic {i}", "kind": "document" if i % 3 == 0 else "meeting",
            "visibility": "private" if i % 3 == 0 else "workspace",
            "revision": "synthetic-ref", "prepared_document_id": f"old{i}", "raw": binding(raw),
            "content_sha256": driver.digest(text.encode()),
            "chunks": [{"id": f"oldchunk{i}", "ordinal": 0, "page": None,
                        "start_offset": 0, "end_offset": len(text),
                        "sha256": driver.digest(text.encode())}]})
    questions = {"schema_version": 1, "phase": "calibration", "cases": [
        {"id": f"c{i}", "query": f"Synthetic query {i}?", "language": "en",
         "family_id": "family1" if i < 3 else "family2",
         "source_kind": "public" if i < 3 else "synthetic"} for i in range(6)]}
    jar = tmp_path / "fake.jar"; jar.write_bytes(b"synthetic jar")
    plan = {"questions": write(tmp_path / "questions.json", questions),
            "sources": sources, "families": families, "code": code, "jar": binding(jar),
            "ui": [{"url": "/", "sha256": "b" * 64}], "source_freeze": source_freeze,
            "item_freeze": item_freeze, "ci": ci, "roles": roles, "gate": None}
    registration = {"schema_version": 1, "phase": "calibration", "run_dir": str(run),
        "plan_sha256": driver.digest(driver.canonical(plan)), "commit": "a" * 40,
        "policy": {"startup_seconds": 120, "active_seconds": 1500, "cleanup_seconds": 5,
                   "answer_seconds": 90, "analyze_seconds": 120, "method": "hybrid_rerank",
                   "profile": "base", "limit": 5, "gpu_layers": 28},
        "accepted_bindings": {key: plan[key]["sha256"]
                              for key in ("source_freeze", "item_freeze", "ci", "roles")},
        "executor": "runner", "final_judge": "judge"}
    manifest = {"schema_version": 1, "phase": "calibration", "plan": plan,
                "registration": write(tmp_path / "registration.json", registration)}
    manifest_path = tmp_path / "manifest.json"
    write(manifest_path, manifest)
    return SimpleNamespace(run=run, manifest=manifest, path=manifest_path, questions=questions,
                           registration=registration, tmp=tmp_path)


def reregister(fixture):
    fixture.registration["plan_sha256"] = driver.digest(driver.canonical(fixture.manifest["plan"]))
    fixture.manifest["registration"] = write(fixture.tmp / "registration.json", fixture.registration)
    write(fixture.path, fixture.manifest)


def sink(fixture, clock=lambda: 100):
    fixture.run.mkdir(); (fixture.run / "raw").mkdir()
    evidence = driver.Evidence(fixture.run, fixture.questions, fixture.manifest["plan"]["sources"],
                               clock)
    evidence.deadline = 1600
    return evidence


def current(fixture, operation, key):
    (fixture.run / "current.json").write_text(json.dumps({"operation": operation, "id": key}))


def test_bound_registration_and_no_oracle_following(fixture):
    assert driver.verify_inputs(fixture.manifest, "calibration", fixture.run) == fixture.questions
    fixture.manifest["plan"]["item_freeze"]["sha256"] = "0" * 64
    with pytest.raises(driver.ExecutionError, match="registration_mismatch"):
        driver.verify_inputs(fixture.manifest, "calibration", fixture.run)


def test_validation_missing_gate_is_rejected_before_service(fixture):
    plan = fixture.manifest["plan"]
    fixture.manifest["phase"] = fixture.registration["phase"] = "validation"
    questions = fixture.questions
    questions["phase"] = "validation"
    for i in (6, 7):
        questions["cases"].append({**questions["cases"][3], "id": f"c{i}"})
    plan["questions"] = write(fixture.tmp / "questions.json", questions)
    roles = driver.read_json(plan["roles"]["path"])
    roles["executor"]["phase"] = roles["final_judge"]["phase"] = "validation"
    plan["roles"] = write(fixture.tmp / "roles.json", roles)
    fixture.registration["accepted_bindings"]["roles"] = plan["roles"]["sha256"]
    reregister(fixture)
    result = driver.execute(fixture.path, "validation", fixture.run,
        service_factory=lambda **kwargs: pytest.fail("validation must remain closed"))
    assert result["failure"] == "calibration_gate_missing"


@pytest.mark.parametrize("mutation", ["fixture", "gate", "judge", "ci", "source_path"])
def test_registration_rejects_unsafe_or_unaccepted_plan_before_factory(fixture, mutation):
    plan = fixture.manifest["plan"]
    if mutation == "fixture":
        plan["fixture"] = "fake"
    elif mutation == "gate":
        fixture.manifest["phase"] = "validation"
    elif mutation == "judge":
        roles = driver.read_json(plan["roles"]["path"])
        roles["final_judge"]["role_id"] = "implementer"
        plan["roles"] = write(fixture.tmp / "roles.json", roles)
        fixture.registration["accepted_bindings"]["roles"] = plan["roles"]["sha256"]
    elif mutation == "ci":
        ci = driver.read_json(plan["ci"]["path"]); ci["jobs"]["backend"] = "pending"
        plan["ci"] = write(fixture.tmp / "ci.json", ci)
        fixture.registration["accepted_bindings"]["ci"] = plan["ci"]["sha256"]
    else:
        plan["sources"][0]["source_id"] = "../escape"
    reregister(fixture)
    result = driver.execute(fixture.path, fixture.manifest["phase"], fixture.run,
        service_factory=lambda **kwargs: pytest.fail("must not start"))
    assert result["status"] == "failed"
    assert (fixture.run / "reservation.json").exists()
    assert not (fixture.run / "isolated.sqlite3").exists()


def test_native_answer_is_once_but_extraction_native_calls_are_separate(fixture):
    evidence = sink(fixture)
    current(fixture, "analyze", "s1")
    evidence("analyze", "started", {"content": "Synthetic source 1."})
    for _ in range(3):
        evidence("analyze", "transport_started", {"path": "/completion"})
    current(fixture, "answer", "c0")
    evidence("answer", "started", {"request": {"query": "Synthetic query 0?", "contexts": []},
                                  "budget_ms": 400})
    evidence("answer", "native_post_started", True)
    with pytest.raises(driver.ExecutionError, match="duplicate_native_answer"):
        evidence("answer", "native_post_started", True)
    assert evidence.native == {("analyze", "s1"): 3, ("answer", "c0"): 1}
    assert evidence.failure == "duplicate_native_answer"


def test_raw_sink_first_storage_failure_survives_generic_followup(fixture, monkeypatch):
    evidence = sink(fixture)
    current(fixture, "answer", "c0")
    monkeypatch.setattr(driver, "save", lambda *a: (_ for _ in ()).throw(OSError("private text")))
    with pytest.raises(driver.ExecutionError, match="evidence_write_failed"):
        evidence("answer", "started", {"request": {"query": "Synthetic query 0?"}, "budget_ms": 1})
    with pytest.raises(driver.ExecutionError, match="evidence_write_failed"):
        evidence("answer", "error", {"code": "generation_failed"})
    assert evidence.failure == "evidence_write_failed"
    assert evidence.native == {}


def test_wrong_actor_marker_and_expiry_fail_before_transport(fixture):
    evidence = sink(fixture)
    current(fixture, "analyze", "s1")
    with pytest.raises(driver.ExecutionError, match="observer_operation"):
        evidence("answer", "started", {})
    assert evidence.starts == {} and evidence.native == {}


class FakeRun:
    def __init__(self, fixture, *, delay=0, browser_survives=False, changed=False,
                 prior_browser=0):
        self.f = fixture
        self.now = 100
        self.delay, self.browser_survives, self.changed = delay, browser_survives, changed
        self.prior_browser = prior_browser
        self.events = []

    @contextmanager
    def service(self, **kwargs):
        self.metrics = kwargs["metrics"]; self.evidence = kwargs["observer"]
        self.now += self.delay
        self.handle = SimpleNamespace(java_url="http://127.0.0.1:1234",
            java=SimpleNamespace(pid=1, args=["fake-java"]),
            retrieval=SimpleNamespace(pid=2, args=["fake-retrieval"]),
            alive=lambda: None, shutdown=self.shutdown)
        try:
            yield self.handle
        finally:
            self.events.append("context_exit")

    def shutdown(self):
        self.events.append("service_shutdown")
        self.metrics["cleanup"] = {"accepted": True, "prior_native_cleanup_seconds": 0}
        return True

    def browser(self, config_path, folder):
        config = driver.read_json(config_path)
        assert config["base_url"] == self.handle.java_url
        fake = self
        class Child:
            process = SimpleNamespace(returncode=0)
            def poll(self):
                return 0
            def stop(self):
                fake.events.append("browser_stop")
            def cleanup_elapsed(self):
                return fake.prior_browser
            def closing(self):
                return False
            def finish(self, deadline, clock):
                fake.events.append("browser_finish")
                assert deadline == 105 - fake.prior_browser
                return not fake.browser_survives
        mapping = {}
        with sqlite3.connect(self.f.run / "isolated.sqlite3") as connection:
            connection.execute("CREATE TABLE documents(id TEXT,source BLOB)")
            for source in config["sources"]:
                key = source["source_id"]; document_id = "new-" + key
                raw = Path(source["raw"]["path"]).read_bytes()
                connection.execute("INSERT INTO documents VALUES(?,?)", (document_id, raw))
                mapping[key] = {"source_revision": source["revision"],
                                "document": {"id": document_id}}
                if source["kind"] == "meeting":
                    current(self.f, "analyze", key)
                    self.evidence("analyze", "started", {"content": raw.decode()})
                    self.evidence("analyze", "transport_started", {"path": "/completion"})
                    self.evidence("analyze", "transport_response", {"path": "/completion",
                                                                   "parsed_json": {"content": "5"}})
                    self.evidence("analyze", "result", {})
        cases = []
        for case in config["questions"]["cases"]:
            response = {"status": "abstained", "reason": "no_evidence", "claims": [],
                        "results": [], "model_called": False}
            cases.append({"id": case["id"], "response": response})
        driver.save(folder / "result.json", {"status": "completed", "analysis_count": 4,
            "answer_posts": 6, "cases": cases, "mapping": mapping, "document_sources": {}})
        if self.changed:
            Path(self.f.manifest["plan"]["sources"][0]["raw"]["path"]).write_text("changed")
        return Child()


def test_driver_actual_factory_default_and_complete_fake_phase_is_single_use(fixture):
    assert driver.execute.__kwdefaults__["service_factory"] is driver.start_services
    fake = FakeRun(fixture)
    result = driver.execute(fixture.path, "calibration", fixture.run,
        service_factory=fake.service, browser_factory=fake.browser, clock=lambda: fake.now)
    assert result["status"] == "mechanical_completed_judgment_pending"
    assert fake.events == ["browser_stop", "service_shutdown", "browser_finish", "context_exit"]
    packet = driver.read_json(fixture.run / "judge-answer-packet.json")
    assert len(packet["cases"]) == 6
    assert not any(word in json.dumps(packet) for word in ("model", "elapsed", "reasoning", "results"))
    with pytest.raises(FileExistsError):
        driver.execute(fixture.path, "calibration", fixture.run,
                       service_factory=lambda **k: pytest.fail("repeat"))


@pytest.mark.parametrize("mutation", [None, "context", "claim", "citation"])
def test_nonempty_context_worker_and_browser_correspondence(fixture, mutation):
    evidence = sink(fixture)
    for key in ("s1", "s2", "s4", "s5"):
        current(fixture, "analyze", key)
        evidence("analyze", "started", {"content": f"Synthetic source {key[1:]}."})
        evidence("analyze", "transport_started", {"path": "/completion"})
        evidence("analyze", "transport_response", {"path": "/completion", "parsed_json": {}})
        evidence("analyze", "result", {})
    context = {"document_id": "new", "revision": 1, "chunk_id": "chunk", "title": "Synthetic",
               "meeting_date": None, "page": None, "start_offset": 0, "end_offset": 4, "text": "Text"}
    citation = {"chunk_id": "chunk", "quote": "Text", "start_offset": 0, "end_offset": 4}
    worker = {"model": "private model name", "revision": "private model revision",
              "status": "answered", "reason": None,
              "claims": [{"text": "Synthetic answer.", "citations": [citation]}]}
    current(fixture, "answer", "c0")
    evidence("answer", "started", {"budget_ms": 80000, "request": {
        "query": "Synthetic query 0?", "contexts": [context]}})
    evidence("answer", "native_post_started", True)
    evidence("answer", "native_response", {"private_reasoning": "synthetic secret"})
    evidence("answer", "worker_response", worker)
    java = {**worker, "model_revision": worker["revision"], "results": [{**context}],
            "claims": [{"text": "Synthetic answer.", "citations": [{**context, **citation}]}]}
    browser = {"status": "completed", "analysis_count": 4, "answer_posts": 6,
        "document_sources": {"new": "s0"}, "mapping": {"s0": {"source_revision": "source-ref"}},
        "cases": [{"id": "c0", "response": java, "citations_opened": 1}] + [{
            "id": f"c{i}", "response": {"status": "abstained", "reason": "no_evidence",
                                       "claims": [], "results": []}} for i in range(1, 6)]}
    if mutation == "context":
        java["results"][0]["text"] = "Changed"
    if mutation == "claim":
        java["claims"][0]["text"] = "Changed"
    if mutation == "citation":
        browser["cases"][0]["citations_opened"] = 0
    if mutation:
        with pytest.raises(driver.ExecutionError):
            driver.reconcile(browser, evidence, fixture.questions)
    else:
        packet = driver.reconcile(browser, evidence, fixture.questions)
        assert packet["cases"][0]["claims"][0]["citations"][0]["source_id"] == "s0"
        assert "private" not in json.dumps(packet) and "results" not in json.dumps(packet)

@pytest.mark.parametrize("problem", ["startup", "browser_survives", "changed"])
def test_phase_failure_and_owned_cleanup_preserved(fixture, problem):
    fake = FakeRun(fixture, delay=121 if problem == "startup" else 0,
                   browser_survives=problem == "browser_survives", changed=problem == "changed")
    result = driver.execute(fixture.path, "calibration", fixture.run,
        service_factory=fake.service, browser_factory=fake.browser, clock=lambda: fake.now)
    assert result["status"] == "failed"
    assert "service_shutdown" in fake.events and fake.events[-1] == "context_exit"
    assert (fixture.run / "receipt.json").exists()


def test_browser_prior_cleanup_consumes_same_five_seconds(fixture):
    fake = FakeRun(fixture, prior_browser=3)
    result = driver.execute(fixture.path, "calibration", fixture.run,
        service_factory=fake.service, browser_factory=fake.browser, clock=lambda: fake.now)
    assert result["cleanup_seconds"] == 3 and result["cleanup_accepted"]


def test_failed_service_entry_preserves_already_spent_cleanup(fixture):
    @contextmanager
    def failed(**kwargs):
        kwargs["metrics"]["cleanup"] = {"accepted": False, "elapsed_seconds": 6}
        raise RuntimeError("private native startup failure")
        yield  # pragma: no cover
    result = driver.execute(fixture.path, "calibration", fixture.run,
                            service_factory=failed, clock=lambda: 100)
    assert result["cleanup_seconds"] == 6 and result["cleanup_accepted"] is False
    assert result["status"] == "failed"


def test_outer_startup_includes_binding_verification(fixture, monkeypatch):
    original = driver.verify_inputs
    now = [100]
    def slow(*args):
        value = original(*args)
        now[0] += 121
        return value
    monkeypatch.setattr(driver, "verify_inputs", slow)
    result = driver.execute(fixture.path, "calibration", fixture.run, clock=lambda: now[0],
                            service_factory=lambda **k: pytest.fail("expired before native"))
    assert result["failure"] == "startup_timeout"


def test_active_timeout_blocks_next_attempt_and_still_cleans(fixture):
    fake = FakeRun(fixture)
    def browser(config, folder):
        class Child:
            process = SimpleNamespace(returncode=None)
            def poll(self):
                fake.now += 1501
            def stop(self):
                fake.events.append("browser_stop")
            def cleanup_elapsed(self):
                return 0
            def finish(self, deadline, clock):
                return True
        return Child()
    result = driver.execute(fixture.path, "calibration", fixture.run,
        service_factory=fake.service, browser_factory=browser, clock=lambda: fake.now)
    assert result["failure"] == "active_timeout"
    assert driver.read_json(fixture.run / "case-states.json")[0]["status"] == "unexecuted"
    assert fake.events == ["browser_stop", "service_shutdown", "context_exit"]


def test_analysis_observer_consumes_original_deadline_before_any_native(monkeypatch):
    import doctrail.meeting_service_rag as module
    now = [100]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    metadata = {"repo_id": "model", "revision": "revision"}
    answer = SimpleNamespace(public_metadata=lambda: metadata)
    analysis = SimpleNamespace(public_metadata=lambda: metadata)
    calls = []
    def observer(operation, event, value):
        if event == "started":
            now[0] += 121
    runtime = ServiceRuntime(answer, analysis, cleanup=lambda: True, observer=observer)
    runtime.analysis.analyze = lambda r: calls.append("native")
    with pytest.raises(WorkerError, match="generation_deadline_exceeded"):
        runtime.analyze(AnalyzeRequest(schema_version=1, document_id="x", revision=1,
                                       title="Synthetic", content="Synthetic."))
    assert calls == []


def test_analysis_clamps_inner_deadline_and_does_not_mutate_payload(monkeypatch):
    import doctrail.meeting_service_rag as module
    now = [100]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    generator = ObservedAnalysisGenerator("http://127.0.0.1:1", "x" * 40, "unused",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"value": "original"})),
        observer=lambda op, event, value: value.update(parsed_json={})
        if event == "transport_response" else None)
    try:
        generator.service_deadline = 220
        now[0] = 200
        generator.begin_request(320)
        generator.observing = True
        assert generator._remaining(320) == 20
        assert generator._request("POST", "/tokenize", {}, 320) == {"value": "original"}
    finally:
        generator.close()


@pytest.mark.parametrize("http_status,archive_failure,available", [(503, False, False),
                                                                 (200, True, True)])
def test_parsed_body_availability_is_not_erased_by_archive_failure(http_status, archive_failure,
                                                                 available):
    events = []
    def observe(operation, event, value):
        if archive_failure and event == "transport_response":
            raise OSError("private storage error")
        events.append((event, value))
    generator = ObservedAnalysisGenerator("http://127.0.0.1:1", "x" * 40, "unused",
        observer=observe, transport=httpx.MockTransport(
            lambda r: httpx.Response(http_status, json={"complete": "synthetic payload"})))
    try:
        generator.observing = True
        with pytest.raises(GenerationError):
            generator._request("POST", "/tokenize", {})
        error = next(value for event, value in events if event == "transport_error")
        assert error["body_available"] is available
        assert error["parsed_json_available"] is available
        assert error["archive_failed"] is archive_failure
    finally:
        generator.close()


def test_browser_module_import_and_contracts_without_browser():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node not installed; real execution is not authorized by this skip")
    url = (driver.ROOT / driver.CODE[2]).as_uri()
    source = f"""
      import {{verifyDocument,verifyAnswerRequest,admitAnswer,verifySelected,sha}} from {json.dumps(url)};
      import assert from 'node:assert/strict';
      const text='Synthetic 😀 content.';
      const chunk={{id:'newchunk',ordinal:0,page:null,start_offset:0,end_offset:Array.from(text).length,text}};
      const doc={{id:'new',revision:1,status:'ready',visibility:'private',content:text,chunks:[chunk]}};
      const source={{prepared_document_id:'old',visibility:'private',content_sha256:sha(text),
        chunks:[{{...chunk,id:'oldchunk',sha256:sha(text)}}]}};
      verifyDocument(source,doc);
      assert.throws(()=>verifyDocument(source,{{...doc,id:'old'}}));
      const body={{query:'Synthetic?',workspace_id:'w',kind:'all',meeting_id:null,date_from:null,
        date_to:null,participant:null,assignee:null,item_type:null,method:'hybrid_rerank',
        limit:5,expected_embedding_profile:'base'}};
      verifyAnswerRequest(body,{{query:'Synthetic?'}},'w');
      const active={{operation:'answer',id:'a',sent:false}}, question={{id:'a',query:'Synthetic?'}};
      admitAnswer(active,body,question,'w');
      assert.throws(()=>admitAnswer(active,body,question,'w'));
      assert.throws(()=>verifyAnswerRequest({{...body,limit:4}},{{query:'Synthetic?'}},'w'));
      verifySelected({{status:'abstained',method:'hybrid_rerank',results:[],claims:[]}},[doc]);
      assert.throws(()=>verifySelected({{status:'answered',method:'hybrid_rerank',
        results:[{{document_id:'forbidden'}}],claims:[]}},[doc]));
    """
    result = subprocess.run([node, "--input-type=module", "-e", source], capture_output=True,
                            timeout=15, check=False)
    assert result.returncode == 0, result.stderr.decode()


def test_cli_has_no_fixture_endpoint_or_policy_override():
    with pytest.raises(SystemExit) as error:
        driver.main(["--phase", "calibration", "--manifest", "none", "--run-dir", "none",
                     "--fixture", "fake"])
    assert error.value.code == 2


@pytest.fixture
def owned_browser(tmp_path, monkeypatch):
    processes, killed = {}, []
    class Missing(Exception):
        pass
    class Timeout(Exception):
        pass
    class Process:
        def __init__(self, pid, created, parent=None):
            self.pid, self.created, self.parent = pid, created, parent
            self.live = True
            processes[pid] = self
        def create_time(self):
            return self.created
        def is_running(self):
            return self.live and processes.get(self.pid) is self
        def parents(self):
            return [self.parent] if self.parent and self.parent.is_running() else []
        def children(self, recursive=False):
            return [p for p in processes.values() if p.parent is self and p.is_running()]
        def kill(self):
            assert processes.get(self.pid) is self
            killed.append(self.pid); self.live = False
        def wait(self, timeout):
            if self.live:
                raise Timeout()
    node = Process(10, 100)
    chromium = Process(20, 101, node)
    grandchild = Process(30, 102, chromium)
    class Popen:
        pid, returncode = 10, None
        def poll(self):
            if not node.live:
                self.returncode = 1
            return self.returncode
        def wait(self, timeout):
            if node.live:
                raise subprocess.TimeoutExpired("owned-node", timeout)
            self.returncode = 1
            return self.returncode
        def kill(self):
            node.kill()
    popen = Popen()
    def lookup(pid):
        if pid not in processes or not processes[pid].live:
            raise Missing()
        return processes[pid]
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(
        Process=lookup, NoSuchProcess=Missing, TimeoutExpired=Timeout))
    monkeypatch.setattr(driver.shutil, "which", lambda name: "node-fake")
    monkeypatch.setattr(driver.subprocess, "Popen", lambda *a, **k: popen)
    folder = tmp_path / "browser"; folder.mkdir()
    driver.save(folder / "chromium.json", {"node_pid": 10, "pid": 20})
    child = driver.BrowserChild(tmp_path / "config.json", folder)
    return SimpleNamespace(child=child, node=node, chromium=chromium, grandchild=grandchild,
                           killed=killed, folder=folder, processes=processes, Process=Process,
                           Missing=Missing)


def test_browser_ownership_ack_precedes_ui_and_records_creation_time(owned_browser):
    rig = owned_browser
    assert rig.child.poll() is None
    ack = driver.read_json(rig.folder / "chromium-adopted.json")
    assert ack == {"node_pid": 10, "node_create_time": 100,
                   "chromium_pid": 20, "chromium_create_time": 101}


def test_node_early_exit_cannot_claim_unknown_chromium_clean(owned_browser):
    rig = owned_browser
    rig.node.live = False
    with pytest.raises(driver.ExecutionError, match="browser_owner_unconfirmed"):
        rig.child.poll()
    assert rig.child.finish(105, lambda: 100) is False
    assert not (rig.folder / "chromium-adopted.json").exists()


def test_adopted_descendants_are_cleaned_after_node_exits(owned_browser):
    rig = owned_browser
    rig.child.poll()
    rig.node.live = False
    assert rig.child.finish(105, lambda: 100) is False
    assert not rig.chromium.live and not rig.grandchild.live
    assert 20 in rig.killed and 30 in rig.killed


def test_browser_cleanup_does_not_kill_reused_pid(owned_browser):
    rig = owned_browser
    rig.child.poll()
    rig.node.live = False
    rig.chromium.live = False
    replacement = rig.Process(20, 999)
    assert rig.child.finish(105, lambda: 100) is False
    assert replacement.live and 20 not in rig.killed


def test_browser_config_uses_remaining_active_budget_and_stops_if_save_expires(fixture, monkeypatch):
    fake = FakeRun(fixture)
    original = driver.save
    def delayed(path, value):
        original(path, value)
        if path.name == "owned-services.json":
            fake.now += 12
        if path.name == "browser-config.json":
            assert value["active_budget_ms"] == 1488000
            fake.now += 1489
    monkeypatch.setattr(driver, "save", delayed)
    result = driver.execute(fixture.path, "calibration", fixture.run, service_factory=fake.service,
        browser_factory=lambda *a: pytest.fail("expired budget must not launch Node"),
        clock=lambda: fake.now)
    assert result["failure"] == "active_timeout"


def test_first_browser_failure_precedes_missing_result_error(fixture):
    fake = FakeRun(fixture)
    def browser(config, folder):
        driver.save(folder / "first-failure.json", {
            "code": "ui_binding_mismatch", "stage": "ui_verification",
            "id": None, "epoch_ms": 1000, "elapsed_ms": 3})
        return SimpleNamespace(process=SimpleNamespace(returncode=1), poll=lambda: 1,
            stop=lambda: None, cleanup_elapsed=lambda: 0, finish=lambda *a: True)
    result = driver.execute(fixture.path, "calibration", fixture.run,
        service_factory=fake.service, browser_factory=browser, clock=lambda: fake.now)
    assert result["failure"] == "ui_binding_mismatch"
    assert result["browser_failure"]["stage"] == "ui_verification"


def test_first_browser_failure_written_during_shutdown_is_inherited(fixture):
    fake = FakeRun(fixture)
    def browser(config, folder):
        def finish(*args):
            driver.save(folder / "first-failure.json", {
                "code": "answer_render_mismatch", "stage": "answer",
                "id": "opaque-case", "epoch_ms": 1000, "elapsed_ms": 3})
            return False
        return SimpleNamespace(process=SimpleNamespace(returncode=1), poll=lambda: 1,
            stop=lambda: None, cleanup_elapsed=lambda: 0, finish=finish)
    result = driver.execute(fixture.path, "calibration", fixture.run,
        service_factory=fake.service, browser_factory=browser, clock=lambda: fake.now)
    assert result["failure"] == "answer_render_mismatch"
    assert result["browser_failure"]["id"] == "opaque-case"
    assert result["cleanup_accepted"] is False


def test_cleanup_continues_after_one_owned_process_observation_or_kill_fails(owned_browser):
    rig = owned_browser
    rig.child.poll()
    rig.node.live = False
    def denied(*args, **kwargs):
        raise PermissionError("private OS details")
    rig.grandchild.children = denied
    rig.grandchild.kill = denied
    assert rig.child.finish(105, lambda: 100) is False
    assert not rig.chromium.live and rig.grandchild.live
    record = driver.read_json(rig.folder / "owned-exit.json")
    assert "browser_descendant_stop_failed" in record["errors"]
    assert "private" not in json.dumps(record)


def test_ack_uses_fresh_remaining_active_budget(owned_browser):
    rig = owned_browser
    rig.child.active_deadline = 1600
    rig.child.clock = lambda: 123
    rig.child.poll()
    ack = driver.read_json(rig.folder / "chromium-adopted.json")
    assert ack["active_budget_ms"] == 1477000
    assert ack["budget_epoch_ms"] > 0


def test_browser_failure_deadline_identity_and_ownership_contracts_without_browser(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable; no actual browser or model validation implied")
    url = (driver.ROOT / driver.CODE[2]).as_uri()
    source = f"""
      import {{run,activeDeadline,failureRecord,preserveFailure,verifyAnalysisIdentity,
        FAILURE_CODES,FAILURE_STAGES,store}} from {json.dumps(url)};
      import assert from 'node:assert/strict';
      import {{mkdirSync,readFileSync,existsSync}} from 'node:fs';
      import {{join}} from 'node:path';
      const root={json.dumps(str(tmp_path))};
      assert.deepEqual([...FAILURE_CODES].sort(),{json.dumps(sorted(driver.BROWSER_CODES))});
      assert.deepEqual([...FAILURE_STAGES].sort(),{json.dumps(sorted(driver.BROWSER_STAGES))});
      const secret=new Error('SECRET response body and credentials');
      secret.stack='SECRET stack'; secret.code='unrecognized-secret';
      const record=failureRecord(secret,'answer','case_1',5,20);
      assert.equal(record.code,'browser_action_failed');
      assert.equal(record.elapsed_ms,15);
      assert(!JSON.stringify(record).includes('SECRET'));
      assert.equal(failureRecord(secret,'SECRET','SECRET invalid id',0,1).id,null);
      preserveFailure(root,{{code:'ui_binding_mismatch'}},'ui_verification',null,0);
      preserveFailure(root,{{code:'browser_close_failed'}},'cleanup',null,0);
      assert.equal(JSON.parse(readFileSync(join(root,'first-failure.json'))).code,'ui_binding_mismatch');
      assert.equal(activeDeadline({{active_budget_ms:1200,budget_epoch_ms:1000}},50,1300),950);
      assert.equal(activeDeadline({{active_budget_ms:1200,budget_epoch_ms:1000}},50,3000),50);
      const identity={{model:'synthetic-browser-transport-fixture-NOT-LLM',revision:'fixture-v1'}};
      const result={{model:identity.model,model_revision:identity.revision}};
      assert.throws(()=>verifyAnalysisIdentity(result), e=>e.code==='analysis_identity_failed');
      verifyAnalysisIdentity(result,identity);
      const config=(dir)=>({{base_url:'http://127.0.0.1:1234',run_dir:dir,
        active_budget_ms:10000,budget_epoch_ms:Date.now(),ui:[{{url:'/',sha256:'different'}}]}});
      const failed=join(root,'failed'); mkdirSync(join(failed,'browser'),{{recursive:true}});
      await assert.rejects(run(config(failed),{{launchServer:async()=>{{throw secret;}}}},null));
      assert.equal(JSON.parse(readFileSync(join(failed,'browser','first-failure.json'))).stage,'ownership');
      assert(existsSync(join(failed,'browser','browser-closed.json')));
      const adopted=join(root,'adopted'), folder=join(adopted,'browser');
      mkdirSync(folder,{{recursive:true}});
      let connected=false,closed=false;
      const server={{process:()=>({{pid:999,exitCode:null}}),wsEndpoint:()=> 'fake-endpoint',
        close:async()=>{{closed=true;}}}};
      const chromium={{launchServer:async()=>server,connect:async()=>{{
        assert(existsSync(join(folder,'chromium-adopted.json'))); connected=true;
        return {{newContext:async()=>({{close:async()=>{{}},request:{{get:async()=>({{
          status:()=>200,body:async()=>Buffer.from('synthetic fixture bytes')}})}}}}),
          close:async()=>{{}}}};
      }}}};
      const pending=run(config(adopted),chromium,null,{{expectedAnalysisIdentity:identity}});
      await new Promise(done=>setTimeout(done,30));
      assert(!connected);
      store(join(folder,'chromium-adopted.json'),{{node_pid:process.pid,node_create_time:100,
        chromium_pid:999,chromium_create_time:101,active_budget_ms:9000,budget_epoch_ms:Date.now()}});
      await assert.rejects(pending,e=>e.code==='ui_binding_mismatch');
      assert(connected && closed);
      const failure=JSON.parse(readFileSync(join(folder,'first-failure.json')));
      assert.equal(failure.code,'ui_binding_mismatch'); assert.equal(failure.stage,'ui_verification');
      assert(!JSON.stringify(failure).includes('synthetic fixture'));
    """
    result = subprocess.run([node, "--input-type=module", "-e", source], capture_output=True,
                            timeout=15, check=False)
    assert result.returncode == 0, result.stderr.decode()


@pytest.mark.parametrize("location", ["node_identity", "node_children", "child_identity",
                                    "child_children"])
def test_adopted_browser_normal_exit_races_do_not_erase_ownership(owned_browser, location):
    rig = owned_browser
    rig.child.poll()
    original = dict(rig.child.descendants)
    def disappeared(*args, **kwargs):
        raise rig.Missing()
    if location == "node_identity":
        rig.node.create_time = disappeared
    elif location == "node_children":
        rig.node.children = disappeared
    elif location == "child_identity":
        rig.grandchild.create_time = disappeared
    else:
        rig.chromium.children = disappeared
    assert rig.child.poll() is None
    assert rig.child.ownership_confirmed is True
    assert all(rig.child.descendants[key] is value for key, value in original.items())


def test_disappearing_parent_during_adoption_never_grants_ownership(owned_browser):
    rig = owned_browser
    def disappeared():
        raise rig.Missing()
    rig.chromium.parents = disappeared
    with pytest.raises(driver.ExecutionError, match="browser_owner_unconfirmed"):
        rig.child.poll()
    assert rig.child.ownership_confirmed is False
    assert not (rig.folder / "chromium-adopted.json").exists()


def test_access_denied_in_poll_is_not_treated_as_normal_exit(owned_browser):
    rig = owned_browser
    rig.child.poll()
    def denied(*args, **kwargs):
        raise PermissionError("synthetic access denied")
    rig.node.children = denied
    with pytest.raises(PermissionError):
        rig.child.poll()


@pytest.mark.parametrize("code", ["active_timeout", "observer_failed", "selected_context_mismatch"])
def test_shutdown_browser_failure_does_not_replace_specific_driver_failure(fixture, code):
    fake = FakeRun(fixture)
    def browser(config, folder):
        def poll():
            raise driver.ExecutionError(code)
        def finish(*args):
            driver.save(folder / "first-failure.json", {
                "code": "stopped", "stage": "cleanup", "id": None,
                "epoch_ms": 1000, "elapsed_ms": 3})
            return False
        return SimpleNamespace(process=SimpleNamespace(returncode=1), poll=poll,
            stop=lambda: None, cleanup_elapsed=lambda: 0, finish=finish)
    result = driver.execute(fixture.path, "calibration", fixture.run,
        service_factory=fake.service, browser_factory=browser, clock=lambda: fake.now)
    assert result["failure"] == code
    assert result["browser_failure"]["code"] == "stopped"


def test_analysis_waits_for_detail_then_scoped_ready_badge():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable")
    url = (driver.ROOT / driver.CODE[2]).as_uri()
    source = f"""
      import {{waitForAnalysisDetail}} from {json.dumps(url)};
      import assert from 'node:assert/strict';
      const events=[],ready={{kind:'scoped-ready'}};
      let detailVisible=false;
      const detail={{kind:'detail',locator:selector=>{{
        assert(detailVisible); assert.equal(selector,'.analysis-status.ready');
        events.push('scoped-ready'); return ready;
      }}}};
      const page={{getByTestId:id=>{{assert.equal(id,'meeting-detail');return detail;}},
        locator:()=>{{throw new Error('ambiguous global badges must not be selected');}}}};
      const expect=locator=>({{toBeVisible:async options=>{{
        assert.equal(options.timeout,123);
        if(locator===detail){{events.push('detail-visible');detailVisible=true;}}
        else {{assert.equal(locator,ready);events.push('ready-visible');}}
      }}}});
      await waitForAnalysisDetail(page,expect,()=>123);
      assert.deepEqual(events,['detail-visible','scoped-ready','ready-visible']);
    """
    result = subprocess.run([node, "--input-type=module", "-e", source], capture_output=True,
                            timeout=15, check=False)
    assert result.returncode == 0, result.stderr.decode()


def test_classification_unit_sum_is_separate_from_observation_count(fixture):
    evidence = sink(fixture)
    for source_id, units in (("s1", 54), ("s2", 62)):
        current(fixture, "analyze", source_id)
        source = next(s for s in fixture.manifest["plan"]["sources"] if s["source_id"] == source_id)
        evidence("analyze", "started", {"content": Path(source["raw"]["path"]).read_text()})
        evidence("analyze", "classification_units", units)
    assert evidence.counts["analyze:classification_units"] == 116
    assert evidence.counts["analyze:classification_units_events"] == 2
    records = [driver.read_json(p) for p in sorted((fixture.run / "raw").glob("*.json"))]
    assert [r["value"] for r in records if r["event"] == "classification_units"] == [54, 62]


@pytest.mark.parametrize("returncode", [0, 1, 7, -15])
def test_closed_owned_browser_cleanup_is_independent_of_business_exit(owned_browser, returncode):
    rig = owned_browser
    rig.child.poll()
    rig.node.live = rig.chromium.live = rig.grandchild.live = False
    rig.child.process.returncode = returncode
    rig.child.process.poll = lambda: returncode
    rig.child.process.wait = lambda timeout: returncode
    driver.save(rig.folder / "browser-closed.json", {"closed": True})
    assert rig.child.finish(105, lambda: 100) is True
    record = driver.read_json(rig.folder / "owned-exit.json")
    assert record["node_returncode"] == returncode
    assert record["node_exited"] is True and record["errors"] == []
    assert rig.killed == []


@pytest.mark.parametrize("problem", ["closed_missing", "closed_false", "owned_alive", "node_alive",
                                     "ownership_unconfirmed"])
def test_business_exit_does_not_mask_missing_cleanup_proof(owned_browser, problem):
    rig = owned_browser
    rig.child.poll()
    rig.node.live = rig.chromium.live = rig.grandchild.live = False
    if problem != "closed_missing":
        driver.save(rig.folder / "browser-closed.json", {"closed": problem != "closed_false"})
    if problem == "owned_alive":
        rig.grandchild.live = True
    if problem == "node_alive":
        rig.node.live = True
    if problem == "ownership_unconfirmed":
        rig.child.ownership_confirmed = False
    assert rig.child.finish(105, lambda: 100) is False


def test_analysis_failure_remains_failed_when_real_browser_boundary_cleanup_passes(fixture,
                                                                                owned_browser):
    fake, rig = FakeRun(fixture), owned_browser
    rig.child.poll()
    rig.node.live = rig.chromium.live = rig.grandchild.live = False
    def browser(config, folder):
        rig.child.folder = folder
        driver.save(folder / "browser-closed.json", {"closed": True})
        driver.save(folder / "first-failure.json", {"code": "analysis_failed", "stage": "analysis",
                    "id": "s2", "epoch_ms": 1000, "elapsed_ms": 5})
        return rig.child
    result = driver.execute(fixture.path, "calibration", fixture.run, service_factory=fake.service,
        browser_factory=browser, clock=lambda: fake.now)
    assert result["cleanup_accepted"] is True
    assert result["status"] == "failed" and result["failure"] == "analysis_failed"
    assert result["browser_failure"]["code"] == "analysis_failed"
    assert not (fixture.run / "judge-answer-packet.json").exists()


@pytest.mark.parametrize("returncode,first_failure", [(0, None), (1, None), (-15, None),
                                                    (1, "analysis_failed")])
def test_late_node_exit_controls_business_result_not_cleanup(fixture, returncode, first_failure):
    fake = FakeRun(fixture)
    packet_present_during_cleanup = []
    def browser(config, folder):
        child = fake.browser(config, folder)
        child.process.returncode = None
        child.poll = lambda: None
        child.closing = lambda: True
        original_finish = child.finish
        def finish(deadline, clock):
            packet_present_during_cleanup.append((fixture.run / "judge-answer-packet.json").exists())
            child.process.returncode = returncode
            if first_failure:
                driver.save(folder / "first-failure.json", {"code": first_failure,
                    "stage": "analysis", "id": "s2", "epoch_ms": 1000, "elapsed_ms": 5})
            return original_finish(deadline, clock)
        child.finish = finish
        return child
    result = driver.execute(fixture.path, "calibration", fixture.run, service_factory=fake.service,
        browser_factory=browser, clock=lambda: fake.now)
    assert result["cleanup_accepted"] is True
    assert packet_present_during_cleanup == [False]
    if returncode == 0:
        assert result["status"] == "mechanical_completed_judgment_pending"
        assert result["judge_packet_eligible"] is True
        assert (fixture.run / "judge-answer-packet.json").exists()
    else:
        assert result["status"] == "failed"
        assert result["failure"] == (first_failure or "browser_failed")
        assert result["judge_packet_eligible"] is False
        assert not (fixture.run / "judge-answer-packet.json").exists()


@pytest.mark.parametrize("failure", ["cleanup", "final_binding"])
def test_judge_packet_is_not_published_when_final_gate_fails(fixture, failure):
    fake = FakeRun(fixture, browser_survives=failure == "cleanup", changed=failure == "final_binding")
    result = driver.execute(fixture.path, "calibration", fixture.run, service_factory=fake.service,
        browser_factory=fake.browser, clock=lambda: fake.now)
    assert result["status"] == "failed"
    assert not (fixture.run / "judge-answer-packet.json").exists()


@pytest.mark.parametrize("failure", ["elapsed", "write"])
def test_packet_publication_failure_preserves_file_but_forbids_judgment(fixture, monkeypatch, failure):
    fake = FakeRun(fixture)
    original = driver.save
    def publication(path, value):
        original(path, value)
        if path.name == "judge-answer-packet.json":
            if failure == "elapsed":
                fake.now += 1626
            else:
                raise OSError("synthetic publication storage failure")
    monkeypatch.setattr(driver, "save", publication)
    result = driver.execute(fixture.path, "calibration", fixture.run, service_factory=fake.service,
        browser_factory=fake.browser, clock=lambda: fake.now)
    assert (fixture.run / "judge-answer-packet.json").exists()
    assert result["status"] == "failed" and result["judge_packet_eligible"] is False
    assert result["cleanup_accepted"] is True
    if failure == "elapsed":
        assert result["window_exceeded"] is True and result["wall_seconds"] > 1625
        packet = (fixture.run / "judge-answer-packet.json").read_bytes()
        assert result["judge_packet"]["sha256"] == driver.digest(packet)
    else:
        assert result["failure"] == "evidence_write_failed"


def register_analysis_policy(fixture, policy="batch-v1", *, adapter=True, registered=True):
    plan = fixture.manifest["plan"]
    plan["analysis_policy"] = policy
    if registered:
        fixture.registration["policy"]["analysis_policy"] = policy
    plan["code"] = [row for row in plan["code"]
                    if Path(row["path"]).name != "meeting_analysis_batch.py"]
    if adapter:
        plan["code"].append(binding(driver.ROOT / "src/doctrail/meeting_analysis_batch.py"))
    ci = driver.read_json(plan["ci"]["path"])
    ci["code"] = plan["code"]
    plan["ci"] = write(fixture.tmp / "ci.json", ci)
    fixture.registration["accepted_bindings"]["ci"] = plan["ci"]["sha256"]
    reregister(fixture)


@pytest.mark.parametrize("policy", [None, "single", "batch-v1"])
def test_registered_analysis_policy_reaches_service_factory(fixture, policy):
    if policy is not None:
        register_analysis_policy(fixture, policy)
    fake = FakeRun(fixture)
    seen = []
    def service(**kwargs):
        seen.append(kwargs["analysis_policy"])
        return fake.service(**kwargs)
    result = driver.execute(fixture.path, "calibration", fixture.run, service_factory=service,
                            browser_factory=fake.browser, clock=lambda: fake.now)
    assert result["status"] == "mechanical_completed_judgment_pending"
    assert seen == [policy or "single"] and result["analysis_policy"] == (policy or "single")


@pytest.mark.parametrize("fault,expected", [("unregistered", "policy_mismatch"),
    ("adapter_missing", "code_binding_missing"), ("unknown", "policy_mismatch"),
    ("registration_only", "policy_mismatch"), ("adapter_changed", "binding_changed")])
def test_batch_requires_explicit_registered_policy_and_exact_adapter_binding(fixture, fault, expected):
    register_analysis_policy(fixture, "auto" if fault == "unknown" else "batch-v1",
                             adapter=fault != "adapter_missing", registered=fault != "unregistered")
    if fault == "registration_only":
        del fixture.manifest["plan"]["analysis_policy"]
        reregister(fixture)
    if fault == "adapter_changed":
        plan = fixture.manifest["plan"]
        plan["code"][-1]["sha256"] = "0" * 64
        ci = driver.read_json(plan["ci"]["path"])
        ci["code"] = plan["code"]
        plan["ci"] = write(fixture.tmp / "ci.json", ci)
        fixture.registration["accepted_bindings"]["ci"] = plan["ci"]["sha256"]
        reregister(fixture)
    result = driver.execute(fixture.path, "calibration", fixture.run,
        service_factory=lambda **kwargs: pytest.fail("unregistered policy started service"))
    assert result["status"] == "failed" and result["failure"] == expected


def test_classification_units_events_and_batches_are_separate(fixture):
    evidence = sink(fixture)
    current(fixture, "analyze", "s1")
    source = fixture.manifest["plan"]["sources"][1]
    evidence("analyze", "started", {"content": Path(source["raw"]["path"]).read_text()})
    evidence("analyze", "classification_units", 9)
    for ids in (list(range(8)), [8]):
        evidence("analyze", "classification_batch", {"ids": ids, "grammar_sha256": "a" * 64,
                                                    "input_tokens": 100})
    assert evidence.counts["analyze:classification_units"] == 9
    assert evidence.counts["analyze:classification_units_events"] == 1
    assert evidence.counts["analyze:classification_batch"] == 2


@pytest.mark.parametrize("policy", [None, "single", "batch-v1"])
@pytest.mark.parametrize("fault", ["missing", "changed"])
def test_every_effective_policy_pins_loaded_batch_dependency(fixture, policy, fault):
    register_analysis_policy(fixture, policy or "single", adapter=fault != "missing")
    plan = fixture.manifest["plan"]
    if policy is None:
        del plan["analysis_policy"]
        del fixture.registration["policy"]["analysis_policy"]
    if fault == "changed":
        plan["code"][-1]["sha256"] = "0" * 64
    ci = driver.read_json(plan["ci"]["path"])
    ci["code"] = plan["code"]
    plan["ci"] = write(fixture.tmp / "ci.json", ci)
    fixture.registration["accepted_bindings"]["ci"] = plan["ci"]["sha256"]
    reregister(fixture)
    result = driver.execute(fixture.path, "calibration", fixture.run,
        service_factory=lambda **kwargs: pytest.fail("unbound loaded dependency started service"))
    expected = "code_binding_missing" if fault == "missing" else "binding_changed"
    assert result["status"] == "failed" and result["failure"] == expected


@pytest.mark.parametrize("policy,gate_policy,accepted", [
    (None, None, True), (None, "single", True), ("single", None, True),
    ("single", "single", True), ("batch-v1", "batch-v1", True),
    (None, "batch-v1", False), ("single", "batch-v1", False),
    ("batch-v1", None, False), ("batch-v1", "single", False),
    ("single", "auto", False), ("batch-v1", "auto", False)])
def test_validation_gate_requires_same_effective_analysis_policy(fixture, policy, gate_policy,
                                                               accepted):
    if policy is not None:
        register_analysis_policy(fixture, policy)
    plan = fixture.manifest["plan"]
    fixture.manifest["phase"] = fixture.registration["phase"] = "validation"
    questions = fixture.questions
    questions["phase"] = "validation"
    questions["cases"].extend([{**questions["cases"][3], "id": f"c{i}"} for i in (6, 7)])
    plan["questions"] = write(fixture.tmp / "questions.json", questions)
    roles = driver.read_json(plan["roles"]["path"])
    roles["executor"]["phase"] = roles["final_judge"]["phase"] = "validation"
    plan["roles"] = write(fixture.tmp / "roles.json", roles)
    fixture.registration["accepted_bindings"]["roles"] = plan["roles"]["sha256"]
    gate = {"phase": "calibration", "answers_total": 6, "answers_passed": 6,
            "judgment_locked": True, "operational_accepted": True, "cleanup_accepted": True,
            "code": plan["code"], "judge_lock_sha256": "a" * 64, "run_receipt_sha256": "b" * 64}
    if gate_policy is not None:
        gate["analysis_policy"] = gate_policy
    plan["gate"] = write(fixture.tmp / "gate.json", gate)
    fixture.registration["gate_sha256"] = plan["gate"]["sha256"]
    reregister(fixture)
    if accepted:
        assert driver.verify_inputs(fixture.manifest, "validation", fixture.run) == questions
    else:
        result = driver.execute(fixture.path, "validation", fixture.run,
            service_factory=lambda **kwargs: pytest.fail("cross-policy gate started service"))
        assert result["status"] == "failed" and result["failure"] == "calibration_gate_rejected"