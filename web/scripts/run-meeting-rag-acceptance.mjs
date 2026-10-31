// Local, single-use companion. Importing this module never opens a browser.
import { createHash, randomUUID } from 'node:crypto';
import { existsSync, openSync, writeSync, fsyncSync, closeSync, renameSync, readFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';

export const FAILURE_CODES = new Set([
  'browser_action_failed', 'browser_action_timeout', 'browser_contract_failed',
  'evidence_write_failed', 'browser_close_failed', 'page_error', 'stopped', 'active_timeout',
  'loopback_required', 'get_status', 'capture_before_login', 'duplicate_registration',
  'duplicate_upload', 'duplicate_answer', 'unregistered_post', 'unregistered_mutation',
  'request_guard_failed', 'ui_http_failed', 'ui_binding_mismatch', 'ui_asset_unregistered',
  'registration_failed', 'membership_failed', 'membership_scope', 'source_binding_changed',
  'upload_failed', 'document_owner', 'document_mismatch', 'chunks_mismatch', 'chunk_mismatch',
  'analysis_repeated', 'analysis_failed', 'analysis_identity_failed', 'ingestion_incomplete',
  'duplicate_runtime_uuid', 'answer_failed', 'answer_request_mismatch', 'answer_response_invalid',
  'unauthorized_context', 'citation_mismatch', 'answer_render_mismatch', 'citation_render_mismatch',
  'mobile_overflow', 'ownership_ack_invalid', 'ownership_unconfirmed', 'arguments',
]);
export const FAILURE_STAGES = new Set(['bootstrap', 'ownership', 'ui_verification',
  'registration', 'membership', 'upload', 'analysis', 'access', 'answer', 'citations',
  'capture', 'cleanup']);
export function check(value, code) {
  if (!value) throw Object.assign(new Error('browser_contract_failed'),
    { code: FAILURE_CODES.has(code) ? code : 'browser_contract_failed' });
}
export const sha = value => createHash('sha256').update(value).digest('hex');
export function store(path, value) {
  check(!existsSync(path), 'evidence_write_failed');
  const temporary = `${path}.tmp`;
  const fd = openSync(temporary, 'wx');
  try { writeSync(fd, JSON.stringify(value) + '\n'); fsyncSync(fd); } finally { closeSync(fd); }
  renameSync(temporary, path); // IPC readers see either no record or complete durable JSON.
}
export function failureRecord(error, stage, id, started, monotonic = performance.now()) {
  const code = FAILURE_CODES.has(error?.code) ? error.code :
    ['EIO', 'ENOSPC', 'EACCES', 'EROFS', 'ENOENT'].includes(error?.code) ? 'evidence_write_failed' :
    error?.name === 'TimeoutError' ? 'browser_action_timeout' : 'browser_action_failed';
  return { code, stage: FAILURE_STAGES.has(stage) ? stage : 'bootstrap',
    id: typeof id === 'string' && /^[A-Za-z0-9_-]{1,80}$/.test(id) ? id : null,
    epoch_ms: Date.now(), elapsed_ms: Math.max(0, monotonic - started) };
}
export function preserveFailure(folder, error, stage, id, started) {
  const path = join(folder, 'first-failure.json');
  if (!existsSync(path)) store(path, failureRecord(error, stage, id, started));
}
export function activeDeadline(config, monotonic = performance.now(), epoch = Date.now()) {
  check(Number.isFinite(config.active_budget_ms) && config.active_budget_ms > 0 &&
    config.active_budget_ms <= 1500000 && Number.isFinite(config.budget_epoch_ms), 'active_timeout');
  return monotonic + Math.max(0, config.active_budget_ms - Math.max(0, epoch - config.budget_epoch_ms));
}
export function verifyDocument(source, doc) {
  check(doc.status === 'ready' && doc.revision === 1 && doc.id !== source.prepared_document_id &&
    doc.visibility === source.visibility && sha(doc.content) === source.content_sha256, 'document_mismatch');
  check(doc.chunks.length === source.chunks.length, 'chunks_mismatch');
  doc.chunks.forEach((chunk, index) => {
    const expected = source.chunks[index];
    check(chunk.id !== expected.id && chunk.ordinal === expected.ordinal && chunk.page === expected.page &&
      chunk.start_offset === expected.start_offset && chunk.end_offset === expected.end_offset &&
      sha(chunk.text) === expected.sha256 &&
      Array.from(doc.content).slice(chunk.start_offset, chunk.end_offset).join('') === chunk.text,
    'chunk_mismatch');
  });
}
export function verifyAnswerRequest(body, question, workspace) {
  const expected = { query: question.query, workspace_id: workspace, kind: 'all',
    meeting_id: null, date_from: null, date_to: null, participant: null, assignee: null,
    item_type: null, method: 'hybrid_rerank', limit: 5, expected_embedding_profile: 'base' };
  check(Object.keys(body).length === Object.keys(expected).length &&
    Object.entries(expected).every(([key, value]) => body[key] === value), 'answer_request_mismatch');
}
export function admitAnswer(active, body, question, workspace) {
  check(active?.operation === 'answer' && active.id === question.id && !active.sent,
    'duplicate_answer');
  verifyAnswerRequest(body, question, workspace);
  active.sent = true; // Reservation is consumed even if evidence write/transmission then fails.
}
export function verifySelected(response, docs) {
  check(['answered', 'abstained'].includes(response.status) && response.method === 'hybrid_rerank' &&
    response.results.length <= 5 && Array.isArray(response.claims), 'answer_response_invalid');
  for (const hit of response.results) {
    const doc = docs.find(d => d.id === hit.document_id);
    const chunk = doc?.chunks.find(c => c.id === hit.chunk_id);
    check(doc && chunk && doc.revision === hit.revision &&
      ['text', 'page', 'start_offset', 'end_offset'].every(k => chunk[k] === hit[k]), 'unauthorized_context');
  }
  for (const claim of response.claims) for (const c of claim.citations) {
    const doc = docs.find(d => d.id === c.document_id);
    const chunk = doc?.chunks.find(k => k.id === c.chunk_id);
    check(chunk && c.revision === doc.revision && c.start_offset >= chunk.start_offset &&
      c.end_offset <= chunk.end_offset && c.end_offset > c.start_offset &&
      Array.from(doc.content).slice(c.start_offset, c.end_offset).join('') === c.quote,
    'citation_mismatch');
  }
}

const ANALYSIS_IDENTITY = Object.freeze({ model: 'Qwen/Qwen3.5-9B',
  revision: 'gguf-sha256:dc2a39aef291f91a9116ad214058da0d86eb648743a124bd8c333787c4b9c91c' });
export function verifyAnalysisIdentity(result, expected = ANALYSIS_IDENTITY) {
  check(result.model === expected.model && result.model_revision === expected.revision,
    'analysis_identity_failed');
}
export async function waitForAnalysisDetail(page, expect, limit) {
  const detail = page.getByTestId('meeting-detail');
  await expect(detail).toBeVisible({ timeout: limit() });
  await expect(detail.locator('.analysis-status.ready')).toBeVisible({ timeout: limit() });
}
// Only direct imported test calls may inject a fixture identity; CLI/config never supplies this.
export async function run(config, chromium, expect, { expectedAnalysisIdentity = ANALYSIS_IDENTITY } = {}) {
  const base = new URL(config.base_url), folder = join(config.run_dir, 'browser');
  const started = performance.now();
  let stage = 'bootstrap', opaqueId = null, deadline = activeDeadline(config);
  let stopped = false, browserServer, browser, fatal = null;
  const fail = error => {
    const record = failureRecord(error, stage, opaqueId, started);
    fatal ||= record.code;
    preserveFailure(folder, error, stage, opaqueId, started);
  };
  const contexts = [], actors = {}, mapping = {}, cases = [];
  let active = null, uploads = 0, answers = 0, analyses = 0, attempt = 0, snapshots = 0, authPosts = 0;
  const limit = () => {
    check(!stopped && !existsSync(join(folder, 'stop.json')), 'stopped');
    check(performance.now() < deadline, 'active_timeout');
    check(fatal === null, fatal || 'browser_error');
    return Math.max(1, Math.min(130000, deadline - performance.now()));
  };
  const marker = (operation, id) => {
    limit();
    store(join(folder, `attempt-${attempt++}.json`), { operation, id, consumed: true });
    const temporary = join(config.run_dir, `current-${attempt}.tmp`);
    store(temporary, { operation, id });
    renameSync(temporary, join(config.run_dir, 'current.json'));
    active = { operation, id, sent: false };
  };
  const get = async (context, path, expected = 200) => {
    limit();
    const response = await context.request.get(path, { timeout: limit() });
    check(response.status() === expected, 'get_status');
    return expected === 200 ? response.json() : { status: expected };
  };
  const capture = async (page, name) => {
    const previous = stage; stage = 'capture';
    limit();
    check(await page.locator('#workspace-select').isVisible(), 'capture_before_login');
    await page.screenshot({ path: join(folder, `${snapshots}-${name}.png`), fullPage: true,
      timeout: limit() });
    store(join(folder, `${snapshots++}-${name}-dom.json`), {
      // Scope excludes scripts/auth state; no HAR, trace, headers or cookies.
      html: await page.locator('main').innerHTML(), captured_epoch_ms: Date.now() });
    limit();
    stage = previous;
  };
  const watch = context => {
    context.on('page', page => page.on('pageerror', () => {
      try { fail({ code: 'page_error' }); } catch { fatal = 'evidence_write_failed'; }
    }));
    // An admission guard only: continue the genuine request without fixture/response substitution.
    return context.route('**/api/**', async route => {
      try {
        limit();
        const request = route.request(), path = new URL(request.url()).pathname;
        if (request.method() === 'POST') {
          if (path === '/api/auth/register') {
            check(++authPosts <= 2, 'duplicate_registration'); // Credentials never archived.
          }
          else if (/\/workspaces\/[^/]+\/(documents|meetings)$/.test(path)) {
            check(active?.operation === 'upload' && !active.sent && uploads < 6, 'duplicate_upload');
            active.sent = true; uploads++;
          } else if (path === '/api/knowledge/answer') {
            check(active?.operation === 'answer' && !active.sent, 'duplicate_answer');
            const question = config.questions.cases.find(c => c.id === active.id);
            const family = config.families.find(f => f.id === question.family_id);
            const body = request.postDataJSON();
            admitAnswer(active, body, question, actors[family.principal].workspace);
            store(join(folder, `answer-${active.id}-request.json`), body);
            answers++;
          } else check(false, 'unregistered_post');
        } else check(request.method() === 'GET' &&
          (!path.endsWith('/search') && !path.endsWith('/knowledge/search')), 'unregistered_mutation');
        await route.continue();
      } catch (error) {
        try { fail(error); } catch { fatal = 'evidence_write_failed'; }
        await route.abort();
      }
    });
  };
  const timer = setInterval(() => {
    if (performance.now() >= deadline || existsSync(join(folder, 'stop.json'))) {
      stopped = true;
      // Close only this companion's browser. Driver still measures whole cleanup.
      void browser?.close().catch(() => {
        try { fail({ code: 'browser_close_failed' }); } catch { fatal = 'evidence_write_failed'; }
      });
    }
  }, 50);
  try {
    check(base.hostname === '127.0.0.1' && base.protocol === 'http:' &&
      !base.username && !base.password && base.pathname === '/', 'loopback_required');
    limit();
    stage = 'ownership';
    browserServer = await chromium.launchServer({ timeout: limit() });
    store(join(folder, 'chromium.json'), { node_pid: process.pid, pid: browserServer.process().pid });
    // No connection, page, authentication or upload before live parent adoption.
    const acknowledgement = join(folder, 'chromium-adopted.json');
    while (!existsSync(acknowledgement)) {
      limit();
      check(browserServer.process().exitCode === null, 'ownership_unconfirmed');
      await new Promise(done => setTimeout(done, 10));
    }
    const owner = JSON.parse(readFileSync(acknowledgement, 'utf8'));
    check(owner.node_pid === process.pid && owner.chromium_pid === browserServer.process().pid &&
      Number.isFinite(owner.node_create_time) && Number.isFinite(owner.chromium_create_time),
    'ownership_ack_invalid');
    deadline = Math.min(deadline, activeDeadline(owner));
    limit();
    browser = await chromium.connect(browserServer.wsEndpoint(), { timeout: limit() });
    stage = 'ui_verification';
    // Verify every actual served UI asset; compare complete bytes, no rebuild.
    const probeContext = await browser.newContext({ baseURL: config.base_url });
    contexts.push(probeContext);
    const uiSeen = new Set();
    for (const asset of config.ui) {
      const response = await probeContext.request.get(asset.url, { timeout: limit() });
      check(response.status() === 200, 'ui_http_failed');
      const bytes = await response.body();
      check(sha(bytes) === asset.sha256, 'ui_binding_mismatch');
      uiSeen.add(asset.url);
      if (asset.url === '/') {
        const paths = [...bytes.toString('utf8').matchAll(/(?:src|href)=["']([^"']+\.(?:js|css))["']/g)]
          .map(match => new URL(match[1], config.base_url).pathname);
        check(paths.length > 0 && paths.every(path => config.ui.some(a => a.url === path)),
          'ui_asset_unregistered');
      }
    }
    store(join(folder, 'ui-verified.json'), { assets: [...uiSeen] });
    for (const family of config.families) {
      stage = 'registration'; opaqueId = null;
      const context = await browser.newContext({ baseURL: config.base_url,
        viewport: { width: 1440, height: 1000 }, locale: 'ko-KR' });
      contexts.push(context); await watch(context);
      const page = await context.newPage();
      page.setDefaultTimeout(Math.min(15000, limit()));
      await page.goto('/', { timeout: limit() });
      await page.getByRole('tab', { name: '새로 시작하기' }).click();
      const email = `acceptance-${randomUUID()}@example.invalid`, password = randomUUID();
      await page.getByLabel('이름', { exact: true }).fill(family.principal);
      await page.getByLabel('이메일', { exact: true }).fill(email);
      await page.getByLabel('비밀번호', { exact: true }).fill(password);
      await page.getByLabel('워크스페이스 이름', { exact: true }).fill(family.id);
      const pending = page.waitForResponse(r => new URL(r.url()).pathname === '/api/auth/register',
        { timeout: limit() });
      await page.getByRole('button', { name: '워크스페이스 만들기' }).click();
      const response = await pending; check(response.status() === 201, 'registration_failed');
      const auth = await response.json();
      actors[family.principal] = { page, context, workspace: auth.workspaces[0].id,
        user: auth.user.id, email };
      await expect(page.locator('#workspace-select')).toBeVisible({ timeout: limit() });
    }
    // actor2 joins actor1's workspace: private denial is tested with a real member.
    const first = actors.actor1, second = actors.actor2;
    stage = 'membership';
    const membership = await first.context.request.post(`/api/workspaces/${first.workspace}/members`,
      { data: { email: second.email }, timeout: limit() });
    check(membership.status() === 201, 'membership_failed');
    store(join(folder, 'principals.json'), Object.fromEntries(Object.entries(actors).map(
      ([key, actor]) => [key, { user_id: actor.user, workspace_id: actor.workspace }])));
    for (const [key, actor] of Object.entries(actors)) {
      const memberships = await get(actor.context, '/api/workspaces');
      check(memberships.items.length === (key === 'actor1' ? 1 : 2), 'membership_scope');
      store(join(folder, `membership-${key}.json`), memberships);
    }
    for (const source of config.sources) {
      stage = 'upload'; opaqueId = source.source_id;
      const family = config.families.find(f => f.id === source.family_id);
      const actor = actors[family.principal], { page, context } = actor;
      await page.locator('#workspace-select').selectOption(actor.workspace);
      await page.locator(`[data-view="${source.kind === 'meeting' ? 'meetings' : 'library'}"]`).click();
      if (await page.locator('#close-source').isVisible()) await page.locator('#close-source').click();
      marker('upload', source.source_id);
      // The runtime marker names the upcoming automatic analysis before the upload POST.
      const temporary = join(config.run_dir, `analysis-${attempt}.tmp`);
      store(temporary, { operation: 'analyze', id: source.source_id });
      renameSync(temporary, join(config.run_dir, 'current.json'));
      if (source.kind === 'meeting') await page.getByRole('button', { name: '회의 등록', exact: true }).click();
      else await page.locator('#upload').click();
      const dialog = page.getByRole('dialog');
      if (source.kind === 'meeting') await dialog.getByRole('tab', { name: '파일 업로드' }).click();
      check(sha(readFileSync(resolve(source.raw.path))) === source.raw.sha256, 'source_binding_changed');
      await dialog.getByLabel(source.kind === 'meeting' ? '회의록 파일' : '업로드할 문서 파일',
        { exact: true }).setInputFiles(resolve(source.raw.path));
      await dialog.locator('input[name=title]').fill(source.title);
      await dialog.locator('select[name=visibility]').selectOption(source.visibility);
      const endpoint = `/api/workspaces/${actor.workspace}/${source.kind === 'meeting' ? 'meetings' : 'documents'}`;
      const pending = page.waitForResponse(r => new URL(r.url()).pathname === endpoint &&
        r.request().method() === 'POST', { timeout: limit() });
      await dialog.getByRole('button', {
        name: source.kind === 'meeting' ? '등록하고 분석 요청' : '업로드', exact: true }).click();
      const response = await pending;
      const uploaded = await response.json();
      store(join(folder, `upload-${source.source_id}.json`), { status: response.status(), body: uploaded });
      check(response.status() === 201, 'upload_failed');
      const doc = uploaded.document || uploaded;
      verifyDocument(source, doc);
      check(doc.workspace_id === actor.workspace && doc.owner_id === actor.user, 'document_owner');
      const readback = await get(context, `/api/documents/${doc.id}`);
      verifyDocument(source, readback);
      mapping[source.source_id] = { source_id: source.source_id, source_revision: source.revision,
        prepared_document_id: source.prepared_document_id, document: readback };
      store(join(folder, `mapping-${source.source_id}.json`), mapping[source.source_id]);
      if (source.kind === 'meeting') {
        stage = 'analysis';
        let detail, runs, last = '', observation = 0;
        while (true) {
          detail = await get(context, `/api/meetings/${doc.id}`);
          runs = await get(context, `/api/meetings/${doc.id}/runs`);
          const fingerprint = sha(JSON.stringify({ detail, runs }));
          if (fingerprint !== last) {
            store(join(folder, `analysis-${source.source_id}-observation-${observation++}.json`),
              { detail, runs, epoch_ms: Date.now() });
            last = fingerprint;
          }
          check(runs.items.length <= 1, 'analysis_repeated');
          if (detail.meeting.analysis_status === 'ready') break;
          check(['pending', 'running', 'queued'].includes(detail.meeting.analysis_status),
            'analysis_failed');
          await new Promise(done => setTimeout(done, 100));
        }
        check(runs.items.length === 1 && runs.items[0].status === 'ready' &&
          runs.items[0].source_revision === doc.revision &&
          detail.meeting.source_revision === doc.revision && detail.meeting.ai_analysis,
        'analysis_identity_failed');
        verifyAnalysisIdentity(runs.items[0], expectedAnalysisIdentity);
        analyses++;
        store(join(folder, `analysis-${source.source_id}.json`), { detail, runs });
        // Refresh UI via GET only, never manual analyze.
        await page.locator('[data-view="meetings"]').click();
        await page.reload({ timeout: limit() });
        await expect(page.locator('#workspace-select')).toBeVisible({ timeout: limit() });
        await page.locator('#workspace-select').selectOption(actor.workspace, { timeout: limit() });
        await page.locator('[data-view="meetings"]').click();
        await page.locator(`[data-meeting="${doc.id}"]`).click();
        await waitForAnalysisDetail(page, expect, limit);
        await capture(page, `analysis-${source.source_id}`);
      }
    }
    check(uploads === 6 && analyses === 4, 'ingestion_incomplete');
    check(new Set(Object.values(mapping).map(m => m.document.id)).size === 6, 'duplicate_runtime_uuid');
    const access = [];
    stage = 'access'; opaqueId = null;
    for (const source of config.sources) {
      const family = config.families.find(f => f.id === source.family_id);
      const doc = mapping[source.source_id].document;
      for (const principal of ['actor1', 'actor2']) {
        const allowed = principal === family.principal ||
          (principal === 'actor2' && family.principal === 'actor1' && source.visibility === 'workspace');
        await get(actors[principal].context, `/api/documents/${doc.id}`, allowed ? 200 : 404);
        access.push({ source_id: source.source_id, principal, allowed, revision: doc.revision });
      }
    }
    store(join(folder, 'access.json'), access);
    for (const question of config.questions.cases) {
      stage = 'answer'; opaqueId = question.id;
      const family = config.families.find(f => f.id === question.family_id);
      const { page, workspace } = actors[family.principal];
      await page.locator('#workspace-select').selectOption(workspace);
      await page.locator('[data-view="knowledge"]').click();
      const form = page.locator('.knowledge-form');
      await form.getByLabel('검색 범위').selectOption('current');
      await form.getByLabel('자료 종류').selectOption('all');
      await form.getByLabel('검색 방식').selectOption('hybrid_rerank');
      await page.getByLabel('지식 질문').fill(question.query);
      marker('answer', question.id);
      const before = Date.now();
      const pending = page.waitForResponse(r => new URL(r.url()).pathname === '/api/knowledge/answer' &&
        r.request().method() === 'POST', { timeout: limit() });
      await page.getByRole('button', { name: '질문하기', exact: true }).click();
      const response = await pending, payload = await response.json();
      store(join(folder, `answer-${question.id}-response.json`),
        { status: response.status(), body: payload, click_to_stored_ms: Date.now() - before });
      check(response.status() === 200, 'answer_failed');
      const docs = config.sources.filter(s => s.family_id === question.family_id)
        .map(s => mapping[s.source_id].document);
      verifySelected(payload, docs);
      await expect(page.getByTestId('knowledge-answer')).toBeVisible({ timeout: limit() });
      check((await page.locator('.answer-claims p').allTextContents()).join('\n') ===
        payload.claims.map(c => c.text).join('\n'), 'answer_render_mismatch');
      await capture(page, `answer-${question.id}`);
      const citations = payload.claims.flatMap(claim => claim.citations);
      stage = 'citations';
      check(await page.locator('.claim-citations button').count() === citations.length,
        'citation_render_mismatch');
      for (let i = 0; i < citations.length; i++) {
        const citation = citations[i], doc = docs.find(d => d.id === citation.document_id);
        await page.locator('.claim-citations button').nth(i).click();
        await expect(page.locator('#source-text')).toHaveText(doc.content, { timeout: limit() });
        await expect(page.locator('#source-citation')).toHaveText(citation.quote, { timeout: limit() });
        await expect(page.locator('.source-badges')).toContainText(`버전 ${citation.revision}`);
        await capture(page, `citation-${question.id}-${i}`);
        await page.locator('#close-source').click();
      }
      if (cases.length === 0) {
        await page.setViewportSize({ width: 390, height: 844 });
        check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
          'mobile_overflow');
        await capture(page, 'mobile');
        await page.setViewportSize({ width: 1440, height: 1000 });
      }
      cases.push({ id: question.id, response: payload, citations_opened: citations.length });
      store(join(folder, `case-${question.id}-completed.json`), { id: question.id, status: 'completed' });
      limit();
    }
    store(join(folder, 'result.json'), { status: 'completed', analysis_count: analyses,
      answer_posts: answers, cases, mapping, document_sources: Object.fromEntries(
        Object.values(mapping).map(m => [m.document.id, m.source_id])) });
  } catch (error) {
    fail(error); // Preserve the first fixed code before cleanup can fail too.
    throw error;
  } finally {
    stage = 'cleanup';
    // Archival failure must not skip releasing our actual browser handles.
    let closed = true;
    try { store(join(folder, 'browser-cleanup-started.json'), { epoch_ms: Date.now() }); }
    catch (error) { closed = false; try { fail(error); } catch { /* Original partial evidence remains. */ } }
    clearInterval(timer);
    stopped = true;
    for (const context of contexts) {
      try { await context.close(); } catch { closed = false; try { fail({ code: 'browser_close_failed' }); } catch {} }
    }
    try { await browser?.close(); } catch { closed = false; try { fail({ code: 'browser_close_failed' }); } catch {} }
    try { await browserServer?.close(); } catch { closed = false; try { fail({ code: 'browser_close_failed' }); } catch {} }
    store(join(folder, 'browser-closed.json'), { closed, analysis_count: analyses, answer_posts: answers });
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  let config;
  const started = performance.now();
  try {
    check(process.argv.length === 4 && process.argv[2] === '--config', 'arguments');
    config = JSON.parse(readFileSync(process.argv[3], 'utf8'));
    const { chromium, expect } = await import('@playwright/test');
    await run(config, chromium, expect);
  } catch (error) {
    if (config?.run_dir) {
      try { preserveFailure(join(config.run_dir, 'browser'), error, 'bootstrap', null, started); }
      catch { /* Existing partial artifact is retained; never print the underlying error. */ }
    }
    process.exitCode = 1; // No credentials, source text, native output or Playwright call logs.
  }
}
