"""Synthetic privacy/limit boundaries; never launches Java, Maven or network."""
import json
from pathlib import Path

import pytest

from scripts import summarize_java_ci as safe

SECRET = "PRIVATE_SENTINEL_password_TOKEN"


def fixture(tmp_path, code=0):
    raw, reports = tmp_path / "raw", tmp_path / "reports"
    raw.mkdir()
    reports.mkdir()
    (raw / "start.json").write_text(json.dumps({"run_id": "40273275050", "attempt": "1",
        "head": "a" * 40, "started_at": 1000}), encoding="utf-8")
    (raw / "exit.json").write_text(json.dumps({"exit_code": code, "finished_at": 1001}), encoding="utf-8")
    (raw / "maven.log").write_text("[INFO] --- compiler:3.14.0:compile (private) @ " + SECRET + " ---\n", encoding="utf-8")
    (reports / (SECRET + ".xml")).write_text(
        '<testsuite name="' + SECRET + '" tests="2" failures="' + ('1' if code else '0') + '" errors="0" skipped="0" time="0.2">'
        '<properties><property name="password" value="' + SECRET + '"/></properties>'
        '<testcase name="' + SECRET + '"><failure message="' + SECRET + '">' + SECRET + '</failure></testcase>'
        '<system-out>' + SECRET + '</system-out><system-err>' + SECRET + '</system-err></testsuite>', encoding="utf-8")
    return raw, reports


def dump():
    return (f'Thread "{SECRET}" prio=5 Id=77 RUNNABLE will be interrupted.\n'
            f'"{SECRET}" daemon prio=5 Id=78 WAITING\n'
            '\tat java.base@21.0.12/java.lang.Thread.sleep0(Native Method)\n'
            '\tat io.doctrail.ExampleTest.hangs(ExampleTest.java:42)\n'
            f'\tat io.doctrail.ExampleTest.hangs(C:/{SECRET}/ExampleTest.java:43)\n'
            f'Exception: {SECRET}\n')


def test_allowlisted_output_hides_all_names_and_contents(tmp_path):
    raw, reports = fixture(tmp_path, 1)
    (reports / (SECRET + "-output.txt")).write_text(dump(), encoding="utf-8")
    (reports / (SECRET + ".dumpstream")).write_text(SECRET, encoding="utf-8")
    report, stacks = safe.summarize(raw, reports, "failure")
    public = json.dumps(report) + stacks
    assert SECRET not in public and str(tmp_path) not in public
    assert report["status"] == "partial" and report["metadata"]["exit_code"] == 1
    assert report["stack_omission_events"] == 1
    assert report["suites"] == [{"suite": 1, "tests": 2, "failures": 1, "errors": 0, "skipped": 0, "seconds": .2}]
    assert report["maven_phases"] == ["compile"]
    assert 'thread 1: WAITING' in stacks and 'ExampleTest.hangs(line:42)' in stacks
    assert 'line:43' not in stacks and 'ExampleTest.java' not in stacks
    assert all(r["sha256"] for r in report["raw_files"])


def test_arbitrary_exception_stacks_not_treated_as_junit_dump():
    stacks, count, omitted = safe.thread_stacks(('java.lang.IllegalStateException: ' + SECRET
        + '\n\tat io.doctrail.ExampleTest.fail(ExampleTest.java:42)\n').encode())
    assert stacks == "" and count == omitted == 0


