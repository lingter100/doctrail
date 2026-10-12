"""SQLite schema v1. Each mutation uses a single database transaction."""

import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE users (
 id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 password_hash TEXT NOT NULL
);
CREATE TABLE workspaces (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE memberships (
 workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 role TEXT NOT NULL CHECK(role IN ('owner','member')),
 PRIMARY KEY(workspace_id,user_id)
);
CREATE TABLE sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires_at REAL NOT NULL
);
CREATE TABLE documents (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 title TEXT NOT NULL, filename TEXT NOT NULL, media_type TEXT NOT NULL,
 visibility TEXT NOT NULL CHECK(visibility IN ('workspace','private')),
 owner_id TEXT NOT NULL REFERENCES users(id), status TEXT NOT NULL,
 error TEXT, revision INTEGER NOT NULL, content TEXT NOT NULL,
 source BLOB NOT NULL, source_kind TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE chunks (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 text TEXT NOT NULL, page INTEGER, start_offset INTEGER NOT NULL,
 end_offset INTEGER NOT NULL, ordinal INTEGER NOT NULL,
 UNIQUE(document_id,ordinal)
);
CREATE TABLE searches (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 query TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE search_results (
 search_id TEXT NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
 document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 chunk_id TEXT NOT NULL, revision INTEGER NOT NULL,
 PRIMARY KEY(search_id,chunk_id)
);
CREATE TABLE feedback (
 search_id TEXT NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
 document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 relevant INTEGER NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(search_id,document_id)
);
CREATE INDEX ix_documents_workspace ON documents(workspace_id);
CREATE INDEX ix_chunks_document ON chunks(document_id);
CREATE INDEX ix_searches_user_workspace ON searches(user_id,workspace_id);
PRAGMA user_version=1;
"""


def connect(path: str | Path) -> sqlite3.Connection:
    # FastAPI may move one request's sequential dependency/endpoint work between pool threads.
    # Each request owns its connection; it is never concurrently shared between requests.
    connection = sqlite3.connect(str(path), timeout=10, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def initialize(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            connection.executescript("BEGIN IMMEDIATE;" + SCHEMA + "COMMIT;")
        elif version != 1:
            raise RuntimeError("unsupported_database_schema_version")
        connection.execute("PRAGMA journal_mode=WAL")
