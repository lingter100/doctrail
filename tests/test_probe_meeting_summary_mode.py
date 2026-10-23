"""Synthetic HTTP/clock/process doubles only; no actual-run path or native launch."""
from __future__ import annotations

import copy
import json
import sys
import types
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest

from doctrail.generation_runtime import GenerationError
from doctrail.inference import WorkerError
from doctrail.meeting_grounded_summary import parse_draft, summary_messages
from scripts import probe_meeting_summary_mode as p


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def documents():
    content = "  \n반복 문장입니다.\n반복 문장입니다.\n  "
    return [{"id": f"synthetic-{i}", "document_id": f"00000000-0000-0000-0000-{i:012d}",
             "revision": 1, "title": "합성 원문 <think> 제목", "content": content,
             "content_sha256": p.sha(content.encode())} for i in range(1, 5)]


DRAFT = '{"status":"draft","claims":[{"evidence":[0],"text":"합성 문장입니다."}]}'
REVIEW = '{"claims":[[0,"supported"]],"coverage":"sufficient"}'
REJECTED = '{"claims":[[0,"uncertain"]],"coverage":"insufficient"}'


def completed_report(first_failure=None):
    return {"status": "completed", "first_failure": first_failure, "bindings_unchanged": True,
            "unexecuted": [], "arms": [{"status": "accepted", "generation_status": "returned",
                                          "review_status": "returned"} for _ in range(8)],
            "counts": {k: 8 for k in ("generation", "review", "generation_validated", "review_validated")}}


def generation_response(prompt, thinking, *, final=DRAFT, count=50, input_n=100):
    reason = "Synthetic reasoning only." if thinking else ""
    raw = reason + "\n</think>\n\n" + final if thinking else final
    return {"object": "chat.completion", "model": p.GGUF_SHA256,
        "system_fingerprint": "b11429-d81235049", "choices": [{"index": 0,
            "finish_reason": "stop", "message": {"role": "assistant",
                "reasoning_content": reason, "content": final}}],
        "usage": {"prompt_tokens": input_n, "completion_tokens": count,
            "total_tokens": input_n + count, "prompt_tokens_details": {"cached_tokens": 0}},
        "__verbose": {"model": p.GGUF_SHA256, "prompt": prompt, "content": raw,
            "tokens": list(range(count)), "tokens_predicted": count, "tokens_evaluated": input_n,
            "stop": True, "truncated": False, "stop_type": "eos",
            "generation_settings": {**p.generation_settings(thinking), "grammar": "synthetic root"},
            "timings": {"prompt_n": input_n, "predicted_n": count, "cache_n": 0}}}


class HTTP:
    def __init__(self, clock=None):
        self.clock = clock or Clock()
        self.requests, self.completions = [], []
        self.input_n, self.final_n, self.output_n = 100, 10, 50
        self.final, self.review_raw = DRAFT, REVIEW
        self.mutate = lambda response: None
        self.tick = lambda path: None
        self.template_delta = ""
        self.fail_at = None

    def prompt(self, body):
        thinking = body["chat_template_kwargs"]["enable_thinking"]
        return (p.encoded(body["messages"]).decode() + (self.template_delta if thinking else "")
                + (p.PREAMBLE if thinking else p.NONTHINKING_PREAMBLE))

    def __call__(self, request):
        path, body = request.url.path, json.loads(request.content)
        self.requests.append((path, body, dict(request.extensions.get("timeout", {}))))
        self.tick(path)
        if path == self.fail_at:
            return httpx.Response(503, json={"error": "synthetic"})
        if path == "/apply-template":
            return httpx.Response(200, json={"prompt": self.prompt(body)})
        if path == "/tokenize":
            return httpx.Response(200, json={"tokens": list(range(self.input_n if body["parse_special"] else self.final_n))})
        self.completions.append((path, body))
        if path == "/v1/chat/completions":
            response = generation_response(self.prompt(body), body["chat_template_kwargs"]["enable_thinking"],
                final=self.final, count=self.output_n, input_n=self.input_n)
        else:
            assert path == "/completion"
            response = {"model": p.GGUF_SHA256, "content": self.review_raw, "tokens": list(range(20)),
                "tokens_predicted": 20, "tokens_evaluated": self.input_n, "truncated": False,
                "stop": True, "stop_type": "eos", "generation_settings": {
                    **p.GREEDY, "n_predict": 128, "grammar": p.REVIEW_GRAMMAR},
                "timings": {"prompt_n": self.input_n, "predicted_n": 20, "cache_n": 0}}
        self.mutate(response)
        return httpx.Response(200, json=response)


@contextmanager
def adapter(http):
    gen = p.ModeAdapter("http://127.0.0.1:8123", "x" * 40, "unused-synthetic-manifest",
                        transport=httpx.MockTransport(http), clock=http.clock)
    gen._alias = p.GGUF_SHA256
    gen.begin_request(180)
    try:
        yield gen
    finally:
        gen.end_request()
        gen.close()


def run(http, **kwargs):
    events = []
    with adapter(http) as gen:
        report = p.diagnose(documents(), gen, active_deadline=1500,
            emit=lambda kind, value: events.append((kind, copy.deepcopy(value))), clock=http.clock, **kwargs)
    return report, events


@pytest.mark.parametrize("thinking", [False, True])
def test_chat_exact_limits_and_final_review_reasoning_separation(thinking):
    http = HTTP()
    with adapter(http) as gen:
        cat = p.source_catalog(documents()[0], gen)
        messages = summary_messages(cat["source"])
        admitted = gen.prepare(messages, thinking, 150)
        result = gen.generate(messages, thinking, admitted, 150)
        claims = parse_draft(result["content"], cat["units"], documents()[0]["content"])
        reviewed = gen.review(summary_messages(cat["source"], claims), 180)
        assert reviewed["content"] == REVIEW
        assert result["final_retokenized_tokens"] == 10
        assert result["telemetry"]["independent_reasoning_hard_cap_verified"] is False
        assert gen.counts["generation"] == gen.counts["review"] == 1
    generation, review = http.completions
    assert generation[1]["n_predict"] == generation[1]["max_tokens"] == 1312
    assert generation[1]["reasoning_budget_tokens"] == 512
    assert review[1]["grammar"] == p.REVIEW_GRAMMAR and review[1]["n_predict"] == 128
    assert "Synthetic reasoning" not in json.dumps(review)


def test_only_mode_differs_in_generation_body():
    messages = [{"role": "user", "content": "synthetic"}]
    a, b = p.generation_body(messages, False), p.generation_body(messages, True)
    assert a.pop("chat_template_kwargs") == {"enable_thinking": False}
    assert b.pop("chat_template_kwargs") == {"enable_thinking": True}
    assert a == b
    a["messages"][0]["content"] = "mutation"
    assert messages[0]["content"] == "synthetic"


@pytest.mark.parametrize("name,bound,good", [("input_n", 4096, True), ("input_n", 4097, False),
    ("output_n", 1312, True), ("output_n", 1313, False), ("final_n", 768, True), ("final_n", 769, False),
    ("input_n", 0, False), ("final_n", 0, False)])
def test_token_boundaries(name, bound, good):
    http = HTTP()
    setattr(http, name, bound)
    with adapter(http) as gen:
        messages = [{"role": "user", "content": "synthetic"}]
        def call():
            admitted = gen.prepare(messages, True, 150)
            return gen.generate(messages, True, admitted, 150)
        if good:
            assert call()["content"] == DRAFT
        else:
            with pytest.raises(ValueError):
                call()
    if name == "input_n" and not good:
        assert http.completions == []
    else:
        assert len(http.completions) == 1


