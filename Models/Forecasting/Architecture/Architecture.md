# InventoryLogix Forecasting Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        INVENTORYLOGIX FORECASTING SYSTEM                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────┐  │
│  │   PostgreSQL │───▶│  Data Access │───▶│  Forecasting │───▶│   API    │  │
│  │   Database   │    │   Layer      │    │   Engine     │    │  Layer   │  │
│  └──────────────┘    └──────────────┘    └──────────────┘    └──────────┘  │
│         │                   │                   │                  │        │
│         ▼                   ▼                   ▼                  ▼        │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────┐  │
│  │  Movements   │    │  Stored      │    │  SARIMA/     │    │  REST    │  │
│  │  Table       │    │  Procedures  │    │  ARIMA/      │    │  Endpoints│  │
│  └──────────────┘    └──────────────┘    │  Ensemble    │    └──────────┘  │
│                                           └──────────────┘                  │
│                                                    │                        │
│                                           ┌────────┴────────┐              │
│                                           ▼                 ▼              │
│                                    ┌─────────────┐  ┌─────────────┐       │
│                                    │ Monitoring  │  │  Retraining │       │
│                                    │  Service    │  │  Pipeline   │       │
│                                    └─────────────┘  └─────────────┘       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Architecture

### 1. Data Access Layer

#### MovementRepository
```python
class MovementRepository:
    @staticmethod
    def daily_for_product(product_id: int, days: int = 90) -> list[dict]:
        """Fetch daily OUT movement totals via stored procedure.
        
        Returns continuous daily series with zeros for missing days.
        Uses generate_series for continuous date coverage.
        """
```

**Stored Procedure**: `sp_movement_daily_for_product(p_product_id, p_days)`
- Uses `generate_series` for continuous date coverage
- LEFT JOIN with movements (OUT type only)
- Returns: `day DATE, total BIGINT` (zeros for missing days)

#### ForecastRepository
```python
class ForecastRepository:
    @staticmethod
    def save(product_id, model, horizon, payload) -> None:
        """Upsert forecast cache with accuracy."""
    
    @staticmethod
    def recent(product_id, limit=5) -> list[dict]:
        """Get recent cached forecasts."""
    
    @staticmethod
    def save_backtest_results(product_id, model, horizon, results) -> None:
        """Persist backtest results."""
    
    @staticmethod
    def get_backtest_results(...) -> tuple[list[dict], int]:
        """Query backtest results with filters."""
```

### 2. Forecasting Engine (`app/ml/forecasting.py`)

#### Core Models

