"""Repository for system alert storage (model_monitoring_alerts)."""
from __future__ import annotations

from ..database import get_cursor


class MonitoringRepository:

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
