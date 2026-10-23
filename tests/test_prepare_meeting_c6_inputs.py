"""Synthetic preparation; fake tokenizer and isolated remote-free Git fixtures."""
import copy
import hashlib
import io
import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from scripts import prepare_meeting_c6_inputs as prep
from tests.test_meeting_c6_review import corpus


def write(target, value):
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, bytes) else prep.encoded(value)
    target.write_bytes(raw)
    return prep.sha(raw)


def reference(root, name):
    return {"file": name, "sha256": prep.sha((root / name).read_bytes())}


def tokenizer_metadata():
    return {"repo_id": "Qwen/Qwen3.5-9B", "revision": "c202236235762e1c871ad0ccb60c8ee5ba337b9a",
        "transformers_version": "synthetic", "assets_sha256": {k: "a" * 64 for k in
            ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja")}, "trust_remote_code": False, "download_authorized": False}


@pytest.fixture
def material(tmp_path):
    code = {}
    for name in prep.SERVICE_FILES | prep.HELPER_FILES | prep.JAVA_PARITY_FILES:
        code[name] = write(tmp_path / name, b"synthetic source binding")
    write(tmp_path / prep.TOOLCHAIN_FREEZE, {"schema_version": 1, "candidate": prep.CANDIDATE_ID, "kind": "toolchain", "bound_files": code})
    ci = {"head_sha": "a" * 40}
    write(tmp_path / prep.CI_RECEIPT, ci)
    write(tmp_path / prep.REGISTRY, {"synthetic_registry": True})
    write(tmp_path / prep.PRIOR_FINGERPRINTS, {"schema_version": 1, "documents": [{"family_id": "closed-synthetic-test-family"}],
        "missing_historical_fingerprints": ["Synthetic fixture lacks historical text fingerprints; no global near-duplicate claim."]})
    write(tmp_path / prep.ROLE_REGISTRATION, {"schema_version": 1, "candidate_id": prep.CANDIDATE_ID,
        "same_split_reuse_disclosed": False, "assignments": [{"phase": phase, "role": role,
            "role_id": identity if phase == "calibration" else identity + "-val",
            "actual_model": "gpt-6-astra", "actual_effort": "xhigh", "accepted": True,
            "accepted_at": "2000-01-01T00:00:00+00:00", "prior_exposure": [],
            "allowed_paths": [f"data/evaluation/meetings-c6-{phase}-synthetic/record.json"],
            "starts_after_commit": "a" * 40} for phase in prep.COUNTS for role, identity in
            (("source_author", "source-writer"), ("source_prereviewer", "source-reviewer"),
             ("item_author", "writer"), ("item_prereviewer", "item-reviewer"))]})
    git_calls = []
    def git(names, **kwargs):
        git_calls.append((set(names), kwargs))
    def fake_code(snapshots, **kwargs):
        snapshots.get(prep.TOOLCHAIN_FREEZE)
        snapshots.get(prep.CI_RECEIPT)
        snapshots.get(prep.REGISTRY)
        for name, digest in code.items():
            snapshots.get(name, digest)
        return code, ci
    def build(phase="calibration"):
        draft, oracle = corpus(phase)
        if phase == "validation":
            for row in oracle["cases"]:
                for key in ("question_author", "oracle_author", "independent_prereviewer"):
                    row[key] += "-val"
        prefix = f"data/evaluation/meetings-c6-{phase}-synthetic"
        names = {role: prefix + "/" + role + ".json" for role in prep.ROLES["source"] | prep.ROLES["item"]}
        names["fingerprints"] = f"data/evaluation/meetings-c6-{phase}-source-fingerprints-v1.json"
        names["code_freeze"] = prep.TOOLCHAIN_FREEZE
        names["item_freeze"] = prefix + "/item-freeze.json"
        names["source_freeze"] = prefix + "/source-freeze.json"
        # Source and item independent reviews must have distinct files.
        names["source_prereview"] = prefix + "/source-prereview.json"
        families, documents, raw_names = [], [], []
        for family_index, family_id in enumerate(prep.FAMILIES[phase]):
            case = next(c for c, o in zip(draft["cases"], oracle["cases"], strict=True) if o["family_id"] == family_id)
            family = {"family_id": family_id, "origin": "public" if family_index == 0 else "synthetic",
                "source_suitability": {"verdict": "ADOPTED"}, "repository": "synthetic/repository", "immutable_commit": "b" * 40,
                "license": {"id": "MIT", "synthetic_fixture": True}, "sources": []}
            source_description = next(o["source_documents"] for o in oracle["cases"] if o["family_id"] == family_id)
            for index, context in enumerate(case["payload"]["contexts"]):
                raw = context["text"].encode()
                raw_name = prefix + f"/raw/{family_id}-{index}.txt"
                write(tmp_path / raw_name, raw)
                raw_names.append(raw_name)
                description = source_description[index]
                source = {**description, "source_id": context["document_id"], "registration_ordinal": len(documents),
                    "title": context["title"], "page": None, "path": f"{family_id}-{index}.txt", "local_raw_snapshot": raw_name,
                    "adoption_verdict": f"ADOPTED_FOR_{phase.upper()}_SOURCE_WITH_REGISTERED_CONSTRAINTS",
                    "adoption_author_role": ("source-writer" + ("-val" if phase == "validation" else "")), "raw_encoding": "UTF-8", "raw_size_bytes": len(raw),
                    "raw_sha256": prep.sha(raw), "processed_codepoints": len(context["text"]), "processed_sha256": prep.sha(raw),
                    "bom": False, "lf_count": 0, "cr_count": 0, "trailing_lf": False, "nfc_identity_verified": True,
                    "service_normalization_identity_verified": True, "license_id": "MIT", "immutable_url": f"https://example.invalid/{family_id}/{index}",
                    "git_blob_sha1": hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() if family_index == 0 else None}
                if family_index:
                    source["synthetic_provenance"] = {"ai_authored": True, "fictional": True, "author_role": ("source-writer" + ("-val" if phase == "validation" else "")), "notice": "Synthetic"}
                    source.pop("immutable_url")
                family["sources"].append(source)
                documents.append(prep.document_record(family, source, raw))
            families.append(family)
        protocol = {"id": "synthetic-processing", "existing_service_reference_sha256": {n: code[n] for n in prep.SERVICE_FILES},
            "chunk_algorithm": __import__("scripts.prepare_meeting_plaintext_source_inventory", fromlist=["CHUNK_CONTRACT"]).CHUNK_CONTRACT,
            "chunk_id_format": "{document_id}-r1-c{ordinal:04d}"}
        manifest = {"schema_version": 1, "phase": phase, "families": families, "processing_protocol": protocol,
            "family_registry": {"path": prep.REGISTRY, "sha256": reference(tmp_path, prep.REGISTRY)["sha256"]},
            "active_comparison_source_freeze": {"path": prep.TOOLCHAIN_FREEZE, "sha256": reference(tmp_path, prep.TOOLCHAIN_FREEZE)["sha256"]}}
        write(tmp_path / names["manifest"], manifest)
        inventory = {"schema_version": 1, "source_processing_version": 2, "phase": phase, "mode": "adopted-all",
            "manifest_sha256": reference(tmp_path, names["manifest"])["sha256"], "documents": documents, "excluded_sources": []}
        write(tmp_path / names["inventory"], inventory)
        counts = {"registered_sources": 6, "processed_documents": 6, "chunks": 6, "excluded_sources": 0,
            "selected_contexts": 0, "questions": 0, "oracles": 0, "synthetic_bodies_authored": 0,
            "tokenizer_runs": 0, "model_calls": 0, "downloads": 0, "human_reviews": 0}
        rows = [{k: d[k] for k in ("source_id", "document_id", "revision", "raw_sha256", "raw_size_bytes", "git_blob_sha1", "processed_sha256", "processed_codepoints")}
                | {"chunks": len(d["chunks"])} for d in documents]
        processing = {"schema_version": 1, "source_processing_version": 2, "phase": phase, "mode": "adopted-all",
            "manifest": {"path": names["manifest"], "sha256": reference(tmp_path, names["manifest"])["sha256"]},
            "bound_files": {n: code[n] for n in prep.SERVICE_FILES | prep.HELPER_FILES},
            "references": {r: manifest[r] for r in ("family_registry", "active_comparison_source_freeze")},
            "inventory_sha256": reference(tmp_path, names["inventory"])["sha256"], "processing_protocol": protocol["id"],
            "documents": rows, "excluded_sources": [], "counts": counts, "java_parity_verified": False}
        write(tmp_path / names["processing_receipt"], processing)
        parity = {"schema_version": 1, "kind": "actual_java_python_document_chunk_parity", "inventory_sha256": reference(tmp_path, names["inventory"])["sha256"],
            "java_version": "21.0.1", "bound_files": {n: code[n] for n in prep.JAVA_PARITY_FILES},
            "documents": [{"document_id": d["document_id"], "raw_sha256": d["raw_sha256"], "processed_sha256": d["processed_sha256"], "codepoints": d["processed_codepoints"], "chunks": len(d["chunks"])} for d in documents],
            "document_count": 6, "chunk_count": 6, "exact_content_pages_chunk_text_offsets_ordinals_ids": True, "model_calls": 0, "semantic_quality_measured": False}
        write(tmp_path / names["java_parity"], parity)
        source_review = {"schema_version": 1, "verdict": "accepted", "rejected_ids": [], "accepted_ids": [d["document_id"] for d in documents],
                         "author_ids": [("source-writer" + ("-val" if phase == "validation" else ""))], "reviewer_id": ("source-reviewer" + ("-val" if phase == "validation" else "")), "human_review_count": 0}
        write(tmp_path / names["source_prereview"], source_review)
        fingerprints = prep.source_fingerprints(manifest, documents)
        write(tmp_path / names["fingerprints"], fingerprints)
        freshness = {"method": prep.FRESHNESS_METHOD, "prior_metadata_sha256": reference(tmp_path, prep.PRIOR_FINGERPRINTS)["sha256"],
            "fingerprints_sha256": reference(tmp_path, names["fingerprints"])["sha256"],
            "missing_historical_fingerprints": json.loads((tmp_path / prep.PRIOR_FINGERPRINTS).read_bytes())["missing_historical_fingerprints"],
            "complete_near_duplicate_absence_proven": False, "reviewer_id": ("source-reviewer" + ("-val" if phase == "validation" else "")), "semantic_freshness_verdict": "accepted",
            "semantic_review_reason": "New synthetic test only.", "within_family_shared_paragraphs": [], "other_split_sha256": None}
        extra = {prep.PRIOR_FINGERPRINTS}
        if phase == "validation":
            other = "data/evaluation/meetings-c6-calibration-source-fingerprints-v1.json"
            freshness["other_split_sha256"] = reference(tmp_path, other)["sha256"]
            extra.add(other)
        write(tmp_path / names["freshness"], freshness)
        source_files = {r: names[r] for r in prep.ROLES["source"]}
        source_files["prereview"] = names["source_prereview"]
        source = {"schema_version": 1, "candidate": prep.CANDIDATE_ID, "phase": phase, "kind": "source", "toolchain_commit": "a" * 40,
                  "files": source_files, "bound_files": {n: reference(tmp_path, n)["sha256"] for n in set(source_files.values()) | set(raw_names) | extra}}
        write(tmp_path / names["source_freeze"], source)
        write(tmp_path / names["draft"], draft)
        write(tmp_path / names["oracle"], oracle)
        write(tmp_path / names["context_selection"], {"schema_version": 1, "phase": phase, "cases": [{"id": c["id"], "chunk_ids": [x["chunk_id"] for x in c["payload"]["contexts"]]} for c in draft["cases"]]})
        write(tmp_path / names["prereview"], {"schema_version": 1, "verdict": "accepted", "rejected_ids": [], "accepted_ids": [c["id"] for c in draft["cases"]],
            "author_ids": [("writer" + ("-val" if phase == "validation" else ""))], "reviewer_id": ("item-reviewer" + ("-val" if phase == "validation" else "")), "human_review_count": 0, "whole_family_absence_checked": True,
            "all_sufficient_alternatives_including_repeated_passages_checked": True})
        item_files = {r: names[r] for r in prep.ROLES["item"]}
        item = {"schema_version": 1, "candidate": prep.CANDIDATE_ID, "phase": phase, "kind": "item", "source_commit": "b" * 40,
                "files": item_files, "bound_files": {n: reference(tmp_path, n)["sha256"] for n in item_files.values()}}
        write(tmp_path / names["item_freeze"], item)
        refs = {k: reference(tmp_path, names[k]) for k in ("draft", "oracle", "source_freeze", "item_freeze")}
        return SimpleNamespace(root=tmp_path, phase=phase, draft=draft, oracle=oracle, source=source, item=item,
            names=names, refs=refs, code=code, ci=ci, git=git, git_calls=git_calls, manifest=manifest,
            documents=documents, contract=fake_code)
    return build


def run(data, *, counter=None):
    from tests.test_meeting_thinking_quality import PROMPT
    return prep.prepare(data.phase, data.refs, root=data.root, git=data.git, contract=data.contract,
        loader=lambda allow: (None, tokenizer_metadata()), counter=counter or (lambda *a: (100, prep.sha(PROMPT.encode()))))


def test_prepare_preserves_complete_payload_and_is_once_only(material):
    data = material()
    result = run(data)
    assert result["status"] == "passed", result
    prepared = json.loads((data.root / ".local/meetings-c6-calibration-prepared-v1/input.json").read_bytes())
    assert [{k: c[k] for k in ("id", "payload", "response_language")} for c in prepared["cases"]] == data.draft["cases"]
    assert result["summary"] == {"planned": 6, "measured": 6, "failed": 0}
    assert data.git_calls
    with pytest.raises(FileExistsError):
        run(data)


@pytest.mark.parametrize("n", [5121, 0, True, 1.5])
def test_failed_survey_preserves_all_measurements_and_consumes_reservation(material, n):
    data = material()
    calls = []
    def count(*args):
        calls.append(1)
        return n, "a" * 64
    result = run(data, counter=count)
    assert result["status"] == "failed" and len(calls) == 6 and result["payloads_preserved"]
    assert not (data.root / ".local/meetings-c6-calibration-prepared-v1/input.json").exists()
    with pytest.raises(FileExistsError):
        run(data)


@pytest.mark.parametrize("n", [4096, 4097, 5120])
def test_offline_budget_inclusive_boundary(material, n):
    result = run(material(), counter=lambda *a: (n, "a" * 64))
    assert result["status"] == "passed"


@pytest.mark.parametrize("key,value", [("kind", "meeting"), ("language", "ko"), ("meeting_date", "2026-01-03")])
def test_oracle_source_labels_must_equal_adopted_manifest(material, key, value):
    data = material()
    for oracle in data.oracle["cases"]:
        if oracle["family_id"] == "c6-f01":
            oracle["source_documents"][0][key] = value
    write(data.root / data.names["oracle"], data.oracle)
    data.item["bound_files"][data.names["oracle"]] = reference(data.root, data.names["oracle"])["sha256"]
    write(data.root / data.names["item_freeze"], data.item)
    data.refs = {k: reference(data.root, data.names[k]) for k in data.refs}
    assert run(data)["status"] == "failed"


def test_source_byte_tamper_prevents_tokenizer(material):
    data = material()
    raw = data.manifest["families"][0]["sources"][0]["local_raw_snapshot"]
    write(data.root / raw, b"changed source")
    result = prep.prepare(data.phase, data.refs, root=data.root, git=data.git, contract=data.contract,
                          loader=lambda *a: pytest.fail("tokenizer before source verification"))
    assert result["status"] == "failed" and result["tokenizer_loads"] == 0


def test_wrong_phase_path_rejected_before_any_snapshot(material):
    data = material()
    data.refs["oracle"]["file"] = "data/evaluation/meetings-c6-validation-source/raw.txt"
    data.contract = lambda *a, **k: pytest.fail("read other split")
    with pytest.raises(ValueError, match="phase_path"):
        run(data)


def test_full_validation_preparation_from_new_synthetic_sources(material):
    run(material())
    result = run(material("validation"))
    assert result["status"] == "passed" and result["summary"]["measured"] == 8


def test_fingerprint_normalization_and_common_long_paragraph():
    source = {"document_id": "a", "raw_sha256": "a" * 64}
    manifest = {"phase": "calibration", "families": [{"sources": [source]}]}
    document = {"document_id": "a", "family_id": "c6-f01", "content": "e\u0301\r\n\r\n" + "Long paragraph " * 30}
    first = prep.source_fingerprints(manifest, [document])
    document["content"] = "\u00e9\n\n" + "Long   paragraph " * 30
    second = prep.source_fingerprints(manifest, [document])
    assert first == second and len(first["documents"][0]["long_paragraph_sha256"]) == 1


def test_git_proof_caches_objects_but_checks_head_and_worktree(tmp_path):
    name = "synthetic.py"
    write(tmp_path / name, b"original")
    head, calls = ["a" * 40], []
    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=(head[0].encode() + b"\n") if command[1] == "rev-parse" else b"original")
    proof = prep.GitProof(tmp_path, runner=fake_run)
    proof([name], root=tmp_path)
    proof([name], root=tmp_path)
    assert sum(c[1] == "show" for c in calls) == 1
    write(tmp_path / name, b"drift")
    with pytest.raises(ValueError, match="git_bytes_changed"):
        proof([name], root=tmp_path)
    write(tmp_path / name, b"original")
    head[0] = "b" * 40
    with pytest.raises(ValueError, match="git_head_changed"):
        proof([name], root=tmp_path)


@pytest.mark.parametrize("name", ["../escape", "C:/outside", ".local/../body", "bad\\path"])
def test_path_guard(name, tmp_path):
    with pytest.raises(ValueError):
        prep.path(name, tmp_path)


@pytest.mark.parametrize("fault", [None, "missing-binding", "source-drift", "failed-ci", "wrong-head", "new-import",
                                  "missing-event", "duplicate-event", "in-progress"])
def test_code_freeze_exact_closure_and_ci_observation(tmp_path, fault):
    write(tmp_path / "scripts/seed.py", b"import scripts.negative\n")
    for name in ("pyproject.toml", "uv.lock"):
        write(tmp_path / name, b"synthetic environment")
    def manifest(root, **kwargs):
        return prep.source_manifest(root, seeds={"scripts/seed.py"}, pinned={}, extra_files=set(), **kwargs)
    frozen = manifest(tmp_path)
    if fault == "missing-binding":
        frozen["bound_files"].pop("uv.lock")
    freeze_sha = write(tmp_path / prep.TOOLCHAIN_FREEZE, frozen)
    ci = {"head_sha": "a" * 40, "source_freeze": {"file": prep.TOOLCHAIN_FREEZE, "sha256": freeze_sha},
        "runs": [{"run_id": i, "head_sha": "a" * 40, "event": event, "status": "completed", "conclusion": "success",
                  "url": f"https://github.com/synthetic/repo/actions/runs/{i}",
                  "jobs": {"backend": "success", "java-service": "success", "web": "success"}}
                 for i, event in enumerate(("push", "pull_request"), 1)]}
    if fault == "failed-ci":
        ci["runs"][0]["jobs"]["web"] = "failure"
    if fault == "wrong-head":
        ci["runs"][0]["head_sha"] = "b" * 40
    if fault == "missing-event":
        ci["runs"].pop()
    if fault == "duplicate-event":
        ci["runs"][1]["event"] = "push"
    if fault == "in-progress":
        ci["runs"][0]["status"] = "in_progress"
    write(tmp_path / prep.CI_RECEIPT, ci)
    if fault == "source-drift":
        write(tmp_path / "scripts/seed.py", b"changed")
    if fault == "new-import":
        write(tmp_path / "scripts/negative.py", b"never read this body")
    observed, reads = [], []
    snapshot = prep.snapshot
    def spy(target, **kwargs):
        reads.append(target)
        return snapshot(target, **kwargs)
    def git(names, **kwargs):
        observed.append((set(names), kwargs.get("revision", "HEAD")))
    if fault:
        with pytest.raises(ValueError):
            prep.code_contract(prep.Snapshots(tmp_path, reader=spy), git=git, manifest=manifest)
    else:
        actual, metadata = prep.code_contract(prep.Snapshots(tmp_path, reader=spy), git=git, manifest=manifest)
        assert actual == frozen["bound_files"] and metadata == ci
    assert observed[0] == ({prep.TOOLCHAIN_FREEZE}, "HEAD")
    assert tmp_path / "scripts/negative.py" not in reads


def refresh_fingerprints(data, documents, approvals=None):
    write(data.root / data.names["fingerprints"], prep.source_fingerprints(data.manifest, documents))
    freshness = json.loads((data.root / data.names["freshness"]).read_bytes())
    freshness["fingerprints_sha256"] = reference(data.root, data.names["fingerprints"])["sha256"]
    freshness["within_family_shared_paragraphs"] = approvals or []
    write(data.root / data.names["freshness"], freshness)
    captures = prep.Snapshots(data.root)
    captures.get(prep.PRIOR_FINGERPRINTS)
    return captures


@pytest.mark.parametrize("kind", ["whole", "cross-family"])
def test_fresh_source_duplicates_rejected_even_if_receipt_claims_acceptance(material, kind):
    data = material()
    documents = copy.deepcopy(data.documents)
    if kind == "whole":
        documents[1]["content"] = documents[0]["content"]
    else:
        shared = "Common synthetic paragraph " * 20
        documents[0]["content"] += "\n\n" + shared
        documents[3]["content"] += "\n\n" + shared
    captures = refresh_fingerprints(data, documents)
    with pytest.raises(ValueError, match="new_source_duplicate"):
        prep.validate_freshness(data.manifest, documents, data.source, captures, {"reviewer_id": "source-reviewer"})


def test_within_family_repeat_needs_exact_hash_doc_and_independent_review(material):
    data = material()
    documents = copy.deepcopy(data.documents)
    common = "Repeated fictional history " * 20
    for document in documents[:2]:
        document["content"] += "\n\n" + common
    captures = refresh_fingerprints(data, documents)
    with pytest.raises(ValueError, match="shared_paragraph_review"):
        prep.validate_freshness(data.manifest, documents, data.source, captures, {"reviewer_id": "source-reviewer"})
    approval = {"documents": [d["document_id"] for d in documents[:2]], "raw_sha256": [d["raw_sha256"] for d in documents[:2]],
        "paragraph_sha256": [prep.sha(common.strip().encode())], "verdict": "accepted_history_repetition", "reason": "Synthetic recurring history."}
    captures = refresh_fingerprints(data, documents, [approval])
    prep.validate_freshness(data.manifest, documents, data.source, captures, {"reviewer_id": "source-reviewer"})
    approval["raw_sha256"][0] = "f" * 64
    captures = refresh_fingerprints(data, documents, [approval])
    with pytest.raises(ValueError, match="shared_paragraph_review"):
        prep.validate_freshness(data.manifest, documents, data.source, captures, {"reviewer_id": "source-reviewer"})


def test_known_historical_fingerprint_reuse_fails_without_opening_old_body(material):
    data = material()
    record = prep.source_fingerprints(data.manifest, data.documents)["documents"][0]
    prior = json.loads((data.root / prep.PRIOR_FINGERPRINTS).read_bytes())
    prior["documents"] = [record]
    write(data.root / prep.PRIOR_FINGERPRINTS, prior)
    freshness = json.loads((data.root / data.names["freshness"]).read_bytes())
    freshness["prior_metadata_sha256"] = reference(data.root, prep.PRIOR_FINGERPRINTS)["sha256"]
    write(data.root / data.names["freshness"], freshness)
    with pytest.raises(ValueError, match="historical_source_reuse"):
        prep.validate_freshness(data.manifest, data.documents, data.source, prep.Snapshots(data.root), {"reviewer_id": "source-reviewer"})


def test_historical_long_paragraph_reuse_rejected_from_metadata_only(material):
    data = material()
    documents = copy.deepcopy(data.documents)
    shared = "Historical synthetic paragraph " * 20
    documents[0]["content"] += "\n\n" + shared
    prior = {"schema_version": 1, "documents": [{"family_id": "historical-family",
        "long_paragraph_sha256": [prep.sha(shared.strip().encode())]}], "missing_historical_fingerprints": []}
    write(data.root / prep.PRIOR_FINGERPRINTS, prior)
    captures = refresh_fingerprints(data, documents)
    freshness = json.loads((data.root / data.names["freshness"]).read_bytes())
    freshness["prior_metadata_sha256"] = reference(data.root, prep.PRIOR_FINGERPRINTS)["sha256"]
    freshness["missing_historical_fingerprints"] = []
    write(data.root / data.names["freshness"], freshness)
    with pytest.raises(ValueError, match="historical_paragraph_reuse"):
        prep.validate_freshness(data.manifest, documents, data.source, captures, {"reviewer_id": "source-reviewer"})


def test_negative_import_created_during_counting_closes_preparation(material):
    data = material()
    write(data.root / "scripts/synthetic_seed.py", b"import scripts.new_candidate\n")
    for name in ("pyproject.toml", "uv.lock"):
        write(data.root / name, b"synthetic environment")
    def manifest(root, **kwargs):
        return prep.source_manifest(root, seeds={"scripts/synthetic_seed.py"}, pinned={}, extra_files=set(), **kwargs)
    frozen = manifest(data.root)
    initial_code = data.contract
    def checked(snapshots, **kwargs):
        manifest(data.root, sealed=frozen)
        return initial_code(snapshots, **kwargs)
    data.contract = checked
    calls = []
    def counter(*args):
        from tests.test_meeting_thinking_quality import PROMPT
        calls.append(1)
        if len(calls) == 6:
            write(data.root / "scripts/new_candidate.py", b"never execute or read")
        return 100, prep.sha(PROMPT.encode())
    result = run(data, counter=counter)
    assert result["status"] == "failed" and len(calls) == 6
    assert not (data.root / ".local/meetings-c6-calibration-prepared-v1/input.json").exists()


def test_snapshot_identity_cache_still_rejects_hardlink_and_detects_drift(tmp_path):
    original, alias = tmp_path / "original", tmp_path / "alias"
    original.write_bytes(b"synthetic metadata")
    try:
        alias.hardlink_to(original)
    except OSError:
        pytest.skip("hardlinks unavailable on this filesystem")
    snapshots = prep.Snapshots(tmp_path)
    snapshots.get("original")
    with pytest.raises(ValueError, match="file_alias"):
        snapshots.get("alias")
    original.write_bytes(b"changed metadata")
    with pytest.raises(ValueError, match="hash_changed"):
        snapshots.unchanged()


@pytest.mark.parametrize("fault", ["not-accepted", "same-reviewer", "cross-split", "future-time"])
def test_actual_role_contract_rejects_before_material_bodies(material, fault):
    data = material()
    target = data.root / prep.ROLE_REGISTRATION
    roles = json.loads(target.read_bytes())
    row = roles["assignments"][0]
    if fault == "not-accepted":
        row["accepted"] = False
    elif fault == "same-reviewer":
        roles["assignments"][1]["role_id"] = row["role_id"]
    elif fault == "cross-split":
        roles["assignments"][4]["role_id"] = row["role_id"]
    else:
        row["accepted_at"] = "2999-01-01T00:00:00+00:00"
    write(target, roles)
    observed = []
    def spy(target, **kwargs):
        observed.append(target.relative_to(data.root).as_posix())
        return prep.snapshot(target, **kwargs)
    with pytest.raises(ValueError):
        prep.load_material("calibration", data.refs, prep.Snapshots(data.root, reader=spy), data.code, data.ci, git=data.git)
    assert data.names["draft"] not in observed and data.names["oracle"] not in observed


def synthetic_code_contract(root):
    write(root / "scripts/seed.py", b"import scripts.absent\n")
    for name in ("pyproject.toml", "uv.lock"):
        write(root / name, b"synthetic environment")
    def manifest(root, **kwargs):
        return prep.source_manifest(root, seeds={"scripts/seed.py"}, pinned={}, extra_files=set(), **kwargs)
    frozen = manifest(root)
    freeze_sha = write(root / prep.TOOLCHAIN_FREEZE, frozen)
    ci = {"head_sha": "a" * 40,
          "source_freeze": {"file": prep.TOOLCHAIN_FREEZE, "sha256": freeze_sha},
          "runs": [{"run_id": i, "head_sha": "a" * 40, "event": event, "status": "completed",
                    "conclusion": "success", "url": f"https://github.com/synthetic/repo/actions/runs/{i}",
                    "jobs": {"backend": "success", "java-service": "success", "web": "success"}}
                   for i, event in enumerate(("push", "pull_request"), 1)]}
    write(root / prep.CI_RECEIPT, ci)
    blobs = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    return manifest, blobs


def test_all_inner_caller_git_and_helper_reads_use_bounded_reader_with_same_consumers(tmp_path):
    from doctrail.meeting_bounded_snapshot import read_snapshot
    outputs = []
    for candidate in (False, True):
        root = tmp_path / str(candidate)
        root.mkdir()
        manifest, blobs = synthetic_code_contract(root)
        meter, reads, commands = prep.Meter(), [], []
        def reader(target, *, meter, candidate=candidate, reads=reads, root=root):
            reads.append(target.relative_to(root).as_posix())
            return read_snapshot(target, meter, candidate=candidate)
        def runner(command, commands=commands, blobs=blobs, **kwargs):
            commands.append(command[1:])
            raw = b"a" * 40 + b"\n" if command[1] == "rev-parse" else blobs[command[2].split(":", 1)[1]]
            return SimpleNamespace(returncode=0, stdout=raw)
        captures = prep.Snapshots(root, meter=meter, reader=reader)
        proof = prep.GitProof(root, meter=meter, reader=reader, runner=runner)
        result = prep.code_contract(captures, git=proof, manifest=manifest)
        outputs.append((result, list(reads), list(commands), meter.export()))
        assert meter.counts["snapshot_calls"] == 35
        assert reads[:3] == [prep.TOOLCHAIN_FREEZE] * 3
        assert reads[3:9] == ["scripts/seed.py", *reads[4:6]] * 2
        assert reads[-5:] == list(captures.hashes)
    assert outputs[0][:3] == outputs[1][:3]
    reference, candidate = outputs[0][3], outputs[1][3]
    for key in ("snapshot_calls", "open_calls", "stat_calls", "actual_read_returned_bytes", "close_calls"):
        assert reference["counts"][key] == candidate["counts"][key]
    assert set(reference["read_requested_lengths"]) == {str(prep.BYTE_LIMIT + 1)}
    assert set(candidate["read_requested_lengths"]) == {"65536"}


def test_default_c6_inner_and_caller_reader_is_bounded(tmp_path):
    manifest, _ = synthetic_code_contract(tmp_path)
    meter = prep.Meter()
    captures = prep.Snapshots(tmp_path, meter=meter)
    prep.code_contract(captures, git=lambda *a, **k: None, manifest=manifest)
    assert meter.counts["snapshot_calls"] > 10
    assert set(meter.read_requested_lengths) == {"65536"}
    proof_meter = prep.Meter()
    def runner(command, **kwargs):
        raw = b"a" * 40 + b"\n" if command[1] == "rev-parse" else (tmp_path / "scripts/seed.py").read_bytes()
        return SimpleNamespace(returncode=0, stdout=raw)
    proof = prep.GitProof(tmp_path, meter=proof_meter, runner=runner)
    proof(["scripts/seed.py"], root=tmp_path)
    proof(["scripts/seed.py"], root=tmp_path)
    assert proof_meter.counts["snapshot_calls"] == 3  # Current twice + committed-helper once.
    assert set(proof_meter.read_requested_lengths) == {"65536"}


@pytest.mark.parametrize("candidate", [False, True])
def test_observed_same_stamp_aba_on_final_fresh_read_rejected(tmp_path, candidate):
    from doctrail.meeting_bounded_snapshot import read_snapshot
    target = tmp_path / "metadata.json"
    original = b"original"
    target.write_bytes(original)
    calls = []
    def reader(path, *, meter):
        calls.append(path)
        if len(calls) == 2:
            before = path.stat()
            path.write_bytes(b"modified")
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        return read_snapshot(path, meter, candidate=candidate)
    captures = prep.Snapshots(tmp_path, reader=reader)
    captures.get(target.name)
    try:
        with pytest.raises(ValueError, match="hash_changed"):
            captures.unchanged()
    finally:
        target.write_bytes(original)
    assert len(calls) == 2


def test_c6_wrapper_overflow_before_stamp():
    class Target:
        stats = 0
        def stat(self):
            self.stats += 1
            return SimpleNamespace(st_dev=1, st_ino=2, st_size=3, st_mtime_ns=4, st_ctime_ns=self.stats)
        def open(self, mode):
            return io.BytesIO(b"x" * (prep.BYTE_LIMIT + 1))
    target = Target()
    with pytest.raises(ValueError, match="preparation_file_limit"):
        prep.snapshot(target)
    assert target.stats == 1


def test_c6_default_wrapper_continues_nonempty_short_reads():
    class Stream(io.BytesIO):
        def read(self, length):
            return super().read(min(length, 2))
    class Target:
        def stat(self):
            return SimpleNamespace(st_dev=1, st_ino=2, st_size=5, st_mtime_ns=4, st_ctime_ns=4)
        def open(self, mode):
            assert mode == "rb"
            return Stream(b"abcde")
    meter = prep.Meter()
    assert prep.snapshot(Target(), meter=meter)[0] == b"abcde"
    assert meter.counts["read_calls"] == 4 and meter.counts["stat_calls"] == 2
    assert meter.read_requested_lengths == {"65536": 4}


@pytest.mark.parametrize("fault", ["read", "close", "invalid", "oversized"])
def test_c6_default_wrapper_propagates_stream_failure_before_final_stamp(fault):
    class Stream:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            if fault == "close":
                raise OSError("synthetic close failure")
        def read(self, length):
            if fault == "read":
                raise OSError("synthetic read failure")
            if fault == "invalid":
                return None
            return b"x" * (length + 1) if fault == "oversized" else b""
    class Target:
        stats = 0
        def stat(self):
            self.stats += 1
            return SimpleNamespace(st_dev=1, st_ino=2, st_size=5, st_mtime_ns=4, st_ctime_ns=self.stats)
        def open(self, mode):
            return Stream()
    target = Target()
    with pytest.raises(OSError if fault in {"read", "close"} else ValueError):
        prep.snapshot(target)
    assert target.stats == 1


@pytest.mark.parametrize("candidate", [False, True])
def test_connected_reader_preserves_reference_detected_midread_mutation(candidate):
    from doctrail.meeting_bounded_snapshot import read_snapshot
    class Target:
        version = 0
        def stat(self):
            return SimpleNamespace(st_dev=1, st_ino=2, st_size=5, st_mtime_ns=self.version, st_ctime_ns=0)
        def open(self, mode):
            self.version += 1
            return io.BytesIO(b"abcde")
    target = Target()
    reader = prep.snapshot if candidate else lambda p: read_snapshot(p, prep.Meter(), candidate=False)
    with pytest.raises(ValueError, match="preparation_snapshot_changed"):
        reader(target)


def test_c6_path_rejects_symlink_before_bounded_read(tmp_path):
    target, link = tmp_path / "target", tmp_path / "linked"
    target.write_bytes(b"synthetic")
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("OS does not permit symbolic link creation")
    def forbidden(*args, **kwargs):
        pytest.fail("linked body read")
    with pytest.raises(ValueError, match="linked_path"):
        prep.Snapshots(tmp_path, reader=forbidden).get("linked")


def test_original_c6_safe_failure_code_survives_preparation_receipt(material):
    data = material()
    def denied(*args, **kwargs):
        raise ValueError("c6_code_allowlist")
    data.contract = denied
    report = run(data)
    assert report["status"] == "failed"
    assert report["first_failure"] == {"code": "c6_code_allowlist", "type": "ValueError"}
    persisted = json.loads((data.root / ".local/meetings-c6-calibration-prepared-v1/receipt.json").read_bytes())
    assert persisted["first_failure"] == report["first_failure"]


def test_input_write_failure_preserves_first_type_in_durable_receipt(material):
    data = material()
    def writer(name, value, root):
        if name.endswith("/input.json"):
            raise PermissionError("private path detail")
        return prep.write_new(name, value, root)
    result = prep.prepare(data.phase, data.refs, root=data.root, git=data.git,
        contract=data.contract, writer=writer, loader=lambda allow: (None, tokenizer_metadata()),
        counter=lambda *a: (100, "a" * 64))
    assert result["status"] == "failed"
    assert result["first_failure"] == {"code": "c6_failed_closed", "type": "PermissionError"}
    assert "private path" not in json.dumps(result)
    receipt = json.loads((data.root / ".local/meetings-c6-calibration-prepared-v1/receipt.json").read_bytes())
    assert receipt["first_failure"] == result["first_failure"]


def test_real_git_sealed_discovery_bytes_and_head_guards(tmp_path):
    manifest, _ = synthetic_code_contract(tmp_path)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
        GIT_AUTHOR_NAME="Synthetic C6", GIT_COMMITTER_NAME="Synthetic C6",
        GIT_AUTHOR_EMAIL="test@example.invalid", GIT_COMMITTER_EMAIL="test@example.invalid")
    def git(*args):
        result = subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "commit.gpgSign=false",
                                 "-c", "core.hooksPath=" + os.devnull, *args],
                                cwd=tmp_path, env=env, capture_output=True, timeout=15, check=True)
        return result.stdout.decode("ascii").strip()
    git("init", "--initial-branch=synthetic", "--template=")
    git("add", ".")
    git("commit", "-m", "Synthetic code fixture")
    source_head = git("rev-parse", "HEAD")
    ci_path = tmp_path / prep.CI_RECEIPT
    ci = json.loads(ci_path.read_bytes())
    ci["head_sha"] = source_head
    for row in ci["runs"]:
        row["head_sha"] = source_head
    write(ci_path, ci)
    git("add", ".")
    git("commit", "-m", "Synthetic CI metadata")
    assert git("remote") == ""
    reads = []
    def reader(target, **kwargs):
        reads.append(target.relative_to(tmp_path).as_posix())
        return prep.snapshot(target, **kwargs)
    proof = prep.GitProof(tmp_path, reader=reader)
    assert prep.code_contract(prep.Snapshots(tmp_path, reader=reader), git=proof, manifest=manifest)[1] == ci
    forbidden = tmp_path / "scripts/absent.py"
    forbidden.write_bytes(b"not Python; body must stay closed")
    reads.clear()
    with pytest.raises(ValueError, match="code_allowlist"):
        prep.code_contract(prep.Snapshots(tmp_path, reader=reader), git=proof, manifest=manifest)
    assert "scripts/absent.py" not in reads
    forbidden.unlink()
    seed = tmp_path / "scripts/seed.py"
    original = seed.read_bytes()
    seed.write_bytes(b"changed")
    with pytest.raises(ValueError, match="git_bytes_changed"):
        proof(["scripts/seed.py"], root=tmp_path)
    seed.write_bytes(original)
    git("commit", "--allow-empty", "-m", "Synthetic HEAD drift")
    with pytest.raises(ValueError, match="git_head_changed"):
        proof(["scripts/seed.py"], root=tmp_path)
