"""Tests for PostgreSQL-backed rate limiting."""
from __future__ import annotations

import pytest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from app.services.auth_service import AuthService
from app.repositories import UserRepository
from app.database import get_cursor


def _unique_username(base: str) -> str:
    """Generate a unique username for test isolation."""
    return f"{base}_{uuid.uuid4().hex[:8]}"


def _utcnow() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(timezone.utc)


class TestPGRateLimiting:
    """Test PostgreSQL-backed rate limiting for authentication."""

    @pytest.fixture(autouse=True)
    def setup_db(self, app):
        """Set up test database with rate_limit_state table."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                # Drop and recreate table with TIMESTAMPTZ columns
                cur.execute("DROP TABLE IF EXISTS rate_limit_state CASCADE")
                cur.execute("""
                    CREATE TABLE rate_limit_state (
                        id SERIAL PRIMARY KEY,
                        key VARCHAR(255) NOT NULL UNIQUE,
                        count INTEGER NOT NULL DEFAULT 0,
                        window_start TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        expires_at TIMESTAMPTZ NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                # Create index for cleanup
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_rate_limit_expires 
                    ON rate_limit_state(expires_at)
                """)
                # Clean up any existing data before test
                cur.execute("DELETE FROM rate_limit_state")
            yield
            # Cleanup
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM rate_limit_state")

    def test_rate_limit_state_table_exists(self, app):
        """Test that rate_limit_state table exists."""
        with app.app_context():
            with get_cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables 
                        WHERE table_name = 'rate_limit_state'
                    )
                """)
                assert cur.fetchone()["exists"] is True

    def test_failed_login_increments_pg_counter(self, app):
        """Test that failed login increments PostgreSQL counter."""
        with app.app_context():
            # Create test user with unique username
            username = _unique_username("testuser_rate")
            user_id = UserRepository.create(
                username=username,
                email=f"{username}@example.com",
                password="TestPass123!",
                role="viewer"
            )
            
            # Attempt failed login
            from app.services.auth_service import AuthError
            with pytest.raises(AuthError):
                AuthService.authenticate(username, "wrongpassword", ip="127.0.0.1")
            
            # Check rate_limit_state table
            with get_cursor() as cur:
                cur.execute("""
                    SELECT count FROM rate_limit_state 
                    WHERE key = %s
                """, (f"login:{username}",))
                row = cur.fetchone()
                assert row is not None
                assert row["count"] == 1

    def test_lockout_after_max_attempts(self, app):
        """Test account lockout after MAX_FAILED_ATTEMPTS."""
        with app.app_context():
            username = _unique_username("testuser_lockout")
            user_id = UserRepository.create(
                username=username,
                email=f"{username}@example.com",
                password="TestPass123!",
                role="viewer"
            )
            
            from app.services.auth_service import AuthError, MAX_FAILED_ATTEMPTS
            
            # Make MAX_FAILED_ATTEMPTS failed attempts
            for i in range(MAX_FAILED_ATTEMPTS):
                with pytest.raises(AuthError):
                    AuthService.authenticate(username, "wrongpassword", ip="127.0.0.1")
            
            # Next attempt should be locked out
            with pytest.raises(AuthError) as exc_info:
                AuthService.authenticate(username, "wrongpassword", ip="127.0.0.1")
            
            assert "locked" in str(exc_info.value).lower()

    def test_successful_login_clears_failed_attempts(self, app):
        """Test that successful login clears failed attempts."""
        with app.app_context():
            username = _unique_username("testuser_success")
            user_id = UserRepository.create(
                username=username,
                email=f"{username}@example.com",
                password="TestPass123!",
                role="viewer"
            )
            
            from app.services.auth_service import AuthError
            
            # Make some failed attempts
            for _ in range(3):
                with pytest.raises(AuthError):
                    AuthService.authenticate(username, "wrongpassword", ip="127.0.0.1")
            
            # Successful login
            user = AuthService.authenticate(username, "TestPass123!", ip="127.0.0.1")
            assert user is not None
            
            # Check counter is cleared
            with get_cursor() as cur:
                cur.execute("""
                    SELECT count FROM rate_limit_state 
                    WHERE key = %s
                """, (f"login:{username}",))
                row = cur.fetchone()
                assert row is None or row["count"] == 0

    def test_rate_limit_window_expiry(self, app):
        """Test that rate limit window expires correctly."""
        with app.app_context():
            username = _unique_username("testuser_expiry")
            user_id = UserRepository.create(
                username=username,
                email=f"{username}@example.com",
                password="TestPass123!",
                role="viewer"
            )
            
            from app.services.auth_service import AuthError
            
            # Make failed attempt
            with pytest.raises(AuthError):
                AuthService.authenticate(username, "wrongpassword", ip="127.0.0.1")
            
            # Manually expire the window using UTC time
            with get_cursor(commit=True) as cur:
                cur.execute("""
                    UPDATE rate_limit_state 
                    SET window_start = NOW() AT TIME ZONE 'UTC' - INTERVAL '20 minutes',
                        expires_at = NOW() AT TIME ZONE 'UTC' - INTERVAL '10 minutes'
                    WHERE key = %s
                """, (f"login:{username}",))
            
            # Next attempt should start fresh (not locked)
            with pytest.raises(AuthError):
                AuthService.authenticate(username, "wrongpassword", ip="127.0.0.1")
            
            # Should have count = 1 (new window)
            with get_cursor() as cur:
                cur.execute("""
                    SELECT count FROM rate_limit_state 
                    WHERE key = %s
                """, (f"login:{username}",))
                row = cur.fetchone()
                assert row["count"] == 1

    def test_concurrent_failed_logins_serialized(self, app):
        """Test that concurrent failed logins are serialized via PG advisory lock."""
        import threading
        import time
        
        with app.app_context():
            username = _unique_username("testuser_concurrent")
            user_id = UserRepository.create(
                username=username,
                email=f"{username}@example.com",
                password="TestPass123!",
                role="viewer"
            )
            
            from app.services.auth_service import AuthError
            errors = []
            
            def attempt_login():
                with app.app_context():
                    try:
                        AuthService.authenticate(username, "wrongpassword", ip="127.0.0.1")
                    except AuthError as e:
                        errors.append(str(e))
            
            # Run concurrent attempts
            threads = [threading.Thread(target=attempt_login) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            
            # All should be AuthError (not internal errors)
            assert len(errors) == 5
            assert all("Invalid username or password" in e or "locked" in e.lower() for e in errors)
            
            # Counter should be 5
            with get_cursor() as cur:
                cur.execute("""
                    SELECT count FROM rate_limit_state 
                    WHERE key = %s
                """, (f"login:{username}",))
                row = cur.fetchone()
                assert row["count"] == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])