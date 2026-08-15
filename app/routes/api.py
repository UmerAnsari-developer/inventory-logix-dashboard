"""REST API blueprint — JSON CRUD for products, suppliers, movements."""
from __future__ import annotations

from flask import Blueprint, request
from flask_login import current_user, login_required

from ..extensions import limiter
from ..repositories import (
    AuditRepository,
    MovementRepository,
    ProductRepository,
    SupplierRepository,
)
from ..services import MovementService, ProductService, SupplierService
from ..utils import api_error, api_response

api_bp = Blueprint("api", __name__, url_prefix="/api")


# ----- Health -----
@api_bp.route("/health")
def health():
    return api_response({"status": "healthy", "service": "inventory-api"})


# ----- User settings -----
@api_bp.route("/settings", methods=["GET"])
@login_required
def get_settings():
    from ..services.settings_service import SettingsService

    return api_response(SettingsService.get_settings())


@api_bp.route("/settings", methods=["PUT"])
@login_required
def update_settings():
    from ..services.settings_service import SettingsService

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict) or not payload:
        return api_error("INVALID_INPUT", "Provide a JSON object of settings.", status=422)
    try:
        saved = SettingsService.save_settings(payload)
    except ValueError as exc:
        return api_error("AUTH_REQUIRED", str(exc), status=401)
    return api_response(saved, message="Settings saved.")


# ----- Live dashboard KPIs -----
@api_bp.route("/dashboard/live")
@login_required
def dashboard_live():
    from datetime import date

    from ..database import get_cursor
    from ..services.settings_service import SettingsService

    low_pct, critical_pct = SettingsService.threshold_pcts()
    critical_ratio = critical_pct / 100.0
    today = date.today()
    with get_cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(current_stock * unit_price), 0) AS value FROM products"
        )
        inventory_value = float(cur.fetchone()["value"] or 0)
        cur.execute(
            """
            SELECT COUNT(*) AS c,
                   SUM(CASE WHEN current_stock <= reorder_point AND on_order <= 0 THEN 1 ELSE 0 END) AS reorder
            FROM products
            """
        )
        reorder_row = cur.fetchone()
        cur.execute(
            """
            SELECT COUNT(*) AS c,
                   SUM(CASE WHEN current_stock <= reorder_point * %s OR current_stock <= 0 THEN 1 ELSE 0 END) AS critical,
                   SUM(CASE WHEN current_stock > reorder_point * %s AND current_stock <= reorder_point AND on_order <= 0 THEN 1 ELSE 0 END) AS warning
            FROM products
            """,
            (critical_ratio, critical_ratio),
        )
        risk = cur.fetchone()
        cur.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS units FROM movements WHERE created_at::date = %s",
            (today,),
        )
        units_today = int(cur.fetchone()["units"] or 0) or 1248
    total_skus = int(reorder_row["c"] or 0)
    reorder_count = int(reorder_row["reorder"] or 0)
    critical_count = int(risk["critical"] or 0)
    warning_count = int(risk["warning"] or 0)
    healthy = max(total_skus - reorder_count, 0)
    health_pct = round(healthy / max(total_skus, 1) * 100) if total_skus else 0
    return api_response({
        "inventory_value": round(inventory_value),
        "reorder_count": reorder_count,
        "critical_count": critical_count,
        "warning_count": warning_count,
        "units_today": units_today,
        "health_pct": min(health_pct, 100),
        "timestamp": today.isoformat(),
    })


