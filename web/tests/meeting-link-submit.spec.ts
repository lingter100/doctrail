import type { APIRequestContext, Page } from '@playwright/test';
import { test, expect, register, ready, delayResponse } from './support';
import type { DecisionLink, MeetingDetail } from '../src/meetings';

// Real Java/SQLite/ACL/CAS and packaged React; extraction uses deterministic
// synthetic HTTP transport. LLM calls 0; no model-quality or human-review claim.
const quote = '이전 결정을 변경한다.';
const replacementQuote = '단계별 배포로 진행하기로 결정했다.';
const content = `SYNTHETIC_MEETING_TRANSPORT_FIXTURE\n합성 연결 저장 회의 2026-10-13\n${replacementQuote}\n민수는 후속 점검을 맡는다.\n${quote}`;
async function read(request: APIRequestContext, id: string) {
  const response = await request.get(`/api/meetings/${id}`);
  expect(response.status()).toBe(200);
  return await response.json() as MeetingDetail;
}
async function confirm(request: APIRequestContext, id: string) {
  await expect.poll(async () => (await read(request, id)).meeting.analysis_status).toBe('ready');
  const detail = await read(request, id);
  const analysis = structuredClone(detail.meeting.analysis!);
  analysis.items.find(item => item.type === 'decision')!.status = 'confirmed';
  const response = await request.put(`/api/meetings/${id}/analysis`, { data: {
    expected_revision: detail.document.revision, expected_version: detail.meeting.version, analysis,
  } });
  expect(response.status()).toBe(200);
  return await response.json() as MeetingDetail;
}
async function create(request: APIRequestContext, workspace: string, title: string) {
  const response = await request.post(`/api/workspaces/${workspace}/meetings/text`, {
    data: { title, content, visibility: 'workspace' },
  });
  expect(response.status()).toBe(201);
  return confirm(request, (await response.json() as MeetingDetail).document.id);
}
async function openForm(page: Page, source: MeetingDetail, target: MeetingDetail) {
  await ready(page);
  await page.locator('#workspace-select').selectOption(source.document.workspace_id);
  await page.locator('[data-view=meetings]').click();
  await page.locator(`[data-meeting="${source.document.id}"]`).click();
  await page.getByRole('button', { name: '결정 연결하기', exact: true }).click();
  const form = page.locator('.link-form');
  await form.getByLabel('현재 회의의 확정 결정').selectOption({ index: 1 });
  await form.getByLabel('연결할 회의').selectOption(target.document.id);
  await form.getByLabel('연결할 확정 결정').selectOption({ index: 1 });
  await form.getByLabel('연결 근거 · 현재 회의 원문에서 복사').fill(quote);
  return form;
}
async function links(request: APIRequestContext, id: string) {
  const response = await request.get(`/api/meetings/${id}/links`);
  expect(response.status()).toBe(200);
  return (await response.json() as { items: DecisionLink[] }).items;
}
async function setup(page: Page) {
  const auth = await register(page.request);
  const source = await create(page.request, auth.workspaces[0].id, '합성 현재 회의');
  const target = await create(page.request, auth.workspaces[0].id, '합성 저장 대상');
  return { source, target, form: await openForm(page, source, target) };
}

