import json

from scripts.meeting_verification_snapshots import SnapshotVerification
from scripts.verify_meeting_service import FIXTURES


def test_later_client_confirmation_cannot_change_initial_evidence(tmp_path, monkeypatch):
    run = SnapshotVerification('http://127.0.0.1:12345', tmp_path / 'report.json')
    detail = {'document': {'id': 'synthetic-test', 'content': 'source'}, 'meeting': {
        'analysis_status': 'ready', 'version': 1, 'provenance': 'ai',
        'analysis': {'items': [{'id': 'decision', 'status': 'needs_confirmation'}]},
        'ai_analysis': {'items': [{'id': 'decision', 'status': 'needs_confirmation'}]}}}
    monkeypatch.setattr(run, 'request', lambda *args, **kwargs: detail)
    monkeypatch.setattr(run, 'verify_spans', lambda result: None)
    try:
        result = run.meeting('workspace', FIXTURES / 'synthetic-release-planning.md', 'test')
        result['meeting']['analysis']['items'][0]['status'] = 'confirmed'
        result['meeting']['version'] = 2
        run.save()
        saved = json.loads(run.output.read_text(encoding='utf-8'))['analyses'][0]['meeting']
        assert saved['version'] == 1 and saved['provenance'] == 'ai'
        assert saved['analysis']['items'][0]['status'] == 'needs_confirmation'
        assert saved['ai_analysis']['items'][0]['status'] == 'needs_confirmation'
    finally:
        run.close()
