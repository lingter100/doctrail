import './style.css';

type User = { id: string; email: string; name: string };
type Workspace = { id: string; name: string; role: string };
type Doc = { id: string; workspace_id: string; title: string; filename: string; media_type: string; visibility: 'workspace' | 'private'; owner_id: string; status: string; error: string | null; revision: number; chunk_count: number; created_at: string; updated_at: string };
type Chunk = { id: string; text: string; page: number | null; start_offset: number; end_offset: number; ordinal: number };
type Detail = Doc & { content: string; chunks: Chunk[] };
type Hit = { document_id: string; title: string; filename: string; revision: number; chunk_id: string; text: string; page: number | null; score: number };
type Search = { query: string; method: string; elapsed_ms: number; search_id: string; results: Hit[] };
type History = { id: string; query: string; created_at: string; result_count: number };
type Auth = { user: User; workspaces: Workspace[] };
const app = document.querySelector<HTMLDivElement>('#app')!;
const dialog = document.querySelector<HTMLDialogElement>('#dialog')!;
const toastBox = document.querySelector<HTMLDivElement>('#toast')!;
let user: User | null = null;
let workspaces: Workspace[] = [];
let workspace: Workspace | undefined;
let documents: Doc[] = [];
let history: History[] = [];
let currentView: 'library' | 'search' | 'history' = 'library';
let search: Search | null = null;
let selected: Detail | null = null;
let selectedHit: Hit | null = null;
let selectedIndex = 0;
let epoch = 0;
let detailRequest = 0;
let searchRequest = 0;
let loading = false;
let pageError = '';
let authMode: 'login' | 'register' = 'register';
let filter = '';
let modalPreviousFocus: HTMLElement | null = null;
let toastTimer: ReturnType<typeof setTimeout>;
const icons: Record<string, string> = {
  logo: '<path d="M5 3h9l5 5v13H5z"/><path d="M14 3v6h5M9 13h6M9 17h4"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
  book: '<path d="M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-3H4zM13 7a3 3 0 0 1 3-3h4v14h-3a4 4 0 0 0-4 3"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  file: '<path d="M6 3h8l5 5v13H6zM14 3v6h5M10 13h5M10 17h5"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  people: '<circle cx="9" cy="8" r="3"/><path d="M3 20v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6m2 3a5 5 0 0 1 3 4v2"/>',
  exit: '<path d="M10 4H4v16h6m4-12 4 4-4 4M8 12h12"/>',
  edit: '<path d="m15 4 5 5M4 20l5-1L21 7l-5-5L4 14z"/>',
  chevron: '<path d="m8 5 7 7-7 7"/>',
  quote: '<path d="M5 11h5v7H3v-7c0-4 2-6 6-6M16 11h5v7h-7v-7c0-4 2-6 6-6"/>',
};
const icon = (name: string, cls = '') => `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.file}</svg>`;
const esc = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const date = (value: string) => new Intl.DateTimeFormat('ko-KR', { month: 'short', day: 'numeric' }).format(new Date(value));
const fullDate = (value: string) => new Date(value).toLocaleString('ko-KR');
const qs = <T extends Element = HTMLElement>(selector: string, root: ParentNode = app) => root.querySelector<T>(selector)!;
const isOwner = (doc: Doc) => doc.owner_id === user?.id;
const statusLabel = (doc: Doc) => doc.status === 'ready' ? '검색 가능' : doc.status === 'failed' ? '처리 실패' : '처리 중';
const visibilityLabel = (doc: Doc) => doc.visibility === 'private' ? '나만 보기' : '워크스페이스';

class ApiError extends Error { constructor(public status: number, public code: string, public requestId?: string) { super(code); } }
function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return '서버에 연결하지 못했어요. 연결 상태를 확인한 뒤 다시 시도해 주세요.';
  const code = error.code.toLowerCase();
  if (error.status === 401) return '이메일 또는 비밀번호를 확인해 주세요. 세션이 만료되었다면 다시 로그인해 주세요.';
  if (error.status === 403) return '이 작업에 대한 권한이 없어요.';
  if (error.status === 404) return '문서를 찾을 수 없거나 접근 권한이 변경되었어요.';
  if (error.status === 409) return '이미 등록된 정보예요. 이메일과 현재 상태를 확인해 주세요.';
  if (error.status === 413 || code.includes('size') || code.includes('large')) return '파일은 5MB 이하로 올려 주세요.';
  if (code.includes('member') || code.includes('user_not_found')) return '먼저 가입한 사용자의 이메일을 입력해 주세요.';
  if (error.status === 422 || error.status === 400) return '입력 내용을 확인해 주세요. UTF-8 TXT·MD 또는 텍스트 PDF를 지원해요.';
  return `요청을 완료하지 못했어요. 잠시 후 다시 시도해 주세요.${error.requestId ? ` (요청 ${error.requestId})` : ''}`;
}
async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(`/api${path}`, { ...options, headers, credentials: 'include' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 401 && user && !path.startsWith('/auth/login')) {
      clearState(); user = null; workspace = undefined; workspaces = []; dialog.close(); authMode = 'login'; renderAuth();
      toast('로그인이 만료되었어요. 다시 로그인해 주세요.');
    }
    throw new ApiError(response.status, typeof body.detail === 'string' ? body.detail : 'invalid_request', response.headers.get('x-request-id') || undefined);
  }
  return response.status === 204 ? undefined as T : response.json();
}
function toast(message: string) {
  clearTimeout(toastTimer); toastBox.textContent = message; toastBox.classList.add('visible');
  toastTimer = setTimeout(() => toastBox.classList.remove('visible'), 4500);
}
function clearState() { epoch++; detailRequest++; searchRequest++; documents = []; history = []; search = null; selected = null; selectedHit = null; filter = ''; loading = false; pageError = ''; }
function showModal(html: string) { modalPreviousFocus = document.activeElement as HTMLElement; dialog.innerHTML = html; dialog.showModal(); dialog.querySelector('[data-close]')?.addEventListener('click', () => dialog.close()); }
dialog.addEventListener('close', () => { dialog.innerHTML = ''; modalPreviousFocus?.focus(); });
dialog.addEventListener('click', event => { if (event.target === dialog) { const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close(); } });
function modalHead(title: string, description: string) { return `<header class="modal-head"><div><h2 id="dialog-title">${title}</h2><p>${description}</p></div><button class="icon-button" data-close aria-label="닫기">${icon('close')}</button></header>`; }
function formError(form: HTMLFormElement, error: unknown) { qs('.form-error', form).textContent = errorMessage(error); }

