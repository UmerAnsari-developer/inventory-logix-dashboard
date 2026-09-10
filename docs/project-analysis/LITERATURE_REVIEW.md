# InventoryLogix — Literature Review & Prior-Art Comparison

**Merged from both analysis passes · September 10, 2026**

Verification key: **[V]** verified online via official docs/Wikipedia
during analysis · **[C]** canonical reference, widely known, not
re-verified online · **[E3]** general knowledge, not verified.

---

## 1. Academic References

### 1.1 Economic Order Quantity (EOQ) — Harris (1913); Wilson (1934)

- **Source [V]:** Harris, F. W. (1913), "How many parts to make at once",
  *Factory, The Magazine of Management* 10:135–136,152; Wilson, R. H.
  (1934), "A Scientific Routine for Stock Control", *Harvard Business
  Review* 13:116–128. (Wikipedia, "Economic order quantity" —
  https://en.wikipedia.org/wiki/Economic_order_quantity)
  *(Note: an earlier in-repo draft cited the title as "How Much to Make
  of What" — corrected here.)*
- **Problem:** Optimal order quantity minimizing total cost (ordering +
  holding).
- **Approach:** Q\* = √(2DK/h) balances costs that move in opposite
  directions with order size.
- **Technology:** plain math, implemented in `app/utils/helpers.py`.
- **Relevance:** Core model of the EOQ calculator; applied to 118
  products with real per-product costs; `eoq_service.py` adds a 3D
  sensitivity surface.
- **Limitations:** assumes constant demand and lead time; no quantity
  discounts; no stockout costs. The project's answer is *visualizing
  sensitivity* rather than solving stochasticity.

### 1.2 Facebook Prophet — Taylor & Letham (2017 preprint / 2018 journal)

- **Source [V]:** facebook.github.io/prophet — "additive model where
  non-linear trends are fit with yearly, weekly, and daily seasonality…
  works best with strong seasonal effects and several seasons of
  historical data… robust to missing data, shifts in trend, and
  outliers"; preprint peerj.com/preprints/3190. Journal version:
  *The American Statistician* 71(1), 2018 [C].
  *(Note: the earlier draft conflated preprint year/venue — corrected.)*
- **Problem:** Business time-series forecasting with seasonality,
  missing data, and outliers.
- **Approach:** Additive regression: piecewise-linear/logistic trend +
  Fourier-series seasonality + holiday effects.
- **Technology:** `prophet` Python library (Stan backend).
- **Relevance:** Primary forecasting model; weekly seasonality only
  (`daily/yearly off`), consistent with short daily histories.
- **Limitations:** heavy dependency chain (hence the guarded import);
  docs advise several seasons of history; this repo needs ≥14 points and
  otherwise degrades honestly to moving average.

### 1.3 ARIMA — Box & Jenkins (1970)

- **Source [C]:** G. E. P. Box & G. M. Jenkins, *Time Series Analysis:
  Forecasting and Control*, Holden-Day, 1970.
- **Problem:** Forecasting non-stationary autoregressive series.
- **Approach:** ARIMA(p,d,q): autoregression + differencing + moving
  average of errors; order selected per series.
- **Technology:** `statsmodels` — here fixed ARIMA(1,1,1), 95% CI.
- **Relevance:** Secondary forecasting model; complements Prophet in the
  ensemble (simple average of predictions and bounds).
- **Limitations:** needs stationarity (via differencing); no automatic
  seasonality; sensitive to outliers; manual tuning — fixed (1,1,1) is an
  acknowledged simplification.

### 1.4 Isolation Forest — Liu, Ting & Zhou (2008)

- **Source [V]:** sklearn IsolationForest docs (algorithm description;
  contamination semantics, range (0, 0.5]) —
  https://scikit-learn.org/stable/modules/outlier.html. Original ICDM
  2008 paper (cs.nju.edu.cn PDF) not fetched [C].
- **Problem:** Unsupervised anomaly detection.
- **Approach:** Random recursive partitioning; outliers isolate with
  short average path lengths; `contamination` = expected outlier
  proportion.
- **Technology:** `scikit-learn` — IsolationForest(contamination=0.05,
  n_estimators=80, random_state=42).
- **Relevance:** Primary anomaly detector over daily movement series;
  anomalies ranked by |z-score|, classified spike/drop; z-score fallback
  on missing library or <14 points. Note: sklearn default is 100 trees;
  80 is a deliberate smaller forest, fine at this scale.
- **Limitations:** requires contamination parameter; univariate fit here
  (single reshaped column) — marginal over its own z-score fallback; no
  explanation of scores ("confidence" is a synthetic formula).

### 1.5 Statistical Process Control — Shewhart (1931)

- **Source [C]:** W. A. Shewhart, *Economic Control of Quality of
  Manufactured Product*, D. Van Nostrand, 1931. *(Publisher spelling
  corrected from an earlier draft's "Vanstrand".)*
- **Problem:** Distinguishing special-cause from common-cause variation.
- **Approach:** Control charts: center line (process mean), UCL = μ+3σ,
  LCL = μ−3σ.
- **Technology:** `app/ml/anomaly.py:84-94` — mean, sigma, UCL, LCL
  (clamped ≥0); configurable threshold (default 3.0).
- **Relevance:** Interpretable complement to Isolation Forest; the
  degraded mode when sklearn is absent.
- **Limitations:** assumes normality; fixed limits; false alarms; no
  root-cause identification.

### 1.6 Star Schema & SCD Type 2 — Kimball & Ross (2013)

- **Source [V]:** Kimball, Ralph; Ross, Margy (2013), *The Data Warehouse
  Toolkit: The Definitive Guide to Dimensional Modeling*, 3rd ed., Wiley,
  ISBN 9781118530801 (via Wikipedia "Star schema"); SCD Type 2 = add-row
  with effective dates and/or current flag, with the warning that Type 2
  is costly when dimensions change frequently (Wikipedia "Slowly changing
  dimension").
- **Relevance:** `warehouse.sql` implements the effective-date +
  current-flag + row_hash variant on dim_product_scd / dim_supplier_scd /
  dim_warehouse_scd / dim_user, with partial indexes on is_current and
  hash-based change detection — the standard maintenance-cost mitigations.

### 1.7 Application Factory Pattern — Flask docs

- **Source [V]:** flask.palletsprojects.com/en/stable/patterns/appfactories/
  (factories enable multiple app instances and per-test configuration;
  extensions created unbound and bound via init_app).
- **Relevance:** `create_app()` (app/__init__.py:31); limiter defined
  unbound in extensions.py and initialized in the factory — exactly the
  documented shape.

### 1.8 Content Security Policy — MDN

- **Source [V]:** MDN CSP reference — nonce = random value generated per
  HTTP response; when a nonce is present the browser ignores
  'unsafe-inline'; applies to script/style elements.
- **Relevance:** `headers.py` generates `secrets.token_urlsafe(24)` per
  request; every inline script/import map carries
  `nonce="{{ csp_nonce }}"`; script-src = 'self' + nonce + CDN allowlist.

### 1.9 Rate Limiting as a Security Control — OWASP

- **Source [V]:** OWASP Cheat Sheet Series, *Denial of Service* cheat
  sheet — rate limiting as an application-level availability control.
  (Two other OWASP rate-limiting URLs returned 404 during verification.)
- **Relevance:** flask-limiter per-route limits (login 10/min, writes
  30/min, movements 60/min) plus lockout/reset throttling — matching the
  guidance. Gap: the two AI portfolio GET endpoints have no limit.

---

## 2. Existing / Similar Solutions

Rows are **E3 general knowledge** unless noted; the final row is
repo-verified [E1].

| Solution | Category | Stack | ML Features | SCD2/DW | Cost | How InventoryLogix differs |
|----------|------|------------|-------------|---------|------|-----------------------------|
| **SAP IBP** | Enterprise planning | SAP HANA, cloud | Advanced ML demand & inventory optimization | Enterprise DW (proprietary) | $$$$$ | Same concept categories at enterprise cost/complexity; Logix demonstrates them in a single-dev Flask app |
| **Oracle SCM Cloud** | Enterprise planning | OCI | Advanced planning | Proprietary | $$$$$ | Enterprise-grade vs. focused dashboard with full source access |
| **ERPNext** | OSS ERP (inventory module) | Python/Frappe, MariaDB | Reorder rules; no native forecast ML | No Kimball star by default | Free OSS | Logix adds Prophet/ARIMA + IF + EOQ 3D; PG SCD2 star + ETL |
| **Odoo Inventory** | OSS ERP module | Python/PG | Replenishment rules; ML limited/module-based | No exposed SCD2 | Free community / paid | Logix: single-purpose, transparent 65-SP layer, /ai/* endpoints, row-hash SCD2 |
| **TradeGecko (QuickBooks Commerce)** | SMB SaaS | Proprietary cloud | None native | No | $29-499/mo | Logix: ML forecasting + anomaly + EOQ 3D + open source, free |
| **inFlow Inventory** | SMB desktop/web | Proprietary (Windows-first) | ROP recommendations only | No | $110-499/mo | Logix: web-first, ensemble forecasting, anomaly detection, warehouse |
| **Unleashed** | Manufacturing SaaS | Proprietary cloud | Reporting only | No | Subscription | Logix: EOQ optimization + ML + SCD2 at zero license cost |
| **PartKeepr** | OSS parts inventory (inactive) | PHP/MySQL | None | None | Free | Logix: active ML layer, general products, warehouse with SCD2 |
| **InvenTree** | OSS parts/BOM inventory | Python/Django, PG | Stock tracking only | No SCD2 | Free | Logix adds forecasting + anomaly + EOQ + DW |
| **Snipe-IT** | OSS **asset** management | PHP/Laravel, MySQL | None (audit/depreciation) | No SCD2 | Free | Different problem (assets vs consumable stock + replenishment math) |
| **InventoryLogix** [E1] | OSS mini-project dashboard | Flask≥3.0, PostgreSQL, Plotly | Prophet+ARIMA ensemble w/ MA fallback; IF + SPC | SCD2 star + ETL | Free | — |

Honest positioning of the combination claim ("no existing solution
combines open Flask+PG stack + integrated ML forecasting + IF/SPC anomaly
+ EOQ 3D + real-dataset grounding + SCD2 + single-developer build"): it
is defensible as a *category* statement for a mini-project; as a
market-absence claim it is unverifiable and stays E3.

---

## 3. Technology Comparison

### 3.1 ML Libraries

| Library | Purpose | Pros | Cons | Used |
|---------|---------|------|------|------|
| Prophet | Time series | Easy, handles seasonality/missing data | Heavy deps, slower | Yes |
| statsmodels (ARIMA) | Statistical models | Fast, well-documented | No automatic seasonality | Yes |
| scikit-learn | ML algorithms | Comprehensive, fast | No deep learning | Yes (IsolationForest) |
| TensorFlow / PyTorch | Deep learning | State-of-the-art accuracy | Complex, GPU required | No |

Decision reasoning (engineering, not attributed intent): 14-30 daily
points is the sparse regime where classical methods beat heavy ML; the
ensemble + fallback design already tolerates missing libraries.

### 3.2 Web Frameworks

| Framework | Language | Pros | Cons | Used |
|-----------|----------|------|------|------|
| Flask | Python | Lightweight, flexible | Fewer batteries | Yes |
| Django | Python | Batteries included, admin | Heavier; ORM conflicts with SP architecture | No |
| FastAPI | Python | Async, type hints | Async unused here (sync driver, blocking ML) | No |
| Express | JavaScript | Fast, large ecosystem | No Python ML ecosystem | No |

### 3.3 Databases

| Database | Type | Pros | Cons | Used |
|----------|------|------|------|------|
| PostgreSQL | Relational | PL/pgSQL, JSONB, RLS, window functions | Setup complexity | Yes |
| SQLite | Embedded | Zero config | No server-side procedures/pooling/RLS | No |
| MySQL | Relational | Fast, popular | Weaker procedures, no native RLS | No |
| MongoDB | Document | Flexible schema | No ACID stored procedures | No |

---

## 4. Research Gap

### 4.1 Current Landscape
1. **Enterprise solutions** (SAP, Oracle): comprehensive but expensive,
   implementation-team-bound, vendor lock-in.
2. **SMB solutions** (TradeGecko, inFlow): affordable but lack ML and
   optimization models.
3. **OSS ERPs** (Odoo, ERPNext): broad but without integrated
   forecasting + EOQ + warehouse analytics in one codebase.

### 4.2 Where the Hard Problems Are (and where this project honestly lands)

1. **EOQ vs stochastic demand.** The literature's answer to uncertain
   demand is (s,S)/newsvendor models. InventoryLogix does not solve this —
   it *visualizes sensitivity* so fragility is visible. A pedagogical
   mitigation, not a theoretical contribution.
2. **Forecast accuracy on sparse data.** Prophet's own docs say several
   seasons of history is ideal; this repo needs only 14/20 points and
   otherwise falls back to moving average — it degrades honestly rather
   than solving sparsity. Candor notes: fallback accuracy is hardcoded
   (78.0), and reported accuracy is in-sample MAPE on fitted values —
   optimistic versus holdout validation.
3. **SCD2 maintenance cost.** The literature warns Type 2 is costly under
   frequent dimension change. The repo mitigates operationally (row-hash
   change detection, is_current partial indexes, batch ETL) — the correct
   engineering response at 118-product scale, not a novel one.
4. **Anomaly parameters.** Fixed contamination (0.05) is a known
   limitation; the SPC z-score channel is the interpretable complement.

### 4.3 Realistic Gap Statement

InventoryLogix advances no state of the art in forecasting, optimization,
or warehousing. Its demonstrable contribution is *integration and
transparency*: the canonical techniques above exist in enterprise suites
or as disconnected libraries, but not as one open, single-developer Flask
codebase with a documented security posture and honest fallbacks. For an
MCA mini-project, that integration — plus the built-in distinction
between implemented, measured, and merely claimed value — is the
defensible academic contribution.

---

## 5. Research Directions

1. Deep-learning forecasting (LSTM/Transformer) for complex patterns —
   only with orders-of-magnitude more data.
2. Real-time/streaming anomaly detection vs. the current on-demand scans.
3. Reinforcement learning for reorder policies beyond EOQ.
4. Stochastic EOQ extensions ((s,S), newsvendor) for variable demand.
5. Optimal contamination parameter estimation for Isolation Forest on
   inventory data.
6. Cost-benefit of real-time vs batch anomaly detection.

### Open Questions
1. How does the Prophet/ARIMA ensemble compare to deep learning on this
   data volume?
2. What is the optimal contamination parameter for inventory data?
3. How should EOQ be adapted for stochastic demand?
4. What is the cost-benefit of real-time vs batch anomaly detection?

---

## 6. Unverified / Correction Notes

- Harris 1913 title corrected to "How many parts to make at once" (earlier
  in-repo draft said "How Much to Make of What").
- Prophet venue: PeerJ preprint (2017) vs The American Statistician
  71(1) (2018) — earlier draft conflated them; corrected.
- Shewhart publisher: D. Van Nostrand (not "Vanstrand").
- DataCo SMART SUPPLY CHAIN dataset: repo-verified loader
  (dataset_service.py); Kaggle page not fetched.
- All §2 vendor rows are E3 general knowledge — no vendor pages fetched;
  pricing figures are public-listing general knowledge and may be dated.
- OWASP rate-limiting URLs that 404'd during verification are noted in §1.9.

---

*Generated: September 10, 2026 · Merged from both analysis passes*
