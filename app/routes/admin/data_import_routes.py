"""Admin data import routes with audit logging."""
from __future__ import annotations

import csv
import io
import random
import psycopg2
from datetime import date

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.database import get_cursor
from app.extensions import limiter
from app.repositories import MovementRepository
from app.security import write_roles_required
from app.security.audit import audit_admin_action
from app.services import DataImportService
from app.services.movement_service import MovementError

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
@audit_admin_action("admin.data_import.list", target_type="data_import")
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


@admin_data_import_bp.route("/preview/<entity>", methods=["POST"])
@login_required
@write_roles_required
@limiter.limit("30 per minute")
def preview(entity: str):
    """Preview CSV import without committing changes."""
    allowed = {"products", "suppliers", "warehouses", "movements", "purchase_orders"}
    if entity not in allowed:
        return jsonify({"success": False, "error": "Invalid entity type"}), 400

    csv_content = request.form.get("csv_content", "")
    if not csv_content:
        return jsonify({"success": False, "error": "No CSV content provided"}), 400

    preview_result = DataImportService.preview_import(csv_content, entity)
    return jsonify({"success": True, "preview": preview_result})


@admin_data_import_bp.route("/upload/<entity>", methods=["POST"])
@login_required
@write_roles_required
@limiter.limit("10 per minute")
@audit_admin_action("admin.data_import.upload", target_type="data_import", detail_func=lambda r, *a, **kw: {"entity": kw.get("entity")})
def upload(entity: str):
    """Handle CSV upload for a given entity."""
    allowed = {"products", "suppliers", "warehouses", "movements", "purchase_orders"}
    if entity not in allowed:
        flash("Invalid entity type.", "error")
        return redirect(url_for("admin_data_import.index"))

    # Size guard: Werkzeug 3.1 does not enforce MAX_CONTENT_LENGTH for
    # multipart uploads — check the request body size explicitly (5 MB default).
    max_bytes = current_app.config.get("MAX_CONTENT_LENGTH", 5 * 1024 * 1024)
    if request.content_length and request.content_length > max_bytes:
        flash("File exceeds the 5 MB size limit. Split the CSV into smaller files.", "error")
        return redirect(url_for("admin_data_import.index", tab=entity))

    # Check if this is a confirmed import from preview step
    confirm = request.form.get("confirm") == "true"
    csv_content = request.form.get("csv_content", "")

    if confirm and csv_content:
        # Import from preview confirmation
        content = csv_content
    else:
        # Traditional file upload
        file = request.files.get("csv_file")
        if not file or not file.filename:
            flash("Choose file first", "error")
            return redirect(url_for("admin_data_import.index", tab=entity))

        if not file.filename.lower().endswith(".csv"):
            flash("Please upload a CSV file.", "error")
            return redirect(url_for("admin_data_import.index", tab=entity))

        try:
            content = file.read().decode("utf-8")
        except UnicodeDecodeError:
            # ADM-018: reject invalid UTF-8 instead of silently replacing chars.
            flash("File is not valid UTF-8. Re-save the CSV with UTF-8 encoding.", "error")
            return redirect(url_for("admin_data_import.index", tab=entity))
        except Exception as e:
            current_app.logger.error(f"File read error for {entity}: {e}")
            flash(f"Failed to read file: {e}", "error")
            return redirect(url_for("admin_data_import.index", tab=entity))

    try:
        reader = csv.DictReader(io.StringIO(content))
        if reader.fieldnames is None:
            flash("The CSV file appears to be empty or malformed.", "error")
            return redirect(url_for("admin_data_import.index", tab=entity))

        # Expected columns for each entity (case-insensitive match)
        expected = {
            "products": {"sku", "name", "unit_price", "current_stock", "reorder_point", "category", "supplier_id"},
            "suppliers": {"name", "location", "lead_days"},
            "warehouses": {"warehouse_name", "location"},
            "movements": {"product_id", "quantity", "type", "reason"},
            "purchase_orders": {"supplier_id", "product_id", "quantity", "status"},
        }

        # Column aliases for flexible matching (matching DataImportService.COLUMN_ALIASES)
        column_aliases = {
            "products": {
                "product_name": "name",
                "price": "unit_price",
                "stock": "current_stock",
                "reorder": "reorder_point",
            },
            "suppliers": {
                "supplier_name": "name",
                "email": "contact_email",
            },
            "warehouses": {
                "name": "warehouse_name",
            },
            "movements": {
                "qty": "quantity",
                "movement_type": "type",
            },
            "purchase_orders": {
                "qty": "quantity",
            },
        }

        # Normalize fieldnames to lower case and strip spaces
        provided = {f.strip().lower() for f in reader.fieldnames}

        # Apply aliases
        normalized_provided = set()
        for col in provided:
            normalized_provided.add(column_aliases.get(entity, {}).get(col, col))

        expected_set = expected[entity]

        # Check if all expected columns are present (extra columns are allowed)
        if not expected_set.issubset(normalized_provided):
            missing = expected_set - normalized_provided
            label = {"products": "Products", "suppliers": "Suppliers", "warehouses": "Warehouses", "movements": "Movements", "purchase_orders": "Purchase Orders"}.get(entity, entity)
            flash(f"CSV columns don't match the {label} tab. Missing: {', '.join(sorted(missing))}. Select the correct tab and try again.", "error")
            return redirect(url_for("admin_data_import.index", tab=entity))

        # Normalize row keys using aliases
        rows = []
        for row in reader:
            normalized_row = {}
            for k, v in row.items():
                key = k.strip().lower()
                key = column_aliases.get(entity, {}).get(key, key)
                normalized_row[key] = v.strip() if isinstance(v, str) else v
            rows.append(normalized_row)

        count = _import_rows(entity, rows)
        if count == 0:
            flash("No rows were imported. Check CSV format and data.", "warning")
        else:
            label = {"products": "Products", "suppliers": "Suppliers", "warehouses": "Warehouses", "movements": "Movements", "purchase_orders": "Purchase Orders"}.get(entity, entity)
            flash(f"Successfully imported {count} {label.lower()}.", "success")
    except Exception as e:
        current_app.logger.error(f"Import error for {entity}: {e}")
        flash(f"Import failed: {e}", "error")

    return redirect(url_for("admin_data_import.index", tab=entity))

    return redirect(url_for("admin_data_import.index", tab=entity))


