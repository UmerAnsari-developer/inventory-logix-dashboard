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


def generate_etl_failure_alert(*, error_message: str, stage: str | None = None,
                                duration_seconds: float | None = None) -> dict:
    """Create an ETL failure alert dict with critical severity."""
    stage_info = f" (stage: {stage})" if stage else ""
    duration_info = f" (duration: {duration_seconds:.1f}s)" if duration_seconds else ""
    message = f"ETL pipeline failed{stage_info}{duration_info}: {error_message}"
    action = (
        "ETL pipeline has failed. Check the monitoring dashboard for details. "
        "Review the error logs and consider re-running the ETL pipeline manually if needed."
    )
    return {
        "sku": "SYSTEM",
        "model_name": "ETL_PIPELINE",
        "alert_date": __import__("datetime").date.today().isoformat(),
        "alert_type": "etl_failure",
        "severity": "critical",
        "metric": "etl_status",
        "baseline_value": None,
        "current_value": None,
        "change_percent": 0.0,
        "message": message,
        "recommended_action": action,
        "status": "new",
    }


def generate_backup_failure_alert(*, error_message: str, backup_name: str | None = None) -> dict:
    """Create a backup failure alert dict with critical severity."""
    name_info = f" '{backup_name}'" if backup_name else ""
    message = f"Database backup{name_info} failed: {error_message}"
    action = (
        "Database backup has failed. Verify pg_dump availability and database "
        "connectivity, then create a backup manually. Data is at risk until a "
        "verified backup exists."
    )
    return {
        "sku": "SYSTEM",
        "model_name": "BACKUP_SERVICE",
        "alert_date": __import__("datetime").date.today().isoformat(),
        "alert_type": "backup_failure",
        "severity": "critical",
        "metric": "backup_status",
        "baseline_value": None,
        "current_value": None,
        "change_percent": 0.0,
        "message": message,
        "recommended_action": action,
        "status": "new",
    }


def generate_pool_exhaustion_alert(*, active: int, pool_size: int) -> dict:
    """Create a DB connection-pool exhaustion alert with critical severity."""
    message = (
        f"Database connection pool exhausted ({active}/{pool_size} connections "
        f"in use). Requests will fail with PoolError until connections free up."
    )
    action = (
        "Connection pool is exhausted. Check for connection leaks (long checkouts), "
        "slow queries holding connections, or increase DB_POOL_SIZE. "
        "See /monitoring/pool-status for live utilization."
    )
    return {
        "sku": "SYSTEM",
        "model_name": "DB_POOL",
        "alert_date": __import__("datetime").date.today().isoformat(),
        "alert_type": "pool_exhaustion",
        "severity": "critical",
        "metric": "pool_usage",
        "baseline_value": float(pool_size),
        "current_value": float(active),
        "change_percent": 0.0,
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
