"""Actual meeting lifecycle verification, explicitly excluding natural-answer readiness.

This independent scope does not repair or supersede failed full-service v1/v2 checks.
It calls real AI analysis and real Java retrieval, edits, ACL and deletion endpoints.
"""
from __future__ import annotations

import argparse
import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from scripts.verify_meeting_service import FIXTURES, ROOT, Verification, sha


class OperationsVerification(Verification):
    def __init__(self, url, output):
        super().__init__(url, output)
        self.report.update(kind='meeting_analysis_lifecycle_only',
                           natural_answer_readiness=False,
                           excluded_scope=['natural_answer_quality'],
                           answer_calls=0)
        self.report['source_hashes'][Path(__file__).relative_to(ROOT).as_posix()] = sha(Path(__file__))

    def run(self, *, learned=False):
        workspace, _ = self.register(self.owner, "owner")
        _, member_email = self.register(self.member, "member")
        feb = self.meeting(workspace, FIXTURES / "public/jupyter-february-2025.md", "Jupyter February")
        june = self.meeting(workspace, FIXTURES / "public/jupyter-june-2025.md", "Jupyter June")
        guide = self.upload_document(workspace, FIXTURES / "public/jupyter-host-guide.md", "Host guide")
        self.check("real_meetings_are_distinct", feb["document"]["id"] != june["document"]["id"])
        mixed = self.search("community meeting host guide Jupyter", workspace_id=workspace)
        self.check("ordinary_and_meeting_results", {r["document_kind"] for r in mixed["results"]}
                   == {"meeting", "document"})
        self.check("outsider_search_empty", not self.search("Jupyter", client=self.member)["results"])
        self.request(self.owner, "POST", f"/workspaces/{workspace}/members", expected=201,
                     json={"email": member_email})
        first = self.meeting(workspace, FIXTURES / "synthetic-release-planning.md", "출시 회의")
        later = self.meeting(workspace, FIXTURES / "synthetic-release-followup.md", "후속 회의")
        self.upload_document(workspace, FIXTURES / "synthetic-runbook.md", "Search operations")
        a, b = first["meeting"]["analysis"], later["meeting"]["analysis"]
        first_ai_original = copy.deepcopy(first['meeting']['ai_analysis'])
        self.check("synthetic_meeting_dates", a["meeting_date"] == "2026-10-01"
                   and b["meeting_date"] == "2026-10-08")
        self.check("proposal_not_confirmed", any(
            i["type"] == "proposal" and i["status"] == "needs_confirmation" and "90일" in i["quote"]
            for i in a["items"]) and not any(
                i["type"] == "decision" and "90일" in i["quote"] for i in a["items"]))
        actions = [i for i in a["items"] if i["type"] == "action"]
        self.check("assigned_and_unassigned_actions", any(i["assignee"] == "민지" for i in actions)
                   and any(i["assignee"] is None and i["due_date"] is None for i in actions))
        old = next(i for i in a["items"] if i["type"] == "decision" and "30일" in i["quote"])
        new = next(i for i in b["items"] if i["type"] == "decision" and "7일" in i["quote"])
        # A test client explicitly confirms model drafts; this is NOT human review.
        for detail, item in ((first, old), (later, new)):
            item["status"] = "confirmed"
            updated = self.edit(detail, detail["meeting"]["analysis"])
            detail.update(updated)
        link = self.request(self.owner, "POST", f"/meetings/{later['document']['id']}/links",
                            expected=201, json={
                                "target_meeting_id": first["document"]["id"],
                                "source_item_id": new["id"], "target_item_id": old["id"],
                                "relation": "supersedes",
                                "expected_revision": later["document"]["revision"],
                                "expected_version": later["meeting"]["version"],
                                "target_expected_revision": first["document"]["revision"],
                                "target_expected_version": first["meeting"]["version"],
                                **{key: new[key] for key in ("quote", "start_offset", "end_offset")}})
        self.check("explicit_decision_link", bool(link["id"]))
        changed = copy.deepcopy(first["meeting"]["analysis"])
        task = next(i for i in changed["items"] if i["type"] == "action" and i["assignee"] is None)
        task.update(assignee="서연", due_date="2026-10-15", status="doing")
        edited = self.edit(first, changed)
        conflict = self.owner.put('/api/meetings/' + first['document']['id'] + '/analysis',
                                  json={'expected_revision': first['document']['revision'],
                                        'expected_version': first['meeting']['version'],
                                        'analysis': changed})
        self.check('stale_user_edit_rejected', conflict.status_code == 409)
        self.check("edit_preserves_ai_original", edited["meeting"]["provenance"] == "user_edited"
                   and edited["meeting"]["ai_analysis"] == first_ai_original
                   and edited["meeting"]["analysis"] == changed)
        self.ready_meeting_id, self.ready_task_id = first['document']['id'], task['id']
        tasks = self.request(self.owner, "GET", "/tasks", params={"assignee": "서연", "status": "doing"})
        self.check("task_management_saved", any(t["id"] == task["id"] for t in tasks["items"]))
        links = self.request(self.owner, "GET", f"/meetings/{later['document']['id']}/links")
        self.check("task_edit_keeps_decision_history", any(x["id"] == link["id"] for x in links["items"]))
        filtered = self.search("로그", workspace_id=workspace, kind="meeting",
                               date_from="2026-10-08", date_to="2026-10-08")
        self.check("date_filter_before_retrieval", bool(filtered["results"]) and all(
            h["document_id"] == later["document"]["id"] for h in filtered["results"]))
        if learned:
            result = self.request(self.owner, "POST", "/knowledge/search",
                                  json={"query": "log retention", "workspace_id": workspace,
                                        "kind": "meeting", "method": "hybrid", "limit": 5})
            self.check("actual_embedding_hybrid_search", bool(result["results"])
                            and result["embedding_profile"]["id"] == "base")
        # Existing document mutation is the authoritative revision lifecycle.
        self.request(self.owner, "PUT", f"/documents/{later['document']['id']}", json={
            "title": "수정된 후속 회의", "content": "새 원문으로 교체했습니다. lunarwidget",
            "visibility": "private"})
        stale = self.request(self.owner, "GET", f"/meetings/{later['document']['id']}")
        self.check("document_edit_stales_analysis", stale["meeting"]["analysis_status"] == "stale")
        replacement = self.search('lunarwidget')['results']
        self.check('replacement_searchable_by_owner', bool(replacement) and all(
            h['document_id'] == later['document']['id']
            and h['revision'] == stale['document']['revision'] for h in replacement))
        hidden = self.member.get('/api/meetings/' + later['document']['id'])
        self.check('private_meeting_direct_access_hidden', hidden.status_code == 404)
        stale_links = self.request(self.owner, 'GET', f"/meetings/{first['document']['id']}/links")
        self.check('changed_source_invalidates_decision_link',
                   not any(x['id'] == link['id'] for x in stale_links['items']))
        self.check("private_meeting_hidden_from_member", not any(
            h["document_id"] == later["document"]["id"]
            for h in self.search("lunarwidget", client=self.member)["results"]))
        self.request(self.owner, "DELETE", f"/documents/{later['document']['id']}", expected=204)
        gone = self.owner.get('/api/meetings/' + later['document']['id'])
        self.check('deleted_meeting_direct_access_missing', gone.status_code == 404)
        self.check("deleted_meeting_not_searchable", not self.search("lunarwidget")["results"])
        self.check("ordinary_document_preserved", self.request(self.owner, "GET",
                   f"/documents/{guide['id']}")["id"] == guide["id"])

    def verify_ready_deletion(self):
        """Run after optional UI observation, while a real ready task is still visible."""
        before = self.request(self.owner, 'GET', '/tasks')['items']
        self.check('ready_task_visible_before_deletion', any(
            t['meeting_id'] == self.ready_meeting_id and t['id'] == self.ready_task_id
            for t in before))
        self.request(self.owner, 'DELETE', f'/documents/{self.ready_meeting_id}', expected=204)
        after = self.request(self.owner, 'GET', '/tasks')['items']
        self.check('ready_meeting_deletion_removes_tasks', not any(
            t['meeting_id'] == self.ready_meeting_id for t in after))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--learned', action='store_true')
    args = parser.parse_args()
    url = urlparse(args.url)
    if (url.scheme != 'http' or url.hostname != '127.0.0.1' or url.port is None
            or url.username or url.password or url.query or url.fragment
            or url.path not in ('', '/')):
        parser.error('local_service_only')
    if args.output.exists():
        parser.error('preserve_previous_report_choose_new_output')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    run = OperationsVerification(args.url, args.output)
    try:
        run.run(learned=args.learned)
        run.verify_ready_deletion()
        run.report['status'] = 'passed_analysis_lifecycle_only'
    except Exception as exc:  # noqa: BLE001 - preserve safe partial verification evidence
        run.report['status'] = 'failed'
        run.report['failure'] = str(exc) if isinstance(exc, AssertionError) else type(exc).__name__
    finally:
        run.report['completed_at'] = datetime.now(UTC).isoformat()
        run.save()
        run.close()
    print(json.dumps({'status': run.report['status'], 'checks': len(run.report['checks']),
                      'analyses': len(run.report['analyses']), 'answer_calls': 0}))
    raise SystemExit(1 if run.report['status'] == 'failed' else 0)


if __name__ == '__main__':
    main()
