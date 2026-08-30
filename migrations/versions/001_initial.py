"""Initial schema — captures current state of all tables, procedures, triggers.

Revision ID: 001_initial
Revises: None
Create Date: 2026-08-29
"""
from pathlib import Path
from alembic import op
import sqlalchemy as sa

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "app" / "database"


def _read_sql(filename: str) -> str:
    filepath = SCHEMA_DIR / filename
    if filepath.exists():
        return filepath.read_text(encoding="utf-8")
    return ""


def upgrade() -> None:
    # Apply all SQL files in order
    sql_files = [
        "schema.sql",
        "procedures.sql",
        "warehouse.sql",
        "etl_procedures.sql",
        "triggers.sql",
    ]
    for fname in sql_files:
        sql = _read_sql(fname)
        if sql:
            op.execute(sql)


def downgrade() -> None:
    # Drop everything in reverse order
    op.execute("DROP TRIGGER IF EXISTS trg_validate_movement ON movements CASCADE")
    op.execute("DROP TRIGGER IF EXISTS trg_movement_stock_update ON movements CASCADE")
    op.execute("DROP TRIGGER IF EXISTS trg_po_audit ON purchase_orders CASCADE")
    op.execute("DROP TRIGGER IF EXISTS trg_supplier_audit ON suppliers CASCADE")
    op.execute("DROP TRIGGER IF EXISTS trg_product_audit ON products CASCADE")
    op.execute("DROP TRIGGER IF EXISTS trg_session_end ON user_sessions CASCADE")
    op.execute("DROP TRIGGER IF EXISTS trg_session_create ON user_sessions CASCADE")
    op.execute("DROP TRIGGER IF EXISTS trg_user_signup ON users CASCADE")

    # Drop warehouse tables
    op.execute("DROP TABLE IF EXISTS fact_product_daily CASCADE")
    op.execute("DROP TABLE IF EXISTS fact_audit_daily CASCADE")
    op.execute("DROP TABLE IF EXISTS fact_signup_events CASCADE")
    op.execute("DROP TABLE IF EXISTS fact_session_activity CASCADE")
    op.execute("DROP TABLE IF EXISTS fact_login_events CASCADE")
    op.execute("DROP TABLE IF EXISTS dim_user CASCADE")
    op.execute("DROP TABLE IF EXISTS dim_warehouse_scd CASCADE")
    op.execute("DROP TABLE IF EXISTS dim_supplier_scd CASCADE")
    op.execute("DROP TABLE IF EXISTS dim_product_scd CASCADE")
    op.execute("DROP TABLE IF EXISTS etl_warehouse_state CASCADE")

    # Drop star schema
    op.execute("DROP TABLE IF EXISTS fact_inventory_daily CASCADE")
    op.execute("DROP TABLE IF EXISTS fact_movement_daily CASCADE")
    op.execute("DROP TABLE IF EXISTS dim_supplier CASCADE")
    op.execute("DROP TABLE IF EXISTS dim_product CASCADE")
    op.execute("DROP TABLE IF EXISTS dim_warehouse CASCADE")
    op.execute("DROP TABLE IF EXISTS dim_date CASCADE")
    op.execute("DROP TABLE IF EXISTS etl_state CASCADE")

    # Drop operational tables
    op.execute("DROP TABLE IF EXISTS forecast_cache CASCADE")
    op.execute("DROP TABLE IF EXISTS anomaly_log CASCADE")
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE")
    op.execute("DROP TABLE IF EXISTS user_settings CASCADE")
    op.execute("DROP TABLE IF EXISTS password_reset_tokens CASCADE")
    op.execute("DROP TABLE IF EXISTS user_sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS purchase_orders CASCADE")
    op.execute("DROP TABLE IF EXISTS movements CASCADE")
    op.execute("DROP TABLE IF EXISTS products CASCADE")
    op.execute("DROP TABLE IF EXISTS suppliers CASCADE")
    op.execute("DROP TABLE IF EXISTS users CASCADE")
