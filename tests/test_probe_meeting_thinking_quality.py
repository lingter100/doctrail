"""Single-call C4 runner integration over a synthetic HTTP transport and sources."""
import copy
import json
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_thinking_quality import QualityThinkingGenerator
from doctrail.meeting_thinking_transport import GGUF_SHA256, PROTOCOL
from scripts import prepare_meeting_thinking_inputs as prep
from scripts import probe_meeting_thinking_quality as probe
from tests.test_meeting_thinking_compat_resources import clean_metrics
from tests.test_meeting_thinking_quality import PROMPT, response
from tests.test_meeting_thinking_review import attestation
from tests.test_prepare_meeting_thinking_inputs import material as material_fixture
from tests.test_prepare_meeting_thinking_inputs import reference, write
from tests.test_prepare_meeting_thinking_inputs import run as prepare_run

material = material_fixture


@pytest.fixture
def world(material, monkeypatch):
    cal = material()
    assert prepare_run(cal)["status"] == "passed"
    val = material("validation")
    assert prepare_run(val)["status"] == "passed"
    root = cal.root
    plan = {"schema_version": 1, "candidate": probe.CANDIDATE_ID, "phases": {}, "audit": {},
        "excluded_roles": sorted(probe.EXCLUDED | {"source-writer", "source-reviewer", "writer", "item-reviewer"}),
        "bound_files": cal.code, "code_freeze": reference(root, prep.TOOLCHAIN_FREEZE), "protocol_sha256": prep.PINNED[prep.PROTOCOL]}
    for data in (cal, val):
        phase = data.phase
        output = f".local/meetings-c4-{phase}-prepared-v1"
        plan["phases"][phase] = data.refs | {"input": reference(root, output + "/input.json"),
            "preparation_receipt": reference(root, output + "/receipt.json"),
            "case_ids": [c["id"] for c in data.draft["cases"]], "output_dir": f".local/meetings-c4-quality-{phase}-v1"}
        prefix = f"data/evaluation/meetings-c4-review-metadata-v1/{phase}"
        write(root / prefix / "seed.bin", phase.encode() * 8)
        write(root / prefix / "attestation.json", attestation("judge-" + phase))
        plan["audit"][phase] = {"reviewer_id": "judge-" + phase, "seed": reference(root, prefix + "/seed.bin"),
            "attestation": reference(root, prefix + "/attestation.json"), "output_dir": f".local/meetings-c4-audit-{phase}-v1"}
    write(root / probe.PLAN, plan)
    write(root / prep.RESOURCE_REPORT, {"identity": {"generation_protocol": PROTOCOL}})
    observed = SimpleNamespace(posts=0, services=0, fail_at=None, alter=None, emitted=0, after_request=None, results={})
    @contextmanager
    def factory(*, telemetry, **kwargs):
        observed.services += 1
        yield SimpleNamespace(process=object(), url="http://127.0.0.1:12345", token="x" * 40, manifest="unused",
            cleanup=telemetry, drain=SimpleNamespace(emitted_bytes=0, read_errors=0))
    def cleanup(process, drain, metrics):
        metrics.update(clean_metrics())
        metrics["drain"]["emitted_bytes"] = observed.emitted
    @contextmanager
    def watchdog(process, metrics, seconds=90):
        metrics.update(watchdog_fired=False, watchdog_joined=True)
        yield
    @contextmanager
    def memory(process, metrics):
        metrics.update(native_rss_sample_count=1, native_rss_max_sample_mib=1, memory_scope="synthetic")
        yield
    monkeypatch.setattr(probe, "cleanup_owned", cleanup)
    monkeypatch.setattr(probe, "owned_watchdog", watchdog)
    monkeypatch.setattr(probe, "rss_samples", memory)
    class Generator(QualityThinkingGenerator):
        def __init__(self, *args):
            super().__init__(*args, transport=httpx.MockTransport(self.handler))
        def load(self):
            self._metadata, self._alias = {"generation_protocol": PROTOCOL}, GGUF_SHA256
            return self
        def answer(self, request, language, **kwargs):
            self.language = language
            self.case = next(c for d in (cal, val) for c in d.draft["cases"] if c["payload"] == request and c["response_language"] == language)
            # Shared payloads are intentional; select the next registered case by phase progress.
            phase = "validation" if observed.posts >= 6 else "calibration"
            index = observed.posts - (6 if phase == "validation" else 0)
            self.case = (val if phase == "validation" else cal).draft["cases"][index]
            result = super().answer(request, language, **kwargs)
            if observed.after_request:
                observed.after_request()
            return result
        def handler(self, request):
            body = json.loads(request.content)
            if request.url.path == "/apply-template":
                return httpx.Response(200, json={"prompt": PROMPT})
            if request.url.path == "/tokenize":
                return httpx.Response(200, json={"tokens": list(range(100 if body["parse_special"] else 30))})
            phase = "validation" if observed.posts >= 6 else "calibration"
            persisted = json.loads((root / f".local/meetings-c4-quality-{phase}-v1/report.json").read_bytes())
            assert persisted["calls"][-1]["dispatch_started"] is True and persisted["calls"][-1]["http_send_attempts"] == 0
            events = sorted((root / f".local/meetings-c4-quality-{phase}-v1/trace").glob("*.json"))
            assert json.loads(events[-1].read_bytes())["key"] == "native_post_started"
            observed.posts += 1
            if observed.posts == observed.fail_at:
                return httpx.Response(503, text="PRIVATE unavailable")
            oracle = next(o for d in (cal, val) for o in d.oracle["cases"] if o["id"] == self.case["id"])
            content = {"status": oracle["expected_status"], "claims": []}
            if content["status"] == "answered":
                content["claims"] = [{"evidence_ids": [0, 1, 2], "text": "합성 답입니다." if self.language == "ko" else "Synthetic answer."}]
            raw = response(json.dumps(content, ensure_ascii=False))
            if observed.alter:
                observed.alter(raw)
            return httpx.Response(200, json=raw)
    return SimpleNamespace(root=root, cal=cal, val=val, plan=plan, git=cal.git, observed=observed,
                           factory=factory, generator_factory=Generator)


