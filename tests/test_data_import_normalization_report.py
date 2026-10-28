"""Tests for the additive preview FK normalization report (Phase 1 #4).

Covers:
- Pure unit tests for DataImportService.classify_fk_matches (no DB)
- DB test for DataImportService.build_fk_stored_values (active rows only)
- preview_import additive keys (defaults, raw values, row cap)
- Endpoint payload for /admin/data-import/preview/<entity> (real DB)

Convention: DB rows created here use the ``NRM-`` prefix and are removed by
the ``clean_nrm`` fixture before and after each DB test.
"""
from __future__ import annotations

import pytest
from flask_login.utils import _create_identifier

from app.database import get_cursor
from app.repositories import UserRepository
from app.services import data_import_service
from app.services.data_import_service import DataImportService

PRODUCTS_CSV_HEADER = "sku,name,unit_price,current_stock,reorder_point,category,supplier_name"

FK_KEYS = (
    "fk_matches",
    "fk_match_count",
    "fk_exact_match_count",
    "fk_normalized_match_count",
    "fk_numeric_match_count",
)


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


@pytest.fixture
def clean_nrm(app):
    """Delete every NRM-prefixed test row before and after a DB test."""

    def _do():
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM products WHERE LOWER(sku) LIKE 'nrm-%'")
                cur.execute("DELETE FROM suppliers WHERE LOWER(name) LIKE 'nrm-%'")

    _do()
    yield
    _do()


def _classify(rows, entity, caches, *, stored=None, raw_rows=None, cap=None):
    kwargs = {"fk_stored": stored, "raw_rows": raw_rows}
    if cap is not None:
        kwargs["display_cap"] = cap
    return DataImportService.classify_fk_matches(rows, entity, caches, **kwargs)


# ══════════════════════════════════════════════════════════════════════
# Unit tests: classify_fk_matches (pure, fake caches, NO DB)
# ══════════════════════════════════════════════════════════════════════

def test_exact_stored_spelling_counted_but_not_listed():
    rows = [{"sku": "T-1", "name": "Thing", "supplier_name": "Acme"}]
    caches = {"suppliers": {"acme": 7}, "products": {}}
    stored = {"suppliers": {"acme": "Acme"}, "products": {}}

    result = _classify(rows, "products", caches, stored=stored)

    assert result["match_count"] == 1
    assert result["exact_count"] == 1
    assert result["normalized_count"] == 0
    assert result["numeric_count"] == 0
    assert result["matches"] == []


def test_case_only_match_listed_with_raw_and_normalized_message():
    rows = [{"sku": "T-1", "name": "Thing", "supplier_name": "ACME"}]
    caches = {"suppliers": {"acme": 7}, "products": {}}
    stored = {"suppliers": {"acme": "Acme"}, "products": {}}

    result = _classify(rows, "products", caches, stored=stored)

    assert result["match_count"] == 1
    assert result["exact_count"] == 0
    assert result["normalized_count"] == 1
    assert len(result["matches"]) == 1
    entry = result["matches"][0]
    assert entry["row"] == 1
    assert entry["field"] == "supplier_name"
    assert entry["raw_value"] == "ACME"
    assert entry["normalized_value"] == "acme"
    assert entry["match_type"] == "normalized"
    assert entry["error_code"] == "fk_normalized_match"
    assert entry["severity"] == "info"
    assert entry["raw_value"].lower() in entry["message"].lower()


def test_surrounding_whitespace_normalized_with_raw_spaces_preserved():
    rows = [{"sku": "T-1", "name": "Thing", "supplier_name": "Acme"}]
    raw_rows = [{"sku": "T-1", "name": "Thing", "supplier_name": "  Acme  "}]
    caches = {"suppliers": {"acme": 7}, "products": {}}
    stored = {"suppliers": {"acme": "Acme"}, "products": {}}

    result = _classify(
        rows, "products", caches, stored=stored, raw_rows=raw_rows
    )

    assert result["exact_count"] == 0
    assert result["normalized_count"] == 1
    entry = result["matches"][0]
    assert entry["raw_value"] == "  Acme  "
    assert entry["normalized_value"] == "acme"
    assert entry["match_type"] == "normalized"


def test_case_and_whitespace_variant_is_normalized():
    rows = [{"sku": "T-1", "name": "Thing", "supplier_name": "aCmE"}]
    raw_rows = [{"sku": "T-1", "name": "Thing", "supplier_name": " aCmE "}]
    caches = {"suppliers": {"acme": 7}, "products": {}}
    stored = {"suppliers": {"acme": "Acme"}, "products": {}}

    result = _classify(
        rows, "products", caches, stored=stored, raw_rows=raw_rows
    )

    assert result["normalized_count"] == 1
    assert result["matches"][0]["raw_value"] == " aCmE "
    assert result["matches"][0]["normalized_value"] == "acme"


