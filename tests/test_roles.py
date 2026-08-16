"""Tests for role-based access control and viewer restrictions."""
from __future__ import annotations

import time


def _login(client, username: str, password: str):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password, "remember": "on"},
        follow_redirects=False,
    )


def test_register_always_creates_viewer(app):
    """Self-registration is always a viewer, even if admin is requested."""
    client = app.test_client()
    username = f"view{int(time.time())}"
    resp = client.post(
        "/auth/register",
        data={
            "username": username,
            "email": f"{username}@example.com",
            "password": "StrongPass1!",
            "role": "admin",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    with app.app_context():
        from app.repositories import UserRepository

        user = UserRepository.find_by_username(username)
        assert user is not None
        assert user["role"] == "viewer"


def test_register_page_has_no_role_selector(client):
    resp = client.get("/auth/register")
    assert resp.status_code == 200
    assert b'name="role"' not in resp.data


def test_viewer_lands_on_overview_after_login(client):
    resp = _login(client, "viewer", "Viewer@123")
    assert resp.status_code in (302, 303)
    assert resp.headers.get("Location", "") == "/"


def test_viewer_blocked_from_product_form(client):
    _login(client, "viewer", "Viewer@123")
    resp = client.get("/products/new")
    assert resp.status_code == 403


def test_viewer_blocked_from_mutations(client):
    _login(client, "viewer", "Viewer@123")
    assert client.post("/suppliers", data={"name": "X", "lead_days": 1, "spend_amount": 1}).status_code == 403
    assert client.post("/purchase-orders", data={"quantity": 5}).status_code == 403
    assert client.post("/api/products", json={"sku": "X", "name": "X"}).status_code == 403
    assert client.post("/api/movements", json={"product_id": 1, "type": "IN", "quantity": 1}).status_code == 403
    assert client.put("/api/settings", json={"dark_mode": "on"}).status_code == 403


def test_viewer_can_view_readonly_pages(client):
    _login(client, "viewer", "Viewer@123")
    assert client.get("/").status_code == 200
    assert client.get("/inventory").status_code == 200
    assert client.get("/reorder-alerts").status_code == 200
    assert client.get("/suppliers").status_code == 200
    assert client.get("/reports").status_code == 200
    assert client.get("/purchase-orders").status_code == 200


def test_viewer_settings_nav_hidden(client):
    _login(client, "viewer", "Viewer@123")
    body = client.get("/").get_data(as_text=True)
    assert "nav-drop-label\">Settings" not in body


def test_admin_allowed_on_write_routes(auth_client):
    assert auth_client.get("/products/new").status_code == 200
    assert auth_client.get("/settings").status_code == 200