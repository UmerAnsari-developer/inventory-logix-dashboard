"""GAP-013 contract tests: OpenAPI spec ↔ url_map parity + backtest regression.

The spec is hand-written, so drift is the failure mode: these tests walk the
live url_map and assert every /api and /ai (method, path) appears in the
spec (and vice versa for the canonical prefixes).
"""
from __future__ import annotations

import re

from app.repositories import UserRepository


def _session_client(app, username: str):
    """Authenticated client without hitting the /auth/login rate limiter.

    Mirrors the proven pattern from tests/test_batch3_phase2.py.
    """
    from flask_login.utils import _create_identifier

    with app.app_context():
        user = UserRepository.find_by_username(username)
        assert user is not None, f"missing user {username}"
        uid = user.id

    c = app.test_client()
    ident_box: dict = {}

    def _capture():
        ident_box["id"] = _create_identifier()

    app.before_request_funcs.setdefault(None, []).append(_capture)
    try:
        resp = c.get("/static/img/favicon.svg")
        assert resp.status_code == 200
    finally:
        app.before_request_funcs[None].remove(_capture)

    with c.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
        sess["_id"] = ident_box["id"]
    return c


def _normalize(rule: str) -> str:
    """<int:id>/<sku> → {id}/{sku}; collapse the /v1 dual prefixes."""
    path = re.sub(r"<(?:[^:<>]+:)?([^<>]+)>", r"{\1}", rule)
    return re.sub(r"^/(api|ai)/v1", r"/\1", path)


def _spec_paths(app) -> dict:
    with app.test_client() as c:
        resp = c.get("/api/openapi.json")
        assert resp.status_code == 200
        return resp.get_json()["paths"]


def test_forecast_backtest_no_nameerror(app):
    """Regression: GET /ai/forecast/backtest raised NameError before the
    ForecastRepository import was added (B1). Must not 500."""
    resp = _session_client(app, "admin").get("/ai/forecast/backtest")
    assert resp.status_code != 500


def test_openapi_spec_valid(client):
    resp = client.get("/api/openapi.json")
    assert resp.status_code == 200
    spec = resp.get_json()
    assert spec["openapi"].startswith("3.0")
    assert spec["info"]["title"]
    assert "success" in spec["components"]["schemas"]["ApiResponse"]["properties"]
    assert "sessionCookie" in spec["components"]["securitySchemes"]


def _missing_from_spec(app, prefix: str) -> list:
    spec_paths = _spec_paths(app)
    missing = []
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith(prefix):
            continue
        path = _normalize(rule.rule)
        ops = spec_paths.get(path, {})
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            if method.lower() not in ops:
                missing.append((method, path))
    return missing


def test_every_api_rule_in_spec(app):
    missing = _missing_from_spec(app, "/api/")
    assert not missing, f"(method, path) pairs missing from OpenAPI spec: {missing}"


def test_every_ai_rule_in_spec(app):
    missing = _missing_from_spec(app, "/ai/")
    assert not missing, f"(method, path) pairs missing from OpenAPI spec: {missing}"


def test_spec_paths_exist_in_url_map(app):
    """Reverse parity: no stale spec entries pointing at non-existent routes."""
    live = {
        (_normalize(rule.rule), tuple(rule.methods - {"HEAD", "OPTIONS"}))
        for rule in app.url_map.iter_rules()
        if rule.rule.startswith(("/api/", "/ai/"))
    }
    live_paths = {path for path, _ in live}
    stale = [
        path for path in _spec_paths(app)
        if path not in live_paths
    ]
    assert not stale, f"spec paths not present in url_map: {stale}"
