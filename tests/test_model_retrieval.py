"""Contract checks use synthetic values/stubs, not evidence of semantic quality."""

import hashlib
import io
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from doctrail.model_retrieval import (
    LocalBGEReranker,
    LocalE5Encoder,
    load_model_manifest,
    rank_scores,
    rrf_fuse,
    verify_snapshot,
)
from scripts.prepare_models import prepare_model


def candidates():
    return [{"chunk_id": key, "text": f"synthetic {key}"} for key in ["z", "a", "b", "c"]]


def test_rrf_rank_positions_not_incompatible_score_scales():
    rows = candidates()
    first = [{**rows[0], "score": 10000}, {**rows[1], "score": 100}]
    second = [{**rows[1], "score": -5}, {**rows[2], "score": -100}]
    result = rrf_fuse([first, second], rows, limit=10)
    assert [row["chunk_id"] for row in result] == ["a", "z", "b"]
    assert result[0]["score"] == pytest.approx(1 / 61 + 1 / 62)
    assert "score" not in rows[0]


def test_rrf_ties_follow_original_candidate_order_and_ignore_absent_rows():
    rows = candidates()
    result = rrf_fuse([[rows[1], rows[0]], [rows[0], rows[1]]], rows, limit=10)
    assert [row["chunk_id"] for row in result] == ["z", "a"]
    assert rrf_fuse([[], []], rows) == []


@pytest.mark.parametrize("ranking", [[{"chunk_id": "unknown"}], [{"chunk_id": "z"}] * 2])
def test_rrf_rejects_unknown_or_duplicate_ids(ranking):
    with pytest.raises(ValueError, match="invalid_rrf_ranking_id"):
        rrf_fuse([ranking], candidates())


def test_rank_scores_preserves_ties_and_rejects_nonfinite_or_wrong_dimensions():
    rows = candidates()
    assert [row["chunk_id"] for row in rank_scores([0, 1, 1, -1], rows)] == ["a", "b", "z", "c"]
    with pytest.raises(ValueError, match="nonfinite"):
        rank_scores([float("nan")] * 4, rows)
    with pytest.raises(ValueError, match="dimensions"):
        rank_scores([1], rows)


