# Batch 1 Architecture Design: ML Validation Framework

## Current Architecture (Relevant to Batch 1)

### Forecast Pipeline
```
User Request (/ai/forecast/run)
    → ForecastService.run(product_id, model, horizon)
        → MovementRepository.daily_for_product(product_id, days=180)
        → forecast_with_prophet/arima/ensemble(history, horizon)
            → _moving_average_forecast() fallback if libs missing or insufficient data
        → ForecastRepository.save(product_id, model, horizon, result)
        → _update_monitoring(sku, model, history)
            → Creates "predictions" for last 30 days using 7-day MA
            → MonitoringRepository.save_predictions_batch()
            → evaluate_all(actuals, predicted) → MAE, MAPE, RMSE, bias, error_std
            → MonitoringRepository.save_metrics() with baseline from first evaluation
```

### Forecast Portfolio
```
User Request (/ai/forecast/portfolio)
    → ForecastService.portfolio(horizon, model)
        → Queries all products + 90 days movements
        → Computes 7-day MA per product (NO model fitting)
        → Labels with selected model name (Prophet/ARIMA/Ensemble)
        → Returns accuracy on active-demand days only
        → Cached 1hr per (horizon, model) in _portfolio_cache
```

### Anomaly Pipeline
```
User Request (/ai/anomaly/run)
    → AnomalyService.run_for_product_enriched(product_id, contamination, z_threshold)
        → MovementRepository.daily_for_product(product_id, days=120)
        → detect_anomalies_enriched(series, ...)
            → detect_anomalies_isoforest() → Isolation Forest or z-score fallback
            → enrich_anomalies() → risk_level, recommended_action, confidence (heuristic)
            → forecast_deviation layer (40% threshold, hardcoded)
            → rule_based_peaks layer (3× multiplier, hardcoded)
            → deduplicate by day (keep highest risk)
        → spc_zscore_analysis() → SPC chart data
        → AnomalyRepository.save() → anomaly_log
```

### Anomaly Portfolio
```
User Request (/ai/anomaly/portfolio)
    → AnomalyService.portfolio(contamination)
        → Queries all products + 120 days movements
        → Runs detect_anomalies_enriched() PER PRODUCT (O(n) model fits)
        → Returns summary with detection_method of first anomaly
        → Cached 1hr per contamination in _portfolio_cache
```

### Monitoring Infrastructure
```
Tables:
- forecast_predictions: (sku, model_name, forecast_date, predicted_value, actual_value, status)
- forecast_monitoring_metrics: (sku, model_name, monitoring_date, mae, mape, rmse, bias, baseline_mae, baseline_mape, model_status)
- model_monitoring_alerts: (sku, model_name, alert_date, alert_type, severity, metric, change_percent)

Services:
- MonitoringService.compute_metrics() → evaluate_all() → detect_degradation() → model_health_status()
- MonitoringRepository.baseline_metrics() → oldest metrics entry (NOT training baseline)
```

---

## Proposed Architecture

### High-Level Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ML VALIDATION LAYER                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────┐    ┌──────────────────────┐                      │
│  │  Forecast Backtest   │    │  Anomaly Benchmark   │                      │
│  │  (app/ml/backtest.py)│    │(app/ml/anomaly_      │                      │
│  │                      │    │ benchmark.py)        │                      │
│  │ • RollingOriginConfig│    │                      │                      │
│  │ • Expanding window   │    │ • SyntheticInjector  │                      │
│  │ • Multi-model eval   │    │ • Spike/Drop/Shift   │                      │
│  │ • Baseline models    │    │ • Precision/Recall   │                      │
│  └──────────┬───────────┘    └──────────┬───────────┘                      │
│             │                           │                                    │
│             ▼                           ▼                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    METRICS ENGINE (app/monitoring/metrics.py)        │   │
│  │  MAE, MAPE, RMSE, WAPE, MASE, Bias, Interval Coverage, Error Std    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│             │                           │                                    │
│             ▼                           ▼                                    │
│  ┌──────────────────────┐    ┌──────────────────────┐                      │
│  │  Forecast Backtest   │    │  Anomaly Labeling    │                      │
│  │  Results Table       │    │  & Fatigue Metrics   │                      │
│  │  forecast_backtest_  │    │  anomaly_log.status  │                      │
│  │  results             │    │  (extended)          │                      │
│  └──────────────────────┘    └──────────────────────┘                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
             │                           │
             ▼                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         EXISTING SERVICE LAYER                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────┐    ┌──────────────────────┐                      │
