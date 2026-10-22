"""Single-use local service acceptance. CLI has no fixture or policy overrides."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

from doctrail.meeting_analysis_batch import POLICIES
from scripts.serve_meeting_rag_service import ROOT, start_services

CODE = ("scripts/run_meeting_rag_acceptance.py", "tests/test_run_meeting_rag_acceptance.py",
        "web/scripts/run-meeting-rag-acceptance.mjs", "src/doctrail/meeting_service_rag.py",
        "scripts/serve_meeting_service_rag.py", "scripts/serve_meeting_rag_service.py",
        "src/doctrail/meeting_analysis_batch.py")
COUNTS = {"calibration": 6, "validation": 8}
BROWSER_CODES = frozenset({
    "browser_action_failed", "browser_action_timeout", "browser_contract_failed",
    "evidence_write_failed", "browser_close_failed", "page_error", "stopped", "active_timeout",
    "loopback_required", "get_status", "capture_before_login", "duplicate_registration",
    "duplicate_upload", "duplicate_answer", "unregistered_post", "unregistered_mutation",
    "request_guard_failed", "ui_http_failed", "ui_binding_mismatch", "ui_asset_unregistered",
    "registration_failed", "membership_failed", "membership_scope", "source_binding_changed",
    "upload_failed", "document_owner", "document_mismatch", "chunks_mismatch", "chunk_mismatch",
    "analysis_repeated", "analysis_failed", "analysis_identity_failed", "ingestion_incomplete",
    "duplicate_runtime_uuid", "answer_failed", "answer_request_mismatch", "answer_response_invalid",
    "unauthorized_context", "citation_mismatch", "answer_render_mismatch", "citation_render_mismatch",
    "mobile_overflow", "ownership_ack_invalid", "ownership_unconfirmed", "arguments",
})
BROWSER_STAGES = frozenset({"bootstrap", "ownership", "ui_verification", "registration",
    "membership", "upload", "analysis", "access", "answer", "citations", "capture", "cleanup"})


class ExecutionError(Exception):
    """Fixed, nonsemantic failure code."""


def require(condition, code):
    if not condition:
        raise ExecutionError(code)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def save(path, value):
    """Exclusive and durable. A partial record remains evidence of failure."""
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def read_json(path):
    return json.loads(Path(path).read_bytes())


def browser_failure(folder):
    path = folder / "first-failure.json"
    if not path.exists():
        return None
    record = read_json(path)
    require(set(record) == {"code", "stage", "id", "epoch_ms", "elapsed_ms"}
            and record["code"] in BROWSER_CODES and record["stage"] in BROWSER_STAGES
            and (record["id"] is None or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", record["id"]))
            and all(type(record[k]) in (int, float) and record[k] >= 0
                    for k in ("epoch_ms", "elapsed_ms")), "browser_failure_record_invalid")
    return record


def bound(binding, *, parse=False):
    # Only explicit run inputs. Never follow paths found inside a freeze/oracle.
    path = Path(binding["path"]).resolve()
    require(not re.search(r"oracle|selection|semantic|review.notes", str(path), re.IGNORECASE),
            "forbidden_input")
    require(re.fullmatch(r"[0-9a-f]{64}", binding["sha256"]), "invalid_binding")
    data = path.read_bytes()
    require(digest(data) == binding["sha256"], "binding_changed")
    if "bytes" in binding:
        require(len(data) == binding["bytes"], "binding_changed")
    return json.loads(data) if parse else None


def verify_inputs(manifest, phase, run_dir):
    """Narrow manifest v1: plan hash is accepted by a separately bound registration."""
    require(set(manifest) == {"schema_version", "phase", "registration", "plan"}
            and manifest["schema_version"] == 1 and manifest["phase"] == phase, "manifest_schema")
    plan = manifest["plan"]
    require(set(plan) - {"analysis_policy"} == {"questions", "sources", "families", "code", "jar", "ui",
                         "source_freeze", "item_freeze", "ci", "roles", "gate"}, "plan_schema")
    analysis_policy = plan.get("analysis_policy", "single")
    require(analysis_policy in POLICIES, "policy_mismatch")
    registration = bound(manifest["registration"], parse=True)
    require(registration["schema_version"] == 1 and registration["phase"] == phase
            and registration["plan_sha256"] == digest(canonical(plan))
            and Path(registration["run_dir"]).resolve() == run_dir, "registration_mismatch")
    expected_policy = {
        "startup_seconds": 120, "active_seconds": 1500, "cleanup_seconds": 5,
        "answer_seconds": 90, "analyze_seconds": 120, "method": "hybrid_rerank",
        "profile": "base", "limit": 5, "gpu_layers": 28}
    if "analysis_policy" in plan:
        expected_policy["analysis_policy"] = analysis_policy
    require(registration["policy"] == expected_policy, "policy_mismatch")
    for key in ("source_freeze", "item_freeze", "ci", "roles"):
        bound(plan[key])
        require(registration["accepted_bindings"][key] == plan[key]["sha256"],
                "acceptance_binding_mismatch")
    ci = bound(plan["ci"], parse=True)
    require(re.fullmatch(r"[a-f0-9]{40}", ci["commit"])
            and ci["commit"] == registration["commit"]
            and ci["jobs"] == {"backend": "success", "java-service": "success", "web": "success"}
            and ci["code"] == plan["code"], "ci_not_accepted")
    roles = bound(plan["roles"], parse=True)
    executor, judge = roles["executor"], roles["final_judge"]
    require(executor["accepted"] is True and judge["accepted"] is True
            and executor["phase"] == judge["phase"] == phase
            and executor["role_id"] != judge["role_id"]
            and judge["role_id"] not in roles["excluded_final_judges"]
            and judge["model"] and judge["exposure"] is not None
            and registration["executor"] == executor["role_id"]
            and registration["final_judge"] == judge["role_id"], "roles_not_accepted")
    required_code = {ROOT / n for n in CODE}
    require({Path(b["path"]).resolve() for b in plan["code"]}
            >= required_code, "code_binding_missing")
    for binding in [*plan["code"], plan["jar"]]:
        bound(binding)
    require(plan["ui"] and any(b["url"] == "/" for b in plan["ui"]), "ui_binding_missing")
    for asset in plan["ui"]:
        require(asset["url"].startswith("/") and not asset["url"].startswith("//")
                and ".." not in asset["url"] and re.fullmatch(r"[0-9a-f]{64}", asset["sha256"]),
                "ui_binding_invalid")
    questions = bound(plan["questions"], parse=True)
    require(set(questions) == {"schema_version", "phase", "cases"}
            and questions["schema_version"] == 1 and questions["phase"] == phase
            and len(questions["cases"]) == COUNTS[phase], "questions_schema")
    families = plan["families"]
    require(len(families) == 2 and {f["source_kind"] for f in families} == {"public", "synthetic"}
            and len({f["id"] for f in families}) == 2
            and {f["principal"] for f in families} == {"actor1", "actor2"}, "family_schema")
    ids = set()
    for case in questions["cases"]:
        require(set(case) == {"id", "query", "language", "family_id", "source_kind"}
                and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", case["id"])
                and case["id"] not in ids and case["language"] in {"ko", "en"}
                and 0 < len(case["query"]) <= 500 and case["query"] == case["query"].strip()
                and any(f["id"] == case["family_id"] and f["source_kind"] == case["source_kind"]
                        for f in families), "questions_schema")
        ids.add(case["id"])
    sources = plan["sources"]
    require(len(sources) == 6 and len({s["source_id"] for s in sources}) == 6, "sources_schema")
    for family in families:
        members = [s for s in sources if s["family_id"] == family["id"]]
        require(sorted(s["kind"] for s in members) == ["document", "meeting", "meeting"]
                and any(s["visibility"] == "private" for s in members), "sources_schema")
    for source in sources:
        require(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", source["source_id"])
                and any(f["id"] == source["family_id"] for f in families)
                and isinstance(source["title"], str) and source["title"]
                and source["visibility"] in {"private", "workspace"} and source["revision"]
                and source["prepared_document_id"] and source["chunks"], "sources_schema")
        bound(source["raw"])
        require(Path(source["raw"]["path"]).suffix.lower() in {".md", ".txt", ".pdf"},
                "source_format")
        require(re.fullmatch(r"[a-f0-9]{64}", source["content_sha256"]), "source_hash")
        for chunk in source["chunks"]:
            require(set(chunk) == {"id", "ordinal", "page", "start_offset", "end_offset", "sha256"}
                    and chunk["end_offset"] > chunk["start_offset"] >= 0
                    and re.fullmatch(r"[a-f0-9]{64}", chunk["sha256"]), "chunk_schema")
    if phase == "validation":
        require(plan["gate"] is not None, "calibration_gate_missing")
        gate = bound(plan["gate"], parse=True)
        require(registration["gate_sha256"] == plan["gate"]["sha256"]
                and gate.get("analysis_policy", "single") in POLICIES
                and gate.get("analysis_policy", "single") == analysis_policy
                and gate["phase"] == "calibration" and gate["answers_total"] == 6
                and gate["answers_passed"] == 6 and gate["judgment_locked"] is True
                and gate["operational_accepted"] is True and gate["cleanup_accepted"] is True
                and gate["code"] == plan["code"] and gate["judge_lock_sha256"]
                and gate["run_receipt_sha256"], "calibration_gate_rejected")
    else:
        require(plan["gate"] is None, "unexpected_gate")
    return questions


class Evidence:
    """One phase, one current UI attempt. No public raw-output channel."""

    def __init__(self, folder, questions, sources, clock=time.monotonic):
        self.folder, self.clock = folder, clock
        self.questions = {c["id"]: c for c in questions["cases"]}
        self.sources = {s["source_id"]: s for s in sources}
        self.lock = threading.Lock()
        self.starts, self.native, self.counts = {}, {}, {}
        self.failure = None
        self.sequence = 0
        self.deadline = 0
        self.requests = {}
        self.responses = {}
        self.completed_native = {}

    def __call__(self, operation, event, value):
        with self.lock:
            try:
                marker = read_json(self.folder / "current.json")
                key = marker["id"]
                require(operation == marker["operation"], "observer_operation")
                require(self.clock() < self.deadline, "active_timeout")
                require(self.failure is None, "prior_evidence_failure")
                if event == "started":
                    require((operation, key) not in self.starts, "duplicate_worker_request")
                    self.starts[operation, key] = True
                    if operation == "answer":
                        require(key in self.questions
                                and value["request"]["query"] == self.questions[key]["query"]
                                and type(value["budget_ms"]) is int
                                and 1 <= value["budget_ms"] <= 90000, "answer_request_mismatch")
                        self.requests[key] = value["request"]
                    else:
                        require(key in self.sources and self.sources[key]["kind"] == "meeting"
                                and digest(value["content"].encode()) ==
                                self.sources[key]["content_sha256"], "analysis_request_mismatch")
                require((operation, key) in self.starts, "observer_without_request")
                is_native = (operation == "answer" and event == "native_post_started") or (
                    operation == "analyze" and event == "transport_started"
                    and value["path"] in {"/completion", "/v1/chat/completions"})
                if is_native:
                    count = self.native.get((operation, key), 0) + 1
                    require(operation != "answer" or count <= 1, "duplicate_native_answer")
                    self.native[operation, key] = count
                    self.counts[operation + ":native_attempts"] = (
                        self.counts.get(operation + ":native_attempts", 0) + 1)
                if event == "classification_units":
                    self.counts["analyze:classification_units"] = (
                        self.counts.get("analyze:classification_units", 0) + value)
                if operation == "analyze" and event == "transport_response":
                    path = value["path"]
                    category = "native_responses" if path in {"/completion", "/v1/chat/completions"} else (
                        "tokenize_responses" if path == "/tokenize" else "template_responses")
                    self.counts["analyze:" + category] = self.counts.get("analyze:" + category, 0) + 1
                if (operation == "answer" and event == "native_response") or (
                        operation == "analyze" and event == "transport_response"
                        and value["path"] in {"/completion", "/v1/chat/completions"}):
                    self.completed_native[operation, key] = self.completed_native.get((operation, key), 0) + 1
                event_key = operation + ":" + event
                if event == "classification_units":
                    event_key += "_events"
                self.counts[event_key] = self.counts.get(event_key, 0) + 1
                if operation == "answer" and event == "worker_response":
                    self.responses[key] = value
                save(self.folder / "raw" / f"{self.sequence:06d}.json",
                     {"operation": operation, "id": key, "event": event,
                      "monotonic": self.clock(), "value": value})
                self.sequence += 1
            except Exception as error:  # noqa: BLE001 - retain first sink failure independently
                if self.failure is None:
                    self.failure = str(error) if isinstance(error, ExecutionError) else "evidence_write_failed"
                raise ExecutionError(self.failure) from None


def reconcile(browser, evidence, questions):
    require(browser["status"] == "completed" and browser["analysis_count"] == 4
            and browser["answer_posts"] == len(questions["cases"]), "browser_incomplete")
    require(sum(op == "analyze" for op, _ in evidence.starts) == 4
            and evidence.counts.get("analyze:result") == 4
            and all(evidence.native.get(("analyze", key), 0) > 0
                    and evidence.completed_native.get(("analyze", key), 0) ==
                    evidence.native.get(("analyze", key), 0)
                    for op, key in evidence.starts if op == "analyze")
            and evidence.failure is None, "analysis_observation_missing")
    require([c["id"] for c in browser["cases"]] == [c["id"] for c in questions["cases"]],
            "case_order_mismatch")
    packet = []
    for item, case in zip(browser["cases"], questions["cases"], strict=True):
        response = item["response"]
        results = response["results"]
        require(len(results) <= 5, "context_count")
        if results:
            require(case["id"] in evidence.responses
                    and evidence.native.get(("answer", case["id"])) == 1
                    and evidence.completed_native.get(("answer", case["id"])) == 1,
                    "native_proof_missing")
            expected = [{k: row.get(k) for k in ("document_id", "revision", "chunk_id", "title",
                        "meeting_date", "page", "start_offset", "end_offset", "text")} for row in results]
            require(evidence.requests[case["id"]]["contexts"] == expected, "selected_context_mismatch")
            worker = evidence.responses[case["id"]]
            require(worker["status"] == response["status"]
                    and worker.get("reason") == response.get("reason")
                    and worker["model"] == response["model"]
                    and worker["revision"] == response["model_revision"], "worker_response_mismatch")
            projected = [{"text": c["text"], "citations": [
                {k: cite[k] for k in ("chunk_id", "quote", "start_offset", "end_offset")}
                for cite in c["citations"]]} for c in response["claims"]]
            require(projected == worker["claims"], "worker_claims_mismatch")
        else:
            require(case["id"] not in evidence.requests and response["reason"] == "no_evidence",
                    "empty_context_mismatch")
        claims = []
        require(item.get("citations_opened", 0) == sum(len(c["citations"]) for c in response["claims"]),
                "citation_open_incomplete")
        for claim in response["claims"]:
            citations = []
            for citation in claim["citations"]:
                source_id = browser["document_sources"][citation["document_id"]]
                citations.append({k: citation[k] for k in ("quote", "start_offset", "end_offset")} |
                                 {"source_id": source_id,
                                  "source_revision": browser["mapping"][source_id]["source_revision"]})
            claims.append({"text": claim["text"], "citations": citations})
        packet.append({"id": case["id"], "query": case["query"], "status": response["status"],
                       "reason": response.get("reason"), "claims": claims})
    return {"schema_version": 1, "cases": packet}


class BrowserChild:
    def __init__(self, config, folder):
        node = shutil.which("node")
        require(node is not None, "node_missing")
        self.folder = folder
        self.process = subprocess.Popen(
            [node, str(ROOT / CODE[2]), "--config", str(config)],
            cwd=ROOT / "web", stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        import psutil
        self.chromium = None
        self.descendants = {}
        self.ownership_confirmed = False
        self.active_deadline = None
        self.clock = time.monotonic
        self.node = None
        try:
            self.node = psutil.Process(self.process.pid)
            self.node_created = self.node.create_time()
        except psutil.NoSuchProcess:
            self.node_created = None

    def _live_node(self):
        import psutil
        try:
            return (self.node is not None and self.node.is_running()
                    and self.node.create_time() == self.node_created and self.process.poll() is None)
        except psutil.NoSuchProcess:
            return False

    def _remember(self, process):
        import psutil
        try:
            self.descendants[process.pid, process.create_time()] = process
            children = process.children(recursive=True)
        except psutil.NoSuchProcess:
            return  # Keep earlier proven identities even if this process just exited.
        for child in children:
            try:
                self.descendants[child.pid, child.create_time()] = child
            except psutil.NoSuchProcess:
                continue

    def poll(self):
        import psutil
        # Only live lineage plus process creation time grants ownership.
        owner = self.folder / "chromium.json"
        live = self._live_node()
        if live:
            try:
                children = self.node.children(recursive=True)
            except psutil.NoSuchProcess:
                children = []
                live = False
            for process in children:
                self._remember(process)
        if not self.ownership_confirmed and owner.exists():
            record = read_json(owner)
            require(record["node_pid"] == self.process.pid, "browser_owner_mismatch")
            candidates = [p for (pid, _), p in self.descendants.items() if pid == record["pid"]]
            try:
                require(live and len(candidates) == 1 and candidates[0].is_running(),
                        "browser_owner_unconfirmed")
                process = candidates[0]
                require(any(p.pid == self.process.pid and p.create_time() == self.node_created
                            for p in process.parents()), "browser_owner_mismatch")
                self._remember(process)
                acknowledgement = {
                    "node_pid": self.process.pid, "node_create_time": self.node_created,
                    "chromium_pid": process.pid, "chromium_create_time": process.create_time()}
            except psutil.NoSuchProcess:
                raise ExecutionError("browser_owner_unconfirmed") from None
            if self.active_deadline is not None:
                acknowledgement.update(active_budget_ms=max(
                    0, int((self.active_deadline - self.clock()) * 1000)),
                    budget_epoch_ms=int(time.time() * 1000))
            temporary = self.folder / "chromium-adopted.tmp"
            save(temporary, acknowledgement)
            temporary.replace(self.folder / "chromium-adopted.json")
            self.chromium, self.ownership_confirmed = process, True
        if not live and not self.ownership_confirmed:
            raise ExecutionError("browser_owner_unconfirmed")
        return self.process.poll()

    def stop(self):
        stop = self.folder / "stop.json"
        if not stop.exists():
            save(stop, {"stop": True})

    def cleanup_elapsed(self):
        path = self.folder / "browser-cleanup-started.json"
        if not path.exists():
            return 0
        return max(0, time.time() - read_json(path)["epoch_ms"] / 1000)

    def closing(self):
        return (self.folder / "browser-cleanup-started.json").exists()

    def finish(self, deadline, clock):
        import psutil
        errors = []
        if not self.ownership_confirmed:
            errors.append("browser_owner_unconfirmed")
        # Keep verified descendants even if Node exits between observations.
        try:
            if self._live_node():
                for process in self.node.children(recursive=True):
                    self._remember(process)
        except psutil.NoSuchProcess:
            pass
        except Exception:  # noqa: BLE001 - continue cleaning already proven identities
            errors.append("browser_descendant_observation_failed")
        for process in list(self.descendants.values()):
            try:
                if process.is_running():
                    self._remember(process)
            except psutil.NoSuchProcess:
                pass
            except Exception:  # noqa: BLE001
                errors.append("browser_descendant_observation_failed")
        try:
            self.process.wait(timeout=max(0, deadline - clock()))
        except subprocess.TimeoutExpired:
            errors.append("browser_forced_stop")
            try:
                self.process.kill()
            except Exception:  # noqa: BLE001
                errors.append("node_stop_failed")
        except Exception:  # noqa: BLE001
            errors.append("node_wait_failed")
        # Never reopen an unverified registry PID or kill a reused process identity.
        for (_, created), process in reversed(list(self.descendants.items())):
            try:
                if process.is_running() and process.create_time() == created:
                    process.kill()
                    errors.append("browser_descendant_forced_stop")
                    process.wait(timeout=max(0, deadline - clock()))
            except psutil.NoSuchProcess:
                pass
            except psutil.TimeoutExpired:
                errors.append("browser_descendant_survived")
            except Exception:  # noqa: BLE001
                errors.append("browser_descendant_stop_failed")
        try:
            self.process.wait(timeout=max(0, deadline - clock()))
        except subprocess.TimeoutExpired:
            errors.append("node_survived")
        except Exception:  # noqa: BLE001
            errors.append("node_wait_failed")
        for (_, created), process in self.descendants.items():
            try:
                if process.is_running() and process.create_time() == created:
                    errors.append("browser_descendant_survived")
            except psutil.NoSuchProcess:
                pass
            except Exception:  # noqa: BLE001
                errors.append("browser_descendant_observation_failed")
        node_returncode = self.process.poll()
        save(self.folder / "owned-exit.json", {
            "ownership_confirmed": self.ownership_confirmed, "errors": errors,
            "node_exited": node_returncode is not None, "node_returncode": node_returncode,
            "owned": [{"pid": pid, "create_time": created}
                      for pid, created in self.descendants]})
        closed = self.folder / "browser-closed.json"
        return (not errors and node_returncode is not None and closed.exists()
                and read_json(closed).get("closed") is True)


def execute(manifest_path, phase, run_dir, *, service_factory=start_services,
            browser_factory=BrowserChild, clock=time.monotonic, sleep=time.sleep):
    started = clock()
    run_dir = Path(run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=False)  # Failure consumes this pinned directory forever.
    save(run_dir / "reservation.json", {"phase": phase, "consumed": True})
    raw = run_dir / "raw"
    raw.mkdir()
    browser_folder = run_dir / "browser"
    browser_folder.mkdir()
    metrics, summary = {}, {"phase": phase, "status": "failed", "hard_preemption_proven": False,
                            "judge_packet_eligible": False}
    service = child = context = evidence = None
    entered = False
    manifest = questions = browser = packet = None
    cleanup_started = None
    try:
        manifest_bytes = Path(manifest_path).read_bytes()
        manifest = json.loads(manifest_bytes)
        save(run_dir / "manifest.json", manifest)
        questions = verify_inputs(manifest, phase, run_dir)
        summary["manifest_sha256"] = digest(manifest_bytes)
        plan = manifest["plan"]
        summary["analysis_policy"] = plan.get("analysis_policy", "single")
        save(run_dir / "cases-initial.json",
             [{"id": c["id"], "status": "unexecuted"} for c in questions["cases"]])
        require(clock() - started < 120, "startup_timeout")
        evidence = Evidence(run_dir, questions, plan["sources"], clock)
        context = service_factory(jar=Path(plan["jar"]["path"]),
            jar_sha256=plan["jar"]["sha256"], database=run_dir / "isolated.sqlite3",
            log_dir=run_dir / "services", metrics=metrics, observer=evidence,
            analysis_policy=summary["analysis_policy"])
        service = context.__enter__()
        entered = True
        ready = clock()
        require(ready - started < 120, "startup_timeout")
        evidence.deadline = ready + 1500
        save(run_dir / "owned-services.json", {
            "java": {"pid": service.java.pid, "argv": service.java.args},
            "retrieval": {"pid": service.retrieval.pid, "argv": service.retrieval.args},
            "native": metrics.get("native_adapter", {}).get("native", {})})
        browser_sources = [{**s, "raw": {**s["raw"],
                            "path": str(Path(s["raw"]["path"]).resolve())}} for s in plan["sources"]]
        remaining = evidence.deadline - clock()
        require(remaining > 0, "active_timeout")
        save(run_dir / "browser-config.json", {"base_url": service.java_url,
            "run_dir": str(run_dir), "active_budget_ms": int(remaining * 1000),
            "budget_epoch_ms": int(time.time() * 1000),
            "questions": questions, "sources": browser_sources, "families": plan["families"],
            "ui": plan["ui"]})
        require(clock() < evidence.deadline, "active_timeout")
        child = browser_factory(run_dir / "browser-config.json", browser_folder)
        child.active_deadline, child.clock = evidence.deadline, clock
        while child.poll() is None:
            first_failure = browser_failure(browser_folder)
            if first_failure:
                summary["browser_failure"] = first_failure
                raise ExecutionError(first_failure["code"])
            require(clock() < evidence.deadline, "active_timeout")
            require(evidence.failure is None, "observer_failed")
            service.alive()
            if child.closing():
                break
            sleep(min(0.05, max(0, evidence.deadline - clock())))
        first_failure = browser_failure(browser_folder)
        if first_failure:
            summary["browser_failure"] = first_failure
            raise ExecutionError(first_failure["code"])
        require(clock() < evidence.deadline and child.process.returncode in (None, 0),
                "browser_failed")
        browser = read_json(browser_folder / "result.json")
        packet = reconcile(browser, evidence, questions)
        require(clock() < evidence.deadline, "active_timeout")
        summary["status"] = "mechanical_completed_judgment_pending"
        summary["active_seconds"] = clock() - ready
    except BaseException as error:  # noqa: BLE001 - raw input/process errors stay out of summary
        summary["failure"] = str(error) if isinstance(error, ExecutionError) else "execution_failed"
    finally:
        cleanup_started = clock()
        cleanup_ok = True
        prior_browser = 0
        if child is not None:
            try:
                prior_browser = child.cleanup_elapsed()
                child.stop()
            except Exception:  # noqa: BLE001
                cleanup_ok = False
        if service is not None:
            try:
                cleanup_ok = service.shutdown() and cleanup_ok
            except Exception:  # noqa: BLE001
                cleanup_ok = False
        if child is not None:
            try:
                prior_native = metrics.get("cleanup", {}).get("prior_native_cleanup_seconds", 0)
                browser_deadline = cleanup_started + max(0, 5 - prior_browser - (
                    prior_native if prior_native is not None else 5))
                cleanup_ok = child.finish(browser_deadline, clock) and cleanup_ok
            except Exception:  # noqa: BLE001
                cleanup_ok = False
        if entered:
            try:
                context.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                cleanup_ok = False
        if child is not None:
            summary["node_returncode"] = child.process.returncode
            if child.process.returncode != 0:
                summary["status"] = "failed"
                summary.setdefault("failure", "browser_failed")
        prior = metrics.get("cleanup", {}).get("prior_native_cleanup_seconds", 0)
        # Failed __enter__ may have already performed the entire launcher cleanup.
        if context is not None and not entered:
            prior = metrics.get("cleanup", {}).get("elapsed_seconds")
            cleanup_ok = metrics.get("cleanup", {}).get("accepted") is True and cleanup_ok
        elapsed = None if prior is None else prior + prior_browser + clock() - cleanup_started
        cleanup_ok = cleanup_ok and elapsed is not None and elapsed <= 5
        summary.update(cleanup_accepted=cleanup_ok, cleanup_seconds=elapsed,
                       prior_browser_cleanup_seconds=prior_browser,
                       observer_failure=evidence.failure if evidence else None,
                       counts=evidence.counts if evidence else {})
        # Node may have persisted its first failure while shutdown was in progress.
        try:
            first_failure = browser_failure(browser_folder)
            if first_failure:
                summary.update(status="failed", browser_failure=first_failure)
                if summary.get("failure") in (None, "browser_failed", "execution_failed"):
                    summary["failure"] = first_failure["code"]
        except Exception:  # noqa: BLE001 - never copy invalid/raw failure text
            summary.update(status="failed", browser_failure_record_invalid=True)
        if manifest is not None and questions is not None:
            try:
                verify_inputs(manifest, phase, run_dir)
                if browser is not None and cleanup_ok:
                    database = run_dir / "isolated.sqlite3"
                    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
                        for source in manifest["plan"]["sources"]:
                            document = browser["mapping"][source["source_id"]]["document"]
                            row = connection.execute("SELECT source FROM documents WHERE id=?",
                                                     (document["id"],)).fetchone()
                            require(row is not None and digest(row[0]) == source["raw"]["sha256"],
                                    "stored_original_mismatch")
            except Exception:  # noqa: BLE001
                summary["binding_check_failed"] = True
                cleanup_ok = False
        if not cleanup_ok:
            summary["status"] = "failed"
        if questions is not None:
            attempts = [read_json(p) for p in browser_folder.glob("attempt-*.json")]
            save(run_dir / "case-states.json", [{
                "id": case["id"], "status": "completed" if (
                    browser_folder / f"case-{case['id']}-completed.json").exists() else (
                    "consumed_incomplete" if any(a["operation"] == "answer" and a["id"] == case["id"]
                                                for a in attempts) else "unexecuted"),
                "response_available": (browser_folder / f"answer-{case['id']}-response.json").exists()
            } for case in questions["cases"]])
        summary["wall_seconds"] = clock() - started
        if summary["wall_seconds"] > 1625:
            summary["status"] = "failed"
            summary["window_exceeded"] = True
        # Raw artifacts never appear in stdout or the safe summary.
        bindings = []
        for path in sorted(run_dir.rglob("*")):
            if path.is_file() and path.suffix not in {".sqlite3"} and not path.name.endswith(("-wal", "-shm")):
                bindings.append({"path": path.relative_to(run_dir).as_posix(),
                                 "bytes": path.stat().st_size, "sha256": digest(path.read_bytes())})
        database = run_dir / "isolated.sqlite3"
        if cleanup_ok and database.exists():
            bindings.append({"path": database.name, "bytes": database.stat().st_size,
                             "sha256": digest(database.read_bytes())})
        save(run_dir / "artifact-index.json", bindings)
        summary["wall_seconds"] = clock() - started
        if summary["wall_seconds"] > 1625:
            summary.update(status="failed", window_exceeded=True)
        if summary["status"] == "mechanical_completed_judgment_pending" and packet is not None:
            # Publish only after final task, cleanup and binding checks. The existing index
            # remains immutable; this late packet has its own exact binding in the receipt.
            try:
                packet_path = run_dir / "judge-answer-packet.json"
                save(packet_path, packet)
                packet_bytes = packet_path.read_bytes()
                summary["judge_packet"] = {"path": packet_path.name, "bytes": len(packet_bytes),
                                           "sha256": digest(packet_bytes)}
            except Exception:  # noqa: BLE001 - preserve any partial original, never retry
                summary["status"] = "failed"
                summary.setdefault("failure", "evidence_write_failed")
            summary["wall_seconds"] = clock() - started
            if summary["wall_seconds"] > 1625:
                summary.update(status="failed", window_exceeded=True)
            summary["judge_packet_eligible"] = (
                summary["status"] == "mechanical_completed_judgment_pending")
        save(run_dir / "receipt.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-real-service-rag-execution", action="store_true", required=True)
    parser.add_argument("--phase", choices=COUNTS, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = execute(args.manifest, args.phase, args.run_dir)
    except Exception:  # noqa: BLE001
        parser.exit(1, "execution_reservation_or_evidence_failed\n")
    print(json.dumps({"status": result["status"], "phase": args.phase}))
    return 0 if result["status"] == "mechanical_completed_judgment_pending" else 1


if __name__ == "__main__":
    raise SystemExit(main())
