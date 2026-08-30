"""User repository: persistence via stored procedures."""
from __future__ import annotations

from werkzeug.security import check_password_hash, generate_password_hash

from ..database import get_cursor
from ..models import UserProxy


class UserRepository:
    """All SQL via stored procedures."""

    @staticmethod
    def create(username: str, email: str, password: str, role: str = "viewer") -> int:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "SELECT sp_user_create(%s, %s, %s, %s)",
                (username, email, generate_password_hash(password), role),
            )
            return cur.fetchone()["sp_user_create"]

    @staticmethod
    def find_by_username(username: str) -> UserProxy | None:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_user_find_by_username(%s)", (username,))
            row = cur.fetchone()
        return UserProxy(row) if row else None

    @staticmethod
    def find_by_email(email: str) -> UserProxy | None:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_user_find_by_email(%s)", (email,))
            row = cur.fetchone()
        return UserProxy(row) if row else None

    @staticmethod
    def find_by_id(user_id: int) -> UserProxy | None:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_user_find_by_id(%s)", (user_id,))
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
            cur.execute("SELECT sp_user_record_login(%s)", (user_id,))

    @staticmethod
    def list_all() -> list[dict]:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_user_list_all()")
            return list(cur.fetchall())

    @staticmethod
    def set_active(user_id: int, active: bool) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_user_set_active(%s, %s)", (user_id, active))

    @staticmethod
    def change_role(user_id: int, role: str) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_user_change_role(%s, %s)", (user_id, role))

    @staticmethod
    def set_password(user_id: int, password: str) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "SELECT sp_user_set_password(%s, %s)",
                (user_id, generate_password_hash(password)),
            )

    @staticmethod
    def create_reset_token(user_id: int, token_hash: str, expires_at) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "SELECT sp_reset_token_create(%s, %s, %s)",
                (user_id, token_hash, expires_at),
            )

    @staticmethod
    def find_valid_reset_token(token_hash: str) -> dict | None:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_reset_token_find(%s)", (token_hash,))
            return cur.fetchone()

    @staticmethod
    def consume_reset_token(token_id: int) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_reset_token_consume(%s)", (token_id,))

    @staticmethod
    def purge_reset_tokens(user_id: int) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_reset_token_purge(%s)", (user_id,))

    @staticmethod
    def create_session(user_id: int, ip_address: str | None, user_agent: str | None) -> str:
        import secrets
        token = secrets.token_urlsafe(32)
        with get_cursor(commit=True) as cur:
            cur.execute(
                "SELECT sp_session_create(%s, %s, %s, %s)",
                (user_id, token, ip_address, user_agent),
            )
        return token

    @staticmethod
    def end_session(token: str) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_session_end(%s)", (token,))

    @staticmethod
    def update_session_activity(token: str) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_session_update_activity(%s)", (token,))

    @staticmethod
    def get_active_sessions(user_id: int | None = None) -> list[dict]:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_session_get_active(%s)", (user_id,))
            return list(cur.fetchall())

    @staticmethod
    def cleanup_stale_sessions(hours: int = 24) -> int:
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_session_cleanup_stale(%s)", (hours,))
            return cur.fetchone()["sp_session_cleanup_stale"]
