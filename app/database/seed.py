"""Seed the database with a realistic, feature-complete dataset.

Runs during app bootstrap and via the ``flask seed-db`` CLI command.

Idempotent: users, products, movements and purchase orders are only inserted
when their tables are empty (unless ``force=True``), so repeated startups never
duplicate rows. The product catalogue uses real product names from the DataCo
SMART SUPPLY CHAIN dataset, spread across ten warehouses and a curated set of
real-world suppliers. A movement ledger is generated from January 2024 to the
current date so every module (dashboard KPIs, reports, Analytics/AI forecasting
and anomaly detection, purchase orders) has data to work with.
"""
from __future__ import annotations

import logging
import random
from datetime import date, datetime, time, timedelta

import psycopg2.extras
from psycopg2.extras import execute_values
from werkzeug.security import generate_password_hash

from flask import current_app

from ..services.dataset_service import get_products

LOGGER = logging.getLogger(__name__)

# Demo accounts used by the UI tour, smoke tests and the test suite.
USERS_SEED = [
    ("admin", "admin@inventorylogix.local", "Admin@123", "admin"),
    ("manager", "manager@inventorylogix.local", "Manager@123", "manager"),
    ("viewer", "viewer@inventorylogix.local", "Viewer@123", "viewer"),
]

# Ten real warehouses the product catalogue is spread across.
WAREHOUSES = [
    "WH-Pune", "WH-Mumbai", "WH-Delhi", "WH-Bengaluru", "WH-Chennai",
    "WH-Hyderabad", "WH-Ahmedabad", "WH-Kolkata", "WH-Jaipur", "WH-Noida",
]

# Curated real-world suppliers (logistics providers + manufacturers) that ship
# the demo catalogue. Fields: (name, location, lead_days, reliability).
SUPPLIER_SEED = [
    ("Tata Steel", "Jamshedpur, India", 21, 92.0),
    ("Reliance Industries", "Mumbai, India", 14, 95.0),
    ("Aditya Birla Group", "Mumbai, India", 18, 90.0),
    ("ITC Limited", "Kolkata, India", 12, 91.0),
    ("Godrej & Boyce", "Mumbai, India", 15, 93.0),
    ("Asian Paints", "Mumbai, India", 10, 94.0),
    ("UltraTech Cement", "Mumbai, India", 16, 89.0),
    ("Mahindra Logistics", "Pune, India", 9, 88.0),
    ("Blue Dart Express", "Mumbai, India", 6, 96.0),
    ("Delhivery", "Gurugram, India", 7, 92.0),
    ("Ecom Express", "Gurugram, India", 8, 87.0),
    ("Safexpress", "New Delhi, India", 11, 90.0),
    ("Rivigo", "Gurugram, India", 9, 85.0),
    ("DHL Supply Chain", "Bengaluru, India", 10, 95.0),
    ("FedEx Express", "Mumbai, India", 8, 94.0),
    ("UPS Supply Chain", "Chennai, India", 12, 91.0),
    ("Maersk Line", "Mumbai, India", 28, 93.0),
    ("DP World", "Mumbai, India", 26, 90.0),
    ("Container Corporation of India", "New Delhi, India", 24, 88.0),
    ("Allcargo Logistics", "Mumbai, India", 18, 86.0),
    ("VRL Logistics", "Hubli, India", 13, 89.0),
    ("Gati Limited", "Hyderabad, India", 12, 84.0),
    ("TCI Express", "New Delhi, India", 10, 90.0),
    ("DTDC Express", "Bengaluru, India", 9, 88.0),
    ("Shadowfax Technologies", "Bengaluru, India", 7, 86.0),
    ("XpressBees Logistics", "Pune, India", 6, 89.0),
    ("Ekart Logistics", "Bengaluru, India", 7, 87.0),
    ("Procter & Gamble", "Cincinnati, USA", 20, 95.0),
    ("Unilever", "London, UK", 22, 94.0),
    ("Samsung Electronics", "Seoul, South Korea", 25, 96.0),
    ("LG Electronics", "Seoul, South Korea", 25, 95.0),
    ("Whirlpool", "Benton Harbor, USA", 21, 91.0),
    ("Sony India", "New Delhi, India", 19, 93.0),
    ("Panasonic India", "Gurugram, India", 17, 92.0),
    ("Nike", "Beaverton, USA", 23, 94.0),
    ("Adidas", "Herzogenaurach, Germany", 22, 93.0),
]

# Movement ledger window: Jan 2024 -> today.
MOVEMENT_START = date(2024, 1, 1)
RECENT_WINDOW_DAYS = 180
_RNG = random.Random(2024)


