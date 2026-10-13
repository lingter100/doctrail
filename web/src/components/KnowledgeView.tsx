import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { meetingError, type KnowledgeResult } from '../meetings';
import type { DocTrail } from '../useDocTrail';
import { searchMethods } from '../searchMethods';
import type { SearchMethod } from '../types';
import { Icon } from './Icon';
import { Highlight } from './ContentViews';

export function KnowledgeView({ app }: { app: DocTrail }) {
  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState({ scope: 'current', kind: 'all', date_from: '', date_to: '', participant: '', assignee: '', item_type: '', meeting_id: '' });
  const [method, setMethod] = useState<SearchMethod>(app.state.searchMethod);
  const [result, setResult] = useState<KnowledgeResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [mode, setMode] = useState<'search' | 'answer'>('answer');
  const [asked, setAsked] = useState('');
  const request = useRef(0);
  const abort = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; request.current++; abort.current?.abort(); }; }, []);
  function invalidate() { request.current++; abort.current?.abort(); setResult(null); setError(''); setBusy(false); app.closeSource(); }
  function filter(key: keyof typeof filters, value: string) { invalidate(); setFilters(current => ({ ...current, [key]: value })); }
  async function run() {
    if (!query.trim()) return;
    abort.current?.abort(); const controller = new AbortController(); abort.current = controller;
    const token = ++request.current;
    const valid = () => mounted.current && token === request.current && !controller.signal.aborted;
    setBusy(true); setError(''); setResult(null); setAsked(query.trim()); app.closeSource();
    try {
      const response = await api<KnowledgeResult>(`/knowledge/${mode}`, { method: 'POST', signal: controller.signal, body: JSON.stringify({
        query: query.trim(), workspace_id: filters.scope === 'current' ? app.state.workspaceId : null, kind: filters.kind,
        meeting_id: filters.meeting_id || null, date_from: filters.date_from || null, date_to: filters.date_to || null,
        participant: filters.participant.trim() || null, assignee: filters.assignee.trim() || null, item_type: filters.item_type || null,
        method, limit: mode === 'answer' ? 5 : 10, ...(method !== 'bm25' && app.state.capabilities?.embedding_profile ? { expected_embedding_profile: app.state.capabilities.embedding_profile.id } : {}),
      }) });
      if (valid()) setResult({ ...response, method: response.method || method, query: response.query || query.trim() });
    } catch (failure) { if (valid() && !app.sessionExpired(failure)) setError(meetingError(failure)); }
    finally { if (valid()) setBusy(false); }
  }
  const meetingFiltered = !!(filters.date_from || filters.date_to || filters.participant || filters.assignee || filters.item_type || filters.meeting_id);
  return <section className="knowledge-view">
    <div className="page-top"><div><span className="eyebrow">ASK YOUR TEAM'S KNOWLEDGE</span><h1>지식 검색 · Q&A</h1><p>회의와 문서를 함께 찾고, 답변의 근거를 원문에서 확인하세요.</p></div><span className="experimental-badge">답변 생성 · 실험 AI</span></div>
    <form className="knowledge-form" onSubmit={event => { event.preventDefault(); void run(); }}>
      <div className="meeting-tabs" role="tablist" aria-label="검색 또는 답변"><button role="tab" type="button" aria-selected={mode === 'answer'} onClick={() => { invalidate(); setMode('answer'); }}>근거 기반 답변</button><button role="tab" type="button" aria-selected={mode === 'search'} onClick={() => { invalidate(); setMode('search'); }}>원문 검색</button></div>
      <div className="global-search"><Icon name="search"/><input id="knowledge-query" aria-label="지식 질문" value={query} maxLength={500} required placeholder="예: 배포 일정은 어떻게 결정됐나요?" onChange={event => { invalidate(); setQuery(event.currentTarget.value); }}/><button className="search-submit" disabled={busy || !app.workspace}>{busy ? '확인 중…' : mode === 'answer' ? '질문하기' : '검색'}<Icon name="arrow"/></button></div>
      {mode === 'answer' && <p className="field-note">관련도가 높은 원문 5개를 바탕으로 답변해요. 자료가 많으면 검색 조건을 좁혀 주세요.</p>}
      <div className="knowledge-filters"><label>검색 범위<select value={filters.scope} onChange={event => filter('scope', event.currentTarget.value)}><option value="current">현재 워크스페이스</option><option value="all">접근 가능한 모든 워크스페이스</option></select></label><label>자료 종류<select value={filters.kind} onChange={event => filter('kind', event.currentTarget.value)}><option value="all">회의 + 일반 문서</option><option value="meeting">회의</option><option value="document">일반 문서</option></select></label><label>검색 방식<select value={method} onChange={event => { invalidate(); setMethod(event.currentTarget.value as SearchMethod); }}>{(Object.keys(searchMethods) as SearchMethod[]).map(value => <option key={value} value={value} disabled={value !== 'bm25' && !app.state.capabilities?.available_methods.includes(value)}>{searchMethods[value].label}</option>)}</select></label></div>
      <details className="knowledge-advanced"><summary>회의 조건으로 좁히기{meetingFiltered ? ' · 적용 중' : ''}</summary><div className="knowledge-filters"><label>회의 시작일<input type="date" value={filters.date_from} max={filters.date_to || undefined} onChange={event => filter('date_from', event.currentTarget.value)}/></label><label>회의 종료일<input type="date" value={filters.date_to} min={filters.date_from || undefined} onChange={event => filter('date_to', event.currentTarget.value)}/></label><label>참석자<input value={filters.participant} placeholder="참석자 이름" onChange={event => filter('participant', event.currentTarget.value)}/></label><label>작업 담당자<input value={filters.assignee} placeholder="담당자 이름" onChange={event => filter('assignee', event.currentTarget.value)}/></label><label>항목 종류<select value={filters.item_type} onChange={event => filter('item_type', event.currentTarget.value)}><option value="">전체 항목</option><option value="decision">결정 사항</option><option value="action">후속 작업</option><option value="unresolved">미해결 사항</option></select></label><div className="filter-reset"><button className="text-button" type="button" onClick={() => { invalidate(); setFilters(current => ({ ...current, date_from: '', date_to: '', participant: '', assignee: '', item_type: '', meeting_id: '' })); }}>회의 조건 초기화</button></div></div><p className="field-note">회의 조건을 적용하면 일반 문서는 제외돼요. 날짜는 질문에서 자동 추정하지 않으므로 직접 선택해 주세요.</p></details>
    </form>
    {error && <div className="error-banner" role="alert">{error}<button className="text-button" onClick={() => void run()} disabled={busy}>다시 시도</button></div>}
    {busy && <div className="loading" role="status"><span className="spinner"/>{mode === 'answer' ? '접근 가능한 근거를 찾아 답변을 확인하고 있어요…' : '접근 가능한 원문을 검색하고 있어요…'}</div>}
    {!result && !busy && !error && <div className="knowledge-empty"><div className="knowledge-empty-icon"><Icon name="quote"/></div><h2>답변마다 돌아갈 수 있는 원문</h2><p>확인할 수 있는 근거가 부족하면 답변을 보류해요.<br/>회의별 결정과 후속 작업까지 조건으로 찾아보세요.</p><div className="question-suggestions">{['최근 회의에서 확정한 결정은 무엇인가요?', '아직 해결되지 않은 문제는 무엇인가요?'].map(question => <button key={question} onClick={() => { invalidate(); setQuery(question); document.getElementById('knowledge-query')?.focus(); }}>{question}<Icon name="arrow"/></button>)}</div></div>}
    {result && <div className="knowledge-results" aria-live="polite">
      {mode === 'answer' && <article className={`answer-panel ${result.status === 'abstained' ? 'abstained' : ''}`} data-testid="knowledge-answer"><div className="answer-heading"><span className="meeting-symbol"><Icon name="quote"/></span><h2>{result.status === 'answered' ? '근거 기반 답변' : '답변을 보류했어요'}</h2><span className="experimental-badge">실험 AI</span></div>{result.status === 'answered' ? <div className="answer-claims">{result.claims?.map((claim, index) => <section key={index}><p>{claim.text}</p><div className="claim-citations">{claim.citations.map((citation, citationIndex) => <button className="citation-chip" key={`${citation.document_id}:${citation.start_offset}:${citationIndex}`} onClick={() => void app.openEvidence(citation)}><Icon name="file"/>{citation.title || '원문'}{citation.meeting_date ? ` · ${citation.meeting_date}` : ''}{citation.page ? ` · ${citation.page}p` : ''}<span>근거 {index + 1}.{citationIndex + 1}</span></button>)}</div></section>)}</div> : <><p>현재 접근 가능한 자료에서 질문에 답할 충분한 근거를 확인하지 못했어요. 조건을 조정하거나 관련 원문을 추가해 주세요.</p>{result.reason && <small className="muted">보류 사유: {result.reason}</small>}</>}<div className="answer-provenance">{result.model_called ? '실제 모델 생성 결과 · 원문 확인 필요' : '모델 호출 없이 근거 확인 단계에서 처리'} · 사용자 검수 전</div></article>}
      <div className="section-bar"><h2>검색된 원문 근거 <span className="count">{result.results.length}</span></h2><span className="muted">{result.method in searchMethods ? searchMethods[result.method as SearchMethod].label : result.method}</span></div>
      {!result.results.length && <p className="mini-empty">조건에 맞는 원문 근거가 없어요.</p>}
      <div className="results">{result.results.map((hit, index) => <article className="result-card knowledge-hit" key={`${hit.document_id}:${hit.chunk_id}`}><div className="result-meta"><span>{hit.document_kind === 'meeting' ? '회의' : '문서'}</span>{filters.scope === 'all' && <span>{app.state.auth?.workspaces.find(workspace => workspace.id === hit.workspace_id)?.name || '워크스페이스'}</span>}<span>{hit.meeting_date || (hit.document_kind === 'meeting' ? '날짜 확인 필요' : `v${hit.revision}`)}</span></div><button className="knowledge-hit-open" onClick={() => void app.openDocument(hit.document_id, hit, index)}><h3>{hit.title}</h3><p className="result-excerpt"><Highlight text={hit.text} query={asked}/></p><span className="text-button">원문에서 확인 <Icon name="arrow"/></span></button></article>)}</div>
    </div>}
  </section>;
}