function renderAuth() {
  const register = authMode === 'register';
  app.innerHTML = `<main class="auth-layout"><section class="auth-story"><a class="brand" href="/">${icon('logo')}<span>DocTrail</span></a><div class="auth-story-body"><span class="eyebrow">YOUR DOCUMENTS, CONNECTED.</span><h1>찾던 정보에서<br>확실한 근거까지.</h1><p>흩어진 문서를 한곳에 모으고,<br>검색 결과를 원문에서 직접 확인하세요.</p><div class="story-visual" aria-hidden="true"><div class="visual-sheet"><span class="visual-file">${icon('file')} 프로젝트 문서</span><i></i><i></i><i class="highlight"></i><i></i><i class="short"></i></div><div class="visual-citation">${icon('quote')} 원문으로 이어지는 검색<span>${icon('check')}</span></div><div class="visual-dot one"></div><div class="visual-dot two"></div></div><div class="story-steps"><span>01 &nbsp; 문서 모으기</span><span>02 &nbsp; 키워드 찾기</span><span>03 &nbsp; 근거 확인</span></div></div><small>내 문서의 맥락을 잃지 않는 검색 공간</small></section><section class="auth-form-area"><div class="auth-card"><span class="eyebrow">START YOUR TRAIL</span><h2>${register ? '나만의 문서 공간 만들기' : '다시 만나서 반가워요'}</h2><p class="muted">${register ? '첫 번째 문서부터, 차근차근 시작하세요.' : '문서와 검색 기록이 기다리고 있어요.'}</p><div class="auth-tabs" role="tablist" aria-label="계정"><button role="tab" aria-selected="${register}" data-auth="register">새로 시작하기</button><button role="tab" aria-selected="${!register}" data-auth="login">로그인</button></div><form id="auth-form">${register ? '<label>이름<input name="name" autocomplete="name" maxlength="80" required placeholder="어떻게 불러 드릴까요?" /></label>' : ''}<label>이메일<input name="email" type="email" autocomplete="email" required placeholder="you@example.com" maxlength="254" /></label><label>비밀번호<input name="password" type="password" autocomplete="${register ? 'new-password' : 'current-password'}" minlength="${register ? '10' : '1'}" required placeholder="${register ? '10자 이상 입력해 주세요' : '비밀번호를 입력해 주세요'}" /></label>${register ? '<label>워크스페이스 이름<input name="workspace_name" required maxlength="100" placeholder="예: 나의 리서치 노트" /></label>' : ''}<p class="form-error" role="alert"></p><button class="button primary auth-submit" type="submit">${register ? '워크스페이스 만들기' : '로그인'}${icon('arrow')}</button></form><p class="auth-note">${icon('lock')} 업로드한 문서는 설정한 공개 범위 안에서 검색됩니다.</p></div><footer class="auth-footer">DocTrail <span>문서에서 근거까지</span></footer></section></main>`;
  app.querySelectorAll<HTMLButtonElement>('[data-auth]').forEach(button => button.onclick = () => { authMode = button.dataset.auth as typeof authMode; renderAuth(); });
  qs<HTMLFormElement>('#auth-form').onsubmit = async event => {
    event.preventDefault(); const form = event.currentTarget as HTMLFormElement; const button = qs<HTMLButtonElement>('[type=submit]', form); button.disabled = true; qs('.form-error', form).textContent = '';
    try { const data = Object.fromEntries(new FormData(form)); const result = await api<Auth>(`/auth/${authMode}`, { method: 'POST', body: JSON.stringify(data) }); user = result.user; workspaces = result.workspaces; workspace = workspaces[0]; clearState(); currentView = 'library'; await loadWorkspace(); }
    catch (error) { if (form.isConnected) { formError(form, error); button.disabled = false; } }
  };
}

