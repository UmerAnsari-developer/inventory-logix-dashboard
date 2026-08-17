"""Application entry point.

Run the development server with ``python run.py`` or the production WSGI
server with ``gunicorn run:app``.
"""
from __future__ import annotations

import os
import threading
import time
import webbrowser

from app import create_app


def _default_env() -> str:
    """Local dev by default, production when deployed (Render sets RENDER_INSTANCE_ID).

    Local ``python run.py`` keeps the auto-reload debug server. On Render the
    debug reloader is disabled so the app runs as a single stable process with
    one shared database connection instead of restarting/reconnecting.
    """
    if os.environ.get("FLASK_ENV"):
        return os.environ["FLASK_ENV"]
    if os.environ.get("RENDER_INSTANCE_ID"):
        return "production"
    return "development"


app = create_app(_default_env())


def _open_landing_page(port: int) -> None:
    """Open the browser at the landing page shortly after the server starts."""
    time.sleep(1.5)
    webbrowser.open(f"http://localhost:{port}/")


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))

    if not os.environ.get("WERKZEUG_RUN_MAIN") and not os.environ.get("RENDER_INSTANCE_ID"):
        threading.Thread(target=_open_landing_page, args=(port,), daemon=True).start()

    app.run(
        host=host,
        port=port,
        debug=app.config.get("DEBUG", False),
    )
