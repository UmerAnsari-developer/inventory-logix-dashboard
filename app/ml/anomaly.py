"""Anomaly detection: Isolation Forest + SPC z-score control limits."""
from __future__ import annotations

import logging
import math
from statistics import mean, pstdev
from typing import Iterable

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover
    from sklearn.ensemble import IsolationForest
    _HAS_SKLEARN = True
except Exception:
    _HAS_SKLEARN = False


def _stats(series: list[float]) -> tuple[float, float]:
    if len(series) < 2:
        return series[0] if series else 0.0, 1.0
    return mean(series), max(pstdev(series), 0.5)


def detect_anomalies_isoforest(series: list[dict], *, contamination: float = 0.05,
                               z_threshold: float = 3.0) -> dict:
    """Detect anomalies using sklearn IsolationForest; degrade to z-score otherwise."""
    if not series:
        return {"anomalies": [], "model": "none"}
    values = [float(s["value"]) for s in series]
    anomalies: list[dict] = []
    model_used = "zscore"

    if _HAS_SKLEARN and len(values) >= 14:
        try:
            import numpy as np
            arr = np.array(values).reshape(-1, 1)
            forest = IsolationForest(contamination=contamination, random_state=42, n_estimators=80)
            forest.fit(arr)
            preds = forest.predict(arr)
            scores = forest.decision_function(arr)
            baseline_mu, baseline_sigma = _stats(values)
            for idx, label in enumerate(preds):
                if label == -1:
                    z = (values[idx] - baseline_mu) / baseline_sigma if baseline_sigma else 0
                    anomalies.append({
                        "day": series[idx]["day"],
                        "value": values[idx],
                        "z_score": round(z, 2),
                        "confidence": round(min(99, max(60, abs(scores[idx]) * 35 + 60)), 1),
                        "type": "spike" if z > 0 else "drop",
                        "description": (
                            f"Unusual {'surge' if z > 0 else 'drop'} on {series[idx]['day']}"
                            f" — value {values[idx]} ({z:+.2f}σ)."
                        ),
                    })
            model_used = "isolation_forest"
        except Exception as exc:  # pragma: no cover
            LOGGER.warning("IsolationForest failed: %s", exc)
            anomalies = []

    if not anomalies:
        mu, sigma = _stats(values)
        for idx, value in enumerate(values):
            z = (value - mu) / sigma
            if abs(z) >= z_threshold:
                anomalies.append({
                    "day": series[idx]["day"],
                    "value": value,
                    "z_score": round(z, 2),
                    "confidence": min(95, abs(z) * 30 + 55),
                    "type": "spike" if z > 0 else "drop",
                    "description": (
                        f"{'Spike' if z > 0 else 'Drop'} detected: {value} units "
                        f"({z:+.2f}σ vs baseline {mu:.1f})."
                    ),
                })
        model_used = "zscore"

    anomalies.sort(key=lambda a: abs(a.get("z_score") or 0), reverse=True)
    return {"anomalies": anomalies[:25], "model": model_used, "count": len(anomalies),
            "threshold": z_threshold}


def spc_zscore_analysis(series: list[dict], *, limit: float = 3.0) -> dict:
    """Compute Statistical Process Control chart data: mean, sigma, UCL/LCL."""
    values = [float(s["value"]) for s in series]
    if not values:
        return {"mean": 0, "sigma": 0, "ucl": 0, "lcl": 0, "values": []}
    mu, sigma = _stats(values)
    return {
        "mean": round(mu, 2),
        "sigma": round(sigma, 2),
        "ucl": round(mu + limit * sigma, 2),
        "lcl": round(max(0, mu - limit * sigma), 2),
        "values": values,
        "limit": limit,
    }


# ---------------------------------------------------------------------------
# Enhanced anomaly alerting — structured business alerts
# ---------------------------------------------------------------------------

# Risk-level thresholds based on z-score magnitude
_RISK_THRESHOLDS = {"low": 2.0, "medium": 3.0, "high": 4.0}


def calculate_risk_level(z_score: float, *,
                         inventory_position: float | None = None,
                         safety_stock: float | None = None,
                         reorder_point: float | None = None,
                         anomaly_type: str = "spike") -> str:
    """Map z-score + inventory context to a business risk level.

    Risk escalates when:
    - High absolute z-score
    - Stock below safety stock or ROP (demand spike risk)
    - Demand drop while stock is healthy (may mask obsolescence)
    """
    abs_z = abs(z_score or 0)

    # Base level from z-score
    if abs_z >= _RISK_THRESHOLDS["high"]:
        level = "critical"
    elif abs_z >= _RISK_THRESHOLDS["medium"]:
        level = "high"
    elif abs_z >= _RISK_THRESHOLDS["low"]:
        level = "medium"
    else:
        level = "low"

    # Inventory context: escalate if stock is dangerously low on demand spikes
    if anomaly_type == "spike" and inventory_position is not None and safety_stock is not None:
        if inventory_position <= safety_stock * 0.5:
            if level == "medium":
                level = "high"
            elif level == "low":
                level = "medium"
    if reorder_point is not None and inventory_position is not None:
        if inventory_position <= 0:
            level = "critical"
        elif inventory_position <= reorder_point * 0.1:
            if level in ("low", "medium"):
                level = "high"

    return level