def test_internal_double_space_does_not_match():
    rows = [{"sku": "T-1", "name": "Thing", "supplier_name": "Acme  Corp"}]
    caches = {"suppliers": {"acme corp": 7}, "products": {}}
    stored = {"suppliers": {"acme corp": "Acme Corp"}, "products": {}}

    result = _classify(rows, "products", caches, stored=stored)

    assert result["match_count"] == 0
    assert result["matches"] == []
    assert result["normalized_count"] == 0
    assert result["numeric_count"] == 0


def test_numeric_id_is_labeled_numeric_id_and_message_names_id():
    rows = [{"sku": "T-1", "name": "Thing", "supplier_name": "5"}]
    caches = {"suppliers": {"acme corp": 5}, "products": {}}

    result = _classify(rows, "products", caches)

    assert result["match_count"] == 1
    assert result["numeric_count"] == 1
    assert result["normalized_count"] == 0
    entry = result["matches"][0]
    assert entry["field"] == "supplier_name"
    assert entry["raw_value"] == "5"
    assert entry["match_type"] == "numeric_id"
    assert entry["error_code"] == "fk_numeric_match"
    assert entry["severity"] == "info"
    assert "5" in entry["message"]
    assert "supplier" in entry["message"].lower()


def test_digit_named_natural_key_beats_numeric_fallback():
    rows = [{"sku": "T-1", "name": "Thing", "supplier_name": "5"}]
    raw_rows = [{"sku": "T-1", "name": "Thing", "supplier_name": " 5 "}]
    caches = {"suppliers": {"5": 9}, "products": {}}
    stored = {"suppliers": {"5": "5"}, "products": {}}

    result = _classify(
        rows, "products", caches, stored=stored, raw_rows=raw_rows
    )

    assert result["numeric_count"] == 0
    assert result["normalized_count"] == 1
    assert result["matches"][0]["match_type"] == "normalized"
    assert result["matches"][0]["error_code"] == "fk_normalized_match"


def test_blank_and_none_values_are_skipped():
    rows = [
        {"supplier_name": ""},
        {"supplier_name": "   "},
        {"supplier_name": None},
    ]
    caches = {"suppliers": {"acme": 1}, "products": {}}
    stored = {"suppliers": {"acme": "Acme"}, "products": {}}

    result = _classify(rows, "products", caches, stored=stored)

    assert result["match_count"] == 0
    assert result["matches"] == []


def test_fk_fields_covered_for_products_movements_and_purchase_orders():
    caches = {
        "suppliers": {"acme": 1, "po sup": 2},
        "products": {"widget": 3},
    }
    stored = {
        "suppliers": {"acme": "Acme", "po sup": "PO Sup"},
        "products": {"widget": "Widget"},
    }

    products = _classify(
        [{"sku": "T-1", "name": "Thing", "supplier_name": "ACME"}],
        "products", caches, stored=stored,
    )
    assert products["normalized_count"] == 1
    assert products["matches"][0]["field"] == "supplier_name"

    movements = _classify(
        [{"product_sku": "WIDGET", "quantity": "1"}],
        "movements", caches, stored=stored,
    )
    assert movements["normalized_count"] == 1
    assert movements["matches"][0]["field"] == "product_sku"

    po = _classify(
        [{"supplier_name": "PO SUP", "product_sku": "WIDGET", "quantity": "1"}],
        "purchase_orders", caches, stored=stored,
    )
    assert po["normalized_count"] == 2
    assert {m["field"] for m in po["matches"]} == {"supplier_name", "product_sku"}


def test_entity_natural_keys_are_not_treated_as_fk_matches():
    rows = [{"sku": "Acme", "name": "Acme", "supplier_name": ""}]
    caches = {"suppliers": {"acme": 1}, "products": {"acme": 2}}
    stored = {"suppliers": {"acme": "Acme"}, "products": {"acme": "Acme"}}

    result = _classify(rows, "products", caches, stored=stored)

    assert result["match_count"] == 0
    assert result["matches"] == []


def test_sixty_normalized_matches_list_fifty_but_count_sixty():
    caches = {
        "suppliers": {f"sup {i:03d}": i + 1 for i in range(60)},
        "products": {},
    }
    stored = {
        "suppliers": {f"sup {i:03d}": f"SUP {i:03d}" for i in range(60)},
        "products": {},
    }
    rows = [
        {"sku": f"T-{i}", "name": "Thing", "supplier_name": f"sup {i:03d}"}
        for i in range(60)
    ]

    result = _classify(rows, "products", caches, stored=stored)

    assert result["match_count"] == 60
    assert result["normalized_count"] == 60
    assert result["exact_count"] == 0
    assert len(result["matches"]) == 50
    assert result["matches"][-1]["row"] == 50


