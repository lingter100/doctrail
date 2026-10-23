"""Once-only C4 offline preparation and shared bounded artifact primitives.

Isolated validation preparation precedes selection, never authorizes inference.
Failures consume the exclusive output reservation and retain an immutable receipt.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import unicodedata
import uuid
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

from doctrail.meeting_answer_thinking import CANDIDATE_ID, prepare_answer
from doctrail.meeting_contract import AnswerRequest, strict_json
from doctrail.meeting_gguf import MAX_REQUEST_BYTES
from doctrail.meeting_thinking_review import COUNTS, FAMILIES, SourceDocument, validate_oracles
from doctrail.meeting_thinking_transport import request_body
from scripts.check_meeting_review_token_budget import load_tokenizer
from scripts.prepare_meeting_budget_inputs import (
    _tokenizer_metadata,
    canonical,
    encoded,
    sha,
    snapshot,
)
from scripts.prepare_meeting_plaintext_source_inventory import (
    HELPER_FILES,
    SERVICE_FILES,
    document_record,
)
from scripts.prepare_meeting_requirements_inputs import (
    JAVA_PARITY_FILES,
    check_prereview,
    validate_processing_receipts,
)
from scripts.probe_meeting_thinking_resources import count

ROOT = Path(__file__).resolve().parents[1]
BYTE_LIMIT = 16 * 1024 * 1024
PROTOCOL = "data/evaluation/meetings-c4-quality-protocol-v1.json"
REGISTRY = "data/evaluation/meetings-c4-family-registry-v1.json"
DESIGN = "docs/MEETINGS-C4-QUALITY-PLAN.md"
TOOLCHAIN_FREEZE = "data/evaluation/meetings-c4-quality-toolchain-freeze-v1.json"
CI_RECEIPT = "data/evaluation/meetings-c4-quality-toolchain-ci-v1.json"
RESOURCE_FREEZE = "data/evaluation/meetings-c4-compat-source-freeze-v1.json"
RESOURCE_REPORT = "experiments/results/meetings-c4-compat-resources-v1.json"
PINNED = {PROTOCOL: "dd9748639d948cce470ec175a5c1ee69bc7b1ba24ea440e684461fe284708cc4",
    "docs/MEETINGS-C4-QUALITY-IMPLEMENTATION-CONTRACT.md": "1109b25c559dc55705bd57f8860f49754c2321afab6508738b76c0dbeaa41416",
    REGISTRY: "509a155134383e989cf7eef174e8c563e0e19a8a7feb569e6d87e61439080858",
    DESIGN: "58926a02b4005b8653eb42ed9d8e7d6a6cbdd23bf6ee3602e4cf2af2095426b3",
    RESOURCE_FREEZE: "de8bfc6b92603b1cd5d999afb5788222c7b71ccda1e7a9a3c0aa5a7df36ef61e",
    RESOURCE_REPORT: "4221cf730c348b4ba6d5741f47a818e1c2ee68cdd337e21a05947d5379bd6043"}
NEW_MODULES = {"src/doctrail/meeting_answer_thinking.py", "src/doctrail/meeting_thinking_quality.py",
    "src/doctrail/meeting_thinking_review.py", "scripts/prepare_meeting_thinking_inputs.py",
    "scripts/probe_meeting_thinking_quality.py", "scripts/audit_meeting_thinking_quality.py"}
NEW_FILES = NEW_MODULES | {"tests/test_" + Path(n).stem + ".py" for n in NEW_MODULES}
PRIOR_FINGERPRINTS = "data/evaluation/meetings-c4-prior-source-fingerprints-v1.json"
FRESHNESS_METHOD = "nfc-whitespace-document-and-blank-line-paragraph-min200-v1"
ROLES = {"source": {"manifest", "inventory", "processing_receipt", "prereview", "java_parity", "freshness", "fingerprints"},
         "item": {"draft", "oracle", "context_selection", "prereview", "source_freeze", "code_freeze"}}


def now():
    return datetime.now(UTC).isoformat()


def path(name, root=ROOT):
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name or Path(name).is_absolute()
            or any(p in {"", ".", ".."} for p in name.split("/"))):
        raise ValueError("c4_relative_path")
    root = Path(root).resolve()
    current = root
    for part in name.split("/"):
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if current.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("c4_linked_path")
    if not current.resolve().is_relative_to(root):
        raise ValueError("c4_path_escape")
    return current


def phase_path(name, phase, root=ROOT):
    target = path(name, root)
    parts = Path(name).parts
    if phase not in COUNTS or not (len(parts) >= 4 and parts[:2] == ("data", "evaluation")
            and parts[2].startswith(f"meetings-c4-{phase}-") or len(parts) >= 3 and parts[0] == ".local"
            and parts[1].startswith(f"meetings-c4-{phase}-")):
        raise ValueError("c4_phase_path")
    return target


def digest(value, size=64):
    return isinstance(value, str) and re.fullmatch(rf"[a-f0-9]{{{size}}}", value) is not None


def ref(value, root=ROOT):
    if not isinstance(value, dict) or set(value) != {"file", "sha256"} or not digest(value["sha256"]):
        raise ValueError("c4_reference")
    return path(value["file"], root)


def separate(names, root=ROOT):
    targets = [path(n, root) for n in names]
    for i, target in enumerate(targets):
        for prior in targets[:i]:
            if (target.is_relative_to(prior) or prior.is_relative_to(target)
                    or target.exists() and prior.exists() and target.samefile(prior)):
                raise ValueError("c4_path_collision")


class Snapshots:
    def __init__(self, root=ROOT):
        self.root, self.raw, self.hashes, self.identities = Path(root), {}, {}, set()

    def get(self, name, expected=None):
        target = path(name, self.root)
        if name not in self.raw:
            info = target.stat()
            identity = (info.st_dev, info.st_ino)
            if (info.st_ino and identity in self.identities
                    or not info.st_ino and any(target.samefile(path(other, self.root)) for other in self.raw)):
                raise ValueError("c4_file_alias")
            raw, _ = snapshot(target)
            if info.st_ino:
                self.identities.add(identity)
            self.raw[name], self.hashes[name] = raw, sha(raw)
        if expected is not None and self.hashes[name] != expected:
            raise ValueError("c4_hash_changed")
        return self.raw[name]

    def read(self, reference):
        ref(reference, self.root)
        return strict_json(self.get(reference["file"], reference["sha256"]).decode("utf-8"))

    def json(self, name):
        return strict_json(self.get(name).decode("utf-8"))

    def unchanged(self):
        fresh = Snapshots(self.root)
        for name, value in self.hashes.items():
            fresh.get(name, value)


def write_new(name, value, root=ROOT):
    target = path(name, root)
    raw = value if isinstance(value, bytes) else encoded(value)
    if len(raw) > BYTE_LIMIT:
        raise ValueError("c4_artifact_size")
    with target.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def replace(name, value, root=ROOT):
    temp = name + "." + uuid.uuid4().hex + ".tmp"
    write_new(temp, value, root)
    os.replace(path(temp, root), path(name, root))


def committed(names, *, root=ROOT, revision="HEAD"):
    """Read-only local Git proof; output/error text never enters logs."""
    if revision != "HEAD" and not digest(revision, 40):
        raise ValueError("c4_commit_identity")
    for name in sorted(names):
        raw = snapshot(path(name, root))[0]
        result = subprocess.run(["git", "show", f"{revision}:{name}"], cwd=root,
                                capture_output=True, check=False, timeout=15)
        if result.returncode or result.stdout != raw:
            raise ValueError("c4_uncommitted_bytes")


class GitProof:
    """Cache Git object bytes only while HEAD and every observed worktree hash stay fixed."""
    def __init__(self, root=ROOT):
        self.root, self.head, self.proven = Path(root), None, {}

    def __call__(self, names, *, root=ROOT, revision="HEAD"):
        if Path(root) != self.root:
            raise ValueError("c4_git_root_changed")
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, check=False, timeout=15)
        head = result.stdout.decode("ascii").strip()
        if result.returncode or not digest(head, 40) or self.head is not None and head != self.head:
            raise ValueError("c4_git_head_changed")
        self.head = head
        for name in sorted(names):
            current = sha(snapshot(path(name, root))[0])
            key = (revision, name)
            if key not in self.proven:
                committed([name], root=root, revision=revision)
                self.proven[key] = current
            elif current != self.proven[key]:
                raise ValueError("c4_git_bytes_changed")


def source_files(root=ROOT):
    """Static recursive import closure, including lazy and relative imports."""
    pending, found = list(NEW_FILES), set()
    while pending:
        name = pending.pop()
        if name in found:
            continue
        found.add(name)
        tree = ast.parse(snapshot(path(name, root))[0])
        package = Path(name).with_suffix("").parts[:-1]
        if package[0] == "src":
            package = package[1:]
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = package[:len(package) - node.level + 1] if node.level else ()
                module = ".".join((*base, *((node.module or "").split("."))))
                modules = [module, *(module + "." + a.name for a in node.names)]
            for module in modules:
                parts = module.split(".")
                candidates = [module.replace(".", "/") + ".py"]
                candidates += ["/".join(parts[:n]) + "/__init__.py" for n in range(1, len(parts) + 1)]
                for candidate in candidates:
                    for prefix in ("", "src/"):
                        local = prefix + candidate
                        if path(local, root).is_file() and local not in found:
                            pending.append(local)
    return found | set(PINNED) | SERVICE_FILES | HELPER_FILES | JAVA_PARITY_FILES | {"pyproject.toml", "uv.lock"}


def code_contract(snapshots, *, git=committed):
    for name, value in PINNED.items():
        snapshots.get(name, value)
    frozen = snapshots.json(TOOLCHAIN_FREEZE)
    compat = snapshots.json(RESOURCE_FREEZE)
    expected = source_files(snapshots.root) | set(compat["bound_files"])
    bound = frozen.get("bound_files", {})
    if (set(frozen) != {"schema_version", "candidate", "kind", "bound_files"}
            or type(frozen["schema_version"]) is not int or frozen["schema_version"] != 1
            or frozen["candidate"] != CANDIDATE_ID or frozen["kind"] != "toolchain"
            or set(bound) != expected or len(compat["bound_files"]) != 52
            or any(bound.get(n) != h for n, h in (PINNED | compat["bound_files"]).items())):
        raise ValueError("c4_code_freeze")
    for name, value in bound.items():
        if not digest(value):
            raise ValueError("c4_code_digest")
        snapshots.get(name, value)
    ci = snapshots.json(CI_RECEIPT)
    if (ci.get("source_freeze") != {"file": TOOLCHAIN_FREEZE, "sha256": snapshots.hashes[TOOLCHAIN_FREEZE]}
            or not digest(ci.get("head_sha"), 40) or not ci.get("runs")
            or any(type(r.get("run_id")) is not int or r["run_id"] <= 0 or r.get("head_sha") != ci["head_sha"]
                   or r.get("jobs") != {"backend": "success", "java-service": "success", "web": "success"} for r in ci["runs"])):
        raise ValueError("c4_ci_observation")
    git(set(bound) | {TOOLCHAIN_FREEZE}, root=snapshots.root, revision=ci["head_sha"])
    git(set(bound) | {TOOLCHAIN_FREEZE, CI_RECEIPT}, root=snapshots.root)
    return bound, ci


def freeze_contract(value, kind, phase, snapshots):
    extra = "toolchain_commit" if kind == "source" else "source_commit"
    if (set(value) != {"schema_version", "candidate", "phase", "kind", "bound_files", "files", extra}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["candidate"] != CANDIDATE_ID or value["phase"] != phase or value["kind"] != kind
            or set(value["files"]) != ROLES[kind] or not digest(value[extra], 40)
            or len(set(value["files"].values())) != len(value["files"])
            or not set(value["files"].values()) <= set(value["bound_files"])):
        raise ValueError("c4_freeze_contract")
    for name, value_hash in value["bound_files"].items():
        if not digest(value_hash):
            raise ValueError("c4_freeze_digest")
        metadata_names = {PRIOR_FINGERPRINTS, *[f"data/evaluation/meetings-c4-{p}-source-fingerprints-v1.json" for p in COUNTS]}
        if name != TOOLCHAIN_FREEZE and not (kind == "source" and name in metadata_names):
            phase_path(name, phase, snapshots.root)
    return value["files"]


def validate_draft(value, phase):
    if (set(value) != {"schema_version", "phase", "cases"} or type(value["schema_version"]) is not int
            or value["schema_version"] != 1 or value["phase"] != phase or phase not in COUNTS
            or len(value["cases"]) != COUNTS[phase]):
        raise ValueError("c4_draft_contract")
    expected = [f"C4-{'CAL' if phase == 'calibration' else 'VAL'}-{i:02d}" for i in range(1, COUNTS[phase] + 1)]
    if [c["id"] for c in value["cases"]] != expected:
        raise ValueError("c4_case_ids")
    for case in value["cases"]:
        if set(case) != {"id", "payload", "response_language"} or case["response_language"] not in {"ko", "en"}:
            raise ValueError("c4_case_contract")
        request = AnswerRequest.model_validate(case["payload"])
        if not request.contexts or canonical(request.model_dump(exclude_unset=True)) != canonical(case["payload"]):
            raise ValueError("c4_payload_coercion")
    return value


def source_fingerprints(manifest, documents):
    """No historical bodies: exact normalized documents and >=200-character paragraphs."""
    rows = []
    lookup = {s["document_id"]: s for f in manifest["families"] for s in f["sources"]}
    for document in documents:
        source = lookup[document["document_id"]]
        text = unicodedata.normalize("NFC", document["content"].replace("\r\n", "\n").replace("\r", "\n"))
        normalized = " ".join(text.split())
        paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text)]
        rows.append({"document_id": document["document_id"], "family_id": document["family_id"],
            "url": source.get("immutable_url"), "revision_identity": source.get("git_blob_sha1") or source["raw_sha256"],
            "raw_sha256": source["raw_sha256"], "normalized_sha256": sha(normalized.encode()),
            "long_paragraph_sha256": sorted({sha(p.encode()) for p in paragraphs if len(p) >= 200})})
    return {"schema_version": 1, "phase": manifest["phase"], "method": FRESHNESS_METHOD, "documents": rows}


def validate_freshness(manifest, documents, source, snapshots, source_review):
    files, phase = source["files"], manifest["phase"]
    own = f"data/evaluation/meetings-c4-{phase}-source-fingerprints-v1.json"
    if files["fingerprints"] != own or PRIOR_FINGERPRINTS not in source["bound_files"]:
        raise ValueError("c4_freshness_paths")
    expected = source_fingerprints(manifest, documents)
    if canonical(snapshots.json(own)) != canonical(expected):
        raise ValueError("c4_fingerprint_replay")
    prior = snapshots.json(PRIOR_FINGERPRINTS)
    checks = snapshots.json(files["freshness"])
    prior_rows = prior.get("documents", [])
    if (prior.get("schema_version") != 1 or not isinstance(prior_rows, list)
            or not isinstance(prior.get("missing_historical_fingerprints"), list)
            or checks.get("method") != FRESHNESS_METHOD or checks.get("prior_metadata_sha256") != snapshots.hashes[PRIOR_FINGERPRINTS]
            or checks.get("fingerprints_sha256") != snapshots.hashes[own]
            or checks.get("missing_historical_fingerprints") != prior["missing_historical_fingerprints"]
            or checks.get("complete_near_duplicate_absence_proven") is not False
            or checks.get("reviewer_id") != source_review["reviewer_id"]
            or checks.get("semantic_freshness_verdict") != "accepted" or not checks.get("semantic_review_reason")):
        raise ValueError("c4_freshness_evidence")
    comparison = []
    if phase == "validation":
        other = "data/evaluation/meetings-c4-calibration-source-fingerprints-v1.json"
        if other not in source["bound_files"] or checks.get("other_split_sha256") != snapshots.hashes[other]:
            raise ValueError("c4_freshness_cross_split_binding")
        prior_split = snapshots.json(other)
        if prior_split.get("phase") != "calibration" or prior_split.get("method") != FRESHNESS_METHOD or len(prior_split.get("documents", [])) != 6:
            raise ValueError("c4_freshness_cross_split_metadata")
        comparison = prior_split["documents"]
    elif checks.get("other_split_sha256") is not None:
        raise ValueError("c4_freshness_order")
    shared = []
    for i, row in enumerate(expected["documents"]):
        for old in prior_rows:
            if any(row.get(k) is not None and row.get(k) == old.get(k) for k in
                   ("family_id", "url", "revision_identity", "raw_sha256", "normalized_sha256")):
                raise ValueError("c4_historical_source_reuse")
        for other in comparison + expected["documents"][:i]:
            common = sorted(set(row["long_paragraph_sha256"]) & set(other["long_paragraph_sha256"]))
            if row["normalized_sha256"] == other["normalized_sha256"] or common and row["family_id"] != other["family_id"]:
                raise ValueError("c4_new_source_duplicate")
            if common:
                shared.append({"documents": [other["document_id"], row["document_id"]],
                    "raw_sha256": [other["raw_sha256"], row["raw_sha256"]], "paragraph_sha256": common})
    approvals = checks.get("within_family_shared_paragraphs")
    if not isinstance(approvals, list) or len(approvals) != len(shared):
        raise ValueError("c4_shared_paragraph_review")
    for observed, approved in zip(shared, approvals, strict=True):
        if any(approved.get(k) != v for k, v in observed.items()) or approved.get("verdict") != "accepted_history_repetition" or not approved.get("reason"):
            raise ValueError("c4_shared_paragraph_review")


def load_material(phase, references, snapshots, code, ci, *, git=committed):
    """The caller establishes execution gate/metadata before this semantic boundary."""
    for key in ("draft", "oracle", "source_freeze", "item_freeze"):
        ref(references[key], snapshots.root)
        phase_path(references[key]["file"], phase, snapshots.root)
    separate([references[k]["file"] for k in ("draft", "oracle", "source_freeze", "item_freeze")], snapshots.root)
    source, item = snapshots.read(references["source_freeze"]), snapshots.read(references["item_freeze"])
    sf = freeze_contract(source, "source", phase, snapshots)
    it = freeze_contract(item, "item", phase, snapshots)
    if (source["toolchain_commit"] != ci["head_sha"] or it["code_freeze"] != TOOLCHAIN_FREEZE
            or any(it[k] != references[k]["file"] for k in ("draft", "oracle", "source_freeze"))
            or set(item["bound_files"]) != set(it.values())
            or item["bound_files"].get(TOOLCHAIN_FREEZE) != snapshots.hashes[TOOLCHAIN_FREEZE]):
        raise ValueError("c4_material_binding")
    # Namespace and Git proofs precede parsing every source/item body.
    git(set(source["bound_files"]) | {references["source_freeze"]["file"]}, root=snapshots.root, revision=item["source_commit"])
    git(set(source["bound_files"]) | set(item["bound_files"]) | {r["file"] for r in references.values()}, root=snapshots.root)
    for frozen in (source, item):
        for name, value in frozen["bound_files"].items():
            snapshots.get(name, value)
    manifest, inventory = snapshots.json(sf["manifest"]), snapshots.json(sf["inventory"])
    if (manifest.get("phase") != phase or inventory.get("phase") != phase
            or inventory.get("source_processing_version") != 2 or inventory.get("mode") != "adopted-all"
            or inventory.get("excluded_sources") != []
            or {f["family_id"] for f in manifest["families"]} != set(FAMILIES[phase])
            or len(manifest["families"]) != 2
            or inventory.get("manifest_sha256") != snapshots.hashes[sf["manifest"]]):
        raise ValueError("c4_source_composition")
    raw_names = {s["local_raw_snapshot"] for f in manifest["families"] for s in f["sources"]}
    metadata_names = {PRIOR_FINGERPRINTS}
    if phase == "validation":
        metadata_names.add("data/evaluation/meetings-c4-calibration-source-fingerprints-v1.json")
    if set(source["bound_files"]) != set(sf.values()) | raw_names | metadata_names:
        raise ValueError("c4_source_bindings")
    documents, authors, descriptions = [], set(), {}
    for family in manifest["families"]:
        origin = "public" if family["family_id"] in {"c4-f01", "c4-f03"} else "synthetic"
        if family.get("origin") != origin or len(family["sources"]) != 3 or family.get("source_suitability", {}).get("verdict") != "ADOPTED":
            raise ValueError("c4_source_family")
        info = []
        for source_row in family["sources"]:
            info.append(SourceDocument.model_validate({k: source_row[k] for k in
                ("document_id", "revision", "kind", "language", "meeting_date")}).model_dump())
            author = source_row.get("adoption_author_role")
            if not isinstance(author, str) or not author:
                raise ValueError("c4_source_author")
            authors.add(author)
            if origin == "synthetic":
                provenance = source_row["synthetic_provenance"]
                if provenance.get("fictional") is not True or provenance.get("ai_authored") is not True:
                    raise ValueError("c4_synthetic_provenance")
                authors.add(provenance["author_role"])
            elif not digest(source_row.get("git_blob_sha1"), 40) or not source_row.get("license_id") or not family.get("license"):
                raise ValueError("c4_public_provenance")
            if (source_row.get("adoption_verdict") != f"ADOPTED_FOR_{phase.upper()}_SOURCE_WITH_REGISTERED_CONSTRAINTS"
                    or source_row.get("raw_encoding") != "UTF-8" or source_row.get("page", "missing") is not None
                    or not source_row.get("title") or type(source_row.get("revision")) is not int or source_row["revision"] != 1):
                raise ValueError("c4_source_adoption")
            raw = snapshots.get(source_row["local_raw_snapshot"], source_row["raw_sha256"])
            documents.append(document_record(family, source_row, raw))
        descriptions[family["family_id"]] = info
    documents.sort(key=lambda d: d["registration_ordinal"])
    if (inventory.get("documents") != documents or [d["registration_ordinal"] for d in documents] != list(range(6))
            or len({d["document_id"] for d in documents}) != 6):
        raise ValueError("c4_inventory_replay")
    for role, filename in (("family_registry", REGISTRY), ("active_comparison_source_freeze", TOOLCHAIN_FREEZE)):
        if manifest.get(role) != {"path": filename, "sha256": snapshots.hashes[filename]}:
            raise ValueError("c4_manifest_binding")
    source_review = snapshots.json(sf["prereview"])
    check_prereview(source_review, [d["document_id"] for d in documents], authors=authors)
    validate_freshness(manifest, documents, source, snapshots, source_review)
    # Shared v2 processing/Java shapes are independent of C3 family IDs.
    validate_processing_receipts(manifest, inventory, snapshots.json(sf["processing_receipt"]),
        snapshots.json(sf["java_parity"]), documents, code, manifest_name=sf["manifest"],
        manifest_sha=snapshots.hashes[sf["manifest"]], inventory_sha=snapshots.hashes[sf["inventory"]], phase=phase)
    draft = validate_draft(snapshots.read(references["draft"]), phase)
    oracles = validate_oracles(draft, snapshots.read(references["oracle"]), phase)
    item_review = snapshots.json(it["prereview"])
    item_authors = {a for o in oracles.cases for a in (o.question_author, o.oracle_author)}
    check_prereview(item_review, [c["id"] for c in draft["cases"]], authors=item_authors, partial_missing=True)
    if item_review.get("all_sufficient_alternatives_including_repeated_passages_checked") is not True:
        raise ValueError("c4_item_alternative_review")
    authors |= item_authors | {source_review["reviewer_id"], item_review["reviewer_id"]}
    chunks = {}
    for d in documents:
        for c in d["chunks"]:
            context = {k: d[k] for k in ("document_id", "revision", "title", "meeting_date")}
            context |= {k: c[k] for k in ("chunk_id", "text", "page", "start_offset", "end_offset")}
            chunks[c["chunk_id"]] = (d["family_id"], context)
    for case, oracle in zip(draft["cases"], oracles.cases, strict=True):
        if (oracle.independent_prereviewer != item_review["reviewer_id"]
                or [d.model_dump() for d in oracle.source_documents] != descriptions[oracle.family_id]
                or any(chunks.get(c["chunk_id"]) != (oracle.family_id, c) for c in case["payload"]["contexts"])):
            raise ValueError("c4_item_whole_context")
    selected = {"schema_version": 1, "phase": phase, "cases": [{"id": c["id"], "chunk_ids": [x["chunk_id"]
        for x in c["payload"]["contexts"]]} for c in draft["cases"]]}
    if canonical(snapshots.json(it["context_selection"])) != canonical(selected):
        raise ValueError("c4_context_selection")
    return draft, oracles, sorted(authors)


def prepare(phase, references, *, root=ROOT, loader=load_tokenizer, counter=count, git=committed):
    if git is committed:
        git = GitProof(root)
    if phase not in COUNTS or set(references) != {"draft", "oracle", "source_freeze", "item_freeze"}:
        raise ValueError("c4_preparation_arguments")
    for reference in references.values():
        ref(reference, root)
        phase_path(reference["file"], phase, root)
    output = f".local/meetings-c4-{phase}-prepared-v1"
    separate([output, *(r["file"] for r in references.values())], root)
    path(output, root).mkdir(parents=True, exist_ok=False)
    captures = Snapshots(root)
    report = {"schema_version": 1, "candidate": CANDIDATE_ID, "phase": phase, "status": "failed",
        "references": references, "cases": [], "errors": [], "model_calls": 0, "native_calls": 0,
        "downloads": 0, "tokenizer_loads": 0, "payloads_preserved": False, "input_sha256": None}
    input_bytes = None
    try:
        code, ci = code_contract(captures, git=git)
        report["bound_files"] = code
        draft, _, authors = load_material(phase, references, captures, code, ci, git=git)
        report["excluded_authors"] = authors
        with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
            report["tokenizer_loads"] = 1
            tokenizer, metadata = loader(False)
            _tokenizer_metadata(metadata)
            report["tokenizer"] = metadata
            for case in draft["cases"]:
                row = {"id": case["id"], "payload_sha256": sha(canonical(case["payload"])), "input_tokens": None, "error": None}
                report["cases"].append(row)
                try:
                    prepared = prepare_answer(case["payload"], case["response_language"])
                    n, prompt_sha = counter(tokenizer, prepared.messages)
                    row.update(input_tokens=n, prompt_sha256=prompt_sha,
                        messages_sha256=sha(canonical(prepared.messages)), schema_sha256=sha(canonical(prepared.schema)),
                        native_request_bytes=len(json.dumps(request_body(prepared.messages, prepared.schema)).encode()))
                    if type(n) is not int or not 0 < n <= 5120 or not digest(prompt_sha) or row["native_request_bytes"] > MAX_REQUEST_BYTES:
                        raise ValueError("count_or_size")
                except Exception:  # noqa: BLE001 - never expose question/tokenizer diagnostics
                    row["error"] = "input_preparation_failed"
        report["payloads_preserved"] = True
        if any(row["error"] for row in report["cases"]):
            raise ValueError("survey_failed")
        prepared_input = {**draft, "cases": [{**c, "official_input_tokens": r["input_tokens"], "prompt_sha256": r["prompt_sha256"]}
            for c, r in zip(draft["cases"], report["cases"], strict=True)]}
        input_bytes = encoded(prepared_input)
        captures.unchanged()
        git(captures.hashes, root=root)
        report.update(status="passed", input_sha256=sha(input_bytes))
    except Exception:  # noqa: BLE001 - exclusive failure receipt, no retries or body logs
        report["errors"].append("preparation_failed_closed")
    report["snapshots"] = captures.hashes
    report["summary"] = {"planned": COUNTS[phase], "measured": sum(type(r["input_tokens"]) is int for r in report["cases"]),
                         "failed": sum(r["error"] is not None for r in report["cases"])}
    if report["status"] == "passed":
        try:
            write_new(output + "/input.json", input_bytes, root)
        except Exception:  # noqa: BLE001
            report.update(status="failed", input_sha256=None)
            report["errors"].append("input_write_failed")
    write_new(output + "/receipt.json", report, root)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=COUNTS, required=True)
    for name in ("draft", "oracle", "source-freeze", "item-freeze"):
        parser.add_argument("--" + name, required=True)
        parser.add_argument("--" + name + "-sha256", required=True)
    args = parser.parse_args(argv)
    references = {name: {"file": getattr(args, name), "sha256": getattr(args, name + "_sha256")}
                  for name in ("draft", "oracle", "source_freeze", "item_freeze")}
    try:
        result = prepare(args.phase, references)
        print(json.dumps({"status": result["status"], "summary": result["summary"]}))
        return 0 if result["status"] == "passed" else 1
    except Exception:  # noqa: BLE001
        print('{"status":"failed_closed"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
