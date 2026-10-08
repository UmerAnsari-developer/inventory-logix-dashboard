"""Anomaly detection service."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from ..ml.anomaly import detect_anomalies_enriched, detect_anomalies_isoforest, spc_zscore_analysis
from ..ml.anomaly_benchmark import run_catalogue_benchmark, SyntheticAnomalyInjector
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
            cur.execute("SELECT id, sku, name, current_stock, reorder_point FROM products WHERE deleted_at IS NULL ORDER BY id")
            products = list(cur.fetchall())
            if not products:
                return out
            product_ids = [p["id"] for p in products]
            cur.execute(
                """
                SELECT m.product_id, m.created_at::date AS day, m.type,
                       COALESCE(SUM(CASE WHEN m.type='IN' THEN m.quantity
                                          WHEN m.type='OUT' THEN -m.quantity
                                          ELSE 0 END), 0) AS total
                FROM movements m
                WHERE m.product_id = ANY(%s) AND m.created_at >= NOW() - INTERVAL '120 days'
                GROUP BY m.product_id, m.created_at::date, m.type
                ORDER BY m.product_id, day
                """,
                (product_ids,),
            )
            movement_rows = cur.fetchall()
        # Group movement rows by product_id
        from collections import defaultdict
        movements_by_product: dict[int, list] = defaultdict(list)
        for row in movement_rows:
            movements_by_product[row["product_id"]].append(row)
        for p in products:
            try:
                rows = movements_by_product.get(p["id"], [])
                series = [{"day": r["day"].isoformat(), "value": int(r["total"])} for r in rows]
                inv_pos = float(p.get("current_stock") or 0)
                safety = float(p.get("reorder_point") or 0) * 0.25
                rop = float(p.get("reorder_point") or 0)
                try:
                    from .settings_service import SettingsService
                    z_threshold = SettingsService.z_score_threshold()
                except Exception:
                    z_threshold = 3.0
                result = detect_anomalies_enriched(
                    series, product_id=p["id"], sku=p.get("sku", ""),
                    product_name=p.get("name", ""), contamination=contamination,
                    z_threshold=z_threshold, inventory_position=inv_pos,
                    safety_stock=safety, reorder_point=rop,
                )
                anomalies = result.get("anomalies", [])
                out.append({
                    "id": p["id"],
                    "sku": p["sku"],
                    "name": p["name"],
                    "model_used": ({"isolation_forest": "Isolation Forest", "zscore": "SPC (z-score)"}.get(
                        anomalies[0].get("detection_method"), "SPC (z-score)") if anomalies else None),
                    "anomaly_count": len(anomalies),
                    "max_z": max((abs(a.get("z_score") or 0) for a in anomalies), default=0),
                    "top_anomaly": anomalies[0] if anomalies else None,
                })
            except Exception as exc:
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

    @staticmethod
    def label_alert(alert_id: int, label: str, labeled_by: int) -> dict:
        """Confirm or reject an anomaly alert (human labeling for precision/recall)."""
        if label not in ("true_positive", "false_positive"):
            raise ValueError("label must be 'true_positive' or 'false_positive'")
        
        alert = AnomalyRepository.find_by_id(alert_id)
        if not alert:
            raise ValueError("Alert not found")
        
        # Update label and status
        new_status = "reviewed" if label == "true_positive" else "resolved"
        AnomalyRepository.update_label(alert_id, label, labeled_by, new_status)
        
        return {
            "alert_id": alert_id,
            "label": label,
            "status": new_status,
            "labeled_by": labeled_by,
        }

    @staticmethod
    def get_precision_recall() -> dict:
        """Compute empirical precision/recall from labeled data."""
        labeled = AnomalyRepository.get_labeled_alerts()
        
        # Group by risk_level and detection_method
        from collections import defaultdict
        by_risk = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
        by_method = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
        
        for alert in labeled:
            label = alert.get("label")
            risk = alert.get("risk_level", "low")
            method = alert.get("detection_method", "unknown")
            
            if label == "true_positive":
                by_risk[risk]["tp"] += 1
                by_method[method]["tp"] += 1
            elif label == "false_positive":
                by_risk[risk]["fp"] += 1
                by_method[method]["fp"] += 1
            # Note: We don't have explicit false negatives from labeling alone
            # Those would come from benchmark
        
        def compute_pr(stats):
            tp = stats["tp"]
            fp = stats["fp"]
            fn = stats["fn"]
            precision = tp / (tp + fp) if (tp + fp) > 0 else None
            recall = tp / (tp + fn) if (tp + fn) > 0 else None
            f1 = 2 * precision * recall / (precision + recall) if precision and recall and (precision + recall) > 0 else None
            return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}
        
        return {
            "by_risk_level": {k: compute_pr(v) for k, v in by_risk.items()},
            "by_detection_method": {k: compute_pr(v) for k, v in by_method.items()},
            "total_labeled": len(labeled),
        }

    @staticmethod
    def benchmark(contamination: float = 0.05) -> dict:
        """Run synthetic anomaly benchmark across the product catalogue."""
        # Get all products with sufficient history
        from ..database import get_cursor
        products_series = {}
        with get_cursor() as cur:
            cur.execute("""
                SELECT p.id, p.sku, p.name
                FROM products p
                WHERE p.deleted_at IS NULL
                AND EXISTS (
                    SELECT 1 FROM movements m 
                    WHERE m.product_id = p.id 
                    AND m.created_at >= NOW() - INTERVAL '120 days'
                )
                ORDER BY p.id
            """)
            products = cur.fetchall()
        
        if not products:
            return {"products_tested": 0, "message": "No products with sufficient history"}
        
        product_ids = [p["id"] for p in products]
        
        # Fetch movement data for all products in one query
        with get_cursor() as cur:
            cur.execute("""
                SELECT m.product_id, m.created_at::date AS day,
                       COALESCE(SUM(CASE WHEN m.type='OUT' THEN m.quantity ELSE 0 END), 0) AS total
                FROM movements m
                WHERE m.product_id = ANY(%s) AND m.created_at >= NOW() - INTERVAL '120 days'
                GROUP BY m.product_id, m.created_at::date
                ORDER BY m.product_id, day
            """, (product_ids,))
            movement_rows = cur.fetchall()
        
        from collections import defaultdict
        movements_by_product: dict[int, list] = defaultdict(list)
        for row in movement_rows:
            movements_by_product[row["product_id"]].append(row)
        
        for p in products:
            rows = movements_by_product.get(p["id"], [])
            if len(rows) >= 60:  # Minimum history for benchmark
                series = [{"day": r["day"].isoformat(), "value": int(r["total"])} for r in rows]
                products_series[p["id"]] = series
        
        if not products_series:
            return {"products_tested": 0, "message": "No products with sufficient history (need 60+ days)"}
        
        # Run benchmark
        def detector_func(series, contamination=contamination):
            return detect_anomalies_enriched(
                series,
                contamination=contamination,
                z_threshold=3.0,
            )
        
        result = run_catalogue_benchmark(products_series, detector_func, contamination)
        return result

    @staticmethod
    def compute_fatigue_metrics(days: int = 30) -> dict:
        """Compute alert fatigue metrics for the last N days."""
        from ..database import get_cursor
        with get_cursor() as cur:
            # Alerts per day by risk level
            cur.execute("""
                SELECT detected_at::date as metric_date,
                       risk_level,
                       COUNT(*) as alert_count,
                       COUNT(*) FILTER (WHERE status IN ('reviewed', 'acknowledged', 'resolved')) as reviewed_count,
                       COUNT(*) FILTER (WHERE status = 'resolved') as resolved_count,
                       AVG(EXTRACT(EPOCH FROM (reviewed_at - detected_at))/3600) FILTER (WHERE reviewed_at IS NOT NULL) as avg_resolve_hours
                FROM anomaly_log
                WHERE detected_at >= NOW() - INTERVAL '%s days'
                GROUP BY detected_at::date, risk_level
                ORDER BY metric_date
            """, (days,))
            daily = cur.fetchall()
            
            # Aggregate totals
            cur.execute("""
                SELECT 
                    COUNT(*) as total_alerts,
                    COUNT(*) FILTER (WHERE risk_level = 'critical') as critical_count,
                    COUNT(*) FILTER (WHERE risk_level = 'high') as high_count,
                    COUNT(*) FILTER (WHERE risk_level = 'medium') as medium_count,
                    COUNT(*) FILTER (WHERE risk_level = 'low') as low_count,
                    COUNT(*) FILTER (WHERE status IN ('reviewed', 'acknowledged', 'resolved')) as reviewed_count,
                    COUNT(*) FILTER (WHERE status = 'resolved') as resolved_count,
                    AVG(EXTRACT(EPOCH FROM (reviewed_at - detected_at))/3600) FILTER (WHERE reviewed_at IS NOT NULL) as avg_resolve_hours
                FROM anomaly_log
                WHERE detected_at >= NOW() - INTERVAL '%s days'
            """, (days,))
            totals = cur.fetchone()
        
        total = totals["total_alerts"] if totals else 0
        reviewed = totals["reviewed_count"] if totals else 0
        review_rate = round((reviewed / total * 100), 1) if total > 0 else 0
        
        # Build daily series
        daily_series = []
        for row in daily:
            daily_series.append({
                "date": row["metric_date"].isoformat() if hasattr(row["metric_date"], "isoformat") else str(row["metric_date"]),
                "risk_level": row["risk_level"],
                "alerts": row["alert_count"],
                "reviewed": row["reviewed_count"],
                "resolved": row["resolved_count"],
                "avg_resolve_hours": round(row["avg_resolve_hours"], 1) if row["avg_resolve_hours"] else None,
            })
        
        return {
            "period_days": days,
            "total_alerts": total,
            "by_risk": {
                "critical": totals["critical_count"] if totals else 0,
                "high": totals["high_count"] if totals else 0,
                "medium": totals["medium_count"] if totals else 0,
                "low": totals["low_count"] if totals else 0,
            },
            "reviewed_count": reviewed,
            "resolved_count": totals["resolved_count"] if totals else 0,
            "review_rate": review_rate,
            "avg_resolve_hours": round(totals["avg_resolve_hours"], 1) if totals and totals["avg_resolve_hours"] else None,
            "daily_series": daily_series,
        }


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