"""Reporting workflow routes: My Team, Submit Report, report detail/review.

Security:
- /team requires the reports.review permission (managers/directors)
- /reports/submit — any authenticated user (manager auto-populated server-side)
- /reports/<id> — submitter or reporting manager only (IDOR-safe)
- Status changes — reporting manager only (ownership-checked in service)
"""
from __future__ import annotations

import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import limiter
from ..repositories.user_repo import UserRepository
from ..security import permission_required
from ..security.audit import audit_admin_action
from ..services.report_service import ReportError, ReportService

LOGGER = logging.getLogger(__name__)

reports_workflow_bp = Blueprint("reports_workflow", __name__)


@reports_workflow_bp.route("/team")
@login_required
@permission_required("reports.review")
def my_team():
    """Manager-facing: My Team (direct reports) + Team Reports inbox."""
    reports = ReportService.list_team_reports(current_user.id, limit=100)
    summary = ReportService.team_summary(current_user.id)
    direct_reports = UserRepository.direct_reports(current_user.id)
    status_filter = request.args.get("status") or ""
    priority_filter = request.args.get("priority") or ""
    if status_filter:
        reports = [r for r in reports if r["status"] == status_filter]
    if priority_filter:
        reports = [r for r in reports if r["priority"] == priority_filter]
    return render_template(
        "reports_workflow/team.html",
        reports=reports,
        summary=summary,
        direct_reports=direct_reports,
        status_filter=status_filter,
        priority_filter=priority_filter,
        active_page="my_team",
    )


@reports_workflow_bp.route("/reports/submit", methods=["GET", "POST"])
@login_required
@limiter.limit("20 per minute")
def submit_report():
    """Submit a report/task to the user's reporting manager."""
    manager = UserRepository.get_reporting_manager(current_user.id)

    if request.method == "GET":
        my_reports = ReportService.my_submissions(current_user, limit=20)
        return render_template(
            "reports_workflow/submit.html",
            manager=manager,
            my_reports=my_reports,
            active_page="submit_report",
        )

    payload = {
        "title": request.form.get("title", ""),
        "report_type": request.form.get("report_type", "general"),
        "description": request.form.get("description", ""),
        "priority": request.form.get("priority", "medium"),
        "related_module": request.form.get("related_module", ""),
        "due_date": request.form.get("due_date") or None,
        "status": "submitted",
    }
    try:
        result = ReportService.submit_report(payload, current_user)
    except ReportError as exc:
        flash(str(exc), "error")
        return redirect(url_for("reports_workflow.submit_report"))
    except Exception:
        LOGGER.exception("Report submission failed")
        flash("Report submission failed. Please try again.", "error")
        return redirect(url_for("reports_workflow.submit_report"))

    flash(
        f"Report submitted to {result['reporting_manager']}.",
        "success",
    )
    return redirect(url_for("reports_workflow.submit_report"))


@reports_workflow_bp.route("/reports/<int:report_id>")
@login_required
def report_detail(report_id: int):
    """Report detail — submitter or reporting manager only (IDOR-safe)."""
    report = ReportService.get_report(report_id, current_user)
    if report is None:
        return render_template("errors/404.html"), 404
    is_manager = report["reporting_manager_id"] == current_user.id
    return render_template(
        "reports_workflow/detail.html",
        report=report,
        is_manager=is_manager,
        active_page="my_team" if is_manager else "submit_report",
    )


@reports_workflow_bp.route("/reports/<int:report_id>/status", methods=["POST"])
@login_required
@limiter.limit("30 per minute")
def update_report_status(report_id: int):
    """Change report status — reporting manager only (ownership-checked)."""
    status = request.form.get("status", "")
    comment = request.form.get("comment") or None
    try:
        result = ReportService.review_report(report_id, status, current_user, comment)
    except ReportError as exc:
        flash(str(exc), "error")
    except Exception:
        LOGGER.exception("Report status update failed")
        flash("Failed to update report status.", "error")
    else:
        flash(f"Report marked {result['status'].replace('_', ' ')}.", "success")
    return redirect(url_for("reports_workflow.report_detail", report_id=report_id))