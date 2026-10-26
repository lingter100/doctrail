"""Bounded generic checks; no Java, model, tokenizer or private corpus launches."""
import copy
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import contextmanager

import pytest

from scripts import verify_meeting_operations_companion as companion
from scripts.backup_db import copy_database


def test_child_environment_disables_workers_and_restores_on_failure(monkeypatch):
    monkeypatch.setenv("DOCTRAIL_GENERATION_URL", "http://must-not-run.invalid")
    monkeypatch.setenv("DOCTRAIL_INFERENCE_TOKEN", "private-secret")
    monkeypatch.setenv("SPRING_APPLICATION_JSON", '{"override":"must-not-run"}')
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-Dunsafe=true")
    before = dict(os.environ)
    with pytest.raises(RuntimeError), companion.child_environment():
        assert os.environ["DOCTRAIL_GENERATION_URL"] == ""
        assert os.environ["DOCTRAIL_GENERATION_TOKEN"] == ""
        assert os.environ["DOCTRAIL_INFERENCE_URL"] == ""
        assert os.environ["DOCTRAIL_INFERENCE_TOKEN"] == ""
        assert "SPRING_APPLICATION_JSON" not in os.environ
        assert "JAVA_TOOL_OPTIONS" not in os.environ
        raise RuntimeError("synthetic body failure")
    assert dict(os.environ) == before


def test_edit_keeps_exact_citations_and_ai_original():
    content = companion.TEXT.format(number=1)
    quote = "단계별 배포로 진행하기로 결정했다."
    start = content.index(quote)
    span = {"quote": quote, "start_offset": start, "end_offset": start + len(quote)}
    analysis = {"summary_version": 2, "summary": "기존 문장", "summary_evidence": [span],
                "summary_claims": [{"id": 0, "text": "기존 문장", "citations": [span]}],
                "items": [{"id": "decision", "type": "decision", "status": "needs_confirmation"},
                          {"id": "action", "type": "action", "status": "needs_confirmation", "assignee": None}]}
    detail = {"meeting": {"analysis": analysis, "ai_analysis": copy.deepcopy(analysis)}}
    original = copy.deepcopy(detail)
    edited = companion.edit_analysis(detail)
    assert detail == original
    assert edited["summary"] == edited["summary_claims"][0]["text"]
    assert edited["summary_evidence"] == [span]
    assert edited["summary_claims"][0]["citations"] == [span]
    assert edited["items"][0]["status"] == "confirmed"
    assert edited["items"][1]["assignee"] == "복원 담당자"
    assert edited["items"][1]["status"] == "done"
    state = {"meetings": [{"document": {"content": content}, "meeting": {"analysis": edited}}],
             "documents": [{"content": content, "chunks": [{"start_offset": start, "end_offset": start + len(quote), "text": quote}]}]}
    companion.check_spans(state)
    state["documents"][0]["chunks"][0]["start_offset"] += 1
    with pytest.raises(companion.CheckFailure, match="chunk_offset_drift"):
        companion.check_spans(state)


def synthetic_db(path):
    with sqlite3.connect(path) as db:
        for table in companion.TABLES:
            if table == "meetings":
                db.execute("CREATE TABLE meetings(id TEXT, active_run TEXT, analysis_status TEXT)")
                db.execute("INSERT INTO meetings VALUES ('m',NULL,'ready')")
            elif table == "meeting_runs":
                db.execute("CREATE TABLE meeting_runs(id TEXT,status TEXT)")
                db.execute("INSERT INTO meeting_runs VALUES ('r','completed')")
            else:
                db.execute(f'CREATE TABLE "{table}" (id TEXT, value BLOB)')
                db.execute(f'INSERT INTO "{table}" VALUES (?,?)', ("한글🚀", b"\x00\x01"))
        db.execute("CREATE TABLE sessions(token_hash TEXT)")
        db.execute("INSERT INTO sessions VALUES ('synthetic-only-hash')")


def test_backup_restore_compares_all_state_and_invalidates_sessions(tmp_path):
    source, backup, restored = [tmp_path / x for x in ("source.db", "backup.db", "restored.db")]
    synthetic_db(source)
    original = companion.database_state(source)
    source_hash = companion.digest(source)
    copy_database(source, backup)
    backup_hash = companion.digest(backup)
    copy_database(backup, restored, restore=True)
    after = companion.database_state(restored)
    assert after["tables"] == original["tables"]
    assert original["sessions"] == 1 and after["sessions"] == 0
    assert companion.digest(source) == source_hash and companion.digest(backup) == backup_hash
    with pytest.raises(ValueError, match="new database"):
        copy_database(backup, restored, restore=True)
    with sqlite3.connect(restored) as db:
        db.execute("UPDATE meeting_link_evidence SET value=?", (b"changed",))
    assert companion.database_state(restored)["tables"] != original["tables"]


