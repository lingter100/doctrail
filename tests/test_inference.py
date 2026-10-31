"""Synthetic fake-model contract checks; these do not measure retrieval quality."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from doctrail.inference import (
    DIMENSION,
    MAX_BODY_BYTES,
    InferenceRuntime,
    create_app,
)

TOKEN = "synthetic-test-token-" + "x" * 32
HEADERS = {"Authorization": "Bearer " + TOKEN}


class FakeEncoder:
    """Deliberately synthetic vectors; no model dependencies or weights required."""

    device, dtype = "synthetic", "synthetic"

    def __init__(self):
        self.telemetry_inputs = []
        self.telemetry = {"truncated_inputs": 0, "tokenized_inputs": 0}
        self.passage_calls, self.query_calls = [], []
        self.output = None
        self.error = None
        self.closed = False
        self.entered = self.release = None

    def _encode(self, texts):
        self.telemetry_inputs.extend({"synthetic": True} for _ in texts)
        self.telemetry["tokenized_inputs"] += len(texts)
        if self.entered:
            self.entered.set()
            assert self.release.wait(timeout=5)
        if self.error:
            raise self.error
        return self.output if self.output is not None else [
            [float(len(text)), *([0.0] * (DIMENSION - 1))] for text in texts
        ]

    def encode_queries(self, texts):
        self.query_calls.append(list(texts))
        return self._encode(texts)

    def encode_passages(self, texts):
        self.passage_calls.append(list(texts))
        return self._encode(texts)

    def close(self):
        self.closed = True


class FakeReranker(FakeEncoder):
    def rerank(self, query, candidates, limit):
        self.telemetry_inputs.append({"synthetic": True})
        if self.error:
            raise self.error
        if self.output is not None:
            return self.output
        return [{**row, "score": float(index)}
                for index, row in reversed(list(enumerate(candidates)))]


@pytest.fixture
def worker():
    encoder, reranker = FakeEncoder(), FakeReranker()
    runtime = InferenceRuntime(encoder, reranker, cache_capacity=2)
    with TestClient(create_app(TOKEN, lambda: runtime)) as client:
        yield client, runtime, encoder, reranker
    assert encoder.closed and reranker.closed
    assert not runtime.cache


def embed_payload(texts, kind="passage"):
    return {"schema_version": 1, "kind": kind,
            "items": [{"id": f"id-{index}", "text": text}
                      for index, text in enumerate(texts)]}


def post(client, payload, path="/embed"):
    return client.post(path, json=payload, headers=HEADERS)


def test_all_endpoints_require_shared_token_and_docs_disabled(worker):
    client, *_ = worker
    for path in ["/health", "/embed", "/rerank", "/docs", "/openapi.json"]:
        response = client.get(path)
        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"
    assert client.get("/health", headers={"Authorization": "Bearer bad"}).status_code == 401
    assert client.get("/docs", headers=HEADERS).status_code == 404
    assert client.get("/openapi.json", headers=HEADERS).status_code == 404


@pytest.mark.parametrize("token", ["", "x" * 31, "x" * 32 + " ", "x" * 32 + "한",
                                 "x" * 32 + "\x00"])
def test_weak_or_invalid_token_rejected_before_runtime_load(token):
    with pytest.raises(ValueError, match="invalid_inference_token"):
        create_app(token, lambda: pytest.fail("must not load model"))


def test_health_pinned_identity_and_limits(worker):
    client, *_ = worker
    health = client.get("/health", headers=HEADERS).json()
    assert health["schema_version"] == 1 and health["status"] == "ready"
    assert health["embedding"]["dimension"] == DIMENSION
    assert health["embedding"]["revision"] == "614241f622f53c4eeff9890bdc4f31cfecc418b3"
    assert health["reranker"]["revision"] == "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
    assert health["limits"] == {"max_embed_items": 64, "max_rerank_items": 50}


def test_embedding_order_cache_content_change_eviction_and_no_raw_text_keys(worker):
    client, runtime, encoder, _ = worker
    initial = post(client, embed_payload(["synthetic alpha", "synthetic beta"])).json()
    assert [item["id"] for item in initial["items"]] == ["id-0", "id-1"]
    assert initial["telemetry"]["cache_misses"] == 2
    second = post(client, embed_payload(["synthetic beta", "synthetic alpha"])).json()
    assert second["telemetry"]["cache_hits"] == 2
    assert len(encoder.passage_calls) == 1
    changed = post(client, embed_payload(["synthetic alpha revised"])).json()
    assert changed["telemetry"]["cache_misses"] == 1
    # beta is least recently used after the second request.
    assert post(client, embed_payload(["synthetic beta"])).json()["telemetry"]["cache_misses"] == 1
    assert len(runtime.cache) == 2
    assert all(len(key[0]) == 40 and len(key[1]) == 64 and len(key[2]) == 64
               for key in runtime.cache)
    assert not encoder.telemetry_inputs and encoder.telemetry["tokenized_inputs"] == 0


def test_cache_model_revision_change_forces_miss(worker):
    client, runtime, encoder, _ = worker
    payload = embed_payload(["synthetic"])
    post(client, payload)
    runtime.specs["e5"]["revision"] = "f" * 40
    result = post(client, payload).json()
    assert result["telemetry"]["cache_misses"] == 1
    assert len(encoder.passage_calls) == 2


@pytest.mark.parametrize("setting", ["passage_prefix", "pooling", "max_length", "dtype", "device"])
def test_cache_inference_setting_change_forces_miss(worker, setting):
    client, runtime, encoder, _ = worker
    payload = embed_payload(["synthetic"])
    post(client, payload)
    if setting in {"dtype", "device"}:
        setattr(encoder, setting, "synthetic-changed")
    else:
        runtime.specs["e5"][setting] = "synthetic-changed"
    result = post(client, payload).json()
    assert result["telemetry"]["cache_misses"] == 1
    assert len(encoder.passage_calls) == 2


def test_queries_uncached_and_duplicate_passage_text_encoded_once(worker):
    client, _, encoder, _ = worker
    payload = embed_payload(["same", "same", "other"])
    assert post(client, payload).status_code == 200
    assert encoder.passage_calls == [["same", "other"]]
    for _ in range(2):
        assert post(client, embed_payload(["same"], "query")).status_code == 200
    assert encoder.query_calls == [["same"], ["same"]]


def test_reranker_sorted_output_restored_to_input_order(worker):
    client, _, _, reranker = worker
    payload = {"schema_version": 1, "query": "synthetic question",
               "items": embed_payload(["alpha", "beta", "gamma"])["items"]}
    result = post(client, payload, "/rerank").json()
    assert result["items"] == [{"id": "id-0", "score": 0.0},
                               {"id": "id-1", "score": 1.0},
                               {"id": "id-2", "score": 2.0}]
    assert not reranker.telemetry_inputs


@pytest.mark.parametrize("mutation", [
    lambda data: data.update(schema_version=True),
    lambda data: data.update(extra="private unknown field"),
    lambda data: data.update(items=[]),
    lambda data: data.update(items=[{"id": "a", "text": 1}]),
    lambda data: data.update(items=[{"id": "a", "text": " "}]),
    lambda data: data.update(items=[{"id": "a", "text": "x" * 1001}]),
    lambda data: data.update(items=[{"id": "a", "text": "x", "extra": "private"}]),
    lambda data: data.update(items=[{"id": "a", "text": "x"}] * 2),
    lambda data: data.update(items=[{"id": str(i), "text": "x"} for i in range(65)]),
    lambda data: data.update(kind="query", items=[{"id": "a", "text": "x" * 501}]),
    lambda data: data.update(kind="query", items=[{"id": "a", "text": "x"},
                                                 {"id": "b", "text": "y"}]),
])
def test_strict_schema_rejects_without_validation_input_echo(worker, mutation):
    client, _, encoder, _ = worker
    payload = embed_payload(["private request content"])
    mutation(payload)
    response = post(client, payload)
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"
    assert set(response.json()) == {"error", "request_id"}
    assert not encoder.passage_calls


def test_malformed_and_invalid_unicode_json_redacted(worker):
    client, *_ = worker
    for body in [b'{"private":',
                 (b'{"schema_version":1,"kind":"passage",'
                  b'"items":[{"id":"a","text":"\\ud800"}]}')]:
        response = client.post("/embed", content=body, headers=HEADERS)
        assert response.status_code == 422
        assert set(response.json()) == {"error", "request_id"}


def test_body_limit_content_length_and_chunked_without_declared_length(worker):
    client, *_ = worker
    response = client.post("/embed", content=b"x" * (MAX_BODY_BYTES + 1), headers=HEADERS)
    assert response.status_code == 413
    response = client.post("/embed", content=iter([b"x" * MAX_BODY_BYTES, b"x"]), headers=HEADERS)
    assert response.status_code == 413
    # Authentication is performed before consuming or parsing the body.
    response = client.post("/embed", content=b"x" * (MAX_BODY_BYTES + 1))
    assert response.status_code == 401


@pytest.mark.parametrize("vectors", [[], [[1.0]], [[float("nan")] * DIMENSION],
                                     [[float("inf")] * DIMENSION], [[0.0] * DIMENSION],
                                     [[1e300] * DIMENSION]])
def test_bad_embedding_outputs_fail_and_do_not_poison_cache(worker, vectors):
    client, runtime, encoder, _ = worker
    encoder.output = vectors
    response = post(client, embed_payload(["private input"]))
    assert response.status_code == 502
    assert response.json()["error"] == "inference_failed"
    assert not runtime.cache and not encoder.telemetry_inputs


@pytest.mark.parametrize("rows", [[], [{"chunk_id": "unknown", "score": 1}],
                                  [{"chunk_id": "id-0", "score": float("nan")}],
                                  [{"chunk_id": "id-0", "score": float("inf")}]])
def test_bad_rerank_outputs_fail_closed(worker, rows):
    client, _, _, reranker = worker
    reranker.output = rows
    response = post(client, {"schema_version": 1, "query": "synthetic",
                             "items": embed_payload(["passage"])["items"]}, "/rerank")
    assert response.status_code == 502


def test_inference_exception_redacted_and_known_query_overflow_safe(worker, caplog):
    client, _, encoder, _ = worker
    encoder.error = RuntimeError("private text token secret database path")
    response = post(client, embed_payload(["private input"]))
    assert response.status_code == 502
    assert "private" not in response.text and "private" not in caplog.text
    encoder.error = ValueError("e5_query_too_long")
    response = post(client, embed_payload(["synthetic"], "query"))
    assert response.status_code == 422 and response.json()["error"] == "query_too_long"
    assert not encoder.telemetry_inputs


def test_busy_request_fails_fast_while_health_remains_available(worker):
    client, _, encoder, _ = worker
    encoder.entered, encoder.release = threading.Event(), threading.Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(post, client, embed_payload(["synthetic blocking"]))
        assert encoder.entered.wait(timeout=5)
        try:
            response = post(client, embed_payload(["synthetic second"]))
            assert response.status_code == 503 and response.json()["error"] == "model_busy"
            assert client.get("/health", headers=HEADERS).status_code == 200
        finally:
            encoder.release.set()
        assert pending.result(timeout=5).status_code == 200
    assert len(encoder.passage_calls) == 1


def test_codepoint_limit_allows_non_ascii_without_normalizing_text(worker):
    client, _, encoder, _ = worker
    payload = embed_payload(["한" * 1000, "é", "e\u0301"])
    assert post(client, payload).status_code == 200
    assert encoder.passage_calls == [["한" * 1000, "é", "e\u0301"]]


def test_raw_json_float_version_not_coerced(worker):
    client, *_ = worker
    payload = embed_payload(["synthetic"])
    payload["schema_version"] = 1.0
    response = client.post("/embed", content=json.dumps(payload), headers=HEADERS)
    assert response.status_code == 422
