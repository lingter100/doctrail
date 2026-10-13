# Meeting natural-answer validation v1 — isolated custodian pool

This folder contains previously unauthored questions and semantic oracles. The parent and prompt tuner may read `summary.json` only. A separate independent reviewer may inspect the pool. Do not open other files here while changing the candidate prompt or policy.

## Registration and provenance

The parent explicitly signaled candidate source freeze at `f81fd8bb241090ddd210f30ae56f0699166b5a7e` before any validation question, oracle, fixture or source copy was written. Before that signal the custodian only investigated source repositories, licenses and file inventories. The custodian did not inspect existing development questions, previous evaluation/calibration/test data, candidate prompts or natural-answer implementation. A wide contract grep unintentionally included adjacent existing extraction declarations; this is disclosed in the manifest and to the parent.

There are exactly 12 new AI-authored questions: 6 grounded in public real source documents and 6 grounded in AI-authored fictional sources. Each half has 4 answerable and 2 insufficient-evidence cases. Question-language counts are English 4, Korean 4 and mixed 4. Source language and question language are separate attributes. All questions and semantic oracles have AI-author self-review; independent review is pending; human/user review count is 0. No model or tokenizer was called while authoring this pool.

This is a supplied-evidence answer validation, not retrieval recall, corpus-wide search, a user study, Java performance evidence, M5-B validation, or proof of production readiness. No prior evaluation data or source family was reused. In particular, Jupyter/community/2025 and synthetic release/log-retention families were excluded.

## Files

- `inputs.json`: exact `answer` request payloads, with 3 contexts per case.
- `oracles.json`: isolated semantic facts, exact supporting quotations, forbidden unsupported claims and insufficiency reasons. Natural paraphrases and translations are acceptable when faithful.
- `sources-manifest.json`: source provenance, pinned commits, source and excerpt hashes, original coordinates, license records and isolation disclosure.
- `sources/public/`: complete unmodified public source documents.
- `sources/excerpts/`: complete short documents or a structurally bounded meeting agenda section, copied without rewriting or sentence selection.
- `sources/synthetic/`: complete AI-authored fictional source documents; each identifies its synthetic provenance.
- `licenses/rust-lang-team/`: unmodified pinned upstream MIT license, Apache-2.0 license and README applying those licenses to repository content. The reuse choice for the public copied material is MIT. Original notices in source files are retained.
- `summary.json`: parent-safe counts, hashes, provenance and candidate freeze identity only; every other authored file is bound by SHA-256.
- `author_validation.py`: custodian-only construction record containing questions and oracles; do not re-run after this pool is frozen.
- `verify.py`: offline schema, byte/hash, source-coordinate and evidence-coordinate checks; optional read-only upstream reproduction.

## Public reproduction and window policy

Public sources are from `https://github.com/rust-lang/lang-team` at commit `c45345e32e81e273aab6c805b0d3cd7b1a666045`. Every manifest entry provides its upstream path, commit-pinned raw URL and SHA-256. No mutable branch URL is used for reproduction. Five short documents are included in full. The larger planning record contributes its complete initial agenda block, from the start of the file up to but excluding the `Active initiatives` heading. That block preserves metadata, attendance, roles, the full proposed-meeting list, the full schedule and both proposal discussions. The complete original file remains available to the independent reviewer.

Windows are document-structure based rather than collections of gold answer sentences. All offsets count Unicode codepoints in the preserved original UTF-8 source; `end_offset - start_offset == len(text)`. The longest context pack is checked under 7,000 codepoints. Actual token counts are intentionally unmeasured; downstream code must enforce its preregistered context budget without silently changing validation contents.

Synthetic sources use an unrelated fictional archive-map digitization workflow. Full bounded documents supply prospective and completed work, old and updated assignments, same-object recapture counts, and missing supporting records. One context includes a clearly quoted instruction-like annotation as untrusted source data. It is not an instruction to the assistant or reviewer.

## Verification

From repository root, using the existing locked Python environment without synchronizing dependencies:

```powershell
uv run --no-sync python data/evaluation/meetings-qwen35-validation-v1/verify.py
uv run --no-sync python data/evaluation/meetings-qwen35-validation-v1/verify.py --check-upstream
```

Both commands print only aggregate counts. The second re-fetches pinned originals and license files into memory and checks their hashes; it does not write source files. Neither command invokes a model, tokenizer or GPU. The strict request type is imported and used only for request validation.

The custodian uses `--check-upstream --write-summary` during preparation, including after the authorized targeted independent-review corrections. `--write-summary` is restricted to preparation before the final fixture freeze. After that freeze, do not change inputs, oracles, sources, licenses, construction record or verification code. Any later evaluation must report schema success separately from semantic correctness, citation support/completeness and valid insufficient-evidence responses.

## Independent review audit

`independent-review.json` preserves the initial 12-case semantic review, original artifact hashes, initial two clarity findings, and event order. The authorized follow-up addresses only those original findings: one question is narrowed to the opinion actually expressed in the source, and one grading fact is narrowed to the information actually requested. Source documents and evidence quotations do not change. The matching construction record is updated so that it reproduces the corrected artifacts.

After the initial findings and automatic checks, the reviewer incidentally saw candidate-failure information through an agent-inventory tool. No complete blind-review claim is made. The receipt preserves this limitation; the custodian does not read or reproduce the failure details. Subsequent review is restricted to resolving the two already identified clarity findings. The final `summary.json` reports receipt hash, completed-review counts, unresolved findings, readiness and the blinding limitation without exposing question or oracle text. The pool remains unqueried by any service model. The original pending-review declarations in the construction-stage manifest and oracles describe that earlier stage; the independent receipt and summary provide the current review state.
