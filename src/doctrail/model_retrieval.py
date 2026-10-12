"""Offline experimental retrieval. Callers must enforce visibility before ranking.

Heavy inference dependencies are imported only when a model is explicitly opened.
There is no network loading, device fallback, generated answer, or model training.
"""

from __future__ import annotations

import gc
import hashlib
import json
import math
from pathlib import Path

DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "data/models/m3-models.json"
MAX_LENGTH = 512


def load_model_manifest(path: Path = DEFAULT_MANIFEST) -> dict:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported_model_manifest")
    return manifest


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_snapshot(snapshot: Path, model_spec: dict) -> dict[str, str]:
    """Validate every required file, including tokenizer and configuration bytes."""
    root = Path(snapshot).resolve()
    verified = {}
    for name, expected in model_spec["files"].items():
        path = (root / name).resolve()
        if path.parent != root or not path.is_file():
            raise ValueError("model_file_missing_or_unsafe")
        if path.stat().st_size != expected["size_bytes"]:
            raise ValueError("model_file_size_mismatch")
        actual = file_sha256(path)
        if actual != expected["sha256"]:
            raise ValueError("model_file_hash_mismatch")
        verified[name] = actual
    # A local directory is loaded instead of a Hub identifier. Reject executable
    # additions and alternate weight formats to keep that loading boundary narrow.
    allowed = set(model_spec["files"]) | {"verification.json"}
    if any(path.name not in allowed for path in root.iterdir()):
        raise ValueError("unexpected_model_snapshot_file")
    return verified


def rank_scores(scores, candidates: list[dict], limit: int = 10) -> list[dict]:
    if limit < 0 or len(scores) != len(candidates):
        raise ValueError("invalid_ranking_dimensions")
    values = [float(score) for score in scores]
    if not all(math.isfinite(score) for score in values):
        raise ValueError("nonfinite_retrieval_score")
    order = sorted(range(len(candidates)), key=lambda index: (-values[index], index))
    return [{**candidates[index], "score": values[index]} for index in order[:limit]]


def rank_dense(query_embedding, passage_embeddings, candidates, limit: int = 10) -> list[dict]:
    """Exact cosine over the supplied corpus; ties retain its original order."""
    import numpy as np

    query = np.asarray(query_embedding, dtype=np.float32)
    passages = np.asarray(passage_embeddings, dtype=np.float32)
    if query.ndim != 1 or passages.ndim != 2 or passages.shape != (len(candidates), query.size):
        raise ValueError("invalid_embedding_dimensions")
    if not np.isfinite(query).all() or not np.isfinite(passages).all():
        raise ValueError("nonfinite_embedding")
    query_norm = np.linalg.norm(query)
    passage_norms = np.linalg.norm(passages, axis=1)
    if query_norm <= 0 or np.any(passage_norms <= 0):
        raise ValueError("zero_embedding")
    scores = (passages @ query) / (passage_norms * query_norm)
    return rank_scores(scores, candidates, limit)


def rrf_fuse(rankings: list[list[dict]], candidates: list[dict], limit=10, k=60) -> list[dict]:
    """Unweighted RRF; absent chunks contribute zero and are not returned."""
    if k <= 0 or limit < 0:
        raise ValueError("invalid_rrf_parameter")
    ids = [row["chunk_id"] for row in candidates]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate_candidate_id")
    scores = {}
    allowed = set(ids)
    for ranking in rankings:
        seen = set()
        for rank, row in enumerate(ranking, start=1):
            chunk_id = row["chunk_id"]
            if chunk_id not in allowed or chunk_id in seen:
                raise ValueError("invalid_rrf_ranking_id")
            seen.add(chunk_id)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (k + rank)
    included = [row for row in candidates if row["chunk_id"] in scores]
    return rank_scores([scores[row["chunk_id"]] for row in included], included, limit)


def _load_runtime():
    import torch
    from transformers import AutoModel, AutoModelForSequenceClassification, AutoTokenizer

    return torch, AutoTokenizer, AutoModel, AutoModelForSequenceClassification


def masked_mean_pool(last_hidden_state, attention_mask):
    """Exclude padding before mean pooling; preserve FP32 accumulation."""
    mask = attention_mask.unsqueeze(-1).bool()
    hidden = last_hidden_state.float().masked_fill(~mask, 0.0)
    return hidden.sum(dim=1) / mask.sum(dim=1).clamp(min=1)