def _import_rows(entity: str, rows: list[dict]) -> int:
    """Insert rows into the target table with advisory lock. Returns count inserted."""
    if not rows:
        return 0

    # Entity-specific lock keys (hash of entity name)
    lock_keys = {
        "products": 0x70726F64,      # "prod"
        "suppliers": 0x73757070,     # "supp"
        "warehouses": 0x77617265,    # "ware"
        "movements": 0x6D6F7665,     # "move"
        "purchase_orders": 0x706F7264, # "pord"
    }
    lock_key = lock_keys.get(entity, hash(entity) & 0x7FFFFFFF)

    if entity == "products":
        return _import_products(rows, lock_key)
    elif entity == "suppliers":
        return _import_suppliers(rows, lock_key)
    elif entity == "warehouses":
        return _import_warehouses(rows, lock_key)
    elif entity == "movements":
        return _import_movements(rows)
    elif entity == "purchase_orders":
        return _import_purchase_orders(rows, lock_key)
    return 0


def _execute_with_lock(lock_key: int, callback):
    """Execute a callback with PostgreSQL advisory lock (session-level)."""
    # Use a simple approach: acquire lock, do work, release lock
    # Advisory locks are session-level and persist across transactions
    with get_cursor(commit=True) as cur:
        cur.execute("SELECT pg_advisory_lock(%s)", (lock_key,))
    try:
        with get_cursor(commit=True) as cur:
            return callback(cur)
    finally:
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))


def _safe_row_insert(cur, insert_fn):
    """Run one row insert under a SAVEPOINT so a failed row (FK violation,
    constraint, etc.) cannot poison the batch transaction.

    Without this, one bad row aborts the transaction and every subsequent
    row fails with InFailedSqlTransaction — silently swallowed, the user
    sees "No rows were imported" even when most rows were valid.

    insert_fn must return cur.rowcount captured immediately after its INSERT
    (RELEASE SAVEPOINT resets rowcount). Returns True only when a row was
    actually inserted/updated; DO NOTHING no-ops return False so the
    reported count is honest.
    """
    cur.execute("SAVEPOINT row_sp")
    try:
        rowcount = insert_fn()
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT row_sp")
        return False
    cur.execute("RELEASE SAVEPOINT row_sp")
    return (rowcount or 0) > 0


def _import_products(rows: list[dict], lock_key: int) -> int:
    count = 0
    
    def do_import(cur):
        nonlocal count
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
                def _insert():
                    cur.execute(
                        """INSERT INTO products (sku, name, unit_price, current_stock,
                           reorder_point, category, supplier_id)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (sku) WHERE deleted_at IS NULL DO UPDATE SET
                             name=EXCLUDED.name,
                             unit_price=EXCLUDED.unit_price,
                             current_stock=EXCLUDED.current_stock,
                             reorder_point=EXCLUDED.reorder_point,
                             category=EXCLUDED.category,
                             supplier_id=EXCLUDED.supplier_id""",
                        (sku, name, price, stock, reorder, category, supplier_id),
                    )
                    return cur.rowcount
                if _safe_row_insert(cur, _insert):
                    count += 1
            except Exception:
                continue
        return count
    
    _execute_with_lock(lock_key, do_import)
    return count


