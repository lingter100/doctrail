import { useLayoutEffect, useRef, useState } from 'react';
import type { DocTrail } from '../useDocTrail';
import { useMeetings, type MeetingsController } from '../useMeetings';
import { analysisLabels, itemLabels, statusLabels, type Analysis, type ItemStatus, type ItemType, type MeetingDetail, type MeetingItem, type Span } from '../meetings';
import { Icon } from './Icon';

const kinds: ItemType[] = ['topic', 'proposal', 'decision', 'unresolved', 'action'];
function AnalysisStatus({ value }: { value: MeetingDetail['meeting']['analysis_status'] }) {
  return <span className={`status-badge analysis-status ${value}`}><i/>{analysisLabels[value]}</span>;
}
function EvidenceButton({ span, detail, app, label = '원문 근거' }: { span: Span; detail: MeetingDetail; app: DocTrail; label?: string }) {
  return <button type="button" className="evidence-button" onClick={() => void app.openEvidence({ ...span, document_id: detail.document.id, revision: detail.meeting.source_revision })}><Icon name="quote"/><span>{label}</span><span className="evidence-preview">{span.quote}</span><Icon name="arrow"/></button>;
}

export function MeetingWorkspace({ app, mode }: { app: DocTrail; mode: 'meetings' | 'actions' }) {
  const controller = useMeetings(app, mode);
  const [registration, setRegistration] = useState(false);
  const [filter, setFilter] = useState('');
  const [assignee, setAssignee] = useState('');
  const [status, setStatus] = useState('');
  const { detail, meetings, tasks } = controller;
  const visible = meetings.filter(item => `${item.document.title} ${item.meeting.analysis?.summary || ''}`.toLocaleLowerCase().includes(filter.toLocaleLowerCase()));
  const actions = tasks.filter(item => (!assignee || (item.assignee || '').toLocaleLowerCase().includes(assignee.toLocaleLowerCase())) && (!status || item.status === status));
  return <div className="meeting-workspace">
    <div className="page-top"><div><span className="eyebrow">{mode === 'actions' ? 'TURN CONVERSATIONS INTO PROGRESS' : 'FROM CONVERSATION TO CLARITY'}</span><h1>{mode === 'actions' ? '후속 작업' : '회의'}</h1><p>{mode === 'actions' ? '회의에서 나온 할 일을 모으고, 담당자와 진행 상태를 확인하세요.' : '회의를 기록하고, 논의와 결정의 근거를 연결하세요.'}</p></div>{mode === 'meetings' && <button className="button primary" disabled={!app.workspace || controller.busy} onClick={() => { controller.clearError(); setRegistration(true); }}><Icon name="plus"/> 회의 등록</button>}</div>
    {controller.error && !registration && <div className="error-banner" role="alert">{controller.error}<button className="text-button" disabled={controller.busy} onClick={() => void (detail ? controller.open(detail.document.id) : controller.load())}>새로 불러오기</button></div>}
    {controller.notice && <p className="meeting-notice" role="status">{controller.notice}</p>}
    {detail ? <MeetingDetailView key={detail.document.id} app={app} controller={controller}/> : controller.loading ? <div className="loading"><span className="spinner"/>회의를 불러오는 중이에요…</div> : mode === 'actions' ? <>
      <div className="meeting-toolbar"><strong>{actions.length}개 작업</strong><div className="inline-filters"><label>담당자<input value={assignee} onChange={event => setAssignee(event.currentTarget.value)} placeholder="담당자 이름"/></label><label>진행 상태<select value={status} onChange={event => setStatus(event.currentTarget.value)}><option value="">모든 상태</option>{(['needs_confirmation', 'todo', 'doing', 'done'] as ItemStatus[]).map(value => <option key={value} value={value}>{statusLabels[value]}</option>)}</select></label></div></div>
      {!actions.length ? <div className="empty-state"><Icon name="check" className="empty-icon"/><h2>표시할 후속 작업이 없어요</h2><p>분석이 완료된 회의의 작업이 여기에 모여요.<br/>없는 담당자와 마감일은 확인 필요로 남겨요.</p></div> : <div className="task-list">{actions.map(item => <button className="task-row" key={`${item.meeting_id}:${item.id}`} onClick={() => void controller.open(item.meeting_id)}><span className={`task-state ${item.status}`}><Icon name={item.status === 'done' ? 'check' : 'clock'}/></span><span className="task-copy"><strong>{item.text}</strong><small>{item.title}</small></span><span>{item.assignee || '담당자 확인 필요'}</span><span>{item.due_date || '마감일 확인 필요'}</span><span className="status-badge">{statusLabels[item.status]}</span><Icon name="chevron"/></button>)}</div>}
    </> : <>
      <div className="meeting-toolbar"><div><strong>모든 회의</strong><span className="count">{visible.length}</span></div><label className="meeting-filter"><span className="sr-only">회의 제목 검색</span><Icon name="search"/><input value={filter} onChange={event => setFilter(event.currentTarget.value)} placeholder="회의 찾아보기"/></label></div>
      {!visible.length ? <div className="empty-state meeting-empty"><Icon name="people" className="empty-icon"/><span className="eyebrow">MAKE EVERY MEETING COUNT</span><h2>{filter ? '조건에 맞는 회의가 없어요' : '대화가 지식이 되는 곳'}</h2><p>회의록을 붙여 넣거나 TXT·MD·텍스트 PDF를 올리세요.<br/>AI 초안, 직접 수정한 내용, 원문을 구분해서 보관해요.</p>{!filter && <button className="button secondary" onClick={() => setRegistration(true)}>첫 회의 등록하기 <Icon name="arrow"/></button>}</div> : <div className="meeting-grid">{visible.map(item => <button className="meeting-card" key={item.document.id} data-meeting={item.document.id} onClick={() => void controller.open(item.document.id)}><div className="meeting-card-top"><span className="meeting-symbol"><Icon name="people"/></span><AnalysisStatus value={item.meeting.analysis_status}/></div><h2>{item.meeting.analysis?.meeting_title || item.document.title}</h2><p>{item.meeting.analysis?.summary || '원문을 열고 AI 분석 상태를 확인하세요.'}</p><div className="meeting-card-meta"><span>{item.meeting.analysis?.meeting_date || '날짜 확인 필요'}</span><span>{item.meeting.analysis?.participants.length ? `${item.meeting.analysis.participants.length}명 참석` : '참석자 확인 필요'}</span></div><div className="meeting-card-foot"><span>{item.document.visibility === 'private' ? '나만 보기' : '워크스페이스'}</span><span>{item.meeting.provenance === 'user_edited' ? '사용자 수정' : 'AI 초안'} <Icon name="chevron"/></span></div></button>)}</div>}
    </>}
    {registration && <MeetingRegistration controller={controller} close={() => setRegistration(false)}/>}
  </div>;
}

