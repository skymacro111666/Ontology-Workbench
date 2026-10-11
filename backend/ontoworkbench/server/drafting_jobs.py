"""In-memory draft job runner (spec §5.3): thread per job, polled via GET.

Generate jobs outlive their HTTP request: submit() spawns a daemon thread
running its own event loop (asyncio.run) and returns a job id immediately;
the wizard polls GET /drafting/jobs/{id} for batch progress. Entries are
process-local scratch — swept lazily one hour after creation.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import structlog

from ontoworkbench.core.errors import CoreError

JOB_TTL_S = 3600

# Job failures must leave a log trail: the 2026-10-11 truncation incident
# was only diagnosable by hand-reproducing the whole pipeline because the
# runner recorded failures in job state alone.
_log = structlog.get_logger("ow.audit")


class DraftJobRunner:
    """Owns the job dicts; mounted at app.state.draft_jobs."""

    def __init__(self) -> None:
        """Start empty; jobs arrive only via submit."""
        self.jobs: dict[str, dict[str, Any]] = {}

    def submit(self, coro_factory: Callable[[Callable[[int, int], None]], Any]) -> str:
        """Run coro_factory(progress) in a background thread; return the job id."""
        self._sweep()
        job_id = uuid.uuid4().hex
        job: dict[str, Any] = {
            "status": "running",
            "batch": 0,
            "batchCount": 0,
            "result": None,
            "code": None,
            "message": None,
            "created": time.time(),
        }
        self.jobs[job_id] = job

        def progress(k: int, n: int) -> None:
            job["batch"] = k
            job["batchCount"] = n

        def run() -> None:
            try:
                result = asyncio.run(coro_factory(progress))
            except CoreError as e:
                job.update(status="failed", code=str(e.code), message=e.message)
                _log.error(
                    "drafting.job_failed",
                    job_id=job_id,
                    code=str(e.code),
                    message=e.message,
                    hint=e.hint,
                )
            except Exception as e:  # noqa: BLE001 - job isolation: the thread survives
                job.update(status="failed", code="INTERNAL_ERROR", message=str(e)[:500])
                _log.error(
                    "drafting.job_failed",
                    job_id=job_id,
                    code="INTERNAL_ERROR",
                    message=str(e)[:500],
                    error=type(e).__name__,
                )
            else:
                job.update(status="done", result=result)
                _log.info("drafting.job_done", job_id=job_id)

        threading.Thread(target=run, daemon=True, name=f"draft-job-{job_id[:8]}").start()
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        """The job dict, or None when unknown or already swept."""
        return self.jobs.get(job_id)

    def _sweep(self) -> None:
        """Drop entries older than the TTL (lazy: only submit pays for it)."""
        cutoff = time.time() - JOB_TTL_S
        stale = [jid for jid, j in self.jobs.items() if j["created"] < cutoff]
        for jid in stale:
            del self.jobs[jid]
