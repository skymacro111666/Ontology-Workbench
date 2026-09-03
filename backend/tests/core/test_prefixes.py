"""PrefixMap: file-declared prefixes (3 formats) over well-known fallbacks."""

from ontoworkbench.core.prefixes import PrefixMap


def test_turtle_prefix_declarations() -> None:
    """@prefix and SPARQL-style PREFIX lines both yield usable mappings."""
    data = (
        b"@prefix ex: <http://example.org/> .\n"
        b"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        b"ex:Thing a owl:Class .\n"
    )
    pm = PrefixMap(data, "turtle")
    assert pm.iri_for("ex", "Thing") == "http://example.org/Thing"
    assert pm.curie_for("http://example.org/Thing") == ("ex", "Thing")
    # PREFIX (SPARQL-style, case-insensitive) also recognized
    pm2 = PrefixMap(b"PREFIX p: <http://p.org/>\np:x a <http://p.org/T> .", "turtle")
    assert pm2.iri_for("p", "x") == "http://p.org/x"


def test_rdfxml_xmlns_declarations() -> None:
    """Namespace attrs are collected, including those on inner elements."""
    data = (
        b'<?xml version="1.0"?>\n<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        b'xmlns:ex="http://example.org/">\n'
        b'<owl:Class xmlns:owl="http://www.w3.org/2002/07/owl#" '
        b'rdf:about="http://example.org/Thing"/>\n</rdf:RDF>'
    )
    pm = PrefixMap(data, "rdfxml")
    assert pm.iri_for("ex", "Thing") == "http://example.org/Thing"
    # owl was declared on an inner element, not the root — still collected
    assert pm.iri_for("owl", "Class") == "http://www.w3.org/2002/07/owl#Class"


def test_jsonld_context_prefixes() -> None:
    """String→IRI entries in @context become prefix declarations."""
    data = b'{"@context": {"ex": "http://example.org/"}, "@id": "ex:Thing", "@type": "ex:T"}'
    pm = PrefixMap(data, "jsonld")
    assert pm.iri_for("ex", "Thing") == "http://example.org/Thing"


def test_well_known_fallback_and_override() -> None:
    """Empty files fall back to builtins; file declarations win on collision."""
    pm = PrefixMap(b"", "turtle")
    assert pm.curie_for("http://www.w3.org/2002/07/owl#Class") == ("owl", "Class")
    assert pm.curie_for("http://nowhere.org/x") is None  # unmapped → full IRI
    # file declaration wins over builtin for the same prefix
    pm2 = PrefixMap(b"@prefix owl: <http://example.org/owl#> .", "turtle")
    assert pm2.iri_for("owl", "X") == "http://example.org/owl#X"


def test_curie_needs_valid_local_name() -> None:
    """A URI whose remainder is not a valid PN_LOCAL does not get curie'd."""
    pm = PrefixMap(b"@prefix ex: <http://example.org/> .", "turtle")
    assert pm.curie_for("http://example.org/-bad") is None  # PN_LOCAL fail → None


def test_as_dict_for_serialization() -> None:
    """as_dict merges file declarations with the builtin table for dump output."""
    pm = PrefixMap(b"@prefix ex: <http://example.org/> .", "turtle")
    d = pm.as_dict()
    assert d["ex"] == "http://example.org/"
    assert d["owl"]  # builtins included for compact dump output
