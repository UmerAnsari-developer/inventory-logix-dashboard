# InventoryLogix — Inventory Logistics Optimization Dashboard

A full-stack Flask + PostgreSQL application for warehouse stock management with
**real-time CRUD**, **AI demand forecasting**, **anomaly detection**, **REST API**,
and an **auth-protected** UI built on a clean, modern dashboard design.

The application preserves a clean, modern look-and-feel and layers in
the advanced features (forecast, anomaly, 3D EOQ surface, dark mode, AI banner,
toast notifications, and sidebar grouping).

---

## Highlights

- **Authentication** — Flask-Login with hashed passwords, role-based access
  (`admin`, `manager`, `viewer`), CSRF protection via Flask-WTF, session
  fingerprinting, and rate-limited login/register endpoints. Self-registration
  always creates a **viewer** account; write access (products, suppliers,
  movements, purchase orders, settings) is restricted to `admin`/`manager`.
- **Database** — PostgreSQL with normalised schema (`users`, `suppliers`,
  `products`, `movements`, `purchase_orders`, `audit_log`, `forecast_cache`,
  `anomaly_log`). Schema bootstrap + data seeding run automatically on first
  start.
- **Real data** — the app is seeded from the **DataCo SMART SUPPLY CHAIN**
  dataset (180,000+ real transactions): 118 products with real demand /
  ordering / holding costs (used for EOQ) and up to 150 suppliers.
- **REST API** — `/api/products`, `/api/suppliers`, `/api/movements`,
  `/api/eoq/calculate`, `/api/health`, plus AI endpoints
  (`/ai/forecast/run`, `/ai/anomaly/run`, `/ai/eoq/sensitivity`). Consistent
  JSON envelope with success/error codes.
- **ML module** — Prophet, ARIMA, and ensemble forecasting with graceful
  fallback to a moving-average model when the optional libraries are
  unavailable. Anomaly detection uses Isolation Forest plus an SPC z-score
  control chart. All results are cached in `forecast_cache` / `anomaly_log`.
- **Security** — CSP / X-Frame-Options / Referrer-Policy / Permissions-Policy
  response headers, password hashing via Werkzeug, parameterised SQL via
  psycopg2, rate limiting on auth and write endpoints, audit log writes for
  every mutating call, soft-validated forms, input length limits, and a clear
  error page hierarchy.
- **UI** — modern dashboard design preserved, with dark-mode toggle, AI banner on
  the dashboard, AI forecast strip, AI savings KPI, sidebar grouping
  (Workspace / Analytics & AI / Account), and toast notifications.

---

## Project Structure

