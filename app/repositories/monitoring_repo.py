"""Repository for forecast model monitoring tables."""
from __future__ import annotations

from datetime import date, timedelta

from ..database import get_cursor


class MonitoringRepository:

    # ── Predictions ──────────────────────────────────────────────

    @staticmethod
    def save_prediction(*, sku: str, model_name: str, forecast_date,
                        predicted_value: float, forecast_horizon: int = 1,
                        forecast_generated_at=None) -> int:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """INSERT INTO forecast_predictions
                   (sku, model_name, forecast_date, predicted_value, forecast_horizon,
                    forecast_generated_at, status)
                   VALUES (%s,%s,%s,%s,%s, COALESCE(%s, NOW()), 'pending')
                   RETURNING id""",
                (sku, model_name, forecast_date, predicted_value, forecast_horizon,
                 forecast_generated_at),
            )
            return cur.fetchone()["id"]

    @staticmethod
    def update_actual(prediction_id: int, actual_value: float) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """UPDATE forecast_predictions
                   SET actual_value = %s, status = 'evaluated'
                   WHERE id = %s""",
                (actual_value, prediction_id),
            )

    @staticmethod
    def find_pending_evaluations(limit: int = 500) -> list[dict]:
        with get_cursor() as cur:
            cur.execute(
                """SELECT * FROM forecast_predictions
                   WHERE status = 'pending' AND actual_value IS NOT NULL
                   ORDER BY forecast_date ASC LIMIT %s""",
                (limit,),
            )
            return list(cur.fetchall())

    @staticmethod
    def get_predictions(*, sku: str | None = None, model_name: str | None = None,
                        date_from=None, date_to=None,
                        limit: int = 200, offset: int = 0) -> tuple[list[dict], int]:
        where, params = [], []
        if sku:
            where.append("sku = %s"); params.append(sku)
        if model_name:
            where.append("model_name = %s"); params.append(model_name)
        if date_from:
            where.append("forecast_date >= %s"); params.append(date_from)
        if date_to:
            where.append("forecast_date <= %s"); params.append(date_to)
        w = ("WHERE " + " AND ".join(where)) if where else ""
        with get_cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM forecast_predictions {w}", params)
            total = cur.fetchone()["count"]
            cur.execute(
                f"""SELECT * FROM forecast_predictions {w}
                    ORDER BY forecast_date DESC LIMIT %s OFFSET %s""",
                params + [limit, offset],
            )
            return list(cur.fetchall()), total

    @staticmethod
    def actual_vs_predicted(*, sku: str | None = None, model_name: str | None = None,
                            date_from=None, date_to=None,
                            limit: int = 200) -> list[dict]:
        where = ["status = 'evaluated'", "actual_value IS NOT NULL"]
        params: list = []
        if sku:
            where.append("sku = %s"); params.append(sku)
        if model_name:
            where.append("model_name = %s"); params.append(model_name)
        if date_from:
            where.append("forecast_date >= %s"); params.append(date_from)
        if date_to:
            where.append("forecast_date <= %s"); params.append(date_to)
        w = "WHERE " + " AND ".join(where)
        with get_cursor() as cur:
            cur.execute(
                f"""SELECT sku, model_name, forecast_date, predicted_value,
                           actual_value, (actual_value - predicted_value) AS error
                    FROM forecast_predictions {w}
                    ORDER BY forecast_date ASC LIMIT %s""",
                params + [limit],
            )
            return list(cur.fetchall())

    # ── Monitoring Metrics ───────────────────────────────────────

    @staticmethod
    def save_metrics(*, sku: str, model_name: str, monitoring_date,
                     aggregation_period: str, observation_count: int,
                     mae, mape, rmse, mean_error, error_std,
                     zero_demand_count: int, baseline_mae, baseline_mape,
                     mae_change_percent, mape_change_percent,
                     model_status: str) -> int:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """INSERT INTO forecast_monitoring_metrics
                   (sku, model_name, monitoring_date, aggregation_period,
                    observation_count, mae, mape, rmse, mean_error, error_std,
                    zero_demand_count, baseline_mae, baseline_mape,
                    mae_change_percent, mape_change_percent, model_status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id""",
                (sku, model_name, monitoring_date, aggregation_period,
                 observation_count, mae, mape, rmse, mean_error, error_std,
                 zero_demand_count, baseline_mae, baseline_mape,
                 mae_change_percent, mape_change_percent, model_status),
            )
            return cur.fetchone()["id"]

    @staticmethod
    def get_metrics(*, sku: str | None = None, model_name: str | None = None,
                    date_from=None, date_to=None,
                    limit: int = 200) -> list[dict]:
        where, params = [], []
        if sku:
            where.append("sku = %s"); params.append(sku)
        if model_name:
            where.append("model_name = %s"); params.append(model_name)
        if date_from:
            where.append("monitoring_date >= %s"); params.append(date_from)
        if date_to:
            where.append("monitoring_date <= %s"); params.append(date_to)
        w = ("WHERE " + " AND ".join(where)) if where else ""
        with get_cursor() as cur:
            cur.execute(
                f"""SELECT * FROM forecast_monitoring_metrics {w}
                    ORDER BY monitoring_date DESC LIMIT %s""",
                params + [limit],
            )
            return list(cur.fetchall())

    @staticmethod
    def latest_metrics(sku: str, model_name: str) -> dict | None:
        with get_cursor() as cur:
            cur.execute(
                """SELECT * FROM forecast_monitoring_metrics
                   WHERE sku = %s AND model_name = %s
                   ORDER BY monitoring_date DESC LIMIT 1""",
                (sku, model_name),
            )
            return cur.fetchone()

    @staticmethod
    def baseline_metrics(sku: str, model_name: str) -> dict | None:
        """Get the oldest metrics entry as baseline (first evaluation period)."""
        with get_cursor() as cur:
            cur.execute(
                """SELECT * FROM forecast_monitoring_metrics
                   WHERE sku = %s AND model_name = %s
                   ORDER BY monitoring_date ASC LIMIT 1""",
                (sku, model_name),
            )
            return cur.fetchone()

    @staticmethod
    def recent_statuses(sku: str, model_name: str, limit: int = 30) -> list[str]:
        with get_cursor() as cur:
            cur.execute(
                """SELECT model_status FROM forecast_monitoring_metrics
                   WHERE sku = %s AND model_name = %s
                   ORDER BY monitoring_date DESC LIMIT %s""",
                (sku, model_name, limit),
            )
            return [r["model_status"] for r in cur.fetchall()]

    @staticmethod
    def model_summary() -> list[dict]:
        """Latest metrics per SKU+Model for the health table."""
        with get_cursor() as cur:
            cur.execute(
                """SELECT DISTINCT ON (sku, model_name)
                   sku, model_name, mae, mape, rmse, mean_error,
                   baseline_mae, baseline_mape, mae_change_percent,
                   mape_change_percent, model_status, monitoring_date,
                   observation_count
                   FROM forecast_monitoring_metrics
                   ORDER BY sku, model_name, monitoring_date DESC"""
            )
            return list(cur.fetchall())

    # ── Alerts ───────────────────────────────────────────────────

    @staticmethod
    def save_alert(*, sku: str, model_name: str, alert_date, alert_type: str,
                   severity: str, metric: str, baseline_value, current_value,
                   change_percent, message: str, recommended_action: str,
                   status: str = "new") -> int:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """INSERT INTO model_monitoring_alerts
                   (sku, model_name, alert_date, alert_type, severity, metric,
                    baseline_value, current_value, change_percent,
                    message, recommended_action, status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id""",
                (sku, model_name, alert_date, alert_type, severity, metric,
                 baseline_value, current_value, change_percent,
                 message, recommended_action, status),
            )
            return cur.fetchone()["id"]

    @staticmethod
    def get_alerts(*, sku: str | None = None, model_name: str | None = None,
                   status: str | None = None, alert_type: str | None = None,
                   limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        where, params = [], []
        if sku:
            where.append("sku = %s"); params.append(sku)
        if model_name:
            where.append("model_name = %s"); params.append(model_name)
        if status:
            where.append("status = %s"); params.append(status)
        if alert_type:
            where.append("alert_type = %s"); params.append(alert_type)
        w = ("WHERE " + " AND ".join(where)) if where else ""
        with get_cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM model_monitoring_alerts {w}", params)
            total = cur.fetchone()["count"]
            cur.execute(
                f"""SELECT * FROM model_monitoring_alerts {w}
                    ORDER BY created_at DESC LIMIT %s OFFSET %s""",
                params + [limit, offset],
            )
            return list(cur.fetchall()), total

    @staticmethod
    def unresolved_alerts(sku: str, model_name: str, alert_type: str) -> list[dict]:
        with get_cursor() as cur:
            cur.execute(
                """SELECT * FROM model_monitoring_alerts
                   WHERE sku = %s AND model_name = %s AND alert_type = %s
                     AND status IN ('new', 'acknowledged')""",
                (sku, model_name, alert_type),
            )
            return list(cur.fetchall())

    @staticmethod
    def update_alert_status(alert_id: int, status: str) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE model_monitoring_alerts SET status = %s WHERE id = %s",
                (status, alert_id),
            )

    @staticmethod
    def alert_counts_by_severity() -> dict:
        with get_cursor() as cur:
            cur.execute(
                """SELECT severity, COUNT(*) AS cnt
                   FROM model_monitoring_alerts
                   WHERE status IN ('new', 'acknowledged')
                   GROUP BY severity"""
            )
            return {r["severity"]: r["cnt"] for r in cur.fetchall()}

    @staticmethod
    def alert_counts_by_status() -> dict:
        with get_cursor() as cur:
            cur.execute(
                """SELECT status, COUNT(*) AS cnt
                   FROM model_monitoring_alerts
                   GROUP BY status"""
            )
            return {r["status"]: r["cnt"] for r in cur.fetchall()}

    @staticmethod
    def total_alerts() -> int:
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM model_monitoring_alerts")
            return cur.fetchone()["count"]

    @staticmethod
    def distinct_models() -> list[str]:
        with get_cursor() as cur:
            cur.execute(
                """SELECT DISTINCT model_name FROM forecast_monitoring_metrics
                   ORDER BY model_name"""
            )
            return [r["model_name"] for r in cur.fetchall()]

    @staticmethod
    def total_evaluated() -> int:
        with get_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM forecast_predictions WHERE status = 'evaluated'"
            )
            return cur.fetchone()["count"]
