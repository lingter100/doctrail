# Service API contract

The Java service preserves this wire contract. Offsets remain Unicode codepoints, not Java UTF-16 indices. The previous Python service is retained as a reference. Migration evidence and parser differences are in JAVA-MIGRATION.md.

Prefix `/api`; JSON errors use `detail`. Opaque string IDs. Cookie sessions, browser `credentials: include`, same origin through Vite `/api` proxy to 127.0.0.1:8000. No client-chosen identity. Backend serves built web/dist at `/` when present.

User: `{id,email,name}`. Workspace: `{id,name,role}`. Auth response: `{user,workspaces}`.
- `POST /api/auth/register` JSON `{email,password,name,workspace_name}` creates user + owned workspace and session. Password minimum 10 characters. `POST /api/auth/login` `{email,password}`. `GET /api/auth/me`; `POST /api/auth/logout`.
- `GET /api/workspaces` -> `{items:Workspace[]}`; `POST /api/workspaces` `{name}` -> Workspace. `POST /api/workspaces/{id}/members` `{email}` owner only, adds existing user for local permission tests; `GET /api/workspaces/{id}/members` -> `{items:[{id,email,name,role}]}`.
- `GET /api/workspaces/{id}/documents` -> `{items:Document[]}`.
- `POST /api/workspaces/{id}/documents` multipart `file`, optional `title`, `visibility` (`workspace` or `private`, default workspace) -> DocumentDetail. Parse failure recorded with `status:failed` and safe error, HTTP 201. UTF-8 .md/.txt and text PDFs only. Max 5MiB, bounded extracted content.
- `GET /api/documents/{id}` -> DocumentDetail.
- `PUT /api/documents/{id}` JSON `{title,content,visibility}` owner only -> DocumentDetail. Edit extracted plain text; revision increments; old chunks replaced atomically.
- `POST /api/documents/{id}/reprocess` -> DocumentDetail. Reparse stored current source; no duplicate chunks.
- `DELETE /api/documents/{id}` -> 204 owner only.
- `GET /api/workspaces/{id}/search?q=...&limit=10&method=bm25` -> `{query,method,elapsed_ms,search_id,results:SearchHit[]}`. Methods: `bm25` (default), `dense`, `hybrid`, `hybrid_rerank`. Limit 1–50; query 1–500 Unicode codepoints and not blank. Reranked responses also include `candidate_policy:"balanced_depth_rrf50_v1"`. Results are retrieved passages, not generated answers; dense top-k does not establish answerability.
- `GET /api/search/capabilities` (authenticated) -> `{default_method:"bm25",model_enabled,status,methods,available_methods}`. Status: `disabled|ready|unavailable`; available methods are BM25 only unless the optional worker responds with validated readiness metadata. No worker address or credentials are exposed.
- `GET /api/workspaces/{id}/history` -> `{items:[{id,query,method,created_at,result_count}]}` own history only. Existing records without additive metadata read as BM25.
- `POST /api/searches/{id}/feedback` JSON `{document_id,relevant:boolean}` -> `{ok:true}`; validate search belongs to user, document was returned and is currently visible.
- `GET /api/health` -> `{status:"ok",version:"0.1.0"}`.

Document fields: `{id,workspace_id,title,filename,media_type,visibility,owner_id,status,error,revision,chunk_count,created_at,updated_at}`. DocumentDetail adds `{content,chunks:[{id,text,page,start_offset,end_offset,ordinal}]}`. `page` is 1-based for PDF, null otherwise; offsets are Python Unicode codepoint indices into normalized content. Source plaintext must match chunk text exactly; UI may use returned chunk text rather than JS slicing offsets.

SearchHit: `{document_id,title,filename,revision,chunk_id,text,page,start_offset,end_offset,score}`. Permissions restrict candidate chunks before corpus statistics, embedding and reranking. Scores are method-specific and are not confidence probabilities. Fetch current source before displaying and reconcile revisions. No generated Q&A response is implemented.

Learned search snapshots current visible chunks, releases its read transaction during HTTP model calls, then rechecks the original session, membership and full visible corpus in the same write transaction as history. Changes during inference return `409 search_context_changed` without results/history. Session expiry/logout returns 401. Model corpus is capped at 4,096 visible chunks; exceeding it returns `422 visible_corpus_too_large`. Model-token overflow returns `422 query_too_long`.

Optional inference errors: `503 inference_disabled|inference_unavailable|inference_invalid_response|inference_busy`, `504 inference_timeout`. These never trigger a silent BM25/CPU fallback. Clients may explicitly choose BM25 in a new request. Model error responses do not expose raw upstream payloads. See [model boundary ADR](decisions/0004-model-serving.md) and [local operations](MODEL-SERVING.md).

UI target: DocTrail, Korean light neutral sidebar/library/search/evidence viewer, account onboarding, uploads/processing feedback, document list/detail, title/content edit, private/workspace toggle, deletion, failure/retry, history and feedback. Empty states explain actual actions. Do not seed fabricated docs or quality numbers automatically.

## Additive embedding profile contract (M4 operations)

- `GET /api/search/capabilities` includes configured `embedding_profile:{id,model,revision}` separately from readiness. Allowlisted server profiles: `base` (default), `m4-terminal-v1` (explicit experiment). Clients cannot select the worker model.
- Successful learned search and its history row include the verified profile at search time. BM25 has absent/null metadata. Legacy learned history without metadata remains null, never inferred from the current server setting.
- Learned search accepts optional `expected_embedding_profile` as an identity guard. After session/membership checks, a mismatch returns `409 embedding_profile_changed`, before model execution and history insertion. The UI sends this guard and asks for a new explicit search when historical and current profiles differ or history metadata is unknown.
- Java validates allowlisted model/revision at health and every embedding response. Terminal revision is the frozen checkpoint manifest SHA-256; base revision remains the pinned upstream commit. See [operational design](M4-OPERATIONS-DESIGN.md) for identities, rollback and provenance.
