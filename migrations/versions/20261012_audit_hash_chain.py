"""GAP-011: tamper-evident audit log (SHA-256 hash chain) + retention schedule.

Revision ID: 20261012_audit_hash_chain
Revises: 20261012_backup_schedule
Create Date: 2026-10-12

- audit_log.prev_hash / row_hash columns (TEXT, hex digests)
- sp_audit_compute_hash(): SINGLE source of the canonical hash input — used by
  the insert trigger, the backfill, and the verification function
- Backfill chains all existing rows (12k rows locally — seconds)
- trg_audit_hash_chain BEFORE INSERT: serializes via transaction-level
  advisory lock so concurrent inserts can never fork the chain. The lock is
  always acquired AFTER the triggering DML's row locks (consistent order, no
  deadlock). ponytail: global chain lock — per-table sharding if audit write
  throughput ever matters.
- sp_audit_verify_integrity(p_limit): recomputes hashes and checks linkage
- pg_cron daily sp_retention_run_all() (graceful when pg_cron unavailable —
  the purge procedures already exist; only scheduling is added)
"""
from alembic import op

revision = "20261012_audit_hash_chain"
down_revision = "20261012_backup_schedule"
branch_labels = None
depends_on = None

# Single source of truth for the hashed payload. Keep in sync with NOTHING
# else — trigger, backfill and verifier all call sp_audit_compute_hash.
_HASH_FN = """
CREATE OR REPLACE FUNCTION sp_audit_compute_hash(
    p_prev TEXT, p_user_id INT, p_action TEXT, p_target_type TEXT,
    p_target_id INT, p_detail JSONB, p_ip TEXT, p_created TIMESTAMP
) RETURNS TEXT AS $$
    SELECT encode(digest(
        COALESCE(p_prev, '') || '|' ||
        COALESCE(p_user_id::TEXT, '') || '|' ||
        COALESCE(p_action, '') || '|' ||
        COALESCE(p_target_type, '') || '|' ||
        COALESCE(p_target_id::TEXT, '') || '|' ||
        COALESCE(p_detail::TEXT, '') || '|' ||
        COALESCE(p_ip, '') || '|' ||
        COALESCE(p_created::TEXT, ''),
        'sha256'), 'hex')
$$ LANGUAGE sql IMMUTABLE;
"""

_BACKFILL = """
-- Idempotent: chains only rows whose row_hash is NULL, seeding the chain
-- from the last already-chained row (safe on re-run).
DO $$
DECLARE
    r RECORD;
    v_prev TEXT;
    v_hash TEXT;
BEGIN
    SELECT row_hash INTO v_prev FROM audit_log
    WHERE row_hash IS NOT NULL ORDER BY id DESC LIMIT 1;

    FOR r IN SELECT id, user_id, action, target_type, target_id, detail,
                    ip_address, created_at
             FROM audit_log WHERE row_hash IS NULL ORDER BY id
    LOOP
        v_hash := sp_audit_compute_hash(v_prev, r.user_id, r.action,
                    r.target_type, r.target_id, r.detail, r.ip_address,
                    r.created_at);
        UPDATE audit_log
        SET prev_hash = v_prev, row_hash = v_hash
        WHERE id = r.id;
        v_prev := v_hash;
    END LOOP;
END $$;
"""

_TRIGGER = """
CREATE OR REPLACE FUNCTION trg_fn_audit_hash_chain()
RETURNS TRIGGER AS $$
DECLARE
    v_prev TEXT;
BEGIN
    -- Serialize chain appends: two concurrent inserts must never read the
    -- same predecessor. Released at transaction end.
    PERFORM pg_advisory_xact_lock(hashtext('audit_log_hash_chain'));

    SELECT row_hash INTO v_prev FROM audit_log ORDER BY id DESC LIMIT 1;

    NEW.prev_hash := v_prev;
    NEW.row_hash := sp_audit_compute_hash(v_prev, NEW.user_id, NEW.action,
        NEW.target_type, NEW.target_id, NEW.detail, NEW.ip_address,
        NEW.created_at);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_hash_chain ON audit_log;
CREATE TRIGGER trg_audit_hash_chain
BEFORE INSERT ON audit_log
FOR EACH ROW EXECUTE FUNCTION trg_fn_audit_hash_chain();
"""

