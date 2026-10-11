"""DraftJobRunner: job failures must land in the logs, not just job state."""

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

    async def boom(progress) -> None:
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

    async def boom(progress) -> None:
        raise RuntimeError("kaboom")

    runner = DraftJobRunner()
    with capture_logs() as logs:
        runner.submit(boom)
        _wait_done(runner, [jid for jid in runner.jobs][0])
    entry = next(e for e in logs if e["event"] == "drafting.job_failed")
    assert entry["log_level"] == "error" and entry["code"] == "INTERNAL_ERROR"


def test_successful_job_logs_done_event() -> None:
    """Completion logs as well — timeline reconstruction needs both ends."""

    async def fine(progress) -> str:
        return "ttl"

    runner = DraftJobRunner()
    with capture_logs() as logs:
        runner.submit(fine)
        _wait_done(runner, [jid for jid in runner.jobs][0])
    assert any(e["event"] == "drafting.job_done" for e in logs)
