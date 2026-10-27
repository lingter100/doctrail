import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../api';
import { knowledgeAbstention, knowledgeError, type KnowledgeResult } from '../meetings';
import type { DocTrail, SourceOrigin } from '../useDocTrail';
import { searchMethods } from '../searchMethods';
import type { SearchMethod } from '../types';
import { Icon } from './Icon';
import { Highlight } from './ContentViews';

export function KnowledgeView({ app }: { app: DocTrail }) {
  const restored = app.state.knowledgeRestore;
  const [query, setQuery] = useState(restored?.query || '');
  const [filters, setFilters] = useState({ scope: restored ? restored.workspace_id ?? 'all' : 'current', kind: (restored?.kind || 'all') as string, date_from: restored?.filters.date_from || '', date_to: restored?.filters.date_to || '', participant: restored?.filters.participant || '', assignee: restored?.filters.assignee || '', item_type: restored?.filters.item_type || '', meeting_id: restored?.filters.meeting_id || '' });
  const [method, setMethod] = useState<SearchMethod>(restored?.method || app.state.searchMethod);
  const [result, setResult] = useState<KnowledgeResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [mode, setMode] = useState<'search' | 'answer'>(restored?.operation || 'answer');
  const [asked, setAsked] = useState('');
  const [attempted, setAttempted] = useState(false);
  const [limit, setLimit] = useState(restored?.filters.limit || 5);
  type Feedback = { status: 'busy' | 'saved' | 'error'; relevant: boolean; error?: string };
  const [feedback, setFeedback] = useState<Record<string, Feedback>>({});
  const pendingFeedback = useRef(new Map<string, AbortController>());
  const workspaceId = filters.scope === 'all' ? null : filters.scope === 'current' ? app.state.workspaceId : filters.scope;
  const scopeUnavailable = workspaceId !== null && !app.state.auth?.workspaces.some(workspace => workspace.id === workspaceId);
  const methodUnavailable = method !== 'bm25' && !app.state.capabilities?.available_methods.includes(method);
  const unavailable = scopeUnavailable || methodUnavailable || app.state.logoutBusy;
  const previous = restored?.embedding_profile, currentProfile = app.state.capabilities?.embedding_profile;
  const profileMismatch = restored?.method !== 'bm25' && (!previous || !currentProfile || previous.id !== currentProfile.id || previous.model !== currentProfile.model || previous.revision !== currentProfile.revision);
  const request = useRef(0);
  const abort = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; request.current++; abort.current?.abort(); pendingFeedback.current.forEach(controller => controller.abort()); }; }, []);
  function invalidate() { request.current++; abort.current?.abort(); pendingFeedback.current.forEach(controller => controller.abort()); pendingFeedback.current.clear(); setFeedback({}); setResult(null); setError(''); setBusy(false); app.closeSource(); }
  useEffect(() => { if (app.state.logoutBusy) invalidate(); }, [app.state.logoutBusy]);
  function filter(key: keyof typeof filters, value: string) { invalidate(); setFilters(current => ({ ...current, [key]: value })); }
  function sourceOrigin(): SourceOrigin {
    const token = request.current, context = app.captureContext();
    return {
      query: asked, retryLabel: mode === 'answer' ? '다시 질문' : '다시 검색',
      isCurrent: () => mounted.current && token === request.current && context(),
      retry: () => { void run(mode); },
      onDenied: () => {
        // A denied source invalidates the snapshot, including answer claims
        // that may depend on it. Keep the form; only an explicit action resends.
        invalidate();
        setError('원문을 열 수 없어 이전 검색 결과와 답변을 숨겼어요. 현재 접근 가능한 자료로 다시 확인해 주세요.');
      },
    };
  }
  async function run(operation: 'search' | 'answer' = mode, requestedLimit = limit) {
    if (!query.trim() || unavailable || !Number.isInteger(requestedLimit) || requestedLimit < 1 || requestedLimit > (operation === 'answer' ? 10 : 50)) return;
    setAttempted(true); invalidate(); const controller = new AbortController(); abort.current = controller;
    const token = ++request.current, context = app.captureContext();
    const valid = () => mounted.current && context() && token === request.current && !controller.signal.aborted;
    setBusy(true); setError(''); setResult(null); setAsked(query.trim()); app.closeSource();
    try {
      const response = await api<KnowledgeResult>(`/knowledge/${operation}`, { method: 'POST', signal: controller.signal, body: JSON.stringify({
        query: query.trim(), workspace_id: workspaceId, kind: filters.kind,
        meeting_id: filters.meeting_id || null, date_from: filters.date_from || null, date_to: filters.date_to || null,
        participant: filters.participant.trim() || null, assignee: filters.assignee.trim() || null, item_type: filters.item_type || null,
        method, limit: requestedLimit, ...(method !== 'bm25' && app.state.capabilities?.embedding_profile ? { expected_embedding_profile: app.state.capabilities.embedding_profile.id } : {}),
      }) });
      if (valid()) setResult({ ...response, method: response.method || method, query: response.query || query.trim() });
    } catch (failure) { if (valid() && !app.sessionExpired(failure)) setError(knowledgeError(failure)); }
    finally { if (valid()) setBusy(false); }
  }
  async function saveFeedback(resultId: string, relevant: boolean) {
    if (!result?.history_id || pendingFeedback.current.has(resultId) || app.state.logoutBusy) return;
    const historyId = result.history_id, token = request.current, context = app.captureContext();
    const controller = new AbortController(); pendingFeedback.current.set(resultId, controller);
    const valid = () => mounted.current && context() && token === request.current && !controller.signal.aborted;
    setFeedback(current => ({ ...current, [resultId]: { status: 'busy', relevant } }));
    try {
      await api('/knowledge/history/' + encodeURIComponent(historyId) + '/feedback', { method: 'POST', signal: controller.signal, body: JSON.stringify({ result_id: resultId, relevant }) });
      if (valid()) setFeedback(current => ({ ...current, [resultId]: { status: 'saved', relevant } }));
    } catch (failure) {
      if (!valid() || app.sessionExpired(failure)) return;
      if (failure instanceof ApiError && [403, 404, 409].includes(failure.status)) {
        invalidate(); setError(knowledgeError(failure));
      } else setFeedback(current => ({ ...current, [resultId]: { status: 'error', relevant, error: knowledgeError(failure) } }));
    } finally { if (pendingFeedback.current.get(resultId) === controller) pendingFeedback.current.delete(resultId); }
  }
  const meetingFiltered = !!(filters.date_from || filters.date_to || filters.participant || filters.assignee || filters.item_type || filters.meeting_id);
  return <section className="knowledge-view">
    <div className="page-top"><div><span className="eyebrow">ASK YOUR TEAM'S KNOWLEDGE</span><h1>지식 검색 · Q&A</h1><p>회의와 문서를 함께 찾고, 답변의 근거를 원문에서 확인하세요.</p></div><span className="experimental-badge">답변 생성 · 실험 AI</span></div>
    {restored && !attempted && <div className="history-restore-notice" role="status" data-testid="knowledge-restore-notice"><strong>기록의 조건을 복원했어요. 아직 실행하지 않았어요.</strong><p>질문과 조건을 확인한 뒤 버튼을 눌러 현재 자료로 새로 실행해 주세요. 이전 답변과 원문은 불러오지 않아요.</p>{profileMismatch && <p>{!previous || !currentProfile ? '검색 모델 정보가 없어 같은 설정인지 확인할 수 없어요.' : '기록의 검색 모델과 현재 모델 설정이 달라요.'} 명시적으로 실행하면 현재 선택한 검색 방식과 설정을 사용해요.</p>}{restored.operation === 'answer' && <p>{restored.generation_model ? '기록에 사용한 답변 모델 정보는 있지만 현재 모델과 같은지 확인할 수 없어요.' : '이 기록에는 사용한 답변 모델 정보가 없어요.'} 질문하기를 누르면 현재 설정으로 답변을 새로 요청해요.</p>}</div>}
    <form className="knowledge-form" onSubmit={event => { event.preventDefault(); void run(); }}>
      <div className="meeting-tabs" role="tablist" aria-label="검색 또는 답변"><button role="tab" type="button" aria-selected={mode === 'answer'} onClick={() => { invalidate(); setMode('answer'); setLimit(5); }}>근거 기반 답변</button><button role="tab" type="button" aria-selected={mode === 'search'} onClick={() => { invalidate(); setMode('search'); setLimit(10); }}>원문 검색</button></div>
      <div className="global-search"><Icon name="search"/><input id="knowledge-query" aria-label="지식 질문" value={query} maxLength={500} required placeholder="예: 배포 일정은 어떻게 결정됐나요?" onChange={event => { invalidate(); setQuery(event.currentTarget.value); }}/><button className="search-submit" disabled={busy || unavailable}>{busy ? '확인 중…' : mode === 'answer' ? '질문하기' : '검색'}<Icon name="arrow"/></button></div>
      {mode === 'answer' && <p className="field-note">관련도가 높은 원문 최대 {limit}개를 바탕으로 답변해요. 자료가 많으면 검색 조건을 좁혀 주세요.</p>}
      <div className="knowledge-filters"><label>검색 범위<select value={filters.scope} onChange={event => filter('scope', event.currentTarget.value)}><option value="current">현재 워크스페이스</option><option value="all">접근 가능한 모든 워크스페이스</option>{app.state.auth?.workspaces.map(workspace => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}{scopeUnavailable && filters.scope !== 'current' && <option value={filters.scope}>기록의 워크스페이스 · 접근 확인 필요</option>}</select></label><label>자료 종류<select value={filters.kind} onChange={event => filter('kind', event.currentTarget.value)}><option value="all">회의 + 일반 문서</option><option value="meeting">회의</option><option value="document">일반 문서</option></select></label><label>검색 방식<select value={method} onChange={event => { invalidate(); setMethod(event.currentTarget.value as SearchMethod); }}>{(Object.keys(searchMethods) as SearchMethod[]).map(value => <option key={value} value={value} disabled={value !== 'bm25' && !app.state.capabilities?.available_methods.includes(value)}>{searchMethods[value].label}</option>)}</select></label></div>
      <details className="knowledge-advanced" open={restored ? true : undefined}><summary>회의 조건으로 좁히기{meetingFiltered ? ' · 적용 중' : ''}</summary><div className="knowledge-filters"><label>회의 시작일<input type="date" value={filters.date_from} max={filters.date_to || undefined} onChange={event => filter('date_from', event.currentTarget.value)}/></label><label>회의 종료일<input type="date" value={filters.date_to} min={filters.date_from || undefined} onChange={event => filter('date_to', event.currentTarget.value)}/></label><label>참석자<input value={filters.participant} placeholder="참석자 이름" onChange={event => filter('participant', event.currentTarget.value)}/></label><label>작업 담당자<input value={filters.assignee} placeholder="담당자 이름" onChange={event => filter('assignee', event.currentTarget.value)}/></label><label>항목 종류<select value={filters.item_type} onChange={event => filter('item_type', event.currentTarget.value)}><option value="">전체 항목</option><option value="decision">결정 사항</option><option value="action">후속 작업</option><option value="unresolved">미해결 사항</option></select></label><div className="knowledge-meeting-condition">{filters.meeting_id && <><span>특정 회의 · 저장된 회의로 제한됨</span><button type="button" className="text-button" onClick={() => filter('meeting_id', '')}>특정 회의 조건 해제</button></>}</div><label>최대 근거 수<input type="number" min={1} max={mode === 'answer' ? 10 : 50} value={limit} required onChange={event => { invalidate(); setLimit(Number(event.currentTarget.value)); }}/></label><div className="filter-reset"><button className="text-button" type="button" onClick={() => { invalidate(); setFilters(current => ({ ...current, date_from: '', date_to: '', participant: '', assignee: '', item_type: '', meeting_id: '' })); }}>회의 조건 초기화</button></div></div><p className="field-note">회의 조건을 적용하면 일반 문서는 제외돼요. 날짜는 질문에서 자동 추정하지 않으므로 직접 선택해 주세요.</p></details>
      {scopeUnavailable && <p className="error-banner" role="alert">기록의 워크스페이스에 접근할 수 없어요. 범위를 임의로 바꾸지 않았어요. 직접 다른 범위를 선택해 주세요.</p>}
      {methodUnavailable && <p className="field-note" role="status">현재 선택한 검색 모델을 사용할 수 없어요. 검색 방식을 직접 바꾸거나 모델 연결을 확인해 주세요. <button type="button" className="text-button" disabled={app.state.capabilitiesBusy} onClick={() => void app.loadCapabilities()}>모델 연결 확인</button></p>}
      {filters.meeting_id && <p className="field-note">저장된 특정 회의 조건을 그대로 사용해요. 접근할 수 없거나 삭제된 회의는 실행 시 확인하며 다른 회의로 바꾸지 않아요.</p>}
    </form>
    {error && <div className="error-banner" role="alert">{error}{mode === 'answer' && <button className="text-button" onClick={() => { setMode('search'); setLimit(10); void run('search', 10); }} disabled={busy || unavailable}>원문 검색으로 확인</button>}<button className="text-button" onClick={() => void run()} disabled={busy || unavailable}>다시 시도</button></div>}
    {busy && <div className="loading" role="status"><span className="spinner"/>{mode === 'answer' ? '접근 가능한 근거를 찾아 답변을 확인하고 있어요…' : '접근 가능한 원문을 검색하고 있어요…'}</div>}
    {!result && !busy && !error && <div className="knowledge-empty"><div className="knowledge-empty-icon"><Icon name="quote"/></div><h2>답변마다 돌아갈 수 있는 원문</h2><p>확인할 수 있는 근거가 부족하면 답변을 보류해요.<br/>회의별 결정과 후속 작업까지 조건으로 찾아보세요.</p><div className="question-suggestions">{['최근 회의에서 확정한 결정은 무엇인가요?', '아직 해결되지 않은 문제는 무엇인가요?'].map(question => <button key={question} onClick={() => { invalidate(); setQuery(question); document.getElementById('knowledge-query')?.focus(); }}>{question}<Icon name="arrow"/></button>)}</div></div>}
    {result && <div className="knowledge-results" aria-live="polite">
      {mode === 'answer' && <article className={`answer-panel ${result.status === 'abstained' ? 'abstained' : ''}`} data-testid="knowledge-answer"><div className="answer-heading"><span className="meeting-symbol"><Icon name="quote"/></span><h2>{result.status === 'answered' ? '근거 기반 답변' : '답변을 보류했어요'}</h2><span className="experimental-badge">실험 AI</span></div>{result.status === 'answered' ? <div className="answer-claims">{result.claims?.map((claim, index) => <section key={index}><p>{claim.text}</p><div className="claim-citations">{claim.citations.map((citation, citationIndex) => <button className="citation-chip" key={`${citation.document_id}:${citation.start_offset}:${citationIndex}`} onClick={() => void app.openEvidence(citation, sourceOrigin())}><Icon name="file"/>{citation.title || '원문'}{citation.meeting_date ? ` · ${citation.meeting_date}` : ''}{citation.page ? ` · ${citation.page}p` : ''}<span>근거 {index + 1}.{citationIndex + 1}</span></button>)}</div></section>)}</div> : <p>{knowledgeAbstention(result.reason)}</p>}<div className="answer-provenance">{result.model_called ? '실제 모델 생성 결과 · 원문 확인 필요' : '모델 호출 없이 근거 확인 단계에서 처리'} · 사용자 검수 전</div></article>}
      <div className="section-bar"><h2>검색된 원문 근거 <span className="count">{result.results.length}</span></h2><span className="muted">{result.method in searchMethods ? searchMethods[result.method as SearchMethod].label : result.method}</span></div>
      {!result.results.length && <p className="mini-empty">조건에 맞는 원문 근거가 없어요.</p>}
      <div className="results">{result.results.map((hit, index) => <article className="result-card knowledge-hit" key={`${hit.document_id}:${hit.chunk_id}`}><div className="result-meta"><span>{hit.document_kind === 'meeting' ? '회의' : '문서'}</span>{filters.scope === 'all' && <span>{app.state.auth?.workspaces.find(workspace => workspace.id === hit.workspace_id)?.name || '워크스페이스'}</span>}<span>{hit.meeting_date || (hit.document_kind === 'meeting' ? '날짜 확인 필요' : `v${hit.revision}`)}</span></div><button className="knowledge-hit-open" onClick={() => void app.openDocument(hit.document_id, hit, index, undefined, sourceOrigin())}><h3>{hit.title}</h3><p className="result-excerpt"><Highlight text={hit.text} query={asked}/></p><span className="text-button">원문에서 확인 <Icon name="arrow"/></span></button>{result.history_id && hit.result_id && <div className="knowledge-feedback"><span id={'feedback-label-' + hit.result_id}>이 원문이 질문과 관련 있나요?</span><div role="group" aria-labelledby={'feedback-label-' + hit.result_id}>{[true, false].map(relevant => <button type="button" key={String(relevant)} aria-label={(index + 1) + '번 근거 관련 ' + (relevant ? '있음' : '없음')} aria-pressed={feedback[hit.result_id]?.status === 'saved' && feedback[hit.result_id]?.relevant === relevant} disabled={feedback[hit.result_id]?.status === 'busy' || app.state.logoutBusy} onClick={() => void saveFeedback(hit.result_id, relevant)}>{relevant ? '관련 있어요' : '관련 없어요'}</button>)}</div><span role="status">{feedback[hit.result_id]?.status === 'busy' ? '피드백 저장 중…' : feedback[hit.result_id]?.status === 'saved' ? '피드백이 저장됐어요. 평가를 바꿀 수 있어요.' : ''}</span>{feedback[hit.result_id]?.status === 'error' && <div role="alert">{feedback[hit.result_id].error}<button type="button" className="text-button" onClick={() => void saveFeedback(hit.result_id, feedback[hit.result_id].relevant)}>피드백 다시 저장</button></div>}</div>}</article>)}</div>
    </div>}
  </section>;
}
