"""Fake-only representation/lifecycle checks; never load a model or tokenizer."""
import copy
import json
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest

from doctrail.generation_runtime import GenerationError
from scripts import measure_meeting_qa_representation as m
from tools.free_qa.policy import ContractError


def service():
    return SimpleNamespace(url="http://127.0.0.1:19876", token="x" * 48)


def adapter(handler, *, check=lambda: None, clock=lambda: 0):
    events = []
    return m.CountTransport(service(), check=check, clock=clock,
        emit=lambda *event: events.append(event), transport=httpx.MockTransport(handler)), events


def fixed_case():
    content = "원문 <TAG> 확인.\n담당자가 검토한다."
    title = "첫 자료"
    bundle = title + "\n" + content
    start = len(title) + 1
    data = {"id": "development-1", "title": "공개 자료", "question": "검토 내용은?",
            "bundle": bundle, "documents": [{"document_id": "doc-1", "revision": 1,
                "title": title, "content": content, "start_offset": start, "end_offset": len(bundle)}]}
    source_units = m.meeting_units(content)
    units = [{"id": i, "document_id": "doc-1", "revision": 1, **unit,
              "bundle_start_offset": start + unit["start_offset"],
              "bundle_end_offset": start + unit["end_offset"]} for i, unit in enumerate(source_units)]
    sidecar = {"bundle_sha256": m.sha(bundle.encode()), "documents": [{"document_id": "doc-1",
        "revision": 1, "title": title, "start_offset": start, "end_offset": len(bundle),
        "content_sha256": m.sha(content.encode())}], "units": units}
    reference = {"claims": [{"evidence": [0], "text": "원문 확인."}], "status": "answered"}
    return data, sidecar, reference


def test_literal_reference_order_unicode_and_no_newline():
    _, _, reference = fixed_case()
    raw = m.reference_wire(reference)
    assert raw == '{"status":"answered","claims":[{"text":"원문 확인.","evidence":[0]}]}'.encode()
    assert m.reference_wire({"claims": [], "status": "abstained"}) == b'{"status":"abstained","claims":[]}'
    assert not raw.endswith(b"\n")


@pytest.mark.parametrize("reference", [
    {"status": "abstained", "claims": [{"text": "x", "evidence": [0]}]},
    {"status": "answered", "claims": []},
    {"status": "answered", "claims": [{"text": "x", "evidence": [True]}]},
    {"status": "answered", "claims": [{"text": "x", "evidence_ids": [0]}]},
])
def test_reference_schema_rejects_mutations(reference):
    with pytest.raises(ContractError):
        m.reference_wire(reference)


def test_existing_wire_preserves_full_content_and_local_units():
    data, sidecar, reference = fixed_case()
    result = m.prepare_input(data, sidecar, reference)
    user = result["messages"][1]["content"]
    assert "\\u003cTAG\\u003e" in user
    payload = json.loads(user)
    parts = payload["source_parts"]
    assert "".join(part if isinstance(part, str) else part[1] for part in parts) == data["bundle"]
    assert [p[0] for p in parts if isinstance(p, list)] == list(range(len(sidecar["units"])))
    assert payload["question"] == data["question"]
    assert "source-parts" not in result["reference"]


def test_sidecar_mismatch_is_not_repaired():
    data, sidecar, reference = fixed_case()
    sidecar["units"][0]["bundle_end_offset"] -= 1
    with pytest.raises(ContractError, match="sidecar_mapping"):
        m.prepare_input(data, sidecar, reference)


@pytest.mark.parametrize("route", ["/completion", "/v1/chat/completions", "/chat/completions", "/tokenize", "/props?x=1"])
def test_no_forbidden_or_out_of_order_route_reaches_network(route):
    calls = []
    transport, _ = adapter(lambda request: calls.append(request))
    try:
        with pytest.raises(ContractError, match="token_count_only_route"):
            transport._request("POST", route, {}, 60)
        assert transport.sent == 0 and not calls and transport.halted
    finally:
        transport.close()


def test_full_sequence_keeps_oversize_inputs_and_reference(tmp_path, monkeypatch):
    calls = []
    def handler(request):
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body))
        if request.url.path == "/props":
            return httpx.Response(200, json={"marker": "props"})
        if request.url.path == "/apply-template":
            assert set(body) == {"messages"}
            return httpx.Response(200, json={"prompt": "<s> 고정 프롬프트"})
        assert body["add_special"] is False and body["parse_special"] is True and body["with_pieces"] is False
        return httpx.Response(200, json={"tokens": list(range(5000 if body["content"].startswith("<s>") else 300))})
    transport, events = adapter(handler)
    monkeypatch.setattr(m, "validate_props", lambda props, prepared: None)
    case = m.prepare_input(*fixed_case())
    cases = [case, {**copy.deepcopy(case), "id": "development-2"}]
    result = []
    try:
        m.measure(transport, cases, None, tmp_path, 60, result)
        assert [(method, path) for method, path, _ in calls] == list(m.SEQUENCE)
        assert transport.sent == 7 and len(events) == 14 and len(result) == 2
        assert all(row["input_excess"] == 904 and row["reference_content_excess"] == 44
                   and row["reference_plus_eog_excess"] == 45 for row in result)
        for row in result:
            for ref in row["files"]:
                raw = (tmp_path / ref["file"]).read_bytes()
                assert len(raw) == ref["size_bytes"] and m.sha(raw) == ref["sha256"]
        assert (tmp_path / "case-1.reference.json").read_bytes() == case["reference"].encode()
        with pytest.raises(ContractError):
            transport._request("GET", "/props", deadline=60)
        assert len(calls) == 7
    finally:
        transport.close()


