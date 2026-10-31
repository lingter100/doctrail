"""Two fixed OPEN development cases; exact token counts, never generation.

Actual execution must be dispatched by the existing fresh serial process gate.
Import and fake tests do not inspect weights or launch a native executable.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from doctrail.meeting_contract import grounded_answer_refs, meeting_units
from doctrail.meeting_gguf import GGUFGenerator
from doctrail.meeting_grounded_summary import source_payload
from scripts.probe_meeting_local_candidate import (
    COMPACT_WIRE,
    QA_COVERAGE_CONTROL,
    RSS6_RESOURCES,
    make_resource_guard,
    qa_request_messages,
    source_wire_messages,
)
from tools.free_qa import runner as r
from tools.free_qa.adapter import validate_props
from tools.free_qa.policy import canonical, exact, need, parse, sha

PREFIX = ".local/meeting-free-qa-representation-"
MANIFEST = PREFIX + "development-v1/draft-cases-v1/DRAFT-MANIFEST.json"
PINS = {
    MANIFEST: "10aa9541c23e3257d1b92081a461e07348482ccea005604799ac942de18c4b9e",
    PREFIX + "token-budget-design-v1/DESIGN.md":
        "9ef2de4c4945f9271dd12484d5175ec241031a2f568a6b11082bd0673bb3cb8b",
    PREFIX + "adequacy-review-v1/RESULT.json":
        "d0d8879f360b99345de07fb48d594737539f0ef9d86d7cc5c9095e7118b0f425",
    PREFIX + "adequacy-review-v1/PARENT-ACCEPTANCE.json":
        "1467c43298cdd1e8afda439a1578c20db8dc148e578b02134e54514ac4f130e1",
}
BASELINE = "ministral3-3b-q5km"
BINDING = "0bf6ae50a13b45f14e166aeb425657f0e76d42359369ce952906666d6be44a9a"
RUNTIME = "903c8dfe33072043922e42622a407047481c5b1f3a6e89f527a7392d8c3dcec2"
LIMITS = {"startup_seconds": 120, "active_seconds": 60, "cleanup_seconds": 5,
          "whole_seconds": 185, "input_tokens": 4096, "reference_content_tokens": 256,
          "eog_allowance": 1, "application_requests": 7, "completions": 0}
SEQUENCE = (("GET", "/props"), *(("POST", path) for path in
    ("/apply-template", "/tokenize", "/tokenize") * 2))


def wire(value):
    """Insertion-ordered UTF-8 JSON; no newline or hash-canonical key sorting."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def reference_wire(value):
    exact(value, "status claims", "reference_schema")
    need(value["status"] in ("answered", "abstained") and isinstance(value["claims"], list),
         "reference_schema")
    claims = []
    for claim in value["claims"]:
        exact(claim, "text evidence", "reference_claim")
        need(isinstance(claim["text"], str) and claim["text"]
             and isinstance(claim["evidence"], list) and claim["evidence"]
             and all(type(n) is int and n >= 0 for n in claim["evidence"]), "reference_claim")
        claims.append({"text": claim["text"], "evidence": claim["evidence"]})
    need(bool(claims) == (value["status"] == "answered"), "reference_status")
    return wire({"status": value["status"], "claims": claims})


def prepare_input(data, sidecar, reference):
    """Rebuild document-local units; existing prepare_case checks every sidecar row."""
    units = [{"quote": unit["quote"],
              "start_offset": document["start_offset"] + unit["start_offset"],
              "end_offset": document["start_offset"] + unit["end_offset"]}
             for document in data["documents"] for unit in meeting_units(document["content"])]
    source = source_payload(data["title"], data["bundle"], units)
    messages = source_wire_messages(
        qa_request_messages(source, data["question"], QA_COVERAGE_CONTROL),
        source, data["bundle"], units, COMPACT_WIRE)
    row = {"id": data["id"], "content_sha256": sha(data["bundle"].encode()),
           "question_sha256": sha(data["question"].encode()),
           "messages_sha256": sha(canonical(messages))}
    checked, mapping = r.prepare_case(row, data, sidecar)
    content = reference_wire(reference)
    grounded_answer_refs(content.decode("utf-8"), mapping)
    return {"id": data["id"], "messages": checked, "reference": content.decode("utf-8")}