function MeetingRegistration({ controller, close }: { controller: MeetingsController; close: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [file, setFile] = useState(false);
  useLayoutEffect(() => {
    const opener = document.activeElement as HTMLElement | null; dialog.current?.showModal();
    return () => { dialog.current?.close(); requestAnimationFrame(() => opener?.isConnected && opener.focus()); };
  }, []);
  return <dialog className="wide" ref={dialog} aria-labelledby="meeting-register-title" onCancel={event => { event.preventDefault(); if (!controller.busy) close(); }}>
    <header className="modal-head"><div><h2 id="meeting-register-title">회의 등록</h2><p>원문을 보관하고, 실험 AI 모델에 분석을 요청해요.</p></div><button className="icon-button" aria-label="회의 등록 닫기" disabled={controller.busy} onClick={close}><Icon name="close"/></button></header>
    <div className="meeting-tabs" role="tablist" aria-label="등록 방식"><button type="button" role="tab" aria-selected={!file} onClick={() => setFile(false)} disabled={controller.busy}>텍스트 입력</button><button type="button" role="tab" aria-selected={file} onClick={() => setFile(true)} disabled={controller.busy}>파일 업로드</button></div>
    <form key={String(file)} onSubmit={event => { event.preventDefault(); const data = new FormData(event.currentTarget); void controller.create(data, file).then(saved => { if (saved) close(); }); }}>
      <label>회의 제목<input name="title" required={!file} maxLength={200} placeholder="예: 제품팀 주간 회의"/></label>
      {file ? <label className="file-drop"><Icon name="upload"/><strong>회의록 파일 선택</strong><span>UTF-8 TXT · MD · 텍스트 PDF / 최대 5MB</span><input type="file" name="file" accept=".txt,.md,.pdf" required aria-label="회의록 파일"/></label> : <label>회의 원문<textarea name="content" rows={10} required placeholder="회의록이나 대화 내용을 붙여 넣으세요. 날짜, 참석자, 담당자 등 원문에 없는 정보는 AI가 추정하지 않도록 요청해요."/></label>}
      <label>공개 범위<select name="visibility"><option value="workspace">워크스페이스 멤버에게 공개</option><option value="private">나만 보기</option></select></label>
      <p className="field-note">원문 저장과 AI 분석은 별개예요. 모델 연결이 없거나 분석이 실패해도 원문은 보존돼요.</p>
      {controller.error && <p className="form-error" role="alert">{controller.error}</p>}
      <div className="modal-actions"><button className="button secondary" type="button" disabled={controller.busy} onClick={close}>취소</button><button className="button primary" disabled={controller.busy}>{controller.busy ? '회의 등록 중…' : '등록하고 분석 요청'}</button></div>
    </form>
  </dialog>;
}

function MeetingDetailView({ app, controller }: { app: DocTrail; controller: MeetingsController }) {
  const detail = controller.detail!;
  const { document: doc, meeting } = detail;
  const [editing, setEditing] = useState(false);
  const [showAi, setShowAi] = useState(false);
  const [linkForm, setLinkForm] = useState(false);
  const owner = doc.owner_id === app.state.auth?.user.id;
  const current = showAi ? meeting.ai_analysis : meeting.analysis;
  const pending = ['queued', 'running'].includes(meeting.analysis_status);
  const editable = owner && meeting.analysis_status === 'ready' && !!meeting.analysis;
  return <article className="meeting-detail" data-testid="meeting-detail">
    <div className="meeting-detail-nav"><button className="text-button" disabled={controller.busy} onClick={controller.back}>← 목록으로</button><div><AnalysisStatus value={meeting.analysis_status}/><span className="experimental-badge">실험 AI</span></div></div>
    <header className="meeting-detail-heading"><h2>{meeting.analysis?.meeting_title || doc.title}</h2><p>원문 v{doc.revision} · 분석 편집 v{meeting.version} · {doc.visibility === 'private' ? '나만 보기' : '워크스페이스'}</p><div className="meeting-detail-actions"><button className="button secondary small-button" onClick={() => void app.openDocument(doc.id)}><Icon name="file"/> 전체 원문</button>{editable && !showAi && <button className="button secondary small-button" disabled={controller.busy} onClick={() => setEditing(value => !value)}><Icon name="edit"/>{editing ? '편집 닫기' : '분석 편집'}</button>}{owner && !pending && <button className="text-button" disabled={controller.busy || editing} onClick={() => void controller.analyze()}>{meeting.analysis_status === 'ready' ? 'AI 재분석 요청' : 'AI 분석 다시 시도'}</button>}</div></header>
    {pending && <div className="analysis-banner" role="status"><span className="spinner"/><div><strong>{analysisLabels[meeting.analysis_status]}</strong><p>완료되면 자동 갱신돼요. 원문은 지금도 확인할 수 있어요.</p></div></div>}
    {meeting.analysis_status === 'failed' && <div className="source-warning"><strong>AI 분석을 완료하지 못했어요</strong><p>{meeting.analysis_error?.includes('not_configured') || meeting.analysis_error?.includes('disabled') ? 'AI 모델이 연결되지 않았어요.' : '모델 연결이나 입력 한도를 확인한 뒤 다시 시도해 주세요.'} 원문은 저장되어 있어요.</p>{meeting.analysis_error && <small>상태 코드: {meeting.analysis_error}</small>}</div>}
    {meeting.analysis_status === 'ready' && meeting.analysis_error && <div className="source-warning"><strong>최근 재분석을 완료하지 못했어요</strong><p>기존 분석과 사용자 수정본은 보존되어 있어요. 모델 연결을 확인한 뒤 AI 재분석을 다시 요청할 수 있어요.</p><small>상태 코드: {meeting.analysis_error}</small></div>}
    {meeting.analysis_status === 'stale' && <div className="source-warning"><strong>현재 원문과 분석 버전이 달라요</strong><p>아래 내용은 이전 원문의 결과예요. 결정과 작업을 사용하기 전에 재분석해 주세요.</p></div>}
    {meeting.ai_analysis && meeting.provenance === 'user_edited' && <div className="meeting-tabs" role="tablist" aria-label="분석 버전"><button role="tab" aria-selected={!showAi} disabled={editing} onClick={() => setShowAi(false)}>사용자 수정본</button><button role="tab" aria-selected={showAi} disabled={editing} onClick={() => setShowAi(true)}>AI 초안 · 읽기 전용</button></div>}
    <p className="analysis-disclosure">{showAi || meeting.provenance === 'ai' ? 'AI 분류와 원문 추출로 만든 초안이에요. 원문 인용과 함께 의미를 확인해 주세요.' : '사용자가 수정한 분석이에요. AI의 원본 결과와 구분해 보관해요.'} 원문에 없는 정보는 ‘확인 필요’로 표시해요.</p>
    {showAi && editable && meeting.ai_analysis && <button className="button secondary small-button" disabled={controller.busy} onClick={() => { void controller.save(meeting.ai_analysis!).then(saved => { if (saved) setShowAi(false); }); }}>이 AI 초안을 사용자 수정본으로 적용</button>}
    {editing && meeting.analysis ? <AnalysisEditor key={`${doc.id}:${meeting.version}`} value={meeting.analysis} content={doc.content} busy={controller.busy} save={async value => { if (await controller.save(value)) setEditing(false); }} cancel={() => setEditing(false)}/> : current ? <>
      <div className="meeting-metadata"><div><span>회의 날짜</span><strong>{current.meeting_date || '확인 필요'}</strong></div><div><span>참석자</span><strong>{current.participants.length ? current.participants.join(', ') : '확인 필요'}</strong></div><div className="meeting-purpose"><span>회의 목적</span><strong>{current.purpose || '확인 필요'}</strong></div></div>
      {!!current.metadata_evidence?.length && <details className="metadata-proof"><summary>기본 정보의 원문 근거</summary>{current.metadata_evidence.map((span, index) => <EvidenceButton key={index} span={span} detail={detail} app={app} label={{ meeting_title: '제목', meeting_date: '날짜', participants: '참석자', purpose: '목적', summary: '요약' }[span.field] || '근거'}/>)}</details>}
      <section className="analysis-section summary-section"><div className="analysis-section-heading"><Icon name="book"/><h3>{!showAi && meeting.provenance === 'user_edited' ? '수정한 요약' : 'AI 발췌 요약'}</h3></div><p className="summary-copy">{current.summary || '요약을 확인해 주세요.'}</p>{(current.summary_evidence || []).map((span, index) => <EvidenceButton key={index} span={span} detail={detail} app={app}/>)}</section>
      <div className="analysis-sections">{kinds.map(kind => <section className={`analysis-section ${kind}`} key={kind}><div className="analysis-section-heading"><Icon name={kind === 'action' ? 'check' : kind === 'unresolved' ? 'clock' : 'quote'}/><h3>{itemLabels[kind]}</h3><span className="count">{current.items.filter(item => item.type === kind).length}</span></div>{!current.items.some(item => item.type === kind) ? <p className="muted">추출된 {itemLabels[kind]}이 없어요.</p> : current.items.filter(item => item.type === kind).map(item => <div className="analysis-item" key={item.id} data-item={item.id}><div className="analysis-item-title"><p>{item.text}</p><span className={`status-badge ${item.status === 'confirmed' ? 'ready' : ''}`}>{statusLabels[item.status]}</span></div>{kind === 'action' && <div className="action-meta"><span>담당자 · {item.assignee || '확인 필요'}</span><span>마감일 · {item.due_date || '확인 필요'}</span><span>우선순위 · {item.priority ? { low: '낮음', medium: '보통', high: '높음' }[item.priority] : '확인 필요'}</span></div>}<EvidenceButton span={item} detail={detail} app={app}/></div>)}</section>)}</div>
    </> : !pending && <div className="empty-state"><h2>아직 분석 결과가 없어요</h2><p>전체 원문을 확인하거나 모델 연결 후 분석을 다시 시도하세요.</p></div>}
    {!editing && <section className="analysis-section decision-history"><div className="analysis-section-heading"><Icon name="clock"/><h3>결정 연결</h3>{editable && <button className="text-button" onClick={() => { setLinkForm(value => !value); void controller.loadTargets(); }}>{linkForm ? '연결 닫기' : '결정 연결하기'}</button>}</div><p className="muted">연결은 사용자가 양쪽 확정 결정과 변경 근거를 확인해 만들어요. 비슷한 논의가 자동으로 변경 관계가 되지는 않아요.</p>{linkForm && <DecisionLinkForm detail={detail} controller={controller} close={() => setLinkForm(false)}/>}
      {!controller.links.length && !linkForm && <p className="no-links">등록된 결정 연결이 없어요.</p>}
      {controller.links.map(link => <div className="decision-link" key={link.id}><div><span className="status-badge">사용자 연결 · {link.relation === 'supersedes' ? '이전 결정 변경' : '관련 결정'}</span><button className="text-button" disabled={controller.busy} onClick={() => void controller.open(link.source_id === doc.id ? link.target_id : link.source_id)}>{link.source_id === doc.id ? link.target_title || '연결된 회의' : link.source_title || '연결된 회의'} <Icon name="arrow"/></button></div><div className="decision-timeline"><p><time>{link.target_meeting_date || '날짜 확인 필요'}</time><strong>{link.target_title || '연결된 회의'}</strong><span>{link.target_item_text}</span></p><span className="timeline-arrow">{link.relation === 'supersedes' ? '↓ 사용자 확인 변경' : '↕ 사용자 확인 관련'}</span><p><time>{link.source_meeting_date || '날짜 확인 필요'}</time><strong>{link.source_title || '현재 회의'}</strong><span>{link.source_item_text}</span></p></div><button className="evidence-button" onClick={() => void app.openEvidence({ ...link, document_id: link.source_id, revision: link.source_revision })}><Icon name="quote"/><span className="evidence-preview">{link.quote}</span></button>{(owner && link.source_id === doc.id) && <button className="text-button danger" disabled={controller.busy} onClick={() => void controller.removeLink(link.id)}>연결 해제</button>}</div>)}
    </section>}
  </article>;
}

function AnalysisEditor({ value, content, busy, save, cancel }: { value: Analysis; content: string; busy: boolean; save: (value: Analysis) => Promise<void>; cancel: () => void }) {
  const [draft, setDraft] = useState<Analysis>(() => structuredClone(value));
  const patch = (change: Partial<Analysis>) => setDraft(current => ({ ...current, ...change }));
  const itemPatch = (id: string, change: Partial<MeetingItem>) => patch({ items: draft.items.map(item => item.id === id ? { ...item, ...change } : item) });
  return <form className="analysis-editor" onSubmit={event => { event.preventDefault(); void save(draft); }}><div className="editor-note"><strong>사용자 수정본 편집</strong><p>인용문과 원문은 유지돼요. 없는 정보는 비워 두고, 확정 여부는 근거를 확인한 뒤 바꾸세요.</p></div>
    <label>분석 제목<input value={draft.meeting_title || ''} maxLength={200} onChange={event => patch({ meeting_title: event.currentTarget.value || null })}/></label><div className="editor-grid"><label>회의 날짜<input type="date" value={draft.meeting_date || ''} onChange={event => patch({ meeting_date: event.currentTarget.value || null })}/></label><label>참석자 · 쉼표로 구분<input value={draft.participants.join(', ')} onChange={event => patch({ participants: event.currentTarget.value.split(',').map(value => value.trim()).filter(Boolean) })}/></label></div><label>회의 목적<input value={draft.purpose || ''} onChange={event => patch({ purpose: event.currentTarget.value || null })}/></label><label>회의 요약<textarea rows={4} value={draft.summary} onChange={event => patch({ summary: event.currentTarget.value })}/></label>
    <details className="metadata-proof"><summary>기본 정보의 근거 편집</summary><p className="field-note">비어 있던 기본 정보를 입력했다면 해당 정보의 원문 인용도 추가해 주세요.</p>{(['meeting_title', 'meeting_date', 'participants', 'purpose'] as const).map(field => <MetadataProof key={field} field={field} value={draft.metadata_evidence.find(item => item.field === field)?.quote || ''} content={content} change={span => patch({ metadata_evidence: [...draft.metadata_evidence.filter(item => item.field !== field), ...(span ? [{ field, ...span }] : [])] })}/>)}</details>
    {draft.items.map((item, index) => <fieldset className="item-editor" key={item.id}><legend>{itemLabels[item.type]} {index + 1}</legend><label>항목 내용<textarea rows={2} required value={item.text} onChange={event => itemPatch(item.id, { text: event.currentTarget.value })}/></label><div className="editor-grid"><label>분류<select value={item.type} onChange={event => { const type = event.currentTarget.value as ItemType; itemPatch(item.id, { type, status: 'needs_confirmation', ...(type !== 'action' ? { assignee: null, due_date: null, priority: null } : {}) }); }}>{kinds.map(kind => <option key={kind} value={kind}>{itemLabels[kind]}</option>)}</select></label><label>상태<select value={item.status} onChange={event => itemPatch(item.id, { status: event.currentTarget.value as ItemStatus })}>{(item.type === 'action' ? ['needs_confirmation', 'todo', 'doing', 'done'] : ['needs_confirmation', 'confirmed']).map(status => <option key={status} value={status}>{statusLabels[status as ItemStatus]}</option>)}</select></label></div>{item.type === 'action' && <div className="editor-grid action-fields"><label>담당자<input value={item.assignee || ''} placeholder="확인 필요" onChange={event => itemPatch(item.id, { assignee: event.currentTarget.value || null })}/></label><label>마감일<input type="date" value={item.due_date || ''} onChange={event => itemPatch(item.id, { due_date: event.currentTarget.value || null })}/></label><label>우선순위<select value={item.priority || ''} onChange={event => itemPatch(item.id, { priority: event.currentTarget.value as MeetingItem['priority'] || null })}><option value="">확인 필요</option><option value="low">낮음</option><option value="medium">보통</option><option value="high">높음</option></select></label></div>}<blockquote className="readonly-proof">{item.quote}</blockquote></fieldset>)}
    <div className="editor-actions"><button type="button" className="button secondary" onClick={cancel} disabled={busy}>취소</button><button className="button primary" disabled={busy}>{busy ? '저장 중…' : '사용자 수정본 저장'}</button></div>
  </form>;
}

function MetadataProof({ field, value, content, change }: { field: 'meeting_title' | 'meeting_date' | 'participants' | 'purpose'; value: string; content: string; change: (span: Span | null) => void }) {
  const [quote, setQuote] = useState(value);
  const index = quote ? content.indexOf(quote) : -1;
  return <label>{{ meeting_title: '제목 근거', meeting_date: '날짜 근거', participants: '참석자 근거', purpose: '목적 근거' }[field]}<textarea rows={2} value={quote} onChange={event => { const next = event.currentTarget.value; setQuote(next); const offset = content.indexOf(next); event.currentTarget.setCustomValidity(next && offset < 0 ? '원문과 정확히 일치하는 구절을 입력하세요.' : ''); if (!next) change(null); else if (offset >= 0) { const start_offset = Array.from(content.slice(0, offset)).length; change({ quote: next, start_offset, end_offset: start_offset + Array.from(next).length }); } }} onBlur={event => event.currentTarget.setCustomValidity(quote && index < 0 ? '원문과 정확히 일치하는 구절을 입력하세요.' : '')}/>{quote && index < 0 && <span className="form-error">원문에서 그대로 복사해 주세요.</span>}</label>;
}

function DecisionLinkForm({ detail, controller, close }: { detail: MeetingDetail; controller: MeetingsController; close: () => void }) {
  const [targetId, setTargetId] = useState('');
  const [quote, setQuote] = useState('');
  const [occurrence, setOccurrence] = useState(0);
  const target = controller.targets.find(value => value.document.id === targetId);
  const points = Array.from(detail.document.content);
  const quotePoints = Array.from(quote);
  const offsets: number[] = [];
  if (quote) for (let index = 0; index <= points.length - quotePoints.length; index++) if (points.slice(index, index + quotePoints.length).join('') === quote) offsets.push(index);
  const decisions = (analysis: Analysis | null) => analysis?.items.filter(item => item.type === 'decision' && item.status === 'confirmed') || [];
  const sourceDecisions = decisions(detail.meeting.analysis);
  const targetDecisions = decisions(target?.meeting.analysis || null);
  return <form className="link-form" onSubmit={event => { event.preventDefault(); if (!target || offsets[occurrence] === undefined) return; const data = new FormData(event.currentTarget); void controller.addLink(target, { source_item_id: String(data.get('source_item_id')), target_item_id: String(data.get('target_item_id')), relation: String(data.get('relation')) as 'related' | 'supersedes', quote, start_offset: offsets[occurrence], end_offset: offsets[occurrence] + quotePoints.length }).then(saved => { if (saved) close(); }); }}>
    <label>현재 회의의 확정 결정<select name="source_item_id" required><option value="">결정 선택</option>{sourceDecisions.map(item => <option key={item.id} value={item.id}>{item.text}</option>)}</select></label>
    <label>연결할 회의<select value={targetId} required onChange={event => setTargetId(event.currentTarget.value)}><option value="">접근 가능한 회의 선택</option>{controller.targets.filter(item => decisions(item.meeting.analysis).length).map(item => <option key={item.document.id} value={item.document.id}>{item.document.title} · {item.meeting.analysis?.meeting_date || '날짜 확인 필요'}</option>)}</select></label>
    <label>연결할 확정 결정<select key={targetId} name="target_item_id" required><option value="">결정 선택</option>{targetDecisions.map(item => <option key={item.id} value={item.id}>{item.text}</option>)}</select></label><label>관계<select name="relation"><option value="related">관련 결정</option><option value="supersedes">현재 결정이 연결한 이전 결정을 변경</option></select></label><label>연결 근거 · 현재 회의 원문에서 복사<textarea rows={3} required value={quote} onChange={event => { setQuote(event.currentTarget.value); setOccurrence(0); }}/></label>{quote && !offsets.length && <p className="form-error">현재 회의의 원문과 정확히 일치하는 구절을 입력하세요.</p>}{offsets.length > 1 && <label>반복되는 구절의 위치<select value={occurrence} onChange={event => setOccurrence(Number(event.currentTarget.value))}>{offsets.map((offset, index) => <option key={offset} value={index}>{index + 1}번째 · 문자 위치 {offset}</option>)}</select></label>}<p className="field-note">양쪽 원문과 분석 버전이 바뀌면 연결은 재확인이 필요해요. 인용문 일치가 변경 관계의 의미를 보증하지는 않아요.</p><div className="modal-actions"><button type="button" className="button secondary" onClick={close}>취소</button><button className="button primary" disabled={controller.busy || !sourceDecisions.length || !targetDecisions.length || !offsets.length}>확인한 결정 연결 저장</button></div>
  </form>;
}
