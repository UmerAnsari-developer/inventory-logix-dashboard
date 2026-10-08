# Batch 1 Research Report: Critical ML Validation Issues

## Batch 1 Issue Summary

| Issue ID | Title | Severity | Priority | Category |
|----------|-------|----------|----------|----------|
| **GAP-001** | Forecast accuracy claims unverified | Critical | P0 | Forecasting |
| **GAP-002** | Anomaly detection has no ground-truth validation | Critical | P0 | Anomaly Detection |

---

## Project Areas Affected

### GAP-001: Forecast Accuracy
- **Files**: `app/ml/forecasting.py`, `app/services/forecast_service.py`, `app/services/monitoring_service.py`, `app/monitoring/metrics.py`, `app/monitoring/degradation.py`, `app/repositories/monitoring_repo.py`, `app/routes/ai.py`, `app/templates/ai/forecast.html`, `app/static/js/ai-features.js`
- **Database**: `forecast_cache`, `forecast_predictions`, `forecast_monitoring_metrics`, `model_monitoring_alerts`
- **API Endpoints**: `/ai/forecast/run`, `/ai/forecast/portfolio`, `/ai/monitoring/*`

### GAP-002: Anomaly Detection Validation
- **Files**: `app/ml/anomaly.py`, `app/services/anomaly_service.py`, `app/repositories/forecast_repo.py` (AnomalyRepository), `app/routes/ai.py`, `app/templates/ai/anomaly.html`, `app/static/js/ai-features.js`
- **Database**: `anomaly_log`
- **API Endpoints**: `/ai/anomaly/run`, `/ai/anomaly/portfolio`, `/ai/anomaly/alerts`, `/ai/anomaly/summary`

---

## Evidence for Each Issue

### GAP-001: Forecast Accuracy Claims Unverified

#### Verified Evidence

1. **In-sample evaluation only** (`app/services/forecast_service.py:46-107`):
   - `_update_monitoring()` evaluates predictions on the **last 30 days of training history** (lines 56-63)
   - Uses a 7-day moving average as the "predicted" value for historical days (line 67), not the actual model
   - Computes metrics on the same data used for training — **no chronological train/test split**

2. **Portfolio uses 7-day MA, not fitted model** (`app/services/forecast_service.py:112-168`):
   - Line 113: "Lightweight forecast summary — uses 7-day moving average, no model fitting"
   - Line 160: Returns `model` column with Prophet/ARIMA/Ensemble label but computes baseline from MA
   - Accuracy computed on active-demand days only using MA baseline (lines 152-155)

3. **Moving average fallback hardcodes accuracy** (`app/ml/forecasting.py:63`):
   - `_moving_average_forecast()` returns `"accuracy": 78.0` (hardcoded)
   - Prophet/ARIMA compute in-sample MAPE on fitted values (lines 90-92, 134-136)

4. **Tests only verify in-sample accuracy** (`tests/test_ml.py:134-145`):
   - `test_prophet_boundary_len_fourteen()` checks `accuracy == pytest.approx(65.15)` — in-sample
   - `test_arima_boundary_len_twenty()` checks `accuracy == pytest.approx(70.09)` — in-sample
   - `test_ensemble_exact_values()` checks `accuracy == pytest.approx(78.0)` — MA fallback

5. **Monitoring baseline is first evaluation window, not training baseline** (`app/repositories/monitoring_repo.py:170-179`):
   - `baseline_metrics()` returns oldest metrics entry (first evaluation period)
   - Not a fixed baseline from model promotion/training time

#### Root Cause Analysis

| Root Cause | Evidence | Classification |
|------------|----------|----------------|
| No chronological train/test split | `_update_monitoring()` uses last 30 days of training history for evaluation | **Verified** |
| Evaluation uses MA baseline, not model predictions | Line 67: `predicted = sum(values[start:i]) / max(1, i - start)` | **Verified** |
| Portfolio endpoint doesn't run actual models | Comment line 113: "uses 7-day moving average, no model fitting" | **Verified** |
| No rolling-origin/walk-forward backtesting framework | Absent from codebase; no backtest orchestrator | **Verified** |
| Accuracy metric undefined on zero-demand days | `calculate_mape()` excludes zero-demand days (metrics.py:52-54) | **Verified** |

#### Risks of Leaving Unfixed
- Business decisions (reorder, safety stock) based on unverified accuracy → stockouts or overstock
- Marketing claims (>90% accuracy) have zero out-of-sample evidence
- Model degradation detection compares recent window to recent window — misses gradual drift
- Users trust per-product Prophet/ARIMA forecasts that don't exist in portfolio view

