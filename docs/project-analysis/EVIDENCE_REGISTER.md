# InventoryLogix — Evidence Register

**Merged from both analysis passes · September 10, 2026**

## Evidence Classification

- **E1**: Direct evidence (visible in source code, config, schema, tests, docs, git)
- **E2**: Strong inference (strongly supported by implementation)
- **E3**: Engineering interpretation (reasonable professional interpretation)
- **E4**: Unknown (insufficient evidence)

Command-verified counts: `CREATE (OR REPLACE )?FUNCTION` = 74 total
(procedures.sql 51, etl_procedures.sql 14, triggers.sql 9); `CREATE
TRIGGER` = 8; tables = 12 operational (schema.sql) + 16 warehouse
(warehouse.sql); tests = 97 `def test_` in 8 files; routes = 50
registrations (ui 23, api 15, auth 5, ai 7); indexes = 49.

---

## A. Architecture & Stack

| # | Claim | Level | Evidence |
|---|---|---|---|
| 1 | App factory + 4 blueprints | E1 | app/__init__.py:31-151; routes/__init__.py |
| 2 | ThreadedConnectionPool(1,20), per-request g.db, teardown rollback | E1 | connection.py:33-39, 92-131; __init__.py:143 |
| 3 | Bootstrap executes 5 SQL files → seed → optional ETL, once per process, reloader-guarded | E1 | connection.py:134-155, 175-195; __init__.py:77-83 |
| 4 | Gunicorn 1 worker × 2 threads, rationale documented in-repo | E1 | run.py:41-49, 56-80; render.yaml:30; SUPABASE_SETUP.md |
| 5 | ui.py bypasses services/repos (~56 inline SQL sites); reports() ≈1156 lines, ~40 queries | E1 | ui.py:734-1890; grep count |
| 6 | Dead deps: pip plotly (never imported), flask-migrate (never wired) | E1 | requirements.txt:2,13; grep negative |
| 7 | Dead code: trg_cleanup_stale_sessions (no trigger), fact_product_daily (never populated), landing_cache (never used) | E1/E2 | triggers.sql:121-133; warehouse.sql:163-175; ui.py:35 |
| 8 | RLS enabled on all public tables with zero policies (Supabase surface) | E1 | schema.sql:271-283; migrations/versions/003_enable_rls.py |
| 9 | 49 CREATE INDEX statements | E1 | grep count |
| 10 | Alembic 001 duplicates bootstrap; runtime bootstrap is the real deploy path | E1 | migrations/versions/001_initial.py:26-38; render.yaml:14-15 |

## B. Data & Warehouse

| # | Claim | Level | Evidence |
|---|---|---|---|
| 11 | 74 SQL functions; 65 sp_/etl_ procedures; 8 triggers; 28 tables | E1 | grep counts (header) |
| 12 | trg_validate_movement auto-populates SKU + blocks negative stock | E1 | triggers.sql:196-225 |
| 13 | SCD2: valid_from/valid_to/is_current/row_hash + partial index; hash-skip merges | E1 | warehouse.sql:9-83; etl_procedures.sql |
| 14 | Incremental watermark ETL; single transaction; stock-walk clamping (negative→0, counted) | E1 | etl.py:74-88, 296-314, 328-405 |
| 15 | Seed: DataCo CSV or deterministic synthetic fallback; 10 warehouses; 36 curated suppliers; 3 demo users; trigger suspended during bulk seed | E1 | seed.py:25-450; dataset_service.py |
| 16 | 118 products / 150 suppliers / 180K+ transactions (dataset-derived) | E2 | seed.py; PRODUCT.md:21 (CSV gitignored, not in repo) |
| 17 | Movements produce multiple audit rows (trigger + service + stock-update trigger) | E1 | triggers.sql:230-254; movement_service.py:51-63 |
| 18 | ~1/6 of products deliberately forced below reorder point for demo queue | E1 | seed.py:89-96, 366-367 |
| 19 | Trigger name `trg_movement_stock_update` is audit-only (stock update happens in Python) | E1 | triggers.sql:250-254; movement_service.py:50 |

## C. Security

