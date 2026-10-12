import { test, expect, register, upload, ready, search, completedSearch } from './support';

test('synthetic model outage: selected method stays explicit and BM25 requires user selection', async ({ page }) => {
  const auth = await register(page.request);
  await upload(page.request, auth.workspaces[0].id, 'Synthetic outage guide', 'outageanchor evidence');
  // Only the availability and outage payloads are synthetic. Auth, documents,
  // successful BM25, evidence and history use the real isolated Java service.
  await page.route('**/api/search/capabilities', route => route.fulfill({ json: {
    default_method: 'bm25', model_enabled: true, status: 'ready',
    methods: ['bm25', 'dense', 'hybrid', 'hybrid_rerank'], available_methods: ['bm25', 'dense', 'hybrid', 'hybrid_rerank'],
  } }));
  const searches: string[] = [];
  await page.route('**/api/workspaces/*/search?*', route => {
    const method = new URL(route.request().url()).searchParams.get('method') || 'bm25';
    searches.push(method);
    return method === 'dense' ? route.fulfill({ status: 503, json: { detail: 'inference_unavailable' } }) : route.continue();
  });
  await ready(page);
  await expect(page.locator('.search-caption')).toContainText('모델 검색 연결됨');
  await page.locator('#search-method').selectOption('dense');
  await search(page, 'outageanchor');
  await expect(page.getByRole('alert')).toContainText('모델 검색을 사용할 수 없어요');
  await expect(page.locator('#search-method')).toHaveValue('dense');
  expect(searches).toEqual(['dense']);
  expect((await (await page.request.get(`/api/workspaces/${auth.workspaces[0].id}/history`)).json()).items).toHaveLength(0);
  await page.locator('#search-method').selectOption('bm25');
  await expect(page.getByRole('alert')).toHaveCount(0);
  await completedSearch(page, 'outageanchor');
  await expect(page.locator('.result-card')).toHaveCount(1);
  expect(searches).toEqual(['dense', 'bm25']);
});
