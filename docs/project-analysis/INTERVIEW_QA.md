# InventoryLogix — Interview Questions & Answers

**Merged from both analysis passes · September 10, 2026**
All answers grounded in the repository. Honesty rules applied: synthetic
metrics flagged, no fabricated adoption, no attributed developer intent.

---

## A) Client Discovery & Sales (10)

**Q1. What problem does InventoryLogix solve?**
A single dashboard for stock health, reorder alerts, purchasing, and
analytics, plus AI assistance (demand forecasting, anomaly detection, EOQ
order quantities). It replaces spreadsheet-based inventory decisions with
data-driven ones: the reorder queue flags SKUs where
`current_stock <= reorder_point AND on_order <= 0`, and the EOQ engine
computes cost-optimal quantities from per-product costs. Framing: a
working full-stack reference implementation, not a battle-tested
commercial product.

**Q2. Who uses it, and how many warehouses/users?**
Three roles: viewer (read-only), manager/admin (write, enforced
server-side). Self-registration always creates a viewer, so newcomers
can't mutate data. Seed data spans 10 warehouses. No tenant isolation —
one deployment serves one company.

**Q3. What does deployment look like?**
Push to GitHub → Render Blueprint creates a free PostgreSQL + web service,
wires DATABASE_URL/SECRET_KEY, and runs Gunicorn (1 worker × 2 threads).
First boot auto-applies the schema, seeds demo data, and runs the ETL.
Health check at /api/health; autoDeploy on push to main.

**Q4. How is my data protected?**
Parameterized SQL everywhere (all CRUD through stored procedures with
placeholders), per-request CSP nonces, CSRF, rate limiting (login 10/min,
API writes 30/min), account lockout (5 fails → 15 min), hashed passwords,
secure cookies, and a DB-level audit trail. Honest caveat: rate limits and
lockout state are in-process memory, safe in the current single-worker
deployment.

**Q5. Can it connect to my ERP or accounting system?**
No — there are no ERP/accounting connectors, and we say so plainly.
Integration today: REST API, CSV export, and CSV import for seeding only.
An ERP bridge would be new development.

**Q6. What does the ML actually do?**
Demand forecasting (Prophet with weekly seasonality, ARIMA, or an
ensemble, with confidence bands) and anomaly detection (Isolation Forest
plus SPC ±3σ control charts), cached 1 hour portfolio-wide. They inform
reorder decisions; they don't autonomously place orders.

**Q7. Is the "AI savings" number real money?**
No, and we say so: it's a model-derived comparison of EOQ ordering versus
a hypothetical order-monthly baseline on estimated cost parameters. It
demonstrates the EOQ math; it is not a measured financial result.
Landing stats are likewise hardcoded demo values.

**Q8. What happens when the ML libraries are missing?**
Graceful degradation: without Prophet/statsmodels or with too few points,
a moving-average model with σ-bands runs; without scikit-learn, anomaly
detection falls back to pure z-score. The app never fails because a model
didn't fit. Honest limitation: the fallback reports a fixed 78% accuracy —
a cosmetic heuristic, not a computed metric.

**Q9. What's the pricing?**
None — it's an MCA mini-project with no billing/licensing code. Running
cost on the reference deployment is Render's free tier plus optional
SendGrid.

**Q10. Why not just use Zoho Inventory or Odoo?**
For a real business at scale, they should — mature ERPs have connectors,
support, and multi-tenancy this project deliberately doesn't. This
project's value is educational/evaluative: how such a system is built
end-to-end (SCD Type 2 warehouse, trigger-enforced stock integrity,
EOQ/forecasting analytics, security hardening), with full source control
at zero license cost.

---

## B) Technical Interview (15)

