# InventoryLogix — Complete Repository Map

> Generated: 2026-09-11 | Inventory Logistics Optimization Dashboard

---

## 1. Complete Directory Tree

```
Inventory Logistics Optimization Dashboard/
├── run.py                          # Application entry point (Flask + Gunicorn)
├── migrate.py                      # CLI migration helper (create/upgrade/downgrade/history)
├── requirements.txt                # Python dependencies (15 packages)
├── .env.example                    # Environment variable template
├── .env                            # Active environment (gitignored)
├── .gitignore                      # Git ignore rules
├── alembic.ini                     # Alembic migration configuration
├── pytest.ini                      # Pytest configuration (testpaths=tests)
├── render.yaml                     # Render.com deployment Blueprint
├── opencode.json                   # OpenCode agent configuration
├── AGENTS.md                       # Agent guide (dev instructions)
├── PRODUCT.md                      # Product documentation
├── README.md                       # Project README
├── SUPABASE_SETUP.md              # Supabase integration guide
├── generate-report.bat             # Report generation script (Windows)
├── generate-report.ps1             # Report generation script (PowerShell)
├── Report_generation.zip           # Report generation archive
│
├── app/                            # Main application package
│   ├── __init__.py                 # Application factory (create_app)
│   ├── extensions.py               # Flask extension singletons (Login, CSRF, Limiter)
│   ├── models.py                   # UserProxy model (Flask-Login adapter)
│   │
│   ├── config/                     # Configuration layer
│   │   ├── __init__.py             # Exports get_config, Config classes
│   │   └── settings.py             # Environment-based config (Dev/Prod/Testing)
│   │
│   ├── database/                   # Data access layer
│   │   ├── __init__.py             # Exports get_connection, get_cursor, bootstrap_database
│   │   ├── connection.py           # psycopg2 pooling, schema init, ETL orchestration
│   │   ├── schema.sql              # Operational tables + star schema DDL
│   │   ├── procedures.sql          # 84+ stored procedures (sp_*)
│   │   ├── triggers.sql            # 8 triggers (audit, validation, session)
│   │   ├── warehouse.sql           # SCD Type 2 dimensions + fact tables
│   │   ├── etl_procedures.sql      # ETL helper stored procedures
│   │   ├── etl.py                  # ETL pipeline (operational → star schema)
│   │   └── seed.py                 # Demo data seeding (users, products, movements)
│   │
│   ├── repositories/               # Data access layer (SQL via stored procedures)
│   │   ├── __init__.py             # Exports all repositories
│   │   ├── user_repo.py            # User CRUD, sessions, reset tokens
│   │   ├── product_repo.py         # Product CRUD, low stock, categories
│   │   ├── supplier_repo.py        # Supplier CRUD
│   │   ├── movement_repo.py        # Movement recording, daily totals
│   │   ├── po_repo.py              # Purchase order CRUD, status updates
│   │   ├── audit_repo.py           # Audit log recording
│   │   ├── forecast_repo.py        # Forecast/anomaly cache persistence
│   │   ├── settings_repo.py        # User settings persistence
│   │   └── warehouse_repo.py       # Star schema warehouse analytics
│   │
│   ├── services/                   # Business logic layer
│   │   ├── __init__.py             # Exports all services
│   │   ├── auth_service.py         # Registration, auth, password reset, lockout
│   │   ├── product_service.py      # Product validation, CRUD orchestration
│   │   ├── supplier_service.py     # Supplier validation, CRUD orchestration
│   │   ├── movement_service.py     # Movement recording with stock validation
│   │   ├── eoq_service.py          # EOQ calculations, cost curves, sensitivity
│   │   ├── forecast_service.py     # Forecast orchestration (ML → API)
│   │   ├── anomaly_service.py      # Anomaly detection orchestration
│   │   ├── settings_service.py     # User settings with defaults & validation
│   │   ├── mailer.py               # Email delivery (SMTP + SendGrid)
│   │   └── dataset_service.py      # DataCo dataset loader + synthetic fallback
│   │
│   ├── security/                   # Security utilities
│   │   ├── __init__.py             # Exports validators, roles, headers
│   │   ├── validators.py           # Input validation (SKU, email, password, etc.)
│   │   ├── roles.py                # RBAC decorators (write_roles_required)
│   │   └── headers.py              # HTTP security headers (CSP, HSTS, etc.)
│   │
│   ├── ml/                         # Machine learning models
│   │   ├── __init__.py             # Exports forecast/anomaly functions
│   │   ├── forecasting.py          # Prophet, ARIMA, ensemble, moving-average fallback
│   │   └── anomaly.py              # Isolation Forest + SPC z-score analysis
│   │
│   ├── utils/                      # Shared utilities
│   │   ├── __init__.py             # Exports helpers, cache instances
│   │   ├── helpers.py              # API responses, EOQ calc, formatting, stock status
│   │   └── cache.py                # TTLCache + named caches (products, dashboard, etc.)
│   │
│   ├── routes/                     # HTTP route blueprints
│   │   ├── __init__.py             # Exports auth_bp, ui_bp, api_bp, ai_bp
│   │   ├── auth.py                 # Auth routes: login, register, forgot/reset password
│   │   ├── ui.py                   # Main UI: dashboard, inventory, suppliers, reports, EOQ
│   │   ├── api.py                  # REST API: health, products, suppliers, movements, EOQ
│   │   └── ai.py                   # AI routes: forecast, anomaly, EOQ sensitivity
│   │
│   ├── templates/                  # Jinja2 HTML templates
│   │   ├── base.html               # Base layout (CDN scripts, theme, nav)
│   │   ├── landing.html            # Public landing page
│   │   ├── dashboard.html          # Main dashboard (KPIs, charts, ABC)
│   │   ├── inventory.html          # Product inventory list + filters
│   │   ├── product_form.html       # Create/edit product form
│   │   ├── product_detail.html     # Product detail + movement history
│   │   ├── movement_form.html      # Record stock movement form
│   │   ├── suppliers.html          # Supplier management page
│   │   ├── purchase_orders.html    # Purchase order kanban board
│   │   ├── reorder_alerts.html     # Low stock alerts + auto-reorder
│   │   ├── warehouses.html         # Warehouse analytics (star schema)
│   │   ├── reports.html            # Filtered analytics reports
│   │   ├── eoq_calculator.html     # EOQ calculator page
│   │   ├── monitoring.html         # ETL monitoring + DB stats
│   │   ├── settings.html           # User settings page
│   │   ├── help.html               # Help page
│   │   ├── contact.html            # Contact page
│   │   ├── auth/
│   │   │   ├── login.html
│   │   │   ├── register.html
│   │   │   ├── forgot_password.html
│   │   │   └── reset_password.html
│   │   ├── ai/
│   │   │   ├── forecast.html       # AI forecast page (Plotly charts)
│   │   │   └── anomaly.html        # AI anomaly detection page
│   │   └── errors/
│   │       ├── 400.html, 401.html, 403.html, 404.html
│   │       ├── 422.html, 429.html, 500.html
│   │
│   └── static/                     # Static assets
│       ├── css/
│       │   ├── style.css           # Main application styles
│       │   ├── landing.css         # Landing page styles
│       │   └── ai-features.css     # AI feature styles
│       ├── js/
│       │   ├── main.js             # Main application JS (theme, nav)
│       │   ├── dashboard-3d.js     # Three.js dashboard background
│       │   ├── landing.js          # Landing page interactions
│       │   ├── landing-bg.js       # Three.js landing background
│       │   ├── auth-bg.js          # Three.js auth background
│       │   ├── app-bg.js           # Three.js app background
│       │   ├── bg-3d.js            # Three.js background utilities
│       │   ├── saas-animations.js  # GSAP scroll animations
│       │   ├── ai-features.js      # AI forecast/anomaly UI logic
│       │   ├── eoq.js              # EOQ calculator client logic
│       │   └── movement.js         # Movement form client logic
│       └── img/
│           ├── favicon.svg         # App favicon
│           └── logo.svg            # App logo
│
├── tests/                          # Test suite
│   ├── __init__.py
│   ├── conftest.py                 # Fixtures: app, client, auth_client
│   ├── test_auth.py                # Authentication flow tests (4 tests)
│   ├── test_api.py                 # REST API tests (4 tests)
│   ├── test_security.py            # Validators, RBAC, headers tests (18+ tests)
│   ├── test_services.py            # Service layer tests
│   ├── test_roles.py               # Role-based access tests
│   ├── test_cache.py               # Cache layer tests
│   ├── test_etl.py                 # ETL pipeline tests
│   └── test_ml.py                  # ML model tests (Prophet/ARIMA fallback)
│
├── migrations/                     # Alembic migrations
│   ├── env.py                      # Alembic environment (DATABASE_URL)
│   └── versions/
│       ├── 001_initial.py          # Initial schema migration
│       ├── 002_critical_fixes.py   # Critical fixes migration
│       └── 003_enable_rls.py       # Row-Level Security migration
│
├── docs/                           # Documentation
│   ├── Testing.md                  # Testing guide
│   └── project-analysis/           # Generated analysis documents
│       ├── BUSINESS_GUIDE.md
│       ├── EVIDENCE_REGISTER.md
│       ├── EXECUTIVE_SUMMARY.md
│       ├── INTERVIEW_QA.md
│       ├── LITERATURE_REVIEW.md
│       ├── PROJECT_ANALYSIS.md
│       └── TECHNICAL_ARCHITECTURE.md
│
├── report_output/                  # Generated reports directory
└── myvenv/                         # Python virtual environment (gitignored)
```

