"""build_ir_store on an ox Store: bnode axioms, literal forms, prefix filter."""

from ontoworkbench.core.ir import build_ir_store
from ontoworkbench.core.parsing import parse_store

GO_STYLE = b"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Dog a owl:Class ; rdfs:subClassOf [
  a owl:Restriction ; owl:onProperty ex:hasToy ; owl:someValuesFrom ex:Toy ] .
ex:hasToy a owl:ObjectProperty ; rdfs:label "has toy"@en ; rdfs:domain ex:Dog ; rdfs:range ex:Toy .
ex:Toy a owl:Class .


"""

TWO_BNODES = b"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Dog a owl:Class ; rdfs:subClassOf [
  a owl:Restriction ; owl:onProperty ex:hasToy ; owl:someValuesFrom ex:Toy ] ,
  [ a owl:Restriction ; owl:onProperty ex:eats ; owl:someValuesFrom ex:Food ] .
ex:hasToy a owl:ObjectProperty .
ex:eats a owl:ObjectProperty .
ex:Toy a owl:Class .
ex:Food a owl:Class .


"""

INDIVIDUALS = b"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
ex:Dog a owl:Class .
ex:Old a owl:Class ; owl:deprecated true .
ex:age a owl:DatatypeProperty ; rdfs:domain ex:Dog ; rdfs:range xsd:integer .
ex:nick a owl:DatatypeProperty .
ex:bio a owl:DatatypeProperty .
ex:knows a owl:ObjectProperty .
ex:Rex a owl:NamedIndividual , ex:Dog ;
  ex:age "5"^^xsd:integer ;
  ex:nick "rex" ;
  ex:bio "good dog"@en ;
  rdfs:comment "good boy" ;
  ex:knows ex:Ace .
ex:Ace a owl:NamedIndividual .


"""


def _build(data: bytes = GO_STYLE):
    store, pm = parse_store(data, "turtle")
    return build_ir_store(store, pm)


def test_restriction_axiom_survives_roundtrip() -> None:
    """The restriction bnode passes through the axiom block relabeled _:b0."""
    ir = _build()
    dog = ir.entities["http://example.org/Dog"]
    assert "rdfs:subClassOf _:b0" in dog.axioms[0].turtle
    assert dog.axioms[0].turtle.endswith(".")


def test_label_language_and_type() -> None:
    """Language-tagged label keys by tag; ptype resolves to ObjectProperty."""
    ir = _build()
    prop = ir.entities["http://example.org/hasToy"]
    assert prop.label == {"en": "has toy"}
    assert prop.type == "ObjectProperty"


def test_axiom_block_is_deterministic() -> None:
    """Blank nodes relabeled _:b0.. by first appearance — two builds equal."""
    a = _build().entities["http://example.org/Dog"].axioms[0].turtle
    b = _build().entities["http://example.org/Dog"].axioms[0].turtle
    assert a == b


def test_two_bnode_restrictions_relabel_stably() -> None:
    """Two bnodes under one predicate: pairing survives fresh parses."""
    blocks = {
        _build(TWO_BNODES).entities["http://example.org/Dog"].axioms[0].turtle for _ in range(3)
    }
    assert len(blocks) == 1
    block = blocks.pop()
    assert "rdfs:subClassOf _:b0 , _:b1" in block


DEFAULT_PREFIX = b"""@prefix : <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
:Dog a owl:Class ; rdfs:subClassOf :Animal .
:Animal a owl:Class .


"""


def test_default_prefix_terms_render_compact() -> None:
    """Default-namespace terms render :Dog (pizza/wine/go style), not <iri>."""
    ir = _build(DEFAULT_PREFIX)
    dog = ir.entities["http://example.org/Dog"]
    assert dog.curie == ":Dog"
    assert dog.parents[0].curie == ":Animal"
    block = dog.axioms[0].turtle
    assert "@prefix : <http://example.org/> ." in block
    assert ":Dog a owl:Class" in block
    assert ":subClassOf :Animal" in block
    assert "<http://example.org/Dog>" not in block
    assert "<http://example.org/Animal>" not in block
    # IR prefixes keep the rdflib-era display name for "" (meta payload only)
    assert ir.prefixes["base"] == "http://example.org/"


def test_individuals_data_assertions_include_plain_strings() -> None:
    """Typed and plain-string literals assert with full datatype IRIs.

    Language-tagged ones stay out; instances group.
    """
    ir = _build(INDIVIDUALS)
    rex = ir.individuals["http://example.org/Rex"]
    assert [c.curie for c in rex.classes] == ["ex:Dog"]
    assert rex.comment == "good boy"
    assert [(a.property.curie, a.object.curie) for a in rex.object_assertions] == [
        ("ex:knows", "ex:Ace")
    ]
    # RDF 1.1: the bare "rex" IS xsd:string, so it asserts with the full
    # datatype IRI — only the @en bio is filtered.
    assert [(a.property.curie, a.value, a.datatype) for a in rex.data_assertions] == [
        ("ex:age", "5", "http://www.w3.org/2001/XMLSchema#integer"),
        ("ex:nick", "rex", "http://www.w3.org/2001/XMLSchema#string"),
    ]
    assert [r.curie for r in ir.instances["http://example.org/Dog"]] == ["ex:Rex"]
    assert ir.counts.individual_count == 2
    assert ir.entities["http://example.org/Old"].deprecated is True
