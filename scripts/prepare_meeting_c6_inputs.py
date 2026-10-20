"""Once-only C6 offline preparation and shared bounded artifact primitives.

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

from doctrail.meeting_answer_thinking import CANDIDATE_ID as REUSED_POLICY_ID
from doctrail.meeting_answer_thinking import prepare_answer
from doctrail.meeting_bounded_snapshot import Meter, read_snapshot
from doctrail.meeting_c6_review import COUNTS, FAMILIES, SourceDocument, validate_oracles
from doctrail.meeting_contract import AnswerRequest, strict_json
from doctrail.meeting_gguf import MAX_REQUEST_BYTES
from doctrail.meeting_thinking_transport import MANIFEST_SHA256, request_body
from scripts.check_meeting_review_token_budget import load_tokenizer
from scripts.prepare_meeting_budget_inputs import (
    _tokenizer_metadata,
    canonical,
    encoded,
    sha,
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
from scripts.profile_meeting_host_proof import _module_candidates

ROOT = Path(__file__).resolve().parents[1]
BYTE_LIMIT = 16 * 1024 * 1024
CANDIDATE_ID = "meeting-answer-single-thinking-c6-v1"
PROTOCOL = "data/evaluation/meetings-c6-protocol-v1.json"
REGISTRY = "data/evaluation/meetings-c6-family-registry-v1.json"
DESIGN = "docs/MEETINGS-C6-PLAN.md"
TOOLCHAIN_FREEZE = "data/evaluation/meetings-c6-toolchain-freeze-v1.json"
CI_RECEIPT = "data/evaluation/meetings-c6-toolchain-ci-v1.json"
ROLE_REGISTRATION = "data/evaluation/meetings-c6-role-registration-v1.json"
PINNED = {PROTOCOL: "10f1ab558996f99b577bb61c533f4b202d73c25fbde42a94e674cb4d3201d691",
    REGISTRY: "f9625e2c7b492f6eabed77a89c1af068736c0922ef8377a8355ad4355cb0dd37",
    "data/models/meetings-generation-qwen35-v1.json": MANIFEST_SHA256,
    DESIGN: "792a9801fe0fd3c70fda4058f13375042b2e39800863b3335bdc98b14c4ed6b4"}
NEW_MODULES = {"src/doctrail/meeting_c6_review.py", "scripts/prepare_meeting_c6_inputs.py",
    "scripts/probe_meeting_c6_quality.py", "scripts/audit_meeting_c6_quality.py"}
NEW_FILES = NEW_MODULES | {"tests/test_" + Path(n).stem + ".py" for n in NEW_MODULES}
PRIOR_FINGERPRINTS = "data/evaluation/meetings-c6-prior-source-fingerprints-v1.json"
FRESHNESS_METHOD = "nfc-whitespace-document-and-blank-line-paragraph-min200-v1"
ROLES = {"source": {"manifest", "inventory", "processing_receipt", "prereview", "java_parity", "freshness", "fingerprints"},
         "item": {"draft", "oracle", "context_selection", "prereview", "source_freeze", "code_freeze"}}


def now():
    return datetime.now(UTC).isoformat()


def snapshot(target, *, meter=None):
    """The only production snapshot route: frozen reader, always bounded mode."""
    return read_snapshot(target, meter if meter is not None else Meter(), candidate=True)


def path(name, root=ROOT):
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name or Path(name).is_absolute()
            or any(p in {"", ".", ".."} for p in name.split("/"))):
        raise ValueError("c6_relative_path")
    root = Path(root).resolve()
    current = root
    for part in name.split("/"):
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if current.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("c6_linked_path")
    if not current.resolve().is_relative_to(root):
        raise ValueError("c6_path_escape")
    return current


def phase_path(name, phase, root=ROOT):
    target = path(name, root)
    parts = Path(name).parts
    if phase not in COUNTS or not (len(parts) >= 4 and parts[:2] == ("data", "evaluation")
            and parts[2].startswith(f"meetings-c6-{phase}-") or len(parts) >= 3 and parts[0] == ".local"
            and parts[1].startswith(f"meetings-c6-{phase}-")):
        raise ValueError("c6_phase_path")
    return target


def digest(value, size=64):
    return isinstance(value, str) and re.fullmatch(rf"[a-f0-9]{{{size}}}", value) is not None


def safe_failure(error):
    code = getattr(error, "code", None) or str(error)
    if not isinstance(code, str) or not re.fullmatch(r"(?:c6|generation|preparation)_[a-z0-9_]{1,90}", code):
        code = "c6_failed_closed"
    return {"code": code, "type": type(error).__name__}


def ref(value, root=ROOT):
    if not isinstance(value, dict) or set(value) != {"file", "sha256"} or not digest(value["sha256"]):
        raise ValueError("c6_reference")
    return path(value["file"], root)


def separate(names, root=ROOT):
    targets = [path(n, root) for n in names]
    for i, target in enumerate(targets):
        for prior in targets[:i]:
            if (target.is_relative_to(prior) or prior.is_relative_to(target)
                    or target.exists() and prior.exists() and target.samefile(prior)):
                raise ValueError("c6_path_collision")


class Snapshots:
    def __init__(self, root=ROOT, *, meter=None, reader=snapshot):
        self.root, self.raw, self.hashes, self.identities = Path(root), {}, {}, set()
        self.meter, self.reader = meter if meter is not None else Meter(), reader

    def get(self, name, expected=None):
        target = path(name, self.root)
        if name not in self.raw:
            info = target.stat()
            identity = (info.st_dev, info.st_ino)
            if (info.st_ino and identity in self.identities
                    or not info.st_ino and any(target.samefile(path(other, self.root)) for other in self.raw)):
                raise ValueError("c6_file_alias")
            raw, _ = self.reader(target, meter=self.meter)
            if info.st_ino:
                self.identities.add(identity)
            self.raw[name], self.hashes[name] = raw, sha(raw)
        if expected is not None and self.hashes[name] != expected:
            raise ValueError("c6_hash_changed")
        return self.raw[name]

    def read(self, reference):
        ref(reference, self.root)
        return strict_json(self.get(reference["file"], reference["sha256"]).decode("utf-8"))

    def json(self, name):
        return strict_json(self.get(name).decode("utf-8"))

    def unchanged(self):
        fresh = Snapshots(self.root, meter=self.meter, reader=self.reader)
        for name, value in self.hashes.items():
            fresh.get(name, value)


def write_new(name, value, root=ROOT):
    target = path(name, root)
    raw = value if isinstance(value, bytes) else encoded(value)
    if len(raw) > BYTE_LIMIT:
        raise ValueError("c6_artifact_size")
    with target.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def replace(name, value, root=ROOT, *, replacer=os.replace):
    temp = name + "." + uuid.uuid4().hex + ".tmp"
    write_new(temp, value, root)
    replacer(path(temp, root), path(name, root))


def committed(names, *, root=ROOT, revision="HEAD", meter=None, reader=snapshot,
              runner=subprocess.run):
    """Read-only local Git proof; output/error text never enters logs."""
    if revision != "HEAD" and not digest(revision, 40):
        raise ValueError("c6_commit_identity")
    for name in sorted(names):
        raw = reader(path(name, root), meter=meter)[0]
        result = runner(["git", "show", f"{revision}:{name}"], cwd=root,
                                capture_output=True, check=False, timeout=15)
        if result.returncode or result.stdout != raw:
            raise ValueError("c6_uncommitted_bytes")


class GitProof:
    """Cache Git object bytes only while HEAD and every observed worktree hash stay fixed."""
    def __init__(self, root=ROOT, *, meter=None, reader=snapshot, runner=subprocess.run):
        self.root, self.head, self.proven = Path(root), None, {}
        self.meter, self.reader = meter if meter is not None else Meter(), reader
        self.runner = runner

    def __call__(self, names, *, root=ROOT, revision="HEAD"):
        if Path(root) != self.root:
            raise ValueError("c6_git_root_changed")
        result = self.runner(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, check=False, timeout=15)
        head = result.stdout.decode("ascii").strip()
        if result.returncode or not digest(head, 40) or self.head is not None and head != self.head:
            raise ValueError("c6_git_head_changed")
        self.head = head
        for name in sorted(names):
            current = sha(self.reader(path(name, root), meter=self.meter)[0])
            key = (revision, name)
            if key not in self.proven:
                committed([name], root=root, revision=revision, meter=self.meter,
                          reader=self.reader, runner=self.runner)
                self.proven[key] = current
            elif current != self.proven[key]:
                raise ValueError("c6_git_bytes_changed")


def source_manifest(root=ROOT, *, sealed=None, meter=None, reader=snapshot,
                    seeds=None, pinned=None, extra_files=None):
    """Code-only C6 closure. A sealed new positive import is rejected before its body."""
    snapshots = Snapshots(root, meter=meter, reader=reader)
    seeds = NEW_FILES if seeds is None else seeds
    pinned = PINNED if pinned is None else pinned
    extra_files = SERVICE_FILES | HELPER_FILES | JAVA_PARITY_FILES if extra_files is None else extra_files
    pending, roster, candidates = list(seeds), set(), {}
    while pending:
        name = pending.pop()
        if name in roster:
            continue
        if not name.endswith(".py") or sealed is not None and name not in sealed["code_roster"]:
            raise ValueError("c6_code_allowlist")
        expected = sealed["bound_files"].get(name) if sealed is not None else None
        tree = ast.parse(snapshots.get(name, expected))
        roster.add(name)
        for candidate in _module_candidates(tree, name):
            exists = path(candidate, root).is_file()
            candidates[candidate] = exists
            if sealed is not None and (sealed["import_candidates"].get(candidate) is not exists
                                       or exists and candidate not in sealed["code_roster"]):
                raise ValueError("c6_code_allowlist")
            if exists and candidate not in roster:
                pending.append(candidate)
    for name in set(pinned) | extra_files | {"pyproject.toml", "uv.lock"}:
        snapshots.get(name, pinned.get(name))
    snapshots.unchanged()
    return {"schema_version": 1, "candidate": CANDIDATE_ID, "reused_policy_id": REUSED_POLICY_ID,
            "kind": "toolchain", "bound_files": dict(sorted(snapshots.hashes.items())),
            "code_roster": sorted(roster), "import_candidates": dict(sorted(candidates.items()))}


def source_files(root=ROOT):
    return set(source_manifest(root)["bound_files"])


def code_contract(snapshots, *, git=committed, manifest=source_manifest):
    # The committed bytes authorize discovery, never an uncommitted expanded allowlist.
    git([TOOLCHAIN_FREEZE], root=snapshots.root)
    frozen = snapshots.json(TOOLCHAIN_FREEZE)
    if (frozen.get("candidate") != CANDIDATE_ID or frozen.get("reused_policy_id") != REUSED_POLICY_ID
            or frozen.get("kind") != "toolchain" or type(frozen.get("schema_version")) is not int
            or frozen["schema_version"] != 1):
        raise ValueError("c6_code_freeze")
    actual = manifest(snapshots.root, sealed=frozen, meter=snapshots.meter, reader=snapshots.reader)
    if actual != frozen:
        raise ValueError("c6_code_freeze")
    bound = frozen["bound_files"]
    for name, value in bound.items():
        if not digest(value):
            raise ValueError("c6_code_digest")
        snapshots.get(name, value)
    ci = snapshots.json(CI_RECEIPT)
    if (ci.get("source_freeze") != {"file": TOOLCHAIN_FREEZE, "sha256": snapshots.hashes[TOOLCHAIN_FREEZE]}
            or not digest(ci.get("head_sha"), 40) or not ci.get("runs")
            or sorted(r.get("event", "") for r in ci["runs"]) != ["pull_request", "push"]
            or any(type(r.get("run_id")) is not int or r["run_id"] <= 0
                   or r.get("status") != "completed" or r.get("conclusion") != "success"
                   or not re.fullmatch(r"https://github\.com/[^/]+/[^/]+/actions/runs/" + str(r["run_id"]), str(r.get("url")))
                   or r.get("head_sha") != ci["head_sha"]
                   or r.get("jobs") != {"backend": "success", "java-service": "success", "web": "success"} for r in ci["runs"])):
        raise ValueError("c6_ci_observation")
    git(set(bound) | {TOOLCHAIN_FREEZE}, root=snapshots.root, revision=ci["head_sha"])
    git(set(bound) | {TOOLCHAIN_FREEZE, CI_RECEIPT}, root=snapshots.root)
    snapshots.unchanged()
    return bound, ci


def freeze_contract(value, kind, phase, snapshots):
    extra = "toolchain_commit" if kind == "source" else "source_commit"
    if (set(value) != {"schema_version", "candidate", "phase", "kind", "bound_files", "files", extra}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["candidate"] != CANDIDATE_ID or value["phase"] != phase or value["kind"] != kind
            or set(value["files"]) != ROLES[kind] or not digest(value[extra], 40)
            or len(set(value["files"].values())) != len(value["files"])
            or not set(value["files"].values()) <= set(value["bound_files"])):
        raise ValueError("c6_freeze_contract")
    for name, value_hash in value["bound_files"].items():
        if not digest(value_hash):
            raise ValueError("c6_freeze_digest")
        metadata_names = {PRIOR_FINGERPRINTS, *[f"data/evaluation/meetings-c6-{p}-source-fingerprints-v1.json" for p in COUNTS]}
        if name != TOOLCHAIN_FREEZE and not (kind == "source" and name in metadata_names):
            phase_path(name, phase, snapshots.root)
    return value["files"]


def validate_draft(value, phase):
    if (set(value) != {"schema_version", "phase", "cases"} or type(value["schema_version"]) is not int
            or value["schema_version"] != 1 or value["phase"] != phase or phase not in COUNTS
            or len(value["cases"]) != COUNTS[phase]):
        raise ValueError("c6_draft_contract")
    expected = [f"C6-{'CAL' if phase == 'calibration' else 'VAL'}-{i:02d}" for i in range(1, COUNTS[phase] + 1)]
    if [c["id"] for c in value["cases"]] != expected:
        raise ValueError("c6_case_ids")
    for case in value["cases"]:
        if set(case) != {"id", "payload", "response_language"} or case["response_language"] not in {"ko", "en"}:
            raise ValueError("c6_case_contract")
        request = AnswerRequest.model_validate(case["payload"])
        if not request.contexts or canonical(request.model_dump(exclude_unset=True)) != canonical(case["payload"]):
            raise ValueError("c6_payload_coercion")
    return value


def role_contract(snapshots, phase, *, git=committed):
    """Committed actual-role metadata; it does not prove historical file absence."""
    git([ROLE_REGISTRATION], root=snapshots.root)
    value = snapshots.json(ROLE_REGISTRATION)
    required = {"source_author", "source_prereviewer", "item_author", "item_prereviewer"}
    if value.get("candidate_id") != CANDIDATE_ID or value.get("schema_version") != 1:
        raise ValueError("c6_role_registration")
    assignments = value.get("assignments", [])
    selected = [r for r in assignments if r.get("phase") == phase]
    if len(selected) != 4 or {r.get("role") for r in selected} != required:
        raise ValueError("c6_role_coverage")
    for row in assignments:
        if (row.get("phase") not in COUNTS or row.get("role") not in required
                or not isinstance(row.get("role_id"), str) or not row["role_id"]
                or row.get("actual_model") != "gpt-6-astra" or row.get("actual_effort") not in {"high", "xhigh"}
                or row.get("accepted") is not True or not isinstance(row.get("prior_exposure"), list)
                or not row.get("allowed_paths") or not digest(row.get("starts_after_commit"), 40)):
            raise ValueError("c6_role_acceptance")
        accepted = datetime.fromisoformat(row["accepted_at"])
        if accepted.tzinfo is None or accepted > datetime.now(UTC):
            raise ValueError("c6_role_time")
        for name in row["allowed_paths"]:
            phase_path(name, row["phase"], snapshots.root)
    own_ids = {r["role_id"] for r in selected}
    if own_ids & {r["role_id"] for r in assignments if r["phase"] != phase}:
        raise ValueError("c6_role_cross_split")
    roles = {r["role"]: r["role_id"] for r in selected}
    if (roles["source_author"] == roles["source_prereviewer"]
            or roles["item_author"] == roles["item_prereviewer"]
            or len(own_ids) != 4 and value.get("same_split_reuse_disclosed") is not True):
        raise ValueError("c6_role_independence")
    return roles


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
    own = f"data/evaluation/meetings-c6-{phase}-source-fingerprints-v1.json"
    if files["fingerprints"] != own or PRIOR_FINGERPRINTS not in source["bound_files"]:
        raise ValueError("c6_freshness_paths")
    expected = source_fingerprints(manifest, documents)
    if canonical(snapshots.json(own)) != canonical(expected):
        raise ValueError("c6_fingerprint_replay")
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
        raise ValueError("c6_freshness_evidence")
    comparison = []
    if phase == "validation":
        other = "data/evaluation/meetings-c6-calibration-source-fingerprints-v1.json"
        if other not in source["bound_files"] or checks.get("other_split_sha256") != snapshots.hashes[other]:
            raise ValueError("c6_freshness_cross_split_binding")
        prior_split = snapshots.json(other)
        if prior_split.get("phase") != "calibration" or prior_split.get("method") != FRESHNESS_METHOD or len(prior_split.get("documents", [])) != 6:
            raise ValueError("c6_freshness_cross_split_metadata")
        comparison = prior_split["documents"]
    elif checks.get("other_split_sha256") is not None:
        raise ValueError("c6_freshness_order")
    shared = []
    for i, row in enumerate(expected["documents"]):
        for old in prior_rows:
            if set(row["long_paragraph_sha256"]) & set(old.get("long_paragraph_sha256", [])):
                raise ValueError("c6_historical_paragraph_reuse")
            if any(row.get(k) is not None and row.get(k) == old.get(k) for k in
                   ("family_id", "url", "revision_identity", "raw_sha256", "normalized_sha256")):
                raise ValueError("c6_historical_source_reuse")
        for other in comparison + expected["documents"][:i]:
            common = sorted(set(row["long_paragraph_sha256"]) & set(other["long_paragraph_sha256"]))
            if row["normalized_sha256"] == other["normalized_sha256"] or common and row["family_id"] != other["family_id"]:
                raise ValueError("c6_new_source_duplicate")
            if common:
                shared.append({"documents": [other["document_id"], row["document_id"]],
                    "raw_sha256": [other["raw_sha256"], row["raw_sha256"]], "paragraph_sha256": common})
    approvals = checks.get("within_family_shared_paragraphs")
    if not isinstance(approvals, list) or len(approvals) != len(shared):
        raise ValueError("c6_shared_paragraph_review")
    for observed, approved in zip(shared, approvals, strict=True):
        if any(approved.get(k) != v for k, v in observed.items()) or approved.get("verdict") != "accepted_history_repetition" or not approved.get("reason"):
            raise ValueError("c6_shared_paragraph_review")


def load_material(phase, references, snapshots, code, ci, *, git=committed):
    """The caller establishes execution gate/metadata before this semantic boundary."""
    roles = role_contract(snapshots, phase, git=git)
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
        raise ValueError("c6_material_binding")
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
        raise ValueError("c6_source_composition")
    raw_names = {s["local_raw_snapshot"] for f in manifest["families"] for s in f["sources"]}
    metadata_names = {PRIOR_FINGERPRINTS}
    if phase == "validation":
        metadata_names.add("data/evaluation/meetings-c6-calibration-source-fingerprints-v1.json")
    if set(source["bound_files"]) != set(sf.values()) | raw_names | metadata_names:
        raise ValueError("c6_source_bindings")
    documents, authors, descriptions = [], set(), {}
    for family in manifest["families"]:
        origin = "public" if family["family_id"] in {"c6-f01", "c6-f03"} else "synthetic"
        if family.get("origin") != origin or len(family["sources"]) != 3 or family.get("source_suitability", {}).get("verdict") != "ADOPTED":
            raise ValueError("c6_source_family")
        info = []
        for source_row in family["sources"]:
            info.append(SourceDocument.model_validate({k: source_row[k] for k in
                ("document_id", "revision", "kind", "language", "meeting_date")}).model_dump())
            author = source_row.get("adoption_author_role")
            if not isinstance(author, str) or not author:
                raise ValueError("c6_source_author")
            authors.add(author)
            if origin == "synthetic":
                provenance = source_row["synthetic_provenance"]
                if provenance.get("fictional") is not True or provenance.get("ai_authored") is not True:
                    raise ValueError("c6_synthetic_provenance")
                authors.add(provenance["author_role"])
            elif not digest(source_row.get("git_blob_sha1"), 40) or not source_row.get("license_id") or not family.get("license"):
                raise ValueError("c6_public_provenance")
            if (source_row.get("adoption_verdict") != f"ADOPTED_FOR_{phase.upper()}_SOURCE_WITH_REGISTERED_CONSTRAINTS"
                    or source_row.get("raw_encoding") != "UTF-8" or source_row.get("page", "missing") is not None
                    or not source_row.get("title") or type(source_row.get("revision")) is not int or source_row["revision"] != 1):
                raise ValueError("c6_source_adoption")
            raw = snapshots.get(source_row["local_raw_snapshot"], source_row["raw_sha256"])
            documents.append(document_record(family, source_row, raw))
        descriptions[family["family_id"]] = info
    documents.sort(key=lambda d: d["registration_ordinal"])
    if (inventory.get("documents") != documents or [d["registration_ordinal"] for d in documents] != list(range(6))
            or len({d["document_id"] for d in documents}) != 6):
        raise ValueError("c6_inventory_replay")
    for role, filename in (("family_registry", REGISTRY), ("active_comparison_source_freeze", TOOLCHAIN_FREEZE)):
        if manifest.get(role) != {"path": filename, "sha256": snapshots.hashes[filename]}:
            raise ValueError("c6_manifest_binding")
    source_review = snapshots.json(sf["prereview"])
    if authors != {roles["source_author"]} or source_review.get("reviewer_id") != roles["source_prereviewer"]:
        raise ValueError("c6_actual_source_roles")
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
    if item_authors != {roles["item_author"]} or item_review.get("reviewer_id") != roles["item_prereviewer"]:
        raise ValueError("c6_actual_item_roles")
    check_prereview(item_review, [c["id"] for c in draft["cases"]], authors=item_authors, partial_missing=True)
    if item_review.get("all_sufficient_alternatives_including_repeated_passages_checked") is not True:
        raise ValueError("c6_item_alternative_review")
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
            raise ValueError("c6_item_whole_context")
    selected = {"schema_version": 1, "phase": phase, "cases": [{"id": c["id"], "chunk_ids": [x["chunk_id"]
        for x in c["payload"]["contexts"]]} for c in draft["cases"]]}
    if canonical(snapshots.json(it["context_selection"])) != canonical(selected):
        raise ValueError("c6_context_selection")
    return draft, oracles, sorted(authors)


def prepare(phase, references, *, root=ROOT, loader=load_tokenizer, counter=count, git=committed,
            contract=code_contract, writer=write_new):
    meter = Meter()
    if git is committed:
        git = GitProof(root, meter=meter)
    if phase not in COUNTS or set(references) != {"draft", "oracle", "source_freeze", "item_freeze"}:
        raise ValueError("c6_preparation_arguments")
    for reference in references.values():
        ref(reference, root)
        phase_path(reference["file"], phase, root)
    output = f".local/meetings-c6-{phase}-prepared-v1"
    separate([output, *(r["file"] for r in references.values())], root)
    path(output, root).mkdir(parents=True, exist_ok=False)
    captures = Snapshots(root, meter=meter)
    report = {"schema_version": 1, "candidate": CANDIDATE_ID, "reused_policy_id": REUSED_POLICY_ID, "phase": phase, "status": "failed",
        "references": references, "cases": [], "errors": [], "model_calls": 0, "native_calls": 0,
        "downloads": 0, "tokenizer_loads": 0, "payloads_preserved": False, "input_sha256": None}
    input_bytes = None
    try:
        code, ci = contract(captures, git=git)
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
                except Exception as error:  # noqa: BLE001 - never expose question/tokenizer diagnostics
                    row["error"] = "input_preparation_failed"
                    report.setdefault("first_failure", safe_failure(error))
        report["payloads_preserved"] = True
        if any(row["error"] for row in report["cases"]):
            raise ValueError("survey_failed")
        prepared_input = {**draft, "cases": [{**c, "official_input_tokens": r["input_tokens"], "prompt_sha256": r["prompt_sha256"]}
            for c, r in zip(draft["cases"], report["cases"], strict=True)]}
        input_bytes = encoded(prepared_input)
        final_code, final_ci = contract(Snapshots(root, meter=meter), git=git)
        if final_code != code or final_ci != ci:
            raise ValueError("c6_post_count_code_changed")
        captures.unchanged()
        git(captures.hashes, root=root)
        report.update(status="passed", input_sha256=sha(input_bytes))
    except Exception as error:  # noqa: BLE001 - exclusive failure receipt, no retries or body logs
        report.setdefault("first_failure", safe_failure(error))
        report["errors"].append("preparation_failed_closed")
    report["snapshots"] = captures.hashes
    report["reader_counts"] = meter.export()
    report["summary"] = {"planned": COUNTS[phase], "measured": sum(type(r["input_tokens"]) is int for r in report["cases"]),
                         "failed": sum(r["error"] is not None for r in report["cases"])}
    if report["status"] == "passed":
        try:
            writer(output + "/input.json", input_bytes, root)
        except Exception as error:  # noqa: BLE001 - safe first cause retained without body/path
            report.setdefault("first_failure", safe_failure(error))
            report.update(status="failed", input_sha256=None)
            report["errors"].append("input_write_failed")
    writer(output + "/receipt.json", report, root)
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
