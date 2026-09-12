"""AI feature routes — forecast, anomaly, and model monitoring."""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from ..extensions import limiter
from ..repositories import ProductRepository
from ..services import AnomalyService, ForecastService, MonitoringService, SettingsService
from ..utils import api_error, api_response
from ..utils.cache import TTLCache

LOGGER = logging.getLogger(__name__)

ai_bp = Blueprint("ai", __name__, url_prefix="/ai")

# 1-hour TTL cache for expensive portfolio operations (model fitting)
_portfolio_cache = TTLCache(ttl=3600, max_entries=10)


@ai_bp.route("/forecast")
@login_required
def forecast_page():
    products, _ = ProductRepository.list(limit=100)
    return render_template(
        "ai/forecast.html",
        products=products,
        default_model=SettingsService.forecast_model(),
    )


@ai_bp.route("/forecast/run", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def forecast_run():
    payload = request.get_json(silent=True) or request.form
    try:
        product_id = int(payload.get("product_id"))
        model = payload.get("model") or SettingsService.forecast_model()
        horizon = int(payload.get("horizon", 90))
    except (TypeError, ValueError):
        return api_error("INVALID_INPUT", "product_id, model and horizon are required.", status=422)
    try:
        result = ForecastService.run(product_id, model=model, horizon=horizon)
    except ValueError as exc:
        return api_error("PRODUCT_NOT_FOUND", str(exc), status=404)
    except Exception as exc:
        LOGGER.exception("Forecast failed")
        return api_error("FORECAST_FAILED", str(exc), status=500)
    return api_response(result)


@ai_bp.route("/forecast/portfolio")
@login_required
def forecast_portfolio():
    horizon = int(request.args.get("horizon", 30))
    model = request.args.get("model") or SettingsService.forecast_model()
    cache_key = f"forecast_portfolio:{horizon}:{model}"
    cached = _portfolio_cache.get(cache_key)
    if cached:
        return api_response(cached)
    result = ForecastService.portfolio(horizon=horizon, model=model)
    _portfolio_cache.set(cache_key, result)
    return api_response(result)


@ai_bp.route("/anomaly")
@login_required
def anomaly_page():
    products, _ = ProductRepository.list(limit=100)
    return render_template(
        "ai/anomaly.html",
        products=products,
        anomaly_enabled=SettingsService.is_on("anomaly_detection"),
        z_score_threshold=SettingsService.z_score_threshold(),
    )


@ai_bp.route("/anomaly/run", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def anomaly_run():
    if not SettingsService.is_on("anomaly_detection"):
        return api_error(
            "FEATURE_DISABLED",
            "Anomaly detection is disabled. Enable it in Settings.",
            status=403,
        )
    payload = request.get_json(silent=True) or request.form
    try:
        product_id = int(payload.get("product_id"))
    except (TypeError, ValueError):
        return api_error("INVALID_INPUT", "product_id is required.", status=422)
    try:
        result = AnomalyService.run_for_product_enriched(
            product_id, z_threshold=SettingsService.z_score_threshold()
        )
    except ValueError as exc:
        return api_error("PRODUCT_NOT_FOUND", str(exc), status=404)
    return api_response(result)


@ai_bp.route("/anomaly/portfolio")
@login_required
def anomaly_portfolio():
    try:
        contamination = float(request.args.get("contamination", 0.05))
    except ValueError:
        contamination = 0.05
    cache_key = f"anomaly_portfolio:{contamination}"
    cached = _portfolio_cache.get(cache_key)
    if cached:
        return api_response(cached)
    result = AnomalyService.portfolio(contamination=contamination)
    _portfolio_cache.set(cache_key, result)
    return api_response(result)


# ---------------------------------------------------------------------------
# Anomaly alert CRUD endpoints
# ---------------------------------------------------------------------------

@ai_bp.route("/anomaly/summary")
@login_required
def anomaly_summary():
    """Dashboard KPI counts for anomaly alerts."""
    return api_response(AnomalyService.alert_summary())


@ai_bp.route("/anomaly/alerts")
@login_required
def anomaly_alerts():
    """List alerts with optional filters: risk_level, status, anomaly_type, date_from, date_to."""
    risk = request.args.get("risk_level")
    status = request.args.get("status")
    a_type = request.args.get("anomaly_type")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    try:
        limit = min(int(request.args.get("limit", 100)), 500)
        offset = max(int(request.args.get("offset", 0)), 0)
    except (TypeError, ValueError):
        limit, offset = 100, 0
    rows, total = AnomalyService.list_alerts(
        risk_level=risk, status=status, anomaly_type=a_type,
        date_from=date_from, date_to=date_to,
        limit=limit, offset=offset,
    )
    return api_response({"alerts": rows, "total": total, "limit": limit, "offset": offset})


@ai_bp.route("/anomaly/alerts/<int:alert_id>")
@login_required
def anomaly_alert_detail(alert_id: int):
    """Get a single alert by ID."""
    alert = AnomalyService.get_alert(alert_id)
    if not alert:
        return api_error("NOT_FOUND", "Alert not found", status=404)
    return api_response(alert)


@ai_bp.route("/anomaly/alerts/<int:alert_id>/status", methods=["PUT"])
@limiter.limit("30 per minute")
@login_required
def anomaly_alert_status(alert_id: int):
    """Update alert status (new → reviewed → acknowledged → resolved)."""
    payload = request.get_json(silent=True) or {}
    status = payload.get("status")
    if not status:
        return api_error("INVALID_INPUT", "status is required.", status=422)
    try:
        user_id = current_user.id if current_user.is_authenticated else None
        AnomalyService.update_alert_status(alert_id, status, reviewed_by=user_id)
    except ValueError as exc:
        return api_error("INVALID_STATUS", str(exc), status=422)
    except Exception as exc:
        LOGGER.exception("Failed to update alert status")
        return api_error("UPDATE_FAILED", str(exc), status=500)
    return api_response({"id": alert_id, "status": status})


@ai_bp.route("/eoq/sensitivity")
@login_required
def eoq_sensitivity():
    payload = request.args
    try:
        demand = float(payload.get("demand") or 0)
        ordering = float(payload.get("ordering_cost") or 0)
        holding = float(payload.get("holding_cost") or 0)
    except ValueError:
        return api_error("INVALID_INPUT", "Provide numeric demand, ordering_cost, holding_cost.",
                         status=422)
    from ..services import EOQService
    return api_response(EOQService.sensitivity_surface(demand, ordering, holding))


# ── Model Monitoring ──────────────────────────────────────────────────────

@ai_bp.route("/monitoring")
@login_required
def monitoring_page():
    try:
        products, _ = ProductRepository.list(search="", limit=200)
    except Exception:
        products = []
    return render_template("ai/monitoring.html", products=products)


@ai_bp.route("/monitoring/summary")
@login_required
def monitoring_summary():
    return api_response(MonitoringService.summary())


@ai_bp.route("/monitoring/health")
@login_required
def monitoring_health():
    return api_response(MonitoringService.health_table())


@ai_bp.route("/monitoring/actual-vs-predicted")
@login_required
def monitoring_avp():
    sku = request.args.get("sku")
    model = request.args.get("model")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    return api_response(MonitoringService.actual_vs_predicted_data(
        sku=sku, model_name=model, date_from=date_from, date_to=date_to,
    ))


@ai_bp.route("/monitoring/metrics")
@login_required
def monitoring_metrics():
    sku = request.args.get("sku")
    model = request.args.get("model")
    limit = min(int(request.args.get("limit", 60)), 200)
    return api_response(MonitoringService.metrics_trend(
        sku=sku, model_name=model, limit=limit,
    ))


@ai_bp.route("/monitoring/alerts")
@login_required
def monitoring_alerts():
    sku = request.args.get("sku")
    model = request.args.get("model")
    status = request.args.get("status")
    alert_type = request.args.get("alert_type")
    limit = min(int(request.args.get("limit", 100)), 500)
    offset = max(int(request.args.get("offset", 0)), 0)
    rows, total = MonitoringService.alerts_list(
        sku=sku, model_name=model, status=status,
        alert_type=alert_type, limit=limit, offset=offset,
    )
    return api_response({"alerts": rows, "total": total})


@ai_bp.route("/monitoring/alerts/<int:alert_id>/status", methods=["PUT"])
@login_required
@limiter.limit("30 per minute")
def monitoring_alert_status(alert_id: int):
    payload = request.get_json(silent=True) or request.form
    status = payload.get("status")
    if not status:
        return api_error("INVALID_INPUT", "status is required.", status=422)
    MonitoringService.update_alert(alert_id, status)
    return api_response({"id": alert_id, "status": status})


@ai_bp.route("/monitoring/evaluate", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def monitoring_evaluate():
    count = MonitoringService.evaluate_pending()
    return api_response({"evaluated": count})


@ai_bp.route("/monitoring/compute", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def monitoring_compute():
    payload = request.get_json(silent=True) or request.form
    sku = payload.get("sku")
    model = payload.get("model_name", "prophet")
    window = int(payload.get("window_days", 7))
    if not sku:
        return api_error("INVALID_INPUT", "sku is required.", status=422)
    result = MonitoringService.compute_metrics(sku, model, window_days=window)
    return api_response(result or {"message": "No evaluated data for this SKU+Model"})


@ai_bp.route("/monitoring/predictions")
@login_required
def monitoring_predictions():
    sku = request.args.get("sku")
    model = request.args.get("model")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    limit = min(int(request.args.get("limit", 200)), 500)
    offset = max(int(request.args.get("offset", 0)), 0)
    rows, total = MonitoringService.predictions_list(
        sku=sku, model_name=model,
        date_from=date_from, date_to=date_to,
        limit=limit, offset=offset,
    )
    return api_response({"predictions": rows, "total": total})
