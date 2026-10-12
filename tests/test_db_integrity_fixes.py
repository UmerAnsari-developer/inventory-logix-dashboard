"""DB integrity fixes D-1..D-8 (Fix/02_plan.md) — against local Postgres.

These validate the *database* guarantees: atomic movement recording, the SKU
unique constraint, the PO state machine, soft supplier delete, upsert
idempotency, and the stale-session cleanup trigger.
"""
from __future__ import annotations

import threading
import uuid
from unittest.mock import patch

import psycopg2.errors
import pytest

from app.database import get_cursor

RUN = uuid.uuid4().hex[:8].upper()  # ProductService uppercases SKUs; keep fixtures matched


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _mk_product(cur, *, stock: int = 0, on_order: int = 0) -> int:
    sku = f"D-{RUN}-{uuid.uuid4().hex[:6].upper()}"
    cur.execute(
        """
        INSERT INTO products (sku, name, category, warehouse, current_stock,
                              reorder_point, unit_price, on_order)
        VALUES (%s, %s, 'IntegrityTest', 'WH-Test', %s, 5, 10.0, %s)
        RETURNING id
        """,
        (sku, f"Integrity test {sku}", stock, on_order),
    )
    return cur.fetchone()["id"]


def _mk_po(cur, product_id: int, *, qty: int, status: str = "draft") -> str:
    po_number = f"PO-D-{RUN}-{uuid.uuid4().hex[:6].upper()}"
    # supplier_id is NOT NULL (db_integrity d548499a4a0d) — pick an existing
    # supplier, creating one only if the table is empty.
    cur.execute("SELECT id FROM suppliers ORDER BY id LIMIT 1")
    row = cur.fetchone()
    if row:
        supplier_id = row["id"]
    else:
        cur.execute(
            """
            INSERT INTO suppliers (name, initials, location, lead_days)
            VALUES ('Integrity Supplier', 'IS', 'Test', 3)
            RETURNING id
            """
        )
        supplier_id = cur.fetchone()["id"]
    cur.execute(
        """
        INSERT INTO purchase_orders (po_number, product_id, supplier_id, quantity, unit_cost, status)
        VALUES (%s, %s, %s, %s, 5.0, %s)
        RETURNING po_number
        """,
        (po_number, product_id, supplier_id, qty, status),
    )
    return cur.fetchone()["po_number"]


def _cleanup_product(product_id: int, po_numbers: tuple = ()) -> None:
    with get_cursor(commit=True) as cur:
        if po_numbers:
            cur.execute("DELETE FROM purchase_orders WHERE po_number = ANY(%s)",
                        (list(po_numbers),))
        # Movements first (FK RESTRICT: PO-receive creates movements that
        # reference the product), then the product.
        cur.execute("DELETE FROM movements WHERE product_id = %s", (product_id,))
        cur.execute("DELETE FROM products WHERE id = %s", (product_id,))


# ---------------------------------------------------------------------------
# D-1: concurrent OUT movements cannot drive stock negative
# ---------------------------------------------------------------------------

def test_d1_concurrent_out_movements_cannot_go_negative(app):
    """Stock 10, five threads each take OUT 3: exactly 3 may succeed, stock 1.

    The old implementation was read-check-write across separate statements, so
    losers of the race overwrote the winner's stock (lost update) and finished
    negative. sp_movement_record now locks the product row for the whole
    guard+insert+update sequence.
    """
    successes: list[int] = []
    failures: list[str] = []

    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur, stock=10)

    def worker():
        with app.app_context():
            try:
                with get_cursor(commit=True) as cur:
                    cur.execute(
                        "SELECT sp_movement_record(%s, 'OUT', 3, 'D1', NULL, NULL)",
                        (product_id,),
                    )
                successes.append(1)
            except Exception as exc:  # noqa: BLE001
                failures.append(str(exc))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT current_stock FROM products WHERE id = %s",
                        (product_id,))
            stock = cur.fetchone()["current_stock"]
            cur.execute("SELECT COUNT(*) AS c FROM movements WHERE product_id = %s",
                        (product_id,))
            movements = cur.fetchone()["c"]
        try:
            _cleanup_product(product_id)
        except Exception:  # noqa: BLE001 - cleanup must not mask assertions
            pass

    assert len(successes) == 3, (
        f"expected exactly 3 winning OUTs (stock 10 / qty 3), got {len(successes)}; "
        f"failures={failures}"
    )
    assert stock == 1, f"final stock must be 1, got {stock}"
    assert movements == 3, f"expected 3 movement rows, got {movements}"
    assert all("Insufficient stock" in f for f in failures), (
        f"losers must fail on the stock guard: {failures}"
    )


