# M2 question authoring protocol v1

This file is the recorded instruction artifact for AI-assisted candidate authoring,
not a reproducible model inference recipe. The tool-accepted assistant model and
effort are recorded in jobs.json. No paid service API is called. Human review is
pending for every candidate. Source excerpts retain Kubernetes Authors CC-BY-4.0
attribution; source paths/versions/licenses are in the frozen corpus manifest.

Read the assigned job in jobs.json and only author evidence from its allowed_document_ids.
Read actual verified processed document text before selecting facts. Never invent or
reconstruct an exact quote from memory. Each quote must be a contiguous exact excerpt
of the normalized document. Unicode codepoint offsets are added by build_questions.py.
Do not edit source content, split assignments or retrieval code to fit questions.
Do not run retrieval on test questions. Do not inspect ranking results to write questions.

Write one JSON object to the job's draft_path with job_id and questions. Every question
has id (job_id plus three digit index), question_family_id, query, language (ko/en),
category (single_document/multi_document/no_evidence/ambiguous), reference_answer,
and evidence (a list). Positive evidence items have document_id, quote,
evidence_group_id and grade=2. Negative and ambiguous questions have evidence=[],
reference_answer="", and negative_reason explaining a specific plausible unsupported
fact or missing condition. The compiler adds other provenance/schema/scope fields.

For independently required facts use separate evidence_group_id values. Alternate
sufficient passages or verified translations for the same fact use the same group.
A multi_document question must actually require facts in at least two documents,
not simply ask the same fact in two languages. Do not join unrelated facts merely
to manufacture multi-document examples. Prefer a practical engineering decision
with complementary roles, constraints or diagnostic steps across two sources.
If you cannot find enough meaningful multi-document questions, report the shortfall
instead of padding the count.

Target each job's category/language quotas, use at least 20 distinct positive source
families when the pack allows it, and spread facts across the assigned documents.
Prefer realistic engineering problems, paraphrases, troubleshooting and decisions.
Avoid copying headings into all queries, adding the answer into the question,
unnecessary boilerplate, or changing only a number/name to create duplicates.
Related questions that differ only in phrasing share question_family_id and should
normally be reduced to one candidate. Avoid querying private passwords/secrets.

Aim for at least 20 positive Korean questions per job with required English-source
evidence. This is a target, not a label to fake. If a Korean equivalent is also in
the assigned pack, inspect it and add a genuinely sufficient alternate span when
present; translations can drift. Incomplete gold labels are a known limitation.
Do not call cross-language retrieval necessary just because an English quote was
selected; evaluation derives language groups from all actually annotated alternatives.

No-evidence questions must be plausible within an internal-doc search experience,
but their asked fact must be absent from the whole fixed indexed corpus (all splits).
Inspect the corpus inventory and use local text searches to challenge negative claims;
record the rationale and limits of that automatic check, never claim exhaustive human
verification. Avoid nonsense strings, arithmetic riddles, or obviously unrelated trivia.
Ambiguous questions should have missing operational context that prevents one reliable
answer. Their negative_reason names the missing conditions and what clarification is
needed. These labels remain provisional; no-evidence and ambiguous are not scored as
generative answer accuracy or abstention in M2.

Reference answers are AI-authored annotation aids based only on cited facts. They
are not service-generated answers. Keep them concise and faithful. Prefer evidence
spans of about 40–350 Unicode characters; use multiple separate required facts when
appropriate. Do not select >1,000-character spans that cannot fit the current chunk
window unless documenting a deliberate boundary stress case in an annotation note.
Keep all generated IDs deterministic and all authored files UTF-8 with LF endings.

After drafting, run the compiler for your job and structural validation only. Correct
quote/offset/schema failures against sources. Do not claim semantic correctness from
those checks. Report source family coverage, actual category/language counts, limits
and any automatic checks you actually performed. Do not commit or push; parent agent
integrates and records actual contribution and checks.
