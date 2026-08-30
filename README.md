# InventoryLogix — Inventory Logistics Optimization Dashboard

A full-stack Flask + PostgreSQL application for warehouse stock management with
**real-time CRUD**, **AI demand forecasting**, **anomaly detection**, **REST API**,
**data warehouse ETL**, and an **auth-protected** UI built on a unified futuristic
dark-mode design with glassmorphism, GSAP animations, and Three.js 3D backgrounds.

---

## Highlights

- **Authentication** — Flask-Login with hashed passwords, role-based access
  (`admin`, `manager`, `viewer`), CSRF protection via Flask-WTF, per-request
  CSP nonces, session fingerprinting, account lockout (5 failed attempts → 15 min),
  and rate-limited auth endpoints. Self-registration always creates a **viewer**
  account; write access is restricted to `admin`/`manager`.
- **Database** — PostgreSQL with 84+ stored procedures, 8 trigger functions,
  SCD Type 2 data warehouse dimensions + fact tables, and a full ETL pipeline.
  Schema bootstrap + seeding run automatically on first start.
- **Real data** — seeded from the **DataCo SMART SUPPLY CHAIN** dataset
  (180,000+ real transactions): 118 products with real demand / ordering /
  holding costs (used for EOQ) and up to 150 suppliers. Deterministic synthetic
  catalogue when the dataset file is absent.
- **REST API** — `/api/products`, `/api/suppliers`, `/api/movements`,
  `/api/eoq/calculate`, `/api/health`, plus AI endpoints. Consistent JSON
  envelope with success/error codes.
- **ML module** — Prophet, ARIMA, and ensemble forecasting with graceful
  fallback. Anomaly detection uses Isolation Forest plus SPC z-score control
  charts. Portfolio-level forecast and anomaly endpoints with 1-hour caching.
- **Data warehouse** — ETL pipeline populates `dim_product`, `dim_supplier`,
  `dim_date`, `fact_inventory_daily`, and `fact_movement_monthly`. Stock walk
  clamping ensures inventory accuracy. Warehouse monitoring dashboard at
  `/monitoring`.
- **Security** — CSP nonces on all inline scripts + import maps, per-request
  nonce generation, password hashing, parameterised SQL, rate limiting, audit
  logging, account lockout, secure session cookies, and soft-validated forms.
- **Performance** — cached context processor (60s), lazy-loaded Plotly (3.5MB
  only on pages that use it), dashboard queries batched (14→11), reports cache
  TTL 5 min, AI portfolio cached 1 hour, ETL rebuilds non-blocking.
- **UI** — unified futuristic dark-mode design with glassmorphism panels, GSAP
  entrance animations, Three.js 3D wave + particle background, Chart.js /
  Plotly charts with theme-aware datalabels, SVG sparklines, dark/light theme
  toggle, and toast notifications.

---

## Project Structure

```
.
├── app/
│   ├── __init__.py              # Application factory
│   ├── config/                  # Environment-driven configuration
│   ├── database/
│   │   ├── schema.sql           # Operational tables
│   │   ├── procedures.sql       # 84+ stored procedures
│   │   ├── triggers.sql         # 8 trigger functions
│   │   ├── warehouse.sql        # SCD Type 2 dims + fact tables
│   │   ├── etl_procedures.sql   # ETL + monitoring procedures
│   │   ├── etl.py               # ETL pipeline + stock walk clamping
│   │   ├── seed.py              # Demo data seeding
│   │   └── connection.py        # Pool management + bootstrap
│   ├── repositories/            # SQL CRUD per entity
│   ├── services/                # Business logic (auth, products, EOQ, …)
│   ├── routes/                  # Flask blueprints (auth, ui, api, ai)
│   ├── ml/                      # Forecasting + anomaly detection
│   ├── security/                # Validators, CSP headers, roles
│   ├── utils/                   # Helpers (EOQ formula, format_money, …)
│   ├── templates/               # Jinja2 templates
│   │   ├── base.html            # Shared layout + CDN scripts
│   │   ├── auth/                # login / register / forgot / reset
│   │   ├── ai/                  # forecast / anomaly
│   │   └── errors/              # 400 / 401 / 403 / 404 / 422 / 429 / 500
│   └── static/
│       ├── css/
│       │   ├── style.css        # Main app styles (~3800 lines)
│       │   ├── landing.css      # Landing page + theme tokens
│       │   └── ai-features.css  # AI overlay styles
│       ├── js/
│       │   ├── auth-bg.js       # Three.js 3D background (all pages)
│       │   ├── dashboard-3d.js  # Dashboard panel tilt + chart animation
│       │   ├── saas-animations.js  # GSAP entrance animations
│       │   ├── ai-features.js   # AI forecast/anomaly/portfolio UI
│       │   ├── eoq.js           # EOQ calculator + cost curve chart
│       │   ├── main.js          # IntersectionObserver, toast, theme
│       │   └── landing.js       # Landing page animations
│       └── img/                 # favicon.svg, logo.svg
├── migrations/                  # Alembic migration system
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 001_initial.py
│       └── 002_critical_fixes.py
├── tests/                       # pytest suite
├── scripts/                     # ops helpers
├── run.py                       # Entry point
├── migrate.py                   # Alembic helper CLI
├── alembic.ini                  # Alembic config
├── render.yaml                  # Render Blueprint
├── requirements.txt
├── PRODUCT.md                   # Product requirements doc
└── README.md
```

