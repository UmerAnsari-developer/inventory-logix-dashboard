"""Tests for additive preview duplicate detection (Phase 1 #5).

Covers:
- Pure unit tests for DataImportService.detect_duplicates (no DB)
- preview_import additive keys (defaults, non-blocking, row cap)
- Endpoint payload for /admin/data-import/preview/<entity>
- DB import behavior parity for duplicate keys (real DB)

Convention: DB rows created here use the ``DUP-`` (products), ``DUP ``
(suppliers) and ``DUPWH-`` (warehouses) prefixes and are removed by the
``clean_dup`` fixture before and after each DB test.
"""
from __future__ import annotations

import pytest
from flask_login.utils import _create_identifier

from app.database import get_cursor
from app.repositories import UserRepository
from app.services import data_import_service
from app.services.data_import_service import DataImportService

PRODUCTS_CSV_HEADER = "sku,name,unit_price,current_stock,reorder_point,category,supplier_name"

DUPLICATE_KEYS = ("duplicates", "duplicate_count")


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


def _detect(rows, entity, *, cap=None):
    if cap is None:
        return DataImportService.detect_duplicates(rows, entity)
    return DataImportService.detect_duplicates(rows, entity, display_cap=cap)


def _prod_row(sku: str) -> dict:
    return {
        "sku": sku, "name": "Product", "unit_price": "1", "current_stock": "1",
        "reorder_point": "1", "category": "Test", "supplier_name": "",
    }


# ══════════════════════════════════════════════════════════════════════
# Unit tests: detect_duplicates (pure, NO DB)
# ══════════════════════════════════════════════════════════════════════

def test_products_exact_sku_duplicate_message_says_update():
    result = _detect([{"sku": "DUP-SKU"}, {"sku": "DUP-SKU"}], "products")

    assert result["duplicate_count"] == 1
    assert len(result["duplicates"]) == 1
    group = result["duplicates"][0]
    assert group["field"] == "sku"
    assert group["value"] == "DUP-SKU"
    assert group["kind"] == "exact"
    assert group["row"] == 1
    assert group["row_count"] == 2
    assert group["rows"] == [2]
    assert group["error_code"] == "duplicate_key"
    assert group["severity"] == "warning"
    assert "update" in group["message"].lower()


def test_products_case_variant_message_says_separate_products():
    result = _detect([{"sku": "DUP-SKU"}, {"sku": "dup-sku"}], "products")

    assert result["duplicate_count"] == 1
    group = result["duplicates"][0]
    assert group["kind"] == "variant"
    assert group["value"] == "DUP-SKU"
    assert group["row"] == 1
    assert group["row_count"] == 2
    assert group["rows"] == [2]
    assert group["severity"] == "warning"
    assert "separate" in group["message"].lower()


def test_products_mixed_exact_and_variant_group_reports_both_outcomes():
    result = _detect(
        [{"sku": "DUP-MIX"}, {"sku": "DUP-MIX"}, {"sku": "dup-mix"}],
        "products",
    )

    assert result["duplicate_count"] == 1
    group = result["duplicates"][0]
    assert group["kind"] == "variant"
    assert group["row_count"] == 3
    assert group["rows"] == [2, 3]
    assert "update" in group["message"].lower()
    assert "separate" in group["message"].lower()


def test_products_repeated_variant_counts_distinct_spellings():
    result = _detect(
        [{"sku": "DUP-REP"}, {"sku": "dup-rep"}, {"sku": "dup-rep"}],
        "products",
    )

    group = result["duplicates"][0]
    assert "1 distinct" in group["message"].lower()
    assert "repeated" in group["message"].lower()


def test_suppliers_mixed_exact_and_variant_group_reports_both_outcomes():
    result = _detect(
        [
            {"supplier_name": "DUP Mixed"},
            {"supplier_name": "DUP Mixed"},
            {"supplier_name": "dup mixed"},
        ],
        "suppliers",
    )

    assert result["duplicate_count"] == 1
    group = result["duplicates"][0]
    assert group["kind"] == "variant"
    assert "already exists" in group["message"].lower()
    assert "separate" in group["message"].lower()


