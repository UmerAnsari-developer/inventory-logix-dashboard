"""OpenAPI 3.0 spec for the InventoryLogix API (GAP-013).

Hand-written, data-driven spec served at GET /api/openapi.json. Flask-RESTX
was rejected (would force refactoring every view). Parity with the live
url_map is enforced by tests/test_openapi_contract.py — every (method, path)
below must exist in the app and vice versa.
"""
from __future__ import annotations

from flask import Blueprint, jsonify

openapi_bp = Blueprint("openapi", __name__)

_API_RESPONSE = {
    "type": "object",
    "description": "Repo-wide JSON envelope: {success, data, error}.",
    "properties": {
        "success": {"type": "boolean"},
        "data": {"description": "Response payload (shape varies per endpoint)."},
        "error": {"type": "string", "nullable": True},
    },
    "required": ["success"],
}

# (path, {method: summary}) — the complete /api + /ai surface. Keep in sync
# with app/routes/api.py and app/routes/ai.py; the contract test fails on drift.
_PATHS: list[tuple[str, dict[str, str]]] = [
    # ── /api — REST CRUD, health, settings, notifications ──
    ("/api/health", {"get": "Liveness + database connectivity"}),
    ("/api/settings", {"get": "Get user settings", "put": "Update user settings"}),
    ("/api/dashboard/live", {"get": "Live dashboard KPIs"}),
    ("/api/products", {"get": "List products (paginated)", "post": "Create product"}),
    ("/api/products/{product_id}", {
        "get": "Get product by id",
        "put": "Update product",
        "delete": "Delete product (soft delete)",
    }),
    ("/api/suppliers", {"get": "List suppliers", "post": "Create supplier"}),
    ("/api/suppliers/{supplier_id}", {"get": "Get supplier by id"}),
    ("/api/purchase-orders", {"post": "Create purchase order"}),
    ("/api/movements", {"get": "List movements (paginated)", "post": "Record stock movement"}),
    ("/api/movements/export", {"get": "Export movements as CSV"}),
    ("/api/products/{product_id}/movements", {"get": "List movements for a product"}),
    ("/api/products/{product_id}/movements/export", {"get": "Export product movements as CSV"}),
    ("/api/movements/recent", {"get": "Recent movement daily totals"}),
    ("/api/export/products", {"get": "Export products as CSV"}),
    ("/api/export/purchase_orders", {"get": "Export purchase orders as CSV"}),
    ("/api/export/suppliers", {"get": "Export suppliers as CSV"}),
    ("/api/export/inventory", {"get": "Export inventory as CSV"}),
    ("/api/eoq/calculate", {"post": "Calculate economic order quantity"}),
    ("/api/notifications", {"get": "List notifications for current user"}),
    ("/api/notifications/{notif_id}/read", {"post": "Mark one notification read"}),
    ("/api/notifications/read-all", {"post": "Mark all notifications read"}),
    ("/api/openapi.json", {"get": "This OpenAPI 3.0 specification"}),
    # ── /ai — EOQ ──
    ("/ai/eoq/sensitivity", {"get": "EOQ sensitivity surface"}),
]


def _build_spec() -> dict:
    paths: dict = {}
    for path, methods in _PATHS:
        tag = "api" if path.startswith("/api") else "ai"
        paths[path] = {
            method: {
                "summary": summary,
                "tags": [tag],
                "security": [{"sessionCookie": []}],
                "responses": {
                    "200": {
                        "description": "Success (or documented error envelope for 4xx/5xx outcomes)",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ApiResponse"}
                            }
                        },
                    }
                },
            }
            for method, summary in methods.items()
        }
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "InventoryLogix API",
            "version": "1.0.0",
            "description": (
                "InventoryLogix REST + AI endpoints. Versioning policy: v1 is current; "
                "breaking changes ship under /api/v2; /api and /ai remain as unversioned "
                "aliases. All JSON responses use the shared ApiResponse envelope "
                "{success, data, error}. Authentication is the Flask-Login session "
                "cookie; role enforcement (viewer/manager/admin) stays in the route "
                "decorators and is not part of this contract."
            ),
        },
        "paths": paths,
        "components": {
            "schemas": {"ApiResponse": _API_RESPONSE},
            "securitySchemes": {
                "sessionCookie": {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": "session",
                    "description": "Flask-Login session cookie (declared only; enforcement stays in decorators).",
                }
            },
        },
    }


@openapi_bp.route("/api/openapi.json")
def openapi_json():
    return jsonify(_build_spec())
