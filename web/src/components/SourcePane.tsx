import { useEffect, useRef } from 'react';
import type { DocTrail } from '../useDocTrail';
import { date, sourceParts, visibilityLabel } from '../helpers';
import { Highlight } from './ContentViews';
import { Icon } from './Icon';

export function SourcePane({ app }: { app: DocTrail }) {
  const { selected: doc, selectedHit: hit, selectedEvidence: evidence, selectedIndex, search, auth, retryBusy, modal } = app.state;
  const pane = useRef<HTMLElement>(null), close = useRef<HTMLButtonElement>(null), mark = useRef<HTMLElement>(null);
  const focusKey = `${doc?.id}:${doc?.revision}:${hit?.chunk_id || ''}:${evidence?.start_offset ?? ''}`;
  useEffect(() => {
    if (modal) return;
    pane.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    close.current?.focus({ preventScroll: true });
  }, [focusKey]);
  if (!doc) return null;
  const isOwner = doc.owner_id === auth?.user.id;
  const evidenceChunk = evidence?.chunk_id ? doc.chunks.find(chunk => chunk.id === evidence.chunk_id) : undefined;
  const evidenceCurrent = evidence && evidence.revision === doc.revision && (!evidence.chunk_id || (evidenceChunk && evidence.start_offset >= evidenceChunk.start_offset && evidence.end_offset <= evidenceChunk.end_offset));
  const candidate = evidenceCurrent
    ? { id: evidence.chunk_id || '', text: evidence.quote, start_offset: evidence.start_offset, end_offset: evidence.end_offset, page: evidence.page || null, ordinal: 0 }
    : hit && doc.revision === hit.revision ? doc.chunks.find(chunk => chunk.id === hit.chunk_id) : undefined;
  const parts = sourceParts(doc.content, candidate);
  // A matching revision/chunk ID alone is insufficient if its span is corrupt.
  const citation = parts ? candidate : undefined;
  return <aside className="source-pane" aria-label="문서 원문" ref={pane}>
    <header className="source-top"><span><Icon name="file"/> 원문 보기</span><button ref={close} className="icon-button" id="close-source" aria-label="원문 닫기" onClick={app.closeSource}><Icon name="close"/></button></header>
    <div className="source-scroll"><div className="source-heading"><span className="eyebrow">SOURCE DOCUMENT</span><h2>{doc.title}</h2><p>{doc.filename}</p><div className="source-badges"><span><Icon name={doc.visibility === 'private' ? 'lock' : 'people'}/>{visibilityLabel(doc)}</span><span>버전 {doc.revision}</span><span>{doc.chunk_count}개 구절</span></div></div>
      {doc.status === 'failed' && <div className="source-warning"><strong>이 문서는 아직 검색할 수 없어요.</strong><p>파일에서 텍스트를 추출하지 못했어요. UTF-8 문서 또는 텍스트가 포함된 PDF인지 확인해 주세요.</p>{isOwner && <button className="button secondary" id="retry-document" disabled={retryBusy} onClick={() => void app.reprocess()}>다시 처리하기</button>}</div>}
      {(hit || evidence) && !citation && <div className="source-warning"><strong>검색 이후 원문이 변경되었어요.</strong><p>아래에는 최신 문서가 표시됩니다. 정확한 근거 위치는 다시 검색해 확인해 주세요.</p>{hit && <button className="text-button" id="search-again" onClick={() => void app.runSearch(search?.query || '')}>다시 검색</button>}</div>}
      {citation && <section className="citation-block"><div><span><Icon name="quote"/> 근거 {selectedIndex + 1}</span><small>v{doc.revision}{citation.page ? ` · ${citation.page}페이지` : ''}</small></div><blockquote><Highlight text={citation.text} query={search?.query || ''}/></blockquote><button className="text-button" id="jump-source" onClick={() => mark.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })}>원문 위치로 이동 ↓</button></section>}
      <div className="source-label"><span>전체 원문</span><small>{date(doc.updated_at)} 수정</small></div><div className="source-text" id="source-text">{parts ? <>{parts.before}<mark id="source-citation" ref={mark}>{parts.match}</mark>{parts.after}</> : doc.content}</div>
      {!doc.content && <p className="muted source-empty">표시할 텍스트가 없어요.</p>}
    </div><footer className="source-actions"><span>원문 텍스트 · v{doc.revision}{doc.document_kind === 'meeting' ? ' · 읽기 전용' : ''}</span>{isOwner && <>{doc.document_kind !== 'meeting' && <button className="button secondary small-button" id="edit-document" onClick={() => app.openModal('edit')}><Icon name="edit"/> 편집</button>}<button className="text-button danger" id="delete-document" onClick={() => app.openModal('delete')}>삭제</button></>}</footer>
  </aside>;
}
