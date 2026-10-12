# DocTrail project instructions

## Scope and truthfulness
- Build for a solo junior AI Engineer portfolio: data quality, retrieval experiments and operational correctness take priority over feature count.
- Current milestone: M3 frozen-data comparison of multilingual embeddings, reciprocal-rank fusion and reranking, followed by permission-aware service integration. Keep M2 inputs/reports and the verified upload/search/evidence service intact. Do not claim model improvements, service integration, generated answers, training, human review or production deployment until measured.
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
- Use uv with Python 3.11, locked dependencies, TypeScript frontend; run relevant tests and a production frontend build before integration.
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
