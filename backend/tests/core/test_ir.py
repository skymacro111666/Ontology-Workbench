"""IR assembly from a small Turtle store (build_ir_store contract)."""

from pathlib import Path

import pyoxigraph as ox

from ontoworkbench.core.ir import _ox_curie, _ox_curie_for, _ox_turtle_block, build_ir_store
from ontoworkbench.core.parsing import parse_store

MINI = """@prefix ex: <http://example.org/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
ex:Animal a owl:Class ; rdfs:label "Animal"@en .
ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal ; rdfs:label "Dog"@en .
ex:likes a owl:ObjectProperty ; rdfs:domain ex:Dog ; rdfs:range ex:Animal .
"""


def _build(ttl: str = MINI):
    """Parse ttl into (store, prefixes) and build the IR bundle."""
    return build_ir_store(*parse_store(ttl.encode(), "turtle"))


def test_build_ir_counts_and_refs() -> None:
    """Counts, CURIEs, hierarchy, and reverse references assemble correctly."""
    store, pm = parse_store(MINI.encode(), "turtle")
    ir = build_ir_store(store, pm)
    assert ir.counts.class_count == 2
    assert ir.counts.property_count == 1
    assert ir.counts.axiom_count == len(store)

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
    ir = _build(ttl)
    assert ir.counts.individual_count == 2
    # Graphs without individuals count zero.
    assert _build().counts.individual_count == 0


def test_ir_prefixes_and_axioms() -> None:
    """Namespace bindings surface as prefixes; axioms serialize as Turtle."""
    ir = _build()
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
    ir = _build()
    dog = ir.entities["http://example.org/Dog"]
    likes = dog.properties[0]
    assert likes.ptype == "ObjectProperty"
    prop_entity = ir.entities["http://example.org/likes"]
    assert prop_entity.type == "ObjectProperty"
    assert prop_entity.stats.direct_children == 0


def test_pizza_ir_deterministic_and_stable() -> None:
    """Pizza IR: stable counts and byte-identical rebuilds (snapshot substitute)."""
    samples = Path(__file__).parents[2] / "ontoworkbench" / "samples"
    data = (samples / "pizza.ttl").read_bytes()
    ir1 = build_ir_store(*parse_store(data, "turtle"))
    ir2 = build_ir_store(*parse_store(data, "turtle"))
    assert ir1.counts.class_count == 99
    assert ir1.counts.property_count == 8
    assert ir1.model_dump_json() == ir2.model_dump_json()


def test_ir_comment_deprecated_and_descendants() -> None:
    """Comment/deprecated parse; total_descendants counts the subtree."""
    ttl = MINI + (
        "ex:Puppy a owl:Class ; rdfs:subClassOf ex:Dog ; "
        'rdfs:comment "young"@en ; owl:deprecated true .\n'
    )
    ir = _build(ttl)
    dog = ir.entities["http://example.org/Dog"]
    assert dog.stats.total_descendants == 1  # Puppy
    thing = ir.entities["http://example.org/Animal"]
    assert thing.stats.total_descendants == 2  # Dog -> Puppy
    puppy = ir.entities["http://example.org/Puppy"]
    assert puppy.comment == "young"
    assert puppy.deprecated is True
    assert dog.deprecated is False


def test_ir_prefixes_only_used_namespaces() -> None:
    """The well-known prefix table does not leak unused entries into prefixes."""
    ir = _build()
    assert set(ir.prefixes) <= {"ex", "rdfs", "owl", "rdf"}  # rdf:type via Turtle 'a'
    assert "brick" not in ir.prefixes and "csvw" not in ir.prefixes


def test_ir_counterpart_declared_flag() -> None:
    """Counterparts mark declared far ends (clickable) vs external IRIs."""
    ttl = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
