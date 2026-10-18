"""supplier name live-unique index — create-missing import parity fix.

Fresh-install / committed parity: the table-wide ``uq_suppliers_name``
constraint previously existed only by hand on the dev database (no committed
source created it; schema.sql's DO-block was inert at runtime because
bootstrap_database() skips init_schema when the products table exists).

The committed path follows the soft-delete convention, mirroring
``products_sku_live_key``: a supplier name is reusable once the previous row
is soft-deleted (``deleted_at IS NOT NULL``), while duplicates among ACTIVE
rows stay blocked by the partial unique index ``uq_suppliers_name_live``.
This is what makes the opt-in create-missing import deliver what its preview
promises for soft-deleted names.

NOTE: the revision id is 29 chars because Alembic's default
``alembic_version.version_num`` is VARCHAR(32) — the descriptive
"20261017_supplier_name_live_unique" (34) cannot be stamped.

Revision ID: 20261017_supplier_live_unique
Revises: 20261012_soft_delete_phase2
Create Date: 2026-10-17
"""
from alembic import op

revision = "20261017_supplier_live_unique"
down_revision = "20261012_soft_delete_phase2"
branch_labels = None
depends_on = None


def _run(sql: str) -> None:
    """Execute raw SQL on the underlying driver connection.

    SQLAlchemy's exec_driver_sql still passes a (possibly empty) parameters
    container to psycopg2, which then tries to %-substitute format strings
    (DO $$ ... % ... $$). The raw DBAPI cursor with vars=None sends the
    statement untouched.
    """
    conn = op.get_bind().connection
    raw = getattr(conn, "driver_connection", None) or conn.dbapi_connection
    with raw.cursor() as cur:
        cur.execute(sql)


# Downgrade guard: table-wide UNIQUE(name) cannot be re-added while ANY
# duplicate name exists — including an active row shadowing a soft-deleted
# one, which the partial index explicitly permits. Check across all rows
# (not just active) so the downgrade can never abort mid-way.
_READD_CONSTRAINT_DO = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_suppliers_name' AND conrelid = 'suppliers'::regclass
    ) AND NOT EXISTS (
        SELECT 1 FROM suppliers GROUP BY name HAVING COUNT(*) > 1
    ) THEN
        ALTER TABLE suppliers ADD CONSTRAINT uq_suppliers_name UNIQUE (name);
    END IF;
END $$;
"""


def upgrade() -> None:
    _run("ALTER TABLE suppliers DROP CONSTRAINT IF EXISTS uq_suppliers_name;")
    _run(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_suppliers_name_live "
        "ON suppliers (name) WHERE deleted_at IS NULL;"
    )


def downgrade() -> None:
    _run("DROP INDEX IF EXISTS uq_suppliers_name_live;")
    _run(_READD_CONSTRAINT_DO)
