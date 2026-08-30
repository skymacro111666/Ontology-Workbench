"""Instance CRUD (B2): create/delete via the A2 write pipeline."""

import io
from typing import Any

from fastapi.testclient import TestClient

LIB = "https://example.org/library#"
SF = f"{LIB}ScienceFiction"
TB = "http://example.org/ThreeBody"
CREATOR = f"{LIB}LiuCixin"
HAS_CREATOR = f"{LIB}hasCreator"

# 最小本体:一个类、一个对象属性、一个实例、一条对象断言
MINI_INST = b"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
ex:Novel a owl:Class .
ex:FanFic a owl:Class .
ex:inspiredBy a owl:ObjectProperty ; rdfs:domain ex:Novel ; rdfs:range ex:Novel .
ex:ThreeBody a owl:NamedIndividual , ex:Novel ;
  rdfs:label "ThreeBody" ; ex:inspiredBy ex:ThreeBody .
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
    # ThreeBody inspiredBy 自身:主语与宾语两端各一条
    r = client.delete(
        f"/api/ontologies/{oid}/instances/{TB}", params={"baseFileHash": meta["fileHash"]}
    )
    assert r.status_code == 200
    assert r.json()["data"]["removed"] >= 4  # type×2 + label + inspiredBy(主语) + inspiredBy(宾语)
    assert "ex:ThreeBody" not in _source(client, oid)
    assert client.get(f"/api/ontologies/{oid}/entities/{TB}").status_code == 404
