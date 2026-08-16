"""Populate a target database (default: the .env-configured DB) with the full
demo dataset and rebuild the star schema.

Wipes ALL tables first (completely clean data), then seeds:
  - 3 demo users
  - 36 real-world suppliers
  - the real-world DataCo product catalogue spread across 10 warehouses
  - a movement ledger from Jan 2024 -> today (5000-8000 rows)
  - ~25 purchase orders

Usage:
    python scripts/populate_demo.py            # uses DB from .env
    python scripts/populate_demo.py --local    # forces localhost DB_* params
    python scripts/populate_demo.py --db <name>  # local DB name to target

After seeding it runs a forced ETL rebuild so the Analytics/warehouse/report
modules read from the freshly built star schema.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# --- Env setup must happen BEFORE importing anything from `app`, because
# `app/__init__.py` calls load_dotenv() and settings.py captures the env at
# class-definition time.
os.environ.setdefault("FLASK_ENV", "development")
if "--local" in sys.argv:
    # load_dotenv() will not override an already-set var, so pin DATABASE_URL to
    # an empty string BEFORE app modules are imported.
    os.environ["DATABASE_URL"] = ""
    os.environ.setdefault("DB_HOST", "localhost")
    os.environ.setdefault("DB_PORT", "5432")
    os.environ.setdefault("DB_NAME", "inventory_db")
    os.environ.setdefault("DB_USER", "postgres")
    os.environ.setdefault("DB_PASSWORD", "Um%25ans12er")
    os.environ.setdefault("DB_SSLMODE", "")
    for i, arg in enumerate(sys.argv):
        if arg == "--db" and i + 1 < len(sys.argv):
            os.environ["DB_NAME"] = sys.argv[i + 1]

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
from flask import Flask  # noqa: E402

from app.config import get_config  # noqa: E402
from app.database.connection import init_schema  # noqa: E402
from app.database.etl import run_etl  # noqa: E402
from app.database.seed import run_seed  # noqa: E402

TRUNCATE_SQL = """
TRUNCATE TABLE
    movements, purchase_orders, products, suppliers, users,
    audit_log, forecast_cache, anomaly_log, user_settings,
    password_reset_tokens,
    dim_date, dim_warehouse, dim_product, dim_supplier,
    fact_movement_daily, fact_inventory_daily, etl_state
RESTART IDENTITY CASCADE
"""

VERIFY_SQL = """
SELECT
  (SELECT COUNT(*) FROM users) AS users,
  (SELECT COUNT(*) FROM suppliers) AS suppliers,
  (SELECT COUNT(*) FROM products) AS products,
  (SELECT COUNT(DISTINCT warehouse) FROM products) AS wh,
  (SELECT COUNT(*) FROM movements) AS movements,
  (SELECT COUNT(*) FROM purchase_orders) AS pos,
  (SELECT COUNT(*) FROM fact_movement_daily) AS fact_mov,
  (SELECT COUNT(*) FROM fact_inventory_daily) AS fact_inv
"""


def _app() -> Flask:
    config_cls = get_config("development")
    app = Flask(
        __name__,
        template_folder=str(PROJECT_ROOT / "app" / "templates"),
        static_folder=str(PROJECT_ROOT / "app" / "static"),
    )
    app.root_path = str(PROJECT_ROOT / "app")
    app.config.from_object(config_cls)
    app.config["psycopg2_params"] = config_cls.psycopg2_params
    return app


def _open_conn(app: Flask):
    params = app.config["psycopg2_params"]()
    if "dsn" in params:
        return psycopg2.connect(
            params["dsn"], cursor_factory=psycopg2.extras.RealDictCursor
        )
    return psycopg2.connect(
        cursor_factory=psycopg2.extras.RealDictCursor, **params
    )


def main() -> None:
    app = _app()
    params = app.config["psycopg2_params"]()
    target = "DATABASE_URL (from .env)" if "dsn" in params else f"DB_* params ({params.get('host')}/{params.get('dbname')})"
    print(f"Target database: {target}")

    with app.app_context():
        print("Applying schema...")
        init_schema()

        print("Wiping all tables...")
        conn = _open_conn(app)
        try:
            with conn.cursor() as cur:
                cur.execute(TRUNCATE_SQL)
            conn.commit()
        finally:
            conn.close()

        print("Seeding demo dataset...")
        run_seed(force=True)

        print("Rebuilding star schema (forced ETL)...")
        summary = run_etl(force=True)
        print("ETL summary:", summary)

        print("\n--- Verification ---")
        conn = _open_conn(app)
        try:
            with conn.cursor() as cur:
                cur.execute(VERIFY_SQL)
                row = cur.fetchone()
        finally:
            conn.close()
        for key in ("users", "suppliers", "products", "wh", "movements",
                    "pos", "fact_mov", "fact_inv"):
            print(f"{key:>12}: {row[key]}")
    print("Done.")


if __name__ == "__main__":
    main()