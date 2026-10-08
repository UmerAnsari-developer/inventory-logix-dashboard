"""Report/task submission workflow: employee → reporting manager.

Security model:
- reporting_manager_id is AUTO-populated from the user's organizational
  relationship — never accepted from the request (spec §12, §16).
- IDOR: every read/status change verifies ownership (submitter OR the
  reporting manager) server-side — never trust IDs from the browser.
- Reporting relationship grants VISIBILITY, never permissions (spec §2).
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from ..repositories.user_repo import UserRepository
from ..database import get_cursor

LOGGER = logging.getLogger(__name__)

REPORT_STATUSES = ("draft", "submitted", "under_review", "approved", "rejected", "completed")
PRIORITIES = ("low", "medium", "high", "critical")
REPORT_TYPES = ("general", "procurement", "warehouse", "analytics", "forecast", "incident")


class ReportError(Exception):
    pass


class ReportService:

    # ── Submit ───────────────────────────────────────────────────

    @staticmethod
    def submit_report(payload: dict, user) -> dict:
        """Submit a report/task to the user's reporting manager.

        The reporting manager is resolved from the user's organizational
        relationship — the request CANNOT override it.
        """
        title = (payload.get("title") or "").strip()
        if not title:
            raise ReportError("Report title is required.")
        if len(title) > 200:
            raise ReportError("Report title must be at most 200 characters.")

        report_type = (payload.get("report_type") or "general").strip().lower()
        if report_type not in REPORT_TYPES:
            raise ReportError(f"Invalid report type. Must be one of: {', '.join(REPORT_TYPES)}")

        priority = (payload.get("priority") or "medium").strip().lower()
        if priority not in PRIORITIES:
            raise ReportError(f"Invalid priority. Must be one of: {', '.join(PRIORITIES)}")

        description = (payload.get("description") or "").strip() or None
        related_module = (payload.get("related_module") or "").strip() or None
        due_date = payload.get("due_date") or None
        status = (payload.get("status") or "submitted").strip().lower()
        if status not in ("draft", "submitted"):
            raise ReportError("Initial status must be 'draft' or 'submitted'.")

        manager = UserRepository.get_reporting_manager(user.id)
        if manager is None:
            raise ReportError(
                "No reporting manager assigned. Ask an administrator to set your "
                "reporting manager before submitting reports."
            )

        report_id = ReportService._insert(
            title=title, report_type=report_type, description=description,
            priority=priority, related_module=related_module, due_date=due_date,
            status=status, submitted_by=user.id,
            reporting_manager_id=manager["id"],
        )

        # Email notification (best-effort — never blocks the submission)
        if status == "submitted":
            try:
                from .mailer import Mailer
                Mailer.send_report_notification(
                    to_email=manager["email"],
                    manager_name=manager.get("full_name") or manager["username"],
                    employee_name=user.get("full_name") or user.username,
                    employee_role=user.get("job_role") or user.role,
                    report_title=title,
                    priority=priority,
                    report_id=report_id,
                    description=description,
                )
            except Exception:
                LOGGER.warning("Report notification email failed", exc_info=True)

        return {
            "id": report_id,
            "title": title,
            "status": status,
            "reporting_manager": manager.get("full_name") or manager["username"],
        }

    @staticmethod
    def _insert(*, title, report_type, description, priority, related_module,
                due_date, status, submitted_by, reporting_manager_id) -> int:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """INSERT INTO reports
                   (title, report_type, description, priority, related_module,
                    due_date, status, submitted_by, reporting_manager_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id""",
                (title, report_type, description, priority, related_module,
                 due_date, status, submitted_by, reporting_manager_id),
            )
            return cur.fetchone()["id"]

    # ── Read (IDOR-safe) ─────────────────────────────────────────

    @staticmethod
    def get_report(report_id: int, user) -> dict | None:
        """Fetch a report — only the submitter or the reporting manager may view it."""
        with get_cursor() as cur:
            cur.execute(
                """SELECT r.*, u.username AS submitter_username,
                          u.full_name AS submitter_name, u.job_role AS submitter_job_role,
                          m.username AS manager_username, m.full_name AS manager_name
                   FROM reports r
                   JOIN users u ON u.id = r.submitted_by
                   JOIN users m ON m.id = r.reporting_manager_id
                   WHERE r.id = %s""",
                (report_id,),
            )
            report = cur.fetchone()
        if report is None:
            return None
        is_submitter = report["submitted_by"] == user.id
        is_manager = report["reporting_manager_id"] == user.id
        is_admin = user.get("role") == "admin"
        if not (is_submitter or is_manager or is_admin):
            return None  # IDOR: non-owner sees 404 (not 403 — don't leak existence)
        return report

    @staticmethod
    def my_submissions(user, *, limit: int = 50) -> list[dict]:
        """Reports the user submitted (own only)."""
        with get_cursor() as cur:
            cur.execute(
                """SELECT r.*, m.username AS manager_username,
                          m.full_name AS manager_name
                   FROM reports r
                   JOIN users m ON m.id = r.reporting_manager_id
                   WHERE r.submitted_by = %s
                   ORDER BY r.submitted_at DESC LIMIT %s""",
                (user.id, limit),
            )
            return list(cur.fetchall())

    # ── Manager inbox (IDOR-safe by construction) ────────────────

    @staticmethod
    def list_team_reports(manager_id: int, *, status: str | None = None,
                          priority: str | None = None,
                          submitted_by: int | None = None,
                          limit: int = 100) -> list[dict]:
        """Reports submitted TO the given manager (their team's submissions)."""
        where = ["r.reporting_manager_id = %s"]
        params: list = [manager_id]
        if status:
            where.append("r.status = %s"); params.append(status)
        if priority:
            where.append("r.priority = %s"); params.append(priority)
        if submitted_by:
            where.append("r.submitted_by = %s"); params.append(submitted_by)
        w = "WHERE " + " AND ".join(where)
        with get_cursor() as cur:
            cur.execute(
                f"""SELECT r.*, u.username AS submitter_username,
                           u.full_name AS submitter_name,
                           u.job_role AS submitter_job_role
                    FROM reports r
                    JOIN users u ON u.id = r.submitted_by
                    {w}
                    ORDER BY r.submitted_at DESC LIMIT %s""",
                params + [limit],
            )
            return list(cur.fetchall())

    @staticmethod
    def team_summary(manager_id: int) -> dict:
        """Counts for the manager's My Team dashboard."""
        with get_cursor() as cur:
            cur.execute(
                """SELECT status, COUNT(*) AS c FROM reports
                   WHERE reporting_manager_id = %s GROUP BY status""",
                (manager_id,),
            )
            by_status = {r["status"]: r["c"] for r in cur.fetchall()}
        pending = by_status.get("submitted", 0) + by_status.get("under_review", 0)
        return {
            "pending": pending,
            "submitted": by_status.get("submitted", 0),
            "under_review": by_status.get("under_review", 0),
            "approved": by_status.get("approved", 0),
            "rejected": by_status.get("rejected", 0),
            "completed": by_status.get("completed", 0),
        }

    # ── Status change (manager-only, ownership-checked) ──────────

    @staticmethod
    def update_report_status(report_id: int, status: str, user) -> dict:
        """Change a report's status — only the reporting manager (or admin)."""
        if status not in REPORT_STATUSES:
            raise ReportError(f"Invalid status. Must be one of: {', '.join(REPORT_STATUSES)}")

        report = ReportService.get_report(report_id, user)
        if report is None:
            raise ReportError("Report not found.")
        # Only the reporting manager (or admin) may review — the submitter cannot
        if report["reporting_manager_id"] != user.id and user.get("role") != "admin":
            raise ReportError("Only the reporting manager can review this report.")

        with get_cursor(commit=True) as cur:
            cur.execute(
                """UPDATE reports SET status = %s, reviewed_at = NOW()
                   WHERE id = %s RETURNING id""",
                (status, report_id),
            )
        return {"id": report_id, "status": status}

    @staticmethod
    def review_report(report_id: int, status: str, user, comment: str | None = None) -> dict:
        """Review a report with an optional comment (manager-only)."""
        if status not in REPORT_STATUSES:
            raise ReportError(f"Invalid status. Must be one of: {', '.join(REPORT_STATUSES)}")

        report = ReportService.get_report(report_id, user)
        if report is None:
            raise ReportError("Report not found.")
        if report["reporting_manager_id"] != user.id and user.get("role") != "admin":
            raise ReportError("Only the reporting manager can review this report.")

        with get_cursor(commit=True) as cur:
            cur.execute(
                """UPDATE reports SET status = %s, reviewed_at = NOW(),
                   review_comment = %s
                   WHERE id = %s RETURNING id""",
                (status, comment, report_id),
            )
        return {"id": report_id, "status": status, "comment": comment}