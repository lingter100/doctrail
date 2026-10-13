"""Checkpoint-bound local Java/React validation on disposable synthetic records.

No quality dataset, training, paid request or public service deployment is used.
Every attempt preserves a partial receipt; existing output directories are refused.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import secrets
import shutil
import stat
import subprocess
import traceback
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx

from scripts.benchmark_api import disposable_database_directory
from scripts.serve_models import ROOT, start_services, stop_process
from scripts.serve_terminal_models import start_terminal_services
from scripts.verify_model_service import (
    METHODS,
    check_evidence,
    expect,
    feedback,
    history,
    register,
    search,
    upload,
)

TERMINAL = {
    "id": "m4-terminal-v1",
    "model": "doctrail/multilingual-e5-small-m4-terminal-v1",
    "revision": "62e530d3094e98b336d039f10956c8e0e2a39d24d66b07818e92a46f0aac10fb",
}
BASE = {"id": "base", "model": "intfloat/multilingual-e5-small",
        "revision": "614241f622f53c4eeff9890bdc4f31cfecc418b3"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def now():
    return datetime.now(UTC).isoformat()


def write_json(path, value):
    with path.open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


@contextmanager
def exclusive_model_check(root=ROOT):
    directory = root / ".local/m4-execution"
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "active.lock"
    payload = json.dumps({"pid": os.getpid(), "command": "terminal-operations",
                          "owner_token": secrets.token_hex(32)}).encode()
    # Exclusive creation remains fail-closed, including for stale locks.
    with lock.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
        owned = os.fstat(stream.fileno())
        identity = (owned.st_dev, owned.st_ino)
    try:
        yield
    finally:
        # Cooperating runs never replace a live lock. External deletion/replacement
        # must not make this run clean up somebody else's lock. This is not an OS
        # lock: hostile replacement after the final check still requires external
        # filesystem access controls; deletion can also permit overlapping runs.
        try:
            current = lock.lstat()
            if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == identity:
                with lock.open("rb") as stream:
                    opened = os.fstat(stream.fileno())
                    ours = (opened.st_dev, opened.st_ino) == identity and stream.read() == payload
                latest = lock.lstat()
                if (ours and stat.S_ISREG(latest.st_mode)
                        and (latest.st_dev, latest.st_ino) == identity):
                    lock.unlink()
        except FileNotFoundError:
            pass  # A missing lock is not ours to recreate or remove.


@contextmanager
def explicit_base_environment():
    previous = os.environ.get("DOCTRAIL_EMBEDDING_PROFILE")
    os.environ["DOCTRAIL_EMBEDDING_PROFILE"] = "base"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DOCTRAIL_EMBEDDING_PROFILE", None)
        else:
            os.environ["DOCTRAIL_EMBEDDING_PROFILE"] = previous


def source_bindings():
    paths = list((ROOT / "server/src").rglob("*"))
    paths += list((ROOT / "web/src").rglob("*"))
    paths += [ROOT / name for name in (
        "scripts/verify_terminal_service.py", "scripts/serve_terminal_models.py",
        "scripts/serve_models.py", "scripts/verify_model_service.py", "scripts/benchmark_api.py",
        "scripts/verify_java_service.py", "src/doctrail/inference.py",
        "src/doctrail/terminal_inference.py", "src/doctrail/model_retrieval.py",
        "web/scripts/verify-terminal-browser.mjs", "docs/M4-OPERATIONS-DESIGN.md")]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for p in sorted(paths) if p.is_file()}


def frontend_artifacts():
    paths = sorted((ROOT / "web/dist").rglob("*"))
    assert (ROOT / "web/dist/index.html").is_file(), "frontend_build_required"
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in paths if p.is_file()}


def verify_served_frontend(url, expected):
    with httpx.Client(base_url=url, timeout=10, trust_env=False) as client:
        for path, sha256 in expected.items():
            suffix = path.removeprefix("web/dist/")
            response = client.get("/" if suffix == "index.html" else "/" + suffix)
            assert response.status_code == 200
            assert hashlib.sha256(response.content).hexdigest() == sha256


@contextmanager
def preserved_local_logs(output):
    with disposable_database_directory() as folder:
        try:
            yield folder
        finally:
            # Raw child logs stay local for failed-start diagnostics; never publish them.
            for path in folder.rglob("*.log"):
                target = output / "logs" / path.relative_to(folder)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)


def assert_profile(result, profile, method):
    assert result.get("embedding_profile") == (None if method == "bm25" else profile)


def run(args, report, completed):
    token = secrets.token_urlsafe(48)
    private_marker = "SYNTHETIC_TERMINAL_PRIVATE_20261013"
    revised_marker = "SYNTHETIC_TERMINAL_REVISED_20261013"
    query = "terminalsyntheticanchor"
    sensitive = [token, private_marker, revised_marker, query]
    report.update(source_sha256_lf=source_bindings(), jar_sha256=digest(args.jar),
                  frontend_artifact_sha256=frontend_artifacts(),
                  checkpoint_manifest_sha256=digest(ROOT / "data/models/m4-terminal-v1.json"),
                  main_dev_receipt_sha256=digest(ROOT / "experiments/results/m4-main-dev-v1.json"))
    assert report["checkpoint_manifest_sha256"] == TERMINAL["revision"]
    with preserved_local_logs(args.output_dir) as folder:
        database = folder / "terminal-java.sqlite3"
        with start_terminal_services(jar=args.jar, database=database, model_root=args.model_root,
                                     device="cuda", token=token, log_dir=folder / "terminal") as services:
            terminal_processes = (services.java, services.worker)
            report["terminal_worker_plus_java_startup_ms_excluding_preflight"] = services.startup_ms
            verify_served_frontend(services.java_url, report["frontend_artifact_sha256"])
            completed("actual_terminal_served_frontend_bytes_match_build")
            report["terminal_worker_health"] = services.health
            assert services.health["runtime"]["device"] == "cuda"
            assert services.health["runtime"]["embedding_dtype"] == "torch.float32"
            assert all(services.health["embedding"][key] == TERMINAL[key] for key in ("model", "revision"))
            with httpx.Client(base_url=services.worker_url, timeout=130, trust_env=False) as worker:
                expect(worker.get("/health"), 401)
            completed("authenticated_actual_terminal_worker_identity")
            with httpx.Client(base_url=services.java_url, timeout=130, trust_env=False) as owner, \
                    httpx.Client(base_url=services.java_url, timeout=130, trust_env=False) as member:
                workspace = register(owner, "owner-terminal@example.invalid", sensitive)
                register(member, "member-terminal@example.invalid", sensitive)
                owner_cookies = dict(owner.cookies)
                caps = expect(owner.get("/api/search/capabilities"))
                assert caps["default_method"] == "bm25" and caps["available_methods"] == METHODS
                assert caps["embedding_profile"] == TERMINAL
                shared = upload(owner, workspace, f"공유 운영 지침 {query} 배포 승인과 복구 순서. 🚀")
                private = upload(owner, workspace, f"{private_marker} {query} 소유자의 비공개 승인 절차.", private=True)
                for method in METHODS:
                    expect(member.get(f"/api/workspaces/{workspace}/search", params={"q": query, "method": method}), 404)
                expect(owner.post(f"/api/workspaces/{workspace}/members", json={"email": "member-terminal@example.invalid"}), 201)
                latest, member_latest = {}, {}
                for method in METHODS:
                    for phase in ("first_request", "repeated_request"):
                        result, elapsed = search(owner, workspace, method, query)
                        assert_profile(result, TERMINAL, method)
                        assert {hit["document_id"] for hit in result["results"]} == {shared["id"], private["id"]}
                        check_evidence(result, [shared, private])
                        report["http_samples"].append({"method": method, "phase": phase,
                            "http_elapsed_ms": elapsed, "java_elapsed_ms": result["elapsed_ms"],
                            "visible_documents": 2, "result_count": len(result["results"]),
                            "cache": "shared_sequential_not_reset"})
                    latest[method] = result
                    feedback(owner, result, private)
                    visible, _ = search(member, workspace, method, query)
                    assert_profile(visible, TERMINAL, method)
                    assert {hit["document_id"] for hit in visible["results"]} == {shared["id"]}
                    check_evidence(visible, [shared])
                    member_latest[method] = visible
                    feedback(member, result, private, 404)
                completed("four_methods_acl_exact_evidence_profile_and_feedback")
                for row in history(owner, workspace):
                    assert_profile(row, TERMINAL, row["method"])
                terminal_history = {r["id"]: r for r in history(owner, workspace)}
                completed("successful_search_identity_persisted_in_history")
                expect(member.get(f"/api/documents/{private['id']}"), 404)
                expect(member.put(f"/api/documents/{private['id']}", json={"title": "denied", "content": "denied", "visibility": "workspace"}), 404)
                expect(member.post(f"/api/documents/{private['id']}/reprocess"), 404)
                expect(member.delete(f"/api/documents/{private['id']}"), 404)
                completed("private_source_edit_reprocess_delete_denied")
                hidden = expect(owner.put(f"/api/documents/{shared['id']}", json={
                    "title": shared["title"], "content": shared["content"], "visibility": "private"}))
                for method in METHODS:
                    denied, _ = search(member, workspace, method, query)
                    assert denied["results"] == []
                    feedback(member, member_latest[method], hidden, 404)
                expect(member.get(f"/api/documents/{shared['id']}"), 404)
                assert all(row["result_count"] == 0 for row in history(member, workspace))
                shared = expect(owner.put(f"/api/documents/{shared['id']}", json={
                    "title": shared["title"], "content": shared["content"], "visibility": "workspace"}))
                completed("visibility_revocation_hides_cached_source_results_history_and_feedback")
                old_chunks = {c["id"] for c in private["chunks"]}
                revised = expect(owner.put(f"/api/documents/{private['id']}", json={
                    "title": "Synthetic terminal revision", "content": f"{revised_marker} {query} 새 승인 순서. 🚀",
                    "visibility": "private"}))
                assert revised["revision"] == private["revision"] + 1
                for method in METHODS:
                    feedback(owner, latest[method], revised, 409)
                    result, _ = search(owner, workspace, method, query)
                    check_evidence(result, [shared, revised])
                    assert not old_chunks.intersection(h["chunk_id"] for h in result["results"])
                    assert all(private_marker not in h["text"] for h in result["results"])
                    latest[method] = result
                completed("revision_replaces_exact_chunks_and_rejects_old_feedback")
                reprocessed = expect(owner.post(f"/api/documents/{private['id']}/reprocess"))
                assert reprocessed["revision"] == revised["revision"] + 1
                revised_chunks = {c["id"] for c in revised["chunks"]}
                for method in METHODS:
                    feedback(owner, latest[method], reprocessed, 409)
                    result, _ = search(owner, workspace, method, query)
                    check_evidence(result, [shared, reprocessed])
                    assert not revised_chunks.intersection(h["chunk_id"] for h in result["results"])
                    latest[method] = result
                completed("reprocess_reuses_content_safely_without_old_revision_identity")
                expect(owner.delete(f"/api/documents/{private['id']}"), 204)
                for method in METHODS:
                    feedback(owner, latest[method], reprocessed, 404)
                    result, _ = search(owner, workspace, method, query)
                    assert {h["document_id"] for h in result["results"]} == {shared["id"]}
                    check_evidence(result, [shared])
                completed("deleted_cached_document_absent_from_all_methods_and_feedback")
                with httpx.Client(base_url=services.worker_url, timeout=130, trust_env=False,
                                  headers={"Authorization": "Bearer " + token}) as worker:
                    witness = []
                    for text in ("터미널 캐시 합성 입력", "터미널 캐시 합성 입력", "터미널 캐시 합성 입력 수정"):
                        payload = expect(worker.post("/embed", json={"schema_version": 1, "kind": "passage",
                            "items": [{"id": "synthetic-cache", "text": text}]}))
                        assert all(payload[k] == TERMINAL[k] for k in ("model", "revision"))
                        witness.append(payload["telemetry"])
                    assert [(r["cache_hits"], r["cache_misses"]) for r in witness] == [(0, 1), (1, 0), (0, 1)]
                    report["terminal_cache_observations"] = witness
                completed("actual_terminal_cache_miss_hit_and_content_change_miss")
                if args.browser:
                    browser_output = args.output_dir / "browser"
                    environment = dict(os.environ, DOCTRAIL_E2E_URL=services.java_url,
                                       DOCTRAIL_E2E_OUTPUT=str(browser_output.resolve()))
                    environment.pop("DOCTRAIL_INFERENCE_TOKEN", None)
                    with (folder / "browser.log").open("ab") as browser_log:
                        subprocess.run(["node", "web/scripts/verify-terminal-browser.mjs"], cwd=ROOT,
                            env=environment, check=True, timeout=240, stdout=browser_log,
                            stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    report["browser"] = json.loads((browser_output / "browser.json").read_bytes())
                    assert report["browser"]["status"] == "passed"
                    report["browser_artifact_sha256"] = {p.name: digest(p) for p in browser_output.iterdir() if p.is_file()}
                    completed("real_terminal_browser_profile_search_evidence_feedback_history_mobile")
                before = history(owner, workspace)
                stop_process(services.worker)
                for method in METHODS[1:]:
                    failure = expect(owner.get(f"/api/workspaces/{workspace}/search", params={"q": query, "method": method}), 503)
                    assert failure["detail"] == "inference_unavailable"
                assert history(owner, workspace) == before
                default = expect(owner.get(f"/api/workspaces/{workspace}/search", params={"q": query}))
                assert default["method"] == "bm25" and default["results"]
                completed("worker_stop_fails_without_fallback_or_history_default_bm25_survives")
        # Same disposable DB and session, but a freshly loaded original worker.
        with explicit_base_environment(), start_services(jar=args.jar, database=database,
                model_root=args.model_root, device="cuda", token=token, log_dir=folder / "base") as services:
            base_processes = (services.java, services.worker)
            report["base_worker_plus_java_startup_ms"] = services.startup_ms
            verify_served_frontend(services.java_url, report["frontend_artifact_sha256"])
            report["rollback_worker_health"] = services.health
            assert all(services.health["embedding"][k] == BASE[k] for k in ("model", "revision"))
            with httpx.Client(base_url=services.java_url, cookies=owner_cookies, timeout=130, trust_env=False) as owner:
                assert expect(owner.get("/api/search/capabilities"))["embedding_profile"] == BASE
                old = {r["id"]: r for r in history(owner, workspace)}
                assert terminal_history.keys() <= old.keys()
                for key, row in terminal_history.items():
                    assert old[key].get("embedding_profile") == row.get("embedding_profile")
                before = history(owner, workspace)
                mismatch = expect(owner.get(f"/api/workspaces/{workspace}/search", params={
                    "q": query, "method": "dense", "expected_embedding_profile": TERMINAL["id"]}), 409)
                assert mismatch["detail"] == "embedding_profile_changed"
                assert history(owner, workspace) == before
                for method in METHODS[1:]:
                    result, _ = search(owner, workspace, method, query)
                    assert_profile(result, BASE, method)
                    check_evidence(result, [shared])
                completed("rollback_base_identity_terminal_history_preserved_mismatched_rerun_rejected")
        log_text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in folder.rglob("*.log"))
        assert all(value not in log_text for value in sensitive if value)
        completed("raw_sentinels_query_password_session_and_worker_token_absent_from_logs")
    assert all(process.poll() is not None for process in (*terminal_processes, *base_processes))
    assert not folder.exists()
    completed("owned_terminal_base_processes_stopped_and_disposable_database_removed")
    assert source_bindings() == report["source_sha256_lf"] and digest(args.jar) == report["jar_sha256"]
    assert frontend_artifacts() == report["frontend_artifact_sha256"]
    completed("source_packaged_jar_and_served_frontend_unchanged_during_validation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, default=ROOT / "server/target/doctrail-server-0.1.0.jar")
    parser.add_argument("--model-root", type=Path, default=ROOT / "models")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if not output.is_relative_to((ROOT / ".local").resolve()) or output.exists():
        parser.error("new_local_output_directory_required")
    args.output_dir = output
    output.mkdir(parents=True)
    report = {"schema_version": 1, "status": "running", "started_at": now(), "checks": [],
              "http_samples": [], "synthetic": True, "human_review": False,
              "quality_evaluated": False, "test_accessed": False, "service_adoption": False,
              "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "git_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
              "python": platform.python_version(), "os": platform.system(),
              "limitations": ["Synthetic local operations, not semantic quality or real-user validation.",
                  "Sequential resident-model HTTP samples share cache; not load/SLO or comparative speed.",
                  "No calibration/main-dev rerun, final test, paid API, or public deployment."]}
    def completed(check):
        report["checks"].append(check)
        with (output / "progress.jsonl").open("ab") as stream:
            stream.write((json.dumps({"at": now(), "check": check, "status": "passed"}) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
    error_code = 0
    try:
        with exclusive_model_check():
            run(args, report, completed)
        report["status"] = "passed"
    except BaseException as error:  # noqa: BLE001 - preserve interruption evidence without raw errors
        error_code = 1
        frame = traceback.extract_tb(error.__traceback__)[-1]
        report.update(status="failed", failure_type=type(error).__name__,
                      failure_location={"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno},
                      failure_code="terminal_operations_failed_inspect_preserved_stage_no_quality_decision")
    finally:
        report["completed_at"] = now()
        report["journal_sha256"] = digest(output / "progress.jsonl") if (output / "progress.jsonl").exists() else None
        write_json(output / "report.json", report)
    print(json.dumps({"status": report["status"], "completed_checks": len(report["checks"])}))
    raise SystemExit(error_code)


if __name__ == "__main__":
    main()
