"""Unit tests for MovementService list/export methods."""

import pytest
from app.services import MovementService
from app.services.movement_service import MovementError
from app.repositories import MovementRepository
from unittest.mock import patch, MagicMock


class TestMovementServiceListMovements:
    """Unit tests for MovementService.list_movements validation."""

    def test_list_movements_valid_params(self, app):
        """Valid params pass validation and call repository."""
        with app.app_context():
            with patch.object(MovementRepository, 'list_movements') as mock_list:
                mock_list.return_value = []

                result = MovementService.list_movements(
                    page=1, per_page=20,
                    sort_by="created_at", sort_order="desc"
                )

                assert result == []
                mock_list.assert_called_once_with(
                    type_filter=None, date_from=None, date_to=None,
                    product_id=None, user_id=None,
                    page=1, per_page=20, sort_by="created_at", sort_order="desc"
                )

    def test_list_movements_rejects_page_below_one(self, app):
        """Page < 1 rejected."""
        with app.app_context():
            with pytest.raises(MovementError, match="Page must be >= 1"):
                MovementService.list_movements(page=0)

    def test_list_movements_clamps_per_page_to_hundred(self, app):
        """per_page > 100 is clamped to 100."""
        with app.app_context():
            with patch.object(MovementRepository, 'list_movements') as mock_list:
                mock_list.return_value = []

                # This should not raise - service should clamp
                result = MovementService.list_movements(per_page=200)
                # Verify it was called with clamped value
                call_args = mock_list.call_args
                assert call_args[1]['per_page'] == 100

    def test_list_movements_rejects_invalid_sort_by(self, app):
        """Invalid sort_by rejected."""
        with app.app_context():
            with pytest.raises(MovementError, match="sort_by must be one of"):
                MovementService.list_movements(sort_by="invalid_column")

    def test_list_movements_rejects_invalid_sort_order(self, app):
        """Invalid sort_order rejected."""
        with app.app_context():
            with pytest.raises(MovementError, match="Sort order must be"):
                MovementService.list_movements(sort_order="invalid")

    def test_list_movements_valid_sort_by_values(self, app):
        """All valid sort_by values accepted."""
        with app.app_context():
            valid_sorts = ["created_at", "type", "product", "user", "quantity"]
            for sort_by in valid_sorts:
                with patch.object(MovementRepository, 'list_movements') as mock_list:
                    mock_list.return_value = []
                    result = MovementService.list_movements(sort_by=sort_by)
                    assert result == []

    def test_list_movements_valid_sort_order_values(self, app):
        """Both asc and desc accepted."""
        with app.app_context():
            for sort_order in ["asc", "desc"]:
                with patch.object(MovementRepository, 'list_movements') as mock_list:
                    mock_list.return_value = []
                    result = MovementService.list_movements(sort_order=sort_order)
                    assert result == []

    def test_list_movements_type_filter_single(self, app):
        """Single type filter accepted."""
        with app.app_context():
            with patch.object(MovementRepository, 'list_movements') as mock_list:
                mock_list.return_value = []
                result = MovementService.list_movements(type_filter="IN")
                assert result == []

    def test_list_movements_type_filter_multiple(self, app):
        """Multiple type filters accepted."""
        with app.app_context():
            with patch.object(MovementRepository, 'list_movements') as mock_list:
                mock_list.return_value = []
                result = MovementService.list_movements(type_filter=["IN", "OUT"])
                assert result == []

    def test_list_movements_rejects_invalid_type(self, app):
        """Invalid type filter rejected."""
        with app.app_context():
            with pytest.raises(MovementError, match="Invalid type"):
                MovementService.list_movements(type_filter="INVALID")

    def test_list_movements_date_from_iso_format(self, app):
        """Valid ISO 8601 date accepted."""
        with app.app_context():
            with patch.object(MovementRepository, 'list_movements') as mock_list:
                mock_list.return_value = []
                result = MovementService.list_movements(date_from="2024-01-15")
                assert result == []

    def test_list_movements_rejects_invalid_date_from(self, app):
        """Invalid date_from format rejected."""
        with app.app_context():
            with pytest.raises(MovementError, match="date_from must be ISO 8601 format"):
                MovementService.list_movements(date_from="invalid-date")

    def test_list_movements_date_to_iso_format(self, app):
        """Valid ISO 8601 date_to accepted."""
        with app.app_context():
            with patch.object(MovementRepository, 'list_movements') as mock_list:
                mock_list.return_value = []
                result = MovementService.list_movements(date_to="2024-12-31")
                assert result == []

    def test_list_movements_rejects_invalid_date_to(self, app):
        """Invalid date_to format rejected."""
        with app.app_context():
            with pytest.raises(MovementError, match="date_to must be ISO 8601 format"):
                MovementService.list_movements(date_to="not-a-date")

    def test_list_movements_product_id_int(self, app):
        """Integer product_id accepted."""
        with app.app_context():
            with patch.object(MovementRepository, 'list_movements') as mock_list:
                mock_list.return_value = []
                result = MovementService.list_movements(product_id=42)
                assert result == []

    def test_list_movements_rejects_non_int_product_id(self, app):
        """Non-integer product_id rejected."""
        with app.app_context():
            with pytest.raises(MovementError, match="product_id must be an integer"):
                MovementService.list_movements(product_id="abc")

    def test_list_movements_user_id_int(self, app):
        """Integer user_id accepted."""
        with app.app_context():
            with patch.object(MovementRepository, 'list_movements') as mock_list:
                mock_list.return_value = []
                result = MovementService.list_movements(user_id=1)
                assert result == []

    def test_list_movements_rejects_non_int_user_id(self, app):
        """Non-integer user_id rejected."""
        with app.app_context():
            with pytest.raises(MovementError, match="user_id must be an integer"):
                MovementService.list_movements(user_id="xyz")


