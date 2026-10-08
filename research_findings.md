# Research Findings: Data Consistency & Integrity Mitigation Strategies

## 1. Transaction Patterns for Multi-Step DB Operations (Without ORM)
**Key Findings:**
- **Explicit Transaction Boundaries**: In PostgreSQL, transactions must be managed explicitly at the connection level when not using ORM. The pattern is:
  ```python
  conn = get_connection()
  try:
      with conn.cursor() as cur:
          cur.execute("BEGIN")
          # Step 1: Record movement
          cur.execute("CALL sp_movement_record(%s, %s, %s, %s, %s)", movement_params)
          # Step 2: Update stock
          cur.execute("CALL sp_product_set_stock(%s, %s)", stock_params)
          # Step 3: Record audit
          cur.execute("CALL sp_audit_record(%s, %s, %s, %s, %s)", audit_params)
          conn.commit()
  except Exception as e:
      conn.rollback()
      raise e
  finally:
      conn.close()
  ```
- **Stored Procedure Transactions**: Alternative approach - wrap all operations in a single stored procedure that handles its own transaction:
  ```sql
  CREATE OR REPLACE PROCEDURE sp_record_movement_with_audit(
      p_product_id INTEGER, p_movement_type VARCHAR(10), p_quantity INTEGER, 
      p_reference VARCHAR(100), p_user_id INTEGER
  )
  LANGUAGE plpgsql
  AS $$
  BEGIN
      -- All operations in single transaction
      PERFORM sp_movement_record(p_product_id, p_movement_type, p_quantity, p_reference, p_user_id);
      -- Calculate and update stock (logic moved to procedure)
      PERFORM sp_product_set_stock(p_product_id, 
          (SELECT current_stock FROM products WHERE product_id = p_product_id) + 
          CASE WHEN p_movement_type IN ('IN', 'RETURN') THEN p_quantity ELSE -p_quantity END);
      PERFORM sp_audit_record('movement', p_product_id, p_movement_type, 
          jsonb_build_object('quantity', p_quantity, 'reference', p_reference), p_user_id);
  END;
  $$;
  ```
- **Two-Phase Commit Alternative**: For distributed systems, but not needed here as single DB.
- **Source**: PostgreSQL documentation on transaction control, PL/pgSQL procedure best practices.

## 2. Safe ETL High-Water Mark Implementation
**Key Findings:**
- **Atomic High-Water Mark Update**: Update the high-water mark only after successful fact table load within same transaction:
  ```python
  def etl_incremental():
      conn = get_connection()
      try:
          with conn.cursor() as cur:
              cur.execute("BEGIN")
              
              # Get current high-water mark
              cur.execute("SELECT last_movement_id FROM etl_state WHERE key = 'movements'")
              last_id = cur.fetchone()[0] or 0
              
              # Process new movements
              cur.execute("""
                  INSERT INTO fact_movement_daily (warehouse_id, product_id, movement_date, in_qty, out_qty)
                  SELECT p.warehouse_id, p.product_id, m.created_at::date,
                         SUM(CASE WHEN m.type = 'IN' THEN m.quantity ELSE 0 END),
                         SUM(CASE WHEN m.type = 'OUT' THEN m.quantity ELSE 0 END)
                  FROM movements m
                  JOIN products p ON m.product_id = p.product_id
                  WHERE m.movement_id > %s
                  GROUP BY p.warehouse_id, p.product_id, m.created_at::date
              """, (last_id,))
              
              # Update dimensions (simplified)
              # ... dimension update logic ...
              
              # ONLY NOW update high-water mark - AFTER fact load success
              cur.execute("""
                  UPDATE etl_state 
                  SET last_movement_id = (SELECT MAX(movement_id) FROM movements),
                      last_updated = NOW()
                  WHERE key = 'movements'
              """)
              
              conn.commit()
      except Exception as e:
          conn.rollback()
          # High-water mark NOT updated on failure - safe for retry
          raise e
      finally:
          conn.close()
  ```
