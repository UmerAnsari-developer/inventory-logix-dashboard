"""EOQ service — orchestrates calculations and product-by-product table data."""
from __future__ import annotations

import logging

from ..repositories import ProductRepository
from ..utils import calculate_eoq, calculate_total_cost
from ..utils.helpers import calculate_total_cost as _cost

LOGGER = logging.getLogger(__name__)


class EOQService:
    @staticmethod
    def per_product_table() -> list[dict]:
        from ..database import get_cursor
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT sku, name, demand_rate, ordering_cost, holding_cost,
                       unit_price, current_stock, reorder_point
                FROM products
                WHERE demand_rate > 0 AND ordering_cost >= 0 AND holding_cost > 0
                ORDER BY sku
                """
            )
            rows = cur.fetchall()
        out = []
        for row in rows:
            eoq = calculate_eoq(row["demand_rate"], row["ordering_cost"], row["holding_cost"])
            if not eoq:
                continue
            total = _cost(row["demand_rate"], row["ordering_cost"], row["holding_cost"], eoq)
            out.append({
                "sku": row["sku"],
                "name": row["name"],
                "demand": float(row["demand_rate"]),
                "ordering": float(row["ordering_cost"]),
                "holding": float(row["holding_cost"]),
                "price": float(row["unit_price"] or 0),
                "stock": int(row["current_stock"] or 0),
                "rop": int(row["reorder_point"] or 0),
                "eoq": round(eoq),
                "total_cost": round(total, 2) if total else None,
            })
        return out

    @staticmethod
    def cost_curve(eoq: float, demand: float, ordering_cost: float, holding_cost: float) -> list[dict]:
        """Return ``{order_qty, total_cost}`` points across an EOQ range."""
        if not eoq or eoq <= 0:
            return []
        points = []
        max_q = max(eoq * 2.2, eoq + 1)
        step = max(1, int(max_q / 60))
        q = max(1, step)
        while q <= max_q:
            orders = demand / q if q else 0
            order_cost = orders * ordering_cost
            hold_cost = (q / 2) * holding_cost
            points.append({"q": q, "total": order_cost + hold_cost})
            q += step
        return points

    @staticmethod
    def sensitivity_surface(demand: float, ordering_cost: float, holding_cost: float) -> dict:
        """Build a 3-axis grid for an EOQ sensitivity surface."""
        if not demand or demand <= 0:
            return {"x": [], "y": [], "z": []}
        demands = [demand * f for f in (0.5, 0.75, 1.0, 1.25, 1.5)]
        orderings = [ordering_cost * f for f in (0.5, 1.0, 1.5, 2.0)]
        z = []
        for d in demands:
            row = []
            for o in orderings:
                eoq = calculate_eoq(d, o, holding_cost) or 0
                orders = d / eoq if eoq else 0
                row.append(orders * o + (eoq / 2) * holding_cost)
            z.append(row)
        return {"x": orderings, "y": demands, "z": z}
