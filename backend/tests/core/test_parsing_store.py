"""parse_store: bytes → (Store, PrefixMap) with error mapping."""

import pytest

from ontoworkbench.core.errors import CoreError
from ontoworkbench.core.parsing import parse_store, timed_parse_store

MINI = b"@prefix ex: <http://example.org/> .\nex:Thing a <http://www.w3.org/2002/07/owl#Class> .\n"


def test_parse_store_turtle() -> None:
    """Turtle bytes land in the Store and @prefix feeds the PrefixMap."""
    store, pm = parse_store(MINI, "turtle")
    assert len(store) == 1
    assert pm.iri_for("ex", "Thing") == "http://example.org/Thing"


def test_parse_store_rdfxml_and_jsonld() -> None:
    """RDF-XML and JSON-LD both load one triple into the default graph."""
    xml = (
        b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        b'<owl:Class xmlns:owl="http://www.w3.org/2002/07/owl#" rdf:about="http://example.org/Thing"/></rdf:RDF>'
    )
    store, _ = parse_store(xml, "rdfxml")
    assert len(store) == 1
    js = b'{"@id": "http://example.org/Thing", "@type": "http://www.w3.org/2002/07/owl#Class"}'
    store2, _ = parse_store(js, "jsonld")
    assert len(store2) == 1


def test_syntax_error_maps_to_parse_failed() -> None:
    """Malformed turtle surfaces as CoreError with code PARSE_FAILED."""
    with pytest.raises(CoreError) as ei:
        parse_store(b"this is not turtle @ @", "turtle")
    assert ei.value.code == "PARSE_FAILED"


def test_unknown_format_maps_to_unsupported() -> None:
    """A fmt outside _OX_FORMAT is rejected before any parsing happens."""
    with pytest.raises(CoreError) as ei:
        parse_store(b"x", "n3")  # not in _OX_FORMAT
    assert ei.value.code == "UNSUPPORTED_FORMAT"


def test_timed_parse_store_reports_ms() -> None:
    """timed_parse_store returns the same result plus a non-negative ms."""
    store, pm, ms = timed_parse_store(MINI, "turtle")
    assert ms >= 0 and len(store) == 1
