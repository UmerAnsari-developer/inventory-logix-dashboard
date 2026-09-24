"""Admin data import routes."""
from __future__ import annotations

import csv
import io

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.database import get_cursor
from app.security import write_roles_required

admin_data_import_bp = Blueprint(
    "admin_data_import", __name__, url_prefix="/admin/data-import"
)


def _count_table(table: str) -> int:
    with get_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
        return int(cur.fetchone()["c"] or 0)


def _get_import_stats() -> dict:
    """Return row counts for each importable entity."""
    tables = {
        "products": ("products", "Products"),
        "suppliers": ("suppliers", "Suppliers"),
        "warehouses": ("warehouses", "Warehouses"),
        "movements": ("movements", "Movements"),
        "purchase_orders": ("purchase_orders", "Purchase Orders"),
    }
    stats = {}
    for key, (table, label) in tables.items():
        try:
            count = _count_table(table)
        except Exception:
            count = 0
        stats[key] = {"label": label, "count": count}
    return stats


@admin_data_import_bp.route("/")
@login_required
@write_roles_required
def index():
    """Data Import dashboard with entity tabs."""
    tab = request.args.get("tab", "products")
    stats = _get_import_stats()
    return render_template(
        "admin/data_import/index.html",
        stats=stats,
        active_tab=tab,
        active_page="data_import",
    )


@admin_data_import_bp.route("/upload/<entity>", methods=["POST"])
@login_required
@write_roles_required
def upload(entity: str):
    """Handle CSV upload for a given entity."""
    allowed = {"products", "suppliers", "warehouses", "movements", "purchase_orders"}
    if entity not in allowed:
        flash("Invalid entity type.", "error")
        return redirect(url_for("admin_data_import.index"))

    file = request.files.get("csv_file")
    if not file or not file.filename:
        flash("Choose file first", "error")
        return redirect(url_for("admin_data_import.index", tab=entity))

    if not file.filename.lower().endswith(".csv"):
        flash("Please upload a CSV file.", "error")
        return redirect(url_for("admin_data_import.index", tab=entity))

    try:
        content = file.read().decode("utf-8", errors="replace")
        # Reset stream position for potential reuse? Not needed as we already read.
        reader = csv.DictReader(io.StringIO(content))
        if reader.fieldnames is None:
            flash("The CSV file appears to be empty or malformed.", "error")
            return redirect(url_for("admin_data_import.index", tab=entity))
        # Expected columns for each entity (case-insensitive match)
        expected = {
            "products": {"sku", "product_name", "unit_price", "current_stock", "reorder_point", "category", "supplier_id"},
            "suppliers": {"supplier_name", "contact_email", "phone", "address"},
            "warehouses": {"warehouse_name", "location"},
            "movements": {"product_id", "quantity", "movement_type", "reason"},
            "purchase_orders": {"supplier_id", "product_id", "quantity", "status"},
        }
        # Normalize fieldnames to lower case and strip spaces
        provided = {f.strip().lower() for f in reader.fieldnames}
        expected_set = expected[entity]
        # Check if all expected columns are present (extra columns are allowed)
        if not expected_set.issubset(provided):
            missing = expected_set - provided
            label = {"products": "Products", "suppliers": "Suppliers", "warehouses": "Warehouses", "movements": "Movements", "purchase_orders": "Purchase Orders"}.get(entity, entity)
            flash(f"CSV columns don't match the {label} tab. Missing: {', '.join(sorted(missing))}. Select the correct tab and try again.", "error")
            return redirect(url_for("admin_data_import.index", tab=entity))

        rows = list(reader)
        count = _import_rows(entity, rows)
        label = {"products": "Products", "suppliers": "Suppliers", "warehouses": "Warehouses", "movements": "Movements", "purchase_orders": "Purchase Orders"}.get(entity, entity)
        flash(f"Successfully imported {count} {label.lower()}.", "success")
    except Exception as e:
        current_app.logger.error(f"Import error for {entity}: {e}")
        flash(f"Import failed: {e}", "error")

    return redirect(url_for("admin_data_import.index", tab=entity))


