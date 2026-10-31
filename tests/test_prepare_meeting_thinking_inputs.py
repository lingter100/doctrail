"""Synthetic whole-source preparation fixtures; official tokenizer and Git are mocked."""
import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import prepare_meeting_thinking_inputs as prep
from tests.test_meeting_thinking_review import corpus


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
def material(tmp_path, monkeypatch):
    code = {}
    for name in prep.SERVICE_FILES | prep.HELPER_FILES | prep.JAVA_PARITY_FILES:
        code[name] = write(tmp_path / name, b"synthetic source binding")
    write(tmp_path / prep.TOOLCHAIN_FREEZE, {"schema_version": 1, "candidate": prep.CANDIDATE_ID, "kind": "toolchain", "bound_files": code})
    ci = {"head_sha": "a" * 40}
    write(tmp_path / prep.CI_RECEIPT, ci)
    write(tmp_path / prep.REGISTRY, {"synthetic_registry": True})
    write(tmp_path / prep.PRIOR_FINGERPRINTS, {"schema_version": 1, "documents": [{"family_id": "closed-synthetic-test-family"}],
        "missing_historical_fingerprints": ["Synthetic fixture lacks historical text fingerprints; no global near-duplicate claim."]})
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
    monkeypatch.setattr(prep, "code_contract", fake_code)
    def build(phase="calibration"):
        draft, oracle = corpus(phase)
        prefix = f"data/evaluation/meetings-c4-{phase}-synthetic"
        names = {role: prefix + "/" + role + ".json" for role in prep.ROLES["source"] | prep.ROLES["item"]}
        names["fingerprints"] = f"data/evaluation/meetings-c4-{phase}-source-fingerprints-v1.json"
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
                    "adoption_author_role": "source-writer", "raw_encoding": "UTF-8", "raw_size_bytes": len(raw),
                    "raw_sha256": prep.sha(raw), "processed_codepoints": len(context["text"]), "processed_sha256": prep.sha(raw),
                    "bom": False, "lf_count": 0, "cr_count": 0, "trailing_lf": False, "nfc_identity_verified": True,
                    "service_normalization_identity_verified": True, "license_id": "MIT", "immutable_url": f"https://example.invalid/{family_id}/{index}",
                    "git_blob_sha1": hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() if family_index == 0 else None}
                if family_index:
                    source["synthetic_provenance"] = {"ai_authored": True, "fictional": True, "author_role": "source-writer", "notice": "Synthetic"}
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
                         "author_ids": ["source-writer"], "reviewer_id": "source-reviewer", "human_review_count": 0}
        write(tmp_path / names["source_prereview"], source_review)
        fingerprints = prep.source_fingerprints(manifest, documents)
        write(tmp_path / names["fingerprints"], fingerprints)
        freshness = {"method": prep.FRESHNESS_METHOD, "prior_metadata_sha256": reference(tmp_path, prep.PRIOR_FINGERPRINTS)["sha256"],
            "fingerprints_sha256": reference(tmp_path, names["fingerprints"])["sha256"],
            "missing_historical_fingerprints": json.loads((tmp_path / prep.PRIOR_FINGERPRINTS).read_bytes())["missing_historical_fingerprints"],
            "complete_near_duplicate_absence_proven": False, "reviewer_id": "source-reviewer", "semantic_freshness_verdict": "accepted",
            "semantic_review_reason": "New synthetic test only.", "within_family_shared_paragraphs": [], "other_split_sha256": None}
        extra = {prep.PRIOR_FINGERPRINTS}
        if phase == "validation":
            other = "data/evaluation/meetings-c4-calibration-source-fingerprints-v1.json"
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
            "author_ids": ["writer"], "reviewer_id": "item-reviewer", "human_review_count": 0, "whole_family_absence_checked": True,
            "all_sufficient_alternatives_including_repeated_passages_checked": True})
        item_files = {r: names[r] for r in prep.ROLES["item"]}
        item = {"schema_version": 1, "candidate": prep.CANDIDATE_ID, "phase": phase, "kind": "item", "source_commit": "b" * 40,
                "files": item_files, "bound_files": {n: reference(tmp_path, n)["sha256"] for n in item_files.values()}}
        write(tmp_path / names["item_freeze"], item)
        refs = {k: reference(tmp_path, names[k]) for k in ("draft", "oracle", "source_freeze", "item_freeze")}
        return SimpleNamespace(root=tmp_path, phase=phase, draft=draft, oracle=oracle, source=source, item=item,
            names=names, refs=refs, code=code, ci=ci, git=git, git_calls=git_calls, manifest=manifest, documents=documents)
    return build


