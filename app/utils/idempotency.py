"""Idempotency key utilities for safe retry of write operations."""
from __future__ import annotations

import json
from functools import wraps
from typing import Callable

from flask import request, g
from flask_login import current_user

from ..database import get_cursor
from ..utils import api_error, api_response


class IdempotencyError(ValueError):
    """Raised when idempotency key validation fails."""
    pass


def _get_idempotency_key() -> str | None:
    """Extract idempotency key from request headers."""
    return request.headers.get("Idempotency-Key") or request.headers.get("X-Idempotency-Key")


def _get_user_id() -> int | None:
    """Get current user ID."""
    if current_user.is_authenticated:
        return current_user.id
    return None


def check_idempotency(key: str, user_id: int) -> dict | None:
    """Check if idempotency key exists and return cached response."""
    with get_cursor() as cur:
        cur.execute("SELECT sp_idempotency_check(%s, %s)", (key, user_id))
        row = cur.fetchone()
        if row and row["sp_idempotency_check"] is not None:
            return row["sp_idempotency_check"]
    return None


def reserve_idempotency(key: str, user_id: int) -> bool:
    """Reserve the key BEFORE executing the endpoint (L2 TOCTOU fix).

    Returns True if this caller owns the key (freshly inserted), False if a
    concurrent request already reserved it. Single transaction — the
    unique index (key, user_id) is the arbiter.
    """
    with get_cursor(commit=True) as cur:
        cur.execute("SELECT sp_idempotency_reserve(%s, %s)", (key, user_id))
        row = cur.fetchone()
        return bool(row["sp_idempotency_reserve"]) if row else False


def record_idempotency(key: str, user_id: int, response: dict) -> None:
    """Record idempotency key with response."""
    with get_cursor(commit=True) as cur:
        cur.execute("SELECT sp_idempotency_record(%s, %s, %s)", (key, user_id, json.dumps(response)))


def idempotent(*, required: bool = False):
    """
    Decorator to make an endpoint idempotent using Idempotency-Key header.

    Args:
        required: If True, reject requests without idempotency key (422).
                  If False, skip idempotency check when key is missing.

    Usage:
        @api_bp.route("/products", methods=["POST"])
        @idempotent(required=True)
        def create_product():
            ...

    The decorator:
    1. Extracts Idempotency-Key from headers
    2. If key exists and was seen before, returns cached response (200/201)
    3. If key is new, executes the endpoint and caches the response
    4. If required=True and no key provided, returns 422
    """
    def decorator(f: Callable):
        @wraps(f)
        def wrapped(*args, **kwargs):
            key = _get_idempotency_key()
            user_id = _get_user_id()

            if not key:
                if required:
                    return api_error("IDEMPOTENCY_KEY_REQUIRED",
                                     "Idempotency-Key header is required for this endpoint.", status=422)
                return f(*args, **kwargs)

            if user_id is None:
                return api_error("UNAUTHORIZED", "Authentication required for idempotent operations.", status=401)

            # L2: reserve the key FIRST (single txn) — closes the check-then-act
            # race where two concurrent retries both pass a plain check.
            if not reserve_idempotency(key, user_id):
                # Key owned by a concurrent request: replay its response if
                # committed, otherwise reject as in-progress.
                cached = check_idempotency(key, user_id)
                if cached is not None:
                    resp = api_response(cached.get("data"), status=cached.get("status", 200),
                                        message=cached.get("message"))
                    resp.headers["Idempotency-Replayed"] = "true"
                    return resp
                return api_error("DUPLICATE_REQUEST_IN_PROGRESS",
                                 "An identical request is already being processed.", status=409)

            # Execute the endpoint
            result = f(*args, **kwargs)

            # Cache successful responses (2xx)
            if hasattr(result, 'status_code') and 200 <= result.status_code < 300:
                try:
                    data = result.get_json()
                    if data and data.get("success"):
                        record_idempotency(key, user_id, {
                            "data": data.get("data"),
                            "status": result.status_code,
                            "message": data.get("message")
                        })
                except Exception:
                    pass  # Don't fail the request if caching fails

            return result
        return wrapped
    return decorator


def cleanup_idempotency_keys(older_than_days: int = 30) -> int:
    """Clean up old idempotency keys. Returns count of deleted keys."""
    with get_cursor(commit=True) as cur:
        cur.execute("SELECT sp_idempotency_cleanup(%s)", (f"{older_than_days} days",))
        row = cur.fetchone()
        return row["sp_idempotency_cleanup"] if row else 0