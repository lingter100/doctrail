// Browser regression checks use an isolated synthetic database and the packaged UI.
import { spawn, spawnSync } from 'node:child_process';
import { once } from 'node:events';
import { createWriteStream, existsSync, readFileSync, writeFileSync, mkdirSync, mkdtempSync, readdirSync } from 'node:fs';
import { createServer } from 'node:net';
import { join, resolve, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import { startMeetingTransportFixture } from './meeting-transport-fixture.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const repo = resolve(root, '..');
const jar = join(repo, 'server/target/doctrail-server-0.1.0.jar');
const index = join(root, 'dist/index.html');
if (!existsSync(jar) || !existsSync(index)) {
  throw new Error('Build web/dist and the Java JAR before npm run test:e2e (see docs/FRONTEND.md).');
}
// The authentication limiter belongs to a server/IP, not a browser context.
// Give each selected spec its own service and database so unrelated specs do
// not consume one another's quota. Keep production limits and test retries intact.
if (!process.env.DOCTRAIL_E2E_SPEC) {
  mkdirSync(join(repo, '.local'), { recursive: true });
  const batchDirectory = mkdtempSync(join(repo, '.local/web-e2e-batch-'));
  const listing = spawnSync(process.execPath, [join(root, 'node_modules/@playwright/test/cli.js'), 'test', ...process.argv.slice(2), '--list', '--reporter=json'], {
    cwd: root, windowsHide: true, encoding: 'utf8',
    env: { ...process.env, DOCTRAIL_E2E_URL: 'http://127.0.0.1:1', DOCTRAIL_E2E_OUTPUT: batchDirectory },
  });
  if (listing.status !== 0) throw new Error('Could not discover selected browser checks.', { cause: listing.stderr || listing.stdout });
  const listed = JSON.parse(listing.stdout);
  const files = new Set();
  function collect(suites) {
    for (const suite of suites) {
      for (const spec of suite.specs || []) files.add(spec.file);
      collect(suite.suites || []);
    }
  }
  collect(listed.suites || []);
  if (listed.errors?.length || !files.size) throw new Error('No valid browser checks were discovered.');
  let exitCode = 0;
  let child, interrupted = false;
  function interruptBatch() { interrupted = true; if (child?.connected) child.send('interrupt'); }
  process.on('SIGINT', interruptBatch);
  process.on('SIGTERM', interruptBatch);
  try {
    for (const file of files) {
      if (interrupted) { exitCode = 1; break; }
      child = spawn(process.execPath, [fileURLToPath(import.meta.url), ...process.argv.slice(2)], {
        cwd: root, windowsHide: true, stdio: ['inherit', 'inherit', 'inherit', 'ipc'],
        env: { ...process.env, DOCTRAIL_E2E_SPEC: file, DOCTRAIL_E2E_BATCH_DIRECTORY: batchDirectory },
      });
      const status = await new Promise((done, reject) => { child.once('error', reject); child.once('exit', done); });
      if (status !== 0) exitCode = 1;
    }
  } finally {
    process.removeListener('SIGINT', interruptBatch);
    process.removeListener('SIGTERM', interruptBatch);
  }
  const runs = readdirSync(batchDirectory, { withFileTypes: true }).filter(entry => entry.isDirectory()).map(entry => {
    const directory = join(batchDirectory, entry.name);
    const runPath = join(directory, 'run.json'), reportPath = join(directory, 'report.json');
    return { directory: relative(repo, directory),
      ...(existsSync(runPath) ? JSON.parse(readFileSync(runPath, 'utf8')) : { exitCode: 1, serverStopped: false }),
      stats: existsSync(reportPath) ? JSON.parse(readFileSync(reportPath, 'utf8')).stats : null };
  });
  const stats = { expected: 0, unexpected: 0, skipped: 0, flaky: 0 };
  for (const run of runs) for (const key of Object.keys(stats)) stats[key] += run.stats?.[key] || 0;
  if (runs.length !== files.size || runs.some(run => run.exitCode !== 0 || !run.serverStopped || !run.stats)) exitCode = 1;
  writeFileSync(join(batchDirectory, 'run.json'), JSON.stringify({ kind: 'automated-synthetic-browser-batch', isolation: 'service-and-database-per-spec', date: new Date().toISOString(), exitCode, stats, runs, humanReview: false }, null, 2) + '\n');
  console.log(`Browser batch: ${stats.expected} passed, ${stats.unexpected} failed; artifacts: ${relative(repo, batchDirectory)}`);
  process.exit(exitCode);
}
// java writes version/settings to stderr; use spawnSync to retain it without shell parsing.
const settings = spawnSync('java', ['-XshowSettings:properties', '-version'], {
  encoding: 'utf8', windowsHide: true,
});
if (settings.status !== 0) throw new Error('Java runtime could not be resolved.');
const javaHome = settings.stderr.match(/^\s*java.home = (.+)$/m)?.[1].trim();
if (!javaHome) throw new Error('java.home is missing.');
const java = join(javaHome, 'bin', process.platform === 'win32' ? 'java.exe' : 'java');

mkdirSync(join(repo, '.local'), { recursive: true });
const runDirectory = mkdtempSync(join(process.env.DOCTRAIL_E2E_BATCH_DIRECTORY || join(repo, '.local'), 'web-e2e-'));
const listener = createServer();
listener.listen(0, '127.0.0.1');
await once(listener, 'listening');
const port = listener.address().port;
await new Promise((done, reject) => listener.close(error => error ? reject(error) : done()));
const url = `http://127.0.0.1:${port}`;
const log = createWriteStream(join(runDirectory, 'java.log'));
// Only these explicit specs enable a deterministic transport contract fixture.
// All other browser specs keep generation disabled, regardless of shell env.
const meetingFixture = ['meeting-ready.spec.ts', 'meeting-conflict-recovery.spec.ts'].includes(process.env.DOCTRAIL_E2E_SPEC.replaceAll('\\', '/').split('/').at(-1))
  ? await startMeetingTransportFixture() : null;
const server = spawn(java, ['-jar', jar, '--server.address=127.0.0.1', `--server.port=${port}`], {
  cwd: repo, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  env: { ...process.env, DOCTRAIL_DB: join(runDirectory, 'synthetic.sqlite3'),
    DOCTRAIL_INFERENCE_URL: '', DOCTRAIL_INFERENCE_TOKEN: '', DOCTRAIL_EMBEDDING_PROFILE: 'base',
    DOCTRAIL_GENERATION_URL: meetingFixture?.url || '', DOCTRAIL_GENERATION_TOKEN: meetingFixture?.token || '',
    DOCTRAIL_SECURE_COOKIE: '0', DOCTRAIL_WEB_DIST: join(runDirectory, 'no-filesystem-ui') },
});
server.stdout.pipe(log);
server.stderr.pipe(log);
let serverEnded = false;
let serverError;
const serverExit = new Promise(done => {
  server.once('exit', () => { serverEnded = true; done(); });
  server.once('error', error => { serverError = error; serverEnded = true; done(); });
});
let tests;
let interrupted = false;
function interrupt() { interrupted = true; tests?.kill(); server.kill(); }
function onMessage(message) { if (message === 'interrupt') interrupt(); }
process.on('SIGINT', interrupt);
process.on('SIGTERM', interrupt);
process.on('message', onMessage);
let result = 1;
let packagedUi = false;
try {
  const deadline = Date.now() + 60_000;
  while (true) {
    if (serverEnded || interrupted) throw new Error('Isolated Java server exited before browser checks.', { cause: serverError });
    try {
      const health = await fetch(`${url}/api/health`, { signal: AbortSignal.timeout(2000) });
      if (health.ok) break;
    } catch { /* Wait for this process to bind; never reuse another server. */ }
    if (Date.now() > deadline) throw new Error('Isolated Java server startup timed out.');
    await delay(200);
  }
  const packagedIndex = await (await fetch(url)).text();
  if (packagedIndex !== readFileSync(index, 'utf8')) {
    throw new Error('Packaged UI differs from web/dist. Repackage the Java JAR after the frontend build.');
  }
  packagedUi = true;
  tests = spawn(process.execPath, [join(root, 'node_modules/@playwright/test/cli.js'), 'test', ...process.argv.slice(2)], {
    cwd: root, windowsHide: true, stdio: 'inherit',
    env: { ...process.env, DOCTRAIL_E2E_URL: url, DOCTRAIL_E2E_OUTPUT: runDirectory },
  });
  result = await new Promise((done, reject) => {
    tests.once('error', reject);
    tests.once('exit', code => done(code ?? 1));
  });
} finally {
  if (!serverEnded) server.kill();
  await Promise.race([serverExit, delay(15_000, undefined, { ref: false })]);
  if (!serverEnded) { server.kill('SIGKILL'); await Promise.race([serverExit, delay(10_000, undefined, { ref: false })]); }
  log.end();
  if (meetingFixture) await meetingFixture.close();
  process.removeListener('SIGINT', interrupt);
  process.removeListener('SIGTERM', interrupt);
  process.removeListener('message', onMessage);
  if (process.connected) process.disconnect();
  writeFileSync(join(runDirectory, 'run.json'), JSON.stringify({
    kind: 'automated-synthetic-browser-check', date: new Date().toISOString(),
    spec: process.env.DOCTRAIL_E2E_SPEC,
    exitCode: result, serverStopped: serverEnded, packagedUi,
    browser: 'Playwright Chromium', humanReview: false,
    generation: meetingFixture ? 'deterministic-transport-fixture-NOT-LLM' : 'disabled',
    generationCalls: meetingFixture?.calls || null,
  }, null, 2) + '\n');
  console.log(`Browser check artifacts: ${relative(repo, runDirectory)}`);
  if (!serverEnded) throw new Error('Owned Java server could not be stopped.');
}
process.exitCode = result;
