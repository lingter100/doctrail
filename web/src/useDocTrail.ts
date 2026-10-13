import { useEffect, useRef, useState } from 'react';
import { api, ApiError, errorMessage } from './api';
import { profileLabel } from './searchMethods';
import type { Auth, AuthMode, Capabilities, Detail, Doc, History, Hit, Modal, Search, SearchMethod, View, Workspace } from './types';

type State = {
  booting: boolean; auth: Auth | null; authMode: AuthMode; authBusy: boolean; authError: string;
  workspaceId: string; documents: Doc[]; history: History[]; view: View; search: Search | null;
  selected: Detail | null; selectedHit: Hit | null; selectedIndex: number; query: string; filter: string;
  loading: boolean; workspaceLoading: boolean; pageError: string; modal: Modal | null; modalBusy: boolean; modalError: string;
  feedback: Record<string, 'busy' | 'saved'>; retryBusy: boolean; logoutBusy: boolean;
  toast: { id: number; message: string } | null;
  searchMethod: SearchMethod; capabilities: Capabilities | null; capabilitiesBusy: boolean;
  historyNotice: string;
};
const emptyWorkspace = {
  documents: [] as Doc[], history: [] as History[], view: 'library' as View, search: null,
  selected: null, selectedHit: null, selectedIndex: 0, query: '', filter: '', loading: false, workspaceLoading: false,
  pageError: '', modal: null, modalBusy: false, modalError: '', feedback: {}, retryBusy: false,
  historyNotice: '',
};
const initial: State = { ...emptyWorkspace, booting: true, auth: null, authMode: 'register', authBusy: false, authError: '', workspaceId: '', logoutBusy: false, toast: null, searchMethod: 'bm25', capabilities: null, capabilitiesBusy: false };

