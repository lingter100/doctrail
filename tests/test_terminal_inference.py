"""Model-free contract checks; synthetic vectors are not retrieval-quality evidence."""

import copy
import hashlib
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from doctrail import terminal_inference as terminal
from doctrail.inference import DIMENSION, EmbedRequest, InferenceRuntime, create_app

TOKEN = "synthetic-terminal-token-" + "x" * 32


class FakeEncoder:
    device, dtype = "cpu", "torch.float32"

    def __init__(self):
        self.telemetry = {"truncated_inputs": 0}
        self.telemetry_inputs = []
        self.closed = False
        self.calls = 0

    def encode_passages(self, texts):
        self.calls += 1
        return [[1.0] + [0.0] * (DIMENSION - 1) for _ in texts]

    encode_queries = encode_passages

    def close(self):
        self.closed = True


def test_bound_receipt_parses_only_the_bytes_that_were_hashed(tmp_path, monkeypatch):
    path = tmp_path / "receipt.json"
    content = b'{"synthetic": true}'
    path.write_bytes(content)
    original = Path.read_bytes
    reads = []

    def read_then_change(target):
        value = original(target)
        reads.append(target)
        target.write_bytes(b'{"synthetic": false}')
        return value

    monkeypatch.setattr(Path, "read_bytes", read_then_change)
    assert terminal._read_bound(tmp_path, path.name, hashlib.sha256(content).hexdigest()) == {
        "synthetic": True}
    assert reads == [path]


def test_public_preflight_reads_only_bound_public_receipts(monkeypatch):
    original = Path.open
    opened = []

    def guarded(path, *args, **kwargs):
        name = path.relative_to(terminal.ROOT).as_posix()
        assert name in set(terminal.PUBLIC_BINDINGS) | {
            "data/training/m4-e5-execution-v2.json",
            "data/training/m4-training-manifest-v2.json",
            "experiments/results/m4-e5-probe-v2.json",
            "experiments/results/m4-e5-train-v2.json",
        }
        opened.append(name)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    result = terminal.validate_public_profile()
    assert result["revision"] == terminal.TERMINAL_REVISION
    assert len(set(opened)) == 8


@pytest.mark.parametrize("changed", list(terminal.PUBLIC_BINDINGS) + [
    "data/training/m4-e5-execution-v2.json", "data/training/m4-training-manifest-v2.json",
    "experiments/results/m4-e5-probe-v2.json", "experiments/results/m4-e5-train-v2.json",
])
def test_public_receipt_tamper_fails_before_model_load(tmp_path, changed, monkeypatch):
    profile = terminal.validate_public_profile()
    for name in profile["public_bindings"]:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(terminal.ROOT / name, target)
    with (tmp_path / changed).open("ab") as stream:
        stream.write(b" ")
    monkeypatch.setattr(terminal.models, "_load_runtime", lambda: pytest.fail("model imported"))
    with pytest.raises(ValueError, match="public_receipt_hash_mismatch"):
        terminal.validate_public_profile(tmp_path)


@pytest.fixture
def tiny_snapshots(tmp_path, monkeypatch):
    profile = copy.deepcopy(terminal.validate_public_profile())
    base, checkpoint = tmp_path / "base", tmp_path / "terminal"
    for folder, spec in ((base, profile["models"]["e5"]), (checkpoint, profile["checkpoint"])):
        folder.mkdir()
        for name in spec["files"]:
            content = (folder.name + name).encode()
            (folder / name).write_bytes(content)
            spec["files"][name] = {"sha256": hashlib.sha256(content).hexdigest(),
                                   "size_bytes": len(content)}
    monkeypatch.setattr(terminal, "validate_public_profile", lambda: profile)
    return base, checkpoint, profile


@pytest.mark.parametrize("change", ["bytes", "missing", "extra", "directory", "base-tokenizer"])
def test_invalid_snapshots_rejected_before_heavy_import(tiny_snapshots, monkeypatch, change):
    base, checkpoint, _ = tiny_snapshots
    if change == "bytes":
        (checkpoint / "model.safetensors").write_bytes(b"wrong")
    elif change == "missing":
        (checkpoint / "tokenizer.json").unlink()
    elif change == "extra":
        (checkpoint / "pytorch_model.bin").write_bytes(b"alternate")
    elif change == "directory":
        (checkpoint / "config.json").unlink()
        (checkpoint / "config.json").mkdir()
    else:
        (base / "tokenizer.json").write_bytes(b"wrong tokenizer")
    monkeypatch.setattr(terminal.models, "_load_runtime", lambda: pytest.fail("model imported"))
    with pytest.raises(ValueError):
        terminal.TerminalEncoder(checkpoint, base, device="cpu")


