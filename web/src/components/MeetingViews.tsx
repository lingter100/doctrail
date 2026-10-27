import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { DocTrail } from '../useDocTrail';
import { useMeetings, type MeetingsController } from '../useMeetings';
import { analysisLabels, createSourceIndex, itemEditError, isGroundedSummary, itemLabels, statusLabels, summaryEditError, summaryFailureMessage, summaryProjection, summaryVersion, type Analysis, type ItemStatus, type ItemType, type MeetingDetail, type MeetingItem, type Span, type SummaryClaim } from '../meetings';
import { Icon } from './Icon';
import { SourceSpanPicker } from './SourceSpanPicker';
type PickSource = (change: (span: Span) => void) => void;

const kinds: ItemType[] = ['topic', 'proposal', 'decision', 'unresolved', 'action'];
function AnalysisStatus({ value }: { value: MeetingDetail['meeting']['analysis_status'] }) {
  return <span className={`status-badge analysis-status ${value}`}><i/>{analysisLabels[value]}</span>;
}
function EvidenceButton({ span, detail, app, controller, label = '원문 근거' }: { span: Span; detail: MeetingDetail; app: DocTrail; controller: MeetingsController; label?: string }) {
  return <button type="button" className="evidence-button" onClick={() => void app.openEvidence({ ...span, document_id: detail.document.id, revision: detail.meeting.source_revision }, controller.sourceOrigin(detail.document.id))}><Icon name="quote"/><span>{label}</span><span className="evidence-preview">{span.quote}</span><Icon name="arrow"/></button>;
}

export function MeetingWorkspace({ app, mode }: { app: DocTrail; mode: 'meetings' | 'actions' }) {
  const controller = useMeetings(app, mode);
  const [registration, setRegistration] = useState(false);
  const [filter, setFilter] = useState('');
  const [assignee, setAssignee] = useState('');
  const [status, setStatus] = useState('');
  const { detail, meetings, tasks } = controller;
  const activeList = controller.listState[mode === 'actions' ? 'tasks' : 'meetings'];
  const visible = meetings.filter(item => `${item.document.title} ${item.meeting.analysis?.meeting_title || ''} ${item.meeting.analysis?.summary || ''}`.toLocaleLowerCase().includes(filter.toLocaleLowerCase()));
  const actions = tasks.filter(item => (!assignee || (item.assignee || '').toLocaleLowerCase().includes(assignee.toLocaleLowerCase())) && (!status || item.status === status));
  return <div className="meeting-workspace">
    <div className="page-top"><div><span className="eyebrow">{mode === 'actions' ? 'TURN CONVERSATIONS INTO PROGRESS' : 'FROM CONVERSATION TO CLARITY'}</span><h1>{mode === 'actions' ? '후속 작업' : '회의'}</h1><p>{mode === 'actions' ? '회의에서 나온 할 일을 모으고, 담당자와 진행 상태를 확인하세요.' : '회의를 기록하고, 논의와 결정의 근거를 연결하세요.'}</p></div>{mode === 'meetings' && <button className="button primary" disabled={!app.workspace || controller.busy} onClick={() => app.requestLeave(() => { controller.clearError(); setRegistration(true); })}><Icon name="plus"/> 회의 등록</button>}</div>
    <ListLoadStatus controller={controller} mode={mode}/>
    {controller.error && !registration && <div className="error-banner" role="alert">{controller.error}<button className="text-button" disabled={controller.busy || controller.refreshing} onClick={() => void (detail ? controller.refresh() : controller.load())}>{controller.editing ? '서버 버전 확인' : '새로 불러오기'}</button></div>}
    {controller.notice && <p className="meeting-notice" role="status">{controller.notice}</p>}
    {!detail && activeList.loaded && <div className="list-refresh"><span role="status">{controller.loading ? '목록을 다시 확인하는 중이에요. 이전 조회 결과를 표시해요.' : activeList.error ? '이전 조회 결과 · 최신 상태 미확인' : ''}</span><button className="text-button" disabled={controller.loading || controller.busy} onClick={() => void controller.load()}>목록 새로고침</button></div>}
    {detail ? <MeetingDetailView key={detail.document.id} app={app} controller={controller}/> : !activeList.loaded ? controller.loading ? <div className="loading"><span className="spinner"/>{mode === 'actions' ? '후속 작업을' : '회의를'} 불러오는 중이에요…</div> : <div className="list-unavailable" role="status"><h2>목록을 확인하지 못했어요</h2><p>조회가 완료되지 않아 {mode === 'actions' ? '작업' : '회의'}의 유무와 개수를 알 수 없어요. 위의 다시 불러오기 버튼으로 재시도해 주세요.</p></div> : mode === 'actions' ? <>
      <div className="meeting-toolbar"><strong>{activeList.error ? '이전 조회 · ' : ''}{actions.length}개 작업</strong><div className="inline-filters"><label>담당자<input value={assignee} onChange={event => setAssignee(event.currentTarget.value)} placeholder="담당자 이름"/></label><label>진행 상태<select value={status} onChange={event => setStatus(event.currentTarget.value)}><option value="">모든 상태</option>{(['needs_confirmation', 'todo', 'doing', 'done'] as ItemStatus[]).map(value => <option key={value} value={value}>{statusLabels[value]}</option>)}</select></label></div></div>
      {!actions.length ? activeList.error ? <p className="list-unavailable">이전 조회 결과에는 표시할 작업이 없었어요. 현재 작업 목록은 확인되지 않았어요.</p> : <div className="empty-state"><Icon name="check" className="empty-icon"/><h2>표시할 후속 작업이 없어요</h2><p>분석이 완료된 회의의 작업이 여기에 모여요.<br/>없는 담당자와 마감일은 확인 필요로 남겨요.</p></div> : <div className="task-list">{actions.map(item => <button className="task-row" key={`${item.meeting_id}:${item.id}`} onClick={() => void controller.open(item.meeting_id)}><span className={`task-state ${item.status}`}><Icon name={item.status === 'done' ? 'check' : 'clock'}/></span><span className="task-copy"><strong>{item.text}</strong><small>{item.title}</small></span><span className="task-metadata"><span className="task-field task-assignee"><span className="task-field-label">담당자</span><span>{item.assignee || '확인 필요'}</span></span><span className="task-field task-due"><span className="task-field-label">마감일</span><span>{item.due_date || '확인 필요'}</span></span></span><span className="status-badge">{statusLabels[item.status]}</span><Icon name="chevron"/></button>)}</div>}
    </> : <>
      <div className="meeting-toolbar"><div><strong>{activeList.error ? '이전 조회한 회의' : '모든 회의'}</strong><span className="count">{visible.length}</span></div><label className="meeting-filter"><span className="sr-only">회의 제목 검색</span><Icon name="search"/><input value={filter} onChange={event => setFilter(event.currentTarget.value)} placeholder="회의 찾아보기"/></label></div>
      {!visible.length ? activeList.error ? <p className="list-unavailable">이전 조회 결과에는 표시할 회의가 없었어요. 현재 회의 목록은 확인되지 않았어요.</p> : <div className="empty-state meeting-empty"><Icon name="people" className="empty-icon"/><span className="eyebrow">MAKE EVERY MEETING COUNT</span><h2>{filter ? '조건에 맞는 회의가 없어요' : '대화가 지식이 되는 곳'}</h2><p>회의록을 붙여 넣거나 TXT·MD·텍스트 PDF를 올리세요.<br/>AI 초안, 직접 수정한 내용, 원문을 구분해서 보관해요.</p>{!filter && <button className="button secondary" onClick={() => setRegistration(true)}>첫 회의 등록하기 <Icon name="arrow"/></button>}</div> : <div className="meeting-grid">{visible.map(item => <button className="meeting-card" key={item.document.id} data-meeting={item.document.id} onClick={() => void controller.open(item.document.id)}><div className="meeting-card-top"><span className="meeting-symbol"><Icon name="people"/></span><AnalysisStatus value={item.meeting.analysis_status}/></div><h2>{item.meeting.analysis?.meeting_title || item.document.title}</h2><p>{item.meeting.analysis?.summary || '원문을 열고 AI 분석 상태를 확인하세요.'}</p><div className="meeting-card-meta"><span>{item.meeting.analysis?.meeting_date || '날짜 확인 필요'}</span><span>{item.meeting.analysis?.participants.length ? `${item.meeting.analysis.participants.length}명 참석` : '참석자 확인 필요'}</span></div><div className="meeting-card-foot"><span>{item.document.visibility === 'private' ? '나만 보기' : '워크스페이스'}</span><span>{item.meeting.provenance === 'user_edited' ? '사용자 수정' : 'AI 초안'} <Icon name="chevron"/></span></div></button>)}</div>}
    </>}
    {registration && <MeetingRegistration controller={controller} close={() => setRegistration(false)}/>}
  </div>;
}

