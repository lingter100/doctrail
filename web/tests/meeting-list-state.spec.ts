import type { APIRequestContext, Page, Route } from '@playwright/test';
import { test, expect, register, ready, delayResponse, password } from './support';
import type { MeetingDetail } from '../src/meetings';

// Real Java, SQLite, authentication and browser. GET failures (including access
// failures) are explicitly injected below. Ready analyses come from the existing
// deterministic HTTP transport fixture, NOT an LLM or semantic-quality test.
const content = 'SYNTHETIC_MEETING_TRANSPORT_FIXTURE\n합성 목록 회의 2026-10-13\n단계별 배포로 진행하기로 결정했다.\n민수는 후속 점검을 맡는다.\nFIXTURE_FAIL_REANALYSIS';
async function create(request: APIRequestContext, workspace: string) {
  const response = await request.post(`/api/workspaces/${workspace}/meetings/text`, {
    data: { title: '보존할 합성 목록 회의', content, visibility: 'workspace' },
  });
  expect(response.status()).toBe(201);
  const initial = await response.json() as MeetingDetail;
  await expect.poll(async () => (await (await request.get(`/api/meetings/${initial.document.id}`)).json() as MeetingDetail).meeting.analysis_status).toBe('ready');
  return await (await request.get(`/api/meetings/${initial.document.id}`)).json() as MeetingDetail;
}
async function failGet(page: Page, matches: (url: URL) => boolean, status = 503) {
  const handler = (route: Route) => route.request().method() === 'GET' && matches(new URL(route.request().url()))
    ? route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ detail: `synthetic_list_failure_${status}` }) })
    : route.fallback();
  await page.route('**/api/**', handler);
  return () => page.unroute('**/api/**', handler);
}
const listError = (page: Page) => page.getByTestId('meeting-list-error');
const retry = (page: Page) => listError(page).getByRole('button', { name: '목록 다시 불러오기', exact: true });

test('real Java + synthetic GET failure: unknown meetings are not empty, explicit retry confirms true empty', async ({ page }, testInfo) => {
  const auth = await register(page.request);
  const path = `/api/workspaces/${auth.workspaces[0].id}/meetings`;
  let restore = await failGet(page, url => url.pathname === path);
  await ready(page); await page.locator('[data-view=meetings]').click();
  await expect(listError(page)).toContainText('회의 목록을 불러오지 못했어요');
  await expect(page.locator('.list-unavailable')).toContainText('유무와 개수를 알 수 없어요');
  await expect(page.locator('.meeting-toolbar, .meeting-empty')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '첫 회의 등록하기' })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('meetings-initial-failure-mobile.png'), fullPage: true });
  await restore();
  const pending = await delayResponse(page, (url, method) => method === 'GET' && url.pathname === path);
  await retry(page).click(); await pending.captured;
  await expect(page.locator('.meeting-toolbar, .meeting-empty')).toHaveCount(0);
  await expect(listError(page)).toContainText('회의 목록을 불러오지 못했어요');
  await pending.release();
  await expect(listError(page)).toHaveCount(0);
  await expect(page.locator('.meeting-toolbar .count')).toHaveText('0');
  await expect(page.getByRole('button', { name: '첫 회의 등록하기' })).toBeVisible();
  // A later failure cannot keep presenting that older zero as the current state.
  restore = await failGet(page, url => url.pathname === path);
  await page.getByRole('button', { name: '목록 새로고침', exact: true }).click();
  await expect(listError(page)).toContainText('이전 조회 결과를 보존');
  await expect(page.getByRole('button', { name: '첫 회의 등록하기' })).toHaveCount(0);
  await expect(page.locator('.meeting-toolbar')).toContainText('이전 조회한 회의');
  await expect(page.locator('.list-unavailable')).toContainText('현재 회의 목록은 확인되지 않았어요');
  await restore();
});