def test_quiescence_refuses_active_run(tmp_path):
    path = tmp_path / "source.db"
    synthetic_db(path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE meetings SET active_run='running-job'")
    with pytest.raises(companion.CheckFailure, match="meeting_jobs_not_quiescent"):
        companion.database_state(path)


def test_existing_destination_refused_before_any_process(monkeypatch, tmp_path):
    monkeypatch.setattr(companion, "ROOT", tmp_path)
    output = tmp_path / ".local" / "existing"
    output.mkdir(parents=True)
    (output / "preserve").write_text("original")
    with pytest.raises(companion.CheckFailure, match="evidence_destination_exists"):
        companion.run(tmp_path / "unused.jar", output, expected_jar_sha256="0" * 64)
    assert (output / "preserve").read_text() == "original"
    assert not (output / "report.json").exists()


def test_bad_jar_saves_safe_failure_and_private_log(monkeypatch, tmp_path):
    monkeypatch.setattr(companion, "ROOT", tmp_path)
    report = companion.run(tmp_path / "missing.jar", tmp_path / ".local" / "failed", expected_jar_sha256="0" * 64)
    assert report["status"] == "failed"
    assert report["first_failure"]["code"] == "jar_binding"
    assert report["java_lifecycles"] == []
    assert (tmp_path / ".local/failed/private/first-failure.log").is_file()


def test_startup_exception_records_failure_without_leaking_secrets(monkeypatch, tmp_path):
    monkeypatch.setattr(companion, "ROOT", tmp_path)
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"fake")
    monkeypatch.setattr(companion, "FIXED", {})
    def fail(*args):
        raise RuntimeError("cookie=private-secret-password")
    monkeypatch.setattr(companion, "exercise", fail)
    report = companion.run(jar, tmp_path / ".local" / "failed-startup", expected_jar_sha256=companion.digest(jar))
    assert report["status"] == "failed"
    assert "private-secret" not in json.dumps(report)
    assert "private-secret" in (tmp_path / ".local/failed-startup/private/first-failure.log").read_text()


