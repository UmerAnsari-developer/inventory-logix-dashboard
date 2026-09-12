"""Evaluate individual forecasts against actual demand."""
from __future__ import annotations

from .metrics import forecast_error, absolute_error, percentage_error, absolute_percentage_error


def evaluate_forecast(predicted: float, actual: float, *,
                      sku: str = "", model_name: str = "",
                      forecast_date: str = "", forecast_generated_at: str = "",
                      horizon: int = 1) -> dict:
    """Create a structured evaluation record for one forecast."""
    err = forecast_error(actual, predicted)
    abs_err = abs(err)
    pct_err = percentage_error(actual, predicted)
    abs_pct_err = absolute_percentage_error(actual, predicted)
    return {
        "sku": sku,
        "model_name": model_name,
        "forecast_date": forecast_date,
        "forecast_generated_at": forecast_generated_at,
        "predicted_value": float(predicted),
        "actual_value": float(actual),
        "error": err,
        "absolute_error": abs_err,
        "percentage_error": pct_err,
        "absolute_percentage_error": abs_pct_err,
        "horizon": horizon,
    }


def batch_evaluate(records: list[dict]) -> list[dict]:
    """Evaluate a list of {predicted, actual, ...} dicts."""
    results = []
    for r in records:
        results.append(evaluate_forecast(
            predicted=r["predicted"],
            actual=r["actual"],
            sku=r.get("sku", ""),
            model_name=r.get("model_name", ""),
            forecast_date=r.get("forecast_date", ""),
            forecast_generated_at=r.get("forecast_generated_at", ""),
            horizon=r.get("horizon", 1),
        ))
    return results
