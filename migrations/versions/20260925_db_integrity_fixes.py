"""db integrity fixes — D-1..D-8 (see Fix/02_plan.md)

Mirrors every change made to schema.sql / procedures.sql / triggers.sql so
existing databases (where bootstrap skips init_schema) converge to the same
state as fresh installs.

Revision ID: 20260925_db_integrity_fixes
Revises: 20260924191107
Create Date: 2026-09-25
"""
from alembic import op

revision = "20260925_db_integrity_fixes"
down_revision = "20260924191107"
branch_labels = None
depends_on = None


def _run(sql: str) -> None:
    """Execute raw SQL on the underlying driver connection.

    SQLAlchemy's exec_driver_sql still passes a (possibly empty) parameters
    container to psycopg2, which then tries to %-substitute the RAISE EXCEPTION
    format strings ('have %, need %') and %ROWTYPE in function bodies. The raw
    DBAPI cursor with vars=None sends the statement untouched.
    """
    conn = op.get_bind().connection
    raw = getattr(conn, "driver_connection", None) or conn.dbapi_connection
    with raw.cursor() as cur:
        cur.execute(sql)


_SP_MOVEMENT_RECORD = """
CREATE OR REPLACE FUNCTION sp_movement_record(
    p_product_id INT, p_type VARCHAR, p_quantity INT,
    p_reference VARCHAR DEFAULT NULL, p_notes TEXT DEFAULT NULL,
    p_user_id INT DEFAULT NULL
) RETURNS INT AS $$
DECLARE
    new_id INT;
    v_stock INT;
    v_delta INT;
BEGIN
    SELECT current_stock INTO v_stock
    FROM products
    WHERE id = p_product_id AND deleted_at IS NULL
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Invalid product_id %: product does not exist', p_product_id;
    END IF;

    IF p_type IN ('IN', 'RETURN', 'ADJUSTMENT') THEN
        v_delta := p_quantity;
    ELSIF p_type = 'OUT' THEN
        v_delta := -p_quantity;
    ELSE
        RAISE EXCEPTION 'Invalid movement type %', p_type;
    END IF;

    v_stock := COALESCE(v_stock, 0);
    IF v_stock + v_delta < 0 THEN
        RAISE EXCEPTION 'Insufficient stock: have %, need %', v_stock, p_quantity;
    END IF;

    INSERT INTO movements (product_id, type, quantity, reference, notes, user_id)
    VALUES (p_product_id, p_type, p_quantity, p_reference, p_notes, p_user_id)
    RETURNING id INTO new_id;

    UPDATE products
    SET current_stock = v_stock + v_delta, updated_at = NOW()
    WHERE id = p_product_id;

    RETURN new_id;
END;
$$ LANGUAGE plpgsql;
"""

_SP_PO_TRANSITION = """
CREATE OR REPLACE FUNCTION sp_po_transition(p_id INT, p_new_status VARCHAR)
RETURNS VOID AS $$
DECLARE
    po purchase_orders%ROWTYPE;
BEGIN
    SELECT * INTO po FROM purchase_orders WHERE id = p_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Purchase order % not found', p_id;
    END IF;
    IF po.status = p_new_status THEN
        RETURN;  -- idempotent re-apply
    END IF;
    IF NOT (
        (po.status = 'draft'       AND p_new_status IN ('approved', 'cancelled')) OR
        (po.status = 'approved'    AND p_new_status IN ('in_transit', 'cancelled')) OR
        (po.status = 'in_transit'  AND p_new_status IN ('received', 'cancelled'))
    ) THEN
        RAISE EXCEPTION 'Invalid PO transition: % -> %', po.status, p_new_status;
    END IF;

    IF po.product_id IS NOT NULL AND p_new_status = 'received' THEN
        UPDATE products
        SET current_stock = current_stock + po.quantity,
            on_order = GREATEST(on_order - po.quantity, 0),
            updated_at = NOW()
        WHERE id = po.product_id;
    ELSIF po.product_id IS NOT NULL AND p_new_status = 'cancelled' THEN
        UPDATE products
        SET on_order = GREATEST(on_order - po.quantity, 0),
            updated_at = NOW()
        WHERE id = po.product_id;
    END IF;

    UPDATE purchase_orders SET status = p_new_status, updated_at = NOW() WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;
"""

_SP_SUPPLIER_LIST_ALL = """
CREATE OR REPLACE FUNCTION sp_supplier_list_all()
RETURNS TABLE (
    id INT, name VARCHAR, initials VARCHAR, location VARCHAR,
    lead_days INT, spend_amount NUMERIC, reliability NUMERIC, tone VARCHAR,
    created_at TIMESTAMP, deleted_at TIMESTAMP, active_skus BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT s.*, COUNT(p.id) AS active_skus
    FROM suppliers s
    LEFT JOIN products p ON p.supplier_id = s.id
    WHERE s.deleted_at IS NULL
    GROUP BY s.id ORDER BY s.name;
END;
$$ LANGUAGE plpgsql;
"""

_SP_SUPPLIER_FIND = """
CREATE OR REPLACE FUNCTION sp_supplier_find(p_id INT)
RETURNS SETOF suppliers AS $$
BEGIN
    RETURN QUERY SELECT * FROM suppliers WHERE id = p_id AND deleted_at IS NULL;
END;
$$ LANGUAGE plpgsql;
"""

_SP_SUPPLIER_DELETE = """
CREATE OR REPLACE FUNCTION sp_supplier_delete(p_id INT)
RETURNS VOID AS $$
BEGIN
    UPDATE suppliers SET deleted_at = NOW() WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;
"""