function ListLoadStatus({ controller, mode }: { controller: MeetingsController; mode: 'meetings' | 'actions' }) {
  const { meetings, tasks } = controller.listState;
  if (!meetings.error && (mode !== 'actions' || !tasks.error)) return null;
  return <div className="error-banner list-load-error" role="alert" data-testid="meeting-list-error"><div>
    {meetings.error && <p><strong>회의 목록을 불러오지 못했어요.</strong> {meetings.loaded ? '이전 조회 결과를 보존했지만 최신 회의 상태는 미확인이에요.' : '회의 유무와 개수는 아직 확인되지 않았어요.'} {meetings.error}</p>}
    {mode === 'actions' && tasks.error && <p><strong>후속 작업을 불러오지 못했어요.</strong> {tasks.loaded ? '이전 작업 목록을 보존했지만 최신 작업 상태는 미확인이에요.' : '작업 유무와 개수는 아직 확인되지 않았어요.'} {tasks.error}</p>}
    {mode === 'actions' && meetings.error && tasks.loaded && !tasks.error && !controller.loading && <p>후속 작업 조회는 완료됐어요. 회의 분석 상태는 확인하지 못했어요.</p>}
    {mode === 'actions' && tasks.error && meetings.loaded && !meetings.error && <p>회의 목록 조회와 후속 작업 조회는 별개예요. 회의 조회 성공이 작업 목록의 최신 상태를 보장하지 않아요.</p>}
  </div><button className="text-button" disabled={controller.loading || controller.busy} onClick={() => void controller.load()}>{controller.loading ? '목록 확인 중…' : '목록 다시 불러오기'}</button></div>;
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
  const editing = controller.editing;
  const setEditing = controller.edit;
  const [showAi, setShowAi] = useState(false);
  const [linkForm, setLinkForm] = useState(false);
  const owner = doc.owner_id === app.state.auth?.user.id;
  const current = showAi ? meeting.ai_analysis : meeting.analysis;
  const pending = ['queued', 'running'].includes(meeting.analysis_status);
  const editable = owner && meeting.analysis_status === 'ready' && !!meeting.analysis && summaryVersion(meeting.analysis) !== null;
  return <article className="meeting-detail" data-testid="meeting-detail">
    <div className="meeting-detail-nav"><button className="text-button" disabled={controller.busy} onClick={controller.back}>← 목록으로</button><div><AnalysisStatus value={meeting.analysis_status}/><span className="experimental-badge">실험 AI</span></div></div>
    <header className="meeting-detail-heading"><h2>{meeting.analysis?.meeting_title || doc.title}</h2><p>원문 v{doc.revision} · 분석 편집 v{meeting.version} · {doc.visibility === 'private' ? '나만 보기' : '워크스페이스'}</p><div className="meeting-detail-actions"><button className="button secondary small-button" onClick={() => void app.openDocument(doc.id, undefined, 0, undefined, controller.sourceOrigin(doc.id))}><Icon name="file"/> 전체 원문</button>{editable && !showAi && <button className="button secondary small-button" disabled={controller.busy} onClick={() => editing ? app.requestLeave(() => setEditing(false)) : setEditing(true)}><Icon name="edit"/>{editing ? '편집 닫기' : '분석 편집'}</button>}{owner && !pending && <button className="text-button" disabled={controller.busy || editing} onClick={() => void controller.analyze()}>{meeting.analysis_status === 'ready' ? 'AI 재분석 요청' : 'AI 분석 다시 시도'}</button>}</div></header>
    {pending && <div className="analysis-banner" role="status"><span className="spinner"/><div><strong>{analysisLabels[meeting.analysis_status]}</strong><p>완료되면 자동 갱신돼요. 원문은 지금도 확인할 수 있어요.</p></div></div>}
    {meeting.analysis_status === 'failed' && <div className="source-warning"><strong>AI 분석을 완료하지 못했어요</strong><p>{summaryFailureMessage(meeting.analysis_error) || (meeting.analysis_error?.includes('not_configured') || meeting.analysis_error?.includes('disabled') ? 'AI 모델이 연결되지 않았어요.' : '모델 연결이나 입력 한도를 확인한 뒤 다시 시도해 주세요.')} 원문은 저장되어 있어요.</p></div>}
    {meeting.analysis_status === 'ready' && meeting.analysis_error && <div className="source-warning"><strong>최근 재분석을 완료하지 못했어요</strong><p>기존 분석과 사용자 수정본은 보존되어 있어요. {summaryFailureMessage(meeting.analysis_error) || '모델 연결을 확인한 뒤 AI 재분석을 다시 요청할 수 있어요.'}</p></div>}
    {meeting.analysis_status === 'stale' && <div className="source-warning"><strong>현재 원문과 분석 버전이 달라요</strong><p>아래 내용은 이전 원문의 결과예요. 결정과 작업을 사용하기 전에 재분석해 주세요.</p></div>}
    {meeting.ai_analysis && meeting.provenance === 'user_edited' && <div className="meeting-tabs" role="tablist" aria-label="분석 버전"><button role="tab" aria-selected={!showAi} disabled={editing} onClick={() => setShowAi(false)}>사용자 수정본</button><button role="tab" aria-selected={showAi} disabled={editing} onClick={() => setShowAi(true)}>AI 초안 · 읽기 전용</button></div>}
    <p className="analysis-disclosure">{showAi || meeting.provenance === 'ai' ? current && isGroundedSummary(current) ? 'AI가 원문을 바탕으로 압축한 요약 초안이에요. 각 문장에 연결된 모든 근거를 함께 확인해 주세요. AI 자체 검토가 내용의 정확성이나 완전성을 보증하지는 않아요.' : 'AI 분류와 원문 추출로 만든 초안이에요. 원문 인용과 함께 의미를 확인해 주세요.' : '사용자가 수정한 분석이에요. AI의 원본 결과와 구분해 보관해요.'} 원문에 없는 정보는 ‘확인 필요’로 표시해요.</p>
    {showAi && editable && meeting.ai_analysis && summaryVersion(meeting.ai_analysis) !== null && <button className="button secondary small-button" disabled={controller.busy} onClick={() => { void controller.save(meeting.ai_analysis!).then(saved => { if (saved) setShowAi(false); }); }}>이 AI 초안을 사용자 수정본으로 적용</button>}
    {editing && meeting.analysis ? <AnalysisEditor key={doc.id} detail={detail} app={app} controller={controller} cancel={() => setEditing(false)}/> : current ? <>
      <div className="meeting-metadata"><div><span>회의 날짜</span><strong>{current.meeting_date || '확인 필요'}</strong></div><div><span>참석자</span><strong>{current.participants.length ? current.participants.join(', ') : '확인 필요'}</strong></div><div className="meeting-purpose"><span>회의 목적</span><strong>{current.purpose || '확인 필요'}</strong></div></div>
      {!!current.metadata_evidence?.length && <details className="metadata-proof"><summary>기본 정보의 원문 근거</summary>{current.metadata_evidence.map((span, index) => <EvidenceButton key={index} span={span} detail={detail} app={app} controller={controller} label={{ meeting_title: '제목', meeting_date: '날짜', participants: '참석자', purpose: '목적', summary: '요약' }[span.field] || '근거'}/>)}</details>}
      <section className="analysis-section summary-section"><div className="analysis-section-heading"><Icon name="book"/><h3>{!showAi && meeting.provenance === 'user_edited' ? '수정한 요약' : isGroundedSummary(current) ? 'AI 요약 초안' : summaryVersion(current) === 1 ? 'AI 발췌 요약' : '회의 요약'}</h3></div><SummaryContent value={current} detail={detail} app={app} controller={controller}/></section>
      <div className="analysis-sections">{kinds.map(kind => <section className={`analysis-section ${kind}`} key={kind}><div className="analysis-section-heading"><Icon name={kind === 'action' ? 'check' : kind === 'unresolved' ? 'clock' : 'quote'}/><h3>{itemLabels[kind]}</h3><span className="count">{current.items.filter(item => item.type === kind).length}</span></div>{!current.items.some(item => item.type === kind) ? <p className="muted">추출된 {itemLabels[kind]}이 없어요.</p> : current.items.filter(item => item.type === kind).map(item => <div className="analysis-item" key={item.id} data-item={item.id}><div className="analysis-item-title"><p>{item.text}</p><span className={`status-badge ${item.status === 'confirmed' ? 'ready' : ''}`}>{statusLabels[item.status]}</span></div>{kind === 'action' && <div className="action-meta"><span>담당자 · {item.assignee || '확인 필요'}</span><span>마감일 · {item.due_date || '확인 필요'}</span><span>우선순위 · {item.priority ? { low: '낮음', medium: '보통', high: '높음' }[item.priority] : '확인 필요'}</span></div>}<EvidenceButton span={item} detail={detail} app={app} controller={controller}/></div>)}</section>)}</div>
    </> : !pending && <div className="empty-state"><h2>아직 분석 결과가 없어요</h2><p>전체 원문을 확인하거나 모델 연결 후 분석을 다시 시도하세요.</p></div>}
    {!editing && <section className="analysis-section decision-history"><div className="analysis-section-heading"><Icon name="clock"/><h3>결정 연결</h3>{editable && <button className="text-button" disabled={controller.busy} onClick={() => { setLinkForm(value => !value); void controller.loadTargets(); }}>{linkForm ? '연결 닫기' : '결정 연결하기'}</button>}</div><p className="muted">연결은 사용자가 양쪽 확정 결정과 변경 근거를 확인해 만들어요. 비슷한 논의가 자동으로 변경 관계가 되지는 않아요.</p>{linkForm && <DecisionLinkForm detail={detail} controller={controller} close={() => setLinkForm(false)}/>}
      {!controller.links.length && !linkForm && <p className="no-links">{controller.linksKnown ? '등록된 결정 연결이 없어요.' : '결정 연결 목록을 아직 확인하지 못했어요. 새로 불러와 확인해 주세요.'}</p>}
      {controller.links.map(link => <div className="decision-link" key={link.id}><div><span className="status-badge">사용자 연결 · {link.relation === 'supersedes' ? '이전 결정 변경' : '관련 결정'}</span><button className="text-button" disabled={controller.busy} onClick={() => void controller.open(link.source_id === doc.id ? link.target_id : link.source_id)}>{link.source_id === doc.id ? link.target_title || '연결된 회의' : link.source_title || '연결된 회의'} <Icon name="arrow"/></button></div><div className="decision-timeline"><p><time>{link.target_meeting_date || '날짜 확인 필요'}</time><strong>{link.target_title || '연결된 회의'}</strong><span>{link.target_item_text}</span></p><span className="timeline-arrow">{link.relation === 'supersedes' ? '↓ 사용자 확인 변경' : '↕ 사용자 확인 관련'}</span><p><time>{link.source_meeting_date || '날짜 확인 필요'}</time><strong>{link.source_title || '현재 회의'}</strong><span>{link.source_item_text}</span></p></div><button className="evidence-button" onClick={() => void app.openEvidence({ ...link, document_id: link.source_id, revision: link.source_revision }, controller.sourceOrigin(link.source_id))}><Icon name="quote"/><span className="evidence-preview">{link.quote}</span></button>{(owner && link.source_id === doc.id) && <button className="text-button danger" disabled={controller.busy} onClick={() => void controller.removeLink(link.id)}>연결 해제</button>}</div>)}
    </section>}
  </article>;
}

