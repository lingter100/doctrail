"""Opt-in synthetic Java meeting backup/restore operations; never model quality.

Run from repository root with -m. No build, download, inference worker or corpus replay.
All raw evidence remains in the new explicitly supplied .local directory.
"""
from __future__ import annotations

import argparse
import codecs
import copy
import hashlib
import json
import locale
import math
import os
import queue
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from contextlib import closing, contextmanager
from pathlib import Path

import httpx
import psutil

from scripts import verify_java_service as java_helper
from scripts.backup_db import copy_database
from scripts.verify_java_service import COOKIE, digest, expect, java_server

ROOT = Path(__file__).resolve().parents[1]
FIXED = {
    "scripts/verify_java_service.py": "e632b1a3082637c8cd8ce7aad7654b0264367dc2f0a390429c75dd9b9a15a68d",
    "scripts/backup_db.py": "93eb767a0969a4999a8e33ee465cfed2f82c13d7c8b96eeecd092669dbb29a6a",
    "web/scripts/meeting-transport-fixture.mjs": "fe2de364c7923ebfaf473b4f3397d773c169a299a0c031e8666f73caf7ab3519",
}
TABLES = ("documents", "chunks", "meetings", "meeting_runs", "meeting_edits", "meeting_links",
          "meeting_link_evidence", "users", "workspaces", "memberships")
HOST = r'''
import { startMeetingTransportFixture } from './web/scripts/meeting-transport-fixture.mjs';
import { createInterface } from 'node:readline';
const fixture = await startMeetingTransportFixture();
const send = value => process.stdout.write(JSON.stringify(value) + '\n');
send({type:'ready',url:fixture.url,token:fixture.token});
const lines = createInterface({input:process.stdin});
try {
  for await (const line of lines) {
    const request = JSON.parse(line);
    if (request.command === 'stats') send({type:'stats',calls:{...fixture.calls}});
    else if (request.command === 'stop') break;
    else throw Error('Unknown fixed-host command');
  }
} finally {
  lines.close(); await fixture.close(); send({type:'closed',calls:{...fixture.calls}});
}
'''
TEXT = ("🚀 복원 회의 {number} — 유니코드복원근거\n"
        "SYNTHETIC_MEETING_TRANSPORT_FIXTURE\nFIXTURE_GROUNDED_SUMMARY_V2\n"
        "회의 날짜: 2026-10-13\n참석자: 민수\n"
        "단계별 배포로 진행하기로 결정했다.\n민수는 후속 점검을 맡는다.\n")


class CheckFailure(RuntimeError):
    """A predeclared safe code, never raw HTTP text or credentials."""


def require(condition, code):
    if not condition:
        raise CheckFailure(code)


