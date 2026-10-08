#!/usr/bin/env python
"""Targeted data updates for InventoryLogix (preserves existing movements/users):

1. Insert the 10 real warehouses products reference (additive)
2. Update products with REAL DataCo names/categories/prices (keep IDs/SKUs ->
   movements + demand history preserved)
3. Push ~15 products into the reorder queue (below reorder point)
4. Insert purchase-order history 2024 -> now (~300 POs, realistic statuses)
5. Sync products.on_order from open POs
"""
from __future__ import annotations

import csv
import logging
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger("data_update")

REPO_ROOT = Path(__file__).resolve().parents[1]
DATACO_CSV = REPO_ROOT / "DataCo_Supply_Chain_Dataset" / "DataCoSupplyChainDataset.csv"
RNG_SEED = 7

WAREHOUSES = [
    ("WH-Pune", "Pune, Maharashtra"),
    ("WH-Mumbai", "Mumbai, Maharashtra"),
    ("WH-Delhi", "Delhi, Delhi"),
    ("WH-Bengaluru", "Bengaluru, Karnataka"),
    ("WH-Chennai", "Chennai, Tamil Nadu"),
    ("WH-Hyderabad", "Hyderabad, Telangana"),
    ("WH-Ahmedabad", "Ahmedabad, Gujarat"),
    ("WH-Kolkata", "Kolkata, West Bengal"),
    ("WH-Jaipur", "Jaipur, Rajasthan"),
    ("WH-Noida", "Noida, Uttar Pradesh"),
]


