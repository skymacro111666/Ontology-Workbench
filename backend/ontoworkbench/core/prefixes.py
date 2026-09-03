"""Prefix declarations extracted from source bytes (ox stores no prefixes).

Replaces rdflib's compute_qname/namespaces(): file declarations are parsed
per format (Turtle @prefix/PREFIX lines, RDF-XML xmlns attrs, JSON-LD
@context), then merged over the well-known table. File declarations win.
"""

from __future__ import annotations

import io
import json
import re
from xml.etree import ElementTree as ET

from ontoworkbench.core.terms import WELL_KNOWN_PREFIXES

_TTL_PREFIX = re.compile(
    rb"^\s*(?:@prefix|PREFIX)\s+([A-Za-z_][\w.-]*):\s*<([^>\s]+)>", re.MULTILINE
)
_PN_LOCAL = re.compile(r"[A-Za-z0-9_](?:[A-Za-z0-9_\-.]*[A-Za-z0-9_\-])?\Z")

# Runaway cap on xmlns collection: real ontologies declare far fewer
# namespaces than this; hostile input must not stall the parse.
_MAX_XMLNS_DECLS = 500


class PrefixMap:
    """prefix → namespace with curie/iri helpers; immutable after build."""

    def __init__(self, data: bytes, fmt: str) -> None:
        """Parse declarations out of `data` per `fmt`, merged over builtins.

        fmt is one of "turtle", "rdfxml", "jsonld"; anything else (or an
        empty payload) leaves just the well-known table.
        """
        decls: dict[str, str] = {}
        if fmt == "turtle":
            decls = {m.group(1).decode(): m.group(2).decode() for m in _TTL_PREFIX.finditer(data)}
        elif fmt == "rdfxml":
            decls = dict(_xmlns_decls(data))
        elif fmt == "jsonld":
            decls = _jsonld_context(data)
        self._decls: dict[str, str] = {**WELL_KNOWN_PREFIXES, **decls}
        # longest-namespace-first matching order, computed once
        self._sorted: list[tuple[str, str]] = sorted(
            self._decls.items(), key=lambda kv: -len(kv[1])
        )

    def curie_for(self, uri: str) -> tuple[str, str] | None:
        """Split `uri` into (prefix, local) if it starts with a known namespace.

        Longest namespace wins; returns None when the remainder is not a
        valid PN_LOCAL (the URI should then stay a full IRI).
        """
        for prefix, ns in self._sorted:
            if uri.startswith(ns):
                local = uri[len(ns) :]
                if _PN_LOCAL.match(local):
                    return prefix, local
                return None
        return None

    def iri_for(self, prefix: str, local: str) -> str | None:
        """Expand (prefix, local) to a full IRI, or None if prefix unknown."""
        ns = self._decls.get(prefix)
        return ns + local if ns is not None else None

    def known_prefixes(self) -> list[str]:
        """Sorted prefix names present in the map (default xmlns excluded)."""
        return sorted(p for p in self._decls if p)

    def as_dict(self) -> dict[str, str]:
        """A copy of the full prefix → namespace table, for dump output."""
        return dict(self._decls)


def _xmlns_decls(data: bytes) -> list[tuple[str, str]]:
    """Collect (prefix, uri) from every xmlns declaration in the XML bytes.

    Malformed XML yields [] — parse_store raises separately; prefixes
    degrade to the builtin table.
    """
    out: list[tuple[str, str]] = []
    try:
        for _, elem in ET.iterparse(io.BytesIO(data), events=("start-ns",)):
            out.append((elem[0] or "", elem[1]))
            if len(out) > _MAX_XMLNS_DECLS:
                break
    except ET.ParseError:
        pass
    return out


def _jsonld_context(data: bytes) -> dict[str, str]:
    """Extract prefix → IRI pairs from a JSON-LD document's @context.

    Non-dict documents, invalid JSON, and non-string context entries are
    ignored rather than raised on.
    """
    try:
        doc = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return {}
    ctx = doc.get("@context") if isinstance(doc, dict) else None
    if isinstance(ctx, dict):
        return {k: v for k, v in ctx.items() if isinstance(k, str) and isinstance(v, str)}
    return {}
