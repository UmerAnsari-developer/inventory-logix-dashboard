"""Tests for the opt-in "Create missing suppliers automatically" CSV import.

Covers:
- Pure unit tests for DataImportService.classify_creatable_misses (no DB)
- validate_fk_rows / preview_import create_missing behavior (no DB)
- Typo-advisory guard (pure; advisory only — the supplier is still created)
- DB tests for DataImportService.get_or_create_supplier (savepoint degrade paths)
- Integration tests for _import_products / _import_purchase_orders (real DB)
- Endpoint tests for /preview and /upload with create_missing=true (real DB)
- Template source + rendering checks (checkbox gating)

Convention: every row created here is prefixed (products 'CM-', suppliers
'CM ', purchase orders 'CM-PO-') and cleaned by the ``clean_cm`` fixture.
"""
from __future__ import annotations

import difflib
import io

import pytest
from flask_login.utils import _create_identifier

from app.database import get_cursor
from app.repositories import UserRepository
from app.services import DataImportService

PRODUCTS_CSV_HEADER = "sku,name,unit_price,current_stock,reorder_point,category,supplier_name"
PO_CSV_HEADER = "supplier_name,product_sku,quantity,status"


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
def clean_cm(app):
    """Delete every CM-prefixed test row before and after a DB test."""

    def _do():
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM purchase_orders WHERE po_number LIKE 'CM-%'")
                cur.execute(
                    "DELETE FROM movements WHERE product_id IN "
                    "(SELECT id FROM products WHERE sku LIKE 'CM-%')"
                )
                cur.execute("DELETE FROM products WHERE sku LIKE 'CM-%'")
                cur.execute("DELETE FROM suppliers WHERE name LIKE 'CM %'")

    _do()
    yield
    _do()


