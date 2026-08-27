"""Third-party log lines must render in the app's JSON envelope (unified format)."""

import json
import logging

from ontoworkbench.observability.logging import JsonEnvelopeFilter

FILTER = JsonEnvelopeFilter({"alembic": "db.migrate", "uvicorn": "server.uvicorn"})


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
    rec = make_record("alembic.runtime.migration", "Context impl %s.", ("SQLiteImpl",))
    assert FILTER.filter(rec) is True

    payload = json.loads(rec.getMessage())  # args cleared → getMessage is plain JSON
    assert payload["message"] == "Context impl SQLiteImpl."
    assert payload["event"] == "db.migrate"
    assert payload["level"] == "info"
    assert "timestamp" in payload


def test_uvicorn_records_wrapped_as_json_envelope() -> None:
    """Lifecycle lines from uvicorn.error get the server.uvicorn event tag."""
    rec = make_record("uvicorn.error", "Uvicorn running on http://127.0.0.1:8734")
    assert FILTER.filter(rec) is True

    payload = json.loads(rec.getMessage())
    assert payload["message"] == "Uvicorn running on http://127.0.0.1:8734"
    assert payload["event"] == "server.uvicorn"


def test_unmapped_records_left_alone() -> None:
    """Records from loggers outside the mapping keep their message untouched."""
    rec = make_record("ow.access", "http.request")
    assert FILTER.filter(rec) is True
    assert rec.getMessage() == "http.request"


def test_prefix_must_not_swallow_similar_names() -> None:
    """A logger merely starting with a mapped prefix text is not matched."""
    rec = make_record("uvicornx.core", "looks like uvicorn but is not")
    assert FILTER.filter(rec) is True
    assert rec.getMessage() == "looks like uvicorn but is not"


def test_no_double_wrap_when_handler_chain_sees_record_twice() -> None:
    """Two handlers share one filter instance; wrap happens exactly once."""
    rec = make_record("alembic.runtime.migration", "Running upgrade 0002 -> 0003")
    FILTER.filter(rec)
    once = rec.getMessage()
    FILTER.filter(rec)
    assert rec.getMessage() == once
