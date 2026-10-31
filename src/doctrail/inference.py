"""Loopback-only model worker; Java owns authorization, storage and ranking.

This module does not access document databases. Local snapshots are verified by
the frozen M3 loaders, loaded once, and never downloaded by this service.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import ntpath
import os
import re
import sys
import threading
import time
import uuid
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from doctrail.model_retrieval import LocalBGEReranker, LocalE5Encoder, load_model_manifest

MAX_BODY_BYTES = 512 * 1024
DIMENSION = 384
MAX_EMBED_ITEMS = 64
MAX_RERANK_ITEMS = 50


class WorkerError(Exception):
    def __init__(self, code: str, status: int):
        self.code, self.status = code, status
        super().__init__(code)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Item(StrictModel):
    id: Annotated[str, Field(min_length=1, max_length=128)]
    text: Annotated[str, Field(min_length=1, max_length=1000)]

    @field_validator("id", "text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("invalid_request")
        # Lone surrogate escapes cannot be encoded to the exact UTF-8 cache key.
        value.encode("utf-8")
        return value


class VersionedRequest(StrictModel):
    schema_version: Literal[1]

    @field_validator("schema_version", mode="before")
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int:
            raise ValueError("invalid_request")
        return value


class EmbedRequest(VersionedRequest):
    kind: Literal["query", "passage"]
    items: Annotated[list[Item], Field(min_length=1, max_length=MAX_EMBED_ITEMS)]


class RerankRequest(VersionedRequest):
    query: Annotated[str, Field(min_length=1, max_length=500)]
    items: Annotated[list[Item], Field(min_length=1, max_length=MAX_RERANK_ITEMS)]

    @field_validator("query")
    @classmethod
    def nonblank_query(cls, value):
        return Item.nonblank(value)


def _check_items(items):
    if len({item.id for item in items}) != len(items):
        raise WorkerError("invalid_request", 422)


class InferenceRuntime:
    """Serialized resident models with a bounded, content-addressed vector LRU."""

    def __init__(self, encoder, reranker, *, cache_capacity=4096):
        if cache_capacity < 1:
            raise ValueError("invalid_cache_capacity")
        self.encoder, self.reranker = encoder, reranker
        self.specs = load_model_manifest()["models"]
        self.cache_capacity = cache_capacity
        self.cache = OrderedDict()
        self.lock = threading.Lock()

    @classmethod
    def load(cls, model_root: Path, device: str):
        encoder = LocalE5Encoder(model_root / "e5", device=device)
        try:
            reranker = LocalBGEReranker(model_root / "reranker", device=device)
        except Exception:
            encoder.close()
            raise
        return cls(encoder, reranker)

    def health(self):
        e5, reranker = self.specs["e5"], self.specs["reranker"]
        return {
            "schema_version": 1, "status": "ready",
            "embedding": {"model": e5["repo_id"], "revision": e5["revision"],
                          "dimension": DIMENSION, "max_length": 512},
            "reranker": {"model": reranker["repo_id"], "revision": reranker["revision"],
                         "max_length": 512},
            "limits": {"max_embed_items": MAX_EMBED_ITEMS,
                       "max_rerank_items": MAX_RERANK_ITEMS},
            "runtime": {"device": str(self.encoder.device),
                        "embedding_dtype": str(self.encoder.dtype),
                        "reranker_dtype": str(self.reranker.dtype)},
        }

    def _reset_telemetry(self):
        for model in (self.encoder, self.reranker):
            model.telemetry_inputs.clear()
            for name in model.telemetry:
                model.telemetry[name] = 0

    def _run(self, operation):
        if not self.lock.acquire(blocking=False):
            raise WorkerError("model_busy", 503)
        start = time.perf_counter()
        try:
            self._reset_telemetry()
            result = operation()
            result.setdefault("telemetry", {}).update({
                "truncated_inputs": sum(
                    model.telemetry.get("truncated_inputs", 0)
                    for model in (self.encoder, self.reranker)
                ),
                "elapsed_ms": round((time.perf_counter() - start) * 1000, 3),
            })
            return result
        except WorkerError:
            raise
        except ValueError as exc:
            # Only exact frozen, constant error codes are exposed.
            if str(exc) in {"e5_query_too_long", "reranker_query_too_long"}:
                raise WorkerError("query_too_long", 422) from None
            raise WorkerError("inference_failed", 502) from None
        except Exception:  # noqa: BLE001 - never expose arbitrary model errors or inputs
            raise WorkerError("inference_failed", 502) from None
        finally:
            self._reset_telemetry()
            self.lock.release()

    @staticmethod
    def _vectors(raw, count):
        if len(raw) != count:
            raise ValueError("invalid_output")
        vectors = [[float(value) for value in row] for row in raw]
        if any(len(row) != DIMENSION or not all(math.isfinite(v) for v in row)
               or not 0 < sum(v * v for v in row) < math.inf for row in vectors):
            raise ValueError("invalid_output")
        return vectors

    def embed(self, request: EmbedRequest):
        _check_items(request.items)
        if request.kind == "query" and (
            len(request.items) != 1 or len(request.items[0].text) > 500
        ):
            raise WorkerError("invalid_request", 422)
        return self._run(lambda: self._embed(request))

    def _embed(self, request):
        spec = self.specs["e5"]
        texts = [item.text for item in request.items]
        hits = 0
        if request.kind == "query":
            vectors = self._vectors(self.encoder.encode_queries(texts), len(texts))
            misses = len(texts)
        else:
            settings = {"schema_version": 1, "dimension": DIMENSION,
                        "prefix": spec["passage_prefix"], "pooling": spec["pooling"],
                        "max_length": spec["max_length"], "dtype": str(self.encoder.dtype),
                        "device": str(self.encoder.device)}
            fingerprint = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
            keys = [(spec["revision"], fingerprint,
                     hashlib.sha256(text.encode("utf-8")).hexdigest())
                    for text in texts]
            available = {}
            missing = OrderedDict()
            for key, text in zip(keys, texts, strict=True):
                if key in self.cache:
                    hits += 1
                    available[key] = self.cache[key]
                    self.cache.move_to_end(key)
                elif key not in missing:
                    missing[key] = text
            misses = len(missing)
            if missing:
                encoded = self._vectors(
                    self.encoder.encode_passages(list(missing.values())), misses
                )
                for key, vector in zip(missing, encoded, strict=True):
                    available[key] = vector
                    self.cache[key] = vector
                    while len(self.cache) > self.cache_capacity:
                        self.cache.popitem(last=False)
            vectors = [available[key] for key in keys]
        return {
            "schema_version": 1, "model": spec["repo_id"], "revision": spec["revision"],
            "dimension": DIMENSION,
            "items": [{"id": item.id, "vector": vector}
                      for item, vector in zip(request.items, vectors, strict=True)],
            "telemetry": {"cache_hits": hits, "cache_misses": misses},
        }

    def rerank(self, request: RerankRequest):
        _check_items(request.items)
        return self._run(lambda: self._rerank(request))

    def _rerank(self, request):
        candidates = [{"chunk_id": item.id, "text": item.text} for item in request.items]
        ranked = self.reranker.rerank(request.query, candidates, limit=len(candidates))
        if len(ranked) != len(candidates):
            raise ValueError("invalid_output")
        scores = {row["chunk_id"]: float(row["score"]) for row in ranked}
        if set(scores) != {item.id for item in request.items} or not all(
            math.isfinite(value) for value in scores.values()
        ):
            raise ValueError("invalid_output")
        spec = self.specs["reranker"]
        return {
            "schema_version": 1, "model": spec["repo_id"], "revision": spec["revision"],
            "items": [{"id": item.id, "score": scores[item.id]} for item in request.items],
            "telemetry": {"cache_hits": 0, "cache_misses": 0},
        }

    def close(self):
        with self.lock:
            self.cache.clear()
            try:
                self.encoder.close()
            finally:
                self.reranker.close()


def _error(code, status, request_id):
    return JSONResponse({"error": code, "request_id": request_id}, status_code=status)


class BoundaryMiddleware:
    """Authenticate and cap bytes before JSON parsing, including chunked bodies."""

    def __init__(self, app, token: str):
        self.app, self.authorization = app, ("Bearer " + token).encode("ascii")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        auth = [value for key, value in scope["headers"] if key.lower() == b"authorization"]
        if len(auth) != 1 or not hmac.compare_digest(auth[0], self.authorization):
            return await _error("unauthorized", 401, request_id)(scope, receive, send)
        lengths = [value for key, value in scope["headers"] if key.lower() == b"content-length"]
        if lengths:
            try:
                length = int(lengths[0])
                if len(lengths) != 1 or length < 0:
                    raise ValueError
            except ValueError:
                return await _error("invalid_request", 422, request_id)(scope, receive, send)
            if length > MAX_BODY_BYTES:
                return await _error("body_too_large", 413, request_id)(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_BODY_BYTES:
                return await _error("body_too_large", 413, request_id)(scope, receive, send)
            if not message.get("more_body", False):
                break

        async def bounded_receive():
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        try:
            await self.app(scope, bounded_receive, send)
        except Exception:  # noqa: BLE001 - redact unexpected framework errors at the boundary
            # Never let framework/server logs print raw model/input exceptions.
            await _error("inference_failed", 502, request_id)(scope, receive, send)


def _validate_token(token):
    if len(token) < 32 or any(not 33 <= ord(char) <= 126 for char in token):
        raise ValueError("invalid_inference_token")


def create_app(token: str, runtime_factory):
    _validate_token(token)

    @asynccontextmanager
    async def lifespan(app):
        app.state.runtime = runtime_factory()
        try:
            yield
        finally:
            app.state.runtime.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(BoundaryMiddleware, token=token)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return _error("invalid_request", 422, request.state.request_id)

    @app.exception_handler(WorkerError)
    async def worker_error(request, exc):
        return _error(exc.code, exc.status, request.state.request_id)

    @app.get("/health")
    def health(request: Request):
        return request.app.state.runtime.health()

    @app.post("/embed")
    def embed(payload: EmbedRequest, request: Request):
        return request.app.state.runtime.embed(payload)

    @app.post("/rerank")
    def rerank(payload: RerankRequest, request: Request):
        return request.app.state.runtime.rerank(payload)

    return app


def _startup_diagnostic(error, stage):
    """Bounded code locations only: never exception text, locals or source lines."""
    def label(value):
        return re.sub(r"[^a-zA-Z0-9_.<>-]", "_", value[:80])

    chain, seen = [], set()
    while error is not None and id(error) not in seen and len(chain) < 4:
        seen.add(id(error))
        frames = deque(maxlen=8)
        trace, visited = error.__traceback__, 0
        while trace is not None and visited < 64:
            code = trace.tb_frame.f_code
            frames.append({"file": label(ntpath.basename(code.co_filename)),
                           "function": label(code.co_name), "line": trace.tb_lineno})
            trace, visited = trace.tb_next, visited + 1
        chain.append({"type": label(type(error).__name__), "frames": list(frames),
                      "frames_truncated": visited > 8 or trace is not None})
        error = error.__cause__ if error.__cause__ is not None else (
            None if error.__suppress_context__ else error.__context__)
    return {"code": "inference_startup_diagnostic", "stage": stage,
            "exceptions": chain, "chain_truncated": error is not None}


def main():
    parser = argparse.ArgumentParser(description="Start the loopback DocTrail model worker")
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--model-root", type=Path, default=Path("models"))
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.exit(2, "invalid_port\n")
    stage = "token_validation"
    try:
        # Preload before server startup so readiness cannot race model loading.
        token = os.environ.get("DOCTRAIL_INFERENCE_TOKEN", "")
        _validate_token(token)
        stage = "model_load"
        runtime = InferenceRuntime.load(args.model_root, args.device)
        stage = "application_setup"
        app = create_app(token, lambda: runtime)
    except Exception as error:  # noqa: BLE001 - startup failures must not disclose paths/tokens
        if os.environ.get("DOCTRAIL_STARTUP_DIAGNOSTICS") == "1":
            try:
                sys.stderr.write(json.dumps(_startup_diagnostic(error, stage),
                                            ensure_ascii=True, separators=(",", ":")) + "\n")
            except Exception:  # noqa: BLE001, S110 - preserve exit; recursive error logging is unsafe
                pass
        parser.exit(2, "inference_startup_failed\n")
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="critical")


if __name__ == "__main__":
    main()
