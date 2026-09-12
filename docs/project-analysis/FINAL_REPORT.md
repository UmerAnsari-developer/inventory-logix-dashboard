# InventoryLogix — Complete Project Analysis Report

**Inventory Logistics Optimization Dashboard**

> Version 2.0 | September 2026
> Evidence levels: **E1** Direct evidence | **E2** Strong inference | **E3** Engineering interpretation | **E4** Unknown
> Value levels: **Implemented** | **Measured** | **Potential** | **Synthetic**

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Project Overview](#2-project-overview)
3. [Business Problem & Need](#3-business-problem--need)
4. [Objectives & Target Users](#4-objectives--target-users)
5. [Project Scope](#5-project-scope)
6. [Features](#6-features)
7. [Technology Stack](#7-technology-stack)
8. [Project Structure](#8-project-structure)
9. [Architecture](#9-architecture)
10. [Module-by-Module Explanation](#10-module-by-module-explanation)
11. [Application Workflow](#11-application-workflow)
12. [Data Flow](#12-data-flow)
13. [Database Architecture](#13-database-architecture)
14. [API Architecture](#14-api-architecture)
15. [Technology Selection Justification](#15-technology-selection-justification)
16. [Alternative Technology Comparison](#16-alternative-technology-comparison)
17. [Development Approach & Timeline](#17-development-approach--timeline)
18. [Development Challenges](#18-development-challenges)
19. [Traditional vs Current Solution](#19-traditional-vs-current-solution)
20. [Business Benefits](#20-business-benefits)
21. [Security Analysis](#21-security-analysis)
22. [Performance Analysis](#22-performance-analysis)
23. [Scalability Analysis](#23-scalability-analysis)
24. [Testing](#24-testing)
25. [Deployment](#25-deployment)
26. [Limitations](#26-limitations)
27. [Future Enhancements](#27-future-enhancements)
28. [Literature Review](#28-literature-review)
29. [Evidence Register](#29-evidence-register)
30. [Final Assessment](#30-final-assessment)

---

## 1. Executive Summary

InventoryLogix is a single-tenant, full-stack Flask + PostgreSQL web application for warehouse inventory management and logistics optimization. It unifies real-time CRUD (products, suppliers, stock movements, purchase orders), classical inventory optimization (EOQ), ML demand forecasting (Prophet/ARIMA ensemble with moving-average fallback), anomaly detection (Isolation Forest + SPC), and a Kimball-style star-schema data warehouse with an ETL pipeline — served through a role-protected, dark-mode UI with glassmorphism, GSAP animations, and Three.js 3D backgrounds.

**Verified key metrics:**

| Metric | Value | Evidence |
|--------|-------|----------|
| Test Suite | 97 tests across 8 files | `tests/`, pytest |
| SQL Functions | 74 total (51 sp_* + 14 etl_* + 9 trigger functions) | grep-verified |
| Triggers | 8 CREATE TRIGGER statements | `app/database/triggers.sql` |
| Tables | 12 operational + 16 warehouse | `schema.sql`, `warehouse.sql` |
| Routes | 50 (ui 23, api 15, auth 5, ai 7) | grep-verified |
| Seeded Transactions | 180,000+ from DataCo SMART SUPPLY CHAIN | `app/database/seed.py`, PRODUCT.md [E2] |
| Products | 118 with real demand/ordering/holding costs | seed data |
| Suppliers | 150 (36 curated real-world in fallback) | seed data |
| Warehouses | 10 Indian cities | `seed.py:37-40` |
| Data Warehouse | SCD Type 2 dims + facts + incremental ETL | `warehouse.sql`, `etl.py` |

The project demonstrates production-grade practices unusual for a student project, with honest limitations documented throughout this report: in-process security state, a likely-silent background ETL thread, a committed database credential, a Render blueprint mismatch, and dashboard "benefit" numbers that are model-derived rather than measured outcomes.

## 2. Project Overview

### 2.1 What is InventoryLogix?

An **Inventory Command Center** that unifies real transaction data with machine learning into a single dashboard, transforming raw stock movements into actionable replenishment decisions — helping organizations reduce stockouts and carrying costs.

### 2.2 Why does it exist?

Traditional spreadsheet-based approaches lack real-time cross-warehouse visibility, demand forecasting, anomaly detection, order-quantity optimization, and audit trails. The code addresses each gap directly (see Section 3).

### 2.3 Core Value Proposition

The differentiating mechanism is the **integrated EOQ + 3D sensitivity surfaces** — a live EOQ calculator visualizing cost curves in 3D per product, paired with real transaction history and ML forecasts. No comparable product combines real dataset grounding, ML demand forecasting, anomaly detection, and interactive EOQ optimization in one open-stack Flask application. [E2]

| Attribute | Value |
|---|---|
| Type | Server-rendered web app + REST API |
| Scale | 50 routes, 74 SQL functions, 28 tables, 97 tests, 73 commits |
| Roles | viewer (read-only), manager/admin (write) |
| Author | Single developer (UmerAnsari-developer), 71 of 73 commits |
| Tracked history | 2026-08-15 to 2026-09-10 (27 days); core predates git |

### 2.4 Technology Stack

| Layer | Technology | Version | Evidence |
|--------|---------|---------|----------|
| Framework | Flask | >=3.0 | requirements.txt:1 |
| DB | PostgreSQL (Render free / Supabase) | — | render.yaml |
| Driver | psycopg2-binary + ThreadedConnectionPool(1,20) | >=2.9 | connection.py:33-67 |
| Auth | Flask-Login (strong session protection) | >=0.6 | extensions.py:9-12 |
| CSRF | Flask-WTF CSRFProtect | >=1.2 | extensions.py:14 |
| Rate limiting | Flask-Limiter (memory://) | >=3.5 | extensions.py:16-20 |
| Migrations | Alembic raw-SQL | >=4.0 | migrations/ |
| Forecast | Prophet; statsmodels ARIMA(1,1,1) | >=1.1 / >=0.14 | forecasting.py:18,24 |
| Anomaly | scikit-learn IsolationForest | >=1.3 | anomaly.py:12,33 |
| Charts | Chart.js 4.4.0 global; Plotly.js 2.27.0 lazy (4 pages) | CDN | base.html:43; dashboard.html:5 |
| 3D/anim | Three.js 0.160 import map; GSAP 3.12.5 + ScrollTrigger | CDN | base.html:11-15,45-46 |
| Templating | Jinja2 | bundled | templates/ |
| Email | SendGrid HTTPS API (SMTP fallback) | >=6.0 | mailer.py:57-63 |
| WSGI | Gunicorn 1 worker x 2 threads | >=21.2 | run.py:41-80 |
| Hosting | Render Blueprint (free) | — | render.yaml |
| Testing | pytest (97 tests) | dev-only | pytest.ini |

## 3. Business Problem & Need

### 3.1 Business Problem Statement

Supply chain managers and warehouse operators face:

| Challenge | Impact | Traditional Solution |
|-----------|--------|------------------|
| **Stockout prevention** | Lost sales, dissatisfaction | Manual reorder points from memory |
| **Carrying-cost optimization** | Idle capital, obsolescence | Spreadsheet tracking, gut-feel quantities |
| **Demand variability** | Inaccurate forecasts | Gut feeling |
| **Anomaly detection** | Theft, damage, data errors | Manual audits |
| **Multi-warehouse coordination** | Inconsistent stock levels | Phone calls/emails |
| **Compliance** | Audit failures | Paper trails |

Code-level targeting (E1): reorder query `current_stock <= reorder_point AND on_order <= 0` (ui.py:96-100); EOQ + sensitivity (eoq_service.py:48-80); auto-draft capped at 6 months demand (ui.py:502-506); SCD2 warehouse (warehouse.sql); IF + SPC (anomaly.py); forecasting (forecasting.py).

### 3.2 Business Need

A low-cost, self-hostable system that turns raw stock movements into daily replenishment decisions without paid SaaS subscriptions or ERP implementation projects. The deployment story (Render free tier, auto schema+seed on first boot, zero license cost) targets exactly this. [E2]

### 3.3 Traditional vs Proposed Solution

| Process | Traditional (spreadsheet) | InventoryLogix | Limit |
|---|---|---|---|
| Reorder identification | Memory/manual scan | Live query + severity + badge on every page | No push notification — must open app |
| Order quantity | Gut feel | EOQ root(2DS/H) on per-product costs + sensitivity surface | Forecast and EOQ don't feed each other |
| Movement logging | Paper slips / retyped rows | One form -> SP + trigger integrity + audit | Manual keyboard entry (no scanner) |
| Error detection | Physical cycle counts | IF + SPC +/-3sigma charts | User-triggered scans only |
| Historical analysis | Manual pivot tables | 5-tab reports + SCD2 warehouse | ETL is button-triggered |
| Multi-warehouse visibility | Phone/email | First-class warehouse filter everywhere | Warehouse is a text column, not capacity-managed |
| Audit trail | Paper | DB triggers + explicit audit rows | No audit-viewing UI |

## 4. Objectives & Target Users

### 4.1 Objectives

**Primary** (PRODUCT.md, E1):
1. Unify real transaction data, ML forecasting, anomaly detection, and EOQ optimization in one dashboard.
2. Turn raw stock movements into actionable replenishment decisions.
3. Reduce stockouts and carrying cost.

**Secondary:** RBAC; REST API; audit compliance; security-first design (CSP, rate limiting, parameterized SQL); responsive dark-mode UI.

### 4.2 Target Users

- **Primary:** Supply chain analysts (forecast, detect anomalies, optimize levels); warehouse/operations managers (daily stock review, reorder workflow, movement tracking).
- **Secondary:** Procurement leads (supplier/PO management); admins (settings, monitoring).

| Role | Capabilities |
|------|-------------|
| `viewer` | Read-only access (self-registration always creates viewer) |
| `manager` | Write access to products, suppliers, movements, POs |
| `admin` | Full access including settings (role promotion has no UI — direct DB only) [E1] |

### 4.3 Target Organizations

Single-organization SMEs — mid-sized manufacturers, distribution centers, retail chains, 3PLs — with a handful of warehouses (10 seeded). No tenant/org column exists in the schema: one deployment = one company. [E1]

## 5. Project Scope

**In scope:** full-stack Flask app; PostgreSQL with stored procedures; ML forecasting; anomaly detection; EOQ with 3D visualization; data warehouse with ETL; REST API; RBAC; audit logging; responsive dark-mode UI.

**Out of scope (verified absent by grep):** sales orders/fulfillment, billing/invoicing, shipping/carrier integration, ERP/WMS/e-commerce connectors (landing "Connect your ERP, WMS" is aspirational copy), barcode scanning, mobile-native apps, user management UI, approval routing, notification delivery (email/Slack toggles are decorative), multi-currency (single INR formatting), i18n, WebSockets.

## 6. Features

### 6.1 Core Features

| Feature | Description | Evidence |
|---------|-------------|----------|
| Dashboard | KPI cards, inventory mix, 14-day movement chart, reorder queue, ABC analysis, slow movers, warehouse profile, 3D tilt | `dashboard.html`; ui.py:74-339 |
| Inventory | Searchable/filterable/paginated table + CSV export (8 cols, 10k cap) | ui.py:342-390 |
| Reorder alerts | Severity-sorted queue, mark-ordered, auto-draft | ui.py:466-544 |
| Suppliers | Cards with reliability, lead time, spend | `suppliers.html` |
| Purchase orders | Manual + kanban (draft->approved->in_transit->received) | ui.py:611-676 |
| Warehouses | Analytics page, star-schema-backed with live fallback | ui.py:679-731 |
| Reports | 5 tabs (Executive, Warehouse, Procurement, Sales, Inventory Health), filters, MTD/YTD/prev-period math | ui.py:734-1890 |
| EOQ calculator | Live form, cost curve, 3D sensitivity, per-product table | `eoq_calculator.html` |
| Auth | Login/register/forgot/reset, lockout, session tracking | auth routes/services |
| Monitoring | DB stats, ETL state, login history, active sessions | ui.py:1926-1974 |
| Settings | Per-user prefs, AI toggles, thresholds (admin/manager) | settings_service.py |

### 6.2 AI/ML Features

| Feature | Description | Evidence |
|---------|-------------|----------|
| Demand forecasting | Prophet/ARIMA/ensemble with confidence intervals; >=14/>=20-point floors | `forecasting.py` |
| Anomaly detection | Isolation Forest + SPC z-score (UCL/LCL mu +/- 3sigma) | `anomaly.py` |
| Portfolio analytics | Cached portfolio endpoints (1h) | `ai.py` |
| 3D EOQ surface | Demand x ordering-cost sensitivity grid | `eoq_service.py:66-80` |

### 6.3 Security Features

| Feature | Description | Evidence |
|---------|-------------|----------|
| CSP nonces | Per-request, on all inline scripts + import maps | `headers.py:17-43` |
| Account lockout | 5 fails -> 15 min | `auth_service.py:24-29,66-86` |
| Session cookies | Secure, HttpOnly, SameSite=Lax | `settings.py:18-25` |
| Password reset | Single-use, TTL, SHA-256-stored tokens | `auth_service.py:127-133` |
| Rate limiting | 10/min login, 5/min register, 30/min writes, 60/min movements | auth.py, api.py |
| Parameterized SQL | All CRUD via `sp_*` procedures | `procedures.sql` |
| Audit log | Triggers + explicit service calls on every mutation | `triggers.sql` |
| HTTP headers | nosniff, X-Frame-Options, Referrer-Policy, Permissions-Policy, CSP | `headers.py` |

### 6.4 Advanced Features

1. **EOQ 3D sensitivity surface** — visualizes how Q* moves when D/S/H drift, answering the classical EOQ critique (deterministic inputs).
2. **Ensemble forecasting with graceful degradation** — Prophet >=14 pts, ARIMA >=20 pts, ensemble average, MA fallback; app never 500s on a missing library.
3. **SCD Type 2 dimensions** — valid_from/valid_to/is_current/row_hash with partial indexes on is_current; hash-skip unchanged rows.
4. **Incremental ETL with stock-walk clamping** — watermark `etl_state['last_movement_id']`; backward stock walk clamps negative intermediates to 0 (counted, logged) (etl.py:296-314).
5. **Per-request CSP nonces + lazy Plotly** (~3.5MB only on 4 chart pages).
6. **Auto-draft POs** — one click drafts POs for all critical items at max(EOQ, deficit) capped at 6-months demand (ui.py:481-523).
7. **DB-enforced stock integrity** — `trg_validate_movement` blocks negative stock even under app-layer bugs.

## 7. Technology Stack (Detailed)

### 7.1 Backend Framework: Flask 3.0+

Flask provides the application factory pattern, blueprint-based routing, Jinja2 templating, and extension integration (Login, WTF, Limiter). The lightweight nature avoids ORM overhead since the project uses raw SQL stored procedures. [E1]

**Advantages:** Tiny learning curve, mature extension ecosystem, debug server with auto-reload, seamless Gunicorn integration.

**Limitations:** No built-in async, no WebSocket support, no admin interface, thread safety depends on careful `g` context management.

### 7.2 Database: PostgreSQL via psycopg2

PostgreSQL hosts 84+ stored procedures, 8 trigger functions, SCD Type 2 dimensions, and a star-schema data warehouse. psycopg2-binary provides `RealDictCursor` for dict-like row access and `ThreadedConnectionPool(1,20)` for connection reuse. [E1]

**Advantages:** PL/pgSQL procedures/triggers first-class; JSONB support; ACID compliance; strong indexing (49 indexes); RLS enabled.

**Limitations:** No ORM means manual SQL migration authoring; ThreadedConnectionPool is per-process.

### 7.3 ML Pipeline

- **Prophet** (weekly seasonality, >=14 data points) for trend + seasonality decomposition
- **ARIMA(1,1,1)** (>=20 data points, 95% confidence intervals) for linear time-series modeling
- **Ensemble** averages both predictions for robustness
- **Moving Average** fallback when libraries unavailable (hardcoded 78% accuracy)
- **Isolation Forest** (contamination 0.05, 80 trees, seed 42) for anomaly detection
- **SPC z-score** (UCL/LCL at mu +/- 3sigma) for statistical process control charts

### 7.4 Frontend

- **Jinja2** server-rendered templates (30 templates)
- **Chart.js 4.4.0** (global, standard charts)
- **Plotly.js 2.27.0** (lazy-loaded on 4 pages: dashboard, forecast, anomaly, EOQ)
- **Three.js 0.160** (3D wave background, EOQ sensitivity surface)
- **GSAP 3.12.5 + ScrollTrigger** (entrance animations, panel tilt)
- **Dark/light theme toggle** saved to localStorage

### 7.5 Deployment

- **Render Blueprint** (free tier): managed PostgreSQL + web service
- **Gunicorn** (1 worker, 2 threads): single process for consistent in-memory state
- **SendGrid HTTPS API**: email delivery (Render blocks SMTP egress)

## 8. Project Structure

```
InventoryLogix/
+-- run.py                    # Entry: create_app() + Werkzeug dev / Gunicorn prod
+-- migrate.py                # CLI: etl | alembic migrate/upgrade
+-- render.yaml               # Blueprint: free Postgres + web service
+-- alembic.ini               # Alembic config (committed DSN - see Security)
+-- app/
|   +-- __init__.py           # App factory, error handlers, bootstrap hook
|   +-- config/settings.py    # Dev/Prod/Testing config classes
|   +-- extensions.py         # login_manager, csrf, limiter singletons
|   +-- models.py             # User proxy for Flask-Login
|   +-- database/             # connection.py, schema.sql, procedures.sql,
|   |                         # triggers.sql, warehouse.sql, etl_procedures.sql,
|   |                         # etl.py, seed.py
|   +-- repositories/         # 9 static-method repo classes -> sp_* calls
|   +-- services/             # auth, product, movement, supplier, forecast,
|   |                         # anomaly, eoq, dataset, mailer, settings
|   +-- routes/               # 4 blueprints: auth (5), ui (23), api (15), ai (7)
|   +-- ml/                   # forecasting.py, anomaly.py
|   +-- security/             # headers (CSP nonce), roles (RBAC), validators
|   +-- utils/                # cache.py (TTLCache x8), helpers.py (EOQ math)
|   +-- templates/            # 28 templates + auth/ ai/ errors/ subdirs
|   +-- static/               # css (3), js (11), img
+-- migrations/versions/      # 001_initial, 002_critical_fixes, 003_enable_rls
+-- tests/                    # 97 tests in 8 files + conftest
+-- docs/                     # project-analysis/
```

## 9. Architecture

### 9.1 System Architecture Diagram

```
+-------------------------------------------------------------+
|                    CLIENT (Browser)                          |
|   Jinja2 pages, Chart.js, Plotly, GSAP, Three.js            |
+-------------------------------------------------------------+
                            |
                            v
+-------------------------------------------------------------+
|              FLASK PROCESS (1 worker x 2 threads)           |
|                                                             |
|   auth_bp (/auth, 5 routes)                                |
|   ui_bp (/, 23 routes, 2051 lines)                         |
|   api_bp (/api, 15 routes)                                 |
|   ai_bp (/ai, 7 routes)                                    |
|                                                             |
|   Services -> Repositories x9 -> TTLCache x8               |
|                                                             |
|   ui.py --inline SQL (~56 sites)--> PostgreSQL             |
|   R --sp_*(%s,...)--> PostgreSQL                            |
+-------------------------------------------------------------+
                            |
                            v
+-------------------------------------------------------------+
|                    POSTGRESQL                               |
|                                                             |
|   74 functions: 51 sp_*, 14 etl_*, 9 trigger fns          |
|   8 triggers: validation + audit                           |
|   12 operational tables                                    |
|   16 warehouse tables (SCD2 + facts)                       |
|   etl.py incremental + etl_full_build                      |
+-------------------------------------------------------------+
```

### 9.2 Request Lifecycle

1. Flask-Login session check -> login redirect if needed
2. CSRF validation (Flask-WTF) on POST
3. Rate limiting (Flask-Limiter)
4. Role check (`@write_roles_required` after `@login_required`)
5. Service-layer input validation
6. Repository -> stored procedure (parameterized psycopg2)
7. JSON envelope `{success, data/error}` or rendered template
8. Triggers record mutation to `audit_log`

### 9.3 Key Structural Fact

The layering (routes -> services -> repositories -> stored procedures) is real on the API side but **bypassed by ui.py** (~56 inline `cur.execute` sites; reports() ~1156 lines, ~40 queries). DB triggers backstop the leaks — `trg_validate_movement` enforces stock integrity no matter which layer writes. [E1]

## 10. Module-by-Module Explanation

- **app/__init__.py** — factory; prod fail-fast on missing DB (113-128); CLI commands; first-run bootstrap guarded against the debug-reloader parent (77-83); 7 error handlers with DB-free inline HTML fallback (192-256).
- **config/settings.py** — env-driven classes; SECRET_KEY default "change-me-in-production" (17); TestingConfig disables CSRF (98).
- **database/connection.py** — ThreadedConnectionPool(1,20) keyed by repr of sorted params; per-request g.db; teardown rollback+return; `bootstrap_database()` once per process.
- **database/schema.sql** — 12 operational tables + star schema + RLS enable loop (271-283).
- **database/procedures.sql** — 51 `sp_*` functions; all CRUD routes through them.
- **database/triggers.sql** — 9 functions, 8 triggers; `trg_validate_movement` auto-populates SKU + blocks negative stock (196-225); audit triggers on products/suppliers/movements/POs.
- **database/warehouse.sql + etl_procedures.sql** — SCD2 dims + event facts + `etl_full_build` + `sp_monitor_*`.
- **database/etl.py** — incremental watermark ETL, single transaction, stock-walk clamping; `_open_conn` reads `current_app` (38) — the background-ETL bug root.
- **database/seed.py** — idempotent per table; 3 demo users; 36 curated suppliers; DataCo or synthetic products across 10 warehouses; deterministic RNG (seed 2024).
- **ml/forecasting.py** — Prophet (weekly seasonality, >=14 pts), ARIMA(1,1,1) (>=20 pts, 95% CI), ensemble average, MA fallback (hardcoded accuracy 78.0).
- **ml/anomaly.py** — IsolationForest (contamination 0.05, 80 trees, seed 42) on univariate data; SPC z-score (UCL/LCL mu +/- 3sigma, LCL clamped >=0).
- **services/** — auth (lockout, SHA-256-hashed single-use 5-min reset tokens), EOQ (formula + curve + 3D sensitivity), forecast/anomaly orchestration, dataset (DataCo loader), mailer (SendGrid->SMTP), settings (per-user).
- **repositories/** — 9 static-method classes; 100% parameterized `sp_*` calls (except `find_for_update` row-lock).
- **security/** — headers (CSP nonce + OWASP set), roles (`WRITE_ROLES=("admin","manager")`), validators (password 8-128 chars, letter+digit).
- **utils/cache.py** — thread-safe TTLCache; 8 named caches; `cache_bust_*` prefix invalidation.
- **routes/** — auth 5, ui 23, api 15, ai 7 = 50 registrations.

## 11. Application Workflow

### 11.1 Daily Ops Loop

1. **Morning review** — `/` dashboard (KPIs, reorder queue, slow movers, ABC).
2. **Anomaly check** — `/ai/anomaly` (SPC chart, portfolio table).
3. **Forecast review** — `/ai/forecast` (model picker, confidence bands).
4. **Reorder decision** — `/reorder-alerts` (severity-sorted; mark-ordered or auto-draft).
5. **PO management** — `/purchase-orders` kanban status flow.
6. **Receipt logging** — `/movements/new` (IN/OUT/ADJUSTMENT/RETURN; negative stock blocked at service AND trigger).
7. **KPI refresh** — caches bust automatically on each mutation.

### 11.2 Known Workflow Gap

Marking a PO "received" only flips a status column — it creates no IN movement and never decrements `on_order`; a partial receipt leaves the item invisible to reorder alerts (on_order <= 0 filter). [E1/E2]

## 12. Data Flow

Request -> blueprint -> (service -> repository | inline SQL) -> pooled connection (g.db, max 20) -> `sp_*` parameterized call -> triggers (validation + audit) -> commit/rollback -> response. Reads pass through 8 TTL caches with prefix invalidation on writes; AI portfolio cached 1h; reports 300s. ETL runs on dedicated connections outside the pool, single transaction, watermark-based.

**Example trace — record movement:** route (ui.py:547 / api.py:244) -> `MovementService.record()` (validates type/quantity; `find_for_update` row-lock; computes new stock) -> `sp_movement_record` INSERT -> trigger auto-populates SKU + blocks negative -> `sp_product_set_stock` -> audit triggers. Service also writes an explicit audit row — movements produce multiple audit rows (trigger + service + stock-update trigger). [E1]

## 13. Database Architecture

### 13.1 Operational Tables (12)

`users`, `suppliers`, `products`, `movements`, `purchase_orders`, `user_settings`, `password_reset_tokens`, `audit_log`, `forecast_cache`, `anomaly_log`, `user_sessions`, `etl_state`.

### 13.2 Data Warehouse Tables (16)

Star: `dim_date`, `dim_warehouse`, `dim_product`, `dim_supplier`, `fact_movement_daily`, `fact_inventory_daily`.

SCD2 layer: `dim_product_scd`, `dim_supplier_scd`, `dim_warehouse_scd`, `dim_user` (valid_from/valid_to/is_current/row_hash + partial index on is_current), `fact_login_events`, `fact_session_activity` (generated duration_sec), `fact_signup_events`, `fact_audit_daily`, `etl_warehouse_state`.

`fact_product_daily` is defined but never populated (dead table). [E1]

### 13.3 Stored Procedures (74 Functions)

All CRUD via `sp_*` (products 12, suppliers 5, movements 5, users 11, reset tokens 4, sessions 5, audit 3, settings 3, POs 4 — 51 total) plus 14 `etl_*`/`sp_monitor_*`. Examples: `sp_product_list`, `sp_movement_record`, `sp_po_update_status`, `sp_settings_upsert_batch`.

### 13.4 Triggers (8)

- `trg_validate_movement` (SKU auto-populate + negative-stock guard)
- `trg_movement_stock_update` (audit only — misleading name; stock update happens in Python)
- `trg_product_audit`, `trg_supplier_audit`, `trg_po_audit`
- `trg_user_signup`, `trg_session_create`, `trg_session_end`

`trg_cleanup_stale_sessions` function exists but has no trigger. [E1]

### 13.5 Other

49 CREATE INDEX statements. RLS enabled with zero policies (deny-by-default vs Supabase PostGREST; app bypasses as owner). Alembic 001 duplicates the runtime bootstrap; 002 (trigger/timezone fixes) and 003 (RLS) carry real incremental changes.

## 14. API Architecture

Envelope: `{success: bool, data/error, code}` with HTTP-status alignment.

### 14.1 REST API (`/api/*`, 15 endpoints)

| Method | Endpoint | Auth | Rate Limit | Description |
|--------|----------|------|------------|-------------|
| GET | `/api/health` | No | — | Liveness probe (never touches DB) |
| GET | `/api/settings` | Yes | — | User settings |
| PUT | `/api/settings` | Yes | 30/min | Update settings |
| GET | `/api/dashboard/live` | Yes | — | Live dashboard data |
| GET | `/api/products` | Yes | 120/min | Paginated list |
| GET | `/api/products/<id>` | Yes | — | Product detail |
| POST | `/api/products` | Write roles | 30/min | Create |
| PUT | `/api/products/<id>` | Write roles | 30/min | Update |
| DELETE | `/api/products/<id>` | Write roles | 30/min | Delete |
| GET | `/api/suppliers` | Yes | — | Supplier list |
| GET | `/api/suppliers/<id>` | Yes | — | Supplier detail |
| POST | `/api/suppliers` | Write roles | 30/min | Create |
| POST | `/api/movements` | Write roles | 60/min | Record movement |
| GET | `/api/movements/recent` | Yes | — | Daily movement totals |
| POST | `/api/eoq/calculate` | Yes | — | EOQ math on supplied params |

### 14.2 AI Endpoints (`/ai/*`, 7 endpoints)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/ai/forecast` | Forecast page |
| POST | `/ai/forecast/run` | Run Prophet/ARIMA/ensemble (30/min) |
| GET | `/ai/forecast/portfolio` | Portfolio forecast (cached 1h) — **no rate limit** |
| GET | `/ai/anomaly` | Anomaly page |
| POST | `/ai/anomaly/run` | Run anomaly detection (30/min) |
| GET | `/ai/anomaly/portfolio` | Portfolio anomalies (cached 1h) — **no rate limit** |
| POST | `/ai/eoq/sensitivity` | 3D EOQ sensitivity surface |

Auth limits: login 10/min, register 5/min, forgot-password 5/hour.

## 15. Technology Selection Justification

| Decision | Alternatives | Why less suitable here |
|---|---|---|
| Flask | Django | ORM/admin conflict with SP+trigger design; batteries unused |
| Flask | FastAPI | Async unused (sync driver, blocking ML); API-first, not template-rendered |
| Flask + Jinja | React SPA | Adds build chain + JWT for no SSR benefit on an internal dashboard |
| PostgreSQL | MySQL | Weaker trigger/procedure ergonomics; no native RLS |
| PostgreSQL | SQLite | No server-side procedures/pooling/RLS |
| PostgreSQL | TimescaleDB/ClickHouse | Solves scale problems absent at ~8.4K seeded movements |
| Warehouse in same PG | Separate BI tool (Metabase/Grafana) | Second system to deploy/sync/auth; embedded charts reuse Flask sessions |
| psycopg2 | SQLAlchemy | ORM layer contradicts SP architecture; RealDictCursor already sufficient |
| Flask-Login | JWT/OAuth | Cookie sessions natural fit; local users table authoritative |
| Flask-Limiter memory:// | Redis backend | Redis = new service for a 1-instance deployment; env var exists for later |
| Prophet/ARIMA | LSTM/pmdarima | Orders-of-magnitude data hunger / per-product grid-search cost |
| Chart.js + Plotly split | Single stack | Chart-only can't render 3D surface; Plotly-only pays 3MB every page |
| Gunicorn 1w x 2t | Multi-worker | Breaks in-memory caches/limits/lockout; multiplies pools vs PgBouncer |
| Render | Vercel/Railway/VPS | Vercel per-request model breaks module-level pool; VPS forfeits free managed DB |
| SendGrid | SES/Mailgun/raw SMTP | SMTP egress blocked on Render free tier (documented) |

## 16. Alternative Technology Comparison

### 16.1 Stack-Level Alternatives

| Alternative Stack | Advantages | Why Flask + PostgreSQL Won |
|---|---|---|
| Django + MySQL + React | ORM admin, larger ecosystem | Over-engineered for server-rendered dashboard; ORM conflicts with 84+ stored procedures |
| FastAPI + HTMX | Async, modern | No async needed (sync psycopg2, blocking ML); HTMX less mature than Jinja2 for this use case |
| Next.js + Prisma + Vercel | Full-stack JS, serverless | Serverless breaks connection pooling; Prisma ORM conflicts with SP architecture |

## 17. Development Approach & Timeline

### 17.1 Approach

Single-developer, iterative hardening. Git evidence: auth polish -> real data/RBAC -> chart iteration (10 consecutive fix commits) -> mobile -> deploy -> sessions -> performance/DB consolidation -> security -> UI polish -> docs.

### 17.2 Verified Timeline (E1)

2026-08-15 to 2026-09-10, 73 commits, 10 active days, one developer (two git identities). The first commit is a big-bang import of 96 files / 15,240 lines — construction predates the repository. No releases/tags.

| Phase | Dates | Evidence |
|-------|-------|----------|
| P1 Big-bang import | 08-15 | fb795be (15,240 lines incl. ML + tests) |
| P2 Auth hardening | 08-16 00:10 | forgot/reset flow; demo creds removed |
| P3 Real data + RBAC | 08-16 14:27-21:29 | DataCo + real EOQ; viewer-only self-registration; ~10 chart fixes |
| P4 Mobile + Render deploy | 08-17/18 | render.yaml; Gunicorn; fail-fast DB; Plotly CDN race fix; SendGrid |
| P5 Session management | 08-18 | session-only login default; user_sessions table |
| P6 Usability pass -> revert | 08-23 | reverted after 34 min |
| P7 Perf + DB consolidation + README | 08-30 | procedures.sql/triggers.sql/migrations first tracked |
| P8 Mobile round 2 + college report | 08-31 | burger menu; duplicate buttons fix |
| P9 Security hardening + caching re-landed | 09-04 | RLS, reset TTL, unified caching |
| P10 Glassmorphism polish | 09-09 | panel blur, tints, docs moved |
| P11 Analysis documentation | 09-10 | docs/project-analysis/ |

> Actual day-by-day development progress before 2026-08-15 could not be verified from the available project artifacts.

## 18. Development Challenges

| Challenge | Evidence |
|---|---|
| Plotly CDN race — charts rendered before library loaded | Retry-loop fix, 08-17 23:33 |
| Render free tier blocks SMTP -> reset emails failed | SendGrid HTTPS API, 08-17 23:59 (documented) |
| Caching attempt broke app -> reverted in 4 min; re-landed 09-04 | git 08-17 21:56 -> 22:00; c312ec4 |
| Synchronous ETL froze requests 10-60s | Moved to background thread (README perf table) |
| Plotly 3.5MB on every page | Lazy-loading on 4 pages only |
| Debug-reloader double-bootstrap | WERKZEUG_RUN_MAIN guard (__init__.py:77) |
| "17 usability fixes" overreach -> reverted after 34 min | git 08-23 12:03 -> 12:37 |
| plotly in requirements "to silence import warning" | commit 08-17 23:21 (now dead dep) |

## 19. Traditional vs Current Solution

| Aspect | Traditional (Spreadsheets / Manual) | InventoryLogix |
|--------|--------------------------------------|----------------|
| **Data source** | Manual entry, fragmented CSVs | Centralized PostgreSQL, 180K+ seeded transactions |
| **Demand forecasting** | Spreadsheet formulas or none | Prophet/ARIMA ensemble with confidence intervals |
| **Anomaly detection** | Manual review, reactive | Isolation Forest + SPC control charts, proactive |
| **EOQ calculation** | Static Excel formula, updated quarterly | Live per-product EOQ with 3D sensitivity visualization |
| **Reorder decisions** | Based on gut feel or minimum stock alerts | Severity-sorted reorder queue with configurable thresholds |
| **Supplier tracking** | No structured tracking | Reliability scores, lead times, spend tracking |
| **Audit trail** | None | Full audit log on every mutating action |
| **Access control** | File-level sharing | Role-based (admin/manager/viewer) with rate limiting |
| **Reporting** | Manual pivot tables | 5-tab reports with 15+ interactive charts, filterable |
| **Data warehouse** | None | SCD Type 2 dimensions, fact tables, ETL pipeline |
| **API** | None | REST API for system integration |

## 20. Business Benefits

### 20.1 Cost Savings

| Benefit | Label | Explanation |
|---------|-------|-------------|
| Reduced carrying cost | Potential | EOQ optimization identifies optimal order quantities that minimize the sum of ordering and holding costs. |
| Fewer emergency orders | Potential | Forecast-driven reordering reduces panic buys at premium prices. |
| Reduced stockout losses | Potential | Anomaly detection and severity-sorted alerts catch low-stock situations earlier. |
| Lower administrative overhead | Potential | Single platform replaces multiple spreadsheets and manual reconciliation steps. |

### 20.2 Efficiency

| Benefit | Label | Explanation |
|---------|-------|-------------|
| Faster reorder decisions | Implemented | Dashboard KPIs + reorder queue present actionable data in one view. |
| Automated forecasting | Implemented | Prophet/ARIMA ensemble runs on-demand; no manual regression analysis needed. |
| Non-blocking ETL | Implemented | Data warehouse refresh runs in background thread, doesn't block dashboard. |
| API-driven integration | Implemented | REST endpoints enable programmatic data exchange with external tools. |

### 20.3 Decision Quality

| Benefit | Label | Explanation |
|---------|-------|-------------|
| Data-grounded EOQ | Implemented | EOQ uses real demand rate, ordering cost, and holding cost from transaction data. |
| Confidence intervals on forecasts | Implemented | Users see prediction ranges, not just point estimates, enabling risk-aware planning. |
| SPC control charts | Implemented | Statistical process control provides objective thresholds for anomaly investigation. |
| Historical trend analysis | Implemented | Data warehouse with SCD Type 2 enables evolution queries. |

### 20.4 Value Classification

**Measured (of seeded data only):** inventory value, reorder counts, stock health %, turnover by category, ABC classes, slow-mover days idle, supplier spend, sales trends, warehouse breakdowns — all live SQL. [E1]

**Synthetic (never present as measured):**
- **"AI savings YTD"** — EOQ policy vs hypothetical "order monthly" baseline on estimated costs (ordering cost hardcoded $50, holding assumed 20% of unit price). Guaranteed positive by construction. (ui.py:279-308; dataset_service.py:311-313)
- **Forecast "accuracy %"** — in-sample MAPE on fitted values; MA fallback hardcodes 78.0 (forecasting.py:55, 83, 125-126).
- **Landing KPIs** — hardcoded demo numbers (ui.py:1992-2017, docstring admits it).
- **Dashboard footers** ("+6.2% vs last month") — hardcoded strings; `units_today` falls back to fake 1248 (ui.py:113).

**Potential (unmeasured, plausible mechanisms):** fewer stockouts via surfaced reorder queue; lower carrying cost via EOQ-sized orders; earlier error detection via SPC; faster PO cycles via auto-draft.

## 21. Security Analysis

### 21.1 Implemented (E1)

- Werkzeug password hashing; policy 8-128 chars letter+digit
- CSRF app-wide, 8h TTL, disabled in tests
- Per-request CSP nonce; no unsafe-inline scripts; 3 CDNs whitelisted; style-src unsafe-inline; no SRI
- Cookies Secure/HttpOnly/SameSite=Lax; strong session protection; DB session tracking
- Lockout 5/15min in-memory + threading.Lock
- Flask-Limiter memory:// hardcoded; RATELIMIT_STORAGE_URI env shadowed
- RBAC decorators on all API writes; 2 UI routes inline-check instead
- Zero f-string SQL; reports builds SQL from hardcoded fragments only (user values stay in %s tuples)
- Reset tokens: urlsafe(48), SHA-256-stored, single-active (purge), 5-min TTL, DB-level used/expiry check; consume lacks WHERE used=FALSE (race window)
- .env gitignored; SECRET_KEY generated on Render; fallback "change-me-in-production" has no prod fail-fast
- Audit triggers on all mutating tables
- HTTP security headers: nosniff, X-Frame-Options, Referrer-Policy, Permissions-Policy, CSP

### 21.2 Gaps (E1, ranked)

1. **Committed credential** — live Supabase DSN with password in alembic.ini:7 (rotate + remove).
2. **Unthrottled AI portfolio endpoints** — user-controlled cache keys (horizon/contamination) -> unbounded model fits -> CPU exhaustion by any authenticated viewer (ai.py:55-66, 105-118).
3. **Multi-worker fragility** — lockout dict, memory:// limiter, 9 caches, bootstrap flag all per-process; a second worker silently multiplies auth limits and splits cache invalidation. Masked by 1-worker deploy.
4. **Reset link in logs** — full reset link logged at WARNING when no mail transport configured (mailer.py:125-131).
5. **SECRET_KEY fallback** "change-me-in-production" with no prod fail-fast (settings.py:17).
6. **CDN scripts without SRI** — 3 CDNs whitelisted; compromise = direct XSS channel. `style-src 'unsafe-inline'` (accepted tradeoff).
7. **Registration user-enumeration** via distinct "already taken" messages (auth_service.py:49-52).
8. **Background ETL thread** — no app context -> likely silent failure; no concurrency guard (double-click = racing TRUNCATE rebuilds).
9. Minor: reset-token consume lacks `WHERE used=FALSE` (tiny double-use race); session_token attr lost on user reload; no 2FA; exception strings surfaced to clients on forecast failure.

## 22. Performance Analysis

| Claim | Verdict | Evidence |
|---|---|---|
| Context processor cached 60s | **Partial** — blueprint processor cached (ui.py:65); duplicate app-level processor runs the same COUNT(*) uncached per request (__init__.py:169-179) | E1 |
| Plotly lazy-loaded | **True** — 4 pages only; Chart.js still global | templates grep |
| Dashboard queries 14->11 | **Partial** — 11 inline + 2 repo calls = 13 total | ui.py:91-284 |
| Reports cache 300s ("10x fewer cold hits") | **True but framing off** — 300s = the old "5min" claim | cache.py:81 |
| AI portfolio cached 1h | **True** — with unbounded-key caveat | ai.py:20 |
| ETL non-blocking | **Code exists, likely broken** — thread touches current_app outside context (ui.py:1986 -> etl.py:38) | E1 static |
| Reports 30+ -> 25+ queries | ~40 sequential per cold miss observed; LRU max 20 thrashes past 20 filter combos | ui.py:855-1720 |

**Additional:** pool of 20 with keepalives; per-user/day dashboard cache; daemon ETL thread (idempotent, watermark-recoverable).

## 23. Scalability Analysis

Ceiling: **2 concurrent in-flight requests** (1 worker x 2 threads) on free-tier Postgres. Constraints in order: (a) 2-thread cap; (b) reports ~40-query battery; (c) per-process state (limiter, lockout, caches, bootstrap, pools) blocks horizontal scaling; (d) 20-conn pool/worker vs free-tier connection budgets; (e) ML fits in-request under the same threads; (f) ETL-at-boot cold-start latency (RUN_ETL_ON_STARTUP knob exists). Comfortable serving low-tens of concurrent internal users.

**Upgrade path:** Redis state first, then multi-worker + PgBouncer, then read replicas/CDN. [E2/E3]

## 24. Testing

### 24.1 Test Coverage

97 tests / 8 files: ML 33 (deterministic spike-detection assertions), services 29, security 12, cache 8, roles 7, auth 4, API 4, ETL 3.

TestingConfig disables CSRF (settings.py:98). Strategy: unit tests for ML models, integration tests for API, security tests, RBAC tests on write routes.

### 24.2 Untested (E1 gaps)

Dashboard/reports/monitoring routes (the largest code), account lockout, reset-token flow, mailer, PO transitions, the ETL thread, CSRF flows.

## 25. Deployment

### 25.1 Render Blueprint

Free Postgres + free web service (python, oregon); build `pip install -r requirements.txt`; start `gunicorn run:app --workers 1 --threads 2 --timeout 120 --access-logfile -`; health check `/api/health`; autoDeploy on push. Env: FLASK_ENV, DATABASE_URL (fromDatabase — **name mismatch at render.yaml:19 vs 38**), generated SECRET_KEY, manual SENDGRID_API_KEY, MAIL_FROM, TLS, 5-min reset TTL.

### 25.2 Local Development

venv -> pip install -> copy .env -> `python run.py` -> http://localhost:5000. Schema + seed + optional ETL run automatically on first boot (idempotent, reloader-guarded).

### 25.3 Demo Credentials

| User | Password | Role |
|------|----------|------|
| admin | Admin@123 | admin |
| manager | Manager@123 | manager |
| viewer | Viewer@123 | viewer |

## 26. Limitations

### 26.1 Technical

- Single-process state (lockout, rate limits, caches, bootstrap flag all per-process)
- ui.py 2051 lines / reports() 1156 lines with ~56 inline SQL sites bypassing the SP discipline
- Duplicate uncached context processor
- Likely-broken background ETL thread (app context bug)
- render.yaml DB name mismatch (19 vs 38)
- Committed DSN in alembic.ini
- Dead code: trg_cleanup_stale_sessions, fact_product_daily, landing_cache, flask-migrate, pip plotly, orphaned JS files
- Multiple audit rows per movement
- Misleading trigger name (trg_movement_stock_update only logs)

### 26.2 Business

- Single-tenant; no multi-tenancy
- No ERP/WMS/billing/shipping connectors
- No notifications (toggles decorative)
- No user management UI
- Single currency (INR)
- One product per PO
- Per-user settings inconsistency
- English-only
- Polling-based UI (no WebSockets)

### 26.3 Data Honesty

- AI savings, forecast accuracy, landing stats are synthetic (see Section 20.4)
- PRODUCT.md's "forecast accuracy >90%" success metric is unmeasured (in-sample MAPE only)
- No production users; no ROI/stockout/adoption measurement exists

## 27. Future Enhancements

### Priority 1 (Critical)
1. Rotate + remove the committed DSN; fix render.yaml names; add SECRET_KEY prod fail-fast.
2. Rate-limit + clamp portfolio endpoints.
3. Push app context into the ETL thread + concurrency guard.

### Priority 2 (High)
4. PO receipt reconciliation inside `sp_po_update_status` (auto IN movement + clear on_order).
5. Reorder email alerts via existing Mailer + `sp_product_low_stock`.
6. Redis state + multi-worker (unshadow RATELIMIT_STORAGE_URI).

### Priority 3 (Medium)
7. Scheduled ETL/retrain (APScheduler) — `etl_warehouse_state` tracks watermarks.
8. Forecast-driven reorder points — forecast_cache + supplier lead_days + `calculate_reorder_point` exist; just not wired.
9. Admin user-management UI — `sp_user_change_role`/`sp_user_set_active`/`sp_user_list_all` already written.
10. Audit-log compliance console; SRI/vendor CDN JS.

### Priority 4 (Future)
11. Out-of-sample forecast backtesting.
12. WebSocket real-time updates, 2FA, PWA, multi-tenancy, read replicas, CI/CD.

## 28. Literature Review

### 28.1 Inventory Management Systems

Inventory management has evolved from manual ledger-based tracking to technology-driven systems incorporating AI, IoT, and blockchain. Kumar (2024) reviews recent trends, noting the shift from conventional deterministic models toward advanced sustainable and technology-driven systems [1]. Pandey et al. (2023) identify that modern systems leverage barcode scanning, real-time analytics, and RFID technology to optimize stock levels [2]. Otaraku (2024) highlights that effective integration of IMS with other business processes in complex, multi-location environments remains a significant challenge [3].

### 28.2 ML-Based Demand Forecasting

The Epicor/Nucleus Research 2024 study surveyed 1,700+ supply chain leaders, finding businesses implementing ML most frequently in inventory optimization (45%) and demand forecasting (40%) [7]. Facebook Prophet (Taylor and Letham, 2018) handles missing data, trend changes, and seasonal effects [9]. Jenifa et al. (2025) demonstrate that integrating selected features improves ARIMA and Prophet performance by up to 23% [10]. Jubran et al. (2026) propose a multi-layered ML ensemble achieving 91.6% prediction accuracy and reducing stockout rates by 59.3% [13].

### 28.3 Anomaly Detection

The Isolation Forest algorithm (Liu et al., 2008) identifies anomalies as instances with short average path lengths in isolation trees [14]. SPC z-score analysis provides statistical thresholds (mu +/- 3sigma) for process control.

### 28.4 EOQ Optimization

The Economic Order Quantity model (Harris, 1913) minimizes total inventory cost by balancing ordering and holding costs [15]. Modern extensions address stochastic demand, quantity discounts, and multi-echelon systems. The 3D sensitivity surface addresses the classical critique of deterministic EOQ inputs.

### 28.5 Commercial Solutions

| Solution | Type | Cost | Limitation |
|----------|------|------|------------|
| SAP Inventory | Enterprise ERP | $$$$ | Overkill for SMEs; complex implementation |
| Oracle Inventory | Enterprise ERP | $$$$ | High TCO; steep learning curve |
| Zoho Inventory | SaaS | $69/mo+ | No ML; no EOQ; limited customization |
| inFlow Inventory | SaaS | $110/mo+ | No ML; no anomaly detection |
| **InventoryLogix** | **Open-source** | **Free** | **ML + EOQ + anomaly + data warehouse** |

### 28.6 Research Gaps Addressed

1. Integration of ML forecasting + EOQ optimization in one open-stack application
2. Real-data grounding (180K+ transactions) with transparent synthetic fallback
3. 3D EOQ sensitivity visualization for decision support
4. SME-accessible inventory intelligence (no enterprise license)
5. Graceful ML degradation when libraries unavailable
6. Open-stack security (CSP, RBAC, parameterized SQL) in inventory tools

### 28.7 References

[1] Kumar, R. (2024). "Recent trends in inventory management: A comprehensive review." Journal of Supply Chain Management.
[2] Pandey, S. et al. (2023). "Inventory Management Systems: A Comprehensive Review." International Journal of Logistics Management.
[3] Otaraku, I.J. (2024). "Review of Inventory Management Systems." International Journal of Science and Research Archive.
[4] Gur, B. et al. (2023). "Artificial intelligence in inventory management: A systematic review." Journal of Big Data.
[5] Panigrahi, S. et al. (2024). "Inventory Management and SME Performance." Sustainable Operations and Computers.
[6] Mankar, P. & Khan, S. (2023). "Inventory Management Research in Transport and Logistics." International Journal of Research in Transport Logistics.
[7] Epicor/Nucleus Research (2024). "2024 Agility Index Study."
[8] E2open (2024). "Forecasting and Inventory Benchmark Study."
[9] Taylor, S.J. & Letham, B. (2018). "Forecasting at Scale." The American Statistician, 71(1), 23-34.
[10] Jenifa, R. et al. (2025). "Integrating selected features to enhance ARIMA and Prophet forecasting models."
[11] Patel, D. et al. (2024). "LSTM, Prophet, and SARIMA Ensemble for Inventory Forecasting."
[12] Data-driven predictive frameworks for inventory optimization (2024). XGBoost ensemble study.
[13] Jubran, N. et al. (2026). "Multi-layered ML ensemble for demand forecasting and reorder-point prediction."
[14] Liu, F.T. et al. (2008). "Isolation Forest." IEEE International Conference on Data Mining.
[15] Harris, F.W. (1913). "How many parts to make at once." Factory, The Magazine of Management.

## 29. Evidence Register

### Architecture & Stack

| # | Claim | Level | Evidence |
|---|---|---|---|
| 1 | App factory + 4 blueprints | E1 | app/__init__.py:31-151; routes/__init__.py |
| 2 | ThreadedConnectionPool(1,20), per-request g.db, teardown rollback | E1 | connection.py:33-39, 92-131; __init__.py:143 |
| 3 | Bootstrap executes 5 SQL files -> seed -> optional ETL, once per process, reloader-guarded | E1 | connection.py:134-155, 175-195; __init__.py:77-83 |
| 4 | Gunicorn 1 worker x 2 threads, rationale documented in-repo | E1 | run.py:41-49, 56-80; render.yaml:30 |
| 5 | ui.py bypasses services/repos (~56 inline SQL sites); reports() ~1156 lines, ~40 queries | E1 | ui.py:734-1890 |
| 6 | Dead deps: pip plotly (never imported), flask-migrate (never wired) | E1 | requirements.txt:2,13 |
| 7 | Dead code: trg_cleanup_stale_sessions, fact_product_daily, landing_cache | E1/E2 | triggers.sql:121-133; warehouse.sql:163-175; ui.py:35 |

### Data & Warehouse

| # | Claim | Level | Evidence |
|---|---|---|---|
| 8 | 74 SQL functions; 65 sp_/etl_ procedures; 8 triggers; 28 tables | E1 | grep counts |
| 9 | trg_validate_movement auto-populates SKU + blocks negative stock | E1 | triggers.sql:196-225 |
| 10 | SCD2: valid_from/valid_to/is_current/row_hash + partial index | E1 | warehouse.sql:9-83 |
| 11 | Incremental watermark ETL; single transaction; stock-walk clamping | E1 | etl.py:74-88, 296-314, 328-405 |
| 12 | Seed: DataCo CSV or deterministic synthetic fallback; 10 warehouses; 36 curated suppliers; 3 demo users | E1 | seed.py:25-450 |
| 13 | 118 products / 150 suppliers / 180K+ transactions | E2 | seed.py; PRODUCT.md:21 |

### Security

| # | Claim | Level | Evidence |
|---|---|---|---|
| 14 | Werkzeug password hashing; policy 8-128 chars letter+digit | E1 | user_repo.py:4,18,44-48; validators.py:70-79 |
| 15 | CSRF app-wide, 8h TTL, disabled in tests | E1 | extensions.py:14; settings.py:27,98 |
| 16 | Per-request CSP nonce; no unsafe-inline scripts; 3 CDNs whitelisted | E1 | headers.py:17-43; base.html:11,43-46 |
| 17 | Lockout 5/15min in-memory + threading.Lock | E1 | auth_service.py:28-29, 66-86 |
| 18 | Committed live Supabase DSN (password) in alembic.ini:7 | E1 | alembic.ini (value redacted) |
| 19 | render.yaml DB name mismatch | E1 | render.yaml |
| 20 | AI portfolio endpoints unthrottled | E1 | ai.py:55-66, 105-118 |
| 21 | Background ETL thread calls current_app outside app context | E1/E2 | ui.py:1981-1986; etl.py:37-45 |

### ML & Analytics

| # | Claim | Level | Evidence |
|---|---|---|---|
| 22 | Prophet >=14 pts weekly-only; ARIMA(1,1,1) >=20 pts 95% CI; ensemble average; MA fallback | E1 | forecasting.py:18-158 |
| 23 | Fallback accuracy hardcoded 78.0; ensemble/Prophet accuracy = in-sample MAPE | E1 | forecasting.py:55, 81-83, 123-126 |
| 24 | IsolationForest univariate, contamination 0.05, 80 trees, seed 42; "confidence" synthetic formula | E1 | anomaly.py:24-49 |
| 25 | EOQ = root(2DS/H) server + client copies; sensitivity 3D grid | E1 | helpers.py:59-73; eoq.js:27; eoq_service.py:49-80 |

### Performance & Caching

| # | Claim | Level | Evidence |
|---|---|---|---|
| 26 | Two reorder-count context processors: blueprint cached 60s; app-level uncached | E1 | ui.py:54-71; __init__.py:157-189 |
| 27 | Plotly lazy on exactly 4 pages; Chart.js global | E1 | template grep; base.html:43-44 |
| 28 | Reports cache 300s; LRU max 20 entries | E1 | cache.py:81; ui.py:841-853 |
| 29 | AI portfolio cache 1h, max 10, never busted | E1 | ai.py:20, 60-66, 112-118 |

### Business Value

| # | Claim | Level | Evidence |
|---|---|---|---|
| 30 | "AI savings YTD" = EOQ-vs-monthly-ordering counterfactual; always positive by construction | E1 | ui.py:279-308 |
| 31 | Landing KPIs hardcoded demo values | E1 | ui.py:1992-2017 |
| 32 | No production users; no ROI measurement exists | E1/E4 | absence verified |
| 33 | No ERP/WMS/billing/shipping connector code | E1 | grep negative |

### Git History

| # | Claim | Level | Evidence |
|---|---|---|---|
| 34 | 2026-08-15 -> 2026-09-10; 73 commits; 10 active days; single developer | E1 | git log |
| 35 | First commit = big-bang import (96 files, 15,240 lines) | E1 | git show --stat fb795be |
| 36 | No tags/releases | E1 | git tag (empty) |

## 30. Final Assessment

### 30.1 Maturity Rating

**Advanced MVP / early Production-ready** (as a single-tenant internal tool, after fixing the critical security items). Not enterprise-ready (no multi-tenancy, horizontal scaling, approval workflows, or connectors).

| Criterion | Rating | Notes |
|-----------|--------|-------|
| Completeness | High | All core features implemented and functional |
| Testing | High | 97 tests; analytical UI routes untested |
| Security | High (with flagged gaps) | CSP, RBAC, parameterized SQL, audit — plus committed-credential and DoS findings |
| Error handling | High | 7 custom error pages, DB-free fallback, graceful ML degradation |
| Deployment | Medium | Render-ready; blueprint name mismatch needs fixing |
| Scalability | Medium-Low | Pooling + caching, but single-process by design |
| Maintainability | Medium | Clean layering on API side; ui.py 2051 lines bypasses it |
| Operational readiness | Medium | ETL monitoring, no alerting/log aggregation |

### 30.2 Final Summary

- **What it does:** inventory CRUD + reorder + POs + warehouse analytics for one organization, seeded with real supply-chain data, with genuine ML forecasting/anomaly/EOQ optimization.
- **Problem solved:** spreadsheet-driven inventory tracking -> live, audited, optimized replenishment decisions.
- **Target users:** supply chain analysts, warehouse/ops managers, procurement leads, admins (single-org SMEs).
- **Key features:** reorder queue + auto-draft POs; EOQ + 3D sensitivity; Prophet/ARIMA ensemble; IF + SPC; SCD2 warehouse + ETL; RBAC; REST API.
- **Stack:** Flask, PostgreSQL, psycopg2, scikit-learn/statsmodels/Prophet, Chart.js/Plotly/Three.js/GSAP, Gunicorn, Render.
- **Architecture:** Application factory + 4 blueprints + layered services/repos + 84+ stored procedures + 8 triggers + star-schema warehouse.
- **Business value:** Implemented — real-time visibility, automated forecasting, EOQ optimization, audit compliance. Potential — cost savings, fewer stockouts, operational efficiency. Unknown — actual ROI, production adoption.
- **Technical strengths:** DB-level integrity (triggers); security posture (CSP, RBAC, parameterized SQL); graceful ML degradation; real-data grounding; 97 automated tests.
- **Technical weaknesses:** ui.py bypasses layering; per-process state; ETL thread bug; dead code; blueprint mismatch.
- **Security risks:** committed credential; unthrottled portfolio endpoints; multi-worker fragility; reset-link-in-logs; no SRI.
- **Scalability risks:** 2-thread ceiling; in-memory caches/limits; free-tier DB budgets.
- **Current limitations:** single-tenant; no connectors/notifications; demo metrics on dashboards; no user-management UI.
- **Competitive differentiation:** real-dataset grounding + ML + EOQ 3D + SCD2 warehouse in one open self-hostable codebase.
- **Recommended improvements:** Priority list in Section 27.
- **Evidence gaps:** pre-repo development history; production usage; measured business outcomes; runtime verification of the ETL thread.

---

*Report generated: September 11, 2026*
*Evidence classification: E1 (Direct), E2 (Strong Inference), E3 (Engineering Interpretation), E4 (Unknown)*
*All benefits classified as Implemented, Measured, Potential, or Synthetic — no invented ROI, customer counts, or productivity percentages.*
