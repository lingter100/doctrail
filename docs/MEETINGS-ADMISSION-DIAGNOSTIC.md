# Bounded admission diagnostic

Design only, 2026-10-20. Phase 1 remains incomplete.

This is one small engineering diagnostic of the existing C7 admission rule. It is not a new quality candidate, source-admission attempt, public-source feasibility result, or model-quality experiment. The current source-stage outcomes and verified product fixes are committed before implementation. The parent owns root documentation, CI evidence, Git, and subsequent authorization.

The designer is the existing `/root/c7_calibration_author`, accepted as `gpt-6-astra`, `xhigh`, `fork_turns=none` through the actual role invocation; this is not runtime model introspection. The designer previously read and authored calibration sources and is **not an independent source reviewer**. This design used frozen code, generic tests, the protocol, and safe aggregate outcomes only. It did not reread actual sources/receipts, questions, oracles, closed pools, or validation semantics. No implementation, tests, Git, network, tokenizer, native execution, or downloads were performed for this design.

## Question and fixed boundary

Does the frozen implementation match its documented lossless block accounting, and does the additional 24-block rule exclude generic syntax examples that satisfy the separate rendered byte limits?

Whitespace blocks and overlapping emitted chunks intentionally count. A count-only refusal is not itself a parser defect. The current `family_admission` records `blocks: null` before calling `catalog_bounds`; rejection there precedes rendered measurements. This diagnostic adds observations in a separate result without changing that original decision or receipt.

Keep C7's protocol, parser, processor, metadata limits, 24-block limit, 6656-byte full-family envelope, 4096-byte schema, 32768-byte reserved wire limit, and all other gates unchanged. No threshold sweep, source selection, rejected-source rescue, corpus substitution, question, tokenizer, chat-template application, HTTP/model invocation, Maven, or quality score is allowed.

## Small implementation surface

After separate dispatch, a different actual Astra high implementation role owns only:

- `scripts/diagnose_meeting_admission.py`: one CLI and small reusable measurement functions.
- `tests/fixtures/meeting-admission-diagnostic-v1.json`: the fixed twelve fully expanded inputs and independently entered expectations below.
- `tests/test_diagnose_meeting_admission.py`: targeted synthetic checks.

Do not copy or version the toolchain, create a candidate/family/role registry, or change frozen files. Existing C7 code is the subject being observed. Bind the existing `data/evaluation/meetings-c7-toolchain-freeze-v1.json` SHA256 `6f829eeb829b957683fb2a7c4b6182a14aab787d816ede11b1c017bbe69a65ca`, its 77 existing bound file hashes, this design, and the three new implementation files in run evidence. Record their actual implementation commit and exact bytes; do not embed a future commit in this design.

Use these real frozen functions, with no runtime replacement, mock processor, hash/parse cache, or substitute renderer:

| Step | Frozen entry point |
| --- | --- |
| Decode and normalize each UTF-8 Markdown input | `doctrail.ingest.extract(raw, "md")` |
| Produce all original chunks | `doctrail.retrieval.chunk_content(content, pages)` |
| Build sorted whole-family contexts | `scripts.prepare_meeting_c7_inputs.whole_contexts(documents)` |
| Original decision, exactly once per official fixture | `scripts.prepare_meeting_c7_inputs.family_admission("calibration", family, documents, toolchain_hash)` |
| Separate observations | `Context.model_validate`, `doctrail.meeting_answer_blocks.build_block_catalog`, `answer_messages_thinking("", catalog, language)`, `answer_schema_thinking`, `safe_payload`, and `request_body` |

This calls the unchanged **pure family decision**; it does not call `admit_sources`, `load_material`, `prepare_answer`, or any actual corpus/role/source workflow. The generic fixture uses the existing family ID `c7-f01` solely because the pure function requires it. Outer evidence must identify `kind=synthetic_admission_diagnostic`, `actual_source_admissions=0`, and `quality_candidate_created=false`; nested C7 identifiers do not make these test strings adopted C7 data.

## Exact twelve fixtures

JSON stores literal expanded strings, not executable recipes. The following notation specifies those strings exactly: `H(n)` is `"# h\n"` repeated `n` times; `P(n)` is `n` copies of `"p"` joined by `"\n\n"`; `X(n)` repeats `"x"`; `K(n)` repeats `"가"`. Backslash escapes below mean their actual Unicode characters. There is no added trailing newline.

Every fixture has three documents A, B, C, ordered in that order. Unless specified, A's raw string is the table entry, B is `"b"`, and C is `"c"`. Encode raw strings as UTF-8. Metadata is fixed: document IDs `diag-a`, `diag-b`, `diag-c`; titles `A`, `B`, `C`; revision 1; page null; A and B are meetings dated `2040-01-01` and `2040-01-02`; C is general with null date. Language is `en`, except A in F11/F12 is `ko`. Source ID equals document ID, registration ordinals are 0/1/2, and every document belongs to `c7-f01`. Each emitted chunk ID is `{document_id}-r1-c{ordinal:04d}`, using the processor's zero-based ordinal.

