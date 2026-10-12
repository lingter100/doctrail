import sqlite3

import pytest
from fastapi.testclient import TestClient

from doctrail.app import create_app
from scripts.backup_db import copy_database


def test_restore_preserves_documents_and_revokes_existing_sessions(tmp_path):
    source = tmp_path / "source.sqlite3"
    with TestClient(create_app(source)) as client:
        auth = client.post(
            "/api/auth/register",
            json={
                "email": "backup@example.invalid",
                "password": "test-password-only",
                "name": "Backup QA",
                "workspace_name": "QA",
            },
        ).json()
        workspace = auth["workspaces"][0]["id"]
        doc = client.post(
            f"/api/workspaces/{workspace}/documents",
            files={"file": ("runbook.txt", b"Recovery evidence.", "text/plain")},
        ).json()
        backup = tmp_path / "backup.sqlite3"
        copy_database(source, backup)
        restored = tmp_path / "restored.sqlite3"
        copy_database(backup, restored, restore=True)
        with TestClient(create_app(restored)) as recovery:
            recovery.cookies.update(client.cookies)
            assert recovery.get(f"/api/documents/{doc['id']}").status_code == 401
            assert (
                recovery.post(
                    "/api/auth/login",
                    json={"email": "backup@example.invalid", "password": "test-password-only"},
                ).status_code
                == 200
            )
            assert (
                recovery.get(f"/api/documents/{doc['id']}").json()["content"]
                == "Recovery evidence."
            )
        with sqlite3.connect(restored) as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        with pytest.raises(ValueError, match="new database"):
            copy_database(source, backup)
