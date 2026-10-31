import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { sourceMatchPositions, sourceSpan, type SourceIndex, type Span } from '../meetings';

export function SourceSpanPicker({ index, opener, apply, close }: { index: SourceIndex; opener: HTMLElement | null; apply: (span: Span) => void; close: () => void }) {
  const content = index.content;
  const [page, setPage] = useState(0);
  const pageSize = 20;
  const dialog = useRef<HTMLDialogElement>(null);
  const source = useRef<HTMLTextAreaElement>(null);
  const [quote, setQuote] = useState('');
  const [selected, setSelected] = useState<Span | null>(null);
  const [error, setError] = useState('');
  const matches = useMemo(() => sourceMatchPositions(index, quote), [index, quote]);
  const quoteLength = useMemo(() => Array.from(quote).length, [quote]);
  const pages = Math.ceil(matches.length / pageSize);
  const context = (start: number, end: number) => content.slice(index.offsets[Math.max(0, start)], index.offsets[Math.min(index.offsets.length - 1, end)]);
  const visible = matches.slice(page * pageSize, (page + 1) * pageSize);
  useLayoutEffect(() => { dialog.current?.showModal(); source.current?.focus(); return () => { requestAnimationFrame(() => { if (opener?.isConnected) opener.focus(); }); }; }, []);
  function useSelection() {
    const input = source.current!;
    const span = sourceSpan(index, input.value, input.selectionStart, input.selectionEnd);
    if (!span) { setError('원문에서 완전한 구절을 선택해 주세요. 빈 선택이나 글자 일부는 사용할 수 없어요.'); return; }
    apply(span);
  }
  return <dialog ref={dialog} className="source-span-picker" aria-label="원문 근거 선택" onCancel={event => { event.preventDefault(); close(); }}>
    <h2>원문에서 근거 고르기</h2><p>구절을 드래그하거나 Shift와 방향키로 선택하세요. 인용 일치가 내용의 의미를 확인해 주지는 않아요.</p>
    <label>전체 원문<textarea ref={source} readOnly value={content} rows={10}/></label>
    <button type="button" className="button secondary" onClick={useSelection}>선택한 구절 사용</button>
    <label>정확한 구절 붙여넣기<textarea rows={3} value={quote} onChange={event => { setQuote(event.currentTarget.value); setSelected(null); setPage(0); setError(''); }}/></label>
    <p role="status">{quote ? matches.length ? `${matches.length}곳에서 일치해요. 문맥을 확인하고 위치를 직접 선택하세요.` : '일치하는 구절이 없어요. 원문을 그대로 복사해 주세요.' : '같은 구절이 여러 번 나오면 사용할 문맥을 선택하세요.'}</p>
    {!!matches.length && <div className="recovery-actions" aria-label="일치 위치 페이지">
      <p role="status">전체 {matches.length}곳 중 {page * pageSize + 1}–{Math.min((page + 1) * pageSize, matches.length)}번째 표시 · {page + 1}/{pages}페이지</p>
      <button type="button" disabled={page === 0} onClick={() => setPage(0)}>첫 페이지</button><button type="button" disabled={page === 0} onClick={() => setPage(value => value - 1)}>이전 페이지</button><button type="button" disabled={page + 1 >= pages} onClick={() => setPage(value => value + 1)}>다음 페이지</button><button type="button" disabled={page + 1 >= pages} onClick={() => setPage(pages - 1)}>마지막 페이지</button>
    </div>}
    <div className="span-matches">{visible.map((start, i) => <button key={start} type="button" className="span-match" aria-pressed={selected?.start_offset === start} onClick={() => setSelected({ quote, start_offset: start, end_offset: start + quoteLength })}><strong>{page * pageSize + i + 1}번째 일치</strong><span>{context(start - 35, start)}<mark>{quote}</mark>{context(start + quoteLength, start + quoteLength + 35)}</span></button>)}</div>
    {error && <p role="alert" className="form-error">{error}</p>}
    <div className="modal-actions"><button type="button" className="button secondary" onClick={close}>취소</button><button type="button" className="button primary" disabled={!selected} onClick={() => selected && apply(selected)}>확인한 위치 사용</button></div>
  </dialog>;
}
