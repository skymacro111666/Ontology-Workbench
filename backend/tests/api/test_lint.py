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


def test_run_lint_endpoint_assembles_builtin_and_custom(client: TestClient) -> None:
    """Run honors disabled builtins, adds custom SPARQL rules, counts severities."""
    oid = _upload(client)
    client.put(
        f"/api/ontologies/{oid}/lint/config",
        json={
            "disabled": ["missing-label"],
            "custom": [
                {
                    "name": "x",
                    "severity": "info",
                    "sparql": "SELECT ?s WHERE { ?s ?p ?o } LIMIT 3",
                    "enabled": True,
                }
            ],
        },
    )
    r = client.post(f"/api/ontologies/{oid}/lint/run", json={})
    assert r.status_code == 200
    data = r.json()["data"]
    ids = {res["ruleId"] for res in data["results"]}
    assert "missing-label" not in ids
    assert "disjoint-parents" in ids and "domain-range" in ids
    assert any(res.get("name") == "x" for res in data["results"])
    assert set(data["counts"]) == {"error", "warning", "info"}
    assert data["fileHash"]

    # onlyRuleId 只跑一条(设置对话框的「测试」)
    rid = next(res for res in data["results"] if res.get("name") == "x")["ruleId"]
    r = client.post(f"/api/ontologies/{oid}/lint/run", json={"onlyRuleId": rid})
    assert len(r.json()["data"]["results"]) == 1
