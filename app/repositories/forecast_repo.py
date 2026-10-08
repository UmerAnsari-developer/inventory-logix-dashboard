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
                ON CONFLICT (product_id, model, horizon)
                DO UPDATE SET payload = EXCLUDED.payload,
                              accuracy = EXCLUDED.accuracy,
                              generated_at = NOW()
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
    def save_backtest_results(product_id: int, model_name: str, horizon: int, results: list) -> None:
        """Save rolling-origin backtest results."""
        if not results:
            return
        with get_cursor(commit=True) as cur:
            from psycopg2.extras import execute_values
            # Get SKU for the product
            cur.execute("SELECT sku FROM products WHERE id = %s", (product_id,))
            sku_row = cur.fetchone()
            sku = sku_row["sku"] if sku_row else f"PRODUCT-{product_id}"

            execute_values(
                cur,
                """INSERT INTO forecast_backtest_results
                   (product_id, sku, model_name, baseline_name, origin_date, horizon,
                    mae, mape, rmse, wape, mase, bias, interval_coverage, observation_count)
                   VALUES %s""",
                [
                    (product_id, sku, r.model_name, None, r.origin_date, r.horizon,
                     r.mae, r.mape, r.rmse, r.wape, r.mase, r.bias, r.interval_coverage, r.observation_count)
                    for r in results if r.leakage_ok  # never persist leakage-flagged origins
                ],
                template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            )

    @staticmethod
    def get_backtest_results(*, product_id: int | None = None, sku: str | None = None,
                             model_name: str | None = None, horizon: int | None = None,
                             date_from: date | None = None, date_to: date | None = None,
                             limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        """Retrieve backtest results with filters."""
        where, params = [], []
        if product_id:
            where.append("product_id = %s"); params.append(product_id)
        if sku:
            where.append("sku = %s"); params.append(sku)
        if model_name:
            where.append("model_name = %s"); params.append(model_name)
        if horizon:
            where.append("horizon = %s"); params.append(horizon)
        if date_from:
            where.append("origin_date >= %s"); params.append(date_from)
        if date_to:
            where.append("origin_date <= %s"); params.append(date_to)
        w = ("WHERE " + " AND ".join(where)) if where else ""
        with get_cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM forecast_backtest_results {w}", params)
            total = cur.fetchone()["count"]
            cur.execute(
                f"""SELECT * FROM forecast_backtest_results {w}
                    ORDER BY origin_date DESC LIMIT %s OFFSET %s""",
                params + [limit, offset],
            )
            return list(cur.fetchall()), total


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
                ON CONFLICT (product_id, COALESCE(alert_date, detected_at::date),
                             anomaly_type, COALESCE(detection_method, 'zscore'))
                DO UPDATE SET z_score = EXCLUDED.z_score,
                              confidence = EXCLUDED.confidence,
                              description = EXCLUDED.description,
                              expected_value = EXCLUDED.expected_value,
                              observed_value = EXCLUDED.observed_value,
                              deviation_pct = EXCLUDED.deviation_pct,
                              risk_level = EXCLUDED.risk_level,
                              recommended_action = EXCLUDED.recommended_action,
                              detected_at = NOW(),
                              -- Re-open only when a NEW detection arrives
                              -- (plan W1-B4): reviewers revisit fresh signals.
                              status = 'new',
                              reviewed_at = NULL,
                              reviewed_by = NULL
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
    def update_label(alert_id: int, label: str, labeled_by: int, new_status: str) -> None:
        """Update anomaly label (true_positive/false_positive) and status."""
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE anomaly_log
                SET label = %s, labeled_at = NOW(), labeled_by = %s, status = %s
                WHERE id = %s
                """,
                (label, labeled_by, new_status, alert_id),
            )

    @staticmethod
    def get_labeled_alerts(*, risk_level: str | None = None,
                           detection_method: str | None = None,
                           limit: int = 500) -> list[dict]:
        """Get alerts that have been labeled for precision/recall computation."""
        where = ["label IS NOT NULL"]
        params = []
        if risk_level:
            where.append("risk_level = %s"); params.append(risk_level)
        if detection_method:
            where.append("detection_method = %s"); params.append(detection_method)
        w = "WHERE " + " AND ".join(where)
        with get_cursor() as cur:
            cur.execute(
                f"""SELECT * FROM anomaly_log {w}
                    ORDER BY labeled_at DESC LIMIT %s""",
                params + [limit],
            )
            return list(cur.fetchall())

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