def _import_suppliers(rows: list[dict], lock_key: int) -> int:
    count = 0
    
    def do_import(cur):
        nonlocal count
        for row in rows:
            try:
                name = row.get("supplier_name", row.get("name", "")).strip()
                location = row.get("location", "").strip()
                # Real schema columns: suppliers has NO contact_email/phone/address.
                initials = "".join(part[0].upper() for part in name.split()[:2])[:10]
                lead_days = int(row.get("lead_days", 0) or 0)
                if not name:
                    continue
                # Dedup by name: suppliers has no unique constraint on name,
                # so a plain INSERT would create duplicates on re-import.
                cur.execute(
                    "SELECT 1 FROM suppliers WHERE name = %s AND deleted_at IS NULL LIMIT 1",
                    (name,),
                )
                if cur.fetchone():
                    continue
                def _insert():
                    cur.execute(
                        """INSERT INTO suppliers (name, initials, location, lead_days)
                           VALUES (%s, %s, %s, %s)""",
                        (name, initials, location, lead_days),
                    )
                    return cur.rowcount
                if _safe_row_insert(cur, _insert):
                    count += 1
            except Exception:
                continue
        return count
    
    _execute_with_lock(lock_key, do_import)
    return count


def _import_warehouses(rows: list[dict], lock_key: int) -> int:
    count = 0
    
    def do_import(cur):
        nonlocal count
        for row in rows:
            try:
                name = row.get("warehouse_name", row.get("name", "")).strip()
                location = row.get("location", "").strip()
                if not name:
                    continue
                def _insert():
                    cur.execute(
                        """INSERT INTO warehouses (warehouse_name, location)
                           VALUES (%s, %s)
                           ON CONFLICT (warehouse_name) DO NOTHING""",
                        (name, location),
                    )
                    return cur.rowcount
                if _safe_row_insert(cur, _insert):
                    count += 1
            except Exception:
                continue
        return count
    
    _execute_with_lock(lock_key, do_import)
    return count


def _import_movements(rows: list[dict], lock_key: int | None = None) -> int:
    """Import movements using MovementRepository.record (per-row transactions).
    
    Each row gets its own transaction via MovementRepository.record -> get_cursor(commit=True).
    This calls sp_movement_record which provides atomic stock update with row-level locking.
    
    Args:
        rows: List of movement row dicts
        lock_key: Ignored (kept for backward compatibility). Advisory lock not needed
                  because sp_movement_record uses FOR UPDATE row-level locking.
    """
    count = 0
    for row in rows:
        try:
            product_id = int(row.get("product_id", 0) or 0)
            qty = int(row.get("quantity", row.get("qty", 0)) or 0)
            movement_type = row.get("movement_type", row.get("type", "IN")).strip().upper()
            reason = row.get("reason", "").strip()
            
            if not product_id or qty == 0:
                continue
            if movement_type not in ("IN", "OUT", "ADJUSTMENT", "RETURN"):
                continue
            if qty < 0:
                # Database constraint chk_quantity_positive requires quantity > 0
                # MovementService also validates quantity must be positive
                continue
            
            MovementRepository.record(
                product_id=product_id,
                mtype=movement_type,
                quantity=qty,
                reference=reason or None,
                notes=None,
                user_id=None,
            )
            count += 1
        except MovementError:
            # Validation errors (invalid product, insufficient stock, etc.) - skip row
            continue
        except psycopg2.Error:
            # Database errors (constraint violations, etc.) - skip row
            continue
        except Exception:
            # Other errors - skip row
            continue
    return count


def _import_purchase_orders(rows: list[dict], lock_key: int) -> int:
    count = 0
    valid_statuses = {"draft", "approved", "in_transit", "received", "cancelled"}
    # ADM-009: valid forward paths so imported POs walk the state machine
    # (sp_po_transition) instead of being inserted with an arbitrary status.
    transition_paths = {
        "approved": ("approved",),
        "in_transit": ("approved", "in_transit"),
        "received": ("approved", "in_transit", "received"),
    }
    
    def do_import(cur):
        nonlocal count
        for row in rows:
            try:
                supplier_id = int(row.get("supplier_id", 0) or 0)
                product_id = int(row.get("product_id", 0) or 0)
                qty = int(row.get("quantity", row.get("qty", 0)) or 0)
                status = row.get("status", "draft").strip().lower()
                po_number = row.get("po_number", "").strip()
                if not supplier_id or not product_id or qty <= 0:
                    continue
                if status not in valid_statuses:
                    status = "draft"
                if not po_number:
                    # Generate a PO number if not provided
                    import random
                    from datetime import date
                    po_number = f"PO-{date.today():%Y%m%d}-{random.randint(1000, 9999)}"
                def _insert():
                    # Always insert as draft; the state machine applies stock/on_order
                    # effects atomically for each forward transition.
                    cur.execute(
                        """INSERT INTO purchase_orders
                           (po_number, supplier_id, product_id, quantity, status)
                           VALUES (%s, %s, %s, %s, 'draft')""",
                        (po_number, supplier_id, product_id, qty),
                    )
                    inserted = cur.rowcount
                    cur.execute("SELECT id FROM purchase_orders WHERE po_number = %s", (po_number,))
                    po_row = cur.fetchone()
                    po_id = po_row["id"] if po_row else None
                    if po_id:
                        for step in transition_paths.get(status, ()):
                            cur.execute("SELECT sp_po_transition(%s, %s)", (po_id, step))
                    return inserted
                if _safe_row_insert(cur, _insert):
                    count += 1
            except Exception:
                continue
        return count
    
    _execute_with_lock(lock_key, do_import)
    return count