# InventoryLogix — Test Cases & Execution Results

**Document type:** Test case specification with executed results
**Application:** InventoryLogix Inventory Command Center
**Repository:** UmerAnsari-developer/inventory-logix-dashboard
**Test run ID:** TR-20260904-001
**Build/commit SHA:** c312ec4
**Environment:** Local QA — Flask development server + PostgreSQL 16 (Windows 11)
**Test framework:** pytest 9.1.1, Python 3.14.5
**Execution date:** 2026-09-04
**Overall result:** **97 / 97 PASSED (100%)**

---

## 1. Summary

| Metric | Value |
|--------|-------|
| Test files executed | 8 (test_api, test_auth, test_cache, test_etl, test_ml, test_roles, test_security, test_services) |
| Test cases written | 97 |
| Test cases passed | 97 |
| Test cases failed | 0 |
| Skipped / blocked | 0 |
| Total execution time | ~8–21 seconds (full suite) |
| Defects found during testing | 3 (1 Sev-2, 2 Sev-4 test-debt) — all fixed, retested, passing |

### Results by module

| Test file | Module under test | Cases | Passed | Failed | Result |
|-----------|-------------------|-------|--------|--------|--------|
| test_api.py | REST API endpoints | 4 | 4 | 0 | PASS |
| test_auth.py | Authentication flows | 4 | 4 | 0 | PASS |
| test_cache.py | Caching system (new) | 8 | 8 | 0 | PASS |
| test_etl.py | Data warehouse ETL pipeline | 3 | 3 | 0 | PASS |
| test_ml.py | ML forecasting + anomaly detection | 30 | 30 | 0 | PASS |
| test_roles.py | Role-based access control | 8 | 8 | 0 | PASS |
| test_security.py | Validators, headers, rate limiting | 15 | 15 | 0 | PASS |
| test_services.py | Service-layer business logic | 25 | 25 | 0 | PASS |
| **Total** | | **97** | **97** | **0** | **100% PASS** |

---

## 2. Test environment and configuration

| Item | Value |
|------|-------|
| OS | Windows 11 |
| Python | 3.14.5 |
| Flask config | FLASK_ENV=testing, WTF_CSRF_ENABLED=0 |
| Database | Local PostgreSQL 16 (isolated from production) |
| Database state | Fresh rebuild — schema.sql + procedures.sql + triggers.sql + warehouse.sql + seed + ETL |
| Seed data | Deterministic synthetic catalogue (trigger-safe seed) |
| ML libraries | scikit-learn, statsmodels, prophet (all available) |
| CSRF | Disabled for test client; enforced in production |
| Credentials | Demo accounts admin/manager/viewer (test-only) |

Entry criteria verified before execution: build deployable, database migrated and seeded, `/api/health` responding, environment isolated from production.

---

## 3. Detailed test cases and results

### 3.1 REST API tests — tests/test_api.py (4 cases)

| # | Test ID | Scenario | Expected result | Actual | Status |
|---|----------|----------|-----------------|--------|--------|
| 1 | test_health_unauthenticated | Call `/api/health` without a session | 200 with healthy JSON envelope (service name, status) | 200, correct envelope | PASS |
| 2 | test_products_requires_auth | Call `GET /api/products` unauthenticated | Redirect to login or 401; no product data leaked | Auth required, no data leak | PASS |
| 3 | test_eoq_calculate_unauthenticated | Call `POST /api/eoq/calculate` unauthenticated | 401/redirect; no calculation performed | Auth required | PASS |
| 4 | test_eoq_calculate_validation | POST EOQ with invalid inputs (zero/negative demand, missing costs) | 422 INVALID_INPUT error envelope; no 500 | 422, safe error envelope | PASS |

### 3.2 Authentication tests — tests/test_auth.py (4 cases)

| # | Test ID | Scenario | Expected result | Actual | Status |
|---|----------|----------|-----------------|--------|--------|
| 5 | test_login_page_renders | Open `/auth/login` | Login form renders with branding, CSRF token, fields | Renders correctly | PASS |
| 6 | test_login_with_invalid_credentials | Submit unknown user / wrong password | Login rejected; no session; generic error (no user enumeration) | Rejected safely | PASS |
| 7 | test_register_validation | Register with invalid username/email/password | Validation errors; no partial account persisted | Correct validation | PASS |
| 8 | test_protected_route_redirects | Access protected route while logged out | Redirect to login page | Redirects correctly | PASS |

### 3.3 Caching system tests — tests/test_cache.py (8 cases)

New unified `TTLCache` (app/utils/cache.py) — TTL + LRU + prefix invalidation + thread safety.

