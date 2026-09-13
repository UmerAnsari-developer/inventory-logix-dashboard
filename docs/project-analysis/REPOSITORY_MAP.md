# InventoryLogix — Complete Repository Map

> Generated: 2026-09-13 | Inventory Logistics Optimization Dashboard

---

## 1. Complete Directory Tree

```
Inventory Logistics Optimization Dashboard/
├── run.py                          # Application entry point (Flask + Gunicorn)
├── migrate.py                      # CLI migration helper (create/upgrade/downgrade/history)
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment variable template
├── .env                            # Active environment (gitignored)
├── .gitignore                      # Git ignore rules
├── alembic.ini                     # Alembic migration configuration (gitignored)
├── pytest.ini                      # Pytest configuration (testpaths=tests)
├── render.yaml                     # Render.com deployment Blueprint
├── opencode.json                   # OpenCode agent configuration
├── AGENTS.md                       # Agent guide (dev instructions)
├── README.md                       # Project README
├── SUPABASE_SETUP.md              # Supabase integration guide
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
│   │   ├── seed.py                 # Demo data seeding (users, products, movements)
│   │   └── monitoring/             # Forecast model monitoring
│   │       ├── metrics.py          # MAE/MAPE/RMSE evaluation
│   │       ├── degradation.py      # Degradation detection + health status
│   │       └── alerts.py           # Model monitoring alerts
│   │
│   ├── repositories/               # Data access layer (SQL via stored procedures)
│   │   ├── __init__.py             # Exports all repositories
│   │   ├── product_repo.py         # Product CRUD, low stock, categories
│   │   ├── movement_repo.py        # Movement recording, daily totals
│   │   ├── supplier_repo.py        # Supplier CRUD
│   │   ├── po_repo.py              # Purchase order CRUD, status updates
│   │   ├── user_repo.py            # User CRUD, sessions, reset tokens
│   │   ├── settings_repo.py        # User settings persistence
│   │   ├── notification_repo.py    # Notification CRUD
│   │   ├── forecast_repo.py        # Forecast/anomaly cache persistence
│   │   ├── monitoring_repo.py      # Predictions + metrics + alerts persistence
│   │   └── audit_repo.py           # Audit log recording
│   │
│   ├── services/                   # Business logic layer
│   │   ├── __init__.py             # Exports all services
│   │   ├── auth_service.py         # Registration, auth, password reset, lockout
│   │   ├── product_service.py      # Product validation, CRUD orchestration
│   │   ├── movement_service.py     # Movement recording with stock validation
│   │   ├── supplier_service.py     # Supplier validation, CRUD orchestration
│   │   ├── eoq_service.py          # EOQ calculations, cost curves, sensitivity
│   │   ├── forecast_service.py     # Forecast orchestration (ML → API)
│   │   ├── anomaly_service.py      # Anomaly detection orchestration
│   │   ├── monitoring_service.py   # Model monitoring aggregation
│   │   ├── notification_service.py # Alert checks + bulk inserts
│   │   ├── settings_service.py     # User settings with defaults & validation
│   │   ├── dataset_service.py      # DataCo dataset loader + synthetic fallback
│   │   └── mailer.py               # Email delivery (SMTP + SendGrid)
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
│   │   ├── cache.py                # TTLCache + named caches (products, dashboard, etc.)
│   │   └── helpers.py              # API responses, EOQ calc, formatting, stock status
│   │
│   ├── routes/                     # HTTP route blueprints
│   │   ├── __init__.py             # Exports auth_bp, ui_bp, api_bp, ai_bp
│   │   ├── auth.py                 # Auth routes: login, register, forgot/reset password
│   │   ├── ui.py                   # Main UI: dashboard, inventory, suppliers, reports, EOQ, monitoring, help, contact, settings
│   │   ├── api.py                  # REST API: health, products, suppliers, movements, EOQ, dashboard live
│   │   └── ai.py                   # AI routes: forecast, anomaly, EOQ sensitivity, monitoring pages
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
│   │       ├── 400.html
│   │       ├── 401.html
│   │       ├── 403.html
│   │       ├── 404.html
│   │       ├── 422.html
│   │       ├── 429.html
│   │       └── 500.html
│   │
│   └── static/                     # Static assets
│       ├── css/
│       │   ├── style.css           # Main application styles
│       │   ├── landing.css         # Landing page styles
│       │   └── ai-features.css     # AI feature styles
│       ├── js/
│       │   ├── auth-bg.js          # Three.js auth background
│   │   │   ├── dashboard-3d.js     # Three.js dashboard background
│   │   │   ├── saas-animations.js  # GSAP scroll-triggered animations
│   │   │   ├── ai-features.js      # AI forecast/anomaly Plotly logic
│   │   │   └── main.js             # Theme toggle, nav, toast notifications
│   │   └── img/
│   │       ├── favicon.svg         # Browser tab icon
│   │   │   └── logo.svg            # App logo
│   │
├── migrations/                     # Alembic migrations
│   ├── env.py                      # Alembic environment (DATABASE_URL)
│   └── versions/
│       ├── 001_initial.py          # Initial schema migration
│       ├── 002_critical_fixes.py   # Critical fixes migration
│       └── 003_enable_rls.py       # Row-Level Security migration
├── tests/                          # Test suite
│   ├── __init__.py
│   ├── conftest.py                 # Fixtures: app, client, auth_client
│   ├── test_api.py                 # REST API tests
│   ├── test_auth.py                # Authentication flow tests
│   ├── test_cache.py               # TTLCache + bust hooks tests
│   ├── test_etl.py                 # ETL pipeline / warehouse tests
│   ├── test_ml.py                  # Forecast + anomaly model tests
│   ├── test_monitoring.py          # Model monitoring tests
│   ├── test_notifications.py       # Notification API tests
│   ├── test_reports_fact.py        # Reports fact-table endpoint tests
│   ├── test_roles.py               # Role-based access control tests
│   ├── test_security.py            # Validators, headers, rate limiting tests
│   └── test_services.py            # Service-layer validation tests
└── myvenv/                         # Python virtual environment (gitignored)
```

