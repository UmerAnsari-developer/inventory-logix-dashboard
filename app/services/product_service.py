"""Product service — orchestrates the product repository with validation."""
from __future__ import annotations

from ..repositories import ProductRepository
from ..security.validators import ValidationError, validate_positive_number, validate_string_length


class ProductError(ValueError):
    pass


class ProductService:
    @staticmethod
    def list_products(**kwargs):
        page = max(1, int(kwargs.get("page", 1)))
        per_page = min(100, max(5, int(kwargs.get("per_page", 20))))
        offset = (page - 1) * per_page
        rows, total = ProductRepository.list(
            search=kwargs.get("search", "").strip(),
            category=kwargs.get("category", "").strip(),
            warehouse=kwargs.get("warehouse", "").strip(),
            status=kwargs.get("stock_status", "").strip(),
            limit=per_page,
            offset=offset,
        )
        pages = (total + per_page - 1) // per_page
        return {
            "rows": rows,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": pages,
                "has_prev": page > 1,
                "has_next": page * per_page < total,
                "prev_num": page - 1,
                "next_num": page + 1,
            },
        }

    @staticmethod
    def validate_payload(payload: dict) -> dict:
        try:
            payload["sku"] = (
                payload.get("sku", "").strip().upper()
                if payload.get("sku")
                else payload.get("sku")
            )
            payload["name"] = validate_string_length(payload.get("name", ""), "Name", 2, 150)
            payload["category"] = (payload.get("category") or "").strip() or None
            payload["warehouse"] = (payload.get("warehouse") or "WH-Pune").strip()
            payload["unit_price"] = validate_positive_number(
                payload.get("unit_price"), "Unit price", allow_zero=True
            )
            payload["current_stock"] = int(payload.get("current_stock") or 0)
            payload["reorder_point"] = int(payload.get("reorder_point") or 0)
            if payload["current_stock"] < 0:
                raise ValidationError("Current stock cannot be negative.")
            if payload["reorder_point"] < 0:
                raise ValidationError("Reorder point cannot be negative.")
            for key in ("demand_rate", "ordering_cost", "holding_cost"):
                if payload.get(key) not in (None, ""):
                    payload[key] = validate_positive_number(payload.get(key), key.replace("_", " ").title(), allow_zero=True)
            payload["supplier_id"] = int(payload["supplier_id"]) if payload.get("supplier_id") else None
        except ValidationError as exc:
            raise ProductError(str(exc)) from exc
        return payload

    @classmethod
    def create(cls, payload: dict) -> int:
        payload = cls.validate_payload(payload)
        existing = ProductRepository.find_by_sku(payload["sku"])
        if existing:
            raise ProductError("SKU already exists.")
        return ProductRepository.create(payload)

    @classmethod
    def update(cls, product_id: int, payload: dict) -> None:
        payload = cls.validate_payload(payload)
        ProductRepository.update(product_id, payload)

    @staticmethod
    def delete(product_id: int) -> None:
        ProductRepository.delete(product_id)