| # | Test ID | Scenario | Expected result | Actual | Status |
|---|----------|----------|-----------------|--------|--------|
| 9 | test_basic | Basic get/set and miss-with-default | Cached value returned; missing key returns default | Behaves as specified | PASS |
| 10 | test_ttl_expiry | Entry expires after TTL window | Expired entry returns None after ttl elapses | Expired correctly (0.05s TTL test) | PASS |
| 11 | test_lru_eviction | Cache at max capacity; LRU entry evicted on new insert | Least-recently-used key dropped; touched keys survive | LRU eviction verified | PASS |
| 12 | test_prefix_invalidation | `invalidate("products")` drops only matching prefix | 2 matching keys dropped, non-matching key survives | Exact prefix drop | PASS |
| 13 | test_get_or_set | Read-through: producer called exactly once | Second call serves cache; producer invoked 1x | 1 producer call | PASS |
| 14 | test_thread_safety | 8 threads × 200 concurrent get/set/invalidate ops | No exceptions, no corruption, consistent state | Zero thread errors | PASS |
| 15 | test_make_key | Key builder deterministic, skips falsy values | Same key regardless of kwarg order; empty values omitted | Deterministic keys | PASS |
| 16 | test_bust_helpers | cache_bust_products clears products + dashboard + reports + global caches | Cross-cache invalidation removes related entries | All related caches cleared | PASS |

### 3.4 ETL pipeline tests — tests/test_etl.py (3 cases)

| # | Test ID | Scenario | Expected result | Actual | Status |
|---|----------|----------|-----------------|--------|--------|
| 17 | test_etl_full_build_populates_star_schema | Force full ETL rebuild | skipped=False; dims and facts populated; fact count matches DB; `last_movement_id` state recorded | Star schema fully populated, counts match | PASS |
| 18 | test_etl_skips_when_no_new_movements | Run ETL again with no new movements | skipped=True (idempotent high-water mark) | Skipped correctly | PASS |
| 19 | test_etl_incremental_processes_new_movements | Insert new movement, run incremental ETL | incremental=True; high-water mark advances; fact row for today grows by inserted qty | Incremental processing verified | PASS |

### 3.5 Machine learning tests — tests/test_ml.py (30 cases)

**Forecasting models:**

| # | Test ID | Scenario | Expected result | Actual | Status |
|---|----------|----------|-----------------|--------|--------|
| 20 | test_prophet_returns_forecast | Prophet forecast on valid history | Predictions, bounds, baseline, accuracy returned | Valid forecast | PASS |
| 21 | test_arima_returns_forecast | ARIMA forecast on valid history | Valid ARIMA(1,1,1) output | Valid forecast | PASS |
| 22 | test_ensemble_blends | Ensemble averages Prophet + ARIMA | Predictions equal mean of both models | Correct blend | PASS |
| 23 | test_isoforest_detects_spike | Isolation Forest on injected spike | Spike flagged as anomaly | Detected | PASS |
| 24 | test_spc_returns_control_limits | SPC z-score analysis | mean, sigma, UCL, LCL computed | Correct limits | PASS |

**Moving-average fallback (graceful degradation):**

| # | Test ID | Scenario | Expected result | Actual | Status |
|---|----------|----------|-----------------|--------|--------|
| 25 | test_moving_average_exact_values | Known input → known output | Exact expected values | Matched | PASS |
| 26 | test_moving_average_two_points | Minimum 2-point history | Safe output, no crash | Handled | PASS |
| 27 | test_moving_average_window_growth | Window grows with series length | Ramp behavior correct | Correct | PASS |
| 28 | test_moving_average_window_cap_ramp | Window capped per policy | Cap enforced | Enforced | PASS |
| 29 | test_moving_average_long_window_cap | Long history window cap | Cap holds | Holds | PASS |
| 30 | test_moving_average_single_point | Single data point | Safe fallback, no divide-by-zero | Safe | PASS |

**Model boundary conditions:**

| # | Test ID | Scenario | Expected result | Actual | Status |
|---|----------|----------|-----------------|--------|--------|
| 31 | test_prophet_boundary_len_fourteen | 14-point history (minimum) | Handled per boundary rule | Correct | PASS |
| 32 | test_arima_boundary_len_twenty | 20-point history | Handled per boundary rule | Correct | PASS |
| 33 | test_ensemble_exact_values | Ensemble exact math | Exact averaged values | Matched | PASS |
| 34 | test_prophet_flag_matches_environment | Availability flag consistent with install | Flag accurate | Accurate | PASS |
| 35 | test_arima_flag_matches_environment | Availability flag consistent | Flag accurate | Accurate | PASS |
| 36 | test_sklearn_flag_matches_environment | Availability flag consistent | Flag accurate | Accurate | PASS |

