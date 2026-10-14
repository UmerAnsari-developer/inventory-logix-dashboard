"""Audit report generator routes with audit logging and async support."""
from __future__ import annotations

import json
from datetime import date, datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for, jsonify
from flask_login import current_user, login_required

from app.extensions import limiter
from app.database import get_cursor
from app.security import write_roles_required
from app.security.audit import audit_admin_action
from app.services import AuditReportService
from app.repositories import ScheduledAuditReportRepository
from app.services.job_queue_service import Job
from app.services.job_tracker import JobTracker

admin_audit_report_bp = Blueprint("admin_audit_report", __name__, url_prefix="/admin/audit_reports")

# GAP-012 Batch 5: job_queue → JobTracker-dict adapter (see _queue_job_to_tracker_dict).
_STATUS_MAP = {"pending": "pending", "running": "running", "completed": "completed", "dead": "failed"}
_PROGRESS_MAP = {"pending": 0, "running": 50, "completed": 100, "dead": 100}


def _load_queue_job(job_id: int) -> Job | None:
    """Load a full job_queue row locally.

    JobQueueService.get_status() calls the job_queue_get_status proc, which
    OMITS ``payload`` — and the 403 ownership check needs ``payload.user_id``.
    """
    with get_cursor() as cur:
        cur.execute("SELECT * FROM job_queue WHERE id = %s", (job_id,))
        row = cur.fetchone()
    return Job(**row) if row else None


def _queue_job_to_tracker_dict(job: Job) -> dict:
    """Reproduce the JobTracker dict contract exactly (job_tracker.py:28-44)
    so the polling UI cannot tell queue jobs from legacy thread jobs."""
    return {
        "job_id": str(job.id),
        "job_type": "audit_report",
        "user_id": (job.payload or {}).get("user_id"),
        "status": _STATUS_MAP.get(job.status, "failed"),
        "progress": _PROGRESS_MAP.get(job.status, 0),
        "current_step": {"pending": 0, "running": 1, "completed": 4, "dead": 4}.get(job.status, 0),
        "total_steps": 4,
        "message": {"pending": "Queued", "running": "Processing report",
                    "completed": "Report generated"}.get(job.status) or (job.error or "Report generation failed"),
        "result": job.result,
        "error": job.error,
        "metadata": {"report_id": (job.payload or {}).get("report_id")},
        "created_at": job.created_at,
        "updated_at": job.completed_at or job.started_at or job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
    }


