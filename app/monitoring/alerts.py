"""Monitoring alert generation and deduplication."""
from __future__ import annotations

from ..config.settings import Config


def _threshold(name: str) -> float:
    return float(getattr(Config, name, 10))


def generate_alert(*, sku: str, model_name: str, alert_date: str,
                   alert_type: str, metric: str,
                   baseline_value: float | None, current_value: float | None,
                   change_percent: float) -> dict:
    """Create a monitoring alert dict with severity and recommendation."""
    warning = _threshold("MODEL_WARNING_THRESHOLD")
    degraded = _threshold("MODEL_DEGRADATION_THRESHOLD")
    critical = _threshold("MODEL_CRITICAL_THRESHOLD")
    if change_percent >= critical:
        severity = "critical"
    elif change_percent >= degraded:
        severity = "high"
    elif change_percent >= warning:
        severity = "warning"
    else:
        severity = "info"
    message = (
        f"{metric.upper()} changed by {change_percent:+.1f}% "
        f"(baseline: {baseline_value:.1f}, current: {current_value:.1f})"
    )
    action = "Review recent demand patterns and consider retraining the model."
    if severity in ("critical", "high"):
        action = (
            "Model performance has deteriorated significantly. "
            "Review recent demand patterns, retrain or reevaluate the forecasting model."
        )
    return {
        "sku": sku,
        "model_name": model_name,
        "alert_date": alert_date,
        "alert_type": alert_type,
        "severity": severity,
        "metric": metric,
        "baseline_value": baseline_value,
        "current_value": current_value,
        "change_percent": round(change_percent, 2),
        "message": message,
        "recommended_action": action,
        "status": "new",
    }


def deduplicate_alerts(existing: list[dict], new_alert: dict) -> bool:
    """Return True if new_alert should be created (no unresolved duplicate exists).

    If an existing alert with same sku+model+type is unresolved, the caller
    should update it rather than creating a duplicate.
    """
    for a in existing:
        if (a.get("sku") == new_alert["sku"]
                and a.get("model_name") == new_alert["model_name"]
                and a.get("alert_type") == new_alert["alert_type"]
                and a.get("status") in ("new", "acknowledged")):
            return False
    return True