test('real Java + synthetic task GET failure: successful meetings do not certify an empty task list', async ({ page }) => {
  await register(page.request);
  const restore = await failGet(page, url => url.pathname === '/api/tasks');
  await ready(page); await page.locator('[data-view=actions]').click();
  await expect(listError(page)).toContainText('후속 작업을 불러오지 못했어요');
  await expect(listError(page)).toContainText('회의 조회 성공이 작업 목록의 최신 상태를 보장하지 않아요');
  await expect(page.locator('.meeting-toolbar, .empty-state, .task-row')).toHaveCount(0);
  await restore(); await retry(page).click();
  await expect(listError(page)).toHaveCount(0);
  await expect(page.locator('.meeting-toolbar')).toContainText('0개 작업');
  await expect(page.getByRole('heading', { name: '표시할 후속 작업이 없어요' })).toBeVisible();
});

for (const mode of ['meetings', 'actions'] as const) {
  test(`real Java + synthetic GET failure: ${mode} preserves previous rows and errors across detail/save${mode === 'meetings' ? '/poll' : ''}`, async ({ page }, testInfo) => {
    const auth = await register(page.request);
    const doc = await create(page.request, auth.workspaces[0].id);
    const endpoint = mode === 'meetings' ? `/api/workspaces/${auth.workspaces[0].id}/meetings` : '/api/tasks';
    await ready(page); await page.locator(`[data-view=${mode}]`).click();
    const rows = page.locator(mode === 'meetings' ? '.meeting-card' : '.task-row');
    await expect(rows).toHaveCount(1);
    // A successful filtered zero is still an ordinary empty result, not failure.
    const filter = mode === 'meetings' ? page.getByRole('textbox', { name: '회의 제목 검색' }) : page.getByRole('textbox', { name: '담당자', exact: true });
    await filter.fill('no-synthetic-match');
    await expect(rows).toHaveCount(0);
    await expect(page.locator('.empty-state')).toBeVisible();
    await expect(listError(page)).toHaveCount(0);
    await filter.fill(''); await expect(rows).toHaveCount(1);
    const restore = await failGet(page, url => url.pathname === endpoint);
    await page.getByRole('button', { name: '목록 새로고침', exact: true }).click();
    await expect(listError(page)).toContainText('최신');
    await expect(rows).toHaveCount(1);
    await expect(page.locator('.list-refresh')).toContainText('최신 상태 미확인');
    await expect(page.locator('.meeting-toolbar')).toContainText('이전 조회');
    if (mode === 'actions') await page.screenshot({ path: testInfo.outputPath('tasks-stale-list-desktop.png'), fullPage: true });
    await rows.first().click();
    await expect(page.getByTestId('meeting-detail')).toBeVisible();
    await expect(listError(page)).toBeVisible();
    await page.getByRole('button', { name: '분석 편집', exact: true }).click();
    await page.locator('.analysis-editor').getByRole('textbox', { name: '회의 요약', exact: true }).fill('목록 오류 중에도 명시적으로 저장한 합성 요약');
    await page.locator('.item-editor').last().getByRole('combobox', { name: '상태', exact: true }).selectOption('done');
    await page.getByRole('button', { name: '사용자 수정본 저장', exact: true }).click();
    await expect(page.locator('.summary-copy')).toHaveText('목록 오류 중에도 명시적으로 저장한 합성 요약');
    await expect(listError(page)).toBeVisible();
    if (mode === 'meetings') {
      // Existing fixture deliberately fails the second analyze call. Real Java
      // polling succeeds and retains the edited result, but cannot clear list failure.
      await page.getByRole('button', { name: 'AI 재분석 요청', exact: true }).click();
      await expect(page.locator('.meeting-detail .source-warning')).toContainText('최근 재분석을 완료하지 못했어요');
      await expect(listError(page)).toBeVisible();
    }
    await page.getByRole('button', { name: '목록으로' }).click();
    await expect(rows).toHaveCount(1);
    await expect(page.locator('.list-refresh')).toContainText('최신 상태 미확인');
    await restore(); await retry(page).click();
    await expect(listError(page)).toHaveCount(0);
    await expect(rows).toContainText(mode === 'meetings' ? '목록 오류 중에도 명시적으로 저장한 합성 요약' : '완료');
    expect((await (await page.request.get(`/api/meetings/${doc.document.id}`)).json() as MeetingDetail).meeting.analysis!.summary).toBe('목록 오류 중에도 명시적으로 저장한 합성 요약');
  });
}