def load_inputs(root):
    bindings = []

    def read(name, expected, size=None):
        path = r.bound_path(name, root)
        raw = r.assets.small_bytes(path, 8 * 1024**2)
        need(sha(raw) == expected and (size is None or len(raw) == size), "fixed_input_changed")
        bindings.append({"file": name, "sha256": expected, "size_bytes": len(raw)})
        return raw

    pinned = {name: read(name, digest) for name, digest in PINS.items()}
    manifest = parse(pinned[MANIFEST])
    base = Path(MANIFEST).parent
    source_ref = manifest["source_manifest"]
    source_path = (root / base / source_ref["file"]).resolve().relative_to(root).as_posix()
    read(source_path, source_ref["sha256"])
    side = manifest["materialization"]["sidecar"]
    sidecar = parse(read((base / side["file"]).as_posix(), side["sha256"], side["size_bytes"]))
    cases = []
    need(len(manifest["cases"]) == len(manifest["materialization"]["inputs"]) == 2,
         "two_cases_required")
    for case, ref in zip(manifest["cases"], manifest["materialization"]["inputs"], strict=True):
        data = parse(read((base / ref["file"]).as_posix(), ref["sha256"], ref["size_bytes"]))
        need(data["id"] == ref["id"] == case["id"] and data["question"] == case["question"],
             "case_binding")
        cases.append(prepare_input(data, sidecar, case["reference_answer"]))
    for ref in manifest["materialization"]["public_contract_code"]:
        read(ref["file"], ref["sha256"])
    # Capture the reused implementation, including transport/guards and this helper.
    # These observed hashes are custody bindings, not a new semantic approval.
    seen = {ref["file"] for ref in bindings}
    for name in (*r.CODE_FILES, "scripts/measure_meeting_qa_representation.py",
                 "tests/test_meeting_qa_representation.py"):
        if name not in seen:
            raw = r.assets.small_bytes(r.bound_path(name, root), 8 * 1024**2)
            bindings.append({"file": name, "sha256": sha(raw), "size_bytes": len(raw)})
            seen.add(name)
    return cases, bindings


class CountTransport(GGUFGenerator):
    """Seven ordered requests only. The inherited transport is bounded/no redirects."""

    def __init__(self, service, *, clock, check, emit, transport=None):
        super().__init__(service.url, service.token, service.manifest_path
                         if hasattr(service, "manifest_path") else ROOT / "unused",
                         transport=transport)
        self.clock, self.check, self.emit = clock, check, emit
        self.sent, self.halted = 0, False

    def _remaining(self, deadline=None):
        need(not self.halted, "measurement_halted")
        self.check()
        return r.remaining(self.clock, self._deadline if deadline is None else deadline)

    def _request(self, method, path, payload=None, deadline=None):
        try:
            need(self.sent < len(SEQUENCE) and (method, path) == SEQUENCE[self.sent],
                 "token_count_only_route")
            self._remaining(deadline)
            if path == "/props":
                need(payload is None, "props_payload")
            elif path == "/apply-template":
                exact(payload, "messages", "template_payload")
            else:
                exact(payload, "content add_special parse_special with_pieces", "tokenize_payload")
                need(isinstance(payload["content"], str) and payload["add_special"] is False
                     and payload["parse_special"] is True and payload["with_pieces"] is False,
                     "tokenize_flags")
            self.sent += 1  # Never refund a lost response or retry.
            self.emit("request", {"index": self.sent, "method": method, "path": path, "body": payload})
            result = super()._request(method, path, payload, deadline)
            self.emit("response", {"index": self.sent, "path": path, "body": result})
            self._remaining(deadline)
            return result
        except Exception:
            self.halted = True
            raise

    def tokens(self, content, deadline):
        result = self._request("POST", "/tokenize", {"content": content, "add_special": False,
            "parse_special": True, "with_pieces": False}, deadline)
        tokens = result.get("tokens")
        need(isinstance(tokens, list) and tokens and all(type(t) is int and t >= 0 for t in tokens),
             "token_protocol")
        return tokens


def save(output, name, data):
    with (output / name).open("xb") as stream:
        stream.write(data)
    return {"file": name, "sha256": sha(data), "size_bytes": len(data)}


def measure(adapter, cases, prepared, output, deadline, results):
    need(len(cases) == 2 and len({case["id"] for case in cases}) == 2, "two_cases_required")
    props = adapter._request("GET", "/props", deadline=deadline)
    validate_props(props, prepared)
    for index, case in enumerate(cases, 1):
        refs = [save(output, f"case-{index}.messages.json", wire(case["messages"])),
                save(output, f"case-{index}.reference.json", case["reference"].encode("utf-8"))]
        prompt = adapter._request("POST", "/apply-template", {"messages": case["messages"]}, deadline).get("prompt")
        need(isinstance(prompt, str) and prompt, "template_protocol")
        refs.append(save(output, f"case-{index}.prompt.txt", prompt.encode("utf-8")))
        input_ids = adapter.tokens(prompt, deadline)
        refs.append(save(output, f"case-{index}.input-token-ids.json", wire(input_ids)))
        reference_ids = adapter.tokens(case["reference"], deadline)
        refs.append(save(output, f"case-{index}.reference-token-ids.json", wire(reference_ids)))
        results.append({"id": case["id"], "files": refs, "input_tokens": len(input_ids),
            "input_limit": 4096, "input_excess": max(0, len(input_ids) - 4096),
            "serialized_reference_content_tokens": len(reference_ids), "reference_content_limit": 256,
            "reference_content_excess": max(0, len(reference_ids) - 256),
            "one_eog_allowance": 1, "reference_content_plus_eog_convention": len(reference_ids) + 1,
            "reference_plus_eog_excess": max(0, len(reference_ids) + 1 - 256),
            "observed_generation_accounting": False})
    need(adapter.sent == 7, "request_count")