def spec_for(data):
    return {
        "repo_id": "synthetic/fixture", "revision": "0" * 40,
        "files": {"config.json": {
            "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        }},
    }


def test_snapshot_hashes_all_bytes_and_rejects_extra_executable_files(tmp_path):
    data = b'{"synthetic":true}'
    spec = spec_for(data)
    path = tmp_path / "config.json"
    path.write_bytes(data)
    assert verify_snapshot(tmp_path, spec) == {"config.json": hashlib.sha256(data).hexdigest()}
    path.write_bytes(data.replace(b"true", b"null"))
    with pytest.raises(ValueError, match="hash_mismatch"):
        verify_snapshot(tmp_path, spec)
    path.write_bytes(data)
    (tmp_path / "model.py").write_text("raise RuntimeError()")
    with pytest.raises(ValueError, match="unexpected_model_snapshot_file"):
        verify_snapshot(tmp_path, spec)


def test_snapshot_missing_and_traversal_rejected(tmp_path):
    spec = spec_for(b"test")
    with pytest.raises(ValueError, match="missing_or_unsafe"):
        verify_snapshot(tmp_path, spec)
    spec["files"]["../escape.json"] = spec["files"].pop("config.json")
    with pytest.raises(ValueError, match="missing_or_unsafe"):
        verify_snapshot(tmp_path, spec)


def test_prepare_atomic_hash_verification_and_reuse(tmp_path, monkeypatch):
    data = b'{"synthetic":true}'
    calls = []

    def response(request, timeout):
        calls.append(request.full_url)
        return io.BytesIO(data)

    monkeypatch.setattr("scripts.prepare_models.urllib.request.urlopen", response)
    spec = spec_for(data)
    receipt = prepare_model("e5", spec, tmp_path)
    assert receipt["revision"] == "0" * 40
    assert len(calls) == 1
    prepare_model("e5", spec, tmp_path)
    assert len(calls) == 1
    assert not list(tmp_path.rglob("*.partial"))


def test_prepare_corrupt_download_never_promoted(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.prepare_models.urllib.request.urlopen", lambda *a, **kw: io.BytesIO(b"evil")
    )
    with pytest.raises(ValueError, match="hash_mismatch"):
        prepare_model("e5", spec_for(b"safe"), tmp_path)
    assert not (tmp_path / "e5/config.json").exists()
    assert not list(tmp_path.rglob("*.partial"))


def test_manifest_pins_safetensors_and_complete_fast_tokenizer():
    for spec in load_model_manifest()["models"].values():
        assert len(spec["revision"]) == 40
        assert spec["max_length"] == 512
        assert set(spec["files"]) == {
            "model.safetensors", "config.json", "tokenizer.json",
            "tokenizer_config.json", "special_tokens_map.json",
        }
        assert all(len(file["sha256"]) == 64 for file in spec["files"].values())


def test_e5_prefix_contract_without_model_weights(monkeypatch):
    encoder = LocalE5Encoder.__new__(LocalE5Encoder)
    monkeypatch.setattr(encoder, "_encode", lambda texts, prefix: [prefix + t for t in texts])
    assert encoder.encode_queries(["synthetic 질문"]) == ["query: synthetic 질문"]
    assert encoder.encode_passages(["synthetic 본문"]) == ["passage: synthetic 본문"]


def test_truncation_accounting_is_explicit():
    encoder = LocalE5Encoder.__new__(LocalE5Encoder)
    encoder.telemetry_inputs = []
    encoder.telemetry = {
        "tokenized_inputs": 0, "truncated_inputs": 0,
        "tokens_before_truncation": 0, "max_tokens_before_truncation": 0,
    }
    encoder._record_lengths([10, 512, 513])
    encoder._record_lengths([3])
    assert encoder.telemetry == {
        "tokenized_inputs": 4, "truncated_inputs": 1,
        "tokens_before_truncation": 1038, "max_tokens_before_truncation": 513,
    }
    assert encoder.telemetry_inputs == [
        {"tokens_before_truncation": 10, "truncated": False},
        {"tokens_before_truncation": 512, "truncated": False},
        {"tokens_before_truncation": 513, "truncated": True},
        {"tokens_before_truncation": 3, "truncated": False},
    ]


@pytest.mark.parametrize(
    ("method", "characters", "error"),
    [
        ("encode_queries", 503, "stub_reached_tensor_encoding"),
        ("encode_queries", 504, "e5_query_too_long"),
        ("encode_passages", 504, "stub_reached_tensor_encoding"),
    ],
)
def test_e5_query_limit_counts_prefix_and_special_tokens(method, characters, error):
    class Tokenizer:
        def __call__(self, texts, **kwargs):
            if kwargs.get("return_tensors"):
                raise ValueError("stub_reached_tensor_encoding")
            # Synthetic character tokenizer with two special tokens. The raw
            # 504-char query fits alone, but prefix + special tokens total 513.
            return {"input_ids": [[1] * (len(text) + 2) for text in texts]}

    encoder = LocalE5Encoder.__new__(LocalE5Encoder)
    encoder.tokenizer, encoder.batch_size = Tokenizer(), 8
    encoder.telemetry_inputs = []
    encoder.telemetry = {
        "tokenized_inputs": 0, "truncated_inputs": 0,
        "tokens_before_truncation": 0, "max_tokens_before_truncation": 0,
    }
    with pytest.raises(ValueError, match=error):
        getattr(encoder, method)(["x" * characters])
    if error == "e5_query_too_long":
        assert encoder.telemetry_inputs == []


def test_reranker_never_silently_truncates_query():
    class Tokenizer:
        def __call__(self, text, **kwargs):
            return {"input_ids": [1] * 508}

        def num_special_tokens_to_add(self, pair):
            return 4

    reranker = LocalBGEReranker.__new__(LocalBGEReranker)
    reranker.tokenizer = Tokenizer()
    with pytest.raises(ValueError, match="reranker_query_too_long"):
        reranker.rerank("synthetic", candidates())


def test_reranker_preserves_query_and_raw_logit_order_with_stub_runtime():
    calls = []

    class Encoded(dict):
        def to(self, device):
            return self

    class Tokenizer:
        def __call__(self, query, passages=None, **kwargs):
            calls.append(kwargs)
            if passages is None:
                return {"input_ids": [1, 2]}
            if kwargs.get("return_tensors"):
                return Encoded(input_ids=[[1]] * len(query))
            return {"input_ids": [[1] * 520 for _ in query]}

        def num_special_tokens_to_add(self, pair):
            return 4

    class Logits:
        shape = (2, 1)

        def __getitem__(self, key):
            return self

        def float(self):
            return self

        def cpu(self):
            return self

        def tolist(self):
            return [-10, -2]

    reranker = LocalBGEReranker.__new__(LocalBGEReranker)
    reranker.tokenizer = Tokenizer()
    reranker.device, reranker.batch_size = "cpu", 2
    reranker.torch = SimpleNamespace(inference_mode=nullcontext)
    reranker.model = lambda **kwargs: SimpleNamespace(logits=Logits())
    reranker.telemetry = {
        "tokenized_inputs": 0, "truncated_inputs": 0,
        "tokens_before_truncation": 0, "max_tokens_before_truncation": 0,
    }
    reranker.telemetry_inputs = []
    result = reranker.rerank("synthetic", candidates()[:2])
    assert [row["score"] for row in result] == [-2, -10]
    assert [row["chunk_id"] for row in result] == ["a", "z"]
    assert calls[-1]["truncation"] == "only_second"
    assert calls[-1]["max_length"] == 512
    assert reranker.telemetry["truncated_inputs"] == 2


def test_exact_cosine_not_vector_magnitude_when_numpy_available():
    pytest.importorskip("numpy")
    from doctrail.model_retrieval import rank_dense

    rows = candidates()[:3]
    result = rank_dense([1, 0], [[1, 1], [20, 20], [-2, 0]], rows)
    assert [row["chunk_id"] for row in result] == ["z", "a", "b"]
    assert result[0]["score"] == pytest.approx(2 ** -0.5)
    assert result[2]["score"] == pytest.approx(-1)
    with pytest.raises(ValueError, match="zero_embedding"):
        rank_dense([0, 0], [[1, 1]], rows[:1])


def test_masked_mean_excludes_padding_when_torch_available():
    torch = pytest.importorskip("torch")
    from doctrail.model_retrieval import masked_mean_pool

    hidden = torch.tensor([[[2, 4], [4, 8], [999, 999]]], dtype=torch.float16)
    result = masked_mean_pool(hidden, torch.tensor([[1, 1, 0]]))
    assert result.dtype == torch.float32
    assert result.tolist() == [[3, 6]]
