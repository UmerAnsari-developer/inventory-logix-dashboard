"""Tests for async reports with progress polling (threading-based)."""
from __future__ import annotations

import pytest
import time
import threading
from unittest.mock import patch, MagicMock

from app.services.job_tracker import JobTracker
from app.services.audit_report_service import AuditReportService
from app.repositories import ScheduledAuditReportRepository
from app.database import get_cursor
from app.repositories import UserRepository


@pytest.fixture
def admin_user_id(app):
    """Get the admin user ID dynamically (avoids hardcoded ID=1)."""
    with app.app_context():
        admin = UserRepository.find_by_username("admin")
        assert admin is not None, "admin user must exist"
        return admin.id


class TestAsyncReportsProgress:
    """Test async reports with progress polling using threading."""

    @pytest.fixture(autouse=True)
    def setup_db(self, app):
        """Set up test database."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM scheduled_audit_reports WHERE name LIKE 'TEST_%'")
            yield
            with app.app_context():
                with get_cursor(commit=True) as cur:
                    cur.execute("DELETE FROM scheduled_audit_reports WHERE name LIKE 'TEST_%'")

    def test_job_tracker_exists(self):
        """Test that JobTracker class exists."""
        assert hasattr(JobTracker, 'create_job')

    def test_create_job_returns_job_id(self, app):
        """Test that create_job returns a valid job ID."""
        with app.app_context():
            job_id = JobTracker.create_job("test_report", user_id=1, total_steps=5)
            assert job_id is not None
            assert isinstance(job_id, str)

    def test_get_job_returns_status(self, app):
        """Test that get_job returns job status."""
        with app.app_context():
            job_id = JobTracker.create_job("test_report", user_id=1, total_steps=5)
            job = JobTracker.get_job(job_id)
            assert job is not None
            assert job["status"] == "pending"
            assert job["total_steps"] == 5

    def test_update_progress_updates_job(self, app):
        """Test that update_progress updates job status."""
        with app.app_context():
            job_id = JobTracker.create_job("test_report", user_id=1, total_steps=5)
            JobTracker.update_progress(job_id, current_step=3, message="Halfway")
            job = JobTracker.get_job(job_id)
            assert job["current_step"] == 3
            assert job["message"] == "Halfway"

    def test_complete_job_marks_done(self, app):
        """Test that complete_job marks job as done."""
        with app.app_context():
            job_id = JobTracker.create_job("test_report", user_id=1, total_steps=5)
            JobTracker.complete_job(job_id, result={"success": True})
            job = JobTracker.get_job(job_id)
            assert job["status"] == "completed"
            assert job["result"]["success"] is True

    def test_fail_job_marks_failed(self, app):
        """Test that fail_job marks job as failed."""
        with app.app_context():
            job_id = JobTracker.create_job("test_report", user_id=1, total_steps=5)
            JobTracker.fail_job(job_id, error="Something went wrong")
            job = JobTracker.get_job(job_id)
            assert job["status"] == "failed"
            assert job["error"] == "Something went wrong"

    def test_async_report_generation(self, app, admin_user_id):
        """Test that audit report can be generated asynchronously."""
        with app.app_context():
            # Create a scheduled report
            report_id = ScheduledAuditReportRepository.create(
                name="TEST_Async_Report",
                description="Test async report",
                format="CSV",
                frequency="daily",
                parameters={"start_date": "2024-01-01", "end_date": "2024-01-31"},
                next_run_time="2024-01-01 00:00:00",
                created_by=admin_user_id
            )
            
            # Generate report asynchronously
            job_id = AuditReportService.generate_report_async(
                report_id=report_id,
                generated_by=admin_user_id
            )
            
            assert job_id is not None
            
            # Job should be created
            job = JobTracker.get_job(job_id)
            assert job is not None
            assert job["status"] in ("pending", "running")

    def test_progress_polling_works(self, app, admin_user_id):
        """Test that progress can be polled."""
        with app.app_context():
            job_id = JobTracker.create_job("test_poll", user_id=admin_user_id, total_steps=10)
            
            # Simulate progress updates
            for i in range(1, 11):
                JobTracker.update_progress(job_id, current_step=i, message=f"Step {i}")
                time.sleep(0.01)  # Small delay
                
                job = JobTracker.get_job(job_id)
                assert job["current_step"] == i
                assert job["progress"] == i * 10

    def test_concurrent_jobs_isolated(self, app, admin_user_id):
        """Test that concurrent jobs don't interfere."""
        with app.app_context():
            job_id_1 = JobTracker.create_job("job_1", user_id=admin_user_id, total_steps=5)
            job_id_2 = JobTracker.create_job("job_2", user_id=admin_user_id, total_steps=5)
            
            JobTracker.update_progress(job_id_1, current_step=3)
            JobTracker.update_progress(job_id_2, current_step=1)
            
            job_1 = JobTracker.get_job(job_id_1)
            job_2 = JobTracker.get_job(job_id_2)
            
            assert job_1["current_step"] == 3
            assert job_2["current_step"] == 1

    def test_job_cleanup_after_completion(self, app, admin_user_id):
        """Test that completed jobs are cleaned up after TTL."""
        with app.app_context():
            job_id = JobTracker.create_job("cleanup_test", user_id=admin_user_id, total_steps=1)
            JobTracker.complete_job(job_id)
            
            # Job should still be retrievable immediately
            job = JobTracker.get_job(job_id)
            assert job["status"] == "completed"
            
            # Note: Actual TTL cleanup is tested separately with time manipulation