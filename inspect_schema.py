import logging
logging.disable(logging.WARNING)
from app import create_app
app = create_app()
with app.app_context():
    from app.database.connection import _open_conn
    conn = _open_conn()
    with conn.cursor() as cur:
        for table in ['movements', 'products', 'suppliers', 'warehouses']:
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = %s ORDER BY ordinal_position", (table,)
            )
            print(table.upper(), 'columns:')
            for r in cur.fetchall():
                print(' ', r['column_name'], r['data_type'])
        print()
        for t in ['movements', 'products', 'suppliers', 'purchase_orders']:
            cur.execute(f'SELECT COUNT(*) as c FROM {t}')
            print(t, 'rows:', cur.fetchone()['c'])