function SummaryContent({ value, detail, app, controller }: { value: Analysis; detail: MeetingDetail; app: DocTrail; controller: MeetingsController }) {
  if (summaryVersion(value) === null) return <p className="form-error" role="alert">요약 형식을 확인할 수 없어요. 원문을 확인하고 회의를 다시 불러와 주세요.</p>;
  if (!isGroundedSummary(value)) return <><p className="summary-copy">{value.summary || '요약을 확인해 주세요.'}</p>{(value.summary_evidence || []).map((span, index) => <EvidenceButton key={index} span={span} detail={detail} app={app} controller={controller}/>)}</>;
  return <div className="answer-claims" aria-label="문장별 요약과 근거">{value.summary_claims.map((claim, index) => <section key={claim.id} data-summary-claim={index}>
    <p className="summary-copy">{claim.text}</p><small className="field-note">문장 {index + 1} · 근거 {claim.citations.length}개를 함께 확인하세요.</small>
    {claim.citations.map((span, citation) => <EvidenceButton key={`${span.start_offset}:${span.end_offset}`} span={span} detail={detail} app={app} controller={controller} label={`문장 ${index + 1} 근거 ${citation + 1}`}/>)}
  </section>)}</div>;
}

function AnalysisEditor({ detail, app, controller, cancel }: { detail: MeetingDetail; app: DocTrail; controller: MeetingsController; cancel: () => void }) {
  const [basis, setBasis] = useState(detail);
  const [draft, setDraft] = useState<Analysis>(() => structuredClone(detail.meeting.analysis!));
  const content = basis.document.content;
  const sourceIndex = useMemo(() => createSourceIndex(content), [content]);
  const form = useRef<HTMLFormElement>(null);
  const [removed, setRemoved] = useState<{ item: MeetingItem; index: number }[]>([]);
  const [newKind, setNewKind] = useState<ItemType>('action');
  const [itemError, setItemError] = useState('');
  const [picker, setPicker] = useState<{ content: string; valid: () => boolean; opener: HTMLElement | null; change: (span: Span) => void } | null>(null);
  const [picking, setPicking] = useState(false);
  const pickerSerial = useRef(0);
  const [leave, setLeave] = useState<{ proceed: () => void } | null>(null);
  const leaveDialog = useRef<HTMLDialogElement>(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(basis.meeting.analysis);
  const guardState = useRef({ dirty, busy: controller.busy }); guardState.current = { dirty, busy: controller.busy };
  useLayoutEffect(() => app.registerLeaveGuard(proceed => {
    if (guardState.current.busy) return;
    if (guardState.current.dirty) setLeave({ proceed }); else proceed();
  }), []);
  useLayoutEffect(() => { if (leave) { const opener = document.activeElement; leaveDialog.current?.showModal(); return () => { if (opener instanceof HTMLElement && opener.isConnected) opener.focus(); }; } }, [leave]);
  useEffect(() => { if (!dirty) return; const prevent = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; }; window.addEventListener('beforeunload', prevent); return () => window.removeEventListener('beforeunload', prevent); }, [dirty]);
  useEffect(() => { if (app.state.logoutBusy || controller.reviewRequired) { pickerSerial.current++; setPicker(null); setPicking(false); } }, [app.state.logoutBusy, controller.reviewRequired]);
  useEffect(() => () => { pickerSerial.current++; }, []);
  const pick: PickSource = change => {
    const token = ++pickerSerial.current; const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null; setPicking(true);
    void controller.verifySource(basis).then(result => {
      if (token !== pickerSerial.current) return;
      setPicking(false); if (result) setPicker({ ...result, opener, change });
    });
  };
  const [focusTarget, setFocusTarget] = useState<{ id?: string; version: number } | null>(null);
  const focusItem = (id?: string) => setFocusTarget(current => ({ id, version: (current?.version || 0) + 1 }));
  useLayoutEffect(() => {
    if (!focusTarget) return;
    const target = focusTarget.id ? [...(form.current?.querySelectorAll<HTMLElement>('[data-edit-item]') || [])].find(el => el.dataset.editItem === focusTarget.id)?.querySelector('textarea') : form.current?.querySelector<HTMLButtonElement>('[data-add-item]'); target?.focus();
  }, [focusTarget]);
  const addItem = () => {
    if (draft.items.length >= 150) return;
    const item: MeetingItem = { id: crypto.randomUUID(), type: newKind, text: '', quote: '', start_offset: -1, end_offset: -1, status: 'needs_confirmation', assignee: null, due_date: null, priority: null };
    setDraft(current => ({ ...current, items: [...current.items, item] })); focusItem(item.id);
  };
  const deleteItem = (item: MeetingItem, index: number) => {
    setRemoved(current => [...current, { item, index }]); setDraft(current => ({ ...current, items: current.items.filter(value => value.id !== item.id) })); focusItem(draft.items[index + 1]?.id || draft.items[index - 1]?.id);
  };
  const undo = () => {
    const entry = removed.at(-1); if (!entry || draft.items.length >= 150) return;
    setDraft(current => { const items = [...current.items]; items.splice(Math.min(entry.index, items.length), 0, entry.item); return { ...current, items }; }); setRemoved(current => current.slice(0, -1)); focusItem(entry.item.id);
  };
  const originalItems = basis.meeting.analysis!.items;
  const added = draft.items.filter(item => !originalItems.some(old => old.id === item.id)).length;
  const deleted = originalItems.filter(old => !draft.items.some(item => old.id === item.id)).length;
  const changed = draft.items.filter(item => originalItems.some(old => old.id === item.id && JSON.stringify(old) !== JSON.stringify(item))).length;
  const affectedDecisions = originalItems.filter(old => old.type === 'decision' && old.status === 'confirmed' && JSON.stringify(draft.items.find(item => item.id === old.id)) !== JSON.stringify(old));
  const busy = controller.busy;
  const latest = controller.recovery?.detail;
  const canKeep = latest && latest.document.revision === basis.document.revision
    && latest.meeting.source_revision === basis.meeting.source_revision && latest.meeting.analysis_status === 'ready'
    && summaryVersion(latest.meeting.analysis) === summaryVersion(draft) && summaryVersion(draft) !== null;
  const blocked = controller.reviewRequired || controller.refreshing;
  const patch = (change: Partial<Pick<Analysis, 'meeting_title' | 'meeting_date' | 'participants' | 'purpose' | 'summary' | 'metadata_evidence' | 'items'>>) => setDraft(current => ({ ...current, ...change }));
  const itemPatch = (id: string, change: Partial<MeetingItem>) => patch({ items: draft.items.map(item => item.id === id ? { ...item, ...change, ...(item.type === 'decision' && item.status === 'confirmed' && ['text', 'type', 'quote', 'start_offset', 'end_offset'].some(key => Object.hasOwn(change, key) && change[key as keyof MeetingItem] !== item[key as keyof MeetingItem]) ? { status: 'needs_confirmation' as const } : {}) } : item) });
  const summaryError = summaryVersion(draft) === null ? '요약 형식을 확인할 수 없어 저장할 수 없어요.' : isGroundedSummary(draft) ? summaryEditError(draft.summary_claims, sourceIndex) : '';
  const changeClaims = (claims: SummaryClaim[]) => setDraft(current => isGroundedSummary(current) ? { ...current, ...summaryProjection(claims),
    // Keep the current input rows stable while editing; canonical citation order is applied on save.
    summary_claims: claims.map((claim, id) => ({ ...claim, id })) } : current);
  return <form ref={form} className="analysis-editor" onSubmit={event => { event.preventDefault(); const invalid = draft.items.find(item => itemEditError(item, sourceIndex)); if (invalid) { setItemError(itemEditError(invalid, sourceIndex)); focusItem(invalid.id); return; } setItemError(''); if (!busy && !picking && !picker && !app.state.logoutBusy && !blocked && !summaryError && summaryVersion(draft) === summaryVersion(basis.meeting.analysis)) void controller.save(isGroundedSummary(draft) ? { ...draft, ...summaryProjection(draft.summary_claims) } : draft, basis); }}><div className="editor-note"><strong>사용자 수정본 편집</strong><p>{isGroundedSummary(draft) ? '요약 문장과 그 문장을 뒷받침하는 근거를 함께 편집하세요. 원문은 바뀌지 않아요.' : '항목과 근거를 직접 보완할 수 있어요. 원문과 AI 초안은 보존돼요.'} 없는 정보는 비워 두고, 확정 여부는 근거를 확인한 뒤 바꾸세요.</p></div>
    {blocked && <section className="edit-recovery" aria-label="편집 충돌 복구"><h3>내 초안은 이 화면에 보관되어 있어요</h3><p>서버 내용을 확인해도 아래 입력은 바뀌지 않아요. 사용할 버전을 선택한 뒤에만 다시 저장할 수 있어요.</p>{controller.refreshing ? <p role="status">서버 버전을 확인하는 중이에요…</p> : latest ? <><p>내 초안의 기준: 원문 v{basis.document.revision} · 분석 v{basis.meeting.version}<br/>확인한 서버: 원문 v{latest.document.revision} · 분석 v{latest.meeting.version}</p><AnalysisComparison detail={latest} app={app} controller={controller}/>{!canKeep && <p className="form-error">원문, 분석 상태 또는 요약 형식이 바뀌었어요. 이전 근거와 항목을 그대로 저장할 수 없어요. 초안 내용을 따로 보관한 뒤 서버 버전에서 재분석 상태를 확인해 주세요.</p>}<div className="recovery-actions"><button type="button" className="button secondary" disabled={!canKeep || busy} onClick={() => { const next = controller.keepLocal(); if (next) setBasis(next); }}>내 초안 유지 · 저장은 나중에</button><button type="button" className="button secondary" disabled={busy} onClick={controller.useServer}>내 초안 버리고 서버 버전 사용</button><button type="button" className="text-button" disabled={busy} onClick={() => void controller.refresh()}>서버 버전 다시 확인</button></div></> : <button type="button" className="button secondary" disabled={busy} onClick={() => void controller.refresh()}>서버 버전 불러오기</button>}</section>}
    {busy && <p role="status" className="field-note">저장 중에는 내용을 수정할 수 없어요. 저장이 끝난 뒤 다시 편집해 주세요.</p>}
    <fieldset disabled={busy || picking || !!picker || app.state.logoutBusy} aria-label="분석 편집 내용" style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
    <label>분석 제목<input value={draft.meeting_title || ''} maxLength={200} onChange={event => patch({ meeting_title: event.currentTarget.value || null })}/></label><div className="editor-grid"><label>회의 날짜<input type="date" value={draft.meeting_date || ''} onChange={event => patch({ meeting_date: event.currentTarget.value || null })}/></label><label>참석자 · 쉼표로 구분<input value={draft.participants.join(', ')} onChange={event => patch({ participants: event.currentTarget.value.split(',').map(value => value.trim()).filter(Boolean) })}/></label></div><label>회의 목적<input value={draft.purpose || ''} onChange={event => patch({ purpose: event.currentTarget.value || null })}/></label>
    {isGroundedSummary(draft) ? <SummaryEditor claims={draft.summary_claims} content={content} pick={pick} change={changeClaims}/> : summaryVersion(draft) === 1 && <label>회의 요약<textarea rows={4} value={draft.summary} onChange={event => patch({ summary: event.currentTarget.value })}/></label>}
    {summaryError && <p className="form-error" role="status">{summaryError}</p>}
    <details className="metadata-proof"><summary>기본 정보의 근거 편집</summary><p className="field-note">비어 있던 기본 정보를 입력했다면 해당 정보의 원문 인용도 추가해 주세요.</p>{(['meeting_title', 'meeting_date', 'participants', 'purpose'] as const).map(field => <MetadataProof key={field} field={field} value={draft.metadata_evidence.find(item => item.field === field)?.quote || ''} pick={pick} change={span => patch({ metadata_evidence: [...draft.metadata_evidence.filter(item => item.field !== field), ...(span ? [{ field, ...span }] : [])] })}/>)}</details>
    {draft.items.map((item, index) => <fieldset className="item-editor" key={item.id} data-edit-item={item.id}><legend>{itemLabels[item.type]} {index + 1}</legend><label>항목 내용<textarea rows={2} required value={item.text} onChange={event => itemPatch(item.id, { text: event.currentTarget.value })}/></label><div className="editor-grid"><label>분류<select value={item.type} onChange={event => { const type = event.currentTarget.value as ItemType; itemPatch(item.id, { type, status: 'needs_confirmation', ...(type !== 'action' ? { assignee: null, due_date: null, priority: null } : {}) }); }}>{kinds.map(kind => <option key={kind} value={kind}>{itemLabels[kind]}</option>)}</select></label><label>상태<select value={item.status} onChange={event => itemPatch(item.id, { status: event.currentTarget.value as ItemStatus })}>{(item.type === 'action' ? ['needs_confirmation', 'todo', 'doing', 'done'] : ['needs_confirmation', 'confirmed']).map(status => <option key={status} value={status}>{statusLabels[status as ItemStatus]}</option>)}</select></label></div>{item.type === 'action' && <div className="editor-grid action-fields"><label>담당자<input value={item.assignee || ''} placeholder="확인 필요" onChange={event => itemPatch(item.id, { assignee: event.currentTarget.value || null })}/></label><label>마감일<input type="date" value={item.due_date || ''} onChange={event => itemPatch(item.id, { due_date: event.currentTarget.value || null })}/></label><label>우선순위<select value={item.priority || ''} onChange={event => itemPatch(item.id, { priority: event.currentTarget.value as MeetingItem['priority'] || null })}><option value="">확인 필요</option><option value="low">낮음</option><option value="medium">보통</option><option value="high">높음</option></select></label></div>}<blockquote className="readonly-proof">{item.quote || '아직 원문 근거를 선택하지 않았어요.'}</blockquote><div className="recovery-actions"><button type="button" className="text-button" onClick={() => pick(span => itemPatch(item.id, span))}>항목 근거 선택</button><button type="button" className="text-button danger" onClick={() => deleteItem(item, index)}>항목 삭제</button></div></fieldset>)}
    {!draft.items.length && <p className="field-note">항목이 없어요. 빠진 논의나 후속 작업을 추가할 수 있어요.</p>}
    <div className="manual-add"><label>새 항목 분류<select value={newKind} onChange={event => setNewKind(event.currentTarget.value as ItemType)}>{kinds.map(kind => <option key={kind} value={kind}>{itemLabels[kind]}</option>)}</select></label><button data-add-item type="button" className="button secondary" disabled={draft.items.length >= 150} onClick={addItem}>항목 추가</button><span>{draft.items.length}/150개</span><button type="button" className="text-button" disabled={!removed.length || draft.items.length >= 150} onClick={undo}>삭제 취소</button></div>
    </fieldset>
    <p role="status" className="field-note">{dirty ? '미저장 변경 있음' : '저장된 내용과 같아요'} · 항목 추가 {added}개 / 삭제 {deleted}개 / 수정 {changed}개</p>
    {!!affectedDecisions.length && <p className="source-warning">확정 결정 {affectedDecisions.length}개가 변경되거나 삭제돼요. {controller.linksKnown ? '현재 볼 수 있는 연결 ' + (controller.recovery?.links ?? controller.links).length + '개를 확인했어요.' : '연결 목록을 확인하지 못해 영향 개수를 단정할 수 없어요.'} 변경된 결정의 연결은 저장 후 다시 확인해야 해요. 자동 재연결하지 않아요.</p>}
    {itemError && <p role="alert" className="form-error">{itemError}</p>}{picking && <p role="status">현재 원문과 접근 권한을 확인하는 중이에요…</p>}
    {picker && <SourceSpanPicker opener={picker.opener} index={sourceIndex} close={() => setPicker(null)} apply={span => { if (picker.valid()) picker.change(span); setPicker(null); }}/ >}
    {leave && <dialog ref={leaveDialog} aria-label="미저장 변경 확인" onCancel={event => { event.preventDefault(); setLeave(null); }}><h2>수정한 내용을 버릴까요?</h2><p>저장하지 않은 항목과 근거 변경이 사라져요.</p><div className="modal-actions"><button type="button" className="button secondary" autoFocus onClick={() => setLeave(null)}>계속 편집</button><button type="button" className="button primary" onClick={() => { const proceed = leave.proceed; setLeave(null); proceed(); }}>버리고 이동</button></div></dialog>}
    <div className="editor-actions"><button type="button" className="button secondary" onClick={() => app.requestLeave(cancel)} disabled={busy}>취소</button><button className="button primary" disabled={busy || picking || !!picker || app.state.logoutBusy || blocked || !!summaryError}>{busy ? '저장 중…' : '사용자 수정본 저장'}</button></div>
  </form>;
}

