import importlib
import logging
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from doctrail.app import COOKIE, create_app
from doctrail.db import connect
from doctrail.ingest import ExtractionError


def register(client, email="owner@example.test"):
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "test-passphrase-2026",
            "name": email.split("@")[0],
            "workspace_name": "Synthetic test workspace",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload(
    client,
    workspace,
    content="synthetic refund policy",
    visibility="workspace",
    filename="guide.md",
):
    response = client.post(
        f"/api/workspaces/{workspace}/documents",
        files={"file": (filename, content.encode(), "text/plain")},
        data={"visibility": visibility},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "test.sqlite3"
    application = create_app(path)
    owner = TestClient(application)
    account = register(owner)
    yield application, owner, account["workspaces"][0]["id"], path
    owner.close()


def test_auth_session_is_persistent_and_not_client_identity(setup):
    app, owner, workspace, path = setup
    cookie = owner.cookies.get(COOKIE)
    with TestClient(create_app(path)) as restarted:
        restarted.cookies.set(COOKIE, cookie)
        assert restarted.get("/api/auth/me").status_code == 200
    with TestClient(app) as anonymous:
        assert anonymous.get(f"/api/workspaces/{workspace}/documents").status_code == 401
        assert anonymous.get("/api/auth/me", headers={"X-User-ID": "owner"}).status_code == 401
        anonymous.cookies.set(COOKIE, "forged")
        assert anonymous.get("/api/auth/me").status_code == 401
    with connect(path) as db:
        saved = db.execute("SELECT password_hash FROM users").fetchone()[0]
        assert "test-passphrase" not in saved
        assert db.execute("SELECT token_hash FROM sessions").fetchone()[0] != cookie
    assert owner.post("/api/auth/logout").status_code == 204
    assert owner.get("/api/auth/me").status_code == 401
    with TestClient(app) as stale:
        stale.cookies.set(COOKIE, cookie)
        assert stale.get("/api/auth/me").status_code == 401


def test_login_cookie_validation_and_cross_origin(setup):
    _, client, _, _ = setup
    response = client.post(
        "/api/auth/login", json={"email": "owner@example.test", "password": "test-passphrase-2026"}
    )
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert (
        client.post("/api/auth/logout", headers={"Origin": "https://attacker.invalid"}).status_code
        == 403
    )
    assert client.get("/api/auth/me").status_code == 200
    invalid = client.post("/api/auth/login", json={"email": "invalid", "password": "secret-data"})
    assert invalid.status_code == 422
    assert "secret-data" not in invalid.text
    assert (
        client.post(
            "/api/auth/login", json={"email": "owner@example.test", "password": "wrong"}
        ).status_code
        == 401
    )


def test_permission_before_ranking_private_and_other_workspace(setup):
    application, owner, workspace, _ = setup
    shared = upload(owner, workspace, "refund policy public")
    private = upload(owner, workspace, "hiddenunique refund", "private")
    with TestClient(application) as member:
        account = register(member, "member@example.test")
        assert member.get(f"/api/workspaces/{workspace}/documents").status_code == 404
        assert (
            member.get(f"/api/workspaces/{workspace}/search", params={"q": "refund"}).status_code
            == 404
        )
        assert member.get(f"/api/documents/{shared['id']}").status_code == 404
        assert (
            owner.post(
                f"/api/workspaces/{workspace}/members", json={"email": account["user"]["email"]}
            ).status_code
            == 201
        )
        listing = member.get(f"/api/workspaces/{workspace}/documents").json()["items"]
        assert [row["id"] for row in listing] == [shared["id"]]
        assert member.get(f"/api/documents/{private['id']}").status_code == 404
        assert member.delete(f"/api/documents/{shared['id']}").status_code == 403
        assert member.post(f"/api/documents/{private['id']}/reprocess").status_code == 404
        assert (
            member.post(
                f"/api/workspaces/{workspace}/members", json={"email": "owner@example.test"}
            ).status_code
            == 403
        )
        before = member.get(f"/api/workspaces/{workspace}/search", params={"q": "refund"}).json()
        assert len(before["results"]) == 1
        # Adding hidden text must not alter IDF or scores, even if it matches the query.
        upload(owner, workspace, "refund " * 300, "private")
        after = member.get(f"/api/workspaces/{workspace}/search", params={"q": "refund"}).json()
        assert before["results"] == after["results"]
        assert (
            member.get(f"/api/workspaces/{workspace}/search", params={"q": "hiddenunique"}).json()[
                "results"
            ]
            == []
        )


def test_revision_update_reprocess_delete_invalidate_chunks(setup):
    _, client, workspace, path = setup
    document = upload(client, workspace, "originalword evidence 😀\r\n" * 100)
    original_ids = {chunk["id"] for chunk in document["chunks"]}
    assert document["status"] == "ready"
    assert all(
        document["content"][c["start_offset"] : c["end_offset"]] == c["text"]
        for c in document["chunks"]
    )
    edited = client.put(
        f"/api/documents/{document['id']}",
        json={
            "title": "edited",
            "content": "replacementword newest source",
            "visibility": "private",
        },
    ).json()
    assert edited["revision"] == 2
    assert original_ids.isdisjoint(c["id"] for c in edited["chunks"])
    assert (
        client.get(f"/api/workspaces/{workspace}/search", params={"q": "originalword"}).json()[
            "results"
        ]
        == []
    )
    retried = client.post(f"/api/documents/{document['id']}/reprocess").json()
    assert retried["revision"] == 3
    assert retried["content"] == edited["content"]
    assert retried["chunk_count"] == edited["chunk_count"]
    assert client.delete(f"/api/documents/{document['id']}").status_code == 204
    assert client.get(f"/api/documents/{document['id']}").status_code == 404
    assert (
        client.get(f"/api/workspaces/{workspace}/search", params={"q": "replacementword"}).json()[
            "results"
        ]
        == []
    )
    with connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0


def test_failed_upload_retry_repair_and_text_html_remains_text(setup):
    _, client, workspace, _ = setup
    failed = upload(client, workspace, "broken pdf", filename="broken.pdf")
    assert failed["status"] == "failed" and failed["error"] == "pdf_parse_failed"
    assert failed["chunks"] == []
    retry = client.post(f"/api/documents/{failed['id']}/reprocess").json()
    assert retry["status"] == "failed" and retry["chunks"] == []
    unsafe = '<script>alert("unsafe")</script> safe searchable'
    repaired = client.put(
        f"/api/documents/{failed['id']}",
        json={"title": "repaired", "content": unsafe, "visibility": "workspace"},
    )
    assert repaired.status_code == 200
    assert repaired.json()["content"] == unsafe
    assert repaired.headers["content-type"].startswith("application/json")
    assert client.post(f"/api/documents/{failed['id']}/reprocess").json()["content"] == unsafe


def test_transaction_rollback_retains_revision_and_chunks(setup, monkeypatch):
    _, client, workspace, _ = setup
    doc = upload(client, workspace, "oldcorrect evidence")
    module = importlib.import_module("doctrail.app")

    def fail_chunking(*_args):
        raise RuntimeError("synthetic injected failure")

    monkeypatch.setattr(module, "chunk_content", fail_chunking)
    response = client.put(
        f"/api/documents/{doc['id']}",
        json={"title": "new", "content": "newincorrect", "visibility": "workspace"},
    )
    assert response.status_code == 500
    assert response.json()["detail"] == "internal_error"
    actual = client.get(f"/api/documents/{doc['id']}").json()
    assert actual == doc


def test_ready_reprocess_failure_preserves_good_revision(setup, monkeypatch):
    _, client, workspace, _ = setup
    doc = upload(client, workspace)
    module = importlib.import_module("doctrail.app")

    def fail_extract(*_args):
        raise ExtractionError("pdf_parse_failed")

    monkeypatch.setattr(module, "extract", fail_extract)
    assert client.post(f"/api/documents/{doc['id']}/reprocess").status_code == 422
    assert client.get(f"/api/documents/{doc['id']}").json() == doc


def test_history_feedback_current_acl_and_revision(setup):
    application, owner, workspace, _ = setup
    doc = upload(owner, workspace)
    other = upload(owner, workspace, "shipping unrelated")
    with TestClient(application) as member:
        register(member, "member@example.test")
        owner.post(f"/api/workspaces/{workspace}/members", json={"email": "member@example.test"})
        search = member.get(f"/api/workspaces/{workspace}/search", params={"q": "refund"}).json()
        feedback_url = f"/api/searches/{search['search_id']}/feedback"
        assert (
            owner.post(feedback_url, json={"document_id": doc["id"], "relevant": True}).status_code
            == 404
        )
        assert (
            member.post(
                feedback_url, json={"document_id": other["id"], "relevant": True}
            ).status_code
            == 422
        )
        assert (
            member.post(feedback_url, json={"document_id": doc["id"], "relevant": True}).status_code
            == 200
        )
        assert owner.get(f"/api/workspaces/{workspace}/history").json()["items"] == []
        assert (
            member.get(f"/api/workspaces/{workspace}/history").json()["items"][0]["result_count"]
            == 1
        )
        owner.put(
            f"/api/documents/{doc['id']}",
            json={"title": "private", "content": "refund new", "visibility": "private"},
        )
        assert (
            member.post(
                feedback_url, json={"document_id": doc["id"], "relevant": False}
            ).status_code
            == 404
        )
        assert (
            member.get(f"/api/workspaces/{workspace}/history").json()["items"][0]["result_count"]
            == 0
        )
        owner.put(
            f"/api/documents/{doc['id']}",
            json={"title": "shared", "content": "refund newer", "visibility": "workspace"},
        )
        assert (
            member.post(
                feedback_url, json={"document_id": doc["id"], "relevant": False}
            ).status_code
            == 409
        )


def test_logs_omit_queries_content_and_passwords(setup, caplog):
    assert logging.getLogger("doctrail.requests").isEnabledFor(logging.INFO)
    _, client, workspace, _ = setup
    with caplog.at_level(logging.INFO, logger="doctrail.requests"):
        upload(client, workspace, "SECRET_DOCUMENT_PAYLOAD")
        response = client.get(
            f"/api/workspaces/{workspace}/search", params={"q": "SECRET_QUERY_PAYLOAD"}
        )
    assert response.headers["x-request-id"]
    assert "SECRET_DOCUMENT_PAYLOAD" not in caplog.text
    assert "SECRET_QUERY_PAYLOAD" not in caplog.text
    assert "route=/api/workspaces/{workspace_id}/search" in caplog.text
    assert "status=200" in caplog.text


def test_api_404_limits_health_and_schema(setup):
    _, client, workspace, path = setup
    assert client.get("/api/missing").status_code == 404
    assert client.get("/api/health").json() == {"status": "ok", "version": "0.1.0"}
    assert client.get(f"/api/workspaces/{workspace}/search", params={"q": " "}).status_code == 422
    assert (
        client.get(
            f"/api/workspaces/{workspace}/search", params={"q": "word", "limit": 1000}
        ).status_code
        == 422
    )
    response = client.post(
        f"/api/workspaces/{workspace}/documents",
        files={"file": ("large.txt", b"x" * (5 * 1024 * 1024 + 1))},
    )
    assert response.status_code == 413
    assert client.get(f"/api/workspaces/{workspace}/documents").json()["items"] == []
    with connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_auth_rate_limit_is_per_process(setup):
    _, client, _, _ = setup
    for _ in range(19):
        assert (
            client.post(
                "/api/auth/login", json={"email": "none@example.test", "password": "bad"}
            ).status_code
            == 401
        )
    response = client.post(
        "/api/auth/login", json={"email": "none@example.test", "password": "bad"}
    )
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"


def test_membership_revocation_denies_history_and_feedback(setup):
    application, owner, workspace, path = setup
    doc = upload(owner, workspace)
    with TestClient(application) as member:
        account = register(member, "revoked@example.test")
        owner.post(f"/api/workspaces/{workspace}/members", json={"email": account["user"]["email"]})
        search = member.get(f"/api/workspaces/{workspace}/search", params={"q": "refund"}).json()
        assert (
            member.put(
                f"/api/documents/{doc['id']}",
                json={"title": "bad", "content": "bad", "visibility": "workspace"},
            ).status_code
            == 403
        )
        with connect(path) as db:
            db.execute(
                "DELETE FROM memberships WHERE user_id=? AND workspace_id=?",
                (account["user"]["id"], workspace),
            )
        assert member.get(f"/api/workspaces/{workspace}/history").status_code == 404
        assert member.get(f"/api/documents/{doc['id']}").status_code == 404
        assert (
            member.post(
                f"/api/searches/{search['search_id']}/feedback",
                json={"document_id": doc["id"], "relevant": True},
            ).status_code
            == 404
        )


def test_streamed_request_limit_without_content_length(setup):
    _, client, _, _ = setup

    def body():
        for _ in range(6):
            yield b" " * (1024 * 1024)

    response = client.post(
        "/api/workspaces", content=body(), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json()["detail"] == "request_too_large"


def test_expired_sessions_and_secure_cookie(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCTRAIL_SECURE_COOKIE", "1")
    path = tmp_path / "secure.sqlite3"
    with TestClient(create_app(path), base_url="https://testserver") as client:
        register(client)
        assert client.get("/api/auth/me").status_code == 200
        response = client.post(
            "/api/auth/login",
            json={"email": "owner@example.test", "password": "test-passphrase-2026"},
        )
        assert "; Secure" in response.headers["set-cookie"]
        with connect(path) as db:
            db.execute("UPDATE sessions SET expires_at=0")
        assert client.get("/api/auth/me").status_code == 401


def test_concurrent_searches_use_separate_connections(setup):
    application, owner, workspace, _ = setup
    upload(owner, workspace)
    cookie = owner.cookies.get(COOKIE)

    def search_once(_index):
        with TestClient(application) as client:
            client.cookies.set(COOKIE, cookie)
            return client.get(f"/api/workspaces/{workspace}/search", params={"q": "refund"})

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(search_once, range(8)))
    assert all(response.status_code == 200 for response in responses)
    assert all(len(response.json()["results"]) == 1 for response in responses)
