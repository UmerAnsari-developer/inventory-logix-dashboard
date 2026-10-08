# InventoryLogix Production Readiness Audit Report

---

## A. Executive Summary

**What the application is today:** InventoryLogix is a Flask + PostgreSQL inventory dashboard with authentication (Flask-Login, RBAC), CRUD for products/suppliers/movements/purchase orders, a data warehouse ETL pipeline (SCD Type 2 dimensions + fact tables), Prophet/ARIMA/ensemble demand forecasting with graceful fallback, Isolation Forest + SPC z-score anomaly detection, EOQ optimization with 3D sensitivity surface, and a dark-mode UI with Three.js/GSAP/Chart.js/Plotly visualizations.

**What it is not yet:** A production-ready logistics optimization platform. It lacks warehouse execution workflows (receiving, putaway, picking, packing, shipping), logistics execution (shipment creation, carrier assignment, tracking, proof of delivery), multi-echelon planning, transfer recommendations, budget-constrained optimization, and has no out-of-sample forecast validation or anomaly precision/recall benchmarks.

**Five highest-risk gaps:**
1. **GAP-001 (Critical):** Forecast accuracy claims (>90%) unsupported — no rolling-origin backtesting, no out-of-sample evaluation, MAPE undefined on zero-demand days, accuracy metric is in-sample only
2. **GAP-002 (Critical):** Anomaly detection has no ground-truth labels — precision/recall/F1 unmeasured; alerts cannot be validated as actionable
3. **GAP-003 (High):** No warehouse execution layer — receiving/putaway/picking/packing/shipping workflows absent; "logistics optimization" claim unsupported
4. **GAP-004 (High):** Process-local login lockout (DB-007) — fails under multi-worker deployments; no Redis/shared store for rate limiting
5. **GAP-005 (High):** Naive UTC timestamps throughout (DB-019) — no TIMESTAMPTZ migration; timezone bugs inevitable in production

**Three highest-value next features:**
1. Rolling-origin backtesting framework with MAE/RMSE/WAPE/MASE on holdout data
2. Anomaly labeling workflow + precision/recall dashboard
3. Warehouse execution workflows (receive → putaway → pick → pack → ship)

**Release-readiness decision:** **Ready for controlled student pilot only** — not production-ready. Core inventory CRUD and forecasting UI work, but business-critical accuracy claims are unverified, warehouse execution is missing, and multi-worker deployment has known concurrency bugs.

---

## B. Capability Matrix

| Capability | Evidence | Status | Severity | Business Impact | Recommended Action |
|------------|----------|--------|----------|-----------------|-------------------|
| User authentication (signup/login/logout) | `app/routes/auth.py:16-194`, `app/services/auth_service.py:44-218` | Complete | Low | — | — |
| Role-based access (admin/manager/viewer) | `app/security/roles.py`, `app/routes/api.py:179-229` | Complete | Low | — | — |
| Password reset (email + UI fallback) | `app/routes/auth.py:76-159`, `app/services/auth_service.py:220-301` | Complete | Low | — | — |
| Account lockout (5 attempts → 15 min) | `app/services/auth_service.py:24-199` | Partial | High | Multi-worker deployments bypass lockout | Move to Redis/DB-backed store |
| Product CRUD | `app/services/product_service.py`, `app/repositories/product_repo.py` | Complete | Low | — | — |
| Stock movements (IN/OUT/ADJUSTMENT/RETURN) | `app/services/movement_service.py`, `app/database/triggers.sql:243-270` | Complete | Low | — | — |
| Negative stock prevention | `app/database/triggers.sql:254-260`, `app/database/procedures.sql` (sp_movement_record) | Complete | Low | — | — |
| Purchase order lifecycle | `app/services/po_service.py`, `app/repositories/po_repo.py` | Partial | Medium | No multi-line PO, no partial receipt workflow | Add PO lines, partial receipt, invoice matching |
| Supplier management | `app/services/supplier_service.py`, `app/repositories/supplier_repo.py` | Complete | Low | — | — |
| Warehouse CRUD | `app/routes/ui.py` (warehouses), `app/repositories/warehouse_repo.py` | UI-only | High | No zone/aisle/rack/bin, no barcode scanning | Add location hierarchy + scanning |
| Reorder detection | `app/routes/ui.py:176-177`, `app/repositories/product_repo.py:139-142` | Partial | Medium | No lead-time demand, no safety stock calc | Implement ROP = lead_time_demand + safety_stock |
| Demand forecasting (Prophet/ARIMA/ensemble) | `app/ml/forecasting.py:69-167`, `app/services/forecast_service.py:23-43` | Partial | Critical | Accuracy claims unverified; no backtesting | Add rolling-origin evaluation on holdout data |
| Forecast portfolio (all products) | `app/services/forecast_service.py:112-168` | Partial | High | Uses 7-day MA, not actual model; misleading "Model" column | Run actual model per product or label clearly as baseline |
| Anomaly detection (Isolation Forest + SPC) | `app/ml/anomaly.py:26-100`, `app/services/anomaly_service.py:17-71` | Partial | Critical | No labels, no precision/recall; risk levels unvalidated | Add labeling workflow + benchmark on synthetic/real labels |
| Anomaly portfolio | `app/services/anomaly_service.py:155-216` | Partial | High | Per-product model fit at request time; doesn't scale | Move to batch job; cache results |
| EOQ calculation | `app/utils/helpers.py`, `app/services/eoq_service.py`, `app/routes/ai.py:190-202` | Complete | Low | — | — |
| EOQ 3D sensitivity surface | `app/static/js/ai-features.js` (EOQ section), `app/templates/ai/forecast.html` | Complete | Low | — | — |
| Data warehouse ETL | `app/database/etl.py`, `app/database/warehouse.sql`, `app/database/etl_procedures.sql` | Partial | Medium | Stock walk clamping; incremental watermark; no SLA monitoring | Add ETL observability, data quality checks |
| Star-schema reporting | `app/routes/ui.py` (reports), `tests/test_reports_fact.py` | Complete | Low | — | — |
| Audit logging | `app/database/triggers.sql:175-328`, `app/repositories/audit_repo.py` | Complete | Low | — | — |
| Model monitoring | `app/monitoring/metrics.py`, `app/monitoring/degradation.py`, `app/monitoring/alerts.py` | Partial | High | Baseline MAE/MAPE not persisted per model; degradation detection untested | Persist baselines; add automated retrain triggers |
| REST API (products/suppliers/movements/EOQ) | `app/routes/api.py:32-374` | Complete | Low | — | — |
| AI API (forecast/anomaly/EOQ/monitoring) | `app/routes/ai.py:24-318` | Complete | Low | — | — |
| Rate limiting | `app/extensions.py`, `app/config/settings.py:68-76` | Partial | High | Memory:// storage; fails with workers>1 | Configure Redis for production |
| CSP nonces + security headers | `app/security/headers.py`, `app/__init__.py:265` | Complete | Low | — | — |
| Parameterized SQL (stored procedures) | `app/database/procedures.sql`, all repositories | Complete | Low | — | — |
| Session management (browser-session only) | `app/routes/auth.py:33-35`, `app/services/auth_service.py:210-211` | Complete | Low | — | — |
| Multi-tenant / org isolation | — | Missing | Medium | No tenant_id on any table; single-org only | Add org_id + RLS policies if multi-tenant needed |
| Mobile/responsive UI | `app/static/css/style.css`, `app/templates/base.html` | Partial | Medium | Desktop-first; table horizontal scroll on mobile | Add responsive tables, touch-friendly controls |
| Accessibility (WCAG 2.1 AA) | `app/templates/` (ARIA labels, semantic HTML) | Partial | Medium | Some icon-only buttons lack aria-label; focus states inconsistent | Audit with axe; fix form labels, focus management |
| Unit/API/integration tests | `tests/` (40+ test files) | Partial | High | No E2E tests; no load tests; no contract tests | Add Playwright E2E; add contract tests for API |
| Forecast backtesting | — | Missing | Critical | Cannot claim accuracy without out-of-sample validation | Implement rolling-origin backtest framework |
| Anomaly benchmarking | — | Missing | Critical | Cannot claim detection quality without labels | Create synthetic + human-labeled benchmark set |
| Deployment (Render Blueprint) | `render.yaml`, `run.py:41-80` | Partial | High | Single worker (workers=1); no horizontal scaling | Document scaling limits; add Redis for multi-worker |
| Health checks | `app/routes/api.py:33-47` | Partial | Medium | Only checks DB connectivity; no dependency checks | Add Redis, SMTP, ML library health checks |
| Backup/restore | `app/services/backup_service.py`, `render.yaml` | Partial | Medium | Relies on Render managed PG backups; no restore test documented | Document RPO/RTO; quarterly restore drill |
| Observability (logs/metrics/tracing) | `app/__init__.py:69-79`, `app/monitoring/` | Partial | Medium | File logging only; no structured logs, no tracing | Add structured JSON logs; OpenTelemetry tracing |

