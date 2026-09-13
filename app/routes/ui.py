"""Main UI routes — dashboard, inventory, suppliers, reports, EOQ.

Preserves the original dashboard design while exposing the AI capabilities
(forecast, anomaly, dark mode).
"""
from __future__ import annotations

import csv
import io
import json
import logging
import threading
from datetime import date, timedelta

from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..security import WRITE_ROLES, write_roles_required

from ..database import get_cursor
from ..repositories import (
    AuditRepository,
    MovementRepository,
    ProductRepository,
    PurchaseOrderRepository,
    SupplierRepository,
    WarehouseRepository,
)
from ..services import MovementService, ProductService, SettingsService, SupplierService
from ..utils import format_money_display
from ..utils.cache import (
    api_cache,
    dashboard_cache,
    landing_cache,
    make_key,
    monitoring_cache,
    products_cache,
    reports_cache,
    suppliers_cache,
    cache_bust_products,
    cache_bust_suppliers,
    cache_bust_movements,
    cache_bust_purchase_orders,
    cache_bust_settings,
)

LOGGER = logging.getLogger(__name__)


ui_bp = Blueprint("ui", __name__)


@ui_bp.route("/")
def dashboard():
    if not current_user.is_authenticated:
        return render_template("landing.html", stats=_landing_stats())

    today = date.today()
    _, critical_pct = SettingsService.threshold_pcts()
    critical_ratio = critical_pct / 100.0

    # Dashboard cache key - per date (same data for all users)
    dash_key = f"dashboard:{today.isoformat()}"
    cached = dashboard_cache.get(dash_key)
    if cached:
        return render_template("dashboard.html", **cached)

    # Run monitoring checks (non-blocking, at most once per 10 min)
    try:
        from ..services.notification_service import run_monitoring_checks
        import threading
        threading.Thread(target=run_monitoring_checks, daemon=True).start()
    except Exception:
        pass

    with get_cursor() as cur:
        # --- Batch 1: product aggregates (1 query instead of 4) ---
        cur.execute(
            """
            SELECT
                COUNT(*) AS total_skus,
                COALESCE(SUM(current_stock * unit_price), 0) AS inventory_value,
                COUNT(*) FILTER (WHERE current_stock <= reorder_point AND on_order <= 0) AS reorder_count,
                COUNT(*) FILTER (WHERE current_stock <= reorder_point AND on_order <= 0
                    AND (current_stock <= reorder_point * %s OR current_stock <= 0)) AS critical,
                COUNT(*) FILTER (WHERE current_stock <= reorder_point AND on_order <= 0
                    AND current_stock > reorder_point * %s) AS warning
            FROM products
            """,
            (critical_ratio, critical_ratio),
        )
        agg = cur.fetchone()
        total_skus = agg["total_skus"]
        inventory_value = float(agg["inventory_value"] or 0)
        reorder_count = int(agg["reorder_count"] or 0)
        critical_count = int(agg["critical"] or 0)
        warning_count = int(agg["warning"] or 0)

        cur.execute("SELECT COALESCE(SUM(quantity), 0) AS units FROM movements WHERE created_at::date = %s", (today,))
        units_today = int(cur.fetchone()["units"] or 0)

        # --- KPI deltas: daily avg (30d) and previous month inventory value ---
        cur.execute(
            "SELECT COALESCE(AVG(daily_qty), 0) AS avg FROM ("
            "  SELECT SUM(quantity) AS daily_qty FROM movements "
            "  WHERE created_at >= %s AND created_at::date != %s "
            "  GROUP BY created_at::date"
            ") sub",
            (today - timedelta(days=30), today),
        )
        daily_avg_units = float(cur.fetchone()["avg"] or 0)
        units_delta_pct = round(
            ((units_today - daily_avg_units) / daily_avg_units * 100) if daily_avg_units > 0 else 0, 1
        )

        first_of_month = today.replace(day=1)
        prev_month_end = first_of_month - timedelta(days=1)
        prev_month_start = prev_month_end.replace(day=1)
        cur.execute(
            "SELECT COALESCE(SUM(current_stock * unit_price), 0) AS val FROM products"
        )
        current_inv = float(cur.fetchone()["val"] or 0)
        cur.execute(
            """
            SELECT COALESCE(SUM(
                (SELECT COALESCE(SUM(quantity), 0) FROM movements m2
                 WHERE m2.product_id = p.id AND m2.type = 'OUT'
                   AND m2.created_at >= %s AND m2.created_at < %s)
                * p.unit_price
            ), 0) AS prev_out_value
            FROM products p WHERE p.unit_price IS NOT NULL
            """,
            (prev_month_start, first_of_month),
        )
        prev_month_out_value = float(cur.fetchone()["prev_out_value"] or 0)
        inv_delta_pct = round(
            ((current_inv - prev_month_out_value) / prev_month_out_value * 100)
            if prev_month_out_value > 0 else 0, 1
        )

        rows = MovementRepository.daily_totals(14)
        series, dates = _series_for_last_days(rows, 14)
        chart = _chart_geometry(series, dates)

        inout_rows = MovementRepository.daily_inout(14)
        in_series, out_series, inout_dates = _inout_series(inout_rows, 14)
        inout_max = max((max(in_series), max(out_series))) or 1

        # --- Batch 2: category counts (same products scan, separate query for grouping) ---
        cur.execute("SELECT category, COUNT(*) AS cnt FROM products WHERE category IS NOT NULL GROUP BY category ORDER BY cnt DESC")
        raw = cur.fetchall()
        max_cat = max((r["cnt"] for r in raw), default=1) or 1
        tones = ["", "amber", "blue", "ink"]
        category_counts = []
        for i, row in enumerate(raw):
            category_counts.append({
                "category": row["category"],
                "count": row["cnt"],
                "pct": round((row["cnt"] / max_cat) * 100),
                "tone": tones[i % len(tones)],
            })

        queue = ProductRepository.low_stock()[:4]

        cur.execute(
            """
            SELECT p.id, p.sku, p.name
            FROM products p
            LEFT JOIN movements m ON m.product_id = p.id AND m.created_at >= %s
            GROUP BY p.id, p.sku, p.name
            ORDER BY COALESCE(SUM(m.quantity), 0) DESC, p.id
            LIMIT 1
            """,
            (today - timedelta(days=30),),
        )
        top = cur.fetchone()
        forecast_product = {"id": top["id"], "sku": top["sku"], "name": top["name"]} if top else None

        # --- Slow-moving products: longest time sitting in inventory ---------
        # Days since the product's last OUT (sales) movement. Products with the
        # biggest gap hold capital idle for the longest.
        cur.execute(
            """
            SELECT p.id, p.sku, p.name, p.category, p.warehouse, p.current_stock,
                   p.unit_price, p.reorder_point,
                   COALESCE(MAX(CASE WHEN m.type = 'OUT' THEN m.created_at::date END),
                            p.created_at::date) AS last_out
            FROM products p
            LEFT JOIN movements m ON m.product_id = p.id
            GROUP BY p.id
            ORDER BY last_out ASC
            LIMIT 6
            """
        )
        slow_movers = list(cur.fetchall())
        today_dt = date.today()
        for row in slow_movers:
            row["days_idle"] = max((today_dt - row["last_out"]).days, 0)

        # --- Top demand & top sales (last 90 days, 1 query instead of 2) -----
        cur.execute(
            """
            SELECT p.sku, p.name, p.category,
                   COALESCE(SUM(CASE WHEN m.type = 'OUT' THEN m.quantity ELSE 0 END), 0) AS units,
                   COALESCE(SUM(CASE WHEN m.type = 'OUT'
                                     THEN m.quantity * p.unit_price ELSE 0 END), 0) AS value
            FROM products p
            JOIN movements m ON m.product_id = p.id
            WHERE m.created_at >= %s
            GROUP BY p.sku, p.name, p.category
            """,
            (today - timedelta(days=90),),
        )
        top_rows = list(cur.fetchall())
        top_demand = sorted(top_rows, key=lambda r: int(r["units"] or 0), reverse=True)[:10]
        top_sales = sorted(top_rows, key=lambda r: float(r["value"] or 0), reverse=True)[:10]

        # --- Top supplier by procurement spend (this year) -------------------
        cur.execute(
            """
            SELECT s.name, s.location AS contact_person,
                   COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.quantity ELSE 0 END), 0) AS units_in,
                   COALESCE(SUM(CASE WHEN m.type = 'IN'
                                     THEN m.quantity * p.unit_price ELSE 0 END), 0) AS spend,
                   COUNT(DISTINCT p.id) AS skus
            FROM suppliers s
            JOIN products p ON p.supplier_id = s.id
            LEFT JOIN movements m ON m.product_id = p.id
                AND m.type = 'IN' AND m.created_at >= %s
            GROUP BY s.id
            ORDER BY spend DESC, units_in DESC
            LIMIT 5
            """,
            (date(today.year, 1, 1),),
        )
        top_suppliers = list(cur.fetchall())

        # --- Warehouse stock & price profile for charts ---------------------
        cur.execute(
            """
            SELECT warehouse,
                   COUNT(*) AS sku_count,
                   COALESCE(SUM(current_stock), 0) AS total_units,
                   COALESCE(AVG(unit_price), 0) AS avg_price,
                   COALESCE(SUM(current_stock * unit_price), 0) AS total_value
            FROM products
            WHERE warehouse IS NOT NULL
            GROUP BY warehouse
            ORDER BY total_units DESC
            """
        )
        warehouse_profile = list(cur.fetchall())

        # --- Stock turnover rate by category (COGS / avg inventory) -----------
        cur.execute(
            """
            SELECT p.category,
                   COALESCE(SUM(CASE WHEN m.type = 'OUT' THEN m.quantity * p.unit_price ELSE 0 END), 0) AS cogs,
                   COALESCE(AVG(p.current_stock * p.unit_price), 0) AS avg_inv_value,
                   COUNT(*) AS sku_count
            FROM products p
            LEFT JOIN movements m ON m.product_id = p.id
                AND m.type = 'OUT' AND m.created_at >= %s
            WHERE p.category IS NOT NULL AND p.unit_price IS NOT NULL
            GROUP BY p.category
            ORDER BY cogs DESC
            """,
            (today - timedelta(days=365),),
        )
        turnover_by_category = list(cur.fetchall())
        for row in turnover_by_category:
            avg_inv = float(row["avg_inv_value"] or 0)
            row["turnover_rate"] = round(float(row["cogs"] or 0) / avg_inv, 2) if avg_inv > 10 else 0

        # --- ABC analysis (Pareto) - SKUs ranked by inventory value ------------
        cur.execute(
            """
            SELECT sku, name, category, (current_stock * unit_price) AS value
            FROM products
            WHERE unit_price IS NOT NULL AND current_stock > 0
            ORDER BY value DESC
            """
        )
        abc_rows = list(cur.fetchall())
        total_value = sum(float(r["value"] or 0) for r in abc_rows)
        cum = 0.0
        abc_data = []
        for i, row in enumerate(abc_rows, 1):
            cum += float(row["value"] or 0)
            pct = round(cum / total_value * 100, 1) if total_value else 0
            if pct <= 80:
                cls = "A"
            elif pct <= 95:
                cls = "B"
            else:
                cls = "C"
            abc_data.append({
                "rank": i,
                "sku": row["sku"],
                "name": row["name"],
                "category": row["category"],
                "value": float(row["value"] or 0),
                "cum_pct": pct,
                "class": cls,
            })

        # --- AI savings (YTD): EOQ query inside same cursor (1 conn instead of 2) ---
        cur.execute(
            """
            SELECT demand_rate, ordering_cost, holding_cost, unit_price
            FROM products
            WHERE demand_rate > 0 AND ordering_cost > 0 AND holding_cost > 0
            """
        )
        eoq_rows = cur.fetchall()

    healthy_count = max(total_skus - reorder_count, 0)
    health_pct = round(healthy_count / max(total_skus, 1) * 100) if total_skus else 0

    import math
    ai_savings = 0.0
    try:
        for row in eoq_rows:
            D = float(row["demand_rate"])
            S = float(row["ordering_cost"])
            H = float(row["holding_cost"])
            # Manual: order monthly (D/12 per order)
            manual_qty = D / 12.0
            if manual_qty > 0:
                manual_cost = (D / manual_qty) * S + (manual_qty / 2) * H
            else:
                manual_cost = 0
            # EOQ-optimized
            eoq = math.sqrt(2 * D * S / H) if H > 0 else 0
            if eoq > 0:
                eoq_cost = (D / eoq) * S + (eoq / 2) * H
            else:
                eoq_cost = manual_cost
            ai_savings += max(manual_cost - eoq_cost, 0)
    except Exception:
        pass

    template_context = {
        "total_skus": total_skus,
        "inventory_value": inventory_value,
        "reorder_count": reorder_count,
        "critical_count": critical_count,
        "warning_count": warning_count,
        "units_today": units_today,
        "units_delta_pct": units_delta_pct,
        "inv_delta_pct": inv_delta_pct,
        "health_pct": min(health_pct, 100),
        "chart": chart,
        "in_series": in_series,
        "out_series": out_series,
        "inout_dates": inout_dates,
        "inout_max": inout_max,
        "category_counts": category_counts,
        "queue": queue,
        "forecast_product": forecast_product,
        "forecast_model": SettingsService.forecast_model(),
        "queue_units": sum(int(p.get("current_stock") or 0) for p in queue),
        "slow_movers": slow_movers,
        "top_demand": top_demand,
        "top_sales": top_sales,
        "top_suppliers": top_suppliers,
        "warehouse_profile": warehouse_profile,
        "turnover_by_category": turnover_by_category,
        "abc_data": abc_data,
        "ai_savings": ai_savings,
        "today": today,
        "format_money": format_money_display,
    }
    dashboard_cache.set(dash_key, template_context)

    return render_template("dashboard.html", **template_context)


