# Mitigation Plan: Data Consistency & Integrity Issues
## InventoryLogix Application

## Overview
This plan outlines mitigation strategies for the data consistency and integrity issues identified in the audit. All solutions adhere to the **no-ORM constraint** - using only raw SQL, stored procedures, and explicit transaction management as per project architecture.

## P1: Critical Issues (Immediate Action)

### DC-001: Atomic Movement Recording
**Problem**: Movement recording, stock update, and audit log are separate operations without transaction boundary, risking inventory/audit mismatch.

**Mitigation Plan**:
1. **Create Composite Stored Procedure**:
   ```sql
   CREATE OR REPLACE PROCEDURE sp_record_movement_complete(
       p_product_id INTEGER, p_movement_type VARCHAR(10), p_quantity INTEGER,
       p_reference VARCHAR(100), p_user_id INTEGER
   )
   LANGUAGE plpgsql
   AS $$
   DECLARE
       v_current_stock INTEGER;
   BEGIN
       -- All operations in single transaction
       -- 1. Record movement
       PERFORM sp_movement_record(p_product_id, p_movement_type, p_quantity, p_reference, p_user_id);
       
       -- 2. Calculate and update stock
       SELECT current_stock INTO v_current_stock FROM products WHERE product_id = p_product_id;
       IF p_movement_type IN ('IN', 'RETURN') THEN
           v_current_stock := v_current_stock + p_quantity;
       ELSE
           v_current_stock := v_current_stock - p_quantity;
       END IF;
       
       PERFORM sp_product_set_stock(p_product_id, v_current_stock);
       
       -- 3. Record audit
       PERFORM sp_audit_record(
           'movement', 
           p_product_id, 
           p_movement_type, 
           jsonb_build_object(
               'quantity', p_quantity, 
               'reference', p_reference,
               'previous_stock', v_current_stock - 
                   CASE WHEN p_movement_type IN ('IN', 'RETURN') THEN p_quantity ELSE -p_quantity END
           ),
           p_user_id
       );
   END;
   $$;
   ```
2. **Update Service Layer**:
   - Replace separate repository calls in `MovementService.record()` with single call to `sp_record_movement_complete`
   - Maintain existing validation and authorization layers
   - Keep cache invalidation (`cache_bust_movements()`) after procedure call

**Verification**: 
- TC-DC001: Simulate failure during audit - verify no movement recorded and stock unchanged

### DC-002: Safe ETL High-Water Mark
**Problem**: High-water mark updated before fact table load completion, risking permanent data loss on ETL failure.

**Mitigation Plan**:
1. **Modify ETL Pipeline** (`app/database/etl.py`):
   ```python
   def etl_incremental():
       conn = get_connection()
       try:
           with conn.cursor() as cur:
               cur.execute("BEGIN")
               
               # Get current high-water mark
               cur.execute("SELECT last_movement_id FROM etl_state WHERE key = 'movements'")
               last_id = cur.fetchone()[0] or 0
               
               # Process new movements into fact table
               cur.execute("""
                   INSERT INTO fact_movement_daily (warehouse_id, product_id, movement_date, in_qty, out_qty)
                   SELECT p.warehouse_id, p.product_id, m.created_at::date,
                          SUM(CASE WHEN m.type = 'IN' THEN m.quantity ELSE 0 END),
                          SUM(CASE WHEN m.type = 'OUT' THEN m.quantity ELSE 0 END)
                   FROM movements m
                   JOIN products p ON m.product_id = p.product_id
                   WHERE m.movement_id > %s
                   GROUP BY p.warehouse_id, p.product_id, m.created_at::date
                   ON CONFLICT (warehouse_id, product_id, movement_date) 
                   DO UPDATE SET 
                       in_qty = EXCLUDED.in_qty,
                       out_qty = EXCLUDED.out_qty
               """, (last_id,))
               
               # Update dimensions (existing logic)
               # ... dimension update procedures ...
               
               # ONLY NOW update high-water mark - AFTER fact load success
               cur.execute("""
                   UPDATE etl_state 
                   SET last_movement_id = (SELECT COALESCE(MAX(movement_id), 0) FROM movements),
                       last_updated = NOW()
                   WHERE key = 'movements'
               """)
               
               conn.commit()
       except Exception as e:
           conn.rollback()
           # High-water mark NOT updated - safe for retry
           raise e
       finally:
           conn.close()
   ```
