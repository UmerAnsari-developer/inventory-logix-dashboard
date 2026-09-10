# InventoryLogix — Interview Questions & Answers

## Technical Interview Questions

### Q1: Explain the architecture of InventoryLogix.

**Answer:** InventoryLogix follows a layered architecture:
1. **Presentation Layer**: Jinja2 templates with Chart.js, Three.js, and GSAP
2. **Route Layer**: Flask blueprints (auth, ui, api, ai)
3. **Service Layer**: Business logic orchestration
4. **Repository Layer**: Data access via stored procedures
5. **Data Layer**: PostgreSQL with 84+ stored procedures and 8 triggers

All SQL queries go through parameterized stored procedures to prevent SQL injection. The application uses Flask-Login for session management and Flask-WTF for CSRF protection.

---

### Q2: How does the ML forecasting work?

**Answer:** The forecasting module (`app/ml/forecasting.py`) implements three models:
1. **Prophet**: Facebook's time series model with weekly seasonality
2. **ARIMA**: AutoRegressive Integrated Moving Average (1,1,1)
3. **Ensemble**: Averages Prophet and ARIMA predictions

When the optional libraries (prophet, statsmodels) are unavailable, the system gracefully falls back to a moving-average forecast. The ensemble model provides more robust predictions by combining both approaches.

Portfolio-level forecasts are cached for 1 hour to avoid repeated model fitting.

---

### Q3: How do you prevent SQL injection?

**Answer:** All database queries go through 84+ stored procedures (`app/database/procedures.sql`). The application uses:
1. **Parameterized queries**: psycopg2 `%s` placeholders
2. **Stored procedures**: Business logic encapsulated in PL/pgSQL
3. **Input validation**: Validators for SKU, email, password strength
4. **No raw SQL**: Repository layer always calls `sp_*` functions

Example:
```python
cur.execute(
    "SELECT * FROM sp_product_list(%s, %s, %s, %s, %s, %s)",
    (search, category, warehouse, status, limit, offset),
)
```

---

### Q4: Explain the EOQ formula and its implementation.

**Answer:** Economic Order Quantity (EOQ) minimizes total inventory costs:
- **Formula**: `EOQ = √(2DS/H)`
  - D = Annual demand
  - S = Ordering cost per order
  - H = Holding cost per unit per year

**Implementation** (`app/utils/helpers.py`):
```python
def calculate_eoq(demand, ordering_cost, holding_cost):
    if not demand or not ordering_cost or not holding_cost:
        return None
    if demand <= 0 or ordering_cost < 0 or holding_cost <= 0:
        return None
    return math.sqrt((2 * demand * ordering_cost) / holding_cost)
```

The EOQ calculator provides:
- Interactive cost curve visualization
- Per-product EOQ table
- 3D sensitivity surface (Three.js)

---

### Q5: How does the anomaly detection work?

**Answer:** The anomaly module (`app/ml/anomaly.py`) implements two approaches:
1. **Isolation Forest**: sklearn's unsupervised algorithm for anomaly detection
   - Contamination parameter (5% default)
   - Decision function scores for confidence
   - Falls back to z-score when sklearn unavailable

2. **SPC Z-score Analysis**: Statistical Process Control
   - Calculates mean, sigma, UCL (Upper Control Limit), LCL (Lower Control Limit)
   - Flags points beyond ±3σ as anomalies
   - Provides control chart data for visualization

---

### Q6: Explain the data warehouse architecture.

**Answer:** The data warehouse uses a star schema with SCD Type 2 dimensions:
- **Dimensions**: `dim_product_scd`, `dim_supplier_scd`, `dim_warehouse_scd`, `dim_user`
- **Facts**: `fact_movement_daily`, `fact_inventory_daily`, `fact_product_daily`

