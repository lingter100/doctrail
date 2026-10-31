import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdtempSync, mkdirSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { runServerLifecycle, summarizeRuns, writeRunReceipt } from './java-runner-lifecycle.mjs';

const base = process.env.DOCTRAIL_RUNNER_TEST_OUTPUT || tmpdir();
mkdirSync(base, { recursive: true });
function fixture(code, overrides = {}) {
  const directory = mkdtempSync(join(base, 'runner-lifecycle-'));
  const server = spawn(process.execPath, ['-e', code], {
    windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  });
  const output = once(server.stdout, 'data');
  return { directory, options: {
    server, logPath: join(directory, 'java.log'), spec: 'synthetic.spec.ts',
    startup: async monitor => {
      await monitor.closed;
      throw new Error('Service ended before readiness');
    },
    verifyUi: async () => assert.fail('UI must not run before readiness'),
    runTests: async () => assert.fail('Browser must not run before readiness'),
    ...overrides,
    ...(overrides.startup ? { startup: monitor => overrides.startup({ ...monitor, output }) } : {}),
  } };
}

test('early nonzero exit retains spec, startup failure, both streams and exit status', async () => {
  const { directory, options } = fixture("process.stdout.write('stdout-before-exit\\n'); process.stderr.write('stderr-before-exit\\n'); process.exitCode = 23;");
  const run = await runServerLifecycle(options);
  assert.equal(run.exitCode, 1);
  assert.equal(run.spec, 'synthetic.spec.ts');
  assert.equal(run.failure.message, 'Service ended before readiness');
  assert.equal(run.failure.stage, 'startup');
  assert.equal(run.serverExitCode, 23);
  assert.equal(run.serverSignal, null);
  assert.equal(run.serverStopped, true);
  assert.equal(run.logFlushed, true);
  assert.equal(run.packagedUi, false);
  assert.match(readFileSync(join(directory, 'java.log'), 'utf8'), /stdout-before-exit/);
  assert.match(readFileSync(join(directory, 'java.log'), 'utf8'), /stderr-before-exit/);
});

test('one stream ending first cannot truncate a large delayed second stream', async () => {
  const { directory, options } = fixture("process.stdout.end('stdout-end\\n'); setTimeout(() => process.stderr.write('S'.repeat(512 * 1024) + '\\nstderr-end\\n'), 30);");
  const run = await runServerLifecycle(options);
  assert.equal(run.serverExitCode, 0);
  assert.equal(run.logFlushed, true);
  const log = readFileSync(join(directory, 'java.log'), 'utf8');
  assert.ok(log.includes('stdout-end\n'));
  assert.ok(log.includes('S'.repeat(512 * 1024) + '\nstderr-end\n'));
});

test('spawn error is a recorded startup failure and closes the log', async () => {
  const directory = mkdtempSync(join(base, 'runner-spawn-error-'));
  const server = spawn(join(directory, 'nonexistent-executable'), [], { stdio: ['ignore', 'pipe', 'pipe'] });
  const run = await runServerLifecycle({
    server, logPath: join(directory, 'java.log'), spec: 'spawn-error.spec.ts',
    startup: async monitor => { await monitor.closed; throw new Error('Service spawn failed'); },
    verifyUi: async () => assert.fail('must not verify'),
    runTests: async () => assert.fail('must not run'),
  });
  assert.equal(run.exitCode, 1);
  assert.equal(run.failure.stage, 'startup');
  assert.equal(run.serverError.code, 'ENOENT');
  assert.equal(run.unexpectedServerTermination.event, 'error');
  assert.equal(run.failure.message, 'Service spawn failed');
  assert.equal(run.serverStopped, true);
  assert.equal(run.logFlushed, true);
});

test('successful browser lifecycle records cleanup termination and flushed output', async () => {
  const { directory, options } = fixture("process.stdout.write('ready\\n'); setInterval(() => {}, 1000);", {
    startup: async monitor => { await monitor.output; },
    verifyUi: async () => {}, runTests: async () => 0,
  });
  const run = await runServerLifecycle(options);
  assert.equal(run.exitCode, 0);
  assert.equal(run.stage, 'complete');
  assert.equal(run.failure, null);
  assert.equal(run.serverStopRequested, true);
  assert.equal(run.unexpectedServerTermination, null);
  assert.equal(run.serverStopped, true);
  assert.equal(run.logFlushed, true);
  assert.equal(run.packagedUi, true);
  assert.ok(run.serverSignal !== null || run.serverExitCode !== null);
  if (process.platform !== 'win32') {
    assert.equal(run.serverSignal, 'SIGTERM');
    assert.equal(run.serverExitCode, null);
  }
  assert.match(readFileSync(join(directory, 'java.log'), 'utf8'), /ready/);
});

test('browser nonzero status is preserved separately from startup failure', async () => {
  const { options } = fixture("process.stdout.write('ready\\n'); setInterval(() => {}, 1000);", {
    startup: async monitor => { await monitor.output; },
    verifyUi: async () => {}, runTests: async () => 7,
  });
  const run = await runServerLifecycle(options);
  assert.equal(run.exitCode, 7);
  assert.equal(run.failure.stage, 'browser');
  assert.equal(run.serverStopped, true);
});

