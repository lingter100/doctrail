import type { APIRequestContext, Page } from '@playwright/test';
import { test, expect, register, ready, delayResponse } from './support';
import type { MeetingDetail } from '../src/meetings';

// Real Java/SQLite/ACL and packaged React. Only analysis HTTP uses the
// deterministic transport fixture; no model inference or quality judgments.
const content = 'SYNTHETIC_MEETING_TRANSPORT_FIXTURE\n합성 원문 접근 회의 2026-10-13\n단계별 배포로 진행하기로 결정했다.\n민수는 후속 점검을 맡는다.';
async function create(request: APIRequestContext, workspace: string, title: string) {
  const response = await request.post(`/api/workspaces/${workspace}/meetings/text`, { data: { title, content, visibility: 'workspace' } });
  expect(response.status()).toBe(201);
  const initial = await response.json() as MeetingDetail;
  await expect.poll(async () => (await (await request.get(`/api/meetings/${initial.document.id}`)).json()).meeting.analysis_status).toBe('ready');
  return await (await request.get(`/api/meetings/${initial.document.id}`)).json() as MeetingDetail;
}
async function hide(owner: APIRequestContext, doc: MeetingDetail) {
  expect((await owner.put(`/api/documents/${doc.document.id}`, { data: { title: doc.document.title, content, visibility: 'private' } })).status()).toBe(200);
}
async function openSource(page: Page, entry: 'full' | 'evidence') {
  if (entry === 'full') await page.getByRole('button', { name: '전체 원문', exact: true }).click();
  else await page.locator('.analysis-section.decision .evidence-button').click();
}
for (const entry of ['full', 'evidence'] as const) {
  test(`real Java reader: ${entry} source 404 hides cached meeting and tasks`, async ({ page, playwright, baseURL }, info) => {
    const owner = await playwright.request.newContext({ baseURL });
    try {
      const auth = await register(owner);
      const doc = await create(owner, auth.workspaces[0].id, '원문 접근 회수 제목');
      const reader = await register(page.request);
      expect((await owner.post(`/api/workspaces/${auth.workspaces[0].id}/members`, { data: { email: reader.user.email } })).status()).toBe(201);
      await ready(page); await page.locator('#workspace-select').selectOption(auth.workspaces[0].id);
      await page.locator('[data-view=actions]').click();
      const initialLinks = page.waitForResponse(r => new URL(r.url()).pathname === `/api/meetings/${doc.document.id}/links`);
      await page.locator('.task-row').click(); expect((await initialLinks).status()).toBe(200);
      await expect(page.getByTestId('meeting-detail')).toBeVisible();
      await hide(owner, doc);
      const denied = page.waitForResponse(r => new URL(r.url()).pathname === `/api/documents/${doc.document.id}`);
      await openSource(page, entry); expect((await denied).status()).toBe(404);
      await page.screenshot({ path: info.outputPath('actual-source-404.png'), fullPage: true });
      await expect(page.getByTestId('meeting-detail')).toHaveCount(0);
      await expect(page.locator('.task-row')).toHaveCount(0);
      await expect(page.locator('.main-content')).not.toContainText(doc.document.title);
      await page.getByRole('button', { name: '목록 다시 불러오기', exact: true }).click();
      await expect(page.locator('.meeting-toolbar')).toContainText('0개 작업');
    } finally { await owner.dispose(); }
  });
}

