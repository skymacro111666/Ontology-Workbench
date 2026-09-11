"""render: py-horned-owl 类型化公理 → Manchester 可读文本(未识别构造回落函数语法)."""

import pyoxigraph as ox

from ontoworkbench.core.owl2.render import entity_manchester

NS = "http://example.org/owl2-spike#"


def _store() -> ox.Store:
    store = ox.Store()
    store.load(path="tests/fixtures/owl2-constructs.ttl", format=ox.RdfFormat.TURTLE)
    return store


def _lines(name: str) -> list:  # type: ignore[type-arg]
    return entity_manchester(_store(), f"{NS}{name}", {}) or []


def test_restriction_axiom_renders_manchester() -> None:
    """限定基数走 Manchester 关键词:enrolledIn exactly 1 Course."""
    out = _lines("Student")
    assert "Student SubClassOf enrolledIn exactly 1 Course" in [ln.text.strip() for ln in out]


def test_lines_carry_axiom_kind() -> None:
    """每行带公理类型 kind(前端徽章与过滤的数据源)."""
    out = _lines("Student")
    assert out
    assert all(ln.kind and ln.text for ln in out)
    kinds = {ln.kind for ln in out}
    assert "SubClassOf" in kinds
    assert "ClassAssertion" in kinds


def test_fallback_lines_shorten_iris() -> None:
    """未识别公理族(如 DataPropertyAssertion)兜底行缩写 IRI,禁全 IRI 墙."""
    out = _lines("Student")
    assert all("<http" not in ln.text for ln in out)
    dpa = [ln for ln in out if ln.kind == "DataPropertyAssertion"]
    assert dpa and "moderate" in dpa[0].text


def test_boolean_connectives_render() -> None:
    """交/并组合用 and/or 连接,并内层并加括号防歧义."""
    joined = " | ".join(ln.text for ln in _lines("Undergrad"))
    assert "Student and" in joined
    assert "enrolledIn some Course or Person" in joined


def test_chain_haskey_disjointunion_render() -> None:
    """属性链/hasKey/disjointUnion 三类构造各有可读渲染."""
    assert any("locatedIn" in ln.text and "shelfIn" in ln.text for ln in _lines("locatedIn"))
    assert any("HasKey" in ln.text for ln in _lines("Person"))
    assert any("DisjointUnionOf" in ln.text for ln in _lines("University"))


def test_bridge_failure_returns_none(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """桥失败(panic 收口)→ None,调用方降级回 raw Turtle(降级纪律)."""
    import ontoworkbench.core.owl2.render as render_mod

    def boom(xml: str):  # type: ignore[no-untyped-def]
        raise render_mod.Owl2BridgeError("boom")

    monkeypatch.setattr(render_mod, "parse", boom)
    assert entity_manchester(_store(), f"{NS}Student", {}) is None
