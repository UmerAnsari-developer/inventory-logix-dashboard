# InventoryLogix — Executive Summary

**Merged from both analysis passes · September 10, 2026**
Evidence levels: E1 direct · E2 strong inference · E3 interpretation.

## Overview

InventoryLogix is a full-stack Flask + PostgreSQL inventory management
dashboard that integrates machine learning for demand forecasting and
anomaly detection with real-time CRUD operations, EOQ optimization, and an
SCD Type 2 data warehouse with ETL pipeline. It serves supply chain
analysts, warehouse managers, and procurement leads with role-based access
control, a REST API, and a unified dark-mode UI featuring glassmorphism,
GSAP animations, and Three.js 3D backgrounds.

## Key Achievements (verified)

| Metric | Value | Evidence |
|--------|-------|----------|
| Test Suite | 97 tests across 8 files | `tests/`, pytest |
| SQL Functions | 74 total (51 sp_* + 14 etl_* + 9 trigger functions) | grep-verified |
| Triggers | 8 CREATE TRIGGER statements | `app/database/triggers.sql` |
| Tables | 12 operational + 16 warehouse | `schema.sql`, `warehouse.sql` |
| Routes | 50 (ui 23, api 15, auth 5, ai 7) | grep-verified |
| Seeded Transactions | 180,000+ from DataCo SMART SUPPLY CHAIN (CSV gitignored; synthetic fallback) | `app/database/seed.py`, PRODUCT.md [E2] |
| Products | 118 with real demand/ordering/holding costs | seed data |
| Suppliers | 150 (36 curated real-world in fallback) | seed data |
| Warehouses | 10 Indian cities | `seed.py:37-40` |
| Data Warehouse | SCD Type 2 dims + facts + incremental ETL | `warehouse.sql`, `etl.py` |

## Technology Stack

- **Backend:** Flask ≥3.0 · PostgreSQL · psycopg2 (ThreadedConnectionPool)
- **ML:** Prophet · ARIMA/statsmodels · Isolation Forest/scikit-learn
- **Frontend:** Jinja2 · Chart.js 4.4 (global) · Plotly 2.27 (lazy, 4 pages) · Three.js 0.160 · GSAP 3.12
- **Deployment:** Render Blueprint free tier · Gunicorn (1 worker, 2 threads) · SendGrid

## Core Capabilities

### 1. Real-Time Inventory Management
CRUD for products, suppliers, movements, purchase orders; role-based
access (`viewer` read-only, `admin`/`manager` write); stock status
(healthy/warning/critical); CSV export.

### 2. AI-Powered Analytics
Demand forecasting (Prophet + ARIMA ensemble with confidence intervals);
anomaly detection (Isolation Forest + SPC z-score control charts);
portfolio endpoints cached 1h; graceful fallback (moving-average/z-score)
when ML libraries are unavailable — the app never 500s on a missing model.

### 3. EOQ Optimization
EOQ = √(2DS/H); interactive cost curve; per-product EOQ table; 3D
sensitivity surface (demand × ordering cost) via Plotly.

### 4. Data Warehouse
SCD Type 2 dimensions (products, suppliers, warehouses, users) with
row-hash change detection; star-schema facts; incremental watermark ETL
with stock-walk clamping; monitoring dashboard at `/monitoring`.

### 5. Security
Per-request CSP nonces; CSRF; rate limiting (10/min login, 30/min API
writes, 60/min movements); account lockout (5 fails → 15 min);
parameterized SQL via stored procedures; hashed single-use password-reset
tokens; audit logging via triggers.

## What Is Genuinely Strong (E1)

1. **Database-first integrity** — negative stock is impossible even if
   the app has a bug, because a DB trigger blocks it.
2. **Security posture rare in student work** — CSP nonces, hashed reset
   tokens, lockout, RBAC, audit trail.
3. **Honest ML degradation** — every model call is guarded with
   deterministic fallbacks.
4. **Real data grounding** — DataCo dataset (180K+ transactions) with
   transparent synthetic fallback.
5. **97 automated tests** covering auth, RBAC, API, security, ML,
   services, cache, ETL.

## What To Be Honest About

- **"AI savings YTD" is not measured money** — it's a model-derived
  comparison of EOQ ordering vs a hypothetical monthly-ordering baseline
  on estimated costs ($50 ordering hardcoded; holding = 20% of price).
  Always positive by construction. Landing-page stats are likewise
  hardcoded demo values.
- **Forecast "accuracy %"** is in-sample fit quality; the fallback
  reports a fixed 78%.
- **Single-process assumptions** — lockout, rate limits, and caches are
  in-process memory; the deployment is deliberately 1 worker × 2 threads.
  Adding workers without Redis silently weakens auth protections.
- **Known risks** — a database credential is committed in `alembic.ini`
  (flagged for rotation); the AI portfolio endpoints lack rate limits; the
  background ETL button likely fails silently (app-context bug);
  `render.yaml` has a database-name mismatch.
- **No production users** — academic project; usage evidence is the test
  suite, not traffic.

## Value Classification

| Implemented | Measured (of seeded data) | Potential | Synthetic |
|---|---|---|---|
| Reorder queue, EOQ, forecasting, anomaly, POs, warehouses, reports, RBAC, audit, API, ETL | Inventory value, turnover, ABC classes, supplier spend, sales trends | Fewer stockouts, lower carrying cost, earlier error detection | AI savings YTD, forecast accuracy %, landing KPIs, dashboard deltas |

## Maturity Assessment

**Advanced MVP / early Production-ready** (as a single-tenant internal
tool, after fixing the critical security items).

| Criterion | Status |
|-----------|--------|
| Core Features | Complete |
| Security | Strong (CSP, RBAC, parameterized SQL) — with flagged gaps |
| Testing | Good (97 tests; analytical UI routes untested) |
| Deployment | Render-ready (blueprint needs name fix) |
| Scalability | Single-instance by design (needs Redis for horizontal) |

## Recommended Next Steps

1. Rotate + remove the committed database credential; fix `render.yaml`
   DB-name mismatch; add a SECRET_KEY production fail-fast.
2. Rate-limit + clamp the AI portfolio endpoints.
3. Push app context into the ETL thread; add an ETL concurrency guard.
4. PO receipt reconciliation (auto IN movement + clear `on_order`).
5. Redis for limiter/lockout/caches, then multi-worker scaling.
6. Reorder email alerts via the existing Mailer.
7. Out-of-sample forecast backtesting to replace synthetic accuracy
   numbers.

---

*Evidence classification: E1 (Direct), E2 (Strong Inference), E3 (Interpretation), E4 (Unknown)*
