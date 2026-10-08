import logging
logging.disable(logging.WARNING)
from app import create_app
app = create_app()
with app.app_context():
    from app.database.connection import _open_conn
    conn = _open_conn()
    with conn.cursor() as cur:
        cur.execute('''
            SELECT p.id, p.sku, p.name, p.supplier_id, s.name as supplier_name
            FROM products p
            JOIN suppliers s ON s.id = p.supplier_id
            WHERE p.sku IN ('SKU-SYN-1012', 'SKU-SYN-1048')
            AND p.deleted_at IS NULL
        ''')
        for r in cur.fetchall():
            print(f'{r["sku"]} | {r["name"][:35]} | product_id={r["id"]} | supplier_id={r["supplier_id"]} | supplier={r["supplier_name"]}')