def test_java_context_reuses_helper_restores_environment_and_reports_cleanup(monkeypatch, tmp_path):
    events = []
    class Observer:
        def __init__(self, jar):
            pass
        def start(self):
            events.append("observe")
        def finish(self):
            events.append("finished")
            return {"all_exits_observed": True, "reference_restored": True, "observation_errors": []}
    @contextmanager
    def fake_server(jar, database, log):
        assert os.environ["DOCTRAIL_GENERATION_URL"] == ""
        events.append("helper-enter")
        try:
            yield "client"
        finally:
            events.append("helper-exit")
    monkeypatch.setattr(companion, "JavaObservation", Observer)
    monkeypatch.setattr(companion, "java_server", fake_server)
    monkeypatch.setenv("DOCTRAIL_GENERATION_URL", "original")
    report = {"java_lifecycles": []}
    with pytest.raises(ValueError):  # noqa: SIM117
        with companion.observed_java(tmp_path / "x.jar", tmp_path / "x.db", tmp_path, "test", report) as client:
            assert client == "client"
            raise ValueError("body")
    assert events == ["observe", "helper-enter", "helper-exit", "finished"]
    assert os.environ["DOCTRAIL_GENERATION_URL"] == "original"
    assert report["java_lifecycles"][0]["all_exits_observed"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node unavailable")
def test_actual_fixed_node_host_starts_counts_and_closes_without_java(tmp_path):
    report = {}
    with companion.Fixture(tmp_path, report) as fixture:
        assert fixture.url.startswith("http://127.0.0.1:")
        assert fixture.stats() == {"analyze": 0, "answer": 0}
        process = fixture.process
    assert process.poll() == 0
    assert report["fixture_cleanup"]["exit_code"] == 0
    assert report["fixture_cleanup"]["reader_joined"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node unavailable")
def test_actual_node_startup_failure_preserves_owned_exit(monkeypatch, tmp_path):
    monkeypatch.setattr(companion, "HOST", "process.exit(3)")
    report = {}
    with pytest.raises(companion.CheckFailure, match="fixture_protocol_eof"):  # noqa: SIM117
        with companion.Fixture(tmp_path, report):
            pytest.fail("unreachable")
    assert report["fixture_cleanup"]["exit_code"] == 3
    assert report["fixture_cleanup"]["reader_joined"]


def test_cli_parser_never_launches_without_explicit_arguments(tmp_path):
    command = [sys.executable, "-B", "-X", "utf8", "-m", "scripts.verify_meeting_operations_companion"]
    help_result = subprocess.run(command + ["--help"], cwd=companion.ROOT, capture_output=True, text=True, check=False)
    assert help_result.returncode == 0
    assert "--execute-synthetic-java" in help_result.stdout
    missing = subprocess.run(command, cwd=companion.ROOT, capture_output=True, text=True, check=False)
    assert missing.returncode == 2
    output = tmp_path / "must-not-create"
    explicit = command + ["--jar", str(tmp_path / "unused.jar"), "--output", str(output),
                          "--execute-synthetic-java"]
    missing_hash = subprocess.run(explicit, cwd=companion.ROOT, capture_output=True, text=True, check=False)
    assert missing_hash.returncode == 2 and "--expected-jar-sha256" in missing_hash.stderr
    for invalid in ("abc", "G" * 64):
        malformed = subprocess.run(explicit + ["--expected-jar-sha256", invalid],
                                   cwd=companion.ROOT, capture_output=True, text=True, check=False)
        assert malformed.returncode == 2
    assert not output.exists()


def test_private_task_guard_uses_actual_meeting_id_contract():
    import httpx
    def transport(request):
        if request.url.path.startswith(("/api/meetings/", "/api/documents/")):
            if request.url.path.endswith("private-id"):
                return httpx.Response(404, json={"detail": "not_found"})
            return httpx.Response(200, json={"id": "shared", "document": {"id": "shared"}})
        if request.url.path == "/api/knowledge/search":
            return httpx.Response(200, json={"results": [{"document_id": "shared"}]})
        return httpx.Response(200, json={"items": [{"meeting_id": "private-id", "id": "task"}]})
    with httpx.Client(base_url="http://test", transport=httpx.MockTransport(transport)) as client:  # noqa: SIM117
        with pytest.raises(companion.CheckFailure, match="private_task_leak"):
            companion.member_denied(client, "private-id", "shared", "workspace")


def test_posthash_failure_does_not_replace_first_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(companion, "ROOT", tmp_path)
    jar, helper = tmp_path / "fake.jar", tmp_path / "helper.py"
    jar.write_bytes(b"fake")
    helper.write_bytes(b"original")
    monkeypatch.setattr(companion, "FIXED", {"helper.py": companion.digest(helper)})
    def fail(*args):
        helper.unlink()
        raise companion.CheckFailure("original_failure")
    monkeypatch.setattr(companion, "exercise", fail)
    report = companion.run(jar, tmp_path / ".local" / "posthash-failure", expected_jar_sha256=companion.digest(jar))
    assert report["status"] == "failed"
    assert report["first_failure"]["code"] == "original_failure"
    assert report["posthash_error"] == "FileNotFoundError"
    assert (tmp_path / ".local/posthash-failure/report.json").is_file()

# Independent review regressions: no Java process is launched by these fakes.
def test_review_explicit_jar_binding_and_postchange(monkeypatch, tmp_path):
    monkeypatch.setattr(companion, "ROOT", tmp_path)
    monkeypatch.setattr(companion, "FIXED", {})
    launches = []
    monkeypatch.setattr(companion, "exercise", lambda *args: launches.append("synthetic"))
    jar = tmp_path / "different-build.jar"
    jar.write_bytes(b"caller selected synthetic build")
    expected = companion.digest(jar)
    with pytest.raises(companion.CheckFailure, match="expected_jar_sha256_invalid"):
        companion.run(jar, tmp_path / ".local/invalid", expected_jar_sha256="not-a-hash")
    assert not (tmp_path / ".local/invalid").exists()
    bad = companion.run(jar, tmp_path / ".local/bad", expected_jar_sha256="0" * 64)
    assert bad["status"] == "failed" and not launches
    good = companion.run(jar, tmp_path / ".local/good", expected_jar_sha256=expected)
    assert good["status"] == "passed" and launches == ["synthetic"]
    assert good["jar_before"] == good["jar_after"]
    assert good["jar_before"]["sha256"] == expected
    def mutate(*args):
        jar.write_bytes(b"changed after admission")
    monkeypatch.setattr(companion, "exercise", mutate)
    changed = companion.run(jar, tmp_path / ".local/changed", expected_jar_sha256=expected)
    assert changed["status"] == "failed" and not changed["JAR_unchanged"]


@pytest.mark.parametrize("fault", ["helper", "observer"])
def test_review_primary_body_error_survives_cleanup(monkeypatch, tmp_path, fault):
    class Observer:
        def __init__(self, jar):
            pass
        def start(self):
            pass
        def finish(self):
            if fault == "observer":
                raise OSError("secondary observer error")
            return {"all_exits_observed": True, "reference_restored": True, "observation_errors": []}
    @contextmanager
    def server(*args):
        try:
            yield "client"
        finally:
            if fault == "helper":
                raise OSError("secondary helper error")
    monkeypatch.setattr(companion, "JavaObservation", Observer)
    monkeypatch.setattr(companion, "java_server", server)
    report = {"java_lifecycles": []}
    with pytest.raises(companion.CheckFailure, match="original_body_failure"):  # noqa: SIM117
        with companion.observed_java(tmp_path / "jar", tmp_path / "db", tmp_path, "test", report):
            raise companion.CheckFailure("original_body_failure")
    lifecycle = report["java_lifecycles"][0]
    assert lifecycle["first_failure"]["code"] == "original_body_failure"
    assert lifecycle["secondary_cleanup_errors"]


def test_review_primary_startup_error_survives_helper_cleanup(monkeypatch, tmp_path):
    class Observer:
        def __init__(self, jar):
            pass
        def start(self):
            pass
        def finish(self):
            return {"all_exits_observed": False, "reference_restored": True, "observation_errors": []}
    @contextmanager
    def server(*args):
        try:
            raise companion.CheckFailure("original_startup_failure")
            yield  # pragma: no cover - contextmanager shape only
        finally:
            raise OSError("secondary helper cleanup")
    monkeypatch.setattr(companion, "JavaObservation", Observer)
    monkeypatch.setattr(companion, "java_server", server)
    report = {"java_lifecycles": []}
    with pytest.raises(companion.CheckFailure, match="original_startup_failure"):  # noqa: SIM117
        with companion.observed_java(tmp_path / "jar", tmp_path / "db", tmp_path, "test", report):
            pytest.fail("unreachable")
    assert report["java_lifecycles"][0]["secondary_cleanup_errors"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node unavailable")
def test_review_unstarted_reader_keeps_original_failure(monkeypatch, tmp_path):
    def fail_start(self):
        raise ValueError("original_reader_start_failure")
    monkeypatch.setattr(companion.threading.Thread, "start", fail_start)
    report = {}
    with pytest.raises(ValueError, match="original_reader_start_failure"):  # noqa: SIM117
        with companion.Fixture(tmp_path, report):
            pytest.fail("unreachable")
    cleanup = report["fixture_cleanup"]
    assert cleanup["exit_code"] is not None
    assert cleanup["reader_started"] is False


def test_review_requested_edit_must_match_entire_returned_analysis():
    before = {"meeting": {"ai_analysis": {"summary": "원래"}}}
    changed = {"summary_version": 2, "summary": "요청한 문장", "summary_claims": [], "items": [{"status": "done"}]}
    response = {"meeting": {"ai_analysis": before["meeting"]["ai_analysis"],
                            "provenance": "user_edited", "analysis": copy.deepcopy(changed)}}
    companion.verify_edit_response(before, changed, response)
    response["meeting"]["analysis"]["summary"] = "무시된 편집"
    with pytest.raises(companion.CheckFailure, match="edit_analysis_mismatch"):
        companion.verify_edit_response(before, changed, response)


@pytest.mark.parametrize("denied", [None, "shared-read", "search", "tasks"])
def test_review_member_requires_shared_positive_control(denied):
    import httpx
    def transport(request):
        path = request.url.path
        if path.startswith(("/api/meetings/", "/api/documents/")):
            if path.endswith("/private") or denied == "shared-read":
                return httpx.Response(404, json={"detail": "not_found"})
            return httpx.Response(200, json={"id": "shared", "document": {"id": "shared"}})
        if path == "/api/knowledge/search":
            return httpx.Response(200, json={"results": [] if denied == "search" else [{"document_id": "shared"}]})
        return httpx.Response(200, json={"items": [] if denied == "tasks" else [{"meeting_id": "shared"}]})
    with httpx.Client(base_url="http://test", transport=httpx.MockTransport(transport)) as client:
        if denied:
            with pytest.raises((companion.CheckFailure, AssertionError)):
                companion.member_denied(client, "private", "shared", "workspace")
        else:
            companion.member_denied(client, "private", "shared", "workspace")


def test_review_loopback_environment_is_explicit_and_restored(monkeypatch):
    monkeypatch.setenv("SERVER_ADDRESS", "0.0.0.0")
    with companion.child_environment():
        assert os.environ["SERVER_ADDRESS"] == "127.0.0.1"
    assert os.environ["SERVER_ADDRESS"] == "0.0.0.0"
    with pytest.raises(ValueError), companion.child_environment():
        assert os.environ["SERVER_ADDRESS"] == "127.0.0.1"
        raise ValueError("body")
    assert os.environ["SERVER_ADDRESS"] == "0.0.0.0"

@pytest.mark.parametrize("inherited", [None, "-Dunsafe=true -javaagent:untrusted.jar"])
def test_encoding_scope_replaces_options_and_restores(monkeypatch, inherited):
    if inherited is None:
        monkeypatch.delenv("JDK_JAVA_OPTIONS", raising=False)
    else:
        monkeypatch.setenv("JDK_JAVA_OPTIONS", inherited)
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-Dunsafe=true")
    monkeypatch.setenv("_JAVA_OPTIONS", "-Xmx99g")
    monkeypatch.setenv("SPRING_APPLICATION_JSON", '{"server.address":"0.0.0.0"}')
    monkeypatch.setenv("SERVER_ADDRESS", "0.0.0.0")
    before = dict(os.environ)
    for fail in (False, True):
        try:
            with companion.child_environment():
                assert os.environ["JDK_JAVA_OPTIONS"] == "-Dstdout.encoding=UTF-8 -Dstderr.encoding=UTF-8"
                assert "JAVA_TOOL_OPTIONS" not in os.environ and "_JAVA_OPTIONS" not in os.environ
                assert "SPRING_APPLICATION_JSON" not in os.environ
                assert os.environ["SERVER_ADDRESS"] == "127.0.0.1"
                if fail:
                    raise ValueError("original body failure")
        except ValueError:
            assert fail
        assert dict(os.environ) == before


@pytest.mark.parametrize("utf8_mode, locale_encoding, stdout_encoding, accepted", [
    (1, "cp949", "cp949", True), (0, "UTF8", "cp949", True), (0, "cp949", "UTF-8", False),
])
def test_encoding_preflight_uses_subprocess_semantics_no_process_on_rejection(
        monkeypatch, tmp_path, utf8_mode, locale_encoding, stdout_encoding, accepted):
    import locale
    from types import SimpleNamespace
    monkeypatch.setattr(companion, "ROOT", tmp_path)
    monkeypatch.setattr(companion, "FIXED", {})
    # stdout is deliberately opposite: it is not subprocess's default text decoder.
    monkeypatch.setattr(companion, "sys", SimpleNamespace(
        flags=SimpleNamespace(utf8_mode=utf8_mode), stdout=SimpleNamespace(encoding=stdout_encoding)), raising=False)
    monkeypatch.setattr(locale, "getencoding", lambda: locale_encoding)
    jar = tmp_path / "synthetic.jar"
    jar.write_bytes(b"synthetic jar metadata only")
    called = []
    monkeypatch.setattr(companion, "exercise", lambda *args: called.append("exercise-fake"))
    def forbidden_process(*args, **kwargs):
        pytest.fail("preflight regression must never launch a process")
    monkeypatch.setattr(companion.subprocess, "Popen", forbidden_process)
    report = companion.run(jar, tmp_path / ".local" / "attempt", expected_jar_sha256=companion.digest(jar))
    if accepted:
        assert report["status"] == "passed" and called == ["exercise-fake"]
        assert report["subprocess_text_encoding"] == "utf-8"
    else:
        assert report["status"] == "failed" and not called
        assert report["first_failure"]["code"] == "subprocess_text_requires_python_X_utf8"
        assert report["java_lifecycles"] == []


# Scoped capture regressions use injected collaborators only, never Java or Node.
def capture_collaborator(monkeypatch, tmp_path, *, code=1, identity_error=None, absence_error=None):
    from types import SimpleNamespace

    from scripts import verify_java_service as helper
    calls = []
    handle = SimpleNamespace(pid=123456, returncode=code, poll=lambda: code)
    delegate_run = object()
    original = SimpleNamespace(run=delegate_run, Popen=lambda *a, **k: calls.append((a, k)) or handle)
    monkeypatch.setattr(helper, "subprocess", original)
    lookups = []
    def process(pid):
        assert pid == handle.pid
        lookups.append(pid)
        if len(lookups) == 1:
            if identity_error:
                raise identity_error(pid)
            return SimpleNamespace(create_time=lambda: 12.5)
        if absence_error:
            raise absence_error(pid)
        raise companion.psutil.NoSuchProcess(pid)
    monkeypatch.setattr(companion.psutil, "Process", process)
    observer = companion.JavaObservation(tmp_path / "approved.jar")
    command = ["java", "-jar", str(tmp_path / "approved.jar"), "--server.port=1234"]
    return helper, original, observer, command, handle, calls, lookups


def test_capture_exact_forwarding_identical_handle_global_untouched(monkeypatch, tmp_path):
    helper, original, observer, command, handle, calls, lookups = capture_collaborator(monkeypatch, tmp_path)
    global_popen = subprocess.Popen
    observer.start()
    try:
        assert helper.subprocess.run is original.run
        marker = object()
        assert helper.subprocess.Popen(command, stdout=marker, env={"safe": "value"}) is handle
        assert calls == [((command,), {"stdout": marker, "env": {"safe": "value"}})]
        assert calls[0][0][0] is command
        assert subprocess.Popen is global_popen
    finally:
        result = observer.finish()
    assert helper.subprocess is original and subprocess.Popen is global_popen
    assert result["all_exits_observed"] and result["reference_restored"]
    assert result["identities"][0]["exit_code"] == 1
    assert lookups == [handle.pid, handle.pid]  # no child inventory or waiter


@pytest.mark.parametrize("fault", ["missing", "multiple", "mismatch", "unknown-exit", "identity", "absence", "alive"])
def test_capture_uncertain_ownership_or_exit_never_passes(monkeypatch, tmp_path, fault):
    helper, original, observer, command, handle, calls, lookups = capture_collaborator(
        monkeypatch, tmp_path, code=None if fault == "unknown-exit" else 0,
        identity_error=companion.psutil.NoSuchProcess if fault == "identity" else None,
        absence_error=companion.psutil.AccessDenied if fault == "absence" else None)
    if fault == "alive":
        from types import SimpleNamespace
        clock = [0.0]
        monkeypatch.setattr(companion, "time", SimpleNamespace(
            monotonic=lambda: clock[0], sleep=lambda delay: clock.__setitem__(0, clock[0] + delay)))
        monkeypatch.setattr(companion.psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: 12.5))
    observer.start()
    try:
        if fault == "mismatch":
            with pytest.raises(companion.CheckFailure, match="java_capture_target_mismatch"):
                helper.subprocess.Popen(["java", "-jar", "wrong.jar"])
        elif fault != "missing":
            assert helper.subprocess.Popen(command) is handle
            if fault == "multiple":
                with pytest.raises(companion.CheckFailure, match="java_capture_multiple"):
                    helper.subprocess.Popen(command)
    finally:
        result = observer.finish()
    assert helper.subprocess is original
    assert not result["all_exits_observed"] or result["observation_errors"]
    assert len(calls) == (0 if fault in ("missing", "mismatch") else 1)
    if fault == "identity":
        assert result["observation_errors"] and len(lookups) == 1


def test_capture_pid_reuse_is_absence_without_terminating_anything(monkeypatch, tmp_path):
    from types import SimpleNamespace
    helper, original, observer, command, _handle, _calls, _lookups = capture_collaborator(monkeypatch, tmp_path)
    times = iter([12.5, 99.0])
    monkeypatch.setattr(companion.psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: next(times)))
    observer.start()
    helper.subprocess.Popen(command)
    result = observer.finish()
    assert result["all_exits_observed"] and helper.subprocess is original


@pytest.mark.parametrize("fault", ["popen", "startup", "body", "identity"])
def test_capture_real_helper_scope_restores_on_failures(monkeypatch, tmp_path, fault):
    helper, original, _observer, command, handle, _calls, _lookups = capture_collaborator(
        monkeypatch, tmp_path, identity_error=companion.psutil.AccessDenied if fault == "identity" else None)
    cleanup = []
    if fault == "popen":
        def fail(*args, **kwargs):
            raise ValueError("original_popen")
        original.Popen = fail
    @contextmanager
    def fake_server(*args):
        owned = helper.subprocess.Popen(command)
        try:
            if fault == "startup":
                raise ValueError("original_startup")
            yield "client"
        finally:
            assert owned is handle
            cleanup.append("unchanged helper cleanup")
    monkeypatch.setattr(companion, "java_server", fake_server)
    report = {"java_lifecycles": []}
    error_type = companion.CheckFailure if fault == "identity" else ValueError
    expected = "java_exit_observation_failed" if fault == "identity" else "original_" + fault
    with pytest.raises(error_type, match=expected):  # noqa: SIM117
        with companion.observed_java(tmp_path / "approved.jar", tmp_path / "db", tmp_path, "test", report):
            if fault == "body":
                raise ValueError("original_body")
    assert helper.subprocess is original
    assert cleanup == ([] if fault == "popen" else ["unchanged helper cleanup"])


def test_capture_reentry_cross_thread_and_reference_conflict(monkeypatch, tmp_path):
    import threading
    helper, original, observer, command, _handle, calls, _lookups = capture_collaborator(monkeypatch, tmp_path)
    observer.start()
    with pytest.raises(companion.CheckFailure, match="java_capture_scope_busy"):
        companion.JavaObservation(tmp_path / "approved.jar").start()
    failures = []
    def other_thread():
        try:
            companion.JavaObservation(tmp_path / "approved.jar").start()
        except companion.CheckFailure as error:
            failures.append(str(error))
        try:
            helper.subprocess.Popen(command)
        except companion.CheckFailure as error:
            failures.append(str(error))
    thread = threading.Thread(target=other_thread)
    thread.start()
    thread.join()
    assert failures == ["java_capture_scope_busy", "java_capture_cross_thread"] and not calls
    helper.subprocess.Popen(command)
    helper.subprocess = object()
    result = observer.finish()
    assert helper.subprocess is original
    assert "java_capture_reference_conflict" in result["observation_errors"]
    assert "java_capture_cross_thread" in result["observation_errors"]
    # A failed nested start must not release the outer owner's lock; finish must.
    next_observer = companion.JavaObservation(tmp_path / "approved.jar")
    next_observer.start()
    next_observer.finish()
    assert helper.subprocess is original


@pytest.mark.parametrize("created", [None, float("nan"), 0])
def test_capture_invalid_creation_identity_is_not_absence(monkeypatch, tmp_path, created):
    from types import SimpleNamespace
    helper, original, observer, command, handle, _calls, _lookups = capture_collaborator(monkeypatch, tmp_path)
    monkeypatch.setattr(companion.psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: created))
    observer.start()
    assert helper.subprocess.Popen(command) is handle
    result = observer.finish()
    assert not result["all_exits_observed"] and result["observation_errors"]
    assert helper.subprocess is original


