"""rdflib parsing + format sniffing (extension first, content fallback)."""

from __future__ import annotations

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
