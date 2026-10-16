import type { APIRequestContext, Page, Route } from '@playwright/test';
import { test, expect, register, ready, delayResponse } from './support';
import type { DecisionLink, MeetingDetail } from '../src/meetings';

// Real Java, SQLite, authentication, decision links and packaged React. Analyses
// use the deterministic HTTP transport fixture, NOT an LLM or quality evidence.
const quote = '이전 결정을 변경한다.';
const content = `SYNTHETIC_MEETING_TRANSPORT_FIXTURE\n합성 연결 회의 2026-10-13\n단계별 배포로 진행하기로 결정했다.\n민수는 후속 점검을 맡는다.\n${quote}`;
async function create(request: APIRequestContext, workspace: string, title: string) {
  const response = await request.post(`/api/workspaces/${workspace}/meetings/text`, { data: { title, content, visibility: 'workspace' } });
  expect(response.status()).toBe(201);
  const initial = await response.json() as MeetingDetail;
  const path = `/api/meetings/${initial.document.id}`;
  await expect.poll(async () => (await (await request.get(path)).json() as MeetingDetail).meeting.analysis_status).toBe('ready');
  const detail = await (await request.get(path)).json() as MeetingDetail;
  const analysis = structuredClone(detail.meeting.analysis!);
  analysis.items.find(item => item.type === 'decision')!.status = 'confirmed';
  const confirmed = await request.put(`${path}/analysis`, { data: { expected_revision: detail.document.revision, expected_version: detail.meeting.version, analysis } });
  expect(confirmed.status()).toBe(200);
  return await confirmed.json() as MeetingDetail;
}
async function connect(request: APIRequestContext, source: MeetingDetail, target: MeetingDetail) {
  const start = Array.from(content.slice(0, content.indexOf(quote))).length;
  const response = await request.post(`/api/meetings/${source.document.id}/links`, { data: {
    target_meeting_id: target.document.id,
    source_item_id: source.meeting.analysis!.items.find(item => item.type === 'decision')!.id,
    target_item_id: target.meeting.analysis!.items.find(item => item.type === 'decision')!.id,
    expected_revision: source.document.revision, expected_version: source.meeting.version,
    target_expected_revision: target.document.revision, target_expected_version: target.meeting.version,
    relation: 'supersedes', quote, start_offset: start, end_offset: start + Array.from(quote).length,
  } });
  expect(response.status()).toBe(201);
  return await response.json() as DecisionLink;
}
async function setup(page: Page) {
  const auth = await register(page.request);
  const source = await create(page.request, auth.workspaces[0].id, '현재 합성 연결 회의');
  const first = await create(page.request, auth.workspaces[0].id, '해제할 합성 연결 회의');
  const link = await connect(page.request, source, first);
  return { auth, source, first, link, path: `/api/meetings/${source.document.id}/links` };
}
async function open(page: Page, source: MeetingDetail) {
  await ready(page); await page.locator('[data-view=meetings]').click();
  await page.locator(`[data-meeting="${source.document.id}"]`).click();
  await expect(page.locator('.decision-link')).toHaveCount(1);
}
const linkRow = (page: Page, title: string) => page.locator('.decision-link').filter({ hasText: title });
async function serverLinks(request: APIRequestContext, path: string) {
  const response = await request.get(path); expect(response.status()).toBe(200);
  return (await response.json() as { items: DecisionLink[] }).items;
}

test('real Java: delayed pre-delete links cannot restore a removed link or hide the new link', async ({ page }, testInfo) => {
  const { auth, source, first, link, path } = await setup(page);
  const second = await create(page.request, auth.workspaces[0].id, '유지할 새 합성 연결 회의');
  await open(page, source);
  await page.getByRole('button', { name: '결정 연결하기', exact: true }).click();
  const form = page.locator('.link-form');
  await form.getByLabel('현재 회의의 확정 결정').selectOption({ index: 1 });
  await form.getByLabel('연결할 회의').selectOption(second.document.id);
  await form.getByLabel('연결할 확정 결정').selectOption({ index: 1 });
  await form.getByLabel('연결 근거 · 현재 회의 원문에서 복사').fill(quote);
  const oldLinks = await delayResponse(page, (url, method) => url.pathname === path && method === 'GET');
  await page.getByRole('button', { name: '확인한 결정 연결 저장' }).click();
  await oldLinks.captured;
  // The server has both links, while the old visible link is still actionable.
  expect((await serverLinks(page.request, path)).map(item => item.target_id).sort()).toEqual([first.document.id, second.document.id].sort());
  const deleted = page.waitForResponse(response => new URL(response.url()).pathname === `${path}/${link.id}` && response.request().method() === 'DELETE');
  await linkRow(page, first.document.title).getByRole('button', { name: '연결 해제', exact: true }).click();
  expect((await deleted).status()).toBe(204);
  await expect(linkRow(page, first.document.title)).toHaveCount(0);
  expect((await serverLinks(page.request, path)).map(item => item.target_id)).toEqual([second.document.id]);
  await oldLinks.release();
  await expect(linkRow(page, first.document.title)).toHaveCount(0);
  await expect(linkRow(page, second.document.title)).toHaveCount(1);
  await expect(page.locator('.decision-link')).toHaveCount(1);
  await page.screenshot({ path: testInfo.outputPath('link-delete-stale-response.png'), fullPage: true });
});

