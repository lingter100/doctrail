# Milestone 1 API contract

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
- `GET /api/workspaces/{id}/search?q=...&limit=10` -> `{query,method:"bm25",elapsed_ms,search_id,results:SearchHit[]}`; empty no-match list is honest, not a generated answer.
- `GET /api/workspaces/{id}/history` -> `{items:[{id,query,created_at,result_count}]}` own history only.
- `POST /api/searches/{id}/feedback` JSON `{document_id,relevant:boolean}` -> `{ok:true}`; validate search belongs to user, document was returned and is currently visible.
- `GET /api/health` -> `{status:"ok",version:"0.1.0"}`.

Document fields: `{id,workspace_id,title,filename,media_type,visibility,owner_id,status,error,revision,chunk_count,created_at,updated_at}`. DocumentDetail adds `{content,chunks:[{id,text,page,start_offset,end_offset,ordinal}]}`. `page` is 1-based for PDF, null otherwise; offsets are Python Unicode codepoint indices into normalized content. Source plaintext must match chunk text exactly; UI may use returned chunk text rather than JS slicing offsets.

SearchHit: `{document_id,title,filename,revision,chunk_id,text,page,start_offset,end_offset,score}`. Results rank chunks; permissions restrict candidate chunks before computing BM25 corpus statistics. Plain text evidence may be shown verbatim. Fetch current source before displaying, reconcile revision when document changed. This is keyword retrieval only; no Q&A response or invented citations.

UI target: DocTrail, Korean light neutral sidebar/library/search/evidence viewer, account onboarding, uploads/processing feedback, document list/detail, title/content edit, private/workspace toggle, deletion, failure/retry, history and feedback. Empty states explain actual actions. Do not seed fabricated docs or quality numbers automatically.
