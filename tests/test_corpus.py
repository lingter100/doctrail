"""Quality gates for the frozen public-real corpus, using small synthetic fixtures."""

import copy
import json

import pytest

from scripts import prepare_corpus as corpus


def source(body, title="Source title"):
    return f'---\ntitle: "{title}"\n---\n{body}\n'.encode()


def row(path, text):
    return {
        "id": corpus.document_id(path),
        "path": path,
        "canonical_path": corpus.canonical_path(path),
        "normalized_sha256": corpus.sha256(text.encode()),
    }


def test_normalizer_preserves_prose_code_and_explicit_feature_state():
    raw = source(
        'Hello {{< glossary_tooltip text="Pod" term_id="pod" >}}.\n'
        "{{< note >}}Keep this warning body.{{< /note >}}\n"
        '```yaml\nkey: "preserved"\n```\n'
        '{{< feature-state for_k8s_version="v1.24" state="stable" >}}'
    )
    text = corpus.normalize_markdown(raw)
    assert "Hello Pod." in text
    assert "Note:\nKeep this warning body." in text
    assert '```yaml\nkey: "preserved"\n```' in text
    assert "Feature state: Kubernetes v1.24; stable." in text


@pytest.mark.parametrize(
    "directive",
    [
        '{{< include "critical-prerequisite.md" >}}',
        '{{< code_sample file="required.yaml" >}}',
        "{{< unknown_content >}}",
        '{{< feature-state feature_gate_name="AnyGate" >}}',
        '{{< feature-state state="stable" >}}',
        '{{< glossary_tooltip term_id="secret" >}}',
        "{{< note >}}unclosed",
        "{{< /warning >}}",
        "{{< note %}}",
        '{{< heading "missing" >}}',
        "{{< unknown",
    ],
)
def test_normalizer_quarantines_unresolved_or_malformed_content(directive):
    with pytest.raises(corpus.QuarantineError):
        corpus.normalize_markdown(source("Keep surrounding text. " + directive))


def test_localized_headings_require_pinned_resolution_and_preserve_title():
    raw = source('## {{< heading "prerequisites" >}}\nActual content.', "실제 제목")
    headings = {"ko": {"prerequisites": "시작하기 전에"}}
    assert "## 시작하기 전에" in corpus.normalize_markdown(raw, "ko", headings)
    assert corpus.frontmatter(raw)[0]["title"] == "실제 제목"
    with pytest.raises(corpus.QuarantineError):
        corpus.normalize_markdown(raw, "ko")


def test_translation_exact_and_transitive_near_duplicates_group_before_split():
    base = [f"token{i}" for i in range(120)]
    text_a = " ".join(base)
    text_b = " ".join([f"changed{i}" for i in range(6)] + base[6:])
    text_c = " ".join(
        [f"changed{i}" for i in range(6)] + base[6:-6] + [f"end{i}" for i in range(6)]
    )
    specifications = [
        ("content/en/docs/concepts/one.md", text_a),
        ("content/ko/docs/concepts/one.md", "별도의 한국어 문서로 번역된 내용이다."),
        ("content/en/docs/tasks/exact.md", text_a),
        ("content/en/docs/tasks/near.md", text_b),
        ("content/en/docs/tasks/transitive.md", text_c),
    ]
    rows = [row(path, text) for path, text in specifications]
    contents = {r["id"]: text for r, (_, text) in zip(rows, specifications)}
    info = corpus.group_and_split(rows, contents)
    assert len({r["family_id"] for r in rows}) == 1
    assert len({r["split"] for r in rows}) == 1
    assert info["largest_component"] == 5
    assert info["canonical_path_families"] == 4
    assert info["near_duplicate_pairs"]
    assert corpus.shingles(text_a) != corpus.shingles(text_b)


def test_split_stability_under_row_order_and_pilot_language_asymmetry():
    paths = ["content/ko/docs/" + next(iter(sorted(corpus.SMOKE_PATHS)))]
    paths += [f"content/en/docs/concepts/document{i}.md" for i in range(30)]
    rows = [row(path, f"unique number {i}") for i, path in enumerate(paths)]
    contents = {r["id"]: f"unique number {i}" for i, r in enumerate(rows)}
    reverse = copy.deepcopy(rows[::-1])
    corpus.group_and_split(rows, contents)
    corpus.group_and_split(reverse, contents)
    assert {r["id"]: (r["family_id"], r["split"]) for r in rows} == {
        r["id"]: (r["family_id"], r["split"]) for r in reverse
    }
    assert rows[0]["split"] == "smoke"