@pytest.mark.parametrize("fault", [None, "poll", "conflict-body"])
def test_capture_context_success_or_failure_preserves_scope(monkeypatch, tmp_path, fault):
    helper, original, _observer, command, handle, _calls, _lookups = capture_collaborator(monkeypatch, tmp_path)
    global_popen = subprocess.Popen
    if fault == "poll":
        handle.returncode = None
        def fail_poll():
            raise OSError("test-only poll failure")
        handle.poll = fail_poll
    @contextmanager
    def fake_server(*args):
        assert helper.subprocess.Popen(args=command) is handle
        yield "client"
    monkeypatch.setattr(companion, "java_server", fake_server)
    report = {"java_lifecycles": []}
    def scope():
        with companion.observed_java(tmp_path / "approved.jar", tmp_path / "db", tmp_path, "test", report):
            assert subprocess.Popen is global_popen
            if fault == "conflict-body":
                helper.subprocess = object()
                raise ValueError("original body")
    if fault is None:
        scope()
        assert report["java_lifecycles"][0]["all_exits_observed"]
    elif fault == "poll":
        with pytest.raises(companion.CheckFailure, match="java_exit_observation_failed"):
            scope()
    else:
        with pytest.raises(ValueError, match="original body"):
            scope()
        assert report["java_lifecycles"][0]["observation_errors"] == ["java_capture_reference_conflict"]
    assert helper.subprocess is original and subprocess.Popen is global_popen


