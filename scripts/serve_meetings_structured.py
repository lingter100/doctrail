"""Explicit pinned local structured-output candidates; not semantic acceptance.

Uses the installed pinned prebuilt server, no downloads/builds. Actual native GPU
resource admission and experiment observation remain the caller's separate gate.
"""
from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import threading
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from doctrail.meeting_structured import (
    CONTEXT_TOKENS,
    LEGACY_QA_CONTRACT,
    MODEL_ID,
    MODEL_SHA256,
    PROFILE,
    QA_CONTRACTS,
    QWEN_PROFILE,
    STRUCTURED_PROFILES,
    StructuredGenerator,
    StructuredMeetingRuntime,
    prepare_qwen_assets,
)
from doctrail.meeting_worker import create_app, worker_lease
from scripts.run_meeting_qa_service_development import (
    MANIFEST,
    MODEL,
    FailureRecord,
    cleanup_owned,
    java_environment,
    java_executable,
    make_server,
    prepare,
    record_error,
    remaining,
    wait_ready,
)

QWEN_MANIFEST = ROOT / "data/models/meetings-generation-qwen25-7b-q4km-v1.json"
QWEN_ASSETS = ROOT / "models/meetings-qwen25-7b-q4km-v2/assets"


@contextmanager
def start_services(*, jar, database, java_port=8000, worker_port=8092, native_port=8093,
                   enable_structured=False, report=None, profile=PROFILE, qa_contract=LEGACY_QA_CONTRACT):
    """One native child, one Java child and one authenticated worker thread."""
    if not enable_structured:
        raise ValueError("structured_candidate_requires_explicit_opt_in")
    if profile not in STRUCTURED_PROFILES:
        raise ValueError("unknown_structured_profile")
    if qa_contract not in QA_CONTRACTS:
        raise ValueError("unknown_qa_contract")
    ports = [java_port, worker_port, native_port]
    if len(set(ports)) != 3 or any(type(port) is not int or not 1 <= port <= 65535 for port in ports):
        raise ValueError("invalid_distinct_ports")
    jar, database = Path(jar), Path(database)
    if not jar.is_file():
        raise ValueError("java_jar_required")
    if report is None:
        report = FailureRecord({"first_failure": None, "secondary_failures": []})
    processes, server, thread, generator = [], None, None, None
    started, startup = time.monotonic(), time.monotonic() + 120
    primary = None
    with ExitStack() as stack:
        for filename in ("meeting-generation.gpu.lock", "meeting-generation.worker.lock", "meeting-llama.lease"):
            stack.enter_context(worker_lease(ROOT / ".local" / filename))
        try:
            report["startup_stage"] = "preparation"
            import uvicorn  # noqa: F401 - resolve required HTTP dependency before native dispatch
            qwen_assets = None
            if profile == QWEN_PROFILE:
                qwen_assets = prepare_qwen_assets(QWEN_MANIFEST, QWEN_ASSETS, MODEL / "runtime", startup)
                binary, model_path, alias = (qwen_assets[key] for key in ("binary", "entry", "alias"))
                manifest = QWEN_MANIFEST
            else:
                receipt = prepare(MANIFEST, MODEL, allow_download=False)
                identity = json.loads(MANIFEST.read_text(encoding="utf-8"))
                if identity["model"] != MODEL_ID or identity["gguf"]["sha256"] != MODEL_SHA256:
                    raise ValueError("structured_model_identity")
                binary = (MODEL / receipt["server_path"]).resolve()
                model_path, alias, manifest = (MODEL / receipt["model"]["path"]).resolve(), MODEL_SHA256, MANIFEST
            remaining(startup)
            native_token, worker_token = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
            native_url, worker_url = f"http://127.0.0.1:{native_port}", f"http://127.0.0.1:{worker_port}"
            env = java_environment(database, worker_url, worker_token)
            argv = [str(binary), "--model", str(model_path),
                    "--host", "127.0.0.1", "--port", str(native_port), "--alias", alias,
                    "--ctx-size", str(CONTEXT_TOKENS), "--parallel", "1", "--n-gpu-layers", "99",
                    "--threads", "2", "--threads-batch", "2", "--batch-size", "512", "--ubatch-size", "128",
                    "--fit", "off", "--no-context-shift", "--no-webui", "--log-disable", "--no-warmup"]
            native = subprocess.Popen(argv, cwd=binary.parent, env=dict(env, LLAMA_API_KEY=native_token),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            processes.append(native)
            report["startup_stage"] = "native_health"
            wait_ready(native, native_url + "/health", headers={"Authorization": "Bearer " + native_token}, timeout=remaining(startup))
            generator = StructuredGenerator(native_url, native_token, manifest, profile=profile, qwen_assets=qwen_assets)
            report["startup_stage"] = "native_identity"
            generator.begin_request(startup)
            try:
                generator.load()
            finally:
                generator.end_request()
            runtime = StructuredMeetingRuntime(generator, qa_contract=qa_contract)
            server = make_server(create_app(worker_token, lambda: runtime), worker_port)
            thread = threading.Thread(target=server.run, daemon=True, name="structured-meetings-http")
            thread.start()
            report["startup_stage"] = "worker_health"
            wait_ready(native, worker_url + "/health", headers={"Authorization": "Bearer " + worker_token}, timeout=remaining(startup))
            java = subprocess.Popen([str(java_executable()), "-jar", str(jar.resolve()),
                "--server.address=127.0.0.1", f"--server.port={java_port}",
                "--doctrail.rag-answer-enabled=false", "--doctrail.embedding-profile=base",
                "--doctrail.answer-neighbors-enabled=true"], cwd=ROOT, env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            processes.append(java)
            report["startup_stage"] = "java_health"
            java_url = f"http://127.0.0.1:{java_port}"
            wait_ready(java, java_url + "/api/health", timeout=remaining(startup))
            remaining(startup)
            report.update(profile=profile, model=generator.public_metadata(), qa_contract=dict(runtime.qa_contract_info),
                          startup_seconds=time.monotonic() - started,
                          startup_stage="ready",
                          native_settings={"gpu_layers": 99, "cpu_threads": 2, "context_tokens": CONTEXT_TOKENS,
                              "parallel": 1, "resource_fit": "not_proven_by_startup", "external_fresh_gate_required": True},
                          answer_neighbors_enabled=True, semantic_quality_accepted=False, downloads=False)
            yield {"java_url": java_url, "worker_url": worker_url, "processes": processes, "thread": thread,
                   "runtime": runtime, "generator": generator, "report": report}
        except BaseException as error:
            primary = error
            record_error(report, error)
            raise
        finally:
            cleanup_owned(processes, server, thread, report, observer=generator)
            report["owned_exit_codes"] = []
            for process in processes:
                try:
                    report["owned_exit_codes"].append(process.poll())
                except Exception as error:  # noqa: BLE001 - metadata cannot mask the primary failure
                    report["owned_exit_codes"].append(None)
                    record_error(report, error)
            if primary is None and report.get("first_failure") is not None:
                raise RuntimeError("structured_owned_cleanup_failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-structured", action="store_true")
    parser.add_argument("--jar", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True, help="Explicit development database; choose a fresh isolated path for evaluation.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--worker-port", type=int, default=8092)
    parser.add_argument("--native-port", type=int, default=8093)
    parser.add_argument("--profile", choices=STRUCTURED_PROFILES, default=PROFILE)
    parser.add_argument("--qa-contract", choices=QA_CONTRACTS, default=LEGACY_QA_CONTRACT)
    args = parser.parse_args()
    if not args.enable_structured:
        parser.error("structured_candidate_requires_explicit_opt_in")
    try:
        with start_services(jar=args.jar, database=args.database, java_port=args.port,
                            worker_port=args.worker_port, native_port=args.native_port, enable_structured=True,
                            profile=args.profile, qa_contract=args.qa_contract) as services:
            print("DocTrail opt-in structured candidate ready: " + services["java_url"], flush=True)
            while all(process.poll() is None for process in services["processes"]) and services["thread"].is_alive():
                time.sleep(0.5)
            raise RuntimeError("structured_service_exited")
    except KeyboardInterrupt:
        pass
    except Exception:  # noqa: BLE001 - never echo tokens, source or native errors
        parser.exit(1, "structured_meeting_service_failed\n")


if __name__ == "__main__":
    main()