---

## 2. Module Inventory

| Module | Path | Responsibility | Key Classes/Functions |
|--------|------|---------------|----------------------|
| **App Factory** | `app/__init__.py` | Flask app creation, extension init, blueprint registration, error handlers, context processor | `create_app()` |
| **Config** | `app/config/settings.py` | Environment-based configuration (Dev/Prod/Testing), DB params, SMTP, feature flags | `Config`, `DevelopmentConfig`, `ProductionConfig`, `TestingConfig` |
| **Extensions** | `app/extensions.py` | Flask extension singletons (Login, CSRF, Limiter) | `login_manager`, `csrf`, `limiter` |
| **Models** | `app/models.py` | Flask-Login user adapter for psycopg2 rows | `UserProxy(UserMixin)` |
| **Database Connection** | `app/database/connection.py` | Threaded connection pooling, schema bootstrap, ETL orchestration | `get_connection()`, `get_cursor()`, `bootstrap_database()`, `init_schema()` |
| **Database Schema** | `app/database/schema.sql` | DDL for 12+ operational tables + star schema (dim/fact) | SQL: `users`, `products`, `movements`, `suppliers`, `purchase_orders`, `dim_*`, `fact_*` |
| **Stored Procedures** | `app/database/procedures.sql` | 84+ `sp_*` functions for all CRUD operations | `sp_product_list`, `sp_movement_record`, `sp_user_create`, etc. |
| **Triggers** | `app/database/triggers.sql` | 8 triggers for audit logging, validation, session tracking | `trg_validate_movement`, `trg_audit_*`, `trg_session_*` |
| **Warehouse** | `app/database/warehouse.sql` | SCD Type 2 dimensions + fact tables for analytics | `dim_product_scd`, `dim_supplier_scd`, `fact_movement_daily`, `fact_inventory_daily` |
| **ETL Pipeline** | `app/database/etl.py` | Builds star-schema warehouse from operational tables (incremental) | `run_etl()` |
| **Seed Data** | `app/database/seed.py` | Populates DB with demo data (118 products, 36 suppliers, movements) | `run_seed()` |
| **Repositories** | `app/repositories/` | Data access layer via stored procedures (8 modules) | `UserRepository`, `ProductRepository`, `SupplierRepository`, `MovementRepository`, `PurchaseOrderRepository`, `AuditRepository`, `ForecastRepository`, `SettingsRepository`, `WarehouseRepository` |
| **Services** | `app/services/` | Business logic and orchestration (10 modules) | `AuthService`, `ProductService`, `SupplierService`, `MovementService`, `EOQService`, `ForecastService`, `AnomalyService`, `SettingsService`, `Mailer`, `DatasetService` |
| **Security** | `app/security/` | Input validation, RBAC, HTTP security headers | `validators.py`, `roles.py`, `headers.py` |
| **ML** | `app/ml/` | Forecasting (Prophet/ARIMA/ensemble) and anomaly detection (Isolation Forest/z-score) | `forecast_with_prophet()`, `forecast_with_arima()`, `forecast_ensemble()`, `detect_anomalies_isoforest()`, `spc_zscore_analysis()` |
| **Utils** | `app/utils/` | API helpers, EOQ calculations, money formatting, TTL cache | `api_response()`, `api_error()`, `calculate_eoq()`, `TTLCache`, `format_money_display()` |
| **Routes** | `app/routes/` | HTTP blueprints (4 blueprints, 50+ endpoints) | `auth_bp`, `ui_bp`, `api_bp`, `ai_bp` |
| **Dataset Service** | `app/services/dataset_service.py` | DataCo SMART SUPPLY CHAIN dataset loader + synthetic fallback | `get_products()`, `get_suppliers()` |

