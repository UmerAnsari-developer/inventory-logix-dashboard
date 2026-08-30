"""ETL — build the star-schema data warehouse from the operational tables.

The warehouse dimensions (``dim_warehouse``) are read from the distinct
``products.warehouse`` values so the analytical layer always mirrors what the
application actually uses.

Idempotent and incremental: a high-water mark (``etl_state['last_movement_id']``)
is advanced after every run so subsequent runs only reprocess movements that are
new (or were edited after the previous watermark). A full rebuild happens when
``force=True`` or the fact tables are empty. The whole build runs in one
transaction so a failure leaves the previous state intact.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import psycopg2.extras
from psycopg2.extras import execute_values

from flask import current_app

LOGGER = logging.getLogger(__name__)

INVENTORY_HISTORY_DAYS = 30

# "WH-Pune" -> code "WH-PUN", city "Pune". Legacy names map to regions.
_REGION_HINT = {
    "Pune": "Central",
    "Mumbai": "West",
    "Delhi": "North",
    "Bengaluru": "South",
    "Chennai": "South",
}


def _open_conn():
    params = current_app.config["psycopg2_params"]()
    if "dsn" in params:
        return psycopg2.connect(
            params["dsn"], cursor_factory=psycopg2.extras.RealDictCursor
        )
    return psycopg2.connect(
        cursor_factory=psycopg2.extras.RealDictCursor, **params
    )


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
    code = f"WH-{city[:3].upper()}" if name.startswith("WH-") else f"WH{digits[:2].zfill(2)}"
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
    cur.execute("SELECT date_key FROM dim_date WHERE date_key BETWEEN %s AND %s", (start, end))
    existing = {r["date_key"] for r in cur.fetchall()}
    rows = []
    for d in _iter_dates(start, end):
        if d in existing:
            continue
        rows.append(
            (
                d, d.year, (d.month - 1) // 3 + 1, d.month,
                d.strftime("%b"), d.day, d.isoweekday(),
                int(d.strftime("%U")), d.weekday() >= 5,
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

    cur.execute(
        "SELECT id, name, location, reliability, lead_days FROM suppliers"
    )
    suppliers = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT supplier_id FROM dim_supplier WHERE supplier_id IS NOT NULL")
    existing_sup = {r["supplier_id"] for r in cur.fetchall()}
    new_sup: list[tuple[int, str, str, float, int]] = []
    for s in suppliers:
        if s["id"] in existing_sup:
            continue
        new_sup.append((s["id"], s["name"], s["location"], s["reliability"], s["lead_days"]))
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
        JOIN dim_product dp ON dp.sku = m.sku
        JOIN products p ON p.sku = m.sku
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

    Walks the movement history backwards from ``products.current_stock``, so
    the value stored for a day only depends on movements *after* that day.
    For incremental runs ``start_day`` is the earliest day touched by new
    movements; days before it are unchanged and left alone. For a full build
    ``start_day`` defaults to the start of the trailing window.
    """
    if start_day is None:
        start_day = end_day - timedelta(days=INVENTORY_HISTORY_DAYS - 1)
    cur.execute(
        "DELETE FROM fact_inventory_daily WHERE date_key BETWEEN %s AND %s",
        (start_day, end_day),
    )
    cur.execute(
        "SELECT sku, warehouse, current_stock, reorder_point, unit_price FROM products"
    )
    products = [dict(r) for r in cur.fetchall()]
    cur.execute(
        """
        SELECT m.sku, m.created_at::date AS day,
               COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.quantity
                                 WHEN m.type = 'OUT' THEN -m.quantity ELSE 0 END), 0) AS net
        FROM movements m
        WHERE m.created_at::date BETWEEN %s AND %s
        GROUP BY m.sku, m.created_at::date
        """,
        (start_day, end_day),
    )
    net_by_sku_day: dict[tuple[str, date], float] = {}
    for r in cur.fetchall():
        net_by_sku_day[(r["sku"], r["day"])] = float(r["net"])

    wh_keys = getattr(cur, "_etl_warehouse_keys", {})
    prod_keys = getattr(cur, "_etl_product_keys", {})
    days_list = [
        end_day - timedelta(days=i)
        for i in range((end_day - start_day).days + 1)
    ]
    rows: list[tuple[date, int, int, float, float, float]] = []
    negative_clamped = 0
    for p in products:
        wh_key = wh_keys.get(p["warehouse"])
        prod_key = prod_keys.get(p["sku"])
        if wh_key is None or prod_key is None:
            continue
        rop = float(p["reorder_point"] or 0)
        price = float(p["unit_price"] or 0)
        stock = float(p["current_stock"] or 0)
        for d in days_list:
            rows.append((d, wh_key, prod_key, stock, rop, stock * price))
            stock -= net_by_sku_day.get((p["sku"], d), 0)
            if stock < 0:
                negative_clamped += 1
                stock = 0.0
    if negative_clamped:
        LOGGER.warning(
            "Inventory backward walk: clamped %d negative stock values to 0 "
            "(data inconsistency in movement history)", negative_clamped,
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


def run_etl(force: bool = False) -> dict:
    """Populate the star-schema tables. Returns a summary dict."""
    conn = _open_conn()
    summary = {
        "skipped": False,
        "incremental": False,
        "dim_dates": 0,
        "dim_warehouses": 0,
        "dim_products": 0,
        "dim_suppliers": 0,
        "fact_movements": 0,
        "fact_inventory": 0,
    }
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM fact_movement_daily")
            fact_count = (cur.fetchone() or {}).get("c", 0)

            if fact_count and not force:
                # ---- incremental run ----------------------------------------
                last_id = int(_read_state(cur, "last_movement_id", 0) or 0)
                cur.execute("SELECT MAX(id) AS max_id FROM movements")
                max_id = (cur.fetchone() or {}).get("max_id") or 0
                if max_id <= last_id:
                    summary["skipped"] = True
                    LOGGER.info("ETL skipped: no new movements since watermark %s.", last_id)
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

                added_dates = _build_dim_dates(cur, first_day, last_day)
                summary["dim_dates"] = added_dates
                _build_dims(cur, summary, (first_day, last_day))
                summary["fact_movements"] = _build_movement_facts(cur, first_day, last_day)
                # Rebuild inventory only from the earliest day affected by the
                # new movements forward; earlier days are unchanged.
                summary["fact_inventory"] = _build_inventory_facts(cur, today, first_day)
                _write_state(cur, "last_movement_id", max_id)
                _write_state(cur, "last_run_at", today.isoformat())
            else:
                # ---- full rebuild -------------------------------------------
                cur.execute(
                    """
                    TRUNCATE dim_date, dim_warehouse, dim_product, dim_supplier,
                             fact_movement_daily, fact_inventory_daily
                    RESTART IDENTITY CASCADE
                    """
                )
                cur.execute("SELECT MIN(created_at)::date AS first FROM movements")
                first = (cur.fetchone() or {}).get("first")
                start = first or (date.today() - timedelta(days=90))
                end = date.today()
                summary["dim_dates"] = _build_dim_dates(cur, start, end)
                _build_dims(cur, summary, (start, end))
                summary["fact_movements"] = _build_movement_facts(cur, start, end)
                summary["fact_inventory"] = _build_inventory_facts(cur, end)

                cur.execute("SELECT MAX(id) AS max_id FROM movements")
                max_id = (cur.fetchone() or {}).get("max_id") or 0
                _write_state(cur, "last_movement_id", max_id)
                _write_state(cur, "last_run_at", end.isoformat())

        conn.commit()
        LOGGER.info("ETL complete%s: %s", " (incremental)" if summary["incremental"] else "", summary)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # Run warehouse layer ETL (SCD merges + event fact loads)
    try:
        _run_warehouse_etl()
    except Exception:
        LOGGER.warning("Warehouse ETL failed (non-fatal):", exc_info=True)

    return summary


def _run_warehouse_etl():
    """Call warehouse stored procedures for SCD merges and event fact loads."""
    conn = _open_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM etl_full_build()")
            results = cur.fetchall()
            for row in results:
                LOGGER.info("Warehouse ETL: %s = %s rows", row["step_name"], row["rows_affected"])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()