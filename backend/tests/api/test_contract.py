"""Golden contract: entity payload structure matches docs/api-examples."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from tests.api.test_browse_api import _upload

GOLDEN = json.loads(
    (Path(__file__).parents[3] / "docs" / "api-examples" / "success-entity.json").read_text()
)


def test_entity_payload_matches_golden_structure(client: TestClient) -> None:
    """The live entity payload carries exactly the golden file's key sets."""
    from urllib.parse import quote

    oid = _upload(client)
    eid = quote("http://example.org/Dog", safe="")
    data = client.get(f"/api/ontologies/{oid}/entities/{eid}").json()["data"]

    golden_data = GOLDEN["data"]
    assert set(data) == set(
        golden_data
    ), f"top-level drift: +{set(data) - set(golden_data)} -{set(golden_data) - set(data)}"
    assert set(data["stats"]) == set(golden_data["stats"])

    # Ref lists: live refs may carry eid (golden abbreviates); relation on
    # referencedBy is part of the contract since the M1 fix wave.
    for field in ("parents", "children"):
        for ref in data[field]:
            assert set(ref) >= {"eid", "curie"}
    for ref in data["referencedBy"]:
        assert set(ref) >= {"eid", "curie", "relation"}
    for prop in data["properties"]:
        assert set(prop) >= {"eid", "curie", "ptype"}
    for axiom in data["axioms"]:
        assert set(axiom) == set(golden_data["axioms"][0])