@ui_bp.route("/inventory")
@login_required
def inventory():
    query = {
        "search": request.args.get("search", "").strip(),
        "category": request.args.get("category", "").strip(),
        "warehouse": request.args.get("warehouse", "").strip(),
        "stock_status": request.args.get("stock_status", "").strip(),
        "page": max(1, int(request.args.get("page", 1))),
        "per_page": 20,
    }
    cache_key = make_key(view="inventory", **query)

    def _load():
        d = ProductService.list_products(**query)
        # Render-serializable snapshot: rows are plain dicts from RealDictCursor
        return {
            "products": d["rows"],
            "pagination": d["pagination"],
            "categories": ProductRepository.categories(),
            "warehouses": ProductRepository.warehouses(),
        }

    cached = products_cache.get_or_set(cache_key, _load)
    return render_template(
        "inventory.html",
        products=cached["products"],
        pagination=cached["pagination"],
        categories=cached["categories"],
        warehouses=cached["warehouses"],
        query=query,
        format_money=format_money_display,
    )


@ui_bp.route("/inventory/export")
@login_required
def inventory_export():
    rows, _ = ProductRepository.list(search=request.args.get("search", ""),
                                      category=request.args.get("category", ""), limit=10000)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["SKU", "Product", "Category", "Warehouse", "Stock", "Reorder", "Price", "Supplier"])
    for r in rows:
        writer.writerow([r["sku"], r["name"], r["category"] or "", r.get("warehouse") or "",
                         r["current_stock"], r["reorder_point"], float(r.get("unit_price") or 0),
                         r.get("supplier_name") or ""])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=inventory.csv"})


@ui_bp.route("/products/new", methods=["GET", "POST"])
@ui_bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
@write_roles_required
def product_form(product_id: int | None = None):
    product = ProductRepository.find(product_id) if product_id else None
    if product_id and not product:
        flash("Product not found", "error")
        return redirect(url_for("ui.inventory"))
    suppliers = SupplierRepository.list_all()
    categories = ProductRepository.categories()
    warehouses = ProductRepository.warehouses()

    if request.method == "POST":
        payload = {
            "sku": request.form.get("sku"),
            "name": request.form.get("name"),
            "category": request.form.get("category"),
            "warehouse": request.form.get("warehouse"),
            "current_stock": request.form.get("current_stock") or 0,
            "reorder_point": request.form.get("reorder_point") or 0,
            "unit_price": request.form.get("unit_price"),
            "demand_rate": request.form.get("demand_rate"),
            "ordering_cost": request.form.get("ordering_cost"),
            "holding_cost": request.form.get("holding_cost"),
            "supplier_id": request.form.get("supplier_id"),
        }
        try:
            if product_id:
                ProductService.update(product_id, payload)
                flash("Product updated", "success")
            else:
                new_id = ProductService.create(payload)
                flash(f"Product created with ID {new_id}", "success")
            cache_bust_products()
        except Exception as exc:
            flash(str(exc), "error")
            return render_template(
                "product_form.html", product=payload, suppliers=suppliers,
                categories=categories, warehouses=warehouses,
            )
        return redirect(url_for("ui.inventory"))

    return render_template(
        "product_form.html", product=product, suppliers=suppliers,
        categories=categories, warehouses=warehouses,
    )


@ui_bp.route("/products/<int:product_id>/delete", methods=["POST"])
@login_required
@write_roles_required
def delete_product(product_id: int):
    ProductService.delete(product_id)
    AuditRepository.record(current_user.id, "product.delete",
                           target_type="product", target_id=product_id)
    cache_bust_products()
    flash("Product deleted", "success")
    return redirect(url_for("ui.inventory"))


@ui_bp.route("/products/<int:product_id>")
@login_required
def product_detail(product_id: int):
    product = ProductRepository.find(product_id)
    if not product:
        flash("Product not found", "error")
        return redirect(url_for("ui.inventory"))
    movements = MovementRepository.recent_for_product(product_id, limit=10)
    return render_template("product_detail.html", p=product, movements=movements,
                           format_money=format_money_display)


@ui_bp.route("/reorder-alerts")
@login_required
def reorder_alerts():
    def _load():
        alerts = ProductRepository.low_stock()
        return {"alerts": alerts, "critical_count": sum(1 for a in alerts if a.get("status") == "critical")}
    cached = products_cache.get_or_set("reorder_alerts", _load)
    return render_template(
        "reorder_alerts.html",
        alerts=cached["alerts"],
        critical_count=cached["critical_count"],
        auto_reorder=SettingsService.is_on("auto_reorder"),
    )


@ui_bp.route("/reorder-alerts/auto-draft", methods=["POST"])
@login_required
@write_roles_required
def auto_draft_pos():
    if not SettingsService.is_on("auto_reorder"):
        flash("Auto-reorder is disabled in Settings", "warning")
        return redirect(url_for("ui.reorder_alerts"))
    alerts = [a for a in ProductRepository.low_stock() if a.get("status") == "critical"]
    if not alerts:
        flash("No critical items to reorder", "warning")
        return redirect(url_for("ui.reorder_alerts"))
    from ..utils import calculate_eoq

    created = 0
    for product in alerts:
        if int(product.get("on_order") or 0) > 0:
            continue
        eoq = calculate_eoq(product.get("demand_rate"), product.get("ordering_cost"),
                            product.get("holding_cost"))
        deficit = max(int(product["reorder_point"] or 0) - int(product["current_stock"] or 0), 1)
        qty = max(int(round(eoq)) if eoq else deficit, deficit)
        # Cap at 6 months of demand to prevent over-ordering
        demand = float(product.get("demand_rate") or 0)
        if demand > 0:
            demand_cap = int(round(demand / 2))
            qty = min(qty, demand_cap)
        po_number = f"AUTO-{date.today():%Y%m%d}-{product['sku']}"
        PurchaseOrderRepository.create({
            "po_number": po_number,
            "supplier_id": product.get("supplier_id"),
            "product_id": product["id"],
            "quantity": qty,
            "unit_cost": product.get("unit_price") or 0,
            "status": "draft",
        })
        ProductRepository.set_on_order(product["id"], qty)
        AuditRepository.record(current_user.id, "po.auto_draft",
                               target_type="product", target_id=product["id"],
                               detail={"quantity": qty, "po_number": po_number})
        created += 1
    cache_bust_purchase_orders()
    flash(f"Auto-reorder drafted {created} purchase order(s) for critical stock", "success")
    return redirect(url_for("ui.reorder_alerts"))


@ui_bp.route("/reorder-alerts/<int:product_id>/mark-ordered", methods=["POST"])
@login_required
@write_roles_required
def mark_ordered(product_id: int):
    product = ProductRepository.find(product_id)
    if not product:
        flash("Product not found", "error")
        return redirect(url_for("ui.reorder_alerts"))
    from ..utils import calculate_eoq
    eoq = calculate_eoq(product.get("demand_rate"), product.get("ordering_cost"), product.get("holding_cost"))
    deficit = max(int(product["reorder_point"] or 0) - int(product["current_stock"] or 0), 1)
    qty = max(int(round(eoq)) if eoq else deficit, deficit)
    ProductRepository.set_on_order(product_id, qty)
    AuditRepository.record(current_user.id, "po.create",
                           target_type="product", target_id=product_id,
                           detail={"quantity": qty})
    cache_bust_purchase_orders()
    flash(f"PO recorded for {product['sku']}: {qty} units on order", "success")
    return redirect(url_for("ui.reorder_alerts"))


@ui_bp.route("/movements/new", methods=["GET", "POST"])
@login_required
@write_roles_required
def movement_form():
    preselect = request.args.get("product_id", type=int)
    with get_cursor() as cur:
        cur.execute(
            "SELECT p.id, p.sku, p.name, p.current_stock, p.reorder_point "
            "FROM products p ORDER BY p.sku"
        )
        products = list(cur.fetchall())

    if request.method == "POST":
        try:
            MovementService.record(
                product_id=int(request.form.get("product_id", 0)),
                mtype=request.form.get("type", "").strip().upper(),
                quantity=int(request.form.get("quantity") or 0),
                reference=request.form.get("reference"),
                notes=request.form.get("notes"),
                user_id=current_user.id,
            )
            flash("Movement saved.", "success")
            cache_bust_movements()
            return redirect(url_for("ui.inventory"))
        except Exception as exc:
            flash(str(exc), "error")
    return render_template("movement_form.html", products=products, preselect=preselect)


@ui_bp.route("/suppliers", methods=["GET", "POST"])
@login_required
def suppliers():
    if request.method == "POST":
        if current_user.role not in WRITE_ROLES:
            abort(403)
        try:
            SupplierService.create({
                "name": request.form.get("name"),
                "location": request.form.get("location"),
                "lead_days": request.form.get("lead_days"),
                "spend_amount": request.form.get("spend_amount"),
                "reliability": request.form.get("reliability") or 90,
                "tone": request.form.get("tone", "amber"),
            })
            flash("Supplier added", "success")
            cache_bust_suppliers()
        except Exception as exc:
            flash(str(exc), "error")
        return redirect(url_for("ui.suppliers"))
    rows = suppliers_cache.get_or_set("list_all", SupplierRepository.list_all)
    return render_template("suppliers.html", suppliers=rows)


@ui_bp.route("/suppliers/<int:supplier_id>/delete", methods=["POST"])
@login_required
@write_roles_required
def delete_supplier(supplier_id: int):
    SupplierService.delete(supplier_id)
    cache_bust_suppliers()
    flash("Supplier removed", "success")
    return redirect(url_for("ui.suppliers"))


@ui_bp.route("/purchase-orders", methods=["GET", "POST"])
@login_required
def purchase_orders():
    if request.method == "POST":
        if current_user.role not in WRITE_ROLES:
            abort(403)
        import random

        po_number = request.form.get("po_number") or "PO-{0:%Y%m%d}-{1:04d}".format(
            date.today(), random.randint(0, 9999)
        )
        payload = {
            "po_number": po_number,
            "supplier_id": request.form.get("supplier_id") or None,
            "product_id": request.form.get("product_id") or None,
            "quantity": request.form.get("quantity") or 0,
            "unit_cost": request.form.get("unit_cost") or 0,
            "status": request.form.get("status") or "draft",
            "eta_date": request.form.get("eta_date") or None,
        }
        if not payload["supplier_id"]:
            flash("Please select a supplier.", "error")
            return redirect(url_for("ui.purchase_orders"))
        if not payload["product_id"]:
            flash("Please select a product.", "error")
            return redirect(url_for("ui.purchase_orders"))
        qty = int(payload["quantity"])
        if qty <= 0:
            flash("Quantity must be at least 1.", "error")
            return redirect(url_for("ui.purchase_orders"))
        unit_cost = float(payload["unit_cost"])
        if unit_cost < 0:
            flash("Unit cost cannot be negative.", "error")
            return redirect(url_for("ui.purchase_orders"))
        if payload["eta_date"] and payload["eta_date"] < date.today().isoformat():
            flash("ETA date cannot be in the past.", "error")
            return redirect(url_for("ui.purchase_orders"))
        PurchaseOrderRepository.create(payload)
        cache_bust_purchase_orders()
        flash("Purchase order %s created" % po_number, "success")
        return redirect(url_for("ui.purchase_orders"))

    def _load_board():
        with get_cursor() as cur:
            cur.execute("SELECT id, name FROM suppliers ORDER BY name")
            sup = list(cur.fetchall())
            cur.execute("SELECT id, sku, name FROM products ORDER BY sku")
            prods = list(cur.fetchall())
            cur.execute("SELECT * FROM sp_po_list_by_status(NULL)")
            all_pos = list(cur.fetchall())
            cur.execute("SELECT * FROM sp_po_counts_by_status()")
            counts = {row["status"]: int(row["cnt"]) for row in cur.fetchall()}
        by_status = {"draft": [], "approved": [], "in_transit": [], "received": []}
        for po in all_pos:
            s = po.get("status")
            if s in by_status:
                by_status[s].append(po)
        return {
            "counts": counts,
            "suppliers": sup,
            "products": prods,
            "draft": by_status["draft"],
            "approved": by_status["approved"],
            "in_transit": by_status["in_transit"],
            "received": by_status["received"],
        }

    board = api_cache.get_or_set("po_board", _load_board)
    return render_template("purchase_orders.html",
                           counts=board["counts"],
                           suppliers=board["suppliers"],
                           products=board["products"],
                           today=date.today(),
                           draft=board["draft"],
                           approved=board["approved"],
                           in_transit=board["in_transit"],
                           received=board["received"])


