"""Explicit metadata admission, full preparation and once-only QA epochs.

No assets or resource readings at import. The fixed trusted-lock file is created
by a separate custodian, not selected by a registration or CLI argument.
"""
from __future__ import annotations

import os
import re
import secrets
import subprocess
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from doctrail.meeting_contract import grounded_answer_refs, meeting_units
from doctrail.meeting_grounded_summary import source_payload
from doctrail.meeting_worker import worker_lease
from scripts.prepare_meeting_gguf import safe_member
from scripts.probe_meeting_local_candidate import (
    CODE_FILES as LEGACY_CODE_FILES,
)
from scripts.probe_meeting_local_candidate import (
    COMPACT_WIRE,
    CONTENT_ERRORS,
    QA_COVERAGE_CONTROL,
    QA_GRAMMAR,
    RSS6_RESOURCES,
    make_resource_guard,
    qa_request_messages,
    runtime_path_set,
    source_wire_messages,
)
from scripts.probe_meeting_summary_mode import (
    Evidence,
    bound_path,
    check_ref,
    cleanup_owner,
    owned_create_time,
)
from scripts.serve_meeting_thinking_compat import CompatService, DiscardDrain
from scripts.serve_models import unused_port, wait_ready
from tools.free_qa import assets
from tools.free_qa.policy import (
    CANDIDATE,
    CATALOGS,
    EPOCHS,
    ComparisonContract,
    bind_policy,
    canonical,
    digest_value,
    exact,
    freeze,
    need,
    parse,
    reference,
    sha,
    thaw,
    validate_contract,
    validate_preflight_review,
)

ROOT = Path(__file__).resolve().parents[2]
TRUSTED_LOCK_FILE = "data/meetings/free-qa-trusted-locks-v1.json"
CODE_FILES = (*LEGACY_CODE_FILES, "tools/free_qa/policy.py", "tools/free_qa/adapter.py",
    "tools/free_qa/runner.py", "scripts/probe_meeting_free_qa.py", "tests/test_meeting_free_qa.py",
    "tools/free_qa/assets.py", "tools/summary_grammar/runtime.py")
_PREPARED = object()


def remaining(clock, deadline):
    need(clock() < deadline, "deadline")
    return deadline - clock()


def read_ref(row, root, *, metadata=True):
    reference(row)
    path = bound_path(row["file"], root)
    before = assets.identity(assets.regular(path))
    if metadata:
        data = assets.small_bytes(path, 8 * 1024**2)
        need(len(data) == row["size_bytes"] and sha(data) == row["sha256"], "reference_changed")
    else:
        check_ref(dict(row), root)
        data = None
    need(assets.identity(assets.regular(path)) == before, "reference_identity_changed")
    return path, data


def prompt_binding():
    return {"qa_system_sha256": sha(QA_COVERAGE_CONTROL.system().encode()),
            "grammar_sha256": sha(QA_GRAMMAR.encode()), "source_wire": COMPACT_WIRE,
            "qa_control": QA_COVERAGE_CONTROL.name}


@dataclass(frozen=True)
class VerifiedContract:
    contract: ComparisonContract
    policies: tuple
    locks: object
    root: Path
    lock_ref: object = None
    custody_refs: tuple = ()
    gate_refs: tuple = ()


def check_inputs(contract, root):
    rows = [item for row in [*contract["cases"], contract["neutral"]] for item in (row["input"], row["sidecar"])]
    parents = {Path(row["file"]).parent.as_posix() for row in rows}
    need(len(parents) == 1 and "." not in parents, "input_root")
    folder = bound_path(next(iter(parents)), root)
    need(len({row["file"].casefold() for row in rows}) == 14
         and runtime_path_set(folder) == frozenset(Path(row["file"]).name for row in rows), "input_inventory")
    return rows