def save(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def binding(path):
    return {"file": path.name, "size_bytes": path.stat().st_size, "sha256": digest(path)}


@contextmanager
def child_environment(generation_url="", generation_token=""):
    values = {"DOCTRAIL_GENERATION_URL": generation_url,
              "DOCTRAIL_GENERATION_TOKEN": generation_token,
              "DOCTRAIL_INFERENCE_URL": "", "DOCTRAIL_INFERENCE_TOKEN": "",
              "DOCTRAIL_EMBEDDING_PROFILE": "base", "DOCTRAIL_RAG_ANSWER_ENABLED": "false",
              "DOCTRAIL_SECURE_COOKIE": "0", "SERVER_ADDRESS": "127.0.0.1",
              "JDK_JAVA_OPTIONS": "-Dstdout.encoding=UTF-8 -Dstderr.encoding=UTF-8"}
    # Prevent inherited JVM/Spring overrides from silently enabling a real worker.
    clear = {key for key in os.environ if key.startswith("SPRING_")} | {
        "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"}
    old = {key: os.environ.get(key) for key in values.keys() | clear}
    try:
        for key in clear:
            os.environ.pop(key, None)
        os.environ.update(values)
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class Fixture:
    """Fixed existing fixture host with an owned handle and private protocol logs."""
    def __init__(self, folder, report):
        self.folder, self.report = folder, report
        self.process = None
        self.lines = queue.Queue()
        self.reader = None
        self.log = None
        self.identity = {}
        self.ready = False
        self.reader_errors = []
        self.reader_started = False

    def receive(self, expected):
        try:
            line = self.lines.get(timeout=15)
        except queue.Empty as error:
            raise CheckFailure("fixture_protocol_timeout") from error
        require(line is not None, "fixture_protocol_eof")
        value = json.loads(line)
        require(value.get("type") == expected, "fixture_protocol_type")
        return value

    def request(self, command, expected):
        self.process.stdin.write(json.dumps({"command": command}) + "\n")
        self.process.stdin.flush()
        return self.receive(expected)

    def stats(self):
        return self.request("stats", "stats")["calls"]

    def __enter__(self):
        try:
            node = shutil.which("node")
            require(node is not None, "node_missing")
            self.log = (self.folder / "fixture-stderr.log").open("ab")
            self.process = subprocess.Popen(
                [node, "--input-type=module", "-e", HOST], cwd=ROOT,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.identity = {"pid": self.process.pid,
                             "create_time": psutil.Process(self.process.pid).create_time()}

            def drain():
                try:
                    with (self.folder / "fixture-private-protocol.jsonl").open("x", encoding="utf-8") as log:
                        for line in self.process.stdout:
                            log.write(line)
                            log.flush()
                            self.lines.put(line)
                except Exception as error:  # noqa: BLE001 - record owned reader failure
                    self.reader_errors.append(type(error).__name__)
                finally:
                    self.lines.put(None)
            self.reader = threading.Thread(target=drain, daemon=True)
            self.reader.start()
            self.reader_started = True
            ready = self.receive("ready")
            require(ready["url"].startswith("http://127.0.0.1:"), "fixture_not_loopback")
            self.url, self.token = ready["url"], ready["token"]
            self.ready = True
            return self
        except BaseException:
            try:
                self.close()
            except BaseException as cleanup_error:  # noqa: BLE001 - never replace the primary startup failure
                record = self.report.setdefault("fixture_cleanup", {"cleanup_errors": []})
                record["cleanup_errors"].append(type(cleanup_error).__name__)
            raise

    def close(self):
        record = {**self.identity, "started": self.process is not None, "cleanup_errors": []}
        try:
            if self.process is not None:
                try:
                    if self.process.poll() is None:
                        if self.ready:
                            record["final_calls"] = self.request("stop", "closed")["calls"]
                        self.process.wait(timeout=15 if self.ready else 1)
                except Exception as error:  # noqa: BLE001 - only the returned owned handle
                    record["cleanup_errors"].append(type(error).__name__)
                    if self.process.poll() is None:
                        self.process.terminate()
                        try:
                            self.process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            self.process.kill()
                            self.process.wait(timeout=5)
        except Exception as error:  # noqa: BLE001 - preserve cleanup failure beside first failure
            record["cleanup_errors"].append(type(error).__name__)
        finally:
            if self.process is not None:
                record["exit_code"] = self.process.poll()
                record["reader_started"] = self.reader_started
                record["reader_joined"] = False
                if self.reader_started:
                    try:
                        self.reader.join(timeout=5)
                        record["reader_joined"] = not self.reader.is_alive()
                    except (RuntimeError, OSError) as error:
                        record["cleanup_errors"].append(type(error).__name__)
                for stream in (self.process.stdin, self.process.stdout):
                    try:
                        if stream:
                            stream.close()
                    except (OSError, ValueError) as error:
                        record["cleanup_errors"].append(type(error).__name__)
            if self.log:
                try:
                    self.log.close()
                except OSError as error:
                    record["cleanup_errors"].append(type(error).__name__)
            record["reader_errors"] = list(self.reader_errors)
            self.report["fixture_cleanup"] = record
        return record

    def __exit__(self, kind, value, trace):
        record = self.close()
        if kind is None:
            require(record.get("exit_code") == 0 and not record["cleanup_errors"]
                    and record.get("reader_joined") and not record["reader_errors"], "fixture_cleanup_failed")


_JAVA_CAPTURE_LOCK = threading.Lock()


class JavaObservation:
    """Serial helper-module instrumentation; the frozen helper owns real cleanup."""
    def __init__(self, jar):
        self.jar = jar.resolve()
        self.rows, self.handles, self.errors = [], [], []
        self.active = False
        self.attempts = 0

    def start(self):
        require(_JAVA_CAPTURE_LOCK.acquire(blocking=False), "java_capture_scope_busy")
        try:
            self.owner_thread = threading.get_ident()
            self.original = java_helper.subprocess
            self.original_popen = self.original.Popen
            java_helper.subprocess = self
            self.active = True
        except BaseException:
            _JAVA_CAPTURE_LOCK.release()
            raise

    def __getattr__(self, name):
        # In particular, real run keeps its original subprocess module globals.
        return getattr(self.original, name)

    @staticmethod
    def valid_creation_time(value):
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and value > 0)

    def reject(self, code):
        self.errors.append(code)
        raise CheckFailure(code)

    def Popen(self, *args, **kwargs):
        if not self.active or threading.get_ident() != self.owner_thread:
            self.reject("java_capture_cross_thread")
        if java_helper.subprocess is not self:
            self.reject("java_capture_reference_conflict")
        if self.attempts:
            self.reject("java_capture_multiple")
        command = args[0] if args else kwargs.get("args")
        try:
            matches = (isinstance(command, (list, tuple)) and len(command) >= 3
                       and command[1] == "-jar" and command.count("-jar") == 1
                       and Path(command[2]).resolve() == self.jar)
        except (TypeError, ValueError, OSError):
            matches = False
        if not matches:
            self.reject("java_capture_target_mismatch")
        self.attempts += 1
        process = self.original_popen(*args, **kwargs)
        # Save and return the identical handle even if auxiliary metadata fails.
        self.handles.append(process)
        row = {"exit_observed": False, "absence_confirmed": False}
        self.rows.append(row)
        try:
            pid = process.pid
            require(isinstance(pid, int) and not isinstance(pid, bool) and pid > 0,
                    "java_capture_pid_invalid")
            row["pid"] = pid
            created = psutil.Process(pid).create_time()
            require(self.valid_creation_time(created), "java_capture_identity_invalid")
            row["create_time"] = created
        except BaseException as error:  # noqa: BLE001 - do not obstruct frozen helper cleanup
            self.errors.append("capture_identity_" + type(error).__name__)
        return process

    def record_exit(self, index):
        # This frame must return before finish releases the last owned reference.
        process, row = self.handles[index], self.rows[index]
        try:
            code = process.returncode
            if code is None:
                code = process.poll()
            row["exit_code"] = code
            row["exit_observed"] = isinstance(code, int) and not isinstance(code, bool)
        except BaseException as error:  # noqa: BLE001 - preserve observation failures
            self.errors.append("capture_exit_" + type(error).__name__)
        return row["exit_observed"]

    def confirm_absence(self, row, deadline):
        row["absence_polls"] = 0
        while True:
            if time.monotonic() >= deadline:
                self.errors.append("capture_absence_timeout")
                return
            row["absence_polls"] += 1
            try:
                created = psutil.Process(row["pid"]).create_time()
                require(self.valid_creation_time(created), "java_capture_absence_uncertain")
                if created != row["create_time"]:
                    row["absence_confirmed"] = True
                    return
            except psutil.NoSuchProcess:
                row["absence_confirmed"] = True
                return
            except BaseException as error:  # noqa: BLE001 - uncertain absence is failure
                self.errors.append("capture_absence_" + type(error).__name__)
                return
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.02, remaining))

    def finish(self):
        require(self.active and threading.get_ident() == self.owner_thread,
                "java_capture_finish_owner")
        captured_handles = len(self.handles)
        try:
            if java_helper.subprocess is not self:
                self.errors.append("java_capture_reference_conflict")
            # Index iteration retains no Popen in a loop local or zip iterator.
            # record_exit returns scalar data before we drop each known-exit handle.
            for index in range(captured_handles):
                if self.record_exit(index):
                    self.handles[index] = None
                    self.rows[index]["companion_reference_released"] = True
            self.handles = [handle for handle in self.handles if handle is not None]
            # One overall deadline, shared by every identity and never refreshed.
            deadline = time.monotonic() + 5.0
            for row in self.rows:
                if row["exit_observed"] and "pid" in row and "create_time" in row:
                    self.confirm_absence(row, deadline)
        finally:
            # Restore our exact prior reference even when another caller conflicted.
            try:
                java_helper.subprocess = self.original
            finally:
                self.active = False
                _JAVA_CAPTURE_LOCK.release()
        return {"identities": self.rows, "observation_errors": self.errors,
                "all_exits_observed": len(self.rows) == 1 and all(
                    x["exit_observed"] and x["absence_confirmed"] for x in self.rows),
                "reference_restored": java_helper.subprocess is self.original,
                "capture_method": "scoped_helper_module_exact_Popen_handle",
                "Popen_attempts": self.attempts, "captured_handles": captured_handles,
                "absence_timeout_seconds": 5.0}