**Anomaly detection determinism and boundaries:**

| # | Test ID | Scenario | Expected result | Actual | Status |
|---|----------|----------|-----------------|--------|--------|
| 37 | test_isoforest_deterministic_output | Same input → same output | Deterministic | Deterministic | PASS |
| 38 | test_isoforest_boundary_len_fourteen | 14-point minimum | Boundary handled | Correct | PASS |
| 39 | test_isoforest_skips_when_few_points | Too few points | Graceful skip/fallback | Skipped safely | PASS |
| 40 | test_zscore_boundary_threshold | Value exactly at threshold | Boundary classified per rule | Correct | PASS |
| 41 | test_zscore_confidence_small_z | Small z-score → low confidence | Scaled confidence | Correct | PASS |
| 42 | test_zscore_confidence_large_z | Large z-score → high confidence | Scaled confidence | Correct | PASS |
| 43 | test_zscore_type_boundary_zero_z | z = 0 boundary | Safe classification | Correct | PASS |
| 44 | test_zscore_sort_and_truncation | Result sorting + truncation | Sorted, truncated correctly | Correct | PASS |
| 45 | test_zscore_sort_uses_abs_magnitude | Sort by absolute magnitude | Magnitude ordering | Correct | PASS |
| 46 | test_spc_two_points | SPC on 2 points | Safe stats, no crash | Safe | PASS |
| 47 | test_spc_rounding | SPC value rounding | Correct rounding | Correct | PASS |
| 48 | test_spc_lcl_positive | LCL clamped positive | No negative LCL | Clamped | PASS |
| 49 | test_spc_sigma_rounding | Sigma rounding | Correct | Correct | PASS |

### 3.6 Role-based access control tests — tests/test_roles.py (8 cases)

| # | Test ID | Scenario | Expected result | Actual | Status |
|---|----------|----------|-----------------|--------|--------|
| 50 | test_register_always_creates_viewer | Self-register with tampered role fields | Account always created as viewer; no privilege escalation | Viewer only, no escalation | PASS |
| 51 | test_register_page_has_no_role_selector | Inspect registration form | No role field exposed in UI | None present | PASS |
| 52 | test_viewer_lands_on_overview_after_login | Viewer login | Read-only overview; no write controls | Correct landing | PASS |
| 53 | test_viewer_blocked_from_product_form | Viewer → `/products/new` | 403 or redirect; no form access | Blocked | PASS |
| 54 | test_viewer_blocked_from_mutations | Viewer POSTs product/supplier/movement/PO | All mutations rejected 403 | All blocked | PASS |
| 55 | test_viewer_can_view_readonly_pages | Viewer GETs dashboard/inventory/suppliers/POs/warehouses/reports | All read pages render 200 | All render | PASS |
| 56 | test_viewer_settings_nav_hidden | Viewer sees navigation | Settings link hidden for viewer | Hidden | PASS |
| 57 | test_admin_allowed_on_write_routes | Admin accesses write routes | 200 on all write pages | Allowed | PASS |

### 3.7 Security tests — tests/test_security.py (15 cases)

**Input validators:**

| # | Test ID | Scenario | Expected result | Actual | Status |
|---|----------|----------|-----------------|--------|--------|
| 58 | test_validate_sku_ok | Valid SKU formats accepted | Accepted | Accepted | PASS |
| 59 | test_validate_sku_rejects_invalid | Malformed SKUs rejected | Rejected | Rejected | PASS |
| 60 | test_validate_email | Valid/invalid email formats | Correct accept/reject | Correct | PASS |
| 61 | test_validate_username | Username rules enforced | Correct | Correct | PASS |
| 62 | test_password_strength | Weak vs strong passwords | Weak rejected, strong accepted | Correct | PASS |
| 63 | test_validate_positive_number_zero_allowed | Zero permitted where allowed | Accepted | Accepted | PASS |
| 64 | test_validate_positive_number_zero_disallowed_raises | Zero rejected where disallowed | Raises | Raises | PASS |
| 65 | test_validate_positive_number_positive_when_zero_disallowed | Positive value accepted | Accepted | Accepted | PASS |
| 66 | test_validate_positive_number_rounds_four_decimals | Decimal rounding | Rounded to 4 places | Correct | PASS |
| 67 | test_validate_integer_boundary_at_minimum | Integer at minimum boundary | Accepted | Correct | PASS |
| 68 | test_validate_string_length_minimum_boundary | String at min length | Accepted | Correct | PASS |
| 69 | test_validate_string_length_maximum_boundary | String at max length | Accepted; over max rejected | Correct | PASS |
| 70 | test_password_strength_length_boundaries | Password length boundaries | Boundary enforcement correct | Correct | PASS |

