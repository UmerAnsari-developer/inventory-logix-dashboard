"""Tests for preview FK validation (data import preview warnings).

Covers:
- Pure unit tests for DataImportService.validate_fk_rows (no DB)
- preview_import integration of warnings (capping, backward compat)
- Endpoint tests for /admin/data-import/preview/<entity> (real DB)
- Preview-vs-import parity: a value that warns in preview must be
  skipped-or-NULL-supplier at import, and a value that does not warn
  must import successfully.
"""
from __future__ import annotations

import pytest
from flask_login.utils import _create_identifier

from app.database import get_cursor
from app.repositories import UserRepository
from app.services import data_import_service
from app.services.data_import_service import DataImportService


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


# ══════════════════════════════════════════════════════════════════════
# Unit tests: validate_fk_rows (pure, fake caches, NO DB)
# ══════════════════════════════════════════════════════════════════════

def test_validate_fk_rows_products_unknown_supplier_warns():
    """Products row with unknown supplier_name -> exactly 1 warning, full schema."""
    rows = [{"sku": "T-1", "name": "Thing", "supplier_name": "Acme Corp"}]
    caches = {"suppliers": {"other co": 1}, "products": {}}

    warnings = DataImportService.validate_fk_rows(rows, "products", caches)

    assert len(warnings) == 1
    w = warnings[0]
    assert w["row"] == 1
    assert w["field"] == "supplier_name"
    assert w["value"] == "Acme Corp"
    assert w["error_code"] == "fk_supplier_not_found"
    assert w["severity"] == "warning"
    assert "imported without supplier" in w["message"]
    assert "Row 1" in w["message"]


def test_validate_fk_rows_products_case_whitespace_match():
    """Normalized match (case/whitespace tolerant) -> no warning."""
    rows = [{"sku": "T-1", "name": "Thing", "supplier_name": "ACME  CORP "}]
    caches = {"suppliers": {"acme  corp": 7}, "products": {}}

    warnings = DataImportService.validate_fk_rows(rows, "products", caches)

    assert warnings == []


def test_validate_fk_rows_movements_numeric_fallback():
    """Movements keep the legacy numeric-ID fallback; misses warn with skip message."""
    caches = {"suppliers": {}, "products": {"widget": 1}}

    # Numeric value matching an existing product id -> no warning
    ok = DataImportService.validate_fk_rows(
        [{"product_sku": "1", "quantity": "5"}], "movements", caches
    )
    assert ok == []

    # Numeric value NOT matching any product id -> warning, "will be skipped"
    miss_num = DataImportService.validate_fk_rows(
        [{"product_sku": "999", "quantity": "5"}], "movements", caches
    )
    assert len(miss_num) == 1
    assert miss_num[0]["error_code"] == "fk_product_not_found"
    assert "will be skipped" in miss_num[0]["message"]

    # Non-numeric unknown SKU -> warning
    miss_str = DataImportService.validate_fk_rows(
        [{"product_sku": "abc", "quantity": "5"}], "movements", caches
    )
    assert len(miss_str) == 1
    assert miss_str[0]["field"] == "product_sku"


def test_validate_fk_rows_movements_unicode_digit_no_crash():
    """Unicode digits like '²' pass .isdigit() but not .isdecimal(); must warn, not crash."""
    caches = {"suppliers": {}, "products": {"widget": 1}}
    warnings = DataImportService.validate_fk_rows(
        [{"product_sku": "²", "quantity": "5"}], "movements", caches
    )
    assert len(warnings) == 1
    assert warnings[0]["error_code"] == "fk_product_not_found"
    assert warnings[0]["field"] == "product_sku"


def test_validate_fk_rows_purchase_orders_numeric_existence_checked():
    """PO numeric supplier_name is existence-checked like every other FK:
    matching an existing id -> no warning; matching no id -> warning."""
    rows = [{"supplier_name": "1", "product_sku": "widget", "quantity": "5"}]
    caches = {"suppliers": {}, "products": {"widget": 1}}

    warnings = DataImportService.validate_fk_rows(rows, "purchase_orders", caches)

    assert len(warnings) == 1
    assert warnings[0]["field"] == "supplier_name"
    assert warnings[0]["error_code"] == "fk_supplier_not_found"

    # Same value now matches an existing supplier id -> resolves, no warning.
    matching = {"suppliers": {"other co": 1}, "products": {"widget": 1}}
    assert DataImportService.validate_fk_rows(rows, "purchase_orders", matching) == []