@pytest.mark.parametrize("bad", ["missing", "duplicate", "wrong_type", "wrong_outcome", "bad_head"])
def test_metadata_never_turns_missing_or_invalid_exit_into_success(tmp_path, bad):
    raw, reports = fixture(tmp_path)
    if bad == "missing":
        (raw / "exit.json").unlink()
    elif bad == "duplicate":
        (raw / "exit.json").write_text('{"exit_code":1,"exit_code":0,"finished_at":1001}', encoding="utf-8")
    elif bad == "wrong_type":
        (raw / "exit.json").write_text('{"exit_code":false,"finished_at":1001}', encoding="utf-8")
    elif bad == "bad_head":
        data = json.loads((raw / "start.json").read_text())
        data["head"] = "a" * 41
        (raw / "start.json").write_text(json.dumps(data), encoding="utf-8")
    report, _ = safe.summarize(raw, reports, "failure" if bad == "wrong_outcome" else "success")
    assert report["status"] == "partial" and not report["metadata"]["valid"]
    if bad == "missing":
        assert report["metadata"]["exit_code"] is None
        assert report["metadata"]["termination"] == "termination_unobserved"


@pytest.mark.parametrize("xml", ['<testsuite', '<!DOCTYPE x [<!ENTITY e "EXPAND">]><testsuite/>',
    '<testsuite tests="2" failures="3" errors="0" time="1"/>',
    '<testsuite tests="2" failures="0" errors="0" time="NaN"/>'])
def test_malformed_xml_is_partial_without_raw_echo(tmp_path, xml):
    raw, reports = fixture(tmp_path)
    (reports / (SECRET + ".xml")).write_text(xml, encoding="utf-8")
    report, _ = safe.summarize(raw, reports, "success")
    assert report["status"] == "partial" and "xml_invalid_or_incomplete" in report["issues"]
    assert xml not in json.dumps(report)


def test_suite_ids_are_anonymous_and_sequential(tmp_path):
    raw, reports = fixture(tmp_path)
    (reports / (SECRET + ".xml")).write_bytes(
        b'<testsuites><testsuite tests="1" failures="0" errors="0" time="1"/>'
        b'<testsuite tests="1" failures="0" errors="0" time="2"/></testsuites>')
    report, _ = safe.summarize(raw, reports, "success")
    assert report["status"] == "complete" and [row["suite"] for row in report["suites"]] == [1, 2]


def test_read_caps_hash_only_read_prefix_and_output_cap(tmp_path, monkeypatch):
    raw, reports = fixture(tmp_path)
    (raw / "maven.log").write_bytes(b"x" * 4000)
    monkeypatch.setattr(safe, "MAX_FILE", 512)
    monkeypatch.setattr(safe, "MAX_TOTAL", 1024)
    output = tmp_path / "safe"
    assert safe.main(["--raw-dir", str(raw), "--reports-dir", str(reports), "--output", str(output),
                      "--step-outcome", "success"]) == 1
    report = json.loads((output / "safe-report.json").read_text())
    log = next(r for r in report["raw_files"] if r["kind"] == "maven_log")
    assert log["status"] == "truncated_or_changed" and log["sha256"] is None
    assert log["read_prefix_sha256"] and sum(r.get("bytes_read", 0) for r in report["raw_files"]) <= 1024
    assert sum(p.stat().st_size for p in output.iterdir()) <= 1024**2
    assert safe.main(["--raw-dir", str(raw), "--reports-dir", str(reports), "--output", str(output),
                      "--step-outcome", "success"]) == 1


def test_linked_input_directory_is_not_read(tmp_path, monkeypatch):
    raw, reports = fixture(tmp_path)
    original = safe.unlinked
    monkeypatch.setattr(safe, "unlinked", lambda p: False if p == reports else original(p))
    report, stacks = safe.summarize(raw, reports, "success")
    assert "linked_reports_directory" in report["issues"] and not report["suites"] and not stacks


def test_safe_file_link_is_rejected_before_open(tmp_path, monkeypatch):
    raw, reports = fixture(tmp_path)
    path = raw / "maven.log"
    original = safe.unlinked
    monkeypatch.setattr(safe, "unlinked", lambda p: False if p == path else original(p))
    report, _ = safe.summarize(raw, reports, "success")
    row = next(r for r in report["raw_files"] if r["kind"] == "maven_log")
    assert row["status"] == "linked_rejected" and row["sha256"] is None