| # | Claim | Level | Evidence |
|---|---|---|---|
| 20 | Werkzeug password hashing; policy 8-128 chars letter+digit | E1 | user_repo.py:4,18,44-48; validators.py:70-79 |
| 21 | CSRF app-wide, 8h TTL, disabled in tests | E1 | extensions.py:14; settings.py:27,98 |
| 22 | Per-request CSP nonce; no unsafe-inline scripts; 3 CDNs whitelisted; style-src unsafe-inline; no SRI | E1 | headers.py:17-43; base.html:11,43-46 |
| 23 | Cookies Secure/HttpOnly/SameSite=Lax; strong session protection; DB session tracking | E1 | settings.py:18-25; extensions.py:12; user_sessions table |
| 24 | Lockout 5/15min in-memory + threading.Lock | E1 | auth_service.py:28-29, 66-86 |
| 25 | Flask-Limiter memory:// hardcoded; RATELIMIT_STORAGE_URI env shadowed | E1 | extensions.py:16-20; settings.py:40 |
| 26 | RBAC decorators on all API writes; 2 UI routes inline-check instead | E1 | roles.py:9-30; api.py:163-248; ui.py:580-582, 614-616 |
| 27 | Zero f-string SQL; reports builds SQL from hardcoded fragments only (user values stay in %s tuples) | E1 | grep; ui.py:789-826, 858-884 |
| 28 | Reset tokens: urlsafe(48), SHA-256-stored, single-active (purge), 5-min TTL, DB-level used/expiry check; consume lacks WHERE used=FALSE (race window) | E1/E2 | auth_service.py:127-133; procedures.sql:400-427 |
| 29 | .env gitignored; SECRET_KEY generated on Render; fallback "change-me-in-production" has no prod fail-fast | E1 | .gitignore:16-18; render.yaml:40-41; settings.py:17 |
| 30 | **Committed live Supabase DSN (password) in alembic.ini:7** | E1 | alembic.ini (value redacted; rotate) |
| 31 | render.yaml DB name mismatch (declared `inventory_db_2ov0` :19 vs fromDatabase `inventory-logix-db` :38) | E1 | render.yaml |
| 32 | AI portfolio endpoints unthrottled; horizon/contamination user-controlled in cache keys | E1 | ai.py:55-66, 105-118 |
| 33 | Reset link logged at WARNING when no mail transport | E1 | mailer.py:125-131 |
| 34 | Registration enumeration via distinct taken-messages | E1 | auth_service.py:49-52 |
| 35 | Background ETL thread calls current_app outside app context → likely silent failure; no concurrency guard | E1(static)/E2(runtime) | ui.py:1981-1986; etl.py:37-45 |

## D. ML & Analytics

| # | Claim | Level | Evidence |
|---|---|---|---|
| 36 | Prophet ≥14 pts weekly-only; ARIMA(1,1,1) ≥20 pts 95% CI; ensemble average; MA fallback | E1 | forecasting.py:18-158 |
| 37 | Fallback accuracy hardcoded 78.0; ensemble/Prophet accuracy = in-sample MAPE on fitted values | E1 | forecasting.py:55, 81-83, 123-126 |
| 38 | IsolationForest univariate (reshape(-1,1)), contamination 0.05, 80 trees, seed 42; "confidence" synthetic formula | E1 | anomaly.py:24-49 |
| 39 | SPC: mean/σ/UCL/LCL (μ±3σ, LCL clamped ≥0) | E1 | anomaly.py:84-94 |
| 40 | EOQ = √(2DS/H) server + client copies; sensitivity 3D grid | E1 | helpers.py:59-73; eoq.js:27; eoq_service.py:49-80 |
| 41 | EOQ service uses raw SQL (one place bypassing sp_* convention) | E1 | eoq_service.py:18-25 |

## E. Performance & Caching

| # | Claim | Level | Evidence |
|---|---|---|---|
| 42 | Two reorder-count context processors: blueprint one cached 60s; app-level one uncached per request | E1 | ui.py:54-71; __init__.py:157-189 |
| 43 | Plotly lazy on exactly 4 pages; Chart.js global | E1 | template grep; base.html:43-44 |
| 44 | Dashboard 11 inline queries + 2 repo calls = 13 total | E1 | ui.py:91-284 |
| 45 | Reports cache 300s; LRU max 20 entries | E1 | cache.py:81; ui.py:841-853 |
| 46 | AI portfolio cache 1h, max 10, never busted | E1 | ai.py:20, 60-66, 112-118 |
| 47 | cache_bust_* prefix invalidation on writes; manual ETL busts only monitoring cache | E1 | cache.py:88-135; ui.py:1987 |

## F. Business Value Classification