---

## 3. Dependency Graph

### Module Dependency Flow

```
run.py
  └── app/__init__.py (create_app)
        ├── app/config/settings.py (Config classes)
        ├── app/database/connection.py (pooling, bootstrap)
        │     ├── app/database/seed.py (demo data)
        │     │     └── app/services/dataset_service.py (DataCo loader)
        │     └── app/database/etl.py (star schema build)
        ├── app/extensions.py (Login, CSRF, Limiter)
        ├── app/models.py (UserProxy)
        ├── app/security/ (headers, validators, roles)
        ├── app/routes/ (4 blueprints)
        │     ├── routes/auth.py
        │     │     ├── app/services/auth_service.py
        │     │     │     ├── app/repositories/user_repo.py
        │     │     │     ├── app/repositories/audit_repo.py
        │     │     │     ├── app/security/validators.py
        │     │     │     └── app/services/mailer.py
        │     │     └── app/repositories/user_repo.py
        │     ├── routes/ui.py
        │     │     ├── app/repositories/* (all repos)
        │     │     ├── app/services/* (all services)
        │     │     └── app/utils/cache.py
        │     ├── routes/api.py
        │     │     ├── app/repositories/* (most repos)
        │     │     ├── app/services/* (most services)
        │     │     └── app/utils/ (helpers, cache)
        │     └── routes/ai.py
        │           ├── app/services/forecast_service.py
        │           │     ├── app/ml/forecasting.py
        │           │     └── app/repositories/forecast_repo.py
        │           └── app/services/anomaly_service.py
        │                 ├── app/ml/anomaly.py
        │                 └── app/repositories/forecast_repo.py
        └── app/utils/cache.py (named cache instances)
```