def test_validate_fk_rows_products_and_po_numeric_existing_no_warning():
    """Legacy numeric supplier_name/product_sku matching an existing id
    resolves at import -> no preview warning (products + purchase orders)."""
    caches = {"suppliers": {"other co": 2}, "products": {"widget": 2}}

    assert DataImportService.validate_fk_rows(
        [{"sku": "T-1", "name": "Thing", "supplier_name": "2"}], "products", caches
    ) == []
    assert DataImportService.validate_fk_rows(
        [{"supplier_name": "2", "product_sku": "2", "quantity": "5"}],
        "purchase_orders", caches,
    ) == []

    # A numeric value matching NO existing id still warns on both entities.
    prod_miss = DataImportService.validate_fk_rows(
        [{"sku": "T-1", "name": "Thing", "supplier_name": "999"}], "products", caches
    )
    assert len(prod_miss) == 1
    assert prod_miss[0]["error_code"] == "fk_supplier_not_found"

    po_miss = DataImportService.validate_fk_rows(
        [{"supplier_name": "999", "product_sku": "2", "quantity": "5"}],
        "purchase_orders", caches,
    )
    assert len(po_miss) == 1
    assert po_miss[0]["error_code"] == "fk_supplier_not_found"


def test_validate_fk_rows_empty_values_no_warnings():
    """Empty/None values are skipped (importer also skips them)."""
    rows = [
        {"supplier_name": "", "product_sku": None},
        {"supplier_name": "   "},
    ]
    caches = {"suppliers": {}, "products": {}}

    assert DataImportService.validate_fk_rows(rows, "purchase_orders", caches) == []
    assert DataImportService.validate_fk_rows(rows, "products", caches) == []


def test_validate_fk_rows_entities_without_fk_fields():
    """suppliers/warehouses have no FK fields -> no warnings regardless of content."""
    rows = [{"supplier_name": "Ghost Co", "product_sku": "nope", "anything": "x"}]

    assert DataImportService.validate_fk_rows(rows, "suppliers", {}) == []
    assert DataImportService.validate_fk_rows(rows, "warehouses", {}) == []
    # Unknown entity -> no warnings either
    assert DataImportService.validate_fk_rows(rows, "unknown_entity", {}) == []


# ══════════════════════════════════════════════════════════════════════
# preview_import integration (capping + backward compatibility)
# ══════════════════════════════════════════════════════════════════════

def _products_csv(n_rows: int, supplier: str) -> str:
    lines = ["sku,name,unit_price,current_stock,reorder_point,category,supplier_name"]
    for i in range(1, n_rows + 1):
        lines.append(f"FKV-{i:03d},Product {i},9.99,10,5,Cat,{supplier}")
    return "\n".join(lines)


def test_preview_import_warning_cap_and_totals():
    """60-row file with empty caches: 60 warnings total, 50 displayed, valid stays true."""
    result = DataImportService.preview_import(
        _products_csv(60, "Missing Sup X"),
        "products",
        fk_caches={"suppliers": {}, "products": {}},
    )

    assert result["valid"] is True
    assert result["row_count"] == 50
    assert result["total_row_count"] == 60
    assert result["warning_count"] == 60
    assert len(result["warnings"]) == 50


def test_preview_import_without_fk_caches_backward_compat():
    """Calling preview_import without fk_caches -> no warnings (old behavior)."""
    result = DataImportService.preview_import(_products_csv(2, "Ghost Co"), "products")

    assert result["valid"] is True
    assert result["warnings"] == []
    assert result["warning_count"] == 0
    assert result["total_row_count"] == 2
    assert result["rows_truncated"] is False


def test_preview_import_early_returns_carry_new_keys():
    """Empty CSV / unknown entity early returns still include all result keys."""
    new_keys = ("warnings", "warning_count", "total_row_count", "rows_truncated")

    empty = DataImportService.preview_import("", "products")
    assert empty["valid"] is False
    for key in new_keys:
        expected = [] if key == "warnings" else 0
        assert empty[key] == expected

    unknown = DataImportService.preview_import("sku,name\nA,B", "no_such_entity")
    assert unknown["valid"] is False
    for key in new_keys:
        assert key in unknown


