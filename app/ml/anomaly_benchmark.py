"""Synthetic anomaly benchmarking for anomaly detection validation.

Injects known anomalies into historical data and evaluates detection
precision, recall, F1, and PR-AUC per detection method.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

from .anomaly import detect_anomalies_enriched, _stats


@dataclass
class InjectedAnomaly:
    """Represents a synthetic anomaly injected into the data."""
    day_index: int
    day_label: str
    original_value: float
    injected_value: float
    anomaly_type: str  # "spike", "drop", "level_shift", "trend_change"
    magnitude: float  # In standard deviations


@dataclass
class DetectionMatch:
    """Result of matching a detected anomaly to an injected one."""
    injected: InjectedAnomaly
    detected: dict | None
    matched: bool
    detection_method: str | None


@dataclass
class BenchmarkResult:
    """Aggregated benchmark results for a detection method."""
    method: str
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    precision: float | None
    recall: float | None
    f1: float | None
    pr_auc: float | None


class SyntheticAnomalyInjector:
    """Injects synthetic anomalies into time series data."""
    
    def __init__(self, random_seed: int = 42):
        self.random = random.Random(random_seed)
    
    def inject_spikes(
        self,
        series: list[dict],
        num_spikes: int,
        magnitude_range: tuple[float, float] = (3.0, 5.0),
    ) -> list[InjectedAnomaly]:
        """Inject positive spikes (sudden demand surges)."""
        if len(series) < 14:
            return []
        
        values = [float(s["value"]) for s in series]
        mu, sigma = _stats(values)
        
        # Choose random positions (avoid first/last 7 days)
        valid_indices = list(range(7, len(series) - 7))
        if len(valid_indices) < num_spikes:
            num_spikes = len(valid_indices)
        
        spike_indices = self.random.sample(valid_indices, num_spikes)
        injected = []
        
        for idx in spike_indices:
            original = values[idx]
            magnitude = self.random.uniform(*magnitude_range)
            injected_value = original + magnitude * sigma
            injected_value = max(0, injected_value)
            
            # Modify the series in place
            series[idx]["value"] = injected_value
            
            injected.append(InjectedAnomaly(
                day_index=idx,
                day_label=series[idx]["day"],
                original_value=original,
                injected_value=injected_value,
                anomaly_type="spike",
                magnitude=magnitude,
            ))
        
        return injected
    
    def inject_drops(
        self,
        series: list[dict],
        num_drops: int,
        magnitude_range: tuple[float, float] = (3.0, 5.0),
    ) -> list[InjectedAnomaly]:
        """Inject negative drops (sudden demand decreases)."""
        if len(series) < 14:
            return []
        
        values = [float(s["value"]) for s in series]
        mu, sigma = _stats(values)
        
        valid_indices = list(range(7, len(series) - 7))
        if len(valid_indices) < num_drops:
            num_drops = len(valid_indices)
        
        drop_indices = self.random.sample(valid_indices, num_drops)
        injected = []
        
        for idx in drop_indices:
            original = values[idx]
            magnitude = self.random.uniform(*magnitude_range)
            injected_value = max(0, original - magnitude * sigma)
            
            series[idx]["value"] = injected_value
            
            injected.append(InjectedAnomaly(
                day_index=idx,
                day_label=series[idx]["day"],
                original_value=original,
                injected_value=injected_value,
                anomaly_type="drop",
                magnitude=magnitude,
            ))
        
        return injected
    
    def inject_level_shift(
        self,
        series: list[dict],
        position: int | None = None,
        magnitude_sigma: float = 2.0,
    ) -> list[InjectedAnomaly]:
        """Inject a persistent level shift (step change)."""
        if len(series) < 21:
            return []
        
        values = [float(s["value"]) for s in series]
        mu, sigma = _stats(values)
        
        if position is None:
            # Random position in middle third
            start = len(series) // 3
            end = 2 * len(series) // 3
            position = self.random.randint(start, end)
        
        shift = magnitude_sigma * sigma * (1 if self.random.random() > 0.5 else -1)
        injected = []
        
        for idx in range(position, len(series)):
            original = values[idx]
            injected_value = max(0, original + shift)
            series[idx]["value"] = injected_value
            
            injected.append(InjectedAnomaly(
                day_index=idx,
                day_label=series[idx]["day"],
                original_value=original,
                injected_value=injected_value,
                anomaly_type="level_shift",
                magnitude=abs(shift) / sigma if sigma else 0,
            ))
        
        return injected
    
    def inject_trend_change(
        self,
        series: list[dict],
        position: int | None = None,
        slope_change: float = 0.5,
    ) -> list[InjectedAnomaly]:
        """Inject a trend change (gradual slope modification)."""
        if len(series) < 21:
            return []
        
        values = [float(s["value"]) for s in series]
        
        if position is None:
            start = len(series) // 3
            end = 2 * len(series) // 3
            position = self.random.randint(start, end)
        
        injected = []
        for idx in range(position, len(series)):
            original = values[idx]
            # Add cumulative trend change
            days_since = idx - position
            change = slope_change * days_since
            injected_value = max(0, original + change)
            series[idx]["value"] = injected_value
            
            injected.append(InjectedAnomaly(
                day_index=idx,
                day_label=series[idx]["day"],
                original_value=original,
                injected_value=injected_value,
                anomaly_type="trend_change",
                magnitude=abs(slope_change),
            ))
        
        return injected


def match_detections_to_injected(
    detected_anomalies: list[dict],
    injected_anomalies: list[InjectedAnomaly],
    tolerance_days: int = 1,
) -> list[DetectionMatch]:
    """Match detected anomalies to injected anomalies by day."""
    matches = []
    detected_by_day = {a["day"]: a for a in detected_anomalies}
    
    for injected in injected_anomalies:
        matched = False
        detected = None
        method = None
        
        # Check exact day and neighboring days
        for offset in range(-tolerance_days, tolerance_days + 1):
            check_idx = injected.day_index + offset
            if 0 <= check_idx < len(detected_by_day):
                day_label = list(detected_by_day.keys())[list(detected_by_day.values()).index(
                    next((v for k, v in detected_by_day.items() if k == injected.day_label), None)
                )] if any(k == injected.day_label for k in detected_by_day) else None
                
                # Simpler: check if day_label exists in detected
                if injected.day_label in detected_by_day:
                    detected = detected_by_day[injected.day_label]
                    matched = True
                    method = detected.get("detection_method", "unknown")
                    break
        
        matches.append(DetectionMatch(
            injected=injected,
            detected=detected,
            matched=matched,
            detection_method=method,
        ))
    
    return matches


def compute_method_metrics(
    matches: list[DetectionMatch],
    method: str,
    total_normal_days: int,
) -> BenchmarkResult:
    """Compute precision, recall, F1 for a specific detection method."""
    tp = sum(1 for m in matches if m.matched and m.detection_method == method)
    fp = sum(1 for m in matches if not m.matched and m.detected and m.detected.get("detection_method") == method)
    fn = sum(1 for m in matches if not m.matched and m.injected.anomaly_type in ("spike", "drop"))
    tn = total_normal_days - fp  # Approximate
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall and (precision + recall) > 0 else None
    
    # PR-AUC approximation (single point)
    pr_auc = f1 if f1 else 0.0
    
    return BenchmarkResult(
        method=method,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        true_negatives=max(0, tn),
        precision=precision,
        recall=recall,
        f1=f1,
        pr_auc=pr_auc,
    )


def run_benchmark_on_series(
    series: list[dict],
    detector_func: Callable,
    injector: SyntheticAnomalyInjector,
    num_spikes: int = 5,
    num_drops: int = 3,
    inject_level_shift: bool = True,
    inject_trend_change: bool = True,
) -> dict:
    """Run benchmark on a single product's time series.
    
    Returns per-method metrics and per-type breakdown.
    """
    # Create a copy for injection
    import copy
    test_series = copy.deepcopy(series)
    
    # Inject anomalies
    all_injected = []
    all_injected.extend(injector.inject_spikes(test_series, num_spikes))
    all_injected.extend(injector.inject_drops(test_series, num_drops))
    
    if inject_level_shift:
        all_injected.extend(injector.inject_level_shift(test_series))
    if inject_trend_change:
        all_injected.extend(injector.inject_trend_change(test_series))
    
    # Run detection on injected series
    result = detector_func(test_series)
    detected = result.get("anomalies", [])
    
    # Match detections to injected
    matches = match_detections_to_injected(detected, all_injected)
    
    # Compute metrics per detection method
    methods = set()
    for a in detected:
        methods.add(a.get("detection_method", "unknown"))
    
    total_normal_days = len(series) - len(all_injected)
    
    by_method = {}
    for method in methods:
        by_method[method] = compute_method_metrics(matches, method, total_normal_days)
    
    # By anomaly type
    by_type = {}
    for anomaly_type in ["spike", "drop", "level_shift", "trend_change"]:
        type_matches = [m for m in matches if m.injected.anomaly_type == anomaly_type]
        if type_matches:
            tp = sum(1 for m in type_matches if m.matched)
            fn = sum(1 for m in type_matches if not m.matched)
            by_type[anomaly_type] = {
                "injected": len(type_matches),
                "detected": tp,
                "missed": fn,
                "recall": tp / len(type_matches) if type_matches else 0,
            }
    
    return {
        "total_injected": len(all_injected),
        "total_detected": len(detected),
        "by_method": {k: {
            "precision": v.precision,
            "recall": v.recall,
            "f1": v.f1,
            "pr_auc": v.pr_auc,
            "tp": v.true_positives,
            "fp": v.false_positives,
            "fn": v.false_negatives,
        } for k, v in by_method.items()},
        "by_type": by_type,
        "matches": [
            {
                "day": m.injected.day_label,
                "type": m.injected.anomaly_type,
                "magnitude": m.injected.magnitude,
                "matched": m.matched,
                "method": m.detection_method,
            }
            for m in matches
        ],
    }


def run_catalogue_benchmark(
    products_series: dict[int, list[dict]],
    detector_func: Callable,
    contamination: float = 0.05,
    min_history_days: int = 60,
) -> dict:
    """Run benchmark across multiple products.
    
    Args:
        products_series: Dict mapping product_id -> series data
        detector_func: Function that takes series and returns detection result
        contamination: Contamination parameter for Isolation Forest
        min_history_days: Minimum history required for benchmark
    
    Returns aggregated benchmark results.
    """
    injector = SyntheticAnomalyInjector()
    all_results = []
    
    for product_id, series in products_series.items():
        if len(series) < min_history_days:
            continue
        
        # Create detector with fixed contamination
        def product_detector(s):
            return detector_func(s, contamination=contamination)
        
        result = run_benchmark_on_series(series, product_detector, injector)
        result["product_id"] = product_id
        all_results.append(result)
    
    if not all_results:
        return {"products_tested": 0, "message": "No products with sufficient history"}
    
    # Aggregate across products
    all_methods = set()
    for r in all_results:
        all_methods.update(r["by_method"].keys())
    
    aggregated_methods = {}
    for method in all_methods:
        precisions = [r["by_method"][method]["precision"] for r in all_results 
                     if method in r["by_method"] and r["by_method"][method]["precision"] is not None]
        recalls = [r["by_method"][method]["recall"] for r in all_results
                  if method in r["by_method"] and r["by_method"][method]["recall"] is not None]
        f1s = [r["by_method"][method]["f1"] for r in all_results
              if method in r["by_method"] and r["by_method"][method]["f1"] is not None]
        
        aggregated_methods[method] = {
            "precision": sum(precisions) / len(precisions) if precisions else None,
            "recall": sum(recalls) / len(recalls) if recalls else None,
            "f1": sum(f1s) / len(f1s) if f1s else None,
            "pr_auc": sum(f1s) / len(f1s) if f1s else None,  # Approximation
            "products_with_data": len(precisions),
        }
    
    # Aggregate by type
    all_types = set()
    for r in all_results:
        all_types.update(r["by_type"].keys())
    
    aggregated_types = {}
    for atype in all_types:
        total_injected = sum(r["by_type"][atype]["injected"] for r in all_results if atype in r["by_type"])
        total_detected = sum(r["by_type"][atype]["detected"] for r in all_results if atype in r["by_type"])
        aggregated_types[atype] = {
            "injected": total_injected,
            "detected": total_detected,
            "recall": total_detected / total_injected if total_injected > 0 else 0,
        }
    
    return {
        "products_tested": len(all_results),
        "total_injected": sum(r["total_injected"] for r in all_results),
        "total_detected": sum(r["total_detected"] for r in all_results),
        "by_method": aggregated_methods,
        "by_type": aggregated_types,
    }