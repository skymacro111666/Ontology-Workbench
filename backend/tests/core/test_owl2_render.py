"""render: py-horned-owl 类型化公理 → Manchester 可读文本(未识别构造回落函数语法)."""

import pyoxigraph as ox

from ontoworkbench.core.owl2.render import entity_manchester

NS = "http://example.org/owl2-spike#"


def _store() -> ox.Store:
    store = ox.Store()
    store.load(path="tests/fixtures/owl2-constructs.ttl", format=ox.RdfFormat.TURTLE)
    return store


def test_restriction_axiom_renders_manchester() -> None:
    """限定基数走 Manchester 关键词:enrolledIn exactly 1 Course."""
    out = entity_manchester(_store(), f"{NS}Student", {})
    assert out is not None
    assert "Student SubClassOf enrolledIn exactly 1 Course" in [x.strip() for x in out]


def test_boolean_connectives_render() -> None:
    """交/并组合用 and/or 连接,并内层并加括号防歧义."""
    out = entity_manchester(_store(), f"{NS}Undergrad", {})
    joined = " | ".join(out or [])
    assert "Student and" in joined
    assert "enrolledIn some Course or Person" in joined


def test_chain_haskey_disjointunion_render() -> None:
    """属性链/hasKey/disjointUnion 三类构造各有可读渲染."""
    store = _store()

    def lines(iri: str) -> list[str]:
        return entity_manchester(store, f"{NS}{iri}", {}) or []

    assert any("locatedIn" in x and "shelfIn" in x for x in lines("locatedIn"))
    assert any("HasKey" in x for x in lines("Person"))
    assert any("DisjointUnionOf" in x for x in lines("University"))


def test_bridge_failure_returns_none(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """桥失败(panic 收口)→ None,调用方降级回 raw Turtle(降级纪律)."""
    import ontoworkbench.core.owl2.render as render_mod

    def boom(xml: str):  # type: ignore[no-untyped-def]
        raise render_mod.Owl2BridgeError("boom")

    monkeypatch.setattr(render_mod, "parse", boom)
    assert entity_manchester(_store(), f"{NS}Student", {}) is None
