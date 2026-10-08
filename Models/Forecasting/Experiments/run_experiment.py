#!/usr/bin/env python
"""
Isolated Testing Environment for ARIMA/SARIMA Forecasting
Tests models on real InventoryLogix data with walk-forward validation.
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

def get_demand_data(product_id, days=365):
    """Fetch demand data for a product."""
    with app.app_context():
        from app.repositories.movement_repo import MovementRepository
        rows = MovementRepository.daily_for_product(product_id, days=days)
        history = [{"ds": r["day"].isoformat(), "y": int(r["total"])} for r in rows]
        return history

def get_all_products():
    """Get all active products."""
    with app.app_context():
        from app.repositories.product_repo import ProductRepository
        products, _ = ProductRepository.list(limit=200)
        return products

def run_experiment():
    """Run forecasting experiments on real data."""
    print("=" * 80)
    print("INVENTORYLOGIX FORECASTING EXPERIMENT")
    print("=" * 80)
    
    with app.app_context():
        from app.ml.forecasting import (
            forecast_with_sarima, forecast_with_arima, 
            forecast_ensemble, _moving_average_forecast
        )
        from app.ml.backtest import (
            BacktestConfig, rolling_origin_backtest, 
            run_baseline_comparison, aggregate_backtest_results
        )
        from app.repositories.product_repo import ProductRepository
        from app.repositories.movement_repo import MovementRepository
        
        # Get products with sufficient data
        products, _ = ProductRepository.list(limit=200)
        print(f"\nFound {len(products)} products")
        
        # Filter products with sufficient data
        valid_products = []
        for p in products[:50]:  # Test first 50
            rows = MovementRepository.daily_for_product(p["id"], days=365)
            history = [{"ds": r["day"].isoformat(), "y": int(r["total"])} for r in rows]
            non_zero = sum(1 for h in history if h["y"] > 0)
            if len(history) >= 60 and non_zero >= 20:
                valid_products.append({
                    "id": p["id"],
                    "sku": p["sku"],
                    "name": p["name"],
                    "history_len": len(history),
                    "non_zero_days": non_zero,
                    "history": history
                })
        
        print(f"Products with sufficient data: {len(valid_products)}")
        
        if not valid_products:
            print("No products with sufficient data!")
            return
        
        # Test on first 5 products
        test_products = valid_products[:5]
        horizons = [7, 15, 30, 45, 60, 90, 120, 150, 180]
        
        results = []
        
        for p in test_products:
            print(f"\n{'='*80}")
            print(f"Testing SKU: {p['sku']} - {p['name']}")
            print(f"History: {p['history_len']} days, {p['non_zero_days']} non-zero days")
            print(f"{'='*80}")
            
            history = p["history"]
            
            for horizon in horizons:
                print(f"\n  Horizon: {horizon} days")
                
                # Test each model
                models = {
                    "SARIMA": forecast_with_sarima,
                    "ARIMA": forecast_with_arima,
                    "Ensemble": forecast_ensemble,
                    "MovingAvg": _moving_average_forecast
                }
                
                for model_name, model_func in models.items():
                    try:
                        result = model_func(p["history"], horizon)
                        print(f"    {model_name:12s}: model={result['model']:12s}, "
                              f"pred_sum={sum(result['predictions']):.1f}, "
                              f"acc={result.get('accuracy', 'N/A')}")
                    except Exception as e:
                        print(f"    {model_name:12s}: ERROR - {e}")
        
        # Run backtest on one product
        print(f"\n{'='*80}")
        print("BACKTESTING")
        print(f"{'='*80}")
        
        if test_products:
            p = test_products[0]
            print(f"\nBacktesting SKU: {p['sku']}")
            
            for horizon in [30, 60, 90, 180]:
                print(f"\n  Horizon: {horizon} days")
                try:
                    from app.ml.backtest import BacktestConfig, rolling_origin_backtest, run_baseline_comparison, aggregate_backtest_results
                    
                    config = BacktestConfig(horizon=horizon, step_days=7, min_train_days=60, max_origins=10)
                    
                    # Test SARIMA
                    results = rolling_origin_backtest(p["history"], config, "sarima")
                    if results:
                        agg = aggregate_backtest_results(results)
                        print(f"    SARIMA:  MAE={agg.get('mae',{}).get('mean',0):.2f}, "
                              f"RMSE={agg.get('rmse',{}).get('mean',0):.2f}, "
                              f"WAPE={agg.get('wape',{}).get('mean',0):.1f}%, "
                              f"MASE={agg.get('mase',{}).get('mean',0):.3f}, "
                              f"Coverage={agg.get('interval_coverage',{}).get('mean',0):.1f}%")
                    
                    # Baselines
                    baselines = run_baseline_comparison(p["history"], config, "sarima")
                    for name, results in baselines.items():
                        if name != "sarima" and results:
                            agg = aggregate_backtest_results(results)
                            print(f"    {name:15s}: MAE={agg.get('mae',{}).get('mean',0):.2f}, "
                                  f"WAPE={agg.get('wape',{}).get('mean',0):.1f}%")
                
                except Exception as e:
                    print(f"    ERROR: {e}")

if __name__ == "__main__":
    run_experiment()