│  │  ForecastService     │    │  AnomalyService      │                      │
│  │                      │    │                      │                      │
│  │ • run()              │    │ • run_for_product_   │                      │
│  │ • portfolio() ←FIX   │    │   enriched()         │                      │
│  │ • backtest() ←NEW    │    │ • portfolio()        │                      │
│  │ • horizon_validate()←NEW│   │ • benchmark() ←NEW   │                      │
│  │ • label_alert() ←NEW │    │ • alert_fatigue()←NEW│                      │
│  └──────────┬───────────┘    └──────────┬───────────┘                      │
│             │                           │                                    │
└─────────────┼───────────────────────────┼────────────────────────────────────┘
              │                           │
              ▼                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         REPOSITORY LAYER                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────┐    ┌──────────────────────┐                      │
│  │  ForecastRepository  │    │  AnomalyRepository   │                      │
│  │                      │    │  (forecast_repo.py)  │                      │
│  │ • save()             │    │                      │                      │
│  │ • recent()           │    │ • save()             │                      │
│  │ • save_backtest()←NEW│    │ • update_label()←NEW │                      │
│  │ • get_backtest()←NEW │    │ • get_labeled()←NEW  │                      │
│  └──────────────────────┘    │ • get_fatigue()←NEW  │                      │
│                              └──────────────────────┘                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
              │                           │
              ▼                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DATABASE LAYER                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Existing:                    New/Extended:                                 │
│  ─────────                    ─────────────                                 │
│  forecast_cache               forecast_backtest_results                     │
│  forecast_predictions         anomaly_log.status (extended labels)          │
│  forecast_monitoring_metrics  anomaly_fatigue_daily (new aggregate table)   │
│  model_monitoring_alerts                                                          │
│  anomaly_log                                                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

### Forecast Backtest Flow

```
1. User clicks "Run Backtest" on forecast page
   │
   ▼
2. POST /ai/forecast/backtest {product_id, model, horizon, config?}
   │
   ▼
3. ForecastService.backtest(product_id, model, horizon, config)
   │
   ├─► MovementRepository.daily_for_product(product_id, days=365+)  [Extended history]
   │
   ├─► BacktestConfig(horizon, step=7, min_train=60, max_origins=10)
   │
   ├─► rolling_origin_backtest(history, config)
   │     │
   │     ├─► For each origin_date from (min_train) to (len - horizon) step 7:
   │     │     ├─► train = history[:origin]
   │     │     ├─► test = history[origin:origin+horizon]
   │     │     ├─► Fit model on train → predict horizon
   │     │     ├─► Fit baselines (seasonal_naive, MA, drift) on train → predict
   │     │     └─► evaluate_backtest(predictions, actuals, train_history)
   │     │
   │     └─► Returns: List[BacktestResult] per origin
   │
   ├─► ForecastRepository.save_backtest_results(product_id, model, horizon, results)
   │
   └─► Returns summary: {model, horizon, origins_tested, avg_mae, avg_rmse, avg_wape, avg_mase, coverage}
```

### Anomaly Benchmark Flow