def test_suppliers_exact_message_says_already_exists_and_is_info():
    result = _detect(
        [{"supplier_name": "DUP Supplier"}, {"supplier_name": "DUP Supplier"}],
        "suppliers",
    )

    assert result["duplicate_count"] == 1
    group = result["duplicates"][0]
    assert group["field"] == "supplier_name"
    assert group["kind"] == "exact"
    assert group["severity"] == "info"
    assert "already exists" in group["message"].lower()


def test_suppliers_case_variant_message_says_separate_rows():
    result = _detect(
        [{"supplier_name": "DUP Supplier"}, {"supplier_name": "dup supplier"}],
        "suppliers",
    )

    assert result["duplicate_count"] == 1
    group = result["duplicates"][0]
    assert group["kind"] == "variant"
    assert group["severity"] == "warning"
    assert "separate" in group["message"].lower()


def test_warehouses_exact_message_says_already_exists_and_is_info():
    result = _detect(
        [{"warehouse_name": "DUPWH-WH"}, {"warehouse_name": "DUPWH-WH"}],
        "warehouses",
    )

    assert result["duplicate_count"] == 1
    group = result["duplicates"][0]
    assert group["field"] == "warehouse_name"
    assert group["kind"] == "exact"
    assert group["severity"] == "info"
    assert "already exists" in group["message"].lower()


def test_warehouses_case_variant_message_says_separate_rows():
    result = _detect(
        [{"warehouse_name": "DUPWH-WH"}, {"warehouse_name": "dupwh-wh"}],
        "warehouses",
    )

    assert result["duplicate_count"] == 1
    group = result["duplicates"][0]
    assert group["kind"] == "variant"
    assert group["severity"] == "warning"
    assert "separate" in group["message"].lower()


def test_group_row_is_first_occurrence_not_flagged_separately():
    result = _detect(
        [{"sku": "DUP-X"}, {"sku": "DUP-UNIQUE"}, {"sku": "DUP-X"}],
        "products",
    )

    assert result["duplicate_count"] == 1
    assert len(result["duplicates"]) == 1
    group = result["duplicates"][0]
    assert group["row"] == 1
    assert group["rows"] == [3]
    assert all(g["row"] != 2 for g in result["duplicates"])

    # A lone row is never a duplicate.
    assert _detect([{"sku": "DUP-SOLO"}], "products")["duplicates"] == []


def test_blank_and_none_values_are_ignored():
    rows = [
        {"sku": ""},
        {"sku": "   "},
        {"sku": None},
        {"supplier_name": ""},
        {"warehouse_name": "   "},
    ]

    assert _detect(rows, "products") == {"duplicates": [], "duplicate_count": 0}
    assert _detect(rows, "suppliers") == {"duplicates": [], "duplicate_count": 0}
    assert _detect(rows, "warehouses") == {"duplicates": [], "duplicate_count": 0}


def test_movements_and_purchase_orders_are_never_flagged():
    movement_rows = [
        {"product_sku": "DUP-SKU", "quantity": "1"},
        {"product_sku": "DUP-SKU", "quantity": "1"},
    ]
    po_rows = [
        {"supplier_name": "DUP Supplier", "product_sku": "DUP-SKU", "quantity": "1"},
        {"supplier_name": "DUP Supplier", "product_sku": "DUP-SKU", "quantity": "1"},
    ]

    assert _detect(movement_rows, "movements") == {
        "duplicates": [], "duplicate_count": 0,
    }
    assert _detect(po_rows, "purchase_orders") == {
        "duplicates": [], "duplicate_count": 0,
    }


def test_products_repeated_supplier_fk_is_ignored():
    rows = [
        {"sku": "DUP-A", "supplier_name": "Acme"},
        {"sku": "DUP-B", "supplier_name": "Acme"},
    ]

    assert _detect(rows, "products") == {"duplicates": [], "duplicate_count": 0}


