"""Synthetic sealed repositories and fake offline counts; no model/tokenizer calls."""
import copy
import json
import unicodedata
from types import SimpleNamespace

import pytest

from doctrail.ingest import normalize
from scripts import prepare_meeting_requirements_inputs as prep
from scripts.prepare_meeting_source_inventory import git_blob


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else prep.encoded(value))
    return prep.sha(path.read_bytes())


@pytest.fixture
def factory(tmp_path, monkeypatch):
    candidate_names = set(json.loads((prep.ROOT / prep.CANDIDATE_FREEZE).read_bytes())["bound_files"])
    monkeypatch.setattr(prep, "ROOT", tmp_path)

    def create(phase="calibration", count=100):
        base = f"data/evaluation/meetings-c3-{phase}-synthetic"
        names = {r: f"{base}/{r}.json" for r in ("draft", "oracle", "manifest", "inventory",
            "processing_receipt", "source_prereview", "item_prereview", "java_parity",
            "context_selection", "source_freeze", "item_freeze")}
        names["code_freeze"] = prep.TOOLCHAIN_FREEZE
        paths = {r: tmp_path / n for r, n in names.items()}
        for n in candidate_names | prep.NEW_FILES | prep.REUSED_FILES | {prep.CONTRACT}:
            write(tmp_path / n, b"# synthetic frozen file\n")
        families, documents, raw_files, registry = [], [], {}, []
        for fid in prep.FAMILIES[phase]:
            origin = "public" if fid in {"C3-F01", "C3-F03"} else "synthetic"
            family = {"family_id": fid, "origin": origin, "source_language": prep.SOURCE_LANGUAGES[fid],
                "source_suitability": {"verdict": "ADOPTED"}, "repository": "fixture/repository",
                "immutable_commit": "1" * 40, "license": {"id": "synthetic-test-only"}, "sources": []}
            entry = {k: family[k] for k in ("family_id", "origin", "source_language", "repository", "immutable_commit")}
            entry.update(split=phase, source_candidates=[])
            for n in range(2):
                raw_text = f"Synthetic notice. Fresh {fid} source {n}. 😀 e\u0301.\r\n"
                raw = raw_text.encode()
                content = normalize(raw_text)
                raw_name = f"{base}/raw/{fid}-{n}.txt"
                raw_files[raw_name] = write(tmp_path / raw_name, raw)
                source = {"source_id": f"{fid}-{n}", "document_id": f"doc-{fid}-{n}", "revision": 1,
                    "registration_ordinal": len(documents), "title": f"Synthetic {fid} source {n}",
                    "meeting_date": None, "page": None, "path": f"{fid}-{n}.txt",
                    "ingestion_kind": "txt", "local_raw_snapshot": raw_name,
                    "raw_sha256": prep.sha(raw), "raw_size_bytes": len(raw), "raw_encoding": "UTF-8",
                    "git_blob_sha1": git_blob(raw) if origin == "public" else None,
                    "processed_sha256": prep.sha(content.encode()), "processed_codepoints": len(content),
                    "adoption_verdict": f"ADOPTED_FOR_{phase.upper()}_SOURCE_WITH_REGISTERED_CONSTRAINTS",
                    "adoption_author_role": "source-writer",
                    "bom": False, "lf_count": raw_text.count("\n"), "cr_count": raw_text.count("\r"),
                    "trailing_lf": True, "nfc_identity_verified": unicodedata.is_normalized("NFC", raw_text),
                    "service_normalization_identity_verified": content == raw_text,
                    "immutable_url": "https://example.invalid/synthetic", "license_id": "synthetic-test-only",
                    "synthetic_provenance": {"ai_authored": True, "fictional": True,
                        "author_role": "source-writer", "notice": "Synthetic notice."}}
                family["sources"].append(source)
                entry["source_candidates"].append({"path": source["path"], "sha": source["git_blob_sha1"]})
                documents.append(prep.document_record(family, source, raw))
            families.append(family)
            registry.append(entry)
        write(tmp_path / prep.REGISTRY, {"schema_version": 1, "families": registry})
        draft, oracle = {"schema_version": 1, "phase": phase, "cases": []}, {"schema_version": 1, "phase": phase, "cases": []}
        for fid in prep.FAMILIES[phase]:
            contexts = []
            for doc in [d for d in documents if d["family_id"] == fid]:
                chunk = doc["chunks"][0]
                contexts.append({k: doc[k] for k in ("document_id", "revision", "title", "meeting_date")}
                    | {k: chunk[k] for k in ("chunk_id", "text", "page", "start_offset", "end_offset")})
            languages = ["en", "ko", "ko"] if fid == "C3-F01" else ["ko", "en", "en"]
            if phase == "validation":
                languages = ["en", "ko", "en", "ko"]
            for i, language in enumerate(languages):
                identity = f"synthetic-{fid}-{i}"
                draft["cases"].append({"id": identity, "response_language": language, "payload": {
                    "schema_version": 1, "query": "Synthetic question 😀 e\u0301.\r\nExplicit requested language.",
                    "contexts": copy.deepcopy(contexts)}})
                facts = []
                for j in range(3 if i < 2 else 2):
                    context = contexts[j % 2]
                    evidence = {k: context[k] for k in ("chunk_id", "start_offset", "end_offset")}
                    evidence["quote"] = context["text"]
                    facts.append({"id": f"f{j}", "text": f"Synthetic fact {j}.",
                                  "evidence_alternatives": [[evidence]] if i < 2 or j == 0 else []})
                oracle["cases"].append({"id": identity, "family_id": fid,
                    "provenance": "public" if fid in {"C3-F01", "C3-F03"} else "synthetic",
                    "language": language, "expected_status": "answered" if i < 2 else "abstained",
                    "required_facts": facts, "unanswerable_reason": None if i < 2 else "Missing required fact.",
                    "forbidden_inferences": [], "limitations": ["Synthetic testing only."],
                    "question_author": "writer", "oracle_author": "writer",
                    "independent_prereviewer": "item-reviewer", "human_review_count": 0})
        s = SimpleNamespace(root=tmp_path, phase=phase, paths=paths, names=names, draft=draft,
            oracle=oracle, documents=documents, families=families, raw_files=raw_files,
            output=tmp_path / ".local/prepared", calls=[], loads=[])

        def seal():
            candidate = {"schema_version": 1, "candidate": prep.ANSWER_POLICY,
                "bound_files": {n: prep.sha((tmp_path / n).read_bytes()) for n in candidate_names}}
            candidate_sha = write(tmp_path / prep.CANDIDATE_FREEZE, candidate)
            monkeypatch.setattr(prep, "CANDIDATE_FREEZE_SHA256", candidate_sha)
            monkeypatch.setattr(prep, "CONTRACT_SHA256", prep.sha((tmp_path / prep.CONTRACT).read_bytes()))
            code_names = candidate_names | prep.NEW_FILES | prep.REUSED_FILES | {prep.CANDIDATE_FREEZE, prep.CONTRACT}
            write(paths["code_freeze"], {"schema_version": 1, "candidate": prep.ANSWER_POLICY,
                "kind": "toolchain", "bound_files": {n: prep.sha((tmp_path / n).read_bytes()) for n in code_names}})
            code = json.loads(paths["code_freeze"].read_bytes())["bound_files"]
            manifest = {"schema_version": 1, "phase": phase, "families": s.families,
                "family_registry": {"path": prep.REGISTRY, "sha256": prep.sha((tmp_path / prep.REGISTRY).read_bytes())},
                "active_comparison_source_freeze": {"path": names["code_freeze"],
                    "sha256": prep.sha(paths["code_freeze"].read_bytes())},
                "processing_protocol": {"id": "synthetic-plaintext-v2",
                    "existing_service_reference_sha256": {n: code[n] for n in prep.SERVICE_FILES},
                    "chunk_algorithm": copy.deepcopy(prep.CHUNK_CONTRACT),
                    "chunk_id_format": "{document_id}-r1-c{ordinal:04d}"}}
            manifest_sha = write(paths["manifest"], manifest)
            inventory_sha = write(paths["inventory"], {"schema_version": 1, "source_processing_version": 2,
                "phase": phase, "mode": "adopted-all", "manifest_sha256": manifest_sha,
                "documents": s.documents, "excluded_sources": []})
            write(paths["source_prereview"], {"schema_version": 1, "verdict": "accepted",
                "reviewer_id": "source-reviewer", "author_ids": ["source-writer"],
                "accepted_ids": [d["document_id"] for d in s.documents], "rejected_ids": [], "human_review_count": 0})
            write(paths["processing_receipt"], {"schema_version": 1, "source_processing_version": 2,
                "phase": phase, "mode": "adopted-all",
                "manifest": {"path": names["manifest"], "sha256": manifest_sha},
                "bound_files": {n: code[n] for n in prep.SERVICE_FILES | prep.HELPER_FILES},
                "references": {r: manifest[r] for r in ("family_registry", "active_comparison_source_freeze")},
                "inventory_sha256": inventory_sha, "processing_protocol": "synthetic-plaintext-v2",
                "documents": [{k: d[k] for k in ("source_id", "document_id", "revision", "raw_sha256",
                    "raw_size_bytes", "git_blob_sha1", "processed_sha256", "processed_codepoints")}
                    | {"chunks": len(d["chunks"])} for d in s.documents],
                "excluded_sources": [], "counts": {"registered_sources": len(s.documents),
                    "processed_documents": len(s.documents), "chunks": sum(len(d["chunks"]) for d in s.documents),
                    "excluded_sources": 0, "selected_contexts": 0, "questions": 0, "oracles": 0,
                    "synthetic_bodies_authored": 0, "tokenizer_runs": 0, "model_calls": 0,
                    "downloads": 0, "human_reviews": 0}, "java_parity_verified": False})
            write(paths["java_parity"], {"schema_version": 1,
                "kind": "actual_java_python_document_chunk_parity", "java_version": "21.0.1",
                "inventory_sha256": inventory_sha, "bound_files": {n: code[n] for n in prep.JAVA_PARITY_FILES},
                "documents": [{"document_id": d["document_id"], "raw_sha256": d["raw_sha256"],
                    "processed_sha256": d["processed_sha256"], "codepoints": d["processed_codepoints"],
                    "chunks": len(d["chunks"])} for d in s.documents],
                "document_count": len(s.documents), "chunk_count": sum(len(d["chunks"]) for d in s.documents),
                "exact_content_pages_chunk_text_offsets_ordinals_ids": True,
                "model_calls": 0, "semantic_quality_measured": False})
            source_roles = {r: names[r if r != "prereview" else "source_prereview"] for r in prep.ROLES["source"]}
            write(paths["source_freeze"], {"schema_version": 1, "candidate": prep.ANSWER_POLICY,
                "phase": phase, "kind": "source", "files": source_roles,
                "bound_files": {**s.raw_files, **{n: prep.sha((tmp_path / n).read_bytes()) for n in source_roles.values()}}})
            write(paths["draft"], s.draft)
            write(paths["oracle"], s.oracle)
            write(paths["context_selection"], {"schema_version": 1, "phase": phase, "cases": [
                {"id": c["id"], "chunk_ids": [x["chunk_id"] for x in c["payload"]["contexts"]]}
                for c in s.draft["cases"]]})
            write(paths["item_prereview"], {"schema_version": 1, "verdict": "accepted",
                "reviewer_id": "item-reviewer", "author_ids": ["writer"],
                "accepted_ids": [c["id"] for c in s.draft["cases"]], "rejected_ids": [],
                "whole_family_absence_checked": True, "human_review_count": 0})
            item_roles = {r: names[r if r != "prereview" else "item_prereview"] for r in prep.ROLES["item"]}
            write(paths["item_freeze"], {"schema_version": 1, "candidate": prep.ANSWER_POLICY,
                "phase": phase, "kind": "item", "files": item_roles,
                "bound_files": {n: prep.sha((tmp_path / n).read_bytes()) for n in item_roles.values()}})
        s.seal = seal
        seal()
        def loader(download):
            s.loads.append(download)
            from doctrail.meeting_qwen35 import MODEL_ID, MODEL_REVISION
            return None, {"repo_id": MODEL_ID, "revision": MODEL_REVISION,
                "transformers_version": "synthetic", "download_authorized": False,
                "trust_remote_code": False, "assets_sha256": {n: "a" * 64 for n in
                    ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja")}}
        def counter(_, prompt):
            s.calls.append(copy.deepcopy(prompt))
            return count
        s.loader, s.counter = loader, counter
        return s
    return create


def run(s, **kwargs):
    return prep.prepare(s.paths["draft"], s.output, s.phase, oracle_path=s.paths["oracle"],
        source_freeze_path=s.paths["source_freeze"], item_freeze_path=s.paths["item_freeze"],
        code_freeze_path=s.paths["code_freeze"], loader=kwargs.get("loader", s.loader),
        counter=kwargs.get("counter", s.counter))


def rebind(s, role):
    """Reseal a synthetic fixture deliberately, before the tested preparation."""
    for freeze in ("source_freeze", "item_freeze"):
        data = json.loads(s.paths[freeze].read_bytes())
        if s.names[role] in data["bound_files"]:
            data["bound_files"][s.names[role]] = prep.sha(s.paths[role].read_bytes())
            write(s.paths[freeze], data)
    if role != "item_freeze":
        item = json.loads(s.paths["item_freeze"].read_bytes())
        item["bound_files"][s.names["source_freeze"]] = prep.sha(s.paths["source_freeze"].read_bytes())
        write(s.paths["item_freeze"], item)


@pytest.mark.parametrize("phase", ["calibration", "validation"])
@pytest.mark.parametrize("count", [4096, 5120])
def test_exact_complete_payload_and_once_only_stage1_preparation(factory, phase, count):
    s = factory(phase, count)
    result = run(s)
    assert result["status"] == "passed", result["errors"]
    prepared = json.loads((s.output / "input.json").read_bytes())
    assert [{k: c[k] for k in ("id", "response_language", "payload")} for c in prepared["cases"]] == s.draft["cases"]
    assert all(c["official_stage1_tokens"] == count for c in prepared["cases"])
    assert result["stage2_readiness"] == "dynamic_unmeasured" and s.loads == [False]
    assert len(s.calls) == prep.COUNTS[phase]
    assert [json.loads(p[1]["content"])["response_language"] for p in s.calls] == [
        c["response_language"] for c in s.draft["cases"]]
    assert result["model_calls"] == result["native_calls"] == result["downloads"] == 0
    assert json.loads((s.output / "receipt.json").read_bytes()) == result
    before = (s.output / "receipt.json").read_bytes()
    with pytest.raises(prep.PreparationError, match="output_exists"):
        run(s)
    assert before == (s.output / "receipt.json").read_bytes()


@pytest.mark.parametrize("bad_count", [5121, False, "10", 0])
def test_entire_survey_continues_after_bad_count_without_hiding_denominator(factory, bad_count):
    s = factory()
    counts = iter([bad_count, 100, 100, 100, 100, 100])
    def counter(_, prompt):
        s.calls.append(prompt)
        return next(counts)
    result = run(s, counter=counter)
    assert result["status"] == "failed" and len(s.calls) == 6
    assert result["summary"]["failed_cases"] == 1
    assert result["summary"]["measured_cases"] == (6 if bad_count == 5121 else 5)
    assert result["summary"]["total_cases"] == 6 and not (s.output / "input.json").exists()
    assert "stage2" not in json.dumps(s.calls)


@pytest.mark.parametrize("role", ["draft", "oracle", "inventory", "source_prereview", "item_prereview",
                                  "java_parity", "context_selection"])
def test_hash_tampering_blocks_all_tokenizer_access(factory, role):
    s = factory()
    s.paths[role].write_bytes(s.paths[role].read_bytes() + b" ")
    result = run(s)
    assert result["status"] == "failed" and not s.loads and not s.calls
    assert "preparation_hash_mismatch" in result["errors"]


@pytest.mark.parametrize("role,change", [
    ("source_prereview", lambda d: d.update(verdict="rejected")),
    ("source_prereview", lambda d: d.update(reviewer_id="source-writer")),
    ("source_prereview", lambda d: d.update(author_ids=["concealed-writer"])),
    ("item_prereview", lambda d: d.update(whole_family_absence_checked=False)),
    ("item_prereview", lambda d: d.update(accepted_ids=[])),
    ("java_parity", lambda d: d.update(exact_content_pages_chunk_text_offsets_ordinals_ids=False)),
    ("java_parity", lambda d: d.update(inventory_sha256="a" * 64)),
    ("java_parity", lambda d: d["bound_files"].update({min(prep.JAVA_PARITY_FILES): "a" * 64})),
    ("java_parity", lambda d: d.update(java_version="17.0.1")),
    ("processing_receipt", lambda d: d.update(source_processing_version=1)),
    ("processing_receipt", lambda d: d["bound_files"].pop(min(prep.HELPER_FILES))),
    ("processing_receipt", lambda d: d.update(inventory_sha256="b" * 64)),
    ("context_selection", lambda d: d.update(schema_version=True)),
    ("context_selection", lambda d: d["cases"][0]["chunk_ids"].reverse()),
])
def test_valid_hash_does_not_replace_semantic_prereview_or_parity_and_selection_contract(factory, role, change):
    s = factory()
    data = json.loads(s.paths[role].read_bytes())
    change(data)
    write(s.paths[role], data)
    rebind(s, role)
    result = run(s)
    assert result["status"] == "failed" and not s.loads


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(extra=True),
    lambda d: d["cases"][0].update(response_language="ja"),
    lambda d: d["cases"][0]["payload"].update(schema_version=True),
    lambda d: d["cases"][0]["payload"]["contexts"][0].pop("page"),
    lambda d: d["cases"][0]["payload"]["contexts"][0].update(title="Changed metadata"),
    lambda d: d["cases"][0]["payload"]["contexts"][0].update(document_id="foreign"),
])
def test_payload_and_whole_inventory_membership_rejected_before_counts(factory, mutate):
    s = factory()
    mutate(s.draft)
    s.seal()
    result = run(s)
    assert result["status"] == "failed" and not s.loads