@pytest.mark.parametrize("target,key,value", [
    ("top", "model", "wrong"), ("top", "system_fingerprint", "wrong"),
    ("native", "truncated", True), ("native", "stop_type", "limit"),
    ("native", "stop", False), ("native", "tokens", [0]),
    ("native", "tokens_evaluated", True), ("native", "prompt", "changed"),
    ("settings", "temperature", True), ("settings", "n_predict", 928),
    ("settings", "max_tokens", 1313), ("settings", "seed", 1),
    ("settings", "generation_prompt", p.NONTHINKING_PREAMBLE),
    ("settings", "stop", ["text stop"]), ("settings", "grammar", ""),
    ("settings", "reasoning_in_content", True), ("settings", "samplers", ["top_k"]),
    ("timing", "cache_n", 1), ("timing", "predicted_n", 49),
    ("usage", "total_tokens", 10), ("choice", "finish_reason", "length"),
    ("message", "tool_calls", [{"name": "tool"}]), ("message", "reasoning_content", ""),
    ("message", "content", "<think>leak</think>"),
    ("native", "content", "different</think>" + DRAFT),
])
def test_native_response_drift_stops_before_review(target, key, value):
    http = HTTP()
    def mutate(response):
        if "__verbose" not in response:
            return
        native = response["__verbose"]
        targets = {"top": response, "native": native, "settings": native["generation_settings"],
            "timing": native["timings"], "usage": response["usage"], "choice": response["choices"][0],
            "message": response["choices"][0]["message"]}
        targets[target][key] = value
    # B is first here solely for adapter validation; orchestration tests use fixed A/B order.
    http.mutate = mutate
    with adapter(http) as gen:
        messages = [{"role": "user", "content": "synthetic"}]
        prepared = gen.prepare(messages, True, 150)
        with pytest.raises((ValueError, WorkerError, GenerationError)):
            gen.generate(messages, True, prepared, 150)
    assert len(http.completions) == 1


@pytest.mark.parametrize("raw", [
    '{"status":"draft","status":"draft","claims":[]}',
    DRAFT + DRAFT, '```json\n' + DRAFT + '\n```',
    '{"status":"draft","claims":[{"evidence":[0],"text":"English only"}]}',
    '{"status":"draft","claims":[]}',
    '{"status":"abstained","claims":[],"extra":1}',
])
def test_invalid_final_json_or_draft_stops_all(raw):
    http = HTTP()
    http.final = raw
    report, _ = run(http)
    assert report["status"] == "stopped"
    assert report["operational_failure"]
    assert len(http.completions) == 1 and len(report["unexecuted"]) == 7


def test_fenced_native_framing_is_compared_but_not_repaired():
    prompt = "input" + p.PREAMBLE
    raw = generation_response(prompt, True)
    raw["__verbose"]["content"] = "Synthetic reasoning only.\n</think>\n```json\n" + DRAFT + "\n```"
    result = p.validate_generation(raw, prompt, 100, True)
    assert result["content"] == DRAFT and result["telemetry"]["native_json_framing"] == "fenced"
    raw["__verbose"]["content"] += "unexplained"
    with pytest.raises(ValueError, match="reasoning_split"):
        p.validate_generation(raw, prompt, 100, True)


def test_nonthinking_reasoning_is_rejected():
    prompt = "input" + p.NONTHINKING_PREAMBLE
    raw = generation_response(prompt, False)
    raw["choices"][0]["message"]["reasoning_content"] = "leak"
    with pytest.raises(ValueError, match="reasoning_split"):
        p.validate_generation(raw, prompt, 100, False)


def test_success_fixed_order_full_source_and_candidate_isolation():
    http = HTTP()
    report, events = run(http)
    assert report["status"] == "completed" and report["first_failure"] is None
    assert report["unexecuted"] == [] and len(http.completions) == 16
    assert [x["mode"] for x in report["arms"]] == list("ABBAABBA")
    assert all(x["status"] == "accepted" for x in report["arms"])
    catalogs = [value for kind, value in events if kind == "catalog"]
    assert len(catalogs) == 4
    for cat in catalogs:
        assert "".join(x["text"] for x in cat["source"]["source_parts"]) == documents()[0]["content"]
        assert cat["source"]["untrusted_title"] == documents()[0]["title"]
        assert len(cat["units"]) == 2
        assert cat["units"][0]["quote"] == cat["units"][1]["quote"]
        assert cat["units"][0]["start_offset"] != cat["units"][1]["start_offset"]
    candidates = [v for k, v in events if k == "judge_candidate"]
    assert len(candidates) == 8
    assert all(set(v) == {"source", "claims"} for v in candidates)
    assert all("Synthetic reasoning" not in json.dumps(v) for v in candidates)
    # Both modes retain the complete same messages, schema and source. Only mode differs.
    generations = [body for path, body in http.completions if path == "/v1/chat/completions"]
    for left, right in zip(generations[::2], generations[1::2], strict=True):
        left.pop("chat_template_kwargs")
        right.pop("chat_template_kwargs")
        assert left == right


def test_valid_semantic_review_rejection_continues_only_next_arm():
    http = HTTP()
    http.review_raw = REJECTED
    report, _ = run(http)
    assert len(http.completions) == 16 and len(report["semantic_rejections"]) == 8
    assert report["first_failure"]["kind"] == "semantic_review"
    assert all(row["status"] == "semantic_review_rejected" for row in report["arms"])


def test_valid_generation_abstention_stops_with_no_review():
    http = HTTP()
    http.final = '{"status":"abstained","claims":[]}'
    report, events = run(http)
    assert report["first_failure"]["kind"] == "semantic_abstention"
    assert report["arms"][0]["status"] == "generation_abstained"
    assert len(report["unexecuted"]) == 7 and len(http.completions) == 1
    assert not any(k in {"review", "judge_candidate"} for k, _ in events)


@pytest.mark.parametrize("review", ['{"claims":[],"coverage":"insufficient"}',
    '{"claims":[[1,"supported"]],"coverage":"sufficient"}', REVIEW + REVIEW,
    '{"claims":[[0,"no"]],"coverage":"sufficient"}'])
def test_malformed_review_is_operational_stop_not_semantic_continue(review):
    http = HTTP()
    http.review_raw = review
    report, _ = run(http)
    assert len(http.completions) == 2 and len(report["unexecuted"]) == 7
    assert report["first_failure"]["kind"] == "operational"


@pytest.mark.parametrize("path", ["/apply-template", "/tokenize", "/v1/chat/completions", "/completion"])
def test_http_failure_is_terminal_without_retry(path):
    http = HTTP()
    http.fail_at = path
    report, _ = run(http)
    assert report["operational_failure"]
    assert sum(request[0] == path for request in http.requests) == 1
    assert len(http.completions) <= 1


def test_all_inputs_admitted_before_any_completion_and_preamble_parity():
    http = HTTP()
    http.template_delta = "mode-specific extra instructions"
    report, _ = run(http)
    assert report["first_failure"]["code"] == "summary_mode_mode_template_difference"
    assert http.completions == [] and len(report["unexecuted"]) == 8


def test_template_drift_after_admission_stops_before_dispatch():
    http = HTTP()
    with adapter(http) as gen:
        messages = [{"role": "user", "content": "synthetic"}]
        admitted = gen.prepare(messages, True, 150)
        http.template_delta = "drift"
        with pytest.raises(ValueError, match="template_drift"):
            gen.generate(messages, True, admitted, 150)
    assert http.completions == []


def test_generation_and_review_share_arm_deadline_no_restart():
    http = HTTP()
    def tick(path):
        if path == "/v1/chat/completions":
            http.clock.now += 149
        if path == "/completion":
            http.clock.now += 32
    http.tick = tick
    report, _ = run(http)
    assert len(http.completions) == 2 and len(report["unexecuted"]) == 7
    generation_timeout = next(r[2]["read"] for r in http.requests if r[0] == "/v1/chat/completions")
    review_timeout = next(r[2]["read"] for r in http.requests if r[0] == "/completion")
    assert generation_timeout == 150
    assert review_timeout == 31
    assert report["operational_failure"]


def test_generation_deadline_and_evidence_time_count():
    http = HTTP()
    http.tick = lambda path: setattr(http.clock, "now", http.clock.now + (150 if path == "/v1/chat/completions" else 0))
    report, _ = run(http)
    assert len(http.completions) == 1 and report["operational_failure"]
    http = HTTP()
    with adapter(http) as gen:
        def emit(kind, value):
            if kind == "generation":
                http.clock.now += 180
        report = p.diagnose(documents(), gen, active_deadline=1500, emit=emit, clock=http.clock)
    assert len(http.completions) == 1 and report["operational_failure"]


def test_first_semantic_failure_preserved_when_later_transport_fails():
    http = HTTP()
    http.review_raw = REJECTED
    def tick(path):
        if path == "/v1/chat/completions" and len(http.completions) == 2:
            http.fail_at = path
    http.tick = tick
    report, _ = run(http)
    assert report["first_failure"]["kind"] == "semantic_review"
    assert report["operational_failure"]["code"] == "generation_backend_unavailable"
    assert report["counts"]["generation"] == 2 and report["counts"]["review"] == 1