---

## C. Detailed Findings

### GAP-001: Forecast Accuracy Claims Unverified
**Category:** Forecasting  
**Current behavior:** `ForecastService.run()` returns `accuracy` field (e.g., 78.0 for moving average, computed as `100 - MAPE` on training data). Portfolio endpoint (`forecast_service.py:112-168`) computes "accuracy" on active-demand days only using a 7-day moving average baseline, not the actual fitted model.  
**Expected behavior:** Accuracy must be measured on chronologically held-out test data (rolling-origin backtesting) with MAE, RMSE, WAPE, MASE, bias, and interval coverage reported.  
**Evidence:** `app/ml/forecasting.py:88-92` (in-sample MAPE), `app/services/forecast_service.py:150-155` (portfolio uses MA, not Prophet/ARIMA), `tests/test_ml.py:134-145` (tests check in-sample accuracy only).  
**Impact:** Business decisions (reorder, safety stock) based on unverified accuracy → stockouts or overstock.  
**Root cause:** No train/test split; evaluation uses same data as training.  
**Solution:** Implement rolling-origin backtesting (expanding window) with configurable horizon; persist test metrics per product/model/horizon.  
**Dependencies:** `app/monitoring/metrics.py` has metric functions; need backtest orchestrator.  
**Tests required:** Backtest on synthetic + DataCo data; compare Prophet vs ARIMA vs ensemble vs MA baseline.  
**Severity:** Critical | **Priority:** P0 | **Complexity:** M

### GAP-002: Anomaly Detection Has No Ground-Truth Validation
**Category:** Anomaly Detection  
**Current behavior:** `AnomalyService.run_for_product_enriched()` generates alerts with risk levels (low/medium/high/critical) and recommended actions. No precision/recall/F1 measured. `detect_anomalies_enriched()` combines Isolation Forest, z-score, forecast deviation, and rule-based peaks with deduplication by day.  
**Expected behavior:** Precision, recall, F1, PR-AUC, false-positive rate measured against labeled anomalies (synthetic + human-reviewed). Alert fatigue tracked (alerts/day, review rate).  
**Evidence:** `app/ml/anomaly.py:276-404`, `app/services/anomaly_service.py:155-216`, `tests/test_ml.py:182-392` (tests verify deterministic output, not detection quality).  
**Impact:** Operations team wastes time on false positives or misses real anomalies; "risk level" is uncalibrated.  
**Root cause:** No labeling pipeline; no evaluation framework.  
**Solution:** Add anomaly labeling UI (review → confirm/reject); generate synthetic anomalies with known ground truth; compute precision/recall per detection method.  
**Dependencies:** `AnomalyRepository` has status field (new/reviewed/acknowledged/resolved).  
**Tests required:** Synthetic benchmark (injected spikes/drops); human-labeled sample from DataCo data.  
**Severity:** Critical | **Priority:** P0 | **Complexity:** M