### Repository → Stored Procedure Mapping

| Repository | Stored Procedures Used |
|-----------|----------------------|
| `UserRepository` | `sp_user_create`, `sp_user_find_by_username`, `sp_user_find_by_email`, `sp_user_find_by_id`, `sp_user_record_login`, `sp_user_list_all`, `sp_user_set_active`, `sp_user_change_role`, `sp_user_set_password`, `sp_reset_token_create`, `sp_reset_token_find`, `sp_reset_token_consume`, `sp_reset_token_purge`, `sp_session_create`, `sp_session_end`, `sp_session_update_activity`, `sp_session_get_active`, `sp_session_cleanup_stale` |
| `ProductRepository` | `sp_product_list`, `sp_product_find`, `sp_product_find_by_sku`, `sp_product_create`, `sp_product_update`, `sp_product_delete`, `sp_product_set_stock`, `sp_product_set_on_order`, `sp_product_categories`, `sp_product_warehouses`, `sp_product_low_stock` |
| `SupplierRepository` | `sp_supplier_list_all`, `sp_supplier_find`, `sp_supplier_create`, `sp_supplier_update`, `sp_supplier_delete` |
| `MovementRepository` | `sp_movement_recent_for_product`, `sp_movement_daily_totals`, `sp_movement_daily_for_product`, `sp_movement_units_today`, `sp_movement_record` |
| `PurchaseOrderRepository` | `sp_po_list_by_status`, `sp_po_counts_by_status`, `sp_po_create`, `sp_po_update_status` |
| `AuditRepository` | `sp_audit_record`, `sp_audit_recent`, `sp_audit_count_last_hours` |
| `SettingsRepository` | `sp_settings_all`, `sp_settings_set_many` |

---

## 4. Entry Points

| Entry Point | Path | Purpose |
|------------|------|---------|
| **`python run.py`** | `run.py` | Main entry point. Creates Flask app via `create_app()`. Debug mode: Werkzeug server with auto-reload. Production: Gunicorn (1 worker, 2 threads). |
| **`gunicorn run:app`** | `run.py` | Production WSGI entry (Render deploy). Same `app` object. |
| **`python migrate.py <cmd>`** | `migrate.py` | CLI: `create`, `upgrade`, `downgrade`, `current`, `history`. Wraps Alembic. |
| **`flask init-db`** | `app/__init__.py` | CLI: Apply schema + seed + ETL in one shot. |
| **`flask seed-db`** | `app/__init__.py` | CLI: Seed demo data only. |
| **`flask etl-db`** | `app/__init__.py` | CLI: Run ETL pipeline only. |
| **`python -m pytest`** | `tests/` | Run test suite (via `pytest.ini`). |

### First-Run Bootstrap

On `python run.py` startup, `bootstrap_database()` runs idempotently:
1. `init_schema()` — applies `schema.sql`, `procedures.sql`, `warehouse.sql`, `etl_procedures.sql`, `triggers.sql`
2. `seed_database()` — inserts demo users, suppliers, products, movements, POs
3. `etl_database()` — builds star-schema warehouse (if `RUN_ETL_ON_STARTUP=true`)

---

## 5. Data Flow Through the Codebase

### Request Lifecycle

```
HTTP Request
  → Flask (run.py / Gunicorn)
    → app/__init__.py (create_app context)
      → security/headers.py (CSP nonce, security headers)
        → routes/ (auth_bp, ui_bp, api_bp, ai_bp)
          → @login_required check (extensions.py → login_manager)
          → @limiter limit check (extensions.py → Flask-Limiter)
          → @write_roles_required check (security/roles.py)
          → services/ (business logic + validation)
            → repositories/ (SQL via stored procedures)
              → database/connection.py (get_cursor)
                → PostgreSQL (psycopg2 pool → stored procedures)
          → utils/cache.py (TTL cache read/write)
          → Response (template render or JSON)
```

### Movement Recording Flow

```
User submits movement form / API POST
  → routes/ui.py or routes/api.py
    → MovementService.record()
      → ProductRepository.find_for_update() (SELECT FOR UPDATE lock)
      → Validate: type allowed, quantity > 0, no negative stock
      → MovementRepository.record() (sp_movement_record)
      → ProductRepository.set_stock() (sp_product_set_stock)
      → AuditRepository.record() (sp_audit_record)
    → cache_bust_movements() (invalidate products, dashboard, reports caches)
  → Redirect / JSON response
```

### Forecast Pipeline Flow