@pytest.fixture
def frozen_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "heading_assets", lambda *args, **kwargs: {})
    path = "content/en/docs/concepts/example.md"
    raw = source("A real source sentence retained without any transformation.")
    content = corpus.normalize_markdown(raw)
    document = row(path, content)
    document.update(
        sha256=corpus.sha256(raw),
        git_blob_sha=corpus.git_blob_sha(raw),
        revision=corpus.REVISION,
        language="en",
        title="Source title",
        normalizer_version=corpus.NORMALIZER_VERSION,
        download_url=f"https://raw.githubusercontent.com/{corpus.REPOSITORY}/"
        f"{corpus.REVISION}/{path}",
    )
    corpus.group_and_split([document], {document["id"]: content})
    entry = {"path": path, "git_blob_sha": document["git_blob_sha"], "size": len(raw)}
    inventory = [entry]
    manifest = {
        "revision": corpus.REVISION,
        "normalizer_version": corpus.NORMALIZER_VERSION,
        "inventory": {
            "entries": inventory,
            "sha256": corpus.sha256(
                json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
            ),
        },
        "documents": [document],
    }
    manifest_path = tmp_path / "manifest.json"
    corpus.write_json(manifest_path, manifest)
    for directory, data in ((corpus.RAW_DIR, raw), (corpus.PROCESSED_DIR, content.encode())):
        local = tmp_path / directory / f"{document['id']}.md"
        local.parent.mkdir(parents=True)
        local.write_bytes(data)
    return tmp_path, manifest_path, manifest


def test_replay_is_offline_and_deterministic_with_verified_cache(frozen_fixture, monkeypatch):
    root, path, _manifest = frozen_fixture
    monkeypatch.setattr(corpus, "download", lambda *args: pytest.fail("unexpected network"))
    before = path.read_bytes()
    assert corpus.replay(path, root) == 1
    assert path.read_bytes() == before
    assert corpus.load_verified_corpus(path, root)[0]["content"].startswith("A real source")


@pytest.mark.parametrize("target", ["raw", "normalized", "inventory", "split", "title"])
def test_corruption_or_manifest_drift_is_rejected(frozen_fixture, target):
    root, path, manifest = frozen_fixture
    document = manifest["documents"][0]
    if target in {"raw", "normalized"}:
        directory = corpus.RAW_DIR if target == "raw" else corpus.PROCESSED_DIR
        (root / directory / f"{document['id']}.md").write_text("tampered", encoding="utf-8")
    elif target == "inventory":
        manifest["inventory"]["entries"][0]["git_blob_sha"] = "0" * 40
    elif target == "title":
        document["title"] = "Invented replacement title"
    else:
        document["split"] = "test" if document["split"] != "test" else "train"
    corpus.write_json(path, manifest)
    with pytest.raises(ValueError):
        loaded = corpus.load_verified_corpus(path, root)
        corpus.verify_groups(loaded)


def test_changed_normalizer_output_detected_even_with_updated_file_checksum(frozen_fixture):
    root, path, manifest = frozen_fixture
    document = manifest["documents"][0]
    altered = b"Silently truncated source body.\n"
    (root / corpus.PROCESSED_DIR / f"{document['id']}.md").write_bytes(altered)
    document["normalized_sha256"] = corpus.sha256(altered)
    corpus.write_json(path, manifest)
    with pytest.raises(ValueError, match="processed corpus drift"):
        corpus.load_verified_corpus(path, root)


def test_heading_dependency_drift_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="dependency checksum mismatch"):
        corpus.heading_assets(tmp_path)


def test_discovery_refuses_to_replace_frozen_manifest_before_network(tmp_path, monkeypatch):
    frozen = tmp_path / corpus.MANIFEST.relative_to(corpus.ROOT)
    frozen.parent.mkdir(parents=True)
    frozen.write_text("already frozen", encoding="utf-8")
    monkeypatch.setattr(corpus, "download", lambda *args: pytest.fail("unexpected network"))
    with pytest.raises(ValueError, match="already frozen"):
        corpus.discover("2026-10-12", tmp_path)
    assert frozen.read_text(encoding="utf-8") == "already frozen"