# ---------------------------------------------------------------------------
# D-2: unique SKU constraint is enforced at the database
# ---------------------------------------------------------------------------

def test_d2_duplicate_sku_rejected_by_db(app):
    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur)
            cur.execute("SELECT sku FROM products WHERE id = %s", (product_id,))
            sku = cur.fetchone()["sku"]
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cur.execute(
                    "INSERT INTO products (sku, name) VALUES (%s, 'Dup')",
                    (sku,),
                )
            cur.connection.rollback()  # release the failed transaction before cleanup
        _cleanup_product(product_id)


def test_d2_service_reports_duplicate_sku(app):
    from app.services.product_service import ProductError, ProductService

    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur)
            cur.execute("SELECT sku FROM products WHERE id = %s", (product_id,))
            sku = cur.fetchone()["sku"]
        payload = {"sku": sku, "name": "Duplicate", "warehouse": "WH-Test",
                   "unit_price": 1}
        with pytest.raises(ProductError, match="SKU already exists"):
            ProductService.create(payload)
        _cleanup_product(product_id)


def test_d2_service_race_backstop_maps_unique_violation(app, monkeypatch):
    """find_by_sku says 'no' (race), DB constraint must still win cleanly."""
    from app.repositories import ProductRepository
    from app.services.product_service import ProductError, ProductService

    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur)
            cur.execute("SELECT sku FROM products WHERE id = %s", (product_id,))
            sku = cur.fetchone()["sku"]

        monkeypatch.setattr(ProductRepository, "find_by_sku",
                            staticmethod(lambda _sku: None))
        payload = {"sku": sku, "name": "Race dup", "warehouse": "WH-Test",
                   "unit_price": 1}
        with pytest.raises(ProductError, match="SKU already exists"):
            ProductService.create(payload)
        _cleanup_product(product_id)


# ---------------------------------------------------------------------------
# D-3 / D-4: PO state machine, stock/on_order effects, idempotent receive
# ---------------------------------------------------------------------------

def test_d3_po_receive_applies_stock_once(app):
    from app.repositories import PurchaseOrderRepository

    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur, stock=5, on_order=7)
            po_number = _mk_po(cur, product_id, qty=4)
            cur.execute("SELECT id FROM purchase_orders WHERE po_number = %s",
                        (po_number,))
            po_id = cur.fetchone()["id"]

        for status in ("approved", "in_transit", "received"):
            PurchaseOrderRepository.transition(po_id, status)

        def read_state():
            with get_cursor() as cur:
                cur.execute(
                    "SELECT current_stock, on_order FROM products WHERE id = %s",
                    (product_id,))
                p = cur.fetchone()
                cur.execute("SELECT status FROM purchase_orders WHERE id = %s",
                            (po_id,))
                return p, cur.fetchone()["status"]

        (product, status) = read_state()
        assert status == "received"
        assert product["current_stock"] == 9, product
        assert product["on_order"] == 3, product

        # Re-applying 'received' must be a no-op (idempotent), not stock +4 again.
        PurchaseOrderRepository.transition(po_id, "received")
        (product, status) = read_state()
        assert status == "received"
        assert product["current_stock"] == 9, f"receive applied twice: {product}"
        assert product["on_order"] == 3, f"on_order applied twice: {product}"

        _cleanup_product(product_id, (po_number,))


