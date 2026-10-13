"""Pinned local generation experiment; no network loading or service integration.

Limits are checked between decoding steps. A stalled CUDA kernel requires the
experiment runner's process watchdog; this is not a hard real-time deadline.
"""

from __future__ import annotations

import copy
import gc
import hashlib
import json
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "data/models/m5-generation-v1.json"
MODEL_ID = "Qwen/Qwen3-1.7B"
MODEL_REVISION = "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"
RUNTIME = {
    "device": "cuda", "dtype": "bfloat16", "attention_implementation": "eager",
    "max_input_tokens": 1536, "max_new_tokens": 384, "do_sample": False,
    "enable_thinking": False, "seed": 42, "max_reserved_mib": 5376,
    "deadline_seconds": 180,
}
ALLOWED_FILES = {
    "config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json",
    "vocab.json", "merges.txt", "LICENSE", "README.md", "model.safetensors.index.json",
    "model-00001-of-00002.safetensors", "model-00002-of-00002.safetensors",
}
MIB = 1024 * 1024


class GenerationError(RuntimeError):
    """Only a safe code crosses the runtime boundary, never a prompt or response."""

    def __init__(self, code: str, telemetry: dict | None = None):
        self.code = code
        self.telemetry = telemetry or {}
        super().__init__(code)


def safe_path(path: Path) -> Path:
    """Check lexical parents before resolution so junctions cannot disappear."""
    path = Path(path).absolute()
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise GenerationError("unsafe_model_path")
    return path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with safe_path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(MIB), b""):
            digest.update(block)
    return digest.hexdigest()


