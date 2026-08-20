"""M1 acceptance: setup → login → pizza import → browse endpoints → envelope OK."""

from urllib.parse import quote

from fastapi.testclient import TestClient


def test_samples_idempotent(client: TestClient) -> None:
    """Importing pizza twice yields the same record id (Task 11 deferral)."""
    r1 = client.post("/api/samples/pizza")
    r2 = client.post("/api/samples/pizza")
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["data"]["id"] == r2.json()["data"]["id"]
    assert r1.json()["data"]["classCount"] == 99


def test_m1_pizza_full_chain(client: TestClient) -> None:
    """Sample import → tree → entity → search → raw all return envelope OK."""
    oid = client.post("/api/samples/pizza").json()["data"]["id"]

    tree = client.get(f"/api/ontologies/{oid}/tree")
    assert tree.json()["code"] == "OK"
    assert len(tree.json()["data"]) > 0

    roots = tree.json()["data"]
    some_eid = roots[0]["eid"]
    eid = quote(some_eid, safe="")
    ent = client.get(f"/api/ontologies/{oid}/entities/{eid}")
    assert ent.json()["code"] == "OK"
    assert ent.json()["data"]["eid"] == some_eid

    nb = client.get(f"/api/ontologies/{oid}/entities/{eid}/neighbors")
    assert nb.json()["code"] == "OK" and nb.json()["data"]["nodes"]

    hits = client.get(f"/api/ontologies/{oid}/search", params={"q": "pizza"})
    assert hits.json()["code"] == "OK" and hits.json()["data"]

    raw = client.get(f"/api/ontologies/{oid}/raw/{eid}")
    assert raw.json()["code"] == "OK" and raw.json()["data"]["turtle"]

    ov = client.get(f"/api/ontologies/{oid}/overview")
    assert ov.json()["code"] == "OK"
    # pizza has ~107 entities, below the 500-node degradation threshold
    assert ov.json()["data"]["truncated"] is False
    assert ov.json()["data"]["totalCount"] >= 99