def _drain_bucket(idx: int) -> bool:
    """Deterministic subset of products left below their reorder point.

    The same rule is used by the movement and PO generators so those products
    never carry an open PO (``on_order`` stays 0) and genuinely appear in the
    reorder queue.
    """
    return idx % 6 == 0


def _open_conn():
    params = current_app.config["psycopg2_params"]()
    if "dsn" in params:
        return psycopg2.connect(
            params["dsn"], cursor_factory=psycopg2.extras.RealDictCursor
        )
    return psycopg2.connect(
        cursor_factory=psycopg2.extras.RealDictCursor, **params
    )


def _seed_users(cur) -> int:
    """Insert the demo users when the users table is empty. Returns count."""
    cur.execute("SELECT COUNT(*) AS c FROM users")
    if (cur.fetchone() or {}).get("c", 0) == 0:
        for username, email, password, role in USERS_SEED:
            cur.execute(
                """
                INSERT INTO users (username, email, password_hash, role)
                VALUES (%s, %s, %s, %s)
                """,
                (username, email, generate_password_hash(password), role),
            )
        LOGGER.info("Seeded %s demo users.", len(USERS_SEED))
        return len(USERS_SEED)
    LOGGER.info("Seed skipped: users table already populated.")
    return 0


def _seed_suppliers(cur) -> list[int]:
    """Insert the curated real-world suppliers. Returns their ids."""
    rows = []
    for name, location, lead_days, reliability in SUPPLIER_SEED:
        initials = "".join(part[0].upper() for part in name.split()[:2])
        tone = "green" if reliability >= 90 else "amber"
        rows.append((name, initials, location, lead_days, reliability, tone))
    returned = execute_values(
        cur,
        """
        INSERT INTO suppliers (name, initials, location, lead_days,
                               reliability, tone)
        VALUES %s RETURNING id
        """,
        rows,
        fetch=True,
    )
    LOGGER.info("Seeded %s suppliers.", len(returned))
    return [row["id"] if isinstance(row, dict) else row[0] for row in returned]


def _product_params(product: dict, supplier_ids: list[int], index: int) -> tuple | None:
    name = (product.get("product_name") or "").strip()
    card_id = str(product.get("product_card_id") or "").strip()
    if not name:
        return None
    sku = f"SKU-DC-{card_id}" if card_id else f"SKU-DC-{abs(hash(name)) % 100000}"
    category = product.get("category_name") or (
        str(product.get("product_category_id") or "")
        if product.get("product_category_id")
        else None
    )
    price = float(product.get("product_price", 0) or 0)
    seed = int(card_id) if card_id else hash(name) % 100000
    # Realistic annual demand drives EOQ, reorder points and the movement
    # ledger below (all stay consistent with one another).
    demand_rate = round(200 + (abs(seed) % 1800), 2)
    daily = demand_rate / 365.0
    reorder_point = max(5, int(daily * 14))
    ordering_cost = round(30 + (abs(seed) % 90), 2)
    holding_cost = round(max(2.0, price * 0.20), 2)
    warehouse = WAREHOUSES[index % len(WAREHOUSES)]
    supplier_id = supplier_ids[index % len(supplier_ids)] if supplier_ids else None
    return (
        sku, name, category, warehouse, 0, reorder_point,
        demand_rate, ordering_cost, holding_cost, price, supplier_id,
    )


def _seed_products(cur, supplier_ids: list[int]) -> int:
    """Insert the real-world DataCo product catalogue across warehouses."""
    products = get_products()
    product_rows = []
    for i, product in enumerate(products):
        params = _product_params(product, supplier_ids, i)
        if params:
            product_rows.append(params)
    if product_rows:
        execute_values(
            cur,
            """
            INSERT INTO products (sku, name, category, warehouse,
                                  current_stock, reorder_point,
                                  demand_rate, ordering_cost,
                                  holding_cost, unit_price, supplier_id)
            VALUES %s
            """,
            product_rows,
        )
    LOGGER.info("Seeded %s products across %s warehouses.",
                len(product_rows), len(WAREHOUSES))
    return len(product_rows)


def _movement_row(product: dict, mtype: str, qty: int, day: date, rng: random.Random) -> tuple:
    ts = datetime.combine(day, time.min) + timedelta(
        hours=rng.randint(7, 20), minutes=rng.randint(0, 59)
    )
    refs = {"IN": "RESTOCK", "OUT": "SALE", "ADJUSTMENT": "ADJ", "RETURN": "RTN"}
    return (
        product["id"], product["sku"], mtype, qty,
        f"{refs[mtype]}-{day:%Y%m%d}", None, None, ts,
    )


