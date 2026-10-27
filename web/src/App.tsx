import { useEffect, useRef } from 'react';
import { useDocTrail } from './useDocTrail';
import { AuthScreen } from './components/AuthScreen';
import { Brand, Icon } from './components/Icon';
import { Library, HistoryView, SearchView } from './components/ContentViews';
import { SourcePane } from './components/SourcePane';
import { Modal } from './components/Modal';
import { MeetingWorkspace } from './components/MeetingViews';
import { KnowledgeView } from './components/KnowledgeView';
import { profileLabel, searchMethods } from './searchMethods';
import type { SearchMethod } from './types';

export function App() {
  const app = useDocTrail();
  const { state, workspace } = app;
  const { auth, view, selected } = state;
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      const target = event.target;
      if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey || state.modal || !auth) return;
      if (target instanceof HTMLElement && (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable)) return;
      event.preventDefault(); if (view === 'meetings' || view === 'actions') { app.changeView('knowledge'); requestAnimationFrame(() => document.getElementById('knowledge-query')?.focus()); } else (view === 'knowledge' ? document.getElementById('knowledge-query') : input.current)?.focus();
    };
    document.addEventListener('keydown', shortcut);
    return () => document.removeEventListener('keydown', shortcut);
  }, [auth, state.modal, view]);
  const title = { library: '문서 라이브러리', history: '검색 기록', search: '문서 검색', meetings: '회의', actions: '후속 작업', knowledge: '지식 검색 · Q&A' }[view];
  const meetingView = view === 'meetings' || view === 'actions';
  const extendedView = meetingView || view === 'knowledge';
  return <>
    {state.booting ? <div className="boot">DocTrail을 여는 중…</div> : !auth ? <AuthScreen app={app}/> :
      <div className={`shell ${selected ? 'with-source' : ''}`}>
        <aside className="sidebar"><Brand/><div className="workspace-switch"><label className="sr-only" htmlFor="workspace-select">워크스페이스 선택</label><span className="workspace-avatar">{workspace?.name.slice(0, 1) || 'D'}</span><select id="workspace-select" value={state.workspaceId} onChange={event => app.switchWorkspace(event.currentTarget.value)}>{auth.workspaces.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>
          <button className="sidebar-search" id="focus-search" onClick={() => { app.changeView('knowledge'); requestAnimationFrame(() => document.getElementById('knowledge-query')?.focus()); }}><Icon name="search"/><span>지식 검색</span><kbd>/</kbd></button><span className="nav-label">WORKSPACE</span>
          <nav aria-label="주 메뉴"><button data-view="knowledge" className={`nav-item ${view === 'knowledge' ? 'active' : ''}`} onClick={() => app.changeView('knowledge')}><Icon name="search"/><span>지식 검색 · Q&A</span></button><button data-view="meetings" className={`nav-item ${view === 'meetings' ? 'active' : ''}`} onClick={() => app.changeView('meetings')}><Icon name="people"/><span>회의</span></button><button data-view="actions" className={`nav-item ${view === 'actions' ? 'active' : ''}`} onClick={() => app.changeView('actions')}><Icon name="check"/><span>후속 작업</span></button><button data-view="library" className={`nav-item ${view === 'library' ? 'active' : ''}`} onClick={() => app.changeView('library')}><Icon name="book"/><span>문서 라이브러리</span><span className="nav-count">{state.documents.length}</span></button><button data-view="history" className={`nav-item ${view === 'history' ? 'active' : ''}`} onClick={() => app.changeView('history')}><Icon name="clock"/><span>검색 기록</span></button></nav>
          <div className="sidebar-bottom"><div className="workspace-note"><span className="status-dot"/> {searchMethods[state.searchMethod].label}<p>답변보다 먼저, 원문 근거를.</p></div><button className="nav-item small" id="new-workspace" onClick={() => app.openModal('workspace')}><Icon name="plus"/> 새 워크스페이스</button>{workspace?.role === 'owner' && <button className="nav-item small" id="members" onClick={() => app.openModal('member')}><Icon name="people"/> 멤버 추가</button>}
            <div className="account"><span className="user-avatar">{auth.user.name.slice(0, 1)}</span><div><strong>{auth.user.name}</strong><span>{auth.user.email}</span></div><button id="logout" className="icon-button" aria-label="로그아웃" title="로그아웃" disabled={state.logoutBusy} onClick={() => void app.logout()}><Icon name="exit"/></button></div>
          </div>
        </aside>
        <div className="main-layout"><header className="topbar"><div className="breadcrumb"><span>{workspace?.name || '워크스페이스'}</span><Icon name="chevron"/><strong>{title}</strong></div><span className="private-note"><Icon name="lock"/> 권한 기반 검색</span></header>
          <main className="main-content">{!extendedView && <><div className="page-top"><div><span className="eyebrow">{view === 'library' ? 'YOUR KNOWLEDGE, IN ONE PLACE' : view === 'history' ? 'PICK UP WHERE YOU LEFT OFF' : 'FOLLOW THE EVIDENCE'}</span><h1>{title}</h1><p>{view === 'library' ? '흩어진 기록을 모아, 필요할 때 근거와 함께 찾아보세요.' : view === 'history' ? '이전에 찾았던 키워드로 탐색을 이어가세요.' : '문서 속 표현을 찾고, 인용된 원문을 직접 확인하세요.'}</p></div><button className="button primary" id="upload" disabled={!workspace} onClick={() => app.openModal('upload')}><Icon name="plus"/> 문서 추가</button></div>
            <form className="global-search" id="search-form" onSubmit={event => { event.preventDefault(); void app.runSearch(state.query); }}><Icon name="search"/><input ref={input} id="search-input" name="query" value={state.query} onChange={event => app.setQuery(event.currentTarget.value)} placeholder="어떤 내용을 찾고 있나요? 문서 속 키워드를 입력하세요" autoComplete="off" maxLength={500} required aria-label="문서 검색어"/><button type="submit" className="search-submit" disabled={!workspace}>검색 <Icon name="arrow"/></button></form>
            <div className="search-options"><label htmlFor="search-method">검색 방식<select id="search-method" value={state.searchMethod} onChange={event => app.setSearchMethod(event.currentTarget.value as SearchMethod)}>{(Object.keys(searchMethods) as SearchMethod[]).map(method => <option key={method} value={method} disabled={method !== 'bm25' && !state.capabilities?.available_methods.includes(method)}>{searchMethods[method].label}</option>)}</select></label><span>{searchMethods[state.searchMethod].description}</span>{state.capabilities?.status !== 'ready' && <button className="text-button" type="button" disabled={state.capabilitiesBusy} onClick={() => void app.loadCapabilities()}>{state.capabilitiesBusy ? '연결 확인 중…' : '모델 연결 확인'}</button>}</div>
            <div className="search-caption"><span>{state.capabilities?.status === 'ready' ? `모델 검색 연결됨${state.capabilities.embedding_profile ? ` · ${profileLabel(state.capabilities.embedding_profile)}` : ''}` : '현재 키워드 검색 사용 가능'}</span><span>내가 볼 수 있는 문서에서만 검색해요</span></div>
            {state.historyNotice && <div className="error-banner" role="status" data-testid="history-model-notice">{state.historyNotice}</div>}
            {state.pageError && <div className="error-banner" role="alert">{state.pageError}<button id="reload" className="text-button" onClick={() => void (view === 'search' ? app.runSearch(state.query) : app.loadWorkspace())}>다시 불러오기</button></div>}
            <section className="content-section" aria-live="polite">{state.loading ? <div className="loading"><span className="spinner"/>문서를 불러오는 중이에요…</div> : view === 'library' ? <Library app={app}/> : view === 'history' ? <HistoryView key={`${auth.user.id}:${state.workspaceId}:${state.viewVersion}:history`} app={app}/> : <SearchView app={app}/>}</section></>}
            {meetingView && <MeetingWorkspace key={`${auth.user.id}:${state.workspaceId}:${view}`} app={app} mode={view}/>}
            {view === 'knowledge' && <KnowledgeView key={`${auth.user.id}:${state.workspaceId}:${state.viewVersion}:knowledge`} app={app}/>}
            <footer className="main-footer"><span>문서에서 시작해, 근거로 도착하다.</span><span>DOCTRAIL</span></footer>
          </main>
        </div>{selected && <SourcePane app={app}/>}
      </div>}
    <div id="toast" role="status" aria-live="polite" className={state.toast ? 'visible' : undefined}>{state.toast?.message || ''}</div>
    {state.modal && <Modal key={state.modal.id} modal={state.modal} app={app}/>}
  </>;
}