```
1. User clicks "Run Benchmark" on anomaly page
   │
   ▼
2. GET /ai/anomaly/benchmark?contamination=0.05
   │
   ▼
3. AnomalyService.benchmark(contamination)
   │
   ├─► For each product with sufficient history:
   │     ├─► Get historical series
   │     ├─► Inject synthetic anomalies:
   │     │     ├─► Spikes at known positions (magnitude 3-5σ)
   │     │     ├─► Drops at known positions (magnitude -3 to -5σ)
   │     │     ├─► Level shifts (persistent +2σ)
   │     │     └─► Trend changes (slope change)
   │     ├─► Run detect_anomalies_enriched() on injected series
   │     ├─► Match detected ↔ injected by day (±1 day tolerance)
   │     └─► Compute per-method: TP, FP, FN, TN, Precision, Recall, F1, PR-AUC
   │
   ├─► Aggregate across all products
   │
   └─► Returns: {contamination, products_tested, total_injected, by_method: {precision, recall, f1, pr_auc}, by_type: {spike, drop, shift, trend}}
```

### Anomaly Labeling Flow

```
1. User views alert detail modal
   │
   ▼
2. Clicks "Confirm" (true positive) or "Reject" (false positive)
   │
   ▼
3. POST /ai/anomaly/alerts/<id>/label {label: "true_positive"|"false_positive", user_id}
   │
   ▼
4. AnomalyRepository.update_label(alert_id, label, labeled_by=user_id)
   │
   ├─► Updates anomaly_log: label, labeled_at, labeled_by
   │
   ├─► If label="true_positive": status="reviewed"
   │
   └─► If label="false_positive": status="resolved"
```

### Alert Fatigue Metrics Flow

```
Daily (scheduled job or on-demand):
   │
   ▼
AnomalyService.compute_fatigue_metrics()
   │
   ├─► Query anomaly_log for last 30 days
   │
   ├─► Group by date: alerts_per_day = COUNT(*) GROUP BY detected_at::date
   │
   ├─► Review rate = COUNT(status IN ('reviewed','acknowledged','resolved')) / COUNT(*)
   │
   ├─► Avg time-to-resolve = AVG(resolved_at - detected_at) WHERE status='resolved'
   │
   ├─► By risk_level: alerts_per_day, review_rate
   │
   └─► Store in anomaly_fatigue_daily table (new)
```

---

## Request/Response Flow

### Forecast Backtest API

**POST /ai/forecast/backtest**
```json
Request:
{
  "product_id": 123,
  "model": "prophet",
  "horizon": 30,
  "config": {
    "min_train_days": 60,
    "step_days": 7,
    "max_origins": 10,
    "baselines": ["seasonal_naive", "moving_average", "drift"]
  }
}

Response:
{
  "success": true,
  "data": {
    "product_id": 123,
    "model": "prophet",
    "horizon": 30,
    "origins_tested": 8,
    "metrics": {
      "mae": {"mean": 4.2, "std": 1.1, "per_origin": [...]},
      "rmse": {"mean": 5.8, "std": 1.4, "per_origin": [...]},
      "wape": {"mean": 18.5, "std": 3.2, "per_origin": [...]},
      "mase": {"mean": 0.85, "std": 0.12, "per_origin": [...]},
      "bias": {"mean": -0.3, "std": 0.8, "per_origin": [...]},
      "interval_coverage": {"mean": 92.1, "std": 4.3, "per_origin": [...]}
    },
    "baselines": {
      "seasonal_naive": {"mae": 5.1, "rmse": 6.9, "wape": 22.3},
      "moving_average": {"mae": 4.8, "rmse": 6.4, "wape": 20.1},
      "drift": {"mae": 5.5, "rmse": 7.2, "wape": 24.0}
    },
    "completed_at": "2026-09-30T10:15:00Z"
  }
}
```

**GET /ai/forecast/backtest?product_id=123&model=prophet&horizon=30**
```json
Response:
{
  "success": true,
  "data": [
    {
      "origin_date": "2026-06-01",
      "horizon": 30,
      "mae": 4.1,
      "rmse": 5.6,
      "wape": 17.8,
      "mase": 0.82,
      "bias": -0.2,
      "interval_coverage": 93.3,
      "observation_count": 30
    },
    ...
  ]
}
```

