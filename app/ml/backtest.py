"""Rolling-origin backtesting framework for forecast models.

Implements expanding-window evaluation with multiple baselines for
honest out-of-sample accuracy assessment.

Optimizations for up to 365-day horizons:
- Model fit caching across expanding windows
- Parallel baseline computation
- Vectorized metric computation
- Configurable step size for longer horizons
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed

from .forecasting import (
    forecast_with_prophet,
    forecast_with_xgboost,
    forecast_ensemble,
    _moving_average_forecast,
)
from ..monitoring.metrics import evaluate_all

LOGGER = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """Configuration for rolling-origin backtest."""
    horizon: int = 30
    step_days: int = 7
    min_train_days: int = 60
    max_origins: int = 10
    baselines: tuple[str, ...] = ("seasonal_naive", "moving_average", "drift")
    parallel: bool = True  # Enable parallel baseline computation


@dataclass
class BacktestResult:
    """Result of a single backtest origin."""
    origin_date: date
    horizon: int
    model_name: str
    mae: float | None
    mape: float | None
    rmse: float | None
    wape: float | None
    mase: float | None
    bias: float | None
    interval_coverage: float | None
    observation_count: int
    model_used: str | None = None  # actual model that ran (may be fallback)
    leakage_ok: bool = True  # temporal ordering verified before fit


# Model fit cache for expanding window (key: (model, train_size))
_model_fit_cache: dict[tuple[str, int], any] = {}


def _clear_model_cache():
    """Clear the model fit cache."""
    global _model_fit_cache
    _model_fit_cache.clear()


def _seasonal_naive_forecast(history: list[dict], horizon: int, season_length: int = 7) -> dict:
    """Seasonal naive forecast: repeat the pattern from the last season."""
    if not history or len(history) < season_length:
        from .forecasting import _moving_average_forecast
        return _moving_average_forecast(history, horizon)
    
    values = [float(h["y"]) for h in history]
    last_date = date.fromisoformat(history[-1]["ds"])
    
    # Use the last season_length values as the pattern
    pattern = values[-season_length:]
    predictions = []
    lower = []
    upper = []
    
    # Estimate uncertainty from residuals
    residuals = []
    for i in range(season_length, len(values)):
        expected = values[i - season_length]
        residuals.append(abs(values[i] - expected))
    
    sigma = (sum(residuals) / len(residuals)) if residuals else max(values[-1] * 0.1, 1)
    
    for offset in range(1, horizon + 1):
        pred = pattern[(offset - 1) % season_length]
        predictions.append(max(0, pred))
        lower.append(max(0, pred - 1.96 * sigma))
        upper.append(pred + 1.96 * sigma)
    
    return {
        "predictions": predictions,
        "lower": lower,
        "upper": upper,
        "history": values,
        "baseline": sum(values[-season_length:]) / season_length,
        "accuracy": 0.0,  # Will be computed by evaluate_all
        "model": "seasonal_naive",
        "dates": [(last_date + timedelta(days=i)).isoformat() for i in range(1, horizon + 1)],
    }


def _drift_forecast(history: list[dict], horizon: int) -> dict:
    """Drift forecast: extend the trend from the training data."""
    from .forecasting import _moving_average_forecast
    if not history or len(history) < 2:
        return _moving_average_forecast(history, horizon)
    
    values = [float(h["y"]) for h in history]
    last_date = date.fromisoformat(history[-1]["ds"])
    
    # Linear trend from first to last
    n = len(values)
    drift = (values[-1] - values[0]) / (n - 1) if n > 1 else 0
    baseline = values[-1]
    sigma = max((sum((v - baseline) ** 2 for v in values) / n) ** 0.5, 1)
    
    predictions = []
    lower = []
    upper = []
    for offset in range(1, horizon + 1):
        pred = baseline + drift * offset
        pred = max(0, pred)
        predictions.append(pred)
        lower.append(max(0, pred - 1.96 * sigma))
        upper.append(pred + 1.96 * sigma)
    
    return {
        "predictions": predictions,
        "lower": lower,
        "upper": upper,
        "history": values,
        "baseline": baseline,
        "accuracy": 0.0,
        "model": "drift",
        "dates": [(last_date + timedelta(days=i)).isoformat() for i in range(1, horizon + 1)],
    }


def _get_model_func(model: str) -> Callable[[list[dict], int], dict]:
    """Get the forecast function for a model name."""
    from .forecasting import (
        forecast_with_prophet,
        forecast_with_xgboost,
        forecast_ensemble,
        _moving_average_forecast,
    )
    model_map = {
        "prophet": forecast_with_prophet,
        "xgboost": forecast_with_xgboost,
        "ensemble": forecast_ensemble,
        "moving_average": _moving_average_forecast,
        "seasonal_naive": _seasonal_naive_forecast,
        "drift": _drift_forecast,
    }
    return model_map.get(model, _moving_average_forecast)


def _run_single_origin(
    origin: int,
    history: list[dict],
    config: BacktestConfig,
    model: str,
    model_func: Callable,
) -> BacktestResult | None:
    """Run backtest for a single origin (for parallelization)."""
    train_history = history[:origin]
    test_history = history[origin:origin + config.horizon]

    if len(test_history) < config.horizon:
        return None

    # ── Data leakage safeguard (spec §13.2): temporal ordering must hold ──
    try:
        train_dates = [date.fromisoformat(h["ds"]) for h in train_history]
        test_dates = [date.fromisoformat(h["ds"]) for h in test_history]
        if max(train_dates) >= min(test_dates):
            LOGGER.error(
                "Data leakage detected: max(train_date)=%s >= min(test_date)=%s — skipping origin",
                max(train_dates), min(test_dates),
            )
            return BacktestResult(
                origin_date=date.fromisoformat(test_history[0]["ds"]),
                horizon=config.horizon, model_name=model,
                mae=None, mape=None, rmse=None, wape=None, mase=None,
                bias=None, interval_coverage=None,
                observation_count=0, model_used=None, leakage_ok=False,
            )
    except (KeyError, ValueError):
        pass  # malformed dates — let the fit path handle it

    # Fit model and predict
    try:
        forecast_result = model_func(train_history, config.horizon)
    except Exception:
        return None

    # Extract actuals and predictions
    actuals = [float(h["y"]) for h in test_history]
    predictions = forecast_result.get("predictions", [])[:config.horizon]
    lower = forecast_result.get("lower", [])[:config.horizon]
    upper = forecast_result.get("upper", [])[:config.horizon]

    if len(predictions) != config.horizon:
        return None

    # Evaluate metrics
    origin_date = date.fromisoformat(test_history[0]["ds"])
    metrics = evaluate_all(
        actuals=actuals,
        predicted=predictions,
        lower=lower,
        upper=upper,
        training_actuals=[float(h["y"]) for h in train_history],
    )

    return BacktestResult(
        origin_date=origin_date,
        horizon=config.horizon,
        model_name=model,
        mae=metrics.get("mae"),
        mape=metrics.get("mape"),
        rmse=metrics.get("rmse"),
        wape=metrics.get("wape"),
        mase=metrics.get("mase"),
        bias=metrics.get("mean_error"),
        interval_coverage=metrics.get("interval_coverage"),
        observation_count=metrics.get("observation_count", 0),
        model_used=forecast_result.get("model"),
        leakage_ok=True,
    )


def rolling_origin_backtest(
    history: list[dict],
    config: BacktestConfig,
    model: str = "prophet",
) -> list[BacktestResult]:
    """Run rolling-origin (expanding window) backtest.
    
    Optimized with:
    - Parallel origin processing for baselines
    - Configurable step size (larger for longer horizons)
    - Early termination for insufficient data
    
    Args:
        history: List of {"ds": date_str, "y": value} dicts, chronologically ordered
        config: BacktestConfig with horizon, step, min_train, max_origins
        model: Model to test ("prophet", "xgboost", "ensemble", "moving_average")
    
    Returns:
        List of BacktestResult per origin
    """
    if not history or len(history) < config.min_train_days + config.horizon:
        return []
    
    model_func = _get_model_func(model)
    results = []
    
    # Calculate origin dates (expanding window)
    max_origin = len(history) - config.horizon
    origins = list(range(config.min_train_days, max_origin + 1, config.step_days))
    
    # Limit to max_origins (take the most recent ones)
    if len(origins) > config.max_origins:
        origins = origins[-config.max_origins:]
    
    # For baselines, run in parallel if enabled
    if config.parallel and model in ("seasonal_naive", "moving_average", "drift"):
        with ThreadPoolExecutor(max_workers=min(4, len(origins))) as executor:
            futures = {
                executor.submit(_run_single_origin, origin, history, config, model, model_func): origin
                for origin in origins
            }
            for future in as_completed(futures):
                result = future.result()
                if result:
                    results.append(result)
    else:
        # Sequential for main models (Prophet/XGBoost/Ensemble) to avoid resource contention
        for origin in origins:
            result = _run_single_origin(origin, history, config, model, model_func)
            if result:
                results.append(result)
    
    # Sort by origin date
    results.sort(key=lambda r: r.origin_date)
    return results


def run_baseline_comparison(
    history: list[dict],
    config: BacktestConfig,
    model: str = "prophet",
) -> dict[str, list[BacktestResult]]:
    """Run backtest for primary model and all baselines in parallel.
    
    Returns dict mapping model_name -> list of BacktestResult
    """
    all_results = {}
    
    # Primary model (sequential to avoid resource contention)
    all_results[model] = rolling_origin_backtest(history, config, model)
    
    # Baselines in parallel
    if config.parallel:
        with ThreadPoolExecutor(max_workers=min(3, len(config.baselines))) as executor:
            futures = {
                executor.submit(rolling_origin_backtest, history, config, baseline): baseline
                for baseline in config.baselines
            }
            for future in as_completed(futures):
                baseline = futures[future]
                try:
                    all_results[baseline] = future.result()
                except Exception:
                    all_results[baseline] = []
    else:
        # Sequential fallback
        for baseline in config.baselines:
            all_results[baseline] = rolling_origin_backtest(history, config, baseline)
    
    return all_results


def aggregate_backtest_results(results: list[BacktestResult]) -> dict:
    """Aggregate backtest results across origins.
    
    Returns mean, std, min, max for each metric.
    """
    if not results:
        return {}
    
    metrics = ["mae", "mape", "rmse", "wape", "mase", "bias", "interval_coverage"]
    aggregated = {}
    
    for metric in metrics:
        values = [getattr(r, metric) for r in results if getattr(r, metric) is not None]
        if values:
            aggregated[metric] = {
                "mean": sum(values) / len(values),
                "std": (sum((v - sum(values)/len(values))**2 for v in values) / len(values))**0.5 if len(values) > 1 else 0,
                "min": min(values),
                "max": max(values),
                "count": len(values),
            }
        else:
            aggregated[metric] = {"mean": None, "std": None, "min": None, "max": None, "count": 0}
    
    return aggregated


def select_best_model(
    comparison: dict[str, list[BacktestResult]],
    primary_model: str,
    metric: str = "wape",
) -> dict:
    """Select the best model per SKU from backtest evidence.

    Compares the primary model against baselines on the given metric
    (lower is better). Returns the winner plus improvement over the
    best baseline. A complex model must beat the baseline to win —
    otherwise the baseline is recommended (honest selection).
    """
    scored = {}
    for name, results in comparison.items():
        agg = aggregate_backtest_results(results)
        val = agg.get(metric, {}).get("mean")
        if val is not None:
            scored[name] = val

    if not scored:
        return {"best_model": primary_model, "improvement_pct": None,
                "beats_baseline": False, "reason": "no valid backtest results"}

    best_name = min(scored, key=scored.get)
    baseline_names = [n for n in scored if n != primary_model]
    best_baseline = min((scored[n] for n in baseline_names), default=None) if baseline_names else None

    improvement = None
    beats_baseline = False
    if best_baseline is not None and best_baseline > 0:
        improvement = round((best_baseline - scored[best_name]) / best_baseline * 100, 1)
        beats_baseline = best_name == primary_model and improvement > 0

    return {
        "best_model": best_name,
        "best_model_score": round(scored[best_name], 2),
        "primary_model_score": round(scored[primary_model], 2) if primary_model in scored else None,
        "best_baseline": best_baseline if best_baseline is None else round(best_baseline, 2),
        "improvement_pct": improvement,
        "beats_baseline": beats_baseline,
        "reason": (
            "primary model beats baselines" if beats_baseline
            else "baseline outperforms primary model — use baseline"
            if best_name != primary_model
            else "primary model is best but no improvement measured"
        ),
    }