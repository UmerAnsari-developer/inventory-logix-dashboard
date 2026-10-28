"""Admin data import routes with audit logging."""
from __future__ import annotations

import csv
import io
import random
from collections import Counter
from datetime import date

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.database import get_cursor
from app.extensions import limiter
from app.repositories import MovementRepository
from app.security import WRITE_ROLES, write_roles_required
from app.security.audit import audit_admin_action
from app.security.dberrors import db_error_message, is_guard_error
from app.services import DataImportService
from app.services.movement_service import MovementError

admin_data_import_bp = Blueprint(
    "admin_data_import", __name__, url_prefix="/admin/data-import"
)

_MAX_REASON_LINES = 10  # flash cookie budget + no-scroll toast stack
_FLASH_CLIP = 140
# Bounds per-row detail on huge CSVs; the flash needs at most 10 entries and
# the full per-code tallies live in error_counts.
_MAX_RETAINED_ERRORS = 200


class _RowSkip(Exception):
    """One skipped row — first failing check wins (skipped == len(errors))."""

    def __init__(self, error_code: str, field: str = "", value: str = "",
                 reason: str = "", severity: str = "warning"):
        super().__init__(reason)
        self.error_code = error_code
        self.field = field
        self.value = value
        self.reason = reason
        self.severity = severity


def _err(row_no: int, error_code: str, field: str = "", value: str = "",
         reason: str = "", severity: str = "warning") -> dict:
    """Build one result entry (mirrors validate_fk_rows' warning shape)."""
    return {
        "row": row_no,
        "field": field,
        "value": value,
        "error_code": error_code,
        "severity": severity,
        "reason": reason,
    }


def _parse_number(field: str, raw, cast, default: int = 0):
    """Cast a CSV cell; blank/falsy values use ``default`` (legacy ``or``
    semantics). Unparseable values raise ``_RowSkip`` so the row is reported
    as an invalid number instead of vanishing."""
    try:
        return cast(raw or default)
    except (TypeError, ValueError):
        raise _RowSkip(
            "invalid_number", field=field, value=str(raw),
            reason=f"{field} is not a number: '{raw}'",
        )


def _empty_result() -> dict:
    """Every importer returns {"imported": int, "skipped": int,
    "errors": [...], "error_counts": {code: count}} — errors holds at most
    ``_MAX_RETAINED_ERRORS`` entries; skipped / error_counts are full tallies."""
    return {"imported": 0, "skipped": 0, "errors": [], "error_counts": {}}


def _record_skip(result: dict, row_no: int, skip: _RowSkip) -> None:
    """Count one skipped row; keep at most ``_MAX_RETAINED_ERRORS`` detail
    entries (invariant: skipped == len(errors) while skipped <= cap)."""
    result["skipped"] += 1
    counts = result["error_counts"]
    counts[skip.error_code] = counts.get(skip.error_code, 0) + 1
    if len(result["errors"]) < _MAX_RETAINED_ERRORS:
        result["errors"].append(
            _err(row_no, skip.error_code, skip.field, skip.value, skip.reason, skip.severity)
        )