@admin_audit_report_bp.route("/")
@login_required
@write_roles_required
@audit_admin_action("admin.audit_report.list", target_type="audit_report")
def index():
    """List scheduled audit reports with pagination."""
    page = request.args.get("page", default=1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    reports = ScheduledAuditReportRepository.list_all(active_only=False, limit=per_page, offset=offset)
    total_count = ScheduledAuditReportRepository.count_all(active_only=False)
    total_pages = (total_count + per_page - 1) // per_page
    
    return render_template(
        "admin/audit_report/index.html",
        reports=reports,
        active_page="audit_reports",
        report_page=page,
        total_pages=total_pages,
        total_count=total_count
    )


@admin_audit_report_bp.route("/create", methods=["GET", "POST"])
@login_required
@write_roles_required
@limiter.limit("10 per minute")
@audit_admin_action("admin.audit_report.create", target_type="audit_report", detail_func=lambda r, *a, **kw: {"name": request.form.get("name")})
def create():
    """Create a new scheduled audit report."""
    if request.method == "GET":
        return render_template(
            "admin/audit_report/create.html",
            active_page="audit_reports",
            min_date=date.today().isoformat()
        )
    
    # POST request
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    format = request.form.get("format", "CSV")
    frequency = request.form.get("frequency", "daily")
    # Parameters: we'll collect them from the form
    parameters = {
        "start_date": request.form.get("start_date", "").strip(),
        "end_date": request.form.get("end_date", "").strip(),
        "user_id": request.form.get("user_id", "").strip(),
        "action": request.form.get("action", "").strip()
    }
    # Remove empty parameters
    parameters = {k: v for k, v in parameters.items() if v}
    next_run_time = request.form.get("next_run_time", "").strip()
    
    if not name:
        flash("Report name is required.", "error")
        return redirect(url_for("admin_audit_report.create"))
    
    if not next_run_time:
        flash("Next run time is required.", "error")
        return redirect(url_for("admin_audit_report.create"))
    
    try:
        # ADM-026: fromisoformat handles the "T" separator natively (Py 3.11+);
        # the .replace("T", " ") hack is no longer needed.
        datetime.fromisoformat(next_run_time)
    except ValueError:
        flash("Invalid next run time format. Please use YYYY-MM-DD HH:MM:SS.", "error")
        return redirect(url_for("admin_audit_report.create"))
    
    report_id = ScheduledAuditReportRepository.create(
        name=name,
        description=description,
        format=format,
        frequency=frequency,
        parameters=parameters,
        next_run_time=next_run_time,
        created_by=current_user.id
    )
    
    flash(f"Scheduled audit report '{name}' created successfully.", "success")
    return redirect(url_for("admin_audit_report.index"))


@admin_audit_report_bp.route("/edit/<int:report_id>", methods=["GET", "POST"])
@login_required
@write_roles_required
@limiter.limit("10 per minute")
@audit_admin_action("admin.audit_report.update", target_type="audit_report", target_id_arg="report_id")
def edit(report_id: int):
    """Edit a scheduled audit report."""
    report = ScheduledAuditReportRepository.get_by_id(report_id)
    if not report:
        flash("Scheduled audit report not found.", "error")
        return redirect(url_for("admin_audit_report.index"))
    
    if request.method == "GET":
        # Parse parameters for the form
        parameters = json.loads(report["parameters"]) if report["parameters"] else {}
        return render_template(
            "admin/audit_report/edit.html",
            report=report,
            parameters=parameters,
            active_page="audit_reports",
            min_date=date.today().isoformat()
        )
    
    # POST request
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    format = request.form.get("format", "CSV")
    frequency = request.form.get("frequency", "daily")
    # Parameters: we'll collect them from the form
    parameters = {
        "start_date": request.form.get("start_date", "").strip(),
        "end_date": request.form.get("end_date", "").strip(),
        "user_id": request.form.get("user_id", "").strip(),
        "action": request.form.get("action", "").strip()
    }
    # Remove empty parameters
    parameters = {k: v for k, v in parameters.items() if v}
    next_run_time = request.form.get("next_run_time", "").strip()
    
    if not name:
        flash("Report name is required.", "error")
        return redirect(url_for("admin_audit_report.edit", report_id=report_id))
    
    if not next_run_time:
        flash("Next run time is required.", "error")
        return redirect(url_for("admin_audit_report.edit", report_id=report_id))
    
    try:
        # ADM-026: fromisoformat handles the "T" separator natively (Py 3.11+).
        datetime.fromisoformat(next_run_time)
    except ValueError:
        flash("Invalid next run time format. Please use YYYY-MM-DD HH:MM:SS.", "error")
        return redirect(url_for("admin_audit_report.edit", report_id=report_id))
    
    try:
        ScheduledAuditReportRepository.update(
            report_id=report_id,
            name=name,
            description=description,
            format=format,
            frequency=frequency,
            parameters=parameters,
            next_run_time=next_run_time,
            updated_by=current_user.id
        )
        flash(f"Scheduled audit report '{name}' updated successfully.", "success")
        return redirect(url_for("admin_audit_report.index"))
    except Exception as e:
        flash(f"Error updating report: {str(e)}", "error")
        return redirect(url_for("admin_audit_report.edit", report_id=report_id))


@admin_audit_report_bp.route("/delete/<int:report_id>", methods=["POST"])
@login_required
@write_roles_required
@limiter.limit("5 per minute")
@audit_admin_action("admin.audit_report.delete", target_type="audit_report", target_id_arg="report_id")
def delete(report_id: int):
    """Delete a scheduled audit report."""
    report = ScheduledAuditReportRepository.get_by_id(report_id)
    if not report:
        flash("Scheduled audit report not found.", "error")
        return redirect(url_for("admin_audit_report.index"))
    
    try:
        ScheduledAuditReportRepository.delete(report_id)
        flash(f"Scheduled audit report '{report['name']}' deleted successfully.", "success")
    except Exception as e:
        flash(f"Error deleting report: {str(e)}", "error")
    return redirect(url_for("admin_audit_report.index"))


@admin_audit_report_bp.route("/run/<int:report_id>", methods=["POST"])
@login_required
@write_roles_required
@limiter.limit("10 per minute")
@audit_admin_action("admin.audit_report.run", target_type="audit_report", target_id_arg="report_id")
def run_report(report_id: int):
    """Run a scheduled audit report on demand (async)."""
    job_id = AuditReportService.generate_report_async(
        report_id=report_id,
        generated_by=current_user.id
    )
    
    flash(f"Report generation started. Job ID: {job_id}", "success")
    return redirect(url_for("admin_audit_report.index"))


@admin_audit_report_bp.route("/run_due", methods=["POST"])
@login_required
@write_roles_required
@limiter.limit("5 per minute")
@audit_admin_action("admin.audit_report.run_due", target_type="audit_report")
def run_due_reports():
    """Run all due scheduled audit reports."""
    result = AuditReportService.run_due_reports()
    
    if result["success"]:
        flash(result["message"], "success")
    else:
        flash(f"Error running due reports: {result.get('message', 'Unknown error')}", "error")
    
    return redirect(url_for("admin_audit_report.index"))


@admin_audit_report_bp.route("/job_status/<job_id>")
@login_required
@write_roles_required
def job_status(job_id: str):
    """Get job status for progress polling."""
    # GAP-012 Batch 5: branch on numeric-parse, not on the flag — UUIDs are
    # never numeric (legacy JobTracker jobs), numeric ids are queue jobs. A
    # numeric id missing from job_queue falls through to JobTracker → 404
    # (identical to today's garbage-id behavior). This survives flag flips
    # across restarts and serves mixed legacy/queue jobs in any mode.
    job = None
    try:
        numeric_id = int(job_id)
    except (TypeError, ValueError):
        numeric_id = None
    if numeric_id is not None:
        queue_job = _load_queue_job(numeric_id)
        if queue_job is not None:
            job = _queue_job_to_tracker_dict(queue_job)
    if job is None:
        job = JobTracker.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # Only allow users to see their own jobs (or admins can see all)
    if job["user_id"] != current_user.id and current_user.role != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    return jsonify(job)


@admin_audit_report_bp.route("/verify-integrity")
@login_required
@write_roles_required
@limiter.limit("10 per minute")
def verify_audit_integrity():
    """Verify the audit-log hash chain (GAP-011 tamper evidence).

    Recomputes SHA-256 row hashes and checks linkage over the most recent
    ``limit`` rows. Empty broken counts == chain intact.
    """
    from app.database import get_cursor

    limit = min(max(request.args.get("limit", default=5000, type=int), 1), 50000)
    try:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM sp_audit_verify_integrity(%s)", (limit,))
            row = cur.fetchone()
    except Exception:
        current_app.logger.exception("Audit integrity verification failed")
        return jsonify({"success": False, "error": "Verification failed"}), 500

    intact = (row["broken_links"] or 0) == 0 and (row["bad_hashes"] or 0) == 0
    return jsonify({
        "success": True,
        "intact": intact,
        "rows_checked": row["rows_checked"],
        "broken_links": row["broken_links"],
        "bad_hashes": row["bad_hashes"],
        "first_broken_id": row["first_broken_id"],
        "limit": limit,
    })