"""TDD tests for Batch 3 data import preview/confirm (R-001).

Tests cover:
- R-001: Preview endpoint exists and returns parsed CSV preview
- R-001: Template has two-step UI: upload → preview → confirm → commit
- R-001: Service has preview_import(csv_content) method
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from flask_login.utils import _create_identifier

from app.repositories import UserRepository

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"


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
# Service layer tests
# ══════════════════════════════════════════════════════════════════════

def test_data_import_service_has_preview_method():
    """DataImportService must have preview_import(csv_content) method."""
    from app.services.data_import_service import DataImportService
    
    # RED: method must exist
    assert hasattr(DataImportService, "preview_import"), \
        "DataImportService.preview_import method missing"
    
    # Method should be callable
    assert callable(getattr(DataImportService, "preview_import")), \
        "preview_import must be callable"


def test_preview_import_returns_structured_data():
    """preview_import must return structured preview data."""
    from app.services.data_import_service import DataImportService
    
    # Sample CSV content
    csv_content = """sku,name,unit_price,current_stock,reorder_point,category,supplier_id
TEST-001,Test Product,29.99,100,10,Electronics,1
TEST-002,Another Product,49.99,50,5,Accessories,2"""
    
    result = DataImportService.preview_import(csv_content, "products")
    
    # Must return dict with expected keys
    assert isinstance(result, dict), "preview_import must return dict"
    assert "headers" in result, "preview must include headers"
    assert "rows" in result, "preview must include rows"
    assert "row_count" in result, "preview must include row_count"
    assert "valid" in result, "preview must include validation status"
    assert "errors" in result, "preview must include errors list"
    
    # Check structure
    assert result["headers"] == ["sku", "name", "unit_price", "current_stock", "reorder_point", "category", "supplier_id"]
    assert result["row_count"] == 2
    assert len(result["rows"]) == 2
    assert result["valid"] is True
    assert result["errors"] == []


def test_preview_import_detects_missing_columns():
    """preview_import must detect missing required columns."""
    from app.services.data_import_service import DataImportService
    
    # CSV missing required columns
    csv_content = """sku,name
TEST-001,Test Product"""
    
    result = DataImportService.preview_import(csv_content, "products")
    
    assert result["valid"] is False
    assert len(result["errors"]) > 0
    assert any("missing" in e.lower() or "column" in e.lower() for e in result["errors"])


def test_preview_import_handles_empty_csv():
    """preview_import must handle empty CSV gracefully."""
    from app.services.data_import_service import DataImportService
    
    result = DataImportService.preview_import("", "products")
    
    assert result["valid"] is False
    assert result["row_count"] == 0
    assert len(result["errors"]) > 0


def test_preview_import_handles_malformed_csv():
    """preview_import must handle malformed CSV gracefully."""
    from app.services.data_import_service import DataImportService
    
    # Malformed CSV (unclosed quote)
    csv_content = 'sku,name\n"TEST-001,Test Product'
    
    result = DataImportService.preview_import(csv_content, "products")
    
    assert result["valid"] is False
    assert len(result["errors"]) > 0


# ══════════════════════════════════════════════════════════════════════
# Route tests
# ══════════════════════════════════════════════════════════════════════

def test_data_import_preview_endpoint_exists(app):
    """POST /admin/data-import/preview/<entity> must exist."""
    client = _session_client(app, "admin")
    
    csv_content = """sku,name,unit_price,current_stock,reorder_point,category,supplier_id