for (const navigation of ['meeting', 'back', 'workspace'] as const) {
  test(`real Java reader: delayed source 404 cannot reclaim ${navigation}`, async ({ page, playwright, baseURL }) => {
    const owner = await playwright.request.newContext({ baseURL });
    try {
      const auth = await register(owner);
      const doc = await create(owner, auth.workspaces[0].id, '지연 회수 원문');
      const reader = await register(page.request);
      expect((await owner.post(`/api/workspaces/${auth.workspaces[0].id}/members`, { data: { email: reader.user.email } })).status()).toBe(201);
      const other = await create(page.request, auth.workspaces[0].id, '유지할 다른 회의');
      await ready(page); await page.locator('#workspace-select').selectOption(auth.workspaces[0].id);
      await page.locator('[data-view=meetings]').click();
      const initialLinks = page.waitForResponse(r => new URL(r.url()).pathname === `/api/meetings/${doc.document.id}/links`);
      await page.locator(`[data-meeting="${doc.document.id}"]`).click(); expect((await initialLinks).status()).toBe(200);
      await hide(owner, doc);
      const held = await delayResponse(page, (url, method) => url.pathname === `/api/documents/${doc.document.id}` && method === 'GET');
      await openSource(page, 'full'); await held.captured;
      if (navigation === 'workspace') await page.locator('#workspace-select').selectOption(reader.workspaces[0].id);
      else {
        await page.getByRole('button', { name: '← 목록으로', exact: true }).click();
        await expect(page.locator(`[data-meeting="${other.document.id}"]`)).toBeVisible();
        if (navigation === 'meeting') {
          await page.locator(`[data-meeting="${other.document.id}"]`).click();
          await page.getByRole('button', { name: '분석 편집', exact: true }).click();
          await page.locator('.analysis-editor').getByRole('textbox', { name: '회의 요약', exact: true }).fill('다른 회의의 보존할 초안');
        }
      }
      await held.release();
      await expect(page.locator('.source-pane')).toHaveCount(0);
      if (navigation === 'meeting') {
        await expect(page.locator('.meeting-detail-heading h2')).toHaveText(other.document.title);
        await expect(page.locator('.analysis-editor').getByRole('textbox', { name: '회의 요약', exact: true })).toHaveValue('다른 회의의 보존할 초안');
      }
      else await expect(page.getByTestId('meeting-detail')).toHaveCount(0);
      if (navigation === 'back') await expect(page.locator(`[data-meeting="${other.document.id}"]`)).toBeVisible();
      if (navigation === 'workspace') await expect(page.locator('#workspace-select')).toHaveValue(reader.workspaces[0].id);
      await expect(page.locator('.error-banner')).toHaveCount(0);
    } finally { await owner.dispose(); }
  });
}

for (const status of [500, 503]) {
  test(`real Java owner + synthetic source ${status}: keep unsaved editor and retry explicitly`, async ({ page }) => {
    const auth = await register(page.request);
    const doc = await create(page.request, auth.workspaces[0].id, '일시 오류 회의');
    await ready(page); await page.locator('[data-view=meetings]').click();
    await page.locator(`[data-meeting="${doc.document.id}"]`).click();
    await page.getByRole('button', { name: '분석 편집', exact: true }).click();
    await page.locator('.analysis-editor').getByRole('textbox', { name: '회의 요약', exact: true }).fill('보존할 미저장 초안');
    let puts = 0;
    page.on('request', r => { if (r.method() === 'PUT') puts++; });
    await page.route(`**/api/documents/${doc.document.id}`, route => route.fulfill({ status, contentType: 'application/json', body: '{"detail":"synthetic_source_failure"}' }), { times: 1 });
    const failed = page.waitForResponse(r => new URL(r.url()).pathname === `/api/documents/${doc.document.id}`);
    await openSource(page, 'full'); expect((await failed).status()).toBe(status);
    await expect(page.locator('#toast')).toContainText('요청을 완료하지 못했어요');
    await expect(page.locator('.analysis-editor').getByRole('textbox', { name: '회의 요약', exact: true })).toHaveValue('보존할 미저장 초안');
    await openSource(page, 'full'); await expect(page.locator('#source-text')).toHaveText(content);
    await expect(page.locator('.analysis-editor').getByRole('textbox', { name: '회의 요약', exact: true })).toHaveValue('보존할 미저장 초안');
    expect(puts).toBe(0);
  });
}

