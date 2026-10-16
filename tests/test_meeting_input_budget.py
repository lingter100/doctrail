"""Synthetic DTOs and mocked HTTP only; never inference or evaluation material."""
import copy
import hashlib
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from doctrail import meeting_input_budget as budget
from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_answer_blocks import BlockAnswerGenerator, BlockAnswerMeetingRuntime
from doctrail.meeting_answer_lines_bounded import BoundedLineGenerator, BoundedLineRuntime
from doctrail.meeting_contract import AnswerRequest
from doctrail.meeting_gguf import GGUFResult
from doctrail.meeting_qwen35 import (
    GGUF_SHA256,
    MODEL_ID,
    MODEL_REVISION,
    NONTHINKING_PREAMBLE,
    PREAMBLE_SHA256,
    Qwen35Generator,
)


def payload():
    text = "Synthetic teal marker.\r\nLabel 😀 stays e\u0301.\n\n"
    return {"schema_version": 1, "query": "What color is the synthetic marker?",
        "contexts": [{"document_id": "synthetic", "revision": 1, "chunk_id": "synthetic-0",
            "title": "Fresh fixture", "page": None, "meeting_date": None,
            "text": text, "start_offset": 7, "end_offset": 7 + len(text)}]}


class Backend:
    def __init__(self, tokens=100):
        self.tokens = tokens
        self.output_tokens = 12
        self.input_tokens = tokens
        self.finish_reason = "eos"
        self.text = '{"status":"answered","claims":[{"text":"Synthetic teal marker.","evidence_ids":[0]}]}'
        self.calls = []
        self.begun = self.ended = 0
        self.cleanup_error = False

    def public_metadata(self):
        return {"repo_id": "synthetic", "revision": "a" * 40, "runtime": {}}

    def begin_request(self, deadline):
        self.begun += 1

    def end_request(self):
        self.ended += 1
        if self.cleanup_error:
            raise RuntimeError("PRIVATE cleanup")

    def count_tokens(self, prompt):
        return self.tokens

    def _complete(self, prompt, deadline, limit, grammar):
        self.calls.append((copy.deepcopy(prompt), limit, grammar))
        return GGUFResult(self.text, self.finish_reason, self.input_tokens,
                          self.output_tokens, 0.0, {})


PAIRS = [(budget.BudgetLineGenerator, budget.BudgetLineRuntime, BoundedLineGenerator, BoundedLineRuntime),
         (budget.BudgetBlockGenerator, budget.BudgetBlockRuntime, BlockAnswerGenerator, BlockAnswerMeetingRuntime)]


@pytest.mark.parametrize("generator,runtime,old_generator,old_runtime", PAIRS)
@pytest.mark.parametrize("count", [4096, 4097, 5120, 5121, False, 1.0, "4096", 0])
def test_both_arm_guards_are_strict_and_do_not_truncate(generator, runtime, old_generator,
                                                       old_runtime, count):
    base = Backend(count)
    service = runtime(generator(base))
    before = payload()
    request = AnswerRequest.model_validate(before)
    allowed = type(count) is int and 0 < count <= 5120
    if allowed:
        result = service.answer(request)
        assert result["status"] == "answered" and len(base.calls) == 1
        assert result["telemetry"]["calls"][0]["input_tokens"] == count
    else:
        with pytest.raises(WorkerError, match="generation_input_limit"):
            service.answer(request)
        assert not base.calls
    assert request.model_dump() == before and base.begun == base.ended == 1
    assert not service.lock.locked()
    assert service.health()["limits"]["input_tokens"] == 5120
    assert service.health()["limits"]["output_tokens"] == 384


@pytest.mark.parametrize("generator,runtime,old_generator,old_runtime", PAIRS)
def test_low_input_prompt_grammar_mapper_and_old_limit_are_unchanged(generator, runtime,
                                                                  old_generator, old_runtime):
    a, b = Backend(), Backend()
    old = old_runtime(old_generator(a)).answer(AnswerRequest.model_validate(payload()))
    new = runtime(generator(b)).answer(AnswerRequest.model_validate(payload()))
    assert a.calls == b.calls
    assert {k: old[k] for k in ("status", "claims", "reason")} == {
        k: new[k] for k in ("status", "claims", "reason")}
    frozen = Backend(4097)
    with pytest.raises(WorkerError, match="generation_input_limit"):
        old_runtime(old_generator(frozen)).answer(AnswerRequest.model_validate(payload()))
    assert not frozen.calls


