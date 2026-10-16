"""Offline C1 calibration checks. Imports only the request DTO, never a model.

--write-summary refreshes the count/hash-only summary before item freeze.
--check-upstream optionally re-fetches only the four registered raw URLs in memory.
"""
import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from doctrail.meeting_contract import AnswerRequest

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
REGISTRY_PATH = REPO / "data/evaluation/meetings-c1-calibration-family-registry-v1.json"
FREEZE_PATH = REPO / "data/evaluation/meetings-c1-source-freeze-v1.json"
COMMIT = "82b0fff79761c0da86f4d8c5614aa20f9b12e7e5"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(name):
    return json.loads((ROOT / name).read_bytes())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-summary", action="store_true")
    parser.add_argument("--check-upstream", action="store_true")
    args = parser.parse_args()
    registry = json.loads(REGISTRY_PATH.read_bytes())
    frozen = json.loads(FREEZE_PATH.read_bytes())
    integrity = read("source-integrity.json")
    manifest = read("sources-manifest.json")
    inputs = read("cases.json")
    oracle_data = read("oracles.json")
    assert integrity["candidate_commit"] == manifest["candidate_commit"] == oracle_data["candidate_commit"] == COMMIT
    assert len(frozen["bound_files"]) == 46
    for path, expected in frozen["bound_files"].items():
        assert sha((REPO / path).read_bytes()) == expected, "Frozen dependency changed"
    assert sha(REGISTRY_PATH.read_bytes()) == manifest["source_registry_sha256"] == integrity["source_registry_sha256"]
    assert sha(FREEZE_PATH.read_bytes()) == manifest["source_freeze_sha256"] == integrity["source_freeze_sha256"]
    assert integrity["questions_authored_at_materialization"] == integrity["oracles_authored_at_materialization"] == 0
    assert manifest["authored_after_source_and_family_freeze"] is True
    assert integrity["verified_at_utc"] <= manifest["authored_at_utc"]
    assert all(x["schema_version"] == 1 for x in [integrity, manifest, inputs, oracle_data])
    sources = {s["source_id"]: s for s in manifest["sources"]}
    registered_public = {s["source_id"]: s for s in registry["approved_public_sources"]}
    assert len(sources) == 10
    assert Counter(s["origin"] for s in sources.values()) == {"public": 4, "synthetic": 6}
    assert {s["source_id"] for s in sources.values() if s["origin"] == "public"} == set(registered_public)
    raw_texts, all_windows = {}, {}
    upstream_count = license_count = 0
    for source in sources.values():
        data = (ROOT / source["raw_path"]).read_bytes()
        assert sha(data) == source["raw_sha256"]
        assert len(data) == source["raw_bytes"]
        raw = data.decode("utf-8")
        assert len(raw) == source["raw_codepoints"]
        raw_texts[source["source_id"]] = raw
        if source["meeting_date"] is not None:
            date.fromisoformat(source["meeting_date"])
        if source["origin"] == "public":
            registered = registered_public[source["source_id"]]
            assert len(data) == registered["raw_bytes"]
            assert sha(data) == registered["raw_sha256"]
            assert hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest() == registered["git_blob_sha1"]
            assert registered["license"]["statement"] in " ".join(raw.split())
            notice = (ROOT / source["license_path"]).read_bytes()
            assert sha(notice) == source["license_sha256"]
            assert notice.decode("utf-8") == raw[source["license_start_offset"]:source["license_end_offset"]]
            assert registered["license"]["statement"] in " ".join(notice.decode("utf-8").split())
            license_count += 1
            if args.check_upstream:
                assert urlopen(registered["download_url"], timeout=30).read() == data
                upstream_count += 1
        else:
            assert source["human_reviews"] == 0
            assert "AI" in raw and ("허구" in raw or "fiction" in raw)
        for win in source["windows"]:
            data = (ROOT / win["processed_path"]).read_bytes()
            text = data.decode("utf-8")
            assert sha(data) == win["processed_sha256"]
            start, end = win["start_offset"], win["end_offset"]
            assert text == raw[start:end]
            assert end - start == len(text)
            assert win["start_line"] == raw.count("\n", 0, start) + 1
            assert win["end_line_inclusive"] == raw.count("\n", 0, end - 1) + 1
            assert win["complete_paragraphs"] is True and win["rewritten_or_translated"] is False
            assert start == 0 or raw[start - 1] == "\n"
            assert text.endswith("\n")
            assert win["chunk_id"] not in all_windows
            all_windows[win["chunk_id"]] = (source, win, text)
    slots = {slot["item_id"]: (family, slot) for family in registry["families"] for slot in family["slots"]}
    case_ids = [f"C1CAL-{n:02d}" for n in range(1, 9)]
    assert [x["id"] for x in inputs["cases"]] == case_ids
    assert [x["id"] for x in oracle_data["cases"]] == case_ids
    assert Counter(x["origin"] for x in oracle_data["cases"]) == {"public": 4, "synthetic": 4}
    assert Counter(x["answerability"] for x in oracle_data["cases"]) == {"answerable": 6, "insufficient_evidence": 2}
    assert Counter(x["question_language"] for x in oracle_data["cases"]) == {"ko": 4, "en": 4}
    assert Counter(x["family_id"] for x in oracle_data["cases"]) == {"C1-F01": 2, "C1-F02": 2, "C1-F03": 2, "C1-F04": 2}
    assert Counter((x["origin"], x["question_language"]) for x in oracle_data["cases"]) == {("public", "ko"): 2, ("public", "en"): 2, ("synthetic", "ko"): 2, ("synthetic", "en"): 2}
    assert Counter(x["question_language"] for x in oracle_data["cases"] if x["answerability"] == "insufficient_evidence") == {"ko": 1, "en": 1}
    used_windows = set()
    sizes = []
    context_occurrences = fact_count = quote_count = alternative_count = partial_fact_count = 0
    for case, oracle in zip(inputs["cases"], oracle_data["cases"]):
        assert set(case) == {"id", "operation", "payload"}
        assert case["operation"] == "answer"
        assert set(case["payload"]) == {"schema_version", "query", "contexts"}
        AnswerRequest.model_validate(case["payload"])
        family, slot = slots[case["id"]]
        assert oracle["family_id"] == family["family_id"]
        assert oracle["origin"] == family["origin"]
        assert oracle["question_language"] == slot["question_language"]
        assert oracle["answerability"] == slot["intended_answerability"]
        assert oracle["required_dimensions"] == slot["required_dimensions"]
        answerable = oracle["answerability"] == "answerable"
        assert oracle["expected_status"] == ("answered" if answerable else "abstained")
        assert oracle["expected_reason"] == (None if answerable else "insufficient_evidence")
        assert bool(oracle["required_facts"]) == answerable
        assert bool(oracle["missing_required_parts"]) != answerable
        assert oracle["independent_prereview_count"] == oracle["human_review_count"] == 0
        contexts = case["payload"]["contexts"]
        assert 2 <= len(contexts) <= 10
        assert [ctx["chunk_id"] for ctx in contexts] == oracle["context_chunk_ids"]
        assert [ctx["chunk_id"] for ctx in contexts] == [b["chunk_id"] for b in oracle["source_binding"]]
        docs_used_for_facts = set()
        for ctx, binding in zip(contexts, oracle["source_binding"]):
            source, win, text = all_windows[ctx["chunk_id"]]
            assert source["origin"] == family["origin"] and source["family_id"] == family["family_id"]
            assert ctx["document_id"] == source["source_id"] == binding["document_id"]
            assert ctx["revision"] == source["document_revision"] == binding["revision"] == 1
            assert ctx["meeting_date"] == source["meeting_date"] and ctx["page"] is None
            assert ctx["text"] == text
            assert ctx["start_offset"] == win["start_offset"] and ctx["end_offset"] == win["end_offset"]
            assert binding["processed_sha256"] == win["processed_sha256"]
            used_windows.add(ctx["chunk_id"])
            context_occurrences += 1
        for kind in ["required_facts", "answerable_parts_when_incomplete"]:
            for fact in oracle[kind]:
                assert fact["statement"].strip() and fact["supporting_evidence"]
                assert fact["mandatory"] == (kind == "required_facts")
                if kind == "required_facts":
                    fact_count += 1
                else:
                    partial_fact_count += 1
                for evidence_kind in ["supporting_evidence", "allowed_alternative_citations"]:
                    for ev in fact[evidence_kind]:
                        assert ev["chunk_id"] in oracle["context_chunk_ids"]
                        src, win, text = all_windows[ev["chunk_id"]]
                        assert ev["document_id"] == src["source_id"] and ev["revision"] == 1
                        assert ev["source_raw_sha256"] == src["raw_sha256"] and ev["processed_sha256"] == win["processed_sha256"]
                        start, end = ev["start_offset"], ev["end_offset"]
                        assert win["start_offset"] <= start < end <= win["end_offset"]
                        assert raw_texts[ev["document_id"]][start:end] == ev["quote"]
                        assert end - start == len(ev["quote"])
                        quote_count += 1
                        alternative_count += evidence_kind == "allowed_alternative_citations"
                        if kind == "required_facts":
                            docs_used_for_facts.add(ev["document_id"])
        if "multisource" in oracle["required_dimensions"]:
            assert len(docs_used_for_facts) >= 2
        payload = case["payload"]
        sizes.append({"id": case["id"], "query_codepoints": len(payload["query"]),
                      "query_utf8_bytes": len(payload["query"].encode()), "context_count": len(contexts),
                      "context_text_codepoints": sum(len(c["text"]) for c in contexts),
                      "context_text_utf8_bytes": sum(len(c["text"].encode()) for c in contexts),
                      "context_title_codepoints": sum(len(c["title"]) for c in contexts),
                      "context_title_utf8_bytes": sum(len(c["title"].encode()) for c in contexts),
                      "request_json_utf8_bytes": len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()),
                      "context_text_sizes": [{"index": i, "codepoints": len(c["text"]), "utf8_bytes": len(c["text"].encode())} for i, c in enumerate(contexts)]})
    assert used_windows == set(all_windows)
    assert max(x["context_text_codepoints"] for x in sizes) < 3500
    bound_files = {}
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.name == "summary.json":
            continue
        data = path.read_bytes()
        data.decode("utf-8")
        assert b"\r" not in data and not data.startswith(b"\xef\xbb\xbf"), path.name
        bound_files[path.relative_to(ROOT).as_posix()] = sha(data)
    summary = {
        "schema_version": 1, "dataset_id": "meetings-c1-calibration-v1", "split": "calibration",
        "candidate_commit": COMMIT, "source_registry_sha256": sha(REGISTRY_PATH.read_bytes()),
        "source_freeze_sha256": sha(FREEZE_PATH.read_bytes()),
        "counts": {"authored_questions": 8, "oracles": 8, "public_cases": 4, "synthetic_cases": 4,
                   "answerable": 6, "insufficient_evidence": 2, "question_languages": {"ko": 4, "en": 4},
                   "families": 4, "cases_per_family": 2, "public_sources": 4, "synthetic_sources": 6,
                   "processed_windows": len(all_windows), "context_occurrences": context_occurrences,
                   "required_facts": fact_count, "partial_answerable_facts": partial_fact_count,
                   "exact_support_quotes_including_alternatives": quote_count,
                   "allowed_alternative_quotes": alternative_count, "ai_author_self_reviews": 8,
                   "independent_prereviews": 0, "human_reviews": 0, "model_calls": 0,
                   "tokenizer_calls": 0, "validation_questions_authored": 0},
        "provenance": {"ai_authored_questions": True, "public_sources": "Four registered primary documents, pinned bytes with individual public-domain/CC0 notices preserved.",
                       "synthetic_sources": "Six AI-authored fictional meeting/procedure-revision documents within the two registered families.",
                       "authored_after_source_and_family_freeze": True,
                       "old_prepared12_or_m5b_opened_for_this_work": False,
                       "model_outputs_used_for_authoring": False,
                       "tool_accepted_author_model": "gpt-6-astra", "tool_accepted_reasoning_effort": "xhigh",
                       "settings_scope": "Existing accepted custodian role reused; no parent or service model change claimed."},
        "checks": {"source_freeze_files_verified": 46, "registered_public_raw_hash_size_blob_checks": 4,
                   "public_document_notices_verified": license_count,
                   "strict_answer_request_dtos_valid": 8, "exact_context_spans_valid": context_occurrences,
                   "exact_oracle_support_spans_valid": quote_count, "registered_slot_distribution_valid": True,
                   "utf8_lf_no_bom_bound_files": len(bound_files), "upstream_refetched_this_check": upstream_count},
        "input_size_measurement": {"unit_note": "Unicode codepoints and UTF-8 bytes only; not token counts or native prompt measurements. Context text excludes title/metadata; request JSON includes them. No content was truncated to meet a bound.",
                                   "cases": sizes,
                                   "max_context_text_codepoints": max(x["context_text_codepoints"] for x in sizes),
                                   "max_context_text_utf8_bytes": max(x["context_text_utf8_bytes"] for x in sizes),
                                   "max_request_json_utf8_bytes": max(x["request_json_utf8_bytes"] for x in sizes),
                                   "max_query_codepoints": max(x["query_codepoints"] for x in sizes),
                                   "max_context_count": max(x["context_count"] for x in sizes),
                                   "total_context_text_codepoints": sum(x["context_text_codepoints"] for x in sizes)},
        "readiness": {"authoring_and_offline_checks_complete": True, "independent_prereview_complete": False,
                      "all_stage_token_readiness_measured": False, "model_execution_authorized_by_this_summary": False},
        "bound_files": bound_files,
    }
    if args.write_summary:
        (ROOT / "summary.json").write_bytes((json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode())
    else:
        assert read("summary.json")["bound_files"] == bound_files, "Pool changed since summary binding"
    print(json.dumps({"verification": "passed", "cases": 8, "sources": len(sources),
                      "source_freeze_files": 46, "context_spans": context_occurrences,
                      "oracle_support_spans": quote_count, "bound_files": len(bound_files),
                      "upstream_refetched": upstream_count, "model_calls": 0, "tokenizer_calls": 0}))


if __name__ == "__main__":
    main()