def verify_contract(contract, trusted_locks=None, *, root=ROOT):
    """Metadata only: no model/runtime body reads, resource sampling or once writes."""
    root = Path(root).resolve()
    lock_ref = None
    if trusted_locks is None:
        path = bound_path(TRUSTED_LOCK_FILE, root)
        raw_locks = assets.small_bytes(path, 8 * 1024**2)
        lock_ref = {"file": TRUSTED_LOCK_FILE, "size_bytes": len(raw_locks), "sha256": sha(raw_locks)}
        trusted_locks = parse(raw_locks)
    if isinstance(contract, (bytes, str)):
        contract = parse(contract)
    validated = validate_contract(contract, trusted_locks)
    need({r["file"] for r in contract["code"]} == set(CODE_FILES)
         and len(contract["code"]) == len(CODE_FILES), "code_closure")
    need(contract["prompt"] == prompt_binding(), "prompt_binding")
    for row in contract["code"]:
        read_ref(row, root, metadata=False)
    # Criteria and packet are opaque byte bindings, never parsed or judged here.
    for row in (contract["criteria"], contract["packet"]):
        read_ref(row, root, metadata=False)
    _, review_bytes = read_ref(contract["preflight_review"], root)
    validate_preflight_review(parse(review_bytes), contract)
    _, excluded_bytes = read_ref(contract["exclusion"], root)
    excluded = parse(excluded_bytes)
    exact(excluded, "catalogs families ids content_hashes question_hashes", "exclusion_index")
    need(set(excluded["catalogs"]) == CATALOGS and all(excluded["catalogs"].values()), "missing_catalog")
    for row in contract["cases"]:
        need(not {row["family"], *row["aliases"], *row["ancestors"]}.intersection(excluded["families"])
             and row["id"] not in excluded["ids"] and row["content_sha256"] not in excluded["content_hashes"]
             and row["question_sha256"] not in excluded["question_hashes"], "excluded_case")
        reference(row["input"])
        reference(row["sidecar"])
    check_inputs(contract, root)  # Names only; no question/source body reads during verify.
    neutral = contract["neutral"]
    need(neutral["id"] not in excluded["ids"] and neutral["content_sha256"] not in excluded["content_hashes"]
         and neutral["question_sha256"] not in excluded["question_hashes"], "excluded_neutral")
    policies, gate_refs = [], []
    for model in contract["models"]:
        _, profile_bytes = read_ref(model["profile"], root)
        _, binding_bytes = read_ref(model["binding"], root)
        binding = parse(binding_bytes)
        policy = bind_policy(profile_bytes, binding, model["runtime"])
        for key in ("metadata_receipt", "review_receipt", "acquisition_gate"):
            read_ref(binding[key], root)
        _, gate_bytes = read_ref(binding["acquisition_gate"], root)
        gate = parse(gate_bytes)
        common = "kind status profile_sha256 canonical_root source_commit source custody"
        if policy.model_id == CANDIDATE:
            exact(gate, common + " actual_cli_exit final_stdout attempt_token attempt cleanup_verified", "external_gate")
            need(gate["kind"] == "external_acquire" and type(gate["actual_cli_exit"]) is int and gate["actual_cli_exit"] == 0
                 and gate["cleanup_verified"] is True and gate["final_stdout"] == {
                     "status": "ACQUIRED_VERIFIED_METADATA_UNREVIEWED", "execution_approved": False}, "unaccepted_external_gate")
            attempt_path, attempt_bytes = read_ref(gate["attempt"], root)
            attempt = parse(attempt_bytes)
            need(attempt_path == bound_path(model["model_root"], root) / "attempt.json"
                 and attempt["operation"] == "acquire" and attempt["token"] == gate["attempt_token"]
                 and isinstance(gate["attempt_token"], str) and gate["attempt_token"]
                 and Path(attempt["root"]).resolve() == Path(gate["canonical_root"]).resolve()
                 and attempt["profile_sha256"] == policy.profile_sha256 and attempt["retry"] is False
                 and attempt["shared_seconds"] == 1800 and attempt["cleanup_reserved_seconds"] == 5
                 and attempt["transfer_limit"] == 5 * 1024**3 and attempt["disk_limit"] == 6 * 1024**3, "acquisition_attempt")
            gate_refs.append(gate["attempt"])
        else:
            # Existing Ministral acquisition predates the Qwen acquire CLI contract.
            exact(gate, common + " asset_receipt", "baseline_asset_gate")
            need(gate["kind"] == "existing_baseline_assets", "baseline_asset_gate")
            read_ref(gate["asset_receipt"], root, metadata=False)
            gate_refs.append(gate["asset_receipt"])
        need(gate["status"] == "accepted" and gate["profile_sha256"] == policy.profile_sha256
             and Path(gate["canonical_root"]).resolve() == bound_path(model["model_root"], root).resolve()
             and isinstance(gate["source_commit"], str) and re.fullmatch(r"[0-9a-f]{40}", gate["source_commit"])
             and isinstance(gate["source"], list) and gate["source"]
             and len({row["file"].casefold() for row in gate["source"]}) == len(gate["source"]), "unaccepted_external_gate")
        for item in [gate["custody"], *gate["source"]]:
            read_ref(item, root, metadata=False)
            gate_refs.append(item)
        policies.append(policy)
    return VerifiedContract(validated, tuple(policies), freeze(trusted_locks), root, freeze(lock_ref), gate_refs=freeze(gate_refs))


