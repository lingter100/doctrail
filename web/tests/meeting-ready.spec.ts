import type { APIRequestContext, Page } from '@playwright/test';
import { test, expect, register, ready, delayResponse } from './support';
import type { MeetingDetail } from '../src/meetings';

// Real Java, SQLite, authentication, worker queue, validation, CAS and browser.
// The HTTP model boundary is an explicit deterministic transport fixture, NOT
// an LLM. These checks provide no evidence of generation or semantic quality.
const content = 'SYNTHETIC_MEETING_TRANSPORT_FIXTURE\n😀 합성 회의 2026-10-13\n단계별 배포로 진행하기로 결정했다.\n민수는 후속 점검을 맡는다.\n이전 결정을 변경한다.\n<img src=x onerror="window.meetingExecuted=true">';
async function create(request: APIRequestContext, workspace: string, title: string, raw = content) {
  const response = await request.post(`/api/workspaces/${workspace}/meetings/text`, { data: { title, content: raw, visibility: 'workspace' } });
  expect(response.status()).toBe(201);
  const initial = await response.json() as MeetingDetail;
  await expect.poll(async () => ((await (await request.get(`/api/meetings/${initial.document.id}`)).json()) as MeetingDetail).meeting.analysis_status).toBe('ready');
  return await (await request.get(`/api/meetings/${initial.document.id}`)).json() as MeetingDetail;
}
async function meetings(page: Page) { await page.locator('[data-view=meetings]').click(); await expect(page.locator('.loading')).toHaveCount(0); }

