"""Tests for user management backend."""
from __future__ import annotations

import pytest
import uuid
from app.repositories import UserRepository
from werkzeug.security import check_password_hash


def _unique_base():
    return f"testuser_{uuid.uuid4().hex[:8]}"


def test_list_all(app):
    """list_all should return a list of users."""
    with app.app_context():
        users = UserRepository.list_all()
        assert isinstance(users, list)
        # At least the admin user from seed should exist
        assert any(u["username"] == "admin" for u in users)


def test_create_user(app):
    """Create a new user and verify it appears in list."""
    with app.app_context():
        base = _unique_base()
        username = f"{base}_create"
        email = f"{base}_create@example.com"
        password = "SecurePass123"
        role = "viewer"
        user_id = UserRepository.create(username, email, password, role)
        assert isinstance(user_id, int)
        # Verify user exists
        user = UserRepository.find_by_id(user_id)
        assert user is not None
        assert user["username"] == username
        assert user["email"] == email
        assert user["role"] == role
        # Clean up: set inactive
        UserRepository.set_active(user_id, False)


def test_set_active(app):
    """set_active should toggle user active status."""
    with app.app_context():
        base = _unique_base()
        username = f"{base}_active"
        email = f"{base}_active@example.com"
        password = "Pass123"
        role = "viewer"
        user_id = UserRepository.create(username, email, password, role)
        # Initially active (default)
        user = UserRepository.find_by_id(user_id)
        assert user["is_active"] is True
        # Disable
        UserRepository.set_active(user_id, False)
        user = UserRepository.find_by_id(user_id)
        assert user["is_active"] is False
        # Re-enable
        UserRepository.set_active(user_id, True)
        user = UserRepository.find_by_id(user_id)
        assert user["is_active"] is True
        # Clean up
        UserRepository.set_active(user_id, False)


def test_change_role(app):
    """change_role should update user's role."""
    with app.app_context():
        base = _unique_base()
        username = f"{base}_role"
        email = f"{base}_role@example.com"
        password = "Pass123"
        role = "viewer"
        user_id = UserRepository.create(username, email, password, role)
        user = UserRepository.find_by_id(user_id)
        assert user["role"] == "viewer"
        # Change to manager
        UserRepository.change_role(user_id, "manager")
        user = UserRepository.find_by_id(user_id)
        assert user["role"] == "manager"
        # Change to admin
        UserRepository.change_role(user_id, "admin")
        user = UserRepository.find_by_id(user_id)
        assert user["role"] == "admin"
        # Change back
        UserRepository.change_role(user_id, "viewer")
        user = UserRepository.find_by_id(user_id)
        assert user["role"] == "viewer"
        # Clean up
        UserRepository.set_active(user_id, False)


def test_set_password(app):
    """set_password should update password and verify_password should work."""
    with app.app_context():
        base = _unique_base()
        username = f"{base}_pass"
        email = f"{base}_pass@example.com"
        password = "OldPass123"
        role = "viewer"
        user_id = UserRepository.create(username, email, password, role)
        # Verify old password works
        user = UserRepository.find_by_id(user_id)
        assert check_password_hash(user["password_hash"], password)
        # Change password
        new_password = "NewPass456"
        UserRepository.set_password(user_id, new_password)
        user = UserRepository.find_by_id(user_id)
        assert check_password_hash(user["password_hash"], new_password)
        # Old password should no longer work
        assert not check_password_hash(user["password_hash"], password)
        # Clean up
        UserRepository.set_active(user_id, False)


def test_create_duplicate_username(app):
    """Creating a duplicate username should raise an exception."""
    with app.app_context():
        base = _unique_base()
        username = f"{base}_dup"
        email1 = f"{base}_dup1@example.com"
        email2 = f"{base}_dup2@example.com"
        password = "Pass123"
        role = "viewer"
        # First creation
        uid1 = UserRepository.create(username, email1, password, role)
        assert isinstance(uid1, int)
        # Second creation with same username should fail (unique constraint)
        with pytest.raises(Exception):
            UserRepository.create(username, email2, password, role)
        # Clean up first user
        UserRepository.set_active(uid1, False)