def generate_recommendation(anomaly_type: str, z_score: float, *,
                            risk_level: str = "low",
                            product_name: str = "",
                            inventory_position: float | None = None,
                            safety_stock: float | None = None,
                            reorder_point: float | None = None,
                            avg_daily_demand: float | None = None,
                            lead_days: int | None = None) -> str:
    """Generate a concise, actionable recommendation for a single anomaly."""
    risk = risk_level or "low"
    name = product_name or "product"

    if anomaly_type == "spike":
        if risk == "critical":
            return (
                f"Urgent: {name} demand spike exceeds normal capacity. "
                f"Review safety stock and consider emergency replenishment."
            )
        if risk == "high":
            return (
                f"HIGH: {name} demand surge detected. Verify if promotional or seasonal. "
                f"Consider increasing order quantity or expediting pending POs."
            )
        if risk == "medium":
            return (
                f"Monitor {name} demand increase. "
                f"Check pending POs and consider adjusting reorder point."
            )
        return f"Minor demand variation on {name}. Continue monitoring."

    # demand drop
    if risk == "critical":
        return (
            f"Urgent: {name} demand collapsed. "
            f"Investigate root cause — possible product issue or market shift."
        )
    if risk == "high":
        return (
            f"HIGH: {name} demand drop significant. "
            f"Review upcoming POs to prevent overstock and consider pausing auto-reorder."
        )
    if risk == "medium":
        return (
            f"Monitor {name} declining demand. "
            f"Verify if seasonal trend and adjust forecasts accordingly."
        )
    return f"Minor {name} demand decrease. Track next cycle."


def compute_deviation(observed: float, expected: float) -> float | None:
    """Compute percentage deviation: ((observed - expected) / expected) * 100."""
    if not expected:
        return None
    return round(((observed - expected) / abs(expected)) * 100, 2)


def enrich_anomaly(anomaly: dict, *,
                    mu: float = 0, sigma: float = 1,
                    inventory_position: float | None = None,
                    safety_stock: float | None = None,
                    reorder_point: float | None = None,
                    product_name: str = "",
                    sku: str = "",
                    detection_method: str = "zscore") -> dict:
    """Add structured business fields to a single anomaly dict."""
    z = anomaly.get("z_score", 0)
    observed = anomaly.get("value", 0)
    a_type = anomaly.get("type", "spike")
    expected = mu

    risk = calculate_risk_level(
        z,
        inventory_position=inventory_position,
        safety_stock=safety_stock,
        reorder_point=reorder_point,
        anomaly_type=a_type,
    )
    dev = compute_deviation(observed, expected)
    rec = generate_recommendation(
        a_type, z,
        risk_level=risk,
        product_name=product_name,
        inventory_position=inventory_position,
        safety_stock=safety_stock,
        reorder_point=reorder_point,
    )
    return {
        **anomaly,
        "sku": sku,
        "expected_value": round(mu, 3),
        "observed_value": observed,
        "deviation_pct": dev,
        "metric": "quantity",
        "risk_level": risk,
        "detection_method": detection_method,
        "recommended_action": rec,
        "status": "new",
    }


def enrich_anomalies(raw_anomalies: list[dict], *,
                     mu: float = 0, sigma: float = 1,
                     inventory_position: float | None = None,
                     safety_stock: float | None = None,
                     reorder_point: float | None = None,
                     product_name: str = "",
                     sku: str = "",
                     model: str = "zscore") -> list[dict]:
    """Enrich all raw anomalies from detect_anomalies_isoforest()."""
    return [
        enrich_anomaly(
            a,
            mu=mu, sigma=sigma,
            inventory_position=inventory_position,
            safety_stock=safety_stock,
            reorder_point=reorder_point,
            product_name=product_name,
            sku=sku,
            detection_method=model,
        )
        for a in raw_anomalies
    ]


