"""Synthetic sealed sources and HTTP transport only; no official/model calls."""
import copy
import json
import os
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest

from doctrail.inference import WorkerError
from doctrail.meeting_qwen35 import GGUF_SHA256, NONTHINKING_PREAMBLE
from scripts import prepare_meeting_requirements_inputs as prep
from scripts import probe_meeting_requirements as probe
from tests.test_meeting_requirements_review import attestation
from tests.test_prepare_meeting_requirements_inputs import factory as factory_fixture
from tests.test_prepare_meeting_requirements_inputs import write

factory = factory_fixture
from tests.test_prepare_meeting_requirements_inputs import run as prepare_fixture


def metadata():
    return {"repo_id": probe.MODEL_ID, "original_revision": probe.MODEL_REVISION,
        "revision": "gguf-sha256:" + GGUF_SHA256, "artifact": {"sha256": GGUF_SHA256},
        "generation_protocol": probe.ANSWER_POLICY, "runtime": {"backend": "llama.cpp",
            "context_tokens": 6144, "max_input_tokens": 5120, "max_new_tokens": 384,
            "deadline_seconds": 90, "tag": "b11429", "commit": "d81235049384534c167caea52b85a694f6103d14",
            "observed_build": "b11429-d81235049", "identity_check": "local_gguf_sha256_and_server_alias"},
        "nonthinking": {"enable_thinking_requested": False, "assistant_preamble_sha256": probe.PREAMBLE_SHA256,
            "policy": "qwen35-terminal-assistant-preamble-v1", "last_template_verified": False,
            "verification_scope": "terminal_assistant_preamble_per_prompt"}}


class Process:
    pid = os.getpid()
    def __init__(self): self.stopped = False
    def poll(self): return 0 if self.stopped else None
    def kill(self): self.stopped = True
    def wait(self, timeout=None): self.stopped = True; return 0


class Transport:
    def __init__(self):
        self.dispatched, self.prepared, self.bases, self.processes = [], [], [], []
        self.fail_at = None
        self.token_count = None
        self.plan_status = "supported"
        self.status_for_case = None
        self.force_answer_abstention = False
        self.mutate = None
        self.runtime_receipt = {"synthetic_runtime_only": True}

    @contextmanager
    def service(self, directory, remaining):
        process = Process()
        self.processes.append(process)
        yield SimpleNamespace(process=process, receipt=self.runtime_receipt)
        assert process.stopped

    def base(self, service, observer):
        def handler(request):
            body = json.loads(request.content)
            if request.url.path == "/apply-template":
                self.prepared.append(body)
                return httpx.Response(200, json={"prompt": json.dumps(body) + NONTHINKING_PREAMBLE})
            if request.url.path == "/tokenize":
                count = (5000 if observer.stress else 100) if self.token_count is None else self.token_count(observer)
                return httpx.Response(200, json={"tokens": list(range(count))})
            assert request.url.path == "/completion"
            persisted = json.loads((observer.prepared["root"] / observer.prepared["output_dir"] / "report.json").read_bytes())
            assert persisted["calls"][-1]["status"] == "started" and persisted["calls"][-1]["payload"] == body
            self.dispatched.append(copy.deepcopy(body))
            if self.fail_at == len(self.dispatched):
                raise httpx.ReadError("PRIVATE transport failure")
            stage = observer.current["stage"]
            language = observer.case.get("response_language", "en")
            claim = "The fictional beacon is turquoise." if observer.case["id"] == "normal" else (
                "Synthetic fact." if language == "en" else "합성 사실입니다.")
            status = self.status_for_case(observer.case) if self.status_for_case else self.plan_status
            plan = {"requirements": [{"requirement_id": 1, "need": "Synthetic need" if language == "en" else "합성 요구",
                "status": status, "evidence_ids": [0] if status == "supported" else []}]}
            raw = json.dumps(plan if stage == 1 else {"status": "answered", "claims": [{"requirement_id": 1, "text": claim}]})
            if stage == 2 and self.force_answer_abstention:
                raw = '{"status":"abstained","claims":[]}'
            result = {"model": GGUF_SHA256, "generation_settings": {k: body[k] for k in (*probe.GREEDY, "n_predict", "grammar")},
                "content": "load " * 384 if observer.stress else raw,
                "tokens_evaluated": len(body["prompt"]), "tokens_predicted": 384 if observer.stress else 30,
                "stop": True, "stop_type": "limit" if observer.stress else "eos", "truncated": False,
                "timings": {"cache_n": 0, "prompt_n": len(body["prompt"]), "predicted_n": 383 if observer.stress else 29,
                    "prompt_ms": 0.1, "predicted_ms": 0.1}}
            if self.mutate:
                self.mutate(result, observer)
            return httpx.Response(200, json=result)
        base = probe.ObservedGenerator("http://127.0.0.1:12345", "x" * 32, "synthetic-unused.json",
            observer=observer, transport=httpx.MockTransport(handler))
        base._alias, base._metadata = GGUF_SHA256, metadata()
        self.bases.append(base)
        return base