def safe_failure(error):
    return {"type": type(error).__name__,
            "code": str(error) if isinstance(error, CheckFailure) else "exception_private_log"}


def earliest_exception(error):
    # Frozen helper startup + finally cleanup retains the original in __context__.
    chain, seen = [], set()
    while error is not None and id(error) not in seen:
        chain.append(error)
        seen.add(id(error))
        error = error.__context__
    return chain[-1], chain[:-1]


@contextmanager
def observed_java(jar, database, private, phase, report, fixture=None):
    observer = JavaObservation(jar)
    primary, primary_traceback, primary_stage = None, None, "startup"
    secondary = []
    result = {"all_exits_observed": False, "reference_restored": False, "observation_errors": []}
    observer_started = False
    try:
        observer.start()
        observer_started = True
        with child_environment(fixture.url if fixture else "", fixture.token if fixture else ""):  # noqa: SIM117
            with java_server(jar, database, private / f"java-{phase}.log") as client:
                try:
                    yield client
                except BaseException as error:
                    # Capture before frozen helper __exit__ can replace this failure.
                    primary, primary_traceback, primary_stage = error, error.__traceback__, "body"
                    raise
    except BaseException as error:  # noqa: BLE001 - rethrow preserved primary after owned cleanup
        if primary is None:
            primary, cleanup_chain = earliest_exception(error)
            primary_traceback = primary.__traceback__
            secondary.extend({"stage": "helper_exit", **safe_failure(x)} for x in cleanup_chain)
        elif error is not primary:
            secondary.append({"stage": "helper_exit", **safe_failure(error)})
    finally:
        if observer_started:
            try:
                result = observer.finish()
            except BaseException as error:  # noqa: BLE001 - retain observer failure separately
                secondary.append({"stage": "observer_finish", **safe_failure(error)})
        record = {"phase": phase, **result, "secondary_cleanup_errors": secondary}
        if primary is not None:
            record["first_failure"] = {"stage": primary_stage, **safe_failure(primary)}
        report["java_lifecycles"].append(record)
    if primary is not None:
        raise primary.with_traceback(primary_traceback)
    require(not secondary and result["all_exits_observed"] and result["reference_restored"]
            and not result["observation_errors"], "java_exit_observation_failed")