### GAP-003: No Warehouse Execution Workflows
**Category:** Warehouse Execution / Logistics  
**Current behavior:** `warehouses` table exists (`schema.sql:434-439`), UI shows capacity tiles (`app/routes/ui.py`), but no receiving, putaway, picking, packing, shipping, cycle counting, or variance reconciliation.  
**Expected behavior:** End-to-end warehouse execution: ASN → receiving → inspection → putaway → pick wave → pack → ship → POD. Bin-level location tracking.  
**Evidence:** `app/database/warehouse.sql` has SCD dims but no execution fact tables. `app/routes/ui.py` has `/warehouses` page only.  
**Impact:** Cannot execute warehouse operations; "logistics optimization" claim is marketing only.  
**Root cause:** Scope limited to inventory intelligence, not execution.  
**Solution:** Add `warehouse_locations` (zone/aisle/rack/shelf/bin), `receipts`, `putaway_tasks`, `pick_tasks`, `pack_tasks`, `shipments` tables + workflow services.  
**Dependencies:** Requires barcode/RFID scanning integration (future).  
**Tests required:** E2E receive→putaway→pick→pack→ship flow.  
**Severity:** High | **Priority:** P1 | **Complexity:** XL

### GAP-004: Process-Local Login Lockout (DB-007)
**Category:** Security  
**Current behavior:** `AuthService._check_rate_limit()` and `_record_failed_attempt()` use in-memory counters (`MAX_FAILED_ATTEMPTS=5`, `LOCKOUT_MINUTES=15`). Comment at `auth_service.py:24-26` acknowledges: "with workers>1 the effective threshold multiplies per worker."  
**Expected behavior:** Shared rate-limit store (Redis or PostgreSQL `rate_limit_state` table) across all workers.  
**Evidence:** `app/services/auth_service.py:74-182`, `render.yaml:30` (`workers: 1`), `app/config/settings.py:71` (`RATELIMIT_STORAGE_URI=memory://`).  
**Impact:** Brute-force protection fails under horizontal scaling.  
**Root cause:** Deferred to "follow-up" per comment.  
**Solution:** Use existing `rate_limit_state` table (already has `key`, `count`, `window_start`, `expires_at`) with advisory locks for all rate limiting.  
**Dependencies:** `app/database/schema.sql:326-337` (rate_limit_state table exists).  
**Tests required:** Multi-worker load test with concurrent failed logins.  
**Severity:** High | **Priority:** P0 | **Complexity:** S

### GAP-005: Naive UTC Timestamps (DB-019)
**Category:** Data Integrity  
**Current behavior:** All timestamps stored as naive `TIMESTAMP` (UTC wall-clock) via `_utcnow()` returning `datetime.now(timezone.utc).replace(tzinfo=None)`. `rate_limit_state` uses `TIMESTAMPTZ` but app code mixes naive/aware.  
**Expected behavior:** All timestamps as `TIMESTAMPTZ` with timezone-aware UTC in application code.  
**Evidence:** `app/services/auth_service.py:31-33`, `app/database/schema.sql:14-15, 326-337`, `README.md:414` (known limitation DB-019).  
**Impact:** Timezone bugs in reporting, scheduling, audit logs when server TZ ≠ UTC.  
**Root cause:** Deferred migration.  
**Solution:** Migrate all `TIMESTAMP` → `TIMESTAMPTZ`; update `_utcnow()` to return aware UTC; audit all datetime comparisons.  
**Dependencies:** Alembic migration; test all datetime-dependent features.  
**Tests required:** Timezone shift test (server TZ=America/New_York).  
**Severity:** High | **Priority:** P1 | **Complexity:** M

### GAP-006: Portfolio Forecast Uses Moving Average, Not Fitted Model
**Category:** Forecasting  
**Current behavior:** `ForecastService.portfolio()` (line 112-168) computes 7-day moving average per product, labels it with the selected model name (Prophet/ARIMA/Ensemble), but never fits the actual model.  
**Expected behavior:** Portfolio should either (a) run actual model per product (cached), or (b) clearly label as "baseline projection" with no model claim.  
**Evidence:** `app/services/forecast_service.py:113` comment: "Lightweight forecast summary — uses 7-day moving average, no model fitting." UI shows "Model" column with Prophet/ARIMA/Ensemble label (`app/templates/ai/forecast.html:71`).  
**Impact:** Users believe per-product Prophet/ARIMA forecasts exist; they don't.  
**Root cause:** Performance optimization (model fitting is slow) without UI transparency.  
**Solution:** Option A: Background job fits models for all products hourly, caches results. Option B: Rename column to "Method" and show "7-day MA (baseline)" honestly.  
**Dependencies:** `app/utils/cache.py` (TTLCache), existing 1-hour portfolio cache.  
**Tests required:** Verify portfolio model column matches actual model used.  
**Severity:** High | **Priority:** P1 | **Complexity:** M

### GAP-007: No Multi-Line Purchase Orders
**Category:** Procurement  
**Current behavior:** `purchase_orders` table (`schema.sql:119-134`) has single `product_id`, `quantity`, `unit_cost`. No line items.  
**Expected behavior:** PO header + multiple line items (product, qty, unit_cost, received_qty). Partial receipt per line. Invoice matching (3-way match).  
**Evidence:** `app/services/po_service.py`, `app/repositories/po_repo.py`, `app/routes/ui.py` (kanban board).  
**Impact:** Real procurement requires multi-line POs; current model forces one PO per product.  
**Root cause:** Simplified data model.  
**Solution:** Add `purchase_order_lines` table; migrate existing POs; update PO service + UI.  
**Dependencies:** `purchase_orders` table, `products`, `suppliers`.  
**Tests required:** Multi-line PO create → partial receive → invoice match → close.  
**Severity:** High | **Priority:** P1 | **Complexity:** M

### GAP-008: No Shipment / Logistics Execution
**Category:** Logistics  
**Current behavior:** No shipment, carrier, tracking, route, POD, or freight cost tables.  
**Expected behavior:** Shipment creation from pick/pack, carrier assignment, tracking number, delivery ETA, proof of delivery, freight cost allocation.  
**Evidence:** Absent from schema, services, routes, templates.  
**Impact:** "Logistics optimization" in product name unsupported.  
**Root cause:** Out of scope for current MVP.  
**Solution:** Add `shipments`, `carriers`, `tracking_events`, `proof_of_delivery` tables + services.  
**Dependencies:** Warehouse execution (GAP-003) must exist first.  
**Tests required:** Shipment create → carrier assign → track → POD → cost allocate.  
**Severity:** High | **Priority:** P2 | **Complexity:** XL

