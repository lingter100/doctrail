"""M5 v2: enforce greedy decoding across Transformers 4.57.6 config preparation.

The frozen v1 remains unchanged. Transformers treats False as a global default
and may replace it with the model's True unless use_model_defaults=False is
passed. v2 verifies the real preparation path both at load and during generate.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass

from doctrail.generation_runtime import MIB, RUNTIME, GenerationError
from doctrail.generation_runtime import GenerationResult as GenerationResultV1
from doctrail.generation_runtime import LocalGenerator as LocalGeneratorV1

EXPECTED_CONFIG = {
    "max_new_tokens": 384, "do_sample": False, "num_beams": 1, "num_return_sequences": 1,
    "temperature": 1.0, "top_k": 50, "top_p": 1.0, "typical_p": 1.0,
    "repetition_penalty": 1.0, "length_penalty": 1.0, "use_cache": True,
    "bos_token_id": 151643, "eos_token_id": [151645, 151643], "pad_token_id": 151643,
}


def verify_effective_config(config) -> dict:
    effective = {key: copy.deepcopy(getattr(config, key)) for key in EXPECTED_CONFIG}
    if effective != EXPECTED_CONFIG or config.get_generation_mode().value != "greedy_search":
        raise GenerationError("generation_effective_config_mismatch")
    return {**effective, "generation_mode": "greedy_search", "use_model_defaults": False}


@dataclass(frozen=True)
class GenerationResult(GenerationResultV1):
    effective_generation_config: dict


class LocalGenerator(LocalGeneratorV1):
    def _prepare_greedy(self):
        config = self._transformers.GenerationConfig(**copy.deepcopy(EXPECTED_CONFIG))
        effective, unused = self._model._prepare_generation_config(
            config, use_model_defaults=False,
        )
        if unused:
            raise GenerationError("generation_effective_config_unused_arguments")
        return effective, verify_effective_config(effective)

    def load(self):
        super().load()
        try:
            _, self._effective_generation_config = self._prepare_greedy()
        except GenerationError:
            self.close()
            raise
        except Exception:  # noqa: BLE001 - preserve safe third-party error boundary
            self.close()
            raise GenerationError("generation_effective_config_preflight_failed") from None
        return self

    def public_metadata(self):
        return {
            **super().public_metadata(), "generation_protocol": "m5-greedy-v2",
            "use_model_defaults": False,
            "effective_config_verified": hasattr(self, "_effective_generation_config"),
            "effective_generation_config": copy.deepcopy(
                getattr(self, "_effective_generation_config", None)
            ),
        }

    def generate(self, messages: list[dict[str, str]]) -> GenerationResult:
        if (
            not isinstance(messages, list) or not messages or len(messages) > 16
            or any(not isinstance(m, dict) or set(m) != {"role", "content"}
                   or not isinstance(m["role"], str)
                   or m["role"] not in {"system", "user", "assistant"}
                   or not isinstance(m["content"], str) for m in messages)
        ):
            raise GenerationError("invalid_generation_messages")
        if sum(len(m["content"]) for m in messages) > 100_000:
            raise GenerationError("generation_input_limit")
        self.load()
        torch = self._torch
        started = time.perf_counter()
        try:
            prompt = self._tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True, enable_thinking=False,
            )
            encoded = self._tokenizer(
                prompt, return_tensors="pt", truncation=False, add_special_tokens=False,
            )
            input_tokens = int(encoded["input_ids"].shape[-1])
            if input_tokens > RUNTIME["max_input_tokens"]:
                raise GenerationError("generation_input_limit")
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
            self._memory_check()
            encoded = {key: value.to(self.device) for key, value in encoded.items()}
            runtime = self

            class BudgetStop(self._transformers.StoppingCriteria):
                def __call__(self, input_ids, scores, **kwargs):
                    runtime._memory_check()
                    if time.perf_counter() - started >= RUNTIME["deadline_seconds"]:
                        raise GenerationError("generation_deadline_exceeded")
                    return False

            if time.perf_counter() - started >= RUNTIME["deadline_seconds"]:
                raise GenerationError("generation_deadline_exceeded")
            config, _ = self._prepare_greedy()
            # Observe the effective object actually prepared by generate(), not
            # merely the input object passed to it. No forward pass may precede
            # this assertion in the pinned Transformers implementation.
            model = self._model
            original_prepare = model._prepare_generation_config
            had_override = "_prepare_generation_config" in vars(model)
            old_override = vars(model).get("_prepare_generation_config")
            observed = []

            def checked_prepare(generation_config, use_model_defaults=None, **kwargs):
                if use_model_defaults is not False:
                    raise GenerationError("generation_model_defaults_enabled")
                actual, model_kwargs = original_prepare(
                    generation_config, use_model_defaults=use_model_defaults, **kwargs,
                )
                observed.append(verify_effective_config(actual))
                return actual, model_kwargs

            model._prepare_generation_config = checked_prepare
            try:
                with torch.inference_mode():
                    sequences = model.generate(
                        **encoded, generation_config=config, use_model_defaults=False,
                        stopping_criteria=self._transformers.StoppingCriteriaList([BudgetStop()]),
                    )
            finally:
                if had_override:
                    model._prepare_generation_config = old_override
                else:
                    del model._prepare_generation_config
            if len(observed) != 1:
                raise GenerationError("generation_effective_config_not_observed")
            torch.cuda.synchronize()
            self._memory_check()
            elapsed = time.perf_counter() - started
            if elapsed >= RUNTIME["deadline_seconds"]:
                raise GenerationError("generation_deadline_exceeded")
            token_ids = sequences[0, input_tokens:].tolist()
            if len(token_ids) > RUNTIME["max_new_tokens"]:
                raise GenerationError("generation_output_limit")
            eos_ids = set(observed[0]["eos_token_id"])
            if token_ids and token_ids[-1] in eos_ids:
                finish_reason = "eos"
            elif len(token_ids) == RUNTIME["max_new_tokens"]:
                finish_reason = "length"
            else:
                raise GenerationError("generation_unexpected_stop")
            decode_ids = token_ids[:-1] if finish_reason == "eos" else token_ids
            return GenerationResult(
                text=self._tokenizer.decode(
                    decode_ids, skip_special_tokens=False, clean_up_tokenization_spaces=False,
                ),
                finish_reason=finish_reason, input_tokens=input_tokens,
                output_tokens=len(token_ids), elapsed_seconds=elapsed,
                peak_allocated_mib=torch.cuda.max_memory_allocated() / MIB,
                peak_reserved_mib=torch.cuda.max_memory_reserved() / MIB,
                effective_generation_config=observed[0],
            )
        except GenerationError as error:
            error.telemetry = self._telemetry(started)
            if error.code != "generation_input_limit":
                self.close()
            raise
        except Exception as error:  # noqa: BLE001 - preserve safe third-party error boundary
            code = self._exception_code(error, "generation_failed")
            telemetry = self._telemetry(started)
            self.close()
            raise GenerationError(code, telemetry) from None
