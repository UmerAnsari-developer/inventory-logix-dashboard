# InventoryLogix — Business Guide

**Merged from both analysis passes · September 10, 2026**
Evidence levels: **E1** direct · **E2** strong inference · **E3** interpretation · **E4** unknown.
Value levels: **Implemented** · **Measured** · **Potential** · **Synthetic**.

## 1. Business Problem

### 1.1 Current Challenges

Supply chain managers and warehouse operators face:

| Challenge | Impact | Traditional Solution |
|-----------|--------|------------------|
| **Stockouts** | Lost sales, customer dissatisfaction | Manual reorder points from memory |
| **Overstocking** | High carrying costs, obsolescence | Spreadsheet tracking |
| **Demand variability** | Inaccurate forecasts | Gut feeling |
| **Anomaly detection** | Theft, damage, data errors | Manual audits |
| **Multi-warehouse coordination** | Inconsistent stock levels | Phone calls / emails |
| **Compliance** | Audit failures | Paper trails |

### 1.2 Business Need

Organizations need a system providing real-time inventory visibility,
predictive analytics for demand planning, automated reorder alerts,
optimization models for order quantities, and audit trails — at a cost
an SME can absorb. InventoryLogix's deployment story (Render free tier,
auto schema+seed on first boot, zero license cost) targets exactly this.
[E2]

## 2. Solution Overview

InventoryLogix is an **Inventory Command Center** that:

1. **Unifies data** — real transaction data (DataCo SMART SUPPLY CHAIN,
   180K+ movements; deterministic synthetic fallback when the CSV is
   absent).
2. **Forecasts demand** — Prophet/ARIMA ensemble with confidence bands.
3. **Detects anomalies** — Isolation Forest + SPC control charts.
4. **Optimizes orders** — EOQ calculator with 3D sensitivity surfaces.
5. **Ensures compliance** — trigger-level audit logging on every mutation.

### Value by persona (implemented)

- **Supply chain analysts:** ML forecasting, anomaly detection,
  portfolio analytics, data warehouse.
- **Warehouse managers:** real-time stock visibility across 10
  warehouses, severity-sorted reorder alerts, movement tracking.
- **Procurement leads:** supplier reliability/lead-time tracking, PO
  kanban, EOQ-driven auto-draft quantities.
- **Admins:** settings and thresholds, ETL monitoring, session/login
  history. (Role promotion has no UI — direct DB only, E1.)

## 3. Daily Operating Rhythm (mapped to real pages)

Morning dashboard review → anomaly check → forecast review → reorder
queue → auto-draft or mark-ordered → PO kanban → record receipts as
movements → reports. Every page caches with automatic busting on
mutations, so KPIs refresh without manual reloads.

**Workflow gap to know about (E1):** marking a PO "received" only
changes status — it does not create the inbound movement or clear
`on_order`. Operators must record the receipt movement separately; a
partial receipt keeps the item hidden from reorder alerts until
`on_order` is resolved. This is the leakiest step in the loop and the #1
improvement candidate (a single stored-procedure change).

## 4. What Is Measured vs Not (critical honesty section)

**Measured today** — descriptive statistics of the actual (seeded)
catalogue, all live SQL: inventory value, reorder counts, stock health %,
turnover by category, ABC classes, slow-mover days idle, supplier spend,
sales trends, warehouse breakdowns. [E1]

**Synthetic — never quote as business results:**

- **"AI savings YTD"** — compares EOQ ordering vs a hypothetical
  "order monthly" policy on *estimated* costs (ordering cost hardcoded
  $50; holding cost assumed 20% of unit price). Mathematically always
  positive. It demonstrates the EOQ formula, not savings.
  (ui.py:279-308; dataset_service.py:311-313)
- **Forecast "accuracy %"** — in-sample fit; fallback fixed at 78%.
- **Landing-page KPIs and dashboard delta footers** — hardcoded demo
  values.

**Potential (unmeasured but plausible mechanisms):** fewer stockouts
from surfaced reorder alerts; lower carrying cost from EOQ-sized
orders; earlier error detection; faster PO cycles.

**Unknown:** stockout-rate reduction, carrying-cost reduction, forecast
accuracy in production, anomaly precision, adoption. No before/after
measurement exists anywhere in the repo. **A pilot with baseline capture
is the only honest path to any ROI claim.** [E4]

> Example realistic pilot: a 2-warehouse distributor reordering each SKU
> monthly from a spreadsheet. InventoryLogix surfaces below-ROP items
> daily and proposes EOQ-sized POs. The tool would *potentially* reduce
> ad-hoc reorder effort and over-ordered safety stock; actual savings
> require before/after measurement the tool does not yet perform.

## 5. Traditional vs InventoryLogix (capability comparison)

| Process | Spreadsheet era | With InventoryLogix |
|---|---|---|
| Reorder point | Memory / manual scan | Live query, severity tiers, badge on every page |
| Order quantity | Gut feel | EOQ √(2DS/H) on per-product costs + sensitivity surface |
| Movement logging | Paper/Excel retyped | One form, trigger-enforced, auto-audited |
| Error detection | Cycle counts | ML + SPC control charts |
| History | Manual pivot tables | SCD2 warehouse, 5-tab reports, MTD/YTD/prev-period math |
| Multi-warehouse | Phone/email | Warehouse filter across inventory/reports/sales |
| Compliance | Paper trail | DB audit log (note: no viewer UI yet) |