test('real Java owner + synthetic source 403 retires editor', async ({ page }) => {
  const auth = await register(page.request);
  const doc = await create(page.request, auth.workspaces[0].id, '합성 거부 회의');
  await ready(page); await page.locator('[data-view=meetings]').click();
  await page.locator(`[data-meeting="${doc.document.id}"]`).click();
  await page.getByRole('button', { name: '분석 편집', exact: true }).click();
  await page.locator('.analysis-editor').getByRole('textbox', { name: '회의 요약', exact: true }).fill('거부 뒤 숨길 초안');
  await page.route(`**/api/documents/${doc.document.id}`, route => route.fulfill({ status: 403, contentType: 'application/json', body: '{"detail":"synthetic_access_denied"}' }));
  const denied = page.waitForResponse(r => new URL(r.url()).pathname === `/api/documents/${doc.document.id}`);
  await openSource(page, 'full'); expect((await denied).status()).toBe(403);
  await expect(page.getByTestId('meeting-detail')).toHaveCount(0);
  await expect(page.locator('.analysis-editor')).toHaveCount(0);
  await expect(page.locator('.meeting-card')).toHaveCount(0);
});

test('real Java reader: denied linked source hides links but preserves the current meeting', async ({ page, playwright, baseURL }) => {
  const owner = await playwright.request.newContext({ baseURL });
  try {
    const auth = await register(owner);
    const source = await create(owner, auth.workspaces[0].id, '회수할 연결 원문');
    const target = await create(owner, auth.workspaces[0].id, '유지할 현재 회의');
    for (const doc of [source, target]) {
      const analysis = structuredClone(doc.meeting.analysis!);
      analysis.items.find(item => item.type === 'decision')!.status = 'confirmed';
      const saved = await owner.put(`/api/meetings/${doc.document.id}/analysis`, { data: { expected_revision: doc.document.revision, expected_version: doc.meeting.version, analysis } });
      expect(saved.status()).toBe(200); Object.assign(doc, await saved.json());
    }
    const quote = '단계별 배포로 진행하기로 결정했다.';
    const start_offset = Array.from(content.slice(0, content.indexOf(quote))).length;
    expect((await owner.post(`/api/meetings/${source.document.id}/links`, { data: {
      target_meeting_id: target.document.id,
      source_item_id: source.meeting.analysis!.items.find(item => item.type === 'decision')!.id,
      target_item_id: target.meeting.analysis!.items.find(item => item.type === 'decision')!.id,
      expected_revision: source.document.revision, expected_version: source.meeting.version,
      target_expected_revision: target.document.revision, target_expected_version: target.meeting.version,
      relation: 'related', quote, start_offset, end_offset: start_offset + Array.from(quote).length,
    } })).status()).toBe(201);
    const reader = await register(page.request);
    expect((await owner.post(`/api/workspaces/${auth.workspaces[0].id}/members`, { data: { email: reader.user.email } })).status()).toBe(201);
    await ready(page); await page.locator('#workspace-select').selectOption(auth.workspaces[0].id);
    await page.locator('[data-view=meetings]').click(); await page.locator(`[data-meeting="${target.document.id}"]`).click();
    await expect(page.locator('.decision-link')).toHaveCount(1);
    await hide(owner, source);
    const denied = page.waitForResponse(r => new URL(r.url()).pathname === `/api/documents/${source.document.id}`);
    await page.locator('.decision-link .evidence-button').click(); expect((await denied).status()).toBe(404);
    await expect(page.locator('.decision-link')).toHaveCount(0);
    await expect(page.locator('.meeting-detail-heading h2')).toHaveText(target.document.title);
    await expect(page.locator('.summary-copy')).toHaveText(target.meeting.analysis!.summary);
    expect((await page.request.get(`/api/meetings/${target.document.id}`)).status()).toBe(200);
  } finally { await owner.dispose(); }
});