### Anomaly Benchmark API

**GET /ai/anomaly/benchmark?contamination=0.05**
```json
Response:
{
  "success": true,
  "data": {
    "contamination": 0.05,
    "products_tested": 45,
    "total_injected": 180,
    "by_method": {
      "isolation_forest": {"precision": 0.78, "recall": 0.72, "f1": 0.75, "pr_auc": 0.81},
      "zscore": {"precision": 0.65, "recall": 0.68, "f1": 0.66, "pr_auc": 0.72},
      "forecast_deviation": {"precision": 0.71, "recall": 0.55, "f1": 0.62, "pr_auc": 0.68},
      "rule_based": {"precision": 0.52, "recall": 0.48, "f1": 0.50, "pr_auc": 0.55}
    },
    "by_type": {
      "spike": {"precision": 0.82, "recall": 0.75},
      "drop": {"precision": 0.70, "recall": 0.68},
      "level_shift": {"precision": 0.60, "recall": 0.55},
      "trend_change": {"precision": 0.45, "recall": 0.40}
    },
    "completed_at": "2026-09-30T10:20:00Z"
  }
}
```

### Anomaly Labeling API

**POST /ai/anomaly/alerts/456/label**
```json
Request:
{
  "label": "true_positive",
  "user_id": 1
}

Response:
{
  "success": true,
  "data": {
    "alert_id": 456,
    "label": "true_positive",
    "status": "reviewed",
    "labeled_at": "2026-09-30T10:25:00Z",
    "labeled_by": 1
  }
}
```

### Portfolio Honesty Fix

**GET /ai/forecast/portfolio?horizon=30&model=prophet**
```json
Response (FIXED - Option A: actual models):
{
  "success": true,
  "data": [
    {
      "id": 1,
      "sku": "SKU-001",
      "name": "Widget A",
      "model": "Prophet (Seasonality)",
      "model_used": "prophet",           // NEW: actual model used
      "predicted_units": 1250,
      "baseline": 42.3,
      "delta_pct": 12.5,
      "accuracy": 87.3,
      "data_sufficiency": "sufficient"   // NEW: warning if horizon > history
    },
    {
      "id": 2,
      "sku": "SKU-002",
      "name": "Widget B",
      "model": "Prophet (Seasonality)",
      "model_used": "moving_average",    // NEW: fallback used
      "predicted_units": 890,
      "baseline": 29.7,
      "delta_pct": -5.2,
      "accuracy": 78.0,
      "data_sufficiency": "insufficient_history"  // NEW
    }
  ]
}
```

---

## Database Interaction

### New Table: forecast_backtest_results

```sql
CREATE TABLE forecast_backtest_results (
    id              BIGSERIAL PRIMARY KEY,
    product_id      INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    sku             VARCHAR(50) NOT NULL,
    model_name      VARCHAR(30) NOT NULL,
    baseline_name   VARCHAR(30),  -- NULL for primary model, set for baseline comparisons
    origin_date     DATE NOT NULL,
    horizon         INTEGER NOT NULL,
    mae             NUMERIC(10,3),
    mape            NUMERIC(7,2),
    rmse            NUMERIC(10,3),
    wape            NUMERIC(7,2),
    mase            NUMERIC(7,3),
    bias            NUMERIC(10,3),
    interval_coverage NUMERIC(5,2),
    observation_count INTEGER NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_fbr_product_model_origin
    ON forecast_backtest_results(product_id, model_name, origin_date);
CREATE INDEX idx_fbr_sku_origin
    ON forecast_backtest_results(sku, origin_date);
```

### Extended Table: anomaly_log (add labeling fields)

