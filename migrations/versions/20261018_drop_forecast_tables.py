"""drop retired forecast/anomaly tables — Feature Removal (2026-10-18).

Demand Forecasting and Anomaly Detection were removed from the product
(code, routes, templates, tests). This migration drops the seven tables that
existed solely for those features, including their data. Irreversible by
design: downgrade() is deliberately a no-op.

NOTE: the revision id is 29 chars — Alembic's default
``alembic_version.version_num`` is VARCHAR(32).

Revision ID: 20261018_drop_forecast_tables
Revises: 20261017_supplier_live_unique
Create Date: 2026-10-18
"""
from alembic import op

revision = "20261018_drop_forecast_tables"
down_revision = "20261017_supplier_live_unique"
branch_labels = None
depends_on = None

_TABLES = (
    "forecast_cache",
    "anomaly_log",
    "forecast_predictions",
    "forecast_monitoring_metrics",
    "forecast_backtest_results",
    "anomaly_fatigue_daily",
    "model_baselines",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table};")


def downgrade() -> None:
    # Irreversible: the dropped tables carried retired-feature data.
    pass