@pytest.mark.parametrize("change", ["hash", "duplicate", "uuid", "revision", "blank", "extra"])
def test_input_contract_preserves_identity(change):
    rows = documents()
    if change == "hash":
        rows[0]["content"] += "x"
    elif change == "duplicate":
        rows[1]["document_id"] = rows[0]["document_id"]
    elif change == "uuid":
        rows[0]["document_id"] = "invalid"
    elif change == "revision":
        rows[0]["revision"] = True
    elif change == "blank":
        rows[0]["title"] = " "
    else:
        rows[0]["selected_units"] = []
    with pytest.raises(ValueError):
        p.validate_input({"schema_version": 1, "diagnostic": p.ID, "documents": rows})


class FakePS:
    def __init__(self):
        self.created, self.rss, self.available = 7.0, 1, 10 * 1024**3

    def Process(self, pid):
        return SimpleNamespace(create_time=lambda: self.created,
            memory_info=lambda: SimpleNamespace(rss=self.rss))

    def virtual_memory(self):
        return SimpleNamespace(available=self.available)


def test_resource_boundary_and_reused_pid_never_killed():
    ps, killed = FakePS(), []
    process = SimpleNamespace(pid=123, poll=lambda: None, kill=lambda: killed.append(1))
    guard = p.ResourceGuard(process, ps=ps)
    ps.rss = 8 * 1024**3
    ps.available = 2 * 1024**3
    assert guard.check()["rss"] == ps.rss
    ps.created = 8
    with pytest.raises(ValueError, match="ownership"):
        guard.check()
    guard.stop_owned()
    assert killed == []


@pytest.mark.parametrize("field,value", [("rss", 8 * 1024**3 + 1), ("available", 2 * 1024**3 - 1)])
def test_resources_fail_closed(field, value):
    ps = FakePS()
    process = SimpleNamespace(pid=123, poll=lambda: None, kill=lambda: None)
    guard = p.ResourceGuard(process, ps=ps)
    setattr(ps, field, value)
    with pytest.raises(ValueError, match="resources"):
        guard.check()


def test_resource_error_aborts_remaining_completions():
    http = HTTP()
    class Guard:
        @contextmanager
        def arm(self, deadline, metrics):
            yield
            p.fail("resources")
    report, _ = run(http, guard=Guard())
    assert len(http.completions) == 2 and len(report["unexecuted"]) == 7
    assert report["operational_failure"]["code"] == "summary_mode_resources"


def test_evidence_exclusive_hash_index_and_no_actual_directory(tmp_path):
    evidence = p.Evidence(tmp_path)
    evidence("synthetic", {"test": True})
    evidence.seal({"eligible": False})
    files = sorted(tmp_path.glob("*.json"))
    assert len(files) == 3
    assert p.sha(files[0].read_bytes()) == evidence.index[0]["sha256"]
    assert not (p.ROOT / ".local" / p.ID).exists()


def test_cli_registration_refuses_unprepared_without_creating_output(tmp_path):
    path = tmp_path / "synthetic-registration.json"
    path.write_bytes(p.encoded({"schema_version": 1}))
    with pytest.raises((ValueError, KeyError)):
        p.verify_registration(path, p.sha(path.read_bytes()), tmp_path)
    assert sorted(x.name for x in tmp_path.iterdir()) == [path.name]


@pytest.mark.parametrize("name", ["../escape", "C:/escape", "a\\b", "/escape"])
def test_registration_path_escape(name, tmp_path):
    with pytest.raises(ValueError):
        p.bound_path(name, tmp_path)


def test_existing_transport_limits_unchanged():
    from doctrail import meeting_thinking_transport as old
    assert old.LIMITS["output_tokens"] == 928
    assert old.LIMITS["final_retokenized_tokens"] == 384
    assert old.LIMITS["request_seconds"] == 90
    assert old.SETTINGS["n_predict"] == 928


@pytest.mark.parametrize("whole_before,active_start,write_seconds,expected", [
    (1624, None, 0.5, True), (1624, None, 1, False),
    (1509, 10, 0.5, True), (1509, 10, 1, False)])
def test_final_write_time_is_included_in_whole_and_active_limits(
        whole_before, active_start, write_seconds, expected):
    clock, events = Clock(), []
    clock.now = whole_before
    class Sink:
        def seal(self, report):
            events.append(("seal", copy.deepcopy(report)))
            clock.now += write_seconds

        def __call__(self, kind, value):
            events.append((kind, value))
    report = completed_report()
    result = p.finalize(report, Sink(), clock=clock, started=0, active_start=active_start)
    assert result["eligible"] is expected
    assert result["whole_seconds_after_final_writes"] == whole_before + write_seconds
    assert result["requires_terminal_receipt"] is True
    assert (events[-1][0] == "finalization-failure") is (not expected)


def test_cleanup_time_is_not_counted_twice_but_whole_includes_it():
    clock = Clock()
    clock.now = 1504
    class Sink:
        def seal(self, report):
            pass

        def __call__(self, kind, value):
            pass
    result = p.finalize(completed_report(),
        Sink(), clock=clock, started=0, active_start=0, cleanup_seconds=5)
    assert result["eligible"] is True
    assert result["active_seconds_after_final_writes"] == 1499
    assert result["whole_seconds_after_final_writes"] == 1504


@pytest.mark.parametrize("native_change", ["review_tokens", "review_cache", "review_non_eos", "review_grammar"])
def test_review_integrity_failures_stop_remaining_arms(native_change):
    http = HTTP()
    def mutate(response):
        if "__verbose" in response:
            return
        if native_change == "review_tokens":
            response["tokens_predicted"] = 129
        elif native_change == "review_cache":
            response["timings"]["cache_n"] = True
        elif native_change == "review_non_eos":
            response["stop_type"] = "limit"
        else:
            response["generation_settings"]["grammar"] = "weakened"
    http.mutate = mutate
    report, _ = run(http)
    assert report["operational_failure"] and len(http.completions) == 2
    assert len(report["unexecuted"]) == 7


def test_review_admission_cap_can_stop_after_valid_generation():
    http = HTTP()
    def tick(path):
        if path == "/apply-template" and len(http.completions) == 1:
            http.input_n = 4097
    http.tick = tick
    report, _ = run(http)
    assert len(http.completions) == 1 and report["operational_failure"]["code"] == "summary_mode_input_limit"


def test_shared_final_review_maps_repeated_text_by_coordinates():
    http = HTTP()
    http.final = '{"status":"draft","claims":[{"evidence":[1],"text":"두 번째 합성 문장입니다."}]}'
    report, events = run(http)
    assert report["status"] == "completed"
    first = next(v for k, v in events if k == "judge_candidate")
    units = [x for x in first["source"]["source_parts"] if x["kind"] == "unit"]
    assert first["claims"][0]["citations"][0]["start_offset"] == units[1]["start_offset"]
    reviews = [body for path, body, _ in http.requests if path == "/apply-template"
               and "candidate_claims" in body["messages"][-1]["content"]]
    assert all(json.loads(body["messages"][-1]["content"])["candidate_claims"][0]["evidence"] == [1]
               for body in reviews)


@pytest.mark.parametrize("claims", [
    [{"evidence": [0], "text": "가" * 241}],
    [{"evidence": [0], "text": "가" * 201}] * 6,
    [{"evidence": [0], "text": "가"}] * 7,
    [{"evidence": [0, 0], "text": "가"}],
    [{"evidence": [1, 0], "text": "가"}],
    [{"evidence": [0, 1, 2, 3, 4], "text": "가"}],
    [{"evidence": [True], "text": "가"}],
    [{"evidence": [159], "text": "가"}],
])
def test_existing_draft_limits_remain_authoritative(claims):
    http = HTTP()
    http.final = json.dumps({"status": "draft", "claims": claims}, ensure_ascii=False)
    report, _ = run(http)
    assert report["operational_failure"] and len(http.completions) == 1


def test_resource_sampler_has_new_721_bound_without_changing_old_sampler(monkeypatch):
    ps, clock, metrics = FakePS(), Clock(), {}
    process = SimpleNamespace(pid=123, poll=lambda: None, kill=lambda: None)
    class Event:
        stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, seconds):
            assert seconds == 0.25
            clock.now += seconds

        def set(self):
            self.stopped = True
    class Thread:
        def __init__(self, *, target, daemon, name):
            self.target = target

        def start(self):
            self.target()

        def join(self, timeout):
            pass

        def is_alive(self):
            return False
    # Replace the new module's namespace only, never the shared threading module.
    monkeypatch.setattr(p, "threading", SimpleNamespace(Event=Event, Thread=Thread))
    guard = p.ResourceGuard(process, clock=clock, ps=ps)
    with guard.arm(1000, metrics):
        pass
    assert len(metrics["samples"]) == 721 and metrics["joined"] is True


