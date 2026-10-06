"""Every entity/instance mutation appends one journal event (spec §8).

Field-level change recording: an update's detail carries
changes.{field}.{from,to} read from the store before and after the edit.
"""

from typing import Any
from urllib.parse import quote

from fastapi.testclient import TestClient

from tests.api.test_browse_api import _upload
from tests.api.test_entities_write import ANIMAL, DOG, TOY
from tests.api.test_instances_write import _upload as _upload_inst


def _events(client: TestClient, oid: str) -> list[dict[str, Any]]:
    return client.get(f"/api/v1/ontologies/{oid}/events?limit=200").json()["data"]["items"]


def _meta(client: TestClient, oid: str) -> dict[str, Any]:
    return client.get(f"/api/v1/ontologies/{oid}/meta").json()["data"]


def test_entity_create_and_update_events(client: TestClient) -> None:
    """Create records params+label+revisions; update records label from→to."""
    oid = _upload(client)
    r = client.post(
        f"/api/v1/ontologies/{oid}/classes",
        json={
            "name": "Payment",
            "prefix": "ex",
            "label": {"value": "Payment"},
            "baseRevision": _meta(client, oid)["revision"],
        },
    )
    assert r.status_code == 200
    ev = _events(client, oid)
    assert [e["action"] for e in ev] == ["entity.create", "ontology.import"]
    assert ev[0]["origin"] == "manual" and ev[0]["source"] == "web"
    assert ev[0]["detail"]["eid"].startswith("http://")
    assert ev[0]["detail"]["curie"] == "ex:Payment"
    assert ev[0]["detail"]["kind"] == "Class"
    assert ev[0]["detail"]["label"] == "Payment"
    assert ev[0]["detail"]["revisionBefore"] == 0
    assert ev[0]["detail"]["revisionAfter"] == 1

    iri = ev[0]["detail"]["eid"]
    ru = client.put(
        f"/api/v1/ontologies/{oid}/entities/{quote(iri, safe='')}",
        json={"label": {"value": "Zahlung"}, "baseRevision": 1},
    )
    assert ru.status_code == 200
    ev = _events(client, oid)
    assert [e["action"] for e in ev] == ["entity.update", "entity.create", "ontology.import"]
    # spec §8.2: field-level from→to, read from the store around the edit
    changes = ev[0]["detail"]["changes"]
    assert changes["label"]["from"] == {"": "Payment"}
    assert changes["label"]["to"] == {"": "Zahlung"}


def test_entity_delete_event(client: TestClient) -> None:
    """Delete records the eid + the label as it was before removal."""
    oid = _upload(client)
    client.post(
        f"/api/v1/ontologies/{oid}/classes",
        json={"name": "Payment", "prefix": "ex", "baseRevision": 0},
    )
    iri = _events(client, oid)[0]["detail"]["eid"]
    rd = client.delete(f"/api/v1/ontologies/{oid}/entities/{quote(iri, safe='')}?baseRevision=1")
    assert rd.status_code == 200
    top = _events(client, oid)[0]
    assert top["action"] == "entity.delete"
    assert top["detail"]["eid"] == iri


def test_instance_events(client: TestClient) -> None:
    """Instance create lands with kind, classes and an assertion summary."""
    oid, meta = _upload_inst(client)
    r = client.post(
        f"/api/v1/ontologies/{oid}/instances",
        json={
            "name": "BallLightning",
            "prefix": "ex",
            "classes": ["http://example.org/Novel"],
            "baseRevision": meta["revision"],
        },
    )
    assert r.status_code == 200
    top = _events(client, oid)[0]
    assert top["action"] == "instance.create"
    assert top["detail"]["kind"] == "Instance"
    assert top["detail"]["classes"] == ["http://example.org/Novel"]
    assert top["detail"]["curie"] == "ex:BallLightning"


def test_entity_create_records_structure(client: TestClient) -> None:
    """Creates journal the request's structure params: parents, domains, ranges."""
    oid = _upload(client)
    r = client.post(
        f"/api/v1/ontologies/{oid}/classes",
        json={"name": "Payment", "prefix": "ex", "parents": [ANIMAL], "baseRevision": 0},
    )
    assert r.status_code == 200
    detail = _events(client, oid)[0]["detail"]
    assert detail["parents"] == [ANIMAL]

    r = client.post(
        f"/api/v1/ontologies/{oid}/properties",
        json={
            "name": "playsWith",
            "prefix": "ex",
            "ptype": "ObjectProperty",
            "domains": [DOG],
            "ranges": [TOY],
            "baseRevision": 1,
        },
    )
    assert r.status_code == 200
    detail = _events(client, oid)[0]["detail"]
    assert detail["kind"] == "ObjectProperty"
    assert detail["domains"] == [DOG]
    assert detail["ranges"] == [TOY]


def test_instance_update_comment_event(client: TestClient) -> None:
    """A comment-only instance edit records comment from→to (spec §8.2)."""
    oid, meta = _upload_inst(client)
    r = client.post(
        f"/api/v1/ontologies/{oid}/instances",
        json={
            "name": "BallLightning",
            "prefix": "ex",
            "classes": ["http://example.org/Novel"],
            "baseRevision": meta["revision"],
        },
    )
    assert r.status_code == 200
    eid = _events(client, oid)[0]["detail"]["eid"]
    ru = client.put(
        f"/api/v1/ontologies/{oid}/instances/{quote(eid, safe='')}",
        json={"comment": "second edition", "baseRevision": 1},
    )
    assert ru.status_code == 200
    top = _events(client, oid)[0]
    assert top["action"] == "instance.update"
    changes = top["detail"]["changes"]
    assert changes["comment"] == {"from": None, "to": "second edition"}


def test_events_cursor_pagination(client: TestClient) -> None:
    """id-anchored pages: newest-first, no overlap across ongoing writes."""
    oid = _upload(client)
    for n in range(3):
        r = client.post(
            f"/api/v1/ontologies/{oid}/classes",
            json={"name": f"K{n}", "prefix": "ex", "baseRevision": n},
        )
        assert r.status_code == 200
    page1 = client.get(f"/api/v1/ontologies/{oid}/events?limit=2").json()["data"]
    assert len(page1["items"]) == 2
    assert page1["nextBeforeId"] == page1["items"][-1]["id"]
    page2 = client.get(
        f"/api/v1/ontologies/{oid}/events",
        params={"limit": 2, "before_id": page1["nextBeforeId"]},
    ).json()["data"]
    ids = [e["id"] for e in page1["items"] + page2["items"]]
    assert len(set(ids)) == len(ids)  # no overlap, strictly descending
    assert ids == sorted(ids, reverse=True)