---

### GAP-002: Anomaly Detection Has No Ground-Truth Validation

#### Verified Evidence

1. **No labeled anomalies exist** (`app/ml/anomaly.py`, `app/services/anomaly_service.py`):
   - `detect_anomalies_enriched()` combines Isolation Forest, z-score, forecast deviation, rule-based peaks
   - Deduplicates by day (keeps highest risk) — loses multi-method confirmation signal
   - No human labeling workflow; `anomaly_log.status` field exists (new/reviewed/acknowledged/resolved) but no UI for labeling

2. **No precision/recall/F1 measurement** (`tests/test_ml.py:182-392`):
   - Tests verify deterministic output (`test_isoforest_deterministic_output()`)
   - Tests verify structure (`test_detect_enriched_returns_structured_alerts()`)
   - **No tests measure detection quality against ground truth**

3. **Synthetic confidence heuristics** (`app/ml/anomaly.py:52, 73, 336, 376`):
   - Isolation Forest: `confidence = round(min(99, max(60, abs(scores[idx]) * 35 + 60)), 1)` (line 52)
   - z-score: `confidence = min(95, abs(z) * 30 + 55)` (line 73)
   - Forecast deviation: `confidence = round(min(95, dev_f * 80 + 55), 1)` (line 336)
   - Rule-based: `confidence = round(min(95, abs(z_p) * 25 + 60), 1)` (line 376)
   - These are **heuristic formulas, not calibrated probabilities**

4. **Risk levels uncalibrated** (`app/ml/anomaly.py:111-149`):
   - `calculate_risk_level()` uses hardcoded z-score thresholds (2.0, 3.0, 4.0)
   - Escalation logic based on inventory position (heuristic multipliers: 0.5, 0.1)
   - No validation that risk levels correspond to actual business outcomes

5. **Hardcoded detection thresholds** (`app/ml/anomaly.py:315, 380`):
   - Forecast deviation: 40% threshold (line 315) — not configurable, not tuned
   - Rule-based peaks: 3× rolling average multiplier (line 380) — hardcoded

#### Root Cause Analysis

| Root Cause | Evidence | Classification |
|------------|----------|----------------|
| No labeling pipeline | `AnomalyRepository` has status field but no UI for review/confirm/reject | **Verified** |
| No evaluation framework | Tests only check deterministic output, not detection quality | **Verified** |
| No synthetic benchmark | No injected anomalies with known ground truth | **Verified** |
| Confidence is heuristic, not probabilistic | Formulas in anomaly.py lines 52, 73, 336, 376 | **Verified** |
| Risk levels not validated against outcomes | `calculate_risk_level()` uses hardcoded thresholds | **Verified** |

#### Risks of Leaving Unfixed
- Operations team wastes time on false positives or misses real anomalies
- "Risk level" is uncalibrated theater — cannot prioritize effectively
- Alert fatigue unknown (no tracking of alerts/day, review rate, time-to-resolve)
- Cannot claim detection quality without precision/recall/F1

---

## Dependencies Between Batch 1 Issues

| Dependency | Description |
|------------|-------------|
| **Shared monitoring infrastructure** | Both issues use `app/monitoring/metrics.py` for evaluation metrics |
| **Shared data source** | Both use `MovementRepository.daily_for_product()` for historical data |
| **Shared caching** | Both portfolio endpoints use `_portfolio_cache` (TTLCache, 1hr TTL) |
| **Forecast integration in anomaly** | `AnomalyService.run_for_product_enriched()` calls `forecast_ensemble()` (line 99-103) |
| **Common test patterns** | Both need synthetic data generation for benchmarking |

**Key Insight**: Fixing GAP-001 (backtesting framework) creates infrastructure that can be reused for GAP-002 (anomaly benchmarking). The rolling-origin framework can generate holdout periods for both forecast evaluation and anomaly injection.

---

## Existing Implementation Behavior

### Forecast Service (`ForecastService.run()`)
1. Fetches 180 days of OUT movements for product
2. Runs selected model (Prophet/ARIMA/Ensemble) or falls back to MA
3. Saves result to `forecast_cache` (upsert on product_id, model, horizon)
4. Calls `_update_monitoring()` which:
   - Creates "predictions" for last 30 days using 7-day MA (not model)
   - Evaluates against actuals from same 30 days
   - Computes MAE, MAPE, RMSE, bias, error_std
   - Compares to baseline (first evaluation window)
   - Saves to `forecast_monitoring_metrics`

