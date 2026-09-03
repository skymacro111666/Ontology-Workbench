"""terms.py: ox NamedNode constants replace rdflib namespace imports."""

import pyoxigraph as ox

from ontoworkbench.core import terms


def test_constants_are_named_nodes() -> None:
    """Constants equal the canonical IRIs of rdf:type / owl:Class / rdfs:label."""
    assert terms.RDF_TYPE == ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
    assert terms.OWL_CLASS == ox.NamedNode("http://www.w3.org/2002/07/owl#Class")
    assert terms.RDFS_LABEL == ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")


def test_well_known_prefixes_cover_common_vocab() -> None:
    """The built-in prefix table maps the four core vocab namespaces."""
    assert terms.WELL_KNOWN_PREFIXES["owl"] == "http://www.w3.org/2002/07/owl#"
    assert terms.WELL_KNOWN_PREFIXES["rdf"] == "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    assert terms.WELL_KNOWN_PREFIXES["rdfs"] == "http://www.w3.org/2000/01/rdf-schema#"
    assert terms.WELL_KNOWN_PREFIXES["xsd"] == "http://www.w3.org/2001/XMLSchema#"
