"""Audit report generator routes with audit logging and async support."""
from __future__ import annotations

import json
from datetime import date, datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for, jsonify
from flask_login import current_user, login_required

from app.extensions import limiter
from app.security import write_roles_required
from app.security.audit import audit_admin_action
from app.services import AuditReportService
from app.repositories import ScheduledAuditReportRepository
from app.services.job_tracker import JobTracker

admin_audit_report_bp = Blueprint("admin_audit_report", __name__, url_prefix="/admin/audit_reports")


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
    job = JobTracker.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    
    # Only allow users to see their own jobs (or admins can see all)
    if job["user_id"] != current_user.id and current_user.role != "admin":
        return jsonify({"error": "Unauthorized"}), 403
    
    return jsonify(job)