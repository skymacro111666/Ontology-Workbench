"""Y-axis debounced flushing: mutations stay in memory; files land in quiet periods."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from ontoworkbench.observability.metrics import ow_autosave_total

logger = logging.getLogger(__name__)


class AutosaveManager:
    """One debounce timer per ontology; one global writer thread serializes all saves.

    The saver closure captures its mutation's store/prefixes/row; a later
    schedule supersedes earlier ones (memory state only moves forward).
    Failures retry with retry_base*2^n backoff; after max_retries the oid
    parks in "failed" until the next edit schedules again.
    """

    def __init__(
        self, debounce_s: float = 3.0, retry_base: float = 1.0, max_retries: int = 4
    ) -> None:
        """Arm per-oid timers around one shared writer thread."""
        self._debounce_s = debounce_s
        self._retry_base = retry_base
        self._max_retries = max_retries
        self._timers: dict[str, threading.Timer] = {}
        self._savers: dict[str, Callable[[], None]] = {}
        self._states: dict[str, str] = {}
        self._guard = threading.Lock()
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ow-autosave")

    def schedule(self, oid: str, saver: Callable[[], None]) -> None:
        """(Re)arm this ontology's debounce timer; latest saver wins."""
        with self._guard:
            self._savers[oid] = saver
            self._states[oid] = "pending"
            old = self._timers.pop(oid, None)
            timer = threading.Timer(self._debounce_s, self._fire, args=(oid, 0))
            self._timers[oid] = timer
        if old is not None:
            old.cancel()
        timer.start()

    def _fire(self, oid: str, attempt: int) -> None:
        try:
            self._writer.submit(self._save, oid, attempt)
        except RuntimeError:  # flush_all 已关停 executor:迟到的计时器无害丢弃
            pass

    def _save(self, oid: str, attempt: int) -> None:
        with self._guard:
            if attempt == 0:
                self._timers.pop(oid, None)
            saver = self._savers.get(oid)
            if saver is None:
                return
            self._states[oid] = "saving"
        try:
            saver()
        except Exception:
            logger.exception("autosave failed oid=%s attempt=%d", oid, attempt)
            ow_autosave_total.labels("failed").inc()
            if attempt >= self._max_retries:
                with self._guard:
                    # saver 留到终态才弹出:attempt 0 就弹会让重试找不到它。
                    # 仅当未被更新的 schedule 覆盖时才弹(后到者必须胜出)。
                    if self._savers.get(oid) is saver:
                        self._savers.pop(oid)
                    self._states[oid] = "failed"
                return
            delay = self._retry_base * (2**attempt)
            timer = threading.Timer(delay, self._fire, args=(oid, attempt + 1))
            with self._guard:
                self._timers[oid] = timer
            timer.start()
            return
        ow_autosave_total.labels("saved").inc()
        with self._guard:
            if self._savers.get(oid) is saver:  # 保存期间有新 schedule 则保留新 saver
                self._savers.pop(oid)
            if self._states.get(oid) != "pending":  # 保存期间无新编辑才算干净落地
                self._states[oid] = "idle"

    def state(self, oid: str) -> str:
        """One of idle|pending|saving|failed; unknown oids read as idle."""
        return self._states.get(oid, "idle")

    def flush_all(self) -> None:
        """Shutdown hook: run every unflushed saver now (graceful exit, zero loss)."""
        with self._guard:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
            pending = [(oid, saver) for oid, saver in self._savers.items()]
            self._savers.clear()
        for _oid, saver in pending:
            self._writer.submit(saver)
        self._writer.shutdown(wait=True)
