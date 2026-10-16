import type { APIRequestContext, Page } from '@playwright/test';
import { test, expect, register, upload, ready, completedSearch, delayResponse } from './support';

// Synthetic documents, real Java/SQLite/ACL/search. No evaluation data or LLM.
const query = 'recovermarker';
async function knowledge(page: Page) {
  await page.locator('[data-view=knowledge]').click();
  await page.getByRole('tab', { name: '원문 검색', exact: true }).click();
  await page.getByRole('combobox', { name: '검색 범위', exact: true }).selectOption('all');
  await page.getByRole('combobox', { name: '자료 종류', exact: true }).selectOption('document');
  await page.getByLabel('지식 질문').fill(query);
}
async function submit(page: Page) {
  const response = page.waitForResponse(r => r.url().endsWith('/api/knowledge/search'));
  await page.locator('.knowledge-form').getByRole('button', { name: '검색', exact: true }).click();
  expect((await response).status()).toBe(200);
  await expect(page.locator('.knowledge-hit')).toHaveCount(1);
}
async function revise(request: APIRequestContext, id: string, title: string, visibility = 'workspace') {
  const response = await request.put(`/api/documents/${id}`, { data: { title, content: `${query} revised source text`, visibility } });
  expect(response.status()).toBe(200);
  return response.json();
}

for (const priorSearch of [false, true]) {
  test(`real Java: stale knowledge source retries its own query and filters; prior legacy search=${priorSearch}`, async ({ page }, info) => {
    const auth = await register(page.request);
    const doc = await upload(page.request, auth.workspaces[0].id, 'Synthetic recovery source', `${query} original source text`);
    await ready(page);
    if (priorSearch) await completedSearch(page, 'unrelatedlegacy');
    await knowledge(page);
    const calls: { path: string; body: unknown }[] = [];
    page.on('request', request => {
      const path = new URL(request.url()).pathname;
      if (path.endsWith('/search')) calls.push({ path, body: request.postDataJSON() });
    });
    await submit(page);
    await revise(page.request, doc.id, doc.title);
    await page.locator('.knowledge-hit-open').click();
    await expect(page.locator('.source-warning')).toContainText('검색 이후 원문이 변경되었어요');
    await expect(page.locator('#source-text')).toContainText('revised source text');
    await expect(page.locator('#source-citation')).toHaveCount(0);
    await page.screenshot({ path: info.outputPath('stale-knowledge-before-retry.png'), fullPage: true });
    await page.locator('#search-again').click();
    await expect.poll(() => calls.length).toBe(2);
    expect(calls[1]).toEqual(calls[0]);
    await expect(page.getByRole('heading', { name: '지식 검색 · Q&A', exact: true })).toBeVisible();
    await expect(page.getByLabel('지식 질문')).toHaveValue(query);
    await expect(page.getByRole('combobox', { name: '검색 범위', exact: true })).toHaveValue('all');
    await expect(page.getByRole('combobox', { name: '자료 종류', exact: true })).toHaveValue('document');
    await expect(page.locator('.knowledge-hit')).toContainText('revised source text');
    await page.locator('.knowledge-hit-open').click();
    await expect(page.locator('#source-citation')).toContainText('revised source text');
  });
}

test('real Java: reader 404 removes obsolete knowledge text and count, retaining explicit re-search', async ({ page, playwright, baseURL }, info) => {
  const owner = await playwright.request.newContext({ baseURL });
  try {
    const auth = await register(owner);
    const workspace = auth.workspaces[0].id;
    const doc = await upload(owner, workspace, 'Synthetic revoked title', `${query} secret excerpt`);
    const reader = await register(page.request);
    expect((await owner.post(`/api/workspaces/${workspace}/members`, { data: { email: reader.user.email } })).status()).toBe(201);
    await ready(page);
    await page.locator('#workspace-select').selectOption(workspace);
    await knowledge(page); await submit(page);
    await revise(owner, doc.id, doc.title, 'private');
    const denied = page.waitForResponse(r => r.url().endsWith(`/api/documents/${doc.id}`));
    await page.locator('.knowledge-hit-open').click();
    expect((await denied).status()).toBe(404);
    await expect(page.locator('#toast')).toContainText('문서를 찾을 수 없거나 접근 권한이 변경되었어요');
    await page.screenshot({ path: info.outputPath('reader-404-observed.png'), fullPage: true });
    await expect(page.locator('.knowledge-hit')).toHaveCount(0);
    await expect(page.locator('.knowledge-results')).toHaveCount(0);
    await expect(page.locator('.main-content')).not.toContainText('secret excerpt');
    await expect(page.getByLabel('지식 질문')).toHaveValue(query);
    await expect(page.getByRole('combobox', { name: '자료 종류', exact: true })).toHaveValue('document');
    await page.locator('.knowledge-form').getByRole('button', { name: '검색', exact: true }).click();
    await expect(page.locator('.knowledge-results .count')).toHaveText('0');
    await revise(owner, doc.id, doc.title, 'workspace');
    await submit(page);
    await page.locator('.knowledge-hit-open').click();
    await expect(page.locator('#source-citation')).toContainText('revised source text');
  } finally { await owner.dispose(); }
});