Create the minimal source/document structures required by the pure function from these fixed metadata and actual processor outputs, including actual raw/processed hashes and exact chunk fields. These structures are synthetic test adapters, not provenance manifests or adoption receipts.

Counts below are family totals. `E/W` means eligible non-whitespace blocks / whitespace-only blocks. Byte totals are processed source text / emitted chunk text, including overlap. They are hand-derived expectations, not measurements made for this design.

| ID | Exact raw A | Chunks | Blocks | E/W | UTF-8 totals | Original admission expectation |
| --- | --- | ---: | ---: | --- | --- | --- |
| F01 | `"\ufeffe\u0301\r\nx\ry"` | 3 | 3 | 3/0 | 8 / 8 | passed |
| F02 | `H(21)` | 3 | 23 | 23/0 | 86 / 86 | passed |
| F03 | `H(22)` | 3 | 24 | 24/0 | 90 / 90 | passed |
| F04 | `H(23)` | 3 | 25 | 25/0 | 94 / 94 | rejected: `c7_block_bounds` |
| F05 | `P(11)` | 3 | 23 | 13/10 | 33 / 33 | passed |
| F06 | `P(11) + "\n\n"` | 3 | 24 | 13/11 | 35 / 35 | passed |
| F07 | `P(12)` | 3 | 25 | 14/11 | 36 / 36 | rejected: `c7_block_bounds` |
| F08 | `"Items:\n\n- a\n- b\n"` | 3 | 3 | 3/0 | 18 / 18 | passed |
| F09 | `"```txt\nx\n\n# h\n- a\n```\n"` | 3 | 3 | 3/0 | 24 / 24 | passed |
| F10 | `X(1100)` | 4 | 4 | 4/0 | 1102 / 1252 | passed |
| F11 | `K(682) + "ab"` | 3 | 3 | 3/0 | 2050 / 2050 | passed |
| F12 | `K(683)` | 3 | 3 | 3/0 | 2051 / 2051 | rejected: `c7_document_bytes` |

Additional hand-expected invariants:

- F01: A raw bytes are 11, raw family bytes 13; normalized A is exactly `"é\nx\ny"`, five code points and six UTF-8 bytes. BOM removal, NFC, and CR/CRLF normalization are expected processing changes, not lost parser text.
- F02–F04: each `"# h\n"` is one eligible block, even without intervening blank lines. A ends at code-point offsets 84, 88, and 92 respectively.
- F05/F07: the first `n-1` paragraph quotes are `"p\n"`, each followed by a separate `"\n"` quote; the last paragraph quote is `"p"`. F06 instead ends with paragraph `"p\n"` followed by whitespace `"\n"`. Whitespace preserves offsets and consumes block budget but is absent from eligible evidence IDs.
- F08: A is one intact block including its introduction, intervening blank line, and both list items. F09: A is one intact fenced-code block; its blank line, apparent heading and list remain literal interior text.
- F10: A chunks are exactly `[0,1000)` and `[850,1100)`. Its emitted text totals 1250 bytes, including 150 bytes of overlap. Both chunks remain separate; neither merge nor duplicate removal is permitted.
- F11: A has 684 code points and exactly 2048 UTF-8 bytes. F12: A has 683 code points and 2049 bytes. Both remain one processor chunk and one parser block. F12's earlier document-byte refusal remains the original decision even though the generic parser can be observed separately.
- Apart from F10, each document has one chunk `[0,len(processed_content))`. Within every chunk, concatenating its block quotes reproduces that chunk exactly; offsets are contiguous and exact slices of processed content. Chunk concatenation across overlap is **not** expected to reproduce a document without duplication.

All twelve are expected to support the separate raw-catalog render observation, with both languages satisfying `E(M0) <= 6656`, compact schema bytes `<= 4096`, and empty-query wire bytes `+ 4096 <= 32768`. These are explicit hypotheses to verify, not registered measured byte values. In particular, F04/F07 are the predeclared count-only-refusal hypotheses. An unexpected result is retained as a discrepancy; do not change inputs or metadata to obtain the expected result.

The fixture file must store these expectations literally. Never generate expected counts, offsets, decisions, or hashes from the code under observation and then call their agreement verification. Hashes of the implementation fixture bytes are recorded after authoring; exact rendered byte counts and hashes are observations.

## Measurements and separation of decisions

For each fixture, preserve the returned `family_admission` object exactly as an `original_admission` value. An expected rejection is an observed result, not an execution failure. Do not fill its null fields, replace its status, or introduce a second acceptance path.

Separately build the catalog from every actual emitted context. This uses the frozen parser's ordinary limits, not C7's `catalog_bounds` gate, so the diagnostic can observe 25 blocks without pretending admission passed. Render that unchanged catalog with the frozen empty-query renderer for `ko` and `en`; no `AnswerRequest` with an empty query is constructed.

Record:

- Raw and processed hashes, UTF-8 bytes and code points per document, normalization identity/change, pages, and metadata hashes.
- All chunk identities, exact offsets and hashes, per-document and family chunk counts, UTF-8 sizes, total emitted bytes, and overlap counted separately from unique covered code points.
- Block offsets and quote hashes, total/eligible/whitespace counts, maximum block code points and UTF-8 bytes, exact per-chunk reconstruction, and unchanged originals before/after calls. Generic quotes may appear in diagnostic evidence; no real source content may.
- Per language: `M0_sha256 = SHA256(safe_payload(messages).encode("utf-8"))`, `E(M0)` using those same bytes, compact schema bytes using the frozen `canonical(schema)`, and wire bytes using `len(json.dumps(request_body(messages, schema)).encode("utf-8"))` with unchanged serialization defaults. Record the existing reserves and each comparison separately.
- Comparison with every hand-expected invariant, original decision, and original rejection code. If the original admission includes rendering measurements, require exact equality with the separate observation. If it does not, label the new fields `diagnostic_only`; they do not retroactively complete that receipt.

Do not infer token count, chat-wrapper size, latency feasibility, semantic adequacy, or public-source feasibility from these bytes. Under lossless substring construction, the 2048-byte per-block bound is already implied by the 2048-byte per-chunk bound; record this as an invariant checked on these fixtures, not permission to remove either guard.

## Unit checks and one official evidence run

Unit verification may call the synthetic helpers separately before implementation review/commit. It may exercise the fixed fixtures, strict fixture validation, repeatability, isolated temporary directories, hash mismatch refusal, output reservation, and controlled I/O-failure persistence. Production parser/admission/renderer behavior must remain real in those checks. Unit output is labelled unit verification and is not the official diagnostic evidence. Any unexpected fixture expectation failure is preserved and reviewed; this design does not authorize silently rewriting an expectation or input.

The official diagnostic runs **once**, only after the different implementation role finishes, independent code review resolves blockers, the implementation/design/fixture/test bytes are committed, and the parent verifies the applicable normal CI. There is no requirement for a new toolchain freeze or a separate CI-receipt commit for each documentation update. The parent coordinates the fixed committed HEAD for the short official run.

Use one fixed CLI entry, for example `python -m scripts.diagnose_meeting_admission`, with no fixture-filter, alternate-corpus, cap, retry, or continue-from-row options. It reads only its fixed fixture, this design, its own implementation/test bytes, and the existing frozen code/metadata allowlist. Verify current and committed bound bytes and HEAD before fixture evaluation; recheck relevant bytes and HEAD before declaring success. Never inspect actual source/pool directories or source receipts.

Reserve a new fixed ignored directory `.local/meetings-admission-diagnostic-v1` exclusively before any fixture evaluation. Existing directory means consumed: exit without running fixtures. Keep an immutable reservation with start time, HEAD and input hashes, append each completed row durably in F01–F12 order, and write a terminal receipt and matching compact CLI summary. A terminal receipt binds the row bytes/hash, completed IDs, unexecuted IDs, first error, later persistence errors, input/code hashes, and zero model/network/tokenizer counters.

Execute the unchanged family admission once per fixture, followed by its separate observation. Stop on the first unexpected exception, invariant discrepancy, hash/HEAD drift, or persistence error; preserve the original cause and partial/unexecuted rows. The three predeclared rejections do not stop the matrix when they match expectations. Do not retry, overwrite a failed run, edit inputs, or resume its remaining rows. If terminal writing fails, preserve the reservation, rows and CLI failure output; absence of a durable terminal receipt cannot count as success.

Successful evidence requires exit zero, all twelve expected observations verified, a durable matching receipt/summary, and unchanged bound bytes/HEAD. Unexpected findings require review and a separate next decision, not automatic extra execution. After this single implementation/test/result cycle, stop; this is not a new recurring diagnostic program.

## Outcome decisions

| Evidence | Permitted conclusion and next decision |
| --- | --- |
| Reconstruction, offsets, documented structural grouping, or a boundary decision differs from the hand expectation | Preserve a minimal generic discrepancy. Independently determine whether implementation or hand expectation is wrong before proposing any narrow repair. No automatic code or threshold change. |
| Accounting matches, and F04/F07 alone fail the block gate while their complete rendered observations fit | The 24-block rule is an additional formatting restriction in these synthetic examples. This is expected policy behavior, not proof of a defect or evidence that a larger limit is safe. |
| Accounting matches but rendered limits also fail | The hypothesized count-only restriction is not demonstrated for that fixture. Record both constraints; do not search for a replacement example after seeing results. |
| All fixed checks pass | End the diagnostic. Before any new quality candidate, use an independent, bounded source-feasibility review to decide whether unchanged full semantic requirements and intact licensed public families are practical. No automatic new toolchain/corpus cycle. |
| Run or evidence is incomplete | No successful diagnostic conclusion. Preserve failure, including unexecuted cases; parent decides any later work separately. |

No outcome rescues a rejected C7 family, licenses reuse of closed data, weakens full-answer semantics, measures model quality, completes Phase 1, or authorizes deployment.