def _mk_product(app, sku: str, stock: int = 10) -> int:
    """Create a test product (sku prefixed 'CM-') and return its id."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("DELETE FROM products WHERE sku = %s", (sku,))
            cur.execute(
                "INSERT INTO products (sku, name, unit_price, current_stock, "
                "reorder_point, category, supplier_id) "
                "VALUES (%s, %s, 1, %s, 1, 'Test', NULL) RETURNING id",
                (sku, f"Product {sku}", stock),
            )
            return cur.fetchone()["id"]


def _products_csv(n_rows: int, supplier: str) -> str:
    lines = [PRODUCTS_CSV_HEADER]
    for i in range(1, n_rows + 1):
        lines.append(f"CM-GEN-{i:03d},Gen Product {i},1,1,1,Cat,{supplier}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# Unit tests: classify_creatable_misses (pure, fake caches, NO DB)
# ══════════════════════════════════════════════════════════════════════

def test_classify_dedupes_case_and_whitespace_variants():
    rows = [
        {"supplier_name": "Acme Corp"},
        {"supplier_name": " acme corp "},
        {"supplier_name": "ACME CORP"},
    ]
    entries = DataImportService.classify_creatable_misses(
        rows, "products", {"suppliers": {}, "products": {}}
    )

    assert len(entries) == 1
    e = entries[0]
    assert e["field"] == "supplier_name"
    assert e["value"] == "Acme Corp"  # first-seen raw spelling wins
    assert e["row"] == 1
    assert e["row_count"] == 3
    assert e["message"] == "Will create supplier 'Acme Corp' (3 rows)"


def test_classify_skips_cache_hits_empties_and_non_creatable_entities():
    caches = {"suppliers": {"acme corp": 1}, "products": {}}
    rows = [
        {"supplier_name": "Acme Corp"},  # cache hit
        {"supplier_name": ""},           # empty
        {"supplier_name": "   "},        # whitespace
        {"supplier_name": None},         # None
    ]
    assert DataImportService.classify_creatable_misses(rows, "products", caches) == []

    rows2 = [{"supplier_name": "Ghost Co", "product_sku": "x"}]
    assert DataImportService.classify_creatable_misses(rows2, "movements", caches) == []
    assert DataImportService.classify_creatable_misses(rows2, "suppliers", caches) == []
    assert DataImportService.classify_creatable_misses(rows2, "warehouses", caches) == []
    assert DataImportService.classify_creatable_misses(rows2, "no_such_entity", caches) == []


def test_numeric_existing_id_beats_create_missing():
    """A numeric value matching an existing id resolves instead of being
    offered for creation: no warning and no 'will create' entry, armed or
    not — an existing id is never shadowed by a supplier named after it."""
    caches = {"suppliers": {"other co": 7}, "products": {"widget": 1}}
    prod_rows = [{"sku": "T-1", "name": "Thing", "supplier_name": "7"}]
    po_rows = [{"supplier_name": "7", "product_sku": "widget", "quantity": "1"}]

    for entity, rows in (("products", prod_rows), ("purchase_orders", po_rows)):
        assert DataImportService.validate_fk_rows(rows, entity, caches) == []
        assert DataImportService.validate_fk_rows(rows, entity, caches, create_missing=True) == []
        assert DataImportService.classify_creatable_misses(rows, entity, caches) == []


def test_classify_purchase_orders_supplier_field():
    rows = [{"supplier_name": "PO New Co", "product_sku": "P1"}]
    entries = DataImportService.classify_creatable_misses(
        rows, "purchase_orders", {"suppliers": {}, "products": {}}
    )
    assert len(entries) == 1
    assert entries[0]["field"] == "supplier_name"
    assert entries[0]["message"] == "Will create supplier 'PO New Co'"


def test_classify_display_cap_via_preview_count_uncapped():
    lines = [PRODUCTS_CSV_HEADER]
    for i in range(60):
        lines.append(f"CM-CAP-{i:03d},Cap Product {i},1,1,1,Cat,New Supplier {i:03d}")

    result = DataImportService.preview_import(
        "\n".join(lines), "products",
        fk_caches={"suppliers": {}, "products": {}}, create_missing=True,
    )

    assert result["valid"] is True
    assert result["will_create_count"] == 60
    assert len(result["will_create"]) == 50


# ══════════════════════════════════════════════════════════════════════
# validate_fk_rows armed vs unarmed (pure, NO DB)
# ══════════════════════════════════════════════════════════════════════

def test_validate_fk_rows_armed_products_and_po_but_product_miss_remains():
    caches = {"suppliers": {"other co": 1}, "products": {"widget": 1}}
    prod_rows = [{"sku": "T-1", "name": "Thing", "supplier_name": "Acme Corp"}]
    assert DataImportService.validate_fk_rows(
        prod_rows, "products", caches, create_missing=True
    ) == []

    po_rows = [{"supplier_name": "Acme Corp", "product_sku": "Ghost SKU", "quantity": "1"}]
    warnings = DataImportService.validate_fk_rows(
        po_rows, "purchase_orders", caches, create_missing=True
    )
    assert len(warnings) == 1
    assert warnings[0]["field"] == "product_sku"          # supplier miss gone ...
    assert warnings[0]["error_code"] == "fk_product_not_found"  # ... product miss stays


def test_validate_fk_rows_armed_movements_unchanged():
    caches = {"suppliers": {}, "products": {"widget": 1}}
    rows = [{"product_sku": "ghost", "quantity": "5"}]

    armed = DataImportService.validate_fk_rows(rows, "movements", caches, create_missing=True)
    unarmed = DataImportService.validate_fk_rows(rows, "movements", caches)
    assert armed == unarmed
    assert len(armed) == 1
    assert armed[0]["error_code"] == "fk_product_not_found"


def test_validate_fk_rows_unarmed_identical_to_default():
    rows = [{"sku": "T-1", "name": "Thing", "supplier_name": "Acme Corp"}]
    caches = {"suppliers": {"other co": 1}, "products": {}}

    unarmed = DataImportService.validate_fk_rows(rows, "products", caches)
    explicit = DataImportService.validate_fk_rows(rows, "products", caches, create_missing=False)

    assert unarmed == explicit
    assert len(unarmed) == 1
    assert unarmed[0]["error_code"] == "fk_supplier_not_found"
    assert "imported without supplier" in unarmed[0]["message"]


def test_validate_fk_rows_armed_overlong_name_keeps_warning():
    """Only names the INSERT can actually store are suppressed when armed;
    a >150-char name keeps its warning (VARCHAR(150) would reject it)."""
    caches = {"suppliers": {}, "products": {}}
    long_151 = "L" * 151
    long_150 = "L" * 150

    over = DataImportService.validate_fk_rows(
        [{"sku": "T-1", "name": "Thing", "supplier_name": long_151}],
        "products", caches, create_missing=True,
    )
    assert len(over) == 1
    assert over[0]["error_code"] == "fk_supplier_not_found"

    exact = DataImportService.validate_fk_rows(
        [{"sku": "T-2", "name": "Thing 2", "supplier_name": long_150}],
        "products", caches, create_missing=True,
    )
    assert exact == []  # 150 chars fit VARCHAR(150) -> creatable, suppressed


# ══════════════════════════════════════════════════════════════════════
# preview_import armed vs unarmed (pure, NO DB)
# ══════════════════════════════════════════════════════════════════════

def test_preview_unarmed_empty_will_create_and_warnings_as_today():
    result = DataImportService.preview_import(
        _products_csv(2, "Missing Sup X"), "products",
        fk_caches={"suppliers": {}, "products": {}},
    )

    assert result["will_create"] == []
    assert result["will_create_count"] == 0
    assert result["warning_count"] == 2  # unchanged default behavior


def test_preview_armed_warning_count_drops_by_creatable_misses():
    csv_content = _products_csv(3, "Brand New Sup")

    armed = DataImportService.preview_import(
        csv_content, "products",
        fk_caches={"suppliers": {}, "products": {}}, create_missing=True,
    )

    assert armed["valid"] is True
    assert armed["warning_count"] == 0        # creatable misses no longer warn
    assert armed["will_create_count"] == 1    # deduped
    assert armed["will_create"][0]["row_count"] == 3


def test_preview_armed_early_returns_carry_new_keys():
    empty = DataImportService.preview_import("", "products", create_missing=True)
    assert empty["valid"] is False
    assert empty["will_create"] == []
    assert empty["will_create_count"] == 0

    unknown = DataImportService.preview_import(
        "sku,name\nA,B", "no_such_entity", create_missing=True
    )
    assert unknown["valid"] is False
    assert unknown["will_create"] == []
    assert unknown["will_create_count"] == 0


def test_preview_no_kwargs_still_works():
    result = DataImportService.preview_import(_products_csv(2, "Ghost Co"), "products")
    assert result["valid"] is True
    assert result["warning_count"] == 0       # no caches -> no validation (old behavior)
    assert result["will_create"] == []
    assert result["will_create_count"] == 0


# ══════════════════════════════════════════════════════════════════════
# Typo-advisory guard (pure, NO DB)
# ══════════════════════════════════════════════════════════════════════

def test_typo_guard_flags_close_match_but_still_creates():
    caches = {"suppliers": {"acme corp": 1}, "products": {}}
    result = DataImportService.preview_import(
        f"{PRODUCTS_CSV_HEADER}\nCM-TYPO-1,Typo Product,1,1,1,Cat,Acme Corpz",
        "products", fk_caches=caches, create_missing=True,
    )

    typo = [w for w in result["warnings"] if w.get("error_code") == "fk_possible_typo"]
    assert len(typo) == 1
    assert typo[0]["severity"] == "warning"
    assert typo[0]["row"] == 1
    assert "will be created" in typo[0]["message"]
    assert "possible typo of 'acme corp'" in typo[0]["message"]
    # Advisory only: the item is still on the create list.
    assert [e["value"] for e in result["will_create"]] == ["Acme Corpz"]
    assert result["will_create_count"] == 1


def test_typo_guard_far_miss_no_warning():
    caches = {"suppliers": {"acme corp": 1}, "products": {}}
    result = DataImportService.preview_import(
        f"{PRODUCTS_CSV_HEADER}\nCM-TYPO-2,Far Product,1,1,1,Cat,Zzqx",
        "products", fk_caches=caches, create_missing=True,
    )
    assert [w for w in result["warnings"] if w.get("error_code") == "fk_possible_typo"] == []
    assert result["will_create_count"] == 1


def test_typo_guard_skips_values_shorter_than_four_chars():
    # Sanity: without the len<4 guard, "abc" WOULD match "abcx" at cutoff 0.85.
    assert difflib.get_close_matches("abc", ["abcx"], n=1, cutoff=0.85) == ["abcx"]

    caches = {"suppliers": {"abcx": 1}, "products": {}}
    result = DataImportService.preview_import(
        f"{PRODUCTS_CSV_HEADER}\nCM-TYPO-3,Short Product,1,1,1,Cat,Abc",
        "products", fk_caches=caches, create_missing=True,
    )
    assert [w for w in result["warnings"] if w.get("error_code") == "fk_possible_typo"] == []
    assert result["will_create_count"] == 1


def test_warning_count_includes_typo_advisories():
    """warning_count is the raw combined count (base warnings + advisories),
    even though advisories say 'will be created'."""
    caches = {"suppliers": {"acme corp": 1}, "products": {}}
    result = DataImportService.preview_import(
        f"{PRODUCTS_CSV_HEADER}\nCM-TYPO-4,Warn Product,1,1,1,Cat,Acme Corpz",
        "products", fk_caches=caches, create_missing=True,
    )
    advisories = [w for w in result["warnings"] if w.get("error_code") == "fk_possible_typo"]
    assert len(advisories) == 1
    assert result["warning_count"] == 1  # advisory included in the count


def test_typo_advisory_loop_capped_at_display_cap():
    """>50 close-matching misses: the difflib scan runs on at most 50 entries
    (the display cap), so advisories never exceed 50."""
    caches = {
        "suppliers": {f"acme corp {i:03d}": i + 1 for i in range(60)},
        "products": {},
    }
    lines = [PRODUCTS_CSV_HEADER]
    for i in range(60):
        lines.append(f"CM-TCAP-{i:03d},Cap {i},1,1,1,Cat,Acme Corpx {i:03d}")

    result = DataImportService.preview_import(
        "\n".join(lines), "products", fk_caches=caches, create_missing=True,
    )

    advisories = [w for w in result["warnings"] if w.get("error_code") == "fk_possible_typo"]
    assert result["will_create_count"] == 60  # count uncapped
    assert len(advisories) == 50              # loop capped at the display cap
    assert result["warning_count"] == 50


def test_cap_truncation_combined_base_warnings_and_advisories():
    """Base warnings + advisories together exceed 50: display keeps 50
    (base first), warning_count reports the full uncapped total."""
    caches = {
        "suppliers": {f"acme corp {i:02d}": i + 1 for i in range(30)},
        "products": {},
    }
    lines = [PO_CSV_HEADER]
    for i in range(30):
        # Unknown product_sku -> base warning; typo supplier name -> advisory.
        lines.append(f"Acme Corpx {i:02d},CM-GHOST-{i:02d},1,draft")

    result = DataImportService.preview_import(
        "\n".join(lines), "purchase_orders", fk_caches=caches, create_missing=True,
    )

    advisories = [w for w in result["warnings"] if w.get("error_code") == "fk_possible_typo"]
    base = [w for w in result["warnings"] if w.get("error_code") == "fk_product_not_found"]
    assert result["warning_count"] == 60  # 30 base + 30 advisories, uncapped
    assert len(result["warnings"]) == 50  # display cap
    assert len(base) == 30                # base warnings come first ...
    assert len(advisories) == 20          # ... advisories fill the remaining slots
    assert result["will_create_count"] == 30


# ══════════════════════════════════════════════════════════════════════
# DB: get_or_create_supplier (real DB)
# ══════════════════════════════════════════════════════════════════════

def test_get_or_create_supplier_creates_raw_name_and_caches(app, clean_cm):
    cache: dict = {}
    with app.app_context():
        with get_cursor(commit=True) as cur:
            supplier_id = DataImportService.get_or_create_supplier(
                cur, "CM New Vendor Inc", cache
            )
            assert supplier_id is not None
            cur.execute(
                "SELECT name, initials, location, lead_days FROM suppliers WHERE id = %s",
                (supplier_id,),
            )
            row = cur.fetchone()

        assert row["name"] == "CM New Vendor Inc"  # raw trimmed name, not lowercase
        assert row["initials"] == "CN"             # first letters of first two words
        assert len(row["initials"]) <= 10          # VARCHAR(10) contract
        assert row["location"] == ""
        assert row["lead_days"] == 0
        assert cache == {"cm new vendor inc": supplier_id}

        # Case/whitespace variant with a FRESH cache -> SELECT path, same id,
        # no second row.
        with get_cursor(commit=True) as cur:
            again = DataImportService.get_or_create_supplier(
                cur, " cm new vendor inc ", {}
            )
        assert again == supplier_id

        with get_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM suppliers "
                "WHERE LOWER(TRIM(name)) = 'cm new vendor inc'"
            )
            assert int(cur.fetchone()["c"]) == 1


def test_get_or_create_supplier_soft_deleted_name_recreated_active(app, clean_cm):
    """Soft-delete convention: a name held only by a SOFT-DELETED supplier is
    created as a fresh ACTIVE row (partial index uq_suppliers_name_live),
    and the soft-deleted row is left untouched."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO suppliers (name, initials, location, lead_days) "
                "VALUES ('CM Revived Vendor', 'RV', '', 0) RETURNING id"
            )
            old_id = cur.fetchone()["id"]
            cur.execute(
                "UPDATE suppliers SET deleted_at = NOW() WHERE id = %s", (old_id,)
            )

        with get_cursor(commit=True) as cur:
            new_id = DataImportService.get_or_create_supplier(cur, "CM Revived Vendor", {})
        assert new_id is not None
        assert new_id != old_id

        with get_cursor() as cur:
            cur.execute(
                "SELECT id, deleted_at FROM suppliers "
                "WHERE name = 'CM Revived Vendor' ORDER BY id"
            )
            rows = cur.fetchall()
        assert len(rows) == 2
        assert rows[0]["id"] == old_id
        assert rows[0]["deleted_at"] is not None  # soft-deleted row untouched
        assert rows[1]["id"] == new_id
        assert rows[1]["deleted_at"] is None      # fresh active row