def test_d4_invalid_po_transition_rejected(app):
    from app.repositories import POError, PurchaseOrderRepository

    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur, stock=0)
            po_number = _mk_po(cur, product_id, qty=4)  # status=draft
            cur.execute("SELECT id FROM purchase_orders WHERE po_number = %s",
                        (po_number,))
            po_id = cur.fetchone()["id"]

        with pytest.raises(POError, match="Invalid PO transition: draft -> received"):
            PurchaseOrderRepository.transition(po_id, "received")

        with pytest.raises(POError, match="Invalid PO transition: draft -> in_transit"):
            PurchaseOrderRepository.transition(po_id, "in_transit")

        # Terminal state: received cannot move back.
        with get_cursor(commit=True) as cur:
            cur.execute("UPDATE purchase_orders SET status = 'received' WHERE id = %s",
                        (po_id,))
        with pytest.raises(POError, match="Invalid PO transition: received -> approved"):
            PurchaseOrderRepository.transition(po_id, "approved")

        with get_cursor() as cur:
            cur.execute("SELECT status FROM purchase_orders WHERE id = %s", (po_id,))
            assert cur.fetchone()["status"] == "received"

        _cleanup_product(product_id, (po_number,))


# ---------------------------------------------------------------------------
# D-5: supplier delete is a soft delete and visibility filters apply
# ---------------------------------------------------------------------------

def test_d5_supplier_soft_delete(app):
    with app.app_context():
        token = uuid.uuid4().hex[:8]
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO suppliers (name, initials, location, lead_days)
                VALUES (%s, %s, 'Test', 3)
                RETURNING id
                """,
                (f"Integrity Supplier {token}", f"I{token[:3].upper()}"),
            )
            supplier_id = cur.fetchone()["id"]

            cur.execute("SELECT sp_supplier_delete(%s)", (supplier_id,))

            # Row must still exist (referential history) with deleted_at set.
            cur.execute("SELECT deleted_at FROM suppliers WHERE id = %s",
                        (supplier_id,))
            row = cur.fetchone()
            assert row is not None, "supplier row was hard-deleted"
            assert row["deleted_at"] is not None, "deleted_at not set"

            # sp_supplier_find must not return a deleted supplier.
            cur.execute("SELECT * FROM sp_supplier_find(%s)", (supplier_id,))
            assert cur.fetchone() is None, "deleted supplier still visible via find"

            # sp_supplier_list_all must exclude it.
            cur.execute(
                "SELECT COUNT(*) AS c FROM sp_supplier_list_all() WHERE id = %s",
                (supplier_id,),
            )
            assert cur.fetchone()["c"] == 0, "deleted supplier still in list_all"

            cur.execute("DELETE FROM suppliers WHERE id = %s", (supplier_id,))


# ---------------------------------------------------------------------------
# D-6 / D-7: anomaly and forecast saves are idempotent upserts
# ---------------------------------------------------------------------------

def test_d6_anomaly_save_is_idempotent(app):
    from app.repositories import AnomalyRepository

    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur)
        try:
            common = dict(product_id=product_id, anomaly_type="stockout",
                          z_score=3.1, confidence=90.0,
                          description="first", alert_date="2026-09-01")
            first_id = AnomalyRepository.save(**common)
            AnomalyRepository.save(**{**common, "z_score": 4.2,
                                      "description": "second"})
            with get_cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS c FROM anomaly_log WHERE product_id = %s",
                    (product_id,))
                count = cur.fetchone()["c"]
                cur.execute(
                    "SELECT z_score FROM anomaly_log WHERE product_id = %s",
                    (product_id,))
                row = cur.fetchone()
            assert count == 1, f"duplicate alert row created (count={count})"
            assert first_id is not None
            assert float(row["z_score"]) == 4.2, row
        finally:
            _cleanup_product(product_id)


def test_d7_forecast_save_is_idempotent(app):
    from app.repositories import ForecastRepository

    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur)
        try:
            ForecastRepository.save(product_id, "prophet", 7, {"mape": 10.0})
            ForecastRepository.save(product_id, "prophet", 7, {"mape": 5.0})
            with get_cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS c FROM forecast_cache "
                    "WHERE product_id = %s AND model = 'prophet' AND horizon = 7",
                    (product_id,))
                count = cur.fetchone()["c"]
            assert count == 1, f"duplicate forecast cache row (count={count})"
            rows = ForecastRepository.recent(product_id, limit=5)
            matching = [r for r in rows if r["model"] == "prophet"
                        and r["horizon"] == 7]
            assert matching, "forecast row missing"
            assert float(matching[0]["payload"]["mape"]) == 5.0, matching[0]
        finally:
            _cleanup_product(product_id)


# ---------------------------------------------------------------------------
# D-8: stale-session cleanup trigger is attached and fires
# ---------------------------------------------------------------------------

def test_d8_session_cleanup_trigger_fires(app):
    with app.app_context():
        token_stale = uuid.uuid4().hex
        token_new = uuid.uuid4().hex
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                SELECT tgname FROM pg_trigger
                WHERE tgname = 'trg_session_cleanup' AND NOT tgisinternal
                """
            )
            assert cur.fetchone(), "trg_session_cleanup trigger not attached (migration missing)"

            cur.execute("SELECT id FROM users ORDER BY id LIMIT 1")
            user_id = cur.fetchone()["id"]

            cur.execute(
                """
                INSERT INTO user_sessions (user_id, session_token, ip_address,
                                           user_agent, last_activity)
                VALUES (%s, %s, '127.0.0.1', 'd8-stale', NOW() - INTERVAL '48 hours')
                RETURNING id
                """,
                (user_id, token_stale),
            )
            stale_id = cur.fetchone()["id"]

        # A new login sweeps sessions idle > 24h (excluding the new one).
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO user_sessions (user_id, session_token, ip_address, user_agent)
                VALUES (%s, %s, '127.0.0.1', 'd8-new')
                RETURNING id
                """,
                (user_id, token_new),
            )
            new_id = cur.fetchone()["id"]

        try:
            with get_cursor() as cur:
                cur.execute(
                    "SELECT is_active FROM user_sessions WHERE id = %s", (stale_id,))
                stale = cur.fetchone()["is_active"]
                cur.execute(
                    "SELECT is_active FROM user_sessions WHERE id = %s", (new_id,))
                new = cur.fetchone()["is_active"]
            assert stale is False, "48h-idle session was not deactivated"
            assert new is True, "fresh session must stay active"
        finally:
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM user_sessions WHERE id = ANY(%s)",
                            ([stale_id, new_id],))


# ---------------------------------------------------------------------------
# DB-001: SKU unique constraint returns 409 via API
# ---------------------------------------------------------------------------

def test_db001_sku_unique_violation_returns_409(app, auth_client):
    """Duplicate SKU via API returns 409 Conflict."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur)
            cur.execute("SELECT sku FROM products WHERE id = %s", (product_id,))
            sku = cur.fetchone()["sku"]

    # First create via API should succeed
    payload = {"sku": sku, "name": "Test Product", "warehouse": "WH-Test", "unit_price": 10.0}
    resp = auth_client.post("/api/products", json=payload)
    # The first one might fail if the test product already exists from _mk_product
    # but we're testing the duplicate case, so we expect 409 on second attempt
    resp2 = auth_client.post("/api/products", json=payload)
    assert resp2.status_code == 409, f"Expected 409, got {resp2.status_code}: {resp2.get_json()}"

    with app.app_context():
        _cleanup_product(product_id)