@pytest.mark.parametrize("generator,runtime,old_generator,old_runtime", PAIRS)
@pytest.mark.parametrize("field,value,code", [
    ("input_tokens", 5121, "generation_token_limit"),
    ("input_tokens", True, "generation_token_limit"),
    ("output_tokens", False, "generation_token_limit"),
    ("output_tokens", 385, "generation_token_limit"),
    ("finish_reason", "length", "generation_output_truncated"),
    ("cleanup_error", True, "generation_cleanup_failed"),
])
def test_output_and_cleanup_failures_stop_after_single_call(generator, runtime, old_generator,
                                                           old_runtime, field, value, code):
    base = Backend()
    setattr(base, field, value)
    service = runtime(generator(base))
    with pytest.raises(WorkerError, match=code):
        service.answer(AnswerRequest.model_validate(payload()))
    assert len(base.calls) == 1 and base.ended == 1 and not service.lock.locked()
    assert service.last_telemetry["error_code"] == code


@pytest.mark.parametrize("generator,runtime,old_generator,old_runtime", PAIRS)
def test_call_once_busy_and_empty_contract(generator, runtime, old_generator, old_runtime):
    base = Backend()
    service = runtime(generator(base))
    service.lock.acquire()
    with pytest.raises(WorkerError, match="model_busy"):
        service.answer(AnswerRequest.model_validate(payload()))
    service.lock.release()
    empty = payload(); empty["contexts"] = []
    assert service.answer(AnswerRequest.model_validate(empty))["status"] == "abstained"
    assert not base.calls and base.ended == 1
    catalog_fn = budget.build_span_catalog if generator is budget.BudgetLineGenerator else budget.build_block_catalog
    wrapped = generator(base)
    wrapped.begin_request(time.monotonic() + 90)
    with wrapped.answer_catalog(catalog_fn(AnswerRequest.model_validate(payload()).contexts)):
        wrapped.generate_bounded([], time.monotonic() + 90)
        with pytest.raises(WorkerError, match="generation_call_limit"):
            wrapped.generate_bounded([], time.monotonic() + 90)
    wrapped.end_request()


class Native:
    """Complete synthetic transport; load/hash are tested separately below."""
    def __init__(self, tmp_path):
        self.path = tmp_path / "identity.json"
        self.tokens = [10] * 100
        self.preamble = NONTHINKING_PREAMBLE
        self.requests = []
        self.change = lambda result: result
        self.context = 6144
        self.repo = MODEL_ID
        self.gguf = tmp_path / "synthetic.gguf"
        self.gguf.write_bytes(b"synthetic artifact, never model weights")
        self.path.write_text(json.dumps({"schema_version": 1, "model": self.repo,
            "revision": MODEL_REVISION, "gguf": {"repo_id": "synthetic/quantizer",
                "revision": "b" * 40, "filename": self.gguf.name, "sha256": GGUF_SHA256,
                "size_bytes": self.gguf.stat().st_size},
            "llama": {"tag": "b11429", "commit": "d81235049384534c167caea52b85a694f6103d14"}}))

    def handler(self, request):
        self.requests.append(request)
        if request.url.path == "/props":
            return httpx.Response(200, json={"model_alias": GGUF_SHA256,
                "model_path": str(self.gguf), "build_info": "b11429-d81235049",
                "total_slots": 1, "is_sleeping": False,
                "default_generation_settings": {"n_ctx": self.context}})
        body = json.loads(request.content)
        if request.url.path == "/apply-template":
            assert body["chat_template_kwargs"] == {"enable_thinking": False}
            return httpx.Response(200, json={"prompt": "Synthetic prompt" + self.preamble})
        if request.url.path == "/tokenize":
            assert body["parse_special"] and not body["add_special"]
            return httpx.Response(200, json={"tokens": self.tokens})
        assert request.url.path == "/completion"
        assert body["prompt"] == self.tokens and body["cache_prompt"] is False
        result = {"model": GGUF_SHA256, "generation_settings": {k: body[k] for k in
            (*budget.GREEDY, "n_predict", "grammar")}, "content": '{"status":"abstained","claims":[]}',
            "tokens_evaluated": len(self.tokens), "tokens_predicted": 7,
            "stop": True, "stop_type": "eos", "truncated": False,
            "timings": {"cache_n": 0, "prompt_n": len(self.tokens), "predicted_n": 6,
                        "prompt_ms": 1.2, "predicted_ms": 1.5}}
        return httpx.Response(200, json=self.change(result))

    def generator(self, kind=budget.BudgetGGUFGenerator):
        return kind("http://127.0.0.1:8093", "x" * 40, self.path,
                    transport=httpx.MockTransport(self.handler)).load()