def test_workflow_bounds_and_only_two_safe_artifacts():
    text = (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for flag in ['-Dsurefire.timeout=300', '-Djunit.jupiter.execution.timeout.default=120s',
                 '-Djunit.jupiter.execution.timeout.thread.mode.default=same_thread',
                 '-Djunit.jupiter.execution.timeout.threaddump.enabled=true',
                 '-Dmaven.test.redirectTestOutputToFile=true']:
        assert flag in text
    block = text[text.index('      - name: Verify Java with bounded Maven'):text.index('      - run: uv sync')]
    assert 'timeout-minutes: 30' in text and 'timeout-minutes: 10' in block
    assert block.count('timeout-minutes: 1\n') == 2
    assert 'exit "$maven_exit"' in block and 'continue-on-error' not in block
    assert 'tee ' not in block and 'skipTests' not in block and 'retry' not in block
    upload = block[block.index('      - name: Preserve safe Maven diagnostics'):]
    assert '.local/java-ci-safe/safe-report.json' in upload and '.local/java-ci-safe/safe-thread-stacks.txt' in upload
    assert 'java-ci-private' not in upload and 'surefire-reports' not in upload and 'retention-days: 3' in upload



def test_directory_and_stack_caps_are_explicit(tmp_path, monkeypatch):
    raw, reports = fixture(tmp_path)
    (raw / "maven.log").write_text(dump(), encoding="utf-8")
    for i in range(5):
        (reports / (str(i) + ".txt")).write_text(SECRET, encoding="utf-8")
    monkeypatch.setattr(safe, "MAX_ENTRIES", 2)
    monkeypatch.setattr(safe, "MAX_STACK", 10)
    report, stacks = safe.summarize(raw, reports, "success")
    assert "directory_entry_limit" in report["issues"] and "safe_stack_output_truncated" in report["issues"]
    assert stacks == "" and len(report["raw_files"]) <= 5



def test_unsupported_frame_does_not_discard_next_anonymous_thread():
    data = dump().replace("Exception: " + SECRET,
        '"' + SECRET + '" prio=5 Id=90 RUNNABLE\n\tat java.lang.Thread.run(Thread.java:10)')
    stacks, count, omitted = safe.thread_stacks(data.encode())
    assert count == 2 and omitted == 1 and 'thread 2: RUNNABLE' in stacks
    assert SECRET not in stacks and 'line:43' not in stacks


@pytest.mark.parametrize("end", ["[]", "null"])
def test_non_object_metadata_is_safely_incomplete(tmp_path, end):
    raw, reports = fixture(tmp_path)
    (raw / "exit.json").write_text(end, encoding="utf-8")
    report, _ = safe.summarize(raw, reports, "success")
    assert not report["metadata"]["valid"] and report["metadata"]["exit_code"] is None


def test_unexpected_projection_error_has_only_safe_fallback(tmp_path, monkeypatch, capsys):
    output = tmp_path / "safe"
    def fail(*a):
        raise RuntimeError(SECRET)
    monkeypatch.setattr(safe, "summarize", fail)
    assert safe.main(["--raw-dir", str(tmp_path), "--reports-dir", str(tmp_path), "--output", str(output),
                      "--step-outcome", "failure"]) == 1
    assert SECRET not in capsys.readouterr().out
    assert json.loads((output / "safe-report.json").read_text())["issues"] == ["projection_failed"]


def test_utf16_entity_declaration_is_rejected_before_xml_parser(tmp_path):
    raw, reports = fixture(tmp_path)
    xml = '<!DOCTYPE testsuite [<!ENTITY e "2">]><testsuite tests="&e;" failures="0" errors="0" time="1"/>'
    (reports / (SECRET + ".xml")).write_bytes(xml.encode("utf-16"))
    report, _ = safe.summarize(raw, reports, "success")
    assert report["status"] == "partial"
    assert "xml_invalid_or_incomplete" in report["issues"]
    assert report["suites"] == []