```sql
-- Add to existing anomaly_log table
ALTER TABLE anomaly_log ADD COLUMN IF NOT EXISTS label VARCHAR(20);
ALTER TABLE anomaly_log ADD COLUMN IF NOT EXISTS labeled_at TIMESTAMP;
ALTER TABLE anomaly_log ADD COLUMN IF NOT EXISTS labeled_by INTEGER REFERENCES users(id);

-- Label values: 'true_positive', 'false_positive', 'true_negative', 'false_negative'
CREATE INDEX idx_anomaly_label ON anomaly_log(label) WHERE label IS NOT NULL;
```

### New Table: anomaly_fatigue_daily

```sql
CREATE TABLE anomaly_fatigue_daily (
    id              SERIAL PRIMARY KEY,
    metric_date     DATE NOT NULL UNIQUE,
    total_alerts    INTEGER NOT NULL DEFAULT 0,
    critical_count  INTEGER NOT NULL DEFAULT 0,
    high_count      INTEGER NOT NULL DEFAULT 0,
    medium_count    INTEGER NOT NULL DEFAULT 0,
    low_count       INTEGER NOT NULL DEFAULT 0,
    reviewed_count  INTEGER NOT NULL DEFAULT 0,
    resolved_count  INTEGER NOT NULL DEFAULT 0,
    avg_resolve_hours NUMERIC(6,2),
    review_rate     NUMERIC(5,2),  -- percentage
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_afd_date ON anomaly_fatigue_daily(metric_date);
```

---

## Service/Module Interaction

### ForecastService Extensions

```python
class ForecastService:
    # ... existing methods ...

    @classmethod
    def backtest(cls, product_id: int, *, model: str = "prophet",
                 horizon: int = 30, config: BacktestConfig = None) -> dict:
        """Run rolling-origin backtest for a product/model/horizon."""
        # 1. Get extended history (365+ days)
        # 2. Run rolling_origin_backtest()
        # 3. Persist results
        # 4. Return summary

    @classmethod
    def portfolio(cls, horizon: int = 30, model: str = "prophet") -> list[dict]:
        """FIXED: Run actual models per product (cached) or label honestly."""
        # Option A: Fit model per product, cache 1hr
        # Option B: Return "7-day MA (baseline)" with model_used="moving_average"

    @classmethod
    def validate_horizon(cls, history: list[dict], horizon: int, model: str) -> dict:
        """Check data sufficiency for horizon/model."""
        # Returns: {sufficient: bool, warning: str, model_used: str}
```

### AnomalyService Extensions

```python
class AnomalyService:
    # ... existing methods ...

    @staticmethod
    def benchmark(contamination: float = 0.05) -> dict:
        """Run synthetic anomaly benchmark across catalogue."""
        # 1. For each product with sufficient history
        # 2. Inject synthetic anomalies
        # 3. Run detection
        # 4. Compute precision/recall/F1 per method
        # 5. Return aggregated results

    @staticmethod
    def label_alert(alert_id: int, label: str, labeled_by: int) -> dict:
        """Confirm or reject an anomaly alert."""
        # 1. Validate label
        # 2. Update anomaly_log
        # 3. Return updated alert

    @staticmethod
    def get_precision_recall() -> dict:
        """Compute empirical precision/recall from labeled data."""
        # 1. Get labeled alerts
        # 2. Group by risk_level, detection_method
        # 3. Compute precision, recall, F1

    @staticmethod
    def compute_fatigue_metrics(days: int = 30) -> dict:
        """Compute alert fatigue metrics."""
        # 1. Alerts per day
        # 2. Review rate
        # 3. Avg time-to-resolve
        # 4. By risk_level
```

---

## Dependency Flow

