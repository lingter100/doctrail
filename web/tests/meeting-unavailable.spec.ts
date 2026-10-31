import { test, expect, register, ready, upload, delayResponse, syntheticPdf } from './support';
import type { MeetingDetail } from '../src/meetings';

test('real Java without generation: text and PDF registration preserve source, show failure and searchable raw records', async ({ page }, testInfo) => {
  await register(page.request); await ready(page);
  await page.locator('[data-view=meetings]').click();
  await page.getByRole('button', { name: '회의 등록', exact: true }).click();
  await page.getByRole('dialog').getByLabel('회의 제목').fill('분석 미연결 합성 회의');
  await page.getByRole('dialog').getByLabel('회의 원문').fill('meetingrawmarker 😀 원문은 모델 없이도 저장됩니다.');
  await page.getByRole('button', { name: '등록하고 분석 요청' }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await expect(page.locator('.meeting-detail .analysis-status')).toHaveText('분석 실패');
  await expect(page.locator('.meeting-detail .source-warning')).toContainText('AI 모델이 연결되지 않았어요');
  await expect(page.getByRole('heading', { name: '아직 완료된 분석 결과가 없어요' })).toBeVisible();
  await expect(page.locator('.analysis-disclosure, .meeting-metadata, .summary-section, .analysis-sections')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'AI 분석 다시 시도', exact: true })).toBeEnabled();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`failed-analysis-${width}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('button', { name: '전체 원문', exact: true }).click();
  await expect(page.locator('#source-text')).toContainText('meetingrawmarker');
  await expect(page.locator('#edit-document')).toHaveCount(0);
  await page.locator('#close-source').click();
  await page.getByRole('button', { name: '← 목록으로', exact: true }).click();
  const failedCard = page.locator('.meeting-card').filter({ hasText: '분석 미연결 합성 회의' });
  await expect(failedCard).toContainText('분석 결과 없음');
  await expect(failedCard.locator('.meeting-card-foot')).not.toContainText('AI 초안');
  await page.getByRole('button', { name: '회의 등록', exact: true }).click();
  await page.getByRole('tab', { name: '파일 업로드' }).click();
  await page.getByLabel('회의록 파일', { exact: true }).setInputFiles({ name: 'synthetic-meeting.pdf', mimeType: 'application/pdf', buffer: syntheticPdf() });
  await page.getByRole('dialog').getByLabel('회의 제목').fill('합성 PDF 회의');
  await page.getByRole('button', { name: '등록하고 분석 요청' }).click();
  await expect(page.locator('.meeting-detail-heading h2')).toHaveText('합성 PDF 회의');
  await page.locator('[data-view=knowledge]').click();
  await page.getByRole('tab', { name: '원문 검색', exact: true }).click();
  await page.getByRole('textbox', { name: '지식 질문' }).fill('meetingrawmarker');
  await page.getByRole('button', { name: '검색', exact: true }).click();
  await expect(page.locator('.knowledge-hit')).toHaveCount(1);
  await expect(page.locator('.knowledge-hit')).toContainText('분석 미연결 합성 회의');
  await page.getByRole('tab', { name: '근거 기반 답변' }).click();
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('현재 답변 생성 기능을 사용할 수 없어요');
  await page.getByRole('textbox', { name: '지식 질문' }).fill('syntheticnomatch999');
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  await expect(page.getByTestId('knowledge-answer')).toContainText('답변을 보류했어요');
  await expect(page.getByTestId('knowledge-answer')).toContainText('모델 호출 없이');
});

// Synthetic detail responses exercise display states only; no model-quality claim.
for (const state of ['queued', 'running', 'ready', 'stale'] as const) {
  test(`synthetic analysis state: ${state} distinguishes pending placeholders from saved empty or stale drafts`, async ({ page }) => {
    const auth = await register(page.request);
    const response = await page.request.post(`/api/workspaces/${auth.workspaces[0].id}/meetings/text`, { data: { title: '합성 분석 상태', content: '원문 보존 확인용 합성 회의', visibility: 'workspace' } });
    expect(response.status()).toBe(201);
    const detail = await response.json() as MeetingDetail;
    const completed = state === 'ready' || state === 'stale';
    detail.meeting.analysis_status = state;
    detail.meeting.analysis_error = null;
    detail.meeting.version = completed ? 1 : 0;
    detail.meeting.analysis!.items = [];
    detail.meeting.analysis!.summary = state === 'stale' ? '이전 원문에서 보존한 요약' : '';
    detail.meeting.ai_analysis = completed ? structuredClone(detail.meeting.analysis) : null;
    if (state === 'stale') detail.document.revision = detail.meeting.source_revision + 1;
    await page.route(`**/api/meetings/${detail.document.id}`, route => route.fulfill({ json: detail }));
    await ready(page);
    await page.locator('[data-view=meetings]').click();
    await page.locator(`[data-meeting="${detail.document.id}"]`).click();
    await expect(page.getByRole('button', { name: '전체 원문', exact: true })).toBeEnabled();
    if (!completed) {
      await expect(page.locator('.analysis-banner')).toBeVisible();
      await expect(page.getByRole('heading', { name: '아직 완료된 분석 결과가 없어요' })).toBeVisible();
      await expect(page.locator('.analysis-disclosure, .meeting-metadata, .summary-section, .analysis-sections')).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'AI 분석 다시 시도', exact: true })).toHaveCount(0);
    } else {
      await expect(page.locator('.analysis-disclosure')).toBeVisible();
      await expect(page.locator('.analysis-section.topic')).toContainText('추출된 논의 주제가 없어요.');
      await expect(page.locator('.analysis-sections .count')).toHaveText(['0', '0', '0', '0', '0']);
      await expect(page.getByRole('heading', { name: '아직 완료된 분석 결과가 없어요' })).toHaveCount(0);
      if (state === 'stale') {
        await expect(page.locator('.summary-copy')).toHaveText('이전 원문에서 보존한 요약');
        await expect(page.locator('.source-warning')).toContainText('이전 원문의 결과예요');
      }
    }
  });
}

test('real Java: knowledge all-workspace scope, meeting-only filters and delayed answer ownership', async ({ page }) => {
  const auth = await register(page.request);
  await upload(page.request, auth.workspaces[0].id, '현재 공간 문서', 'scopeuniquemarker current workspace');
  const workspace = await (await page.request.post('/api/workspaces', { data: { name: '합성 추가 공간' } })).json();
  await upload(page.request, workspace.id, '추가 공간 문서', 'scopeuniquemarker extra workspace');
  await ready(page); await page.locator('#workspace-select').selectOption(auth.workspaces[0].id);
  await page.locator('[data-view=knowledge]').click();
  await page.getByRole('tab', { name: '원문 검색', exact: true }).click();
  await page.getByRole('textbox', { name: '지식 질문' }).fill('scopeuniquemarker');
  await page.getByRole('button', { name: '검색', exact: true }).click();
  await expect(page.locator('.knowledge-hit')).toHaveCount(1);
  await page.getByLabel('검색 범위').selectOption('all');
  await page.getByRole('button', { name: '검색', exact: true }).click();
  await expect(page.locator('.knowledge-hit')).toHaveCount(2);
  await page.getByText('회의 조건으로 좁히기', { exact: true }).click();
  await page.getByLabel('회의 시작일').fill('2026-10-01');
  await page.getByRole('button', { name: '검색', exact: true }).click();
  await expect(page.locator('.knowledge-hit')).toHaveCount(0);
  await page.getByRole('button', { name: '회의 조건 초기화' }).click();
  const held = await delayResponse(page, (url, method) => url.pathname === '/api/knowledge/search' && method === 'POST');
  await page.getByRole('button', { name: '검색', exact: true }).click(); await held.captured;
  await page.getByLabel('자료 종류').selectOption('meeting');
  await held.release();
  await expect(page.locator('.knowledge-hit')).toHaveCount(0);
  await expect(page.locator('.knowledge-empty')).toBeVisible();
});
