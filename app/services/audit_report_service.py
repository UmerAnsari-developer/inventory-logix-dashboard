"""Audit report generator service with async support."""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from flask import Response, current_app, has_app_context

from ..database import get_cursor
from ..repositories import (
    ScheduledAuditReportRepository,
    UserActivityRepository,
)
from ..services.job_tracker import JobTracker
from app.services.nnotification_center_service import NotificationCenterService


class AuditReportService:
    """Service for generating audit reports with async support."""

    @staticmethod
    def generate_report_data(
        start_date: date | None = None,
        end_date: date | None = None,
        user_id: int | None = None,
        action: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Generate report data from the audit log."""
        where_clauses = []
        params = []
        
        if start_date is not None:
            where_clauses.append("created_at >= %s")
            params.append(start_date)
        
        if end_date is not None:
            where_clauses.append("created_at < %s")
            params.append(end_date + timedelta(days=1))
        
        if user_id is not None:
            where_clauses.append("user_id = %s")
            params.append(user_id)
        
        if action is not None:
            where_clauses.append("action = %s")
            params.append(action)
        
        where_clause = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT id, user_id, action, target_type, target_id, detail,
                       ip_address, created_at
                FROM audit_log
                {where_clause}
                ORDER BY created_at DESC
                """,
                tuple(params),
            )
            return [dict(row) for row in cur.fetchall()]

    @staticmethod
    def generate_csv_report(data: List[Dict[str, Any]]) -> Response:
        """Generate a CSV report from the data."""
        if not data:
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["ID", "User ID", "Action", "Target Type", "Target ID", "Detail", "IP Address", "Created At"])
            buf.seek(0)
            return Response(
                buf.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=audit_report.csv"}
            )
        
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["ID", "User ID", "Action", "Target Type", "Target ID", "Detail", "IP Address", "Created At"])
        for row in data:
            writer.writerow([
                row["id"],
                row["user_id"] or "",
                row["action"] or "",
                row["target_type"] or "",
                row["target_id"] or "",
                json.dumps(row["detail"]) if row["detail"] else "",
                row["ip_address"] or "",
                row["created_at"].isoformat() if row["created_at"] else ""
            ])
        buf.seek(0)
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit_report.csv"}
        )

    @staticmethod
    def generate_pdf_report(data: List[Dict[str, Any]]) -> Response:
        """Generate a PDF report from the data (placeholder - returns CSV)."""
        response = AuditReportService.generate_csv_report(data)
        response.headers["Content-Disposition"] = "attachment; filename=audit_report.pdf"
        response.headers["Content-Type"] = "application/pdf"
        return response

    @staticmethod
    def generate_report_async(
        report_id: int,
        generated_by: int
    ) -> str:
        """Start async report generation and return job ID."""
        # GAP-012 Batch 5: queue mode — enqueue instead of JobTracker + thread.
        # user_id rides in the payload: the job_status 403 ownership check
        # depends on it (job_queue has no user_id column).
        if has_app_context() and current_app.config.get("JOB_QUEUE_ENABLED"):
            from app.services.job_queue_service import JobQueueService

            return str(JobQueueService.enqueue(
                "generate_report", {"report_id": report_id, "user_id": generated_by}
            ))

        # Threads do not inherit the caller's app context — without this the
        # background thread dies on `current_app` at its first DB touch and
        # the job flips straight to 'failed'.
        try:
            _app = current_app._get_current_object()
        except RuntimeError:
            _app = None  # no ambient context (CLI caller) — thread fails as before

        # Create job tracker entry
        job_id = JobTracker.create_job(
            job_type="audit_report",
            user_id=generated_by,
            total_steps=4,  # fetch, generate, save, notify
            metadata={"report_id": report_id}
        )

        # Start background thread
        import threading
        thread = threading.Thread(
            target=AuditReportService._generate_report_background,
            args=(job_id, report_id, generated_by, _app),
            daemon=True
        )
        thread.start()

        return job_id

    @staticmethod
    def _generate_report_background(job_id: str, report_id: int, generated_by: int, _app=None) -> None:
        """Background task for report generation."""
        from contextlib import nullcontext

        try:
            with (_app.app_context() if _app is not None else nullcontext()):
                # Step 1: Fetch report config
                JobTracker.update_progress(job_id, current_step=1, message="Fetching report configuration")

                report = ScheduledAuditReportRepository.get_by_id(report_id)
                if not report:
                    JobTracker.fail_job(job_id, "Scheduled report not found")
                    return

                # Step 2: Generate report data
                JobTracker.update_progress(job_id, current_step=2, message="Generating report data")

                parameters = json.loads(report["parameters"]) if report["parameters"] else {}
                start_date = parameters.get("start_date")
                end_date = parameters.get("end_date")
                user_id = parameters.get("user_id")
                action = parameters.get("action")

                if start_date:
                    start_date = date.fromisoformat(start_date)
                if end_date:
                    end_date = date.fromisoformat(end_date)

                data = AuditReportService.generate_report_data(
                    start_date=start_date,
                    end_date=end_date,
                    user_id=user_id,
                    action=action
                )

                # Step 3: Generate report file
                JobTracker.update_progress(job_id, current_step=3, message="Generating report file")

                if report["format"] == "CSV":
                    report_response = AuditReportService.generate_csv_report(data)
                else:
                    report_response = AuditReportService.generate_pdf_report(data)

                # In a real implementation, save file to storage
                # For now, just update last run time
                ScheduledAuditReportRepository.update_last_run(report_id)

                # Step 4: Send notification
                JobTracker.update_progress(job_id, current_step=4, message="Sending notification")

                try:
                    NotificationCenterService.create_notification(
                        user_id=generated_by,
                        title=f"Audit Report Generated: {report['name']}",
                        message=f"The audit report '{report['name']}' has been generated successfully.",
                        icon="&#9675;",
                        link="/admin/audit_reports"
                    )
                except Exception:
                    pass  # Don't fail if notification fails

                JobTracker.complete_job(job_id, result={"rows": len(data), "format": report["format"]})

        except Exception as e:
            JobTracker.fail_job(job_id, str(e))

    @staticmethod
    def generate_and_save_report(
        report_id: int,
        generated_by: int
    ) -> Dict[str, Any]:
        """Generate a report synchronously (for backward compatibility)."""
        report = ScheduledAuditReportRepository.get_by_id(report_id)
        if not report:
            return {"success": False, "message": "Scheduled report not found"}
        
        parameters = json.loads(report["parameters"]) if report["parameters"] else {}
        
        start_date = parameters.get("start_date")
        end_date = parameters.get("end_date")
        user_id = parameters.get("user_id")
        action = parameters.get("action")
        
        if start_date:
            start_date = date.fromisoformat(start_date)
        if end_date:
            end_date = date.fromisoformat(end_date)
        
        data = AuditReportService.generate_report_data(
            start_date=start_date,
            end_date=end_date,
            user_id=user_id,
            action=action
        )
        
        if report["format"] == "CSV":
            report_response = AuditReportService.generate_csv_report(data)
        else:
            report_response = AuditReportService.generate_pdf_report(data)
        
        ScheduledAuditReportRepository.update_last_run(report_id)
        
        try:
            NotificationCenterService.create_notification(
                user_id=generated_by,
                title=f"Audit Report Generated: {report['name']}",
                message=f"The audit report '{report['name']}' has been generated successfully.",
                icon="&#9675;",
                link="/admin/audit_reports"
            )
        except Exception:
            pass
        
        return {
            "success": True,
            "message": f"Report '{report['name']}' generated successfully.",
        }

    @staticmethod
    def run_due_reports() -> Dict[str, Any]:
        """Run all due scheduled audit reports."""
        due_reports = ScheduledAuditReportRepository.get_due_reports()
        results = []
        for report in due_reports:
            # ADM-015: attribute to the triggering user when available; fall
            # back to the admin account only as a last resort.
            from ..repositories import UserRepository
            from flask_login import current_user
            if current_user.is_authenticated:
                system_user_id = current_user.id
            else:
                admin_user = UserRepository.find_by_username("admin")
                system_user_id = admin_user["id"] if admin_user else 1
            
            result = AuditReportService.generate_and_save_report(
                report_id=report["id"],
                generated_by=system_user_id
            )
            results.append({
                "report_id": report["id"],
                "report_name": report["name"],
                "success": result["success"],
                "message": result["message"]
            })
        
        return {
            "success": True,
            "message": f"Processed {len(results)} due reports",
            "results": results
        }


# Register handlers with JobQueueService (GAP-012)
try:
    from app.services.job_queue_service import JobQueueService

    def _generate_report_handler(payload: dict) -> dict:
        report_id = payload["report_id"]
        # Batch 5 enqueue writes "user_id"; accept the legacy key too.
        generated_by = payload.get("user_id") or payload.get("generated_by")
        # Use the existing synchronous method
        return AuditReportService.generate_and_save_report(report_id, generated_by)

    def _check_due_reports_handler(payload: dict) -> dict:
        return AuditReportService.run_due_reports()

    JobQueueService.register_handler("generate_report", _generate_report_handler)
    JobQueueService.register_handler("check_due_reports", _check_due_reports_handler)
except ImportError:
    # JobQueueService not available (e.g., during migration)
    pass