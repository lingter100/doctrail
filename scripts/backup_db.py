"""Consistent SQLite backup; restore only into a new path and invalidate sessions."""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path


def copy_database(source: Path, output: Path, *, restore: bool = False) -> None:
    if not source.is_file():
        raise ValueError("source database does not exist")
    if output.exists() or source.resolve() == output.resolve():
        raise ValueError("output must be a new database path")
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as original,
        closing(sqlite3.connect(output)) as copied,
        copied,
    ):
        original.backup(copied)
        result = copied.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError("backup integrity check failed")
        if restore:
            copied.execute("DELETE FROM sessions")
    print("restore_copy_verified" if restore else "backup_verified")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    copy_database(args.source, args.output, restore=args.restore)
