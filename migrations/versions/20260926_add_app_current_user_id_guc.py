"""Register app.current_user_id GUC for audit trail context (DB-068).

Revision ID: 20260926_add_app_current_user_id_guc
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

revision = "20260926_add_app_current_user_id_guc"
down_revision = "20260925_db_integrity_fixes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Best-effort only: on managed Postgres this raises InsufficientPrivilege,
    # which we swallow — the per-transaction set_config path needs no registration.
    op.execute(
        """
        DO $$
        BEGIN
            BEGIN
                ALTER SYSTEM SET app.current_user_id = '';
                PERFORM pg_reload_conf();
            EXCEPTION WHEN insufficient_privilege OR feature_not_supported THEN
                NULL;  -- managed Postgres: app-level set_config suffices
            END;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            BEGIN
                ALTER SYSTEM RESET app.current_user_id;
                PERFORM pg_reload_conf();
            EXCEPTION WHEN insufficient_privilege OR feature_not_supported THEN
                NULL;
            END;
        END $$;
        """
    )
