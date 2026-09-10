# InventoryLogix — Evidence Register

## Evidence Classification

- **E1**: Direct evidence (visible in source code, config, schema, tests, docs)
- **E2**: Strong inference (strongly supported by implementation)
- **E3**: Engineering interpretation (reasonable professional interpretation)
- **E4**: Unknown (insufficient evidence)

---

## Claims with Evidence

### Core Functionality

| Claim | Evidence Level | Source | Location |
|-------|---------------|--------|----------|
| 97 tests passing | E1 | pytest output | `tests/` |
| 84+ stored procedures | E1 | SQL file | `app/database/procedures.sql` |
| 8 trigger functions | E1 | SQL file | `app/database/triggers.sql` |
| 12 operational tables | E1 | SQL file | `app/database/schema.sql` |
| 15 warehouse tables | E1 | SQL file | `app/database/warehouse.sql` |
| SCD Type 2 dimensions | E1 | SQL file | `app/database/warehouse.sql:9-61` |
| ETL pipeline | E1 | Python file | `app/database/etl.py` |
| Demo data seeding | E1 | Python file | `app/database/seed.py` |
| 10 warehouses | E1 | Seed data | `app/database/seed.py:37-40` |
| 150 suppliers | E1 | Seed data | `app/database/seed.py:44-81` |
| 118 products | E2 | Seed data (DataCo reference) | `app/database/seed.py` |
| 180K+ transactions | E2 | DataCo dataset reference | `PRODUCT.md:21` |

### Authentication & Security

| Claim | Evidence Level | Source | Location |
|-------|---------------|--------|----------|
| Flask-Login session management | E1 | Import + usage | `app/extensions.py`, `app/__init__.py:136-141` |
| Flask-WTF CSRF protection | E1 | Config enabled | `app/config/settings.py:27-28` |
| Account lockout (5 attempts → 15 min) | E1 | Constants | `app/services/auth_service.py:24-25` |
| In-memory lockout tracker | E1 | Variable declaration | `app/services/auth_service.py:28-29` |
| Password hashing (werkzeug) | E1 | Import + usage | `app/database/seed.py:21` |
| Role-based access (viewer/admin/manager) | E1 | CHECK constraint | `app/database/schema.sql:18` |
| Write roles required decorator | E1 | Function definition | `app/security/roles.py:28-30` |
| CSP nonces per request | E1 | before_request hook | `app/security/headers.py:17-19` |
| CSP header injection | E1 | after_request hook | `app/security/headers.py:25-46` |
| Rate limiting (10/min login) | E1 | Decorator | `app/routes/auth.py:17` |
| Rate limiting (5/min register) | E1 | Decorator | `app/routes/auth.py:41` |
| Rate limiting (30/min API writes) | E1 | Decorator | `app/routes/api.py:164` |
| Rate limiting (60/min movements) | E1 | Decorator | `app/routes/api.py:246` |
| Session cookies (Secure, HttpOnly) | E1 | Config | `app/config/settings.py:18-24` |
| Password reset tokens | E1 | Table schema | `app/database/schema.sql:114-123` |
| Audit logging | E1 | Triggers | `app/database/triggers.sql` |
| HTTP security headers | E1 | after_request hook | `app/security/headers.py:26-46` |
| Parameterized SQL | E1 | All repository files | `app/repositories/*.py` |

### Machine Learning

| Claim | Evidence Level | Source | Location |
|-------|---------------|--------|----------|
| Prophet forecasting | E1 | Import + usage | `app/ml/forecasting.py:18-21` |
| ARIMA forecasting | E1 | Import + usage | `app/ml/forecasting.py:24-27` |
| Ensemble averaging | E1 | Function | `app/ml/forecasting.py:143-158` |
| Moving-average fallback | E1 | Function | `app/ml/forecasting.py:30-58` |
| Isolation Forest | E1 | Import + usage | `app/ml/anomaly.py:12-15` |
| SPC z-score analysis | E1 | Function | `app/ml/anomaly.py:84-97` |
| Graceful library fallback | E1 | try/except blocks | `app/ml/forecasting.py:17-27` |
| Portfolio caching (1hr) | E1 | Cache TTL | `app/routes/ai.py` |

### EOQ Optimization

| Claim | Evidence Level | Source | Location |
|-------|---------------|--------|----------|
| EOQ formula √(2DS/H) | E1 | Function | `app/utils/helpers.py:59-64` |
| Total cost calculation | E1 | Function | `app/utils/helpers.py:67-73` |
| Cost curve visualization | E1 | Function | `app/services/eoq_service.py:48-63` |
| 3D sensitivity surface | E1 | Function | `app/services/eoq_service.py:66-80` |
| Three.js 3D surface | E1 | JS file | `app/static/js/eoq.js` |

### Data Warehouse

| Claim | Evidence Level | Source | Location |
|-------|---------------|--------|----------|
| SCD Type 2 product dimension | E1 | Table schema | `app/database/warehouse.sql:9-27` |
| SCD Type 2 supplier dimension | E1 | Table schema | `app/database/warehouse.sql:32-47` |
| SCD Type 2 warehouse dimension | E1 | Table schema | `app/database/warehouse.sql:51-63` |
| Incremental ETL | E1 | High-water mark | `app/database/etl.py:74-88` |
| Stock walk clamping | E1 | max(0, running_stock) | `app/database/etl.py` |
| ETL monitoring dashboard | E1 | Route | `app/routes/ui.py` |

### Performance

| Claim | Evidence Level | Source | Location |
|-------|---------------|--------|----------|
| Connection pooling (20 max) | E1 | Pool size | `app/database/connection.py:35` |
| Context processor caching (60s) | E2 | Global cache | `app/__init__.py:154-189` |
| Reports cache (300s TTL) | E1 | Cache config | `app/utils/cache.py` |
| Plotly lazy-loaded | E2 | Template conditionals | `app/templates/base.html` |
| Dashboard queries batched | E1 | SQL aggregation | `app/routes/ui.py:89-200` |

### Deployment

| Claim | Evidence Level | Source | Location |
|-------|---------------|--------|----------|
| Render Blueprint | E1 | Config file | `render.yaml` |
| Gunicorn (1 worker, 2 threads) | E1 | Config | `run.py:70-80` |
| Auto-deploy on push | E1 | Config | `render.yaml:32` |
| Health check endpoint | E1 | Route | `app/routes/api.py:31-33` |
| Schema bootstrap on start | E1 | Function call | `app/__init__.py:78-83` |

---

## Unverified Claims

| Claim | Evidence Level | Notes |
|-------|---------------|-------|
| 118 products seeded | E2 | DataCo reference, actual count not manually verified |
| 180K+ transactions | E2 | DataCo reference, CSV not in repo (gitignored) |
| Forecast accuracy >90% | E3 | Claimed in PRODUCT.md, not measured in production |
| EOQ-driven savings | E3 | Business assumption, not measured |
| WCAG 2.1 AA compliance | E3 | Claimed in PRODUCT.md, not audited |

---

## Contradictions Found

None identified during analysis.

---

## Missing Evidence

| Claim | Required Evidence | Status |
|-------|------------------|--------|
| Production deployment | Live URL, monitoring data | Not available |
| User adoption metrics | User counts, active sessions | Not available |
| Performance benchmarks | Load test results | Not available |
| Security audit | Penetration test report | Not available |
| ML accuracy metrics | Real forecast vs actual comparison | Not available |

---

*Generated: September 10, 2026*