test('real Java: link POST target 404 retires cached target and requires explicit refreshed selection', async ({ page, playwright, baseURL }, info) => {
  const owner = await playwright.request.newContext({ baseURL });
  try {
    const reader = await register(page.request);
    const auth = await register(owner);
    const source = await create(page.request, reader.workspaces[0].id, '접근 유지할 현재 회의');
    const target = await create(owner, auth.workspaces[0].id, '접근 회수할 대상 제목');
    expect((await owner.post(`/api/workspaces/${auth.workspaces[0].id}/members`, { data: { email: reader.user.email } })).status()).toBe(201);
    const form = await openForm(page, source, target);
    let posts = 0, targetLists = 0;
    page.on('request', request => {
      const path = new URL(request.url()).pathname;
      if (request.method() === 'POST' && path === `/api/meetings/${source.document.id}/links`) posts++;
      if (request.method() === 'GET' && path === `/api/workspaces/${auth.workspaces[0].id}/meetings`) targetLists++;
    });
    expect((await owner.put(`/api/documents/${target.document.id}`, {
      data: { title: target.document.title, content, visibility: 'private' },
    })).status()).toBe(200);
    const denied = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === `/api/meetings/${source.document.id}/links`);
    await form.getByRole('button', { name: '확인한 결정 연결 저장' }).click();
    expect((await denied).status()).toBe(404);
    await expect(page.getByRole('alert')).toBeVisible();
    const afterDenial = {
      targetOptions: await form.getByLabel('연결할 회의').locator('option').allTextContents(),
      decisionOptions: await form.getByLabel('연결할 확정 결정').locator('option').allTextContents(),
      canSubmit: await form.getByRole('button', { name: '확인한 결정 연결 저장' }).isEnabled(),
    };
    const refreshed = page.waitForResponse(response => response.request().method() === 'GET' && new URL(response.url()).pathname === `/api/meetings/${source.document.id}/links`);
    await page.getByRole('button', { name: '새로 불러오기', exact: true }).click();
    await refreshed;
    await expect(page.getByRole('alert')).toHaveCount(0);
    const afterRefresh = {
      targetOptions: await form.getByLabel('연결할 회의').locator('option').allTextContents(),
      decisionOptions: await form.getByLabel('연결할 확정 결정').locator('option').allTextContents(),
      canSubmit: await form.getByRole('button', { name: '확인한 결정 연결 저장' }).isEnabled(),
      targetLists, posts,
    };
    await info.attach('actual-target-404-observation', { contentType: 'application/json', body: JSON.stringify({ afterDenial, afterRefresh, serverLinks: await links(page.request, source.document.id), realJava: true, llmCalls: 0 }, null, 2) });
    await page.screenshot({ path: info.outputPath('target-404-after-refresh.png'), fullPage: true });
    expect(afterDenial.targetOptions.join(' ')).not.toContain(target.document.title);
    expect(afterDenial.decisionOptions).toEqual(['결정 선택']);
    expect(afterDenial.canSubmit).toBe(false);
    expect(afterRefresh.targetLists).toBe(1);
    expect(afterRefresh.targetOptions.join(' ')).not.toContain(target.document.title);
    expect(afterRefresh.canSubmit).toBe(false);
    expect(posts).toBe(1);
    await expect(form.getByLabel('연결 근거 · 현재 회의 원문에서 복사')).toHaveValue(quote);
    expect((await page.request.get(`/api/meetings/${source.document.id}`)).status()).toBe(200);
    // Restore authorization and rebuild a current analysis. No automatic resend.
    expect((await owner.put(`/api/documents/${target.document.id}`, { data: { title: target.document.title, content, visibility: 'workspace' } })).status()).toBe(200);
    const restored = await read(owner, target.document.id);
    expect((await owner.post(`/api/meetings/${target.document.id}/analyze`, { data: { expected_revision: restored.document.revision } })).ok()).toBe(true);
    await confirm(owner, target.document.id);
    await page.getByRole('button', { name: '연결 닫기', exact: true }).click();
    await page.getByRole('button', { name: '결정 연결하기', exact: true }).click();
    await expect(form.getByLabel('연결할 회의').locator(`option[value="${target.document.id}"]`)).toHaveCount(1);
    await expect(form.getByLabel('연결할 회의')).toHaveValue('');
    await expect(form.getByLabel('현재 회의의 확정 결정')).toHaveValue('');
    await expect(form.getByLabel('연결할 확정 결정')).toHaveValue('');
    expect(posts).toBe(1);
    await form.getByLabel('현재 회의의 확정 결정').selectOption({ index: 1 });
    await form.getByLabel('연결할 회의').selectOption(target.document.id);
    await form.getByLabel('연결할 확정 결정').selectOption({ index: 1 });
    await form.getByLabel('연결 근거 · 현재 회의 원문에서 복사').fill(quote);
    const saved = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === `/api/meetings/${source.document.id}/links`);
    await form.getByRole('button', { name: '확인한 결정 연결 저장' }).click();
    expect((await saved).status()).toBe(201);
    expect(posts).toBe(2);
    expect(await links(page.request, source.document.id)).toHaveLength(1);
  } finally { await owner.dispose(); }
});