@pytest.mark.parametrize("entity", ["suppliers", "warehouses", "no_such_entity"])
def test_entities_without_fk_fields_return_zeroes(entity):
    rows = [{"supplier_name": "Acme", "product_sku": "Widget", "warehouse_name": "WH"}]
    caches = {"suppliers": {"acme": 1}, "products": {"widget": 2}}

    result = _classify(rows, entity, caches)

    assert result == {
        "matches": [],
        "match_count": 0,
        "exact_count": 0,
        "normalized_count": 0,
        "numeric_count": 0,
    }


# ══════════════════════════════════════════════════════════════════════
# DB: build_fk_stored_values (active rows only)
# ══════════════════════════════════════════════════════════════════════

def test_build_fk_stored_values_returns_active_stored_spellings(app, clean_nrm):
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO suppliers (name, initials, location, lead_days) "
                "VALUES ('NRM-Stored Name', 'SN', '', 0)"
            )
            cur.execute(
                "INSERT INTO suppliers (name, initials, location, lead_days) "
                "VALUES ('NRM-Deleted Name', 'DN', '', 0) RETURNING id"
            )
            deleted_id = cur.fetchone()["id"]
            cur.execute(
                "UPDATE suppliers SET deleted_at = NOW() WHERE id = %s", (deleted_id,)
            )
            cur.execute(
                """INSERT INTO products (sku, name, unit_price, current_stock,
                   reorder_point, category, supplier_id)
                   VALUES ('NRM-Stored-SKU', 'Stored Product', 1, 1, 1, 'Test', NULL)"""
            )

        with get_cursor() as cur:
            stored = DataImportService.build_fk_stored_values(cur)

    assert set(stored) == {"suppliers", "products"}
    assert stored["suppliers"]["nrm-stored name"] == "NRM-Stored Name"
    assert stored["products"]["nrm-stored-sku"] == "NRM-Stored-SKU"
    assert "nrm-deleted name" not in stored["suppliers"]


def test_build_fk_preview_data_resolves_case_collision_deterministically(app, clean_nrm):
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO suppliers (name, initials, location, lead_days) "
                "VALUES ('NRM-Case Collision', 'CC', '', 0) RETURNING id"
            )
            low_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO suppliers (name, initials, location, lead_days) "
                "VALUES ('nrm-case collision', 'CC', '', 0) RETURNING id"
            )
            high_id = cur.fetchone()["id"]

        with get_cursor() as cur:
            caches, stored = DataImportService.build_fk_preview_data(cur)

    assert high_id > low_id
    assert caches["suppliers"]["nrm-case collision"] == high_id
    assert stored["suppliers"]["nrm-case collision"] == "nrm-case collision"


# ══════════════════════════════════════════════════════════════════════
# preview_import additive keys (pure, NO DB)
# ══════════════════════════════════════════════════════════════════════

def test_preview_early_returns_carry_fk_match_keys():
    empty = DataImportService.preview_import("", "products")
    unknown = DataImportService.preview_import("sku,name\nA,B", "no_such_entity")
    missing = DataImportService.preview_import("sku,name\nA,B", "products")

    for result in (empty, unknown, missing):
        assert result["valid"] is False
        for key in FK_KEYS:
            expected = [] if key == "fk_matches" else 0
            assert result[key] == expected, f"{key} wrong on early return"


def test_preview_counts_exact_match_without_listing_it():
    csv_content = f"{PRODUCTS_CSV_HEADER}\nNRM-EX-1,Exact Product,1,1,1,Cat,Acme"

    result = DataImportService.preview_import(
        csv_content, "products",
        fk_caches={"suppliers": {"acme": 1}, "products": {}},
        fk_stored={"suppliers": {"acme": "Acme"}, "products": {}},
    )

    assert result["valid"] is True
    assert result["warning_count"] == 0
    assert result["fk_match_count"] == 1
    assert result["fk_exact_match_count"] == 1
    assert result["fk_normalized_match_count"] == 0
    assert result["fk_matches"] == []


def test_preview_reports_raw_csv_value_and_stays_valid():
    csv_content = f"{PRODUCTS_CSV_HEADER}\nNRM-RW-1,Raw Product,1,1,1,Cat, acme "

    result = DataImportService.preview_import(
        csv_content, "products",
        fk_caches={"suppliers": {"acme": 1}, "products": {}},
        fk_stored={"suppliers": {"acme": "Acme"}, "products": {}},
    )

    assert result["valid"] is True
    assert result["warning_count"] == 0
    assert result["fk_match_count"] == 1
    assert result["fk_exact_match_count"] == 0
    assert result["fk_normalized_match_count"] == 1
    entry = result["fk_matches"][0]
    assert entry["row"] == 1
    assert entry["raw_value"] == " acme "
    assert entry["normalized_value"] == "acme"
    assert entry["match_type"] == "normalized"


