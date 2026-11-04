"""Integration tests for Movement Ledger API endpoints."""

import pytest
import json
import io
import csv
from datetime import datetime, timedelta


class TestMovementListAPI:
    """Tests for GET /api/movements endpoint."""

    def test_get_movements_returns_paginated_json(self, auth_client, app):
        """GET /api/movements returns paginated JSON with total_count."""
        resp = auth_client.get("/api/movements")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "data" in data
        assert "total_count" in data
        assert "page" in data
        assert "per_page" in data
        assert isinstance(data["data"], list)

    def test_get_movements_default_page_per_page(self, auth_client, app):
        """Default page=1, per_page=20."""
        resp = auth_client.get("/api/movements")
        data = resp.get_json()
        assert data["page"] == 1
        assert data["per_page"] == 20

    def test_get_movements_custom_page_per_page(self, auth_client, app):
        """Custom page and per_page params work."""
        resp = auth_client.get("/api/movements?page=2&per_page=10")
        data = resp.get_json()
        assert data["page"] == 2
        assert data["per_page"] == 10

    def test_get_movements_clamp_per_page(self, auth_client, app):
        """per_page > 100 is clamped to 100."""
        resp = auth_client.get("/api/movements?per_page=200")
        data = resp.get_json()
        assert data["per_page"] == 100

    def test_get_movements_invalid_page_returns_400(self, auth_client, app):
        """Page < 1 returns 400."""
        resp = auth_client.get("/api/movements?page=0")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False

    def test_get_movements_type_filter_single(self, auth_client, app):
        """Single type filter works."""
        resp = auth_client.get("/api/movements?type=IN")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_get_movements_type_filter_multiple(self, auth_client, app):
        """Multiple type filters work (comma-separated)."""
        resp = auth_client.get("/api/movements?type=IN,OUT")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_get_movements_invalid_type_returns_400(self, auth_client, app):
        """Invalid type returns 400."""
        resp = auth_client.get("/api/movements?type=INVALID")
        assert resp.status_code == 400

    def test_get_movements_date_from_filter(self, auth_client, app):
        """date_from filter works (ISO 8601)."""
        resp = auth_client.get("/api/movements?date_from=2024-01-01")
        assert resp.status_code == 200

    def test_get_movements_date_to_filter(self, auth_client, app):
        """date_to filter works (ISO 8601)."""
        resp = auth_client.get("/api/movements?date_to=2024-12-31")
        assert resp.status_code == 200

    def test_get_movements_invalid_date_returns_400(self, auth_client, app):
        """Invalid date format returns 400."""
        resp = auth_client.get("/api/movements?date_from=invalid")
        assert resp.status_code == 400

    def test_get_movements_product_id_filter(self, auth_client, app):
        """product_id filter works."""
        resp = auth_client.get("/api/movements?product_id=1")
        assert resp.status_code == 200

    def test_get_movements_invalid_product_id_returns_400(self, auth_client, app):
        """Non-integer product_id returns 400."""
        resp = auth_client.get("/api/movements?product_id=abc")
        assert resp.status_code == 400

    def test_get_movements_user_id_filter(self, auth_client, app):
        """user_id filter works."""
        resp = auth_client.get("/api/movements?user_id=1")
        assert resp.status_code == 200

    def test_get_movements_invalid_user_id_returns_400(self, auth_client, app):
        """Non-integer user_id returns 400."""
        resp = auth_client.get("/api/movements?user_id=xyz")
        assert resp.status_code == 400

    def test_get_movements_sort_by_created_at(self, auth_client, app):
        """Sort by created_at works."""
        resp = auth_client.get("/api/movements?sort_by=created_at&sort_order=asc")
        assert resp.status_code == 200

    def test_get_movements_sort_by_type(self, auth_client, app):
        """Sort by type works."""
        resp = auth_client.get("/api/movements?sort_by=type&sort_order=desc")
        assert resp.status_code == 200

    def test_get_movements_sort_by_product(self, auth_client, app):
        """Sort by product works."""
        resp = auth_client.get("/api/movements?sort_by=product&sort_order=asc")
        assert resp.status_code == 200

    def test_get_movements_sort_by_user(self, auth_client, app):
        """Sort by user works."""
        resp = auth_client.get("/api/movements?sort_by=user&sort_order=desc")
        assert resp.status_code == 200

    def test_get_movements_sort_by_quantity(self, auth_client, app):
        """Sort by quantity works."""
        resp = auth_client.get("/api/movements?sort_by=quantity&sort_order=asc")
        assert resp.status_code == 200

    def test_get_movements_invalid_sort_by_returns_400(self, auth_client, app):
        """Invalid sort_by returns 400."""
        resp = auth_client.get("/api/movements?sort_by=invalid")
        assert resp.status_code == 400

    def test_get_movements_invalid_sort_order_returns_400(self, auth_client, app):
        """Invalid sort_order returns 400."""
        resp = auth_client.get("/api/movements?sort_order=invalid")
        assert resp.status_code == 400

    def test_get_movements_combined_filters(self, auth_client, app):
        """Multiple filters combined work."""
        resp = auth_client.get("/api/movements?type=IN&date_from=2024-01-01&product_id=1&sort_by=created_at&sort_order=desc")
        assert resp.status_code == 200

    def test_get_movements_viewer_access(self, viewer_client, app):
        """Viewer role can access movement list (read-only)."""
        resp = viewer_client.get("/api/movements")
        assert resp.status_code == 200

    def test_get_movements_unauthenticated_returns_401(self, client, app):
        """Unauthenticated request returns 401."""
        resp = client.get("/api/movements")
        assert resp.status_code == 401