def detect_anomalies_enriched(series: list[dict], *,
                               product_id: int = 0,
                               sku: str = "",
                               product_name: str = "",
                               contamination: float = 0.05,
                               z_threshold: float = 3.0,
                               inventory_position: float | None = None,
                               safety_stock: float | None = None,
                               reorder_point: float | None = None,
                               forecast_values: list[float] | None = None,
                               rule_based_peaks: list[dict] | None = None) -> dict:
    """Run detection and return enriched structured business alerts.

    Combines Isolation Forest / z-score with optional forecast-deviation
    and rule-based signals, then deduplicates by day.
    """
    result = detect_anomalies_isoforest(series, contamination=contamination,
                                        z_threshold=z_threshold)
    mu, sigma = _stats([float(s["value"]) for s in series]) if series else (0, 1)

    enriched = enrich_anomalies(
        result.get("anomalies", []),
        mu=mu, sigma=sigma,
        inventory_position=inventory_position,
        safety_stock=safety_stock,
        reorder_point=reorder_point,
        product_name=product_name,
        sku=sku,
        model=result.get("model", "zscore"),
    )

    # --- Forecast-deviation layer: compare actual vs forecasted demand ---
    if forecast_values and series:
        last_n = min(len(forecast_values), len(series))
        for i in range(last_n):
            actual = float(series[-(last_n - i)]["value"])
            expected_f = float(forecast_values[i]) if i < len(forecast_values) else mu
            if expected_f > 0:
                dev_f = abs(actual - expected_f) / expected_f
                if dev_f > 0.4:  # 40% deviation threshold
                    day_label = series[-(last_n - i)]["day"]
                    if not any(a["day"] == day_label for a in enriched):
                        z_f = (actual - mu) / sigma if sigma else 0
                        a_type_f = "spike" if actual > expected_f else "drop"
                        risk_f = calculate_risk_level(
                            z_f,
                            inventory_position=inventory_position,
                            safety_stock=safety_stock,
                            reorder_point=reorder_point,
                            anomaly_type=a_type_f,
                        )
                        dev_pct_f = compute_deviation(actual, expected_f)
                        rec_f = generate_recommendation(
                            a_type_f, z_f, risk_level=risk_f,
                            product_name=product_name,
                        )
                        enriched.append({
                            "day": day_label,
                            "value": actual,
                            "z_score": round(z_f, 2),
                            "confidence": round(min(95, dev_f * 80 + 55), 1),
                            "type": a_type_f,
                            "description": (
                                f"Forecast deviation: actual {actual} vs expected {expected_f:.0f} "
                                f"({dev_f*100:.0f}% off) on {day_label}."
                            ),
                            "sku": sku,
                            "expected_value": round(expected_f, 3),
                            "observed_value": actual,
                            "deviation_pct": dev_pct_f,
                            "metric": "quantity",
                            "risk_level": risk_f,
                            "detection_method": "forecast_deviation",
                            "recommended_action": rec_f,
                            "status": "new",
                        })

    # --- Rule-based layer: daily movement > 3x rolling average ---
    if rule_based_peaks:
        for peak in rule_based_peaks:
            day_p = peak.get("day", "")
            val_p = peak.get("value", 0)
            if not any(a["day"] == day_p for a in enriched):
                z_p = (val_p - mu) / sigma if sigma else 0
                risk_p = calculate_risk_level(
                    z_p,
                    inventory_position=inventory_position,
                    safety_stock=safety_stock,
                    reorder_point=reorder_point,
                    anomaly_type="spike",
                )
                dev_p = compute_deviation(val_p, mu)
                rec_p = generate_recommendation(
                    "spike", z_p, risk_level=risk_p,
                    product_name=product_name,
                )
                enriched.append({
                    "day": day_p,
                    "value": val_p,
                    "z_score": round(z_p, 2),
                    "confidence": round(min(95, abs(z_p) * 25 + 60), 1),
                    "type": "spike",
                    "description": (
                        f"Rule-based spike: {val_p} units on {day_p} "
                        f"(>{3.0:.0f}x rolling average {mu:.0f})."
                    ),
                    "sku": sku,
                    "expected_value": round(mu, 3),
                    "observed_value": val_p,
                    "deviation_pct": dev_p,
                    "metric": "quantity",
                    "risk_level": risk_p,
                    "detection_method": "rule_based",
                    "recommended_action": rec_p,
                    "status": "new",
                })

    # Deduplicate by day — keep highest-risk entry per day
    seen: dict[str, dict] = {}
    _risk_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    for alert in enriched:
        d = alert["day"]
        if d not in seen or _risk_order.get(alert["risk_level"], 0) > _risk_order.get(seen[d]["risk_level"], 0):
            seen[d] = alert
    enriched = sorted(seen.values(), key=lambda a: abs(a.get("z_score", 0)), reverse=True)

    result["anomalies"] = enriched[:25]
    result["count"] = len(enriched)
    return result