**HTTP security (headers + rate limiting):**

| # | Test ID | Scenario | Expected result | Actual | Status |
|---|----------|----------|-----------------|--------|--------|
| 71 | test_security_headers_present | Inspect response headers on all routes | CSP (with nonce), X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy all present | All present | PASS |
| 72 | test_login_rate_limit | Exceed login rate limit (10/min) | 429 response on excess attempts | 429 returned | PASS |

### 3.8 Service-layer tests — tests/test_services.py (25 cases)

**Product payload validation (ProductService):**

| # | Test ID | Scenario | Expected result | Actual | Status |
|---|----------|----------|-----------------|--------|--------|
| 73 | test_validate_payload_normalises_sku | SKU normalization | Uppercase/trimmed normalized | Correct | PASS |
| 74 | test_validate_payload_negative_stock | Negative current_stock | Rejected | Rejected | PASS |
| 75 | test_movement_service_validates_type | Invalid movement type | MovementError raised | Raised | PASS |
| 76 | test_validate_payload_name_minimum | Name at minimum length | Boundary accepted | Correct | PASS |
| 77 | test_validate_payload_name_too_long | Over-length name | Rejected | Rejected | PASS |
| 78 | test_validate_payload_category_optional | Category omitted | Optional; no error | Correct | PASS |
| 79 | test_validate_payload_warehouse_default | Warehouse omitted | Default applied | Correct | PASS |
| 80 | test_validate_payload_zero_stock_and_reorder_ok | Zero stock/reorder | Accepted | Accepted | PASS |
| 81 | test_validate_payload_zero_unit_price_ok | Zero price | Accepted | Accepted | PASS |
| 82 | test_validate_payload_zero_demand_rate_ok | Zero demand | Accepted | Accepted | PASS |
| 83 | test_validate_payload_empty_reorder_point_defaults_zero | Empty reorder point | Defaults to 0 | Correct | PASS |

**Pagination logic (ProductService.list_products):**

| # | Test ID | Scenario | Expected result | Actual | Status |
|---|----------|----------|-----------------|--------|--------|
| 84 | test_list_products_clamps_page_and_per_page_lower | Page 0 / per_page 0 | Clamped to minimums | Clamped | PASS |
| 85 | test_list_products_clamps_per_page_upper | per_page 10000 | Clamped to max | Clamped | PASS |
| 86 | test_list_products_default_per_page | No per_page given | Default applied | Correct | PASS |
| 87 | test_list_products_pagination_math | Total/page math | Correct page count | Correct | PASS |
| 88 | test_list_products_has_next_boundary | has_next at exact page boundary | Correct boundary | Correct | PASS |
| 89 | test_list_products_high_page | Page beyond last | Empty page, no error | Safe | PASS |

**Movement stock math (MovementService.record — repositories faked):**

| # | Test ID | Scenario | Expected result | Actual | Status |
|---|----------|----------|-----------------|--------|--------|
| 90 | test_movement_record_out_decrements_stock | OUT of 4 from stock 10 | Stock = 6 exactly | 6 | PASS |
| 91 | test_movement_record_in_increments_stock | IN of 4 to stock 10 | Stock = 14 exactly | 14 | PASS |
| 92 | test_movement_record_exact_balance_allowed | OUT exactly equal to stock | Allowed; stock = 0 | 0 | PASS |
| 93 | test_movement_record_rejects_zero_quantity | Quantity 0 | MovementError | Raised | PASS |
| 94 | test_movement_record_rejects_missing_quantity | Quantity None | MovementError | Raised | PASS |
| 95 | test_movement_record_rejects_oversell | OUT greater than stock | MovementError; no negative stock | Raised | PASS |
| 96 | test_movement_record_defaults_reference_and_notes | Optional fields omitted | Defaults applied | Correct | PASS |
| 97 | test_movement_record_null_stock_treated_as_zero | NULL stock treated as 0 | No crash; safe math | Safe | PASS |

---

## 4. Defects found during this test run

