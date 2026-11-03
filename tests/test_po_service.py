"""Unit tests for POService.receive validation."""

import pytest
from app.services import POService, POServiceError
from app.repositories import PurchaseOrderRepository, POError
from unittest.mock import patch, MagicMock


class TestPOServiceReceiveValidation:
    """Service-layer validation for PO receive."""

    def test_receive_validate_partial_qty(self, app, sample_po_in_transit, admin_user):
        """Valid partial quantity passes validation."""
        with app.app_context():
            with patch.object(PurchaseOrderRepository, 'receive') as mock_receive:
                mock_receive.return_value = None
                POService.receive(po_id=sample_po_in_transit, quantity=8, user_id=admin_user['id'], notes="Partial", location="WH1", idempotency_key="k-8")
                mock_receive.assert_called_once_with(sample_po_in_transit, 8, admin_user['id'], "Partial", "WH1", "k-8")

    def test_receive_validate_full_qty(self, app, sample_po_in_transit, admin_user):
        """Valid full quantity (completing PO) passes validation."""
        with app.app_context():
            with patch.object(PurchaseOrderRepository, 'receive') as mock_receive:
                mock_receive.return_value = None
                POService.receive(po_id=sample_po_in_transit, quantity=2, user_id=admin_user['id'], notes="Final", location="WH1")
                mock_receive.assert_called_once_with(sample_po_in_transit, 2, admin_user['id'], "Final", "WH1", None)

    def test_receive_reject_over_outstanding(self, app, sample_po_partial_received, admin_user):
        """Quantity exceeding outstanding rejected."""
        with app.app_context():
            # PO has quantity=10, already received 8, outstanding=2
            # Trying to receive 5 should exceed outstanding
            with pytest.raises(POServiceError, match="exceeds outstanding"):
                POService.receive(po_id=sample_po_partial_received, quantity=5, user_id=admin_user['id'], notes="", location="")

    def test_receive_reject_wrong_status(self, app, sample_po_approved, admin_user):
        """PO not in in_transit rejected."""
        with app.app_context():
            with pytest.raises(POServiceError, match="Invalid PO transition"):
                POService.receive(po_id=sample_po_approved, quantity=5, user_id=admin_user['id'], notes="", location="")

    def test_receive_reject_zero_negative_qty(self, app, sample_po_in_transit, admin_user):
        """Zero or negative quantity rejected."""
        with app.app_context():
            with pytest.raises(POServiceError, match="must be positive"):
                POService.receive(po_id=sample_po_in_transit, quantity=0, user_id=admin_user['id'])
            with pytest.raises(POServiceError, match="must be positive"):
                POService.receive(po_id=sample_po_in_transit, quantity=-1, user_id=admin_user['id'])

    def test_receive_reject_nonexistent_user(self, app, sample_po_in_transit):
        """Non-existent user rejected."""
        with app.app_context():
            with pytest.raises(POServiceError, match="User 999 not found"):
                POService.receive(po_id=1, quantity=5, user_id=999)

    def test_receive_reject_nonexistent_po(self, app, admin_user):
        """Non-existent PO rejected."""
        with app.app_context():
            with pytest.raises(POServiceError, match="Purchase order 999 not found"):
                POService.receive(po_id=999, quantity=5, user_id=admin_user['id'])

    def test_receive_reject_cancelled_po(self, app, sample_po_cancelled, admin_user):
        """Cancelled PO cannot be received."""
        with app.app_context():
            with pytest.raises(POServiceError, match="Invalid PO transition: cancelled -> received"):
                POService.receive(po_id=sample_po_cancelled, quantity=5, user_id=admin_user['id'])