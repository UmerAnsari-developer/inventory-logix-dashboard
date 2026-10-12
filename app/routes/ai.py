"""AI feature routes — forecast, anomaly, and model monitoring."""
from __future__ import annotations

import logging

from flask import Blueprint, render_template, request
from flask_login import current_user, login_required

from ..extensions import limiter
from ..repositories import ForecastRepository, ProductRepository
from ..security import write_roles_required
from ..services import AnomalyService, ForecastService, MonitoringService, SettingsService
from ..utils import api_error, api_response
from ..utils.cache import TTLCache, products_cache

LOGGER = logging.getLogger(__name__)

ai_bp = Blueprint("ai", __name__, url_prefix="/ai")

# 1-hour TTL cache for expensive portfolio operations (model fitting)
_portfolio_cache = TTLCache(ttl=3600, max_entries=10)


@ai_bp.route("/forecast")
@login_required
def forecast_page():
    products = products_cache.get_or_set(
        "ai_product_list", lambda: ProductRepository.list(limit=100)[0]
    )
    return render_template(
        "ai/forecast.html",
        products=products,
        default_model=SettingsService.forecast_model(),
    )


@ai_bp.route("/forecast/run", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
@write_roles_required
def forecast_run():
    payload = request.get_json(silent=True) or request.form
    try:
        product_id = int(payload.get("product_id"))
        model = payload.get("model") or SettingsService.forecast_model()
        horizon = int(payload.get("horizon", 90))
    except (TypeError, ValueError):
        return api_error("INVALID_INPUT", "product_id, model and horizon are required.", status=422)
    # Horizon must be one of the supported horizons (or capped to max)
    if model not in ForecastService.MODELS:
        return api_error("INVALID_INPUT", f"model must be one of {sorted(ForecastService.MODELS)}.", status=422)
    if horizon not in ForecastService.HORIZONS and horizon != ForecastService.MAX_HORIZON_DAYS:
        horizon = min((h for h in ForecastService.HORIZONS if h >= horizon), default=ForecastService.HORIZONS[-1])
    try:
        result = ForecastService.run(product_id, model=model, horizon=horizon)
    except ValueError as exc:
        return api_error("PRODUCT_NOT_FOUND", str(exc), status=404)
    except Exception as exc:
        LOGGER.exception("Forecast failed")
        return api_error("FORECAST_FAILED", str(exc), status=500)
    return api_response(result)


@ai_bp.route("/forecast/backtest", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
@write_roles_required
def forecast_backtest():
    """Run rolling-origin backtest for a product/model/horizon."""
    payload = request.get_json(silent=True) or request.form
    try:
        product_id = int(payload.get("product_id"))
        model = payload.get("model") or SettingsService.forecast_model()
        horizon = int(payload.get("horizon", 30))
        # Optional config
        config = None
        if payload.get("config"):
            from ..ml.backtest import BacktestConfig
            config = BacktestConfig(
                horizon=horizon,
                step_days=payload["config"].get("step_days", 7),
                min_train_days=payload["config"].get("min_train_days", 60),
                max_origins=payload["config"].get("max_origins", 10),
            )
    except (TypeError, ValueError):
        return api_error("INVALID_INPUT", "product_id, model and horizon are required.", status=422)
    try:
        result = ForecastService.backtest(product_id, model=model, horizon=horizon, config=config)
    except ValueError as exc:
        return api_error("PRODUCT_NOT_FOUND", str(exc), status=404)
    except Exception as exc:
        LOGGER.exception("Backtest failed")
        return api_error("BACKTEST_FAILED", str(exc), status=500)
    return api_response(result)


@ai_bp.route("/forecast/backtest", methods=["GET"])
@login_required
def forecast_backtest_results():
    """Retrieve backtest results with filters."""
    product_id = request.args.get("product_id", type=int)
    sku = request.args.get("sku")
    model = request.args.get("model")
    horizon = request.args.get("horizon", type=int)
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    limit = min(int(request.args.get("limit", 100)), 500)
    offset = max(int(request.args.get("offset", 0)), 0)
    
    rows, total = ForecastRepository.get_backtest_results(
        product_id=product_id, sku=sku, model_name=model,
        horizon=horizon, date_from=date_from, date_to=date_to,
        limit=limit, offset=offset,
    )
    return api_response({"results": rows, "total": total, "limit": limit, "offset": offset})


@ai_bp.route("/forecast/portfolio")
@limiter.limit("6 per minute")
@login_required
def forecast_portfolio():
    horizon = int(request.args.get("horizon", 30))
    model = request.args.get("model") or SettingsService.forecast_model()
    cache_key = f"forecast_portfolio:{horizon}:{model}"
    result = _portfolio_cache.get_or_set(
        cache_key, lambda: ForecastService.portfolio(horizon=horizon, model=model)
    )
    return api_response(result)


@ai_bp.route("/anomaly")
@login_required
def anomaly_page():
    products = products_cache.get_or_set(
        "ai_product_list", lambda: ProductRepository.list(limit=100)[0]
    )
    return render_template(
        "ai/anomaly.html",
        products=products,
        anomaly_enabled=SettingsService.is_on("anomaly_detection"),
        z_score_threshold=SettingsService.z_score_threshold(),
    )


@ai_bp.route("/anomaly/run", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
@write_roles_required
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
@limiter.limit("6 per minute")
@login_required
def anomaly_portfolio():
    try:
        contamination = float(request.args.get("contamination", 0.05))
    except ValueError:
        contamination = 0.05
    cache_key = f"anomaly_portfolio:{contamination}"
    result = _portfolio_cache.get_or_set(
        cache_key, lambda: AnomalyService.portfolio(contamination=contamination)
    )
    return api_response(result)


# ---------------------------------------------------------------------------
# Anomaly Benchmark & Validation Endpoints
# ---------------------------------------------------------------------------

@ai_bp.route("/anomaly/benchmark", methods=["GET"])
@limiter.limit("6 per minute")
@login_required
def anomaly_benchmark():
    """Run synthetic anomaly benchmark across the catalogue."""
    try:
        contamination = float(request.args.get("contamination", 0.05))
    except ValueError:
        contamination = 0.05
    try:
        result = AnomalyService.benchmark(contamination=contamination)
    except Exception as exc:
        LOGGER.exception("Anomaly benchmark failed")
        return api_error("BENCHMARK_FAILED", str(exc), status=500)
    return api_response(result)


@ai_bp.route("/anomaly/precision-recall", methods=["GET"])
@login_required
def anomaly_precision_recall():
    """Get empirical precision/recall from labeled alerts."""
    try:
        result = AnomalyService.get_precision_recall()
    except Exception as exc:
        LOGGER.exception("Precision/recall computation failed")
        return api_error("PRECISION_RECALL_FAILED", str(exc), status=500)
    return api_response(result)


@ai_bp.route("/anomaly/fatigue", methods=["GET"])
@login_required
def anomaly_fatigue():
    """Get alert fatigue metrics."""
    try:
        days = int(request.args.get("days", 30))
    except ValueError:
        days = 30
    try:
        result = AnomalyService.compute_fatigue_metrics(days=days)
    except Exception as exc:
        LOGGER.exception("Fatigue metrics computation failed")
        return api_error("FATIGUE_FAILED", str(exc), status=500)
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
@write_roles_required
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


@ai_bp.route("/anomaly/alerts/<int:alert_id>/label", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
@write_roles_required
def anomaly_alert_label(alert_id: int):
    """Label an alert as true_positive or false_positive for precision/recall tracking."""
    payload = request.get_json(silent=True) or {}
    label = payload.get("label")
    if not label:
        return api_error("INVALID_INPUT", "label is required (true_positive or false_positive).", status=422)
    try:
        user_id = current_user.id if current_user.is_authenticated else None
        result = AnomalyService.label_alert(alert_id, label, user_id)
    except ValueError as exc:
        return api_error("INVALID_LABEL", str(exc), status=422)
    except Exception as exc:
        LOGGER.exception("Failed to label alert")
        return api_error("LABEL_FAILED", str(exc), status=500)
    return api_response(result)


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
@write_roles_required
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
@write_roles_required
@limiter.limit("10 per minute")
def monitoring_evaluate():
    count = MonitoringService.evaluate_pending()
    return api_response({"evaluated": count})


@ai_bp.route("/monitoring/compute", methods=["POST"])
@login_required
@write_roles_required
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


@ai_bp.route("/monitoring/pool-status")
@login_required
@write_roles_required
def monitoring_pool_status():
    """Live DB connection-pool utilization (GAP-008)."""
    from ..database.connection import get_pool_utilization
    return api_response(get_pool_utilization())


@ai_bp.route("/monitoring/etl-health")
@login_required
@write_roles_required
def monitoring_etl_health():
    """Warehouse ETL health snapshot (GAP-007)."""
    return api_response(MonitoringService.etl_health())


@ai_bp.route("/monitoring/cache-status")
@login_required
@write_roles_required
def monitoring_cache_status():
    """Per-cache backend, size, and hit/miss stats (GAP-003)."""
    from ..utils.cache import (
        api_cache,
        dashboard_cache,
        global_cache,
        landing_cache,
        monitoring_cache,
        products_cache,
        reports_cache,
        suppliers_cache,
    )
    caches = {
        "products": products_cache,
        "suppliers": suppliers_cache,
        "dashboard": dashboard_cache,
        "reports": reports_cache,
        "global": global_cache,
        "api": api_cache,
        "landing": landing_cache,
        "monitoring": monitoring_cache,
    }
    return api_response({name: c.stats() for name, c in caches.items()})


@ai_bp.route("/monitoring/promote-baseline", methods=["POST"])
@login_required
@write_roles_required
@limiter.limit("10 per minute")
def monitoring_promote_baseline():
    """Pin the latest metrics for a SKU+Model as its baseline (GAP-016)."""
    payload = request.get_json(silent=True) or request.form
    sku = str(payload.get("sku") or "").strip()[:64]
    model_name = (payload.get("model_name") or "").strip() or None
    if not sku:
        return api_error("INVALID_INPUT", "sku is required.", status=422)
    try:
        result = MonitoringService.promote_baseline(
            sku, model_name=model_name,
            promoted_by=getattr(current_user, "username", None),
        )
    except ValueError as exc:
        return api_error("NO_METRICS", str(exc), status=404)
    except Exception:
        LOGGER.exception("Baseline promotion failed")
        return api_error("PROMOTION_FAILED", "Baseline promotion failed.", status=500)
    return api_response(result, message="Baseline promoted.")
