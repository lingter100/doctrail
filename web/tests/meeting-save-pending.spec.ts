import type { Page } from '@playwright/test';
import { test, expect, register, ready, delayResponse } from './support';
import type { MeetingDetail } from '../src/meetings';

// Real Java authentication, SQLite, CAS and packaged React. Analysis creation
// uses deterministic synthetic HTTP transport: actual LLM 0, human review 0.
const content = 'SYNTHETIC_MEETING_TRANSPORT_FIXTURE\n합성 저장 대기 회의 2026-10-13\n단계별 배포로 진행하기로 결정했다.\n민수는 후속 점검을 맡는다.';
const savedSummary = '저장을 누르기 전에 작성한 요약';
const lateSummary = '저장 응답을 기다리는 동안 추가한 요약';
async function setup(page: Page) {
  const auth = await register(page.request);
  const response = await page.request.post(`/api/workspaces/${auth.workspaces[0].id}/meetings/text`, {
    data: { title: '합성 저장 대기 회의', content, visibility: 'workspace' },
  });
  expect(response.status()).toBe(201);
  const initial = await response.json() as MeetingDetail;
  const path = `/api/meetings/${initial.document.id}`;
  const read = async () => await (await page.request.get(path)).json() as MeetingDetail;
  await expect.poll(async () => (await read()).meeting.analysis_status).toBe('ready');
  const doc = await read();
  await ready(page);
  await page.locator('[data-view=meetings]').click();
  await page.locator(`[data-meeting="${doc.document.id}"]`).click();
  await page.getByRole('button', { name: '분석 편집', exact: true }).click();
  const editor = page.locator('.analysis-editor');
  await editor.getByRole('textbox', { name: '회의 요약', exact: true }).fill(savedSummary);
  await editor.locator('.metadata-proof summary').click();
  const action = editor.locator('.item-editor').filter({ has: page.getByRole('textbox', { name: '담당자', exact: true }) });
  await action.getByRole('textbox', { name: '담당자', exact: true }).fill('저장 전 담당자');
  await action.getByRole('combobox', { name: '상태', exact: true }).selectOption('doing');
  return { doc, path, read, editor, action };
}

test('real Java: pending successful save locks every analysis field and retains the submitted snapshot', async ({ page }, testInfo) => {
  const { doc, path, read, editor, action } = await setup(page);
  let puts = 0;
  page.on('request', request => { if (request.method() === 'PUT' && new URL(request.url()).pathname === `${path}/analysis`) puts++; });
  const held = await delayResponse(page, (url, method) => url.pathname === `${path}/analysis` && method === 'PUT');
  await page.getByRole('button', { name: '사용자 수정본 저장', exact: true }).click();
  await held.captured;
  const committed = await read();
  expect(committed.meeting.version).toBe(doc.meeting.version + 1);
  const controls = editor.locator('input, textarea, select');
  const enabled = await controls.evaluateAll(elements => elements.filter(element => !element.matches(':disabled')).map(element => ({ tag: element.tagName, label: element.closest('label')?.textContent })));
  // Preserve a concrete pre-fix data-loss witness if the controls remain open.
  // The same regression still fails on any enabled field; this branch never
  // treats accepted-but-discarded edits as correct behavior.
  let pendingDraft = null;
  if (await editor.getByRole('textbox', { name: '회의 요약', exact: true }).isEnabled()) {
    await editor.getByRole('textbox', { name: '회의 요약', exact: true }).fill(lateSummary);
    await action.getByRole('textbox', { name: '담당자', exact: true }).fill('응답 대기 중 담당자');
    await action.getByRole('combobox', { name: '상태', exact: true }).selectOption('done');
    pendingDraft = { summary: await editor.getByRole('textbox', { name: '회의 요약', exact: true }).inputValue(), assignee: await action.getByRole('textbox', { name: '담당자', exact: true }).inputValue(), status: await action.getByRole('combobox', { name: '상태', exact: true }).inputValue() };
  }
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('pending-save-mobile.png'), fullPage: true });
  const pendingNotice = await editor.getByRole('status').allTextContents();
  await held.release();
  await expect(editor).toHaveCount(0);
  await expect(page.locator('.summary-copy')).toHaveText(savedSummary);
  const after = await read();
  const storedAction = after.meeting.analysis!.items.find(item => item.type === 'action')!;
  await testInfo.attach('pending-save-evidence', { contentType: 'application/json', body: JSON.stringify({ enabled, pendingDraft, pendingNotice, after: { summary: after.meeting.analysis!.summary, assignee: storedAction.assignee, status: storedAction.status }, editorClosed: true, puts, realJava: true, llmCalls: 0, humanReview: false }, null, 2) });
  expect(enabled, 'No analysis field may accept edits after the save snapshot is submitted').toEqual([]);
  expect(pendingNotice).toContain('저장 중에는 내용을 수정할 수 없어요. 저장이 끝난 뒤 다시 편집해 주세요.');
  expect(storedAction.assignee).toBe('저장 전 담당자');
  expect(storedAction.status).toBe('doing');
  expect(puts).toBe(1);
  await page.getByRole('button', { name: '분석 편집', exact: true }).click();
  for (const control of await controls.all()) await expect(control).toBeEnabled();
  await editor.getByRole('textbox', { name: '회의 요약', exact: true }).fill('저장 완료 후 다시 편집할 수 있는 요약');
});

test('real Java + synthetic PUT 503: failed save unlocks the preserved draft without automatic retry', async ({ page }) => {
  const { doc, path, read, editor, action } = await setup(page);
  let puts = 0;
  let signalCaptured!: () => void, release!: () => void;
  const captured = new Promise<void>(resolve => { signalCaptured = resolve; });
  const released = new Promise<void>(resolve => { release = resolve; });
  await page.route(`**${path}/analysis`, async route => {
    if (route.request().method() !== 'PUT') return route.fallback();
    puts++; signalCaptured(); await released;
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'synthetic_save_unavailable' }) });
  });
  await page.getByRole('button', { name: '사용자 수정본 저장', exact: true }).click();
  await captured;
  const locked = await editor.locator('input, textarea, select').evaluateAll(elements => elements.every(element => element.matches(':disabled')));
  release();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(editor.getByRole('textbox', { name: '회의 요약', exact: true })).toHaveValue(savedSummary);
  await expect(action.getByRole('textbox', { name: '담당자', exact: true })).toHaveValue('저장 전 담당자');
  await expect(action.getByRole('combobox', { name: '상태', exact: true })).toHaveValue('doing');
  for (const control of await editor.locator('input, textarea, select').all()) await expect(control).toBeEnabled();
  await expect(editor.getByRole('status').filter({ hasText: '저장 중에는 내용을 수정할 수 없어요.' })).toHaveCount(0);
  await expect(editor.getByRole('status').filter({ hasText: '미저장 변경 있음' })).toBeVisible();
  await editor.getByRole('textbox', { name: '회의 요약', exact: true }).fill('실패 후 보존한 초안을 계속 편집');
  expect((await read()).meeting.version).toBe(doc.meeting.version);
  expect(puts).toBe(1);
  expect(locked).toBe(true);
});
