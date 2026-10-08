"""Tests for threaded job tracker."""
from __future__ import annotations

import pytest
import threading
import time
from unittest.mock import patch, MagicMock

from app.services.job_tracker import JobTracker


class TestThreadedJobs:
    """Test threading-based job tracker."""

    def test_job_tracker_thread_safe(self):
        """Test that JobTracker is thread-safe."""
        job_id = JobTracker.create_job("thread_test", user_id=1, total_steps=100)
        
        errors = []
        
        def update_progress(thread_id):
            try:
                for i in range(10):
                    JobTracker.update_progress(job_id, current_step=thread_id * 10 + i)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(str(e))
        
        threads = [threading.Thread(target=update_progress, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        
        job = JobTracker.get_job(job_id)
        assert job is not None

    def test_job_tracker_uses_threading_lock(self):
        """Test that JobTracker uses threading.Lock for synchronization."""
        # Check that JobTracker has a lock
        assert hasattr(JobTracker, '_lock')
        assert isinstance(JobTracker._lock, threading.Lock)

    def test_job_storage_is_dict(self):
        """Test that jobs are stored in a dictionary."""
        assert hasattr(JobTracker, '_jobs')
        assert isinstance(JobTracker._jobs, dict)

    def test_create_job_generates_unique_ids(self):
        """Test that create_job generates unique job IDs."""
        ids = set()
        for _ in range(100):
            job_id = JobTracker.create_job("unique_test", user_id=1, total_steps=10)
            assert job_id not in ids
            ids.add(job_id)

    def test_job_expiration_cleanup(self):
        """Test that old jobs can be cleaned up."""
        # Create a job
        job_id = JobTracker.create_job("expiry_test", user_id=1, total_steps=5)
        JobTracker.complete_job(job_id)
        
        # Manually set created_at to old time
        import datetime
        JobTracker._jobs[job_id]["created_at"] = datetime.datetime.now() - datetime.timedelta(hours=25)
        
        # Run cleanup
        JobTracker.cleanup_old_jobs(max_age_hours=24)
        
        # Job should be removed
        assert job_id not in JobTracker._jobs

    def test_job_tracker_singleton_pattern(self):
        """Test that JobTracker uses class-level storage (singleton-like)."""
        # All calls should share the same job storage
        job_id = JobTracker.create_job("singleton_test", user_id=1, total_steps=5)
        
        # Access from another "instance" (class method)
        job = JobTracker.get_job(job_id)
        assert job is not None
        assert job["job_id"] == job_id

    def test_update_progress_calculates_percentage(self):
        """Test that progress percentage is calculated correctly."""
        job_id = JobTracker.create_job("progress_test", user_id=1, total_steps=10)
        
        JobTracker.update_progress(job_id, current_step=5)
        job = JobTracker.get_job(job_id)
        assert job["progress"] == 50
        
        JobTracker.update_progress(job_id, current_step=10)
        job = JobTracker.get_job(job_id)
        assert job["progress"] == 100

    def test_job_metadata_stored(self):
        """Test that job metadata is stored."""
        job_id = JobTracker.create_job(
            "metadata_test", 
            user_id=42, 
            total_steps=10,
            metadata={"report_type": "audit", "format": "CSV"}
        )
        
        job = JobTracker.get_job(job_id)
        assert job["user_id"] == 42
        assert job["metadata"]["report_type"] == "audit"
        assert job["metadata"]["format"] == "CSV"

    def test_fail_job_stores_error(self):
        """Test that fail_job stores error message."""
        job_id = JobTracker.create_job("fail_test", user_id=1, total_steps=5)
        
        JobTracker.fail_job(job_id, error="Database connection failed")
        
        job = JobTracker.get_job(job_id)
        assert job["status"] == "failed"
        assert job["error"] == "Database connection failed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])