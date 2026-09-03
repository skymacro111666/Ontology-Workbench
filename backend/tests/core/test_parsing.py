"""Format sniffing and store parsing."""

import pyoxigraph as ox
import pytest

from ontoworkbench.core.parsing import ParseError, parse_store, sniff_format

TTL = b"""@prefix ex: <http://example.org/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Dog rdfs:subClassOf ex:Animal .
"""
JSONLD = b'{"@context": {"ex": "http://example.org/"}, "@id": "ex:Dog", "@type": "ex:Class"}'


def test_sniff_by_extension() -> None:
    """Known extensions win over content probing."""
    assert sniff_format("a.ttl", TTL) == "turtle"
    assert sniff_format("a.owl", b"<xml/>") == "rdfxml"
    assert sniff_format("a.jsonld", JSONLD) == "jsonld"


def test_sniff_by_content_fallback() -> None:
    """Unknown extension falls back to content probing."""
    assert sniff_format("unknown", TTL) == "turtle"
    assert sniff_format("unknown", JSONLD) == "jsonld"


def test_sniff_rejects_garbage() -> None:
    """Bytes that look like nothing supported raise UNSUPPORTED_FORMAT."""
    with pytest.raises(ParseError) as e:
        sniff_format("x.bin", b"\x00\x01binary")
    assert e.value.code == "UNSUPPORTED_FORMAT"


def test_parse_and_syntax_error() -> None:
    """Valid turtle parses to one quad; garbage raises PARSE_FAILED."""
    store, _ = parse_store(TTL, "turtle")
    quads = list(store.quads_for_pattern(None, None, None, ox.DefaultGraph()))
    assert len(quads) == 1
    with pytest.raises(ParseError) as e:
        parse_store(b"this is @not turtle", "turtle")
    assert e.value.code == "PARSE_FAILED"


def test_parse_error_carries_detail() -> None:
    """ParseError exposes code/message/hint fields for the API layer."""
    with pytest.raises(ParseError) as e:
        parse_store(b"<http://x> <http://y>", "rdfxml")
    err = e.value
    assert err.code == "PARSE_FAILED"
    assert err.message
    assert isinstance(err.hint, str | type(None))


def test_parse_rejects_unknown_format() -> None:
    """A format name outside turtle/rdfxml/jsonld is UNSUPPORTED_FORMAT."""
    with pytest.raises(ParseError) as e:
        parse_store(TTL, "n3")
    assert e.value.code == "UNSUPPORTED_FORMAT"
