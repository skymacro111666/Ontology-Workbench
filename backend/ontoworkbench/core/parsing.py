"""Parsing + format sniffing (extension first, content fallback).

parse_store/serialize_store are the engine; the rdflib parse_graph family
below is the migration-window oracle pending removal (plan 2026-09-03).
"""

from __future__ import annotations

import time
from typing import cast

import pyoxigraph as ox
import rdflib

from ontoworkbench.core.errors import CoreError
from ontoworkbench.core.prefixes import PrefixMap

XSD_NS = "http://www.w3.org/2001/XMLSchema#"


class ParseError(CoreError):
    """Raised for unsupported formats or syntax errors (code/message/hint)."""


_EXT_MAP = {
    ".ttl": "turtle",
    ".turtle": "turtle",
    ".n3": "turtle",
    ".owl": "rdfxml",
    ".rdf": "rdfxml",
    ".xml": "rdfxml",
    ".jsonld": "jsonld",
    ".json": "jsonld",
}
_RDFFORMAT = {"turtle": "turtle", "rdfxml": "xml", "jsonld": "json-ld"}


def sniff_format(filename: str, head: bytes) -> str:
    """Decide turtle/rdfxml/jsonld from extension, else probe content."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in _EXT_MAP:
        return _EXT_MAP[ext]
    text = head[:2048].lstrip()
    # JSON-LD always starts with { or [ (a truncated head must not fall through)
    if text.startswith(b"{") or text.startswith(b"["):
        return "jsonld"
    if text.startswith(b"<"):
        return "rdfxml"
    if b"prefix" in text or b":" in text.split(b"\n")[0]:
        return "turtle"
    raise ParseError(
        "UNSUPPORTED_FORMAT",
        "Cannot detect a supported RDF format",
        "Supported: Turtle (.ttl), RDF-XML (.owl/.rdf), JSON-LD (.jsonld)",
    )


def parse_graph(data: bytes, fmt: str) -> rdflib.Graph:
    """Parse bytes into a Graph; wrap syntax errors with the parser's detail.

    Deprecated: rdflib path, kept only for pre-Store callers (M2 removal);
    new code should use parse_store.
    """
    g = rdflib.Graph()
    try:
        g.parse(data=data, format=_RDFFORMAT[fmt])
    except Exception as exc:  # rdflib raises many parser-specific types
        raise ParseError("PARSE_FAILED", f"Syntax error: {exc}") from exc
    return g


def serialize_graph(graph: rdflib.Graph, fmt: str) -> bytes:
    """Serialize a Graph back to bytes in the stored format (A2 writes)."""
    try:
        return graph.serialize(format=_RDFFORMAT[fmt]).encode("utf-8")
    except Exception as exc:
        raise ParseError("PARSE_FAILED", f"Serialization error: {exc}") from exc


def timed_parse(data: bytes, fmt: str) -> tuple[rdflib.Graph, float]:
    """parse_graph plus wall-clock duration in milliseconds (for meta)."""
    start = time.perf_counter()
    graph = parse_graph(data, fmt)
    return graph, (time.perf_counter() - start) * 1000.0


_OX_FORMAT = {
    "turtle": ox.RdfFormat.TURTLE,
    "rdfxml": ox.RdfFormat.RDF_XML,
    "jsonld": ox.RdfFormat.JSON_LD,
}


def parse_store(data: bytes, fmt: str) -> tuple[ox.Store, PrefixMap]:
    """Parse bytes into an in-memory pyoxigraph Store (default graph) + prefixes.

    Unknown format names raise UNSUPPORTED_FORMAT; parser failures raise
    PARSE_FAILED with ox's detail (SyntaxError/ValueError/OSError mapped).
    """
    fmt_enum = _OX_FORMAT.get(fmt)
    if fmt_enum is None:
        raise ParseError(
            "UNSUPPORTED_FORMAT",
            f"Unsupported format '{fmt}'",
            "Supported: turtle, rdfxml, jsonld",
        )
    store = ox.Store()
    try:
        store.load(input=data, format=fmt_enum, to_graph=ox.DefaultGraph())
    except SyntaxError as exc:
        raise ParseError("PARSE_FAILED", f"Syntax error: {exc}") from exc
    except ValueError as exc:
        raise ParseError("UNSUPPORTED_FORMAT", f"Bad format: {exc}") from exc
    except Exception as exc:  # OSError etc.
        raise ParseError("PARSE_FAILED", f"Parse error: {exc}") from exc
    return store, PrefixMap(data, fmt)


def timed_parse_store(data: bytes, fmt: str) -> tuple[ox.Store, PrefixMap, float]:
    """parse_store plus wall-clock duration in milliseconds (for meta)."""
    start = time.perf_counter()
    store, pm = parse_store(data, fmt)
    return store, pm, (time.perf_counter() - start) * 1000.0


_OX_OUT = {
    "turtle": ox.RdfFormat.TURTLE,
    "rdfxml": ox.RdfFormat.RDF_XML,
    "jsonld": ox.RdfFormat.JSON_LD,
}


def serialize_store(store: ox.Store, prefixes: PrefixMap, fmt: str) -> bytes:
    """Dump the default graph back to bytes in the stored format (A2 writes).

    prefixes feeds the serializer's @prefix/xmlns table (jsonld output
    ignores it). from_graph=DefaultGraph scopes the dump: jsonld is a
    dataset format and would otherwise write the full store, named
    graphs included. Unknown fmt raises UNSUPPORTED_FORMAT; dump
    failures raise PARSE_FAILED with ox's detail.
    """
    fmt_enum = _OX_OUT.get(fmt)
    if fmt_enum is None:
        raise ParseError(
            "UNSUPPORTED_FORMAT",
            f"Unsupported format '{fmt}'",
            "Supported: turtle, rdfxml, jsonld",
        )
    try:
        out = store.dump(format=fmt_enum, from_graph=ox.DefaultGraph(), prefixes=prefixes.as_dict())
        # dump returns None only when an output stream is given; we omit it.
        return cast("bytes", out)
    except Exception as exc:
        raise ParseError("PARSE_FAILED", f"Serialization error: {exc}") from exc


def literal_type_ok(value: str, datatype: str) -> bool:
    """Whether a lexical form parses as the xsd/rdfs datatype.

    Lint + write validation share this; unknown datatypes accept — xsd:anyURI etc.
    """
    from collections.abc import Callable
    from datetime import date, datetime

    def _try(fn: Callable[[], object]) -> bool:
        try:
            fn()
            return True
        except ValueError:
            return False

    table = {
        XSD_NS + "integer": lambda v: v.lstrip("+-").isdigit() and v.lstrip("+-") != "",
        XSD_NS + "decimal": lambda v: _is_decimal(v),
        XSD_NS + "boolean": lambda v: v in ("true", "false", "0", "1"),
        XSD_NS + "date": lambda v: _try(lambda: date.fromisoformat(v)),
        XSD_NS + "dateTime": lambda v: _try(lambda: datetime.fromisoformat(v)),
    }
    check = table.get(datatype)
    return True if check is None else bool(check(value))


def _is_decimal(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False