test('real Java: ordinary search also discards a denied source and explicitly recovers after sharing', async ({ page, playwright, baseURL }) => {
  const owner = await playwright.request.newContext({ baseURL });
  try {
    const auth = await register(owner);
    const workspace = auth.workspaces[0].id;
    const doc = await upload(owner, workspace, 'Synthetic ordinary denied source', `${query} original source`);
    const reader = await register(page.request);
    expect((await owner.post(`/api/workspaces/${workspace}/members`, { data: { email: reader.user.email } })).status()).toBe(201);
    await ready(page); await page.locator('#workspace-select').selectOption(workspace);
    await completedSearch(page, query);
    await revise(owner, doc.id, doc.title, 'private');
    const denied = page.waitForResponse(r => r.url().endsWith(`/api/documents/${doc.id}`));
    await page.locator('[data-hit="0"]').click();
    expect((await denied).status()).toBe(404);
    await expect(page.locator('.result-card')).toHaveCount(0);
    await expect(page.locator('.source-pane')).toHaveCount(0);
    await expect(page.getByLabel('문서 검색어')).toHaveValue(query);
    await revise(owner, doc.id, doc.title, 'workspace');
    await completedSearch(page, query);
    await page.locator('[data-hit="0"]').click();
    await expect(page.locator('#source-citation')).toContainText('revised source text');
  } finally { await owner.dispose(); }
});

// These answer checks use the existing explicitly synthetic HTTP transport
// fixture through real Java validation. They make zero real LLM calls and do
// not assess answer semantics or generation quality.
const answerContent = 'SYNTHETIC_MEETING_TRANSPORT_FIXTURE\n단계별 배포로 진행하기로 결정했다.';
async function answer(page: Page) {
  await page.locator('[data-view=knowledge]').click();
  await page.getByRole('combobox', { name: '검색 범위', exact: true }).selectOption('all');
  await page.getByRole('combobox', { name: '자료 종류', exact: true }).selectOption('document');
  await page.getByLabel('지식 질문').fill('단계별 배포');
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  await expect(page.getByTestId('knowledge-answer')).toContainText('합성 전송 검사용 고정 답변');
}
test('synthetic answer transport + real Java: stale citation retries answer only on explicit action', async ({ page }, info) => {
  const auth = await register(page.request);
  const doc = await upload(page.request, auth.workspaces[0].id, 'Synthetic answer source', answerContent);
  await ready(page);
  const calls: unknown[] = [];
  page.on('request', request => { if (request.url().endsWith('/api/knowledge/answer')) calls.push(request.postDataJSON()); });
  await answer(page);
  expect((await page.request.put(`/api/documents/${doc.id}`, { data: { title: doc.title, content: `${answerContent}\n새 버전`, visibility: 'workspace' } })).status()).toBe(200);
  await page.locator('.citation-chip').click();
  await expect(page.locator('.source-warning')).toContainText('검색 이후 원문이 변경되었어요');
  await expect(page.locator('#source-citation')).toHaveCount(0);
  expect(calls).toHaveLength(1);
  await page.screenshot({ path: info.outputPath('stale-answer-explicit-retry.png'), fullPage: true });
  await page.locator('#search-again').click();
  await expect(page.getByTestId('knowledge-answer')).toContainText('합성 전송 검사용 고정 답변');
  expect(calls).toHaveLength(2); expect(calls[1]).toEqual(calls[0]);
  await page.locator('.citation-chip').click();
  await expect(page.locator('#source-citation')).toHaveText('단계별 배포로 진행하기로 결정했다.');
  await expect(page.locator('.source-badges')).toContainText('버전 2');
});

