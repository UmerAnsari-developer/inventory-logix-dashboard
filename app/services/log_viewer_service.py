"""System logs viewer service."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from flask import current_app


class LogViewerService:
    """Service for viewing system logs."""

    LOG_FILE = Path("inventorylogix.log")
    LOG_PATTERN = re.compile(
        r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) (\w+) ([^ ]+) (.*)$"
    )

    @staticmethod
    def get_log_entries(limit: int = 100, offset: int = 0, level: str | None = None,
                        start_date: datetime | None = None,
                        end_date: datetime | None = None,
                        search: str | None = None) -> list[dict]:
        """Get log entries with optional filtering."""
        if not LogViewerService.LOG_FILE.exists():
            return []
        
        entries = []
        with LogViewerService.LOG_FILE.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        
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
        if not LogViewerService.LOG_FILE.exists():
            return 0
        with LogViewerService.LOG_FILE.open("r", encoding="utf-8") as f:
            return sum(1 for _ in f)