### Forecast Portfolio (`ForecastService.portfolio()`)
1. Queries all products + 90 days of movements
2. Computes 7-day MA per product
3. Labels with selected model name (Prophet/ARIMA/Ensemble)
4. Returns accuracy computed on active-demand days only
5. Cached 1 hour per (horizon, model) combination

### Anomaly Service (`AnomalyService.run_for_product_enriched()`)
1. Fetches 120 days of movements (net IN/OUT/ADJUSTMENT)
2. Runs `detect_anomalies_enriched()` combining:
   - Isolation Forest (or z-score fallback)
   - Forecast deviation layer (if forecast available, 40% threshold)
   - Rule-based peaks (3× rolling average)
3. Deduplicates by day (keeps highest risk)
4. Adds SPC chart data (mean, sigma, UCL/LCL)
5. Persists to `anomaly_log` with risk_level, detection_method, recommended_action

### Anomaly Portfolio (`AnomalyService.portfolio()`)
1. Queries all products + 120 days of movements
2. Runs `detect_anomalies_enriched()` per product (scales O(n))
3. Returns summary with model column showing first anomaly's detection_method
4. Cached 1 hour per contamination value

---

## Possible Solution Approaches

### For GAP-001: Forecast Backtesting

| Approach | Description | Advantages | Disadvantages |
|----------|-------------|------------|---------------|
| **A. Rolling-origin backtest (expanding window)** | Train on [0:t], test on [t:t+h]; expand window; repeat | Standard ML practice; uses all data; matches production retrain cycle | More compute; needs orchestration |
| **B. Fixed-origin backtest (sliding window)** | Train on fixed window, test on next h; slide forward | Faster; consistent training size | Less data for early tests |
| **C. Single holdout split** | Train on first 80%, test on last 20% | Simple; fast | Wasteful; doesn't match retrain cycle |
| **D. Extend existing monitoring** | Use `forecast_predictions` table with actuals filled over time | Reuses existing tables; incremental | Only evaluates as time passes; no historical backtest |

**Recommended: Approach A (Rolling-origin backtest)** — Industry standard for time series; matches the weekly retrain ritual described in PRODUCT.md; enables MAE/RMSE/WAPE/MASE/bias/coverage reporting.

### For GAP-002: Anomaly Validation

| Approach | Description | Advantages | Disadvantages |
|----------|-------------|------------|---------------|
| **A. Synthetic anomaly injection** | Inject known spikes/drops into historical data; measure detection | Controlled ground truth; repeatable; no human effort | May not reflect real anomaly patterns |
| **B. Human labeling workflow** | UI for reviewers to confirm/reject alerts; compute metrics from labels | Real business validation; builds labeled dataset over time | Slow; requires user participation |
| **C. Hybrid: Synthetic + Human** | Synthetic for CI/regression; human for production calibration | Best of both; synthetic catches regressions | More complex |
| **D. Semi-supervised: Use forecast residuals** | Large forecast errors as proxy anomaly labels | Uses existing data; no new labeling | Forecast errors ≠ anomalies; noisy |

**Recommended: Approach C (Hybrid)** — Synthetic benchmark for CI/CD and regression testing; human labeling workflow for production calibration and ongoing validation.

---

## Recommended Solution Approach

### GAP-001: Rolling-Origin Backtesting Framework

**Core Components:**
1. **Backtest Orchestrator** (`app/ml/backtest.py`): Expanding window, configurable horizon, multiple models
2. **Metrics Persistence**: Extend `forecast_monitoring_metrics` or new `forecast_backtest_results` table
3. **Baseline Models**: Seasonal naive, moving average, drift — for comparison
4. **API Endpoint**: `/ai/forecast/backtest` to trigger and retrieve results
5. **Portfolio Fix**: Either run actual models (cached) or label honestly as "7-day MA (baseline)"

**Integration Points:**
- Reuse `MovementRepository.daily_for_product()` for data
- Reuse `forecast_with_prophet/arima/ensemble` for model fitting
- Reuse `evaluate_all()` from `monitoring.metrics` for MAE/RMSE/WAPE/MASE/bias/coverage
- Store results per product/model/horizon/origin_date

### GAP-002: Anomaly Labeling + Synthetic Benchmark