# ---------------------------------------------------------------------------
# DB-009: PO number unique constraint returns 409 via API
# ---------------------------------------------------------------------------

def test_db009_duplicate_po_number_returns_409(app, auth_client):
    """Duplicate PO number via API returns 409 Conflict."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur)
            # Create a supplier for the test
            cur.execute(
                "INSERT INTO suppliers (name, initials, location, lead_days) VALUES ('Test Supplier', 'TS', 'Test', 3) RETURNING id"
            )
            supplier_id = cur.fetchone()["id"]
            po_number = _mk_po(cur, product_id, qty=5)

    payload = {
        "po_number": po_number,
        "supplier_id": supplier_id,
        "product_id": product_id,
        "quantity": 10,
        "unit_cost": 5.0,
        "status": "draft",
    }
    resp = auth_client.post("/api/purchase-orders", json=payload)
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.get_json()}"

    with app.app_context():
        _cleanup_product(product_id, (po_number,))


def test_db009_create_purchase_order_success(app, auth_client):
    """Valid PO creation via API returns 201 Created."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur)
            # Create a supplier for the test
            cur.execute(
                "INSERT INTO suppliers (name, initials, location, lead_days) VALUES ('Test Supplier', 'TS', 'Test', 3) RETURNING id"
            )
            supplier_id = cur.fetchone()["id"]

    po_number = f"PO-TEST-{uuid.uuid4().hex[:6].upper()}"
    payload = {
        "po_number": po_number,
        "supplier_id": supplier_id,
        "product_id": product_id,
        "quantity": 10,
        "unit_cost": 5.0,
        "status": "draft",
    }
    resp = auth_client.post("/api/purchase-orders", json=payload)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.get_json()}"
    data = resp.get_json()
    assert data["success"] is True
    assert "id" in data["data"]
    assert data["message"] == "Purchase order created."

    with app.app_context():
        _cleanup_product(product_id, (po_number,))


