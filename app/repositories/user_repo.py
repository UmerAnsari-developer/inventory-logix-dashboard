"""User repository: persistence for the ``users`` table."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

from ..database import get_cursor
from ..models import UserProxy


class UserRepository:
    """Encapsulates all SQL touching the ``users`` table."""

    @staticmethod
    def create(username: str, email: str, password: str, role: str = "viewer") -> int:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO users (username, email, password_hash, role)
                VALUES (%s, %s, %s, %s) RETURNING id
                """,
                (username.lower(), email.lower(), generate_password_hash(password), role),
            )
            return cur.fetchone()["id"]

    @staticmethod
    def find_by_username(username: str) -> UserProxy | None:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM users WHERE username = %s", (username.lower(),))
            row = cur.fetchone()
        return UserProxy(row) if row else None

    @staticmethod
    def find_by_email(email: str) -> UserProxy | None:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM users WHERE email = %s", (email.lower(),))
            row = cur.fetchone()
        return UserProxy(row) if row else None

    @staticmethod
    def find_by_id(user_id: int) -> UserProxy | None:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
        return UserProxy(row) if row else None

    @staticmethod
    def verify_password(plain: str, stored_hash: str) -> bool:
        try:
            return check_password_hash(stored_hash, plain)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def record_login(user_id: int) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE users SET last_login = %s WHERE id = %s",
                (datetime.utcnow(), user_id),
            )

    @staticmethod
    def list_all() -> list[dict]:
        with get_cursor() as cur:
            cur.execute(
                "SELECT id, username, email, role, is_active, last_login, created_at "
                "FROM users ORDER BY created_at DESC"
            )
            return list(cur.fetchall())

    @staticmethod
    def set_active(user_id: int, active: bool) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE users SET is_active = %s WHERE id = %s", (bool(active), user_id)
            )

    @staticmethod
    def change_role(user_id: int, role: str) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE users SET role = %s WHERE id = %s", (role, user_id)
            )

    @staticmethod
    def set_password(user_id: int, password: str) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (generate_password_hash(password), user_id),
            )

    @staticmethod
    def create_reset_token(user_id: int, token_hash: str, expires_at: datetime) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
                VALUES (%s, %s, %s)
                """,
                (user_id, token_hash, expires_at),
            )

    @staticmethod
    def find_valid_reset_token(token_hash: str) -> dict | None:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, token_hash, expires_at, used
                FROM password_reset_tokens
                WHERE token_hash = %s
                """,
                (token_hash,),
            )
            return cur.fetchone()

    @staticmethod
    def consume_reset_token(token_id: int) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE password_reset_tokens SET used = TRUE WHERE id = %s",
                (token_id,),
            )

    @staticmethod
    def purge_reset_tokens(user_id: int) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "DELETE FROM password_reset_tokens WHERE user_id = %s", (user_id,)
            )