```
POST /ai/forecast/run
  → routes/ai.py → ForecastService.run()
    → ProductRepository.find() (get product details)
    → MovementRepository.daily_for_product() (get 180-day history)
    → ml/forecasting.py → forecast_with_prophet() / forecast_with_arima() / forecast_ensemble()
      → Optional: Prophet model (if installed)
      → Optional: ARIMA(1,1,1) (if installed)
      → Fallback: Moving average forecast
    → ForecastRepository.save() (cache result in forecast_cache table)
  → JSON response with predictions, confidence intervals, accuracy
```

### ETL Pipeline Flow

```
bootstrap_database() / flask etl-db / /monitoring "Run ETL"
  → app/database/etl.py → run_etl()
    → Read etl_state high-water mark
    → Rebuild dim_date, dim_warehouse, dim_product, dim_supplier (SCD Type 2)
    → Process movements since last watermark → fact_movement_daily
    → Snapshot current inventory → fact_inventory_daily
    → Update etl_state watermark
    → All in one transaction (atomic)
```

---

## 6. Configuration Management

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | `change-me-in-production` | Flask session signing |
| `DATABASE_URL` | — | PostgreSQL connection string (overrides DB_* fields) |
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | `inventory_db` | Database name |
| `DB_USER` | `postgres` | Database user |
| `DB_PASSWORD` | `""` | Database password |
| `DB_SSLMODE` | `""` | SSL mode for PostgreSQL |
| `FLASK_ENV` | `development` | Environment (development/production/testing) |
| `RENDER_INSTANCE_ID` | — | Set by Render.com (auto-detects production) |
| `RUN_ETL_ON_STARTUP` | `true` | Run ETL on app start |
| `SMTP_HOST` | `""` | SMTP server (empty = dev fallback) |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USERNAME` | `""` | SMTP login |
| `SMTP_PASSWORD` | `""` | SMTP password |
| `MAIL_FROM` | `no-reply@inventorylogix.local` | Sender email |
| `MAIL_USE_TLS` | `true` | Enable TLS |
| `SENDGRID_API_KEY` | `""` | SendGrid API (alternative to SMTP) |
| `PASSWORD_RESET_TTL_MINUTES` | `5` | Reset token lifetime |
| `RATELIMIT_STORAGE_URI` | `memory://` | Rate limit storage backend |
| `AI_FORECAST_ENABLED` | `true` | Feature flag |
| `ANOMALY_DETECTION_ENABLED` | `true` | Feature flag |
| `SECURITY_HEADERS_ENABLED` | `true` | Feature flag |
| `TEST_DB_PASSWORD` | `""` | Local test DB password |

### Configuration Classes

| Class | Debug | Session Secure | CSRF | Purpose |
|-------|-------|---------------|------|---------|
| `DevelopmentConfig` | `True` | `False` | `True` | Local development |
| `ProductionConfig` | `False` | `True` | `True` | Render deployment |
| `TestingConfig` | `False` | N/A | `False` | pytest suite |

### Deployment (render.yaml)

- **Service type**: web (Python)
- **Plan**: free
- **Region**: Oregon
- **Build**: `pip install -r requirements.txt`
- **Start**: `gunicorn run:app --workers 1 --threads 2 --timeout 120`
- **Health check**: `/api/health`
- **Database**: Free PostgreSQL (auto-wired via `DATABASE_URL`)

---

## 7. Test Coverage Overview

| Test File | Path | Focus | Key Tests |
|-----------|------|-------|-----------|
| `conftest.py` | `tests/conftest.py` | Fixtures | `app` (session-scoped), `client`, `runner`, `auth_client` (logged-in) |
| `test_auth.py` | `tests/test_auth.py` | Auth flows | Login page renders, invalid credentials, register validation |
| `test_api.py` | `tests/test_api.py` | REST API | Health endpoint, auth required for products, EOQ validation |
| `test_security.py` | `tests/test_security.py` | Validators | SKU, email, password, username, positive number, string length, RBAC, headers |
| `test_services.py` | `tests/test_services.py` | Service layer | Business logic validation |
| `test_roles.py` | `tests/test_roles.py` | RBAC | Role-based access control |
| `test_cache.py` | `tests/test_cache.py` | Cache | TTLCache get/set/invalidate |
| `test_etl.py` | `tests/test_etl.py` | ETL | Star-schema build, incremental runs |
| `test_ml.py` | `tests/test_ml.py` | ML | Forecast fallback, anomaly detection |

### Test Configuration

- `pytest.ini`: `testpaths = tests`
- Tests run against local PostgreSQL (never production)
- `WTF_CSRF_ENABLED = False` for test client
- Demo credentials: `admin/Admin@123`, `manager/Manager@123`, `viewer/Viewer@123`

---

## 8. Documentation Inventory

