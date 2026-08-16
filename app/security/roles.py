"""Role-based access control helpers."""
from __future__ import annotations

from functools import wraps

from flask import abort
from flask_login import current_user

WRITE_ROLES = ("admin", "manager")


def roles_required(*roles: str):
    """Restrict a route to the given roles.

    Must be stacked under ``@login_required`` so the user is authenticated
    before the role check runs. Non-matching roles get a 403.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def write_roles_required(fn):
    """Restrict a route to admin/manager (the roles that may mutate data)."""
    return roles_required(*WRITE_ROLES)(fn)