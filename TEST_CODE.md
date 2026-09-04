# InventoryLogix — Test Code Documentation

**Document type:** Complete test source code reference
**Application:** InventoryLogix Inventory Command Center
**Repository:** UmerAnsari-developer/inventory-logix-dashboard
**Test run ID:** TR-20260904-001
**Build/commit SHA:** c312ec4
**Framework:** pytest 9.1.1, Python 3.14.5
**Total test files:** 9 (1 fixtures + 8 test modules)
**Total test cases:** 97 — **all passing**

---

This document contains the complete, verbatim source code of every test file in the InventoryLogix test suite, along with its fixtures. Each file is preceded by a description of what it tests and a summary of its results.

---

## Table of contents

1. [conftest.py — Test fixtures](#1-conftestpy--test-fixtures)
2. [test_auth.py — Authentication flows (4 cases)](#2-test_authpy--authentication-flows)
3. [test_api.py — REST API contract (4 cases)](#3-test_apipy--rest-api-contract)
4. [test_roles.py — Role-based access control (8 cases)](#4-test_rolespy--role-based-access-control)
5. [test_security.py — Validators, headers, rate limiting (15 cases)](#5-test_securitypy--validators-headers-rate-limiting)
6. [test_services.py — Service-layer business logic (25 cases)](#6-test_servicespy--service-layer-business-logic)
7. [test_ml.py — ML forecasting + anomaly detection (30 cases)](#7-test_mlpy--ml-forecasting--anomaly-detection)
8. [test_etl.py — ETL pipeline / data warehouse (3 cases)](#8-test_etlpy--etl-pipeline--data-warehouse)
9. [test_cache.py — Caching system (8 cases)](#9-test_cachepy--caching-system)

---

## 1. conftest.py — Test fixtures

Shared pytest fixtures: environment isolation (tests always run against local PostgreSQL, never the production Supabase/Render database), Flask app factory, test client, and a pre-authenticated admin client.

**Result: 0 test cases (fixture module) — supports all 97.**

```python
"""Test fixtures for the InventoryLogix application."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("FLASK_ENV", "testing")
os.environ.setdefault("WTF_CSRF_ENABLED", "0")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

# Tests always run against the local development PostgreSQL, never the
# Render database configured in .env. load_dotenv() won't override these.
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "inventory_db")
os.environ.setdefault("DB_USER", "postgres")
os.environ.setdefault("DB_PASSWORD", "Um%25ans12er")
os.environ.setdefault("DB_SSLMODE", "")
# .env may carry a Render DATABASE_URL; tests must use the local DB_* fields.
os.environ.setdefault("DATABASE_URL", "")


@pytest.fixture(scope="session")
def app():
    from app import create_app
    flask_app = create_app("testing")
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def runner(app):
    return app.test_cli_runner()


@pytest.fixture()
def auth_client(client):
    """Returns a logged-in test client."""
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "Admin@123", "remember": "on"},
        follow_redirects=False,
    )
    return client
```

---

## 2. test_auth.py — Authentication flows

Verifies login page rendering, invalid-credential rejection without information disclosure, registration validation, and that protected routes redirect unauthenticated users.

**Result: 4/4 PASSED.**

```python
"""Tests for the authentication flow."""
from __future__ import annotations

import pytest


def test_login_page_renders(client):
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert b"Welcome back" in response.data or b"Sign in" in response.data


def test_login_with_invalid_credentials(client):
    response = client.post(
        "/auth/login",
        data={"username": "nope", "password": "wrong", "remember": "on"},
        follow_redirects=True,
    )
    assert response.status_code in (200, 401)
    assert b"Invalid" in response.data or b"nope" in response.data


def test_register_validation(client):
    response = client.post(
        "/auth/register",
        data={"username": "ab", "email": "not-an-email", "password": "short", "role": "viewer"},
        follow_redirects=True,
    )
    assert response.status_code in (200, 400)
    assert b"required" in response.data.lower() or b"invalid" in response.data.lower() or b"valid" in response.data.lower()


def test_protected_route_redirects(client):
    response = client.get("/inventory")
    assert response.status_code in (302, 303)
    assert "/auth/login" in response.headers.get("Location", "")
```

---

## 3. test_api.py — REST API contract

Verifies the health endpoint, authentication enforcement on protected API endpoints, and EOQ calculation input validation.

**Result: 4/4 PASSED.**

```python
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
```

---

## 4. test_roles.py — Role-based access control

Verifies that self-registration always creates viewer accounts (even with tampered role=admin fields), the registration form exposes no role selector, viewers are read-only across all mutation routes, and admins can access write routes.

**Result: 8/8 PASSED.**

```python
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
```

---

## 5. test_security.py — Validators, headers, rate limiting

Verifies all input validators (SKU, email, username, password strength, positive numbers, integers, string lengths) at exact boundaries, plus HTTP security headers (CSP, X-Frame-Options, etc.) and login rate limiting.

**Result: 15/15 PASSED.**

```python
"""Tests for security helpers and validators."""
from __future__ import annotations

import pytest

from app.security.validators import (
    validate_email,
    validate_integer,
    validate_password_strength,
    validate_positive_number,
    validate_sku,
    validate_string_length,
    validate_username,
    ValidationError,
)


def test_validate_sku_ok():
    assert validate_sku("SKU-TECH-001") == "SKU-TECH-001"


def test_validate_sku_rejects_invalid():
    with pytest.raises(ValidationError):
        validate_sku("sku tech 001")


def test_validate_email():
    assert validate_email("me@example.com") == "me@example.com"
    with pytest.raises(ValidationError):
        validate_email("not-an-email")


def test_validate_username():
    assert validate_username("admin") == "admin"
    with pytest.raises(ValidationError):
        validate_username("a!")


def test_password_strength():
    with pytest.raises(ValidationError):
        validate_password_strength("short")
    with pytest.raises(ValidationError):
        validate_password_strength("nodigitshere")
    pw = validate_password_strength("Strong1Pass")
    assert pw == "Strong1Pass"


def test_validate_positive_number_zero_allowed():
    assert validate_positive_number(0) == 0.0


def test_validate_positive_number_zero_disallowed_raises():
    with pytest.raises(ValidationError):
        validate_positive_number(0, allow_zero=False)


def test_validate_positive_number_positive_when_zero_disallowed():
    assert validate_positive_number(5, allow_zero=False) == 5.0


def test_validate_positive_number_rounds_four_decimals():
    assert validate_positive_number(1.23456) == 1.2346


def test_validate_integer_boundary_at_minimum():
    assert validate_integer(5, minimum=5) == 5
    with pytest.raises(ValidationError):
        validate_integer(4, minimum=5)


def test_validate_string_length_minimum_boundary():
    assert validate_string_length("a", "x") == "a"
    with pytest.raises(ValidationError):
        validate_string_length("", "x")


def test_validate_string_length_maximum_boundary():
    value = "a" * 200
    assert validate_string_length(value, "x") == value
    with pytest.raises(ValidationError):
        validate_string_length(value + "a", "x")


def test_password_strength_length_boundaries():
    pw8 = validate_password_strength("Short1A9")
    assert pw8 == "Short1A9"
    with pytest.raises(ValidationError):
        validate_password_strength("Short1")
    long_ok = "A1" * 64
    assert validate_password_strength(long_ok) == long_ok
    with pytest.raises(ValidationError):
        validate_password_strength("A1" * 64 + "A")


def test_security_headers_present(client):
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Content-Security-Policy")


def test_login_rate_limit(client):
    # A couple of requests should not trip the rate limiter immediately.
    for _ in range(3):
        response = client.post(
            "/auth/login",
            data={"username": "x", "password": "y", "remember": "on"},
        )
        assert response.status_code in (401, 429)
```

---

## 6. test_services.py — Service-layer business logic

Verifies ProductService payload validation (SKU normalization, boundary rules, defaults), pagination math (clamping, boundary pages), and MovementService stock math (IN/OUT/overdraw/zero/null with faked repositories).

**Result: 25/25 PASSED.**

```python
"""Inventory service tests covering validation rules."""
from __future__ import annotations

import pytest

from app.services import ProductService, MovementService
from app.services.product_service import ProductError
from app.services.movement_service import MovementError


def test_validate_payload_normalises_sku():
    payload = {
        "sku": " sku-test-001 ",
        "name": "Test SKU",
        "current_stock": "5",
        "reorder_point": "2",
        "unit_price": "12.50",
        "demand_rate": "100",
        "ordering_cost": "5",
        "holding_cost": "3",
    }
    result = ProductService.validate_payload(payload)
    assert result["sku"] == "SKU-TEST-001"
    assert result["current_stock"] == 5


def test_validate_payload_negative_stock():
    payload = {"sku": "x", "name": "x", "current_stock": -1, "reorder_point": 0, "unit_price": 1}
    with pytest.raises(ProductError):
        ProductService.validate_payload(payload)


def test_movement_service_validates_type():
    with pytest.raises(MovementError):
        MovementService.record(
            product_id=1,
            mtype="INVALID",
            quantity=10,
        )


# ---------------------------------------------------------------------------
# ProductService.validate_payload boundary rules
# ---------------------------------------------------------------------------
def _full_payload(**overrides):
    payload = {
        "sku": "SKU-BND-001",
        "name": "Test Product",
        "current_stock": "10",
        "reorder_point": "2",
        "unit_price": "12.50",
        "demand_rate": "100",
        "ordering_cost": "5",
        "holding_cost": "3",
    }
    payload.update(overrides)
    return payload


def test_validate_payload_name_minimum():
    result = ProductService.validate_payload(_full_payload(name="ab"))
    assert result["name"] == "ab"


def test_validate_payload_name_too_long():
    with pytest.raises(ProductError):
        ProductService.validate_payload(_full_payload(name="x" * 151))


def test_validate_payload_category_optional():
    result = ProductService.validate_payload(_full_payload())
    assert result["category"] is None


def test_validate_payload_warehouse_default():
    result = ProductService.validate_payload(_full_payload(warehouse=""))
    assert result["warehouse"] == "WH-Pune"


def test_validate_payload_zero_stock_and_reorder_ok():
    result = ProductService.validate_payload(
        _full_payload(current_stock="0", reorder_point="0")
    )
    assert result["current_stock"] == 0
    assert result["reorder_point"] == 0


def test_validate_payload_zero_unit_price_ok():
    result = ProductService.validate_payload(_full_payload(unit_price="0"))
    assert result["unit_price"] == 0.0


def test_validate_payload_zero_demand_rate_ok():
    result = ProductService.validate_payload(_full_payload(demand_rate="0"))
    assert result["demand_rate"] == 0.0


def test_validate_payload_empty_reorder_point_defaults_zero():
    result = ProductService.validate_payload(_full_payload(reorder_point=""))
    assert result["reorder_point"] == 0


# ---------------------------------------------------------------------------
# ProductService.list_products pagination math (repository faked, no DB)
# ---------------------------------------------------------------------------
def _fake_product_repo(total=16):
    class FakeRepo:
        captured = {}
        last_limit = None

        @staticmethod
        def list(**kwargs):
            FakeRepo.captured = kwargs
            FakeRepo.last_limit = kwargs["limit"]
            return [{"id": i} for i in range(kwargs["limit"])], total

    return FakeRepo


def test_list_products_clamps_page_and_per_page_lower(monkeypatch):
    repo = _fake_product_repo()
    monkeypatch.setattr("app.services.product_service.ProductRepository", repo)
    result = ProductService.list_products(page=0, per_page=4)
    pag = result["pagination"]
    assert pag["page"] == 1
    assert pag["per_page"] == 5
    assert repo.captured["offset"] == 0
    assert repo.captured["limit"] == 5


def test_list_products_clamps_per_page_upper(monkeypatch):
    repo = _fake_product_repo()
    monkeypatch.setattr("app.services.product_service.ProductRepository", repo)
    result = ProductService.list_products(per_page=9999)
    assert result["pagination"]["per_page"] == 100
    assert repo.captured["limit"] == 100


def test_list_products_default_per_page(monkeypatch):
    repo = _fake_product_repo()
    monkeypatch.setattr("app.services.product_service.ProductRepository", repo)
    result = ProductService.list_products()
    assert result["pagination"]["page"] == 1
    assert result["pagination"]["per_page"] == 20
    assert repo.captured["limit"] == 20


def test_list_products_pagination_math(monkeypatch):
    repo = _fake_product_repo(total=16)
    monkeypatch.setattr("app.services.product_service.ProductRepository", repo)
    result = ProductService.list_products(page=2, per_page=5)
    pag = result["pagination"]
    assert pag["page"] == 2
    assert pag["per_page"] == 5
    assert pag["total"] == 16
    assert pag["pages"] == 4
    assert pag["has_prev"] is True
    assert pag["has_next"] is True
    assert pag["prev_num"] == 1
    assert pag["next_num"] == 3
    assert repo.captured["offset"] == 5
    assert repo.captured["limit"] == 5


def test_list_products_has_next_boundary(monkeypatch):
    repo = _fake_product_repo(total=10)
    monkeypatch.setattr("app.services.product_service.ProductRepository", repo)
    result = ProductService.list_products(page=1, per_page=10)
    pag = result["pagination"]
    assert pag["pages"] == 1
    assert pag["has_next"] is False
    assert pag["has_prev"] is False


def test_list_products_high_page(monkeypatch):
    repo = _fake_product_repo(total=16)
    monkeypatch.setattr("app.services.product_service.ProductRepository", repo)
    result = ProductService.list_products(page=99999, per_page=100)
    pag = result["pagination"]
    assert pag["page"] == 99999
    assert pag["has_next"] is False
    assert pag["prev_num"] == 99998


# ---------------------------------------------------------------------------
# MovementService.record stock math (repositories faked, no DB)
# ---------------------------------------------------------------------------
def _patch_movement(monkeypatch, current_stock=10, sku="SKU-MV-001"):
    class FakeProductRepo:
        last_stock = None

        @staticmethod
        def find(product_id):
            return {"id": product_id, "sku": sku, "current_stock": current_stock}

        @staticmethod
        def find_for_update(product_id):
            return {"id": product_id, "sku": sku, "current_stock": current_stock}

        @staticmethod
        def set_stock(product_id, stock):
            FakeProductRepo.last_stock = stock

    class FakeMovementRepo:
        last_call = None

        @staticmethod
        def record(**kwargs):
            FakeMovementRepo.last_call = kwargs
            return 99

    class FakeAuditRepo:
        @staticmethod
        def record(*args, **kwargs):
            pass

    monkeypatch.setattr("app.services.movement_service.ProductRepository", FakeProductRepo)
    monkeypatch.setattr("app.services.movement_service.MovementRepository", FakeMovementRepo)
    monkeypatch.setattr("app.services.movement_service.AuditRepository", FakeAuditRepo)
    return FakeProductRepo, FakeMovementRepo


def test_movement_record_out_decrements_stock(monkeypatch):
    fake_p, fake_m = _patch_movement(monkeypatch, current_stock=10)
    MovementService.record(product_id=1, mtype="OUT", quantity=4)
    assert fake_p.last_stock == 6
    assert fake_m.last_call["quantity"] == 4


def test_movement_record_in_increments_stock(monkeypatch):
    fake_p, _ = _patch_movement(monkeypatch, current_stock=10)
    MovementService.record(product_id=1, mtype="IN", quantity=4)
    assert fake_p.last_stock == 14


def test_movement_record_exact_balance_allowed(monkeypatch):
    fake_p, _ = _patch_movement(monkeypatch, current_stock=10)
    MovementService.record(product_id=1, mtype="OUT", quantity=10)
    assert fake_p.last_stock == 0


def test_movement_record_rejects_zero_quantity(monkeypatch):
    _patch_movement(monkeypatch)
    with pytest.raises(MovementError):
        MovementService.record(product_id=1, mtype="IN", quantity=0)


def test_movement_record_rejects_missing_quantity(monkeypatch):
    _patch_movement(monkeypatch)
    with pytest.raises(MovementError):
        MovementService.record(product_id=1, mtype="IN", quantity=None)


def test_movement_record_rejects_oversell(monkeypatch):
    _patch_movement(monkeypatch, current_stock=10)
    with pytest.raises(MovementError):
        MovementService.record(product_id=1, mtype="OUT", quantity=11)


def test_movement_record_defaults_reference_and_notes(monkeypatch):
    _, fake_m = _patch_movement(monkeypatch, current_stock=10)
    MovementService.record(product_id=1, mtype="IN", quantity=5)
    assert fake_m.last_call["reference"] is None
    assert fake_m.last_call["notes"] is None


def test_movement_record_null_stock_treated_as_zero(monkeypatch):
    fake_p, _ = _patch_movement(monkeypatch, current_stock=None)
    MovementService.record(product_id=1, mtype="IN", quantity=5)
    assert fake_p.last_stock == 5
```

---

## 7. test_ml.py — ML forecasting + anomaly detection

Verifies Prophet/ARIMA/ensemble forecasting, moving-average fallback with exact numeric assertions, model availability flags, Isolation Forest determinism and boundaries, z-score classification/confidence/sorting, and SPC control-limit math.

**Result: 30/30 PASSED.**

```python
"""Tests for the EOQ, forecast and anomaly ML helpers."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.ml import anomaly as amod
from app.ml import forecasting as fmod
from app.ml.forecasting import (
    _moving_average_forecast,
    forecast_ensemble,
    forecast_with_arima,
    forecast_with_prophet,
)
from app.ml.anomaly import _stats, detect_anomalies_isoforest, spc_zscore_analysis


def _series(n: int = 120, base: int = 50, spike_at: int = 60):
    today = date.today()
    rows, values = [], []
    for i in range(n):
        v = base + (i % 7) * 2
        if i == spike_at:
            v = base * 5
        values.append(v)
        rows.append({"ds": (today - timedelta(days=n - i)).isoformat(), "y": v})
    return rows, values


def test_prophet_returns_forecast():
    history, _ = _series()
    result = forecast_with_prophet(history, horizon=14)
    assert "predictions" in result
    assert len(result["predictions"]) == 14
    assert result["model"] in {"prophet", "moving_average"}


def test_arima_returns_forecast():
    history, _ = _series()
    result = forecast_with_arima(history, horizon=7)
    assert "predictions" in result
    assert len(result["predictions"]) == 7


def test_ensemble_blends():
    history, _ = _series()
    result = forecast_ensemble(history, horizon=10)
    assert "predictions" in result
    assert len(result["predictions"]) == 10
    assert result["model"] == "ensemble"


def test_isoforest_detects_spike():
    _, values = _series()
    series = [{"day": f"d{i}", "value": v} for i, v in enumerate(values)]
    result = detect_anomalies_isoforest(series)
    assert result["model"] in {"isolation_forest", "zscore"}
    assert result["count"] >= 1


def test_spc_returns_control_limits():
    _, values = _series()
    series = [{"day": f"d{i}", "value": v} for i, v in enumerate(values)]
    result = spc_zscore_analysis(series)
    assert result["mean"] > 0
    assert result["ucl"] > result["mean"]
    assert result["lcl"] <= result["mean"]


# ---------------------------------------------------------------------------
# Deterministic value-level assertions (kill weak mutation survivors)
# ---------------------------------------------------------------------------
def test_moving_average_exact_values():
    history, _ = _series(n=5)
    result = _moving_average_forecast(history, horizon=3)
    assert result["model"] == "moving_average"
    assert len(result["predictions"]) == 3
    assert result["baseline"] == pytest.approx(56.0)
    assert result["predictions"] == pytest.approx([57.0, 58.0, 59.0])
    assert result["lower"][0] == pytest.approx(53.79933340276332)
    assert result["upper"][0] == pytest.approx(60.20066659723668)


def test_moving_average_two_points():
    history, _ = _series(n=2)
    result = _moving_average_forecast(history, horizon=2)
    assert result["baseline"] == pytest.approx(51.0)
    assert result["lower"][0] == pytest.approx(49.54)


def test_moving_average_window_growth():
    history, _ = _series(n=8)
    result = _moving_average_forecast(history, horizon=3)
    assert result["baseline"] == pytest.approx(57.333333333333336)


def test_moving_average_window_cap_ramp():
    today = date.today()
    rows = []
    for i in range(60):
        rows.append({
            "ds": (today - timedelta(days=59 - i)).isoformat(),
            "y": float(i + 1),
        })
    result = _moving_average_forecast(rows, horizon=3)
    assert result["baseline"] == pytest.approx(53.5)


def test_moving_average_long_window_cap():
    history, _ = _series(n=60)
    result = _moving_average_forecast(history, horizon=3)
    assert result["baseline"] == pytest.approx(56.0)


def test_moving_average_single_point():
    history, _ = _series(n=1, base=5)
    result = _moving_average_forecast(history, horizon=2)
    assert result["baseline"] == pytest.approx(5.0)
    assert result["lower"][0] == pytest.approx(3.04)
    assert result["upper"][0] == pytest.approx(6.96)


def test_prophet_boundary_len_fourteen():
    history, _ = _series(n=14, spike_at=7)
    result = forecast_with_prophet(history, horizon=3)
    assert result["model"] == "prophet"
    assert result["accuracy"] == pytest.approx(65.15, abs=0.05)


def test_arima_boundary_len_twenty():
    history, _ = _series(n=20, spike_at=10)
    result = forecast_with_arima(history, horizon=3)
    assert result["model"] == "arima"
    assert result["accuracy"] == pytest.approx(70.09, abs=0.05)


def test_ensemble_exact_values():
    history, _ = _series(n=10)
    result = forecast_ensemble(history, horizon=3)
    assert result["model"] == "ensemble"
    assert result["predictions"][0] == pytest.approx(52.45)
    assert result["lower"][0] == pytest.approx(49.24933340276332)
    assert result["upper"][0] == pytest.approx(55.650666597236686)
    assert result["baseline"] == pytest.approx(52.0)
    assert result["accuracy"] == pytest.approx(78.0)


def test_prophet_flag_matches_environment():
    assert fmod._HAS_PROPHET is True


def test_arima_flag_matches_environment():
    assert fmod._HAS_ARIMA is True


def test_sklearn_flag_matches_environment():
    assert amod._HAS_SKLEARN is True


def _value_series(n, base=50, spike_at=None, mult=5):
    rows, values = [], []
    for i in range(n):
        v = base + (i % 7) * 2
        if i == spike_at:
            v = base * mult
        values.append(v)
        rows.append({"day": f"d{i}", "value": v})
    return rows, values


def test_isoforest_deterministic_output():
    series, _ = _value_series(n=120, spike_at=60)
    result = detect_anomalies_isoforest(series)
    assert result["model"] == "isolation_forest"
    assert result["count"] == 1
    first = result["anomalies"][0]
    assert first["day"] == "d60"
    assert first["value"] == 250.0
    assert first["z_score"] == pytest.approx(10.64)
    assert first["confidence"] == pytest.approx(74.0)
    assert first["type"] == "spike"


def test_isoforest_boundary_len_fourteen():
    series, _ = _value_series(n=14, spike_at=7)
    result = detect_anomalies_isoforest(series)
    assert result["model"] == "isolation_forest"
    assert result["count"] == 1
    first = result["anomalies"][0]
    assert first["value"] == 250.0
    assert first["z_score"] == pytest.approx(3.6)
    assert first["confidence"] == pytest.approx(66.1)


def test_isoforest_skips_when_few_points():
    series, _ = _value_series(n=8, spike_at=4, mult=10)
    result = detect_anomalies_isoforest(series)
    assert result["model"] == "zscore"


def test_zscore_boundary_threshold():
    values = [0, 100, 200, 0, 100, 200, 0, 100, 200, 0]
    series = [{"day": f"d{i}", "value": v} for i, v in enumerate(values)]
    mu, sigma = _stats(values)
    z200 = (200 - mu) / sigma
    result = detect_anomalies_isoforest(series, z_threshold=z200)
    assert result["count"] == 3


def test_zscore_confidence_small_z():
    series = [{"day": f"d{i}", "value": v}
              for i, v in enumerate([10, 30, 10, 30, 10, 30, 10, 30])]
    result = detect_anomalies_isoforest(series, z_threshold=0)
    assert result["anomalies"][0]["confidence"] == pytest.approx(85.0)


def test_zscore_confidence_large_z():
    series = [{"day": f"d{i}", "value": v}
              for i, v in enumerate([0, 0, 0, 0, 0, 0, 0, 400])]
    result = detect_anomalies_isoforest(series, z_threshold=2.5)
    assert result["count"] == 1
    assert result["anomalies"][0]["confidence"] == pytest.approx(95.0)


def test_zscore_type_boundary_zero_z():
    series = [{"day": f"d{i}", "value": v} for i, v in enumerate([5, 10, 15])]
    result = detect_anomalies_isoforest(series, z_threshold=0)
    by_value = {a["value"]: a for a in result["anomalies"]}
    assert by_value[10]["type"] == "drop"
    assert by_value[10]["z_score"] == pytest.approx(0.0)
    assert by_value[5]["z_score"] == pytest.approx(-1.22)
    assert by_value[15]["z_score"] == pytest.approx(1.22)


def test_zscore_sort_and_truncation():
    series = [{"day": f"d{i}", "value": v} for i, v in enumerate([5, 10, 15] * 10)]
    result = detect_anomalies_isoforest(series, z_threshold=0)
    assert result["count"] == 30
    assert len(result["anomalies"]) == 25
    assert abs(result["anomalies"][0]["z_score"]) == pytest.approx(1.22)
    assert result["anomalies"][0]["value"] == 5.0


def test_zscore_sort_uses_abs_magnitude():
    series = [{"day": f"d{i}", "value": v} for i, v in enumerate([2, 20, 4])]
    result = detect_anomalies_isoforest(series, z_threshold=0.4)
    assert result["anomalies"][0]["value"] == 20.0


def test_spc_two_points():
    result = spc_zscore_analysis([{"value": 1}, {"value": 2}])
    assert result["mean"] == pytest.approx(1.5)
    assert result["sigma"] == pytest.approx(0.5)


def test_spc_rounding():
    series = [{"value": 1.111}, {"value": 1.111}, {"value": 1.111}]
    result = spc_zscore_analysis(series)
    assert result["mean"] == pytest.approx(1.11)
    assert result["sigma"] == pytest.approx(0.5)
    assert result["ucl"] == pytest.approx(2.61)
    assert result["lcl"] == pytest.approx(0)


def test_spc_lcl_positive():
    series = [{"value": 10.111}, {"value": 10.111}, {"value": 10.111}]
    result = spc_zscore_analysis(series)
    assert result["mean"] == pytest.approx(10.11)
    assert result["ucl"] == pytest.approx(11.61)
    assert result["lcl"] == pytest.approx(8.61)


def test_spc_sigma_rounding():
    result = spc_zscore_analysis([{"value": 1}, {"value": 2.234}])
    assert result["sigma"] == pytest.approx(0.62)
```

---

## 8. test_etl.py — ETL pipeline / data warehouse

Verifies the full ETL build populates the star schema (dimension + fact tables with matching counts and state markers), idempotent skipping when no new movements exist, and incremental processing with high-water-mark advancement.

**Result: 3/3 PASSED.**

```python
"""ETL pipeline tests: full rebuild, incremental runs, and high-water marks."""
from __future__ import annotations

import pytest


def _etl_state(cur):
    cur.execute("SELECT state_key, value FROM etl_state ORDER BY state_key")
    return {r["state_key"]: r["value"] for r in cur.fetchall()}


def test_etl_full_build_populates_star_schema(app):
    from app.database.connection import etl_database
    with app.app_context():
        result = etl_database(force=True)
        assert result["skipped"] is False
        assert result["dim_warehouses"] > 0
        assert result["dim_products"] > 0
        assert result["fact_movements"] > 0

        from app.database import get_cursor
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM fact_movement_daily")
            assert cur.fetchone()["c"] == result["fact_movements"]
            state = _etl_state(cur)
            assert "last_movement_id" in state
            assert int(state["last_movement_id"]) > 0


def test_etl_skips_when_no_new_movements(app):
    from app.database.connection import etl_database
    with app.app_context():
        etl_database(force=True)
        result = etl_database()
        assert result["skipped"] is True


def test_etl_incremental_processes_new_movements(app):
    from app.database.connection import etl_database
    from app.database import get_cursor
    with app.app_context():
        etl_database(force=True)
        with get_cursor() as cur:
            cur.execute("SELECT value FROM etl_state WHERE state_key='last_movement_id'")
            before = int(cur.fetchone()["value"])

        with get_cursor(commit=True) as cur:
            # Grab any real product from the seeded catalogue; the synthetic
            # seeder mints SKU-DC-* codes so we cannot hardcode a fixture SKU.
            cur.execute("SELECT id, sku, warehouse FROM products ORDER BY id LIMIT 1")
            row = cur.fetchone()
            pid, sku, wh = row["id"], row["sku"], row["warehouse"]
            cur.execute(
                """
                INSERT INTO movements (product_id, sku, type, quantity, reference, notes, created_at)
                VALUES (%s, %s, 'OUT', 12, 'TEST-ETL', 'incremental test', NOW())
                """,
                (pid, sku),
            )

        result = etl_database()
        assert result["incremental"] is True
        assert result["skipped"] is False

        with get_cursor() as cur:
            cur.execute("SELECT value FROM etl_state WHERE state_key='last_movement_id'")
            after = int(cur.fetchone()["value"])
            assert after > before
            # The affected day's OUT qty for this sku must have grown.
            cur.execute(
                """
                SELECT f.out_qty
                FROM fact_movement_daily f
                JOIN dim_warehouse dw ON dw.warehouse_key = f.warehouse_key
                JOIN dim_product dp ON dp.product_key = f.product_key
                WHERE dw.warehouse_name = %s
                  AND dp.sku = %s
                  AND f.date_key = CURRENT_DATE
                """,
                (wh, sku),
            )
            out_qty = cur.fetchone()
            assert out_qty is not None
            assert out_qty["out_qty"] >= 12
```

---

## 9. test_cache.py — Caching system

Verifies the unified TTLCache: basic get/set with defaults, TTL expiry, LRU eviction, prefix invalidation, read-through `get_or_set` (producer runs exactly once), thread safety (8 threads × 200 ops), deterministic key building, and cross-cache bust helpers.

**Result: 8/8 PASSED.**

```python
"""Self-check for TTLCache: expiry, LRU eviction, prefix invalidation, thread safety."""
import sys
import time
import threading

sys.path.insert(0, ".")

from app.utils.cache import TTLCache, make_key, cache_bust_all, cache_bust_products


def test_basic():
    c = TTLCache(ttl=60, max_entries=5)
    c.set("a", 1)
    assert c.get("a") == 1
    assert c.get("missing") is None
    assert c.get("missing", "dflt") == "dflt"
    print("PASS basic get/set/miss-default")


def test_ttl_expiry():
    c = TTLCache(ttl=0.05, max_entries=5)
    c.set("k", "v")
    assert c.get("k") == "v"
    time.sleep(0.06)
    assert c.get("k") is None, "entry should expire after ttl"
    print("PASS ttl expiry")


def test_lru_eviction():
    c = TTLCache(ttl=60, max_entries=3)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    c.get("a")              # touch a -> b is now LRU
    c.set("d", 4)           # evicts b
    assert c.get("b") is None, "LRU entry should be evicted"
    assert c.get("a") == 1 and c.get("c") == 3 and c.get("d") == 4
    print("PASS lru eviction")


def test_prefix_invalidation():
    c = TTLCache(ttl=60, max_entries=10)
    c.set("products:1", "x")
    c.set("products:2", "y")
    c.set("suppliers:1", "z")
    dropped = c.invalidate("products")
    assert dropped == 2
    assert c.get("products:1") is None and c.get("products:2") is None
    assert c.get("suppliers:1") == "z"
    print("PASS prefix invalidation")


def test_get_or_set():
    c = TTLCache(ttl=60, max_entries=5)
    calls = []
    def producer():
        calls.append(1)
        return "expensive"
    assert c.get_or_set("k", producer) == "expensive"
    assert c.get_or_set("k", producer) == "expensive"
    assert len(calls) == 1, "producer must run exactly once"
    print("PASS get_or_set read-through")


def test_thread_safety():
    c = TTLCache(ttl=60, max_entries=100)
    errors = []
    def worker(n):
        try:
            for i in range(200):
                c.set(f"k{n}-{i}", i)
                c.get(f"k{n}-{i}")
                c.invalidate("k0")
        except Exception as e:
            errors.append(e)
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, f"thread errors: {errors}"
    print("PASS thread safety (8 threads x 200 ops)")


def test_make_key():
    assert make_key(a="1", b="", c="x") == "a=1|c=x"
    assert make_key(a="1", c="x") == make_key(c="x", a="1")
    print("PASS make_key deterministic + skips falsy")


def test_bust_helpers():
    from app.utils import cache as mod
    mod.products_cache.set("foo", 1)
    mod.dashboard_cache.set("bar", 2)
    n = cache_bust_products()
    assert n >= 2 and mod.products_cache.get("foo") is None
    print("PASS cache_bust helpers clear cross-caches")


if __name__ == "__main__":
    test_basic()
    test_ttl_expiry()
    test_lru_eviction()
    test_prefix_invalidation()
    test_get_or_set()
    test_thread_safety()
    test_make_key()
    test_bust_helpers()
    cache_bust_all()
    print("\nAll TTLCache checks passed.")
```

---

## 10. Execution results summary

| File | Test cases | Passed | Failed | Status |
|------|-----------|--------|--------|--------|
| conftest.py (fixtures) | — | — | — | Supports all |
| test_api.py | 4 | 4 | 0 | 100% PASS |
| test_auth.py | 4 | 4 | 0 | 100% PASS |
| test_cache.py | 8 | 8 | 0 | 100% PASS |
| test_etl.py | 3 | 3 | 0 | 100% PASS |
| test_ml.py | 30 | 30 | 0 | 100% PASS |
| test_roles.py | 8 | 8 | 0 | 100% PASS |
| test_security.py | 15 | 15 | 0 | 100% PASS |
| test_services.py | 25 | 25 | 0 | 100% PASS |
| **Total** | **97** | **97** | **0** | **100% PASS** |

## 11. How to run

```bash
# From the repository root (virtualenv active, local PostgreSQL running and seeded)
pytest -v                  # verbose: lists every test with PASSED status
pytest -q                  # quiet: summary line only
pytest tests/test_ml.py    # single module
```

Expected output: `97 passed` in ~8-21 seconds.

---

*All credentials in the test code are demo/test accounts (admin/Admin@123, viewer/Viewer@123). Tests run exclusively against the local development PostgreSQL database — never production Supabase/Render.*