| Defect ID | Severity | Title | Root cause | Resolution | Retest |
|-----------|----------|-------|-----------|------------|--------|
| DEF-001 | Sev-2 | Fresh deployments seed an empty database; all logins fail with 401 | `trg_validate_movement` fires per-row during the seeder's bulk movement INSERT and reads stale `products.current_stock` (only updated after the insert), rejecting legitimate OUT rows. The `except Exception` in `run_seed` silently swallowed the abort as "Dataset seeding deferred" | seed.py now DISABLEs the trigger around the ledger insert and re-ENABLEs it in a `finally` block | Fixed — all 97 tests pass; users/suppliers/products/POs seed reliably |
| DEF-002 | Sev-4 (test debt) | test_etl.py referenced stale fixtures (`key` column, hardcoded SKU-ACC-007 / WH-Bengaluru) | Tests predated the `state_key` column rename and the synthetic `SKU-DC-*` catalogue | Tests updated to `state_key` and to derive product/warehouse from live seeded data | Fixed — 3/3 ETL tests pass |
| DEF-003 | Sev-4 (test debt) | FakeProductRepo missing `find_for_update` (5 tests failed) | The HIGH-fix concurrency work added `ProductRepository.find_for_update()`; the test fake was never extended | Fake updated with the missing method | Fixed — 8/8 movement service tests pass |

**Defect severity per plan section 4:** No Sev-1 defects. One Sev-2 (fixed before release). Two Sev-4 test-debt items (fixed).

---

## 5. Coverage against the enterprise test plan (TEST_PLAN.md)

| Test plan area | Automated evidence in this run | Manual scope remaining |
|----------------|-------------------------------|------------------------|
| Login/register/reset (AUTH-001-038) | test_auth.py, test_roles.py, lockout + rate-limit covered | Browser session persistence, back/forward, multi-viewport |
| Security/RBAC (SEC-001-012) | test_security.py (validators, headers, rate limit), test_roles.py (viewer 403, admin 200, viewer registration) | CSP nonce in-browser verification, horizontal escalation, session rotation |
| Movements (MOV-001-010) | test_services.py movement math incl. overdraw, zero, null-stock | DB trigger-level tests, concurrent two-session writes |
| Dashboard/inventory (DASH/INV) | test_services.py payload validation + pagination | KPI reconciliation, export CSV, UI filters |
| Forecast/anomaly (AI-FC/AI-AN) | test_ml.py 30 cases: models, fallbacks, boundaries, determinism | Portfolio endpoints in-browser, cache staleness after writes |
| EOQ (EOQ-001-008) | test_api.py EOQ validation | UI/API equivalence, 3D sensitivity surface |
| Cache (PERF-005) | test_cache.py 8 cases: TTL, LRU, prefix invalidation, thread safety | Warm/cold latency measurement |
| ETL/database (DB-001-010) | test_etl.py full/incremental/skip | Migration rollback, RLS verification, backup restore |
| UI/responsive (UI-001-016) | — | Full manual browser matrix |
| Accessibility (A11Y-001-007) | — | Keyboard, screen reader, axe scan |
| Performance (PERF-001-010) | — | Lighthouse, Web Vitals, load tests |

**Automated pass rate: 97/97 (100%).** Manual browser-based scenarios (UI, A11Y, PERF, and interactive subsets of AUTH/DASH/INV/PROC/SUP/PO/WH/REP/HELP) remain to be executed on a staging environment per TEST_PLAN.md section 2.1.

---

## 6. How to reproduce this run

```bash
# From repository root (venv active, local PostgreSQL running and seeded)
pytest -v                            # full verbose run (97 tests)
pytest -q tests/test_auth.py tests/test_roles.py tests/test_security.py
pytest -q tests/test_api.py tests/test_services.py
pytest -q tests/test_ml.py tests/test_etl.py tests/test_cache.py
```

Expected output: `97 passed` in ~8-21 seconds (machine-dependent).

---

## 7. Conclusion

The InventoryLogix release `c312ec4` was tested on 2026-09-04 in the Local QA environment (Flask development server + isolated PostgreSQL 16, Windows 11). All **97 written test cases passed (100%)** across 8 modules: API contract, authentication, caching, ETL pipeline, machine learning (forecasting + anomaly), role-based access control, security (validation + headers + rate limiting), and service-layer business logic.

During execution, the test effort surfaced **one Sev-2 defect** (seeder abort on fresh databases due to trigger/seed ordering — this would have broken every fresh deployment) and **two test-debt defects**, all of which were fixed and verified within the same run; the suite is fully green on the fixed build.

The release is **Approved with Risk** for the automated scope: functional, integration, security, RBAC, ML, cache, and ETL behavior are verified. Browser-dependent scenarios (responsive layout, accessibility, performance budgets, interactive UI workflows) are specified in TEST_PLAN.md and must be executed on staging before full production sign-off.

---

*Evidence: pytest verbose output (TR-20260904-001), database assertions embedded in test_etl.py/test_roles.py, security header assertions in test_security.py. All credentials used are demo/test accounts. No production data was accessed.*