def run(world, phase="calibration"):
    prepared = probe.check(phase, root=world.root, git=world.git)
    return probe.run(prepared, factory=world.factory, generator_factory=world.generator_factory)


def test_calibration_single_call_six_native_and_full_replay(world):
    result = run(world)
    assert result["status"] == "completed", result.get("error")
    assert world.observed.posts == 6 and result["http_send_attempts"] == 6 and world.observed.services == 2
    prepared = probe.check("calibration", root=world.root, git=world.git)
    assert len(probe.report_replay(prepared, result)) == 6
    with pytest.raises(FileExistsError):
        run(world)


def test_transport_failure_preserves_attempt_raw_availability_and_closes(world):
    world.observed.fail_at = 2
    result = run(world)
    assert result["status"] == "failed_closed" and world.observed.posts == 2 and world.observed.services == 1
    assert len(result["unexecuted"]) == 4 and result["calls"][-1]["native_error"]["body_available"] is False
    assert "PRIVATE" not in json.dumps(result)
    assert result["first_failure"]["code"] == result["calls"][-1]["native_error"]["code"]
    assert result["first_failure"]["type"] == "GenerationError"
    assert result["calls"][-1]["request_seconds"] > 0
    assert result["native_responses_received"] == 1 and result["contract_valid_answers"] == 1
    with pytest.raises(ValueError, match="report_not_complete"):
        probe.report_replay(probe.check("calibration", root=world.root, git=world.git), result)


def test_structural_failure_preserves_original_response_no_second_call(world):
    world.observed.alter = lambda raw: raw["choices"][0].update(finish_reason="length")
    result = run(world)
    assert result["status"] == "failed_closed" and world.observed.posts == 1 and len(result["unexecuted"]) == 5
    assert "response" in result["calls"][0]
    assert result["first_failure"]["code"] == "generation_stop_mismatch"
    assert result["calls"][0]["request_seconds"] > 0
    assert result["native_responses_received"] == 1 and result["contract_valid_answers"] == 0


