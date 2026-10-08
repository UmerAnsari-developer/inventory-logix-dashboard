"""Tests for admin health endpoint (M-009)."""
from __future__ import annotations

import pytest


class TestAdminHealthEndpoint:
    """Test that admin health endpoint exists and works."""

    def test_admin_health_endpoint_exists(self, auth_client):
        """Admin health endpoint should exist at /admin/dashboard/health."""
        response = auth_client.get("/admin/dashboard/health")
        assert response.status_code == 200

    def test_admin_health_returns_json(self, auth_client):
        """Admin health endpoint should return JSON."""
        response = auth_client.get("/admin/dashboard/health")
        assert response.status_code == 200
        assert response.is_json

    def test_admin_health_includes_database_check(self, auth_client):
        """Admin health should include database connectivity check."""
        response = auth_client.get("/admin/dashboard/health")
        data = response.get_json()
        
        assert "checks" in data
        assert "database" in data["checks"]
        assert data["checks"]["database"]["status"] in ("healthy", "unhealthy", "ok", "error", "degraded", "warning", "critical")

    def test_admin_health_includes_redis_check(self, auth_client):
        """Admin health should include Redis/cache check."""
        response = auth_client.get("/admin/dashboard/health")
        data = response.get_json()
        
        assert "checks" in data
        assert "cache" in data["checks"]

    def test_admin_health_includes_disk_space(self, auth_client):
        """Admin health should include disk space check."""
        response = auth_client.get("/admin/dashboard/health")
        data = response.get_json()
        
        assert "checks" in data
        assert "disk" in data["checks"]

    def test_admin_health_includes_memory_check(self, auth_client):
        """Admin health should include memory check."""
        response = auth_client.get("/admin/dashboard/health")
        data = response.get_json()
        
        assert "checks" in data
        assert "memory" in data["checks"]

    def test_admin_health_includes_etl_status(self, auth_client):
        """Admin health should include ETL pipeline status."""
        response = auth_client.get("/admin/dashboard/health")
        data = response.get_json()
        
        assert "checks" in data
        assert "etl" in data["checks"]

    def test_admin_health_requires_admin_role(self, client):
        """Admin health endpoint should require admin role."""
        # Login as non-admin (viewer)
        client.post(
            "/auth/login",
            data={"username": "viewer", "password": "Viewer@123"},
            follow_redirects=True
        )
        
        response = client.get("/admin/dashboard/health")
        # Should be forbidden for non-admin
        assert response.status_code in (403, 302)

    def test_admin_health_service_exists(self):
        """AdminDashboardService should have health check method."""
        from app.services.admin_dashboard_service import AdminDashboardService
        
        assert hasattr(AdminDashboardService, 'get_health_status')
        assert callable(AdminDashboardService.get_health_status)

    def test_admin_health_service_returns_structured_data(self):
        """AdminDashboardService.get_health_status should return structured data."""
        from app.services.admin_dashboard_service import AdminDashboardService
        from flask import Flask
        
        # Create a minimal app context for the test
        app = Flask(__name__)
        app.config['TESTING'] = True
        
        with app.app_context():
            health = AdminDashboardService.get_health_status()
            assert isinstance(health, dict)
            assert "status" in health
            assert "checks" in health
            assert "database" in health["checks"]
            assert "cache" in health["checks"]
            assert "disk" in health["checks"]
            assert "memory" in health["checks"]
            assert "etl" in health["checks"]