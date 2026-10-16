import { test, expect, register, upload, ready, delayResponse } from './support';

test('synthetic language rejection recovers through real Java search with the same question and filters', async ({ page }) => {
  const auth = await register(page.request);
  await upload(page.request, auth.workspaces[0].id, '복구할 원문', 'recoverymarker original evidence');
  let answerRequests = 0;
  let answerBody: Record<string, unknown> = {};
  await page.route('**/api/knowledge/answer', async route => {
    answerRequests++;
    answerBody = route.request().postDataJSON();
    // Deliberate error injection only. Registration, search and source reading are real Java requests.
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'generation_language_mismatch' }) });
  });
  await ready(page);
  await page.locator('[data-view=knowledge]').click();
  await page.getByRole('textbox', { name: '지식 질문' }).fill('recoverymarker');
  await page.getByLabel('검색 범위').selectOption('all');
  await page.getByLabel('자료 종류').selectOption('document');
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('요청한 언어와 달라');
  await expect(page.getByTestId('knowledge-answer')).toHaveCount(0);
  const search = page.waitForRequest(request => new URL(request.url()).pathname === '/api/knowledge/search');
  await page.getByRole('button', { name: '원문 검색으로 확인', exact: true }).click();
  expect((await search).postDataJSON()).toEqual({ ...answerBody, limit: 10 });
  await expect(page.getByRole('tab', { name: '원문 검색', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('textbox', { name: '지식 질문' })).toHaveValue('recoverymarker');
  await expect(page.getByLabel('검색 범위')).toHaveValue('all');
  await expect(page.getByLabel('자료 종류')).toHaveValue('document');
  await expect(page.getByLabel('검색 방식')).toHaveValue('bm25');
  await expect(page.locator('.knowledge-hit')).toHaveCount(1);
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByTestId('knowledge-answer')).toHaveCount(0);
  await page.locator('.knowledge-hit-open').click();
  await expect(page.locator('#source-text')).toContainText('recoverymarker original evidence');
  expect(answerRequests).toBe(1);
});

test('real Java disabled answer and a delayed recovery search cannot replace changed filters', async ({ page }) => {
  const auth = await register(page.request);
  await upload(page.request, auth.workspaces[0].id, '이전 조건 문서', 'recoveryracemarker existing evidence');
  await ready(page);
  await page.locator('[data-view=knowledge]').click();
  await page.getByRole('textbox', { name: '지식 질문' }).fill('recoveryracemarker');
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('AI 모델이 연결되지 않았어요');
  const held = await delayResponse(page, (url, method) => url.pathname === '/api/knowledge/search' && method === 'POST');
  await page.getByRole('button', { name: '원문 검색으로 확인', exact: true }).click();
  await held.captured;
  await page.getByLabel('자료 종류').selectOption('meeting');
  await held.release();
  await expect(page.locator('.knowledge-hit')).toHaveCount(0);
  await expect(page.locator('.knowledge-empty')).toBeVisible();
  await expect(page.getByRole('textbox', { name: '지식 질문' })).toHaveValue('recoveryracemarker');
  await expect(page.getByLabel('자료 종류')).toHaveValue('meeting');
  await expect(page.getByTestId('knowledge-answer')).toHaveCount(0);
});