### GAP-009: No Safety Stock / Reorder Point Calculation
**Category:** Inventory Optimization  
**Current behavior:** `reorder_point` is a manual field on `products`. No service-level target, lead-time demand, demand variability, or lead-time variability calculation.  
**Expected behavior:** ROP = lead_time_demand + safety_stock; safety_stock = Z × √(LT×σ²_d + d²_avg×σ²_LT); service-level configurable per ABC class.  
**Evidence:** `app/services/product_service.py` validates `reorder_point` but doesn't compute it. `inventory-demand-planning` skill documents the formulas.  
**Impact:** Reorder points are guesswork; stockouts or excess inventory.  
**Root cause:** Not implemented.  
**Solution:** Add `ReplenishmentService` with `calculate_rop(product_id, service_level)`, `calculate_safety_stock()`, `suggest_reorder_points()`.  
**Dependencies:** Lead time history (from PO receipts), demand history (movements).  
**Tests required:** ROP calculation matches textbook formula; service-level achieved in simulation.  
**Severity:** High | **Priority:** P1 | **Complexity:** M

### GAP-010: No Transfer Recommendations / Multi-Warehouse Balancing
**Category:** Inventory Optimization  
**Current behavior:** Products have single `warehouse` field. No transfer logic, no multi-echelon planning.  
**Expected behavior:** Transfer recommendations based on warehouse-level demand, stock imbalance, transfer cost vs. stockout cost.  
**Evidence:** `products.warehouse` is single value; no `transfers` table.  
**Impact:** Multi-warehouse networks cannot optimize stock distribution.  
**Root cause:** Single-warehouse assumption in data model.  
**Solution:** Add `warehouse_locations`, `stock_balances` (product × warehouse), `transfer_orders`, `transfer_recommendations`.  
**Dependencies:** Multi-warehouse product model (GAP-003).  
**Tests required:** Transfer recommendation reduces total network stock while maintaining service level.  
**Severity:** Medium | **Priority:** P2 | **Complexity:** L

### GAP-011: ETL Concurrency & Observability Gaps
**Category:** Data Engineering  
**Current behavior:** `run_etl()` uses PG advisory lock (`_ETL_LOCK_KEY=774001`) — single-run guard. Stages commit individually with watermark held at incoming `last_id` until final stage (good). But: no metrics export, no alerting on ETL failure, no data quality checks beyond orphaned FKs.  
**Expected behavior:** ETL metrics (rows processed, duration, watermark lag) exported; alerts on failure/staleness; data quality rules (completeness, freshness, referential integrity).  
**Evidence:** `app/database/etl.py:469-738`, `app/routes/ui.py:54-57` (in-process lock for `/monitoring/run-etl`).  
**Impact:** Silent ETL failures → stale reports → wrong decisions.  
**Root cause:** Monitoring focused on ML models, not data pipeline.  
**Solution:** Add ETL metrics to `monitoring` schema; Prometheus exporter; alert on `last_run_at` staleness > 24h.  
**Dependencies:** `etl_state` table, `monitoring` tables.  
**Tests required:** ETL failure injection → alert fires; watermark lag > threshold → alert.  
**Severity:** Medium | **Priority:** P1 | **Complexity:** M

### GAP-012: Rate Limiting Storage Not Production-Ready
**Category:** Security / Scalability  
**Current behavior:** `RATELIMIT_STORAGE_URI=memory://` (default). `render.yaml` uses `workers: 1` to avoid the issue.  
**Expected behavior:** Redis-backed rate limiting for multi-worker deployments.  
**Evidence:** `app/config/settings.py:68-76`, `render.yaml:30`, `app/extensions.py` (Flask-Limiter config).  
**Impact:** Cannot scale horizontally; rate limits reset per worker.  
**Root cause:** Deferred to "when scaling out."  
**Solution:** Document Redis requirement for production; update `render.yaml` to provision Redis; test multi-worker.  
**Dependencies:** Redis instance, `flask-limiter` Redis support.  
**Tests required:** Multi-worker rate limit test (100 req/min across 4 workers).  
**Severity:** High | **Priority:** P1 | **Complexity:** S

### GAP-013: No API Versioning / OpenAPI Documentation
**Category:** API / Integration  
**Current behavior:** `/api/*` and `/ai/*` endpoints exist with consistent JSON envelope. No version prefix (`/api/v1/`), no OpenAPI spec, no deprecation policy.  
**Expected behavior:** `/api/v1/` prefix; OpenAPI 3.0 spec generated; versioning strategy documented.  
**Evidence:** `app/routes/api.py`, `app/routes/ai.py` — no versioning.  
**Impact:** Breaking changes cannot be managed; external integrations fragile.  
**Root cause:** Not prioritized.  
**Solution:** Add Flask-RESTX or apispec; mount blueprints under `/api/v1/`; generate `openapi.json`.  
**Dependencies:** All API routes.  
**Tests required:** Contract tests against OpenAPI spec.  
**Severity:** Medium | **Priority:** P2 | **Complexity:** M

### GAP-014: Accessibility Gaps (WCAG 2.1 AA)
**Category:** Accessibility  
**Current behavior:** Some ARIA labels present (`base.html:96-97`, `ai-features.js`), semantic HTML used, dark mode toggle. But: icon-only buttons lack `aria-label` (e.g., `base.html:96` nav-toggle), focus outlines inconsistent, table headers not always scoped, color contrast unverified.  
**Expected behavior:** All interactive elements keyboard-accessible; focus visible; contrast ≥ 4.5:1; screen-reader labels on all controls.  
**Evidence:** `app/templates/base.html`, `app/static/css/style.css`, `app/static/js/ai-features.js`.  
**Impact:** Excludes users with disabilities; legal risk in some jurisdictions.  
**Root cause:** No automated a11y testing in CI.  
**Solution:** Add `axe-core` to test suite; fix reported violations; document a11y checklist.  
**Dependencies:** `pytest`, Playwright.  
**Tests required:** `axe` scan on all authenticated pages.  
**Severity:** Medium | **Priority:** P1 | **Complexity:** M