These are **Implemented capabilities**, not measured outcomes.

## 6. Target Users & Roles

| Role | Capabilities | Access |
|------|-------------|--------|
| **Viewer** | Read dashboards, reports, data | Read-only (self-registration creates viewer) |
| **Manager** | Create/edit products, suppliers, movements, POs | Write |
| **Admin** | Full access + settings + thresholds | Full (user promotion: direct DB) |

Personas: supply chain analyst (forecast/anomaly optimization),
warehouse manager (daily stock/reorder), procurement lead (supplier/PO),
admin (settings/monitoring).

## 7. Competitive Analysis (E3 — general knowledge, labeled)

| Solution | Category | vs InventoryLogix |
|----------|------|------------------|
| **SAP IBP / Oracle SCM** | Enterprise planning ($$$$) | Same concept categories (forecast/optimize/warehouse) at enterprise cost and complexity |
| **TradeGecko / QuickBooks Commerce** | SMB SaaS | Mature order management; no open EOQ sensitivity or native ML forecasting |
| **inFlow Inventory** | SMB desktop/web | Reorder-point recommendations; no statistical forecasting |
| **Odoo Inventory / ERPNext** | Open-source ERP | Far broader scope; ML/forecasting limited or module-based; no exposed SCD2 star |
| **InvenTree / PartKeepr / Snipe-IT** | OSS inventory/assets | Operational tracking focus; no forecasting/EOQ/warehouse |

**Unique selling points (grounded in code):**
1. Integrated ML (Prophet/ARIMA ensemble) + Isolation Forest + SPC
2. Interactive EOQ with 3D sensitivity surface
3. SCD Type 2 data warehouse in the same PostgreSQL
4. Real dataset grounding (DataCo 180K+)
5. Open stack, self-hostable, zero license cost
6. Security-first (CSP nonces, RBAC, parameterized SQL, audit logging)

Honest positioning: for a real business needing barcode scanning, order
management, channel sync, and support, buy a commercial product. This
project's differentiation is the **combination** in one transparent,
self-hostable codebase — and, as a mini-project, a demonstration of how
such systems are built end-to-end.

## 8. Use Cases

- **Manufacturing:** raw-material inventory optimization — forecasting
  for production planning, EOQ for bulk ordering.
- **Retail:** multi-store replenishment — warehouse-level demand
  analysis, reorder alerts.
- **Distribution:** stock balancing — cross-warehouse visibility,
  movement tracking.
- **E-commerce:** fulfillment-center inventory — seasonal forecasting,
  anomaly detection for shrinkage.

## 9. Implementation Guide

### Deployment options
1. **Render (recommended)** — push to GitHub → Blueprint creates free
   Postgres + web service; first boot auto-applies schema, seeds demo
   data, runs ETL. ~10-minute setup.
2. **Local** — venv → `pip install -r requirements.txt` → copy .env →
   `python run.py` → http://localhost:5000.
3. **Self-hosted** — any PostgreSQL; Gunicorn for production.

### Data migration (for real use)
1. Export from existing system → 2. map to InventoryLogix schema →
3. import via REST API or direct inserts → 4. run ETL.

### Onboarding
Admin configures settings and creates manager accounts → managers import
products/suppliers and create POs → viewers consume dashboards.

## 10. Cost Profile

Reference deployment: Render free tier (web + Postgres) + optional free
SendGrid. Zero license cost. **No pricing tiers exist for InventoryLogix
itself** — it is an MCA mini-project, free for evaluation; any pricing
model would be new business development.

## 11. Success Metrics & Monitoring

**Honest KPI framing:** targets can be *defined* (stockout rate, carrying
cost, forecast accuracy vs actuals, anomaly precision, EOQ savings via
before/after pilot) but none are currently *measured* by the tool. The
`/monitoring` page measures what exists today: DB stats, ETL state,
daily logins, warehouse health. The "AI savings YTD" dashboard card is
a policy counterfactual, not a KPI (see §4).

## 12. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **Data breach** | Low | High | CSP, RBAC, parameterized SQL, audit logging — but rotate the committed DB credential first |
| **System downtime** | Medium | Medium | Render auto-restart, health checks |
| **ML model drift** | Medium | Low | Confidence intervals; retraining ritual (unscheduled — needs a scheduler) |
| **User adoption** | Medium | Medium | Intuitive UI; train users which dashboard numbers are live vs illustrative |
| **Scalability ceiling** | Low (internal scale) | High | Single-process by design; Redis upgrade path documented |
| **Misleading demo metrics** | Medium | Medium | §4 classification; label synthetic numbers in any client-facing use |

## 13. Growth Roadmap (cheapest-value first, evidence-based)

1. **PO receipt reconciliation** — auto IN movement + clear `on_order`
   inside `sp_po_update_status`; closes the workflow leak.
2. **Reorder email alerts** — Mailer already exists; consume the same
   low-stock query the alerts page uses; makes the decorative
   email_alerts toggle real.
3. **Scheduled ETL/forecast refresh** — watermark state already tracked
   (`etl_warehouse_state`).
4. **Forecast-driven reorder points** — forecast_cache + supplier lead
   days + existing ROP formula just need wiring; closes the
   forecast↔EOQ disconnect.
5. **Admin user-management UI** — stored procedures already written.
6. **Pilot measurement program** — baseline capture to convert
   Potential benefits into Measured ones.

---

*Generated: September 10, 2026 · Merged from both analysis passes*
