"""F-V4: system-config edit/delete must write usable audit rows.

Pre-fix, both routes pass ``target_id_arg="key"`` with no ``detail_func``.
``audit_log.target_id`` is INTEGER, so inserting the string key raises
(DataError) inside the decorator's swallow-all handler — *no audit row at
all* is written. The fix records ``{"key": <path key>}`` in ``detail`` and
leaves ``target_id`` NULL. Config values are never recorded (secret-safety).
"""
from __future__ import annotations

import pytest

from app.database import get_cursor
from app.repositories import UserRepository

KEY = "RUN_ETL_ON_STARTUP"
# Include create: _ensure_override seeds the row via the create route, which
# writes its own audit rows that must not accumulate either.
ACTIONS = ("admin.config.create", "admin.config.update", "admin.config.delete")


@pytest.fixture
def admin_user_id(app):
    with app.app_context():
        admin = UserRepository.find_by_username("admin")
        assert admin is not None, "admin user must exist"
        return admin.id


@pytest.fixture
def config_guard(app):
    """Snapshot/restore the override row; delete only this test's audit rows."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute(
                "SELECT id, key, value, description, is_sensitive, updated_at, "
                "updated_by, deleted_at FROM system_config_overrides "
                "WHERE key = %s ORDER BY id",
                (KEY,),
            )
            before = [dict(r) for r in cur.fetchall()]
            # DB clock so the cutoff matches audit_log.created_at's clock.
            cur.execute("SELECT NOW() AS cutoff")
            cutoff = cur.fetchone()["cutoff"]
    yield {"before": before, "cutoff": cutoff}
    with app.app_context():
        with get_cursor(commit=True) as cur:
            if before:
                ids = [r["id"] for r in before]
                cur.execute(
                    "DELETE FROM system_config_overrides WHERE key = %s AND id <> ALL(%s)",
                    (KEY, ids),
                )
                for row in before:
                    cur.execute(
                        "UPDATE system_config_overrides SET value = %s, description = %s, "
                        "is_sensitive = %s, updated_at = %s, updated_by = %s, deleted_at = %s "
                        "WHERE id = %s",
                        (
                            row["value"], row["description"], row["is_sensitive"],
                            row["updated_at"], row["updated_by"], row["deleted_at"],
                            row["id"],
                        ),
                    )
            else:
                # The test created the row — remove it again.
                cur.execute(
                    "DELETE FROM system_config_overrides WHERE key = %s", (KEY,)
                )
            cur.execute(
                "DELETE FROM audit_log WHERE action = ANY(%s) "
                "AND detail->>'key' = %s AND created_at >= %s",
                (list(ACTIONS), KEY, cutoff),
            )


def _ensure_override(client):
    """Edit early-returns when the row is absent → seed it via the create route."""
    response = client.post(
        "/admin/system_config/create",
        data={"key": KEY, "value": "false", "description": "F-V4 test"},
    )
    assert response.status_code == 302


def _latest_audit_row(app, action, cutoff):
    # cutoff-scoped so a leftover row of the same action can't make the test vacuous
    with app.app_context():
        with get_cursor() as cur:
            cur.execute(
                "SELECT action, target_type, target_id, detail, user_id FROM audit_log "
                "WHERE action = %s AND created_at >= %s ORDER BY id DESC LIMIT 1",
                (action, cutoff),
            )
            return cur.fetchone()


def test_edit_records_audit_row_with_key_detail(app, auth_client, admin_user_id, config_guard):
    _ensure_override(auth_client)

    response = auth_client.post(f"/admin/system_config/edit/{KEY}", data={"value": "true"})
    assert response.status_code == 302

    row = _latest_audit_row(app, "admin.config.update", config_guard["cutoff"])
    assert row is not None, "config edit must write an audit row"

    assert row["target_type"] == "system_config"
    assert row["target_id"] is None
    assert row["detail"]["key"] == KEY
    assert "value" not in row["detail"], "config values must never enter the audit detail"
    assert row["user_id"] == admin_user_id


def test_delete_records_audit_row_with_key_detail(app, auth_client, admin_user_id, config_guard):
    _ensure_override(auth_client)

    response = auth_client.post(f"/admin/system_config/delete/{KEY}")
    assert response.status_code == 302

    row = _latest_audit_row(app, "admin.config.delete", config_guard["cutoff"])
    assert row is not None, "config delete must write an audit row"

    assert row["target_type"] == "system_config"
    assert row["target_id"] is None
    assert row["detail"]["key"] == KEY
    assert "value" not in row["detail"], "config values must never enter the audit detail"
    assert row["user_id"] == admin_user_id
