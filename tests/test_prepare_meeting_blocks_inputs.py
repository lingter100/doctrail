"""Only fresh synthetic drafts and fake tokenizers; no model or evaluation pools."""
import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from doctrail.inference import WorkerError
from scripts import prepare_meeting_blocks_inputs as probe


def write(path, value):
    path.write_bytes(probe.encoded(value))


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    monkeypatch.setattr(probe, "FILES", {"synthetic.py"})
    (tmp_path / "synthetic.py").write_text("# synthetic bound implementation\n")
    text = "The fresh synthetic sample is mint.\r\nIts label is a square.\n\n"
    payload = {"schema_version": 1, "query": "What color is the fresh synthetic sample?",
        "contexts": [{"document_id": "synthetic-doc", "revision": 1,
            "chunk_id": "synthetic-chunk", "title": "Synthetic token preparation",
            "meeting_date": None, "page": None, "start_offset": 11,
            "end_offset": 11 + len(text), "text": text}]}
    draft = {"schema_version": 1, "phase": "calibration", "cases": [
        {"id": f"synthetic-{i}", "payload": copy.deepcopy(payload)} for i in range(8)]}
    path = tmp_path / "draft.json"
    write(path, draft)
    return SimpleNamespace(root=tmp_path, path=path, draft=draft, output=tmp_path / "prepared")


def run(source, **kwargs):
    return probe.prepare(source.path, source.output, source.draft["phase"],
        loader=kwargs.pop("loader", lambda download: (None, {"pinned": "synthetic", "download": download})),
        counter=kwargs.pop("counter", lambda _, messages: len(json.dumps(messages))), **kwargs)


def test_preparation_preserves_exact_payload_and_receipt_binds_exact_bytes(source):
    raw = source.path.read_bytes()
    receipt = run(source)
    output = json.loads((source.output / "input.json").read_bytes())
    assert receipt["draft_sha256"] == hashlib.sha256(raw).hexdigest()
    assert receipt["input_sha256"] == hashlib.sha256((source.output / "input.json").read_bytes()).hexdigest()
    assert receipt["tokenizer"] == {"pinned": "synthetic", "download": False}
    assert receipt["model_calls"] == receipt["downloads"] == 0
    for original, prepared in zip(source.draft["cases"], output["cases"], strict=True):
        assert prepared["payload"] == original["payload"] and prepared["id"] == original["id"]
        assert set(prepared["official_input_tokens"]) == {"L0", "C2"}
    assert receipt["cases"] == [{"id": c["id"], "official_input_tokens": c["official_input_tokens"]}
                                for c in output["cases"]]
    assert set(receipt["bound_files"]) == {"synthetic.py"}
    assert json.loads((source.output / "receipt.json").read_bytes()) == receipt


def test_repeat_preflight_to_different_new_output_is_byte_deterministic(source):
    first = run(source)
    first_bytes = (source.output / "input.json").read_bytes()
    source.output = source.root / "second-preparation"
    assert run(source) == first
    assert (source.output / "input.json").read_bytes() == first_bytes


def test_missing_required_nullable_fields_are_not_silently_added(source):
    for case in source.draft["cases"]:
        del case["payload"]["contexts"][0]["meeting_date"]
        del case["payload"]["contexts"][0]["page"]
    write(source.path, source.draft)
    with pytest.raises(ValueError):
        run(source)
    assert not source.output.exists()


@pytest.mark.parametrize("change", [lambda d: d.update(schema_version=True),
    lambda d: d.update(phase="validation"), lambda d: d["cases"].pop(),
    lambda d: d["cases"][1].update(id=d["cases"][0]["id"]),
    lambda d: d["cases"][0].update(id="unsafe/id"),
    lambda d: d["cases"][0].update(official_input_tokens={"L0": 2, "C2": 2}),
    lambda d: d["cases"][0]["payload"].update(contexts=[]),
    lambda d: d["cases"][0]["payload"]["contexts"][0].update(end_offset=12)])
def test_bad_draft_fails_before_tokenizer_load_or_output_claim(source, change):
    change(source.draft)
    write(source.path, source.draft)

    def forbidden_loader(*args):
        pytest.fail("Invalid draft must not load tokenizer")
    with pytest.raises((ValueError, WorkerError)):
        probe.prepare(source.path, source.output, "calibration", loader=forbidden_loader)
    assert not source.output.exists()


@pytest.mark.parametrize("tokens", [0, -1, 4097, True, 1.0, "200", None])
def test_invalid_token_counts_never_truncate_retry_or_write(source, tokens):
    calls = []

    def counter(*args):
        calls.append(1)
        return tokens
    with pytest.raises(ValueError, match="token_limit"):
        run(source, counter=counter)
    assert len(calls) == 2 and not source.output.exists()


