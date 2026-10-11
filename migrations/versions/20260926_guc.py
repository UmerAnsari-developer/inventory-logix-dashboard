"""Register app.current_user_id GUC for audit trail context (DB-068).

Revision ID: 20260926_guc
Revises: 20260925_db_integrity_fixes
Create Date: 2026-09-26

NOTE: The GUC needs NO server-side registration — the app sets it
per-transaction via set_config() and current_app_user_id() handles the
unset case. ALTER SYSTEM requires superuser/pg_alter_system and fails on
managed Postgres (Render/Supabase), so this migration is a best-effort
no-op there: it swallows the privilege error and lets the app-level
mechanism work regardless.
"""
from alembic import op
from sqlalchemy import create_engine, text
import os


revision = "20260926_guc"
down_revision = "20260925_db_integrity_fixes"
branch_labels = None
depends_on = None


def _execute_autocommit(sql: str) -> None:
    """Execute SQL with autocommit (outside transaction block) using a fresh engine."""
    # Get database URL from environment or Alembic config
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        # Fallback to alembic.ini config
        from alembic import context
        db_url = context.config.get_main_option("sqlalchemy.url")
    
    if not db_url or db_url == "driver://user:pass@localhost/dbname":
        raise RuntimeError("DATABASE_URL not configured")
    
    # Create a new engine with autocommit isolation level
    engine = create_engine(db_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(sql))
    finally:
        engine.dispose()


def upgrade() -> None:
    # Best-effort only: on managed Postgres this raises InsufficientPrivilege,
    # which we swallow — the per-transaction set_config path needs no registration.
    try:
        _execute_autocommit("ALTER SYSTEM SET app.current_user_id = ''")
        _execute_autocommit("SELECT pg_reload_conf()")
    except Exception as e:
        # Best-effort only: on managed Postgres this raises InsufficientPrivilege,
        # which we swallow — the per-transaction set_config path needs no registration.
        import logging
        logging.warning(f"Could not set app.current_user_id GUC: {e}")


def downgrade() -> None:
    try:
        _execute_autocommit("ALTER SYSTEM RESET app.current_user_id")
        _execute_autocommit("SELECT pg_reload_conf()")
    except Exception as e:
        import logging
        logging.warning(f"Could not reset app.current_user_id GUC: {e}")