### GAP-015: No E2E Tests / Critical User Flows Untested
**Category:** Testing  
**Current behavior:** 40+ test files covering unit, API, auth, services, security, ML smoke, ETL, reports. No Playwright E2E tests.  
**Expected behavior:** E2E tests for: login → dashboard → inventory → create product → record movement → reorder alert → PO create → receive → verify stock.  
**Evidence:** `tests/` directory — no `test_e2e.py` or Playwright config.  
**Impact:** Regressions in critical flows undetected.  
**Root cause:** E2E testing deferred.  
**Solution:** Add Playwright config; implement Page Object Model for key pages; run in CI.  
**Dependencies:** `playwright` package, CI browser support.  
**Tests required:** 5 critical flows minimum.  
**Severity:** High | **Priority:** P1 | **Complexity:** M

### GAP-016: Model Monitoring Baselines Not Persisted Per Model
**Category:** ML Operations  
**Current behavior:** `MonitoringRepository.baseline_metrics()` queries `forecast_monitoring_metrics` but baseline is computed from first evaluation window, not a fixed training-period baseline. No model version tracking.  
**Expected behavior:** Baseline MAE/MAPE fixed at model promotion time; degradation measured against that baseline; model version stored with predictions.  
**Evidence:** `app/monitoring/degradation.py:7-23`, `app/services/forecast_service.py:90-92` (baseline from repo), `app/database/schema.sql:359-381` (monitoring tables).  
**Impact:** Degradation detection compares recent window to recent window — misses gradual drift.  
**Root cause:** Baseline logic conflates "first evaluation" with "training baseline."  
**Solution:** Add `model_version` to `forecast_predictions`; persist baseline at promotion; compare current to promoted baseline.  
**Dependencies:** Model promotion workflow (not yet implemented).  
**Tests required:** Simulate drift → alert fires at correct threshold.  
**Severity:** Medium | **Priority:** P1 | **Complexity:** M

### GAP-017: No Backup Encryption Key Rotation / Restore Testing
**Category:** Operations / Security  
**Current behavior:** `BACKUP_ENCRYPTION_KEY` optional (derives from `SECRET_KEY`). `system_backups` table tracks metadata. Render managed PG provides daily backups + PITR. No documented restore procedure or quarterly test.  
**Expected behavior:** Documented RPO/RTO; encryption key rotation procedure; quarterly restore drill with checksum verification.  
**Evidence:** `app/config/settings.py:98`, `app/database/schema.sql:441-457`, `README.md:233-239`.  
**Impact:** Data loss unrecoverable in disaster; encryption key compromise = all backups compromised.  
**Root cause:** Operational procedure not documented.  
**Solution:** Write runbook: backup schedule, encryption key management, restore steps, test calendar.  
**Dependencies:** Render/PostgreSQL backup features.  
**Tests required:** Quarterly restore to staging; verify data integrity.  
**Severity:** Medium | **Priority:** P2 | **Complexity:** S (documentation)

### GAP-018: Idempotency Keys Table Exists But Not Fully Integrated
**Category:** API / Data Integrity  
**Current behavior:** `idempotency_keys` table (`schema.sql:494-502`) and `@idempotent()` decorator (`app/utils/idempotency.py`) exist. Applied to API write endpoints (`api.py:182, 202, 221, 255, 271, 293`). Not used in UI form POSTs.  
**Expected behavior:** All mutating operations (API + UI) idempotent; duplicate submissions safe.  
**Evidence:** `app/utils/idempotency.py`, `app/routes/api.py` decorators.  
**Impact:** Double-submit on slow network creates duplicate movements/POs/products.  
**Root cause:** UI forms use standard POST-Redirect-GET without idempotency key.  
**Solution:** Add idempotency key to all forms; validate in service layer.  
**Dependencies:** `idempotency_keys` table, `@idempotent` decorator.  
**Tests required:** Double-submit test for each mutating endpoint.  
**Severity:** Medium | **Priority:** P1 | **Complexity:** S

### GAP-019: Forecast Horizon Not Validated Against Data Sufficiency
**Category:** Forecasting  
**Current behavior:** `forecast_run` accepts any `horizon` (default 90). Prophet requires ≥14 points; ARIMA requires ≥20. Fallback to moving average silently.  
**Expected behavior:** Validate horizon ≤ reasonable multiple of history length; warn if horizon > history; reject if insufficient data for selected model.  
**Evidence:** `app/ml/forecasting.py:71, 111`, `app/routes/ai.py:41-48`.  
**Impact:** User requests 365-day forecast on 30 days of data → gets moving average without knowing.  
**Root cause:** Silent fallback design.  
**Solution:** Return `model_used` field (already present); add `data_sufficiency` warning in response; UI shows warning banner.  
**Dependencies:** Forecast response schema.  
**Tests required:** Horizon > history → warning returned; model_used = moving_average.  
**Severity:** Medium | **Priority:** P1 | **Complexity:** S

### GAP-020: No Soft Delete / Archival Policy for Core Entities
**Category:** Data Governance  
**Current behavior:** `products`, `suppliers`, `users` have `deleted_at` column (soft delete). `movements`, `purchase_orders`, `audit_log` are hard-delete only. No archival policy, no retention schedule.  
**Expected behavior:** Consistent soft-delete or archival for all entities; retention policy documented; GDPR/privacy compliance for user data.  
**Evidence:** `schema.sql:24, 40, 61` (deleted_at on products/suppliers/users), `schema.sql:63-73, 119-134` (no deleted_at on movements/POs).  
**Impact:** Accidental hard delete loses audit trail; no compliance-ready deletion.  
**Root cause:** Inconsistent pattern.  
**Solution:** Add `deleted_at` to movements/POs (with FK `ON DELETE RESTRICT` → `SET NULL`); add retention config; implement purge job.  
**Dependencies:** FK constraints, audit triggers.  
**Tests required:** Soft delete → excluded from lists; hard delete blocked by FK; purge job respects retention.  
**Severity:** Low | **Priority:** P2 | **Complexity:** M

---

## D. Critical Workflow Traces

