"""Tests for data import backend."""
from __future__ import annotations

import io
import csv

import pytest


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


def test_import_products(auth_client):
    with auth_client as client:
        rows = [
            {"sku": "TSTIMP01", "product_name": "Test Import A", "unit_price": "10.5", "current_stock": "100", "reorder_point": "20", "category": "Test", "supplier_id": ""},
            {"sku": "TSTIMP02", "product_name": "Test Import B", "unit_price": "15.0", "current_stock": "50", "reorder_point": "10", "category": "Test", "supplier_id": ""},
        ]
        resp = _post_upload(client, "products", rows)
        assert resp.status_code == 200
        assert b"imported" in resp.data


def test_import_suppliers(auth_client):
    with auth_client as client:
        rows = [
            {"supplier_name": "Test Supplier X", "contact_email": "tsx@example.com", "phone": "111", "address": "Addr A"},
            {"supplier_name": "Test Supplier Y", "contact_email": "tsy@example.com", "phone": "222", "address": "Addr B"},
        ]
        resp = _post_upload(client, "suppliers", rows)
        assert resp.status_code == 200
        assert b"imported" in resp.data


def test_import_warehouses(auth_client):
    with auth_client as client:
        rows = [
            {"warehouse_name": "Test WH Alpha", "location": "City A"},
            {"warehouse_name": "Test WH Beta", "location": "City B"},
        ]
        resp = _post_upload(client, "warehouses", rows)
        assert resp.status_code == 200
        assert b"imported" in resp.data


def test_import_movements(auth_client):
    with auth_client as client:
        rows = [
            {"product_id": "1", "quantity": "10", "movement_type": "in", "reason": "Bulk import"},
            {"product_id": "1", "quantity": "5", "movement_type": "out", "reason": "Sale"},
        ]
        resp = _post_upload(client, "movements", rows)
        assert resp.status_code == 200
        assert b"imported" in resp.data


def test_import_purchase_orders(auth_client):
    with auth_client as client:
        rows = [
            {"supplier_id": "1", "product_id": "1", "quantity": "100", "status": "pending"},
            {"supplier_id": "1", "product_id": "2", "quantity": "50", "status": "completed"},
        ]
        resp = _post_upload(client, "purchase_orders", rows)
        assert resp.status_code == 200
        assert b"imported" in resp.data


def test_import_invalid_entity(auth_client):
    with auth_client as client:
        resp = _post_upload(client, "invalid", [{"foo": "bar"}])
        assert resp.status_code == 200
        assert b"Invalid entity type" in resp.data


def test_import_non_csv(auth_client):
    with auth_client as client:
        data = {"csv_file": (io.BytesIO(b"not csv"), "test.txt")}
        resp = client.post(
            "/admin/data-import/upload/products",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Please upload a CSV file" in resp.data


def test_import_no_file(auth_client):
    with auth_client as client:
        resp = client.post(
            "/admin/data-import/upload/products",
            data={},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Choose file first" in resp.data