def test_get_or_create_supplier_overlong_name_degrades_to_none(app, clean_cm):
    long_name = "CM " + "X" * 160  # 163 chars > VARCHAR(150)
    with app.app_context():
        with get_cursor(commit=True) as cur:
            assert DataImportService.get_or_create_supplier(cur, long_name, {}) is None


# ══════════════════════════════════════════════════════════════════════
# Integration: _import_products (real DB)
# ══════════════════════════════════════════════════════════════════════

def test_import_products_armed_creates_one_supplier_cache_reused(app, clean_cm):
    import app.routes.admin.data_import_routes as routes_mod

    rows = [
        {"sku": "CM-P1", "name": "P1", "unit_price": "1", "current_stock": "1",
         "reorder_point": "1", "category": "Test", "supplier_name": "CM Auto Supplier"},
        {"sku": "CM-P2", "name": "P2", "unit_price": "1", "current_stock": "1",
         "reorder_point": "1", "category": "Test", "supplier_name": "cm auto supplier"},
    ]

    with app.app_context():
        count = routes_mod._import_rows("products", rows, create_missing=True)["imported"]
        assert count == 2

        with get_cursor() as cur:
            cur.execute(
                "SELECT id FROM suppliers "
                "WHERE name = 'CM Auto Supplier' AND deleted_at IS NULL"
            )
            sup_rows = cur.fetchall()
            assert len(sup_rows) == 1
            supplier_id = sup_rows[0]["id"]

            cur.execute("SELECT sku, supplier_id FROM products WHERE sku IN ('CM-P1', 'CM-P2')")
            linked = {r["sku"]: r["supplier_id"] for r in cur.fetchall()}
            assert linked == {"CM-P1": supplier_id, "CM-P2": supplier_id}