for (const choice of ['server', 'local'] as const) {
test(`real Java: denied linked source cannot return from a retained recovery snapshot - ${choice}`, async ({ page, playwright, baseURL }, info) => {
  const owner = await playwright.request.newContext({ baseURL });
  try {
    const auth = await register(owner);
    const source = await create(owner, auth.workspaces[0].id, '회수할 복구 연결 원문');
    const reader = await register(page.request);
    expect((await owner.post(`/api/workspaces/${auth.workspaces[0].id}/members`, { data: { email: reader.user.email } })).status()).toBe(201);
    const target = await create(page.request, auth.workspaces[0].id, '복구 중인 현재 회의');
    for (const [doc, request] of [[source, owner], [target, page.request]] as const) {
      const analysis = structuredClone(doc.meeting.analysis!);
      analysis.items.find(item => item.type === 'decision')!.status = 'confirmed';
      const saved = await request.put(`/api/meetings/${doc.document.id}/analysis`, { data: { expected_revision: doc.document.revision, expected_version: doc.meeting.version, analysis } });
      expect(saved.status()).toBe(200); Object.assign(doc, await saved.json());
    }
    const quote = '단계별 배포로 진행하기로 결정했다.';
    const start_offset = Array.from(content.slice(0, content.indexOf(quote))).length;
    expect((await owner.post(`/api/meetings/${source.document.id}/links`, { data: {
      target_meeting_id: target.document.id, source_item_id: source.meeting.analysis!.items.find(item => item.type === 'decision')!.id,
      target_item_id: target.meeting.analysis!.items.find(item => item.type === 'decision')!.id,
      expected_revision: source.document.revision, expected_version: source.meeting.version,
      target_expected_revision: target.document.revision, target_expected_version: target.meeting.version,
      relation: 'related', quote, start_offset, end_offset: start_offset + Array.from(quote).length,
    } })).status()).toBe(201);
    await ready(page); await page.locator('#workspace-select').selectOption(auth.workspaces[0].id);
    await page.locator('[data-view=meetings]').click(); await page.locator(`[data-meeting="${target.document.id}"]`).click();
    const held = await delayResponse(page, (url, method) => url.pathname === `/api/documents/${source.document.id}` && method === 'GET', false, true);
    await page.locator('.decision-link .evidence-button').click(); await held.captured;
    await page.getByRole('button', { name: '분석 편집', exact: true }).click();
    await page.locator('.analysis-editor').getByRole('textbox', { name: '회의 요약', exact: true }).fill('유지할 복구 초안');
    const analysis = structuredClone(target.meeting.analysis!); analysis.summary = '동시 저장된 서버 요약';
    expect((await page.request.put(`/api/meetings/${target.document.id}/analysis`, { data: { expected_revision: target.document.revision, expected_version: target.meeting.version, analysis } })).status()).toBe(200);
    await page.getByRole('button', { name: '사용자 수정본 저장', exact: true }).click();
    await expect(page.locator('.edit-recovery')).toBeVisible();
    await page.getByRole('button', { name: '서버 버전 확인', exact: true }).click();
    await expect(page.locator('.server-analysis')).toContainText('동시 저장된 서버 요약');
    await hide(owner, source);
    const denied = page.waitForResponse(r => new URL(r.url()).pathname === `/api/documents/${source.document.id}`);
    await held.release(); expect((await denied).status()).toBe(404);
    await expect(page.locator('.analysis-editor').getByRole('textbox', { name: '회의 요약', exact: true })).toHaveValue('유지할 복구 초안');
    if (choice === 'server') await page.getByRole('button', { name: '내 초안 버리고 서버 버전 사용', exact: true }).click();
    else {
      await page.getByRole('button', { name: '내 초안 유지 · 저장은 나중에', exact: true }).click();
      await expect(page.locator('.analysis-editor').getByRole('textbox', { name: '회의 요약', exact: true })).toHaveValue('유지할 복구 초안');
      await page.locator('.analysis-editor').getByRole('button', { name: '취소', exact: true }).click();
    }
    await page.screenshot({ path: info.outputPath('recovery-after-source-denial.png'), fullPage: true });
    await expect(page.locator('.meeting-detail-heading h2')).toHaveText(target.document.title);
    await expect(page.locator('.decision-link')).toHaveCount(0);
  } finally { await owner.dispose(); }
});
}
