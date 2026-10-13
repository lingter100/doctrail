"""Real CPU child process check; never loads a model or opens a GPU device."""
import multiprocessing
import time

import pytest

from scripts.evaluate_generation_smoke import SmokeError, await_event, stop_owned_worker


def _blocked_worker(connection):
    connection.send({"event": "ready"})
    time.sleep(60)


def test_watchdog_terminates_real_owned_process():
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_blocked_worker, args=(child,))
    process.start()
    child.close()
    pid = process.pid
    try:
        assert await_event(parent, process, 15, "ready")["event"] == "ready"
        with pytest.raises(SmokeError, match="watchdog_generated_timeout"):
            await_event(parent, process, 0.1, "generated")
    finally:
        stop_owned_worker(process, parent)
        parent.close()
    assert pid not in {child.pid for child in multiprocessing.active_children()}
