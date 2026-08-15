"""Forecast service — bridges the ML module with the rest of the app."""
from __future__ import annotations

import json
import logging

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
        return result

    @staticmethod
    def recent_for_product(product_id: int, limit: int = 5):
        return ForecastRepository.recent(product_id, limit=limit)

    @staticmethod
    def portfolio(horizon: int = 30, model: str = "prophet") -> list[dict]:
        """Lightweight forecast summary for the dashboard."""
        from ..database import get_cursor
        out = []
        with get_cursor() as cur:
            cur.execute(
                "SELECT id, sku, name FROM products ORDER BY id LIMIT 12"
            )
            products = list(cur.fetchall())
        for p in products:
            try:
                result = ForecastService.run(p["id"], model=model, horizon=horizon)
                preds = result.get("predictions", [])
                baseline = result.get("baseline", 1) or 1
                predicted = sum(preds) if preds else 0
                delta_pct = round(((predicted / max(horizon, 1)) / baseline - 1) * 100, 1)
                out.append({
                    "id": p["id"],
                    "sku": p["sku"],
                    "name": p["name"],
                    "predicted_units": int(predicted),
                    "baseline": round(baseline, 1),
                    "delta_pct": delta_pct,
                    "accuracy": result.get("accuracy", 0),
                })
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.warning("Forecast failed for %s: %s", p["sku"], exc)
        return out
