"""Greedy-config regression: lightweight real library preparation, never inference."""
import copy
import importlib.util
from types import MethodType, SimpleNamespace

import pytest
import test_generation_runtime as shared

from doctrail import generation_runtime as v1
from doctrail import generation_runtime_v2 as v2

fake = shared.fake
snapshot = shared.snapshot


@pytest.fixture
def configured(fake):
    _, transformers = v1._load_runtime()
    model = transformers.AutoModelForCausalLM.from_pretrained("unused")
    fake.calls.clear()
    original_generate = model.generate
    fake.corrupt_actual = False
    fake.skip_prepare = False

    class Config:
        def __init__(self, **kwargs):
            self.__dict__.update(copy.deepcopy(v2.EXPECTED_CONFIG))
            self.__dict__.update(kwargs)

        def get_generation_mode(self):
            return SimpleNamespace(value="sample" if self.do_sample else "greedy_search")

    def prepare(instance, generation_config, use_model_defaults=None, **kwargs):
        actual = copy.deepcopy(generation_config)
        if use_model_defaults is not False:
            actual.do_sample = True
            actual.temperature = 0.6
            actual.top_k = 20
            actual.top_p = 0.95
        if fake.corrupt_actual and "input_ids" in kwargs:
            actual.do_sample = True
        return actual, kwargs

    def generate(instance, **kwargs):
        config = kwargs.pop("generation_config")
        defaults = kwargs.pop("use_model_defaults", None)
        fake.defaults_argument = defaults
        if not fake.skip_prepare:
            config, _ = instance._prepare_generation_config(config, defaults, **kwargs)
        return original_generate(generation_config=config, **kwargs)

    model._prepare_generation_config = MethodType(prepare, model)
    model.generate = MethodType(generate, model)
    transformers.GenerationConfig = Config
    fake.model = model
    return fake


def test_v2_observes_actual_greedy_configuration_and_restores_hook(snapshot, configured):
    original = configured.model._prepare_generation_config
    with v2.LocalGenerator(*snapshot) as generator:
        metadata = generator.public_metadata()
        assert metadata["effective_config_verified"] is True
        assert metadata["generation_protocol"] == "m5-greedy-v2"
        result = generator.generate([{"role": "user", "content": "q"}])
        assert configured.defaults_argument is False
        assert result.effective_generation_config["do_sample"] is False
        assert result.effective_generation_config["generation_mode"] == "greedy_search"
        assert result.effective_generation_config["temperature"] == 1.0
        assert result.effective_generation_config["top_k"] == 50
        assert configured.model._prepare_generation_config is original
        assert result.finish_reason == "eos"
        assert configured.decode["skip_special_tokens"] is False


def test_v2_asserts_effective_config_before_forward(snapshot, configured):
    configured.corrupt_actual = True
    original = configured.model._prepare_generation_config
    with pytest.raises(v1.GenerationError, match="generation_effective_config_mismatch"):
        v2.LocalGenerator(*snapshot).generate([{"role": "user", "content": "q"}])
    assert not hasattr(configured, "generate")
    assert configured.model._prepare_generation_config is original


def test_v2_requires_observation_from_actual_generate_path(snapshot, configured):
    configured.skip_prepare = True
    with pytest.raises(v1.GenerationError, match="generation_effective_config_not_observed"):
        v2.LocalGenerator(*snapshot).generate([{"role": "user", "content": "q"}])


def test_v2_restores_class_method_descriptor_used_by_real_models(snapshot, configured, monkeypatch):
    model = configured.model
    original_function = model._prepare_generation_config.__func__
    monkeypatch.setattr(type(model), "_prepare_generation_config", original_function, raising=False)
    del model._prepare_generation_config
    with v2.LocalGenerator(*snapshot) as generator:
        generator.generate([{"role": "user", "content": "q"}])
        assert "_prepare_generation_config" not in vars(model)
        assert model._prepare_generation_config.__func__ is original_function


@pytest.mark.parametrize("tokens,reason", [([42] * 384, "length"),
                                           ([42] * 383 + [151645], "eos")])
def test_v2_preserves_frozen_token_boundary(snapshot, configured, tokens, reason):
    configured.output = tokens
    with v2.LocalGenerator(*snapshot) as generator:
        result = generator.generate([{"role": "user", "content": "q"}])
        assert result.finish_reason == reason and result.output_tokens == 384


def test_v2_preserves_input_rejection_without_truncation(snapshot, configured):
    configured.input_tokens = 1537
    with (v2.LocalGenerator(*snapshot) as generator,
          pytest.raises(v1.GenerationError, match="generation_input_limit")):
        generator.generate([{"role": "user", "content": "q"}])
    assert not hasattr(configured, "generate")


@pytest.mark.skipif(importlib.util.find_spec("transformers") is None,
                    reason="Optional pinned retrieval group is not installed")
def test_real_transformers_4576_reproduces_v1_bug_and_proves_v2_fix():
    # Import and config preparation only: no model weights, forward pass, or CUDA call.
    import transformers
    from transformers import GenerationConfig
    from transformers.generation.utils import GenerationMixin

    assert transformers.__version__ == "4.57.6"
    model_defaults = GenerationConfig(
        do_sample=True, temperature=0.6, top_k=20, top_p=0.95,
        bos_token_id=151643, eos_token_id=[151645, 151643], pad_token_id=151643,
        transformers_version="4.51.0",
    )
    holder = SimpleNamespace(generation_config=model_defaults)
    config = GenerationConfig(**copy.deepcopy(v2.EXPECTED_CONFIG))
    wrong, _ = GenerationMixin._prepare_generation_config(holder, config)
    assert wrong.do_sample is True
    assert wrong.temperature == 0.6 and wrong.top_p == 0.95 and wrong.top_k == 20
    assert wrong.get_generation_mode().value == "sample"
    correct, unused = GenerationMixin._prepare_generation_config(
        holder, config, use_model_defaults=False,
    )
    assert unused == {}
    observed = v2.verify_effective_config(correct)
    assert observed["do_sample"] is False and observed["generation_mode"] == "greedy_search"
    assert observed["bos_token_id"] == 151643
    assert observed["eos_token_id"] == [151645, 151643]
    assert observed["pad_token_id"] == 151643
    assert model_defaults.do_sample is True  # Source model defaults were not mutated.