def run(data, *, counter=None):
    from tests.test_meeting_thinking_quality import PROMPT
    return prep.prepare(data.phase, data.refs, root=data.root, git=data.git,
        loader=lambda allow: (None, tokenizer_metadata()), counter=counter or (lambda *a: (100, prep.sha(PROMPT.encode()))))


def test_prepare_preserves_complete_payload_and_is_once_only(material):
    data = material()
    result = run(data)
    assert result["status"] == "passed", result
    prepared = json.loads((data.root / ".local/meetings-c4-calibration-prepared-v1/input.json").read_bytes())
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
    assert not (data.root / ".local/meetings-c4-calibration-prepared-v1/input.json").exists()
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
        if oracle["family_id"] == "c4-f01":
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
    result = prep.prepare(data.phase, data.refs, root=data.root, git=data.git, loader=lambda *a: pytest.fail("tokenizer before source verification"))
    assert result["status"] == "failed" and result["tokenizer_loads"] == 0


def test_wrong_phase_path_rejected_before_any_snapshot(material, monkeypatch):
    data = material()
    data.refs["oracle"]["file"] = "data/evaluation/meetings-c4-validation-source/raw.txt"
    monkeypatch.setattr(prep.Snapshots, "get", lambda *a: pytest.fail("read other split"))
    with pytest.raises(ValueError, match="phase_path"):
        run(data)


def test_full_validation_preparation_from_new_synthetic_sources(material):
    run(material())
    result = run(material("validation"))
    assert result["status"] == "passed" and result["summary"]["measured"] == 8


def test_fingerprint_normalization_and_common_long_paragraph():
    source = {"document_id": "a", "raw_sha256": "a" * 64}
    manifest = {"phase": "calibration", "families": [{"sources": [source]}]}
    document = {"document_id": "a", "family_id": "c4-f01", "content": "e\u0301\r\n\r\n" + "Long paragraph " * 30}
    first = prep.source_fingerprints(manifest, [document])
    document["content"] = "é\n\n" + "Long   paragraph " * 30
    second = prep.source_fingerprints(manifest, [document])
    assert first == second and len(first["documents"][0]["long_paragraph_sha256"]) == 1


def test_git_proof_caches_objects_but_checks_head_and_worktree(tmp_path, monkeypatch):
    name = "synthetic.py"
    write(tmp_path / name, b"original")
    head, calls = ["a" * 40], []
    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=(head[0].encode() + b"\n") if command[1] == "rev-parse" else b"original")
    monkeypatch.setattr(prep.subprocess, "run", fake_run)
    proof = prep.GitProof(tmp_path)
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


@pytest.mark.parametrize("fault", [None, "missing-binding", "source-drift", "failed-ci", "wrong-head"])
def test_code_freeze_exact_closure_and_ci_observation(tmp_path, monkeypatch, fault):
    frozen = {}
    for i in range(52):
        name = f"old/synthetic-{i}.py"
        frozen[name] = write(tmp_path / name, b"frozen synthetic code")
    pinned = {}
    for name in prep.PINNED:
        content = {"bound_files": frozen} if name == prep.RESOURCE_FREEZE else {"synthetic": name}
        pinned[name] = write(tmp_path / name, content)
    monkeypatch.setattr(prep, "PINNED", pinned)
    monkeypatch.setattr(prep, "source_files", lambda root: set(pinned))
    bound = frozen | pinned
    if fault == "missing-binding":
        bound.pop(next(iter(frozen)))
    freeze_sha = write(tmp_path / prep.TOOLCHAIN_FREEZE, {"schema_version": 1, "candidate": prep.CANDIDATE_ID,
        "kind": "toolchain", "bound_files": bound})
    ci = {"head_sha": "a" * 40, "source_freeze": {"file": prep.TOOLCHAIN_FREEZE, "sha256": freeze_sha},
        "runs": [{"run_id": 1, "head_sha": "a" * 40, "jobs": {"backend": "success", "java-service": "success", "web": "success"}}]}
    if fault == "failed-ci":
        ci["runs"][0]["jobs"]["web"] = "failure"
    if fault == "wrong-head":
        ci["runs"][0]["head_sha"] = "b" * 40
    write(tmp_path / prep.CI_RECEIPT, ci)
    if fault == "source-drift":
        write(tmp_path / next(iter(frozen)), b"changed")
    observed = []
    def git(names, **kwargs):
        observed.append((set(names), kwargs.get("revision", "HEAD")))
    if fault:
        with pytest.raises(ValueError):
            prep.code_contract(prep.Snapshots(tmp_path), git=git)
    else:
        actual, metadata = prep.code_contract(prep.Snapshots(tmp_path), git=git)
        assert actual == bound and metadata == ci
        assert observed[0][1] == "a" * 40 and observed[1][1] == "HEAD"
        assert prep.CI_RECEIPT in observed[1][0]


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
