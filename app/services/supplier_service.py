"""Supplier service."""
from __future__ import annotations

from ..repositories import SupplierRepository
from ..security.validators import ValidationError, validate_string_length, validate_positive_number


class SupplierError(ValueError):
    pass


class SupplierService:
    @staticmethod
    def list_all():
        return SupplierRepository.list_all()

    @staticmethod
    def validate_payload(payload: dict) -> dict:
        try:
            payload["name"] = validate_string_length(payload.get("name", ""), "Supplier name", 2, 150)
            payload["location"] = (payload.get("location") or "").strip() or None
            payload["lead_days"] = int(payload.get("lead_days") or 0)
            if payload["lead_days"] < 0:
                raise ValidationError("Lead time cannot be negative.")
            payload["spend_amount"] = validate_positive_number(
                payload.get("spend_amount"), "YTD spend", allow_zero=True
            )
            payload["reliability"] = validate_positive_number(
                payload.get("reliability") or 90.0, "Reliability"
            )
            payload["tone"] = payload.get("tone") or "amber"
        except ValidationError as exc:
            raise SupplierError(str(exc)) from exc
        return payload

    @classmethod
    def create(cls, payload: dict) -> int:
        payload = cls.validate_payload(payload)
        return SupplierRepository.create(payload)

    @classmethod
    def update(cls, supplier_id: int, payload: dict) -> None:
        payload = cls.validate_payload(payload)
        SupplierRepository.update(supplier_id, payload)

    @staticmethod
    def delete(supplier_id: int) -> None:
        SupplierRepository.delete(supplier_id)
