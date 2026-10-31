async function pickQuote(page: Page, section: ReturnType<Page['locator']>, number: number, quote: string, ordinal = 0) {
  await section.getByRole('button', { name: '근거 ' + number + ' 원문 위치 선택', exact: true }).click();
  const picker = page.getByRole('dialog', { name: '원문 근거 선택' });
  await picker.getByLabel('정확한 구절 붙여넣기').fill(quote);
  await expect(picker.getByRole('button', { name: '확인한 위치 사용' })).toBeDisabled();
  await picker.locator('.span-match').nth(ordinal).click();
  await picker.getByRole('button', { name: '확인한 위치 사용' }).click();
}
import type { APIRequestContext, Page } from '@playwright/test';
import { test, expect, register, ready } from './support';
import type { GroundedAnalysis, MeetingDetail, Span, SummaryClaim } from '../src/meetings';

// Real isolated Java/SQLite/CAS/source reads and packaged React. The explicit
// FIXTURE_GROUNDED_SUMMARY_V2 model HTTP response is synthetic, not model quality.
// Named error/schema-change tests below deliberately fabricate browser responses.
const repeated = '반복 확인 문장이다.';
const content = `SYNTHETIC_MEETING_TRANSPORT_FIXTURE\nFIXTURE_GROUNDED_SUMMARY_V2\n😀 합성 요약 회의 2026-10-13\n단계별 배포로 진행하기로 결정했다.\n민수는 후속 점검을 맡는다.\n${repeated}\n이전 결정을 변경한다.\n${repeated}`;
const analysisOf = (doc: MeetingDetail): GroundedAnalysis => {
  const analysis = doc.meeting.analysis;
  if (!analysis || analysis.summary_version !== 2) throw new Error('Synthetic grounded transport fixture did not produce v2');
  return analysis;
};
function occurrence(quote: string, ordinal = 0): Span {
  let offset = -1;
  for (let i = 0; i <= ordinal; i++) offset = content.indexOf(quote, offset + 1);
  if (offset < 0) throw new Error('Missing synthetic quote');
  const start_offset = Array.from(content.slice(0, offset)).length;
  return { quote, start_offset, end_offset: start_offset + Array.from(quote).length };
}
// Build expected projections independently from the production helper.
function withClaims(analysis: GroundedAnalysis, claims: SummaryClaim[]): GroundedAnalysis {
  const sorted = claims.map((claim, id) => ({ ...claim, id,
    citations: [...claim.citations].sort((a, b) => a.start_offset - b.start_offset || a.end_offset - b.end_offset) }));
  const all = sorted.flatMap(claim => claim.citations);
  const evidence = all.filter((span, i) => all.findIndex(other => other.start_offset === span.start_offset && other.end_offset === span.end_offset) === i)
    .sort((a, b) => a.start_offset - b.start_offset || a.end_offset - b.end_offset);
  return { ...analysis, summary_version: 2, summary_claims: sorted, summary: sorted.map(claim => claim.text).join('\n'), summary_evidence: evidence };
}
async function create(request: APIRequestContext, workspace: string) {
  const response = await request.post(`/api/workspaces/${workspace}/meetings/text`, { data: { title: '합성 근거 연결 요약', content, visibility: 'workspace' } });
  expect(response.status()).toBe(201);
  const initial = await response.json() as MeetingDetail;
  const read = async () => await (await request.get(`/api/meetings/${initial.document.id}`)).json() as MeetingDetail;
  await expect.poll(async () => (await read()).meeting.analysis_status).toBe('ready');
  const doc = await read(); analysisOf(doc);
  return { doc, read };
}
async function open(page: Page, doc: MeetingDetail) {
  await ready(page); await page.locator('[data-view=meetings]').click();
  await page.locator(`[data-meeting="${doc.document.id}"]`).click();
  await expect(page.getByTestId('meeting-detail')).toBeVisible();
}
async function setup(page: Page) {
  const auth = await register(page.request);
  const result = await create(page.request, auth.workspaces[0].id);
  await open(page, result.doc);
  return result;
}
async function put(request: APIRequestContext, doc: MeetingDetail, analysis: GroundedAnalysis) {
  const response = await request.put(`/api/meetings/${doc.document.id}/analysis`, { data: { expected_revision: doc.document.revision, expected_version: doc.meeting.version, analysis } });
  expect(response.status()).toBe(200);
  return await response.json() as MeetingDetail;
}

