"""Synthetic lifecycle and exact-evidence checks; never learned model quality."""
import copy
import hashlib
import json
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from scripts import run_meeting_qa_retrieval_development as m


def inputs():
    docs = [{"document_id": f"source-{n}", "title": f"Public {n}", "path": f"source-{n}.md",
        "content": f"Public source {n}.\nEvidence {n}.".encode(), "raw_sha256": str(n) * 64,
        "immutable_url": f"https://example.invalid/source/{n}"} for n in range(3)]
    cases = [{"id": "one", "question": "fixed one"}, {"id": "two", "question": "fixed two"}]
    return docs, cases


def uploaded(docs):
    return [{"source_id": source["document_id"], "java": {"id": f"document-{n}", "revision": 1,
        "status": "ready", "title": source["title"], "content": source["content"].decode(),
        "chunks": [{"id": f"chunk-{n}", "page": None, "ordinal": 0,
                    "start_offset": 0, "end_offset": len(source["content"].decode()),
                    "text": source["content"].decode()}]}} for n, source in enumerate(docs)]


def report(cases):
    return m.FailureRecord({"first_failure": None, "secondary_failures": [], "documents": [],
                           "searches": m.plan(cases), "search_attempts": 0})


class Service:
    def __init__(self, docs, *, fail_search=None, stale_search=None):
        self.docs = uploaded(docs)
        self.chunks = m.current_chunks(docs, self.docs)
        self.paths, self.requests = [], []
        self.uploads = self.searches = 0
        self.fail_search, self.stale_search = fail_search, stale_search

    def __call__(self, req):
        self.paths.append(req.url.path)
        if req.url.path.endswith("/register"):
            return httpx.Response(201, json={"workspaces": [{"id": "fresh"}]})
        if req.url.path.endswith("/documents"):
            result = self.docs[self.uploads]["java"]
            self.uploads += 1
            return httpx.Response(201, json=result)
        assert req.url.path == "/api/knowledge/search"
        payload = json.loads(req.content)
        self.requests.append(payload)
        self.searches += 1
        if self.fail_search == self.searches:
            raise httpx.ReadTimeout("SECRET transport details", request=req)
        hits = []
        for n, score in ((2, 2.0), (0, 1.0)):
            row = self.chunks[f"chunk-{n}"]
            hit = {k: row[k] for k in ("document_id", "revision", "title", "chunk_id", "page",
                                       "start_offset", "end_offset", "text")}
            hits.append({**hit, "score": score, "document_kind": "document", "meeting_date": None})
        if self.stale_search == self.searches:
            hits[0]["revision"] += 1
        return httpx.Response(200, json={"query": payload["query"], "method": payload["method"],
            "results": hits, "embedding_profile": {"id": "base"}})


def test_six_serial_searches_preserve_current_full_chunk_evidence_and_order():
    docs, cases = inputs()
    fake, result = Service(docs), report(cases)
    with httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(fake)) as client:
        m.operations(client, docs, cases, result, time.monotonic() + 20)
    assert [(r["query"], r["method"]) for r in fake.requests] == [
        (case["question"], method) for case in cases for method in m.METHODS]
    assert fake.paths == ["/api/auth/register"] + ["/api/workspaces/fresh/documents"] * 3 + [
        "/api/knowledge/search"] * 6
    assert all(r["limit"] == 10 and r["expected_embedding_profile"] == "base" for r in fake.requests)
    assert result["search_attempts"] == 6 and result["uploaded_chunks"] == 3
    for row in result["searches"]:
        assert row["status"] == "completed"
        evidence = row["ranked_evidence"]
        assert [hit["source_id"] for hit in evidence] == ["source-2", "source-0"]
        assert [hit["rank"] for hit in evidence] == [1, 2]
        assert [hit["score"] for hit in evidence] == [2.0, 1.0]
        for hit in evidence:
            assert hit["text"] == docs[hit["ordinal"] if hit["source_id"] == "source-0" else 2]["content"].decode()
            assert hit["end_offset"] - hit["start_offset"] == len(hit["text"])


@pytest.mark.parametrize("failure", ["timeout", "stale"])
def test_failed_search_aborts_remaining_methods_and_cases(failure):
    docs, cases = inputs()
    fake = Service(docs, fail_search=2 if failure == "timeout" else None,
                   stale_search=2 if failure == "stale" else None)
    result = report(cases)
    with (httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(fake)) as client,
          pytest.raises((httpx.ReadTimeout, ValueError))):
        m.operations(client, docs, cases, result, time.monotonic() + 20)
    assert fake.searches == result["search_attempts"] == 2
    assert [r["status"] for r in result["searches"]] == ["completed", "failed"] + ["unattempted"] * 4
    assert result["searches"][1]["first_failure"] is not None
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize("change", ["content", "offset", "duplicate", "kind", "score", "profile"])
def test_retrieval_cannot_substitute_stale_or_changed_evidence(change):
    docs, _ = inputs()
    chunks = m.current_chunks(docs, uploaded(docs))
    payload = {"query": "fixed", "method": "dense"}
    fake = Service(docs)
    body = fake(httpx.Request("POST", "http://127.0.0.1/api/knowledge/search",
                              json=payload)).json()
    if change == "content":
        body["results"][0]["text"] = "changed"
    elif change == "offset":
        body["results"][0]["start_offset"] += 1
    elif change == "duplicate":
        body["results"].append(copy.deepcopy(body["results"][0]))
    elif change == "kind":
        body["results"][0]["document_kind"] = "meeting"
    elif change == "score":
        body["results"][0]["score"] = float("nan")
    else:
        body["embedding_profile"]["id"] = "other"
    with pytest.raises(ValueError):
        m.ranked_evidence(body, payload, chunks)