def extract_real_products(limit: int = 118) -> list[dict]:
    """Extract unique real products (name, category, price) from DataCo CSV."""
    products: dict[str, dict] = {}
    with open(DATACO_CSV, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            name = (row.get("Product Name") or "").strip()
            cat = (row.get("Category Name") or "").strip()
            try:
                price = round(float(row.get("Product Price") or 0), 2)
            except ValueError:
                price = 0.0
            if name and name not in products and price > 0:
                products[name] = {"name": name[:150], "category": cat[:80], "price": price}
            if len(products) >= limit or i >= 300000:
                break
    return list(products.values())


def run():
    sys.path.insert(0, str(REPO_ROOT))
    from app import create_app
    from app.database.connection import _open_conn

    rng = random.Random(RNG_SEED)
    real_products = extract_real_products()
    LOGGER.info("Extracted %s real products from DataCo", len(real_products))

    app = create_app()
    with app.app_context():
        conn = _open_conn()
        try:
            with conn.cursor() as cur:
                # ── 1. Warehouses: insert the 10 real warehouses (additive) ──
                for name, loc in WAREHOUSES:
                    cur.execute(
                        "SELECT id FROM warehouses WHERE warehouse_name = %s", (name,)
                    )
                    if cur.fetchone() is None:
                        cur.execute(
                            "INSERT INTO warehouses (warehouse_name, location) VALUES (%s, %s)",
                            (name, loc),
                        )
                LOGGER.info("Warehouses ensured (%s total)", len(WAREHOUSES))

                # ── 2. Products: real DataCo names/categories/prices ──
                cur.execute(
                    "SELECT id, sku, reorder_point, current_stock FROM products "
                    "WHERE deleted_at IS NULL ORDER BY id"
                )
                db_products = list(cur.fetchall())
                if len(real_products) < len(db_products):
                    raise RuntimeError(
                        f"Only {len(real_products)} real products for {len(db_products)} SKUs"
                    )
                for i, p in enumerate(db_products):
                    real = real_products[i]
                    holding = round(real["price"] * 0.2, 2)
                    cur.execute(
                        """UPDATE products SET name = %s, category = %s,
                           unit_price = %s, holding_cost = %s, updated_at = NOW()
                           WHERE id = %s""",
                        (real["name"], real["category"], real["price"], holding, p["id"]),
                    )
                LOGGER.info("Updated %s products with real DataCo names", len(db_products))

                # ── 3. Reorder queue: push ~15 products below reorder point ──
                # Deterministic subset: every 4th product, mixed severity
                queue_targets = db_products[::4][:15]
                for j, p in enumerate(queue_targets):
                    rop = p["reorder_point"]
                    if j % 3 == 0:
                        new_stock = 0                      # out of stock
                    elif j % 3 == 1:
                        new_stock = max(1, int(rop * 0.25))  # critical
                    else:
                        new_stock = max(1, int(rop * 0.7))   # low stock
                    cur.execute(
                        "UPDATE products SET current_stock = %s WHERE id = %s",
                        (new_stock, p["id"]),
                    )
                LOGGER.info("Pushed %s products into reorder queue", len(queue_targets))

                # ── 4. Purchase-order history 2024 -> now ──
                cur.execute("SELECT COUNT(*) AS c FROM purchase_orders")
                if cur.fetchone()["c"] > 0:
                    LOGGER.info("PO history already present — skipping")
                else:
                    cur.execute("SELECT id FROM suppliers WHERE deleted_at IS NULL ORDER BY id")
                    supplier_ids = [r["id"] for r in cur.fetchall()]
                    cur.execute(
                        "SELECT id, unit_price FROM products WHERE deleted_at IS NULL ORDER BY id"
                    )
                    po_products = list(cur.fetchall())
                    today = date.today()
                    start = date(2024, 1, 1)
                    span = (today - start).days
                    seen: set[str] = set()
                    po_rows = []
                    for _ in range(300):
                        prod = rng.choice(po_products)
                        sup = rng.choice(supplier_ids)
                        created = start + timedelta(days=rng.randint(0, span))
                        age = (today - created).days
                        roll = rng.random()
                        if age < 7:
                            status = rng.choice(["draft", "approved"])
                        elif roll < 0.70:
                            status = "received"
                        elif roll < 0.80:
                            status = "in_transit"
                        elif roll < 0.90:
                            status = "approved"
                        elif roll < 0.95:
                            status = "draft"
                        else:
                            status = "cancelled"
                        qty = rng.randint(10, 200)
                        unit_cost = round(float(prod["unit_price"]) * rng.uniform(0.55, 0.85), 2)
                        eta = created + timedelta(days=rng.randint(3, 18))
                        po_number = f"PO-{created:%Y%m%d}-{len(seen):04d}"
                        if po_number in seen:
                            continue
                        seen.add(po_number)
                        updated = created if status in ("draft",) else (
                            eta if status in ("approved", "in_transit", "cancelled") else eta
                        )
                        po_rows.append((po_number, sup, prod["id"], qty, unit_cost,
                                        status, eta, created, updated))
                    from psycopg2.extras import execute_values
                    execute_values(
                        cur,
                        """INSERT INTO purchase_orders
                           (po_number, supplier_id, product_id, quantity, unit_cost,
                            status, eta_date, created_at, updated_at) VALUES %s""",
                        po_rows,
                    )
                    LOGGER.info("Inserted %s purchase orders (2024 -> now)", len(po_rows))

                # ── 5. Sync products.on_order from open POs ──
                cur.execute(
                    """UPDATE products p SET on_order = COALESCE(o.qty, 0)
                       FROM (SELECT product_id, SUM(quantity) AS qty
                             FROM purchase_orders
                             WHERE status IN ('approved', 'in_transit')
                             GROUP BY product_id) o
                       WHERE p.id = o.product_id"""
                )
                cur.execute(
                    """UPDATE products SET on_order = 0
                       WHERE id NOT IN (SELECT DISTINCT product_id FROM purchase_orders
                                        WHERE status IN ('approved', 'in_transit'))"""
                )
                LOGGER.info("Synced products.on_order from open POs")

            conn.commit()
            LOGGER.info("All updates committed")
        except Exception:
            conn.rollback()
            LOGGER.exception("Update FAILED — rolled back")
            raise
        finally:
            conn.close()


if __name__ == "__main__":
    run()