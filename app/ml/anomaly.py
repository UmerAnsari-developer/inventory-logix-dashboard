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