```
app/ml/backtest.py
    │
    ├─► app/ml/forecasting.py (forecast_with_prophet, forecast_with_arima, forecast_ensemble)
    ├─► app/monitoring/metrics.py (evaluate_all, calculate_wape, calculate_mase, calculate_interval_coverage)
    └─► app/repositories/forecast_repo.py (save_backtest_results)

app/ml/anomaly_benchmark.py
    │
    ├─► app/ml/anomaly.py (detect_anomalies_enriched)
    ├─► app/monitoring/metrics.py (precision, recall, f1, pr_auc helpers)
    └─► app/services/anomaly_service.py (benchmark orchestration)

app/services/forecast_service.py
    │
    ├─► app/ml/backtest.py (backtest)
    ├─► app/ml/forecasting.py (portfolio model fitting)
    ├─► app/repositories/forecast_repo.py (save, save_backtest)
    └─► app/repositories/movement_repo.py (daily_for_product)

app/services/anomaly_service.py
    │
    ├─► app/ml/anomaly_benchmark.py (benchmark)
    ├─► app/ml/anomaly.py (detect_anomalies_enriched)
    ├─► app/repositories/forecast_repo.py (AnomalyRepository: save, update_label, get_labeled, get_fatigue)
    └─► app/repositories/movement_repo.py (daily_for_product)

app/repositories/forecast_repo.py
    │
    ├─► ForecastRepository.save_backtest_results()
    ├─► ForecastRepository.get_backtest_results()
    ├─► AnomalyRepository.update_label()
    ├─► AnomalyRepository.get_labeled_alerts()
    └─► AnomalyRepository.get_fatigue_metrics()
```

---

## Error-Handling Flow

### Forecast Backtest Errors

| Error Scenario | Handling |
|----------------|----------|
| Insufficient history (< min_train_days) | Return error: "Need at least 60 days history for backtest" |
| Model fitting fails at origin | Skip origin; log warning; continue with remaining |
| All origins fail | Return error with details; don't persist partial results |
| Database error during persist | Rollback; return 500; log full traceback |
| Timeout (backtest > 60s) | Run in background thread; return job_id; poll for results |

### Anomaly Benchmark Errors

| Error Scenario | Handling |
|----------------|----------|
| No products with sufficient history | Return empty results with message |
| Detection fails for product | Skip product; log warning; continue |
| Synthetic injection creates invalid data | Validate injected series; skip if invalid |
| Database error | Return 500; log; benchmark is read-only |

### Anomaly Labeling Errors

| Error Scenario | Handling |
|----------------|----------|
| Invalid label value | Return 422: "label must be true_positive or false_positive" |
| Alert not found | Return 404 |
| User not authorized | Return 403 (write_roles_required) |
| Concurrent label update | Optimistic locking via version or timestamp |

---

## Security Considerations

### Input Validation
- All API endpoints validate `product_id`, `horizon`, `model`, `contamination` as integers/floats
- `model` validated against allowed list: `["prophet", "arima", "ensemble"]`
- `label` validated against allowed list: `["true_positive", "false_positive"]`
- Horizon capped at 365 days (configurable)

### Authorization
- `/ai/forecast/backtest` — `@write_roles_required` (admin/manager only)
- `/ai/anomaly/benchmark` — `@login_required` (viewer can run benchmark)
- `/ai/anomaly/alerts/<id>/label` — `@write_roles_required`
- Portfolio endpoints — `@login_required` (existing)

### Rate Limiting
- Backtest: `10 per minute` (expensive operation)
- Benchmark: `6 per minute` (expensive operation)
- Labeling: `30 per minute` (existing anomaly rate limit)

### Data Exposure
- Backtest results only show aggregated metrics, not raw predictions
- Anomaly benchmark only shows aggregated precision/recall, not per-product details
- Labeling only exposes alert ID and label; no PII

---

## Transaction/Integrity Considerations

### Forecast Backtest
- Each origin evaluation is independent — no transaction needed across origins
- `save_backtest_results()` uses single transaction with `execute_values` for batch insert
- If partial failure: rollback entire batch; user can retry

### Anomaly Labeling
- `update_label()` is single-row UPDATE — atomic
- Status transition: `new → reviewed` (confirm) or `new → resolved` (reject)
- No concurrent modification expected (single alert per user action)