def test_preview_alias_header_preserves_pre_strip_raw_value():
    header = "sku,name,unit_price,current_stock,reorder_point,category,supplier"
    csv_content = f"{header}\nNRM-AL-1,Alias Product,1,1,1,Cat,  Acme  "

    result = DataImportService.preview_import(
        csv_content, "products",
        fk_caches={"suppliers": {"acme": 1}, "products": {}},
        fk_stored={"suppliers": {"acme": "Acme"}, "products": {}},
    )

    assert result["valid"] is True
    entry = result["fk_matches"][0]
    assert entry["field"] == "supplier_name"
    assert entry["raw_value"] == "  Acme  "
    assert entry["normalized_value"] == "acme"


def test_preview_without_fk_caches_keeps_empty_defaults():
    csv_content = f"{PRODUCTS_CSV_HEADER}\nNRM-NC-1,No Cache,1,1,1,Cat,Acme"

    result = DataImportService.preview_import(csv_content, "products")

    assert result["valid"] is True
    for key in FK_KEYS:
        expected = [] if key == "fk_matches" else 0
        assert result[key] == expected


@pytest.mark.parametrize("cap,expected", [(5, 5), (6, 6)])
def test_preview_fk_matches_respect_row_cap(monkeypatch, cap, expected):
    monkeypatch.setattr(data_import_service, "MAX_PREVIEW_ROWS", cap)
    lines = [PRODUCTS_CSV_HEADER]
    for i in range(6):
        lines.append(f"NRM-CAP-{i},Cap Product {i},1,1,1,Cat,acme")

    result = DataImportService.preview_import(
        "\n".join(lines), "products",
        fk_caches={"suppliers": {"acme": 1}, "products": {}},
        fk_stored={"suppliers": {"acme": "Acme"}, "products": {}},
    )

    assert result["rows_truncated"] is (cap < 6)
    assert result["fk_match_count"] == expected
    assert len(result["fk_matches"]) == expected


# ══════════════════════════════════════════════════════════════════════
# Endpoint tests (real DB)
# ══════════════════════════════════════════════════════════════════════

def test_preview_endpoint_reports_exact_and_normalized(app, clean_nrm):
    client = _session_client(app, "admin")

    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO suppliers (name, initials, location, lead_days) "
                "VALUES ('NRM-Exact Supplier', 'ES', '', 0)"
            )

    csv_content = "\n".join([
        PRODUCTS_CSV_HEADER,
        "NRM-EP-1,Exact Product,1,1,1,Cat,NRM-Exact Supplier",
        "NRM-EP-2,Lower Product,1,1,1,Cat,nrm-exact supplier",
    ])
    resp = client.post(
        "/admin/data-import/preview/products",
        data={"csv_content": csv_content},
        content_type="application/x-www-form-urlencoded",
    )

    assert resp.status_code == 200
    preview = resp.get_json()["preview"]
    assert preview["valid"] is True
    assert preview["warning_count"] == 0
    assert preview["fk_match_count"] == 2
    assert preview["fk_exact_match_count"] == 1
    assert preview["fk_normalized_match_count"] == 1
    assert preview["fk_numeric_match_count"] == 0
    assert len(preview["fk_matches"]) == 1
    entry = preview["fk_matches"][0]
    assert entry["row"] == 2
    assert entry["field"] == "supplier_name"
    assert entry["raw_value"] == "nrm-exact supplier"
    assert entry["normalized_value"] == "nrm-exact supplier"
    assert entry["match_type"] == "normalized"
    assert entry["error_code"] == "fk_normalized_match"
    assert entry["severity"] == "info"


def test_preview_endpoint_db_unavailable_keeps_fk_keys_empty(app, monkeypatch):
    import app.routes.admin.data_import_routes as routes_mod

    client = _session_client(app, "admin")

    def _boom(*args, **kwargs):
        raise Exception("simulated db outage")

    monkeypatch.setattr(routes_mod, "get_cursor", _boom)

    csv_content = f"{PRODUCTS_CSV_HEADER}\nNRM-DB-1,Db Product,1,1,1,Cat,Any Co"
    resp = client.post(
        "/admin/data-import/preview/products",
        data={"csv_content": csv_content},
        content_type="application/x-www-form-urlencoded",
    )

    assert resp.status_code == 200
    preview = resp.get_json()["preview"]
    assert preview["valid"] is False
    assert any("db_unavailable" in str(e) for e in preview["errors"])
    for key in FK_KEYS:
        expected = [] if key == "fk_matches" else 0
        assert preview[key] == expected