---

## Quick start

### 1. Install dependencies

```bash
python -m venv myvenv
myvenv\Scripts\activate            # Windows
pip install -r requirements.txt
```

### 2. Configure environment

Copy `.env.example` to `.env`:

```
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/inventory_db
SECRET_KEY=replace-this-with-a-random-50-char-string
FLASK_ENV=development
```

### 3. Run the Flask app

```bash
python run.py
# open http://localhost:5000
```

Schema is applied and seeded automatically on first run. Demo credentials:

| User    | Password    | Role    |
|---------|-------------|---------|
| viewer  | Viewer@123  | viewer  |

### 4. Password reset

- **SMTP configured** — branded HTML email with single-use reset link.
- **No SMTP** — reset link shown directly on the confirmation page (dev mode).

---

## Deploying to Render

1. Push to GitHub.
2. Render dashboard → **New + → Blueprint** → pick repo → **Apply**.
3. Render creates a PostgreSQL database + web service automatically.
4. First boot applies schema + seeds demo data.

`autoDeploy: true` redeploys on every push to `main`.

---

## Performance

| Area | Before | After |
|------|--------|-------|
| Context processor | 1 DB query per page load | Cached 60s (global key) |
| Plotly CDN | Loaded on every page (~3.5MB) | Lazy-loaded (dashboard, forecast, anomaly, EOQ only) |
| Dashboard queries | 14 sequential | 11 (batched product agg + merged top demand/sales) |
| Reports queries | 30+ sequential | 25+ (merged `_period_orders` 4→1, warehouse breakdown+status merged) |
| Reports cache | 30s TTL | 300s TTL (10x fewer cold hits) |
| AI portfolio | No caching | 1-hour TTL cache |
| ETL rebuild | Synchronous (10-60s block) | Non-blocking thread |

---

## Security

- **CSP nonces** — per-request nonces on all inline scripts + import maps; no
  `unsafe-inline` for scripts.
- **Account lockout** — 5 failed attempts → 15 minute lock with threading lock.
- **Session cookies** — `Secure`, `HttpOnly`, `SameSite=Lax` by default;
  `SESSION_COOKIE_SECURE` true in production.
- **Password reset tokens** — single-use, TTL-based, only shown in debug mode.
- **Role-based access** — `viewer` is read-only; write routes restricted to
  `admin`/`manager`.
- **Rate limiting** — Flask-Limiter on auth (10/min login, 5/min register),
  API writes (30/min), movements (60/min).
- **Parameterised SQL** — psycopg2 `%s` placeholders everywhere; all CRUD
  goes through stored procedures.
