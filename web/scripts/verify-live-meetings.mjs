// Opt-in UI check against the actual local Java/model run. No transport mocks.
// The state file contains session cookies: keep it local and never commit it.
import { chromium } from '@playwright/test';
import { mkdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { parseArgs } from 'node:util';

const { values } = parseArgs({ options: {
  url: { type: 'string' }, state: { type: 'string' }, output: { type: 'string' },
} });
const address = new URL(values.url || 'invalid:');
if (address.protocol !== 'http:' || address.hostname !== '127.0.0.1' ||
    !address.port || address.username || address.password || address.search || address.hash ||
    address.pathname !== '/' || !values.state || !values.output) {
  throw new Error('Use a local service URL, local session state, and a new output directory.');
}
const output = resolve(values.output);
if (existsSync(output)) throw new Error('Preserve previous UI evidence; choose a new output directory.');
mkdirSync(output, { recursive: true });
const report = { kind: 'actual-local-meeting-ui', human_review_count: 0,
  transport_mock: false, checks: [], started_at: new Date().toISOString() };
function check(name, condition) {
  report.checks.push({ name, passed: !!condition });
  if (!condition) throw new Error(name);
}
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ storageState: JSON.parse(readFileSync(values.state, 'utf8')),
    viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', () => errors.push('pageerror'));
  await page.goto(address.href);
  await page.locator('[data-view=meetings]').click();
  await page.locator('.meeting-card').filter({ hasText: '2025-02-19' }).click();
  await page.locator('.meeting-detail .analysis-status').waitFor();
  check('real_analysis_ready', (await page.locator('.meeting-detail .analysis-status').innerText()) === '분석 완료');
  check('real_summary_present', (await page.locator('.summary-copy').innerText()).trim().length > 30);
  await page.screenshot({ path: join(output, 'meeting-desktop.png'), fullPage: true });
  await page.locator('.summary-section .evidence-button').first().click();
  const quote = await page.locator('#source-citation').innerText();
  check('real_summary_source', quote.length > 0 && (await page.locator('#source-text').innerText()).includes(quote));
  await page.screenshot({ path: join(output, 'meeting-evidence-desktop.png'), fullPage: true });
  await page.locator('#close-source').click();
  await page.locator('[data-view=knowledge]').click();
  await page.getByLabel('자료 종류', { exact: true }).selectOption('document');
  await page.getByLabel('지식 질문').fill('What does the host guide say about the agenda link?');
  const responsePromise = page.waitForResponse(r => r.url().endsWith('/api/knowledge/answer') && r.request().method() === 'POST', { timeout: 150000 });
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  const response = await responsePromise;
  check('real_answer_http', response.ok());
  const body = await response.json();
  check('five_context_request', response.request().postDataJSON().limit === 5);
  check('real_answer_generated', body.status === 'answered' && body.model_called === true && body.claims.length > 0);
  report.answer = body;
  await page.locator('.claim-citations button').first().click();
  check('real_answer_source', (await page.locator('#source-citation').innerText()).length > 0);
  await page.screenshot({ path: join(output, 'answer-evidence-desktop.png'), fullPage: true });
  await page.locator('#close-source').click();
  await page.setViewportSize({ width: 390, height: 844 });
  check('mobile_no_horizontal_overflow', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: join(output, 'answer-mobile.png'), fullPage: true });
  check('no_uncaught_ui_errors', errors.length === 0);
  report.status = 'passed';
} catch (error) {
  report.status = 'failed';
  // Preserve safe diagnostics without printing session state or HTTP request headers.
  report.failure = error instanceof Error ? error.message.split('\n')[0] : 'unknown';
  process.exitCode = 1;
} finally {
  report.completed_at = new Date().toISOString();
  writeFileSync(join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n');
  await browser.close();
}
console.log(JSON.stringify({ status: report.status, checks: report.checks.length }));
