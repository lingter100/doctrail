# DocTrail project instructions

## Scope and truthfulness
- User explicitly resumed this project on 2026-10-13 with "진행해". Heartbeat doctrail is ACTIVE again; the prior pause handoff remains in docs/STATUS.md for provenance. Preserve completed work and do not duplicate model jobs.
- Build for a solo junior AI Engineer portfolio: data quality, retrieval experiments and operational correctness take priority over feature count.
- Current milestone: M4 bounded E5 training, internal calibration, frozen once-only main-dev comparison and checkpoint-bound local operational validation are complete. Preserve failed readiness v1/GPU v1.1 and successful fixed-scale1024 v2 training (16 real updates). Main-dev fresh base→terminal whole-evidence @50 34→47/59 and @5 29→37/59 passed the gate, with 2 @50 and 6 @5 regressions; multi-document @5 fell 1→0/7. Actual terminal Java/React operations16 checks passed at61285dd with base rollback/history preservation; terminal remains explicit experimental, BM25/base defaults unchanged. Follow M4-OPERATIONS-RESULTS, M4-MAIN-DEV-ANALYSIS and STATUS: next is M5 grounded-answer/abstention design and local generation model resource/license review, not automatic adoption or more retrieval tuning. Do not rerun calibration/main-dev; test locked, human0. Check active jobs/PR CI. Python remains inference/data/training/evaluation; never reinterpret Python measurements as Java service performance.
- Preserve provenance. Mark synthetic examples, AI-authored questions, automated checks and user review separately.
- Add new experiment entrypoints for follow-up work; preserve all source files bound by completed M2/M3/M4 execution/evaluation plans so saved result replay stays valid.
- Paid APIs/GPU/cloud and public service deployment require the user's approval. Public GitHub source repository creation and push to the authenticated user's account are explicitly authorized.
- Do not commit secrets, local databases, uploaded documents, model weights, cached corpora or personal environment paths.

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