@pytest.fixture
def native(tmp_path, monkeypatch):
    result = Native(tmp_path)
    # A synthetic local artifact stands in for pinned bytes; no real weights read.
    monkeypatch.setattr(hashlib, "file_digest", lambda *_: SimpleNamespace(hexdigest=lambda: GGUF_SHA256))
    return result


@pytest.mark.parametrize("count", [4096, 4097, 5120, 5121])
def test_native_actual_ids_enforce_new_cap_and_keep_truthful_counts(native, count):
    native.tokens = [10] * count
    generator = native.generator()
    if count <= 5120:
        result = generator._complete([], time.monotonic() + 90, 384, "root ::= [0-9]")
        assert result.input_tokens == count
        assert generator.last_effective_config["observed_nonthinking_preamble_sha256"] == PREAMBLE_SHA256
        assert generator.last_effective_config["enable_thinking_requested"] is False
        assert result.telemetry["native_timings"]["predicted_n"] == 6
    else:
        with pytest.raises(GenerationError, match="generation_input_limit"):
            generator.generate_bounded([], time.monotonic() + 90)
        assert not any(r.url.path == "/completion" for r in native.requests)
    assert generator.public_metadata()["runtime"]["max_input_tokens"] == 5120
    generator.close()


def test_low_native_path_matches_frozen_qwen_config_and_tokenization(native):
    old = native.generator(Qwen35Generator)
    a = old._complete([], time.monotonic() + 90, 384, "root ::= [0-9]")
    old_requests = [(r.url.path, r.content) for r in native.requests]
    native.requests.clear()
    new = native.generator()
    b = new._complete([], time.monotonic() + 90, 384, "root ::= [0-9]")
    assert old_requests == [(r.url.path, r.content) for r in native.requests]
    assert old.last_effective_config == new.last_effective_config
    assert (a.text, a.input_tokens, a.output_tokens, a.telemetry) == (b.text, b.input_tokens, b.output_tokens, b.telemetry)
    old.end_request(); new.end_request()
    assert not old._cache and not new._cache
    old.close(); new.close()


@pytest.mark.parametrize("context", [5120, 6143, 6145, True])
def test_native_context_is_exact_not_minimum(native, context):
    native.context = context
    with pytest.raises(GenerationError, match="generation_identity_mismatch"):
        native.generator()
    assert not any(r.url.path == "/completion" for r in native.requests)


def test_pinned_model_and_nonthinking_fail_before_completion(native):
    doc = json.loads(native.path.read_text()); doc["model"] = "wrong/model"
    native.path.write_text(json.dumps(doc))
    with pytest.raises(GenerationError, match="generation_identity_mismatch"):
        native.generator()
    doc["model"] = MODEL_ID; native.path.write_text(json.dumps(doc))
    generator = native.generator()
    native.preamble = "<think>"
    with pytest.raises(GenerationError, match="generation_nonthinking_template_mismatch"):
        generator.generate_bounded([], time.monotonic() + 90)
    assert not any(r.url.path in ("/tokenize", "/completion") for r in native.requests)
    generator.close()


