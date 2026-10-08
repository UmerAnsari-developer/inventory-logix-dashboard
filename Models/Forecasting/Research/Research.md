# InventoryLogix Forecasting Research Document

## Executive Summary

This document analyzes the current ARIMA/SARIMA forecasting implementation in InventoryLogix and identifies gaps against the requirements for a production-ready demand forecasting system with horizons of 7, 15, 30, 45, 60, 90, 120, 150, 180 days.

## Current Implementation Analysis

### Existing Models
1. **SARIMA** (`forecast_with_sarima`) - Primary model with automatic seasonal order selection
2. **ARIMA** (`forecast_with_arima`) - Fixed ARIMA(1,1,1) with statespace method
3. **Ensemble** - Simple average of SARIMA + ARIMA predictions
4. **Moving Average** - Fallback baseline (7-day window)

### Current Capabilities
- ✅ SARIMA with automatic seasonal order selection (weekly seasonality s=7)
- ✅ ARIMA(1,1,1) with statespace fitting
- ✅ Ensemble averaging
- ✅ Moving average fallback
- ✅ Rolling-origin backtesting framework
- ✅ Baseline comparisons (seasonal_naive, moving_average, drift)
- ✅ Confidence intervals (95%)
- ✅ Multiple metrics (MAE, MAPE, RMSE, WAPE, MASE, bias, interval_coverage)
- ✅ Rolling-origin backtesting with expanding window
- ✅ Baseline comparison (seasonal_naive, moving_average, drift)
- ✅ Model monitoring with degradation detection
- ✅ Portfolio forecasting with caching

### Current Horizons Supported
- UI supports: 30, 60, 90, 180, 365 days
- Required: 7, 15, 30, 45, 60, 90, 120, 150, 180 days

### Data Pipeline
- Source: `sp_movement_daily_for_product` stored procedure
- Returns daily OUT movement totals per product
- Uses `generate_series` for continuous date series (includes zeros)
- History window: `min(max(horizon * 2, 180), 730)` days

## Gap Analysis

### Critical Gaps

| Requirement | Current Status | Gap |
|-------------|----------------|-----|
| Horizons 7, 15, 45, 120, 150 days | Not in UI dropdown | Missing UI options |
| ARIMA parameter grid search | Fixed ARIMA(1,1,1) | No parameter optimization |
| SARIMA seasonal order selection | Heuristic only | No AIC/BIC-based selection |
| Stationarity testing (ADF/KPSS) | Not implemented | Missing |
| Seasonal differencing | Not explicit | Handled by SARIMAX internally |
| ACF/PACF analysis | Not implemented | Missing |
| Walk-forward validation | Implemented | ✅ Exists |
| Baseline comparison | Implemented | ✅ Exists |
| Data leakage safeguards | Partial | Need validation |
| Data sufficiency analysis | Basic horizon check | Need deeper analysis |
| Data enrichment pipeline | Not implemented | Missing |
| Residual diagnostics | Not implemented | Missing |
| Prediction interval evaluation | Basic coverage | Need more metrics |
| Model retraining pipeline | Manual only | No automation |
| Data enrichment leakage safeguards | Not implemented | Missing |

### Data Quality Issues
1. **Sparse data**: `sp_movement_daily_for_product` returns zeros for days without movements
2. **Intermittent demand**: Many SKUs have zero-demand days
3. **Limited history**: Some SKUs have < 60 days of data
3. **Zero-demand days**: MAPE undefined on zero-demand days (handled in metrics)
4. **Seasonal period**: Hardcoded to weekly (s=7), no monthly/yearly detection

### Model Limitations
1. **SARIMA**: Fixed seasonal period (s=7), heuristic order selection
2. **ARIMA**: Fixed (1,1,1) order, no parameter search
3. **Ensemble**: Simple average, no weighted blending
4. **No exogenous variables**: No promotions, holidays, weather
5. **No model versioning**: No tracking of model versions
5. **No automated retraining**: Manual trigger only

## Data Analysis Requirements

### Phase 2: Data Collection
- Need to inspect actual data from `sp_movement_daily_for_product`
- Check data coverage per SKU
- Identify SKUs with sufficient history
- Analyze demand patterns (trend, seasonality, intermittency)

### Phase 3: Data Preparation & EDA
- Stationarity analysis (ADF/KPSS)
- ACF/PACF analysis
- Seasonality detection
- Outlier detection
- Missing data handling
- Zero-demand day analysis

### Phase 4: Feature Engineering / Time-Series Transformation
- Stationarity analysis
- Differencing (regular and seasonal)
- Trend analysis
- Seasonal decomposition
- Outlier treatment

