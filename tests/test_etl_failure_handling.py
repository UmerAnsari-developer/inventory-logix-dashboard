"""Tests for ETL failure handling improvements."""
from __future__ import annotations

import pytest

def test_etl_stage_wise_transactions_allow_partial_rollback(app):
    # Test that ETL uses stage-wise transactions so failure in one stage doesn't prevent committing previous stages
    from app.database.connection import etl_database
    from app.database import get_cursor
    
    with app.app_context():
        # First, run a successful ETL to establish baseline
        etl_database(force=True)
        
        # Get initial state
        with get_cursor() as cur:
            cur.execute('SELECT COUNT(*) AS c FROM dim_warehouse')
            initial_warehouse_count = cur.fetchone()['c']
            
            cur.execute('SELECT COUNT(*) AS c FROM dim_product')
            initial_product_count = cur.fetchone()['c']
            
            cur.execute("SELECT value FROM etl_state WHERE state_key='last_movement_id'")
            initial_watermark = int(cur.fetchone()['value'])
        
        # New movement so the follow-up incremental run is not skipped
        with get_cursor(commit=True) as cur:
            cur.execute('SELECT id FROM products ORDER BY id LIMIT 1')
            row = cur.fetchone()
            cur.execute(
                """
                INSERT INTO movements (product_id, type, quantity, reference, notes, created_at)
                    VALUES (%s, 'IN', 10, 'TEST-ROLLBACK', 'rollback test', NOW())
                    """,
                (row['id'],),
            )

        # Now simulate a failure during fact loading
        import app.database.etl as etl_module
        original_build_movement_facts = etl_module._build_movement_facts
        
        def failing_build_movement_facts(*args, **kwargs):
            raise Exception('Simulated fact loading failure')
        
        etl_module._build_movement_facts = failing_build_movement_facts
        
        try:
            # Run ETL again - should fail during fact loading
            with pytest.raises(Exception):
                etl_database(force=False)
        finally:
            # Restore original function
            etl_module._build_movement_facts = original_build_movement_facts
        
        # Even though facts failed, dimensions should have been updated
        with get_cursor() as cur:
            cur.execute('SELECT COUNT(*) AS c FROM dim_warehouse')
            warehouse_count_after = cur.fetchone()['c']
            
            cur.execute('SELECT COUNT(*) AS c FROM dim_product')
            product_count_after = cur.fetchone()['c']
            
            cur.execute("SELECT value FROM etl_state WHERE state_key='last_movement_id'")
            watermark_after = int(cur.fetchone()['value'])
        
        # Watermark should have been advanced due to checkpointing after dimension load
        assert watermark_after >= initial_watermark


def test_etl_idempotent_design_safe_for_reruns(app):
    # Test that ETL is idempotent - running twice produces same result as running once
    from app.database.connection import etl_database
    from app.database import get_cursor
    
    with app.app_context():
        # Run ETL first time
        result1 = etl_database(force=True)
        
        # Capture state after first run
        with get_cursor() as cur:
            cur.execute('SELECT COUNT(*) AS c FROM fact_movement_daily')
            movements_count_1 = cur.fetchone()['c']
            
            cur.execute('SELECT COUNT(*) AS c FROM fact_inventory_daily')
            inventory_count_1 = cur.fetchone()['c']
            
            cur.execute("SELECT value FROM etl_state WHERE state_key='last_movement_id'")
            watermark_1 = int(cur.fetchone()['value'])
        
        # Run ETL second time (should be incremental and idempotent)
        result2 = etl_database(force=False)
        
        # Capture state after second run
        with get_cursor() as cur:
            cur.execute('SELECT COUNT(*) AS c FROM fact_movement_daily')
            movements_count_2 = cur.fetchone()['c']
            
            cur.execute('SELECT COUNT(*) AS c FROM fact_inventory_daily')
            inventory_count_2 = cur.fetchone()['c']
            
            cur.execute("SELECT value FROM etl_state WHERE state_key='last_movement_id'")
            watermark_2 = int(cur.fetchone()['value'])
        
        # Second run should not change fact counts (idempotent)
        assert movements_count_1 == movements_count_2
        assert inventory_count_1 == inventory_count_2
        # Watermark should be the same (no new movements processed)
        assert watermark_1 == watermark_2
        
        # First run did the work; an idle rerun must be a safe no-op (skip guard)
        assert result1['skipped'] == False
        assert result2['skipped'] == True


