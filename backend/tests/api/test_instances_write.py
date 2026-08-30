"""Instance CRUD (B2): create/delete via the A2 write pipeline."""

import io
from typing import Any

from fastapi.testclient import TestClient

TB = "http://example.org/ThreeBody"

# 最小本体:两个类、一个对象属性、两个实例、三条断言
# ThreeBody: 自引用 inspiredBy + 被 FanSequel 引用(对象端)
MINI_INST = b"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
ex:Novel a owl:Class .
ex:FanFic a owl:Class .
ex:inspiredBy a owl:ObjectProperty ; rdfs:domain ex:Novel ; rdfs:range ex:Novel .
ex:ThreeBody a owl:NamedIndividual , ex:Novel ;
  rdfs:label "ThreeBody" ; ex:inspiredBy ex:ThreeBody .
ex:FanSequel a owl:NamedIndividual , ex:FanFic ;
  ex:inspiredBy ex:ThreeBody ; ex:knows ex:ThreeBody .
"""


def _upload(client: TestClient, data: bytes = MINI_INST) -> tuple[str, dict[str, Any]]:
    r = client.post(
        "/api/ontologies", files={"file": ("mini.ttl", io.BytesIO(data), "text/turtle")}
    )
    assert r.status_code == 201
    return r.json()["data"]["id"], r.json()["data"]


def _source(client: TestClient, oid: str) -> str:
    return client.get(f"/api/ontologies/{oid}/source").json()["data"]["content"]


def test_create_instance_lands_types_and_label(client: TestClient) -> None:
    """Create instance with types and label, verify persistence."""
    oid, meta = _upload(client)
    r = client.post(
        f"/api/ontologies/{oid}/instances",
        json={
            "name": "BallLightning",
            "prefix": "ex",
            "classes": ["http://example.org/Novel"],
            "comment": "fan fic",
            "baseFileHash": meta["fileHash"],
        },
    )
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["entity"]["curie"] == "ex:BallLightning"
    assert d["meta"]["instanceCount"] == meta["instanceCount"] + 1
    # 落盘:NamedIndividual + 类型 + label(=name 纯字面量)
    src = _source(client, oid)
    assert "ex:BallLightning" in src
    got = client.get(
        f"/api/ontologies/{oid}/entities/http%3A%2F%2Fexample.org%2FBallLightning"
    ).json()["data"]
    assert got["kind"] == "instance"
    assert got["label"] == {"en": "BallLightning"}
    assert [c["curie"] for c in got["classes"]] == ["ex:Novel"]


def test_create_instance_guards(client: TestClient) -> None:
    """Create instance guards: undeclared class and duplicate IRI."""
    oid, meta = _upload(client)
    # 未声明类 → 422
    r = client.post(
        f"/api/ontologies/{oid}/instances",
        json={
            "name": "X",
            "prefix": "ex",
            "classes": ["http://example.org/Nope"],
            "baseFileHash": meta["fileHash"],
        },
    )
    assert r.status_code == 422
    # 重复 IRI → DUPLICATE_ENTITY 409
    r = client.post(
        f"/api/ontologies/{oid}/instances",
        json={
            "name": "ThreeBody",
            "prefix": "ex",
            "classes": ["http://example.org/Novel"],
            "baseFileHash": meta["fileHash"],
        },
    )
    assert r.status_code == 409


def test_delete_instance_removes_assertions_both_ends(client: TestClient) -> None:
    """Delete instance removes subject and object property assertions."""
    oid, meta = _upload(client)
    # ThreeBody: 自引用(subject) + 被 FanSequel 引用(object)
    # 删除后: FanSequel ex:inspiredBy ex:ThreeBody 应被删除,但 ex:knows(非声明属性)应保留
    r = client.delete(
        f"/api/ontologies/{oid}/instances/{TB}", params={"baseFileHash": meta["fileHash"]}
    )
    assert r.status_code == 200
    # 移除数: ThreeBody 的 type×2 + label + inspiredBy 自引用 + FanSequel 的 inspiredBy(object端)
    assert r.json()["data"]["removed"] >= 5
    src = _source(client, oid)
    # FanSequel ex:inspiredBy ex:ThreeBody 必须被删除(对象端清理)
    assert "ex:FanSequel" in src
    assert "ex:inspiredBy ex:ThreeBody" not in src
    # ex:knows ex:ThreeBody 必须保留(保守剪裁:非声明属性不断开)
    assert "ex:knows ex:ThreeBody" in src
    # ThreeBody 的主语三元组必须全部删除(包括 NamedIndividual 类型断言)
    assert "ex:ThreeBody a owl:NamedIndividual" not in src
    assert "ex:ThreeBody a ex:Novel" not in src
    assert "ex:ThreeBody rdfs:label" not in src
    assert client.get(f"/api/ontologies/{oid}/entities/{TB}").status_code == 404


def _put(client: TestClient, oid: str, eid: str, body: dict) -> dict:
    from urllib.parse import quote

    r = client.put(f"/api/ontologies/{oid}/instances/{quote(eid, safe='')}", json=body)
    return r  # type: ignore[return-value]


def test_update_instance_replaces_assertions(client: TestClient) -> None:
    """Update instance comment, classes, and assertions with full replacement."""
    oid, meta = _upload(client)
    new_hash = client.get(f"/api/ontologies/{oid}/meta").json()["data"]["fileHash"]
    r = _put(
        client,
        oid,
        TB,
        {
            "comment": "updated",
            "classes": ["http://example.org/FanFic"],
            "assertions": [
                {
                    "property": "http://example.org/inspiredBy",
                    "kind": "object",
                    "value": "http://example.org/ThreeBody",
                },
            ],
            "baseFileHash": new_hash,
        },
    )
    assert r.status_code == 200
    got = client.get(f"/api/ontologies/{oid}/entities/{TB}").json()["data"]
    assert got["comment"] == "updated"
    assert [c["curie"] for c in got["classes"]] == ["ex:FanFic"]
    assert len(got["objectAssertions"]) == 1
    assert "ex:inspiredBy" in _source(client, oid)


def test_update_instance_validation(client: TestClient) -> None:
    """Validate assertion updates: undeclared property, non-instance object value, kind mismatch."""
    oid, _ = _upload(client)
    h = client.get(f"/api/ontologies/{oid}/meta").json()["data"]["fileHash"]
    # 属性未声明
    r = _put(
        client,
        oid,
        TB,
        {
            "assertions": [
                {
                    "property": "http://example.org/nope",
                    "kind": "object",
                    "value": "http://example.org/ThreeBody",
                }
            ],
            "baseFileHash": h,
        },
    )
    assert r.status_code == 422
    # 对象断言值不是实例
    r = _put(
        client,
        oid,
        TB,
        {
            "assertions": [
                {
                    "property": "http://example.org/inspiredBy",
                    "kind": "object",
                    "value": "http://example.org/Novel",
                }
            ],
            "baseFileHash": h,
        },
    )
    assert r.status_code == 422
    # kind 与属性类型错配
    r = _put(
        client,
        oid,
        TB,
        {
            "assertions": [
                {
                    "property": "http://example.org/inspiredBy",
                    "kind": "data",
                    "value": "x",
                    "datatype": "http://www.w3.org/2001/XMLSchema#string",
                }
            ],
            "baseFileHash": h,
        },
    )
    assert r.status_code == 422


def test_update_instance_untouched_keys_stay(client: TestClient) -> None:
    """Absent keys unchanged;stale hash → 409(照抄 A2 语义)。."""
    oid, meta = _upload(client)
    r = _put(client, oid, TB, {"baseFileHash": meta["fileHash"]})
    assert r.status_code == 200
    got = client.get(f"/api/ontologies/{oid}/entities/{TB}").json()["data"]
    assert got["label"] == {"en": "ThreeBody"}  # label 永不动
    r = _put(client, oid, TB, {"comment": "x", "baseFileHash": "stale"})
    assert r.status_code == 409
