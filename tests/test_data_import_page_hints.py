"""Phase 1 #6 import-page hints + #4/#5 preview report UI.

Renders ``/admin/data-import/?tab=<entity>`` for every entity and asserts the
page teaches the real CSV contract:

- every canonical column from ``DataImportService.IMPORT_GUIDE`` is shown;
- natural keys are labelled as such;
- functional aliases (target in ``EXPECTED_COLUMNS``) are documented, and the
  non-functional ``email -> contact_email`` mapping is not offered;
- the create-missing policy is explained on products / purchase orders only;
- the limits strip states the size, display and preview-validation caps.

Template-source checks pin the new preview sections (matches / duplicates) and
their JS wiring (textContent only, hidden on zero count and every error path).

No production code here: a failure means the UI has not been written yet.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from flask_login.utils import _create_identifier

from app.repositories import UserRepository
from app.services import DataImportService

TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "app" / "templates" / "admin" / "data_import" / "index.html"
)

ENTITIES = tuple(DataImportService.IMPORT_GUIDE)

PREVIEW_SECTION_IDS = (
    "preview_matches",
    "preview_match_badge",
    "preview_match_list",
    "preview_duplicates",
    "preview_duplicate_badge",
    "preview_duplicate_list",
)


def _session_client(app, username: str = "admin"):
    """Authenticated test client without hitting the /auth/login rate limiter."""
    with app.app_context():
        user = UserRepository.find_by_username(username)
        assert user is not None, f"missing user {username}"
        uid = user.id

    c = app.test_client()
    ident_box: dict = {}

    def _capture_ident():
        ident_box["id"] = _create_identifier()

    app.before_request_funcs.setdefault(None, []).append(_capture_ident)
    try:
        resp = c.get("/static/img/favicon.svg")
        assert resp.status_code == 200, "identifier probe request failed"
    finally:
        app.before_request_funcs[None].remove(_capture_ident)
    assert "id" in ident_box, "failed to capture session identifier"

    with c.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
        sess["_id"] = ident_box["id"]
    return c


@pytest.fixture
def admin_client(app):
    return _session_client(app, "admin")


def _page(admin_client, entity: str) -> str:
    resp = admin_client.get(f"/admin/data-import/?tab={entity}")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def _functional_aliases(entity: str) -> dict[str, str]:
    """Alias -> target pairs that actually resolve for this entity."""
    expected = DataImportService.EXPECTED_COLUMNS[entity]
    return {
        alias: target
        for alias, target in DataImportService.COLUMN_ALIASES.get(entity, {}).items()
        if target in expected
    }


# ══════════════════════════════════════════════════════════════════════
# Canonical columns / natural keys
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("entity", ENTITIES)
def test_every_canonical_column_is_rendered(admin_client, entity):
    html = _page(admin_client, entity)
    for column in DataImportService.IMPORT_GUIDE[entity]["columns"]:
        assert f"<code>{column}</code>" in html, \
            f"{entity}: canonical column {column!r} not on page"


@pytest.mark.parametrize("entity", ENTITIES)
def test_natural_keys_are_labelled(admin_client, entity):
    html = _page(admin_client, entity)
    for key in DataImportService.IMPORT_GUIDE[entity]["natural_keys"]:
        row = re.search(
            rf"<tr>.*?<code>{re.escape(key)}</code>.*?</tr>", html, re.S
        )
        assert row and "natural key" in row.group(0).lower(), \
            f"{entity}: natural key {key!r} not labelled on its row"


def test_products_guide_uses_supplier_name_not_legacy_required_sentence(admin_client):
    html = _page(admin_client, "products")

    assert "supplier_name" in html
    # The old copy demanded the alias/legacy column and hid the real one.
    assert "CSV must have columns: sku, product_name" not in html
    assert "CSV must have columns" not in html

    # supplier_id may survive only as an alias note, never as a required column.
    low = html.lower()
    for match in re.finditer(re.escape("supplier_id"), low):
        context = low[max(0, match.start() - 300): match.end() + 300]
        assert any(
            hint in context
            for hint in ("alias", "accepted", "accepts", "legacy", "alternative", "synonym")
        ), "supplier_id is presented as a required column, not an alias"


def test_purchase_orders_guide_shows_natural_key_columns(admin_client):
    html = _page(admin_client, "purchase_orders")
    assert "supplier_name" in html
    assert "product_sku" in html


def test_movements_guide_shows_natural_key_columns(admin_client):
    html = _page(admin_client, "movements")
    assert "product_sku" in html
    assert "movement_type" in html


# ══════════════════════════════════════════════════════════════════════
# Alias notes
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("entity", ENTITIES)
def test_functional_aliases_are_documented(admin_client, entity):
    html = _page(admin_client, entity)
    aliases = _functional_aliases(entity)
    assert aliases, f"{entity}: expected at least one functional alias"
    for alias, target in aliases.items():
        assert alias in html, f"{entity}: alias {alias!r} not documented"
        assert target in html, f"{entity}: alias target {target!r} not documented"


def test_contact_email_alias_is_not_offered(admin_client):
    html = _page(admin_client, "suppliers")
    # suppliers has no contact_email column, so the alias must not be shown.
    assert "contact_email" not in html


# ══════════════════════════════════════════════════════════════════════
# Create-missing policy copy
# ══════════════════════════════════════════════════════════════════════

def test_products_page_explains_null_supplier_default(admin_client):
    html = _page(admin_client, "products")
    assert "create missing" in html.lower()
    assert "null" in html.lower(), "products copy must mention the NULL supplier default"


def test_purchase_orders_page_explains_row_skip_default(admin_client):
    html = _page(admin_client, "purchase_orders")
    assert "create missing" in html.lower()
    assert "skip" in html.lower(), "purchase orders copy must mention the skipped default"


@pytest.mark.parametrize("entity", ["suppliers", "warehouses", "movements"])
def test_create_missing_policy_not_claimed_elsewhere(admin_client, entity):
    html = _page(admin_client, entity)
    assert "create missing" not in html.lower()


# ══════════════════════════════════════════════════════════════════════
# Limits strip
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("entity", ENTITIES)
def test_limits_strip_states_all_caps(admin_client, entity):
    html = _page(admin_client, entity)
    assert "5 MB" in html
    assert "50 rows" in html          # display cap
    assert "10,000" in html           # preview validation cap


# ══════════════════════════════════════════════════════════════════════
# Template source: preview report sections + JS wiring
# ══════════════════════════════════════════════════════════════════════

def _script_source() -> str:
    src = TEMPLATE.read_text(encoding="utf-8")
    assert "{% block scripts %}" in src, "template lost its scripts block"
    return src.split("{% block scripts %}", 1)[1]


def _hide_assignments(region: str, stem: str) -> int:
    """Count ``...<stem>....style.display = 'none'`` statements in a region."""
    pattern = re.compile(
        rf"[^\n;]*{stem}[^\n;]*\.style\.display\s*=\s*['\"]none['\"]", re.I
    )
    return len(pattern.findall(region))


def _region(script: str, marker: str, before: int = 800, after: int = 1200) -> str:
    idx = script.index(marker)
    return script[max(0, idx - before): idx + after]


def test_template_has_preview_report_sections():
    src = TEMPLATE.read_text(encoding="utf-8")
    for element_id in PREVIEW_SECTION_IDS:
        assert f'id="{element_id}"' in src, f"missing preview section #{element_id}"


def test_preview_js_reads_match_and_duplicate_payloads():
    script = _script_source()
    for key in ("fk_matches", "fk_match_count", "duplicates", "duplicate_count"):
        assert key in script, f"preview JS never reads {key!r}"


@pytest.mark.parametrize(
    ("marker", "stem"),
    [("fk_matches", "match"), ("duplicates", "duplicate")],
)
def test_preview_js_renders_with_text_content(marker, stem):
    script = _script_source()
    assert marker in script, f"preview JS never reads {marker!r}"

    window = script[script.index(marker): script.index(marker) + 2500]
    assert "textContent" in window, f"{marker} list must be rendered with textContent"
    # No HTML injection: innerHTML may only be cleared, never assigned data.
    assert re.search(r"\.innerHTML\s*=\s*(?!['\"]{2})", window) is None, (
        f"{marker} rendering must not assign innerHTML"
    )


@pytest.mark.parametrize("stem", ["match", "duplicate"])
def test_preview_js_hides_sections_on_every_failure_path(stem):
    script = _script_source()

    paths = {
        "401/403": _region(script, "response.status === 401", before=0, after=1200),
        "success=false": _region(script, "Preview failed"),
        "catch": _region(script, ".catch(function(err)", before=0, after=1200),
    }
    for path, region in paths.items():
        assert _hide_assignments(region, stem) >= 1, (
            f"{stem} section is not hidden in the {path} branch"
        )

    # Zero-count hides live in the success path: 3 failure branches + 1 zero
    # check = at least 4 hide statements for each section.
    assert _hide_assignments(script, stem) >= 4, (
        f"{stem} section is not hidden on zero count"
    )


def test_template_keeps_existing_import_invariants():
    src = TEMPLATE.read_text(encoding="utf-8")
    assert 'name="create_missing" value="true"' in src
    assert 'id="create_missing_{{ active_tab }}"' in src
    assert "cmInput.name = 'create_missing'" in src
    assert "data-confirm" in src
    assert "csrf_token" in src
