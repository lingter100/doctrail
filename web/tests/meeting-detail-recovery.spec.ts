import type { APIRequestContext, Page } from '@playwright/test';
import { test, expect, register, ready, delayResponse } from './support';
import type { MeetingDetail } from '../src/meetings';

// Actual Java/SQLite/ACL/CAS and packaged UI; analysis transport is synthetic, LLM0.
const quote = '이전 결정을 변경한다.';
const content = `SYNTHETIC_MEETING_TRANSPORT_FIXTURE\n합성 상세 복구 회의 2026-10-13\n단계별 배포로 진행하기로 결정했다.\n민수는 후속 점검을 맡는다.\n${quote}`;
async function read(request: APIRequestContext, id: string) {
  const response = await request.get(`/api/meetings/${id}`); expect(response.status()).toBe(200);
  return await response.json() as MeetingDetail;
}
async function create(request: APIRequestContext, workspace: string, title: string) {
  const response = await request.post(`/api/workspaces/${workspace}/meetings/text`, { data: { title, content, visibility: 'workspace' } });
  expect(response.status()).toBe(201);
  const initial = await response.json() as MeetingDetail;
  await expect.poll(async () => (await read(request, initial.document.id)).meeting.analysis_status).toBe('ready');
  const detail = await read(request, initial.document.id);
  const analysis = structuredClone(detail.meeting.analysis!);
  analysis.items.find(item => item.type === 'decision')!.status = 'confirmed';
  analysis.items.find(item => item.type === 'action')!.assignee = '비공개 담당자';
  return save(request, detail, analysis);
}
async function save(request: APIRequestContext, detail: MeetingDetail, analysis = structuredClone(detail.meeting.analysis!)) {
  const response = await request.put(`/api/meetings/${detail.document.id}/analysis`, { data: { expected_revision: detail.document.revision, expected_version: detail.meeting.version, analysis } });
  expect(response.status()).toBe(200); return await response.json() as MeetingDetail;
}
async function openForm(page: Page, source: MeetingDetail, target: MeetingDetail) {
  await ready(page); await page.locator('[data-view=meetings]').click();
  await page.locator(`[data-meeting="${source.document.id}"]`).click();
  await page.getByRole('button', { name: '결정 연결하기', exact: true }).click();
  const form = page.locator('.link-form');
  await form.getByLabel('현재 회의의 확정 결정').selectOption({ index: 1 });
  await form.getByLabel('연결할 회의').selectOption(target.document.id);
  await form.getByLabel('연결할 확정 결정').selectOption({ index: 1 });
  await form.getByLabel('연결 근거 · 현재 회의 원문에서 복사').fill(quote);
  return form;
}
async function submit(page: Page, id: string) {
  const response = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith(`/api/meetings/${id}/links`));
  await page.getByRole('button', { name: '확인한 결정 연결 저장' }).click();
  return await response;
}

test('real Java reader: direct detail 404 clears cached task title assignee and count', async ({ page, playwright, baseURL }, info) => {
  const owner = await playwright.request.newContext({ baseURL });
  try {
    const auth = await register(owner); const workspace = auth.workspaces[0].id;
    const doc = await create(owner, workspace, '접근 회수할 비공개 제목');
    const reader = await register(page.request);
    expect((await owner.post(`/api/workspaces/${workspace}/members`, { data: { email: reader.user.email } })).status()).toBe(201);
    await ready(page); await page.locator('#workspace-select').selectOption(workspace);
    await page.locator('[data-view=actions]').click();
    await expect(page.locator('.task-row')).toHaveCount(1);
    expect((await owner.put(`/api/documents/${doc.document.id}`, { data: { title: doc.document.title, content, visibility: 'private' } })).status()).toBe(200);
    const response = page.waitForResponse(r => r.url().endsWith(`/api/meetings/${doc.document.id}`));
    await page.locator('.task-row').click(); expect((await response).status()).toBe(404);
    await page.screenshot({ path: info.outputPath('actual-reader-404.png'), fullPage: true });
    await expect(page.locator('.task-row')).toHaveCount(0);
    await expect(page.locator('.meeting-toolbar')).toHaveCount(0);
    await expect(page.locator('.main-content')).not.toContainText(doc.document.title);
    await expect(page.locator('.main-content')).not.toContainText('비공개 담당자');
    await page.getByRole('button', { name: '목록 다시 불러오기' }).click();
    await expect(page.locator('.meeting-toolbar')).toContainText('0개 작업');
  } finally { await owner.dispose(); }
});