2. **Add Idempotency**: 
   - Use `ON CONFLICT DO UPDATE` for fact table inserts to allow safe retries
   - Ensure dimension updates are also idempotent (use UPSERT patterns)

**Verification**:
- TC-DC002: Kill ETL after fact load but before high-water mark update - verify high-water mark unchanged and data reprocessed on retry

### DC-003: SQL Injection in Reports
**Problem**: Reports route uses f-string interpolation for `product_where` clauses, enabling SQL injection.

**Mitigation Plan**:
1. **Implement Column Whitelisting** (`app/routes/ui.py`):
   ```python
   # Define allowed columns for reporting
   REPORT_COLUMN_MAP = {
       'category': 'p.category',
       'warehouse': 'w.warehouse_code',
       'status': 'p.stock_status',
       'supplier': 's.supplier_name',
       'sku': 'p.sku',
       'product_name': 'p.product_name'
   }
   
   def build_safe_report_where(filters):
       conditions = []
       params = []
       for column, value in filters.items():
           if column in REPORT_COLUMN_MAP:
               conditions.append(f"{REPORT_COLUMN_MAP[column]} = %s")
               params.append(value)
           else:
               raise ValueError(f"Invalid report column: {column}")
       return " AND ".join(conditions) if conditions else "1=1", params
   
   # In reports() function:
   where_clause, params = build_safe_report_where(request.args)
   cur.execute(f"""
       SELECT ... 
       FROM fact_movement_daily f
       JOIN dim_product p ON f.product_id = p.product_id
       JOIN dim_warehouse w ON f.warehouse_id = w.warehouse_id
       JOIN dim_supplier s ON p.supplier_id = s.supplier_id
       WHERE {where_clause}
       AND f.movement_date BETWEEN %s AND %s
   """, params + [start_date, end_date])
   ```
2. **Alternative: Stored Procedure Approach** (Preferred for complex reporting):
   ```sql
   -- Create reporting stored procedure
   CREATE OR REPLACE FUNCTION sp_get_inventory_report(
       p_categories VARCHAR[], p_warehouses VARCHAR[],
       p_date_from DATE, p_date_to DATE
   )
   RETURNS TABLE (
       product_id INTEGER, sku VARCHAR, product_name VARCHAR,
       category VARCHAR, warehouse_code VARCHAR, 
       total_in INTEGER, total_out INTEGER, net_change INTEGER
   )
   LANGUAGE plpgsql
   AS $$
   BEGIN
       RETURN QUERY
       SELECT 
           p.product_id, p.sku, p.product_name,
           p.category, w.warehouse_code,
           SUM(f.in_qty) AS total_in,
           SUM(f.out_qty) AS total_out,
           SUM(f.in_qty - f.out_qty) AS net_change
       FROM fact_movement_daily f
       JOIN dim_product p ON f.product_id = p.product_id
       JOIN dim_warehouse w ON f.warehouse_id = w.warehouse_id
       WHERE (p_categories IS NULL OR p.category = ANY(p_categories))
         AND (p_warehouses IS NULL OR w.warehouse_code = ANY(p_warehouses))
         AND f.movement_date BETWEEN p_date_from AND p_date_to
       GROUP BY p.product_id, p.sku, p.product_name, p.category, w.warehouse_code
       ORDER BY net_change DESC;
   END;
   $$;
   ```
   ```python
   # In reports() function:
   cur.execute("""
       SELECT * FROM sp_get_inventory_report(%s, %s, %s, %s)
   """, (category_list, warehouse_list, start_date, end_date))
   ```

**Verification**:
- TC-DC003: Attempt SQL injection via report filter - verify request rejected with validation error

## P2: Medium Issues

### DC-004: Cache Invalidation Strategy
**Problem**: Cache invalidation relies solely on application hooks, missing direct SQL/ETL/writes.

