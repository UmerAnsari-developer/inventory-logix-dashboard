"""Seed the database with realistic sample data for demo / development.

Idempotent: only inserts rows when the table is empty (unless ``force=True``).
"""
from __future__ import annotations

import logging
import random
from datetime import date, datetime, timedelta
from decimal import Decimal

import psycopg2
import psycopg2.extras

from flask import current_app
from werkzeug.security import generate_password_hash

LOGGER = logging.getLogger(__name__)


SUPPLIER_SEED = [
    ("MetroFast Components", "MF", "Mumbai · Hardware & electrical", 5, 184000.00, 94.0, "amber"),
    ("PackRight India", "PR", "Pune · Packaging materials", 7, 92400.00, 91.0, "green"),
    ("SafeHands Industrial", "SH", "Nashik · PPE & safety", 5, 68700.00, 88.0, "blue"),
    ("Cleanline Traders", "CT", "Pune · Facilities supplies", 8, 41200.00, 86.0, "ink"),
    ("Apex Industrial Supply", "AI", "Bengaluru · Machine parts", 10, 36800.00, 82.0, "amber"),
    ("Boxcraft Logistics", "BL", "Mumbai · Dispatch supplies", 4, 19500.00, 90.0, "green"),
    ("BearingCorp International", "BC", "Pune · Industrial bearings", 14, 248000.00, 92.0, "blue"),
    ("HydroMax Systems", "HM", "Chennai · Hydraulic machinery", 21, 312000.00, 87.0, "amber"),
]

WAREHOUSES = [
    "WH-Pune",
    "WH-Mumbai",
    "WH-Delhi",
    "WH-Bengaluru",
    "WH-Chennai",
]

PRODUCT_SEED = [
    # (sku, name, category, warehouse, stock, rop, demand, ordering, holding, price, supplier_init)
    ("SKU-TECH-001", "Wireless Mechanical Keyboard", "Electronics", "WH-Pune", 42, 20, 2400, 65.00, 4.50, 89.99, "MetroFast Components"),
    ("SKU-TECH-002", "USB-C Docking Station", "Electronics", "WH-Pune", 6, 15, 1200, 50.00, 6.00, 149.00, "MetroFast Components"),
    ("SKU-TECH-003", "4K Webcam with Mic", "Electronics", "WH-Mumbai", 0, 10, 900, 40.00, 5.00, 99.50, "MetroFast Components"),
    ("SKU-OFF-001", "Ergonomic Office Chair", "Furniture", "WH-Pune", 18, 8, 360, 120.00, 15.00, 329.00, "PackRight India"),
    ("SKU-OFF-002", "Standing Desk L-Shaped", "Furniture", "WH-Delhi", 4, 6, 180, 150.00, 20.00, 649.00, "PackRight India"),
    ("SKU-OFF-003", "Monitor Arm Mount", "Furniture", "WH-Pune", 12, 5, 210, 30.00, 8.50, 79.99, "PackRight India"),
    ("SKU-ACC-001", "Anti-Static Wrist Strap", "Accessories", "WH-Pune", 60, 25, 1500, 12.00, 1.50, 12.99, "SafeHands Industrial"),
    ("SKU-ACC-002", "Cable Management Kit", "Accessories", "WH-Mumbai", 25, 20, 800, 18.00, 2.00, 24.99, "SafeHands Industrial"),
    ("SKU-ACC-003", "Industrial Bearing 40mm", "Components", "WH-Pune", 12, 50, 6000, 45.00, 8.63, 34.50, "BearingCorp International"),
    ("SKU-ACC-004", "Steel Bolt M10x50 (100pc)", "Fasteners", "WH-Bengaluru", 85, 100, 8000, 25.00, 3.00, 12.00, "Apex Industrial Supply"),
    ("SKU-ACC-005", "Hydraulic Pump 25HP", "Machinery", "WH-Chennai", 3, 5, 120, 250.00, 156.25, 1250.00, "HydroMax Systems"),
    ("SKU-ACC-006", "Safety Valve 2-inch", "Safety", "WH-Delhi", 142, 40, 480, 60.00, 13.35, 89.00, "SafeHands Industrial"),
    ("SKU-ACC-007", "Copper Cable 4mm (100m)", "Electrical", "WH-Bengaluru", 320, 100, 360, 80.00, 49.00, 245.00, "MetroFast Components"),
    ("SKU-ACC-008", "Gasket Set Universal", "Components", "WH-Mumbai", 18, 20, 900, 35.00, 5.63, 45.00, "Apex Industrial Supply"),
    ("SKU-ACC-009", "Air Filter HEPA Class", "Filtration", "WH-Delhi", 560, 150, 720, 45.00, 10.13, 67.50, "Cleanline Traders"),
    ("SKU-ACC-010", "Electric Motor 5HP 3-Phase", "Machinery", "WH-Chennai", 7, 8, 180, 180.00, 80.10, 890.00, "HydroMax Systems"),
]

