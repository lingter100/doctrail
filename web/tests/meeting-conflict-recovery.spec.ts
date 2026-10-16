import type { Page } from '@playwright/test';
import { test, expect, register, ready, delayResponse } from './support';
import type { MeetingDetail } from '../src/meetings';

// Real Java authentication, SQLite, revision/version CAS and browser. The model
// HTTP boundary is a deterministic synthetic transport fixture, NOT an LLM.
// Only the explicitly named refresh failure below fabricates an HTTP error.
const content = 'SYNTHETIC_MEETING_TRANSPORT_FIXTURE\n합성 충돌 복구 회의 2026-10-13\n단계별 배포로 진행하기로 결정했다.\n민수는 후속 점검을 맡는다.';
const localSummary = '아직 저장하지 않은 내 초안';
const serverSummary = '다른 창에서 저장한 서버 요약';
async function setup(page: Page, withSecondWorkspace = false) {
  const auth = await register(page.request);
  const second = withSecondWorkspace
    ? await (await page.request.post('/api/workspaces', { data: { name: '복구 이후 다른 공간' } })).json() as { id: string }
    : null;
  const response = await page.request.post(`/api/workspaces/${auth.workspaces[0].id}/meetings/text`, {
    data: { title: '합성 충돌 복구 회의', content, visibility: 'workspace' },
  });
  expect(response.status()).toBe(201);
  const initial = await response.json() as MeetingDetail;
  const read = async () => await (await page.request.get(`/api/meetings/${initial.document.id}`)).json() as MeetingDetail;
  await expect.poll(async () => (await read()).meeting.analysis_status).toBe('ready');
  const doc = await read();
  await ready(page);
  await page.locator('[data-view=meetings]').click();
  await page.locator(`[data-meeting="${doc.document.id}"]`).click();
  await page.getByRole('button', { name: '분석 편집', exact: true }).click();
  await page.locator('.analysis-editor').getByRole('textbox', { name: '회의 요약', exact: true }).fill(localSummary);
  return { doc, read, second };
}
async function concurrentSave(page: Page, doc: MeetingDetail, summary = serverSummary) {
  const analysis = structuredClone(doc.meeting.analysis!);
  analysis.summary = summary;
  analysis.items.find(item => item.type === 'action')!.status = 'doing';
  const response = await page.request.put(`/api/meetings/${doc.document.id}/analysis`, {
    data: { expected_revision: doc.document.revision, expected_version: doc.meeting.version, analysis },
  });
  expect(response.status()).toBe(200);
  return await response.json() as MeetingDetail;
}
async function conflict(page: Page) {
  await page.getByRole('button', { name: '사용자 수정본 저장', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('변경되어 저장하지 않았어요');
  await expect(page.locator('.analysis-editor').getByRole('textbox', { name: '회의 요약', exact: true })).toHaveValue(localSummary);
  await expect(page.getByRole('button', { name: '사용자 수정본 저장', exact: true })).toBeDisabled();
}
async function inspectServer(page: Page) {
  await page.getByRole('button', { name: '서버 버전 확인', exact: true }).click();
  await expect(page.locator('.server-analysis')).toContainText(serverSummary);
  await expect(page.locator('.server-analysis')).toContainText('진행 중');
  await expect(page.locator('.analysis-editor').getByRole('textbox', { name: '회의 요약', exact: true })).toHaveValue(localSummary);
}

test('synthetic transport + real Java: inspect conflict, keep local explicitly, then deliberate fresh-version retry', async ({ page }, testInfo) => {
  const { doc, read } = await setup(page);
  const server = await concurrentSave(page, doc);
  const saves: { expected_revision: number; expected_version: number }[] = [];
  page.on('request', request => {
    if (request.method() === 'PUT' && new URL(request.url()).pathname === `/api/meetings/${doc.document.id}/analysis`) saves.push(request.postDataJSON());
  });
  await conflict(page);
  await inspectServer(page);
  expect(saves).toHaveLength(1);
  expect((await read()).meeting.version).toBe(server.meeting.version);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('conflict-comparison-mobile.png'), fullPage: true });
  await page.getByRole('button', { name: '내 초안 유지 · 저장은 나중에' }).click();
  await expect(page.locator('.edit-recovery')).toHaveCount(0);
  expect(saves).toHaveLength(1);
  expect((await read()).meeting.analysis!.summary).toBe(serverSummary);
  await expect(page.getByRole('button', { name: '사용자 수정본 저장', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '사용자 수정본 저장', exact: true }).click();
  await expect(page.locator('.analysis-editor')).toHaveCount(0);
  await expect(page.locator('.summary-copy')).toHaveText(localSummary);
  expect(saves).toHaveLength(2);
  expect(saves[1].expected_version).toBe(server.meeting.version);
  expect(saves[1].expected_revision).toBe(doc.document.revision);
  expect((await read()).meeting.analysis!.summary).toBe(localSummary);
});

test('synthetic transport + real Java: choosing server deliberately discards local without another PUT', async ({ page }) => {
  const { doc, read } = await setup(page);
  const server = await concurrentSave(page, doc);
  await conflict(page); await inspectServer(page);
  let additionalPuts = 0;
  page.on('request', request => { if (request.method() === 'PUT') additionalPuts++; });
  await page.getByRole('button', { name: '내 초안 버리고 서버 버전 사용' }).click();
  await expect(page.locator('.analysis-editor')).toHaveCount(0);
  await expect(page.locator('.summary-copy')).toHaveText(serverSummary);
  expect(additionalPuts).toBe(0);
  expect((await read()).meeting.version).toBe(server.meeting.version);
  await page.getByRole('button', { name: '분석 편집', exact: true }).click();
  await expect(page.locator('.analysis-editor').getByRole('textbox', { name: '회의 요약', exact: true })).toHaveValue(serverSummary);
});

test('synthetic transport + real Java with synthetic GET failure: failed refresh keeps draft and CAS survives another writer', async ({ page }) => {
  const { doc, read } = await setup(page);
  const server = await concurrentSave(page, doc);
  await conflict(page);
  const path = `**/api/meetings/${doc.document.id}`;
  await page.route(path, route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'synthetic_refresh_unavailable' }) }));
  await page.getByRole('button', { name: '서버 버전 확인', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('사용할 수 없어요');
  await expect(page.locator('.analysis-editor').getByRole('textbox', { name: '회의 요약', exact: true })).toHaveValue(localSummary);
  await expect(page.getByRole('button', { name: '사용자 수정본 저장', exact: true })).toBeDisabled();
  await expect(page.locator('.server-analysis')).toHaveCount(0);
  await page.unroute(path);
  await inspectServer(page);
  await page.getByRole('button', { name: '내 초안 유지 · 저장은 나중에' }).click();
  const newest = await concurrentSave(page, server, '확인 후에 도착한 또 다른 수정');
  await conflict(page);
  expect((await read()).meeting.version).toBe(newest.meeting.version);
  expect((await read()).meeting.analysis!.summary).toBe('확인 후에 도착한 또 다른 수정');
});

