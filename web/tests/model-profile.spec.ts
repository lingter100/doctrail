import { test, expect, register, upload, ready, search, completedSearch } from './support';
import type { Page } from '@playwright/test';

// Model metadata and learned responses are synthetic. Sessions, documents and
// BM25 still use the isolated Java service; these checks claim no model quality.
const base = { id: 'base', model: 'intfloat/multilingual-e5-small', revision: '614241f622f53c4eeff9890bdc4f31cfecc418b3' };
const terminal = { id: 'm4-terminal-v1', model: 'doctrail/multilingual-e5-small-m4-terminal-v1', revision: '62e530d3094e98b336d039f10956c8e0e2a39d24d66b07818e92a46f0aac10fb' };
const methods = ['bm25', 'dense', 'hybrid', 'hybrid_rerank'];
function capabilities(profile = terminal) {
  return { default_method: 'bm25', model_enabled: true, status: 'ready', methods, available_methods: methods, embedding_profile: profile };
}
function result(profile = terminal, id = 'synthetic-learned') {
  return { query: 'profileanchor', method: 'dense', elapsed_ms: 1, search_id: id, results: [], embedding_profile: profile };
}
async function mockCapabilities(page: Page, profile = terminal) {
  await page.route('**/api/search/capabilities', route => route.fulfill({ json: capabilities(profile) }));
}

test('synthetic terminal profile is labeled without changing BM25 default and remains in learned history', async ({ page }) => {
  const auth = await register(page.request);
  await upload(page.request, auth.workspaces[0].id, 'Synthetic profile guide', 'profileanchor evidence');
  await mockCapabilities(page);
  const guards: (string | null)[] = [];
  await page.route('**/api/workspaces/*/search?*', route => {
    const params = new URL(route.request().url()).searchParams;
    if (params.get('method') === 'bm25') return route.continue();
    guards.push(params.get('expected_embedding_profile'));
    return route.fulfill({ json: result() });
  });
  await ready(page);
  await expect(page.locator('#search-method')).toHaveValue('bm25');
  await expect(page.locator('.search-caption')).toContainText('학습 실험 모델');
  await completedSearch(page, 'profileanchor');
  await expect(page.locator('.section-bar')).not.toContainText('학습 실험 모델');
  await page.locator('#search-method').selectOption('dense');
  await completedSearch(page, 'profileanchor');
  await expect(page.locator('.section-bar')).toContainText('학습 실험 모델');
  await expect(page.locator('body')).not.toContainText(terminal.revision);
  await page.locator('[data-view=history]').click();
  await expect(page.locator('.history-row').first()).toContainText('학습 실험 모델');
  await page.locator('.history-row').first().click();
  await expect(page.locator('.section-bar')).toContainText('학습 실험 모델');
  expect(guards).toEqual(['m4-terminal-v1', 'm4-terminal-v1']);
});

test('different and unknown historical models require an explicit new search with the current profile', async ({ page }) => {
  await register(page.request);
  await mockCapabilities(page, base);
  await page.route('**/api/workspaces/*/history', route => route.fulfill({ json: { items: [
    { id: 'terminal-past', query: 'previous terminal', method: 'dense', created_at: '2026-01-02T00:00:00Z', result_count: 1, embedding_profile: terminal },
    { id: 'unknown-past', query: 'unknown legacy', method: 'dense', created_at: '2026-01-01T00:00:00Z', result_count: 1, embedding_profile: null },
  ] } }));
  const guards: (string | null)[] = [];
  await page.route('**/api/workspaces/*/search?*', route => {
    guards.push(new URL(route.request().url()).searchParams.get('expected_embedding_profile'));
    return route.fulfill({ json: result(base) });
  });
  await ready(page);
  await page.locator('[data-view=history]').click();
  await page.locator('.history-row').filter({ hasText: 'previous terminal' }).click();
  await expect(page.getByTestId('history-model-notice')).toContainText('현재 모델과 달라요');
  expect(guards).toEqual([]);
  await completedSearch(page, 'previous terminal');
  expect(guards).toEqual(['base']);
  await expect(page.locator('.section-bar')).toContainText('기본 모델');
  await page.locator('[data-view=history]').click();
  await page.locator('.history-row').filter({ hasText: 'unknown legacy' }).click();
  await expect(page.getByTestId('history-model-notice')).toContainText('사용한 모델 정보가 없어');
  expect(guards).toEqual(['base']);
});

test('late learned profile response cannot replace a newer BM25 search or its history', async ({ page }) => {
  const auth = await register(page.request);
  await upload(page.request, auth.workspaces[0].id, 'Synthetic race guide', 'profileanchor evidence');
  await mockCapabilities(page);
  let release!: () => void, captured!: () => void;
  const pending = new Promise<void>(done => { release = done; });
  const arrived = new Promise<void>(done => { captured = done; });
  await page.route('**/api/workspaces/*/search?*', async route => {
    if (new URL(route.request().url()).searchParams.get('method') === 'bm25') return route.continue();
    captured(); await pending; await route.fulfill({ json: result() });
  });
  await ready(page);
  await page.locator('#search-method').selectOption('dense');
  await search(page, 'late terminal');
  await arrived;
  await page.locator('#search-method').selectOption('bm25');
  await completedSearch(page, 'profileanchor');
  const response = page.waitForResponse(r => r.url().includes('method=dense'));
  release(); await response;
  await page.evaluate(() => new Promise<void>(done => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
  await expect(page.locator('.result-card')).toHaveCount(1);
  await expect(page.locator('.section-bar')).not.toContainText('학습 실험 모델');
  await page.locator('[data-view=history]').click();
  await expect(page.locator('.history-row')).toHaveCount(1);
  await expect(page.locator('.history-row')).toContainText('키워드 검색');
});

test('server profile conflict refreshes the visible model and never automatically reruns', async ({ page }) => {
  await register(page.request);
  let capabilityCalls = 0;
  await page.route('**/api/search/capabilities', route => route.fulfill({ json: capabilities(capabilityCalls++ === 0 ? terminal : base) }));
  const guards: (string | null)[] = [];
  await page.route('**/api/workspaces/*/search?*', route => {
    guards.push(new URL(route.request().url()).searchParams.get('expected_embedding_profile'));
    return guards.length === 1 ? route.fulfill({ status: 409, json: { detail: 'embedding_profile_changed' } }) : route.fulfill({ json: result(base) });
  });
  await ready(page);
  await page.locator('#search-method').selectOption('dense');
  await search(page, 'profileanchor');
  await expect(page.getByTestId('history-model-notice')).toContainText('연결된 모델이 변경');
  await expect(page.locator('.search-caption')).toContainText('기본 모델');
  expect(guards).toEqual(['m4-terminal-v1']);
  await completedSearch(page, 'profileanchor');
  expect(guards).toEqual(['m4-terminal-v1', 'base']);
  await expect(page.locator('.section-bar')).toContainText('기본 모델');
});