def database_state(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "sqlite_integrity")
        require(not db.execute("PRAGMA foreign_key_check").fetchall(), "sqlite_foreign_keys")
        tables = {}
        for name in TABLES:
            columns = [x[1] for x in db.execute(f'PRAGMA table_info("{name}")')]
            require(bool(columns), "missing_required_table")
            rows = [[{"blob_hex": v.hex()} if isinstance(v, bytes) else v for v in row]
                    for row in db.execute(f'SELECT * FROM "{name}"')]
            tables[name] = {"columns": columns, "rows": sorted(rows, key=lambda x: json.dumps(x))}
        sessions = db.execute("SELECT count(*) FROM sessions").fetchone()[0]
        active = db.execute("SELECT count(*) FROM meetings WHERE active_run IS NOT NULL "
                            "OR analysis_status IN ('queued','running')").fetchone()[0]
        running = db.execute("SELECT count(*) FROM meeting_runs WHERE status IN ('queued','running')").fetchone()[0]
        require(active == running == 0, "meeting_jobs_not_quiescent")
        return {"tables": tables, "sessions": sessions}


def wait_ready(client, identity):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        detail = expect(client.get(f"/api/meetings/{identity}"))
        status = detail["meeting"]["analysis_status"]
        if status == "ready":
            require(detail["meeting"]["analysis"]["summary_version"] == 2, "summary_v2_missing")
            return detail
        require(status in ("queued", "running"), "synthetic_analysis_failed")
        time.sleep(0.1)
    raise CheckFailure("synthetic_analysis_timeout")