| Document | Path | Purpose |
|----------|------|---------|
| `README.md` | Root | Project overview, setup instructions |
| `AGENTS.md` | Root | Agent development guide, architecture notes |
| `PRODUCT.md` | Root | Product documentation |
| `SUPABASE_SETUP.md` | Root | Supabase integration guide |
| `Testing.md` | `docs/Testing.md` | Testing guide |
| `REPOSITORY_MAP.md` | `docs/project-analysis/` | This document |
| `BUSINESS_GUIDE.md` | `docs/project-analysis/` | Business context |
| `EVIDENCE_REGISTER.md` | `docs/project-analysis/` | Evidence tracking |
| `EXECUTIVE_SUMMARY.md` | `docs/project-analysis/` | Executive summary |
| `INTERVIEW_QA.md` | `docs/project-analysis/` | Interview Q&A |
| `LITERATURE_REVIEW.md` | `docs/project-analysis/` | Literature review |
| `PROJECT_ANALYSIS.md` | `docs/project-analysis/` | Full project analysis |
| `TECHNICAL_ARCHITECTURE.md` | `docs/project-analysis/` | Technical architecture |

---

## 9. Static Assets Inventory

### CSS (3 files)

| File | Path | Purpose |
|------|------|---------|
| `style.css` | `app/static/css/` | Main application styles (dark mode, dashboard, forms) |
| `landing.css` | `app/static/css/` | Landing page styles |
| `ai-features.css` | `app/static/css/` | AI forecast/anomaly page styles |

### JavaScript (11 files)

| File | Path | Purpose |
|------|------|---------|
| `main.js` | `app/static/js/` | Theme toggle, nav, toast notifications |
| `dashboard-3d.js` | `app/static/js/` | Three.js dashboard background |
| `landing.js` | `app/static/js/` | Landing page interactions |
| `landing-bg.js` | `app/static/js/` | Three.js landing background |
| `auth-bg.js` | `app/static/js/` | Three.js auth page background |
| `app-bg.js` | `app/static/js/` | Three.js app background |
| `bg-3d.js` | `app/static/js/` | Three.js background utilities |
| `saas-animations.js` | `app/static/js/` | GSAP scroll-triggered animations |
| `ai-features.js` | `app/static/js/` | AI forecast/anomaly Plotly charts |
| `eoq.js` | `app/static/js/` | EOQ calculator client logic |
| `movement.js` | `app/static/js/` | Movement form client logic |

### Images (2 files)

| File | Path | Purpose |
|------|------|---------|
| `favicon.svg` | `app/static/img/` | Browser tab icon |
| `logo.svg` | `app/static/img/` | App logo (also embedded in password reset emails) |

### CDN Dependencies (loaded in base.html)

- **Plotly.js** — Charts (dashboard, reports, forecast, anomaly, EOQ)
- **Three.js** — 3D background animations
- **GSAP + ScrollTrigger** — Scroll animations
- **Chart.js** — Additional charting
- **Inter Font** — Typography

---

## 10. Template Inventory

| Template | Path | Route | Purpose |
|----------|------|-------|---------|
| `base.html` | `templates/` | — | Base layout (CDN, nav, theme, flash messages) |
| `landing.html` | `templates/` | `GET /` (unauth) | Public landing page with stats |
| `dashboard.html` | `templates/` | `GET /` (auth) | Main dashboard (KPIs, charts, ABC, suppliers) |
| `inventory.html` | `templates/` | `GET /inventory` | Product list with search/filter/pagination |
| `product_form.html` | `templates/` | `GET/POST /products/new`, `/products/<id>/edit` | Create/edit product form |
| `product_detail.html` | `templates/` | `GET /products/<id>` | Product detail + recent movements |
| `movement_form.html` | `templates/` | `GET/POST /movements/new` | Record stock movement form |
| `suppliers.html` | `templates/` | `GET/POST /suppliers` | Supplier management page |
| `purchase_orders.html` | `templates/` | `GET/POST /purchase-orders` | Purchase order kanban board |
| `reorder_alerts.html` | `templates/` | `GET /reorder-alerts` | Low stock alerts + auto-reorder |
| `warehouses.html` | `templates/` | `GET /warehouses` | Warehouse analytics (star schema) |
| `reports.html` | `templates/` | `GET/POST /reports` | Filtered analytics reports |
| `eoq_calculator.html` | `templates/` | `GET /eoq-calculator` | EOQ calculator page |
| `monitoring.html` | `templates/` | `GET /monitoring` | ETL monitoring + DB stats |
| `settings.html` | `templates/` | `GET /settings` | User preferences page |
| `help.html` | `templates/` | `GET /help` | Help documentation page |
| `contact.html` | `templates/` | `GET /contact` | Contact page |
| `auth/login.html` | `templates/auth/` | `GET/POST /auth/login` | Login form |
| `auth/register.html` | `templates/auth/` | `GET/POST /auth/register` | Registration form |
| `auth/forgot_password.html` | `templates/auth/` | `GET/POST /auth/forgot-password` | Password reset request |
| `auth/reset_password.html` | `templates/auth/` | `GET/POST /auth/reset-password/<token>` | Password reset form |
| `ai/forecast.html` | `templates/ai/` | `GET /ai/forecast` | AI forecast page (Plotly) |
| `ai/anomaly.html` | `templates/ai/` | `GET /ai/anomaly` | AI anomaly detection page |
| `errors/400.html` | `templates/errors/` | 400 handler | Bad request |
| `errors/401.html` | `templates/errors/` | 401 handler | Unauthorized |
| `errors/403.html` | `templates/errors/` | 403 handler | Forbidden |
| `errors/404.html` | `templates/errors/` | 404 handler | Not found |
| `errors/422.html` | `templates/errors/` | 422 handler | Unprocessable |
| `errors/429.html` | `templates/errors/` | 429 handler | Rate limited |
| `errors/500.html` | `templates/errors/` | 500 handler | Server error |

