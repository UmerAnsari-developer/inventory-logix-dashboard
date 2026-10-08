"""System logs viewer service."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from flask import current_app


class LogViewerService:
    """Service for viewing system logs."""

    # Fixed log file path - not user controllable
    LOG_FILE = Path("inventorylogix.log").resolve()
    LOG_PATTERN = re.compile(
        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) (\w+) ([^ ]+) (.*)$"
    )

    @staticmethod
    def _validate_log_path() -> Path:
        """Validate that the log file is within the allowed directory."""
        log_file = LogViewerService.LOG_FILE.resolve()
        # ADM-011: realpath both sides — defeats symlinks and '..' components.
        cwd = Path.cwd().resolve()
        try:
            log_file.relative_to(cwd)
        except ValueError:
            # Log file is outside the working directory - security issue
            current_app.logger.error(f"Log file path traversal attempt detected: {log_file}")
            raise ValueError("Invalid log file path")
        return log_file

    @staticmethod
    def get_log_entries(limit: int = 100, offset: int = 0, level: str | None = None,
                        start_date: datetime | None = None,
                        end_date: datetime | None = None,
                        search: str | None = None) -> list[dict]:
        """Get log entries with optional filtering."""
        # Validate log file path to prevent path traversal
        log_file = LogViewerService._validate_log_path()
        
        if not log_file.exists():
            return []
        
        entries = []
        # ADM-028: bounded read — keep only the last `limit + offset` lines
        # instead of loading the whole file into memory (OOM on large logs).
        # errors="replace": log lines may contain non-UTF-8 bytes (e.g. em-dashes
        # written by a non-UTF-8 console handler) — a strict decode would crash
        # the admin dashboard with UnicodeDecodeError.
        from collections import deque
        with log_file.open("r", encoding="utf-8", errors="replace") as f:
            lines = deque(f, maxlen=limit + offset)
        
        # Process lines in reverse order to get the most recent first
        for line in reversed(lines):
            match = LogViewerService.LOG_PATTERN.match(line.strip())
            if not match:
                # Skip lines that don't match the pattern
                continue
            
            timestamp_str, level_str, name, message = match.groups()
            try:
                timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S,%f")
            except ValueError:
                # If parsing fails, skip this entry
                continue
            
            # Apply filters
            if level and level_str.upper() != level.upper():
                continue
            if start_date and timestamp < start_date:
                continue
            if end_date and timestamp > end_date:
                continue
            if search and search.lower() not in message.lower():
                continue
            
            entries.append({
                "timestamp": timestamp,
                "level": level_str,
                "name": name,
                "message": message,
                "raw": line.strip()
            })
            
            # Stop if we have enough entries (after filtering)
            if len(entries) >= limit + offset:
                break
        
        # Apply offset
        return entries[offset:offset+limit]

    @staticmethod
    def get_recent_logs(limit: int = 100) -> list[dict]:
        """Get recent log entries."""
        return LogViewerService.get_log_entries(limit=limit)

    @staticmethod
    def get_log_count() -> int:
        """Get the total number of log lines."""
        log_file = LogViewerService._validate_log_path()
        if not log_file.exists():
            return 0
        # errors="replace": log lines may contain non-UTF-8 bytes (e.g. em-dashes
        # written by a non-UTF-8 console handler) — a strict decode would crash
        # the admin dashboard with UnicodeDecodeError.
        with log_file.open("r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)