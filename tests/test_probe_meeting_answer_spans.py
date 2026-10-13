"""Synthetic runner controls only; no native load or sealed dataset access."""
import dataclasses
import json
import time

import pytest

from scripts import probe_meeting_answer_spans as probe


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def payload():
    return {"schema_version": 1, "query": "What is open?", "contexts": [{
        "document_id": "doc", "revision": 1, "chunk_id": "chunk", "title": "Synthetic",
        "meeting_date": None, "page": None, "start_offset": 0, "end_offset": 21,
        "text": "The library is open.\n"}]}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    monkeypatch.setattr(probe, "REQUIRED_FILES", {"implementation.py"})
    (tmp_path / "implementation.py").write_text("# synthetic version one\n")
    plan = {"schema_version": 1, "candidate": probe.CANDIDATE, "retries": 0,
            "analysis_calls": 0,
            "bound_files": {"implementation.py": probe.sha(tmp_path / "implementation.py")},
            "phases": {}, "known_gate": {"report": "out-known/report.json",
                                         "review": "review.json"}}
    for phase, count in probe.COUNTS.items():
        file = tmp_path / (phase + ".json")
        ids = [f"synthetic-{phase}-{n}" for n in range(count)]
        write(file, {"cases": [{"id": id, "operation": "answer", "payload": payload()}
                               for id in ids]})
        plan["phases"][phase] = {"input_file": file.name, "input_sha256": probe.sha(file),
                                 "case_ids": ids, "output_dir": "out-" + phase}
    path = tmp_path / "plan.json"
    write(path, plan)
    return tmp_path, path, plan


@dataclasses.dataclass
class Result:
    text: str = '{"status":"abstained","claims":[]}'
    finish_reason: str = "eos"
    input_tokens: int = 10
    output_tokens: int = 11
    elapsed_seconds: float = .01


class Generator:
    def __init__(self, effect=None):
        self.calls = 0
        self.closed = False
        self.effect = effect
        self.last_effective_config = {"temperature": 0, "grammar": "synthetic"}

    def public_metadata(self):
        return {"repo_id": "synthetic/model", "revision": "synthetic-revision"}

    def generate_bounded(self, messages, deadline):
        self.calls += 1
        if self.effect:
            self.effect(self.calls)
        return Result()

    def classify_bounded(self, *args):
        raise AssertionError("native classification must never execute")

    def close(self):
        self.closed = True


class Runtime:
    def __init__(self, generator):
        self.generator = generator

    def answer(self, request):
        self.generator.generate_bounded([{"role": "user", "content": request.query}],
                                        time.monotonic() + 10)
        return {"status": "abstained", "claims": []}

    def close(self):
        self.generator.close()


def run_phase(setup, phase="known", generator=None, runtime=Runtime):
    root, path, _ = setup
    prepared = probe.prepare(path, phase, root / ("out-" + phase))
    report = probe.claim_output(prepared)
    generator = generator or Generator()
    return probe.execute(generator, prepared, report, runtime), generator


def allow_validation(setup):
    root, path, _ = setup
    report, _ = run_phase(setup)
    write(root / "review.json", {"gate_passed": True,
          "report_sha256": probe.sha(root / "out-known/report.json"),
          "plan_sha256": probe.sha(path), "independent_of_implementation": True})
    return report


@pytest.mark.parametrize("phase", ["neutral", "known"])
def test_exact_case_budget_raw_capture_and_no_overwrite(setup, phase):
    root, path, _ = setup
    report, generator = run_phase(setup, phase)
    assert report["status"] == "completed_not_semantically_verified"
    assert report["sources_unchanged"] is True
    assert len(report["calls"]) == generator.calls == probe.COUNTS[phase]
    assert all(c["messages"] and c["output"] and c["effective_config"] for c in report["calls"])
    assert report["analysis_calls"] == 0 and generator.closed
    with pytest.raises(ValueError, match="output_exists"):
        probe.prepare(path, phase, root / ("out-" + phase))
    with pytest.raises(ValueError, match="mismatch"):
        probe.prepare(path, phase, root / "new-output-does-not-authorize-rerun")


def test_known_filters_preserved_analysis_without_executing_it(setup):
    root, path, plan = setup
    data = probe.read_json(root / "known.json")
    data["cases"].insert(0, {"id": "unused-analysis", "operation": "analyze", "payload": {}})
    write(root / "known.json", data)
    plan["phases"]["known"]["input_sha256"] = probe.sha(root / "known.json")
    write(path, plan)
    report, generator = run_phase(setup)
    assert generator.calls == 4 and len(report["results"]) == 4


@pytest.mark.parametrize("mutation", ["duplicate_chunk", "overflow", "bad_range", "empty"])
def test_all_requests_validated_before_any_native_start(setup, mutation):
    root, path, plan = setup
    data = probe.read_json(root / "known.json")
    target = data["cases"][-1]["payload"]
    if mutation == "duplicate_chunk":
        target["contexts"] *= 2
    elif mutation == "overflow":
        target["contexts"] *= 11
    elif mutation == "bad_range":
        target["contexts"][0]["end_offset"] = 99
    else:
        target["contexts"] = []
    write(root / "known.json", data)
    plan["phases"]["known"]["input_sha256"] = probe.sha(root / "known.json")
    write(path, plan)
    with pytest.raises(ValueError):
        probe.prepare(path, "known", root / "out-known")
    assert not (root / "out-known").exists()


