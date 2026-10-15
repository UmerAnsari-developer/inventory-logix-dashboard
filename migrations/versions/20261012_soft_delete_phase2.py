"""GAP-020 phase 2: audit triggers for soft deletes + analytics/ETL filters.

Revision ID: 20261012_soft_delete_phase2
Revises: 20261012_soft_delete_ops
Create Date: 2026-10-12

Closes the phase-1 "hidden but counted" boundary:

- Audit: trg_log_po_change logs 'po_deleted' on deleted_at NULL->NOT NULL;
  new trg_movement_soft_delete trigger logs 'movement_deleted' on the same
  transition (mirrors the products DB-068 pattern in triggers.sql).
- Analytics: sp_movement_daily_totals / sp_movement_daily_inout /
  sp_movement_daily_for_product / sp_movement_units_today exclude soft-deleted
  movements. Raw-SQL dashboard/reports/monitoring/services/ETL filters live in
  the application code (same commit).
- ETL: _build_movement_facts filters m.deleted_at IS NULL going forward;
  historical fact rows retain pre-phase-2 contributions (incremental ETL never
  revisits past days). The MAX(id) watermark stays unfiltered — soft-deleted
  rows still exist and must advance it.

Downgrade restores the ORIGINAL trigger/proc bodies verbatim BEFORE anything
else references the filtered shapes.
"""
from alembic import op

revision = "20261012_soft_delete_phase2"
down_revision = "20261012_soft_delete_ops"
branch_labels = None
depends_on = None

# ── upgrade: audit triggers ──────────────────────────────────────────────────
# trg_log_po_change: new po_deleted branch (copied verbatim from triggers.sql).
# trg_movement_soft_delete: new function + WHEN-scoped trigger.
_TRIGGERS_UP = """
CREATE OR REPLACE FUNCTION trg_log_po_change()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
        VALUES (current_app_user_id(), 'po_created', 'purchase_order', NEW.id,
                jsonb_build_object('po_number', NEW.po_number, 'status', NEW.status));
    ELSIF TG_OP = 'UPDATE' AND OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL THEN
        -- GAP-020 phase 2: soft delete (deleted_at NULL -> NOT NULL) is an UPDATE
        -- to the database but a DELETE to the business — log it as po_deleted.
        INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
        VALUES (current_app_user_id(), 'po_deleted', 'purchase_order', OLD.id,
                jsonb_build_object('po_number', OLD.po_number, 'status', OLD.status));
    ELSIF TG_OP = 'UPDATE' AND OLD.status != NEW.status THEN
        INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
        VALUES (current_app_user_id(), 'po_status_changed', 'purchase_order', NEW.id,
                jsonb_build_object(
                    'po_number', NEW.po_number,
                    'old_status', OLD.status,
                    'new_status', NEW.status
                ));
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION trg_log_movement_soft_delete()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
    VALUES (
        current_app_user_id(),
        'movement_deleted',
        'movement',
        OLD.id,
        jsonb_build_object(
            'product_id', OLD.product_id,
            'sku', (SELECT sku FROM products WHERE id = OLD.product_id),
            'type', OLD.type,
            'quantity', OLD.quantity,
            'reference', OLD.reference
        )
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_movement_soft_delete ON movements;
CREATE TRIGGER trg_movement_soft_delete
    AFTER UPDATE ON movements
    FOR EACH ROW
    WHEN (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL)
    EXECUTE FUNCTION trg_log_movement_soft_delete();
"""