---

## Technology Inventory

### Backend

| Technology | Version | Purpose |
|-----------|---------|---------|
| Python | 3.10+ | Runtime |
| Flask | ≥3.0 | Web framework (application factory pattern) |
| psycopg2-binary | ≥2.9 | PostgreSQL adapter (RealDictCursor) |
| Flask-Login | ≥0.6 | Session management |
| Flask-WTF | ≥1.2 | CSRF protection |
| Flask-Limiter | ≥3.5 | Rate limiting |
| Flask-Migrate | ≥4.0 | Alembic integration |
| Werkzeug | (Flask) | Password hashing, WSGI |
| python-dotenv | ≥1.0 | Environment variable loading |
| email-validator | ≥2.0 | Email validation |

### Data & Analytics

| Technology | Version | Purpose |
|-----------|---------|---------|
| PostgreSQL | 14+ | Primary database |
| Alembic | (via Flask-Migrate) | Schema migrations |

### Machine Learning

| Technology | Version | Purpose |
|-----------|---------|---------|
| Prophet | ≥1.1 | Time-series forecasting (optional) |
| statsmodels | ≥0.14 | ARIMA forecasting (optional) |
| scikit-learn | ≥1.3 | Isolation Forest anomaly detection (optional) |
| plotly | ≥5.0 | Interactive charting (frontend) |

### External Services

| Service | Purpose |
|---------|---------|
| SendGrid API | Password reset emails (HTTPS, Render-compatible) |
| SMTP (optional) | Alternative email delivery |

### Deployment

| Tool | Purpose |
|------|---------|
| Gunicorn | Production WSGI server (1 worker, 2 threads) |
| Render.com | Cloud hosting (free tier) |
| Supabase | Alternative PostgreSQL hosting |

### Frontend Libraries (CDN)

| Library | Purpose |
|---------|---------|
| Plotly.js | Interactive charts |
| Three.js | 3D background animations |
| GSAP + ScrollTrigger | Scroll animations |
| Chart.js | Additional charts |
| Inter Font | Typography |

---

## Database Schema Summary

### Operational Tables (schema.sql)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `users` | User accounts | id, username, email, password_hash, role, is_active |
| `suppliers` | Supplier directory | id, name, location, lead_days, reliability |
| `products` | Product catalogue | id, sku, name, category, warehouse, current_stock, reorder_point, unit_price, demand_rate, ordering_cost, holding_cost |
| `movements` | Stock movements | id, product_id, sku, type (IN/OUT/ADJUSTMENT/RETURN), quantity |
| `purchase_orders` | PO tracking | id, po_number, supplier_id, product_id, quantity, status (draft/approved/in_transit/received/cancelled) |
| `user_settings` | Per-user preferences | user_id, key, value |
| `password_reset_tokens` | Password reset | user_id, token_hash, expires_at, used |
| `audit_log` | Audit trail | user_id, action, target_type, target_id, detail (JSONB) |
| `forecast_cache` | ML results cache | product_id, model, horizon, payload (JSONB) |
| `anomaly_log` | Anomaly detections | product_id, anomaly_type, z_score, confidence |
| `user_sessions` | Session tracking | user_id, session_token, ip_address, is_active |
| `etl_state` | ETL watermark | state_key, value |

### Warehouse Tables (warehouse.sql)

| Table | Purpose |
|-------|---------|
| `dim_date` | Date dimension |
| `dim_warehouse` | Warehouse dimension |
| `dim_product` | Product dimension |
| `dim_supplier` | Supplier dimension |
| `dim_product_scd` | SCD Type 2 product history |
| `dim_supplier_scd` | SCD Type 2 supplier history |
| `dim_warehouse_scd` | SCD Type 2 warehouse history |
| `dim_user` | User dimension (SCD Type 2) |
| `fact_movement_daily` | Daily movement aggregates |
| `fact_inventory_daily` | Daily inventory snapshots |

### Row-Level Security

All tables have RLS enabled with zero policies (deny-by-default for Supabase auto-API). Flask app connects as table owner (`postgres`) which bypasses RLS.

---

## Route Summary

