"""ETL pipeline tests: full rebuild, incremental runs, and high-water marks."""
from __future__ import annotations

import pytest


def _etl_state(cur):
    cur.execute("SELECT state_key, value FROM etl_state ORDER BY state_key")
    return {r["state_key"]: r["value"] for r in cur.fetchall()}


def test_etl_full_build_populates_star_schema(app):
    from app.database.connection import etl_database
    with app.app_context():
        result = etl_database(force=True)
        assert result["skipped"] is False
        assert result["dim_warehouses"] > 0
        assert result["dim_products"] > 0
        assert result["fact_movements"] > 0

        from app.database import get_cursor
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM fact_movement_daily")
            assert cur.fetchone()["c"] == result["fact_movements"]
            state = _etl_state(cur)
            assert "last_movement_id" in state
            assert int(state["last_movement_id"]) > 0


def test_etl_skips_when_no_new_movements(app):
    from app.database.connection import etl_database
    with app.app_context():
        etl_database(force=True)
        result = etl_database()
        assert result["skipped"] is True


def test_etl_incremental_processes_new_movements(app):
    from app.database.connection import etl_database
    from app.database import get_cursor
    with app.app_context():
        etl_database(force=True)
        with get_cursor() as cur:
            cur.execute("SELECT value FROM etl_state WHERE state_key='last_movement_id'")
            before = int(cur.fetchone()["value"])

        with get_cursor(commit=True) as cur:
            # Grab any real product from the seeded catalogue; the synthetic
            # seeder mints SKU-DC-* codes so we cannot hardcode a fixture SKU.
            cur.execute("SELECT id, sku, warehouse FROM products ORDER BY id LIMIT 1")
            row = cur.fetchone()
            pid, sku, wh = row["id"], row["sku"], row["warehouse"]
            cur.execute(
                """
                INSERT INTO movements (product_id, sku, type, quantity, reference, notes, created_at)
                VALUES (%s, %s, 'OUT', 12, 'TEST-ETL', 'incremental test', NOW())
                """,
                (pid, sku),
            )

        result = etl_database()
        assert result["incremental"] is True
        assert result["skipped"] is False

        with get_cursor() as cur:
            cur.execute("SELECT value FROM etl_state WHERE state_key='last_movement_id'")
            after = int(cur.fetchone()["value"])
            assert after > before
            # The affected day's OUT qty for this sku must have grown.
            cur.execute(
                """
                SELECT f.out_qty
                FROM fact_movement_daily f
                JOIN dim_warehouse dw ON dw.warehouse_key = f.warehouse_key
                JOIN dim_product dp ON dp.product_key = f.product_key
                WHERE dw.warehouse_name = %s
                  AND dp.sku = %s
                  AND f.date_key = CURRENT_DATE
                """,
                (wh, sku),
            )
            out_qty = cur.fetchone()
            assert out_qty is not None
            assert out_qty["out_qty"] >= 12