- **Audit log** — every mutating call writes to `audit_log`.
- **HTTP headers** — `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, `Permissions-Policy`, CSP.
- **Error pages** — user-safe pages for 400, 401, 403, 404, 422, 429, 500.

---

## Database

### Operational tables
`users`, `suppliers`, `products`, `movements`, `purchase_orders`, `audit_log`,
`forecast_cache`, `anomaly_log`, `user_settings`, `etl_state`

### Stored procedures (84+)
All CRUD goes through `sp_*` functions to prevent SQL injection. Examples:
`sp_product_list`, `sp_movement_create`, `sp_po_update_status`,
`sp_settings_upsert_batch`.

### Triggers
- `trg_validate_movement` — auto-populates SKU from product_id, validates FK,
  prevents negative stock on OUT/ADJUSTMENT.
- `trg_audit_*` — audit log triggers on products, suppliers, movements, POs.

### Data warehouse (Alembic-managed)
- `dim_product` (SCD Type 2), `dim_supplier`, `dim_date`
- `fact_inventory_daily`, `fact_movement_monthly`
- ETL pipeline: `python migrate.py etl` or `/monitoring` → Run ETL

---

## REST API

| Method | Endpoint                          | Description                       |
|--------|-----------------------------------|-----------------------------------|
| GET    | `/api/health`                     | Liveness probe                    |
| GET    | `/api/products`                   | Paginated product list            |
| GET    | `/api/products/<id>`              | Product detail                    |
| POST   | `/api/products`                   | Create product                    |
| PUT    | `/api/products/<id>`              | Update product                    |
| DELETE | `/api/products/<id>`              | Delete product                    |
| GET    | `/api/suppliers`                  | Supplier list                     |
| POST   | `/api/suppliers`                  | Create supplier                   |
| POST   | `/api/movements`                  | Record a stock movement           |
| GET    | `/api/movements/recent?days=14`   | Daily movement totals             |
| POST   | `/api/eoq/calculate`              | Run EOQ math on supplied params   |
| POST   | `/ai/forecast/run`                | Run Prophet/ARIMA/ensemble        |
| GET    | `/ai/forecast/portfolio`          | Portfolio-level forecast (cached) |
| POST   | `/ai/anomaly/run`                 | Run anomaly detection             |
| GET    | `/ai/anomaly/portfolio`           | Portfolio anomalies (cached)      |
| GET    | `/ai/eoq/sensitivity`             | 3D EOQ sensitivity surface        |

---

## ML Module

**Forecasting** (`app/ml/forecasting.py`):
- `forecast_with_prophet` — Prophet with weekly seasonality
- `forecast_with_arima` — ARIMA(1, 1, 1)
- `forecast_ensemble` — averages the two
- Graceful fallback to moving-average when libraries unavailable

**Anomaly detection** (`app/ml/anomaly.py`):
- `detect_anomalies_isoforest` — sklearn Isolation Forest
- `spc_zscore_analysis` — mean/sigma/UCL/LCL for SPC charts

Portfolio endpoints are cached for 1 hour to avoid repeated model fitting.

---

## UI Tour

1. **Landing** — `/` — animated marketing page with live KPIs, 3D background,
   movement chart, inventory mix, and Log in / Sign up.
2. **Login / Register** — `/auth/*` — corporate card with demo credentials.
3. **Dashboard** — `/` — KPI cards (stock health, AI savings YTD, reorder
   count), inventory mix, stock movement chart, reorder queue, top demand/sales,
   warehouse profile, ABC analysis, stock turnover, slow movers, 3D panel tilt.
4. **Inventory** — `/inventory` — searchable, filterable, paginated table with
   CSV export.
5. **Reorder alerts** — `/reorder-alerts` — severity-sorted cards with
   "Mark ordered" action.
6. **Suppliers** — `/suppliers` — cards with reliability and lead time.
7. **Purchase orders** — `/purchase-orders` — kanban board by status.
8. **Warehouses** — `/warehouses` — capacity tiles.
9. **Reports** — `/reports` — 5 tabs (Executive Summary, Warehouse Analytics,
   Procurement & Suppliers, Sales Performance, Inventory Health) with 15+
   interactive charts, filterable by warehouse/category/date range.
10. **EOQ calculator** — `/eoq-calculator` — live form, cost curve, per-product
    table, theme-aware datalabels.
11. **AI forecast** — `/ai/forecast` — product selector, model choice, Plotly
    chart with confidence intervals, portfolio snapshot.
12. **Anomaly detection** — `/ai/anomaly` — Isolation Forest + SPC control
    chart, portfolio table.
13. **Monitoring** — `/monitoring` — DB stats, ETL status, daily logins,
    warehouse health, Run ETL button (non-blocking).
14. **Settings** — `/settings` — per-account preferences, AI defaults, alert
    thresholds (admin/manager only).
15. **Help / Contact** — `/help`, `/contact` — FAQ and support form.

Dark/light theme toggle saved to localStorage. All pages have themed scrollbars,
GSAP entrance animations, and the Three.js 3D wave background.

---

## Tests

```bash
pip install pytest
pytest
```

Covers auth flow, role-based access, REST API, security helpers, ML smoke
tests, and service-layer validation.

---

## License

This codebase is part of an MCA mini-project. Use freely within your
organisation.
