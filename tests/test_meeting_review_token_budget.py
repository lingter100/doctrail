"""Synthetic tokenizer doubles only; no installed tokenizer or data is loaded."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import check_meeting_review_token_budget as check


class Tokenizer:
    def __init__(self, count=100):
        self.count, self.messages = count, []

    def apply_chat_template(self, messages, **kwargs):
        assert kwargs == {"tokenize": False, "add_generation_prompt": True, "enable_thinking": False}
        self.messages.append(messages)
        return json.dumps(messages) + check.NONTHINKING_PREAMBLE

    def encode(self, text, **kwargs):
        assert kwargs == {"add_special_tokens": False}
        assert text.endswith(check.NONTHINKING_PREAMBLE)
        return [1] * self.count


@pytest.fixture
def fixture(tmp_path):
    text = "Synthetic private source.\n\nSecond line."
    path = tmp_path / "cases.json"
    payload = {"schema_version": 1, "query": "SYNTHETIC_PRIVATE_QUESTION", "contexts": [{
        "document_id": "doc", "chunk_id": "chunk", "revision": 1, "title": "Title",
        "meeting_date": None, "page": None, "text": text, "start_offset": 5,
        "end_offset": 5 + len(text)}]}
    path.write_text(json.dumps({"cases": [{"id": "synthetic-1", "operation": "answer", "payload": payload}]}))
    return path, check.sha(path.read_bytes()), tmp_path / "report.json"


def test_full_frozen_prompts_headroom_and_no_text_in_report(fixture):
    path, digest, output = fixture
    tokenizer = Tokenizer()
    report = check.prepare(path, digest, output, loader=lambda allow: (tokenizer, {"mock": True}))
    assert len(tokenizer.messages) == 5
    row = report["cases"][0]
    assert row["planning_prompt_tokens_with_headroom"]["D0"] == 100
    assert row["planning_prompt_tokens_with_headroom"]["V0_fixed_synthetic"] == 1124
    assert row["planning_prompt_tokens_with_headroom"]["D1_empty"] == 1636
    assert row["placeholder_prompt_tokens"]["V1_empty"] == row["placeholder_prompt_tokens"]["V0_empty"]
    sources = [json.loads(messages[1]["content"])["sources"] for messages in tokenizer.messages]
    assert all(source == sources[0] for source in sources)
    assert report["model_calls"] == report["native_calls"] == 0
    assert "SYNTHETIC_PRIVATE" not in output.read_text()
    assert "Synthetic private source" not in output.read_text()
    assert report["candidate_code_sha256"]


def test_hash_and_existing_output_fail_before_tokenizer_load(fixture):
    path, digest, output = fixture
    def forbidden(*args):
        pytest.fail("loader called")
    with pytest.raises(ValueError, match="hash_mismatch"):
        check.prepare(path, "0" * 64, output, loader=forbidden)
    output.write_text("existing")
    with pytest.raises(ValueError, match="output_exists"):
        check.prepare(path, digest, output, loader=forbidden)
    assert output.read_text() == "existing"


def test_headroom_failure_is_not_native_or_quality_failure(fixture):
    path, digest, output = fixture
    report = check.prepare(path, digest, output, loader=lambda _: (Tokenizer(3000), {}))
    assert report["summary"]["all_d0_within_limit"] is True
    assert report["summary"]["all_planning_within_limit"] is False
    assert "not a mathematical worst-case" in " ".join(report["limitations"])


def test_template_must_end_with_registered_nonthinking_preamble():
    tokenizer = Tokenizer()
    tokenizer.apply_chat_template = lambda *a, **k: "wrong preamble"
    with pytest.raises(ValueError, match="preamble"):
        check.count_prompt(tokenizer, [])


@pytest.mark.parametrize("allowed", [False, True])
def test_loader_pins_only_tokenizer_assets_and_never_remote_code(tmp_path, monkeypatch, allowed):
    calls = []
    for name in check.ASSETS:
        (tmp_path / name).write_text("synthetic asset")
    (tmp_path / "config.json").write_text("must not load root model config")
    (tmp_path / "model.safetensors").write_text("must not load weights")
    def snapshot(**kwargs):
        calls.append(kwargs)
        return str(tmp_path)
    class Auto:
        @staticmethod
        def from_pretrained(path, **kwargs):
            assert path != str(tmp_path)
            assert {p.name for p in Path(path).iterdir()} == set(check.ASSETS)
            assert all(p.read_text() == "synthetic asset" for p in Path(path).iterdir())
            assert kwargs == {"local_files_only": True, "trust_remote_code": False}
            return Tokenizer()
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(AutoTokenizer=Auto, __version__="synthetic"))
    _, metadata = check.load_tokenizer(allowed)
    assert calls == [{"repo_id": check.MODEL_ID, "revision": check.MODEL_REVISION,
                      "allow_patterns": list(check.ASSETS), "local_files_only": not allowed}]
    assert all("config.json" != name and not name.endswith("safetensors") for name in check.ASSETS)
    assert len(metadata["assets_sha256"]) == len(check.ASSETS)


def test_cli_errors_and_success_only_print_aggregate(fixture, monkeypatch, capsys):
    path, digest, output = fixture
    monkeypatch.setattr(sys, "argv", ["check", "--input", str(path), "--expected-sha", digest,
                                     "--output", str(output)])
    def failed(*args, **kwargs):
        print("SYNTHETIC_PRIVATE_QUESTION")
        print("SYNTHETIC_PRIVATE_QUESTION", file=sys.stderr)
        raise RuntimeError("SYNTHETIC_PRIVATE_QUESTION")
    monkeypatch.setattr(check, "prepare", failed)
    with pytest.raises(SystemExit):
        check.main()
    captured = capsys.readouterr()
    assert "SYNTHETIC_PRIVATE" not in captured.out + captured.err
    monkeypatch.setattr(check, "prepare", lambda *a, **k: {"summary": {
        "cases": 1, "all_planning_within_limit": True}})
    with pytest.raises(SystemExit) as error:
        check.main()
    assert error.value.code == 0
    assert json.loads(capsys.readouterr().out)["model_calls"] == 0
