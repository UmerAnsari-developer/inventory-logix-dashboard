"""REST API blueprint — JSON CRUD for products, suppliers, movements."""
from __future__ import annotations

from datetime import datetime
from flask import Blueprint, request, Response, stream_with_context, current_app
from flask_login import current_user, login_required

from ..extensions import limiter
from ..repositories import (
    MovementRepository,
    POError,
    ProductRepository,
    PurchaseOrderRepository,
    SupplierRepository,
)
from ..security import write_roles_required
from ..services import MovementService, ProductService, ProductError, SupplierService, POService, POServiceError
from ..services.movement_service import MovementError
from ..utils import api_error, api_response
from ..utils.cache import (
    api_cache,
    cache_bust_movements,
    cache_bust_products,
    cache_bust_purchase_orders,
    cache_bust_settings,
    cache_bust_suppliers,
    make_key,
)
from ..utils.idempotency import idempotent

api_bp = Blueprint("api", __name__, url_prefix="/api")


# ----- Health -----
@api_bp.route("/health")
def health():
    from ..database import get_cursor
    import psycopg2

    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return api_response({"status": "healthy", "service": "inventory-api", "database": "connected"})
    except Exception as e:
        # L1: generic message — psycopg2 errors can embed host/port/dbname;
        # log the detail server-side, never expose it to unauthenticated callers.
        LOGGER.warning("Health check failed: %s", e)
        return api_error("HEALTH_CHECK_FAILED", "Database connection failed.", status=503)


# ----- User settings -----
@api_bp.route("/settings", methods=["GET"])
@login_required
def get_settings():
    from ..services.settings_service import SettingsService

    return api_response(SettingsService.get_settings())


@api_bp.route("/settings", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
@write_roles_required
def update_settings():
    from ..services.settings_service import SettingsService

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict) or not payload:
        return api_error("INVALID_INPUT", "Provide a JSON object of settings.", status=422)
    try:
        saved = SettingsService.save_settings(payload)
    except ValueError as exc:
        return api_error("AUTH_REQUIRED", str(exc), status=401)
    cache_bust_settings()
    return api_response(saved, message="Settings saved.")


