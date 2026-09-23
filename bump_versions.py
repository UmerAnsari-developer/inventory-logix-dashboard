"""Rewrite ?v= cache-busters in templates to the asset file's md5[:8].

Usage:
    python bump_versions.py

Scans app/templates/**/*.html for local css/js references in two forms:
  (a) url_for('static', filename='css/x.css') }}?v=...
  (b) raw "/static/css/x.css" / "/static/js/x.js" strings (importmap entries)
and sets (or appends) ?v=<md5 hex[:8] of the asset file>. Idempotent.
CDN urls, images, fonts and inline code are never touched.
"""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "app" / "static"
TEMPLATES = ROOT / "app" / "templates"

# (a) url_for('static', filename='js/main.js') }}?v=1.5
_URL_FOR = re.compile(
    r"url_for\('static', filename='((?:css|js)/[^']+)'\)\s*\}\}(\?v=[^\"'\s>]+)?"
)
# (b) "/static/js/vendor/three.module.js" (importmap / raw paths)
_RAW = re.compile(
    r"['\"]/static/((?:css|js)/[^\"'\s?]+)(\?v=[^\"'\s}]+)?"
)
PATTERNS = (_URL_FOR, _RAW)


def asset_hash(filename: str) -> str:
    """md5 hex[:8] of the asset file for a css/X or js/X filename."""
    return hashlib.md5((STATIC / filename).read_bytes()).hexdigest()[:8]


def discover(template_text: str) -> list:
    """[(filename, ref)] for every local css/js asset reference found."""
    refs = []
    for pat in PATTERNS:
        refs.extend((m.group(1), m.group(0)) for m in pat.finditer(template_text))
    return refs


def rewrite(template_text: str) -> tuple:
    """Set/append ?v=<hash> on every local css/js ref.

    Returns (new_text, number_of_refs_updated). Idempotent.
    """
    edits = []  # (start, end, replacement) applied last-to-first
    for pat in PATTERNS:
        for m in pat.finditer(template_text):
            want = "?v=" + asset_hash(m.group(1))
            if m.group(2):
                if m.group(2) != want:
                    edits.append((m.start(2), m.end(2), want))
            else:
                edits.append((m.end(), m.end(), want))
    for start, end, repl in sorted(edits, key=lambda e: -e[0]):
        template_text = template_text[:start] + repl + template_text[end:]
    return template_text, len(edits)


def main() -> None:
    total = touched = 0
    for path in sorted(TEMPLATES.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        new_text, n = rewrite(text)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            total += n
            touched += 1
            print(f"  {path.relative_to(ROOT)}: {n} ref(s)")
    print(f"Updated {total} ref(s) across {touched} template(s)")


if __name__ == "__main__":
    main()