def test_exact_completion_cap_blocks_seventeenth_dispatch():
    http = HTTP()
    with adapter(http) as gen:
        gen.counts["generation"] = 8
        gen.counts["review"] = 8
        with pytest.raises(ValueError, match="completion_cap"):
            gen._request("POST", "/completion", {}, 180)
    assert http.requests == []


def test_evidence_write_failure_stops_before_more_completion():
    http = HTTP()
    calls = []
    with adapter(http) as gen:
        def emit(kind, value):
            calls.append(kind)
            if kind == "judge_candidate":
                raise OSError("synthetic evidence storage failure")
        report = p.diagnose(documents(), gen, active_deadline=1500, emit=emit, clock=http.clock)
    assert report["operational_failure"]["type"] == "OSError" and len(http.completions) == 1
    assert "review" not in calls


@pytest.mark.parametrize("startup_failure,cleanup_ok", [(False, True), (True, True), (False, False)])
def test_execute_lifecycle_with_fake_owner_and_http_only(tmp_path, monkeypatch, startup_failure, cleanup_ok):
    http, cleanup_calls, starts = HTTP(), [], []
    output = tmp_path / "synthetic-evidence"
    registration = tmp_path / "synthetic-registration.json"
    registration.write_bytes(b"{}")
    reference = {"file": registration.name, **p.digest(registration)}
    spec = {"plan": reference, "amendment": reference, "provenance_boundary": reference, "input": reference, "source_receipt": reference,
            "source_lock": reference, "code": [], "assets": [], "runtime": {"argv": p.normalized_argv(28)}}
    manifest = tmp_path / "data/models/meetings-generation-qwen35-v1.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(p.MANIFEST.read_bytes())
    monkeypatch.setattr(p, "verify_registration", lambda *a: (spec, documents(), output))
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(
        virtual_memory=lambda: SimpleNamespace(available=10 * 1024**3)))
    monkeypatch.setitem(sys.modules, "scripts.probe_meeting_gpu_placement", SimpleNamespace(
        gpu_checkpoint=lambda **kwargs: {"query_stopped": True, "error": None, "uuid": "synthetic-gpu"}))
    process = SimpleNamespace(pid=123, poll=lambda: None)
    @contextmanager
    def launcher(**kwargs):
        starts.append(kwargs)
        if startup_failure:
            raise ValueError("summary_mode_synthetic_startup")
        kwargs["telemetry"].update(process_started=True, process_creation_attempted=True)
        try:
            yield SimpleNamespace(process=process, drain=None, url="http://127.0.0.1:8123",
                                  token="x" * 40, manifest=manifest)
        finally:
            cleanup(process, None, kwargs["telemetry"])
    monkeypatch.setattr(p, "owned_launcher", launcher)
    def cleanup(owned, drain, metrics):
        assert owned is process
        cleanup_calls.append(owned.pid)
        metrics.update(stopped=cleanup_ok, process_absence_confirmed=cleanup_ok, within_budget=cleanup_ok, seconds=1)
        http.clock.now += 1
    monkeypatch.setattr(p, "cleanup_owned", cleanup)
    class Guard:
        def __init__(self, *args, **kwargs):
            self.created = 123.0

        def check(self):
            pass

        @contextmanager
        def arm(self, deadline, metrics):
            yield
    monkeypatch.setattr(p, "ResourceGuard", Guard)
    original = p.ModeAdapter
    def factory(*args, **kwargs):
        gen = original(*args, transport=httpx.MockTransport(http), **kwargs)
        gen.load = lambda: gen  # Synthetic identity seam; no /props, hashing or native process.
        return gen
    monkeypatch.setattr(p, "ModeAdapter", factory)
    result = p.execute(registration, p.sha(registration.read_bytes()), root=tmp_path, clock=http.clock)
    assert result["eligible"] is (cleanup_ok and not startup_failure)
    assert starts[0]["phase_deadline"] == 120 and starts[0]["gpu_layers"] == 28
    if startup_failure:
        assert cleanup_calls == [] and len(result["unexecuted"]) == 8
        assert http.completions == []
    else:
        assert cleanup_calls == [123] and len(http.completions) == 16
    assert result["product_writes"] == 0 and result["hard_blocking_io_preemption_proven"] is False
    assert list(output.glob("*-index.json"))


def test_repair_sm01_mixed_reviews_complete_operationally():
    http = HTTP()
    def tick(path):
        if path == "/completion":
            http.review_raw = REJECTED if len(http.completions) == 1 else REVIEW
    http.tick = tick
    report, _ = run(http)
    report["bindings_unchanged"] = True
    class Sink:
        def seal(self, value):
            pass

        def __call__(self, kind, value):
            pass
    result = p.finalize(report, Sink(), clock=http.clock, started=0, active_start=0)
    assert len(http.completions) == 16
    assert result["first_failure"]["kind"] == "semantic_review"
    assert result["eligible"] is True


def test_repair_sm02_rejection_then_abstention_keeps_first_failure():
    http = HTTP()
    http.review_raw = REJECTED
    def tick(path):
        if path == "/v1/chat/completions" and len(http.completions) == 2:
            http.final = '{"status":"abstained","claims":[]}'
    http.tick = tick
    report, _ = run(http)
    assert len(http.completions) == 3 and len(report["unexecuted"]) == 6
    assert report["first_failure"]["kind"] == "semantic_review"
    assert report["stop_reason"]["kind"] == "semantic_abstention"
    assert report["arms"][-1]["review_not_started_reason"] == "generation_abstained_no_claims"


def test_repair_sm03_guard_exit_deadline_is_terminal():
    http = HTTP()
    class Guard:
        @contextmanager
        def arm(self, deadline, metrics):
            yield
            metrics["joined"] = True
            http.clock.now = deadline + 0.01
    report, _ = run(http, guard=Guard())
    assert len(http.completions) == 2
    assert report["operational_failure"]
    assert report["arms"][0]["elapsed_seconds"] > 180


@pytest.mark.parametrize("active_start,sequence", [(None, [0, 1624.99, 1625.01]),
    (0, [0, 1499.98, 1499.99, 1500.01, 1500.02])])
def test_repair_sm04_terminal_clock_and_verdict_agree(active_start, sequence):
    values = iter(sequence)
    last = sequence[-1]
    clock = lambda: next(values, last)
    class Sink:
        def seal(self, report):
            pass

        def __call__(self, kind, value):
            pass
    result = p.finalize(completed_report(),
        Sink(), clock=clock, started=0, active_start=active_start)
    if result["eligible"]:
        assert result["whole_seconds_after_final_writes"] < 1625
        assert active_start is None or result["active_seconds_after_final_writes"] < 1500


def test_repair_sm05_drain_constructor_failure_keeps_returned_owner(tmp_path):
    calls = []
    class Process:
        pid = 123
        stdout = SimpleNamespace(close=lambda: calls.append("pipe-close"))
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            calls.append("terminate")
            self.returncode = 0

        def kill(self):
            calls.append("kill")
            self.returncode = 0

        def wait(self, timeout):
            calls.append("wait")
            return self.returncode
    process = Process()
    def drain(stream):
        raise RuntimeError("synthetic drain constructor")
    @contextmanager
    def lease(path):
        yield
    # Clone only the function's globals into an isolated test namespace. Neither
    # subprocess nor the shared/frozen launcher module is monkeypatched.
    launch = getattr(p, "owned_launcher", getattr(p, "start_llama", None))
    original = launch.__wrapped__
    namespace = dict(original.__globals__)
    namespace.update(DiscardDrain=drain, worker_lease=lease,
        prepare=lambda *a, **k: {"server_path": "runtime/llama-server.exe", "model": {"path": "model.gguf"}},
        subprocess=SimpleNamespace(Popen=lambda *a, **k: process, PIPE=-1, STDOUT=-2,
                                   TimeoutExpired=TimeoutError),
        unused_port=lambda: 12345, wait_ready=lambda *a, **k: None, owned_create_time=lambda process: 1.0)
    copied = types.FunctionType(original.__code__, namespace, original.__name__, original.__defaults__, original.__closure__)
    copied.__kwdefaults__ = original.__kwdefaults__
    launcher = contextmanager(copied)
    metrics = {}
    with pytest.raises(RuntimeError, match="synthetic drain constructor"), launcher(
            gpu_layers=28, log_dir=tmp_path / "synthetic-native-log", model_dir=tmp_path,
            manifest=p.MANIFEST, telemetry=metrics, phase_deadline=999999999):
        pytest.fail("must not yield")
    assert "terminate" in calls
    assert metrics["process_absence_confirmed"] is True


