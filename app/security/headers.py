"""Apply common HTTP security headers on every response."""
from __future__ import annotations

import secrets

from flask import Flask, Response, g


def init_security_headers(app: Flask) -> None:
    """Register an ``after_request`` hook that adds defensive headers.

    The hook keeps the existing Jinja auto-escaping and CSRF protection as
    the primary XSS defence and only adds headers that work alongside them.
    A per-request nonce is generated for inline scripts.
    """

    @app.before_request
    def _set_nonce():
        g.csp_nonce = secrets.token_urlsafe(24)

    @app.context_processor
    def _inject_nonce():
        return {"csp_nonce": getattr(g, "csp_nonce", "")}

    @app.after_request
    def _apply(response: Response) -> Response:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        nonce = getattr(g, "csp_nonce", "")
        nonce_src = f"'nonce-{nonce}'" if nonce else "'unsafe-inline'"
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com data:; "
            f"script-src 'self' {nonce_src} https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://cdn.plot.ly; "
            "connect-src 'self' https://cdn.jsdelivr.net",
        )
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
