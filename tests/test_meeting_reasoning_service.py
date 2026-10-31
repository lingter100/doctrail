"""Generic fake HTTP/service checks. No weights, tokenizer, native or old QA data."""
import copy
import json

import httpx
import pytest

from doctrail import meeting_reasoning_service as m
from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_contract import AnswerRequest

QUESTION = "두 기록에서 색상과 모양은 무엇인가요?"
TEXTS = ["The badge is turquoise.", "The badge is triangular."]
CONTENT = '{"status":"answered","claims":[{"text":"배지는 청록색 삼각형이다.","evidence":[0,1]}]}'
PROMPT = "synthetic serialized schema and full messages\n" + m.PREAMBLE


def request():
    return AnswerRequest.model_validate({"schema_version": 1, "query": QUESTION, "contexts": [
        {"document_id": f"synthetic-{i}", "revision": 1, "chunk_id": f"chunk-{i}",
         "title": f"Record{i}", "meeting_date": None, "page": None,
         "start_offset": 10, "end_offset": 10 + len(text), "text": text}
        for i, text in enumerate(TEXTS)]})


def response(content=CONTENT, count=40):
    return {"object": "chat.completion", "model": m.GGUF_SHA256,
        "system_fingerprint": "b11429-d81235049",
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant",
            "content": content, "reasoning_content": "Private synthetic reasoning."}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": count, "total_tokens": 100 + count,
                  "prompt_tokens_details": {"cached_tokens": 0}},
        "__verbose": {"model": m.GGUF_SHA256, "prompt": PROMPT,
            "content": "Private synthetic reasoning.\n</think>\n" + content,
            "generation_settings": {**copy.deepcopy(m.SETTINGS), "grammar": "schema", "stop": []},
            "tokens_predicted": count, "tokens_evaluated": 100, "tokens": list(range(count)),
            "stop": True, "truncated": False, "stop_type": "eos",
            "timings": {"cache_n": 0, "prompt_n": 100, "predicted_n": count}}}


class Fake:
    def __init__(self):
        self.seen, self.input_count, self.final_count = [], 100, 45
        self.raw, self.hook = response(), lambda _: None
        self.generator = m.ReasoningServiceGenerator("http://127.0.0.1:8123", "x" * 40,
            "unused", transport=httpx.MockTransport(self.handle))
        self.generator._alias = m.GGUF_SHA256
        self.generator._metadata = {"repo_id": m.MODEL_ID, "revision": "gguf-sha256:" + m.GGUF_SHA256,
            "original_revision": m.MODEL_REVISION, "artifact": {"sha256": m.GGUF_SHA256},
            "runtime": {"context_tokens": 8192, "tag": "b11429", "commit": m.RUNTIME_COMMIT,
                        "observed_build": "b11429-d81235049"}}
        self.runtime = m.ReasoningMeetingRuntime(self.generator)

    def handle(self, req):
        body = json.loads(req.content)
        self.seen.append((req.url.path, body))
        self.hook(req.url.path)
        if req.url.path == "/apply-template":
            result = {"prompt": PROMPT}
        elif req.url.path == "/v1/chat/completions/input_tokens":
            result = {"object": "response.input_tokens", "input_tokens": self.input_count}
        elif req.url.path == "/tokenize":
            assert body["parse_special"] is False and body["add_special"] is False
            result = {"tokens": list(range(self.final_count))}
        else:
            assert req.url.path == "/v1/chat/completions"
            result = self.raw
        return httpx.Response(200, json=result)


@pytest.fixture
def fake():
    fixture = Fake()
    yield fixture
    fixture.runtime.close()


