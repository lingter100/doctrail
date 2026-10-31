import type { Page } from '@playwright/test';
import { test, expect, register, upload, ready, password, delayResponse } from './support';
import type { KnowledgeHistory } from '../src/types';

const saved: KnowledgeHistory = {
  id: 'history-one', operation: 'answer', query: 'Synthetic deployment question', workspace_id: null, kind: 'meeting',
  filters: { meeting_id: 'meeting-one', date_from: '2026-10-01', date_to: '2026-10-27', participant: 'Synthetic participant', assignee: 'Synthetic owner', item_type: 'action', limit: 7 },
  method: 'hybrid', embedding_profile: { id: 'old', model: 'old-model', revision: 'old-revision' }, generation_model: null,
  status: 'abstained', reason: 'no_evidence', model_called: false, created_at: '2026-10-27T01:00:00Z', result_count: 0,
};
const auth = { user: { id: 'user-one', email: 'synthetic@example.test', name: 'Synthetic user' }, workspaces: [{ id: 'workspace-one', name: '첫 작업공간', role: 'owner' }, { id: 'workspace-two', name: '두 번째 작업공간', role: 'owner' }] };
const response = { history_id: 'search-one', query: 'synthetic marker', method: 'bm25', results: [{ result_id: 'result-one', document_id: 'document-one', workspace_id: 'workspace-one', document_kind: 'document', title: 'Synthetic source', filename: 'synthetic.md', revision: 1, chunk_id: 'chunk-one', text: 'synthetic marker evidence', page: null, score: 1, meeting_date: null }] };
function latch() { let resolve!: () => void; const promise = new Promise<void>(done => { resolve = done; }); return { promise, resolve }; }
async function mock(page: Page, history: KnowledgeHistory[] = [saved]) {
  const calls: { path: string; body: Record<string, unknown> }[] = [];
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === 'POST') calls.push({ path, body: route.request().postDataJSON() });
    let json: unknown;
    if (path.endsWith('/auth/me')) json = auth;
    else if (path.endsWith('/search/capabilities')) json = { default_method: 'bm25', model_enabled: true, status: 'ready', methods: ['bm25', 'hybrid'], available_methods: ['bm25', 'hybrid'], embedding_profile: { id: 'new', model: 'new-model', revision: 'new-revision' } };
    else if (path.endsWith('/knowledge/history')) json = { items: history };
    else if (path.endsWith('/knowledge/search')) json = response;
    else if (path.endsWith('/knowledge/answer')) json = { ...response, status: 'abstained', reason: 'no_evidence', model_called: false, results: [] };
    else if (path.endsWith('/feedback')) json = { ok: true };
    else if (/\/workspaces\/[^/]+\/(documents|history)$/.test(path)) json = { items: [] };
    else if (path.endsWith('/auth/logout')) json = { ok: true };
    else throw new Error('Unexpected mock request: ' + path);
    await route.fulfill({ json });
  });
  await ready(page); return calls;
}
async function historyTab(page: Page) {
  await page.locator('[data-view=history]').click();
  await page.getByRole('tab', { name: '통합 검색·질문', exact: true }).click();
}
async function searchUI(page: Page) {
  await page.locator('[data-view=knowledge]').click();
  await page.getByRole('tab', { name: '원문 검색', exact: true }).click();
  await page.getByLabel('지식 질문').fill('synthetic marker');
  await page.locator('.knowledge-form').getByRole('button', { name: '검색', exact: true }).click();
}