test('real Java + synthetic DELETE failure: preserve the link and retry only on explicit action', async ({ page }) => {
  const { source, first, link, path } = await setup(page);
  await open(page, source);
  let deleteCount = 0;
  const failure = async (route: Route) => {
    if (route.request().method() !== 'DELETE' || new URL(route.request().url()).pathname !== `${path}/${link.id}`) return route.fallback();
    deleteCount++;
    await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'synthetic_delete_failure' }) });
  };
  await page.route('**/api/**', failure);
  await linkRow(page, first.document.title).getByRole('button', { name: '연결 해제', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(linkRow(page, first.document.title)).toHaveCount(1);
  await expect(linkRow(page, first.document.title).getByRole('button', { name: '연결 해제', exact: true })).toBeEnabled();
  expect((await serverLinks(page.request, path)).map(item => item.id)).toEqual([link.id]);
  expect(deleteCount).toBe(1);
  await page.unroute('**/api/**', failure);
  const deleted = page.waitForResponse(response => new URL(response.url()).pathname === `${path}/${link.id}` && response.request().method() === 'DELETE');
  await linkRow(page, first.document.title).getByRole('button', { name: '연결 해제', exact: true }).click();
  expect((await deleted).status()).toBe(204);
  await expect(page.locator('.decision-link')).toHaveCount(0);
  await expect(page.getByRole('alert')).toHaveCount(0);
  expect(await serverLinks(page.request, path)).toEqual([]);
});

test('real Java: delayed successful DELETE cannot reopen the old meeting after workspace movement', async ({ page }) => {
  const { source, first, link, path } = await setup(page);
  const response = await page.request.post('/api/workspaces', { data: { name: '합성 연결 이동 공간' } });
  expect(response.status()).toBe(201);
  const second = await response.json() as { id: string };
  await open(page, source);
  const deleted = await delayResponse(page, (url, method) => url.pathname === `${path}/${link.id}` && method === 'DELETE');
  await linkRow(page, first.document.title).getByRole('button', { name: '연결 해제', exact: true }).click();
  await deleted.captured;
  expect(await serverLinks(page.request, path)).toEqual([]);
  await page.locator('#workspace-select').selectOption(second.id);
  await deleted.release();
  await expect(page.locator('#workspace-select')).toHaveValue(second.id);
  await expect(page.getByTestId('meeting-detail')).toHaveCount(0);
  await expect(page.locator('.decision-link')).toHaveCount(0);
  await expect(page.locator('.main-content')).not.toContainText(source.document.title);
  await expect(page.locator('.meeting-notice')).toHaveCount(0);
});

test('real Java + synthetic failures: deleting during recovery leaves a failed fresh read retryable', async ({ page }) => {
  const { source, first, link, path } = await setup(page);
  await open(page, source);
  let failDelete = true, failLinks = false;
  const failures = async (route: Route) => {
    const method = route.request().method(), pathname = new URL(route.request().url()).pathname;
    if ((failDelete && method === 'DELETE' && pathname === `${path}/${link.id}`)
      || (failLinks && method === 'GET' && pathname === path)) {
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'synthetic_recovery_failure' }) });
    } else await route.fallback();
  };
  await page.route('**/api/**', failures);
  await linkRow(page, first.document.title).getByRole('button', { name: '연결 해제', exact: true }).click();
  const retry = page.getByRole('alert').getByRole('button', { name: '새로 불러오기', exact: true });
  await expect(retry).toBeEnabled();
  failDelete = false;
  const oldRefresh = await delayResponse(page, (url, method) => url.pathname === path && method === 'GET');
  await retry.click(); await oldRefresh.captured;
  // A recovery read leaves the existing link actionable. Its old finally must
  // not leave the new recovery action disabled after the deletion retires it.
  failLinks = true;
  const deleted = page.waitForResponse(response => new URL(response.url()).pathname === `${path}/${link.id}` && response.request().method() === 'DELETE');
  await linkRow(page, first.document.title).getByRole('button', { name: '연결 해제', exact: true }).click();
  expect((await deleted).status()).toBe(204);
  await expect(page.getByRole('alert')).toBeVisible();
  await oldRefresh.release();
  await expect(page.locator('.decision-link')).toHaveCount(0);
  await expect(retry).toBeEnabled();
  expect(await serverLinks(page.request, path)).toEqual([]);
  failLinks = false;
  const refreshed = page.waitForResponse(response => new URL(response.url()).pathname === path && response.request().method() === 'GET');
  await retry.click();
  expect((await refreshed).status()).toBe(200);
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.locator('.decision-link')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '분석 편집', exact: true })).toBeEnabled();
  await page.unroute('**/api/**', failures);
});
