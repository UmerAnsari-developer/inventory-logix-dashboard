"""Forecast service — bridges the ML module with the rest of the app."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from ..ml.forecasting import (
    forecast_with_prophet,
    forecast_with_xgboost,
    forecast_ensemble,
)
from ..ml.backtest import BacktestConfig, rolling_origin_backtest, run_baseline_comparison, aggregate_backtest_results
from ..repositories import ForecastRepository
from ..repositories.product_repo import ProductRepository
from ..repositories.movement_repo import MovementRepository
from ..config.settings import Config

LOGGER = logging.getLogger(__name__)


class ForecastService:
    MODELS = {"prophet": "Prophet (Seasonality)", "xgboost": "XGBoost (ML)", "ensemble": "Ensemble (Both)"}
    MIN_HISTORY_FOR_PROPHET = 14
    MIN_HISTORY_FOR_XGBOOST = 45
    MAX_HORIZON_DAYS = 365
    # Required forecast horizons (spec §3) — every horizon evaluated independently
    HORIZONS = [7, 15, 30, 45, 60, 90, 120, 150, 180]

    @classmethod
    def run(cls, product_id: int, *, model: str = "prophet", horizon: int = 90) -> dict:
        product = ProductRepository.find(product_id)
        if not product:
            raise ValueError("Product not found")
        # Fetch enough history for the horizon (at least 2x horizon, capped at 730 days)
        history_days = min(max(horizon * 2, 180), 730)
        rows = MovementRepository.daily_for_product(product_id, days=history_days)
        history = [{"ds": r["day"].isoformat(), "y": int(r["total"])} for r in rows]
        
        # Validate horizon against data sufficiency
        validation = cls.validate_horizon(history, horizon, model)
        if not validation["sufficient"]:
            LOGGER.warning("Horizon validation warning for product %s: %s", product["sku"], validation["warning"])
        
        if model == "xgboost":
            result = forecast_with_xgboost(history, horizon)
        elif model == "ensemble":
            result = forecast_ensemble(history, horizon)
        else:
            result = forecast_with_prophet(history, horizon)
        
        result["product"] = {
            "id": product["id"],
            "sku": product["sku"],
            "name": product["name"],
        }
        result["model_label"] = cls.MODELS.get(model, "Prophet")
        result["model_used"] = validation["model_used"]
        result["data_sufficiency"] = validation["data_sufficiency"]
        if validation["warning"]:
            result["warning"] = validation["warning"]
        
        ForecastRepository.save(product_id, model, horizon, result)
        cls._update_monitoring(product["sku"], model, history)
        return result

    @classmethod
    def validate_horizon(cls, history: list[dict], horizon: int, model: str) -> dict:
        """Check data sufficiency for the requested horizon and model.
        
        Returns dict with:
        - sufficient: bool (True if horizon is reasonable for the data)
        - model_used: str (actual model that will be used, may be fallback)
        - data_sufficiency: str ("sufficient", "limited", "insufficient")
        - warning: str or None
        """
        history_len = len(history)
        
        # Cap horizon at maximum
        if horizon > cls.MAX_HORIZON_DAYS:
            horizon = cls.MAX_HORIZON_DAYS
        
        # Determine minimum required history for each model
        if model == "prophet":
            min_required = cls.MIN_HISTORY_FOR_PROPHET
        elif model == "xgboost":
            min_required = cls.MIN_HISTORY_FOR_XGBOOST
        else:  # ensemble needs both
            min_required = max(cls.MIN_HISTORY_FOR_PROPHET, cls.MIN_HISTORY_FOR_XGBOOST)
        
        # Check if we have enough data for the requested model
        if history_len < min_required:
            return {
                "sufficient": False,
                "model_used": "moving_average",
                "data_sufficiency": "insufficient",
                "warning": f"Need at least {min_required} days of history for {model}; using moving average fallback",
            }
        
        # Check horizon reasonableness
        if horizon > history_len * 4:
            return {
                "sufficient": True,
                "model_used": model if history_len >= min_required else "moving_average",
                "data_sufficiency": "limited",
                "warning": f"Horizon ({horizon}d) exceeds 4x history length ({history_len}d); predictions may be unreliable",
            }
        elif horizon > history_len * 2:
            return {
                "sufficient": True,
                "model_used": model if history_len >= min_required else "moving_average",
                "data_sufficiency": "limited",
                "warning": f"Horizon ({horizon}d) exceeds 2x history length ({history_len}d); predictions may be unreliable",
            }
        elif horizon > history_len:
            return {
                "sufficient": True,
                "model_used": model if history_len >= min_required else "moving_average",
                "data_sufficiency": "limited",
                "warning": f"Horizon ({horizon}d) exceeds history length ({history_len}d); predictions may be unreliable",
            }
        
        return {
            "sufficient": True,
            "model_used": model,
            "data_sufficiency": "sufficient",
            "warning": None,
        }

    @classmethod
    def _update_monitoring(cls, sku: str, model_name: str, history: list[dict]) -> None:
        """Record predictions for last 30 days and compute monitoring metrics."""
        try:
            from ..repositories.monitoring_repo import MonitoringRepository
            from ..monitoring.metrics import evaluate_all
            from ..monitoring.degradation import detect_degradation, model_health_status

            if len(history) < 10:
                return

            actuals_by_day = {r["ds"]: r["y"] for r in history}
            today = date.today()
            window = min(30, len(history) - 1)

            # Batch-insert predictions with actuals in one round-trip
            values = [r["y"] for r in history]
            batch_rows = []
            for i in range(len(history) - window, len(history)):
                day_str = history[i]["ds"]
                actual = float(actuals_by_day[day_str])
                start = max(0, i - 7)
                predicted = sum(values[start:i]) / max(1, i - start)
                batch_rows.append({
                    "sku": sku, "model_name": model_name,
                    "forecast_date": day_str,
                    "predicted_value": round(predicted, 2),
                    "actual_value": actual,
                })
            MonitoringRepository.save_predictions_batch(batch_rows)

            # Compute metrics from evaluated predictions
            today_str = today.isoformat()
            week_ago = (today - timedelta(days=window)).isoformat()
            avp = MonitoringRepository.actual_vs_predicted(
                sku=sku, model_name=model_name,
                date_from=week_ago, date_to=today_str, limit=100,
            )
            if not avp:
                return
            actual_vals = [float(r["actual_value"]) for r in avp]
            pred_vals = [float(r["predicted_value"]) for r in avp]
            metrics = evaluate_all(actual_vals, pred_vals)
            # Only keys with columns in forecast_monitoring_metrics may pass
            # through **metrics — extras (mase/interval_coverage/mape_valid_count)
            # would raise TypeError and silently skip the whole monitoring update.
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

            MonitoringRepository.save_metrics(
                sku=sku, model_name=model_name, monitoring_date=today,
                aggregation_period="daily", **metrics,
                baseline_mae=baseline_mae, baseline_mape=baseline_mape,
                mae_change_percent=deg["change_percent"],
                mape_change_percent=deg_mape["change_percent"],
                model_status=status,
            )
        except Exception:
            LOGGER.debug("Monitoring update skipped", exc_info=True)

    @classmethod
    def portfolio(cls, horizon: int = 30, model: str = "prophet") -> list[dict]:
        """Forecast portfolio summary.
        
        If PORTFOLIO_RUN_ACTUAL_MODELS is True, runs actual model per product (cached).
        Otherwise, uses 7-day moving average baseline (honest labeling).
        """
        run_actual = getattr(Config, "PORTFOLIO_RUN_ACTUAL_MODELS", True)
        
        if run_actual:
            return cls._portfolio_actual_models(horizon, model)
        else:
            return cls._portfolio_moving_average(horizon, model)

    @classmethod
    def _portfolio_actual_models(cls, horizon: int, model: str) -> list[dict]:
        """Run actual forecast model per product (cached via ForecastRepository)."""
        from ..database import get_cursor
        out = []
        with get_cursor() as cur:
            cur.execute("SELECT id, sku, name FROM products WHERE deleted_at IS NULL ORDER BY id")
            products = list(cur.fetchall())
            if not products:
                return out
            product_ids = [p["id"] for p in products]
            cur.execute(
                """
                SELECT m.product_id, m.created_at::date AS day,
                       COALESCE(SUM(CASE WHEN m.type='OUT' THEN m.quantity ELSE 0 END), 0) AS total
                FROM movements m
                WHERE m.product_id = ANY(%s) AND m.created_at >= NOW() - INTERVAL '180 days'
                  AND m.deleted_at IS NULL
                GROUP BY m.product_id, m.created_at::date
                ORDER BY m.product_id, day
                """,
                (product_ids,),
            )
            movement_rows = cur.fetchall()
        from collections import defaultdict
        movements_by_product: dict[int, list] = defaultdict(list)
        for row in movement_rows:
            movements_by_product[row["product_id"]].append(row)
        
        for p in products:
            try:
                rows = movements_by_product.get(p["id"], [])
                history = [{"ds": r["day"].isoformat(), "y": int(r["total"])} for r in rows]
                
                if not history or sum(h["y"] for h in history) == 0:
                    continue
                
                # Check cache first
                cached = ForecastRepository.recent(p["id"], limit=1)
                cached_result = None
                for c in cached:
                    if c.get("model") == model and c.get("horizon") == horizon:
                        cached_result = c
                        break
                
                if cached_result:
                    payload = cached_result["payload"]
                    model_used = payload.get("model_used", model)
                    data_sufficiency = payload.get("data_sufficiency", "sufficient")
                else:
                    # Run actual model
                    validation = cls.validate_horizon(history, horizon, model)
                    if model == "xgboost":
                        result = forecast_with_xgboost(history, horizon)
                    elif model == "ensemble":
                        result = forecast_ensemble(history, horizon)
                    else:
                        result = forecast_with_prophet(history, horizon)
                    
                    result["product"] = {"id": p["id"], "sku": p["sku"], "name": p["name"]}
                    result["model_label"] = cls.MODELS.get(model, "Prophet")
                    result["model_used"] = validation["model_used"]
                    result["data_sufficiency"] = validation["data_sufficiency"]
                    if validation["warning"]:
                        result["warning"] = validation["warning"]
                    
                    ForecastRepository.save(p["id"], model, horizon, result)
                    model_used = validation["model_used"]
                    data_sufficiency = validation["data_sufficiency"]
                    payload = result
                
                predicted_total = sum(payload.get("predictions", [])[:horizon])
                baseline = payload.get("baseline", 0)
                recent_avg = sum(h["y"] for h in history[-7:]) / min(7, len(history))
                delta_pct = round(((recent_avg / max(baseline, 1)) - 1) * 100, 1)
                accuracy = payload.get("accuracy", 0)
                
                out.append({
                    "id": p["id"],
                    "sku": p["sku"],
                    "name": p["name"],
                    "model": cls.MODELS.get(model, "Prophet (Seasonality)"),
                    "model_used": model_used,
                    "predicted_units": int(round(predicted_total)),
                    "baseline": round(baseline, 1),
                    "delta_pct": delta_pct,
                    "accuracy": accuracy,
                    "data_sufficiency": data_sufficiency,
                })
            except Exception as exc:
                LOGGER.warning("Portfolio forecast failed for %s: %s", p["sku"], exc)
        return out

    @classmethod
    def _portfolio_moving_average(cls, horizon: int = 30, model: str = "prophet") -> list[dict]:
        """Lightweight forecast summary — uses 7-day moving average, no model fitting.
        
        Honestly labeled as baseline projection.
        """
        from ..database import get_cursor
        out = []
        with get_cursor() as cur:
            cur.execute("SELECT id, sku, name FROM products WHERE deleted_at IS NULL ORDER BY id")
            products = list(cur.fetchall())
            if not products:
                return out
            product_ids = [p["id"] for p in products]
            cur.execute(
                """
                SELECT m.product_id, m.created_at::date AS day,
                       COALESCE(SUM(CASE WHEN m.type='OUT' THEN m.quantity ELSE 0 END), 0) AS total
                FROM movements m
                WHERE m.product_id = ANY(%s) AND m.created_at >= NOW() - INTERVAL '90 days'
                  AND m.deleted_at IS NULL
                GROUP BY m.product_id, m.created_at::date
                ORDER BY m.product_id, day
                """,
                (product_ids,),
            )
            movement_rows = cur.fetchall()
        from collections import defaultdict
        movements_by_product: dict[int, list] = defaultdict(list)
        for row in movement_rows:
            movements_by_product[row["product_id"]].append(row)
        for p in products:
            try:
                rows = movements_by_product.get(p["id"], [])
                totals = [int(r["total"]) for r in rows]
                if not totals or sum(totals) == 0:
                    continue
                baseline = sum(totals) / len(totals)
                window = min(7, len(totals))
                recent_avg = sum(totals[-window:]) / window
                predicted = round(recent_avg * horizon, 1)
                delta_pct = round(((recent_avg / max(baseline, 1)) - 1) * 100, 1)
                active = [t for t in totals if t > 0]
                avg_active = sum(active) / len(active) if active else 1
                mae = sum(abs(t - baseline) for t in active) / len(active) if active else 0
                accuracy = max(0, round(100 - (mae / max(avg_active, 1)) * 100, 1))
                out.append({
                    "id": p["id"],
                    "sku": p["sku"],
                    "name": p["name"],
                    "model": "7-day MA (baseline)",
                    "model_used": "moving_average",
                    "predicted_units": int(predicted),
                    "baseline": round(baseline, 1),
                    "delta_pct": delta_pct,
                    "accuracy": accuracy,
                    "data_sufficiency": "baseline_only",
                })
            except Exception as exc:
                LOGGER.warning("Portfolio MA forecast failed for %s: %s", p["sku"], exc)
        return out

    @classmethod
    def backtest(cls, product_id: int, *, model: str = "prophet",
                 horizon: int = 30, config: BacktestConfig | None = None) -> dict:
        """Run rolling-origin backtest for a product/model/horizon.

        Includes baseline comparison and honest model selection: the
        recommended model is whichever (model or baseline) wins on WAPE.
        """
        from ..ml.backtest import select_best_model

        product = ProductRepository.find(product_id)
        if not product:
            raise ValueError("Product not found")

        # Get extended history for backtesting (365+ days)
        rows = MovementRepository.daily_for_product(product_id, days=365)
        history = [{"ds": r["day"].isoformat(), "y": int(r["total"])} for r in rows]

        if len(history) < 60:
            raise ValueError("Need at least 60 days of history for backtesting")

        if config is None:
            config = BacktestConfig(horizon=horizon)
        else:
            config.horizon = horizon

        # Run backtest for primary model
        primary_results = rolling_origin_backtest(history, config, model)

        # Run baselines for comparison
        baseline_results = run_baseline_comparison(history, config, model)

        # Aggregate results
        primary_agg = aggregate_backtest_results(primary_results)
        baselines_agg = {}
        for name, results in baseline_results.items():
            if name != model:
                baselines_agg[name] = aggregate_backtest_results(results)

        # Honest model selection: winner on WAPE (model vs baselines)
        comparison = {**baseline_results, model: primary_results}
        selection = select_best_model(comparison, model, metric="wape")

        # Actual models that ran (may be fallbacks)
        models_actually_used = sorted({r.model_used for r in primary_results if r.model_used})
        leakage_ok = all(r.leakage_ok for r in primary_results)

        # Persist backtest results
        ForecastRepository.save_backtest_results(product_id, model, horizon, primary_results)
        for baseline_name, results in baseline_results.items():
            if baseline_name != model:
                ForecastRepository.save_backtest_results(product_id, baseline_name, horizon, results)

        return {
            "product_id": product_id,
            "sku": product["sku"],
            "model": model,
            "horizon": horizon,
            "origins_tested": len(primary_results),
            "metrics": primary_agg,
            "baselines": baselines_agg,
            "selection": selection,
            "models_actually_used": models_actually_used,
            "leakage_ok": leakage_ok,
        }