def test_preview_import_row_cap_bounds_memory():
    """Files beyond MAX_PREVIEW_ROWS are capped: rows_truncated=True, totals capped."""
    result = DataImportService.preview_import(
        _products_csv(data_import_service.MAX_PREVIEW_ROWS + 1, "Missing Sup X"),
        "products",
        fk_caches={"suppliers": {}, "products": {}},
    )

    assert result["rows_truncated"] is True
    assert result["total_row_count"] == data_import_service.MAX_PREVIEW_ROWS
    assert result["row_count"] == 50
    assert result["warning_count"] == data_import_service.MAX_PREVIEW_ROWS


# ══════════════════════════════════════════════════════════════════════
# Endpoint tests (real DB)
# ══════════════════════════════════════════════════════════════════════

PRODUCTS_CSV_HEADER = "sku,name,unit_price,current_stock,reorder_point,category,supplier_name"


def test_preview_endpoint_reports_fk_warning(app):
    """Unknown supplier_name in products CSV -> warning, still valid."""
    client = _session_client(app, "admin")
    csv_content = (
        f"{PRODUCTS_CSV_HEADER}\nFKV-WARN-1,Warn Product,9.99,10,5,Cat,Nonexistent Corp XYZ"
    )

    resp = client.post(
        "/admin/data-import/preview/products",
        data={"csv_content": csv_content},
        content_type="application/x-www-form-urlencoded",
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    preview = data["preview"]
    assert preview["valid"] is True
    assert preview["warning_count"] >= 1
    assert preview["warnings"][0]["field"] == "supplier_name"
    assert "Nonexistent Corp XYZ" in preview["warnings"][0]["message"]


def test_preview_endpoint_real_supplier_no_warning(app):
    """A real supplier name from the DB -> zero warnings."""
    client = _session_client(app, "admin")

    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO suppliers (name, initials, location, lead_days) "
                "VALUES (%s, %s, %s, %s)",
                ("FKV Real Supplier", "FRS", "Test City", 3),
            )
            cur.execute(
                "SELECT id, LOWER(TRIM(name)) AS norm_name FROM suppliers "
                "WHERE name = %s AND deleted_at IS NULL LIMIT 1",
                ("FKV Real Supplier",),
            )
            row = cur.fetchone()
            supplier_id, norm_name = row["id"], row["norm_name"]

    try:
        csv_content = (
            f"{PRODUCTS_CSV_HEADER}\nFKV-OK-1,Ok Product,9.99,10,5,Cat,FKV Real Supplier"
        )
        resp = client.post(
            "/admin/data-import/preview/products",
            data={"csv_content": csv_content},
            content_type="application/x-www-form-urlencoded",
        )

        assert resp.status_code == 200
        preview = resp.get_json()["preview"]
        assert preview["valid"] is True
        assert preview["warning_count"] == 0
    finally:
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM suppliers WHERE id = %s", (supplier_id,))


def test_preview_endpoint_db_unavailable_graceful(app, monkeypatch):
    """FK cache build failure -> preview still returns, valid=False + db_unavailable."""
    import app.routes.admin.data_import_routes as routes_mod

    client = _session_client(app, "admin")

    def _boom(*args, **kwargs):
        raise Exception("simulated db outage")

    monkeypatch.setattr(routes_mod, "get_cursor", _boom)

    csv_content = f"{PRODUCTS_CSV_HEADER}\nFKV-DB-1,Db Product,9.99,10,5,Cat,Any Co"
    resp = client.post(
        "/admin/data-import/preview/products",
        data={"csv_content": csv_content},
        content_type="application/x-www-form-urlencoded",
    )

    assert resp.status_code == 200
    data = resp.get_json()
    # Response stays success-shaped
    assert data["success"] is True
    assert "preview" in data
    preview = data["preview"]
    assert preview["valid"] is False
    assert any("db_unavailable" in str(e) for e in preview["errors"])


# ══════════════════════════════════════════════════════════════════════
# Preview-vs-import parity (architect requirement)
# ══════════════════════════════════════════════════════════════════════

