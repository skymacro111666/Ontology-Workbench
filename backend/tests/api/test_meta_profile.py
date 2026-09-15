"""GET /meta 的 profile 字段:惰性现算 + stats_json 缓存 + 超限/失败降级 null."""

import io
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

FIX = Path("tests/fixtures/owl2-constructs.ttl")


def _upload(client: TestClient) -> str:
    r = client.post(
        "/api/v1/ontologies",
        files={"file": ("owl2.ttl", io.BytesIO(FIX.read_bytes()), "text/turtle")},
    )
    return r.json()["data"]["id"]


def _boom(*args: object, **kwargs: object) -> Any:
    raise RuntimeError("boom")


def test_meta_carries_profile(client: TestClient) -> None:
    """owl2 fixture:profile.top == DL,证据与 camelCase 键齐备."""
    oid = _upload(client)
    p = client.get(f"/api/v1/ontologies/{oid}/meta").json()["data"]["profile"]
    assert p is not None
    assert p["top"] == "DL"
    assert p["approximate"] is True
    assert p["axiomCount"] > 0
    assert any("qualifiedCardinality" in v["axiom"] for v in p["violations"])


def test_profile_cached_in_stats_json(client: TestClient, monkeypatch: Any) -> None:
    """第二次 GET 走 stats_json 缓存:classify 挂了也照样服务."""
    import ontoworkbench.server.routers.ontologies as om

    oid = _upload(client)
    assert client.get(f"/api/v1/ontologies/{oid}/meta").json()["data"]["profile"]["top"] == "DL"
    monkeypatch.setattr(om, "classify", _boom)
    assert client.get(f"/api/v1/ontologies/{oid}/meta").json()["data"]["profile"]["top"] == "DL"


def test_classify_failure_degrades_to_null(client: TestClient, monkeypatch: Any) -> None:
    """现算失败 → profile = null,meta 其余字段照旧(不阻塞)."""
    import ontoworkbench.server.routers.ontologies as om

    oid = _upload(client)
    monkeypatch.setattr(om, "classify", _boom)
    data = client.get(f"/api/v1/ontologies/{oid}/meta").json()["data"]
    assert data["profile"] is None
    assert data["filename"] == "owl2.ttl"


def test_oversize_skips_compute(client: TestClient, monkeypatch: Any) -> None:
    """实体数超阈值 → 不现算,profile = null."""
    import ontoworkbench.server.routers.ontologies as om

    oid = _upload(client)
    monkeypatch.setattr(om, "_PROFILE_MAX_ENTITIES", 0)
    called: list[int] = []
    monkeypatch.setattr(om, "classify", lambda *a, **k: called.append(1) or {})
    assert client.get(f"/api/v1/ontologies/{oid}/meta").json()["data"]["profile"] is None
    assert not called


def test_save_invalidates_cached_profile(client: TestClient) -> None:
    """保存重写 stats_json → 旧 profile 失效,重新现算."""
    oid = _upload(client)
    assert client.get(f"/api/v1/ontologies/{oid}/meta").json()["data"]["profile"] is not None
    src = client.get(f"/api/v1/ontologies/{oid}/source").json()["data"]
    put = client.put(
        f"/api/v1/ontologies/{oid}/source",
        json={"content": src["content"], "baseFileHash": src["fileHash"]},
    )
    assert put.status_code == 200
    p = client.get(f"/api/v1/ontologies/{oid}/meta").json()["data"]["profile"]
    assert p is not None and p["top"] == "DL"
