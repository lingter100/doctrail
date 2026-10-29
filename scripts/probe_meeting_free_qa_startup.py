"""Separately admitted startup-only diagnostic. No QA inputs or generation transport."""
from __future__ import annotations

import argparse
import ipaddress
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import httpx

from tools.free_qa import runner as r
from tools.free_qa.adapter import validate_props
from tools.free_qa.policy import (
    CANDIDATE,
    ContractError,
    canonical,
    digest_value,
    exact,
    need,
    parse,
    sha,
    thaw,
)

ID = "meeting-free-qa-startup-v2"
NAMESPACE = ".local/" + ID
TRUSTED_LOCK_FILE = NAMESPACE + "/trusted-lock.json"
CODE_FILES = (*r.CODE_FILES, "scripts/probe_meeting_free_qa_startup.py", "tests/test_meeting_free_qa_startup.py")
LIMITS = {"startup_seconds": 120, "cleanup_seconds": 5, "whole_seconds": 185,
          "props_requests": 1, "props_response_bytes": 1024**2, "completions": 0, "requested_tokens": 0,
          "startup_available_bytes": 8 * 1024**3, "native_rss_bytes": 6 * 1024**3,
          "available_bytes": 2 * 1024**3}


def verify_registration(path, expected_sha, *, root=ROOT):
    """Read-only public admission; never creates trust, registration, once or assets."""
    root = Path(root).resolve()
    path = Path(path).absolute()
    relative = path.relative_to(root).as_posix()
    need(Path(relative).parent.as_posix() == NAMESPACE + "/registrations", "startup_registration_namespace")
    raw = r.assets.small_bytes(r.bound_path(relative, root), 8 * 1024**2)
    need(sha(raw) == digest_value(expected_sha), "startup_registration_identity")
    registration_ref = {"file": relative, "sha256": expected_sha, "size_bytes": len(raw)}
    lock_raw = r.assets.small_bytes(r.bound_path(TRUSTED_LOCK_FILE, root), 8 * 1024**2)
    lock_ref = {"file": TRUSTED_LOCK_FILE, "sha256": sha(lock_raw), "size_bytes": len(lock_raw)}
    spec, lock = parse(raw), parse(lock_raw)
    exact(spec, "schema_version diagnostic model code limits once_sha256 output_dir", "startup_registration")
    exact(lock, "schema_version diagnostic registration_sha256 model_sha256 binding_sha256 runtime_sha256 code_sha256", "startup_trust")
    need(type(spec["schema_version"]) is int and spec["schema_version"] == 1
         and type(lock["schema_version"]) is int and lock["schema_version"] == 1
         and spec["diagnostic"] == lock["diagnostic"] == ID
         and lock["registration_sha256"] == expected_sha
         and canonical(spec["limits"]) == canonical(LIMITS), "startup_authority")
    need(sha(canonical(spec["model"])) == digest_value(lock["model_sha256"])
         and sha(canonical(spec["code"])) == digest_value(lock["code_sha256"]), "startup_trusted_closure")
    need(spec["model"]["id"] == CANDIDATE, "startup_model")
    need(isinstance(spec["code"], list) and len(spec["code"]) == len(CODE_FILES)
         and {row["file"] for row in spec["code"]} == set(CODE_FILES), "startup_code_closure")
    for row in spec["code"]:
        r.read_ref(row, root, metadata=False)
    admitted = r.admit_model(spec["model"], lock["binding_sha256"], lock["runtime_sha256"], root=root)
    once_sha = digest_value(spec["once_sha256"])
    need(spec["output_dir"] == NAMESPACE + "/runs/" + once_sha, "startup_output_namespace")
    output = r.bound_path(spec["output_dir"], root)
    need(not output.exists(), "startup_output_exists")
    return spec, admitted, output, (registration_ref, lock_ref)


