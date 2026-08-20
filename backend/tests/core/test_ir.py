"""IR assembly from a small Turtle graph."""

import rdflib

from ontoworkbench.core.ir import build_ir

MINI = """@prefix ex: <http://example.org/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
ex:Animal a owl:Class ; rdfs:label "Animal"@en .
ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal ; rdfs:label "Dog"@en .
ex:likes a owl:ObjectProperty ; rdfs:domain ex:Dog ; rdfs:range ex:Animal .
"""


def test_build_ir_counts_and_refs() -> None:
    """Counts, CURIEs, hierarchy, and reverse references assemble correctly."""
    g = rdflib.Graph().parse(data=MINI, format="turtle")
    ir = build_ir(g)
    assert ir.counts.class_count == 2
    assert ir.counts.property_count == 1
    assert ir.counts.axiom_count == len(g)

    dog = ir.entities["http://example.org/Dog"]
    assert dog.curie == "ex:Dog"
    assert dog.label == {"en": "Dog"}
    assert [p.curie for p in dog.parents] == ["ex:Animal"]
    assert dog.stats.direct_children == 0
    assert dog.type == "Class"

    animal = ir.entities["http://example.org/Animal"]
    assert [c.curie for c in animal.children] == ["ex:Dog"]
    assert [p.curie for p in animal.properties] == ["ex:likes"]
    # reverse reference: Dog's subClassOf axiom references Animal
    animal_refs = [r.curie for r in animal.referenced_by]
    assert "ex:Dog" in animal_refs


def test_ir_prefixes_and_axioms() -> None:
    """Namespace bindings surface as prefixes; axioms serialize as Turtle."""
    g = rdflib.Graph().parse(data=MINI, format="turtle")
    ir = build_ir(g)
    assert ir.prefixes.get("ex") == "http://example.org/"
    dog = ir.entities["http://example.org/Dog"]
    turtle_text = "\n".join(a.turtle for a in dog.axioms)
    assert (
        "subClassOf" in turtle_text
        or "http://www.w3.org/2000/01/rdf-schema#subClassOf" in turtle_text
    )
    assert "ex:Dog" in turtle_text


def test_ir_domain_property_typed() -> None:
    """A property bound to Dog via rdfs:domain carries its ptype."""
    g = rdflib.Graph().parse(data=MINI, format="turtle")
    ir = build_ir(g)
    dog = ir.entities["http://example.org/Dog"]
    likes = dog.properties[0]
    assert likes.ptype == "ObjectProperty"
    prop_entity = ir.entities["http://example.org/likes"]
    assert prop_entity.type == "ObjectProperty"
    assert prop_entity.stats.direct_children == 0