**Q1. Explain the architecture of InventoryLogix.**
Layered: Jinja2 templates (Chart.js/Plotly/Three.js/GSAP) → Flask
blueprints (auth, ui, api, ai) → services → repositories → stored
procedures → PostgreSQL with triggers and a star-schema warehouse.
Factory pattern (`create_app()`) allows test-isolated apps and one boot
path shared by WSGI, CLI, and Alembic. Honest nuance: the layering is
enforced on the API side; the UI blueprint uses inline SQL for its
analytical routes (~56 sites), backstopped by DB triggers that enforce
integrity regardless of the writing layer.

**Q2. Why stored procedures instead of an ORM? Tradeoffs?**
All CRUD routes through `sp_*` functions called as parameterized SELECTs
from repository classes. Benefits: the SQL injection surface collapses,
integrity rules live next to the data, and analytics run set-based in the
DB. Tradeoffs we accept: no compile-time model checking, harder unit
testing (DB required), and validation logic split between Python and
PL/pgSQL.

**Q3. Why enforce movement validation in a database trigger?**
`trg_validate_movement` (BEFORE INSERT) auto-populates SKU from
product_id, rejects bad FKs, and raises on movements that would drive
stock negative. DB-level is the only place the rule can't be bypassed —
REST API, UI, a future script, or a manual psql session all pass through
the same trigger. Service-layer validation is a fast-fail convenience; the
trigger is the enforcement backstop.

**Q4. Explain SCD Type 2 as used here.**
Type 2 keeps history by inserting a new row per change instead of
overwriting. `dim_product_scd` (and supplier/warehouse/user variants)
carry valid_from, valid_to, is_current, and a row_hash. The merge
functions diff the operational row against the current SCD row; on change
they stamp the old row closed and insert a new current row, skipping
writes when the hash is unchanged. Facts join to the dimension as-of a
date, so you can ask "what did this product look like last month."

**Q5. How is the ETL incremental, and what is stock-walk clamping?**
A high-water mark (`etl_state['last_movement_id']`) skips runs with no new
movements; otherwise only the affected date range is reprocessed and the
watermark advanced, in one transaction (rollback on failure; force=True
TRUNCATEs and rebuilds). Because seeded history doesn't always net out
cleanly, `fact_inventory_daily` is built by walking current stock
backwards day-by-day and clamping any negative intermediate value to 0
(counted and logged) — a pragmatic guard against history inconsistencies
rather than a silently corrupt fact table.

**Q6. State the EOQ formula and its assumptions.**
EOQ = √(2DS/H): demand rate D, ordering cost S, holding cost H; total
cost = (D/Q)·S + (Q/2)·H. Assumes constant deterministic demand, fixed
per-order cost, linear holding cost, no quantity discounts, and no
lead-time variability. Because real inputs are estimates, the service
also builds a cost curve and a 3D sensitivity surface (demand × ordering
cost) so fragility of the optimum is visible.

**Q7. Prophet vs ARIMA here — when does each fail, and what's the fallback?**
Prophet handles weekly cycles, missing data, and outliers well, but is a
heavy dependency and needs ≥14 points. ARIMA(1,1,1) is lightweight but
assumes a simple differenced structure and needs ≥20 points with an
inferrable frequency; it can diverge on strongly seasonal series. The
ensemble averages both, hedging single-model bias. Every call is guarded:
any exception or missing library degrades to a deterministic moving
average with 1.96σ bands — the app never 500s because a model didn't fit.

**Q8. How does anomaly detection work?**
Two layers: (1) IsolationForest (contamination 0.05, 80 trees, seeded) on
the daily movement series, each anomaly annotated with its z-score and a
spike/drop classification; (2) SPC z-score analysis producing mean, σ,
UCL/LCL (μ±3σ) for a control chart. Below 14 points, without sklearn, or
on forest errors it falls back to pure z-score detection. Honest caveat:
the forest is fit on a single feature, so its marginal value over the
z-score channel is small — it's there for the API shape and ranking.