def prepare_case(row, data, sidecar):
    """Lossless bundle; units originate within each document, never across boundaries."""
    exact(data, "id title question bundle documents", "case_input")
    exact(sidecar, "bundle_sha256 documents units", "sidecar")
    need(data["id"] == row["id"] and isinstance(data["bundle"], str) and isinstance(data["question"], str)
         and data["question"].strip() and isinstance(data["title"], str), "case_values")
    content = data["bundle"]
    need(sha(content.encode()) == row["content_sha256"] == sidecar["bundle_sha256"]
         and sha(data["question"].encode()) == row["question_sha256"], "case_bytes")
    need(isinstance(data["documents"], list) and data["documents"], "documents")
    units, projected, mapping, metadata, seen = [], [], {}, [], set()
    previous_end = 0
    for document in data["documents"]:
        exact(document, "document_id revision title content start_offset end_offset", "source_document")
        start, end = document["start_offset"], document["end_offset"]
        need(type(start) is int and type(end) is int and previous_end <= start < end <= len(content)
             and content[start:end] == document["content"] and isinstance(document["title"], str)
             and type(document["revision"]) is int and document["revision"] > 0
             and isinstance(document["document_id"], str) and document["document_id"]
             and document["document_id"] not in seen, "document_boundaries")
        need(document["title"] and document["title"] in content[previous_end:start], "bundle_title")
        seen.add(document["document_id"])
        metadata.append({k: document[k] for k in ("document_id", "revision", "title", "start_offset", "end_offset")}
                        | {"content_sha256": sha(document["content"].encode())})
        for unit in meeting_units(document["content"]):
            index = len(units)
            shifted = {"quote": unit["quote"], "start_offset": start + unit["start_offset"], "end_offset": start + unit["end_offset"]}
            units.append(shifted)
            projected.append({"id": index, "document_id": document["document_id"], "revision": document["revision"],
                **unit, "bundle_start_offset": shifted["start_offset"], "bundle_end_offset": shifted["end_offset"]})
            mapping[index] = {**unit, "document_id": document["document_id"], "revision": document["revision"],
                              "chunk_id": f"{document['document_id']}:{document['revision']}:{index}"}
        previous_end = end
    need(1 <= len(units) <= 160 and projected == sidecar["units"] and metadata == sidecar["documents"], "sidecar_mapping")
    source = source_payload(data["title"], content, units)
    messages = source_wire_messages(qa_request_messages(source, data["question"], QA_COVERAGE_CONTROL),
                                    source, content, units, COMPACT_WIRE)
    need(sha(canonical(messages)) == row["messages_sha256"], "paired_messages")
    return messages, mapping