ex:Dog a owl:Class .
ex:Animal a owl:Class .
ex:likes a owl:ObjectProperty ; rdfs:domain ex:Dog ; rdfs:range ex:Animal .
ex:barks a owl:DatatypeProperty ; rdfs:domain ex:Dog ; rdfs:range xsd:boolean .
"""
    ir = _build(ttl)
    dog = ir.entities["http://example.org/Dog"]
    refs = {r.curie: r for r in dog.referenced_by}
    assert refs["ex:likes"].counterpart is not None
    assert refs["ex:likes"].counterpart.declared is True  # owl:Class in-graph
    assert refs["ex:barks"].counterpart is not None
    assert refs["ex:barks"].counterpart.declared is False  # xsd:boolean external


def test_ir_referenced_by_relations() -> None:
    """Domain/range axioms link classes and properties in both directions."""
    ir = _build()
    dog = ir.entities["http://example.org/Dog"]
    # likes points at Dog via rdfs:domain -> Dog is referenced by likes
    refs = {(r.curie, r.relation) for r in dog.referenced_by}
    assert ("ex:likes", "rdfs:domain") in refs
    # The domain ref carries the axiom's far end: likes's range Animal.
    dog_likes = next(r for r in dog.referenced_by if r.curie == "ex:likes")
    assert dog_likes.counterpart is not None
    assert dog_likes.counterpart.curie == "ex:Animal"
    assert dog_likes.counterpart.declared is True
    likes = ir.entities["http://example.org/likes"]
    # and likes is referenced by the classes its axioms point at
    prop_refs = {(r.curie, r.relation) for r in likes.referenced_by}
    assert ("ex:Dog", "rdfs:domain") in prop_refs
    assert ("ex:Animal", "rdfs:range") in prop_refs
    # Property side mirrors: the Animal range ref's far end is likes's domain.
    likes_animal = next(r for r in likes.referenced_by if r.curie == "ex:Animal")
    assert likes_animal.counterpart is not None
    assert likes_animal.counterpart.curie == "ex:Dog"
    animal = ir.entities["http://example.org/Animal"]
    animal_refs = {(r.curie, r.relation) for r in animal.referenced_by}
    assert ("ex:Dog", "subClassOf") in animal_refs
    assert ("ex:likes", "rdfs:range") in animal_refs
    # subClassOf backrefs have no counterpart.
    animal_dog = next(r for r in animal.referenced_by if r.curie == "ex:Dog")
    assert animal_dog.counterpart is None


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
    ir = _build(ttl)
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


def test_individuals_collect_assertions() -> None:
    """library.ttl 的 ThreeBody:类型、对象断言、数据断言齐备."""
    data = (Path(__file__).parents[2] / "ontoworkbench" / "samples" / "library.ttl").read_bytes()
    ir = build_ir_store(*parse_store(data, "turtle"))

    tb = ir.individuals[
        "https://github.com/skymacro111666/ontology-workbench/samples/library#ThreeBody"
    ]
    assert tb.kind == "instance"
    assert tb.curie == "lib:ThreeBody"
    assert [c.curie for c in tb.classes] == ["lib:ScienceFiction"]
    objs = {a.property.curie: a.object.curie for a in tb.object_assertions}
    assert objs == {"lib:hasCreator": "lib:LiuCixin", "lib:locatedIn": "lib:MainStacks"}
    data_values = {a.property.curie: a.value for a in tb.data_assertions}
    # lib:isbn is a bare string literal — RDF 1.1 makes it xsd:string, so it
    # IS collected, with the full datatype IRI (final-review fix 2026-09-04)
    assert data_values == {
        "lib:isbn": "978-7-5366-9293-0",
        "lib:publicationYear": "2008",
        "lib:pageCount": "302",
        "lib:available": "true",
    }
    isbn = next(a for a in tb.data_assertions if a.property.curie == "lib:isbn")
    assert isbn.datatype == "http://www.w3.org/2001/XMLSchema#string"
    year = next(a for a in tb.data_assertions if a.property.curie == "lib:publicationYear")
    assert year.datatype == "http://www.w3.org/2001/XMLSchema#integer"
    # 既有 instances 映射不回归(徽章口径)
    assert any(
        r.eid == tb.eid
        for r in ir.instances[
            "https://github.com/skymacro111666/ontology-workbench/samples/library#ScienceFiction"
        ]
    )
    # 实体也带 kind 字段
    assert (
        ir.entities[
            "https://github.com/skymacro111666/ontology-workbench/samples/library#Book"
        ].kind
        == "entity"
    )


def test_prop_refs_carry_domain_and_range() -> None:
    """A class page's property list carries each property's domain/range."""
    ir = _build()
    dog = ir.entities["http://example.org/Dog"]
    likes = next(p for p in dog.properties if p.curie == "ex:likes")
    assert [d.curie for d in likes.domain] == ["ex:Dog"]
    assert [r.curie for r in likes.range] == ["ex:Animal"]


def test_ir_bundle_carries_ontology_iri() -> None:
    """The owl:Ontology subject IRI rides the bundle for provenance."""
    assert _build().ontology_iri is None  # no declaration → None

    declared = MINI + "<http://example.org/> a owl:Ontology .\n"
    assert _build(declared).ontology_iri == "http://example.org/"


EQUIV_TTL = """@prefix ex: <http://example.org/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
ex:Animal a owl:Class .
ex:Dog a owl:Class ;
    rdfs:label "Dog"@en , "Dog \\"aka\\" canine" , "4"^^xsd:integer , "tab\\there" ;
    rdfs:comment "line1\\nline2" ;
    rdfs:subClassOf ex:Animal , [ a owl:Restriction ] .