### Authentication: Login
```
UI (auth/login.html) 
  → POST /auth/login (auth.py:16-52) 
  → AuthService.authenticate() (auth_service.py:185-217) 
  → UserRepository.find_by_username() (user_repo.py:23-27) 
  → sp_user_find_by_username (procedures.sql) 
  → users table 
  → UserRepository.verify_password() (werkzeug check_password_hash) 
  → UserRepository.record_login() → sp_user_record_login 
  → UserRepository.create_session() → sp_session_create 
  → user_sessions table 
  → trg_log_session_create (triggers.sql:70-96) → audit_log 
  → login_user() (Flask-Login, session cookie only) 
  → redirect to dashboard
```
**Missing links:** ✅ All present. **Gap:** Process-local lockout (GAP-004).

### Inventory: Stock Receipt (IN Movement)
```
UI (inventory page → "Receive" modal) 
  → POST /api/movements (api.py:289-308) 
  → MovementService.record() (movement_service.py:30-104) 
  → ProductRepository.find() → sp_product_find 
  → MovementRepository.record() → sp_movement_record (procedures.sql) 
  → movements table (INSERT) 
  → products.current_stock += quantity (UPDATE, row lock) 
  → trg_validate_movement (triggers.sql:243-270) — validates product FK 
  → trg_log_movement_create (triggers.sql:275-300) → audit_log 
  → AuditRepository.record() (best-effort) 
  → notify_movement() (notification_service.py)
```
**Missing links:** ✅ All present. Atomic via `sp_movement_record` (DB-002 fix).

### Procurement: PO Create → Receive
```
UI (purchase-orders kanban → "Create PO") 
  → POST /api/purchase-orders (api.py:267-285) 
  → POService.create() (po_service.py) 
  → PurchaseOrderRepository.create() → sp_po_create 
  → purchase_orders table (status=draft) 
  → trg_log_po_change (triggers.sql:305-328) → audit_log
  
UI (kanban → drag to "approved" → "in_transit" → "received") 
  → PurchaseOrderRepository.transition() → sp_po_transition (procedures.sql) 
  → Validates state machine (draft→approved→in_transit→received) 
  → On "received": products.current_stock += qty, on_order -= qty 
  → Idempotent: re-applying "received" is no-op (test_db_integrity_fixes.py:208-213)
```
**Missing links:** ❌ No multi-line PO (GAP-007), ❌ No partial receipt per line, ❌ No invoice matching.

### Forecasting: Run Forecast
```
UI (ai/forecast.html → select product/horizon/model → "Run forecast") 
  → POST /ai/forecast/run (ai.py:37-56) 
  → ForecastService.run() (forecast_service.py:23-43) 
  → ProductRepository.find() 
  → MovementRepository.daily_for_product() → sp_movement_daily_for_product (180 days) 
  → forecast_with_prophet/arima/ensemble (forecasting.py:69-167) 
  → Falls back to _moving_average_forecast if libs unavailable or insufficient data 
  → ForecastRepository.save() → forecast_cache (upsert via uq_forecast_cache_key) 
  → _update_monitoring() → MonitoringRepository.save_predictions_batch() 
  → forecast_predictions table 
  → evaluate_all() → MonitoringRepository.save_metrics() 
  → forecast_monitoring_metrics table
```
**Missing links:** ❌ No train/test split (GAP-001), ❌ Portfolio uses MA not model (GAP-006), ❌ No model version tracking (GAP-016).

### Anomaly Detection: Run Detection
```
UI (ai/anomaly.html → select product/contamination → "Detect anomalies") 
  → POST /ai/anomaly/run (ai.py:86-108) 
  → AnomalyService.run_for_product_enriched() (anomaly_service.py:74-152) 
  → MovementRepository.daily_for_product() (120 days) 
  → detect_anomalies_enriched() (anomaly.py:276-404) 
    → detect_anomalies_isoforest() (Isolation Forest or z-score fallback) 
    → enrich_anomalies() → risk_level, recommended_action 
    → forecast_deviation layer (if forecast available) 
    → rule_based_peaks layer (3× rolling avg) 
    → deduplicate by day (keep highest risk) 
  → spc_zscore_analysis() → SPC chart data 
  → AnomalyRepository.save() → anomaly_log (upsert via uq_anomaly_detection) 
  → Returns enriched anomalies + SPC data
```
**Missing links:** ❌ No ground-truth labels (GAP-002), ❌ No precision/recall measurement, ❌ Risk levels uncalibrated.

### ETL: Warehouse Rebuild
```
CLI: python migrate.py etl 
  → etl_database() (connection.py) 
  → run_etl() (etl.py:469-738) 
  → pg_try_advisory_lock(_ETL_LOCK_KEY) — single-run guard 
  → Incremental: watermark from etl_state['last_movement_id'] 
  → Stage 1: _build_dim_dates (dim_date) 
  → Stage 2: _build_dims (dim_warehouse, dim_product, dim_supplier) 
  → Stage 3: _build_movement_facts (fact_movement_daily) 
  → Stage 4: _build_inventory_facts (fact_inventory_daily, stock walk clamping) 
  → Validation: _validate_warehouse_consistency, _validate_product_consistency 
  → _run_warehouse_etl() → etl_full_build() (etl_procedures.sql:401-466) 
    → SCD merges (dim_product_scd, dim_supplier_scd, dim_warehouse_scd, dim_user) 
    → Event facts (fact_login_events, fact_session_activity, fact_signup_events, fact_audit_daily) 
  → Watermark advanced to max_id
```
**Missing links:** ❌ No metrics export (GAP-011), ❌ No alerting on failure/staleness.

---

## E. AI Quality Report

### Forecasting