@pytest.mark.parametrize("mutation", ["extra", "missing", "candidate_changed", "wrong_kind"])
def test_exact_code_freeze_set_and_original_candidate_binding(factory, mutation):
    s = factory()
    data = json.loads(s.paths["code_freeze"].read_bytes())
    if mutation == "extra":
        data["bound_files"]["irrelevant.txt"] = "a" * 64
    elif mutation == "missing":
        data["bound_files"].pop(min(prep.NEW_FILES))
    elif mutation == "candidate_changed":
        data["bound_files"]["src/doctrail/meeting_answer_requirements.py"] = "a" * 64
    else:
        data["kind"] = "source"
    write(s.paths["code_freeze"], data)
    rebind(s, "code_freeze")
    result = run(s)
    assert "preparation_code_freeze_contract" in result["errors"] and not s.loads


def test_source_raw_inventory_and_declared_family_language_are_bound(factory):
    s = factory()
    s.families[0]["source_language"] = "ko"
    s.seal()
    result = run(s)
    assert "preparation_registry_family" in result["errors"] and not s.loads


def test_inventory_tampering_is_replayed_even_with_new_valid_hash(factory):
    s = factory()
    s.documents[0]["chunks"][0]["text"] = "Invented fixture content."
    s.seal()
    result = run(s)
    assert "preparation_inventory_mismatch" in result["errors"] and not s.loads


