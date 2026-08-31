# InventoryLogix Agent Guide

## Essential Commands

**Setup & Run**
- `python -m venv myvenv` → create virtual environment
- `myvenv\Scripts\activate` (Windows) or `source myvenv/bin/activate` (Unix)
- `pip install -r requirements.txt`
- `cp .env.example .env` → set `DATABASE_URL` and `SECRET_KEY`
- `python run.py` → starts Flask app on http://localhost:5000
- First run auto-applies schema and seeds demo data

**Testing**
- `pip install pytest`
- `pytest` → runs full test suite
- Tests cover auth, RBAC, REST API, security helpers, ML smoke tests, service validation

**Database & ETL**
- `python migrate.py etl` → runs ETL pipeline (populates data warehouse)
- Visit `/monitoring` → Run ETL button (non-blocking thread)
- Schema migrations: `flask db migrate` / `flask db upgrade` (via Alembic)

**Environment**
- Critical vars in `.env`: `DATABASE_URL`, `SECRET_KEY`, `NVIDIA_API_KEY` (for OpenCode agents)
- SMTP vars needed for password reset emails in production
- `FLASK_ENV=development` enables debug mode

## Key Architecture Notes

**Entrypoint**
- `run.py` → calls `create_app()` from `app/__init__.py`
- Application factory pattern with config from `app/config/`

**Security Implementation**
- All SQL uses parameterized queries via stored procedures (`sp_*` functions)
- CSP nonces generated per-request for inline scripts + import maps
- Role-based access: `viewer` (read-only), `admin`/`manager` (write)
- Rate limits: auth (10/min login, 5/min register), API writes (30/min), movements (60/min)

**ML Pipeline**
- Forecasting: Prophet + ARIMA ensemble with moving-average fallback
- Anomaly: Isolation Forest + SPC z-score charts
- Portfolio endpoints cached 1-hour TTL to avoid repeated model fitting

**Performance Optimizations**
- Context processor cached 60s (was 1 DB query/page load)
- Plotly lazy-loaded (only loads on pages that use it: dashboard, forecast, anomaly, EOQ)
- Dashboard queries batched (reduced from 14→11 sequential queries)
- Reports cache TTL: 5min → 300s (10x fewer cold hits)
- ETL rebuild: non-blocking thread (was synchronous 10-60s block)

## File Conventions

**Stored Procedures**
- Located in `app/database/procedures.sql` (84+ functions)
- Naming: `sp_*` for all CRUD operations
- Example: `sp_product_list, `sp_movement_create`, `sp_po_update_status`

**Triggers**
- Located in `app/database/triggers.sql` (8 functions)
- Validation: `trg_validate_movement` (auto-populates SKU, validates FK, prevents negative stock)
- Audit: `trg_audit_*` on products, suppliers, movements, POs

**Static Assets**
- CSS: `app/static/css/` (style.css, landing.css, ai-features.css)
- JS: `app/static/js/` (auth-bg.js for Three.js background, dashboard-3d.js, saas-animations.js for GSAP, ai-features.js, eoq.js, main.js, landing.js)
- Images: `app/static/img/` (favicon.svg, logo.svg)

**Templates**
- Base layout: `app/templates/base.html` (includes CDN scripts, theme handling)
- Auth: `app/templates/auth/` (login, register, forgot, reset)
- AI: `app/templates/ai/` (forecast, anomaly)
- Errors: `app/templates/errors/` (400/401/403/404/422/429/500)

## Common Gotchas

1. **ML Library Availability**
   - Prophet, ARIMA, Isolation Forest are optional
   - Code gracefully falls back to moving-average/z-score when unavailable
   - Check `app/ml/forecasting.py` and `app/ml/anomaly.py` for fallback logic

2. **Theme Handling**
   - Dark-mode default; toggle saves to `localStorage`
   - All charts use theme-aware datalabels via JS
   - Three.js background adapts to theme via CSS variables

3. **Data Warehouse**
   - Uses SCD Type 2 for `dim_product` and `dim_supplier`
   - ETL pipeline includes stock walk clamping for inventory accuracy
   - Warehouse monitoring at `/monitoring` shows ETL status and DB stats

4. **API Format**
   - All endpoints return consistent JSON envelope: `{success: boolean, data: ..., error: ...}`
   - HTTP status codes indicate outcome (200 success, 4xx client errors, 5xx server errors)
   - AI endpoints: `/ai/forecast/run`, `/ai/anomaly/run`, `/ai/eoq/sensitivity`

## OpenCode Specific

**Agent Configuration**
- OpenCode config in `opencode.json` (project root)
- Agent definitions in `.opencode/agents/`
- Uses free NVIDIA Zen models: `nemotron-3-ultra-550b`, `nemotron-3.5-flash`, `nemotron-3-super`, `ling`, `mimo-v2-free`
- MCP servers configured: filesystem, github, memory, brave-search

**When Working with This Repo**
- Always activate virtualenv before running Python commands
- Remember schema seeding happens automatically on first run
- For UI changes, hard-refresh browser to clear JS/CSS cache
- Test auth flows with demo credentials: viewer/Viewer@123, manager/Manager@123, admin/Admin@123