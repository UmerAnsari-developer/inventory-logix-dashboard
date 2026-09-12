# InventoryLogix — Interview Preparation Q&A

> Evidence-based answers drawn from actual source code. Every claim below maps
> to a file, function, or configuration value in the repository.

---

## Table of Contents

1. [Client Discovery Questions](#1-client-discovery-questions)
2. [Sales / Objection Handling](#2-sales--objection-handling)
3. [Technical Interview Questions](#3-technical-interview-questions)
4. [Business Interview Questions](#4-business-interview-questions)
5. [Viva Voce Questions](#5-viva-voce-questions)
6. [Scenario-Based Questions](#6-scenario-based-questions)

---

## 1. Client Discovery Questions

These simulate stakeholder interviews where you must understand requirements,
validate assumptions, and map features to business outcomes.

### Q1: "Who are the primary and secondary users of InventoryLogix?"

**Answer:**
Primary users are **supply chain analysts** who forecast demand, detect anomalies,
and optimize inventory across warehouses. Secondary users include warehouse
managers (daily stock/reorder), procurement leads (supplier/PO management), and
admins (settings, user management). The `viewer` role is read-only; self-
registration always creates a viewer — an admin must promote.

**Evidence:** `PRODUCT.md` lines 12–17; `app/services/auth_service.py` line 54
硬codes `"viewer"` as the default role on registration.

**Follow-up:** "How do you prevent privilege escalation through self-registration?"
→ Self-registration hardcodes `"viewer"` in `AuthService.register()` regardless
of what the caller passes. Only the admin can promote via settings.

---

### Q2: "What problem does InventoryLogix solve?"

**Answer:**
It unifies real transaction data (DataCo SMART SUPPLY CHAIN, 180K+ rows) with
ML forecasting, anomaly detection, and EOQ optimization into a single dashboard.
The goal is fewer stockouts, lower carrying cost, forecast accuracy >90%, and
measurable EOQ-driven savings visible on the dashboard.

**Evidence:** `PRODUCT.md` line 21; success metrics on line 22.

---

### Q3: "How is the data sourced and seeded?"

**Answer:**
The `seed.py` module reads from a local CSV file (DataCo dataset, 180K+
transactions). When the CSV is absent, a **deterministic synthetic catalogue**
is generated so the application is always runnable. The seeding runs
automatically on first startup via `bootstrap_database()` which calls
`init_schema()` → `seed_database()` → `etl_database()`.

**Evidence:** `app/database/connection.py` lines 179–195 (`bootstrap_database`);
`app/database/seed.py` referenced in `connection.py` line 163.

---

### Q4: "What does the daily workflow look like for an operations manager?"

**Answer:**
Daily stock review → anomaly check → forecast review → EOQ recalc → PO creation
→ receipt logging → dashboard KPI refresh. Each screen in the app maps to one
of these steps: Dashboard for KPIs, Reorder Alerts for stock review, AI
Forecast for demand signals, EOQ Calculator for order quantities, Purchase
Orders for the kanban workflow.

**Evidence:** `PRODUCT.md` lines 31–33 ("Workflows" section).

---

### Q5: "What is the differentiating feature compared to competitors?"

**Answer:**
The integrated EOQ + 3D sensitivity surfaces — a live Economic Order Quantity
calculator that visualizes cost curves in 3D (ordering cost vs holding cost vs
total cost) per product, paired with real transaction history and ML forecasts.
No other open-stack Flask application combines real dataset grounding, ML
demand forecasting, anomaly detection, and interactive EOQ optimization.

**Evidence:** `PRODUCT.md` lines 27–28 ("Positioning"); `app/routes/ai.py`
lines 121–133 (`/ai/eoq/sensitivity` endpoint); `app/static/js/eoq.js` for
Three.js 3D surface rendering.

---

### Q6: "What happens when the ML libraries aren't installed?"

**Answer:**
The system degrades gracefully. `forecasting.py` tries `import prophet` at
module level; if it fails, `_HAS_PROPHET = False`. Similarly for ARIMA
(`_HAS_ARIMA`). When either is unavailable, the code falls back to a
**deterministic moving-average forecast** with 95% confidence intervals computed
from historical standard deviation. The user sees results either way — they
just see the model label change to `"moving_average"`.

**Evidence:** `app/ml/forecasting.py` lines 17–27 (try/except imports); lines
30–58 (`_moving_average_forecast`); line 63 (`if not _HAS_PROPHET`).

---

### Q7: "How do you ensure security by default?"

**Answer:**
Five layers: (1) All SQL uses parameterized queries via stored procedures
(`sp_*` functions) — no raw string interpolation. (2) CSP nonces are generated
per-request for all inline scripts — no `unsafe-inline`. (3) Account lockout:
5 failed attempts → 15-minute lock via an in-memory tracker with thread lock.
(4) Rate limiting via Flask-Limiter: auth 10/min, API writes 30/min,
movements 60/min. (5) Every mutating call writes to `audit_log`.

**Evidence:** `app/security/headers.py` lines 18–43 (nonce + CSP); `app/services/auth_service.py`
lines 24–29 (`MAX_FAILED_ATTEMPTS`, `_lockout_mutex`); `app/routes/api.py`
`@limiter.limit` decorators.

---

### Q8: "Can the system handle multiple warehouses?"

**Answer:**
Yes. The `products` table has a `warehouse` column (default `'WH-Pune'`). The
ETL pipeline parses warehouse names into code/city/region tuples and builds a
`dim_warehouse` dimension table. The dashboard, reports, and inventory pages
all support warehouse-based filtering. The warehouse monitoring page at
`/monitoring` shows per-warehouse health.

**Evidence:** `app/database/etl.py` lines 48–64 (`_parse_warehouse`); lines
122–160 (building `dim_warehouse`); `app/database/schema.sql` line 45
(`warehouse VARCHAR(80) DEFAULT 'WH-Pune'`).

---

### Q9: "How does the ETL pipeline work?"

**Answer:**
The ETL builds a star-schema warehouse from operational tables. It uses a
**high-water mark** pattern: `etl_state['last_movement_id']` tracks the last
processed movement. On incremental runs, only movements above the watermark
are processed. For full rebuilds, all tables are truncated and rebuilt. The
pipeline constructs `dim_date`, `dim_warehouse`, `dim_product`, `dim_supplier`,
`fact_movement_daily`, and `fact_inventory_daily` (via backward stock walk). A
stock walk clamp ensures negative stock values are set to 0 with a warning.

**Evidence:** `app/database/etl.py` lines 328–415 (`run_etl`); lines 254–325
(`_build_inventory_facts` with backward walk + clamping at line 308–309).

---

### Q10: "What is the deployment story?"

**Answer:**
One-click deploy via Render Blueprint. The `render.yaml` defines a free-tier
PostgreSQL database and a Python web service. Gunicorn runs with 1 worker, 2
threads, 120s timeout. `DATABASE_URL` is auto-wired. On first boot, schema
is applied and demo data seeded. `autoDeploy: true` redeploys on every push to
`main`. The health check hits `/api/health`.

**Evidence:** `render.yaml` lines 18–49; `startCommand: gunicorn run:app --workers 1 --threads 2`.

---

## 2. Sales / Objection Handling

### Q1: "Why Flask? Why not Django or a modern JS framework?"

**Answer:**
Flask gives us the **application factory pattern** (`create_app()` in
`__init__.py`) which is ideal for testability — we can create isolated app
instances for tests with `TestingConfig`. The ORM is bypassed entirely in favor
of raw SQL stored procedures (84+), which gives us full control over query
plans and makes the database the single source of truth. A JS framework would
add a build pipeline and API boundary that isn't needed when Jinja2 templates
render server-side. The result: **zero npm install, zero webpack, zero
hydration bugs**.

**Evidence:** `app/__init__.py` lines 31–85 (`create_app` factory); `app/repositories/product_repo.py`
calls `sp_product_list(...)` directly.

---

### Q2: "The ML models seem basic — Prophet, ARIMA, Isolation Forest. Is this enough?"

**Answer:**
For an inventory optimization use case, these are the industry-standard tools.
Prophet handles weekly seasonality (the dominant pattern in retail stock
movements). ARIMA(1,1,1) captures short-term autoregressive trends. The
**ensemble** averages both predictions, which empirically reduces variance.
Isolation Forest is the go-to for unsupervised anomaly detection on tabular
data. The SPC z-score chart provides a complementary statistical process
control view. The key design choice is **graceful degradation**: if libraries
aren't installed, moving-average and z-score fallbacks still produce results.

**Evidence:** `app/ml/forecasting.py` lines 61–97 (Prophet), 100–140 (ARIMA),
143–158 (ensemble); `app/ml/anomaly.py` lines 24–81 (Isolation Forest + z-score
fallback).

---

### Q3: "Why parameterized stored procedures instead of an ORM?"

**Answer:**
Two reasons: (1) **SQL injection prevention** — every user input goes through
`%s` placeholders in psycopg2, and the stored procedure is the only code that
touches the database. There's no ORM layer that could accidentally interpolate
raw strings. (2) **Performance** — stored procedures run inside the PostgreSQL
process, avoiding network round-trips for multi-step operations. The 84+
procedures encapsulate complex logic like `sp_product_list` which handles
search, filtering, and pagination in a single call.

**Evidence:** `app/repositories/product_repo.py` line 51: `SELECT * FROM sp_product_list(%s, %s, %s, %s, %s, %s)`.

---

### Q4: "How does the app handle concurrency? Can two users edit the same product?"

**Answer:**
The `products` table supports `SELECT ... FOR UPDATE` locking via
`ProductRepository.find_for_update()`. The movement recording uses this lock
to prevent concurrent overdraw: when a movement is created, the product row
is locked, current stock is verified, and then stock is updated — all within
the same transaction. The `trg_validate_movement` trigger also prevents
negative stock on OUT/ADJUSTMENT movements.

**Evidence:** `app/repositories/product_repo.py` lines 111–115
(`find_for_update` with `FOR UPDATE`); `app/database/triggers.sql` referenced
in `AGENTS.md`.

---

### Q5: "What about scalability? Can this handle a real enterprise?"

**Answer:**
The architecture is horizontally scalable. The connection pool is thread-safe
(`ThreadedConnectionPool` with 20 connections, keyed per-config). The ETL
supports incremental runs (only processes movements above a high-water mark).
Portfolio-level AI endpoints have a 1-hour TTL cache to avoid repeated model
fitting. Context processor queries are cached 60 seconds. For enterprise
scale, you'd add a load balancer, increase pool size, and move the cache to
Redis — but the code structure (factory pattern, blueprint registration,
separate repositories) supports this without refactoring.

**Evidence:** `app/database/connection.py` lines 33–69 (pool management); `app/routes/ai.py`
line 20 (`TTLCache(ttl=3600)`); `AGENTS.md` performance section.

---

## 3. Technical Interview Questions

### Q1: Explain the application factory pattern in `create_app()`.

**Answer:**
`create_app()` in `app/__init__.py` is the factory. It:
1. Loads the config class via `get_config(config_name)` (env-based: dev/prod/test).
2. Creates a `Flask` instance with explicit template/static folders.
3. Registers extensions (CSRF, limiter, login manager).
4. Registers 4 blueprints: `auth_bp`, `ui_bp`, `api_bp`, `ai_bp`.
5. Injects a context processor that computes `reorder_count` and loads settings.
6. Registers error handlers for 400–500 status codes.
7. Runs first-run bootstrap (schema + seed + ETL) guarded by a `_BOOTSTRAPPED`
   flag with a thread lock so the debug reloader doesn't double-initialize.

**Evidence:** `app/__init__.py` lines 31–85.

**Follow-up:** "Why the `_BOOTSTRAPPED` guard?"
→ The Flask debug reloader imports the module in both the parent and child
process. Without the guard, schema would be applied twice on every restart.

---

### Q2: How does the connection pooling work?

**Answer:**
A module-level dict `_POOLS` maps a string key (derived from sorted config
params) to a `psycopg2.pool.ThreadedConnectionPool` (min 1, max 20 connections).
On first request, `_get_pool()` creates the pool. `get_connection()` draws a
connection from the pool and stores it on Flask's `g` object. At request end,
`close_connection()` returns it to the pool (or closes it if the pool is full).
Connections use `connect_timeout=15`, keepalives every 300s idle, and
`RealDictCursor` for dict-style row access.

**Evidence:** `app/database/connection.py` lines 31–131.

---

### Q3: What is the CSP nonce strategy?

**Answer:**
On every request, `_set_nonce()` (a `before_request` hook) generates a random
24-byte URL-safe token via `secrets.token_urlsafe(24)` and stores it on `g`.
A context processor injects `csp_nonce` into every template. The `after_request`
hook builds the CSP header: `script-src 'self' 'nonce-{token}' ...`. Inline
scripts use `<script nonce="{{ csp_nonce }}">`. This eliminates the need for
`unsafe-inline` while still allowing inline scripts — a strict but flexible
policy.

**Evidence:** `app/security/headers.py` lines 17–43.

---

### Q4: How does the backward stock walk in ETL work?

**Answer:**
`_build_inventory_facts()` reconstructs historical stock levels by walking
**backwards** from today's `current_stock`. For each product, it starts with
the current stock, then for each day going backward in time, it subtracts
the net movement (IN adds, OUT subtracts). If stock goes negative, it's
clamped to 0 with a warning log. This means the stored stock_on_hand for
day N only depends on movements after day N — making the walk idempotent
for incremental runs.

**Evidence:** `app/database/etl.py` lines 254–325; clamping at lines 307–309.

---

### Q5: Explain the EOQ formula implementation.

**Answer:**
`calculate_eoq()` in `app/utils/helpers.py` implements the classic formula:

```
EOQ = sqrt((2 * D * S) / H)
```

Where D = annual demand rate, S = ordering cost per order, H = holding cost
per unit per year. The total cost is `(D/Q)*S + (Q/2)*H`. The EOQ service
also builds a **sensitivity surface** by varying demand (50%–150%) and ordering
cost (50%–200%) in a grid, computing total cost at each point for 3D
visualization via Three.js.

**Evidence:** `app/services/eoq_service.py` lines 66–80 (`sensitivity_surface`);
`app/routes/api.py` lines 279–299 (`/api/eoq/calculate`).

---

### Q6: How does the anomaly detection decide between Isolation Forest and z-score?

**Answer:**
In `detect_anomalies_isoforest()`, the code first checks `_HAS_SKLEARN` and
whether there are at least 14 data points. If both are true, it fits an
`IsolationForest(contamination=0.05, n_estimators=80)` model, and any point
with prediction `-1` is flagged. If the Isolation Forest produces no anomalies,
or if sklearn is unavailable, it falls back to z-score analysis: points with
`|z| >= 3.0` are flagged. Results are sorted by absolute z-score descending,
capped at 25 anomalies.

**Evidence:** `app/ml/anomaly.py` lines 24–81.

---

### Q7: What caching strategy is used throughout the app?

**Answer:**
A custom `TTLCache` (in `app/utils/cache.py`) with configurable TTL and max
entries. Usage: dashboard live KPIs (short TTL), API product list (parameter-
keyed), AI portfolio endpoints (1-hour TTL to avoid repeated model fitting),
report data (300s TTL — 10x improvement over 30s). Cache busting functions
(`cache_bust_products`, `cache_bust_movements`, etc.) are called on every
write operation.

**Evidence:** `app/routes/ai.py` line 20 (`TTLCache(ttl=3600, max_entries=10)`);
`app/routes/api.py` line 119 (`api_cache.get_or_set`); `AGENTS.md` performance
table.

---

### Q8: How does the audit log work?

**Answer:**
Every mutating operation calls `AuditRepository.record()` with user_id,
action type, target_type, target_id, and optional detail dict. This is called
from service methods (auth, products, movements) and API routes. The audit
log table captures the user, action, timestamp, target entity, and IP address.
Database triggers (`trg_audit_*`) also fire on product, supplier, movement,
and PO changes, providing a double layer of audit coverage.

**Evidence:** `app/routes/api.py` lines 173–175 (API audit calls); `AGENTS.md`
"Triggers" section.

---

### Q9: How does the session management work?

**Answer:**
Flask-Login manages sessions with `remember=True` and a 7-day remember cookie.
Sessions are `HttpOnly`, `SameSite=Lax`, and `Secure` in production. The
`PERMANENT_SESSION_LIFETIME` is 8 hours. On login, `UserRepository.record_login()`
updates `last_login` and `UserRepository.create_session()` stores a session
token for tracking. Failed logins are tracked in-memory with a thread-safe
dict (`_failed_logins`) protected by `_lockout_mutex`.

**Evidence:** `app/config/settings.py` lines 19–26; `app/services/auth_service.py`
lines 88–96.

---

### Q10: Explain the 3D EOQ sensitivity surface rendering.

**Answer:**
The backend (`EOQService.sensitivity_surface()`) generates a grid of total
cost values: demands at 50%/75%/100%/125%/150% of base, ordering costs at
50%/100%/150%/200%. The frontend in `eoq.js` receives `{x, y, z}` arrays and
renders a Three.js surface mesh. The user can rotate, zoom, and hover over the
surface to see how total cost varies with both input parameters — making the
cost trade-off intuitive.

**Evidence:** `app/services/eoq_service.py` lines 66–80; `app/routes/ai.py`
lines 121–133 (`/ai/eoq/sensitivity`).

---

### Q11: How are errors handled across the application?

**Answer:**
Three layers: (1) Service methods raise domain exceptions (`AuthError`,
`ValueError`). (2) Routes catch exceptions and return consistent JSON via
`api_error(code, message, status)` or render error templates. (3) A fallback
error page is hardcoded in `__init__.py` that never touches the database —
ensuring even a broken DB connection returns a user-safe page. Error pages
exist for 400, 401, 403, 404, 422, 429, and 500.

**Evidence:** `app/__init__.py` lines 192–256 (error handlers + fallback);
`app/routes/api.py` line 172 (`api_error`).

---

### Q12: How does the password reset flow work?

**Answer:**
1. User submits email → `request_password_reset()` validates the email, looks
   up the user, generates a `secrets.token_urlsafe(48)` token, hashes it with
   SHA-256, stores the hash in `reset_tokens` with a TTL (default 5 minutes).
2. If SMTP is configured, a branded HTML email is sent via `Mailer`. If not,
   the reset link is shown directly on the confirmation page (dev fallback).
3. User clicks link → `reset_password()` validates the token hash, checks
   expiry and `used` flag, applies the new password, and purges all tokens
   for that user.

**Evidence:** `app/services/auth_service.py` lines 98–178.

---

### Q13: What database triggers exist and what do they do?

**Answer:**
8 trigger functions in `triggers.sql`:
- `trg_validate_movement` — auto-populates `sku` from `product_id`, validates
  FK relationships, and prevents negative stock on OUT/ADJUSTMENT movements.
- `trg_audit_*` — audit log triggers on products, suppliers, movements, and
  purchase orders that fire on INSERT/UPDATE/DELETE.

**Evidence:** `AGENTS.md` "Triggers" section; `app/database/triggers.sql`.

---

### Q14: How does the rate limiting work?

**Answer:**
Flask-Limiter with `memory://` storage (default). Specific limits:
- Auth endpoints: 10/min login, 5/min register
- API writes (products, suppliers): 30/min
- Movements: 60/min
- Product listing reads: 120/min
- AI endpoints: 30/min

In production, `RATELIMIT_STORAGE_URI` can be pointed to Redis for distributed
rate limiting across workers.

**Evidence:** `app/routes/api.py` `@limiter.limit` decorators; `app/config/settings.py`
line 40.

---

### Q15: Explain the SCD Type 2 implementation in the data warehouse.

**Answer:**
`dim_product` and `dim_supplier` use SCD Type 2 — when a product's attributes
change, a new row is inserted (with `valid_from` / `valid_to` timestamps)
rather than updating the existing row. This preserves historical accuracy for
analytical queries. The ETL's `_build_dims()` method checks existing rows by
SKU/supplier_id and only inserts new ones, so changed attributes get new
dimension keys.

**Evidence:** `AGENTS.md` "Data Warehouse" section; `app/database/etl.py` lines
122–210 (`_build_dims`).

---

### Q16: How does the `get_cursor` context manager ensure data integrity?

**Answer:**
`get_cursor(commit=False)` yields a cursor and closes it in `finally`. When
`commit=True` is passed, the connection commits on success and rolls back on
exception. This ensures atomic operations — if a stored procedure fails mid-
execution, the entire transaction is rolled back. The connection is always
returned to the pool via `close_connection()` in the `teardown_appcontext`.

**Evidence:** `app/database/connection.py` lines 102–131.

---

### Q17: How are the Plotly charts lazy-loaded?

**Answer:**
Plotly.js (~3.5MB) is only loaded on pages that use it: dashboard, forecast,
anomaly, and EOQ calculator. Other pages don't include the CDN script tag.
This is controlled in `base.html` where the Plotly script is conditionally
included based on a template variable, reducing initial page load for pages
like login, suppliers, and settings.

**Evidence:** `AGENTS.md` "Performance Optimizations" section; `README.md` line 38.

---

### Q18: How does the theme system work?

**Answer:**
Dark mode is the default. A toggle in the UI saves the preference to
`localStorage`. CSS variables (defined in `landing.css` and `style.css`)
define the color palette: `--bg`, `--surface`, `--text`, `--accent`, etc.
Three.js backgrounds adapt via CSS variable inheritance. Chart.js and Plotly
charts use theme-aware datalabels via JavaScript. The `prefers-reduced-motion`
media query is respected for all GSAP animations.

**Evidence:** `AGENTS.md` "Theme Handling"; `app/static/css/landing.css` for
token definitions.

---

### Q19: How is the context processor optimized?

**Answer:**
The context processor in `_register_context()` runs on every page load and
computes `reorder_count` (a DB query for products at or below reorder point)
and loads user settings. Both are cached: the reorder count query was reduced
from 14 sequential queries to 11 (batched product aggregation), and settings
are loaded from a service that has its own cache. The result is cached for
60 seconds globally.

**Evidence:** `app/__init__.py` lines 154–189; `AGENTS.md` performance table.

---

### Q20: What testing infrastructure exists?

**Answer:**
A `pytest` suite in the `tests/` directory covers:
- Auth flow (registration, login, lockout, password reset)
- Role-based access (viewer can't write, admin can)
- REST API (products, suppliers, movements, EOQ)
- Security helpers (validators, password strength)
- ML smoke tests (forecasting with/without libraries)

Tests use `TestingConfig` which disables CSRF, sets `TESTING=True`, and uses
a test database. `run.py` and `create_app()` support `config_name='testing'`.

**Evidence:** `app/config/settings.py` lines 95–100 (`TestingConfig`); `README.md`
lines 290–298.

---

## 4. Business Interview Questions

### Q1: "What is the business value of EOQ optimization?"

**Answer:**
EOQ calculates the optimal order quantity that minimizes the sum of ordering
costs and holding costs. For the seeded dataset with 118 products, each
product has real demand rates, ordering costs, and holding costs from the
DataCo dataset. The EOQ calculator shows the per-product optimal quantity
and total cost, and the 3D sensitivity surface helps managers understand how
costs change when demand or ordering costs shift — enabling data-driven
procurement decisions.

**Evidence:** `app/services/eoq_service.py` lines 15–46 (`per_product_table`);
`app/routes/api.py` lines 279–299.

---

### Q2: "How does anomaly detection help operations?"

**Answer:**
The Isolation Forest + SPC z-score system flags unusual stock movements —
sudden surges (potential theft, data entry errors) or drops (unexpected
demand spikes, supply disruptions). The anomaly page shows a control chart
with UCL/LCL bounds, and each anomaly includes a z-score, confidence level,
and human-readable description. This allows ops teams to investigate
outliers before they cause stockouts or overstock.

**Evidence:** `app/ml/anomaly.py` lines 24–81; `app/routes/ai.py` lines 69–118.

---

### Q3: "What KPIs does the dashboard track?"

**Answer:**
The landing page and dashboard show: inventory value (total stock × unit price),
reorder count (products at/below reorder point with nothing on order), critical
count (stock below configurable critical threshold), warning count, units
moved today, stock health percentage, AI savings YTD, and a 14-day movement
chart. The reports section has 5 tabs with 15+ interactive charts covering
executive summary, warehouse analytics, procurement, sales, and inventory
health.

**Evidence:** `app/routes/api.py` lines 62–119 (`/api/dashboard/live`);
`README.md` lines 257–283 (UI Tour).

---

### Q4: "How does the reorder alert system work?"

**Answer:**
Products have a `reorder_point` field and an `on_order` counter. When
`current_stock <= reorder_point AND on_order <= 0`, the product appears in
the reorder queue. The dashboard context processor counts these for the badge.
The `/reorder-alerts` page shows severity-sorted cards with a "Mark ordered"
action that increments `on_order`, removing the item from the queue until
the PO is received.

**Evidence:** `app/__init__.py` lines 173–178 (reorder count query); `README.md`
line 265 (reorder alerts page).

---

### Q5: "What does the procurement workflow look like?"

**Answer:**
Purchase orders follow a kanban flow: `draft` → `approved` → `in_transit` →
`received` (or `cancelled`). The `/purchase-orders` page renders a kanban
board. Creating a PO links a supplier and product, sets quantity and unit
cost, and optionally an ETA date. When status changes to `received`, the
system logs a stock movement (IN) and updates `current_stock` and `on_order`.

**Evidence:** `app/database/schema.sql` lines 84–97 (PO table with status
CHECK constraint); `README.md` line 268 (kanban board).

---

### Q6: "How do you measure success?"

**Answer:**
Per `PRODUCT.md`: fewer stockouts (measured by reorder queue size trend),
lower carrying cost (visible in EOQ total cost calculations), forecast
accuracy >90% (MAPE computed against historical data), and measurable EOQ-
driven savings visible in the dashboard KPI cards.

**Evidence:** `PRODUCT.md` lines 21–22.

---

### Q7: "What is the reporting capability?"

**Answer:**
The `/reports` page has 5 tabs: Executive Summary, Warehouse Analytics,
Procurement & Suppliers, Sales Performance, and Inventory Health. It renders
15+ interactive Chart.js/Plotly charts filterable by warehouse, category, and
date range. Queries were optimized from 30+ sequential to 25+ by merging
related queries (e.g., `_period_orders` reduced from 4 queries to 1). Cache
TTL is 300 seconds (10x improvement over initial 30s).

**Evidence:** `AGENTS.md` performance table; `README.md` lines 270–273.

---

### Q8: "How does the monitoring page work?"

**Answer:**
`/monitoring` shows database stats, ETL status (last run time, rows processed),
daily login counts, warehouse health metrics, and a "Run ETL" button. The ETL
button triggers a non-blocking thread so the UI doesn't freeze during the
potentially slow (10–60s) warehouse rebuild. This was changed from synchronous
to threaded execution.

**Evidence:** `AGENTS.md` performance table ("ETL rebuild: non-blocking thread");
`README.md` lines 279–280.

---

### Q9: "What is the role hierarchy and why?"

**Answer:**
Three roles: `admin` (full access + settings + user management), `manager`
(write access to products, movements, POs), and `viewer` (read-only).
Self-registration always creates a viewer to prevent privilege escalation.
The constraint is enforced at the database level: `CHECK (role IN ('admin',
'manager','viewer'))` and at the route level via `@write_roles_required`.

**Evidence:** `app/database/schema.sql` line 18; `app/services/auth_service.py`
line 54; `app/security/__init__.py` for `write_roles_required`.

---

### Q10: "How do you handle data consistency between the operational DB and the warehouse?"

**Answer:**
The ETL uses a high-water mark (`etl_state.last_movement_id`) to track which
movements have been processed. On incremental runs, only movements above the
mark are processed. The warehouse rebuild happens in a single transaction —
if it fails, the previous state is preserved (rollback). The backward stock
walk in `_build_inventory_facts()` reconstructs historical stock from the
current `current_stock` minus net movements, clamping negatives to 0.

**Evidence:** `app/database/etl.py` lines 328–415; lines 254–325.

---

## 5. Viva Voce Questions

### Q1: "What is InventoryLogix in one sentence?"

**Answer:**
InventoryLogix is a Flask + PostgreSQL dashboard that combines real supply chain
transaction data with ML forecasting, anomaly detection, and EOQ optimization
to reduce stockouts and carrying costs.

---

### Q2: "Why did you choose PostgreSQL over MySQL or SQLite?"

**Answer:**
PostgreSQL supports advanced features we rely on: stored procedures with
PL/pgSQL (84+ functions), `RETURNING` clauses in `INSERT` (used in ETL for
getting generated keys), `ON CONFLICT DO UPDATE` (used in ETL upserts), and
`EXECUTE VALUES` for bulk inserts. SQLite lacks stored procedures and
connection pooling. MySQL's stored procedure syntax is less expressive.

**Evidence:** `app/database/etl.py` line 86 (`ON CONFLICT ... DO UPDATE`);
line 150 (`RETURNING warehouse_name, warehouse_key`).

---

### Q3: "What is the most complex part of the codebase?"

**Answer:**
The ETL pipeline (`app/database/etl.py`) — it handles incremental vs full
rebuilds, builds 6 dimension/fact tables, implements backward stock walk with
negative clamping, manages high-water marks, and runs everything in a single
transaction. It's also the most performance-critical path (10–60s on large
datasets).

---

### Q4: "How do you prevent SQL injection?"

**Answer:**
Every database interaction goes through psycopg2's parameterized queries with
`%s` placeholders. The repositories call stored procedures (`sp_*`) which
encapsulate the actual SQL. Raw user input never appears in query strings.
The connection layer uses `RealDictCursor` but all parameter binding is handled
by psycopg2's client-side escaping.

**Evidence:** `app/repositories/product_repo.py` line 51; `AGENTS.md` "Security
Implementation" section.

---

### Q5: "What would you improve if you had more time?"

**Answer:**
Three areas: (1) Add Celery for background task processing (ETL, forecast
retraining) instead of threading. (2) Implement a proper migration system
with Alembic (partially done in `migrations/`). (3) Add WebSocket support for
real-time dashboard updates instead of polling.

**Evidence:** `AGENTS.md` mentions Alembic migrations exist; `render.yaml` shows
single-worker Gunicorn.

---

### Q6: "Explain the data flow from a stock movement to the dashboard."

**Answer:**
1. User creates a movement via UI or API → `MovementService.record()` validates
   and calls `sp_movement_create` stored procedure.
2. The trigger `trg_validate_movement` auto-populates SKU, validates FK, and
   prevents negative stock.
3. The stored procedure updates `products.current_stock` and writes to
   `movements` table.
4. The dashboard reads `products` for KPIs (inventory value, reorder count) and
   `movements` for the 14-day chart, both via cached queries.
5. The ETL (when run) processes new movements into `fact_movement_daily` and
   `fact_inventory_daily` for the warehouse layer.

---

### Q7: "How does the application handle database failures?"

**Answer:**
The context processor and most views wrap DB calls in try/except — if the
database is down, they return default values (e.g., `reorder_count = 0`). The
error handlers render user-safe pages for 500 errors. The `_fallback_page()`
function in `__init__.py` generates a complete HTML error page without touching
the database at all. The connection pool handles dropped connections via
keepalives and connect timeouts.

**Evidence:** `app/__init__.py` lines 168–179 (graceful fallback); lines 203–221
(fallback page).

---

### Q8: "What is the difference between the operational DB and the data warehouse?"

**Answer:**
The operational DB (`users`, `products`, `movements`, `purchase_orders`) stores
current transactional state. The data warehouse (`dim_product`, `dim_supplier`,
`dim_date`, `dim_warehouse`, `fact_movement_daily`, `fact_inventory_daily`)
stores historical analytical data built by the ETL pipeline. The warehouse
uses SCD Type 2 for dimensions and aggregated daily facts — optimized for
analytical queries rather than transactional writes.

---

### Q9: "How does the application bootstrap on first run?"

**Answer:**
`bootstrap_database()` in `connection.py` runs once per process (guarded by
`_BOOTSTRAPPED` flag + thread lock). It calls `init_schema()` which executes
5 SQL files in order: `schema.sql` → `procedures.sql` → `warehouse.sql` →
`etl_procedures.sql` → `triggers.sql`. Then `seed_database()` populates with
DataCo CSV data or synthetic fallback. Finally `etl_database()` builds the
warehouse star schema.

**Evidence:** `app/database/connection.py` lines 179–195.

---

### Q10: "Why use stored procedures instead of application-level SQL?"

**Answer:**
Three benefits: (1) Security — all SQL runs inside PostgreSQL, reducing the
attack surface. (2) Performance — multi-step operations (like movement
recording with stock updates) execute in a single round-trip. (3) Data
integrity — triggers and constraints in stored procedures enforce rules
regardless of which client connects (API, UI, or direct DB access).

**Evidence:** `app/database/procedures.sql` referenced in `AGENTS.md`; 84+
`sp_*` functions.

---

### Q11: "How do you test the ML components?"

**Answer:**
ML smoke tests verify that forecasting functions return valid output structures
(predictions, lower, upper, history, baseline, accuracy, model labels) even
when libraries are missing. The tests check that `_moving_average_forecast`
produces reasonable values and that the anomaly detection returns the expected
JSON schema. Integration tests verify the `/ai/forecast/run` and
`/ai/anomaly/run` endpoints return valid responses.

**Evidence:** `README.md` lines 290–298 ("Tests cover... ML smoke tests").

---

### Q12: "What is the purpose of the `etl_state` table?"

**Answer:**
It stores key-value pairs tracking ETL progress. The critical key is
`last_movement_id` — the high-water mark of processed movements. On
incremental runs, only movements with `id > last_movement_id` are processed.
The `last_run_at` key tracks when the ETL last ran. This enables efficient
incremental processing without scanning the entire movements table.

**Evidence:** `app/database/etl.py` lines 74–88 (`_read_state` / `_write_state`);
lines 348–354 (incremental logic).

---

### Q13: "How does the search functionality work in the inventory page?"

**Answer:**
`sp_product_list` stored procedure accepts `search`, `category`, `warehouse`,
and `status` parameters. It uses `ILIKE` for case-insensitive search across
product name and SKU. Results are paginated via `LIMIT` and `OFFSET`. The
repository adds computed fields (EOQ, stock status, initials, runway_ratio)
via the `_decorate()` function before returning to the frontend.

**Evidence:** `app/repositories/product_repo.py` lines 46–56; lines 8–40
(`_decorate`).

---

### Q14: "What is the role of the `forecast_cache` and `anomaly_log` tables?"

**Answer:**
`forecast_cache` stores previous forecast results so the portfolio endpoint
doesn't re-run models on every request. `anomaly_log` records detected
anomalies for historical tracking. Both are populated by the AI service
layer and consulted by the portfolio endpoints (which have a 1-hour TTL
in-memory cache on top of the database cache).

**Evidence:** `app/database/schema.sql` referenced in `AGENTS.md`; `app/routes/ai.py`
line 20 (TTL cache).

---

### Q15: "How do you handle environment-specific configuration?"

**Answer:**
Three config classes in `app/config/settings.py`: `DevelopmentConfig` (DEBUG
True, SESSION_COOKIE_SECURE False), `ProductionConfig` (DEBUG False, secure
cookies), `TestingConfig` (TESTING True, CSRF disabled). The `get_config()`
function selects based on `FLASK_ENV` env var. Database params can come from
individual vars (`DB_HOST`, `DB_PORT`, etc.) or a single `DATABASE_URL`
(DSN format), giving flexibility for local dev, Render, or Supabase.

**Evidence:** `app/config/settings.py` lines 14–112.

---

## 6. Scenario-Based Questions

### Q1: "A user reports that the dashboard is showing stale data. How do you debug?"

**Answer:**
Check three things: (1) The context processor cache (60s TTL) — if the user
refreshed within 60s, data is cached. (2) The API cache for `/api/dashboard/live`
— verify the cache key. (3) Whether the ETL has run recently — the monitoring
page shows `last_run_at`. If the ETL hasn't run, the warehouse layer is stale.
The operational DB should always be current (movements update `current_stock`
immediately), but historical analytics depend on ETL freshness.

**Evidence:** `app/__init__.py` line 181 (settings cache); `app/routes/api.py`
line 119 (dashboard cache); `app/database/etl.py` line 377 (last_run_at).

---

### Q2: "An admin wants to restrict a manager from deleting products. How do you implement this?"

**Answer:**
Currently, `admin` and `manager` both have write access via `@write_roles_required`.
To restrict delete to admin-only, create a new decorator `@admin_required` that
checks `current_user.role == 'admin'` and apply it to the DELETE endpoint in
`app/routes/api.py`. The role constraint is already enforced at the DB level
(`CHECK (role IN ('admin','manager','viewer'))`), so the application layer just
needs the additional check.

**Evidence:** `app/routes/api.py` lines 196–205 (DELETE uses `@write_roles_required`);
`app/database/schema.sql` line 18 (role CHECK constraint).

---

### Q3: "The ML forecast is returning all zeros for a product. Why?"

**Answer:**
The product likely has no movement history. In `forecast_with_prophet()` and
`forecast_with_arima()`, the code checks `len(history) < 14` (Prophet) or
`len(history) < 20` (ARIMA) and falls back to `_moving_average_forecast()`.
If `history` is empty, the moving average returns `baseline = 0.0` and all
predictions are 0. The fix: ensure the product has at least 20 days of
movement data before running forecasts, or show a user-friendly message.

**Evidence:** `app/ml/forecasting.py` lines 63, 102 (length checks); lines 30–58
(moving average with empty history handling).

---

### Q4: "A user claims they can see another user's password hash. How do you respond?"

**Answer:**
Password hashes are never exposed. The `users` table stores `password_hash`
but no API endpoint returns it. The `UserRepository` methods that read users
(`find_by_username`, `find_by_email`) are used internally by `AuthService` for
authentication only. The UI only shows username, email, and role. The password
hash uses Werkzeug's `generate_password_hash` / `check_password_hash` which
uses pbkdf2:sha256 with random salts.

**Evidence:** `app/database/schema.sql` line 10 (`password_hash VARCHAR(256)`);
`app/services/auth_service.py` line 77 (`verify_password`).

---

### Q5: "The ETL is taking 60 seconds and blocking the UI. How do you fix it?"

**Answer:**
The current implementation runs ETL in a `threading.Thread` (non-blocking)
when triggered from the `/monitoring` page. If it's still blocking, check
that the monitoring route is using `threading.Thread(target=etl_database,
daemon=True).start()` instead of calling `etl_database()` directly. For
production, move to a task queue (Celery + Redis) with a webhook callback
to update the monitoring page when the ETL completes.

**Evidence:** `AGENTS.md` ("ETL rebuild: non-blocking thread"); `app/routes/ui.py`
for the monitoring page handler.

---

### Q6: "Two users simultaneously record OUT movements for the same product with only 5 units in stock. How do you prevent overselling?"

**Answer:**
The `MovementService.record()` method calls `ProductRepository.find_for_update()`
which issues `SELECT ... FOR UPDATE` on the product row. This acquires a row-
level lock. The first transaction sees stock=5, records the movement, and
commits (releasing the lock). The second transaction then acquires the lock,
sees the updated stock (e.g., 2), and if the requested quantity exceeds it, the
`trg_validate_movement` trigger prevents negative stock by raising an error.

**Evidence:** `app/repositories/product_repo.py` lines 111–115 (`FOR UPDATE`);
`AGENTS.md` "Triggers" section.

---

### Q7: "A user wants to export inventory data. How does this work?"

**Answer:**
The `/inventory` page includes a CSV export feature. The frontend calls the
`/api/products` endpoint with the current filter parameters, receives the
full product list, and generates a CSV blob for download. The API supports
pagination (`page`, `per_page`) and filtering (`search`, `category`,
`warehouse`, `stock_status`), so the export respects the user's current view.

**Evidence:** `app/routes/api.py` lines 122–148 (product listing with filters);
`README.md` line 262 ("searchable, filterable, paginated table with CSV
export").

---

## Summary

This document covers the full breadth of InterviewLogix's architecture,
from client discovery through technical deep-dives to real-world scenarios.
Every answer is grounded in actual source code — use these to demonstrate
production-level understanding in interviews.
