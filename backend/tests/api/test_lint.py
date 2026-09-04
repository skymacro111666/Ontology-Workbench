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


def test_run_lint_never_evicts_pooled_store(client: TestClient, monkeypatch) -> None:
    """Lint warms the Store pool; a follow-up edit parses zero times (T12).

    Lint goes through store_for read-only — never mutating, never
    evicting — so the edit after a lint run reuses the warmed entry.
    """
    import ontoworkbench.server.cache as cache_mod

    oid = _upload(client)
    assert client.post(f"/api/ontologies/{oid}/lint/run", json={}).status_code == 200

    calls: list[int] = []
    real = cache_mod.parse_store

    def spy(data, fmt):  # noqa: ANN001 — test-local shape
        calls.append(1)
        return real(data, fmt)

    monkeypatch.setattr(cache_mod, "parse_store", spy)
    base = client.get(f"/api/ontologies/{oid}/meta").json()["data"]["fileHash"]
    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={"name": "Cat", "prefix": "ex", "parents": [], "baseFileHash": base},
    )
    assert r.status_code == 200, r.text
    assert calls == []  # the lint-warmed Store carried the edit, parse-free


def test_custom_update_rule_errors_and_nothing_lands(client: TestClient) -> None:
    """A custom rule shaped as UPDATE is a per-rule error, never a mutation.

    Even against the shared pooled Store the query must not run: the
    next successful edit would otherwise persist whatever it changed.
    """
    oid = _upload(client)
    client.put(
        f"/api/ontologies/{oid}/lint/config",
        json={
            "disabled": [],
            "custom": [
                {
                    "name": "evil",
                    "severity": "info",
                    "sparql": "DELETE WHERE { ?s ?p ?o }",
                    "enabled": True,
                }
            ],
        },
    )
    data = client.post(f"/api/ontologies/{oid}/lint/run", json={}).json()["data"]
    evil = next(res for res in data["results"] if res.get("name") == "evil")
    assert (evil["error"] or "").startswith("SPARQL_ERROR")

    # The pooled Store survived intact: the next edit persists everything.
    base = client.get(f"/api/ontologies/{oid}/meta").json()["data"]["fileHash"]
    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={"name": "Cat", "prefix": "ex", "parents": [], "baseFileHash": base},
    )
    assert r.status_code == 200, r.text
    after = client.get(f"/api/ontologies/{oid}/source").json()["data"]["content"]
    assert "ex:Cat" in after
    assert "ex:Animal" in after and "subClassOf" in after  # nothing was deleted
