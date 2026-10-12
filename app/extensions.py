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


def get_rate_limit_key() -> str:
    """Rate-limit key: the client IP as seen by the app.

    ProxyFix(x_for=1) is installed at app startup when TRUST_PROXY=on and
    already rewrites ``remote_addr`` to the trusted X-Forwarded-For hop
    (werkzeug uses values[-trusted], the LAST entry — the only one the
    proxy vouches for). Never read the raw XFF header here: the FIRST hop
    is client-controlled and would let an attacker rotate unlimited
    rate-limit buckets.
    """
    return get_remote_address()


# storage backend comes from Config.RATELIMIT_STORAGE_URI via app.config —
# no storage_uri kwarg here (it would shadow flask-limiter's config lookup).
limiter = Limiter(
    key_func=get_rate_limit_key,
    default_limits=["200 per minute"],
)