# InventoryLogix — Inventory Logistics Optimization Dashboard

A full-stack Flask + PostgreSQL application for warehouse stock management with
**real-time CRUD**, **EOQ optimization**, **REST API**,
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
  `/api/eoq/calculate`, `/api/health`, plus the EOQ sensitivity endpoint.
  Consistent JSON envelope with success/error codes.
- **EOQ optimization** — per-product economic order quantity with a live cost
  curve chart and a 3D cost-sensitivity surface. The per-product EOQ table is
  cached (busted on product CRUD) to keep the page fast.
- **Data warehouse** — ETL pipeline populates `dim_product`, `dim_supplier`,
  `dim_date`, `fact_inventory_daily`, and `fact_movement_monthly`. Stock walk
  clamping ensures inventory accuracy. Warehouse monitoring dashboard at
  `/monitoring`.
- **Security** — CSP nonces on all inline scripts + import maps, per-request
  nonce generation, password hashing, parameterised SQL, rate limiting, audit
  logging, account lockout, secure session cookies, and soft-validated forms.
- **Performance** — cached context processor (60s), lazy-loaded Plotly (3.5MB
  only on pages that use it), dashboard queries batched (14→11), reports cache
  TTL 1 hour, dashboard cache TTL 5 min, Intelligence product list + EOQ table
  cached, ETL rebuilds non-blocking.
  Heavy report sections (category breakdown + KPIs, 30-day movement series,
  top SKUs) query the **star-schema fact tables** (`fact_movement_daily` +
  dimensions) instead of raw `movements` scans.
- **UI** — unified futuristic dark-mode design with glassmorphism panels, GSAP
  entrance animations, Three.js 3D wave + particle background, Chart.js /
  Plotly charts with theme-aware datalabels, SVG sparklines, dark/light theme
  toggle, and toast notifications.
- **Inventory filters** — category and warehouse are **multi-select checkbox
  dropdowns** (same pattern as Reports) with an **Apply** button (Enter in the
  search box applies too) and a **Reset** link. `sp_product_list` filters via
  `= ANY(string_to_array(…, ','))` — comma-separated multi-select, fully
  backward compatible with single values.
- **Session policy** — login sets **only a browser-session cookie** (no
  persistent remember-me cookie): closing the browser always ends the login
  and requires signing in again, for all roles.

---

## Project Structure