def test_direct_full_sources_original_question_citations_and_private_telemetry(fake):
    result = fake.runtime.answer(request())
    assert [p for p, _ in fake.seen] == ["/apply-template", "/v1/chat/completions/input_tokens",
                                        "/v1/chat/completions", "/tokenize"]
    template, counted, native = [body for _, body in fake.seen[:3]]
    assert template == counted == native
    payload = json.loads(native["messages"][-1]["content"])
    assert payload["question"] == QUESTION and payload["target_language"] == "ko"
    assert [s["passages"][0]["text"] for s in payload["sources"]] == TEXTS
    assert native["max_tokens"] == native["n_predict"] == 1312
    assert native["reasoning_budget_tokens"] == 512
    assert native["chat_template_kwargs"] == {"enable_thinking": True}
    assert native["cache_prompt"] is False
    citations = result["claims"][0]["citations"]
    assert [c["quote"] for c in citations] == TEXTS
    assert all(c["start_offset"] == 10 for c in citations)
    telemetry = json.dumps(result["telemetry"], ensure_ascii=False)
    assert all(secret not in telemetry for secret in [QUESTION, *TEXTS, "Private synthetic reasoning."])
    assert result["telemetry"]["calls"][0]["final_retokenized_tokens"] == 45
    assert result["telemetry"]["calls"][0]["reasoning_budget_effective_serialized"] is False
    assert fake.generator._deadline is None and not fake.runtime.lock.locked()


@pytest.mark.parametrize("content", ['{"status":"abstained","claims":[]}', CONTENT])
def test_valid_answer_or_whole_abstention_never_repaired(fake, content):
    fake.raw = response(content)
    result = fake.runtime.answer(request())
    assert result["status"] == json.loads(content)["status"]
    assert sum(p == "/v1/chat/completions" for p, _ in fake.seen) == 1


@pytest.mark.parametrize("field,value,posts", [
    ("input_count", 6145, 0), ("input_count", True, 0),
    ("final_count", 769, 1), ("final_count", 0, 1)])
def test_admission_and_retokenized_limit_no_retry(fake, field, value, posts):
    setattr(fake, field, value)
    with pytest.raises(WorkerError):
        fake.runtime.answer(request())
    assert sum(p == "/v1/chat/completions" for p, _ in fake.seen) == posts
    assert fake.generator._deadline is None and not fake.runtime.lock.locked()


@pytest.mark.parametrize("location,key,value", [
    ("settings", "n_predict", 768), ("settings", "max_tokens", 1313),
    ("settings", "seed", True), ("settings", "reasoning_format", "none"),
    ("settings", "stop", ["user stop"]), ("settings", "grammar", ""),
    ("native", "tokens", [1]), ("native", "tokens_evaluated", 101),
    ("native", "truncated", True), ("native", "stop_type", "limit"),
    ("native", "prompt", "other"), ("native", "model", "other"),
    ("timings", "cache_n", 1), ("timings", "predicted_n", 41),
    ("message", "reasoning_content", ""), ("message", "tool_calls", [{"name": "tool"}]),
    ("top", "system_fingerprint", "wrong"), ("top", "model", "other"),
    ("usage", "completion_tokens", 39), ("usage", "total_tokens", 141),
    ("choice", "finish_reason", "length")])
def test_native_chat_identity_limits_and_split_fail_closed(location, key, value):
    raw = response()
    targets = {"settings": raw["__verbose"]["generation_settings"], "native": raw["__verbose"],
        "timings": raw["__verbose"]["timings"], "message": raw["choices"][0]["message"],
        "choice": raw["choices"][0], "top": raw, "usage": raw["usage"]}
    targets[location][key] = value
    with pytest.raises(GenerationError):
        m.validate_reasoning_response(raw, prompt=PROMPT, input_tokens=100)


def test_native_total_cap_independent_of_final_retokenization():
    assert m.validate_reasoning_response(response(count=1312), prompt=PROMPT, input_tokens=100)[1] == 1312
    with pytest.raises(GenerationError):
        m.validate_reasoning_response(response(count=1313), prompt=PROMPT, input_tokens=100)


@pytest.mark.parametrize("raw_content", ["wrong</think>" + CONTENT,
    "Private synthetic reasoning.</think>```json\n" + CONTENT,
    "Private synthetic reasoning.</think>prefix" + CONTENT])