| Model | Function | Parameters | Fallback |
|-------|----------|------------|----------|
| SARIMA | `forecast_with_sarima` | Auto seasonal order | → ARIMA |
| ARIMA | `forecast_with_arima` | Fixed (1,1,1) | → Moving Average |
| Ensemble | `forecast_ensemble` | SARIMA + ARIMA avg | → MA |
| Moving Average | `_moving_average_forecast` | Window=min(14, n//4) | None |

#### SARIMA Pipeline
```
Input: history[{"ds": "YYYY-MM-DD", "y": value}, ...], horizon
    │
    ▼
1. Validate: len(history) >= 14, statsmodels available
    │
    ▼
2. Infer seasonal period: _infer_seasonal_period()
    │  - n >= 730 → 365 (yearly)
    │  - n >= 60  → 7 (weekly)
    │  - n >= 14  → 7 (weekly)
    │  - else → 7 (default)
    ▼
3. Select SARIMA order: _select_sarima_order()
    │  - Trend detection: |last - first| > 0.1 * mean
    │  - Seasonality: autocorr at seasonal lag > 0.3
    │  - Non-seasonal: (p=1, d=1/0, q=1)
    │  - Seasonal: (1,1,1,s) or (0,0,0,0)
    ▼
4. Build SARIMAX model
    │  - SARIMAX(series, order=(p,d,q), seasonal_order=(P,D,Q,s))
    │  - enforce_stationarity=False, enforce_invertibility=False
    ▼
5. Fit: model.fit(disp=False)
    │
    ▼
6. Forecast: fitted.get_forecast(steps=horizon)
    │
    ▼
7. Compute metrics (in-sample):
    - MAE, MAPE, RMSE, WAPE, MASE, Bias
    ▼
8. Return standardized dict:
    {
        predictions, lower, upper, history, baseline,
        accuracy, model, dates
    }
```

#### ARIMA Pipeline
```
Input: history, horizon
    │
    ▼
1. Validate: len >= 20, statsmodels available
    │
    ▼
2. Build ARIMA(1,1,1) with statespace method
    │
    ▼
3. Fit: model.fit(method='statespace')
    │
    ▼
4. Forecast + confidence intervals
    │
    ▼
5. Compute in-sample metrics
    │
    ▼
5. Return standardized dict
```

#### Ensemble Blending
```
Parallel execution:
    future_sarima = executor.submit(forecast_with_sarima, history, horizon)
    future_arima  = executor.submit(forecast_with_arima, history, horizon)
    
    a = future_sarima.result()
    b = future_arima.result()
    
    blended = {
        predictions: (a.pred + b.pred) / 2,
        lower: (a.lower + b.lower) / 2,
        upper: (a.upper + b.upper) / 2,
        model: "ensemble",
        accuracy: (a.acc + b.acc) / 2
    }
```

### 3. Backtesting Framework (`app/ml/backtest.py`)

#### Configuration
```python
@dataclass
class BacktestConfig:
    horizon: int = 30           # Forecast horizon
    step_days: int = 7          # Step between origins
    min_train_days: int = 60    # Minimum training window
    max_origins: int = 10       # Max number of origins
    baselines: tuple = ("seasonal_naive", "moving_average", "drift")
    parallel: bool = True       # Parallel baseline computation
```

#### Rolling-Origin Backtest
```
History: [d1, d2, ..., dN]
    │
    ▼
Origins = [min_train, min_train+step, ..., N-horizon] (max 10)
    │
    ▼
For each origin:
    Train = history[:origin]
    Test  = history[origin:origin+horizon]
    │
    ▼
    Fit model on Train
    Predict horizon steps
    Evaluate on Test
    │
    ▼
Aggregate metrics across origins
```

#### Baseline Models
| Baseline | Description |
|----------|-------------|
| `seasonal_naive` | Repeat last seasonal cycle (s=7) |
| `moving_average` | 7-day moving average |
| `drift` | Linear trend extrapolation |

#### Parallel Execution
- **Baselines**: Parallel (ThreadPoolExecutor, max 3 workers)
- **Main models**: Sequential (avoid resource contention)
- **Origins**: Parallel for baselines only

### 4. Forecast Service (`app/services/forecast_service.py`)

#### Main Entry Point
```python
ForecastService.run(product_id, model="sarima", horizon=90)
    │
    ├─▶ Fetch history (dynamic window: min(max(horizon*2, 180), 730))
    ├─▶ Validate horizon vs data sufficiency
    ├─▶ Select model: sarima/arima/ensemble
    ├─▶ Run forecast
    ├─▶ Validate horizon (sufficiency warnings)
    ├─▶ Save to cache (forecast_cache table)
    ├─▶ Update monitoring (async)
    └─▶ Return standardized result
```

#### Horizon Validation
```python
def validate_horizon(history, horizon, model):
    # 1. Cap at MAX_HORIZON_DAYS (365)
    # 2. Min history: SARIMA=14, ARIMA=20, Ensemble=max(14,20)=20
    # 3. Horizon reasonableness:
    #    - horizon > 4*history_len → "limited" (warning)
    #    - horizon > 2*history_len → "limited" (warning)
    #    - horizon > history_len → "limited" (warning)
    #    - else → "sufficient"
```

#### Portfolio Forecasting
```python
# Two modes:
# 1. PORTFOLIO_RUN_ACTUAL_MODELS=True: Run actual model per product (cached 1hr)
# 2. PORTFOLIO_RUN_ACTUAL_MODELS=False: 7-day MA baseline (honest labeling)

# Output includes:
# - model_used: actual model used (sarima/arima/moving_average)
# - data_sufficiency: sufficient/limited/insufficient/baseline_only
# - warning: horizon warnings if any
```

#### Backtesting
```python
ForecastService.backtest(product_id, model="sarima", horizon=30, config)
    │
    ├─▶ Fetch 365 days history
    ├─▶ Validate min 60 days
    ├─▶ Run rolling_origin_backtest
    ├─▶ Run baseline comparison
    ├─▶ Aggregate metrics
    ├─▶ Persist results (forecast_backtest_results table)
    └─▶ Return aggregated metrics + baselines
```

### 5. Monitoring Service (`app/services/monitoring_service.py`)

#### Metrics Computation
```python
MonitoringService.compute_metrics(sku, model, window_days=7)
    │
    ├─▶ Fetch actual vs predicted (last window_days)
    ├─▶ Compute metrics (MAE, MAPE, RMSE, WAPE, MASE, Bias)
    ├─▶ Compare to baseline (first evaluation window)
    ├─▶ Detect degradation (MAE/MAPE increase)
    ├─▶ Determine health status (healthy/warning/degraded/critical)
    ├─▶ Save metrics + generate alerts if sustained degradation
    └─▶ Return metrics + status
```

#### Degradation Detection
```python
# Thresholds (configurable):
# WARNING: 10% increase
# DEGRADED: 25% increase  
# CRITICAL: 50% increase

# Sustained degradation: 7+ consecutive days degraded/critical
```

#### 8.3 Alerting
- Severity: info, warning, degraded, critical
- Deduplication: same SKU+model+type+date
- Status: new → reviewed → acknowledged → resolved

### 5. API Layer (`app/routes/ai.py`)

#### Endpoints
| Endpoint | Method | Auth | Rate Limit | Description |
|----------|--------|------|------------|-------------|
| `/ai/forecast` | GET | ✓ | - | Forecast page |
| `/ai/forecast/run` | POST | ✓ | 30/min | Run forecast |
| `/ai/forecast/backtest` | POST | ✓ | 10/min | Run backtest |
| `/ai/forecast/backtest` | GET | ✓ | - | Get backtest results |
| `/ai/forecast/portfolio` | GET | ✓ | 6/min | Portfolio forecast |
| `/ai/anomaly/run` | POST | ✓ | 30/min | Run anomaly detection |
| `/ai/anomaly/portfolio` | GET | ✓ | 6/min | Anomaly portfolio |
| `/ai/anomaly/benchmark` | GET | ✓ | 6/min | Synthetic benchmark |
| `/ai/anomaly/precision-recall` | GET | ✓ | - | Precision/recall from labels |
| `/ai/anomaly/fatigue` | GET | ✓ | - | Alert fatigue metrics |
| `/ai/monitoring/compute` | POST | ✓ | 10/min | Compute metrics |
| `/ai/monitoring/evaluate` | POST | ✓ | 10/min | Evaluate pending |

#### Request/Response Format
```python
# Forecast Request
{
    "product_id": 123,
    "model": "sarima",  # sarima, arima, ensemble
    "horizon": 90       # 7,15,30,45,60,90,120,150,180
}

# Forecast Response
{
    "success": true,
    "data": {
        "predictions": [...],
        "lower": [...],
        "upper": [...],
        "history": [...],
        "baseline": 42.5,
        "accuracy": 87.5,
        "model": "sarima",
        "model_used": "sarima",
        "data_sufficiency": "sufficient",
        "dates": ["2026-10-01", ...],
        "model_label": "SARIMA (Seasonal)",
        "product": {"id": 123, "sku": "SKU-001", "name": "Widget"}
    }
```

### 6. Frontend (`app/templates/ai/forecast.html`, `app/static/js/ai-features.js`)

#### Forecast Page Components
- Product selector (dropdown)
- Horizon selector (7,15,30,45,60,90,120,150,180)
- Model selector (SARIMA, ARIMA, Ensemble)
- Run Forecast / Run Backtest buttons
- Plotly chart (history + forecast + confidence bands)
- Metrics cards (Accuracy, Predicted Demand, Confidence Band, Runtime)
- Monitoring section (MAE, MAPE, RMSE, Observations)
- Backtest results table
- Portfolio forecast table

#### JavaScript Module: `StockflowForecast`
```javascript
init(config) {
    // config: {product, horizon, model, runButton, backtestButton, 
    //          chartId, badge, metrics, table, backtestTable, 
    //          backtestBaselines, backtestSection, runUrl, backtestUrl, 
    //          portfolioUrl, monitoring}
}
```

### 7. Data Flow

#### Forecast Request Flow
```
User Request
    │
    ▼
/ai/forecast/run (POST)
    │
    ▼
ForecastService.run(product_id, model, horizon)
    │
    ├─▶ MovementRepository.daily_for_product(product_id, days=history_days)
    │       │
    │       ▼
    │   sp_movement_daily_for_product(product_id, history_days)
    │       │
    │       ▼
    │   generate_series + LEFT JOIN movements (OUT only)
    │       │
    │       ▼
    │   Returns: [{day: date, total: int}, ...]  // continuous dates
    │
    ▼
ForecastService.validate_horizon(history, horizon, model)
    │
    ▼
Model Selection:
    sarima → forecast_with_sarima(history, horizon)
    arima  → forecast_with_arima(history, horizon)
    ensemble → forecast_ensemble(history, horizon)
    │
    ▼
Model Execution:
    │
    ├─▶ SARIMA: _infer_seasonal_period → _select_sarima_order → SARIMAX.fit → forecast
    ├─▶ ARIMA: ARIMA(1,1,1).fit(method='statespace') → forecast
    └─▶ Ensemble: parallel SARIMA + ARIMA → average
    │
    ▼
Result Processing:
    ├─▶ Add product info, model_label, model_used, data_sufficiency, warning
    ├─▶ ForecastRepository.save(product_id, model, horizon, result)
    ├─▶ _update_monitoring(sku, model, history)  // async
    └─▶ Return result
```

#### Backtest Flow
```
User Request
    │
    ▼
/ai/forecast/backtest (POST)
    │
    ▼
ForecastService.backtest(product_id, model, horizon, config)
    │
    ├─▶ Fetch 365 days history
    ├─▶ Validate min 60 days
    ├─▶ rolling_origin_backtest(history, config, model)
    │       │
    │       ├─▶ Calculate origins (min_train to N-horizon, step=7)
    │       ├─▶ For each origin: train on [0:origin], test on [origin:origin+horizon]
    │       └─▶ Aggregate metrics across origins
    │
    ├─▶ run_baseline_comparison(history, config, model)
    │       ├─▶ Primary model backtest
    │       └─▶ Baselines in parallel (seasonal_naive, moving_average, drift)
    │
    ├─▶ Aggregate results (mean, std, min, max per metric)
    ├─▶ Persist to forecast_backtest_results table
    └─▶ Return aggregated metrics + baselines
```

### 8. Database Schema

#### Core Tables
```sql
-- Forecast cache (per product/model/horizon)
CREATE TABLE forecast_cache (
    id SERIAL PRIMARY KEY,
    product_id INT REFERENCES products(id) ON DELETE CASCADE,
    model VARCHAR(30) NOT NULL,
    horizon INT NOT NULL,
    payload JSONB NOT NULL,
    accuracy NUMERIC(5,2),
    generated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (product_id, model, horizon)
);

-- Backtest results
CREATE TABLE forecast_backtest_results (
    id BIGSERIAL PRIMARY KEY,
    product_id INT REFERENCES products(id) ON DELETE CASCADE,
    sku VARCHAR(50) NOT NULL,
    model_name VARCHAR(30) NOT NULL,
    baseline_name VARCHAR(30),  -- NULL for primary model
    origin_date DATE NOT NULL,
    horizon INT NOT NULL,
    mae NUMERIC(10,3),
    mape NUMERIC(7,2),
    rmse NUMERIC(10,3),
    wape NUMERIC(7,2),
    mase NUMERIC(7,3),
    bias NUMERIC(10,3),
    interval_coverage NUMERIC(5,2),
    observation_count INT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Monitoring tables
CREATE TABLE forecast_predictions (
    id SERIAL PRIMARY KEY,
    sku VARCHAR(50) NOT NULL,
    model_name VARCHAR(30) NOT NULL,
    forecast_generated_at TIMESTAMP DEFAULT NOW(),
    forecast_date DATE NOT NULL,
    predicted_value NUMERIC(12,3) NOT NULL,
    actual_value NUMERIC(12,3),
    forecast_horizon INT DEFAULT 1,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE forecast_monitoring_metrics (
    id SERIAL PRIMARY KEY,
    sku VARCHAR(50) NOT NULL,
    model_name VARCHAR(30) NOT NULL,
    monitoring_date DATE NOT NULL,
    aggregation_period VARCHAR(10) DEFAULT 'daily',
    observation_count INT DEFAULT 0,
    mae NUMERIC(10,3),
    mape NUMERIC(7,2),
    rmse NUMERIC(10,3),
    mean_error NUMERIC(10,3),
    error_std NUMERIC(10,3),
    zero_demand_count INT DEFAULT 0,
    baseline_mae NUMERIC(10,3),
    baseline_mape NUMERIC(7,2),
    mae_change_percent NUMERIC(7,2),
    mape_change_percent NUMERIC(7,2),
    model_status VARCHAR(20) DEFAULT 'healthy',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE model_monitoring_alerts (
    id SERIAL PRIMARY KEY,
    sku VARCHAR(50) NOT NULL,
    model_name VARCHAR(30) NOT NULL,
    alert_date DATE NOT NULL,
    alert_type VARCHAR(40) NOT NULL,
    severity VARCHAR(20) DEFAULT 'warning',
    metric VARCHAR(30) NOT NULL,
    baseline_value NUMERIC(10,3),
    current_value NUMERIC(10,3),
    change_percent NUMERIC(7,2),
    message TEXT,
    recommended_action TEXT,
    status VARCHAR(20) DEFAULT 'new',
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Data Leakage Prevention Architecture

### Temporal Boundaries
```
┌─────────────────────────────────────────────────────────────┐
│                    TEMPORAL BOUNDARIES                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Training Data          Validation Data      Test Data       │
│  ─────────────────      ─────────────────    ─────────────  │
│  T ≤ cutoff_date        cutoff < T ≤ val_end  val_end < T   │
│                                                              │
│  Forecast Cutoff: The boundary between training and future  │
│  No data with date > forecast_cutoff_date enters training   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Leakage Prevention Mechanisms

| Layer | Mechanism |
|-------|-----------|
| **Database** | `sp_movement_daily_for_product` uses `CURRENT_DATE - (p_days - 1)` cutoff |
| **Service** | `validate_horizon()` checks history length vs horizon |
| **Backtest** | Expanding window: train=[0:origin], test=[origin:origin+horizon] |
| **Model Selection** | Baseline comparison on validation window only |
| **Preprocessing** | No future data in rolling statistics (expanding window only) |
| **Seasonality Detection** | Computed on training window only |
| **Model Selection** | Isolated from test set (no test data in model selection) |

### Leakage Tests
```python
# tests/test_leakage.py
def test_no_future_data_in_training():
    """Verify training data never includes future dates."""
    
def test_walk_forward_temporal_ordering():
    """Verify train_end < test_start for all folds."""
    
def test_no_future_in_seasonality_detection():
    """Seasonality detection uses only training window."""
    
def test_no_future_in_preprocessing():
    """Rolling statistics use only historical data."""
    
def test_model_selection_isolated():
    """Model selection never sees test data."""
```

---

## Security Architecture

### Input Validation
```python
# Forecast request validation
product_id: int (validated via ProductRepository.find)
model: enum ["sarima", "arima", "ensemble"]
horizon: int (1-365, capped at MAX_HORIZON_DAYS)
```

### Rate Limiting
```python
# Flask-Limiter
@limiter.limit("30 per minute")  # forecast run
@limiter.limit("10 per minute")  # backtest
@limiter.limit("6 per minute")   # portfolio
@limiter.limit("30 per minute")  # anomaly
```

### Authentication/Authorization
```python
@login_required
@write_roles_required  # admin/manager only for write operations
```

### SQL Injection Prevention
- All queries via stored procedures (`sp_*`)
- Parameterized queries only
- No dynamic SQL construction

---

## Performance Architecture

### Caching Strategy
| Cache | TTL | Key Pattern | Invalidation |
|-------|-----|-------------|--------------|
| Portfolio forecast | 1hr | `forecast_portfolio:{horizon}:{model}` | On product CRUD |
| Product list | 60s | `ai_product_list` | On product CRUD |
| Forecast cache | Persistent | `forecast_cache` table | On new forecast |
| Backtest results | Persistent | `forecast_backtest_results` table | On new backtest |

### Concurrency Control
- **Forecast**: Sequential per request (model fitting is CPU-intensive)
- **Baselines**: Parallel (ThreadPoolExecutor, max 3 workers)
- **Backtest origins**: Parallel for baselines only
- **Ensemble**: Parallel SARIMA + ARIMA (ThreadPoolExecutor, 2 workers)

### Timeouts
- Model fitting: Implicit via statsmodels (no explicit timeout)
- Request timeout: Flask default (30s)
- Recommendation: Add explicit timeout wrapper for production

---

## Deployment Architecture

### Container/Process Model
```
┌─────────────────────────────────────────────────────────────┐
│                    RENDER DEPLOYMENT                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────┐    ┌──────────────────┐                    │
│  │  PostgreSQL │◀───│  Gunicorn (1w)   │                    │
│  │  (Managed)  │    │  2 threads       │                    │
│  └─────────────┘    └────────┬─────────┘                    │
│                               │                              │
│                    ┌──────────┴──────────┐                   │
│                    ▼                     ▼                   │
│             ┌─────────────┐      ┌─────────────┐            │
│             │  Forecast   │      │  Monitoring │            │
│             │  Thread     │      │  Thread     │            │
│             └─────────────┘      └─────────────┘            │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Configuration
```yaml
# render.yaml
services:
  - type: web
    name: inventorylogix
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn run:app --workers 1 --threads 2 --timeout 120
    envVars:
      - key: FLASK_ENV
        value: production
      - key: DATABASE_URL
        fromDatabase: inventory-db
      - key: SECRET_KEY
        generateValue: true
    autoDeploy: true
```

### Database Connection Pool
```python
# app/database/connection.py
ThreadedConnectionPool(
    minconn=1,
    maxconn=20,
    keepalives_idle=30,
    keepalives_interval=10,
    keepalives_count=3
)
```

---

## Error Handling & Resilience

### Forecast Failure Chain
```
forecast_with_sarima()
    │
    ├─▶ Success → return result
    │
    └─▶ Exception → LOGGER.warning → forecast_with_arima()
                          │
                          ├─▶ Success → return result
                          │
                          └─▶ Exception → _moving_average_forecast()
```

### Backtest Resilience
- Individual origin failures → skip, continue
- Model convergence failure → skip origin, log warning
- Insufficient test data → skip origin
- Empty results → return empty list (not error)

### Monitoring Resilience
- Evaluation failures → logged, not raised
- Metric computation failures → skipped, logged
- Alert generation failures → logged, not raised

---

## Observability

### Logging
```python
LOGGER = logging.getLogger(__name__)

# Forecast
LOGGER.warning("Horizon validation warning for product %s: %s", sku, warning)
LOGGER.warning("SARIMA forecast failed: %s", exc)
LOGGER.warning("ARIMA forecast failed: %s", exc)

# Backtest
LOGGER.warning("Backtest failed for product %s: %s", sku, exc)

# Monitoring
LOGGER.debug("Monitoring update skipped", exc_info=True)
```

### Metrics to Monitor
| Metric | Source | Alert Threshold |
|--------|--------|-----------------|
| Forecast latency (p95) | Request timing | > 10s |
| Model convergence rate | Training logs | < 95% |
| Backtest duration | Backtest logs | > 60s |
| Cache hit rate | Cache stats | < 80% |
| Model degradation alerts | MonitoringService | Any critical |

---

## Disaster Recovery

### Backup Strategy
- PostgreSQL: Render managed (daily + PITR)
- Model cache: Rebuildable from source data
- Backtest results: Reproducible from source data

### Rollback Procedures
1. **Model rollback**: Revert `model_versions` champion flag
2. **Data rollback**: PostgreSQL PITR
3. **Code rollback**: Git revert + deploy

### RTO/RPO Targets
| Component | RTO | RPO |
|-----------|-----|-----|
| Database | 1 hour | 0 (PITR) |
| Forecast API | 5 min | 0 |
| Model cache | 1 min | 1 hour |
| Backtest results | 1 hour | 1 hour |

---

## Future Extensibility

### Planned Enhancements
1. **Exogenous Variables**: Promotions, holidays, weather
2. **Deep Learning**: LSTM/Transformer for complex patterns
3. **Hierarchical Forecasting**: Category/warehouse level
4. **Probabilistic Forecasting**: Full predictive distributions
5. **Automated Feature Engineering**: Automated lag/rolling features
6. **Multi-horizon Models**: Single model for all horizons

### Extension Points
```python
# New model registration
MODEL_REGISTRY = {
    "sarima": forecast_with_sarima,
    "arima": forecast_with_arima,
    "ensemble": forecast_ensemble,
    # "lstm": forecast_with_lstm,  # Future
    # "prophet": forecast_with_prophet,  # Future
}

# New baseline registration
BASELINE_REGISTRY = {
    "seasonal_naive": _seasonal_naive_forecast,
    "moving_average": _moving_average_forecast,
    "drift": _drift_forecast,
    # "croston": croston_forecast,  # Future
}
```

---

## Appendix: Key Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MAX_HORIZON_DAYS` | 365 | Maximum forecast horizon |
| `MIN_HISTORY_SARIMA` | 14 | Minimum days for SARIMA |
| `MIN_HISTORY_ARIMA` | 20 | Minimum days for ARIMA |
| `BACKTEST_MIN_TRAIN_DAYS` | 60 | Minimum training window |
| `BACKTEST_STEP_DAYS` | 7 | Step between origins |
| `BACKTEST_MAX_ORIGINS` | 10 | Maximum backtest origins |
| `PORTFOLIO_RUN_ACTUAL_MODELS` | False | Run actual models in portfolio |
| `PORTFOLIO_CACHE_TTL` | 3600 | Portfolio cache TTL (seconds) |
| `MONITORING_WINDOW_DAYS` | 30 | Monitoring evaluation window |
| `DEGRADATION_WINDOW_DAYS` | 7 | Sustained degradation window |
| `RETRAIN_SCHEDULE` | "weekly" | Retraining frequency |
| `CHAMPION_CHALLENGER_THRESHOLD` | 0.05 | 5% improvement required |

---

*Architecture version: 1.0*
*Last updated: 2026-09-30*
*Status: Ready for implementation*