def test_same_registered_public_source_cannot_impersonate_two_documents(factory):
    s = factory()
    original = s.families[0]["sources"][0]
    s.families[0]["sources"][1].update(path=original["path"], git_blob_sha1=original["git_blob_sha1"])
    s.seal()
    result = run(s)
    assert "preparation_source_not_adopted" in result["errors"] and not s.loads


@pytest.mark.parametrize("field,value", [("ai_authored", False), ("fictional", False),
                                       ("author_role", ""), ("notice", "")])
def test_synthetic_provenance_cannot_be_laundered_by_inventory_receipts(factory, field, value):
    s = factory()
    s.families[1]["sources"][0]["synthetic_provenance"][field] = value
    s.seal()
    result = run(s)
    assert "preparation_synthetic_provenance" in result["errors"] and not s.loads


def test_processing_protocol_must_match_frozen_service_and_chunk_contract(factory):
    s = factory()
    manifest = json.loads(s.paths["manifest"].read_bytes())
    manifest["processing_protocol"]["chunk_algorithm"]["max_codepoints"] = 999
    new_hash = write(s.paths["manifest"], manifest)
    inventory = json.loads(s.paths["inventory"].read_bytes())
    inventory["manifest_sha256"] = new_hash
    write(s.paths["inventory"], inventory)
    rebind(s, "manifest")
    rebind(s, "inventory")
    result = run(s)
    assert "preparation_processing_protocol" in result["errors"] and not s.loads