test('real Java link: target-only version conflict refresh allows explicit reviewed retry', async ({ page }, info) => {
  const auth = await register(page.request);
  const source = await create(page.request, auth.workspaces[0].id, '현재 연결 회의');
  const target = await create(page.request, auth.workspaces[0].id, '대상 연결 회의');
  const form = await openForm(page, source, target);
  const analysis = structuredClone(target.meeting.analysis!); analysis.items.find(item => item.type === 'action')!.assignee = '다른 담당자';
  const latest = await save(page.request, target, analysis);
  expect(latest.meeting.version).toBeGreaterThan(target.meeting.version);
  expect((await submit(page, source.document.id)).status()).toBe(409);
  await page.getByRole('button', { name: '새로 불러오기', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(form.getByLabel('연결 근거 · 현재 회의 원문에서 복사')).toHaveValue(quote);
  await expect(form.getByLabel('현재 회의의 확정 결정')).toHaveValue('');
  await expect(form.getByLabel('연결할 확정 결정')).toHaveValue('');
  expect((await (await page.request.get(`/api/meetings/${source.document.id}/links`)).json()).items).toHaveLength(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('explicit-link-review-mobile.png'), fullPage: true });
  await form.getByLabel('현재 회의의 확정 결정').selectOption({ index: 1 });
  await form.getByLabel('연결할 확정 결정').selectOption({ index: 1 });
  const retried = await submit(page, source.document.id);
  await info.attach('retry-response', { body: JSON.stringify({ status: retried.status(), body: await retried.json() }), contentType: 'application/json' });
  expect(retried.status()).toBe(201);
});

for (const scenario of ['refresh-denial', 'late-list', 'workspace-navigation'] as const) {
  test(`real Java reader: ${scenario} owns access invalidation`, async ({ page, playwright, baseURL }) => {
    const owner = await playwright.request.newContext({ baseURL });
    try {
      const auth = await register(owner); const workspace = auth.workspaces[0].id;
      const doc = await create(owner, workspace, '회수할 회의');
      const reader = await register(page.request);
      expect((await owner.post(`/api/workspaces/${workspace}/members`, { data: { email: reader.user.email } })).status()).toBe(201);
      await ready(page); await page.locator('#workspace-select').selectOption(workspace);
      await page.locator('[data-view=actions]').click(); await expect(page.locator('.task-row')).toHaveCount(1);
      if (scenario === 'refresh-denial') {
        // Explicit synthetic transient links failure exposes the existing retry;
        // the subsequent ACL mutation and detail 404 are real Java.
        await page.route(`**/api/meetings/${doc.document.id}/links`, route => route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"synthetic_links_unavailable"}' }));
        await page.locator('.task-row').click(); await expect(page.getByRole('alert')).toBeVisible();
        await page.unroute(`**/api/meetings/${doc.document.id}/links`);
      }
      const held = scenario === 'late-list'
        ? await delayResponse(page, (url, method) => url.pathname === `/api/workspaces/${workspace}/meetings` && method === 'GET')
        : scenario === 'workspace-navigation' ? await delayResponse(page, url => url.pathname === `/api/meetings/${doc.document.id}`) : null;
      if (scenario === 'late-list') { await page.getByRole('button', { name: '목록 새로고침', exact: true }).click(); await held!.captured; }
      expect((await owner.put(`/api/documents/${doc.document.id}`, { data: { title: doc.document.title, content, visibility: 'private' } })).status()).toBe(200);
      if (scenario === 'refresh-denial') await page.getByRole('button', { name: '새로 불러오기', exact: true }).click();
      else await page.locator('.task-row').click();
      if (scenario === 'workspace-navigation') {
        await held!.captured;
        await page.locator('#workspace-select').selectOption(reader.workspaces[0].id);
        await page.locator('[data-view=actions]').click();
        await expect(page.locator('.meeting-toolbar')).toContainText('0개 작업');
        await held!.release();
        await expect(page.getByRole('alert')).toHaveCount(0);
        await expect(page.locator('.meeting-toolbar')).toContainText('0개 작업');
      } else {
        await expect(page.locator('[data-testid=meeting-list-error]')).toBeVisible();
        if (held) await held.release();
        await expect(page.locator('.task-row')).toHaveCount(0);
        await expect(page.locator('[data-testid=meeting-detail]')).toHaveCount(0);
        await expect(page.locator('.meeting-toolbar')).toHaveCount(0);
        await page.getByRole('button', { name: '목록 다시 불러오기' }).click();
        await expect(page.locator('.meeting-toolbar')).toContainText('0개 작업');
      }
    } finally { await owner.dispose(); }
  });
}

for (const scenario of ['target-decision-change', 'source-version', 'source-revision', 'reload-failure', 'target-list-denial'] as const) {
  test(`real Java link conflict: ${scenario} requires explicit review`, async ({ page }) => {
    const auth = await register(page.request); const workspace = auth.workspaces[0].id;
    const source = await create(page.request, workspace, '현재 검토 회의');
    const target = await create(page.request, workspace, '대상 검토 회의');
    const form = await openForm(page, source, target);
    let posts = 0;
    page.on('request', r => { if (r.method() === 'POST' && r.url().endsWith(`/api/meetings/${source.document.id}/links`)) posts++; });
    if (scenario === 'source-revision') {
      expect((await page.request.put(`/api/documents/${source.document.id}`, { data: { title: source.document.title, content: `${content}\n새 원문`, visibility: 'workspace' } })).status()).toBe(200);
    } else {
      const changed = scenario === 'source-version' ? source : target;
      const analysis = structuredClone(changed.meeting.analysis!);
      if (scenario === 'target-decision-change') analysis.items.find(item => item.type === 'decision')!.text = '사용자가 바꾼 결정 의미';
      else analysis.items.find(item => item.type === 'action')!.assignee = '변경 담당자';
      await save(page.request, changed, analysis);
    }
    expect((await submit(page, source.document.id)).status()).toBe(409);
    await expect(page.getByRole('button', { name: '확인한 결정 연결 저장' })).toBeDisabled();
    if (scenario === 'reload-failure' || scenario === 'target-list-denial') {
      // Only target LIST denial is synthetic: the source detail/links retain
      // actual Java 200. This must not be mistaken for source access denial.
      await page.route(`**/api/workspaces/${workspace}/meetings`, route => route.fulfill({ status: scenario === 'target-list-denial' ? 403 : 503, contentType: 'application/json', body: '{"detail":"synthetic_targets_unavailable"}' }));
      await page.getByRole('button', { name: '새로 불러오기', exact: true }).click();
      await expect(page.locator('.error-banner').filter({ hasText: scenario === 'target-list-denial' ? '이 작업에 대한 권한' : '사용할 수 없어요' })).toBeVisible();
      if (scenario === 'target-list-denial') expect((await page.request.get(`/api/meetings/${source.document.id}`)).status()).toBe(200);
      await expect(form.getByLabel('연결 근거 · 현재 회의 원문에서 복사')).toHaveValue(quote);
      await expect(page.getByRole('button', { name: '확인한 결정 연결 저장' })).toBeDisabled();
      if (scenario === 'target-list-denial') {
        await expect(page.locator('[data-testid=meeting-detail]')).toBeVisible();
        await expect(form.getByLabel('연결할 확정 결정').locator('option')).toHaveCount(1);
        expect((await page.request.get(`/api/meetings/${source.document.id}`)).status()).toBe(200);
      }
      expect(posts).toBe(1);
      await page.unroute(`**/api/workspaces/${workspace}/meetings`);
    }
    await page.getByRole('button', { name: '새로 불러오기', exact: true }).click();
    await expect(page.getByRole('alert')).toHaveCount(0);
    expect(posts).toBe(1);
    await expect(form.getByLabel('현재 회의의 확정 결정')).toHaveValue('');
    await expect(form.getByLabel('연결할 확정 결정')).toHaveValue('');
    await expect(form.getByLabel('연결 근거 · 현재 회의 원문에서 복사')).toHaveValue(quote);
    if (scenario === 'source-revision') {
      await expect(page.getByRole('button', { name: '확인한 결정 연결 저장' })).toBeDisabled();
      await expect(page.locator('.source-warning')).toContainText('현재 원문과 분석 버전이 달라요');
    } else {
      if (scenario === 'target-decision-change') await expect(form.getByLabel('연결할 확정 결정')).toContainText('사용자가 바꾼 결정 의미');
      await form.getByLabel('현재 회의의 확정 결정').selectOption({ index: 1 });
      await form.getByLabel('연결할 확정 결정').selectOption({ index: 1 });
      expect((await submit(page, source.document.id)).status()).toBe(201);
      expect(posts).toBe(2);
    }
  });
}