---

## 2. Module Inventory

| Module | Path | Responsibility | Key Classes/Functions |
|--------|------|---------------|----------------------|
| **App Factory** | `app/__init__.py` | Flask app creation, extension init, blueprint registration, error handlers, context processor, bootstrap hook | `create_app()` |
| **Config** | `app/config/settings.py` | Environment-based configuration (Dev/Prod/Testing), DB params, SMTP, feature flags | `Config`, `DevelopmentConfig`, `ProductionConfig`, `TestingConfig` |
| **Extensions** | `app/extensions.py` | Flask extension singletons (Login, CSRF, Limiter) | `login_manager`, `csrf`, `limiter` |
| **Models** | `app/models.py` | Flask-Login user adapter for psycopg2 rows | `UserProxy(UserMixin)` |
| **Database Connection** | `app/database/connection.py` | Threaded connection pooling, schema bootstrap, ETL orchestration | `get_connection()`, `get_cursor()`, `bootstrap_database()`, `init_schema()` |
| **Database Schema** | `app/database/schema.sql` | DDL for operational tables + star schema (dim/fact) + RLS | SQL: `users`, `products`, `movements`, `suppliers`, `purchase_orders`, `dim_*`, `fact_*` |
| **Stored Procedures** | `app/database/procedures.sql` | 84+ `sp_*` functions for all CRUD operations | `sp_product_list`, `sp_movement_record`, `sp_user_create`, etc. |
| **Triggers** | `app/database/triggers.sql` | 8 triggers for audit logging, validation, session tracking | `trg_validate_movement`, `trg_audit_*`, `trg_session_*` |
| **Warehouse** | `app/database/warehouse.sql` | SCD Type 2 dimensions + fact tables for analytics | `dim_product_scd`, `dim_supplier_scd`, `dim_warehouse_scd`, `fact_movement_daily`, `fact_inventory_daily` |
| **ETL Pipeline** | `app/database/etl.py` | Builds star-schema warehouse from operational tables (incremental) | `run_etl()` |
| **Seed Data** | `app/database/seed.py` | Populates DB with demo data (users, suppliers, products, movements) | `run_seed()` |
| **Repositories** | `app/repositories/` | Data access layer via stored procedures (11 modules) | `ProductRepository`, `MovementRepository`, `SupplierRepository`, `PurchaseOrderRepository`, `UserRepository`, `SettingsRepository`, `NotificationRepository`, `ForecastRepository`, `MonitoringRepository`, `AuditRepository`, `WarehouseRepository` |
| **Services** | `app/services/` | Business logic and orchestration (12 modules) | `AuthService`, `ProductService`, `MovementService`, `SupplierService`, `EOQService`, `ForecastService`, `AnomalyService`, `MonitoringService`, `NotificationService`, `SettingsService`, `DatasetService`, `Mailer` |
| **Security** | `app/security/` | Input validation, RBAC, HTTP security headers | `validators.py`, `roles.py`, `headers.py` |
| **ML** | `app/ml/` | Forecasting (Prophet/ARIMA/ensemble) and anomaly detection (Isolation Forest/z-score) | `forecast_with_prophet()`, `forecast_with_arima()`, `forecast_ensemble()`, `detect_anomalies_isoforest()`, `spc_zscore_analysis()` |
| **Utils** | `app/utils/` | API helpers, EOQ calculations, money formatting, TTL cache | `cache.py` (TTLCache + `cache_bust_*` hooks), `helpers.py` (`api_response()`, `api_error()`, `calculate_eoq()`, `format_money_display()`) |
| **Routes** | `app/routes/` | HTTP blueprints (4 blueprints: auth, ui, api, ai) | `auth_bp` (5 routes), `ui_bp` (25 routes), `api_bp` (18 routes), `ai_bp` (21 routes) |