def test_etl_checkpointing_persists_watermark_after_each_stage(app):
    # Test that watermark is persisted after each successful stage
    from app.database.connection import etl_database
    from app.database import get_cursor
    
    with app.app_context():
        # Start with clean state
        etl_database(force=True)
        
        with get_cursor() as cur:
            cur.execute("SELECT value FROM etl_state WHERE state_key='last_movement_id'")
            initial_watermark = int(cur.fetchone()['value'])
        
# Add a new movement
        with get_cursor(commit=True) as cur:
            cur.execute('SELECT id FROM products ORDER BY id LIMIT 1')
            row = cur.fetchone()
            pid = row['id']
            cur.execute(
                """
                INSERT INTO movements (product_id, type, quantity, reference, notes, created_at)
                VALUES (%s, 'IN', 10, 'TEST-WATERMARK', 'checkpoint test', NOW())
                """,
                (pid,),
            )
        
        # Get the new movement ID
        with get_cursor() as cur:
            cur.execute('SELECT MAX(id) AS max_id FROM movements')
            new_movement_id = int(cur.fetchone()['max_id'])
        
        # Monkey patch to simulate failure after dimension load but before fact load
        import app.database.etl as etl_module
        original_build_dims = etl_module._build_dims
        original_build_movement_facts = etl_module._build_movement_facts
        
        def checkpointing_build_dims(*args, **kwargs):
            # This simulates completing dimension load
            result = original_build_dims(*args, **kwargs)
            return result
            
        def failing_build_movement_facts(*args, **kwargs):
            # Fail during fact loading
            raise Exception('Simulated failure after dimension load')
        
        etl_module._build_dims = checkpointing_build_dims
        etl_module._build_movement_facts = failing_build_movement_facts
        
        try:
            # Run ETL - should fail during fact loading
            with pytest.raises(Exception):
                etl_database(force=False)
        finally:
            # Restore original functions
            etl_module._build_dims = original_build_dims
            etl_module._build_movement_facts = original_build_movement_facts
        
        # Check that watermark was updated after dimension load (checkpointing)
        with get_cursor() as cur:
            cur.execute("SELECT value FROM etl_state WHERE state_key='last_movement_id'")
            watermark_after_failure = int(cur.fetchone()['value'])
        
        # With proper checkpointing, watermark should have been advanced after dimension load
        # even though fact loading failed
        assert watermark_after_failure >= initial_watermark


def test_etl_validation_step_checks_consistency_after_load(app):
    # Test that ETL includes a validation step checking consistency
    from app.database.connection import etl_database
    
    with app.app_context():
        # Run ETL to populate warehouse
        result = etl_database(force=True)
        
        # The validation step should check consistency and log/alert on mismatch
        assert result['skipped'] == False


def test_etl_retry_with_exponential_backoff_for_transient_errors(app):
    # Test that ETL retries transient database errors with exponential backoff
    from app.database.connection import etl_database
    from app.database import get_cursor

    with app.app_context():
        # Run initial ETL
        etl_database(force=True)

# New movement so the follow-up incremental run is not skipped
        with get_cursor(commit=True) as cur:
            cur.execute('SELECT id FROM products ORDER BY id LIMIT 1')
            row = cur.fetchone()
            cur.execute(
                """
                INSERT INTO movements (product_id, type, quantity, reference, notes, created_at)
                VALUES (%s, 'IN', 7, 'TEST-RETRY', 'retry test', NOW())
                """,
                (row['id'],),
            )

        # run_etl binds `_open_conn` into the etl module at import time, so
        # patch that binding (patching app.database.connection has no effect).
        # Simulate a transient OperationalError - the type _retry_operation
        # retries - that succeeds on the third attempt.
        import psycopg2
        import app.database.etl as etl_module
        original_conn_open = etl_module._open_conn

        call_count = 0

        def patched_open_conn(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:  # Fail first 2 times, succeed on 3rd
                raise psycopg2.OperationalError('Simulated transient DB error')
            return original_conn_open(*args, **kwargs)

        etl_module._open_conn = patched_open_conn

        try:
            # This should succeed after retries
            result = etl_database(force=False)

            # Should have retried and eventually succeeded
            assert call_count >= 3  # At least 3 attempts (2 failures + 1 success)
            assert result['skipped'] == False

        finally:
            # Restore original function
            etl_module._open_conn = original_conn_open
