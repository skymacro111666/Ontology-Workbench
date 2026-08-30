"""Lint config: per-ontology rule toggles + custom SPARQL rules (B3)."""

from fastapi.testclient import TestClient

from tests.api.test_browse_api import _upload


def test_config_roundtrip_and_defaults(client: TestClient) -> None:
    """Fresh ontology carries no config; PUT overwrites the whole set."""
    oid = _upload(client)
    r = client.get(f"/api/ontologies/{oid}/lint/config")
    assert r.status_code == 200
    assert r.json()["data"] == {"disabled": [], "custom": []}

    body = {
        "disabled": ["missing-label", "duplicate-label"],
        "custom": [
            {
                "name": "老书",
                "severity": "info",
                "sparql": "SELECT ?s WHERE { ?s <http://example.org/year> ?y . FILTER(?y < 1950) }",
                "enabled": True,
            }
        ],
    }
    assert client.put(f"/api/ontologies/{oid}/lint/config", json=body).status_code == 200
    data = client.get(f"/api/ontologies/{oid}/lint/config").json()["data"]
    assert data["disabled"] == ["missing-label", "duplicate-label"]
    assert len(data["custom"]) == 1 and data["custom"][0]["name"] == "老书"
    assert data["custom"][0]["id"]  # uuid 持久,供 onlyRuleId


def test_config_rejects_bad_severity_and_foreign_ontology(client: TestClient) -> None:
    """Severity outside the enum and unknown oids both 4xx."""
    oid = _upload(client)
    bad = {
        "disabled": [],
        "custom": [{"name": "x", "severity": "fatal", "sparql": "SELECT ?s WHERE {}"}],
    }
    assert client.put(f"/api/ontologies/{oid}/lint/config", json=bad).status_code == 422
    ghost = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/ontologies/{ghost}/lint/config").status_code == 404