def test_generation_disabled_and_cpu_threads_are_explicit_child_settings(monkeypatch):
    for key in ("DOCTRAIL_GENERATION_URL", "DOCTRAIL_GENERATION_TOKEN", "DOCTRAIL_INFERENCE_URL",
                "DOCTRAIL_EMBEDDING_PROFILE", "LLAMA_ARG_MODEL", "LLAMA_API_KEY"):
        monkeypatch.setenv(key, "SECRET inherited")
    before = dict(m.os.environ)
    env = m.environment(Path("fresh.sqlite3"), "http://127.0.0.1:1234", "fresh-token")
    assert env["DOCTRAIL_GENERATION_URL"] == env["DOCTRAIL_GENERATION_TOKEN"] == ""
    assert env["DOCTRAIL_EMBEDDING_PROFILE"] == "base"
    assert env["CUDA_VISIBLE_DEVICES"] == ""
    assert all(env[key] == "2" for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"))
    assert "LLAMA_API_KEY" not in env and "LLAMA_ARG_MODEL" not in env
    assert m.os.environ == before
    assert "set_num_threads(2)" in m.WORKER_BOOTSTRAP and "set_num_interop_threads(2)" in m.WORKER_BOOTSTRAP


def fake_health():
    specs = m.load_model_manifest(m.MANIFEST)["models"]
    return {"status": "ready", "embedding": {"model": specs["e5"]["repo_id"],
        "revision": specs["e5"]["revision"], "dimension": 384, "max_length": 512},
        "reranker": {"model": specs["reranker"]["repo_id"], "revision": specs["reranker"]["revision"],
                     "max_length": 512},
        "runtime": {"device": "cpu", "embedding_dtype": "torch.float32", "reranker_dtype": "torch.float32"}}


@pytest.mark.parametrize("bad_health", [False, True])
def test_owned_lifecycle_and_model_identity_failure_cleanup(monkeypatch, bad_health):
    children, waits = [], []
    class Child:
        stopped = False
        def __init__(self, argv, **kwargs):
            self.pid, self.argv, self.kwargs = 100 + len(children), argv, kwargs
            children.append(self)
        def poll(self):
            return 0 if self.stopped else None
        def terminate(self):
            self.stopped = True
        def kill(self):
            self.stopped = True
        def wait(self, timeout):
            return 0
    def ready(process, url, **kwargs):
        waits.append(kwargs["timeout"])
        if url.endswith("/api/health"):
            return {"status": "ok", "version": "0.1.0"}
        health = fake_health()
        if bad_health:
            health["embedding"]["revision"] = "wrong"
        return health
    ports = iter([12341, 12342])
    monkeypatch.setattr(m, "unused_port", lambda: next(ports))
    monkeypatch.setattr(m, "java_executable", lambda: Path("fake-java.exe"))
    monkeypatch.setattr(m, "wait_ready", ready)
    monkeypatch.setattr(m.subprocess, "Popen", Child)
    result = report(inputs()[1])
    with pytest.raises(Exception) as raised, m.start_services(Path("fake.jar"), Path("fresh-output"),
                                               result, time.monotonic() + 240):
        raise RuntimeError("SECRET body failure")
    assert result.errors[0] is raised.value
    assert len(children) == (1 if bad_health else 2) and all(c.stopped for c in children)
    assert all(0 < timeout <= 240 for timeout in waits)
    assert result["cleanup"]["owned_children_absent"] is True
    assert children[0].argv[1:4] == ["-B", "-c", m.WORKER_BOOTSTRAP]
    assert children[0].kwargs["stdout"] == subprocess.DEVNULL
    assert "SECRET" not in json.dumps(result)
    if not bad_health:
        assert "--doctrail.generation-url=" in children[1].argv


def test_startup_failure_still_reports_all_six_unattempted(tmp_path, monkeypatch):
    docs, cases = inputs()
    monkeypatch.setattr(m, "load_bundle", lambda bundle: (docs, cases))
    jar = tmp_path / "synthetic.jar"
    jar.write_bytes(b"synthetic jar, never executed")
    @contextmanager
    def fail(*args):
        raise TimeoutError("SECRET")
        yield
    result = m.execute(jar, hashlib.sha256(jar.read_bytes()).hexdigest(), tmp_path / "output", launcher=fail)
    assert result["status"] == "stopped" and result["search_attempts"] == 0
    assert len(result["unattempted"]) == 6
    saved = json.loads((tmp_path / "output/result.json").read_text(encoding="utf-8"))
    assert saved == result and "SECRET" not in json.dumps(saved)


def test_expired_operations_budget_issues_no_http_request():
    docs, cases = inputs()
    fake = Service(docs)
    with (httpx.Client(base_url="http://127.0.0.1", transport=httpx.MockTransport(fake)) as client,
          pytest.raises(TimeoutError)):
        m.operations(client, docs, cases, report(cases), time.monotonic() - 1)
    assert fake.paths == []
