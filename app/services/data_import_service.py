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

    # Expected columns for each entity (lowercase) — matches the real schema:
    # suppliers has NO contact_email/phone/address columns.
    EXPECTED_COLUMNS = {
        "products": {"sku", "name", "unit_price", "current_stock", "reorder_point", "category", "supplier_name"},
        "suppliers": {"supplier_name", "location", "lead_days"},
        "warehouses": {"warehouse_name", "location"},
        "movements": {"product_sku", "quantity", "movement_type", "reason"},
        "purchase_orders": {"supplier_name", "product_sku", "quantity", "status"},
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

    @staticmethod
    def _normalize_key(value: str) -> str:
        """Normalize for case-insensitive, whitespace-tolerant matching."""
        return value.strip().lower() if isinstance(value, str) else ""

    @staticmethod
    def _build_fk_cache(cur, entity: str) -> dict[str, int]:
        """Bulk-load all active natural keys -> IDs for an entity."""
        queries = {
            "suppliers": "SELECT id, LOWER(TRIM(name)) as norm_name FROM suppliers WHERE deleted_at IS NULL",
            "products": "SELECT id, LOWER(TRIM(sku)) as norm_sku FROM products WHERE deleted_at IS NULL",
            "warehouses": "SELECT id, LOWER(TRIM(warehouse_name)) as norm_name FROM warehouses",
        }
        if entity not in queries:
            return {}
        cur.execute(queries[entity])
        rows = cur.fetchall()
        if not rows:
            return {}
        # RealDictCursor returns RealDictRow which only supports string key access
        # Use column aliases from the query
        if entity == "suppliers":
            return {row["norm_name"]: row["id"] for row in rows}
        elif entity == "products":
            return {row["norm_sku"]: row["id"] for row in rows}
        elif entity == "warehouses":
            return {row["norm_name"]: row["id"] for row in rows}
        return {}

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
            rows_truncated
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
            all_rows = []
            rows_truncated = False
            for row in reader:
                if len(all_rows) >= MAX_PREVIEW_ROWS:
                    rows_truncated = True
                    break
                # Normalize row keys
                normalized_row = {}
                for k, v in row.items():
                    key = k.strip().lower()
                    key = DataImportService.COLUMN_ALIASES.get(entity, {}).get(key, key)
                    normalized_row[key] = v.strip() if isinstance(v, str) else v
                all_rows.append(normalized_row)

            rows = all_rows[:50]

            result["headers"] = list(reader.fieldnames)
            result["rows"] = rows
            result["row_count"] = len(rows)
            result["total_row_count"] = len(all_rows)
            result["rows_truncated"] = rows_truncated
            result["valid"] = True

            if fk_caches is not None:
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