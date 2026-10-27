"""Check public carriers, or execute one separately reviewed model-free engine batch."""
from __future__ import annotations

import argparse
import json
import math
import os
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.prepare_summary_grammar_engine import check_acquired
from tools.summary_grammar.runtime import (
    BUNDLE,
    BoundaryError,
    bundle,
    check_refs,
    clean_environment,
    digest,
    load,
    parse_json,
    reference,
    require,
    reviewed,
    run_owned,
    safe_path,
    write,
)


def encode_batch(rows):
    data = bytearray(b"SGE1" + struct.pack("<I", len(rows)))
    for row in rows:
        data += struct.pack("<I", {"dead": 0, "prefix": 1, "complete": 2}[row["expected"]])
        for value in (row["raw"], row["suffix"]):
            value.decode("utf-8", "strict")
            data += struct.pack("<I", len(value)) + value
    require(len(data) <= 2 * 1024**2, "batch_byte_limit")
    return bytes(data)


def protocol(data, rows):
    require(len(data) <= 8 * 1024**2, "protocol_bytes")
    text = data.decode("utf-8", "strict")
    require(text.endswith("\n"), "protocol_partial")
    parsed = [parse_json(line) for line in text.splitlines()]
    require(len(parsed) == len(rows) + 2, "protocol_count")
    header, tail = parsed[0], parsed[-1]
    require(set(header) == {"init_ms", "rules"} and type(header["rules"]) is int and 0 < header["rules"] <= 20000, "protocol_header")
    require(set(tail) == {"done", "clone_total_ms", "longest_ms", "total_ms"} and type(tail["done"]) is int and tail["done"] == len(rows), "protocol_done")
    for i, (actual, expected) in enumerate(zip(parsed[1:-1], rows, strict=True)):
        require(set(actual) == {"case", "state", "witness", "clone_ms", "elapsed_ms"} and type(actual["case"]) is int and actual["case"] == i, "protocol_order")
        require(actual["state"] in {"complete", "prefix", "dead"} and actual["state"] == expected["expected"], "verdict_mismatch")
        require(actual["witness"] == ("complete" if expected["suffix"] else None), "witness_mismatch")
    for row in parsed:
        for key, value in row.items():
            if key.endswith("_ms"):
                require(type(value) in (int, float) and math.isfinite(value) and 0 <= value < 55000, "protocol_time")
    return {"header": header, "cases": parsed[1:-1], "timing": tail}


def prior_absent(root, manifest, ps):
    receipts = []
    for ref in manifest["cleanup_receipts"]:
        check_refs(root, [ref])
        receipt = load(root / ref["file"])
        require(receipt["cleanup"]["all_absent"] and not receipt["cleanup"]["errors"], "prior_cleanup_failed")
        for pid, created, exe in receipt["cleanup"]["identities"]:
            try:
                proc = ps.Process(pid)
                require(proc.create_time() != created or os.path.normcase(str(Path(proc.exe()).resolve())) != exe, "prior_owned_process_live")
            except ps.NoSuchProcess:
                pass
        receipts.append(ref)
    return receipts


def verify(root, build_sha, result_name="engine-check", runner=run_owned, ps=None, clock=time.monotonic):
    root = Path(root).absolute()
    result = safe_path(root, result_name)
    require(not result.exists() and not (root / "native-issued.json").exists(), "native_once")
    manifest = reviewed(root / "build-manifest.json", build_sha)
    require(manifest["status"] == "BUILT_UNREVIEWED_NOT_ENGINE_VALIDATED", "build_contract")
    check_acquired(root, manifest["acquisition_sha256"])
    check_refs(root, [manifest["executable"], manifest["configure_trace"], *manifest["build_logs"]])
    rows, carrier = bundle()
    if ps is None:
        import psutil as ps
    prior_absent(root, manifest, ps)
    result.mkdir()
    try:
        batch = encode_batch(rows)
        (result / "batch.bin").write_bytes(batch)
        grammar = (BUNDLE / "candidate.gbnf").read_bytes()
        (result / "grammar.gbnf").write_bytes(grammar)
        executable = safe_path(root, manifest["executable"]["file"])
        deadline = clock() + 60
        write(root / "native-issued.json", {"reviewed_build_sha256": build_sha, "result": result_name,
              "batch_sha256": digest(batch), "grammar_sha256": digest(grammar), "native_cases": 105,
              "carrier_rejected": carrier, "expected_before_run": reference(BUNDLE / "expected.json", BUNDLE),
              "witnesses_before_run": reference(BUNDLE / "prefix-witnesses.json", BUNDLE), "retry": False})
        allowed = [executable]
        if "SystemRoot" in os.environ:
            allowed.append(Path(os.environ["SystemRoot"]) / "System32/conhost.exe")
        record = runner([executable, result / "grammar.gbnf", result / "batch.bin"], cwd=result,
                        env=clean_environment([executable.parent], root, result_name + "/tmp"), root=root, log_prefix=result / "engine",
                        deadline=deadline, rss=512 * 1024**2, host=2 * 1024**3, start=5 * 1024**3 // 2,
                        allowed=allowed, ps=ps, clock=clock)
        parsed = protocol((result / "engine.stdout").read_bytes(), rows)
        require(clock() <= deadline, "whole_batch_deadline")
        require((result / "batch.bin").read_bytes() == batch and (result / "grammar.gbnf").read_bytes() == grammar, "batch_input_changed")
        check_refs(root, [manifest["executable"]])
        bundle()
        result_data = {"status": "FINITE_ENGINE_CHECK_PASS_NOT_PRODUCT_ACCEPTANCE", "native_cases": len(rows),
                       "carrier_rejections": carrier, "total_manifest_cases": 106, "prefix_witnesses": 10,
                       "engine": parsed, "process": record, "reviewed_build_sha256": build_sha,
                       "model_tokenizer_calls": 0, "semantics_verified": False, "all_strings_equivalent": False,
                       "limit_scope": "sampled stop thresholds; not OS hard peak bounds"}
        write(result / "result.json", result_data)
        return result_data
    except Exception as error:
        write(result / "failure.json", {"status": "FAILED_NO_RETRY", "error": type(error).__name__,
              "reason": str(error), "partial_output_preserved": True, "model_calls": 0})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["carriers", "run"])
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--reviewed-build-sha256")
    parser.add_argument("--result-name", default="engine-check")
    args = parser.parse_args()
    if args.operation == "carriers":
        rows, carrier = bundle()
        print(json.dumps({"status": "CARRIERS_ONLY_ENGINE_NOT_RUN", "total": 106, "native_eligible": len(rows), "carrier_rejected": carrier, "prefix_witnesses": sum(bool(r["suffix"]) for r in rows)}))
    else:
        require(args.workspace is not None, "workspace_required")
        print(json.dumps({"status": verify(args.workspace, args.reviewed_build_sha256, args.result_name)["status"]}))


if __name__ == "__main__":
    try:
        main()
    except (BoundaryError, OSError, ValueError) as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        raise SystemExit(1) from error
