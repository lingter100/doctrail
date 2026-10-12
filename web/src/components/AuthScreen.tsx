import type { DocTrail } from '../useDocTrail';
import { Brand, Icon } from './Icon';

export function AuthScreen({ app }: { app: DocTrail }) {
  const { authMode, authBusy, authError } = app.state;
  const register = authMode === 'register';
  return <main className="auth-layout">
    <section className="auth-story"><Brand/><div className="auth-story-body">
      <span className="eyebrow">YOUR DOCUMENTS, CONNECTED.</span><h1>찾던 정보에서<br/>확실한 근거까지.</h1>
      <p>흩어진 문서를 한곳에 모으고,<br/>검색 결과를 원문에서 직접 확인하세요.</p>
      <div className="story-visual" aria-hidden="true"><div className="visual-sheet"><span className="visual-file"><Icon name="file"/> 프로젝트 문서</span><i/><i/><i className="highlight"/><i/><i className="short"/></div><div className="visual-citation"><Icon name="quote"/> 원문으로 이어지는 검색<span><Icon name="check"/></span></div><div className="visual-dot one"/><div className="visual-dot two"/></div>
      <div className="story-steps"><span>01 &nbsp; 문서 모으기</span><span>02 &nbsp; 키워드 찾기</span><span>03 &nbsp; 근거 확인</span></div>
    </div><small>내 문서의 맥락을 잃지 않는 검색 공간</small></section>
    <section className="auth-form-area"><div className="auth-card"><span className="eyebrow">START YOUR TRAIL</span>
      <h2>{register ? '나만의 문서 공간 만들기' : '다시 만나서 반가워요'}</h2><p className="muted">{register ? '첫 번째 문서부터, 차근차근 시작하세요.' : '문서와 검색 기록이 기다리고 있어요.'}</p>
      <div className="auth-tabs" role="tablist" aria-label="계정"><button role="tab" aria-selected={register} data-auth="register" disabled={authBusy} onClick={() => app.setAuthMode('register')}>새로 시작하기</button><button role="tab" aria-selected={!register} data-auth="login" disabled={authBusy} onClick={() => app.setAuthMode('login')}>로그인</button></div>
      <form id="auth-form" key={authMode} onSubmit={event => { event.preventDefault(); void app.authenticate(new FormData(event.currentTarget)); }}>
        {register && <label>이름<input name="name" autoComplete="name" maxLength={80} required placeholder="어떻게 불러 드릴까요?"/></label>}
        <label>이메일<input name="email" type="email" autoComplete="email" required placeholder="you@example.com" maxLength={254}/></label>
        <label>비밀번호<input name="password" type="password" autoComplete={register ? 'new-password' : 'current-password'} minLength={register ? 10 : 1} required placeholder={register ? '10자 이상 입력해 주세요' : '비밀번호를 입력해 주세요'}/></label>
        {register && <label>워크스페이스 이름<input name="workspace_name" required maxLength={100} placeholder="예: 나의 리서치 노트"/></label>}
        <p className="form-error" role="alert">{authError}</p><button className="button primary auth-submit" type="submit" disabled={authBusy}>{register ? '워크스페이스 만들기' : '로그인'}<Icon name="arrow"/></button>
      </form><p className="auth-note"><Icon name="lock"/> 업로드한 문서는 설정한 공개 범위 안에서 검색됩니다.</p>
    </div><footer className="auth-footer">DocTrail <span>문서에서 근거까지</span></footer></section>
  </main>;
}
