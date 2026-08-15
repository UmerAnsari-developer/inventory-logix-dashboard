"""User wrapper that adapts psycopg2 RealDictRow to Flask-Login's user API."""
from __future__ import annotations

from flask_login import UserMixin


class UserProxy(UserMixin):
    """Wrap a database row so Flask-Login + our code can treat it as an object."""

    # Tell UserMixin to use our explicit get_id
    def __init__(self, row: dict | None):
        self._row = row or {}

    # Explicit overrides so UserMixin lookups don't fall through to __getattr__
    @property
    def is_active(self) -> bool:
        return bool(self._row.get("is_active", True))

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_id(self) -> str:
        return str(self._row.get("id"))

    # Allow dict-like access (e.g., for templates)
    def get(self, key, default=None):
        return self._row.get(key, default)

    def __getitem__(self, key):
        return self._row[key]

    def __contains__(self, key):
        return key in self._row

    def __getattr__(self, item):
        if item.startswith("_"):
            raise AttributeError(item)
        try:
            return self._row[item]
        except KeyError:
            raise AttributeError(item)

    def to_dict(self) -> dict:
        return dict(self._row)
