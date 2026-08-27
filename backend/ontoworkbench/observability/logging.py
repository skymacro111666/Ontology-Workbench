"""structlog config: JSON lines to stdout + daily-rotated file (15 kept)."""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from pathlib import Path

import structlog


class AlembicJsonFilter(logging.Filter):
    """Re-encode third-party alembic lines as the app's JSON envelope.

    Alembic logs plain strings through stdlib logging; the app's JSON shape
    comes from structlog's processor chain, which alembic never enters.
    Attached at handler level (logger-level filters miss records propagating
    from child loggers like ``alembic.runtime.migration``); a marker flag
    keeps the wrap idempotent when both handlers share one filter instance.
    """

    def __init__(self, event: str) -> None:
        """Remember the envelope's event tag (e.g. ``db.migrate``)."""
        super().__init__()
        self.event = event

    def filter(self, record: logging.LogRecord) -> bool:
        """Wrap alembic-origin records in-place; pass everything else through."""
        if not (record.name == "alembic" or record.name.startswith("alembic.")):
            return True
        if getattr(record, "ow_json_wrapped", False):
            return True
        payload = {
            "message": record.getMessage(),
            "event": self.event,
            "level": record.levelname.lower(),
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        record.msg = json.dumps(payload, ensure_ascii=False)
        record.args = None  # JSON may contain %; never re-apply %-formatting
        record.ow_json_wrapped = True
        return True


def setup_logging(log_dir: Path, level: str = "INFO") -> None:
    """Idempotent logging setup with dual sinks (stdout + rotating file)."""
    log_dir.mkdir(parents=True, exist_ok=True)
    rotating = logging.handlers.TimedRotatingFileHandler(
        log_dir / "ow-server.log", when="midnight", backupCount=15, encoding="utf-8"
    )
    # StreamHandler defaults to stderr; spec mandates stdout as the first sink
    stream = logging.StreamHandler(stream=sys.stdout)
    alembic_json = AlembicJsonFilter("db.migrate")
    for h in (stream, rotating):
        h.setFormatter(logging.Formatter("%(message)s"))
        h.addFilter(alembic_json)
    logging.basicConfig(level=level.upper(), handlers=[stream, rotating], force=True)
    # Our JSON access log replaces these libraries' own request logging;
    # keep their non-request chatter below INFO so stdout stays clean.
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