def test_import_products_unarmed_unchanged_null_supplier(app, clean_cm):
    import app.routes.admin.data_import_routes as routes_mod

    rows = [
        {"sku": "CM-P3", "name": "P3", "unit_price": "1", "current_stock": "1",
         "reorder_point": "1", "category": "Test", "supplier_name": "CM Ghost Supplier"},
    ]

    with app.app_context():
        count = routes_mod._import_rows("products", rows)["imported"]  # 2-arg backward compat
        assert count == 1

        with get_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM suppliers WHERE name = 'CM Ghost Supplier'"
            )
            assert int(cur.fetchone()["c"]) == 0  # nothing auto-created unarmed
            cur.execute("SELECT supplier_id FROM products WHERE sku = 'CM-P3'")
            assert cur.fetchone()["supplier_id"] is None  # NULL supplier, as today


def test_import_products_armed_supplier_created_audited_under_admin(app, clean_cm):
    import app.routes.admin.data_import_routes as routes_mod
    from flask import g

    with app.app_context():
        admin = UserRepository.find_by_username("admin")
        assert admin is not None
        admin_id = admin.id

    rows = [
        {"sku": "CM-P4", "name": "P4", "unit_price": "1", "current_stock": "1",
         "reorder_point": "1", "category": "Test", "supplier_name": "CM Audited Supplier"},
    ]

    with app.app_context():
        g.user_id = admin_id  # what the before_request hook sets on real requests
        count = routes_mod._import_rows("products", rows, create_missing=True)["imported"]
        assert count == 1

    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT id FROM suppliers WHERE name = 'CM Audited Supplier'")
            supplier_id = cur.fetchone()["id"]
            cur.execute(
                "SELECT action, user_id, target_type, detail FROM audit_log "
                "WHERE action = 'supplier_created' AND target_id = %s",
                (supplier_id,),
            )
            audit = cur.fetchone()

        assert audit is not None
        assert audit["user_id"] == admin_id
        assert audit["target_type"] == "supplier"
        assert audit["detail"]["name"] == "CM Audited Supplier"