def edit_analysis(detail):
    analysis = copy.deepcopy(detail["meeting"]["analysis"])
    analysis["summary_claims"][0]["text"] = "복원 검증용 편집: 단계별 배포를 결정하고 민수가 후속 점검을 맡는다."
    analysis["summary"] = "\n".join(x["text"] for x in analysis["summary_claims"])
    spans = {(x["start_offset"], x["end_offset"]): x
             for claim in analysis["summary_claims"] for x in claim["citations"]}
    analysis["summary_evidence"] = [spans[key] for key in sorted(spans)]
    for item in analysis["items"]:
        if item["type"] == "decision":
            item["status"] = "confirmed"
        if item["type"] == "action":
            item.update(assignee="복원 담당자", status="done")
    return analysis


def snapshot(client, ids, workspace):
    return {"meetings": [expect(client.get(f"/api/meetings/{x}")) for x in ids],
            "documents": [expect(client.get(f"/api/documents/{x}")) for x in ids],
            "runs": [expect(client.get(f"/api/meetings/{x}/runs")) for x in ids],
            "links": [expect(client.get(f"/api/meetings/{x}/links")) for x in ids],
            "tasks": expect(client.get("/api/tasks", params={"workspace_id": workspace,
                            "assignee": "복원 담당자", "status": "done"}))}


def check_spans(state):
    for detail in state["meetings"]:
        content = detail["document"]["content"]
        analysis = detail["meeting"]["analysis"]
        require(analysis["summary"] == "\n".join(x["text"] for x in analysis["summary_claims"]),
                "summary_projection_drift")
        for claim in analysis["summary_claims"]:
            for span in claim["citations"]:
                require(content[span["start_offset"]:span["end_offset"]] == span["quote"], "citation_offset_drift")
    for document in state["documents"]:
        for chunk in document["chunks"]:
            require(document["content"][chunk["start_offset"]:chunk["end_offset"]] == chunk["text"], "chunk_offset_drift")


def verify_edit_response(before, changed, edited):
    require(edited["meeting"]["analysis"] == changed, "edit_analysis_mismatch")
    require(edited["meeting"]["ai_analysis"] == before["meeting"]["ai_analysis"]
            and edited["meeting"]["provenance"] == "user_edited", "edit_provenance_drift")


def member_denied(client, private_id, shared_id, workspace):
    expect(client.get(f"/api/meetings/{private_id}"), 404)
    expect(client.get(f"/api/documents/{private_id}"), 404)
    shared_meeting = expect(client.get(f"/api/meetings/{shared_id}"))
    shared_document = expect(client.get(f"/api/documents/{shared_id}"))
    require(shared_meeting["document"]["id"] == shared_id and shared_document["id"] == shared_id,
            "shared_read_identity")
    result = expect(client.post("/api/knowledge/search", json={"query": "유니코드복원근거",
                    "workspace_id": workspace, "kind": "meeting", "method": "bm25", "limit": 10}))
    require(all(x["document_id"] != private_id for x in result["results"]), "private_search_leak")
    require(any(x["document_id"] == shared_id for x in result["results"]), "shared_search_missing")
    tasks = expect(client.get("/api/tasks", params={"workspace_id": workspace}))
    require(all("meeting_id" in x and x["meeting_id"] != private_id for x in tasks["items"]), "private_task_leak")
    require(any(x["meeting_id"] == shared_id for x in tasks["items"]), "shared_tasks_missing")



