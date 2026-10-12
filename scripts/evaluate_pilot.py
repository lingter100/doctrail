"""Measure the real API on a tiny smoke corpus; never present it as test-set quality."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import secrets
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from doctrail.app import create_app
from scripts.prepare_pilot import verified_processed
from scripts.validate_splits import validate

ROOT = Path(__file__).resolve().parents[1]


def percentile(values: list[float], proportion: float) -> float:
    return sorted(values)[max(0, math.ceil(len(values) * proportion) - 1)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Refusing to overwrite a past run. Choose a new report name.")
    manifest = json.loads(
        (ROOT / "data/manifests/kubernetes-pilot.json").read_text(encoding="utf-8")
    )
    questions = [
        json.loads(line)
        for line in (ROOT / "data/evaluation/pilot-smoke.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    split_check = validate(manifest["documents"], questions)
    outcomes = []
    documents = {}
    evaluated_corpus_hashes = {}
    with (
        tempfile.TemporaryDirectory(prefix="doctrail-eval-") as folder,
        TestClient(create_app(Path(folder) / "eval.sqlite3")) as client,
    ):
        auth = client.post(
            "/api/auth/register",
            json={
                "email": "evaluation@example.invalid",
                "password": secrets.token_urlsafe(24),
                "name": "Automatic evaluation",
                "workspace_name": "Pilot",
            },
        )
        auth.raise_for_status()
        workspace_id = auth.json()["workspaces"][0]["id"]
        for row in manifest["documents"]:
            source = ROOT / f"data/processed/kubernetes-pilot/{row['id']}.md"
            if not source.exists():
                raise SystemExit("Run scripts/prepare_pilot.py first.")
            processed_bytes = verified_processed(row)
            result = client.post(
                f"/api/workspaces/{workspace_id}/documents",
                files={"file": (source.name, processed_bytes, "text/markdown")},
                data={"title": row["title"], "visibility": "workspace"},
            )
            result.raise_for_status()
            document = result.json()
            assert document["status"] == "ready", document
            documents[document["id"]] = {"source_id": row["id"], "content": document["content"]}
            evaluated_corpus_hashes[row["id"]] = {
                "processed_sha256": hashlib.sha256(processed_bytes).hexdigest(),
                "ingested_content_sha256": hashlib.sha256(
                    document["content"].encode("utf-8")
                ).hexdigest(),
            }
        for question in questions:
            for evidence in question["evidence"]:
                matching = next(
                    d for d in documents.values() if d["source_id"] == evidence["document_id"]
                )
                assert evidence["quote"] in matching["content"], "evidence missing after ingestion"
            started = time.perf_counter()
            response = client.get(
                f"/api/workspaces/{workspace_id}/search",
                params={"q": question["query"], "limit": 10},
            )
            total_ms = (time.perf_counter() - started) * 1000
            response.raise_for_status()
            payload = response.json()
            hits = payload["results"]
            ranked_ids = [documents[hit["document_id"]]["source_id"] for hit in hits]
            relevant = set(question["relevant_document_ids"])
            ranked_unique_ids = list(dict.fromkeys(ranked_ids))
            rank = next((i for i, doc in enumerate(ranked_unique_ids, 1) if doc in relevant), None)
            exact_source = all(
                documents[hit["document_id"]]["content"][hit["start_offset"] : hit["end_offset"]]
                == hit["text"]
                for hit in hits
            )
            evidence_hit5 = any(
                e["quote"] in hit["text"]
                and documents[hit["document_id"]]["source_id"] == e["document_id"]
                for e in question["evidence"]
                for hit in hits[:5]
            )
            outcomes.append(
                {
                    "id": question["id"],
                    "category": question["category"],
                    "query": question["query"],
                    "relevant_document_ids": sorted(relevant),
                    "ranked_chunk_document_ids": ranked_ids,
                    "ranked_document_ids": ranked_unique_ids,
                    "first_relevant_rank": rank,
                    "evidence_hit_at_5": evidence_hit5,
                    "source_offsets_match": exact_source,
                    "empty_result": not hits,
                    "server_elapsed_ms": payload["elapsed_ms"],
                    "in_process_roundtrip_ms": round(total_ms, 3),
                }
            )
    answerable = [row for row in outcomes if row["category"] == "single_document"]
    absent = [row for row in outcomes if row["category"] == "no_evidence"]
    source_paths = sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "scripts").glob("*.py"))
    source_paths += [
        ROOT / "uv.lock",
        ROOT / "data/manifests/kubernetes-pilot.json",
        ROOT / "data/evaluation/pilot-smoke.jsonl",
    ]
    hashes = {
        str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in source_paths
    }
    command = lambda args: subprocess.check_output(args, cwd=ROOT, text=True).strip()
    report = {
        "status": "measured_smoke_only",
        "created_at": datetime.now(UTC).isoformat(),
        "purpose": "Integration/small-corpus failure discovery. Not held-out retrieval quality, QA accuracy or production performance.",
        "git_commit": command(["git", "rev-parse", "HEAD"]),
        "git_dirty": bool(command(["git", "status", "--porcelain"])),
        "source_sha256": hashes,
        "evaluated_corpus_sha256": evaluated_corpus_hashes,
        "python": platform.python_version(),
        "platform": platform.system(),
        "dataset": {
            "documents": len(documents),
            "questions": len(questions),
            "human_reviewed_questions": 0,
            "split": "smoke",
            "split_check": split_check,
        },
        "config": {
            "method": "bm25",
            "k1": 1.5,
            "b": 0.75,
            "chunk_characters": 1000,
            "overlap_characters": 150,
            "ranking_unit": "chunk",
            "document_metric_unit": "deduplicated documents within top 10 chunks",
            "retrieved_chunks": 10,
            "tokenizer": "ascii-word-korean-bigram-v1",
            "normalizer": "hugo-light-v2",
        },
        "metrics": {
            "document_hit_at_5": sum(
                bool(r["first_relevant_rank"] and r["first_relevant_rank"] <= 5) for r in answerable
            )
            / len(answerable),
            "document_mrr_at_10": sum(
                1 / r["first_relevant_rank"] if r["first_relevant_rank"] else 0 for r in answerable
            )
            / len(answerable),
            "annotated_evidence_hit_at_5": sum(r["evidence_hit_at_5"] for r in answerable)
            / len(answerable),
            "no_evidence_empty_result_rate": sum(r["empty_result"] for r in absent) / len(absent),
            "source_offsets_match": all(r["source_offsets_match"] for r in outcomes),
            "server_latency_p50_ms": percentile([r["server_elapsed_ms"] for r in outcomes], 0.5),
            "server_latency_p95_ms": percentile([r["server_elapsed_ms"] for r in outcomes], 0.95),
        },
        "cost": {
            "external_api_requests": 0,
            "external_api_cost_usd": 0,
            "local_electricity_and_hardware_cost": "not_measured",
        },
        "limitations": [
            "10 answerable and 2 AI-authored no-evidence questions; all lack human review.",
            "Bilingual translations are near duplicates. No training/dev/test comparison.",
            "Document hit does not prove the answer-bearing span was found.",
            "Partial BM25 match on absent-answer questions is not abstention or answerability.",
            "Latency is serial in-process TestClient, no internet/TLS/load/GPU measurement.",
            "Unresolved Hugo content includes need review before dataset expansion.",
        ],
        "questions": outcomes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {"report": args.output.as_posix(), "metrics": report["metrics"]}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
