"""Exercise real local Java + Qwen meeting flows on licensed/synthetic fixtures.

This is a developmental operational check, not a held-out accuracy benchmark.
Reports preserve actual outputs for separate semantic review. No paid API calls.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import secrets
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/meetings"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Verification:
    def __init__(self, url: str, output: Path):
        self.url, self.output = url, output
        self.report = {"schema_version": 1, "kind": "meeting_development_operations",
                       "started_at": datetime.now(UTC).isoformat(),
                       "git_head": subprocess.check_output(
                           ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                       "working_tree_dirty": bool(subprocess.check_output(
                           ["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()),
                       "human_review_count": 0, "semantic_review": "pending",
                       "external_deployment": False, "paid_service_calls": 0,
                       "checks": [], "analyses": [], "answers": [],
                       "source_hashes": {p.relative_to(ROOT).as_posix(): sha(p)
                                         for pattern in ("src/doctrail/meeting_*.py",
                                                         "server/src/main/java/io/doctrail/*.java",
                                                         "scripts/verify_meeting_service.py")
                                         for p in ROOT.glob(pattern)},
                       "fixtures": {p.relative_to(ROOT).as_posix(): sha(p)
                                    for p in FIXTURES.rglob("*") if p.is_file()}}
        self.owner = httpx.Client(base_url=url, timeout=180, trust_env=False)
        self.member = httpx.Client(base_url=url, timeout=180, trust_env=False)

    def save(self):
        self.output.write_text(json.dumps(self.report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8", newline="\n")

    def check(self, name, condition, **details):
        self.report["checks"].append({"name": name, "passed": bool(condition), **details})
        self.save()
        if not condition:
            raise AssertionError(name)

    @staticmethod
    def request(client, method, path, *, expected=200, **kwargs):
        response = client.request(method, "/api" + path, **kwargs)
        if response.status_code != expected:
            try:
                code = response.json().get("detail", response.json().get("error", "unknown"))
            except (ValueError, AttributeError):
                code = "non_json"
            raise AssertionError(f"http_{response.status_code}_{code}")
        return response.json() if response.content else None

    def register(self, client, label):
        email = f"meeting-{label}-{secrets.token_hex(6)}@example.test"
        result = self.request(client, "POST", "/auth/register", expected=201,
                              json={"email": email, "password": secrets.token_urlsafe(24),
                                    "name": label, "workspace_name": label})
        return result["workspaces"][0]["id"], email

    def upload_document(self, workspace, file, title):
        return self.request(self.owner, "POST", f"/workspaces/{workspace}/documents",
                            expected=201, files={"file": (file.name, file.read_bytes(), "text/plain")},
                            data={"title": title, "visibility": "workspace"})

    def meeting(self, workspace, file, title, visibility="workspace"):
        started = time.perf_counter()
        result = self.request(self.owner, "POST", f"/workspaces/{workspace}/meetings/text",
                              expected=201, json={"title": title,
                                                 "content": file.read_text(encoding="utf-8"),
                                                 "visibility": visibility})
        identity = result["document"]["id"]
        deadline = time.monotonic() + 160
        while result["meeting"]["analysis_status"] in {"queued", "running"}:
            if time.monotonic() >= deadline:
                raise AssertionError("analysis_poll_timeout")
            time.sleep(.25)
            result = self.request(self.owner, "GET", f"/meetings/{identity}")
        self.report["analyses"].append({"fixture": file.relative_to(ROOT).as_posix(),
                                        "document_id": identity,
                                        "java_roundtrip_ms": round(
                                            (time.perf_counter() - started) * 1000, 3),
                                        "meeting": result["meeting"]})
        self.save()
        self.check("automatic_analysis_" + file.stem,
                   result["meeting"]["analysis_status"] == "ready")
        self.verify_spans(result)
        return result

    def verify_spans(self, result):
        source = result["document"]["content"]
        analysis = result["meeting"]["ai_analysis"]
        spans = analysis["summary_evidence"] + analysis["metadata_evidence"] + analysis["items"]
        self.check("analysis_source_spans", bool(analysis["summary"]) and bool(spans)
                   and all(source[s["start_offset"]:s["end_offset"]] == s["quote"]
                           for s in spans))

    def search(self, query, client=None, **filters):
        return self.request(client or self.owner, "POST", "/knowledge/search",
                            json={"query": query, "method": "bm25", "limit": 10, **filters})

    def answer(self, query, **filters):
        started = time.perf_counter()
        try:
            result = self.request(self.owner, "POST", "/knowledge/answer",
                                  json={"query": query, "method": "bm25", "limit": 5, **filters})
        except AssertionError as exc:
            self.report["answers"].append({"query": query, "filters": filters,
                                           "failure": str(exc), "java_roundtrip_ms": round(
                                               (time.perf_counter() - started) * 1000, 3)})
            self.save()
            raise
        self.report["answers"].append({"query": query, "filters": filters, "response": result,
                                       "java_roundtrip_ms": round(
                                           (time.perf_counter() - started) * 1000, 3)})
        self.save()
        for claim in result["claims"]:
            for citation in claim["citations"]:
                document = self.request(self.owner, "GET", "/documents/" + citation["document_id"])
                self.check("answer_current_source_citation",
                           document["revision"] == citation["revision"] and
                           document["content"][citation["start_offset"]:citation["end_offset"]]
                           == citation["quote"])
        return result

    def edit(self, detail, analysis):
        return self.request(self.owner, "PUT", f"/meetings/{detail['document']['id']}/analysis",
                            json={"expected_revision": detail["document"]["revision"],
                                  "expected_version": detail["meeting"]["version"],
                                  "analysis": analysis})

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
        public_answer = self.answer("What does the host guide say about the agenda link?",
                                    workspace_id=workspace, kind="document")
        self.check("real_document_answer_generated", public_answer["status"] == "answered")
        cross = self.answer("What was reported about JupyterLab 4.4 in February and June?",
                            workspace_id=workspace, kind="meeting")
        self.check("multiple_meetings_cited", cross["status"] == "answered" and len({
            c["document_id"] for claim in cross["claims"] for c in claim["citations"]}) >= 2)
        absent = self.answer("누가 회사 비밀 프로젝트의 예산을 승인했나요?", workspace_id=workspace)
        self.check("missing_evidence_abstention", absent["status"] == "abstained")
        missing = self.answer("What is the Jupyter community meeting catering budget?",
                              workspace_id=workspace, kind="meeting")
        self.check("model_abstains_with_irrelevant_candidates",
                   missing["status"] == "abstained" and missing["model_called"])
        self.check("outsider_search_empty", not self.search("Jupyter", client=self.member)["results"])
        self.request(self.owner, "POST", f"/workspaces/{workspace}/members", expected=201,
                     json={"email": member_email})
        first = self.meeting(workspace, FIXTURES / "synthetic-release-planning.md", "출시 회의")
        later = self.meeting(workspace, FIXTURES / "synthetic-release-followup.md", "후속 회의")
        self.upload_document(workspace, FIXTURES / "synthetic-runbook.md", "Search operations")
        self.answer("로그 보관 기간은 언제 어떻게 변경됐고 원문 질문을 운영 로그에 남겨도 되나요?",
                    workspace_id=workspace, method="hybrid" if learned else "bm25")
        a, b = first["meeting"]["analysis"], later["meeting"]["analysis"]
        self.check("synthetic_meeting_dates", a["meeting_date"] == "2026-10-01"
                   and b["meeting_date"] == "2026-10-08")
        self.check("proposal_not_confirmed", not any(
            i["type"] == "decision" and i["status"] == "confirmed" and "90일" in i["quote"]
            for i in a["items"]))
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
        self.check("edit_preserves_ai_original", edited["meeting"]["provenance"] == "user_edited"
                   and edited["meeting"]["ai_analysis"] != edited["meeting"]["analysis"])
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
        self.check("private_meeting_hidden_from_member", not any(
            h["document_id"] == later["document"]["id"]
            for h in self.search("lunarwidget", client=self.member)["results"]))
        self.request(self.owner, "DELETE", f"/documents/{later['document']['id']}", expected=204)
        self.check("deleted_meeting_not_searchable", not self.search("lunarwidget")["results"])
        self.check("ordinary_document_preserved", self.request(self.owner, "GET",
                   f"/documents/{guide['id']}")["id"] == guide["id"])

    def close(self):
        self.owner.close()
        self.member.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Already running isolated local service URL")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--learned", action="store_true")
    args = parser.parse_args()
    url = urlparse(args.url)
    if (url.scheme != "http" or url.hostname != "127.0.0.1" or url.port is None
            or url.username or url.password or url.query or url.fragment
            or url.path not in ("", "/")):
        parser.error("local_service_only")
    if args.output.exists():
        parser.error("preserve_previous_report_choose_new_output")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    run = Verification(args.url, args.output)
    failed = False
    try:
        run.run(learned=args.learned)
        run.report["status"] = "passed"
    except Exception as exc:  # noqa: BLE001 - preserve partial evidence, avoid raw HTTP payloads
        failed = True
        run.report["status"] = "failed"
        run.report["failure"] = str(exc) if isinstance(exc, AssertionError) else type(exc).__name__
    finally:
        run.report["completed_at"] = datetime.now(UTC).isoformat()
        run.save()
        run.close()
    print(json.dumps({"status": run.report["status"], "checks": len(run.report["checks"]),
                      "analyses": len(run.report["analyses"]), "answers": len(run.report["answers"])}))
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