@pytest.mark.parametrize("phase", list(probe.COUNTS))
@pytest.mark.parametrize("role", ["seed", "attestation"])
def test_review_metadata_drift_before_body(world, phase, role, monkeypatch):
    write(world.root / world.plan["audit"][phase][role]["file"], b"drift")
    monkeypatch.setattr(prep, "load_material", lambda *a, **k: pytest.fail("semantic source opened"))
    with pytest.raises(ValueError, match="hash_changed"):
        probe.check("calibration", root=world.root, git=world.git)
    assert world.observed.posts == 0


def test_invalid_review_path_rejected_before_any_reference_read(world, monkeypatch):
    world.plan["audit"]["validation"]["attestation"] = world.plan["phases"]["validation"]["oracle"]
    write(world.root / probe.PLAN, world.plan)
    original = prep.Snapshots.get
    def spy(self, name, expected=None):
        assert name == probe.PLAN
        return original(self, name, expected)
    monkeypatch.setattr(prep.Snapshots, "get", spy)
    with pytest.raises(ValueError, match="review_metadata_path"):
        probe.check("calibration", root=world.root, git=world.git)


def test_between_requests_attestation_drift_prevents_next_dispatch(world):
    target = world.root / world.plan["audit"]["validation"]["attestation"]["file"]
    world.observed.after_request = lambda: write(target, b"changed after first response")
    result = run(world)
    assert result["status"] == "failed_closed" and world.observed.posts == 1 and world.observed.services == 1


def test_validation_gate_failure_happens_before_validation_bytes(world, monkeypatch):
    original = prep.Snapshots.get
    def spy(self, name, expected=None):
        assert "validation" not in name, "held-out bytes opened before calibration gate"
        return original(self, name, expected)
    monkeypatch.setattr(prep.Snapshots, "get", spy)
    with pytest.raises(FileNotFoundError):
        probe.check("validation", root=world.root, git=world.git)


def test_native_drain_failure_cannot_be_success(world):
    world.observed.emitted = 1
    result = run(world)
    assert result["status"] == "failed_closed" and result["cleanup"][0]["drain"]["emitted_bytes"] == 1
    assert world.observed.services == 1


def test_replay_tampered_final_reasoning_input_and_count(world):
    result = run(world)
    assert result["status"] == "completed"
    prepared = probe.check("calibration", root=world.root, git=world.git)
    changes = [lambda r: r["calls"][0]["result"]["answer"]["claims"][0].update(text="forged"),
               lambda r: r["calls"][0]["response"]["choices"][0]["message"].update(reasoning_content="wrong"),
               lambda r: r["calls"][0]["input_token_ids"].__setitem__(0, True),
               lambda r: r.update(http_send_attempts=7), lambda r: r["calls"].reverse(),
               lambda r: r.update(first_failure={"code": "c4_cleanup_or_drain", "type": "ValueError"})]
    for change in changes:
        mutated = copy.deepcopy(result)
        change(mutated)
        with pytest.raises((ValueError, GenerationError)):
            probe.report_replay(prepared, mutated)


def test_immutable_event_hash_order_value_and_extra(world):
    report = run(world)
    assert report["status"] == "completed", report.get("error")
    prepared = probe.check("calibration", root=world.root, git=world.git)
    for mutate in (lambda r: r["calls"][0]["observations"].reverse(),
                   lambda r: r["calls"][0]["observations"].pop(),
                   lambda r: r["calls"][0].update(native_post_started=False)):
        changed = copy.deepcopy(report)
        mutate(changed)
        with pytest.raises(ValueError, match="c4_event"):
            probe.observation_replay(prepared, changed)
    first = report["calls"][0]["observations"][0]
    target = world.root / first["file"]
    original = target.read_bytes()
    target.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="hash_changed"):
        probe.observation_replay(prepared, report)
    target.write_bytes(original)
    write(world.root / prepared["output"] / "trace/999999.json", {})
    with pytest.raises(ValueError, match="event_extra"):
        probe.observation_replay(prepared, report)


