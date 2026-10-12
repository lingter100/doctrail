"""Real Java HTTP checks against a copy of a synthetic Python database.

Optional public-corpus replay compares every dev ranking with the frozen Python
baseline. This is migration parity, not a new model-quality or load benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx

from scripts.backup_db import copy_database
from scripts.benchmark_api import disposable_database_directory
from scripts.prepare_corpus import load_verified_corpus
from scripts.question_dataset import read_questions

ROOT = Path(__file__).resolve().parents[1]
COOKIE = "doctrail_session"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def java_executable() -> Path:
    # Windows javapath can spawn another JVM; waiting on that shim is insufficient.
    properties = subprocess.run(["java", "-XshowSettings:properties", "-version"],
                                capture_output=True, text=True, check=True)
    match = re.search(r"^\s*java.home = (.+)$", properties.stderr, re.MULTILINE)
    if not match:
        raise RuntimeError("java_home_not_reported")
    executable = Path(match.group(1).strip()) / "bin" / ("java.exe" if os.name == "nt" else "java")
    if not executable.is_file():
        raise RuntimeError("java_runtime_executable_missing")
    return executable


def expect(response: httpx.Response, status: int = 200):
    if response.status_code != status:
        # Never include request bodies, cookies or raw response text in diagnostics.
        raise AssertionError(f"HTTP status {response.status_code}, expected {status}")
    return response.json() if response.content else None


def seed_legacy(path: Path) -> dict:
    previous = os.environ.get("DOCTRAIL_DB")
    os.environ["DOCTRAIL_DB"] = str(path)
    try:
        from fastapi.testclient import TestClient

        from doctrail.app import create_app

        password = secrets.token_urlsafe(24)
        with TestClient(create_app(path)) as client:
            auth = expect(client.post("/api/auth/register", json={
                "email": "migration@example.invalid", "password": password,
                "name": "Synthetic migration check", "workspace_name": "Synthetic legacy",
            }), 201)
            workspace = auth["workspaces"][0]["id"]
            content = ("🚀 합성 문서 근거 migrationanchor e\u0301\r\n" * 55).encode()
            doc = expect(client.post(f"/api/workspaces/{workspace}/documents",
                                    files={"file": ("legacy.md", content)}), 201)
            return {"password": password, "workspace": workspace, "document": doc,
                    "cookie": client.cookies.get(COOKIE)}
    finally:
        if previous is None:
            os.environ.pop("DOCTRAIL_DB", None)
        else:
            os.environ["DOCTRAIL_DB"] = previous


@contextmanager
def java_server(jar: Path, database: Path, log: Path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = dict(os.environ, DOCTRAIL_DB=str(database), DOCTRAIL_SECURE_COOKIE="0")
    with log.open("ab") as output:
        process = subprocess.Popen(
            [str(java_executable()), "-jar", str(jar.resolve()), f"--server.port={port}"],
            cwd=ROOT, env=environment, stdout=output, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60,
                              trust_env=False) as client:
                deadline = time.monotonic() + 60
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("java_startup_exited")
                    try:
                        if client.get("/api/health").status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    if time.monotonic() > deadline:
                        raise TimeoutError("java_startup_timeout")
                    time.sleep(0.2)
                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def corpus_parity(client: httpx.Client) -> dict:
    workspace = expect(client.post("/api/workspaces", json={"name": "Public parity"}), 201)["id"]
    manifest = ROOT / "data/manifests/kubernetes-v1.json"
    questions = ROOT / "data/evaluation/m2-dev-v1.1.jsonl"
    corpus = load_verified_corpus(manifest)
    baseline_file = ROOT / "experiments/results/m2-bm25-dev-v1.1.json"
    baseline = json.loads(baseline_file.read_text(encoding="utf-8"))
    references = {row["id"]: row for row in baseline["questions"]}
    identities, chunk_ids, chunks = {}, {}, 0
    for row in corpus:
        doc = expect(client.post(f"/api/workspaces/{workspace}/documents",
                                 files={"file": (row["id"] + ".md", row["content"].encode())},
                                 data={"title": row["title"]}), 201)
        assert doc["status"] == "ready" and doc["content"] == row["content"]
        identities[doc["id"]] = row["id"]
        chunks += len(doc["chunks"])
        for chunk in doc["chunks"]:
            assert doc["content"][chunk["start_offset"]:chunk["end_offset"]] == chunk["text"]
            chunk_ids[chunk["id"]] = f"{row['id']}:{chunk['ordinal']}"
    assert len(corpus) == 313 and chunks == 3588
    checked = []
    for question in read_questions(questions):
        assert question["split"] == "dev", "test_questions_locked"
        result = expect(client.get(f"/api/workspaces/{workspace}/search",
                                   params={"q": question["query"]}))
        expected = references[question["id"]]["ranked_chunks"]
        actual = result["results"]
        assert len(actual) == len(expected), question["id"]
        for hit, old in zip(actual, expected, strict=True):
            assert identities[hit["document_id"]] == old["document_id"], question["id"]
            assert chunk_ids[hit["chunk_id"]] == old["chunk_id"], question["id"]
            for field in ("score", "page", "start_offset", "end_offset"):
                assert hit[field] == old[field], (question["id"], field)
        checked.append(question["id"])
    return {"documents": len(corpus), "chunks": chunks, "dev_questions": len(checked),
            "all_top10_ids_scores_offsets_equal": True, "checked_ids": checked,
            "manifest_sha256": digest(manifest), "questions_sha256": digest(questions),
            "python_baseline_sha256": digest(baseline_file), "test_evaluated": False}


def run(jar: Path, full_corpus: bool) -> dict:
    checks = []
    report = {"status": "running", "started_at": datetime.now(UTC).isoformat(),
              "scope": "Java loopback HTTP migration parity; synthetic accounts; not human review",
              "jar_sha256": digest(jar), "checks": checks,
              "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                     cwd=ROOT, text=True).strip(),
              "git_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"],
                                                         cwd=ROOT, text=True).strip())}
    files = [*ROOT.glob("server/src/**/*.java"), *ROOT.glob("server/src/main/resources/*"),
             ROOT / "server/pom.xml", Path(__file__).resolve()]
    report["source_sha256"] = {str(f.relative_to(ROOT)).replace("\\", "/"): digest(f)
                               for f in files if f.is_file()}
    with disposable_database_directory() as folder:
        legacy, copied, log = folder / "legacy.sqlite3", folder / "java.sqlite3", folder / "java.log"
        seeded = seed_legacy(legacy)
        copy_database(legacy, copied)
        original_hash = digest(legacy)
        with java_server(jar, copied, log) as client:
            expect(client.get("/api/auth/me"), 401)
            client.cookies.set(COOKIE, seeded["cookie"])
            expect(client.get("/api/auth/me"))
            workspace, doc = seeded["workspace"], seeded["document"]
            assert expect(client.get(f"/api/documents/{doc['id']}")) == doc
            checks.append("legacy_session_and_unchanged_stored_unicode_chunks")
            expect(client.post("/api/auth/logout"), 204)
            client.cookies.clear()
            expect(client.post("/api/auth/login", json={"email": "migration@example.invalid",
                                                         "password": seeded["password"]}))
            checks.append("legacy_scrypt_password_login")
            assert client.get("/").status_code == 200
            assert "DocTrail" in client.get("/").text
            checks.append("built_frontend_served_by_java")
            found = expect(client.get(f"/api/workspaces/{workspace}/search",
                                      params={"q": "migrationanchor"}))
            assert found["results"] and found["method"] == "bm25"
            expect(client.post(f"/api/searches/{found['search_id']}/feedback",
                               json={"document_id": doc["id"], "relevant": True}))
            updated = expect(client.put(f"/api/documents/{doc['id']}", json={
                "title": "Java revision", "content": "🚀 newjavaevidence 새 근거", "visibility": "private"}))
            assert updated["revision"] == doc["revision"] + 1
            with httpx.Client(base_url=client.base_url, timeout=30, trust_env=False) as member:
                expect(member.post("/api/auth/register", json={
                    "email": "member@example.invalid", "password": secrets.token_urlsafe(24),
                    "name": "Synthetic member", "workspace_name": "Isolated workspace",
                }), 201)
                expect(member.get(f"/api/workspaces/{workspace}/documents"), 404)
                expect(client.post(f"/api/workspaces/{workspace}/members",
                                   json={"email": "member@example.invalid"}), 201)
                expect(member.get(f"/api/documents/{doc['id']}"), 404)
                assert not expect(member.get(f"/api/workspaces/{workspace}/search",
                                             params={"q": "newjavaevidence"}))["results"]
                expect(member.delete(f"/api/documents/{doc['id']}"), 404)
            checks.append("cross_workspace_and_member_private_document_denial")
            assert not expect(client.get(f"/api/workspaces/{workspace}/search",
                                         params={"q": "migrationanchor"}))["results"]
            expect(client.post(f"/api/searches/{found['search_id']}/feedback",
                               json={"document_id": doc["id"], "relevant": False}), 409)
            checks.append("revision_replaces_chunks_and_rejects_stale_feedback")
            expect(client.post("/api/workspaces", json={"name": "blocked"},
                               headers={"Origin": "https://cross-site.invalid"}), 403)
            expect(client.post("/api/workspaces", json={"name": "unknown", "user_id": "fake"}), 422)
            expect(client.post("/api/workspaces", content=iter([b" " * 1048576] * 6),
                               headers={"Content-Type": "application/json"}), 413)
            boundary = "doctrailboundary"
            def multipart():
                yield (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                       "filename=\"large.txt\"\r\nContent-Type: text/plain\r\n\r\n").encode()
                yield from [b"x" * 1048576] * 6
                yield f"\r\n--{boundary}--\r\n".encode()
            expect(client.post(f"/api/workspaces/{workspace}/documents", content=multipart(),
                               headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}), 413)
            checks.append("same_origin_strict_json_and_chunked_size_limits")
            failed = expect(client.post(f"/api/workspaces/{workspace}/documents",
                                        files={"file": ("broken.pdf", b"SYNTHETIC_SECRET_PDF")}), 201)
            assert failed["status"] == "failed" and failed["error"] == "pdf_parse_failed"
            expect(client.post(f"/api/documents/{failed['id']}/reprocess"))
            checks.append("pdf_failure_status_and_reprocess")
            secret_query = "SYNTHETIC_SECRET_QUERY"
            expect(client.get(f"/api/workspaces/{workspace}/search", params={"q": secret_query}))
            with socket.create_connection(("127.0.0.1", client.base_url.port), timeout=5) as raw:
                raw.sendall(b"GET /api/search?q=SYNTHETIC_MALFORMED_SECRET[ HTTP/1.1\r\n"
                            b"Host: localhost\r\nConnection: close\r\n\r\n")
                assert b"400" in raw.recv(4096).split(b"\r\n")[0]
            expect(client.get("/api/auth/me", headers={
                "Cookie": "doctrail_session=SYNTHETIC_INVALID_COOKIE_SECRET,",
            }), 401)
            saved_cookie = client.cookies.get(COOKIE)
            if full_corpus:
                report["corpus_parity"] = corpus_parity(client)
        from fastapi.testclient import TestClient

        from doctrail.app import create_app

        with TestClient(create_app(copied)) as legacy_reader:
            legacy_reader.cookies.set(COOKIE, saved_cookie)
            assert expect(legacy_reader.get(f"/api/documents/{doc['id']}")) == updated
            assert expect(legacy_reader.get(f"/api/workspaces/{workspace}/history"))["items"]
        checks.append("python_reads_java_revision_session_and_history")
        with java_server(jar, copied, log) as client:
            client.cookies.set(COOKIE, saved_cookie)
            assert expect(client.get(f"/api/documents/{doc['id']}")) == updated
            assert expect(client.get(f"/api/workspaces/{workspace}/history"))["items"]
            assert expect(client.get(f"/api/workspaces/{workspace}/search",
                                     params={"q": "newjavaevidence"}))["results"]
            expect(client.delete(f"/api/documents/{doc['id']}"), 204)
            assert not expect(client.get(f"/api/workspaces/{workspace}/search",
                                         params={"q": "newjavaevidence"}))["results"]
            checks.append("restart_persistence_and_deleted_document_removal")
        assert digest(legacy) == original_hash
        checks.append("original_python_database_bytes_unchanged")
        log_text = log.read_text(encoding="utf-8", errors="replace")
        for secret in ("SYNTHETIC_SECRET_PDF", "SYNTHETIC_SECRET_QUERY", seeded["password"],
                       "SYNTHETIC_MALFORMED_SECRET", "SYNTHETIC_INVALID_COOKIE_SECRET",
                       "newjavaevidence", saved_cookie):
            assert secret not in log_text, "sensitive_content_in_java_log"
        checks.append("safe_java_operational_logs")
    report.update(status="passed", completed_at=datetime.now(UTC).isoformat(),
                  limitations=["No deployment, load, new model inference or human review.",
                               "PDFBox extraction is not asserted identical to pypdf."])
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jar", type=Path, default=ROOT / "server/target/doctrail-server-0.1.0.jar")
    parser.add_argument("--full-corpus", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("output_exists_choose_new_path")
    result = run(args.jar, args.full_corpus)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "checks": len(result["checks"]),
                      "full_corpus": args.full_corpus}))


if __name__ == "__main__":
    main()