- **Idempotent ETL Design**: Make ETL safely retryable by:
  - Using movement_id range processing (not timestamp-based)
  - Ensuring fact table inserts are idempotent (e.g., ON CONFLICT DO UPDATE or delete-then-insert for date granularity)
  - Source: Martin Kleppmann's "Designing Data-Intensive Applications" ETL patterns, AWS DMS best practices.
- **Fallback Mechanism**: If fact table load fails, high-water mark remains unchanged, allowing safe retry.

## 3. SQL Injection Prevention for Dynamic Queries
**Key Findings:**
- **Strict Whitelist Validation**: For dynamic column names in reporting, validate against a predefined list:
  ```python
  ALLOWED_REPORT_COLUMNS = {
      'category': 'p.category',
      'warehouse': 'w.warehouse_code',
      'status': 'p.stock_status',
      'supplier': 's.supplier_name'
  }
  
  def build_report_filters(filters):
      conditions = []
      params = []
      for col, value in filters.items():
          if col in ALLOWED_REPORT_COLUMNS:
              conditions.append(f"{ALLOWED_REPORT_COLUMNS[col]} = %s")
              params.append(value)
          else:
              raise ValueError(f"Invalid column: {col}")
      return " AND ".join(conditions), params
  ```
- **Stored Procedure for Reporting**: Move complex reporting logic to a stored procedure that uses static SQL:
  ```sql
  CREATE OR REPLACE FUNCTION sp_get_report_data(
      p_category VARCHAR[], p_warehouse VARCHAR[], 
      p_date_from DATE, p_date_to DATE
  )
  RETURNS TABLE (product_id INTEGER, sku VARCHAR, total_qty INTEGER)
  LANGUAGE plpgsql
  AS $$
  BEGIN
      RETURN QUERY
      SELECT p.product_id, p.sku, SUM(f.in_qty - f.out_qty)
      FROM fact_movement_daily f
      JOIN dim_product p ON f.product_id = p.product_id
      JOIN dim_warehouse w ON f.warehouse_id = w.warehouse_id
      WHERE (p_category IS NULL OR p.category = ANY(p_category))
        AND (p_warehouse IS NULL OR w.warehouse_code = ANY(p_warehouse))
        AND f.movement_date BETWEEN p_date_from AND p_date_to
      GROUP BY p.product_id, p.sku;
  END;
  $$;
  ```
- **Parameterized LIKE/ILIKE**: For search terms, always use parameters:
  ```python
  # SAFE: Parameterized
  cur.execute("SELECT * FROM products WHERE sku ILIKE %s", (f"%{search_term}%",))
  
  # UNSAFE: String concatenation (avoid)
  # cur.execute(f"SELECT * FROM products WHERE sku ILIKE '%{search_term}%'")
  ```
- **Source**: OWASP SQL Injection Prevention Cheat Sheet, PostgreSQL documentation on safe dynamic SQL.

## 4. Cache Invalidation Strategies for Non-ORM Systems
**Key Findings:**
- **Database Triggers for Cache Invalidation**: Since ORM hooks aren't available, use DB triggers to notify application of changes:
  ```sql
  -- Create a cache invalidation queue table
  CREATE TABLE cache_invalidation_queue (
      id SERIAL PRIMARY KEY,
      table_name VARCHAR(50) NOT NULL,
      operation VARCHAR(10) NOT NULL, -- INSERT/UPDATE/DELETE
      record_id INTEGER,
      created_at TIMESTAMP DEFAULT NOW()
  );
  
  -- Trigger function
  CREATE OR REPLACE FUNCTION trg_cache_invalidation()
  RETURNS TRIGGER
  LANGUAGE plpgsql
  AS $$
  BEGIN
      IF TG_OP = 'INSERT' THEN
          INSERT INTO cache_invalidation_queue (table_name, operation, record_id)
          VALUES (TG_TABLE_NAME, 'INSERT', NEW.id);
      ELSIF TG_OP = 'UPDATE' THEN
          INSERT INTO cache_invalidation_queue (table_name, operation, record_id)
          VALUES (TG_TABLE_NAME, 'UPDATE', NEW.id);
      ELSIF TG_OP = 'DELETE' THEN
          INSERT INTO cache_invalidation_queue (table_name, operation, record_id)
          VALUES (TG_TABLE_NAME, 'DELETE', OLD.id);
      END IF;
      RETURN NEW;
  END;
  $$;
  
  -- Attach to relevant tables
  CREATE TRIGGER trg_invalidate_products_cache
  AFTER INSERT OR UPDATE OR DELETE ON products
  FOR EACH ROW EXECUTE FUNCTION trg_cache_invalidation();
  ```