def test_unique_atomic_temp_preserves_stale_and_reports_original_failure(tmp_path, monkeypatch):
    write(tmp_path / "report.json.tmp", b"prior failure evidence")
    prep.replace("report.json", {"ok": True}, tmp_path)
    assert (tmp_path / "report.json.tmp").read_bytes() == b"prior failure evidence"
    def denied(*args):
        raise PermissionError("private filesystem detail")
    monkeypatch.setattr(prep.os, "replace", denied)
    with pytest.raises(PermissionError):
        prep.replace("report.json", {}, tmp_path)
    assert len(list(tmp_path.glob("report.json.*.tmp"))) == 1


def test_event_archival_failure_blocks_transport_preserves_reservation(world, monkeypatch):
    original = prep.write_new
    def fail_event(name, value, root=prep.ROOT):
        if "/trace/" in name and b'"native_post_started"' in value:
            raise PermissionError("private path detail")
        return original(name, value, root)
    monkeypatch.setattr(prep, "write_new", fail_event)
    report = run(world)
    assert report["status"] == "failed_closed" and world.observed.posts == 0
    assert len(report["ledger"]) == 1 and report["calls"][0]["dispatch_started"] is True
    assert report["first_failure"]["type"] == "PermissionError"
    assert "private path" not in json.dumps(report)


def test_final_save_failure_keeps_original_generation_failure(world, monkeypatch):
    world.observed.fail_at = 1
    original = prep.replace
    def fail_final(name, value, root=prep.ROOT):
        if name.endswith("report.json") and value["status"] == "failed_closed":
            raise PermissionError("private path detail")
        return original(name, value, root)
    monkeypatch.setattr(prep, "replace", fail_final)
    report = run(world)
    assert report["first_failure"]["type"] == "GenerationError"
    assert report["final_save_failure"]["type"] == "PermissionError"
    fallback = world.root / world.plan["phases"]["calibration"]["output_dir"] / "failed-final-save.json"
    assert json.loads(fallback.read_bytes()) == report and world.observed.posts == 1


def test_transport_error_precedes_failure_to_archive_error_event(world, monkeypatch):
    world.observed.fail_at = 1
    original = prep.write_new
    def fail_error_event(name, value, root=prep.ROOT):
        if "/trace/" in name and b'"native_error"' in value:
            raise PermissionError("private path")
        return original(name, value, root)
    monkeypatch.setattr(prep, "write_new", fail_error_event)
    report = run(world)
    assert report["status"] == "failed_closed" and world.observed.posts == 1
    assert report["first_failure"]["type"] == "GenerationError"
    assert report["first_failure"]["code"] != "quality_failed_closed"
    assert report["calls"][0]["archival_failure"]["type"] == "PermissionError"


def test_aborted_deadline_precedes_archive_failure_and_sends_zero(world, monkeypatch):
    original = prep.write_new
    def fail_abort(name, value, root=prep.ROOT):
        if "/trace/" in name and b'"native_post_aborted"' in value:
            raise PermissionError("private path")
        return original(name, value, root)
    monkeypatch.setattr(prep, "write_new", fail_abort)
    class Aborted(world.generator_factory):
        def answer(self, request, language, *, before_dispatch, observe):
            built = probe.prepare_answer(request, language)
            before_dispatch(PROMPT, list(range(100)), probe.request_body(built.messages, built.schema))
            observe("native_post_started", True)
            observe("native_post_aborted", {"code": "generation_deadline_exceeded"})
            raise GenerationError("generation_deadline_exceeded")
    world.generator_factory = Aborted
    report = run(world)
    assert report["status"] == "failed_closed" and world.observed.posts == 0
    assert report["http_send_attempts"] == 0 and len(report["ledger"]) == 1
    assert report["first_failure"] == {"type": "GenerationError", "code": "generation_deadline_exceeded"}
    assert report["calls"][0]["archival_failure"]["type"] == "PermissionError"
