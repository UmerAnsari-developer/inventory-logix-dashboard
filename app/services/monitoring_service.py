"""System alert persistence (ETL/backup/pool failures) + retention purges."""
from __future__ import annotations

import logging

from ..monitoring.alerts import (
    deduplicate_alerts,
    generate_etl_failure_alert,
    generate_backup_failure_alert,
)
from ..repositories.monitoring_repo import MonitoringRepository

LOGGER = logging.getLogger(__name__)


def _maybe_create_system_alert(alert: dict) -> None:
    """Persist a system-level alert (etl_failure, backup_failure, ...) with dedup.

    ``alert`` is a dict from generate_*_alert() carrying sku/model_name/
    alert_type plus all save_alert kwargs. Skips when an unresolved alert of
    the same (sku, model_name, alert_type) already exists. After saving, fires
    the optional external alert channels (GAP-009) — best-effort.
    """
    existing = MonitoringRepository.unresolved_alerts(
        alert["sku"], alert["model_name"], alert["alert_type"]
    )
    if deduplicate_alerts(existing, alert):
        MonitoringRepository.save_alert(**alert)
        try:
            from .alert_notifier import notify_alert
            notify_alert(alert)
        except Exception as notify_err:  # noqa: BLE001 — routing must not break alerts
            LOGGER.warning("Alert routing failed: %s", notify_err)


def run_retention() -> dict:
    """Run all retention purge procedures (GAP-011) — audit_log, sessions,
    idempotency keys, rate-limit state. Wired as the ``run_retention`` job
    handler; pg_cron schedules it daily where available."""
    from ..database import get_cursor

    with get_cursor(commit=True) as cur:
        cur.execute("SELECT * FROM sp_retention_run_all()")
        results = [
            {"object": r["object_name"], "purged": r["purged"]}
            for r in cur.fetchall()
        ]
    LOGGER.info("Retention run: %s", results)
    return {"success": True, "results": results}


def _maybe_create_etl_failure_alert(error_message: str, stage: str | None = None,
                                      duration_seconds: float | None = None) -> None:
    """Create an ETL failure alert with critical severity (dedup-aware)."""
    _maybe_create_system_alert(
        generate_etl_failure_alert(
            error_message=error_message,
            stage=stage,
            duration_seconds=duration_seconds,
        )
    )


def _maybe_create_backup_failure_alert(error_message: str,
                                        backup_name: str | None = None) -> None:
    """Create a backup failure alert with critical severity (dedup-aware)."""
    _maybe_create_system_alert(
        generate_backup_failure_alert(
            error_message=error_message,
            backup_name=backup_name,
        )
    )


# Register retention handler with JobQueueService (GAP-011)
try:
    from app.services.job_queue_service import JobQueueService as _JQS

    def _run_retention_handler(payload: dict) -> dict:
        return run_retention()

    _JQS.register_handler("run_retention", _run_retention_handler)
except (ImportError, ValueError):
    # JobQueueService unavailable or handler name collision on re-import
    pass
