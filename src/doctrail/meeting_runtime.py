"""Experimental meeting inference, independent of frozen M5 experiment protocols."""
from __future__ import annotations

import copy
import time

from doctrail.generation_runtime import MIB, GenerationError, GenerationResult
from doctrail.generation_runtime_v2 import EXPECTED_CONFIG, LocalGenerator

PROTOCOL = "meeting-full-chunk-evidence-v5"
MAX_INPUT_TOKENS = 4096
MAX_NEW_TOKENS = 768
DEADLINE_SECONDS = 120


class MeetingGenerator(LocalGenerator):
    """Reuse the verified offline loader; never mutate frozen module constants."""

    def load(self):
        super().load()
        config = self._transformers.GenerationConfig(
            **{**copy.deepcopy(EXPECTED_CONFIG), "max_new_tokens": MAX_NEW_TOKENS}
        )
        actual, unused = self._model._prepare_generation_config(config, use_model_defaults=False)
        if unused:
            raise GenerationError("generation_effective_config_unused_arguments")
        self._effective_generation_config = self._meeting_config(actual)
        return self

    def public_metadata(self):
        result = super().public_metadata()
        result["generation_protocol"] = PROTOCOL
        result["runtime"] = {**result["runtime"], "max_input_tokens": MAX_INPUT_TOKENS,
                             "max_new_tokens": MAX_NEW_TOKENS,
                             "deadline_seconds": DEADLINE_SECONDS}
        return result

    def count_tokens(self, messages):
        return len(self._tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True, enable_thinking=False,
        ))

    def classify_bounded(self, prompts, deadline):
        """Actual Qwen conditional next-token classification over ten explicit labels.

        Restricting the label space is a decoding constraint, not regex inference.
        Confidence is conditional within these labels, never calibrated probability.
        """
        started = time.monotonic()
        self.last_effective_config = None
        torch = self._torch
        codes = [self._tokenizer.encode(str(index), add_special_tokens=False)
                 for index in range(10)]
        if any(len(code) != 1 for code in codes):
            raise GenerationError("generation_label_token_mismatch")
        code_ids = torch.tensor([code[0] for code in codes], device=self.device)
        texts = [self._tokenizer.apply_chat_template(prompt, tokenize=False,
                    add_generation_prompt=True, enable_thinking=False) for prompt in prompts]
        lengths = [len(self._tokenizer.encode(text, add_special_tokens=False)) for text in texts]
        if any(length > MAX_INPUT_TOKENS for length in lengths):
            raise GenerationError("generation_input_limit")
        results = []
        total_tokens = 0
        batches = 0
        torch.cuda.reset_peak_memory_stats()
        original_padding = self._tokenizer.padding_side
        self._tokenizer.padding_side = "left"
        try:
            cursor = 0
            while cursor < len(texts):
                if time.monotonic() >= deadline:
                    raise GenerationError("generation_deadline_exceeded")
                batch_size = min(4, len(texts) - cursor)
                if max(lengths[cursor:cursor + batch_size]) > 768:
                    batch_size = 1
                batch = texts[cursor:cursor + batch_size]
                encoded = self._tokenizer(batch, return_tensors="pt", padding=True,
                                          truncation=False, add_special_tokens=False)
                encoded = {key: value.to(self.device) for key, value in encoded.items()}
                self._memory_check()
                with torch.inference_mode():
                    output = self._model(**encoded, use_cache=False, logits_to_keep=1)
                    logits = output.logits[:, -1, :].index_select(-1, code_ids).float()
                    probabilities = torch.softmax(logits, dim=-1)
                    values, indexes = probabilities.max(dim=-1)
                    results.extend({"label": int(index), "label_score": float(value)}
                                   for index, value in zip(indexes.tolist(), values.tolist(), strict=True))
                del output, encoded, logits, probabilities
                torch.cuda.synchronize()
                self._memory_check()
                total_tokens += sum(lengths[cursor:cursor + batch_size])
                batches += 1
                cursor += batch_size
            if time.monotonic() >= deadline:
                raise GenerationError("generation_deadline_exceeded")
            return results, {"operation": "restricted_next_token_classification",
                "label_count": 10, "selection": "argmax", "use_cache": False,
                "logits_to_keep": 1,
                "input_tokens": total_tokens, "output_tokens": len(results),
                "forward_batches": batches,
                "elapsed_seconds": time.monotonic() - started,
                "peak_allocated_mib": torch.cuda.max_memory_allocated() / MIB,
                "peak_reserved_mib": torch.cuda.max_memory_reserved() / MIB}
        except GenerationError:
            raise
        except Exception as error:  # noqa: BLE001 - sanitized model boundary
            raise GenerationError(self._exception_code(error, "generation_failed")) from None
        finally:
            self._tokenizer.padding_side = original_padding

    def _meeting_config(self, config):
        expected = {**copy.deepcopy(EXPECTED_CONFIG), "max_new_tokens": MAX_NEW_TOKENS}
        actual = {key: copy.deepcopy(getattr(config, key)) for key in expected}
        if actual != expected or config.get_generation_mode().value != "greedy_search":
            raise GenerationError("generation_effective_config_mismatch")
        return {**actual, "generation_mode": "greedy_search", "use_model_defaults": False}

    def generate_bounded(self, messages, deadline):
        started = time.monotonic()
        if started >= deadline:
            raise GenerationError("generation_deadline_exceeded")
        torch = self._torch
        try:
            prompt = self._tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True, enable_thinking=False,
            )
            encoded = self._tokenizer(prompt, return_tensors="pt", truncation=False,
                                      add_special_tokens=False)
            input_tokens = int(encoded["input_ids"].shape[-1])
            if input_tokens > MAX_INPUT_TOKENS:
                raise GenerationError("generation_input_limit")
            torch.cuda.reset_peak_memory_stats()
            self._memory_check()
            encoded = {key: value.to(self.device) for key, value in encoded.items()}
            runtime = self

            class BudgetStop(self._transformers.StoppingCriteria):
                def __call__(self, input_ids, scores, **kwargs):
                    runtime._memory_check()
                    if time.monotonic() >= deadline:
                        raise GenerationError("generation_deadline_exceeded")
                    return False

            config = self._transformers.GenerationConfig(
                **{**copy.deepcopy(EXPECTED_CONFIG), "max_new_tokens": MAX_NEW_TOKENS}
            )
            model = self._model
            original = model._prepare_generation_config
            observed = []

            def checked(config, use_model_defaults=None, **kwargs):
                if use_model_defaults is not False:
                    raise GenerationError("generation_model_defaults_enabled")
                actual, extra = original(config, use_model_defaults=False, **kwargs)
                observed.append(self._meeting_config(actual))
                return actual, extra

            model._prepare_generation_config = checked
            try:
                with torch.inference_mode():
                    sequences = model.generate(
                        **encoded, generation_config=config, use_model_defaults=False,
                        stopping_criteria=self._transformers.StoppingCriteriaList([BudgetStop()]),
                    )
            finally:
                del model._prepare_generation_config
            torch.cuda.synchronize()
            self._memory_check()
            if time.monotonic() >= deadline:
                raise GenerationError("generation_deadline_exceeded")
            if len(observed) != 1:
                raise GenerationError("generation_effective_config_not_observed")
            self.last_effective_config = observed[0]
            tokens = sequences[0, input_tokens:].tolist()
            finish = "eos" if tokens and tokens[-1] in EXPECTED_CONFIG["eos_token_id"] else "length"
            return GenerationResult(
                text=self._tokenizer.decode(tokens[:-1] if finish == "eos" else tokens,
                    skip_special_tokens=False, clean_up_tokenization_spaces=False),
                finish_reason=finish, input_tokens=input_tokens, output_tokens=len(tokens),
                elapsed_seconds=time.monotonic() - started,
                peak_allocated_mib=torch.cuda.max_memory_allocated() / MIB,
                peak_reserved_mib=torch.cuda.max_memory_reserved() / MIB,
            )
        except GenerationError:
            raise
        except Exception as error:  # noqa: BLE001 - no raw third-party error crosses boundary
            raise GenerationError(self._exception_code(error, "generation_failed")) from None