def test_preview_overcount_blank_sku_row_not_imported(app, clean_cm):
    """Preview lists a supplier for a blank-sku row (documented overcount);
    the import never creates it because the row itself is skipped."""
    import app.routes.admin.data_import_routes as routes_mod

    preview = DataImportService.preview_import(
        f"{PRODUCTS_CSV_HEADER}\n,Blank Product,1,1,1,Cat,CM Blank Row Supplier",
        "products", fk_caches={"suppliers": {}, "products": {}}, create_missing=True,
    )
    assert preview["will_create_count"] == 1  # overcount heuristic (pinned)

    rows = [
        {"sku": "", "name": "Blank Product", "unit_price": "1", "current_stock": "1",
         "reorder_point": "1", "category": "Cat", "supplier_name": "CM Blank Row Supplier"},
    ]
    with app.app_context():
        count = routes_mod._import_rows("products", rows, create_missing=True)["imported"]
        assert count == 0
        with get_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM suppliers WHERE name = 'CM Blank Row Supplier'"
            )
            assert int(cur.fetchone()["c"]) == 0


# ══════════════════════════════════════════════════════════════════════
# Integration: _import_purchase_orders (real DB)
# ══════════════════════════════════════════════════════════════════════

def test_import_purchase_orders_armed_creates_supplier_and_imports(app, clean_cm):
    import app.routes.admin.data_import_routes as routes_mod

    product_id = _mk_product(app, "CM-PO-PROD")
    rows = [
        {"supplier_name": "CM PO Supplier", "product_sku": "CM-PO-PROD",
         "quantity": "3", "status": "draft", "po_number": "CM-PO-001"},
    ]

    with app.app_context():
        count = routes_mod._import_rows("purchase_orders", rows, create_missing=True)["imported"]
        assert count == 1

        with get_cursor() as cur:
            cur.execute(
                "SELECT id FROM suppliers "
                "WHERE name = 'CM PO Supplier' AND deleted_at IS NULL"
            )
            sup = cur.fetchone()
            assert sup is not None
            cur.execute(
                "SELECT supplier_id, product_id FROM purchase_orders WHERE po_number = 'CM-PO-001'"
            )
            po = cur.fetchone()
            assert po is not None
            assert po["supplier_id"] == sup["id"]
            assert po["product_id"] == product_id