test('UI contract: restore every condition without requests; keyboard explicit execution and 1440/390 layout', async ({ page }, info) => {
  const calls = await mock(page); await historyTab(page);
  await expect(page.locator('.knowledge-history-row')).toContainText('모든 워크스페이스');
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath('history-' + width + '.png'), fullPage: true });
  }
  await page.locator('.knowledge-history-row').focus(); await page.keyboard.press('Enter');
  await expect(page.getByLabel('지식 질문')).toHaveValue(saved.query);
  await expect(page.getByLabel('지식 질문')).toBeFocused();
  await expect(page.getByRole('combobox', { name: '검색 범위', exact: true })).toHaveValue('all');
  await expect(page.getByRole('combobox', { name: '자료 종류', exact: true })).toHaveValue('meeting');
  for (const [label, value] of [['회의 시작일', '2026-10-01'], ['회의 종료일', '2026-10-27'], ['참석자', 'Synthetic participant'], ['작업 담당자', 'Synthetic owner'], ['항목 종류', 'action'], ['최대 근거 수', '7']]) await expect(label === '항목 종류' ? page.getByRole('combobox', { name: label, exact: true }) : page.getByLabel(label, { exact: true })).toHaveValue(value);
  await expect(page.getByRole('combobox', { name: '검색 방식', exact: true })).toHaveValue('hybrid');
  await expect(page.getByText('특정 회의 · 저장된 회의로 제한됨', { exact: true })).toBeVisible();
  await expect(page.getByTestId('knowledge-restore-notice')).toContainText('현재 모델 설정이 달라요');
  await expect(page.getByTestId('knowledge-restore-notice')).toContainText('답변 모델 정보가 없어요');
  expect(calls).toHaveLength(0); await expect(page.locator('.knowledge-results')).toHaveCount(0);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath('restore-' + width + '.png'), fullPage: true });
  }
  await page.getByRole('button', { name: '질문하기', exact: true }).focus(); await page.keyboard.press('Enter');
  await expect(page.getByTestId('knowledge-answer')).toBeVisible();
  expect(calls).toEqual([{ path: '/api/knowledge/answer', body: { query: saved.query, workspace_id: null, kind: 'meeting', ...saved.filters, method: 'hybrid', expected_embedding_profile: 'new' } }]);
  expect(await page.evaluate(() => Object.values(localStorage).join(''))).not.toContain(saved.query);
});

test('UI contract: exact saved workspace retained; inaccessible scope is not substituted', async ({ page }) => {
  await mock(page, [{ ...saved, workspace_id: 'missing-workspace', method: 'bm25' }]); await historyTab(page);
  await page.locator('.knowledge-history-row').click();
  await expect(page.getByRole('combobox', { name: '검색 범위', exact: true })).toHaveValue('missing-workspace');
  await expect(page.getByRole('alert')).toContainText('범위를 임의로 바꾸지 않았어요');
  await expect(page.getByRole('button', { name: '질문하기', exact: true })).toBeDisabled();
  await page.getByRole('combobox', { name: '검색 범위', exact: true }).selectOption('workspace-two');
  await expect(page.getByRole('button', { name: '질문하기', exact: true })).toBeEnabled();
});

test('UI contract: feedback pending, explicit retry and opposite assessment target result id', async ({ page }, info) => {
  await mock(page, []); await searchUI(page);
  const entered = latch(), release = latch(); let count = 0; const payloads: unknown[] = [];
  await page.route('**/api/knowledge/history/*/feedback', async route => {
    payloads.push(route.request().postDataJSON()); count++;
    if (count === 1) { entered.resolve(); await release.promise; await route.fulfill({ status: 503, json: { detail: 'synthetic_failure' } }); }
    else await route.fulfill({ json: { ok: true } });
  });
  await page.getByRole('button', { name: '1번 근거 관련 있음', exact: true }).click(); await entered.promise;
  await expect(page.locator('.knowledge-feedback')).toContainText('피드백 저장 중');
  await expect(page.getByRole('button', { name: '1번 근거 관련 없음', exact: true })).toBeDisabled();
  release.resolve(); await expect(page.getByRole('button', { name: '피드백 다시 저장' })).toBeVisible(); expect(count).toBe(1);
  await page.getByRole('button', { name: '피드백 다시 저장' }).click();
  await expect(page.getByRole('button', { name: '1번 근거 관련 있음', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: '1번 근거 관련 없음', exact: true }).click();
  await expect(page.getByRole('button', { name: '1번 근거 관련 없음', exact: true })).toHaveAttribute('aria-pressed', 'true');
  expect(payloads).toEqual([{ result_id: 'result-one', relevant: true }, { result_id: 'result-one', relevant: true }, { result_id: 'result-one', relevant: false }]);
  await page.setViewportSize({ width: 390, height: 900 }); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('feedback-390.png'), fullPage: true });
});