async function loadWorkspace() {
  const stamp = epoch; const id = workspace?.id; loading = true; pageError = ''; render();
  if (!id) { loading = false; render(); return; }
  try { const [docs, past] = await Promise.all([api<{ items: Doc[] }>(`/workspaces/${id}/documents`), api<{ items: History[] }>(`/workspaces/${id}/history`)]); if (stamp !== epoch) return; documents = docs.items; history = past.items; }
  catch (error) { if (stamp !== epoch) return; pageError = errorMessage(error); }
  if (stamp === epoch) { loading = false; render(); }
}

function render() {
  if (!user) { renderAuth(); return; }
  const title = currentView === 'library' ? '문서 라이브러리' : currentView === 'history' ? '검색 기록' : '문서 검색';
  app.innerHTML = `<div class="shell ${selected ? 'with-source' : ''}"><aside class="sidebar"><a class="brand" href="/">${icon('logo')}<span>DocTrail</span></a><div class="workspace-switch"><label class="sr-only" for="workspace-select">워크스페이스 선택</label><span class="workspace-avatar">${esc(workspace?.name.slice(0, 1) || 'D')}</span><select id="workspace-select">${workspaces.map(w => `<option value="${esc(w.id)}" ${w.id === workspace?.id ? 'selected' : ''}>${esc(w.name)}</option>`).join('')}</select></div><button class="sidebar-search" id="focus-search">${icon('search')}<span>문서 검색</span><kbd>/</kbd></button><span class="nav-label">WORKSPACE</span><nav aria-label="주 메뉴"><button data-view="library" class="nav-item ${currentView === 'library' ? 'active' : ''}">${icon('book')}<span>문서 라이브러리</span><span class="nav-count">${documents.length}</span></button><button data-view="history" class="nav-item ${currentView === 'history' ? 'active' : ''}">${icon('clock')}<span>검색 기록</span></button></nav><div class="sidebar-bottom"><div class="workspace-note"><span class="status-dot"></span> 키워드 검색 · BM25<p>답변보다 먼저, 원문 근거를.</p></div><button class="nav-item small" id="new-workspace">${icon('plus')} 새 워크스페이스</button>${workspace?.role === 'owner' ? `<button class="nav-item small" id="members">${icon('people')} 멤버 추가</button>` : ''}<div class="account"><span class="user-avatar">${esc(user.name.slice(0, 1))}</span><div><strong>${esc(user.name)}</strong><span>${esc(user.email)}</span></div><button id="logout" class="icon-button" aria-label="로그아웃" title="로그아웃">${icon('exit')}</button></div></div></aside><div class="main-layout"><header class="topbar"><div class="breadcrumb"><span>${esc(workspace?.name || '워크스페이스')}</span>${icon('chevron')}<strong>${title}</strong></div><span class="private-note">${icon('lock')} 권한 기반 검색</span></header><main class="main-content"><div class="page-top"><div><span class="eyebrow">${currentView === 'library' ? 'YOUR KNOWLEDGE, IN ONE PLACE' : currentView === 'history' ? 'PICK UP WHERE YOU LEFT OFF' : 'FOLLOW THE EVIDENCE'}</span><h1>${title}</h1><p>${currentView === 'library' ? '흩어진 기록을 모아, 필요할 때 근거와 함께 찾아보세요.' : currentView === 'history' ? '이전에 찾았던 키워드로 탐색을 이어가세요.' : '문서 속 표현을 찾고, 인용된 원문을 직접 확인하세요.'}</p></div><button class="button primary" id="upload" ${!workspace ? 'disabled' : ''}>${icon('plus')} 문서 추가</button></div><form class="global-search" id="search-form">${icon('search')}<input id="search-input" name="query" value="${esc(search?.query || '')}" placeholder="어떤 내용을 찾고 있나요? 문서 속 키워드를 입력하세요" autocomplete="off" maxlength="500" required aria-label="문서 검색어" /><button type="submit" class="search-submit" ${!workspace ? 'disabled' : ''}>검색 ${icon('arrow')}</button></form><div class="search-caption"><span>키워드 검색 · BM25</span><span>내가 볼 수 있는 문서에서만 검색해요</span></div>${pageError ? `<div class="error-banner" role="alert">${esc(pageError)}<button id="reload" class="text-button">다시 불러오기</button></div>` : ''}<section class="content-section" aria-live="polite">${loading ? '<div class="loading"><span class="spinner"></span>문서를 불러오는 중이에요…</div>' : currentView === 'library' ? libraryHTML() : currentView === 'history' ? historyHTML() : searchHTML()}</section><footer class="main-footer"><span>문서에서 시작해, 근거로 도착하다.</span><span>DOCTRAIL</span></footer></main></div>${selected ? sourceHTML() : ''}</div>`;
  wireShell(); wireContent(); wireSource();
}
function libraryHTML() {
  const filtered = documents.filter(doc => doc.title.toLowerCase().includes(filter.toLowerCase()) || doc.filename.toLowerCase().includes(filter.toLowerCase()));
  return `<div class="section-bar"><div class="section-tabs"><span class="active">모든 문서 <b>${documents.length}</b></span></div><div class="library-filter">${icon('search')}<input id="filter" aria-label="문서 제목 필터" placeholder="제목으로 좁히기" value="${esc(filter)}" /></div></div>${!documents.length ? `<div class="empty-state library-empty"><div class="empty-illustration"><span class="paper back"></span><span class="paper front">${icon('file')}<i></i><i></i><i></i></span><span class="empty-plus">${icon('plus')}</span></div><span class="eyebrow">A GOOD PLACE TO BEGIN</span><h2>첫 번째 문서가, 첫 번째 근거가 됩니다.</h2><p>회의록, 프로젝트 기록, 참고 자료를 올려 보세요.<br>문서 속 키워드부터 원문 위치까지 연결해 드릴게요.</p><button class="button primary" id="empty-upload">${icon('upload')} 첫 문서 업로드</button><span class="file-hint">TXT · MD · 텍스트 PDF &nbsp; / &nbsp; 최대 5MB</span></div><div class="getting-started"><article><span>01</span><div><h3>기록을 모으세요</h3><p>파일을 올리고 문서 공개 범위를 선택해요.</p></div></article><article><span>02</span><div><h3>필요한 표현을 찾으세요</h3><p>문서 속 키워드로 관련 구절을 검색해요.</p></div></article><article><span>03</span><div><h3>원문으로 확인하세요</h3><p>검색된 구절과 최신 문서를 함께 읽어요.</p></div></article></div>` : `<div class="document-table"><div class="table-head"><span>문서 이름</span><span>공개 범위</span><span>상태</span><span>최근 수정</span><span></span></div>${filtered.length ? filtered.map(doc => `<button class="document-row ${selected?.id === doc.id ? 'selected' : ''}" data-document="${esc(doc.id)}"><span class="doc-name"><span class="file-icon ${doc.filename.toLowerCase().endsWith('.pdf') ? 'pdf' : ''}">${icon('file')}<small>${esc(doc.filename.split('.').pop()?.toUpperCase())}</small></span><span><strong>${esc(doc.title)}</strong><small>${esc(doc.filename)} <span>· v${doc.revision}</span></small></span></span><span class="visibility">${icon(doc.visibility === 'private' ? 'lock' : 'people')}${visibilityLabel(doc)}</span><span><span class="status-badge ${doc.status}"><i></i>${statusLabel(doc)}</span></span><span class="doc-date">${date(doc.updated_at)}</span>${icon('chevron')}</button>`).join('') : '<div class="mini-empty">일치하는 제목이 없어요.</div>'}</div><div class="table-bottom"><span>${filtered.length}개의 문서</span><span>문서를 선택하면 원문이 열립니다 ${icon('arrow')}</span></div>`}`;
}
function historyHTML() {
  return `<div class="section-bar"><h2>최근 검색 <span class="count">${history.length}</span></h2><span class="muted">내 검색 기록만 표시됩니다</span></div>${history.length ? `<div class="history-list">${history.map((item, index) => `<button class="history-row" data-history="${index}"><span class="history-icon">${icon('clock')}</span><span><strong>${esc(item.query)}</strong><small>${fullDate(item.created_at)}</small></span><span class="history-count">근거 ${item.result_count}개</span>${icon('arrow')}</button>`).join('')}</div>` : `<div class="empty-state compact">${icon('clock', 'empty-icon')}<h2>아직 검색 기록이 없어요.</h2><p>궁금한 키워드를 검색하면, 이곳에서 다시 찾을 수 있어요.</p></div>`}`;
}
function searchHTML() {
  if (!search) return `<div class="empty-state compact">${icon('search', 'empty-icon')}<h2>찾고 싶은 문서 속 표현이 있나요?</h2><p>위 검색창에 키워드를 입력하면 관련 구절을 찾아드려요.</p></div>`;
  return `<div class="section-bar"><h2>검색된 근거 <span class="count">${search.results.length}</span></h2><span class="muted">${Math.round(search.elapsed_ms)}ms · 관련도순</span></div>${search.results.length ? `<div class="results">${search.results.map((hit, index) => `<article class="result-card ${selectedHit?.chunk_id === hit.chunk_id ? 'selected' : ''}"><button class="result-open" data-hit="${index}"><div class="result-meta"><span class="citation-number">${index + 1}</span><span>${esc(hit.filename)}</span><span>v${hit.revision}${hit.page ? ` · ${hit.page}페이지` : ''}</span></div><h2>${esc(hit.title)}</h2><p class="result-excerpt">${highlight(excerpt(hit.text, search!.query), search!.query)}</p><span class="result-link">원문에서 근거 확인 ${icon('arrow')}</span></button><div class="result-bottom"><span>검색된 원문 구절</span><div class="feedback"><span>도움이 됐나요?</span><button data-feedback="${index}" data-relevant="true" aria-label="${index + 1}번 결과 관련 있음">관련 있어요</button><button data-feedback="${index}" data-relevant="false" aria-label="${index + 1}번 결과 관련 없음">관련 없어요</button></div></div></article>`).join('')}</div><p class="search-disclaimer">검색 결과는 원문 구절입니다. AI가 생성한 답변이 아니에요.</p>` : `<div class="empty-state compact">${icon('search', 'empty-icon')}<h2>“${esc(search.query)}”에 맞는 근거가 없어요.</h2><p>문서에 쓰인 표현으로 바꾸거나, 더 짧은 키워드를 입력해 보세요.<br>문서의 상태가 ‘검색 가능’인지도 확인해 주세요.</p><button class="button secondary" id="back-library">문서 라이브러리 보기</button></div>`}`;
}
function excerpt(text: string, query: string): string {
  const terms = [...new Set(query.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean))];
  const paragraphs = [...text.matchAll(/[^\n]+(?:\n(?!\s*\n)[^\n]+)*/g)];
  const ranked = paragraphs.map(paragraph => {
    const lower = paragraph[0].toLocaleLowerCase();
    const matching = terms.filter(term => lower.includes(term));
    const count = matching.reduce((total, term) => total + lower.split(term).length - 1, 0);
    const score = matching.length * 10 + Math.min(count, 8) + Math.min(paragraph[0].length / 100, 2) - (/^\s*#{1,6}\s/.test(paragraph[0]) ? 8 : 0);
    return { paragraph, matching, lower, score: matching.length ? score : -1 };
  }).sort((a, b) => b.score - a.score);
  const best = ranked[0];
  const matchOffset = best?.matching.length ? Math.min(...best.matching.map(term => best.lower.indexOf(term))) + best.paragraph.index! : 0;
  let start = Math.max(0, matchOffset - 40);
  let end = Math.min(text.length, start + 260);
  // Do not split an emoji surrogate pair at excerpt boundaries.
  if (start > 0 && /[\uDC00-\uDFFF]/.test(text[start])) start--;
  if (end < text.length && /[\uDC00-\uDFFF]/.test(text[end])) end++;
  return `${start ? '…' : ''}${text.slice(start, end)}${end < text.length ? '…' : ''}`;
}
function highlight(text: string, query: string) {
  const terms = [...new Set(query.trim().split(/\s+/).filter(Boolean))].sort((a, b) => b.length - a.length);
  if (!terms.length) return esc(text);
  const regex = new RegExp(terms.map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'giu');
  let html = '', last = 0;
  for (const match of text.matchAll(regex)) { html += esc(text.slice(last, match.index)) + `<mark>${esc(match[0])}</mark>`; last = match.index! + match[0].length; }
  return html + esc(text.slice(last));
}
function sourceHTML() {
  const doc = selected!;
  const hit = selectedHit;
  const citation = hit && doc.revision === hit.revision ? doc.chunks.find(chunk => chunk.id === hit.chunk_id) : undefined;
  return `<aside class="source-pane" aria-label="문서 원문"><header class="source-top"><span>${icon('file')} 원문 보기</span><button class="icon-button" id="close-source" aria-label="원문 닫기">${icon('close')}</button></header><div class="source-scroll"><div class="source-heading"><span class="eyebrow">SOURCE DOCUMENT</span><h2>${esc(doc.title)}</h2><p>${esc(doc.filename)}</p><div class="source-badges"><span>${icon(doc.visibility === 'private' ? 'lock' : 'people')}${visibilityLabel(doc)}</span><span>버전 ${doc.revision}</span><span>${doc.chunk_count}개 구절</span></div></div>${doc.status === 'failed' ? `<div class="source-warning"><strong>이 문서는 아직 검색할 수 없어요.</strong><p>파일에서 텍스트를 추출하지 못했어요. UTF-8 문서 또는 텍스트가 포함된 PDF인지 확인해 주세요.</p>${isOwner(doc) ? '<button class="button secondary" id="retry-document">다시 처리하기</button>' : ''}</div>` : ''}${hit && !citation ? '<div class="source-warning"><strong>검색 이후 원문이 변경되었어요.</strong><p>아래에는 최신 문서가 표시됩니다. 정확한 근거 위치는 다시 검색해 확인해 주세요.</p><button class="text-button" id="search-again">다시 검색</button></div>' : ''}${citation ? `<section class="citation-block"><div><span>${icon('quote')} 근거 ${selectedIndex + 1}</span><small>v${doc.revision}${citation.page ? ` · ${citation.page}페이지` : ''}</small></div><blockquote>${highlight(citation.text, search?.query || '')}</blockquote><button class="text-button" id="jump-source">원문 위치로 이동 ↓</button></section>` : ''}<div class="source-label"><span>전체 원문</span><small>${date(doc.updated_at)} 수정</small></div><div class="source-text" id="source-text">${sourceText(doc.content, citation)}</div>${!doc.content ? '<p class="muted source-empty">표시할 텍스트가 없어요.</p>' : ''}</div><footer class="source-actions"><span>원문 텍스트 · v${doc.revision}</span>${isOwner(doc) ? `<button class="button secondary small-button" id="edit-document">${icon('edit')} 편집</button><button class="text-button danger" id="delete-document">삭제</button>` : ''}</footer></aside>`;
}
function sourceText(content: string, citation?: Chunk) {
  if (!citation) return esc(content);
  // Python offsets count Unicode codepoints; Array.from preserves those offsets for emoji too.
  const points = Array.from(content);
  if (points.slice(citation.start_offset, citation.end_offset).join('') !== citation.text) return esc(content);
  return esc(points.slice(0, citation.start_offset).join('')) + `<mark id="source-citation">${esc(citation.text)}</mark>` + esc(points.slice(citation.end_offset).join(''));
}