@pytest.mark.parametrize("link_target", ["directory", "file"])
def test_symlink_rejection_even_with_correct_bytes(tiny_snapshots, monkeypatch, link_target):
    base, checkpoint, _ = tiny_snapshots
    target = checkpoint if link_target == "directory" else checkpoint / "tokenizer.json"
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == target or original(path))
    monkeypatch.setattr(terminal.models, "_load_runtime", lambda: pytest.fail("model imported"))
    with pytest.raises(ValueError, match="linked_model_or_receipt_path"):
        terminal.TerminalEncoder(checkpoint, base, device="cpu")


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_terminal_encoder_uses_verified_base_tokenizer_fp32_eager(tiny_snapshots, monkeypatch, device):
    base, checkpoint, _ = tiny_snapshots
    calls = {}

    class Tokenizer:
        @staticmethod
        def from_pretrained(path, **kwargs):
            calls["tokenizer"] = path, kwargs
            return SimpleNamespace(is_fast=True, truncation_side="right")

    class Model:
        @staticmethod
        def from_pretrained(path, **kwargs):
            calls["model"] = path, kwargs
            return Model()

        def to(self, value):
            calls["device"] = value
            return self

        def eval(self):
            calls["eval"] = True
            return self

    torch = SimpleNamespace(float32="float32", cuda=SimpleNamespace(is_available=lambda: True))
    monkeypatch.setattr(terminal.models, "_load_runtime", lambda: (torch, Tokenizer, Model, None))
    encoder = terminal.TerminalEncoder(checkpoint, base, device=device)
    assert calls["tokenizer"] == (str(base), {"local_files_only": True,
                                              "trust_remote_code": False, "use_fast": True})
    assert calls["model"] == (str(checkpoint), {"local_files_only": True,
                                               "trust_remote_code": False, "use_safetensors": True,
                                               "torch_dtype": "float32",
                                               "attn_implementation": "eager"})
    assert encoder.batch_size == 8 and calls["device"] == device and calls["eval"]
    assert terminal.models.MAX_LENGTH == 512


def test_runtime_identity_cache_separation_auth_and_cleanup():
    encoder, reranker = FakeEncoder(), FakeEncoder()
    runtime = terminal.TerminalInferenceRuntime(encoder, reranker)
    original = InferenceRuntime(FakeEncoder(), FakeEncoder())
    request = EmbedRequest(schema_version=1, kind="passage", items=[{"id": "a", "text": "synthetic"}])
    original.embed(request)
    # A mistakenly reused base cache still cannot satisfy a terminal key.
    runtime.cache.update(original.cache)
    with TestClient(create_app(TOKEN, lambda: runtime)) as client:
        assert client.get("/health").status_code == 401
        health = client.get("/health", headers={"Authorization": "Bearer " + TOKEN}).json()
        terminal.validate_health(health, "cpu")
        first = runtime.embed(request)
        assert first["model"] == terminal.TERMINAL_MODEL
        assert first["revision"] == terminal.TERMINAL_REVISION
        assert first["telemetry"]["cache_misses"] == 1
        assert runtime.embed(request)["telemetry"]["cache_hits"] == 1
        assert encoder.calls == 1
        assert original.health()["embedding"]["revision"] != terminal.TERMINAL_REVISION
    assert encoder.closed and reranker.closed and not runtime.cache


def test_reranker_failure_closes_terminal_encoder(monkeypatch, tmp_path):
    encoder = FakeEncoder()
    monkeypatch.setattr(terminal, "preflight", lambda *_: ({}, tmp_path, {}))
    monkeypatch.setattr(terminal, "TerminalEncoder", lambda *args, **kwargs: encoder)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(terminal.models, "LocalBGEReranker", fail)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        terminal.TerminalInferenceRuntime.load(tmp_path, "cpu")
    assert encoder.closed


def test_drift_during_resident_loading_closes_both_models(monkeypatch, tmp_path):
    encoder, reranker = FakeEncoder(), FakeEncoder()
    calls = 0

    def preflight(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("model_file_hash_mismatch")
        return {}, tmp_path, {}

    monkeypatch.setattr(terminal, "preflight", preflight)
    monkeypatch.setattr(terminal, "TerminalEncoder", lambda *args, **kwargs: encoder)
    monkeypatch.setattr(terminal.models, "LocalBGEReranker", lambda *args, **kwargs: reranker)
    with pytest.raises(ValueError, match="model_file_hash_mismatch"):
        terminal.TerminalInferenceRuntime.load(tmp_path, "cpu")
    assert encoder.closed and reranker.closed