def test_no_split_framing_salvage(raw_content):
    raw = response()
    raw["__verbose"]["content"] = raw_content
    with pytest.raises(GenerationError):
        m.validate_reasoning_response(raw, prompt=PROMPT, input_tokens=100)


def test_bad_citation_fails_after_single_native_call(fake):
    fake.raw = response(CONTENT.replace("[0,1]", "[17]"))
    with pytest.raises(WorkerError, match="generation_invalid_evidence"):
        fake.runtime.answer(request())
    assert sum(p == "/v1/chat/completions" for p, _ in fake.seen) == 1


def test_shared_deadline_covers_capture_preparation_and_projection(fake, monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(m.time, "monotonic", lambda: clock[0])
    fake.runtime.set_development_capture(lambda _: clock.__setitem__(0, 160.0))
    with pytest.raises(WorkerError, match="generation_deadline_exceeded"):
        fake.runtime.answer(request())
    assert fake.seen == []
    assert fake.runtime.last_telemetry["failure_code"] == "generation_deadline_exceeded"
    assert fake.runtime.last_telemetry["request_stage"] == "template"
    assert fake.runtime.last_telemetry["native_call"]["dispatch_intent"] is False
    assert fake.runtime.last_telemetry["native_call"]["returned"] is False
    fake.runtime.set_development_capture(None)
    clock[0] = 10.0
    real_projector = m.grounded_answer_refs
    def slow_projector(*args):
        result = real_projector(*args)
        clock[0] = 160.0
        return result
    monkeypatch.setattr(m, "grounded_answer_refs", slow_projector)
    with pytest.raises(WorkerError, match="generation_deadline_exceeded"):
        fake.runtime.answer(request())
    assert not fake.runtime.lock.locked()


def test_busy_empty_input_and_cleanup_failure_release_lock(fake, monkeypatch):
    fake.runtime.lock.acquire()
    with pytest.raises(WorkerError, match="model_busy"):
        fake.runtime.answer(request())
    fake.runtime.lock.release()
    empty = request().model_copy(update={"contexts": []})
    assert fake.runtime.answer(empty)["status"] == "abstained" and fake.seen == []
    def broken_cleanup():
        raise RuntimeError("cleanup failed")
    monkeypatch.setattr(fake.generator, "end_request", broken_cleanup)
    with pytest.raises(WorkerError, match="generation_cleanup_failed"):
        fake.runtime.answer(empty)
    assert not fake.runtime.lock.locked()


@pytest.mark.parametrize("context", [6144, 8192])
def test_pinned_manifest_model_props_and_startup_deadline(fake, tmp_path, monkeypatch, context):
    # A small metadata fixture and mocked base loader; never hash/read model bytes.
    path = tmp_path / "manifest.json"
    path.write_bytes(b"synthetic identity")
    fake.generator.manifest_path = path
    monkeypatch.setattr(m, "MANIFEST_SHA256", m.hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(m.GGUFGenerator, "load", lambda self: self)
    fake.generator._metadata["runtime"]["context_tokens"] = context
    if context == 6144:
        with pytest.raises(GenerationError, match="generation_identity_mismatch"):
            fake.generator.load()
    else:
        fake.generator.load()
        assert fake.generator.public_metadata()["reasoning_profile"]["hardware_fit_measured"] is False
    assert fake.generator._deadline is None


def test_expired_startup_fails_before_manifest_read(fake):
    with pytest.raises(GenerationError, match="generation_deadline_exceeded"):
        fake.generator.load(deadline=0)


def test_frozen_profile_settings_unchanged():
    assert m.FROZEN_SETTINGS["n_predict"] == m.FROZEN_SETTINGS["max_tokens"] == 928
    assert m.LIMITS["owned_rss_bytes"] == 8 * 1024**3


def test_old_counter_resource_probe_and_analysis_are_not_exposed(fake):
    with pytest.raises(GenerationError, match="reasoning_requires_full_chat_body"):
        fake.generator.count_tokens([])
    with pytest.raises(GenerationError, match="reasoning_qa_only"):
        fake.generator.generate_neutral([], {})
    with pytest.raises(WorkerError, match="analysis_not_supported"):
        fake.runtime.analyze(None)
    assert fake.seen == []


@pytest.mark.parametrize("cleanup_breaks", [False, True])
def test_failure_telemetry_preserves_projection_counts_and_first_error(fake, monkeypatch, cleanup_breaks):
    fake.raw = response(CONTENT.replace("[0,1]", "[17]"))
    if cleanup_breaks:
        monkeypatch.setattr(fake.generator, "end_request", lambda: (_ for _ in ()).throw(
            RuntimeError("private cleanup exception")))
    with pytest.raises(WorkerError, match="generation_invalid_evidence"):
        fake.runtime.answer(request())
    report = fake.runtime.last_telemetry
    assert report["failure_code"] == "generation_invalid_evidence"
    assert report["request_stage"] == "citation_projection"
    assert report["native_call"]["output_tokens"] == 40
    assert report["native_call"]["input_tokens"] == 100
    assert report["native_call"]["returned"] is True
    assert report["calls"][0]["output_tokens"] == 40
    assert report["cleanup_failed"] is cleanup_breaks
    assert "private cleanup exception" not in repr(report)
    assert not fake.runtime.lock.locked()


def test_failure_telemetry_retains_native_observations_before_validation(fake):
    fake.raw["__verbose"]["generation_settings"]["seed"] = 7
    with pytest.raises(WorkerError):
        fake.runtime.answer(request())
    report = fake.runtime.last_telemetry
    assert report["failure_code"] == "generation_effective_config_mismatch"
    assert report["request_stage"] == "native_validation"
    assert report["native_call"]["observed_output_tokens"] == 40
    assert "output_tokens" not in report["native_call"]
    assert report["native_call"]["accepted"] is False


def test_failure_telemetry_deadline_after_projection_keeps_completed_call(fake, monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(m.time, "monotonic", lambda: clock[0])
    project = m.grounded_answer_refs
    def slow_project(*args):
        answer = project(*args)
        clock[0] = 160.0
        return answer
    monkeypatch.setattr(m, "grounded_answer_refs", slow_project)
    with pytest.raises(WorkerError, match="generation_deadline_exceeded"):
        fake.runtime.answer(request())
    report = fake.runtime.last_telemetry
    assert report["failure_code"] == "generation_deadline_exceeded"
    assert report["request_stage"] == "response_validation"
    assert report["native_call"]["output_tokens"] == 40
    assert report["elapsed_ms"] == 150000


def test_failure_telemetry_unknown_error_and_cleanup_are_safe(fake, monkeypatch):
    def bad_project(*args):
        raise WorkerError("private source " + QUESTION, 599)
    monkeypatch.setattr(m, "grounded_answer_refs", bad_project)
    with pytest.raises(WorkerError, match="^generation_failed$") as error:
        fake.runtime.answer(request())
    assert error.value.status == 503
    assert fake.runtime.last_telemetry["failure_code"] == "generation_failed"
    assert QUESTION not in json.dumps(fake.runtime.last_telemetry, ensure_ascii=False)
    monkeypatch.setattr(fake.generator, "end_request", lambda: (_ for _ in ()).throw(
        RuntimeError("private cleanup text")))
    with pytest.raises(WorkerError, match="^generation_cleanup_failed$"):
        fake.runtime.answer(request().model_copy(update={"contexts": []}))
    assert fake.runtime.last_telemetry["failure_code"] == "generation_cleanup_failed"
    assert fake.runtime.last_telemetry["request_stage"] == "cleanup"
    assert fake.runtime.last_telemetry["cleanup_failed"] is True
    assert not fake.runtime.lock.locked()
