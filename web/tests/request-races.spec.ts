import { test, expect, register, upload, ready, search, completedSearch, delayResponse, password } from './support';

test('real responses: initial list load survives search and return to the library', async ({ page }) => {
  const auth = await register(page.request);
  const workspace = auth.workspaces[0].id;
  const doc = await upload(page.request, workspace, 'Synthetic initial document', 'initialmarker evidence');
  const pending = await delayResponse(page, url => url.pathname === `/api/workspaces/${workspace}/documents`);
  await page.goto('/');
  await pending.captured;
  await completedSearch(page, 'initialmarker');
  await expect(page.locator('.result-card')).toHaveCount(1);
  await page.locator('[data-view="library"]').click();
  await expect(page.locator('.loading')).toBeVisible();
  await pending.release();
  await expect(page.locator('.loading')).toHaveCount(0);
  await expect(page.locator(`[data-document="${doc.id}"]`)).toBeVisible();
  await page.locator('[data-view="history"]').click();
  await expect(page.locator('.history-row').filter({ hasText: 'initialmarker' })).toHaveCount(1);
});

test('real responses: an older search and document detail cannot replace newer results', async ({ page }) => {
  const auth = await register(page.request);
  const workspace = auth.workspaces[0].id;
  const first = await upload(page.request, workspace, 'Synthetic alpha document', 'alphamarker original evidence');
  const second = await upload(page.request, workspace, 'Synthetic beta document', 'betamarker current evidence');
  await ready(page);
  const oldSearch = await delayResponse(page, url => url.pathname.endsWith('/search') && url.searchParams.get('q') === 'alphamarker');
  await search(page, 'alphamarker');
  await oldSearch.captured;
  await completedSearch(page, 'betamarker');
  await expect(page.locator('.result-card')).toContainText(second.title);
  await oldSearch.release();
  await expect(page.locator('.result-card')).toHaveCount(1);
  await expect(page.locator('.result-card')).toContainText(second.title);
  await expect(page.locator('#search-input')).toHaveValue('betamarker');
  await page.locator('[data-view="library"]').click();
  const oldDetail = await delayResponse(page, url => url.pathname === `/api/documents/${first.id}`);
  await page.locator(`[data-document="${first.id}"]`).click();
  await oldDetail.captured;
  await page.locator(`[data-document="${second.id}"]`).click();
  await expect(page.locator('.source-heading h2')).toHaveText(second.title);
  await oldDetail.release();
  await expect(page.locator('.source-heading h2')).toHaveText(second.title);
  await expect(page.locator('#source-text')).toHaveText(second.content);
});

for (const kind of ['search', 'detail', 'load'] as const) {
  test(`real responses: workspace switch discards pending ${kind}`, async ({ page }) => {
    const auth = await register(page.request, 'Synthetic first workspace');
    const first = auth.workspaces[0].id;
    const oldDoc = await upload(page.request, first, 'Synthetic first document', 'firstmarker old evidence');
    const create = await page.request.post('/api/workspaces', { data: { name: 'Synthetic second workspace' } });
    expect(create.status()).toBe(201);
    const second = (await create.json()).id as string;
    const newDoc = await upload(page.request, second, 'Synthetic second document', 'secondmarker current evidence');
    await ready(page);
    await page.locator('#workspace-select').selectOption(first);
    await expect(page.locator(`[data-document="${oldDoc.id}"]`)).toBeVisible();
    if (kind === 'load') {
      await page.locator('#workspace-select').selectOption(second);
      await expect(page.locator(`[data-document="${newDoc.id}"]`)).toBeVisible();
    }
    const pending = await delayResponse(page, url => kind === 'detail'
      ? url.pathname === `/api/documents/${oldDoc.id}`
      : url.pathname === `/api/workspaces/${first}/${kind === 'load' ? 'documents' : 'search'}`);
    if (kind === 'search') await search(page, 'firstmarker');
    else if (kind === 'detail') await page.locator(`[data-document="${oldDoc.id}"]`).click();
    else await page.locator('#workspace-select').selectOption(first);
    await pending.captured;
    await page.locator('#workspace-select').selectOption(second);
    await expect(page.locator(`[data-document="${newDoc.id}"]`)).toBeVisible();
    await pending.release();
    await expect(page.locator('#workspace-select')).toHaveValue(second);
    await expect(page.locator(`[data-document="${oldDoc.id}"]`)).toHaveCount(0);
    await expect(page.locator('.source-pane, .result-card')).toHaveCount(0);
    await expect(page.locator('.loading')).toHaveCount(0);
    await completedSearch(page, 'secondmarker');
    await expect(page.locator('.result-card')).toHaveCount(1);
    await expect(page.locator('.result-card')).toContainText(newDoc.title);
  });
}