**SCD Type 2** tracks full history:
```sql
CREATE TABLE dim_product_scd (
    product_key SERIAL PRIMARY KEY,
    sku VARCHAR(80),
    valid_from TIMESTAMP,
    valid_to TIMESTAMP,
    is_current BOOLEAN,
    row_hash VARCHAR(64)
);
```

The ETL pipeline (`app/database/etl.py`) is incremental:
1. Reads high-water mark from `etl_state`
2. Processes only new/modified movements
3. Updates dimensions with versioning
4. Rebuilds facts with stock walk clamping

---

### Q7: How do you handle rate limiting?

**Answer:** Flask-Limiter with in-memory storage:
```python
@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login(): ...

@api_bp.route("/products", methods=["POST"])
@limiter.limit("30 per minute")
def create_product(): ...

@api_bp.route("/movements", methods=["POST"])
@limiter.limit("60 per minute")
def create_movement(): ...
```

**Rate Limits:**
- Authentication: 10/min login, 5/min register
- API writes: 30/min
- Movements: 60/min

---

### Q8: Explain the CSP nonce implementation.

**Answer:** Per-request CSP nonces prevent inline script injection:
```python
@app.before_request
def _set_nonce():
    g.csp_nonce = secrets.token_urlsafe(24)

@app.context_processor
def _inject_nonce():
    return {"csp_nonce": getattr(g, "csp_nonce", "")}

@app.after_request
def _apply(response):
    nonce = getattr(g, "csp_nonce", "")
    response.headers["Content-Security-Policy"] = (
        f"script-src 'self' 'nonce-{nonce}' ..."
    )
```

Templates use `{{ csp_nonce }}`:
```html
<script nonce="{{ csp_nonce }}">
  // Inline scripts are allowed with valid nonce
</script>
```

---

### Q9: How does the account lockout work?

**Answer:** In-memory lockout tracker with threading lock:
```python
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

_failed_logins: dict[int, list[tuple[datetime, str]]] = defaultdict(list)
_lockout_mutex = threading.Lock()

def authenticate(username, password, ip):
    # Check lockout
    with _lockout_mutex:
        attempts = _failed_logins[uid]
        if len(attempts) >= MAX_FAILED_ATTEMPTS:
            raise AuthError(f"Account locked. Try again in {remaining} minutes.")
    
    # Verify password
    if not UserRepository.verify_password(password, user["password_hash"]):
        with _lockout_mutex:
            _failed_logins[uid].append((datetime.utcnow(), ip))
        raise AuthError("Invalid username or password.")
    
    # Clear on success
    with _lockout_mutex:
        _failed_logins.pop(uid, None)
```

**Limitation:** Lockout resets on app restart (in-memory only).

---

### Q10: Explain the testing strategy.

**Answer:** 97 tests across 8 test files:
- `test_api.py`: REST API endpoint tests
- `test_auth.py`: Authentication flow tests
- `test_cache.py`: Caching layer tests
- `test_etl.py`: ETL pipeline tests
- `test_ml.py`: ML model smoke tests (deterministic assertions)
- `test_roles.py`: RBAC tests
- `test_security.py`: Validator and header tests
- `test_services.py`: Business logic tests

**ML Tests:** Use synthetic data with known spikes to verify detection:
```python
def test_isoforest_deterministic_output():
    series, _ = _value_series(n=120, spike_at=60)
    result = detect_anomalies_isoforest(series)
    assert result["model"] == "isolation_forest"
    assert result["count"] == 1
    assert result["anomalies"][0]["value"] == 250.0
```

---

## Business Interview Questions

### Q11: What problem does InventoryLogix solve?

**Answer:** Supply chain managers struggle with:
1. **Lack of visibility**: No real-time view across multiple warehouses
2. **Reactive decisions**: No demand forecasting or anomaly detection
3. **Suboptimal ordering**: No EOQ optimization
4. **Compliance gaps**: No audit trails for inventory changes

InventoryLogix provides a unified dashboard combining real transaction data with ML capabilities, enabling proactive inventory management.

---

### Q12: Who are the target users?

