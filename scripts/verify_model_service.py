"""Real Java HTTP + local model operational checks on synthetic disposable data.

These checks are AI-authored and automated. Timings are local integration
measurements, never frozen M2/M3 results or evidence of semantic search quality.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import secrets
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from scripts.benchmark_api import disposable_database_directory
from scripts.serve_models import ROOT, start_services, stop_process

METHODS = ["bm25", "dense", "hybrid", "hybrid_rerank"]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expect(response, status=200):
    if response.status_code != status:
        raise AssertionError(f"http_status_{response.status_code}_expected_{status}")
    return response.json() if response.content else None


def register(client, email, secrets_to_scan):
    password = secrets.token_urlsafe(32)
    result = expect(client.post("/api/auth/register", json={
        "email": email, "password": password, "name": "Synthetic model integration",
        "workspace_name": "Synthetic operational checks",
    }), 201)
    secrets_to_scan.extend([password, client.cookies.get("doctrail_session")])
    return result["workspaces"][0]["id"]


def upload(client, workspace, text, *, private=False):
    result = expect(client.post(f"/api/workspaces/{workspace}/documents",
                                files={"file": ("synthetic.md", text.encode("utf-8"))},
                                data={"title": "Synthetic operational fixture",
                                      "visibility": "private" if private else "workspace"}), 201)
    assert result["status"] == "ready" and result["chunks"]
    return result


def search(client, workspace, method, query):
    started = time.perf_counter()
    result = expect(client.get(f"/api/workspaces/{workspace}/search",
                               params={"q": query, "method": method, "limit": 50}))
    assert result["method"] == method
    return result, round((time.perf_counter() - started) * 1000, 3)


def check_evidence(result, documents):
    by_id = {doc["id"]: doc for doc in documents}
    for hit in result["results"]:
        document = by_id[hit["document_id"]]
        chunks = {row["id"]: row for row in document["chunks"]}
        chunk = chunks[hit["chunk_id"]]
        assert hit["revision"] == document["revision"]
        assert hit["text"] == chunk["text"]
        assert document["content"][hit["start_offset"]:hit["end_offset"]] == hit["text"]
        assert hit["page"] == chunk["page"]


def history(client, workspace):
    return expect(client.get(f"/api/workspaces/{workspace}/history"))["items"]


def feedback(client, result, document, status=200):
    return expect(client.post(f"/api/searches/{result['search_id']}/feedback",
                              json={"document_id": document["id"], "relevant": True}), status)


def run(args):
    checks, timings = [], []
    report = {
        "schema_version": 1, "started_at": datetime.now(UTC).isoformat(),
        "provenance": {"fixtures": "AI-authored synthetic documents and queries",
                       "checks": "automated real Java HTTP and actual local model inference",
                       "human_review": False, "semantic_quality_evaluated": False,
                       "frozen_m2_m3_modified": False},
        "checks": checks, "timings": timings,
        "runtime": {"python": platform.python_version(), "os": platform.system(),
                    "requested_device": args.device},
        "jar_sha256": digest(args.jar),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                               cwd=ROOT, text=True).strip(),
        "git_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"],
                                                   cwd=ROOT, text=True).strip()),
    }
    files = [*ROOT.glob("server/src/**/*.java"), *ROOT.glob("server/src/main/resources/*"),
             ROOT / "src/doctrail/inference.py", ROOT / "src/doctrail/model_retrieval.py",
             ROOT / "data/models/m3-models.json", ROOT / "scripts/serve_models.py",
             ROOT / "scripts/verify_java_service.py", Path(__file__).resolve()]
    report["source_sha256"] = {path.relative_to(ROOT).as_posix(): digest(path)
                               for path in files if path.is_file()}
    token = secrets.token_urlsafe(48)
    sensitive = [token, "SYNTHETIC_PRIVATE_SENTINEL", "SYNTHETIC_REVISED_SENTINEL",
                 "syntheticanchor"]
    with disposable_database_directory() as folder:
        with start_services(jar=args.jar, database=folder / "model-java.sqlite3",
                            model_root=args.model_root, device=args.device, token=token,
                            log_dir=folder) as services:
            report["worker_health"] = services.health
            report["startup_ms"] = services.startup_ms
            assert services.health["runtime"]["device"] == args.device
            with httpx.Client(base_url=services.worker_url, timeout=130, trust_env=False) as worker:
                expect(worker.get("/health"), 401)
            checks.append("real_worker_health_requires_shared_authentication")
            with httpx.Client(base_url=services.java_url, timeout=130, trust_env=False) as owner, \
                    httpx.Client(base_url=services.java_url, timeout=130, trust_env=False) as member:
                expect(owner.get("/api/search/capabilities"), 401)
                workspace = register(owner, "owner-model@example.invalid", sensitive)
                register(member, "member-model@example.invalid", sensitive)
                caps = expect(owner.get("/api/search/capabilities"))
                assert caps["available_methods"] == METHODS and caps["default_method"] == "bm25"
                assert caps["status"] == "ready"
                checks.append("authenticated_capabilities_all_four_methods_ready")
                shared = upload(owner, workspace,
                                "공유 운영 문서 syntheticanchor 배포 전 승인 절차. 🚀 근거 위치 검사.")
                private = upload(owner, workspace,
                                 "SYNTHETIC_PRIVATE_SENTINEL syntheticanchor 비공개 소유자 자료.",
                                 private=True)
                for method in METHODS:
                    expect(member.get(f"/api/workspaces/{workspace}/search",
                                      params={"q": "syntheticanchor", "method": method}), 404)
                expect(owner.post(f"/api/workspaces/{workspace}/members",
                                  json={"email": "member-model@example.invalid"}), 201)
                old_searches = {}
                for method in METHODS:
                    for phase in ("first_request", "repeated_request"):
                        result, duration = search(owner, workspace, method, "syntheticanchor")
                        assert {hit["document_id"] for hit in result["results"]} == {
                            shared["id"], private["id"]}
                        check_evidence(result, [shared, private])
                        old_searches[method] = result
                        timings.append({"method": method, "phase": phase,
                                        "passage_cache_state": (
                                            "not_used" if method == "bm25" else
                                            "cold" if method == "dense" and phase == "first_request"
                                            else "warm_shared_across_methods"),
                                        "http_elapsed_ms": duration,
                                        "java_elapsed_ms": result["elapsed_ms"],
                                        "visible_documents": 2, "result_count": len(result["results"])})
                    feedback(owner, result, private)
                    member_result, _ = search(member, workspace, method, "syntheticanchor")
                    assert {hit["document_id"] for hit in member_result["results"]} == {shared["id"]}
                    check_evidence(member_result, [shared])
                    feedback(member, result, private, 404)
                for row in history(owner, workspace):
                    if row["id"] in {result["search_id"] for result in old_searches.values()}:
                        assert old_searches[row["method"]]["search_id"] == row["id"]
                assert {row["method"] for row in history(owner, workspace)} == set(METHODS)
                checks.extend(["all_methods_real_inference_exact_evidence_and_method_history",
                               "workspace_and_private_document_acl_all_methods",
                               "method_specific_owner_feedback_and_cross_user_denial"])
                expect(member.get(f"/api/documents/{private['id']}"), 404)
                expect(member.put(f"/api/documents/{private['id']}", json={
                    "title": "denied", "content": "denied", "visibility": "workspace"}), 404)
                expect(member.post(f"/api/documents/{private['id']}/reprocess"), 404)
                expect(member.delete(f"/api/documents/{private['id']}"), 404)
                old_chunk_ids = {row["id"] for row in private["chunks"]}
                revised = expect(owner.put(f"/api/documents/{private['id']}", json={
                    "title": "Synthetic revision", "content":
                    "SYNTHETIC_REVISED_SENTINEL syntheticanchor 새 승인 단계. 🚀",
                    "visibility": "private"}))
                assert revised["revision"] == private["revision"] + 1
                assert not old_chunk_ids.intersection(row["id"] for row in revised["chunks"])
                revision_searches = {}
                for method in METHODS:
                    feedback(owner, old_searches[method], revised, 409)
                    result, _ = search(owner, workspace, method, "syntheticanchor")
                    check_evidence(result, [shared, revised])
                    assert not old_chunk_ids.intersection(hit["chunk_id"] for hit in result["results"])
                    revision_searches[method] = result
                checks.append("atomic_edit_removes_old_chunk_evidence_and_rejects_stale_feedback")
                processed = expect(owner.post(f"/api/documents/{private['id']}/reprocess"))
                assert processed["revision"] == revised["revision"] + 1
                revised_chunks = {row["id"] for row in revised["chunks"]}
                for method in METHODS:
                    feedback(owner, revision_searches[method], processed, 409)
                    result, _ = search(owner, workspace, method, "syntheticanchor")
                    check_evidence(result, [shared, processed])
                    assert not revised_chunks.intersection(hit["chunk_id"] for hit in result["results"])
                    old_searches[method] = result
                checks.append("reprocess_invalidates_revision_and_chunks_despite_identical_text_cache")
                expect(owner.delete(f"/api/documents/{private['id']}"), 204)
                for method in METHODS:
                    feedback(owner, old_searches[method], processed, 404)
                    result, _ = search(owner, workspace, method, "syntheticanchor")
                    assert all(hit["document_id"] != private["id"] for hit in result["results"])
                    check_evidence(result, [shared])
                checks.append("delete_excludes_cached_document_from_every_method_and_feedback")
                with httpx.Client(base_url=services.worker_url, timeout=130,
                                  headers={"Authorization": "Bearer " + token},
                                  trust_env=False) as worker:
                    cache_witness = []
                    for text in ("독립 합성 캐시 검사", "독립 합성 캐시 검사", "독립 합성 캐시 수정"):
                        result = expect(worker.post("/embed", json={
                            "schema_version": 1, "kind": "passage",
                            "items": [{"id": "synthetic-cache-witness", "text": text}],
                        }))
                        cache_witness.append(result["telemetry"])
                    assert [(row["cache_hits"], row["cache_misses"]) for row in cache_witness] == [
                        (0, 1), (1, 0), (0, 1)]
                    report["worker_cache_witness"] = cache_witness
                checks.append("actual_worker_cache_hit_and_changed_content_miss")
                if args.browser:
                    browser_output = ROOT / ".local" / ("model-browser-" + secrets.token_hex(8))
                    environment = dict(os.environ, DOCTRAIL_E2E_URL=services.java_url,
                                       DOCTRAIL_E2E_OUTPUT=str(browser_output.resolve()))
                    # Browser receives the public Java URL, never the worker token.
                    environment.pop("DOCTRAIL_INFERENCE_TOKEN", None)
                    subprocess.run(["node", "web/scripts/verify-model-browser.mjs"],
                                   cwd=ROOT, env=environment, check=True, timeout=240,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    browser_report = json.loads((browser_output / "browser.json").read_text(
                        encoding="utf-8"))
                    assert browser_report["status"] == "passed"
                    report["browser"] = browser_report
                    report["browser_artifacts"] = {
                        "directory": browser_output.relative_to(ROOT).as_posix(),
                        "sha256": {path.name: digest(path) for path in browser_output.iterdir()
                                   if path.is_file()},
                    }
                    checks.append("real_browser_model_method_workflows")
                before_failure_history = history(owner, workspace)
                stop_process(services.worker)
                for method in METHODS[1:]:
                    failure = expect(owner.get(f"/api/workspaces/{workspace}/search",
                                               params={"q": "syntheticanchor", "method": method}), 503)
                    assert failure["detail"] == "inference_unavailable"
                assert history(owner, workspace) == before_failure_history
                default = expect(owner.get(f"/api/workspaces/{workspace}/search",
                                           params={"q": "syntheticanchor"}))
                assert default["method"] == "bm25" and default["results"]
                caps = expect(owner.get("/api/search/capabilities"))
                assert caps["available_methods"] == ["bm25"] and caps["status"] == "unavailable"
                checks.append("worker_outage_explicit_503_no_fallback_no_history_and_default_bm25_survives")
        log_text = "\n".join(path.read_text(encoding="utf-8", errors="replace")
                             for path in folder.glob("*.log"))
        assert all(secret not in log_text for secret in sensitive if secret), "sensitive_log_content"
        checks.append("no_document_sentinels_session_cookies_passwords_or_worker_token_in_logs")
    report.update(status="passed", completed_at=datetime.now(UTC).isoformat(), limitations=[
        "Synthetic operational integration checks; no real-user or human quality judgment.",
        "First/repeated request timings are sequential local Java HTTP samples, not a load benchmark.",
        "Models are resident before timings; cache state is shared across methods and explicitly not reset.",
        "No training, grounded QA, frozen test evaluation, paid API, or public deployment.",
    ])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, default=ROOT / "server/target/doctrail-server-0.1.0.jar")
    parser.add_argument("--model-root", type=Path, default=ROOT / "models")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.exit(2, "output_exists_choose_new_path\n")
    try:
        report = run(args)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    except Exception:  # noqa: BLE001 - redact credentials, fixture text and raw child diagnostics
        parser.exit(1, "model_service_verification_failed_no_success_report_written\n")
    print(json.dumps({"status": "passed", "checks": len(report["checks"])}))


if __name__ == "__main__":
    main()