def load_generation_manifest(path: Path = DEFAULT_MANIFEST) -> dict:
    try:
        manifest = json.loads(safe_path(path).read_text(encoding="utf-8"))
        model = manifest["model"]
        files = model["files"]
        if (
            manifest["schema_version"] != 1 or model["repo_id"] != MODEL_ID
            or model["revision"] != MODEL_REVISION or model["license"] != "Apache-2.0"
            or manifest["runtime"] != RUNTIME or not isinstance(files, dict)
            or set(files) != ALLOWED_FILES
        ):
            raise GenerationError("unsupported_generation_manifest")
        for name, expected in files.items():
            if (
                name not in ALLOWED_FILES or type(expected["size_bytes"]) is not int
                or expected["size_bytes"] <= 0
                or not isinstance(expected["sha256"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", expected["sha256"])
            ):
                raise GenerationError("unsafe_model_manifest_file")
    except (KeyError, TypeError, ValueError, OSError):
        raise GenerationError("invalid_generation_manifest") from None
    return manifest


def verify_snapshot(snapshot: Path, model_spec: dict) -> dict[str, str]:
    root = safe_path(snapshot)
    if not root.is_dir():
        raise GenerationError("model_snapshot_missing")
    expected_files = model_spec["files"]
    if {entry.name for entry in root.iterdir()} != set(expected_files):
        raise GenerationError("unexpected_or_missing_model_file")
    verified = {}
    for name, expected in expected_files.items():
        if name not in ALLOWED_FILES:
            raise GenerationError("unsafe_model_manifest_file")
        path = safe_path(root / name)
        if not path.is_file() or path.stat().st_nlink != 1:
            raise GenerationError("unsafe_model_file")
        if path.stat().st_size != expected["size_bytes"]:
            raise GenerationError("model_file_size_mismatch")
        digest = file_sha256(path)
        if digest != expected["sha256"]:
            raise GenerationError("model_file_hash_mismatch")
        verified[name] = digest
    return verified


def _load_runtime():
    import torch
    import transformers

    return torch, transformers


@dataclass(frozen=True)
class GenerationResult:
    text: str
    finish_reason: str
    input_tokens: int
    output_tokens: int
    elapsed_seconds: float
    peak_allocated_mib: float
    peak_reserved_mib: float


class LocalGenerator:
    """Single-case, CUDA-only generator. Caller must serialize use and close it."""

    def __init__(self, snapshot: Path, manifest_path: Path = DEFAULT_MANIFEST,
                 device: str = "cuda"):
        if device != "cuda":
            raise GenerationError("unsupported_generation_device")
        self.snapshot = safe_path(snapshot)
        self._manifest = load_generation_manifest(manifest_path)
        self.device = device
        self._torch = self._transformers = self._model = self._tokenizer = None
        self.verified_files: dict[str, str] = {}
        self.load_metrics: dict = {}
        self._original_memory_fraction = None
        self._closed = False

    def public_metadata(self) -> dict:
        return {
            "repo_id": MODEL_ID, "revision": MODEL_REVISION,
            "license": "Apache-2.0", "runtime": copy.deepcopy(RUNTIME),
            "experimental": True, "measurement_scope": "python_local_generation",
        }

    def _memory_check(self):
        cuda = self._torch.cuda
        if max(cuda.memory_reserved(), cuda.max_memory_reserved()) > RUNTIME[
            "max_reserved_mib"
        ] * MIB:
            raise GenerationError("generation_memory_limit")

    def _telemetry(self, started: float) -> dict:
        result = {"elapsed_seconds": time.perf_counter() - started}
        if self._torch is not None and self._torch.cuda.is_available():
            result.update(
                peak_allocated_mib=self._torch.cuda.max_memory_allocated() / MIB,
                peak_reserved_mib=self._torch.cuda.max_memory_reserved() / MIB,
            )
        return result

    def load(self):
        if self._closed:
            raise GenerationError("generation_runtime_closed")
        if self._model is not None:
            return self
        self.verified_files = verify_snapshot(self.snapshot, self._manifest["model"])
        started = time.perf_counter()
        try:
            self._torch, self._transformers = _load_runtime()
            torch, transformers = self._torch, self._transformers
            if (torch.__version__.split("+")[0] != "2.10.0"
                    or transformers.__version__ != "4.57.6"):
                raise GenerationError("unsupported_generation_environment")
            if not torch.cuda.is_available():
                raise GenerationError("requested_cuda_unavailable")
            if not torch.cuda.is_bf16_supported(including_emulation=False):
                raise GenerationError("native_bfloat16_unavailable")
            torch.cuda.reset_peak_memory_stats()
            self._memory_check()
            total = torch.cuda.get_device_properties(self.device).total_memory
            self._original_memory_fraction = torch.cuda.get_per_process_memory_fraction()
            torch.cuda.set_per_process_memory_fraction(min(
                self._original_memory_fraction, RUNTIME["max_reserved_mib"] * MIB / total,
            ))
            torch.manual_seed(RUNTIME["seed"])
            self._tokenizer = transformers.AutoTokenizer.from_pretrained(
                str(self.snapshot), local_files_only=True, trust_remote_code=False, use_fast=True,
            )
            if not self._tokenizer.is_fast:
                raise GenerationError("fast_tokenizer_required")
            self._model = transformers.AutoModelForCausalLM.from_pretrained(
                str(self.snapshot), local_files_only=True, trust_remote_code=False,
                use_safetensors=True, torch_dtype=torch.bfloat16, attn_implementation="eager",
            ).to(self.device).eval()
            torch.cuda.synchronize()
            self._memory_check()
            if verify_snapshot(self.snapshot, self._manifest["model"]) != self.verified_files:
                raise GenerationError("model_changed_during_load")
            self.load_metrics = {
                "elapsed_seconds": time.perf_counter() - started,
                "peak_allocated_mib": torch.cuda.max_memory_allocated() / MIB,
                "peak_reserved_mib": torch.cuda.max_memory_reserved() / MIB,
            }
            return self
        except GenerationError as error:
            error.telemetry = self._telemetry(started)
            self.close()
            raise
        except Exception as error:  # noqa: BLE001 - sanitize third-party errors at privacy boundary
            code = self._exception_code(error, "generation_load_failed")
            telemetry = self._telemetry(started)
            self.close()
            raise GenerationError(code, telemetry) from None

    def _exception_code(self, error: Exception, default: str) -> str:
        if self._torch is not None and isinstance(error, self._torch.cuda.OutOfMemoryError):
            return "generation_out_of_memory"
        return default

    def generate(self, messages: list[dict[str, str]]) -> GenerationResult:
        if (
            not isinstance(messages, list) or not messages or len(messages) > 16
            or any(not isinstance(m, dict) or set(m) != {"role", "content"}
                   or not isinstance(m["role"], str)
                   or m["role"] not in {"system", "user", "assistant"}
                   or not isinstance(m["content"], str) for m in messages)
        ):
            raise GenerationError("invalid_generation_messages")
        # Bound host-side tokenization too; actual token count remains authoritative.
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
            # Replace model-supplied generation defaults so no sampling, repetition
            # penalty, beam settings, or hidden output expansion can leak into the run.
            config = self._transformers.GenerationConfig(
                max_new_tokens=RUNTIME["max_new_tokens"], do_sample=False, num_beams=1,
                use_cache=True, eos_token_id=self._model.generation_config.eos_token_id,
                pad_token_id=self._tokenizer.pad_token_id,
            )
            with torch.inference_mode():
                sequences = self._model.generate(
                    **encoded, generation_config=config,
                    stopping_criteria=self._transformers.StoppingCriteriaList([BudgetStop()]),
                )
            torch.cuda.synchronize()
            self._memory_check()
            elapsed = time.perf_counter() - started
            if elapsed >= RUNTIME["deadline_seconds"]:
                raise GenerationError("generation_deadline_exceeded")
            token_ids = sequences[0, input_tokens:].tolist()
            if len(token_ids) > RUNTIME["max_new_tokens"]:
                raise GenerationError("generation_output_limit")
            eos = config.eos_token_id
            eos_ids = {eos} if isinstance(eos, int) else set(eos or [])
            if token_ids and token_ids[-1] in eos_ids:
                finish_reason = "eos"
            elif len(token_ids) == RUNTIME["max_new_tokens"]:
                finish_reason = "length"
            else:
                raise GenerationError("generation_unexpected_stop")
            # Remove exactly the protocol's terminal EOS, preserving all other
            # emitted tokens. Dropping internal special tokens would silently
            # repair malformed output before the strict JSON/citation validator.
            decode_ids = token_ids[:-1] if finish_reason == "eos" else token_ids
            return GenerationResult(
                text=self._tokenizer.decode(
                    decode_ids, skip_special_tokens=False, clean_up_tokenization_spaces=False,
                ),
                finish_reason=finish_reason, input_tokens=input_tokens,
                output_tokens=len(token_ids), elapsed_seconds=elapsed,
                peak_allocated_mib=torch.cuda.max_memory_allocated() / MIB,
                peak_reserved_mib=torch.cuda.max_memory_reserved() / MIB,
            )
        except GenerationError as error:
            error.telemetry = self._telemetry(started)
            if error.code != "generation_input_limit":
                self.close()
            raise
        except Exception as error:  # noqa: BLE001 - sanitize third-party errors at privacy boundary
            code = self._exception_code(error, "generation_failed")
            telemetry = self._telemetry(started)
            self.close()
            raise GenerationError(code, telemetry) from None

    def close(self):
        self._model = self._tokenizer = None
        self._closed = True
        gc.collect()
        if self._torch is not None and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()
            if self._original_memory_fraction is not None:
                self._torch.cuda.set_per_process_memory_fraction(self._original_memory_fraction)
                self._original_memory_fraction = None

    def __enter__(self):
        return self.load()

    def __exit__(self, *_):
        self.close()
