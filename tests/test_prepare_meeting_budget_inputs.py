"""Generic synthetic snapshots and fake official counters; no real data/models."""
import copy
import json
from types import SimpleNamespace

import pytest

from scripts import prepare_meeting_budget_inputs as prep


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(prep.encoded(value))
    return prep.sha(path.read_bytes())


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setattr(prep, "ROOT", tmp_path)

    def make(phase="validation", counts=100):
        draft_path, item_path = (tmp_path / n for n in prep.PHASE_PATHS[phase])
        text = "Synthetic cyan fixture 😀 e\u0301.\r\nSecond line.\n\n"
        payload = {"schema_version": 1, "query": "What color is the synthetic fixture?",
            "contexts": [{"document_id": "synthetic", "revision": 1, "chunk_id": "fresh-0",
                "title": "Synthetic only", "page": None, "meeting_date": None,
                "start_offset": 9, "end_offset": 9 + len(text), "text": text}]}
        draft = {"schema_version": 1, "phase": phase, "cases": [
            {"id": f"synthetic-{i}", "payload": copy.deepcopy(payload)} for i in range(prep.COUNTS[phase])]}
        for name in prep.FILES:
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"# synthetic bound source, no implementation execution\n")
        corpus = item_path.parent / "source-freeze-v1.json"
        write(corpus, {"bound_files": {"must-not-read-oracle.json": "e" * 64}})
        legacy = {}
        for name in prep.LEGACY_FREEZES:
            legacy[name] = write(tmp_path / name, {"bound_files": {
                min(prep.FILES): prep.sha((tmp_path / min(prep.FILES)).read_bytes())}})
        baseline = tmp_path / ".local/old/input.json"
        write(baseline, {**draft, "cases": [{**c, "official_input_tokens": {"L0": counts, "C2": counts}}
                                          for c in draft["cases"]]})
        protocol_path = tmp_path / prep.PROTOCOL_FILE
        freeze_path = tmp_path / "new-code-freeze.json"
        source = SimpleNamespace(root=tmp_path, draft=draft, draft_path=draft_path,
            item_path=item_path, corpus=corpus, protocol_path=protocol_path,
            freeze_path=freeze_path, baseline=baseline, phase=phase, output=tmp_path / ".local/new",
            loads=[], calls=[])

        def seal():
            draft_sha = write(draft_path, source.draft)
            item_sha = write(item_path, {"schema_version": 1, "bound_files": {
                **legacy, draft_path.relative_to(tmp_path).as_posix(): draft_sha,
                corpus.relative_to(tmp_path).as_posix(): prep.sha(corpus.read_bytes())}})
            protocol_sha = write(protocol_path, {"candidate": prep.PROTOCOL, "bound_files": {
                **legacy, draft_path.relative_to(tmp_path).as_posix(): draft_sha,
                item_path.relative_to(tmp_path).as_posix(): item_sha}})
            monkeypatch.setattr(prep, "PROTOCOL_SHA256", protocol_sha)
            write(freeze_path, {"bound_files": {**legacy, prep.PROTOCOL_FILE: protocol_sha,
                **{n: prep.sha((tmp_path / n).read_bytes()) for n in prep.FILES}},
                "baseline_inputs": {
                    baseline.relative_to(tmp_path).as_posix(): prep.sha(baseline.read_bytes())}})
        source.seal = seal
        seal()

        def loader(download):
            source.loads.append(download)
            return None, {"repo_id": prep.MODEL_ID, "revision": prep.MODEL_REVISION,
                "transformers_version": "synthetic-test", "download_authorized": False,
                "trust_remote_code": False, "assets_sha256": {n: "a" * 64 for n in
                    ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja")}}

        def counter(_, prompt):
            source.calls.append(copy.deepcopy(prompt))
            return counts

        source.loader, source.counter = loader, counter
        return source
    return make


def run(s, **kwargs):
    return prep.prepare(s.draft_path, s.output, s.phase, item_freeze_path=s.item_path,
        source_freeze_path=s.freeze_path, protocol_path=s.protocol_path,
        baseline_input_path=kwargs.pop("baseline_input_path", s.baseline if s.phase == "calibration" else None),
        loader=kwargs.pop("loader", s.loader), counter=kwargs.pop("counter", s.counter), **kwargs)


def assert_receipt(s, report):
    assert json.loads((s.output / "receipt.json").read_bytes()) == report
    assert report["model_calls"] == report["native_calls"] == report["downloads"] == 0
    if report["status"] == "failed":
        assert not (s.output / "input.json").exists()


@pytest.mark.parametrize("phase", ["calibration", "validation"])
def test_complete_counts_exact_payload_and_immutable_receipt(factory, phase):
    s = factory(phase)
    report = run(s)
    assert report["status"] == "passed", report["errors"]
    assert_receipt(s, report)
    prepared = json.loads((s.output / "input.json").read_bytes())
    assert [{"id": c["id"], "payload": c["payload"]} for c in prepared["cases"]] == s.draft["cases"]
    assert report["input_sha256"] == prep.sha((s.output / "input.json").read_bytes())
    assert report["payloads_preserved"] is True
    assert s.loads == [False] and len(s.calls) == prep.COUNTS[phase] * 2
    assert report["summary"]["unknown_arms"] == 0
    measured = report["cases"][0]["arms"]["C2"]
    assert measured["native_request_bytes"] is None and not measured["native_request_bytes_verified"]
    assert measured["template_request_bytes"] > 0 and measured["grammar_sha256"]
    before = (s.output / "receipt.json").read_bytes()
    with pytest.raises(prep.PreparationError, match="output_exists"):
        run(s)
    assert (s.output / "receipt.json").read_bytes() == before


@pytest.mark.parametrize("count", [4096, 4097, 5120, 5121])
def test_full_survey_after_any_overflow_both_caps_both_arms(factory, count):
    s = factory(counts=count)
    report = run(s)
    assert len(s.calls) == 24
    assert report["status"] == ("passed" if count <= 5120 else "failed")
    assert report["summary"]["measured_arms"] == 24
    assert report["summary"]["old_4096_pass"] == (24 if count <= 4096 else 0)
    assert report["summary"]["new_5120_pass"] == (24 if count <= 5120 else 0)
    assert report["payloads_preserved"] is True
    for case in report["cases"]:
        assert all(r["official_input_tokens"] == count for r in case["arms"].values())
    assert_receipt(s, report)


@pytest.mark.parametrize("bad", [False, True, 0, -1, 4.0, "5120", None])
def test_bad_one_count_remains_unknown_and_other_arms_still_measured(factory, bad):
    s = factory()
    calls = []
    def counter(*_):
        calls.append(1)
        return bad if len(calls) == 3 else 120
    report = run(s, counter=counter)
    assert len(calls) == 24 and report["status"] == "failed"
    assert report["summary"]["unknown_arms"] == 1
    assert report["summary"]["measured_arms"] == 23
    assert report["cases"][1]["arms"]["L0"]["official_input_tokens"] is None
    assert_receipt(s, report)


def test_private_token_exception_and_loader_failure_are_safe_receipts(factory):
    s = factory()
    calls = []
    def counter(*_):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("PRIVATE BODY")
        return 100
    report = run(s, counter=counter)
    assert len(calls) == 24 and report["summary"]["measured_arms"] == 23
    assert b"PRIVATE" not in (s.output / "receipt.json").read_bytes()
    s.output = s.root / ".local/loader-fail"
    def loader(*_):
        raise RuntimeError("PRIVATE CACHE PATH")
    failed = run(s, loader=loader)
    assert failed["summary"]["unknown_arms"] == 24 and failed["tokenizer"] is None
    assert b"PRIVATE" not in (s.output / "receipt.json").read_bytes()


def test_structurally_oversized_block_not_split_and_other_cases_continue(factory):
    s = factory()
    context = s.draft["cases"][0]["payload"]["contexts"][0]
    context["text"] = "x" * 1025
    context["end_offset"] = context["start_offset"] + 1025
    s.seal()
    report = run(s)
    assert report["status"] == "failed"
    assert report["cases"][0]["arms"]["C2"]["error_code"] == "static_structure_or_byte_limit"
    assert report["summary"]["measured_arms"] == 23  # Frozen L0 segmentation stays untouched.
    assert len(s.calls) == 23


@pytest.mark.parametrize("change", [
    lambda d: d.update(schema_version=True), lambda d: d.update(phase="calibration"),
    lambda d: d["cases"].pop(), lambda d: d["cases"][1].update(id=d["cases"][0]["id"]),
    lambda d: d["cases"][0].update(id="invalid/id"),
])
def test_invalid_draft_schema_receipted_without_tokenizer(factory, change):
    s = factory()
    change(s.draft); s.seal()
    report = run(s)
    assert report["status"] == "failed" and not s.loads
    assert report["summary"]["unknown_arms"] == 24
    assert_receipt(s, report)


@pytest.mark.parametrize("change", [
    lambda p: p["contexts"][0].pop("meeting_date"),
    lambda p: p["contexts"][0].update(revision=True),
    lambda p: p["contexts"][0].update(end_offset=1),
])
def test_invalid_or_omitted_required_fields_not_inserted_or_coerced(factory, change):
    s = factory()
    change(s.draft["cases"][0]["payload"]); s.seal()
    report = run(s)
    assert report["status"] == "failed" and len(s.calls) == 22
    assert report["cases"][0]["arms"]["L0"]["error_code"] == "invalid_payload"
    assert report["summary"]["unknown_arms"] == 2


def test_phase_paths_rejected_before_body_read(factory, monkeypatch):
    s = factory()
    reads = []
    original = prep.snapshot
    def snapshot(path):
        reads.append(path)
        return original(path)
    monkeypatch.setattr(prep, "snapshot", snapshot)
    s.phase = "calibration"
    report = run(s)
    assert report["errors"] == ["preparation_phase_path_mismatch"] and not reads


def test_single_bounded_input_snapshot_and_detected_source_drift(factory, monkeypatch):
    s = factory()
    reads = []
    original = prep.snapshot
    def snapshot(path):
        reads.append(path)
        return original(path)
    monkeypatch.setattr(prep, "snapshot", snapshot)
    report = run(s)
    assert report["status"] == "passed"
    for path in (s.draft_path, s.item_path, s.corpus, s.protocol_path, s.freeze_path):
        assert reads.count(path) == 1
    s.output = s.root / ".local/drift"
    def counter(*_):
        (s.root / min(prep.FILES)).write_bytes(b"changed")
        return 5121  # Integrity failure must also be detected on an over-cap survey.
    report = run(s, counter=counter)
    assert report["status"] == "failed"
    assert any("changed" in e for e in report["errors"])


def test_hash_tampering_stops_before_tokenization_and_no_old_output_overwrite(factory):
    s = factory()
    s.draft_path.write_bytes(s.draft_path.read_bytes() + b" ")
    report = run(s)
    assert report["status"] == "failed" and not s.loads
    assert "preparation_hash_mismatch" in report["errors"]
    assert_receipt(s, report)
    s.output = s.root / ".local/empty"
    s.output.mkdir()
    with pytest.raises(prep.PreparationError, match="output_exists"):
        run(s)


def test_baseline_payload_count_and_registration_are_required(factory):
    s = factory("calibration")
    report = run(s, baseline_input_path=None)
    assert report["errors"] == ["preparation_baseline_required"]
    s.output = s.root / ".local/count-drift"
    report = run(s, counter=lambda *_: 101)
    assert report["summary"]["measured_arms"] == 16
    assert all(r["error_code"] == "baseline_token_count_mismatch" for c in report["cases"]
               for r in c["arms"].values())
    s.output = s.root / ".local/payload-drift"
    baseline = json.loads(s.baseline.read_bytes())
    baseline["cases"][0]["payload"]["query"] = "Different synthetic question"
    write(s.baseline, baseline); s.seal()
    assert run(s)["errors"] == ["preparation_baseline_payload_mismatch"]


def test_artifact_bound_duplicate_json_keys_and_paths_fail_safely(factory, monkeypatch):
    s = factory()
    with pytest.raises(prep.PreparationError, match="outside_repository"):
        prep.prepare(s.root.parent / "outside", s.output, s.phase,
                     item_freeze_path=s.item_path, source_freeze_path=s.freeze_path)
    s.output = s.draft_path.parent
    with pytest.raises(prep.PreparationError, match="outside_repository"):
        run(s)
    monkeypatch.setattr(prep, "BYTE_LIMIT", 10)
    with pytest.raises(prep.PreparationError, match="file_limit"):
        prep.snapshot(s.draft_path)


def test_template_request_bytes_and_completion_lower_bound_are_not_native_proof(factory, monkeypatch):
    s = factory()
    monkeypatch.setattr(prep, "MAX_REQUEST_BYTES", 1)
    report = run(s)
    assert report["status"] == "failed" and not s.calls
    assert report["summary"]["unknown_arms"] == 24


def test_cli_redacts_errors_and_uses_failure_exit(factory, monkeypatch, capsys):
    s = factory()
    def private(*_, **__):
        print("PRIVATE BODY")
        raise ValueError("PRIVATE PATH")
    monkeypatch.setattr(prep, "prepare", private)
    monkeypatch.setattr("sys.argv", ["prepare", "--draft", str(s.draft_path), "--output", str(s.output),
        "--phase", s.phase, "--item-freeze", str(s.item_path), "--source-freeze", str(s.freeze_path)])
    with pytest.raises(SystemExit) as result:
        prep.main()
    captured = capsys.readouterr()
    assert result.value.code == 1 and captured.err == "budget_input_preparation_failed\n"
    assert "PRIVATE" not in captured.out + captured.err


def test_missing_code_or_corpus_freeze_bindings_fail_before_tokenizer(factory):
    s = factory()
    freeze = json.loads(s.freeze_path.read_bytes())
    del freeze["bound_files"][min(prep.FILES)]
    write(s.freeze_path, freeze)
    report = run(s)
    assert report["errors"] == ["preparation_source_freeze_incomplete"] and not s.loads
    assert_receipt(s, report)


def test_runtime_preparation_drift_fails_without_second_draft_read(factory, monkeypatch):
    s = factory()
    reads = []
    original = prep.snapshot
    def snapshot(path):
        reads.append(path)
        return original(path)
    monkeypatch.setattr(prep, "snapshot", snapshot)
    def counter(*_):
        s.draft_path.write_bytes(b"changed after captured snapshot")
        return 100
    report = run(s, counter=counter)
    assert report["status"] == "failed" and "preparation_snapshot_changed" in report["errors"]
    assert reads.count(s.draft_path) == 1
    assert_receipt(s, report)


def test_unpinned_tokenizer_metadata_cannot_be_success(factory):
    s = factory()
    def loader(download):
        tokenizer, metadata = s.loader(download)
        metadata["download_authorized"] = True
        return tokenizer, metadata
    report = run(s, loader=loader)
    assert report["errors"] == ["preparation_tokenizer_metadata"] and not s.calls


def test_symlink_output_ancestor_refused_without_reading_data(factory):
    s = factory()
    link = s.root / ".local/link"
    try:
        link.symlink_to(s.root / ".local/old", target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    s.output = link / "new"
    with pytest.raises(prep.PreparationError, match="linked_path"):
        run(s)