**Mitigation Plan**:
1. **Implement PostgreSQL LISTEN/NOTIFY System**:
   - **Database Side** (`app/database/triggers.sql` additions):
     ```sql
     CREATE OR REPLACE FUNCTION trg_notify_cache_invalidation()
     RETURNS TRIGGER
     LANGUAGE plpgsql
     AS $$
     BEGIN
         PERFORM pg_notify('cache_invalid', json_build_object(
             'table', TG_TABLE_NAME,
             'operation', TG_OP,
             'schema', TG_TABLE_SCHEMA
         )::text);
         RETURN NEW;
     END;
     $$;
     
     -- Attach to all relevant tables
     DO $$
     DECLARE
         tables CURSOR FOR 
             SELECT table_name 
             FROM information_schema.tables 
             WHERE table_schema = 'public' 
                 AND table_name IN ('products', 'movements', 'suppliers', 
                                   'purchase_orders', 'users', 'settings');
     BEGIN
         FOR t IN tables LOOP
             EXECUTE format('
                 DROP TRIGGER IF EXISTS trg_notify_cache_%I ON %I;
                 CREATE TRIGGER trg_notify_cache_%I
                 AFTER INSERT OR UPDATE OR DELETE ON %I
                 FOR EACH STATEMENT EXECUTE FUNCTION trg_notify_cache_invalidation();
             ', t.table_name, t.table_name, t.table_name, t.table_name);
         END LOOP;
     END $$;
     ```
   - **Application Side** (`app/utils/cache.py` additions):
     ```python
     import threading
     import time
     import json
     
     class CacheListener(threading.Thread):
         def __init__(self, cache_manager):
             super().__init__(daemon=True)
             self.cache_manager = cache_manager
             self.conn = None
             
         def run(self):
             try:
                 self.conn = get_connection()
                 self.conn.set_isolation_level(
                     psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT
                 )
                 cur = self.conn.cursor()
                 cur.execute("LISTEN cache_invalid")
                 
                 while True:
                     self.conn.poll()
                     while self.conn.notifies:
                         notify = self.conn.notifies.pop(0)
                         payload = json.loads(notify.payload)
                         table_name = payload['table']
                         
                         # Invalidate relevant caches
                         if table_name == 'products':
                             cache_bust_products()
                         elif table_name == 'movements':
                             cache_bust_movements()
                         elif table_name == 'suppliers':
                             cache_bust_suppliers()
                         # ... other tables ...
             except Exception as e:
                 # Log error but don't crash listener
                 current_app.logger.error(f"Cache listener error: {e}")
             finally:
                 if self.conn:
                     self.conn.close()
     ```
   - **Initialize Listener** (`app/__init__.py` in `create_app()`):
     ```python
     # After cache initialization
     from app.utils.cache import CacheListener
     cache_listener = CacheListener(cache)
     cache_listener.start()
     ```

**Verification**:
- TC-DC004: Execute direct SQL UPDATE on movements - verify cache invalidated and dashboard updates within seconds

### DC-005: Atomic Login Recording
**Problem**: Login recording happens after credential validation, risking premature lockout on DB failure.

**Mitigation Plan**:
1. **Reorder Operations** (`app/services/auth_service.py`):
   ```python
   def authenticate(username, password):
       # 1. Record login attempt FIRST (before validation)
       login_token = secrets.token_urlsafe(32)
       login_recorded = False
       
       try:
           # Record attempt in login_attempts table
           conn = get_connection()
           with conn.cursor() as cur:
               cur.execute("""
                   INSERT INTO login_attempts 
                   (username, ip_address, user_agent, login_token, created_at, success)
                   VALUES (%s, %s, %s, %s, NOW(), FALSE)
                   RETURNING id
               """, (username, request.remote_addr, request.user_agent.string, login_token))
               login_attempt_id = cur.fetchone()[0]
               conn.commit()
               login_recorded = True
           conn.close()
       except Exception as e:
           current_app.logger.error(f"Failed to record login attempt: {e}")
           # Continue with validation - fail open for availability
       
       # 2. Validate credentials
       user = UserRepository.find_by_username(username)
       if not user or not check_password_hash(user.password_hash, password):
           # Update attempt as failed
           if login_recorded:
               try:
                   conn = get_connection()
                   with conn.cursor() as cur:
                       cur.execute("""
                           UPDATE login_attempts 
                           SET success = FALSE, failure_reason = 'invalid_credentials'
                           WHERE id = %s
                       """, (login_attempt_id,))
                       conn.commit()
                   conn.close()
               except:
                   pass  # Best effort
           
           # Increment failed login counter (with lockout logic)
           increment_failed_login(username)
           return None
       
       # 3. Update attempt as successful
       if login_recorded:
           try:
               conn = get_connection()
               with conn.cursor() as cur:
                   cur.execute("""
                       UPDATE login_attempts 
                       SET success = TRUE, failure_reason = NULL
                       WHERE id = %s
                   """, (login_attempt_id,))
                   conn.commit()
               conn.close()
           except:
               pass  # Best effort
       
       # 4. Reset failed login counter on success
       reset_failed_login(username)
       
       # 5. Create session
       return UserProxy(user)
   ```
