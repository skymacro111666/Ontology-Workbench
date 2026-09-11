"""实体详情的 Manchester 渲染接线:载荷 manchester 字段 + 降级契约."""

import io
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from ontoworkbench.core.owl2.bridge import Owl2BridgeError

FIX = Path("tests/fixtures/owl2-constructs.ttl")
NS = "http://example.org/owl2-spike#"


@pytest.fixture()
def oid(client: TestClient) -> str:
    """Upload the owl2 constructs fixture; return its ontology id."""
    r = client.post(
        "/api/ontologies",
        files={"file": ("owl2.ttl", io.BytesIO(FIX.read_bytes()), "text/turtle")},
    )
    return r.json()["data"]["id"]


def test_entity_detail_carries_manchester(client: TestClient, oid: str) -> None:
    """Student 详情:manchester 含限定基数行(exactly 1),axioms 照旧."""
    eid = quote(f"{NS}Student", safe="")
    ent = client.get(f"/api/ontologies/{oid}/entities/{eid}").json()["data"]
    assert ent["manchester"], "manchester 字段应非空"
    assert all({"kind", "text"} <= set(line) for line in ent["manchester"])
    assert any("exactly 1" in line["text"] for line in ent["manchester"])
    assert ent["axioms"], "axioms(原始 Turtle)不因渲染失败而消失"


def test_degradation_contract_bridge_failure(
    client: TestClient, oid: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """桥失败 → manchester = null,axioms 照旧(降级纪律)."""
    import ontoworkbench.server.routers.browse as browse_mod

    def boom(*args: object, **kwargs: object) -> None:
        raise Owl2BridgeError("boom")

    monkeypatch.setattr(browse_mod, "entity_manchester", boom)
    eid = quote(f"{NS}Student", safe="")
    ent = client.get(f"/api/ontologies/{oid}/entities/{eid}").json()["data"]
    assert ent["manchester"] is None
    assert ent["axioms"]


def test_instance_detail_has_no_manchester(client: TestClient, oid: str) -> None:
    """个体详情不渲染 manchester(公理区是实体页面)."""
    # fixture 的 alice 未显式声明 NamedIndividual,临时上传一个带声明的语料
    mini = (
        f"@prefix : <{NS}> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        ":Person a owl:Class .\n"
        ":alice a :Person, owl:NamedIndividual .\n"
    ).encode()
    r = client.post(
        "/api/ontologies", files={"file": ("mini.ttl", io.BytesIO(mini), "text/turtle")}
    )
    mini_oid = r.json()["data"]["id"]
    eid = quote(f"{NS}alice", safe="")
    ind = client.get(f"/api/ontologies/{mini_oid}/entities/{eid}").json()["data"]
    assert ind["kind"] == "instance"
    assert ind.get("manchester") is None
