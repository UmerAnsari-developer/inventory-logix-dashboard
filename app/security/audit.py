"""Centralized audit decorator for admin routes."""
from __future__ import annotations

import functools
import json
from datetime import datetime
from typing import Callable, Any, Optional

from flask import request, current_app
from flask_login import current_user

from ..repositories import AuditRepository


def audit_action(
    action: str,
    target_type: str = "",
    target_id_arg: str = "",
    detail_func: Optional[Callable] = None
):
    """
    Decorator to audit function calls.
    
    Args:
        action: Action name (e.g., "user.create", "backup.restore")
        target_type: Target type (e.g., "user", "backup", "config")
        target_id_arg: Name of function argument to use as target_id
        detail_func: Optional function(result, *args, **kwargs) -> dict for custom detail
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # Get user info
            user_id = None
            ip_address = None
            user_agent = None
            
            if current_user.is_authenticated:
                user_id = current_user.id
            
            if request:
                ip_address = request.remote_addr or "127.0.0.1"
                user_agent = request.user_agent.string if request.user_agent else None
            
            # Get target_id from function arguments if specified
            target_id = None
            if target_id_arg and target_id_arg in kwargs:
                target_id = kwargs[target_id_arg]
            elif target_id_arg and args:
                # Try to get from positional args (assume first arg after self)
                import inspect
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                if target_id_arg in params:
                    idx = params.index(target_id_arg)
                    if idx < len(args):
                        target_id = args[idx]
            
            # Execute function
            success = True
            error = None
            result = None
            
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                error = str(e)
                raise
            finally:
                # Build detail
                detail = {}
                if detail_func:
                    try:
                        detail = detail_func(result, *args, **kwargs)
                    except Exception:
                        detail = {"detail_error": "Failed to generate detail"}
                else:
                    detail = {"success": success}
                    if error:
                        detail["error"] = error
                    if result is not None and not isinstance(result, (str, int, float, bool)):
                        try:
                            detail["result_type"] = type(result).__name__
                        except Exception:
                            pass
                
                # Record audit
                try:
                    AuditRepository.record(
                        user_id=user_id,
                        action=action,
                        target_type=target_type or None,
                        target_id=target_id,
                        detail=detail,
                        ip_address=ip_address
                    )
                except Exception:
                    # Don't let audit failures break the main flow
                    if current_app:
                        current_app.logger.exception("Audit logging failed")
        
        return wrapper
    return decorator


def audit_admin_action(
    action: str,
    target_type: str = "",
    target_id_arg: str = "",
    detail_func: Optional[Callable] = None
):
    """
    Decorator to audit admin actions with role check.
    
    Requires current_user to have admin role.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # Check admin role
            if not current_user.is_authenticated:
                raise PermissionError("Authentication required")
            
            if current_user.role != "admin":
                raise PermissionError("Admin role required")
            
            # Apply audit_action decorator
            audited_func = audit_action(action, target_type, target_id_arg, detail_func)(func)
            return audited_func(*args, **kwargs)
        
        return wrapper
    return decorator