def test_internal_whitespace_is_not_grouped():
    result = _detect(
        [{"supplier_name": "Acme Corp"}, {"supplier_name": "Acme  Corp"}],
        "suppliers",
    )

    assert result["duplicate_count"] == 0
    assert result["duplicates"] == []


def test_sixty_one_identical_skus_is_one_group():
    rows = [{"sku": "DUP-61-SAME"} for _ in range(61)]

    result = _detect(rows, "products")

    assert result["duplicate_count"] == 1
    assert len(result["duplicates"]) == 1
    group = result["duplicates"][0]
    assert group["row_count"] == 61
    assert group["row"] == 1
    assert group["rows"][0] == 2
    assert len(group["rows"]) <= 50  # bounded later-row numbers


def test_sixty_distinct_groups_list_fifty_but_count_sixty():
    rows = []
    for i in range(60):
        rows.append({"sku": f"DUP-GRP-{i:03d}"})
        rows.append({"sku": f"DUP-GRP-{i:03d}"})

    result = _detect(rows, "products")

    assert result["duplicate_count"] == 60
    assert len(result["duplicates"]) == 50


def test_surrounding_whitespace_is_exact_after_trim():
    result = _detect(
        [{"supplier_name": " Acme "}, {"supplier_name": "Acme"}], "suppliers"
    )

    assert result["duplicate_count"] == 1
    group = result["duplicates"][0]
    assert group["kind"] == "exact"
    assert group["row_count"] == 2
    assert group["row"] == 1
    assert group["rows"] == [2]


# ══════════════════════════════════════════════════════════════════════
# preview_import additive keys (pure, NO DB)
# ══════════════════════════════════════════════════════════════════════

def test_preview_early_returns_carry_duplicate_keys():
    empty = DataImportService.preview_import("", "products")
    unknown = DataImportService.preview_import("sku,name\nA,B", "no_such_entity")
    missing = DataImportService.preview_import("sku,name\nA,B", "products")

    for result in (empty, unknown, missing):
        assert result["valid"] is False
        for key in DUPLICATE_KEYS:
            expected = [] if key == "duplicates" else 0
            assert result[key] == expected


def test_preview_duplicates_are_non_blocking_and_leave_warnings_alone():
    csv_content = "\n".join([
        PRODUCTS_CSV_HEADER,
        "DUP-EP-SAME,First,1,1,1,Cat,Acme",
        "DUP-EP-SAME,Second,1,1,1,Cat,Acme",
    ])

    result = DataImportService.preview_import(
        csv_content, "products",
        fk_caches={"suppliers": {"acme": 1}, "products": {}},
    )

    assert result["valid"] is True
    assert result["warning_count"] == 0
    assert result["duplicates"]
    assert result["duplicate_count"] == 1
    assert result["duplicates"][0]["row_count"] == 2


def test_preview_duplicates_respect_row_cap(monkeypatch):
    monkeypatch.setattr(data_import_service, "MAX_PREVIEW_ROWS", 5)
    lines = [PRODUCTS_CSV_HEADER]
    for i in range(6):
        lines.append(f"DUP-CAP-SAME,Product {i},1,1,1,Cat,")

    result = DataImportService.preview_import("\n".join(lines), "products")

    assert result["rows_truncated"] is True
    assert result["duplicate_count"] == 1
    group = result["duplicates"][0]
    assert group["row_count"] == 5
    assert group["rows"] == [2, 3, 4, 5]


# ══════════════════════════════════════════════════════════════════════
# Endpoint test
# ══════════════════════════════════════════════════════════════════════

def test_preview_endpoint_reports_duplicates(app):
    client = _session_client(app, "admin")
    csv_content = "\n".join([
        PRODUCTS_CSV_HEADER,
        "DUP-EP-1,First,1,1,1,Cat,Acme",
        "DUP-EP-1,Second,1,1,1,Cat,Acme",
    ])

    resp = client.post(
        "/admin/data-import/preview/products",
        data={"csv_content": csv_content},
        content_type="application/x-www-form-urlencoded",
    )

    assert resp.status_code == 200
    preview = resp.get_json()["preview"]
    assert preview["valid"] is True
    assert preview["duplicate_count"] == 1
    assert len(preview["duplicates"]) == 1
    group = preview["duplicates"][0]
    assert group["field"] == "sku"
    assert group["row"] == 1
    assert group["row_count"] == 2
    assert group["error_code"] == "duplicate_key"