def test_import_purchase_orders_armed_numeric_existing_supplier_id_links_not_creates(app, clean_cm):
    """Legacy numeric supplier id that exists: the armed import links it and
    never creates a supplier literally named after the number."""
    import app.routes.admin.data_import_routes as routes_mod

    product_id = _mk_product(app, "CM-PO-PRODN")
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO suppliers (name, initials, location, lead_days) "
                "VALUES ('CM Numeric Real', 'NR', '', 0) RETURNING id"
            )
            supplier_id = cur.fetchone()["id"]

    rows = [
        {"supplier_name": str(supplier_id), "product_sku": "CM-PO-PRODN",
         "quantity": "3", "status": "draft", "po_number": "CM-PO-007"},
    ]

    with app.app_context():
        count = routes_mod._import_rows("purchase_orders", rows, create_missing=True)["imported"]
        assert count == 1

        with get_cursor() as cur:
            cur.execute(
                "SELECT supplier_id, product_id FROM purchase_orders WHERE po_number = 'CM-PO-007'"
            )
            po = cur.fetchone()
            assert po["supplier_id"] == supplier_id  # linked, not created
            assert po["product_id"] == product_id
            cur.execute(
                "SELECT COUNT(*) AS c FROM suppliers WHERE name = %s", (str(supplier_id),)
            )
            assert int(cur.fetchone()["c"]) == 0  # never created as a name


def test_import_purchase_orders_armed_unknown_product_no_orphan_supplier(app, clean_cm):
    import app.routes.admin.data_import_routes as routes_mod

    rows = [
        {"supplier_name": "CM Orphan Supplier", "product_sku": "CM-NOPE",
         "quantity": "3", "status": "draft", "po_number": "CM-PO-002"},
    ]

    with app.app_context():
        count = routes_mod._import_rows("purchase_orders", rows, create_missing=True)["imported"]
        assert count == 0

        with get_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM suppliers WHERE name = 'CM Orphan Supplier'"
            )
            assert int(cur.fetchone()["c"]) == 0


def test_preview_po_unresolvable_product_overcount_pinned(app, clean_cm):
    """PO overcount heuristic (documented): a row with unknown supplier AND
    unknown product_sku still appears in will_create, while the import skips
    the row before creating anything (0 POs, 0 suppliers)."""
    import app.routes.admin.data_import_routes as routes_mod

    preview = DataImportService.preview_import(
        f"{PO_CSV_HEADER}\nCM PO Ghost Sup,CM-NOPE,3,draft",
        "purchase_orders",
        fk_caches={"suppliers": {}, "products": {}}, create_missing=True,
    )
    assert preview["will_create_count"] >= 1
    assert preview["valid"] is True

    with app.app_context():
        count = routes_mod._import_rows(
            "purchase_orders",
            [{"supplier_name": "CM PO Ghost Sup", "product_sku": "CM-NOPE",
              "quantity": "3", "status": "draft", "po_number": "CM-PO-006"}],
            create_missing=True,
        )["imported"]
        assert count == 0

        with get_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM suppliers WHERE name = 'CM PO Ghost Sup'"
            )
            assert int(cur.fetchone()["c"]) == 0
            cur.execute(
                "SELECT COUNT(*) AS c FROM purchase_orders WHERE po_number = 'CM-PO-006'"
            )
            assert int(cur.fetchone()["c"]) == 0