def login(client, email, password):
    client.cookies.clear()
    expect(client.post("/api/auth/login", json={"email": email, "password": password}))


def exercise(jar, directory, report):
    private = directory / "private"
    source, backup, restored = [private / name for name in ("source.sqlite3", "backup.sqlite3", "restored.sqlite3")]
    password, member_password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    email, member_email = "operations-owner@example.invalid", "operations-member@example.invalid"
    with Fixture(private, report) as fixture:
        report["stage"] = "setup-java"
        with observed_java(jar, source, private, "setup", report, fixture) as owner:
            auth = expect(owner.post("/api/auth/register", json={"email": email, "password": password,
                          "name": "합성 복원 소유자", "workspace_name": "합성 복원 작업공간"}), 201)
            workspace = auth["workspaces"][0]["id"]
            old_cookie = owner.cookies.get(COOKIE)
            require(bool(old_cookie), "owner_cookie_missing")
            details = []
            for n in (1, 2):
                detail = expect(owner.post(f"/api/workspaces/{workspace}/meetings/text", json={
                    "title": f"복원 합성 회의 {n}", "content": TEXT.format(number=n),
                    "visibility": "private" if n == 1 else "workspace"}), 201)
                detail = wait_ready(owner, detail["document"]["id"])
                changed = edit_analysis(detail)
                edited = expect(owner.put(f"/api/meetings/{detail['document']['id']}/analysis", json={
                    "expected_revision": detail["document"]["revision"],
                    "expected_version": detail["meeting"]["version"], "analysis": changed}))
                verify_edit_response(detail, changed, edited)
                details.append(edited)
            ids = [x["document"]["id"] for x in details]
            first, later = details
            previous = next(x for x in first["meeting"]["analysis"]["items"] if x["type"] == "decision")
            current = next(x for x in later["meeting"]["analysis"]["items"] if x["type"] == "decision")
            link = expect(owner.post(f"/api/meetings/{ids[1]}/links", json={
                "target_meeting_id": ids[0], "source_item_id": current["id"], "target_item_id": previous["id"],
                "relation": "supersedes", "expected_revision": later["document"]["revision"],
                "expected_version": later["meeting"]["version"],
                "target_expected_revision": first["document"]["revision"],
                "target_expected_version": first["meeting"]["version"],
                **{k: current[k] for k in ("quote", "start_offset", "end_offset")}}), 201)
            require(bool(link["id"]), "link_missing")
            with httpx.Client(base_url=owner.base_url, timeout=30, trust_env=False) as member:
                expect(member.post("/api/auth/register", json={"email": member_email,
                    "password": member_password, "name": "합성 구성원", "workspace_name": "구성원 초기 공간"}), 201)
                expect(owner.post(f"/api/workspaces/{workspace}/members", json={"email": member_email}), 201)
                member_denied(member, ids[0], ids[1], workspace)
            before = snapshot(owner, ids, workspace)
            require(len(before["tasks"]["items"]) == 2, "edited_tasks_missing")
            check_spans(before)
            save(private / "api-before.json", before)
            database_state(source)
        calls = fixture.stats()
        require(calls == {"analyze": 2, "answer": 0}, "unexpected_setup_fixture_calls")
        report["stage"] = "disabled-source-restart"
        with observed_java(jar, source, private, "restart", report) as owner:
            owner.cookies.set(COOKIE, old_cookie)
            expect(owner.get("/api/auth/me"))
            require(snapshot(owner, ids, workspace) == before, "source_restart_state_changed")
        require(fixture.stats() == calls, "fixture_called_during_restart")
        report["stage"] = "backup-and-restore"
        baseline = database_state(source)
        save(private / "database-before.json", baseline)
        source_hash = digest(source)
        copy_database(source, backup)
        backup_hash = digest(backup)
        copy_database(backup, restored, restore=True)
        restored_before_login = database_state(restored)
        require(restored_before_login["sessions"] == 0, "restore_sessions_not_empty")
        require(restored_before_login["tables"] == baseline["tables"], "restored_tables_changed")
        require(database_state(backup)["tables"] == baseline["tables"], "backup_tables_changed")
        save(private / "database-restored-before-login.json", restored_before_login)
        report["stage"] = "restored-java-disabled"
        with observed_java(jar, restored, private, "restored", report) as owner:
            owner.cookies.set(COOKIE, old_cookie)
            for path in ("/api/auth/me", f"/api/meetings/{ids[0]}", f"/api/documents/{ids[0]}", "/api/tasks"):
                expect(owner.get(path), 401)
            login(owner, email, password)
            require(bool(owner.cookies.get(COOKIE)) and owner.cookies.get(COOKIE) != old_cookie, "session_not_rotated")
            after = snapshot(owner, ids, workspace)
            require(after == before, "restored_API_state_changed")
            check_spans(after)
            save(private / "api-restored.json", after)
            found = expect(owner.post("/api/knowledge/search", json={"query": "유니코드복원근거",
                "workspace_id": workspace, "kind": "meeting", "method": "bm25", "limit": 10}))
            require(found["method"] == "bm25" and {x["document_id"] for x in found["results"]} == set(ids), "restored_bm25_missing")
            documents = {x["id"]: x for x in after["documents"]}
            for hit in found["results"]:
                doc = documents[hit["document_id"]]
                require(hit["revision"] == doc["revision"] and
                        doc["content"][hit["start_offset"]:hit["end_offset"]] == hit["text"], "search_unicode_span_drift")
            save(private / "bm25-restored.json", found)
            with httpx.Client(base_url=owner.base_url, timeout=30, trust_env=False) as member:
                login(member, member_email, member_password)
                member_denied(member, ids[0], ids[1], workspace)
        require(database_state(restored)["tables"] == baseline["tables"], "post_login_state_changed")
        require(fixture.stats() == calls, "fixture_called_during_restore")
        require(digest(source) == source_hash and digest(backup) == backup_hash, "source_or_backup_mutated")
        report.update(fixture_calls=calls, table_counts={k: len(v["rows"]) for k, v in baseline["tables"].items()},
                      sessions_before_restored_login=0, unchanged_source_sha256=source_hash,
                      unchanged_backup_sha256=backup_hash,
                      checks=["summary_v2_edit_and_provenance", "confirmed_decision_supersedes", "done_assignee_tasks",
                              "source_restart_without_generation", "backup_restore_table_equality", "integrity_foreign_keys",
                              "old_cookie_denied", "relogin_state_equality", "bm25_unicode_spans", "private_member_ACL",
                              "no_fixture_calls_during_restart_or_restore", "source_backup_unchanged"])