2. **Add Login Attempts Table** (if not exists):
   ```sql
   CREATE TABLE IF NOT EXISTS login_attempts (
       id SERIAL PRIMARY KEY,
       username VARCHAR(64) NOT NULL,
       ip_address INET,
       user_agent TEXT,
       login_token VARCHAR(64) UNIQUE,
       created_at TIMESTAMP NOT NULL,
       success BOOLEAN,
       failure_reason TEXT
   );
   
   CREATE INDEX idx_login_attempts_username ON login_attempts(username);
   CREATE INDEX idx_login_attempts_created_at ON login_attempts(created_at);
   ```

**Verification**:
- TC-DC005: Simulate DB failure during login recording after successful auth - verify second login with same credentials succeeds (counter reset)

### DC-006: Connection Pool Health Checks
**Problem**: Connection pool lacks validation, risking stale connection errors under load.

**Mitigation Plan**:
1. **Enhance Connection Pool** (`app/database/connection.py`):
   ```python
   def get_connection():
       global _POOL
       with _POOL_LOCK:
           if _POOL is None:
               _POOL = ThreadedConnectionPool(
                   minconn=1,
                   maxconn=20,
                   host=current_app.config['DB_HOST'],
                   port=current_app.config['DB_PORT'],
                   database=current_app.config['DB_NAME'],
                   user=current_app.config['DB_USER'],
                   password=current_app.config['DB_PASSWORD'],
                   # Critical: Add connection validation
                   # Validates connection before returning from pool
                   # Uses lightweight query to check liveness
               )
       
       conn = _POOL.getconn()
       
       # Additional validation: Ensure connection is usable
       try:
           with conn.cursor() as cur:
               cur.execute("SELECT 1")
               cur.fetchone()  # Will raise exception if connection dead
       except (psycopg2.InterfaceError, psycopg2.OperationalError):
           # Connection is bad - discard and get new one
           _POOL.putconn(conn, close=True)  # Destroy bad connection
           conn = _POOL.getconn()  # Get fresh connection
           # Validate again
           with conn.cursor() as cur:
               cur.execute("SELECT 1")
               cur.fetchone()
       
       return conn
   ```
2. **Add Connection Reset on Checkout** (Alternative approach):
   ```python
   def get_connection():
       # ... pool acquisition ...
       conn = _POOL.getconn()
       
       # Reset connection state to avoid leaking transaction state
       conn.autocommit = True
       with conn.cursor() as cur:
           cur.execute("ROLLBACK")  # Clear any failed transaction
           cur.execute("SELECT 1")
       conn.autocompt = False  # Restore default
       
       return conn
   ```

**Verification**:
- TC-DC006: Simulate stale connection in pool - verify system recovers without "server closed connection" error

## P3: Low Issues

### DC-007: Decimal Precision in EOQ
**Problem**: Floating-point precision in money calculations risks rounding errors.

**Mitigation Plan**:
1. **Use Decimal for Financial Calculations** (`app/services/eoq_service.py`):
   ```python
   from decimal import Decimal, getcontext
   
   # Set precision for financial calculations (28 digits is default, sufficient for currency)
   getcontext().prec = 28
   
   def calculate_eoq(demand, ordering_cost, holding_cost):
       # Convert inputs to Decimal for precision
       d = Decimal(str(demand))
       oc = Decimal(str(ordering_cost))
       hc = Decimal(str(holding_cost))
       
       if hc <= 0 or d <= 0:
           return None
       
       # EOQ = sqrt(2*D*OC/HC)
       inside_sqrt = Decimal('2') * d * oc / hc
       eoq = inside_sqrt.sqrt()
       
       # Return as float for API compatibility (or keep as Decimal if API supports)
       return float(eoq)
   
   def calculate_total_cost(eoq, demand, ordering_cost, holding_cost):
       d = Decimal(str(demand))
       oc = Decimal(str(ordering_cost))
       hc = Decimal(str(holding_cost))
       q = Decimal(str(eoq))
       
       # TC = (D/Q)*OC + (Q/2)*HC
       ordering_cost_component = (d / q) * oc
       holding_cost_component = (q / Decimal('2')) * hc
       total_cost = ordering_cost_component + holding_cost_component
       
       return float(total_cost)
   ```