def test_preview_import_parity_products(app):
    """A supplier_name that warns must import with NULL supplier; a match imports linked."""
    import app.routes.admin.data_import_routes as routes_mod

    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO suppliers (name, initials, location, lead_days) "
                "VALUES (%s, %s, %s, %s)",
                ("FKV Parity Supplier", "FPS", "Test City", 2),
            )
            cur.execute(
                "SELECT id, LOWER(TRIM(name)) AS norm_name FROM suppliers "
                "WHERE name = %s AND deleted_at IS NULL LIMIT 1",
                ("FKV Parity Supplier",),
            )
            row = cur.fetchone()
            supplier_id, norm_name = row["id"], row["norm_name"]

    caches = {"suppliers": {norm_name: supplier_id}, "products": {}}
    warn_row = {
        "sku": "FKV-PAR-P1", "name": "Parity Null Sup", "unit_price": "1.0",
        "current_stock": "1", "reorder_point": "1", "category": "Test",
        "supplier_name": "Ghost Supplier XYZ",
    }
    ok_row = {
        "sku": "FKV-PAR-P2", "name": "Parity Linked Sup", "unit_price": "2.0",
        "current_stock": "2", "reorder_point": "1", "category": "Test",
        "supplier_name": "FKV Parity Supplier",
    }

    # Preview side
    warn = DataImportService.validate_fk_rows([warn_row], "products", caches)
    assert len(warn) == 1 and "imported without supplier" in warn[0]["message"]
    assert DataImportService.validate_fk_rows([ok_row], "products", caches) == []

    # Import side (unchanged import code path)
    with app.app_context():
        try:
            routes_mod._import_products([warn_row, ok_row], 0x464B56, caches)
            with get_cursor() as cur:
                cur.execute(
                    "SELECT sku, supplier_id FROM products WHERE sku IN (%s, %s)",
                    (warn_row["sku"], ok_row["sku"]),
                )
                db_rows = {r["sku"]: r["supplier_id"] for r in cur.fetchall()}
            assert db_rows[warn_row["sku"]] is None       # warned -> NULL supplier
            assert db_rows[ok_row["sku"]] == supplier_id  # matched -> linked
        finally:
            with app.app_context():
                with get_cursor(commit=True) as cur:
                    cur.execute(
                        "DELETE FROM products WHERE sku IN (%s, %s)",
                        (warn_row["sku"], ok_row["sku"]),
                    )
                    cur.execute("DELETE FROM suppliers WHERE id = %s", (supplier_id,))


def test_preview_import_parity_products_legacy_numeric_supplier_id(app):
    """Legacy CSV carrying a bare numeric supplier id: an id that exists warns
    nowhere in preview and links at import; a bogus id warns (row imported
    with NULL supplier), exactly as preview predicts."""
    import app.routes.admin.data_import_routes as routes_mod

    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "DELETE FROM products WHERE sku IN (%s, %s)",
                ("FKV-NUM-P1", "FKV-NUM-P2"),
            )
            cur.execute(
                "DELETE FROM suppliers WHERE name = %s", ("FKV Numeric Supplier",)
            )
            cur.execute(
                "INSERT INTO suppliers (name, initials, location, lead_days) "
                "VALUES (%s, %s, %s, %s)",
                ("FKV Numeric Supplier", "FNS", "Test City", 1),
            )
            cur.execute(
                "SELECT id FROM suppliers WHERE name = %s AND deleted_at IS NULL LIMIT 1",
                ("FKV Numeric Supplier",),
            )
            supplier_id = cur.fetchone()["id"]

    caches = {"suppliers": {"fkv numeric supplier": supplier_id}, "products": {}}
    ok_row = {
        "sku": "FKV-NUM-P1", "name": "Numeric Linked", "unit_price": "1.0",
        "current_stock": "1", "reorder_point": "1", "category": "Test",
        "supplier_name": str(supplier_id),
    }
    miss_row = {
        "sku": "FKV-NUM-P2", "name": "Numeric Bogus", "unit_price": "1.0",
        "current_stock": "1", "reorder_point": "1", "category": "Test",
        "supplier_name": str(supplier_id + 100000),
    }

    # Preview side: existing id -> no warning; bogus id -> warning.
    assert DataImportService.validate_fk_rows([ok_row], "products", caches) == []
    miss = DataImportService.validate_fk_rows([miss_row], "products", caches)
    assert len(miss) == 1
    assert miss[0]["field"] == "supplier_name"
    assert miss[0]["error_code"] == "fk_supplier_not_found"
    assert "imported without supplier" in miss[0]["message"]

    # Import side: existing id links; bogus id -> NULL supplier.
    with app.app_context():
        try:
            imported = routes_mod._import_products([ok_row, miss_row], 0x464B57, caches)["imported"]
            assert imported == 2
            with get_cursor() as cur:
                cur.execute(
                    "SELECT sku, supplier_id FROM products WHERE sku IN (%s, %s)",
                    (ok_row["sku"], miss_row["sku"]),
                )
                db_rows = {r["sku"]: r["supplier_id"] for r in cur.fetchall()}
            assert db_rows[ok_row["sku"]] == supplier_id  # numeric id linked
            assert db_rows[miss_row["sku"]] is None       # bogus id -> NULL supplier
        finally:
            with app.app_context():
                with get_cursor(commit=True) as cur:
                    cur.execute(
                        "DELETE FROM products WHERE sku IN (%s, %s)",
                        (ok_row["sku"], miss_row["sku"]),
                    )
                    cur.execute("DELETE FROM suppliers WHERE id = %s", (supplier_id,))