@pytest.mark.parametrize("change", [
    lambda r: r["generation_settings"].update(seed=False),
    lambda r: r.update(tokens_evaluated=True), lambda r: r.update(tokens_predicted=385),
    lambda r: r.update(truncated=True), lambda r: r["timings"].update(cache_n=1),
])
def test_native_effective_config_and_counts_fail_closed(native, change):
    def corrupt(result):
        change(result)
        return result
    native.change = corrupt
    generator = native.generator()
    with pytest.raises(GenerationError):
        generator.generate_bounded([], time.monotonic() + 90)
    assert sum(r.url.path == "/completion" for r in native.requests) == 1
    generator.close()


def test_native_request_and_response_bytes_guarded_without_network(native):
    generator = native.generator()
    with pytest.raises(GenerationError, match="generation_input_limit"):
        generator._complete([], time.monotonic() + 90, 384, "x" * 524288)
    assert not any(r.url.path == "/completion" for r in native.requests)
    with pytest.raises(GenerationError, match="generation_input_limit"):
        generator._request("POST", "/apply-template", {"messages": "x" * 524288})
    generator.close()
    huge = budget.BudgetGGUFGenerator("http://127.0.0.1:8093", "x" * 40, native.path,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * (2097152 + 1))))
    with pytest.raises(GenerationError, match="generation_backend_response_limit"):
        huge._request("GET", "/props")
    huge.close()


@pytest.mark.parametrize("tokens,limit", [([True], 384), ([1.0], 384), ([1], True), ([1], 385), ([], 384)])
def test_native_payload_rejects_coercion(tokens, limit):
    with pytest.raises(GenerationError, match="generation_input_limit"):
        budget.native_payload(tokens, limit, "")


@pytest.mark.parametrize("generator,runtime,old_generator,old_runtime", PAIRS)
@pytest.mark.parametrize("expire_during", ["preparation", "cleanup"])
def test_whole_request_deadline_includes_preparation_and_cleanup(generator, runtime,
                                                               old_generator, old_runtime,
                                                               expire_during, monkeypatch):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(budget, "time", SimpleNamespace(monotonic=lambda: clock.now))
    base = Backend()
    if expire_during == "preparation":
        def count(_):
            clock.now = 90.0
            return 100
        base.count_tokens = count
    else:
        def end():
            base.ended += 1
            clock.now = 90.0
        base.end_request = end
    service = runtime(generator(base))
    with pytest.raises(WorkerError, match="generation_deadline_exceeded"):
        service.answer(AnswerRequest.model_validate(payload()))
    assert len(base.calls) == (0 if expire_during == "preparation" else 1)
    assert base.ended == 1 and not service.lock.locked()
    assert service.last_telemetry["elapsed_ms"] == 90000


def test_frozen_qwen_backend_still_rejects_4097(native):
    native.tokens = [10] * 4097
    generator = native.generator(Qwen35Generator)
    with pytest.raises(GenerationError, match="generation_input_limit"):
        generator._complete([], time.monotonic() + 90, 384, "root ::= [0-9]")
    assert not any(r.url.path == "/completion" for r in native.requests)
    generator.close()


def test_serialized_request_inclusive_byte_boundary_and_http_timeout(native):
    _, initial = budget.native_payload([1], 384, "")
    size = len(json.dumps(initial, ensure_ascii=False, allow_nan=False).encode())
    budget.native_payload([1], 384, "a" * (524288 - size))
    with pytest.raises(GenerationError, match="generation_input_limit"):
        budget.native_payload([1], 384, "a" * (524288 - size + 1))
    def timeout(_):
        raise httpx.ReadTimeout("PRIVATE raw HTTP details")
    generator = budget.BudgetGGUFGenerator("http://127.0.0.1:8093", "x" * 40, native.path,
                                          transport=httpx.MockTransport(timeout))
    with pytest.raises(GenerationError, match="generation_deadline_exceeded"):
        generator._request("GET", "/props", deadline=time.monotonic() + 90)
    generator.close()