USERS_SEED = [
    ("admin", "admin@inventorylogix.local", "Admin@123", "admin"),
    ("manager", "manager@inventorylogix.local", "Manager@123", "manager"),
    ("viewer", "viewer@inventorylogix.local", "Viewer@123", "viewer"),
]


def _open_conn():
    params = current_app.config["psycopg2_params"]()
    if "dsn" in params:
        return psycopg2.connect(
            params["dsn"], cursor_factory=psycopg2.extras.RealDictCursor
        )
    return psycopg2.connect(
        cursor_factory=psycopg2.extras.RealDictCursor, **params
    )


def _random_movements(sku_lookup):
    """Generate movement history per product from Jan 2024 through today."""
    rows = []
    start = date(2024, 1, 1)
    today = date.today()
    for sku, info in sku_lookup.items():
        daily = max(1, int(float(info["demand"]) / 365))
        d = start
        while d <= today:
            jitter = random.randint(-max(1, daily // 2), daily + 2)
            qty = max(1, daily + jitter)
            if random.random() < 0.18:
                qty = int(qty * random.uniform(2.0, 3.5))  # anomaly spikes
            if qty <= 0:
                d += timedelta(days=1)
                continue
            mtype = random.choices(["IN", "OUT"], weights=[0.45, 0.55])[0]
            rows.append((info["id"], sku, mtype, qty, d))
            d += timedelta(days=1)
    return rows


def _random_purchase_orders(sku_lookup, supplier_lookup):
    """Generate purchase order history per product from Jan 2024 through today."""
    rows = []
    start = date(2024, 1, 1)
    today = date.today()
    counter = 0
    for sku, info in sku_lookup.items():
        supplier_id = supplier_lookup.get(info.get("supplier"))
        # Place a PO roughly every 75 days per SKU.
        d = start
        while d <= today:
            qty = max(10, int(float(info["demand"]) / 365) * 55)
            qty = int(qty * random.uniform(0.8, 1.4))
            eta = d + timedelta(days=random.randint(15, 45))
            if eta < today:
                status = random.choices(
                    ["received", "received", "received", "cancelled"],
                    weights=[0.7, 0.2, 0.05, 0.05],
                )[0]
            else:
                status = random.choices(["approved", "in_transit", "draft"], weights=[0.5, 0.3, 0.2])[0]
            counter += 1
            rows.append((
                f"PO-{d.strftime('%Y%m%d')}-{counter:04d}",
                supplier_id,
                info["id"],
                qty,
                info.get("unit_cost"),
                status,
                eta,
                d,
            ))
            d += timedelta(days=random.randint(60, 90))
    return rows


def run_seed(force: bool = False) -> dict:
    """Insert seed data. Returns counts of inserted rows."""
    conn = _open_conn()
    inserted = {"users": 0, "suppliers": 0, "products": 0, "movements": 0, "pos": 0}
    try:
        with conn.cursor() as cur:
            # Users
            cur.execute("SELECT COUNT(*) AS c FROM users")
            user_count = cur.fetchone()
            user_count = (user_count or {}).get("c", 0)
            if force or user_count == 0:
                for username, email, password, role in USERS_SEED:
                    cur.execute(
                        """
                        INSERT INTO users (username, email, password_hash, role)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (username) DO NOTHING
                        """,
                        (username, email, generate_password_hash(password), role),
                    )
                    inserted["users"] += 1

            # Suppliers — idempotent by name (no unique constraint on name).
            cur.execute("SELECT COUNT(*) AS c FROM suppliers")
            supplier_count = (cur.fetchone() or {}).get("c", 0)
            if force or supplier_count == 0:
                for row in SUPPLIER_SEED:
                    cur.execute(
                        "SELECT id FROM suppliers WHERE name = %s LIMIT 1",
                        (row[0],),
                    )
                    if cur.fetchone():
                        continue
                    cur.execute(
                        """
                        INSERT INTO suppliers
                            (name, initials, location, lead_days, spend_amount, reliability, tone)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                        """,
                        row,
                    )
                    inserted["suppliers"] += 1

            # Suppliers lookup
            cur.execute("SELECT id, name FROM suppliers")
            supplier_lookup = {row["name"]: row["id"] for row in cur.fetchall()}

            # Products — always ensure the seed catalogue is present (idempotent).
            # Missing or previously-deleted seed SKUs are re-added on every boot.
            cur.execute("SELECT COUNT(*) AS c FROM products")
            product_count = (cur.fetchone() or {}).get("c", 0)
            sku_lookup: dict[str, dict] = {}
            for row in PRODUCT_SEED:
                (
                    sku, name, category, warehouse, stock, rop,
                    demand, ordering, holding, price, supplier_name,
                ) = row
                cur.execute(
                    """
                    INSERT INTO products
                        (sku, name, category, warehouse, current_stock, reorder_point,
                         demand_rate, ordering_cost, holding_cost, unit_price, supplier_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (sku) DO NOTHING
                    RETURNING id
                    """,
                    (
                        sku, name, category, warehouse, stock, rop,
                        demand, ordering, holding, price,
                        supplier_lookup.get(supplier_name),
                    ),
                )
                fetched = cur.fetchone()
                pid = fetched["id"] if fetched and fetched["id"] is not None else None
                if pid:
                    inserted["products"] += 1
                # Sync only the warehouse on existing rows so the multi-warehouse
                # layout (e.g. the 5-warehouse split) always applies.
                cur.execute(
                    "UPDATE products SET warehouse=%s WHERE sku=%s",
                    (warehouse, sku),
                )
                cur.execute("SELECT id FROM products WHERE sku=%s", (sku,))
                found = cur.fetchone()
                if found:
                    sku_lookup[sku] = {
                        "id": int(found["id"]),
                        "name": name,
                        "demand": float(demand),
                        "supplier": supplier_name,
                        "unit_cost": float(price * random.uniform(0.55, 0.75)),
                    }

            # Movements — ensure sufficient history exists for AI features.
            # Regenerate if forced or if we have fewer than 500 total movements
            # (aiming for Jan 2024 through today = 16 products × 950+ days).
            cur.execute("SELECT COUNT(*) AS c FROM movements")
            movement_count = (cur.fetchone() or {}).get("c", 0)
            if force or movement_count < 500:
                # Clear existing to avoid duplicates
                if movement_count > 0:
                    cur.execute("DELETE FROM movements")
                if not sku_lookup:
                    cur.execute("SELECT id, sku, demand_rate FROM products")
                    for r in cur.fetchall():
                        sku_lookup[r["sku"]] = {
                            "id": r["id"],
                            "name": "",
                            "demand": float(r["demand_rate"] or 0),
                            "supplier": None,
                            "unit_cost": None,
                        }
                movements = _random_movements(sku_lookup)
                if movements:
                    cur.executemany(
                        """
                        INSERT INTO movements (product_id, sku, type, quantity, reference, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        [(m[0], m[1], m[2], m[3], "seed", m[4]) for m in movements],
                    )
                    inserted["movements"] = len(movements)

            # Purchase orders — regenerate on force or when empty so the
            # procurement analytics have a full 2024–2026 history.
            cur.execute("SELECT COUNT(*) AS c FROM purchase_orders")
            po_count = (cur.fetchone() or {}).get("c", 0)
            if force or po_count == 0:
                if po_count > 0:
                    cur.execute("DELETE FROM purchase_orders")
                if not sku_lookup or not supplier_lookup:
                    cur.execute("SELECT id, sku, demand_rate, supplier_id FROM products")
                    for r in cur.fetchall():
                        sku_lookup[r["sku"]] = {
                            "id": r["id"],
                            "name": "",
                            "demand": float(r["demand_rate"] or 0),
                            "supplier": None,
                            "unit_cost": None,
                        }
                    cur.execute("SELECT id, name FROM suppliers")
                    for row in cur.fetchall():
                        supplier_lookup.setdefault(row["name"], row["id"])
                pos = _random_purchase_orders(sku_lookup, supplier_lookup)
                if pos:
                    cur.executemany(
                        """
                        INSERT INTO purchase_orders
                            (po_number, supplier_id, product_id, quantity, unit_cost, status, eta_date, created_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        pos,
                    )
                    inserted["pos"] = len(pos)
        conn.commit()
        LOGGER.info("Seed data inserted: %s", inserted)
    finally:
        conn.close()
    return inserted
