import { useEffect, useRef, useState } from 'react';
import { api, ApiError, errorMessage } from './api';
import type { DocTrail, SourceOrigin } from './useDocTrail';
import { meetingError, summaryVersion, type Analysis, type DecisionLink, type MeetingDetail, type TaskItem } from './meetings';

// This controller is mounted with a session/workspace/view key. Every request and
// poll also owns a token: responses from disposed pages cannot reclaim the UI.
export function useMeetings(app: DocTrail, mode: 'meetings' | 'actions') {
  const workspaceId = app.state.workspaceId;
  const [meetings, setMeetings] = useState<MeetingDetail[]>([]);
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [detail, setDetail] = useState<MeetingDetail | null>(null);
  const [links, setLinks] = useState<DecisionLink[]>([]);
  const [linksKnown, setLinksKnown] = useState(false);
  const [targets, setTargets] = useState<MeetingDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [listState, setListState] = useState({
    meetings: { loaded: false, error: '' },
    tasks: { loaded: false, error: '' },
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [editing, setEditing] = useState(false);
  const editingRef = useRef(false);
  const [recovery, setRecovery] = useState<{ detail: MeetingDetail; links: DecisionLink[] } | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [reviewRequired, setReviewRequired] = useState(false);
  const [linkReviewRequired, setLinkReviewRequired] = useState(false);
  const [linkSelectionVersion, setLinkSelectionVersion] = useState(0);
  const [targetSelectionVersion, setTargetSelectionVersion] = useState(0);
  const mounted = useRef(false);
  const serials = useRef(new Map<string, number>());
  const aborts = useRef(new Map<string, AbortController>());
  const selected = useRef<string | null>(null);
  const mutationBusy = useRef(false);
  function request(key: string) {
    const contextValid = app.captureContext();
    aborts.current.get(key)?.abort();
    const abort = new AbortController(); aborts.current.set(key, abort);
    const token = (serials.current.get(key) || 0) + 1; serials.current.set(key, token);
    return { signal: abort.signal, valid: () => mounted.current && contextValid() && !abort.signal.aborted && serials.current.get(key) === token };
  }
  function fail(failure: unknown, valid: () => boolean) { if (valid() && !app.sessionExpired(failure)) setError(meetingError(failure)); }
  function accessDenied(failure: unknown) { return failure instanceof ApiError && (failure.status === 403 || failure.status === 404); }
  function invalidateSelection() {
    const pendingMutation = mutationBusy.current;
    request('mutation'); request('targets');
    mutationBusy.current = false; setBusy(false); setNotice('');
    edit(false); selected.current = null; setDetail(null); setLinks([]); setTargets([]); app.closeSource();
    if (pendingMutation) setError('접근 상태가 바뀌어 진행 중인 요청의 결과를 표시하지 않았어요. 서버에 반영됐을 수 있으니 목록을 다시 확인해 주세요.');
  }
  function denyCurrentMeeting() {
    // A cached list and an earlier in-flight list cannot certify access after
    // an explicit denial from the detail, links or source endpoint.
    request('list'); setLoading(false); setMeetings([]); setTasks([]);
    invalidateSelection();
    const state = { loaded: false, error: '회의 접근 상태가 바뀌어 이전 조회 결과를 숨겼어요. 목록을 다시 확인해 주세요.' };
    setListState({ meetings: state, tasks: state });
  }
  function sourceOrigin(documentId: string): SourceOrigin {
    const meetingId = selected.current;
    const isCurrent = () => mounted.current && meetingId !== null && selected.current === meetingId;
    return { query: '', retryLabel: '회의 다시 확인', isCurrent,
      retry: () => { if (isCurrent()) void refresh(); },
      onDenied: () => {
        if (!isCurrent()) return;
        if (documentId === meetingId) denyCurrentMeeting();
        else {
          // A linked meeting's source denial does not revoke the open meeting.
          // Retire cached links/targets and their pending reads, preserving drafts.
          request('detail'); request('targets'); request('list'); setLoading(false); setRefreshing(false); setLinks([]); setLinksKnown(false); setTargets([]);
          setRecovery(current => current && { ...current, links: [] });
          setMeetings(current => current.filter(item => item.document.id !== documentId));
          setTasks(current => current.filter(item => item.meeting_id !== documentId));
        }
        setError('원문 접근 상태가 바뀌어 이전 조회 결과를 숨겼어요. 다시 확인해 주세요.');
      },
    };
  }
  function detailFailure(failure: unknown, valid: () => boolean, id: string) {
    if (!valid() || selected.current !== id || app.sessionExpired(failure)) return;
    if (accessDenied(failure)) denyCurrentMeeting();
    setError(meetingError(failure));
  }
  async function load() {
    const owner = request('list');
    setLoading(true);
    try {
      try {
        const result = await api<{ items: MeetingDetail[] }>(`/workspaces/${workspaceId}/meetings`, { signal: owner.signal });
        if (!owner.valid()) return;
        setMeetings(result.items);
        setListState(current => ({ ...current, meetings: { loaded: true, error: '' } }));
      } catch (failure) {
        if (!owner.valid() || app.sessionExpired(failure)) return;
        const denied = accessDenied(failure);
        if (denied) { setMeetings([]); setTasks([]); invalidateSelection(); }
        setListState(current => ({ ...current,
          meetings: { loaded: denied ? false : current.meetings.loaded, error: errorMessage(failure) },
          tasks: denied ? { loaded: false, error: '회의 접근 상태가 바뀌어 기존 작업 목록도 표시하지 않아요.' } : current.tasks,
        }));
      }
      // Tasks have their own endpoint and can succeed even when the meeting
      // status lookup fails. Neither result can certify the other list.
      if (mode === 'actions' && owner.valid()) {
        try {
          const result = await api<{ items: TaskItem[] }>(`/tasks?workspace_id=${encodeURIComponent(workspaceId)}`, { signal: owner.signal });
          if (!owner.valid()) return;
          setTasks(result.items);
          setListState(current => ({ ...current, tasks: { loaded: true, error: '' } }));
        } catch (failure) {
          if (!owner.valid() || app.sessionExpired(failure)) return;
          const denied = accessDenied(failure);
          if (denied) { setTasks([]); invalidateSelection(); }
          setListState(current => ({ ...current, tasks: { loaded: denied ? false : current.tasks.loaded, error: errorMessage(failure) } }));
        }
      }
    }
    finally { if (owner.valid()) setLoading(false); }
  }
  async function open(id: string, silent = false) {
    if (app.state.logoutBusy || (silent && editingRef.current)) return;
    const owner = request('detail'); selected.current = id; setLinksKnown(false);
    if (!silent) { setEditing(false); editingRef.current = false; setRecovery(null); setReviewRequired(false); setLinkReviewRequired(false); setRefreshing(false); setError(''); setDetail(null); setLinks([]); setNotice(''); app.closeSource(); }
    try {
      const result = await api<MeetingDetail>(`/meetings/${id}`, { signal: owner.signal });
      if (!owner.valid() || selected.current !== id) return;
      setDetail(result);
      const resultLinks = await api<{ items: DecisionLink[] }>(`/meetings/${id}/links`, { signal: owner.signal });
      if (owner.valid() && selected.current === id) { setLinks(resultLinks.items); setLinksKnown(true); }
    } catch (failure) { detailFailure(failure, owner.valid, id); }
  }
  function edit(value: boolean) {
    request('detail'); editingRef.current = value; setEditing(value);
    setRecovery(null); setReviewRequired(false); setLinkReviewRequired(false); setRefreshing(false); setError('');
  }
  async function verifySource(basis: MeetingDetail) {
    if (mutationBusy.current || app.state.logoutBusy || reviewRequired || refreshing) return null;
    const id = basis.document.id, owner = request('picker');
    try {
      const latest = await api<MeetingDetail>(`/meetings/${id}`, { signal: owner.signal });
      if (!owner.valid() || selected.current !== id || !editingRef.current) return null;
      if (latest.document.revision !== basis.document.revision || latest.meeting.source_revision !== basis.meeting.source_revision || latest.meeting.version !== basis.meeting.version || latest.meeting.analysis_status !== 'ready' || latest.document.content !== basis.document.content) {
        setReviewRequired(true); setError('원문이나 분석이 바뀌었어요. 초안을 유지한 채 서버 버전을 확인해 주세요.'); return null;
      }
      return { content: latest.document.content, valid: () => owner.valid() && selected.current === id && editingRef.current };
    } catch (failure) { detailFailure(failure, owner.valid, id); return null; }
  }
  async function refresh() {
    if (!detail || mutationBusy.current || app.state.logoutBusy) return;
    const id = detail.document.id;
    const owner = request('detail'); setRefreshing(true); setRecovery(null); setError(''); setLinksKnown(false);
    if (editingRef.current) setReviewRequired(true);
    try {
      const [latest, latestLinks] = await Promise.all([
        api<MeetingDetail>(`/meetings/${id}`, { signal: owner.signal }),
        api<{ items: DecisionLink[] }>(`/meetings/${id}/links`, { signal: owner.signal }),
      ]);
      let latestTargets: MeetingDetail[] | null = null;
      if (linkReviewRequired) {
        try { latestTargets = await fetchTargets(owner.signal); }
        catch (failure) {
          if (!owner.valid() || selected.current !== id || app.sessionExpired(failure)) return;
          // Another workspace's target list is not the source meeting's ACL.
          // Keep the source and quote draft; denied targets must not remain usable.
          if (accessDenied(failure)) { request('targets'); setTargets([]); }
          setError(`연결 대상 목록을 확인하지 못했어요. 현재 회의와 입력한 근거는 유지했어요. ${meetingError(failure)}`);
          return;
        }
      }
      if (!owner.valid() || selected.current !== id) return;
      setLinksKnown(true);
      if (editingRef.current) setRecovery({ detail: latest, links: latestLinks.items });
      else { setDetail(latest); setLinks(latestLinks.items); }
      if (latestTargets) {
        request('targets'); setTargets(latestTargets); setLinkReviewRequired(false);
        setLinkSelectionVersion(value => value + 1);
        setNotice('양쪽 회의를 새로 확인했어요. 현재 결정과 연결할 결정을 다시 선택하고 근거를 검토한 뒤 저장해 주세요. 자동으로 연결하지 않아요.');
      }
    } catch (failure) { detailFailure(failure, owner.valid, id); }
    finally { if (owner.valid()) setRefreshing(false); }
  }
  function keepLocal() {
    if (!recovery || !detail || refreshing || recovery.detail.document.revision !== detail.document.revision
      || recovery.detail.meeting.source_revision !== detail.meeting.source_revision
      || recovery.detail.meeting.analysis_status !== 'ready' || summaryVersion(recovery.detail.meeting.analysis) !== summaryVersion(detail.meeting.analysis)) return null;
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
  function back() { app.requestLeave(() => { edit(false); selected.current = null; setDetail(null); setLinks([]); setLinksKnown(false); setError(''); setNotice(''); app.closeSource(); void load(); }); }
  async function mutate<T>(action: (signal: AbortSignal) => Promise<T>, done: (result: T) => void, rejected?: (failure: unknown) => void | Promise<void>) {
    if (mutationBusy.current || app.state.logoutBusy) return false;
    const owner = request('mutation'); mutationBusy.current = true; setBusy(true); setError(''); setNotice('');
    try {
      const result = await action(owner.signal);
      if (!owner.valid()) return false;
      done(result); void load(); return true;
    } catch (failure) { if (owner.valid()) await rejected?.(failure); fail(failure, owner.valid); return false; }
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
    }, failure => {
      if (accessDenied(failure)) { denyCurrentMeeting(); return; }
      // A lost response may hide a committed PUT. Require an explicit version read
      // before another CAS; never retry the mutation automatically.
      if (editingRef.current && (!(failure instanceof ApiError) || failure.status === 409 || failure.status >= 500)) setReviewRequired(true);
      if (!(failure instanceof ApiError) || failure.status >= 500) setNotice('저장 여부가 확인되지 않아요. 서버에 저장됐을 수 있으니 버전을 확인한 뒤 직접 다시 저장해 주세요.');
    });
  }
  async function fetchTargets(signal: AbortSignal) {
    const results = await Promise.all((app.state.auth?.workspaces || []).map(workspace => api<{ items: MeetingDetail[] }>(`/workspaces/${workspace.id}/meetings`, { signal })));
    return results.flatMap(result => result.items).filter(item => item.document.id !== selected.current && item.meeting.analysis_status === 'ready');
  }
  async function loadTargets() {
    if (app.state.logoutBusy) return;
    if (linkReviewRequired) { await refresh(); return; }
    const owner = request('targets'); setError('');
    try {
      const results = await fetchTargets(owner.signal);
      if (owner.valid()) setTargets(results);
    } catch (failure) { fail(failure, owner.valid); }
  }
  async function recheckLinkSource(id: string) {
    const owner = request('detail'); setRefreshing(true);
    try {
      // A denied POST is ambiguous. Check access only; keep the review gate
      // and the user's draft until they explicitly refresh both sides.
      await api<MeetingDetail>(`/meetings/${id}`, { signal: owner.signal });
    } catch (failure) { detailFailure(failure, owner.valid, id); }
    finally { if (owner.valid()) setRefreshing(false); }
  }
  async function addLink(target: MeetingDetail, data: { source_item_id: string; target_item_id: string; relation: 'related' | 'supersedes'; quote: string; start_offset: number; end_offset: number }) {
    if (!detail || linkReviewRequired || refreshing || detail.meeting.analysis_status !== 'ready' || detail.meeting.source_revision !== detail.document.revision) return false;
    const id = detail.document.id;
    return mutate(signal => api(`/meetings/${id}/links`, { method: 'POST', signal, body: JSON.stringify({ ...data, target_meeting_id: target.document.id, expected_revision: detail.document.revision, expected_version: detail.meeting.version, target_expected_revision: target.document.revision, target_expected_version: target.meeting.version }) }), () => { if (selected.current === id) { setNotice('사용자 확인 관계를 저장했어요.'); void open(id, true); } }, async failure => {
      if (failure instanceof ApiError && failure.status === 409) setLinkReviewRequired(true);
      if (accessDenied(failure)) {
        // Retire target data immediately, then check source access without
        // resubmitting or accepting replacement choices on the user's behalf.
        request('targets'); request('detail'); request('list');
        setTargets([]); setLinks([]); setRecovery(null); setLoading(false); setRefreshing(false);
        setMeetings(current => current.filter(item => item.document.id !== target.document.id));
        setTasks(current => current.filter(item => item.meeting_id !== target.document.id));
        setLinkReviewRequired(true); setLinkSelectionVersion(value => value + 1);
        setTargetSelectionVersion(value => value + 1); app.closeSource();
        // Keep mutation controls locked until this access check returns.
        await recheckLinkSource(id);
      }
    });
  }
  async function removeLink(id: string) {
    if (!detail) return;
    const meetingId = detail.document.id;
    return mutate(signal => api(`/meetings/${meetingId}/links/${id}`, { method: 'DELETE', signal }), () => {
      if (selected.current !== meetingId) return;
      // A prior add/refresh may still hold the pre-delete links response.
      // Retire that read before removing locally, then reconcile surviving links.
      request('detail'); setRefreshing(false);
      setLinks(current => current.filter(link => link.id !== id));
      setNotice('결정 연결을 해제했어요.');
      void open(meetingId, true);
    });
  }
  useEffect(() => {
    if (!app.state.logoutBusy) return;
    for (const abort of aborts.current.values()) abort.abort();
    if (mutationBusy.current) setReviewRequired(true);
    mutationBusy.current = false; setBusy(false); setRefreshing(false); setLoading(false);
  }, [app.state.logoutBusy]);
  useEffect(() => {
    mounted.current = true; void load();
    return () => { mounted.current = false; for (const abort of aborts.current.values()) abort.abort(); };
  }, []);
  useEffect(() => {
    const pending = (value: MeetingDetail) => ['queued', 'running'].includes(value.meeting.analysis_status);
    if (!(detail && pending(detail)) && !meetings.some(pending)) return;
    const timer = setTimeout(() => { if (!mutationBusy.current) { void load(); if (selected.current) void open(selected.current, true); } }, 2500);
    return () => clearTimeout(timer);
  }, [meetings, detail, busy]);
  return { meetings, tasks, detail, links, linksKnown, verifySource, targets, loading, listState, busy, error, notice, editing, recovery, refreshing, reviewRequired, linkReviewRequired, linkSelectionVersion, targetSelectionVersion, sourceOrigin, edit, refresh, keepLocal, useServer, load, open, back, create, analyze, save, loadTargets, addLink, removeLink, clearError: () => setError('') };
}
export type MeetingsController = ReturnType<typeof useMeetings>;