### Anomaly Fatigue Metrics
- Daily aggregate computed from `anomaly_log` — read-only
- Stored in `anomaly_fatigue_daily` with `ON CONFLICT (metric_date) DO UPDATE`
- Idempotent: safe to re-run

---

## Concurrency Considerations

### Forecast Backtest
- **Problem**: Model fitting is CPU-intensive; multiple concurrent backtests could exhaust resources
- **Solution**: 
  - Rate limit: 10/min per user, 20/min global
  - Run in background thread (like ETL) for large backtests
  - Cache results 24h per product/model/horizon

### Anomaly Portfolio
- **Problem**: `portfolio()` fits model per product O(n) — scales poorly
- **Solution** (existing): 1hr cache per contamination value
- **Improvement**: Move to scheduled background job (APScheduler) for >200 SKUs

### Anomaly Benchmark
- **Problem**: Runs detection on all products with injected anomalies — very expensive
- **Solution**:
  - Run in background thread
  - Cache results 1hr per contamination
  - Limit to products with ≥60 days history

---

## Configuration Impacts

### New Settings (app/config/settings.py)

```python
class BaseConfig:
    # Forecast backtest
    BACKTEST_MIN_TRAIN_DAYS = 60
    BACKTEST_STEP_DAYS = 7
    BACKTEST_MAX_ORIGINS = 10
    BACKTEST_CACHE_TTL = 86400  # 24 hours
    BACKTEST_TIMEOUT_SECONDS = 60

    # Anomaly detection (make configurable)
    ANOMALY_ZWARNING = 2.0
    ANOMALY_ZHIGH = 3.0
    ANOMALY_ZCRITICAL = 4.0
    ANOMALY_CONTAMINATION = 0.05
    ANOMALY_FORECAST_DEV_THRESHOLD = 0.4
    ANOMALY_RULE_PEAK_MULTIPLIER = 3.0

    # Anomaly benchmark
    ANOMALY_BENCHMARK_CACHE_TTL = 3600  # 1 hour
    ANOMALY_BENCHMARK_MIN_HISTORY_DAYS = 60
    ANOMALY_BENCHMARK_TIMEOUT_SECONDS = 120

    # Portfolio
    PORTFOLIO_CACHE_TTL = 3600
    PORTFOLIO_RUN_ACTUAL_MODELS = True  # Feature flag for Option A vs B
```

### Environment Variables
```bash
# Optional overrides
BACKTEST_MIN_TRAIN_DAYS=60
BACKTEST_STEP_DAYS=7
ANOMALY_ZWARNING=2.0
ANOMALY_ZHIGH=3.0
ANOMALY_ZCRITICAL=4.0
ANOMALY_CONTAMINATION=0.05
PORTFOLIO_RUN_ACTUAL_MODELS=true
```

---

## Integration Impacts

### Existing API Contracts (Preserved)
- `/ai/forecast/run` — unchanged response schema; adds `data_sufficiency` field
- `/ai/forecast/portfolio` — unchanged schema; adds `model_used`, `data_sufficiency` fields
- `/ai/anomaly/run` — unchanged
- `/ai/anomaly/portfolio` — unchanged schema; adds `model_used` field
- `/ai/anomaly/alerts` — unchanged; labeling is new endpoint

### Frontend Integration
- `ai-features.js` — new `StockflowForecast.backtest()` and `StockflowAnomaly.benchmark()` modules
- `forecast.html` — add "Run Backtest" button, results panel
- `anomaly.html` — add "Confirm/Reject" in modal, "Run Benchmark" button, metrics display

### Monitoring Integration
- Backtest results can feed into `forecast_monitoring_metrics` for historical comparison
- Anomaly labeling improves `model_monitoring_alerts` calibration
- Fatigue metrics displayed on monitoring dashboard

---

## Testing Architecture