test('real Java + independent injected GET failures: partial task success cannot clear meeting failure', async ({ page }) => {
  const auth = await register(page.request);
  await create(page.request, auth.workspaces[0].id);
  const restoreMeetings = await failGet(page, url => url.pathname === `/api/workspaces/${auth.workspaces[0].id}/meetings`);
  await ready(page); await page.locator('[data-view=actions]').click();
  await expect(page.locator('.task-row')).toHaveCount(1);
  await expect(listError(page)).toContainText('후속 작업 조회는 완료됐어요. 회의 분석 상태는 확인하지 못했어요');
  const restoreTasks = await failGet(page, url => url.pathname === '/api/tasks');
  await retry(page).click();
  await expect(listError(page)).toContainText('후속 작업을 불러오지 못했어요');
  await expect(page.locator('.task-row')).toHaveCount(1);
  await expect(page.locator('.meeting-toolbar')).toContainText('이전 조회');
  await restoreTasks(); await retry(page).click();
  await expect(listError(page)).toContainText('후속 작업 조회는 완료됐어요');
  await expect(listError(page)).not.toContainText('후속 작업을 불러오지 못했어요');
  await expect(listError(page)).toContainText('회의 목록을 불러오지 못했어요');
  await restoreMeetings(); await retry(page).click();
  await expect(listError(page)).toHaveCount(0);
});

test('real Java + synthetic 403/404: permission failures invalidate cached tasks until freshly authorized', async ({ page }) => {
  const auth = await register(page.request);
  await create(page.request, auth.workspaces[0].id);
  await ready(page); await page.locator('[data-view=actions]').click();
  await expect(page.locator('.task-row')).toHaveCount(1);
  let restoreTasks = await failGet(page, url => url.pathname === '/api/tasks', 403);
  await page.getByRole('button', { name: '목록 새로고침', exact: true }).click();
  await expect(listError(page)).toContainText('권한이 없어요');
  await expect(page.locator('.task-row, .meeting-toolbar, .empty-state')).toHaveCount(0);
  await restoreTasks(); await retry(page).click();
  await expect(page.locator('.task-row')).toHaveCount(1);
  const restoreMeetings = await failGet(page, url => url.pathname === `/api/workspaces/${auth.workspaces[0].id}/meetings`, 404);
  restoreTasks = await failGet(page, url => url.pathname === '/api/tasks');
  await page.getByRole('button', { name: '목록 새로고침', exact: true }).click();
  await expect(listError(page)).toContainText('후속 작업을 불러오지 못했어요');
  await expect(page.locator('.task-row, .meeting-toolbar, .empty-state')).toHaveCount(0);
  // The old task cache was cleared by workspace access failure. A fresh 200
  // from the independent tasks endpoint is required before showing rows again.
  await restoreTasks(); await retry(page).click();
  await expect(page.locator('.task-row')).toHaveCount(1);
  await expect(listError(page)).toContainText('후속 작업 조회는 완료됐어요');
  await restoreMeetings();
});

test('real Java delayed tasks: workspace switch cannot display an old successful list', async ({ page }) => {
  const auth = await register(page.request);
  const first = auth.workspaces[0].id;
  const secondResponse = await page.request.post('/api/workspaces', { data: { name: '합성 빈 작업공간' } });
  expect(secondResponse.status()).toBe(201);
  const second = (await secondResponse.json()).id as string;
  await create(page.request, first);
  await ready(page); await page.locator('#workspace-select').selectOption(first);
  const pending = await delayResponse(page, (url, method) => method === 'GET' && url.pathname === '/api/tasks' && url.searchParams.get('workspace_id') === first);
  await page.locator('[data-view=actions]').click(); await pending.captured;
  await page.locator('#workspace-select').selectOption(second);
  // Workspace switching intentionally returns to the document library.
  await page.locator('[data-view=actions]').click();
  await expect(page.getByRole('heading', { name: '표시할 후속 작업이 없어요' })).toBeVisible();
  await pending.release();
  await expect(page.locator('.task-row')).toHaveCount(0);
  await expect(page.locator('.meeting-toolbar')).toContainText('0개 작업');
  await expect(listError(page)).toHaveCount(0);
  await expect(page.locator('#workspace-select')).toHaveValue(second);
});

