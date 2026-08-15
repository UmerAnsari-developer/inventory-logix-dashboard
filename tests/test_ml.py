"""Tests for the EOQ, forecast and anomaly ML helpers."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.ml import anomaly as amod
from app.ml import forecasting as fmod
from app.ml.forecasting import (
    _moving_average_forecast,
    forecast_ensemble,
    forecast_with_arima,
    forecast_with_prophet,
)
from app.ml.anomaly import _stats, detect_anomalies_isoforest, spc_zscore_analysis


def _series(n: int = 120, base: int = 50, spike_at: int = 60):
    today = date.today()
    rows, values = [], []
    for i in range(n):
        v = base + (i % 7) * 2
        if i == spike_at:
            v = base * 5
        values.append(v)
        rows.append({"ds": (today - timedelta(days=n - i)).isoformat(), "y": v})
    return rows, values


def test_prophet_returns_forecast():
    history, _ = _series()
    result = forecast_with_prophet(history, horizon=14)
    assert "predictions" in result
    assert len(result["predictions"]) == 14
    assert result["model"] in {"prophet", "moving_average"}


def test_arima_returns_forecast():
    history, _ = _series()
    result = forecast_with_arima(history, horizon=7)
    assert "predictions" in result
    assert len(result["predictions"]) == 7


def test_ensemble_blends():
    history, _ = _series()
    result = forecast_ensemble(history, horizon=10)
    assert "predictions" in result
    assert len(result["predictions"]) == 10
    assert result["model"] == "ensemble"


def test_isoforest_detects_spike():
    _, values = _series()
    series = [{"day": f"d{i}", "value": v} for i, v in enumerate(values)]
    result = detect_anomalies_isoforest(series)
    assert result["model"] in {"isolation_forest", "zscore"}
    assert result["count"] >= 1


def test_spc_returns_control_limits():
    _, values = _series()
    series = [{"day": f"d{i}", "value": v} for i, v in enumerate(values)]
    result = spc_zscore_analysis(series)
    assert result["mean"] > 0
    assert result["ucl"] > result["mean"]
    assert result["lcl"] <= result["mean"]


# ---------------------------------------------------------------------------
# Deterministic value-level assertions (kill weak mutation survivors)
# ---------------------------------------------------------------------------
def test_moving_average_exact_values():
    history, _ = _series(n=5)
    result = _moving_average_forecast(history, horizon=3)
    assert result["model"] == "moving_average"
    assert len(result["predictions"]) == 3
    assert result["baseline"] == pytest.approx(56.0)
    assert result["predictions"] == pytest.approx([57.0, 58.0, 59.0])
    assert result["lower"][0] == pytest.approx(53.79933340276332)
    assert result["upper"][0] == pytest.approx(60.20066659723668)


def test_moving_average_two_points():
    history, _ = _series(n=2)
    result = _moving_average_forecast(history, horizon=2)
    assert result["baseline"] == pytest.approx(51.0)
    assert result["lower"][0] == pytest.approx(49.54)


def test_moving_average_window_growth():
    history, _ = _series(n=8)
    result = _moving_average_forecast(history, horizon=3)
    assert result["baseline"] == pytest.approx(57.333333333333336)


def test_moving_average_window_cap_ramp():
    today = date.today()
    rows = []
    for i in range(60):
        rows.append({
            "ds": (today - timedelta(days=59 - i)).isoformat(),
            "y": float(i + 1),
        })
    result = _moving_average_forecast(rows, horizon=3)
    assert result["baseline"] == pytest.approx(53.5)


def test_moving_average_long_window_cap():
    history, _ = _series(n=60)
    result = _moving_average_forecast(history, horizon=3)
    assert result["baseline"] == pytest.approx(56.0)


def test_moving_average_single_point():
    history, _ = _series(n=1, base=5)
    result = _moving_average_forecast(history, horizon=2)
    assert result["baseline"] == pytest.approx(5.0)
    assert result["lower"][0] == pytest.approx(3.04)
    assert result["upper"][0] == pytest.approx(6.96)


def test_prophet_boundary_len_fourteen():
    history, _ = _series(n=14, spike_at=7)
    result = forecast_with_prophet(history, horizon=3)
    assert result["model"] == "prophet"
    assert result["accuracy"] == pytest.approx(65.15, abs=0.05)


def test_arima_boundary_len_twenty():
    history, _ = _series(n=20, spike_at=10)
    result = forecast_with_arima(history, horizon=3)
    assert result["model"] == "arima"
    assert result["accuracy"] == pytest.approx(70.09, abs=0.05)


def test_ensemble_exact_values():
    history, _ = _series(n=10)
    result = forecast_ensemble(history, horizon=3)
    assert result["model"] == "ensemble"
    assert result["predictions"][0] == pytest.approx(52.45)
    assert result["lower"][0] == pytest.approx(49.24933340276332)
    assert result["upper"][0] == pytest.approx(55.650666597236686)
    assert result["baseline"] == pytest.approx(52.0)
    assert result["accuracy"] == pytest.approx(78.0)


def test_prophet_flag_matches_environment():
    assert fmod._HAS_PROPHET is True


def test_arima_flag_matches_environment():
    assert fmod._HAS_ARIMA is True


def test_sklearn_flag_matches_environment():
    assert amod._HAS_SKLEARN is True


def _value_series(n, base=50, spike_at=None, mult=5):
    rows, values = [], []
    for i in range(n):
        v = base + (i % 7) * 2
        if i == spike_at:
            v = base * mult
        values.append(v)
        rows.append({"day": f"d{i}", "value": v})
    return rows, values


def test_isoforest_deterministic_output():
    series, _ = _value_series(n=120, spike_at=60)
    result = detect_anomalies_isoforest(series)
    assert result["model"] == "isolation_forest"
    assert result["count"] == 1
    first = result["anomalies"][0]
    assert first["day"] == "d60"
    assert first["value"] == 250.0
    assert first["z_score"] == pytest.approx(10.64)
    assert first["confidence"] == pytest.approx(74.0)
    assert first["type"] == "spike"


def test_isoforest_boundary_len_fourteen():
    series, _ = _value_series(n=14, spike_at=7)
    result = detect_anomalies_isoforest(series)
    assert result["model"] == "isolation_forest"
    assert result["count"] == 1
    first = result["anomalies"][0]
    assert first["value"] == 250.0
    assert first["z_score"] == pytest.approx(3.6)
    assert first["confidence"] == pytest.approx(66.1)


def test_isoforest_skips_when_few_points():
    series, _ = _value_series(n=8, spike_at=4, mult=10)
    result = detect_anomalies_isoforest(series)
    assert result["model"] == "zscore"


def test_zscore_boundary_threshold():
    values = [0, 100, 200, 0, 100, 200, 0, 100, 200, 0]
    series = [{"day": f"d{i}", "value": v} for i, v in enumerate(values)]
    mu, sigma = _stats(values)
    z200 = (200 - mu) / sigma
    result = detect_anomalies_isoforest(series, z_threshold=z200)
    assert result["count"] == 3


def test_zscore_confidence_small_z():
    series = [{"day": f"d{i}", "value": v}
              for i, v in enumerate([10, 30, 10, 30, 10, 30, 10, 30])]
    result = detect_anomalies_isoforest(series, z_threshold=0)
    assert result["anomalies"][0]["confidence"] == pytest.approx(85.0)


def test_zscore_confidence_large_z():
    series = [{"day": f"d{i}", "value": v}
              for i, v in enumerate([0, 0, 0, 0, 0, 0, 0, 400])]
    result = detect_anomalies_isoforest(series, z_threshold=2.5)
    assert result["count"] == 1
    assert result["anomalies"][0]["confidence"] == pytest.approx(95.0)


def test_zscore_type_boundary_zero_z():
    series = [{"day": f"d{i}", "value": v} for i, v in enumerate([5, 10, 15])]
    result = detect_anomalies_isoforest(series, z_threshold=0)
    by_value = {a["value"]: a for a in result["anomalies"]}
    assert by_value[10]["type"] == "drop"
    assert by_value[10]["z_score"] == pytest.approx(0.0)
    assert by_value[5]["z_score"] == pytest.approx(-1.22)
    assert by_value[15]["z_score"] == pytest.approx(1.22)


def test_zscore_sort_and_truncation():
    series = [{"day": f"d{i}", "value": v} for i, v in enumerate([5, 10, 15] * 10)]
    result = detect_anomalies_isoforest(series, z_threshold=0)
    assert result["count"] == 30
    assert len(result["anomalies"]) == 25
    assert abs(result["anomalies"][0]["z_score"]) == pytest.approx(1.22)
    assert result["anomalies"][0]["value"] == 5.0


def test_zscore_sort_uses_abs_magnitude():
    series = [{"day": f"d{i}", "value": v} for i, v in enumerate([2, 20, 4])]
    result = detect_anomalies_isoforest(series, z_threshold=0.4)
    assert result["anomalies"][0]["value"] == 20.0


def test_spc_two_points():
    result = spc_zscore_analysis([{"value": 1}, {"value": 2}])
    assert result["mean"] == pytest.approx(1.5)
    assert result["sigma"] == pytest.approx(0.5)


def test_spc_rounding():
    series = [{"value": 1.111}, {"value": 1.111}, {"value": 1.111}]
    result = spc_zscore_analysis(series)
    assert result["mean"] == pytest.approx(1.11)
    assert result["sigma"] == pytest.approx(0.5)
    assert result["ucl"] == pytest.approx(2.61)
    assert result["lcl"] == pytest.approx(0)


def test_spc_lcl_positive():
    series = [{"value": 10.111}, {"value": 10.111}, {"value": 10.111}]
    result = spc_zscore_analysis(series)
    assert result["mean"] == pytest.approx(10.11)
    assert result["ucl"] == pytest.approx(11.61)
    assert result["lcl"] == pytest.approx(8.61)


def test_spc_sigma_rounding():
    result = spc_zscore_analysis([{"value": 1}, {"value": 2.234}])
    assert result["sigma"] == pytest.approx(0.62)
