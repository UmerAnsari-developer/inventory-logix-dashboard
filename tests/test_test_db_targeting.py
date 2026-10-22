"""Phase 0: the app under test must connect to the dedicated test database.

Read-only: only ``current_database()`` is queried, so a stale test DB fails
loudly instead of being mutated.
"""
from __future__ import annotations


def test_app_uses_the_test_database(app):
    expected = app.config["DB_NAME"]
    assert expected.endswith("_test")
    with app.app_context():
        from app.database.connection import get_cursor
        with get_cursor() as cur:
            cur.execute("SELECT current_database() AS db")
            assert cur.fetchone()["db"] == expected