test('synthetic transport + real Java: meeting registration, evidence, user edits, tasks, links, answer and responsive layouts', async ({ page }, testInfo) => {
  const auth = await register(page.request);
  const previous = await create(page.request, auth.workspaces[0].id, '이전 합성 회의');
  const previousAnalysis = structuredClone(previous.meeting.analysis!);
  previousAnalysis.items.find(item => item.type === 'decision')!.status = 'confirmed';
  expect((await page.request.put(`/api/meetings/${previous.document.id}/analysis`, { data: { expected_revision: previous.document.revision, expected_version: previous.meeting.version, analysis: previousAnalysis } })).status()).toBe(200);
  await ready(page); await meetings(page);
  await page.getByRole('button', { name: '회의 등록', exact: true }).click();
  await page.getByRole('dialog').getByLabel('회의 제목').fill('현재 합성 회의');
  await page.getByRole('dialog').getByLabel('회의 원문').fill(content);
  await page.getByRole('button', { name: '등록하고 분석 요청' }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await expect(page.locator('.meeting-detail .analysis-status')).toHaveText('분석 완료');
  await expect(page.locator('.meeting-detail-heading h2')).toHaveText('현재 합성 회의');
  await expect(page.locator('.meeting-purpose')).toContainText('확인 필요');
  await expect(page.locator('.analysis-section.action')).toContainText('마감일 · 확인 필요');
  await page.locator('.analysis-section.decision .evidence-button').click();
  await expect(page.locator('#source-citation')).toHaveText('단계별 배포로 진행하기로 결정했다.');
  await expect(page.locator('#source-text')).toHaveText(content);
  await expect(page.locator('#edit-document')).toHaveCount(0);
  await expect(page.locator('#source-text img')).toHaveCount(0);
  await page.locator('#close-source').click();
  await page.getByRole('button', { name: '분석 편집', exact: true }).click();
  const editor = page.locator('.analysis-editor');
  await editor.getByRole('textbox', { name: '회의 요약', exact: true }).fill('사용자가 근거를 확인한 합성 수정 요약');
  await editor.locator('.item-editor').first().getByRole('combobox', { name: '상태', exact: true }).selectOption('confirmed');
  await editor.locator('.item-editor').last().getByRole('combobox', { name: '상태', exact: true }).selectOption('doing');
  await editor.getByLabel('담당자', { exact: true }).fill('민수');
  await editor.getByLabel('마감일', { exact: true }).fill('2026-10-20');
  await page.getByRole('button', { name: '사용자 수정본 저장' }).click();
  await expect(editor).toHaveCount(0);
  await expect(page.locator('.summary-copy')).toHaveText('사용자가 근거를 확인한 합성 수정 요약');
  await page.getByRole('tab', { name: 'AI 초안 · 읽기 전용' }).click();
  await expect(page.locator('.summary-copy')).toContainText('합성 회귀용 고정 초안');
  await expect(page.getByRole('button', { name: '분석 편집', exact: true })).toHaveCount(0);
  await page.getByRole('tab', { name: '사용자 수정본' }).click();
  await page.getByRole('button', { name: '결정 연결하기' }).click();
  const link = page.locator('.link-form');
  await link.getByLabel('현재 회의의 확정 결정').selectOption({ index: 1 });
  await expect(link.getByLabel('연결할 회의').locator('option')).toHaveCount(2);
  await link.getByLabel('연결할 회의').selectOption(previous.document.id);
  await link.getByLabel('연결할 확정 결정').selectOption({ index: 1 });
  await link.getByRole('combobox', { name: '관계', exact: true }).selectOption('supersedes');
  await link.getByLabel('연결 근거 · 현재 회의 원문에서 복사').fill('이전 결정을 변경한다.');
  await page.getByRole('button', { name: '확인한 결정 연결 저장' }).click();
  await expect(page.locator('.decision-link')).toContainText('이전 합성 회의');
  await expect(page.locator('.decision-link')).toContainText('이전 결정 변경');
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath('meeting-detail-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath('meeting-detail-mobile.png'), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.locator('[data-view=actions]').click();
  await expect(page.locator('.task-row').filter({ hasText: '현재 합성 회의' })).toContainText('민수');
  await expect(page.locator('.task-row').filter({ hasText: '현재 합성 회의' })).toContainText('진행 중');
  await page.locator('.task-row').filter({ hasText: '현재 합성 회의' }).click();
  await page.getByRole('button', { name: '분석 편집', exact: true }).click();
  await page.locator('.item-editor').last().getByRole('combobox', { name: '상태', exact: true }).selectOption('done');
  await page.getByRole('button', { name: '사용자 수정본 저장' }).click();
  await expect(page.locator('.analysis-section.action')).toContainText('완료');
  await expect(page.locator('.decision-link')).toHaveCount(1);
  await page.getByRole('button', { name: '분석 편집', exact: true }).click();
  await page.locator('.item-editor').first().getByRole('textbox', { name: '항목 내용', exact: true }).fill('사용자가 의미를 다시 확인해야 하는 수정 결정');
  const heldDecisionSave = await delayResponse(page, (url, method) => method === 'PUT' && /\/api\/meetings\/[^/]+\/analysis$/.test(url.pathname));
  await page.getByRole('button', { name: '사용자 수정본 저장' }).click();
  await heldDecisionSave.captured;
  // Editing hides decision history even while the real save response is pending.
  // Its absence cannot certify save completion or release the navigation guard.
  await expect(editor).toBeVisible();
  await expect(editor.getByRole('button', { name: '저장 중…', exact: true })).toBeDisabled();
  await expect(page.locator('.decision-history')).toHaveCount(0);
  await heldDecisionSave.release();
  await expect(editor).toHaveCount(0);
  await expect(page.locator('.analysis-section.decision')).toContainText('사용자가 의미를 다시 확인해야 하는 수정 결정');
  await expect(page.locator('.decision-history .no-links')).toHaveText('등록된 결정 연결이 없어요.');
  await expect(page.locator('.decision-link')).toHaveCount(0);
  await page.locator('[data-view=knowledge]').click();
  await page.getByRole('textbox', { name: '지식 질문' }).fill('단계별 배포');
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  await expect(page.getByTestId('knowledge-answer')).toContainText('합성 전송 검사용 고정 답변');
  await page.locator('.citation-chip').first().click();
  await expect(page.locator('#source-citation')).toHaveText('단계별 배포로 진행하기로 결정했다.');
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath('knowledge-answer-evidence-desktop.png'), fullPage: true });
  await page.locator('#close-source').click();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath('knowledge-answer-mobile.png'), fullPage: true });
});