test('synthetic failure: delayed expired 401 from an old session cannot log out the new session', async ({ page }) => {
  const auth = await register(page.request);
  await ready(page);
  const expired = await delayResponse(page, url => url.pathname.endsWith('/search'), true);
  await search(page, 'synthetic-expired-request');
  await expired.captured;
  await page.getByRole('button', { name: '로그아웃' }).click();
  await expect(page.locator('#auth-form')).toBeVisible();
  await page.getByLabel('이메일', { exact: true }).fill(auth.user.email);
  await page.getByLabel('비밀번호', { exact: true }).fill(password);
  await page.locator('#auth-form').getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.locator('#workspace-select')).toBeVisible();
  await expect(page.locator('.loading')).toHaveCount(0);
  await expired.release();
  await expect(page.locator('#auth-form')).toHaveCount(0);
  await expect(page.locator('#workspace-select')).toBeVisible();
  await expect(page.locator('.error-banner')).toHaveCount(0);
  expect((await page.request.get('/api/auth/me')).status()).toBe(200);
});

test('real response: closing a pending upload and opening another modal preserves the new form', async ({ page }) => {
  await register(page.request);
  await ready(page);
  const pending = await delayResponse(page, (url, method) => method === 'POST' && /\/workspaces\/[^/]+\/documents$/.test(url.pathname));
  await page.locator('#upload').click();
  await page.getByRole('dialog').getByLabel('업로드할 문서 파일').setInputFiles({ name: 'synthetic-delayed.md', mimeType: 'text/markdown', buffer: Buffer.from('delayedmarker synthetic document') });
  await page.getByRole('dialog').getByRole('button', { name: '업로드', exact: true }).click();
  await pending.captured;
  await page.getByRole('dialog').getByRole('button', { name: '닫기', exact: true }).click();
  await page.locator('#new-workspace').click();
  await page.getByRole('dialog').getByLabel('워크스페이스 이름').fill('Synthetic untouched draft');
  await pending.release();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('dialog').getByLabel('워크스페이스 이름')).toHaveValue('Synthetic untouched draft');
  await expect(page.getByRole('dialog').getByRole('heading')).toHaveText('새 워크스페이스');
  await expect(page.getByRole('dialog').getByLabel('워크스페이스 이름')).toBeFocused();
  await expect(page.locator('.source-pane')).toHaveCount(0);
  // Closing a modal cannot cancel a server commit that already happened.
  await expect(page.locator('[data-document]')).toHaveCount(1);
  await page.getByRole('dialog').getByRole('button', { name: '닫기', exact: true }).click();
  await expect(page.locator('[data-document]')).toHaveCount(1);
});

test('real responses: dismissed edit cannot resurrect a later deletion or overwrite a replacement modal', async ({ page }) => {
  const auth = await register(page.request);
  const doc = await upload(page.request, auth.workspaces[0].id, 'Synthetic deleted document', 'deletedmarker synthetic content');
  await ready(page);
  await page.locator(`[data-document="${doc.id}"]`).click();
  await expect(page.locator('#source-text')).toHaveText(doc.content);
  const oldEdit = await delayResponse(page, (url, method) => method === 'PUT' && url.pathname === `/api/documents/${doc.id}`);
  await page.locator('#edit-document').click();
  await page.getByRole('dialog').getByLabel('원문 텍스트').fill('synthetic delayed older revision');
  await page.getByRole('button', { name: '변경 저장' }).click();
  await oldEdit.captured;
  await page.getByRole('dialog').getByRole('button', { name: '닫기', exact: true }).click();
  const pending = await delayResponse(page, (url, method) => method === 'DELETE' && url.pathname === `/api/documents/${doc.id}`);
  await page.locator('#delete-document').click();
  await page.getByRole('dialog').getByRole('button', { name: '문서 삭제', exact: true }).click();
  await pending.captured;
  await page.getByRole('dialog').getByRole('button', { name: '닫기', exact: true }).click();
  await page.locator('#new-workspace').click();
  await page.getByRole('dialog').getByLabel('워크스페이스 이름').fill('Synthetic preserved after delete');
  await pending.release();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('dialog').getByLabel('워크스페이스 이름')).toHaveValue('Synthetic preserved after delete');
  await expect(page.getByRole('dialog').getByLabel('워크스페이스 이름')).toBeFocused();
  await expect(page.locator(`[data-document="${doc.id}"], .source-pane`)).toHaveCount(0);
  await oldEdit.release();
  await expect(page.locator(`[data-document="${doc.id}"], .source-pane`)).toHaveCount(0);
  await expect(page.getByRole('dialog').getByLabel('워크스페이스 이름')).toHaveValue('Synthetic preserved after delete');
  await expect(page.getByRole('dialog').getByLabel('워크스페이스 이름')).toBeFocused();
  expect((await page.request.get(`/api/documents/${doc.id}`)).status()).toBe(404);
});