for (const boundary of ['navigate', 'workspace', 'logout'] as const) test('UI contract: delayed history and feedback ignored after ' + boundary, async ({ page }) => {
  await mock(page);
  const entered = latch(), release = latch(), finished = latch();
  await page.route('**/api/knowledge/history', async route => { entered.resolve(); await release.promise; await route.fulfill({ json: { items: [saved] } }); finished.resolve(); });
  await historyTab(page); await entered.promise;
  if (boundary === 'navigate') await page.locator('[data-view=library]').click();
  if (boundary === 'workspace') await page.locator('#workspace-select').selectOption('workspace-two');
  if (boundary === 'logout') await page.locator('#logout').click();
  release.resolve(); await finished.promise;
  await page.evaluate(() => new Promise<void>(done => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
  await expect(page.locator('.knowledge-history-row')).toHaveCount(0); await expect(page.getByLabel('지식 질문')).toHaveCount(0);
  if (boundary === 'logout') { await expect(page.locator('#workspace-select')).toHaveCount(0); return; }
  await searchUI(page); await expect(page.locator('.knowledge-hit')).toHaveCount(1);
  const feedbackEntered = latch(), feedbackRelease = latch(), feedbackFinished = latch();
  await page.route('**/api/knowledge/history/*/feedback', async route => { feedbackEntered.resolve(); await feedbackRelease.promise; await route.fulfill({ status: 401, json: { detail: 'synthetic_old_session' } }); feedbackFinished.resolve(); });
  await page.getByRole('button', { name: '1번 근거 관련 있음', exact: true }).click(); await feedbackEntered.promise;
  if (boundary === 'navigate') await page.locator('[data-view=library]').click(); else await page.locator('#workspace-select').selectOption('workspace-one');
  feedbackRelease.resolve(); await feedbackFinished.promise;
  await page.evaluate(() => new Promise<void>(done => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
  await expect(page.locator('#workspace-select')).toBeVisible(); await expect(page.locator('.knowledge-feedback')).toHaveCount(0);
});

test('real Java: search, per-result feedback, history after relogin, null scope restore and explicit rerun', async ({ page }, info) => {
  const account = await register(page.request);
  await upload(page.request, account.workspaces[0].id, 'Synthetic history source', 'historymarker synthetic evidence');
  await ready(page); await page.locator('[data-view=knowledge]').click();
  await page.getByRole('tab', { name: '원문 검색', exact: true }).click();
  await page.getByRole('combobox', { name: '검색 범위', exact: true }).selectOption('all');
  await page.getByRole('combobox', { name: '자료 종류', exact: true }).selectOption('document');
  await page.getByLabel('지식 질문').fill('historymarker');
  const completed = page.waitForResponse(r => r.url().endsWith('/api/knowledge/search'));
  await page.locator('.knowledge-form').getByRole('button', { name: '검색', exact: true }).click();
  const result = await (await completed).json(); expect(result.history_id).toBeTruthy(); expect(result.results[0].result_id).toBeTruthy();
  await page.getByRole('button', { name: '1번 근거 관련 있음', exact: true }).click();
  await expect(page.locator('.knowledge-feedback')).toContainText('피드백이 저장됐어요');
  await page.getByRole('button', { name: '1번 근거 관련 없음', exact: true }).click();
  await expect(page.getByRole('button', { name: '1번 근거 관련 없음', exact: true })).toHaveAttribute('aria-pressed', 'true');
  expect((await page.request.post('/api/auth/logout')).status()).toBe(204);
  expect((await page.request.post('/api/auth/login', { data: { email: account.user.email, password } })).status()).toBe(200);
  await ready(page); let calls = 0;
  page.on('request', request => { if (/\/api\/knowledge\/(search|answer)$/.test(request.url())) calls++; });
  await historyTab(page); await page.locator('[data-knowledge-history="' + result.history_id + '"]').click();
  expect(calls).toBe(0); await expect(page.getByRole('combobox', { name: '검색 범위', exact: true })).toHaveValue('all');
  await expect(page.getByRole('combobox', { name: '자료 종류', exact: true })).toHaveValue('document');
  await expect(page.locator('.knowledge-results')).toHaveCount(0);
  await page.locator('.knowledge-form').getByRole('button', { name: '검색', exact: true }).click();
  await expect(page.locator('.knowledge-hit')).toHaveCount(1); expect(calls).toBe(1);
  await page.screenshot({ path: info.outputPath('real-history-restored.png'), fullPage: true });
  await page.getByRole('tab', { name: '근거 기반 답변', exact: true }).click();
  const noEvidenceQuery = 'qzxhistoryabsenceonly';
  const emptySearch = await page.request.post('/api/knowledge/search', { data: { query: noEvidenceQuery, workspace_id: null, kind: 'document', method: 'bm25', limit: 5 } });
  expect(emptySearch.status()).toBe(200); expect((await emptySearch.json()).results).toEqual([]);
  await page.getByLabel('지식 질문').fill(noEvidenceQuery);
  const abstained = page.waitForResponse(r => r.url().endsWith('/api/knowledge/answer'));
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  const answerResponse = await abstained; expect(answerResponse.status()).toBe(200);
  const answer = await answerResponse.json(); expect(answer.status).toBe('abstained'); expect(answer.model_called).toBe(false); expect(answer.history_id).toBeTruthy();
  await historyTab(page); await expect(page.locator('[data-knowledge-history="' + answer.history_id + '"]')).toContainText('답변 보류');
  const beforeRestore = calls; await page.locator('[data-knowledge-history="' + answer.history_id + '"]').click();
  await expect(page.getByRole('tab', { name: '근거 기반 답변', exact: true })).toHaveAttribute('aria-selected', 'true'); expect(calls).toBe(beforeRestore);
});

test('UI contract: failed history fetch has explicit retry and keeps document history available', async ({ page }) => {
  await mock(page); let attempts = 0;
  await page.route('**/api/knowledge/history', async route => { attempts++; if (attempts === 1) await route.fulfill({ status: 503, json: { detail: 'synthetic_history_error' } }); else await route.fulfill({ json: { items: [saved] } }); });
  await historyTab(page); await expect(page.getByRole('button', { name: '기록 다시 불러오기' })).toBeVisible(); expect(attempts).toBe(1);
  await page.getByRole('button', { name: '기록 다시 불러오기' }).click(); await expect(page.locator('.knowledge-history-row')).toHaveCount(1);
  await page.getByRole('tab', { name: '문서 검색', exact: true }).click(); await expect(page.getByRole('heading', { name: '최근 검색', exact: false })).toBeVisible();
});

test('UI contract: late search after logout attempt never revives results, even when logout fails', async ({ page }) => {
  await mock(page, []); const entered = latch(), release = latch(), finished = latch();
  await page.route('**/api/knowledge/search', async route => { entered.resolve(); await release.promise; await route.fulfill({ json: response }); finished.resolve(); });
  await page.route('**/api/auth/logout', route => route.fulfill({ status: 503, json: { detail: 'synthetic_logout_failure' } }));
  await searchUI(page); await entered.promise;
  await page.locator('#logout').click(); await expect(page.locator('#toast')).toContainText('요청을 완료하지 못했어요');
  release.resolve(); await finished.promise;
  await page.evaluate(() => new Promise<void>(done => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
  await expect(page.locator('.knowledge-results')).toHaveCount(0); await expect(page.locator('#workspace-select')).toBeVisible();
  await expect(page.locator('.knowledge-form').getByRole('button', { name: '검색', exact: true })).toBeEnabled();
});

test('real Java: current ACL/revision/deletion invalidate feedback and retained all-scope history has no stale evidence', async ({ page, playwright, baseURL }) => {
  const owner = await playwright.request.newContext({ baseURL });
  try {
    const ownerAccount = await register(owner), reader = await register(page.request);
    const workspace = ownerAccount.workspaces[0].id;
    expect((await owner.post('/api/workspaces/' + workspace + '/members', { data: { email: reader.user.email } })).status()).toBe(201);
    const doc = await upload(owner, workspace, 'Synthetic access history', 'synthetic marker evidence');
    await ready(page); await page.locator('#workspace-select').selectOption(workspace); await searchUI(page);
    await expect(page.locator('.knowledge-hit')).toHaveCount(1);
    expect((await owner.put('/api/documents/' + doc.id, { data: { title: doc.title, content: 'synthetic marker revised evidence', visibility: 'workspace' } })).status()).toBe(200);
    await page.getByRole('button', { name: '1번 근거 관련 있음', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('원문이 변경되어 피드백을 저장하지 않았어요'); await expect(page.locator('.knowledge-hit')).toHaveCount(0);
    await page.getByRole('button', { name: '다시 시도', exact: true }).click(); await expect(page.locator('.knowledge-hit')).toHaveCount(1);
    expect((await owner.put('/api/documents/' + doc.id, { data: { title: doc.title, content: 'synthetic marker private evidence', visibility: 'private' } })).status()).toBe(200);
    await page.getByRole('button', { name: '1번 근거 관련 없음', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('자료를 확인할 수 없어요'); await expect(page.locator('.knowledge-hit')).toHaveCount(0);
    await historyTab(page); await expect(page.locator('.knowledge-history-row').first()).toContainText('근거 0개');
    expect((await owner.put('/api/documents/' + doc.id, { data: { title: doc.title, content: 'synthetic marker shared evidence', visibility: 'workspace' } })).status()).toBe(200);
    await searchUI(page); await expect(page.locator('.knowledge-hit')).toHaveCount(1);
    expect((await owner.delete('/api/documents/' + doc.id)).status()).toBe(204);
    await page.getByRole('button', { name: '1번 근거 관련 있음', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('자료를 확인할 수 없어요'); await expect(page.locator('.knowledge-hit')).toHaveCount(0);
    await historyTab(page); await expect(page.locator('.knowledge-history-row').first()).toContainText('근거 0개');
    const delayed = await delayResponse(page, (url, method) => url.pathname === '/api/knowledge/history' && method === 'GET');
    await page.getByRole('button', { name: '기록 새로고침', exact: true }).click(); await delayed.captured;
    await page.locator('[data-view=library]').click(); await delayed.release(); await expect(page.locator('.knowledge-history-row')).toHaveCount(0);
  } finally { await owner.dispose(); }
});

test('UI contract: history logout failure cancels pending list and offers explicit refresh', async ({ page }) => {
  await mock(page); const entered = latch(), release = latch(), finished = latch();
  await page.route('**/api/knowledge/history', async route => { entered.resolve(); await release.promise; await route.fulfill({ json: { items: [saved] } }); finished.resolve(); });
  await page.route('**/api/auth/logout', route => route.fulfill({ status: 503, json: { detail: 'synthetic_logout_failure' } }));
  await historyTab(page); await entered.promise; await page.locator('#logout').click(); await expect(page.locator('#toast')).toContainText('요청을 완료하지 못했어요');
  release.resolve(); await finished.promise;
  await page.evaluate(() => new Promise<void>(done => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
  await expect(page.locator('.knowledge-history-row')).toHaveCount(0); await expect(page.getByRole('button', { name: '기록 새로고침' })).toBeEnabled();
  await page.getByRole('button', { name: '기록 새로고침' }).click(); await expect(page.locator('.knowledge-history-row')).toHaveCount(1);
});

test('UI contract: saved workspace is independent of sidebar and missing profile requires explicit execution', async ({ page }) => {
  const calls = await mock(page, [{ ...saved, operation: 'search', workspace_id: 'workspace-two', embedding_profile: null }]);
  await historyTab(page); await page.locator('.knowledge-history-row').click();
  await expect(page.locator('#workspace-select')).toHaveValue('workspace-one');
  await expect(page.getByRole('combobox', { name: '검색 범위', exact: true })).toHaveValue('workspace-two');
  await expect(page.getByTestId('knowledge-restore-notice')).toContainText('검색 모델 정보가 없어'); expect(calls).toHaveLength(0);
  await page.locator('.knowledge-form').getByRole('button', { name: '검색', exact: true }).click();
  await expect(page.locator('.knowledge-hit')).toHaveCount(1); expect(calls[0].body.workspace_id).toBe('workspace-two'); expect(calls[0].body.limit).toBe(7);
  await expect(page.getByTestId('knowledge-restore-notice')).toHaveCount(0);
});

for (const outcome of ['success', 'failure'] as const) test('UI contract: KH-F1 delayed history ' + outcome + ' survives changing only the document search method', async ({ page }) => {
  const calls = await mock(page), entered = latch(), release = latch(); let attempts = 0;
  await page.route('**/api/knowledge/history', async route => {
    attempts++;
    if (attempts === 1) { entered.resolve(); await release.promise; }
    if (attempts === 1 && outcome === 'failure') await route.fulfill({ status: 503, json: { detail: 'synthetic_history_failure' } });
    else await route.fulfill({ json: { items: [saved] } });
  });
  await historyTab(page); await entered.promise;
  await page.locator('#search-method').selectOption('hybrid'); await expect(page.locator('#search-method')).toHaveValue('hybrid');
  release.resolve();
  if (outcome === 'success') await expect(page.locator('.knowledge-history-row')).toHaveCount(1);
  else await expect(page.getByRole('button', { name: '기록 다시 불러오기', exact: true })).toBeVisible();
  await expect(page.locator('.loading')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '기록 새로고침', exact: true })).toBeEnabled();
  expect(attempts).toBe(1); expect(calls).toHaveLength(0);
  await page.getByRole('button', { name: outcome === 'success' ? '기록 새로고침' : '기록 다시 불러오기', exact: true }).click();
  await expect(page.locator('.knowledge-history-row')).toHaveCount(1); expect(attempts).toBe(2); expect(calls).toHaveLength(0);
});

test('UI contract: superseded history response cannot end the newer request or expire its session', async ({ page }) => {
  const calls = await mock(page), oldEntered = latch(), oldRelease = latch(), oldFinished = latch(), newEntered = latch(), newRelease = latch(); let attempts = 0;
  await page.route('**/api/knowledge/history', async route => {
    const attempt = ++attempts;
    if (attempt === 1) { oldEntered.resolve(); await oldRelease.promise; await route.fulfill({ status: 401, json: { detail: 'synthetic_old_session' } }); oldFinished.resolve(); }
    else { newEntered.resolve(); await newRelease.promise; await route.fulfill({ json: { items: [{ ...saved, id: 'new-history', query: 'New synthetic history' }] } }); }
  });
  await historyTab(page); await oldEntered.promise;
  await page.getByRole('tab', { name: '문서 검색', exact: true }).click(); await page.getByRole('tab', { name: '통합 검색·질문', exact: true }).click(); await newEntered.promise;
  await page.locator('#search-method').selectOption('hybrid');
  oldRelease.resolve(); await oldFinished.promise;
  await page.evaluate(() => new Promise<void>(done => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
  await expect(page.locator('#workspace-select')).toBeVisible(); await expect(page.locator('.loading')).toHaveCount(1);
  await expect(page.getByRole('button', { name: '기록 새로고침', exact: true })).toBeDisabled();
  newRelease.resolve(); await expect(page.locator('.knowledge-history-row')).toHaveText(/New synthetic history/);
  await expect(page.locator('.loading')).toHaveCount(0); expect(calls).toHaveLength(0);
});


test('UI contract: explicit answer fallback updates search default in both request and form while other limits stay deliberate', async ({ page }) => {
  const calls = await mock(page, [{ ...saved, method: 'bm25' }]); await historyTab(page); await page.locator('.knowledge-history-row').click();
  await page.route('**/api/knowledge/answer', route => route.fulfill({ status: 503, json: { detail: 'generation_language_mismatch' } }));
  await expect(page.getByLabel('최대 근거 수', { exact: true })).toHaveValue('7');
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  await expect(page.getByRole('button', { name: '원문 검색으로 확인', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '원문 검색으로 확인', exact: true }).click();
  await expect(page.locator('.knowledge-hit')).toHaveCount(1);
  expect(calls).toHaveLength(1); expect(calls[0].path).toBe('/api/knowledge/search');
  expect(calls[0].body).toMatchObject({ query: saved.query, workspace_id: null, kind: saved.kind, ...saved.filters, limit: 10, method: 'bm25' });
  await expect(page.getByRole('tab', { name: '원문 검색', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByLabel('최대 근거 수', { exact: true })).toHaveValue('10');
  await page.locator('.knowledge-form').getByRole('button', { name: '검색', exact: true }).click();
  await expect(page.locator('.knowledge-hit')).toHaveCount(1); expect(calls[1].body.limit).toBe(10);
  await page.getByLabel('최대 근거 수', { exact: true }).fill('4'); expect(calls).toHaveLength(2);
  await page.locator('.knowledge-form').getByRole('button', { name: '검색', exact: true }).click();
  await expect(page.locator('.knowledge-hit')).toHaveCount(1); expect(calls[2].body.limit).toBe(4);
  await page.getByRole('tab', { name: '근거 기반 답변', exact: true }).click();
  await expect(page.getByLabel('최대 근거 수', { exact: true })).toHaveValue('5'); expect(calls).toHaveLength(3);
});