## Model Training Requirements

### ARIMA
- Parameter grid: p∈{0,1,2}, d∈{0,1}, q∈{0,1,2}
- AIC/BIC-based selection
- Convergence handling
- Minimum 20 observations

### SARIMA
- Seasonal period detection (7, 30, 365)
- Seasonal order selection (P,D,Q,s)
- Seasonal differencing
- Minimum 2×seasonal_period observations

### Baselines
- Naive (last value)
- Seasonal Naive (same period last cycle)
- Moving Average (7-day)
- Drift (linear trend)

## Validation Framework

### Walk-Forward Validation
- Expanding window
- Configurable step size
- Minimum 60 days training
- Maximum 10 origins
- Step size: 7 days (configurable)

### Metrics
- MAE, RMSE, WAPE, MAPE, MASE, Bias
- Interval coverage (95%)
- Baseline improvement
- MASE for intermittent demand

### Baselines
- Naive (last value)
- Seasonal Naive (seasonal period)
- Moving Average (7-day)
- Drift (linear trend)

## Data Leakage Safeguards

### Current State
- ✅ Walk-forward validation (expanding window)
- ✅ Temporal ordering in backtest
- ❌ No explicit forecast_cutoff_date enforcement
- ❌ No validation of temporal ordering before model fit
- ❌ No leakage tests
- ❌ No preprocessing leakage checks

### Required Safeguards
1. Explicit `forecast_cutoff_date` in all operations
2. Temporal ordering validation before model fit
3. Future data exclusion in training queries
4. Model selection isolation from test set
5. Preprocessing leakage prevention
5. Seasonality detection leakage prevention
6. Database query safeguards
6. Leakage tests
6. Training dataset audit logging

## Data Enrichment Requirements

### Current State
- No data enrichment pipeline
- No external data sources
- No data enrichment validation
- No enrichment leakage safeguards

### Potential Enrichment Sources
1. **Promotions/Marketing calendar** - Binary flags + intensity
2. **Holidays/Events** - Calendar API integration
3. **Weather** - Temperature, precipitation
4. **Economic indicators** - CPI, fuel prices
6. **Competitor activity** - Price tracking
6. **Product lifecycle** - Launch date, phase

### Enrichment Safeguards
- Training/validation/test eligibility tracking
- Ingestion metadata recording
- Rollback capability
- Integrity verification

## Testing Requirements

### Unit Tests
- Data aggregation/preprocessing
- Stationarity tests
- Seasonality detection
- ARIMA/SARIMA model fitting
- Forecast generation
- Convergence failures

### Integration Tests
- Forecasting API
- Database interaction
- Dashboard rendering
- Model persistence
- Monitoring
- Retraining

### Horizons to Test
7, 15, 30, 45, 60, 90, 120, 150, 180 days

### Real-World Scenarios
- Normal demand
- Noisy demand
- Missing dates
- Zero-demand days
- Demand spikes/drops
- Changing demand
- Weak seasonality
- Sparse demand
- Extreme outliers
- Structural changes
- Insufficient history
- Convergence failure
- Long horizons (180 days)
- Large SKU count

## Monitoring & Retraining

### Current Monitoring
- Model performance tracking
- Degradation detection
- Alert generation
- Prediction interval monitoring

### Required Enhancements
- Automated retraining trigger
- Champion/challenger framework
- Model versioning
- Automated baseline comparison
- Drift detection
- Automated rollback

## Risk Assessment

### High Risk
1. **No parameter optimization** - Fixed ARIMA(1,1,1), heuristic SARIMA
2. **No stationarity testing** - May fit non-stationary models
3. **No residual diagnostics** - Model adequacy unknown
4. **No data leakage tests** - Potential leakage in validation
5. **No automated retraining** - Models stale over time
6. **No exogenous variables** - Missing promotions, holidays
7. **Fixed seasonal period** - Assumes weekly only

### Medium Risk
1. **Fixed ARIMA order** - No parameter search
2. **Heuristic SARIMA order** - No AIC/BIC selection
3. **No exogenous variables** - Missing promotions, holidays
4. **Fixed seasonal period** - Assumes weekly only
6. **No automated retraining** - Manual only
7. **No model versioning** - No rollback capability

### Low Risk
1. **UI horizons incomplete** - Missing 7,15,45,120,150
2. **Ensemble weighting** - Simple average only
3. **No prediction interval calibration** - Coverage not validated

## Recommendations