test('UI mismatch is recorded at its actual stage and never starts browser tests', async () => {
  const { options } = fixture("process.stdout.write('ready\\n'); setInterval(() => {}, 1000);", {
    startup: async monitor => { await monitor.output; },
    verifyUi: async () => { throw new Error('UI mismatch'); },
  });
  const run = await runServerLifecycle(options);
  assert.equal(run.exitCode, 1);
  assert.equal(run.failure.stage, 'packaged-ui');
  assert.equal(run.failure.message, 'UI mismatch');
  assert.equal(run.packagedUi, false);
});

test('batch cannot hide startup, missing-report or missing-run failures behind passed tests', () => {
  const good = { exitCode: 0, serverStopped: true, stats: { expected: 95, unexpected: 0 } };
  const startup = { exitCode: 1, serverStopped: true, failure: { stage: 'startup' }, stats: null };
  const summary = summarizeRuns([good, startup], 2);
  assert.equal(summary.stats.expected, 95);
  assert.equal(summary.stats.unexpected, 0);
  assert.equal(summary.startupFailures, 1);
  assert.equal(summary.infrastructureFailures, 1);
  assert.equal(summary.unreportedSpecs, 1);
  assert.equal(summary.exitCode, 1);
  assert.equal(summarizeRuns([good, { ...good, stats: null }], 2).exitCode, 1);
  assert.equal(summarizeRuns([good], 2).missingRuns, 1);
  assert.equal(summarizeRuns([good], 2).exitCode, 1);
  assert.equal(summarizeRuns([good], 1).exitCode, 0);
});

test('parent receives nonzero failure and complete JSON/log files after child runner closes', async () => {
  const directory = mkdtempSync(join(base, 'runner-process-boundary-'));
  const helperUrl = new URL('./java-runner-lifecycle.mjs', import.meta.url).href;
  const code = `
    import { spawn } from 'node:child_process';
    import { runServerLifecycle, writeRunReceipt } from ${JSON.stringify(helperUrl)};
    const server = spawn(process.execPath, ['-e', "process.stdout.write('boundary-out'); process.stderr.write('boundary-err'); process.exitCode = 23;"], { stdio: ['ignore', 'pipe', 'pipe'] });
    const run = await runServerLifecycle({
      server, logPath: ${JSON.stringify(join(directory, 'java.log'))}, spec: 'boundary.spec.ts',
      startup: async monitor => { await monitor.closed; throw new Error('Startup failed'); },
      verifyUi: async () => { throw new Error('Unexpected UI launch'); },
      runTests: async () => { throw new Error('Unexpected browser launch'); },
    });
    writeRunReceipt(${JSON.stringify(join(directory, 'run.json'))}, run);
    process.exitCode = run.exitCode;
  `;
  const runner = spawn(process.execPath, ['--input-type=module', '-e', code], { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  let stderr = '';
  runner.stderr.on('data', chunk => { stderr += chunk; });
  runner.stdout.resume();
  const [codeResult, signal] = await once(runner, 'close');
  assert.equal(codeResult, 1, stderr);
  assert.equal(signal, null);
  const run = JSON.parse(readFileSync(join(directory, 'run.json'), 'utf8'));
  assert.equal(run.serverExitCode, 23);
  assert.equal(run.failure.stage, 'startup');
  assert.equal(run.logFlushed, true);
  const log = readFileSync(join(directory, 'java.log'), 'utf8');
  assert.ok(log.includes('boundary-out') && log.includes('boundary-err'));
});

for (const [serverCode, browserCode] of [[23, 0], [0, 0], [23, 7]]) {
  test(`unexpected server exit ${serverCode} is retained with browser result ${browserCode}`, async () => {
    const directory = mkdtempSync(join(base, 'runner-unexpected-exit-'));
    const server = spawn(process.execPath, ['-e', `
      process.stdout.write('ready');
      process.stdin.once('data', () => {
        process.stderr.write('spontaneous-end');
        process.exitCode = ${serverCode};
        process.stdin.destroy();
      });
    `], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
    const ready = once(server.stdout, 'data');
    let closed;
    const run = await runServerLifecycle({
      server, logPath: join(directory, 'java.log'), spec: 'unexpected-exit.spec.ts',
      startup: async monitor => {
        closed = monitor.closed;
        await Promise.race([ready, closed.then(() => { throw new Error('Child ended before readiness'); })]);
      },
      verifyUi: async () => {},
      runTests: async () => { server.stdin.end('exit\n'); await closed; return browserCode; },
    });
    // Preserve the actual result before assertions, including the pre-fix false success.
    writeRunReceipt(join(directory, 'run.json'), run);
    assert.equal(run.exitCode, browserCode || 1);
    assert.equal(run.serverExitCode, serverCode);
    assert.equal(run.serverStopRequested, false);
    assert.equal(run.unexpectedServerTermination.stage, 'browser');
    assert.equal(run.unexpectedServerTermination.code, serverCode);
    if (browserCode === 0) assert.equal(run.failure.kind, 'unexpected-server-termination');
    else {
      assert.equal(run.failure.stage, 'browser');
      assert.equal(run.failure.message, 'Browser checks exited with code 7.');
    }
    assert.notEqual(run.stage, 'complete');
    assert.equal(run.logFlushed, true);
    const summary = summarizeRuns([{ ...run, stats: { expected: 1, unexpected: 0 } }], 1);
    assert.equal(summary.exitCode, 1);
    assert.equal(summary.infrastructureFailures, 1);
  });
}
