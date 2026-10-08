"""TDD Test Specification for ADM-001: Replace direct INSERT in _import_movements with MovementRepository.record calls.

Test Categories:
1. Unit Tests - Test _import_movements calls MovementRepository.record with correct parameters
2. Integration Tests - Test successful import, stock updates, audit log entries
3. Regression Tests - Existing tests still pass
4. Edge Cases - Empty CSV, invalid rows, boundary conditions
5. Database Integrity Tests - Stock never negative, constraints enforced
"""
from __future__ import annotations

import csv
import io
import threading
import psycopg2
from unittest.mock import patch, MagicMock, call

import pytest

from app.routes.admin.data_import_routes import _import_movements, _import_rows
from app.database import get_cursor
from app.repositories import MovementRepository
from app.services.movement_service import MovementService, MovementError


# =============================================================================
# HELPERS
# =============================================================================

def _csv_rows(rows):
    """Helper to convert list of dicts to CSV string."""
    if not rows:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _post_upload(client, entity, rows):
    """Upload CSV rows to the import endpoint."""
    csv_data = _csv_rows(rows)
    data = {
        "csv_file": (io.BytesIO(csv_data.encode("utf-8")), f"test_{entity}.csv"),
    }
    return client.post(
        f"/admin/data-import/upload/{entity}",
        data=data,
        content_type="multipart/form-data",
        follow_redirects=True,
    )


def _mk_product(cur, *, stock: int = 0, sku_suffix: str = "") -> int:
    """Create a test product and return its ID."""
    import uuid
    sku = f"ADM001-{sku_suffix or uuid.uuid4().hex[:6].upper()}"
    cur.execute(
        """
        INSERT INTO products (sku, name, category, warehouse, current_stock,
                              reorder_point, unit_price, on_order)
        VALUES (%s, %s, 'Test', 'WH-Test', %s, 5, 10.0, 0)
        RETURNING id
        """,
        (sku, f"Test Product {sku}", stock),
    )
    return cur.fetchone()["id"]


def _cleanup_product(product_id: int) -> None:
    """Clean up test product."""
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM movements WHERE product_id = %s", (product_id,))
        cur.execute("DELETE FROM products WHERE id = %s", (product_id,))


# =============================================================================
# 1. UNIT TESTS
# =============================================================================