for (const width of [1440, 390]) {
  test(`synthetic v2 + real Java: every claim citation opens its exact source at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    const { doc } = await setup(page);
    const claims = analysisOf(doc).summary_claims;
    await expect(page.getByRole('heading', { name: 'AI 요약 초안', exact: true })).toBeVisible();
    await expect(page.locator('.analysis-disclosure')).toContainText('정확성이나 완전성을 보증하지는 않아요');
    await expect(page.locator('.summary-section [data-summary-claim]')).toHaveCount(claims.length);
    for (const [index, claim] of claims.entries()) {
      const section = page.locator(`.summary-section [data-summary-claim="${index}"]`);
      await expect(section.locator('.summary-copy')).toHaveText(claim.text);
      await expect(section.locator('.evidence-button')).toHaveCount(claim.citations.length);
      for (const [citation, span] of claim.citations.entries()) {
        const button = section.locator('.evidence-button').nth(citation);
        await button.focus(); await page.keyboard.press('Enter');
        await expect(page.locator('#source-citation')).toHaveText(span.quote);
        const before = await page.locator('#source-text').evaluate(element => {
          const range = document.createRange(); range.selectNodeContents(element);
          range.setEndBefore(element.querySelector('mark')!); return range.toString();
        });
        expect(Array.from(before).length).toBe(span.start_offset);
        await page.locator('#close-source').click(); await expect(button).toBeFocused();
      }
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`grounded-summary-${width}.png`), fullPage: true });
  });
}

test('v2 edits preserve repeat occurrence, all citations and canonical projections after reorder and reload', async ({ page }, info) => {
  const { doc, read } = await setup(page);
  const original = structuredClone(analysisOf(doc));
  await page.getByRole('button', { name: '분석 편집', exact: true }).click();
  const editor = page.locator('.analysis-editor');
  await expect(editor.getByRole('textbox', { name: '회의 요약', exact: true })).toHaveCount(0);
  const first = editor.locator('[data-summary-editor="0"]');
  const editedText = 'Edited summary: source references remain visible.'; // Human edits have no model-language gate.
  await first.getByRole('textbox', { name: '문장 1 내용', exact: true }).fill(editedText);
  await pickQuote(page, first, 1, repeated, 1);
  await first.getByRole('button', { name: '근거 추가', exact: true }).click();
  const emoji = occurrence('😀 합성 요약 회의');
  await pickQuote(page, first, 3, emoji.quote);
  await first.getByRole('button', { name: '문장 1 아래로', exact: true }).click();
  await expect(editor.getByRole('textbox', { name: '문장 2 내용', exact: true })).toHaveValue(editedText);
  await editor.getByRole('button', { name: '요약 문장 추가' }).click();
  await expect(editor.locator('[data-summary-editor]')).toHaveCount(3);
  await editor.getByRole('button', { name: '문장 3 삭제', exact: true }).click();
  const expected = withClaims(original, [original.summary_claims[1], { id: 1, text: editedText,
    citations: [occurrence(repeated, 1), original.summary_claims[0].citations[1], emoji] }]);
  const saved = page.waitForRequest(r => r.method() === 'PUT' && new URL(r.url()).pathname === `/api/meetings/${doc.document.id}/analysis`);
  await editor.getByRole('button', { name: '사용자 수정본 저장' }).click();
  const payload = (await saved).postDataJSON();
  expect(payload.analysis).toEqual(expected);
  await expect(editor).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '수정한 요약', exact: true })).toBeVisible();
  expect(analysisOf(await read())).toEqual(expected);
  await page.reload(); await expect(page.locator('#workspace-select')).toBeVisible(); await page.locator('[data-view=meetings]').click();
  await expect(page.locator(`[data-meeting="${doc.document.id}"]`)).toBeVisible();
  await page.locator(`[data-meeting="${doc.document.id}"]`).click();
  await expect(page.locator('.summary-section [data-summary-claim="1"] .summary-copy')).toHaveText(editedText);
  await page.getByRole('tab', { name: 'AI 초안 · 읽기 전용', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'AI 요약 초안', exact: true })).toBeVisible();
  for (const [index, claim] of original.summary_claims.entries()) {
    await expect(page.locator(`.summary-section [data-summary-claim="${index}"] .summary-copy`)).toHaveText(claim.text);
    await expect(page.locator(`.summary-section [data-summary-claim="${index}"] .evidence-button`)).toHaveCount(claim.citations.length);
  }
  await page.screenshot({ path: info.outputPath('grounded-ai-original.png'), fullPage: true });
  await page.getByRole('button', { name: '이 AI 초안을 사용자 수정본으로 적용' }).click();
  await expect(page.getByRole('tab', { name: '사용자 수정본', exact: true })).toHaveAttribute('aria-selected', 'true');
  expect(analysisOf(await read())).toEqual(original);
});

test('v2 invalid edits never send PUT: unknown/repeated position, blank text, codepoint and count caps', async ({ page }) => {
  const { doc } = await setup(page);
  let puts = 0;
  page.on('request', r => { if (r.method() === 'PUT' && r.url().endsWith(`/meetings/${doc.document.id}/analysis`)) puts++; });
  await page.getByRole('button', { name: '분석 편집', exact: true }).click();
  const editor = page.locator('.analysis-editor'), first = editor.locator('[data-summary-editor="0"]');
  const save = editor.getByRole('button', { name: '사용자 수정본 저장' });
  const text = first.getByRole('textbox', { name: '문장 1 내용', exact: true });
  await text.fill(' '); await expect(save).toBeDisabled();
  await text.fill('가'.repeat(241)); await expect(save).toBeDisabled();
  await text.fill('두 문단\n허용하지 않음'); await expect(save).toBeDisabled();
  await text.fill('😀'.repeat(239) + '가'); await expect(save).toBeEnabled();
  await text.fill('편집 중인 문장');
  await first.getByRole('button', { name: '근거 1 원문 위치 선택' }).click();
  const picker = page.getByRole('dialog', { name: '원문 근거 선택' });
  await picker.getByLabel('정확한 구절 붙여넣기').fill('원문에 없는 인용');
  await expect(picker.getByRole('button', { name: '확인한 위치 사용' })).toBeDisabled();
  await picker.getByRole('button', { name: '취소', exact: true }).click();
  const duplicate = analysisOf(doc).summary_claims[0].citations[1];
  await pickQuote(page, first, 1, duplicate.quote);
  await expect(save).toBeDisabled(); await expect(editor).toContainText('같은 위치의 근거가 중복');
  await first.getByRole('button', { name: '근거 1 삭제', exact: true }).click();
  await expect(save).toBeEnabled();
  for (let i = 0; i < 3; i++) await first.getByRole('button', { name: '근거 추가', exact: true }).click();
  await expect(first.getByRole('button', { name: '근거 추가', exact: true })).toBeDisabled();
  for (let i = 0; i < 4; i++) await editor.getByRole('button', { name: '요약 문장 추가' }).click();
  await expect(editor.getByRole('button', { name: '요약 문장 추가' })).toBeDisabled();
  await expect(editor.locator('[data-summary-editor]')).toHaveCount(6);
  await expect(save).toBeDisabled();
  expect(puts).toBe(0);
});

test('real v2 conflict preserves local claims and shows server claim-to-citation links before explicit retry', async ({ page }, info) => {
  const { doc, read } = await setup(page);
  await page.getByRole('button', { name: '분석 편집', exact: true }).click();
  const editor = page.locator('.analysis-editor');
  await editor.getByRole('textbox', { name: '문장 1 내용', exact: true }).fill('저장 전 로컬 요약');
  const original = analysisOf(doc);
  const serverAnalysis = withClaims(original, original.summary_claims.map((claim, index) => ({ ...claim, text: index ? claim.text : '다른 창에서 저장한 요약' })));
  const server = await put(page.request, doc, serverAnalysis);
  await editor.getByRole('button', { name: '사용자 수정본 저장' }).click();
  await expect(editor.getByRole('button', { name: '사용자 수정본 저장' })).toBeDisabled();
  await page.getByRole('button', { name: '서버 버전 확인', exact: true }).click();
  const comparison = page.locator('.server-analysis');
  await expect(comparison).toContainText('다른 창에서 저장한 요약');
  await expect(comparison.locator('[data-summary-claim="0"] .evidence-button')).toHaveCount(original.summary_claims[0].citations.length);
  await comparison.locator('[data-summary-claim="0"] .evidence-button').last().click();
  await expect(page.locator('#source-citation')).toHaveText(original.summary_claims[0].citations.at(-1)!.quote);
  await page.locator('#close-source').click();
  await expect(editor.getByRole('textbox', { name: '문장 1 내용', exact: true })).toHaveValue('저장 전 로컬 요약');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('grounded-conflict-mobile.png'), fullPage: true });
  await page.getByRole('button', { name: '내 초안 유지 · 저장은 나중에' }).click();
  const outgoing = page.waitForRequest(r => r.method() === 'PUT' && r.url().endsWith(`/meetings/${doc.document.id}/analysis`));
  await editor.getByRole('button', { name: '사용자 수정본 저장' }).click();
  const body = (await outgoing).postDataJSON();
  expect(body.expected_version).toBe(server.meeting.version);
  expect(body.analysis.summary_version).toBe(2);
  expect(body.analysis.summary_claims[0].citations).toEqual(original.summary_claims[0].citations);
  await expect(editor).toHaveCount(0);
  expect(analysisOf(await read()).summary_claims[0].text).toBe('저장 전 로컬 요약');
});

for (const code of ['generation_summary_insufficient', 'generation_summary_review_rejected']) {
  test(`synthetic ${code} responses explain refusal and retain stored v2`, async ({ page }) => {
    const auth = await register(page.request);
    const { doc, read } = await create(page.request, auth.workspaces[0].id);
    await page.route(`**/api/meetings/${doc.document.id}`, route => route.fulfill({ json: { ...doc, meeting: { ...doc.meeting, analysis_error: code } } }));
    await page.route(`**/api/meetings/${doc.document.id}/analyze`, route => route.fulfill({ status: 503, json: { detail: code } }));
    await open(page, doc);
    await expect(page.locator('.source-warning')).toContainText('기존 분석과 사용자 수정본은 보존');
    await expect(page.locator('.source-warning')).not.toContainText(code);
    await page.getByRole('button', { name: 'AI 재분석 요청', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText(code.endsWith('insufficient') ? '핵심을 충분히 담은 요약' : '새 요약을 반영하지 않았어요');
    await expect(page.getByRole('alert')).not.toContainText(code);
    expect(analysisOf(await read())).toEqual(analysisOf(doc));
  });
}

test('synthetic server contract switch during conflict cannot silently downgrade the v2 draft', async ({ page }) => {
  const { doc } = await setup(page);
  await page.getByRole('button', { name: '분석 편집', exact: true }).click();
  await page.locator('.analysis-editor').getByRole('textbox', { name: '문장 1 내용', exact: true }).fill('보존할 v2 초안');
  const { summary_version: _version, summary_claims: _claims, ...legacy } = analysisOf(doc);
  await page.route(`**/api/meetings/${doc.document.id}/analysis`, route => route.fulfill({ status: 409, json: { detail: 'analysis_conflict' } }));
  await page.route(`**/api/meetings/${doc.document.id}`, route => route.fulfill({ json: { ...doc, meeting: { ...doc.meeting, version: doc.meeting.version + 1, analysis: legacy } } }));
  await page.getByRole('button', { name: '사용자 수정본 저장', exact: true }).click();
  await page.getByRole('button', { name: '서버 버전 확인', exact: true }).click();
  await expect(page.getByRole('button', { name: '내 초안 유지 · 저장은 나중에' })).toBeDisabled();
  await expect(page.getByRole('button', { name: '사용자 수정본 저장', exact: true })).toBeDisabled();
  await expect(page.locator('.analysis-editor').getByRole('textbox', { name: '문장 1 내용', exact: true })).toHaveValue('보존할 v2 초안');
});

for (const malformed of ['unknown_version', 'missing_claims', 'null_claim']) {
  test(`synthetic ${malformed} is not displayed as an editable legacy summary`, async ({ page }) => {
    const auth = await register(page.request);
    const { doc } = await create(page.request, auth.workspaces[0].id);
    const analysis: Record<string, unknown> = { ...analysisOf(doc) };
    if (malformed === 'unknown_version') analysis.summary_version = 3;
    else if (malformed === 'missing_claims') delete analysis.summary_claims;
    else analysis.summary_claims = [null];
    await page.route(`**/api/meetings/${doc.document.id}`, route => route.fulfill({ json: { ...doc, meeting: { ...doc.meeting, analysis } } }));
    await open(page, doc);
    await expect(page.locator('.summary-section')).toContainText('요약 형식을 확인할 수 없어요');
    await expect(page.getByRole('button', { name: '분석 편집', exact: true })).toHaveCount(0);
    await expect(page.locator('.summary-section .summary-copy')).toHaveCount(0);
  });
}

test('v2 citation after real source revision change shows latest text without a false highlight', async ({ page }) => {
  const { doc } = await setup(page);
  const changed = await page.request.put(`/api/documents/${doc.document.id}`, { data: { title: doc.document.title,
    content: '😀 새 원문에는 이전 인용이 없다.', visibility: 'workspace' } });
  expect(changed.ok()).toBe(true);
  await page.locator('.summary-section .evidence-button').first().click();
  await expect(page.locator('#source-text')).toHaveText('😀 새 원문에는 이전 인용이 없다.');
  await expect(page.locator('.source-pane .source-warning')).toContainText('원문이 변경되었어요');
  await expect(page.locator('#source-citation')).toHaveCount(0);
});

test('v2 citation after real source deletion retires cached detail', async ({ page }) => {
  const { doc } = await setup(page);
  const removed = await page.request.delete(`/api/documents/${doc.document.id}`);
  expect(removed.ok()).toBe(true);
  await page.locator('.summary-section .evidence-button').first().click();
  await expect(page.getByTestId('meeting-detail')).toHaveCount(0);
  await expect(page.locator('.source-pane')).toHaveCount(0);
  await expect(page.locator('.main-content')).not.toContainText(analysisOf(doc).summary_claims[0].text);
});
