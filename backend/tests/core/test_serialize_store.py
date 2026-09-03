"""serialize_store: dump with prefixes; round-trips across all formats."""

import pyoxigraph as ox
import pytest

from ontoworkbench.core.errors import CoreError
from ontoworkbench.core.parsing import parse_store, serialize_store

SRC = (
    b"@prefix ex: <http://example.org/> .\n"
    b"ex:Thing a <http://www.w3.org/2002/07/owl#Class> ;\n"
    b'  <http://www.w3.org/2000/01/rdf-schema#label> "Thing"@en .\n'
)


def _triple_set(store: ox.Store) -> set[tuple[str, str, str]]:
    """(subject, predicate, object-lexical) triples of the default graph."""
    return {(q.subject.value, q.predicate.value, q.object.value) for q in store}


def test_turtle_roundtrip_preserves_triples() -> None:
    """Turtle dump keeps @prefix ex: compact and reparses to the same graph."""
    store, pm = parse_store(SRC, "turtle")
    out = serialize_store(store, pm, "turtle")
    assert b"@prefix ex:" in out  # prefix kept compact
    store2, _ = parse_store(out, "turtle")
    assert len(store) == len(store2) == 2
    assert _triple_set(store2) == _triple_set(store)


def test_rdfxml_roundtrip() -> None:
    """RDF-XML dump starts with an XML declaration and reparses losslessly."""
    store, pm = parse_store(SRC, "turtle")
    out = serialize_store(store, pm, "rdfxml")
    assert out.startswith(b"<?xml")
    store2, _ = parse_store(out, "rdfxml")
    assert len(store2) == 2
    assert _triple_set(store2) == _triple_set(store)


def test_jsonld_roundtrip() -> None:
    """JSON-LD dump is parseable JSON-LD holding the same two triples."""
    store, pm = parse_store(SRC, "turtle")
    out = serialize_store(store, pm, "jsonld")
    assert b'"@id"' in out or b'"http' in out
    store2, _ = parse_store(out, "jsonld")
    assert len(store2) == 2
    assert _triple_set(store2) == _triple_set(store)


def test_unknown_format_rejected() -> None:
    """A fmt outside the table is UNSUPPORTED_FORMAT, not a dump crash."""
    store, pm = parse_store(SRC, "turtle")
    with pytest.raises(CoreError) as ei:
        serialize_store(store, pm, "n3")
    assert ei.value.code == "UNSUPPORTED_FORMAT"