def test_preview_import_parity_movements(app):
    """A product_sku that warns must be skipped at import; a resolvable one imports."""
    import app.routes.admin.data_import_routes as routes_mod

    with app.app_context():
        # Fixture product owned by this test
        with get_cursor(commit=True) as cur:
            cur.execute("DELETE FROM movements WHERE product_id IN (SELECT id FROM products WHERE sku = %s)", ("FKV-PAR-MOV",))
            cur.execute("DELETE FROM products WHERE sku = %s", ("FKV-PAR-MOV",))
            cur.execute(
                """INSERT INTO products (sku, name, unit_price, current_stock,
                   reorder_point, category, supplier_id)
                   VALUES (%s, %s, %s, %s, %s, %s, NULL)""",
                ("FKV-PAR-MOV", "Parity Mov Product", 1.0, 100, 5, "Test"),
            )
            cur.execute(
                "SELECT id, LOWER(TRIM(sku)) AS norm_sku FROM products WHERE sku = %s",
                ("FKV-PAR-MOV",),
            )
            row = cur.fetchone()
            product_id, norm_sku = row["id"], row["norm_sku"]

    caches = {"suppliers": {}, "products": {norm_sku: product_id}}
    warn_row = {"product_sku": "Ghost SKU XYZ", "quantity": "5", "movement_type": "IN", "reason": "parity"}
    ok_row = {"product_sku": str(product_id), "quantity": "10", "movement_type": "IN", "reason": "parity"}

    # Preview side
    warn = DataImportService.validate_fk_rows([warn_row], "movements", caches)
    assert len(warn) == 1 and "will be skipped" in warn[0]["message"]
    assert DataImportService.validate_fk_rows([ok_row], "movements", caches) == []

    # Import side (unchanged import code path)
    with app.app_context():
        try:
            imported_warn = routes_mod._import_movements([warn_row], caches)["imported"]
            imported_ok = routes_mod._import_movements([ok_row], caches)["imported"]
            assert imported_warn == 0  # warned -> skipped at import
            assert imported_ok == 1    # resolvable -> imported
            with get_cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS c FROM movements "
                    "WHERE product_id = %s AND reference = 'parity'",
                    (product_id,),
                )
                assert int(cur.fetchone()["c"]) == 1
        finally:
            with app.app_context():
                with get_cursor(commit=True) as cur:
                    cur.execute(
                        "DELETE FROM movements WHERE product_id = %s AND reference = 'parity'",
                        (product_id,),
                    )
                    cur.execute("DELETE FROM products WHERE id = %s", (product_id,))


@pytest.mark.parametrize("entity,csv_body", [
    ("products", f"{PRODUCTS_CSV_HEADER}\nFKV-ENT-1,Ent Product,1,1,1,Cat,X"),
    ("suppliers", "supplier_name,location,lead_days\nEnt Sup,Loc,1"),
    ("warehouses", "warehouse_name,location\nEnt WH,Loc"),
    ("movements", "product_sku,quantity,movement_type,reason\n1,1,IN,r"),
    ("purchase_orders", "supplier_name,product_sku,quantity,status\nS,1,1,draft"),
])
def test_preview_entities_valid_is_true_with_warnings_only(entity, csv_body):
    """FK warnings are NON-BLOCKING: valid stays true for warning-only previews."""
    result = DataImportService.preview_import(
        csv_body, entity, fk_caches={"suppliers": {}, "products": {}}
    )
    assert result["valid"] is True
    # Unknown FK refs in these fixtures (where the entity has FK fields)
    if entity in ("products", "movements", "purchase_orders"):
        assert result["warning_count"] >= 1
    else:
        assert result["warning_count"] == 0
