"""Verify the new pool without model or tokenizer calls.

The script reads hidden validation text and oracles but prints only aggregates.
--check-upstream re-fetches pinned public bytes in memory and checks hashes.
--write-summary is for the isolated custodian before the final fixture freeze.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from doctrail.meeting_contract import AnswerRequest

ROOT = Path(__file__).resolve().parent


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-upstream", action="store_true")
    parser.add_argument("--write-summary", action="store_true")
    args = parser.parse_args()
    inputs = load("inputs.json")
    oracle_data = load("oracles.json")
    manifest = load("sources-manifest.json")
    assert inputs["schema_version"] == oracle_data["schema_version"] == manifest["schema_version"] == 1
    assert manifest["candidate_source_freeze_head"] == "f81fd8bb241090ddd210f30ae56f0699166b5a7e"
    assert oracle_data["candidate_source_freeze_head"] == manifest["candidate_source_freeze_head"]
    assert manifest["authoring_started_after_candidate_freeze"] is True
    cases = inputs["cases"]
    oracles = {x["id"]: x for x in oracle_data["cases"]}
    sources = {x["document_id"]: x for x in manifest["sources"]}
    assert len(cases) == len(oracles) == len({x["id"] for x in cases}) == 12
    assert {x["id"] for x in cases} == set(oracles)
    assert Counter(x["provenance"] for x in cases) == {"public": 6, "synthetic": 6}
    assert Counter(x["expected_status"] for x in oracles.values()) == {"answered": 8, "insufficient_evidence": 4}
    assert Counter(x["language"] for x in oracles.values()) == {"en": 4, "ko": 4, "mixed": 4}
    assert Counter((x["provenance"], x["expected_status"]) for x in oracles.values()) == {
        ("public", "answered"): 4, ("public", "insufficient_evidence"): 2,
        ("synthetic", "answered"): 4, ("synthetic", "insufficient_evidence"): 2,
    }
    assert len(sources) == 12
    raw_texts = {}
    upstream_checked = 0
    for source in sources.values():
        data = (ROOT / source["raw_path"]).read_bytes()
        assert digest(data) == source["raw_sha256"]
        assert len(data) == source["raw_bytes"]
        raw = data.decode("utf-8")
        assert len(raw) == source["raw_codepoints"]
        raw_texts[source["document_id"]] = raw
        win = source["window"]
        excerpt = (ROOT / source["excerpt_path"]).read_bytes()
        assert digest(excerpt) == source["excerpt_sha256"]
        assert excerpt.decode("utf-8") == raw[win["start_offset"]:win["end_offset"]]
        if source["meeting_date"] is not None:
            date.fromisoformat(source["meeting_date"])
        if source["provenance"] == "public":
            assert source["commit"] == manifest["public_repository_pin"]["commit"]
            assert source["license"] == "MIT OR Apache-2.0"
            assert source["reuse_license"] == "MIT"
            if args.check_upstream:
                assert digest(urlopen(source["raw_url"], timeout=30).read()) == source["raw_sha256"]
                upstream_checked += 1
    for license_record in manifest["public_license_records"]:
        data = (ROOT / license_record["path"]).read_bytes()
        assert digest(data) == license_record["sha256"]
        assert len(data) == license_record["bytes"]
        if args.check_upstream:
            assert digest(urlopen(license_record["url"], timeout=30).read()) == license_record["sha256"]
            upstream_checked += 1
    fact_count = quote_count = context_count = 0
    pack_lengths = []
    used_sources = set()
    for case in cases:
        assert set(case) == {"id", "operation", "provenance", "payload"}
        assert case["operation"] == "answer"
        AnswerRequest.model_validate(case["payload"])
        ctxs = case["payload"]["contexts"]
        assert 2 <= len(ctxs) <= 5
        assert len({x["document_id"] for x in ctxs}) == len(ctxs)
        by_chunk = {x["chunk_id"]: x for x in ctxs}
        pack_lengths.append(sum(len(x["text"]) for x in ctxs))
        oracle = oracles[case["id"]]
        assert oracle["provenance"] == case["provenance"]
        assert oracle["user_review_count"] == 0
        assert set(oracle["permitted_source_ids"]) == {x["document_id"] for x in ctxs}
        assert bool(oracle["required_facts"]) == (oracle["expected_status"] == "answered")
        assert bool(oracle["abstain_reason"]) == (oracle["expected_status"] == "insufficient_evidence")
        for ctx in ctxs:
            source = sources[ctx["document_id"]]
            assert source["provenance"] == case["provenance"]
            assert ctx["revision"] == source["revision"] == 1
            assert ctx["title"] == source["title"]
            assert ctx["meeting_date"] == source["meeting_date"]
            assert ctx["page"] is None
            assert ctx["start_offset"] == source["window"]["start_offset"]
            assert ctx["end_offset"] == source["window"]["end_offset"]
            assert ctx["end_offset"] - ctx["start_offset"] == len(ctx["text"])
            assert ctx["text"] == raw_texts[ctx["document_id"]][ctx["start_offset"]:ctx["end_offset"]]
            used_sources.add(ctx["document_id"])
            context_count += 1
        for fact in oracle["required_facts"]:
            assert fact["statement"].strip() and fact["evidence"]
            fact_count += 1
            for evidence in fact["evidence"]:
                ctx = by_chunk[evidence["chunk_id"]]
                assert evidence["document_id"] == ctx["document_id"]
                assert evidence["revision"] == ctx["revision"]
                start, end = evidence["start_offset"], evidence["end_offset"]
                assert ctx["start_offset"] <= start < end <= ctx["end_offset"]
                assert raw_texts[evidence["document_id"]][start:end] == evidence["quote"]
                assert end - start == len(evidence["quote"])
                quote_count += 1
    assert used_sources == set(sources)
    review_path = ROOT / "independent-review.json"
    review_summary = {
        "receipt_path": None, "receipt_sha256": None, "independent_ai_reviews": 0,
        "ready_for_frozen_evaluation": False, "strictly_blind_throughout": None,
        "readiness_scope": "dataset_preparation_only",
        "evaluation_execution_authorized_by_receipt": False,
        "initial_findings": 0, "resolved_initial_findings": 0,
        "unresolved_initial_findings": 0, "new_semantic_findings_after_exposure": 0,
        "current_reviewed_artifact_hashes_valid": 0,
        "blinding_limitation": None,
        "review_state": "Author self-review and automatic checks only; independent review pending; human 0",
    }
    if review_path.exists():
        # The complete receipt remains isolated. Only selected counts/flags escape
        # into the parent-safe summary; semantic details are never printed.
        review = load("independent-review.json")
        aggregate = review["initial_review_aggregates"]
        assert aggregate["human_reviews"] == aggregate["service_model_calls"] == aggregate["tokenizer_calls"] == 0
        assert review["candidate_source_freeze_head"] == manifest["candidate_source_freeze_head"]
        followup = review.get("targeted_followup")
        hashes = followup["reviewed_artifact_hashes"] if followup else review["reviewed_artifact_hashes"]
        for file_name in ["inputs.json", "oracles.json", "sources-manifest.json"]:
            assert digest((ROOT / file_name).read_bytes()) == hashes[file_name], "Review hash no longer matches"
        for file_name, expected in review["reviewed_artifact_hashes"]["source_and_license_files"].items():
            assert digest((ROOT / file_name).read_bytes()) == expected, "Reviewed source changed"
        if followup:
            assert followup["original_findings_count"] == 2
            assert followup["source_changes"] is False
            assert followup["service_model_calls"] == followup["tokenizer_calls"] == 0
            assert followup["new_semantic_findings_count"] == 0
        review_summary = {
            "receipt_path": "independent-review.json",
            "receipt_sha256": digest(review_path.read_bytes()),
            "independent_ai_reviews": aggregate["cases_semantically_reviewed_before_exposure"],
            "ready_for_frozen_evaluation": review["ready_for_frozen_evaluation"],
            "readiness_scope": "dataset_preparation_only",
            "evaluation_execution_authorized_by_receipt": False,
            "strictly_blind_throughout": review["isolation"]["strictly_blind_throughout"],
            "initial_findings": aggregate["cases_with_requested_semantic_or_grading_clarification"],
            "resolved_initial_findings": followup["resolved_findings_count"] if followup else 0,
            "unresolved_initial_findings": followup["unresolved_findings_count"] if followup else aggregate["cases_with_requested_semantic_or_grading_clarification"],
            "new_semantic_findings_after_exposure": followup["new_semantic_findings_count"] if followup else 0,
            "current_reviewed_artifact_hashes_valid": 3,
            "blinding_limitation": (
                "Independent reviewer incidentally saw candidate failure information after the initial semantic findings and automatic checks. Strict blinding throughout cannot be claimed. Follow-up was limited to the original two pre-exposure clarity findings; source documents unchanged."
                if review["isolation"]["candidate_output_or_failure_text_exposed"] else None
            ),
            "review_state": (
                "12 initial independent AI case reviews; original two clarity findings resolved by targeted follow-up; limited blinding; human 0"
                if followup and followup["unresolved_findings_count"] == 0 else
                "12 initial independent AI case reviews; clarification findings unresolved; limited blinding; human 0"
            ),
        }
    # Deliberately do not enforce an estimated token count as a real token measurement.
    assert max(pack_lengths) < 7000
    bound_files = {}
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.name == "summary.json":
            continue
        data = path.read_bytes()
        data.decode("utf-8")
        assert b"\r" not in data, path.name
        assert not data.startswith(b"\xef\xbb\xbf"), path.name
        bound_files[path.relative_to(ROOT).as_posix()] = digest(data)
    summary = {
        "schema_version": 1,
        "dataset_id": "meetings-qwen35-validation-v1",
        "candidate_source_freeze_head": manifest["candidate_source_freeze_head"],
        "authored_after_candidate_source_freeze": True,
        "counts": {"cases": len(cases), "public_cases": 6, "synthetic_cases": 6,
                   "answerable": 8, "insufficient_evidence": 4,
                   "public_answerable": 4, "public_insufficient_evidence": 2,
                   "synthetic_answerable": 4, "synthetic_insufficient_evidence": 2,
                   "question_languages": {"en": 4, "ko": 4, "mixed": 4},
                   "source_documents": len(sources), "public_source_documents": 6,
                   "synthetic_source_documents": 6, "meeting_source_documents": 4,
                   "ordinary_source_documents": 8, "context_occurrences": context_count,
                   "contexts_per_case_min": min(len(x["payload"]["contexts"]) for x in cases),
                   "contexts_per_case_max": max(len(x["payload"]["contexts"]) for x in cases),
                   "required_facts": fact_count, "exact_evidence_quotes": quote_count,
                   "ai_authored_questions": 12, "ai_author_self_reviews": 12,
                   "independent_ai_reviews": review_summary["independent_ai_reviews"], "user_reviews": 0,
                   "model_calls": 0, "tokenizer_calls": 0},
        "provenance": {"public_repository": manifest["public_repository_pin"],
                       "public_license": "MIT OR Apache-2.0; MIT elected; all upstream notices retained",
                       "synthetic_sources": "AI-authored fictional archive digitization records",
                       "questions_and_oracles": "AI-authored by isolated custodian after source freeze",
                       "existing_eval_or_dev_cases_read": False,
                       "candidate_prompt_read": False,
                       "review_state": review_summary["review_state"]},
        "independent_review": review_summary,
        "checks": {"answer_request_schema_valid_cases": len(cases),
                   "raw_source_hashes_valid": len(sources),
                   "public_license_provenance_files_valid": len(manifest["public_license_records"]),
                   "exact_source_context_spans_valid": context_count,
                   "exact_oracle_evidence_spans_valid": quote_count,
                   "utf8_lf_without_bom_files_valid": len(bound_files),
                   "pinned_public_and_license_bytes_refetched": upstream_checked,
                   "token_counts_measured": False},
        "context_sizes_codepoints": {"min": min(pack_lengths), "max": max(pack_lengths),
                                    "total": sum(pack_lengths)},
        "bound_files": bound_files,
    }
    if args.write_summary:
        (ROOT / "summary.json").write_bytes((json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    else:
        saved = load("summary.json")
        assert saved["bound_files"] == bound_files, "Dataset files changed after recorded summary"
    print(json.dumps({"verification": "passed", "cases": len(cases),
                      "context_spans": context_count, "evidence_spans": quote_count,
                      "bound_files": len(bound_files), "upstream_hashes_checked": upstream_checked,
                      "model_calls": 0, "tokenizer_calls": 0}, ensure_ascii=True))


if __name__ == "__main__":
    main()
