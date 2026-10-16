"""Launch the explicitly prepared local GGUF candidate; no builds or downloads."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from doctrail.meeting_worker import worker_lease
from scripts.prepare_meeting_gguf import DEFAULT_ROOT, MANIFEST, ROOT, prepare
from scripts.serve_meetings import start_services
from scripts.serve_models import stop_process, unused_port, wait_ready


@dataclass
class LlamaService:
    process: subprocess.Popen
    url: str
    token: str = field(repr=False)
    manifest: Path
    identity: dict
    receipt: dict


@contextmanager
def start_llama(*, log_dir, model_dir=DEFAULT_ROOT, runtime_dir=None, port=0, token=None,
                manifest=MANIFEST):
    """Verify pinned archives/model/binaries before starting exactly one owned child."""
    model_dir, manifest = Path(model_dir), Path(manifest)
    runtime_dir = Path(runtime_dir) if runtime_dir else model_dir / "runtime"
    if runtime_dir.resolve() != (model_dir / "runtime").resolve():
        raise ValueError("runtime_must_match_setup_receipt")
    token = token or secrets.token_urlsafe(48)
    port = port or unused_port()
    if len(token) < 32 or any(not 33 <= ord(c) <= 126 for c in token):
        raise ValueError("invalid_llama_token")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("invalid_llama_port")
    with ExitStack() as stack:
        # Shared admission covers allocation through child termination, including failures.
        stack.enter_context(worker_lease(ROOT / ".local/meeting-generation.gpu.lock"))
        # A previously running legacy worker may predate shared GPU admission.
        # Release this probe before the GGUF HTTP worker takes its own lifetime lease.
        with worker_lease(ROOT / ".local/meeting-generation.worker.lock"):
            pass
        stack.enter_context(worker_lease(ROOT / ".local/meeting-llama.lease"))
        receipt = prepare(manifest, model_dir, allow_download=False)
        identity = json.loads(manifest.read_text(encoding="utf-8"))
        server = (model_dir / receipt["server_path"]).resolve()
        model = (model_dir / receipt["model"]["path"]).resolve()
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        log = stack.enter_context((log_dir / "llama.log").open("ab"))
        # API key stays in child environment, never process arguments or receipts.
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith("LLAMA_ARG_")}
        environment.update(LLAMA_API_KEY=token, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        process = subprocess.Popen(
            [str(server), "--model", str(model), "--host", "127.0.0.1", "--port", str(port),
             "--alias", identity["gguf"]["sha256"], "--ctx-size", "6144", "--parallel", "1",
             "--n-gpu-layers", "99", "--batch-size", "512", "--ubatch-size", "128",
             "--fit", "off", "--no-context-shift", "--no-webui", "--log-disable"],
            cwd=server.parent, env=environment, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        stack.callback(stop_process, process)
        url = f"http://127.0.0.1:{port}"
        wait_ready(process, url + "/health", headers={"Authorization": "Bearer " + token},
                   timeout=240)
        yield LlamaService(process, url, token, manifest, identity, receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--jar", type=Path, default=ROOT / "server/target/doctrail-server-0.1.0.jar")
    parser.add_argument("--database", type=Path, default=ROOT / "var/doctrail-java.sqlite3")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--worker-port", type=int, default=8092)
    parser.add_argument("--llama-port", type=int, default=8093)
    parser.add_argument("--retrieval", action="store_true", help="load E5/BGE on CPU only")
    parser.add_argument("--log-dir", type=Path, default=ROOT / "var/meeting-gguf-logs")
    args = parser.parse_args()
    ports = [args.port, args.worker_port, args.llama_port]
    if len(set(ports)) != len(ports):
        parser.error("ports_must_differ")
    if not args.jar.is_file():
        parser.error("build_java_jar_first")
    try:
        with (start_llama(log_dir=args.log_dir, model_dir=args.model_dir,
                         manifest=args.manifest, port=args.llama_port) as llama,
              start_services(jar=args.jar, database=args.database, model_root=args.model_dir,
                    log_dir=args.log_dir, java_port=args.port, worker_port=args.worker_port,
                    retrieval=args.retrieval, llama_url=llama.url, llama_token=llama.token,
                    llama_manifest=llama.manifest) as services):
            print(f"DocTrail experimental GGUF meetings ready: {services.java_url}", flush=True)
            children = [llama.process, services.java, services.worker] + (
                [services.retrieval] if services.retrieval else [])
            while all(child.poll() is None for child in children):
                time.sleep(0.5)
            raise RuntimeError("service_exited")
    except KeyboardInterrupt:
        pass
    except Exception:  # noqa: BLE001 - do not echo child credentials or raw model responses
        parser.exit(1, "meeting_gguf_service_failed_check_local_logs\n")


if __name__ == "__main__":
    main()