def reference(root, name):
    return {"file": name, "sha256": probe.sha((root / name).read_bytes())}


@pytest.fixture
def world(factory, tmp_path):
    cal = factory("calibration")
    registry_cal = json.loads((tmp_path / prep.REGISTRY).read_bytes())
    val = factory("validation")
    registry_val = json.loads((tmp_path / prep.REGISTRY).read_bytes())
    write(tmp_path / prep.REGISTRY, {"schema_version": 1, "families": registry_cal["families"] + registry_val["families"]})
    cal.seal(); val.seal()
    refs = {}
    for data in (cal, val):
        data.output = tmp_path / f".local/meetings-c3-{data.phase}-prepared-v1"
        prepare_fixture(data)
        refs[data.phase] = reference(tmp_path, data.output.relative_to(tmp_path).as_posix() + "/receipt.json")
    transport = Transport()
    runtime_name = "models/meetings-qwen35-v1/setup-receipt.json"
    write(tmp_path / runtime_name, transport.runtime_receipt)
    neutral_name = "data/evaluation/meetings-c3-neutral-plan-synthetic.json"
    neutral = probe.register_neutral(neutral_name, ".local/meetings-c3-neutral-synthetic",
        code_freeze=prep.TOOLCHAIN_FREEZE, calibration_receipt=refs["calibration"]["file"],
        validation_receipt=refs["validation"]["file"], runtime_receipt=runtime_name, root=tmp_path,
        loader=cal.loader, counter=lambda _, msgs: 5000 if "resource_stage" in msgs[-1]["content"] else 100)
    resource = probe.run_neutral(neutral_name, root=tmp_path, factory=transport.service, base_factory=transport.base)
    assert resource["status"] == "completed", resource
    report_name = "experiments/results/meetings-c3-resources-synthetic.json"
    write(tmp_path / report_name, resource)
    plan = {k: copy.deepcopy(neutral[k]) for k in ("schema_version", "candidate", "limits", "code_freeze", "bound_files", "registry", "runtime_receipt_sha256", "tokenizer")}
    plan.update(kind="quality", resource_plan=reference(tmp_path, neutral_name), resource_report=reference(tmp_path, report_name),
        phases={}, audit={}, excluded_roles=sorted(probe.EXCLUDED_ROLES | {"source-writer", "source-reviewer", "writer", "item-reviewer"}))
    for data in (cal, val):
        phase = data.phase
        plan["phases"][phase] = {"case_ids": [c["id"] for c in data.draft["cases"]],
            **{role: reference(tmp_path, data.names[role]) for role in ("oracle", "source_freeze", "item_freeze")},
            "input": reference(tmp_path, data.output.relative_to(tmp_path).as_posix() + "/input.json"),
            "preparation_receipt": refs[phase], "output_dir": f".local/meetings-c3-run-{phase}-v1"}
        prefix = f".local/meetings-c3-review-metadata-v1/{phase}"
        write(tmp_path / prefix / "seed.bin", (phase.encode() * 64)[:64])
        exposure = attestation() | {"reviewer_id": "judge-" + phase}
        write(tmp_path / prefix / "attestation.json", exposure)
        plan["audit"][phase] = {"reviewer_id": exposure["reviewer_id"], "seed": reference(tmp_path, prefix + "/seed.bin"),
            "attestation": reference(tmp_path, prefix + "/attestation.json"), "output_dir": ".local/meetings-c3-audit-" + phase + "-v1"}
    plan_name = "data/evaluation/meetings-c3-quality-plan-synthetic.json"
    write(tmp_path / plan_name, plan)
    return SimpleNamespace(root=tmp_path, cal=cal, val=val, plan=plan, plan_name=plan_name, transport=transport,
        resource=resource, neutral=neutral, neutral_name=neutral_name)


