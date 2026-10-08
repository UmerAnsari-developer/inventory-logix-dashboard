#!/usr/bin/env python
"""
Comprehensive Model Validation Experiment
Tests ARIMA/SARIMA with proper validation and diagnostics.
"""

import sys
import os
sys.path.insert(0, r"D:\MCA\3rd Sem\Mini Project\Inventory Logistics Optimization Dashboard")

import pandas as pd
import numpy as np
from datetime import date, timedelta
import json
import warnings
warnings.filterwarnings('ignore')

# Setup Flask app context
from app import create_app
app = create_app()

def run_comprehensive_validation():
    """Run comprehensive model validation with diagnostics."""
    print("=" * 80)
    print("COMPREHENSIVE MODEL VALIDATION")
    print("=" * 80)
    
    with app.app_context():
        from app.ml.forecasting import (
            forecast_with_sarima, forecast_with_arima, 
            forecast_ensemble, _moving_average_forecast,
            _infer_seasonal_period, _select_sarima_order
        )
        from app.ml.backtest import (
            BacktestConfig, rolling_origin_backtest, 
            run_baseline_comparison, aggregate_backtest_results
        )
        from app.repositories.product_repo import ProductRepository
        from app.repositories.movement_repo import MovementRepository
        from app.ml.forecasting import _check_arima
        
        print(f"Statsmodels available: {_check_arima()}")
        
        # Get products with sufficient data
        products, _ = ProductRepository.list(limit=200)
        print(f"\nTotal products: {len(products)}")
        
        # Analyze data characteristics for each product
        print("\n" + "="*80)
        print("DATA CHARACTERISTICS ANALYSIS")
        print("="*80)
        
        product_analysis = []
        for p in products[:30]:  # Analyze first 30 products
            rows = MovementRepository.daily_for_product(p["id"], days=365)
            history = [{"ds": r["day"].isoformat(), "y": int(r["total"])} for r in rows]
            
            values = [h["y"] for h in history]
            non_zero = sum(1 for v in values if v > 0)
            zero_pct = (len(values) - non_zero) / len(values) * 100
            mean_val = np.mean(values) if values else 0
            std_val = np.std(values) if len(values) > 1 else 0
            cv = std_val / mean_val if mean_val > 0 else 0
            
            # Check for seasonality (simple autocorr at lag 7)
            seasonal_corr = 0
            if len(values) >= 14:
                lag_corr = sum((values[i] - np.mean(values)) * (values[i-7] - np.mean(values)) 
                              for i in range(7, len(values)))
                var = sum((v - np.mean(values))**2 for v in values)
                if var > 0:
                    seasonal_corr = lag_corr / var
            
            # Trend check
            trend = values[-1] - values[0] if len(values) > 1 else 0
            trend_pct = abs(trend) / np.mean(values) * 100 if np.mean(values) > 0 else 0
            
            p_info = {
                "id": p["id"],
                "sku": p["sku"],
                "name": p["name"],
                "n_obs": len(values),
                "non_zero": non_zero,
                "zero_pct": zero_pct,
                "mean": mean_val,
                "std": std_val,
                "cv": cv,
                "seasonal_corr": seasonal_corr,
                "trend_pct": trend_pct,
                "has_trend": trend_pct > 10,
                "has_seasonality": seasonal_corr > 0.3
            }
            product_analysis.append(p_info)
            
            print(f"SKU: {p['sku']:12s} | n={len(values):3d} | nz={non_zero:3d} | "
                  f"zero%={zero_pct:5.1f}% | mean={mean_val:6.1f} | cv={cv:.2f} | "
                  f"seasonal_corr={seasonal_corr:.3f} | trend%={trend_pct:5.1f}% | "
                  f"trend={p_info['has_trend']} | seasonal={p_info['has_seasonality']}")
        
        # Summary statistics
        print(f"\n{'='*80}")
        print("SUMMARY STATISTICS")
        print(f"{'='*80}")
        n_products = len(product_analysis)
        print(f"Products analyzed: {n_products}")
        print(f"Avg observations: {np.mean([p['n_obs'] for p in product_analysis]):.0f}")
        print(f"Avg zero%: {np.mean([p['zero_pct'] for p in product_analysis]):.1f}%")
        print(f"Avg CV: {np.mean([p['cv'] for p in product_analysis]):.2f}")
        print(f"Products with trend: {sum(1 for p in product_analysis if p['has_trend'])}")
        print(f"Products with seasonality: {sum(1 for p in product_analysis if p['has_seasonality'])}")
        print(f"Avg seasonal correlation: {np.mean([p['seasonal_corr'] for p in product_analysis]):.3f}")
        
        # Test model behavior on different data types
        print(f"\n{'='*80}")
        print("MODEL BEHAVIOR ANALYSIS")
        print(f"{'='*80}")
        
        # Test on different data patterns
        test_cases = [
            ("Stable demand", [50]*100),
            ("Trending up", list(range(10, 110))),
            ("Trending down", list(range(100, 10, -1))),
            ("Weekly seasonal", [50 + 10*np.sin(2*np.pi*i/7) + np.random.normal(0,2) for i in range(100)]),
            ("Monthly seasonal", [50 + 10*np.sin(2*np.pi*i/30) + np.random.normal(0,2) for i in range(200)]),
            ("Intermittent", [0 if i%3==0 else np.random.poisson(5) for i in range(100)]),
            ("Spiky", [10 if i%20==0 else np.random.poisson(5) for i in range(100)]),
        ]
        
        from app.ml.forecasting import (
            forecast_with_sarima, forecast_with_arima, 
            forecast_ensemble, _moving_average_forecast,
            _infer_seasonal_period, _select_sarima_order
        )
        
        print(f"\n{'='*80}")
        print("SYNTHETIC DATA TESTS")
        print(f"{'='*80}")
        
        for name, values in test_cases:
            history = [{"ds": (date.today() - timedelta(days=len(values)-i)).isoformat(), "y": v} 
                       for i, v in enumerate(values)]
            
            print(f"\n{name}: n={len(values)}, mean={np.mean(values):.1f}, "
                  f"std={np.std(values):.1f}, zeros={sum(1 for v in values if v==0)}")
            
            # Test seasonal period inference
            s = _infer_seasonal_period(history)
            print(f"  Inferred seasonal period: {s}")
            
            # Test SARIMA order selection
            try:
                (p,d,q), (P,D,Q,s) = _select_sarima_order(history, s)
                print(f"  SARIMA order: ({p},{d},{q}) x ({P},{D},{Q},{s})")
            except Exception as e:
                print(f"  SARIMA order selection failed: {e}")
            
            # Test models
            for model_name, model_func in [
                ("SARIMA", forecast_with_sarima),
                ("ARIMA", forecast_with_arima),
                ("Ensemble", forecast_ensemble),
                ("MA", _moving_average_forecast)
            ]:
                try:
                    result = model_func(history, horizon=30)
                    print(f"  {model_name:8s}: model={result['model']:12s}, "
                          f"pred_sum={sum(result['predictions']):.1f}, "
                          f"acc={result.get('accuracy', 'N/A')}")
                except Exception as e:
                    print(f"  {model_name:8s}: ERROR - {e}")
        
        # Test backtest with proper metrics
        print(f"\n{'='*80}")
        print("BACKTEST VALIDATION WITH PROPER METRICS")
        print(f"{'='*80}")
        
        # Get a product with good data
        products, _ = ProductRepository.list(limit=200)
        for p in products[:10]:
            rows = MovementRepository.daily_for_product(p["id"], days=365)
            history = [{"ds": r["day"].isoformat(), "y": int(r["total"])} for r in rows]
            non_zero = sum(1 for h in history if h["y"] > 0)
            if len(history) >= 180 and non_zero >= 50:
                print(f"\nBacktesting SKU: {p['sku']} ({p['name']})")
                print(f"  History: {len(history)} days, {non_zero} non-zero days")
                
                for horizon in [30, 60, 90, 180]:
                    print(f"\n  Horizon: {horizon} days")
                    try:
                        config = BacktestConfig(horizon=horizon, step_days=7, min_train_days=60, max_origins=10)
                        
                        # Test SARIMA
                        results = rolling_origin_backtest(history, config, "sarima")
                        if results:
                            agg = aggregate_backtest_results(results)
                            print(f"  SARIMA:  MAE={agg.get('mae',{}).get('mean',0):.2f}, "
                                  f"RMSE={agg.get('rmse',{}).get('mean',0):.2f}, "
                                  f"WAPE={agg.get('wape',{}).get('mean',0):.1f}%, "
                                  f"MASE={agg.get('mase',{}).get('mean',0):.3f}, "
                                  f"Bias={agg.get('bias',{}).get('mean',0):.2f}, "
                                  f"Coverage={agg.get('interval_coverage',{}).get('mean',0):.1f}%")
                        
                        # Baselines
                        baselines = run_baseline_comparison(history, config, "sarima")
                        for name, results in baselines.items():
                            if name != "sarima" and results:
                                agg = aggregate_backtest_results(results)
                                print(f"  {name:15s}: MAE={agg.get('mae',{}).get('mean',0):.2f}, "
                                      f"WAPE={agg.get('wape',{}).get('mean',0):.1f}%, "
                                      f"MASE={agg.get('mase',{}).get('mean',0):.3f}")
                        
                        # Check if SARIMA actually used seasonal model
                        sarima_results = rolling_origin_backtest(history, config, "sarima")
                        if sarima_results:
                            models_used = set(r.model_name for r in sarima_results)
                            print(f"  Models used in backtest: {models_used}")
                    
                    except Exception as e:
                        print(f"  ERROR: {e}")
                break

if __name__ == "__main__":
    run_comprehensive_validation()