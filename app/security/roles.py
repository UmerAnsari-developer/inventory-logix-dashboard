"""Role-based access control helpers.

Two separate concepts (do not conflate):
- RBAC role/permission: what a user can access (users.role tier + users.job_role)
- Reporting Manager: organizational relationship (users.reporting_manager_id) —
  grants VISIBILITY into subordinate submissions, never permissions.

Hierarchy (4 levels):
    inventory.director
    └── vp.operations
        ├── procurement.manager
        │   ├── procurement.buyer
        │   ├── procurement.coordinator
        │   └── supplier.coordinator
        ├── warehouse.manager
        │   ├── receiving.associate
        │   └── inventory.analyst
        └── demand.planning.analyst
"""
from __future__ import annotations

from functools import wraps

from flask import abort
from flask_login import current_user

WRITE_ROLES = ("admin", "manager")

# ── Hierarchy job roles (10 exposed; "supplier" documented but NOT exposed —
#    the app has no external-user support in its security model) ──
JOB_ROLES = (
    "inventory_director", "vp_operations",
    "procurement_manager", "procurement_buyer", "procurement_coordinator",
    "supplier_coordinator",
    "warehouse_manager", "receiving_associate",
    "inventory_analyst", "demand_planning_analyst",
)

# Legacy role → default hierarchy job role (migration mapping)
LEGACY_JOB_ROLE = {
    "admin": "inventory_director",
    "manager": "procurement_manager",
    "viewer": "inventory_analyst",
}

# ── Permission model (code-level for fast checks; mirrored in job_role_permissions
#    table for admin UI display) ──
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "inventory_director": {"*"},  # everything
    "vp_operations": {
        "inventory.view.all", "dashboard.view", "forecast.view", "analytics.view",
        "supplier.view", "reports.view.all", "reports.review",
        "procurement.view", "warehouse.view",
    },
    "procurement_manager": {
        "procurement.view", "po.view", "po.create", "po.approve",
        "supplier.view", "supplier.manage", "reports.review",
        "report.submit", "dashboard.view",
    },
    "procurement_buyer": {
        "po.view", "po.create", "supplier.view", "report.submit", "dashboard.view",
    },
    "procurement_coordinator": {
        "po.view", "po.create", "report.submit", "dashboard.view",
    },
    "supplier_coordinator": {
        "supplier.view", "supplier.manage", "report.submit", "dashboard.view",
    },
    "warehouse_manager": {
        "warehouse.view", "stock.receive", "stock.adjust",
        "reports.review", "report.submit", "dashboard.view",
    },
    "receiving_associate": {
        "stock.receive", "warehouse.view", "report.submit", "dashboard.view",
    },
    "inventory_analyst": {
        "analytics.view", "forecast.view", "report.submit", "dashboard.view",
    },
    "demand_planning_analyst": {
        "forecast.view", "forecast.run", "forecast.validate",
        "analytics.view", "report.submit", "dashboard.view",
    },
}


def user_job_role(user) -> str:
    """Resolve a user's hierarchy job role (falls back to legacy role mapping)."""
    job_role = user.get("job_role") if user is not None else None
    if job_role in JOB_ROLES:
        return job_role
    return LEGACY_JOB_ROLE.get(user.get("role") if user else None, "inventory_analyst")


def user_permissions(user) -> set[str]:
    """Effective permission set for a user. Admins hold '*' (everything)."""
    if user is not None and user.get("role") == "admin":
        return {"*"}
    return set(ROLE_PERMISSIONS.get(user_job_role(user), set()))


def has_permission(user, permission: str) -> bool:
    """Check a single permission (server-side; never rely on frontend hiding)."""
    perms = user_permissions(user)
    return "*" in perms or permission in perms


def roles_required(*roles: str):
    """Restrict a route to the given roles.

    Must be stacked under ``@login_required`` so the user is authenticated
    before the role check runs. Non-matching roles get a 403.

    Admin session timeout is enforced by middleware in create_app().
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


def permission_required(permission: str):
    """Restrict a route to users holding the given permission.

    Resolved from users.job_role (hierarchy role) with legacy fallback.
    Must be stacked under ``@login_required``.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not has_permission(current_user, permission):
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator