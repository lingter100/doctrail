import { Fragment, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { knowledgeAbstention, knowledgeError } from '../meetings';
import type { KnowledgeHistory } from '../types';
import { date, excerpt, fullDate, highlightParts, statusLabel, visibilityLabel } from '../helpers';
import type { DocTrail } from '../useDocTrail';
import { Icon } from './Icon';
import { profileLabel, searchMethods } from '../searchMethods';

export function Highlight({ text, query }: { text: string; query: string }) {
  return <>{highlightParts(text, query).map((part, index) => part.marked ? <mark key={index}>{part.text}</mark> : <Fragment key={index}>{part.text}</Fragment>)}</>;
}
export function Library({ app }: { app: DocTrail }) {
  const { documents, filter, selected } = app.state;
  const filtered = documents.filter(doc => doc.title.toLowerCase().includes(filter.toLowerCase()) || doc.filename.toLowerCase().includes(filter.toLowerCase()));
  return <>
    <div className="section-bar"><div className="section-tabs"><span className="active">모든 문서 <b>{documents.length}</b></span></div><div className="library-filter"><Icon name="search"/><input id="filter" aria-label="문서 제목 필터" placeholder="제목으로 좁히기" value={filter} onChange={event => app.setFilter(event.currentTarget.value)}/></div></div>
    {!documents.length ? <>
      <div className="empty-state library-empty"><div className="empty-illustration"><span className="paper back"/><span className="paper front"><Icon name="file"/><i/><i/><i/></span><span className="empty-plus"><Icon name="plus"/></span></div><span className="eyebrow">A GOOD PLACE TO BEGIN</span><h2>첫 번째 문서가, 첫 번째 근거가 됩니다.</h2><p>회의록, 프로젝트 기록, 참고 자료를 올려 보세요.<br/>문서 속 키워드부터 원문 위치까지 연결해 드릴게요.</p><button className="button primary" id="empty-upload" disabled={!app.workspace} onClick={() => app.openModal('upload')}><Icon name="upload"/> 첫 문서 업로드</button><span className="file-hint">TXT · MD · 텍스트 PDF &nbsp; / &nbsp; 최대 5MB</span></div>
      <div className="getting-started"><article><span>01</span><div><h3>기록을 모으세요</h3><p>파일을 올리고 문서 공개 범위를 선택해요.</p></div></article><article><span>02</span><div><h3>필요한 표현을 찾으세요</h3><p>문서 속 키워드로 관련 구절을 검색해요.</p></div></article><article><span>03</span><div><h3>원문으로 확인하세요</h3><p>검색된 구절과 최신 문서를 함께 읽어요.</p></div></article></div>
    </> : <>
      <div className="document-table"><div className="table-head"><span>문서 이름</span><span>공개 범위</span><span>상태</span><span>최근 수정</span><span/></div>
        {filtered.length ? filtered.map(doc => <button key={doc.id} className={`document-row ${selected?.id === doc.id ? 'selected' : ''}`} data-document={doc.id} onClick={() => void app.openDocument(doc.id)}>
          <span className="doc-name"><span className={`file-icon ${doc.filename.toLowerCase().endsWith('.pdf') ? 'pdf' : ''}`}><Icon name="file"/><small>{doc.filename.split('.').pop()?.toUpperCase()}</small></span><span><strong>{doc.title}</strong><small>{doc.filename} <span>· v{doc.revision}</span></small></span></span>
          <span className="visibility"><Icon name={doc.visibility === 'private' ? 'lock' : 'people'}/>{visibilityLabel(doc)}</span><span><span className={`status-badge ${doc.status}`}><i/>{statusLabel(doc)}</span></span><span className="doc-date">{date(doc.updated_at)}</span><Icon name="chevron"/>
        </button>) : <div className="mini-empty">일치하는 제목이 없어요.</div>}
      </div><div className="table-bottom"><span>{filtered.length}개의 문서</span><span>문서를 선택하면 원문이 열립니다 <Icon name="arrow"/></span></div>
    </>}
  </>;
}
export function HistoryView({ app }: { app: DocTrail }) {
  const { history } = app.state;
  const [tab, setTab] = useState<'document' | 'knowledge'>('document');
  const [items, setItems] = useState<KnowledgeHistory[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const request = useRef(0);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => { request.current++; abort.current?.abort(); }, []);
  useEffect(() => {
    if (app.state.logoutBusy) { request.current++; abort.current?.abort(); setItems([]); setBusy(false); setError(''); }
  }, [app.state.logoutBusy]);
  function selectTab(next: typeof tab) {
    request.current++; abort.current?.abort(); setBusy(false); setError(''); setItems([]); setTab(next);
    if (next === 'knowledge') void load();
  }
  async function load() {
    abort.current?.abort(); const controller = new AbortController(); abort.current = controller;
    const token = ++request.current, current = app.captureContext();
    const valid = () => current() && token === request.current && !controller.signal.aborted;
    setBusy(true); setError(''); setItems([]);
    try {
      const response = await api<{ items: KnowledgeHistory[] }>('/knowledge/history', { signal: controller.signal });
      if (valid()) setItems(response.items);
    } catch (failure) { if (valid() && !app.sessionExpired(failure)) setError(knowledgeError(failure)); }
    finally { if (valid()) setBusy(false); }
  }
  return <>
    <div className="meeting-tabs history-tabs" role="tablist" aria-label="기록 종류">
      <button type="button" role="tab" aria-selected={tab === 'document'} onClick={() => selectTab('document')}>문서 검색</button>
      <button type="button" role="tab" aria-selected={tab === 'knowledge'} onClick={() => selectTab('knowledge')}>통합 검색·질문</button>
    </div>
    {tab === 'document' ? <><div className="section-bar"><h2>최근 검색 <span className="count">{history.length}</span></h2><span className="muted">내 검색 기록만 표시됩니다</span></div>
    {history.length ? <div className="history-list">{history.map((item, index) => <button key={item.id} className="history-row" data-history={index} onClick={() => app.rerunHistory(item)}><span className="history-icon"><Icon name="clock"/></span><span><strong>{item.query}</strong><small>{fullDate(item.created_at)} · {searchMethods[item.method || 'bm25'].label}{item.method && item.method !== 'bm25' ? ` · ${profileLabel(item.embedding_profile)}` : ''}</small></span><span className="history-count">근거 {item.result_count}개</span><Icon name="arrow"/></button>)}</div> : <div className="empty-state compact"><Icon name="clock" className="empty-icon"/><h2>아직 검색 기록이 없어요.</h2><p>궁금한 키워드를 검색하면, 이곳에서 다시 찾을 수 있어요.</p></div>}
</> : <section aria-label="통합 검색·질문 기록">
      <div className="section-bar"><h2>통합 검색·질문 <span className="count">{items.length}</span></h2><button className="text-button" disabled={busy} onClick={() => void load()}>기록 새로고침</button></div>
      <p className="field-note">모든 워크스페이스의 내 완료 기록을 최근 100개까지 표시해요. 조건만 복원하며, 답변과 원문은 보관하지 않아요. 근거 수는 현재 접근 가능한 최신 자료 기준이에요.</p>
      {busy ? <div className="loading" role="status">기록을 불러오는 중이에요…</div> : error ? <div className="error-banner" role="alert">{error}<button className="text-button" onClick={() => void load()}>기록 다시 불러오기</button></div> : items.length ? <div className="history-list">{items.map(item => <button key={item.id} className="history-row knowledge-history-row" data-knowledge-history={item.id} onClick={() => app.restoreKnowledgeHistory(item)}>
        <span className="history-icon"><Icon name="clock"/></span><span><strong>{item.query}</strong><small>{fullDate(item.created_at)} · {item.operation === 'answer' ? '질문' : '검색'} · {item.status === 'abstained' ? '답변 보류' : item.status === 'answered' ? '답변 완료' : '검색 완료'}</small><small>{item.kind === 'all' ? '회의 + 문서' : item.kind === 'meeting' ? '회의' : '문서'} · {item.workspace_id === null ? '모든 워크스페이스' : app.state.auth?.workspaces.find(workspace => workspace.id === item.workspace_id)?.name || '접근 확인 필요'} · {searchMethods[item.method].label} · 최대 {item.filters.limit}개</small>{item.status === 'abstained' && <small>{knowledgeAbstention(item.reason)}</small>}<small>조건 복원 · 실행은 다음 화면에서</small></span><span className="history-count">근거 {item.result_count}개</span><Icon name="arrow"/>
      </button>)}</div> : <div className="empty-state compact"><Icon name="clock" className="empty-icon"/><h2>아직 통합 검색·질문 기록이 없어요.</h2><p>검색 또는 질문이 완료되면 이곳에서 조건을 다시 불러올 수 있어요.</p></div>}
    </section>}
  </>;
}
export function SearchView({ app }: { app: DocTrail }) {
  const { search, selectedHit, feedback } = app.state;
  if (!search) return <div className="empty-state compact"><Icon name="search" className="empty-icon"/><h2>찾고 싶은 문서 속 표현이 있나요?</h2><p>위 검색창에 키워드를 입력하면 관련 구절을 찾아드려요.</p></div>;
  return <><div className="section-bar"><h2>검색된 근거 <span className="count">{search.results.length}</span></h2><span className="muted">{searchMethods[search.method].label}{search.method !== 'bm25' ? ` · ${profileLabel(search.embedding_profile)}` : ''} · {Math.round(search.elapsed_ms)}ms · 관련도순</span></div>
    {search.results.length ? <><div className="results">{search.results.map((hit, index) => <article key={hit.chunk_id} className={`result-card ${selectedHit?.chunk_id === hit.chunk_id ? 'selected' : ''}`}>
      <button className="result-open" data-hit={index} onClick={() => void app.openDocument(hit.document_id, hit, index)}><div className="result-meta"><span className="citation-number">{index + 1}</span><span>{hit.filename}</span><span>v{hit.revision}{hit.page ? ` · ${hit.page}페이지` : ''}</span></div><h2>{hit.title}</h2><p className="result-excerpt"><Highlight text={excerpt(hit.text, search.query)} query={search.query}/></p><span className="result-link">원문에서 근거 확인 <Icon name="arrow"/></span></button>
      <div className="result-bottom"><span>검색된 원문 구절</span><div className="feedback">{feedback[hit.chunk_id] === 'saved' ? '피드백이 저장됐어요. 고마워요!' : <><span>도움이 됐나요?</span><button data-feedback={index} data-relevant="true" aria-label={`${index + 1}번 결과 관련 있음`} disabled={feedback[hit.chunk_id] === 'busy'} onClick={() => void app.feedback(index, true)}>관련 있어요</button><button data-feedback={index} data-relevant="false" aria-label={`${index + 1}번 결과 관련 없음`} disabled={feedback[hit.chunk_id] === 'busy'} onClick={() => void app.feedback(index, false)}>관련 없어요</button></>}</div></div>
    </article>)}</div><p className="search-disclaimer">검색 결과는 원문 구절입니다. AI가 생성한 답변이 아니에요.</p></> : <div className="empty-state compact"><Icon name="search" className="empty-icon"/><h2>“{search.query}”에 맞는 근거가 없어요.</h2><p>문서에 쓰인 표현으로 바꾸거나, 더 짧은 키워드를 입력해 보세요.<br/>문서의 상태가 ‘검색 가능’인지도 확인해 주세요.</p><button className="button secondary" id="back-library" onClick={() => app.changeView('library')}>문서 라이브러리 보기</button></div>}
  </>;
}