function AnalysisComparison({ detail, app, controller }: { detail: MeetingDetail; app: DocTrail; controller: MeetingsController }) {
  const value = detail.meeting.analysis;
  return <details className="server-analysis" open><summary>서버에 저장된 분석 · 읽기 전용</summary>{value ? <><dl><dt>제목</dt><dd>{value.meeting_title || '확인 필요'}</dd><dt>날짜 / 참석자</dt><dd>{value.meeting_date || '확인 필요'} / {value.participants.join(', ') || '확인 필요'}</dd><dt>목적</dt><dd>{value.purpose || '확인 필요'}</dd><dt>요약</dt><dd>{summaryVersion(value) === 1 ? value.summary : <SummaryContent value={value} detail={detail} app={app} controller={controller}/>}</dd></dl>{value.items.map(item => <div className="server-item" key={item.id}><strong>{itemLabels[item.type]} · {statusLabels[item.status]}</strong><p>{item.text}</p>{item.type === 'action' && <p>담당자: {item.assignee || '확인 필요'} · 마감일: {item.due_date || '확인 필요'} · 우선순위: {item.priority ? { low: '낮음', medium: '보통', high: '높음' }[item.priority] : '확인 필요'}</p>}<blockquote className="readonly-proof">{item.quote}</blockquote></div>)}<details><summary>서버 기본 정보와 요약의 근거</summary>{[...value.metadata_evidence, ...(!isGroundedSummary(value) ? value.summary_evidence || [] : [])].map((span, index) => <blockquote className="readonly-proof" key={index}>{span.quote}</blockquote>)}</details></> : <p>서버에 분석 결과가 없어요.</p>}</details>;
}

