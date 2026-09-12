# InventoryLogix — Architecture Analysis

> **Version:** 1.0 | **Date:** September 2026
> **Stack:** Flask 3.x · PostgreSQL · psycopg2 · Plotly · Prophet/ARIMA · Isolation Forest

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Module Relationships & Data Flow](#2-module-relationships--data-flow)
3. [Database Architecture](#3-database-architecture)
4. [API Architecture](#4-api-architecture)
5. [Security Architecture](#5-security-architecture)
6. [Performance Architecture](#6-performance-architecture)
7. [ML Pipeline Architecture](#7-ml-pipeline-architecture)
8. [Deployment Architecture](#8-deployment-architecture)
9. [Strengths & Weaknesses](#9-strengths--weaknesses)
10. [Scalability Analysis](#10-scalability-analysis)

---

## 1. Architecture Overview

### 1.1 Application Factory Pattern

InventoryLogix follows the standard Flask application factory pattern. The entry point is `run.py`, which calls `create_app()` from `app/__init__.py`.

```
run.py  →  create_app(config_name)  →  Flask app instance
```

The factory performs these steps in order:

| Step | Method | Purpose |
|------|--------|---------|
| 1 | `get_config(config_name)` | Resolve config class from `FLASK_ENV` |
| 2 | `Flask(...)` + `app.config.from_object(config_cls)` | Create app, load config |
| 3 | `_log_database_target()` / `_ensure_database_configured()` | Fail-fast DB validation (production only) |
| 4 | `_init_extensions(app)` | Register CSRF, Limiter, LoginManager, security headers |
| 5 | `_register_blueprints(app)` | Mount auth, ui, api, ai blueprints |
| 6 | `_register_context(app)` | Context processor for reorder count + settings |
| 7 | `_register_error_handlers(app)` | Error pages for 400–500 |
| 8 | `bootstrap_database()` | Idempotent schema + seed + ETL (once per process) |

**Key implementation detail:** The bootstrap guard (`_BOOTSTRAPPED` global with a `threading.Lock`) ensures schema/seed/ETL runs exactly once per process, even under the Flask debug reloader or Gunicorn's worker model.

**Evidence:**
- `app/__init__.py:31-85` — factory function
- `app/__init__.py:175-195` — `bootstrap_database()` in `app/database/connection.py`

### 1.2 Blueprint System

Four blueprints partition the routing surface:

| Blueprint | URL Prefix | Purpose | Auth Required |
|-----------|-----------|---------|---------------|
| `auth_bp` | `/auth` | Login, register, logout, password reset | No (login/register) / Yes (logout) |
| `ui_bp` | `/` (root) | Dashboard, inventory, suppliers, reports, warehouses, POs | Yes |
| `api_bp` | `/api` | REST CRUD for products, suppliers, movements, settings | Yes (except `/api/health`) |
| `ai_bp` | `/ai` | Forecast, anomaly detection, EOQ sensitivity | Yes |

**Registration order matters:** `auth_bp` is registered first so its routes resolve before the catch-all `/` in `ui_bp`.

**Evidence:** `app/__init__.py:147-151`, `app/routes/__init__.py`

---

## 2. Module Relationships & Data Flow

### 2.1 Layered Architecture

```
┌─────────────────────────────────────────────────────┐
│                   ROUTES (Blueprints)                │
│   auth.py  │  ui.py  │  api.py  │  ai.py            │
├─────────────────────────────────────────────────────┤
│                  SERVICES (Business Logic)           │
│   AuthService  ProductService  MovementService       │
│   ForecastService  AnomalyService  EOQService        │
│   SupplierService  SettingsService                   │
├─────────────────────────────────────────────────────┤
│              REPOSITORIES (Data Access)              │
│   UserRepository  ProductRepository  MovementRepo    │
│   SupplierRepository  AuditRepository  PORepo        │
│   ForecastRepository  SettingsRepository  WHRepo     │
├─────────────────────────────────────────────────────┤
│            SECURITY (Cross-Cutting)                  │
│   headers.py  roles.py  validators.py               │
├─────────────────────────────────────────────────────┤
│              DATABASE (Connection + SQL)             │
│   connection.py  procedures.sql  triggers.sql        │
│   warehouse.sql  etl.py  schema.sql                 │
├─────────────────────────────────────────────────────┤
│                    ML PIPELINE                       │
│   forecasting.py  anomaly.py                         │
├─────────────────────────────────────────────────────┤
│              UTILITIES + CACHING                     │
│   cache.py  helpers.py                               │
└─────────────────────────────────────────────────────┘
```

### 2.2 Request Flow — Example: Creating a Product Movement

```
1. POST /api/movements  (JSON body)
   │
   ├─ @login_required  →  Flask-Login checks session
   ├─ @write_roles_required  →  roles.py: abort(403) if viewer
   ├─ @limiter.limit("60 per minute")  →  flask-limiter
   │
   ▼
2. MovementService.record()
   │
   ├─ Validates mtype ∈ {IN, OUT, ADJUSTMENT, RETURN}
   ├─ ProductRepository.find_for_update(product_id)  →  SELECT ... FOR UPDATE
   ├─ Calculates new_stock (prevents negative)
   ├─ MovementRepository.record()  →  sp_movement_record()
   ├─ ProductRepository.set_stock()  →  sp_product_set_stock()
   ├─ AuditRepository.record()  →  sp_audit_record()
   │
   ▼
3. cache_bust_movements()  →  invalidates all related caches
   │
   ▼
4. api_response({"id": movement_id}, status=201)
```

### 2.3 Dependency Graph (Key Modules)

```
Routes
  ├─→ Services
  │     ├─→ Repositories
  │     │     └─→ database.get_cursor() → psycopg2 pool
  │     ├─→ security.validators
  │     └─→ ml.forecasting / ml.anomaly
  ├─→ utils.cache
  └─→ extensions (limiter, csrf, login_manager)

Database
  ├─→ connection.py (pool, cursor, bootstrap)
  └─→ SQL files (schema, procedures, triggers, warehouse, ETL)
```

---

## 3. Database Architecture

### 3.1 Connection Pooling

**Implementation:** `app/database/connection.py`

- Uses `psycopg2.pool.ThreadedConnectionPool` (min=1, max=20)
- Pool is keyed by config params — one pool per unique DB connection string
- Connections are request-scoped: acquired in `get_connection()`, returned in `close_connection()` via `teardown_appcontext`
- Uses `RealDictCursor` globally — all queries return dict-like rows
- TCP keepalives configured: idle=300s, interval=30s, count=1
- Connect timeout: 15s

**Thread safety:** A `_POOL_LOCK` (`threading.Lock`) guards pool creation. The pool itself is thread-safe (psycopg2's `ThreadedConnectionPool`).

**Evidence:** `app/database/connection.py:33-99`

### 3.2 Stored Procedures

**84+ stored procedures** in `app/database/procedures.sql` (627 lines). All application CRUD goes through these, preventing SQL injection at the database level.

Key procedure groups:

| Group | Procedures | Purpose |
|-------|-----------|---------|
| Products | `sp_product_list`, `sp_product_create`, `sp_product_update`, `sp_product_delete`, `sp_product_set_stock`, `sp_product_low_stock` | Full CRUD + queries |
| Suppliers | `sp_supplier_list_all`, `sp_supplier_create`, `sp_supplier_update`, `sp_supplier_delete` | Supplier management |
| Movements | `sp_movement_record`, `sp_movement_daily_totals`, `sp_movement_daily_for_product` | Stock movements |
| Users | `sp_user_create`, `sp_user_find_by_username`, `sp_user_record_login`, `sp_user_set_password` | Auth |
| Sessions | `sp_session_create`, `sp_session_end`, `sp_session_cleanup_stale` | Session tracking |
| Audit | `sp_audit_record`, `sp_audit_recent`, `sp_audit_count_last_hours` | Audit trail |
| POs | `sp_po_create`, `sp_po_update_status`, `sp_po_counts_by_status` | Purchase orders |
| Settings | `sp_settings_all`, `sp_settings_set_many` | User preferences |
| Forecast | `sp_forecast_save`, `sp_forecast_recent` | Forecast cache |
| Anomaly | `sp_anomaly_save`, `sp_anomaly_recent` | Anomaly log |

**Example — `sp_product_list`:** Builds a CTE with dynamic filtering (search, category, warehouse, status), returns results with a `total_count` window column for pagination.

**Evidence:** `app/database/procedures.sql:8-45`

### 3.3 Triggers

**8 trigger functions** in `app/database/triggers.sql`:

| Trigger | Table | Event | Purpose |
|---------|-------|-------|---------|
| `trg_user_signup` | `users` | AFTER INSERT | Audit log signup |
| `trg_session_create` | `user_sessions` | AFTER INSERT | Audit log login + update `last_login` |
| `trg_session_end` | `user_sessions` | AFTER UPDATE | Audit log logout |
| `trg_validate_movement` | `movements` | BEFORE INSERT | Auto-populate SKU, prevent negative stock |
| `trg_movement_stock_update` | `movements` | AFTER INSERT | Audit log movement |
| `trg_product_audit` | `products` | AFTER INSERT/UPDATE/DELETE | Audit log product changes |
| `trg_supplier_audit` | `suppliers` | AFTER INSERT/UPDATE/DELETE | Audit log supplier changes |
| `trg_po_audit` | `purchase_orders` | AFTER INSERT/UPDATE | Audit log PO changes |

**Notable:** `trg_validate_movement` is a `BEFORE INSERT` trigger that overwrites the caller-provided `sku` with the one from the database, and raises an exception if the movement would create negative stock. This is a defense-in-depth measure — the application layer also checks this in `MovementService.record()`.

**Evidence:** `app/database/triggers.sql:196-225`

### 3.4 Data Warehouse (Star Schema)

**Dimension tables:**

| Table | Type | Purpose |
|-------|------|---------|
| `dim_date` | Static | Date dimension (year, quarter, month, day_of_week, is_weekend) |
| `dim_warehouse` | Static | Warehouse lookup (code, city, region) |
| `dim_product` | SCD Type 2 | Product history (valid_from, valid_to, is_current, row_hash) |
| `dim_supplier` | SCD Type 2 | Supplier history (reliability, lead_days, spend changes) |
| `dim_warehouse_scd` | SCD Type 2 | Warehouse history |
| `dim_user` | SCD Type 2 | User history (role changes, oauth) |

**Fact tables:**

| Table | Grain | Purpose |
|-------|-------|---------|
| `fact_movement_daily` | Day × Warehouse × Product | In/out quantities and values |
| `fact_inventory_daily` | Day × Warehouse × Product | Stock on hand, reorder point |
| `fact_login_events` | Per login attempt | Security analytics |
| `fact_session_activity` | Per session | Duration, IP, user agent |
| `fact_signup_events` | Per registration | Signup tracking |
| `fact_audit_daily` | Day × Action × Target × User | Pre-aggregated audit data |
| `fact_product_daily` | Day × Product × Warehouse | Product-level movement stats |

**SCD Type 2** tracks full history via `valid_from`, `valid_to`, `is_current`, and `row_hash` columns. This enables time-travel queries and historical trend analysis.

**Evidence:** `app/database/warehouse.sql`, `app/database/etl.py`

### 3.5 ETL Pipeline

**Implementation:** `app/database/etl.py` (432 lines)

- **Incremental:** Uses a high-water mark (`etl_state['last_movement_id']`) to process only new/changed movements
- **Full rebuild:** Triggered when `force=True` or fact tables are empty
- **Transactional:** Entire build runs in one transaction — failure leaves previous state intact
- **On startup:** Runs automatically via `bootstrap_database()` (configurable via `RUN_ETL_ON_STARTUP`)
- **Non-blocking option:** Available via `/monitoring` endpoint (threaded)

**Dimension population:**
1. `dim_date` — fills date range from oldest movement to today
2. `dim_warehouse` — derived from `DISTINCT products.warehouse`
3. `dim_product` / `dim_supplier` — SCD Type 2 with row hash comparison

**Evidence:** `app/database/etl.py:1-100`, `app/database/connection.py:168-195`

---

## 4. API Architecture

### 4.1 REST Endpoints

| Method | Endpoint | Purpose | Rate Limit | Auth |
|--------|----------|---------|------------|------|
| GET | `/api/health` | Health check | Default | No |
| GET | `/api/settings` | User preferences | Default | Yes |
| PUT | `/api/settings` | Update preferences | Default | Yes + Write |
| GET | `/api/dashboard/live` | Live KPI data | Default | Yes |
| GET | `/api/products` | Paginated list | 120/min | Yes |
| GET | `/api/products/:id` | Single product | Default | Yes |
| POST | `/api/products` | Create product | 30/min | Yes + Write |
| PUT | `/api/products/:id` | Update product | 30/min | Yes + Write |
| DELETE | `/api/products/:id` | Delete product | 30/min | Yes + Write |
| GET | `/api/suppliers` | List all suppliers | Default | Yes |
| GET | `/api/suppliers/:id` | Single supplier | Default | Yes |
| POST | `/api/suppliers` | Create supplier | 30/min | Yes + Write |
| POST | `/api/movements` | Record movement | 60/min | Yes + Write |
| GET | `/api/movements/recent` | Daily totals | Default | Yes |
| POST | `/api/eoq/calculate` | EOQ calculation | Default | Yes |
| GET | `/ai/forecast/run` | Run forecast | 30/min | Yes |
| GET | `/ai/forecast/portfolio` | Multi-product forecast | Default | Yes |
| GET | `/ai/anomaly/run` | Run anomaly detection | 30/min | Yes |
| GET | `/ai/anomaly/portfolio` | Multi-product anomalies | Default | Yes |
| GET | `/ai/eoq/sensitivity` | Sensitivity surface | Default | Yes |

### 4.2 JSON Envelope

All API responses follow a consistent envelope:

```json
{
  "success": true,
  "data": { ... },
  "message": "Product created.",
  "error": null
}
```

Error responses:

```json
{
  "success": false,
  "data": null,
  "message": null,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "SKU already exists."
  }
}
```

**Evidence:** `app/utils/helpers.py` — `api_response()`, `api_error()`

### 4.3 Caching Strategy

Multi-tier in-memory TTL caching via `app/utils/cache.py`:

| Cache Name | TTL | Max Entries | Scope |
|-----------|-----|-------------|-------|
| `dashboard_cache` | 60s | 10 | Dashboard context (per user+date) |
| `api_cache` | 60s | 50 | REST GET responses |
| `products_cache` | 120s | 50 | Product lists + details |
| `suppliers_cache` | 120s | 50 | Supplier lists |
| `reports_cache` | 300s | 20 | Heavy report queries |
| `global_cache` | 60s | 10 | Reorder count, cross-cutting |
| `landing_cache` | 300s | 5 | Public landing stats |
| `monitoring_cache` | 30s | 5 | ETL status + DB stats |
| `_portfolio_cache` | 3600s | 10 | ML model fitting (AI endpoints) |

**Cache invalidation** uses prefix-based busting:

```
cache_bust_products()  →  invalidates: products, dashboard, reports, global, api("products"), landing
cache_bust_movements() →  invalidates: everything (stock changes affect all views)
cache_bust_suppliers() →  invalidates: suppliers, reports, api("suppliers"), landing
```

**Dashboard caching** is per-user+date (`dashboard:{user_id}:{date}`), so each user gets a fresh dashboard daily but repeated loads within the same day are cached.

**Evidence:** `app/utils/cache.py:78-140`

---

## 5. Security Architecture

### 5.1 Authentication

- **Flask-Login** with `UserProxy` adapter (wraps `psycopg2.RealDictRow`)
- **Password hashing:** Werkzeug's `generate_password_hash` / `check_password_hash` (pbkdf2:sha256)
- **Session management:** DB-backed `user_sessions` table with token tracking
- **Session cookie:** `HttpOnly`, `SameSite=Lax`, `Secure` (configurable)
- **Remember me:** 7-day duration, secure cookies
- **Session lifetime:** 8 hours (`PERMANENT_SESSION_LIFETIME`)
- **Session protection:** "strong" mode in Flask-Login

**Evidence:** `app/extensions.py:9-13`, `app/config/settings.py:18-25`

### 5.2 Account Lockout

In-memory failed login tracker:

```python
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
```

- Uses `defaultdict(list)` keyed by user_id
- Thread-safe via `_lockout_mutex` (`threading.Lock`)
- Old attempts pruned on each check
- Clears on successful login
- Lockout duration: 15 minutes

**Limitation:** Lockout state is per-process and resets on restart. In a multi-worker deployment, each worker has its own lockout tracker.

**Evidence:** `app/services/auth_service.py:27-29, 66-86`

### 5.3 Password Reset

- Token generated via `secrets.token_urlsafe(48)`
- Stored as SHA-256 hash in `password_reset_tokens` table
- TTL: 5 minutes (configurable)
- Single-use: marked as consumed on use
- Previous tokens purged on new request
- Delivery: SendGrid API (HTTPS) → SMTP fallback → UI fallback (dev mode)

**Evidence:** `app/services/auth_service.py:98-151`

### 5.4 Role-Based Access Control (RBAC)

Three roles defined in the database constraint:

```sql
CONSTRAINT users_role_chk CHECK (role IN ('admin','manager','viewer'))
```

**Write operations** restricted to `admin` and `manager`:

```python
WRITE_ROLES = ("admin", "manager")
```

**Decorator pattern:**

```python
@write_roles_required  # → roles_required(*WRITE_ROLES)
def create_product():
    ...
```

Self-registration always assigns `viewer` role — no privilege escalation.

**Evidence:** `app/security/roles.py:1-30`, `app/database/schema.sql:18`

### 5.5 Security Headers

Applied via `after_request` hook in `app/security/headers.py`:

| Header | Value |
|--------|-------|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | `geolocation=(), microphone=(), camera=()` |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` (when Secure cookies enabled) |
| `Content-Security-Policy` | Nonce-based script-src, whitelisted CDN domains |

**CSP nonce:** Generated per-request via `secrets.token_urlsafe(24)`, injected into templates via context processor. Inline scripts use `'nonce-{value}'` instead of `'unsafe-inline'`.

**CSP domains:** `cdn.jsdelivr.net`, `cdnjs.cloudflare.com`, `cdn.plot.ly` (Plotly), `fonts.googleapis.com`, `fonts.gstatic.com`.

**Evidence:** `app/security/headers.py:1-46`

### 5.6 CSRF Protection

- `flask-wtf` `CSRFProtect` initialized globally
- `WTF_CSRF_TIME_LIMIT = 28800` (8 hours)
- Disabled in testing config (`WTF_CSRF_ENABLED = False`)
- Applies to all form submissions

**Evidence:** `app/extensions.py:14`, `app/config/settings.py:27`

### 5.7 Rate Limiting

- `flask-limiter` with `get_remote_address` key function
- Default: `200 per minute`
- Auth endpoints: `10/min` (login), `5/min` (register), `5/hour` (forgot password)
- Write endpoints: `30/min` (products, suppliers), `60/min` (movements)
- Storage: `memory://` (per-process, not shared across workers)

### 5.8 Input Validation

`app/security/validators.py` provides:

| Validator | Pattern/Rule |
|-----------|-------------|
| `validate_sku` | `^[A-Z0-9][A-Z0-9\-_]{1,49}$` |
| `validate_username` | `^[A-Za-z0-9_.\-]{3,60}$` |
| `validate_email` | `^[^@\s]+@[^@\s]+\.[^@\s]+$` |
| `validate_password_strength` | ≥8 chars, ≥1 letter, ≥1 digit |
| `validate_positive_number` | Numeric, ≥0 (or >0) |
| `validate_string_length` | Min/max length check |

**Evidence:** `app/security/validators.py:1-86`

### 5.9 Row-Level Security (RLS)

All public tables have RLS enabled with **zero policies**, making them deny-by-default for non-owner roles:

```sql
ALTER TABLE public.<table> ENABLE ROW LEVEL SECURITY;
```

The Flask app connects as the table owner (`postgres`), which bypasses RLS. This protects against Supabase's auto-generated REST API exposing data to anonymous users.

**Evidence:** `app/database/schema.sql:261-283`

### 5.10 Audit Logging

Dual-layer audit logging:

1. **Application-level:** `AuditRepository.record()` called explicitly in services for every mutation (login, register, product CRUD, movement recording, PO changes)
2. **Database-level:** 8 triggers automatically record changes to `audit_log` table

Audit entries include: `user_id`, `action`, `target_type`, `target_id`, `detail` (JSONB), `ip_address`, `created_at`.

**Evidence:** `app/database/triggers.sql`, `app/repositories/audit_repo.py`

---

## 6. Performance Architecture

### 6.1 Caching Layers

| Layer | Mechanism | Scope |
|-------|-----------|-------|
| L1: In-memory TTLCache | `app/utils/cache.py` | Per-process, 60-3600s TTL |
| L2: Database connection pool | `psycopg2.pool.ThreadedConnectionPool` | Per-process, 20 connections |
| L3: Stored procedures | Pre-compiled SQL in PostgreSQL | Per-database |

### 6.2 Query Optimization

**Dashboard queries** (in `ui.py`) are batched to reduce round-trips:

- **Batch 1:** Product aggregates (total SKUs, inventory value, reorder count, critical/warning counts) — 1 query instead of 4
- **Batch 2:** Category counts, slow movers, top demand, top sales, supplier analytics, warehouse profile, turnover, ABC analysis — ~8 queries total
- **Before optimization:** 14 sequential queries → **After:** 11 queries (per AGENTS.md)

**Database indexes** cover the main access patterns:

```sql
-- Products
idx_products_stock_rop ON products(current_stock, reorder_point, on_order)
idx_products_warehouse_category ON products(warehouse, category)
idx_products_supplier ON products(supplier_id)
idx_products_unit_price ON products(unit_price)

-- Movements
idx_movements_product_created ON movements(product_id, created_at)
idx_movements_type_created ON movements(type, created_at)
idx_movements_product_type_created ON movements(product_id, type, created_at)

-- Purchase Orders
idx_po_supplier_status ON purchase_orders(supplier_id, status)
```

**Evidence:** `app/database/schema.sql:73-101`, `app/routes/ui.py:89-275`

### 6.3 Lazy Loading

Plotly.js is lazy-loaded — only fetched on pages that need charts (dashboard, forecast, anomaly, EOQ):

```html
<!-- Only loaded on chart pages -->
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
```

### 6.4 Concurrency Control

**`SELECT ... FOR UPDATE`** used in `MovementService.record()` to prevent concurrent overdraw:

```python
product = ProductRepository.find_for_update(product_id)  # SELECT ... FOR UPDATE
```

**Evidence:** `app/repositories/product_repo.py:111-115`

### 6.5 Context Processor Caching

The reorder count query in `inject_globals()` runs once per request and is cached in `global_cache` (60s TTL):

```python
reorder_count = global_cache.get_or_set("reorder_count", _count)
```

**Evidence:** `app/routes/ui.py:54-71`

---

## 7. ML Pipeline Architecture

### 7.1 Forecasting

**Three models** with graceful degradation:

```
┌──────────────────────────────────────────────────┐
│              ForecastService.run()                │
│                                                   │
│  ┌─────────┐   ┌─────────┐   ┌──────────┐       │
│  │ Prophet  │   │  ARIMA  │   │ Ensemble │       │
│  │(seasonal)│   │ (trend) │   │ (average)│       │
│  └────┬─────┘   └────┬────┘   └────┬─────┘       │
│       │              │              │              │
│       ▼              ▼              ▼              │
│  ┌─────────────────────────────────────────┐      │
│  │   Moving Average Fallback (stdlib)      │      │
│  │   Used when: prophet/statsmodels not    │      │
│  │   installed, or < 14 data points        │      │
│  └─────────────────────────────────────────┘      │
└──────────────────────────────────────────────────┘
```

| Model | Library | Min Data Points | Fallback |
|-------|---------|----------------|----------|
| Prophet | `prophet` (optional) | 14 days | Moving average |
| ARIMA | `statsmodels` (optional) | 20 days | Moving average |
| Ensemble | Prophet + ARIMA average | Both available | MA when either missing |

**Data pipeline:**
1. `ForecastService.run()` → fetches 180 days of daily movement history
2. Converts to `[{ds, y}]` format for the model
3. Calls the selected model function
4. Saves result to `forecast_cache` table
5. Returns predictions, confidence intervals, accuracy score

**Accuracy calculation:** MAPE-based (Mean Absolute Percentage Error), computed as `100 - (mean_residuals / mean_actuals * 100)`.

**Portfolio mode:** Runs forecasts for up to 12 products, cached for 1 hour (`_portfolio_cache`).

**Evidence:** `app/ml/forecasting.py:1-158`, `app/services/forecast_service.py:1-76`

### 7.2 Anomaly Detection

**Two-layer approach:**

```
┌──────────────────────────────────────────────────┐
│            AnomalyService.run_for_product()       │
│                                                    │
│  Layer 1: Isolation Forest (if sklearn available)  │
│  ├─ Contamination: 0.05 (5% of data)              │
│  ├─ n_estimators: 80                               │
│  └─ Degrades to z-score on failure                 │
│                                                    │
│  Layer 2: SPC Z-Score Analysis (always runs)       │
│  ├─ UCL/LCL at ±3σ (configurable threshold)       │
│  ├─ Mean and sigma computed from series            │
│  └─ Used for control chart visualization           │
└──────────────────────────────────────────────────┘
```

| Component | Library | Fallback |
|-----------|---------|----------|
| Isolation Forest | `sklearn.ensemble.IsolationForest` (optional) | z-score analysis |
| SPC Z-Score | `statistics` (stdlib) | Always available |

**Anomaly types:** `spike` (z > 0) or `drop` (z < 0), with confidence scores and human-readable descriptions.

**Results persisted** to `anomaly_log` table for historical tracking.

**Portfolio mode:** Scans up to 30 products, sorted by max z-score.

**Evidence:** `app/ml/anomaly.py:1-97`, `app/services/anomaly_service.py:1-72`

### 7.3 EOQ Optimization

**Economic Order Quantity** formula: `EOQ = sqrt(2DS/H)`

```python
def calculate_eoq(demand, ordering_cost, holding_cost):
    if holding_cost <= 0 or demand <= 0:
        return None
    return math.sqrt(2 * demand * ordering_cost / holding_cost)
```

**Features:**
- Per-product EOQ table with total cost calculation
- Cost curve visualization (60 data points across EOQ range)
- Sensitivity surface (5×4 grid of demand × ordering cost combinations)
- Auto-reorder integration: drafts POs using EOQ with 6-month demand cap

**Evidence:** `app/utils/helpers.py`, `app/services/eoq_service.py`

---

## 8. Deployment Architecture

### 8.1 Render Blueprint

**`render.yaml`** defines the infrastructure-as-code:

```yaml
databases:
  - name: inventory_db_2ov0
    plan: free

services:
  - type: web
    name: inventory-logix
    runtime: python
    plan: free
    region: oregon
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn run:app --workers 1 --threads 2 --timeout 120
    healthCheckPath: /api/health
    autoDeploy: true
```

**Key decisions:**
- **1 worker, 2 threads** — keeps one process = one DB connection pool = no pool contention
- **120s timeout** — accommodates ML model fitting and ETL
- **Free tier** — auto-sleeps after inactivity, cold starts take ~30s

### 8.2 Gunicorn Configuration

```python
_GunicornServer(app, {
    "bind": f"{host}:{port}",
    "workers": 1,
    "threads": 2,
    "timeout": 120,
    "accesslog": "-",
    "errorlog": "-",
}).run()
```

**Evidence:** `run.py:41-80`

### 8.3 Environment Configuration

Three config classes via `app/config/settings.py`:

| Config | Debug | CSRF | Cookie Secure | ETL on Startup |
|--------|-------|------|---------------|----------------|
| `DevelopmentConfig` | True | Enabled | False | True |
| `ProductionConfig` | False | Enabled | True | True |
| `TestingConfig` | False | **Disabled** | — | — |

**Environment detection:** `FLASK_ENV` → falls back to checking `RENDER_INSTANCE_ID` → defaults to `development`.

### 8.4 Email Delivery

Dual-path email for password reset:

```
1. SendGrid API (HTTPS) — preferred, works on Render free tier
   └─ Falls back to ↓
2. SMTP (smtplib) — blocked on Render free tier
   └─ Falls back to ↓
3. UI display — reset link shown in flash message (dev mode)
```

**Evidence:** `app/services/mailer.py:56-143`

---

## 9. Strengths & Weaknesses

### 9.1 Strengths

| Area | Detail |
|------|--------|
| **Defense in depth** | SQL injection prevented at 3 layers: stored procedures, parameterized queries, trigger validation |
| **Graceful ML degradation** | App works fully without Prophet/sklearn/statsmodels — falls back to stdlib implementations |
| **Comprehensive audit trail** | Dual-layer (app + triggers) audit logging for every data mutation |
| **Consistent API design** | Uniform JSON envelope, proper HTTP status codes, typed error codes |
| **Idempotent bootstrap** | Schema + seed + ETL runs once per process, safe under reloader and multi-worker |
| **Multi-tier caching** | Per-concern caches with prefix-based invalidation, proper TTLs |
| **Concurrency safety** | `SELECT FOR UPDATE` prevents stock overdraw; trigger-level negative stock prevention |
| **SCD Type 2 warehouse** | Full historical tracking of product/supplier changes for time-travel analytics |
| **Security headers** | Nonce-based CSP, HSTS, frame denial, permissions policy — production-grade |
| **Password reset flow** | Token hashing, TTL, single-use, purge old tokens, email fallback chain |
| **Configuration flexibility** | DATABASE_URL or individual DB_* vars, feature flags, configurable thresholds |

### 9.2 Weaknesses

| Area | Detail | Impact |
|------|--------|--------|
| **In-memory rate limiting** | `memory://` storage — resets on restart, not shared across workers | Rate limits ineffective after restart; not applicable with 1 worker |
| **In-memory lockout** | Failed login tracker is per-process | Lockout resets on deploy; no cross-worker coordination |
| **In-memory cache** | All TTLCache instances are per-process | Cache is cold after every deploy; no shared invalidation across workers |
| **SQL injection in reports** | `ui.py` reports route uses f-string interpolation for `product_where` clauses | Parameterized values are safe, but the dynamic SQL construction via f-strings is fragile |
| **No migration tool** | Schema applied via raw SQL files, not Alembic | Schema drift risk; no rollback capability for schema changes |
| **Dashboard query complexity** | `ui.py:dashboard()` executes ~11 queries inline in one route handler | Hard to test independently; route function is 300+ lines |
| **No API versioning** | `/api/` prefix but no version segment | Breaking changes require client coordination |
| **No background job queue** | ETL and ML run synchronously in request threads | Long-running operations block request threads |
| **Test coverage gaps** | Tests exist but are thin (31-line test_api.py, 36-line test_auth.py) | Limited regression protection |
| **SECRET_KEY default** | `change-me-in-production` as default | Security risk if env var not set in production |
| **No connection pool health checks** | Pool doesn't validate connections before handing them out | Stale connections may cause errors under load |

---

## 10. Scalability Analysis

### 10.1 Current Constraints

| Component | Bottleneck | Threshold |
|-----------|-----------|-----------|
| Gunicorn workers | 1 worker (by design) | ~50 concurrent users |
| DB connection pool | 20 connections per process | 20 concurrent DB queries |
| In-memory cache | Per-process, ~50 entries per cache | Cache hit ratio drops with data growth |
| ML inference | Synchronous, per-request | ~2-5s per forecast (Prophet fitting) |
| ETL pipeline | Full rebuild: 10-60s | Blocks bootstrap on cold start |
| Render free tier | Auto-sleep, 512MB RAM | Cold start penalty, memory pressure |

### 10.2 Horizontal Scaling Path

```
Current (1 worker):
  Gunicorn (1 worker, 2 threads) → 1 DB pool → PostgreSQL

Scale to 4 workers:
  Gunicorn (4 workers, 2 threads each) → 4 DB pools (80 connections) → PostgreSQL
  ⚠ Problems:
    - Rate limiting ineffective (per-process memory)
    - Lockout ineffective (per-process memory)
    - Cache cold per worker (4× cold misses)
    - DB connection pressure (80 connections)
```

### 10.3 Recommended Scaling Changes

| Change | Effort | Impact |
|--------|--------|--------|
| Switch to Redis for rate limiting/cache | Medium | Shared state across workers |
| Add connection pooling proxy (PgBouncer) | Low | Reduces PostgreSQL connection count |
| Move ETL to background worker (Celery/RQ) | Medium | Unblocks request threads |
| Add API response compression (gzip) | Low | Reduces bandwidth |
| Implement query result caching in PostgreSQL | Low | Offloads repeated expensive queries |
| Add read replicas for analytics queries | High | Separates OLTP from OLAP |

### 10.4 Data Growth Projections

| Table | Growth Rate | 1-Year Volume |
|-------|------------|---------------|
| `movements` | ~100-500/day | 36K-180K rows |
| `fact_movement_daily` | ~50/day | 18K rows |
| `audit_log` | ~200/day | 73K rows |
| `forecast_cache` | ~12/day | 4K rows |
| `anomaly_log` | ~10/day | 3.6K rows |

At this scale, the current PostgreSQL instance handles the load comfortably. The star schema with SCD Type 2 dimensions is well-designed for this volume.

---

## Evidence Register

| Claim | Evidence File | Lines |
|-------|--------------|-------|
| Application factory pattern | `app/__init__.py` | 31-85 |
| Connection pooling (ThreadedConnectionPool, max=20) | `app/database/connection.py` | 33-35, 62-69 |
| 84+ stored procedures | `app/database/procedures.sql` | 1-627 |
| 8 trigger functions | `app/database/triggers.sql` | 1-283 |
| SCD Type 2 dimensions | `app/database/warehouse.sql` | 1-186 |
| Incremental ETL with high-water mark | `app/database/etl.py` | 1-100 |
| CSP nonce per-request | `app/security/headers.py` | 17-19, 33-42 |
| RBAC: WRITE_ROLES = ("admin", "manager") | `app/security/roles.py` | 9 |
| Account lockout (5 attempts, 15 min) | `app/services/auth_service.py` | 24-25, 66-86 |
| Password reset: SHA-256 hash, 5-min TTL | `app/services/auth_service.py` | 127-131 |
| Prophet/ARIMA graceful fallback to MA | `app/ml/forecasting.py` | 17-27, 61-97 |
| Isolation Forest fallback to z-score | `app/ml/anomaly.py` | 11-16, 24-81 |
| Multi-tier TTL cache with prefix invalidation | `app/utils/cache.py` | 78-140 |
| SELECT FOR UPDATE for concurrency | `app/repositories/product_repo.py` | 111-115 |
| Dashboard queries batched (14→11) | `app/routes/ui.py` | 89-275 |
| Render Blueprint: 1 worker, 2 threads | `render.yaml` | 30 |
| RLS enabled on all tables | `app/database/schema.sql` | 261-283 |
| Dual email delivery (SendGrid → SMTP → UI) | `app/services/mailer.py` | 56-143 |
| Test suite: 8 test files | `tests/test_*.py` | — |
| Idempotent bootstrap guard | `app/database/connection.py` | 175-195 |