def fetch_props(service, prepared, deadline, metrics, check, *, clock=time.monotonic, transport=None):
    """Only GET /props exists here. Count before send; no retry, redirects or proxy."""
    url = urlsplit(service.url)
    need(url.scheme == "http" and ipaddress.ip_address(url.hostname or "").is_loopback
         and url.port and not (url.username or url.password or url.query or url.fragment)
         and url.path in ("", "/"), "startup_url")
    need(isinstance(service.token, str) and 32 <= len(service.token) <= 256 and service.token.isascii()
         and all(33 <= ord(char) <= 126 for char in service.token), "startup_token")
    need(metrics["props_requests"] == 0, "startup_props_once")
    check()
    r.remaining(clock, deadline)
    with httpx.Client(base_url=service.url.rstrip("/"), trust_env=False, follow_redirects=False,
                      headers={"Authorization": "Bearer " + service.token, "Accept-Encoding": "identity"},
                      transport=transport) as client:
        check()
        timeout = min(5, r.remaining(clock, deadline))
        metrics["props_requests"] += 1
        try:
            with client.stream("GET", "/props", timeout=timeout) as response:
                need(response.status_code == 200, "startup_props_status")
                need(response.headers.get("content-encoding", "identity") == "identity", "startup_props_encoding")
                length = response.headers.get("content-length")
                need(length is None or (length.isdecimal() and int(length) <= LIMITS["props_response_bytes"]),
                     "startup_props_limit")
                body = bytearray()
                for chunk in response.iter_raw(chunk_size=16384):
                    check()
                    r.remaining(clock, deadline)
                    need(len(body) + len(chunk) <= LIMITS["props_response_bytes"], "startup_props_limit")
                    body.extend(chunk)
                check()
                r.remaining(clock, deadline)
                props = parse(bytes(body))
                need(isinstance(props, dict), "startup_props_object")
                validate_props(props, prepared)
                check()
                r.remaining(clock, deadline)
                metrics["props_valid"] = True
        except httpx.TimeoutException as error:
            raise ContractError("free_qa_startup_props_timeout") from error
        except httpx.HTTPError as error:
            raise ContractError("free_qa_startup_props_transport") from error


def record_failure(report, error):
    row = error if isinstance(error, dict) else r.safe_error(error)
    if report["first_failure"] is None:
        report["first_failure"] = row
    elif row != report["first_failure"] and row not in report["secondary_failures"]:
        report["secondary_failures"].append(row)
    report["status"] = "stopped"


def check_metadata(spec, admitted, fixed_refs, deadline, clock):
    model, policy, root = thaw(admitted.descriptor), admitted.policy, admitted.root
    refs = [*fixed_refs, *spec["code"], model["profile"], model["binding"],
            *(thaw(policy.reviewed[key]) for key in ("metadata_receipt", "review_receipt", "acquisition_gate")),
            *map(thaw, admitted.gate_refs)]
    for row in refs:
        r.remaining(clock, deadline)
        r.read_ref(row, root, metadata=False)
    r.remaining(clock, deadline)


def check_custody(spec, admitted, prepared, fixed_refs, deadline, clock):
    check_metadata(spec, admitted, fixed_refs, deadline, clock)
    model, policy = thaw(admitted.descriptor), admitted.policy
    if prepared is not None:
        r.check_prepared(prepared, policy, clock, deadline)
        for folder, refs in ((prepared.model_root, model["asset_files"]),
                             (prepared.runtime_root, policy.runtime["files"])):
            for row in refs:
                r.remaining(clock, deadline)
                r.check_ref(thaw(row), folder)
                r.remaining(clock, deadline)
        r.check_prepared(prepared, policy, clock, deadline)
    r.remaining(clock, deadline)


