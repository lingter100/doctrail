"""Explicit opt-in asset download or offline verification; never launches a model."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.free_qa.assets import BoundaryError, profile, require, supervise, worker


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["inspect", "acquire", "verify-only", "_worker"])
    parser.add_argument("--root", type=Path)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--operation", choices=["acquire", "verify-only"], help=argparse.SUPPRESS)
    parser.add_argument("--token", help=argparse.SUPPRESS)
    parser.add_argument("--deadline", type=float, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.command == "inspect":
        require(not args.download, "inspect_never_downloads")
        spec = profile()
        result = {"status": "PROFILE_ONLY_ASSETS_NOT_READ", "profile_id": spec["id"],
                  "shard_bytes": spec["gguf"]["total_size_bytes"], "execution_approved": False}
    else:
        require(args.root is not None, "root_required")
        if args.command == "_worker":
            require(args.token and args.deadline is not None and args.operation and not args.download, "internal_worker_binding")
            result = worker(args.root, args.operation, args.token, args.deadline)
        else:
            require(args.operation is None and args.token is None and args.deadline is None, "no_worker_override")
            result = supervise(args.root, args.command, allow_download=args.download)
    print(json.dumps({"status": result["status"], "execution_approved": False}))


if __name__ == "__main__":
    try:
        main()
    except (BoundaryError, OSError, ValueError) as error:
        print(type(error).__name__ + ":" + str(error), file=sys.stderr)
        raise SystemExit(1) from error
