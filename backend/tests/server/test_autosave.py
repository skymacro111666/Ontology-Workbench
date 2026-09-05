"""AutosaveManager: debounce coalescing, retry backoff, flush-on-shutdown."""

from __future__ import annotations

import time

from ontoworkbench.server.autosave import AutosaveManager


def test_debounce_coalesces_and_runs_once() -> None:
    """Five rapid schedules coalesce into one saver run, then return to idle."""
    m = AutosaveManager(debounce_s=0.05)
    calls = []
    for _ in range(5):
        m.schedule("o1", lambda: calls.append(1))
    time.sleep(0.3)
    assert calls == [1]
    assert m.state("o1") == "idle"


def test_failure_retries_with_backoff_then_failed() -> None:
    """A failing saver retries with backoff, then parks in failed state."""
    n = [0]

    def boom() -> None:
        n[0] += 1
        raise RuntimeError("disk")

    m = AutosaveManager(debounce_s=0.01, retry_base=0.01)
    m.schedule("o1", boom)
    time.sleep(0.5)
    assert n[0] == 5 and m.state("o1") == "failed"


def test_flush_all_runs_pending_now() -> None:
    """flush_all bypasses the debounce and lands pending savers immediately."""
    m = AutosaveManager(debounce_s=30.0)
    ran = []
    m.schedule("o1", lambda: ran.append(1))
    m.flush_all()
    assert ran == [1]