@ui_bp.route("/purchase-orders/<int:po_id>/status", methods=["POST"])
@login_required
@write_roles_required
def update_po_status(po_id: int):
    status = request.form.get("status")
    if status in ("draft", "approved", "in_transit", "received", "cancelled"):
        # Get PO details before update for notification
        with get_cursor() as cur:
            cur.execute(
                """SELECT po.po_number, s.name AS supplier_name
                   FROM purchase_orders po
                   LEFT JOIN suppliers s ON s.id = po.supplier_id
                   WHERE po.id = %s""",
                (po_id,),
            )
            po_row = cur.fetchone()

        PurchaseOrderRepository.update_status(po_id, status)
        cache_bust_purchase_orders()
        flash("Purchase order status updated to " + status, "success")

        # Send notification
        if po_row:
            try:
                from ..services.notification_service import notify_po_status
                notify_po_status(
                    po_number=po_row["po_number"],
                    status=status,
                    supplier_name=po_row.get("supplier_name", "Unknown"),
                )
            except Exception:
                pass
    return redirect(url_for("ui.purchase_orders"))


@ui_bp.route("/warehouses")
@login_required
def warehouses():
    """Warehouse overview served from the star-schema warehouse (dim + facts).

    Falls back to the operational tables if the ETL hasn't run yet.
    """
    def _load():
        rows = WarehouseRepository.analytics()
        if rows is None:
            rows = _warehouses_legacy()
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT warehouse,
                       COUNT(*) AS sku_count,
                       COALESCE(SUM(current_stock), 0) AS total_units,
                       COALESCE(AVG(unit_price), 0) AS avg_price,
                       COALESCE(SUM(current_stock * unit_price), 0) AS total_value
                FROM products
                WHERE warehouse IS NOT NULL
                GROUP BY warehouse
                ORDER BY total_units DESC
                """
            )
            return {"rows": rows, "chart_data": list(cur.fetchall())}

    cached = products_cache.get_or_set("warehouses_page", _load)
    rows = cached["rows"]
    active_warehouse = rows[0]["warehouse"] if rows else None

    return render_template("warehouses.html", warehouses=rows,
                           format_money=format_money_display,
                           active_warehouse=active_warehouse,
                           chart_data=cached["chart_data"])


def _warehouses_legacy():
    """Direct query over ``products`` used until the star schema is populated."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT warehouse,
                   COUNT(*) AS sku_count,
                   COALESCE(SUM(current_stock), 0) AS total_units,
                   COALESCE(SUM(current_stock * unit_price), 0) AS total_value,
                   SUM(CASE WHEN current_stock <= reorder_point AND current_stock > 0 THEN 1 ELSE 0 END) AS low_count,
                   SUM(CASE WHEN current_stock <= 0 THEN 1 ELSE 0 END) AS critical_count
            FROM products WHERE warehouse IS NOT NULL
            GROUP BY warehouse ORDER BY total_value DESC
            """
        )
        return list(cur.fetchall())


@ui_bp.route("/reports", methods=["GET", "POST"])
@login_required
def reports():
    # --- Filter parameters ---
    # Multi-select month/year from JSON hidden inputs
    month_json = request.values.get("month_json")
    year_json = request.values.get("year_json")

    try:
        parsed_months = json.loads(month_json) if month_json else []
    except (TypeError, ValueError):
        parsed_months = None
    selected_months = (
        parsed_months if isinstance(parsed_months, list)
        else request.values.getlist("month")
    )
    selected_months = [str(m) for m in selected_months if m]

    try:
        parsed_years = json.loads(year_json) if year_json else []
    except (TypeError, ValueError):
        parsed_years = None
    selected_years = (
        parsed_years if isinstance(parsed_years, list)
        else request.values.getlist("year")
    )
    selected_years = [str(y) for y in selected_years if y]

    # Compute date range strings for backend filtering
    date_from = None
    date_to = None
    if selected_months and selected_years:
        combos = [(int(y), int(m)) for y in selected_years for m in selected_months]
        earliest = min(combos)
        latest = max(combos)
        date_from = f"{earliest[0]}-{earliest[1]:02d}"
        date_to = f"{latest[0]}-{latest[1]:02d}"
    elif selected_months:
        min_m = min(int(m) for m in selected_months)
        max_m = max(int(m) for m in selected_months)
        date_from = f"2024-{min_m:02d}"
        date_to = f"{date.today().year}-{max_m:02d}"
    elif selected_years:
        min_y = min(int(y) for y in selected_years)
        max_y = max(int(y) for y in selected_years)
        date_from = f"{min_y}-01"
        date_to = f"{max_y}-12"

    def _month_bounds(value):
        try:
            y, m = value.split("-")
            first = date(int(y), int(m), 1)
            last = date(int(y) + (int(m) == 12), (int(m) % 12) + 1, 1) - timedelta(days=1)
            return first, last
        except Exception:
            return None, None

    date_from_start, date_from_end = _month_bounds(date_from) if date_from else (None, None)
    date_to_start, date_to_end = _month_bounds(date_to) if date_to else (None, None)
    
    # Handle multi-select filters (from JSON hidden inputs or comma-separated)
    warehouse_json = request.values.get("warehouse_json")
    category_json = request.values.get("category_json")
    
    try:
        parsed_warehouses = json.loads(warehouse_json) if warehouse_json else []
    except (TypeError, ValueError):
        parsed_warehouses = None
    selected_warehouses = (
        parsed_warehouses if isinstance(parsed_warehouses, list)
        else request.values.getlist("warehouse")
    )
    selected_warehouses = [str(w) for w in selected_warehouses if w]

    try:
        parsed_categories = json.loads(category_json) if category_json else []
    except (TypeError, ValueError):
        parsed_categories = None
    selected_categories = (
        parsed_categories if isinstance(parsed_categories, list)
        else request.values.getlist("category")
    )
    selected_categories = [str(c) for c in selected_categories if c]

    # Backward compatibility with single select
    if not selected_warehouses:
        selected_warehouses = [request.values.get("warehouse")] if request.values.get("warehouse") else []
    if not selected_categories:
        selected_categories = [request.values.get("category")] if request.values.get("category") else []

    # Build WHERE conditions
    product_conditions = []
    product_params = []
    movement_conditions = []
    movement_params = []

    if selected_warehouses:
        placeholders = ','.join(['%s'] * len(selected_warehouses))
        product_conditions.append(f"p.warehouse IN ({placeholders})")
        product_params.extend(selected_warehouses)

    if selected_categories:
        placeholders = ','.join(['%s'] * len(selected_categories))
        product_conditions.append(f"p.category IN ({placeholders})")
        product_params.extend(selected_categories)

    # Period-active filter: when dates are set, restrict every panel to products
    # that had movement within the selected range.  Materialize the IDs once
    # instead of repeating the subquery in every panel (~12 queries).
    period_active_ids = None
    if date_from_start or date_to_end:
        period_start = date_from_start if date_from_start else (date.today() - timedelta(days=3650))
        period_end = (date_to_end + timedelta(days=1)) if date_to_end else (date.today() + timedelta(days=1))
        from ..database.connection import get_cursor as _gc
        with _gc() as _cur:
            _cur.execute(
                "SELECT DISTINCT product_id FROM movements "
                "WHERE created_at >= %s AND created_at < %s",
                (period_start, period_end),
            )
            period_active_ids = [r["product_id"] for r in _cur.fetchall()]
        if period_active_ids:
            ids_placeholders = ','.join(['%s'] * len(period_active_ids))
            product_conditions.append(f"p.id IN ({ids_placeholders})")
            product_params.extend(int(i) for i in period_active_ids)
        else:
            product_conditions.append("p.id = 0")

    product_where = ("WHERE " + " AND ".join(product_conditions)) if product_conditions else "WHERE 1=1"

    # Filters without the period-active clause — used by the fixed-period
    # (MTD/YTD) and cross-sectional panels so their scope is warehouse/category only.
    filter_conditions = []
    filter_params = []
    if selected_warehouses:
        placeholders = ','.join(['%s'] * len(selected_warehouses))
        filter_conditions.append(f"p.warehouse IN ({placeholders})")
        filter_params.extend(selected_warehouses)
    if selected_categories:
        placeholders = ','.join(['%s'] * len(selected_categories))
        filter_conditions.append(f"p.category IN ({placeholders})")
        filter_params.extend(selected_categories)
    filter_clause = (" AND " + " AND ".join(filter_conditions)) if filter_conditions else ""

    # Date range for movement (month bounds)
    if date_from_start:
        movement_conditions.append("m.created_at >= %s")
        movement_params.append(date_from_start)
    if date_to_end:
        movement_conditions.append("m.created_at < %s")
        movement_params.append(date_to_end + timedelta(days=1))
    if not date_from_start and not date_to_end:
        movement_conditions.append("m.created_at >= NOW() - INTERVAL '30 days'")

    movement_where = ("WHERE " + " AND ".join(movement_conditions)) if movement_conditions else "WHERE 1=1"

    # --- Cache key for reports data ---
    cache_key = make_key(
        date_from=date_from or "",
        date_to=date_to or "",
        warehouses=",".join(selected_warehouses) if selected_warehouses else "",
        categories=",".join(selected_categories) if selected_categories else "",
    )
    cached = reports_cache.get(cache_key)
    if cached:
        # Unpack cached data and render
        return render_template(
            "reports.html",
            **cached,
        )

    with get_cursor() as cur:
        # --- Category breakdown + KPIs + stock status (1 query instead of 3) ---
        low_pct, critical_pct = SettingsService.threshold_pcts()
        crit_ratio = critical_pct / 100.0
        if date_from_start or date_to_end:
            _pc = ("AND " + " AND ".join(product_conditions)) if product_conditions else ""
            cur.execute(
                f"""
                SELECT p.category,
                       SUM(m.quantity * p.unit_price) AS cat_value,
                       SUM(m.quantity) AS cat_units,
                       COUNT(DISTINCT m.product_id) AS sku_count,
                       SUM(m.quantity) AS total_units,
                       SUM(m.quantity * p.unit_price) AS inventory_value,
                       SUM(CASE WHEN p.current_stock <= 0 THEN 1 ELSE 0 END) AS out_of_stock,
                       SUM(CASE WHEN p.current_stock <= p.reorder_point AND p.on_order <= 0
                                THEN 1 ELSE 0 END) AS below_rop,
                       SUM(CASE WHEN p.current_stock <= 0 THEN 1 ELSE 0 END) AS out_count,
                       SUM(CASE WHEN p.current_stock > 0 AND p.reorder_point > 0
                                  AND p.current_stock <= p.reorder_point * %s THEN 1 ELSE 0 END) AS critical_count,
                       SUM(CASE WHEN p.current_stock > 0 AND p.reorder_point > 0
                                  AND p.current_stock > p.reorder_point * %s
                                  AND p.current_stock <= p.reorder_point THEN 1 ELSE 0 END) AS warning_count,
                       COUNT(DISTINCT m.product_id) AS total_count
                FROM movements m
                JOIN products p ON p.id = m.product_id
                WHERE m.created_at >= %s AND m.created_at < %s {_pc}
                  AND p.unit_price IS NOT NULL
                GROUP BY p.category ORDER BY cat_value DESC
                """,
                tuple([crit_ratio, crit_ratio, period_start, period_end] + product_params)
            )
            raw = list(cur.fetchall())
            breakdown = []
            total = sum(float(r["cat_value"] or 0) for r in raw) or 1
            tones = ["ink", "amber", "green", "blue", ""]
            for i, r in enumerate(raw):
                breakdown.append({
                    "category": r["category"],
                    "value": float(r["cat_value"] or 0),
                    "units": int(r["cat_units"] or 0),
                    "pct": round((float(r["cat_value"] or 0) / total) * 100),
                    "tone": tones[i % len(tones)],
                    "bar_class": "bar-fill " + (tones[i % len(tones)] or "").strip(),
                    "bar_width": str(round((float(r["cat_value"] or 0) / total) * 100)),
                })
            first = raw[0] if raw else {}
            kpi = {
                "sku_count": first.get("sku_count"),
                "total_units": first.get("total_units"),
                "inventory_value": first.get("inventory_value"),
                "out_of_stock": first.get("out_of_stock"),
                "below_rop": first.get("below_rop"),
            }
            st = {
                "out_count": first.get("out_count"),
                "critical_count": first.get("critical_count"),
                "warning_count": first.get("warning_count"),
                "total_count": first.get("total_count"),
            }
        else:
            cur.execute(
                f"""
                SELECT p.category,
                       COALESCE(SUM(p.current_stock * p.unit_price), 0) AS value,
                       COALESCE(SUM(p.current_stock), 0) AS units
                FROM products p
                {product_where}
                AND p.category IS NOT NULL AND p.unit_price IS NOT NULL
                GROUP BY p.category ORDER BY value DESC
                """,
                tuple(product_params)
            )
            raw = list(cur.fetchall())
            total = sum(float(r["value"] or 0) for r in raw) or 1
            breakdown = []
            tones = ["ink", "amber", "green", "blue", ""]
            for i, r in enumerate(raw):
                breakdown.append({
                    "category": r["category"],
                    "value": float(r["value"] or 0),
                    "units": int(r["units"] or 0),
                    "pct": round((float(r["value"] or 0) / total) * 100),
                    "tone": tones[i % len(tones)],
                    "bar_class": "bar-fill " + (tones[i % len(tones)] or "").strip(),
                    "bar_width": str(round((float(r["value"] or 0) / total) * 100)),
                })
            cur.execute(
                f"""
                SELECT COUNT(*) AS sku_count,
                       COALESCE(SUM(current_stock), 0) AS total_units,
                       COALESCE(SUM(current_stock * unit_price), 0) AS inventory_value,
                       SUM(CASE WHEN current_stock <= 0 THEN 1 ELSE 0 END) AS out_of_stock,
                       SUM(CASE WHEN current_stock <= reorder_point AND on_order <= 0
                                THEN 1 ELSE 0 END) AS below_rop
                FROM products p
                {product_where}
                """,
                tuple(product_params)
            )
            kpi = cur.fetchone()
            cur.execute(
                f"""
                SELECT SUM(CASE WHEN current_stock <= 0 THEN 1 ELSE 0 END) AS out_count,
                       SUM(CASE WHEN current_stock > 0 AND reorder_point > 0
                                  AND current_stock <= reorder_point * %s THEN 1 ELSE 0 END) AS critical_count,
                       SUM(CASE WHEN current_stock > 0 AND reorder_point > 0
                                  AND current_stock > reorder_point * %s
                                  AND current_stock <= reorder_point THEN 1 ELSE 0 END) AS warning_count,
                       COUNT(*) AS total_count
                FROM products p
                {product_where}
                """,
                tuple([crit_ratio, crit_ratio] + product_params)
            )
            st = cur.fetchone()

        status_out = int(st["out_count"] or 0)
        status_critical = int(st["critical_count"] or 0)
        status_warning = int(st["warning_count"] or 0)
        status_total = int(st["total_count"] or 0)
        status_healthy = max(0, status_total - status_out - status_critical - status_warning)

        # --- Warehouse breakdown (1 query instead of 2) ---
        cur.execute(
            f"""
            SELECT COALESCE(warehouse, 'Unassigned') AS warehouse,
                   COUNT(*) AS sku_count,
                   COALESCE(SUM(current_stock), 0) AS units,
                   COALESCE(SUM(current_stock * unit_price), 0) AS value,
                   SUM(CASE WHEN current_stock <= 0 THEN 1 ELSE 0 END) AS out_count,
                   SUM(CASE WHEN current_stock > 0 AND reorder_point > 0
                            AND current_stock <= reorder_point THEN 1 ELSE 0 END) AS low_count,
                   SUM(CASE WHEN current_stock > 0 AND reorder_point > 0
                            AND current_stock > reorder_point THEN 1 ELSE 0 END) AS healthy_count
            FROM products p
            {product_where}
            GROUP BY warehouse ORDER BY value DESC
            """,
            tuple(product_params)
        )
        warehouse_breakdown = list(cur.fetchall())
        warehouse_stock_status = warehouse_breakdown

        # Get distinct warehouses and categories for filter dropdowns (1 query)
        cur.execute(
            "SELECT DISTINCT warehouse, category FROM products "
            "WHERE warehouse IS NOT NULL OR category IS NOT NULL"
        )
        _wc = set()
        _cc = set()
        warehouses = []
        categories = []
        for r in cur.fetchall():
            w = r["warehouse"]
            c = r["category"]
            if w and w not in _wc:
                warehouses.append(w)
                _wc.add(w)
            if c and c not in _cc:
                categories.append(c)
                _cc.add(c)
        warehouses.sort()
        categories.sort()

        # --- 30-day movement series ---
        cur.execute(
            f"""
            SELECT m.created_at::date AS day,
                   COALESCE(SUM(CASE WHEN type = 'IN' THEN quantity ELSE 0 END), 0) AS qty_in,
                   COALESCE(SUM(CASE WHEN type = 'OUT' THEN quantity ELSE 0 END), 0) AS qty_out
            FROM movements m
            JOIN products p ON p.id = m.product_id
            {movement_where}
            {("AND " + " AND ".join(product_conditions)) if product_conditions else ""}
            GROUP BY m.created_at::date ORDER BY day
            """,
            tuple(movement_params + product_params)
        )
        mv_rows = {r["day"]: (int(r["qty_in"] or 0), int(r["qty_out"] or 0))
                   for r in cur.fetchall()}
        # Determine date range for movement labels
        if date_from_start and date_to_end:
            from_dt = date_from_start
            to_dt = date_to_end
        else:
            to_dt = date.today()
            from_dt = to_dt - timedelta(days=29)
        movement = {"labels": [], "in": [], "out": []}
        d = from_dt
        while d <= to_dt:
            qin, qout = mv_rows.get(d, (0, 0))
            movement["labels"].append(d.strftime("%d %b"))
            movement["in"].append(qin)
            movement["out"].append(qout)
            d += timedelta(days=1)

        # --- Top SKUs by inventory value ---
        if date_from_start or date_to_end:
            cur.execute(
                f"""
                SELECT p.sku, p.name, COALESCE(SUM(m.quantity), 0) AS current_stock,
                       p.unit_price, SUM(m.quantity * p.unit_price) AS value
                FROM movements m
                JOIN products p ON p.id = m.product_id
                WHERE m.created_at >= %s AND m.created_at < %s
                {("AND " + " AND ".join(product_conditions)) if product_conditions else ""}
                AND p.unit_price IS NOT NULL
                GROUP BY p.sku, p.name, p.unit_price
                ORDER BY value DESC LIMIT 8
                """,
                tuple([period_start, period_end] + product_params)
            )
        else:
            cur.execute(
                f"""
                SELECT sku, name, current_stock, unit_price,
                       (current_stock * unit_price) AS value
                FROM products p
                {product_where}
                AND unit_price IS NOT NULL
                ORDER BY value DESC LIMIT 8
                """,
                tuple(product_params)
            )
        top_skus = list(cur.fetchall())

        # --- Supplier analytics ---
        cur.execute(
            f"""
            SELECT s.name, s.location, s.reliability, s.lead_days, s.spend_amount,
                   COUNT(p.id) AS product_count
            FROM suppliers s
            LEFT JOIN products p ON p.supplier_id = s.id
            {('WHERE ' + ' AND '.join(product_conditions)) if product_conditions else ''}
            GROUP BY s.id ORDER BY s.spend_amount DESC
            """,
            tuple(product_params)
        )
        supplier_stats = list(cur.fetchall())

        # --- Reorder pressure list + by supplier (1 query instead of 2) ---
        cur.execute(
            f"""
            SELECT p.sku, p.name, p.category, p.warehouse, p.current_stock, p.reorder_point,
                   p.on_order, round(p.current_stock * 1.0 / NULLIF(p.reorder_point, 0), 2) AS coverage,
                   COALESCE(s.name, 'Unassigned') AS supplier_name
            FROM products p
            LEFT JOIN suppliers s ON s.id = p.supplier_id
            {product_where}
            AND p.reorder_point > 0 AND p.current_stock <= p.reorder_point
            ORDER BY coverage ASC LIMIT 12
            """,
            tuple(product_params)
        )
        reorder_rows = list(cur.fetchall())
        reorder_pressure = reorder_rows
        # Derive reorder_by_supplier from the same result set
        _sup_counts = {}
        for r in reorder_rows:
            sn = r["supplier_name"]
            _sup_counts[sn] = _sup_counts.get(sn, 0) + 1
        reorder_by_supplier = [
            {"supplier": k, "skus_below_rop": v}
            for k, v in sorted(_sup_counts.items(), key=lambda x: -x[1])
        ][:10]

        # --- Open POs, supplier count, unders (1 query) + thinnest (separate) ---
        _pc_sub = ('WHERE ' + ' AND '.join(product_conditions)) if product_conditions else 'WHERE 1=1'
        cur.execute(
            f"""
            SELECT
                (SELECT COUNT(*) FROM purchase_orders WHERE status NOT IN ('received','cancelled')) AS open_po,
                (SELECT COUNT(DISTINCT s.id) FROM suppliers s LEFT JOIN products p ON p.supplier_id = s.id {_pc_sub}) AS supplier_count,
                (SELECT COUNT(*) FROM products p {_pc_sub}
                 AND current_stock <= reorder_point AND on_order <= 0) AS unders
            """,
            tuple(product_params + product_params)
        )
        _agg = cur.fetchone()
        open_po = int(_agg["open_po"] or 0)
        supplier_count = int(_agg["supplier_count"] or 0)
        unders = _agg["unders"]

        cur.execute(
            f"""
            SELECT sku, name, current_stock, reorder_point FROM products p
            {_pc_sub}
            AND reorder_point > 0 ORDER BY (current_stock * 1.0 / reorder_point) ASC LIMIT 1
            """,
            tuple(product_params)
        )
        thinnest = cur.fetchone()

        # --- Inventory Health replacements: coverage dist, category coverage, wh turnover ---
        cur.execute(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE reorder_point > 0 AND current_stock < reorder_point * 0.25) AS b_0_25,
                COUNT(*) FILTER (WHERE reorder_point > 0 AND current_stock >= reorder_point * 0.25
                                  AND current_stock < reorder_point * 0.50) AS b_25_50,
                COUNT(*) FILTER (WHERE reorder_point > 0 AND current_stock >= reorder_point * 0.50
                                  AND current_stock < reorder_point * 0.75) AS b_50_75,
                COUNT(*) FILTER (WHERE reorder_point > 0 AND current_stock >= reorder_point * 0.75
                                  AND current_stock <= reorder_point) AS b_75_100,
                COUNT(*) FILTER (WHERE reorder_point > 0 AND current_stock > reorder_point) AS b_over
            FROM products p
            {_pc_sub}
            """,
            tuple(product_params)
        )
        cov = cur.fetchone()
        coverage_distribution = [
            {"bucket": "<25%", "count": int(cov["b_0_25"] or 0)},
            {"bucket": "25-50%", "count": int(cov["b_25_50"] or 0)},
            {"bucket": "50-75%", "count": int(cov["b_50_75"] or 0)},
            {"bucket": "75-100%", "count": int(cov["b_75_100"] or 0)},
            {"bucket": ">100%", "count": int(cov["b_over"] or 0)},
        ]

        cur.execute(
            f"""
            SELECT p.category,
                   COALESCE(SUM(p.current_stock), 0) AS stock_units,
                   COALESCE(SUM(CASE WHEN m.type = 'OUT' THEN m.quantity END) / 90.0, 0) AS daily_out
            FROM products p
            LEFT JOIN movements m ON m.product_id = p.id
                AND m.type = 'OUT' AND m.created_at >= %s
            {product_where}
            AND p.category IS NOT NULL
            GROUP BY p.category
            """,
            tuple([date.today() - timedelta(days=90)] + product_params)
        )
        category_coverage_rows = cur.fetchall()
        category_coverage = [
            {
                "category": r["category"],
                "days": round(float(r["stock_units"] or 0) / float(r["daily_out"] or 0), 0)
                if float(r["daily_out"] or 0) > 0.01 else None,
            }
            for r in category_coverage_rows
        ]

        cur.execute(
            f"""
            SELECT p.warehouse,
                   COALESCE(SUM(CASE WHEN m.type = 'OUT' THEN m.quantity * p.unit_price END), 0) AS cogs,
                   COALESCE(AVG(p.current_stock * p.unit_price), 0) AS avg_inv
            FROM products p
            LEFT JOIN movements m ON m.product_id = p.id
                AND m.type = 'OUT' AND m.created_at >= %s
            {product_where}
            AND p.warehouse IS NOT NULL AND p.unit_price IS NOT NULL
            GROUP BY p.warehouse
            """,
            tuple([date.today() - timedelta(days=365)] + product_params)
        )
        wh_turnover_rows = cur.fetchall()
        warehouse_turnover = [
            {
                "warehouse": r["warehouse"],
                "turnover": round(float(r["cogs"] or 0) / float(r["avg_inv"] or 0), 2)
                if float(r["avg_inv"] or 0) > 10 else 0,
            }
            for r in wh_turnover_rows
        ]

        # --- Stock aging buckets (Executive Summary) ---
        cur.execute(
            f"""
            WITH last_out AS (
                SELECT product_id, MAX(created_at) AS ts
                FROM movements WHERE type = 'OUT' GROUP BY product_id
            )
            SELECT
                COALESCE(SUM(p.current_stock * p.unit_price) FILTER (
                    WHERE COALESCE(lo.ts, p.created_at) >= %s), 0) AS fresh,
                COALESCE(SUM(p.current_stock * p.unit_price) FILTER (
                    WHERE COALESCE(lo.ts, p.created_at) < %s
                      AND COALESCE(lo.ts, p.created_at) >= %s), 0) AS mid,
                COALESCE(SUM(p.current_stock * p.unit_price) FILTER (
                    WHERE COALESCE(lo.ts, p.created_at) < %s), 0) AS old
            FROM products p
            LEFT JOIN last_out lo ON lo.product_id = p.id
            {_pc_sub}
            """,
            tuple([date.today() - timedelta(days=30),
                   date.today() - timedelta(days=30), date.today() - timedelta(days=90),
                   date.today() - timedelta(days=90)] + product_params)
        )
        _age = cur.fetchone()
        stock_aging = {
            "labels": ["0-30 days", "31-90 days", "90+ days"],
            "values": [round(float(_age["fresh"] or 0)), round(float(_age["mid"] or 0)), round(float(_age["old"] or 0))],
        }

        # --- Reorder value gap by category (Inventory Health) ---
        cur.execute(
            f"""
            SELECT p.category,
                   COALESCE(SUM(GREATEST(p.reorder_point - p.current_stock, 0) * p.unit_price), 0) AS gap_value
            FROM products p
            {product_where}
            AND p.reorder_point > 0 AND p.current_stock < p.reorder_point AND p.category IS NOT NULL
            GROUP BY p.category ORDER BY gap_value DESC
            """,
            tuple(product_params)
        )
        gap_rows = cur.fetchall()
        reorder_value_gap = {
            "labels": [r["category"] for r in gap_rows],
            "values": [round(float(r["gap_value"] or 0)) for r in gap_rows],
        }

        # --- Top SKUs by movement activity, last 30 days (Executive Summary) ---
        cur.execute(
            f"""
            SELECT p.sku, p.name, COALESCE(SUM(m.quantity), 0) AS units
            FROM products p
            JOIN movements m ON m.product_id = p.id
                AND m.created_at >= %s
            {product_where}
            GROUP BY p.id, p.sku, p.name
            ORDER BY units DESC LIMIT 10
            """,
            tuple([date.today() - timedelta(days=30)] + product_params)
        )
        active_rows = cur.fetchall()
        top_active_skus = {
            "labels": [r["sku"] for r in active_rows],
            "values": [int(r["units"] or 0) for r in active_rows],
        }

        # --- SKU idle-days distribution (Inventory Health) ---
        cur.execute(
            f"""
            WITH last_move AS (
                SELECT product_id, MAX(created_at) AS ts
                FROM movements GROUP BY product_id
            )
            SELECT
                COUNT(*) FILTER (WHERE COALESCE(lm.ts, p.created_at) >= %s) AS fresh,
                COUNT(*) FILTER (WHERE COALESCE(lm.ts, p.created_at) < %s
                                  AND COALESCE(lm.ts, p.created_at) >= %s) AS mid,
                COUNT(*) FILTER (WHERE COALESCE(lm.ts, p.created_at) < %s
                                  AND COALESCE(lm.ts, p.created_at) >= %s) AS stale,
                COUNT(*) FILTER (WHERE COALESCE(lm.ts, p.created_at) < %s) AS dead
            FROM products p
            LEFT JOIN last_move lm ON lm.product_id = p.id
            {_pc_sub}
            """,
            tuple([date.today() - timedelta(days=7),
                   date.today() - timedelta(days=7), date.today() - timedelta(days=30),
                   date.today() - timedelta(days=30), date.today() - timedelta(days=90),
                   date.today() - timedelta(days=90)] + product_params)
        )
        _idle = cur.fetchone()
        idle_distribution = {
            "labels": ["0-7 days", "8-30 days", "31-90 days", "90+ days"],
            "values": [int(_idle["fresh"] or 0), int(_idle["mid"] or 0),
                       int(_idle["stale"] or 0), int(_idle["dead"] or 0)],
        }

    # --- Performance Trends: fixed-period metrics (respect warehouse/category filters) ---
    today = date.today()
    mtd_start = today.replace(day=1)
    prev_mtd_start = (mtd_start - timedelta(days=1)).replace(day=1)
    ytd_start = today.replace(month=1, day=1)
    prev_ytd_start = date(today.year - 1, 1, 1)
    prev_ytd_end = date(today.year - 1, today.month, today.day) + timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    with get_cursor() as cur:
        # Combined period metrics in one query (MTD, YTD, prev MTD, prev YTD)
        cur.execute(
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN m.type = 'IN' AND m.created_at >= %s AND m.created_at < %s THEN m.quantity ELSE 0 END), 0) AS mtd_units_in,
                COALESCE(SUM(CASE WHEN m.type = 'OUT' AND m.created_at >= %s AND m.created_at < %s THEN m.quantity ELSE 0 END), 0) AS mtd_units_out,
                COALESCE(SUM(CASE WHEN m.type = 'IN' AND m.created_at >= %s AND m.created_at < %s THEN m.quantity * p.unit_price ELSE 0 END), 0) AS mtd_value_in,
                COALESCE(SUM(CASE WHEN m.type = 'OUT' AND m.created_at >= %s AND m.created_at < %s THEN m.quantity * p.unit_price ELSE 0 END), 0) AS mtd_value_out,
                COUNT(DISTINCT CASE WHEN m.created_at >= %s AND m.created_at < %s THEN m.product_id END) AS mtd_skus,

                COALESCE(SUM(CASE WHEN m.type = 'IN' AND m.created_at >= %s AND m.created_at < %s THEN m.quantity ELSE 0 END), 0) AS ytd_units_in,
                COALESCE(SUM(CASE WHEN m.type = 'OUT' AND m.created_at >= %s AND m.created_at < %s THEN m.quantity ELSE 0 END), 0) AS ytd_units_out,
                COALESCE(SUM(CASE WHEN m.type = 'IN' AND m.created_at >= %s AND m.created_at < %s THEN m.quantity * p.unit_price ELSE 0 END), 0) AS ytd_value_in,
                COALESCE(SUM(CASE WHEN m.type = 'OUT' AND m.created_at >= %s AND m.created_at < %s THEN m.quantity * p.unit_price ELSE 0 END), 0) AS ytd_value_out,
                COUNT(DISTINCT CASE WHEN m.created_at >= %s AND m.created_at < %s THEN m.product_id END) AS ytd_skus,

                COALESCE(SUM(CASE WHEN m.type = 'IN' AND m.created_at >= %s AND m.created_at < %s THEN m.quantity ELSE 0 END), 0) AS prev_mtd_units_in,
                COALESCE(SUM(CASE WHEN m.type = 'OUT' AND m.created_at >= %s AND m.created_at < %s THEN m.quantity ELSE 0 END), 0) AS prev_mtd_units_out,
                COALESCE(SUM(CASE WHEN m.type = 'IN' AND m.created_at >= %s AND m.created_at < %s THEN m.quantity * p.unit_price ELSE 0 END), 0) AS prev_mtd_value_in,
                COALESCE(SUM(CASE WHEN m.type = 'OUT' AND m.created_at >= %s AND m.created_at < %s THEN m.quantity * p.unit_price ELSE 0 END), 0) AS prev_mtd_value_out,
                COUNT(DISTINCT CASE WHEN m.created_at >= %s AND m.created_at < %s THEN m.product_id END) AS prev_mtd_skus,

                COALESCE(SUM(CASE WHEN m.type = 'IN' AND m.created_at >= %s AND m.created_at < %s THEN m.quantity ELSE 0 END), 0) AS prev_ytd_units_in,
                COALESCE(SUM(CASE WHEN m.type = 'OUT' AND m.created_at >= %s AND m.created_at < %s THEN m.quantity ELSE 0 END), 0) AS prev_ytd_units_out,
                COALESCE(SUM(CASE WHEN m.type = 'IN' AND m.created_at >= %s AND m.created_at < %s THEN m.quantity * p.unit_price ELSE 0 END), 0) AS prev_ytd_value_in,
                COALESCE(SUM(CASE WHEN m.type = 'OUT' AND m.created_at >= %s AND m.created_at < %s THEN m.quantity * p.unit_price ELSE 0 END), 0) AS prev_ytd_value_out,
                COUNT(DISTINCT CASE WHEN m.created_at >= %s AND m.created_at < %s THEN m.product_id END) AS prev_ytd_skus
            FROM movements m
            JOIN products p ON p.id = m.product_id
            WHERE (m.created_at >= %s AND m.created_at < %s) {filter_clause}
            """,
            tuple([
                mtd_start, tomorrow, mtd_start, tomorrow, mtd_start, tomorrow, mtd_start, tomorrow, mtd_start, tomorrow,
                ytd_start, tomorrow, ytd_start, tomorrow, ytd_start, tomorrow, ytd_start, tomorrow, ytd_start, tomorrow,
                prev_mtd_start, mtd_start, prev_mtd_start, mtd_start, prev_mtd_start, mtd_start, prev_mtd_start, mtd_start, prev_mtd_start, mtd_start,
                prev_ytd_start, prev_ytd_end, prev_ytd_start, prev_ytd_end, prev_ytd_start, prev_ytd_end, prev_ytd_start, prev_ytd_end, prev_ytd_start, prev_ytd_end,
                prev_ytd_start, tomorrow,
            ] + filter_params),
        )
        period_row = cur.fetchone()

        mtd_row = {
            "units_in": period_row["mtd_units_in"], "units_out": period_row["mtd_units_out"],
            "value_in": period_row["mtd_value_in"], "value_out": period_row["mtd_value_out"],
            "skus": period_row["mtd_skus"],
        }
        ytd_row = {
            "units_in": period_row["ytd_units_in"], "units_out": period_row["ytd_units_out"],
            "value_in": period_row["ytd_value_in"], "value_out": period_row["ytd_value_out"],
            "skus": period_row["ytd_skus"],
        }
        prev_mtd_row = {
            "units_in": period_row["prev_mtd_units_in"], "units_out": period_row["prev_mtd_units_out"],
            "value_in": period_row["prev_mtd_value_in"], "value_out": period_row["prev_mtd_value_out"],
            "skus": period_row["prev_mtd_skus"],
        }
        prev_ytd_row = {
            "units_in": period_row["prev_ytd_units_in"], "units_out": period_row["prev_ytd_units_out"],
            "value_in": period_row["prev_ytd_value_in"], "value_out": period_row["prev_ytd_value_out"],
            "skus": period_row["prev_ytd_skus"],
        }

        # Combined PO period metrics
        cur.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN created_at >= %s AND created_at < %s THEN quantity * unit_cost ELSE 0 END), 0) AS mtd_value,
                COUNT(CASE WHEN created_at >= %s AND created_at < %s THEN 1 END) AS mtd_c,
                COALESCE(SUM(CASE WHEN created_at >= %s AND created_at < %s THEN quantity * unit_cost ELSE 0 END), 0) AS ytd_value,
                COUNT(CASE WHEN created_at >= %s AND created_at < %s THEN 1 END) AS ytd_c,
                COALESCE(SUM(CASE WHEN created_at >= %s AND created_at < %s THEN quantity * unit_cost ELSE 0 END), 0) AS prev_mtd_value,
                COUNT(CASE WHEN created_at >= %s AND created_at < %s THEN 1 END) AS prev_mtd_c,
                COALESCE(SUM(CASE WHEN created_at >= %s AND created_at < %s THEN quantity * unit_cost ELSE 0 END), 0) AS prev_ytd_value,
                COUNT(CASE WHEN created_at >= %s AND created_at < %s THEN 1 END) AS prev_ytd_c
            FROM purchase_orders
            WHERE created_at >= %s AND created_at < %s
            """,
            tuple([
                mtd_start, tomorrow, mtd_start, tomorrow,
                ytd_start, tomorrow, ytd_start, tomorrow,
                prev_mtd_start, mtd_start, prev_mtd_start, mtd_start,
                prev_ytd_start, prev_ytd_end, prev_ytd_start, prev_ytd_end,
                prev_ytd_start, tomorrow,
            ]),
        )
        po_row = cur.fetchone()

        mtd_po_row = {"value": po_row["mtd_value"], "c": po_row["mtd_c"]}
        ytd_po_row = {"value": po_row["ytd_value"], "c": po_row["ytd_c"]}
        prev_mtd_po_row = {"value": po_row["prev_mtd_value"], "c": po_row["prev_mtd_c"]}
        prev_ytd_po_row = {"value": po_row["prev_ytd_value"], "c": po_row["prev_ytd_c"]}

        def _period_dict(row, po_row):
            return {
                "units_in": int(row["units_in"] or 0),
                "units_out": int(row["units_out"] or 0),
                "net": int((row["units_in"] or 0) - (row["units_out"] or 0)),
                "value_in": float(row["value_in"] or 0),
                "value_out": float(row["value_out"] or 0),
                "skus": int(row["skus"] or 0),
                "po_value": float(po_row["value"] or 0),
                "po_count": int(po_row["c"] or 0),
            }

        mtd = _period_dict(mtd_row, mtd_po_row)
        ytd = _period_dict(ytd_row, ytd_po_row)
        prev_mtd = _period_dict(prev_mtd_row, prev_mtd_po_row)
        prev_ytd = _period_dict(prev_ytd_row, prev_ytd_po_row)

        # --- Year-wise inventory value moved (chart 1) ---
        cur.execute(
            f"""
            SELECT EXTRACT(YEAR FROM m.created_at)::int AS yr,
                   COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.quantity ELSE 0 END), 0) AS in_qty,
                   COALESCE(SUM(CASE WHEN m.type = 'OUT' THEN m.quantity ELSE 0 END), 0) AS out_qty,
                   COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.quantity * p.unit_price ELSE 0 END), 0) AS in_value,
                   COALESCE(SUM(CASE WHEN m.type = 'OUT' THEN m.quantity * p.unit_price ELSE 0 END), 0) AS out_value
            FROM movements m
            JOIN products p ON p.id = m.product_id
            WHERE p.unit_price IS NOT NULL {filter_clause}
            GROUP BY 1 ORDER BY 1
            """,
            tuple(filter_params),
        )
        year_rows = list(cur.fetchall())
        year_series = {
            "labels": [int(r["yr"]) for r in year_rows],
            "in": [round(float(r["in_value"] or 0)) for r in year_rows],
            "out": [round(float(r["out_value"] or 0)) for r in year_rows],
        }

        # --- YTD current year vs YTD previous year, cumulative by month (chart 2) ---
        cur.execute(
            f"""
            SELECT EXTRACT(YEAR FROM m.created_at)::int AS yr,
                   EXTRACT(MONTH FROM m.created_at)::int AS mo,
                   COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.quantity * p.unit_price ELSE 0 END), 0) AS in_value,
                   COALESCE(SUM(CASE WHEN m.type = 'OUT' THEN m.quantity * p.unit_price ELSE 0 END), 0) AS out_value
            FROM movements m
            JOIN products p ON p.id = m.product_id
            WHERE p.unit_price IS NOT NULL
              AND m.created_at >= DATE_TRUNC('year', NOW()) - INTERVAL '1 year' {filter_clause}
            GROUP BY 1, 2 ORDER BY 1, 2
            """,
            tuple(filter_params),
        )
        month_value = {(r["yr"], r["mo"]): float(r["in_value"] or 0) + float(r["out_value"] or 0)
                       for r in cur.fetchall()}
        cur_year = today.year
        prev_year = today.year - 1
        ytd_compare = {"labels": [], "current": [], "previous": []}
        cum_cur = 0.0
        cum_prev = 0.0
        for mo in range(1, today.month + 1):
            ytd_compare["labels"].append(date(2000, mo, 1).strftime("%b"))
            cum_cur += month_value.get((cur_year, mo), 0.0)
            cum_prev += month_value.get((prev_year, mo), 0.0)
            ytd_compare["current"].append(round(cum_cur))
            ytd_compare["previous"].append(round(cum_prev))

        # --- Current month vs previous month value by category (all + OUT only, 1 query) ---
        cur.execute(
            f"""
            SELECT p.category,
                   COALESCE(SUM(CASE WHEN m.created_at >= %s AND m.created_at < %s
                                     THEN m.quantity * p.unit_price ELSE 0 END), 0) AS cur,
                   COALESCE(SUM(CASE WHEN m.created_at >= %s AND m.created_at < %s
                                     THEN m.quantity * p.unit_price ELSE 0 END), 0) AS prev,
                   COALESCE(SUM(CASE WHEN m.type = 'OUT' AND m.created_at >= %s AND m.created_at < %s
                                     THEN m.quantity * p.unit_price ELSE 0 END), 0) AS sales_cur,
                   COALESCE(SUM(CASE WHEN m.type = 'OUT' AND m.created_at >= %s AND m.created_at < %s
                                     THEN m.quantity * p.unit_price ELSE 0 END), 0) AS sales_prev
            FROM movements m
            JOIN products p ON p.id = m.product_id
            WHERE p.category IS NOT NULL AND p.unit_price IS NOT NULL {filter_clause}
            GROUP BY p.category ORDER BY cur DESC
            """,
            tuple([mtd_start, tomorrow, prev_mtd_start, mtd_start,
                   mtd_start, tomorrow, prev_mtd_start, mtd_start] + filter_params),
        )
        month_compare = list(cur.fetchall())
        sales_month_compare = month_compare

        # --- SKU count per category ---
        cur.execute(
            f"""
            SELECT category, COUNT(*) AS c FROM products p
            {product_where}
            AND category IS NOT NULL
            GROUP BY category ORDER BY c DESC
            """,
            tuple(product_params),
        )
        category_counts = list(cur.fetchall())

        # --- Top products by value (product analysis) ---
        cur.execute(
            f"""
            SELECT sku, name, category, warehouse, current_stock, reorder_point, unit_price,
                   (current_stock * unit_price) AS value
            FROM products p
            {product_where}
            AND unit_price IS NOT NULL
            ORDER BY value DESC LIMIT 12
            """,
            tuple(product_params),
        )
        product_rows = list(cur.fetchall())

        # --- Purchase order status + open POs (1 query instead of 2) ---
        cur.execute(
            """
            SELECT status, COUNT(*) AS c, COALESCE(SUM(quantity * unit_cost), 0) AS value
            FROM purchase_orders GROUP BY status ORDER BY value DESC
            """
        )
        po_status = list(cur.fetchall())
        po_value = sum(
            float(r["value"] or 0) for r in po_status
            if r["status"] not in ("received", "cancelled")
        )
        # Open POs derived from same table — already fetched status; just get detail
        cur.execute(
            """
            SELECT po.po_number, po.status, po.quantity, po.unit_cost, po.eta_date,
                   s.name AS supplier_name, p.name AS product_name, p.sku,
                   (po.quantity * po.unit_cost) AS value
            FROM purchase_orders po
            LEFT JOIN suppliers s ON s.id = po.supplier_id
            LEFT JOIN products p ON p.id = po.product_id
            WHERE po.status NOT IN ('received', 'cancelled')
            ORDER BY po.eta_date ASC LIMIT 12
            """
        )
        open_pos = list(cur.fetchall())

        # --- Warehouse analytics (star schema) + movement summary ---
        warehouse_analytics = WarehouseRepository.analytics() or []
        warehouse_movement = WarehouseRepository.movement_summary(30)
        if not warehouse_analytics:
            warehouse_analytics = [
                {
                    "warehouse": r["warehouse"],
                    "warehouse_code": r["warehouse"],
                    "city": "",
                    "region": "",
                    "sku_count": int(r["sku_count"] or 0),
                    "total_units": int(r["units"] or 0),
                    "total_value": float(r["value"] or 0),
                    "low_count": 0,
                    "critical_count": 0,
                }
                for r in warehouse_breakdown
            ]

        # --- Reorder pressure by category ---
        cur.execute(
            f"""
            SELECT category,
                   SUM(CASE WHEN reorder_point > 0 AND current_stock <= reorder_point
                            THEN 1 ELSE 0 END) AS below,
                   COUNT(*) AS total
            FROM products p
            {product_where}
            AND category IS NOT NULL
            GROUP BY category ORDER BY below DESC
            """,
            tuple(product_params),
        )
        reorder_by_category = list(cur.fetchall())

        # --- 12-month movement + sales trend (1 query instead of 2) ---
        cur.execute(
            f"""
            SELECT DATE_TRUNC('month', m.created_at)::date AS month,
                   COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.quantity ELSE 0 END), 0) AS in_qty,
                   COALESCE(SUM(CASE WHEN m.type = 'OUT' THEN m.quantity ELSE 0 END), 0) AS out_qty,
                   COALESCE(SUM(CASE WHEN m.type = 'OUT' THEN m.quantity * p.unit_price ELSE 0 END), 0) AS out_value,
                   COALESCE(SUM(CASE WHEN m.type = 'OUT' THEN m.quantity ELSE 0 END), 0) AS out_units
            FROM movements m
            JOIN products p ON p.id = m.product_id
            WHERE m.created_at >= DATE_TRUNC('month', NOW()) - INTERVAL '11 months'
              AND p.unit_price IS NOT NULL {filter_clause}
            GROUP BY 1 ORDER BY 1
            """,
            tuple(filter_params),
        )
        monthly_rows = {r["month"]: r for r in cur.fetchall()}
        month_cursor = today.replace(day=1)
        month_labels = []
        for _ in range(12):
            month_labels.append(month_cursor)
            month_cursor = (month_cursor - timedelta(days=1)).replace(day=1)
        month_labels.reverse()
        monthly_series = {"labels": [], "in": [], "out": []}
        for lm in month_labels:
            row = monthly_rows.get(lm)
            monthly_series["labels"].append(lm.strftime("%b %y"))
            monthly_series["in"].append(int((row["in_qty"] or 0)) if row else 0)
            monthly_series["out"].append(int((row["out_qty"] or 0)) if row else 0)

        movement_caption = (
            f"from {date_from_start.strftime('%b %Y')} to {date_to_end.strftime('%b %Y')}"
            if date_from_start and date_to_end
            else "over the last 30 days"
        )

        # --- Sales analysis: OUT movements = sales ---
        # Combined period order counts (1 query instead of 4)
        cur.execute(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE m.created_at >= %s AND m.created_at < %s) AS mtd_orders,
                COUNT(*) FILTER (WHERE m.created_at >= %s AND m.created_at < %s) AS ytd_orders,
                COUNT(*) FILTER (WHERE m.created_at >= %s AND m.created_at < %s) AS prev_mtd_orders,
                COUNT(*) FILTER (WHERE m.created_at >= %s AND m.created_at < %s) AS prev_ytd_orders
            FROM movements m
            JOIN products p ON p.id = m.product_id
            WHERE m.type = 'OUT' {filter_clause}
            """,
            tuple([
                mtd_start, tomorrow,
                ytd_start, tomorrow,
                prev_mtd_start, mtd_start,
                prev_ytd_start, prev_ytd_end,
            ] + filter_params),
        )
        order_counts = cur.fetchone()

        sales = {
            "mtd": {
                "revenue": round(mtd["value_out"]),
                "units": mtd["units_out"],
                "orders": int(order_counts["mtd_orders"] or 0),
            },
            "ytd": {
                "revenue": round(ytd["value_out"]),
                "units": ytd["units_out"],
                "orders": int(order_counts["ytd_orders"] or 0),
            },
            "prev_mtd": {
                "revenue": round(prev_mtd["value_out"]),
                "units": prev_mtd["units_out"],
                "orders": int(order_counts["prev_mtd_orders"] or 0),
            },
            "prev_ytd": {
                "revenue": round(prev_ytd["value_out"]),
                "units": prev_ytd["units_out"],
                "orders": int(order_counts["prev_ytd_orders"] or 0),
            },
        }

        # --- Month-wise sales revenue from Jan 2024 through today (OUT only) ---
        cur.execute(
            f"""
            SELECT DATE_TRUNC('month', m.created_at)::date AS month,
                   COALESCE(SUM(m.quantity), 0) AS units,
                   COALESCE(SUM(m.quantity * p.unit_price), 0) AS value
            FROM movements m
            JOIN products p ON p.id = m.product_id
            WHERE m.type = 'OUT' AND p.unit_price IS NOT NULL
              AND m.created_at >= '2024-01-01' {filter_clause}
            GROUP BY 1 ORDER BY 1
            """,
            tuple(filter_params),
        )
        sales_monthly_all = list(cur.fetchall())

        # Year-wise totals (compare each year).
        year_agg: dict[int, dict] = {}
        for r in sales_monthly_all:
            yr = r["month"].year
            year_agg.setdefault(yr, {"value": 0.0, "units": 0})
            year_agg[yr]["value"] += float(r["value"] or 0)
            year_agg[yr]["units"] += int(r["units"] or 0)
        sales_year_series = {
            "labels": [str(yr) for yr in sorted(year_agg)],
            "out": [round(year_agg[yr]["value"]) for yr in sorted(year_agg)],
            "units": [year_agg[yr]["units"] for yr in sorted(year_agg)],
        }

        # Monthly sales per year — drives the year selector on the month chart.
        months_by_year: dict[int, dict] = {}
        for r in sales_monthly_all:
            yr = r["month"].year
            months_by_year.setdefault(yr, {"labels": [], "value": [], "units": []})
            months_by_year[yr]["labels"].append(r["month"].strftime("%b"))
            months_by_year[yr]["value"].append(round(float(r["value"] or 0)))
            months_by_year[yr]["units"].append(int(r["units"] or 0))
        sales_months_by_year = months_by_year
        sales_years = sorted(months_by_year)

        # Quarter-wise sales trend.
        q_agg: dict[tuple[int, int], dict] = {}
        for r in sales_monthly_all:
            qkey = (r["month"].year, (r["month"].month - 1) // 3 + 1)
            q_agg.setdefault(qkey, {"value": 0.0, "units": 0})
            q_agg[qkey]["value"] += float(r["value"] or 0)
            q_agg[qkey]["units"] += int(r["units"] or 0)
        sales_quarter_series = {
            "labels": [f"Q{q} {yr}" for (yr, q) in sorted(q_agg)],
            "value": [round(v["value"]) for v in q_agg.values()],
            "units": [v["units"] for v in q_agg.values()],
        }

        # Current quarter vs previous quarter sales by category.
        cur_q = (today.month - 1) // 3 + 1
        cur_q_start = date(today.year, (cur_q - 1) * 3 + 1, 1)
        prev_q_month = cur_q_start.month - 3
        prev_q_year = cur_q_start.year
        if prev_q_month <= 0:
            prev_q_month += 12
            prev_q_year -= 1
        prev_q_start = date(prev_q_year, prev_q_month, 1)
        cur.execute(
            f"""
            SELECT p.category,
                   COALESCE(SUM(CASE WHEN m.created_at >= %s AND m.created_at < %s
                                     THEN m.quantity * p.unit_price ELSE 0 END), 0) AS cur,
                   COALESCE(SUM(CASE WHEN m.created_at >= %s AND m.created_at < %s
                                     THEN m.quantity * p.unit_price ELSE 0 END), 0) AS prev
            FROM movements m
            JOIN products p ON p.id = m.product_id
            WHERE m.type = 'OUT' AND p.category IS NOT NULL AND p.unit_price IS NOT NULL {filter_clause}
            GROUP BY p.category ORDER BY cur DESC
            """,
            tuple([cur_q_start, tomorrow, prev_q_start, cur_q_start] + filter_params),
        )
        sales_quarter_compare = list(cur.fetchall())

        # --- YTD cumulative sales for the last 3 years (2024, 2025, 2026) ---
        cur.execute(
            f"""
            SELECT EXTRACT(YEAR FROM m.created_at)::int AS yr,
                   EXTRACT(MONTH FROM m.created_at)::int AS mo,
                   COALESCE(SUM(m.quantity * p.unit_price), 0) AS out_value
            FROM movements m
            JOIN products p ON p.id = m.product_id
            WHERE m.type = 'OUT' AND p.unit_price IS NOT NULL
              AND EXTRACT(YEAR FROM m.created_at) BETWEEN %s AND %s {filter_clause}
            GROUP BY 1, 2 ORDER BY 1, 2
            """,
            tuple([today.year - 2, today.year] + filter_params),
        )
        sales_month_value = {(r["yr"], r["mo"]): float(r["out_value"] or 0)
                             for r in cur.fetchall()}
        ytd_years = [today.year - 2, today.year - 1, today.year]
        sales_ytd_compare = {
            "labels": [date(2000, mo, 1).strftime("%b") for mo in range(1, today.month + 1)],
            "series": [],
        }
        for yr in ytd_years:
            cum = 0.0
            data = []
            for mo in range(1, today.month + 1):
                cum += sales_month_value.get((yr, mo), 0.0)
                data.append(round(cum))
            sales_ytd_compare["series"].append({"year": yr, "data": data})

        # --- QTD cumulative sales for the last 3 years (2024, 2025, 2026) ---
        sales_qtd_compare = {
            "labels": [f"Q{q}" for q in range(1, cur_q + 1)],
            "series": [],
        }
        for yr in ytd_years:
            cum = 0.0
            data = []
            for q in range(1, cur_q + 1):
                for mo in range((q - 1) * 3 + 1, q * 3 + 1):
                    cum += sales_month_value.get((yr, mo), 0.0)
                data.append(round(cum))
            sales_qtd_compare["series"].append({"year": yr, "data": data})

        # sales_month_compare derived from merged month_compare query above

        # 12-month sales trend derived from merged query above
        sales_monthly_rows = monthly_rows
        sales_monthly_series = {"labels": [], "value": [], "units": []}
        for lm in month_labels:
            row = sales_monthly_rows.get(lm)
            sales_monthly_series["labels"].append(lm.strftime("%b %y"))
            sales_monthly_series["value"].append(round(float(row["out_value"] or 0)) if row else 0)
            sales_monthly_series["units"].append(int(row["out_units"] or 0) if row else 0)

        # --- Sales by warehouse ---
        cur.execute(
            f"""
            SELECT COALESCE(p.warehouse, 'Unassigned') AS warehouse,
                   COALESCE(SUM(m.quantity), 0) AS units,
                   COALESCE(SUM(m.quantity * p.unit_price), 0) AS value
            FROM movements m
            JOIN products p ON p.id = m.product_id
            WHERE m.type = 'OUT' AND p.warehouse IS NOT NULL AND p.unit_price IS NOT NULL {filter_clause}
            GROUP BY p.warehouse ORDER BY value DESC
            """,
            tuple(filter_params),
        )
        sales_warehouse = list(cur.fetchall())

        # --- Category revenue mix, monthly (stacked area trend) ---
        cur.execute(
            f"""
            SELECT DATE_TRUNC('month', m.created_at)::date AS month,
                   p.category,
                   COALESCE(SUM(m.quantity * p.unit_price), 0) AS value
            FROM movements m
            JOIN products p ON p.id = m.product_id
            WHERE m.type = 'OUT' AND p.category IS NOT NULL
                  AND p.unit_price IS NOT NULL AND m.created_at >= %s {filter_clause}
            GROUP BY month, p.category
            """,
            tuple([date.today() - timedelta(days=365)] + filter_params),
        )
        _mix_rows = cur.fetchall()
        _mix_by_month = {}
        _mix_categories = set()
        for r in _mix_rows:
            _mix_by_month.setdefault(r["month"], {})[r["category"]] = round(float(r["value"] or 0))
            _mix_categories.add(r["category"])
        _ordered_cats = sorted(_mix_categories)
        category_mix_trend = {"labels": [], "categories": _ordered_cats, "series": []}
        for lm in month_labels:
            row = _mix_by_month.get(lm, {})
            category_mix_trend["labels"].append(lm.strftime("%b %y"))
            category_mix_trend["series"].append([row.get(c, 0) for c in _ordered_cats])

        # --- Top selling products ---
        cur.execute(
            f"""
            SELECT p.sku, p.name, p.category,
                   COALESCE(SUM(m.quantity), 0) AS units,
                   COALESCE(SUM(m.quantity * p.unit_price), 0) AS value
            FROM movements m
            JOIN products p ON p.id = m.product_id
            WHERE m.type = 'OUT' AND p.unit_price IS NOT NULL {filter_clause}
            GROUP BY p.sku, p.name, p.category
            ORDER BY value DESC LIMIT 12
            """,
            tuple(filter_params),
        )
        top_sellers = list(cur.fetchall())

        # --- Monthly PO spend trend (last 12 months) ---
        cur.execute(
            """
            SELECT DATE_TRUNC('month', created_at)::date AS month,
                   COALESCE(SUM(quantity * unit_cost), 0) AS spend,
                   COUNT(*) AS po_count
            FROM purchase_orders
            WHERE created_at >= DATE_TRUNC('month', NOW()) - INTERVAL '11 months'
              AND status NOT IN ('cancelled')
            GROUP BY 1 ORDER BY 1
            """
        )
        po_monthly_rows = {r["month"]: r for r in cur.fetchall()}
        po_month_cursor = today.replace(day=1)
        po_month_labels = []
        for _ in range(12):
            po_month_labels.append(po_month_cursor)
            po_month_cursor = (po_month_cursor - timedelta(days=1)).replace(day=1)
        po_month_labels.reverse()
        po_monthly_trend = {"labels": [], "spend": [], "count": []}
        for lm in po_month_labels:
            row = po_monthly_rows.get(lm)
            po_monthly_trend["labels"].append(lm.strftime("%b %y"))
            po_monthly_trend["spend"].append(round(float(row["spend"] or 0)) if row else 0)
            po_monthly_trend["count"].append(int(row["po_count"] or 0) if row else 0)

        # --- Supplier lead time distribution ---
        cur.execute(
            """
            SELECT s.name, s.lead_days, s.reliability,
                   COUNT(p.id) AS product_count
            FROM suppliers s
            LEFT JOIN products p ON p.supplier_id = s.id
            GROUP BY s.id ORDER BY s.lead_days ASC
            """
        )
        supplier_lead_times = list(cur.fetchall())

        # --- Warehouse SKU count + stock status per warehouse ---
        # Already computed above as part of warehouse_breakdown

    report_data = {
        "status": {
            "labels": ["Healthy", "Low stock", "Critical", "Out of stock"],
            "values": [status_healthy, status_warning, status_critical, status_out],
        },
        "warehouse": {
            "labels": [r["warehouse"] for r in warehouse_breakdown],
            "values": [round(float(r["value"] or 0)) for r in warehouse_breakdown],
        },
        "movement": movement,
        "monthly": monthly_series,
        "topSkus": {
            "labels": [r["sku"] for r in top_skus],
            "values": [round(float(r["value"] or 0)) for r in top_skus],
        },
        "category": {
            "labels": [r["category"] for r in breakdown],
            "values": [round(float(r["value"] or 0)) for r in breakdown],
        },
        "warehouseMovement": {
            "labels": [r["warehouse"] for r in warehouse_movement],
            "in": [int(r["in_qty"] or 0) for r in warehouse_movement],
            "out": [int(r["out_qty"] or 0) for r in warehouse_movement],
        },
        "supplierSpend": {
            "labels": [r["name"] for r in supplier_stats],
            "values": [round(float(r["spend_amount"] or 0)) for r in supplier_stats],
        },
        "poStatus": {
            "labels": [r["status"].replace("_", " ").title() for r in po_status],
            "values": [int(r["c"] or 0) for r in po_status],
        },
        "year": year_series,
        "ytdCompare": ytd_compare,
        "monthCompare": {
            "labels": [r["category"] for r in month_compare],
            "current": [round(float(r["cur"] or 0)) for r in month_compare],
            "previous": [round(float(r["prev"] or 0)) for r in month_compare],
        },
        "reorderCategory": {
            "labels": [r["category"] for r in reorder_by_category],
            "below": [int(r["below"] or 0) for r in reorder_by_category],
        },
        "reorderSupplier": {
            "labels": [r["supplier"] for r in reorder_by_supplier],
            "values": [int(r["skus_below_rop"] or 0) for r in reorder_by_supplier],
        },
        "coverageDistribution": coverage_distribution,
        "categoryCoverage": category_coverage,
        "warehouseTurnover": warehouse_turnover,
        "stockAging": stock_aging,
        "reorderValueGap": reorder_value_gap,
        "topActiveSkus": top_active_skus,
        "idleDistribution": idle_distribution,
        "warehouseUnits": {
            "labels": [r["warehouse"] for r in warehouse_stock_status],
            "units": [int(r["units"] or 0) for r in warehouse_stock_status],
            "value": [round(float(r["value"] or 0)) for r in warehouse_stock_status],
        },
        "salesYear": sales_year_series,
        "salesYtdCompare": sales_ytd_compare,
        "salesQtdCompare": sales_qtd_compare,
        "salesMonthsByYear": sales_months_by_year,
        "salesYears": sales_years,
        "salesQuarter": sales_quarter_series,
        "salesQuarterCompare": {
            "labels": [r["category"] for r in sales_quarter_compare],
            "current": [round(float(r["cur"] or 0)) for r in sales_quarter_compare],
            "previous": [round(float(r["prev"] or 0)) for r in sales_quarter_compare],
        },
        "salesMonthly": sales_monthly_series,
        "categoryMixTrend": category_mix_trend,
        "salesMonthCompare": {
            "labels": [r["category"] for r in sales_month_compare],
            "current": [round(float(r["sales_cur"] or 0)) for r in sales_month_compare],
            "previous": [round(float(r["sales_prev"] or 0)) for r in sales_month_compare],
        },
        "salesWarehouse": {
            "labels": [r["warehouse"] for r in sales_warehouse],
            "values": [round(float(r["value"] or 0)) for r in sales_warehouse],
            "units": [int(r["units"] or 0) for r in sales_warehouse],
        },
        "topSellers": {
            "labels": [r["sku"] for r in top_sellers],
            "values": [round(float(r["value"] or 0)) for r in top_sellers],
            "units": [int(r["units"] or 0) for r in top_sellers],
        },
        "categoryCount": {
            "labels": [r["category"] for r in category_counts],
            "values": [int(r["c"] or 0) for r in category_counts],
        },
        "poMonthlyTrend": po_monthly_trend,
        "supplierLeadTimes": {
            "labels": [r["name"] for r in supplier_lead_times],
            "leadDays": [int(r["lead_days"] or 0) for r in supplier_lead_times],
            "reliability": [round(float(r["reliability"] or 0)) for r in supplier_lead_times],
            "productCount": [int(r["product_count"] or 0) for r in supplier_lead_times],
        },
        "warehouseStockStatus": {
            "labels": [r["warehouse"] for r in warehouse_stock_status],
            "skuCount": [int(r["sku_count"] or 0) for r in warehouse_stock_status],
            "healthy": [int(r["healthy_count"] or 0) for r in warehouse_stock_status],
            "low": [int(r["low_count"] or 0) for r in warehouse_stock_status],
            "out": [int(r["out_count"] or 0) for r in warehouse_stock_status],
        },
}
    # Cache the template context for reuse
    template_context = {
        "breakdown": breakdown,
        "top_skus": top_skus,
        "warehouse_breakdown": warehouse_breakdown,
        "supplier_stats": supplier_stats,
        "reorder_pressure": reorder_pressure,
        "movement": movement,
        "report_data": report_data,
        "total": float(kpi["inventory_value"] or 0),
        "total_units": int(kpi["total_units"] or 0),
        "sku_count": int(kpi["sku_count"] or 0),
        "unders": int(unders or 0),
        "out_stock": int(kpi["out_of_stock"] or 0),
        "healthy": status_healthy,
        "open_po": open_po,
        "supplier_count": supplier_count,
        "thinnest": thinnest,
        "today": date.today(),
        "warehouses": warehouses,
        "categories": categories,
        "selected_warehouses": selected_warehouses,
        "selected_categories": selected_categories,
        "selected_warehouse": selected_warehouses[0] if selected_warehouses else "",
        "selected_category": selected_categories[0] if selected_categories else "",
        "selected_months": selected_months,
        "selected_years": selected_years,
        "date_from": selected_months,
        "date_to": selected_years,
        "category_counts": category_counts,
        "product_rows": product_rows,
        "po_status": po_status,
        "po_value": po_value,
        "open_pos": open_pos,
        "warehouse_analytics": warehouse_analytics,
        "warehouse_movement": warehouse_movement,
        "ytd": ytd,
        "prev_ytd": prev_ytd,
        "mtd": mtd,
        "prev_mtd": prev_mtd,
        "year_series": year_series,
        "ytd_compare": ytd_compare,
        "month_compare": month_compare,
        "monthly_series": monthly_series,
        "reorder_by_category": reorder_by_category,
        "sales": sales,
        "top_sellers": top_sellers,
        "sales_years": sales_years,
        "sales_ytd_compare": sales_ytd_compare,
        "sales_qtd_compare": sales_qtd_compare,
        "sales_months_by_year": sales_months_by_year,
        "sales_quarter": sales_quarter_series,
        "sales_quarter_compare": sales_quarter_compare,
        "sales_month_compare": sales_month_compare,
        "sales_monthly": sales_monthly_series,
        "reorder_by_supplier": {
            "labels": [r["supplier"] for r in reorder_by_supplier] if 'reorder_by_supplier' in locals() else [],
            "values": [int(r["skus_below_rop"] or 0) for r in reorder_by_supplier] if 'reorder_by_supplier' in locals() else [],
        },
        "movement_caption": movement_caption,
        "coverage_distribution": coverage_distribution,
        "category_coverage": category_coverage,
        "warehouse_turnover": warehouse_turnover,
        "reorder_coverage": [
            {"sku": r["sku"], "coverage": round((r["coverage"] or 0) * 100)}
            for r in reorder_pressure
        ],
        "po_monthly_trend": po_monthly_trend,
        "supplier_lead_times": supplier_lead_times,
        "warehouse_stock_status": warehouse_stock_status,
    }
    reports_cache.set(cache_key, template_context)

    return render_template("reports.html", **template_context)


@ui_bp.route("/eoq-calculator")
@login_required
def eoq_calculator():
    from ..services import EOQService
    return render_template("eoq_calculator.html", product_eoq=EOQService.per_product_table())


@ui_bp.route("/settings")
@login_required
@write_roles_required
def settings():
    settings_data = SettingsService.get_settings()
    low_pct, critical_pct = SettingsService.threshold_pcts()
    settings_data = dict(settings_data)
    settings_data["low_stock_threshold"] = str(int(low_pct))
    settings_data["critical_threshold"] = str(int(critical_pct))
    return render_template("settings.html", user=current_user, settings_data=settings_data)


@ui_bp.route("/help")
@login_required
def help():
    return render_template("help.html")


@ui_bp.route("/contact")
@login_required
def contact():
    return render_template("contact.html")


# ── Warehouse Monitoring Routes ──────────────────────────────────────────────

@ui_bp.route("/monitoring")
@login_required
@write_roles_required
def monitoring():
    """Session & login monitoring dashboard."""
    from ..database import get_cursor

    def _load():
        active_sessions = []
        login_history = []
        signup_history = []
        user_summary = []
        daily_logins = []
        etl_status = {}
        try:
            with get_cursor() as cur:
                cur.execute("SELECT * FROM sp_monitor_active_sessions()")
                active_sessions = list(cur.fetchall())

                cur.execute("SELECT * FROM sp_monitor_login_history(30)")
                login_history = list(cur.fetchall())

                cur.execute("SELECT * FROM sp_monitor_signup_history(30)")
                signup_history = list(cur.fetchall())

                cur.execute("SELECT * FROM sp_monitor_user_activity_summary()")
                user_summary = list(cur.fetchall())

                cur.execute("SELECT * FROM sp_monitor_daily_logins(30)")
                daily_logins = list(cur.fetchall())

                cur.execute("SELECT state_key, value, updated_at FROM etl_warehouse_state ORDER BY updated_at DESC")
                etl_status = {row["state_key"]: {"value": row["value"], "updated_at": row["updated_at"]}
                              for row in cur.fetchall()}
        except Exception:
            pass
        return {
            "active_sessions": active_sessions,
            "login_history": login_history,
            "signup_history": signup_history,
            "user_summary": user_summary,
            "daily_logins": daily_logins,
            "etl_status": etl_status,
        }

    cached = monitoring_cache.get_or_set("monitoring", _load)
    return render_template("monitoring.html", **cached)


@ui_bp.route("/monitoring/run-etl", methods=["POST"])
@login_required
@write_roles_required
def monitoring_run_etl():
    """Manually trigger warehouse ETL (non-blocking)."""
    from ..database.connection import etl_database
    def _run():
        try:
            etl_database(force=True)
        except Exception as e:
            LOGGER.warning("Background ETL failed: %s", e)
    threading.Thread(target=_run, daemon=True).start()
    monitoring_cache.invalidate("")  # bust so the page shows fresh ETL state
    flash("ETL rebuild started in background", "success")
    return redirect(url_for("ui.monitoring"))


def _landing_stats():
    """Public landing page stats — hardcoded demo values only (no real DB queries)."""
    return {
        "total_skus": 500,
        "inventory_value": 4_280_000.0,
        "reorder_count": 12,
        "suppliers": 48,
        "warehouses": 6,
        "units_today": 1240,
        "stock_health": 94,
        "categories": [
            {"category": "Electronics", "count": 120},
            {"category": "Clothing", "count": 95},
            {"category": "Home & Garden", "count": 80},
            {"category": "Sports", "count": 65},
            {"category": "Automotive", "count": 55},
            {"category": "Books", "count": 45},
            {"category": "Other", "count": 40},
        ],
        "series": [1200, 1350, 1100, 1400, 1550, 1300, 1600, 1450, 1700, 1850, 1600, 1900],
        "dates": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        "movements": 24800,
        "first_movement": "2025-01-01",
        "last_movement": "2026-08-29",
        "open_pos": 3,
    }


def _inout_series(rows, days):
    cutoff = date.today() - timedelta(days=days - 1)
    by_day = {}
    for r in rows:
        key = (r["day"].year, r["day"].month, r["day"].day)
        by_day[key] = (int(r["in_qty"]), int(r["out_qty"]))
    in_s, out_s, dates = [], [], []
    for i in range(days):
        d = cutoff + timedelta(days=i)
        if d > date.today():
            break
        in_val, out_val = by_day.get((d.year, d.month, d.day), (0, 0))
        in_s.append(in_val)
        out_s.append(out_val)
        dates.append(d.strftime("%d %b").upper())
    return in_s, out_s, dates


def _series_for_last_days(rows, days):
    cutoff = date.today() - timedelta(days=days - 1)
    by_day = {(r["day"].year, r["day"].month, r["day"].day): int(r["total"]) for r in rows}
    series, dates = [], []
    for i in range(days):
        d = cutoff + timedelta(days=i)
        if d > date.today():
            break
        series.append(by_day.get((d.year, d.month, d.day), 0))
        dates.append(d.strftime("%d %b").upper())
    return series, dates


def _chart_geometry(values, dates):
    if not values:
        values = [0]
    max_val = max(values) or 1
    width, height = 600, 220
    left, right, top, bottom = 20, 580, 35, 185
    pts = []
    for i, value in enumerate(values):
        x = left + i * ((right - left) / max(1, len(values) - 1))
        y = bottom - (value / max_val) * (bottom - top)
        pts.append((round(x), round(y)))
    points = " ".join(f"{x},{y}" for x, y in pts)
    area = f"{left},{bottom} {points} {right},{bottom}"
    return {
        "values": values, "max": max_val, "points": points,
        "area": area, "circles": pts, "dates": dates,
    }


# ── Notifications ──────────────────────────────────────────────────────
@ui_bp.route("/notifications")
@login_required
def notifications_page():
    from ..repositories import NotificationRepository
    notifs = NotificationRepository.list_for_user(current_user.id, limit=100)
    return render_template("notifications.html", notifications=notifs)


@ui_bp.route("/notifications/<int:notif_id>")
@login_required
def notification_detail(notif_id: int):
    from ..repositories import NotificationRepository
    notif = NotificationRepository.get(notif_id, current_user.id)
    if not notif:
        abort(404)
    return render_template("notification_detail.html", notif=notif)
