"""Audit log repository via stored procedures."""
from __future__ import annotations

import json as _json

from ..database import get_cursor
from flask import g


class AuditRepository:
    @staticmethod
    def record(user_id: int | None, action: str, *, target_type: str | None = None,
               target_id: int | None = None, detail: dict | None = None,
               ip_address: str | None = None, cur=None) -> None:
        """Record an audit log entry.
        
        Args:
            cur: Optional existing cursor to use. If not provided, a new transaction is created.
                 This allows the caller to control the transaction and set GUCs.
        """
        owns_cursor = cur is None
        if owns_cursor:
            ctx = get_cursor(commit=True)
            cur = ctx.__enter__()
            try:
                cur.execute(
                    "SELECT sp_audit_record(%s, %s, %s, %s, %s, %s)",
                    (
                        user_id, action, target_type, target_id,
                        _json.dumps(detail or {}), ip_address,
                    ),
                )
            finally:
                ctx.__exit__(None, None, None)
        else:
            cur.execute(
                "SELECT sp_audit_record(%s, %s, %s, %s, %s, %s)",
                (
                    user_id, action, target_type, target_id,
                    _json.dumps(detail or {}), ip_address,
                ),
            )