**Core Components:**
1. **Synthetic Benchmark Generator** (`app/ml/anomaly_benchmark.py`): Inject known anomalies (spikes, drops, level shifts, trend changes) into historical data
2. **Labeling UI**: Extend anomaly alerts table with "Confirm/Reject" actions; persist to `anomaly_log.status`
3. **Evaluation Metrics**: Precision, recall, F1, PR-AUC per detection method (isolation_forest, zscore, forecast_deviation, rule_based)
4. **Alert Fatigue Tracking**: Alerts/day, review rate, time-to-resolve
5. **Calibration**: Map risk_level to empirical precision (e.g., "critical" = 90% precision)

**Integration Points:**
- Reuse `AnomalyRepository` status field (new/reviewed/acknowledged/resolved)
- Reuse `detect_anomalies_enriched()` for detection
- Add `/ai/anomaly/benchmark` endpoint for synthetic evaluation
- Add `/ai/anomaly/alerts/<id>/label` endpoint for human labeling

---

## Testing Considerations

### GAP-001 Tests Required
| Test | Description |
|------|-------------|
| Backtest on synthetic data | Known pattern (trend + seasonality); verify metrics computed correctly |
| Backtest on DataCo data | Real data; compare Prophet vs ARIMA vs Ensemble vs MA baseline |
| Horizon validation | Test horizon > history returns warning; model_used = moving_average |
| Portfolio honesty | Verify portfolio model column matches actual method used |
| Metric persistence | Backtest results saved with product/model/horizon/origin_date |

### GAP-002 Tests Required
| Test | Description |
|------|-------------|
| Synthetic benchmark | Inject 10 spikes + 5 drops + 3 level shifts; measure precision/recall/F1 per method |
| Human labeling workflow | Create alert → confirm → verify status=reviewed; reject → verify status=resolved |
| Risk level calibration | Verify "critical" alerts have higher precision than "low" |
| Alert fatigue metrics | Track alerts/day, review rate, time-to-resolve |
| Detection method comparison | Isolation Forest vs z-score vs forecast_deviation vs rule_based |

---

## Regression Risks

| Risk | Mitigation |
|------|------------|
| Backtest computation blocks UI | Run in background thread (like ETL); cache results |
| Portfolio model change breaks UI | Maintain same response schema; add `data_sufficiency` field |
| Anomaly labeling changes alert status flow | Preserve existing status transitions; add new "confirmed"/"rejected" if needed |
| Synthetic benchmark modifies production data | Use separate test database or transaction rollback |
| Increased DB storage for backtest results | Partition by date; retention policy |

---

## Research Sources

### Internal (Verified from Codebase)
- `app/ml/forecasting.py` — Model implementations, fallback logic, in-sample accuracy
- `app/services/forecast_service.py` — Portfolio MA usage, monitoring update logic
- `app/ml/anomaly.py` — Detection methods, confidence heuristics, risk levels
- `app/services/anomaly_service.py` — Portfolio per-product fitting, alert persistence
- `app/monitoring/metrics.py` — MAE, MAPE, RMSE, bias, WAPE (missing), MASE (missing)
- `app/repositories/monitoring_repo.py` — Baseline = first evaluation window
- `tests/test_ml.py` — In-sample tests only; deterministic output verification

### External (Research-Backed)
- **Rolling-origin backtesting**: Hyndman & Athanasopoulos "Forecasting: Principles and Practice" Ch. 5; standard for time series evaluation
- **WAPE/MASE metrics**: Better for intermittent demand than MAPE (Hyndman & Koehler 2006)
- **Anomaly detection evaluation**: Precision/recall/F1 standard; PR-AUC for threshold-independent assessment (Chandola et al. 2009)
- **Synthetic anomaly injection**: Standard practice for ML validation when labels scarce (Laptev et al. 2015 - Netflix)
- **Alert fatigue metrics**: Alerts/day, review rate, MTTR — standard SRE practice (Google SRE Book)

---

## Summary

**GAP-001** is fundamentally a **missing evaluation framework** — the code computes in-sample metrics on training data and presents them as accuracy. The fix requires a rolling-origin backtest orchestrator that evaluates on chronologically held-out data.

**GAP-002** is fundamentally a **missing validation framework** — the code generates alerts with risk levels and confidence scores that are heuristic and uncalibrated. The fix requires synthetic benchmarking for CI/CD and a human labeling workflow for production calibration.

**Shared opportunity**: The backtesting infrastructure for GAP-001 can generate the holdout periods needed for anomaly injection in GAP-002. Both should be designed as a unified ML validation framework.