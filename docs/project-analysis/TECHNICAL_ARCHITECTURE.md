# InventoryLogix — Technical Architecture

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client Layer                              │
│  Browser → Jinja2 Templates → Chart.js / Three.js / GSAP       │
└─────────────────────────────┬───────────────────────────────────┘
                              │ HTTPS
┌─────────────────────────────▼───────────────────────────────────┐
│                     Application Layer                            │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐              │
│  │ Auth BP │ │  UI BP  │ │ API BP  │ │  AI BP  │              │
│  │ /auth/* │ │   /*    │ │ /api/*  │ │ /ai/*   │              │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘              │
│       │           │           │           │                     │
│  ┌────▼───────────▼───────────▼───────────▼─────────────────┐  │
│  │              Services Layer                                │  │
│  │  AuthService, ProductService, MovementService,            │  │
│  │  EOQService, ForecastService, AnomalyService              │  │
│  └────────────────────────┬──────────────────────────────────┘  │
│                           │                                      │
│  ┌────────────────────────▼──────────────────────────────────┐  │
│  │              Repositories Layer                            │  │
│  │  ProductRepo, SupplierRepo, MovementRepo, UserRepo,       │  │
│  │  AuditRepo, WarehouseRepo, SettingsRepo, ForecastRepo     │  │
│  └────────────────────────┬──────────────────────────────────┘  │
└───────────────────────────┼──────────────────────────────────────┘
                            │ psycopg2 (parameterized)
┌───────────────────────────▼──────────────────────────────────────┐
│                     Data Layer                                    │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │   PostgreSQL     │  │  Connection Pool  │  │   Triggers   │  │
│  │  (12 operational │  │  (20 max conn)    │  │  (8 functions)│  │
│  │   + 15 warehouse │  │  ThreadedPool     │  │  Audit/Valid │  │
│  │   tables)        │  │                   │  │              │  │
│  └──────────────────┘  └──────────────────┘  └──────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │           Stored Procedures (84+ PL/pgSQL functions)      │   │
│  │  sp_product_list, sp_movement_create, sp_po_update_status │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Flask Application Factory

**Entry Point:** `run.py` → `create_app()` from `app/__init__.py`

**Key Responsibilities:**
- Load configuration from `app/config/settings.py`
- Initialize extensions (Flask-Login, Flask-WTF, Flask-Limiter)
- Register blueprints (auth, ui, api, ai)
- Setup security headers with CSP nonces
- Bootstrap database (schema, seed, ETL)
- Register error handlers (400-500)

**Configuration Classes:**
```python
class Config:          # Base (env vars)
class DevelopmentConfig(Config):  # DEBUG=True
class ProductionConfig(Config):   # DEBUG=False, Secure cookies
class TestingConfig(Config):      # TESTING=True, no CSRF
```

### 2. Database Layer

**Connection Management:**
- `psycopg2.pool.ThreadedConnectionPool` (1-20 connections)
- Per-request connection via Flask `g` object
- Automatic cleanup on request teardown

**Schema Bootstrap:**
1. `schema.sql` — 12 operational tables
2. `procedures.sql` — 84+ stored procedures
3. `warehouse.sql` — SCD Type 2 dimensions
4. `etl_procedures.sql` — ETL functions
5. `triggers.sql` — 8 trigger functions

**Stored Procedure Pattern:**
```sql
CREATE OR REPLACE FUNCTION sp_product_list(
    p_search TEXT DEFAULT '',
    p_category TEXT DEFAULT '',
    ...
) RETURNS TABLE (...) AS $$
BEGIN
    RETURN QUERY
    SELECT ...
    WHERE (p_search = '' OR p.sku ILIKE '%' || p_search || '%')
    LIMIT p_limit OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;
```

### 3. Repository Pattern

**All database access goes through repositories:**
```python
class ProductRepository:
    @classmethod
    def list(cls, *, search, category, warehouse, status, limit, offset):
        with get_cursor() as cur:
            cur.execute(
                "SELECT * FROM sp_product_list(%s, %s, %s, %s, %s, %s)",
                (search, category, warehouse, status, limit, offset),
            )
            rows = cur.fetchall()
        return [_decorate(r) for r in rows], total
```

**Benefits:**
- All queries parameterized (SQL injection prevention)
- Stored procedures encapsulate business logic
- Easy to test (mock repository layer)
- Consistent data access pattern

### 4. Service Layer

**Business logic orchestration:**
```python
class ProductService:
    @classmethod
    def create(cls, payload: dict) -> int:
        payload = cls.validate_payload(payload)
        existing = ProductRepository.find_by_sku(payload["sku"])
        if existing:
            raise ProductError("SKU already exists.")
        return ProductRepository.create(payload)
```

**Services:**
- `AuthService`: Authentication, registration, password reset, lockout
- `ProductService`: Product CRUD with validation
- `MovementService`: Stock movement recording
- `EOQService`: EOQ calculations and sensitivity surfaces
- `ForecastService`: ML forecasting orchestration
- `AnomalyService`: Anomaly detection orchestration
- `SettingsService`: User settings management

### 5. ML Pipeline

**Forecasting (`app/ml/forecasting.py`):**
```python
def forecast_ensemble(history, horizon):
    a = forecast_with_prophet(history, horizon)  # Prophet
    b = forecast_with_arima(history, horizon)    # ARIMA
    # Average predictions, lower/upper bounds
    return blended
```

**Anomaly Detection (`app/ml/anomaly.py`):**
```python
def detect_anomalies_isoforest(series, contamination=0.05, z_threshold=3.0):
    if _HAS_SKLEARN and len(values) >= 14:
        # Isolation Forest
        forest = IsolationForest(contamination=contamination)
        ...
    else:
        # Z-score fallback
        ...
```

### 6. Security Layer

**CSP Nonces (`app/security/headers.py`):**
```python
@app.before_request
def _set_nonce():
    g.csp_nonce = secrets.token_urlsafe(24)

@app.context_processor
def _inject_nonce():
    return {"csp_nonce": getattr(g, "csp_nonce", "")}

@app.after_request
def _apply(response):
    nonce = getattr(g, "csp_nonce", "")
    response.headers["Content-Security-Policy"] = (
        f"script-src 'self' 'nonce-{nonce}' ..."
    )
```

**Rate Limiting:**
```python
@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login(): ...

@api_bp.route("/products", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
@write_roles_required
def create_product(): ...
```

### 7. Caching Strategy

**In-Memory TTL Cache:**
```python
class TTLCache:
    def get_or_set(self, key, loader, ttl=60):
        entry = self._store.get(key)
        if entry and entry["expires"] > time.time():
            return entry["value"]
        value = loader()
        self._store[key] = {"value": value, "expires": time.time() + ttl}
        return value
```

**Cache Layers:**
- `global_cache`: 60s TTL (reorder count)
- `dashboard_cache`: Per-user, per-day
- `reports_cache`: 300s TTL
- `api_cache`: 60s TTL
- `landing_cache`: 300s TTL
- AI portfolio: 3600s TTL

### 8. ETL Pipeline

**Incremental ETL (`app/database/etl.py`):**
1. Read high-water mark from `etl_state`
2. Process only new/modified movements
3. Update dimensions (SCD Type 2)
4. Rebuild facts (stock walk clamping)
5. Advance high-water mark

**Stock Walk Clamping:**
```python
# Ensure inventory accuracy by clamping negative values
stock_on_hand = max(0, running_stock)
```

## Data Flow Diagrams

### 1. Product Creation Flow
```
Browser → POST /api/products
  → Flask Route (api.py)
  → @login_required + @write_roles_required
  → @limiter.limit("30 per minute")
  → ProductService.create(payload)
    → validate_payload()
    → ProductRepository.find_by_sku()
    → ProductRepository.create()
      → sp_product_create() [Stored Procedure]
      → PostgreSQL INSERT
  → AuditRepository.record()
  → cache_bust_products()
  → api_response({"id": new_id}, status=201)
```

### 2. Forecast Request Flow
```
Browser → POST /ai/forecast/run
  → Flask Route (ai.py)
  → @login_required
  → ForecastService.run(product_id, model, horizon)
    → ProductRepository.find(product_id)
    → MovementRepository.daily_totals(product_id, days=90)
    → forecast_ensemble(history, horizon)
      → forecast_with_prophet(history, horizon)
      → forecast_with_arima(history, horizon)
      → Average predictions
    → Cache result (1 hour TTL)
  → api_response(forecast_data)
```

### 3. Stock Movement Flow
```
Browser → POST /api/movements
  → Flask Route (api.py)
  → @login_required + @write_roles_required
  → @limiter.limit("60 per minute")
  → MovementService.record(product_id, type, quantity, ...)
    → validate movement type
    → MovementRepository.create()
      → sp_movement_create() [Stored Procedure]
      → trg_validate_movement [TRIGGER]
        → Auto-populate SKU
        → Validate FK
        → Prevent negative stock
      → trg_movement_stock_update [TRIGGER]
        → Update products.current_stock
      → trg_log_movement_create [TRIGGER]
        → Insert into audit_log
  → cache_bust_movements()
  → api_response({"id": movement_id}, status=201)
```

## Database Schema

### Operational Tables
```
users ──────────────┐
suppliers ──────────┤
products ───────────┤
movements ──────────┼──▶ audit_log
purchase_orders ────┤
user_settings ──────┤
password_reset_tokens┘
forecast_cache
anomaly_log
user_sessions
etl_state
```

### Warehouse Tables (SCD Type 2)
```
dim_date ───────────┐
dim_warehouse ──────┤
dim_product ────────┼──▶ fact_movement_daily
dim_supplier ───────┤    fact_inventory_daily
dim_product_scd ────┤    fact_product_daily
dim_supplier_scd ───┤    fact_login_events
dim_warehouse_scd ──┤    fact_session_activity
dim_user ───────────┘    fact_signup_events
                         fact_audit_daily
```

## Performance Characteristics

| Metric | Value | Notes |
|--------|-------|-------|
| DB Connection Pool | 20 max | ThreadedConnectionPool |
| Context Processor Cache | 60s | Global key |
| Dashboard Cache | Per-user/day | Resets daily |
| Reports Cache | 300s | 10x fewer cold hits |
| AI Portfolio Cache | 3600s | Avoids repeated model fitting |
| Gunicorn Workers | 1 | Single process |
| Gunicorn Threads | 2 | Concurrent requests |
| Request Timeout | 120s | Gunicorn timeout |

## Security Boundaries

### Trust Boundaries
1. **Browser → Flask**: HTTPS, CSRF tokens, session cookies
2. **Flask → PostgreSQL**: Parameterized SQL, stored procedures
3. **Flask → External**: Rate limiting, input validation

### Attack Surfaces Mitigated
| Attack | Mitigation |
|--------|------------|
| SQL Injection | 84+ stored procedures with parameterized inputs |
| XSS | CSP nonces, Jinja2 auto-escaping |
| CSRF | Flask-WTF CSRF tokens |
| Brute Force | Rate limiting (10/min login) |
| Account Takeover | Lockout (5 attempts → 15 min) |
| Session Hijacking | Secure, HttpOnly, SameSite cookies |
| Privilege Escalation | RBAC (viewer/admin/manager) |

---

*Generated: September 10, 2026*
