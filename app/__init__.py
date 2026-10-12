"""Application factory for the Inventory Logistics Optimization Dashboard."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, render_template, request, g, session, abort
from flask_compress import Compress
from flask_login import current_user
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import get_config
from .database.connection import (
    bootstrap_database,
    close_connection,
    etl_database,
    init_schema,
    seed_database,
)
from .extensions import csrf, limiter, login_manager
from .repositories import UserRepository
from .routes import ai_bp, api_bp, auth_bp, ui_bp, reports_workflow_bp
from .routes.openapi import openapi_bp
from .routes.admin.backup_routes import admin_backup_bp
from .routes.admin.system_config_routes import admin_system_config_bp
from .routes.admin.log_viewer_routes import admin_log_viewer_bp
from .routes.admin.user_activity_routes import admin_user_activity_bp
from .routes.admin.nnotification_center_routes import notification_center_bp
from .routes.admin.user_activity_analytics_routes import admin_user_activity_analytics_bp
from .routes.admin.export_routes import admin_export_bp
from .routes.admin.audit_report_routes import admin_audit_report_bp
from .routes.admin.dashboard_routes import admin_dashboard_bp
from .routes.admin.user_management_routes import admin_user_management_bp
from .routes.admin.data_import_routes import admin_data_import_bp
from .security.headers import init_security_headers

LOGGER = logging.getLogger(__name__)


def create_app(config_name: str | None = None) -> Flask:
    """Application factory used by ``run.py`` and the WSGI server."""
    config_cls = get_config(config_name)
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        instance_relative_config=False,
    )
    app.config.from_object(config_cls)
    _register_class_helpers(app, config_cls)

    # Opt-in reverse-proxy trust: behind a trusted proxy the shared proxy
    # IP would otherwise key every client into ONE rate-limit bucket.
    # ProxyFix rewrites remote_addr from X-Forwarded-For before
    # flask-limiter's get_remote_address runs. Default OFF keeps XFF
    # spoof-proof when the app is directly exposed.
    if app.config.get("TRUST_PROXY"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    # Enable gzip compression for all responses
    Compress(app)

    logging.basicConfig(
        level=logging.INFO if not app.config.get("TESTING") else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Add file handler for persistent logs
    log_file = Path("inventorylogix.log")
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    ))
    logging.getLogger().addHandler(file_handler)

    # Production: surface the resolved database target and fail fast (with a
    # clear message) instead of serving 500s against an unconfigured DB.
    if not app.config.get("TESTING") and not app.config.get("DEBUG"):
        _log_database_target(config_cls)
        _ensure_database_configured(config_cls)

    _init_extensions(app)
    _register_blueprints(app)
    _register_context(app)
    _register_error_handlers(app)

    # Profiling middleware - logs slow requests
    @app.before_request
    def _start_timer():
        g._start_time = time.time()

    @app.before_request
    def _set_current_user_id():
        """Set g.user_id for audit attribution in database layer."""
        if current_user.is_authenticated:
            g.user_id = current_user.id
        else:
            g.user_id = None

    @app.before_request
    def _enforce_admin_session_timeout():
        """Enforce admin session timeout for /admin/* routes.
        
        Admin sessions have a shorter timeout (default 30 minutes) than regular
        sessions for security. This middleware runs before the route handler
        and checks if the admin's last activity exceeds the timeout.
        """
        # Only apply to admin routes
        if not request.path.startswith("/admin/"):
            return None
        
        # Only apply to authenticated admin users
        if not current_user.is_authenticated or current_user.role != "admin":
            return None
        
        from .config.settings import Config
        
        last_activity_str = session.get("admin_last_activity")
        if last_activity_str:
            try:
                last_activity = datetime.fromisoformat(last_activity_str)
                # Handle both naive and aware datetimes
                if last_activity.tzinfo is None:
                    last_activity = last_activity.replace(tzinfo=timezone.utc)
                
                now = datetime.now(timezone.utc)
                timeout_minutes = Config.ADMIN_SESSION_TIMEOUT_MINUTES
                
                if now - last_activity > timedelta(minutes=timeout_minutes):
                    # Session expired - clear admin activity and abort
                    session.pop("admin_last_activity", None)
                    abort(403, description="Admin session expired. Please log in again.")
            except (ValueError, TypeError):
                # Invalid format - reset and continue
                pass
        
        # Update last activity on every admin request (sliding window)
        session["admin_last_activity"] = datetime.now(timezone.utc).isoformat()
        return None

    @app.after_request
    def _log_slow(response):
        if hasattr(g, '_start_time'):
            duration = time.time() - g._start_time
            if duration > 1.0:
                LOGGER.warning("SLOW: %s %s - %.2fs", request.method, request.path, duration)
        return response

    @app.cli.command("init-db")
    def init_db_cmd() -> None:  # pragma: no cover
        init_schema()
        seed_database()
        etl_database()

    @app.cli.command("seed-db")
    def seed_db_cmd(force: bool = False) -> None:  # pragma: no cover
        seed_database(force=force)

    @app.cli.command("etl-db")
    def etl_db_cmd(force: bool = False) -> None:  # pragma: no cover
        etl_database(force=force)

    # First-run bootstrap (idempotent, once per process). Under the Flask
    # debug reloader the monitor (parent) process also imports this module;
    # only the serving child should touch the database so the DB isn't
    # bootstrapped twice on every ``python run.py`` start.
    reloader_parent = app.config.get("DEBUG", False) and os.environ.get("WERKZEUG_RUN_MAIN") != "true"
    if not reloader_parent:
        with app.app_context():
            try:
                bootstrap_database()
            except Exception as exc:
                # DB-086: fail fast in production, log warning in development
                if app.config.get("ENV") == "production":
                    LOGGER.error("Database bootstrap failed: %s", exc)
                    raise
                LOGGER.warning("Database bootstrap deferred: %s", exc)

    return app


def _register_class_helpers(app: Flask, config_cls) -> None:
    """Expose small helper methods on ``app.config`` so they're test-friendly."""

    def _params():
        return config_cls.psycopg2_params()

    app.config["psycopg2_params"] = _params


def _log_database_target(config_cls) -> None:
    """Log which PostgreSQL host the app resolved to (never the password)."""
    params = config_cls.psycopg2_params()
    if "dsn" in params:
        dsn = params["dsn"]
        host = dsn.split("@")[-1].split("/")[0] if "@" in dsn else "unknown"
        LOGGER.info("Connecting to PostgreSQL via DATABASE_URL (host %s).", host)
    else:
        LOGGER.info(
            "Connecting to PostgreSQL at %s:%s/%s.",
            params.get("host"),
            params.get("port"),
            params.get("dbname"),
        )


def _ensure_database_configured(config_cls) -> None:
    """Raise a clear error if production resolves to the localhost defaults."""
    params = config_cls.psycopg2_params()
    if params.get("dsn"):
        return
    if params.get("host") == "localhost":
        LOGGER.error(
            "No database configured: DATABASE_URL is not set and DB_HOST "
            "defaults to localhost. On Render, open the service Environment "
            "and set DATABASE_URL to the PostgreSQL connection string (or "
            "deploy via render.yaml Blueprint, which wires it automatically)."
        )
        raise RuntimeError(
            "Database is not configured: set DATABASE_URL (or DB_HOST/DB_PORT/"
            "DB_NAME/DB_USER/DB_PASSWORD) in the service environment."
        )


def _check_redis_connectivity(uri: str, timeout: float = 2.0) -> tuple[bool, str | None]:
    """Check Redis connectivity with timeout.
    
    Args:
        uri: Redis connection URI
        timeout: Connection timeout in seconds
        
    Returns:
        Tuple of (success: bool, error_message: str | None)
    """
    if not uri.startswith("redis://"):
        return False, "URI must start with redis://"
    
    try:
        import redis
        client = redis.from_url(uri, socket_connect_timeout=timeout)
        client.ping()
        return True, None
    except Exception as e:
        return False, str(e)


def _init_extensions(app: Flask) -> None:
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def _load_user(user_id: str):
        try:
            return UserRepository.find_by_id(int(user_id))
        except (TypeError, ValueError):
            return None

    app.teardown_appcontext(close_connection)
    init_security_headers(app)


def _register_blueprints(app: Flask) -> None:
    app.register_blueprint(auth_bp)
    app.register_blueprint(ui_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(reports_workflow_bp)
    # GAP-013: versioned aliases — same blueprint objects, distinct names
    # (Flask ≥2.0.1). /api and /ai remain the unversioned canonical prefixes.
    app.register_blueprint(api_bp, name="api_v1", url_prefix="/api/v1")
    app.register_blueprint(ai_bp, name="ai_v1", url_prefix="/ai/v1")
    # GAP-013: OpenAPI 3.0 spec (GET /api/openapi.json)
    app.register_blueprint(openapi_bp)
    app.register_blueprint(admin_backup_bp)
    app.register_blueprint(admin_system_config_bp)
    app.register_blueprint(admin_user_activity_bp)
    app.register_blueprint(notification_center_bp)
    app.register_blueprint(admin_user_activity_analytics_bp)
    app.register_blueprint(admin_log_viewer_bp)
    app.register_blueprint(admin_export_bp)
    app.register_blueprint(admin_audit_report_bp)
    app.register_blueprint(admin_dashboard_bp)
    app.register_blueprint(admin_user_management_bp)
    app.register_blueprint(admin_data_import_bp)


def _register_context(app: Flask) -> None:
    @app.context_processor
    def inject_globals():
        settings = {}
        try:
            if current_user.is_authenticated:
                from .utils.cache import global_cache
                settings = global_cache.get(f"settings:{current_user.id}") or {}
        except Exception:
            pass
        try:
            from .utils.cache import global_cache
            reorder_count = global_cache.get_or_set("reorder_count", _fetch_reorder_count)
        except Exception:
            reorder_count = 0
        return {"app_settings": settings, "reorder_count": reorder_count}


def _fetch_reorder_count() -> int:
    from .database import get_cursor
    with get_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS c FROM products "
            "WHERE current_stock <= reorder_point AND on_order <= 0"
        )
        return int(cur.fetchone()["c"] or 0)


def _register_error_handlers(app: Flask) -> None:
    _TITLES = {
        400: "Bad request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not found",
        413: "File too large",
        422: "Unprocessable request",
        429: "Too many requests",
        500: "Server error",
    }

    def _fallback_page(code: int) -> str:
        """Self-contained error page that never touches the database."""
        title = _TITLES.get(code, "Error")
        return (
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<title>{code} {title}</title>"
            "<style>"
            "body{font-family:Inter,system-ui,sans-serif;background:#f7f5ef;color:#13242c;"
            "display:grid;place-items:center;min-height:100vh;margin:0}"
            ".card{background:#fff;padding:2.2rem 2.8rem;border-radius:22px;text-align:center;"
            "box-shadow:0 18px 45px rgba(19,36,44,.08)}"
            ".code{font-size:56px;font-weight:800;color:#3d997c;margin:0}"
            ".back{display:inline-block;margin-top:1.1rem;color:#fff;background:#3d997c;"
            "padding:.6rem 1.2rem;border-radius:9px;text-decoration:none}"
            "</style></head><body><div class=\"card\">"
            f"<p class=\"code\">{code}</p><h1>{title}</h1>"
            "<p>InventoryLogix</p><a class=\"back\" href=\"/\">Go home</a>"
            "</div></body></html>"
        )

    def _render(template: str, code: int):
        try:
            return render_template(template), code
        except Exception:
            return _fallback_page(code), code

    @app.errorhandler(400)
    def _bad_request(err):
        return _render("errors/400.html", 400)

    @app.errorhandler(401)
    def _unauthorized(err):
        return _render("errors/401.html", 401)

    @app.errorhandler(403)
    def _forbidden(err):
        return _render("errors/403.html", 403)

    @app.errorhandler(404)
    def _not_found(err):
        return _render("errors/404.html", 404)

    @app.errorhandler(422)
    def _unprocessable(err):
        return _render("errors/422.html", 422)

    @app.errorhandler(413)
    def _file_too_large(err):
        # CSV import etc.: body exceeded MAX_CONTENT_LENGTH (default 5 MB).
        if request.path.startswith("/api"):
            from .utils import api_error

            return api_error(
                "FILE_TOO_LARGE",
                "Uploaded file exceeds the 5 MB size limit. Split the CSV into smaller files.",
                status=413,
            )
        return _render("errors/413.html", 413)

    @app.errorhandler(429)
    def _too_many(err):
        if request.path.startswith("/api"):
            from .utils import api_error

            return api_error(
                "RATE_LIMITED", "Too many requests. Please try again later.", status=429
            )
        return _render("errors/429.html", 429)

    @app.errorhandler(500)
    def _server_error(err):
        LOGGER.exception("Server error: %s", err)
        return _render("errors/500.html", 500)