def _clip(text, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _flash_import_detail(result: dict) -> None:
    """Flash skipped-row reasons AFTER the status line. Clean imports (and
    header-only CSVs) stay exactly as before: no extra flash."""
    errors = result["errors"]
    if result["skipped"] == 0 and not errors:
        return
    flash(f"Skipped {result['skipped']} row(s).", "warning")
    displayed = errors[:_MAX_REASON_LINES]
    for entry in displayed:
        flash(
            f"Row {entry['row']} — {_clip(entry['reason'], _FLASH_CLIP)}",
            entry.get("severity", "warning"),
        )
    remaining = result["skipped"] - len(displayed)
    if remaining > 0:
        # Tail heights come from the FULL tallies minus the displayed codes,
        # so it stays correct when errors was truncated at _MAX_RETAINED_ERRORS.
        counts = Counter(result["error_counts"])
        for entry in displayed:
            counts[entry["error_code"]] -= 1
        grouped = ", ".join(
            f"{n}× {code}"
            for code, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            if n > 0
        )
        flash(f"…and {remaining} more: {grouped}.", "warning")


def _count_table(table: str) -> int:
    with get_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
        return int(cur.fetchone()["c"] or 0)


def _get_import_stats() -> dict:
    """Return row counts for each importable entity."""
    tables = {
        "products": "products",
        "suppliers": "suppliers",
        "warehouses": "warehouses",
        "movements": "movements",
        "purchase_orders": "purchase_orders",
    }
    stats = {}
    for key, table in tables.items():
        try:
            count = _count_table(table)
        except Exception:
            count = 0
        stats[key] = {"label": DataImportService.IMPORT_GUIDE[key]["label"], "count": count}
    return stats


@admin_data_import_bp.route("/")
@login_required
@write_roles_required
@audit_admin_action("admin.data_import.list", target_type="data_import", roles=WRITE_ROLES)
def index():
    """Data Import dashboard with entity tabs."""
    tab = request.args.get("tab", "products")
    stats = _get_import_stats()
    return render_template(
        "admin/data_import/index.html",
        stats=stats,
        active_tab=tab,
        active_page="data_import",
        import_guide=DataImportService.IMPORT_GUIDE,
        column_aliases=DataImportService.COLUMN_ALIASES,
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

    # Size guard: Werkzeug 3.1 does not enforce MAX_CONTENT_LENGTH for
    # urlencoded bodies — check the request body size explicitly (5 MB default).
    # Mirrors the upload route's guard. A missing Content-Length (chunked
    # request) is rejected too: we cannot bound an unannounced body.
    max_bytes = current_app.config.get("MAX_CONTENT_LENGTH", 5 * 1024 * 1024)
    max_mb = round(max_bytes / (1024 * 1024))
    if not request.content_length or request.content_length > max_bytes:
        return (
            jsonify({
                "success": False,
                "error": f"File exceeds the {max_mb} MB size limit. Split the CSV into smaller files.",
            }),
            413,
        )

    # Opt-in create-missing (checkbox on the import page): unknown supplier
    # refs preview as "will create" instead of warnings.
    create_missing = request.form.get("create_missing") == "true"

    # Build FK caches for preview validation. A DB hiccup must not break the
    # preview itself — degrade to "no FK validation" and flag it in errors.
    # Entities without FK fields (suppliers, warehouses) skip the DB entirely.
    fk_caches = None
    fk_stored = None
    db_failed = False
    if DataImportService.FK_CHECK_FIELDS.get(entity):
        try:
            with get_cursor() as cur:
                fk_caches, fk_stored = DataImportService.build_fk_preview_data(cur)
        except Exception:
            current_app.logger.warning("FK cache build failed during preview", exc_info=True)
            db_failed = True

    preview_result = DataImportService.preview_import(
        csv_content, entity, fk_caches=fk_caches, create_missing=create_missing,
        fk_stored=fk_stored,
    )
    if db_failed:
        # errors are plain strings elsewhere (template joins them with '; ');
        # keep the machine token as a prefix so tests/JS can detect it.
        preview_result["errors"].append(
            "db_unavailable: Database unavailable; foreign-key validation could not run"
        )
        preview_result["valid"] = False
    return jsonify({"success": True, "preview": preview_result})


@admin_data_import_bp.route("/upload/<entity>", methods=["POST"])
@login_required
@write_roles_required
@limiter.limit("10 per minute")
@audit_admin_action(
    "admin.data_import.upload", target_type="data_import", roles=WRITE_ROLES,
    detail_func=lambda r, *a, **kw: {"entity": kw.get("entity")},
)
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
    create_missing = request.form.get("create_missing") == "true"

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
            "products": {"sku", "name", "unit_price", "current_stock", "reorder_point", "category", "supplier_name"},
            "suppliers": {"name", "location", "lead_days"},
            "warehouses": {"warehouse_name", "location"},
            "movements": {"product_sku", "quantity", "type", "reason"},
            "purchase_orders": {"supplier_name", "product_sku", "quantity", "status"},
        }

        # Column aliases for flexible matching (matching DataImportService.COLUMN_ALIASES)
        column_aliases = {
            "products": {
                "product_name": "name",
                "price": "unit_price",
                "stock": "current_stock",
                "reorder": "reorder_point",
                "supplier": "supplier_name",
                "supplier_id": "supplier_name",      # backward compat
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
                "product_id": "product_sku",         # backward compat
            },
            "purchase_orders": {
                "qty": "quantity",
                "supplier_id": "supplier_name",      # backward compat
                "product_id": "product_sku",         # backward compat
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

        result = _import_rows(entity, rows, create_missing=create_missing)
        count = result["imported"]
        if count == 0:
            flash("No rows were imported. Check CSV format and data.", "warning")
        else:
            label = {"products": "Products", "suppliers": "Suppliers", "warehouses": "Warehouses", "movements": "Movements", "purchase_orders": "Purchase Orders"}.get(entity, entity)
            flash(f"Successfully imported {count} {label.lower()}.", "success")
        _flash_import_detail(result)
    except Exception as e:
        current_app.logger.error(f"Import error for {entity}: {e}")
        flash(f"Import failed: {e}", "error")

    return redirect(url_for("admin_data_import.index", tab=entity))

    return redirect(url_for("admin_data_import.index", tab=entity))


def _import_rows(entity: str, rows: list[dict], create_missing: bool = False) -> dict:
    """Insert rows with batched FK resolution.

    ``create_missing`` is opt-in and only affects products / purchase_orders:
    unknown ``supplier_name`` references are auto-created as supplier rows
    instead of the default skip / NULL-supplier behavior. Other entities
    ignore it (suppliers are only creatable as suppliers).

    Returns {"imported": int, "skipped": int, "errors": [...],
    "error_counts": {code: count}} where each error entry is one skipped row
    (retained detail capped at ``_MAX_RETAINED_ERRORS``; ``error_counts`` and
    ``skipped`` are full tallies).
    """
    if not rows:
        return _empty_result()

    # Build FK cache ONCE per import
    fk_cache = {}
    with get_cursor() as cur:
        fk_cache["suppliers"] = DataImportService._build_fk_cache(cur, "suppliers")
        fk_cache["products"] = DataImportService._build_fk_cache(cur, "products")
        fk_cache["warehouses"] = DataImportService._build_fk_cache(cur, "warehouses")

    lock_keys = {
        "products": 0x70726F64, "suppliers": 0x73757070, "warehouses": 0x77617265,
        "movements": 0x6D6F7665, "purchase_orders": 0x706F7264,
    }
    lock_key = lock_keys.get(entity, hash(entity) & 0x7FFFFFFF)

    if entity == "products":
        return _import_products(rows, lock_key, fk_cache, create_missing=create_missing)
    elif entity == "suppliers":
        return _import_suppliers(rows, lock_key)
    elif entity == "warehouses":
        return _import_warehouses(rows, lock_key)
    elif entity == "movements":
        return _import_movements(rows, fk_cache)
    elif entity == "purchase_orders":
        return _import_purchase_orders(rows, lock_key, fk_cache, create_missing=create_missing)
    return _empty_result()


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
    (RELEASE SAVEPOINT resets rowcount). Returns that rowcount (int) or None
    when the insert raised and the savepoint was rolled back — callers MUST
    treat None as a failed row. A 0 rowcount means the insert no-opped
    (e.g. ON CONFLICT DO NOTHING) and was not counted either.
    """
    cur.execute("SAVEPOINT row_sp")
    try:
        rowcount = insert_fn()
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT row_sp")
        # Release after rollback: unreleased savepoints accumulate as
        # subtransactions and slow the batch commit past ~64 of them.
        cur.execute("RELEASE SAVEPOINT row_sp")
        current_app.logger.warning("Import row insert failed", exc_info=True)
        return None
    cur.execute("RELEASE SAVEPOINT row_sp")
    return rowcount


def _import_products(rows: list[dict], lock_key: int, fk_cache: dict, create_missing: bool = False) -> dict:
    result = _empty_result()
    created_names: list[str] = []
    supplier_ids = set(fk_cache["suppliers"].values())
    def do_import(cur):
        for row_no, row in enumerate(rows, start=1):
            try:
                sku = (row.get("sku", "") or "").strip()
                name = (row.get("product_name", row.get("name", "")) or "").strip()
                price = _parse_number("unit_price", row.get("unit_price", row.get("price", 0)), float)
                stock = _parse_number("current_stock", row.get("current_stock", row.get("stock", 0)), int)
                reorder = _parse_number("reorder_point", row.get("reorder_point", row.get("reorder", 10)), int, default=10)
                category = (row.get("category", "General") or "").strip() or "General"
                supplier_name = (row.get("supplier_name", "") or "").strip()
                supplier_id = DataImportService.resolve_fk(cur, "suppliers", supplier_name, fk_cache["suppliers"])
                # Existence-checked numeric-ID fallback (legacy supplier_id CSVs).
                if not supplier_id and supplier_name.isdecimal() and int(supplier_name) in supplier_ids:
                    supplier_id = int(supplier_name)
                if not sku:
                    raise _RowSkip("missing_required", field="sku", value="", reason="missing required value: sku")
                if not name:
                    raise _RowSkip("missing_required", field="name", value="", reason="missing required value: name")
                if create_missing and not supplier_id and supplier_name:
                    # Miss is provably uncached (resolve_fk just checked), so a
                    # non-None return means created. shortcut: a concurrent
                    # different-entity import inserting the same name is a
                    # rare log-only overcount.
                    supplier_id = DataImportService.get_or_create_supplier(
                        cur, supplier_name, fk_cache["suppliers"]
                    )
                    if supplier_id is not None:
                        created_names.append(supplier_name)
                # shortcut: the row's later INSERT can still fail, leaving
                # this auto-created supplier behind (accepted on the products
                # path; purchase orders only create after product resolution).
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
                rowcount = _safe_row_insert(cur, _insert)
                if rowcount is None:
                    _record_skip(result, row_no, _RowSkip("db_error", reason="insert failed"))
                elif rowcount == 0:
                    _record_skip(result, row_no, _RowSkip("db_error", reason="insert affected 0 rows"))
                else:
                    result["imported"] += 1
            except _RowSkip as skip:
                _record_skip(result, row_no, skip)
            except Exception as exc:
                _record_skip(result, row_no, _RowSkip("db_error", reason=db_error_message(exc)))
        return result
    _execute_with_lock(lock_key, do_import)
    if create_missing:
        current_app.logger.info(
            "Auto-created %d supplier(s) during products import", len(created_names)
        )
        if created_names:
            current_app.logger.debug(
                "Auto-created suppliers during products import: %s", ", ".join(created_names)
            )
    return result


def _import_suppliers(rows: list[dict], lock_key: int) -> dict:
    result = _empty_result()
    def do_import(cur):
        for row_no, row in enumerate(rows, start=1):
            try:
                name = (row.get("supplier_name", row.get("name", "")) or "").strip()
                location = (row.get("location", "") or "").strip()
                # Real schema columns: suppliers has NO contact_email/phone/address.
                initials = "".join(part[0].upper() for part in name.split()[:2])[:10]
                lead_days = _parse_number("lead_days", row.get("lead_days", 0), int)
                if not name:
                    raise _RowSkip("missing_required", field="name", value="", reason="missing required value: name")
                # Dedup by active name: SELECT first (legacy exact match),
                # with the uq_suppliers_name_live partial unique index as the
                # backstop. Re-importing a SOFT-DELETED name now creates a
                # fresh active row (soft-delete convention).
                cur.execute(
                    "SELECT 1 FROM suppliers WHERE name = %s AND deleted_at IS NULL LIMIT 1",
                    (name,),
                )
                if cur.fetchone():
                    _record_skip(result, row_no, _RowSkip(
                        "already_exists", field="name", value=name, severity="info",
                        reason=f"supplier '{name}' already exists",
                    ))
                    continue
                def _insert():
                    cur.execute(
                        """INSERT INTO suppliers (name, initials, location, lead_days)
                           VALUES (%s, %s, %s, %s)""",
                        (name, initials, location, lead_days),
                    )
                    return cur.rowcount
                rowcount = _safe_row_insert(cur, _insert)
                if rowcount is None:
                    _record_skip(result, row_no, _RowSkip("db_error", reason="insert failed"))
                elif rowcount == 0:
                    _record_skip(result, row_no, _RowSkip("db_error", reason="insert affected 0 rows"))
                else:
                    result["imported"] += 1
            except _RowSkip as skip:
                _record_skip(result, row_no, skip)
            except Exception as exc:
                _record_skip(result, row_no, _RowSkip("db_error", reason=db_error_message(exc)))
        return result
    _execute_with_lock(lock_key, do_import)
    return result


def _import_warehouses(rows: list[dict], lock_key: int) -> dict:
    result = _empty_result()
    def do_import(cur):
        for row_no, row in enumerate(rows, start=1):
            try:
                name = (row.get("warehouse_name", row.get("name", "")) or "").strip()
                location = (row.get("location", "") or "").strip()
                if not name:
                    raise _RowSkip("missing_required", field="warehouse_name", value="", reason="missing required value: warehouse_name")
                def _insert():
                    cur.execute(
                        """INSERT INTO warehouses (warehouse_name, location)
                           VALUES (%s, %s)
                           ON CONFLICT (warehouse_name) DO NOTHING""",
                        (name, location),
                    )
                    return cur.rowcount
                rowcount = _safe_row_insert(cur, _insert)
                if rowcount is None:
                    _record_skip(result, row_no, _RowSkip("db_error", reason="insert failed"))
                elif rowcount == 0:
                    _record_skip(result, row_no, _RowSkip(
                        "already_exists", field="warehouse_name", value=name, severity="info",
                        reason=f"warehouse '{name}' already exists",
                    ))
                else:
                    result["imported"] += 1
            except _RowSkip as skip:
                _record_skip(result, row_no, skip)
            except Exception as exc:
                _record_skip(result, row_no, _RowSkip("db_error", reason=db_error_message(exc)))
        return result
    _execute_with_lock(lock_key, do_import)
    return result


def _import_movements(rows: list[dict], fk_cache: dict = None, lock_key: int = None) -> dict:
    """Import movement rows with MovementRepository.record (per-row committed
    transactions; stock floor enforced by sp_movement_record / trg_validate_movement).

    ``fk_cache`` may supply the pre-built natural-key caches; when omitted the
    product cache is built from the DB (legacy direct-call path). ``lock_key``
    is accepted for signature parity with the other importers but unused:
    movement rows commit individually, there is no batch advisory lock.
    """
    result = _empty_result()

    # Build FK cache if not provided (legacy call from tests)
    if fk_cache is None:
        with get_cursor() as cur:
            fk_cache = {
                "products": DataImportService._build_fk_cache(cur, "products"),
            }
    product_ids = set(fk_cache["products"].values())

    for row_no, row in enumerate(rows, start=1):
        try:
            # Support both product_sku (new) and product_id (legacy) columns
            sku = (row.get("product_sku", "") or "").strip()
            if not sku:
                # Legacy: product_id used directly (upload aliases it to product_sku)
                raw_pid = str(row.get("product_id", "") or "").strip()
                product_id = _parse_number("product_id", raw_pid, int)
                if not product_id:
                    raise _RowSkip("missing_required", field="product_id", value=raw_pid, reason="missing required value: product_id")
                if product_id not in product_ids:
                    raise _RowSkip("fk_product_not_found", field="product_id", value=raw_pid, reason=f"product_id '{raw_pid}' not found")
            else:
                # Natural key first (no cursor needed — pure cache lookup),
                # then the existence-checked numeric-ID fallback.
                product_id = DataImportService.resolve_fk(None, "products", sku, fk_cache["products"])
                if not product_id and sku.isdigit():
                    # .isdigit() (not .isdecimal()) is kept for backward compat:
                    # "²" passes it but int() raises -> invalid_number skip.
                    candidate = _parse_number("product_sku", sku, int)
                    if candidate in product_ids:
                        product_id = candidate
            if not product_id:
                raise _RowSkip("fk_product_not_found", field="product_sku", value=sku, reason=f"product_sku '{sku}' not found")

            qty = _parse_number("quantity", row.get("quantity", row.get("qty", 0)), int)
            movement_type = (row.get("movement_type", row.get("type", "IN")) or "").strip().upper()
            reason = (row.get("reason", "") or "").strip()
            
            if qty == 0:
                raise _RowSkip("quantity_not_positive", field="quantity", value=str(qty), reason=f"quantity must be positive: '{qty}'")
            if movement_type not in ("IN", "OUT", "ADJUSTMENT", "RETURN"):
                raise _RowSkip("invalid_movement_type", field="movement_type", value=movement_type, reason=f"movement_type '{movement_type}' is not valid")
            if qty < 0:
                raise _RowSkip("quantity_not_positive", field="quantity", value=str(qty), reason=f"quantity must be positive: '{qty}'")
            
            MovementRepository.record(
                product_id=product_id, mtype=movement_type, quantity=qty,
                reference=reason or None, notes=None, user_id=None,
            )
            result["imported"] += 1
        except _RowSkip as skip:
            _record_skip(result, row_no, skip)
        except MovementError as exc:
            message = str(exc)
            if "negative balance" in message:
                skip = _RowSkip("stock_violation", field="quantity", value=str(qty), reason=message)
            elif "not found" in message:
                skip = _RowSkip("fk_product_not_found", field="product_sku", value=sku, reason=message)
            elif "Type must be" in message:
                skip = _RowSkip("invalid_movement_type", field="movement_type", value=movement_type, reason=message)
            elif "positive integer" in message:
                skip = _RowSkip("quantity_not_positive", field="quantity", value=str(qty), reason=message)
            else:
                skip = _RowSkip("db_error", reason=message)
            _record_skip(result, row_no, skip)
        except Exception as exc:
            if is_guard_error(exc, "Insufficient stock", "Adjustment would create negative stock"):
                raw_qty = row.get("quantity", row.get("qty", ""))
                _record_skip(result, row_no, _RowSkip(
                    "stock_violation", field="quantity", value=str(raw_qty or ""),
                    reason=db_error_message(exc),
                ))
            else:
                _record_skip(result, row_no, _RowSkip("db_error", reason=db_error_message(exc)))
    return result


def _import_purchase_orders(rows: list[dict], lock_key: int, fk_cache: dict, create_missing: bool = False) -> dict:
    result = _empty_result()
    created_names: list[str] = []
    valid_statuses = {"draft", "approved", "in_transit", "received", "cancelled"}
    transition_paths = {
        "approved": ("approved",),
        "in_transit": ("approved", "in_transit"),
        "received": ("approved", "in_transit", "received"),
    }
    supplier_ids = set(fk_cache["suppliers"].values())
    product_ids = set(fk_cache["products"].values())
    def do_import(cur):
        for row_no, row in enumerate(rows, start=1):
            try:
                supplier_name = (row.get("supplier_name", "") or "").strip()
                sku = (row.get("product_sku", "") or "").strip()
                qty = _parse_number("quantity", row.get("quantity", row.get("qty", 0)), int)
                status = (row.get("status", "draft") or "").strip().lower()
                po_number = (row.get("po_number", "") or "").strip()
                if not supplier_name:
                    raise _RowSkip("missing_required", field="supplier_name", value="", reason="missing required value: supplier_name")
                if not sku:
                    raise _RowSkip("missing_required", field="product_sku", value="", reason="missing required value: product_sku")
                if qty <= 0:
                    raise _RowSkip("quantity_not_positive", field="quantity", value=str(qty), reason=f"quantity must be positive: '{qty}'")
                if status not in valid_statuses:
                    status = "draft"
                supplier_id = DataImportService.resolve_fk(cur, "suppliers", supplier_name, fk_cache["suppliers"])
                product_id = DataImportService.resolve_fk(cur, "products", sku, fk_cache["products"])
                # Existence-checked numeric-ID fallback (legacy supplier_id /
                # product_id CSVs): a bare decimal matching an existing id
                # resolves here — before any create path, so an existing id
                # is never shadowed by an auto-created supplier of that name.
                if not product_id and sku.isdecimal() and int(sku) in product_ids:
                    product_id = int(sku)
                if not supplier_id and supplier_name.isdecimal() and int(supplier_name) in supplier_ids:
                    supplier_id = int(supplier_name)
                # Product first: never create a supplier for a row that will
                # be skipped anyway (no orphan suppliers for unknown products).
                if not product_id:
                    raise _RowSkip("fk_product_not_found", field="product_sku", value=sku, reason=f"product_sku '{sku}' not found")
                if create_missing and not supplier_id and supplier_name:
                    # Miss is provably uncached (resolve_fk just checked), so a
                    # non-None return means created. shortcut: a concurrent
                    # different-entity import inserting the same name is a
                    # rare log-only overcount.
                    supplier_id = DataImportService.get_or_create_supplier(
                        cur, supplier_name, fk_cache["suppliers"]
                    )
                    if supplier_id is not None:
                        created_names.append(supplier_name)
                if not supplier_id:
                    raise _RowSkip("fk_supplier_not_found", field="supplier_name", value=supplier_name, reason=f"supplier_name '{supplier_name}' not found")
                if not po_number:
                    po_number = f"PO-{date.today():%Y%m%d}-{random.randint(1000, 9999)}"
                def _insert():
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
                rowcount = _safe_row_insert(cur, _insert)
                if rowcount is None:
                    _record_skip(result, row_no, _RowSkip("db_error", reason="insert failed"))
                elif rowcount == 0:
                    _record_skip(result, row_no, _RowSkip("db_error", reason="insert affected 0 rows"))
                else:
                    result["imported"] += 1
            except _RowSkip as skip:
                _record_skip(result, row_no, skip)
            except Exception as exc:
                _record_skip(result, row_no, _RowSkip("db_error", reason=db_error_message(exc)))
        return result
    _execute_with_lock(lock_key, do_import)
    if create_missing:
        current_app.logger.info(
            "Auto-created %d supplier(s) during purchase_orders import", len(created_names)
        )
        if created_names:
            current_app.logger.debug(
                "Auto-created suppliers during purchase_orders import: %s",
                ", ".join(created_names),
            )
    return result