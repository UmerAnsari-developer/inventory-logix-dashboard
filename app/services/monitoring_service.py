"""Forecast model monitoring service."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from ..monitoring.metrics import evaluate_all
from ..monitoring.degradation import detect_degradation, model_health_status, sustained_degradation
from ..monitoring.alerts import generate_alert, deduplicate_alerts
from ..repositories.monitoring_repo import MonitoringRepository

LOGGER = logging.getLogger(__name__)


class MonitoringService:

    # ── Store predictions ────────────────────────────────────────

    @staticmethod
    def record_prediction(*, sku: str, model_name: str, forecast_date,
                          predicted_value: float, forecast_horizon: int = 1) -> int:
        return MonitoringRepository.save_prediction(
            sku=sku, model_name=model_name, forecast_date=forecast_date,
            predicted_value=predicted_value, forecast_horizon=forecast_horizon,
        )

    @staticmethod
    def attach_actual(prediction_id: int, actual_value: float) -> None:
        MonitoringRepository.update_actual(prediction_id, actual_value)

    # ── Evaluate pending forecasts ───────────────────────────────

    @staticmethod
    def evaluate_pending() -> int:
        """Evaluate all pending predictions that now have actual values."""
        pending = MonitoringRepository.find_pending_evaluations()
        count = 0
        for row in pending:
            pred_id = row["id"]
            predicted = float(row["predicted_value"])
            actual = float(row["actual_value"])
            MonitoringRepository.update_actual(pred_id, actual)
            count += 1
        return count

    # ── Compute and store monitoring metrics ─────────────────────

    @staticmethod
    def compute_metrics(sku: str, model_name: str, *,
                        period: str = "daily", window_days: int = 7) -> dict | None:
        """Compute monitoring metrics for a SKU+Model over a window."""
        today = date.today()
        date_from = today - timedelta(days=window_days)
        avp = MonitoringRepository.actual_vs_predicted(
            sku=sku, model_name=model_name,
            date_from=date_from, date_to=today, limit=1000,
        )
        if not avp:
            return None
        actuals = [float(r["actual_value"]) for r in avp]
        predicted = [float(r["predicted_value"]) for r in avp]
        metrics = evaluate_all(actuals, predicted)

        baseline = MonitoringRepository.baseline_metrics(sku, model_name)
        baseline_mae = float(baseline["mae"]) if baseline and baseline.get("mae") else None
        baseline_mape = float(baseline["mape"]) if baseline and baseline.get("mape") else None

        deg = detect_degradation(metrics["mae"], baseline_mae)
        deg_mape = detect_degradation(metrics["mape"], baseline_mape)
        status = model_health_status(
            metrics["mae"], metrics["mape"], baseline_mae, baseline_mape,
        )

        mae_change = deg["change_percent"]
        mape_change = deg_mape["change_percent"]

        metric_id = MonitoringRepository.save_metrics(
            sku=sku, model_name=model_name, monitoring_date=today,
            aggregation_period=period, **metrics,
            baseline_mae=baseline_mae, baseline_mape=baseline_mape,
            mae_change_percent=mae_change, mape_change_percent=mape_change,
            model_status=status,
        )

        # Check for sustained degradation and generate alerts
        recent = MonitoringRepository.recent_statuses(sku, model_name)
        if sustained_degradation(recent):
            _maybe_create_alert(sku, model_name, today, "mae", baseline_mae, metrics["mae"], mae_change)
            _maybe_create_alert(sku, model_name, today, "mape", baseline_mape, metrics["mape"], mape_change)

        return {**metrics, "model_status": status, "metric_id": metric_id}

    # ── Dashboard data ───────────────────────────────────────────

    @staticmethod
    def summary() -> dict:
        models = MonitoringRepository.distinct_models()
        total_evaluated = MonitoringRepository.total_evaluated()
        model_summary = MonitoringRepository.model_summary()
        healthy = sum(1 for m in model_summary if m.get("model_status") == "healthy")
        degraded = sum(1 for m in model_summary if m.get("model_status") in ("degraded", "critical"))
        mae_vals = [float(m["mae"]) for m in model_summary if m.get("mae") is not None]
        mape_vals = [float(m["mape"]) for m in model_summary if m.get("mape") is not None]
        alert_sev = MonitoringRepository.alert_counts_by_severity()
        return {
            "models_monitored": len(models),
            "forecasts_evaluated": total_evaluated,
            "current_mae": round(sum(mae_vals) / len(mae_vals), 2) if mae_vals else 0,
            "current_mape": round(sum(mape_vals) / len(mape_vals), 2) if mape_vals else 0,
            "healthy_models": healthy,
            "degraded_models": degraded,
            "alerts_by_severity": alert_sev,
        }

    @staticmethod
    def health_table() -> list[dict]:
        return MonitoringRepository.model_summary()

    @staticmethod
    def actual_vs_predicted_data(sku=None, model_name=None,
                                  date_from=None, date_to=None) -> list[dict]:
        return MonitoringRepository.actual_vs_predicted(
            sku=sku, model_name=model_name,
            date_from=date_from, date_to=date_to, limit=500,
        )

    @staticmethod
    def metrics_trend(sku=None, model_name=None, limit: int = 60) -> list[dict]:
        return MonitoringRepository.get_metrics(
            sku=sku, model_name=model_name, limit=limit,
        )

    @staticmethod
    def alerts_list(sku=None, model_name=None, status=None,
                    alert_type=None, limit=100, offset=0) -> tuple[list[dict], int]:
        return MonitoringRepository.get_alerts(
            sku=sku, model_name=model_name, status=status,
            alert_type=alert_type, limit=limit, offset=offset,
        )

    @staticmethod
    def update_alert(alert_id: int, status: str) -> None:
        MonitoringRepository.update_alert_status(alert_id, status)

    @staticmethod
    def predictions_list(sku=None, model_name=None,
                          date_from=None, date_to=None,
                          limit=200, offset=0) -> tuple[list[dict], int]:
        return MonitoringRepository.get_predictions(
            sku=sku, model_name=model_name,
            date_from=date_from, date_to=date_to,
            limit=limit, offset=offset,
        )


def _maybe_create_alert(sku, model_name, today, metric_name,
                         baseline, current, change_pct):
    if baseline is None or current is None:
        return
    existing = MonitoringRepository.unresolved_alerts(sku, model_name, f"{metric_name}_degradation")
    new_alert = generate_alert(
        sku=sku, model_name=model_name, alert_date=str(today),
        alert_type=f"{metric_name}_degradation", metric=metric_name,
        baseline_value=baseline, current_value=current,
        change_percent=change_pct,
    )
    if deduplicate_alerts(existing, new_alert):
        MonitoringRepository.save_alert(**new_alert)
