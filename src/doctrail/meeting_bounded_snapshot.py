"""64 KiB reader experiment; unchanged original snapshot is the reference.

Only regular blocking binary streams are supported. Counters describe Python
calls and returned bytes, not allocator, RSS, prefetch, or physical disk I/O.
"""
from __future__ import annotations

from collections import Counter

from scripts.prepare_meeting_budget_inputs import BYTE_LIMIT, PreparationError, snapshot, stamp

CHUNK_BYTES = 65536


class Meter:
    def __init__(self):
        self.counts = Counter({name: 0 for name in (
            "snapshot_calls", "stat_calls", "open_calls", "read_calls", "close_calls",
            "actual_read_returned_bytes", "hash_calls", "hash_bytes", "ast_parse_calls",
            "json_parse_calls", "path_checks", "alias_checks", "candidate_checks",
            "head_checks", "write_calls", "write_returned_bytes", "fsync_calls",
            "replace_calls")})
        self.read_requested_lengths = Counter()
        self.git = []

    def export(self):
        return {"counts": dict(self.counts),
                "read_requested_lengths": dict(sorted(self.read_requested_lengths.items())),
                "git": list(self.git)}


class ObservedStream:
    def __init__(self, stream, meter):
        self.stream, self.meter = stream, meter

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        self.meter.counts["close_calls"] += 1
        return self.stream.__exit__(*args)

    def read(self, length):
        self.meter.counts["read_calls"] += 1
        self.meter.read_requested_lengths[str(length)] += 1
        raw = self.stream.read(length)
        if isinstance(raw, bytes):
            self.meter.counts["actual_read_returned_bytes"] += len(raw)
        if not isinstance(raw, bytes) or len(raw) > length:
            raise PreparationError("preparation_stream_contract")
        return raw


class ObservedPath:
    """Explicit forwarding adapter; never changes modules, globals, or builtins."""
    def __init__(self, target, meter):
        self.target, self.meter = target, meter

    def stat(self):
        self.meter.counts["stat_calls"] += 1
        return self.target.stat()

    def open(self, mode):
        self.meter.counts["open_calls"] += 1
        return ObservedStream(self.target.open(mode), self.meter)


def read_snapshot(target, meter, *, candidate=False):
    meter.counts["snapshot_calls"] += 1
    observed = ObservedPath(target, meter)
    if not candidate:
        return snapshot(observed)
    before = stamp(observed)
    chunks, total = [], 0
    with observed.open("rb") as stream:
        while total < BYTE_LIMIT + 1:
            raw = stream.read(min(CHUNK_BYTES, BYTE_LIMIT + 1 - total))
            if not raw:
                break
            chunks.append(raw)
            total += len(raw)
    raw = b"".join(chunks)
    if len(raw) > BYTE_LIMIT:
        raise PreparationError("preparation_file_limit")
    if stamp(observed) != before:
        raise PreparationError("preparation_snapshot_changed")
    return raw, before