def test_repair_smn1_observer_failure_is_not_client_dispatch():
    http = HTTP()
    with adapter(http) as gen:
        def observe(kind, value):
            if kind == "http_request" and value["path"] == "/v1/chat/completions":
                raise OSError("synthetic request evidence failure")
        gen.observe = observe
        prepared = gen.prepare([{"role": "user", "content": "synthetic"}], False, 150)
        with pytest.raises(OSError):
            gen.generate([{"role": "user", "content": "synthetic"}], False, prepared, 150)
        assert gen.counts["generation"] == 0
    assert http.completions == []


def cloned(function, **replacements):
    namespace = {**function.__globals__, **replacements}
    copied = types.FunctionType(function.__code__, namespace, function.__name__,
                                function.__defaults__, function.__closure__)
    copied.__kwdefaults__ = function.__kwdefaults__
    return copied


def fake_owned_launch(tmp_path, *, stage=None, clock=None, wait_delays=(), close_delay=0):
    """Isolated function globals; no shared helper or subprocess state is changed."""
    clock, events = clock or Clock(), []
    delays = iter(wait_delays)
    class Pipe:
        closed = False

        def close(self):
            events.append(("pipe_close", clock()))
            clock.now += close_delay
            self.closed = True
    class Handle:
        closed = False

        def Close(self):
            events.append(("handle_close",))
            self.closed = True
    class Process:
        pid, returncode = 123, None
        stdout, stderr, stdin = Pipe(), None, None
        _handle = Handle()

        def poll(self):
            return self.returncode

        def terminate(self):
            events.append(("terminate", clock()))
            if stage == "terminate_error":
                raise OSError("synthetic terminate failure")
            if not wait_delays:
                self.returncode = 0

        def kill(self):
            events.append(("kill", clock()))
            if stage == "kill_error":
                raise OSError("synthetic kill failure")
            self.returncode = 0

        def wait(self, timeout):
            events.append(("wait", timeout, clock()))
            clock.now += next(delays, 0)
            if self.returncode is None:
                raise p.subprocess.TimeoutExpired("synthetic", timeout)
            return self.returncode
    process = Process()
    class Drain:
        def __init__(self, stream):
            events.append(("drain_construct",))
            if stage == "drain_constructor":
                raise RuntimeError("synthetic drain_constructor")
            self.stream, self.started, self.alive, self.ident = stream, False, False, None
            self.thread = SimpleNamespace(is_alive=lambda: self.alive, ident=None)

        def start(self):
            events.append(("drain_start",))
            if stage == "drain_start_before":
                raise RuntimeError("synthetic drain_start_before")
            self.thread.ident, self.alive = 7, True
            if stage == "drain_start_after":
                raise RuntimeError("synthetic drain_start_after")
            self.started = True

        def join(self, seconds):
            events.append(("drain_join", seconds))
            self.alive = stage == "drain_still_alive"

        def metadata(self):
            return {"started": self.started, "joined": self.started and not self.alive,
                    "read_errors": 0, "join_errors": int(self.alive), "eof": not self.alive}
    @contextmanager
    def lease(path):
        events.append(("lease_enter", path.name))
        try:
            yield
        finally:
            events.append(("lease_exit", path.name))
    def prepare(*args, **kwargs):
        events.append(("prepare", kwargs["allow_download"]))
        if stage == "prepare":
            raise RuntimeError("synthetic prepare")
        return {"server_path": "runtime/llama-server.exe", "model": {"path": "model.gguf"}}
    def popen(argv, **kwargs):
        events.append(("popen", argv, kwargs))
        if stage == "popen":
            raise OSError("synthetic popen")
        return process
    def created(owner):
        assert owner is process
        events.append(("create_time",))
        if stage == "create_time":
            raise RuntimeError("synthetic create_time")
        return 7.0
    def ready(owner, url, **kwargs):
        assert owner is process
        events.append(("readiness", url, kwargs["timeout"]))
        if stage == "readiness":
            raise RuntimeError("synthetic readiness")
    shared_cleanup = cloned(p.cleanup_owned, time=SimpleNamespace(monotonic=clock))
    cleanup = cloned(p.cleanup_owner, cleanup_owned=shared_cleanup)
    raw = cloned(p.owned_launcher.__wrapped__, worker_lease=lease, prepare=prepare,
        DiscardDrain=Drain, owned_create_time=created, wait_ready=ready, cleanup_owner=cleanup,
        os=SimpleNamespace(environ={"KEEP": "same", "LLAMA_ARG_MODEL": "must disappear"}),
        subprocess=SimpleNamespace(Popen=popen, PIPE=-1, STDOUT=-2, CREATE_NO_WINDOW=0x08000000),
        unused_port=lambda: 12345)
    launch = contextmanager(raw)
    metrics = {}
    kwargs = {"gpu_layers": 28, "log_dir": tmp_path / "synthetic-native-log",
        "model_dir": tmp_path, "manifest": p.MANIFEST, "telemetry": metrics,
        "phase_deadline": 120, "clock": clock, "token": "x" * 40,
        "expected_argv": p.normalized_argv(28)}
    return launch, kwargs, metrics, process, events, clock, cleanup


@pytest.mark.parametrize("stage", ["prepare", "popen", "create_time", "drain_constructor",
    "drain_start_before", "drain_start_after", "readiness", "guard", "adapter_load", "body"])
def test_repair_all_startup_boundaries_close_exact_owner_before_lease_release(tmp_path, stage):
    launch, kwargs, metrics, process, events, _, _ = fake_owned_launch(tmp_path, stage=stage)
    with pytest.raises((OSError, RuntimeError)), launch(**kwargs) as service:
        assert service.process is process
        raise RuntimeError("synthetic " + stage)
    returned = stage not in ("prepare", "popen")
    assert metrics["process_returned"] is returned
    assert metrics["process_creation_attempted"] is (stage != "prepare")
    if returned:
        assert metrics["owner_basis"] == "original_returned_popen_handle"
        assert process.returncode == 0 and process.stdout.closed
        assert metrics["process_absence_confirmed"] is True
        terminate_index = next(i for i, row in enumerate(events) if row[0] == "terminate")
        exit_index = next(i for i, row in enumerate(events) if row == ("lease_exit", "meeting-llama.lease"))
        assert terminate_index < exit_index
        if stage in ("create_time", "drain_constructor", "drain_start_before"):
            assert metrics["drain"]["joined"] is False
            assert metrics["drain_state"] == ("not_started" if stage == "drain_start_before" else "absent")
    elif stage == "popen":
        assert metrics["process_absence_confirmed"] is None
        assert metrics["within_budget"] is False
        assert not any(row[0] in ("terminate", "kill") for row in events)
    else:
        assert metrics["process_absence_confirmed"] is True


