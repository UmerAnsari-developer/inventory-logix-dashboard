"""Enable pg_cron extension for job queue scheduling (GAP-012).

Revision ID: 20261008_enable_pg_cron
Revises: 20261008_create_job_queue_table
Create Date: 2026-10-08
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20261008_enable_pg_cron"
down_revision = "20261008_create_job_queue_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pg_cron extension and schedule jobs.
    # Check if pg_cron is available before trying to create it.
    op.execute("""
        DO $$
        DECLARE
            _has_pg_cron boolean;
        BEGIN
            -- Check if pg_cron is available in the PostgreSQL installation
            SELECT EXISTS (
                SELECT 1 FROM pg_available_extensions WHERE name = 'pg_cron'
            ) INTO _has_pg_cron;
            
            IF _has_pg_cron THEN
                -- Try to create the extension
                CREATE EXTENSION IF NOT EXISTS pg_cron;
                
                -- Schedule job processor (every minute)
                PERFORM cron.schedule('job-queue-processor', '* * * * *', 'SELECT job_queue_process_batch(100);');
                
                -- Schedule cleanup (daily at 2 AM)
                PERFORM cron.schedule('job-queue-cleanup', '0 2 * * *', 'SELECT job_queue_cleanup(interval ''30 days'');');
            ELSE
                RAISE NOTICE 'pg_cron extension not available in this PostgreSQL installation. Job queue will require external worker.';
            END IF;
        EXCEPTION
            WHEN insufficient_privilege THEN
                RAISE NOTICE 'Insufficient privilege to create pg_cron extension. Job queue will require external worker.';
        END $$;
    """)


def downgrade() -> None:
    # Unschedule pg_cron jobs
    op.execute("""
        DO $$
        BEGIN
            PERFORM cron.unschedule('job-queue-processor');
            PERFORM cron.unschedule('job-queue-cleanup');
        EXCEPTION
            WHEN undefined_object THEN
                -- pg_cron not available, nothing to do
                NULL;
            WHEN insufficient_privilege THEN
                RAISE NOTICE 'Insufficient privilege to unschedule pg_cron jobs.';
        END $$;
    """)
    # Note: We don't drop the extension as it may be used by other migrations