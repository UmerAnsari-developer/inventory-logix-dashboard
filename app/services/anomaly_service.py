"""Anomaly detection service."""
from __future__ import annotations

import logging

from ..ml.anomaly import detect_anomalies_isoforest, spc_zscore_analysis
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
        result = detect_anomalies_isoforest(series, contamination=contamination,
                                            z_threshold=z_threshold)
        result.update(spc_zscore_analysis(series, limit=z_threshold))
        def _to_py(val):
            """Convert numpy types to native Python types for DB serialization."""
            if hasattr(val, "item"):  # numpy scalar
                return val.item()
            return val

        for anomaly in result.get("anomalies", []):
            AnomalyRepository.save(
                product_id=product_id,
                anomaly_type=anomaly.get("type", "spike"),
                z_score=_to_py(anomaly.get("z_score")),
                confidence=_to_py(anomaly.get("confidence")),
                description=anomaly.get("description"),
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
