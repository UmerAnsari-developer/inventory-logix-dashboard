"""Enable RLS on all public tables (Supabase security advisory fix).

Supabase exposes every table through its auto-generated REST API.
With RLS disabled, anyone with the project URL can read/modify data.
Enable RLS with zero policies: public API = deny-all. The Flask app
connects as the table owner (bypasses RLS), so it keeps working.

Revision ID: 003_enable_rls
Revises: 002_critical_fixes
Create Date: 2026-09-04
"""
from alembic import op

revision = "003_enable_rls"
down_revision = "002_critical_fixes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        DECLARE
            t TEXT;
        BEGIN
            FOR t IN
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename NOT LIKE 'pg_%'
                  AND tablename NOT LIKE 'schema_%'
            LOOP
                EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
            END LOOP;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        DECLARE
            t TEXT;
        BEGIN
            FOR t IN
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename NOT LIKE 'pg_%'
                  AND tablename NOT LIKE 'schema_%'
            LOOP
                EXECUTE format('ALTER TABLE public.%I DISABLE ROW LEVEL SECURITY', t);
            END LOOP;
        END $$;
    """)