def test_import_purchase_orders_armed_soft_deleted_name_recreated_and_imported(app, clean_cm):
    """Soft-deleted same-name supplier: preview says 'will create' and the
    import now delivers exactly that — a fresh ACTIVE supplier (name reuse
    after soft-delete, mirrors products_sku_live_key) — and the PO imports."""
    import app.routes.admin.data_import_routes as routes_mod

    _mk_product(app, "CM-PO-PROD2")

    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO suppliers (name, initials, location, lead_days) "
                "VALUES ('CM Revived PO Sup', 'RS', '', 0) RETURNING id"
            )
            old_id = cur.fetchone()["id"]
            cur.execute(
                "UPDATE suppliers SET deleted_at = NOW() WHERE id = %s", (old_id,)
            )
        with get_cursor() as cur:
            caches = DataImportService.build_fk_caches(cur)

    preview = DataImportService.preview_import(
        f"{PO_CSV_HEADER}\nCM Revived PO Sup,CM-PO-PROD2,2,draft",
        "purchase_orders", fk_caches=caches, create_missing=True,
    )
    assert preview["will_create_count"] == 1  # preview cannot see soft-deleted rows
    assert [
        w for w in preview["warnings"] if w["error_code"] == "fk_supplier_not_found"
    ] == []

    rows = [
        {"supplier_name": "CM Revived PO Sup", "product_sku": "CM-PO-PROD2",
         "quantity": "2", "status": "draft", "po_number": "CM-PO-003"},
    ]
    with app.app_context():
        count = routes_mod._import_rows("purchase_orders", rows, create_missing=True)["imported"]
        assert count == 1  # fresh active supplier -> row imports

        with get_cursor() as cur:
            cur.execute(
                "SELECT id FROM suppliers "
                "WHERE name = 'CM Revived PO Sup' AND deleted_at IS NULL"
            )
            new_sup = cur.fetchone()
            assert new_sup is not None
            assert new_sup["id"] != old_id
            cur.execute(
                "SELECT supplier_id FROM purchase_orders WHERE po_number = 'CM-PO-003'"
            )
            assert cur.fetchone()["supplier_id"] == new_sup["id"]
            cur.execute("SELECT deleted_at FROM suppliers WHERE id = %s", (old_id,))
            assert cur.fetchone()["deleted_at"] is not None  # old row untouched


def test_import_purchase_orders_unarmed_unchanged(app, clean_cm):
    import app.routes.admin.data_import_routes as routes_mod

    _mk_product(app, "CM-PO-PROD3")

    # Unknown supplier unarmed -> skip, no supplier created.
    with app.app_context():
        count = routes_mod._import_rows(
            "purchase_orders",
            [{"supplier_name": "CM Unarmed Ghost", "product_sku": "CM-PO-PROD3",
              "quantity": "1", "status": "draft", "po_number": "CM-PO-004"}],
        )["imported"]
        assert count == 0

    # Known supplier unarmed -> imports, supplier untouched.
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO suppliers (name, initials, location, lead_days) "
                "VALUES ('CM Unarmed Real', 'UR', '', 0)"
            )
        count = routes_mod._import_rows(
            "purchase_orders",
            [{"supplier_name": "CM Unarmed Real", "product_sku": "CM-PO-PROD3",
              "quantity": "1", "status": "draft", "po_number": "CM-PO-005"}],
        )["imported"]
        assert count == 1

        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM suppliers WHERE name = 'CM Unarmed Real'")
            assert int(cur.fetchone()["c"]) == 1
            cur.execute(
                "SELECT COUNT(*) AS c FROM suppliers WHERE name = 'CM Unarmed Ghost'"
            )
            assert int(cur.fetchone()["c"]) == 0


# ══════════════════════════════════════════════════════════════════════
# Endpoints (real DB)
# ══════════════════════════════════════════════════════════════════════

def test_preview_endpoint_create_missing_flag(app, clean_cm):
    client = _session_client(app, "admin")
    csv_content = (
        f"{PRODUCTS_CSV_HEADER}\nCM-EP-1,Endpoint Product,1,1,1,Cat,CM Endpoint Supplier"
    )

    armed = client.post(
        "/admin/data-import/preview/products",
        data={"csv_content": csv_content, "create_missing": "true"},
        content_type="application/x-www-form-urlencoded",
    )
    assert armed.status_code == 200
    preview = armed.get_json()["preview"]
    assert preview["valid"] is True
    assert preview["will_create_count"] >= 1
    assert all(e["field"] == "supplier_name" for e in preview["will_create"])

    unarmed = client.post(
        "/admin/data-import/preview/products",
        data={"csv_content": csv_content},
        content_type="application/x-www-form-urlencoded",
    )
    assert unarmed.status_code == 200
    preview2 = unarmed.get_json()["preview"]
    assert preview2["will_create"] == []
    assert preview2["will_create_count"] == 0
    assert preview2["warning_count"] >= 1  # warnings as today


