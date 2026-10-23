"""Bounded native llama.cpp adapter; no model downloads or dependency changes.

The launcher owns the native process. This adapter verifies its advertised build,
alias and local GGUF bytes before accepting requests. Native responses may contain
source text, so only explicitly selected numeric/configuration telemetry escapes.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from doctrail.generation_runtime import GenerationError
from doctrail.meeting_runtime import (
    DEADLINE_SECONDS,
    MAX_INPUT_TOKENS,
    MAX_NEW_TOKENS,
    PROTOCOL,
)

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = 512 * 1024
LABEL_GRAMMAR = "root ::= [0-9]"
LABEL_TOKEN_LIMIT = 4  # digit followed by EOS; never treat a length stop as a label
GREEDY = {"temperature": 0.0, "samplers": ["temperature"], "seed": 0,
          "dynatemp_range": 0.0, "mirostat": 0, "ignore_eos": False,
          "stream": False, "stop": [], "logit_bias": [], "grammar_lazy": False,
          "lora": []}


@dataclass(frozen=True)
class GGUFResult:
    text: str
    finish_reason: str
    input_tokens: int
    output_tokens: int
    elapsed_seconds: float
    telemetry: dict


def _fail(code="generation_backend_protocol"):
    raise GenerationError(code)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def _json(raw):
    try:
        result = json.loads(raw, object_pairs_hook=_object,
                            parse_constant=lambda value: _fail())
        if not isinstance(result, dict):
            _fail()
        return result
    except (ValueError, UnicodeError):
        _fail()


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _same_setting(actual, expected):
    # JSON booleans must not compare equal to numeric zero/one.
    if type(expected) in (int, float):
        return type(actual) in (int, float) and actual == expected
    return type(actual) is type(expected) and actual == expected


class GGUFGenerator:
    """Native HTTP generation with artifact identity and effective-setting checks."""

    def __init__(self, llama_url, token, identity_manifest_path, *, transport=None):
        try:
            url = urlsplit(llama_url)
            address = ipaddress.ip_address(url.hostname or "")
            if (url.scheme != "http" or not address.is_loopback or not url.port
                    or url.username or url.password or url.query or url.fragment
                    or url.path not in ("", "/")):
                _fail("generation_backend_url")
            if (not isinstance(token, str) or not 32 <= len(token) <= 256
                    or not token.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in token)):
                _fail("generation_backend_token")
        except (ValueError, TypeError):
            _fail("generation_backend_url")
        self.manifest_path = Path(identity_manifest_path)
        self._client = httpx.Client(base_url=llama_url.rstrip("/"),
            headers={"Authorization": "Bearer " + token, "Accept-Encoding": "identity"},
            follow_redirects=False, trust_env=False, transport=transport)
        self._cache = OrderedDict()
        self._deadline = None
        self._metadata = None
        self.last_effective_config = None

    def _remaining(self, deadline=None):
        effective = deadline if deadline is not None else self._deadline
        remaining = (effective - time.monotonic()) if effective is not None else DEADLINE_SECONDS
        if remaining <= 0:
            _fail("generation_deadline_exceeded")
        return remaining

    def _request(self, method, path, payload=None, deadline=None):
        remaining = self._remaining(deadline)
        body = None if payload is None else json.dumps(payload, ensure_ascii=False,
                                                       allow_nan=False).encode("utf-8")
        if body is not None and len(body) > MAX_REQUEST_BYTES:
            _fail("generation_input_limit")
        try:
            with self._client.stream(method, path, content=body,
                    headers={"Content-Type": "application/json"}, timeout=remaining) as response:
                if response.status_code != 200:
                    _fail("generation_backend_unavailable")
                if response.headers.get("content-encoding", "identity") != "identity":
                    _fail()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    self._remaining(deadline)
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        _fail("generation_backend_response_limit")
                    chunks.append(chunk)
                self._remaining(deadline)
                return _json(b"".join(chunks))
        except httpx.TimeoutException:
            _fail("generation_deadline_exceeded")
        except (httpx.HTTPError, OSError):
            _fail("generation_backend_unavailable")

    def load(self):
        try:
            if self.manifest_path.stat().st_size > 65536:
                _fail("generation_identity_mismatch")
            manifest = _json(self.manifest_path.read_bytes())
            gguf, llama = manifest["gguf"], manifest["llama"]
            if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
                    or not isinstance(manifest["model"], str) or not manifest["model"]
                    or not re.fullmatch(r"[a-f0-9]{40}", manifest["revision"])
                    or not re.fullmatch(r"[a-f0-9]{64}", gguf["sha256"])
                    or not re.fullmatch(r"[a-f0-9]{40}", gguf["revision"])
                    or not re.fullmatch(r"[a-f0-9]{40}", llama["commit"])
                    or not re.fullmatch(r"b[0-9]+", llama["tag"])
                    or not _integer(gguf["size_bytes"], 1)):
                _fail("generation_identity_mismatch")
            props = self._request("GET", "/props")
            build = re.fullmatch(r"b([0-9]+)-([a-f0-9]{7,40})", props.get("build_info", ""))
            path = Path(props["model_path"])
            settings = props["default_generation_settings"]
            if (props.get("model_alias") != gguf["sha256"]
                    or not build or "b" + build[1] != llama["tag"]
                    or not llama["commit"].startswith(build[2])
                    or path.name != gguf["filename"] or not path.is_file()
                    or path.stat().st_size != gguf["size_bytes"]
                    or not _integer(settings.get("n_ctx"), MAX_INPUT_TOKENS + MAX_NEW_TOKENS)
                    or type(props.get("total_slots")) is not int or props["total_slots"] != 1
                    or props.get("is_sleeping") is not False):
                _fail("generation_identity_mismatch")
            with path.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            if digest != gguf["sha256"]:
                _fail("generation_identity_mismatch")
            self._alias = gguf["sha256"]
            self._metadata = {"repo_id": manifest["model"],
                "revision": "gguf-sha256:" + gguf["sha256"],
                "original_revision": manifest["revision"],
                "experimental": True, "generation_protocol": PROTOCOL,
                "artifact": {key: gguf[key] for key in
                             ("repo_id", "revision", "filename", "sha256", "size_bytes")},
                "runtime": {"backend": "llama.cpp", "tag": llama["tag"],
                    "commit": llama["commit"], "observed_build": props["build_info"],
                    "identity_check": "local_gguf_sha256_and_server_alias",
                    "context_tokens": settings["n_ctx"], "max_input_tokens": MAX_INPUT_TOKENS,
                    "max_new_tokens": MAX_NEW_TOKENS, "deadline_seconds": DEADLINE_SECONDS,
                    "memory_telemetry": "not_measured"}}
            return self
        except GenerationError:
            self.close()
            raise
        except (OSError, KeyError, TypeError, ValueError):
            self.close()
            _fail("generation_identity_mismatch")

    def public_metadata(self):
        if self._metadata is None:
            _fail("generation_not_ready")
        return json.loads(json.dumps(self._metadata))

    def begin_request(self, deadline):
        self._deadline = deadline
        self._cache.clear()
        self.last_effective_config = None

    def end_request(self):
        self._cache.clear()  # never retain uploaded text between requests
        self._deadline = None

    def _prepare(self, messages, deadline=None):
        self._remaining(deadline)
        key = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        response = self._request("POST", "/apply-template", {"messages": messages,
            "chat_template_kwargs": {"enable_thinking": False}}, deadline)
        prompt = response.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            _fail()
        tokenized = self._request("POST", "/tokenize", {"content": prompt,
            "add_special": False, "parse_special": True, "with_pieces": False}, deadline)
        tokens = tokenized.get("tokens")
        if not isinstance(tokens, list) or not tokens or not all(_integer(t) for t in tokens):
            _fail()
        self._cache[key] = tokens
        while len(self._cache) > 8:
            self._cache.popitem(last=False)
        return tokens

    def count_tokens(self, messages):
        return len(self._prepare(messages))

    def _complete(self, messages, deadline, token_limit, grammar=""):
        started = time.monotonic()
        self.last_effective_config = None
        tokens = self._prepare(messages, deadline)
        if len(tokens) > MAX_INPUT_TOKENS:
            _fail("generation_input_limit")
        expected = {**GREEDY, "n_predict": token_limit, "grammar": grammar}
        payload = {**expected, "prompt": tokens, "cache_prompt": False,
                   "return_tokens": True}
        response = self._request("POST", "/completion", payload, deadline)
        settings = response.get("generation_settings")
        if not isinstance(settings, dict) or any(
                key not in settings or not _same_setting(settings[key], value)
                for key, value in expected.items()):
            _fail("generation_effective_config_mismatch")
        timings = response.get("timings")
        if (response.get("model") != self._alias or response.get("truncated") is not False
                or response.get("stop") is not True or not isinstance(timings, dict)
                or type(timings.get("cache_n")) is not int or timings["cache_n"] != 0
                or not _integer(timings.get("prompt_n"), 1)
                or timings["prompt_n"] != len(tokens)
                or not _integer(response.get("tokens_evaluated"), 1)
                or response["tokens_evaluated"] != len(tokens)
                or not _integer(response.get("tokens_predicted"), 1)
                or response["tokens_predicted"] > token_limit
                or not isinstance(response.get("content"), str)
                or response.get("stop_type") not in ("eos", "limit")):
            _fail()
        # No source-containing prompt, raw native response or local model path in telemetry.
        self.last_effective_config = {"backend": "llama.cpp", **expected,
            "cache_prompt_requested": False, "observed_cache_tokens": timings["cache_n"]}
        telemetry = {key: value for key, value in timings.items()
                     if key in {"cache_n", "prompt_n", "prompt_ms", "predicted_n", "predicted_ms"}
                     and type(value) in (int, float)}
        return GGUFResult(response["content"],
            "eos" if response["stop_type"] == "eos" else "length", len(tokens),
            response["tokens_predicted"], time.monotonic() - started,
            {"backend": "llama.cpp", "native_timings": telemetry})

    def generate_bounded(self, messages, deadline):
        return self._complete(messages, deadline, MAX_NEW_TOKENS)

    def classify_bounded(self, prompts, deadline):
        started, results, input_tokens, output_tokens = time.monotonic(), [], 0, 0
        self.last_effective_config = None
        for prompt in prompts:
            output = self._complete(prompt, deadline, LABEL_TOKEN_LIMIT, LABEL_GRAMMAR)
            if output.finish_reason != "eos" or not re.fullmatch(r"[0-9]", output.text):
                _fail("generation_invalid_label")
            results.append({"label": int(output.text)})  # no fabricated classifier confidence
            input_tokens += output.input_tokens
            output_tokens += output.output_tokens
        return results, {"operation": "grammar_constrained_classification", "backend": "llama.cpp",
            "label_count": 10, "selection": "greedy", "confidence": "not_measured",
            "completion_calls": len(results), "input_tokens": input_tokens,
            "output_tokens": output_tokens, "elapsed_seconds": time.monotonic() - started}

    def close(self):
        self._cache.clear()
        self._client.close()
