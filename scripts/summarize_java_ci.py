"""Bounded, allowlisted Java CI diagnostics. Never executes Maven or a JVM."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import time
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_FILE = 4 * 1024**2
MAX_TOTAL = 16 * 1024**2
MAX_FILES = 128
MAX_ENTRIES = 256
MAX_PUBLIC = 1024**2
MAX_STACK = 512 * 1024
LIMITS = {"junit_method_seconds": 120, "surefire_fork_seconds": 300,
          "maven_step_minutes": 10, "java_job_minutes": 30,
          "projection_step_minutes": 1, "upload_step_minutes": 1}
STATES = "NEW|RUNNABLE|BLOCKED|WAITING|TIMED_WAITING|TERMINATED"
THREAD = re.compile(r'^"[^\r\n]{0,512}"(?: daemon)? prio=\d{1,3} Id=\d{1,12} (' + STATES + r')$')
HEADER = re.compile(r'^Thread "[^\r\n]{0,512}"(?: daemon)? prio=\d{1,3} Id=\d{1,12} (?:'
                    + STATES + r') will be interrupted\.$')
FRAME = re.compile(r'^\s+at (?:(?:[A-Za-z0-9_.@-]+/|app//))?'
                   r'((?:java|javax|jdk|sun|org\.junit|org\.apache\.maven\.surefire|'
                   r'org\.apache\.maven|io\.doctrail)\.[A-Za-z0-9_.$]+)\.'
                   r'([A-Za-z_$][A-Za-z0-9_$]*|<init>|<clinit>)'
                   r'\((?:[A-Za-z_$][A-Za-z0-9_$]*\.java:(\d{1,9})|(Native Method|Unknown Source))\)$')
PHASE = re.compile(r'^\[INFO\] --- [A-Za-z0-9_.-]{1,80}:[A-Za-z0-9_.-]{1,80}:'
                   r'(resources|compile|testResources|testCompile|test|jar|repackage|verify|install|clean)\s')


def unlinked(path):
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            return False
    return True


class Reader:
    def __init__(self):
        self.remaining = MAX_TOTAL
        self.records = []
        self.issues = []

    def read(self, path, kind):
        record = {"id": len(self.records) + 1, "kind": kind, "status": "unread",
                  "size_bytes": None, "sha256": None}
        self.records.append(record)
        if not unlinked(path):
            record["status"] = "linked_rejected"
            self.issues.append("linked_input")
            return None
        try:
            before = path.stat()
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("not_regular")
            with path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                    raise ValueError("changed_identity")
                data = stream.read(min(MAX_FILE, self.remaining))
                after = os.fstat(stream.fileno())
            self.remaining -= len(data)
            record["size_bytes"] = before.st_size
            record["bytes_read"] = len(data)
            digest = hashlib.sha256(data).hexdigest()
            stable = (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
            complete = len(data) == before.st_size and stable
            record["status"] = "complete" if complete else "truncated_or_changed"
            record["sha256" if complete else "read_prefix_sha256"] = digest
            if not complete:
                self.issues.append("input_truncated_or_changed")
            return data
        except FileNotFoundError:
            record["status"] = "missing"
            self.issues.append("missing_input")
        except (OSError, ValueError):
            record["status"] = "unreadable"
            self.issues.append("unreadable_input")
        return None


def numeric(value, *, integer=False, maximum=86400):
    if not isinstance(value, str) or len(value) > 32:
        raise ValueError("numeric")
    if integer and not re.fullmatch(r"\d{1,15}", value):
        raise ValueError("integer")
    number = int(value) if integer else float(value)
    if not math.isfinite(number) or not 0 <= number <= maximum:
        raise ValueError("range")
    return number


def suites(data):
    text = data.decode("utf-8")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("xml_declaration")
    root = ET.fromstring(text)
    if root.tag not in ("testsuite", "testsuites"):
        raise ValueError("xml_root")
    nodes = [root] if root.tag == "testsuite" else list(root)
    if not nodes or len(nodes) > 128 or any(node.tag != "testsuite" for node in nodes):
        raise ValueError("xml_suites")
    result = []
    for node in nodes:
        counts = {key: numeric(node.attrib.get(key, "0" if key == "skipped" else None),
                              integer=True, maximum=100000)
                  for key in ("tests", "failures", "errors", "skipped")}
        if sum(counts[k] for k in ("failures", "errors", "skipped")) > counts["tests"]:
            raise ValueError("xml_counts")
        result.append({**counts, "seconds": numeric(node.attrib.get("time"))})
    return result


def thread_stacks(data):
    """Recognize JUnit's pre-interrupt dump, not arbitrary exception stack traces."""
    active, current, threads, omitted, lines = False, False, 0, 0, []
    for raw in data.decode("utf-8", errors="replace").splitlines():
        if HEADER.fullmatch(raw):
            active, current = True, False
            continue
        if not active:
            continue
        match = THREAD.fullmatch(raw)
        if match:
            if threads >= 128:
                omitted += 1
                break
            threads += 1
            lines.append(f"thread {threads}: {match[1]}\n")
            current = True
            continue
        match = FRAME.fullmatch(raw) if current else None
        if match:
            # No file names, module paths, thread names, messages or display names.
            location = "line:" + match[3] if match[3] else match[4]
            lines.append(f"  at {match[1]}.{match[2]}({location})\n")
        elif current and raw.lstrip().startswith("at "):
            # Unsupported frame syntax or namespace: omit it, retain the dump boundary.
            omitted += 1
        elif raw.strip():
            active, current = False, False
    return "".join(lines), threads, omitted


