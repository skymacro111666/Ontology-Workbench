"""structlog config: JSON lines to stdout + daily-rotated file (15 kept)."""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import structlog

# Service identity on every line (observability spec §1): which service,
# which build, which log schema — so aggregated lines are attributable.
SERVICE_NAME = "ontology-workbench"
try:
    SERVICE_VERSION = metadata.version(SERVICE_NAME)
except metadata.PackageNotFoundError:  # running from a source tree
    SERVICE_VERSION = "dev"


def add_service_fields(logger, method_name: str, event_dict: dict) -> dict:
    """Structlog processor: stamp service identity onto every event.

    setdefault so a caller that deliberately overrides (e.g. a future
    schema_version bump on one event) keeps its value.
    """
    event_dict.setdefault("service", SERVICE_NAME)
    event_dict.setdefault("service_version", SERVICE_VERSION)
    event_dict.setdefault("schema_version", 1)
    return event_dict


def drop_nones(logger, method_name: str, event_dict: dict) -> dict:
    """Omit absent fields entirely rather than emitting null placeholders.

    Spec §2: a missing key reads as "not applicable", null as "unknown".
    """
    return {k: v for k, v in event_dict.items() if v is not None}


class JsonEnvelopeFilter(logging.Filter):
    """Re-encode third-party plain-text lines as the app's JSON envelope.

    Libraries like alembic and uvicorn log plain strings through stdlib
    logging; the app's JSON shape comes from structlog's processor chain,
    which they never enter. Attached at handler level (logger-level filters
    miss records propagating from child loggers like
    ``alembic.runtime.migration``); a marker flag keeps the wrap idempotent
    when both handlers share one filter instance.
    """

    def __init__(self, events: dict[str, str]) -> None:
        """Map logger-name prefixes (e.g. ``alembic``) to event tags."""
        super().__init__()
        self.events = events

    def _event_for(self, name: str) -> str | None:
        """Return the event tag for a logger name, or None if unmapped."""
        for prefix, event in self.events.items():
            if name == prefix or name.startswith(prefix + "."):
                return event
        return None

    def filter(self, record: logging.LogRecord) -> bool:
        """Wrap records from mapped logger families in-place; pass the rest."""
        event = self._event_for(record.name)
        if event is None or getattr(record, "ow_json_wrapped", False):
            return True
        payload = {
            "message": record.getMessage(),
            "event": event,
            "service": SERVICE_NAME,
            "service_version": SERVICE_VERSION,
            "schema_version": 1,
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
    envelope = JsonEnvelopeFilter({"alembic": "db.migrate", "uvicorn": "server.uvicorn"})
    for h in (stream, rotating):
        h.setFormatter(logging.Formatter("%(message)s"))
        h.addFilter(envelope)
    logging.basicConfig(level=level.upper(), handlers=[stream, rotating], force=True)
    # Our JSON access log replaces these libraries' own request logging;
    # keep their non-request chatter below INFO so stdout stays clean.
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            add_service_fields,
            drop_nones,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