# ---------------------------------------------------------------------------
# DB-021: Product edit rejects current_stock in payload
# ---------------------------------------------------------------------------

def test_db021_product_edit_rejects_current_stock(app, auth_client):
    """PUT /api/products/<id> with current_stock in payload returns 422."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur, stock=10)

    # Try to update with current_stock in payload - should be rejected
    payload = {"name": "Updated Name", "warehouse": "WH-Test", "unit_price": 10.0, "current_stock": 999}
    resp = auth_client.put(f"/api/products/{product_id}", json=payload)
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.get_json()}"
    data = resp.get_json()
    assert data["success"] is False
    assert "current_stock" in data["error"]["message"].lower() or "stock" in data["error"]["message"].lower()

    # Verify stock wasn't changed
    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
            stock = cur.fetchone()["current_stock"]
        assert stock == 10, f"Stock should remain 10, got {stock}"
        _cleanup_product(product_id)


# ---------------------------------------------------------------------------
# POService validation tests
# ---------------------------------------------------------------------------

def test_po_service_validate_payload(app):
    """POService.validate_payload validates required fields and types."""
    from app.services.po_service import POService, POServiceError

    with app.app_context():
        # Valid payload
        valid = {
            "po_number": "PO-TEST-001",
            "supplier_id": 1,
            "product_id": 1,
            "quantity": 10,
            "unit_cost": 5.0,
            "status": "draft",
        }
        validated = POService.validate_payload(valid)
        assert validated["po_number"] == "PO-TEST-001"
        assert validated["quantity"] == 10
        assert validated["unit_cost"] == 5.0

        # Missing po_number
        invalid = {**valid}
        del invalid["po_number"]
        with pytest.raises(POServiceError, match="PO number is required"):
            POService.validate_payload(invalid)

        # Invalid quantity (zero)
        invalid = {**valid, "quantity": 0}
        with pytest.raises(POServiceError, match="Quantity"):
            POService.validate_payload(invalid)

        # Invalid unit_cost (negative)
        invalid = {**valid, "unit_cost": -1}
        with pytest.raises(POServiceError, match="Unit cost"):
            POService.validate_payload(invalid)

        # Invalid status
        invalid = {**valid, "status": "invalid_status"}
        with pytest.raises(POServiceError, match="Invalid status"):
            POService.validate_payload(invalid)


# ---------------------------------------------------------------------------
# UI form excludes current_stock from POST payload
# ---------------------------------------------------------------------------

def test_ui_form_excludes_current_stock(app, auth_client):
    """UI product form POST does not include current_stock in payload sent to service."""
    from unittest.mock import patch

    with app.app_context():
        with get_cursor(commit=True) as cur:
            product_id = _mk_product(cur, stock=5)

    # Mock ProductService.update to capture the payload
    with patch("app.routes.ui.ProductService.update") as mock_update:
        mock_update.return_value = None
        form_data = {
            "sku": "TEST-SKU",
            "name": "Test Product",
            "category": "Test",
            "warehouse": "WH-Test",
            "current_stock": "999",  # This should NOT be passed to service
            "reorder_point": "5",
            "unit_price": "10.0",
            "supplier_id": "1",
        }
        resp = auth_client.post(f"/products/{product_id}/edit", data=form_data, follow_redirects=True)
        assert resp.status_code == 200

        # Verify update was called without current_stock
        mock_update.assert_called_once()
        call_args = mock_update.call_args
        payload = call_args[0][1]  # Second positional arg is payload
        assert "current_stock" not in payload, f"current_stock should not be in payload, got {payload}"

    with app.app_context():
        _cleanup_product(product_id)