def test_repair_launcher_preserves_argv_environment_prepare_and_lease_sequence(tmp_path):
    launch, kwargs, metrics, process, events, _, _ = fake_owned_launch(tmp_path)
    with launch(**kwargs) as service:
        assert service.process is process and service.token == "x" * 40
        assert metrics["owned_create_time"] == 7.0
    call = next(row for row in events if row[0] == "popen")
    assert call[1] == p.command((tmp_path / "runtime/llama-server.exe").resolve(),
                                (tmp_path / "model.gguf").resolve(), 12345, 28)
    assert call[2]["env"] == {"KEEP": "same", "LLAMA_API_KEY": "x" * 40,
                                "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    assert call[2]["creationflags"] == 0x08000000
    assert call[2]["stdout"] == -1 and call[2]["stderr"] == -2 and call[2]["bufsize"] == 0
    assert ("prepare", False) in events
    assert [row for row in events if row[0].startswith("lease_")] == [
        ("lease_enter", "meeting-generation.gpu.lock"),
        ("lease_enter", "meeting-generation.worker.lock"),
        ("lease_exit", "meeting-generation.worker.lock"),
        ("lease_enter", "meeting-llama.lease"),
        ("lease_exit", "meeting-llama.lease"),
        ("lease_exit", "meeting-generation.gpu.lock")]
    assert metrics["within_budget"] is True and metrics["drain"]["joined"] is True
    assert metrics["remaining_drain_thread"] is False
    assert metrics["owned_process_handle"] == "closed" and process._handle.closed


@pytest.mark.parametrize("close_delay,within", [(0, True), (0.01, False)])
def test_repair_no_drain_shared_five_seconds_and_duplicate_cleanup(tmp_path, close_delay, within):
    launch, kwargs, metrics, process, events, clock, cleanup = fake_owned_launch(
        tmp_path, stage="drain_constructor", wait_delays=[2, 3], close_delay=close_delay)
    with pytest.raises(RuntimeError, match="drain_constructor"), launch(**kwargs):
        pytest.fail("unreachable")
    assert metrics["within_budget"] is within
    waits = [row[1] for row in events if row[0] == "wait"]
    assert waits == [2, 3]
    assert metrics["seconds"] == 5 + close_delay
    before = len(events)
    clock.now += 100
    cleanup(process, None, metrics, clock=clock)
    assert len(events) == before
    assert metrics["seconds"] == 5 + close_delay
    assert metrics["duplicate_cleanup_observations"] == 1


def test_repair_shared_drain_cleanup_failure_is_retained_without_extra_budget(tmp_path):
    launch, kwargs, metrics, _, events, _, _ = fake_owned_launch(tmp_path, stage="drain_still_alive")
    with launch(**kwargs):
        pass
    assert metrics["process_absence_confirmed"] is True
    assert metrics["remaining_drain_thread"] is True
    assert metrics["within_budget"] is False and metrics["owned_pipes_closed"] is False
    assert len([r for r in events if r[0] == "drain_join"]) == 1


@pytest.mark.parametrize("where", ["request_observer", "final_admission", "response_status", "response_integrity"])
def test_repair_stage_request_dispatch_response_distinctions(where):
    http, events = HTTP(), []
    with adapter(http) as gen:
        def emit(kind, value):
            events.append((kind, value))
        def observe(kind, value):
            if value.get("path") == "/v1/chat/completions":
                if where == "request_observer" and kind == "http_request":
                    raise OSError("synthetic request observer")
                if where == "final_admission" and kind == "http_dispatch_admission":
                    http.clock.now = 150
        gen.observe = observe
        if where == "response_status":
            http.fail_at = "/v1/chat/completions"
        if where == "response_integrity":
            http.mutate = lambda response: response["__verbose"].update(truncated=True)
        report = p.diagnose(documents(), gen, active_deadline=1500, emit=emit, clock=http.clock)
    stage = report["arms"][0]
    assert stage["generation_status"] == "attempted_failed"
    assert stage["review_status"] == "not_started" and stage["review_attempted"] is False
    transport = stage["generation_transport"]
    assert transport["request_entries"] == 1
    assert transport["client_dispatches"] == int(where in ("response_status", "response_integrity"))
    assert transport["responses_received"] == transport["client_dispatches"]
    assert transport["validated_completion"] is False
    assert report["counts"]["generation_attempts"] == 1
    assert report["counts"]["generation"] == transport["client_dispatches"]
    assert report["counts"]["generation_responses"] == transport["responses_received"]
    assert report["counts"]["generation_validated"] == 0


def synthetic_registration(tmp_path):
    def write(name, data):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {"file": name, **p.digest(path)}
    plan = write(p.PLAN, (p.ROOT / p.PLAN).read_bytes())
    amendment = write(p.AMENDMENT, (p.ROOT / p.AMENDMENT).read_bytes())
    boundary_name = "docs/MEETINGS-SUMMARY-MODE-PROVENANCE-BOUNDARY.md"
    boundary = write(boundary_name, (p.ROOT / boundary_name).read_bytes())
    write("data/models/meetings-generation-qwen35-v1.json", p.MANIFEST.read_bytes())
    inputs = write("synthetic/input.json", p.encoded({"schema_version": 1,
        "diagnostic": p.ID, "documents": documents()}))
    receipt = write("synthetic/source-receipt.json", b'{"synthetic":true}')
    lock = write("synthetic/source-lock.json", b'{"synthetic":true}')
    code = [write(name, b"# synthetic never executed\n") for name in (
        "src/doctrail/synthetic.py", "scripts/probe_meeting_summary_mode.py", "pyproject.toml", "uv.lock",
        "tests/test_probe_meeting_summary_mode.py")]
    assets = [write("models/meetings-qwen35-v1/setup-receipt.json", b'{"synthetic":true}')]
    spec = {"schema_version": 1, "diagnostic": p.ID, "prepared": True, "limits": p.LIMITS,
        "input": inputs, "plan": plan, "amendment": amendment, "provenance_boundary": boundary,
        "code": code, "assets": assets,
        "source_receipt": receipt, "source_lock": lock, "order": p.order(documents()),
        "output_dir": ".local/synthetic-never-created/" + p.ID,
        "runtime": {"manifest_sha256": p.MANIFEST_SHA256, "model_sha256": p.GGUF_SHA256,
                    "commit": p.RUNTIME_COMMIT, "argv": p.normalized_argv(28)}}
    path = tmp_path / "synthetic-registration.json"
    path.write_bytes(p.encoded(spec))
    return path, spec


def test_repair_registration_requires_exact_original_and_amendment_without_execution(tmp_path):
    path, spec = synthetic_registration(tmp_path)
    actual, rows, output = p.verify_registration(path, p.sha(path.read_bytes()), tmp_path)
    assert actual["plan"] == spec["plan"] and actual["amendment"] == spec["amendment"]
    assert rows == documents() and not output.exists()
    assert actual["plan"]["size_bytes"] == 18650 and actual["amendment"]["size_bytes"] == 11215


@pytest.mark.parametrize("mutation", ["missing_amendment", "amendment_hash", "amendment_bytes",
    "amendment_file", "plan_hash", "plan_bytes", "plan_file", "original_mutated", "amendment_mutated"])
def test_repair_bad_design_binding_cannot_prepare_actual_run(tmp_path, mutation):
    path, spec = synthetic_registration(tmp_path)
    if mutation == "missing_amendment":
        del spec["amendment"]
    elif mutation.endswith("_mutated"):
        name = "plan" if mutation == "original_mutated" else "amendment"
        with (tmp_path / spec[name]["file"]).open("ab") as stream:
            stream.write(b"drift")
    else:
        name, field = mutation.split("_")
        key = {"hash": "sha256", "bytes": "size_bytes", "file": "file"}[field]
        spec[name][key] = {"hash": "0" * 64, "bytes": 1, "file": "other.md"}[field]
    path.write_bytes(p.encoded(spec))
    with pytest.raises(ValueError):
        p.verify_registration(path, p.sha(path.read_bytes()), tmp_path)
    assert not (tmp_path / ".local").exists()


@pytest.mark.parametrize("operational_error", [False, True])
def test_repair_cli_reports_same_bound_terminal_verdict_with_semantic_failure(tmp_path, monkeypatch, capsys, operational_error):
    http = HTTP()
    http.review_raw = REJECTED
    report, _ = run(http)
    report.update(bindings_unchanged=True, registration_sha256="a" * 64)
    if operational_error:
        p.record_failure(report, {"code": "summary_mode_cleanup"}, operational=True, stop=True)
    class Sink:
        def seal(self, value):
            pass

        def __call__(self, kind, value):
            pass
    result = p.finalize(report, Sink(), clock=http.clock, started=0, active_start=0)
    path = tmp_path / "never-opened-registration.json"
    def execute(actual_path, expected):
        assert actual_path == path and expected == "a" * 64
        return result
    monkeypatch.setattr(p, "execute", execute)
    monkeypatch.setattr(sys, "argv", ["probe", "--registration", str(path), "--execute-once-sha256", "a" * 64])
    assert p.main() == int(operational_error)
    terminal = json.loads(capsys.readouterr().out)
    assert terminal["operational_eligible"] is (not operational_error)
    assert terminal["registration_sha256"] == "a" * 64
    assert terminal["first_failure"]["kind"] == "semantic_review"
    assert terminal["terminal_observed_at"] == result["terminal_observed_at"]
    assert terminal["whole_seconds_after_final_writes"] == result["whole_seconds_after_final_writes"]
    assert terminal["active_seconds_after_final_writes"] == result["active_seconds_after_final_writes"]


def test_repair_late_invalidation_retains_original_cause_and_measures_write():
    clock, events = Clock(), []
    first = {"code": "generation_summary_review_rejected", "kind": "semantic_review"}
    class Sink:
        def seal(self, value):
            clock.now = 1625

        def __call__(self, kind, value):
            events.append((kind, value))
            clock.now += 0.1
    result = p.finalize(completed_report(first),
        Sink(), clock=clock, started=0, active_start=120, cleanup_seconds=5)
    assert result["eligible"] is False and result["first_failure"] == first
    assert result["whole_seconds_after_final_writes"] == result["terminal_observed_at"] == 1625.1
    assert result["active_seconds_after_final_writes"] == 1500.1
    assert [kind for kind, _ in events] == ["finalization-failure"]


def test_repair_resource_guard_binds_initial_launcher_creation_time():
    ps = FakePS()
    process = SimpleNamespace(pid=123, poll=lambda: None, kill=lambda: pytest.fail("must not kill"))
    with pytest.raises(ValueError, match="ownership"):
        p.ResourceGuard(process, ps=ps, expected_created=ps.created + 1)


def test_repair_diagnostic_evidence_failure_does_not_erase_earlier_rejection():
    http = HTTP()
    http.review_raw = REJECTED
    with adapter(http) as gen:
        def emit(kind, value):
            if kind == "diagnostic":
                raise OSError("synthetic final evidence failure")
        report = p.diagnose(documents(), gen, active_deadline=1500, emit=emit, clock=http.clock)
    assert report["first_failure"]["kind"] == "semantic_review"
    assert report["operational_failure"]["type"] == "OSError"
    assert report["status"] == "stopped" and len(http.completions) == 16


def test_repair_last_arm_guard_exit_still_invalidates_completion():
    http = HTTP()
    class Guard:
        count = 0

        @contextmanager
        def arm(self, deadline, metrics):
            self.count += 1
            yield
            metrics["joined"] = True
            if self.count == 8:
                http.clock.now = deadline + 0.01
    report, _ = run(http, guard=Guard())
    assert len(http.completions) == 16 and report["unexecuted"] == []
    assert report["status"] == "stopped"
    assert report["operational_failure"]["code"] == "summary_mode_deadline"
    assert report["arms"][-1]["elapsed_seconds"] > 180


def test_repair_no_drain_terminate_failure_retains_error_and_uses_same_handle(tmp_path):
    _, _, _, process, events, clock, cleanup = fake_owned_launch(tmp_path, stage="terminate_error")
    metrics = {"process_creation_attempted": True, "process_returned": True}
    cleanup(process, None, metrics, clock=clock)
    assert process.returncode == 0 and metrics["process_absence_confirmed"] is True
    assert [r[0] for r in events if r[0] in ("terminate", "kill")] == ["terminate", "kill"]
    assert metrics["within_budget"] is False and len(metrics["cleanup_failures"]) == 1
    assert metrics["owned_process_handle"] == "closed"


@pytest.mark.parametrize("stage", ["prepare", "popen", "create_time", "drain_constructor",
    "drain_start_before", "drain_start_after", "readiness", "guard", "adapter_constructor", "adapter_load"])
def test_repair_executor_startup_failures_keep_eight_arms_unexecuted(tmp_path, monkeypatch, stage):
    http = HTTP()
    launch, kwargs, _, process, events, _, _ = fake_owned_launch(tmp_path, stage=stage, clock=http.clock)
    registration = tmp_path / "synthetic-registration.json"
    registration.write_bytes(b"{}")
    reference = {"file": registration.name, **p.digest(registration)}
    spec = {key: reference for key in ("plan", "amendment", "provenance_boundary", "input", "source_receipt", "source_lock")}
    spec.update(code=[], assets=[], runtime={"argv": p.normalized_argv(28)})
    manifest = tmp_path / "data/models/meetings-generation-qwen35-v1.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(p.MANIFEST.read_bytes())
    monkeypatch.setattr(p, "verify_registration", lambda *args: (spec, documents(), tmp_path / "synthetic-evidence"))
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(
        virtual_memory=lambda: SimpleNamespace(available=10 * 1024**3)))
    monkeypatch.setattr(p, "owned_launcher", lambda **actual: launch(**{**kwargs, **actual}))
    def guard(*args, **kw):
        if stage == "guard":
            raise RuntimeError("synthetic guard")
        return SimpleNamespace(created=7.0, check=lambda: None)
    monkeypatch.setattr(p, "ResourceGuard", guard)
    original = p.ModeAdapter
    def factory(*args, **kw):
        if stage == "adapter_constructor":
            raise RuntimeError("synthetic adapter constructor")
        gen = original(*args, transport=httpx.MockTransport(http), **kw)
        def load():
            raise RuntimeError("synthetic adapter load")
        gen.load = load
        return gen
    monkeypatch.setattr(p, "ModeAdapter", factory)
    result = p.execute(registration, p.sha(registration.read_bytes()), root=tmp_path, clock=http.clock)
    assert result["eligible"] is False and len(result["unexecuted"]) == 8
    assert result["arms"] == [] and http.completions == [] and http.requests == []
    assert result["active_seconds_after_final_writes"] is None
    assert result["first_failure"]["type"] in ("RuntimeError", "OSError")
    if stage not in ("prepare", "popen"):
        assert result["cleanup"]["process_absence_confirmed"] is True
        assert process.returncode == 0 and process.stdout.closed
        assert any(row[0] == "terminate" for row in events)
    if stage == "popen":
        assert result["cleanup"]["process_absence_confirmed"] is None
        assert result["first_failure"]["type"] == "OSError"
        assert any(row["code"] == "summary_mode_cleanup" for row in result["failure_history"])


