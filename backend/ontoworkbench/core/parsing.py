"""rdflib parsing + format sniffing (extension first, content fallback)."""

from __future__ import annotations

import time

import rdflib

from ontoworkbench.core.errors import CoreError


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
    """Parse bytes into a Graph; wrap syntax errors with the parser's detail."""
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


def literal_type_ok(value: str, datatype: str) -> bool:
    """Whether a lexical form parses as the xsd/rdfs datatype.

    Lint + write validation share this; unknown datatypes accept — xsd:anyURI etc.
    """
    from collections.abc import Callable
    from datetime import date, datetime

    from rdflib.namespace import XSD

    def _try(fn: Callable[[], object]) -> bool:
        try:
            fn()
            return True
        except ValueError:
            return False

    table = {
        str(XSD.integer): lambda v: v.lstrip("+-").isdigit() and v.lstrip("+-") != "",
        str(XSD.decimal): lambda v: _is_decimal(v),
        str(XSD.boolean): lambda v: v in ("true", "false", "0", "1"),
        str(XSD.date): lambda v: _try(lambda: date.fromisoformat(v)),
        str(XSD.dateTime): lambda v: _try(lambda: datetime.fromisoformat(v)),
    }
    check = table.get(datatype)
    return True if check is None else bool(check(value))


def _is_decimal(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False