---

## 3. Dependency Flow

### High-Level Module Dependencies
```
run.py
  └── app/__init__.py (create_app)
      ├── app/config/settings.py (Config classes)
      ├── app/database/connection.py (pooling, bootstrap)
      │   ├── app/database/seed.py (demo data)
      │   │   └── app/services/dataset_service.py (DataCo loader)
      │   └── app/database/etl.py (star schema build)
      ├── app/extensions.py (Login, CSRF, Limiter)
      ├── app/models.py (UserProxy)
      ├── app/security/ (headers, validators, roles)
      ├── app/routes/ (4 blueprints)
      │   ├── routes/auth.py
      │   │   ├── app/services/auth_service.py
      │   │   │   ├── app/repositories/user_repo.py
      │   │   │   ├── app/repositories/audit_repo.py
      │   │   │   ├── app/security/validators.py
      │   │   │   └── app/services/mailer.py
      │   │   └── app/repositories/user_repo.py
      │   ├── routes/ui.py
      │   │   ├── app/repositories/* (all repos)
      │   │   ├── app/services/* (all services)
      │   │   └── app/utils/cache.py
      │   ├── routes/api.py
      │   │   ├── app/repositories/* (most repos)
      │   │   ├── app/services/* (most services)
      │   │   └── app/utils/ (helpers, cache)
      │   └── routes/ai.py
      │       ├── app/services/forecast_service.py
      │       │   ├── app/ml/forecasting.py
      │       │   └── app/repositories/forecast_repo.py
      │       └── app/services/anomaly_service.py
      │           ├── app/ml/anomaly.py
      │           └── app/repositories/forecast_repo.py
      └── app/utils/cache.py (named cache instances: products, dashboard, reports, eoq_table, ai_product_list)
```

### Repository → Stored Procedure Mapping (Key Examples)
| Repository | Frequently Used SPROCs |
|-----------|------------------------|
| `UserRepository` | `sp_user_create`, `sp_user_find_by_username`, `sp_user_find_by_email`, `sp_user_record_login`, `sp_session_*` |
| `ProductRepository` | `sp_product_list`, `sp_product_find_by_sku`, `sp_product_create`, `sp_product_update`, `sp_product_set_stock`, `sp_product_low_stock` |
| `MovementRepository` | `sp_movement_record`, `sp_movement_daily_totals`, `sp_movement_units_today`, `sp_movement_daily_for_product` |
| `PurchaseOrderRepository` | `sp_po_list_by_status`, `sp_po_create`, `sp_po_update_status` |
| `NotificationRepository` | `sp_notification_create`, `sp_notification_find_by_user`, `sp_notification_mark_read` |
| `AuditRepository` | `sp_audit_record`, `sp_audit_recent` |
| `SettingsRepository` | `sp_settings_all`, `sp_settings_set_many` |
| `ForecastRepository` | `sp_forecast_save`, `sp_forecast_get_by_product` |
| `MonitoringRepository` | `sp_monitoring_save`, `sp_monitoring_get_latest` |
| `WarehouseRepository` | `sp_warehouse_analytics` (complex joins on star schema) |

