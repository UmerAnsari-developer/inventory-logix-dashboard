"""Alert routing to external channels (GAP-009).

Routes system alerts (etl_failure, backup_failure, pool_exhaustion) to the
configured channels. Every channel is optional and best-effort: a channel
failure is logged and never raised — the alert is already persisted in
model_monitoring_alerts, routing is a delivery extra.

Channels (env-configured, see app/config/settings.py):
- Email   — ALERT_EMAIL_ENABLED + ALERT_EMAIL_RECIPIENTS (via Mailer.send_alert)
- Slack   — SLACK_WEBHOOK_URL (incoming webhook, JSON payload)
- Webhook — ALERT_WEBHOOK_URL (generic JSON POST)
"""
from __future__ import annotations

import logging

import requests
from flask import current_app

LOGGER = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10


def _alert_subject_and_body(alert: dict) -> tuple[str, str]:
    severity = (alert.get("severity") or "info").upper()
    subject = f"[InventoryLogix][{severity}] {alert.get('alert_type', 'alert')}"
    body = (
        f"{alert.get('message', '')}\n\n"
        f"Severity: {severity}\n"
        f"Type: {alert.get('alert_type', '')}\n"
        f"Recommended action: {alert.get('recommended_action', '')}\n"
    )
    return subject, body


def _send_email(alert: dict) -> str:
    cfg = current_app.config
    if not cfg.get("ALERT_EMAIL_ENABLED"):
        return "skipped"
    recipients = [
        e.strip() for e in (cfg.get("ALERT_EMAIL_RECIPIENTS") or "").split(",") if e.strip()
    ]
    if not recipients:
        return "skipped"
    from .mailer import Mailer

    subject, body = _alert_subject_and_body(alert)
    return "sent" if Mailer.send_alert(recipients, subject, body) else "failed"


def _post_json(url: str, payload: dict, *, slack: bool) -> str:
    try:
        if slack:
            # Slack incoming-webhook format: {"text": "..."}
            _, body = _alert_subject_and_body(payload)
            payload = {"text": f"*{payload.get('alert_type', 'alert')}*\n{body}"}
        resp = requests.post(url, json=payload, timeout=_TIMEOUT_SECONDS)
        return "sent" if resp.status_code < 300 else f"failed({resp.status_code})"
    except requests.RequestException as exc:
        LOGGER.warning("Alert webhook delivery failed: %s", exc)
        return "failed"


def notify_alert(alert: dict) -> dict:
    """Route one alert to every configured channel. Never raises.

    Returns a per-channel result map, e.g. {"email": "sent", "slack": "skipped"}.
    """
    results: dict[str, str] = {}
    cfg = current_app.config if current_app else {}

    try:
        results["email"] = _send_email(alert)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Alert email routing error: %s", exc)
        results["email"] = "failed"

    slack_url = cfg.get("SLACK_WEBHOOK_URL") or ""
    try:
        results["slack"] = (
            _post_json(slack_url, alert, slack=True) if slack_url else "skipped"
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Alert slack routing error: %s", exc)
        results["slack"] = "failed"

    webhook_url = cfg.get("ALERT_WEBHOOK_URL") or ""
    try:
        results["webhook"] = (
            _post_json(webhook_url, alert, slack=False) if webhook_url else "skipped"
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Alert webhook routing error: %s", exc)
        results["webhook"] = "failed"

    LOGGER.info("Alert %s routed: %s", alert.get("alert_type"), results)
    return results