- **Application-Side Polling/Dispatch**: 
  - Option 1: Application polls `cache_invalidation_queue` periodically (e.g., every 5s) and clears relevant caches
  - Option 2: Use PostgreSQL LISTEN/NOTIFY for real-time invalidation:
    ```sql
    -- In trigger function
    PERFORM pg_notify('cache_invalid', json_build_object(
        'table', TG_TABLE_NAME,
        'operation', TG_OP,
        'id', COALESCE(NEW.id, OLD.id)
    )::text);
    ```
    ```python
    # In application
    conn = get_connection()
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    cur.execute("LISTEN cache_invalid")
    
    while True:
        conn.poll()
        while conn.notifies:
            notify = conn.notifies.pop(0)
            payload = json.loads(notify.payload)
            # Invalidate cache based on payload
            cache_bust_table(payload['table'])
        time.sleep(0.1)
  ```
- **Source**: PostgreSQL LISTEN/NOTIFY documentation, Redis invalidation patterns adapted for TTLCache.

## 5. Idempotency Patterns for Notification Systems
**Key Findings:**
- **Idempotency Key Pattern**: 
  - Generate unique key from event characteristics: `idempotency_key = hash(event_type + event_id + timestamp_rounded_to_minute)`
  - Store processed keys in a table with TTL:
    ```sql
    CREATE TABLE processed_notifications (
        idempotency_key VARCHAR(64) PRIMARY KEY,
        processed_at TIMESTAMP DEFAULT NOW()
    );
    
    -- Cleanup old entries (run via cron)
    DELETE FROM processed_notifications WHERE processed_at < NOW() - INTERVAL '1 hour';
    ```
  - Usage:
    ```python
    def send_notification_safely(event_type, event_id, timestamp):
        # Create idempotency key (e.g., SHA256 of "movement_123_2026-09-24 10:30")
        key_string = f"{event_type}_{event_id}_{timestamp.strftime('%Y-%m-%d %H:%M')}"
        idempotency_key = hashlib.sha256(key_string.encode()).hexdigest()
        
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                # Try to insert key - if exists, notification already sent
                cur.execute("""
                    INSERT INTO processed_notifications (idempotency_key) 
                    VALUES (%s) 
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING idempotency_key
                """, (idempotency_key,))
                
                if cur.fetchone():  # Key was inserted (not duplicate)
                    # Actually send notification
                    send_notification(event_type, event_id)
                    return True
                else:  # Key already existed
                    return False  # Skip duplicate
        finally:
            conn.close()
    ```
- **Database Constraints**: Use UNIQUE constraint on idempotency key to prevent race conditions.
- **Source**: AWS API Gateway idempotency patterns, Stripe idempotency keys, Google Cloud Pub/Sub deduplication.

## Cross-Cutting Research Insights
1. **No-ORM Doesn't Mean Unsafe**: Proper use of parameterized queries, stored procedures, and explicit transactions provides safety comparable to ORMs.
2. **Transaction Scope Matters**: The critical factor is ensuring related operations share the same transaction boundary - achievable without ORM.
3. **Defense in Depth**: Combine application validation, database constraints, and transactional safety for robust consistency.
4. **Idempotency is Essential**: For any system with retries (network, ETL, notifications), idempotency prevents duplicate processing.
5. **Monitoring Gaps**: Current system lacks consistency monitoring (e.g., alerts when audit log count ≠ movement count).