```
.
├── app/
│   ├── __init__.py              # Application factory + context processor
│   ├── extensions.py            # Flask-Limiter and other extensions
│   ├── models.py                # Flask-Login user model
│   ├── config/                  # Environment-driven configuration
│   │   └── settings.py          # Config classes (base/production/testing)
│   ├── database/
│   │   ├── schema.sql           # Operational tables + star schema + RLS
│   │   ├── procedures.sql       # 84+ stored procedures (all CRUD)
│   │   ├── triggers.sql         # 8 trigger functions (validation + audit)
│   │   ├── warehouse.sql        # SCD Type 2 dims + fact tables
│   │   ├── etl_procedures.sql   # ETL + monitoring procedures
│   │   ├── etl.py               # ETL pipeline + stock walk clamping
│   │   ├── seed.py              # Demo data seeding (DataCo / synthetic)
│   │   └── connection.py        # Pool management + lazy health-check + bootstrap
│   ├── monitoring/              # System alert generation + dedup
│   │   └── alerts.py            # ETL/backup/pool failure alerts
│   ├── repositories/            # SQL CRUD per entity
│   │   ├── product_repo.py      # products (via sp_product_list)
│   │   ├── movement_repo.py     # movements
│   │   ├── supplier_repo.py     # suppliers
│   │   ├── po_repo.py           # purchase orders
│   │   ├── warehouse_repo.py    # star-schema warehouse analytics
│   │   ├── user_repo.py         # users + sessions
│   │   ├── settings_repo.py     # per-user settings
│   │   ├── notification_repo.py # notifications
│   │   ├── monitoring_repo.py   # system alerts
│   │   └── audit_repo.py        # audit log
│   ├── services/                # Business logic
│   │   ├── auth_service.py      # Authentication + lockout + session tracking
│   │   ├── product_service.py   # Product validation + orchestration
│   │   ├── movement_service.py  # Movement recording
│   │   ├── supplier_service.py  # Supplier creation
│   │   ├── eoq_service.py       # EOQ table + sensitivity surface
│   │   ├── monitoring_service.py # System alert persistence + retention
│   │   ├── notification_service.py # Alert checks + bulk inserts
│   │   ├── settings_service.py  # Per-user settings
│   │   ├── dataset_service.py   # DataCo dataset import
│   │   └── mailer.py            # SMTP password reset emails
│   ├── routes/                  # Flask blueprints
│   │   ├── auth.py              # /auth/* (login, register, reset, logout)
│   │   ├── ui.py                # Main pages (dashboard, inventory, reports, …)
│   │   ├── api.py               # /api/* REST endpoints
│   │   └── ai.py                # /ai/* EOQ sensitivity
│   ├── security/                # Validators, CSP headers, roles
│   │   ├── validators.py        # Input validators (SKU, email, password, …)
│   │   ├── headers.py           # CSP + security header after_request
│   │   └── roles.py             # write_roles_required decorator
│   ├── utils/                   # Helpers
│   │   ├── cache.py             # Unified TTLCache + cache_bust_* hooks
│   │   └── helpers.py           # EOQ formula, format_money, …
│   ├── templates/               # Jinja2 templates
│   │   ├── base.html            # Shared layout + CDN scripts + theme init
│   │   ├── landing.html         # Public landing page
│   │   ├── auth/                # login / register / forgot / reset
│   │   ├── errors/              # 400 / 401 / 403 / 404 / 422 / 429 / 500
│   │   └── …                    # dashboard, inventory, reports, monitoring, …
│   └── static/
│       ├── css/
│       │   ├── style.css        # Main app styles (~3800 lines)
│       │   ├── landing.css      # Landing page + theme tokens
│       │   └── ai-features.css  # EOQ + shared feature styles
│       ├── js/
│       │   ├── auth-bg.js       # Three.js 3D background (all pages)
│       │   ├── dashboard-3d.js  # Dashboard panel tilt + chart animation
│       │   ├── saas-animations.js  # GSAP entrance animations
│       │   ├── ai-features.js   # EOQ calculator + shared UI helpers
│       │   ├── eoq.js           # EOQ calculator + cost curve chart
│       │   ├── main.js          # IntersectionObserver, toast, theme
│       │   └── landing.js       # Landing page animations
│       └── img/                 # favicon.svg, logo.svg
├── migrations/                  # Alembic migration system
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 001_initial.py
│       ├── 002_critical_fixes.py
│       └── 003_enable_rls.py
├── docs/                        # Documentation
│   ├── Testing.md               # Test plan + code + results
│   └── project-analysis/        # Academic reports (architecture, business, …)
├── tests/                       # pytest suite
│   ├── conftest.py              # Fixtures (app, client, auth_client)
│   ├── test_api.py              # REST API contract
│   ├── test_auth.py             # Auth flows
│   ├── test_cache.py            # TTLCache + bust hooks
│   ├── test_etl.py              # ETL pipeline / warehouse
│   ├── test_notifications.py    # Notification API
│   ├── test_reports_fact.py     # Reports fact-table endpoints
│   ├── test_roles.py            # Role-based access control
│   ├── test_security.py         # Validators, headers, rate limiting
│   └── test_services.py         # Service-layer validation
├── run.py                       # Entry point
├── migrate.py                   # Alembic helper CLI (migrate.py etl)
├── alembic.ini                  # Alembic config
├── render.yaml                  # Render Blueprint
├── requirements.txt
├── .env.example                 # Environment template
├── SUPABASE_SETUP.md            # Supabase deployment guide
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

- **Backups**: Render managed PostgreSQL provides daily backups + PITR;
  `system_backups` table tracks app-level backup metadata. Verify RPO/RTO
  expectations before production launch.
- **Known accepted tradeoffs**: `audit_log.target_id` is polymorphic (no FK —
  dangles after hard deletes, acceptable for audit history);
  `dim_product.supplier_id` is a bare INTEGER (SCD2 history table — an FK
  would break historical rows).

---

## Performance

| Area | Before | After |
|------|--------|-------|
| Context processor | 1 DB query per page load | Cached 60s (global key) |
| Plotly CDN | Loaded on every page (~3.5MB) | Lazy-loaded (dashboard, EOQ only) |
| Dashboard queries | 14 sequential | 11 (batched product agg + merged top demand/sales) |
| Dashboard cache | 60s TTL | 300s TTL (5 min) |
| Reports heavy sections | Raw `movements` scans | Star-schema fact tables (`fact_movement_daily` + dims) |
| Reports cache | 300s TTL | 3600s TTL (1 hour) — cold `/reports` ≈7s once, then ≈0.6s |
| Intelligence pages | 100-product query every load | Cached product list (`ai_product_list`) |
| EOQ calculator | Per-product table query every load | Cached (`eoq_table`) |
| ETL rebuild | Synchronous (10-60s block) | Non-blocking thread |
| DB connections | `SELECT 1` ping per request | Lazy health-check + stale-connection retry |
| Bootstrap | Full schema init on every first boot | Skipped when schema exists (1 `SELECT`) |

---

## Security

- **CSP nonces** — per-request nonces on all inline scripts + import maps; no
  `unsafe-inline` for scripts.
- **Account lockout** — 5 failed attempts → 15 minute lock with threading lock.
- **Session cookies** — `Secure`, `HttpOnly`, `SameSite=Lax` by default;
  `SESSION_COOKIE_SECURE` true in production. **No persistent remember-me
  cookie**: login sets only the browser-session cookie, so closing the
  browser always ends the session and re-opening requires re-login.
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
`model_monitoring_alerts`, `user_settings`, `etl_state`

### Stored procedures (84+)
All CRUD goes through `sp_*` functions to prevent SQL injection. Examples:
`sp_product_list`, `sp_movement_create`, `sp_po_update_status`,
`sp_settings_upsert_batch`.

### Triggers
- `trg_validate_movement` — validates product FK, prevents negative stock on
  OUT/ADJUSTMENT. (SKU is read from `products`, not stored on `movements`.)
- `trg_audit_*` — audit log triggers on products, suppliers, movements, POs.

### Data warehouse (Alembic-managed)
- `dim_product` (SCD Type 2), `dim_supplier`, `dim_date`
- `fact_inventory_daily`, `fact_movement_monthly`
- ETL pipeline: `python migrate.py etl` or `/monitoring` → Run ETL

---

## Background job worker (optional)

By default, background work (warehouse ETL, backup restore, scheduled audit
reports) runs on per-request daemon threads. Setting `JOB_QUEUE_ENABLED=1`
switches those routes to a persistent PostgreSQL job queue (`job_queue` table):

```bash
# .env
JOB_QUEUE_ENABLED=1
```

With the flag on, an in-process worker thread starts automatically with the
app (polls every 5 s). For a dedicated worker process instead, run:

```bash
python -m app.worker
```

**⚠️ pg_cron hosts:** if the `job-queue-processor` schedule exists, unschedule
it when the flag is on — it only MARKS jobs `running`, it never executes them:

```sql
SELECT cron.unschedule('job-queue-processor');
```

If it is left scheduled, rows it marks `running` sit until the worker's
stale-requeue rescues them after 10 minutes. The `job-queue-cleanup` and
backup-enqueue schedules stay.

**Stale jobs:** a job stuck `running` for more than 10 minutes (killed worker,
OOM, deploy) is requeued on the next tick (`attempts + 1`) or moved to `dead`
once `max_attempts` is reached. Unset the flag + restart to return to the
legacy threading behavior (stray `pending` rows are inert).

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
| GET    | `/ai/eoq/sensitivity`             | 3D EOQ sensitivity surface        |

---

## UI Tour

1. **Landing** — `/` — animated marketing page with live KPIs, 3D background,
   movement chart, inventory mix, and Log in / Sign up.
2. **Login / Register** — `/auth/*` — corporate card with demo credentials.
3. **Dashboard** — `/` — KPI cards (stock health, AI savings YTD, reorder
   count), inventory mix, stock movement chart, reorder queue, top demand/sales,
   warehouse profile, ABC analysis, stock turnover, slow movers, 3D panel tilt.
4. **Inventory** — `/inventory` — searchable, paginated table with **multi-select
   category/warehouse filters**, single-select stock status, CSV export, Apply /
   Reset controls.
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
11. **Monitoring** — `/monitoring` — DB stats, ETL status, daily logins,
    warehouse health, Run ETL button (non-blocking).
12. **Settings** — `/settings` — per-account preferences, recommendation &
    reorder defaults, alert thresholds (admin/manager only).
13. **Help / Contact** — `/help`, `/contact` — FAQ and support form.

Dark/light theme toggle saved to localStorage. All pages have themed scrollbars,
GSAP entrance animations, and the Three.js 3D wave background.

---

## Tests
```bash
pip install pytest
pytest
```
Covers auth flow, role-based access, REST API, security helpers,
service-layer validation, caching, ETL, and the reports fact-table endpoints
(`tests/test_reports_fact.py` — verifies 200 OK, fact-table SQL execution,
and dimension-table joins when filters are applied).


## Known Limitations
- **ETL watermark semantics (DB-005/006):** stages commit individually with
  idempotent `ON CONFLICT DO NOTHING` reloads, so a failed run replays safely.
  A full rebuild can show one cycle of cross-fact skew that self-heals on the
  next run (`_validate_warehouse_consistency` is the backstop). Intentional.
- **Per-process login lockout (DB-007):** failed-login counters live in process
  memory, so the threshold multiplies per worker. Keep `WORKERS=1` (current
  Render setup); a shared store (Redis or DB table) is a follow-up.
- **Accepted as-is (DB-015/016):** ETL state keys are negligible in size; the
  seed-time trigger disable is dev-only and wrapped in `try/finally`.
- **Cache invalidation granularity (DB-017):** `cache_bust_products()` clears
  five caches — correctness-safe (cold reads only), but a keyed invalidation
  scheme is a perf follow-up.
- **Backups (DB-018):** rely on managed Postgres daily backups + PITR — enable
  PITR and run a quarterly restore test before any production data matters.
- **Timezones (DB-019):** all app code uses naive UTC timestamps (`_utcnow()`);
  set `TZ=UTC` in production. A mass `TIMESTAMPTZ` migration is deferred.
- **Immutable SKUs (DB-020):** SKU is the warehouse key for `dim_product` and
  has no update path; add `product_id` to `dim_product` if SKUs ever become
  mutable.
- **Soft delete (GAP-020 phases 1+2):** soft-deleted movements/POs are hidden
  from list views AND excluded from analytics/dashboard/reports/ETL. Historical
  fact-table rows retain pre-phase-2 contributions (ETL is incremental).

### Changelog
- **2026-10-18 — Feature removal (forecast/anomaly):** Demand Forecasting and
  Anomaly Detection were removed end-to-end (routes, services, ML modules,
  templates, JS/CSS, tests, requirements). The seven feature tables were
  dropped via Alembic migration `20261018_drop_forecast_tables`. The EOQ
  calculator and the system-alert backbone (ETL/backup/pool failure alerts)
  remain.
- **2026-09-25 — DB integrity fixes (D-1…D-8):** atomic `sp_movement_record`
  (row lock + stock guard, no lost updates or negative stock), PO state machine
  `sp_po_transition` (valid transitions only, idempotent receive, stock/`on_order`
  effects), DB-level unique SKU constraint with duplicate-create mapping to
  `ProductError` (no more 500s), soft supplier delete with `deleted_at IS NULL`
  visibility filters, `ON CONFLICT` upserts + dedup unique indexes for
  `anomaly_log`/`forecast_cache`, partial product-list index, and the stale-session
  cleanup trigger attached on `user_sessions`. Shipped in both the SQL files and
  Alembic migration `20260925_db_integrity_fixes` (dual-apply), covered by
  `tests/test_db_integrity_fixes.py`.


## License
This codebase is part of an MCA mini-project. Use freely within your
organisation.
