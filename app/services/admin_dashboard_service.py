"""Admin dashboard service."""
from __future__ import annotations

import os
import psutil
import shutil
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
                "SELECT COUNT(*) AS cnt FROM movements "
                "WHERE created_at::date = %s AND deleted_at IS NULL",
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
                SELECT id, key, value, is_sensitive, updated_at
                FROM system_config_overrides
                ORDER BY updated_at DESC
                LIMIT 5
                """
            )
            recent_config_overrides = []
            for row in cur.fetchall():
                override = dict(row)
                if override.get("is_sensitive"):
                    override["display_value"] = "********"
                else:
                    override["display_value"] = override["value"]
                recent_config_overrides.append(override)

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

    @staticmethod
    def get_health_status() -> dict[str, Any]:
        """Get system health status for admin monitoring."""
        health = {
            "status": "healthy",
            "checks": {}
        }
        
        # Database check
        try:
            with get_cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            health["checks"]["database"] = {"status": "healthy", "message": "Database connection OK"}
        except Exception as e:
            health["checks"]["database"] = {"status": "unhealthy", "message": str(e)}
            health["status"] = "degraded"
        
        # Cache/Redis check
        try:
            from app.utils.cache import global_cache
            global_cache.set("health_check", "ok", ttl=10)
            val = global_cache.get("health_check")
            if val == "ok":
                health["checks"]["cache"] = {"status": "healthy", "message": "Cache OK"}
            else:
                health["checks"]["cache"] = {"status": "degraded", "message": "Cache not responding"}
                health["status"] = "degraded"
        except Exception as e:
            health["checks"]["cache"] = {"status": "unhealthy", "message": str(e)}
            health["status"] = "degraded"
        
        # Disk space check
        try:
            total, used, free = shutil.disk_usage("/")
            free_percent = (free / total) * 100
            if free_percent > 10:
                health["checks"]["disk"] = {"status": "healthy", "message": f"Disk free: {free_percent:.1f}%"}
            elif free_percent > 5:
                health["checks"]["disk"] = {"status": "warning", "message": f"Disk free: {free_percent:.1f}%"}
                health["status"] = "degraded"
            else:
                health["checks"]["disk"] = {"status": "critical", "message": f"Disk free: {free_percent:.1f}%"}
                health["status"] = "unhealthy"
        except Exception as e:
            health["checks"]["disk"] = {"status": "unknown", "message": str(e)}
        
        # Memory check
        try:
            mem = psutil.virtual_memory()
            if mem.percent < 80:
                health["checks"]["memory"] = {"status": "healthy", "message": f"Memory usage: {mem.percent:.1f}%"}
            elif mem.percent < 90:
                health["checks"]["memory"] = {"status": "warning", "message": f"Memory usage: {mem.percent:.1f}%"}
                health["status"] = "degraded"
            else:
                health["checks"]["memory"] = {"status": "critical", "message": f"Memory usage: {mem.percent:.1f}%"}
                health["status"] = "unhealthy"
        except Exception as e:
            health["checks"]["memory"] = {"status": "unknown", "message": str(e)}
        
        # ETL status check
        try:
            with get_cursor() as cur:
                cur.execute("""
                    SELECT state_key, value, updated_at 
                    FROM etl_state 
                    WHERE state_key IN ('last_run', 'last_success')
                    ORDER BY updated_at DESC
                """)
                etl_state = [dict(row) for row in cur.fetchall()]
            health["checks"]["etl"] = {"status": "healthy", "message": "ETL state available", "details": etl_state}
        except Exception as e:
            health["checks"]["etl"] = {"status": "unknown", "message": str(e)}
        
        return health