### Phase 1: Foundation (Week 1-2)
1. Add missing horizon options to UI (7, 15, 45, 120, 150)
2. Implement stationarity testing (ADF/KPSS)
3. Implement ACF/PACF analysis
4. Add stationarity testing to SARIMA pipeline
5. Implement seasonal differencing logic

### Phase 2: Model Improvement (Week 2-3)
1. Implement ARIMA parameter grid search (AIC/BIC)
2. Implement SARIMA seasonal order selection (AIC/BIC)
2. Add seasonal period detection (7, 30, 365)
3. Implement residual diagnostics (Ljung-Box)
4. Add prediction interval calibration
5. Implement seasonal naive baseline

### Phase 3: Validation & Testing (Week 3-4)
1. Implement data leakage safeguards
2. Add leakage tests
3. Implement data sufficiency analysis
4. Add residual diagnostics (Ljung-Box)
5. Add prediction interval evaluation
6. Implement data leakage tests

### Phase 4: Data Enrichment (Week 4-5)
1. Design enrichment pipeline
2. Add holiday calendar
3. Add promotion flags
4. Implement enrichment leakage safeguards
5. Run enrichment experiments

### Phase 5: Production Hardening (Week 5-6)
1. Automated retraining pipeline
2. Model versioning
2. Champion/challenger framework
3. Automated retraining triggers
4. Monitoring dashboard enhancements
4. Retraining automation
5. Rollback procedures

## Files to Modify

### Core ML Modules
- `app/ml/forecasting.py` - SARIMA/ARIMA improvements
- `app/ml/backtest.py` - Validation enhancements
- `app/ml/__init__.py` - Exports

### Services
- `app/services/forecast_service.py` - Horizon validation, model selection
- `app/services/monitoring_service.py` - Monitoring enhancements
- `app/services/settings_service.py` - Model configuration

### API Routes
- `app/routes/ai.py` - New endpoints for horizons, backtest config

### Templates
- `app/templates/ai/forecast.html` - Horizon dropdown
- `app/templates/ai/monitoring.html` - Model filter options
- `app/templates/ai/forecast.html` - Backtest config UI
- `app/templates/settings.html` - Model selection

### Tests
- `tests/test_ml.py` - New model tests
- `tests/test_backtest.py` - New backtest tests
- `tests/test_leakage.py` - Leakage tests (new)
- `tests/test_enrichment.py` - Enrichment tests (new)

### Database
- `app/database/schema.sql` - Model versioning tables
- `app/database/procedures.sql` - New stored procedures

## Success Criteria

### Minimum Viable
- [ ] All 9 horizons working (7,15,30,45,60,90,120,150,180)
- [ ] ARIMA with parameter search
- [ ] SARIMA with seasonal order selection
- [ ] Walk-forward validation for all horizons
- [ ] Baseline comparison (Naive, Seasonal Naive, MA, Drift)
- [ ] All 151 existing tests pass
- [ ] New tests for leakage, enrichment, horizons

### Production Ready
- [ ] Stationarity testing integrated
- [ ] Seasonal differencing
- [ ] Residual diagnostics
- [ ] Prediction interval calibration
- [ ] Data leakage safeguards
- [ ] Leakage tests passing
- [ ] Data sufficiency analysis
- [ ] Enrichment pipeline (if needed)
- [ ] Automated retraining pipeline
- [ ] Model versioning
- [ ] Champion/challenger framework
- [ ] Monitoring dashboard
- [ ] Retraining automation
- [ ] Rollback procedures
- [ ] All 151+ tests pass
- [ ] Security review passed
- [ ] Integration tests pass
- [ ] No regressions

## Open Questions

1. **Seasonal period**: Should we support monthly (30) and yearly (365) seasonality?
2. **Exogenous variables**: Which external data sources are available?
3. **Retraining frequency**: Daily, weekly, monthly?
4. **Model selection**: Automatic (AIC/BIC) or manual?
5. **Ensemble weighting**: Equal weight or performance-based?
6. **Prediction intervals**: Calibrate to 95% coverage?
5. **Retraining trigger**: Time-based, performance-based, or both?
6. **Rollback criteria**: What triggers rollback?

## Next Steps

1. **Create Research.md** - This document
2. **Create Plan.md** - Detailed implementation plan
3. **Create Architecture.md** - System architecture
4. **Set up isolated testing environment**
5. **Run experiments on real data**
6. **Evaluate models**
7. **Implement improvements**
8. **Run validation**
9. **Deploy**

---

*Document created: 2026-09-30*
*Status: Research phase complete - Ready for planning phase*