@pytest.mark.parametrize("reply", [httpx.Response(302, headers={"location": "/completion"}),
                                    httpx.Response(500), httpx.Response(200, content=b"bad json"),
                                    httpx.Response(200, content=b"x" * (2 * 1024**2 + 1))])
def test_transport_errors_stop_without_retry(reply):
    calls = []
    def handler(request):
        calls.append(request)
        return reply
    transport, _ = adapter(handler)
    try:
        with pytest.raises(GenerationError):
            transport._request("GET", "/props", deadline=60)
        with pytest.raises(ContractError):
            transport._request("GET", "/props", deadline=60)
        assert len(calls) == transport.sent == 1 and transport.halted
    finally:
        transport.close()


@pytest.mark.parametrize("ids", [[], [True], [-1], [0.2], "1", None])
def test_token_ids_are_strict(ids):
    transport, _ = adapter(lambda _: httpx.Response(200, json={"tokens": ids}))
    transport.sent = 2
    try:
        with pytest.raises(ContractError, match="token_protocol"):
            transport.tokens("unchanged", 60)
    finally:
        transport.close()


def test_deadline_and_resource_failure_prevent_dispatch():
    for clock, check in [(lambda: 60, lambda: None), (lambda: 0, lambda: (_ for _ in ()).throw(ValueError("resources")))]:
        calls = []
        transport, _ = adapter(lambda req, calls=calls: calls.append(req), clock=clock, check=check)
        try:
            with pytest.raises(ValueError):
                transport._request("GET", "/props", deadline=60)
            assert not calls and transport.sent == 0
        finally:
            transport.close()


@pytest.mark.parametrize("fail", [None, "measure", "close", "cleanup", "startup", "combined"])
def test_lifecycle_always_cleans_and_reports_failures(tmp_path, monkeypatch, fail):
    descriptor = tmp_path / "descriptor.json"
    descriptor.write_bytes(m.wire({"id": m.BASELINE}))
    (tmp_path / ".local").mkdir()
    output = tmp_path / ".local/meeting-free-qa-representation-measurement-fake"
    monkeypatch.setattr(m, "load_inputs", lambda root: ([{}, {}], []))
    monkeypatch.setattr(m.r, "admit_model", lambda *a, **k: "admitted")
    monkeypatch.setattr(m.r, "check_prepared", lambda *a: None)
    calls = []
    @contextmanager
    def lease(path):
        yield
    monkeypatch.setattr(m.r, "worker_lease", lease)
    @contextmanager
    def launcher(prepared, deadline, metrics, **kwargs):
        assert deadline == 120
        metrics["owned_create_time"] = 1
        try:
            if fail == "startup":
                raise ValueError("startup")
            yield SimpleNamespace(process=None)
        finally:
            calls.append("cleanup")
            metrics.update(within_budget=fail != "cleanup", process_absence_confirmed=fail != "cleanup")
    class Guard:
        def check(self):
            pass
        @contextmanager
        def arm(self, deadline, metrics):
            assert deadline == 60
            try:
                yield
            finally:
                if fail == "combined":
                    raise ValueError("summary_mode_resources")
    class Adapter:
        sent = 7
        def __init__(self, *a, **k):
            pass
        def close(self):
            calls.append("close")
            if fail == "close":
                raise ValueError("close")
    def measure(*args):
        if fail == "combined":
            raise ContractError("measurement_primary")
        if fail == "measure":
            raise ValueError("measure")
    monkeypatch.setattr(m, "measure", measure)
    report = m.execute(descriptor, m.sha(descriptor.read_bytes()), output, root=tmp_path,
        clock=lambda: 0, launcher=launcher, preparer=lambda *a, **k: SimpleNamespace(policy=None),
        guard_factory=lambda *a, **k: Guard(), adapter_factory=Adapter)
    assert calls == (["cleanup"] if fail == "startup" else ["close", "cleanup"])
    assert report["status"] == ("completed" if fail is None else "stopped")
    assert report["completions"] == report["requested_generation_tokens"] == 0
    if fail == "combined":
        assert report["first_failure"] == m.r.safe_error(ContractError("measurement_primary"))
        assert report["secondary_failures"] == [m.r.safe_error(ValueError("summary_mode_resources"))]
    elif fail in ("measure", "close", "startup"):
        assert report["secondary_failures"] == []
    assert json.loads((output / "report.json").read_bytes())["status"] == report["status"]
    with pytest.raises(ContractError, match="fresh_output"):
        m.execute(descriptor, m.sha(descriptor.read_bytes()), output, root=tmp_path)