test('synthetic transport + real Java: changed document revision refuses stale evidence and items', async ({ page }) => {
  const { doc, read } = await setup(page);
  const response = await page.request.put(`/api/documents/${doc.document.id}`, {
    data: { title: doc.document.title, content: '새 원문에는 기존 결정과 담당자 근거가 없다.', visibility: 'workspace' },
  });
  expect(response.status()).toBe(200);
  await conflict(page);
  await page.getByRole('button', { name: '서버 버전 확인', exact: true }).click();
  await expect(page.locator('.edit-recovery')).toContainText('이전 근거와 항목을 그대로 저장할 수 없어요');
  await expect(page.getByRole('button', { name: '내 초안 유지 · 저장은 나중에' })).toBeDisabled();
  await expect(page.getByRole('button', { name: '사용자 수정본 저장', exact: true })).toBeDisabled();
  await expect(page.locator('.analysis-editor').getByRole('textbox', { name: '회의 요약', exact: true })).toHaveValue(localSummary);
  // A synthetic DOM submit also must not bypass the controller/form guard.
  let puts = 0;
  page.on('request', request => { if (request.method() === 'PUT') puts++; });
  await page.locator('.analysis-editor').evaluate(form => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  await page.getByRole('button', { name: '내 초안 버리고 서버 버전 사용' }).click();
  await expect(page.locator('.analysis-editor')).toHaveCount(0);
  await expect(page.locator('.meeting-detail .source-warning')).toContainText('현재 원문과 분석 버전이 달라요');
  expect(puts).toBe(0);
  expect((await read()).meeting.analysis_status).toBe('stale');
});

test('synthetic transport + real Java: delayed recovery cannot repopulate a different workspace', async ({ page }) => {
  const { doc, second } = await setup(page, true);
  await concurrentSave(page, doc); await conflict(page);
  const held = await delayResponse(page, (url, method) => url.pathname === `/api/meetings/${doc.document.id}` && method === 'GET');
  await page.getByRole('button', { name: '서버 버전 확인', exact: true }).click();
  await held.captured;
  await page.locator('#workspace-select').selectOption(second!.id);
  await held.release();
  await expect(page.getByTestId('meeting-detail')).toHaveCount(0);
  await expect(page.locator('.edit-recovery')).toHaveCount(0);
  await expect(page.locator('#workspace-select')).toHaveValue(second!.id);
  await expect(page.locator('.main-content')).not.toContainText(serverSummary);
});
