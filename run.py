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

app = create_app(os.environ.get("FLASK_ENV", "development"))


def _open_landing_page(port: int) -> None:
    """Open the browser at the landing page shortly after the server starts."""
    time.sleep(1.5)
    webbrowser.open(f"http://localhost:{port}/")


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))

    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        threading.Thread(target=_open_landing_page, args=(port,), daemon=True).start()

    app.run(
        host=host,
        port=port,
        debug=app.config.get("DEBUG", False),
    )
