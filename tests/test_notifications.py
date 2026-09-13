"""Notification system tests."""
from __future__ import annotations


def test_api_notifications_requires_auth(client):
    response = client.get("/api/notifications")
    assert response.status_code in (302, 401, 403)


def test_api_mark_read_requires_auth(client):
    response = client.post("/api/notifications/1/read")
    assert response.status_code in (302, 401, 403)


def test_api_mark_all_read_requires_auth(client):
    response = client.post("/api/notifications/read-all")
    assert response.status_code in (302, 401, 403)


def test_api_notifications_returns_list(auth_client):
    response = auth_client.get("/api/notifications", follow_redirects=True)
    assert response.status_code in (200, 429)
    if response.status_code == 200:
        data = response.get_json()
        assert data["success"] is True
        assert "notifications" in data["data"]


def test_api_mark_all_read_works(auth_client):
    response = auth_client.post("/api/notifications/read-all", follow_redirects=True)
    assert response.status_code in (200, 429)
    if response.status_code == 200:
        data = response.get_json()
        assert data["success"] is True
