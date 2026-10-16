# C1 calibration v1 — isolated authoring pool

Eight fresh calibration items were authored only after the parent froze the C1 policy, implementation and source-family registry at commit `82b0fff79761c0da86f4d8c5614aa20f9b12e7e5`. This folder is calibration, not validation. It does not rename, reopen or reuse the old prepared 12-item pool, M5-B or any locked prior split.

The parent may inspect `summary.json` for counts, provenance, hashes and sizes without reading the question or oracle text. A separate semantic reviewer should inspect this pool before item freeze and inference. This author did not implement the C1 generation/review prompts. The existing tool-accepted Astra xhigh custodian role was reused; neither the parent chat nor the service model was changed by this task.

## Composition and provenance

- Exactly 8 items in registered order, `C1CAL-01` through `C1CAL-08`.
- Answerable 6, insufficient evidence 2; Korean questions 4, English questions 4.
- Public cases 4, synthetic cases 4. Each origin has two questions in each language; insufficient-evidence questions include one per language.
- Four registered source families, two items per family. Within-family pairs are correlated and are not eight independent families.
- Four original public documents and six AI-authored fictional meeting/procedure-revision sources. Questions and synthetic source authorship are separately disclosed.
- AI-author self-review 8; independent semantic prereview 0; human review 0; service/native/model/tokenizer calls 0. Token readiness has not been measured.

Before authoring, all 46 source-freeze bindings were checked, along with the neutral-input hash. The four registered public URLs were retrieved without substituting a live branch; exact byte sizes, SHA-256, Git blob identities and document-specific rights notices were verified before writing any raw source. `source-integrity.json` preserves that pre-question event. The complete public raw bytes remain unchanged. All four upstream originals already use UTF-8 LF, so no normalization was needed. The exact copyright sections are also copied under `licenses/`; original acknowledgements remain in the raw documents. No linked external images or documents were downloaded under an assumed inherited license.

## Contents and coordinates

`cases.json` contains only ordered IDs, `operation: answer`, and strict `AnswerRequest` payloads. Oracle labels never enter the model payload. `oracles.json` contains required facts, explicit permissible alternative citations, partial known facts for insufficient-evidence items, missing requirements, prohibited inferences, languages and immutable source bindings. Natural translations/paraphrases are allowed; exact oracle quote text is not a required answer phrasing. Correct source quotations alone do not prove complete semantic correctness.

`sources-manifest.json` binds originals, processed windows, registered family IDs, source revisions, licenses and one-based line/Unicode-codepoint mappings. Public windows retain source headings and complete paragraphs, subsections or sections. Each window is one contiguous exact source range; no connective text, source translation or rewritten status is inserted. Synthetic windows contain entire bounded documents. Their historical procedure revisions are preserved as distinct evidence documents; this is not a claim that obsolete chunks of one active mutable service document may remain searchable.

`source-integrity.json` records materialization. `author_calibration.py` is the isolated construction record and contains questions/oracles. `materialize_public.py` is the one-time public-byte constructor; it refuses to run after cases exist. Do not rerun constructors after item freeze. `verify.py` validates integrity, DTOs, coordinates, evidence, registered distributions and frozen-source bindings without loading a model or tokenizer.

`summary.json` binds every authored file except itself by SHA-256 and exposes only counts, provenance and input sizes. Per-case query/context sizes are Unicode codepoints and UTF-8 bytes, not measured tokens. Request JSON byte counts include metadata but are not full C1 prompt sizes. Evidence was kept compact before inference; all-stage prompt budget checks remain separate and must not silently truncate the pool.

## Offline verification

From repository root, using the already locked environment without dependency synchronization:

```powershell
uv run --no-sync python data/evaluation/meetings-c1-calibration-v1/verify.py
```

Optional reproduction re-fetches only the four registered pinned raw URLs into memory and compares exact bytes:

```powershell
uv run --no-sync python data/evaluation/meetings-c1-calibration-v1/verify.py --check-upstream
```

The custodian may use `--write-summary` during preparation before final item freeze. After independent review and freeze, do not change sources, questions or oracles in response to model outputs. Commands print aggregate counts only; do not display a whole data diff to the parent. The verifier checks structural evidence coordinates, not semantic entailment, ecological correctness, real federation rules or model quality.

This is a small AI-authored/public-document experiment. It is not actual organizational-user accuracy, independent human review, validation readiness, a completed C1 gate or Phase-1 product completion. Fresh validation authoring remains 0 and requires the separate preregistered calibration gate.
