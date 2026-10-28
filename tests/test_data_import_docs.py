"""Phase 1 #9 documentation contract for ``docs/data-import.md``.

These tests are a content spec, not a style guide: they assert that every
canonical column and functional alias from ``DataImportService`` is documented,
plus the FK-match, duplicate, create-missing, limits and result-shape semantics
the UI and importers actually implement.

No production code here: a failure means the doc has not been written yet.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services import DataImportService

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "data-import.md"

ENTITIES = tuple(DataImportService.IMPORT_GUIDE)


def _doc_text() -> str:
    assert DOCS.is_file(), f"missing {DOCS}"
    return DOCS.read_text(encoding="utf-8")


def _functional_aliases(entity: str) -> dict[str, str]:
    expected = DataImportService.EXPECTED_COLUMNS[entity]
    return {
        alias: target
        for alias, target in DataImportService.COLUMN_ALIASES.get(entity, {}).items()
        if target in expected
    }


def test_docs_file_exists():
    assert DOCS.is_file()


# ══════════════════════════════════════════════════════════════════════
# Columns and aliases
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("entity", ENTITIES)
def test_docs_list_every_canonical_column(entity):
    text = _doc_text()
    for column in DataImportService.IMPORT_GUIDE[entity]["columns"]:
        assert column in text, f"{entity}: canonical column {column!r} undocumented"


@pytest.mark.parametrize("entity", ENTITIES)
def test_docs_list_every_functional_alias(entity):
    text = _doc_text()
    aliases = _functional_aliases(entity)
    assert aliases, f"{entity}: expected at least one functional alias"
    for alias, target in aliases.items():
        assert alias in text, f"{entity}: alias {alias!r} undocumented"
        assert target in text, f"{entity}: alias target {target!r} undocumented"


def test_docs_never_present_contact_email_as_supported():
    # suppliers has no contact_email column; if it is mentioned at all it must
    # be explicitly unsupported, never offered as a working alias target.
    for line in _doc_text().splitlines():
        if "contact_email" in line:
            low = line.lower()
            assert any(
                hint in low for hint in ("not ", "no ", "unsupported", "never", "ignored")
            ), f"contact_email presented as supported: {line!r}"


# ══════════════════════════════════════════════════════════════════════
# FK match semantics (Phase 1 #4)
# ══════════════════════════════════════════════════════════════════════

def test_docs_explain_exact_normalized_and_numeric_fk_matches():
    text = _doc_text().lower()
    assert "fk_normalized_match" in text
    assert "fk_numeric_match" in text
    assert "exact" in text
    assert "normalized" in text
    assert "numeric" in text
    # Exact matches are compared against the spelling stored in the DB.
    assert "stored" in text


# ══════════════════════════════════════════════════════════════════════
# Duplicate semantics (Phase 1 #5)
# ══════════════════════════════════════════════════════════════════════

def test_docs_explain_duplicate_semantics():
    text = _doc_text().lower()
    assert "duplicate_count" in text
    assert "distinct" in text            # duplicate_count counts distinct groups
    assert "already" in text and "skip" in text   # suppliers/warehouses exact repeats
    assert "update" in text              # products exact repeats update earlier row
    assert "case" in text and "separate" in text  # case variants become new rows
    assert any(
        phrase in text
        for phrase in (
            "not flagged", "never flagged", "no duplicate",
            "no in-file duplicate", "not checked",
        )
    ), "doc must state movements/purchase orders have no duplicate semantics"


# ══════════════════════════════════════════════════════════════════════
# Create-missing policy
# ══════════════════════════════════════════════════════════════════════

def test_docs_explain_create_missing_policy():
    text = _doc_text().lower()
    assert "create missing" in text
    assert "products" in text and "purchase orders" in text   # only these two
    assert "150" in text                 # VARCHAR(150) supplier-name limit
    assert "null" in text                # products fall back to NULL supplier
    assert "skip" in text                # purchase orders skip the row
    assert "soft" in text and "deleted" in text   # soft-deleted name reuse


# ══════════════════════════════════════════════════════════════════════
# Limits / truncation
# ══════════════════════════════════════════════════════════════════════

def test_docs_document_limits_and_truncation():
    text = _doc_text()
    assert "5 MB" in text
    assert "**50**" in text              # preview display cap
    assert "**10,000**" in text          # preview validation cap
    assert "rows_truncated" in text      # truncation flag


# ══════════════════════════════════════════════════════════════════════
# Import result shape and flash budget
# ══════════════════════════════════════════════════════════════════════

def test_docs_document_import_result_shape():
    text = _doc_text()
    for key in ("imported", "skipped", "errors", "error_counts"):
        assert key in text, f"import result key {key!r} undocumented"
    assert "200" in text                 # retained per-row error entries
    assert "flash" in text               # flash budget is documented


def test_docs_document_flash_line_budget():
    text = _doc_text()
    assert re.search(r"(?<![\d,])10(?![\d,])", text), "10-line flash budget undocumented"
    assert "error_counts" in text        # grouped tail comes from full tallies
    assert "grouped" in text.lower() or "tail" in text.lower()


# ══════════════════════════════════════════════════════════════════════
# Preview-only caveat
# ══════════════════════════════════════════════════════════════════════

def test_docs_warn_that_direct_uploads_bypass_preview_reports():
    text = _doc_text().lower()
    assert "direct" in text
    assert "duplicate" in text
    assert "normaliz" in text
    assert any(
        hint in text for hint in ("bypass", "without preview", "skip the preview", "not run")
    ), "doc must state direct uploads bypass preview normalization/duplicate reporting"


# ══════════════════════════════════════════════════════════════════════
# README entry point
# ══════════════════════════════════════════════════════════════════════

def test_readme_links_to_data_import_docs():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/data-import.md" in readme
