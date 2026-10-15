import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
import type { DocTrail } from './useDocTrail';
import { meetingError, type Analysis, type DecisionLink, type MeetingDetail, type TaskItem } from './meetings';

// This controller is mounted with a session/workspace/view key. Every request and
// poll also owns a token: responses from disposed pages cannot reclaim the UI.
export function useMeetings(app: DocTrail, mode: 'meetings' | 'actions') {
  const workspaceId = app.state.workspaceId;
  const [meetings, setMeetings] = useState<MeetingDetail[]>([]);
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [detail, setDetail] = useState<MeetingDetail | null>(null);
  const [links, setLinks] = useState<DecisionLink[]>([]);
  const [targets, setTargets] = useState<MeetingDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [editing, setEditing] = useState(false);
  const editingRef = useRef(false);
  const [recovery, setRecovery] = useState<{ detail: MeetingDetail; links: DecisionLink[] } | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [reviewRequired, setReviewRequired] = useState(false);
  const mounted = useRef(false);
  const serials = useRef(new Map<string, number>());
  const aborts = useRef(new Map<string, AbortController>());
  const selected = useRef<string | null>(null);
  const mutationBusy = useRef(false);
  function request(key: string) {
    aborts.current.get(key)?.abort();
    const abort = new AbortController(); aborts.current.set(key, abort);
    const token = (serials.current.get(key) || 0) + 1; serials.current.set(key, token);
    return { signal: abort.signal, valid: () => mounted.current && !abort.signal.aborted && serials.current.get(key) === token };
  }
  function fail(failure: unknown, valid: () => boolean) { if (valid() && !app.sessionExpired(failure)) setError(meetingError(failure)); }
  async function load(silent = false) {
    const owner = request('list');
    if (!silent) { setLoading(true); setError(''); }
    try {
      const result = await api<{ items: MeetingDetail[] }>(`/workspaces/${workspaceId}/meetings`, { signal: owner.signal });
      if (owner.valid()) setMeetings(result.items);
      if (mode === 'actions') {
        const result = await api<{ items: TaskItem[] }>(`/tasks?workspace_id=${encodeURIComponent(workspaceId)}`, { signal: owner.signal });
        if (owner.valid()) setTasks(result.items);
      }
    } catch (failure) { fail(failure, owner.valid); }
    finally { if (owner.valid()) setLoading(false); }
  }
  async function open(id: string, silent = false) {
    if (silent && editingRef.current) return;
    const owner = request('detail'); selected.current = id;
    if (!silent) { setEditing(false); editingRef.current = false; setRecovery(null); setReviewRequired(false); setRefreshing(false); setError(''); setDetail(null); setLinks([]); setNotice(''); app.closeSource(); }
    try {
      const result = await api<MeetingDetail>(`/meetings/${id}`, { signal: owner.signal });
      if (!owner.valid() || selected.current !== id) return;
      setDetail(result);
      const resultLinks = await api<{ items: DecisionLink[] }>(`/meetings/${id}/links`, { signal: owner.signal });
      if (owner.valid() && selected.current === id) setLinks(resultLinks.items);
    } catch (failure) { fail(failure, owner.valid); }
  }
  function edit(value: boolean) {
    request('detail'); editingRef.current = value; setEditing(value);
    setRecovery(null); setReviewRequired(false); setRefreshing(false); setError('');
  }
  async function refresh() {
    if (!detail || mutationBusy.current) return;
    const id = detail.document.id;
    const owner = request('detail'); setRefreshing(true); setRecovery(null); setError('');
    if (editingRef.current) setReviewRequired(true);
    try {
      const [latest, latestLinks] = await Promise.all([
        api<MeetingDetail>(`/meetings/${id}`, { signal: owner.signal }),
        api<{ items: DecisionLink[] }>(`/meetings/${id}/links`, { signal: owner.signal }),
      ]);
      if (!owner.valid() || selected.current !== id) return;
      if (editingRef.current) setRecovery({ detail: latest, links: latestLinks.items });
      else { setDetail(latest); setLinks(latestLinks.items); }
    } catch (failure) { fail(failure, owner.valid); }
    finally { if (owner.valid()) setRefreshing(false); }
  }
  function keepLocal() {
    if (!recovery || !detail || refreshing || recovery.detail.document.revision !== detail.document.revision
      || recovery.detail.meeting.source_revision !== detail.meeting.source_revision
      || recovery.detail.meeting.analysis_status !== 'ready') return null;
    const latest = recovery.detail;
    setDetail(latest); setLinks(recovery.links);
    setRecovery(null); setReviewRequired(false); setError('');
    setNotice('내 초안을 유지했어요. 서버의 변경 내용을 덮어쓸 수 있으니 확인한 뒤 저장 버튼을 눌러 주세요.');
    return latest;
  }
  function useServer() {
    if (!recovery || refreshing) return;
    setDetail(recovery.detail); setLinks(recovery.links); edit(false);
    setNotice('로컬 초안을 버리고 확인한 서버 버전을 열었어요.');
  }
  function back() { edit(false); selected.current = null; setDetail(null); setLinks([]); setError(''); setNotice(''); app.closeSource(); void load(); }
  async function mutate<T>(action: (signal: AbortSignal) => Promise<T>, done: (result: T) => void, rejected?: (failure: unknown) => void) {
    if (mutationBusy.current) return false;
    const owner = request('mutation'); mutationBusy.current = true; setBusy(true); setError(''); setNotice('');
    try {
      const result = await action(owner.signal);
      if (!owner.valid()) return false;
      done(result); void load(true); return true;
    } catch (failure) { if (owner.valid()) rejected?.(failure); fail(failure, owner.valid); return false; }
    finally { if (owner.valid()) { mutationBusy.current = false; setBusy(false); } }
  }
  async function create(data: FormData, file: boolean) {
    if (file) {
      const input = data.get('file');
      if (!(input instanceof File) || !input.name) return false;
      if (input.size > 5 * 1024 * 1024) { setError('5MB 이하의 파일을 선택해 주세요.'); return false; }
    }
    return mutate(signal => api<MeetingDetail>(`/workspaces/${workspaceId}/meetings${file ? '' : '/text'}`, {
      method: 'POST', signal, body: file ? data : JSON.stringify(Object.fromEntries(data)),
    }), result => { request('detail'); selected.current = result.document.id; setDetail(result); setLinks([]); setNotice('회의 원문을 등록했어요. AI 분석 상태를 확인해 주세요.'); });
  }
  async function analyze() {
    if (!detail) return;
    const id = detail.document.id;
    return mutate(signal => api<MeetingDetail>(`/meetings/${id}/analyze`, { method: 'POST', signal, body: JSON.stringify({ expected_revision: detail.document.revision }) }), result => {
      if (selected.current === id) { request('detail'); setDetail(result); setNotice('분석을 요청했어요. 완료되면 상태가 갱신됩니다.'); }
    });
  }
  async function save(analysis: Analysis, basis = detail) {
    if (!detail || !basis || (editingRef.current && (reviewRequired || refreshing))) return false;
    const id = detail.document.id;
    if (basis.document.id !== id || basis.document.revision !== detail.document.revision) return false;
    return mutate(signal => api<MeetingDetail>(`/meetings/${id}/analysis`, { method: 'PUT', signal, body: JSON.stringify({ expected_revision: basis.document.revision, expected_version: basis.meeting.version, analysis }) }), result => {
      if (selected.current === id) { edit(false); setDetail(result); setLinks([]); setNotice('사용자 수정본을 저장했어요. AI 초안과 원문은 보존돼요.'); void open(id, true); }
    }, failure => { if (failure instanceof ApiError && failure.status === 409 && editingRef.current) setReviewRequired(true); });
  }
  async function loadTargets() {
    const owner = request('targets'); setError('');
    try {
      const results = await Promise.all((app.state.auth?.workspaces || []).map(workspace => api<{ items: MeetingDetail[] }>(`/workspaces/${workspace.id}/meetings`, { signal: owner.signal })));
      if (owner.valid()) setTargets(results.flatMap(result => result.items).filter(item => item.document.id !== selected.current && item.meeting.analysis_status === 'ready'));
    } catch (failure) { fail(failure, owner.valid); }
  }
  async function addLink(target: MeetingDetail, data: { source_item_id: string; target_item_id: string; relation: 'related' | 'supersedes'; quote: string; start_offset: number; end_offset: number }) {
    if (!detail) return false;
    const id = detail.document.id;
    return mutate(signal => api(`/meetings/${id}/links`, { method: 'POST', signal, body: JSON.stringify({ ...data, target_meeting_id: target.document.id, expected_revision: detail.document.revision, expected_version: detail.meeting.version, target_expected_revision: target.document.revision, target_expected_version: target.meeting.version }) }), () => { if (selected.current === id) { setNotice('사용자 확인 관계를 저장했어요.'); void open(id, true); } });
  }
  async function removeLink(id: string) {
    if (!detail) return;
    const meetingId = detail.document.id;
    return mutate(signal => api(`/meetings/${meetingId}/links/${id}`, { method: 'DELETE', signal }), () => { if (selected.current === meetingId) { setLinks(current => current.filter(link => link.id !== id)); setNotice('결정 연결을 해제했어요.'); } });
  }
  useEffect(() => {
    mounted.current = true; void load();
    return () => { mounted.current = false; for (const abort of aborts.current.values()) abort.abort(); };
  }, []);
  useEffect(() => {
    const pending = (value: MeetingDetail) => ['queued', 'running'].includes(value.meeting.analysis_status);
    if (!(detail && pending(detail)) && !meetings.some(pending)) return;
    const timer = setTimeout(() => { if (!mutationBusy.current) { void load(true); if (selected.current) void open(selected.current, true); } }, 2500);
    return () => clearTimeout(timer);
  }, [meetings, detail, busy]);
  return { meetings, tasks, detail, links, targets, loading, busy, error, notice, editing, recovery, refreshing, reviewRequired, edit, refresh, keepLocal, useServer, load, open, back, create, analyze, save, loadTargets, addLink, removeLink, clearError: () => setError('') };
}
export type MeetingsController = ReturnType<typeof useMeetings>;
