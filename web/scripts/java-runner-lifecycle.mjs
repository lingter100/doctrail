// Process lifecycle diagnostics for isolated, synthetic browser checks.
import { createWriteStream, writeFileSync } from 'node:fs';
import { finished } from 'node:stream/promises';
import { setTimeout as delay } from 'node:timers/promises';

function errorDetails(error) {
  return { name: error.name, message: error.message, ...(error.code ? { code: error.code } : {}) };
}

export async function runServerLifecycle({ server, logPath, spec, startup, verifyUi, runTests, cleanup = async () => {} }) {
  const run = {
    spec, stage: 'startup', failure: null, exitCode: 1, packagedUi: false,
    serverStopped: false, serverExitCode: null, serverSignal: null, serverError: null,
    logFlushed: false, logError: null, serverStopRequested: false, unexpectedServerTermination: null,
  };
  const log = createWriteStream(logPath);
  // Neither stdout nor stderr owns the shared destination. End it only after
  // ChildProcess.close, which follows both streams draining (unlike exit).
  const logFinished = finished(log).then(() => { run.logFlushed = true; }, error => {
    run.logError = errorDetails(error);
  });
  server.stdout.pipe(log, { end: false });
  server.stderr.pipe(log, { end: false });
  let ended = false;
  function recordUnexpectedTermination(event, code, signal, error = null) {
    if (!run.serverStopRequested) {
      run.unexpectedServerTermination ||= { stage: run.stage, event, code, signal, error };
    }
  }
  function preserveUnexpectedFailure() {
    if (!run.unexpectedServerTermination) return;
    const termination = run.unexpectedServerTermination;
    // Callback failures retain their original reason/code; the independently
    // observed server failure still invalidates a browser result of zero.
    run.failure ||= {
      stage: termination.stage, kind: 'unexpected-server-termination',
      message: `Owned server ended without a stop request (event=${termination.event}, code=${termination.code}, signal=${termination.signal}).`,
    };
    if (run.exitCode === 0) run.exitCode = 1;
  }
  const closed = new Promise(done => {
    server.once('exit', (code, signal) => {
      recordUnexpectedTermination('exit', code, signal);
      ended = true;
      run.serverExitCode = code;
      run.serverSignal = signal;
    });
    server.once('error', error => {
      run.serverError = errorDetails(error);
      recordUnexpectedTermination('error', null, null, run.serverError);
      ended = true;
    });
    server.once('close', (code, signal) => {
      ended = true;
      run.serverStopped = true;
      run.serverExitCode = code;
      run.serverSignal = signal;
      done();
    });
  });
  const monitor = { get ended() { return ended; }, closed, run };
  try {
    await startup(monitor);
    run.stage = 'packaged-ui';
    await verifyUi();
    run.packagedUi = true;
    run.stage = 'browser';
    run.exitCode = await runTests();
    if (run.exitCode !== 0) run.failure ||= { stage: run.stage, message: `Browser checks exited with code ${run.exitCode}.` };
  } catch (error) {
    run.failure ||= { stage: run.stage, ...errorDetails(error) };
    run.exitCode = 1;
  } finally {
    preserveUnexpectedFailure();
    if (!ended) {
      run.serverStopRequested = true;
      server.kill();
    }
    await Promise.race([closed, delay(15_000, undefined, { ref: false })]);
    if (!run.serverStopped) {
      run.serverStopRequested = true;
      server.kill('SIGKILL');
      await Promise.race([closed, delay(10_000, undefined, { ref: false })]);
    }
    // On a stop failure, stop accepting output before closing the log; the
    // failed cleanup is retained rather than claiming a normal full flush.
    if (!run.serverStopped) {
      server.stdout.unpipe(log);
      server.stderr.unpipe(log);
    }
    log.end();
    await logFinished;
    preserveUnexpectedFailure();
    try { await cleanup(); } catch (error) {
      run.cleanupError = errorDetails(error);
      run.failure ||= { stage: 'cleanup', ...run.cleanupError };
      if (run.exitCode === 0) run.exitCode = 1;
    }
    if (!run.serverStopped || run.logError) {
      run.failure ||= { stage: 'cleanup', message: !run.serverStopped ? 'Owned server could not be stopped.' : 'Server log could not be flushed.' };
      if (run.exitCode === 0) run.exitCode = 1;
    }
  }
  if (!run.failure) run.stage = 'complete';
  return run;
}

export function summarizeRuns(runs, selectedSpecs) {
  const stats = { expected: 0, unexpected: 0, skipped: 0, flaky: 0 };
  for (const run of runs) for (const key of Object.keys(stats)) stats[key] += run.stats?.[key] || 0;
  const startupFailures = runs.filter(run => run.failure?.stage === 'startup').length;
  const infrastructureFailures = runs.filter(run => run.unexpectedServerTermination || !run.stats || !run.serverStopped || (run.failure && run.failure.stage !== 'browser')).length;
  const unreportedSpecs = runs.filter(run => !run.stats).length;
  const missingRuns = Math.max(0, selectedSpecs - runs.length);
  const failed = runs.length !== selectedSpecs || runs.some(run => run.exitCode !== 0 || !run.serverStopped || !run.stats);
  return { stats, startupFailures, infrastructureFailures, unreportedSpecs, missingRuns, exitCode: failed ? 1 : 0 };
}

export function writeRunReceipt(path, run) {
  writeFileSync(path, JSON.stringify(run, null, 2) + '\n');
}