def run_phase(world, phase="calibration", gate=None):
    prepared = probe.check(world.plan_name, phase, gate, root=world.root)
    return probe.run(prepared, factory=world.transport.service, base_factory=world.transport.base)


def test_neutral_four_and_calibration_twelve_real_transport_paths(world):
    report = run_phase(world)
    assert report["status"] == "completed", report
    assert len(report["calls"]) == 12 and len(report["ledger_entries"]) == 16
    assert report["actual_native_posts"] == 12 and all(p.stopped for p in world.transport.processes)
    for row in report["results"]:
        assert row["telemetry"]["completion_attempts"] == 2
        assert row["stage2_readiness"] == "measured_at_runtime"
    with pytest.raises(FileExistsError):
        run_phase(world)


@pytest.mark.parametrize("status", ["missing", "uncertain"])
def test_one_stage_abstention_and_dynamic_unmeasured(world, status):
    world.transport.plan_status = status
    report = run_phase(world)
    assert report["status"] == "completed", report
    assert len(report["calls"]) == 6
    assert all(r["answer"]["status"] == "abstained" and r["stage2_readiness"] == "not_required" for r in report["results"])


def test_stage2_overflow_keeps_first_raw_and_zero_second_dispatch(world):
    world.transport.token_count = lambda o: 5121 if o.current["stage"] == 2 else 100
    report = run_phase(world)
    assert report["status"] == "failed" and len(report["calls"]) == 1 and len(report["unexecuted"]) == 5
    assert len(report["results"][0]["preparations"]) == 2
    assert report["results"][0]["telemetry"]["completion_attempts"] == 1


def test_started_receipt_survives_transport_failure_no_retry(world):
    world.transport.fail_at = 5
    report = run_phase(world)
    assert report["status"] == "failed" and len(report["calls"]) == 1
    assert report["calls"][0]["dispatch_started"] and "raw_response" not in report["calls"][0]
    assert report["actual_native_posts"] == 1 and len(world.transport.dispatched) == 5
    assert "PRIVATE" not in json.dumps(report)


@pytest.mark.parametrize("role", ["seed", "attestation"])
def test_metadata_path_rejects_heldout_body_before_read(world, role, monkeypatch):
    plan = copy.deepcopy(world.plan)
    plan["audit"]["calibration"][role]["file"] = world.val.names["oracle"]
    seen = []
    monkeypatch.setattr(probe.Snapshots, "get", lambda _, name, expected=None: seen.append(name))
    with pytest.raises(ValueError, match="metadata_path"):
        probe.metadata_paths(plan, world.root)
    assert seen == []


@pytest.mark.parametrize("phase", ["calibration", "validation"])
def test_register_rejects_arbitrary_survey_body_before_read(world, phase, monkeypatch):
    seen = []
    monkeypatch.setattr(probe.Snapshots, "get", lambda _, name, expected=None: seen.append(name))
    with pytest.raises(ValueError, match="preparation_metadata_path"):
        probe.register_neutral(".local/meetings-c3-neutral-plan-another.json", ".local/meetings-c3-neutral-new",
            code_freeze=prep.TOOLCHAIN_FREEZE, calibration_receipt=world.cal.names["oracle"] if phase == "calibration" else world.plan["phases"]["calibration"]["preparation_receipt"]["file"],
            validation_receipt=world.val.names["oracle"] if phase == "validation" else world.plan["phases"]["validation"]["preparation_receipt"]["file"],
            runtime_receipt="models/meetings-qwen35-v1/setup-receipt.json", root=world.root)
    assert not seen