**Answer:**
- **Primary**: Supply chain analysts who need to forecast demand and detect anomalies
- **Secondary**: Warehouse managers (daily stock review), procurement leads (supplier management), admins (settings)

**User Roles:**
- `viewer`: Read-only access to dashboards and reports
- `manager`: Write access to products, suppliers, movements
- `admin`: Full access including settings and user management

---

### Q13: What makes InventoryLogix different from existing solutions?

**Answer:** The differentiating mechanism is the **integrated EOQ + 3D sensitivity surfaces**:
- Real transaction data grounding (DataCo dataset, 180K+ rows)
- ML forecasting (Prophet/ARIMA ensemble)
- Anomaly detection (Isolation Forest + SPC)
- Interactive EOQ optimization with 3D visualization
- Open-stack Flask + PostgreSQL (no vendor lock-in)

Most competitors either lack ML capabilities or require enterprise-level investment.

---

### Q14: What are the limitations?

**Answer:**
1. **Single-tenant**: No multi-tenant or white-label support
2. **No Mobile App**: Web-only, no native mobile application
3. **No Real-time Updates**: Polling-based dashboard
4. **In-memory Lockout**: Account lockout resets on app restart
5. **Demo Data Only**: Seeded from DataCo dataset, no production integration
6. **No Internationalization**: English-only UI

---

### Q15: How would you scale this application?

**Answer:**
1. **Horizontal Scaling**: Increase Gunicorn workers, add load balancer
2. **Shared Caching**: Replace in-memory cache with Redis
3. **Database Scaling**: Add read replicas for analytics queries
4. **CDN**: Serve static assets via CDN
5. **WebSocket**: Real-time dashboard updates
6. **Microservices**: Split ML pipeline into separate service

---

## Viva Questions

### Q16: Why did you choose Flask over Django?

**Answer:** Flask's micro-framework approach suits this project because:
- No admin interface needed (custom UI preferred)
- Better control over database layer with raw SQL
- Lighter footprint for deployment
- More flexibility for ML integration

Django's ORM would add complexity for a stored-procedure-heavy architecture.

---

### Q17: How do you ensure data integrity?

**Answer:** Multiple layers:
1. **Stored Procedures**: All CRUD via `sp_*` functions
2. **Triggers**: `trg_validate_movement` prevents negative stock
3. **Constraints**: Foreign keys, CHECK constraints
4. **Audit Log**: Every mutation recorded
5. **SCD Type 2**: Full history tracking in data warehouse

---

### Q18: Explain the caching strategy.

**Answer:** Multi-layer caching:
- `global_cache`: 60s TTL (reorder count)
- `dashboard_cache`: Per-user, per-day
- `reports_cache`: 300s TTL
- `api_cache`: 60s TTL
- AI portfolio: 3600s TTL

Cache busting on mutations:
```python
def cache_bust_products():
    products_cache.clear()
    dashboard_cache.clear()
    global_cache.clear()
```

---

### Q19: How do you handle errors?

**Answer:** Comprehensive error handling:
1. **Custom Error Pages**: 400, 401, 403, 404, 422, 429, 500
2. **Graceful ML Fallback**: Moving-average when libraries unavailable
3. **Service Exceptions**: `AuthError`, `ProductError` for business logic
4. **API Envelope**: Consistent `{success, data, error}` format
5. **Audit Logging**: Errors logged for debugging

---

### Q20: What would you improve with more time?

**Answer:**
1. **Redis Caching**: Shared across instances
2. **WebSocket**: Real-time dashboard updates
3. **Two-Factor Auth**: Enhanced security
4. **Mobile PWA**: Offline-capable mobile experience
5. **Database Replicas**: Read scaling for analytics
6. **IP Blocking**: Brute-force protection
7. **Monitoring**: Prometheus metrics + Grafana dashboards
8. **CI/CD**: GitHub Actions for automated testing/deployment

---

*Generated: September 10, 2026*
