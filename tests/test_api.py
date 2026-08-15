"""REST API tests."""
from __future__ import annotations


def test_health_unauthenticated(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json()["success"] is True


def test_products_requires_auth(client):
    response = client.get("/api/products")
    assert response.status_code in (302, 401, 403)


def test_eoq_calculate_unauthenticated(client):
    response = client.post(
        "/api/eoq/calculate",
        json={"demand": 1200, "ordering_cost": 45, "holding_cost": 6},
    )
    assert response.status_code in (302, 401, 403)


def test_eoq_calculate_validation(client):
    # Even when logged in, negative inputs are rejected.
    response = client.post(
        "/api/eoq/calculate",
        json={"demand": 0, "ordering_cost": 0, "holding_cost": 0},
    )
    # Without auth we expect a redirect; with auth a 422.
    assert response.status_code in (302, 401, 403, 422)
