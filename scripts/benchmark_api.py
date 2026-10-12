"""Bounded real-loopback HTTP benchmark in a disposable database, never production."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from doctrail.retrieval import rank_chunks
from scripts.evaluate_dataset import source_hashes
from scripts.prepare_corpus import load_verified_corpus
from scripts.question_dataset import read_questions, validate_questions

ROOT = Path(__file__).resolve().parents[1]


def select_queries(rows: list[dict]) -> list[dict]:
    """Predeclared: first 2 IDs per category/language, independent of search results."""
    if not rows or any(row["split"] != "dev" for row in rows):
        raise ValueError("API benchmark requires non-empty dev questions; test is locked")
    selected = []
    for category in ("single_document", "multi_document", "no_evidence", "ambiguous"):
        for language in ("ko", "en"):
            selected.extend(
                sorted(
                    [
                        row
                        for row in rows
                        if row["category"] == category and row["language"] == language
                    ],
                    key=lambda row: row["id"],
                )[:2]
            )
    return selected


def percentile(values: list[float], proportion: float) -> float | None:
    return round(sorted(values)[math.ceil(len(values) * proportion) - 1], 3) if values else None


def run(manifest: Path, questions: Path) -> dict:
    frozen = source_hashes(ROOT, manifest, questions)
    rows = read_questions(questions)
    selected = select_queries(rows)
    corpus = load_verified_corpus(manifest)
    validate_questions(rows, corpus, allowed_split="dev", manifest_sha256=frozen["input_manifest"])
    report = {
        "status": "measured_local_loopback_http_only",
        "created_at": datetime.now(UTC).isoformat(),
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.system(),
            "logical_cpu_count": os.cpu_count(),
            "peak_memory_bytes": None,
            "peak_memory_status": "not_measured",
        },
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "git_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
        ),
        "source_sha256": frozen,
        "protocol": {
            "transport": "actual_HTTP_on_127.0.0.1",
            "database": "disposable_sqlite_created_via_authenticated_uploads",
            "query_selection": "first_2_sorted_ids_per_category_language_from_dev",
            "selected_query_ids": [row["id"] for row in selected],
            "warmup_requests": 2,
            "measured_repetitions": 2,
            "concurrency": 1,
            "server_workers": 1,
            "request_timeout_seconds": 60,
            "cache_state": "OS_cache_uncontrolled; warmed_after_upload_and_2_searches",
            "power_and_background_load": "uncontrolled_local_development_machine",
        },
        "requests": [],
        "cost": {
            "external_api_requests": 0,
            "external_api_cost_usd": 0,
            "local_electricity_and_hardware_cost": "not_measured",
        },
    }
    with tempfile.TemporaryDirectory(prefix="doctrail-http-") as folder:
        temporary = Path(folder)
        database = temporary / "benchmark.sqlite3"
        environment = dict(
            os.environ, DOCTRAIL_DB=str(database), DOCTRAIL_SECURE_COOKIE="0", PYTHONUTF8="1"
        )
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        with (temporary / "server.log").open("w+b") as logs:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "doctrail.app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--no-access-log",
                ],
                cwd=ROOT,
                env=environment,
                stdout=logs,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{port}", timeout=60, trust_env=False
                ) as client:
                    deadline = time.monotonic() + 25
                    while True:
                        if process.poll() is not None:
                            raise RuntimeError("Isolated API server exited during startup")
                        try:
                            ready = client.get("/api/health")
                            if ready.status_code == 200:
                                break
                        except httpx.ConnectError:
                            pass
                        if time.monotonic() > deadline:
                            raise TimeoutError("Isolated API startup timed out")
                        time.sleep(0.1)
                    password = secrets.token_urlsafe(30)
                    auth = client.post(
                        "/api/auth/register",
                        json={
                            "email": "benchmark@example.invalid",
                            "password": password,
                            "name": "Automated HTTP benchmark",
                            "workspace_name": "Disposable public corpus",
                        },
                    )
                    auth.raise_for_status()
                    workspace = auth.json()["workspaces"][0]["id"]
                    source_by_api_id, candidates, source_content = {}, [], {}
                    ingestion_started = time.perf_counter()
                    for row in corpus:
                        filename = row["id"] + ".md"
                        upload = client.post(
                            f"/api/workspaces/{workspace}/documents",
                            files={"file": (filename, row["content"].encode(), "text/markdown")},
                            data={"title": row["title"], "visibility": "workspace"},
                        )
                        upload.raise_for_status()
                        doc = upload.json()
                        if doc["status"] != "ready" or doc["content"] != row["content"]:
                            raise ValueError(
                                "Upload content/status differs from frozen normalized corpus"
                            )
                        source_by_api_id[doc["id"]] = row["id"]
                        source_content[doc["id"]] = doc["content"]
                        for chunk in doc["chunks"]:
                            candidates.append(
                                {
                                    **chunk,
                                    "chunk_id": chunk["id"],
                                    "document_id": doc["id"],
                                    "title": row["title"],
                                    "filename": filename,
                                }
                            )
                    report["corpus"] = {
                        "documents_uploaded": len(corpus),
                        "chunks": len(candidates),
                        "upload_wall_ms": round(
                            (time.perf_counter() - ingestion_started) * 1000, 3
                        ),
                    }
                    endpoint = f"/api/workspaces/{workspace}/search"
                    for _ in range(2):
                        client.get(
                            endpoint, params={"q": selected[0]["query"], "limit": 10}
                        ).raise_for_status()
                    # Expected results computed outside the measured request interval.
                    expected = {
                        row["id"]: rank_chunks(row["query"], candidates, 10) for row in selected
                    }
                    for repetition in range(2):
                        for row in selected:
                            started = time.perf_counter()
                            sample = {"question_id": row["id"], "repetition": repetition + 1}
                            try:
                                response = client.get(
                                    endpoint, params={"q": row["query"], "limit": 10}
                                )
                                elapsed = (time.perf_counter() - started) * 1000
                                sample.update(
                                    http_status=response.status_code,
                                    http_roundtrip_ms=round(elapsed, 3),
                                )
                                response.raise_for_status()
                                result = response.json()
                                keys = ("document_id", "start_offset", "end_offset", "score")
                                signature = lambda hits, keys=keys: [
                                    tuple(hit[key] for key in keys) for hit in hits
                                ]
                                sample.update(
                                    success=True,
                                    server_elapsed_ms=result["elapsed_ms"],
                                    ranker_parity=signature(result["results"])
                                    == signature(expected[row["id"]]),
                                    source_offsets_match=all(
                                        source_content[h["document_id"]][
                                            h["start_offset"] : h["end_offset"]
                                        ]
                                        == h["text"]
                                        for h in result["results"]
                                    ),
                                    ranked_source_ids=[
                                        source_by_api_id[h["document_id"]]
                                        for h in result["results"]
                                    ],
                                )
                            except httpx.HTTPError as exc:
                                # No URL/query/password in errors or operational log outputs.
                                sample.update(
                                    success=False,
                                    error_type=type(exc).__name__,
                                    http_roundtrip_ms=round(
                                        (time.perf_counter() - started) * 1000, 3
                                    ),
                                )
                            report["requests"].append(sample)
                    report["corpus"]["sqlite_file_bytes_after_searches"] = {
                        suffix or "main": Path(str(database) + suffix).stat().st_size
                        for suffix in ("", "-wal", "-shm")
                        if Path(str(database) + suffix).exists()
                    }
                    client.post("/api/auth/logout").raise_for_status()
                logs.flush()
                logs.seek(0)
                safe_log = logs.read().decode("utf-8", errors="replace")
                report["log_check"] = {
                    "raw_selected_queries_present": any(
                        row["query"] in safe_log for row in selected
                    ),
                    "password_present": password in safe_log,
                }
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
    if source_hashes(ROOT, manifest, questions) != frozen:
        raise ValueError("Benchmark inputs or source changed during run")
    success = [sample for sample in report["requests"] if sample["success"]]
    report["summary"] = {
        "measured_requests": len(report["requests"]),
        "successful_requests": len(success),
        "failed_requests": len(report["requests"]) - len(success),
        "ranker_parity": bool(success) and all(sample["ranker_parity"] for sample in success),
        "source_offsets_match": bool(success)
        and all(sample["source_offsets_match"] for sample in success),
        "successful_http_roundtrip_p50_ms": percentile(
            [r["http_roundtrip_ms"] for r in success], 0.5
        ),
        "successful_http_roundtrip_p95_ms": percentile(
            [r["http_roundtrip_ms"] for r in success], 0.95
        ),
        "successful_server_p50_ms": percentile([r["server_elapsed_ms"] for r in success], 0.5),
        "successful_server_p95_ms": percentile([r["server_elapsed_ms"] for r in success], 0.95),
    }
    report["limitations"] = [
        "Small serial local HTTP sample; no concurrent load, TLS, internet, UI or deployment claim.",
        "Public corpus all visible to benchmark user; ACL isolation is covered by separate tests.",
        "AI-authored dev selection; no human review and no held-out test queries.",
        "p95 is an order statistic from few requests; host load and power are uncontrolled.",
        "No generated answers, embeddings or training; source content is not operationally logged.",
    ]
    report["completed_at"] = datetime.now(UTC).isoformat()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Refusing to overwrite a prior benchmark")
    report = run(args.manifest, args.questions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"]))


if __name__ == "__main__":
    main()
