export type User = { id: string; email: string; name: string };
export type Workspace = { id: string; name: string; role: string };
export type Doc = { id: string; workspace_id: string; title: string; filename: string; media_type: string; visibility: 'workspace' | 'private'; owner_id: string; status: string; error: string | null; revision: number; chunk_count: number; created_at: string; updated_at: string; document_kind?: 'meeting' | 'document' };
export type Chunk = { id: string; text: string; page: number | null; start_offset: number; end_offset: number; ordinal: number };
export type Detail = Doc & { content: string; chunks: Chunk[] };
export type Hit = { document_id: string; title: string; filename: string; revision: number; chunk_id: string; text: string; page: number | null; score: number };
export type SearchMethod = 'bm25' | 'dense' | 'hybrid' | 'hybrid_rerank';
export type EmbeddingProfile = { id: string; model: string; revision: string };
export type Capabilities = { default_method: SearchMethod; model_enabled: boolean; status: 'disabled' | 'ready' | 'unavailable'; methods: SearchMethod[]; available_methods: SearchMethod[]; embedding_profile?: EmbeddingProfile };
export type Search = { query: string; method: SearchMethod; elapsed_ms: number; search_id: string; results: Hit[]; embedding_profile?: EmbeddingProfile | null };
export type History = { id: string; query: string; created_at: string; result_count: number; method?: SearchMethod; embedding_profile?: EmbeddingProfile | null };
export type Auth = { user: User; workspaces: Workspace[] };
export type View = 'library' | 'search' | 'history' | 'meetings' | 'actions' | 'knowledge';
export type AuthMode = 'login' | 'register';
export type Modal = { id: number; kind: 'upload' } | { id: number; kind: 'workspace' } | { id: number; kind: 'member' } | { id: number; kind: 'edit'; doc: Detail } | { id: number; kind: 'delete'; doc: Detail };

export type KnowledgeHistory = {
  id: string; operation: 'search' | 'answer'; query: string; workspace_id: string | null;
  kind: 'all' | 'meeting' | 'document';
  filters: { meeting_id: string | null; date_from: string | null; date_to: string | null; participant: string | null; assignee: string | null; item_type: string | null; limit: number };
  method: SearchMethod; embedding_profile: EmbeddingProfile | null; generation_model: { model: string; revision: string } | null;
  status: 'searched' | 'answered' | 'abstained'; reason: string | null; model_called: boolean; created_at: string; result_count: number;
};