---

## 4. Entry Points

| Entry Point | Path | Purpose |
|-------------|------|---------|
| **`python run.py`** | `run.py` | Main entry point. Creates Flask app via `create_app()`. Debug: Werkzeug server with auto-reload. Prod: Gunicorn (1 worker, 2 threads). |
| **`gunicorn run:app`** | `run.py` | Production WSGI entry (Render deploy). Same `app` object. |
| **`python migrate.py <cmd>`** | `migrate.py` | CLI: `create`, `upgrade`, `downgrade`, `current`, `history`. Wraps Alembic. |
| **`flask init-db`** | `app/__init__.py` | CLI: Apply schema + seed + ETL in one shot (`bootstrap_database()`). |
| **`flask seed-db`** | `app/__init__.py` | CLI: Seed demo data only. |
| **`flask etl-db`** | `app/__init__.py` | CLI: Run ETL pipeline only. |
| **`python -m pytest`** | `tests/` | Run test suite (via `pytest.ini`). |

### First-Run Bootstrap (Idempotent)
On `python run.py` startup, `bootstrap_database()` runs:
1. `init_schema()` — applies `schema.sql`, `procedures.sql`, `warehouse.sql`, `etl_procedures.sql`, `triggers.sql`
2. `seed_database()` — inserts demo users, suppliers, products, movements, POs
3. `etl_database()` — builds star-schema warehouse (if `RUN_ETL_ON_STARTUP=true`)

---

## 5. Data Flow Through the Codebase

### Request Lifecycle (Simplified)
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

### Key Environment Variables
| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | `change-me-in-production` | Flask session signing |
| `DATABASE_URL` | — | PostgreSQL connection string (overrides DB_* fields) |
| `FLASK_ENV` | `development` | Environment (development/production/testing) |
| `RENDER_INSTANCE_ID` | — | Set by Render.com (auto-detects production) |
| `RUN_ETL_ON_STARTUP` | `true` | Run ETL on app start |
| `SMTP_HOST` | `""` | SMTP server (empty = dev fallback) |
| `SMTP_PORT` | `587` | SMTP port |
| `MAIL_FROM` | `no-reply@inventorylogix.local` | Sender email |
| `MAIL_USE_TLS` | `true` | Enable TLS |
| `SENDGRID_API_KEY` | `""` | SendGrid API (alternative to SMTP) |
| `PASSWORD_RESET_TTL_MINUTES` | `5` | Reset token lifetime |
| `RATELIMIT_STORAGE_URI` | `memory://` | Rate limit storage backend |
| `AI_FORECAST_ENABLED` | `true` | Feature flag |
| `ANOMALY_DETECTION_ENABLED` | `true` | Feature flag |
| `SECURITY_HEADERS_ENABLED` | `true` | Feature flag |

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
| `test_security.py` | `tests/test_security.py` | Validators | SKU, email, password, username, positive number, string length, RBAC, headers, rate limiting |
| `test_services.py` | `tests/test_services.py` | Service layer | Business logic validation (auth, product, movement, etc.) |
| `test_roles.py` | `tests/test_roles.py` | RBAC | Role-based access control |
| `test_cache.py` | `tests/test_cache.py` | Cache | TTLCache get/set/invalidate, cache_bust_* hooks |
| `test_etl.py` | `tests/test_etl.py` | ETL | Star-schema build, incremental runs, stock walk clamping |
| `test_ml.py` | `tests/test_ml.py` | ML | Forecast fallback (moving average), anomaly detection (Isolation Forest + SPC) |
| `test_monitoring.py` | `tests/test_monitoring.py` | Monitoring | Metrics aggregation, alert triggering, degradation detection |
| `test_notifications.py` | `tests/test_notifications.py` | Notifications | CRUD operations, bulk inserts, alert checks |
| `test_reports_fact.py` | `tests/test_reports_fact.py` | Reports fact-table | SQL uses fact_movement_daily + dim joins, correct output structure |
| `test_api.py` | `tests/test_api.py` | API contract | Response envelope, status codes, error handling |

### Test Configuration
- `pytest.ini`: `testpaths = tests`
- Tests run against local PostgreSQL (never production)
- `WTF_CSRF_ENABLED = False` for test client
- Demo credentials: `admin/Admin@123`, `manager/Manager@123`, `viewer/Viewer@123`
- Collected tests: 180 in 11 files + conftest (typically 170+ pass)

