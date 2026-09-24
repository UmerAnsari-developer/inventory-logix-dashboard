"""Flask extension singletons shared across the application factory."""
from __future__ import annotations

from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"
login_manager.session_protection = "strong"

csrf = CSRFProtect()

# storage backend comes from Config.RATELIMIT_STORAGE_URI via app.config —
# no storage_uri kwarg here (it would shadow flask-limiter's config lookup).
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute"],
)