"""


def _term_key(t: ox.NamedNode | ox.BlankNode | ox.Literal) -> tuple:
    """A comparison key; blank nodes normalize to one placeholder."""
    if isinstance(t, ox.NamedNode):
        return ("iri", t.value)
    if isinstance(t, ox.Literal):
        return ("lit", t.value, t.language, t.datatype.value if t.datatype else None)
    return ("bnode",)


def _subject_quads(store: ox.Store, uri: str) -> set[tuple]:
    """(predicate, object-key) pairs of the subject's default-graph triples."""
    return {
        (q.predicate.value, _term_key(q.object))
        for q in store.quads_for_pattern(ox.NamedNode(uri), None, None, ox.DefaultGraph())
    }


def _subjects(ttl: str) -> list[str]:
    """Distinct IRI subjects of the parsed store, deterministic order."""
    store, _ = parse_store(ttl.encode(), "turtle")
    return sorted(
        {
            q.subject.value
            for q in store.quads_for_pattern(None, None, None, ox.DefaultGraph())
            if isinstance(q.subject, ox.NamedNode)
        }
    )


def test_turtle_block_round_trips_every_subject() -> None:
    """Every IRI subject renders a block that re-parses to the same triples.

    The block is self-contained (@prefix lines included), so re-parsing it
    through the engine must reproduce the store's (predicate, object) set
    for that subject — literals with tag/datatype, blank nodes by shape.
    """
    store, pm = parse_store(EQUIV_TTL.encode(), "turtle")
    subjects = [s for s in _subjects(EQUIV_TTL) if s.startswith("http://")]
    assert len(subjects) >= 2  # fixture sanity: at least Dog and Animal
    for uri in subjects:
        block = _ox_turtle_block(store, pm, uri)
        reparsed, _ = parse_store(block.encode(), "turtle")
        assert _subject_quads(reparsed, uri) == _subject_quads(store, uri), f"divergence on {uri}"


def test_turtle_block_grouped_and_deterministic() -> None:
    """Predicates group with ';' , objects with ','; output is deterministic."""
    store, pm = parse_store(EQUIV_TTL.encode(), "turtle")
    dog = "http://example.org/Dog"
    text = _ox_turtle_block(store, pm, dog)
    assert text == _ox_turtle_block(store, pm, dog)  # stable across calls
    assert "rdfs:label" in text and "@" in text  # lang tag survives
    assert " ;\n" in text  # predicate grouping
    assert text.endswith(" .")


def test_curie_cache_roundtrip_and_reuse() -> None:
    """Cached splits equal uncached curies; a hit must come from the cache."""
    _, pm = parse_store(MINI.encode(), "turtle")
    dog = "http://example.org/Dog"
    cc: dict[str, tuple[str, str] | None] = {}
    assert _ox_curie(pm, dog, cc) == _ox_curie(pm, dog) == "ex:Dog"
    assert dog in cc
    cc[dog] = ("ex", "POISONED")  # bogus memo entry
    assert _ox_curie(pm, dog, cc) == "ex:POISONED"  # served from the cache
    assert _ox_curie_for(pm, dog, cc) == ("ex", "POISONED")


def test_build_ir_with_memo_changes_nothing() -> None:
    """The threaded memo changes no observable IR content."""
    ir = _build(EQUIV_TTL)
    dog = ir.entities["http://example.org/Dog"]
    assert dog.curie == "ex:Dog"
    assert any("rdfs:label" in a.turtle for a in dog.axioms)
    assert "ex" in ir.prefixes
