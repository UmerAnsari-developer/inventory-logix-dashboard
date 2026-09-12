"""Model performance degradation detection."""
from __future__ import annotations

from ..config.settings import Config


def _threshold(name: str) -> float:
    return float(getattr(Config, name, 10))


def detect_degradation(current_mae: float | None, baseline_mae: float | None) -> dict:
    """Compare current MAE against baseline. Returns status + change %."""
    if current_mae is None or baseline_mae is None or baseline_mae == 0:
        return {"change_percent": 0.0, "status": "healthy"}
    change_pct = ((current_mae - baseline_mae) / baseline_mae) * 100
    warning = _threshold("MODEL_WARNING_THRESHOLD")
    degraded = _threshold("MODEL_DEGRADATION_THRESHOLD")
    critical = _threshold("MODEL_CRITICAL_THRESHOLD")
    if change_pct >= critical:
        status = "critical"
    elif change_pct >= degraded:
        status = "degraded"
    elif change_pct >= warning:
        status = "warning"
    else:
        status = "healthy"
    return {"change_percent": round(change_pct, 2), "status": status}


def model_health_status(mae: float | None, mape: float | None,
                        baseline_mae: float | None, baseline_mape: float | None) -> str:
    """Determine overall model health from both MAE and MAPE."""
    s_mae = detect_degradation(mae, baseline_mae)
    s_mape = detect_degradation(mape, baseline_mape)
    order = {"healthy": 0, "warning": 1, "degraded": 2, "critical": 3}
    worst = max(s_mae["status"], s_mape["status"], key=lambda s: order.get(s, 0))
    return worst


def sustained_degradation(recent_statuses: list[str], window: int = 7) -> bool:
    """True if degradation persists for `window` consecutive observations."""
    if len(recent_statuses) < window:
        return False
    return all(s in ("degraded", "critical") for s in recent_statuses[-window:])