---

## 8. Documentation Inventory

| Document | Path | Purpose |
|----------|------|---------|
| `README.md` | Root | Project overview, setup instructions |
| `AGENTS.md` | Root | Agent development guide, architecture notes |
| `opencode.json` | Root | OpenCode agent configuration |
| `SUPABASE_SETUP.md` | Root | Supabase integration guide |
| `Testing.md` | `docs/Testing.md` | Testing guide |
| `REPOSITORY_MAP.md` | `docs/project-analysis/` | This document |
| `BUSINESS_GUIDE.md` | `docs/project-analysis/` | Business context, use cases, stakeholders |
| `EVIDENCE_REGISTER.md` | `docs/project-analysis/` | Evidence tracking (direct observation, structural, inferred, documentation) |
| `EXECUTIVE_SUMMARY.md` | `docs/project-analysis/` | Executive summary for stakeholders |
| `INTERVIEW_QA.md` | `docs/project-analysis/` | Interview questions and answers with domain experts |
| `LITERATURE_REVIEW.md` | `docs/project-analysis/` | Literature review of inventory optimization techniques |
| `PROJECT_ANALYSIS.md` | `docs/project-analysis/` | Full project analysis (architecture, business, dev history, client-sales) |
| `TECHNICAL_ARCHITECTURE.md` | `docs/project-analysis/` | Deep dive into technical design decisions |

---

## 9. Static Assets Inventory

### CSS (3 files)
| File | Path | Purpose |
|------|------|---------|
| `style.css` | `app/static/css/` | Main application styles (dark mode, dashboard, forms, responsive) |
| `landing.css` | `app/static/css/` | Landing page styles (hero, features, CTA) |
| `ai-features.css` | `app/static/css/` | AI forecast/anomaly page styles (overlays, modals) |

### JavaScript (5 files)
| File | Path | Purpose |
|------|------|---------|
| `auth-bg.js` | `app/static/js/` | Three.js 3D background (auth pages) |
| `dashboard-3d.js` | `app/static/js/` | Three.js 3D background (dashboard) |
| `saas-animations.js` | `app/static/js/` | GSAP scroll-triggered entrance animations |
| `ai-features.js` | `app/static/js/` | AI forecast/anomaly Plotly charts, UI logic |
| `main.js` | `app/static/js/` | Theme toggle, nav, toast notifications, IntersectionObserver |

### Images (2 files)
| File | Path | Purpose |
|------|------|---------|
| `favicon.svg` | `app/static/img/` | Browser tab icon |
| `logo.svg` | `app/static/img/` | App logo (also embedded in password reset emails) |

### CDN Dependencies (loaded in base.html)
- **Plotly.js** — Interactive charts (dashboard, reports, forecast, anomaly, EOQ)
- **Three.js** — 3D background animations
- **GSAP + ScrollTrigger** — Scroll-triggered animations
- **Chart.js** — Additional charting (used in some legacy components)
- **Inter Font** — Typography (variable font, loaded via Google Fonts)

---

## 10. Template Inventory