def _movement_dates(rng: random.Random, today: date, recent_cutoff: date) -> list[date]:
    """Evenly distributed movement days from Jan 2024 -> today.

    Every calendar year gets its own share of days so the year-over-year sales
    charts stay competitive (2024/2025 are no longer dwarfed by the current
    year), plus an extra dense burst in the last ``RECENT_WINDOW_DAYS`` so the
    Prophet/ARIMA forecasters have enough daily points. Each COMPLETE year also gets a
    seasonal burst to make YTD/QTD/MTD charts show tight competition.
    """
    dates: list[date] = []
    current_year = today.year
    for year in range(MOVEMENT_START.year, current_year + 1):
        year_start = max(MOVEMENT_START, date(year, 1, 1))
        year_end = min(today, date(year, 12, 31))
        span = (year_end - year_start).days
        if span <= 0:
            continue
        n = rng.randint(15, 20)  # increased base per year
        for _ in range(n):
            dates.append(year_start + timedelta(days=rng.randint(0, span)))
        # Seasonal burst: add extra movement days in peak months (Q2 + Q4) for COMPLETE years only
        is_complete_year = year < current_year or (year == current_year and year_end.month == 12 and year_end.day == 31)
        if is_complete_year:
            peak_months = [4, 5, 6, 10, 11, 12]
            for month in peak_months:
                m_start = max(year_start, date(year, month, 1))
                if month == 12:
                    m_end = min(year_end, date(year, 12, 31))
                else:
                    m_end = min(year_end, date(year, month + 1, 1) - timedelta(days=1))
                if (m_end - m_start).days >= 0:
                    dates.append(m_start + timedelta(days=rng.randint(0, (m_end - m_start).days)))
    recent_span = (today - recent_cutoff).days
    if recent_span > 0:
        for _ in range(rng.randint(4, 6)):  # reduced recent burst for forecasting only
            dates.append(recent_cutoff + timedelta(days=rng.randint(0, recent_span)))
    dates.sort()
    return dates


def _generate_movements(cur) -> int:
    """Build a movement ledger from Jan 2024 -> today.

    Each product receives a deterministic stream of IN (restock), OUT (sales)
    and occasional ADJUSTMENT/RETURN movements. Stock is managed against a
    restock-to level (``rop + reorder_qty``) so the cumulative units moved in
    and out stay close to each other — the charts show a real battle between
    inbound supply and outbound demand rather than a one-sided restock flood.
    ``products.current_stock`` is set to the final ledger balance so the ETL's
    backward stock walk stays consistent. A deterministic subset of products
    (``_drain_bucket``) ends the period below their reorder point (a demand
    surge without a matching restock), which is what populates the reorder
    queue.
    """
    cur.execute("SELECT id, sku, demand_rate, reorder_point FROM products ORDER BY id")
    products = [dict(r) for r in cur.fetchall()]
    today = date.today()
    recent_cutoff = today - timedelta(days=RECENT_WINDOW_DAYS)
    rows: list[tuple] = []
    for idx, product in enumerate(products):
        demand = float(product["demand_rate"] or 0)
        daily = max(0.5, demand / 365.0) if demand else 3.0
        rop = max(int(product["reorder_point"] or 0), 1)
        reorder_qty = max(int(daily * 14), 10)
        target = rop + reorder_qty
        stock = target

        dates = _movement_dates(_RNG, today, recent_cutoff)
        for day in dates:
            if stock <= rop:
                qty = max(target - stock, 1)
                rows.append(_movement_row(product, "IN", qty, day, _RNG))
                stock += qty
                continue
            roll = _RNG.random()
            if roll < 0.72:
                qty = max(1, round(daily * _RNG.uniform(1.5, 6.0)))
                qty = min(qty, stock)
                rows.append(_movement_row(product, "OUT", qty, day, _RNG))
                stock -= qty
            elif roll < 0.82:
                qty = max(1, round(reorder_qty * _RNG.uniform(0.4, 0.8)))
                rows.append(_movement_row(product, "IN", qty, day, _RNG))
                stock += qty
            elif roll < 0.92:
                rows.append(_movement_row(product, "ADJUSTMENT", _RNG.randint(1, 5), day, _RNG))
            else:
                rows.append(_movement_row(product, "RETURN", _RNG.randint(1, 4), day, _RNG))

        if _drain_bucket(idx):
            # Demand surge: recent sales outrun supply, ending the period
            # below the reorder point so the product lands in the reorder queue.
            target_low = _RNG.randint(0, max(rop - 1, 0))
            if stock > target_low:
                day = today - timedelta(days=_RNG.randint(0, 2))
                rows.append(_movement_row(product, "OUT", stock - target_low, day, _RNG))
                stock = target_low
        cur.execute("UPDATE products SET current_stock=%s WHERE id=%s", (stock, product["id"]))

    if rows:
        execute_values(
            cur,
            """
            INSERT INTO movements (product_id, sku, type, quantity,
                                   reference, notes, user_id, created_at)
            VALUES %s
            """,
            rows,
        )
    LOGGER.info("Seeded %s movements (Jan %s -> today).", len(rows), MOVEMENT_START.year)
    return len(rows)


