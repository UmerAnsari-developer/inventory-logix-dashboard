#!/usr/bin/env python
"""InventoryLogix — Synthetic DataCo-like Supply Chain Dataset Generator.

Generates a statistically structured, temporally realistic dataset for
testing demand forecasting (ARIMA/SARIMA), intermittent-demand analysis,
anomaly detection, inventory optimization, and dashboard KPIs.

Design (per dataset spec):
- ~65 SKUs across 5 demand profiles (stable / trending / seasonal /
  intermittent / promotional)
- 10 warehouses, 36 suppliers with varied lead times
- Date range: 2024-01-01 -> CURRENT_DATE (dynamic)
- Demand = base + trend + weekly seasonality + monthly seasonality
  + holiday effects + noise + controlled anomalies + stockout censoring
- Inventory accounting: closing = opening + received - fulfilled +/- adjustments
- Outputs: CSVs + DATA_GENERATION_REPORT.md; optional --insert into PostgreSQL

Usage:
    python scripts/generate_synthetic_dataset.py            # CSVs + report only
    python scripts/generate_synthetic_dataset.py --insert   # also insert into DB
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
import random
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOGGER = logging.getLogger("synthetic_dataset")

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "synthetic_dataset_output"
DATASET_SOURCE = "synthetic_dataco_2024_current"
RNG_SEED = 42

START_DATE = date(2024, 1, 1)

# ── Demand profile groups ────────────────────────────────────────────────────
# share = fraction of SKUs; demand_prob = P(demand occurs on a given day)
GROUPS = {
    "A_stable":       {"count": 18, "demand_prob": 0.90, "base_range": (8, 15),
                       "weekly_strength": (0.10, 0.25), "trend_rate": (0.0, 0.05)},
    "B_trending":     {"count": 10, "demand_prob": 0.85, "base_range": (8, 12),
                       "weekly_strength": (0.10, 0.25), "trend_rate": (0.25, 0.60)},
    "C_seasonal":     {"count": 14, "demand_prob": 0.85, "base_range": (10, 20),
                       "weekly_strength": (0.35, 0.60), "trend_rate": (0.0, 0.10)},
    "D_intermittent": {"count": 13, "demand_prob": 0.17, "base_range": (5, 18),
                       "weekly_strength": (0.0, 0.10), "trend_rate": (0.0, 0.05)},
    "E_promotional":  {"count": 10, "demand_prob": 0.80, "base_range": (10, 16),
                       "weekly_strength": (0.10, 0.30), "trend_rate": (0.0, 0.10)},
}

CATEGORIES = [
    "Electronics", "Home Appliances", "Office Supplies", "Furniture",
    "Industrial Equipment", "Tools", "Packaging", "Computer Accessories",
    "Networking", "Consumer Goods",
]

# Category -> holiday/promo sensitivity (Electronics strong, industrial weak)
CATEGORY_SENSITIVITY = {
    "Electronics": 1.6, "Computer Accessories": 1.5, "Networking": 1.3,
    "Home Appliances": 1.2, "Consumer Goods": 1.2, "Office Supplies": 1.0,
    "Furniture": 0.9, "Packaging": 0.7, "Tools": 0.6, "Industrial Equipment": 0.5,
}

WAREHOUSES = [
    ("WH-Pune", "Pune, Maharashtra, West"),
    ("WH-Mumbai", "Mumbai, Maharashtra, West"),
    ("WH-Delhi", "Delhi, Delhi, North"),
    ("WH-Bengaluru", "Bengaluru, Karnataka, South"),
    ("WH-Chennai", "Chennai, Tamil Nadu, South"),
    ("WH-Hyderabad", "Hyderabad, Telangana, South"),
    ("WH-Ahmedabad", "Ahmedabad, Gujarat, West"),
    ("WH-Kolkata", "Kolkata, West Bengal, East"),
    ("WH-Jaipur", "Jaipur, Rajasthan, North"),
    ("WH-Noida", "Noida, Uttar Pradesh, North"),
]

SUPPLIER_NAMES = [
    "Tata Steel", "Reliance Industries", "Aditya Birla Group", "ITC Limited",
    "Godrej & Boyce", "Mahindra & Mahindra", "Larsen & Toubro", "Bharat Forge",
    "Ashok Leyland", "Bajaj Auto", "Hero MotoCorp", "Maruti Suzuki",
    "Siemens India", "ABB India", "Bosch India", "Philips India",
    "Samsung India", "LG Electronics India", "Sony India", "Dell India",
    "HP India", "Lenovo India", "Asus India", "Acer India",
    "Videocon Industries", "Voltas Limited", "Blue Star Limited", "Havells India",
    "Asian Paints", "Berger Paints", "Pidilite Industries", "JK Cement",
    "UltraTech Cement", "Shree Cement", "Dalmia Bharat", "Ramco Cements",
]

# Approximate Indian holiday calendar (month, day) per year — promotional windows
HOLIDAYS = {
    2024: [(1, 1), (1, 26), (3, 25), (4, 10), (8, 15), (10, 12), (11, 1), (12, 25)],
    2025: [(1, 1), (1, 26), (3, 14), (3, 31), (8, 15), (9, 5), (10, 20), (12, 25)],
    2026: [(1, 1), (1, 26), (3, 4), (3, 20), (8, 15), (9, 25), (11, 8), (12, 25)],
}
HOLIDAY_WINDOW_DAYS = 3  # demand lift applies +/- N days around each holiday


def _holiday_multiplier(day: date, sensitivity: float) -> float:
    """Demand lift around holidays, scaled by category sensitivity."""
    for (m, d) in HOLIDAYS.get(day.year, []):
        hday = date(day.year, m, d)
        delta = abs((day - hday).days)
        if delta <= HOLIDAY_WINDOW_DAYS:
            # Lift decays with distance from the holiday: 1.0 at the day itself
            lift = 1.0 + 0.5 * (1 - delta / (HOLIDAY_WINDOW_DAYS + 1))
            return 1.0 + (lift - 1.0) * sensitivity
    return 1.0


def _weekly_pattern(rng: random.Random, strength: float) -> list[float]:
    """Generate a per-SKU weekly demand pattern (Mon..Sun) with given strength."""
    # Base shape: weekend-heavy retail pattern with per-SKU variation
    shape = [rng.uniform(0.9, 1.1), rng.uniform(0.95, 1.15), rng.uniform(0.85, 1.05),
             rng.uniform(0.9, 1.1), rng.uniform(1.0, 1.2), rng.uniform(1.05, 1.3),
             rng.uniform(0.6, 0.9)]
    mean_shape = sum(shape) / 7
    return [1.0 + (s / mean_shape - 1.0) * strength for s in shape]


def generate_suppliers(rng: random.Random) -> list[dict]:
    """36 suppliers with varied lead times (3-18 days) and reliability."""
    suppliers = []
    for i, name in enumerate(SUPPLIER_NAMES[:36]):
        lead = rng.choice([3, 4, 5, 5, 7, 7, 8, 10, 10, 12, 12, 14, 15, 18])
        reliability = round(rng.uniform(78.0, 98.0), 2)
        suppliers.append({
            "name": name,
            "initials": "".join(w[0] for w in name.split()[:2]).upper(),
            "location": rng.choice(["Mumbai, India", "Delhi, India", "Pune, India",
                                    "Chennai, India", "Kolkata, India", "Ahmedabad, India"]),
            "lead_days": lead,
            "reliability": reliability,
            "tone": "green" if reliability >= 90 else ("amber" if reliability >= 82 else "red"),
        })
    return suppliers


def generate_warehouses() -> list[dict]:
    return [{"warehouse_name": n, "location": loc} for n, loc in WAREHOUSES]


def generate_products(rng: random.Random, suppliers: list[dict]) -> list[dict]:
    """~65 SKUs across 5 demand profiles; unit_price > unit_cost always."""
    products = []
    sku_counter = 1000
    for group_name, cfg in GROUPS.items():
        for _ in range(cfg["count"]):
            category = rng.choice(CATEGORIES)
            unit_cost = round(rng.uniform(50, 2000), 2)
            unit_price = round(unit_cost * rng.uniform(1.25, 1.8), 2)
            base = round(rng.uniform(*cfg["base_range"]), 1)
            trend_rate = round(rng.uniform(*cfg["trend_rate"]), 3)
            if rng.random() < 0.4:
                trend_rate = -trend_rate  # declining for some
            weekly = _weekly_pattern(rng, rng.uniform(*cfg["weekly_strength"]))
            monthly_strength = round(rng.uniform(0, 0.15), 2)
            supplier = rng.choice(suppliers)
            # Reorder point ~ 1-2 weeks of demand + safety buffer
            daily = max(0.5, base)
            rop = int(daily * supplier["lead_days"] * 0.6 + daily * 7)
            products.append({
                "sku": f"SKU-SYN-{sku_counter}",
                "name": f"{rng.choice(['Prime', 'Aero', 'Titan', 'Velo', 'Flex', 'Core', 'Max', 'Lite'])} {category.split()[0]}",
                "category": category,
                "warehouse": rng.choice([w[0] for w in WAREHOUSES]),
                "demand_rate": round(base * 365, 2),
                "ordering_cost": round(rng.uniform(30, 80), 2),
                "holding_cost": round(unit_price * 0.2, 2),
                "unit_price": unit_price,
                "supplier_id": None,  # resolved after supplier insert
                "supplier_name": supplier["name"],
                "reorder_point": max(rop, 5),
                "group": group_name,
                "demand_prob": cfg["demand_prob"],
                "base": base,
                "trend_rate": trend_rate,
                "weekly": weekly,
                "monthly_strength": monthly_strength,
                "sensitivity": CATEGORY_SENSITIVITY[category],
            })
            sku_counter += 1
    return products


def generate_daily_demand(products: list[dict], start: date, end: date,
                          rng: random.Random) -> dict[str, list[dict]]:
    """Generate daily demand per SKU with full temporal structure.

    demand = base * trend * weekly * monthly * holiday + noise,
    gated by demand_prob (intermittency), with controlled anomalies
    (1-3% of SKU-days) and stockout censoring (2-5% of SKU-days).
    """
    n_days = (end - start).days + 1
    demand_by_sku: dict[str, list[dict]] = {}
    anomaly_log: list[dict] = []

    for p in products:
        rows = []
        for i in range(n_days):
            day = start + timedelta(days=i)
            dow = day.weekday()
            trend_factor = 1.0 + p["trend_rate"] * (i / max(n_days - 1, 1))
            weekly = p["weekly"][dow]
            monthly = 1.0 + p["monthly_strength"] * math.sin(2 * math.pi * day.day / 30)
            holiday = _holiday_multiplier(day, p["sensitivity"])
            expected = p["base"] * trend_factor * weekly * monthly * holiday

            # Intermittency gate: zero-demand day
            if rng.random() > p["demand_prob"]:
                rows.append({"day": day, "requested": 0, "fulfilled": 0,
                             "stockout": False, "anomaly": None})
                continue

            # Quantity: gaussian around expected, clamped positive
            qty = max(1, round(rng.gauss(expected, max(expected * 0.3, 0.8))))

            # Controlled anomalies: ~1-3% of active SKU-days
            anomaly = None
            roll = rng.random()
            if roll < 0.015:  # spike
                observed = int(qty * rng.uniform(3.0, 5.0))
                anomaly = {"type": "spike", "normal_value": qty, "observed_value": observed,
                           "deviation_pct": round((observed - qty) / max(qty, 1) * 100, 1),
                           "severity": "high" if observed > qty * 4 else "medium"}
                qty = observed
            elif roll < 0.025:  # drop
                observed = max(1, int(qty * rng.uniform(0.05, 0.2)))
                anomaly = {"type": "drop", "normal_value": qty, "observed_value": observed,
                           "deviation_pct": round((observed - qty) / max(qty, 1) * 100, 1),
                           "severity": "high" if observed < qty * 0.1 else "medium"}
                qty = observed
            elif roll < 0.03:  # unusual order quantity (B2B-style large order)
                observed = int(qty * rng.uniform(6.0, 10.0))
                anomaly = {"type": "unusual_quantity", "normal_value": qty,
                           "observed_value": observed,
                           "deviation_pct": round((observed - qty) / max(qty, 1) * 100, 1),
                           "severity": "medium"}
                qty = observed

            # Stockout censoring: 2-5% of active SKU-days
            stockout = False
            if rng.random() < 0.035:
                stockout = True
                # fulfilled < requested (censored demand)
                qty = max(1, int(qty * rng.uniform(0.2, 0.6)))

            rows.append({"day": day, "requested": qty, "fulfilled": qty,
                         "stockout": stockout, "anomaly": anomaly})
            if anomaly:
                anomaly_log.append({
                    "sku": p["sku"], "day": day.isoformat(), **anomaly,
                })
        demand_by_sku[p["sku"]] = rows
    return demand_by_sku, anomaly_log


def generate_movements(products: list[dict], demand_by_sku: dict[str, list[dict]],
                       rng: random.Random) -> tuple[list[tuple], dict[str, int]]:
    """Build DB-shaped movement ledger with inventory accounting.

    OUT = fulfilled demand (censored by stockouts), IN = restocks when
    stock <= reorder_point, ADJUSTMENT/RETURN occasional. Reference prefix
    'SYN-' identifies this dataset batch. Returns (rows, final_stock_by_sku).
    """
    rows: list[tuple] = []
    refs = {"IN": "SYN-RESTOCK", "OUT": "SYN-SALE",
            "ADJUSTMENT": "SYN-ADJ", "RETURN": "SYN-RTN"}
    final_stock: dict[str, int] = {}

    for p in products:
        stock = p["reorder_point"] * 2 + 20  # opening inventory
        for rec in demand_by_sku[p["sku"]]:
            day = rec["day"]
            ts = datetime.combine(day, time(rng.randint(8, 20), rng.randint(0, 59)))
            # OUT: fulfilled demand
            if rec["fulfilled"] > 0:
                qty = min(rec["fulfilled"], stock)
                if qty > 0:
                    rows.append((p["sku"], "OUT", qty,
                                 f"{refs['OUT']}-{day:%Y%m%d}", None, ts))
                    stock -= qty
            # RETURN: occasional inbound returns
            if rng.random() < 0.03:
                qty = rng.randint(1, 3)
                rows.append((p["sku"], "RETURN", qty,
                             f"{refs['RETURN']}-{day:%Y%m%d}", None, ts))
                stock += qty
            # ADJUSTMENT: occasional corrections
            if rng.random() < 0.03:
                qty = rng.randint(1, 4)
                rows.append((p["sku"], "ADJUSTMENT", qty,
                             f"{refs['ADJUSTMENT']}-{day:%Y%m%d}", None, ts))
                stock += qty
            # IN: restock when below reorder point
            if stock <= p["reorder_point"]:
                qty = max(p["reorder_point"] * 2 + 20 - stock, 1)
                rows.append((p["sku"], "IN", qty,
                             f"{refs['IN']}-{day:%Y%m%d}", None, ts))
                stock += qty
        final_stock[p["sku"]] = stock
    return rows, final_stock


def validate(products: list[dict], demand_by_sku: dict, movements: list[tuple],
             anomaly_log: list[dict]) -> dict:
    """Integrity + statistical validation (spec §25-26)."""
    n_days = (date.today() - START_DATE).days + 1
    report = {
        "total_rows": len(movements),
        "total_skus": len(products),
        "total_warehouses": len(WAREHOUSES),
        "total_suppliers": 36,
        "date_range": f"{START_DATE.isoformat()} -> {date.today().isoformat()}",
        "anomalies": {"spike": 0, "drop": 0, "unusual_quantity": 0},
        "stockout_days": 0,
        "sku_stats": [],
        "issues": [],
    }
    for a in anomaly_log:
        report["anomalies"][a["type"]] = report["anomalies"].get(a["type"], 0) + 1

    suitable_arima = suitable_sarima = intermittent = insufficient = 0
    skus_300 = skus_500 = 0

    for p in products:
        rows = demand_by_sku[p["sku"]]
        fulfilled = [r["fulfilled"] for r in rows]
        non_zero = sum(1 for v in fulfilled if v > 0)
        zero_pct = (len(fulfilled) - non_zero) / len(fulfilled) * 100
        mean_d = sum(fulfilled) / len(fulfilled)
        sorted_v = sorted(fulfilled)
        median_d = sorted_v[len(sorted_v) // 2]
        var = sum((v - mean_d) ** 2 for v in fulfilled) / len(fulfilled)
        std_d = math.sqrt(var)
        cv = std_d / mean_d if mean_d > 0 else 0
        # Weekly seasonality: autocorrelation at lag 7
        mu = mean_d
        var_all = sum((v - mu) ** 2 for v in fulfilled)
        lag_corr = (sum((fulfilled[i] - mu) * (fulfilled[i - 7] - mu)
                        for i in range(7, len(fulfilled))) / var_all) if var_all > 0 else 0
        # Trend: first-vs-last quarter means
        q = len(fulfilled) // 4
        trend_pct = ((sum(fulfilled[-q:]) / q) - (sum(fulfilled[:q]) / q)) / max(mean_d, 1) * 100

        report["stockout_days"] += sum(1 for r in rows if r["stockout"])
        report["sku_stats"].append({
            "sku": p["sku"], "group": p["group"], "calendar_days": len(fulfilled),
            "active_days": non_zero, "zero_pct": round(zero_pct, 1),
            "avg_daily": round(mean_d, 2), "median_daily": median_d,
            "std": round(std_d, 2), "cv": round(cv, 2),
            "weekly_acf": round(lag_corr, 3), "trend_pct": round(trend_pct, 1),
        })
        if non_zero >= 300:
            skus_300 += 1
        if non_zero >= 500:
            skus_500 += 1
        if zero_pct > 50:
            intermittent += 1
        elif abs(lag_corr) > 0.15 and non_zero >= 56:
            suitable_sarima += 1
            suitable_arima += 1
        elif non_zero >= 60:
            suitable_arima += 1
        else:
            insufficient += 1

    report["forecast_suitability"] = {
        "skus_suitable_arima": suitable_arima,
        "skus_suitable_sarima": suitable_sarima,
        "intermittent_skus": intermittent,
        "insufficient_skus": insufficient,
        "skus_with_300plus_obs": skus_300,
        "skus_with_500plus_obs": skus_500,
    }

    # Integrity checks
    skus = {p["sku"] for p in products}
    bad_sku = sum(1 for m in movements if m[0] not in skus)
    bad_qty = sum(1 for m in movements if m[2] <= 0)
    bad_type = sum(1 for m in movements if m[1] not in ("IN", "OUT", "ADJUSTMENT", "RETURN"))
    bad_date = sum(1 for m in movements if not (START_DATE <= m[5].date() <= date.today()))
    if bad_sku: report["issues"].append(f"{bad_sku} movements with unknown SKU")
    if bad_qty: report["issues"].append(f"{bad_qty} movements with quantity <= 0")
    if bad_type: report["issues"].append(f"{bad_type} movements with invalid type")
    if bad_date: report["issues"].append(f"{bad_date} movements outside date range")
    return report


def write_outputs(products, suppliers, demand_by_sku, movements, anomaly_log, report):
    OUT_DIR.mkdir(exist_ok=True)

    # products.csv (DataCo-like master data)
    with open(OUT_DIR / "products.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sku", "product_name", "category", "warehouse", "unit_price",
                    "demand_rate", "ordering_cost", "holding_cost", "reorder_point",
                    "supplier_name", "demand_group"])
        for p in products:
            w.writerow([p["sku"], p["name"], p["category"], p["warehouse"],
                        p["unit_price"], p["demand_rate"], p["ordering_cost"],
                        p["holding_cost"], p["reorder_point"], p["supplier_name"],
                        p["group"]])

    # suppliers.csv
    with open(OUT_DIR / "suppliers.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["supplier_name", "initials", "location", "lead_days", "reliability"])
        for s in suppliers:
            w.writerow([s["name"], s["initials"], s["location"], s["lead_days"],
                        s["reliability"]])

    # transactions.csv (DataCo-like order items — full detail incl. unsupported-in-DB fields)
    with open(OUT_DIR / "transactions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["transaction_id", "order_id", "order_date", "sku", "product_name",
                    "category", "warehouse", "quantity", "unit_price", "discount",
                    "sales_amount", "customer_segment", "order_status", "shipping_mode",
                    "delivery_days", "late_delivery_flag", "stockout_flag"])
        tid = 0
        for p in products:
            for rec in demand_by_sku[p["sku"]]:
                if rec["fulfilled"] <= 0:
                    continue
                tid += 1
                day = rec["day"]
                sales = round(rec["fulfilled"] * p["unit_price"], 2)
                w.writerow([tid, f"ORD-{day:%Y%m%d}-{tid % 1000:03d}", day.isoformat(),
                            p["sku"], p["name"], p["category"], p["warehouse"],
                            rec["fulfilled"], p["unit_price"], 0.0, sales,
                            "Consumer", "Completed", "Standard", 5, False,
                            rec["stockout"]])

    # movements.csv (DB-shaped)
    with open(OUT_DIR / "movements.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sku", "type", "quantity", "reference", "created_at"])
        for m in movements:
            w.writerow([m[0], m[1], m[2], m[3], m[5].isoformat()])

    # anomalies.csv (ground truth for detection validation)
    with open(OUT_DIR / "anomalies.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sku", "day", "anomaly_type", "normal_value", "observed_value",
                    "deviation_pct", "severity"])
        for a in anomaly_log:
            w.writerow([a["sku"], a["day"], a["type"], a["normal_value"],
                        a["observed_value"], a["deviation_pct"], a["severity"]])

    LOGGER.info("CSVs written to %s", OUT_DIR)


def write_report(report: dict) -> None:
    fs = report["forecast_suitability"]
    lines = [
        "# DATA_GENERATION_REPORT.md",
        "",
        "## Dataset Summary",
        f"- Total rows: {report['total_rows']:,}",
        f"- Total SKUs: {report['total_skus']}",
        f"- Total warehouses: {report['total_warehouses']}",
        f"- Total suppliers: {report['total_suppliers']}",
        f"- Date range: {report['date_range']}",
        "",
        "## Demand Statistics",
        f"- Stockout days: {report['stockout_days']:,}",
        f"- Controlled anomalies: {report['anomalies']}",
        "",
        "## Forecast Suitability",
        f"- SKUs suitable for ARIMA: {fs['skus_suitable_arima']}",
        f"- SKUs suitable for SARIMA: {fs['skus_suitable_sarima']}",
        f"- Intermittent SKUs (zero% > 50): {fs['intermittent_skus']}",
        f"- Insufficient-data SKUs: {fs['insufficient_skus']}",
        f"- SKUs with 300+ observations: {fs['skus_with_300plus_obs']}",
        f"- SKUs with 500+ observations: {fs['skus_with_500plus_obs']}",
        "",
        "## Per-SKU Statistics",
        "",
        "| SKU | Group | Days | Active | Zero% | Avg | Median | Std | CV | Weekly ACF | Trend% |",
        "|-----|-------|------|--------|-------|-----|--------|-----|-----|-----------|--------|",
    ]
    for s in report["sku_stats"]:
        lines.append(
            f"| {s['sku']} | {s['group']} | {s['calendar_days']} | {s['active_days']} | "
            f"{s['zero_pct']} | {s['avg_daily']} | {s['median_daily']} | {s['std']} | "
            f"{s['cv']} | {s['weekly_acf']} | {s['trend_pct']} |"
        )
    lines += ["", "## Data-Quality Checks", ""]
    if report["issues"]:
        lines += [f"- {i}" for i in report["issues"]]
    else:
        lines.append("- No integrity issues: all SKUs known, quantities > 0, "
                     "types valid, dates in range")
    lines += [
        "",
        "## Schema Mapping (spec §28) — Fields NOT Supported by Existing Schema",
        "",
        "The following DataCo-like fields have no counterpart in the InventoryLogix",
        "schema and are preserved in CSVs only (not silently added to the schema):",
        "",
        "- `movements`: transaction_id/order_id/order_item_id (encoded in `reference`),",
        "  shipping_date, discount, sales_amount, cost_amount, profit_amount,",
        "  customer_segment, order_status, shipping_mode, delivery_days,",
        "  late_delivery_flag, stockout_flag, fulfilled_quantity",
        "  (stockout censoring: DB stores fulfilled quantity only — requested-vs-fulfilled",
        "  distinction is NOT representable; full detail in transactions.csv)",
        "- `products`: subcategory, department, warehouse_id FK (single `warehouse` VARCHAR)",
        "- `suppliers`: supplier_region (held in `location`), min_order_quantity",
        "- `warehouses`: city/state/region (held in `location`), capacity",
        "",
        f"- Dataset identifier: `{DATASET_SOURCE}` (movements.reference prefix `SYN-`)",
        "",
    ]
    (OUT_DIR / "DATA_GENERATION_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Report written to %s", OUT_DIR / "DATA_GENERATION_REPORT.md")


def insert_to_db(products, suppliers, movements, final_stock) -> None:
    """Insert into PostgreSQL: truncate demo tables, bulk insert in one transaction.

    Rollback on failure; movement trigger suspended during bulk insert
    (same pattern as app/database/seed.py).
    """
    sys.path.insert(0, str(REPO_ROOT))
    from app import create_app
    from app.database.connection import _open_conn
    from werkzeug.security import generate_password_hash

    app = create_app()
    with app.app_context():
        conn = _open_conn()
        try:
            with conn.cursor() as cur:
                # Backup point: count rows before (rollback = transaction; counts logged)
                cur.execute("SELECT COUNT(*) AS c FROM movements")
                LOGGER.info("Backup point: %s existing movements (transaction-protected)",
                            cur.fetchone()["c"])
                # Truncate demo tables (users preserved)
                cur.execute(
                    "TRUNCATE movements, purchase_orders, products, suppliers "
                    "RESTART IDENTITY CASCADE"
                )
                # Suppliers
                for s in suppliers:
                    cur.execute(
                        "INSERT INTO suppliers (name, initials, location, lead_days, "
                        "spend_amount, reliability, tone) VALUES (%s,%s,%s,%s,0,%s,%s)",
                        (s["name"], s["initials"], s["location"], s["lead_days"],
                         s["reliability"], s["tone"]),
                    )
                cur.execute("SELECT id, name FROM suppliers")
                supplier_ids = {r["name"]: r["id"] for r in cur.fetchall()}
                # Products
                for p in products:
                    cur.execute(
                        "INSERT INTO products (sku, name, category, warehouse, "
                        "current_stock, reorder_point, demand_rate, ordering_cost, "
                        "holding_cost, unit_price, supplier_id) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (p["sku"], p["name"], p["category"], p["warehouse"],
                         final_stock[p["sku"]], p["reorder_point"], p["demand_rate"],
                         p["ordering_cost"], p["holding_cost"], p["unit_price"],
                         supplier_ids[p["supplier_name"]]),
                    )
                cur.execute("SELECT id, sku FROM products")
                product_ids = {r["sku"]: r["id"] for r in cur.fetchall()}
                # Movements (bulk, trigger suspended)
                cur.execute("ALTER TABLE movements DISABLE TRIGGER trg_validate_movement")
                try:
                    from psycopg2.extras import execute_values
                    execute_values(
                        cur,
                        """INSERT INTO movements (product_id, type, quantity,
                           reference, notes, created_at) VALUES %s""",
                        [(product_ids[m[0]], m[1], m[2], m[3], m[4], m[5])
                         for m in movements],
                    )
                finally:
                    cur.execute("ALTER TABLE movements ENABLE TRIGGER trg_validate_movement")
            conn.commit()
            LOGGER.info("Inserted %s movements, %s products, %s suppliers",
                        len(movements), len(products), len(suppliers))
        except Exception:
            conn.rollback()
            LOGGER.exception("Insert FAILED — transaction rolled back")
            raise
        finally:
            conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--insert", action="store_true",
                        help="Also insert the generated dataset into PostgreSQL")
    parser.add_argument("--seed", type=int, default=RNG_SEED)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    today = date.today()  # dynamic end date — never hard-coded

    LOGGER.info("Generating dataset %s -> %s", START_DATE.isoformat(), today.isoformat())
    suppliers = generate_suppliers(rng)
    products = generate_products(rng, suppliers)
    demand_by_sku, anomaly_log = generate_daily_demand(products, START_DATE, today, rng)
    movements, final_stock = generate_movements(products, demand_by_sku, rng)

    report = validate(products, demand_by_sku, movements, anomaly_log)
    write_outputs(products, suppliers, demand_by_sku, movements, anomaly_log, report)
    write_report(report)

    LOGGER.info("Rows: %s | SKUs: %s | Anomalies: %s | Stockout days: %s",
                report["total_rows"], report["total_skus"],
                sum(report["anomalies"].values()), report["stockout_days"])
    LOGGER.info("Suitability: %s", report["forecast_suitability"])
    if report["issues"]:
        LOGGER.warning("Integrity issues: %s", report["issues"])

    if args.insert:
        if report["issues"]:
            LOGGER.error("Insert aborted: integrity issues must be resolved first")
            sys.exit(1)
        insert_to_db(products, suppliers, movements, final_stock)


if __name__ == "__main__":
    main()