| Metric | Value | Notes |
|--------|-------|-------|
| **Data target** | `movements.type='OUT'` daily totals per product (180 days) | `MovementRepository.daily_for_product` sums OUT only — correct for demand |
| **Training window** | Last 180 days (configurable via `days` param) | No chronological split; all data used for fitting |
| **Test window** | None (in-sample only) | **Critical gap** |
| **Backtesting status** | Not implemented | No rolling-origin, no walk-forward |
| **Baselines** | Moving average (7-day) used in portfolio; seasonal naive not tested | Baseline comparison only in monitoring (MAE vs baseline MAE) |
| **MAE** | Computed in `monitoring.metrics.evaluate_all()` | Only on evaluated predictions (last 30 days of history) |
| **RMSE** | Computed | Same as above |
| **WAPE** | Not computed | Weighted MAPE (sum|e|/sum|a|) — better for intermittent demand |
| **MAPE valid count** | Tracked (`mape_valid_count` in `evaluate_all`) | Zero-demand days excluded — correct |
| **Bias (mean error)** | Computed (`mean_error`) | Positive = underprediction |
| **Interval coverage** | Not measured | Prophet/ARIMA produce intervals; coverage % never checked |
| **Model used** | Returned in `model` field (prophet/arima/ensemble/moving_average) | Portfolio lies — shows selected model but uses MA |
| **Fallback use** | Moving average when libs missing or data < 14 (Prophet) / 20 (ARIMA) | Silent; UI shows selected model name |
| **Runtime** | Measured client-side (`performance.now()`) | Server-side not logged |
| **Limitations** | No intermittent demand handling (Croston/SBA); no promotional causal factors; no new-product analog forecasting; horizon not validated; no prediction interval calibration check | |

### Anomaly Detection

| Metric | Value | Notes |
|--------|-------|-------|
| **Label source** | None (no human labels, no synthetic benchmark) | **Critical gap** |
| **Positives / Negatives** | Unknown | No labeled dataset |
| **True Positives** | Not measured | |
| **False Positives** | Not measured | Alert fatigue unknown |
| **False Negatives** | Not measured | Missed anomalies unknown |
| **True Negatives** | Not measured | |
| **Precision** | Not measured | |
| **Recall** | Not measured | |
| **F1** | Not measured | |
| **False-positive rate** | Not measured | |
| **PR-AUC** | Not measured | |
| **Thresholds** | `ANOMALY_ZWARNING=2.0`, `ANOMALY_ZHIGH=3.0`, `ANOMALY_ZCRITICAL=4.0`, `ANOMALY_CONTAMINATION=0.05` | Configurable via env; not tuned per product |
| **Contamination** | 0.05 default (Isolation Forest) | Heuristic; not optimized |
| **Alert volume** | Tracked via `AnomalyService.alert_summary()` | Counts by risk/status; no trend |
| **Review rate** | Not tracked | `status` field exists (new/reviewed/acknowledged/resolved) but no analytics |
| **Limitations** | No seasonality adjustment (promotions, holidays cause false positives); no promotion calendar integration; risk level heuristics unvalidated; forecast deviation layer uses 40% threshold hardcoded; rule-based peaks use 3× multiplier hardcoded; deduplication by day loses multi-method confirmation | |

**If these values cannot be measured:** **Not measured** — requires (1) synthetic anomaly injection with known ground truth, (2) human labeling workflow for historical anomalies, (3) precision/recall dashboard per detection method, (4) alert fatigue tracking (alerts/day, review rate, time-to-resolve).

---

## F. Prioritized Roadmap

| Priority | Feature or Fix | Reason | Dependencies | Acceptance Criteria |
|----------|----------------|--------|--------------|---------------------|
| **P0** | Implement rolling-origin backtesting for forecasts | Cannot claim accuracy without out-of-sample evidence | `app/monitoring/metrics.py`, `ForecastService` | Backtest runs on demand; MAE/RMSE/WAPE/MASE/bias/coverage persisted per product/model/horizon; baseline (seasonal naive, MA) included |
| **P0** | Move login lockout & rate limiting to Redis/DB | Multi-worker deployments bypass security | `rate_limit_state` table exists; Redis provisioning | 5 failed logins → lockout across all workers; rate limits shared |
| **P0** | Fix portfolio forecast to use actual model or label honestly | Misleading "Model" column in UI | `ForecastService.portfolio`, cache layer | Portfolio either runs actual model (cached) or shows "7-day MA (baseline)" with no model claim |
| **P0** | Migrate naive UTC → TIMESTAMPTZ | Timezone bugs in production | Alembic migration; all datetime code | All timestamps timezone-aware; server TZ change doesn't break logic |
| **P1** | Add anomaly labeling workflow + synthetic benchmark | Cannot validate detection quality | `AnomalyRepository` (status field), `anomaly_log` table | Label UI (confirm/reject); synthetic benchmark with injected anomalies; precision/recall/F1 per method displayed |
| **P1** | Implement safety stock / ROP calculation service | Reorder points are manual guesswork | Lead time history (PO receipts), demand history | `ReplenishmentService.calculate_rop()` matches textbook formula; service-level configurable per ABC class |
| **P1** | Add multi-line PO + partial receipt + invoice match | Real procurement requires multi-line | `purchase_orders` table, `products`, `suppliers` | PO header + lines; partial receive per line; 3-way match (PO/Receipt/Invoice) |
| **P1** | Add E2E tests (Playwright) for 5 critical flows | Regressions undetected in CI | Playwright, CI browser | Login→Dashboard→Inventory→Movement→Reorder→PO→Receive→Stock verified |
| **P1** | Fix accessibility (WCAG 2.1 AA) | Legal/inclusion risk | axe-core, template fixes | Zero axe violations on authenticated pages; keyboard nav works; contrast ≥4.5:1 |
| **P1** | Add ETL observability (metrics, alerts) | Silent ETL failures → stale reports | `etl_state`, `monitoring` tables | ETL duration/rows/watermark lag exported; alert if `last_run_at` > 24h |
| **P2** | Warehouse execution workflows (receive→putaway→pick→pack→ship) | "Logistics optimization" requires execution | Location hierarchy (zone/aisle/rack/bin) | ASN→Receive→Putaway→Pick→Pack→Ship→POD flow works end-to-end |
| **P2** | Multi-warehouse stock balancing + transfer recommendations | Network optimization missing | Multi-warehouse product model | Transfer recommendations reduce total stock while maintaining service level |
| **P2** | API versioning + OpenAPI spec | Integration stability | All API routes | `/api/v1/` prefix; `openapi.json` generated; contract tests pass |
| **P2** | Backup/restore runbook + quarterly drill | Disaster recovery untested | Render PG backups | Documented RPO/RTO; encryption key rotation; quarterly restore verified |
| **P2** | Model promotion workflow + versioned baselines | Degradation detection compares wrong baseline | `forecast_predictions`, `forecast_monitoring_metrics` | Baseline fixed at promotion; degradation vs. promoted baseline; model version in predictions |

