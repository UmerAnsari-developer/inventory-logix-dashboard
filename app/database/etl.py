"""ETL â€” build the star-schema data warehouse from the operational tables.

The warehouse dimensions (``dim_warehouse``) are read from the distinct
``products.warehouse`` values so the analytical layer always mirrors what the
application actually uses.

Idempotent and incremental: a high-water mark (``etl_state['last_movement_id']``)
is advanced after every run so subsequent runs only reprocess movements that are
new (or were edited after the previous watermark). A full rebuild happens when
``force=True`` or the fact tables are empty. Stages commit individually
(checkpointed stage-wise commits); the watermark only advances to ``max_id``
when the final stage commits, so a mid-run failure replays safely from the
previous mark.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import psycopg2
import psycopg2.extras
from psycopg2.extras import execute_values

from flask import current_app

from .connection import _open_conn

LOGGER = logging.getLogger(__name__)

INVENTORY_HISTORY_DAYS = 30

# DB-003: advisory-lock key serializing ETL runs across threads AND processes.
_ETL_LOCK_KEY = 774001

# "WH-Pune" -> code "WH-PUN", city "Pune". Legacy names map to regions.
_REGION_HINT = {
    "Pune": "Central",
    "Mumbai": "West",
    "Delhi": "North",
    "Bengaluru": "South",
    "Chennai": "South",
}


def _parse_warehouse(name: str) -> tuple[str, str, str]:
    """Split a warehouse display name into (code, city, region).

    Short codes look like ``WH-Pune`` -> code ``WH-PUN``, city ``Pune``.
    Legacy names like ``Warehouse 01 - Pune`` are still handled for old data.
    """
    body = name
    if " - " in name:
        body = name.split(" - ", 1)[1].strip()
    if body.startswith("WH-"):
        city = body[3:].strip() or "Unknown"
    else:
        city = body or "Unknown"
    digits = "".join(ch for ch in name if ch.isdigit()) or "00"
    code = (
        f"WH-{city[:3].upper()}"
        if name.startswith("WH-")
        else f"WH{digits[:2].zfill(2)}"
    )
    region = _REGION_HINT.get(city, "General")
    return code, city, region


def _iter_dates(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _read_state(cur, key: str, default=None):
    cur.execute("SELECT value FROM etl_state WHERE state_key = %s", (key,))
    row = cur.fetchone()
    return row["value"] if row else default


def _write_state(cur, key: str, value) -> None:
    cur.execute(
        """
        INSERT INTO etl_state (state_key, value, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (state_key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """,
        (key, str(value)),
    )


def _build_dim_dates(cur, start: date, end: date) -> int:
    """Insert any missing date rows in ``[start, end]``. Returns count added."""
    added = 0
    cur.execute(
        "SELECT date_key FROM dim_date WHERE date_key BETWEEN %s AND %s", (start, end)
    )
    existing = {r["date_key"] for r in cur.fetchall()}
    rows = []
    for d in _iter_dates(start, end):
        if d in existing:
            continue
        rows.append(
            (
                d,
                d.year,
                (d.month - 1) // 3 + 1,
                d.month,
                d.strftime("%b"),
                d.day,
                d.isoweekday(),
                int(d.strftime("%U")),
                d.weekday() >= 5,
            )
        )
        added += 1
    if rows:
        execute_values(
            cur,
            """
            INSERT INTO dim_date
                (date_key, year, quarter, month, month_name, day_of_month,
                 day_of_week, week, is_weekend)
            VALUES %s
            """,
            rows,
        )
    return added


def _build_dims(cur, summary: dict, product_range: tuple[date, date]) -> None:
    """Upsert warehouse/product/supplier dims. Adds any missing rows only."""
    cur.execute(
        "SELECT DISTINCT warehouse FROM products "
        "WHERE warehouse IS NOT NULL AND TRIM(warehouse) <> '' "
        "ORDER BY warehouse"
    )
    warehouse_names = [r["warehouse"].strip() for r in cur.fetchall()]
    cur.execute("SELECT warehouse_name, warehouse_key FROM dim_warehouse")
    existing_wh = {r["warehouse_name"]: r["warehouse_key"] for r in cur.fetchall()}
    used_codes: set[str] = set()
    cur.execute("SELECT warehouse_code FROM dim_warehouse")
    used_codes = {r["warehouse_code"] for r in cur.fetchall()}
    warehouse_keys: dict[str, int] = dict(existing_wh)
    new_wh: list[tuple[str, str, str, str]] = []
    for name in warehouse_names:
        if name in warehouse_keys:
            continue
        code, city, region = _parse_warehouse(name)
        if code in used_codes:  # keep codes unique even on collisions
            n = 2
            while f"{code}-{n}" in used_codes:
                n += 1
            code = f"{code}-{n}"
        used_codes.add(code)
        new_wh.append((code, name, city, region))
    if new_wh:
        returned = execute_values(
            cur,
            """
            INSERT INTO dim_warehouse (warehouse_code, warehouse_name, city, region)
            VALUES %s RETURNING warehouse_name, warehouse_key
            """,
            new_wh,
            fetch=True,
        )
        for name, key in returned:
            warehouse_keys[name] = key
            summary["dim_warehouses"] += 1

    cur.execute("SELECT id, sku, name, category, supplier_id, unit_price FROM products")
    products = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT sku, product_key FROM dim_product")
    existing_prod = {r["sku"]: r["product_key"] for r in cur.fetchall()}
    product_keys: dict[str, int] = dict(existing_prod)
    new_prod: list[tuple[str, str, str, int, float]] = []
    for p in products:
        if p["sku"] in product_keys:
            continue
        new_prod.append(
            (p["sku"], p["name"], p["category"], p["supplier_id"], p["unit_price"])
        )
    if new_prod:
        returned = execute_values(
            cur,
            """
            INSERT INTO dim_product
                (sku, product_name, category, supplier_id, unit_price)
            VALUES %s RETURNING sku, product_key
            """,
            new_prod,
            fetch=True,
        )
        for sku, key in returned:
            product_keys[sku] = key
            summary["dim_products"] += 1

    cur.execute("SELECT id, name, location, reliability, lead_days FROM suppliers")
    suppliers = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT supplier_id FROM dim_supplier WHERE supplier_id IS NOT NULL")
    existing_sup = {r["supplier_id"] for r in cur.fetchall()}
    new_sup: list[tuple[int, str, str, float, int]] = []
    for s in suppliers:
        if s["id"] in existing_sup:
            continue
        new_sup.append(
            (s["id"], s["name"], s["location"], s["reliability"], s["lead_days"])
        )
        existing_sup.add(s["id"])
    if new_sup:
        execute_values(
            cur,
            """
            INSERT INTO dim_supplier (supplier_id, supplier_name, location, reliability, lead_days)
            VALUES %s
            """,
            new_sup,
        )
        summary["dim_suppliers"] += len(new_sup)

    # Publish dim maps back onto the cursor-friendly namespace for fact build.
    cur.execute("SELECT warehouse_name, warehouse_key FROM dim_warehouse")
    _wh = {r["warehouse_name"]: r["warehouse_key"] for r in cur.fetchall()}
    cur.execute("SELECT sku, product_key FROM dim_product")
    _pk = {r["sku"]: r["product_key"] for r in cur.fetchall()}
    cur._etl_warehouse_keys = _wh
    cur._etl_product_keys = _pk


def _build_movement_facts(cur, start: date, end: date) -> int:
    """(Re)aggregate fact_movement_daily for days in [start, end]. Returns rows."""
    cur.execute(
        "DELETE FROM fact_movement_daily WHERE date_key BETWEEN %s AND %s",
        (start, end),
    )
    cur.execute(
        """
        INSERT INTO fact_movement_daily
            (date_key, warehouse_key, product_key, in_qty, out_qty,
             net_qty, in_value, out_value)
        SELECT m.created_at::date AS day,
                dw.warehouse_key,
                dp.product_key,
                COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.quantity ELSE 0 END), 0) AS in_qty,
                COALESCE(SUM(CASE WHEN m.type = 'OUT' THEN m.quantity ELSE 0 END), 0) AS out_qty,
                COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.quantity
                                  WHEN m.type = 'OUT' THEN -m.quantity ELSE 0 END), 0) AS net_qty,
                COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.quantity * dp.unit_price ELSE 0 END), 0) AS in_value,
                COALESCE(SUM(CASE WHEN m.type = 'OUT' THEN m.quantity * dp.unit_price ELSE 0 END), 0) AS out_value
        FROM movements m
        JOIN products p ON p.id = m.product_id
        JOIN dim_product dp ON dp.sku = p.sku
        JOIN dim_warehouse dw ON dw.warehouse_name = p.warehouse
        WHERE m.created_at::date BETWEEN %s AND %s
        GROUP BY m.created_at::date, dw.warehouse_key, dp.product_key
        ON CONFLICT (date_key, warehouse_key, product_key) DO NOTHING
        """,
        (start, end),
    )
    return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0


def _build_inventory_facts(cur, end_day: date, start_day: date | None = None) -> int:
    """Reconstruct stock history for days in ``[start_day, end_day]``.

    Uses a SQL window function to do the backward stock walk in one query
    instead of a Python loop over products Ã— days.
    """
    if start_day is None:
        start_day = end_day - timedelta(days=INVENTORY_HISTORY_DAYS - 1)
    cur.execute(
        "DELETE FROM fact_inventory_daily WHERE date_key BETWEEN %s AND %s",
        (start_day, end_day),
    )
    wh_keys = getattr(cur, "_etl_warehouse_keys", {})
    prod_keys = getattr(cur, "_etl_product_keys", {})
    if not wh_keys or not prod_keys:
        return 0
    # Build the warehouse/product key lookup arrays for SQL
    wh_names = list(wh_keys.keys())
    wh_ids = [wh_keys[n] for n in wh_names]
    prod_skus = list(prod_keys.keys())
    prod_ids = [prod_keys[s] for s in prod_skus]
    cur.execute(
        """
        WITH daily_net AS (
            SELECT m.product_id, m.created_at::date AS day,
                    SUM(CASE WHEN m.type='IN' THEN m.quantity
                             WHEN m.type='OUT' THEN -m.quantity ELSE 0 END) AS net
            FROM movements m
            WHERE m.created_at::date BETWEEN %s AND %s
            GROUP BY m.product_id, m.created_at::date
        ),
        product_days AS (
            SELECT p.id, p.warehouse, p.current_stock, p.reorder_point, p.unit_price,
                    gs::date AS day
            FROM products p
            CROSS JOIN generate_series(%s::date, %s::date, '1 day'::interval) gs
            WHERE p.id = ANY(%s)
        )
        SELECT pd.day, pd.warehouse, pd.id,
                pd.current_stock - COALESCE(
                    SUM(dn.net) OVER (
                        PARTITION BY pd.id ORDER BY pd.day DESC
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0
                ) AS stock_on_hand,
                pd.reorder_point, pd.unit_price
        FROM product_days pd
        LEFT JOIN daily_net dn ON dn.product_id = pd.id AND dn.day = pd.day
        ORDER BY pd.id, pd.day
        """,
        (start_day, end_day, start_day, end_day, prod_ids),
    )
    rows = []
    for r in cur.fetchall():
        wh_key = wh_keys.get(r["warehouse"])
        prod_key = prod_keys.get(r["id"])
        if wh_key is None or prod_key is None:
            continue
        stock = max(float(r["stock_on_hand"] or 0), 0.0)
        price = float(r["unit_price"] or 0)
        rows.append(
            (
                r["day"],
                wh_key,
                prod_key,
                stock,
                float(r["reorder_point"] or 0),
                stock * price,
            )
        )
    if rows:
        execute_values(
            cur,
            """
            INSERT INTO fact_inventory_daily
                (date_key, warehouse_key, product_key, stock_on_hand, reorder_point, inventory_value)
            VALUES %s
            """,
            rows,
        )
    return len(rows)


def _safe_error(e: BaseException) -> str:
    """Log-safe error text (F7): class name for DB connection-class errors
    (libpq messages embed host/port/user), str(e) otherwise."""
    if isinstance(e, (psycopg2.OperationalError, psycopg2.InterfaceError)):
        return type(e).__name__
    return str(e)


def _retry_operation(func, max_retries=3, base_delay=1, max_delay=10):
    """Retry an operation with exponential backoff for transient errors."""
    for attempt in range(max_retries):
        try:
            return func()
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            if attempt == max_retries - 1:  # Last attempt
                LOGGER.error(
                    f"Operation failed after {max_retries} attempts: "
                    f"{_safe_error(e)}"
                )
                raise
            delay = min(base_delay * (2**attempt), max_delay)
            LOGGER.warning(
                f"Transient error on attempt {attempt + 1}: {_safe_error(e)}. "
                f"Retrying in {delay}s..."
            )
            time.sleep(delay)
        except Exception as e:
            # Non-transient error, don't retry (sanitized per F7)
            LOGGER.error(f"Non-transient error: {_safe_error(e)}")
            raise


def _build_dim_dates_with_retry(cur, start: date, end: date) -> int:
    """Build dimension dates with retry logic."""

    def operation():
        return _build_dim_dates(cur, start, end)

    return _retry_operation(operation)


def _build_dims_with_retry(
    cur, summary: dict, product_range: tuple[date, date]
) -> None:
    """Build dimensions with retry logic."""

    def operation():
        _build_dims(cur, summary, product_range)

    return _retry_operation(operation)


def _build_movement_facts_with_retry(cur, start: date, end: date) -> int:
    """Build movement facts with retry logic."""

    def operation():
        return _build_movement_facts(cur, start, end)

    return _retry_operation(operation)


def _build_inventory_facts_with_retry(
    cur, end_day: date, start_day: date | None = None
) -> int:
    """Build inventory facts with retry logic."""

    def operation():
        return _build_inventory_facts(cur, end_day, start_day)

    return _retry_operation(operation)


def _validate_warehouse_consistency(cur) -> bool:
    """Validate warehouse consistency after ETL load."""
    try:
        # Check that all products have valid warehouse mappings
        cur.execute("""
            SELECT COUNT(*) 
            FROM products p 
            LEFT JOIN dim_warehouse dw ON dw.warehouse_name = p.warehouse
            WHERE p.warehouse IS NOT NULL AND TRIM(p.warehouse) <> '' 
            AND dw.warehouse_key IS NULL
            """)
        orphaned_products = cur.fetchone()["count"]

        if orphaned_products > 0:
            LOGGER.warning(
                f"Found {orphaned_products} products with invalid warehouse mappings"
            )
            return False

        return True
    except Exception as e:
        LOGGER.error(f"Error during warehouse consistency validation: {_safe_error(e)}")
        return False


def _validate_product_consistency(cur) -> bool:
    """Validate product consistency after ETL load."""
    try:
        # Check that all movements have valid product mappings
        cur.execute("""
            SELECT COUNT(*) 
            FROM movements m 
            LEFT JOIN dim_product dp ON dp.sku = (SELECT sku FROM products WHERE id = m.product_id)
            WHERE dp.product_key IS NULL
            """)
        orphaned_movements = cur.fetchone()["count"]

        if orphaned_movements > 0:
            LOGGER.warning(
                f"Found {orphaned_movements} movements with invalid product mappings"
            )
            return False

        return True
    except Exception as e:
        LOGGER.error(f"Error during product consistency validation: {_safe_error(e)}")
        return False


def run_etl(force: bool = False) -> dict:
    """Populate the star-schema tables. Returns a summary dict."""
    summary = {
        "skipped": False,
        "incremental": False,
        "dim_dates": 0,
        "dim_warehouses": 0,
        "dim_products": 0,
        "dim_suppliers": 0,
        "fact_movements": 0,
        "fact_inventory": 0,
        "warehouse_etl_ok": True,  # F6: flipped to False if warehouse ETL fails
    }
    conn = None
    try:
        conn = _retry_operation(_open_conn)
        with conn.cursor() as cur:
            # Release any stale advisory lock from previous pooled connection use
            # (advisory locks are session-level and persist across pooled connections).
            cur.execute("SELECT pg_advisory_unlock(%s)", (_ETL_LOCK_KEY,))

            # DB-003: single-run guard. Session-level advisory lock.
            # Must be explicitly released before returning connection to pool
            # (advisory locks are session-level and persist across pooled connections).
            cur.execute("SELECT pg_try_advisory_lock(%s) AS locked", (_ETL_LOCK_KEY,))
            if not cur.fetchone()["locked"]:
                summary["skipped"] = True
                LOGGER.info(
                    "ETL skipped: another ETL run is already in progress."
                )
                # Release lock before early return
                cur.execute("SELECT pg_advisory_unlock(%s)", (_ETL_LOCK_KEY,))
                return summary

            cur.execute("SELECT 1 FROM fact_movement_daily LIMIT 1")
            facts_exist = cur.fetchone() is not None

            if facts_exist and not force:
                # ---- incremental run ----------------------------------------
                last_id = int(_read_state(cur, "last_movement_id", 0) or 0)
                cur.execute("SELECT MAX(id) AS max_id FROM movements")
                max_id = (cur.fetchone() or {}).get("max_id") or 0
                if max_id <= last_id:
                    summary["skipped"] = True
                    LOGGER.info(
                        "ETL skipped: no new movements since watermark %s.", last_id
                    )
                    # Release lock before early return
                    cur.execute("SELECT pg_advisory_unlock(%s)", (_ETL_LOCK_KEY,))
                    return summary

                today = date.today()
                cur.execute(
                    """
                    SELECT MIN(created_at)::date AS first, MAX(created_at)::date AS last
                    FROM movements WHERE id > %s
                    """,
                    (last_id,),
                )
                bounds = cur.fetchone()
                first_day = bounds["first"] or today
                last_day = max(bounds["last"] or today, today)
                summary["incremental"] = True

                # Stage 1: Build dimension dates
                try:
                    added_dates = _build_dim_dates_with_retry(cur, first_day, last_day)
                    summary["dim_dates"] = added_dates
                    _write_state(
                        cur, "last_movement_id", last_id
                    )  # Checkpoint after dimension dates
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass  # F4: never mask the original stage error
                    raise

                # Stage 2: Build dimensions
                try:
                    _build_dims_with_retry(cur, summary, (first_day, last_day))
                    _write_state(
                        cur, "last_movement_id", last_id
                    )  # F1: hold watermark at incoming last_id until final stage
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass  # F4: never mask the original stage error
                    raise

                # Stage 3: Build movement facts
                try:
                    movements_count = _build_movement_facts_with_retry(
                        cur, first_day, last_day
                    )
                    summary["fact_movements"] = movements_count
                    _write_state(
                        cur, "last_movement_id", last_id
                    )  # F1: hold watermark at incoming last_id until final stage
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass  # F4: never mask the original stage error
                    raise

                # Stage 4: Build inventory facts
                try:
                    inventory_count = _build_inventory_facts_with_retry(
                        cur, today, first_day
                    )
                    summary["fact_inventory"] = inventory_count
                    _write_state(
                        cur, "last_movement_id", max_id
                    )  # Checkpoint after inventory facts
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass  # F4: never mask the original stage error
                    raise

            else:
                # ---- full rebuild -------------------------------------------  # TEST
                # For full rebuild, we'll do it in one transaction for simplicity
                # but we could break it down further if needed
                cur.execute("""
                TRUNCATE dim_date, dim_warehouse, dim_product, dim_supplier,
                         fact_movement_daily, fact_inventory_daily
                RESTART IDENTITY CASCADE
                """)
                # F2 (strategy B): CASCADE wipes fact_audit_daily (FK ->
                # dim_date); dropping the loader watermark in the SAME
                # transaction makes etl_load_audit_daily rebuild full history.
                cur.execute(
                    "DELETE FROM etl_warehouse_state "
                    "WHERE state_key = 'last_audit_daily_at'"
                )
                cur.execute("SELECT MIN(created_at)::date AS first FROM movements")
                first = (cur.fetchone() or {}).get("first")
                start = first or (date.today() - timedelta(days=90))
                end = date.today()

                # Get max movement ID for watermark updates
                cur.execute("SELECT MAX(id) AS max_id FROM movements")
                max_id = (cur.fetchone() or {}).get("max_id") or 0

                # Stage 1: Build dimension dates
                try:
                    summary["dim_dates"] = _build_dim_dates_with_retry(cur, start, end)
                    _write_state(
                        cur, "last_movement_id", 0
                    )  # Reset watermark for full rebuild
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass  # F4: never mask the original stage error
                    raise

                # Stage 2: Build dimensions
                try:
                    _build_dims_with_retry(cur, summary, (start, end))
                    _write_state(
                        cur, "last_movement_id", 0
                    )  # Keep at 0 until we have data
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass  # F4: never mask the original stage error
                    raise

                # Stage 3: Build movement facts
                try:
                    summary["fact_movements"] = _build_movement_facts_with_retry(
                        cur, start, end
                    )
                    _write_state(
                        cur, "last_movement_id", 0
                    )  # Keep at 0 until we have data
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass  # F4: never mask the original stage error
                    raise

                # Stage 4: Build inventory facts
                try:
                    summary["fact_inventory"] = _build_inventory_facts_with_retry(
                        cur, end
                    )
                    _write_state(
                        cur, "last_movement_id", max_id
                    )  # Checkpoint after inventory facts
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass  # F4: never mask the original stage error
                    raise

            # Validation step: check consistency after load
            try:
                warehouse_valid = _validate_warehouse_consistency(cur)
                product_valid = _validate_product_consistency(cur)

                if not warehouse_valid or not product_valid:
                    LOGGER.warning(
                        "ETL completed but consistency validation failed"
                    )
                    # Don't fail the ETL, but log the issue
                else:
                    LOGGER.info(
                        "ETL completed successfully with consistency validation passed"
                    )
            except Exception as e:
                LOGGER.error(f"Error during validation step: {e}")
                # Don't fail the ETL for validation errors

            _write_state(cur, "last_run_at", date.today().isoformat())

        # F5: commit bookkeeping before warehouse ETL so its rollback cannot
        # discard last_run_at.
        conn.commit()

        # Run warehouse layer ETL (SCD merges + event fact loads) - same connection
        try:
            _run_warehouse_etl(conn)
        except Exception as e:
            summary["warehouse_etl_ok"] = False  # F6
            LOGGER.error(
                "Warehouse ETL failed (non-fatal): %s", _safe_error(e)
            )

        # Release advisory lock before returning connection to pool
        # (advisory locks are session-level and persist across pooled connections)
        try:
            cur = conn.cursor()
            cur.execute("SELECT pg_advisory_unlock(%s)", (_ETL_LOCK_KEY,))
            cur.close()
        except Exception:
            pass  # Best effort

        return summary
    except Exception as e:
        LOGGER.error(f"ETL failed: {_safe_error(e)}")
        # Release advisory lock on error too
        try:
            if conn and not conn.closed:
                cur = conn.cursor()
                cur.execute("SELECT pg_advisory_unlock(%s)", (_ETL_LOCK_KEY,))
                cur.close()
        except Exception:
            pass
        raise
    finally:
        if conn:
            conn.close()


def _run_warehouse_etl(conn=None):
    """Call warehouse stored procedures for SCD merges + event fact loads."""
    own_conn = conn is None
    if own_conn:
        conn = _open_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM etl_full_build()")
            results = cur.fetchall()
            for row in results:
                LOGGER.info(
                    "Warehouse ETL: %s = %s rows",
                    row["step_name"],
                    row["rows_affected"],
                )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass  # F4: never mask the original error
        raise
    finally:
        if own_conn:
            conn.close()