2. **Update Database Storage** (if storing EOQ results):
   - Change relevant columns to `NUMERIC(15, 4)` for precision
   - Example: `ALTER TABLE eoq_results ALTER COLUMN eoq_value TYPE NUMERIC(15, 4);`

**Verification**:
- TC-DC007: Calculate EOQ for extreme values - verify result matches manual decimal calculation

### DC-008: Trigger Recursion Prevention
**Problem**: Risk of infinite trigger loops between tables.

**Mitigation Plan**:
1. **Add Session-Based Recursion Flag** (`app/database/triggers.sql`):
   ```sql
   CREATE OR REPLACE FUNCTION trg_safe_audit_record()
   RETURNS TRIGGER
   LANGUAGE plpgsql
   AS $$
   DECLARE
       v_recursion_check BOOLEAN;
   BEGIN
       -- Check if we're already in an audit-triggered operation
       SELECT current_setting('app.audit_recursion_safe', true) 
       INTO v_recursion_check;
       
       IF v_recursion_check THEN
           -- Already in audit context - skip to prevent recursion
           RETURN NEW;
       END IF;
       
       -- Set recursion flag for nested triggers
       PERFORM set_config('app.audit_recursion_safe', 'true', true);
       
       BEGIN
           -- Actual audit logging logic
           INSERT INTO audit_log (
               user_id, action, target_type, target_id, 
               detail, ip_address, created_at
           ) VALUES (
               NEW.user_id, 
               TG_OP,
               TG_TABLE_NAME::varchar,
               NEW.id,
               to_jsonb(NEW) - 'password_hash',  -- Remove sensitive fields
               inet_client_addr(),
               NOW()
           );
       EXCEPTION
           WHEN OTHERS THEN
               -- Log error but don't fail the original operation
               RAISE NOTICE 'Audit logging failed: %', SQLERRM;
       FINALLY
           -- Always reset recursion flag
           PERFORM set_config('app.audit_recursion_safe', 'false', true);
       END;
       
       RETURN NEW;
   END;
   $$;
   
   -- Replace existing audit triggers with safe version
   DROP TRIGGER IF EXISTS trg_product_audit ON products;
   CREATE TRIGGER trg_product_audit
   AFTER INSERT OR UPDATE OR DELETE ON products
   FOR EACH ROW EXECUTE FUNCTION trg_safe_audit_record();
   
   -- Repeat for other tables (movements, suppliers, etc.)
   ```
2. **Initialize Custom Variable** (`app/database/connection.py` in `get_connection()`):
   ```python
   def get_connection():
       # ... existing pool logic ...
       conn = _POOL.getconn()
       
       # Initialize custom session variables
       with conn.cursor() as cur:
           cur.execute("SET app.audit_recursion_safe = 'false'")
       
       return conn
   ```

**Verification**:
- TC-DC008: Create circular trigger (audit_log → movements) - verify system prevents stack overflow and logs error instead

### DC-009: Movement Type CHECK Constraint
**Problem**: Missing DB-level constraint on movement types allows invalid values via direct SQL.

**Mitigation Plan**:
1. **Add CHECK Constraint** (`app/database/schema.sql`):
   ```sql
   ALTER TABLE movements 
   ADD CONSTRAINT chk_movement_type 
   CHECK (type IN ('IN', 'OUT', 'ADJUSTMENT', 'RETURN'));
   ```
2. **Update Existing Data** (if needed):
   ```sql
   -- First, check for invalid data
   SELECT * FROM movements WHERE type NOT IN ('IN', 'OUT', 'ADJUSTMENT', 'RETURN');
   
   -- If exists, decide: fix data or make constraint NOT VALID initially
   -- For new systems, assume clean data
   ```

**Verification**:
- TC-DC009: Attempt to insert movement with invalid type - verify constraint violation error

### DC-010: Notification Deduplication
**Problem**: Non-idempotent notification generation risks alert spam on retries.

