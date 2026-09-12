"""Forecast error and monitoring metric calculations."""
from __future__ import annotations

import math
from typing import Sequence


def forecast_error(actual: float, predicted: float) -> float:
    """Error = Actual - Predicted. Positive means model underestimated."""
    return float(actual) - float(predicted)


def absolute_error(actual: float, predicted: float) -> float:
    return abs(forecast_error(actual, predicted))


def percentage_error(actual: float, predicted: float) -> float:
    """(Actual - Predicted) / |Actual| * 100. Returns 0 when actual is 0."""
    a = float(actual)
    if a == 0:
        return 0.0
    return (float(a) - float(predicted)) / abs(a) * 100


def absolute_percentage_error(actual: float, predicted: float) -> float:
    """|Actual - Predicted| / |Actual| * 100. Undefined when actual=0."""
    a = float(actual)
    if a == 0:
        return 0.0
    return abs(float(a) - float(predicted)) / abs(a) * 100


def calculate_mae(errors: Sequence[float]) -> float | None:
    """Mean Absolute Error. Returns None for empty sequences."""
    if not errors:
        return None
    return sum(abs(e) for e in errors) / len(errors)


def calculate_mape(actuals: Sequence[float], predicted: Sequence[float]) -> tuple[float | None, int, int]:
    """Mean Absolute Percentage Error.

    Returns (mape_or_None, valid_count, zero_demand_count).
    Observations where actual=0 are excluded from MAPE but counted.
    """
    if len(actuals) != len(predicted):
        raise ValueError("actuals and predicted must have same length")
    valid = 0
    zero_count = 0
    total_ape = 0.0
    for a, p in zip(actuals, predicted):
        if float(a) == 0:
            zero_count += 1
            continue
        total_ape += abs(float(a) - float(p)) / abs(float(a))
        valid += 1
    if valid == 0:
        return None, valid, zero_count
    return (total_ape / valid) * 100, valid, zero_count


def calculate_rmse(errors: Sequence[float]) -> float | None:
    """Root Mean Squared Error."""
    if not errors:
        return None
    return math.sqrt(sum(e * e for e in errors) / len(errors))


def calculate_bias(errors: Sequence[float]) -> float | None:
    """Mean Error (bias). Positive = systematic underprediction."""
    if not errors:
        return None
    return sum(errors) / len(errors)


def calculate_error_std(errors: Sequence[float]) -> float | None:
    """Standard deviation of errors."""
    if len(errors) < 2:
        return None
    mean = sum(errors) / len(errors)
    return math.sqrt(sum((e - mean) ** 2 for e in errors) / (len(errors) - 1))


def evaluate_all(actuals: Sequence[float], predicted: Sequence[float]) -> dict:
    """Compute all monitoring metrics at once."""
    if len(actuals) != len(predicted):
        raise ValueError("actuals and predicted must have same length")
    errors = [float(a) - float(p) for a, p in zip(actuals, predicted)]
    mape, valid_count, zero_count = calculate_mape(actuals, predicted)
    return {
        "observation_count": len(errors),
        "mae": calculate_mae(errors),
        "mape": mape,
        "rmse": calculate_rmse(errors),
        "mean_error": calculate_bias(errors),
        "error_std": calculate_error_std(errors),
        "zero_demand_count": zero_count,
        "mape_valid_count": valid_count,
    }
