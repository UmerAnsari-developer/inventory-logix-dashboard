"""Threading-based job tracker for async operations."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional


class JobTracker:
    """Thread-safe job tracker for async operations with progress polling."""
    
    _jobs: Dict[str, Dict[str, Any]] = {}
    _lock = threading.Lock()
    
    @classmethod
    def create_job(
        cls,
        job_type: str,
        user_id: int,
        total_steps: int = 100,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Create a new job and return job ID."""
        job_id = str(uuid.uuid4())
        
        with cls._lock:
            cls._jobs[job_id] = {
                "job_id": job_id,
                "job_type": job_type,
                "user_id": user_id,
                "status": "pending",
                "progress": 0,
                "current_step": 0,
                "total_steps": total_steps,
                "message": "Job created",
                "result": None,
                "error": None,
                "metadata": metadata or {},
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "started_at": None,
                "completed_at": None,
            }
        
        return job_id
    
    @classmethod
    def get_job(cls, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job status by ID."""
        with cls._lock:
            job = cls._jobs.get(job_id)
            if job:
                # Return a copy to prevent external modification
                return dict(job)
            return None
    
    @classmethod
    def update_progress(
        cls,
        job_id: str,
        current_step: int,
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Update job progress."""
        with cls._lock:
            job = cls._jobs.get(job_id)
            if not job:
                return False
            
            job["current_step"] = current_step
            job["total_steps"] = max(job["total_steps"], current_step)
            job["progress"] = int((current_step / job["total_steps"]) * 100) if job["total_steps"] > 0 else 0
            job["status"] = "running"
            job["message"] = message
            job["updated_at"] = datetime.now()
            
            if job["started_at"] is None:
                job["started_at"] = datetime.now()
            
            if metadata:
                job["metadata"].update(metadata)
            
            return True
    
    @classmethod
    def complete_job(cls, job_id: str, result: Optional[Dict[str, Any]] = None) -> bool:
        """Mark job as completed."""
        with cls._lock:
            job = cls._jobs.get(job_id)
            if not job:
                return False
            
            job["status"] = "completed"
            job["progress"] = 100
            job["current_step"] = job["total_steps"]
            job["result"] = result
            job["completed_at"] = datetime.now()
            job["updated_at"] = datetime.now()
            job["message"] = "Job completed successfully"
            
            return True
    
    @classmethod
    def fail_job(cls, job_id: str, error: str) -> bool:
        """Mark job as failed."""
        with cls._lock:
            job = cls._jobs.get(job_id)
            if not job:
                return False
            
            job["status"] = "failed"
            job["error"] = error
            job["completed_at"] = datetime.now()
            job["updated_at"] = datetime.now()
            job["message"] = f"Job failed: {error}"
            
            return True
    
    @classmethod
    def cleanup_job(cls, job_id: str) -> bool:
        """Remove job from tracker."""
        with cls._lock:
            if job_id in cls._jobs:
                del cls._jobs[job_id]
                return True
            return False
    
    @classmethod
    def cleanup_old_jobs(cls, max_age_hours: int = 24) -> int:
        """Remove jobs older than max_age_hours."""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        cleaned = 0
        
        with cls._lock:
            to_delete = [
                job_id for job_id, job in cls._jobs.items()
                if job["created_at"] < cutoff and job["status"] in ("completed", "failed")
            ]
            for job_id in to_delete:
                del cls._jobs[job_id]
                cleaned += 1
        
        return cleaned
    
    @classmethod
    def list_jobs(cls, user_id: Optional[int] = None, status: Optional[str] = None) -> list[Dict[str, Any]]:
        """List jobs with optional filters."""
        with cls._lock:
            jobs = list(cls._jobs.values())
        
        if user_id is not None:
            jobs = [j for j in jobs if j["user_id"] == user_id]
        
        if status is not None:
            jobs = [j for j in jobs if j["status"] == status]
        
        # Sort by created_at descending
        jobs.sort(key=lambda j: j["created_at"], reverse=True)
        
        return jobs