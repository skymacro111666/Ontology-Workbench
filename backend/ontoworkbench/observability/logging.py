"""structlog config: JSON lines to stdout + daily-rotated file (15 kept)."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

import structlog


def setup_logging(log_dir: Path, level: str = "INFO") -> None:
    """Idempotent logging setup with dual sinks (stdout + rotating file)."""
    log_dir.mkdir(parents=True, exist_ok=True)
    rotating = logging.handlers.TimedRotatingFileHandler(
        log_dir / "ow-server.log", when="midnight", backupCount=15, encoding="utf-8"
    )
    # StreamHandler defaults to stderr; spec mandates stdout as the first sink
    stream = logging.StreamHandler(stream=sys.stdout)
    for h in (stream, rotating):
        h.setFormatter(logging.Formatter("%(message)s"))
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
