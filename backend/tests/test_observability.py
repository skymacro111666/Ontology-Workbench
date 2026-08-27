"""Alembic log lines must render in the app's JSON envelope (unified format)."""

import json
import logging

from ontoworkbench.observability.logging import AlembicJsonFilter


def make_record(name: str, msg: str, args: tuple | None = None) -> logging.LogRecord:
    """Synthesize a stdlib record the way a logger.info() call would."""
    return logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


def test_alembic_records_wrapped_as_json_envelope() -> None:
    """Records from alembic loggers come out as one JSON envelope line."""
    f = AlembicJsonFilter("db.migrate")
    rec = make_record("alembic.runtime.migration", "Context impl %s.", ("SQLiteImpl",))
    assert f.filter(rec) is True

    payload = json.loads(rec.getMessage())  # args cleared → getMessage is plain JSON
    assert payload["message"] == "Context impl SQLiteImpl."
    assert payload["event"] == "db.migrate"
    assert payload["level"] == "info"
    assert "timestamp" in payload


def test_non_alembic_records_left_alone() -> None:
    """Records from other loggers keep their message untouched."""
    f = AlembicJsonFilter("db.migrate")
    rec = make_record("ow.access", "http.request")
    assert f.filter(rec) is True
    assert rec.getMessage() == "http.request"


def test_no_double_wrap_when_handler_chain_sees_record_twice() -> None:
    """Two handlers share one filter instance; wrap happens exactly once."""
    f = AlembicJsonFilter("db.migrate")
    rec = make_record("alembic.runtime.migration", "Running upgrade 0002 -> 0003")
    f.filter(rec)
    once = rec.getMessage()
    f.filter(rec)
    assert rec.getMessage() == once