test('real responses: dismissed older edit cannot replace a later accepted revision', async ({ page }) => {
  const auth = await register(page.request);
  const doc = await upload(page.request, auth.workspaces[0].id, 'Synthetic revision document', 'originalmarker content');
  await ready(page);
  await page.locator(`[data-document="${doc.id}"]`).click();
  await expect(page.locator('#source-text')).toHaveText(doc.content);
  const older = await delayResponse(page, (url, method) => method === 'PUT' && url.pathname === `/api/documents/${doc.id}`);
  await page.locator('#edit-document').click();
  await page.getByRole('dialog').getByLabel('원문 텍스트').fill('oldermarker synthetic version two');
  await page.getByRole('button', { name: '변경 저장' }).click();
  await older.captured;
  await page.getByRole('dialog').getByRole('button', { name: '닫기', exact: true }).click();
  await page.locator('#edit-document').click();
  await page.getByRole('dialog').getByLabel('원문 텍스트').fill('latestmarker synthetic version three');
  await page.getByRole('button', { name: '변경 저장' }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await expect(page.locator('.source-badges')).toContainText('버전 3');
  await expect(page.locator('#source-text')).toHaveText('latestmarker synthetic version three');
  await older.release();
  await expect(page.locator('.source-badges')).toContainText('버전 3');
  await expect(page.locator('#source-text')).toHaveText('latestmarker synthetic version three');
  await expect(page.locator(`[data-document="${doc.id}"]`)).toContainText('v3');
  await completedSearch(page, 'oldermarker');
  await expect(page.locator('.result-card')).toHaveCount(0);
  await completedSearch(page, 'latestmarker');
  await expect(page.locator('.result-card')).toHaveCount(1);
});

test('real response: delayed logout still ends the session after switching workspace', async ({ page }) => {
  const auth = await register(page.request, 'Synthetic logout first workspace');
  const created = await page.request.post('/api/workspaces', { data: { name: 'Synthetic logout second workspace' } });
  expect(created.status()).toBe(201);
  const second = (await created.json()).id as string;
  await ready(page);
  await page.locator('#workspace-select').selectOption(auth.workspaces[0].id);
  await expect(page.locator('.loading')).toHaveCount(0);
  // Delay request delivery so the switch loads with the still-valid session;
  // this cannot accidentally pass because its load encounters a separate 401.
  const pending = await delayResponse(page, (url, method) => method === 'POST' && url.pathname === '/api/auth/logout', false, true);
  await page.getByRole('button', { name: '로그아웃' }).click();
  await pending.captured;
  await page.locator('#workspace-select').selectOption(second);
  await expect(page.locator('.loading')).toHaveCount(0);
  await expect(page.locator('#workspace-select')).toHaveValue(second);
  await pending.release();
  await expect(page.locator('#auth-form')).toBeVisible();
  await expect(page.locator('#workspace-select')).toHaveCount(0);
  expect((await page.request.get('/api/auth/me')).status()).toBe(401);
});

test('synthetic failure: late error from a closed modal does not appear in the replacement modal', async ({ page }) => {
  await register(page.request);
  await ready(page);
  // A real nonexistent-member request returns 404. Only response timing is synthetic.
  const pending = await delayResponse(page, (url, method) => method === 'POST' && url.pathname.endsWith('/members'));
  await page.locator('#members').click();
  await page.getByRole('dialog').getByLabel('가입한 이메일').fill('synthetic-missing-user@example.test');
  await page.getByRole('dialog').getByRole('button', { name: '멤버 추가', exact: true }).click();
  await pending.captured;
  await page.getByRole('dialog').getByRole('button', { name: '닫기', exact: true }).click();
  await page.locator('#new-workspace').click();
  await page.getByRole('dialog').getByLabel('워크스페이스 이름').fill('Synthetic clean draft');
  await pending.release();
  await expect(page.getByRole('dialog').getByLabel('워크스페이스 이름')).toHaveValue('Synthetic clean draft');
  await expect(page.getByRole('dialog').locator('.form-error')).toBeEmpty();
});
