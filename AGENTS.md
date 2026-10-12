# DocTrail project instructions

## Scope and truthfulness
- Build for a solo junior AI Engineer portfolio: data quality, retrieval experiments and operational correctness take priority over feature count.
- Current milestone: Java/React model integration is verified. M4 preserves the original 78-question pilot and adds 2 independently AI-reviewed calibration questions in m4-pilot-v2. Readiness v1 actually reviewed 256 negatives and tokenized all80 questions: fit048 has no accepted negative; 12 fixed negative pairs truncate; data_ready=false. Preserve v1 evidence. Follow additive m4-readiness-plan-v2 for next4 fit048 candidates and independent actual truncated-input review; no easier-candidate substitution or question removal. Probe/training have not run. Check STATUS and active jobs/PR CI before resuming. Python remains inference/data/training/evaluation; never reinterpret Python experiment measurements as Java service performance.
- Preserve provenance. Mark synthetic examples, AI-authored questions, automated checks and user review separately.
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
