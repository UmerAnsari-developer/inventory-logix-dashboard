"""AI feature routes — forecast and anomaly."""
from __future__ import annotations

import logging
import time
from collections import OrderedDict

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from ..extensions import limiter
from ..repositories import ProductRepository
from ..services import AnomalyService, ForecastService, SettingsService
from ..utils import api_error, api_response

LOGGER = logging.getLogger(__name__)

ai_bp = Blueprint("ai", __name__, url_prefix="/ai")

# 1-hour TTL cache for expensive portfolio operations
_portfolio_cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
_PORTFOLIO_CACHE_TTL = 3600  # seconds
_MAX_PORTFOLIO_CACHE = 10


def _pcache_get(key: str):
    entry = _portfolio_cache.get(key)
    if entry and (time.time() - entry[0]) < _PORTFOLIO_CACHE_TTL:
        _portfolio_cache.move_to_end(key)
        return entry[1]
    return None


def _pcache_set(key: str, value: dict):
    _portfolio_cache[key] = (time.time(), value)
    _portfolio_cache.move_to_end(key)
    while len(_portfolio_cache) > _MAX_PORTFOLIO_CACHE:
        _portfolio_cache.popitem(last=False)


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
    cached = _pcache_get(cache_key)
    if cached:
        return api_response(cached)
    result = ForecastService.portfolio(horizon=horizon, model=model)
    _pcache_set(cache_key, result)
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
        result = AnomalyService.run_for_product(
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
    cached = _pcache_get(cache_key)
    if cached:
        return api_response(cached)
    result = AnomalyService.portfolio(contamination=contamination)
    _pcache_set(cache_key, result)
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
