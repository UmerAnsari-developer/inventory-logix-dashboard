"""Forecast service — bridges the ML module with the rest of the app."""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from ..ml.forecasting import (
    forecast_with_prophet,
    forecast_with_arima,
    forecast_ensemble,
)
from ..repositories import ForecastRepository
from ..repositories.product_repo import ProductRepository
from ..repositories.movement_repo import MovementRepository

LOGGER = logging.getLogger(__name__)


class ForecastService:
    MODELS = {"prophet": "Prophet (Seasonality)", "arima": "ARIMA (Trend)", "ensemble": "Ensemble (Both)"}

    @classmethod
    def run(cls, product_id: int, *, model: str = "prophet", horizon: int = 90) -> dict:
        product = ProductRepository.find(product_id)
        if not product:
            raise ValueError("Product not found")
        rows = MovementRepository.daily_for_product(product_id, days=180)
        history = [{"ds": r["day"].isoformat(), "y": int(r["total"])} for r in rows]
        if model == "arima":
            result = forecast_with_arima(history, horizon)
        elif model == "ensemble":
            result = forecast_ensemble(history, horizon)
        else:
            result = forecast_with_prophet(history, horizon)
        result["product"] = {
            "id": product["id"],
            "sku": product["sku"],
            "name": product["name"],
        }
        result["model_label"] = cls.MODELS.get(model, "Prophet")
        ForecastRepository.save(product_id, model, horizon, result)
        cls._update_monitoring(product["sku"], model, history)
        return result

    @classmethod
    def _update_monitoring(cls, sku: str, model_name: str, history: list[dict]) -> None:
        """Record predictions for last 30 days and compute monitoring metrics."""
        try:
            from ..repositories.monitoring_repo import MonitoringRepository
            from ..monitoring.metrics import evaluate_all
            from ..monitoring.degradation import detect_degradation, model_health_status

            if len(history) < 10:
                return

            actuals_by_day = {r["ds"]: r["y"] for r in history}
            today = date.today()
            window = min(30, len(history) - 1)

            # Use 7-day moving average as model prediction for each historical day
            values = [r["y"] for r in history]
            for i in range(len(history) - window, len(history)):
                day_str = history[i]["ds"]
                actual = float(actuals_by_day[day_str])
                # Predicted = mean of previous 7 days (or all available)
                start = max(0, i - 7)
                predicted = sum(values[start:i]) / max(1, i - start)
                pred_id = MonitoringRepository.save_prediction(
                    sku=sku, model_name=model_name,
                    forecast_date=day_str, predicted_value=round(predicted, 2),
                    forecast_horizon=1,
                )
                MonitoringRepository.update_actual(pred_id, actual)

            # Compute metrics from evaluated predictions
            today_str = today.isoformat()
            week_ago = (today - timedelta(days=window)).isoformat()
            avp = MonitoringRepository.actual_vs_predicted(
                sku=sku, model_name=model_name,
                date_from=week_ago, date_to=today_str, limit=100,
            )
            if not avp:
                return
            actual_vals = [float(r["actual_value"]) for r in avp]
            pred_vals = [float(r["predicted_value"]) for r in avp]
            metrics = evaluate_all(actual_vals, pred_vals)
            metrics.pop("mape_valid_count", None)

            baseline = MonitoringRepository.baseline_metrics(sku, model_name)
            baseline_mae = float(baseline["mae"]) if baseline and baseline.get("mae") else None
            baseline_mape = float(baseline["mape"]) if baseline and baseline.get("mape") else None

            deg = detect_degradation(metrics["mae"], baseline_mae)
            deg_mape = detect_degradation(metrics["mape"], baseline_mape)
            status = model_health_status(
                metrics["mae"], metrics["mape"], baseline_mae, baseline_mape,
            )

            MonitoringRepository.save_metrics(
                sku=sku, model_name=model_name, monitoring_date=today,
                aggregation_period="daily", **metrics,
                baseline_mae=baseline_mae, baseline_mape=baseline_mape,
                mae_change_percent=deg["change_percent"],
                mape_change_percent=deg_mape["change_percent"],
                model_status=status,
            )
        except Exception:
            LOGGER.debug("Monitoring update skipped", exc_info=True)

    @staticmethod
    def recent_for_product(product_id: int, limit: int = 5):
        return ForecastRepository.recent(product_id, limit=limit)

    @staticmethod
    def portfolio(horizon: int = 30, model: str = "prophet") -> list[dict]:
        """Lightweight forecast summary — uses 7-day moving average, no model fitting."""
        from ..database import get_cursor
        out = []
        with get_cursor() as cur:
            cur.execute(
                "SELECT id, sku, name FROM products ORDER BY id LIMIT 12"
            )
            products = list(cur.fetchall())
        for p in products:
            try:
                rows = MovementRepository.daily_for_product(p["id"], days=90)
                totals = [int(r["total"]) for r in rows]
                if not totals:
                    continue
                baseline = sum(totals) / len(totals)
                window = min(7, len(totals))
                recent_avg = sum(totals[-window:]) / window
                predicted = round(recent_avg * horizon, 1)
                delta_pct = round(((recent_avg / max(baseline, 1)) - 1) * 100, 1)
                residuals = [abs(t - baseline) for t in totals]
                mae = sum(residuals) / len(residuals) if residuals else 0
                accuracy = max(0, round(100 - (mae / max(baseline, 1)) * 100, 1))
                out.append({
                    "id": p["id"],
                    "sku": p["sku"],
                    "name": p["name"],
                    "predicted_units": int(predicted),
                    "baseline": round(baseline, 1),
                    "delta_pct": delta_pct,
                    "accuracy": accuracy,
                })
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.warning("Portfolio forecast failed for %s: %s", p["sku"], exc)
        return out
