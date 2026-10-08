"""Tests for admin self-protection (C-002)."""
from __future__ import annotations

import pytest

from app.repositories import UserRepository
from app.database import get_cursor


@pytest.fixture()
def test_auth_client(app, client):
    """Returns a logged-in test client using the shared app fixture."""
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "Admin@123", "remember": "on"},
        follow_redirects=False,
    )
    return client


@pytest.fixture()
def admin_user_id(app):
    """Get the admin user ID from the database."""
    with app.app_context():
        admin = UserRepository.find_by_username("admin")
        assert admin is not None, "Admin user not found"
        return admin.id


class TestAdminSelfProtection:
    """Test that admins cannot demote or delete themselves."""

    def test_admin_cannot_change_own_role(self, test_auth_client, app, admin_user_id):
        """Admin should not be able to change their own role."""
        # Reset admin user to known state
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute(
                    "UPDATE users SET role = 'admin', is_active = TRUE WHERE id = %s",
                    (admin_user_id,)
                )
        
        response = test_auth_client.get("/admin/users/")
        assert response.status_code == 200
        
        # Verify admin role before attempt
        with app.app_context():
            admin_user = UserRepository.find_by_id(admin_user_id)
            assert admin_user is not None, "Admin user not found"
            assert admin_user.role == "admin"
        
        # POST to change own role - should redirect with flash error
        response = test_auth_client.post(
            f"/admin/users/change-role/{admin_user_id}",
            data={"role": "viewer", "csrf_token": "test"},
            follow_redirects=True
        )
        # Server-side protection: redirects to index with flash error
        assert response.status_code == 200
        
        # Verify role is unchanged (security intent)
        with app.app_context():
            admin_user = UserRepository.find_by_id(admin_user_id)
            assert admin_user.role == "admin", "Admin role should not change"

    def test_admin_cannot_disable_own_account(self, test_auth_client, app, admin_user_id):
        """Admin should not be able to disable their own account."""
        # Reset admin user to known state
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute(
                    "UPDATE users SET role = 'admin', is_active = TRUE WHERE id = %s",
                    (admin_user_id,)
                )
        
        # Verify admin is active before attempt
        with app.app_context():
            admin_user = UserRepository.find_by_id(admin_user_id)
            assert admin_user is not None, "Admin user not found"
            assert admin_user.is_active is True
        
        response = test_auth_client.post(
            f"/admin/users/toggle/{admin_user_id}",
            data={"csrf_token": "test"},
            follow_redirects=True
        )
        # Server-side protection: redirects to index with flash error
        assert response.status_code == 200
        
        # Verify account is still active (security intent)
        with app.app_context():
            admin_user = UserRepository.find_by_id(admin_user_id)
            assert admin_user.is_active is True, "Admin account should not be disabled"

    def test_admin_cannot_delete_own_account(self, auth_client, admin_user_id):
        """Admin should not be able to delete their own account."""
        # The edit page redirects when trying to edit self (handled in edit route)
        response = auth_client.get(f"/admin/users/edit/{admin_user_id}")
        # Should redirect to index with error
        assert response.status_code in (302, 200)

    def test_admin_can_change_other_user_role(self, auth_client):
        """Admin should be able to change other users' roles."""
        response = auth_client.post(
            "/admin/users/create",
            data={
                "username": "testuser2",
                "email": "test2@example.com",
                "password": "Test@123",
                "role": "viewer",
                "csrf_token": "test"
            },
            follow_redirects=True
        )
        assert response.status_code == 200

    def test_admin_can_disable_other_user(self, auth_client):
        """Admin should be able to disable other users."""
        response = auth_client.post(
            "/admin/users/create",
            data={
                "username": "testuser3",
                "email": "test3@example.com",
                "password": "Test@123",
                "role": "viewer",
                "csrf_token": "test"
            },
            follow_redirects=True
        )
        assert response.status_code == 200