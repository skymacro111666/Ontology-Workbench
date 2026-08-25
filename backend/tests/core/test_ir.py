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


def test_counts_individual_count_is_distinct() -> None:
    """individual_count = distinct NamedIndividuals, deduped across classes."""
    ttl = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Animal a owl:Class .
ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal .
ex:rex a owl:NamedIndividual , ex:Dog , ex:Animal .
ex:buddy a owl:NamedIndividual , ex:Dog .
"""
    ir = build_ir(rdflib.Graph().parse(data=ttl, format="turtle"))
    assert ir.counts.individual_count == 2
    # Graphs without individuals count zero.
    mini = build_ir(rdflib.Graph().parse(data=MINI, format="turtle"))
    assert mini.counts.individual_count == 0


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


def test_pizza_ir_deterministic_and_stable() -> None:
    """Pizza IR: stable counts and byte-identical rebuilds (snapshot substitute)."""
    from pathlib import Path

    from ontoworkbench.core.parsing import parse_graph

    samples = Path(__file__).parents[2] / "ontoworkbench" / "samples"
    data = (samples / "pizza.ttl").read_bytes()
    ir1 = build_ir(parse_graph(data, "turtle"))
    ir2 = build_ir(parse_graph(data, "turtle"))
    assert ir1.counts.class_count == 99
    assert ir1.counts.property_count == 8
    assert ir1.model_dump_json() == ir2.model_dump_json()


def test_ir_comment_deprecated_and_descendants() -> None:
    """Comment/deprecated parse; total_descendants counts the subtree."""
    ttl = MINI + (
        "ex:Puppy a owl:Class ; rdfs:subClassOf ex:Dog ; "
        'rdfs:comment "young"@en ; owl:deprecated true .\n'
    )
    g = rdflib.Graph().parse(data=ttl, format="turtle")
    ir = build_ir(g)
    dog = ir.entities["http://example.org/Dog"]
    assert dog.stats.total_descendants == 1  # Puppy
    thing = ir.entities["http://example.org/Animal"]
    assert thing.stats.total_descendants == 2  # Dog -> Puppy
    puppy = ir.entities["http://example.org/Puppy"]
    assert puppy.comment == "young"
    assert puppy.deprecated is True
    assert dog.deprecated is False


def test_ir_prefixes_only_used_namespaces() -> None:
    """Built-in rdflib namespace bindings do not leak into prefixes."""
    g = rdflib.Graph().parse(data=MINI, format="turtle")
    ir = build_ir(g)
    assert set(ir.prefixes) <= {"ex", "rdfs", "owl", "rdf"}  # rdf:type via Turtle 'a'
    assert "brick" not in ir.prefixes and "csvw" not in ir.prefixes


def test_ir_referenced_by_relations() -> None:
    """Domain/range axioms link classes and properties in both directions."""
    g = rdflib.Graph().parse(data=MINI, format="turtle")
    ir = build_ir(g)
    dog = ir.entities["http://example.org/Dog"]
    # likes points at Dog via rdfs:domain -> Dog is referenced by likes
    refs = {(r.curie, r.relation) for r in dog.referenced_by}
    assert ("ex:likes", "rdfs:domain") in refs
    likes = ir.entities["http://example.org/likes"]
    # and likes is referenced by the classes its axioms point at
    prop_refs = {(r.curie, r.relation) for r in likes.referenced_by}
    assert ("ex:Dog", "rdfs:domain") in prop_refs
    assert ("ex:Animal", "rdfs:range") in prop_refs
    animal = ir.entities["http://example.org/Animal"]
    animal_refs = {(r.curie, r.relation) for r in animal.referenced_by}
    assert ("ex:Dog", "subClassOf") in animal_refs
    assert ("ex:likes", "rdfs:range") in animal_refs


def test_ir_individuals_grouped_by_direct_class() -> None:
    """Named individuals typed at a declared class group under it.

    Individuals stay out of entities/counts — they join the canvas on
    demand, not the schema walk.
    """
    ttl = MINI + (
        'ex:rex a owl:NamedIndividual , ex:Dog ; rdfs:label "Rex"@en .\n'
        "ex:buddy a owl:NamedIndividual , ex:Dog .\n"
        "ex:loose a owl:NamedIndividual .\n"
    )
    g = rdflib.Graph().parse(data=ttl, format="turtle")
    ir = build_ir(g)
    dog_insts = ir.instances["http://example.org/Dog"]
    assert [i.curie for i in dog_insts] == ["ex:buddy", "ex:rex"]
    rex = next(i for i in dog_insts if i.curie == "ex:rex")
    assert rex.eid == "http://example.org/rex"
    assert rex.label == {"en": "Rex"}
    # No declared class -> nowhere to group; no class gains phantom instances.
    assert "http://example.org/loose" not in {
        i.eid for insts in ir.instances.values() for i in insts
    }
    assert ir.counts.class_count == 2
    assert "http://example.org/rex" not in ir.entities
