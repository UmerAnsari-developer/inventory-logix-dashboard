"""Admin dashboard service."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from flask_login import current_user

from ..database import get_cursor
from ..repositories import (
    UserRepository,
    ProductRepository,
    MovementRepository,
    SupplierRepository,
    SystemBackupRepository,
    SystemConfigRepository,
    UserActivityRepository,
)
from app.services.nnotification_center_service import NotificationCenterService
from app.services.log_viewer_service import LogViewerService


class AdminDashboardService:
    """Service for gathering admin dashboard data."""

    @staticmethod
    def get_dashboard_data() -> dict[str, Any]:
        """Get data for the admin dashboard."""
        if not current_user.is_authenticated:
            raise ValueError("Authentication required")
        if current_user.role not in ("admin", "manager"):
            raise ValueError("Insufficient permissions")

        with get_cursor() as cur:
            # Total users
            cur.execute("SELECT COUNT(*) AS cnt FROM users")
            total_users = cur.fetchone()["cnt"]

            # Active users (logged in within last 30 days)
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM users WHERE last_login >= %s",
                (date.today() - timedelta(days=30),),
            )
            active_users = cur.fetchone()["cnt"]

            # Total products
            cur.execute("SELECT COUNT(*) AS cnt FROM products")
            total_products = cur.fetchone()["cnt"]

            # Low stock products
            cur.execute(
                """
                SELECT COUNT(*) AS cnt FROM products
                WHERE current_stock <= reorder_point AND on_order <= 0
                """
            )
            low_stock_products = cur.fetchone()["cnt"]

            # Total suppliers
            cur.execute("SELECT COUNT(*) AS cnt FROM suppliers")
            total_suppliers = cur.fetchone()["cnt"]

            # Movements today
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM movements WHERE created_at::date = %s",
                (date.today(),),
            )
            movements_today = cur.fetchone()["cnt"]

            # Recent backups (last 5)
            cur.execute(
                """
                SELECT id, backup_name, backup_type, status, created_at
                FROM system_backups
                ORDER BY created_at DESC
                LIMIT 5
                """
            )
            recent_backups = [dict(row) for row in cur.fetchall()]

            # Recent system config overrides (last 5)
            cur.execute(
                """
                SELECT id, key, value, updated_at
                FROM system_config_overrides
                ORDER BY updated_at DESC
                LIMIT 5
                """
            )
            recent_config_overrides = [dict(row) for row in cur.fetchall()]

            # Recent user activities (last 10)
            cur.execute(
                """
                SELECT id, user_id, action, target_type, created_at
                FROM audit_log
                ORDER BY created_at DESC
                LIMIT 10
                """
            )
            recent_activities = [dict(row) for row in cur.fetchall()]

            # Recent log entries (last 10)
            recent_logs = LogViewerService.get_log_entries(limit=10)

            # Unread notification count
            unread_notifications = NotificationCenterService.get_unread_count()

        return {
            "total_users": total_users,
            "active_users": active_users,
            "total_products": total_products,
            "low_stock_products": low_stock_products,
            "total_suppliers": total_suppliers,
            "movements_today": movements_today,
            "recent_backups": recent_backups,
            "recent_config_overrides": recent_config_overrides,
            "recent_activities": recent_activities,
            "recent_logs": recent_logs,
            "unread_notifications": unread_notifications,
        }