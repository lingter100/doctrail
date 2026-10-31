# DocTrail project instructions

## Active checkpoint — 2026-10-31
- User explicitly resumed with “완성까지해”; existing goal and doctrail heartbeat are ACTIVE. Phase 1 and whole portfolio remain incomplete. Free/local only; public source publication authorized, public service deployment and human review are separate.
- Branch feat/meeting-intelligence, PR14 draft, published HEAD ff879a00. Its push41201778897/PR41201783981 required CI CLOSED PASS: Python6001/21skip, browser162 each, Java/ops/web/frozen-source gates. This CI does not cover newer working changes. No live model/CI watcher remains.
- requested_facts_v1 actual CLOSED: technical2/2, independent semantic0/2; Korean2/2 but completeness/abstention failed. Public result experiments/results/meetings-qa-request-contract-v1.json. No service adoption.
- evidence_plan_v1 current8 implementation reviewed with0blockers (d02ac018), core49 focus + affected span7 and verifier9 checks/Ruff passed; overlapping checks are not summed. Latest modulecee30389/test6df241fe/runtime7bdfee49/test32dba079/verifier91ff6211/test5c1b9add/launcher c09e428e/test0f40e68c. Authors returned; these8 await joint publication and exact CI.
- Actual evidence-plan-service-v1 CLOSED FAILED: FINAL .local/meeting-evidence-plan-service-v1-launch/FINAL.json cede4b1c; session15789 naturalCLI1/outer19.937s, first plan299in/87out/EOS rejected generation_invalid_evidence. Native1/acceptedplan0/ledger0; second QA unattempted. Known9+launcher absent/cleanup0/80refs unchanged, HOLD released. Diagnosis c788db6f identifies mixed-language regenerated time plus empty entity and bundled endpoints. No retry/regrade/automatic limit increase; old outputs preserved. Public actual and diagnosis reports saved.
- Independent public transfer6 is frozen, SAFE .local/meeting-evidence-plan-transfer-v1/SAFE-RESULT.json ac43c64d, sourcesf268f6a3/cases9f23a04a. Only execute after unchanged OPEN2 independently pass with frozen candidate. Parent/implementers SAFE-only before freeze; do not tune on this packet. Human0, not locked validation/finaltest.
- Current sole code assignment: existing Astra high qa_representation_measure owns NEW src/doctrail/meeting_agenda_extraction.py + tests/test_meeting_agenda_extraction.py ONLY. Accepted Astra xhigh design .local/meeting-summary-context-design-v1/RESULT.md proposes one agenda-aware joint summary/items completion, unchanged source/API/resource limits and768 output/shared120s; no actual authority. Runtime/core/verifier integration requires a later explicit ownership assignment after publication. Parent owns docs/results/publication. Other agents are locally closed.
- Next: publish verified QA experimental code and preserved failures via user identity/PR14/required CI, continue the separate agenda extraction implementation, and use diagnosis for one justified QA representation repair. Do not replace quality work with more receipt frameworks, repeat passed checks without cause, or claim completion from tests/CI.
- Historical checkpoints and exact prior failure references are preserved in [the pre-closeout archive](docs/history/AGENTS-2026-10-31-before-evidence-plan-closeout.md), [earlier history](docs/history/AGENTS-2026-10-30-before-compaction.md), STATUS and individual reports. Read only the history relevant to the next task, not every closed experiment. All old private QA, frozen sources and final-test rules below remain binding.
## Scope and truthfulness
- Build a solo junior AI Engineer portfolio. Data quality, retrieval experiments, failure analysis and operational correctness take priority over feature count.
- Current priority: docs/MEETINGS-DESIGN.md phase 1 (text meetings, actual local AI summary, integrated RAG with cited natural answers, decision changes, assignee tasks, polished existing UI and real-data/regression verification). No recording/STT/realtime/external meeting integrations before phase 1 completion.
- Preserve completed M2/M3/M4 experiments, M5-A/B frozen inputs, all closed C0-C5/v7 and QA runs. Do not rerun closed experiments, tune on isolated validation/final test, or modify plan-bound source. Follow the original relevant freeze/role rules before touching any artifact.
- M4 trained checkpoint remains explicitly experimental; BM25/base defaults remain unchanged. Final test is locked and human review is not complete. Python results are not Java service measurements.
- Separate plans, synthetic fixtures, AI-authored/automatically reviewed data, actual model results, local operations, CI, user review and public deployment. Passing tests/citations alone do not prove semantic correctness. Never invent feedback, performance or approval.
- Free/local service models only. No paid APIs, rented GPU/cloud, credit charges or repeated paid-approval questions unless the user reopens this. Public GitHub source/push is authorized; public service deployment requires separate approval.
- Preserve prior Python service for regression. Current service is Java21/Spring, React/TypeScript, Python for AI/data/training/evaluation. No unnecessary architecture changes.
- Do not commit secrets, local databases, uploaded/private documents, weights, cached corpora or personal environment paths.
- Within assigned scope, repair ordinary local metadata/implementation mistakes autonomously in preserved new variants; do not add approval/design loops for each fix. This never permits replaying a closed actual model run, weakening frozen criteria/limits, or mutating another owner's files.
- Read docs/STATUS.md, docs/DECISIONS.md, docs/CONTRIBUTIONS.md plus Git/process/goal state before resuming. Respect explicit pauses and do not duplicate jobs. Keep progress docs concise and outside actual-run immutable holds.

## Workflow
- Use Conventional Commits: feat, fix, docs, test, chore, refactor, ci; lowercase English scope and short imperative subject.
- Use main for verified integration; short feature branches feat/<topic>, fix/<topic>, docs/<topic>; open PRs with purpose, checks and limitations. No permanent develop branch for this solo project.
- Use the repository-local verified user identity for author and committer. Never invent a human review or remove AI contribution disclosures.
- Each milestone updates docs/STATUS.md, docs/DECISIONS.md and docs/CONTRIBUTIONS.md with verified results, commands, limitations and next steps.
- The user authorizes autonomous continuation through the existing roadmap without repeated proceed questions. A thread heartbeat resumes work hourly. Follow docs/AUTONOMY.md, preserve user review and paid/public-deployment approval boundaries, and do not duplicate running jobs.
- Keep changes narrowly staged. Never modify a sibling agent's owned files without coordinating.
- Use Java 21 and the pinned Maven wrapper for the service, uv with Python 3.11 and locked dependencies for AI/data experiments, and React + TypeScript + Vite frontend. Run relevant Java/Python checks, a production frontend build and browser regression checks before integration. Do not add Python subprocesses behind a Java facade for core service behavior.
- Local model commands use `uv run --group retrieval ...`; normal CI and BM25 do not require the heavy retrieval group. Do not run dependency synchronization concurrently with active model inference.

## Models and delegation
- User authorizes subagents. Design/data/evaluation/major architecture: gpt-6-astra xhigh. Implementation/tests/fixes: gpt-6-astra high. Repetitive cost-conscious implementation: gpt-6.1-sol high. Complex unresolved comparison only: gpt-6-astra max.
- Record actual tool-accepted settings; never claim the parent chat model was changed without evidence.
- Development assistant models are separate from service inference/training models.

## Security and retrieval
- Authenticate from server-side sessions, not client-supplied user IDs. Check workspace membership and document ACL before scoring, listing, direct access, edit, delete, history and feedback.
- Atomic revision replacement must invalidate previous chunks. Deleted documents must not remain searchable.
- Render document content as text or sanitized markup, never raw uploaded HTML.
- Keep raw document/question text out of operational logs; preserve request IDs and safe error codes.
