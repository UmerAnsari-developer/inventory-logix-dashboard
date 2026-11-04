"""Unit tests for MovementRepository movement list/export methods."""

import pytest
from app.repositories import MovementRepository
from app.repositories import POError
from unittest.mock import patch, MagicMock


class TestMovementRepositoryListMovements:
    """Unit tests for MovementRepository.list_movements."""

    def test_list_movements_calls_sp_with_defaults(self, app):
        """list_movements calls sp_movement_list with default filters."""
        with app.app_context():
            with patch('app.repositories.movement_repo.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_cur.fetchall.return_value = [
                    {"id": 1, "type": "IN", "quantity": 10, "reference": "PO-123", "notes": "", "user_id": 1, "created_at": "2024-01-15 10:00", "total_count": 1, "product_name": "Test Product", "sku": "SKU-001", "user_name": "admin"}
                ]
                mock_get_cursor.return_value.__enter__.return_value = mock_cur

                result = MovementRepository.list_movements()

                mock_cur.execute.assert_called_once()
                call_args = mock_cur.execute.call_args
                assert "sp_movement_list" in call_args[0][0]
                assert len(result) == 1

    def test_list_movements_calls_sp_with_all_filters(self, app):
        """list_movements passes all filter params correctly."""
        with app.app_context():
            with patch('app.repositories.movement_repo.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_cur.fetchall.return_value = []
                mock_get_cursor.return_value.__enter__.return_value = mock_cur

                MovementRepository.list_movements(
                    type_filter=["IN", "OUT"],
                    date_from="2024-01-01",
                    date_to="2024-01-31",
                    product_id=42,
                    user_id=1,
                    page=3,
                    per_page=50,
                    sort_by="quantity",
                    sort_order="asc"
                )

                mock_cur.execute.assert_called_once()
                call_args = mock_cur.execute.call_args
                assert "sp_movement_list" in call_args[0][0]
                params = call_args[0][1]
                assert params == (["IN", "OUT"], "2024-01-01", "2024-01-31", 42, 1, 3, 50, "quantity", "asc")

    def test_list_movements_returns_pagination_info(self, app):
        """list_movements returns rows and total_count from SP."""
        with app.app_context():
            with patch('app.repositories.movement_repo.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_cur.fetchall.return_value = [
                    {"id": 1, "type": "IN", "quantity": 10, "reference": "PO-123", "notes": "", "user_id": 1, "created_at": "2024-01-15 10:00", "total_count": 150, "product_name": "Test Product", "sku": "SKU-001", "user_name": "admin"},
                    {"id": 2, "type": "OUT", "quantity": 5, "reference": "SO-456", "notes": "", "user_id": 2, "created_at": "2024-01-15 11:00", "total_count": 150, "product_name": "Test Product", "sku": "SKU-002", "user_name": "manager"}
                ]
                mock_get_cursor.return_value.__enter__.return_value = mock_cur

                rows = MovementRepository.list_movements(page=2, per_page=20)

                assert len(rows) == 2
                assert rows[0]["total_count"] == 150
                assert rows[1]["total_count"] == 150


class TestMovementRepositoryGetMovementCount:
    """Unit tests for MovementRepository.get_movement_count."""

    def test_get_movement_count_calls_sp_with_filters(self, app):
        """get_movement_count calls sp_movement_count with correct params."""
        with app.app_context():
            with patch('app.repositories.movement_repo.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_cur.fetchone.return_value = {"sp_movement_count": 75}
                mock_get_cursor.return_value.__enter__.return_value = mock_cur

                count = MovementRepository.get_movement_count(
                    type_filter=["IN"],
                    date_from="2024-01-01",
                    date_to="2024-12-31"
                )

                mock_cur.execute.assert_called_once()
                call_args = mock_cur.execute.call_args
                assert "sp_movement_count" in call_args[0][0]
                params = call_args[0][1]
                assert params == (["IN"], "2024-01-01", "2024-12-31", None, None)

    def test_get_movement_count_returns_int(self, app):
        """get_movement_count returns integer count."""
        with app.app_context():
            with patch('app.repositories.movement_repo.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_cur.fetchone.return_value = {"sp_movement_count": 42}
                mock_get_cursor.return_value.__enter__.return_value = mock_cur

                count = MovementRepository.get_movement_count()
                assert count == 42
                assert isinstance(count, int)


class TestMovementRepositoryExportMovements:
    """Unit tests for MovementRepository.export_movements."""

    def test_export_movements_uses_csv_writer(self, app):
        """export_movements uses csv.DictWriter to generate CSV."""
        with app.app_context():
            with patch('app.repositories.movement_repo.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_cur.fetchall.return_value = [
                    {"id": 1, "type": "IN", "quantity": 10, "reference": "PO-123", "notes": "test", "created_at": "2024-01-15 10:00", "user_id": 1, "product_name": "Test Product", "sku": "SKU-001", "user_name": "admin"}
                ]
                mock_get_cursor.return_value.__enter__.return_value = mock_cur

                lines = list(MovementRepository.export_movements())

                assert len(lines) == 2  # header + 1 row
                assert "id,type,quantity" in lines[0]
                assert "IN" in lines[1]

    def test_export_movements_passes_sort_params(self, app):
        """export_movements passes sort and order to SP."""
        with app.app_context():
            with patch('app.repositories.movement_repo.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_cur.fetchall.return_value = [
                    {"id": 1, "type": "IN", "quantity": 10, "reference": "PO-123", "notes": "test", "created_at": "2024-01-15 10:00", "user_id": 1, "product_name": "Test Product", "sku": "SKU-001", "user_name": "admin"}
                ]
                mock_get_cursor.return_value.__enter__.return_value = mock_cur

                lines = list(MovementRepository.export_movements(
                    sort_by="quantity",
                    sort_order="desc",
                    limit=100
                ))

                mock_cur.execute.assert_called_once()
                call_args = mock_cur.execute.call_args
                assert "sp_movement_export_data" in call_args[0][0]
                params = call_args[0][1]
                assert params[-2] == "quantity"
                assert params[-1] == "desc"

    def test_export_movements_empty_result(self, app):
        """export_movements yields only header when no rows."""
        with app.app_context():
            with patch('app.repositories.movement_repo.get_cursor') as mock_get_cursor:
                mock_cur = MagicMock()
                mock_cur.fetchall.return_value = []
                mock_get_cursor.return_value.__enter__.return_value = mock_cur

                lines = list(MovementRepository.export_movements())

                assert len(lines) == 1  # only header
                assert "id,type,quantity" in lines[0]