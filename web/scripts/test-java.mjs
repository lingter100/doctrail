// Browser regression checks use an isolated synthetic database and the packaged UI.
import { spawn, spawnSync } from 'node:child_process';
import { once } from 'node:events';
import { createWriteStream, existsSync, readFileSync, writeFileSync, mkdirSync, mkdtempSync } from 'node:fs';
import { createServer } from 'node:net';
import { join, resolve, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const root = fileURLToPath(new URL('../', import.meta.url));
const repo = resolve(root, '..');
const jar = join(repo, 'server/target/doctrail-server-0.1.0.jar');
const index = join(root, 'dist/index.html');
if (!existsSync(jar) || !existsSync(index)) {
  throw new Error('Build web/dist and the Java JAR before npm run test:e2e (see docs/FRONTEND.md).');
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
const runDirectory = mkdtempSync(join(repo, '.local/web-e2e-'));
const listener = createServer();
listener.listen(0, '127.0.0.1');
await once(listener, 'listening');
const port = listener.address().port;
await new Promise((done, reject) => listener.close(error => error ? reject(error) : done()));
const url = `http://127.0.0.1:${port}`;
const log = createWriteStream(join(runDirectory, 'java.log'));
const server = spawn(java, ['-jar', jar, `--server.port=${port}`], {
  cwd: repo, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  env: { ...process.env, DOCTRAIL_DB: join(runDirectory, 'synthetic.sqlite3'),
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
process.on('SIGINT', interrupt);
process.on('SIGTERM', interrupt);
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
  process.removeListener('SIGINT', interrupt);
  process.removeListener('SIGTERM', interrupt);
  writeFileSync(join(runDirectory, 'run.json'), JSON.stringify({
    kind: 'automated-synthetic-browser-check', date: new Date().toISOString(),
    exitCode: result, serverStopped: serverEnded, packagedUi,
    browser: 'Playwright Chromium', humanReview: false,
  }, null, 2) + '\n');
  console.log(`Browser check artifacts: ${relative(repo, runDirectory)}`);
  if (!serverEnded) throw new Error('Owned Java server could not be stopped.');
}
process.exitCode = result;