function SummaryEditor({ claims, content, pick, change }: { claims: SummaryClaim[]; content: string; pick: PickSource; change: (claims: SummaryClaim[]) => void }) {
  const patch = (index: number, value: Partial<SummaryClaim>) => change(claims.map((claim, i) => i === index ? { ...claim, ...value } : claim));
  const move = (index: number, direction: number) => { const next = [...claims]; [next[index], next[index + direction]] = [next[index + direction], next[index]]; change(next); };
  return <section aria-label="문장별 요약 편집">
    <h3>문장과 근거</h3><p className="field-note">문장 1~6개 · 문장마다 240자 이내 · 전체 1,200자 이내. 한 문장에 필요한 근거 1~4개를 함께 연결하세요. 저장하면 순서와 요약 미리보기가 자동 반영돼요.</p>
    <details className="metadata-proof"><summary>요약 근거로 쓸 원문 보기</summary><p className="summary-copy">{content}</p></details>
    {claims.map((claim, index) => <fieldset className="item-editor" key={index} data-summary-editor={index}><legend>요약 문장 {index + 1}</legend>
      <label>문장 {index + 1} 내용<textarea rows={3} required value={claim.text} onChange={event => patch(index, { text: event.currentTarget.value })}/></label>
      <p className="field-note">{Array.from(claim.text).length}/240자 · 연결된 근거 {claim.citations.length}/4개</p>
      {claim.citations.map((citation, citationIndex) => <SummaryCitationEditor key={citationIndex} span={citation} pick={pick} number={citationIndex + 1}
        change={span => patch(index, { citations: claim.citations.map((old, i) => i === citationIndex ? span : old) })}
        remove={() => patch(index, { citations: claim.citations.filter((_, i) => i !== citationIndex) })} canRemove={claim.citations.length > 1}/>)}
      <div className="recovery-actions"><button type="button" className="text-button" disabled={claim.citations.length >= 4} onClick={() => patch(index, { citations: [...claim.citations, { quote: '', start_offset: -1, end_offset: -1 }] })}>근거 추가</button>
        <button type="button" className="text-button" aria-label={`문장 ${index + 1} 위로`} disabled={index === 0} onClick={() => move(index, -1)}>위로</button><button type="button" className="text-button" aria-label={`문장 ${index + 1} 아래로`} disabled={index === claims.length - 1} onClick={() => move(index, 1)}>아래로</button>
        <button type="button" className="text-button danger" aria-label={`문장 ${index + 1} 삭제`} disabled={claims.length <= 1} onClick={() => change(claims.filter((_, i) => i !== index))}>문장 삭제</button></div>
    </fieldset>)}
    <div className="editor-actions"><button type="button" className="button secondary" disabled={claims.length >= 6} onClick={() => change([...claims, { id: claims.length, text: '', citations: [{ quote: '', start_offset: -1, end_offset: -1 }] }])}><Icon name="plus"/> 요약 문장 추가</button></div>
  </section>;
}

