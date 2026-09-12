"""Forecast and anomaly cache repositories."""
from __future__ import annotations

import json as _json
from datetime import date, datetime

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


class AnomalyRepository:
    @staticmethod
    def save(*, product_id: int, anomaly_type: str, z_score: float | None,
             confidence: float | None, description: str | None,
             sku: str | None = None,
             expected_value: float | None = None,
             observed_value: float | None = None,
             deviation_pct: float | None = None,
             metric: str = "quantity",
             alert_date: date | str | None = None,
             risk_level: str = "low",
             detection_method: str = "zscore",
             recommended_action: str | None = None,
             status: str = "new") -> int:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO anomaly_log (
                    product_id, anomaly_type, z_score, confidence, description,
                    sku, expected_value, observed_value, deviation_pct,
                    metric, alert_date, risk_level, detection_method,
                    recommended_action, status
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (
                    product_id, anomaly_type, z_score, confidence, description,
                    sku, expected_value, observed_value, deviation_pct,
                    metric, alert_date, risk_level, detection_method,
                    recommended_action, status,
                ),
            )
            return cur.fetchone()["id"]

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

    @staticmethod
    def find_by_id(alert_id: int) -> dict | None:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT a.*, p.sku, p.name AS product_name
                FROM anomaly_log a LEFT JOIN products p ON p.id = a.product_id
                WHERE a.id = %s
                """,
                (alert_id,),
            )
            return cur.fetchone()

    @staticmethod
    def find_by_product(product_id: int, limit: int = 50) -> list[dict]:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT a.*, p.sku, p.name AS product_name
                FROM anomaly_log a LEFT JOIN products p ON p.id = a.product_id
                WHERE a.product_id = %s
                ORDER BY a.detected_at DESC LIMIT %s
                """,
                (product_id, limit),
            )
            return list(cur.fetchall())

    @staticmethod
    def filter_alerts(*, risk_level: str | None = None, status: str | None = None,
                      anomaly_type: str | None = None,
                      date_from: date | str | None = None,
                      date_to: date | str | None = None,
                      limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        """Return filtered alerts with count."""
        where, params = [], []
        if risk_level:
            where.append("a.risk_level = %s")
            params.append(risk_level)
        if status:
            where.append("a.status = %s")
            params.append(status)
        if anomaly_type:
            where.append("a.anomaly_type = %s")
            params.append(anomaly_type)
        if date_from:
            where.append("a.alert_date >= %s")
            params.append(date_from)
        if date_to:
            where.append("a.alert_date <= %s")
            params.append(date_to)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        params_count = list(params)

        with get_cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS c FROM anomaly_log a {where_sql}",
                params_count,
            )
            total = cur.fetchone()["c"]

            cur.execute(
                f"""
                SELECT a.*, p.sku, p.name AS product_name
                FROM anomaly_log a LEFT JOIN products p ON p.id = a.product_id
                {where_sql}
                ORDER BY a.detected_at DESC LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            rows = list(cur.fetchall())
        return rows, total

    @staticmethod
    def update_status(alert_id: int, status: str, *,
                      reviewed_by: int | None = None) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE anomaly_log
                SET status = %s, reviewed_at = NOW(), reviewed_by = %s
                WHERE id = %s
                """,
                (status, reviewed_by, alert_id),
            )

    @staticmethod
    def counts_by_risk() -> dict:
        with get_cursor() as cur:
            cur.execute(
                "SELECT risk_level, COUNT(*) AS c FROM anomaly_log GROUP BY risk_level"
            )
            return {row["risk_level"]: row["c"] for row in cur.fetchall()}

    @staticmethod
    def counts_by_status() -> dict:
        with get_cursor() as cur:
            cur.execute(
                "SELECT status, COUNT(*) AS c FROM anomaly_log GROUP BY status"
            )
            return {row["status"]: row["c"] for row in cur.fetchall()}

    @staticmethod
    def total_count() -> int:
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM anomaly_log")
            return cur.fetchone()["c"]

    @staticmethod
    def recent_alerts(limit: int = 20) -> list[dict]:
        """Return recent alerts with product info for dashboard display."""
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
