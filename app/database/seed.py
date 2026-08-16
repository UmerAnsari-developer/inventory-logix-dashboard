"""Seed the database from the DataCo SMART SUPPLY CHAIN dataset.

Called during app bootstrap and by the ``flask seed-db`` CLI command.

Idempotent: when the ``products`` table is already populated the seed is
skipped (unless ``force=True``), so repeated startups never duplicate rows.
A fresh database gets a bounded set of suppliers plus the full product
catalogue so every page (reorder queue, EOQ calculator, ETL) has data.
"""

from __future__ import annotations

import logging

import psycopg2.extras
from werkzeug.security import generate_password_hash

from flask import current_app

from ..services.dataset_service import get_products, get_suppliers

LOGGER = logging.getLogger(__name__)

SUPPLIER_LIMIT = 150

# Demo accounts used by the UI tour, smoke tests and the test suite.
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


def _supplier_params(supplier: dict) -> tuple | None:
    first = (supplier.get("supplier_first_name") or "").strip()
    last = (supplier.get("supplier_last_name") or "").strip()
    name = f"{first} {last}".strip()
    if not name:
        return None
    initials = "".join(part[0].upper() for part in name.split()[:2])
    city = supplier.get("customer_city") or ""
    country = supplier.get("customer_country") or ""
    location = ", ".join(p for p in (city, country) if p) or None
    reliability = 88.0 if country else 90.0
    tone = "green" if reliability >= 90 else "amber"
    return name, initials or None, location, 5, reliability, tone


def _product_params(product: dict, supplier_ids: list[int]) -> tuple | None:
    name = (product.get("product_name") or "").strip()
    card_id = str(product.get("product_card_id") or "").strip()
    if not name:
        return None
    sku = f"SKU-DC-{card_id}" if card_id else f"SKU-DC-{abs(hash(name)) % 100000}"
    category = product.get("category_name") or (
        str(product.get("product_category_id") or "") if product.get("product_category_id") else None
    )
    price = float(product.get("product_price", 0) or 0)
    # Deterministic, varied stock levels so a fresh DB has a realistic mix of
    # healthy and below-reorder-point items.
    seed = int(card_id) if card_id else hash(name) % 100000
    reorder_point = 20 + (abs(seed) % 80)
    current_stock = (abs(seed) * 37) % 150
    demand_rate = float(product.get("eoq_demand", 0) or 0)
    ordering_cost = float(product.get("eoq_order_cost", 0) or 0)
    holding_cost = float(product.get("eoq_holding_cost", 0) or 0)
    supplier_id = supplier_ids[abs(seed) % len(supplier_ids)] if supplier_ids else None
    return (
        sku, name, category, "WH-Pune", current_stock, reorder_point,
        demand_rate, ordering_cost, holding_cost, price, supplier_id,
    )


def run_seed(force: bool = False) -> None:
    """Load demo users plus a bounded supplier/product catalogue into the DB."""
    conn = _open_conn()
    try:
        with conn.cursor() as cur:
            if not force:
                cur.execute("SELECT COUNT(*) AS c FROM products")
                if (cur.fetchone() or {}).get("c", 0):
                    LOGGER.info("Seed skipped: products table already populated.")
                    return

            # Demo users — only inserted when the users table is empty so
            # self-registered accounts are never overwritten.
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
            else:
                LOGGER.info("Seed skipped: users table already populated.")

            suppliers = get_suppliers()
            products = get_products()
            LOGGER.info("Loaded %s suppliers and %s products from dataset.",
                        len(suppliers), len(products))

            supplier_ids: list[int] = []
            for supplier in suppliers[:SUPPLIER_LIMIT]:
                params = _supplier_params(supplier)
                if not params:
                    continue
                cur.execute(
                    """
                    INSERT INTO suppliers (name, initials, location, lead_days,
                                           reliability, tone)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                    """,
                    params,
                )
                supplier_ids.append(cur.fetchone()["id"])

            added_products = 0
            for product in products:
                params = _product_params(product, supplier_ids)
                if not params:
                    continue
                cur.execute(
                    """
                    INSERT INTO products (sku, name, category, warehouse,
                                          current_stock, reorder_point,
                                          demand_rate, ordering_cost,
                                          holding_cost, unit_price, supplier_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    params,
                )
                added_products += 1

        conn.commit()
        LOGGER.info("Seed complete: %s suppliers, %s products.",
                    len(supplier_ids), added_products)
    except Exception as exc:
        conn.rollback()
        LOGGER.warning("DataCo dataset seeding deferred: %s", exc)
    finally:
        conn.close()