def test_repair_completion_flag_alone_is_not_operational_success():
    class Sink:
        def seal(self, report):
            pass

        def __call__(self, kind, value):
            pass
    result = p.finalize({"status": "completed", "first_failure": None, "bindings_unchanged": True},
        Sink(), clock=Clock(), started=0)
    assert result["eligible"] is False


@pytest.mark.parametrize("write_kind", ["final-report", "index"])
@pytest.mark.parametrize("earlier", [False, True])
@pytest.mark.parametrize("partial_write", [False, True])
def test_terminal_repair_seal_failure_preserves_bound_report(
        tmp_path, monkeypatch, capsys, write_kind, earlier, partial_write):
    clock = Clock()
    report = completed_report()
    report["registration_sha256"] = "a" * 64
    if earlier:
        p.record_failure(report, {"code": "semantic-first", "kind": "semantic_review"})
        p.record_failure(report, {"code": "operational-first"}, operational=True, stop=True)
    class Sink(p.Evidence):
        def __call__(self, kind, value):
            clock.now += 1
            if kind == write_kind and not partial_write:
                raise OSError("synthetic create " + kind)
            super().__call__(kind, value)
            if kind == write_kind:
                raise OSError("synthetic partial " + kind)
    sink = Sink(tmp_path)
    result = p.finalize(report, sink, clock=clock, started=0, active_start=0)
    assert result is report and result["registration_sha256"] == "a" * 64
    assert result["eligible"] is result["operational_eligible"] is False
    assert result["sealing_status"] == "failed" and result["evidence_sealed"] is False
    assert result["failure_history"][-1]["stage"] == "final_seal"
    if earlier:
        assert result["first_failure"]["code"] == "semantic-first"
        assert result["operational_failure"]["code"] == "operational-first"
    else:
        assert result["first_failure"] == result["operational_failure"]
        assert result["first_failure"]["type"] == "OSError"
    assert result["terminal_observed_at"] == result["whole_seconds_after_final_writes"] == clock.now
    assert result["active_seconds_after_final_writes"] == clock.now
    assert len(list(tmp_path.glob("*.json"))) == int(partial_write) + int(write_kind == "index")
    assert clock.now == (1 if write_kind == "final-report" else 2)  # no retry/error write
    assert_bound_terminal_cli(result, monkeypatch, capsys)


def test_terminal_repair_late_invalidation_write_failure_keeps_deadline(tmp_path, monkeypatch, capsys):
    clock = Clock()
    report = completed_report({"code": "semantic-first", "kind": "semantic_review"})
    report["registration_sha256"] = "a" * 64
    class Sink(p.Evidence):
        def seal(self, value):
            super().seal(value)
            clock.now = 1625

        def __call__(self, kind, value):
            if kind == "finalization-failure":
                clock.now += 0.5
                raise OSError("synthetic invalidation write")
            super().__call__(kind, value)
    sink = Sink(tmp_path)
    result = p.finalize(report, sink, clock=clock, started=0, active_start=120, cleanup_seconds=5)
    assert result["first_failure"]["code"] == "semantic-first"
    assert result["operational_failure"]["code"] == "summary_mode_whole_deadline"
    assert result["failure_history"][-1]["stage"] == "final_invalidation"
    assert result["eligible"] is False and result["evidence_sealed"] is False
    assert result["sealing_status"] == "failed"
    assert result["terminal_observed_at"] == result["whole_seconds_after_final_writes"] == 1625.5
    assert result["active_seconds_after_final_writes"] == 1500.5
    assert sink.count == 2 and len(list(tmp_path.glob("*.json"))) == 2
    assert_bound_terminal_cli(result, monkeypatch, capsys)


