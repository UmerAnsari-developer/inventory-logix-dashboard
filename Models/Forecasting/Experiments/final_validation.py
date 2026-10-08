#!/usr/bin/env python
"""Reduced final validation: model selection + forecast smoke test."""
import sys
sys.path.insert(0, r"D:\MCA\3rd Sem\Mini Project\Inventory Logistics Optimization Dashboard")

import warnings
warnings.filterwarnings('ignore')

from app import create_app
app = create_app()

def run_reduced_validation():
    print("=" * 80)
    print("REDUCED FINAL VALIDATION")
    print("=" * 80)

    with app.app_context():
        from app.services.forecast_service import ForecastService
        from app.repositories.product_repo import ProductRepository
        from app.repositories.movement_repo import MovementRepository

        products, _ = ProductRepository.list(limit=200)

        # Pick 1 product with good data
        target = None
        for p in products:
            rows = MovementRepository.daily_for_product(p["id"], days=365)
            history = [{"ds": r["day"].isoformat(), "y": int(r["total"])} for r in rows]
            non_zero = sum(1 for h in history if h["y"] > 0)
            if len(history) >= 240 and non_zero >= 100:
                target = {"id": p["id"], "sku": p["sku"], "name": p["name"]}
                break

        if not target:
            print("No suitable product found")
            return

        print(f"\nSKU: {target['sku']} - {target['name']}")

        # Backtest on 3 representative horizons (short/medium/long)
        for horizon in [7, 30, 90]:
            try:
                result = ForecastService.backtest(target["id"], model="prophet", horizon=horizon)
                sel = result.get("selection", {})
                metrics = result.get("metrics", {})
                mae = metrics.get("mae", {}).get("mean")
                wape = metrics.get("wape", {}).get("mean")
                mase = metrics.get("mase", {}).get("mean")
                cov = metrics.get("interval_coverage", {}).get("mean")
                best = sel.get("best_model", "?")
                impr = sel.get("improvement_pct")
                reason = sel.get("reason", "")
                leakage = result.get("leakage_ok")
                used = result.get("models_actually_used")
                impr_str = "—" if impr is None else str(impr) + "%"
                print(f"  H={horizon:3d} | MAE={mae if mae is None else round(mae,2)} | "
                      f"WAPE={wape if wape is None else round(wape,1)}% | "
                      f"MASE={mase if mase is None else round(mase,2)} | "
                      f"Cov={cov if cov is None else round(cov,0)}% | "
                      f"Best={best} | impr={impr_str}")
                print(f"        | leakage_ok={leakage} | models_used={used} | {reason}")
            except Exception as e:
                print(f"  H={horizon:3d} | ERROR: {e}")

        # Forecast smoke test — all 9 horizons (single fit each, fast)
        print("\nFORECAST SMOKE TEST (all 9 horizons):")
        for horizon in [7, 15, 30, 45, 60, 90, 120, 150, 180]:
            try:
                result = ForecastService.run(target["id"], model="prophet", horizon=horizon)
                print(f"  H={horizon:3d} | model_used={result.get('model_used'):15s} | "
                      f"sufficiency={result.get('data_sufficiency'):12s} | "
                      f"preds={len(result.get('predictions', [])):3d} | "
                      f"acc={result.get('accuracy')}")
            except Exception as e:
                print(f"  H={horizon:3d} | ERROR: {e}")

if __name__ == "__main__":
    run_reduced_validation()