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
    def find_by_ids(user_ids: list[int]) -> list[dict]:
        """Return list of dicts with id and username for the given user IDs."""
        users = []
        for uid in user_ids:
            user = UserRepository.find_by_id(uid)
            if user:
                users.append({"id": user.id, "username": user.username})
        return users

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
        """List all users (admin)."""
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_user_list_all()")
            return cur.fetchall()

    @staticmethod
    def set_active(user_id: int, active: bool) -> None:
        """Enable or disable a user account."""
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT sp_user_set_active(%s, %s)", (user_id, active))

    @staticmethod
    def change_role(user_id: int, role: str) -> None:
        """Change a user's role."""
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
    def delete_sessions_for_user(user_id: int) -> None:
        """Invalidate all active sessions for a user (ADM-016: role change / deactivation)."""
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE user_sessions SET is_active = FALSE, logout_at = NOW() "
                "WHERE user_id = %s AND is_active = TRUE",
                (user_id,),
            )

    # ── Reporting hierarchy (org relationship — grants visibility, not permissions) ──

    @staticmethod
    def set_reporting_manager(user_id: int, manager_id: int | None) -> None:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE users SET reporting_manager_id = %s WHERE id = %s",
                (manager_id, user_id),
            )

    @staticmethod
    def get_reporting_manager(user_id: int) -> dict | None:
        """The user's reporting manager (or None)."""
        with get_cursor() as cur:
            cur.execute(
                """SELECT m.id, m.username, m.full_name, m.email, m.role, m.job_role,
                          m.department, m.is_active
                   FROM users u JOIN users m ON m.id = u.reporting_manager_id
                   WHERE u.id = %s""",
                (user_id,),
            )
            return cur.fetchone()

    @staticmethod
    def direct_reports(manager_id: int) -> list[dict]:
        """Users whose reporting_manager_id is the given manager."""
        with get_cursor() as cur:
            cur.execute(
                """SELECT id, username, full_name, email, role, job_role,
                          department, is_active, last_login
                   FROM users
                   WHERE reporting_manager_id = %s AND deleted_at IS NULL
                   ORDER BY username""",
                (manager_id,),
            )
            return list(cur.fetchall())

    @staticmethod
    def list_managers() -> list[dict]:
        """Active users eligible as reporting managers (for the assignment dropdown)."""
        with get_cursor() as cur:
            cur.execute(
                """SELECT id, username, full_name, email, role, job_role, department
                   FROM users
                   WHERE is_active = TRUE AND deleted_at IS NULL
                   ORDER BY username""",
            )
            return list(cur.fetchall())

    @staticmethod
    def manager_chain(user_id: int, max_depth: int = 50) -> list[int]:
        """Walk up the reporting_manager_id chain (for cycle detection)."""
        chain: list[int] = []
        current: int | None = user_id
        with get_cursor() as cur:
            for _ in range(max_depth):
                if current is None:
                    break
                cur.execute(
                    "SELECT reporting_manager_id FROM users WHERE id = %s", (current,)
                )
                row = cur.fetchone()
                if not row or row["reporting_manager_id"] is None:
                    break
                nxt = int(row["reporting_manager_id"])
                if nxt in chain:
                    break  # existing cycle — stop walking
                chain.append(nxt)
                current = nxt
        return chain

    @staticmethod
    def update_profile(user_id: int, *, full_name: str | None = None,
                       department: str | None = None,
                       job_role: str | None = None) -> None:
        """Update organizational profile fields (admin)."""
        sets, params = [], []
        if full_name is not None:
            sets.append("full_name = %s"); params.append(full_name)
        if department is not None:
            sets.append("department = %s"); params.append(department)
        if job_role is not None:
            sets.append("job_role = %s"); params.append(job_role)
        if not sets:
            return
        params.append(user_id)
        with get_cursor(commit=True) as cur:
            cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = %s", params)