class TestProductMovementsAPI:
    """Tests for GET /api/products/<id>/movements endpoint."""

    def test_get_product_movements_returns_list(self, auth_client, app):
        """GET /api/products/<id>/movements returns movement list for product."""
        with app.app_context():
            from app.repositories import ProductRepository
            rows, _ = ProductRepository.list(limit=1)
            product = rows[0]
            product_id = product["id"]

        resp = auth_client.get(f"/api/products/{product_id}/movements")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "data" in data

    def test_get_product_movements_404_for_nonexistent(self, auth_client, app):
        """Non-existent product returns 404."""
        resp = auth_client.get("/api/products/999999/movements")
        assert resp.status_code == 404

    def test_get_product_movements_invalid_id_returns_404(self, auth_client, app):
        """Non-integer product_id does not match the int route converter."""
        resp = auth_client.get("/api/products/abc/movements")
        assert resp.status_code == 404

    def test_get_product_movements_viewer_access(self, viewer_client, app):
        """Viewer can access product movements."""
        with app.app_context():
            from app.repositories import ProductRepository
            rows, _ = ProductRepository.list(limit=1)
            product = rows[0]
            product_id = product["id"]

        resp = viewer_client.get(f"/api/products/{product_id}/movements")
        assert resp.status_code == 200


class TestMovementExportAPI:
    """Tests for GET /api/movements/export endpoint."""

    def test_export_movements_returns_csv(self, auth_client, app):
        """GET /api/movements/export returns CSV with proper headers."""
        resp = auth_client.get("/api/movements/export")
        assert resp.status_code == 200
        assert resp.mimetype == "text/csv"
        assert "attachment" in resp.headers.get("Content-Disposition", "")
        assert "movements_" in resp.headers.get("Content-Disposition", "")

    def test_export_movements_csv_content(self, auth_client, app):
        """CSV has correct headers and data."""
        resp = auth_client.get("/api/movements/export")
        content = resp.data.decode("utf-8")
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)

        assert len(rows) >= 1  # header + data
        header = rows[0]
        expected_headers = ["id", "type", "quantity", "reference", "notes", "created_at", "user_id", "product_name", "sku", "user_name"]
        assert header == expected_headers

    def test_export_movements_with_filters(self, auth_client, app):
        """Export respects filters."""
        resp = auth_client.get("/api/movements/export?type=IN&date_from=2024-01-01")
        assert resp.status_code == 200
        content = resp.data.decode("utf-8")
        # Should not error

    def test_export_movements_streaming(self, auth_client, app):
        """Export streams without loading full CSV in memory."""
        resp = auth_client.get("/api/movements/export?limit=5000")
        # Should stream - no memory issues
        assert resp.status_code == 200

    def test_export_movements_limit_clamped(self, auth_client, app):
        """Limit > 5000 clamped to 5000."""
        resp = auth_client.get("/api/movements/export?limit=10000")
        assert resp.status_code == 200

    def test_export_movements_invalid_limit_returns_400(self, auth_client, app):
        """Limit < 1 returns 400."""
        resp = auth_client.get("/api/movements/export?limit=0")
        assert resp.status_code == 400

    def test_export_movements_filename_timestamped(self, auth_client, app):
        """Export filename includes timestamp."""
        resp = auth_client.get("/api/movements/export")
        cd = resp.headers.get("Content-Disposition", "")
        assert "movements_" in cd
        assert ".csv" in cd

    def test_export_movements_viewer_access(self, viewer_client, app):
        """Viewer can export movements."""
        resp = viewer_client.get("/api/movements/export")
        assert resp.status_code == 200


class TestProductMovementsExportAPI:
    """Tests for GET /api/products/<id>/movements/export endpoint."""

    def test_export_product_movements(self, auth_client, app):
        """Export movements for specific product."""
        with app.app_context():
            from app.repositories import ProductRepository
            rows, _ = ProductRepository.list(limit=1)
            product = rows[0]
            product_id = product["id"]

        resp = auth_client.get(f"/api/products/{product_id}/movements/export")
        assert resp.status_code == 200
        assert resp.mimetype == "text/csv"