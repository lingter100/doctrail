// Optional real GPU integration, separate from model-free CI. All records are synthetic.
import { chromium, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const baseURL = process.env.DOCTRAIL_E2E_URL;
const output = process.env.DOCTRAIL_E2E_OUTPUT;
if (!baseURL || !output || new URL(baseURL).hostname !== '127.0.0.1') throw new Error('isolated_loopback_target_required');
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const context = await browser.newContext({ baseURL, viewport: { width: 1440, height: 1000 }, locale: 'ko-KR' });
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));
const checks = [];
try {
  await page.goto('/');
  await page.getByRole('tab', { name: '새로 시작하기' }).click();
  await page.getByLabel('이름', { exact: true }).fill('합성 시연 사용자');
  await page.getByLabel('이메일', { exact: true }).fill(`model-ui-${randomUUID()}@example.invalid`);
  await page.getByLabel('비밀번호', { exact: true }).fill(randomUUID());
  await page.getByLabel('워크스페이스 이름', { exact: true }).fill('합성 운영 문서');
  await page.getByRole('button', { name: '워크스페이스 만들기' }).click();
  await expect(page.locator('.search-caption')).toContainText('모델 검색 연결됨', { timeout: 15000 });
  await page.locator('#upload').click();
  const content = '# 합성 배포 가이드\n\n배포 전에 서비스 상태를 확인합니다. Canary deployment starts with a small traffic percentage. 오류가 증가하면 이전 버전으로 롤백합니다.\n\n합성 예시이며 실제 운영 정책이 아닙니다.';
  await page.getByLabel('업로드할 문서 파일').setInputFiles({ name: 'synthetic-deployment.md', mimeType: 'text/markdown', buffer: Buffer.from(content) });
  await page.getByRole('dialog').locator('input[name=title]').fill('배포 및 복구 가이드 · 합성');
  await page.getByRole('button', { name: '업로드', exact: true }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  checks.push('real_ui_registration_and_upload');

  for (const method of ['dense', 'hybrid', 'hybrid_rerank']) {
    await page.locator('#search-method').selectOption(method);
    await page.locator('#search-input').fill('Canary deployment 배포');
    const pending = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/search'), { timeout: 130000 });
    await page.locator('#search-form').getByRole('button', { name: '검색', exact: true }).click();
    const response = await pending;
    expect(response.status()).toBe(200);
    const payload = await response.json();
    expect(payload.method).toBe(method);
    expect(payload.results).toHaveLength(1);
    await expect(page.locator('.result-card')).toHaveCount(1);
    await page.locator('[data-hit="0"]').click();
    await expect(page.locator('#source-text')).toHaveText(content);
    await expect(page.locator('#source-citation')).toHaveText(payload.results[0].text);
    await page.getByRole('button', { name: '원문 닫기' }).click();
    checks.push(`real_${method}_search_and_evidence`);
  }
  await page.getByRole('button', { name: '1번 결과 관련 있음', exact: true }).click();
  await expect(page.locator('.feedback').first()).toContainText('피드백이 저장됐어요');
  await page.locator('[data-view="history"]').click();
  await expect(page.locator('.history-row').first()).toContainText('통합 검색 + 재정렬');
  const rerun = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/search'), { timeout: 130000 });
  await page.locator('.history-row').first().click();
  expect((await (await rerun).json()).method).toBe('hybrid_rerank');
  await expect(page.locator('.result-card')).toHaveCount(1);
  await page.locator('[data-hit="0"]').click();
  await expect(page.locator('#source-citation')).toBeVisible();
  await page.screenshot({ path: resolve(output, 'model-desktop.png'), fullPage: true });
  checks.push('feedback_and_original_method_history_rerun');
  await page.getByRole('button', { name: '원문 닫기' }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator('#search-method')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: resolve(output, 'model-mobile.png'), fullPage: true });
  checks.push('mobile_controls_without_horizontal_overflow');
  expect(errors).toEqual([]);
  await writeFile(resolve(output, 'browser.json'), JSON.stringify({ schema_version: 1, status: 'passed', synthetic: true, actual_model_http: true, user_review: false, completed_at: new Date().toISOString(), checks, uncaught_errors: errors }, null, 2) + '\n');
  console.log(JSON.stringify({ status: 'passed', checks: checks.length }));
} finally { await context.close(); await browser.close(); }