def execute(descriptor, descriptor_sha, output, *, root=ROOT, clock=time.monotonic,
            launcher=r.launch_model, preparer=r.prepare_admitted_model,
            guard_factory=make_resource_guard, adapter_factory=CountTransport):
    """No epoch registration/once calls; fresh output refuses accidental replay."""
    root = Path(root).resolve()
    output = Path(output).absolute()
    output = r.bound_path(output.relative_to(root).as_posix(), root)
    need(output.parent == root / ".local" and output.name.startswith(
        "meeting-free-qa-representation-measurement-") and not output.exists(), "fresh_output")
    cases, bindings = load_inputs(root)
    descriptor = Path(descriptor).absolute()
    name = descriptor.relative_to(root).as_posix()
    raw = r.assets.small_bytes(r.bound_path(name, root), 8 * 1024**2)
    need(sha(raw) == descriptor_sha, "model_descriptor_changed")
    model = parse(raw)
    need(model["id"] == BASELINE, "baseline_only")
    admitted = r.admit_model(model, BINDING, RUNTIME, root=root)
    bindings.append({"file": name, "sha256": descriptor_sha, "size_bytes": len(raw)})
    output.mkdir(exist_ok=False)
    report = {"status": "stopped", "limits": LIMITS, "bindings": bindings, "cases": [],
        "first_failure": None, "secondary_failures": [], "AI_quality": False,
        "human_reviews": 0, "heldout_evaluation": False, "gold_context_retrieval_bypass": True,
        "completions": 0, "requested_generation_tokens": 0, "retries": 0,
        "admission": "Metadata admission precedes the 185s lifecycle; external fresh serial gate required.",
        "scope": "Fixed reference token counts cannot establish model quality or adequate phrasing limits."}
    metrics, adapter, prepared = {}, None, None
    started = clock()
    startup, whole = started + 120, started + 185
    events = []
    recorded_errors = []

    def emit(kind, value):
        events.append(save(output, f"event-{len(events) + 1:02d}-{kind}.json", wire(value)))

    def record_error(error):
        # Re-raised exceptions cross several owners; retain each occurrence once.
        if any(error is previous for previous in recorded_errors):
            return
        recorded_errors.append(error)
        if report["first_failure"] is None:
            report["first_failure"] = r.safe_error(error)
        else:
            report["secondary_failures"].append(r.safe_error(error))

    try:
        with r.worker_lease(root / ".local" / "meeting-free-qa-comparison.lock"):
            prepared = preparer(admitted, startup, clock=clock)
            with launcher(prepared, startup, metrics, clock=clock) as service:
                guard = guard_factory(service.process, RSS6_RESOURCES, clock=clock,
                                      expected_created=metrics["owned_create_time"])
                active = min(whole - 5, clock() + 60)
                adapter = adapter_factory(service, clock=clock, check=guard.check, emit=emit)
                try:
                    with guard.arm(active, metrics.setdefault("active_resources", {})):
                        try:
                            measure(adapter, cases, prepared, output, active, report["cases"])
                            r.check_prepared(prepared, prepared.policy, clock, active)
                            r.remaining(clock, active)
                        except Exception as error:
                            # Capture before guard.arm's finally can replace it.
                            record_error(error)
                            raise
                except Exception as error:
                    record_error(error)
                    raise
                finally:
                    try:
                        adapter.close()
                    except Exception as error:
                        record_error(error)
                        raise
            need(metrics.get("within_budget") is True and metrics.get("process_absence_confirmed") is True,
                 "cleanup")
            need(not metrics.get("cleanup_failures"), "cleanup")
            for ref in bindings:
                r.read_ref(ref, root)
                r.remaining(clock, whole)
            r.check_prepared(prepared, prepared.policy, clock, whole)
            report["status"] = "completed"
    except Exception as error:  # noqa: BLE001 - preserve terminal failures without retry
        record_error(error)
    report.update(cleanup=metrics, events=events, elapsed_seconds=clock() - started,
                  application_requests=adapter.sent if adapter is not None else 0)
    if clock() >= whole:
        report["status"] = "stopped"
        report["secondary_failures"].append({"code": "whole_deadline"})
    report["requires_external_terminal_custody"] = True
    save(output, "report.json", wire(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-descriptor", type=Path, required=True)
    parser.add_argument("--model-descriptor-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = execute(args.model_descriptor, args.model_descriptor_sha256, args.output)
    print(json.dumps({"status": report["status"], "application_requests": report["application_requests"],
                      "completions": 0, "AI_quality": False}))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