| Template | Path | Route | Purpose |
|----------|------|-------|---------|
| `base.html` | `templates/` | — | Base layout (CDN scripts, theme handling, nav, flash messages) |
| `landing.html` | `templates/` | `GET /` (unauth) | Public landing page with stats and CTAs |
| `dashboard.html` | `templates/` | `GET /` (auth) | Main dashboard (KPIs, charts, ABC analysis, supplier performance) |
| `inventory.html` | `templates/` | `GET /inventory` | Product list with search/filter/pagination, bulk actions |
| `product_form.html` | `templates/` | `GET/POST /products/new`, `/products/<id>/edit` | Create/edit product form (validation, dynamic sections) |
| `product_detail.html` | `templates/` | `GET /products/<id>` | Product detail view + recent movement history |
| `movement_form.html` | `templates/` | `GET/POST /movements/new` | Record stock movement form (type, quantity, notes) |
| `suppliers.html` | `templates/` | `GET/POST /suppliers` | Supplier management page (list, create/edit) |
| `purchase_orders.html` | `templates/` | `GET/POST /purchase-orders` | Purchase order kanban board (status columns) |
| `reorder_alerts.html` | `templates/` | `GET /reorder-alerts` | Low stock alerts + auto-reorder draft PO generation |
| `warehouses.html` | `templates/` | `GET /warehouses` | Warehouse analytics (star schema: turns, dor, efficiency) |
| `reports.html` | `templates/` | `GET/POST /reports` | Filtered analytics reports (breakdown, KPIs, trends, top SKUs) |
| `eoq_calculator.html` | `templates/` | `GET /eoq-calculator` | EOQ calculator page (formula, cost curve chart) |
| `monitoring.html` | `templates/` | `GET /monitoring` | ETL monitoring + DB stats (table sizes, last run, performance) |
| `settings.html` | `templates/` | `GET /settings` | User preferences page (theme, notifications, language) |
| `help.html` | `templates/` | `GET /help` | Help documentation page (FAQ, troubleshooting) |
| `contact.html` | `templates/` | `GET /contact` | Contact page (form, email, phone) |
| `auth/login.html` | `templates/auth/` | `GET/POST /auth/login` | Login form (username/password, remember-me removed) |
| `auth/register.html` | `templates/auth/` | `GET/POST /auth/register` | Registration form (email validation, password strength) |
| `auth/forgot_password.html` | `templates/auth/` | `GET/POST /auth/forgot-password` | Password reset request (email input) |
| `auth/reset_password.html` | `templates/auth/` | `GET/POST /auth/reset-password/<token>` | Password reset form (new password, confirm) |
| `ai/forecast.html` | `templates/ai/` | `GET /ai/forecast` | AI forecast page (Plotly chart, portfolio table, plain-language info) |
| `ai/anomaly.html` | `templates/ai/` | `GET /ai/anomaly` | AI anomaly detection page (Plotly chart, portfolio table, plain-language info) |
| `errors/400.html` | `templates/errors/` | 400 handler | Bad request (invalid input) |
| `errors/401.html` | `templates/errors/` | 401 handler | Unauthorized (auth required) |
| `errors/403.html` | `templates/errors/` | 403 handler | Forbidden (insufficient permissions) |
| `errors/404.html` | `templates/errors/` | 404 handler | Not found (route/resource missing) |
| `errors/422.html` | `templates/errors/` | 422 handler | Unprocessable (validation failed) |
| `errors/429.html` | `templates/errors/` | 429 handler | Rate limited (too many requests) |
| `errors/500.html` | `templates/errors/` | 500 handler | Server error (unexpected exception) |

---

## 11. Technology Stack

### Backend
| Technology | Version | Purpose |
|-----------|---------|---------|
| Python | 3.10+ | Runtime |
| Flask | ≥3.0 | Web framework (application factory pattern) |
| psycopg2-binary | ≥2.9 | PostgreSQL adapter (RealDictCursor) |
| Flask-Login | ≥0.6 | Session management (browser-session cookie only) |
| Flask-WTF | ≥1.2 | CSRF protection |
| Flask-Limiter | ≥3.5 | Rate limiting (auth: 10/min login, 5/min register; API writes: 30/min; movements: 60/min) |
| Flask-Migrate | ≥4.0 | Alembic integration |
| Werkzeug | (Flask) | Password hashing, WSGI utilities |
| python-dotenv | ≥1.0 | Environment variable loading (.env) |
| email-validator | ≥2.0 | Email validation |

### Data & Analytics
| Technology | Version | Purpose |
|-----------|---------|---------|
| PostgreSQL | 14+ | Primary database (operational + star schema) |
| Alembic | (via Flask-Migrate) | Schema migrations (001_initial, 002_critical_fixes, 003_enable_rls) |

### Machine Learning (Optional - Graceful Fallback)
| Technology | Version | Purpose |
|-----------|---------|---------|
| Prophet | ≥1.1 | Time-series forecasting (if installed) |
| statsmodels | ≥0.14 | ARIMA forecasting (if installed) |
| scikit-learn | ≥1.3 | Isolation Forest anomaly detection (if installed) |
| plotly | ≥5.0 | Interactive charting (frontend) |
| Moving average | — | Forecast fallback when ML libraries unavailable |
| Z-score | — | Anomaly fallback when ML libraries unavailable (SPC ±3σ bands) |

### External Services
| Service | Purpose |
|---------|---------|
| SendGrid API | Password reset emails (HTTPS, Render-compatible, fallback to SMTP logs) |
| SMTP (optional) | Alternative email delivery (dev: logs to console) |

