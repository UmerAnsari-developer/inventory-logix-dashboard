"""Utility helpers used across blueprints."""
from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable

from flask import jsonify

LOGGER = logging.getLogger(__name__)


def json_safe(value: Any) -> Any:
    """Convert ``Decimal``/``datetime`` values to JSON-safe primitives."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def api_response(data: Any = None, *, status: int = 200, message: str | None = None):
    """Return a consistent JSON envelope."""
    payload = {"success": 200 <= status < 400, "data": json_safe(data)}
    if message:
        payload["message"] = message
    return jsonify(payload), status


def api_error(code: str, message: str, *, status: int = 400, http_status: int | None = None):
    payload = {
        "success": False,
        "error": {"code": code, "message": message},
    }
    return jsonify(payload), http_status or status


def format_money_display(value) -> str:
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        v = 0.0
    if v >= 1_000_000:
        return f"\u20B9 {v / 1_000_000:.2f}Cr"
    if v >= 100_000:
        return f"\u20B9 {v / 100_000:.1f}L"
    if v >= 1000:
        return f"\u20B9 {v / 1000:.1f}K"
    return f"\u20B9 {int(v)}"


def calculate_eoq(demand: float, ordering_cost: float, holding_cost: float) -> float | None:
    if not demand or not ordering_cost or not holding_cost:
        return None
    if demand <= 0 or ordering_cost < 0 or holding_cost <= 0:
        return None
    return math.sqrt((2 * demand * ordering_cost) / holding_cost)


def calculate_total_cost(demand: float, ordering_cost: float, holding_cost: float, eoq: float) -> float | None:
    if not eoq or eoq <= 0 or demand <= 0:
        return None
    orders = float(demand) / eoq
    order_cost = orders * float(ordering_cost)
    hold_cost = (eoq / 2) * float(holding_cost)
    return order_cost + hold_cost


def calculate_reorder_point(avg_daily_demand: float, lead_days: int, safety_stock: float = 0) -> float:
    return avg_daily_demand * lead_days + safety_stock


def stock_status(stock: int, reorder_point: int,
                 low_pct: float = 20.0, critical_pct: float = 10.0) -> tuple[str, str]:
    """Classify stock health using configurable severity thresholds.

    ``low_pct`` / ``critical_pct`` are percentages of the reorder point, e.g.
    ``critical_pct=10`` means "critical below 10% of ROP".
    """
    if stock <= 0:
        return "critical", "Critical"
    if reorder_point <= 0:
        return "good", "Healthy"
    critical_line = reorder_point * (critical_pct / 100.0)
    low_line = reorder_point * (low_pct / 100.0)
    if stock <= critical_line:
        return "critical", "Critical"
    if stock <= low_line:
        return "warning", "Low stock"
    if stock <= reorder_point:
        return "warning", "Monitor"
    return "good", "Healthy"


def chunked(iterable: Iterable, size: int):
    buf: list = []
    for item in iterable:
        buf.append(item)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf
