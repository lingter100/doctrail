"""Same-origin FastAPI service. No inference model or generated answers."""
# ruff: noqa: B008 -- FastAPI evaluates dependency/field declarations at registration.

import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .db import connect, initialize
from .ingest import MAX_CONTENT_CHARS, MAX_FILE_BYTES, ExtractionError, extract
from .retrieval import chunk_content, rank_chunks

logger = logging.getLogger("doctrail.requests")
logger.setLevel(logging.INFO)
if not logger.handlers:
    request_handler = logging.StreamHandler()
    request_handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s"))
    logger.addHandler(request_handler)
# Parser diagnostics can contain source excerpts; expose only our safe extraction codes.
logging.getLogger("pypdf").disabled = True
logging.getLogger("pypdf").handlers = [logging.NullHandler()]
logging.getLogger("pypdf").propagate = False
# Uvicorn's default access records include the search query string.
logging.getLogger("uvicorn.access").disabled = True
COOKIE = "doctrail_session"
SESSION_TTL = 60 * 60 * 24 * 7


def uid() -> str:
    return uuid4().hex


def now() -> str:
    return datetime.now(UTC).isoformat()


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return salt + ":" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    return hmac.compare_digest(password_hash(password, stored.split(":")[0]), stored)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Model):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def email_valid(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or any(char.isspace() for char in value):
            raise ValueError("invalid_email")
        return value


class Register(Login):
    password: str = Field(min_length=10, max_length=1024)
    name: str = Field(min_length=1, max_length=100)
    workspace_name: str = Field(min_length=1, max_length=100)


class WorkspaceInput(Model):
    name: str = Field(min_length=1, max_length=100)


class MemberInput(Model):
    email: str = Field(min_length=3, max_length=254)


class EditInput(Model):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    visibility: Literal["workspace", "private"]


class FeedbackInput(Model):
    document_id: str
    relevant: bool


def create_app(db_path: str | Path | None = None) -> FastAPI:
    path = Path(db_path or os.getenv("DOCTRAIL_DB", "var/doctrail.sqlite3"))
    initialize(path)
    app = FastAPI(title="DocTrail", version="0.1.0")
    app.state.db_path = path
    attempts: dict[str, deque] = defaultdict(deque)
    attempt_lock = threading.Lock()
    dummy_password = password_hash(secrets.token_hex(32))

    def database():
        connection = connect(path)
        try:
            yield connection
        finally:
            connection.close()

    def user(request: Request, db=Depends(database)):
        token = request.cookies.get(COOKIE, "")
        record = db.execute(
            "SELECT u.id,u.email,u.name FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token_hash=? AND s.expires_at>?",
            (hashlib.sha256(token.encode()).hexdigest(), time.time()),
        ).fetchone()
        if record is None:
            raise HTTPException(401, "authentication_required")
        return dict(record)

    def membership(db, workspace_id, user_id, owner=False):
        record = db.execute(
            "SELECT role FROM memberships WHERE workspace_id=? AND user_id=?",
            (workspace_id, user_id),
        ).fetchone()
        if record is None:
            raise HTTPException(404, "workspace_not_found")
        if owner and record["role"] != "owner":
            raise HTTPException(403, "workspace_owner_required")
        return record["role"]

    def document(db, document_id, user_id, owner=False):
        record = db.execute(
            "SELECT d.* FROM documents d JOIN memberships m ON m.workspace_id=d.workspace_id "
            "WHERE d.id=? AND m.user_id=? AND (d.visibility='workspace' OR d.owner_id=?)",
            (document_id, user_id, user_id),
        ).fetchone()
        if record is None:
            raise HTTPException(404, "document_not_found")
        if owner and record["owner_id"] != user_id:
            raise HTTPException(403, "document_owner_required")
        return record

    def serialize(db, record, detail=False):
        value = dict(record)
        value.pop("source", None)
        value.pop("source_kind", None)
        content = value.pop("content")
        chunks = [
            dict(row)
            for row in db.execute(
                "SELECT id,text,page,start_offset,end_offset,ordinal FROM chunks "
                "WHERE document_id=? ORDER BY ordinal",
                (value["id"],),
            )
        ]
        value["chunk_count"] = len(chunks)
        if detail:
            value.update(content=content, chunks=chunks)
        return value

    def workspaces(db, user_id):
        return [
            dict(row)
            for row in db.execute(
                "SELECT w.id,w.name,m.role FROM workspaces w "
                "JOIN memberships m ON w.id=m.workspace_id WHERE m.user_id=? ORDER BY w.name,w.id",
                (user_id,),
            )
        ]

    def set_session(db, response, user_id, old_token=None):
        token = secrets.token_urlsafe(32)
        if old_token:
            db.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (hashlib.sha256(old_token.encode()).hexdigest(),),
            )
        db.execute("DELETE FROM sessions WHERE expires_at<=?", (time.time(),))
        db.execute(
            "INSERT INTO sessions VALUES (?,?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), user_id, time.time() + SESSION_TTL),
        )
        response.set_cookie(
            COOKIE,
            token,
            max_age=SESSION_TTL,
            httponly=True,
            secure=os.getenv("DOCTRAIL_SECURE_COOKIE") == "1",
            samesite="strict",
            path="/",
        )

    def throttle(request):
        address = request.client.host if request.client else "unknown"
        current = time.monotonic()
        with attempt_lock:
            if len(attempts) > 4096:
                for key in list(attempts):
                    if not attempts[key] or attempts[key][-1] < current - 60:
                        del attempts[key]
            queue = attempts[address]
            while queue and queue[0] < current - 60:
                queue.popleft()
            if len(queue) >= 20:
                raise HTTPException(
                    429, "authentication_rate_limited", headers={"Retry-After": "60"}
                )
            queue.append(current)

    def replace_chunks(db, document_id, content, pages):
        db.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
        for chunk in chunk_content(content, pages):
            db.execute(
                "INSERT INTO chunks VALUES (?,?,?,?,?,?,?)",
                (
                    uid(),
                    document_id,
                    chunk.text,
                    chunk.page,
                    chunk.start_offset,
                    chunk.end_offset,
                    chunk.ordinal,
                ),
            )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, _exc):
        # FastAPI's default includes input values, which could echo a password or document.
        return JSONResponse(status_code=422, content={"detail": "invalid_request"})

    @app.middleware("http")
    async def request_guard(request: Request, call_next):
        request_id = uid()
        started = time.perf_counter()
        response = None
        received_bytes = 0
        original_receive = request._receive

        async def bounded_receive():
            nonlocal received_bytes
            message = await original_receive()
            received_bytes += len(message.get("body", b""))
            if received_bytes > MAX_FILE_BYTES + 65536:
                raise HTTPException(413, "request_too_large")
            return message

        request._receive = bounded_receive
        try:
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                origin = request.headers.get("origin")
                target = urlsplit(str(request.url))
                if request.headers.get("sec-fetch-site") == "cross-site" or (
                    origin
                    and (urlsplit(origin).scheme, urlsplit(origin).netloc)
                    != (target.scheme, target.netloc)
                ):
                    response = JSONResponse(
                        status_code=403, content={"detail": "cross_origin_request_rejected"}
                    )
                length = request.headers.get("content-length")
                if response is None and length:
                    try:
                        too_large = int(length) > MAX_FILE_BYTES + 65536
                    except ValueError:
                        too_large = True
                    if too_large:
                        response = JSONResponse(
                            status_code=413, content={"detail": "request_too_large"}
                        )
            if response is None:
                response = await call_next(request)
        except HTTPException as exc:
            response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        except Exception:  # noqa: BLE001 -- sanitized boundary; never expose source or passwords
            # Do not log exception repr: driver/parser exceptions may contain input text.
            response = JSONResponse(status_code=500, content={"detail": "internal_error"})
        # FastAPI may translate a receive error into a generic parsing 400.
        if received_bytes > MAX_FILE_BYTES + 65536:
            response = JSONResponse(status_code=413, content={"detail": "request_too_large"})
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        route = request.scope.get("route")
        logger.info(
            "request_id=%s method=%s route=%s status=%s elapsed_ms=%.2f",
            request_id,
            request.method,
            getattr(route, "path", "unmatched"),
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.post("/api/auth/register", status_code=201)
    def register(body: Register, request: Request, response: Response, db=Depends(database)):
        throttle(request)
        user_id, workspace_id = uid(), uid()
        name, workspace_name = body.name.strip(), body.workspace_name.strip()
        if not name or not workspace_name:
            raise HTTPException(422, "invalid_request")
        try:
            with db:
                db.execute(
                    "INSERT INTO users VALUES (?,?,?,?)",
                    (user_id, body.email, name, password_hash(body.password)),
                )
                db.execute("INSERT INTO workspaces VALUES (?,?)", (workspace_id, workspace_name))
                db.execute("INSERT INTO memberships VALUES (?,?,'owner')", (workspace_id, user_id))
                set_session(db, response, user_id, request.cookies.get(COOKIE))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "email_already_registered") from None
        return {
            "user": {"id": user_id, "email": body.email, "name": name},
            "workspaces": workspaces(db, user_id),
        }

    @app.post("/api/auth/login")
    def login(body: Login, request: Request, response: Response, db=Depends(database)):
        throttle(request)
        record = db.execute("SELECT * FROM users WHERE email=?", (body.email,)).fetchone()
        valid = verify_password(
            body.password, record["password_hash"] if record else dummy_password
        )
        if record is None or not valid:
            raise HTTPException(401, "invalid_credentials")
        with db:
            set_session(db, response, record["id"], request.cookies.get(COOKIE))
        return {
            "user": {key: record[key] for key in ("id", "email", "name")},
            "workspaces": workspaces(db, record["id"]),
        }

    @app.get("/api/auth/me")
    def me(current=Depends(user), db=Depends(database)):
        return {"user": current, "workspaces": workspaces(db, current["id"])}

    @app.post("/api/auth/logout", status_code=204)
    def logout(request: Request, response: Response, db=Depends(database)):
        with db:
            db.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (hashlib.sha256(request.cookies.get(COOKIE, "").encode()).hexdigest(),),
            )
        response.delete_cookie(COOKIE, path="/")

    @app.get("/api/workspaces")
    def workspace_list(current=Depends(user), db=Depends(database)):
        return {"items": workspaces(db, current["id"])}

    @app.post("/api/workspaces", status_code=201)
    def workspace_create(body: WorkspaceInput, current=Depends(user), db=Depends(database)):
        if not body.name.strip():
            raise HTTPException(422, "invalid_request")
        workspace_id = uid()
        with db:
            db.execute("INSERT INTO workspaces VALUES (?,?)", (workspace_id, body.name.strip()))
            db.execute(
                "INSERT INTO memberships VALUES (?,?,'owner')", (workspace_id, current["id"])
            )
        return {"id": workspace_id, "name": body.name.strip(), "role": "owner"}

    @app.get("/api/workspaces/{workspace_id}/members")
    def member_list(workspace_id: str, current=Depends(user), db=Depends(database)):
        membership(db, workspace_id, current["id"])
        return {
            "items": [
                dict(row)
                for row in db.execute(
                    "SELECT u.id,u.email,u.name,m.role FROM users u JOIN memberships m ON m.user_id=u.id "
                    "WHERE m.workspace_id=? ORDER BY u.name,u.id",
                    (workspace_id,),
                )
            ]
        }

    @app.post("/api/workspaces/{workspace_id}/members", status_code=201)
    def member_add(
        workspace_id: str, body: MemberInput, current=Depends(user), db=Depends(database)
    ):
        with db:
            db.execute("BEGIN IMMEDIATE")
            membership(db, workspace_id, current["id"], owner=True)
            member = db.execute(
                "SELECT id FROM users WHERE email=?", (body.email.strip().lower(),)
            ).fetchone()
            if member is None:
                raise HTTPException(404, "user_not_found")
            db.execute(
                "INSERT OR IGNORE INTO memberships VALUES (?,?,'member')",
                (workspace_id, member["id"]),
            )
        return {"ok": True}

    @app.get("/api/workspaces/{workspace_id}/documents")
    def document_list(workspace_id: str, current=Depends(user), db=Depends(database)):
        with db:
            db.execute("BEGIN")
            membership(db, workspace_id, current["id"])
            records = db.execute(
                "SELECT * FROM documents WHERE workspace_id=? "
                "AND (visibility='workspace' OR owner_id=?) ORDER BY updated_at DESC,id",
                (workspace_id, current["id"]),
            ).fetchall()
            return {"items": [serialize(db, record) for record in records]}

    @app.post("/api/workspaces/{workspace_id}/documents", status_code=201)
    def document_upload(
        workspace_id: str,
        file: UploadFile = File(...),
        title: str | None = Form(None),
        visibility: Literal["workspace", "private"] = Form("workspace"),
        current=Depends(user),
        db=Depends(database),
    ):
        membership(db, workspace_id, current["id"])
        filename = (file.filename or "document").replace("\\", "/").rsplit("/", 1)[-1][:255]
        filename = "".join(char for char in filename if ord(char) >= 32) or "document"
        title = (title or filename).strip()
        if not title or len(title) > 200:
            raise HTTPException(422, "invalid_title")
        source = file.file.read(MAX_FILE_BYTES + 1)
        if len(source) > MAX_FILE_BYTES:
            raise HTTPException(413, "file_too_large")
        kind = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        media_type = {"pdf": "application/pdf", "md": "text/markdown", "txt": "text/plain"}.get(
            kind, "application/octet-stream"
        )
        content, pages, error = "", [], None
        try:
            content, pages = extract(source, kind)
        except ExtractionError as exc:
            error = str(exc)
        document_id, timestamp = uid(), now()
        with db:
            db.execute("BEGIN IMMEDIATE")
            membership(db, workspace_id, current["id"])
            db.execute(
                "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    document_id,
                    workspace_id,
                    title,
                    filename,
                    media_type,
                    visibility,
                    current["id"],
                    "failed" if error else "ready",
                    error,
                    1,
                    content,
                    source,
                    kind,
                    timestamp,
                    timestamp,
                ),
            )
            replace_chunks(db, document_id, content, pages)
        return serialize(db, document(db, document_id, current["id"]), True)

    @app.get("/api/documents/{document_id}")
    def document_get(document_id: str, current=Depends(user), db=Depends(database)):
        with db:
            db.execute("BEGIN")
            return serialize(db, document(db, document_id, current["id"]), True)

    @app.put("/api/documents/{document_id}")
    def document_edit(
        document_id: str, body: EditInput, current=Depends(user), db=Depends(database)
    ):
        document(db, document_id, current["id"], owner=True)
        if not body.title.strip():
            raise HTTPException(422, "invalid_title")
        try:
            content, pages = extract(body.content.encode("utf-8"), "txt")
        except ExtractionError as exc:
            raise HTTPException(422, str(exc)) from None
        with db:
            db.execute("BEGIN IMMEDIATE")
            document(db, document_id, current["id"], owner=True)
            db.execute(
                "UPDATE documents SET title=?,content=?,visibility=?,source=?,source_kind='txt',"
                "status='ready',error=NULL,revision=revision+1,updated_at=? WHERE id=?",
                (
                    body.title.strip(),
                    content,
                    body.visibility,
                    content.encode("utf-8"),
                    now(),
                    document_id,
                ),
            )
            replace_chunks(db, document_id, content, pages)
        return serialize(db, document(db, document_id, current["id"]), True)

    @app.post("/api/documents/{document_id}/reprocess")
    def document_reprocess(document_id: str, current=Depends(user), db=Depends(database)):
        with db:
            db.execute("BEGIN IMMEDIATE")
            record = document(db, document_id, current["id"], owner=True)
            content, pages, error = "", [], None
            try:
                content, pages = extract(record["source"], record["source_kind"])
            except ExtractionError as exc:
                if record["status"] == "ready":
                    raise HTTPException(422, str(exc)) from None
                error = str(exc)
            db.execute(
                "UPDATE documents SET content=?,status=?,error=?,revision=revision+1,"
                "updated_at=? WHERE id=?",
                (content, "failed" if error else "ready", error, now(), document_id),
            )
            replace_chunks(db, document_id, content, pages)
        return serialize(db, document(db, document_id, current["id"]), True)

    @app.delete("/api/documents/{document_id}", status_code=204)
    def document_delete(document_id: str, current=Depends(user), db=Depends(database)):
        with db:
            db.execute("BEGIN IMMEDIATE")
            document(db, document_id, current["id"], owner=True)
            db.execute("DELETE FROM documents WHERE id=?", (document_id,))

    @app.get("/api/workspaces/{workspace_id}/search")
    def search(
        workspace_id: str,
        q: str = Query(min_length=1, max_length=500),
        limit: int = Query(default=10, ge=1, le=50),
        current=Depends(user),
        db=Depends(database),
    ):
        started = time.perf_counter()
        if not q.strip():
            raise HTTPException(422, "query_required")
        search_id = uid()
        # Snapshot and history insertion share the write transaction; ACL cannot race a revision.
        with db:
            db.execute("BEGIN IMMEDIATE")
            membership(db, workspace_id, current["id"])
            candidates = [
                dict(row)
                for row in db.execute(
                    "SELECT d.id AS document_id,d.title,d.filename,d.revision,c.id AS chunk_id,"
                    "c.text,c.page,c.start_offset,c.end_offset FROM chunks c "
                    "JOIN documents d ON c.document_id=d.id WHERE d.workspace_id=? "
                    "AND d.status='ready' AND (d.visibility='workspace' OR d.owner_id=?)",
                    (workspace_id, current["id"]),
                )
            ]
            results = rank_chunks(q, candidates, limit)
            db.execute(
                "INSERT INTO searches VALUES (?,?,?,?,?)",
                (search_id, workspace_id, current["id"], q, now()),
            )
            for result in results:
                db.execute(
                    "INSERT INTO search_results VALUES (?,?,?,?)",
                    (search_id, result["document_id"], result["chunk_id"], result["revision"]),
                )
        return {
            "query": q,
            "method": "bm25",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "search_id": search_id,
            "results": results,
        }

    @app.get("/api/workspaces/{workspace_id}/history")
    def history(workspace_id: str, current=Depends(user), db=Depends(database)):
        with db:
            db.execute("BEGIN")
            membership(db, workspace_id, current["id"])
            rows = db.execute(
                "SELECT s.id,s.query,s.created_at, (SELECT COUNT(*) FROM search_results r "
                "JOIN documents d ON d.id=r.document_id WHERE r.search_id=s.id "
                "AND d.status='ready' AND d.revision=r.revision "
                "AND (d.visibility='workspace' OR d.owner_id=?)) AS result_count "
                "FROM searches s WHERE s.workspace_id=? AND s.user_id=? "
                "ORDER BY s.created_at DESC,s.id LIMIT 100",
                (current["id"], workspace_id, current["id"]),
            ).fetchall()
        return {"items": [dict(row) for row in rows]}

    @app.post("/api/searches/{search_id}/feedback")
    def feedback(search_id: str, body: FeedbackInput, current=Depends(user), db=Depends(database)):
        with db:
            db.execute("BEGIN IMMEDIATE")
            record = db.execute(
                "SELECT * FROM searches WHERE id=? AND user_id=?", (search_id, current["id"])
            ).fetchone()
            if record is None:
                raise HTTPException(404, "search_not_found")
            membership(db, record["workspace_id"], current["id"])
            doc = document(db, body.document_id, current["id"])
            returned = db.execute(
                "SELECT revision FROM search_results WHERE search_id=? AND document_id=? LIMIT 1",
                (search_id, body.document_id),
            ).fetchone()
            if returned is None:
                raise HTTPException(422, "document_not_in_search")
            if doc["revision"] != returned["revision"]:
                raise HTTPException(409, "search_result_stale")
            db.execute(
                "INSERT INTO feedback VALUES (?,?,?,?) ON CONFLICT(search_id,document_id) "
                "DO UPDATE SET relevant=excluded.relevant,created_at=excluded.created_at",
                (search_id, body.document_id, int(body.relevant), now()),
            )
        return {"ok": True}

    dist = Path(__file__).resolve().parents[2] / "web" / "dist"

    @app.get("/{asset_path:path}", include_in_schema=False)
    def frontend(asset_path: str):
        if asset_path == "api" or asset_path.startswith("api/"):
            raise HTTPException(404, "not_found")
        requested = (dist / asset_path).resolve()
        if not requested.is_relative_to(dist.resolve()):
            raise HTTPException(404, "not_found")
        if requested.is_file():
            return FileResponse(requested)
        index = dist / "index.html"
        if index.is_file() and "." not in asset_path.rsplit("/", 1)[-1]:
            return FileResponse(index)
        raise HTTPException(404, "frontend_not_built")

    return app


app = create_app()
