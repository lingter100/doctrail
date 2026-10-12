"""Freeze and replay openly licensed Kubernetes documents without paid services.

uv run python scripts/prepare_corpus.py discover --collected-at 2026-10-12
uv run python scripts/prepare_corpus.py replay
uv run python scripts/prepare_corpus.py verify

The strict normalizer quarantines unknown Hugo content directives. Cached raw and
normalized documents are ignored by Git; only provenance and quality metadata ship.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import time
import tomllib
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/manifests/kubernetes-v1.json"
QUALITY = ROOT / "data/manifests/kubernetes-v1-quality.json"
REVISION = "4b10551a8c6f0a3f100356d8fc3c6fb5cfde1448"
REPOSITORY = "kubernetes/website"
NORMALIZER_VERSION = "hugo-strict-v1"
SPLIT_SEED = "doctrail-kubernetes-v1"
NEAR_THRESHOLD = 0.85
SHINGLE_SIZE = 5
MAX_SOURCE_BYTES = 250_000
MIN_CHARACTERS = 700
RAW_DIR = "data/raw/kubernetes-v1"
PROCESSED_DIR = "data/processed/kubernetes-v1"
SMOKE_PATHS = {
    "concepts/workloads/pods/_index.md",
    "concepts/configuration/configmap.md",
    "concepts/overview/working-with-objects/namespaces.md",
    "concepts/configuration/secret.md",
}
SHORTCODE = re.compile(r"\{\{([<%])\s*(.*?)\s*([>%])\}\}", re.DOTALL)
HEADING_SOURCES = {
    "layouts/shortcodes/feature-state.html": "39ae3ac93a098c0754509e5df65f8702f1fb76f940e5a983def7a573d30d4209",
    "layouts/shortcodes/heading.html": "eb0c8e7155d82217d816d2d38e3d3c31c9fc1718e3b89ed75e621f239ac29fec",
    "i18n/en/en.toml": "ec55d721cb9d5d24d1fc1f66c7587d1c40e99f4c1437c10ab79fce63d7d647b4",
    "i18n/ko/ko.toml": "11c1ed5eb695bb135ebc365866047166f0008c9fe5e393550ef2bdfe18092435",
}


def heading_assets(root: Path = ROOT, fetch: bool = False) -> dict:
    """Resolve localized labels only from checksum-pinned shortcode and locale assets."""
    labels = {}
    for source_path, expected in HEADING_SOURCES.items():
        local = root / RAW_DIR / source_path.replace("/", "-")
        raw = (
            local.read_bytes()
            if local.exists()
            else (
                download(f"https://raw.githubusercontent.com/{REPOSITORY}/{REVISION}/{source_path}")
                if fetch
                else b""
            )
        )
        if sha256(raw) != expected:
            raise ValueError("heading dependency checksum mismatch: " + source_path)
        if fetch:
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(raw)
        if source_path.endswith(".toml"):
            labels[source_path.split("/")[1]] = {
                key.removesuffix("_heading"): value["other"]
                for key, value in tomllib.loads(raw.decode("utf-8")).items()
                if key.endswith("_heading")
            }
    return labels


class QuarantineError(ValueError):
    """Source cannot safely become a standalone document."""


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def git_blob_sha(raw: bytes) -> str:
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


def download(url: str, limit: int = MAX_SOURCE_BYTES) -> bytes:
    for attempt in range(3):
        try:
            with urlopen(
                Request(url, headers={"User-Agent": "DocTrail-research/0.2"}), timeout=45
            ) as response:
                raw = response.read(limit + 1)
            if len(raw) > limit:
                raise ValueError("download exceeds bounded size")
            return raw
        except OSError:
            if attempt == 2:
                raise
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError("unreachable")


def canonical_path(path: str) -> str:
    match = re.fullmatch(r"content/(?:en|ko)/docs/(.+\.md)", path)
    if not match or ".." in Path(path).parts:
        raise ValueError("invalid source path")
    return match.group(1)


def document_id(path: str) -> str:
    return "k8s-" + path.split("/")[1] + "-" + sha256(path.encode())[:16]


def frontmatter(raw: bytes) -> tuple[dict, str]:
    text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    match = re.match(r"\A---\n(.*?)\n---(?:\n|$)", text, re.DOTALL)
    if not match:
        raise QuarantineError("missing_frontmatter")
    metadata = {}
    for key in ("title", "lastmod", "date", "draft", "content_type", "no_list"):
        value = re.search(rf"^{key}:\s*([^\n]*)$", match.group(1), re.MULTILINE)
        if value:
            scalar = value.group(1).strip()
            if scalar.startswith('"'):
                try:
                    scalar = json.loads(scalar)
                except ValueError as exc:
                    raise QuarantineError("unsupported_frontmatter_scalar") from exc
            elif scalar.startswith("'"):
                if not scalar.endswith("'"):
                    raise QuarantineError("unsupported_frontmatter_scalar")
                scalar = scalar[1:-1].replace("''", "'")
            metadata[key] = scalar
    title = metadata.get("title", "")
    if not title or title in {"|", ">", "|-", ">-"}:
        raise QuarantineError("missing_or_complex_title")
    return metadata, text[match.end() :]


def normalize_markdown(raw: bytes, language: str = "en", headings: dict | None = None) -> str:
    """Preserve prose/code; only explicitly known presentation directives disappear.

    Content-producing shortcodes, including includes and code_sample, are NOT
    silently stripped. Their entire source document is quarantined.
    """
    _, text = frontmatter(raw)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    stack = []

    def replace(match: re.Match) -> str:
        if (match[1], match[3]) not in {("<", ">"), ("%", "%")}:
            raise QuarantineError("malformed_shortcode")
        try:
            parts = shlex.split(match[2])
        except ValueError as exc:
            raise QuarantineError("malformed_shortcode") from exc
        if not parts:
            raise QuarantineError("empty_shortcode")
        name, args = parts[0], parts[1:]
        if name == "feature-state":
            attrs = dict(item.split("=", 1) for item in args if "=" in item)
            if (
                len(args) != 2
                or set(attrs) != {"state", "for_k8s_version"}
                or attrs["state"] not in {"alpha", "beta", "stable", "deprecated"}
                or not re.fullmatch(r"v?\d+\.\d+", attrs["for_k8s_version"])
            ):
                raise QuarantineError("unresolved_feature_state")
            # Pinned template manual mode emits only stage and Kubernetes version.
            # Reword as explicit text; never guess automatic feature-gate histories.
            return (
                "\nFeature state: Kubernetes "
                + attrs["for_k8s_version"]
                + "; "
                + attrs["state"]
                + ".\n"
            )
        if name == "heading" and len(args) == 1:
            label = (headings or {}).get(language, {}).get(args[0])
            if not label:
                raise QuarantineError("unresolved_heading:" + args[0])
            return label
        if name in {"note", "caution", "warning"}:
            if args:
                raise QuarantineError("unsupported_shortcode_arguments:" + name)
            stack.append(name)
            return "\n" + name.capitalize() + ":\n"
        if name in {"/note", "/caution", "/warning"}:
            if args or not stack or stack.pop() != name[1:]:
                raise QuarantineError("unbalanced_shortcode")
            return "\n"
        if name == "glossary_tooltip":
            attrs = dict(item.split("=", 1) for item in args if "=" in item)
            if not attrs.get("text") or any("=" not in item for item in args):
                raise QuarantineError("unresolved_glossary_label")
            return attrs["text"]
        if name == "capture" and args in [["overview"], ["body"], ["whatsnext"]]:
            stack.append(name)
            return "\n"
        if name == "/capture" and not args:
            if not stack or stack.pop() != "capture":
                raise QuarantineError("unbalanced_shortcode")
            return "\n"
        raise QuarantineError("unresolved_shortcode:" + name)

    text = SHORTCODE.sub(replace, text)
    if stack or "{{<" in text or "{{%" in text:
        raise QuarantineError("unbalanced_shortcode")
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def path_exclusion(path: str, size: int) -> str | None:
    canonical = canonical_path(path)
    if canonical.split("/")[0] not in {"concepts", "tasks", "tutorials", "reference"}:
        return "outside_standalone_document_scope"
    if canonical.startswith(
        (
            "reference/kubernetes-api/",
            "reference/command-line-tools-reference/",
            "reference/setup-tools/",
            "reference/glossary/",
        )
    ):
        return "generated_reference_or_glossary_fragment"
    if size > MAX_SOURCE_BYTES:
        return "source_size_limit"
    return None


def shingles(text: str) -> set[tuple[str, ...]]:
    tokens = re.findall(r"\w+", text.casefold())
    return {tuple(tokens[i : i + SHINGLE_SIZE]) for i in range(len(tokens) - SHINGLE_SIZE + 1)}


def group_and_split(documents: list[dict], contents: dict[str, str]) -> dict:
    """Union translations, exact and lexical near duplicates before assigning splits."""
    rows = sorted(documents, key=lambda row: row["id"])
    parent = {row["id"]: row["id"] for row in rows}

    def find(value):
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left, right):
        a, b = sorted((find(left), find(right)))
        parent[b] = a

    edges = []
    for field in ("canonical_path", "normalized_sha256"):
        groups = defaultdict(list)
        for row in rows:
            groups[row[field]].append(row["id"])
        for ids in groups.values():
            for other in ids[1:]:
                union(ids[0], other)
                edges.append({"left": ids[0], "right": other, "reason": field})
    sets = {row["id"]: shingles(contents[row["id"]]) for row in rows}
    postings = defaultdict(set)
    near_pairs = []
    candidates_count = scored_count = 0
    for row in rows:
        doc_id = row["id"]
        current = sets[doc_id]
        candidates = set()
        for shingle in current:
            candidates.update(postings[shingle])
        candidates_count += len(candidates)
        for other in sorted(candidates):
            previous = sets[other]
            if min(len(current), len(previous)) / max(len(current), len(previous)) < NEAR_THRESHOLD:
                continue
            scored_count += 1
            intersection = len(current & previous)
            score = intersection / (len(current) + len(previous) - intersection)
            if score >= NEAR_THRESHOLD:
                union(doc_id, other)
                near_pairs.append({"left": other, "right": doc_id, "jaccard": round(score, 8)})
        for shingle in current:
            postings[shingle].add(doc_id)
    components = defaultdict(list)
    for row in rows:
        components[find(row["id"])].append(row)
    for members in components.values():
        signature = "\n".join(sorted({row["canonical_path"] for row in members}))
        family_id = "k8s-family-" + sha256(signature.encode())[:16]
        bucket = int(sha256(f"{SPLIT_SEED}:{family_id}".encode())[:16], 16) % 100
        split = "train" if bucket < 60 else "dev" if bucket < 80 else "test"
        if any(row["canonical_path"] in SMOKE_PATHS for row in members):
            split = "smoke"
        for row in members:
            row.update(family_id=family_id, split=split)
    return {
        "algorithm": "connected_components_then_seeded_sha256_bucket_60_20_20",
        "algorithm_version": "lexical-components-v1",
        "tokenizer": "Python Unicode regex \\w+ over str.casefold(); no stemming",
        "candidate_enumeration": "all pairs sharing any shingle; prune by min/max set-size bound",
        "component_size_counts": dict(sorted(Counter(len(x) for x in components.values()).items())),
        "largest_component": max((len(x) for x in components.values()), default=0),
        "canonical_path_families": len({row["canonical_path"] for row in rows}),
        "seed": SPLIT_SEED,
        "shingle_size": SHINGLE_SIZE,
        "near_duplicate_threshold": NEAR_THRESHOLD,
        "candidate_pairs": candidates_count,
        "jaccard_scored_pairs": scored_count,
        "near_duplicate_pairs": near_pairs,
        "translation_and_exact_edges": edges,
        "families": len(components),
        "limitations": [
            "Lexical shingles do not detect semantic paraphrases or translations with different paths.",
            "Matching canonical paths are grouped even when translation revisions differ.",
            "Threshold 0.85 is a predeclared heuristic, not human-validated duplicate truth.",
            "60/20/20 are family hash bucket probabilities, not exact document quotas.",
            "Stable under input order and replay; changing corpus component membership can change splits.",
        ],
    }


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def cached_source(row: dict, root: Path = ROOT) -> bytes:
    path = root / RAW_DIR / f"{row['id']}.md"
    raw = path.read_bytes() if path.exists() else download(row["download_url"])
    if len(raw) > MAX_SOURCE_BYTES or git_blob_sha(raw) != row["git_blob_sha"]:
        raise ValueError(f"source Git blob mismatch: {row['id']}")
    if "sha256" in row and sha256(raw) != row["sha256"]:
        raise ValueError(f"raw checksum mismatch: {row['id']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def discover(collected_at: str, root: Path = ROOT) -> dict:
    if (root / MANIFEST.relative_to(ROOT)).exists() or (root / QUALITY.relative_to(ROOT)).exists():
        raise ValueError(
            "Corpus already frozen; use replay or create a new explicit dataset version"
        )
    date.fromisoformat(collected_at)
    headings = heading_assets(root, fetch=True)
    tree_path = root / RAW_DIR / "tree.json"
    tree_url = f"https://api.github.com/repos/{REPOSITORY}/git/trees/{REVISION}?recursive=1"
    tree_raw = tree_path.read_bytes() if tree_path.exists() else download(tree_url, 20_000_000)
    tree = json.loads(tree_raw)
    if tree.get("sha") != REVISION or tree.get("truncated"):
        raise ValueError("unverified or incomplete Git tree inventory")
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_raw)
    inventory = sorted(
        [
            {"path": row["path"], "git_blob_sha": row["sha"], "size": row["size"]}
            for row in tree["tree"]
            if row["type"] == "blob" and re.fullmatch(r"content/(en|ko)/docs/.+\.md", row["path"])
        ],
        key=lambda row: row["path"],
    )
    excluded, candidates = [], []
    for entry in inventory:
        reason = path_exclusion(entry["path"], entry["size"])
        if reason:
            excluded.append({**entry, "reason": reason})
            continue
        path = entry["path"]
        candidates.append(
            {
                **entry,
                "id": document_id(path),
                "download_url": f"https://raw.githubusercontent.com/{REPOSITORY}/{REVISION}/{path}",
            }
        )
    documents, contents = [], {}

    def process(row):
        raw = cached_source(row, root)
        row = {**row, "sha256": sha256(raw)}
        try:
            meta, _ = frontmatter(raw)
            if meta.get("draft") == "true":
                raise QuarantineError("draft_document")
            normalized = normalize_markdown(raw, row["path"].split("/")[1], headings)
            if len(normalized.strip()) < MIN_CHARACTERS:
                raise QuarantineError("short_navigation_or_fragment")
            return row, meta, normalized, None
        except (QuarantineError, UnicodeError) as exc:
            return row, None, None, str(exc) if isinstance(exc, QuarantineError) else "invalid_utf8"

    with ThreadPoolExecutor(max_workers=8) as executor:
        for index, (row, meta, normalized, reason) in enumerate(executor.map(process, candidates)):
            if reason:
                excluded.append({**row, "reason": reason})
                continue
            updated = meta.get("lastmod")
            if updated and not re.match(r"^\d{4}-\d{2}-\d{2}(?:T.*)?$", updated):
                updated = None
            row.update(
                canonical_path=canonical_path(row["path"]),
                language=row["path"].split("/")[1],
                title=meta["title"],
                source_kind="public_real",
                author="The Kubernetes Authors",
                repository=REPOSITORY,
                revision=REVISION,
                license="CC-BY-4.0",
                license_url=f"https://github.com/{REPOSITORY}/blob/{REVISION}/LICENSE",
                source_url=f"https://github.com/{REPOSITORY}/blob/{REVISION}/{row['path']}",
                normalized_sha256=sha256(normalized.encode()),
                normalizer_version=NORMALIZER_VERSION,
                source_updated_at=updated,
                source_updated_at_basis="frontmatter_lastmod" if updated else "not_available",
                collected_at=collected_at,
                characters=len(normalized),
                human_review="pending",
            )
            documents.append(row)
            contents[row["id"]] = normalized
            output = root / PROCESSED_DIR / f"{row['id']}.md"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(normalized, encoding="utf-8", newline="\n")
    print(
        json.dumps({"normalized_documents": len(documents), "excluded": len(excluded)}), flush=True
    )
    grouping = group_and_split(documents, contents)
    inventory_digest = sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode())
    manifest = {
        "schema_version": 1,
        "corpus_id": "kubernetes-v1",
        "source_kind": "public_real",
        "repository": REPOSITORY,
        "revision": REVISION,
        "license": "CC-BY-4.0",
        "author": "The Kubernetes Authors",
        "collected_at": collected_at,
        "normalizer_version": NORMALIZER_VERSION,
        "normalizer_dependencies": [
            {
                "path": path,
                "sha256": digest,
                "source_url": f"https://github.com/{REPOSITORY}/blob/{REVISION}/{path}",
            }
            for path, digest in HEADING_SOURCES.items()
        ],
        "normalization_changes": [
            "Remove YAML metadata from body (title retained in manifest).",
            "Remove HTML comments; preserve prose, code blocks and Markdown links.",
            "Expand note/caution/warning presentation wrappers and glossary tooltip labels.",
            "Remove balanced overview/body/whatsnext capture wrappers; preserve inner text.",
            "Resolve heading labels using pinned EN/KO locale files and heading template.",
            "Render explicit feature-state version/status as text; quarantine automatic gate lookup.",
            "Quarantine all unsupported or malformed shortcodes; do not resolve remote includes.",
        ],
        "inventory": {
            "url": tree_url,
            "git_revision": REVISION,
            "scope": "all Markdown under content/en/docs and content/ko/docs",
            "sha256": inventory_digest,
            "entries": inventory,
        },
        "quality_policy": {
            "minimum_normalized_characters": MIN_CHARACTERS,
            "maximum_source_bytes": MAX_SOURCE_BYTES,
            "all_eligible_documents_retained": True,
            "human_review": "pending",
            "target_approximate_documents": 1000,
        },
        "split_policy": {
            "seed": SPLIT_SEED,
            "train": 60,
            "dev": 20,
            "test": 20,
            "unit": "translation_exact_near_duplicate_connected_component",
            "smoke_canonical_paths": sorted(SMOKE_PATHS),
        },
        "documents": sorted(documents, key=lambda row: row["path"]),
    }
    quality = {
        "schema_version": 1,
        "corpus_id": "kubernetes-v1",
        "revision": REVISION,
        "collected_at": collected_at,
        "inventory_sha256": inventory_digest,
        "automated_checks": True,
        "human_review": "pending",
        "counts": {
            "inventory": len(inventory),
            "download_candidates": len(candidates),
            "accepted": len(documents),
            "excluded": len(excluded),
            "by_language": dict(Counter(row["language"] for row in documents)),
            "by_split": dict(Counter(row["split"] for row in documents)),
            "exclusion_reasons": dict(sorted(Counter(row["reason"] for row in excluded).items())),
        },
        "grouping": grouping,
        "excluded": sorted(excluded, key=lambda row: row["path"]),
        "limitations": [
            "Automated eligibility and normalization checks are not human review.",
            "Public technical documentation does not represent private enterprise ACL distributions.",
            "Source update timestamps are nullable; collection date is never substituted.",
            "Strict shortcode quarantine lowers coverage, particularly tutorials and examples.",
            "Index pages are retained only when they contain at least 700 normalized characters.",
            "Frozen tree inventory is obtained from GitHub HTTPS; blobs are checked against Git SHA1.",
            "The approximate 1000-document target does not override content-quality exclusions.",
        ],
    }
    write_json(root / MANIFEST.relative_to(ROOT), manifest)
    write_json(root / QUALITY.relative_to(ROOT), quality)
    return quality["counts"]


def validate_manifest(manifest: dict) -> None:
    if (
        manifest.get("normalizer_version") != NORMALIZER_VERSION
        or manifest.get("revision") != REVISION
    ):
        raise ValueError("manifest snapshot or normalizer drift")
    seen = set()
    families = {}
    canonical_families = {}
    exact_families = {}
    inventory = manifest["inventory"]["entries"]
    digest = sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode())
    if digest != manifest["inventory"]["sha256"]:
        raise ValueError("inventory checksum drift")
    inventory_map = {item["path"]: item for item in inventory}
    if len(inventory_map) != len(inventory):
        raise ValueError("duplicate inventory path")
    for row in manifest["documents"]:
        if not re.fullmatch(r"k8s-(?:en|ko)-[0-9a-f]{16}", row["id"]) or row["id"] in seen:
            raise ValueError("invalid or duplicate document id")
        seen.add(row["id"])
        if row["id"] != document_id(row["path"]):
            raise ValueError("source identity drift")
        if row["revision"] != REVISION or row["language"] != row["path"].split("/")[1]:
            raise ValueError("source snapshot or language drift")
        expected_url = f"https://raw.githubusercontent.com/{REPOSITORY}/{REVISION}/{row['path']}"
        if row["download_url"] != expected_url:
            raise ValueError("source download URL drift")
        if row.get("source_url") is not None and row["source_url"] != (
            f"https://github.com/{REPOSITORY}/blob/{REVISION}/{row['path']}"
        ):
            raise ValueError("source attribution URL drift")
        inventory_row = inventory_map.get(row["path"], {})
        if inventory_row.get("git_blob_sha") != row["git_blob_sha"]:
            raise ValueError("source not in frozen inventory")
        if row["canonical_path"] != canonical_path(row["path"]):
            raise ValueError("canonical path drift")
        if row["normalizer_version"] != NORMALIZER_VERSION:
            raise ValueError("document normalizer drift")
        if row["split"] not in {"train", "dev", "test", "smoke"}:
            raise ValueError("invalid split")
        if families.setdefault(row["family_id"], row["split"]) != row["split"]:
            raise ValueError("family crosses splits")
        for groups, field in (
            (canonical_families, "canonical_path"),
            (exact_families, "normalized_sha256"),
        ):
            if groups.setdefault(row[field], row["family_id"]) != row["family_id"]:
                raise ValueError("translation or exact duplicate crosses families")
        if row["canonical_path"] in SMOKE_PATHS and row["split"] != "smoke":
            raise ValueError("pilot document leaks into heldout splits")


def load_verified_corpus(manifest_path: Path, root: Path = ROOT) -> list[dict]:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    validate_manifest(manifest)
    headings = heading_assets(root)
    result = []
    for row in manifest["documents"]:
        raw = (root / RAW_DIR / f"{row['id']}.md").read_bytes()
        if sha256(raw) != row["sha256"] or git_blob_sha(raw) != row["git_blob_sha"]:
            raise ValueError(f"raw checksum mismatch: {row['id']}")
        processed = (root / PROCESSED_DIR / f"{row['id']}.md").read_bytes()
        if sha256(processed) != row["normalized_sha256"]:
            raise ValueError(f"normalized checksum mismatch: {row['id']}")
        if normalize_markdown(raw, row["language"], headings).encode() != processed:
            raise ValueError(f"processed corpus drift: {row['id']}")
        if frontmatter(raw)[0]["title"] != row["title"]:
            raise ValueError(f"source title drift: {row['id']}")
        result.append({**row, "content": processed.decode("utf-8")})
    verify_groups(result)
    return result


def replay(manifest_path: Path, root: Path = ROOT) -> int:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    validate_manifest(manifest)
    headings = heading_assets(root, fetch=True)

    def process(row):
        raw = cached_source(row, root)
        normalized = normalize_markdown(raw, row["language"], headings).encode()
        if sha256(normalized) != row["normalized_sha256"]:
            raise ValueError(f"normalizer output drift: {row['id']}")
        path = root / PROCESSED_DIR / f"{row['id']}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(normalized)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(process, manifest["documents"]))
    documents = load_verified_corpus(manifest_path, root)
    return len(documents)


def verify_groups(documents: list[dict]) -> None:
    expected = {row["id"]: (row["family_id"], row["split"]) for row in documents}
    copies = [dict(row) for row in documents]
    group_and_split(copies, {row["id"]: row["content"] for row in copies})
    if expected != {row["id"]: (row["family_id"], row["split"]) for row in copies}:
        raise ValueError("family grouping or split assignment drift")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["discover", "replay", "verify"])
    parser.add_argument("--collected-at", default=date.today().isoformat())
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args()
    if args.command == "discover":
        result = discover(args.collected_at)
    elif args.command == "replay":
        result = {"documents": replay(args.manifest), "status": "replayed-and-verified"}
    else:
        documents = load_verified_corpus(args.manifest)
        result = {"documents": len(documents), "status": "verified"}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
