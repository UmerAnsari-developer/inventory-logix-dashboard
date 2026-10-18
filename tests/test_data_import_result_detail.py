"""Tests for import result detail: {"imported": int, "skipped": int, "errors": [...]}.

Covers:
- Shape + invariant (skipped == len(errors)) for every importer
- Error taxonomy: 1-based data row (header excluded), field, value, error_code, severity
- Movements classification, incl. MovementError substring map (mocked record)
- Row-number parity with validate_fk_rows preview warnings
- Endpoint flashes: status line, per-row banners, grouped tail after the cap

Convention: every row created here is prefixed (products 'RD-', suppliers
'RD ', warehouses 'RDWH-', purchase orders 'RD-PO-') and cleaned by the
``clean_rd`` fixture.
"""
from __future__ import annotations

import csv
import io
from unittest.mock import patch

import pytest
from flask import get_flashed_messages
from flask_login.utils import _create_identifier

import app.routes.admin.data_import_routes as routes_mod
from app.database import get_cursor
from app.repositories import MovementRepository, UserRepository
from app.services import DataImportService
from app.services.movement_service import MovementError


def _session_client(app, username: str):
    """Authenticated test client without hitting the /auth/login rate limiter."""
    with app.app_context():
        user = UserRepository.find_by_username(username)
        assert user is not None, f"missing user {username}"
        uid = user.id

    c = app.test_client()
    ident_box: dict = {}

    def _capture_ident():
        ident_box["id"] = _create_identifier()

    app.before_request_funcs.setdefault(None, []).append(_capture_ident)
    try:
        resp = c.get("/static/img/favicon.svg")
        assert resp.status_code == 200, "identifier probe request failed"
    finally:
        app.before_request_funcs[None].remove(_capture_ident)
    assert "id" in ident_box, "failed to capture session identifier"

    with c.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
        sess["_id"] = ident_box["id"]
    return c


