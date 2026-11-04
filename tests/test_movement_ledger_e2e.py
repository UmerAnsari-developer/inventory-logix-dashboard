"""E2E tests for Movement Ledger feature using Flask test client."""

import csv
import io
import uuid


class TestMovementLedgerE2E:
    """End-to-end tests for movement ledger feature."""

    def test_full_movement_ledger_flow(self, auth_client, app):
        """Complete flow: create product -> record movements -> list -> export."""
        with app.app_context():
            from app.repositories import ProductRepository
            from app.services import MovementService

            sku = f"E2E-{uuid.uuid4().hex[:6].upper()}"
            product_id = ProductRepository.create({
                "sku": sku,
                "name": "E2E Test Product",
                "category": "Test",
                "warehouse": "WH-Test",
                "current_stock": 100,
                "reorder_point": 10,
                "unit_price": 25.0,
            })

            movements = [
                {"type": "IN", "quantity": 50, "reference": "PO-001", "notes": "Initial stock"},
                {"type": "OUT", "quantity": 20, "reference": "SO-001", "notes": "Sale"},
                {"type": "ADJUSTMENT", "quantity": 5, "reference": "ADJ-001", "notes": "Cycle count"},
                {"type": "RETURN", "quantity": 3, "reference": "RET-001", "notes": "Customer return"},
            ]
            for mv in movements:
                MovementService.record(
                    product_id=product_id,
                    mtype=mv["type"],
                    quantity=mv["quantity"],
                    reference=mv["reference"],
                    notes=mv["notes"],
                    user_id=None,
                )

        # 1. Movement list API
        resp = auth_client.get("/api/movements")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["total_count"] >= 4
        assert len(data["data"]) >= 4

        # 2. Filtered list API
        resp = auth_client.get("/api/movements?type=IN")
        assert resp.status_code == 200
        data = resp.get_json()
        assert all(m["type"] == "IN" for m in data["data"])

        resp = auth_client.get("/api/movements?product_id=" + str(product_id))
        assert resp.status_code == 200
        data = resp.get_json()
        assert all(m["product_name"] == "E2E Test Product" for m in data["data"])

        # 3. Product-specific movements API
        resp = auth_client.get(f"/api/products/{product_id}/movements")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert all(m["product_id"] == product_id for m in data["data"])

        # 4. Movement form remains available to writers
        resp = auth_client.get("/movements/new")
        assert resp.status_code == 200

        # 5. CSV export
        resp = auth_client.get("/api/movements/export")
        assert resp.status_code == 200
        assert resp.mimetype == "text/csv"
        content = resp.data.decode("utf-8")
        rows = list(csv.reader(io.StringIO(content)))
        assert len(rows) >= 5  # header + 4 movements
        expected_headers = ["id", "type", "quantity", "reference", "notes", "created_at", "user_id", "product_name", "sku", "user_name"]
        assert rows[0] == expected_headers

        # 6. Filtered export
        resp = auth_client.get(f"/api/movements/export?type=IN&product_id={product_id}")
        assert resp.status_code == 200
        rows = list(csv.reader(io.StringIO(resp.data.decode("utf-8"))))
        assert len(rows) >= 2  # header + at least 1 IN movement
        for row in rows[1:]:
            assert row[1] == "IN"

        # 7. Product detail page still renders
        resp = auth_client.get(f"/products/{product_id}")
        assert resp.status_code == 200

        # Cleanup
        with app.app_context():
            from app.database.connection import get_cursor

            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM movements WHERE product_id = %s", (product_id,))
                cur.execute("DELETE FROM products WHERE id = %s", (product_id,))

    def test_movement_ledger_viewer_access(self, viewer_client, app):
        """Viewer can read movements but cannot write them."""
        resp = viewer_client.get("/api/movements")
        assert resp.status_code == 200

        resp = viewer_client.post("/api/movements", json={
            "product_id": 1,
            "type": "IN",
            "quantity": 10,
        })
        assert resp.status_code == 403

        resp = viewer_client.get("/movements/new")
        assert resp.status_code == 403

    def test_movement_ledger_unauthenticated_redirect(self, client, app):
        """Unauthenticated user is redirected for HTML and rejected for JSON."""
        resp = client.get("/movements/new")
        assert resp.status_code == 302
        assert "/auth/login" in resp.headers.get("Location", "")

        resp = client.get("/api/movements")
        assert resp.status_code == 401

    def test_movement_ledger_pagination(self, auth_client, app):
        """Pagination works correctly."""
        with app.app_context():
            from app.repositories import ProductRepository
            from app.services import MovementService

            product_id = ProductRepository.create({
                "sku": f"PAGE-{uuid.uuid4().hex[:6].upper()}",
                "name": "Pagination Test",
                "category": "Test",
                "warehouse": "WH-Test",
                "current_stock": 1000,
                "reorder_point": 10,
                "unit_price": 10.0,
            })
            for i in range(25):
                MovementService.record(
                    product_id=product_id,
                    mtype="IN",
                    quantity=10,
                    reference=f"BATCH-{i}",
                    user_id=None,
                )

        base = f"/api/movements?product_id={product_id}"
        resp = auth_client.get(base + "&page=1&per_page=20")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["page"] == 1
        assert data["per_page"] == 20
        assert len(data["data"]) == 20
        assert data["total_count"] == 25

        resp = auth_client.get(base + "&page=2&per_page=20")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["page"] == 2
        assert len(data["data"]) == 5

        resp = auth_client.get(base + "&per_page=50")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["per_page"] == 50
        assert len(data["data"]) == 25

        with app.app_context():
            from app.database.connection import get_cursor

            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM movements WHERE product_id = %s", (product_id,))
                cur.execute("DELETE FROM products WHERE id = %s", (product_id,))

    def test_movement_ledger_sorting(self, auth_client, app):
        """Sorting works on all sortable columns."""
        sort_fields = ["created_at", "type", "product", "user", "quantity"]
        for field in sort_fields:
            for order in ["asc", "desc"]:
                resp = auth_client.get(f"/api/movements?sort_by={field}&sort_order={order}")
                assert resp.status_code == 200, f"Failed for {field} {order}"
                data = resp.get_json()
                assert data["success"] is True