def metadata(start, end, outcome):
    result = {"run_id": None, "attempt": None, "head": None, "started_at": None,
              "finished_at": None, "exit_code": None, "termination": "termination_unobserved",
              "step_outcome": outcome, "valid": False}
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_metadata_key")
            result[key] = value
        return result
    try:
        first = json.loads(start, object_pairs_hook=unique)
        if not isinstance(first, dict) or set(first) != {"run_id", "attempt", "head", "started_at"}:
            return result
        run = numeric(first["run_id"], integer=True, maximum=10**15)
        attempt = numeric(first["attempt"], integer=True, maximum=100000)
        head = first["head"]
        started = first["started_at"]
        if (run < 1 or attempt < 1 or not isinstance(head, str) or not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", head)
                or type(started) not in (int, float) or not math.isfinite(started) or not 0 < started < 4102444800):
            return result
        result.update(run_id=run, attempt=attempt, head=head, started_at=started)
        if end is None:
            return result
        last = json.loads(end, object_pairs_hook=unique)
        if not isinstance(last, dict):
            return result
        code, finished = last.get("exit_code"), last.get("finished_at")
        if (set(last) != {"exit_code", "finished_at"} or type(code) is not int or not 0 <= code <= 255
                or type(finished) not in (int, float) or not math.isfinite(finished)
                or not started <= finished < 4102444800):
            return result
        result.update(exit_code=code, finished_at=finished, termination="exit_observed",
                      valid=(outcome == "success" and code == 0) or (outcome == "failure" and code != 0))
    except (TypeError, ValueError, KeyError):
        pass
    return result