def test_capture_uncertain_current_creation_time_is_not_pid_reuse(monkeypatch, tmp_path):
    from types import SimpleNamespace
    helper, original, observer, command, _handle, _calls, _lookups = capture_collaborator(monkeypatch, tmp_path)
    times = iter([12.5, None])
    monkeypatch.setattr(companion.psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: next(times)))
    observer.start()
    helper.subprocess.Popen(command)
    result = observer.finish()
    assert not result["all_exits_observed"] and result["observation_errors"]
    assert helper.subprocess is original


# OBS-R1: deterministic Windows retained/delayed process-identity counterexamples.
def delayed_capture(monkeypatch, tmp_path, *, external=False, delay=0, never=False, code=1):
    import weakref
    from types import SimpleNamespace

    from scripts import verify_java_service as helper
    clock = {"now": 0.0, "sleeps": [], "reads": 0}
    def monotonic():
        clock["reads"] += 1
        assert clock["reads"] < 2000, "absence deadline was reset or polling never stopped"
        return clock["now"]
    def sleep(seconds):
        assert seconds > 0
        clock["sleeps"].append(seconds)
        clock["now"] += seconds
    monkeypatch.setattr(companion, "time", SimpleNamespace(monotonic=monotonic, sleep=sleep))
    references, owners = [], []
    class Handle:
        pid = 987654
        returncode = code
        def poll(self):
            return code
    def create(*args, **kwargs):
        handle = Handle()
        references.append(weakref.ref(handle))
        if external:
            owners.append(handle)
        return handle
    original = SimpleNamespace(Popen=create)
    monkeypatch.setattr(helper, "subprocess", original)
    def process(pid):
        assert pid == Handle.pid
        if references[0]() is not None or never or clock["now"] < delay:
            return SimpleNamespace(create_time=lambda: 12.5)
        raise companion.psutil.NoSuchProcess(pid)
    monkeypatch.setattr(companion.psutil, "Process", process)
    observer = companion.JavaObservation(tmp_path / "approved.jar")
    command = ["java", "-jar", str(tmp_path / "approved.jar")]
    return helper, original, observer, command, references, owners, clock


