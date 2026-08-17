"""Forecast and anomaly cache repositories."""
from __future__ import annotations

import json as _json

from ..database import get_cursor


class ForecastRepository:
    @staticmethod
    def save(product_id: int, model: str, horizon: int, payload: dict) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO forecast_cache (product_id, model, horizon, payload, accuracy)
                VALUES (%s,%s,%s,%s,%s)
                """,
                (product_id, model, horizon, _json.dumps(payload), payload.get("accuracy")),
            )

    @staticmethod
    def recent(product_id: int, limit: int = 5) -> list[dict]:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT id, model, horizon, accuracy, generated_at, payload
                FROM forecast_cache WHERE product_id = %s
                ORDER BY generated_at DESC LIMIT %s
                """,
                (product_id, limit),
            )
            rows = list(cur.fetchall())
        for row in rows:
            if isinstance(row.get("payload"), str):
                row["payload"] = _json.loads(row["payload"])
        return rows

    @staticmethod
    def recent_for(product_id: int, model: str, horizon: int, limit: int = 1) -> list[dict]:
        """Latest stored forecast for an exact product + model + horizon.

        Uses the idx_forecast_cache_lookup composite index.
        """
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT id, model, horizon, accuracy, generated_at, payload
                FROM forecast_cache
                WHERE product_id = %s AND model = %s AND horizon = %s
                ORDER BY generated_at DESC LIMIT %s
                """,
                (product_id, model, horizon, limit),
            )
            rows = list(cur.fetchall())
        for row in rows:
            if isinstance(row.get("payload"), str):
                row["payload"] = _json.loads(row["payload"])
        return rows


class AnomalyRepository:
    @staticmethod
    def save(*, product_id: int, anomaly_type: str, z_score: float | None,
             confidence: float | None, description: str | None) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO anomaly_log (product_id, anomaly_type, z_score, confidence, description)
                VALUES (%s,%s,%s,%s,%s)
                """,
                (product_id, anomaly_type, z_score, confidence, description),
            )

    @staticmethod
    def recent(limit: int = 50) -> list[dict]:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT a.*, p.sku, p.name AS product_name
                FROM anomaly_log a LEFT JOIN products p ON p.id = a.product_id
                ORDER BY a.detected_at DESC LIMIT %s
                """,
                (limit,),
            )
            return list(cur.fetchall())