test('synthetic answer transport + real Java: reader denial clears answer claims without automatic resend', async ({ page, playwright, baseURL }, info) => {
  const owner = await playwright.request.newContext({ baseURL });
  try {
    const auth = await register(owner);
    const doc = await upload(owner, auth.workspaces[0].id, 'Synthetic revoked answer', answerContent);
    const reader = await register(page.request);
    expect((await owner.post(`/api/workspaces/${auth.workspaces[0].id}/members`, { data: { email: reader.user.email } })).status()).toBe(201);
    await ready(page);
    let calls = 0;
    page.on('request', request => { if (request.url().endsWith('/api/knowledge/answer')) calls++; });
    await answer(page);
    expect((await owner.put(`/api/documents/${doc.id}`, { data: { title: doc.title, content: answerContent, visibility: 'private' } })).status()).toBe(200);
    const denied = page.waitForResponse(r => r.url().endsWith(`/api/documents/${doc.id}`));
    await page.locator('.citation-chip').click();
    expect((await denied).status()).toBe(404);
    await expect(page.getByTestId('knowledge-answer')).toHaveCount(0);
    await expect(page.locator('.knowledge-results')).toHaveCount(0);
    await expect(page.locator('.main-content')).not.toContainText('합성 전송 검사용 고정 답변');
    await expect(page.getByLabel('지식 질문')).toHaveValue('단계별 배포');
    expect(calls).toBe(1);
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath('answer-denied-mobile.png'), fullPage: true });
    await page.getByRole('button', { name: '질문하기', exact: true }).click();
    await expect(page.getByTestId('knowledge-answer')).toContainText('답변을 보류했어요');
    await expect(page.locator('.knowledge-results .count')).toHaveText('0');
    expect(calls).toBe(2);
  } finally { await owner.dispose(); }
});

test('real Java plus one synthetic 503: failed source read retains usable knowledge results', async ({ page }) => {
  const auth = await register(page.request);
  const doc = await upload(page.request, auth.workspaces[0].id, 'Synthetic transient source', `${query} original source`);
  await ready(page); await knowledge(page); await submit(page);
  await page.route(`**/api/documents/${doc.id}`, route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'synthetic_source_unavailable' }) }), { times: 1 });
  await page.locator('.knowledge-hit-open').click();
  await expect(page.locator('#toast')).toContainText('요청을 완료하지 못했어요');
  await expect(page.locator('.knowledge-hit')).toHaveCount(1);
  await expect(page.locator('.source-pane')).toHaveCount(0);
  await page.locator('.knowledge-hit-open').click();
  await expect(page.locator('#source-citation')).toContainText('original source');
});

test('real Java: query, filters, mode, navigation and workspace changes cancel delayed source origins', async ({ page }) => {
  const auth = await register(page.request);
  const workspace = auth.workspaces[0].id;
  const doc = await upload(page.request, workspace, 'Synthetic delayed source', `${query} original source`);
  const second = await (await page.request.post('/api/workspaces', { data: { name: 'Synthetic second workspace' } })).json();
  await ready(page);
  for (const change of ['query', 'filter', 'mode', 'navigation', 'workspace']) {
    await page.locator('[data-view=library]').click();
    await knowledge(page); await submit(page);
    const held = await delayResponse(page, (url, method) => url.pathname === `/api/documents/${doc.id}` && method === 'GET');
    await page.locator('.knowledge-hit-open').click(); await held.captured;
    if (change === 'query') await page.getByLabel('지식 질문').fill('changedmarker');
    if (change === 'filter') await page.getByRole('combobox', { name: '자료 종류', exact: true }).selectOption('meeting');
    if (change === 'mode') await page.getByRole('tab', { name: '근거 기반 답변', exact: true }).click();
    if (change === 'navigation') await page.locator('[data-view=library]').click();
    if (change === 'workspace') await page.locator('#workspace-select').selectOption(second.id);
    await held.release();
    await expect(page.locator('.source-pane')).toHaveCount(0);
    await expect(page.locator('.knowledge-results')).toHaveCount(0);
    if (change === 'workspace') await expect(page.locator('#workspace-select')).toHaveValue(second.id);
  }
});
