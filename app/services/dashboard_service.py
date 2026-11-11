"""Dashboard service — single proc call for admin dashboard KPIs."""
from __future__ import annotations

from ..database import get_cursor


class DashboardService:
    @staticmethod
    def get_dashboard_data() -> dict:
        """Get dashboard KPIs via sp_dashboard_snapshot (replaces 11 queries)."""
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_dashboard_snapshot()")
            return {row["metric"]: row["value"] for row in cur.fetchall()}