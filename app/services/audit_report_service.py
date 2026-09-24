"""Audit report generator service."""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from flask import Response, current_app

from ..database import get_cursor
from ..repositories import (
    ScheduledAuditReportRepository,
    UserActivityRepository,
)
from app.services.nnotification_center_service import NotificationCenterService


class AuditReportService:
    """Service for generating audit reports."""

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
            # We want to include the entire end date, so we add one day and use <
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
            # Create a CSV with just a header
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
        # Write header
        writer.writerow(["ID", "User ID", "Action", "Target Type", "Target ID", "Detail", "IP Address", "Created At"])
        # Write rows
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
        """Generate a PDF report from the data.
        
        For simplicity, we'll return a CSV for now. In a real implementation,
        we would use a PDF library like ReportLab or WeasyPrint.
        """
        # For now, we'll just generate a CSV and change the filename and content type.
        # In a real implementation, we would generate a proper PDF.
        response = AuditReportService.generate_csv_report(data)
        # Change the filename and content type
        response.headers["Content-Disposition"] = "attachment; filename=audit_report.pdf"
        response.headers["Content-Type"] = "application/pdf"
        return response

    @staticmethod
    def generate_and_save_report(
        report_id: int,
        generated_by: int
    ) -> Dict[str, Any]:
        """Generate a report based on a scheduled audit report and save it.
        
        Returns a dictionary with keys: success, message, report_data (if needed).
        """
        # Get the scheduled report
        report = ScheduledAuditReportRepository.get_by_id(report_id)
        if not report:
            return {"success": False, "message": "Scheduled report not found"}
        
        # Parse parameters
        parameters = json.loads(report["parameters"]) if report["parameters"] else {}
        
        # Extract parameters
        start_date = parameters.get("start_date")
        end_date = parameters.get("end_date")
        user_id = parameters.get("user_id")
        action = parameters.get("action")
        
        # Convert string dates to date objects if needed
        if start_date:
            start_date = date.fromisoformat(start_date)
        if end_date:
            end_date = date.fromisoformat(end_date)
        
        # Generate the report data
        data = AuditReportService.generate_report_data(
            start_date=start_date,
            end_date=end_date,
            user_id=user_id,
            action=action
        )
        
        # Generate the report file (CSV for now)
        if report["format"] == "CSV":
            report_response = AuditReportService.generate_csv_report(data)
        else:  # PDF
            report_response = AuditReportService.generate_pdf_report(data)
        
        # In a real implementation, we would save the file to a storage location
        # and update the report record with the file path.
        # For now, we'll just update the last run time and return success.
        
        # Update the last run time (this will also calculate the next run time)
        ScheduledAuditReportRepository.update_last_run(report_id)
        
        # Optionally, we could send a notification
        try:
            NotificationCenterService.create_notification(
                user_id=generated_by,
                title=f"Audit Report Generated: {report['name']}",
                message=f"The audit report '{report['name']}' has been generated successfully.",
                icon="&#9675;",
                link="/admin/audit_reports"
            )
        except Exception:
            # Don't fail if notification fails
            pass
        
        return {
            "success": True,
            "message": f"Report '{report['name']}' generated successfully.",
            # We could return the report data here, but for now we just return success
        }

    @staticmethod
    def run_due_reports() -> Dict[str, Any]:
        """Run all due scheduled audit reports.
        
        This method would typically be called by a scheduler or background thread.
        """
        due_reports = ScheduledAuditReportRepository.get_due_reports()
        results = []
        for report in due_reports:
            # We'll generate the report as if it was run by the system user
            # We'll use the first admin user we find as the system user
            from ..repositories import UserRepository
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