**Q9. How are sessions and RBAC implemented?**
Flask-Login with `session_protection = "strong"` (session invalidated on
fingerprint change) plus a user_loader fetching from Postgres. Beyond the
cookie, login creates a user_sessions row (token, IP, user-agent) so
triggers log logins/logouts to the audit trail, enabling the
active-sessions view at /monitoring. Authorization is two stacked
decorators: @login_required then @roles_required/@write_roles_required —
admin/manager pass, anything else 403s.

**Q10. How do CSRF and CSP nonces work here?**
CSRF: Flask-WTF CSRFProtect app-wide with an 8-hour token time limit
(aligned to session lifetime). CSP: each request generates a 24-byte
url-safe nonce in before_request; templates tag every inline script and
import map with it; the after_request header sets script-src 'self'
'nonce-…' plus a CDN allowlist. Net: no unsafe-inline for scripts, so an
injected inline script won't execute.

**Q11. Rate limiting — configuration and its caveat?**
Flask-Limiter keyed on remote address, memory storage, 200/min default,
plus per-route: login 10/min, register 5/min, forgot 5/hour, API writes
30/min, movements 60/min, AI runs 30/min. The caveat I volunteer: memory
storage is per-process, so limits are only globally accurate under the
current 1-worker config; add workers and each gets its own counter. The
Redis env var exists for the upgrade; it's shadowed today by a hardcoded
constructor argument.

**Q12. Why ThreadedConnectionPool and 1 worker × 2 threads?**
The pool avoids a fresh TCP/TLS handshake to a remote DB per request;
connections are checked out onto Flask's g per request and returned at
teardown. Gunicorn runs 1 worker × 2 threads deliberately, documented in
the repo: the app holds in-process state (limiter counters, lockout
tracker, TTL caches, a bootstrap-once flag), so multiple worker processes
would each have independent copies — inconsistent limits, lockouts, and
stale cache views. One worker with threads sidesteps that at the cost of
a single-process throughput ceiling.