### Auth Blueprint (`/auth`)

| Method | Endpoint | Handler | Rate Limit |
|--------|----------|---------|------------|
| GET/POST | `/auth/login` | `auth.login` | 10/min |
| GET/POST | `/auth/register` | `auth.register` | 5/min |
| GET/POST | `/auth/forgot-password` | `auth.forgot_password` | 5/hr |
| GET/POST | `/auth/reset-password/<token>` | `auth.reset_password` | — |
| GET | `/auth/logout` | `auth.logout` | — |

### UI Blueprint (`/`)

| Method | Endpoint | Handler |
|--------|----------|---------|
| GET | `/` | `ui.dashboard` |
| GET | `/inventory` | `ui.inventory` |
| GET | `/inventory/export` | `ui.inventory_export` |
| GET/POST | `/products/new` | `ui.product_form` |
| GET/POST | `/products/<id>/edit` | `ui.product_form` |
| POST | `/products/<id>/delete` | `ui.delete_product` |
| GET | `/products/<id>` | `ui.product_detail` |
| GET | `/reorder-alerts` | `ui.reorder_alerts` |
| POST | `/reorder-alerts/auto-draft` | `ui.auto_draft_pos` |
| POST | `/reorder-alerts/<id>/mark-ordered` | `ui.mark_ordered` |
| GET/POST | `/movements/new` | `ui.movement_form` |
| GET/POST | `/suppliers` | `ui.suppliers` |
| POST | `/suppliers/<id>/delete` | `ui.delete_supplier` |
| GET/POST | `/purchase-orders` | `ui.purchase_orders` |
| POST | `/purchase-orders/<id>/status` | `ui.update_po_status` |
| GET | `/warehouses` | `ui.warehouses` |
| GET/POST | `/reports` | `ui.reports` |
| GET | `/eoq-calculator` | `ui.eoq_calculator` |
| GET | `/monitoring` | `ui.monitoring` |
| GET | `/settings` | `ui.settings` |
| GET | `/help` | `ui.help` |
| GET | `/contact` | `ui.contact` |

### API Blueprint (`/api`)

| Method | Endpoint | Handler | Rate Limit |
|--------|----------|---------|------------|
| GET | `/api/health` | `api.health` | — |
| GET | `/api/settings` | `api.get_settings` | — |
| PUT | `/api/settings` | `api.update_settings` | — |
| GET | `/api/dashboard/live` | `api.dashboard_live` | — |
| GET | `/api/products` | `api.list_products` | 120/min |
| GET | `/api/products/<id>` | `api.get_product` | — |
| POST | `/api/products` | `api.create_product` | 30/min |
| PUT | `/api/products/<id>` | `api.update_product` | 30/min |
| DELETE | `/api/products/<id>` | `api.delete_product` | 30/min |
| GET | `/api/suppliers` | `api.list_suppliers` | — |
| GET | `/api/suppliers/<id>` | `api.get_supplier` | — |
| POST | `/api/suppliers` | `api.create_supplier` | 30/min |
| POST | `/api/movements` | `api.create_movement` | 60/min |
| GET | `/api/movements/recent` | `api.recent_movements` | — |
| POST | `/api/eoq/calculate` | `api.calculate_eoq` | — |

### AI Blueprint (`/ai`)

| Method | Endpoint | Handler | Rate Limit |
|--------|----------|---------|------------|
| GET | `/ai/forecast` | `ai.forecast_page` | — |
| POST | `/ai/forecast/run` | `ai.forecast_run` | 30/min |
| GET | `/ai/forecast/portfolio` | `ai.forecast_portfolio` | — |
| GET | `/ai/anomaly` | `ai.anomaly_page` | — |
| POST | `/ai/anomaly/run` | `ai.anomaly_run` | 30/min |
| GET | `/ai/anomaly/portfolio` | `ai.anomaly_portfolio` | — |
| GET | `/ai/eoq/sensitivity` | `ai.eoq_sensitivity` | — |

---

## Unknowns

| Item | Status | Notes |
|------|--------|-------|
| DataCo dataset CSV | Gitignored | `datasets/DataCoSupplyChainDataset.csv` not in repo; synthetic fallback used |
| NVIDIA API key | Mentioned in AGENTS.md | Referenced for OpenCode agents; no usage in Python code |
| OAuth providers | Schema ready | `oauth_provider`/`oauth_id` columns exist; no OAuth routes implemented |
| WebSocket support | Not present | Dashboard uses polling (`/api/dashboard/live`) |
| Celery/task queue | Not present | ETL runs in-thread (non-blocking) |

---

## Evidence References

- **E1 (Direct observation)**: All file contents read directly from filesystem
- **E2 (Structural)**: Directory listings, glob results, import statements
- **E3 (Inferred)**: Module dependencies traced via imports, route registrations
- **E4 (Documentation)**: AGENTS.md, README.md, render.yaml, .env.example

---

*End of Repository Map*
