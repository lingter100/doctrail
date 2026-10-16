# C3 calibration item prereview

Reviewed on 2026-10-14 by `/root/c3_calibration_source_review`: accepted 6, rejected 0, requested changes 0. This is an AI item prereview independent of the question/oracle author, with human/user review count 0. It is not a model-output evaluation, official token-budget result or service-adoption decision.

The reviewer read all six questions, all required facts and their complete evidence alternatives, the selected unchanged whole chunks, and all four complete adopted source bodies. The two missing-information judgments below were made against the full source families, not only the selected contexts. No source, draft, oracle, context selection or author receipt was edited. Only this note and `item-prereview.json` were created; no item freeze or Git mutation was performed.

## Provenance and exposure

The source freeze is `source-freeze-v1.json`, SHA256 `e423804942438acfa38c8bb77095905761a9c9098ce743d33b289048cc6b3676`, with all 9 bound files unchanged. The parent confirmed source commit `d02697e171e575533fb81fd651b007a9fc87499b` and successful required push/PR CI before this item handoff. The reviewer checked local freeze/source hashes and did not repeat a remote CI query. All 66 whole-toolchain bindings also remain unchanged.

Every `question_author` and `oracle_author` is `/root/c2_calibration_source`; their exact union is the single author ID in the review JSON. All six oracles name this separate reviewer. The parent's task confirms retention of this role's actual `gpt-6-astra` / `xhigh` setting; no new setting change was requested or claimed here, and the parent's tool-acceptance evidence remains the basis for that configuration report.

This reviewer previously accepted the same calibration sources and has seen project AGENTS, STATUS, candidate/topic/family metadata, historical aggregate statuses, frozen preparation/review contracts, the source and item author receipts, and this calibration's bodies/questions/oracles. Source-review participation and candidate-metadata exposure are disclosed: separate authorship does not imply complete candidate blindness. This role remains excluded from independent final-output scoring. No closed pool body, isolated validation semantics or new candidate-generated output was read.

The author's earlier `pending` / completed-review-0 statuses are preserved as author-time records. This later independent review supplies the completed item judgment; it does not retrospectively change those records. The synthetic library documents and all six questions/oracles are AI-authored. Public documentation pretraining exposure, small purposive sampling, shared source/item authorship and human-review-0 remain limitations.

## Per-item semantic decisions

| Item | Language | Expected status | Required facts | Supported / missing | Essential documents | Decision |
| --- | --- | --- | ---: | --- | ---: | --- |
| C3-CAL-01 | Korean | answered | 6 | 6 / 0 | 2 | accepted |
| C3-CAL-02 | English | answered | 5 | 5 / 0 | 1 | accepted |
| C3-CAL-03 | Korean | abstained | 2 | 1 / 1 | not counted as answerable | accepted |
| C3-CAL-04 | Korean | answered | 6 | 6 / 0 | 2 | accepted |
| C3-CAL-05 | English | answered | 6 | 6 / 0 | 2 | accepted |
| C3-CAL-06 | English | abstained | 3 | 2 / 1 | not counted as answerable | accepted |

### C3-CAL-01

The question explicitly distinguishes shared application resources from a small notification after a request and asks for timing and lifecycle restrictions. F1 is supported by the resource-sharing paragraph plus the async-context-manager and recommended-lifespan paragraphs. F2 and F3 preserve the once-per-lifecycle startup/cleanup timing rather than changing it into per-request work. F4 combines the small-email recommendation with after-response execution and the client not waiting for completion. F5 and F6 retain the stated event-handler exclusion and main-application-only scope. All six facts answer an explicit part of the question, and their evidence sets identify the relevant mechanism without relying on unresolved code includes.

Two documents are semantically necessary: the full Background Tasks page does not supply the requested lifespan restrictions, and the full Lifespan Events page does not establish the notification mechanism or its after-response timing. This item also supplies the required English-source to Korean-answer direction. No unsupported durability, retry or sub-application behavior is required.

### C3-CAL-02

The task-object, callable-form, argument, dependency-reuse and scheduling requests are unambiguous within the adopted Background Tasks page. F1 retains both parameter declaration and FastAPI object creation. F2's subject is supplied by the task-function paragraph, with both normal and async forms. F3 retains the `.add_task()` action and its function/positional/keyword arguments. F4 uses the dependency-level sentence and the overlapping pieces of the reuse/merge paragraph together, preserving both the FastAPI subject and the paragraph ending. F5 establishes after-response execution and the reason the client need not wait. All five informational needs are supported; external snippets, concurrency, retry and ordering guarantees are not necessary to answer this question. It is correctly a single-document item.

### C3-CAL-03 — full-family absence checked

The first part is supported: small email work can use BackgroundTasks after returning the response. The second part specifically requires a guaranteed numeric retry count after interruption and restart. The reviewer read both complete C3-F01 bodies, including background-work caveats and the normal startup/shutdown discussion. Neither body gives that count or a recovery guarantee from which it can be derived. References to Celery/queues are not statements of BackgroundTasks recovery behavior, and normal lifespan cleanup is not crash-retry evidence. No answer-bearing source passage was removed by selection.