---

## G. Release-Readiness Decision

**Decision: Ready for controlled student pilot only**

**Evidence:**
- ✅ Core inventory CRUD, movements, PO lifecycle work correctly (validated by `test_db_integrity_fixes.py`)
- ✅ Authentication, RBAC, audit logging, CSP, parameterized SQL — security baseline solid
- ✅ Forecasting UI functional; models run (Prophet/ARIMA/ensemble) with fallback
- ✅ Anomaly detection runs; alerts generated with risk levels and recommendations
- ✅ ETL pipeline builds star schema incrementally with advisory lock guard
- ✅ Reports query fact tables (verified by `test_reports_fact.py`)
- ❌ **Forecast accuracy claims (>90%) have zero out-of-sample evidence** (GAP-001)
- ❌ **Anomaly detection precision/recall completely unknown** (GAP-002)
- ❌ **No warehouse execution or logistics workflows** — "logistics optimization" unsupported (GAP-003, GAP-008)
- ❌ **Multi-worker deployment breaks login lockout and rate limiting** (GAP-004, GAP-012)
- ❌ **No E2E tests; critical flows unverified** (GAP-015)
- ❌ **Naive UTC timestamps — timezone bugs inevitable** (GAP-005)

**Not production-ready because:** Business-critical decisions (reorder, safety stock, anomaly response) rely on unverified ML outputs. Horizontal scaling breaks security controls. Core logistics workflows absent.

---

## H. Final Checklist

### Business Capability
- [ ] Inventory intelligence (forecasting, anomalies, EOQ) — **Partial** (accuracy unverified)
- [ ] Warehouse management — **Missing** (no execution workflows)
- [ ] Procurement management — **Partial** (no multi-line PO, no invoice match)
- [ ] Replenishment planning — **Missing** (no safety stock/ROP calculation)
- [ ] Logistics execution — **Missing** (no shipments, carriers, POD)
- [ ] Supply-chain optimization — **Missing** (no multi-echelon, transfers, budget constraints)

### Data Correctness
- [x] Negative stock prevented (DB trigger + sp_movement_record)
- [x] SKU uniqueness enforced (partial unique index)
- [x] PO state machine enforced (sp_po_transition)
- [x] Soft delete on products/suppliers/users
- [ ] Consistent soft delete on movements/POs
- [ ] TIMESTAMPTZ migration complete
- [ ] Referential integrity on all FKs (dim_product.supplier_id lacks FK — known)

### Forecasting
- [ ] Rolling-origin backtesting implemented
- [ ] Out-of-sample MAE/RMSE/WAPE/MASE reported
- [ ] Baseline models (seasonal naive, MA) included
- [ ] Interval coverage measured
- [ ] Bias tracked
- [ ] Horizon validated against data sufficiency
- [ ] Portfolio uses actual model or labeled honestly
- [ ] Model version tracked with predictions
- [ ] Promotion workflow with fixed baseline

### Anomaly Detection
- [ ] Synthetic benchmark with ground truth
- [ ] Human labeling workflow
- [ ] Precision/recall/F1 per method
- [ ] PR-AUC reported
- [ ] False-positive rate tracked
- [ ] Alert fatigue metrics (volume, review rate, time-to-resolve)
- [ ] Risk levels calibrated against outcomes
- [ ] Seasonal/promotional adjustment

### Security
- [x] Parameterized SQL (stored procedures)
- [x] CSP nonces + security headers
- [x] Password hashing (werkzeug)
- [x] Session cookies (HttpOnly, Secure, SameSite=Lax)
- [x] Browser-session only (no remember-me)
- [x] Rate limiting on auth/API (but memory:// only)
- [ ] Redis-backed rate limiting for multi-worker
- [ ] Login lockout shared across workers
- [ ] Dependency vulnerability scanning (npm audit / pip-audit in CI)
- [ ] Secret scanning in CI

### Accessibility
- [ ] WCAG 2.1 AA audit (axe-core in CI)
- [ ] All form inputs have connected labels
- [ ] All icon buttons have aria-label
- [ ] Focus visible on all interactive elements
- [ ] Color contrast ≥ 4.5:1
- [ ] Reduced motion respected
- [ ] Keyboard navigation works end-to-end

### Testing
- [x] Unit tests (services, validators, ML smoke)
- [x] API contract tests
- [x] Auth/RBAC tests
- [x] DB integrity tests
- [ ] E2E tests (Playwright) for 5 critical flows
- [ ] Load tests (locust/k6)
- [ ] Contract tests (OpenAPI)
- [ ] Property-based tests (hypothesis)
- [ ] Forecast backtest tests
- [ ] Anomaly benchmark tests

### Performance
- [x] Dashboard query batching (14→11)
- [x] Plotly lazy-loaded
- [x] Context processor cached (60s)
- [x] Reports cache TTL 1h (fact tables)
- [x] AI portfolio cached 1h
- [x] ETL non-blocking thread
- [ ] Redis cache for multi-worker
- [ ] Connection pooling tuned (pgbouncer)
- [ ] Model fitting offloaded to background worker

### Deployment
- [x] Render Blueprint (render.yaml)
- [x] Gunicorn single worker (workers=1)
- [x] Health check endpoint (/api/health)
- [x] Auto-deploy on main
- [ ] Multi-worker with Redis rate limiting
- [ ] Horizontal scaling documented
- [ ] Graceful shutdown (SIGTERM handling)
- [ ] Blue-green / canary deployment capability

### Documentation
- [x] README.md (setup, architecture, API, ML, known limitations)
- [x] PRODUCT.md (product definition)
- [x] AGENTS.md (agent guide)
- [ ] API OpenAPI spec
- [ ] Runbook (backup/restore, incident response, scaling)
- [ ] Model retraining/approval process
- [ ] Data retention policy
- [ ] Accessibility statement
- [ ] Security hardening guide