def test_validation_gate_rejected_before_reading_dataset_or_shared_files(setup, monkeypatch):
    root, path, _ = setup
    (root / "validation.json").unlink()
    (root / "implementation.py").unlink()
    with pytest.raises(FileNotFoundError) as error:
        probe.prepare(path, "validation", root / "out-validation")
    assert "out-known" in str(error.value)


@pytest.mark.parametrize("field,value", [("gate_passed", 1), ("gate_passed", "true"),
    ("gate_passed", False), ("report_sha256", "a" * 64), ("plan_sha256", "b" * 64),
    ("independent_of_implementation", False)])
def test_review_requires_literal_true_and_exact_report_plan_link(setup, field, value):
    root, path, _ = setup
    allow_validation(setup)
    review = probe.read_json(root / "review.json")
    review[field] = value
    write(root / "review.json", review)
    (root / "validation.json").unlink()
    with pytest.raises(ValueError, match="known_gate_not_passed"):
        probe.prepare(path, "validation", root / "out-validation")


@pytest.mark.parametrize("field,value", [("candidate", "failed-old-9b"),
    ("phase", "neutral"), ("sources_unchanged", False), ("plan_sha256", "a" * 64),
    ("bound_files", {}), ("phase_inputs", {}), ("calls", []), ("results", [])])
def test_old_or_unlinked_report_cannot_open_validation(setup, field, value):
    root, path, _ = setup
    allow_validation(setup)
    report = probe.read_json(root / "out-known/report.json")
    report[field] = value
    write(root / "out-known/report.json", report)
    review = probe.read_json(root / "review.json")
    review["report_sha256"] = probe.sha(root / "out-known/report.json")
    write(root / "review.json", review)
    with pytest.raises(ValueError, match="known_gate_not_passed"):
        probe.prepare(path, "validation", root / "out-validation")


def test_validation_twelve_once_only_after_linked_independent_gate(setup):
    allow_validation(setup)
    report, generator = run_phase(setup, "validation")
    assert generator.calls == 12 and len(report["results"]) == 12
    assert report["known_gate"]["review_sha256"]


def test_failure_is_recorded_without_retry_and_other_cases_continue(setup):
    def fail(call):
        if call == 2:
            raise RuntimeError("raw private text must not become diagnostics")
    report, generator = run_phase(setup, generator=Generator(fail))
    assert generator.calls == 4
    assert [r["structural_status"] for r in report["results"]] == ["passed", "failed", "passed", "passed"]
    assert report["calls"][1]["error"] == "RuntimeError"
    assert "raw private" not in json.dumps(report)


@pytest.mark.parametrize("changed", ["implementation.py", "plan.json", "known.json"])
def test_source_or_plan_changes_stop_remaining_calls_and_preserve_partial(setup, changed):
    root, _, _ = setup
    def change(call):
        (root / changed).write_text("changed during first generation")
    report, generator = run_phase(setup, generator=Generator(change))
    assert generator.calls == 1 and len(report["calls"]) == 1
    assert report["status"] == "failed" and report["sources_unchanged"] is False
    assert generator.closed and probe.read_json(root / "out-known/report.json") == report


@pytest.mark.parametrize("mode", ["retry", "classify"])
def test_per_case_retries_and_classification_are_blocked(setup, mode):
    class BadRuntime(Runtime):
        def answer(self, request):
            if mode == "classify":
                self.generator.classify_bounded([], 0)
            super().answer(request)
            return super().answer(request)
    report, generator = run_phase(setup, runtime=BadRuntime)
    assert generator.calls == (4 if mode == "retry" else 0)
    assert all(x["structural_status"] == "failed" for x in report["results"])


def test_preflight_console_never_exposes_schema_input(setup, monkeypatch, capsys):
    root, path, plan = setup
    data = probe.read_json(root / "known.json")
    data["cases"][0]["payload"]["query"] = "PRIVATE_SOURCE_SENTINEL" * 100
    write(root / "known.json", data)
    plan["phases"]["known"]["input_sha256"] = probe.sha(root / "known.json")
    write(path, plan)
    monkeypatch.setattr("sys.argv", ["probe", "--phase", "known", "--plan", str(path),
                                     "--output", str(root / "out-known")])
    with pytest.raises(SystemExit):
        probe.main()
    captured = capsys.readouterr()
    assert "PRIVATE_SOURCE_SENTINEL" not in captured.out + captured.err


def test_shared_bindings_must_not_open_sealed_input(setup):
    root, path, plan = setup
    plan["bound_files"]["validation.json"] = plan["phases"]["validation"]["input_sha256"]
    write(path, plan)
    (root / "validation.json").unlink()
    with pytest.raises(ValueError, match="phase_input_in_shared_bindings"):
        probe.prepare(path, "known", root / "out-known")