def _import_rows(entity: str, rows: list[dict]) -> int:
    """Insert rows into the target table. Returns count inserted."""
    if not rows:
        return 0

    if entity == "products":
        return _import_products(rows)
    elif entity == "suppliers":
        return _import_suppliers(rows)
    elif entity == "warehouses":
        return _import_warehouses(rows)
    elif entity == "movements":
        return _import_movements(rows)
    elif entity == "purchase_orders":
        return _import_purchase_orders(rows)
    return 0


def _import_products(rows: list[dict]) -> int:
    count = 0
    with get_cursor(commit=True) as cur:
        for row in rows:
            try:
                sku = row.get("sku", "").strip()
                name = row.get("product_name", row.get("name", "")).strip()
                price = float(row.get("unit_price", row.get("price", 0)) or 0)
                stock = int(row.get("current_stock", row.get("stock", 0)) or 0)
                reorder = int(row.get("reorder_point", row.get("reorder", 10)) or 10)
                category = row.get("category", "General").strip() or "General"
                supplier_id = int(row.get("supplier_id", 0) or 0) or None
                if not sku or not name:
                    continue
                cur.execute(
                    """INSERT INTO products (sku, product_name, unit_price, current_stock,
                       reorder_point, category, supplier_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (sku) DO UPDATE SET
                         product_name=EXCLUDED.product_name,
                         unit_price=EXCLUDED.unit_price""",
                    (sku, name, price, stock, reorder, category, supplier_id),
                )
                count += 1
            except Exception:
                continue
    return count


def _import_suppliers(rows: list[dict]) -> int:
    count = 0
    with get_cursor(commit=True) as cur:
        for row in rows:
            try:
                name = row.get("supplier_name", row.get("name", "")).strip()
                contact = row.get("contact_email", row.get("email", "")).strip()
                phone = row.get("phone", "").strip()
                address = row.get("address", "").strip()
                if not name:
                    continue
                cur.execute(
                    """INSERT INTO suppliers (supplier_name, contact_email, phone, address)
                       VALUES (%s, %s, %s, %s)""",
                    (name, contact, phone, address),
                )
                count += 1
            except Exception:
                continue
    return count


def _import_warehouses(rows: list[dict]) -> int:
    count = 0
    with get_cursor(commit=True) as cur:
        for row in rows:
            try:
                name = row.get("warehouse_name", row.get("name", "")).strip()
                location = row.get("location", "").strip()
                if not name:
                    continue
                cur.execute(
                    """INSERT INTO warehouses (warehouse_name, location)
                       VALUES (%s, %s)""",
                    (name, location),
                )
                count += 1
            except Exception:
                continue
    return count


def _import_movements(rows: list[dict]) -> int:
    count = 0
    with get_cursor(commit=True) as cur:
        for row in rows:
            try:
                product_id = int(row.get("product_id", 0) or 0)
                qty = int(row.get("quantity", row.get("qty", 0)) or 0)
                movement_type = row.get("movement_type", row.get("type", "in")).strip()
                reason = row.get("reason", "").strip()
                if not product_id or qty == 0:
                    continue
                cur.execute(
                    """INSERT INTO movements (product_id, quantity, movement_type, reason)
                       VALUES (%s, %s, %s, %s)""",
                    (product_id, qty, movement_type, reason),
                )
                count += 1
            except Exception:
                continue
    return count


def _import_purchase_orders(rows: list[dict]) -> int:
    count = 0
    with get_cursor(commit=True) as cur:
        for row in rows:
            try:
                supplier_id = int(row.get("supplier_id", 0) or 0)
                product_id = int(row.get("product_id", 0) or 0)
                qty = int(row.get("quantity", row.get("qty", 0)) or 0)
                status = row.get("status", "pending").strip()
                if not supplier_id or not product_id or qty <= 0:
                    continue
                cur.execute(
                    """INSERT INTO purchase_orders
                       (supplier_id, product_id, quantity, status)
                       VALUES (%s, %s, %s, %s)""",
                    (supplier_id, product_id, qty, status),
                )
                count += 1
            except Exception:
                continue
    return count