# ----- Live dashboard KPIs -----
@api_bp.route("/dashboard/live")
@login_required
def dashboard_live():
    from datetime import date

    from ..database import get_cursor
    from ..services.settings_service import SettingsService

    def _load():
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
                       SUM(CASE WHEN current_stock <= reorder_point * %s AND on_order <= 0 THEN 1 ELSE 0 END) AS critical,
                       SUM(CASE WHEN current_stock > reorder_point * %s AND current_stock <= reorder_point AND on_order <= 0 THEN 1 ELSE 0 END) AS warning
                FROM products
                """,
                (critical_ratio, critical_ratio),
            )
            risk = cur.fetchone()
            cur.execute(
                "SELECT COALESCE(SUM(quantity), 0) AS units FROM movements "
                "WHERE created_at::date = %s AND deleted_at IS NULL",
                (today,),
            )
            units_today = int(cur.fetchone()["units"] or 0)
        total_skus = int(reorder_row["c"] or 0)
        reorder_count = int(reorder_row["reorder"] or 0)
        critical_count = int(risk["critical"] or 0)
        warning_count = int(risk["warning"] or 0)
        healthy = max(total_skus - reorder_count, 0)
        health_pct = round(healthy / max(total_skus, 1) * 100) if total_skus else 0
        return {
            "inventory_value": round(inventory_value),
            "reorder_count": reorder_count,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "units_today": units_today,
            "health_pct": min(health_pct, 100),
            "timestamp": today.isoformat(),
        }

    return api_response(api_cache.get_or_set("dashboard:live", _load))


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
    params = {
        "search": request.args.get("search", ""),
        "category": request.args.get("category", ""),
        "warehouse": request.args.get("warehouse", ""),
        "stock_status": request.args.get("stock_status", ""),
        "page": page,
        "per_page": per_page,
    }
    cache_key = make_key(prefix="products", **params)

    def _load():
        return ProductService.list_products(**params)

    return api_response(api_cache.get_or_set(cache_key, _load))


@api_bp.route("/products/<int:product_id>", methods=["GET"])
@login_required
def get_product(product_id):
    row = api_cache.get_or_set(
        f"product:{product_id}",
        lambda: ProductRepository.find(product_id),
    )
    if not row:
        return api_error("PRODUCT_NOT_FOUND", "Product not found.", status=404)
    return api_response(row)


@api_bp.route("/products", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
@write_roles_required
@idempotent()
def create_product():
    payload = request.get_json(silent=True) or {}
    try:
        new_id = ProductService.create(payload)
    except ProductError as exc:
        # Check if it's a duplicate SKU error
        if "already exists" in str(exc).lower():
            return api_error("DUPLICATE_SKU", str(exc), status=409)
        return api_error("VALIDATION_ERROR", str(exc), status=422)
    except Exception as exc:
        return api_error("VALIDATION_ERROR", str(exc), status=422)
    cache_bust_products()
    return api_response({"id": new_id}, status=201, message="Product created.")


@api_bp.route("/products/<int:product_id>", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
@write_roles_required
@idempotent()
def update_product(product_id):
    payload = request.get_json(silent=True) or {}
    # Check if product exists
    product = ProductRepository.find(product_id)
    if not product:
        return api_error("PRODUCT_NOT_FOUND", "Product not found.", status=404)
    try:
        ProductService.update(product_id, payload)
    except Exception as exc:
        return api_error("VALIDATION_ERROR", str(exc), status=422)
    cache_bust_products()
    return api_response({"id": product_id}, message="Product updated.")


@api_bp.route("/products/<int:product_id>", methods=["DELETE"])
@limiter.limit("30 per minute")
@login_required
@write_roles_required
@idempotent()
def delete_product(product_id):
    # Check if product exists
    product = ProductRepository.find(product_id)
    if not product:
        return api_error("PRODUCT_NOT_FOUND", "Product not found.", status=404)
    ProductService.delete(product_id)
    cache_bust_products()
    return api_response(message="Product deleted.", status=204)


# ----- Suppliers -----
@api_bp.route("/suppliers", methods=["GET"])
@login_required
def list_suppliers():
    return api_response(api_cache.get_or_set("suppliers:all", SupplierRepository.list_all))


@api_bp.route("/suppliers/<int:supplier_id>", methods=["GET"])
@login_required
def get_supplier(supplier_id):
    row = api_cache.get_or_set(
        f"supplier:{supplier_id}",
        lambda: SupplierRepository.find(supplier_id),
    )
    if not row:
        return api_error("SUPPLIER_NOT_FOUND", "Supplier not found.", status=404)
    return api_response(row)


@api_bp.route("/suppliers", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
@write_roles_required
@idempotent()
def create_supplier():
    payload = request.get_json(silent=True) or {}
    try:
        new_id = SupplierService.create(payload)
    except Exception as exc:
        return api_error("VALIDATION_ERROR", str(exc), status=422)
    cache_bust_suppliers()
    return api_response({"id": new_id}, status=201, message="Supplier created.")


# ----- Purchase Orders -----
@api_bp.route("/purchase-orders", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
@write_roles_required
@idempotent()
def create_purchase_order():
    payload = request.get_json(silent=True) or {}
    try:
        new_id = POService.create(payload)
    except (POServiceError, POError) as exc:
        # Check if it's a duplicate PO number
        msg = str(exc)
        if "already exists" in msg.lower():
            return api_error("DUPLICATE_PO_NUMBER", msg, status=409)
        return api_error("VALIDATION_ERROR", msg, status=422)
    except Exception as exc:
        return api_error("VALIDATION_ERROR", str(exc), status=422)
    cache_bust_purchase_orders()
    return api_response({"id": new_id}, status=201, message="Purchase order created.")


# ----- Movements -----
@api_bp.route("/movements", methods=["POST"])
@limiter.limit("60 per minute")
@login_required
@write_roles_required
@idempotent()
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
    cache_bust_movements()
    return api_response({"id": movement_id}, status=201, message="Movement recorded.")


@api_bp.route("/movements", methods=["GET"])
@login_required
@limiter.limit("60 per minute")
def list_movements():
    """List movements with filters, pagination, and sorting."""
    try:
        # Parse query parameters
        type_filter = request.args.getlist("type")
        if type_filter and len(type_filter) == 1 and "," in type_filter[0]:
            type_filter = type_filter[0].split(",")

        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")
        int_args = {}
        for name in ("product_id", "user_id", "page", "per_page"):
            raw = request.args.get(name)
            value = request.args.get(name, type=int)
            if raw is not None and value is None:
                return api_error("VALIDATION_ERROR", f"{name} must be an integer", status=400)
            int_args[name] = value
        product_id = int_args["product_id"]
        user_id = int_args["user_id"]
        page = 1 if int_args["page"] is None else int_args["page"]
        per_page = 20 if int_args["per_page"] is None else min(int_args["per_page"], 100)
        sort_by = request.args.get("sort_by", default="created_at", type=str)
        sort_order = request.args.get("sort_order", default="desc", type=str)

        result = MovementService.list_movements(
            type_filter=type_filter if type_filter else None,
            date_from=date_from,
            date_to=date_to,
            product_id=product_id,
            user_id=user_id,
            page=page,
            per_page=per_page,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        # Get total count for pagination
        total_count = MovementService.get_movement_count(
            type_filter=type_filter if type_filter else None,
            date_from=date_from,
            date_to=date_to,
            product_id=product_id,
            user_id=user_id,
        )

        return api_response(
            result,
            total_count=total_count,
            page=page,
            per_page=per_page,
        )
    except MovementError as exc:
        return api_error("VALIDATION_ERROR", str(exc), status=400)
    except Exception as exc:
        current_app.logger.error(f"List movements error: {exc}", exc_info=True)
        return api_error("INTERNAL_ERROR", "Failed to list movements", status=500)


@api_bp.route("/products/<int:product_id>/movements", methods=["GET"])
@login_required
@limiter.limit("60 per minute")
def list_product_movements(product_id: int):
    """List movements for a specific product."""
    try:
        type_filter = request.args.getlist("type")
        if type_filter and len(type_filter) == 1 and "," in type_filter[0]:
            type_filter = type_filter[0].split(",")

        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")
        int_args = {}
        for name in ("user_id", "page", "per_page"):
            raw = request.args.get(name)
            value = request.args.get(name, type=int)
            if raw is not None and value is None:
                return api_error("VALIDATION_ERROR", f"{name} must be an integer", status=400)
            int_args[name] = value
        user_id = int_args["user_id"]
        page = 1 if int_args["page"] is None else int_args["page"]
        per_page = 20 if int_args["per_page"] is None else min(int_args["per_page"], 100)
        sort_by = request.args.get("sort_by", default="created_at", type=str)
        sort_order = request.args.get("sort_order", default="desc", type=str)

        result = MovementService.get_product_movements(
            product_id=product_id,
            type_filter=type_filter if type_filter else None,
            date_from=date_from,
            date_to=date_to,
            user_id=user_id,
            page=page,
            per_page=per_page,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        return api_response(result)
    except MovementError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        return api_error("NOT_FOUND" if status == 404 else "VALIDATION_ERROR", str(exc), status=status)
    except Exception as exc:
        current_app.logger.error(f"List product movements error: {exc}", exc_info=True)
        return api_error("INTERNAL_ERROR", "Failed to list product movements", status=500)


@api_bp.route("/movements/export", methods=["GET"])
@login_required
@limiter.limit("30 per minute")
def export_movements():
    """Export movements as CSV stream."""
    try:
        type_filter = request.args.getlist("type")
        if type_filter and len(type_filter) == 1 and "," in type_filter[0]:
            type_filter = type_filter[0].split(",")

        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")
        int_args = {}
        for name in ("product_id", "user_id", "limit"):
            raw = request.args.get(name)
            value = request.args.get(name, type=int)
            if raw is not None and value is None:
                return api_error("VALIDATION_ERROR", f"{name} must be an integer", status=400)
            int_args[name] = value
        product_id = int_args["product_id"]
        user_id = int_args["user_id"]
        limit = 5000 if int_args["limit"] is None else int_args["limit"]
        if limit < 1:
            return api_error("VALIDATION_ERROR", "limit must be >= 1", status=400)
        limit = min(limit, 5000)
        sort_by = request.args.get("sort_by", default="created_at", type=str)
        sort_order = request.args.get("sort_order", default="desc", type=str)

        from flask import Response, stream_with_context
        import io
        import csv

        def generate():
            # Stream CSV using MovementService.export_movements
            try:
                for chunk in MovementService.export_movements(
                    type_filter=type_filter if type_filter else None,
                    date_from=date_from,
                    date_to=date_to,
                    product_id=product_id,
                    user_id=user_id,
                    sort_by=sort_by,
                    sort_order=sort_order,
                    limit=limit,
                ):
                    yield chunk
            except MovementError as exc:
                yield f"Error: {exc}\n"

        resp = Response(stream_with_context(generate()), mimetype="text/csv")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        resp.headers["Content-Disposition"] = f"attachment; filename=movements_{timestamp}.csv"
        return resp
    except MovementError as exc:
        return api_error("VALIDATION_ERROR", str(exc), status=400)
    except Exception as exc:
        current_app.logger.error(f"Export movements error: {exc}", exc_info=True)
        return api_error("INTERNAL_ERROR", "Failed to export movements", status=500)


@api_bp.route("/products/<int:product_id>/movements/export", methods=["GET"])
@login_required
@limiter.limit("30 per minute")
def export_product_movements(product_id: int):
    """Export movements for a specific product as CSV."""
    try:
        sort_by = request.args.get("sort_by", default="created_at", type=str)
        sort_order = request.args.get("sort_order", default="desc", type=str)
        raw_limit = request.args.get("limit")
        limit = request.args.get("limit", default=5000, type=int)
        if raw_limit is not None and limit is None:
            return api_error("VALIDATION_ERROR", "limit must be an integer", status=400)
        limit = 5000 if limit is None else limit
        if limit < 1:
            return api_error("VALIDATION_ERROR", "limit must be >= 1", status=400)
        limit = min(limit, 5000)

        from flask import Response, stream_with_context

        def generate():
            try:
                for chunk in MovementService.export_movements(
                    product_id=product_id,
                    sort_by=sort_by,
                    sort_order=sort_order,
                    limit=limit,
                ):
                    yield chunk
            except MovementError as exc:
                yield f"Error: {exc}\n"

        resp = Response(stream_with_context(generate()), mimetype="text/csv")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        resp.headers["Content-Disposition"] = f"attachment; filename=product_{product_id}_movements_{timestamp}.csv"
        return resp
    except MovementError as exc:
        return api_error("VALIDATION_ERROR", str(exc), status=400)
    except Exception as exc:
        current_app.logger.error(f"Export product movements error: {exc}", exc_info=True)
        return api_error("INTERNAL_ERROR", "Failed to export product movements", status=500)


@api_bp.route("/movements/recent")
@login_required
def recent_movements():
    try:
        days = min(max(int(request.args.get("days", 14)), 1), 365)
    except (TypeError, ValueError):
        days = 14
    return api_response(
        api_cache.get_or_set(f"movements:recent:{days}",
                             lambda: MovementRepository.daily_totals(days))
    )


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


# ----- Notifications -----


@api_bp.route("/notifications/<int:notif_id>/read", methods=["POST"])
@limiter.limit("60 per minute")
@login_required
def mark_notification_read(notif_id: int):
    from ..repositories import NotificationRepository
    NotificationRepository.mark_read(notif_id, current_user.id)
    return api_response({"ok": True})


@api_bp.route("/notifications/read-all", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def mark_all_notifications_read():
    from ..repositories import NotificationRepository
    NotificationRepository.mark_all_read(current_user.id)
    return api_response({"ok": True})


@api_bp.route("/notifications", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def list_notifications():
    from ..repositories import NotificationRepository
    notifs = NotificationRepository.list_for_user(current_user.id, limit=50)
    return api_response({"notifications": notifs, "unread": NotificationRepository.count_unread(current_user.id)})


# ----- Exports -----

@api_bp.route("/export/products", methods=["GET"])
@login_required
@write_roles_required
def export_products():
    from ..services.export_service import ExportService
    return ExportService.export_products_csv()

@api_bp.route("/export/purchase_orders", methods=["GET"])
@login_required
@write_roles_required
def export_purchase_orders():
    from ..services.export_service import ExportService
    return ExportService.export_purchase_orders_csv()

@api_bp.route("/export/suppliers", methods=["GET"])
@login_required
@write_roles_required
def export_suppliers():
    from ..services.export_service import ExportService
    return ExportService.export_suppliers_csv()

@api_bp.route("/export/inventory", methods=["GET"])
@login_required
@write_roles_required
def export_inventory():
    from ..services.export_service import ExportService
    return ExportService.export_inventory_csv()