# ══════════════════════════════════════════════════════════════════════
# DB import behavior parity (real DB)
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def clean_dup(app):
    """Delete only DUP-/DUP /DUPWH- prefixed rows before and after a DB test."""

    def _do():
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute(
                    "DELETE FROM movements WHERE product_id IN "
                    "(SELECT id FROM products WHERE LOWER(sku) LIKE 'dup-%')"
                )
                cur.execute("DELETE FROM products WHERE LOWER(sku) LIKE 'dup-%'")
                cur.execute("DELETE FROM suppliers WHERE LOWER(name) LIKE 'dup %'")
                cur.execute(
                    "DELETE FROM warehouses WHERE LOWER(warehouse_name) LIKE 'dupwh-%'"
                )

    _do()
    yield
    _do()


def test_db_import_products_same_sku_twice_updates_earlier_row(app, clean_dup):
    import app.routes.admin.data_import_routes as routes_mod

    rows = [
        _prod_row("DUP-SAME"),
        _prod_row("DUP-SAME"),
    ]
    rows[0]["name"] = "First Name"
    rows[1]["name"] = "Second Name"

    with app.app_context():
        result = routes_mod._import_rows("products", rows)

        with get_cursor() as cur:
            cur.execute("SELECT name FROM products WHERE sku = 'DUP-SAME'")
            db_rows = cur.fetchall()

    assert result["imported"] == 2
    assert len(db_rows) == 1
    assert db_rows[0]["name"] == "Second Name"


def test_db_import_suppliers_same_name_twice_skips_second(app, clean_dup):
    import app.routes.admin.data_import_routes as routes_mod

    rows = [
        {"supplier_name": "DUP Supplier Same", "location": "Loc", "lead_days": "1"},
        {"supplier_name": "DUP Supplier Same", "location": "Loc", "lead_days": "1"},
    ]

    with app.app_context():
        result = routes_mod._import_rows("suppliers", rows)

    assert result["imported"] == 1
    assert result["skipped"] == 1
    assert result["error_counts"].get("already_exists") == 1
    assert result["errors"][0]["error_code"] == "already_exists"
    assert result["errors"][0]["severity"] == "info"


def test_db_import_warehouses_same_name_twice_skips_second(app, clean_dup):
    import app.routes.admin.data_import_routes as routes_mod

    rows = [
        {"warehouse_name": "DUPWH-Same", "location": "Loc"},
        {"warehouse_name": "DUPWH-Same", "location": "Loc"},
    ]

    with app.app_context():
        result = routes_mod._import_rows("warehouses", rows)

    assert result["imported"] == 1
    assert result["skipped"] == 1
    assert result["error_counts"].get("already_exists") == 1
    assert result["errors"][0]["error_code"] == "already_exists"
    assert result["errors"][0]["severity"] == "info"


def test_db_import_products_case_variants_create_two_rows(app, clean_dup):
    import app.routes.admin.data_import_routes as routes_mod

    rows = [_prod_row("DUP-CASE"), _prod_row("DUP-case")]
    rows[0]["name"] = "Upper"
    rows[1]["name"] = "Lower"

    with app.app_context():
        result = routes_mod._import_rows("products", rows)

        with get_cursor() as cur:
            cur.execute(
                "SELECT sku, name FROM products WHERE LOWER(sku) = 'dup-case' "
                "ORDER BY id"
            )
            db_rows = cur.fetchall()

    assert result["imported"] == 2
    assert len(db_rows) == 2
    assert {r["sku"] for r in db_rows} == {"DUP-CASE", "DUP-case"}