**Q13. Describe the caching layers and the per-process caveat.**
One thread-safe TTLCache class (LRU + expiry + prefix invalidation)
instantiated per concern — products 120s, dashboard 60s, reports 300s, AI
portfolio 1h, etc. Writes call explicit cache_bust_* prefix drops; reads
use get_or_set read-through. Caveats: in-memory (each worker would have
its own; busts don't propagate), the AI portfolio cache is never busted
(1h staleness by design), and a manual ETL only busts the monitoring
cache.

**Q14. What specifically breaks if you scale to multiple workers?**
Concretely: (1) Flask-Limiter memory:// — each worker enforces its own
login budget, so the effective limit multiplies; (2) the lockout
tracker — a brute-force spread across workers wouldn't accumulate to 5
failures; (3) TTLCache — busts only reach the local process, so other
workers serve up-to-TTL-stale dashboards; (4) cost — a 20-connection
pool per worker can exhaust Postgres connections (PgBouncer or a capped
pool needed). The single-worker shape is a deliberate sizing decision,
not an oversight.

**Q15. Why does CSP still allow unsafe-inline styles and un-SRI'd CDNs?**
style-src keeps 'unsafe-inline' because the app injects per-element style
tokens; style injection is far lower-risk than script injection (no
direct code execution) — an accepted, documented tradeoff. Scripts load
from three CDNs without Subresource Integrity — a compromised CDN could
serve malicious JS within the allowlist. The hardening path is
self-hosting the JS with SRI hashes; not done in this academic build.

---

## C) Viva / Business Defense (10)

**Q1. Why did you choose Flask over Django?**
The project's center of gravity is custom SQL — stored procedures,
triggers, a hand-built star schema. Django's ORM and admin would fight
that architecture at every step. Flask gives a thin factory, explicit
blueprints, and free choice of psycopg2 pooling, Flask-Login, Flask-WTF,
and Flask-Limiter. Django's batteries were mostly things we weren't going
to use.

**Q2. Why PostgreSQL over MySQL?**
Three concrete reasons from the code: (1) PL/pgSQL procedures and
triggers are first-class — 74 function definitions that would be far
clunkier in MySQL's routine syntax; (2) the warehouse leans on
PostgreSQL specifics — partial indexes on is_current, IS DISTINCT FROM
in SCD merges, jsonb audit details, ON CONFLICT upserts; (3) the
deployment targets (Render/Supabase) are Postgres-native. Plus native
Row-Level Security for the Supabase surface.

**Q3. Why a monolith instead of microservices?**
One team, one repo, one database — no organizational or scaling pressure
justifies the operational cost of service meshes and distributed
transactions. The monolith keeps clear internal layering
(routes → services → repositories → DB) so it's decomposable later.

**Q4. What is a data warehouse doing in a mini-project?**
The analytical half of inventory management: fact tables with SCD Type 2
dimensions let reports and monitoring query pre-aggregated history
instead of scanning 180K raw movements per page. It demonstrates classic
BI patterns — incremental watermark ETL, idempotent full rebuilds,
single-transaction consistency. An MCA project that shows both OLTP and
OLAP design earns more depth than one more CRUD form.

**Q5. How does seeding real data make results credible?**
Forecasting and anomaly detection on uniformly random synthetic data
would "work" trivially; real supply-chain data has weekly cycles, bursts,
and noise that stress the models meaningfully. The loader reads the
actual DataCo SMART SUPPLY CHAIN CSV (118 products with real
demand/ordering/holding costs, up to 150 suppliers) with a deterministic
synthetic fallback when absent. Caveat: costs and stock levels are still
seed-derived.

**Q6. What are the known limitations?**
Listed openly: single-tenant; no ERP/accounting connectors; in-memory
auth state (lockout, limiter) that only holds up in the single-worker
deployment; per-process caches; demo metrics (AI savings is a policy
counterfactual, landing stats hardcoded, fallback accuracy fixed at 78%);
the background ETL thread has an app-context bug; a database credential
is committed in a config file (flagged for rotation); two AI portfolio
endpoints lack rate limits.

**Q7. Did real users use this in production?**
No — it's an academic project with no production users, and I won't imply
otherwise. What it does have: a deployed demo, a 97-test pytest suite
covering auth, RBAC, the REST API, security helpers, ML smoke tests, and
service validation, and role-based demo accounts for evaluation.

**Q8. What did you struggle with technically?**
Three documented from the history: (1) platform constraints — Render's
free tier blocks outbound SMTP, which broke password-reset emails until
SendGrid HTTPS API support was added; (2) blocking operations — the ETL
rebuild took 10-60 seconds synchronously, freezing the request, so it
moved to a background thread; (3) frontend weight — Plotly's 3.5MB loaded
everywhere hurt load times, leading to lazy-loading on chart pages only
and a dedicated mobile performance fix. Each fix is a visible commit plus
a README performance-table entry.

**Q9. What's the future roadmap?**
Grounded in the code's own gaps: stateless auth state via Redis so
multi-worker scaling works; reorder notifications via the existing
mailer; PO receipt reconciliation (status flip should create the inbound
movement and clear on_order); forecast-driven reorder points (the forecast
cache, supplier lead times, and ROP formula all exist — they just aren't
wired together); an admin user-management UI (the stored procedures are
already written); out-of-sample forecast backtesting to replace the
synthetic accuracy numbers.

**Q10. How would you productionize this?**
(1) Rotate the committed credential and add a SECRET_KEY fail-fast;
(2) rate-limit and input-clamp the AI portfolio endpoints; (3) fix the
ETL thread's app context and add a concurrency guard; (4) externalize
state — Redis for rate limits, lockout, and shared caches; (5) scale to
multiple workers with PgBouncer; (6) move ETL to a scheduled job with
retry/visibility; (7) self-host CDN JS with SRI; (8) add monitoring
(Sentry) on top of the existing health endpoint; (9) onboarding — an
import pipeline and role provisioning instead of seeded demo data.

---

*Generated: September 10, 2026 · Merged from both analysis passes*
