"""SPA static serving: assets, history fallback, API paths stay JSON 404."""

from fastapi.testclient import TestClient

INDEX_HTML = "<html><body>ow-spa-marker</body></html>"


def test_root_serves_index_html(client: TestClient) -> None:
    """GET / returns the built SPA entry (html)."""
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "ow-spa-marker" in r.text


def test_client_route_falls_back_to_index(client: TestClient) -> None:
    """Deep links like /browse/<id> serve index.html (history fallback)."""
    r = client.get("/browse/0b6a3f2a-8f13-4a3e-9c2d-1d4e5f6a7b8c")
    assert r.status_code == 200
    assert "ow-spa-marker" in r.text


def test_static_assets_are_served(client: TestClient) -> None:
    """Files under dist/assets serve with their real content type."""
    r = client.get("/assets/app.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert "console.log" in r.text


def test_unknown_api_path_is_json_404(client: TestClient) -> None:
    """Unmatched /api paths never hit the SPA fallback: JSON envelope 404."""
    r = client.get("/api/nope")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["code"] == "NOT_FOUND"
    assert set(body) == {"code", "message", "data", "hint", "request_id"}
