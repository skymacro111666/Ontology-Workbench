"""Shared RDF term constants (pyoxigraph NamedNode) + well-known prefixes.

Every module that used to import rdflib's OWL/RDF/RDFS namespaces imports
these instead; pyoxigraph ships no vocabulary constants of its own.
"""

from __future__ import annotations

import pyoxigraph as ox

_NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "schema": "http://schema.org/",
    "obo": "http://purl.obolibrary.org/obo/",
    "prov": "http://www.w3.org/ns/prov#",
    "time": "http://www.w3.org/2006/time#",
    "geo": "http://www.opengis.net/ont/geosparql#",
    "vcard": "http://www.w3.org/2006/vcard/ns#",
    "xml": "http://www.w3.org/XML/1998/namespace",
}

WELL_KNOWN_PREFIXES = dict(_NS)

RDF_TYPE = ox.NamedNode(_NS["rdf"] + "type")
RDFS_LABEL = ox.NamedNode(_NS["rdfs"] + "label")
DCTERMS_TITLE = ox.NamedNode(_NS["dcterms"] + "title")
RDFS_COMMENT = ox.NamedNode(_NS["rdfs"] + "comment")
RDFS_SUBCLASSOF = ox.NamedNode(_NS["rdfs"] + "subClassOf")
RDFS_DOMAIN = ox.NamedNode(_NS["rdfs"] + "domain")
RDFS_RANGE = ox.NamedNode(_NS["rdfs"] + "range")
OWL_CLASS = ox.NamedNode(_NS["owl"] + "Class")
OWL_OBJECTPROPERTY = ox.NamedNode(_NS["owl"] + "ObjectProperty")
OWL_DATATYPEPROPERTY = ox.NamedNode(_NS["owl"] + "DatatypeProperty")
OWL_NAMEDINDIVIDUAL = ox.NamedNode(_NS["owl"] + "NamedIndividual")
OWL_ONTOLOGY = ox.NamedNode(_NS["owl"] + "Ontology")
OWL_DEPRECATED = ox.NamedNode(_NS["owl"] + "deprecated")
XSD_BOOLEAN = ox.NamedNode(_NS["xsd"] + "boolean")
XSD_STRING = ox.NamedNode(_NS["xsd"] + "string")
