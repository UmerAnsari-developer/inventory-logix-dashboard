"""ML package: forecasting and anomaly detection models.

All imports are lazy — heavy libraries (prophet, xgboost, sklearn) are
only loaded when their functions are actually called, not at package import.
"""
from .forecasting import (
    forecast_with_prophet,
    forecast_with_xgboost,
    forecast_ensemble,
)

__all__ = [
    "forecast_with_prophet",
    "forecast_with_xgboost",
    "forecast_ensemble",
]