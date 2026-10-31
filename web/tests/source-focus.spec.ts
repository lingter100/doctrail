import { test, expect, register, upload, uiUpload, ready, completedSearch } from './support';

// Real isolated Java/SQLite/source reads; only the answer envelope is synthetic.
for (const width of [1440, 390]) {
  test(`source close restores the connected keyboard opener without stealing navigation focus at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    const auth = await register(page.request);
    const doc = await upload(page.request, auth.workspaces[0].id, 'Synthetic focus source', 'focusmarker source evidence');
    await ready(page);
    const row = page.locator(`[data-document="${doc.id}"]`);
    await row.focus(); await page.keyboard.press('Enter');
    await expect(page.locator('#close-source')).toBeFocused();
    await page.keyboard.press('Enter'); await expect(row).toBeFocused();
    await completedSearch(page, 'focusmarker');
    const hit = page.locator('.result-open');
    await hit.focus(); await page.keyboard.press('Enter');
    await expect(page.locator('#close-source')).toBeFocused();
    await page.keyboard.press('Enter'); await expect(hit).toBeFocused();

    await page.locator('[data-view=knowledge]').click();
    const chunk = doc.chunks[0];
    await page.route('**/api/knowledge/answer', route => route.fulfill({ json: {
      status: 'answered', reason: null, results: [], method: 'bm25', model_called: false,
      claims: [{ text: 'Synthetic focus claim', citations: [{ document_id: doc.id, title: doc.title, revision: doc.revision, chunk_id: chunk.id, quote: chunk.text, start_offset: chunk.start_offset, end_offset: chunk.end_offset }] }],
    } }));
    await page.getByLabel('지식 질문').fill('focusmarker');
    await page.getByRole('button', { name: '질문하기', exact: true }).click();
    const citation = page.locator('.citation-chip');
    await citation.focus(); await page.keyboard.press('Enter');
    await expect(page.locator('#source-citation')).toHaveText(chunk.text);
    await expect(page.locator('#close-source')).toBeFocused();
    await page.screenshot({ path: info.outputPath('citation-open.png'), fullPage: false });
    await page.keyboard.press('Enter'); await expect(citation).toBeFocused();
    await page.screenshot({ path: info.outputPath('citation-focus-return.png'), fullPage: false });
    await page.keyboard.press('Tab'); await expect(citation).not.toBeFocused();

    await citation.focus(); await page.keyboard.press('Enter'); await expect(page.locator('#close-source')).toBeFocused();
    const scope = page.locator('.knowledge-form').getByLabel('검색 범위');
    await scope.focus(); await scope.selectOption('all');
    await expect(page.locator('.source-pane')).toHaveCount(0); await expect(scope).toBeFocused();
    await expect(citation).toHaveCount(0);
    await page.getByRole('button', { name: '질문하기', exact: true }).click();
    await citation.focus(); await page.keyboard.press('Enter'); await expect(page.locator('#close-source')).toBeFocused();
    // A subsequent navigation in the same event turn must beat deferred focus.
    await page.evaluate(() => {
      document.getElementById('close-source')!.click();
      const history = document.querySelector<HTMLButtonElement>('[data-view=history]')!;
      history.focus(); history.click();
    });
    await expect(page.locator('[data-view=history]')).toBeFocused();
    await expect(page.locator('.source-pane')).toHaveCount(0);
  });
}

test('detached source opener and session invalidation do not resurrect or refocus obsolete content', async ({ page }) => {
  const auth = await register(page.request);
  const doc = await upload(page.request, auth.workspaces[0].id, 'Synthetic detached opener', 'detached source');
  await ready(page);
  const row = page.locator(`[data-document="${doc.id}"]`);
  await row.focus(); await page.keyboard.press('Enter'); await expect(page.locator('#close-source')).toBeFocused();
  // Remove the opener without mutating React's contents, then restore the same
  // node before the next React render; the close callback sees it disconnected.
  await page.evaluate(async () => {
    const opener = document.querySelector('.document-row')!;
    const parent = opener.parentElement!;
    opener.remove(); document.getElementById('close-source')!.click();
    await new Promise<void>(done => requestAnimationFrame(() => done()));
    const active = document.activeElement;
    parent.append(opener);
    if (active === opener) throw new Error('Detached opener received focus');
  });
  await expect(page.locator('.source-pane')).toHaveCount(0);
  await row.focus(); await page.keyboard.press('Enter'); await expect(page.locator('#close-source')).toBeFocused();
  await page.locator('#logout').click();
  await expect(page.locator('#auth-form')).toBeVisible();
  await expect(page.locator('.source-pane')).toHaveCount(0);
  await expect(page.locator('.document-row')).toHaveCount(0);
});

test('upload replacement never restores the previous document opener and reopening the new document restores its own opener', async ({ page }, info) => {
  const auth = await register(page.request);
  const docA = await upload(page.request, auth.workspaces[0].id, 'Synthetic source A', 'Source A remains in the library.');
  await ready(page);
  const rowA = page.locator(`[data-document="${docA.id}"]`);
  await rowA.focus(); await page.keyboard.press('Enter');
  await expect(page.locator('#source-text')).toHaveText(docA.content);
  const docB = await uiUpload(page, 'source-b.txt', Buffer.from('Source B was uploaded while A was open.'), 'text/plain', 'Synthetic source B');
  await expect(page.locator('#source-text')).toHaveText(docB.content);
  // Let the existing dialog-close focus restoration finish before starting a
  // separate user action on the new source panel.
  await page.evaluate(() => new Promise<void>(done => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
  await page.locator('#close-source').focus(); await expect(page.locator('#close-source')).toBeFocused(); await page.keyboard.press('Enter');
  await expect(page.locator('.source-pane')).toHaveCount(0);
  // Settle the explicit-close animation frame before checking a negative focus
  // assertion; otherwise a premature pass could miss the old opener restoration.
  await page.evaluate(() => new Promise<void>(done => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
  await page.screenshot({ path: info.outputPath('upload-replacement-close.png'), fullPage: false });
  await expect(rowA).not.toBeFocused();
  const rowB = page.locator(`[data-document="${docB.id}"]`);
  await rowB.focus(); await page.keyboard.press('Enter');
  await expect(page.locator('#close-source')).toBeFocused();
  await page.keyboard.press('Enter'); await expect(rowB).toBeFocused();
  await page.screenshot({ path: info.outputPath('new-document-opener-return.png'), fullPage: false });
});