_VERIFY = """
CREATE OR REPLACE FUNCTION sp_audit_verify_integrity(p_limit INT DEFAULT 10000)
RETURNS TABLE (rows_checked BIGINT, broken_links BIGINT, bad_hashes BIGINT,
               first_broken_id INT) AS $$
DECLARE
    r RECORD;
    v_prev_expected TEXT := NULL;   -- NULL => chain start (or pre-chain row)
    v_checked BIGINT := 0;
    v_broken BIGINT := 0;
    v_bad BIGINT := 0;
    v_first_broken INT := NULL;
BEGIN
    FOR r IN
        SELECT * FROM (
            SELECT id, user_id, action, target_type, target_id, detail,
                   ip_address, created_at, prev_hash, row_hash
            FROM audit_log ORDER BY id DESC LIMIT p_limit
        ) recent ORDER BY id
    LOOP
        v_checked := v_checked + 1;
        -- Linkage: first scanned row may legitimately start the chain.
        IF v_prev_expected IS NOT NULL
           AND COALESCE(r.prev_hash, '') <> COALESCE(v_prev_expected, '') THEN
            v_broken := v_broken + 1;
            IF v_first_broken IS NULL THEN v_first_broken := r.id; END IF;
        END IF;
        -- Content: stored hash must match a recompute from row data.
        IF COALESCE(r.row_hash, '') <> COALESCE(sp_audit_compute_hash(
                r.prev_hash, r.user_id, r.action, r.target_type,
                r.target_id, r.detail, r.ip_address, r.created_at), '') THEN
            v_bad := v_bad + 1;
            IF v_first_broken IS NULL THEN v_first_broken := r.id; END IF;
        END IF;
        v_prev_expected := r.row_hash;
    END LOOP;
    rows_checked := v_checked;
    broken_links := v_broken;
    bad_hashes := v_bad;
    first_broken_id := v_first_broken;
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;
"""

_SCHEDULE = """
DO $$
DECLARE
    _has_pg_cron boolean;
BEGIN
    SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_cron')
    INTO _has_pg_cron;
    IF _has_pg_cron THEN
        CREATE EXTENSION IF NOT EXISTS pg_cron;
        PERFORM cron.schedule('audit-retention', '30 3 * * *',
            'SELECT sp_retention_run_all();');
    ELSE
        RAISE NOTICE 'pg_cron not available - audit retention schedule skipped.';
    END IF;
EXCEPTION
    WHEN insufficient_privilege THEN
        RAISE NOTICE 'Insufficient privilege for pg_cron - retention schedule skipped.';
END $$;
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")  # digest(); contrib, available locally
    op.execute("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS prev_hash TEXT;")
    op.execute("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS row_hash TEXT;")
    op.execute(_HASH_FN)
    op.execute(_BACKFILL)
    op.execute(_TRIGGER)
    op.execute(_VERIFY)
    op.execute(_SCHEDULE)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_hash_chain ON audit_log;")
    op.execute("DROP FUNCTION IF EXISTS trg_fn_audit_hash_chain();")
    op.execute("DROP FUNCTION IF EXISTS sp_audit_verify_integrity(integer);")
    op.execute("DROP FUNCTION IF EXISTS sp_audit_compute_hash(TEXT,INT,TEXT,TEXT,INT,JSONB,TEXT,TIMESTAMP);")
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS row_hash;")
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS prev_hash;")
    op.execute("""
        DO $$
        BEGIN
            PERFORM cron.unschedule('audit-retention');
        EXCEPTION WHEN undefined_object THEN NULL; WHEN insufficient_privilege THEN NULL;
        END $$;
    """)