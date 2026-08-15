"""User settings service — typed access, defaults and validation.

Values are stored per user as plain strings; this module is the single
authoritative place for default values and how they are coerced.
"""
from __future__ import annotations

from flask import g
from flask_login import current_user

from ..database import get_cursor
from ..repositories import SettingsRepository

DEFAULTS: dict[str, str] = {
    # Appearance / behaviour
    "dark_mode": "",
    "live_data": "on",
    "sound_alerts": "off",
    # AI feature flags
    "ai_recommendations": "on",
    "anomaly_detection": "on",
    "auto_reorder": "off",
    "forecast_model": "prophet",
    # Alert thresholds
    "low_stock_threshold": "20",
    "critical_threshold": "10",
    "z_score_threshold": "3",
    # Integrations
    "slack_connected": "off",
    "email_alerts": "on",
}

MODEL_CHOICES = {"prophet", "arima", "ensemble"}
_BOOL_KEYS = {
    "dark_mode",
    "live_data",
    "sound_alerts",
    "ai_recommendations",
    "anomaly_detection",
    "auto_reorder",
    "slack_connected",
    "email_alerts",
}
_INT_KEYS = {"low_stock_threshold", "critical_threshold", "z_score_threshold"}


class SettingsService:
    """Read and write the current user's preferences."""

    @staticmethod
    def get_settings(user_id: int | None = None) -> dict[str, str]:
        """Return merged settings (defaults + stored), cached per request."""
        if user_id is None:
            user_id = (
                getattr(current_user, "id", None)
                if current_user.is_authenticated
                else None
            )
        cached = getattr(g, "user_settings", None)
        if cached is not None:
            return cached
        data = dict(DEFAULTS)
        if user_id:
            try:
                data.update(SettingsRepository.all(user_id))
            except Exception:
                pass
        g.user_settings = data
        return data

    @staticmethod
    def save_settings(values: dict) -> dict[str, str]:
        """Validate and persist a batch of settings for the current user."""
        if not current_user.is_authenticated:
            raise ValueError("Authentication required")
        cleaned: dict[str, str] = {}
        for key, raw in values.items():
            if key not in DEFAULTS:
                continue
            cleaned[key] = SettingsService._validate(key, raw)
        if cleaned:
            SettingsRepository.set_many(current_user.id, cleaned)
            merged = dict(DEFAULTS)
            merged.update(SettingsRepository.all(current_user.id))
            g.user_settings = merged
        else:
            merged = SettingsService.get_settings()
        return merged

    @staticmethod
    def _validate(key: str, raw) -> str:
        value = str(raw).strip()
        if key in _BOOL_KEYS:
            return "on" if value in ("1", "true", "yes", "on", "True") else (
                "off" if value in ("0", "false", "no", "off", "False") else value
            )
        if key == "forecast_model":
            return value if value in MODEL_CHOICES else DEFAULTS["forecast_model"]
        if key == "low_stock_threshold":
            return str(max(1, min(100, _int_or(value, 20))))
        if key == "critical_threshold":
            return str(max(0, min(99, _int_or(value, 10))))
        if key == "z_score_threshold":
            return str(max(1.0, min(10.0, _float_or(value, 3.0))))
        return value

    # Typed getters ----------------------------------------------------------
    @staticmethod
    def is_on(key: str) -> bool:
        return SettingsService.get_settings().get(key) == "on"

    @staticmethod
    def forecast_model() -> str:
        model = SettingsService.get_settings().get("forecast_model", "prophet")
        return model if model in MODEL_CHOICES else "prophet"

    @staticmethod
    def threshold_pcts() -> tuple[float, float]:
        """Return (low_pct, critical_pct) as 0-100 floats, low >= critical."""
        data = SettingsService.get_settings()
        low = _float_or(data.get("low_stock_threshold"), 20.0)
        critical = _float_or(data.get("critical_threshold"), 10.0)
        return max(low, critical), min(critical, low)

    @staticmethod
    def z_score_threshold() -> float:
        data = SettingsService.get_settings()
        return max(1.0, min(10.0, _float_or(data.get("z_score_threshold"), 3.0)))


def _int_or(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_or(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