function wireShell() {
  qs<HTMLSelectElement>('#workspace-select').onchange = event => { workspace = workspaces.find(w => w.id === (event.target as HTMLSelectElement).value); clearState(); currentView = 'library'; void loadWorkspace(); };
  app.querySelectorAll<HTMLButtonElement>('[data-view]').forEach(button => button.onclick = () => { currentView = button.dataset.view as typeof currentView; pageError = ''; render(); });
  qs('#focus-search').onclick = () => qs<HTMLInputElement>('#search-input').focus();
  qs<HTMLFormElement>('#search-form').onsubmit = event => { event.preventDefault(); void runSearch(qs<HTMLInputElement>('#search-input').value); };
  qs('#upload').onclick = uploadModal;
  qs('#new-workspace').onclick = workspaceModal;
  app.querySelector('#members')?.addEventListener('click', memberModal);
  app.querySelector('#reload')?.addEventListener('click', () => void loadWorkspace());
  qs<HTMLButtonElement>('#logout').onclick = async event => {
    const button = event.currentTarget as HTMLButtonElement; button.disabled = true;
    try { await api('/auth/logout', { method: 'POST' }); clearState(); user = null; workspace = undefined; workspaces = []; dialog.close(); authMode = 'login'; render(); }
    catch (error) { toast(errorMessage(error)); button.disabled = false; }
  };
}
function wireContent() {
  app.querySelector('#empty-upload')?.addEventListener('click', uploadModal);
  const filterInput = app.querySelector<HTMLInputElement>('#filter');
  if (filterInput) filterInput.oninput = () => { filter = filterInput.value; const start = filterInput.selectionStart; qs('.content-section').innerHTML = libraryHTML(); wireContent(); const fresh = qs<HTMLInputElement>('#filter'); fresh.focus(); fresh.setSelectionRange(start, start); };
  app.querySelectorAll<HTMLButtonElement>('[data-document]').forEach(button => button.onclick = () => void openDocument(button.dataset.document!));
  app.querySelectorAll<HTMLButtonElement>('[data-hit]').forEach(button => button.onclick = () => { const index = Number(button.dataset.hit); const hit = search!.results[index]; void openDocument(hit.document_id, hit, index); });
  app.querySelectorAll<HTMLButtonElement>('[data-history]').forEach(button => button.onclick = () => void runSearch(history[Number(button.dataset.history)].query));
  app.querySelector('#back-library')?.addEventListener('click', () => { currentView = 'library'; render(); });
  app.querySelectorAll<HTMLButtonElement>('[data-feedback]').forEach(button => button.onclick = async () => {
    const activeSearch = search; if (!activeSearch) return; const hit = activeSearch.results[Number(button.dataset.feedback)]; const stamp = epoch; const parent = button.parentElement!; parent.querySelectorAll('button').forEach(b => b.disabled = true);
    try { await api(`/searches/${activeSearch.search_id}/feedback`, { method: 'POST', body: JSON.stringify({ document_id: hit.document_id, relevant: button.dataset.relevant === 'true' }) }); if (stamp === epoch && parent.isConnected) { parent.textContent = '피드백이 저장됐어요. 고마워요!'; } }
    catch (error) { if (stamp === epoch) { toast(errorMessage(error)); parent.querySelectorAll('button').forEach(b => b.disabled = false); } }
  });
}
function wireSource() {
  app.querySelector('#close-source')?.addEventListener('click', () => { detailRequest++; selected = null; selectedHit = null; render(); });
  app.querySelector('#edit-document')?.addEventListener('click', editModal);
  app.querySelector('#delete-document')?.addEventListener('click', deleteModal);
  app.querySelector('#jump-source')?.addEventListener('click', () => qs('#source-citation')?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
  app.querySelector('#search-again')?.addEventListener('click', () => void runSearch(search?.query || ''));
  app.querySelector('#retry-document')?.addEventListener('click', async event => {
    const button = event.currentTarget as HTMLButtonElement; const doc = selected!; const stamp = epoch; button.disabled = true;
    try { const detail = await api<Detail>(`/documents/${doc.id}/reprocess`, { method: 'POST' }); if (stamp !== epoch) return; replaceDoc(detail); if (selected?.id === doc.id) selected = detail; render(); toast(detail.status === 'ready' ? '문서 처리가 완료됐어요.' : '아직 텍스트를 추출하지 못했어요. 파일을 확인해 주세요.'); }
    catch (error) { if (stamp === epoch) { toast(errorMessage(error)); button.disabled = false; } }
  });
}
async function runSearch(query: string) {
  query = query.trim(); if (!query || !workspace) return;
  const stamp = epoch; const request = ++searchRequest; detailRequest++; const id = workspace.id; currentView = 'search'; selected = null; selectedHit = null; search = null; loading = true; pageError = ''; render(); qs<HTMLInputElement>('#search-input').value = query;
  try { const result = await api<Search>(`/workspaces/${id}/search?q=${encodeURIComponent(query)}&limit=10`); if (stamp !== epoch || request !== searchRequest) return; search = result; history = [{ id: result.search_id, query, created_at: new Date().toISOString(), result_count: result.results.length }, ...history].slice(0, 50); }
  catch (error) { if (stamp !== epoch || request !== searchRequest) return; pageError = errorMessage(error); }
  if (stamp === epoch && request === searchRequest) { loading = false; render(); }
}
async function openDocument(id: string, hit?: Hit, index = 0) {
  const stamp = epoch; const request = ++detailRequest;
  try { const detail = await api<Detail>(`/documents/${id}`); if (stamp !== epoch || request !== detailRequest) return; selected = detail; selectedHit = hit || null; selectedIndex = index; replaceDoc(detail); render(); qs('.source-pane').scrollIntoView({ behavior: 'smooth', block: 'nearest' }); qs<HTMLButtonElement>('#close-source').focus({ preventScroll: true }); }
  catch (error) { if (stamp === epoch && request === detailRequest) {
    selected = null; selectedHit = null;
    if (error instanceof ApiError && [403, 404].includes(error.status)) {
      documents = documents.filter(doc => doc.id !== id);
      if (search) search.results = search.results.filter(result => result.document_id !== id);
    }
    render(); toast(errorMessage(error));
  } }
}
function replaceDoc(detail: Detail) { const index = documents.findIndex(doc => doc.id === detail.id); if (index >= 0) documents[index] = detail; else documents.unshift(detail); }

function uploadModal() {
  if (!workspace) return;
  const id = workspace.id; const stamp = epoch;
  showModal(`${modalHead('문서 추가', '찾을 수 있는 기록으로, 새로운 문서를 연결하세요.')}<form id="upload-form"><label class="file-drop">${icon('upload')}<strong>업로드할 파일을 선택하세요</strong><span>UTF-8 TXT · MD · 텍스트 PDF / 최대 5MB</span><input type="file" name="file" accept=".txt,.md,.pdf" required aria-label="업로드할 문서 파일" /><span id="file-name"></span></label><label>문서 제목 <span class="optional">선택</span><input name="title" maxlength="200" placeholder="비워 두면 파일 이름을 사용해요" /></label>${visibilityField('workspace')}<p class="form-error" role="alert"></p><div class="modal-actions"><button type="button" class="button secondary" id="upload-cancel">취소</button><button type="submit" class="button primary">${icon('upload')} 업로드</button></div></form>`);
  const form = qs<HTMLFormElement>('#upload-form', dialog); const fileInput = qs<HTMLInputElement>('[type=file]', form);
  qs('#upload-cancel', dialog).onclick = () => dialog.close();
  fileInput.onchange = () => { qs('#file-name', form).textContent = fileInput.files?.[0]?.name || ''; };
  form.onsubmit = async event => {
    event.preventDefault(); const file = fileInput.files?.[0]; if (!file) return; if (file.size > 5 * 1024 * 1024) { qs('.form-error', form).textContent = '5MB 이하의 파일을 선택해 주세요.'; return; }
    const button = qs<HTMLButtonElement>('[type=submit]', form); button.disabled = true; button.textContent = '문서를 처리하는 중…'; qs('.form-error', form).textContent = '';
    try { const detail = await api<Detail>(`/workspaces/${id}/documents`, { method: 'POST', body: new FormData(form) }); if (stamp !== epoch) return; detailRequest++; replaceDoc(detail); selected = detail; selectedHit = null; currentView = 'library'; form.reset(); if (form.isConnected) dialog.close(); render(); toast(detail.status === 'ready' ? '문서를 추가했어요. 이제 키워드로 검색해 보세요.' : '파일을 저장했지만 텍스트 추출에 실패했어요. 원문 패널을 확인해 주세요.'); }
    catch (error) { if (stamp === epoch && form.isConnected) { formError(form, error); button.disabled = false; button.textContent = '다시 업로드'; } }
  };
}
function visibilityField(value: string) { return `<label>공개 범위<select name="visibility"><option value="workspace" ${value === 'workspace' ? 'selected' : ''}>워크스페이스 멤버에게 공개</option><option value="private" ${value === 'private' ? 'selected' : ''}>나만 보기</option></select></label><p class="field-note">나만 보기 문서는 다른 멤버의 목록과 검색에 나타나지 않아요.</p>`; }
function editModal() {
  const doc = selected; if (!doc) return; const stamp = epoch;
  showModal(`${modalHead('문서 편집', '저장하면 새 버전으로 바뀌고, 검색에 바로 반영됩니다.')}<form id="edit-form"><label>문서 제목<input name="title" value="${esc(doc.title)}" required maxlength="200" /></label>${visibilityField(doc.visibility)}<label>원문 텍스트<textarea name="content" rows="13" required>${esc(doc.content)}</textarea></label><p class="field-note">추출된 텍스트를 수정합니다. PDF의 원래 레이아웃은 편집하지 않아요.</p><p class="form-error" role="alert"></p><div class="modal-actions"><button type="button" class="button secondary" id="edit-cancel">취소</button><button type="submit" class="button primary">변경 저장</button></div></form>`);
  dialog.classList.add('wide'); dialog.addEventListener('close', () => dialog.classList.remove('wide'), { once: true }); qs('#edit-cancel', dialog).onclick = () => dialog.close();
  const form = qs<HTMLFormElement>('#edit-form', dialog);
  form.onsubmit = async event => { event.preventDefault(); const button = qs<HTMLButtonElement>('[type=submit]', form); button.disabled = true;
    try { const detail = await api<Detail>(`/documents/${doc.id}`, { method: 'PUT', body: JSON.stringify(Object.fromEntries(new FormData(form))) }); if (stamp !== epoch) return; detailRequest++; searchRequest++; loading = false; replaceDoc(detail); selected = detail; search = null; selectedHit = null; currentView = 'library'; if (form.isConnected) dialog.close(); render(); toast(`버전 ${detail.revision}으로 저장했어요. 검색에도 반영됐어요.`); }
    catch (error) { if (stamp === epoch && form.isConnected) { formError(form, error); button.disabled = false; } }
  };
}
function deleteModal() {
  const doc = selected; if (!doc) return; const stamp = epoch;
  showModal(`${modalHead('문서를 삭제할까요?', '삭제한 문서는 라이브러리와 검색 결과에서 사라집니다.')}<div class="delete-preview">${icon('file')}<strong>${esc(doc.title)}</strong></div><p class="muted">이 작업은 되돌릴 수 없어요.</p><p class="form-error" role="alert"></p><div class="modal-actions"><button class="button secondary" id="delete-cancel">취소</button><button class="button danger-button" id="confirm-delete">문서 삭제</button></div>`);
  qs('#delete-cancel', dialog).onclick = () => dialog.close();
  qs<HTMLButtonElement>('#confirm-delete', dialog).onclick = async event => { const button = event.currentTarget as HTMLButtonElement; button.disabled = true;
    try { await api(`/documents/${doc.id}`, { method: 'DELETE' }); if (stamp !== epoch) return; documents = documents.filter(item => item.id !== doc.id); detailRequest++; searchRequest++; loading = false; selected = null; selectedHit = null; search = null; currentView = 'library'; if (button.isConnected) dialog.close(); render(); toast('문서를 삭제했어요. 더 이상 검색되지 않아요.'); }
    catch (error) { if (stamp === epoch) { qs('.form-error', dialog).textContent = errorMessage(error); button.disabled = false; } }
  };
}
function workspaceModal() {
  const stamp = epoch;
  showModal(`${modalHead('새 워크스페이스', '주제나 프로젝트별로 문서를 나누어 관리하세요.')}<form id="workspace-form"><label>워크스페이스 이름<input name="name" required maxlength="100" placeholder="예: 제품 리서치" /></label><p class="form-error" role="alert"></p><div class="modal-actions"><button class="button primary" type="submit">만들기</button></div></form>`);
  const form = qs<HTMLFormElement>('#workspace-form', dialog);
  form.onsubmit = async event => { event.preventDefault(); const button = qs<HTMLButtonElement>('[type=submit]', form); button.disabled = true;
    try { const result = await api<Workspace>('/workspaces', { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(form))) }); if (stamp !== epoch) return; workspaces.push(result); workspace = result; clearState(); currentView = 'library'; dialog.close(); await loadWorkspace(); toast('새 워크스페이스를 만들었어요.'); }
    catch (error) { if (stamp === epoch && form.isConnected) { formError(form, error); button.disabled = false; } }
  };
}
function memberModal() {
  const id = workspace?.id; const stamp = epoch;
  showModal(`${modalHead('워크스페이스 멤버 추가', '이미 DocTrail에 가입한 사용자를 추가할 수 있어요.')}<form id="member-form"><label>가입한 이메일<input name="email" type="email" autocomplete="email" required placeholder="member@example.com" /></label><p class="field-note">추가된 멤버는 워크스페이스에 공개된 문서를 읽고 검색할 수 있어요. 초대 메일은 발송하지 않습니다.</p><p class="form-error" role="alert"></p><div class="modal-actions"><button class="button primary" type="submit">멤버 추가</button></div></form>`);
  const form = qs<HTMLFormElement>('#member-form', dialog);
  form.onsubmit = async event => { event.preventDefault(); const button = qs<HTMLButtonElement>('[type=submit]', form); button.disabled = true;
    try { await api(`/workspaces/${id}/members`, { method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(form))) }); if (stamp !== epoch) return; dialog.close(); toast('워크스페이스에 멤버를 추가했어요.'); }
    catch (error) { if (stamp === epoch && form.isConnected) { formError(form, error); button.disabled = false; } }
  };
}
document.addEventListener('keydown', event => { if (event.key === '/' && !dialog.open && !['INPUT', 'TEXTAREA', 'SELECT'].includes((event.target as HTMLElement).tagName) && user) { event.preventDefault(); qs<HTMLInputElement>('#search-input').focus(); } });
async function boot() {
  try { const auth = await api<Auth>('/auth/me'); user = auth.user; workspaces = auth.workspaces; workspace = workspaces[0]; await loadWorkspace(); }
  catch (error) { renderAuth(); if (!(error instanceof ApiError && error.status === 401)) toast(errorMessage(error)); }
}
void boot();