### Unit Tests (New Files)
```
tests/
├── test_backtest.py           # Backtest orchestrator, metrics
├── test_anomaly_benchmark.py  # Synthetic injection, evaluation
```

### Extended Tests
```
tests/test_ml.py               # Add: backtest tests, anomaly benchmark tests
tests/test_api.py              # Add: backtest endpoint, benchmark endpoint, labeling endpoint
tests/test_services.py         # Add: ForecastService.backtest, AnomalyService.benchmark
```

### Test Data Strategy
- **Synthetic**: Known patterns (trend + seasonality + noise) for deterministic verification
- **DataCo**: Real seeded data for integration testing
- **Fixtures**: Pre-computed expected values for regression testing

### CI/CD Integration
- Backtest tests run on every PR (fast synthetic data)
- Anomaly benchmark runs nightly (expensive; full catalogue)
- Labeling workflow tested via API integration tests

---

## Backward-Compatibility Considerations

### API Responses
- All existing fields preserved
- New fields added: `model_used`, `data_sufficiency`, `label`, `labeled_at`, `labeled_by`
- No breaking changes to existing endpoints

### Database
- New tables only (`forecast_backtest_results`, `anomaly_fatigue_daily`)
- Existing tables extended with nullable columns (`anomaly_log.label`, `labeled_at`, `labeled_by`)
- No column removals or type changes

### Caching
- Existing cache keys preserved
- New cache keys for backtest/benchmark results
- Cache invalidation on model retrain (future)

### Configuration
- All new settings have sensible defaults
- Feature flag `PORTFOLIO_RUN_ACTUAL_MODELS` allows gradual rollout
- Anomaly thresholds made configurable (previously hardcoded)

---

## Performance Considerations

### Forecast Backtest
| Operation | Complexity | Optimization |
|-----------|------------|--------------|
| Data fetch | O(history_days) | Index on `movements(product_id, created_at)` |
| Model fitting per origin | O(origins × model_complexity) | Cache fitted models; parallel origins |
| Metrics computation | O(horizon × origins) | Vectorized numpy operations |
| Persistence | O(origins) | Batch insert with `execute_values` |

**Expected runtime**: 5-30 seconds for 10 origins × 30-day horizon (Prophet)
**Mitigation**: Background thread for >10s; cache 24h

### Anomaly Benchmark
| Operation | Complexity | Optimization |
|-----------|------------|--------------|
| Data fetch all products | O(products × history_days) | Single query with `product_id = ANY(%s)` |
| Synthetic injection | O(products × injected_anomalies) | Vectorized; minimal overhead |
| Detection per product | O(products × detection_complexity) | Parallel processing (ThreadPoolExecutor) |
| Evaluation | O(total_detected) | Simple counting; fast |

**Expected runtime**: 30-120 seconds for 100 products
**Mitigation**: Background thread; cache 1hr; run nightly via scheduler

### Portfolio (Fixed)
| Operation | Complexity | Optimization |
|-----------|------------|--------------|
| Option A: Actual models | O(products × model_complexity) | Cache 1hr; background job for >500 SKUs |
| Option B: MA only | O(products × history_days) | Current implementation; fast |

---

## Summary of Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| New `backtest.py` module (not in forecasting.py) | Separation of concerns; backtesting is evaluation, not forecasting |
| New `anomaly_benchmark.py` module | Synthetic injection is test infrastructure, not detection logic |
| `forecast_backtest_results` table (not extend monitoring_metrics) | Different granularity (per-origin vs daily); different purpose (validation vs monitoring) |
| Extend `anomaly_log` with label fields | Reuses existing alert infrastructure; minimal schema change |
| Background threads for expensive ops | Consistent with existing ETL pattern; non-blocking UI |
| Feature flag for portfolio models | Allows safe rollout; Option B as fallback |
| Configurable anomaly thresholds | Removes hardcoded values; enables calibration |
| WAPE/MASE in metrics.py | Industry-standard metrics for intermittent demand; complements MAPE |