TEST-001,Test Product,29.99,100,10,Electronics,1"""
    
    resp = client.post(
        "/admin/data-import/preview/products",
        data={"csv_content": csv_content},
        content_type="application/x-www-form-urlencoded"
    )
    
    # Should not be 404
    assert resp.status_code != 404, "preview endpoint not found (404)"
    # Should return JSON
    assert resp.is_json, "preview endpoint must return JSON"
    
    data = resp.get_json()
    assert data["success"] is True
    assert "preview" in data
    assert data["preview"]["row_count"] == 1


def test_data_import_preview_endpoint_validates_entity(app):
    """Preview endpoint must validate entity type."""
    client = _session_client(app, "admin")
    
    resp = client.post(
        "/admin/data-import/preview/invalid_entity",
        data={"csv_content": "sku,name\nTEST,Test"},
        content_type="application/x-www-form-urlencoded"
    )
    
    assert resp.status_code == 400 or resp.status_code == 404
    if resp.is_json:
        data = resp.get_json()
        assert data["success"] is False


def test_data_import_preview_requires_auth(app):
    """Preview endpoint must require authentication."""
    client = app.test_client()
    
    resp = client.post(
        "/admin/data-import/preview/products",
        data={"csv_content": "sku,name\nTEST,Test"},
        content_type="application/x-www-form-urlencoded"
    )
    
    # Should redirect to login or return 401/403
    assert resp.status_code in (302, 401, 403)


def test_data_import_preview_requires_write_role(app):
    """Preview endpoint must require write role (admin/manager)."""
    client = _session_client(app, "viewer")
    
    resp = client.post(
        "/admin/data-import/preview/products",
        data={"csv_content": "sku,name\nTEST,Test"},
        content_type="application/x-www-form-urlencoded"
    )
    
    assert resp.status_code in (302, 403)


# ══════════════════════════════════════════════════════════════════════
# Template tests
# ══════════════════════════════════════════════════════════════════════

def test_data_import_template_has_two_step_ui():
    """Data import template must have two-step UI: upload → preview → confirm."""
    tpl = (TEMPLATES / "admin" / "data_import" / "index.html").read_text(encoding="utf-8")
    
    # Must have preview step (hidden initially, shown after file selection)
    assert "preview" in tpl.lower(), "preview step missing from template"
    
    # Must have confirm step
    assert "confirm" in tpl.lower(), "confirm step missing from template"
    
    # Must have commit/import button (separate from preview)
    assert "commit" in tpl.lower() or "import" in tpl.lower(), "commit/import button missing"
    
    # Must have JavaScript for two-step flow
    assert "preview" in tpl.lower() and "javascript" in tpl.lower() or "script" in tpl.lower()


def test_data_import_template_has_preview_section():
    """Template must have a preview section to display parsed CSV."""
    tpl = (TEMPLATES / "admin" / "data_import" / "index.html").read_text(encoding="utf-8")
    
    # Should have a preview table or grid
    assert "preview" in tpl.lower()
    # Should have headers/rows display
    assert "header" in tpl.lower() or "row" in tpl.lower()


def test_data_import_template_preserves_csv_for_confirm():
    """Template must preserve CSV content for confirm step."""
    tpl = (TEMPLATES / "admin" / "data_import" / "index.html").read_text(encoding="utf-8")
    
    # Should have hidden input or JS variable to store CSV for confirm
    assert "csv_content" in tpl.lower() or "csv-data" in tpl.lower() or "data-csv" in tpl.lower()


# ══════════════════════════════════════════════════════════════════════
# Integration test: full flow
# ══════════════════════════════════════════════════════════════════════

def test_data_import_full_preview_confirm_flow(app):
    """Full flow: upload → preview → confirm → commit."""
    client = _session_client(app, "admin")
    
    csv_content = """sku,name,unit_price,current_stock,reorder_point,category,supplier_id
FLOW-001,Flow Test Product,19.99,200,20,Test Category,1"""
    
    # Step 1: Preview
    preview_resp = client.post(
        "/admin/data-import/preview/products",
        data={"csv_content": csv_content},
        content_type="application/x-www-form-urlencoded"
    )
    assert preview_resp.status_code == 200
    preview_data = preview_resp.get_json()
    assert preview_data["success"] is True
    assert preview_data["preview"]["row_count"] == 1
    
    # Step 2: Confirm/Commit (using the existing upload endpoint with preview data)
    # The upload endpoint should accept a preview confirmation
    commit_resp = client.post(
        "/admin/data-import/upload/products",
        data={
            "csv_file": (io.BytesIO(csv_content.encode()), "test.csv"),
            "confirm": "true"  # Indicates user confirmed preview
        },
        content_type="multipart/form-data"
    )
    # Should succeed (or at least not 404)
    assert commit_resp.status_code != 404


# ══════════════════════════════════════════════════════════════════════
# Entity-specific preview tests
# ══════════════════════════════════════════════════════════════════════

def test_preview_import_all_entities():
    """preview_import must work for all entity types."""
    from app.services.data_import_service import DataImportService
    
    entities = {
        "products": "sku,name,unit_price,current_stock,reorder_point,category,supplier_id\nTEST,Test,10,100,10,Cat,1",
        "suppliers": "supplier_name,location,lead_days\nTest Supplier,Test Location,5",
        "warehouses": "warehouse_name,location\nTest Warehouse,Test Location",
        "movements": "product_id,quantity,movement_type,reason\n1,10,IN,Test",
        "purchase_orders": "supplier_id,product_id,quantity,status\n1,1,10,draft",
    }
    
    for entity, csv_content in entities.items():
        result = DataImportService.preview_import(csv_content, entity)
        assert result["valid"] is True, f"preview failed for {entity}: {result['errors']}"
        assert result["row_count"] == 1, f"wrong row count for {entity}"