def _generate_purchase_orders(cur) -> int:
    """Insert ~25 purchase orders with realistic statuses and dates."""
    cur.execute("SELECT id FROM suppliers ORDER BY id")
    supplier_ids = [r["id"] for r in cur.fetchall()]
    cur.execute("SELECT id, unit_price FROM products ORDER BY id")
    products = [dict(r) for r in cur.fetchall()]
    if not supplier_ids or not products:
        return 0

    rng = random.Random(7)
    today = date.today()
    span = (today - MOVEMENT_START).days
    rows: list[tuple] = []
    po_rows: list[tuple] = []
    seen: set[str] = set()
    for i in range(25):
        product = rng.choice(products)
        product_idx = products.index(product)
        supplier_id = rng.choice(supplier_ids)
        created = MOVEMENT_START + timedelta(days=rng.randint(0, span))
        age_days = (today - created).days
        if age_days > 120:
            status = "received"
        elif age_days > 60:
            status = rng.choice(["received", "in_transit", "approved"])
        else:
            status = rng.choice(["draft", "approved", "in_transit", "cancelled"])
        if _drain_bucket(product_idx) and status in ("approved", "in_transit"):
            status = "draft"
        po_number = f"PO-{created:%Y%m%d}-{i + 1:04d}"
        if po_number in seen:
            continue
        seen.add(po_number)
        qty = rng.randint(20, 300)
        unit_cost = round(float(product["unit_price"] or 0) * rng.uniform(0.75, 0.95), 2)
        eta = created + timedelta(days=rng.randint(10, 45))
        ts = datetime.combine(created, time.min) + timedelta(hours=rng.randint(8, 18))
        po_rows.append((po_number, supplier_id, product["id"], qty, unit_cost, status, eta, ts))
        if status in ("approved", "in_transit"):
            rows.append((product["id"], qty))

    if po_rows:
        execute_values(
            cur,
            """
            INSERT INTO purchase_orders (po_number, supplier_id, product_id,
                                         quantity, unit_cost, status,
                                         eta_date, created_at)
            VALUES %s
            """,
            po_rows,
        )
    # Open POs (approved/in_transit) add to each product's on-order count.
    for product_id, qty in rows:
        cur.execute(
            "UPDATE products SET on_order = on_order + %s WHERE id = %s",
            (qty, product_id),
        )
    # Supplier spend reflects the value of their purchase orders.
    cur.execute(
        """
        UPDATE suppliers s
        SET spend_amount = COALESCE((
            SELECT SUM(po.quantity * po.unit_cost)
            FROM purchase_orders po WHERE po.supplier_id = s.id
        ), 0)
        """
    )
    LOGGER.info("Seeded %s purchase orders.", len(po_rows))
    return len(po_rows)


def run_seed(force: bool = False) -> None:
    """Load demo users, suppliers, products, movements and purchase orders."""
    conn = _open_conn()
    try:
        with conn.cursor() as cur:
            _seed_users(cur)

            cur.execute("SELECT COUNT(*) AS c FROM products")
            products_exist = (cur.fetchone() or {}).get("c", 0) > 0
            if force or not products_exist:
                supplier_ids = _seed_suppliers(cur)
                _seed_products(cur, supplier_ids)
            else:
                LOGGER.info("Seed skipped: products table already populated.")
                cur.execute("SELECT id FROM suppliers ORDER BY id")
                supplier_ids = [r["id"] for r in cur.fetchall()]

            cur.execute("SELECT COUNT(*) AS c FROM movements")
            if (cur.fetchone() or {}).get("c", 0) == 0:
                _generate_movements(cur)
            else:
                LOGGER.info("Seed skipped: movements table already populated.")

            cur.execute("SELECT COUNT(*) AS c FROM purchase_orders")
            if (cur.fetchone() or {}).get("c", 0) == 0:
                _generate_purchase_orders(cur)
            else:
                LOGGER.info("Seed skipped: purchase_orders table already populated.")

        conn.commit()
        LOGGER.info("Seed complete.")
    except Exception as exc:
        conn.rollback()
        LOGGER.warning("Dataset seeding deferred: %s", exc)
    finally:
        conn.close()