class _LocalModel:
    model_key: str

    def __init__(self, snapshot: Path, device: str, batch_size: int):
        if batch_size < 1:
            raise ValueError("invalid_batch_size")
        self.spec = load_model_manifest()["models"][self.model_key]
        self.verified_files = verify_snapshot(Path(snapshot), self.spec)
        torch, tokenizer_class, encoder_class, reranker_class = _load_runtime()
        if device not in {"cpu", "cuda"}:
            raise ValueError("unsupported_device")
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("requested_cuda_unavailable")
        self.torch, self.device, self.batch_size = torch, device, batch_size
        self.telemetry = {
            "tokenized_inputs": 0,
            "truncated_inputs": 0,
            "tokens_before_truncation": 0,
            "max_tokens_before_truncation": 0,
        }
        self.telemetry_inputs: list[dict] = []
        self.tokenizer = tokenizer_class.from_pretrained(
            str(snapshot), local_files_only=True, trust_remote_code=False, use_fast=True
        )
        if not self.tokenizer.is_fast:
            raise RuntimeError("fast_tokenizer_required")
        self.dtype = torch.float16 if self.model_key == "reranker" and device == "cuda" else torch.float32
        model_class = encoder_class if self.model_key == "e5" else reranker_class
        self.model = model_class.from_pretrained(
            str(snapshot), local_files_only=True, trust_remote_code=False,
            use_safetensors=True, torch_dtype=self.dtype, attn_implementation="eager",
        ).to(device).eval()

    def _record_lengths(self, lengths):
        self.telemetry_inputs.extend(
            {"tokens_before_truncation": length, "truncated": length > MAX_LENGTH}
            for length in lengths
        )
        self.telemetry["tokenized_inputs"] += len(lengths)
        self.telemetry["truncated_inputs"] += sum(length > MAX_LENGTH for length in lengths)
        self.telemetry["tokens_before_truncation"] += sum(lengths)
        self.telemetry["max_tokens_before_truncation"] = max(
            [self.telemetry["max_tokens_before_truncation"], *lengths]
        )

    def synchronize(self):
        if self.device == "cuda":
            self.torch.cuda.synchronize()

    def close(self):
        self.synchronize()
        self.model = None
        self.tokenizer = None
        gc.collect()
        if self.device == "cuda":
            self.torch.cuda.empty_cache()


class LocalE5Encoder(_LocalModel):
    model_key = "e5"

    def __init__(self, snapshot: Path, device: str = "cuda", batch_size: int = 8):
        super().__init__(snapshot, device, batch_size)

    def _encode(self, texts: list[str], prefix: str):
        vectors = []
        for offset in range(0, len(texts), self.batch_size):
            batch = [prefix + text for text in texts[offset:offset + self.batch_size]]
            token_ids = self.tokenizer(batch, truncation=False, padding=False)["input_ids"]
            lengths = [len(ids) for ids in token_ids]
            if prefix == "query: " and any(length > MAX_LENGTH for length in lengths):
                raise ValueError("e5_query_too_long")
            self._record_lengths(lengths)
            encoded = self.tokenizer(
                batch, max_length=MAX_LENGTH, truncation=True, padding=True, return_tensors="pt"
            ).to(self.device)
            with self.torch.inference_mode():
                outputs = self.model(**encoded)
                pooled = masked_mean_pool(outputs.last_hidden_state, encoded["attention_mask"])
                normalized = self.torch.nn.functional.normalize(pooled, p=2, dim=1)
                vectors.append(normalized.cpu().numpy())
        import numpy as np

        if not vectors:
            return np.empty((0, self.model.config.hidden_size), dtype=np.float32)
        return np.concatenate(vectors, axis=0)

    def encode_passages(self, texts: list[str]):
        return self._encode(texts, "passage: ")

    def encode_queries(self, texts: list[str]):
        return self._encode(texts, "query: ")


class LocalBGEReranker(_LocalModel):
    model_key = "reranker"

    def __init__(self, snapshot: Path, device: str = "cuda", batch_size: int = 1):
        super().__init__(snapshot, device, batch_size)

    def rerank(self, query: str, candidates: list[dict], limit: int = 10) -> list[dict]:
        query_tokens = self.tokenizer(query, add_special_tokens=False)["input_ids"]
        overhead = self.tokenizer.num_special_tokens_to_add(pair=True)
        if len(query_tokens) + overhead >= MAX_LENGTH:
            raise ValueError("reranker_query_too_long")
        scores = []
        for offset in range(0, len(candidates), self.batch_size):
            batch = candidates[offset:offset + self.batch_size]
            queries, passages = [query] * len(batch), [row["text"] for row in batch]
            lengths = self.tokenizer(
                queries, passages, truncation=False, padding=False
            )["input_ids"]
            self._record_lengths([len(ids) for ids in lengths])
            encoded = self.tokenizer(
                queries, passages, max_length=MAX_LENGTH, truncation="only_second",
                padding=True, return_tensors="pt",
            ).to(self.device)
            with self.torch.inference_mode():
                logits = self.model(**encoded).logits
                if tuple(logits.shape) != (len(batch), 1):
                    raise ValueError("unexpected_reranker_logits_shape")
                scores.extend(logits[:, 0].float().cpu().tolist())
        return rank_scores(scores, candidates, limit)