class TestMovementServiceExportMovements:
    """Unit tests for MovementService.export_movements validation."""

    def test_export_movements_valid_params(self, app):
        """Valid params pass validation and call repository."""
        with app.app_context():
            with patch.object(MovementRepository, 'export_movements') as mock_export:
                mock_export.return_value = iter(["header\n", "row1\n"])

                result = list(MovementService.export_movements(
                    sort_by="created_at", sort_order="desc", limit=1000
                ))

                assert len(result) == 2
                mock_export.assert_called_once_with(
                    type_filter=None, date_from=None, date_to=None,
                    product_id=None, user_id=None,
                    sort_by="created_at", sort_order="desc", limit=1000
                )

    def test_export_movements_rejects_limit_below_one(self, app):
        """Limit < 1 rejected."""
        with app.app_context():
            with pytest.raises(MovementError, match="Limit must be >= 1"):
                MovementService.export_movements(limit=0)

    def test_export_movements_clamps_limit_to_five_thousand(self, app):
        """Limit > 5000 clamped to 5000."""
        with app.app_context():
            with patch.object(MovementRepository, 'export_movements') as mock_export:
                mock_export.return_value = iter(["header\n"])

                result = list(MovementService.export_movements(limit=10000))
                call_args = mock_export.call_args
                assert call_args[1]['limit'] == 5000

    def test_export_movements_reuses_list_validation(self, app):
        """export_movements reuses list_movements validation for filters."""
        with app.app_context():
            with pytest.raises(MovementError, match="sort_by must be one of"):
                MovementService.export_movements(sort_by="invalid")

            with pytest.raises(MovementError, match="type must be one of|Invalid type"):
                MovementService.export_movements(type_filter="INVALID")


class TestMovementServiceGetMovement:
    """Unit tests for MovementService.get_movement (if implemented)."""

    def test_get_movement_not_implemented_yet(self, app):
        """get_movement not implemented - placeholder test."""
        # This would be implemented if we add GET /api/movements/<id>
        pass


class TestMovementServiceGetProductMovements:
    """Unit tests for MovementService.get_product_movements."""

    def test_get_product_movements_valid(self, app):
        """Valid product_id calls list_movements with product filter."""
        with app.app_context():
            with patch('app.repositories.ProductRepository.find', return_value={"id": 42}):
                with patch('app.services.movement_service.MovementService.list_movements') as mock_list:
                    mock_list.return_value = []
                    from app.services import MovementService

                    result = MovementService.get_product_movements(product_id=42)

                    assert result == []
                    mock_list.assert_called_once_with(product_id=42)

    def test_get_product_movements_rejects_invalid_product_id(self, app):
        """Invalid product_id rejected."""
        with app.app_context():
            with pytest.raises(MovementError, match="product_id must be an integer"):
                from app.services import MovementService
                MovementService.get_product_movements(product_id="abc")

    def test_get_product_movements_product_not_found(self, app):
        """Non-existent product raises error."""
        with app.app_context():
            with patch('app.repositories.ProductRepository.find', return_value=None):
                from app.services import MovementService

                with pytest.raises(MovementError, match="Product 999 not found"):
                    MovementService.get_product_movements(product_id=999)