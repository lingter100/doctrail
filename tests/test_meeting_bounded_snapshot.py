import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from doctrail.meeting_bounded_snapshot import BYTE_LIMIT, CHUNK_BYTES, Meter, read_snapshot


@pytest.mark.parametrize("size", [0, 1, 65535, 65536, 65537, BYTE_LIMIT-1,
                                  BYTE_LIMIT, BYTE_LIMIT+1, BYTE_LIMIT+2])
def test_regular_sizes_same_bytes_stamp_or_overflow(tmp_path, size):
    target = tmp_path / "payload.bin"
    raw = b"q" * size
    target.write_bytes(raw)
    meters, results = [], []
    for candidate in (False, True):
        meter = Meter()
        meters.append(meter)
        if size > BYTE_LIMIT:
            with pytest.raises(ValueError, match="preparation_file_limit"):
                read_snapshot(target, meter, candidate=candidate)
        else:
            results.append(read_snapshot(target, meter, candidate=candidate))
        assert meter.counts["actual_read_returned_bytes"] == min(size, BYTE_LIMIT+1)
    assert not results or results[0] == results[1] == (raw, results[0][1])
    assert list(meters[0].read_requested_lengths) == [str(BYTE_LIMIT+1)]
    assert max(map(int, meters[1].read_requested_lengths)) <= CHUNK_BYTES


class ShortRaw(io.RawIOBase):
    def __init__(self, raw, fail_at=None):
        super().__init__()
        self.raw, self.position, self.fail_at = raw, 0, fail_at

    def readable(self):
        return True

    def readinto(self, buffer):
        if self.fail_at is not None and self.position >= self.fail_at:
            raise OSError("private path must not enter safe report")
        length = min(len(buffer), 1031, len(self.raw)-self.position)
        if self.fail_at is not None:
            length = min(length, self.fail_at-self.position)
        buffer[:length] = self.raw[self.position:self.position+length]
        self.position += length
        return length


class StreamPath:
    def __init__(self, factory, changing=False):
        self.factory, self.changing, self.stats = factory, changing, 0

    def open(self, mode):
        assert mode == "rb"
        return self.factory()

    def stat(self):
        self.stats += 1
        return SimpleNamespace(st_dev=1, st_ino=2, st_size=1, st_mtime_ns=3,
                               st_ctime_ns=self.stats if self.changing else 4)


def test_independent_buffered_short_raw_streams():
    raw = b"abc" * 50001
    results = [read_snapshot(StreamPath(lambda: io.BufferedReader(ShortRaw(raw))), Meter(),
                             candidate=arm) for arm in (False, True)]
    assert results[0] == results[1]
    assert results[0][0] == raw


def test_direct_nonempty_short_reads_continue():
    class ShortBytes(io.BytesIO):
        def read(self, length):
            return super().read(min(length, 7))
    meter = Meter()
    raw, _ = read_snapshot(StreamPath(lambda: ShortBytes(b"a" * 31)), meter, candidate=True)
    assert raw == b"a" * 31
    assert meter.counts["read_calls"] == 6


def test_error_at_common_raw_position_preserves_different_partial_counts():
    counts = []
    for candidate in (False, True):
        meter = Meter()
        with pytest.raises(OSError):
            read_snapshot(StreamPath(lambda: io.BufferedReader(ShortRaw(b"a" * 200000, 131072))),
                          meter, candidate=candidate)
        counts.append(meter.counts["actual_read_returned_bytes"])
        assert meter.counts["close_calls"] == 1
    assert counts == [0, 131072]


@pytest.mark.parametrize("value", [None, "bad", bytearray(b"a"), b"x" * 65537],
                         ids=["none", "text", "bytearray", "overreturn"])
def test_invalid_candidate_stream_return_is_not_eof(value):
    class Invalid(io.BytesIO):
        def read(self, length):
            return value
    with pytest.raises(ValueError, match="preparation_stream_contract"):
        read_snapshot(StreamPath(Invalid), Meter(), candidate=True)


@pytest.mark.parametrize("candidate", [False, True])
def test_stamp_change_and_overflow_precedence(candidate):
    with pytest.raises(ValueError, match="preparation_snapshot_changed"):
        read_snapshot(StreamPath(lambda: io.BytesIO(b"a"), changing=True), Meter(), candidate=candidate)
    target = StreamPath(lambda: io.BytesIO(b"a" * (BYTE_LIMIT+1)), changing=True)
    with pytest.raises(ValueError, match="preparation_file_limit"):
        read_snapshot(target, Meter(), candidate=candidate)
    assert target.stats == 1


@pytest.mark.parametrize("candidate", [False, True])
def test_close_failure_never_accepts_partial_bytes(candidate):
    class BadClose(io.BytesIO):
        def __exit__(self, *args):
            super().__exit__(*args)
            raise OSError("close")
    meter = Meter()
    with pytest.raises(OSError, match="close"):
        read_snapshot(StreamPath(lambda: BadClose(b"abc")), meter, candidate=candidate)
    assert meter.counts["actual_read_returned_bytes"] == 3
    assert meter.counts["stat_calls"] == 1


@pytest.mark.parametrize("candidate", [False, True])
def test_mid_read_mutation_detected_and_returned_bytes_counted(tmp_path, candidate):
    target = tmp_path / "mutable"
    target.write_bytes(b"abc")

    class MutatingPath:
        def stat(self):
            return target.stat()

        def open(self, mode):
            class Stream(io.BytesIO):
                def read(self, length):
                    raw = super().read(length)
                    target.write_bytes(b"changed-size")
                    return raw
            return Stream(b"abc")
    meter = Meter()
    with pytest.raises(ValueError, match="preparation_snapshot_changed"):
        read_snapshot(MutatingPath(), meter, candidate=candidate)
    assert meter.counts["actual_read_returned_bytes"] == 3


def test_reference_is_frozen_function_not_reimplementation():
    from doctrail import meeting_bounded_snapshot as reader
    from scripts.prepare_meeting_budget_inputs import snapshot
    assert reader.snapshot is snapshot
    assert Path(snapshot.__code__.co_filename).name == "prepare_meeting_budget_inputs.py"