test('real Java + delayed synthetic 401: an old list failure cannot expire a new login', async ({ page }) => {
  const auth = await register(page.request);
  await ready(page);
  const expired = await delayResponse(page, (url, method) => method === 'GET' && url.pathname === `/api/workspaces/${auth.workspaces[0].id}/meetings`, true);
  await page.locator('[data-view=meetings]').click(); await expired.captured;
  await page.getByRole('button', { name: '로그아웃' }).click();
  await expect(page.locator('#auth-form')).toBeVisible();
  await page.getByLabel('이메일', { exact: true }).fill(auth.user.email);
  await page.getByLabel('비밀번호', { exact: true }).fill(password);
  await page.locator('#auth-form').getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.locator('#workspace-select')).toBeVisible();
  await page.locator('[data-view=meetings]').click();
  await expect(page.getByRole('button', { name: '첫 회의 등록하기' })).toBeVisible();
  await expired.release();
  await expect(listError(page)).toHaveCount(0);
  await expect(page.locator('#auth-form')).toHaveCount(0);
  expect((await page.request.get('/api/auth/me')).status()).toBe(200);
});

test('real Java delayed create + synthetic 403: access loss cannot restore an older mutation result or leave controls busy', async ({ page }) => {
  const auth = await register(page.request);
  const path = `/api/workspaces/${auth.workspaces[0].id}/meetings`;
  await ready(page); await page.locator('[data-view=meetings]').click();
  await expect(page.getByRole('button', { name: '첫 회의 등록하기' })).toBeVisible();
  let captured!: () => void, release!: () => void;
  const capturedPromise = new Promise<void>(resolve => { captured = resolve; });
  const releasePromise = new Promise<void>(resolve => { release = resolve; });
  let used = false;
  const denied = async (route: Route) => {
    if (used || route.request().method() !== 'GET') return route.fallback();
    used = true;
    await route.fetch(); // Buffer a real read; only its failure status is synthetic.
    captured(); await releasePromise;
    await route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ detail: 'synthetic_access_revoked' }) });
  };
  await page.route(`**${path}`, denied);
  await page.getByRole('button', { name: '목록 새로고침', exact: true }).click();
  await capturedPromise;
  const created = await delayResponse(page, (url, method) => method === 'POST' && url.pathname === `${path}/text`);
  await page.getByRole('button', { name: '회의 등록', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('회의 제목').fill('늦게 도착한 합성 생성 결과');
  await dialog.getByLabel('회의 원문').fill(content);
  await dialog.getByRole('button', { name: '등록하고 분석 요청', exact: true }).click();
  await created.captured;
  const rejected = page.waitForResponse(response => new URL(response.url()).pathname === path && response.status() === 403);
  release(); await rejected;
  await expect(listError(page)).toContainText('권한이 없어요');
  await created.release();
  await expect(page.getByTestId('meeting-detail')).toHaveCount(0);
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('button', { name: '취소', exact: true })).toBeEnabled();
  await expect(dialog.getByRole('button', { name: '등록하고 분석 요청', exact: true })).toBeEnabled();
  await expect(dialog.getByRole('alert')).toContainText('서버에 반영됐을 수 있으니');
  await dialog.getByRole('button', { name: '취소', exact: true }).click();
  await page.unroute(`**${path}`, denied);
  await retry(page).click();
  // Invalidation only cancels client ownership, not the already committed Java
  // transaction. An explicit fresh read must reveal the real stored record.
  await expect(page.locator('.meeting-card')).toContainText('늦게 도착한 합성 생성 결과');
  await expect(listError(page)).toHaveCount(0);
  await page.getByRole('button', { name: '회의 등록', exact: true }).click();
  await dialog.getByLabel('회의 제목').fill('접근 재확인 뒤 명시적인 새 요청');
  await dialog.getByLabel('회의 원문').fill(content);
  await dialog.getByRole('button', { name: '등록하고 분석 요청', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.locator('.meeting-detail-heading h2')).toHaveText('접근 재확인 뒤 명시적인 새 요청');
});
