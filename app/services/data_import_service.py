"""Data import service with preview functionality."""
from __future__ import annotations

import csv
import difflib
import io
import logging
from typing import Any

_logger = logging.getLogger(__name__)

# Hard cap on rows parsed for a preview (bounds memory: ~10k dicts is a few MB).
# The full file is still imported; this only limits preview/validation work.
MAX_PREVIEW_ROWS = 10_000


class DataImportService:
    """Service for importing data with preview capability."""

    # Ordered import guide: one source of truth for each entity's canonical
    # headers, natural keys and short description (also shown in the UI).
    IMPORT_GUIDE = {
        "products": {
            "label": "Products",
            "columns": ("sku", "name", "unit_price", "current_stock", "reorder_point", "category", "supplier_name"),
            "natural_keys": ("sku", "supplier_name"),
            "description": "Product master data: one row per SKU with price, stock levels and supplier name.",
        },
        "suppliers": {
            "label": "Suppliers",
            "columns": ("supplier_name", "location", "lead_days"),
            "natural_keys": ("supplier_name",),
            "description": "Supplier master data: one row per supplier with location and lead time.",
        },
        "warehouses": {
            "label": "Warehouses",
            "columns": ("warehouse_name", "location"),
            "natural_keys": ("warehouse_name",),
            "description": "Warehouse master data: one row per warehouse with its location.",
        },
        "movements": {
            "label": "Movements",
            "columns": ("product_sku", "quantity", "movement_type", "reason"),
            "natural_keys": ("product_sku",),
            "description": "Stock movements: one row per IN/OUT/ADJUSTMENT/RETURN event on an existing product SKU.",
        },
        "purchase_orders": {
            "label": "Purchase Orders",
            "columns": ("supplier_name", "product_sku", "quantity", "status"),
            "natural_keys": ("supplier_name", "product_sku"),
            "description": "Purchase orders: one row per supplier/product order line.",
        },
    }

    # Expected columns for each entity (lowercase) — matches the real schema:
    # suppliers has NO contact_email/phone/address columns.
    # Derived from IMPORT_GUIDE so there is one source of truth.
    EXPECTED_COLUMNS = {
        entity: set(spec["columns"]) for entity, spec in IMPORT_GUIDE.items()
    }

    # Column aliases for flexible matching
    COLUMN_ALIASES = {
        "products": {
            "product_name": "name",
            "price": "unit_price",
            "stock": "current_stock",
            "reorder": "reorder_point",
            "supplier": "supplier_name",
            "supplier_id": "supplier_name",      # backward compat
        },
        "suppliers": {
            "name": "supplier_name",
            "email": "contact_email",
        },
        "warehouses": {
            "name": "warehouse_name",
        },
        "movements": {
            "qty": "quantity",
            "type": "movement_type",
            "product_id": "product_sku",         # backward compat
        },
        "purchase_orders": {
            "qty": "quantity",
            "supplier_id": "supplier_name",      # backward compat
            "product_id": "product_sku",         # backward compat
        },
    }

    # Natural-key fields checked for duplicates inside one CSV preview.
    # Products/suppliers/warehouses only: movements and purchase orders have
    # no in-file duplicate semantics (every row is its own event/order line).
    DUPLICATE_KEY_FIELDS: dict[str, tuple[str, ...]] = {
        "products": ("sku",),
        "suppliers": ("supplier_name",),
        "warehouses": ("warehouse_name",),
    }

    @staticmethod
    def _normalize_key(value: str) -> str:
        """Normalize for case-insensitive, whitespace-tolerant matching."""
        return value.strip().lower() if isinstance(value, str) else ""

    @staticmethod
    def _fk_rows(cur, entity: str) -> list[dict]:
        """Bulk-load active natural keys with id + stored spelling.

        ``ORDER BY id`` makes case-collision resolution deterministic (the
        highest id wins) and identical for preview and import caches.
        """
        queries = {
            "suppliers": (
                "SELECT id, LOWER(TRIM(name)) AS norm_key, name AS stored "
                "FROM suppliers WHERE deleted_at IS NULL ORDER BY id"
            ),
            "products": (
                "SELECT id, LOWER(TRIM(sku)) AS norm_key, sku AS stored "
                "FROM products WHERE deleted_at IS NULL ORDER BY id"
            ),
            "warehouses": (
                "SELECT id, LOWER(TRIM(warehouse_name)) AS norm_key, "
                "warehouse_name AS stored FROM warehouses ORDER BY id"
            ),
        }
        sql = queries.get(entity)
        if sql is None:
            return []
        cur.execute(sql)
        return cur.fetchall()

    @staticmethod
    def _build_fk_cache(cur, entity: str) -> dict[str, int]:
        """Bulk-load all active natural keys -> IDs for an entity."""
        return {
            row["norm_key"]: row["id"]
            for row in DataImportService._fk_rows(cur, entity)
        }

    @staticmethod
    def build_fk_caches(cur) -> dict[str, dict[str, int]]:
        """Bulk-load FK caches for every entity used as a natural-key target.

        Thin helper so the entity-to-query map lives in one place; preview
        validation and import both consume the same cache shape.
        """
        return {
            "suppliers": DataImportService._build_fk_cache(cur, "suppliers"),
            "products": DataImportService._build_fk_cache(cur, "products"),
        }

    @staticmethod
    def build_fk_stored_values(cur) -> dict[str, dict[str, str]]:
        """Bulk-load normalized natural key -> stored spelling (active rows).

        Same entity set as :meth:`build_fk_caches`. Lets the preview report a
        case/whitespace-only FK match against the spelling actually stored in
        the DB instead of only flagging it as normalized.
        """
        return {
            entity: {
                row["norm_key"]: row["stored"]
                for row in DataImportService._fk_rows(cur, entity)
            }
            for entity in ("suppliers", "products")
        }

    @staticmethod
    def build_fk_preview_data(
        cur,
    ) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, str]]]:
        """Build id + stored-spelling maps in one scan per entity."""
        caches: dict[str, dict[str, int]] = {}
        stored: dict[str, dict[str, str]] = {}
        for entity in ("suppliers", "products"):
            rows = DataImportService._fk_rows(cur, entity)
            caches[entity] = {row["norm_key"]: row["id"] for row in rows}
            stored[entity] = {row["norm_key"]: row["stored"] for row in rows}
        return caches, stored

    # Natural-key fields checked per entity at preview time.
    # Tuple shape: (csv field, cache key, error_code, action phrase,
    # numeric-id fallback allowed). The action phrase matches what the
    # importers actually do with an unresolved key (see
    # app/routes/admin/data_import_routes.py): products are still imported
    # with a NULL supplier, movements/purchase-orders rows are skipped.
    # numeric-id fallback: a bare decimal value matching an existing id
    # (cache values = active rows only) resolves at import for every FK
    # field below — legacy CSVs that carry ids in natural-key columns.
    FK_CHECK_FIELDS: dict[str, list[tuple[str, str, str, str, bool]]] = {
        "products": [
            ("supplier_name", "suppliers", "fk_supplier_not_found", "imported without supplier", True),
        ],
        "movements": [
            ("product_sku", "products", "fk_product_not_found", "skipped", True),
        ],
        "purchase_orders": [
            ("supplier_name", "suppliers", "fk_supplier_not_found", "skipped", True),
            ("product_sku", "products", "fk_product_not_found", "skipped", True),
        ],
    }

    # FK fields the opt-in create-missing import may auto-create.
    # Suppliers only: a bare SKU is no natural name for a product, so products
    # can never be auto-created this way.
    CREATABLE_FK_FIELDS: dict[str, set[str]] = {
        "products": {"supplier_name"},
        "purchase_orders": {"supplier_name"},
    }

    @staticmethod
    def validate_fk_rows(
        rows: list[dict], entity: str, fk_caches: dict[str, dict[str, int]],
        create_missing: bool = False,
    ) -> list[dict[str, Any]]:
        """Validate natural-key FK references in CSV rows against pre-built caches.

        Pure function (no DB access); callers pass caches built by
        :meth:`build_fk_caches`. Resolution semantics mirror the importers in
        ``app/routes/admin/data_import_routes.py`` exactly so preview warnings
        predict import outcomes:

        - Empty/None values are skipped (the importer also skips them).
        - Existence-checked numeric-ID fallback: a bare decimal value matching
          an existing id (cache values = active rows only) resolves at import —
          movements ``product_sku``, products/PO ``supplier_name`` and PO
          ``product_sku``. A numeric reference to a soft-deleted row therefore
          warns here too (import skips it / NULL-links the supplier), since
          both sides resolve against the same active-only caches.
        - Products with an unknown supplier are STILL imported with
          ``supplier_id`` NULL; movements/purchase-orders rows are skipped.
        - ``create_missing=True`` (opt-in import checkbox): misses on fields in
          :data:`CREATABLE_FK_FIELDS` are NOT warned — the import auto-creates
          the supplier instead. Names longer than the VARCHAR(150) limit keep
          their warning (the INSERT would reject them, so the row still ends
          up imported without a supplier / skipped). Unarmed behavior is
          unchanged.

        Known heuristic limitations (documented, acceptable):
        - Products: an unknown supplier warns even when sku/name are blank
          and the importer would skip the whole row — acceptable heuristic.

        Returns NON-BLOCKING warnings; each has row (1-based), field, value,
        error_code, severity and a human-readable message.
        """
        checks = DataImportService.FK_CHECK_FIELDS.get(entity, [])
        if not checks:
            return []

        creatable = DataImportService.CREATABLE_FK_FIELDS.get(entity, set())

        # Precompute existing-id sets for the numeric-ID fallback (movements).
        id_sets = {key: set(cache.values()) for key, cache in fk_caches.items()}

        warnings: list[dict[str, Any]] = []
        for idx, row in enumerate(rows, start=1):
            for field, cache_key, error_code, action, allow_numeric in checks:
                raw = row.get(field)
                if raw is None:
                    continue
                value = raw if isinstance(raw, str) else str(raw)
                if not value.strip():
                    continue  # importer also skips empty values
                cache = fk_caches.get(cache_key) or {}
                norm = DataImportService._normalize_key(value)
                if norm in cache:
                    continue
                if allow_numeric and norm.isdecimal() and int(norm) in id_sets.get(cache_key, set()):
                    # Existence-checked numeric-ID fallback (legacy CSVs that
                    # carry ids in natural-key columns): a bare decimal that
                    # matches an existing active id resolves at import.
                    # isdecimal() (not isdigit()): "²".isdigit() is True but
                    # int("²") raises — isdecimal treats it as a natural key,
                    # so preview warns. Runs BEFORE create_missing so an
                    # existing id is never reported as "will create".
                    # Movements' IMPORT side keeps its .isdigit() quirk ("²"
                    # -> invalid_number there); do NOT change import behavior.
                    continue
                if create_missing and field in creatable and len(value.strip()) <= 150:
                    # Armed: auto-created at import — except names over
                    # VARCHAR(150), which the INSERT cannot store; those keep
                    # the honest not-found warning.
                    continue
                warnings.append({
                    "row": idx,
                    "field": field,
                    "value": value,
                    "error_code": error_code,
                    "severity": "warning",
                    "message": f"Row {idx}: {field} '{value}' not found — row will be {action}",
                })
        return warnings

    @staticmethod
    def classify_fk_matches(
        rows: list[dict], entity: str, fk_caches: dict[str, dict[str, int]],
        fk_stored: dict[str, dict[str, str]] | None = None,
        raw_rows: list[dict] | None = None,
        display_cap: int = 50,
    ) -> dict[str, Any]:
        """Report FK field cells that resolve only via normalization.

        Pure (no DB). Same field set and resolution order as
        :meth:`validate_fk_rows` (natural key first, then the existence-checked
        numeric-ID fallback), but non-blocking and informational only:

        - ``exact``: the raw cell equals the spelling stored in the DB — counted,
          never listed (nothing to fix).
        - ``normalized``: the natural key matched after case/whitespace
          normalization — listed with the raw cell so the user can see the drift.
        - ``numeric_id``: a bare decimal resolved as an existing active id.

        ``raw_rows`` (optional, 1:1 with ``rows``) supplies the pre-strip cell
        so surrounding whitespace is visible; otherwise the stripped row value
        is reported. The list is capped at ``display_cap``; all counts are not.

        Returns {"matches", "match_count", "exact_count", "normalized_count",
        "numeric_count"} where exact + normalized + numeric == match_count.
        """
        result = {
            "matches": [],
            "match_count": 0,
            "exact_count": 0,
            "normalized_count": 0,
            "numeric_count": 0,
        }
        checks = DataImportService.FK_CHECK_FIELDS.get(entity, [])
        if not checks:
            return result

        stored_by_cache = fk_stored or {}
        id_sets = {key: set(cache.values()) for key, cache in fk_caches.items()}
        matches: list[dict[str, Any]] = []
        exact = normalized = numeric = 0

        for idx, row in enumerate(rows):
            row_no = idx + 1
            raw_row = raw_rows[idx] if raw_rows is not None and idx < len(raw_rows) else None
            for field, cache_key, _error_code, _action, allow_numeric in checks:
                value = row.get(field)
                if value is None:
                    continue
                value = value if isinstance(value, str) else str(value)
                stripped = value.strip()
                if not stripped:
                    continue
                raw_value = stripped
                if raw_row is not None:
                    raw = raw_row.get(field)
                    if raw is not None:
                        raw_value = raw if isinstance(raw, str) else str(raw)
                norm = DataImportService._normalize_key(stripped)
                cache = fk_caches.get(cache_key) or {}
                if norm in cache:
                    stored = (stored_by_cache.get(cache_key) or {}).get(norm)
                    if stored is not None and raw_value == stored:
                        exact += 1
                        continue
                    normalized += 1
                    if len(matches) < display_cap:
                        matches.append({
                            "row": row_no,
                            "field": field,
                            "raw_value": raw_value,
                            "normalized_value": norm,
                            "match_type": "normalized",
                            "error_code": "fk_normalized_match",
                            "severity": "info",
                            "message": (
                                f"Row {row_no}: {field} '{raw_value}' -> '{norm}' (matched)"
                            ),
                        })
                    continue
                if allow_numeric and stripped.isdecimal() and int(stripped) in id_sets.get(cache_key, set()):
                    numeric += 1
                    if len(matches) < display_cap:
                        target = "supplier" if cache_key == "suppliers" else "product"
                        matches.append({
                            "row": row_no,
                            "field": field,
                            "raw_value": raw_value,
                            "normalized_value": norm,
                            "match_type": "numeric_id",
                            "error_code": "fk_numeric_match",
                            "severity": "info",
                            "message": (
                                f"Row {row_no}: {field} '{raw_value}' resolved as "
                                f"existing {target} id {int(stripped)}"
                            ),
                        })

        result["matches"] = matches
        result["exact_count"] = exact
        result["normalized_count"] = normalized
        result["numeric_count"] = numeric
        result["match_count"] = exact + normalized + numeric
        return result

    @staticmethod
    def detect_duplicates(
        rows: list[dict], entity: str, display_cap: int = 50
    ) -> dict[str, Any]:
        """Group repeated natural keys inside one CSV preview (non-blocking).

        Only entities in :data:`DUPLICATE_KEY_FIELDS` are checked. Values are
        stripped and grouped case-insensitively (internal whitespace is NOT
        collapsed). Groups with fewer than two occurrences are not duplicates.

        Each group mirrors the importer's real behavior: an exact repeat on
        products updates the earlier row; an exact repeat on suppliers /
        warehouses is skipped as already existing; case variants create
        separate rows. ``rows`` holds the later row numbers (capped at 50);
        ``duplicate_count`` counts distinct groups uncapped.
        """
        fields = DataImportService.DUPLICATE_KEY_FIELDS.get(entity)
        if not fields:
            return {"duplicates": [], "duplicate_count": 0}

        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for idx, row in enumerate(rows, start=1):
            for field in fields:
                raw = row.get(field)
                if raw is None:
                    continue
                value = raw if isinstance(raw, str) else str(raw)
                trimmed = value.strip()
                if not trimmed:
                    continue
                key = (field, DataImportService._normalize_key(trimmed))
                group = groups.get(key)
                if group is None:
                    groups[key] = {
                        "field": field,
                        "value": trimmed,
                        "spellings": [trimmed],
                        "rows": [idx],
                    }
                else:
                    group["spellings"].append(trimmed)
                    group["rows"].append(idx)

        noun = DataImportService.IMPORT_GUIDE.get(entity, {}).get("label", "rows").lower()
        duplicates: list[dict[str, Any]] = []
        duplicate_count = 0
        for group in groups.values():
            if len(group["rows"]) < 2:
                continue
            duplicate_count += 1
            if len(duplicates) >= display_cap:
                continue
            first = group["rows"][0]
            later = len(group["rows"]) - 1
            field = group["field"]
            is_exact = all(spelling == group["value"] for spelling in group["spellings"])
            if is_exact and entity in ("suppliers", "warehouses"):
                severity = "info"
                message = (
                    f"Row {first}: {field} '{group['value']}' is repeated on "
                    f"{later} later row(s) — later rows are skipped as already exists"
                )
            elif is_exact:
                severity = "warning"
                message = (
                    f"Row {first}: {field} '{group['value']}' is repeated on "
                    f"{later} later row(s) — later rows update the earlier product"
                )
            else:
                severity = "warning"
                later_spellings = group["spellings"][1:]
                exact_later = sum(
                    spelling == group["value"] for spelling in later_spellings
                )
                variant_count = len({
                    spelling for spelling in later_spellings
                    if spelling != group["value"]
                })
                if exact_later:
                    exact_outcome = (
                        "update the earlier product" if entity == "products"
                        else "are skipped as already exists"
                    )
                    message = (
                        f"Row {first}: {field} '{group['value']}' appears on {later} "
                        f"later row(s) — {exact_later} exact repeat(s) {exact_outcome}, "
                        f"{variant_count} distinct case variant spelling(s) "
                        f"create separate {noun}"
                    )
                else:
                    message = (
                        f"Row {first}: {field} '{group['value']}' appears on {later} "
                        f"later row(s) with different casing — {variant_count} distinct "
                        f"case variant spelling(s) create separate {noun}; repeated "
                        f"spellings follow the exact-repeat behavior"
                    )
            duplicates.append({
                "field": field,
                "value": group["value"],
                "kind": "exact" if is_exact else "variant",
                "row": first,
                "row_count": len(group["rows"]),
                "rows": group["rows"][1:1 + display_cap],
                "error_code": "duplicate_key",
                "severity": severity,
                "message": message,
            })

        return {"duplicates": duplicates, "duplicate_count": duplicate_count}

    @staticmethod
    def classify_creatable_misses(
        rows: list[dict], entity: str, fk_caches: dict[str, dict[str, int]]
    ) -> list[dict[str, Any]]:
        """Dedupe auto-creatable FK misses for the "will create" preview list.

        Pure (no DB); mirrors :meth:`validate_fk_rows` resolution semantics:
        empty/None values, cache hits and values that resolve via the
        existence-checked numeric-ID fallback (a bare decimal matching an
        existing id — the import links those instead of creating) are skipped.

        One entry per normalized value, order-preserving, first-seen raw
        spelling wins; ``row`` is the first row (1-based), ``row_count`` the
        number of rows naming it, ``message`` a human-readable line.
        """
        creatable = DataImportService.CREATABLE_FK_FIELDS.get(entity, set())
        checks = [
            (field, cache_key, numeric)
            for field, cache_key, _code, _action, numeric
            in DataImportService.FK_CHECK_FIELDS.get(entity, [])
            if field in creatable
        ]
        if not checks:
            return []

        id_sets = {key: set(cache.values()) for key, cache in fk_caches.items()}
        entries: dict[str, dict[str, Any]] = {}
        for idx, row in enumerate(rows, start=1):
            for field, cache_key, numeric in checks:
                raw = row.get(field)
                if raw is None:
                    continue
                value = raw if isinstance(raw, str) else str(raw)
                if not value.strip():
                    continue
                norm = DataImportService._normalize_key(value)
                if norm in (fk_caches.get(cache_key) or {}):
                    continue
                if numeric and norm.isdecimal() and int(norm) in id_sets.get(cache_key, set()):
                    continue
                entry = entries.get(norm)
                if entry is None:
                    entries[norm] = {"field": field, "value": value, "row": idx, "row_count": 1}
                else:
                    entry["row_count"] += 1

        return [
            {**entry, "message": (
                f"Will create supplier '{entry['value']}'"
                + (f" ({entry['row_count']} rows)" if entry["row_count"] > 1 else "")
            )}
            for entry in entries.values()
        ]

    @staticmethod
    def resolve_fk(cur, entity: str, natural_key: str, cache: dict) -> int | None:
        """Resolve natural key to surrogate ID using pre-built cache."""
        if not natural_key:
            return None
        norm = DataImportService._normalize_key(natural_key)
        return cache.get(norm)

    @staticmethod
    def get_or_create_supplier(cur, name: str, fk_cache: dict[str, int]) -> int | None:
        """Resolve a supplier by natural key, INSERTing it when it is missing.

        Opt-in create-missing path (armed by the "Create missing suppliers
        automatically" checkbox). Resolution mirrors :meth:`_build_fk_cache`
        (case/whitespace-tolerant, active rows only); the raw trimmed name is
        stored — never the normalized lowercase form — and ``initials`` is
        derived the same way the suppliers importer does it.

        Name reuse follows the soft-delete convention (partial unique index
        ``uq_suppliers_name_live``, mirrors ``products_sku_live_key``): a name
        held only by a SOFT-DELETED supplier is created as a fresh ACTIVE row
        and the soft-deleted row is left untouched. Degrade-to-None remains
        only for over-length names, transient DB errors and the concurrent
        active-name race.

        Runs under a SAVEPOINT so a failed INSERT degrades to None with the
        surrounding batch transaction intact. Returns None when nothing could
        be resolved or created; callers then keep their default behavior
        (products: NULL supplier, purchase orders: row skipped).
        """
        norm = DataImportService._normalize_key(name)
        if not norm:
            return None
        if norm in fk_cache:
            return fk_cache[norm]
        raw = name.strip()
        if len(raw) > 150:  # VARCHAR(150); fail fast, no savepoint churn
            return None

        cur.execute("SAVEPOINT supplier_create")
        try:
            cur.execute(
                "SELECT id FROM suppliers WHERE deleted_at IS NULL "
                "AND LOWER(TRIM(name)) = %s LIMIT 1",
                (norm,),
            )
            row = cur.fetchone()
            if row:
                supplier_id = row["id"]
            else:
                initials = "".join(part[0].upper() for part in raw.split()[:2])[:10]
                cur.execute(
                    "INSERT INTO suppliers (name, initials, location, lead_days) "
                    "VALUES (%s, %s, '', 0) RETURNING id",
                    (raw, initials),
                )
                supplier_id = cur.fetchone()["id"]
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT supplier_create")
            # Also RELEASE: rollback-only savepoints otherwise accumulate as
            # subtransactions and slow the commit past ~64 of them.
            cur.execute("RELEASE SAVEPOINT supplier_create")
            _logger.debug("Supplier auto-create failed for %r", name, exc_info=True)
            return None
        cur.execute("RELEASE SAVEPOINT supplier_create")
        fk_cache[norm] = supplier_id
        return supplier_id

    @staticmethod
    def preview_import(
        csv_content: str, entity: str, fk_caches: dict[str, dict[str, int]] | None = None,
        create_missing: bool = False,
        fk_stored: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Preview CSV import without committing changes.

        Args:
            csv_content: Raw CSV content as string
            entity: Entity type (products, suppliers, warehouses, movements, purchase_orders)
            fk_caches: Optional pre-built FK caches (from :meth:`build_fk_caches`).
                When provided, unknown natural-key references are reported as
                NON-BLOCKING warnings (import behavior is unchanged). Omit to
                skip FK validation entirely (backward compatible).
            create_missing: Opt-in flag matching the "Create missing suppliers
                automatically" checkbox. When armed, creatable supplier misses
                (see :data:`CREATABLE_FK_FIELDS`) produce a ``will_create``
                list instead of warnings, plus advisory typo hints
                (``fk_possible_typo``) when a miss closely matches an existing
                supplier name — the supplier is still created either way.
            fk_stored: Optional normalized key -> stored spelling map (from
                :meth:`build_fk_preview_data` or :meth:`build_fk_stored_values`).
                Used only by the advisory FK normalization report; omitted ->
                every natural-key match is reported as normalized.

        Rows are parsed up to ``MAX_PREVIEW_ROWS`` (10,000) to bound memory;
        ``rows_truncated`` flags when the cap was hit (``total_row_count``
        then reports the cap, not the true file size). Validation runs on
        the capped rows only.

        FK warnings share the same heuristic limitations documented on
        :meth:`validate_fk_rows` (products blank-row warning; numeric IDs
        resolve against active-row caches only).

        ``will_create`` heuristic limitations (documented, acceptable):
        - May OVERCOUNT: products rows that fail the blank sku/name check at
          import are still listed; names longer than VARCHAR(150) cannot be
          created (their warning is kept) yet still preview here; and rows
          beyond ``MAX_PREVIEW_ROWS`` are not scanned at all.
        - Purchase orders: a row with an unresolvable ``product_sku`` still
          lists its supplier, but the import skips the row before creating
          anything (never an orphan supplier).

        Returns:
            Dict with keys: headers, rows, row_count, valid, errors, warnings,
            warning_count, will_create, will_create_count, total_row_count,
            rows_truncated, duplicates, duplicate_count, fk_matches,
            fk_match_count, fk_exact_match_count, fk_normalized_match_count,
            fk_numeric_match_count
        """
        result = {
            "headers": [],
            "rows": [],
            "row_count": 0,
            "valid": False,
            "errors": [],
            "warnings": [],
            "warning_count": 0,
            "will_create": [],
            "will_create_count": 0,
            "total_row_count": 0,
            "rows_truncated": False,
            "duplicates": [],
            "duplicate_count": 0,
            "fk_matches": [],
            "fk_match_count": 0,
            "fk_exact_match_count": 0,
            "fk_normalized_match_count": 0,
            "fk_numeric_match_count": 0,
        }

        if not csv_content or not csv_content.strip():
            result["errors"].append("CSV content is empty")
            return result

        if entity not in DataImportService.EXPECTED_COLUMNS:
            result["errors"].append(f"Unknown entity type: {entity}")
            return result

        try:
            reader = csv.DictReader(io.StringIO(csv_content))
            if reader.fieldnames is None:
                result["errors"].append("CSV file appears to be empty or malformed")
                return result

            # Normalize fieldnames to lowercase and strip spaces
            provided = {f.strip().lower() for f in reader.fieldnames}
            expected_set = DataImportService.EXPECTED_COLUMNS[entity]

            # Apply aliases
            normalized_provided = set()
            for col in provided:
                normalized_provided.add(DataImportService.COLUMN_ALIASES.get(entity, {}).get(col, col))

            # Check if all expected columns are present (extra columns are allowed)
            missing = expected_set - normalized_provided
            if missing:
                result["errors"].append(f"Missing required columns: {', '.join(sorted(missing))}")
                return result

            # Read ALL rows (preview displays only the first 50) up to the
            # MAX_PREVIEW_ROWS cap that bounds memory on huge files.
            # raw_rows is parallel to all_rows (1:1, same cap) and keeps the
            # pre-strip cells the advisory FK report compares against the DB
            # spelling; it is never returned in the response.
            raw_keys = {
                field for field, *_rest in DataImportService.FK_CHECK_FIELDS.get(entity, [])
            } | set(DataImportService.DUPLICATE_KEY_FIELDS.get(entity, ()))
            all_rows = []
            raw_rows = []
            rows_truncated = False
            for row in reader:
                if len(all_rows) >= MAX_PREVIEW_ROWS:
                    rows_truncated = True
                    break
                # Normalize row keys
                normalized_row = {}
                raw_row = {}
                for k, v in row.items():
                    key = k.strip().lower()
                    key = DataImportService.COLUMN_ALIASES.get(entity, {}).get(key, key)
                    normalized_row[key] = v.strip() if isinstance(v, str) else v
                    if key in raw_keys:
                        raw_row[key] = v
                all_rows.append(normalized_row)
                raw_rows.append(raw_row)

            rows = all_rows[:50]

            result["headers"] = list(reader.fieldnames)
            result["rows"] = rows
            result["row_count"] = len(rows)
            result["total_row_count"] = len(all_rows)
            result["rows_truncated"] = rows_truncated
            result["valid"] = True

            # Advisory duplicate report: non-blocking, never touches
            # valid/warnings/errors — a failure only logs.
            try:
                duplicate_report = DataImportService.detect_duplicates(all_rows, entity)
                result["duplicates"] = duplicate_report["duplicates"]
                result["duplicate_count"] = duplicate_report["duplicate_count"]
            except Exception:
                _logger.exception("Duplicate detection failed during preview_import")

            if fk_caches is not None:
                # Advisory FK normalization report: separate try/except from the
                # validation block below so it can never invalidate the preview.
                try:
                    fk_report = DataImportService.classify_fk_matches(
                        all_rows, entity, fk_caches,
                        fk_stored=fk_stored, raw_rows=raw_rows,
                    )
                    result["fk_matches"] = fk_report["matches"]
                    result["fk_match_count"] = fk_report["match_count"]
                    result["fk_exact_match_count"] = fk_report["exact_count"]
                    result["fk_normalized_match_count"] = fk_report["normalized_count"]
                    result["fk_numeric_match_count"] = fk_report["numeric_count"]
                except Exception:
                    _logger.exception("FK match classification failed during preview_import")

                # Validation failure = incomplete preview -> blocking (valid
                # must not stay true when we cannot vouch for the rows).
                # Details go to the server log only; never leak str(e).
                try:
                    all_warnings = DataImportService.validate_fk_rows(
                        all_rows, entity, fk_caches, create_missing=create_missing
                    )
                    typo_warnings: list[dict[str, Any]] = []
                    if create_missing:
                        creates = DataImportService.classify_creatable_misses(
                            all_rows, entity, fk_caches
                        )
                        result["will_create"] = creates[:50]
                        result["will_create_count"] = len(creates)
                        # Advisory typo hints, evaluated on the DEDUPED miss
                        # list: a close existing name suggests a typo, but
                        # the supplier is still created at import either way.
                        # Only the first 50 entries are checked (the display
                        # cap below): difflib against the full cache is
                        # O(misses x names) — 10k x 2k measured ~38s.
                        cache_keys = list((fk_caches.get("suppliers") or {}).keys())
                        for entry in creates[:50]:
                            norm_value = DataImportService._normalize_key(entry["value"])
                            if len(norm_value) < 4:
                                continue
                            match = difflib.get_close_matches(
                                norm_value, cache_keys, n=1, cutoff=0.85
                            )
                            if match:
                                typo_warnings.append({
                                    "row": entry["row"],
                                    "field": entry["field"],
                                    "value": entry["value"],
                                    "error_code": "fk_possible_typo",
                                    "severity": "warning",
                                    "message": (
                                        f"Row {entry['row']}: {entry['field']} "
                                        f"'{entry['value']}' not found — will be created "
                                        f"(possible typo of '{match[0]}')"
                                    ),
                                })
                    # Base warnings first, then typo advisories: one shared
                    # display cap of 50; warning_count stays uncapped.
                    combined = all_warnings + typo_warnings
                    result["warnings"] = combined[:50]
                    result["warning_count"] = len(combined)
                except Exception:
                    _logger.exception("FK validation failed during preview_import")
                    result["errors"].append("Unexpected error during foreign-key validation")
                    result["valid"] = False

        except csv.Error as e:
            result["errors"].append(f"CSV parsing error: {str(e)}")
        except Exception:
            # Sanitized: no str(e) in the response (may embed file/DB details).
            _logger.exception("Unexpected error while parsing CSV preview")
            result["errors"].append("Unexpected error while parsing CSV")

        return result