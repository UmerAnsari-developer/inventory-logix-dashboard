"""Anomaly detection service."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from ..ml.anomaly import detect_anomalies_enriched, detect_anomalies_isoforest, spc_zscore_analysis
from ..repositories import AnomalyRepository
from ..repositories.product_repo import ProductRepository
from ..repositories.movement_repo import MovementRepository

LOGGER = logging.getLogger(__name__)


class AnomalyService:
    @staticmethod
    def run_for_product(product_id: int, *, contamination: float = 0.05,
                        z_threshold: float | None = None):
        if z_threshold is None:
            try:
                from .settings_service import SettingsService
                z_threshold = SettingsService.z_score_threshold()
            except Exception:
                z_threshold = 3.0
        product = ProductRepository.find(product_id)
        if not product:
            raise ValueError("Product not found")
        rows = MovementRepository.daily_for_product(product_id, days=120)
        series = [{"day": r["day"].isoformat(), "value": int(r["total"])} for r in rows]

        # Inventory context for risk scoring
        inv_pos = float(product.get("current_stock") or 0)
        safety = float(product.get("reorder_point") or 0) * 0.25  # approx safety stock
        rop = float(product.get("reorder_point") or 0)

        result = detect_anomalies_enriched(
            series,
            product_id=product_id,
            sku=product.get("sku", ""),
            product_name=product.get("name", ""),
            contamination=contamination,
            z_threshold=z_threshold,
            inventory_position=inv_pos,
            safety_stock=safety,
            reorder_point=rop,
        )

        # Merge SPC chart data
        spc = spc_zscore_analysis(series, limit=z_threshold)
        result.update(spc)

        # Persist enriched alerts
        for anomaly in result.get("anomalies", []):
            AnomalyRepository.save(
                product_id=product_id,
                anomaly_type=anomaly.get("type", "spike"),
                z_score=_to_py(anomaly.get("z_score")),
                confidence=_to_py(anomaly.get("confidence")),
                description=anomaly.get("description"),
                sku=anomaly.get("sku"),
                expected_value=_to_py(anomaly.get("expected_value")),
                observed_value=_to_py(anomaly.get("observed_value")),
                deviation_pct=_to_py(anomaly.get("deviation_pct")),
                metric=anomaly.get("metric", "quantity"),
                alert_date=anomaly.get("day"),
                risk_level=anomaly.get("risk_level", "low"),
                detection_method=anomaly.get("detection_method", "zscore"),
                recommended_action=anomaly.get("recommended_action"),
                status=anomaly.get("status", "new"),
            )
        return result

    @staticmethod
    def run_for_product_enriched(product_id: int, *, contamination: float = 0.05,
                                 z_threshold: float | None = None,
                                 with_forecast: bool = True) -> dict:
        """Run detection with optional forecast integration and rule-based peaks."""
        if z_threshold is None:
            try:
                from .settings_service import SettingsService
                z_threshold = SettingsService.z_score_threshold()
            except Exception:
                z_threshold = 3.0
        product = ProductRepository.find(product_id)
        if not product:
            raise ValueError("Product not found")
        rows = MovementRepository.daily_for_product(product_id, days=120)
        series = [{"day": r["day"].isoformat(), "value": int(r["total"])} for r in rows]
        values = [float(s["value"]) for s in series]

        inv_pos = float(product.get("current_stock") or 0)
        safety = float(product.get("reorder_point") or 0) * 0.25
        rop = float(product.get("reorder_point") or 0)

        # Optional: run forecast to get expected-demand baseline
        forecast_values = None
        if with_forecast:
            try:
                from ..ml.forecasting import forecast_ensemble
                history = [{"ds": r["day"].isoformat(), "y": int(r["total"])} for r in rows]
                if len(history) >= 14:
                    fcast = forecast_ensemble(history, horizon=14)
                    forecast_values = fcast.get("predictions", [])
            except Exception as exc:
                LOGGER.warning("Forecast integration failed for %s: %s", product.get("sku"), exc)

        # Rule-based peaks: daily > 3x rolling average
        rule_peaks = _detect_rule_based_peaks(series, multiplier=3.0)

        result = detect_anomalies_enriched(
            series,
            product_id=product_id,
            sku=product.get("sku", ""),
            product_name=product.get("name", ""),
            contamination=contamination,
            z_threshold=z_threshold,
            inventory_position=inv_pos,
            safety_stock=safety,
            reorder_point=rop,
            forecast_values=forecast_values,
            rule_based_peaks=rule_peaks,
        )

        spc = spc_zscore_analysis(series, limit=z_threshold)
        result.update(spc)
        result["product"] = {
            "id": product["id"],
            "sku": product["sku"],
            "name": product["name"],
            "current_stock": inv_pos,
            "reorder_point": rop,
        }

        for anomaly in result.get("anomalies", []):
            AnomalyRepository.save(
                product_id=product_id,
                anomaly_type=anomaly.get("type", "spike"),
                z_score=_to_py(anomaly.get("z_score")),
                confidence=_to_py(anomaly.get("confidence")),
                description=anomaly.get("description"),
                sku=anomaly.get("sku"),
                expected_value=_to_py(anomaly.get("expected_value")),
                observed_value=_to_py(anomaly.get("observed_value")),
                deviation_pct=_to_py(anomaly.get("deviation_pct")),
                metric=anomaly.get("metric", "quantity"),
                alert_date=anomaly.get("day"),
                risk_level=anomaly.get("risk_level", "low"),
                detection_method=anomaly.get("detection_method", "zscore"),
                recommended_action=anomaly.get("recommended_action"),
                status=anomaly.get("status", "new"),
            )
        return result

    @staticmethod
    def portfolio(contamination: float = 0.05) -> list[dict]:
        from ..database import get_cursor
        out = []
        with get_cursor() as cur:
            cur.execute("SELECT id, sku, name FROM products ORDER BY id LIMIT 30")
            products = list(cur.fetchall())
        for p in products:
            try:
                result = AnomalyService.run_for_product(p["id"], contamination=contamination)
                anomalies = result.get("anomalies", [])
                if anomalies:
                    out.append({
                        "id": p["id"],
                        "sku": p["sku"],
                        "name": p["name"],
                        "anomaly_count": len(anomalies),
                        "max_z": max((abs(a.get("z_score") or 0) for a in anomalies), default=0),
                        "top_anomaly": anomalies[0],
                    })
            except Exception as exc:  # pragma: no cover
                LOGGER.warning("Anomaly detection failed for %s: %s", p["sku"], exc)
        out.sort(key=lambda r: r.get("max_z") or 0, reverse=True)
        return out

    @staticmethod
    def alert_summary() -> dict:
        """Return aggregated alert counts for dashboard KPI cards."""
        risk = AnomalyRepository.counts_by_risk()
        status = AnomalyRepository.counts_by_status()
        return {
            "total": AnomalyRepository.total_count(),
            "critical": risk.get("critical", 0),
            "high": risk.get("high", 0),
            "medium": risk.get("medium", 0),
            "low": risk.get("low", 0),
            "new": status.get("new", 0),
            "reviewed": status.get("reviewed", 0),
            "acknowledged": status.get("acknowledged", 0),
            "resolved": status.get("resolved", 0),
        }

    @staticmethod
    def list_alerts(*, risk_level: str | None = None, status: str | None = None,
                    anomaly_type: str | None = None,
                    date_from: date | str | None = None,
                    date_to: date | str | None = None,
                    limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        return AnomalyRepository.filter_alerts(
            risk_level=risk_level, status=status, anomaly_type=anomaly_type,
            date_from=date_from, date_to=date_to, limit=limit, offset=offset,
        )

    @staticmethod
    def get_alert(alert_id: int) -> dict | None:
        return AnomalyRepository.find_by_id(alert_id)

    @staticmethod
    def update_alert_status(alert_id: int, status: str, *,
                            reviewed_by: int | None = None) -> None:
        if status not in ("new", "reviewed", "acknowledged", "resolved"):
            raise ValueError("Invalid status")
        AnomalyRepository.update_status(alert_id, status, reviewed_by=reviewed_by)


def _detect_rule_based_peaks(series: list[dict], *, multiplier: float = 3.0) -> list[dict]:
    """Flag days where movement > multiplier * rolling average."""
    if len(series) < 7:
        return []
    values = [float(s["value"]) for s in series]
    peaks = []
    window = 7
    for i in range(window, len(values)):
        avg = sum(values[i - window:i]) / window
        if avg > 0 and values[i] > avg * multiplier:
            peaks.append({"day": series[i]["day"], "value": values[i], "avg": round(avg, 1)})
    return peaks


def _to_py(val):
    """Convert numpy types to native Python types for DB serialization."""
    if val is None:
        return None
    if hasattr(val, "item"):
        return val.item()
    return val