def test_retained_handle_released_before_identity_check(monkeypatch, tmp_path):
    helper, original, observer, command, references, _owners, clock = delayed_capture(monkeypatch, tmp_path)
    observer.start()
    helper.subprocess.Popen(command)
    result = observer.finish()
    assert references[0]() is None  # also catches a retained loop local/zip iterator
    assert result["captured_handles"] == 1 and result["all_exits_observed"]
    assert result["identities"][0]["exit_code"] == 1
    assert result["identities"][0]["create_time"] == 12.5
    assert not observer.handles and not clock["sleeps"]
    assert helper.subprocess is original


@pytest.mark.parametrize("external", [True, False])
def test_retained_external_or_persistent_identity_times_out_once(monkeypatch, tmp_path, external):
    helper, original, observer, command, references, owners, clock = delayed_capture(
        monkeypatch, tmp_path, external=external, never=not external)
    observer.start()
    helper.subprocess.Popen(command)
    result = observer.finish()
    assert not result["all_exits_observed"]
    assert "capture_absence_timeout" in result["observation_errors"]
    assert clock["now"] == pytest.approx(5.0) and len(clock["sleeps"]) > 1
    assert result["captured_handles"] == 1 and not observer.handles
    assert bool(owners) == external and (references[0]() is not None) == external
    assert helper.subprocess is original


