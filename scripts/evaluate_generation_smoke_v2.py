"""Corrected greedy v2 entrypoint; preserve all frozen v1 source and receipts.

The serialized, temporary in-memory adapter reuses v1 locking, watchdogs,
reservations, receipts, and replay. Its explicit top-level worker is importable
by Windows spawn and creates the v2 generator in the child process.
"""

from __future__ import annotations

import argparse
import json
import threading
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from doctrail.generation_runtime import GenerationError
from doctrail.grounded_answer import GroundedAnswerError
from scripts import evaluate_generation_smoke as base

ROOT = base.ROOT
PROTOCOL_ID = "corrected_greedy_v2"
REQUIRED_SOURCES = base.REQUIRED_SOURCES | {
    "scripts/evaluate_generation_smoke_v2.py", "src/doctrail/generation_runtime_v2.py",
    "docs/M5-DESIGN.md", "data/evaluation/reviews/m5-smoke-review-v1.json",
}
EXPECTED_EFFECTIVE = {
    "max_new_tokens": 384, "do_sample": False, "num_beams": 1,
    "num_return_sequences": 1, "temperature": 1.0, "top_k": 50, "top_p": 1.0,
    "typical_p": 1.0, "repetition_penalty": 1.0, "length_penalty": 1.0,
    "bos_token_id": 151643,
    "eos_token_id": [151645, 151643], "pad_token_id": 151643, "use_cache": True,
    "generation_mode": "greedy_search", "use_model_defaults": False,
}
_BASE_VERIFY = base.verify_plan
_BASE_WRITE = base._write_json
_ADAPTER_LOCK = threading.Lock()


def verify_plan(plan_path, root=ROOT):
    plan, dataset, manifest, sources = _BASE_VERIFY(plan_path, root)
    if (plan["run_id"] != "m5-generation-v2"
            or plan.get("protocol_id") != PROTOCOL_ID
            or not REQUIRED_SOURCES.issubset(sources)):
        raise base.SmokeError("invalid_generation_v2_plan")
    return plan, dataset, manifest, sources


def _check_effective(config):
    if not isinstance(config, dict):
        raise base.SmokeError("generation_v2_effective_config_missing")
    for key, expected in EXPECTED_EFFECTIVE.items():
        actual = config.get(key)
        if type(actual) is not type(expected) or actual != expected:
            raise base.SmokeError("generation_v2_effective_config_mismatch")


def _check_metadata(metadata):
    if (not isinstance(metadata, dict)
            or metadata.get("generation_protocol") != "m5-greedy-v2"
            or metadata.get("use_model_defaults") is not False
            or metadata.get("effective_config_verified") is not True):
        raise base.SmokeError("generation_v2_runtime_metadata_mismatch")
    _check_effective(metadata.get("effective_generation_config"))


def _worker(connection, snapshot, manifest_path):
    # A top-level, spawn-safe worker must import the corrected runtime itself;
    # replacing the v1 module's class only in the parent would not affect spawn.
    from doctrail.generation_runtime_v2 import LocalGenerator

    generator = None
    try:
        generator = LocalGenerator(snapshot, manifest_path)
        generator.load()
        metadata = generator.public_metadata()
        _check_metadata(metadata)
        connection.send({"event": "loaded", "metadata": metadata,
                         "load_metrics": generator.load_metrics,
                         "verified_files": generator.verified_files})
        while True:
            command = connection.recv()
            if command["event"] == "close":
                break
            result = asdict(generator.generate(command["messages"]))
            _check_effective(result.get("effective_generation_config"))
            connection.send({"event": "generated", "case_id": command["case_id"],
                             "result": result})
    except (GenerationError, base.SmokeError) as error:
        connection.send({"event": "failed", "error_code": error.code,
                         "telemetry": getattr(error, "telemetry", {})})
    except Exception:  # noqa: BLE001 - safe child-process error boundary
        connection.send({"event": "failed", "error_code": "generation_worker_failed"})
    finally:
        if generator is not None:
            generator.close()
        connection.close()


def _write_json(path, payload):
    if isinstance(payload, dict) and isinstance(payload.get("cases"), list):
        payload["protocol_id"] = PROTOCOL_ID
    _BASE_WRITE(path, payload)


@contextmanager
def _adapter():
    if not _ADAPTER_LOCK.acquire(blocking=False):
        raise base.SmokeError("generation_v2_adapter_busy")
    originals = (base.verify_plan, base._worker, base._write_json)
    try:
        base.verify_plan, base._worker, base._write_json = verify_plan, _worker, _write_json
        yield
    finally:
        base.verify_plan, base._worker, base._write_json = originals
        _ADAPTER_LOCK.release()


def run(plan_path, snapshot, output, root=ROOT):
    with _adapter():
        return base.run(plan_path, snapshot, output, root)


def replay(report_path, root=ROOT):
    report = base._json(report_path)
    if report.get("protocol_id") != PROTOCOL_ID:
        raise base.SmokeError("replay_generation_v2_protocol_mismatch")
    if "model_runtime" in report:
        _check_metadata(report["model_runtime"].get("metadata"))
    elif report.get("cases") or report.get("status") == "completed":
        raise base.SmokeError("replay_generation_v2_runtime_missing")
    for row in report.get("cases", []):
        if row.get("model_called") is True:
            _check_effective(row.get("generation", {}).get("effective_generation_config"))
    with _adapter():
        result = base.replay(report_path, root)
    return {**result, "protocol_id": PROTOCOL_ID,
            "effective_config_verified": "model_runtime" in report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    try:
        if args.replay:
            result = replay(args.replay)
        else:
            if not all((args.plan, args.snapshot, args.output)):
                parser.error("--plan, --snapshot and --output are required for execution")
            report = run(args.plan.absolute(), args.snapshot, args.output)
            result = {"status": report["status"], "error_code": report.get("error_code"),
                      "protocol_id": report["protocol_id"], "summary": report["summary"]}
    except (base.SmokeError, GenerationError, GroundedAnswerError) as error:
        result = {"status": "failed", "error_code": error.code}
    except Exception:  # noqa: BLE001 - no raw output, local paths, or third-party error text
        result = {"status": "failed", "error_code": "smoke_command_failed"}
    print(json.dumps(result, sort_keys=True))
    return 1 if result.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
