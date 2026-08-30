# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Flask + PostgreSQL (psycopg2) with Jinja2 templates, vanilla CSS/JS, Chart.js, Three.js (r158). ML: Prophet, ARIMA (statsmodels), Isolation Forest (scikit-learn). Auth: Flask-Login + Flask-WTF. Deploy: Render Blueprint (Gunicorn).

## Users

**Primary:** Supply chain analysts who need to forecast demand, detect anomalies, and optimize inventory levels across multiple warehouses.

**Secondary:** Warehouse/operations managers (daily stock/reorder workflow), procurement leads (supplier/PO management), admins (settings, user management). Viewer role is read-only; self-registration creates viewer accounts.

## Product Purpose

InventoryLogix unifies real transaction data (DataCo SMART SUPPLY CHAIN, 180K+ rows) with ML forecasting (Prophet/ARIMA ensemble), anomaly detection (Isolation Forest + SPC), and EOQ optimization into a single Flask + PostgreSQL dashboard. It turns raw stock movements into actionable replenishment decisions, reducing stockouts and carrying cost.

Success = fewer stockouts, lower carrying cost, forecast accuracy >90%, and measurable EOQ-driven savings visible in the dashboard.

## Positioning

The meaningfully different mechanism is the **integrated EOQ + 3D sensitivity surfaces** — a live Economic Order Quantity calculator that visualizes cost curves in 3D (ordering cost vs holding cost vs total cost) per product, paired with real transaction history and ML forecasts. No neighboring product combines real dataset grounding, ML demand forecasting, anomaly detection, and interactive EOQ optimization in one open-stack Flask application.

## Operating Context

- **Workflows:** Daily stock review → anomaly check → forecast review → EOQ recalc → PO creation → receipt logging → dashboard KPI refresh
- **Tools:** PostgreSQL (normalized schema), REST API (`/api/*`), AI endpoints (`/ai/forecast/run`, `/ai/anomaly/run`, `/ai/eoq/sensitivity`)
- **Environment:** Internal tool for ops teams; runs on Render (Gunicorn) or local dev (`python run.py`)
- **Data:** Seeded from DataCo CSV (180K+ real transactions) or deterministic synthetic fallback
- **Rituals:** Weekly forecast retrain, daily anomaly scan, monthly EOQ recalibration

## Capabilities and Constraints

**Confirmed functionality:**
- CRUD for products, suppliers, movements, purchase orders, warehouses
- Role-based access: admin/manager (write), viewer (read-only)
- Demand forecasting (Prophet/ARIMA/ensemble) with confidence intervals
- Anomaly detection (Isolation Forest + SPC z-score control charts)
- EOQ optimization with 3D sensitivity surface (Three.js)
- REST API with consistent JSON envelope
- Dark mode (user preference, stored in DB)
- Audit log for all mutating actions

**Technical constraints:**
- Stack locked to Flask + PostgreSQL + specific ML libraries
- ML libraries optional; graceful fallback to moving-average / z-score when unavailable
- Self-registration always creates viewer role; admin must promote
- Rate limits: auth 10/min, API write 30/min, movements 60/min
- CSP + security headers enforced; parameterized SQL only

**Explicitly undecided:**
- Multi-tenant / white-label support
- Advanced scheduling / automation of PO creation
- Mobile-native app

## Brand Commitments

**Name:** InventoryLogix (Inventory Command Center on landing page)
**Voice:** Technical, precise, ops-focused. No marketing fluff.
**Assets:** Logo (SVG, warehouse icon), favicon. No brand guideline doc.
**Identity constraints:** Dark-mode default for dashboard; landing page is dark-theme. Copper/sky accent palette. Space Grotesk (display), Inter (body), JetBrains Mono (data).

## Evidence on Hand

**Real content/data:**
- DataCo SMART SUPPLY CHAIN dataset (180K+ transactions, 118 products, 150 suppliers) — local CSV only, gitignored
- Deterministic synthetic catalog (fallback when CSV absent)
- Seeded demo users: admin/Admin@123, manager/Manager@123, viewer/Viewer@123

**Demonstrations:**
- Landing page (`/`) with live KPIs, 14-day movement chart, inventory mix
- Dashboard with AI savings KPI, forecast strip, anomaly alerts
- EOQ calculator with 3D surface (`/eoq-calculator`)
- AI forecast (`/ai/forecast`) + anomaly (`/ai/anomaly`) pages with Plotly charts

**Absences future work must not fabricate:**
- No customer testimonials, case studies, or press
- No benchmark claims beyond seeded dataset stats
- No pricing/licensing tiers (single product, free for evaluation)

## Product Principles

1. **Data-first, not demo-first** — every feature grounded in real transaction data or transparent synthetic fallback
2. **ML as augmentation, not magic** — forecasts show confidence intervals; anomalies show root-cause hints; graceful degradation when libraries missing
3. **Ops workflow over dashboard theater** — each screen maps to a daily task (reorder, receive, adjust, analyze)
4. **Security by default** — CSP, rate limits, audit log, parameterized SQL, RBAC are non-negotiable
5. **Open stack, no vendor lock-in** — Flask + PostgreSQL + standard ML libs; deployable anywhere Postgres runs

## Accessibility & Inclusion

- WCAG 2.1 AA target for dashboard (color contrast, focus management, semantic HTML, keyboard navigation)
- Reduced-motion respected (`prefers-reduced-motion`) for all animations
- Screen-reader labels on icon-only controls; tabular data has proper headers
- Focus-visible outlines on all interactive elements