test('synthetic transport + real Java: failed reanalysis visibly preserves the ready user-edited result', async ({ page }, info) => {
  const auth = await register(page.request);
  const meeting = await create(page.request, auth.workspaces[0].id, '재분석 실패 합성 회의', `${content}\nFIXTURE_FAIL_REANALYSIS`);
  const analysis = structuredClone(meeting.meeting.analysis!); analysis.summary = '재분석 실패에도 보존할 사용자 수정본';
  expect((await page.request.put(`/api/meetings/${meeting.document.id}/analysis`, { data: { expected_revision: meeting.document.revision, expected_version: meeting.meeting.version, analysis } })).status()).toBe(200);
  await ready(page); await meetings(page);
  await page.locator(`[data-meeting="${meeting.document.id}"]`).click();
  await page.getByRole('button', { name: 'AI 재분석 요청', exact: true }).click();
  await expect(page.locator('.meeting-detail .source-warning')).toContainText('최근 재분석을 완료하지 못했어요');
  await expect(page.locator('.meeting-detail .source-warning')).not.toContainText('generation_unavailable');
  await expect(page.locator('.meeting-detail .source-warning')).not.toContainText('상태 코드');
  await expect(page.locator('.summary-copy')).toHaveText('재분석 실패에도 보존할 사용자 수정본');
  await expect(page.getByRole('button', { name: '분석 편집', exact: true })).toBeEnabled();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await page.screenshot({ path: info.outputPath(`reanalysis-warning-${width}.png`), fullPage: true });
    const source = page.getByRole('button', { name: '전체 원문', exact: true });
    await source.focus(); await page.keyboard.press('Enter');
    await expect(page.locator('#close-source')).toBeFocused();
    await page.keyboard.press('Enter'); await expect(source).toBeFocused();
  }
});

test('synthetic transport + real Java: edited titles remain searchable and task metadata stays visible across layouts', async ({ page }, testInfo) => {
  const auth = await register(page.request, '합성 화면 회귀');
  const originalTitle = '기존 문서 제목으로도 찾는 합성 회의';
  const editedTitle = '사용자가 수정한 출시 점검 회의';
  const longAssignee = '모바일출시품질점검담당김민수와협업담당박지현';
  const longTask = '작은 화면에서도 작업 내용을 빠뜨리지 않고 출시 전 모바일 접근성 점검과 후속 확인 결과를 공유한다.';
  const meeting = await create(page.request, auth.workspaces[0].id, originalTitle, `${content}\n${editedTitle}\n${longAssignee}\n2026-10-20`);
  await create(page.request, auth.workspaces[0].id, '담당자와 기한이 없는 합성 회의');
  await ready(page); await meetings(page);
  await page.locator(`[data-meeting="${meeting.document.id}"]`).click();
  await page.getByRole('button', { name: '분석 편집', exact: true }).click();
  const editor = page.locator('.analysis-editor');
  await editor.getByLabel('분석 제목', { exact: true }).fill(editedTitle);
  await editor.locator('.metadata-proof summary').click();
  await editor.getByRole('button', { name: '제목 근거 선택', exact: true }).click();
  const picker = page.getByRole('dialog', { name: '원문 근거 선택', exact: true });
  await picker.getByLabel('정확한 구절 붙여넣기', { exact: true }).fill(editedTitle);
  await expect(picker.locator('.span-match')).toHaveCount(1);
  await expect(picker.locator('.span-match mark')).toHaveText(editedTitle);
  await expect(picker.getByRole('button', { name: '확인한 위치 사용', exact: true })).toBeDisabled();
  await picker.locator('.span-match').click();
  await expect(picker.locator('.span-match')).toHaveAttribute('aria-pressed', 'true');
  await picker.getByRole('button', { name: '확인한 위치 사용', exact: true }).click();
  await expect(picker).toHaveCount(0);
  await expect(editor.getByRole('textbox', { name: '제목 근거', exact: true })).toHaveValue(editedTitle);
  await editor.getByLabel('담당자', { exact: true }).fill(longAssignee);
  await editor.getByLabel('마감일', { exact: true }).fill('2026-10-20');
  await editor.locator('.item-editor').last().getByRole('textbox', { name: '항목 내용', exact: true }).fill(longTask);
  await editor.locator('.item-editor').last().getByRole('combobox', { name: '상태', exact: true }).selectOption('doing');
  await page.getByRole('button', { name: '사용자 수정본 저장' }).click();
  await expect(editor).toHaveCount(0);
  await expect(page.locator('.meeting-detail-heading h2')).toHaveText(editedTitle);
  const persisted = await (await page.request.get(`/api/meetings/${meeting.document.id}`)).json() as MeetingDetail;
  const titleStart = [...meeting.document.content.slice(0, meeting.document.content.indexOf(editedTitle))].length;
  expect(persisted.meeting.analysis!.metadata_evidence).toContainEqual({ field: 'meeting_title', quote: editedTitle, start_offset: titleStart, end_offset: titleStart + [...editedTitle].length });
  await page.getByRole('button', { name: '목록으로' }).click();
  const filter = page.getByRole('textbox', { name: '회의 제목 검색' });
  for (const query of [editedTitle, originalTitle]) {
    await filter.fill(query);
    await expect(page.locator('.meeting-card')).toHaveCount(1);
    await expect(page.locator('.meeting-card h2')).toHaveText(editedTitle);
  }
  await filter.fill('합성 회귀용 고정 초안');
  await expect(page.locator('.meeting-card')).toHaveCount(2);
  await filter.fill(editedTitle);
  await page.screenshot({ path: testInfo.outputPath('edited-title-search-desktop.png'), fullPage: true });
  await page.locator('[data-view=actions]').click();
  await expect(page.locator('.task-row')).toHaveCount(2);
  const task = page.locator('.task-row').filter({ hasText: originalTitle });
  const unknown = page.locator('.task-row').filter({ hasText: '담당자와 기한이 없는 합성 회의' });
  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await expect(task.locator('.task-assignee')).toBeVisible();
    await expect(task.locator('.task-assignee')).toContainText(longAssignee);
    await expect(task.locator('.task-due')).toBeVisible();
    await expect(task.locator('.task-due')).toContainText('2026-10-20');
    await expect(unknown.locator('.task-assignee')).toBeVisible();
    await expect(unknown.locator('.task-assignee')).toContainText('확인 필요');
    await expect(unknown.locator('.task-due')).toBeVisible();
    await expect(unknown.locator('.task-due')).toContainText('확인 필요');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(await page.locator('.task-copy, .task-metadata, .task-field').evaluateAll(elements =>
      elements.every(element => element.scrollWidth <= element.clientWidth + 1))).toBe(true);
    await page.getByRole('combobox', { name: '진행 상태', exact: true }).focus();
    await page.keyboard.press('Tab');
    await expect(page.locator('.task-row').first()).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('.meeting-detail')).toBeVisible();
    await page.getByRole('button', { name: '목록으로' }).click();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: testInfo.outputPath(`task-metadata-${width}.png`), fullPage: true });
  }
  await task.focus();
  await page.keyboard.press('Space');
  await expect(page.locator('.meeting-detail-heading h2')).toHaveText(editedTitle);
  await page.locator('.analysis-section.action .evidence-button').click();
  await expect(page.locator('#source-citation')).toHaveText('민수는 후속 점검을 맡는다.');
  await page.screenshot({ path: testInfo.outputPath('task-source-mobile.png') });
  await page.locator('#close-source').click();
  await expect(page.locator('.meeting-detail-heading h2')).toHaveText(editedTitle);
});