def subprocess_text_encoding():
    """Match Python 3.11+ subprocess text=True default, independently of stdout.

    subprocess._text_encoding uses UTF-8 mode, otherwise locale.getencoding().
    Keep the frozen discovery helper unchanged and compare canonical codec names.
    """
    encoding = "utf-8" if sys.flags.utf8_mode else locale.getencoding()
    return codecs.lookup(encoding).name


def run(jar, output, *, expected_jar_sha256):
    require(isinstance(expected_jar_sha256, str) and
            re.fullmatch(r"[a-fA-F0-9]{64}", expected_jar_sha256) is not None,
            "expected_jar_sha256_invalid")
    expected_jar_sha256 = expected_jar_sha256.lower()
    output = output.resolve()
    require(output.is_relative_to((ROOT / ".local").resolve()), "evidence_outside_local")
    require(not output.exists(), "evidence_destination_exists")
    output.mkdir(parents=True)
    private = output / "private"
    private.mkdir()
    report = {"schema_version": 1, "status": "running", "stage": "binding-preflight",
              "scope": "actual Java + synthetic HTTP transport operations only",
              "AI_quality": False, "human_review_count": 0, "model_tokenizer_calls": 0,
              "build_download_paid_Git_calls": 0, "java_lifecycles": [], "checks": []}
    before, jar_before = {}, None
    report["expected_jar_sha256"] = expected_jar_sha256
    try:
        report["stage"] = "subprocess-decoder-preflight"
        report["subprocess_text_encoding"] = subprocess_text_encoding()
        report["python_utf8_mode"] = bool(sys.flags.utf8_mode)
        report["invocation_guidance"] = "Use python -B -X utf8 -m scripts.verify_meeting_operations_companion"
        require(report["subprocess_text_encoding"] == "utf-8", "subprocess_text_requires_python_X_utf8")
        report["stage"] = "binding-preflight"
        require(jar.is_file(), "jar_binding")
        jar_before = report["jar_before"] = binding(jar)
        require(jar_before["sha256"] == expected_jar_sha256, "jar_binding")
        for name, sha in FIXED.items():
            require(digest(ROOT / name) == sha, "helper_or_fixture_binding")
        before = {name: digest(ROOT / name) for name in FIXED}
        report["bindings"] = {**before, "JAR": expected_jar_sha256, "companion": digest(Path(__file__)),
                              "fixed_node_host": hashlib.sha256(HOST.encode()).hexdigest()}
        exercise(jar, output, report)
        report["status"] = "passed"
    except Exception as error:  # noqa: BLE001 - preserve first failure without raw secrets
        report["status"] = "failed"
        report["first_failure"] = {"stage": report["stage"], "type": type(error).__name__,
                                   "code": str(error) if isinstance(error, CheckFailure) else "exception_private_log"}
        (private / "first-failure.log").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        try:
            if jar_before is not None:
                report["jar_after"] = binding(jar)
                report["JAR_unchanged"] = (report["jar_after"]["sha256"] == expected_jar_sha256
                    and report["jar_after"]["size_bytes"] == jar_before["size_bytes"])
                require(report["JAR_unchanged"], "jar_binding_changed")
            if before:
                report["helpers_fixture_unchanged"] = all(digest(ROOT / name) == sha for name, sha in before.items())
                require(report["helpers_fixture_unchanged"], "helper_binding_changed")
        except Exception as error:  # noqa: BLE001 - receipt survives posthash failure
            report["status"] = "failed"
            report.setdefault("first_failure", {"stage": "posthash", "type": type(error).__name__,
                                               "code": "posthash_failed"})
            report["posthash_error"] = type(error).__name__
        report["private_artifacts"] = []
        for artifact in sorted(private.iterdir()):
            if artifact.is_file():
                try:
                    report["private_artifacts"].append(binding(artifact))
                except OSError as error:
                    report["status"] = "failed"
                    report.setdefault("first_failure", {"stage": "artifact_index", "type": type(error).__name__})
        save(output / "report.json", report)
    return report


def sha256_argument(value):
    if re.fullmatch(r"[a-fA-F0-9]{64}", value) is None:
        raise argparse.ArgumentTypeError("expected JAR hash must be exactly 64 hexadecimal characters")
    return value.lower()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-jar-sha256", type=sha256_argument, required=True)
    parser.add_argument("--execute-synthetic-java", action="store_true", required=True)
    args = parser.parse_args()
    try:
        report = run(args.jar, args.output, expected_jar_sha256=args.expected_jar_sha256)
    except CheckFailure as error:
        print(json.dumps({"status": "refused", "code": str(error)}))
        return 2
    print(json.dumps({"status": report["status"], "report": str(args.output / "report.json"),
                      "AI_quality": False}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
