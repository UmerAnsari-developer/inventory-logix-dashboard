"""Unit tests for PurchaseOrderRepository receive and list_receipts methods."""

import pytest
from app.repositories import PurchaseOrderRepository
from unittest.mock import patch, MagicMock


class TestPurchaseOrderRepositoryReceive:
    """Repository method calls to sp_po_transition."""

    def test_receive_calls_sp_po_transition(self, app):
        """receive() calls sp_po_transition with correct params."""
        with app.app_context():
            with patch('app.repositories.po_repo.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_get_cursor.return_value.__enter__.return_value = mock_cur
                
                PurchaseOrderRepository.receive(
                    po_id=1, quantity=8, user_id=2, notes="test", location="WH1",
                    idempotency_key="k-1"
                )
                
                mock_cur.execute.assert_called_once()
                call_args = mock_cur.execute.call_args
                assert "sp_po_transition" in call_args[0][0]
                # Params: (po_id, 'received', quantity, user_id, notes, location, idempotency_key)
                params = call_args[0][1]
                assert len(params) == 7
                assert params[0] == 1
                assert params[1] == 'received'
                assert params[2] == 8
                assert params[3] == 2
                assert params[4] == 'test'
                assert params[5] == 'WH1'
                # HTTP key is threaded through, not regenerated (P0 idempotency fix)
                assert params[6] == 'k-1'

    def test_receive_generates_fallback_key_when_missing(self, app):
        """Direct service callers without an HTTP key still get DB-level dedupe."""
        with app.app_context():
            with patch('app.repositories.po_repo.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_get_cursor.return_value.__enter__.return_value = mock_cur

                PurchaseOrderRepository.receive(
                    po_id=42, quantity=5, user_id=7, notes="", location=""
                )

                params = mock_cur.execute.call_args[0][1]
                assert len(params) == 7
                assert params[6].startswith('recv-42-')

    def test_receive_passes_all_params(self, app):
        """receive() passes all 7 params with status='received' hardcoded."""
        with app.app_context():
            with patch('app.repositories.po_repo.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_get_cursor.return_value.__enter__.return_value = mock_cur
                
                PurchaseOrderRepository.receive(
                    po_id=42, quantity=5, user_id=7, notes="delivery note",
                    location="Dock B", idempotency_key="k-42"
                )
                
                call_args = mock_cur.execute.call_args
                params = call_args[0][1]
                # (p_id, p_new_status, p_received_quantity, p_received_by, p_notes, p_location, p_idempotency_key)
                assert len(params) == 7
                assert params == (42, 'received', 5, 7, 'delivery note', 'Dock B', 'k-42')


class TestPurchaseOrderRepositoryListReceipts:
    """Repository method calls to sp_goods_receipt_list."""

    def test_list_receipts_calls_sp_goods_receipt_list(self, app):
        """list_receipts() calls sp_goods_receipt_list."""
        with app.app_context():
            with patch('app.repositories.po_repo.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_cur.fetchall.return_value = [
                    {'id': 1, 'po_id': 1, 'quantity': 5, 'received_by': 2, 'received_at': '2026-01-15', 'notes': 'Test', 'location': 'WH1', 'product_name': 'Product A', 'supplier_name': 'Supplier X'}
                ]
                mock_get_cursor.return_value.__enter__.return_value = mock_cur
                
                results = PurchaseOrderRepository.list_receipts(po_id=1)
                
                mock_cur.execute.assert_called_once()
                call_args = mock_cur.execute.call_args
                assert "sp_goods_receipt_list" in call_args[0][0]
                assert call_args[0][1] == (1, None, None, None)
                assert len(results) == 1
                assert results[0]['quantity'] == 5

    def test_list_receipts_filters_correctly(self, app):
        """list_receipts() passes filter params correctly."""
        with app.app_context():
            with patch('app.repositories.po_repo.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_cur.fetchall.return_value = []
                mock_get_cursor.return_value.__enter__.return_value = mock_cur
                
                # Filter by po_id
                PurchaseOrderRepository.list_receipts(po_id=5)
                assert mock_cur.execute.call_args[0][1] == (5, None, None, None)
                
                # Filter by user_id
                PurchaseOrderRepository.list_receipts(received_by=3)
                assert mock_cur.execute.call_args[0][1] == (None, 3, None, None)
                
                # Filter by date range
                PurchaseOrderRepository.list_receipts(date_from='2026-01-01', date_to='2026-01-31')
                assert mock_cur.execute.call_args[0][1] == (None, None, '2026-01-01', '2026-01-31')
                
                # No filters
                PurchaseOrderRepository.list_receipts()
                assert mock_cur.execute.call_args[0][1] == (None, None, None, None)