@pytest.mark.parametrize("tokens", [1, 4096])
def test_inclusive_official_token_bounds_and_recorded_ranges(source, tokens):
    result = run(source, counter=lambda *_: tokens)
    assert result["token_range"] == {arm: {"min": tokens, "max": tokens} for arm in ("L0", "C2")}


def test_oversized_c2_block_is_rejected_without_splitting_or_tokenizer_load(source):
    context = source.draft["cases"][0]["payload"]["contexts"][0]
    context.update(text="x" * 1025, end_offset=context["start_offset"] + 1025)
    write(source.path, source.draft)

    def forbidden_loader(*args):
        pytest.fail("Oversized block must not load tokenizer")
    with pytest.raises(WorkerError, match="generation_block_limit"):
        run(source, loader=forbidden_loader)
    assert not source.output.exists()


def test_existing_output_even_empty_is_never_reused(source):
    source.output.mkdir()
    with pytest.raises(ValueError, match="output_exists"):
        run(source)
    assert not list(source.output.iterdir())


def test_existing_receipt_and_input_preserved_on_second_attempt(source):
    run(source)
    before = {p.name: p.read_bytes() for p in source.output.iterdir()}
    with pytest.raises(ValueError, match="output_exists"):
        run(source)
    assert {p.name: p.read_bytes() for p in source.output.iterdir()} == before


def test_source_output_collision_and_outside_paths_rejected_before_read(source):
    with pytest.raises(ValueError, match="output_exists_or_collision"):
        probe.prepare(source.path, source.path, "calibration")
    with pytest.raises(ValueError, match="outside_repository"):
        probe.prepare(source.root.parent / "outside.json", source.output, "calibration")
    with pytest.raises(ValueError, match="outside_repository"):
        probe.prepare(source.path, source.root.parent / "outside-output", "calibration")


def test_draft_snapshot_is_read_once_and_hashes_the_parsed_bytes(source, monkeypatch):
    original = probe.snapshot
    reads = []

    def snapshot(path):
        if path == source.path:
            reads.append(path)
            raw, sha = original(path)
            path.write_text("changed after captured snapshot")
            return raw, sha
        return original(path)
    before = source.path.read_bytes()
    monkeypatch.setattr(probe, "snapshot", snapshot)
    result = run(source)
    assert len(reads) == 1 and result["draft_sha256"] == hashlib.sha256(before).hexdigest()
    output = json.loads((source.output / "input.json").read_bytes())
    assert output["cases"][0]["payload"] == source.draft["cases"][0]["payload"]


def test_source_binding_change_during_tokenization_aborts_before_output(source):
    def changed(*args):
        (source.root / "synthetic.py").write_text("# changed")
        return 200
    with pytest.raises(ValueError, match="source_changed"):
        run(source, counter=changed)
    assert not source.output.exists()


def test_duplicate_json_keys_and_bounded_bytes_fail_closed(source, monkeypatch):
    source.path.write_text('{"schema_version":1,"schema_version":1,"phase":"calibration","cases":[]}')
    with pytest.raises((ValueError, WorkerError)):
        run(source)
    monkeypatch.setattr(probe, "BYTE_LIMIT", 10)
    with pytest.raises(ValueError, match="file_limit"):
        probe.snapshot(source.path)


def test_validation_preparation_has_twelve_cases_and_no_generation_gate_or_calls(source):
    source.draft["phase"] = "validation"
    source.draft["cases"] += [dict(copy.deepcopy(source.draft["cases"][0]), id=f"synthetic-{i}")
                              for i in range(8, 12)]
    write(source.path, source.draft)
    loads, counters = [], []

    def loader(download):
        loads.append(download)
        return None, {"offline": True}

    def counter(*args):
        counters.append(1)
        return 200
    result = run(source, loader=loader, counter=counter)
    assert result["phase"] == "validation" and len(result["cases"]) == 12
    assert loads == [False] and len(counters) == 24 and result["model_calls"] == 0


def test_cli_error_does_not_print_private_exception_text(source, monkeypatch, capsys):
    def fail(*args):
        raise ValueError("PRIVATE_QUESTION_AND_SOURCE")
    monkeypatch.setattr(probe, "prepare", fail)
    monkeypatch.setattr("sys.argv", ["helper", "--draft", str(source.path), "--output",
                                   str(source.output), "--phase", "calibration"])
    with pytest.raises(SystemExit) as error:
        probe.main()
    output = capsys.readouterr()
    assert error.value.code == 1 and output.err == "input_preparation_failed\n"
    assert "PRIVATE" not in output.out + output.err