def test_upload_endpoint_create_missing_armed_and_unarmed(app, clean_cm):
    client = _session_client(app, "admin")

    armed_csv = (
        f"{PRODUCTS_CSV_HEADER}\nCM-UP-1,Upload Product,1,1,1,Cat,CM Upload Supplier"
    ).encode()
    resp = client.post(
        "/admin/data-import/upload/products",
        data={
            "csv_file": (io.BytesIO(armed_csv), "cm_armed.csv"),
            "create_missing": "true",
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        with get_cursor() as cur:
            cur.execute(
                "SELECT id FROM suppliers "
                "WHERE name = 'CM Upload Supplier' AND deleted_at IS NULL"
            )
            sup = cur.fetchone()
            assert sup is not None
            cur.execute("SELECT supplier_id FROM products WHERE sku = 'CM-UP-1'")
            assert cur.fetchone()["supplier_id"] == sup["id"]

    unarmed_csv = (
        f"{PRODUCTS_CSV_HEADER}\nCM-UP-2,Upload Product 2,1,1,1,Cat,CM Upload Ghost"
    ).encode()
    resp2 = client.post(
        "/admin/data-import/upload/products",
        data={"csv_file": (io.BytesIO(unarmed_csv), "cm_unarmed.csv")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp2.status_code == 200

    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT supplier_id FROM products WHERE sku = 'CM-UP-2'")
            assert cur.fetchone()["supplier_id"] is None
            cur.execute("SELECT COUNT(*) AS c FROM suppliers WHERE name = 'CM Upload Ghost'")
            assert int(cur.fetchone()["c"]) == 0


def test_movements_entity_armed_creates_nothing(app, clean_cm):
    import app.routes.admin.data_import_routes as routes_mod

    client = _session_client(app, "admin")
    resp = client.post(
        "/admin/data-import/preview/movements",
        data={
            "csv_content": "product_sku,quantity,movement_type,reason\nCM-NOPE,1,IN,r",
            "create_missing": "true",
        },
        content_type="application/x-www-form-urlencoded",
    )
    assert resp.status_code == 200
    preview = resp.get_json()["preview"]
    assert preview["will_create"] == []
    assert preview["will_create_count"] == 0
    assert preview["warning_count"] >= 1  # product miss still warns

    with app.app_context():
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM suppliers")
            before = int(cur.fetchone()["c"])
        count = routes_mod._import_rows(
            "movements",
            [{"product_sku": "CM-NOPE", "quantity": "1", "movement_type": "IN", "reason": "cm"}],
            create_missing=True,
        )["imported"]
        assert count == 0
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM suppliers")
            after = int(cur.fetchone()["c"])
        assert after == before


# ══════════════════════════════════════════════════════════════════════
# Template checks + signature compatibility
# ══════════════════════════════════════════════════════════════════════

def test_template_source_has_gated_create_missing_checkbox():
    from pathlib import Path

    tpl = (
        Path(__file__).resolve().parent.parent
        / "app" / "templates" / "admin" / "data_import" / "index.html"
    )
    src = tpl.read_text(encoding="utf-8")

    assert 'name="create_missing" value="true"' in src      # value must be "true"
    assert "id=\"create_missing_{{ active_tab }}\"" in src
    assert "{% if active_tab in ('products', 'purchase_orders') %}" in src
    assert "cmInput.name = 'create_missing'" in src         # confirm-handler hidden input


def test_template_renders_checkbox_only_on_creatable_tabs(app):
    client = _session_client(app, "admin")

    products_page = client.get("/admin/data-import/?tab=products")
    assert products_page.status_code == 200
    assert b"create_missing_products" in products_page.data
    assert b'name="create_missing" value="true"' in products_page.data

    movements_page = client.get("/admin/data-import/?tab=movements")
    assert movements_page.status_code == 200
    assert b"create_missing_movements" not in movements_page.data


def test_signature_backward_compat(app):
    import app.routes.admin.data_import_routes as routes_mod

    # preview_import(csv_content, entity) — no kwargs (all 14 compat tests call this way)
    result = DataImportService.preview_import(
        f"{PRODUCTS_CSV_HEADER}\nCM-SIG-1,Sig Product,1,1,1,Cat,CM Sig Sup", "products"
    )
    assert result["valid"] is True
    assert "will_create" in result and "will_create_count" in result

    # _import_rows(entity, rows) — 2-arg (movements tests call this way)
    with app.app_context():
        assert routes_mod._import_rows("products", [])["imported"] == 0
        assert routes_mod._import_rows("no_such_entity", [])["imported"] == 0