# D-2: collapsed single soft-delete definition (procedures.sql had three
# order-dependent overwrites; only one survives there — ship it here too so
# migrated DBs match fresh installs).
_SP_PRODUCT_DELETE = """
DROP FUNCTION IF EXISTS sp_product_delete(integer);
CREATE FUNCTION sp_product_delete(p_id INT)
RETURNS VOID AS $$
BEGIN
    UPDATE products SET deleted_at = NOW() WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;
"""

_SKU_CONSTRAINT_DO = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_index i
        WHERE i.indrelid = 'products'::regclass
          AND i.indisunique
          AND i.indnkeyatts = 1
          AND (SELECT a.attname FROM pg_attribute a
                WHERE a.attrelid = i.indrelid AND a.attnum = i.indkey[0]) = 'sku'
    ) THEN
        UPDATE products p
           SET sku = LEFT(p.sku, 44) || '#' || p.id
         WHERE EXISTS (
               SELECT 1 FROM products q
                WHERE q.sku = p.sku AND q.id < p.id);
        ALTER TABLE products ADD CONSTRAINT products_sku_key UNIQUE (sku);
    END IF;
END $$;
"""

_ANOMALY_UNIQUE = """
DELETE FROM anomaly_log a
 USING anomaly_log b
 WHERE a.id < b.id
   AND a.product_id IS NOT DISTINCT FROM b.product_id
   AND COALESCE(a.alert_date, a.detected_at::date) = COALESCE(b.alert_date, b.detected_at::date)
   AND a.anomaly_type = b.anomaly_type
   AND COALESCE(a.detection_method, 'zscore') = COALESCE(b.detection_method, 'zscore');
CREATE UNIQUE INDEX IF NOT EXISTS uq_anomaly_detection
    ON anomaly_log (product_id, COALESCE(alert_date, detected_at::date),
                    anomaly_type, COALESCE(detection_method, 'zscore'));
"""

_FORECAST_UNIQUE = """
DELETE FROM forecast_cache a
 USING forecast_cache b
 WHERE a.id < b.id
   AND a.product_id IS NOT DISTINCT FROM b.product_id
   AND a.model = b.model
   AND a.horizon = b.horizon;
CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_cache_key
    ON forecast_cache (product_id, model, horizon);
"""

_SESSION_TRIGGER = """
DROP TRIGGER IF EXISTS trg_session_cleanup ON user_sessions;
CREATE TRIGGER trg_session_cleanup
    AFTER INSERT ON user_sessions
    FOR EACH ROW
    EXECUTE FUNCTION trg_cleanup_stale_sessions();
"""


def upgrade() -> None:
    # D-1: atomic movement recording (row lock + guard + delta update + insert)
    _run(_SP_MOVEMENT_RECORD)
    # D-3/D-4: PO state machine with stock/on_order effects, idempotent
    _run(_SP_PO_TRANSITION)
    # D-5: soft supplier delete + visibility filters
    # Column first — databases bootstrapped before schema.sql gained it lack it.
    _run("ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;")
    # suppliers gained deleted_at, so the OUT row type changes — CREATE OR
    # REPLACE refuses that, drop first (no-arg signature is unambiguous).
    _run("DROP FUNCTION IF EXISTS sp_supplier_list_all();")
    _run(_SP_SUPPLIER_LIST_ALL)
    _run(_SP_SUPPLIER_FIND)
    # D-1: remove the legacy 7-arg overload (raw INSERT, no stock guard) left
    # behind by an old bootstrap — movement_repo only calls the 6-arg version.
    _run(
        "DROP FUNCTION IF EXISTS sp_movement_record("
        "integer, character varying, character varying, integer, "
        "character varying, text, integer);"
    )
    # D-2: single soft-delete sp_product_delete (replaces any legacy body/overloads)
    _run(_SP_PRODUCT_DELETE)
    # D-2: partial list index + catalog-guarded unique SKU constraint
    _run(
        """
        CREATE INDEX IF NOT EXISTS idx_products_list_filter
            ON products (warehouse, category, current_stock, reorder_point, on_order)
            WHERE deleted_at IS NULL;
        """
    )
    _run(_SKU_CONSTRAINT_DO)
    # Convergence (dual-apply checksum): these two were removed from schema.sql
    # in 9b4bf2a ("remove redundant indexes") but existing databases kept them.
    # sku is covered by products_sku_key; unit_price had no consumers.
    _run(
        "DROP INDEX IF EXISTS idx_products_sku; "
        "DROP INDEX IF EXISTS idx_products_unit_price;"
    )
    # D-6/D-7: dedup + unique indexes for anomaly alerts and forecast cache
    _run(_ANOMALY_UNIQUE)
    _run(_FORECAST_UNIQUE)
    # D-8: attach the orphaned stale-session cleanup trigger
    _run(_SESSION_TRIGGER)


def downgrade() -> None:
    # Drop only objects this revision created. Function bodies and the SKU
    # constraint stay: schema.sql re-creates them for fresh installs and
    # dropping a unique constraint could strand rows created meanwhile.
    _run("DROP TRIGGER IF EXISTS trg_session_cleanup ON user_sessions;")
    _run("DROP INDEX IF EXISTS uq_anomaly_detection;")
    _run("DROP INDEX IF EXISTS uq_forecast_cache_key;")
    _run("DROP INDEX IF EXISTS idx_products_list_filter;")
    # restore the legacy indexes this revision dropped (pre-migration state)
    _run("CREATE INDEX IF NOT EXISTS idx_products_sku ON products (sku);")
    _run(
        "CREATE INDEX IF NOT EXISTS idx_products_unit_price "
        "ON products (unit_price);"
    )