@dataclass(frozen=True)
class PreparedModel:
    policy: object
    root: Path
    model_root: Path
    entry: Path
    server: Path
    runtime_root: Path
    files: tuple
    token: object


def check_prepared(prepared, policy, clock, deadline):
    need(isinstance(prepared, PreparedModel) and prepared.token is _PREPARED and prepared.policy is policy, "prepared_connection")
    for name, expected in prepared.files:
        remaining(clock, deadline)
        need(assets.identity(assets.regular(Path(name))) == expected, "prepared_file_changed")
    model_names = frozenset(Path(name).relative_to(prepared.model_root).as_posix() for name, _ in prepared.files
                            if Path(name).is_relative_to(prepared.model_root))
    need(runtime_path_set(prepared.model_root) == model_names, "model_inventory")
    need(runtime_path_set(prepared.runtime_root) == frozenset(r["file"] for r in policy.runtime["files"]), "runtime_inventory")
    remaining(clock, deadline)


def prepare_model(verified, model_id, deadline, *, clock=time.monotonic):
    need(isinstance(verified, VerifiedContract), "verified_contract_required")
    model = next(x for x in thaw(verified.contract.data)["models"] if x["id"] == model_id)
    policy = next(x for x in verified.policies if x.model_id == model_id)
    root = verified.root
    model_root = bound_path(model["model_root"], root)
    runtime_root = bound_path(policy.runtime["root"], root)
    need(runtime_path_set(model_root) == frozenset(r["file"] for r in model["asset_files"]), "model_inventory")
    need(runtime_path_set(runtime_root) == frozenset(r["file"] for r in policy.runtime["files"]), "runtime_inventory")
    records = {}
    for folder, rows in ((model_root, model["asset_files"]), (runtime_root, policy.runtime["files"])):
        for row in rows:
            remaining(clock, deadline)
            need(safe_member(row["file"]).as_posix() == row["file"], "asset_member")
            path = bound_path(row["file"], folder)
            before = assets.identity(assets.regular(path))
            check_ref(thaw(row), folder)  # Reuse the existing streaming SHA reference check.
            need(assets.identity(assets.regular(path)) == before, "asset_changed_during_hash")
            records[str(path)] = before
            remaining(clock, deadline)
    observations, metadata_remaining = [], 32 * 1024**2
    for shard in policy.shards:
        relative = ("assets/" if model_id == CANDIDATE else "") + shard["filename"]
        expected = next((row for row in model["asset_files"] if row["file"] == relative), None)
        need(expected is not None and expected["sha256"] == shard["sha256"]
             and expected["size_bytes"] == shard["size_bytes"], "whole_shard_binding")
        path = bound_path(relative, model_root)
        def checkpoint():
            remaining(clock, deadline)
        with path.open("rb", buffering=0) as stream:
            reader = assets.KVReader(stream, checkpoint, metadata_remaining)
            observed = reader.parse()
        metadata_remaining -= observed["metadata_bytes_read"]
        observations.append(observed)
        need(assets.identity(assets.regular(path)) == records[str(path)], "metadata_file_changed")
    need(canonical(observations) == canonical(policy.reviewed["metadata"]), "unreviewed_embedded_metadata")
    entry = model_root / (("assets/" if model_id == CANDIDATE else "") + policy.entry)
    prepared = PreparedModel(policy, root, model_root, entry, runtime_root / policy.runtime["server"], runtime_root,
                             tuple(records.items()), _PREPARED)
    check_prepared(prepared, policy, clock, deadline)
    return prepared


def command(prepared, port):
    return [str(prepared.server), "--model", str(prepared.entry), "--host", "127.0.0.1", "--port", str(port),
        "--alias", prepared.policy.alias, "--ctx-size", "6144", "--parallel", "1", "--n-gpu-layers", "99",
        "--cache-type-k", "f16", "--cache-type-v", "f16", "--fit", "off", "--jinja", "--reasoning", "off",
        "--no-warmup", "--cache-ram", "0", "--no-context-shift", "--no-webui", "--log-disable"]