def trace(count=100):
    messages, grammar = [{"role": "user", "content": "New synthetic trace."}], "root ::= \"ok\"\n"
    rendered = "New synthetic rendering" + NONTHINKING_PREAMBLE
    tokens = list(range(count))
    payload = {**probe.GREEDY, "prompt": tokens, "n_predict": 384, "grammar": grammar, "cache_prompt": False, "return_tokens": True}
    expected = {**probe.GREEDY, "n_predict": 384, "grammar": grammar}
    native = {"model": GGUF_SHA256, "generation_settings": expected, "content": "ok", "tokens_evaluated": count,
        "tokens_predicted": 30, "stop": True, "stop_type": "eos", "truncated": False,
        "timings": {"cache_n": 0, "prompt_n": count, "predicted_n": 29, "prompt_ms": 1, "predicted_ms": 1}}
    row = {"status": "returned", "dispatch_started": True, "messages_sha256": probe.fingerprint(messages),
        "rendered_sha256": probe.sha(rendered.encode()), "template": {"request": {"messages": messages,
            "chat_template_kwargs": {"enable_thinking": False}}, "response": {"prompt": rendered}},
        "tokenize": {"request": {"content": rendered, "add_special": False, "parse_special": True, "with_pieces": False},
            "response": {"tokens": tokens}}, "payload": payload, "payload_sha256": probe.fingerprint(payload),
        "grammar_sha256": probe.sha(grammar.encode()), "input_tokens": count, "raw_response": native,
        "effective_config": {"backend": "llama.cpp", **expected, "cache_prompt_requested": False,
            "observed_cache_tokens": 0, "observed_nonthinking_preamble_sha256": probe.PREAMBLE_SHA256, "enable_thinking_requested": False}}
    return row, messages, grammar


@pytest.mark.parametrize("count", [4096, 4097, 5120, 5121])
def test_trace_actual_input_boundary_and_distinct_native_decode_count(count):
    row, messages, grammar = trace(count)
    if count <= 5120:
        probe.check_trace(row, messages, grammar, metadata(), expected_tokens=count)
    else:
        with pytest.raises(ValueError, match="native_trace"):
            probe.check_trace(row, messages, grammar, metadata(), expected_tokens=count)


@pytest.mark.parametrize("field,value", [
    ("model", "wrong"), ("stop", 1), ("truncated", 0), ("stop_type", "limit"),
    ("tokens_evaluated", False), ("tokens_predicted", 385), ("tokens_predicted", True),
    ("content", None), ("tokens_evaluated", 101),
])
def test_native_replay_rejects_config_types_counts_and_identity(field, value):
    row, messages, grammar = trace()
    row["raw_response"][field] = value
    with pytest.raises(ValueError):
        probe.check_trace(row, messages, grammar, metadata())


@pytest.mark.parametrize("mutation", [
    lambda r: r["payload"].update(grammar=probe.STRESS_GRAMMAR),
    lambda r: r["payload"].update(cache_prompt=0),
    lambda r: r["template"]["request"]["messages"][0].update(content="replaced"),
    lambda r: r["tokenize"]["request"].update(parse_special=False),
    lambda r: r["tokenize"]["response"]["tokens"].__setitem__(0, False),
    lambda r: r["raw_response"]["generation_settings"].update(temperature=0.5),
    lambda r: r["raw_response"]["timings"].update(cache_n=1),
    lambda r: r["raw_response"]["timings"].update(predicted_ms=float("nan")),
    lambda r: r["effective_config"].update(enable_thinking_requested=0),
    lambda r: r.update(status="started"),
])
def test_trace_tampering_is_not_a_success_flag(mutation):
    row, messages, grammar = trace()
    expected_messages = copy.deepcopy(messages)
    mutation(row)
    with pytest.raises(ValueError):
        probe.check_trace(row, expected_messages, grammar, metadata())


def test_snapshot_single_bounded_read_and_drift(tmp_path):
    name = ".local/new-synthetic.json"
    write(tmp_path / name, {"marker": "e\u0301 😀\r\n"})
    snapshots = probe.Snapshots(tmp_path)
    first = snapshots.get(name)
    write(tmp_path / name, {"changed": True})
    assert snapshots.get(name) == first
    with pytest.raises(ValueError, match="hash_changed"):
        snapshots.unchanged()
    write(tmp_path / name, b"x" * (probe.BYTE_LIMIT + 1))
    with pytest.raises(ValueError, match="snapshot_limit"):
        probe.Snapshots(tmp_path).get(name)


@pytest.mark.parametrize("name", ["../escape", ".local/../escape", "C:/outside/file", ".local\\bad.json"])
def test_unsafe_relative_paths(name, tmp_path):
    with pytest.raises(ValueError):
        probe.path(name, tmp_path)


