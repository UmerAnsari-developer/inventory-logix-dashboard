"""Quick smoke test for the InventoryLogix app.

Starts the app in a thread, hits a handful of endpoints, then exits.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

# Run with testing config so CSRF is disabled for the smoke test
os.environ["FLASK_ENV"] = "testing"

from app import create_app

app = create_app("testing")
client = app.test_client()

results = []


def record(label, response, expected=(200, 302, 303, 401, 404)):
    ok = response.status_code in expected
    results.append((ok, label, response.status_code, len(response.data or b"")))
    mark = "PASS" if ok else "FAIL"
    print(f"{mark} {label:40s} -> {response.status_code}  ({len(response.data or b'')} bytes)")


# Public
record("GET /auth/login", client.get("/auth/login"))
record("GET /api/health", client.get("/api/health"))

# Protected (unauth)
record("GET /  (unauth, landing)", client.get("/"), expected=(200,))
record("GET /inventory (unauth)", client.get("/inventory"))

# Login and test protected pages
login = client.post(
    "/auth/login",
    data={"username": "admin", "password": "Admin@123", "remember": "on"},
    follow_redirects=False,
)
record("POST /auth/login", login, expected=(200, 302, 303))

record("GET /  (auth)", client.get("/"))
record("GET /inventory (auth)", client.get("/inventory"))
record("GET /reorder-alerts (auth)", client.get("/reorder-alerts"))
record("GET /suppliers (auth)", client.get("/suppliers"))
record("GET /reports (auth)", client.get("/reports"))
record("GET /eoq-calculator (auth)", client.get("/eoq-calculator"))
record("GET /warehouses (auth)", client.get("/warehouses"))
record("GET /purchase-orders (auth)", client.get("/purchase-orders"))
record("GET /settings (auth)", client.get("/settings"))
record("GET /ai/forecast (auth)", client.get("/ai/forecast"))
record("GET /ai/anomaly (auth)", client.get("/ai/anomaly"))

# API smoke
record("GET /api/products (auth)", client.get("/api/products"))
record("GET /api/suppliers (auth)", client.get("/api/suppliers"))
record("GET /api/movements/recent", client.get("/api/movements/recent"))
record("POST /api/eoq/calculate",
       client.post("/api/eoq/calculate", json={"demand": 1200, "ordering_cost": 45, "holding_cost": 6}))
record("POST /ai/forecast/run",
       client.post("/ai/forecast/run", json={"product_id": 2, "horizon": 30, "model": "prophet"}))
record("POST /ai/anomaly/run",
       client.post("/ai/anomaly/run", json={"product_id": 2, "contamination": 0.05}))
record("GET /ai/forecast/portfolio",
       client.get("/ai/forecast/portfolio"))
record("GET /ai/anomaly/portfolio",
       client.get("/ai/anomaly/portfolio"))

failed = [r for r in results if not r[0]]
print("\n========== SUMMARY ==========")
print(f"Passed: {len(results) - len(failed)} / {len(results)}")
if failed:
    print("FAILED:")
    for ok, label, code, size in failed:
        print(f"  - {label}: status={code} size={size}")
    sys.exit(1)

