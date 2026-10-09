"""Shared chat-piece fixtures: a small parsed store + Indexes + tool ctx."""

import types
from uuid import uuid4

import pytest

from ontoworkbench.core.indexes import build_indexes
from ontoworkbench.core.ir import build_ir_store
from ontoworkbench.core.parsing import parse_store
from ontoworkbench.server.chat.tools import ChatToolContext

SMALL_TTL = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/o#> .
<http://example.org/o> a owl:Ontology .
ex:Customer a owl:Class ; rdfs:label "客户" .
ex:Order a owl:Class .
ex:hasCustomer a owl:ObjectProperty .
""".encode()


@pytest.fixture()
def small_ctx() -> ChatToolContext:
    """A ChatToolContext over the small fixture store.

    No Request — the tools under test never touch it.
    """
    store, prefixes = parse_store(SMALL_TTL, "turtle")
    ix = build_indexes(build_ir_store(store, prefixes))
    row = types.SimpleNamespace(
        id=uuid4(),
        title="演示本体",
        filename="demo.ttl",
        format="turtle",
        storage_path="",
        file_hash="",
        class_count=2,
        property_count=1,
        instance_count=0,
        axiom_count=3,
        revision=1,
    )
    return ChatToolContext(request=None, row=row, ix=ix, store=store, prefixes=prefixes)  # type: ignore[arg-type]