F1 therefore has sufficient evidence and F2 is genuinely absent from the adopted whole family. The whole-question abstention is appropriate under the registered contract. Absence must not be converted into a guaranteed count of zero or an external implementation claim. The known portion does not make the entire question answerable.

### C3-CAL-04

The question asks for purpose, approved scope, actual adjustment, dates and the later permanent-layout decision procedure. F1 preserves the conflicting circulation paths and the trial-adjustment purpose. F2 combines the proposal's shelf identification with the actual approval and excluded furniture. F3 combines the dated meeting header, scheduled work/recording period and the handover's dated work identity, rather than guessing a year from an undated sentence. F4 accurately describes Ryu's curtain-clearance adjustment and the maintained orientation; it does not replace it with the rejected north-wall proposal. F5 preserves the distinction between trial approval and the still-pending final decision. F6 identifies Moon's compilation and Cha's later scheduling as the stated follow-up procedure.

All six facts are supported and respond to the requested topics. The meeting alone lacks the later adjustment; the handover alone lacks the full purpose, approved exclusions and follow-up assignments. Both are therefore required. The source is explicitly fictional, and the oracle does not assert observed improvement or a completed final decision.

### C3-CAL-05

The first-opening reference is identified by the handover header and April 14 section. F1 comes from the meeting's rule: the named access check and arrangement/guidance check must both be complete for an area, with staff lending while a check remains. F2 and F3 preserve the difference between the ready first shelf and only the end section of the second shelf, not a whole-library closure. The overlapping table units retain the header, row identity and complete follow-up entry; the narrative separately establishes that book order was already correct and the location label was the problem. F4 keeps Moon as the actor replacing/rechecking the label, notifying Bae and removing the notice before reopening. F5 and F6 distinguish completion of that local work from completion of the trial or a final layout decision.

The event, actor and temporal links in all six facts are supported. The broader trial explanation in the question includes the pending decision and later-record review described by F6; no clock time or final vote is invented. The meeting is needed for the prescribed two-check rule and named responsibilities, while the handover is needed for the actual readiness and resolution. This supplies the required Korean-source to English-answer direction. Reasonable transliterations identify the same fictional people and are not treated as official English names.

### C3-CAL-06 — full-family absence checked

The meeting table supports Bae's feedback-recording responsibility, and the final meeting paragraph supports Moon's later compilation assignment. The question also asks for the final percentage favoring the layout. Both complete C3-F02 bodies were read, and all four family chunks are selected for this item. Neither body supplies a final percentage, numerator or denominator; the latest handover says the decision is still pending. A position inquiry is not a vote, and a planned compilation date is not a completed survey result.

F1 and F2 are supported while F3 is genuinely absent from the full family. The absence was not manufactured by withholding context. Whole-question abstention is appropriate; 0%, 100%, a majority or a final adoption outcome would be invented.

## Composition and structural verification

The registered composition holds: public family 3 items and synthetic family 3; Korean 3 and English 3; answerable 4 and partial-information abstentions 2. Answerable fact counts are 6, 5, 6 and 6, within the registered 3–6 range. There are 28 required informational needs in total: 26 supported and 2 deliberately absent. Three answerable items genuinely require two source documents, exceeding the split minimum of 2, and both language-crossing directions are represented.

The reviewer independently ran frozen `validate_draft`, C3 `validate_oracles`, full `validate_inventory` reconstruction, exact context-selection comparison, all selected-context identity checks and `check_prereview` with the actual author union and `partial_missing=True`. All passed. The selected 23 context instances are 13 distinct original whole chunks from the full 20-chunk inventory. Text, page, offsets, document/revision/title/meeting-date metadata and family identities remain unchanged. Oracle evidence coordinates match the frozen whole-unit contract; the semantic judgments above are separate from these automated checks.

One preliminary read-only display command stopped because the terminal's CP949 encoding could not print a source emoji. It was repeated with UTF-8 output; no data or source bytes were edited, and no preparation/model job ran. This display issue is not an oracle/schema failure. The completed structural checks reported no verification errors.

| Reviewed input | SHA256 |
| --- | --- |
| draft.json | `3a87a916b30552138942f6bff04ba8a9cce54d60ab522dade319373ac138a4fc` |
| oracle.json | `b408ca9377e322da426a7c86ec999feb8bf3701974115d1e8b9a736e42d66770` |
| context-selection.json | `300b9f7f991eb85205d1dd5550014c9f47fd263e7113cb5f13c82f9a6a03fd96` |
| item-authoring-receipt.json | `7669c68befd5df1d31280e198d0071f298bd976d2da5cfd68c4290cae5da677f` |

Input-budget considerations, token measurement or estimation, official preparation entrypoint calls, service/native model calls, external network calls, paid usage and human/user review during this task are all 0. This review does not establish that any input fits the tokenizer limit or that a candidate can answer correctly. Preserve the author records and this separate judgment; item freezing and committing belong to the parent before subsequent official token preparation.
