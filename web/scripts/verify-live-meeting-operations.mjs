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
const report = { kind: 'actual-local-meeting-lifecycle-ui', natural_answer_readiness: false, human_review_count: 0,
  transport_mock: false, checks: [], started_at: new Date().toISOString() };
function check(name, condition) {
  report.checks.push({ name, passed: !!condition });
  if (!condition) throw new Error(name);
}
const browser = await chromium.launch({ headless: true });
const deadline = setTimeout(() => void browser.close(), 120000);
try {
  const context = await browser.newContext({ storageState: JSON.parse(readFileSync(values.state, 'utf8')),
    viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', () => errors.push('pageerror'));
  await page.goto(address.href);
  await page.locator('[data-view=meetings]').click();
  const meeting = page.locator('.meeting-card').filter({ hasText: '2025-02-19' });
  const meetingId = await meeting.getAttribute('data-meeting');
  const detailResponse = page.waitForResponse(r => r.url().endsWith(`/api/meetings/${meetingId}`));
  await meeting.click();
  const detail = await (await detailResponse).json();
  check('expected_meeting_opened', detail.document.id === meetingId);
  await page.locator('.meeting-detail .analysis-status').waitFor();
  check('real_analysis_ready', (await page.locator('.meeting-detail .analysis-status').innerText()) === '분석 완료');
  check('real_summary_present', (await page.locator('.summary-copy').innerText()).trim().length > 30);
  await page.screenshot({ path: join(output, 'meeting-desktop.png'), fullPage: true });
  const evidence = page.locator('.summary-section .evidence-button').first();
  const expectedQuote = await evidence.locator('.evidence-preview').textContent();
  await evidence.click();
  const quote = await page.locator('#source-citation').textContent();
  check('real_summary_source', !!quote && quote === expectedQuote && detail.document.content.includes(quote)
    && (await page.locator('#source-text').textContent()) === detail.document.content
    && (await page.locator('.source-heading h2').innerText()) === detail.document.title);
  await page.screenshot({ path: join(output, 'meeting-evidence-desktop.png'), fullPage: true });
  await page.locator('#close-source').click();
  await page.locator('[data-view=actions]').click();
  await page.getByLabel('담당자', { exact: true }).fill('서연');
  const task = page.locator('.task-row').filter({ hasText: '서연' });
  await task.waitFor();
  check('real_saved_task_owner_date_status', (await task.innerText()).includes('2026-10-15') && (await task.innerText()).includes('진행 중'));
  await page.screenshot({ path: join(output, 'task-desktop.png'), fullPage: true });
  await task.click();
  check('task_opens_original_meeting', (await page.locator('.meeting-detail').innerText()).includes('2026-10-01'));
  await page.locator('.summary-section .evidence-button').first().click();
  check('task_meeting_source', (await page.locator('#source-citation').innerText()).length > 0);
  await page.locator('#close-source').click();
  await page.setViewportSize({ width: 390, height: 844 });
  check('mobile_no_horizontal_overflow', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: join(output, 'meeting-mobile.png'), fullPage: true });
  check('no_uncaught_ui_errors', errors.length === 0);
  report.status = 'passed';
} catch (error) {
  report.status = 'failed';
  // Preserve safe diagnostics without printing session state or HTTP request headers.
  report.failure = error instanceof Error ? error.message.split('\n')[0] : 'unknown';
  process.exitCode = 1;
} finally {
  clearTimeout(deadline);
  report.completed_at = new Date().toISOString();
  writeFileSync(join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n');
  await browser.close();
}
console.log(JSON.stringify({ status: report.status, checks: report.checks.length }));