**Mitigation Plan**:
1. **Implement Idempotency Key System** (`app/services/notification_service.py`):
   ```python
   import hashlib
   
   def generate_notification_idempotency_key(event_type, event_id, timestamp=None):
       """Generate unique key for notification deduplication"""
       if timestamp is None:
           timestamp = datetime.now()
       
       # Round to minute to prevent microsecond variations from causing duplicates
       rounded_timestamp = timestamp.replace(second=0, microsecond=0)
       key_string = f"{event_type}:{event_id}:{rounded_timestamp.isoformat()}"
       return hashlib.sha256(key_string.encode()).hexdigest()
   
   def send_notification_safely(event_type, event_id, payload=None):
       idempotency_key = generate_notification_idempotency_key(event_type, event_id)
       
       conn = get_connection()
       try:
           with conn.cursor() as cur:
               # Try to insert idempotency key - if exists, notification already sent
               cur.execute("""
                   INSERT INTO processed_notifications (idempotency_key, event_type, event_id, created_at)
                   VALUES (%s, %s, %s, NOW())
                   ON CONFLICT (idempotency_key) DO NOTHING
                   RETURNING idempotency_key
               """, (idempotency_key, event_type, event_id))
               
               if cur.fetchone():  # Key was inserted (first time)
                   # Actually send notification
                   _send_notification_impl(event_type, event_id, payload)
                   return True
               else:  # Key already existed (duplicate)
                   current_app.logger.info(f"Skipping duplicate notification: {idempotency_key}")
                   return False
       finally:
           conn.close()
   
   def _send_notification_impl(event_type, event_id, payload):
       # Original notification sending logic
       # ... existing implementation ...
   
   # Update all notification callers:
   # OLD: notification_service.notify_movement(movement_id)
   # NEW: notification_service.send_notification_safely('movement', movement_id)
   ```
2. **Add Processed Notifications Table**:
   ```sql
   CREATE TABLE IF NOT EXISTS processed_notifications (
       idempotency_key VARCHAR(64) PRIMARY KEY,
       event_type VARCHAR(32) NOT NULL,
       event_id VARCHAR(64) NOT NULL,
       created_at TIMESTAMP NOT NULL DEFAULT NOW()
   );
   
   CREATE INDEX idx_processed_notifications_event ON processed_notifications(event_type, event_id);
   
   -- Cleanup old entries (daily cron job)
   -- DELETE FROM processed_notifications WHERE created_at < NOW() - INTERVAL '30 days';
   ```

**Verification**:
- TC-DC010: Simulate duplicate notification sending - verify only one notification sent and recorded

## Implementation Priority & Dependencies

### Phase 1: Critical Fixes (Week 1)
1. DC-001: Atomic movement recording (blocks DC-010 verification)
2. DC-002: Safe ETL high-water mark 
3. DC-003: SQL injection in reports

### Phase 2: Medium Fixes (Week 2)
1. DC-004: Cache invalidation strategy (enables reliable caching)
2. DC-005: Atomic login recording
3. DC-006: Connection pool health checks

### Phase 3: Low Fixes (Week 3)
1. DC-007: Decimal precision in EOQ
2. DC-008: Trigger recursion prevention
3. DC-009: Movement type CHECK constraint
4. DC-010: Notification deduplication (depends on DC-001 for movement events)

## Risk Mitigation Notes
- **Backward Compatibility**: All changes are backward compatible; existing API contracts unchanged
- **Rollback Plan**: Each change can be rolled back by reverting to previous code (no destructive DB changes in P1)
- **Testing**: All fixes include verification test cases from audit (TC-DC001 through TC-DC010)
- **Performance**: 
  - Transactional changes add minimal overhead (single DB roundtrip vs multiple)
  - Cache invalidation uses lightweight LISTEN/NOTIFY
  - Idempotency checks add single SELECT/INSERT per notification
- **Security**: 
  - SQL injection fix eliminates critical vulnerability
  - Stored procedures maintain existing SQL injection defense
  - No new attack surfaces introduced

## Success Criteria
After implementation:
1. Zero tolerance for inventory/audit mismatches (DC-001 resolved)
2. ETL pipeline survives intermediate failures without data loss (DC-002 resolved)
3. Reporting immune to SQL injection attacks (DC-003 resolved)
4. Cache stays consistent with database state (DC-004 resolved)
5. Login system resilient to DB failures during authentication (DC-005 resolved)
6. Connection pool recovers gracefully from stale connections (DC-006 resolved)
7. Financial calculations maintain precision (DC-007 resolved)
8. Trigger system immune to recursion (DC-008 resolved)
9. Movement types strictly validated at DB level (DC-009 resolved)
10. Notification system eliminates duplicate alerts (DC-010 resolved)

This plan provides a comprehensive, prioritized approach to resolving all data consistency and integrity issues while respecting the project's no-ORM architectural constraint.