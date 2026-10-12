import { useLayoutEffect, useRef, useState } from 'react';
import type { DocTrail } from '../useDocTrail';
import type { Modal as ModalState } from '../types';
import { Icon } from './Icon';

const headings = {
  upload: ['문서 추가', '찾을 수 있는 기록으로, 새로운 문서를 연결하세요.'],
  edit: ['문서 편집', '저장하면 새 버전으로 바뀌고, 검색에 바로 반영됩니다.'],
  delete: ['문서를 삭제할까요?', '삭제한 문서는 라이브러리와 검색 결과에서 사라집니다.'],
  workspace: ['새 워크스페이스', '주제나 프로젝트별로 문서를 나누어 관리하세요.'],
  member: ['워크스페이스 멤버 추가', '이미 DocTrail에 가입한 사용자를 추가할 수 있어요.'],
};
function VisibilityField({ value }: { value: string }) {
  return <><label>공개 범위<select name="visibility" defaultValue={value}><option value="workspace">워크스페이스 멤버에게 공개</option><option value="private">나만 보기</option></select></label><p className="field-note">나만 보기 문서는 다른 멤버의 목록과 검색에 나타나지 않아요.</p></>;
}

export function Modal({ app, modal }: { app: DocTrail; modal: ModalState }) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const [filename, setFilename] = useState('');
  useLayoutEffect(() => {
    const dialog = ref.current!;
    if (!opener.current && document.activeElement instanceof HTMLElement) opener.current = document.activeElement;
    dialog.showModal();
    return () => {
      // Release native inertness first; no close handler can affect another modal.
      dialog.close();
      requestAnimationFrame(() => {
        if (!document.querySelector('dialog[open]') && opener.current?.isConnected) opener.current.focus({ preventScroll: true });
      });
    };
  }, []);
  const { modalBusy: busy, modalError: error } = app.state;
  const [title, description] = headings[modal.kind];
  return <dialog id="dialog" ref={ref} className={modal.kind === 'edit' ? 'wide' : undefined} aria-labelledby="dialog-title"
    onCancel={event => { event.preventDefault(); app.closeModal(); }}
    onClick={event => {
      if (event.target !== event.currentTarget) return;
      const bounds = event.currentTarget.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) app.closeModal();
    }}>
    <header className="modal-head"><div><h2 id="dialog-title">{title}</h2><p>{description}</p></div><button className="icon-button" data-close aria-label="닫기" onClick={app.closeModal}><Icon name="close"/></button></header>
    <form id={`${modal.kind}-form`} onSubmit={event => { event.preventDefault(); void app.submitModal(new FormData(event.currentTarget)); }}>
      {modal.kind === 'upload' && <>
        <label className="file-drop"><Icon name="upload"/><strong>업로드할 파일을 선택하세요</strong><span>UTF-8 TXT · MD · 텍스트 PDF / 최대 5MB</span><input type="file" name="file" accept=".txt,.md,.pdf" required aria-label="업로드할 문서 파일" onChange={event => setFilename(event.currentTarget.files?.[0]?.name || '')}/><span id="file-name">{filename}</span></label>
        <label>문서 제목 <span className="optional">선택</span><input name="title" maxLength={200} placeholder="비워 두면 파일 이름을 사용해요"/></label><VisibilityField value="workspace"/>
      </>}
      {modal.kind === 'edit' && <>
        <label>문서 제목<input name="title" defaultValue={modal.doc.title} required maxLength={200}/></label><VisibilityField value={modal.doc.visibility}/>
        <label>원문 텍스트<textarea name="content" rows={13} required defaultValue={modal.doc.content}/></label><p className="field-note">추출된 텍스트를 수정합니다. PDF의 원래 레이아웃은 편집하지 않아요.</p>
      </>}
      {modal.kind === 'delete' && <><div className="delete-preview"><Icon name="file"/><strong>{modal.doc.title}</strong></div><p className="muted">이 작업은 되돌릴 수 없어요.</p></>}
      {modal.kind === 'workspace' && <label>워크스페이스 이름<input name="name" required maxLength={100} placeholder="예: 제품 리서치"/></label>}
      {modal.kind === 'member' && <><label>가입한 이메일<input name="email" type="email" autoComplete="email" required placeholder="member@example.com"/></label><p className="field-note">추가된 멤버는 워크스페이스에 공개된 문서를 읽고 검색할 수 있어요. 초대 메일은 발송하지 않습니다.</p></>}
      <p className="form-error" role="alert">{error}</p><div className="modal-actions">
        {['upload', 'edit', 'delete'].includes(modal.kind) && <button type="button" className="button secondary" id={`${modal.kind}-cancel`} onClick={app.closeModal}>취소</button>}
        <button type="submit" className={`button ${modal.kind === 'delete' ? 'danger-button' : 'primary'}`} id={modal.kind === 'delete' ? 'confirm-delete' : undefined} disabled={busy}>
          {modal.kind === 'upload' ? busy ? '문서를 처리하는 중…' : <><Icon name="upload"/> 업로드</> : modal.kind === 'edit' ? '변경 저장' : modal.kind === 'delete' ? '문서 삭제' : modal.kind === 'workspace' ? '만들기' : '멤버 추가'}
        </button>
      </div>
    </form>
  </dialog>;
}
