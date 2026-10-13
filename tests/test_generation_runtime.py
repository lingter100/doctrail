"""Model-free adversarial checks: no Torch import, GPU, network, or real weights."""

import hashlib
import io
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from doctrail import generation_runtime as runtime
from scripts.prepare_generation_model import prepare_snapshot


@pytest.fixture
def snapshot(tmp_path):
    root = tmp_path / "snapshot"
    root.mkdir()
    files = {}
    for name in sorted(runtime.ALLOWED_FILES):
        payload = name.encode()
        (root / name).write_bytes(payload)
        files[name] = {"size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    manifest = {
        "schema_version": 1,
        "model": {"repo_id": runtime.MODEL_ID, "revision": runtime.MODEL_REVISION,
                  "license": "Apache-2.0", "files": files},
        "runtime": dict(runtime.RUNTIME),
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return root, path


class Tensor:
    def __init__(self, values):
        self.values = values
        self.shape = (1, len(values))

    def to(self, device):
        assert device == "cuda"
        return self

    def __getitem__(self, key):
        return Tensor(self.values[key[1]])

    def tolist(self):
        return self.values


@pytest.fixture
def fake(monkeypatch):
    state = SimpleNamespace(
        input_tokens=20, output=[42, 151645], calls=[], available=True, bf16=True,
        reserved=100, allocated=80, fraction=1.0, after_load=None, during_generate=None,
    )

    def loader(kind, value):
        def load(path, **kwargs):
            state.calls.append((kind, kwargs))
            if kind == "model" and state.after_load:
                state.after_load()
            return value
        return SimpleNamespace(from_pretrained=load)

    class Tokenizer:
        is_fast = True
        pad_token_id = 151643

        def apply_chat_template(self, messages, **kwargs):
            state.template = kwargs
            return "PRIVATE TEMPLATE"

        def __call__(self, prompt, **kwargs):
            state.tokenize = kwargs
            return {"input_ids": Tensor([1] * state.input_tokens),
                    "attention_mask": Tensor([1] * state.input_tokens)}

        def decode(self, ids, **kwargs):
            state.decoded_ids = ids
            state.decode = kwargs
            return "PRIVATE OUTPUT"

    class Model:
        generation_config = SimpleNamespace(eos_token_id=[151645, 151643])

        def to(self, device):
            assert device == "cuda"
            return self

        def eval(self):
            return self

        def generate(self, **kwargs):
            state.generate = kwargs
            if state.during_generate:
                state.during_generate()
            for stopper in kwargs["stopping_criteria"]:
                stopper(None, None)
            return Tensor([1] * state.input_tokens + state.output)

    cuda = SimpleNamespace(
        is_available=lambda: state.available,
        is_bf16_supported=lambda **kw: state.bf16 and not kw["including_emulation"],
        reset_peak_memory_stats=lambda: None,
        synchronize=lambda: None,
        memory_reserved=lambda: state.reserved * runtime.MIB,
        max_memory_reserved=lambda: state.reserved * runtime.MIB,
        max_memory_allocated=lambda: state.allocated * runtime.MIB,
        get_device_properties=lambda device: SimpleNamespace(total_memory=6144 * runtime.MIB),
        get_per_process_memory_fraction=lambda: state.fraction,
        set_per_process_memory_fraction=lambda v: setattr(state, "fraction", v),
        empty_cache=lambda: None,
        OutOfMemoryError=MemoryError,
    )
    torch = SimpleNamespace(
        __version__="2.10.0+cu128", bfloat16="BF16", cuda=cuda,
        manual_seed=lambda seed: setattr(state, "seed", seed), inference_mode=nullcontext,
    )
    transformers = SimpleNamespace(
        __version__="4.57.6", AutoTokenizer=loader("tokenizer", Tokenizer()),
        AutoModelForCausalLM=loader("model", Model()), StoppingCriteria=object,
        StoppingCriteriaList=list, GenerationConfig=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(runtime, "_load_runtime", lambda: (torch, transformers))
    state.torch = torch
    return state


def test_construct_does_not_import_inference_or_touch_network(snapshot, monkeypatch):
    monkeypatch.setattr(runtime, "_load_runtime", lambda: pytest.fail("unexpected inference import"))
    generator = runtime.LocalGenerator(*snapshot)
    metadata = generator.public_metadata()
    metadata["runtime"]["do_sample"] = True
    assert generator.public_metadata()["runtime"]["do_sample"] is False
    assert prepare_snapshot(*snapshot)["verified"] is True


@pytest.mark.parametrize("device", ["cpu", "cuda:1", "auto"])
def test_no_device_fallback(snapshot, device):
    with pytest.raises(runtime.GenerationError, match="unsupported_generation_device"):
        runtime.LocalGenerator(*snapshot, device=device)


@pytest.mark.parametrize("mutation", ["extra", "size", "hash", "missing", "hardlink"])
def test_snapshot_tampering_rejected_before_import(snapshot, monkeypatch, mutation):
    root, manifest = snapshot
    target = root / "config.json"
    if mutation == "extra":
        (root / "model.bin").write_bytes(b"pickle")
    elif mutation == "size":
        target.write_bytes(b"x")
    elif mutation == "hash":
        target.write_bytes(b"X" * target.stat().st_size)
    elif mutation == "missing":
        target.unlink()
    else:
        (root.parent / "linked.json").hardlink_to(target)
    monkeypatch.setattr(runtime, "_load_runtime", lambda: pytest.fail("unexpected inference import"))
    with pytest.raises(runtime.GenerationError):
        runtime.LocalGenerator(root, manifest).load()


def test_lexical_reparse_parent_rejected(tmp_path, monkeypatch):
    root = tmp_path / "junction"
    root.mkdir()
    original = Path.lstat

    def lstat(path):
        if path == root:
            return SimpleNamespace(st_mode=0, st_file_attributes=1024)
        return original(path)

    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(runtime.GenerationError, match="unsafe_model_path"):
        runtime.safe_path(root / "child")


def test_frozen_runtime_settings_reject_manifest_edit(snapshot):
    _, path = snapshot
    data = json.loads(path.read_text())
    data["runtime"]["do_sample"] = True
    path.write_text(json.dumps(data))
    with pytest.raises(runtime.GenerationError, match="unsupported_generation_manifest"):
        runtime.LocalGenerator(*snapshot)


@pytest.mark.parametrize("capability,code", [
    ("available", "requested_cuda_unavailable"), ("bf16", "native_bfloat16_unavailable"),
])
def test_hardware_requirement_fails_without_fallback(snapshot, fake, capability, code):
    setattr(fake, capability, False)
    with pytest.raises(runtime.GenerationError, match=code):
        runtime.LocalGenerator(*snapshot).load()
    assert not fake.calls


def test_environment_version_is_pinned(snapshot, fake):
    fake.torch.__version__ = "2.11.0"
    with pytest.raises(runtime.GenerationError, match="unsupported_generation_environment"):
        runtime.LocalGenerator(*snapshot).load()


def test_load_rechecks_snapshot_after_model_open(snapshot, fake):
    fake.after_load = lambda: (snapshot[0] / "config.json").write_bytes(b"tampered")
    with pytest.raises(runtime.GenerationError, match="model_file_size_mismatch"):
        runtime.LocalGenerator(*snapshot).load()
    assert fake.fraction == 1.0


def test_eos_generation_has_explicit_local_safe_settings(snapshot, fake, capsys):
    with runtime.LocalGenerator(*snapshot) as generator:
        result = generator.generate([{"role": "user", "content": "PRIVATE INPUT"}])
        assert result.finish_reason == "eos"
        assert result.input_tokens == 20 and result.output_tokens == 2
        assert result.text == "PRIVATE OUTPUT"
        assert result.peak_reserved_mib == 100
        assert fake.fraction == 5376 / 6144
        assert fake.template == {"tokenize": False, "add_generation_prompt": True,
                                 "enable_thinking": False}
        assert fake.tokenize["truncation"] is False
        assert fake.generate["generation_config"].max_new_tokens == 384
        assert fake.generate["generation_config"].do_sample is False
        assert fake.decoded_ids == [42]
        assert fake.decode == {
            "skip_special_tokens": False, "clean_up_tokenization_spaces": False,
        }
        assert fake.seed == 42
        for kind, kwargs in fake.calls:
            assert kwargs["local_files_only"] is True
            assert kwargs["trust_remote_code"] is False
            if kind == "model":
                assert kwargs["use_safetensors"] is True
                assert kwargs["torch_dtype"] == "BF16"
    assert fake.fraction == 1.0
    assert not capsys.readouterr().out
    with pytest.raises(runtime.GenerationError, match="generation_runtime_closed"):
        generator.load()


@pytest.mark.parametrize("tokens,reason", [([42] * 384, "length"),
                                           ([42] * 383 + [151645], "eos")])
def test_eos_at_cap_is_not_mislabeled_as_truncation(snapshot, fake, tokens, reason):
    fake.output = tokens
    with runtime.LocalGenerator(*snapshot) as generator:
        assert generator.generate([{"role": "user", "content": "q"}]).finish_reason == reason


@pytest.mark.parametrize("tokens,code", [([42] * 385, "generation_output_limit"),
                                         ([42], "generation_unexpected_stop")])
def test_broken_decode_contract_rejected(snapshot, fake, tokens, code):
    fake.output = tokens
    with pytest.raises(runtime.GenerationError, match=code):
        runtime.LocalGenerator(*snapshot).generate([{"role": "user", "content": "q"}])


def test_input_overflow_is_rejected_not_silently_truncated(snapshot, fake):
    fake.input_tokens = 1537
    with runtime.LocalGenerator(*snapshot) as generator:
        with pytest.raises(runtime.GenerationError, match="generation_input_limit"):
            generator.generate([{"role": "user", "content": "q"}])
        assert not hasattr(fake, "generate")
        fake.input_tokens = 1536
        assert generator.generate([{"role": "user", "content": "q"}]).input_tokens == 1536


def test_resource_failure_has_safe_metrics_and_no_retry(snapshot, fake):
    fake.during_generate = lambda: setattr(fake, "reserved", 5377)
    generator = runtime.LocalGenerator(*snapshot)
    with pytest.raises(runtime.GenerationError, match="generation_memory_limit") as failure:
        generator.generate([{"role": "user", "content": "SECRET"}])
    assert failure.value.telemetry["peak_reserved_mib"] == 5377
    assert "SECRET" not in str(failure.value)
    assert generator._closed


def test_deadline_failure_is_not_a_partial_answer(snapshot, fake, monkeypatch):
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(runtime.time, "perf_counter", lambda: clock.now)
    fake.during_generate = lambda: setattr(clock, "now", 181)
    with pytest.raises(runtime.GenerationError, match="generation_deadline_exceeded"):
        runtime.LocalGenerator(*snapshot).generate([{"role": "user", "content": "q"}])


def test_download_verifies_hash_without_loading_inference(snapshot, monkeypatch):
    root, manifest = snapshot
    payload = (root / "config.json").read_bytes()
    (root / "config.json").unlink()
    requests = []

    def open_url(request, timeout):
        requests.append(request.full_url)
        response = io.BytesIO(payload)
        response.url = request.full_url
        return response

    monkeypatch.setattr("scripts.prepare_generation_model.urllib.request.urlopen", open_url)
    assert prepare_snapshot(root, manifest, download=True)["verified"]
    assert requests == [(f"https://huggingface.co/{runtime.MODEL_ID}/resolve/"
                         f"{runtime.MODEL_REVISION}/config.json")]
    assert not list(root.parent.glob("*.partial"))


def test_corrupt_download_never_promoted(snapshot, monkeypatch):
    root, manifest = snapshot
    target = root / "config.json"
    payload = b"X" * target.stat().st_size
    target.unlink()

    def open_url(request, timeout):
        response = io.BytesIO(payload)
        response.url = request.full_url
        return response

    monkeypatch.setattr("scripts.prepare_generation_model.urllib.request.urlopen", open_url)
    with pytest.raises(runtime.GenerationError, match="model_download_hash_mismatch"):
        prepare_snapshot(root, manifest, download=True)
    assert not target.exists()
    assert not list(root.parent.glob("*.partial"))


def test_preexisting_partial_is_never_overwritten(snapshot):
    root, manifest = snapshot
    (root / "config.json").unlink()
    partial = root.parent / f".{root.name}.config.json.partial"
    partial.write_bytes(b"preserve")
    with pytest.raises(FileExistsError):
        prepare_snapshot(root, manifest, download=True)
    assert partial.read_bytes() == b"preserve"


def test_verify_missing_snapshot_does_not_download(snapshot, monkeypatch):
    (snapshot[0] / "config.json").unlink()
    monkeypatch.setattr("scripts.prepare_generation_model.urllib.request.urlopen",
                        lambda *a, **kw: pytest.fail("verify must not download"))
    with pytest.raises(runtime.GenerationError, match="unexpected_or_missing_model_file"):
        prepare_snapshot(*snapshot)


@pytest.mark.parametrize("exception,code", [
    (MemoryError("PRIVATE INPUT"), "generation_out_of_memory"),
    (RuntimeError("PRIVATE INPUT"), "generation_failed"),
])
def test_third_party_errors_are_sanitized_and_stop_runtime(snapshot, fake, exception, code):
    def fail():
        raise exception

    fake.during_generate = fail
    generator = runtime.LocalGenerator(*snapshot)
    with pytest.raises(runtime.GenerationError, match=code) as failure:
        generator.generate([{"role": "user", "content": "PRIVATE INPUT"}])
    assert str(failure.value) == code
    assert failure.value.telemetry["peak_reserved_mib"] == 100
    assert generator._closed


def test_preflight_memory_failure_does_not_load_model(snapshot, fake):
    fake.reserved = 5377
    with pytest.raises(runtime.GenerationError, match="generation_memory_limit"):
        runtime.LocalGenerator(*snapshot).load()
    assert not fake.calls


def test_malformed_messages_are_rejected_before_model_load(snapshot, monkeypatch):
    monkeypatch.setattr(runtime, "_load_runtime", lambda: pytest.fail("unexpected inference import"))
    with pytest.raises(runtime.GenerationError, match="invalid_generation_messages"):
        runtime.LocalGenerator(*snapshot).generate([{"role": "tool", "content": "secret"}])


@pytest.mark.parametrize("role", [[], {}, None, True, 1])
def test_malformed_role_types_have_safe_error_before_load(snapshot, monkeypatch, role):
    monkeypatch.setattr(runtime, "_load_runtime", lambda: pytest.fail("unexpected inference import"))
    with pytest.raises(runtime.GenerationError, match="invalid_generation_messages"):
        runtime.LocalGenerator(*snapshot).generate([{"role": role, "content": "secret"}])


@pytest.mark.parametrize("tokens,decoded", [
    ([42, 151644, 151643, 151645], [42, 151644, 151643]),
    ([42] * 383 + [151644], [42] * 383 + [151644]),
])
def test_decode_preserves_internal_special_tokens_and_removes_only_terminal_eos(
    snapshot, fake, tokens, decoded
):
    fake.output = tokens
    with runtime.LocalGenerator(*snapshot) as generator:
        result = generator.generate([{"role": "user", "content": "q"}])
        assert fake.decoded_ids == decoded
        assert fake.decode == {
            "skip_special_tokens": False, "clean_up_tokenization_spaces": False,
        }
        assert result.output_tokens == len(tokens)