def test_runtime_metadata_path_rejected_without_read(tmp_path, monkeypatch):
    monkeypatch.setattr(probe.Snapshots, "get", lambda *a: pytest.fail("opened arbitrary runtime body"))
    with pytest.raises(ValueError, match="runtime_metadata_path"):
        probe.register_neutral(".local/meetings-c3-neutral-plan-new.json", ".local/meetings-c3-neutral-new",
            code_freeze=prep.TOOLCHAIN_FREEZE,
            calibration_receipt=".local/meetings-c3-calibration-prepared-v1/receipt.json",
            validation_receipt=".local/meetings-c3-validation-prepared-v1/receipt.json",
            runtime_receipt=".local/meetings-c3-validation-source/raw.txt", root=tmp_path)


def test_cli_error_never_prints_private_text(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise ValueError("PRIVATE body exception")
    monkeypatch.setattr(probe, "check", fail)
    with pytest.raises(SystemExit) as exit_result:
        probe.main(["check", "--plan", "synthetic", "--phase", "calibration"])
    assert exit_result.value.code == 1
    assert "PRIVATE" not in capsys.readouterr().out


def test_actual_stage2_and_mapper_replay_reject_tampering(world):
    report = run_phase(world)
    assert report["status"] == "completed", report
    inputs = json.loads((world.root / world.plan["phases"]["calibration"]["input"]["file"]).read_bytes())
    case = inputs["cases"][0]
    original_row = report["results"][0]
    original_calls = report["calls"][:2]
    mutations = [
        lambda row, calls: row["answer"]["claims"][0].update(text="Fabricated accepted answer"),
        lambda row, calls: row["answer"]["claims"][0]["citations"][0].update(end_offset=0),
        lambda row, calls: row["telemetry"].update(completion_attempts=1),
        lambda row, calls: row["telemetry"]["requirements"][0].update(status="missing"),
        lambda row, calls: row["telemetry"]["resource_identity"]["nonthinking"].update(last_template_verified=True),
        lambda row, calls: calls[1]["template"]["request"]["messages"][1].update(content="Different plan"),
        lambda row, calls: calls[0]["raw_response"].update(content='{"requirements":[]}'),
    ]
    for mutation in mutations:
        row, calls = copy.deepcopy(original_row), copy.deepcopy(original_calls)
        mutation(row, calls)
        with pytest.raises((ValueError, WorkerError)):
            probe.replay_request(case, row, calls, report["model_runtime"])


def test_preflight_memory_payload_and_source_drift_stop_before_service(world):
    prepared = probe.check(world.plan_name, "calibration", root=world.root)
    prepared["cases"][0]["payload"]["query"] = "Changed after preflight"
    with pytest.raises(ValueError, match="prepared_payload_changed"):
        probe.run(prepared, factory=lambda *a: pytest.fail("started before snapshot validation"))
    prepared = probe.check(world.plan_name, "calibration", root=world.root)
    write(world.root / world.cal.names["draft"], {"changed": True})
    with pytest.raises(ValueError, match="hash_changed"):
        probe.run(prepared, factory=lambda *a: pytest.fail("started with source drift"))


def test_request_and_response_byte_guards_are_replayed():
    row, messages, grammar = trace()
    row["raw_response"]["content"] = "x" * (probe.MAX_RESPONSE_BYTES + 1)
    with pytest.raises(ValueError, match="native_trace"):
        probe.check_trace(row, messages, grammar, metadata())
    row, messages, grammar = trace()
    rendered = "x" * probe.MAX_REQUEST_BYTES + NONTHINKING_PREAMBLE
    row["template"]["response"]["prompt"] = rendered
    row["rendered_sha256"] = probe.sha(rendered.encode())
    row["tokenize"]["request"]["content"] = rendered
    with pytest.raises(ValueError, match="native_trace"):
        probe.check_trace(row, messages, grammar, metadata())


def test_atomic_temporary_collision_never_overwrites_existing_file(tmp_path):
    output = ".local/meetings-c3-run-calibration-v1"
    existing = tmp_path / output / "report.tmp"
    write(existing, b"untouched synthetic sentinel")
    with pytest.raises(FileExistsError):
        probe.save(output, {"new": True}, tmp_path)
    assert existing.read_bytes() == b"untouched synthetic sentinel"
    ledger_temp = tmp_path / ".local/meetings-c3-native-ledger-v1.tmp"
    write(ledger_temp, b"untouched ledger sentinel")
    with pytest.raises(FileExistsError):
        probe.write_ledger([], {"file": "fake", "sha256": "a" * 64}, tmp_path)
    assert ledger_temp.read_bytes() == b"untouched ledger sentinel"


def test_symlinked_output_is_rejected(tmp_path):
    source = tmp_path / "original"
    source.mkdir()
    linked = tmp_path / ".local/link"
    linked.parent.mkdir()
    try:
        linked.symlink_to(source, target_is_directory=True)
    except OSError:
        pytest.skip("Windows account cannot create directory symbolic links")
    with pytest.raises(ValueError, match="linked_path"):
        probe.path(".local/link/report.json", tmp_path, local=True)


def test_quality_binds_exact_preparation_refs_registered_before_neutral(world):
    # Exercise both the real resource replay and each changed reference, with no model.
    probe.resource_evidence(world.plan, probe.Snapshots(world.root))
    for phase in probe.COUNTS:
        changed = copy.deepcopy(world.plan)
        changed["phases"][phase]["preparation_receipt"]["sha256"] = "f" * 64
        with pytest.raises(ValueError, match="resource_binding"):
            probe.resource_evidence(changed, probe.Snapshots(world.root))


@pytest.fixture
def review_registration(tmp_path):
    """Only four review metadata files exist; semantic paths are unopened sentinels."""
    def placeholder(name):
        return {"file": name, "sha256": "a" * 64}
    plan = {"kind": "quality", "phases": {}, "audit": {}, "excluded_roles": sorted(probe.EXCLUDED_ROLES),
        "code_freeze": placeholder(prep.TOOLCHAIN_FREEZE), "registry": placeholder(prep.REGISTRY),
        "resource_plan": placeholder(".local/meetings-c3-neutral-plan-synthetic.json"),
        "resource_report": placeholder("experiments/results/meetings-c3-resources-synthetic.json")}
    for phase, count in probe.COUNTS.items():
        prefix = f".local/meetings-c3-{phase}-synthetic"
        plan["phases"][phase] = {"case_ids": [f"{phase}-{i}" for i in range(count)],
            **{key: placeholder(f"{prefix}/{key}.json") for key in ("input", "oracle", "item_freeze", "source_freeze")},
            "preparation_receipt": placeholder(f".local/meetings-c3-{phase}-prepared-v1/receipt.json"),
            "output_dir": f".local/meetings-c3-run-{phase}-v1"}
        prefix = f".local/meetings-c3-review-metadata-v1/{phase}"
        exposure = attestation() | {"reviewer_id": f"judge-{phase}", "registered_at": "2000-01-01T00:00:00+00:00"}
        write(tmp_path / prefix / "seed.bin", b"s" * 64)
        write(tmp_path / prefix / "attestation.json", exposure)
        plan["audit"][phase] = {"reviewer_id": exposure["reviewer_id"],
            "seed": reference(tmp_path, prefix + "/seed.bin"),
            "attestation": reference(tmp_path, prefix + "/attestation.json"),
            "output_dir": f".local/meetings-c3-audit-{phase}-v1"}
    return plan


def test_review_metadata_snapshots_exactly_both_splits_and_actual_preflight_time(review_registration, tmp_path, monkeypatch):
    from datetime import UTC, datetime
    before = datetime.now(UTC)
    cutoffs = []
    validator = probe.validate_attestation
    def inspect(*args, **kwargs):
        cutoffs.append(datetime.fromisoformat(kwargs["pack_opened_at"]))
        return validator(*args, **kwargs)
    monkeypatch.setattr(probe, "validate_attestation", inspect)
    original = copy.deepcopy(review_registration)
    snapshots = probe.Snapshots(tmp_path)
    probe.validate_review_metadata(review_registration, snapshots)
    after = datetime.now(UTC)
    assert set(snapshots.hashes) == {
        data[role]["file"] for data in review_registration["audit"].values() for role in ("seed", "attestation")}
    assert len(cutoffs) == 2 and all(before <= cutoff <= after for cutoff in cutoffs)
    assert review_registration == original  # No fabricated future pack disclosure timestamp.


@pytest.mark.parametrize("phase", list(probe.COUNTS))
@pytest.mark.parametrize("role", ["seed", "attestation"])
def test_review_metadata_all_paths_precede_any_metadata_read(review_registration, tmp_path, monkeypatch, phase, role):
    review_registration["audit"][phase][role] = review_registration["phases"]["validation"]["oracle"]
    monkeypatch.setattr(probe.Snapshots, "get", lambda *a, **k: pytest.fail("read before both metadata namespaces checked"))
    with pytest.raises(ValueError, match="review_metadata_path"):
        probe.validate_review_metadata(review_registration, probe.Snapshots(tmp_path))


@pytest.mark.parametrize("phase", list(probe.COUNTS))
@pytest.mark.parametrize("defect", ["missing-seed", "missing-attestation", "seed-drift", "attestation-drift",
    "seed-short", "seed-long", "invalid-json", "invalid-schema", "wrong-reviewer", "participated", "plan-exposure",
    "raw-exposure", "mapping-exposure", "judgments-exposure", "future-timestamp"])
def test_review_metadata_invalid_blocks_check_before_any_semantic_read(review_registration, tmp_path, monkeypatch, phase, defect):
    registration = review_registration["audit"][phase]
    role = "seed" if "seed" in defect else "attestation"
    target = tmp_path / registration[role]["file"]
    if defect.startswith("missing"):
        target.unlink()
    elif defect.endswith("drift"):
        write(target, b"changed after sealing")
    else:
        if defect == "seed-short":
            replacement = b"s" * 31
        elif defect == "seed-long":
            replacement = b"s" * 129
        elif defect == "invalid-json":
            replacement = b"{"
        elif defect == "invalid-schema":
            replacement = {}
        else:
            replacement = json.loads(target.read_bytes())
            mutations = {"wrong-reviewer": {"reviewer_id": "another-judge"},
                "participated": {"participating_roles": ["/root"], "role_nonparticipation": False},
                "plan-exposure": {"plan_seen": True}, "raw-exposure": {"raw_trace_seen": True},
                "mapping-exposure": {"mapping_seen": True}, "judgments-exposure": {"prior_judgments_seen": True},
                "future-timestamp": {"registered_at": "9999-01-01T00:00:00+00:00"}}
            replacement.update(mutations[defect])
        registration[role]["sha256"] = write(target, replacement)
    plan_name = ".local/meetings-c3-quality-plan-metadata.json"
    write(tmp_path / plan_name, review_registration)
    allowed = {plan_name} | {entry[key]["file"] for entry in review_registration["audit"].values()
                            for key in ("seed", "attestation")}
    original_get = probe.Snapshots.get
    def metadata_only(self, name, expected=None):
        assert name in allowed, "semantic or other artifact opened before metadata rejection"
        return original_get(self, name, expected)
    monkeypatch.setattr(probe.Snapshots, "get", metadata_only)
    monkeypatch.setattr(probe, "common", lambda *a: pytest.fail("advanced past invalid review metadata"))
    expected_error = WorkerError if defect == "invalid-json" else (ValueError, FileNotFoundError)
    with pytest.raises(expected_error):
        probe.check(plan_name, "calibration", root=tmp_path)


@pytest.mark.parametrize("size", [32, 128])
def test_review_metadata_seed_inclusive_boundaries(review_registration, tmp_path, size):
    for entry in review_registration["audit"].values():
        entry["seed"]["sha256"] = write(tmp_path / entry["seed"]["file"], b"s" * size)
    probe.validate_review_metadata(review_registration, probe.Snapshots(tmp_path))


@pytest.mark.parametrize("role", ["seed", "attestation"])
def test_review_metadata_drift_after_check_stops_before_service(world, role):
    prepared = probe.check(world.plan_name, "calibration", root=world.root)
    for phase in probe.COUNTS:
        target = world.root / world.plan["audit"][phase][role]["file"]
        original = target.read_bytes()
        write(target, b"altered after successful check")
        with pytest.raises(ValueError, match="hash_changed"):
            probe.run(prepared, factory=lambda *a: pytest.fail("service started after metadata drift"))
        write(target, original)
    assert len(world.transport.dispatched) == 4  # Only fixture resource calls.


@pytest.mark.parametrize("role", ["seed", "attestation"])
def test_review_metadata_between_stage_drift_blocks_second_post(world, role):
    target = world.root / world.plan["audit"]["validation"][role]["file"]
    def mutate(_result, observer):
        assert observer.current["stage"] == 1
        write(target, b"altered between stages")
    world.transport.mutate = mutate
    report = run_phase(world)
    assert report["status"] == "failed" and report["sources_unchanged"] is False
    assert report["actual_native_posts"] == 1 and len(report["calls"]) == 1
    assert report["calls"][0]["stage"] == 1 and "raw_response" in report["calls"][0]
    assert len(world.transport.dispatched) == 5 and all(p.stopped for p in world.transport.processes)
