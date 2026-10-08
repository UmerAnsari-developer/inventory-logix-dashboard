"""Tests for streaming exports."""
from __future__ import annotations

import pytest
import csv
import io
from unittest.mock import patch, MagicMock

from app.services.export_service import ExportService
from app.database import get_cursor


class TestStreamingExports:
    """Test streaming exports for large datasets."""

    @pytest.fixture(autouse=True)
    def setup_db(self, app):
        """Set up test database with large dataset."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                # Clean up
                cur.execute("DELETE FROM products WHERE sku LIKE 'STREAM_%'")
                cur.execute("DELETE FROM suppliers WHERE name LIKE 'STREAM_%'")
                
                # Create test suppliers
                supplier_ids = []
                for i in range(5):
                    cur.execute("""
                        INSERT INTO suppliers (name, location, lead_days, spend_amount, reliability, tone)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (f"STREAM_Supplier_{i}", "Test Location", 5, 1000.00, 90.0, "green"))
                    supplier_ids.append(cur.fetchone()["id"])
                
                # Create many products (simulate large dataset)
                for i in range(1000):
                    cur.execute("""
                        INSERT INTO products (sku, name, category, warehouse, current_stock, reorder_point, 
                                              demand_rate, ordering_cost, holding_cost, unit_price, supplier_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (f"STREAM_{i:04d}", f"Stream Product {i}", "Test", "WH-Pune", 
                          100, 10, 5.0, 10.0, 2.0, 50.0, supplier_ids[i % 5]))
            yield
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM products WHERE sku LIKE 'STREAM_%'")
                cur.execute("DELETE FROM suppliers WHERE name LIKE 'STREAM_%'")

    def test_export_products_uses_streaming(self, app):
        """Test that export_products uses streaming response."""
        with app.app_context():
            response = ExportService.export_products()
            
            # Should be a streaming response
            assert hasattr(response, 'response')
            # Check it's a generator or iterable
            assert hasattr(response.response, '__iter__')

    def test_export_products_streaming_yields_chunks(self, app):
        """Test that streaming export yields chunks."""
        with app.app_context():
            response = ExportService.export_products()
            
            # Collect all chunks
            chunks = list(response.response)
            assert len(chunks) > 0
            
            # First chunk should contain header
            first_chunk = chunks[0]
            assert "SKU" in first_chunk
            assert "Product" in first_chunk

    def test_export_large_dataset_memory_efficient(self, app):
        """Test that large dataset export doesn't load all into memory."""
        with app.app_context():
            response = ExportService.export_products()
            
            # Verify it's streaming (not loading all 1000 rows at once)
            chunks = list(response.response)
            assert len(chunks) > 1  # Multiple chunks

    def test_export_movements_streaming(self, app):
        """Test that export_movements uses streaming."""
        with app.app_context():
            response = ExportService.export_movements(limit=100)
            
            assert hasattr(response, 'response')
            assert hasattr(response.response, '__iter__')
            
            chunks = list(response.response)
            assert len(chunks) > 0
            assert "ID" in chunks[0]
            assert "SKU" in chunks[0]

    def test_export_sets_correct_headers(self, app):
        """Test that streaming export sets correct headers."""
        with app.app_context():
            response = ExportService.export_products()
            
            assert response.mimetype == "text/csv"
            assert "attachment" in response.headers.get("Content-Disposition", "")
            assert ".csv" in response.headers.get("Content-Disposition", "")

    def test_streaming_handles_empty_result(self, app):
        """Test streaming export with empty result."""
        with app.app_context():
            # Test with a search that won't match any products
            with patch('app.services.export_service.ExportService._product_rows_generator') as mock_gen:
                mock_gen.return_value = iter([])
                
                response = ExportService.export_products()
                
                chunks = list(response.response)
                # Should have header + empty chunk
                assert len(chunks) >= 1
                assert "SKU" in chunks[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])