function SummaryCitationEditor({ span, pick, number, change, remove, canRemove }: { span: Span; pick: PickSource; number: number; change: (span: Span) => void; remove: () => void; canRemove: boolean }) {
  return <div className="server-item" data-summary-citation-editor={number - 1}><label>근거 {number} 인용문<textarea rows={2} readOnly value={span.quote}/></label><button type="button" className="text-button" onClick={() => pick(change)}>근거 {number} 원문 위치 선택</button><button type="button" className="text-button danger" disabled={!canRemove} onClick={remove}>근거 {number} 삭제</button></div>;
}
function MetadataProof({ field, value, pick, change }: { field: 'meeting_title' | 'meeting_date' | 'participants' | 'purpose'; value: string; pick: PickSource; change: (span: Span | null) => void }) {
  const label = { meeting_title: '제목 근거', meeting_date: '날짜 근거', participants: '참석자 근거', purpose: '목적 근거' }[field];
  return <div><label>{label}<textarea rows={2} readOnly value={value}/></label><button type="button" className="text-button" onClick={() => pick(change)}>{label} 선택</button><button type="button" className="text-button" disabled={!value} onClick={() => change(null)}>{label} 지우기</button></div>;
}

function DecisionLinkForm({ detail, controller, close }: { detail: MeetingDetail; controller: MeetingsController; close: () => void }) {
  const [targetId, setTargetId] = useState('');
  const [quote, setQuote] = useState('');
  const [occurrence, setOccurrence] = useState(-1);
  useLayoutEffect(() => { setTargetId(''); }, [controller.targetSelectionVersion]);
  const target = controller.targets.find(value => value.document.id === targetId);
  const points = Array.from(detail.document.content);
  const quotePoints = Array.from(quote);
  const offsets: number[] = [];
  if (quote) for (let index = 0; index <= points.length - quotePoints.length; index++) if (points.slice(index, index + quotePoints.length).join('') === quote) offsets.push(index);
  const chosen = offsets.length === 1 ? offsets[0] : offsets[occurrence];
  const decisions = (analysis: Analysis | null) => analysis?.items.filter(item => item.type === 'decision' && item.status === 'confirmed') || [];
  const sourceDecisions = decisions(detail.meeting.analysis);
  const targetDecisions = decisions(target?.meeting.analysis || null);
  return <form className="link-form" onSubmit={event => { event.preventDefault(); if (controller.busy || controller.refreshing || controller.linkReviewRequired || !target || chosen === undefined) return; const data = new FormData(event.currentTarget); void controller.addLink(target, { source_item_id: String(data.get('source_item_id')), target_item_id: String(data.get('target_item_id')), relation: String(data.get('relation')) as 'related' | 'supersedes', quote, start_offset: chosen, end_offset: chosen + quotePoints.length }).then(saved => { if (saved) close(); }); }}>
    {controller.linkReviewRequired && <p role="status">양쪽 회의의 최신 버전을 불러온 뒤 결정을 다시 확인해 주세요. 입력한 근거는 유지돼요.</p>}
    {controller.busy && <p role="status" className="field-note">연결 저장 중에는 내용을 수정하거나 닫을 수 없어요. 완료 후 새 연결을 작성해 주세요.</p>}
    <fieldset disabled={controller.busy} aria-label="결정 연결 내용" style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
    <label>현재 회의의 확정 결정<select key={controller.linkSelectionVersion} name="source_item_id" required><option value="">결정 선택</option>{sourceDecisions.map(item => <option key={item.id} value={item.id}>{item.text}</option>)}</select></label>
    <label>연결할 회의<select value={targetId} required onChange={event => setTargetId(event.currentTarget.value)}><option value="">접근 가능한 회의 선택</option>{controller.targets.filter(item => decisions(item.meeting.analysis).length).map(item => <option key={item.document.id} value={item.document.id}>{item.document.title} · {item.meeting.analysis?.meeting_date || '날짜 확인 필요'}</option>)}</select></label>
    <label>연결할 확정 결정<select key={`${targetId}:${controller.linkSelectionVersion}`} name="target_item_id" required><option value="">결정 선택</option>{targetDecisions.map(item => <option key={item.id} value={item.id}>{item.text}</option>)}</select></label><label>관계<select name="relation"><option value="related">관련 결정</option><option value="supersedes">현재 결정이 연결한 이전 결정을 변경</option></select></label><label>연결 근거 · 현재 회의 원문에서 복사<textarea rows={3} required value={quote} onChange={event => { setQuote(event.currentTarget.value); setOccurrence(-1); }}/></label>{quote && !offsets.length && <p className="form-error">현재 회의의 원문과 정확히 일치하는 구절을 입력하세요.</p>}{offsets.length > 1 && <label>반복되는 구절의 위치<select value={occurrence} onChange={event => setOccurrence(Number(event.currentTarget.value))}><option value={-1}>문맥을 확인하고 위치 선택</option>{offsets.map((offset, index) => <option key={offset} value={index}>{index + 1}번째 · {points.slice(Math.max(0, offset - 25), offset + quotePoints.length + 25).join('')}</option>)}</select></label>}
    </fieldset>
    <p className="field-note">양쪽 원문과 분석 버전이 바뀌면 연결은 재확인이 필요해요. 인용문 일치가 변경 관계의 의미를 보증하지는 않아요.</p><div className="modal-actions"><button type="button" className="button secondary" disabled={controller.busy} onClick={close}>취소</button><button className="button primary" disabled={controller.busy || controller.refreshing || controller.linkReviewRequired || detail.meeting.analysis_status !== 'ready' || detail.meeting.source_revision !== detail.document.revision || !sourceDecisions.length || !targetDecisions.length || chosen === undefined}>확인한 결정 연결 저장</button></div>
  </form>;
}