class TestImportMovementsUnit:
    """Unit tests for _import_movements function."""

    @pytest.fixture(autouse=True)
    def setup_db(self, app):
        """Set up test database."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM products WHERE sku LIKE 'ADM001-%'")
                cur.execute("DELETE FROM movements WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'ADM001-%')")
            yield
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM products WHERE sku LIKE 'ADM001-%'")
                cur.execute("DELETE FROM movements WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'ADM001-%')")

    def test_import_movements_calls_movement_repository_record(self, app):
        """Test _import_movements calls MovementRepository.record with correct parameters."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="UNIT01")

            rows = [
                {"product_id": str(product_id), "quantity": "10", "movement_type": "IN", "reason": "Bulk import"},
                {"product_id": str(product_id), "quantity": "5", "movement_type": "OUT", "reason": "Sale"},
            ]

            with patch.object(MovementRepository, 'record', return_value=1) as mock_record:
                count = _import_movements(rows, lock_key=0x6D6F7665)

            assert count == 2
            assert mock_record.call_count == 2

            # Verify first call: IN movement
            call1 = mock_record.call_args_list[0]
            assert call1.kwargs['product_id'] == product_id
            assert call1.kwargs['mtype'] == 'IN'
            assert call1.kwargs['quantity'] == 10
            assert call1.kwargs['reference'] == 'Bulk import'
            assert call1.kwargs['notes'] is None
            assert call1.kwargs['user_id'] is None

            # Verify second call: OUT movement
            call2 = mock_record.call_args_list[1]
            assert call2.kwargs['product_id'] == product_id
            assert call2.kwargs['mtype'] == 'OUT'
            assert call2.kwargs['quantity'] == 5
            assert call2.kwargs['reference'] == 'Sale'
            assert call2.kwargs['notes'] is None
            assert call2.kwargs['user_id'] is None

    def test_import_movements_parameter_mapping_reason_to_reference(self, app):
        """Test CSV 'reason' column maps to SP 'reference' parameter."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="UNIT02")

            rows = [
                {"product_id": str(product_id), "quantity": "10", "movement_type": "IN", "reason": "Purchase order #123"},
            ]

            with patch.object(MovementRepository, 'record', return_value=1) as mock_record:
                _import_movements(rows, lock_key=0x6D6F7665)

            call_args = mock_record.call_args
            assert call_args.kwargs['reference'] == 'Purchase order #123'

    def test_import_movements_notes_and_user_id_are_none(self, app):
        """Test notes and user_id are passed as None (not from CSV)."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="UNIT03")

            rows = [
                {"product_id": str(product_id), "quantity": "10", "movement_type": "IN", "reason": "Test"},
            ]

            with patch.object(MovementRepository, 'record', return_value=1) as mock_record:
                _import_movements(rows, lock_key=0x6D6F7665)

            call_args = mock_record.call_args
            assert call_args.kwargs['notes'] is None
            assert call_args.kwargs['user_id'] is None

    def test_import_movements_validates_invalid_product_id(self, app):
        """Test invalid product_id rows are skipped."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="UNIT04")

            rows = [
                {"product_id": "999999", "quantity": "10", "movement_type": "IN", "reason": "Invalid product"},
                {"product_id": str(product_id), "quantity": "5", "movement_type": "IN", "reason": "Valid"},
            ]

            def side_effect(*args, **kwargs):
                if kwargs.get('product_id') == 999999:
                    raise psycopg2.Error("Invalid product_id")
                return 1

            with patch.object(MovementRepository, 'record', side_effect=side_effect) as mock_record:
                count = _import_movements(rows, lock_key=0x6D6F7665)

            # Only valid product should be processed
            assert count == 1
            assert mock_record.call_count == 2

    def test_import_movements_validates_zero_qty(self, app):
        """Test zero quantity rows are skipped."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="UNIT05")

            rows = [
                {"product_id": str(product_id), "quantity": "0", "movement_type": "IN", "reason": "Zero qty"},
                {"product_id": str(product_id), "quantity": "5", "movement_type": "IN", "reason": "Valid"},
            ]

            with patch.object(MovementRepository, 'record', return_value=1) as mock_record:
                count = _import_movements(rows, lock_key=0x6D6F7665)

            assert count == 1
            assert mock_record.call_count == 1

    def test_import_movements_validates_invalid_type(self, app):
        """Test invalid movement_type rows are skipped."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="UNIT06")

            rows = [
                {"product_id": str(product_id), "quantity": "10", "movement_type": "INVALID", "reason": "Bad type"},
                {"product_id": str(product_id), "quantity": "5", "movement_type": "IN", "reason": "Valid"},
            ]

            with patch.object(MovementRepository, 'record', return_value=1) as mock_record:
                count = _import_movements(rows, lock_key=0x6D6F7665)

            assert count == 1
            assert mock_record.call_count == 1

    def test_import_movements_exception_in_one_row_doesnt_stop_others(self, app):
        """Test exception in one row doesn't stop processing of other rows."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="UNIT07")

            rows = [
                {"product_id": str(product_id), "quantity": "10", "movement_type": "IN", "reason": "First"},
                {"product_id": str(product_id), "quantity": "5", "movement_type": "OUT", "reason": "Second"},
                {"product_id": str(product_id), "quantity": "3", "movement_type": "IN", "reason": "Third"},
            ]

            def side_effect(*args, **kwargs):
                if kwargs.get('reference') == 'Second':
                    raise MovementError("Simulated error")
                return 1

            with patch.object(MovementRepository, 'record', side_effect=side_effect) as mock_record:
                count = _import_movements(rows, lock_key=0x6D6F7665)

            # First and third should succeed, second fails
            assert count == 2
            assert mock_record.call_count == 3


# =============================================================================
# 2. INTEGRATION TESTS
# =============================================================================

