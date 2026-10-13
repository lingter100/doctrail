"""Explicit, checkpoint-bound experimental worker; no evaluation or training loaders."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path

from doctrail import model_retrieval as models
from doctrail.inference import InferenceRuntime, _validate_token, create_app

ROOT = Path(__file__).resolve().parents[2]
PROFILE = "m4-terminal-v1"
TERMINAL_MODEL = "doctrail/multilingual-e5-small-m4-terminal-v1"
TERMINAL_REVISION = "62e530d3094e98b336d039f10956c8e0e2a39d24d66b07818e92a46f0aac10fb"
MANIFEST_PATH = "data/models/m4-terminal-v1.json"
BASE_MANIFEST_PATH = "data/models/m3-models.json"
MAIN_DEV_PLAN_PATH = "data/evaluation/m4-main-dev-evaluation-v1.json"
MAIN_DEV_REPORT_PATH = "experiments/results/m4-main-dev-v1.json"
PUBLIC_BINDINGS = {
    MANIFEST_PATH: TERMINAL_REVISION,
    BASE_MANIFEST_PATH: "9140036af43711a12702ee6cf12d0ce2073acf7d9ef3269c3c297ad1dbe065a1",
    MAIN_DEV_PLAN_PATH: "756f13b8abf52afa4c1ddd4f4442ad42216fdc0b2c3deff5e23d4c46ab8a36d4",
    MAIN_DEV_REPORT_PATH: "03898eeab53b2c3e166b92dd62138a55f315c560fb2d3ad26c238ce1573be5f8",
}
CHECKPOINT_FILES = {"config.json", "model.safetensors", "special_tokens_map.json",
                    "tokenizer.json", "tokenizer_config.json"}


def _check(condition, code):
    if not condition:
        raise ValueError(code)


def _no_links(path: Path):
    # Windows junctions are reparse points too; reject redirected parent directories.
    for item in (path, *path.parents):
        _check(not item.is_symlink() and not (
            item.exists() and getattr(item.lstat(), "st_file_attributes", 0) & 0x400
        ), "linked_model_or_receipt_path")


def _read_bound(root, name, digest):
    path = root / name
    _no_links(path)
    _check(path.is_file(), "public_receipt_hash_mismatch")
    content = path.read_bytes()
    _check(hashlib.sha256(content).hexdigest() == digest, "public_receipt_hash_mismatch")
    return json.loads(content)


def validate_public_profile(root: Path = ROOT):
    """Check pinned public receipts only; never read questions, corpora or training packs."""
    root = Path(root)
    values = {name: _read_bound(root, name, digest) for name, digest in PUBLIC_BINDINGS.items()}
    checkpoint = values[MANIFEST_PATH]
    base = values[BASE_MANIFEST_PATH]["models"]["e5"]
    bindings = dict(PUBLIC_BINDINGS)
    for name, digest in checkpoint["inputs_sha256"].items():
        values[name] = _read_bound(root, name, digest)
        bindings[name] = digest
    train = values["experiments/results/m4-e5-train-v2.json"]
    report = values[MAIN_DEV_REPORT_PATH]
    plan = values[MAIN_DEV_PLAN_PATH]
    hashes = {name: value["sha256"] for name, value in checkpoint["files"].items()}
    _check(checkpoint["schema_version"] == 1
           and checkpoint["checkpoint_kind"] == "sole_terminal_after_16_verified_updates"
           and checkpoint["checkpoint_path"] == ".local/m4-e5-train-v2/terminal"
           and checkpoint["inference_tokenizer"] == "original_verified_base_snapshot"
           and checkpoint["base_repo_id"] == base["repo_id"]
           and checkpoint["base_revision"] == base["revision"] == train["base_revision"]
           and set(hashes) == CHECKPOINT_FILES
           and hashes == train["checkpoint_sha256"]
           and train["verified_base_files"] == {k: v["sha256"] for k, v in base["files"].items()}
           and train["status"] == "passed" and train["terminal_checkpoint_saved"] is True
           and train["optimizer_steps_verified"] == train["weight_updates_observed"] == 16,
           "terminal_training_identity_mismatch")
    _check(report["status"] == "passed" and report["comparison"]["quality_gate_passed"] is True
           and report["comparison"]["decision"] == "eligible_for_separate_operational_validation"
           and report["service_adoption"] is False and report["test_question_accessed"] is False
           and report["human_reviewed_questions"] == 0
           and report["model_files_before"]["terminal_fresh"] == hashes
           and report["model_files_after"]["terminal_fresh"] == hashes
           and plan["input_bindings"]["checkpoint"]["sha256"] == TERMINAL_REVISION,
           "terminal_main_dev_receipt_mismatch")
    return {"profile": PROFILE, "model": TERMINAL_MODEL, "revision": TERMINAL_REVISION,
            "checkpoint": checkpoint, "models": values[BASE_MANIFEST_PATH]["models"],
            "public_bindings": bindings}


def verify_local_snapshot(snapshot, spec, *, terminal=False):
    snapshot = Path(snapshot)
    _no_links(snapshot)
    _check(snapshot.is_dir(), "model_snapshot_missing")
    for item in snapshot.iterdir():
        _no_links(item)
        _check(item.is_file(), "nonregular_model_file")
    if terminal:
        _check({item.name for item in snapshot.iterdir()} == CHECKPOINT_FILES,
               "terminal_file_set_mismatch")
    return models.verify_snapshot(snapshot, spec)


def preflight(model_root, checkpoint=None):
    profile = validate_public_profile()
    location = Path(checkpoint) if checkpoint is not None else ROOT / profile["checkpoint"]["checkpoint_path"]
    verified = {
        "terminal": verify_local_snapshot(location, profile["checkpoint"], terminal=True),
        "base": verify_local_snapshot(Path(model_root) / "e5", profile["models"]["e5"]),
        "reranker": verify_local_snapshot(Path(model_root) / "reranker", profile["models"]["reranker"]),
    }
    return profile, location, verified


class TerminalEncoder(models.LocalE5Encoder):
    """Frozen E5 encoding, original tokenizer, only trained weights/config differ."""

    def __init__(self, checkpoint, base_snapshot, *, device="cuda"):
        _check(device in {"cpu", "cuda"}, "unsupported_device")
        profile = validate_public_profile()
        self.spec = profile["checkpoint"]
        self.verified_files = verify_local_snapshot(checkpoint, self.spec, terminal=True)
        self.verified_base_files = verify_local_snapshot(base_snapshot, profile["models"]["e5"])
        torch, tokenizer_class, encoder_class, _ = models._load_runtime()
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("requested_cuda_unavailable")
        self.torch, self.device, self.batch_size = torch, device, 8
        self.telemetry = {"tokenized_inputs": 0, "truncated_inputs": 0,
                          "tokens_before_truncation": 0, "max_tokens_before_truncation": 0}
        self.telemetry_inputs = []
        self.tokenizer = tokenizer_class.from_pretrained(
            str(base_snapshot), local_files_only=True, trust_remote_code=False, use_fast=True)
        _check(self.tokenizer.is_fast and self.tokenizer.truncation_side == "right",
               "fast_right_truncating_base_tokenizer_required")
        self.dtype = torch.float32
        self.model = encoder_class.from_pretrained(
            str(checkpoint), local_files_only=True, trust_remote_code=False, use_safetensors=True,
            torch_dtype=self.dtype, attn_implementation="eager").to(device).eval()
        try:
            verify_local_snapshot(checkpoint, self.spec, terminal=True)
            verify_local_snapshot(base_snapshot, profile["models"]["e5"])
        except BaseException:
            self.close()
            raise


class TerminalInferenceRuntime(InferenceRuntime):
    def __init__(self, encoder, reranker, *, cache_capacity=4096):
        super().__init__(encoder, reranker, cache_capacity=cache_capacity)
        self.specs = copy.deepcopy(self.specs)
        self.specs["e5"].update(repo_id=TERMINAL_MODEL, revision=TERMINAL_REVISION)

    @classmethod
    def load(cls, model_root: Path, device: str, checkpoint=None):
        _, location, before = preflight(model_root, checkpoint)
        encoder = TerminalEncoder(location, Path(model_root) / "e5", device=device)
        reranker = None
        try:
            reranker = models.LocalBGEReranker(Path(model_root) / "reranker", device=device)
            _, _, after = preflight(model_root, checkpoint)
            _check(before == after, "model_changed_during_loading")
        except BaseException:
            try:
                encoder.close()
            finally:
                if reranker is not None:
                    reranker.close()
            raise
        return cls(encoder, reranker)


def validate_health(health, device):
    base = models.load_model_manifest()["models"]["reranker"]
    _check(health.get("schema_version") == 1 and health.get("status") == "ready"
           and health.get("embedding") == {"model": TERMINAL_MODEL, "revision": TERMINAL_REVISION,
                                            "dimension": 384, "max_length": 512}
           and health.get("reranker") == {"model": base["repo_id"], "revision": base["revision"],
                                           "max_length": 512}
           and health.get("runtime") == {"device": device, "embedding_dtype": "torch.float32",
                                          "reranker_dtype": "torch.float16" if device == "cuda"
                                          else "torch.float32"}, "terminal_worker_identity_mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--model-root", type=Path, default=ROOT / "models")
    parser.add_argument("--checkpoint", type=Path)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.exit(2, "invalid_port\n")
    try:
        token = os.environ.get("DOCTRAIL_INFERENCE_TOKEN", "")
        _validate_token(token)
        os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                          TOKENIZERS_PARALLELISM="false")
        runtime = TerminalInferenceRuntime.load(args.model_root, args.device, args.checkpoint)
        app = create_app(token, lambda: runtime)
    except Exception:  # noqa: BLE001 - no local paths, request text or credentials in logs
        parser.exit(2, "terminal_inference_startup_failed\n")
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="critical")


if __name__ == "__main__":
    main()
