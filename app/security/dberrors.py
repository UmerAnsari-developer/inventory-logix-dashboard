"""Translate PostgreSQL driver errors into domain-friendly messages.

Integrity guards live in the database (unique SKU, stock floor, PO state
machine). This module is the single place where those failures are recognised
so services can raise clean domain errors instead of leaking HTTP 500s.
"""
from __future__ import annotations

import psycopg2.errors


def db_error_message(exc: Exception) -> str:
    """Return the first line of the server message for a DB error.

    psycopg2 prefixes pgerror with ``ERROR:  ``; strip it so callers can
    compare against the bare RAISE text ('Invalid PO transition: ...').
    """
    text = getattr(exc, "pgerror", None) or str(exc) or ""
    lines = text.strip().splitlines()
    first = lines[0] if lines else ""
    if first.startswith("ERROR:"):
        first = first[6:].lstrip()
    return first


def is_unique_violation(exc: Exception) -> bool:
    """True for SQLSTATE 23505 (unique_violation)."""
    return isinstance(exc, psycopg2.errors.UniqueViolation)


def is_guard_error(exc: Exception, *prefixes: str) -> bool:
    """True for a plpgsql ``RAISE EXCEPTION`` whose message starts with a prefix."""
    if not isinstance(exc, psycopg2.errors.RaiseException):
        return False
    msg = db_error_message(exc)
    return any(msg.startswith(p) for p in prefixes)