| # | Claim | Level | Evidence |
|---|---|---|---|
| 48 | "AI savings YTD" = EOQ-vs-monthly-ordering counterfactual on estimated costs ($50 ordering, 20% holding); always positive by construction | E1 | ui.py:279-308; dataset_service.py:311-313 |
| 49 | Landing KPIs hardcoded demo values (docstring admits) | E1 | ui.py:1992-2017 |
| 50 | units_today falls back to fake 1248; dashboard delta footers hardcoded | E1 | ui.py:113; dashboard.html:17-19 |
| 51 | Measured: inventory value, reorder counts, turnover, ABC, slow-movers, supplier spend, sales trends (live SQL over seeded data) | E1 | ui.py:89-274 |
| 52 | No production users; no ROI/stockout/adoption measurement exists | E1/E4 | absence verified |
| 53 | No ERP/WMS/billing/shipping connector code; landing "Connect your ERP, WMS" is aspirational copy | E1 | grep negative; landing.html:317 |
| 54 | Email/Slack/sound alert toggles have no backend consumer; mailer used only by password reset | E1 | grep; settings_service.py:29-30 |
| 55 | No user-management UI; sp_user_change_role/set_active/list_all exist but no route calls them | E1 | user_repo.py:56-69; grep |
| 56 | No reorder notifications; no scheduler/cron anywhere | E1 | grep negative |
| 57 | PO "received" status flip creates no movement, never clears on_order | E1 | procedures.sql:604-609; ui.py:516,538 only setters |
| 58 | Forecast accuracy >90% (PRODUCT.md success metric) not measured; in-sample MAPE only | E1/E3 | PRODUCT.md:23; forecasting.py:81-83 |
| 59 | WCAG 2.1 AA target claimed, not audited | E3 | PRODUCT.md:96 |

## G. Git History

| # | Claim | Level | Evidence |
|---|---|---|---|
| 60 | 2026-08-15 → 2026-09-10; 73 commits; 10 active days; single developer (two identities) | E1 | git log |
| 61 | First commit = big-bang import (96 files, 15,240 lines); construction predates repo | E1 | git show --stat fb795be |
| 62 | No tags/releases | E1 | git tag (empty) |
| 63 | Verified events: caching reverted in 4 min then re-landed 09-04; "17 usability fixes" reverted after 34 min; SendGrid added for Render SMTP block; Plotly CDN race fix | E1 | git log: bfaf3ad→1045f8b, 895dbed→daee271, 93f53df, a14afbb |
| 64 | Pre-repo development timeline unverifiable | E4 | — |

## H. Tests

| # | Claim | Level | Evidence |
|---|---|---|---|
| 65 | 97 tests / 8 files: ML 33, services 29, security 12, cache 8, roles 7, auth 4, API 4, ETL 3 | E1 | grep `def test_`; tests/ |
| 66 | Untested: dashboard/reports/monitoring routes, lockout, reset-token flow, mailer, PO transitions, ETL thread, CSRF (disabled in TestingConfig) | E1 | absence in tests/; settings.py:98 |

---

## Unverified / Missing Evidence

| Claim | Required Evidence | Status |
|-------|------------------|--------|
| Production deployment in active use | Live URL, monitoring data | Not available |
| User adoption metrics | User counts, active sessions | Not available |
| Performance benchmarks | Load-test results | Not available |
| Security audit | Penetration-test report | Not available |
| ML accuracy vs actuals | Real forecast-vs-actual comparison | Not available |
| Background ETL runtime behavior | Runtime test of /monitoring/run-etl | Static analysis only (likely fails on app context) |
| ProxyFix/client-IP behind Render proxy | Runtime header inspection | Not verified |
| 002/003 changes folded back into .sql bootstrap files | Diff verification | Not verified |

---

## Contradictions Found & Resolved

| Topic | Earlier doc claim | Verified reality (this register) |
|---|---|---|
| Procedure count | "84+ stored procedures" | 74 functions total (51 sp_* + 14 etl_* + 9 trigger functions) |
| Context processor | "Cached 60s" | Only the blueprint-level one; duplicate app-level processor uncached (#42) |
| Dashboard queries | "14→11" | 11 inline + 2 repo = 13 total (#44) |
| Reports TTL | "5min → 300s (10× fewer cold hits)" | 300s ≡ 5 min; framing only (#45) |
| ETL non-blocking | Verified working | Thread exists but likely fails silently (app context) — needs runtime confirmation (#35) |
| Warehouse table count | "15 warehouse tables" | 16 in warehouse.sql (#11) |
| Demo credentials exposure | README lists only viewer | Three seeded users exist (admin/manager/viewer, seed.py:30-34; render.yaml:16) |
| Harris 1913 title | "How Much to Make of What" | "How many parts to make at once" (corrected in Literature_Review.md) |
| Prophet venue | 2017, The American Statistician | PeerJ preprint 2017; journal 71(1) 2018 (corrected) |
| Shewhart publisher | "D. Vanstrand" | D. Van Nostrand (corrected) |

---

*Generated: September 10, 2026 · Merged from both analysis passes*