export function useDocTrail() {
  const [state, setState] = useState<State>(initial);
  const live = useRef(state);
  const tokens = useRef({ epoch: 0, auth: 0, load: 0, search: 0, detail: 0, modal: 0, toast: 0, capabilities: 0 });
  const documentVersions = useRef(new Map<string, number>());
  const deletedDocuments = useRef(new Set<string>());
  function update(patch: Partial<State> | ((current: State) => Partial<State>)) {
    live.current = { ...live.current, ...(typeof patch === 'function' ? patch(live.current) : patch) };
    setState(live.current);
  }
  function toast(message: string) { update({ toast: { id: ++tokens.current.toast, message } }); }
  function invalidateReads() { tokens.current.load++; tokens.current.search++; tokens.current.detail++; }
  function resetWorkspace() {
    tokens.current.epoch++; tokens.current.modal++; invalidateReads();
    documentVersions.current.clear(); deletedDocuments.current.clear();
    update(emptyWorkspace);
  }
  function sessionExpired(error: unknown) {
    if (!(error instanceof ApiError && error.status === 401) || !live.current.auth) return false;
    resetWorkspace(); tokens.current.auth++;
    update({ auth: null, workspaceId: '', authMode: 'login', authBusy: false, logoutBusy: false });
    toast('로그인이 만료되었어요. 다시 로그인해 주세요.');
    return true;
  }
  function replaceDoc(detail: Detail) {
    // Mutations may finish on the server before their HTTP responses arrive.
    // A dismissed v2 edit must not overwrite accepted v3 or revive a deletion.
    const listedRevision = live.current.documents.find(doc => doc.id === detail.id)?.revision || 0;
    if (deletedDocuments.current.has(detail.id) || detail.revision < Math.max(documentVersions.current.get(detail.id) || 0, listedRevision)) return false;
    documentVersions.current.set(detail.id, detail.revision);
    update(current => ({ documents: current.documents.some(doc => doc.id === detail.id)
      ? current.documents.map(doc => doc.id === detail.id ? detail : doc) : [detail, ...current.documents] }));
    return true;
  }
  async function loadWorkspace() {
    const id = live.current.workspaceId;
    const epoch = tokens.current.epoch, request = ++tokens.current.load;
    const valid = () => epoch === tokens.current.epoch && request === tokens.current.load;
    update(current => ({ workspaceLoading: true, loading: current.view === 'search' ? current.loading : true, pageError: '' }));
    if (!id) { update({ loading: false, workspaceLoading: false }); return; }
    try {
      const [docs, past] = await Promise.all([
        api<{ items: Doc[] }>(`/workspaces/${id}/documents`), api<{ items: History[] }>(`/workspaces/${id}/history`),
      ]);
      if (valid()) update(current => ({ documents: docs.items, history: [...current.history, ...past.items.filter(item => !current.history.some(existing => existing.id === item.id))].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 50) }));
    } catch (error) {
      if (valid() && !sessionExpired(error)) { if (live.current.view === 'search') toast(errorMessage(error)); else update({ pageError: errorMessage(error) }); }
    } finally { if (valid()) update(current => ({ workspaceLoading: false, loading: current.view === 'search' ? current.loading : false })); }
  }
  async function loadCapabilities() {
    const session = tokens.current.auth, request = ++tokens.current.capabilities;
    const valid = () => session === tokens.current.auth && request === tokens.current.capabilities;
    update({ capabilitiesBusy: true });
    try {
      const capabilities = await api<Capabilities>('/search/capabilities');
      if (valid()) update({ capabilities });
    } catch (error) {
      if (valid() && !sessionExpired(error)) update({ capabilities: null });
    } finally { if (valid()) update({ capabilitiesBusy: false }); }
  }
  function setSearchMethod(searchMethod: SearchMethod) {
    tokens.current.search++; tokens.current.detail++;
    update({ searchMethod, search: null, selected: null, selectedHit: null, feedback: {}, pageError: '', historyNotice: '', loading: live.current.view === 'search' ? false : live.current.loading });
  }
  function acceptAuth(auth: Auth) {
    resetWorkspace();
    update({ auth, workspaceId: auth.workspaces[0]?.id || '', authBusy: false, authError: '', booting: false, searchMethod: 'bm25', capabilities: null });
    void loadWorkspace(); void loadCapabilities();
  }
  useEffect(() => {
    const abort = new AbortController();
    const request = ++tokens.current.auth;
    void api<Auth>('/auth/me', { signal: abort.signal }).then(auth => {
      if (!abort.signal.aborted && request === tokens.current.auth) acceptAuth(auth);
    }).catch(error => {
      if (abort.signal.aborted || request !== tokens.current.auth) return;
      update({ booting: false });
      if (!(error instanceof ApiError && error.status === 401)) toast(errorMessage(error));
    });
    // StrictMode can dispose the first boot while the second boot is in flight.
    return () => { abort.abort(); tokens.current.auth++; tokens.current.epoch++; invalidateReads(); tokens.current.modal++; };
  }, []);
  useEffect(() => {
    if (!state.toast) return;
    const id = state.toast.id;
    const timer = setTimeout(() => { if (live.current.toast?.id === id) update({ toast: null }); }, 4500);
    return () => clearTimeout(timer);
  }, [state.toast]);

  function setAuthMode(authMode: AuthMode) {
    if (live.current.authBusy) return;
    tokens.current.auth++; update({ authMode, authError: '' });
  }
  async function authenticate(data: FormData) {
    if (live.current.authBusy) return;
    const mode = live.current.authMode, request = ++tokens.current.auth;
    update({ authBusy: true, authError: '' });
    try {
      const auth = await api<Auth>(`/auth/${mode}`, { method: 'POST', body: JSON.stringify(Object.fromEntries(data)) });
      if (request === tokens.current.auth) acceptAuth(auth);
    } catch (error) {
      if (request === tokens.current.auth) update({ authBusy: false, authError: errorMessage(error) });
    }
  }
  function switchWorkspace(workspaceId: string) {
    if (!live.current.auth?.workspaces.some(workspace => workspace.id === workspaceId)) return;
    resetWorkspace(); update({ workspaceId }); void loadWorkspace();
  }
  function changeView(view: View) {
    // A search that finishes after navigating away must not reclaim the view.
    tokens.current.search++; update({ view, pageError: '', historyNotice: '', loading: view === 'search' ? false : live.current.workspaceLoading });
  }
  async function logout() {
    if (live.current.logoutBusy) return;
    const session = tokens.current.auth;
    update({ logoutBusy: true });
    try {
      await api('/auth/logout', { method: 'POST' });
      if (session !== tokens.current.auth) return;
      tokens.current.auth++; resetWorkspace();
      update({ auth: null, workspaceId: '', authMode: 'login', authError: '', logoutBusy: false });
    } catch (error) {
      if (session === tokens.current.auth && !sessionExpired(error)) { update({ logoutBusy: false }); toast(errorMessage(error)); }
    }
  }
  function rerunHistory(item: History) {
    const method = item.method || 'bm25';
    const previous = item.embedding_profile, current = live.current.capabilities?.embedding_profile;
    if (method !== 'bm25' && (!previous || !current || previous.id !== current.id || previous.model !== current.model || previous.revision !== current.revision)) {
      tokens.current.search++; tokens.current.detail++;
      update({ view: 'search', query: item.query, searchMethod: method, search: null, selected: null, selectedHit: null, loading: false, pageError: '', feedback: {},
        historyNotice: `${previous ? `이 기록은 ${profileLabel(previous)}로 검색했어요. 현재 모델과 달라요.` : '이 기록에는 사용한 모델 정보가 없어 같은 모델인지 확인할 수 없어요.'} 위 검색창에서 검색을 누르면 현재 연결된 모델로 새로 검색해요.` });
      return;
    }
    void runSearch(item.query, method, previous?.id);
  }
  async function runSearch(rawQuery: string, method = live.current.searchMethod, expectedProfile = live.current.capabilities?.embedding_profile?.id) {
    const query = rawQuery.trim(), id = live.current.workspaceId;
    if (!query || !id) return;
    const epoch = tokens.current.epoch, request = ++tokens.current.search;
    tokens.current.detail++;
    const valid = () => epoch === tokens.current.epoch && request === tokens.current.search;
    update({ view: 'search', query, searchMethod: method, selected: null, selectedHit: null, search: null, loading: true, pageError: '', historyNotice: '', feedback: {}, retryBusy: false });
    try {
      const guard = method !== 'bm25' && expectedProfile ? `&expected_embedding_profile=${encodeURIComponent(expectedProfile)}` : '';
      const result = await api<Search>(`/workspaces/${id}/search?q=${encodeURIComponent(query)}&limit=10&method=${encodeURIComponent(method)}${guard}`);
      if (valid()) update(current => ({ search: result, history: [{ id: result.search_id, query, method: result.method, embedding_profile: result.embedding_profile, created_at: new Date().toISOString(), result_count: result.results.length }, ...current.history.filter(item => item.id !== result.search_id)].slice(0, 50) }));
    } catch (error) {
      if (valid() && !sessionExpired(error)) {
        if (error instanceof ApiError && error.code === 'embedding_profile_changed') {
          update({ historyNotice: '연결된 모델이 변경되어 검색을 멈췄어요. 모델 표시를 확인한 뒤 위 검색창에서 새로 검색해 주세요.' });
          void loadCapabilities();
        } else update({ pageError: errorMessage(error) });
      }
    } finally { if (valid()) update({ loading: false }); }
  }
  async function openDocument(id: string, hit?: Hit, selectedIndex = 0) {
    const epoch = tokens.current.epoch, request = ++tokens.current.detail;
    const valid = () => epoch === tokens.current.epoch && request === tokens.current.detail;
    try {
      const detail = await api<Detail>(`/documents/${id}`);
      if (!valid()) return;
      if (replaceDoc(detail)) update({ selected: detail, selectedHit: hit || null, selectedIndex, retryBusy: false });
    } catch (error) {
      if (!valid() || sessionExpired(error)) return;
      update({ selected: null, selectedHit: null });
      if (error instanceof ApiError && [403, 404].includes(error.status)) {
        // Invalidate an older list as well, so it cannot resurrect a revoked row.
        tokens.current.load++;
        update(current => ({ loading: false, workspaceLoading: false, documents: current.documents.filter(doc => doc.id !== id), search: current.search && { ...current.search, results: current.search.results.filter(hit => hit.document_id !== id) } }));
      }
      toast(errorMessage(error));
    }
  }
  function closeSource() { tokens.current.detail++; update({ selected: null, selectedHit: null, retryBusy: false }); }
  async function feedback(index: number, relevant: boolean) {
    const search = live.current.search, epoch = tokens.current.epoch;
    if (!search) return;
    const hit = search.results[index];
    if (!hit || live.current.feedback[hit.chunk_id]) return;
    const key = hit.chunk_id;
    const valid = () => epoch === tokens.current.epoch && live.current.search?.search_id === search.search_id;
    update(current => ({ feedback: { ...current.feedback, [key]: 'busy' } }));
    try {
      await api(`/searches/${search.search_id}/feedback`, { method: 'POST', body: JSON.stringify({ document_id: hit.document_id, relevant }) });
      if (valid()) update(current => ({ feedback: { ...current.feedback, [key]: 'saved' } }));
    } catch (error) {
      if (!valid() || sessionExpired(error)) return;
      update(current => { const next = { ...current.feedback }; delete next[key]; return { feedback: next }; });
      toast(errorMessage(error));
    }
  }
  function openModal(kind: Modal['kind']) {
    if (!live.current.auth) return;
    const id = ++tokens.current.modal;
    if (kind === 'edit' || kind === 'delete') {
      const doc = live.current.selected;
      if (!doc || doc.owner_id !== live.current.auth.user.id) return;
      update({ modal: { id, kind, doc }, modalError: '', modalBusy: false });
    } else {
      if (kind !== 'workspace' && !live.current.workspaceId) return;
      update({ modal: { id, kind }, modalError: '', modalBusy: false });
    }
  }
  function closeModal() { tokens.current.modal++; update({ modal: null, modalBusy: false, modalError: '' }); }
  async function submitModal(data: FormData) {
    const modal = live.current.modal, workspaceId = live.current.workspaceId;
    if (!modal || live.current.modalBusy) return;
    const epoch = tokens.current.epoch;
    const sameContext = () => epoch === tokens.current.epoch;
    const valid = () => sameContext() && tokens.current.modal === modal.id;
    if (modal.kind === 'upload') {
      const file = data.get('file');
      if (!(file instanceof File) || !file.name) return;
      if (file.size > 5 * 1024 * 1024) { update({ modalError: '5MB 이하의 파일을 선택해 주세요.' }); return; }
    }
    update({ modalBusy: true, modalError: '' });
    try {
      if (modal.kind === 'workspace') {
        const result = await api<Workspace>('/workspaces', { method: 'POST', body: JSON.stringify(Object.fromEntries(data)) });
        if (!sameContext()) return;
        update(current => ({ auth: current.auth && { ...current.auth, workspaces: [...current.auth.workspaces, result] } }));
        if (valid()) { resetWorkspace(); update({ workspaceId: result.id }); void loadWorkspace(); toast('새 워크스페이스를 만들었어요.'); }
      } else if (modal.kind === 'member') {
        await api(`/workspaces/${workspaceId}/members`, { method: 'POST', body: JSON.stringify(Object.fromEntries(data)) });
        if (valid()) { closeModal(); toast('워크스페이스에 멤버를 추가했어요.'); }
      } else if (modal.kind === 'delete') {
        await api(`/documents/${modal.doc.id}`, { method: 'DELETE' });
        if (!sameContext()) return;
        const reloadList = live.current.workspaceLoading;
        deletedDocuments.current.add(modal.doc.id);
        invalidateReads();
        update(current => ({ documents: current.documents.filter(doc => doc.id !== modal.doc.id),
          ...(current.selected?.id === modal.doc.id ? { selected: null, selectedHit: null, retryBusy: false } : {}),
          search: current.search && { ...current.search, results: current.search.results.filter(hit => hit.document_id !== modal.doc.id) }, loading: false, workspaceLoading: false }));
        if (valid()) { update({ selected: null, selectedHit: null, search: null, view: 'library' }); closeModal(); toast('문서를 삭제했어요. 더 이상 검색되지 않아요.'); }
        if (reloadList) void loadWorkspace();
      } else {
        const detail = modal.kind === 'upload'
          ? await api<Detail>(`/workspaces/${workspaceId}/documents`, { method: 'POST', body: data })
          : await api<Detail>(`/documents/${modal.doc.id}`, { method: 'PUT', body: JSON.stringify(Object.fromEntries(data)) });
        if (!sameContext()) return;
        if (!replaceDoc(detail)) { if (valid()) closeModal(); return; }
        const reloadList = live.current.workspaceLoading;
        invalidateReads();
        update(current => ({ loading: false, workspaceLoading: false, ...(current.selected?.id === detail.id ? { selected: detail, retryBusy: false } : {}) }));
        if (valid()) {
          update({ selected: detail, selectedHit: null, search: null, view: 'library', loading: false, retryBusy: false });
          closeModal();
          toast(modal.kind === 'edit' ? `버전 ${detail.revision}으로 저장했어요. 검색에도 반영됐어요.` : detail.status === 'ready' ? '문서를 추가했어요. 이제 키워드로 검색해 보세요.' : '파일을 저장했지만 텍스트 추출에 실패했어요. 원문 패널을 확인해 주세요.');
        }
        // The invalidated initial list may contain other existing documents.
        if (reloadList) void loadWorkspace();
      }
    } catch (error) {
      if (valid() && !sessionExpired(error)) update({ modalBusy: false, modalError: errorMessage(error) });
    }
  }
  async function reprocess() {
    const doc = live.current.selected, epoch = tokens.current.epoch, request = tokens.current.detail;
    if (!doc || live.current.retryBusy || doc.owner_id !== live.current.auth?.user.id) return;
    const sameContext = () => epoch === tokens.current.epoch;
    const valid = () => sameContext() && request === tokens.current.detail && live.current.selected?.id === doc.id;
    update({ retryBusy: true });
    try {
      const detail = await api<Detail>(`/documents/${doc.id}/reprocess`, { method: 'POST' });
      if (!sameContext()) return;
      if (!replaceDoc(detail)) { if (valid()) update({ retryBusy: false }); return; }
      const stillSelected = valid(), reloadList = live.current.workspaceLoading;
      tokens.current.load++; tokens.current.search++;
      update({ loading: false, workspaceLoading: false });
      if (stillSelected) {
        tokens.current.detail++;
        update({ selected: detail, retryBusy: false });
        toast(detail.status === 'ready' ? '문서 처리가 완료됐어요.' : '아직 텍스트를 추출하지 못했어요. 파일을 확인해 주세요.');
      }
      if (reloadList) void loadWorkspace();
    } catch (error) {
      if (valid() && !sessionExpired(error)) { update({ retryBusy: false }); toast(errorMessage(error)); }
    }
  }
  return { state, workspace: state.auth?.workspaces.find(workspace => workspace.id === state.workspaceId),
    setQuery: (query: string) => update({ query }), setFilter: (filter: string) => update({ filter }),
    setAuthMode, authenticate, switchWorkspace, changeView, logout, loadWorkspace, runSearch, rerunHistory, loadCapabilities, setSearchMethod,
    openDocument, closeSource, feedback, openModal, closeModal, submitModal, reprocess };
}
export type DocTrail = ReturnType<typeof useDocTrail>;