def test_template_byte_limit_prevents_counts_and_preserves_all_failed_rows(factory, monkeypatch):
    s = factory()
    monkeypatch.setattr(prep, "MAX_REQUEST_BYTES", 100)
    result = run(s)
    assert result["status"] == "failed" and not s.calls
    assert result["summary"]["unmeasured_cases"] == result["summary"]["failed_cases"] == 6
    assert all(r["error_code"] == "preparation_template_byte_limit" for r in result["cases"])


def test_snapshot_drift_during_survey_invalidates_all_outputs(factory):
    s = factory()
    def counter(_, prompt):
        if not s.calls:
            s.paths["draft"].write_bytes(s.paths["draft"].read_bytes() + b" ")
        s.calls.append(prompt)
        return 100
    result = run(s, counter=counter)
    assert result["status"] == "failed" and "preparation_snapshot_changed" in result["errors"]
    assert len(s.calls) == 6 and not (s.output / "input.json").exists()


def test_tokenizer_failure_is_sanitized_and_claim_consumed(factory):
    s = factory()
    def fail(_):
        raise RuntimeError("PRIVATE source words")
    result = run(s, loader=fail)
    assert result["status"] == "failed" and "PRIVATE" not in json.dumps(result)
    assert result["summary"]["unmeasured_cases"] == 6
    with pytest.raises(prep.PreparationError, match="output_exists"):
        run(s)


