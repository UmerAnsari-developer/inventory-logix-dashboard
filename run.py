"""Application entry point.

Local development runs the Werkzeug debug server (``python run.py``). On
production (Render) the same command transparently serves the app with
Gunicorn — one worker, two threads — so every request is handled by a single
stable process sharing one database connection pool.
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


def _serve_with_gunicorn(host: str, port: int) -> None:
    """Serve the already-created app via Gunicorn (single worker, 2 threads).

    A single worker keeps one process — and therefore one shared database
    connection pool — for the whole instance. ``run.py`` is the Gunicorn entry
    point too (``gunicorn run:app``), so config stays identical either way.
    Falls back to the built-in server when Gunicorn is unavailable (Gunicorn
    does not run on Windows; Render uses Linux and always takes this path).
    """
    try:
        from gunicorn.app.base import BaseApplication
    except ImportError:
        app.run(host=host, port=port, debug=False)
        return

    class _GunicornServer(BaseApplication):
        def __init__(self, wsgi_app, options):
            self._wsgi_app = wsgi_app
            self._options = options
            super().__init__()

        def load_config(self):
            for key, value in self._options.items():
                if key in self.cfg.settings and value is not None:
                    self.cfg.set(key.lower(), value)

        def load(self):
            return self._wsgi_app

    _GunicornServer(
        app,
        {
            "bind": f"{host}:{port}",
            "workers": 1,
            "threads": 2,
            "timeout": 120,
            "accesslog": "-",
            "errorlog": "-",
        },
    ).run()


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))

    if app.config.get("DEBUG", False):
        if not os.environ.get("WERKZEUG_RUN_MAIN") and not os.environ.get("RENDER_INSTANCE_ID"):
            threading.Thread(target=_open_landing_page, args=(port,), daemon=True).start()
        app.run(host=host, port=port, debug=True)
    else:
        _serve_with_gunicorn(host, port)