def assert_bound_terminal_cli(report, monkeypatch, capsys):
    monkeypatch.setattr(p, "execute", lambda *a: report)
    monkeypatch.setattr(sys, "argv", ["probe", "--registration", "unused-synthetic.json",
                                     "--execute-once-sha256", "a" * 64])
    assert p.main() == 1
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["receipt_scope"] == "bound_terminal"
    for key in ("first_failure", "operational_failure", "failure_history", "registration_sha256",
                "terminal_observed_at", "whole_seconds_after_final_writes", "active_seconds_after_final_writes",
                "eligible", "sealing_status", "evidence_sealed"):
        assert receipt[key] == report[key]


@pytest.mark.parametrize("prior_failure", [None, "load", "body"])
def test_terminal_repair_first_close_failure_reaches_bound_cli(tmp_path, monkeypatch, capsys, prior_failure):
    clock = Clock()
    launch, kwargs, _, process, events, _, _ = fake_owned_launch(tmp_path, clock=clock)
    registration = tmp_path / "synthetic-registration.json"
    registration.write_bytes(b"{}")
    reference = {"file": registration.name, **p.digest(registration)}
    spec = {k: reference for k in ("plan", "amendment", "provenance_boundary", "input", "source_receipt", "source_lock")}
    spec.update(code=[], assets=[], runtime={"argv": p.normalized_argv(28)})
    manifest = tmp_path / "data/models/meetings-generation-qwen35-v1.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(p.MANIFEST.read_bytes())
    monkeypatch.setattr(p, "verify_registration", lambda *a: (spec, documents(), tmp_path / "synthetic-evidence"))
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(
        virtual_memory=lambda: SimpleNamespace(available=10 * 1024**3)))
    monkeypatch.setattr(p, "owned_launcher", lambda **actual: launch(**{**kwargs, **actual}))
    monkeypatch.setattr(p, "ResourceGuard", lambda *a, **kw: SimpleNamespace(created=7.0, check=lambda: None))
    close_calls = []
    class Adapter:
        def __init__(self, *a, **kw):
            self.counts = {"generation": 0, "review": 0}

        def begin_request(self, deadline):
            pass

        def load(self):
            if prior_failure == "load":
                raise RuntimeError("synthetic original load")

        def close(self):
            close_calls.append(clock.now)
            raise OSError("synthetic first close")
    monkeypatch.setattr(p, "ModeAdapter", Adapter)
    def diagnose(*a, **kw):
        if prior_failure == "body":
            raise RuntimeError("synthetic original body")
        return completed_report()
    monkeypatch.setattr(p, "diagnose", diagnose)
    execute = p.execute
    monkeypatch.setattr(p, "execute", lambda path, expected: execute(path, expected, root=tmp_path, clock=clock))
    expected = p.sha(registration.read_bytes())
    monkeypatch.setattr(sys, "argv", ["probe", "--registration", str(registration), "--execute-once-sha256", expected])
    assert p.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["registration_sha256"] == expected and result["eligible"] is False
    assert result["first_failure"]["type"] == ("RuntimeError" if prior_failure else "OSError")
    assert result["operational_failure"] == result["first_failure"]
    assert result["failure_history"][-1]["stage"] == "client_close"
    assert result["counts"] == {"generation": 0, "review": 0}
    assert result["bindings_unchanged"] is True
    assert len(close_calls) == 1 and result["retries"] == 0
    assert result["cleanup"]["within_budget"] is True and process.returncode == 0
    assert sum(row[0] == "terminate" for row in events) == 1
    assert result["terminal_observed_at"] == result["whole_seconds_after_final_writes"] == clock.now



def test_boundary_exact_reference_is_required_alongside_original_contracts(tmp_path):
    path, spec = synthetic_registration(tmp_path)
    actual, rows, output = p.verify_registration(path, p.sha(path.read_bytes()), tmp_path)
    assert actual["provenance_boundary"] == {
        "file": "docs/MEETINGS-SUMMARY-MODE-PROVENANCE-BOUNDARY.md", "size_bytes": 7014,
        "sha256": "ab191c4aa424d2ca16a874683feb3c88eb6064a89bcb47e9bae0e2fdfa9a11ac"}
    assert actual["plan"] == spec["plan"] and actual["amendment"] == spec["amendment"]
    assert rows == documents() and not output.exists()
    assert not (tmp_path / ".local").exists()


@pytest.mark.parametrize("mutation", ["missing", "file", "size_bytes", "sha256",
                                     "file_mutation", "file_missing"])
def test_boundary_invalid_registration_stops_before_any_launch_or_output(tmp_path, monkeypatch, mutation):
    path, spec = synthetic_registration(tmp_path)
    boundary = spec["provenance_boundary"]
    if mutation == "missing":
        del spec["provenance_boundary"]
    elif mutation == "file_mutation":
        target = tmp_path / boundary["file"]
        target.write_bytes(b"!" + target.read_bytes()[1:])  # same size, changed content
    elif mutation == "file_missing":
        (tmp_path / boundary["file"]).unlink()
    else:
        boundary[mutation] = {"file": "docs/other-boundary.md", "size_bytes": 7015,
                              "sha256": "0" * 64}[mutation]
    path.write_bytes(p.encoded(spec))
    calls = []
    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        pytest.fail("registration rejection must precede native/model setup")
    monkeypatch.setattr(p, "owned_launcher", forbidden)
    monkeypatch.setattr(p, "ModeAdapter", forbidden)
    before = {str(f.relative_to(tmp_path)): p.digest(f) for f in tmp_path.rglob("*") if f.is_file()}
    match = {"file_mutation": "summary_mode_binding_changed",
             "file_missing": "missing_or_linked_artifact"}.get(mutation, "summary_mode_registration_contract")
    with pytest.raises(ValueError, match=match):
        p.execute(path, p.sha(path.read_bytes()), root=tmp_path, clock=Clock())
    after = {str(f.relative_to(tmp_path)): p.digest(f) for f in tmp_path.rglob("*") if f.is_file()}
    assert before == after and calls == [] and not (tmp_path / ".local").exists()


@pytest.mark.parametrize("mutate_boundary", [False, True])
def test_boundary_post_custody_recheck_uses_real_registration_and_fake_runtime(tmp_path, monkeypatch, mutate_boundary):
    path, spec = synthetic_registration(tmp_path)
    http = HTTP()
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(
        virtual_memory=lambda: SimpleNamespace(available=10 * 1024**3)))
    monkeypatch.setitem(sys.modules, "scripts.probe_meeting_gpu_placement", SimpleNamespace(
        gpu_checkpoint=lambda **kwargs: {"query_stopped": True, "error": None, "uuid": "synthetic-gpu"}))
    # Only the synthetic output parent is prepared; execute still must create its once directory.
    (tmp_path / spec["output_dir"]).parent.mkdir(parents=True)
    @contextmanager
    def launcher(**kwargs):
        kwargs["telemetry"].update(process_creation_attempted=True, owned_create_time=123.0)
        try:
            yield SimpleNamespace(process=SimpleNamespace(pid=123), url="http://127.0.0.1:8123",
                                  token="x" * 40, manifest=tmp_path / p.MANIFEST.relative_to(p.ROOT))
        finally:
            kwargs["telemetry"].update(process_absence_confirmed=True, within_budget=True, seconds=0)
            if mutate_boundary:
                target = tmp_path / spec["provenance_boundary"]["file"]
                target.write_bytes(b"!" + target.read_bytes()[1:])
    monkeypatch.setattr(p, "owned_launcher", launcher)
    class Guard:
        def __init__(self, *args, **kwargs):
            self.created = 123.0

        def check(self):
            pass

        @contextmanager
        def arm(self, deadline, metrics):
            yield
    monkeypatch.setattr(p, "ResourceGuard", Guard)
    original = p.ModeAdapter
    def factory(*args, **kwargs):
        gen = original(*args, transport=httpx.MockTransport(http), **kwargs)
        gen.load = lambda: gen
        return gen
    monkeypatch.setattr(p, "ModeAdapter", factory)
    result = p.execute(path, p.sha(path.read_bytes()), root=tmp_path, clock=http.clock)
    assert len(http.completions) == 16 and result["product_writes"] == 0
    assert result["bindings_unchanged"] is (not mutate_boundary)
    assert result["eligible"] is (not mutate_boundary)
    assert result["operational_eligible"] is (not mutate_boundary)
    if mutate_boundary:
        assert result["operational_failure"]["code"] == "summary_mode_binding_changed"
    else:
        assert result["first_failure"] is None
