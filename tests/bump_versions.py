"""Shared asset cache-bust helpers: discover() + asset_hash().

The version-bump workflow and tests/test_frontend_mitigations.py share
these so a broken implementation can't pass both sides of the same check.
"""
import hashlib
import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parent.parent / "app" / "static"

# {{ url_for('static', filename='css/style.css') }}?v=abc12345
_REF = re.compile(
    r"url_for\(\s*['\"]static['\"]\s*,\s*filename\s*=\s*['\"]([^'\"]+)['\"]\s*\)"
    r"\s*\}{1,2}\s*\?v=([0-9a-f]+)"
)


def discover(text):
    """[(filename, 'filename}}?v=hash'), ...] for every static ?v= ref."""
    return [(fn, f"{fn}}}?v={h}") for fn, h in _REF.findall(text)]


def asset_hash(fn):
    """md5[:8] of the asset's bytes — the cache-bust version."""
    return hashlib.md5((_STATIC / fn).read_bytes()).hexdigest()[:8]