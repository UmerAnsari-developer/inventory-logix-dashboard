"""Chaos / fault-injection test suite for InventoryLogix.

Scenarios:
  A. Fault injection  - DB outage, dropped connection, recovery.
  B. Fuzz / robustness - malformed inputs & injection strings; asserts no 5xx.
  C. Load / stress     - rapid + concurrent requests; no 5xx, rate limiter works.

Results are written to scripts/chaos_report.md.
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

os.environ.setdefault("FLASK_ENV", "testing")
os.environ.setdefault("WTF_CSRF_ENABLED", "0")
os.environ.setdefault("SECRET_KEY", "chaos-secret")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app

REPORT_PATH = Path(__file__).resolve().parent / "chaos_report.md"
BAD_DSN = "postgresql://postgres:wrong@127.0.0.1:1/inventory_db?connect_timeout=1"

SCENARIO_NAMES = {
    "A": "Fault Injection",
    "B": "Fuzz / Robustness",
    "C": "Load / Stress",
}

app = create_app("testing")
# Render 500 error pages instead of propagating exceptions so we can assert them.
app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)

GOOD_PARAMS = app.config["psycopg2_params"]  # original callable, restored after outage

results: list[dict] = []


def record(scenario: str, name: str, passed: bool, detail: str = "") -> None:
    status = "PASS" if passed else "FAIL"
    results.append({"scenario": scenario, "name": name, "status": status, "detail": detail})
    print(f"[{status}] {scenario} :: {name} :: {detail}")


def login(client) -> bool:
    r = client.post(
        "/auth/login",
        data={"username": "admin", "password": "Admin@123", "remember": "on"},
    )
    return r.status_code == 302


def code(client, method: str, path: str, **kw):
    """Return status code, or ('RAISE', exc_type) if the request raised."""
    try:
        return getattr(client, method)(path, **kw).status_code
    except Exception as exc:  # pragma: no cover - defensive
        return ("RAISE", type(exc).__name__)


# ---------------------------------------------------------------------------
# Scenario A - Fault injection
# ---------------------------------------------------------------------------
def scenario_a() -> None:
    with app.test_client() as c:
        record("A", "admin login", login(c))
        r = c.get("/api/products")
        record("A", "baseline GET /api/products", r.status_code == 200, f"-> {r.status_code}")

        app.config["psycopg2_params"] = lambda: {"dsn": BAD_DSN}
        try:
            r = c.get("/api/products")
            record("A", "DB outage -> /api/products", r.status_code == 500, f"-> {r.status_code}")
        except Exception as exc:
            record("A", "DB outage -> /api/products", False, f"raised {type(exc).__name__}")
        try:
            r = c.get("/inventory")
            record("A", "DB outage -> /inventory page", r.status_code == 500, f"-> {r.status_code}")
        except Exception as exc:
            record("A", "DB outage -> /inventory page", False, f"raised {type(exc).__name__}")
        r = c.get("/api/health")
        record("A", "DB outage -> /api/health still up", r.status_code == 200, f"-> {r.status_code}")

        app.config["psycopg2_params"] = GOOD_PARAMS
        r = c.get("/api/products")
        record("A", "recovery after outage", r.status_code == 200, f"-> {r.status_code}")

    # Dropped connection mid-use must surface as a clean psycopg2 error.
    with app.app_context():
        from psycopg2 import InterfaceError

        from app.database.connection import get_connection

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        conn.close()
        try:
            cur.execute("SELECT 2")
            record("A", "dropped connection detected", False, "query unexpectedly succeeded")
        except InterfaceError:
            record("A", "dropped connection detected", True, "clean InterfaceError")
        except Exception as exc:
            record("A", "dropped connection detected", False, f"wrong error {type(exc).__name__}")

    with app.test_client() as c:
        r = c.get("/api/health")
        record("A", "post-drop request works", r.status_code == 200, f"-> {r.status_code}")


# ---------------------------------------------------------------------------
# Scenario B - Fuzz / robustness
# ---------------------------------------------------------------------------
def scenario_b() -> None:
    sqli = "' OR 1=1 --"
    xss = "<script>alert(1)</script>"

    with app.test_client() as c:
        record("B", "admin login", login(c))

        cases = [
            # (name, http method, path, kwargs)
            ("POST /api/products sqli/xss payload", "post", "/api/products",
             dict(json={"sku": sqli, "name": xss, "unit_price": -1, "current_stock": -5})),
            ("POST /api/products huge number", "post", "/api/products",
             dict(json={"sku": "x" * 300, "unit_price": 10 ** 300})),
            ("POST /api/products empty object", "post", "/api/products", dict(json={})),
            ("POST /api/products empty array", "post", "/api/products", dict(json=[])),
            ("POST /api/products malformed JSON body", "post", "/api/products",
             dict(data=b"{not json", content_type="application/json")),
            ("POST /api/products wrong types", "post", "/api/products",
             dict(json={"name": ["not", "a", "string"], "sku": 12345, "name2": None})),
            ("GET /api/products search=XSS", "get", "/api/products?search=" + xss, {}),
            ("GET /api/products search=SQLi", "get", "/api/products?search=" + sqli, {}),
            ("GET /api/products?page=abc", "get", "/api/products?page=abc", {}),
            ("GET /api/products?per_page=abc", "get", "/api/products?per_page=abc", {}),
            ("GET /api/products?page=-99", "get", "/api/products?page=-99", {}),
            ("GET /api/products/abc (non-int)", "get", "/api/products/abc", {}),
            ("GET /api/products/-1", "get", "/api/products/-1", {}),
            ("GET /api/products/999999", "get", "/api/products/999999", {}),
            ("POST /api/movements sqli payload", "post", "/api/movements",
             dict(json={"product_id": sqli, "type": "IN", "quantity": -100})),
            ("POST /api/movements huge quantity", "post", "/api/movements",
             dict(json={"type": "IN", "quantity": 10 ** 15})),
            ("GET /api/movements/recent?days=abc", "get", "/api/movements/recent?days=abc", {}),
            ("GET /reports?warehouse_json=123", "get", "/reports?warehouse_json=123", {}),
            ("GET /reports?warehouse_json=[1,2]", "get", "/reports?warehouse_json=%5B1%2C2%5D", {}),
            ("GET /reports?category_json={a:1}", "get", "/reports?category_json=%7Ba%3A1%7D", {}),
            ("GET /reports?date_from=garbage", "get", "/reports?date_from=garbage", {}),
            ("GET /reports?date_from=13-99", "get", "/reports?date_from=13-99", {}),
            ("GET /inventory search=SQLi", "get", "/inventory?search=" + sqli, {}),
            ("GET /warehouses?x=XSS", "get", "/warehouses?x=" + xss, {}),
        ]

        for name, method, path, kw in cases:
            sc = code(c, method, path, **kw)
            if isinstance(sc, tuple):
                record("B", name, False, f"raised {sc[1]}")
            elif isinstance(sc, int) and sc >= 500:
                record("B", name, False, f"5xx ({sc}) - server error on malformed input")
            else:
                record("B", name, True, f"-> {sc}")

    # Anonymous register validation - run in its own clean client context so the
    # test-harness g._login_user leak (preserved app context) cannot mask it.
    with app.test_client() as a:
        sc = code(a, "post", "/auth/register",
                  data={"username": sqli, "email": "x@x.com",
                        "password": "Strong1Pass", "role": "viewer"})
        record("B", "POST /auth/register sqli username", sc == 400, f"-> {sc}")

    # Post-fuzz health check.
    with app.test_client() as c:
        r = c.get("/api/health")
        record("B", "post-fuzz recovery", r.status_code == 200, f"-> {r.status_code}")


# ---------------------------------------------------------------------------
# Scenario C - Load / stress
# ---------------------------------------------------------------------------
def scenario_c() -> None:
    # Rapid /api/products (limit 120/min) - expect some 429, no 5xx.
    with app.test_client() as c:
        login(c)
        codes: dict[int, int] = {}
        for _ in range(130):
            r = c.get("/api/products")
            codes[r.status_code] = codes.get(r.status_code, 0) + 1
        no5xx = not any(k >= 500 for k in codes)
        record("C", "rapid /api/products x130", no5xx and 200 in codes and 429 in codes,
               f"codes={codes}")

    # Login hammer (limit 10/min) - expect eventual 429, no 5xx.
    with app.test_client() as c:
        codes = {}
        for _ in range(15):
            r = c.post("/auth/login",
                       data={"username": "x", "password": "y", "remember": "on"})
            codes[r.status_code] = codes.get(r.status_code, 0) + 1
        no5xx = not any(k >= 500 for k in codes)
        record("C", "login hammer x15", no5xx and 429 in codes, f"codes={codes}")

    # Concurrent anonymous traffic - no 5xx, no crashes.
    def worker(_):
        with app.test_client() as wc:
            bad = 0
            for _ in range(20):
                if wc.get("/").status_code >= 500:
                    bad += 1
                if wc.get("/inventory").status_code >= 500:
                    bad += 1
            return bad

    with ThreadPoolExecutor(max_workers=8) as ex:
        bads = list(ex.map(worker, range(8)))
    record("C", "concurrent anonymous traffic (8 workers x 40)", sum(bads) == 0,
           f"5xx total={sum(bads)}")

    with app.test_client() as c:
        r = c.get("/api/health")
        record("C", "post-stress recovery", r.status_code == 200, f"-> {r.status_code}")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def write_report() -> None:
    lines = ["# Chaos Test Report", ""]
    lines.append(f"- Timestamp: {datetime.now().isoformat()}")
    lines.append("- Environment: FLASK_ENV=testing, DB=inventory_db (live)")
    lines.append("")

    for sc in ("A", "B", "C"):
        rows = [r for r in results if r["scenario"] == sc]
        passed = sum(1 for r in rows if r["status"] == "PASS")
        lines.append(f"## Scenario {sc} - {SCENARIO_NAMES[sc]}")
        lines.append(f"Passed {passed}/{len(rows)}")
        lines.append("")
        lines.append("| Case | Status | Detail |")
        lines.append("|---|---|---|")
        for r in rows:
            lines.append(f"| {r['name']} | {r['status']} | {r['detail']} |")
        lines.append("")

    total_p = sum(1 for r in results if r["status"] == "PASS")
    lines.append(f"## Summary\n\n**{total_p}/{len(results)} checks passed.**")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to {REPORT_PATH}")


if __name__ == "__main__":
    print("=== Chaos test: Scenario A - Fault Injection ===")
    scenario_a()
    print("\n=== Chaos test: Scenario B - Fuzz / Robustness ===")
    scenario_b()
    print("\n=== Chaos test: Scenario C - Load / Stress ===")
    scenario_c()
    write_report()
    total_p = sum(1 for r in results if r["status"] == "PASS")
    print(f"\nSUMMARY: {total_p}/{len(results)} checks passed")