@contextmanager
def launch_model(prepared, deadline, metrics, *, clock=time.monotonic):
    import psutil
    with ExitStack() as stack:
        for name in ("meeting-generation.gpu.lock", "meeting-generation.worker.lock", "meeting-llama.lease"):
            stack.enter_context(worker_lease(prepared.root / ".local" / name))
        check_prepared(prepared, prepared.policy, clock, deadline)
        port, token = unused_port(), secrets.token_urlsafe(48)
        env = {key: value for key, value in os.environ.items() if not key.startswith("LLAMA_ARG_")}
        env.update(LLAMA_API_KEY=token, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        remaining(clock, deadline)
        available = psutil.virtual_memory().available  # Exactly one fresh startup gate.
        metrics["startup_ram_gate"] = {"available_bytes": available, "minimum_bytes": 8 * 1024**3,
                                       "passed": available >= 8 * 1024**3}
        need(metrics["startup_ram_gate"]["passed"], "startup_ram")
        process = drain = None
        try:
            remaining(clock, deadline)
            metrics["process_creation_attempted"] = True
            process = subprocess.Popen(command(prepared, port), cwd=prepared.server.parent, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            metrics.update(owned_pid=process.pid, owned_create_time=owned_create_time(process))
            drain = DiscardDrain(process.stdout)
            drain.start()
            guard = make_resource_guard(process, RSS6_RESOURCES, clock=clock, expected_created=metrics["owned_create_time"])
            with guard.arm(deadline, metrics.setdefault("startup_resources", {})):
                wait_ready(process, f"http://127.0.0.1:{port}/health", headers={"Authorization": "Bearer " + token},
                           timeout=remaining(clock, deadline))
                remaining(clock, deadline)
            yield CompatService(process, f"http://127.0.0.1:{port}", token, prepared.root / prepared.policy.profile_path,
                                {}, metrics, drain)
        finally:
            cleanup_owner(process, drain, metrics, clock=clock)


def safe_error(error):
    code = getattr(error, "code", None)
    return {"type": type(error).__name__, "code": code if isinstance(code, str) else "free_qa_boundary"}


def load_registration(registration, expected_sha, *, trusted_locks=None, root=ROOT):
    root = Path(root).resolve()
    path = Path(registration).absolute()
    need(path.is_relative_to(root), "registration_scope")
    path = bound_path(path.relative_to(root).as_posix(), root)
    data = assets.small_bytes(path, 8 * 1024**2)
    need(sha(data) == expected_sha, "registration_sha")
    spec = parse(data)
    exact(spec, "schema_version contract epoch output_dir once_sha256 predecessors", "registration")
    need(type(spec["schema_version"]) is int and spec["schema_version"] == 1 and spec["epoch"] in EPOCHS, "epoch")
    _, contract_bytes = read_ref(spec["contract"], root)
    verified = verify_contract(parse(contract_bytes), trusted_locks, root=root)
    epoch = EPOCHS[spec["epoch"]]
    output = bound_path(spec["output_dir"], root)
    need(output.is_relative_to(root / ".local") and not output.exists(), "fresh_output")
    once = sha(canonical({"contract_sha256": verified.contract.sha256, "epoch": epoch.name, "output_dir": spec["output_dir"]}))
    need(spec["once_sha256"] == once, "once_binding")
    expected = thaw(verified.locks)["predecessors"][epoch.name]
    need(spec["predecessors"] == expected and len(expected) == ["neutral", "baseline", "candidate"].index(epoch.name), "predecessor_lock")
    prior_calls = prior_tokens = 0
    custody_refs = []
    for index, ref in enumerate(expected):
        _, data = read_ref(ref, root)
        custody = parse(data)
        exact(custody, "epoch contract_sha256 registration_sha256 once_sha256 actual_cli_exit final_stdout terminal custody_verified", "prior_custody")
        prior_name = ["neutral", "baseline"][index]
        digest_value(custody["registration_sha256"])
        digest_value(custody["once_sha256"])
        need(custody["epoch"] == prior_name and custody["contract_sha256"] == verified.contract.sha256
             and type(custody["actual_cli_exit"]) is int and custody["actual_cli_exit"] == 0
             and custody["custody_verified"] is True and custody["final_stdout"] == {
                 "status": "completed", "epoch": prior_name, "registration_sha256": custody["registration_sha256"],
                 "once_sha256": custody["once_sha256"], "AI_quality": False}, "prior_external_terminal")
        terminal_path, terminal_bytes = read_ref(custody["terminal"], root)
        terminal = parse(terminal_bytes)
        exact(terminal, "status epoch contract_sha256 registration_sha256 once_sha256 counts valid_cases AI_quality report_sha256 cleanup_verified within_deadline", "prior_terminal_schema")
        need(terminal["epoch"] == prior_name and terminal["AI_quality"] is False
             and type(terminal["valid_cases"]) is int and 0 <= terminal["valid_cases"] <= EPOCHS[prior_name].calls, "prior_terminal_epoch")
        need(not (terminal_path.parent / "late-invalidation.json").exists(), "prior_invalidated")
        report_path = terminal_path.parent / "report.json"
        report_ref = {"file": report_path.relative_to(root).as_posix(), "size_bytes": assets.regular(report_path).st_size,
                      "sha256": digest_value(terminal["report_sha256"])}
        read_ref(report_ref, root, metadata=False)
        custody_refs.extend((custody["terminal"], report_ref))
        exact(terminal["counts"], "completions requested_tokens http", "prior_counts")
        need(type(terminal["counts"]["http"]) is int and 0 <= terminal["counts"]["http"] <= 1 + 3 * EPOCHS[prior_name].calls, "prior_http_cap")
        need(terminal["status"] == "completed" and terminal["contract_sha256"] == verified.contract.sha256
             and terminal["registration_sha256"] == custody["registration_sha256"]
             and terminal["once_sha256"] == custody["once_sha256"] and terminal["cleanup_verified"] is True
             and terminal["within_deadline"] is True, "prior_terminal")
        count, tokens = terminal["counts"]["completions"], terminal["counts"]["requested_tokens"]
        need(type(count) is int and 0 <= count <= EPOCHS[prior_name].calls
             and type(tokens) is int and tokens == count * 256, "prior_caps")
        if prior_name == "neutral":
            need(count == 1 and terminal["valid_cases"] == 1, "neutral_failed")
        prior_calls += count
        prior_tokens += tokens
    need(prior_calls + epoch.calls <= 13 and prior_tokens + epoch.calls * 256 <= 3328, "comparison_cap")
    return spec, replace(verified, custody_refs=freeze(custody_refs)), epoch, output, prior_calls


def run_epoch(registration, expected_sha, once_sha, *, trusted_locks=None, root=ROOT,
              clock=time.monotonic, launcher=launch_model, preparer=prepare_model, adapter_factory=None):
    """Explicit run only; tests inject doubles, never an automatic native/mock switch."""
    from tools.free_qa.adapter import PairedQAAdapter
    adapter_factory = PairedQAAdapter if adapter_factory is None else adapter_factory
    started = clock()
    spec, verified, epoch, output, prior_calls = load_registration(registration, expected_sha,
        trusted_locks=trusted_locks, root=root)
    need(once_sha == spec["once_sha256"], "explicit_once")
    root = verified.root
    contract = thaw(verified.contract.data)
    whole_deadline = started + epoch.whole_seconds
    startup_deadline = started + 120
    rows = [contract["neutral"]] if epoch.name == "neutral" else contract["cases"]
    # Contract/source incompatibility is rejected before Popen or once consumption.
    check_inputs(contract, root)
    prepared_cases = []
    for row in rows:
        remaining(clock, startup_deadline)
        _, source_bytes = read_ref(row["input"], root)
        _, sidecar_bytes = read_ref(row["sidecar"], root)
        source, sidecar = parse(source_bytes), parse(sidecar_bytes)
        prepare_case(row, source, sidecar)
        prepared_cases.append((row, source, sidecar))
    remaining(clock, startup_deadline)
    with worker_lease(root / ".local" / "meeting-free-qa-comparison.lock"):
        once_dir = bound_path(".local/meeting-free-qa-once", root)
        once_dir.mkdir(exist_ok=True)
        # One reservation per contract/epoch even if a new output/registration is proposed.
        epoch_reservation = once_dir / (verified.contract.sha256 + "-" + epoch.name + ".json")
        with epoch_reservation.open("xb") as stream:
            stream.write(canonical({"registration_sha256": expected_sha, "once_sha256": once_sha}))
        with (once_dir / (once_sha + ".json")).open("xb") as stream:
            stream.write(canonical({"registration_sha256": expected_sha, "contract_sha256": verified.contract.sha256,
                                    "epoch": epoch.name, "once_sha256": once_sha}))
        output.mkdir(parents=True, exist_ok=False)
        private = output / "private"
        private.mkdir()
        emit = Evidence(private)
        metrics, adapter, prepared = {}, None, None
        report = {"status": "stopped", "epoch": epoch.name, "contract_sha256": verified.contract.sha256,
            "registration_sha256": expected_sha, "once_sha256": once_sha, "AI_quality": False,
            "first_failure": None, "secondary_failures": [], "denominator": epoch.calls,
            "cases": [{"id": row["id"], "status": "unexecuted"} for row in rows],
            "counts": {"completions": 0, "requested_tokens": 0, "http": 0}, "prior_completions": prior_calls}
        try:
            prepared = preparer(verified, epoch.model_id, startup_deadline, clock=clock)
            with launcher(prepared, startup_deadline, metrics, clock=clock) as service:
                guard = make_resource_guard(service.process, RSS6_RESOURCES, clock=clock,
                                            expected_created=metrics["owned_create_time"])
                adapter = adapter_factory(service.url, service.token, policy=prepared.policy, epoch=epoch,
                    case_ids=tuple(row["id"] for row in rows), resource_check=guard.check, clock=clock, evidence=emit)
                try:
                    adapter.begin_request(startup_deadline)
                    with guard.arm(startup_deadline, metrics.setdefault("load_resources", {})):
                        adapter.load(prepared)
                        remaining(clock, startup_deadline)
                    adapter.end_request()
                    active_deadline = min(whole_deadline - 5, clock() + epoch.active_seconds)
                    for (row, source, sidecar), result in zip(prepared_cases, report["cases"], strict=True):
                        request_deadline = min(active_deadline, clock() + 60)
                        resources = {}
                        try:
                            with guard.arm(request_deadline, resources):
                                remaining(clock, request_deadline)
                                messages, mapping = prepare_case(row, source, sidecar)
                                remaining(clock, request_deadline)
                                generated = adapter.complete_qa(row["id"], messages, request_deadline)
                                parsed = grounded_answer_refs(generated.text, mapping)
                                remaining(clock, request_deadline)
                                emit("qa", {"case_id": row["id"], "parsed": parsed,
                                    "input_tokens": generated.input_tokens, "output_tokens": generated.output_tokens})
                                remaining(clock, request_deadline)
                            result.update(status="valid", answer_status=parsed["status"], resources=resources)
                        except Exception as error:
                            rejection = getattr(error, "code", None) in CONTENT_ERRORS
                            result.update(status="rejected" if rejection else "failed", error=safe_error(error), resources=resources)
                            report["first_failure"] = report["first_failure"] or safe_error(error)
                            if not rejection or epoch.name == "neutral":
                                adapter.halted = True
                                raise
                    report["status"] = "completed"
                finally:
                    try:
                        adapter.close()
                    except Exception as error:  # noqa: BLE001 - preserve first failure while closing transport
                        report["secondary_failures"].append(safe_error(error))
                        report["first_failure"] = report["first_failure"] or safe_error(error)
                        report["status"] = "stopped"
        except Exception as error:  # noqa: BLE001 - terminal fail-closed boundary
            report["first_failure"] = report["first_failure"] or safe_error(error)
            report["status"] = "stopped"
        finally:
            if adapter is not None:
                report["counts"] = dict(adapter.counts)
            report["cleanup"] = metrics
            try:
                need(not metrics.get("process_creation_attempted") or metrics.get("within_budget") is True, "cleanup")
                need(sha(assets.small_bytes(Path(registration), 8 * 1024**2)) == expected_sha, "registration_changed")
                check_inputs(contract, root)
                metadata_refs = [item for model in contract["models"] for item in (model["profile"], model["binding"])]
                metadata_refs += [thaw(policy.reviewed[key]) for policy in verified.policies
                                  for key in ("metadata_receipt", "review_receipt", "acquisition_gate")]
                metadata_refs += spec["predecessors"] + [thaw(item) for item in (*verified.custody_refs, *verified.gate_refs)]
                for item in verified.custody_refs:
                    if item["file"].endswith("/terminal.json"):
                        need(not (bound_path(item["file"], root).parent / "late-invalidation.json").exists(), "prior_invalidated")
                if verified.lock_ref is not None:
                    metadata_refs.append(thaw(verified.lock_ref))
                for ref in [*metadata_refs, spec["contract"], *contract["code"], contract["criteria"], contract["packet"], contract["exclusion"], contract["preflight_review"],
                            *[item for row in rows for item in (row["input"], row["sidecar"])]]:
                    remaining(clock, whole_deadline)
                    read_ref(ref, root, metadata=False)
                    remaining(clock, whole_deadline)
                if prepared is not None:
                    check_prepared(prepared, prepared.policy, clock, whole_deadline)
                    model = next(m for m in contract["models"] if m["id"] == epoch.model_id)
                    for folder, refs in ((prepared.model_root, model["asset_files"]),
                                         (prepared.runtime_root, prepared.policy.runtime["files"])):
                        for ref in refs:
                            remaining(clock, whole_deadline)
                            check_ref(thaw(ref), folder)
                            remaining(clock, whole_deadline)
                    check_prepared(prepared, prepared.policy, clock, whole_deadline)
                report["bindings_unchanged"] = True
            except Exception as error:  # noqa: BLE001 - custody failure cannot promote completion
                report["secondary_failures"].append(safe_error(error))
                report["first_failure"] = report["first_failure"] or safe_error(error)
                report["status"] = "stopped"
            report.update(valid_cases=sum(x["status"] == "valid" for x in report["cases"]),
                          elapsed_seconds=clock() - started, retries=0, requires_external_terminal_custody=True)
            try:
                emit.seal(report)
                remaining(clock, whole_deadline)
                with (output / "report.json").open("xb") as stream:
                    stream.write(canonical(report))
                remaining(clock, whole_deadline)
                terminal = {key: report[key] for key in ("status", "epoch", "contract_sha256", "registration_sha256",
                            "once_sha256", "counts", "valid_cases", "AI_quality")}
                terminal.update(report_sha256=sha((output / "report.json").read_bytes()),
                    cleanup_verified=metrics.get("within_budget") is True, within_deadline=clock() < whole_deadline)
                remaining(clock, whole_deadline)
                with (output / "terminal.json").open("xb") as stream:
                    stream.write(canonical(terminal))
                remaining(clock, whole_deadline)
                need(sha((output / "report.json").read_bytes()) == terminal["report_sha256"], "late_report_change")
                remaining(clock, whole_deadline)
            except BaseException as error:
                report["status"] = "stopped"
                report["first_failure"] = report["first_failure"] or safe_error(error)
                with (output / "late-invalidation.json").open("xb") as stream:
                    stream.write(canonical({"status": "INVALIDATED", "error": safe_error(error)}))
                raise
        return report