```
.
├── app/
│   ├── __init__.py            # Application factory
│   ├── config/                # Environment-driven configuration classes
│   ├── database/              # schema.sql + seed.py + connection helpers
│   ├── repositories/          # SQL CRUD per entity (one module per table)
│   ├── services/              # Business logic (auth, products, dataset, …)
│   ├── routes/                # Flask blueprints (auth, ui, api, ai)
│   ├── ml/                    # Forecasting + anomaly detection models
│   ├── security/              # Validators, headers + role decorators
│   ├── utils/                 # Helpers (EOQ formula, JSON envelope, …)
│   ├── templates/             # Jinja2 templates
│   │   ├── base.html
│   │   ├── auth/              # login / register
│   │   ├── ai/                # forecast / anomaly
│   │   └── errors/            # 400 / 401 / 403 / 404 / 422 / 429 / 500
│   └── static/                # CSS / JS (style.css preserved, AI overlays added)
├── datasets/                  # DataCoSupplyChainDataset.csv (not in git)
├── tests/                     # pytest suite
├── scripts/                   # smoke_test.py — end-to-end route verification
├── run.py                     # Entry point
├── requirements.txt
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

Copy `.env.example` to `.env` (or export the variables in your shell):

```
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/inventory_db
SECRET_KEY=replace-this-with-a-random-50-char-string
FLASK_ENV=development
```

### 3. Initialise the database

The schema is applied and seeded automatically on first run, but you can also
do it explicitly:

```bash
flask --app run.py init-db
flask --app run.py seed-db --force
```

The seeder loads from `datasets/DataCoSupplyChainDataset.csv`. Place the
dataset file there first (it is gitignored, so you must add it locally):

```
datasets/
└── DataCoSupplyChainDataset.csv
```

On a fresh database this creates:

- 3 demo users (admin / manager / viewer)
- up to 150 suppliers derived from the DataCo dataset
- 118 products with real demand, ordering and holding costs (real EOQ values)
  and deterministic, varied stock levels
- If the dataset file is missing, seeding is deferred with a log warning and
  the app still boots (the schema is applied regardless).

### 4. Run the Flask app

```bash
python run.py
# open http://localhost:5000
```

Demo credentials:

| User    | Password    | Role    |
|---------|-------------|---------|
| admin   | Admin@123   | admin   |
| manager | Manager@123 | manager |
| viewer  | Viewer@123  | viewer  |

---

## REST API

All endpoints return a consistent JSON envelope:

```json
{ "success": true, "data": {}, "message": "..." }
```

Auth is required for everything except `/api/health` and `/auth/*`. Include
the Flask session cookie; CSRF is enforced on write requests.

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
| GET    | `/ai/forecast/portfolio`          | Portfolio-level forecast snapshot |
| POST   | `/ai/anomaly/run`                 | Run anomaly detection             |
| GET    | `/ai/anomaly/portfolio`           | Portfolio anomalies               |
| GET    | `/ai/eoq/sensitivity`             | 3D EOQ sensitivity surface        |

---

## Security

- All write endpoints require an authenticated session.
- Role-based access: `viewer` is read-only. Routes that create / edit / delete
  products, suppliers, movements or purchase orders, and the settings page,
  are restricted to `admin` and `manager` (see `app/security/roles.py`).
- CSRF tokens are auto-injected into every Jinja form via `csrf_token()` and
  verified by Flask-WTF on POST/PUT/DELETE.
- Rate limits (Flask-Limiter) on `/auth/login` (10/min) and `/auth/register`
  (5/min); API write endpoints (30/min); movement endpoint (60/min).
- Parameterised SQL via psycopg2 (`%s` placeholders) — no string concatenation
  anywhere.
- Werkzeug password hashing (PBKDF2-SHA256 by default, with the `scrypt`
  fallback available in newer Werkzeug versions).
- HTTP security headers (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, `Permissions-Policy`, `Content-Security-Policy`,
  optional HSTS).
- Per-request audit log entries for login, registration, product changes,
  movement recording, and supplier CRUD.
- Centralised error handling renders user-safe pages for 400, 401, 403, 404,
  422, 429, 500. Internal tracebacks are never exposed.

---

## ML Module

`app/ml/forecasting.py` exposes three forecast flavours:

- `forecast_with_prophet(history, horizon)` — Prophet with weekly seasonality.
- `forecast_with_arima(history, horizon)` — statsmodels ARIMA(1, 1, 1).
- `forecast_ensemble(history, horizon)` — averages the two outputs.

Each returns:

```json
{
  "predictions": [...], "lower": [...], "upper": [...],
  "history": [...], "baseline": 12.4,
  "accuracy": 91.3, "model": "prophet",
  "dates": ["2026-08-13", ...]
}
```

`app/ml/anomaly.py` exposes:

- `detect_anomalies_isoforest(series, contamination=0.05)` — sklearn Isolation
  Forest with a z-score fallback.
- `spc_zscore_analysis(series, limit=3.0)` — mean / sigma / UCL / LCL for SPC
  charting.

Both are wired through `services/forecast_service.py` and
`services/anomaly_service.py`, which persist results to `forecast_cache` and
`anomaly_log`.

---

## Tests

```bash
pip install pytest
pytest
```

The suite (89 tests) covers:

- Auth flow (login, registration validation, protected routes)
- Role-based access control (viewer is read-only, registration is always
  viewer, admin/manager can write)
- REST API (health, products, EOQ validation)
- Security helpers + HTTP headers
- ML helpers (forecast + anomaly smoke tests)
- Service-layer validation (product + movement)

---

## UI Tour

1. **Landing** — `/` — animated, analytics-driven marketing page referencing
   the real DataCo dataset, with live KPIs, a 14-day movement chart and
   inventory mix, plus **Log in** / **Sign up** options. Authenticated users
   skip straight to the dashboard.
2. **Login** — `/auth/login` — corporate InventoryLogix card with seeded demo
   credentials under a `<details>` block.
3. **Dashboard** — `/` — KPI cards (incl. AI savings), AI recommendation
   banner, AI forecast strip, inventory mix, reorder queue.
4. **Inventory** — `/inventory` — searchable, filterable table with
   pagination and CSV export.
5. **Reorder queue** — `/reorder-alerts` — severity-sorted cards with
   "Mark ordered" action (admin/manager only).
6. **Suppliers** — `/suppliers` — cards with reliability and lead time.
7. **Purchase orders** — `/purchase-orders` — kanban board by status.
8. **Warehouses** — `/warehouses` — capacity tiles.
9. **Reports** — `/reports` — category breakdown + insights.
10. **EOQ calculator** — `/eoq-calculator` — live EOQ form, cost curve,
    3D sensitivity surface, per-product table.
11. **AI forecast** — `/ai/forecast` — product + horizon + model selector,
    Plotly history/projection/confidence chart, KPIs, portfolio snapshot.
12. **Anomaly detection** — `/ai/anomaly` — Isolation Forest + SPC chart.
13. **Settings** — `/settings` — per-account preferences, AI defaults, alert
    thresholds, and integrations (admin/manager only).
14. **Dark mode** — saved preference (theme toggle was removed from the
    sidebar; it is set under Settings).

All pages are viewable by every role; create / edit / delete actions and the
Settings page are hidden for `viewer` accounts.

---

## Troubleshooting

- **`psycopg2.OperationalError`** — make sure PostgreSQL is running and the
  credentials in `.env` are correct. `python -c "import psycopg2; psycopg2.connect(...)"` 
  is a quick way to verify.
- **`ModuleNotFoundError: prophet`** — Prophet requires a working
  `cmdstanpy` install. The app falls back to a moving-average forecast if
  Prophet is unavailable, so this is non-fatal.
- **Login keeps saying "Invalid"** — credentials may not be seeded. Run
  `flask --app run.py seed-db --force`.
- **Empty inventory / no products** — the `datasets/DataCoSupplyChainDataset.csv`
  file is missing (it is gitignored). Add it and run `flask --app run.py
  seed-db --force`. The app boots fine without it; pages simply have no
  seeded data.

---

## License

This codebase is part of an MCA mini-project. Use freely within your
organisation.
