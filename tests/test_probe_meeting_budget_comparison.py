"""Only newly authored synthetic fixtures and fake transport; no model or pool reads."""
import copy
import hashlib
import json
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace

import pytest

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_answer_blocks import (
    answer_messages_blocks,
    build_block_catalog,
    grounded_answer_blocks,
)
from doctrail.meeting_answer_spans import (
    answer_messages_spans,
    build_span_catalog,
    grounded_answer_spans,
    span_answer_grammar,
)
from doctrail.meeting_contract import AnswerRequest
from doctrail.meeting_gguf import GREEDY, GGUFResult
from doctrail.meeting_qwen35 import GGUF_SHA256, MODEL_ID, MODEL_REVISION, PREAMBLE_SHA256
from scripts import probe_meeting_budget_comparison as probe


def metadata():
    return {"repo_id": MODEL_ID, "revision": "gguf-sha256:" + GGUF_SHA256,
        "original_revision": MODEL_REVISION, "artifact": {"sha256": GGUF_SHA256},
        "generation_protocol": probe.CANDIDATE, "runtime": {"backend": "llama.cpp",
            "context_tokens": 6144, "max_input_tokens": 5120, "max_new_tokens": 384,
            "deadline_seconds": 90}, "nonthinking": {"enable_thinking_requested": False,
            "assistant_preamble_sha256": PREAMBLE_SHA256,
            "policy": "qwen35-terminal-assistant-preamble-v1", "last_template_verified": False,
            "verification_scope": "terminal_assistant_preamble_per_prompt"}}


def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resource_fixture(bindings, protocol_sha):
    text = "The synthetic marker is mint.\n\n"
    payload = {"schema_version": 1, "query": "What color is the synthetic marker?", "contexts": [{
        "document_id": "fresh-neutral", "revision": 1, "chunk_id": "fresh-neutral-0",
        "title": "Synthetic", "meeting_date": None, "page": None,
        "start_offset": 0, "end_offset": len(text), "text": text}]}
    registration = {"schema_version": 1, "candidate": probe.RESOURCE_CANDIDATE,
        "protocol_sha256": protocol_sha, "limits": probe.RESOURCE_LIMITS,
        "bound_files": bindings, "stress_grammar": 'root ::= ("z "){600}\n',
        "normal_expected_terms": ["mint"], "runtime_receipt_sha256": probe.fingerprint({"synthetic_runtime": True}),
        "tokenizer": {"synthetic_tokenizer": True},
        "cases": [{"id": kind, "payload": copy.deepcopy(payload),
                   "official_input_tokens": {"L0": count, "C2": count}}
                  for kind, count in (("normal", 200), ("stress", 5000))]}
    report = {"candidate": probe.RESOURCE_CANDIDATE, "protocol_sha256": protocol_sha,
        "fixture_sha256": probe.fingerprint(registration["cases"]), "limits": probe.RESOURCE_LIMITS,
        "bound_files": bindings, "status": "completed_resource_only", "readiness_passed": True,
        "sources_unchanged": True, "processes_stopped": True, "metadata_recovery": True,
        "cleanup_within_service_budget": True, "native_log_bytes": 0, "recovery_generation_calls": 0,
        "paid_calls": 0, "warmup_calls": 0, "retries": 0, "elapsed_seconds": 1,
        "owned_cleanup_ms": 1, "last_request_through_cleanup_ms": 1,
        "recovery_cleanup_ms": 1, "human_review_count": 0, "model_quality_evaluated": False,
        "unexecuted": [],
        "model_runtime": metadata(), "recovered_identity": metadata(), "calls": [], "results": []}
    for sequence, (kind, arm) in enumerate(probe.RESOURCE_ORDER):
        req = AnswerRequest.model_validate(payload)
        cf, pf, mapper = ((build_span_catalog, answer_messages_spans, grounded_answer_spans)
            if arm == "L0" else (build_block_catalog, answer_messages_blocks, grounded_answer_blocks))
        catalog = cf(req.contexts)
        grammar = span_answer_grammar(catalog) if kind == "normal" else registration["stress_grammar"]
        n, out = (200, 30) if kind == "normal" else (5000, 384)
        config = {**GREEDY, "n_predict": 384, "grammar": grammar}
        text = json.dumps({"status": "answered", "claims": [{"evidence_ids": [0],
            "text": "The synthetic marker is mint."}]}) if kind == "normal" else "z " * 384
        payload_native = {**config, "prompt": [7] * n, "cache_prompt": False, "return_tokens": True}
        raw = {"content": text, "model": GGUF_SHA256, "generation_settings": config,
            "stop": True, "truncated": False, "stop_type": "eos" if kind == "normal" else "limit",
            "tokens_evaluated": n, "tokens_predicted": out,
            "timings": {"cache_n": 0, "prompt_n": n, "predicted_n": out - 1,
                        "prompt_ms": 0., "predicted_ms": 0.}}
        report["calls"].append({"id": f"{kind}-{arm}", "case_id": kind, "arm": arm,
            "sequence": sequence, "dispatch_attempted": True, "payload": payload_native, "raw_response": raw})
        row = {"id": f"{kind}-{arm}", "case_id": kind, "arm": arm, "passed": True,
            "input_tokens": n, "official_input_tokens": n, "output_tokens": out,
            "finish_reason": "eos" if kind == "normal" else "length", "elapsed_seconds": 0.,
            "prompt_sha256": probe.fingerprint(pf(req.query, catalog)),
            "grammar_sha256": hashlib.sha256(grammar.encode()).hexdigest(),
            "watchdog_fired": False, "watchdog_joined": True,
            "memory": {"sample_count": 1, "sampler_joined": True},
            "effective_config": {"backend": "llama.cpp", **config, "cache_prompt_requested": False,
                "observed_cache_tokens": 0, "observed_nonthinking_preamble_sha256": PREAMBLE_SHA256,
                "enable_thinking_requested": False}}
        if kind == "normal":
            row["response"] = mapper(text, catalog, req.contexts, "en")
        report["results"].append(row)
    return registration, report


