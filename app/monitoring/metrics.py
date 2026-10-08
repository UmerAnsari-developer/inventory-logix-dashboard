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


def calculate_wape(actuals: Sequence[float], predicted: Sequence[float]) -> float | None:
    """Weighted Absolute Percentage Error (WAPE).
    
    WAPE = sum(|actual - predicted|) / sum(|actual|) * 100.
    Better for intermittent demand than MAPE as it weights by volume.
    Returns None if all actuals are zero.
    """
    if len(actuals) != len(predicted):
        raise ValueError("actuals and predicted must have same length")
    sum_abs_error = sum(abs(float(a) - float(p)) for a, p in zip(actuals, predicted))
    sum_abs_actual = sum(abs(float(a)) for a in actuals)
    if sum_abs_actual == 0:
        return None
    return (sum_abs_error / sum_abs_actual) * 100


def calculate_mase(actuals: Sequence[float], predicted: Sequence[float], 
                   training_actuals: Sequence[float] | None = None) -> float | None:
    """Mean Absolute Scaled Error (MASE).
    
    MASE = MAE / MAE_naive, where MAE_naive is the in-sample MAE of 
    a seasonal naive forecast (or simple naive if no seasonality).
    MASE < 1 means better than naive; MASE > 1 means worse.
    
    If training_actuals not provided, uses actuals as training (less accurate).
    """
    if len(actuals) != len(predicted):
        raise ValueError("actuals and predicted must have same length")
    if not actuals:
        return None
    
    # Compute MAE of the model
    errors = [abs(float(a) - float(p)) for a, p in zip(actuals, predicted)]
    mae = sum(errors) / len(errors)
    
    # Compute naive forecast MAE on training data
    train = training_actuals if training_actuals is not None else actuals
    if len(train) < 2:
        return None
    
    # Seasonal naive: forecast = value from same season last cycle
    # For daily data with weekly seasonality, season_length = 7
    season_length = 7
    if len(train) <= season_length:
        # Fall back to simple naive (previous value)
        naive_errors = [abs(float(train[i]) - float(train[i-1])) for i in range(1, len(train))]
    else:
        naive_errors = [abs(float(train[i]) - float(train[i-season_length])) 
                       for i in range(season_length, len(train))]
    
    if not naive_errors:
        return None
    
    mae_naive = sum(naive_errors) / len(naive_errors)
    if mae_naive == 0:
        return None
    
    return mae / mae_naive


def calculate_interval_coverage(actuals: Sequence[float], lower: Sequence[float], 
                                 upper: Sequence[float]) -> float | None:
    """Prediction Interval Coverage Probability (PICP).
    
    Percentage of actual values that fall within the prediction interval.
    For a 95% confidence interval, expected coverage is ~95%.
    """
    if len(actuals) != len(lower) or len(actuals) != len(upper):
        raise ValueError("actuals, lower, and upper must have same length")
    if not actuals:
        return None
    
    covered = sum(1 for a, l, u in zip(actuals, lower, upper) if l <= float(a) <= u)
    return (covered / len(actuals)) * 100


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


def evaluate_all(actuals: Sequence[float], predicted: Sequence[float],
                 lower: Sequence[float] | None = None,
                 upper: Sequence[float] | None = None,
                 training_actuals: Sequence[float] | None = None) -> dict:
    """Compute all monitoring metrics at once.
    
    Args:
        actuals: Actual observed values
        predicted: Predicted values
        lower: Lower prediction interval bounds (optional)
        upper: Upper prediction interval bounds (optional)
        training_actuals: Training data for MASE calculation (optional)
    """
    if len(actuals) != len(predicted):
        raise ValueError("actuals and predicted must have same length")
    errors = [float(a) - float(p) for a, p in zip(actuals, predicted)]
    mape, valid_count, zero_count = calculate_mape(actuals, predicted)
    
    result = {
        "observation_count": len(errors),
        "mae": calculate_mae(errors),
        "mape": mape,
        "rmse": calculate_rmse(errors),
        "mean_error": calculate_bias(errors),
        "error_std": calculate_error_std(errors),
        "zero_demand_count": zero_count,
        "mape_valid_count": valid_count,
        "wape": calculate_wape(actuals, predicted),
        "mase": calculate_mase(actuals, predicted, training_actuals),
    }
    
    if lower is not None and upper is not None:
        result["interval_coverage"] = calculate_interval_coverage(actuals, lower, upper)
    
    return result
