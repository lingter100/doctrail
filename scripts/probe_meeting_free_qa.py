"""Metadata-only verify or explicitly assigned free-QA run. No overrides or downloads."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("verify", "run"):
        command = sub.add_parser(name)
        command.add_argument("--registration", type=Path, required=True)
        command.add_argument("--sha256", required=True)
        if name == "run":
            command.add_argument("--once", required=True)
    args = parser.parse_args(argv)
    from tools.free_qa.runner import load_registration, run_epoch, safe_error
    try:
        if args.command == "verify":
            _spec, verified, epoch, _, _ = load_registration(args.registration, args.sha256)
            result = {"status": "METADATA_VERIFIED_NO_ASSETS_OR_EXECUTION", "epoch": epoch.name,
                      "contract_sha256": verified.contract.sha256, "execution_approved": False}
        else:
            report = run_epoch(args.registration, args.sha256, args.once)
            result = {key: report[key] for key in ("status", "epoch", "registration_sha256", "once_sha256", "AI_quality")}
        print(json.dumps(result))
        return 0 if args.command == "verify" or result["status"] == "completed" else 1
    except Exception as error:  # noqa: BLE001 - safe CLI terminal without private exception text
        print(json.dumps({"status": "FAILED_CLOSED", "error": safe_error(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