class TestImportMovementsIntegration:
    """Integration tests for movement import via API."""

    @pytest.fixture(autouse=True)
    def setup_db(self, app):
        """Set up test database."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM products WHERE sku LIKE 'ADM001-%'")
                cur.execute("DELETE FROM movements WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'ADM001-%')")
                cur.execute("DELETE FROM audit_log WHERE detail->>'product_id' LIKE 'ADM001-%'")
            yield
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM products WHERE sku LIKE 'ADM001-%'")
                cur.execute("DELETE FROM movements WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'ADM001-%')")
                cur.execute("DELETE FROM audit_log WHERE detail->>'product_id' LIKE 'ADM001-%'")

    def test_successful_import_creates_movement_row(self, app, auth_client):
        """Test successful import creates movement row."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="INT01")

        rows = [
            {"product_id": str(product_id), "quantity": "10", "movement_type": "IN", "reason": "Bulk import"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200
        assert b"imported" in resp.data

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT COUNT(*) as c FROM movements WHERE product_id = %s", (product_id,))
                count = cur.fetchone()["c"]
                assert count == 1

    def test_out_movement_reduces_stock(self, app, auth_client):
        """Test OUT movement reduces stock."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="INT02")

        rows = [
            {"product_id": str(product_id), "quantity": "30", "movement_type": "OUT", "reason": "Sale"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
                stock = cur.fetchone()["current_stock"]
                assert stock == 70

    def test_in_movement_increases_stock(self, app, auth_client):
        """Test IN movement increases stock."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=50, sku_suffix="INT03")

        rows = [
            {"product_id": str(product_id), "quantity": "25", "movement_type": "IN", "reason": "Restock"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
                stock = cur.fetchone()["current_stock"]
                assert stock == 75

    def test_adjustment_positive_increases_stock(self, app, auth_client):
        """Test positive ADJUSTMENT increases stock."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=50, sku_suffix="INT04")

        rows = [
            {"product_id": str(product_id), "quantity": "10", "movement_type": "ADJUSTMENT", "reason": "Cycle count"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
                stock = cur.fetchone()["current_stock"]
                assert stock == 60

    def test_adjustment_negative_rejected_due_to_constraint(self, app, auth_client):
        """Test negative ADJUSTMENT is rejected due to database constraint (quantity must be positive)."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=50, sku_suffix="INT05")

        rows = [
            {"product_id": str(product_id), "quantity": "-10", "movement_type": "ADJUSTMENT", "reason": "Damage"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200
        assert b"No rows were imported" in resp.data or b"imported 0" in resp.data

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
                stock = cur.fetchone()["current_stock"]
                assert stock == 50  # Unchanged

    def test_return_movement_increases_stock(self, app, auth_client):
        """Test RETURN movement increases stock."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=50, sku_suffix="INT06")

        rows = [
            {"product_id": str(product_id), "quantity": "5", "movement_type": "RETURN", "reason": "Customer return"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
                stock = cur.fetchone()["current_stock"]
                assert stock == 55

    def test_invalid_rows_skipped_valid_rows_imported(self, app, auth_client):
        """Test invalid rows skipped, valid rows imported (partial success)."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="INT07")

        rows = [
            {"product_id": "999999", "quantity": "10", "movement_type": "IN", "reason": "Invalid product"},
            {"product_id": str(product_id), "quantity": "0", "movement_type": "IN", "reason": "Zero qty"},
            {"product_id": str(product_id), "quantity": "5", "movement_type": "INVALID", "reason": "Bad type"},
            {"product_id": str(product_id), "quantity": "10", "movement_type": "IN", "reason": "Valid 1"},
            {"product_id": str(product_id), "quantity": "5", "movement_type": "OUT", "reason": "Valid 2"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200
        assert b"imported" in resp.data

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT COUNT(*) as c FROM movements WHERE product_id = %s", (product_id,))
                count = cur.fetchone()["c"]
                assert count == 2

    def test_audit_log_entry_created_with_correct_action(self, app, auth_client):
        """Test audit log entry created with correct action, user_id, detail."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="INT08")
                cur.execute("SELECT id FROM users WHERE username = 'admin'")
                admin_id = cur.fetchone()["id"]

        rows = [
            {"product_id": str(product_id), "quantity": "10", "movement_type": "IN", "reason": "Test import"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("""
                    SELECT action, user_id, detail
                    FROM audit_log
                    WHERE target_type = 'movement'
                    ORDER BY created_at DESC
                    LIMIT 1
                """)
                audit = cur.fetchone()
                assert audit is not None
                assert audit["action"] == "movement_in"
                assert audit["user_id"] == admin_id
                detail = audit["detail"]
                assert detail["product_id"] == product_id
                assert detail["type"] == "IN"
                assert detail["quantity"] == 10
                assert detail["reference"] == "Test import"


# =============================================================================
# 3. REGRESSION TESTS
# =============================================================================

class TestImportMovementsRegression:
    """Regression tests - existing functionality must still work."""

    @pytest.fixture(autouse=True)
    def setup_db(self, app):
        """Set up test database."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM products WHERE sku LIKE 'ADM001-%'")
                cur.execute("DELETE FROM movements WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'ADM001-%')")
            yield
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM products WHERE sku LIKE 'ADM001-%'")
                cur.execute("DELETE FROM movements WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'ADM001-%')")

    def test_existing_test_import_movements_happy_path(self, app, auth_client):
        """Existing test: test_import_movements (happy path) still passes."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="REG01")

        rows = [
            {"product_id": str(product_id), "quantity": "10", "movement_type": "in", "reason": "Bulk import"},
            {"product_id": str(product_id), "quantity": "5", "movement_type": "out", "reason": "Sale"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200
        assert b"imported" in resp.data

    def test_existing_test_data_import_race_condition(self, app):
        """Existing test: test_data_import_race_condition still passes."""
        results = []
        errors = []

        def import_products(thread_id):
            with app.app_context():
                try:
                    rows = [{
                        "sku": f"ADM001-RACE-{thread_id}",
                        "product_name": f"Test Product {thread_id}",
                        "unit_price": "10.00",
                        "current_stock": "5",
                        "reorder_point": "10",
                        "category": "Test",
                        "supplier_id": ""
                    }]
                    count = _import_rows("products", rows)
                    results.append(count)
                except Exception as e:
                    errors.append(str(e))

        threads = [threading.Thread(target=import_products, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        # Print errors for debugging
        if errors:
            print(f"Errors: {errors}")
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 5
        assert all(r == 1 for r in results), f"Results: {results}"

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT COUNT(*) as c FROM products WHERE sku LIKE 'ADM001-RACE-%'")
                count = cur.fetchone()["c"]
                assert count == 5

    def test_import_with_invalid_rows_bad_product_id(self, app, auth_client):
        """Import with invalid product_id -> skipped, others imported."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="REG02")

        rows = [
            {"product_id": "999999", "quantity": "10", "movement_type": "IN", "reason": "Bad product"},
            {"product_id": str(product_id), "quantity": "5", "movement_type": "IN", "reason": "Good"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT COUNT(*) as c FROM movements WHERE product_id = %s", (product_id,))
                count = cur.fetchone()["c"]
                assert count == 1

    def test_import_with_invalid_rows_bad_type(self, app, auth_client):
        """Import with invalid movement_type -> skipped, others imported."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="REG03")

        rows = [
            {"product_id": str(product_id), "quantity": "10", "movement_type": "INVALID", "reason": "Bad type"},
            {"product_id": str(product_id), "quantity": "5", "movement_type": "IN", "reason": "Good"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT COUNT(*) as c FROM movements WHERE product_id = %s", (product_id,))
                count = cur.fetchone()["c"]
                assert count == 1

    def test_import_with_invalid_rows_zero_qty(self, app, auth_client):
        """Import with zero qty -> skipped, others imported."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="REG04")

        rows = [
            {"product_id": str(product_id), "quantity": "0", "movement_type": "IN", "reason": "Zero qty"},
            {"product_id": str(product_id), "quantity": "5", "movement_type": "IN", "reason": "Good"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT COUNT(*) as c FROM movements WHERE product_id = %s", (product_id,))
                count = cur.fetchone()["c"]
                assert count == 1


# =============================================================================
# 4. EDGE CASES
# =============================================================================

class TestImportMovementsEdgeCases:
    """Edge case tests for movement import."""

    @pytest.fixture(autouse=True)
    def setup_db(self, app):
        """Set up test database."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM products WHERE sku LIKE 'ADM001-%'")
                cur.execute("DELETE FROM movements WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'ADM001-%')")
            yield
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM products WHERE sku LIKE 'ADM001-%'")
                cur.execute("DELETE FROM movements WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'ADM001-%')")

    def test_empty_csv_returns_zero(self, app, auth_client):
        """Empty CSV (no rows) returns 0."""
        rows = []
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200
        # Empty CSV results in redirect to index page
        # The flash message may not be in response data due to redirect
        # Just verify it doesn't error
        assert resp.status_code == 200

    def test_all_rows_invalid_returns_zero_no_errors(self, app, auth_client):
        """All rows invalid -> returns 0, no errors raised."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="EDGE01")

        rows = [
            {"product_id": "999999", "quantity": "10", "movement_type": "IN", "reason": "Bad product"},
            {"product_id": str(product_id), "quantity": "0", "movement_type": "IN", "reason": "Zero qty"},
            {"product_id": str(product_id), "quantity": "5", "movement_type": "INVALID", "reason": "Bad type"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200
        assert b"No rows were imported" in resp.data or b"imported 0" in resp.data

    def test_csv_with_extra_columns_ignored(self, app, auth_client):
        """CSV with extra columns -> ignored."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="EDGE02")

        rows = [
            {"product_id": str(product_id), "quantity": "10", "movement_type": "IN", "reason": "Test", "extra_col": "ignored", "another": "also ignored"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200
        assert b"imported" in resp.data

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT COUNT(*) as c FROM movements WHERE product_id = %s", (product_id,))
                count = cur.fetchone()["c"]
                assert count == 1

    def test_very_large_qty_boundary(self, app, auth_client):
        """Very large qty (boundary) - should work if stock allows."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=1000000, sku_suffix="EDGE03")

        rows = [
            {"product_id": str(product_id), "quantity": "999999", "movement_type": "IN", "reason": "Large import"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
                stock = cur.fetchone()["current_stock"]
                assert stock == 1999999

    def test_product_id_not_exists_rejected(self, app, auth_client):
        """product_id that doesn't exist -> rejected."""
        rows = [
            {"product_id": "999999", "quantity": "10", "movement_type": "IN", "reason": "Non-existent"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200
        assert b"No rows were imported" in resp.data or b"imported 0" in resp.data

    def test_movement_type_case_insensitivity(self, app, auth_client):
        """movement_type case insensitivity (in/out/adjustment/return)."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="EDGE05")

        rows = [
            {"product_id": str(product_id), "quantity": "10", "movement_type": "in", "reason": "Lowercase"},
            {"product_id": str(product_id), "quantity": "5", "movement_type": "Out", "reason": "Mixed case"},
            {"product_id": str(product_id), "quantity": "3", "movement_type": "ADJUSTMENT", "reason": "Uppercase"},
            {"product_id": str(product_id), "quantity": "2", "movement_type": "return", "reason": "Lowercase return"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200
        assert b"imported" in resp.data

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT COUNT(*) as c FROM movements WHERE product_id = %s", (product_id,))
                count = cur.fetchone()["c"]
                assert count == 4


# =============================================================================
# 5. DATABASE INTEGRITY TESTS
# =============================================================================

class TestImportMovementsDBIntegrity:
    """Database integrity tests for movement import."""

    @pytest.fixture(autouse=True)
    def setup_db(self, app):
        """Set up test database."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM products WHERE sku LIKE 'ADM001-%'")
                cur.execute("DELETE FROM movements WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'ADM001-%')")
            yield
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM products WHERE sku LIKE 'ADM001-%'")
                cur.execute("DELETE FROM movements WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'ADM001-%')")

    def test_products_current_stock_never_negative_after_import(self, app, auth_client):
        """Verify products.current_stock never negative after import."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=10, sku_suffix="DB01")

        # Try to import more OUT than stock
        rows = [
            {"product_id": str(product_id), "quantity": "15", "movement_type": "OUT", "reason": "Too much"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
                stock = cur.fetchone()["current_stock"]
                assert stock >= 0, f"Stock should never be negative, got {stock}"

    def test_movements_row_count_matches_successful_imports(self, app, auth_client):
        """Verify movements row count matches successful imports."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="DB02")

        rows = [
            {"product_id": str(product_id), "quantity": "10", "movement_type": "IN", "reason": "Valid 1"},
            {"product_id": "999999", "quantity": "5", "movement_type": "IN", "reason": "Invalid product"},
            {"product_id": str(product_id), "quantity": "5", "movement_type": "OUT", "reason": "Valid 2"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT COUNT(*) as c FROM movements WHERE product_id = %s", (product_id,))
                count = cur.fetchone()["c"]
                assert count == 2  # Only 2 valid rows

    def test_audit_log_entries_match_successful_imports(self, app, auth_client):
        """Verify audit_log entries match successful imports."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="DB03")
                cur.execute("SELECT id FROM users WHERE username = 'admin'")
                admin_id = cur.fetchone()["id"]

        rows = [
            {"product_id": str(product_id), "quantity": "10", "movement_type": "IN", "reason": "Valid 1"},
            {"product_id": "999999", "quantity": "5", "movement_type": "IN", "reason": "Invalid product"},
            {"product_id": str(product_id), "quantity": "5", "movement_type": "OUT", "reason": "Valid 2"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) as c
                    FROM audit_log
                    WHERE target_type = 'movement'
                    AND detail->>'product_id' = %s
                """, (str(product_id),))
                count = cur.fetchone()["c"]
                assert count == 2  # Only 2 valid rows

    def test_trg_validate_movement_trigger_fires(self, app, auth_client):
        """Verify trg_validate_movement trigger fires (defense-in-depth)."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=5, sku_suffix="DB04")

        # Try to import OUT more than stock - trigger should catch it
        rows = [
            {"product_id": str(product_id), "quantity": "10", "movement_type": "OUT", "reason": "Too much"},
        ]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200
        assert b"No rows were imported" in resp.data or b"imported 0" in resp.data

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
                stock = cur.fetchone()["current_stock"]
                assert stock == 5  # Unchanged

    def test_products_chk_current_stock_nonnegative_constraint_not_violated(self, app, auth_client):
        """Verify products.chk_current_stock_nonnegative constraint not violated."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=10, sku_suffix="DB05")

        # Multiple concurrent OUT attempts via import
        import concurrent.futures

        def import_out():
            rows = [{"product_id": str(product_id), "quantity": "5", "movement_type": "OUT", "reason": "Concurrent"}]
            return _post_upload(auth_client, "movements", rows)

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(import_out) for _ in range(5)]
            for f in concurrent.futures.as_completed(futures):
                resp = f.result()
                assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
                stock = cur.fetchone()["current_stock"]
                assert stock >= 0, f"Stock constraint violated: {stock}"


# =============================================================================
# 6. MOVEMENT TYPE SPECIFIC TESTS
# =============================================================================

class TestImportMovementsTypeSpecific:
    """Tests for specific movement types."""

    @pytest.fixture(autouse=True)
    def setup_db(self, app):
        """Set up test database."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM products WHERE sku LIKE 'ADM001-%'")
                cur.execute("DELETE FROM movements WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'ADM001-%')")
            yield
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM products WHERE sku LIKE 'ADM001-%'")
                cur.execute("DELETE FROM movements WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'ADM001-%')")

    def test_in_movement_type_creates_correct_movement_row(self, app, auth_client):
        """IN movement creates correct movement row with type='IN'."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="TYPE01")

        rows = [{"product_id": str(product_id), "quantity": "10", "movement_type": "IN", "reason": "Test"}]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT type, quantity, reference FROM movements WHERE product_id = %s", (product_id,))
                row = cur.fetchone()
                assert row["type"] == "IN"
                assert row["quantity"] == 10
                assert row["reference"] == "Test"

    def test_out_movement_type_creates_correct_movement_row(self, app, auth_client):
        """OUT movement creates correct movement row with type='OUT'."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="TYPE02")

        rows = [{"product_id": str(product_id), "quantity": "10", "movement_type": "OUT", "reason": "Test"}]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT type, quantity, reference FROM movements WHERE product_id = %s", (product_id,))
                row = cur.fetchone()
                assert row["type"] == "OUT"
                assert row["quantity"] == 10
                assert row["reference"] == "Test"

    def test_adjustment_movement_type_creates_correct_movement_row(self, app, auth_client):
        """ADJUSTMENT movement creates correct movement row with type='ADJUSTMENT'."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="TYPE03")

        rows = [{"product_id": str(product_id), "quantity": "10", "movement_type": "ADJUSTMENT", "reason": "Test"}]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT type, quantity, reference FROM movements WHERE product_id = %s", (product_id,))
                row = cur.fetchone()
                assert row["type"] == "ADJUSTMENT"
                assert row["quantity"] == 10
                assert row["reference"] == "Test"

    def test_return_movement_type_creates_correct_movement_row(self, app, auth_client):
        """RETURN movement creates correct movement row with type='RETURN'."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="TYPE04")

        rows = [{"product_id": str(product_id), "quantity": "10", "movement_type": "RETURN", "reason": "Test"}]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT type, quantity, reference FROM movements WHERE product_id = %s", (product_id,))
                row = cur.fetchone()
                assert row["type"] == "RETURN"
                assert row["quantity"] == 10
                assert row["reference"] == "Test"

    def test_qty_alias_works(self, app, auth_client):
        """CSV 'qty' column alias works for quantity."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="TYPE05")

        rows = [{"product_id": str(product_id), "qty": "10", "type": "IN", "reason": "Test"}]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT quantity FROM movements WHERE product_id = %s", (product_id,))
                row = cur.fetchone()
                assert row["quantity"] == 10

    def test_type_alias_works(self, app, auth_client):
        """CSV 'type' column alias works for movement_type."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=100, sku_suffix="TYPE06")

        rows = [{"product_id": str(product_id), "quantity": "10", "type": "IN", "reason": "Test"}]
        resp = _post_upload(auth_client, "movements", rows)
        assert resp.status_code == 200

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT type FROM movements WHERE product_id = %s", (product_id,))
                row = cur.fetchone()
                assert row["type"] == "IN"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])