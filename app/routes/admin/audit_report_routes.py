"""Audit report generator routes."""
from __future__ import annotations

import json
from datetime import date, datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.security import write_roles_required
from app.services import audit_report_service
from app.repositories import ScheduledAuditReportRepository

admin_audit_report_bp = Blueprint("admin_audit_report", __name__, url_prefix="/admin/audit_reports")


@admin_audit_report_bp.route("/")
@login_required
@write_roles_required
def index():
    """List scheduled audit reports."""
    reports = ScheduledAuditReportRepository.list_all(active_only=False)
    return render_template(
        "admin/audit_report/index.html",
        reports=reports,
        active_page="audit_reports"
    )


@admin_audit_report_bp.route("/create", methods=["GET", "POST"])
@login_required
@write_roles_required
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
        # Validate the next_run_time format
        datetime.fromisoformat(next_run_time.replace("T", " "))
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
        # Validate the next_run_time format
        datetime.fromisoformat(next_run_time.replace("T", " "))
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
def run_report(report_id: int):
    """Run a scheduled audit report on demand."""
    result = audit_report_service.generate_and_save_report(
        report_id=report_id,
        generated_by=current_user.id
    )
    
    if result["success"]:
        flash(result["message"], "success")
    else:
        flash(result["message"], "error")
    
    return redirect(url_for("admin_audit_report.index"))


@admin_audit_report_bp.route("/run_due", methods=["POST"])
@login_required
@write_roles_required
def run_due_reports():
    """Run all due scheduled audit reports."""
    result = audit_report_service.run_due_reports()
    
    if result["success"]:
        flash(result["message"], "success")
        # Optionally, we could show the results in a flash message or redirect to a page showing results
    else:
        flash(f"Error running due reports: {result.get('message', 'Unknown error')}", "error")
    
    return redirect(url_for("admin_audit_report.index"))