@pytest.mark.parametrize("name", ["../outside", "folder/../outside", "C:/foreign", "x\\y", "/absolute", "a//b"])
def test_relative_reference_path_guards(name, tmp_path):
    with pytest.raises(prep.PreparationError):
        prep.relative(name, tmp_path)


def test_bounded_snapshot_and_output_alias(factory, tmp_path):
    s = factory()
    s.paths["draft"].write_bytes(b" " * (prep.BYTE_LIMIT + 1))
    result = run(s)
    assert result["status"] == "failed" and not s.loads
    s.output = s.paths["source_freeze"].parent
    with pytest.raises(prep.PreparationError):
        run(s)


def test_linked_input_rejected_before_read(factory, tmp_path):
    s = factory()
    link = tmp_path / "linked"
    try:
        link.symlink_to(s.paths["draft"])
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    s.paths["draft"] = link
    with pytest.raises(prep.PreparationError, match="linked_path"):
        run(s)


@pytest.mark.parametrize("name", ["data/evaluation/meetings-c2-validation-v1/oracle.json",
    "data/evaluation/meetings-c3-validation-v1/source.txt",
    "data/evaluation/meetings-c3-calibration-synthetic/unregistered.txt"])
def test_unrelated_bound_body_is_rejected_before_open(factory, monkeypatch, name):
    s = factory()
    forbidden = s.root / name
    digest = write(forbidden, b"PRIVATE synthetic sentinel; must not be opened")
    freeze = json.loads(s.paths["source_freeze"].read_bytes())
    freeze["bound_files"][name] = digest
    write(s.paths["source_freeze"], freeze)
    rebind(s, "source_freeze")
    reads = []
    original = prep.snapshot
    def snapshot(path):
        reads.append(path)
        assert path != forbidden
        return original(path)
    monkeypatch.setattr(prep, "snapshot", snapshot)
    result = run(s)
    assert result["status"] == "failed" and not s.loads
    assert forbidden not in reads
    assert any(e in {"preparation_phase_data_path", "preparation_source_binding_set"}
               for e in result["errors"])


@pytest.mark.parametrize("name", ["data/evaluation/meetings-c3-validation-v1/source.txt",
    "data/evaluation/meetings-c2-validation-v1/oracle.json",
    "data/evaluation/meetings-c3-calibration-synthetic/source.txt"])
def test_code_freeze_argument_cannot_open_any_phase_or_old_pool_body(factory, monkeypatch, name):
    s = factory()
    forbidden = s.root / name
    write(forbidden, b"PRIVATE synthetic sentinel; not code metadata")
    s.paths["code_freeze"] = forbidden
    reads = []
    original = prep.snapshot
    def snapshot(path):
        reads.append(path)
        return original(path)
    monkeypatch.setattr(prep, "snapshot", snapshot)
    with pytest.raises(prep.PreparationError, match="preparation_code_freeze_path"):
        run(s)
    assert not reads and not s.loads and not s.calls and not s.output.exists()
