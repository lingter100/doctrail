import { test, expect, register, upload, ready, delayResponse } from './support';

test('synthetic abstention reasons retain the question and never expose raw worker codes', async ({ page }, info) => {
  await register(page.request);
  let reason = 'no_evidence', calls = 0;
  const bodies: unknown[] = [];
  await page.route('**/api/knowledge/answer', async route => {
    calls++; bodies.push(route.request().postDataJSON());
    await route.fulfill({ json: { status: 'abstained', reason, claims: [], results: [], method: 'bm25', model_called: true } });
  });
  await ready(page); await page.locator('[data-view=knowledge]').click();
  await page.getByLabel('지식 질문').fill('synthetic recovery question');
  for (const [code, message] of [
    ['no_evidence', '현재 검색 조건에 맞는 원문 근거가 없어요'],
    ['insufficient_evidence', '찾은 원문만으로는 질문에 답할 근거가 충분하지 않아요'],
    ['conflicting_evidence', '찾은 원문의 내용이 서로 달라'],
    ['unsupported_question', '현재 답변 기능으로 처리하기 어려운 질문이에요'],
    ['private_unknown_reason', '답변을 보류했어요. 검색된 원문을 확인'],
  ]) {
    reason = code; const before = calls;
    await page.getByRole('button', { name: '질문하기', exact: true }).click();
    await expect(page.getByTestId('knowledge-answer')).toContainText(message);
    await expect(page.getByTestId('knowledge-answer')).not.toContainText(code);
    await expect(page.getByRole('alert')).toHaveCount(0);
    await expect(page.getByLabel('지식 질문')).toHaveValue('synthetic recovery question');
    expect(calls).toBe(before + 1);
    await page.getByRole('button', { name: '질문하기', exact: true }).click();
    await expect.poll(() => calls).toBe(before + 2);
    await expect(page.getByTestId('knowledge-answer')).toContainText(message);
    expect(bodies.at(-1)).toEqual(bodies.at(-2));
    if (code === 'conflicting_evidence') await page.screenshot({ path: info.outputPath('conflicting-evidence.png'), fullPage: true });
  }
});

test('synthetic HTTP failures distinguish recovery causes without changing method or retrying automatically', async ({ page }, info) => {
  await register(page.request);
  let code = 'generation_timeout', status = 504, calls = 0;
  const bodies: Record<string, unknown>[] = [];
  await page.route('**/api/knowledge/answer', async route => {
    calls++; bodies.push(route.request().postDataJSON());
    await route.fulfill({ status, json: { detail: code } });
  });
  await ready(page); await page.locator('[data-view=knowledge]').click();
  await page.getByLabel('지식 질문').fill('synthetic recovery question');
  await page.getByLabel('자료 종류').selectOption('document');
  const cases: [string, number, string][] = [
    ['generation_timeout', 504, '답변 생성 시간이 초과됐어요'],
    ['generation_busy', 503, '다른 AI 요청을 처리하고 있어요'],
    ['generation_unavailable', 503, '답변 생성에 일시적인 문제가 생겼어요'],
    ['generation_failed', 503, '답변 생성에 일시적인 문제가 생겼어요'],
    ...['invalid_response', 'invalid_json', 'invalid_schema', 'invalid_evidence', 'duplicate_item', 'unsupported_field', 'unsupported_metadata', 'conflicting_metadata', 'output_truncated'].map(suffix => ['generation_' + suffix, 503, 'AI 응답의 형식이나 근거를 검증하지 못했어요'] as [string, number, string]),
    ['generation_language_mismatch', 503, '요청한 언어와 달라'],
    ['generation_disabled', 503, '현재 답변 생성 기능을 사용할 수 없어요'],
    ['generation_cleanup_failed', 503, '현재 답변 생성 기능을 사용할 수 없어요'],
    ['context_budget_exceeded', 422, '찾은 근거가 한 번에 답변할 수 있는 분량을 넘었어요'],
    ['generation_input_limit', 422, '검색 조건을 좁히거나'],
    ['generation_partition_limit', 422, '검색 조건을 좁히거나'],
    ['generation_invalid_request', 422, '검색 또는 답변 요청을 완료하지 못했어요'],
    ['search_context_changed', 409, '검색 중 원문이나 접근 권한이 변경됐어요'],
    ['embedding_profile_changed', 409, '검색 모델 설정이 변경됐어요'],
    ['private_unknown_code', 409, '검색 또는 답변 요청을 완료하지 못했어요'],
    ['private_unknown_code', 500, '검색 또는 답변 요청을 완료하지 못했어요'],
    ['inference_unknown_code', 503, '검색 또는 답변 요청을 완료하지 못했어요'],
    ['not_found', 403, '자료를 확인할 수 없어요'],
    ['not_found', 404, '자료를 확인할 수 없어요'],
  ];
  for (const [nextCode, nextStatus, message] of cases) {
    code = nextCode; status = nextStatus; const before = calls;
    await page.getByRole('button', { name: '질문하기', exact: true }).click();
    const alert = page.getByRole('alert');
    await expect(alert).toContainText(message);
    await expect(alert).not.toContainText(code);
    await expect(alert).not.toContainText('저장하지 않았어요');
    await expect(page.getByTestId('knowledge-answer')).toHaveCount(0);
    expect(calls).toBe(before + 1);
    await alert.getByRole('button', { name: '다시 시도', exact: true }).click();
    await expect.poll(() => calls).toBe(before + 2);
    await expect(alert).toContainText(message);
    expect(bodies.at(-1)).toEqual(bodies.at(-2));
    expect(bodies.at(-1)).toMatchObject({ method: 'bm25', kind: 'document', limit: 5 });
    await expect(page.getByLabel('검색 방식')).toHaveValue('bm25');
    if (code === 'generation_timeout') await page.screenshot({ path: info.outputPath('generation-timeout.png'), fullPage: true });
  }
});

test('real Java empty evidence abstains before disabled generation without a model call', async ({ page }) => {
  await register(page.request);
  await ready(page); await page.locator('[data-view=knowledge]').click();
  await page.getByLabel('지식 질문').fill('synthetic absent evidence');
  const pending = page.waitForResponse(r => new URL(r.url()).pathname === '/api/knowledge/answer');
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  const response = await pending;
  expect(response.status()).toBe(200);
  expect(await response.json()).toMatchObject({ status: 'abstained', reason: 'no_evidence', model_called: false, results: [] });
  await expect(page.getByTestId('knowledge-answer')).toContainText('현재 검색 조건에 맞는 원문 근거가 없어요');
  await expect(page.getByRole('alert')).toHaveCount(0);
});

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
  await expect(page.getByRole('alert')).toContainText('현재 답변 생성 기능을 사용할 수 없어요');
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


test('real Java session expiry keeps existing login recovery and clears knowledge output', async ({ page }) => {
  await register(page.request);
  await ready(page); await page.locator('[data-view=knowledge]').click();
  await page.getByLabel('지식 질문').fill('synthetic absent evidence');
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  await expect(page.getByTestId('knowledge-answer')).toBeVisible();
  expect((await page.request.post('/api/auth/logout')).status()).toBe(204);
  const pending = page.waitForResponse(r => new URL(r.url()).pathname === '/api/knowledge/answer');
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  expect((await pending).status()).toBe(401);
  await expect(page.locator('#workspace-select')).toHaveCount(0);
  await expect(page.getByTestId('knowledge-answer')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '로그인', exact: true })).toBeVisible();
});
