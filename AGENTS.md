# DocTrail project instructions

## Current checkpoint (2026-10-30)
- Goal remains ACTIVE; phase 1 and draft PR14 are incomplete. The latest user asked for candid progress and less delay. Prioritize actual AI quality comparisons and service integration over new preparation frameworks or repeated passed checks.
- Branch feat/meeting-intelligence, HEAD a8cd66ef3ef6f71a18ab0911b663f68ee1ba5484; verified Git author/committer lingter100. Published template repair adapter fc983eee remains fixed. New tested3source: browser286bb146, runner9fcfc292, QA test40747527; preserve exact bytes for combined publication.
- Exact CI is CLOSED: push40980942562/watch53847 exit1 (browser157 pass/1 fail), PR40980948287/watch69201 exit0 (browser158 pass). Backend/web both passed; actual Java HTTP/operations passed. Do not report both runs as passing, rerun blindly, or start new model controls yet.
- Astra high baseline_resume_executor completed the test-only meeting-ready race repair: deterministic failure preserved, focused6PASS/typecheck/build, receipt7cbb7ace, parent35refs verified. It also owns runner.py + QA test2 for the narrow v3 path delta, focused7PASS/Ruff. Combined Astra xhigh review914684fc accepted blockers0/advisories0; all3source owners returned. Parent owns docs/CI/Git; no controls/model/private semantics.
- Existing Astra xhigh baseline_resume_review returned the minimal next decision: .local/meeting-free-qa-after-baseline-repair-decision-v1/FINAL-RECEIPT.json (a57829b3). Sequencing amendment89df7b5f allows the confirmed test-only fix and v3 constant/existing tests in ONE next publication/exact CI. Both new workflows must pass before controls/model work. No extra design stage or startup diagnostic. Reuse the existing 14 sealed inputs, criteria, settings and observer code; new neutral1 is required by the same-contract predecessor guard, followed by baseline6/candidate6.
- Baseline v2 actual is CLOSED/STOPPED/consumed: generation0, all6unexecuted, free_qa_runtime_template. Full custody accepted, HOLD released. Never retry v2 or start its candidate. Preserve .local/meeting-free-qa-paired-v2-baseline-actual-v1 and parent-closeout-v1. Root cause proved from exact public props; precise Ministral mapping repair is published, independently accepted, not actual AI quality success.
- Earlier neutral v2 succeeded once (generation1/valid1/21.031s); startup v2 health/props succeeded with generation0. Both are consumed and must not be rerun. Do not transplant old neutral as a new contract predecessor.
- Canonical data/meetings/free-qa-trusted-locks-v2.json is local/untracked and must NEVER be staged. No canonical v3 controls or actual execution yet. Closed contracts, original inputs, consumed once files and failure evidence remain immutable.
- Parent, implementer and this reviewer do not open private question/criteria/answer semantics. The prior exact public GET /props exception is closed. Opaque hashes/IDs/status are allowed; judging follows the sealed original role/criteria rules.
- Full previous checkpoint history is preserved byte-for-byte in docs/history/AGENTS-2026-10-30-before-compaction.md. It is historical evidence, not a list of active assignments. Consult relevant receipts/STATUS only; do not recursively replay historical plans.

## Scope and truthfulness
- Build a solo junior AI Engineer portfolio. Data quality, retrieval experiments, failure analysis and operational correctness take priority over feature count.
- Current priority: docs/MEETINGS-DESIGN.md phase 1 (text meetings, actual local AI summary, integrated RAG with cited natural answers, decision changes, assignee tasks, polished existing UI and real-data/regression verification). No recording/STT/realtime/external meeting integrations before phase 1 completion.
- Preserve completed M2/M3/M4 experiments, M5-A/B frozen inputs, all closed C0-C5/v7 and QA runs. Do not rerun closed experiments, tune on isolated validation/final test, or modify plan-bound source. Follow the original relevant freeze/role rules before touching any artifact.
- M4 trained checkpoint remains explicitly experimental; BM25/base defaults remain unchanged. Final test is locked and human review is not complete. Python results are not Java service measurements.
- Separate plans, synthetic fixtures, AI-authored/automatically reviewed data, actual model results, local operations, CI, user review and public deployment. Passing tests/citations alone do not prove semantic correctness. Never invent feedback, performance or approval.
- Free/local service models only. No paid APIs, rented GPU/cloud, credit charges or repeated paid-approval questions unless the user reopens this. Public GitHub source/push is authorized; public service deployment requires separate approval.
- Preserve prior Python service for regression. Current service is Java21/Spring, React/TypeScript, Python for AI/data/training/evaluation. No unnecessary architecture changes.
- Do not commit secrets, local databases, uploaded/private documents, weights, cached corpora or personal environment paths.
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