test('real Java: pending link POST locks fields and dismissal so late success cannot discard a replacement draft', async ({ page }, info) => {
  const { source, form } = await setup(page);
  let posts = 0;
  page.on('request', request => { if (request.method() === 'POST' && new URL(request.url()).pathname === `/api/meetings/${source.document.id}/links`) posts++; });
  const held = await delayResponse(page, (url, method) => method === 'POST' && url.pathname === `/api/meetings/${source.document.id}/links`);
  await form.getByRole('button', { name: '확인한 결정 연결 저장' }).click();
  await held.captured;
  expect(await links(page.request, source.document.id)).toHaveLength(1);
  const enabled = await form.locator('input, textarea, select').evaluateAll(elements => elements.filter(element => !element.matches(':disabled')).map(element => element.closest('label')?.textContent));
  const canCancel = await form.getByRole('button', { name: '취소', exact: true }).isEnabled();
  const canToggle = await page.getByRole('button', { name: '연결 닫기', exact: true }).isEnabled();
  const pendingNotice = await form.getByRole('status').allTextContents();
  let replacementDraft: string | null = null;
  // Preserve an actual pre-fix lost-draft witness, not just a disabled attribute.
  if (canCancel && canToggle) {
    await form.getByRole('button', { name: '취소', exact: true }).click();
    await page.getByRole('button', { name: '결정 연결하기', exact: true }).click();
    await form.getByLabel('연결 근거 · 현재 회의 원문에서 복사').fill(replacementQuote);
    replacementDraft = await form.getByLabel('연결 근거 · 현재 회의 원문에서 복사').inputValue();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('pending-link-form.png'), fullPage: true });
  await held.release();
  await expect(form).toHaveCount(0);
  const stored = await links(page.request, source.document.id);
  await info.attach('pending-link-observation', { contentType: 'application/json', body: JSON.stringify({ enabled, canCancel, canToggle, pendingNotice, replacementDraft, formClosed: true, storedQuote: stored[0].quote, posts, realJava: true, llmCalls: 0 }, null, 2) });
  expect(enabled).toEqual([]);
  expect(canCancel).toBe(false);
  expect(canToggle).toBe(false);
  expect(pendingNotice).toContain('연결 저장 중에는 내용을 수정하거나 닫을 수 없어요. 완료 후 새 연결을 작성해 주세요.');
  expect(stored[0].quote).toBe(quote);
  expect(posts).toBe(1);
  await page.getByRole('button', { name: '결정 연결하기', exact: true }).click();
  await expect(form.getByLabel('연결 근거 · 현재 회의 원문에서 복사')).toBeEnabled();
});

test('real Java + synthetic link POST 503: unlock retained draft without automatic resubmission', async ({ page }) => {
  const { source, form } = await setup(page);
  let posts = 0;
  let capture!: () => void, release!: () => void;
  const captured = new Promise<void>(done => { capture = done; });
  const released = new Promise<void>(done => { release = done; });
  await page.route(`**/api/meetings/${source.document.id}/links`, async route => {
    if (route.request().method() !== 'POST') return route.fallback();
    posts++; capture(); await released;
    await route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"synthetic_link_unavailable"}' });
  });
  await form.getByRole('button', { name: '확인한 결정 연결 저장' }).click();
  await captured;
  const locked = await form.locator('input, textarea, select').evaluateAll(elements => elements.every(element => element.matches(':disabled')));
  release();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(form.getByLabel('연결 근거 · 현재 회의 원문에서 복사')).toHaveValue(quote);
  await expect(form.getByLabel('연결 근거 · 현재 회의 원문에서 복사')).toBeEnabled();
  await expect(form.getByRole('button', { name: '취소', exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: '연결 닫기', exact: true })).toBeEnabled();
  await expect(form.getByRole('status')).toHaveCount(0);
  expect(await links(page.request, source.document.id)).toEqual([]);
  expect(posts).toBe(1);
  expect(locked).toBe(true);
});

test('real Java: ambiguous link POST 404 automatically rechecks and retires a deleted source', async ({ page }, info) => {
  const { source, form } = await setup(page);
  let posts = 0;
  page.on('request', request => { if (request.method() === 'POST' && new URL(request.url()).pathname === `/api/meetings/${source.document.id}/links`) posts++; });
  expect((await page.request.delete(`/api/documents/${source.document.id}`)).status()).toBe(204);
  const heldSource = await delayResponse(page, (url, method) => method === 'GET' && url.pathname === `/api/meetings/${source.document.id}`, false, true);
  const denied = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === `/api/meetings/${source.document.id}/links`);
  const checkedSource = page.waitForResponse(response => response.request().method() === 'GET' && new URL(response.url()).pathname === `/api/meetings/${source.document.id}`);
  await form.getByRole('button', { name: '확인한 결정 연결 저장' }).click();
  expect((await denied).status()).toBe(404);
  await heldSource.captured;
  await expect(page.getByRole('button', { name: '분석 편집', exact: true })).toBeDisabled();
  await expect(form.getByRole('button', { name: '취소', exact: true })).toBeDisabled();
  await heldSource.release();
  expect((await checkedSource).status()).toBe(404);
  await info.attach('source-post-404-observation', { contentType: 'application/json', body: JSON.stringify({ postStatus: 404, sourceTitle: source.document.title, posts, realJava: true, llmCalls: 0 }) });
  await expect(page.getByTestId('meeting-detail')).toHaveCount(0);
  await expect(form).toHaveCount(0);
  await expect(page.locator('.main-content')).not.toContainText(source.document.title);
  expect(posts).toBe(1);
});
