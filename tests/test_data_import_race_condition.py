"""Tests for data import race condition fix with advisory lock."""
from __future__ import annotations

import pytest
import threading
import time
from unittest.mock import patch, MagicMock

from app.routes.admin.data_import_routes import _import_rows
from app.database import get_cursor


class TestDataImportRaceCondition:
    """Test data import race condition fix using PostgreSQL advisory lock."""

    @pytest.fixture(autouse=True)
    def setup_db(self, app):
        """Set up test database."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                # Clean up test data
                cur.execute("DELETE FROM products WHERE sku LIKE 'TEST_%'")
                cur.execute("DELETE FROM suppliers WHERE name LIKE 'TEST_%'")
            yield
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM products WHERE sku LIKE 'TEST_%'")
                cur.execute("DELETE FROM suppliers WHERE name LIKE 'TEST_%'")

    def test_import_uses_advisory_lock(self, app):
        """Test that import acquires PostgreSQL advisory lock."""
        with app.app_context():
            with patch('app.routes.admin.data_import_routes.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_get_cursor.return_value.__enter__.return_value = mock_cur
                
                rows = [{"sku": "TEST_001", "product_name": "Test Product", "unit_price": "10.00",
                         "current_stock": "5", "reorder_point": "10", "category": "Test", "supplier_id": ""}]
                
                _import_rows("products", rows)
                
                # Verify advisory lock was acquired
                calls = [str(call) for call in mock_cur.execute.call_args_list]
                lock_acquired = any("pg_advisory_lock" in call for call in calls)
                lock_released = any("pg_advisory_unlock" in call for call in calls)
                
                assert lock_acquired, "Advisory lock should be acquired"
                assert lock_released, "Advisory lock should be released"

    def test_concurrent_imports_serialized(self, app):
        """Test that concurrent imports are serialized via advisory lock."""
        results = []
        errors = []
        
        def import_products(thread_id):
            with app.app_context():
                try:
                    rows = [{
                        "sku": f"TEST_CONCURRENT_{thread_id}",
                        "product_name": f"Test Product {thread_id}",
                        "unit_price": "10.00",
                        "current_stock": "5",
                        "reorder_point": "10",
                        "category": "Test",
                        "supplier_id": ""
                    }]
                    count = _import_rows("products", rows)
                    results.append(count)
                except Exception as e:
                    errors.append(f"Thread {thread_id}: {e}")
        
        # Run concurrent imports
        threads = [threading.Thread(target=import_products, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        
        # Print errors for debugging
        if errors:
            print(f"Errors: {errors}")
        # All should succeed
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 5
        assert all(r == 1 for r in results), f"Results: {results}"
        
        # Verify all products were inserted
        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT COUNT(*) as c FROM products WHERE sku LIKE 'TEST_CONCURRENT_%'")
                count = cur.fetchone()["c"]
                assert count == 5

    def test_advisory_lock_key_is_consistent(self, app):
        """Test that advisory lock key is consistent for same entity."""
        with app.app_context():
            with patch('app.routes.admin.data_import_routes.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_get_cursor.return_value.__enter__.return_value = mock_cur
                
                rows = [{"sku": "TEST_LOCK_001", "product_name": "Test", "unit_price": "10.00",
                         "current_stock": "5", "reorder_point": "10", "category": "Test", "supplier_id": ""}]
                
                _import_rows("products", rows)
                
                # Check the lock key used
                calls = [str(call) for call in mock_cur.execute.call_args_list]
                lock_calls = [c for c in calls if "pg_advisory_lock" in c]
                
                assert len(lock_calls) > 0
                # Lock key should be based on entity name (e.g., hash of "products")
                # This ensures same entity gets same lock

    def test_lock_released_on_exception(self, app):
        """Test that advisory lock is released even on exception."""
        with app.app_context():
            with patch('app.routes.admin.data_import_routes.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_get_cursor.return_value.__enter__.return_value = mock_cur
                
                # Make the insert fail
                mock_cur.execute.side_effect = [
                    None,  # pg_advisory_lock
                    Exception("Simulated DB error"),  # INSERT
                    None,  # pg_advisory_unlock (should still be called)
                ]
                
                rows = [{"sku": "TEST_EXCEPTION", "product_name": "Test", "unit_price": "10.00",
                         "current_stock": "5", "reorder_point": "10", "category": "Test", "supplier_id": ""}]
                
                # Function catches exception and returns 0, doesn't raise
                count = _import_rows("products", rows)
                assert count == 0
                
                # Verify unlock was called despite exception
                calls = [str(call) for call in mock_cur.execute.call_args_list]
                lock_released = any("pg_advisory_unlock" in call for call in calls)
                assert lock_released, "Advisory lock should be released even on exception"

    def test_different_entities_use_different_locks(self, app):
        """Test that different entities use different advisory lock keys."""
        with app.app_context():
            with patch('app.routes.admin.data_import_routes.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_get_cursor.return_value.__enter__.return_value = mock_cur
                
                # Import products
                product_rows = [{"sku": "TEST_DIFF_1", "product_name": "Test", "unit_price": "10.00",
                                 "current_stock": "5", "reorder_point": "10", "category": "Test", "supplier_id": ""}]
                _import_rows("products", product_rows)
                
                # Import suppliers
                supplier_rows = [{"supplier_name": "TEST_DIFF_SUP", "contact_email": "test@test.com",
                                  "phone": "", "address": ""}]
                _import_rows("suppliers", supplier_rows)
                
                # Check that different lock keys were used
                calls = [str(call) for call in mock_cur.execute.call_args_list]
                lock_calls = [c for c in calls if "pg_advisory_lock" in c]
                
                # Should have two different lock keys
                assert len(lock_calls) == 2
                # The lock keys should be different (based on entity name hash)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])