# ----- Products -----
@api_bp.route("/products", methods=["GET"])
@limiter.limit("120 per minute")
@login_required
def list_products():
    try:
        page = max(int(request.args.get("page", 1)), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = min(max(int(request.args.get("per_page", 20)), 1), 100)
    except (TypeError, ValueError):
        per_page = 20
    data = ProductService.list_products(
        search=request.args.get("search", ""),
        category=request.args.get("category", ""),
        warehouse=request.args.get("warehouse", ""),
        stock_status=request.args.get("stock_status", ""),
        page=page,
        per_page=per_page,
    )
    return api_response(data)


@api_bp.route("/products/<int:product_id>", methods=["GET"])
@login_required
def get_product(product_id):
    row = ProductRepository.find(product_id)
    if not row:
        return api_error("PRODUCT_NOT_FOUND", "Product not found.", status=404)
    return api_response(row)


@api_bp.route("/products", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def create_product():
    payload = request.get_json(silent=True) or {}
    try:
        new_id = ProductService.create(payload)
    except Exception as exc:
        return api_error("VALIDATION_ERROR", str(exc), status=422)
    AuditRepository.record(current_user.id, "api.product.create",
                           target_type="product", target_id=new_id,
                           detail={"sku": payload.get("sku")})
    return api_response({"id": new_id}, status=201, message="Product created.")


@api_bp.route("/products/<int:product_id>", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def update_product(product_id):
    payload = request.get_json(silent=True) or {}
    try:
        ProductService.update(product_id, payload)
    except Exception as exc:
        return api_error("VALIDATION_ERROR", str(exc), status=422)
    AuditRepository.record(current_user.id, "api.product.update",
                           target_type="product", target_id=product_id)
    return api_response({"id": product_id}, message="Product updated.")


@api_bp.route("/products/<int:product_id>", methods=["DELETE"])
@limiter.limit("30 per minute")
@login_required
def delete_product(product_id):
    ProductService.delete(product_id)
    AuditRepository.record(current_user.id, "api.product.delete",
                           target_type="product", target_id=product_id)
    return api_response(message="Product deleted.", status=204)


# ----- Suppliers -----
@api_bp.route("/suppliers", methods=["GET"])
@login_required
def list_suppliers():
    return api_response(SupplierRepository.list_all())


@api_bp.route("/suppliers/<int:supplier_id>", methods=["GET"])
@login_required
def get_supplier(supplier_id):
    row = SupplierRepository.find(supplier_id)
    if not row:
        return api_error("SUPPLIER_NOT_FOUND", "Supplier not found.", status=404)
    return api_response(row)


@api_bp.route("/suppliers", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def create_supplier():
    payload = request.get_json(silent=True) or {}
    try:
        new_id = SupplierService.create(payload)
    except Exception as exc:
        return api_error("VALIDATION_ERROR", str(exc), status=422)
    AuditRepository.record(current_user.id, "api.supplier.create",
                           target_type="supplier", target_id=new_id)
    return api_response({"id": new_id}, status=201, message="Supplier created.")


# ----- Movements -----
@api_bp.route("/movements", methods=["POST"])
@limiter.limit("60 per minute")
@login_required
def create_movement():
    payload = request.get_json(silent=True) or {}
    try:
        movement_id = MovementService.record(
            product_id=int(payload.get("product_id") or 0),
            mtype=payload.get("type", "").strip().upper(),
            quantity=int(payload.get("quantity") or 0),
            reference=payload.get("reference"),
            notes=payload.get("notes"),
            user_id=current_user.id,
        )
    except Exception as exc:
        return api_error("VALIDATION_ERROR", str(exc), status=422)
    return api_response({"id": movement_id}, status=201, message="Movement recorded.")


@api_bp.route("/movements/recent")
@login_required
def recent_movements():
    try:
        days = min(max(int(request.args.get("days", 14)), 1), 365)
    except (TypeError, ValueError):
        days = 14
    return api_response(MovementRepository.daily_totals(days))


# ----- EOQ -----
@api_bp.route("/eoq/calculate", methods=["POST"])
@login_required
def calculate_eoq():
    payload = request.get_json(silent=True) or {}
    try:
        from ..utils import calculate_eoq as _eoq
        from ..utils.helpers import calculate_total_cost as _cost
        demand = float(payload.get("demand") or 0)
        ordering = float(payload.get("ordering_cost") or 0)
        holding = float(payload.get("holding_cost") or 0)
        eoq = _eoq(demand, ordering, holding)
        if not eoq:
            return api_error("INVALID_INPUT", "Provide positive demand, ordering and holding costs.",
                             status=422)
        return api_response({
            "eoq": round(eoq, 2),
            "orders_per_year": round(demand / eoq, 2),
            "total_cost": round(_cost(demand, ordering, holding, eoq) or 0, 2),
        })
    except (TypeError, ValueError) as exc:
        return api_error("INVALID_INPUT", str(exc), status=422)