def summarize(raw_dir, reports_dir, outcome):
    reader = Reader()
    start = reader.read(raw_dir / "start.json", "start_metadata")
    end = reader.read(raw_dir / "exit.json", "exit_metadata")
    info = metadata(start, end, outcome)
    report = {"schema_version": 1, "metadata": info, "configured_limits": LIMITS,
              "limits_basis": "Fixed CI policy; not inferred from logs or proof of enforcement",
              "observed_at": time.time(), "maven_phases": [], "suites": [],
              "recognized_JUnit_dump_threads": 0, "stack_omission_events": 0, "surefire_dump_files": 0,
              "raw_files": reader.records, "issues": reader.issues}
    if not info["valid"]:
        reader.issues.append("metadata_incomplete_or_inconsistent")
    candidates = [(raw_dir / "maven.log", "maven_log")]
    if not unlinked(reports_dir):
        reader.issues.append("linked_reports_directory")
    else:
        try:
            with os.scandir(reports_dir) as entries:
                for count, entry in enumerate(entries):
                    if count >= MAX_ENTRIES or len(candidates) >= MAX_FILES:
                        reader.issues.append("directory_entry_limit")
                        break
                    suffix = Path(entry.name).suffix
                    if suffix in (".xml", ".txt", ".dump", ".dumpstream"):
                        candidates.append((Path(entry.path), {".xml": "surefire_xml", ".txt": "surefire_output",
                                           ".dump": "surefire_dump", ".dumpstream": "surefire_dumpstream"}[suffix]))
        except OSError:
            reader.issues.append("reports_directory_missing_or_unreadable")
    stack = ""
    for path, kind in candidates:
        data = reader.read(path, kind)
        if data is None:
            continue
        if kind == "surefire_dump":
            report["surefire_dump_files"] += 1
        if kind == "surefire_xml":
            try:
                rows = suites(data)
                if len(report["suites"]) + len(rows) > 256:
                    raise ValueError("suite_limit")
                offset = len(report["suites"])
                report["suites"].extend({"suite": offset + i + 1, **row} for i, row in enumerate(rows))
            except (ET.ParseError, ValueError):
                reader.issues.append("xml_invalid_or_incomplete")
        else:
            if kind == "maven_log":
                for line in data.decode("utf-8", errors="replace").splitlines():
                    match = PHASE.match(line)
                    if match and match[1] not in report["maven_phases"]:
                        report["maven_phases"].append(match[1])
            safe, count, omitted = thread_stacks(data)
            report["recognized_JUnit_dump_threads"] += count
            report["stack_omission_events"] += omitted
            if omitted:
                reader.issues.append("unsupported_stack_frames_or_thread_limit")
            if safe:
                addition = f"dump {reader.records[-1]['id']}\n" + safe
                if len((stack + addition).encode()) <= MAX_STACK:
                    stack += addition
                else:
                    reader.issues.append("safe_stack_output_truncated")
    if not report["suites"]:
        reader.issues.append("no_complete_suite_report")
    if info["exit_code"] == 0 and any(row["failures"] or row["errors"] for row in report["suites"]):
        reader.issues.append("exit_and_suite_results_inconsistent")
    report["issues"] = sorted(set(reader.issues))
    report["status"] = "complete" if not report["issues"] else "partial"
    return report, stack


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--step-outcome", choices=("success", "failure", "cancelled", "skipped"), required=True)
    args = parser.parse_args(argv)
    created = False
    try:
        if not unlinked(args.output):
            raise ValueError("linked_output")
        args.output.mkdir(parents=True, exist_ok=False)
        created = True
        report, stack = summarize(args.raw_dir, args.reports_dir, args.step_outcome)
        encoded = (json.dumps(report, ensure_ascii=True, indent=2) + "\n").encode()
        if len(encoded) + len(stack.encode()) > MAX_PUBLIC:
            report = {"schema_version": 1, "status": "partial", "issues": ["public_output_limit"]}
            encoded, stack = (json.dumps(report) + "\n").encode(), ""
        (args.output / "safe-report.json").write_bytes(encoded)
        (args.output / "safe-thread-stacks.txt").write_text(stack, encoding="utf-8", newline="\n")
        return 0 if report["status"] == "complete" else 1
    except Exception:  # noqa: BLE001 - diagnostics never print raw exception details
        # Preserve a safe incomplete result only in a directory created by this call.
        try:
            if created and args.output.is_dir() and unlinked(args.output) and not any(args.output.iterdir()):
                (args.output / "safe-report.json").write_text(
                    '{"schema_version":1,"status":"partial","issues":["projection_failed"]}\n',
                    encoding="utf-8")
                (args.output / "safe-thread-stacks.txt").write_text("", encoding="utf-8")
        except OSError:
            pass
        print("java_ci_safe_projection_failed")
        return 1



if __name__ == "__main__":
    raise SystemExit(main())
