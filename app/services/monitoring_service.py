"""Forecast model monitoring service."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from ..monitoring.metrics import evaluate_all
from ..monitoring.degradation import detect_degradation, model_health_status, sustained_degradation
from ..monitoring.alerts import (
    generate_alert,
    deduplicate_alerts,
    generate_etl_failure_alert,
    generate_backup_failure_alert,
)
from ..repositories.monitoring_repo import MonitoringRepository

LOGGER = logging.getLogger(__name__)


class MonitoringService:

    # ── Evaluate pending forecasts ───────────────────────────────

    @staticmethod
    def evaluate_pending() -> int:
        """Evaluate all pending predictions that now have actual values."""
        pending = MonitoringRepository.find_pending_evaluations()
        if not pending:
            return 0
        pairs = [(float(row["actual_value"]), row["id"]) for row in pending]
        MonitoringRepository.batch_update_actuals(pairs)
        return len(pairs)

    # ── Compute and store monitoring metrics ─────────────────────

    @staticmethod
    def compute_metrics(sku: str, model_name: str, *,
                        period: str = "daily", window_days: int = 7) -> dict | None:
        """Compute monitoring metrics for a SKU+Model over a window."""
        today = date.today()
        date_from = today - timedelta(days=window_days)
        avp = MonitoringRepository.actual_vs_predicted(
            sku=sku, model_name=model_name,
            date_from=date_from, date_to=today, limit=1000,
        )
        if not avp:
            return None
        actuals = [float(r["actual_value"]) for r in avp]
        predicted = [float(r["predicted_value"]) for r in avp]
        metrics = evaluate_all(actuals, predicted)
        # Only keys with columns in forecast_monitoring_metrics may pass
        # through **metrics — extras would raise TypeError (500 on /compute).
        for extra in ("mape_valid_count", "mase", "interval_coverage"):
            metrics.pop(extra, None)

        baseline = MonitoringRepository.baseline_metrics(sku, model_name)
        baseline_mae = float(baseline["mae"]) if baseline and baseline.get("mae") else None
        baseline_mape = float(baseline["mape"]) if baseline and baseline.get("mape") else None

        deg = detect_degradation(metrics["mae"], baseline_mae)
        deg_mape = detect_degradation(metrics["mape"], baseline_mape)
        status = model_health_status(
            metrics["mae"], metrics["mape"], baseline_mae, baseline_mape,
        )

        mae_change = deg["change_percent"]
        mape_change = deg_mape["change_percent"]

        metric_id = MonitoringRepository.save_metrics(
            sku=sku, model_name=model_name, monitoring_date=today,
            aggregation_period=period, **metrics,
            baseline_mae=baseline_mae, baseline_mape=baseline_mape,
            mae_change_percent=mae_change, mape_change_percent=mape_change,
            model_status=status,
        )

        # Check for sustained degradation and generate alerts
        recent = MonitoringRepository.recent_statuses(sku, model_name)
        if sustained_degradation(recent):
            _maybe_create_alert(sku, model_name, today, "mae", baseline_mae, metrics["mae"], mae_change)
            _maybe_create_alert(sku, model_name, today, "mape", baseline_mape, metrics["mape"], mape_change)

        return {**metrics, "model_status": status, "metric_id": metric_id}

    # ── Dashboard data ───────────────────────────────────────────

    @staticmethod
    def summary() -> dict:
        models = MonitoringRepository.distinct_models()
        total_evaluated = MonitoringRepository.total_evaluated()
        model_summary = MonitoringRepository.model_summary()
        healthy = sum(1 for m in model_summary if m.get("model_status") == "healthy")
        degraded = sum(1 for m in model_summary if m.get("model_status") in ("degraded", "critical"))
        mae_vals = [float(m["mae"]) for m in model_summary if m.get("mae") is not None]
        mape_vals = [float(m["mape"]) for m in model_summary if m.get("mape") is not None]
        alert_sev = MonitoringRepository.alert_counts_by_severity()
        return {
            "models_monitored": len(models),
            "forecasts_evaluated": total_evaluated,
            "current_mae": round(sum(mae_vals) / len(mae_vals), 2) if mae_vals else 0,
            "current_mape": round(sum(mape_vals) / len(mape_vals), 2) if mape_vals else 0,
            "healthy_models": healthy,
            "degraded_models": degraded,
            "alerts_by_severity": alert_sev,
        }

    @staticmethod
    def health_table() -> list[dict]:
        return MonitoringRepository.model_summary()

    @staticmethod
    def actual_vs_predicted_data(sku=None, model_name=None,
                                  date_from=None, date_to=None) -> list[dict]:
        return MonitoringRepository.actual_vs_predicted(
            sku=sku, model_name=model_name,
            date_from=date_from, date_to=date_to, limit=500,
        )

    @staticmethod
    def metrics_trend(sku=None, model_name=None, limit: int = 60) -> list[dict]:
        return MonitoringRepository.get_metrics(
            sku=sku, model_name=model_name, limit=limit,
        )

    @staticmethod
    def alerts_list(sku=None, model_name=None, status=None,
                    alert_type=None, limit=100, offset=0) -> tuple[list[dict], int]:
        return MonitoringRepository.get_alerts(
            sku=sku, model_name=model_name, status=status,
            alert_type=alert_type, limit=limit, offset=offset,
        )

    @staticmethod
    def update_alert(alert_id: int, status: str) -> None:
        MonitoringRepository.update_alert_status(alert_id, status)

    # ── Baseline promotion (GAP-016) ─────────────────────────────

    @staticmethod
    def promote_baseline(sku: str, model_name: str | None = None,
                         promoted_by: str | None = None) -> dict | list:
        """Pin the latest metrics row(s) for a SKU as its baseline.

        With model_name, pins that one model; without, pins every model that
        has metrics for the SKU. Raises ValueError when no metrics exist yet.
        """
        rows = MonitoringRepository.latest_metrics(sku, model_name)
        if not rows:
            raise ValueError(
                f"No monitoring metrics found for sku={sku!r}"
                + (f", model_name={model_name!r}" if model_name else "")
                + " — run /ai/monitoring/compute first."
            )
        # M2: an all-NULL metrics row would pin NULL baselines that shadow the
        # healthy fallback and silently disable drift detection — refuse it.
        rows = [r for r in rows if r.get("mae") is not None or r.get("mape") is not None]
        if not rows:
            raise ValueError(
                f"Latest metrics for sku={sku!r} have no mae/mape values — nothing to pin."
            )
        promoted = [
            MonitoringRepository.promote_baseline(
                sku=r["sku"], model_name=r["model_name"],
                mae=r.get("mae"), mape=r.get("mape"),
                promoted_by=promoted_by,
            )
            for r in rows
        ]
        return promoted[0] if model_name else promoted

    @staticmethod
    def predictions_list(sku=None, model_name=None,
                          date_from=None, date_to=None,
                          limit=200, offset=0) -> tuple[list[dict], int]:
        return MonitoringRepository.get_predictions(
            sku=sku, model_name=model_name,
            date_from=date_from, date_to=date_to,
            limit=limit, offset=offset,
        )

    # ── ETL health (GAP-007) ─────────────────────────────────────

    @staticmethod
    def etl_health() -> dict:
        """Warehouse ETL health snapshot from etl_state + etl_warehouse_state.

        Reads only persisted state — no ETL run is triggered. Reports the
        last run date, the movement watermark vs. the live max movement id
        (pending backlog), and the restore-job status if one is recorded.
        """
        from ..database import get_cursor

        health: dict = {
            "last_run_at": None,
            "watermark": 0,
            "max_movement_id": 0,
            "pending_movements": 0,
            "restore_job_status": None,
            "restore_job_error": None,
            "status": "unknown",
        }
        try:
            with get_cursor() as cur:
                cur.execute(
                    "SELECT state_key, value FROM etl_state "
                    "WHERE state_key IN ('last_run_at', 'last_movement_id')"
                )
                state = {r["state_key"]: r["value"] for r in cur.fetchall()}
                health["last_run_at"] = state.get("last_run_at")
                health["watermark"] = int(state.get("last_movement_id") or 0)

                cur.execute("SELECT COALESCE(MAX(id), 0) AS max_id FROM movements")
                health["max_movement_id"] = int(cur.fetchone()["max_id"] or 0)

                cur.execute(
                    "SELECT state_key, value FROM etl_warehouse_state "
                    "WHERE state_key IN ('restore_job_status', 'restore_job_error')"
                )
                wh = {r["state_key"]: r["value"] for r in cur.fetchall()}
                health["restore_job_status"] = wh.get("restore_job_status")
                health["restore_job_error"] = wh.get("restore_job_error")
        except Exception as e:  # noqa: BLE001 — health endpoint must not 500
            LOGGER.warning("ETL health read failed: %s", e)
            health["status"] = "error"
            return health

        health["pending_movements"] = max(
            health["max_movement_id"] - health["watermark"], 0
        )
        if not health["last_run_at"]:
            health["status"] = "never_run"
        elif health["restore_job_status"] == "failed":
            health["status"] = "restore_failed"
        else:
            health["status"] = "ok"
        return health


def _maybe_create_alert(sku, model_name, today, metric_name,
                          baseline, current, change_pct):
    if baseline is None or current is None:
        return
    existing = MonitoringRepository.unresolved_alerts(sku, model_name, f"{metric_name}_degradation")
    new_alert = generate_alert(
        sku=sku, model_name=model_name, alert_date=str(today),
        alert_type=f"{metric_name}_degradation", metric=metric_name,
        baseline_value=baseline, current_value=current,
        change_percent=change_pct,
    )
    if deduplicate_alerts(existing, new_alert):
        MonitoringRepository.save_alert(**new_alert)


def _maybe_create_system_alert(alert: dict) -> None:
    """Persist a system-level alert (etl_failure, backup_failure, ...) with dedup.

    ``alert`` is a dict from generate_*_alert() carrying sku/model_name/
    alert_type plus all save_alert kwargs. Skips when an unresolved alert of
    the same (sku, model_name, alert_type) already exists. After saving,
    fires the optional external alert channels (GAP-009) — best-effort.
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