def install_contract(root, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", root)
    monkeypatch.setattr(probe, "FILES", {"synthetic.py", "protocol.json", "old-freeze.json"})
    monkeypatch.setattr(probe, "PREPARATION_FILES", {"synthetic.py"})
    monkeypatch.setattr(probe, "PROTOCOL_FILE", "protocol.json")
    monkeypatch.setattr(probe, "LEGACY_FREEZES", ("old-freeze.json",))
    monkeypatch.setattr(probe, "ORACLE_PATHS", {"calibration": "oracle.json", "validation": "sealed-oracle.json"})
    monkeypatch.setattr(probe, "PHASE_PATHS", {p: (f"{p}-draft.json", f"{p}-item-freeze.json")
                                             for p in probe.COUNTS})
    (root / "synthetic.py").write_text("# newly synthetic source\n")
    write(root / "old-freeze.json", {"bound_files": {"synthetic.py": hash_file(root / "synthetic.py")}})
    write(root / "protocol.json", {"supersedes_for_execution_only": "meeting-answer-blocks-c2-comparison-v1",
        "bound_files": {"old-freeze.json": hash_file(root / "old-freeze.json")}})
    protocol_sha = hash_file(root / "protocol.json")
    monkeypatch.setattr(probe, "PROTOCOL_SHA256", protocol_sha)
    bindings = {name: hash_file(root / name) for name in probe.FILES}
    write(root / "source-freeze.json", {"bound_files": bindings})
    registration, report = resource_fixture(bindings, protocol_sha)
    write(root / "resource-plan.json", registration)
    report["plan_sha256"] = hash_file(root / "resource-plan.json")
    write(root / "resource.json", report)
    return {"bound_files": bindings, "protocol_sha256": protocol_sha,
        "protocol_deviation": probe.DEVIATION,
        "supersedes_for_execution_only": "meeting-answer-blocks-c2-comparison-v1",
        "source_freeze": {"file": "source-freeze.json", "sha256": hash_file(root / "source-freeze.json")},
        "resource_report": {"file": "resource.json", "sha256": hash_file(root / "resource.json")},
        "resource_plan": {"file": "resource-plan.json", "sha256": hash_file(root / "resource-plan.json")}}


def seal_synthetic_protocol(plan, root, monkeypatch):
    """Seal fake metadata only, before constructing any synthetic generation report."""
    protocol = json.loads((root / probe.PROTOCOL_FILE).read_text())
    for phase, spec in plan["phases"].items():
        protocol["bound_files"][probe.ORACLE_PATHS[phase]] = spec["oracle_sha256"]
        protocol["bound_files"].update({name: "d" * 64 for name in probe.PHASE_PATHS[phase]})
    write(root / probe.PROTOCOL_FILE, protocol)
    sha = hash_file(root / probe.PROTOCOL_FILE)
    monkeypatch.setattr(probe, "PROTOCOL_SHA256", sha)
    plan["protocol_sha256"] = sha
    plan["bound_files"][probe.PROTOCOL_FILE] = sha
    write(root / "source-freeze.json", {"bound_files": plan["bound_files"]})
    plan["source_freeze"]["sha256"] = hash_file(root / "source-freeze.json")
    registration, report = resource_fixture(plan["bound_files"], sha)
    write(root / "resource-plan.json", registration)
    plan["resource_plan"]["sha256"] = report["plan_sha256"] = hash_file(root / "resource-plan.json")
    write(root / "resource.json", report)
    plan["resource_report"]["sha256"] = hash_file(root / "resource.json")


def preparation_fixture(plan, phase, cases, root):
    spec = plan["phases"][phase]
    rows = []
    for c in cases:
        request = AnswerRequest.model_validate(c["payload"])
        row = {"id": c["id"], "payload_sha256": probe.fingerprint(c["payload"]),
               "payload_preserved": True, "arms": {}}
        for arm, cf, pf in (("L0", build_span_catalog, answer_messages_spans),
                           ("C2", build_block_catalog, answer_messages_blocks)):
            catalog = cf(request.contexts); n = c["official_input_tokens"][arm]
            row["arms"][arm] = {"official_input_tokens": n, "error_code": None,
                "old_4096_pass": n <= 4096, "new_5120_pass": n <= 5120,
                "prompt_sha256": probe.fingerprint(pf(request.query, catalog)),
                "grammar_sha256": hashlib.sha256(span_answer_grammar(catalog).encode()).hexdigest()}
        rows.append(row)
    receipt = {"candidate": probe.CANDIDATE, "phase": phase, "status": "passed",
        "payloads_preserved": True, "input_sha256": spec["input_sha256"],
        "protocol_deviation": probe.DEVIATION, "referenced_body_oracle_bytes_rechecked": False,
        "errors": [], "model_calls": 0, "native_calls": 0, "downloads": 0,
        "tokenizer": plan["tokenizer"], "cases": rows, "bound_files": plan["bound_files"],
        "snapshots": {plan["source_freeze"]["file"]: {"sha256": plan["source_freeze"]["sha256"]},
            probe.PROTOCOL_FILE: {"sha256": probe.PROTOCOL_SHA256},
            **{name: {"sha256": "d" * 64} for name in probe.PHASE_PATHS[phase]}},
        "summary": {"total_arms": len(cases) * 2, "measured_arms": len(cases) * 2,
            "unknown_arms": 0, "failed_arms": 0, "new_5120_pass": len(cases) * 2, "new_5120_fail": 0}}
    path = root / f".local/{phase}-preparation.json"
    write(path, receipt)
    spec["preparation_receipt"] = {"file": path.relative_to(root).as_posix(), "sha256": hash_file(path)}
    return receipt


@pytest.mark.parametrize("phase", ["calibration", "validation"])
@pytest.mark.parametrize("field", ["oracle_file", "oracle_sha256"])
def test_original_oracle_metadata_cannot_be_replaced(source, phase, field):
    source.plan["phases"][phase][field] = "other-oracle.json" if field == "oracle_file" else "f" * 64
    with pytest.raises(ValueError, match="original_oracle_binding"):
        probe.verify_source_contract(source.plan, source.root)


@pytest.mark.parametrize("binding", ["draft", "item", "protocol"])
def test_original_preparation_snapshot_cannot_be_replaced(source, binding):
    receipt = json.loads((source.root / ".local/calibration-preparation.json").read_text())
    key = (probe.PROTOCOL_FILE if binding == "protocol" else
           probe.PHASE_PATHS["calibration"][0 if binding == "draft" else 1])
    receipt["snapshots"][key]["sha256"] = "f" * 64
    with pytest.raises(ValueError, match="original_preparation_binding"):
        probe.validate_preparation_receipt(source.plan, "calibration", receipt)


def test_preparation_receipt_changed_during_run_stops_next_dispatch(source):
    def change_receipt(base, payload, deadline):
        (source.root / ".local/calibration-preparation.json").write_bytes(b"{}")
    report, processes, base = run(source, Base(change_receipt))
    assert base.calls == len(report["calls"]) == 1
    assert not report["resources_passed"] and report["status"] == "failed"
    assert processes[0].stopped and len(report["unexecuted"]) == 15


class Process:
    def __init__(self):
        self.stopped = False

    def poll(self):
        return 0 if self.stopped else None

    def kill(self):
        self.stopped = True

    def wait(self, timeout):
        assert timeout <= 5
        return 0


class Base:
    def __init__(self, effect=None):
        self.effect, self.closed, self.last_effective_config = effect, False, None
        self.calls = 0
        self.text = json.dumps({"status": "answered", "claims": [{"evidence_ids": [0],
            "text": "The synthetic marker is mint."}]})
        self.output_tokens = 30
        self.dispatch_error = None

    def public_metadata(self):
        return metadata()

    def begin_request(self, deadline):
        self.last_effective_config = None

    def end_request(self):
        pass

    def count_tokens(self, messages):
        return 200

    def _request(self, method, path, payload=None, deadline=None):
        assert method == "POST" and path == "/completion"
        def dispatch():
            self.calls += 1
            if self.dispatch_error:
                self.dispatch_error()
            return {"content": self.text, "model": GGUF_SHA256,
                "generation_settings": {k: payload[k] for k in (*GREEDY, "n_predict", "grammar")},
                "stop": True, "stop_type": "eos", "truncated": False,
                "tokens_evaluated": 200, "tokens_predicted": self.output_tokens,
                "timings": {"cache_n": 0, "prompt_n": 200, "predicted_n": 29,
                            "prompt_ms": 0., "predicted_ms": 0.}}
        return self.observer.request(dispatch, method, path, payload, deadline)

    def _complete(self, messages, deadline, token_limit, grammar=""):
        deadline = self.observer.before_complete(messages, deadline, token_limit, grammar)
        payload = {**GREEDY, "n_predict": token_limit, "grammar": grammar,
                   "prompt": [7] * 200, "cache_prompt": False, "return_tokens": True}
        raw = self._request("POST", "/completion", payload, deadline)
        self.last_effective_config = {"backend": "llama.cpp", **GREEDY,
            "n_predict": token_limit, "grammar": grammar, "cache_prompt_requested": False,
            "observed_cache_tokens": 0, "observed_nonthinking_preamble_sha256": PREAMBLE_SHA256,
            "enable_thinking_requested": False}
        if self.effect:
            self.effect(self, payload, deadline)
        return GGUFResult(self.text, "eos", 200, self.output_tokens, 0.,
            {"native_timings": raw["timings"]})

    def close(self):
        self.closed = True


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def source(tmp_path, monkeypatch):
    contract = install_contract(tmp_path, monkeypatch)
    monkeypatch.setattr(probe, "rss_samples", lambda *args: nullcontext())
    payload = {"schema_version": 1, "query": "What is the synthetic marker?", "contexts": [{
        "document_id": "synthetic-doc", "revision": 1, "chunk_id": "synthetic-chunk",
        "title": "Synthetic marker", "meeting_date": None, "page": None,
        "start_offset": 0, "end_offset": 31, "text": "The synthetic marker is mint.\n\n"}]}
    cases = [{"id": f"c-{i}", "payload": copy.deepcopy(payload),
              "official_input_tokens": {"L0": 200, "C2": 200}} for i in range(8)]
    write(tmp_path / "input.json", {"schema_version": 1, "phase": "calibration", "cases": cases})
    plan = {"schema_version": 1, "candidate": probe.CANDIDATE, "limits": copy.deepcopy(probe.LIMITS),
        **contract,
        "runtime_receipt_sha256": probe.fingerprint({"synthetic_runtime": True}),
        "audit": {"calibration": {"seed_sha256": "a" * 64, "reviewer_id": "synthetic-reviewer-cal", "seed_file": ".local/cal.seed", "output_dir": ".local/cal-audit"},
                  "validation": {"seed_sha256": "b" * 64, "reviewer_id": "synthetic-reviewer-val", "seed_file": ".local/val.seed", "output_dir": ".local/val-audit"}},
        "excluded_reviewer_ids": ["synthetic-author", *sorted(probe.REQUIRED_EXCLUDED)],
        "tokenizer": {"synthetic_tokenizer": True}, "phases": {
            "calibration": {"case_ids": [c["id"] for c in cases], "input_file": "input.json", "oracle_file": "oracle.json",
                "input_sha256": probe.snapshot(tmp_path / "input.json")[1], "oracle_sha256": "1" * 64,
                "output_dir": ".local/calibration"},
            "validation": {"case_ids": [f"v-{i}" for i in range(12)],
                "input_file": "sealed-not-present.json", "oracle_file": "sealed-oracle.json", "input_sha256": "2" * 64,
                "oracle_sha256": "3" * 64, "output_dir": ".local/validation",
                "preparation_receipt": {"file": ".local/validation-preparation.json", "sha256": "a" * 64}}}}
    seal_synthetic_protocol(plan, tmp_path, monkeypatch)
    preparation_fixture(plan, "calibration", cases, tmp_path)
    path = tmp_path / "plan.json"
    write(path, plan)
    return SimpleNamespace(root=tmp_path, path=path, plan=plan, cases=cases)


def prepare(source, phase="calibration", gate=None):
    return probe.prepare(source.path, phase, gate,
        loader=lambda download: (None, {"synthetic_tokenizer": True}), counter=lambda *_: 200)


def launch():
    processes = []

    @contextmanager
    def factory(*args):
        process = Process()
        processes.append(process)
        try:
            yield SimpleNamespace(process=process, receipt={"synthetic_runtime": True})
        finally:
            process.kill()
    return factory, processes


def run(source, base=None):
    factory, processes = launch()
    base = base or Base()
    def base_factory(_, observer):
        base.observer = observer
        return base
    return probe.run(prepare(source), factory, base_factory), processes, base


def test_two_arm_alternating_all_sixteen_dispatches_and_raw_evidence(source):
    report, processes, base = run(source)
    assert report["resources_passed"] and report["status"] == "completed_not_semantically_verified"
    assert not report["semantics_verified"] and report["human_review_count"] == 0
    assert len(report["results"]) == len(report["calls"]) == base.calls == 16
    assert len(processes) == 1 and processes[0].stopped and base.closed
    assert [(c["id"], c["arm"]) for c in report["calls"]] == probe.schedule(
        "calibration", source.plan["phases"]["calibration"]["case_ids"])
    assert [r["arm"] for r in report["results"][:4]] == ["L0", "C2", "C2", "L0"]
    assert not report["unexecuted"] and report["sources_unchanged"]
    assert all(json.loads(c["raw_response"]["content"])["status"] == "answered" for c in report["calls"])
    for i in range(0, 16, 2):
        assert report["results"][i]["payload_sha256"] == report["results"][i + 1]["payload_sha256"]
    with pytest.raises(ValueError, match="output_exists"):
        prepare(source)


def test_native_failure_persists_dispatch_before_post_and_never_continues(source):
    base = Base()

    def fail(*args):
        report = json.loads((source.root / ".local/calibration/report.json").read_text())
        assert len(report["calls"]) == 1 and report["calls"][0]["dispatch_attempted"]
        raise GenerationError("generation_deadline_exceeded")
    base.dispatch_error = fail
    report, processes, base = run(source, base)
    assert report["failure"] == "generation_deadline_exceeded"
    assert report["calls"][0]["error"] == "generation_deadline_exceeded"
    assert len(report["calls"]) == len(report["results"]) == 1
    assert len(report["unexecuted"]) == 15 and not report["resources_passed"]
    assert processes[0].stopped and base.closed


def test_duplicate_dispatch_rejected_and_source_changes_stop_before_next_case(source):
    def duplicate(base, payload, deadline):
        base._request("POST", "/completion", payload, deadline)
    report, _, base = run(source, Base(duplicate))
    assert base.calls == 1 and len(report["calls"]) == 1 and not report["resources_passed"]


def test_source_change_during_call_is_preserved_and_stops(source):
    def change(*args):
        (source.root / "synthetic.py").write_text("# changed\n")
    report, _, base = run(source, Base(change))
    assert base.calls == 1 and not report["sources_unchanged"]
    assert report["failure"] == report["source_error"] == "comparison_source_changed"
    assert len(report["unexecuted"]) == 15


@pytest.mark.parametrize("field,value", [("n_predict", 385), ("seed", 4),
    ("cache_prompt_requested", True), ("observed_cache_tokens", 1),
    ("enable_thinking_requested", True), ("observed_nonthinking_preamble_sha256", "bad")])
def test_effective_configuration_drift_is_fatal(source, field, value):
    def change(base, *args):
        base.last_effective_config[field] = value
    report, _, base = run(source, Base(change))
    assert base.calls == 1 and not report["resources_passed"]
    assert report["failure"] == "comparison_row_integrity"


@pytest.mark.parametrize("change", [lambda p: p.update(schema_version=True),
    lambda p: p["limits"].update(retries=False),
    lambda p: p["phases"]["calibration"].update(output_dir="../outside"),
    lambda p: p["phases"]["validation"].update(output_dir=".local/calibration/nested"),
    lambda p: p["phases"]["calibration"].update(case_ids=["duplicate"] * 8),
    lambda p: p["bound_files"].update(extra="0" * 64)])
def test_unregistered_plan_mutations_rejected(source, change):
    change(source.plan)
    write(source.path, source.plan)
    with pytest.raises(ValueError):
        prepare(source)


def test_calibration_does_not_touch_validation_input(source, monkeypatch):
    original = probe.snapshot

    def guard(path):
        assert str(path).endswith("sealed-not-present.json") is False
        return original(path)
    monkeypatch.setattr(probe, "snapshot", guard)
    assert len(prepare(source)["schedule"]) == 16


def test_validation_gate_failure_precedes_even_input_hash(source, monkeypatch):
    touched = []
    original = probe.snapshot

    def guard(path):
        touched.append(str(path))
        assert not str(path).endswith("sealed-not-present.json")
        return original(path)

    def failed_gate(prepared):
        raise ValueError("synthetic_independent_gate_failed")
    monkeypatch.setattr(probe, "snapshot", guard)
    monkeypatch.setattr(probe, "verify_gate", failed_gate)
    with pytest.raises(ValueError, match="independent_gate_failed"):
        prepare(source, "validation", "locked-gate.json")
    assert str(source.path) in touched


def test_validation_selected_candidate_only_twelve_calls(source, monkeypatch):
    spec = source.plan["phases"]["validation"]
    cases = [dict(copy.deepcopy(source.cases[0]), id=i) for i in spec["case_ids"]]
    path = source.root / spec["input_file"]
    write(path, {"schema_version": 1, "phase": "validation", "cases": cases})
    spec["input_sha256"] = probe.snapshot(path)[1]
    preparation_fixture(source.plan, "validation", cases, source.root)
    write(source.path, source.plan)
    monkeypatch.setattr(probe, "verify_gate", lambda _: {"synthetic_gate": True})
    factory, _ = launch()
    def base_factory(_, observer):
        base = Base(); base.observer = observer
        return base
    report = probe.run(prepare(source, "validation", "gate.json"), factory, base_factory)
    assert report["resources_passed"] and len(report["calls"]) == 12
    assert all(r["arm"] == "C2" for r in report["results"])


def test_once_only_output_claim_survives_startup_failure(source):
    prepared = prepare(source)

    def failure(*args):
        raise RuntimeError("private detail that must not escape")
    report = probe.run(prepared, failure)
    assert report["failure"] == "RuntimeError" and not report["calls"]
    assert len(report["unexecuted"]) == 16
    with pytest.raises(FileExistsError):
        probe.run(prepared, failure)


def test_watchdog_terminates_only_owned_child():
    owned, other, metrics = Process(), Process(), {}
    with probe.watchdog(owned, metrics, seconds=0):
        pass
    assert metrics["watchdog_fired"] and metrics["watchdog_joined"]
    assert owned.stopped and not other.stopped


def test_token_budget_and_tokenizer_identity_fail_before_claim(source):
    with pytest.raises(ValueError, match="token_budget"):
        probe.prepare(source.path, "calibration", loader=lambda _: (None, source.plan["tokenizer"]),
                      counter=lambda *_: 4097)
    with pytest.raises(ValueError, match="tokenizer_changed"):
        probe.prepare(source.path, "calibration", loader=lambda _: (None, {"changed": True}))
    assert not (source.root / ".local/calibration").exists()


def test_truncation_stops_after_single_call(source):
    base = Base()
    original = base._complete

    def truncated(*args):
        output = original(*args)
        return GGUFResult(output.text, "length", 200, 384, output.elapsed_seconds, {})
    base._complete = truncated
    report, _, _ = run(source, base)
    assert len(report["calls"]) == 1 and report["failure"] == "generation_output_truncated"
    assert not report["resources_passed"]


def test_structurally_valid_abstention_remains_unscored_and_does_not_stop(source):
    base = Base()
    base.text = '{"status":"abstained","claims":[]}'
    base.output_tokens = 10
    report, _, _ = run(source, base)
    assert report["resources_passed"] and len(report["calls"]) == 16
    assert all(r["response"]["status"] == "abstained" for r in report["results"])
    assert report["semantics_verified"] is False


def test_runtime_artifact_receipt_drift_prevents_any_generation(source):
    source.plan["runtime_receipt_sha256"] = "a" * 64
    write(source.path, source.plan)
    with pytest.raises(ValueError, match="resource_binding"):
        prepare(source)


def test_missing_dispatch_never_passes(source):
    base = Base()
    original = base._complete

    def no_dispatch(*args):
        dispatch = base._request
        base._request = lambda *args: {"timings": {}}
        try:
            return original(*args)
        finally:
            base._request = dispatch
    base._complete = no_dispatch
    report, _, _ = run(source, base)
    assert report["failure"] == "comparison_row_integrity" and not report["calls"]
    assert len(report["unexecuted"]) == 16


def test_input_mutation_after_preparation_fails_before_claim(source):
    prepared = prepare(source)
    (source.root / "input.json").write_text("{}")
    with pytest.raises(ValueError, match="input_changed"):
        probe.run(prepared)
    assert not prepared["output"].exists()


def test_closed_resource_report_mutation_fails_before_claim(source):
    (source.root / "resource.json").write_text("{}")
    with pytest.raises(ValueError, match="hash_mismatch"):
        prepare(source)
    assert not (source.root / ".local/calibration").exists()


def test_close_failure_invalidates_even_completed_sixteen_rows(source):
    base = Base()

    def fail_close():
        raise RuntimeError("do not print this")
    base.close = fail_close
    report, processes, _ = run(source, base)
    assert len(report["calls"]) == 16 and not report["resources_passed"]
    assert report["failure"] == "RuntimeError" and processes[0].stopped


def test_request_configuration_rejected_before_native_transport(source):
    base = Base()

    def wrong(*args):
        base._request("POST", "/completion", {"prompt": [1], "n_predict": 500})
    base._complete = wrong
    report, _, _ = run(source, base)
    assert base.calls == 0 and not report["calls"] and not report["resources_passed"]


def test_incorrect_claim_text_is_not_automatically_semantically_scored(source):
    base = Base()
    original = base._complete

    def wrong_fact(*args):
        result = original(*args)
        return GGUFResult(json.dumps({"status": "answered", "claims": [{
            "text": "The synthetic marker is purple.", "evidence_ids": [0]}]}),
            "eos", result.input_tokens, result.output_tokens, result.elapsed_seconds, {})
    base._complete = wrong_fact
    report, _, _ = run(source, base)
    assert len(report["calls"]) == 16 and report["resources_passed"]
    assert report["semantics_verified"] is False


@pytest.mark.parametrize("arm", ["L0", "C2"])
@pytest.mark.parametrize("count", [4096, 4097, 5120, 5121, True])
def test_registered_input_budget_boundary_without_models(source, arm, count):
    for case in source.cases:
        case["official_input_tokens"][arm] = count
    write(source.root / "input.json", {"schema_version": 1, "phase": "calibration", "cases": source.cases})
    source.plan["phases"]["calibration"]["input_sha256"] = hash_file(source.root / "input.json")
    preparation_fixture(source.plan, "calibration", source.cases, source.root)
    write(source.path, source.plan)
    counts = iter([c["official_input_tokens"][a] for c in source.cases for a in ("L0", "C2")])
    def execute():
        return probe.prepare(source.path, "calibration",
            loader=lambda _: (None, source.plan["tokenizer"]), counter=lambda *_: next(counts))
    if type(count) is int and count <= 5120:
        result = execute()
        assert result["cases"][source.cases[0]["id"]]["arms"][arm]["official_input_tokens"] == count
    else:
        with pytest.raises(ValueError, match="preparation_receipt"):
            execute()
    assert not (source.root / ".local/calibration").exists()


@pytest.mark.parametrize("change", [
    lambda r: r["calls"].reverse(), lambda r: r["results"].pop(),
    lambda r: r["calls"][0]["raw_response"].update(tokens_evaluated=True),
    lambda r: r["results"][0].update(official_input_tokens=201),
    lambda r: r["results"][2].update(output_tokens=383),
    lambda r: r["results"][0]["effective_config"].update(enable_thinking_requested=True),
    lambda r: r["results"][0]["memory"].update(sample_count=0),
    lambda r: r.update(recovery_cleanup_ms=5001),
    lambda r: r.update(readiness_error="failed"),
])
def test_resource_pass_flag_cannot_hide_invalid_raw_evidence(source, change):
    registration = json.loads((source.root / "resource-plan.json").read_bytes())
    report = json.loads((source.root / "resource.json").read_bytes())
    change(report)
    with pytest.raises(ValueError):
        probe.validate_resource_evidence(report, registration,
            expected_bound_files=source.plan["bound_files"], expected_protocol_sha256=probe.PROTOCOL_SHA256)


def test_native_count_disagreement_rejected_before_persisted_dispatch(source):
    base = Base()
    original = base._request
    def wrong(method, path, payload=None, deadline=None):
        payload = copy.deepcopy(payload)
        payload["prompt"].pop()
        return original(method, path, payload, deadline)
    base._request = wrong
    report, _, base = run(source, base)
    assert not report["calls"] and base.calls == 0 and report["status"] == "failed"


def test_required_designers_and_custodians_cannot_be_registered_as_scorers(source):
    source.plan["excluded_reviewer_ids"].remove("/root/c2_validation_source_b")
    write(source.path, source.plan)
    with pytest.raises(ValueError, match="registration_invalid"):
        prepare(source)
