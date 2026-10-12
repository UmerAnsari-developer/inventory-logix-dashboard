"""GAP-010: pg_cron schedules for backup, verification, and retention.

Revision ID: 20261012_backup_schedule
Revises: c631f3054dac
Create Date: 2026-10-12

Schedules (only when pg_cron is available — degrades gracefully otherwise):
  - daily full backup at 02:00       -> job_queue_enqueue('create_backup', ...)
  - weekly verification Sun 03:00    -> job_queue_enqueue('verify_latest_backup', ...)
  - daily retention cleanup 04:00    -> job_queue_enqueue('cleanup_old_backups', ...)

Jobs are enqueued into job_queue; an external worker (or in-app worker) must
process them. Without pg_cron, enqueue these from an external scheduler.
"""
from alembic import op

revision = "20261012_backup_schedule"
down_revision = "c631f3054dac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        DECLARE
            _has_pg_cron boolean;
        BEGIN
            SELECT EXISTS (
                SELECT 1 FROM pg_available_extensions WHERE name = 'pg_cron'
            ) INTO _has_pg_cron;

            IF _has_pg_cron THEN
                CREATE EXTENSION IF NOT EXISTS pg_cron;

                PERFORM cron.schedule('daily-backup', '0 2 * * *',
                    'SELECT job_queue_enqueue(''create_backup'', jsonb_build_object(''backup_name'', ''daily_'' || to_char(now(), ''YYYYMMDD'')));');

                PERFORM cron.schedule('weekly-backup-verify', '0 3 * * 0',
                    'SELECT job_queue_enqueue(''verify_latest_backup'', ''{}''::jsonb);');

                PERFORM cron.schedule('backup-retention', '0 4 * * *',
                    'SELECT job_queue_enqueue(''cleanup_old_backups'', jsonb_build_object(''retention_days'', 30));');
            ELSE
                RAISE NOTICE 'pg_cron not available - backup schedules skipped (enqueue jobs from an external scheduler).';
            END IF;
        EXCEPTION
            WHEN insufficient_privilege THEN
                RAISE NOTICE 'Insufficient privilege for pg_cron - backup schedules skipped.';
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            PERFORM cron.unschedule('daily-backup');
            PERFORM cron.unschedule('weekly-backup-verify');
            PERFORM cron.unschedule('backup-retention');
        EXCEPTION
            WHEN undefined_object THEN
                NULL;  -- pg_cron not available, nothing to unschedule
            WHEN insufficient_privilege THEN
                NULL;
        END $$;
    """)