def _post_upload(client, entity, rows):
    """Upload CSV rows to the import endpoint."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    data = {
        "csv_file": (io.BytesIO(output.getvalue().encode("utf-8")), f"test_{entity}.csv"),
    }
    return client.post(
        f"/admin/data-import/upload/{entity}",
        data=data,
        content_type="multipart/form-data",
        follow_redirects=True,
    )


def _mk_product(app, sku: str, stock: int = 10) -> int:
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO products (sku, name, unit_price, current_stock, "
                "reorder_point, category, supplier_id) "
                "VALUES (%s, %s, 1, %s, 1, 'Test', NULL) RETURNING id",
                (sku, f"Product {sku}", stock),
            )
            return cur.fetchone()["id"]


@pytest.fixture
def clean_rd(app):
    """Delete every RD-prefixed test row before and after a DB test."""

    def _do():
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute(
                    "DELETE FROM movements WHERE product_id IN "
                    "(SELECT id FROM products WHERE sku LIKE 'RD-%')"
                )
                cur.execute("DELETE FROM purchase_orders WHERE po_number LIKE 'RD-PO-%'")
                cur.execute("DELETE FROM products WHERE sku LIKE 'RD-%'")
                cur.execute("DELETE FROM suppliers WHERE name LIKE 'RD %'")
                cur.execute("DELETE FROM warehouses WHERE warehouse_name LIKE 'RDWH-%'")

    _do()
    yield
    _do()


def test_import_warehouses_result_shape_and_invariant(app, clean_rd):
    with app.app_context():
        result = routes_mod._import_rows("warehouses", [
            {"warehouse_name": "RDWH-Alpha", "location": "A"},
            {"warehouse_name": "", "location": "B"},
        ])

    assert result["imported"] == 1
    assert result["skipped"] == 1 == len(result["errors"])
    entry = result["errors"][0]
    assert set(entry) == {"row", "field", "value", "error_code", "severity", "reason"}
    assert entry["row"] == 2
    assert entry["field"] == "warehouse_name"
    assert entry["error_code"] == "missing_required"
    assert entry["severity"] == "warning"
    assert "missing required value" in entry["reason"]


def test_import_warehouses_duplicate_is_info_already_exists(app, clean_rd):
    rows = [
        {"warehouse_name": "RDWH-Dup", "location": "A"},
        {"warehouse_name": "RDWH-Dup", "location": "A"},
    ]
    with app.app_context():
        result = routes_mod._import_rows("warehouses", rows)

    assert result["imported"] == 1
    assert result["skipped"] == 1 == len(result["errors"])
    entry = result["errors"][0]
    assert entry["row"] == 2
    assert entry["error_code"] == "already_exists"
    assert entry["severity"] == "info"
    assert entry["value"] == "RDWH-Dup"
    assert "already exists" in entry["reason"]


def test_import_products_invalid_number_and_missing_required(app, clean_rd):
    rows = [
        {"sku": "RD-P1", "name": "P1", "unit_price": "abc", "current_stock": "1",
         "reorder_point": "1", "category": "Test", "supplier_name": ""},
        {"sku": "", "name": "P2", "unit_price": "1", "current_stock": "1",
         "reorder_point": "1", "category": "Test", "supplier_name": ""},
        {"sku": "RD-P2", "name": "P2", "unit_price": "1", "current_stock": "1",
         "reorder_point": "1", "category": "Test", "supplier_name": ""},
    ]
    with app.app_context():
        result = routes_mod._import_rows("products", rows)

    assert result["imported"] == 1
    assert result["skipped"] == 2 == len(result["errors"])
    bad_number, blank = result["errors"]
    assert (bad_number["row"], bad_number["field"], bad_number["value"],
            bad_number["error_code"]) == (1, "unit_price", "abc", "invalid_number")
    assert "is not a number" in bad_number["reason"]
    assert (blank["row"], blank["field"], blank["error_code"]) == (2, "sku", "missing_required")


def test_import_suppliers_lead_days_duplicate_blank(app, clean_rd):
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO suppliers (name, initials, location, lead_days) "
                "VALUES ('RD Dup Supplier', 'RD', '', 0)"
            )
        result = routes_mod._import_rows("suppliers", [
            {"name": "RD New Supplier", "location": "", "lead_days": "3"},
            {"name": "RD Dup Supplier", "location": "", "lead_days": "1"},
            {"name": "RD Bad Days", "location": "", "lead_days": "xyz"},
            {"name": "", "location": "", "lead_days": "1"},
        ])

    assert result["imported"] == 1
    assert result["skipped"] == 3 == len(result["errors"])
    dup, bad_days, blank = result["errors"]
    assert (dup["row"], dup["error_code"], dup["severity"]) == (2, "already_exists", "info")
    assert "already exists" in dup["reason"]
    assert (bad_days["row"], bad_days["field"], bad_days["error_code"]) == (3, "lead_days", "invalid_number")
    assert (blank["row"], blank["field"], blank["error_code"]) == (4, "name", "missing_required")


def test_import_movements_classification_real_db(app, clean_rd):
    _mk_product(app, "RD-MOV", stock=50)
    with app.app_context():
        result = routes_mod._import_movements([
            {"product_sku": "RD-MOV", "quantity": "5", "movement_type": "IN", "reason": "rd"},
            {"product_sku": "RD-GHOST", "quantity": "5", "movement_type": "IN", "reason": "rd"},
            {"product_sku": "RD-MOV", "quantity": "0", "movement_type": "IN", "reason": "rd"},
            {"product_sku": "RD-MOV", "quantity": "5", "movement_type": "FOO", "reason": "rd"},
        ])

    assert result["imported"] == 1
    assert result["skipped"] == 3 == len(result["errors"])
    ghost, zero_qty, bad_type = result["errors"]
    assert (ghost["row"], ghost["field"], ghost["error_code"]) == (2, "product_sku", "fk_product_not_found")
    assert "not found" in ghost["reason"]
    assert (zero_qty["row"], zero_qty["field"], zero_qty["error_code"]) == (3, "quantity", "quantity_not_positive")
    assert (bad_type["row"], bad_type["field"], bad_type["error_code"]) == (4, "movement_type", "invalid_movement_type")


def test_import_movements_movement_error_classification(app, clean_rd):
    _mk_product(app, "RD-MOV2", stock=100)
    rows = [
        {"product_sku": "RD-MOV2", "quantity": "5", "movement_type": "OUT", "reason": "neg balance"},
        {"product_sku": "RD-MOV2", "quantity": "5", "movement_type": "IN", "reason": "missing"},
        {"product_sku": "RD-MOV2", "quantity": "5", "movement_type": "IN", "reason": "bad type"},
        {"product_sku": "RD-MOV2", "quantity": "5", "movement_type": "IN", "reason": "bad qty"},
        {"product_sku": "RD-MOV2", "quantity": "5", "movement_type": "IN", "reason": "boom"},
    ]
    messages = {
        "neg balance": "Stock-out would create a negative balance.",
        "missing": "Product not found.",
        "bad type": "Type must be one of ['ADJUSTMENT', 'IN', 'OUT', 'RETURN'].",
        "bad qty": "Quantity must be a positive integer.",
        "boom": "Simulated error",
    }

    def _raise(*args, **kwargs):
        raise MovementError(messages[kwargs["reference"]])

    with app.app_context():
        with patch.object(MovementRepository, "record", side_effect=_raise):
            result = routes_mod._import_movements(rows)

    assert result["imported"] == 0
    assert result["skipped"] == 5 == len(result["errors"])
    assert [e["error_code"] for e in result["errors"]] == [
        "stock_violation",
        "fk_product_not_found",
        "invalid_movement_type",
        "quantity_not_positive",
        "db_error",
    ]
    stock_err = result["errors"][0]
    assert stock_err["field"] == "quantity"
    assert "negative balance" in stock_err["reason"]


def test_import_purchase_orders_classification(app, clean_rd):
    _mk_product(app, "RD-PO-PROD", stock=100)
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO suppliers (name, initials, location, lead_days) "
                "VALUES ('RD PO Real Sup', 'RP', '', 0)"
            )
        result = routes_mod._import_rows("purchase_orders", [
            {"supplier_name": "", "product_sku": "RD-UNKNOWN", "quantity": "1", "status": "draft"},
            {"supplier_name": "RD PO Real Sup", "product_sku": "RD-UNKNOWN", "quantity": "1", "status": "draft"},
            {"supplier_name": "RD PO Ghost Sup", "product_sku": "RD-PO-PROD", "quantity": "1", "status": "draft"},
            {"supplier_name": "RD PO Real Sup", "product_sku": "RD-PO-PROD", "quantity": "0", "status": "draft"},
            {"supplier_name": "RD PO Real Sup", "product_sku": "RD-PO-PROD", "quantity": "2",
             "status": "draft", "po_number": "RD-PO-1"},
        ])

    assert result["imported"] == 1
    assert result["skipped"] == 4 == len(result["errors"])
    blank_supplier, unknown_product, ghost_supplier, zero_qty = result["errors"]
    assert (blank_supplier["row"], blank_supplier["field"], blank_supplier["error_code"]) == (1, "supplier_name", "missing_required")
    assert (unknown_product["row"], unknown_product["field"], unknown_product["error_code"]) == (2, "product_sku", "fk_product_not_found")
    assert (ghost_supplier["row"], ghost_supplier["field"], ghost_supplier["error_code"]) == (3, "supplier_name", "fk_supplier_not_found")
    assert (zero_qty["row"], zero_qty["field"], zero_qty["error_code"]) == (4, "quantity", "quantity_not_positive")


def test_row_number_parity_with_preview(app, clean_rd):
    _mk_product(app, "RD-PAR", stock=50)
    rows = [
        {"product_sku": "RD-PAR", "quantity": "5", "movement_type": "IN", "reason": "rd"},
        {"product_sku": "RD-GHOST-A", "quantity": "5", "movement_type": "IN", "reason": "rd"},
        {"product_sku": "RD-GHOST-B", "quantity": "5", "movement_type": "IN", "reason": "rd"},
    ]
    with app.app_context():
        with get_cursor() as cur:
            caches = DataImportService.build_fk_caches(cur)
        warnings = DataImportService.validate_fk_rows(rows, "movements", caches)
        result = routes_mod._import_movements(rows, caches)

    assert [w["row"] for w in warnings] == [2, 3]
    assert [e["row"] for e in result["errors"]] == [2, 3]


def test_upload_flash_shows_counts_and_reasons(app, clean_rd):
    _mk_product(app, "RD-EP-MOV", stock=100)
    client = _session_client(app, "admin")
    resp = _post_upload(client, "movements", [
        {"product_sku": "RD-GHOST-EP", "quantity": "5", "movement_type": "IN", "reason": "rd"},
        {"product_sku": "RD-EP-MOV", "quantity": "5", "movement_type": "IN", "reason": "rd"},
        {"product_sku": "RD-EP-MOV", "quantity": "0", "movement_type": "IN", "reason": "rd"},
    ])

    assert resp.status_code == 200
    assert b"Successfully imported 1 movements." in resp.data
    assert b"Skipped 2 row(s)." in resp.data
    assert b"Row 1" in resp.data
    assert b"not found" in resp.data
    assert b"Row 3" in resp.data


def test_upload_flash_caps_banners_and_groups_the_tail(app, clean_rd):
    client = _session_client(app, "admin")
    rows = [{"warehouse_name": "", "location": "x"} for _ in range(12)]
    resp = _post_upload(client, "warehouses", rows)

    assert resp.status_code == 200
    assert b"Skipped 12 row(s)." in resp.data
    assert resp.data.count(b"missing required value") == 10  # capped at _MAX_REASON_LINES
    assert b"and 2 more" in resp.data
    assert b"missing_required" in resp.data


def test_clean_import_no_extra_flash(app, clean_rd):
    with app.app_context():
        result = routes_mod._import_rows("products", [
            {"sku": "RD-CLEAN-1", "name": "C1", "unit_price": "1", "current_stock": "1",
             "reorder_point": "1", "category": "Test", "supplier_name": ""},
            {"sku": "RD-CLEAN-2", "name": "C2", "unit_price": "1", "current_stock": "1",
             "reorder_point": "1", "category": "Test", "supplier_name": ""},
        ])
    assert result == {"imported": 2, "skipped": 0, "errors": [], "error_counts": {}}

    client = _session_client(app, "admin")
    resp = _post_upload(client, "products", [
        {"sku": "RD-CLEAN-3", "name": "C3", "unit_price": "1", "current_stock": "1",
         "reorder_point": "1", "category": "Test", "supplier_name": ""},
        {"sku": "RD-CLEAN-4", "name": "C4", "unit_price": "1", "current_stock": "1",
         "reorder_point": "1", "category": "Test", "supplier_name": ""},
    ])
    assert resp.status_code == 200
    assert b"Successfully imported 2 products." in resp.data
    assert b"Skipped" not in resp.data


def test_record_skip_caps_retained_errors_but_keeps_full_tallies(app):
    """Detail entries cap at 200; skipped / error_counts are full, and the
    tail flash subtracts only the displayed entries from the full tallies."""
    result = routes_mod._empty_result()
    for i in range(250):
        routes_mod._record_skip(
            result, i + 1,
            routes_mod._RowSkip("missing_required", field=f"field-{i}", value="",
                                reason="missing required value"),
        )

    assert result["skipped"] == 250
    assert len(result["errors"]) == 200
    assert result["error_counts"] == {"missing_required": 250}

    with app.test_request_context("/"):
        routes_mod._flash_import_detail(result)
        messages = get_flashed_messages()

    assert any("Skipped 250 row(s)." in m for m in messages)
    assert any("and 240 more" in m for m in messages)
    assert any("240× missing_required" in m for m in messages)


def test_none_cells_skip_as_missing_required_not_db_error(app, clean_rd):
    """Short CSV rows give None cells; every importer must degrade to the
    normal missing_required taxonomy, never AttributeError -> db_error."""
    with app.app_context():
        results = [
            routes_mod._import_rows("products", [
                {"sku": None, "name": "N", "unit_price": "1", "current_stock": "1",
                 "reorder_point": "1", "category": None, "supplier_name": None},
            ]),
            routes_mod._import_rows("suppliers", [
                {"name": None, "location": None, "lead_days": "1"},
            ]),
            routes_mod._import_rows("warehouses", [
                {"warehouse_name": None, "location": None},
            ]),
            routes_mod._import_movements([
                {"product_sku": None, "quantity": "1", "movement_type": None, "reason": None},
            ]),
            routes_mod._import_rows("purchase_orders", [
                {"supplier_name": None, "product_sku": "RD-X", "quantity": "1", "status": None},
            ]),
        ]

    for result in results:
        assert result["imported"] == 0
        assert result["skipped"] == 1 == len(result["errors"])
        assert result["errors"][0]["error_code"] == "missing_required"
        assert "db_error" not in result["error_counts"]


def test_import_movements_stock_guard_is_stock_violation_real_db(app, clean_rd):
    """Real sp_movement_record stock guard -> stock_violation taxonomy."""
    _mk_product(app, "RD-MOVGUARD", stock=5)
    with app.app_context():
        result = routes_mod._import_movements([
            {"product_sku": "RD-MOVGUARD", "quantity": "10", "movement_type": "OUT", "reason": "rd"},
            {"product_sku": "RD-MOVGUARD", "quantity": "2", "movement_type": "IN", "reason": "rd"},
        ])

    assert result["imported"] == 1
    assert result["skipped"] == 1 == len(result["errors"])
    entry = result["errors"][0]
    assert (entry["row"], entry["field"], entry["error_code"]) == (1, "quantity", "stock_violation")
    assert "Insufficient stock" in entry["reason"]


def test_import_movements_bogus_numeric_ids_fk_not_found(app, clean_rd):
    """Bogus numeric product ids (new or legacy column) skip as
    fk_product_not_found before reaching the DB — never db_error."""
    with app.app_context():
        result = routes_mod._import_movements([
            {"product_sku": "999999999", "quantity": "1", "movement_type": "IN", "reason": "rd"},
            {"product_id": "999999999", "quantity": "1", "movement_type": "IN", "reason": "rd"},
        ])

    assert result["imported"] == 0
    assert result["skipped"] == 2 == len(result["errors"])
    assert [e["error_code"] for e in result["errors"]] == ["fk_product_not_found"] * 2
    assert "db_error" not in result["error_counts"]
