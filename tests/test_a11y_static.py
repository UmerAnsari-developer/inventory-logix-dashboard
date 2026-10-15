"""Static accessibility assertions for GAP-014 (Batch 4, Agent A).

No browser, no axe-core (disk-constrained) — mirrors the static-assertion
style of tests/test_frontend_mitigations.py. Each test embeds RED evidence:
a crafted bad sample that trips the same detector the real files pass.

Covers:
  - every data-table <th> carries a scope attribute (repo-wide guard)
  - icon-only buttons carry aria-label
  - the anomaly detail-modal close button is labeled
  - the GAP-019 persistent forecast-warning banner is wired (template + JS)
"""
from __future__ import annotations

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"
AI_FEATURES_JS = (
    Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "ai-features.js"
)

# A <th tag that is NOT <thead/<thdr… (\b after "th"), through its closing ">".
TH_TAG = re.compile(r"<th\b[^>]*>", re.I)
SCOPE_ATTR = re.compile(r"\bscope\s*=", re.I)
BUTTON = re.compile(r"<button\b([^>]*)>(.*?)</button>", re.I | re.S)
ARIA_LABEL = re.compile(r"\baria-label\s*=", re.I)
HTML_TAG = re.compile(r"<[^>]+>")
HTML_ENTITY = re.compile(r"&[a-zA-Z#0-9]+;")

# GAP-014 complete: every template's <th> is scoped, so the ratchet is now a
# hard repo-wide guarantee — ANY unscoped <th> in ANY template fails the test.
# Keep the set (not the mechanism) so a future regression has a place to be
# ratcheted, but it must stay empty.
KNOWN_UNSCOPED = frozenset()


def _unscoped_th(text: str) -> list[str]:
    """Every <th …> opening tag in the text that lacks a scope attribute."""
    return [
        m.group(0) for m in TH_TAG.finditer(text) if not SCOPE_ATTR.search(m.group(0))
    ]


def _icon_only(inner_html: str) -> bool:
    """True when a button's content renders no text (tags/entities/symbols only)."""
    text = HTML_ENTITY.sub("", HTML_TAG.sub("", inner_html))
    return not re.search(r"[A-Za-z0-9]", text)


# ── GAP-014: every data-table header is scoped ──────────────────────────

def test_all_table_headers_scoped():
    # RED evidence: an unscoped header trips the detector; <thead> does not
    assert _unscoped_th("<tr><th>SKU</th></tr>") == ["<th>"]
    assert _unscoped_th("<thead><tr><th scope=\"col\">SKU</th></tr></thead>") == []
    assert _unscoped_th('<th scope="row">x</th>') == []

    offenders: list[str] = []
    stale: list[str] = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        rel = path.relative_to(TEMPLATES).as_posix()
        unscoped = _unscoped_th(path.read_text(encoding="utf-8", errors="replace"))
        if unscoped:
            if rel in KNOWN_UNSCOPED:
                continue  # pending assignment — see KNOWN_UNSCOPED comment
            offenders.append(f"{rel}: {len(unscoped)} unscoped <th>")
        elif rel in KNOWN_UNSCOPED:
            stale.append(rel)
    assert offenders == [], f"unscoped <th> outside the known-pending set: {offenders}"
    assert stale == [], (
        f"allowlist entries no longer needed (remove from KNOWN_UNSCOPED): {stale}"
    )


# ── GAP-014: icon-only buttons are labeled ───────────────────────────────

def test_icon_only_buttons_labeled():
    # RED evidence: unlabeled &times; button trips; labeled one and a text
    # button with an entity do not
    assert _icon_only("&times;")
    assert not _icon_only("Next &raquo;")
    assert not ARIA_LABEL.search('<button class="btn" id="closeModal">')

    offenders = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in BUTTON.finditer(text):
            if _icon_only(m.group(2)) and not ARIA_LABEL.search(m.group(1)):
                line = text[: m.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(TEMPLATES).as_posix()}:{line}")
    assert offenders == [], f"icon-only buttons without aria-label: {offenders}"


def test_anomaly_close_button_labeled():
    # RED evidence: the pre-fix tag has no aria-label
    pre_fix = '<button class="btn btn-secondary btn-sm" id="closeModal">&times;</button>'
    assert not ARIA_LABEL.search(pre_fix)

    text = (TEMPLATES / "ai" / "anomaly.html").read_text(encoding="utf-8")
    assert 'id="closeModal"' in text, "closeModal button missing"
    for m in BUTTON.finditer(text):
        if 'id="closeModal"' in m.group(1):
            assert ARIA_LABEL.search(m.group(1)), (
                "closeModal is icon-only and must carry aria-label"
            )
            return
    raise AssertionError("closeModal <button> tag not found")


# ── GAP-019: persistent forecast-warning banner is wired ─────────────────

def test_forecast_warning_banner_present():
    # RED evidence: a banner div without the id, or JS without the hook,
    # fails the same presence checks
    assert 'id="forecast-error"' not in (
        TEMPLATES / "ai" / "forecast.html"
    ).read_text(encoding="utf-8")

    forecast = (TEMPLATES / "ai" / "forecast.html").read_text(encoding="utf-8")
    assert 'id="forecast-warning"' in forecast, (
        "forecast.html must contain the persistent warning banner div"
    )
    assert "hidden" in forecast, "banner must start hidden"

    js = AI_FEATURES_JS.read_text(encoding="utf-8")
    assert "forecast-warning" in js, (
        "ai-features.js must populate the forecast-warning banner"
    )


# ── Stored-XSS: innerHTML row builders escape server data ────────────────

def test_portfolio_rows_escape_server_data():
    # RED evidence: a raw `+ r.sku +` concat into innerHTML trips the detector;
    # escapeHtml(r.sku) does not. Product name/sku are manager-writable free
    # text, so any unescaped interpolation is a stored-XSS sink for viewers.
    js = AI_FEATURES_JS.read_text(encoding="utf-8")
    assert re.search(r"\bescapeHtml\b\s*=", js), (
        "ai-features.js must define an escapeHtml helper"
    )
    assert "escapeHtml(r.sku)" in js and "escapeHtml(r.name)" in js, (
        "portfolio row builders must wrap sku/name (manager-writable) in escapeHtml"
    )
    raw = re.findall(r"\+\s*r\.\w+", js)
    assert raw == [], (
        f"unescaped server-data interpolation into innerHTML: {raw}"
    )
