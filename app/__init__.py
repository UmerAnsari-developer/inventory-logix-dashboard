"""Application factory for the Inventory Logistics Optimization Dashboard."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, g, render_template, request
from flask_login import current_user

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
from .routes import ai_bp, api_bp, auth_bp, ui_bp
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

    logging.basicConfig(
        level=logging.INFO if not app.config.get("TESTING") else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Production: surface the resolved database target and fail fast (with a
    # clear message) instead of serving 500s against an unconfigured DB.
    if not app.config.get("TESTING") and not app.config.get("DEBUG"):
        _log_database_target(config_cls)
        _ensure_database_configured(config_cls)

    _init_extensions(app)
    _register_blueprints(app)
    _register_context(app)
    _register_error_handlers(app)

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


def _register_context(app: Flask) -> None:
    from .repositories import AuditRepository

    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        from .services.settings_service import SettingsService

        reorder_count = 0
        settings = {}
        authenticated = False
        try:
            authenticated = bool(current_user.is_authenticated)
        except Exception:
            authenticated = False
        db = getattr(g, "db", None)
        if db is not None:
            try:
                with db.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) AS c FROM products "
                        "WHERE current_stock <= reorder_point AND on_order <= 0"
                    )
                    reorder_count = cur.fetchone()["c"]
            except Exception:
                reorder_count = 0
        if authenticated:
            try:
                settings = SettingsService.get_settings()
            except Exception:
                settings = {}
        return {
            "reorder_count": reorder_count,
            "current_user": current_user,
            "app_settings": settings,
        }


def _register_error_handlers(app: Flask) -> None:
    _TITLES = {
        400: "Bad request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not found",
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

    @app.errorhandler(429)
    def _too_many(err):
        return _render("errors/429.html", 429)

    @app.errorhandler(500)
    def _server_error(err):
        LOGGER.exception("Server error: %s", err)
        return _render("errors/500.html", 500)