# ── upgrade: filtered analytics procs (copied verbatim from procedures.sql
#    + `AND deleted_at IS NULL` on the movements alias) ────────────────────────
_PROCS_FILTERED = """
CREATE OR REPLACE FUNCTION sp_movement_daily_totals(p_days INT DEFAULT 14)
RETURNS TABLE(day DATE, total BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT date_trunc('day', m.created_at)::date AS day,
           COALESCE(SUM(m.quantity), 0)::BIGINT AS total
    FROM movements m
    WHERE m.created_at >= (CURRENT_DATE - (p_days - 1))
      AND m.deleted_at IS NULL
    GROUP BY day ORDER BY day;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_movement_daily_inout(p_days INT DEFAULT 14)
RETURNS TABLE(day DATE, in_qty BIGINT, out_qty BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT date_trunc('day', m.created_at)::date AS day,
           COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.quantity ELSE 0 END), 0)::BIGINT AS in_qty,
           COALESCE(SUM(CASE WHEN m.type = 'OUT' THEN m.quantity ELSE 0 END), 0)::BIGINT AS out_qty
    FROM movements m
    WHERE m.created_at >= (CURRENT_DATE - (p_days - 1))
      AND m.deleted_at IS NULL
    GROUP BY day ORDER BY day;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_movement_daily_for_product(
    p_product_id INT, p_days INT DEFAULT 90
) RETURNS TABLE(day DATE, total BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT d.day::date,
           COALESCE(m.total, 0)::BIGINT AS total
    FROM generate_series(
             (CURRENT_DATE - (p_days - 1))::date,
             CURRENT_DATE,
             '1 day'::interval
         ) AS d(day)
    LEFT JOIN (
        SELECT date_trunc('day', m.created_at)::date AS day,
               COALESCE(SUM(CASE WHEN m.type = 'OUT' THEN m.quantity ELSE 0 END), 0)::BIGINT AS total
        FROM movements m
        WHERE m.created_at >= (CURRENT_DATE - (p_days - 1))
          AND m.product_id = p_product_id
          AND m.deleted_at IS NULL
        GROUP BY day
    ) m ON m.day = d.day::date
    ORDER BY d.day;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_movement_units_today()
RETURNS BIGINT AS $$
DECLARE
    total BIGINT;
BEGIN
    SELECT COALESCE(SUM(quantity), 0) INTO total
    FROM movements WHERE created_at::date = CURRENT_DATE AND deleted_at IS NULL;
    RETURN total;
END;
$$ LANGUAGE plpgsql;
"""

# ── downgrade: original bodies verbatim (pre-phase-2) ────────────────────────
_TRIGGERS_DOWN = """
CREATE OR REPLACE FUNCTION trg_log_po_change()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
        VALUES (current_app_user_id(), 'po_created', 'purchase_order', NEW.id,
                jsonb_build_object('po_number', NEW.po_number, 'status', NEW.status));
    ELSIF TG_OP = 'UPDATE' AND OLD.status != NEW.status THEN
        INSERT INTO audit_log (user_id, action, target_type, target_id, detail)
        VALUES (current_app_user_id(), 'po_status_changed', 'purchase_order', NEW.id,
                jsonb_build_object(
                    'po_number', NEW.po_number,
                    'old_status', OLD.status,
                    'new_status', NEW.status
                ));
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_movement_soft_delete ON movements;
DROP FUNCTION IF EXISTS trg_log_movement_soft_delete();
"""

_PROCS_ORIGINAL = """
CREATE OR REPLACE FUNCTION sp_movement_daily_totals(p_days INT DEFAULT 14)
RETURNS TABLE(day DATE, total BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT date_trunc('day', m.created_at)::date AS day,
           COALESCE(SUM(m.quantity), 0)::BIGINT AS total
    FROM movements m
    WHERE m.created_at >= (CURRENT_DATE - (p_days - 1))
    GROUP BY day ORDER BY day;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_movement_daily_inout(p_days INT DEFAULT 14)
RETURNS TABLE(day DATE, in_qty BIGINT, out_qty BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT date_trunc('day', m.created_at)::date AS day,
           COALESCE(SUM(CASE WHEN m.type = 'IN' THEN m.quantity ELSE 0 END), 0)::BIGINT AS in_qty,
           COALESCE(SUM(CASE WHEN m.type = 'OUT' THEN m.quantity ELSE 0 END), 0)::BIGINT AS out_qty
    FROM movements m
    WHERE m.created_at >= (CURRENT_DATE - (p_days - 1))
    GROUP BY day ORDER BY day;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_movement_daily_for_product(
    p_product_id INT, p_days INT DEFAULT 90
) RETURNS TABLE(day DATE, total BIGINT) AS $$
BEGIN
    RETURN QUERY
    SELECT d.day::date,
           COALESCE(m.total, 0)::BIGINT AS total
    FROM generate_series(
             (CURRENT_DATE - (p_days - 1))::date,
             CURRENT_DATE,
             '1 day'::interval
         ) AS d(day)
    LEFT JOIN (
        SELECT date_trunc('day', m.created_at)::date AS day,
               COALESCE(SUM(CASE WHEN m.type = 'OUT' THEN m.quantity ELSE 0 END), 0)::BIGINT AS total
        FROM movements m
        WHERE m.created_at >= (CURRENT_DATE - (p_days - 1))
          AND m.product_id = p_product_id
        GROUP BY day
    ) m ON m.day = d.day::date
    ORDER BY d.day;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_movement_units_today()
RETURNS BIGINT AS $$
DECLARE
    total BIGINT;
BEGIN
    SELECT COALESCE(SUM(quantity), 0) INTO total
    FROM movements WHERE created_at::date = CURRENT_DATE;
    RETURN total;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute(_TRIGGERS_UP)
    op.execute(_PROCS_FILTERED)


def downgrade() -> None:
    op.execute(_TRIGGERS_DOWN)
    op.execute(_PROCS_ORIGINAL)
