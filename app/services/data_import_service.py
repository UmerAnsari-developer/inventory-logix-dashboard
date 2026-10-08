"""Data import service with preview functionality."""
from __future__ import annotations

import csv
import io
from typing import Any


class DataImportService:
    """Service for importing data with preview capability."""

    # Expected columns for each entity (lowercase) — matches the real schema:
    # suppliers has NO contact_email/phone/address columns.
    EXPECTED_COLUMNS = {
        "products": {"sku", "name", "unit_price", "current_stock", "reorder_point", "category", "supplier_id"},
        "suppliers": {"supplier_name", "location", "lead_days"},
        "warehouses": {"warehouse_name", "location"},
        "movements": {"product_id", "quantity", "movement_type", "reason"},
        "purchase_orders": {"supplier_id", "product_id", "quantity", "status"},
    }

    # Column aliases for flexible matching
    COLUMN_ALIASES = {
        "products": {
            "product_name": "name",
            "price": "unit_price",
            "stock": "current_stock",
            "reorder": "reorder_point",
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
        },
        "purchase_orders": {
            "qty": "quantity",
        },
    }

    @staticmethod
    def preview_import(csv_content: str, entity: str) -> dict[str, Any]:
        """Preview CSV import without committing changes.

        Args:
            csv_content: Raw CSV content as string
            entity: Entity type (products, suppliers, warehouses, movements, purchase_orders)

        Returns:
            Dict with keys: headers, rows, row_count, valid, errors
        """
        result = {
            "headers": [],
            "rows": [],
            "row_count": 0,
            "valid": False,
            "errors": [],
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

            # Read rows (limit preview to first 50 rows)
            rows = []
            for i, row in enumerate(reader):
                if i >= 50:
                    break
                # Normalize row keys
                normalized_row = {}
                for k, v in row.items():
                    key = k.strip().lower()
                    key = DataImportService.COLUMN_ALIASES.get(entity, {}).get(key, key)
                    normalized_row[key] = v.strip() if isinstance(v, str) else v
                rows.append(normalized_row)

            result["headers"] = list(reader.fieldnames)
            result["rows"] = rows
            result["row_count"] = len(rows)
            result["valid"] = True

        except csv.Error as e:
            result["errors"].append(f"CSV parsing error: {str(e)}")
        except Exception as e:
            result["errors"].append(f"Unexpected error: {str(e)}")

        return result