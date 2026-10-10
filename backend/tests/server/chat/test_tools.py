"""Chat tools: search/tree/entity shapes, SPARQL row cap, clipping, unknown."""

import json

from ontoworkbench.server.chat import tools
from ontoworkbench.server.chat.tools import clip_result, execute_tool

_OWL_CLASS = "<http://www.w3.org/2002/07/owl#Class>"


def test_search_tree_entity_ontology_shapes(small_ctx) -> None:
    """The read tools serialize camelCase with their metadata fields."""
    hits = json.loads(execute_tool("search_entities", {"q": "Customer"}, small_ctx))
    assert hits["items"][0]["curie"] == "ex:Customer"
    assert "matchedField" in hits["items"][0]
    assert hits["limitReached"] is False

    tree = json.loads(execute_tool("get_class_tree", {}, small_ctx))
    assert {n["curie"] for n in tree} == {"ex:Customer", "ex:Order"}

    # eid is the full IRI (the same shape search_entities hands back)
    ent = json.loads(execute_tool("get_entity", {"eid": hits["items"][0]["eid"]}, small_ctx))
    assert ent["entity"]["curie"] == "ex:Customer"
    assert "neighbors" in ent

    meta = json.loads(execute_tool("get_ontology", {}, small_ctx))
    assert meta["title"] == "演示本体" and meta["classCount"] == 2

    missing = json.loads(
        execute_tool("get_entity", {"eid": "http://example.org/o#Nope"}, small_ctx)
    )
    assert missing == {"error": "entity not found"}


def test_sparql_row_cap(small_ctx, monkeypatch) -> None:
    """Select results slice at SPARQL_ROW_CAP with rowsTruncated set."""
    monkeypatch.setattr(tools, "SPARQL_ROW_CAP", 1)
    out = json.loads(
        execute_tool("sparql_query", {"qs": f"SELECT ?c WHERE {{ ?c a {_OWL_CLASS} }}"}, small_ctx)
    )
    assert out["rowCount"] == 1
    assert out["rowsTruncated"] is True


def test_clip_appends_note() -> None:
    """Byte-clipping lands on a UTF-8 boundary and appends the refine note."""
    clipped = clip_result("x" * 100, limit_bytes=10)
    assert clipped.encode()[:10] == b"xxxxxxxxxx"  # boundary intact
    assert "已截断" in clipped
    assert "更精确" in clipped
    assert clip_result("short", limit_bytes=10) == "short"
    # multi-byte char cut lands on the boundary, not mid-sequence
    wide = clip_result("长" * 100, limit_bytes=7)
    wide.encode("utf-8")  # must not raise


def test_unknown_tool_is_json_error(small_ctx) -> None:
    """Unknown names return a JSON error payload, never raise."""
    out = json.loads(execute_tool("nope", {}, small_ctx))
    assert "error" in out and "nope" in out["error"]


def test_search_kind_maps_to_internal_vocab(small_ctx) -> None:
    """The wire enum filters for real.

    class→Class, individual→Instance, property covers the whole property
    family.
    """
    classes = json.loads(execute_tool("search_entities", {"q": "e", "kind": "class"}, small_ctx))
    assert classes["items"], "kind=class must match Class entities"
    assert all(h["type"] == "Class" for h in classes["items"])

    props = json.loads(
        execute_tool("search_entities", {"q": "hasCustomer", "kind": "property"}, small_ctx)
    )
    assert [h["curie"] for h in props["items"]] == ["ex:hasCustomer"]
    assert props["items"][0]["type"] == "ObjectProperty"

    individuals = json.loads(
        execute_tool("search_entities", {"q": "alice", "kind": "individual"}, small_ctx)
    )
    assert [h["type"] for h in individuals["items"]] == ["Instance"]