def run_startup(registration, expected_sha, once_sha, *, root=ROOT, clock=time.monotonic,
                launcher=r.launch_model, preparer=r.prepare_admitted_model, transport=None):
    """Explicit separate execution only; owner must perform fresh external process preflight."""
    started = clock()
    startup_deadline, whole_deadline = started + 120, started + 185
    spec, admitted, output, fixed_refs = verify_registration(registration, expected_sha, root=root)
    need(once_sha == spec["once_sha256"], "startup_explicit_once")
    r.remaining(clock, startup_deadline)
    with r.worker_lease(admitted.root / ".local" / "meeting-free-qa-startup.lock"):
        once_dir = r.bound_path(NAMESPACE + "/once", admitted.root)
        once_dir.mkdir(parents=True, exist_ok=True)
        # Registration and token reservations both survive every subsequent failure.
        once_refs = []
        for name in ("registration-" + expected_sha, "token-" + once_sha):
            path = once_dir / (name + ".json")
            data = canonical({"diagnostic": ID, "registration_sha256": expected_sha, "once_sha256": once_sha})
            with path.open("xb") as stream:
                stream.write(data)
            once_refs.append({"file": path.relative_to(admitted.root).as_posix(), "sha256": sha(data), "size_bytes": len(data)})
        output.parent.mkdir(parents=True, exist_ok=True)
        output.mkdir(exist_ok=False)
        metrics = {}
        report = {"diagnostic": ID, "status": "stopped", "registration_sha256": expected_sha,
                  "once_sha256": once_sha, "health_ready": False, "props_valid": False,
                  "props_requests": 0, "counts": {"completions": 0, "requested_tokens": 0},
                  "health_requests": "not_instrumented", "AI_quality": False,
                  "first_failure": None, "secondary_failures": [], "cleanup": metrics,
                  "bindings_unchanged": False, "retries": 0,
                  "external_process_preflight": "required_from_assigned_owner_not_measured_here",
                  "requires_external_terminal_custody": True}
        prepared = guard = None
        try:
            with r.diagnostic_phase(report, "asset_preparation", clock):
                prepared = preparer(admitted, startup_deadline, clock=clock)
            with r.diagnostic_phase(report, "prelaunch_bindings", clock):
                check_metadata(spec, admitted, (*fixed_refs, *once_refs), startup_deadline, clock)
                r.check_prepared(prepared, admitted.policy, clock, startup_deadline)
            with launcher(prepared, startup_deadline, metrics, clock=clock) as service:
                report["health_ready"] = True
                with r.diagnostic_phase(report, "props", clock):
                    guard = r.make_resource_guard(service.process, r.RSS6_RESOURCES, clock=clock,
                                                  expected_created=metrics["owned_create_time"])
                    with guard.arm(startup_deadline, metrics.setdefault("props_resources", {})):
                        try:
                            r.check_prepared(prepared, admitted.policy, clock, startup_deadline)
                            fetch_props(service, prepared, startup_deadline, report, guard.check,
                                        clock=clock, transport=transport)
                        except Exception as error:
                            record_failure(report, error)  # before guard unwind can replace it
                            raise
                r.remaining(clock, startup_deadline)
            report["status"] = "startup_validated"
        except Exception as error:  # noqa: BLE001 - only safe records leave this diagnostic
            if metrics.get("readiness_error"):
                record_failure(report, metrics["readiness_error"])
                if (metrics["readiness_error"]["code"] == "service_startup_exited"
                        and not metrics.get("readiness_guard_failure")):
                    report["native_failure_classification"] = "native_startup_unknown"
            record_failure(report, error)
        finally:
            failure = getattr(guard, "failure", None)
            metrics["props_guard_failure"] = ("summary_mode_" + failure
                if isinstance(failure, str) and failure in r._GUARD_FAILURES
                else "free_qa_boundary" if failure is not None else None)
            try:
                with r.diagnostic_phase(report, "final_custody", clock):
                    need(not metrics.get("process_creation_attempted") or
                         (metrics.get("within_budget") is True and metrics.get("process_absence_confirmed") is True),
                         "startup_cleanup")
                    check_custody(spec, admitted, prepared, (*fixed_refs, *once_refs), whole_deadline, clock)
                    report["bindings_unchanged"] = True
            except Exception as error:  # noqa: BLE001 - custody cannot promote a failed phase
                record_failure(report, error)
            report["elapsed_seconds"] = clock() - started
            try:
                r.remaining(clock, whole_deadline)
                report_bytes = canonical(report)
                with (output / "report.json").open("xb") as stream:
                    stream.write(report_bytes)
                r.remaining(clock, whole_deadline)
                terminal = {"diagnostic": ID, "status": report["status"], "registration_sha256": expected_sha,
                            "once_sha256": once_sha, "report_sha256": sha(report_bytes),
                            "counts": report["counts"], "props_requests": report["props_requests"],
                            "cleanup_verified": metrics.get("within_budget") is True,
                            "within_deadline": clock() < whole_deadline, "requires_external_terminal_custody": True}
                with (output / "terminal.json").open("xb") as stream:
                    stream.write(canonical(terminal))
                r.remaining(clock, whole_deadline)
                need(sha((output / "report.json").read_bytes()) == terminal["report_sha256"], "startup_late_report_change")
                r.remaining(clock, whole_deadline)
            except BaseException as error:
                record_failure(report, error)
                with (output / "late-invalidation.json").open("xb") as stream:
                    stream.write(canonical({"diagnostic": ID, "status": "INVALIDATED", "error": r.safe_error(error)}))
                raise
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("verify", "run"):
        command = sub.add_parser(name)
        command.add_argument("--registration", type=Path, required=True)
        command.add_argument("--sha256", required=True)
        if name == "run":
            command.add_argument("--once", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            verify_registration(args.registration, args.sha256)
            result = {"diagnostic": ID, "status": "METADATA_VERIFIED_NO_ASSETS_OR_EXECUTION", "execution_approved": False}
        else:
            report = run_startup(args.registration, args.sha256, args.once)
            result = {key: report[key] for key in ("diagnostic", "status", "registration_sha256", "once_sha256", "counts")}
        print(json.dumps(result))
        return 0 if args.command == "verify" or result["status"] == "startup_validated" else 1
    except Exception as error:  # noqa: BLE001 - never print paths, body, token or arbitrary text
        print(json.dumps({"diagnostic": ID, "status": "FAILED_CLOSED", "error": r.safe_error(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