def test_retained_identity_disappears_after_bounded_delay(monkeypatch, tmp_path):
    helper, original, observer, command, references, _owners, clock = delayed_capture(
        monkeypatch, tmp_path, delay=0.06)
    observer.start()
    helper.subprocess.Popen(command)
    result = observer.finish()
    assert result["all_exits_observed"] and references[0]() is None
    assert 0.06 <= clock["now"] < 5 and len(clock["sleeps"]) >= 3
    assert helper.subprocess is original


def test_retained_unknown_exit_is_not_released_or_accepted(monkeypatch, tmp_path):
    helper, original, observer, command, references, _owners, clock = delayed_capture(
        monkeypatch, tmp_path, code=None)
    observer.start()
    helper.subprocess.Popen(command)
    result = observer.finish()
    assert not result["all_exits_observed"] and references[0]() is not None
    assert result["captured_handles"] == 1 and observer.handles
    assert not clock["sleeps"] and helper.subprocess is original


def test_retained_timeout_keeps_original_body_failure(monkeypatch, tmp_path):
    helper, original, _observer, command, _references, _owners, clock = delayed_capture(
        monkeypatch, tmp_path, external=True)
    @contextmanager
    def server(*args):
        helper.subprocess.Popen(command)
        yield "client"
    monkeypatch.setattr(companion, "java_server", server)
    report = {"java_lifecycles": []}
    with pytest.raises(ValueError, match="original body"):  # noqa: SIM117
        with companion.observed_java(tmp_path / "approved.jar", tmp_path / "db", tmp_path, "test", report):
            raise ValueError("original body")
    row = report["java_lifecycles"][0]
    assert "capture_absence_timeout" in row["observation_errors"]
    assert row["first_failure"]["stage"] == "body"
    assert clock["now"] == pytest.approx(5) and helper.subprocess is original
