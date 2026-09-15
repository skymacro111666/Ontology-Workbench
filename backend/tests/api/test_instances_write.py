"""Instance CRUD (B2): create/delete via the Y-axis incremental pipeline.

Every mutation rides _commit_mutation (baseRevision lock, IR patch,
debounced autosave) exactly like entities.py; tests that read the file
wait for the autosave to land first.
"""

import io
from typing import Any

from fastapi.testclient import TestClient

from tests.api.test_entities_write import _wait_landed

TB = "http://example.org/ThreeBody"
NOVEL = "http://example.org/Novel"
FANFIC = "http://example.org/FanFic"

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

# 数据断言用最小本体:rating 无 rdfs:range → 写入路径默认 xsd:string(正是
# 曾被 IR 过滤吞掉的场景)
MINI_DATA = b"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Novel a owl:Class .
ex:rating a owl:DatatypeProperty ; rdfs:domain ex:Novel .
ex:ThreeBody a owl:NamedIndividual , ex:Novel ; rdfs:label "ThreeBody" .
"""


def _upload(client: TestClient, data: bytes = MINI_INST) -> tuple[str, dict[str, Any]]:
    r = client.post(
        "/api/v1/ontologies", files={"file": ("mini.ttl", io.BytesIO(data), "text/turtle")}
    )
    assert r.status_code == 201
    return r.json()["data"]["id"], r.json()["data"]


def _source(client: TestClient, oid: str) -> str:
    return client.get(f"/api/v1/ontologies/{oid}/source").json()["data"]["content"]


def _revision(client: TestClient, oid: str) -> int:
    return client.get(f"/api/v1/ontologies/{oid}/meta").json()["data"]["revision"]


def test_create_instance_lands_types_and_label(client: TestClient, autosave_debounce_50ms) -> None:
    """Create instance with types and label, verify persistence."""
    oid, meta = _upload(client)
    r = client.post(
        f"/api/v1/ontologies/{oid}/instances",
        json={
            "name": "BallLightning",
            "prefix": "ex",
            "classes": ["http://example.org/Novel"],
            "comment": "fan fic",
            "baseRevision": meta["revision"],
        },
    )
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["entity"]["curie"] == "ex:BallLightning"
    assert d["meta"]["instanceCount"] == meta["instanceCount"] + 1
    assert d["meta"]["revision"] == 1
    # 读路径立即可见(补丁后的 IR,字节尚未落盘)
    got = client.get(
        f"/api/v1/ontologies/{oid}/entities/http%3A%2F%2Fexample.org%2FBallLightning"
    ).json()["data"]
    assert got["kind"] == "instance"
    assert got["label"] == {"en": "BallLightning"}
    assert [c["curie"] for c in got["classes"]] == ["ex:Novel"]
    # 落盘:NamedIndividual + 类型 + label(=name 纯字面量)
    _wait_landed(client, oid)
    src = _source(client, oid)
    assert "ex:BallLightning" in src


def test_create_instance_guards(client: TestClient, autosave_debounce_50ms) -> None:
    """Create instance guards: undeclared class and duplicate IRI."""
    oid, meta = _upload(client)
    # 未声明类 → 422
    r = client.post(
        f"/api/v1/ontologies/{oid}/instances",
        json={
            "name": "X",
            "prefix": "ex",
            "classes": ["http://example.org/Nope"],
            "baseRevision": meta["revision"],
        },
    )
    assert r.status_code == 422
    # 重复 IRI → DUPLICATE_ENTITY 409
    r = client.post(
        f"/api/v1/ontologies/{oid}/instances",
        json={
            "name": "ThreeBody",
            "prefix": "ex",
            "classes": ["http://example.org/Novel"],
            "baseRevision": meta["revision"],
        },
    )
    assert r.status_code == 409


def test_delete_instance_removes_assertions_both_ends(
    client: TestClient, autosave_debounce_50ms
) -> None:
    """Delete instance removes subject and object property assertions."""
    oid, meta = _upload(client)
    # ThreeBody: 自引用(subject) + 被 FanSequel 引用(object)
    # 删除后: FanSequel ex:inspiredBy ex:ThreeBody 应被删除,但 ex:knows(非声明属性)应保留
    r = client.delete(
        f"/api/v1/ontologies/{oid}/instances/{TB}", params={"baseRevision": meta["revision"]}
    )
    assert r.status_code == 200
    assert r.json()["data"]["meta"]["revision"] == 1
    # 读路径立即 404(实例从 IR 摘除)
    assert client.get(f"/api/v1/ontologies/{oid}/entities/{TB}").status_code == 404
    _wait_landed(client, oid)
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


def _put(client: TestClient, oid: str, eid: str, body: dict) -> dict:
    from urllib.parse import quote

    r = client.put(f"/api/v1/ontologies/{oid}/instances/{quote(eid, safe='')}", json=body)
    return r  # type: ignore[return-value]


def test_update_instance_replaces_assertions(client: TestClient, autosave_debounce_50ms) -> None:
    """Update instance comment, classes, and assertions with full replacement."""
    oid, meta = _upload(client)
    # Replace the self-loop (ThreeBody → ThreeBody) with ThreeBody → FanSequel
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
                    "value": "http://example.org/FanSequel",  # DIFFERENT from fixture's self-loop
                },
            ],
            "baseRevision": meta["revision"],
        },
    )
    assert r.status_code == 200
    got = client.get(f"/api/v1/ontologies/{oid}/entities/{TB}").json()["data"]
    assert got["comment"] == "updated"
    assert [c["curie"] for c in got["classes"]] == ["ex:FanFic"]
    assert len(got["objectAssertions"]) == 1
    _wait_landed(client, oid)
    # Old self-loop must be GONE (this fails if sweep loop is deleted)
    src = _source(client, oid)
    assert "ex:ThreeBody ex:inspiredBy ex:ThreeBody" not in src
    # New assertion must be present (Turtle serializer uses ; separator)
    assert "ex:inspiredBy ex:FanSequel" in src


def test_update_instance_data_assertion_string_roundtrip(
    client: TestClient, autosave_debounce_50ms
) -> None:
    """Default-datatype (xsd:string) data assertions read back from the IR.

    The IR build historically dropped bare-string literals (RDF 1.1: they
    report datatype xsd:string), so a PUT that landed 200 vanished from
    the instance payload — and the UI's next full-replace PUT deleted them from
    the file. Write with no explicit datatype, then read back.
    """
    oid, _ = _upload(client, MINI_DATA)
    r = _put(
        client,
        oid,
        TB,
        {
            "assertions": [
                {"property": "http://example.org/rating", "kind": "data", "value": "5 stars"},
            ],
            "baseRevision": _revision(client, oid),
        },
    )
    assert r.status_code == 200
    got = client.get(f"/api/v1/ontologies/{oid}/entities/{TB}").json()["data"]
    assert [(a["property"]["curie"], a["value"], a["datatype"]) for a in got["dataAssertions"]] == [
        ("ex:rating", "5 stars", "http://www.w3.org/2001/XMLSchema#string")
    ]
    # UI 契约:全量替换 PUT 原样回传页面所见(含完整 datatype IRI)→ 不丢
    r = _put(
        client,
        oid,
        TB,
        {
            "assertions": [
                {
                    "property": "http://example.org/rating",
                    "kind": "data",
                    "value": "5 stars",
                    "datatype": "http://www.w3.org/2001/XMLSchema#string",
                },
            ],
            "baseRevision": _revision(client, oid),
        },
    )
    assert r.status_code == 200
    _wait_landed(client, oid)
    assert '"5 stars"' in _source(client, oid)


def test_update_instance_clears_all_assertions(client: TestClient, autosave_debounce_50ms) -> None:
    """Empty assertions list clears all declared assertions; undeclared references survive."""
    oid, meta = _upload(client)
    r = _put(client, oid, TB, {"assertions": [], "baseRevision": meta["revision"]})
    assert r.status_code == 200
    got = client.get(f"/api/v1/ontologies/{oid}/entities/{TB}").json()["data"]
    # All declared assertions cleared
    assert got["objectAssertions"] == []
    assert got["dataAssertions"] == []
    _wait_landed(client, oid)
    # Verify old assertion is gone from source
    src = _source(client, oid)
    assert "ex:ThreeBody ex:inspiredBy ex:ThreeBody" not in src
    # UNDECLARED ex:knows reference (FanSequel → ThreeBody) must survive
    # This is the object-end of an undeclared property pointing at TB
    assert "ex:knows ex:ThreeBody" in src


def test_update_instance_validation(client: TestClient, autosave_debounce_50ms) -> None:
    """Validate assertion updates.

    Undeclared property, non-instance object value, kind mismatch, bad kind value.
    """
    oid, _ = _upload(client)
    h = _revision(client, oid)
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
            "baseRevision": h,
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
            "baseRevision": h,
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
            "baseRevision": h,
        },
    )
    assert r.status_code == 422
    # kind 值无效 (banana 不是 "object" 或 "data")
    r = _put(
        client,
        oid,
        TB,
        {
            "assertions": [
                {
                    "property": "http://example.org/inspiredBy",
                    "kind": "banana",
                    "value": "http://example.org/ThreeBody",
                }
            ],
            "baseRevision": h,
        },
    )
    assert r.status_code == 422


def test_update_instance_untouched_keys_stay(client: TestClient, autosave_debounce_50ms) -> None:
    """Absent keys unchanged;stale revision → 409(照抄 A2 语义)。."""
    oid, meta = _upload(client)
    r = _put(client, oid, TB, {"baseRevision": meta["revision"]})
    assert r.status_code == 200
    got = client.get(f"/api/v1/ontologies/{oid}/entities/{TB}").json()["data"]
    assert got["label"] == {"en": "ThreeBody"}  # label 永不动
    r = _put(client, oid, TB, {"comment": "x", "baseRevision": meta["revision"] + 7})
    assert r.status_code == 409


def test_instance_create_visible_immediately_and_regroups_on_retype(
    client: TestClient, autosave_debounce_50ms
) -> None:
    """Y 轴核心契约:实例创建毫秒级可见、retype 即时换桶(不落盘也成立).

    - POST 返回即带新 revision,saveState=pending
    - 实例 GET 立即可见;类 badge(instances 端点)即时 +1
    - 改 rdf:type 后:新类含它、旧类不含,individuals 归组与全量重建一致
    """
    from urllib.parse import quote

    oid, meta = _upload(client)
    assert meta["revision"] == 0
    r = client.post(
        f"/api/v1/ontologies/{oid}/instances",
        json={
            "name": "james",
            "prefix": "ex",
            "classes": [FANFIC],
            "baseRevision": meta["revision"],
        },
    )
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["meta"]["revision"] == 1
    assert d["meta"]["saveState"] == "pending"
    james = "http://example.org/james"

    # 读路径立即可见:实例页 + 类 badge 归组(FanFic 1 个、Novel 仍只有 ThreeBody)
    inst = client.get(f"/api/v1/ontologies/{oid}/entities/{quote(james, safe='')}").json()["data"]
    assert inst["kind"] == "instance"
    assert [c["eid"] for c in inst["classes"]] == [FANFIC]
    fanfic = client.get(f"/api/v1/ontologies/{oid}/entities/{FANFIC}/instances").json()["data"]
    assert [n["id"] for n in fanfic["nodes"]] == ["http://example.org/FanSequel", james]
    novel = client.get(f"/api/v1/ontologies/{oid}/entities/{NOVEL}/instances").json()["data"]
    assert [n["id"] for n in novel["nodes"]] == [TB]

    # retype:james 换到 Novel → 新类含它、旧类不含(个体行归位)
    r = _put(
        client,
        oid,
        james,
        {"classes": [NOVEL], "baseRevision": _revision(client, oid)},
    )
    assert r.status_code == 200
    inst = client.get(f"/api/v1/ontologies/{oid}/entities/{quote(james, safe='')}").json()["data"]
    assert [c["eid"] for c in inst["classes"]] == [NOVEL]
    novel = client.get(f"/api/v1/ontologies/{oid}/entities/{NOVEL}/instances").json()["data"]
    assert {n["id"] for n in novel["nodes"]} == {TB, james}
    fanfic = client.get(f"/api/v1/ontologies/{oid}/entities/{FANFIC}/instances").json()["data"]
    assert [n["id"] for n in fanfic["nodes"]] == ["http://example.org/FanSequel"]
    # 实例总数不动(retype 不产生/消灭个体;创建时已 +1)
    meta2 = client.get(f"/api/v1/ontologies/{oid}/meta").json()["data"]
    assert meta2["instanceCount"] == meta["instanceCount"] + 1
    assert meta2["revision"] == 2