### Deployment & DevOps
| Tool | Purpose |
|------|---------|
| Gunicorn | Production WSGI server (1 worker, 2 threads) |
| Render.com | Cloud hosting (free tier: PostgreSQL + web service) |
| Supabase | Alternative PostgreSQL hosting (via `SUPABASE_SETUP.md`) |
| Alembic | Database schema migrations (version-controlled) |
| pre-commit | (Optional) Git hooks for formatting/linting |

### Frontend Libraries (CDN)
| Library | Purpose |
|---------|---------|
| Plotly.js | Interactive charts (time-series, bar, pie, scatter) |
| Three.js | 3D background animations (auth-bg.js, dashboard-3d.js) |
| GSAP + ScrollTrigger | Scroll-triggered entrance animations (saas-animations.js) |
| Chart.js | Additional charting (legacy components, being phased out) |
| Inter Font | Typography (variable font, weights 400/600, loaded via Google Fonts) |

---

## 12. Database Schema Summary

### Operational Tables (`schema.sql`)
| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `users` | User accounts | `id`, `username`, `email`, `password_hash`, `role` (`viewer`/`manager`/`admin`), `is_active` |
| `suppliers` | Supplier directory | `id`, `name`, `location`, `lead_days` (avg), `reliability` (0-1 score) |
| `products` | Product catalogue | `id`, `sku` (unique), `name`, `category`, `warehouse`, `current_stock`, `reorder_point`, `unit_price`, `demand_rate` (avg daily units), `ordering_cost`, `holding_cost` |
| `movements` | Stock movements | `id`, `product_id` (FK), `sku` (denormalized for speed), `type` (`IN`/`OUT`/`ADJUSTMENT`/`RETURN`), `quantity` (positive), `created_at` |
| `purchase_orders` | PO tracking | `id`, `po_number` (unique), `supplier_id` (FK), `product_id` (FK), `quantity`, `status` (`draft`/`approved`/`in_transit`/`received`/`cancelled`), `expected_date`, `received_date` |
| `user_settings` | Per-user preferences | `user_id` (FK), `key` (e.g., `theme`, `items_per_page`), `value` (TEXT) |
| `password_reset_tokens` | Password reset | `user_id` (FK), `token_hash` (unique), `expires_at`, `used` (boolean) |
| `audit_log` | Audit trail (JSONB) | `user_id` (FK), `action` (enum), `target_type` (enum), `target_id` (FK), `detail` (JSONB), `created_at` |
| `user_sessions` | Session tracking | `user_id` (FK), `session_token` (unique, browser-session), `ip_address`, `user_agent`, `is_active`, `created_at`, `last_activity` |
| `etl_state` | ETL watermark (key-value) | `state_key` (unique), `value` (TEXT), `updated_at` |
| `forecast_cache` | ML results cache | `product_id` (FK), `model` (enum), `horizon` (days), `payload` (JSONB: predictions, conf_int, accuracy), `created_at` |
| `anomaly_log` | Anomaly detections | `product_id` (FK), `anomaly_type` (enum), `z_score` (DOUBLE PRECISION), `confidence` (0-1), `value` (actual), `expected` (model), `created_at` |

### Warehouse Tables (`warehouse.sql` - Star Schema)
| Table | Purpose | Key Columns / Notes |
|-------|---------|---------------------|
| `dim_date` | Date dimension | `date_id` (PK, INT YYYYMMDD), `date` (DATE), `day`, `month`, `quarter`, `year`, `day_of_week`, `is_weekend` |
| `dim_warehouse` | Warehouse dimension | `warehouse_id` (PK), `warehouse` (name), `location`, `capacity` |
| `dim_product` | Product dimension (SCD Type 2) | `product_id` (PK), `sku` (business key), `name`, `category`, `warehouse`, `effective_date`, `expiration_date`, `is_current` (boolean) |
| `dim_supplier` | Supplier dimension (SCD Type 2) | `supplier_id` (PK), `name` (business key), `location`, `lead_days`, `reliability`, `effective_date`, `expiration_date`, `is_current` |
| `fact_movement_daily` | Daily movement aggregates | `date_id` (FK → dim_date), `product_id` (FK → dim_product), `warehouse_id` (FK → dim_warehouse), `units_in`, `units_out`, `units_adjustment`, `units_return`, `net_change` |
| `fact_inventory_daily` | Daily inventory snapshots | `date_id` (FK → dim_date), `product_id` (FK → dim_product), `warehouse_id` (FK → dim_warehouse), `snapshot_stock` (closing stock) |

