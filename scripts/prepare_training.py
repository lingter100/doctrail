"""Replayable train-only authoring and weak-negative curation; no model training."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from doctrail.ingest import extract
from doctrail.retrieval import chunk_content, rank_chunks
from scripts.prepare_corpus import load_verified_corpus

ROOT = Path(__file__).resolve().parents[1]


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def fingerprint(value: object) -> str:
    return sha256(json_bytes(value))


def jsonl_bytes(rows: list[dict]) -> bytes:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    ).encode()


def write_or_verify(path: Path, content: bytes, verify: bool = False) -> None:
    if verify:
        if not path.is_file() or path.read_bytes() != content:
            raise ValueError(f"Replay mismatch: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(content)


def normalized_query(text: str) -> str:
    return " ".join(text.casefold().split())


def word_shingles(text: str, width: int = 3) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", text.casefold())
    if len(words) < width:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + width]) for i in range(len(words) - width + 1)}


def query_shingles(text: str) -> set[str]:
    normalized = normalized_query(text)
    return {normalized[i:i + 3] for i in range(max(1, len(normalized) - 2))}


def jaccard(left: set, right: set) -> float:
    return len(left & right) / len(left | right) if left or right else 0.0


def chunks_for(documents: list[dict]) -> list[dict]:
    chunks = []
    for row in sorted(documents, key=lambda item: item["id"]):
        if row["split"] != "train":
            raise ValueError("Only train documents may be chunked")
        raw = row["content"].encode()
        if sha256(raw) != row["normalized_sha256"]:
            raise ValueError("Normalized corpus checksum drift")
        content, pages = extract(raw, "md")
        if content != row["content"]:
            raise ValueError("Ingestion changed source offsets")
        for chunk in chunk_content(content, pages):
            chunks.append({
                "document_id": row["id"], "family_id": row["family_id"],
                "chunk_id": f"{row['id']}:{chunk.ordinal}", "text": chunk.text,
                "start_offset": chunk.start_offset, "end_offset": chunk.end_offset,
                "page": chunk.page, "title": row["title"], "filename": f"{row['id']}.md",
                "text_sha256": sha256(chunk.text.encode()),
            })
    return chunks


def compact_chunk(chunk: dict) -> dict:
    return {key: chunk[key] for key in (
        "document_id", "family_id", "chunk_id", "start_offset", "end_offset", "text_sha256"
    )}


def partition_for(family_id: str, plan: dict) -> str:
    split = plan["split"]
    bucket = int(sha256(f"{split['seed']}:{family_id}".encode())[:16], 16) % 100
    return "fit" if bucket < 80 else "calibration"


def validate_plan(plan: dict) -> None:
    split = plan.get("split", {})
    required = {
        "seed": "doctrail-m4-train-v1", "hash_algorithm": "sha256",
        "hash_prefix_hex_chars": 16, "bucket_modulus": 100,
        "fit_buckets": [0, 79], "calibration_buckets": [80, 99],
        "group_field": "family_id", "source_split": "train",
    }
    if plan.get("schema_version") != 1 or any(split.get(k) != v for k, v in required.items()):
        raise ValueError("Unsupported frozen M4 split plan")
    mining = plan.get("negative_mining", {})
    for key, value in {"method": "bm25", "top_k": 20, "near_duplicate_threshold": 0.8,
                       "pool": "same_partition_only"}.items():
        if mining.get(key) != value:
            raise ValueError("Unsupported frozen negative mining policy")
    positive = plan.get("positive_gates", {})
    if (positive.get("question_duplicate_method") !=
            "casefolded normalized character trigram Jaccard"
            or positive.get("question_duplicate_threshold") != 0.8):
        raise ValueError("Unsupported question duplicate policy")


def load_inputs(plan_path: Path, root: Path = ROOT) -> tuple[dict, list[dict]]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    validate_plan(plan)
    protocol = plan.get("draft_contract", {})
    if (not protocol.get("protocol_path") or not protocol.get("protocol_sha256")
            or sha256((root / protocol["protocol_path"]).read_bytes()) != protocol["protocol_sha256"]):
        raise ValueError("Authoring protocol checksum drift")
    manifest_path = root / plan["corpus"]["manifest_path"]
    if sha256(manifest_path.read_bytes()) != plan["corpus"]["manifest_sha256"]:
        raise ValueError("Frozen manifest checksum drift")
    # Full loader checks immutable hashes and original split components. Only train
    # rows escape this expression; no held-out questions are ever opened here.
    train = [row for row in load_verified_corpus(manifest_path, root) if row["split"] == "train"]
    return plan, train


def build_inventory(plan: dict, documents: list[dict], plan_sha256: str) -> dict:
    validate_plan(plan)
    if not documents or any(row["split"] != "train" for row in documents):
        raise ValueError("Inventory requires only original train documents")
    if len({row["id"] for row in documents}) != len(documents):
        raise ValueError("Duplicate document ID")
    # Even an injected test loader must not split translations/exact duplicates.
    families = {}
    for row in documents:
        for field in ("canonical_path", "normalized_sha256"):
            key = (field, row[field])
            if families.setdefault(key, row["family_id"]) != row["family_id"]:
                raise ValueError("Translation or exact duplicate crosses families")
    chunks = chunks_for(documents)
    chunk_counts = Counter(chunk["document_id"] for chunk in chunks)
    rows = []
    for doc in sorted(documents, key=lambda row: row["id"]):
        rows.append({
            **{key: doc[key] for key in (
                "id", "family_id", "canonical_path", "language", "title", "source_url",
                "license", "author", "revision", "normalized_sha256", "sha256", "split"
            )},
            "partition": partition_for(doc["family_id"], plan),
            "characters": len(doc["content"]), "chunks": chunk_counts[doc["id"]],
            "topic": doc["canonical_path"].split("/")[0],
        })
    counts = {}
    for part in ("fit", "calibration"):
        subset = [row for row in rows if row["partition"] == part]
        counts[part] = {
            "documents": len(subset), "families": len({row["family_id"] for row in subset}),
            "chunks": sum(row["chunks"] for row in subset),
            "languages": dict(sorted(Counter(row["language"] for row in subset).items())),
            "topics": dict(sorted(Counter(row["topic"] for row in subset).items())),
        }
    return {
        "schema_version": 1, "plan_sha256": plan_sha256,
        "manifest_sha256": plan["corpus"]["manifest_sha256"], "documents": rows,
        "counts": counts, "human_reviewed": 0,
        "validation_scope": "full_corpus_integrity_then_train_only_processing",
    }


def build_author_pack(inventory: dict, documents: list[dict], partition: str,
                      selected_ids: list[str] | None = None) -> dict:
    if partition not in {"fit", "calibration"}:
        raise ValueError("Invalid author partition")
    allowed = {row["id"]: row for row in inventory["documents"] if row["partition"] == partition}
    selected = sorted(allowed if selected_ids is None else selected_ids)
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(allowed):
        raise ValueError("Author pack document outside allowed partition")
    corpus = {row["id"]: row for row in documents}
    return {
        "schema_version": 1, "partition": partition,
        "plan_sha256": inventory["plan_sha256"], "inventory_sha256": fingerprint(inventory),
        "allowed_document_ids": selected,
        "documents": [{**allowed[doc_id], "content": corpus[doc_id]["content"]}
                      for doc_id in selected],
        "instructions": [
            "Write one evidence-grounded fact per question; use exact source quotes.",
            "AI authorship and human review pending must remain explicit.",
            "Do not read dev/test/smoke questions or author from any other partition.",
            "All negative candidates are unreviewed, never assumed irrelevant.",
        ],
    }


def validate_author_pack(pack: dict, inventory: dict, documents: list[dict]) -> None:
    expected = build_author_pack(inventory, documents, pack.get("partition"),
                                 pack.get("allowed_document_ids"))
    if pack != expected:
        raise ValueError("Author pack integrity or allowed-document drift")


def evidence_span(item: dict, document: dict) -> dict:
    quote = item.get("quote")
    if not isinstance(quote, str) or len(quote.strip()) < 8:
        raise ValueError("Evidence quote is too short")
    occurrence = item.get("occurrence", 0)
    if type(occurrence) is not int or occurrence < 0:
        raise ValueError("Invalid quote occurrence")
    start = -1
    for _ in range(occurrence + 1):
        start = document["content"].find(quote, start + 1)
        if start < 0:
            raise ValueError("Exact quote missing from allowed source")
    end = start + len(quote)
    if "start_offset" in item and item["start_offset"] != start:
        raise ValueError("Draft offset differs from computed Unicode span")
    return {
        "document_id": document["id"], "family_id": document["family_id"],
        "start_offset": start, "end_offset": end, "quote": quote,
        "normalized_sha256": document["normalized_sha256"],
        "source_url": document["source_url"], "license": document["license"],
    }


def negative_candidates(query: str, positive_spans: list[dict], positives: list[dict],
                        candidates: list[dict], top_k: int = 20) -> list[dict]:
    positive_families = {span["family_id"] for span in positive_spans}
    positive_hashes = {chunk["text_sha256"] for chunk in positives}
    positive_sets = [word_shingles(chunk["text"]) for chunk in positives]
    quotes = [normalized_query(span["quote"]) for span in positive_spans]
    result = []
    for rank, hit in enumerate(rank_chunks(query, candidates, limit=top_k), 1):
        reasons = []
        if hit["family_id"] in positive_families:
            reasons.append("positive_document_or_connected_family")
        if hit["text_sha256"] in positive_hashes:
            reasons.append("exact_positive_chunk")
        if any(quote in normalized_query(hit["text"]) for quote in quotes):
            reasons.append("contains_known_evidence_quote")
        hit_shingles = word_shingles(hit["text"])
        if any(jaccard(hit_shingles, other) >= 0.8 for other in positive_sets):
            reasons.append("near_duplicate_positive_chunk")
        result.append({
            **compact_chunk(hit), "mining_method": "bm25_train_partition_only",
            "rank": rank, "score": hit["score"],
            "status": "quarantined_false_negative_risk" if reasons else "unreviewed",
            "quarantine_reasons": reasons, "negative_label": None,
            "semantic_review": "pending", "human_review": "pending",
            "eligible_for_training": False,
        })
    return result


def compile_dataset(plan: dict, inventory: dict, documents: list[dict],
                    packs: dict[str, dict], drafts: list[dict], draft_hashes: dict) -> dict[str, bytes]:
    """Compile provisional positives and separate *unlabelled* mining candidates."""
    for pack_hash, pack in packs.items():
        if fingerprint(pack) != pack_hash:
            raise ValueError("Author pack checksum mismatch")
        validate_author_pack(pack, inventory, documents)
    expected = build_inventory(plan, documents, inventory["plan_sha256"])
    if inventory != expected:
        raise ValueError("Inventory replay mismatch")
    if not drafts:
        raise ValueError("Draft question set is empty")
    corpus = {row["id"]: row for row in documents}
    chunks = chunks_for(documents)
    partition_chunks = {
        part: [chunk for chunk in chunks if partition_for(chunk["family_id"], plan) == part]
        for part in ("fit", "calibration")
    }
    questions, pairs, mined = [], [], []
    seen_ids, seen_queries, intent_parts = set(), {}, {}
    for draft in sorted(drafts, key=lambda row: row["id"]):
        identifier, part = draft.get("id"), draft.get("partition")
        if (not isinstance(identifier, str) or identifier in seen_ids
                or part not in partition_chunks):
            raise ValueError("Duplicate question ID or invalid partition")
        seen_ids.add(identifier)
        query = draft.get("question")
        if not isinstance(query, str) or not 3 <= len(query.strip()) <= 500:
            raise ValueError("Invalid question text")
        normalized = normalized_query(query)
        if normalized in seen_queries:
            raise ValueError("Exact duplicate question text")
        seen_queries[normalized] = identifier
        intent = draft.get("question_family_id")
        if not isinstance(intent, str) or not intent:
            raise ValueError("Question intent family missing")
        if intent_parts.setdefault(intent, part) != part:
            raise ValueError("Question intent family crosses fit/calibration")
        if draft.get("language") not in {"en", "ko"} or draft.get("query_type") not in {
            "semantic", "exact_term", "cross_lingual"
        }:
            raise ValueError("Invalid language or query type")
        provenance = draft.get("provenance", {})
        if (provenance.get("authorship") != "ai_authored"
                or provenance.get("source_kind") != "public_real"
                or provenance.get("author_model") not in {"gpt-6-astra", "gpt-6.1-sol"}
                or provenance.get("author_reasoning") not in {"high", "xhigh", "max"}
                or provenance.get("human_review") != "pending"
                or provenance.get("human_reviewer") is not None):
            raise ValueError("AI provenance and human-pending review required")
        review = draft.get("semantic_review", {})
        if review.get("status") not in {"pending", "ai_checked"}:
            raise ValueError("Invalid semantic review provenance")
        if review["status"] == "ai_checked" and (
            review.get("reviewer_model") not in {"gpt-6-astra", "gpt-6.1-sol"}
            or not isinstance(review.get("notes"), str) or not review["notes"].strip()
        ):
            raise ValueError("AI semantic check needs model and notes")
        for field in ("expected_answer", "rationale"):
            if not isinstance(draft.get(field), str) or not draft[field].strip():
                raise ValueError("Expected answer and author rationale required")
        pack = packs.get(draft.get("author_pack_sha256"))
        if pack is None or pack["partition"] != part:
            raise ValueError("Unknown author pack or partition mismatch")
        evidence = draft.get("evidence")
        if not isinstance(evidence, list) or len(evidence) != 1:
            raise ValueError("M4 pilot requires exactly one evidence fact/quote")
        doc_id = evidence[0].get("document_id")
        if (doc_id not in corpus or doc_id not in pack["allowed_document_ids"]
                or partition_for(corpus[doc_id]["family_id"], plan) != part):
            raise ValueError("Evidence outside allowed author partition")
        span = evidence_span(evidence[0], corpus[doc_id])
        cross_language = draft["language"] != corpus[doc_id]["language"]
        if (draft["query_type"] == "cross_lingual") != cross_language:
            raise ValueError("Query type disagrees with evidence language")
        positives = [chunk for chunk in partition_chunks[part]
                     if chunk["document_id"] == doc_id
                     and chunk["start_offset"] <= span["start_offset"]
                     and chunk["end_offset"] >= span["end_offset"]]
        question = {
            **draft, "schema_version": 1, "source_split": "train", "evidence": [span],
            "positive_chunk_ids": [chunk["chunk_id"] for chunk in positives],
            "automatic_validation": "exact_source_span_and_partition_passed",
            "quarantine_reasons": [] if positives else ["evidence_not_covered_by_one_chunk"],
            "human_review": "pending",
            "cross_language": cross_language,
        }
        questions.append(question)
        for chunk in positives:
            pairs.append({
                "question_id": identifier, "partition": part, "question": query,
                "question_family_id": intent, "positive": compact_chunk(chunk),
                "label_status": "ai_authored_provisional_positive", "human_review": "pending",
                "eligible_for_training": False,
            })
        if positives:
            for candidate in negative_candidates(query, [span], positives, partition_chunks[part]):
                mined.append({"question_id": identifier, "partition": part, **candidate})
    # Similar questions are reported and quarantined, never silently removed.
    near_flags = []
    shingles = {row["id"]: query_shingles(row["question"]) for row in questions}
    for i, left in enumerate(questions):
        for right in questions[i + 1:]:
            score = jaccard(shingles[left["id"]], shingles[right["id"]])
            if score >= 0.8:
                flag = {"left": left["id"], "right": right["id"], "jaccard": round(score, 8),
                        "cross_partition": left["partition"] != right["partition"]}
                near_flags.append(flag)
                for row in (left, right):
                    if "near_duplicate_question" not in row["quarantine_reasons"]:
                        row["quarantine_reasons"].append("near_duplicate_question")
    intent_counts = Counter(row["question_family_id"] for row in questions)
    for row in questions:
        if intent_counts[row["question_family_id"]] > 1:
            row["quarantine_reasons"].append("duplicate_question_intent")
    quarantined = {row["id"] for row in questions if row["quarantine_reasons"]}
    for pair in pairs:
        pair["quarantined"] = pair["question_id"] in quarantined
    counts = {}
    for part in ("fit", "calibration"):
        subset = [row for row in questions if row["partition"] == part]
        counts[part] = {
            "questions": len(subset),
            "families": len({row["evidence"][0]["family_id"] for row in subset}),
            "languages": dict(sorted(Counter(row["language"] for row in subset).items())),
            "query_types": dict(sorted(Counter(row["query_type"] for row in subset).items())),
            "quarantined_questions": sum(row["id"] in quarantined for row in subset),
            "positive_pairs": sum(row["partition"] == part for row in pairs),
            "unique_intents": len({row["question_family_id"] for row in subset}),
            "cross_language": sum(row["cross_language"] for row in subset),
        }
    pilot = plan.get("pilot", {})
    gates = {}
    for part in ("fit", "calibration"):
        gates[f"{part}_query_target"] = counts[part]["questions"] >= pilot.get(
            f"target_{part}_queries", 0
        )
        gates[f"{part}_family_target"] = counts[part]["families"] >= pilot.get(
            f"min_{part}_families", 0
        )
    family_counts = Counter(row["evidence"][0]["family_id"] for row in questions)
    gates["max_queries_per_family"] = max(family_counts.values(), default=0) <= pilot.get(
        "max_queries_per_family", 4
    )
    gates["korean_queries_with_english_evidence"] = sum(
        row["language"] == "ko" and corpus[row["evidence"][0]["document_id"]]["language"] == "en"
        for row in questions
    ) >= pilot.get("min_korean_queries_with_english_evidence", 0)
    gates["english_queries"] = sum(row["language"] == "en" for row in questions) >= pilot.get(
        "min_english_queries", 0
    )
    covered_topics = {corpus[row["evidence"][0]["document_id"]]["canonical_path"].split("/")[0]
                      for row in questions}
    gates["topic_coverage"] = set(pilot.get("coverage", [])) <= covered_topics
    gates["no_quarantined_questions"] = not quarantined
    report = {
        "schema_version": 1, "plan_sha256": inventory["plan_sha256"],
        "inventory_sha256": fingerprint(inventory), "draft_sha256": draft_hashes,
        "author_pack_sha256": sorted(packs), "counts": counts,
        "ai_authored_questions": len(questions), "human_reviewed_questions": 0,
        "near_duplicate_flags": near_flags,
        "negative_candidate_statuses": dict(sorted(Counter(row["status"] for row in mined).items())),
        "confirmed_negative_labels": 0, "training_executed": False,
        "training_ready": False,
        "pilot_data_gates": gates,
        "unmet_pilot_data_gates": sorted(key for key, passed in gates.items() if not passed),
        "outstanding_training_gates": [
            "independent_positive_semantic_review", "e5_token_retention",
            "two_reviewed_negatives_per_fit_query", "resource_probe",
        ],
        "source_sha256_lf": {
            path: sha256((ROOT / path).read_bytes().replace(b"\r\n", b"\n"))
            for path in ("scripts/prepare_training.py", "scripts/prepare_corpus.py",
                         "src/doctrail/ingest.py", "src/doctrail/retrieval.py")
        },
        "validation": "verified_hashes_exact_spans_train_partition_and_provenance_passed",
        "limitations": [
            "AI authorship and automatic span checks do not establish semantic correctness.",
            "Candidates are unreviewed or quarantined; none are labelled negative.",
            "Positive pairs are provisional and no training recipe is authorized by this artifact.",
            "Lexical duplicate screening does not prove semantic independence.",
            "Calibration originates inside old train and is not a new blind test.",
        ],
    }
    return {
        "questions.jsonl": jsonl_bytes(questions), "positive-pairs.jsonl": jsonl_bytes(pairs),
        "negative-candidates.jsonl": jsonl_bytes(mined), "report.json": json_bytes(report),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inventory", "author-pack", "compile", "replay"))
    parser.add_argument("--plan", type=Path, default=ROOT / "data/training/m4-plan-v1.json")
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--partition", choices=("fit", "calibration"))
    parser.add_argument("--document-ids", nargs="+")
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--author-packs", type=Path, nargs="+")
    parser.add_argument("--drafts", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    plan, documents = load_inputs(args.plan)
    inventory = build_inventory(plan, documents, sha256(args.plan.read_bytes()))
    if args.command == "inventory":
        if args.output is None:
            parser.error("inventory needs --output")
        write_or_verify(args.output, json_bytes(inventory), args.verify)
        print(json.dumps(inventory["counts"], ensure_ascii=False))
        return
    if args.inventory is None or args.inventory.read_bytes() != json_bytes(inventory):
        raise ValueError("Inventory file missing or drifted")
    if args.command == "author-pack":
        if args.output is None or args.partition is None:
            parser.error("author-pack needs --output and --partition")
        # Full source text is a local cache artifact, never a public corpus copy.
        if not args.output.resolve().is_relative_to((ROOT / ".local").resolve()):
            raise ValueError("Author packs containing full source must be inside .local")
        if args.selection and args.document_ids:
            parser.error("Choose --selection or --document-ids")
        selected = args.document_ids
        if args.selection:
            selection = json.loads(args.selection.read_text(encoding="utf-8"))
            selected = selection["selected"][args.partition]
        pack = build_author_pack(inventory, documents, args.partition, selected)
        write_or_verify(args.output, json_bytes(pack), args.verify)
        print(json.dumps({"documents": len(pack["documents"]), "sha256": fingerprint(pack)}))
        return
    if not args.author_packs or not args.drafts or args.output_dir is None:
        parser.error("compile/replay needs --author-packs, --drafts and --output-dir")
    packs = {}
    for path in args.author_packs:
        raw = path.read_bytes()
        pack = json.loads(raw)
        if raw != json_bytes(pack):
            raise ValueError("Author pack must use deterministic canonical encoding")
        packs[sha256(raw)] = pack
    drafts = [json.loads(line) for path in args.drafts
              for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    hashes = {path.name: sha256(path.read_bytes()) for path in args.drafts}
    if len(hashes) != len(args.drafts):
        raise ValueError("Draft filenames must be unique")
    artifacts = compile_dataset(plan, inventory, documents, packs, drafts, hashes)
    verify = args.verify or args.command == "replay"
    if not verify and any((args.output_dir / name).exists() for name in artifacts):
        raise FileExistsError("Refusing to overwrite an existing dataset artifact")
    for name, raw in artifacts.items():
        write_or_verify(args.output_dir / name, raw, verify)
    report = json.loads(artifacts["report.json"])
    print(json.dumps({"counts": report["counts"], "replay": verify, "training_ready": False}))


if __name__ == "__main__":
    main()
