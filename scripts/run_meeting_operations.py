"""Own one local candidate service, verify real lifecycle and optionally observe its UI."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import psutil

from scripts.verify_meeting_operations import OperationsVerification
from scripts.verify_meeting_service import ROOT, sha


def artifact_snapshot(jar):
    # Bind only this 4B candidate and its dependencies; unrelated 9B preparation
    # can proceed independently without being misreported as a loaded-code change.
    plan = json.loads((ROOT / 'data/evaluation/meetings-answer-decoder-plan-v1.json').read_text(
        encoding='utf-8'))
    paths = [*(ROOT / name for name in plan['bound_files']),
             ROOT / 'src/doctrail/meeting_worker_grammar.py',
             *ROOT.glob('server/src/main/java/io/doctrail/*.java'),
             *ROOT.glob('web/dist/assets/*'), Path(jar).resolve(),
             ROOT / 'scripts/run_meeting_operations.py',
             ROOT / 'scripts/verify_meeting_operations.py',
             ROOT / 'scripts/verify_meeting_service.py',
             ROOT / 'scripts/serve_meetings_candidate.py',
             ROOT / 'scripts/serve_meetings_gguf.py',
             ROOT / 'web/scripts/verify-live-meeting-operations.mjs',
             ROOT / 'data/models/meetings-generation-gguf-v1.json']
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in paths if p.is_file()}


def stop_ui_tree(process):
    """Kill only the still-owned Node process and its observed browser descendants."""
    try:
        parent = psutil.Process(process.pid)
        owned = parent.children(recursive=True) + [parent]
    except psutil.NoSuchProcess:
        return
    for child in owned:
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(owned, timeout=5)
    for child in alive:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--jar', type=Path, default=ROOT / 'server/target/doctrail-server-0.1.0.jar')
    parser.add_argument('--retrieval', action='store_true')
    parser.add_argument('--ui', action='store_true')
    args = parser.parse_args()
    directory = args.output.resolve()
    if not directory.is_relative_to((ROOT / '.local').resolve()) or directory.exists():
        parser.error('choose_new_private_local_output_directory')
    if args.ui and not shutil.which('node'):
        parser.error('node_required_for_ui')
    if not args.jar.is_file():
        parser.error('build_java_jar_first')
    directory.mkdir(parents=True, exist_ok=False)
    before = artifact_snapshot(args.jar)
    from scripts.serve_meetings_candidate import start_services

    with start_services(jar=args.jar, database=directory / 'service.sqlite3',
                        log_dir=directory / 'logs', retrieval=args.retrieval) as services:
        print('experimental_local_services_ready', flush=True)
        run = OperationsVerification(services.java_url, directory / 'operations.json')
        try:
            run.run(learned=args.retrieval)
            if args.ui:
                # This local-only state contains credentials. Never include it in public reports.
                cookies = [{'name': c.name, 'value': c.value, 'domain': c.domain,
                            'path': c.path, 'httpOnly': True, 'secure': False, 'sameSite': 'Lax'}
                           for c in run.owner.cookies.jar]
                state = directory / 'browser-state.json'
                state.write_text(json.dumps({'cookies': cookies, 'origins': []}), encoding='utf-8')
                process = subprocess.Popen([shutil.which('node'),
                    str(ROOT / 'web/scripts/verify-live-meeting-operations.mjs'),
                    '--url', services.java_url, '--state', str(state),
                    '--output', str(directory / 'ui')], cwd=ROOT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                try:
                    process.wait(timeout=180)
                except subprocess.TimeoutExpired:
                    stop_ui_tree(process)
                    raise
                run.check('actual_ui_lifecycle_script', process.returncode == 0)
            run.verify_ready_deletion()
            run.check('loaded_artifacts_unchanged', before == artifact_snapshot(args.jar))
            run.report['status'] = 'passed_analysis_lifecycle_only'
        except Exception as exc:  # noqa: BLE001 - retain safe failure and clean up owned children
            run.report['status'] = 'failed'
            run.report['failure'] = str(exc) if isinstance(exc, AssertionError) else type(exc).__name__
        finally:
            run.report.update(health=services.health, startup_ms=services.startup_ms,
                completed_at=datetime.now(UTC).isoformat(), prelaunch_artifact_hashes=before,
                loaded_sources_unchanged_during_run=(before == artifact_snapshot(args.jar)))
            run.save()
            run.close()
        print(json.dumps({'status': run.report['status'], 'checks': len(run.report['checks']),
                          'analyses': len(run.report['analyses']), 'answer_calls': 0}))
        if run.report['status'] == 'failed':
            raise SystemExit(1)


if __name__ == '__main__':
    main()