### Row-Level Security (RLS)
- All tables have RLS enabled with **zero policies** (deny-by-default for Supabase auto-generated API).
- Flask app connects as table owner (`postgres` role) which **bypasses RLS** entirely.
- This design allows Supabase compatibility while maintaining full control via stored procedures in the Flask app.

---

## 13. Route Summary

### Auth Blueprint (`/auth`)
| Method | Endpoint | Handler | Rate Limit |
|--------|----------|---------|------------|
| GET/POST | `/auth/login` | `auth.login` | 10/min |
| GET/POST | `/auth/register` | `auth.register` | 5/min |
| GET/POST | `/auth/forgot-password` | `auth.forgot_password` | 5/hr |
| GET/POST | `/auth/reset-password/<token>` | `auth.reset_password` | — |
| POST | `/auth/logout` | `auth.logout` | — |

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

## 14. Known Variations / Unsupported Features

| Item | Status | Notes |
|------|--------|-------|
| DataCo dataset CSV | Gitignored | `datasets/DataCoSupplyChainDataset.csv` not tracked; synthetic fallback used in `dataset_service.py` |
| NVIDIA API key | Referenced in AGENTS.md | Used by OpenCode agents; **no usage in Python code** (local LLM inference) |
| OAuth providers | Schema ready | `oauth_provider`/`oauth_id` columns exist in `users`; no OAuth routes implemented |
| WebSocket support | Not present | Dashboard uses polling (`/api/dashboard/live` every 15s) for live updates |
| Celery/task queue | Not present | ETL runs in non-blocking thread (via `threading.Thread`) for responsiveness |
| Remember-me login | **Removed** | Login sets **only browser-session cookie** (no persistent remember-me); closing browser ends session |
| Static asset versioning | Manual bump | Query params (`style.css?v=20.3`, `main.js?v=1.2`, `ai-features.js?v=9.2`) must be updated on CSS/JS changes to bust cache |

---

## 15. Evidence Provenance

- **E1 (Direct observation)**: All file contents read directly from the current workspace filesystem.
- **E2 (Structural)**: Directory listings (`ls`), glob results (`grep -r`), import statements (`grep -r "from.*import"`).
- **E3 (Inferred)**: Module dependencies traced via import chains, route registrations (`@bp.route`), service/repository instantiation.
- **E4 (Documentation)**: Cross-checked with `AGENTS.md`, `README.md`, `render.yaml`, `.env.example`, `pytest.ini`.
- **E5 (Execution validation)**: Spot-checked flows via manual test runs (login, movement record, forecast run, reports page load).

---

## 16. Conclusion

This repository map reflects the **current state** of the Inventory Logistics Optimization Dashboard as of **2026-09-13**. It captures the evolution from an initial CRUD app to a feature-rich system with:

- **Star-schema data warehouse** (SCD Type 2 dimensions + fact tables) enabling fast analytical queries
- **Role-based access control** (viewer/manager/admin) with granular route protection
- **Multi-select filters** (checkbox dropdowns with Apply/Reset) for reports and inventory
- **Browser-session-only authentication** (no persistent remember-me cookie) enhancing security
- **Cached intelligence pages** (forecast/anomaly/EOQ) with model metadata and plain-language explainability
- **Automated ETL pipeline** with incremental updates and stock walk clamping for accuracy
- **Comprehensive test suite** (180 tests) covering auth, RBAC, API contracts, ML fallbacks, caching, and warehouse analytics
- **Performance optimizations** (increased cache TTLs, batched queries, lazy-loaded assets, removed smooth-scroll hijacker)
- **UI/UX enhancements** (responsive filter panels, theme-aware charts, toast notifications, accessible modals)
- **Security hardening** (parameterized queries via stored procedures, CSP nonces, rate limiting, input validation)

The system balances **technical sophistication** (star schema, ML orchestration, SCD Type 2) with **practical usability** (intuitive filters, clear KPIs, actionable alerts) and **maintainability** (modular layers, documented contracts, automated testing).

*End of Repository Map*