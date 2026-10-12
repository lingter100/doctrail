import { test as base, expect, type APIRequestContext, type Page, type Route } from '@playwright/test';
import { randomUUID } from 'node:crypto';

// All data is synthetic. Requests use the real, isolated Java test service unless
// a test explicitly identifies a synthetic failure response.
export const test = base.extend<{ pageErrors: string[] }>({
  pageErrors: [async ({ page }, use) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await use(errors);
    expect(errors, 'No uncaught browser errors').toEqual([]);
  }, { auto: true }],
});
export { expect };
export const password = 'Synthetic-browser-password-123';
export type Auth = { user: { id: string; email: string }; workspaces: { id: string; name: string }[] };
export type Detail = { id: string; title: string; content: string; revision: number; status: string; chunks: { id: string; text: string; start_offset: number; end_offset: number }[] };

export async function register(request: APIRequestContext, label = 'Synthetic workspace'): Promise<Auth> {
  const response = await request.post('/api/auth/register', { data: {
    email: `browser-${randomUUID()}@example.test`, password, name: 'Synthetic browser user', workspace_name: label,
  } });
  expect(response.status()).toBe(201);
  return response.json();
}
export async function upload(request: APIRequestContext, workspace: string, title: string, content: string, visibility = 'workspace'): Promise<Detail> {
  const response = await request.post(`/api/workspaces/${workspace}/documents`, { multipart: {
    title, visibility, file: { name: `${title}.md`, mimeType: 'text/markdown', buffer: Buffer.from(content) },
  } });
  expect(response.status()).toBe(201);
  const detail = await response.json();
  expect(detail.status).toBe('ready');
  return detail;
}
export async function ready(page: Page) {
  await page.goto('/');
  await expect(page.locator('#workspace-select')).toBeVisible();
  await expect(page.locator('.loading')).toHaveCount(0);
}
export async function search(page: Page, query: string) {
  await page.getByRole('textbox', { name: '문서 검색어' }).fill(query);
  await page.locator('#search-form').getByRole('button', { name: '검색', exact: true }).click();
}
export async function completedSearch(page: Page, query: string) {
  const response = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/search') && new URL(r.url()).searchParams.get('q') === query);
  await search(page, query);
  expect((await response).status()).toBe(200);
  await expect(page.locator('.loading')).toHaveCount(0);
}
export async function uiUpload(page: Page, name: string, content: Buffer, mimeType: string, title: string) {
  await page.locator('#upload').click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('업로드할 문서 파일').setInputFiles({ name, mimeType, buffer: content });
  await dialog.locator('input[name=title]').fill(title);
  const response = page.waitForResponse(r => r.request().method() === 'POST' && /\/workspaces\/[^/]+\/documents$/.test(new URL(r.url()).pathname));
  await dialog.getByRole('button', { name: '업로드', exact: true }).click();
  const result = await response;
  expect(result.status()).toBe(201);
  const detail = await result.json() as Detail;
  expect(detail.status).toBe('ready');
  await expect(dialog).not.toBeVisible();
  await expect(page.locator('.source-heading h2')).toHaveText(title);
  return detail;
}

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>(done => { resolve = done; });
  return { promise, resolve };
}

// Buffer a REAL Java response, then release it only at an explicit test checkpoint.
// No fixed sleeps or fabricated successful payloads are used for race checks.
export async function delayResponse(page: Page, matches: (url: URL, method: string) => boolean, synthetic401 = false, beforeFetch = false) {
  const captured = deferred();
  const release = deferred();
  const finished = deferred();
  const delivered = deferred();
  let used = false;
  let failure: unknown;
  const handler = async (route: Route) => {
    if (used || !matches(new URL(route.request().url()), route.request().method())) return route.fallback();
    used = true;
    const browserRequest = route.request();
    const onDone = (request: import('@playwright/test').Request) => {
      if (request !== browserRequest) return;
      page.off('requestfinished', onDone);
      page.off('requestfailed', onDone);
      delivered.resolve();
    };
    page.on('requestfinished', onDone);
    page.on('requestfailed', onDone);
    try {
      if (beforeFetch) { captured.resolve(); await release.promise; }
      const response = await route.fetch();
      captured.resolve();
      await release.promise;
      if (synthetic401) await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'synthetic_expired_session' }) });
      else await route.fulfill({ response });
    } catch (error) { failure = error; captured.resolve(); }
    finally { finished.resolve(); }
  };
  await page.route('**/api/**', handler);
  return {
    captured: captured.promise,
    async release() {
      release.resolve();
      await finished.promise;
      if (failure) throw failure;
      await delivered.promise;
      // Let the delivered fetch and React commit drain before negative assertions.
      await page.evaluate(() => new Promise<void>(done => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
      await page.unroute('**/api/**', handler);
    },
  };
}

// A minimal, valid one-page PDF with a text layer; generated test data, no corpus.
export function syntheticPdf(): Buffer {
  const stream = 'BT /F1 14 Tf 72 720 Td (pdfmarker synthetic evidence) Tj ET';
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
  ];
  let pdf = '%PDF-1.4\n';
  const offsets = [0];
  objects.forEach((object, index) => { offsets.push(Buffer.byteLength(pdf)); pdf += `${index + 1} 0 obj\n${object}\nendobj\n`; });
  const xref = Buffer.byteLength(pdf);
  pdf += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(pdf);
}
