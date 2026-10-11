"""DraftJobRunner: job failures must land in the logs, not just job state."""

import asyncio
import time

from structlog.testing import capture_logs

from ontoworkbench.core.errors import CoreError
from ontoworkbench.server.drafting_jobs import DraftJobRunner


def _wait_done(runner: DraftJobRunner, job_id: str) -> dict:
    """Poll the job dict until the thread settles (it is async by design)."""
    deadline = time.time() + 5
    while time.time() < deadline:
        job = runner.get(job_id)
        assert job is not None
        if job["status"] != "running":
            return job
        time.sleep(0.01)
    raise AssertionError("job did not settle in 5s")


def test_failed_core_error_job_logs_error_event() -> None:
    """A CoreError failure records code/message/hint in an error-level log.

    The 2026-10-11 drafting incident left no log trail at all.
    """

    async def boom(progress, cancelled) -> None:
        raise CoreError("LLM_OUTPUT_INVALID", "bad output", hint="det")

    runner = DraftJobRunner()
    with capture_logs() as logs:
        job_id = runner.submit(boom)
        job = _wait_done(runner, job_id)

    assert job["status"] == "failed" and job["code"] == "LLM_OUTPUT_INVALID"
    entry = next(e for e in logs if e["event"] == "drafting.job_failed")
    assert entry["log_level"] == "error"
    assert entry["code"] == "LLM_OUTPUT_INVALID" and entry["hint"] == "det"
    assert entry["job_id"] == job_id


def test_unexpected_exception_job_logs_error_event() -> None:
    """Non-CoreError failures log too (INTERNAL_ERROR path)."""

    async def boom(progress, cancelled) -> None:
        raise RuntimeError("kaboom")

    runner = DraftJobRunner()
    with capture_logs() as logs:
        runner.submit(boom)
        _wait_done(runner, [jid for jid in runner.jobs][0])
    entry = next(e for e in logs if e["event"] == "drafting.job_failed")
    assert entry["log_level"] == "error" and entry["code"] == "INTERNAL_ERROR"


def test_successful_job_logs_done_event() -> None:
    """Completion logs as well — timeline reconstruction needs both ends."""

    async def fine(progress, cancelled) -> str:
        return "ttl"

    runner = DraftJobRunner()
    with capture_logs() as logs:
        runner.submit(fine)
        _wait_done(runner, [jid for jid in runner.jobs][0])
    assert any(e["event"] == "drafting.job_done" for e in logs)


def test_cancelled_job_settles_as_cancelled_with_info_log() -> None:
    """Abandon is intentional, not a failure.

    The cooperative factory sees the flag, raises DRAFT_CANCELLED, and the
    job lands status=cancelled with an info-level event (error logs stay
    for real failures).
    """

    async def cooperative(progress, cancelled) -> None:
        for _ in range(500):
            if cancelled():
                raise CoreError("DRAFT_CANCELLED", "draft cancelled by user")
            await asyncio.sleep(0.01)

    runner = DraftJobRunner()
    with capture_logs() as logs:
        job_id = runner.submit(cooperative)
        time.sleep(0.05)  # let the loop spin up
        assert runner.cancel(job_id) is True
        job = _wait_done(runner, job_id)

    assert job["status"] == "cancelled"
    assert job["code"] is None
    entry = next(e for e in logs if e["event"] == "drafting.job_cancelled")
    assert entry["log_level"] == "info"
    assert not any(e["event"] == "drafting.job_failed" for e in logs)


def test_cancel_is_false_for_unknown_or_settled_jobs() -> None:
    """Cancelling an unknown id or an already-settled job changes nothing."""

    async def fine(progress, cancelled) -> str:
        return "x"

    runner = DraftJobRunner()
    assert runner.cancel("missing") is False
    jid = runner.submit(fine)
    _wait_done(runner, jid)
    assert runner.cancel(jid) is False
    assert runner.get(jid)["status"] == "done"