def test_initial_partial_plan_does_not_authorize_validation(setup):
    root, path, plan = setup
    del plan["phases"]["validation"]
    del plan["known_gate"]
    write(path, plan)
    (root / "validation.json").unlink()
    report, generator = run_phase(setup)
    assert report["phase"] == "known" and generator.calls == 4
    with pytest.raises(ValueError, match="c0_plan_mismatch"):
        probe.prepare(path, "validation", root / "out-validation")


def separate_validation(setup):
    root, path, plan = setup
    validation = plan["phases"].pop("validation")
    write(path, plan)
    allow_validation(setup)
    later = {**plan, "source_plan": {"path": path.name, "sha256": probe.sha(path)},
             "phases": {"validation": validation}}
    later_path = root / "later-plan.json"
    write(later_path, later)
    return later_path, later


def test_new_validation_plan_binds_original_c0_plan_and_gate(setup):
    root, original_path, _ = setup
    path, _ = separate_validation(setup)
    prepared = probe.prepare(path, "validation", root / "out-validation")
    report = probe.claim_output(prepared)
    result = probe.execute(Generator(), prepared, report, Runtime)
    assert result["status"] == "completed_not_semantically_verified"
    assert result["plan_sha256"] == probe.sha(path)
    assert result["known_gate"]["source_plan_sha256"] == probe.sha(original_path)


@pytest.mark.parametrize("mutation", ["hash", "sources", "wrong_candidate", "missing_known"])
def test_separate_validation_rejects_substituted_source_plan(setup, mutation):
    root, original_path, _ = setup
    path, later = separate_validation(setup)
    if mutation == "hash":
        later["source_plan"]["sha256"] = "a" * 64
    elif mutation == "sources":
        later["bound_files"] = {**later["bound_files"], "extra.py": "b" * 64}
    else:
        source = probe.read_json(original_path)
        if mutation == "wrong_candidate":
            source["candidate"] = "old-failed-9b"
        else:
            del source["phases"]["known"]
        write(original_path, source)
        later["source_plan"]["sha256"] = probe.sha(original_path)
    write(path, later)
    (root / "validation.json").unlink()
    with pytest.raises(ValueError, match="source_plan"):
        probe.prepare(path, "validation", root / "out-validation")


def test_validation_gate_changes_after_preflight_stop_before_call(setup):
    root, path, _ = setup
    allow_validation(setup)
    prepared = probe.prepare(path, "validation", root / "out-validation")
    report = probe.claim_output(prepared)
    write(root / "review.json", {"gate_passed": False})
    generator = Generator()
    result = probe.execute(generator, prepared, report, Runtime)
    assert result["status"] == "failed" and generator.calls == 0
    assert result["sources_unchanged"] is False


def test_startup_failure_claims_output_and_preserves_safe_report(setup, monkeypatch, capsys):
    from contextlib import contextmanager

    from scripts import serve_meeting_qwen35
    root, path, _ = setup
    @contextmanager
    def fail_start(**kwargs):
        raise RuntimeError("PRIVATE_NATIVE_PATH_OR_TOKEN")
        yield  # pragma: no cover
    monkeypatch.setattr(serve_meeting_qwen35, "start_llama", fail_start)
    monkeypatch.setattr("sys.argv", ["probe", "--phase", "known", "--plan", str(path),
                                     "--output", str(root / "out-known")])
    with pytest.raises(SystemExit) as error:
        probe.main()
    assert error.value.code == 1
    report = probe.read_json(root / "out-known/report.json")
    assert report["status"] == "failed" and report["failure"] == "RuntimeError"
    assert report["calls"] == [] and report["results"] == []
    captured = capsys.readouterr()
    assert "PRIVATE_NATIVE_PATH_OR_TOKEN" not in captured.out + captured.err + json.dumps(report)


def test_real_span_runtime_plumbing_uses_only_fake_native_completions(setup):
    from doctrail.meeting_answer_spans import SpanAnswerGenerator
    root, path, _ = setup
    class FakeBase(Generator):
        def begin_request(self, deadline):
            pass

        def end_request(self):
            pass

        def count_tokens(self, messages):
            return 30

        def _complete(self, messages, deadline, token_limit, grammar):
            self.last_effective_config = {"temperature": 0, "grammar": grammar,
                                          "n_predict": token_limit}
            return self.generate_bounded(messages, deadline)
    base = FakeBase()
    generator = SpanAnswerGenerator(base)
    prepared = probe.prepare(path, "neutral", root / "out-neutral")
    report = probe.execute(generator, prepared, probe.claim_output(prepared))
    assert base.calls == 2 and base.closed
    assert all(row["structural_status"] == "passed" for row in report["results"])
    assert all(call["runtime_identity"]["answer_decoder"]["grammar_sha256"]
               for call in report["calls"])
    assert all(call["effective_config"]["n_predict"] == 768 for call in report["calls"])