test('synthetic transport + real Java: edit conflicts preserve local draft and workspace change cancels delayed meeting', async ({ page }) => {
  const auth = await register(page.request);
  const doc = await create(page.request, auth.workspaces[0].id, '합성 경합 회의');
  const second = await (await page.request.post('/api/workspaces', { data: { name: '합성 다른 공간' } })).json();
  await ready(page); await meetings(page);
  await page.locator(`[data-meeting="${doc.document.id}"]`).click();
  await page.getByRole('button', { name: '분석 편집', exact: true }).click();
  await page.locator('.analysis-editor').getByLabel('회의 요약').fill('저장되지 않은 로컬 수정');
  const changed = structuredClone(doc.meeting.analysis!); changed.summary = '다른 창에서 저장한 요약';
  expect((await page.request.put(`/api/meetings/${doc.document.id}/analysis`, { data: { expected_revision: doc.document.revision, expected_version: doc.meeting.version, analysis: changed } })).status()).toBe(200);
  await page.getByRole('button', { name: '사용자 수정본 저장' }).click();
  await expect(page.getByRole('alert')).toContainText('변경되어 저장하지 않았어요');
  await expect(page.locator('.analysis-editor').getByLabel('회의 요약')).toHaveValue('저장되지 않은 로컬 수정');
  await page.locator('.analysis-editor').getByRole('button', { name: '취소', exact: true }).click();
  await page.getByRole('dialog', { name: '미저장 변경 확인' }).getByRole('button', { name: '버리고 이동' }).click();
  await page.getByRole('button', { name: '목록으로' }).click();
  const held = await delayResponse(page, (url, method) => url.pathname === `/api/meetings/${doc.document.id}` && method === 'GET');
  await page.locator(`[data-meeting="${doc.document.id}"]`).click(); await held.captured;
  await page.locator('#workspace-select').selectOption(second.id);
  await held.release();
  await expect(page.locator('[data-testid=meeting-detail]')).toHaveCount(0);
  await expect(page.locator('#workspace-select')).toHaveValue(second.id);
  await expect(page.locator('.main-content')).not.toContainText('합성 경합 회의');
});
